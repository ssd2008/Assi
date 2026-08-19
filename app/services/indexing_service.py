from __future__ import annotations

import asyncio
import logging
from threading import Event
from uuid import UUID

from app.config import Settings
from app.exceptions import DocumentNotFoundError, IndexingCancelledError, IndexingError
from app.qdrant_schema import ChunkPayload, build_chunk_point_id, calculate_content_hash
from app.repositories.document_repository import DocumentRepository
from app.repositories.folder_repository import FolderRepository
from app.repositories.job_repository import JobRepository
from app.repositories.vector_repository import VectorChunk, VectorRepository
from app.schemas import DocumentStatus, SourceType
from app.services.chunking_service import ChunkingService
from app.services.embedding_service import EmbeddingService
from app.services.extraction_service import ExtractedDocument, PageSpan, TimedTextSpan
from app.services.indexing_cancellation import IndexingCancellationRegistry
from app.services.transcription_service import TranscriptionService
from app.services.video_analysis_service import VideoAnalysisService

logger = logging.getLogger(__name__)


class IndexingService:
    def __init__(
        self,
        *,
        settings: Settings,
        documents: DocumentRepository,
        folders: FolderRepository,
        jobs: JobRepository,
        vectors: VectorRepository,
        chunking: ChunkingService,
        embeddings: EmbeddingService,
        transcription: TranscriptionService,
        video_analysis: VideoAnalysisService,
        cancellation: IndexingCancellationRegistry | None = None,
    ) -> None:
        self._settings = settings
        self._documents = documents
        self._folders = folders
        self._jobs = jobs
        self._vectors = vectors
        self._chunking = chunking
        self._embeddings = embeddings
        self._transcription = transcription
        self._video_analysis = video_analysis
        self._cancellation = cancellation or IndexingCancellationRegistry()

    async def create_job(self, document_id: UUID, *, chunk_size: int | None, chunk_overlap: int | None):
        document = await self._documents.get_internal(document_id)
        if document is None:
            raise DocumentNotFoundError("Document not found", context={"document_id": str(document_id)})
        size = chunk_size or self._settings.chunk_size_tokens
        overlap = self._settings.chunk_overlap_tokens if chunk_overlap is None else chunk_overlap
        if overlap >= size:
            raise ValueError("chunk_overlap must be smaller than chunk_size")
        job = await self._jobs.create(document_id, chunk_size=size, chunk_overlap=overlap)
        self._cancellation.prepare(job.id, document_id)
        return job

    async def cancel_document(self, document_id: UUID) -> None:
        await self._cancellation.cancel_document(document_id)

    async def run_job(self, job_id: UUID, document_id: UUID) -> None:
        cancel_event = self._cancellation.get_cancel_event(job_id, document_id)
        try:
            self._raise_if_cancelled(cancel_event)
            job = await self._jobs.get(job_id)
            if job is None:
                raise IndexingError("Indexing job disappeared before execution")
            await self._jobs.mark_running(job_id)
            await self._documents.update_status(document_id, DocumentStatus.PROCESSING)
            document = await self._documents.get_internal(document_id)
            if document is None:
                raise DocumentNotFoundError("Document not found")
            folder = await self._folders.get(document.folder_id)
            if folder is None:
                raise IndexingError("Document folder does not exist")
            self._raise_if_cancelled(cancel_event)

            if document.source_type == SourceType.VIDEO and not document.content_text:
                if document.storage_path is None:
                    raise IndexingError("Video file is missing from storage")
                await self._jobs.update_progress(job_id, 5, stage="transcribing", stage_detail="Распознавание речи: подготовка аудио")
                transcription = await self._transcribe_video(job_id, document.storage_path, language=document.language, cancel_event=cancel_event)
                self._raise_if_cancelled(cancel_event)
                metadata = {
                    **document.metadata,
                    "transcription_status": "completed",
                    "asr_model": self._settings.asr_model_name,
                    "detected_language": transcription.detected_language,
                    "language_probability": transcription.language_probability,
                    "duration_seconds": transcription.duration_seconds,
                    "time_spans": [
                        {
                            "start_seconds": span.start_seconds,
                            "end_seconds": span.end_seconds,
                            "char_start": span.char_start,
                            "char_end": span.char_end,
                        }
                        for span in transcription.time_spans
                    ],
                }
                await self._documents.update_extracted_content(document.id, content_text=transcription.text, metadata=metadata)
                document = await self._documents.get_internal(document_id)
                if document is None:
                    raise DocumentNotFoundError("Document disappeared after transcription")
                await self._jobs.update_progress(job_id, 20, stage="transcribed", stage_detail="Распознавание речи завершено")

            self._raise_if_cancelled(cancel_event)
            if not document.content_text:
                raise IndexingError("Document has no extracted text")

            await self._jobs.update_progress(job_id, 22, stage="chunking", stage_detail="Разбиение материала на фрагменты")
            page_spans = tuple(
                PageSpan(**item)
                for item in document.metadata.get("page_spans", [])
                if isinstance(item, dict) and {"page_number", "char_start", "char_end"} <= set(item)
            )
            time_spans = tuple(
                TimedTextSpan(**item)
                for item in document.metadata.get("time_spans", [])
                if isinstance(item, dict) and {"start_seconds", "end_seconds", "char_start", "char_end"} <= set(item)
            )
            is_video = document.source_type == SourceType.VIDEO
            chunks = self._chunking.split(
                ExtractedDocument(text=document.content_text, page_spans=page_spans, time_spans=time_spans),
                chunk_size=job.chunk_size,
                chunk_overlap=job.chunk_overlap,
                max_time_seconds=self._settings.video_chunk_duration_seconds if is_video else None,
                time_overlap_seconds=self._settings.video_chunk_overlap_seconds if is_video else 0.0,
            )
            if not chunks:
                raise IndexingError("Chunking produced no chunks")
            self._raise_if_cancelled(cancel_event)

            await self._jobs.update_progress(job_id, 30, stage="embedding", stage_detail=f"Создание embeddings для {len(chunks)} фрагментов")
            embeddings = await self._embeddings.embed_documents([chunk.text for chunk in chunks])
            self._raise_if_cancelled(cancel_event)

            document = await self._documents.get_internal(document_id)
            if document is None:
                raise DocumentNotFoundError("Document disappeared during indexing")
            folder = await self._folders.get(document.folder_id)
            if folder is None:
                raise IndexingError("Document folder does not exist")

            await self._jobs.update_progress(job_id, 75, stage="storing", stage_detail="Сохранение векторного индекса в Qdrant")
            vector_chunks: list[VectorChunk] = []
            for chunk, vector in zip(chunks, embeddings, strict=True):
                content_hash = calculate_content_hash(chunk.text)
                payload = ChunkPayload(
                    document_id=document.id,
                    folder_id=document.folder_id,
                    folder_name=folder.name,
                    chunk_index=chunk.chunk_index,
                    text=chunk.text,
                    token_count=chunk.token_count,
                    char_start=chunk.char_start,
                    char_end=chunk.char_end,
                    page_start=chunk.page_start,
                    page_end=chunk.page_end,
                    time_start_seconds=chunk.time_start_seconds,
                    time_end_seconds=chunk.time_end_seconds,
                    section_title=chunk.section_title,
                    document_title=document.title,
                    source_type=document.source_type,
                    source_url=document.source_url,
                    lecture_date=document.lecture_date,
                    lecture_date_ordinal=document.lecture_date.toordinal() if document.lecture_date else None,
                    language=document.language,
                    content_hash=content_hash,
                )
                vector_chunks.append(
                    VectorChunk(
                        point_id=build_chunk_point_id(document.id, chunk.chunk_index, content_hash),
                        vector=vector,
                        payload=payload,
                    )
                )

            count = await self._vectors.replace_document_chunks(document.id, vector_chunks)
            self._raise_if_cancelled(cancel_event)

            if is_video:
                await self._jobs.update_progress(job_id, 86, stage="video_analysis", stage_detail="Формирование глав и хайлайтов")
                analysis = await self._video_analysis.analyze(chunks, embeddings)
                await self._documents.update_metadata(document.id, {**document.metadata, **analysis})

            await self._jobs.update_progress(job_id, 90, stage="finalizing", stage_detail="Завершение индексации")
            await self._documents.finish_indexing(document.id, count)
            await self._jobs.complete(
                job_id,
                {
                    "document_id": str(document.id),
                    "chunks_count": count,
                    "embedding_backend": self._embeddings.backend_name,
                    "asr_backend": self._transcription.backend_name if is_video else None,
                    "duration_seconds": document.metadata.get("duration_seconds"),
                    "video_analysis": is_video,
                    "generative_video_analysis": is_video and self._video_analysis.generative_enabled,
                },
            )
        except IndexingCancelledError:
            logger.info("Indexing job %s cancelled", job_id)
            await self._vectors.delete_document(document_id)
            await self._jobs.cancel(job_id)
            await self._documents.update_status(document_id, DocumentStatus.UPLOADED)
        except Exception as exc:
            logger.exception("Indexing job %s failed", job_id)
            message = str(exc) or exc.__class__.__name__
            await self._jobs.fail(job_id, message)
            await self._documents.update_status(document_id, DocumentStatus.FAILED, error_message=message)
        finally:
            self._cancellation.finish(job_id)

    async def _transcribe_video(self, job_id: UUID, path, *, language: str, cancel_event: Event):
        loop = asyncio.get_running_loop()
        last_progress = 4
        last_reported_second = -30.0

        def report_progress(processed_seconds: float, total_seconds: float) -> None:
            nonlocal last_progress, last_reported_second
            if total_seconds <= 0:
                return
            ratio = min(max(processed_seconds / total_seconds, 0.0), 1.0)
            progress = 5 + min(14, int(ratio * 15))
            if progress <= last_progress and processed_seconds - last_reported_second < 30:
                return
            last_progress = progress
            last_reported_second = processed_seconds
            detail = f"Распознавание речи: {self._format_duration(processed_seconds)} из {self._format_duration(total_seconds)}"
            future = asyncio.run_coroutine_threadsafe(
                self._jobs.update_progress(job_id, progress, stage="transcribing", stage_detail=detail), loop
            )
            future.result(timeout=10)

        return await self._transcription.transcribe(path, language=language, on_progress=report_progress, should_cancel=cancel_event.is_set)

    @staticmethod
    def _raise_if_cancelled(cancel_event: Event) -> None:
        if cancel_event.is_set():
            raise IndexingCancelledError("Indexing cancelled by user")

    @staticmethod
    def _format_duration(seconds: float) -> str:
        total = max(0, int(seconds))
        hours, remainder = divmod(total, 3600)
        minutes, secs = divmod(remainder, 60)
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
