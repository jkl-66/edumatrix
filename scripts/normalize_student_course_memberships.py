"""Normalize learner-facing built-in course memberships in the formal database.

The operation is deliberately opt-in (``--apply``) and reversible: it only
changes non-master active memberships for student/visitor accounts to
``removed``. Course rows and all learning/history data remain untouched.
Teacher/admin/assistant memberships are never changed because they represent
management access rather than a learner shelf baseline.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.database import DBUser, DBCourseMembership, SessionLocal, DB_PATH
from course_catalog import MASTER_COURSE_ID


LEARNER_ROLES = {"student", "visitor"}


def normalize(*, apply: bool) -> dict[str, object]:
    if os.getenv("TESTING", "false").lower() == "true":
        raise RuntimeError("refusing to modify a test database")
    if os.path.basename(DB_PATH).lower().endswith("_test.db"):
        raise RuntimeError(f"refusing to modify test database: {DB_PATH}")

    with SessionLocal() as session:
        users = session.query(DBUser).filter(
            DBUser.is_active.is_(True),
            DBUser.role.in_(sorted(LEARNER_ROLES)),
        ).order_by(DBUser.username).all()
        user_ids = [user.public_id for user in users]
        rows = session.query(DBCourseMembership).filter(
            DBCourseMembership.user_public_id.in_(user_ids or ["__none__"]),
            DBCourseMembership.status == "active",
            DBCourseMembership.course_id != MASTER_COURSE_ID,
        ).order_by(DBCourseMembership.user_public_id, DBCourseMembership.course_id).all()
        changes = [
            {
                "membership_id": row.id,
                "user_public_id": row.user_public_id,
                "course_id": row.course_id,
                "from_status": row.status,
                "to_status": "removed",
            }
            for row in rows
        ]
        if apply:
            for row in rows:
                row.status = "removed"
            session.commit()
        else:
            session.rollback()
        # Re-read after the transaction so the report reflects the database,
        # not objects retained in the SQLAlchemy identity map.
        session.expire_all()
        remaining = session.query(DBCourseMembership).filter(
            DBCourseMembership.user_public_id.in_(user_ids or ["__none__"]),
            DBCourseMembership.status == "active",
        ).all()
        return {
            "schema_version": "edumatrix.learner-course-membership-normalization.v1",
            "database": DB_PATH,
            "applied": apply,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "learner_count": len(users),
            "changed_count": len(changes),
            "changes": changes,
            "remaining_active_by_user": {
                user.public_id: sorted({row.course_id for row in remaining if row.user_public_id == user.public_id})
                for user in users
            },
            "protected_master_course_id": MASTER_COURSE_ID,
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="commit the reversible status changes")
    args = parser.parse_args()
    print(json.dumps(normalize(apply=args.apply), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
