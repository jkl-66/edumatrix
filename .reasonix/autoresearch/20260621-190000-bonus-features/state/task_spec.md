# Task: 完整实现并验证加分项功能 + 非功能性需求

## Goal
赛题加分项一（智能辅导）、加分项二（学习效果评估）、非功能性需求（高可用/防幻觉/安全）全部真实完整实现并通过测试。

## Scope
- Bonus 1: Chat.vue行级答疑, drag_debate.py, VisRAG图片, AvatarSpeech.vue数字人语音
- Bonus 2: quiz.py, event_bus.py, WrongQuestionBook.vue, SM-2/anki, PDF导出
- Non-func: rag_engine置信度熔断, manifold_alignment, concurrency.py, database.py多租户隔离

## Success Criteria
1. [SC1] Line-level Socratic答疑交互（Chat.vue点击代码行/公式弹出悬浮框）
2. [SC2] VisRAG 7张内置图片 data/patches/ 可被引用渲染
3. [SC3] AvatarSpeech.vue 数字人语音播报（讯飞TTS + 嘴形滤波）
4. [SC4] LearningEventBus 松耦合学情事件订阅发布
5. [SC5] 错题本 WrongQuestionBook.vue + 3D Anki SM-2 迭代
6. [SC6] 同阶相似题防矛盾机制
7. [SC7] PDF报告一键导出（Playwright）
8. [SC8] RAG低置信度<0.20熔断拒答
9. [SC9] Poincaré双曲流形对齐
10. [SC10] concurrency.py熔断器+令牌桶
11. [SC11] 多租户数据库连接池洗白
12. [SC12] 全部现有20项测试通过 + 新增测试
