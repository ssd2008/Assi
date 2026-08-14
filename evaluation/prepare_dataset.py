from __future__ import annotations

import argparse
import html
import json
import re
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET
from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from evaluation.benchmark_lib import write_jsonl

MEDQUAD_COMMIT = "577bd37b96c02d1833b2c9eed2de9f96964e96cb"
MEDQUAD_LICENSE = "CC BY 4.0"
BUNDLED_SOURCE_DIR = Path(__file__).resolve().parent / "fixtures" / "medquad"
DEFAULT_DOWNLOAD_ATTEMPTS = 4


@dataclass(frozen=True)
class SourceSpec:
    document_id: str
    title: str
    path: str

    @property
    def raw_url(self) -> str:
        return f"https://raw.githubusercontent.com/abachaa/MedQuAD/{MEDQUAD_COMMIT}/{self.path}"

    @property
    def api_url(self) -> str:
        return (
            "https://api.github.com/repos/abachaa/MedQuAD/contents/"
            f"{self.path}?ref={MEDQUAD_COMMIT}"
        )

    @property
    def fixture_path(self) -> Path:
        return BUNDLED_SOURCE_DIR / Path(self.path).name


SOURCE_SPECS = (
    SourceSpec("niddk-acromegaly", "Acromegaly", "5_NIDDK_QA/0000001.xml"),
    SourceSpec("niddk-celiac-disease", "Celiac Disease", "5_NIDDK_QA/0000088.xml"),
    SourceSpec("niddk-crohns-disease", "Crohn's Disease", "5_NIDDK_QA/0000093.xml"),
)

_TEMPLATE_MAP: dict[str, tuple[str, ...]] = {
    "information": (
        "Define {focus}.",
        "What is the medical meaning of {focus}?",
        "Give an overview of {focus}.",
    ),
    "symptoms": (
        "Which signs and symptoms are associated with {focus}?",
        "How can {focus} present clinically?",
        "What manifestations can occur in {focus}?",
    ),
    "causes": (
        "What factors cause or contribute to {focus}?",
        "Describe the causes of {focus}.",
        "What is known about the etiology of {focus}?",
    ),
    "frequency": (
        "How common is {focus}?",
        "What is the prevalence or incidence of {focus}?",
        "How frequently does {focus} occur?",
    ),
    "exams and tests": (
        "How is {focus} diagnosed?",
        "Which examinations and tests are used for {focus}?",
        "Describe the diagnostic work-up for {focus}.",
    ),
    "treatment": (
        "How is {focus} treated?",
        "Which treatment options are used for {focus}?",
        "Describe the management of {focus}.",
    ),
    "risk factors": (
        "What increases the risk of {focus}?",
        "Which risk factors are associated with {focus}?",
        "Who is more likely to develop {focus}?",
    ),
    "prevention": (
        "Can {focus} be prevented?",
        "Which measures may prevent {focus}?",
        "How can the risk of {focus} be reduced?",
    ),
    "complications": (
        "What complications can result from {focus}?",
        "Which long-term problems are associated with {focus}?",
        "What adverse outcomes can {focus} cause?",
    ),
}


def _normalize_text(value: str | None) -> str:
    if not value:
        return ""
    value = html.unescape(value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def _validate_xml(payload: bytes, source: str) -> None:
    if not payload:
        raise ValueError(f"Empty XML payload from {source}")
    try:
        root = ET.fromstring(payload)
    except ET.ParseError as exc:
        raise ValueError(f"Invalid XML payload from {source}: {exc}") from exc
    if root.tag != "Document" or root.find("QAPairs") is None:
        raise ValueError(f"Unexpected MedQuAD XML structure in {source}")


def _download(
    spec: SourceSpec,
    timeout_seconds: int = 60,
    attempts: int = DEFAULT_DOWNLOAD_ATTEMPTS,
    base_delay_seconds: float = 1.0,
) -> bytes:
    if attempts < 1:
        raise ValueError("attempts must be at least 1")

    endpoints = (
        (spec.raw_url, "application/octet-stream"),
        (spec.api_url, "application/vnd.github.raw+json"),
    )
    errors: list[str] = []

    for attempt in range(1, attempts + 1):
        for url, accept in endpoints:
            request = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "Assi-evaluation/1.0",
                    "Accept": accept,
                    "Accept-Encoding": "identity",
                    "Connection": "close",
                },
            )
            try:
                with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                    payload = response.read()
                _validate_xml(payload, url)
                return payload
            except Exception as exc:  # Network and TLS errors vary by platform.
                errors.append(f"attempt {attempt}, {url}: {type(exc).__name__}: {exc}")

        if attempt < attempts:
            delay = base_delay_seconds * (2 ** (attempt - 1))
            print(
                f"MedQuAD download failed (attempt {attempt}/{attempts}); retrying in {delay:.1f}s...",
                file=sys.stderr,
            )
            time.sleep(delay)

    details = "\n".join(errors[-min(len(errors), 8) :])
    raise RuntimeError(
        f"Could not download MedQuAD source {spec.path} after {attempts} attempts. "
        "Both raw.githubusercontent.com and the GitHub Contents API failed.\n"
        f"{details}"
    )


def _read_validated(path: Path) -> bytes:
    payload = path.read_bytes()
    _validate_xml(payload, str(path))
    return payload


def _atomic_write(path: Path, payload: bytes) -> None:
    temporary_path = path.with_suffix(path.suffix + ".tmp")
    try:
        temporary_path.write_bytes(payload)
        temporary_path.replace(path)
    finally:
        temporary_path.unlink(missing_ok=True)


def _load_source(spec: SourceSpec, cache_dir: Path, *, refresh: bool) -> bytes:
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / Path(spec.path).name

    if not refresh and cache_path.exists():
        try:
            return _read_validated(cache_path)
        except ValueError as exc:
            print(f"Ignoring corrupt cached source {cache_path}: {exc}", file=sys.stderr)
            cache_path.unlink(missing_ok=True)

    if not refresh and spec.fixture_path.exists():
        payload = _read_validated(spec.fixture_path)
        _atomic_write(cache_path, payload)
        return payload

    payload = _download(spec)
    _atomic_write(cache_path, payload)
    return payload


def _question_variants(original: str, question_type: str, focus: str) -> list[tuple[str, str]]:
    variants = [(original, "medquad_original")]
    templates = _TEMPLATE_MAP.get(
        question_type.lower(),
        (
            "What should a medical learner know about {focus} in relation to {question_type}?",
            "Explain the {question_type} aspects of {focus}.",
            "Summarize {question_type} information for {focus}.",
        ),
    )
    variants.extend(
        (template.format(focus=focus, question_type=question_type), "template_paraphrase")
        for template in templates
    )
    return variants


def _parse_document(spec: SourceSpec, xml_bytes: bytes) -> tuple[list[dict], list[dict]]:
    root = ET.fromstring(xml_bytes)
    focus = _normalize_text(root.findtext("Focus")) or spec.title
    source_url = root.attrib.get("url", spec.raw_url)
    chunks: list[dict] = []
    question_candidates: list[dict] = []

    for pair in root.findall("./QAPairs/QAPair"):
        question_node = pair.find("Question")
        answer_node = pair.find("Answer")
        if question_node is None or answer_node is None:
            continue
        source_question_id = question_node.attrib.get(
            "qid", f"{spec.document_id}-{pair.attrib.get('pid', 'unknown')}"
        )
        question_type = question_node.attrib.get("qtype", "other").strip().lower()
        original_question = _normalize_text("".join(question_node.itertext()))
        answer = _normalize_text("".join(answer_node.itertext()))
        if not original_question or not answer:
            continue

        chunk_id = f"{spec.document_id}:{source_question_id}"
        chunks.append(
            {
                "chunk_id": chunk_id,
                "document_id": spec.document_id,
                "title": focus,
                "source_url": source_url,
                "text": answer,
                "license": MEDQUAD_LICENSE,
                "source_question_id": source_question_id,
                "question_type": question_type,
            }
        )
        for question, provenance in _question_variants(original_question, question_type, focus):
            question_candidates.append(
                {
                    "question": question,
                    "document_id": spec.document_id,
                    "gold_chunk_ids": [chunk_id],
                    "question_type": question_type,
                    "provenance": provenance,
                    "source_question_ids": [source_question_id],
                }
            )
    return chunks, question_candidates


def _deduplicate(candidates: Iterable[dict]) -> list[dict]:
    grouped: dict[tuple[str, str], dict] = {}
    for candidate in candidates:
        key = (
            candidate["document_id"],
            re.sub(r"\s+", " ", candidate["question"].strip().lower()),
        )
        if key not in grouped:
            grouped[key] = candidate
            continue
        current = grouped[key]
        current["gold_chunk_ids"] = sorted(
            set(current["gold_chunk_ids"]) | set(candidate["gold_chunk_ids"])
        )
        current["source_question_ids"] = sorted(
            set(current["source_question_ids"]) | set(candidate["source_question_ids"])
        )
        if current["provenance"] != candidate["provenance"]:
            current["provenance"] = "mixed"
    return list(grouped.values())


def _balanced_take(candidates: Iterable[dict], target: int) -> list[dict]:
    by_document: dict[str, deque[dict]] = defaultdict(deque)
    for candidate in sorted(
        candidates,
        key=lambda item: (
            item["document_id"],
            item["question_type"],
            item["provenance"],
            item["question"],
        ),
    ):
        by_document[candidate["document_id"]].append(candidate)

    selected: list[dict] = []
    document_ids = sorted(by_document)
    while len(selected) < target and any(by_document[document_id] for document_id in document_ids):
        for document_id in document_ids:
            if by_document[document_id] and len(selected) < target:
                selected.append(by_document[document_id].popleft())
    if len(selected) < target:
        raise ValueError(f"Only {len(selected)} unique questions were generated; requested {target}")
    return selected


def prepare_dataset(output_dir: Path, *, target_questions: int, refresh: bool) -> dict[str, int]:
    if not 50 <= target_questions <= 100:
        raise ValueError("target_questions must be between 50 and 100")

    cache_dir = output_dir / "raw"
    all_chunks: list[dict] = []
    all_candidates: list[dict] = []
    sources: list[dict] = []

    for spec in SOURCE_SPECS:
        xml_bytes = _load_source(spec, cache_dir, refresh=refresh)
        chunks, candidates = _parse_document(spec, xml_bytes)
        all_chunks.extend(chunks)
        all_candidates.extend(candidates)
        sources.append(
            {
                "document_id": spec.document_id,
                "title": spec.title,
                "medquad_path": spec.path,
                "snapshot_url": spec.raw_url,
                "fixture_path": str(spec.fixture_path.relative_to(Path(__file__).resolve().parent)),
                "license": MEDQUAD_LICENSE,
                "medquad_commit": MEDQUAD_COMMIT,
                "chunk_count": len(chunks),
                "source_mode": "remote_refresh" if refresh else "bundled_fixture",
            }
        )

    unique_candidates = _deduplicate(all_candidates)
    if len(unique_candidates) < target_questions and not refresh:
        raise ValueError(
            f"Bundled fixtures contain {len(unique_candidates)} unique questions, but {target_questions} were requested. "
            "Use --questions 60 or run with --refresh to download the complete pinned MedQuAD XML files."
        )
    selected = _balanced_take(unique_candidates, target_questions)
    questions: list[dict] = []
    for index, candidate in enumerate(selected, start=1):
        questions.append({"question_id": f"q-{index:03d}", **candidate})

    output_dir.mkdir(parents=True, exist_ok=True)
    write_jsonl(output_dir / "corpus.jsonl", all_chunks)
    write_jsonl(output_dir / "questions.jsonl", questions)
    (output_dir / "sources.json").write_text(
        json.dumps(sources, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    summary = {
        "documents": len(sources),
        "chunks": len(all_chunks),
        "questions": len(questions),
        "original_questions": sum(
            question["provenance"] == "medquad_original" for question in questions
        ),
        "paraphrased_questions": sum(
            question["provenance"] != "medquad_original" for question in questions
        ),
    }
    (output_dir / "dataset_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a 3-document MedQuAD retrieval benchmark")
    parser.add_argument("--output-dir", type=Path, default=Path("evaluation/data"))
    parser.add_argument("--questions", type=int, default=60)
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Ignore bundled fixtures and redownload complete pinned XML files with retries",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    summary = prepare_dataset(args.output_dir, target_questions=args.questions, refresh=args.refresh)
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
