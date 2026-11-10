"""Freeze the next development acceptance on a separate DB, without model calls."""
from pathlib import Path
import copy
import hashlib
import json
import os
import secrets
import sqlite3
import sys
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "scratch/automatic-generation-r207"
ORIGIN = ROOT / "scratch/validation-20261025/acceptance.sqlite3"
DATABASE = OUT / "acceptance.sqlite3"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    if (OUT / "inputs.json").exists():
        print("Frozen inputs already exist; preserving the original matrix.")
        return
    if not DATABASE.exists():
        with sqlite3.connect(ORIGIN.as_uri() + "?mode=ro", uri=True) as source:
            with sqlite3.connect(DATABASE) as destination:
                source.backup(destination)
    os.environ["EDUMATRIX_DB_PATH"] = str(DATABASE)
    os.environ["EDUMATRIX_GENERATION_WORKER"] = "false"
    sys.path.insert(0, str(ROOT))
    from app.database import (init_db, SessionLocal, DBUser, DBStudentProfile,
        DBProfileSnapshot, DBCourseMembership, DBCourse, DBSourceRef)
    from app.auth import get_password_hash
    from app.resource_bundles import GENERATION_RESOURCE_TYPES
    init_db()
    prior_path = ROOT / "scratch/defense-reference-20261030/b7-evaluation/same-ai-five391/evaluation-development-r158/manifest.json"
    prior = json.loads(prior_path.read_text(encoding="utf-8-sig"))
    common = prior["cases"][0]
    personas, credentials = {}, {}
    with SessionLocal() as db:
        course = db.get(DBCourse, common["course_id"])
        for name, original in prior["personas"].items():
            username = f"auto_r207_{name}"
            actor = db.query(DBUser).filter_by(username=username).first()
            password = secrets.token_urlsafe(24)
            if not actor:
                actor = DBUser(username=username, hashed_password=get_password_hash(password),
                               role="student", display_name=f"自动生成验收 · {name}")
                db.add(actor)
                db.flush()
                origin_profile = db.get(DBStudentProfile, original["username"])
                fields = {column.name: copy.deepcopy(getattr(origin_profile, column.name))
                          for column in DBStudentProfile.__table__.columns if column.name != "student_id"}
                db.add(DBStudentProfile(student_id=username, **fields))
                db.add(DBCourseMembership(course_id=course.id, user_public_id=actor.public_id,
                                          role="student", status="active"))
            else:
                actor.hashed_password = get_password_hash(password)
            source_snapshot = db.get(DBProfileSnapshot, original["snapshot_id"])
            frozen = copy.deepcopy(source_snapshot.snapshot)
            # These are the same synthetic learning facts, owned by a dedicated
            # account. No old answer, resource or formal score is rewritten.
            frozen = json.loads(json.dumps(frozen, ensure_ascii=False)
                .replace(original["owner_public_id"], actor.public_id).replace(original["username"], username))
            digest = hashlib.sha256(json.dumps(frozen, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
            snapshot = DBProfileSnapshot(owner_public_id=actor.public_id, legacy_student_id=username,
                profile_version="automatic-generation-r207", snapshot=frozen, content_hash=digest,
                trace_id=f"auto-r207-{name}")
            db.add(snapshot)
            db.flush()
            personas[name] = {"username": username, "owner_public_id": actor.public_id,
                              "profile_snapshot_id": snapshot.id, "snapshot_hash": digest,
                              "original_snapshot_id": source_snapshot.id, "synthetic": True}
            credentials[name] = {"username": username, "password": password}
        sources = []
        for ref_id in common["source_ref_ids"]:
            ref = db.get(DBSourceRef, ref_id)
            assert ref is not None
            sources.append({"id": ref.id, "content_hash": ref.content_hash,
                "quote_sha256": hashlib.sha256((ref.quote or "").encode()).hexdigest(),
                "location_label": ref.location_label})
        db.commit()
        cases = [{"id": f"bundle-{name}", "persona": name, "types": list(GENERATION_RESOURCE_TYPES),
                  "entry": "resource_center"} for name in personas]
        cases += [{"id": f"single-{kind}", "persona": "software_developer", "types": [kind],
                   "entry": "resource_center"} for kind in GENERATION_RESOURCE_TYPES]
        cases += [
            {"id": "path-practical", "persona": "mathematics_student",
             "types": ["code_sandbox", "interactive_model", "training_task"], "entry": "learning_path"},
            {"id": "chat-explanation", "persona": "finance_practitioner", "types": ["handout", "quiz"], "entry": "chat"},
            {"id": "review-practice", "persona": "shop_ai", "types": list(GENERATION_RESOURCE_TYPES), "entry": "review"},
            {"id": "ordinary-exam", "persona": "software_developer", "entry": "formal_exam"},
            {"id": "inquiry-training-vs-validation", "persona": "humanities_educator", "entry": "inquiry"},
            {"id": "inquiry-mse-direction", "persona": "humanities_educator", "entry": "inquiry"},
            {"id": "new-registration-learning", "entry": "registration_diagnosis_path_resource_feedback"},
        ]
        manifest = {"version": "r207-development-automatic-generation", "frozen_at": datetime.now(timezone.utc).isoformat(),
            "scope": "合成画像、真实生成的开发验收；受控故障另列，不并入旧正式指标。",
            "course_id": course.id, "course_version": course.version,
            "knowledge_point_id": common["knowledge_point_id"], "title": common["title"],
            "common_instruction": common["instruction"], "sources": sources, "personas": personas, "cases": cases,
            "fault_cases": ["planner_failure", "invalid_json_or_fields", "output_limit", "wrong_answer_or_calculation",
                "missing_data", "false_review_rejection", "omitted_condition", "review_timeout", "network_or_rate_limit",
                "dependency_version_change", "refresh_and_restart", "duplicate_submit", "cancel_late_response", "account_402"],
            "criteria": ["全部原选类型完成", "来源、画像和版本一致", "通过独立内容核对及实际学习操作",
                "无人工改稿、补裁决或调用恢复接口", "原稿、失败、自动动作与最终版本可复查"],
            "reports": ["first_draft_pass", "automatic_repair_complete", "external_block", "unresolved", "manual_takeover", "elapsed_seconds", "model_calls"]}
    (OUT / "inputs.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT / "credentials.local.json").write_text(json.dumps(credentials, indent=2), encoding="utf-8")
    print(f"Frozen {len(cases)} natural scenarios and {len(manifest['fault_cases'])} controlled faults; isolated DB prepared.")


if __name__ == "__main__":
    main()
