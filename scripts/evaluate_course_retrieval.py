from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from course_retrieval_evaluation import evaluate_course_retrieval


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the frozen offline course retrieval evaluation.")
    parser.add_argument("--dataset", type=Path, default=None)
    parser.add_argument("--manifest", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    kwargs = {}
    if args.dataset is not None:
        kwargs["dataset_path"] = args.dataset
    if args.manifest is not None:
        kwargs["manifest_path"] = args.manifest
    report = evaluate_course_retrieval(**kwargs)
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
