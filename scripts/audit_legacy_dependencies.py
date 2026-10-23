from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.legacy_migration_governance import legacy_governance_summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit progressive legacy migration dependencies")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--require-zero-unregistered", action="store_true")
    parser.add_argument("--require-zero-stale-policies", action="store_true")
    parser.add_argument("--require-zero-invalid-deletion-claims", action="store_true")
    args = parser.parse_args()
    payload = legacy_governance_summary(ROOT)
    rendered = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    if args.require_zero_unregistered and (payload["unregistered_consumer_count"] or payload["unregistered_method_count"]):
        return 2
    if args.require_zero_stale_policies and payload["stale_method_policy_count"]:
        return 3
    if args.require_zero_invalid_deletion_claims and payload["invalid_deletion_claim_count"]:
        return 4
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
