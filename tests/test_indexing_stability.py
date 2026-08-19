from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

from app.schemas import DocumentStatus
from app.services.indexing_service import IndexingService


class FakeJobs:
    def __init__(self, interrupted_document_ids: list) -> None:
        self.interrupted_document_ids = interrupted_document_ids

    async def cancel_interrupted(self):
        return self.interrupted_document_ids


class FakeDocuments:
    def __init__(self, processing_document_ids: list) -> None:
        self.processing_document_ids = processing_document_ids
        self.status_updates: list[tuple] = []

    async def list_documents(self, **_: Any):
        return [SimpleNamespace(id=document_id) for document_id in self.processing_document_ids]

    async def get_internal(self, document_id):
        if document_id not in self.processing_document_ids:
            return None
        return SimpleNamespace(id=document_id, status=DocumentStatus.PROCESSING)

    async def update_status(self, document_id, status):
        self.status_updates.append((document_id, status))
        return None


class FakeVectors:
    def __init__(self) -> None:
        self.deleted_document_ids: list = []

    async def delete_document(self, document_id) -> None:
        self.deleted_document_ids.append(document_id)


def make_service(*, jobs: Any, documents: Any, vectors: Any) -> IndexingService:
    return IndexingService(
        settings=object(),  # type: ignore[arg-type]
        documents=documents,
        folders=object(),  # type: ignore[arg-type]
        jobs=jobs,
        vectors=vectors,
        chunking=object(),  # type: ignore[arg-type]
        embeddings=object(),  # type: ignore[arg-type]
        transcription=object(),  # type: ignore[arg-type]
        video_analysis=object(),  # type: ignore[arg-type]
    )


def test_recover_interrupted_jobs_cleans_vectors_and_resets_processing_documents() -> None:
    async def scenario() -> None:
        running_document_id = uuid4()
        orphan_processing_document_id = uuid4()
        jobs = FakeJobs([running_document_id])
        documents = FakeDocuments([running_document_id, orphan_processing_document_id])
        vectors = FakeVectors()
        service = make_service(jobs=jobs, documents=documents, vectors=vectors)

        recovered = await service.recover_interrupted_jobs()

        assert recovered == 2
        assert set(vectors.deleted_document_ids) == {
            running_document_id,
            orphan_processing_document_id,
        }
        assert set(documents.status_updates) == {
            (running_document_id, DocumentStatus.UPLOADED),
            (orphan_processing_document_id, DocumentStatus.UPLOADED),
        }

    asyncio.run(scenario())


def test_run_job_allows_only_one_indexing_pipeline_at_a_time() -> None:
    async def scenario() -> None:
        service = make_service(jobs=object(), documents=object(), vectors=object())
        active = 0
        maximum_active = 0

        async def fake_serialized_run(_job_id, _document_id) -> None:
            nonlocal active, maximum_active
            active += 1
            maximum_active = max(maximum_active, active)
            await asyncio.sleep(0.02)
            active -= 1

        service._run_job_serialized = fake_serialized_run  # type: ignore[method-assign]
        await asyncio.gather(
            service.run_job(uuid4(), uuid4()),
            service.run_job(uuid4(), uuid4()),
        )

        assert maximum_active == 1

    asyncio.run(scenario())
