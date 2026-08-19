from __future__ import annotations

import asyncio
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.config import Settings
from app.exceptions import IndexingCancelledError, InvalidDocumentError
from app.services.extraction_service import TimedTextSpan, clean_text

_PUNCTUATION = frozenset(".,!?;:%)]}»")
TranscriptionProgressCallback = Callable[[float, float], None]
CancellationCheck = Callable[[], bool]


@dataclass(frozen=True, slots=True)
class TranscriptionResult:
    text: str
    time_spans: tuple[TimedTextSpan, ...]
    detected_language: str | None
    language_probability: float | None
    duration_seconds: float


class TranscriptionService:
    backend_name = "faster-whisper"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._model: Any | None = None
        self._model_lock = asyncio.Lock()
        self._transcription_lock = asyncio.Lock()

    async def _get_model(self):
        if self._settings.asr_backend == "disabled":
            raise RuntimeError("Video transcription is disabled")
        if self._model is not None:
            return self._model
        async with self._model_lock:
            if self._model is None:
                try:
                    from faster_whisper import WhisperModel
                except ImportError as exc:
                    raise RuntimeError(
                        "faster-whisper is not installed; build the image with requirements-ml.txt"
                    ) from exc
                device = "cpu" if self._settings.asr_device == "auto" else self._settings.asr_device
                self._model = await asyncio.to_thread(
                    WhisperModel,
                    self._settings.asr_model_name,
                    device=device,
                    compute_type=self._settings.asr_compute_type,
                    cpu_threads=self._settings.asr_cpu_threads,
                    num_workers=self._settings.asr_num_workers,
                )
        return self._model

    async def transcribe(
        self,
        path: Path,
        *,
        language: str | None,
        on_progress: TranscriptionProgressCallback | None = None,
        should_cancel: CancellationCheck | None = None,
    ) -> TranscriptionResult:
        async with self._transcription_lock:
            self._raise_if_cancelled(should_cancel)
            model = await self._get_model()
            return await asyncio.to_thread(
                self._transcribe_sync,
                model,
                path,
                language,
                on_progress,
                should_cancel,
            )

    def _transcribe_sync(
        self,
        model: Any,
        path: Path,
        language: str | None,
        on_progress: TranscriptionProgressCallback | None = None,
        should_cancel: CancellationCheck | None = None,
    ) -> TranscriptionResult:
        self._raise_if_cancelled(should_cancel)
        requested_language = language if language and language.lower() not in {"auto", "unknown"} else None
        segments, info = model.transcribe(
            str(path),
            language=requested_language,
            beam_size=self._settings.asr_beam_size,
            word_timestamps=True,
            vad_filter=self._settings.asr_vad_filter,
        )

        parts: list[str] = []
        spans: list[TimedTextSpan] = []
        cursor = 0
        total_duration = float(getattr(info, "duration", 0.0) or 0.0)

        if on_progress is not None and total_duration > 0:
            on_progress(0.0, total_duration)

        for segment in segments:
            self._raise_if_cancelled(should_cancel)
            words = list(segment.words or [])
            if words:
                for word in words:
                    self._raise_if_cancelled(should_cancel)
                    token = clean_text(str(word.word or "")).strip()
                    if not token:
                        continue
                    start_seconds = float(
                        word.start if word.start is not None else segment.start
                    )
                    end_seconds = float(word.end if word.end is not None else segment.end)
                    cursor = self._append_token(
                        parts,
                        spans,
                        cursor,
                        token,
                        start_seconds,
                        end_seconds,
                    )
            else:
                cursor = self._append_approximate_segment(
                    parts,
                    spans,
                    cursor,
                    clean_text(str(segment.text or "")),
                    float(segment.start),
                    float(segment.end),
                )

            if on_progress is not None and total_duration > 0:
                on_progress(min(float(segment.end), total_duration), total_duration)

        self._raise_if_cancelled(should_cancel)
        text = "".join(parts).strip()
        if not text or not spans:
            raise InvalidDocumentError("No speech could be transcribed from the uploaded video")

        shift = spans[0].char_start
        if shift:
            spans = [
                TimedTextSpan(
                    start_seconds=span.start_seconds,
                    end_seconds=span.end_seconds,
                    char_start=span.char_start - shift,
                    char_end=span.char_end - shift,
                )
                for span in spans
            ]

        duration = max(span.end_seconds for span in spans)
        probability = getattr(info, "language_probability", None)
        return TranscriptionResult(
            text=text,
            time_spans=tuple(spans),
            detected_language=getattr(info, "language", None),
            language_probability=float(probability) if probability is not None else None,
            duration_seconds=duration,
        )

    @staticmethod
    def _raise_if_cancelled(should_cancel: CancellationCheck | None) -> None:
        if should_cancel is not None and should_cancel():
            raise IndexingCancelledError("Indexing cancelled by user")

    @staticmethod
    def _append_token(
        parts: list[str],
        spans: list[TimedTextSpan],
        cursor: int,
        token: str,
        start_seconds: float,
        end_seconds: float,
    ) -> int:
        separator = "" if not parts or token[0] in _PUNCTUATION else " "
        if separator:
            parts.append(separator)
            cursor += len(separator)
        char_start = cursor
        parts.append(token)
        cursor += len(token)
        spans.append(
            TimedTextSpan(
                start_seconds=max(0.0, start_seconds),
                end_seconds=max(start_seconds, end_seconds),
                char_start=char_start,
                char_end=cursor,
            )
        )
        return cursor

    def _append_approximate_segment(
        self,
        parts: list[str],
        spans: list[TimedTextSpan],
        cursor: int,
        text: str,
        start_seconds: float,
        end_seconds: float,
    ) -> int:
        tokens = re.findall(r"\S+", text)
        if not tokens:
            return cursor
        duration = max(0.01, end_seconds - start_seconds)
        for index, token in enumerate(tokens):
            token_start = start_seconds + duration * index / len(tokens)
            token_end = start_seconds + duration * (index + 1) / len(tokens)
            cursor = self._append_token(
                parts,
                spans,
                cursor,
                token,
                token_start,
                token_end,
            )
        return cursor
