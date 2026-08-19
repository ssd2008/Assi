from __future__ import annotations

from dataclasses import dataclass

import asyncpg
from qdrant_client import AsyncQdrantClient

from app.config import Settings
from app.database import create_database_pool
from app.repositories.document_repository import DocumentRepository
from app.repositories.feedback_repository import FeedbackRepository
from app.repositories.folder_repository import FolderRepository
from app.repositories.job_repository import JobRepository
from app.repositories.vector_repository import VectorRepository
from app.services.answer_service import AnswerService, ExtractiveAnswerGenerator, create_answer_generator
from app.services.chunking_service import ChunkingService
from app.services.document_service import DocumentService
from app.services.embedding_service import EmbeddingService, create_embedding_service
from app.services.extraction_service import ExtractionService
from app.services.folder_service import FolderService
from app.services.indexing_cancellation import IndexingCancellationRegistry
from app.services.indexing_service import IndexingService
from app.services.rerank_service import RerankService, create_rerank_service
from app.services.search_service import SearchService
from app.services.transcription_service import TranscriptionService
from app.services.video_analysis_service import VideoAnalysisService
from app.services.video_service import VideoService


@dataclass(slots=True)
class AppContainer:
    settings: Settings
    pool: asyncpg.Pool
    qdrant_client: AsyncQdrantClient
    documents: DocumentRepository
    folders: FolderRepository
    jobs: JobRepository
    feedback: FeedbackRepository
    vectors: VectorRepository
    embeddings: EmbeddingService
    reranker: RerankService
    transcription: TranscriptionService
    document_service: DocumentService
    folder_service: FolderService
    indexing_service: IndexingService
    search_service: SearchService
    answer_service: AnswerService
    video_service: VideoService

    async def close(self) -> None:
        await self.qdrant_client.close()
        await self.pool.close()


async def create_container(settings: Settings) -> AppContainer:
    pool = await create_database_pool(settings)
    qdrant_client: AsyncQdrantClient | None = None
    try:
        qdrant_client = AsyncQdrantClient(
            url=settings.qdrant_url,
            api_key=settings.get_qdrant_api_key(),
            timeout=settings.qdrant_timeout_seconds,
        )
        documents = DocumentRepository(pool)
        folders = FolderRepository(pool)
        jobs = JobRepository(pool)
        feedback = FeedbackRepository(pool)
        vectors = VectorRepository(
            qdrant_client,
            collection_name=settings.qdrant_collection_name,
            vector_size=settings.embedding_dimension,
            upsert_batch_size=settings.qdrant_upsert_batch_size,
        )
        await vectors.ensure_collection()
        extraction = ExtractionService(settings)
        chunking = ChunkingService()
        embeddings = create_embedding_service(settings)
        reranker = create_rerank_service(settings)
        transcription = TranscriptionService(settings)
        video_analysis = VideoAnalysisService(settings)
        cancellation = IndexingCancellationRegistry()
        document_service = DocumentService(
            settings=settings,
            repository=documents,
            folders=folders,
            vector_repository=vectors,
            extraction_service=extraction,
        )
        folder_service = FolderService(repository=folders, vectors=vectors)
        indexing_service = IndexingService(
            settings=settings,
            documents=documents,
            folders=folders,
            jobs=jobs,
            vectors=vectors,
            chunking=chunking,
            embeddings=embeddings,
            transcription=transcription,
            video_analysis=video_analysis,
            cancellation=cancellation,
        )
        await indexing_service.recover_interrupted_jobs()
        search_service = SearchService(
            vectors=vectors,
            embeddings=embeddings,
            reranker=reranker,
            reranker_enabled=settings.reranker_enabled,
            video_context_neighbor_chunks=settings.video_context_neighbor_chunks,
        )
        fallback = ExtractiveAnswerGenerator()
        answer_service = AnswerService(
            settings=settings,
            search_service=search_service,
            generator=create_answer_generator(settings),
            fallback_generator=fallback,
        )
        video_service = VideoService(settings=settings, documents=documents, answers=answer_service)
        return AppContainer(
            settings=settings,
            pool=pool,
            qdrant_client=qdrant_client,
            documents=documents,
            folders=folders,
            jobs=jobs,
            feedback=feedback,
            vectors=vectors,
            embeddings=embeddings,
            reranker=reranker,
            transcription=transcription,
            document_service=document_service,
            folder_service=folder_service,
            indexing_service=indexing_service,
            search_service=search_service,
            answer_service=answer_service,
            video_service=video_service,
        )
    except Exception:
        if qdrant_client is not None:
            await qdrant_client.close()
        await pool.close()
        raise
