from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.schemas import AnswerRequest, DocumentCreate, QueryRequest, SourceType


def test_document_requires_folder() -> None:
    with pytest.raises(ValidationError):
        DocumentCreate(title="x", source_type=SourceType.TEXT, raw_text="text")


def test_text_document_requires_text() -> None:
    with pytest.raises(ValidationError):
        DocumentCreate(title="x", source_type=SourceType.TEXT, folder_id=uuid4())


def test_url_document_rejects_raw_text() -> None:
    with pytest.raises(ValidationError):
        DocumentCreate(
            title="x",
            source_type=SourceType.URL,
            folder_id=uuid4(),
            source_url="https://example.com",
            raw_text="not allowed",
        )


def test_query_uses_dense_retrieval_by_default() -> None:
    request = QueryRequest(query="test query")
    assert request.use_reranker is False


def test_answer_context_cannot_exceed_top_k() -> None:
    with pytest.raises(ValidationError):
        AnswerRequest(query="test query", top_k=2, candidate_k=3, max_context_chunks=3)
