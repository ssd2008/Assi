from uuid import uuid4

from app.qdrant_schema import ChunkPayload, calculate_content_hash
from app.schemas import SourceType


def test_video_payload_serializes_timestamps() -> None:
    payload = ChunkPayload(
        document_id=uuid4(),
        chunk_index=0,
        text="фрагмент лекции",
        token_count=2,
        char_start=0,
        char_end=15,
        time_start_seconds=12.5,
        time_end_seconds=21.8,
        document_title="Лекция",
        source_type=SourceType.VIDEO,
        folder_id=uuid4(),
        folder_name="Кардиология",
        language="ru",
        content_hash=calculate_content_hash("фрагмент лекции"),
    )
    serialized = payload.to_qdrant_payload()
    assert serialized["time_start_seconds"] == 12.5
    assert serialized["time_end_seconds"] == 21.8
