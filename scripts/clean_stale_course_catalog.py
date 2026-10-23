"""Retire empty published course shells without deleting history.

The active selector catalog is derived from courses with usable knowledge
material.  This one-time migration only marks public empty shells withdrawn;
course rows and every learning/history relation remain auditable.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.database import DBCourse, SessionLocal
from course_catalog import course_has_knowledge


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    db_path = Path(os.getenv("EDUMATRIX_DB_PATH", "edumatrix.db")).resolve()
    if db_path.name.endswith("_test.db") or os.getenv("TESTING", "").lower() in {"1", "true", "yes"}:
        raise SystemExit("refusing to clean a test database")
    db = SessionLocal()
    try:
        candidates = [
            row for row in db.query(DBCourse).filter(
                DBCourse.status == "published", DBCourse.visibility == "public",
            ).order_by(DBCourse.id).all()
            if not course_has_knowledge(db, row.id)
        ]
        print({"database": str(db_path), "candidates": [row.id for row in candidates], "apply": args.apply})
        if not args.apply:
            return 0
        for row in candidates:
            row.status = "withdrawn"
        db.commit()
        print({"changed_count": len(candidates), "repeat_safe": True})
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
