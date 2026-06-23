# Task: 完整实现并验证赛题重点二「多智能体协同的资源生成」

## Goal
赛题重点二要求系统体现多智能体(Multi-Agent)架构设计，由不同角色智能体协作生成至少5种类型的个性化资源。

## Scope
- 验证 `agent_swarm.py` 中的 AGENT_MATRIX / EduMatrixSwarm / AsyncResourceFactory
- 验证 `swarm_factory.py` 的智能体工厂模式
- 验证 `code_exec_api.py` 的沙箱隔离
- 验证前端 SandboxConsole.vue 的可视化终端
- 实现所有缺失的功能，确保5种资源类型（theory/mapper/coder/quiz/director）能正常生成

## Non-goals
- 不改动数据库/ORM层
- 不改动RAG引擎核心
- 不改动API路由层

## Success Criteria
1. [SC1] AGENT_MATRIX 定义了 1+3+5 共9个智能体角色
2. [SC2] `AsyncResourceFactory.generate_all` 使用 asyncio.gather 并发生成5种资源
3. [SC3] coder 生成的可执行代码能通过沙箱安全运行
4. [SC4] 每种资源类型（theory/mapper/coder/quiz/director）的输出格式正确
5. [SC5] 系统现有 18 项自动化测试全部通过
6. [SC6] 新增集成测试验证多智能体并发生成
