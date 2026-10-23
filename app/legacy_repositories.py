"""Read repositories for M0 compatibility routes during M1 convergence."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import func

from app.database import (
    DBAlignmentLog, DBCodeExecution, DBCourse, DBCourseDocument, DBConversationHistory,
    DBChapter, DBCheckinLog, DBKnowledgeDocument, DBNote, DBQuizItem,
    DBQuizRecord, DBReviewPlan, DBStudentProfile, DBUser, DBWrongQuestion,
    DBSourceDocument, DBSourceRef, DBWebSearchHistory,
)


class LegacyReadRepository:
    def __init__(self, session: Any):
        self.session = session

    def _observe_assessment(self, legacy_result, canonical_loader, *, projector=None, mode="shadow_read"):
        from app.legacy_migration_governance import observe_legacy_shadow_read, project_model_tree
        return observe_legacy_shadow_read(
            self.session,
            chain_id="assessment-review-calibration",
            legacy_result=legacy_result,
            canonical_loader=canonical_loader,
            legacy_projector=projector or project_model_tree,
            mode=mode,
        )

    def user_by_username(self, username: str) -> DBUser | None:
        return self.session.query(DBUser).filter_by(username=username).first()

    def student_profile(self, student_id: str) -> DBStudentProfile | None:
        return self.session.query(DBStudentProfile).filter_by(student_id=student_id).first()

    def student_profile_ids(self) -> list[str]:
        return [row[0] for row in self.session.query(DBStudentProfile.student_id).order_by(
            DBStudentProfile.student_id
        ).all()]

    def quiz_record(
        self, quiz_id: str, student_id: str | None = None
    ) -> DBQuizRecord | None:
        query = self.session.query(DBQuizRecord).filter_by(id=quiz_id)
        if student_id is not None:
            query = query.filter_by(student_id=student_id)
        result = query.first()
        from app.legacy_migration_governance import AssessmentReviewCalibrationCanonicalReader
        self._observe_assessment(
            result,
            lambda: AssessmentReviewCalibrationCanonicalReader(self.session).quiz_record(quiz_id, student_id),
        )
        return result

    def available_quiz_items(self, concept: str, student_id: str) -> list[DBQuizItem]:
        candidates = self.session.query(DBQuizItem).filter_by(concept=concept).all()
        answered = self.session.query(DBQuizRecord.question).filter(
            DBQuizRecord.student_id == student_id,
            DBQuizRecord.student_answer != "",
        ).all()
        answered_texts = {row[0].strip() for row in answered if row[0]}
        result = [
            item for item in candidates
            if item.question.strip() not in answered_texts
        ]
        from app.legacy_migration_governance import AssessmentReviewCalibrationCanonicalReader, project_model_rows
        self._observe_assessment(
            result,
            lambda: AssessmentReviewCalibrationCanonicalReader(self.session).available_quiz_items(concept, student_id),
            projector=project_model_rows,
        )
        return result

    def quiz_history_desc(self, student_id: str, limit: int) -> list[DBQuizRecord]:
        result = self.session.query(DBQuizRecord).filter_by(
            student_id=student_id
        ).order_by(DBQuizRecord.created_at.desc()).limit(limit).all()
        from app.legacy_migration_governance import AssessmentReviewCalibrationCanonicalReader, project_model_rows
        self._observe_assessment(
            result,
            lambda: AssessmentReviewCalibrationCanonicalReader(self.session).quiz_history_desc(student_id, limit),
            projector=project_model_rows,
        )
        return result

    def save_quiz_record(self, record: DBQuizRecord) -> None:
        self.session.add(record)
        self.session.commit()
        from app.legacy_migration_governance import AssessmentReviewCalibrationCanonicalReader, project_model_row
        persisted = self.session.query(DBQuizRecord).filter_by(id=record.id).first()
        self._observe_assessment(
            persisted,
            lambda: AssessmentReviewCalibrationCanonicalReader(self.session).quiz_record(record.id, record.student_id),
            projector=project_model_row,
            mode="canonical_write_postcheck",
        )

    def update_quiz_item_beta(
        self, question: str, beta: float, beta_vec: list[float]
    ) -> None:
        self.session.query(DBQuizItem).filter_by(question=question).update({
            "irt_beta": beta,
            "irt_beta_vec": beta_vec,
        }, synchronize_session=False)
        self.session.commit()
        from app.legacy_migration_governance import AssessmentReviewCalibrationCanonicalReader, project_model_row
        item = self.session.query(DBQuizItem).filter_by(question=question).first()
        if item is not None:
            self._observe_assessment(
                item,
                lambda: AssessmentReviewCalibrationCanonicalReader(self.session).model_poststate(DBQuizItem, {"id": item.id}),
                projector=project_model_row,
                mode="canonical_write_postcheck",
            )

    def create_wrong_question_if_missing(
        self, *, student_id: str, quiz_record_id: str, concept: str,
        reason: str,
    ) -> bool:
        existing = self.session.query(DBWrongQuestion).filter_by(
            student_id=student_id,
            concept_name=concept,
            quiz_record_id=quiz_record_id,
        ).first()
        if existing:
            return False
        self.session.add(DBWrongQuestion(
            student_id=student_id,
            quiz_record_id=quiz_record_id,
            concept_name=concept,
            wrong_reason_category=reason,
        ))
        return True

    def lower_review_priority(self, student_id: str, concept: str) -> bool:
        review_plan = self.review_plan(student_id, concept)
        if review_plan is None:
            return False
        review_plan.priority = min(5.0, (review_plan.priority or 1.0) * 1.5)
        self.session.commit()
        from app.legacy_migration_governance import AssessmentReviewCalibrationCanonicalReader, project_model_row
        self._observe_assessment(
            review_plan,
            lambda: AssessmentReviewCalibrationCanonicalReader(self.session).review_plan(student_id, concept),
            projector=project_model_row,
            mode="canonical_write_postcheck",
        )
        return True

    def link_similar_quiz(self, student_id: str, concept: str, quiz_id: str) -> bool:
        review_plan = self.review_plan(student_id, concept)
        if review_plan is None:
            return False
        current = list(review_plan.similar_quiz_ids or [])
        if quiz_id not in current:
            current.append(quiz_id)
        review_plan.similar_quiz_ids = current
        self.session.commit()
        from app.legacy_migration_governance import AssessmentReviewCalibrationCanonicalReader, project_model_row
        self._observe_assessment(
            review_plan,
            lambda: AssessmentReviewCalibrationCanonicalReader(self.session).review_plan(student_id, concept),
            projector=project_model_row,
            mode="canonical_write_postcheck",
        )
        return True

    def wrong_questions(
        self, student_id: str, concept: str, limit: int
    ) -> list[tuple[DBWrongQuestion, DBQuizRecord | None]]:
        query = self.session.query(DBWrongQuestion).filter_by(student_id=student_id)
        if concept:
            query = query.filter_by(concept_name=concept)
        records = query.order_by(
            DBWrongQuestion.pinned.desc(), DBWrongQuestion.created_at.desc()
        ).limit(limit).all()
        result = [
            (record, self.quiz_record(record.quiz_record_id))
            for record in records
        ]
        from app.legacy_migration_governance import AssessmentReviewCalibrationCanonicalReader, project_model_tree
        self._observe_assessment(
            result,
            lambda: AssessmentReviewCalibrationCanonicalReader(self.session).wrong_questions(student_id, concept, limit),
            projector=project_model_tree,
        )
        return result

    def wrong_concept_stats(self, student_id: str) -> list[tuple[str, int]]:
        result = self.session.query(
            DBWrongQuestion.concept_name,
            func.count(DBWrongQuestion.id),
        ).filter_by(student_id=student_id).group_by(
            DBWrongQuestion.concept_name
        ).order_by(func.count(DBWrongQuestion.id).desc()).all()
        from app.legacy_migration_governance import AssessmentReviewCalibrationCanonicalReader
        self._observe_assessment(
            [list(row) for row in result],
            lambda: AssessmentReviewCalibrationCanonicalReader(self.session).wrong_concept_stats(student_id),
        )
        return result

    def wrong_question(self, wrong_id: int, student_id: str) -> DBWrongQuestion | None:
        result = self.session.query(DBWrongQuestion).filter_by(
            id=wrong_id, student_id=student_id
        ).first()
        from app.legacy_migration_governance import AssessmentReviewCalibrationCanonicalReader
        self._observe_assessment(
            result,
            lambda: AssessmentReviewCalibrationCanonicalReader(self.session).wrong_question(wrong_id, student_id),
        )
        return result

    def delete_wrong_question(self, wrong_id: int, student_id: str) -> bool:
        record = self.wrong_question(wrong_id, student_id)
        if record is None:
            return False
        self.session.delete(record)
        self.session.commit()
        from app.legacy_migration_governance import AssessmentReviewCalibrationCanonicalReader
        self._observe_assessment(
            None,
            lambda: AssessmentReviewCalibrationCanonicalReader(self.session).wrong_question(wrong_id, student_id),
            mode="canonical_write_postcheck",
        )
        return True

    def toggle_wrong_question_pin(
        self, wrong_id: int, student_id: str
    ) -> bool | None:
        record = self.wrong_question(wrong_id, student_id)
        if record is None:
            return None
        record.pinned = not record.pinned
        self.session.commit()
        from app.legacy_migration_governance import AssessmentReviewCalibrationCanonicalReader, project_model_row
        self._observe_assessment(
            record,
            lambda: AssessmentReviewCalibrationCanonicalReader(self.session).wrong_question(wrong_id, student_id),
            projector=project_model_row,
            mode="canonical_write_postcheck",
        )
        return bool(record.pinned)

    def update_wrong_question_notes(
        self, wrong_id: int, student_id: str, notes: str
    ) -> bool:
        record = self.wrong_question(wrong_id, student_id)
        if record is None:
            return False
        record.notes = notes
        self.session.commit()
        from app.legacy_migration_governance import AssessmentReviewCalibrationCanonicalReader, project_model_row
        self._observe_assessment(
            record,
            lambda: AssessmentReviewCalibrationCanonicalReader(self.session).wrong_question(wrong_id, student_id),
            projector=project_model_row,
            mode="canonical_write_postcheck",
        )
        return True

    def checkins_between(
        self, student_id: str, start: datetime, end: datetime
    ) -> list[DBCheckinLog]:
        result = self.session.query(DBCheckinLog).filter(
            DBCheckinLog.student_id == student_id,
            DBCheckinLog.checkin_date >= start,
            DBCheckinLog.checkin_date <= end,
        ).all()
        from app.legacy_migration_governance import AssessmentReviewCalibrationCanonicalReader, project_model_rows
        self._observe_assessment(
            result,
            lambda: AssessmentReviewCalibrationCanonicalReader(self.session).checkins_between(student_id, start, end),
            projector=project_model_rows,
        )
        return result

    def save_checkin(self, checkin: DBCheckinLog) -> None:
        self.session.add(checkin)
        self.session.commit()
        from app.legacy_migration_governance import AssessmentReviewCalibrationCanonicalReader, project_model_row
        self._observe_assessment(
            checkin,
            lambda: AssessmentReviewCalibrationCanonicalReader(self.session).model_poststate(DBCheckinLog, {"id": checkin.id}),
            projector=project_model_row,
            mode="canonical_write_postcheck",
        )

    def commit(self) -> None:
        self.session.commit()

    def checkin_history(self, student_id: str) -> list[DBCheckinLog]:
        return self.session.query(DBCheckinLog).filter_by(
            student_id=student_id
        ).order_by(DBCheckinLog.checkin_date.asc()).all()

    def checkin_dates(self, student_id: str) -> list[datetime]:
        rows = self.session.query(DBCheckinLog.checkin_date).filter_by(
            student_id=student_id
        ).order_by(DBCheckinLog.checkin_date.desc()).all()
        return [row[0] for row in rows if row[0]]

    def mcmc_training_rows(
        self,
    ) -> tuple[list[DBStudentProfile], list[DBQuizItem], list[DBQuizRecord]]:
        students = self.session.query(DBStudentProfile).filter(
            DBStudentProfile.rl_q_table.isnot(None)
        ).all()
        items = self.session.query(DBQuizItem).all()
        student_ids = [student.student_id for student in students]
        records = self.session.query(DBQuizRecord).filter(
            DBQuizRecord.student_id.in_(student_ids)
        ).all() if student_ids else []
        result = (students, items, records)
        from app.legacy_migration_governance import AssessmentReviewCalibrationCanonicalReader, project_model_tree
        self._observe_assessment(
            result,
            lambda: AssessmentReviewCalibrationCanonicalReader(self.session).mcmc_training_rows(),
            projector=project_model_tree,
        )
        return result

    def update_calibrated_quiz_items(self, item_ids: list[str], calibrated: list[Any]) -> None:
        for index, item_id in enumerate(item_ids):
            item = calibrated[index]
            self.session.query(DBQuizItem).filter_by(id=item_id).update({
                "irt_alpha_vec": item.alpha,
                "irt_beta_vec": item.beta,
                "irt_alpha": item.alpha[0],
                "irt_beta": item.beta[0],
            }, synchronize_session=False)
        self.session.commit()
        from app.legacy_migration_governance import AssessmentReviewCalibrationCanonicalReader, project_model_rows
        rows = self.session.query(DBQuizItem).filter(DBQuizItem.id.in_(item_ids)).order_by(DBQuizItem.id).all()
        self._observe_assessment(
            rows,
            lambda: AssessmentReviewCalibrationCanonicalReader(self.session).quiz_items(item_ids),
            projector=project_model_rows,
            mode="canonical_write_postcheck",
        )

    def review_plan(self, student_id: str, concept: str) -> DBReviewPlan | None:
        result = self.session.query(DBReviewPlan).filter_by(
            student_id=student_id, concept=concept
        ).first()
        from app.legacy_migration_governance import AssessmentReviewCalibrationCanonicalReader
        self._observe_assessment(
            result,
            lambda: AssessmentReviewCalibrationCanonicalReader(self.session).review_plan(student_id, concept),
        )
        return result

    def due_review_plans(
        self, student_id: str, *, now: datetime, limit: int
    ) -> list[DBReviewPlan]:
        result = self.session.query(DBReviewPlan).filter(
            DBReviewPlan.student_id == student_id,
            (DBReviewPlan.next_review_at.is_(None)) | (DBReviewPlan.next_review_at <= now),
        ).order_by(DBReviewPlan.next_review_at.asc()).limit(limit).all()
        from app.legacy_migration_governance import AssessmentReviewCalibrationCanonicalReader, project_model_rows
        self._observe_assessment(
            result,
            lambda: AssessmentReviewCalibrationCanonicalReader(self.session).due_review_plans(student_id, now, limit),
            projector=project_model_rows,
        )
        return result

    def all_review_plans(self, student_id: str) -> list[DBReviewPlan]:
        result = self.session.query(DBReviewPlan).filter_by(student_id=student_id).all()
        from app.legacy_migration_governance import AssessmentReviewCalibrationCanonicalReader, project_model_rows
        self._observe_assessment(
            result,
            lambda: AssessmentReviewCalibrationCanonicalReader(self.session).all_review_plans(student_id),
            projector=project_model_rows,
        )
        return result

    def code_history(self, student_id: str, *, limit: int) -> list[DBCodeExecution]:
        return self.session.query(DBCodeExecution).filter_by(student_id=student_id).order_by(
            DBCodeExecution.created_at.desc()
        ).limit(limit).all()

    def web_search_history(self, student_id: str, *, limit: int) -> list[DBWebSearchHistory]:
        return self.session.query(DBWebSearchHistory).filter_by(student_id=student_id).order_by(
            DBWebSearchHistory.created_at.desc()
        ).limit(limit).all()

    def knowledge_library_rows(self, student_id: str):
        legacy = self.session.query(DBKnowledgeDocument).filter(
            DBKnowledgeDocument.student_id.in_([student_id, "public", "system"])
        ).order_by(DBKnowledgeDocument.created_at.desc()).all()
        course_query = self.session.query(
            DBCourseDocument, DBCourse, DBSourceDocument, DBSourceRef, DBChapter
        ).join(
            DBCourse, DBCourse.id == DBCourseDocument.course_id
        ).outerjoin(
            DBSourceDocument,
            (DBSourceDocument.course_id == DBCourseDocument.course_id)
            & (DBSourceDocument.legacy_document_id == DBCourseDocument.id),
        ).outerjoin(
            DBSourceRef, DBSourceRef.source_document_id == DBSourceDocument.id
        ).outerjoin(
            DBChapter, DBChapter.id == DBSourceRef.chapter_id
        ).filter(
            DBCourse.status == "published", DBCourseDocument.status == "published",
            DBCourse.visibility == "public",
        )
        course = course_query.order_by(DBCourse.title, DBCourseDocument.chapter_order).all()
        return legacy, course

    def knowledge_document_context(self, doc_id: str, student_id: str):
        legacy = self.session.query(DBKnowledgeDocument).filter(
            DBKnowledgeDocument.id == doc_id,
            DBKnowledgeDocument.student_id.in_([student_id, "public", "system"]),
        ).first()
        if legacy:
            return "legacy", legacy, None
        course = self.session.query(
            DBCourseDocument, DBCourse, DBSourceDocument, DBSourceRef, DBChapter
        ).join(
            DBCourse, DBCourse.id == DBCourseDocument.course_id
        ).outerjoin(
            DBSourceDocument,
            (DBSourceDocument.course_id == DBCourseDocument.course_id)
            & (DBSourceDocument.legacy_document_id == DBCourseDocument.id),
        ).outerjoin(
            DBSourceRef, DBSourceRef.source_document_id == DBSourceDocument.id
        ).outerjoin(
            DBChapter, DBChapter.id == DBSourceRef.chapter_id
        ).filter(
            DBCourseDocument.id == doc_id, DBCourseDocument.status == "published",
            DBCourse.status == "published", DBCourse.visibility == "public",
        ).first()
        return ("course", *course) if course else None

    def set_document_guide(self, doc_id: str, student_id: str, guide: dict[str, Any]) -> bool:
        document = self.session.query(DBKnowledgeDocument).filter_by(
            id=doc_id, student_id=student_id
        ).first()
        if document is None:
            return False
        metadata = dict(document.multimodal_metadata or {})
        metadata["doc_guide"] = guide
        document.multimodal_metadata = metadata
        self.session.commit()
        return True

    def delete_knowledge_document(self, doc_id: str, student_id: str):
        if self.session.query(DBCourseDocument.id).filter_by(id=doc_id).first():
            return "readonly_course"
        document = self.session.query(DBKnowledgeDocument).filter_by(
            id=doc_id, student_id=student_id
        ).first()
        if document is None:
            readonly = self.session.query(DBKnowledgeDocument.id).filter(
                DBKnowledgeDocument.id == doc_id,
                DBKnowledgeDocument.student_id.in_(["public", "system"]),
            ).first()
            return "readonly_public" if readonly else None
        result = (document.filename, document.file_type or "txt")
        source = self.session.query(DBSourceDocument).filter_by(
            legacy_document_id=document.id
        ).first()
        if source is not None:
            self.session.delete(source)
        self.session.delete(document)
        self.session.commit()
        return result

    def display_name(self, username: str) -> str:
        user = self.user_by_username(username)
        return user.display_name if (user and user.display_name) else username

    def latest_alignment(self, student_id: str) -> DBAlignmentLog | None:
        return self.session.query(DBAlignmentLog).filter_by(student_id=student_id).order_by(
            DBAlignmentLog.timestamp.desc()
        ).first()

    def quiz_history(self, student_id: str) -> list[DBQuizRecord]:
        return self.session.query(DBQuizRecord).filter_by(student_id=student_id).order_by(
            DBQuizRecord.created_at.asc()
        ).all()

    def personal_knowledge_documents(self, student_id: str) -> list[DBKnowledgeDocument]:
        return self.session.query(DBKnowledgeDocument).filter_by(student_id=student_id).all()

    def conversation_snapshot(self, student_id: str, conversation_id: int | str):
        return self.session.query(DBConversationHistory).filter_by(
            student_id=student_id, id=conversation_id
        ).first()

    def delete_review_plan(self, student_id: str, concept: str) -> int:
        deleted = self.session.query(DBReviewPlan).filter_by(
            student_id=student_id, concept=concept
        ).delete(synchronize_session=False)
        self.session.commit()
        from app.legacy_migration_governance import AssessmentReviewCalibrationCanonicalReader
        self._observe_assessment(
            None,
            lambda: AssessmentReviewCalibrationCanonicalReader(self.session).review_plan(student_id, concept),
            mode="canonical_write_postcheck",
        )
        return deleted

    def knowledge_filenames(self, document_ids: list[str] | None = None) -> list[str]:
        query = self.session.query(DBKnowledgeDocument.filename)
        if document_ids is not None:
            query = query.filter(DBKnowledgeDocument.id.in_(document_ids))
        return [row[0] for row in query.all() if row[0]]

    def upsert_generated_note(
        self, *, note_id: str, student_id: str, content: str,
        tag: str, concepts: list[str],
    ) -> str:
        existing = self.session.query(DBNote).filter_by(student_id=student_id).all()
        target = next((note for note in existing
                       if any(item in (note.concepts or []) for item in concepts)
                       and tag in (note.tags or [])), None)
        if target:
            target.content = content
            current = list(target.concepts or [])
            target.concepts = current + [item for item in concepts if item not in current]
            result = target.id
        else:
            self.session.add(DBNote(
                id=note_id, student_id=student_id, source="adaptive_hub",
                content=content, tags=[tag], concepts=concepts,
            ))
            result = note_id
        self.session.commit()
        return result
