from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from uuid import UUID

from app.config import Settings
from app.exceptions import DocumentNotFoundError, InvalidDocumentError
from app.repositories.document_repository import DocumentInternal, DocumentRepository
from app.schemas import (
    AnswerOut,
    AnswerRequest,
    SearchFilters,
    SourceType,
    TranscriptSegment,
    VideoAskRequest,
    VideoChapter,
    VideoHighlight,
    VideoWorkspaceOut,
)
from app.services.answer_service import AnswerService


class VideoService:
    def __init__(self, *, settings: Settings, documents: DocumentRepository, answers: AnswerService) -> None:
        self._settings = settings
        self._documents = documents
        self._answers = answers
        self._client: Any | None = None
        if settings.generative_features_enabled:
            try:
                from openai import AsyncOpenAI
            except ImportError:
                self._client = None
            else:
                self._client = AsyncOpenAI(
                    api_key=settings.get_openai_api_key(),
                    base_url=settings.openai_base_url,
                    timeout=settings.openai_timeout_seconds,
                )

    async def _get_video(self, document_id: UUID) -> DocumentInternal:
        document = await self._documents.get_internal(document_id)
        if document is None:
            raise DocumentNotFoundError("Video not found", context={"document_id": str(document_id)})
        if document.source_type != SourceType.VIDEO:
            raise InvalidDocumentError("The requested document is not a video")
        return document

    async def stream_source(self, document_id: UUID) -> tuple[Path, str, int]:
        document = await self._get_video(document_id)
        if document.storage_path is None or not document.storage_path.exists():
            raise DocumentNotFoundError("Video file is missing", context={"document_id": str(document_id)})
        size = document.size_bytes or document.storage_path.stat().st_size
        return document.storage_path, document.mime_type or "video/mp4", int(size)

    async def workspace(self, document_id: UUID) -> VideoWorkspaceOut:
        document = await self._get_video(document_id)
        transcript = self._build_transcript(document)
        chapters = self._parse_chapters(document.metadata.get("chapters"))
        if not chapters and transcript:
            chapters = self._fallback_chapters(transcript)
        highlights = self._parse_highlights(document.metadata.get("highlights"))
        raw_status = str(document.metadata.get("video_analysis_status") or "pending")
        status = raw_status if raw_status in {"pending", "local", "generated", "failed"} else "pending"
        return VideoWorkspaceOut(
            document=document.to_public(),
            transcript=transcript,
            chapters=chapters,
            highlights=highlights,
            analysis_status=status,
            generative_features_enabled=self._settings.generative_features_enabled,
        )

    async def ask(self, document_id: UUID, request: VideoAskRequest) -> AnswerOut:
        await self._get_video(document_id)
        query = await self._standalone_query(request)
        return await self._answers.answer(
            AnswerRequest(
                query=query,
                top_k=self._settings.retrieval_top_k,
                candidate_k=self._settings.retrieval_candidate_k,
                use_reranker=self._settings.reranker_enabled,
                min_retrieval_score=self._settings.minimum_retrieval_score,
                filters=SearchFilters(document_ids=[document_id]),
                max_context_chunks=min(6, self._settings.retrieval_top_k),
                response_style="detailed",
                include_citations=True,
            )
        )

    async def _standalone_query(self, request: VideoAskRequest) -> str:
        if not request.history:
            return request.message
        if self._client is None:
            user_context = [item.content for item in request.history if item.role == "user"][-2:]
            return " Контекст предыдущих вопросов: ".join([*user_context, request.message])[-5000:]
        history = "\n".join(f"{item.role}: {item.content}" for item in request.history[-8:])
        response = await self._client.chat.completions.create(
            model=self._settings.openai_model,
            temperature=0.0,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Перепиши последний вопрос как самостоятельный поисковый запрос по транскрипту видео. "
                        "Используй историю только для разрешения ссылок вроде «второе», «это», «он». "
                        "Не отвечай на вопрос. Верни только запрос."
                    ),
                },
                {"role": "user", "content": f"История:\n{history}\n\nПоследний вопрос: {request.message}"},
            ],
        )
        query = (response.choices[0].message.content or "").strip()
        return query[:5000] or request.message

    @staticmethod
    def _build_transcript(document: DocumentInternal) -> list[TranscriptSegment]:
        if not document.content_text:
            return []
        spans = [
            item for item in document.metadata.get("time_spans", [])
            if isinstance(item, dict) and {"start_seconds", "end_seconds", "char_start", "char_end"} <= set(item)
        ]
        spans.sort(key=lambda item: (float(item["start_seconds"]), int(item["char_start"])))
        if not spans:
            return []
        result: list[TranscriptSegment] = []
        cursor = 0
        while cursor < len(spans):
            start = cursor
            start_seconds = float(spans[start]["start_seconds"])
            end = start
            while end + 1 < len(spans):
                candidate = spans[end + 1]
                duration = float(candidate["end_seconds"]) - start_seconds
                if duration > 18:
                    break
                end += 1
                char_end = int(spans[end]["char_end"])
                text = document.content_text[int(spans[start]["char_start"]):char_end].strip()
                if duration >= 7 and re.search(r"[.!?…][\"»)]?$", text):
                    break
            char_start = int(spans[start]["char_start"])
            char_end = int(spans[end]["char_end"])
            text = re.sub(r"\s+", " ", document.content_text[char_start:char_end]).strip()
            if text:
                result.append(
                    TranscriptSegment(
                        index=len(result),
                        start_seconds=round(start_seconds, 3),
                        end_seconds=round(float(spans[end]["end_seconds"]), 3),
                        text=text,
                    )
                )
            cursor = end + 1
        return result

    @staticmethod
    def _parse_chapters(raw: object) -> list[VideoChapter]:
        if not isinstance(raw, list):
            return []
        result = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            try:
                result.append(VideoChapter.model_validate(item))
            except Exception:
                continue
        return result

    @staticmethod
    def _parse_highlights(raw: object) -> list[VideoHighlight]:
        if not isinstance(raw, list):
            return []
        result = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            try:
                result.append(VideoHighlight.model_validate(item))
            except Exception:
                continue
        return result

    @staticmethod
    def _fallback_chapters(transcript: list[TranscriptSegment]) -> list[VideoChapter]:
        groups: list[list[TranscriptSegment]] = [[]]
        group_start = transcript[0].start_seconds
        for segment in transcript:
            if groups[-1] and segment.start_seconds - group_start >= 300:
                groups.append([])
                group_start = segment.start_seconds
            groups[-1].append(segment)
        result = []
        for index, group in enumerate(groups):
            words = group[0].text.split()[:9]
            title = " ".join(words) or f"Глава {index + 1}"
            result.append(
                VideoChapter(
                    index=index,
                    start_seconds=group[0].start_seconds,
                    end_seconds=group[-1].end_seconds,
                    title=title[:200],
                )
            )
        return result
