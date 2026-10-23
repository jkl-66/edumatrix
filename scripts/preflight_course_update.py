from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.database import SessionLocal
from course_catalog import (
    CURATED_COURSE_MANIFESTS,
    apply_course_bundle_update,
    ingest_course_bundle,
    load_versioned_course_bundle,
    preflight_course_bundle_update,
)


def inspect_course_update(session: Any, manifest_path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    bundle = load_versioned_course_bundle(manifest_path)
    return bundle, preflight_course_bundle_update(session, bundle)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Preflight a packaged course version. Read-only unless --apply is explicit."
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=CURATED_COURSE_MANIFESTS[0],
        help="Path to an allowlisted course_manifest.json",
    )
    parser.add_argument("--apply", action="store_true", help="Apply an approved version transition")
    parser.add_argument("--expected-current-version")
    parser.add_argument("--expected-incoming-version")
    args = parser.parse_args()

    session = SessionLocal()
    try:
        bundle, report = inspect_course_update(session, args.manifest)
        result: dict[str, Any] = {"preflight": report, "applied": False}
        if args.apply:
            if not args.expected_current_version or not args.expected_incoming_version:
                parser.error(
                    "--apply requires --expected-current-version and --expected-incoming-version"
                )
            if report["status"] != "update_available":
                raise ValueError("only an update_available transition can be explicitly applied")
            write_result = apply_course_bundle_update(
                session,
                bundle,
                expected_current_version=args.expected_current_version,
                expected_incoming_version=args.expected_incoming_version,
            )
            result.update(
                {
                    "applied": True,
                    "database": write_result,
                    "rag_chunks": ingest_course_bundle(bundle),
                }
            )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
