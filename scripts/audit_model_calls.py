from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.model_call_governance import governance_summary, scan_model_calls


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit production model-call governance")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--require-zero-unregistered", action="store_true")
    parser.add_argument("--require-zero-active-direct", action="store_true")
    args = parser.parse_args()
    callsites = scan_model_calls(ROOT)
    payload = {**governance_summary(callsites), "callsites": [item.payload() for item in callsites]}
    rendered = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    if args.require_zero_unregistered and payload["unregistered_count"]:
        return 2
    if args.require_zero_active_direct and payload["active_direct_count"]:
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
