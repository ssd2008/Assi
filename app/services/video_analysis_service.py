from __future__ import annotations

import json
import logging
import math
import re
from collections.abc import Sequence
from typing import Any

from app.config import Settings
from app.services.chunking_service import TextChunk

logger = logging.getLogger(__name__)


class VideoAnalysisService:
    """Builds transcript-only chapters locally and optionally enriches them through an OpenAI-compatible API."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client: Any | None = None
        if settings.generative_features_enabled:
            try:
                from openai import AsyncOpenAI
            except ImportError:
                logger.warning("openai package is unavailable; video generative analysis disabled")
            else:
                self._client = AsyncOpenAI(
                    api_key=settings.get_openai_api_key(),
                    base_url=settings.openai_base_url,
                    timeout=settings.openai_timeout_seconds,
                )

    @property
    def generative_enabled(self) -> bool:
        return self._client is not None

    async def analyze(self, chunks: Sequence[TextChunk], vectors: Sequence[Sequence[float]]) -> dict[str, Any]:
        timed = [(chunk, vector) for chunk, vector in zip(chunks, vectors, strict=True) if chunk.time_start_seconds is not None and chunk.time_end_seconds is not None]
        if not timed:
            return {"chapters": [], "highlights": [], "video_analysis_status": "local"}

        chapter_groups = self._chapter_groups(timed)
        chapters = [
            {
                "index": index,
                "start_seconds": round(group[0][0].time_start_seconds or 0.0, 3),
                "end_seconds": round(group[-1][0].time_end_seconds or 0.0, 3),
                "title": self._fallback_title(group[0][0].text, index),
            }
            for index, group in enumerate(chapter_groups)
        ]
        highlights: list[dict[str, Any]] = []
        status = "local"

        if self._client is not None:
            try:
                chapters = await self._generate_chapter_titles(chapters, chapter_groups)
                highlights = await self._generate_highlights(timed)
                status = "generated"
            except Exception:
                logger.exception("Generative video analysis failed; keeping local chapters")

        return {"chapters": chapters, "highlights": highlights, "video_analysis_status": status}

    def _chapter_groups(self, timed: Sequence[tuple[TextChunk, Sequence[float]]]) -> list[list[tuple[TextChunk, Sequence[float]]]]:
        groups: list[list[tuple[TextChunk, Sequence[float]]]] = [[timed[0]]]
        chapter_start = timed[0][0].time_start_seconds or 0.0
        for previous, current in zip(timed, timed[1:]):
            chunk, vector = current
            now = chunk.time_start_seconds or chapter_start
            elapsed = now - chapter_start
            similarity = self._cosine(previous[1], vector)
            semantic_shift = 1.0 - similarity
            should_split = (
                elapsed >= self._settings.video_chapter_max_seconds
                or (
                    elapsed >= self._settings.video_chapter_min_seconds
                    and semantic_shift >= self._settings.video_chapter_shift_threshold
                )
            )
            if should_split:
                groups.append([])
                chapter_start = now
            groups[-1].append(current)
        return groups

    @staticmethod
    def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
        dot = sum(a * b for a, b in zip(left, right, strict=True))
        left_norm = math.sqrt(sum(value * value for value in left))
        right_norm = math.sqrt(sum(value * value for value in right))
        if left_norm == 0 or right_norm == 0:
            return 0.0
        return max(-1.0, min(1.0, dot / (left_norm * right_norm)))

    @staticmethod
    def _fallback_title(text: str, index: int) -> str:
        normalized = re.sub(r"\s+", " ", text).strip()
        sentence = re.split(r"(?<=[.!?])\s+", normalized, maxsplit=1)[0]
        words = sentence.split()
        if not words:
            return f"Глава {index + 1}"
        title = " ".join(words[:10])
        return title[:117] + "…" if len(title) > 120 else title

    async def _generate_chapter_titles(self, chapters: list[dict[str, Any]], groups: Sequence[Sequence[tuple[TextChunk, Sequence[float]]]]) -> list[dict[str, Any]]:
        blocks = []
        for chapter, group in zip(chapters, groups, strict=True):
            excerpt = " ".join(item[0].text for item in group)[:5000]
            blocks.append(f"CHAPTER {chapter['index']}\n{excerpt}")
        payload = await self._json_call(
            "Ты размечаешь медицинскую учебную лекцию. Дай короткие нейтральные названия глав. "
            "Не меняй chapter_id и не добавляй факты. Верни JSON: {\"chapters\":[{\"chapter_id\":0,\"title\":\"...\"}]}.\n\n"
            + "\n\n".join(blocks)
        )
        titles = {
            int(item["chapter_id"]): str(item["title"]).strip()
            for item in payload.get("chapters", [])
            if isinstance(item, dict) and "chapter_id" in item and item.get("title")
        }
        return [{**chapter, "title": titles.get(chapter["index"], chapter["title"])[:200]} for chapter in chapters]

    async def _generate_highlights(self, timed: Sequence[tuple[TextChunk, Sequence[float]]]) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        batch_size = 30
        for start in range(0, len(timed), batch_size):
            batch = timed[start:start + batch_size]
            lines = [f"SEGMENT {chunk.chunk_index}: {chunk.text}" for chunk, _ in batch]
            payload = await self._json_call(
                "Выбери только действительно важные учебные фрагменты медицинской лекции. "
                "Используй только указанные segment_id; таймкоды не придумывай. "
                "Верни JSON: {\"highlights\":[{\"start_segment\":1,\"end_segment\":2,\"title\":\"...\",\"reason\":\"...\",\"importance\":5}]}. "
                "Не более 3 highlights на блок.\n\n" + "\n\n".join(lines)
            )
            by_id = {chunk.chunk_index: chunk for chunk, _ in batch}
            for item in payload.get("highlights", []):
                if not isinstance(item, dict):
                    continue
                try:
                    first = by_id[int(item["start_segment"])]
                    last = by_id[int(item["end_segment"])]
                    importance = int(item.get("importance") or 3)
                except (KeyError, TypeError, ValueError):
                    continue
                result.append({
                    "index": len(result),
                    "start_seconds": round(first.time_start_seconds or 0.0, 3),
                    "end_seconds": round(last.time_end_seconds or first.time_end_seconds or 0.0, 3),
                    "title": str(item.get("title") or "Важный фрагмент")[:200],
                    "reason": str(item.get("reason") or "")[:1000],
                    "importance": max(1, min(5, importance)),
                })
        return result

    async def _json_call(self, prompt: str) -> dict[str, Any]:
        if self._client is None:
            return {}
        response = await self._client.chat.completions.create(
            model=self._settings.openai_model,
            temperature=0.1,
            messages=[
                {"role": "system", "content": "Отвечай только валидным JSON без markdown."},
                {"role": "user", "content": prompt},
            ],
        )
        content = (response.choices[0].message.content or "").strip()
        if content.startswith("```"):
            content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content, flags=re.IGNORECASE)
        parsed = json.loads(content)
        if not isinstance(parsed, dict):
            raise ValueError("OpenAI-compatible endpoint returned non-object JSON")
        return parsed
