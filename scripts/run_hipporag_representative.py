"""Real extension run, using an explicitly selected isolated database.

Set the normal EDUMATRIX_* runtime environment before invoking this script.
Successful retrieval and API outputs are reused; no formal evaluation is edited.
"""
from __future__ import annotations
import argparse
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

COURSE = "course-ai-deep-learning-agents-v1"
SOURCES = ["ref-9e813bffe27b5705da77d217", "ref-f93b7fce536564cda6ee3c99"]
QUESTION = ("某同学先用全部数据计算标准化的均值和标准差，再划分训练、验证、测试集；"
            "他发现九次多项式的训练误差更低，又反复查看测试误差来选择多项式阶数。"
            "能据此断言九次模型泛化更好吗？结合课程资料给出可以执行的重做流程，"
            "说明各数据集、预处理拟合、阶数选择和最终重拟合分别在何时使用，最后可以报告哪个误差。")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--runtime-pid", type=int)
    parser.add_argument("--index-dir", required=True)
    args = parser.parse_args()
    if args.runtime_pid:
        import psutil
        for key, value in psutil.Process(args.runtime_pid).environ().items():
            if key.startswith("EDUMATRIX_"):
                os.environ[key] = value
    if not os.getenv("EDUMATRIX_DB_PATH"):
        raise SystemExit("Set EDUMATRIX_DB_PATH to an isolated database.")
    root = Path(args.output).resolve()
    root.mkdir(parents=True, exist_ok=True)
    os.environ["EDUMATRIX_HIPPORAG_DIR"] = str(Path(args.index_dir).resolve())
    from app.database import SessionLocal
    from app.canonical_retrieval import retrieve_canonical_sources, list_canonical_source_refs
    with SessionLocal() as db:
        frozen = {"course_id": COURSE, "question": QUESTION, "source_ref_ids": SOURCES,
                  "top_k": 8, "sources": list_canonical_source_refs(db, course_id=COURSE, source_ref_ids=SOURCES),
                  "criteria": ["训练误差不能决定泛化", "先分数据再只在训练数据拟合预处理",
                               "验证集选阶数", "测试集不能反复用于选择",
                               "选定后可在训练加验证数据重拟合完整流程", "报告未参与选择的新测试数据误差"]}
        inputs = root / "inputs.json"
        if inputs.exists():
            assert json.loads(inputs.read_text(encoding="utf-8")) == frozen, "Frozen inputs changed"
        else:
            inputs.write_text(json.dumps(frozen, ensure_ascii=False, indent=2), encoding="utf-8")
        for mode in ("hybrid", "hipporag2"):
            path = root / f"retrieval-{mode}.json"
            if path.exists():
                print(f"Reuse {mode}", flush=True)
                continue
            started = time.monotonic()
            result = retrieve_canonical_sources(db, course_id=COURSE, query=QUESTION,
                source_ref_ids=SOURCES, top_k=8, retrieval_mode=mode, assemble_for_task=True)
            saved = {"mode": mode, "elapsed_seconds": time.monotonic() - started,
                     "low_confidence": result["low_confidence"], "retrieval": result["retrieval"],
                     "passages": [{"id": item['evidence'].id, "content": item['evidence'].content,
                                   "source_ref": item['source_ref'], "metadata": item['evidence'].metadata,
                                   "relevant": item['relevant'], "ranking": item['ranking']}
                                  for item in result['items']]}
            path.write_text(json.dumps(saved, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"Completed {mode}: {saved['elapsed_seconds']:.3f}s, {len(saved['passages'])} passages", flush=True)


if __name__ == "__main__":
    main()
