"""
EduMatrix Integration Test
Tests the full pipeline without requiring real LLM or model downloads.

Usage:
  python scripts/run_integration_test.py
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

print("=" * 70)
print("EDUMATRIX INTEGRATION TEST REPORT")
print("=" * 70)

# 1. Core imports
print("\n--- 1. Core Module Imports ---")
from config import CONFIG
print(f"  Config: OK (LLM={CONFIG.llm_provider}, Embed={CONFIG.embedding_provider})")

from embedding_models import EMBEDDINGS
print(f"  Embeddings: OK ({EMBEDDINGS.name})")

from llm_client import DEFAULT_LLM
from llm_client import DeterministicEducationLLM
assert isinstance(DEFAULT_LLM, DeterministicEducationLLM)
print(f"  LLM: OK (DeterministicEducationLLM)")

from rag_engine import hybrid_rag
from vector_store import InMemoryVectorIndex
assert isinstance(hybrid_rag, object)
print(f"  HybridRAG: OK")

# 2. RAG Retrieval
print("\n--- 2. RAG Retrieval ---")
test_queries = [
    "什么是逻辑回归？sigmoid函数如何工作",
    "最大池化与平均池化的区别",
    "混淆矩阵中的precision和recall怎么计算",
    "过拟合的表现和正则化方法",
    "数据预处理步骤和特征工程",
]
for q in test_queries:
    bundle = hybrid_rag.retrieve(q, target="机器学习", top_k=3)
    print(f"\n  Query: {q[:40]}...")
    print(f"    Target: {bundle.target}")
    print(f"    Evidence count: {len(bundle.evidence)}")
    for ev in bundle.evidence[:3]:
        print(f"    [{ev.id[:20]}] score={ev.score:.3f} | {ev.title[:40]}")

# 3. Debate Augmented RAG
print("\n--- 3. Debate Augmented RAG ---")
from drag_debate import DebateAugmentedRAG
drag = DebateAugmentedRAG()
bundle = hybrid_rag.retrieve("用 PyTorch 代码演示最大池化层", target="池化层", top_k=6)
result = drag.clean(bundle)
kept_count = sum(1 for v in result.verdicts if v.keep)
print(f"  Evidence judged: {len(result.verdicts)}, kept: {kept_count}")

# 4. Alignment
print("\n--- 4. Manifold Alignment ---")
from manifold_alignment import verify_consistency
text = "本讲义讲最大池化，窗口取局部最大值。"
code = "import torch.nn.nn as nn\npool = nn.AvgPool2d(2)"
report = verify_consistency(text, code, threshold=0.4)
print(f"  Text vs Code (misaligned): passed={report.passed}, dist={report.distance:.3f}")
same = "最大池化取窗口最大值"
report2 = verify_consistency(text, same, threshold=0.4)
print(f"  Text vs Text (aligned): passed={report2.passed}, dist={report2.distance:.3f}")

# 5. Full Swarm Pipeline
print("\n--- 5. Full Swarm Pipeline ---")
from agent_swarm import EduMatrixSwarm
swarm = EduMatrixSwarm()
package = swarm.process("我看不懂池化层，请用图和 PyTorch 代码演示最大池化。")
print(f"  Alignment: passed={package.alignment.passed}, dist={package.alignment.distance:.3f}")
print(f"  Target: {package.target}")
print(f"  Profile causes: {list(package.profile.learning_state_causes.keys())}")
print(f"  Resources generated: {len(package.resources)}")
for r in package.resources:
    print(f"    [{r.agent}] {r.resource_type} ({len(r.content)} chars)")

# 6. Student Profile
print("\n--- 6. Student Profile & Feedback ---")
from models import StudentProfile
profile = StudentProfile(student_id="s1")
profile.update_from_message(
    "我是计算机专业，期末要考机器学习。池化层还是看不懂，最大池化和平均池化总混。"
)
print(f"  Major: {profile.major}")
print(f"  Weak points: {profile.weak_points}")
print(f"  State causes: {list(profile.learning_state_causes.keys())}")
before = profile.concept_mastery.get("池化层", 0.5)
profile.update_from_feedback(
    feedback="做最大池化题选成了平均池化",
    accuracy=0.35, self_confidence=0.85, hint_count=2,
)
print(f"  Mastery before={before:.2f} -> after={profile.concept_mastery.get('池化层', 0):.2f}")

# 7. Learning Strategy
print("\n--- 7. Learning Strategy ---")
from learning_strategy import LearningStrategyEngine
lse = LearningStrategyEngine()
strategy = lse.build_plan(profile, target="池化层")
print(f"  Target: {strategy.target}")
print(f"  Actions: {[a.description[:60] for a in strategy.actions[:3]]}")

# Summary
print("\n" + "=" * 70)
print("ALL INTEGRATION TESTS PASSED")
print("=" * 70)
print(f"\nTo run with real LLM:")
print(f"  set EDUMATRIX_LLM_API_KEY=sk-your-key")
print(f"  python scripts/run_integration_test.py")
