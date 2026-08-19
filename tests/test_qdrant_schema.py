from datetime import date
from uuid import uuid4

from app.qdrant_schema import ChunkPayload, build_chunk_point_id, calculate_content_hash
from app.schemas import SourceType


def test_chunk_point_id_is_deterministic() -> None:
    document_id = uuid4()
    content_hash = calculate_content_hash("text")
    assert build_chunk_point_id(document_id, 0, content_hash) == build_chunk_point_id(document_id, 0, content_hash)


def test_payload_serializes_uuid_and_date() -> None:
    lecture_date = date(2026, 7, 14)
    payload = ChunkPayload(
        document_id=uuid4(),
        chunk_index=0,
        text="text",
        token_count=1,
        char_start=0,
        char_end=4,
        document_title="title",
        source_type=SourceType.TEXT,
        folder_id=uuid4(),
        folder_name="Кардиология",
        lecture_date=lecture_date,
        lecture_date_ordinal=lecture_date.toordinal(),
        language="ru",
        content_hash=calculate_content_hash("text"),
    )
    serialized = payload.to_qdrant_payload()
    assert isinstance(serialized["document_id"], str)
    assert isinstance(serialized["folder_id"], str)
    assert serialized["lecture_date"] == "2026-07-14"
