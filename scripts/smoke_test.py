from __future__ import annotations

import argparse
import asyncio

import httpx


async def main(base_url: str) -> None:
    document_id: str | None = None
    folder_id: str | None = None
    async with httpx.AsyncClient(base_url=base_url, timeout=120) as client:
        try:
            health = await client.get("/health")
            health.raise_for_status()
            print("health:", health.json())

            folder_response = await client.post("/folders", json={"name": "Smoke test"})
            folder_response.raise_for_status()
            folder = folder_response.json()
            folder_id = folder["id"]
            print("folder:", folder)

            created = await client.post(
                "/documents",
                json={
                    "title": "Smoke test: hypertension",
                    "source_type": "text",
                    "raw_text": (
                        "Артериальная гипертензия — стойкое повышение артериального давления. "
                        "Для лечения применяют ингибиторы АПФ, БРА, диуретики, блокаторы "
                        "кальциевых каналов и бета-блокаторы."
                    ),
                    "folder_id": folder_id,
                    "language": "ru",
                },
            )
            created.raise_for_status()
            document = created.json()
            document_id = document["id"]
            print("document:", document)

            index = await client.post(f"/documents/{document_id}/index", json={})
            index.raise_for_status()
            job_id = index.json()["job_id"]
            print("job:", index.json())

            for _ in range(120):
                job_response = await client.get(f"/jobs/{job_id}")
                job_response.raise_for_status()
                job = job_response.json()
                if job["status"] == "failed":
                    raise RuntimeError(job.get("error_message") or "Indexing job failed")
                if job["status"] == "completed":
                    print("job result:", job)
                    break
                await asyncio.sleep(0.5)
            else:
                raise RuntimeError("Indexing job timed out")

            answer = await client.post(
                "/answer",
                json={
                    "query": "Какие препараты применяют при артериальной гипертензии?",
                    "top_k": 5,
                    "candidate_k": 10,
                    "max_context_chunks": 3,
                    "filters": {"folder_ids": [folder_id]},
                },
            )
            answer.raise_for_status()
            payload = answer.json()
            if payload.get("used_chunks", 0) < 1:
                raise RuntimeError("Smoke test answer did not use indexed chunks")
            print("answer:", payload)
        finally:
            if document_id is not None:
                deleted = await client.delete(f"/documents/{document_id}")
                deleted.raise_for_status()
                print("cleanup: deleted", document_id)
            if folder_id is not None:
                deleted_folder = await client.delete(f"/folders/{folder_id}")
                deleted_folder.raise_for_status()
                print("cleanup: deleted folder", folder_id)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000/api/v1")
    args = parser.parse_args()
    asyncio.run(main(args.base_url))
