"""
从 knowledge_base.json 构建 FAISS 索引。

用法:
  set EDUMATRIX_EMBEDDING_PROVIDER=sentence_transformer
  python scripts/seed_faiss.py
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import CONFIG
from embedding_models import EMBEDDINGS, EmbeddingBackend
from knowledge_base import load_evidence_from_file
from vector_store_faiss import FaissVectorIndex


def seed():
    provider = CONFIG.embedding_provider
    if provider == "hash":
        print("警告: 当前使用 hash 嵌入，FAISS 索引需用真实嵌入效果才好")
        print(f"建议: set EDUMATRIX_EMBEDDING_PROVIDER=sentence_transformer\n")

    kb_files = [
        Path("data/knowledge_base.json"),
        Path("data/evidences.json"),
    ]

    all_evidence = []
    for f in kb_files:
        ev = load_evidence_from_file(f)
        if ev:
            all_evidence.extend(ev)
            print(f"  加载 {f}: {len(ev)} 条")

    if not all_evidence:
        print("未找到知识库文件，创建示例")
        sample = [
            {"id": "TXT_SAMPLE_01", "title": "示例知识", "content": "EduMatrix 支持多智能体教育问答", "modality": "text", "source": "示例", "tags": ["EduMatrix"], "anchors": ["example"]},
        ]
        with open("data/knowledge_base.json", "w", encoding="utf-8") as f:
            json.dump(sample, f, ensure_ascii=False, indent=2)
        all_evidence = load_evidence_from_file("data/knowledge_base.json")

    dim = len(EMBEDDINGS.embed("init"))
    print(f"\n嵌入维度: {dim}, 提供者: {EMBEDDINGS.name}")
    print(f"索引目录: {CONFIG.faiss_index_dir}\n")

    categories = {
        "courseware": [],
        "textbook": [],
        "code": [],
        "dataset": [],
        "ppt": [],
    }

    for ev in all_evidence:
        tags = set(ev.tags)
        if tags & {"代码", "code", "Code", "Python", "pytorch"}:
            categories["code"].append(ev)
        elif tags & {"数据集", "dataset"}:
            categories["dataset"].append(ev)
        elif tags & {"PPT", "ppt", "讲义"}:
            categories["ppt"].append(ev)
        elif tags & {"教材", "课本", "图像", "image"}:
            categories["textbook"].append(ev)
        else:
            categories["courseware"].append(ev)

    for category, items in categories.items():
        if not items:
            continue
        print(f"  [{category}] 构建 {len(items)} 条...")
        idx = FaissVectorIndex(f"edumatrix-{category}")
        idx.upsert(tuple(items))
        idx.save(CONFIG.faiss_index_dir)
        print(f"    -> 已保存到 {CONFIG.faiss_index_dir}/{category}")

    print(f"\n完成! 共索引 {len(all_evidence)} 条知识")
    print(f"运行 python run.py (EDUMATRIX_USE_FAISS=1) 以使用 FAISS 加速检索")


if __name__ == "__main__":
    seed()
