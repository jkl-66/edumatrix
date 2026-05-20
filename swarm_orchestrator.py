from __future__ import annotations

import argparse
import json
from dataclasses import asdict

from agent_swarm import EduMatrixSwarm, render_console_summary
from observability import TELEMETRY


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="EduMatrix 1+3+5 Swarm orchestration entry point")
    parser.add_argument(
        "query",
        nargs="?",
        default="我还是看不懂卷积神经网络里的池化层，能给我演示最大池化吗？",
        help="学生问题",
    )
    parser.add_argument("--student-id", default="demo-student", help="学生 ID")
    parser.add_argument("--json", action="store_true", dest="as_json", help="输出完整 JSON 包")
    parser.add_argument("--metrics", action="store_true", help="附带输出运行指标快照")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    swarm = EduMatrixSwarm()
    package = swarm.process(args.query, student_id=args.student_id)
    if args.as_json:
        payload = asdict(package)
        if args.metrics:
            payload["metrics"] = TELEMETRY.snapshot()
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    else:
        print(render_console_summary(package))
        if args.metrics:
            print(json.dumps(TELEMETRY.snapshot(), ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
