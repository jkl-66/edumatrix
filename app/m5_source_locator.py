"""Deterministic, fail-closed locators for course retrieval evidence."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Iterable

from app.database import DBCourseDocument, DBSourceDocument, DBSourceRef
from document_parser import chunk_document
from models import Evidence


class SourceLocationError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class EvidenceLocation:
    evidence_id: str
    char_start: int
    char_end: int
    quote: str
    fragment_hash: str


def _normalized_with_offsets(text: str) -> tuple[str, list[int], list[int]]:
    chars: list[str] = []
    starts: list[int] = []
    ends: list[int] = []
    in_whitespace = False
    for index, char in enumerate(text):
        if char.isspace():
            if not in_whitespace:
                chars.append(" ")
                starts.append(index)
                ends.append(index + 1)
                in_whitespace = True
            else:
                ends[-1] = index + 1
            continue
        chars.append(char)
        starts.append(index)
        ends.append(index + 1)
        in_whitespace = False

    if chars and chars[0] == " ":
        chars.pop(0)
        starts.pop(0)
        ends.pop(0)
    if chars and chars[-1] == " ":
        chars.pop()
        starts.pop()
        ends.pop()
    return "".join(chars), starts, ends


def build_evidence_locations(
    document_content: str, evidence_items: Iterable[Evidence]
) -> dict[str, EvidenceLocation]:
    """Map deterministic retrieval evidence back to the original document.

    Parent-child retrieval returns the parent block to preserve context, so all
    child evidence from one parent intentionally resolves to the same trusted
    parent range. Only whitespace normalization is tolerated; other content
    drift fails closed.
    """
    normalized_document, starts, ends = _normalized_with_offsets(document_content)
    if not normalized_document:
        raise SourceLocationError("source_document_empty", "来源文档没有可定位正文")

    cursor = 0
    parent_locations: dict[object, tuple[int, int]] = {}
    output: dict[str, EvidenceLocation] = {}
    for evidence in evidence_items:
        parent_index = evidence.metadata.get("parent_index")
        location_key: object = (
            ("parent", int(parent_index))
            if parent_index is not None
            else ("evidence", evidence.id)
        )
        original_range = parent_locations.get(location_key)
        if original_range is None:
            target = str(evidence.metadata.get("parent_content") or evidence.content)
            normalized_target, _, _ = _normalized_with_offsets(target)
            if not normalized_target:
                raise SourceLocationError(
                    "evidence_fragment_empty", f"证据 {evidence.id} 没有可定位内容"
                )
            normalized_start = normalized_document.find(normalized_target, cursor)
            if normalized_start < 0:
                raise SourceLocationError(
                    "evidence_fragment_drift",
                    f"证据 {evidence.id} 无法从冻结正文重建",
                )
            normalized_end = normalized_start + len(normalized_target)
            original_range = (
                starts[normalized_start],
                ends[normalized_end - 1],
            )
            parent_locations[location_key] = original_range
            cursor = normalized_end

        char_start, char_end = original_range
        fragment = document_content[char_start:char_end]
        output[evidence.id] = EvidenceLocation(
            evidence_id=evidence.id,
            char_start=char_start,
            char_end=char_end,
            quote=fragment[:500],
            fragment_hash=hashlib.sha256(fragment.encode("utf-8")).hexdigest(),
        )
    return output


def resolve_course_evidence_location(
    session,
    *,
    source_ref: DBSourceRef,
    evidence_id: str,
) -> tuple[DBCourseDocument, EvidenceLocation]:
    """Resolve evidence from canonical source identity and frozen course text."""
    source = (
        session.query(DBSourceDocument)
        .filter_by(id=source_ref.source_document_id)
        .first()
    )
    if source is None:
        raise SourceLocationError(
            "canonical_source_missing", "来源引用的 canonical 文档不存在"
        )
    document = (
        session.query(DBCourseDocument)
        .filter_by(id=source.legacy_document_id, course_id=source.course_id)
        .first()
    )
    if document is None:
        raise SourceLocationError(
            "source_document_unavailable", "canonical 来源没有对应课程文档"
        )

    content = document.content or ""
    content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
    expected_hashes = {
        str(getattr(source, "processed_sha256", "") or document.content_hash).lower(),
        str(source_ref.content_hash).lower(),
    }
    if len(expected_hashes) != 1 or content_hash.lower() not in expected_hashes:
        raise SourceLocationError(
            "source_content_drift", "课程正文与 canonical 引用哈希不一致"
        )
    if source_ref.chapter_id is None:
        raise SourceLocationError("source_chapter_missing", "来源引用没有绑定章节")
    if source_ref.char_start != 0 or source_ref.char_end != len(content):
        raise SourceLocationError(
            "source_ref_range_drift", "canonical 整章范围与冻结正文不一致"
        )

    source_name = f"{source.course_id}/{document.filename}"
    chunks = chunk_document(content, source=source_name)
    locations = build_evidence_locations(content, chunks)
    location = locations.get(evidence_id)
    if location is None:
        raise SourceLocationError("evidence_not_found", "证据不属于该来源引用")
    return document, location
