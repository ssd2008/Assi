from datetime import date
from uuid import uuid4

import pytest

from app.config import Settings
from app.schemas import AnswerRequest, SearchResponse, SearchResult, SourceType
from app.services.answer_service import AnswerService, ExtractiveAnswerGenerator


class FakeSearchService:
    async def search(self, request):
        folder_id = uuid4()
        return SearchResponse(
            query=request.query,
            total_candidates=1,
            took_ms=1,
            results=[
                SearchResult(
                    rank=1,
                    chunk_id=uuid4(),
                    document_id=uuid4(),
                    document_title="Lecture",
                    chunk_index=0,
                    text="Ингибиторы АПФ применяются при артериальной гипертензии.",
                    source_type=SourceType.TEXT,
                    folder_id=folder_id,
                    folder_name="Кардиология",
                    lecture_date=date(2026, 1, 1),
                    language="ru",
                    char_start=0,
                    char_end=60,
                    retrieval_score=0.8,
                    rerank_score=0.9,
                    final_score=0.8875,
                )
            ],
        )


@pytest.mark.asyncio
async def test_answer_contains_citation_and_safety_note() -> None:
    generator = ExtractiveAnswerGenerator()
    service = AnswerService(
        settings=Settings(),
        search_service=FakeSearchService(),
        generator=generator,
        fallback_generator=generator,
    )
    result = await service.answer(
        AnswerRequest(
            query="Что применяют при гипертензии?",
            top_k=3,
            candidate_k=5,
            max_context_chunks=1,
        )
    )
    assert result.used_chunks == 1
    assert result.citations[0].document_title == "Lecture"
    assert result.confidence > 0.5
    assert result.safety_notes
