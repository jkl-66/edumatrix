# Task: 验证并实现「3次答错掌握度上限锁死」硬拦截机制

## Goal
赛题重点一要求画像系统具备「客观信号优先防膨胀锁死」机制：若某概念最近3次客观答题正确率低于0.6，则该概念掌握度物理上限被强行卡死在0.5以下，元认知偏差上调30%。

## Scope
- 验证 `models.py` 中是否已实现该逻辑
- 如缺失，在正确的层级实现该逻辑
- 确保原有 17 项自动化测试仍然全部通过
- 添加针对此逻辑的专门测试

## Non-goals
- 不改动前端代码
- 不改动 RAG / Swarm / BKT 引擎逻辑
- 不改变现有 API 接口契约

## Success Criteria
1. [SC1] `StudentProfile._refresh_dynamic_profile` 或等效路径中存在硬拦截逻辑
2. [SC2] 当某概念 recent_quiz_accuracy 中最近3次平均值 < 0.6 时，concept_mastery 被 cap 到 ≤ 0.5
3. [SC3] 元认知偏差 metacognitive_mismatch 上调 30%
4. [SC4] 原有 17 项 pytest 全部通过
5. [SC5] 新增的专项测试验证了 SC2 和 SC3

## Verification Gates
- Gate 1: grep/model-inspection 确认当前代码中是否存在该逻辑
- Gate 2: 编写集成测试验证该逻辑
- Gate 3: 全量 pytest 回归
