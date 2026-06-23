# Task: 完整验证赛题重点三「个性化路径规划与资源推送」

## Goal
验证 ZPD 路径规划算法、自适应二档教学机制、前置依赖回滚机制和前端 DAG 图谱展示全部正常工作。

## Scope
- bkt_engine.py: get_zpd_path_plan, classify_zpd_zone, should_rollback_to_prerequisites
- agent_swarm.py: SwarmMediationRouter.decide_mode, get_forced_instructions
- learning_strategy.py: 自适应难度齿轮和策略计划
- frontend/src/components/LearningPathGraph.vue

## Success Criteria
1. [SC1] ZPD 区间 [0.3, 0.75] 正确分类：below/in/above
2. [SC2] 掌握度<0.3 且前置不足 → 前置依赖回滚机制触发
3. [SC3] 掌握度<50% → SIMPLIFIED_MODE 降维指令注入
4. [SC4] 掌握度>80% → ADVANCED_MODE 进阶指令注入
5. [SC5] LearningPathGraph.vue 存在且可渲染 DAG
6. [SC6] 全部现有测试通过 + 新增边界测试
