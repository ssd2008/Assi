from __future__ import annotations

import logging
import re
import time
from abc import ABC, abstractmethod
from collections.abc import Sequence

from app.config import Settings
from app.schemas import AnswerOut, AnswerRequest, Citation, SearchResult
from app.services.search_service import SearchService

logger = logging.getLogger(__name__)


class AnswerGenerator(ABC):
    backend_name: str

    @abstractmethod
    async def generate(self, *, question: str, chunks: Sequence[SearchResult], style: str) -> str:
        raise NotImplementedError


class ExtractiveAnswerGenerator(AnswerGenerator):
    backend_name = "extractive"

    async def generate(self, *, question: str, chunks: Sequence[SearchResult], style: str) -> str:
        del question
        if not chunks:
            return "В загруженных материалах недостаточно информации для ответа."
        excerpts: list[str] = []
        max_chars = 280 if style == "brief" else 520
        for index, chunk in enumerate(chunks, start=1):
            text = re.sub(r"\s+", " ", chunk.text).strip()
            if len(text) > max_chars:
                text = text[:max_chars].rsplit(" ", 1)[0] + "…"
            excerpts.append(f"[{index}] {text}")
        intro = "Ниже приведены наиболее релевантные фрагменты учебных материалов:" if style != "study_notes" else "Конспект по найденным материалам:"
        return intro + "\n\n" + "\n\n".join(excerpts)


class OpenAIAnswerGenerator(AnswerGenerator):
    backend_name = "openai"

    def __init__(self, settings: Settings) -> None:
        try:
            from openai import AsyncOpenAI
        except ImportError as exc:
            raise RuntimeError("The openai package is not installed") from exc
        self._client = AsyncOpenAI(
            api_key=settings.get_openai_api_key(),
            base_url=settings.openai_base_url,
            timeout=settings.openai_timeout_seconds,
        )
        self._model = settings.openai_model

    async def generate(self, *, question: str, chunks: Sequence[SearchResult], style: str) -> str:
        context = "\n\n".join(
            f"SOURCE [{index}] ({chunk.document_title}; {chunk.time_start_seconds or '-'}–{chunk.time_end_seconds or '-'}):\n{chunk.text}"
            for index, chunk in enumerate(chunks, start=1)
        )
        response = await self._client.chat.completions.create(
            model=self._model,
            temperature=0.2,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Ты образовательный медицинский ассистент. Отвечай только по переданным "
                        "источникам. Не ставь диагноз и не назначай лечение. Ссылайся на источники "
                        "маркерами [1], [2]. Если данных недостаточно, скажи об этом прямо."
                    ),
                },
                {"role": "user", "content": f"Стиль ответа: {style}\n\nВопрос: {question}\n\n{context}"},
            ],
        )
        answer = (response.choices[0].message.content or "").strip()
        if not answer:
            raise RuntimeError("OpenAI-compatible endpoint returned an empty answer")
        return answer


class AnswerService:
    def __init__(self, *, settings: Settings, search_service: SearchService, generator: AnswerGenerator, fallback_generator: ExtractiveAnswerGenerator) -> None:
        self._settings = settings
        self._search = search_service
        self._generator = generator
        self._fallback = fallback_generator

    @property
    def backend_name(self) -> str:
        return self._generator.backend_name

    async def answer(self, request: AnswerRequest) -> AnswerOut:
        started = time.perf_counter()
        search_response = await self._search.search(request)
        chunks = search_response.results[:request.max_context_chunks]
        limitations: list[str] = []
        if not chunks:
            answer = "В загруженных материалах недостаточно информации для ответа."
            limitations.append("По запросу не найдено релевантных фрагментов.")
        else:
            try:
                answer = await self._generator.generate(question=request.query, chunks=chunks, style=request.response_style)
            except Exception:
                logger.exception("Primary answer generator failed; using extractive fallback")
                answer = await self._fallback.generate(question=request.query, chunks=chunks, style=request.response_style)
                limitations.append("Генеративная модель была недоступна; возвращён extractive-ответ.")
        if self._generator.backend_name == "extractive":
            limitations.append("Ответ собран из найденных фрагментов без генеративной переформулировки.")
        citations = [
            Citation(
                number=index, document_id=chunk.document_id, chunk_id=chunk.chunk_id,
                document_title=chunk.document_title, quote=chunk.text[:1000],
                page_start=chunk.page_start, page_end=chunk.page_end,
                time_start_seconds=chunk.time_start_seconds, time_end_seconds=chunk.time_end_seconds,
                section_title=chunk.section_title, char_start=chunk.char_start, char_end=chunk.char_end,
                retrieval_score=chunk.retrieval_score, rerank_score=chunk.rerank_score,
            )
            for index, chunk in enumerate(chunks, start=1)
        ] if request.include_citations else []
        return AnswerOut(
            answer=answer,
            citations=citations,
            confidence=self._confidence(chunks),
            limitations=limitations,
            safety_notes=[
                "Ответ предназначен для обучения и не заменяет клиническое решение врача.",
                "Проверяйте критически важные сведения по первичному источнику.",
            ],
            used_chunks=len(chunks),
            took_ms=(time.perf_counter() - started) * 1000,
        )

    @staticmethod
    def _confidence(chunks: Sequence[SearchResult]) -> float:
        if not chunks:
            return 0.0
        top = list(chunks[:3])
        relevance = sum(chunk.final_score for chunk in top) / len(top)
        coverage = min(1.0, len(chunks) / 3.0)
        return round(max(0.0, min(1.0, 0.85 * relevance + 0.15 * coverage)), 4)


def create_answer_generator(settings: Settings) -> AnswerGenerator:
    if settings.answer_backend == "openai":
        return OpenAIAnswerGenerator(settings)
    return ExtractiveAnswerGenerator()
