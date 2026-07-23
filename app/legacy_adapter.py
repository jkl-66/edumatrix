"""Read-only compatibility projection from pre-M1 records."""

from __future__ import annotations

from typing import Any

from app.database import (
    DBConversationHistory,
    DBKnowledgeDocument,
    DBNote,
    DBReviewPlan,
    DBWrongQuestion,
)


class LegacyDataAdapter:
    def __init__(self, session: Any):
        self.session = session

    def knowledge_documents(self, student_id: str) -> list[dict[str, Any]]:
        rows = (
            self.session.query(DBKnowledgeDocument)
            .filter(DBKnowledgeDocument.student_id == student_id)
            .order_by(DBKnowledgeDocument.created_at, DBKnowledgeDocument.id)
            .all()
        )
        return [
            {
                "legacy_id": row.id,
                "owner_legacy_student_id": row.student_id,
                "object_type": "source_document",
                "title": row.title or row.filename,
                "filename": row.filename,
                "content": row.content or "",
                "metadata": {
                    "file_type": row.file_type,
                    "file_size": row.file_size,
                    "tags": row.tags or [],
                    "chunk_count": row.chunk_count,
                },
            }
            for row in rows
        ]

    def notes(self, student_id: str) -> list[dict[str, Any]]:
        rows = (
            self.session.query(DBNote)
            .filter(DBNote.student_id == student_id)
            .order_by(DBNote.created_at, DBNote.id)
            .all()
        )
        return [
            {
                "legacy_id": row.id,
                "owner_legacy_student_id": row.student_id,
                "object_type": "artifact",
                "artifact_type": "note",
                "title": (row.content or "")[:80] or "Legacy note",
                "content": row.content or "",
                "metadata": {"source": row.source, "tags": row.tags or [], "concepts": row.concepts or []},
            }
            for row in rows
        ]

    def review_plans(self, student_id: str) -> list[dict[str, Any]]:
        rows = (
            self.session.query(DBReviewPlan)
            .filter(DBReviewPlan.student_id == student_id)
            .order_by(DBReviewPlan.created_at, DBReviewPlan.id)
            .all()
        )
        return [
            {
                "legacy_id": str(row.id),
                "owner_legacy_student_id": row.student_id,
                "object_type": "path_node",
                "title": row.concept,
                "status": "scheduled",
                "metadata": {
                    "interval_days": row.interval_days,
                    "next_review_at": row.next_review_at.isoformat() if row.next_review_at else None,
                    "mastery": row.mastery,
                },
            }
            for row in rows
        ]

    def conversations(self, student_id: str) -> list[dict[str, Any]]:
        rows = (
            self.session.query(DBConversationHistory)
            .filter(DBConversationHistory.student_id == student_id)
            .order_by(DBConversationHistory.created_at, DBConversationHistory.id)
            .all()
        )
        return [
            {
                "legacy_id": str(row.id),
                "owner_legacy_student_id": row.student_id,
                "object_type": "conversation",
                "query": row.query or "",
                "response_summary": row.response_summary or "",
                "target": row.target or "",
                "profile_snapshot": row.profile_snapshot,
            }
            for row in rows
        ]

    def wrong_questions(self, student_id: str) -> list[dict[str, Any]]:
        rows = (
            self.session.query(DBWrongQuestion)
            .filter(DBWrongQuestion.student_id == student_id)
            .order_by(DBWrongQuestion.created_at, DBWrongQuestion.id)
            .all()
        )
        return [
            {
                "legacy_id": str(row.id),
                "owner_legacy_student_id": row.student_id,
                "object_type": "wrong_question",
                "quiz_record_id": row.quiz_record_id,
                "concept": row.concept_name or "",
                "wrong_reason_category": row.wrong_reason_category,
                "pinned": bool(row.pinned),
                "notes": row.notes or "",
            }
            for row in rows
        ]
