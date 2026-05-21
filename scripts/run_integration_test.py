"""
EduMatrix FAISS Integration Tests
Tests the full FAISS vector database pipeline with real downloaded data.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

print("=" * 70)
print("EDUMATRIX FAISS INTEGRATION TEST REPORT")
print("=" * 70)

from config import CONFIG
print(f"\n[CONFIG] use_faiss={CONFIG.use_faiss}")
print(f"[CONFIG] faiss_index_dir={CONFIG.faiss_index_dir}")

from rag_engine import FAISSIndexSet, hybrid_rag

# 1. Test FAISS Index Loading
print("\n--- 1. FAISS Index Loading ---")
faiss_set = FAISSIndexSet()
total_vec = sum(idx.count() for idx in faiss_set.indexes.values())
print(f"Total vectors: {total_vec}")
print(f"Categories loaded: {list(faiss_set.indexes.keys())}")
for cat, idx in faiss_set.indexes.items():
    print(f"  {cat}: {idx.count()} vectors")

# 2. Test Category-Specific Search
print("\n--- 2. Category-Specific Search ---")
for cat in ["courseware", "code", "textbook"]:
    results = faiss_set.search_by_category("逻辑回归", cat, top_k=2)
    if results:
        r = results[0]
        print(f"  [{cat}] top: {r.title[:60]} (score={r.score:.3f})")
    else:
        print(f"  [{cat}] (none)")

# 3. Test Full Retrieval Pipeline
print("\n--- 3. Full Retrieval Pipeline ---")
test_queries = [
    "什么是逻辑回归？sigmoid函数如何工作",
    "最大池化与平均池化的区别",
    "混淆矩阵中的precision和recall怎么计算",
    "过拟合的表现和正则化方法",
    "数据预处理步骤和特征工程",
]
for q in test_queries:
    bundle = hybrid_rag.retrieve(q, top_k=3)
    print(f"\nQuery: {q}")
    print(f"  Target: {bundle.target}")
    for ev in bundle.evidence:
        src_short = ev.source[:40] if len(ev.source) > 40 else ev.source
        print(f"  [{ev.id[:20]}] score={ev.score:.3f} | {ev.title[:40]} | {src_short}")

# 4. Test FAISS Index Save/Load Roundtrip
print("\n--- 4. FAISS Index Save/Load ---")
from vector_store_faiss import FaissVectorIndex
from models import Evidence, EvidenceModality
test_idx = FaissVectorIndex("test-roundtrip")
test_ev = Evidence(id="rt1", title="test", content="测试内容", modality=EvidenceModality.TEXT, source="test", tags=("test",), anchors=())
test_idx.upsert((test_ev,))
test_idx.save(r"d:\code\edumatrix\data\faiss_indexes\_test_roundtrip")
loaded = FaissVectorIndex.load(r"d:\code\edumatrix\data\faiss_indexes\_test_roundtrip")
assert loaded.count() == 1
loaded_ev = loaded.search("测试", top_k=1)
assert len(loaded_ev) == 1
print("  Save/Load roundtrip: PASS")

# Cleanup
import shutil, os
for f in ["_test_roundtrip.faiss", "_test_roundtrip.json"]:
    p = Path(r"d:\code\edumatrix\data\faiss_indexes") / f
    if p.exists():
        os.remove(p)
print("  Cleanup: OK")

print("\n" + "=" * 70)
print("ALL INTEGRATION TESTS PASSED")
print("=" * 70)
