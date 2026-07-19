# 🗺️ EduMatrix 智教矩阵系统代码图谱 (Code Graph)

本项目使用 Python AST 静态分析引擎自动提取并生成了本代码图谱，清晰展示了系统的模块划分、依赖关系、类与核心方法。本设计旨在帮助评审专家及开发团队快速理解系统底层的模块拓扑结构。

## 📈 系统整体统计 (System Stats)

- **总模块数 (Python Files)**: 102
- **总定义类数 (Classes)**: 153
- **顶级函数数 (Functions)**: 260
- **模块间显式物理依赖数 (Dependencies)**: 155

## 🔗 模块物理依赖拓扑图 (Module Dependency Graph)

```mermaid
flowchart TD
    agent_swarm["agent_swarm.py"]:::coreNode
    animation_api["animation_api.py"]:::coreNode
    animation_resources["animation_resources.py"]:::coreNode
    anki_engine["anki_engine.py"]:::coreNode
    app_agents_coder["app/agents/coder.py"]:::appNode
    app_auth["app/auth.py"]:::appNode
    app_crud["app/crud.py"]:::appNode
    app_database["app/database.py"]:::appNode
    app_main["app/main.py"]:::appNode
    app_utils___init__["app/utils/__init__.py"]:::appNode
    app_utils_event_bus["app/utils/event_bus.py"]:::appNode
    app_utils_exceptions["app/utils/exceptions.py"]:::appNode
    app_utils_formula_extractor["app/utils/formula_extractor.py"]:::appNode
    app_utils_formula_rag["app/utils/formula_rag.py"]:::appNode
    app_utils_graph_builder["app/utils/graph_builder.py"]:::appNode
    app_utils_graph_models["app/utils/graph_models.py"]:::appNode
    app_utils_recommendation_engine["app/utils/recommendation_engine.py"]:::appNode
    app_utils_rl_planner["app/utils/rl_planner.py"]:::appNode
    behavior_api["behavior_api.py"]:::coreNode
    bkt_engine["bkt_engine.py"]:::coreNode
    code_exec_api["code_exec_api.py"]:::coreNode
    concurrency["concurrency.py"]:::coreNode
    config["config.py"]:::coreNode
    content_safety["content_safety.py"]:::coreNode
    document_parser["document_parser.py"]:::coreNode
    drag_debate["drag_debate.py"]:::coreNode
    embedding_models["embedding_models.py"]:::coreNode
    export_pdf["export_pdf.py"]:::coreNode
    fix["fix.py"]:::coreNode
    flashcard_api["flashcard_api.py"]:::coreNode
    ingestion["ingestion.py"]:::coreNode
    instruct_rag["instruct_rag.py"]:::coreNode
    knowledge_api["knowledge_api.py"]:::coreNode
    knowledge_base["knowledge_base.py"]:::coreNode
    learning_event_bus["learning_event_bus.py"]:::coreNode
    learning_strategy["learning_strategy.py"]:::coreNode
    llm_client["llm_client.py"]:::coreNode
    manifold_alignment["manifold_alignment.py"]:::coreNode
    math_utils["math_utils.py"]:::coreNode
    mirt_engine["mirt_engine.py"]:::coreNode
    models["models.py"]:::coreNode
    multimodal_alignment["multimodal_alignment.py"]:::coreNode
    note_engine["note_engine.py"]:::coreNode
    observability["observability.py"]:::coreNode
    profile_api["profile_api.py"]:::coreNode
    quiz_api["quiz_api.py"]:::coreNode
    rag_engine["rag_engine.py"]:::coreNode
    report_api["report_api.py"]:::coreNode
    retrieval_evaluation["retrieval_evaluation.py"]:::coreNode
    run["run.py"]:::coreNode
    scratch_check_bvid["scratch/check_bvid.py"]:::coreNode
    scratch_check_chat_root["scratch/check_chat_root.py"]:::coreNode
    scratch_check_db["scratch/check_db.py"]:::coreNode
    scratch_check_simhei_glyphs["scratch/check_simhei_glyphs.py"]:::coreNode
    scratch_debug_bing_html["scratch/debug_bing_html.py"]:::coreNode
    scratch_debug_bing_video["scratch/debug_bing_video.py"]:::coreNode
    scratch_debug_pdf_trace["scratch/debug_pdf_trace.py"]:::coreNode
    scratch_find_3b1b_bvid["scratch/find_3b1b_bvid.py"]:::coreNode
    scratch_find_all_non_test_users["scratch/find_all_non_test_users.py"]:::coreNode
    scratch_find_template_close["scratch/find_template_close.py"]:::coreNode
    scratch_find_template_end["scratch/find_template_end.py"]:::coreNode
    scratch_find_user_data["scratch/find_user_data.py"]:::coreNode
    scratch_fix_export_pdf["scratch/fix_export_pdf.py"]:::coreNode
    scratch_get_file_times["scratch/get_file_times.py"]:::coreNode
    scratch_query_db["scratch/query_db.py"]:::coreNode
    scratch_query_db_backup["scratch/query_db_backup.py"]:::coreNode
    scratch_query_db_backup_demo["scratch/query_db_backup_demo.py"]:::coreNode
    scratch_query_db_backup_lzz["scratch/query_db_backup_lzz.py"]:::coreNode
    scratch_query_db_test["scratch/query_db_test.py"]:::coreNode
    scratch_query_db_v2["scratch/query_db_v2.py"]:::coreNode
    scratch_restore_db["scratch/restore_db.py"]:::coreNode
    scratch_restore_truncate["scratch/restore_truncate.py"]:::coreNode
    scratch_search_html_occurrences["scratch/search_html_occurrences.py"]:::coreNode
    scratch_test_alternative_search["scratch/test_alternative_search.py"]:::coreNode
    scratch_test_baidu_search["scratch/test_baidu_search.py"]:::coreNode
    scratch_test_bili_api["scratch/test_bili_api.py"]:::coreNode
    scratch_test_bili_cookie["scratch/test_bili_cookie.py"]:::coreNode
    scratch_test_bili_search["scratch/test_bili_search.py"]:::coreNode
    scratch_test_bing_redirect["scratch/test_bing_redirect.py"]:::coreNode
    scratch_test_bing_search["scratch/test_bing_search.py"]:::coreNode
    scratch_test_bing_unicode["scratch/test_bing_unicode.py"]:::coreNode
    scratch_test_code_font["scratch/test_code_font.py"]:::coreNode
    scratch_test_export_api["scratch/test_export_api.py"]:::coreNode
    scratch_test_helvetica_chinese["scratch/test_helvetica_chinese.py"]:::coreNode
    scratch_test_keyword_search["scratch/test_keyword_search.py"]:::coreNode
    scratch_test_math_pdf["scratch/test_math_pdf.py"]:::coreNode
    scratch_test_pdf_long_code["scratch/test_pdf_long_code.py"]:::coreNode
    scratch_test_profile_robustness["scratch/test_profile_robustness.py"]:::coreNode
    scratch_test_quote["scratch/test_quote.py"]:::coreNode
    scratch_test_screenshot_formulas["scratch/test_screenshot_formulas.py"]:::coreNode
    scratch_test_search_videos["scratch/test_search_videos.py"]:::coreNode
    scratch_test_subsup["scratch/test_subsup.py"]:::coreNode
    scratch_test_ultimate_sanitizer["scratch/test_ultimate_sanitizer.py"]:::coreNode
    scratch_try_delete["scratch/try_delete.py"]:::coreNode
    stream_api["stream_api.py"]:::coreNode
    swarm_factory["swarm_factory.py"]:::coreNode
    swarm_orchestrator["swarm_orchestrator.py"]:::coreNode
    test_edumatrix["test_edumatrix.py"]:::coreNode
    vector_store["vector_store.py"]:::coreNode
    vector_store_faiss["vector_store_faiss.py"]:::coreNode
    web_demo["web_demo.py"]:::coreNode
    web_search_api["web_search_api.py"]:::coreNode
    agent_swarm --> concurrency
    agent_swarm --> config
    agent_swarm --> drag_debate
    agent_swarm --> instruct_rag
    agent_swarm --> learning_strategy
    agent_swarm --> llm_client
    agent_swarm --> manifold_alignment
    agent_swarm --> models
    agent_swarm --> observability
    agent_swarm --> rag_engine
    animation_api --> animation_resources
    app_auth --> app_database
    app_auth --> config
    app_crud --> app_database
    app_crud --> models
    app_main --> animation_api
    app_main --> app_auth
    app_main --> app_crud
    app_main --> app_database
    app_main --> behavior_api
    app_main --> code_exec_api
    app_main --> concurrency
    app_main --> config
    app_main --> export_pdf
    app_main --> flashcard_api
    app_main --> knowledge_api
    app_main --> models
    app_main --> note_engine
    app_main --> observability
    app_main --> profile_api
    app_main --> quiz_api
    app_main --> report_api
    app_main --> stream_api
    app_main --> swarm_factory
    app_main --> web_search_api
    app_utils_event_bus --> learning_event_bus
    app_utils_formula_extractor --> app_utils_exceptions
    app_utils_formula_extractor --> embedding_models
    app_utils_formula_extractor --> models
    app_utils_formula_rag --> app_utils_exceptions
    app_utils_formula_rag --> app_utils_formula_extractor
    app_utils_formula_rag --> config
    app_utils_formula_rag --> embedding_models
    app_utils_formula_rag --> models
    app_utils_graph_builder --> app_utils_exceptions
    app_utils_graph_builder --> app_utils_graph_models
    app_utils_graph_builder --> config
    app_utils_graph_builder --> embedding_models
    app_utils_recommendation_engine --> app_database
    app_utils_recommendation_engine --> models
    app_utils_recommendation_engine --> rag_engine
    behavior_api --> app_crud
    behavior_api --> app_database
    behavior_api --> models
    code_exec_api --> app_database
    code_exec_api --> config
    drag_debate --> config
    drag_debate --> models
    embedding_models --> config
    flashcard_api --> app_crud
    flashcard_api --> app_database
    ingestion --> config
    ingestion --> models
    ingestion --> vector_store
    instruct_rag --> llm_client
    instruct_rag --> models
    knowledge_api --> app_database
    knowledge_api --> document_parser
    knowledge_api --> ingestion
    knowledge_api --> rag_engine
    knowledge_base --> config
    knowledge_base --> models
    learning_strategy --> animation_resources
    learning_strategy --> embedding_models
    learning_strategy --> models
    llm_client --> concurrency
    llm_client --> config
    manifold_alignment --> embedding_models
    manifold_alignment --> models
    note_engine --> llm_client
    profile_api --> app_crud
    profile_api --> app_database
    profile_api --> learning_strategy
    profile_api --> swarm_factory
    quiz_api --> app_crud
    quiz_api --> app_database
    quiz_api --> code_exec_api
    quiz_api --> learning_event_bus
    quiz_api --> swarm_factory
    rag_engine --> config
    rag_engine --> embedding_models
    rag_engine --> knowledge_base
    rag_engine --> math_utils
    rag_engine --> models
    rag_engine --> observability
    rag_engine --> vector_store
    report_api --> app_crud
    report_api --> app_database
    retrieval_evaluation --> models
    retrieval_evaluation --> rag_engine
    scratch_check_db --> app_database
    scratch_debug_pdf_trace --> export_pdf
    scratch_test_baidu_search --> web_search_api
    scratch_test_bili_search --> web_search_api
    scratch_test_bing_search --> web_search_api
    scratch_test_bing_unicode --> web_search_api
    scratch_test_code_font --> export_pdf
    scratch_test_export_api --> app_main
    scratch_test_helvetica_chinese --> export_pdf
    scratch_test_keyword_search --> web_search_api
    scratch_test_math_pdf --> export_pdf
    scratch_test_pdf_long_code --> export_pdf
    scratch_test_profile_robustness --> app_crud
    scratch_test_profile_robustness --> app_database
    scratch_test_profile_robustness --> learning_event_bus
    scratch_test_profile_robustness --> models
    scratch_test_profile_robustness --> profile_api
    scratch_test_quote --> export_pdf
    scratch_test_screenshot_formulas --> export_pdf
    scratch_test_search_videos --> web_search_api
    scratch_test_ultimate_sanitizer --> export_pdf
    stream_api --> content_safety
    stream_api --> models
    stream_api --> swarm_factory
    swarm_factory --> agent_swarm
    swarm_factory --> llm_client
    swarm_factory --> rag_engine
    swarm_orchestrator --> agent_swarm
    swarm_orchestrator --> observability
    test_edumatrix --> agent_swarm
    test_edumatrix --> app_database
    test_edumatrix --> drag_debate
    test_edumatrix --> ingestion
    test_edumatrix --> instruct_rag
    test_edumatrix --> llm_client
    test_edumatrix --> manifold_alignment
    test_edumatrix --> models
    test_edumatrix --> observability
    test_edumatrix --> rag_engine
    test_edumatrix --> retrieval_evaluation
    test_edumatrix --> vector_store
    test_edumatrix --> web_demo
    vector_store --> embedding_models
    vector_store --> models
    vector_store_faiss --> embedding_models
    vector_store_faiss --> models
    vector_store_faiss --> vector_store
    web_demo --> agent_swarm
    web_demo --> models
    web_demo --> observability
    web_search_api --> app_database
    web_search_api --> document_parser
    web_search_api --> models
    web_search_api --> rag_engine
    web_search_api --> swarm_factory

    classDef coreNode fill:#f9f,stroke:#333,stroke-width:2px,color:#333;
    classDef appNode fill:#bbf,stroke:#333,stroke-width:1px,color:#333;
```

## 📝 模块详细字典 (Module Reference Dictionary)

### 📄 [agent_swarm.py](file:///d:/project-edumatrix/edumatrix-main/agent_swarm.py)

**文件路径**: `agent_swarm.py`

> *暂无详细模块级别文档注释.*

#### 📦 类定义 (Classes)

- **`class AgentSpec`**: *无类文档*
- **`class ProfileProbeAgent`**: 画像探针智能体。
  - **核心方法 (Methods)**:
    - `__init__()`: *无描述*
    - `update()`: *无描述*
    - `_get_sliding_context()`: 构建 3 轮滑动上下文窗口。
- **`class ZPDPlannerAgent`**: ZPD（最近发展区）路径规划智能体。
  - **核心方法 (Methods)**:
    - `__init__()`: *无描述*
    - `plan()`: 执行 ZPD 路径规划。
    - `get_path_plan()`: *无描述*
    - `_extract_concept_from_query()`: *无描述*
    - `_infer_target()`: *无描述*
- **`class SwarmMediationMode`**: Swarm 全局运行模式。
- **`class SwarmMediationRouter`**: 多门控自适应 FSM 路由器 (SwarmMediationRouter)。
  - **核心方法 (Methods)**:
    - `__init__()`: *无描述*
    - `current_mode()`: *无描述*
    - `record_attempt()`: 记录一次答题结果。
    - `decide_mode()`: 基于硬规则决策当前运行模式。
    - `get_forced_instructions()`: 根据当前模式返回强制注入各智能体的指令。
    - `to_prompt()`: 生成可注入 Swarm 系统提示词的模式描述。
- **`class EffectEvaluatorAgent`**: 量化评估师 — 使用 LLM 评估资源包质量，触发重规划决策。
  - **核心方法 (Methods)**:
    - `__init__()`: *无描述*
    - `evaluate()`: *无描述*
    - `_llm_evaluate()`: *无描述*
    - `_fallback_evaluate()`: 回退：硬编码公式版。
- **`class AsyncResourceFactory`**: *无类文档*
  - **核心方法 (Methods)**:
    - `__init__()`: *无描述*
    - `_build_strategy_injections()`: 将策略计划翻译为各角色的强制注入指令（任务 10.2 核心）。
    - `_get_learning_style_priority()`: 任务 7.9: 根据学习风格调整生成资源的排版优先级。
- **`class CausalConflictAttributionEngine`**: 因果冲突归因与自愈引擎：分析多模态对齐校验冲突，定位根本责任 Agent 并生成自愈校准指令。
  - **核心方法 (Methods)**:
    - `attribute_and_heal()`: 归因决策核心：返回需要追加到特定 Agent 下次生成时的自愈指令字典 {agent_name: healing_instruction}。
- **`class EduMatrixSwarm`**: 1+3+5 full-band orchestration for EduMatrix with async concurrency control.
  - **核心方法 (Methods)**:
    - `__init__()`: *无描述*
    - `process()`: *无描述*

#### ⚙️ 独立函数 (Functions)

- `_build_conversation_memory()`: *无描述*
- `_resolve_coreference()`: 口语指代消解：将模糊指代归一化为已追踪的核心知识点。
- `_get_bkt_engine()`: 获取全局 BKT 引擎单例。
- `render_console_summary()`: *无描述*

---

### 📄 [animation_api.py](file:///d:/project-edumatrix/edumatrix-main/animation_api.py)

**文件路径**: `animation_api.py`

> animation_api.py — 本地动画视频服务
提供知识点 → 本地视频文件的映射和静态文件服务

#### ⚙️ 独立函数 (Functions)

- `_animations_dir()`: *无描述*
- `_get_knowledge_videos()`: 获取某个知识点下的所有本地视频文件

---

### 📄 [animation_resources.py](file:///d:/project-edumatrix/edumatrix-main/animation_resources.py)

**文件路径**: `animation_resources.py`

> *暂无详细模块级别文档注释.*

#### ⚙️ 独立函数 (Functions)

- `candidate_animation_dirs()`: Return animation dataset locations in precedence order.
- `find_animation_dir()`: *无描述*
- `_load_json()`: *无描述*
- `_media_type_for_file()`: *无描述*
- `_local_files()`: *无描述*
- `load_animation_resource_index()`: Load local animation metadata keyed by knowledge point.
- `clear_animation_resource_cache()`: *无描述*

---

### 📄 [anki_engine.py](file:///d:/project-edumatrix/edumatrix-main/anki_engine.py)

**文件路径**: `anki_engine.py`

> 任务 7.5: 自适应 Anki 间隔记忆闪卡与 SM-2 间隔重复引擎

核心公式：
1. 易度因子更新: E' = max(1.3, E + (0.1 - (5-q)) * (0.08 + (5-q) * 0.02))
2. 复习间隔迭代: I' = I * E (q>=4 时); I' = 1 (q<4 时)

#### 📦 类定义 (Classes)

- **`class FlashCard`**: 记忆闪卡数据结构。
  - **核心方法 (Methods)**:
    - `schedule()`: 根据质量评分与学生画像状态（认知负荷、挫败感）动态更新复习参数。
    - `to_dict()`: *无描述*
- **`class SM2Engine`**: SM-2 间隔重复引擎，管理全局闪卡库。
  - **核心方法 (Methods)**:
    - `__init__()`: *无描述*
    - `get_or_create()`: *无描述*
    - `review()`: 执行一次复习，更新 SM-2 参数。
    - `get_due_cards()`: 获取到期待复习的闪卡。
    - `get_all_cards()`: *无描述*
    - `to_dict()`: *无描述*

#### ⚙️ 独立函数 (Functions)

- `sm2_update_easiness()`: SM-2 易度因子更新公式。
- `calculate_act_r_decay()`: 根据 ACT-R 理论计算动态记忆衰减率 d (通常范围在 0.3 到 0.7 之间，默认值为 0.5)
- `sm2_next_interval()`: 自适应复习间隔：底层切换为 FSRS (DSR) 核心记忆状态方程，并通过 ACT-R 情感状态自适应调节。
- `sm2_schedule()`: 完整自适应 SM-2 调度：同时考虑作答质量与认知负荷、挫败感。
- `get_sm2_engine()`: *无描述*

---

### 📄 [coder.py](file:///d:/project-edumatrix/edumatrix-main/app/agents/coder.py)

**文件路径**: `app/agents/coder.py`

> *暂无详细模块级别文档注释.*

#### 📦 类定义 (Classes)

- **`class PyTorchPoolCodeSchema`**: *无类文档*

---

### 📄 [auth.py](file:///d:/project-edumatrix/edumatrix-main/app/auth.py)

**文件路径**: `app/auth.py`

> *暂无详细模块级别文档注释.*

#### ⚙️ 独立函数 (Functions)

- `verify_password()`: 验证明文密码是否与哈希密码匹配
- `get_password_hash()`: 对明文密码进行哈希处理
- `create_access_token()`: 创建 JWT 访问令牌，包含用户角色
- `authenticate_user()`: 验证用户凭据并返回用户对象

---

### 📄 [crud.py](file:///d:/project-edumatrix/edumatrix-main/app/crud.py)

**文件路径**: `app/crud.py`

> *暂无详细模块级别文档注释.*

#### ⚙️ 独立函数 (Functions)

- `to_dict_safe()`: 递归将 dataclass 转换为字典，安全避免 Enum/类型 循环递归
- `calibrate_student_prior_collaborative()`: 协同画像先验校准：若当前画像无掌握度数据，寻找相似 Peer 的特征均值进行初始化。
- `load_student_profile()`: 从 SQLite 中加载学生画像，如果不存在则初始化并存入数据库
- `save_student_profile()`: 持久化保存/更新学生画像至 SQLite 数据库，实现事务性保存
- `record_alignment_log()`: 记录每一次流形对齐校验的测地线距离与冲突建议
- `create_note()`: *无描述*
- `get_notes()`: *无描述*
- `delete_note()`: *无描述*
- `update_note()`: *无描述*
- `append_wrong_question_reflection()`: *无描述*
- `_utcnow_naive()`: *无描述*
- `_as_utc_naive()`: *无描述*
- `review_plan_to_dict()`: *无描述*
- `get_review_plan()`: *无描述*
- `upsert_review_plan()`: *无描述*
- `delete_review_plan()`: *无描述*
- `apply_review_feedback()`: *无描述*
- `record_conversation()`: *无描述*
- `get_conversation_history()`: *无描述*
- `migrate_anonymous_data()`: 将匿名临时ID(anon_id)产生的所有学情数据迁移/合并到正式账号(target_id)下，

---

### 📄 [database.py](file:///d:/project-edumatrix/edumatrix-main/app/database.py)

**文件路径**: `app/database.py`

> *暂无详细模块级别文档注释.*

#### 📦 类定义 (Classes)

- **`class DBStudentProfile`**: 持久化物理表：存储学生 10 维画像、掌握度、认知负荷与学习偏好
- **`class DBUser`**: 用户表：存储登录凭证
- **`class DBAlignmentLog`**: *无类文档*
- **`class DBNote`**: *无类文档*
- **`class DBReviewPlan`**: 持久化物理表：SM-2 间隔重复复习计划
- **`class DBConversationHistory`**: *无类文档*
- **`class DBKnowledgeDocument`**: 持久化物理表：存储用户上传的知识库文档
- **`class DBQuizRecord`**: 持久化物理表：存储测验记录与置信度反馈
- **`class DBQuizItem`**: 持久化物理表：本地预置种子题库
- **`class DBWebSearchHistory`**: 持久化物理表：存储联网搜索与文档加载记录
- **`class DBCodeExecution`**: 持久化物理表：存储代码执行记录
- **`class DBWrongQuestion`**: 持久化物理表：存储错题记录 (Task 6.2)
- **`class DBCheckinLog`**: 持久化物理表：复习打卡日志 (Task 7.4)
- **`class DBArxivCache`**: 持久化物理表：arXiv 学术检索本地缓存 (Task 2.4)
- **`class DBConceptCoordinate`**: 持久化物理表：存储概念在庞加莱圆盘中的2D投影坐标缓存 (MDS 投影缓存)

#### ⚙️ 独立函数 (Functions)

- `_utcnow()`: *无描述*
- `set_tenant()`: 上下文管理器，用于安全地切换和恢复当前协程的租户上下文
- `on_connection_checkin()`: *无描述*
- `set_sqlite_pragma()`: *无描述*
- `before_cursor_execute()`: *无描述*
- `init_db()`: *无描述*
- `_migrate_schema()`: SQLite 增量迁移：添加新列（如存在则跳过）
- `get_db()`: *无描述*

---

### 📄 [main.py](file:///d:/project-edumatrix/edumatrix-main/app/main.py)

**文件路径**: `app/main.py`

> *暂无详细模块级别文档注释.*

#### ⚙️ 独立函数 (Functions)

- `_seed_demo_class()`: 初始化数据库种子数据（演示专用学生）
- `_profile_card()`: *无描述*
- `_resource_summary()`: *无描述*
- `_package_response()`: *无描述*
- `calc_avg_mastery()`: 计算单个画像的平均掌握度

---

### 📄 [__init__.py](file:///d:/project-edumatrix/edumatrix-main/app/utils/__init__.py)

**文件路径**: `app/utils/__init__.py`

> EduMatrix 后端工具集：图谱构建、公式抽取、双轨检索。

---

### 📄 [event_bus.py](file:///d:/project-edumatrix/edumatrix-main/app/utils/event_bus.py)

**文件路径**: `app/utils/event_bus.py`

> app/utils/event_bus.py — 兼容 re-export of learning_event_bus.

The canonical implementation lives at learning_event_bus.py.
This module re-exports all public symbols for the documented path.

---

### 📄 [exceptions.py](file:///d:/project-edumatrix/edumatrix-main/app/utils/exceptions.py)

**文件路径**: `app/utils/exceptions.py`

> 集中异常模块（替代抛裸 HTTPException / RuntimeError）。

#### 📦 类定义 (Classes)

- **`class EduMatrixUtilError`**: 工具子系统统一基类。
- **`class GraphBuilderError`**: 图谱构建（三元组抽取 / Neo4j 写入 / 实体对齐）类异常。
- **`class TripletExtractionError`**: LLM 返回非约束 JSON / 解析失败。
- **`class GraphRepositoryError`**: Neo4j 或图存储后端写入失败。
- **`class FormulaExtractionError`**: Layout/OCR 公式抽取失败。
- **`class FormulaIndexError`**: 公式向量库读写失败。

---

### 📄 [formula_extractor.py](file:///d:/project-edumatrix/edumatrix-main/app/utils/formula_extractor.py)

**文件路径**: `app/utils/formula_extractor.py`

> Layout 分析与公式 LaTeX 抽取模块。

职责:
  1. 从课件/课本图像中检测公式区域 (LayoutLMv3 / 规则降级)
  2. 将公式区域转换为 LaTeX 标准串 (Pix2Text / 规则降级)
  3. 生成 Jinja2 增强格式文本: [LaTeX_Source: ...] (公式语义解释: ...)

#### 📦 类定义 (Classes)

- **`class FormulaRegion`**: 图像中检测到的公式区域。
- **`class ExtractedFormula`**: 从图像中提取的公式结果。
  - **核心方法 (Methods)**:
    - `enhanced_text()`: 生成 Jinja2 增强格式: [LaTeX_Source: ...] (公式语义解释: ...)
- **`class LayoutAnalyzer`**: 公式区域检测器。优先使用 LayoutLMv3, 降级使用规则引擎。
  - **核心方法 (Methods)**:
    - `detect_formulas()`: 检测图像中的公式区域。
    - `_detect_with_layoutlm()`: LayoutLMv3 公式区域检测。
    - `_detect_with_rules()`: 规则引擎降级: 返回全图区域作为公式候选。
- **`class FormulaOCREngine`**: LaTeX 公式 OCR 引擎。优先使用 Pix2Text, 降级使用正则/规则方法。
  - **核心方法 (Methods)**:
    - `extract_latex()`: 从图像或裁剪区域提取 LaTeX 公式。
    - `_extract_with_pix2text()`: Pix2Text LaTeX 提取。
    - `_extract_with_regex()`: 正则降级: 从文件名或路径推断公式内容。
- **`class FormulaExtractor`**: 公式提取管道: Layout 分析 -> OCR -> 增强格式。
  - **核心方法 (Methods)**:
    - `__init__()`: *无描述*
    - `extract_from_image()`: 从图像中提取所有公式。
    - `extract_from_text()`: 从文本中提取已有的 LaTeX 公式 (不依赖 OCR)。
    - `formula_to_evidence()`: 将提取的公式转换为 Evidence 对象 (用于双轨嵌入)。

#### ⚙️ 独立函数 (Functions)

- `_latex_to_semantic()`: 将 LaTeX 公式源码转换为中文自然语言语义描述。

---

### 📄 [formula_rag.py](file:///d:/project-edumatrix/edumatrix-main/app/utils/formula_rag.py)

**文件路径**: `app/utils/formula_rag.py`

> 公式 LaTeX 双轨增强检索模块。

职责:
  1. 将公式源码和自然语言语义同时嵌入向量空间 (bge-m3 双轨)
  2. 存入 ChromaDB 向量库 (降级: InMemoryVectorIndex)
  3. 检索时对公式源码和语义双轨召回并融合排序
  4. 验收: "损失函数对权重的偏导数" -> 召回含 ∂L/∂W 的 Chunk (cos > 0.88)

#### 📦 类定义 (Classes)

- **`class DualTrackVector`**: 公式双轨向量: 源码轨道 + 语义轨道。
- **`class FormulaVectorStore`**: 公式向量存储协议。
  - **核心方法 (Methods)**:
    - `upsert()`: *无描述*
    - `search()`: *无描述*
    - `count()`: *无描述*
- **`class FormulaSearchHit`**: 公式检索命中结果。
- **`class InMemoryFormulaStore`**: 内存公式向量存储 (ChromaDB 不可用时的降级方案)。
  - **核心方法 (Methods)**:
    - `__init__()`: *无描述*
    - `upsert()`: *无描述*
    - `search()`: *无描述*
    - `count()`: *无描述*
- **`class ChromaDBFormulaStore`**: ChromaDB 公式向量存储。
  - **核心方法 (Methods)**:
    - `__init__()`: *无描述*
    - `_get_collection()`: *无描述*
    - `upsert()`: *无描述*
    - `search()`: *无描述*
    - `count()`: *无描述*
- **`class FormulaRAG`**: 公式 LaTeX 双轨增强检索系统。
  - **核心方法 (Methods)**:
    - `__init__()`: *无描述*
    - `index_formulas()`: 将提取的公式批量索引到向量库。
    - `index_from_image()`: 从图像提取公式并索引。
    - `index_from_text()`: 从文本提取 LaTeX 公式并索引。
    - `search()`: 双轨检索公式。
    - `search_as_evidence()`: 检索公式并转换为 Evidence 对象 (供 HybridRAGPipeline 使用)。

#### ⚙️ 独立函数 (Functions)

- `encode_dual_track()`: 对公式生成双轨嵌入向量。
- `_cosine_similarity()`: Standard cosine similarity in [-1, 1], clamped to [0, 1].
- `create_formula_store()`: 工厂方法: 优先使用 ChromaDB, 降级使用内存存储。
- `seed_formula_index()`: 将内置的机器学习公式导入向量库。

---

### 📄 [graph_builder.py](file:///d:/project-edumatrix/edumatrix-main/app/utils/graph_builder.py)

**文件路径**: `app/utils/graph_builder.py`

> 动态三元组抽取与 Neo4j 拓扑图谱并网模块。

职责:
  1. 从文本 Chunk 中通过 LLM 提取 (source)-[relation]->(target) 三元组
  2. 基于 Levenshtein + 余弦相似度完成实体白名单同义词对齐
  3. 通过 Neo4j MERGE 语句构建有向无环图 (DAG)
  4. 当 Neo4j 不可用时, 自动降级到内存图存储

#### 📦 类定义 (Classes)

- **`class GraphRepository`**: 图存储后端协议。
  - **核心方法 (Methods)**:
    - `merge_node()`: *无描述*
    - `merge_edge()`: *无描述*
    - `query_prerequisites()`: *无描述*
    - `count_nodes()`: *无描述*
    - `count_edges()`: *无描述*
- **`class InMemoryGraphRepository`**: 内存图存储 (Neo4j 不可用时的降级方案)。
  - **核心方法 (Methods)**:
    - `__init__()`: *无描述*
    - `merge_node()`: *无描述*
    - `merge_edge()`: *无描述*
    - `query_prerequisites()`: *无描述*
    - `count_nodes()`: *无描述*
    - `count_edges()`: *无描述*
- **`class Neo4jGraphRepository`**: Neo4j 图存储后端, 使用 MERGE 语句构建 DAG。
  - **核心方法 (Methods)**:
    - `__init__()`: *无描述*
    - `_get_driver()`: *无描述*
    - `_run_query()`: *无描述*
    - `merge_node()`: *无描述*
    - `merge_edge()`: *无描述*
    - `query_prerequisites()`: *无描述*
    - `count_nodes()`: *无描述*
    - `count_edges()`: *无描述*
    - `close()`: *无描述*
- **`class GraphBuilder`**: 图谱构建器: 三元组抽取 -> 实体对齐 -> Neo4j MERGE 写入。
  - **核心方法 (Methods)**:
    - `__init__()`: *无描述*
    - `build_from_chunks()`: 从文本 Chunk 列表构建图谱, 返回构建报告。
    - `build_from_text()`: 从单段文本构建图谱 (自动按段落分割)。
    - `query()`: 查询某概念的前置依赖与后续应用。
    - `_align_triplet()`: *无描述*
    - `_has_path()`: DFS 检测从 start 到 end 是否存在可达路径。用于环路检测。
    - `_write_triplet()`: *无描述*

#### ⚙️ 独立函数 (Functions)

- `levenshtein_distance()`: Compute the Levenshtein (edit) distance between two strings.
- `levenshtein_ratio()`: Normalized similarity in [0, 1] based on Levenshtein distance.
- `align_entity()`: 将原始实体名对齐到白名单标准名。优先级: exact > levenshtein > cosine > fallback
- `_dot_cosine()`: Standard cosine similarity clamped to [0, 1].
- `extract_triplets_from_text()`: 从文本中提取三元组。优先使用 LLM, 降级使用正则规则引擎。
- `_parse_llm_triplets()`: Parse LLM response into Triplet objects, tolerating extra text.
- `_rule_based_triplets()`: 基于正则规则的三元组提取 (LLM 不可用时的降级方案)。
- `_safe_relation()`: Sanitize relation name for Cypher (alphanumeric + underscore only).
- `create_graph_repository()`: 工厂方法: 优先创建 Neo4j 后端, 失败则降级到内存后端。
- `seed_default_graph()`: 将内置的机器学习知识图谱边导入图谱存储。

---

### 📄 [graph_models.py](file:///d:/project-edumatrix/edumatrix-main/app/utils/graph_models.py)

**文件路径**: `app/utils/graph_models.py`

> 图谱构建相关的领域模型（dataclass 不可变值对象）。

按 backend.md 第 1/2 条：业务领域模型集中定义，repository / service 仅依赖
这些类型，不直接依赖 ORM 行或外部 SDK 对象。

#### 📦 类定义 (Classes)

- **`class Triplet`**: 前置依赖三元组：source -[relation]-> target。
  - **核心方法 (Methods)**:
    - `normalized()`: *无描述*
- **`class EntityAlignment`**: 实体对齐结果。
- **`class AlignedTriplet`**: 对齐后的三元组（source/target 替换为白名单标准词）。
  - **核心方法 (Methods)**:
    - `aligned()`: *无描述*
    - `both_aligned()`: *无描述*
- **`class GraphBuildReport`**: 图谱构建一次执行的统计快照。
- **`class GraphQueryResult`**: 图谱查询返回值。

#### ⚙️ 独立函数 (Functions)

- `_utc_now_iso()`: *无描述*

---

### 📄 [recommendation_engine.py](file:///d:/project-edumatrix/edumatrix-main/app/utils/recommendation_engine.py)

**文件路径**: `app/utils/recommendation_engine.py`

> *暂无详细模块级别文档注释.*

#### ⚙️ 独立函数 (Functions)

- `evaluate_tactical_pathway()`: 根据学情特征多维度评估，决策当前概念对应的自适应教学战术路线
- `get_concept_specific_overview()`: *无描述*
- `get_smart_recommendations()`: 根据学生认知掌握度、薄弱点与交互偏好，自适应精准推送匹配的学习资源

---

### 📄 [rl_planner.py](file:///d:/project-edumatrix/edumatrix-main/app/utils/rl_planner.py)

**文件路径**: `app/utils/rl_planner.py`

> *暂无详细模块级别文档注释.*

#### 📦 类定义 (Classes)

- **`class QLearningPathPlanner`**: *无类文档*
  - **核心方法 (Methods)**:
    - `get_state_key()`: 将连续的学情特征离散化为 12 种状态组合
    - `calculate_reward()`: 根据学习交互前后的学情变化以及认知开销计算即时奖励值 R
    - `update_q_value()`: 执行 Q-learning 强化更新步骤 (TD-learning)
    - `get_best_action()`: 获取当前学情状态下的最优推荐资源类型 (Epsilon-Greedy 决策)

---

### 📄 [behavior_api.py](file:///d:/project-edumatrix/edumatrix-main/behavior_api.py)

**文件路径**: `behavior_api.py`

> 任务 7.8: 真实行为信号回流与学习负荷更新 API

核心公式（认知负荷滑动更新）：
    L_cognitive(t) = 0.75 * L_cognitive(t-1) + 0.25 * min(1.0, T_actual/T_base * (1.0 + 0.15 * E_sandbox_runs))

情绪阻滞判定规则：
    页面停留 < 10s 且答题正确率极低 → affective_barrier 上调 25%

#### ⚙️ 独立函数 (Functions)

- `_update_cognitive_load()`: 认知负荷滑动更新公式。
- `_check_affective_block()`: 情绪阻滞判定：停留 < 10s 且正确率 < 0.3 → 上调 affective_barrier。
- `_update_focus_level()`: 专注度同步更新：停留越短/负荷越高 → 专注度下降。

---

### 📄 [bkt_engine.py](file:///d:/project-edumatrix/edumatrix-main/bkt_engine.py)

**文件路径**: `bkt_engine.py`

> P0 任务 7.1: 贝叶斯知识追踪引擎 (BKT) + ZPD 动态剪枝 + Poincaré 双曲距离。

技术要点：
1. BKT: HMM 双状态(掌握/未掌握)更新 P(L_t)
2. ZPD 动态剪枝: mastery [0.3, 0.75] 为最近发展区
3. Poincaré 双曲距离: 解决概念间的双曲空间距离

#### 📦 类定义 (Classes)

- **`class KalmanFilter`**: 一维自适应卡尔曼滤波器，用于学情状态防抖平滑。
  - **核心方法 (Methods)**:
    - `__init__()`: *无描述*
    - `step()`: 运行一步预测与更新。
- **`class BKTState`**: 单个知识点的 BKT 状态，整合卡尔曼滤波器。
  - **核心方法 (Methods)**:
    - `__post_init__()`: *无描述*
    - `update()`: 根据答题结果更新 BKT 状态，并通过自适应卡尔曼滤波器进行防抖平滑，支持特定认知层级维度。
- **`class BKTEngine`**: 贝叶斯知识追踪引擎：管理多个知识点的 BKT 状态。
  - **核心方法 (Methods)**:
    - `__init__()`: *无描述*
    - `get_or_create()`: *无描述*
    - `update()`: *无描述*
    - `get_mastery()`: *无描述*
    - `snapshot()`: *无描述*
- **`class HmdsMlpProxy`**: 轻量级高维双曲到 2D Poincaré 圆盘投影的 MLP 代理网络
  - **核心方法 (Methods)**:
    - `__init__()`: *无描述*
    - `forward()`: *无描述*
- **`class EbbinghausDecayEngine`**: 艾宾浩斯遗忘衰减引擎：管理全知识点衰减调度。
  - **核心方法 (Methods)**:
    - `decay_profile()`: 对画像中的全部知识点执行遗忘衰减。
    - `apply_decay_to_profile()`: 对 StudentProfile 原地执行遗忘衰减。
- **`class KnowledgeDiffusionEngine`**: LMCD 知识扩散引擎：解决冷启动，自动将某个概念的掌握度变化向关联概念传播。
  - **核心方法 (Methods)**:
    - `__init__()`: *无描述*
    - `diffuse()`: 对知识点掌握度执行扩散。
    - `_resolve_active_dag()`: Merge caller DAG with GraphRAG dynamic prerequisites when available.
    - `_compute_topo_distances()`: 通过无向 BFS 计算目标点到图中其他各概念的拓扑最短距离。
- **`class DktRnnEngine`**: 基于双线性认知诊断投影的动态 DKT 网络
  - **核心方法 (Methods)**:
    - `__init__()`: *无描述*
    - `forward()`: seq_embeddings: (batch_size, seq_len, 385)
- **`class DktService`**: DKT 推理与增量学习服务单例包装 (二分类 BCE 正确率估计版本 - Option B 个性化偏置)
  - **核心方法 (Methods)**:
    - `__new__()`: *无描述*
    - `predict_mastery()`: 根据学生最近 50 次答题序列与学生专属偏置推理最新的概念掌握度，支持动态额外概念追踪
    - `train_incremental()`: 在线对比增量微调 (支持单例和个性化偏置双模模式)
    - `_worker_loop()`: 后台单线程工作循环
    - `_train_step()`: 真正的个性化偏置梯度更新步骤，只对 student_bias 进行更新

#### ⚙️ 独立函数 (Functions)

- `classify_zpd_zone()`: 根据掌握度将知识点分类到 ZPD 区间。
- `should_rollback_to_prerequisites()`: 任务7.1要求: 当目标概念的前置依赖节点掌握度低于 0.5 时，自动回溯到前置。
- `get_zpd_path_plan()`: 生成 ZPD 动态路径规划。
- `poincare_distance()`: 计算单位球内两点 u, v 之间的 Poincaré 双曲距离。
- `project_to_ball()`: 将向量投影到 Poincaré 单位球内部（用于距离计算）。
- `_get_mds_process_executor()`: *无描述*
- `_poincare_mds_live_optimization_worker()`: MDS 双曲投影 Adam 优化的子进程 Worker，彻底释放主进程的 GIL 锁
- `_get_raw_poincare_coordinates()`: 使用双曲多维尺度变换 (Hyperbolic MDS) 并结合本地数据库缓存，将高维双曲向量动态投影至 2D 庞加莱圆盘
- `poincare_to_2d_coordinates()`: 将专业领域概念映射至 2D 庞加莱圆盘中，采用同心环深度分布与角度等间距对齐算法，保障极致的排版与疏密排版均匀度
- `find_nearest_concept()`: 在双曲空间中找到距离目标最近的概念（用于困难时跳转）。
- `ebbinghaus_decay()`: 艾宾浩斯遗忘衰减公式。
- `compute_decay_beta()`: 根据认知负荷和挫败感动态计算衰减系数 beta。
- `behavior_sanity_check()`: 行为信号校验（平滑校准版）：聚合近3次答题正确率，使用 Sigmoid 连续门控调节掌握度，消除跃迁抖动。

---

### 📄 [code_exec_api.py](file:///d:/project-edumatrix/edumatrix-main/code_exec_api.py)

**文件路径**: `code_exec_api.py`

> *暂无详细模块级别文档注释.*

#### 📦 类定义 (Classes)

- **`class SandboxProcessRunner`**: *无类文档*
  - **核心方法 (Methods)**:
    - `__init__()`: *无描述*
    - `_create_container()`: *无描述*
    - `_validate_code_ast()`: 使用 AST 静态分析扫描学生代码，拦截反射逃逸、任意代码执行等不安全操作。
    - `_get_wrapper_script()`: *无描述*

#### ⚙️ 独立函数 (Functions)

- `_generate_id()`: *无描述*

---

### 📄 [concurrency.py](file:///d:/project-edumatrix/edumatrix-main/concurrency.py)

**文件路径**: `concurrency.py`

> *暂无详细模块级别文档注释.*

#### 📦 类定义 (Classes)

- **`class CircuitState`**: *无类文档*
- **`class CircuitBreaker`**: *无类文档*
  - **核心方法 (Methods)**:
    - `state()`: *无描述*
    - `reset()`: *无描述*
- **`class CircuitBreakerOpenError`**: *无类文档*
- **`class TokenBucket`**: *无类文档*
  - **核心方法 (Methods)**:
    - `__post_init__()`: *无描述*
    - `_refill()`: *无描述*
- **`class APIRateLimiter`**: *无类文档*
  - **核心方法 (Methods)**:
    - `__init__()`: *无描述*
    - `release()`: *无描述*
- **`class AsyncWorkerPool`**: *无类文档*
  - **核心方法 (Methods)**:
    - `__post_init__()`: *无描述*

---

### 📄 [config.py](file:///d:/project-edumatrix/edumatrix-main/config.py)

**文件路径**: `config.py`

> *暂无详细模块级别文档注释.*

#### 📦 类定义 (Classes)

- **`class EduMatrixConfig`**: *无类文档*

---

### 📄 [content_safety.py](file:///d:/project-edumatrix/edumatrix-main/content_safety.py)

**文件路径**: `content_safety.py`

> *暂无详细模块级别文档注释.*

#### 📦 类定义 (Classes)

- **`class ContentSafetyFilter`**: *无类文档*
  - **核心方法 (Methods)**:
    - `__init__()`: *无描述*
    - `check_safety()`: *无描述*
    - `sanitize()`: *无描述*
    - `check_academic_validity()`: *无描述*
    - `_extract_context()`: *无描述*

---

### 📄 [document_parser.py](file:///d:/project-edumatrix/edumatrix-main/document_parser.py)

**文件路径**: `document_parser.py`

> *暂无详细模块级别文档注释.*

#### ⚙️ 独立函数 (Functions)

- `_check_vision_llm()`: 检测是否配置了多模态视觉大模型，结果缓存到模块级变量。
- `_render_pdf_to_images()`: 使用 PyMuPDF 将 PDF 每一页渲染为 PNG 图像。
- `_describe_image_with_multimodal_llm()`: 调用多模态视觉大模型描述 PDF 页面图片内容。
- `_describe_image_with_pil()`: 使用 PIL 生成基础图片元数据描述（非视觉模型时的降级方案）。
- `parse_pdf_visually()`: 解析 PDF 的视觉内容：逐页渲染为图片 → 调用多模态大模型生成语义描述。
- `parse_uploaded_file()`: *无描述*
- `_parse_pdf()`: 解析 PDF 文本，优先 pdfplumber（支持表格提取），降级 PyPDF2，保底 decode。
- `_markdown_escape_cell()`: 转义表格单元格中可能破坏 Markdown 表格的字符。
- `_parse_docx()`: *无描述*
- `_parse_pptx()`: *无描述*
- `_describe_image()`: *无描述*
- `_get_dominant_colors()`: *无描述*
- `_transcribe_video()`: *无描述*
- `_audio_transcription()`: *无描述*
- `_speech_to_text()`: *无描述*
- `parse_pptx_slides()`: *无描述*
- `chunk_document()`: 将文档切分为父子分块结构。
- `_chunk_code()`: 代码文件分块（保持原有逻辑）。
- `_chunk_with_parent_child()`: 父子分块：先切父块(~1000-1500字)，再在每个父块内切子块(~200-250字)。
- `_infer_tags()`: *无描述*

---

### 📄 [drag_debate.py](file:///d:/project-edumatrix/edumatrix-main/drag_debate.py)

**文件路径**: `drag_debate.py`

> *暂无详细模块级别文档注释.*

#### 📦 类定义 (Classes)

- **`class DebateResult`**: *无类文档*
- **`class DebateAugmentedRAG`**: DRAG-style multi-agent evidence cleaning.
  - **核心方法 (Methods)**:
    - `__init__()`: *无描述*
    - `clean()`: *无描述*
    - `_llm_debate_clean()`: 使用 LLM 的 Prover-Challenger-Judge 三轮对话清洗证据。
    - `_collective_batch_judge()`: 对整个证据集进行 LLM 批量评估，模拟 Prover-Challenger-Judge 三层对话。
    - `_deterministic_clean()`: 原始确定性评分函数路径。
    - `_prover()`: *无描述*
    - `_challenger()`: *无描述*
    - `_reason()`: *无描述*

#### ⚙️ 独立函数 (Functions)

- `_get_or_create_loop()`: *无描述*

---

### 📄 [embedding_models.py](file:///d:/project-edumatrix/edumatrix-main/embedding_models.py)

**文件路径**: `embedding_models.py`

> *暂无详细模块级别文档注释.*

#### 📦 类定义 (Classes)

- **`class EmbeddingBackend`**: *无类文档*
  - **核心方法 (Methods)**:
    - `embed()`: *无描述*
    - `score()`: *无描述*
- **`class SentenceTransformerEmbedding`**: *无类文档*
  - **核心方法 (Methods)**:
    - `__post_init__()`: *无描述*
    - `_load_model()`: *无描述*
    - `embed()`: *无描述*
    - `score()`: *无描述*
- **`class HashEmbeddingBackend`**: *无类文档*
  - **核心方法 (Methods)**:
    - `embed()`: *无描述*
    - `score()`: *无描述*
- **`class OpenAICompatibleEmbeddingBackend`**: *无类文档*
  - **核心方法 (Methods)**:
    - `embed()`: *无描述*
    - `score()`: *无描述*
- **`class CachingEmbeddingBackend`**: *无类文档*
  - **核心方法 (Methods)**:
    - `__init__()`: *无描述*
    - `embed()`: *无描述*
    - `score()`: *无描述*

#### ⚙️ 独立函数 (Functions)

- `cosine_similarity()`: *无描述*
- `_tokens()`: *无描述*
- `build_embedding_backend()`: *无描述*

---

### 📄 [export_pdf.py](file:///d:/project-edumatrix/edumatrix-main/export_pdf.py)

**文件路径**: `export_pdf.py`

> export_pdf.py — 任务 2: 结构化讲义一键生成与 PDF 导出

渲染管线: Markdown → ReportLab → PDF

零外部依赖（纯 Python），支持中英文混排、数学公式、代码块

#### ⚙️ 独立函数 (Functions)

- `_make_styles()`: *无描述*
- `_escape_pdf()`: 转义 ReportLab Paragraph 的 XML 特殊字符。
- `_get_simhei_char_map()`: *无描述*
- `_sanitize_simhei_glyphs()`: 过滤掉 SimHei 字体中不存在的缺失字符，彻底杜绝 PDF 中的缺字方框 □。
- `_clean_latex_to_reportlab_html()`: 将 LaTeX 数学公式表达式转换为带有 ReportLab <sub>/<sup> 标签的优雅 HTML，防止 CJK 字体缺字方框 □。
- `_inline_to_pdf()`: 将行内 Markdown 标记转换为 ReportLab XML 格式。
- `md_to_flowables()`: 将 Markdown 文本转换为 ReportLab Flowable 列表。
- `_build_cover()`: 构建封面页的 flowable 列表。
- `generate_note_pdf()`: 将笔记内容生成为 PDF（ReportLab 引擎）。

---

### 📄 [fix.py](file:///d:/project-edumatrix/edumatrix-main/fix.py)

**文件路径**: `fix.py`

> *暂无详细模块级别文档注释.*

---

### 📄 [flashcard_api.py](file:///d:/project-edumatrix/edumatrix-main/flashcard_api.py)

**文件路径**: `flashcard_api.py`

> Adaptive Anki-style flashcard API.

Endpoints:
- POST /api/flashcard/generate: create a flashcard from a wrong quiz or weak point.
- POST /api/flashcard/review: record review quality and persist SM-2 scheduling.
- GET  /api/flashcard/due: list cards due for review directly from DB.
- GET  /api/flashcard/all: list all cards directly from DB.

#### ⚙️ 独立函数 (Functions)

- `_utcnow_naive()`: *无描述*
- `_iso_utc()`: *无描述*

---

### 📄 [ingestion.py](file:///d:/project-edumatrix/edumatrix-main/ingestion.py)

**文件路径**: `ingestion.py`

> *暂无详细模块级别文档注释.*

#### 📦 类定义 (Classes)

- **`class IngestionReport`**: *无类文档*
- **`class DocumentChunk`**: *无类文档*
  - **核心方法 (Methods)**:
    - `to_evidence()`: *无描述*
- **`class DocumentIngestionPipeline`**: Dataset-ready ingestion pipeline for course material.
  - **核心方法 (Methods)**:
    - `__init__()`: *无描述*
    - `ingest_text()`: *无描述*
    - `ingest_file()`: *无描述*
    - `chunk_text()`: *无描述*
    - `_maybe_persist()`: Persist the underlying index to disk if it is a FaissVectorIndex.

#### ⚙️ 独立函数 (Functions)

- `_stable_chunk_id()`: *无描述*
- `_infer_tags()`: *无描述*
- `_infer_anchors()`: *无描述*
- `_sentence_diff()`: 对两段文本做句级别 diff，返回仅存在于新文本中的句子。
- `_get_graph_builder()`: 延迟初始化图谱构建器（InMemory 后端，种子数据预填充）。
- `build_graph_after_upload()`: 文档上传后触发增量图谱自生长 (Task 2)。
- `_build_co_occur_edges()`: 跨文档共现关联：对新切片搜索已有索引中相似度>0.85的切片，建立 CO_OCCUR 边。

---

### 📄 [instruct_rag.py](file:///d:/project-edumatrix/edumatrix-main/instruct_rag.py)

**文件路径**: `instruct_rag.py`

> *暂无详细模块级别文档注释.*

#### 📦 类定义 (Classes)

- **`class InstructionPlan`**: *无类文档*
- **`class InstructRAGGenerator`**: *无类文档*
  - **核心方法 (Methods)**:
    - `__init__()`: *无描述*
    - `generate()`: *无描述*
    - `_build_plan()`: *无描述*
- **`class AsyncInstructRAGGenerator`**: *无类文档*
  - **核心方法 (Methods)**:
    - `__init__()`: *无描述*
    - `_build_plan()`: *无描述*

#### ⚙️ 独立函数 (Functions)

- `_build_instruction_plan()`: 统一的构建计划逻辑，同步/异步生成器共享。
- `_edges_desc()`: *无描述*

---

### 📄 [knowledge_api.py](file:///d:/project-edumatrix/edumatrix-main/knowledge_api.py)

**文件路径**: `knowledge_api.py`

> *暂无详细模块级别文档注释.*

#### ⚙️ 独立函数 (Functions)

- `_estimate_video_duration()`: *无描述*

---

### 📄 [knowledge_base.py](file:///d:/project-edumatrix/edumatrix-main/knowledge_base.py)

**文件路径**: `knowledge_base.py`

> *暂无详细模块级别文档注释.*

#### ⚙️ 独立函数 (Functions)

- `load_evidence_from_file()`: *无描述*
- `_parse_evidence()`: *无描述*
- `load_seed_evidence()`: *无描述*
- `save_evidence_to_file()`: *无描述*

---

### 📄 [learning_event_bus.py](file:///d:/project-edumatrix/edumatrix-main/learning_event_bus.py)

**文件路径**: `learning_event_bus.py`

> 任务 10.1: 学情交互诊断事件总线 (LearningEventBus)

消除答题评测系统与对话大模型之间的数据隔离，
引入进程内异步事件总线统一分发学情事件。

核心组件：
1. QuizAttemptedEvent — 标准化答题事件
2. LearningEventBus — 进程内异步事件总线 (pub/sub)
3. ProfileHistorySubscriber — 全局订阅器，自动写入 StudentProfile.history

#### 📦 类定义 (Classes)

- **`class QuizAttemptedEvent`**: 标准化答题事件。
  - **核心方法 (Methods)**:
    - `to_profile_log()`: 格式化为可追加到 StudentProfile.history 的日志字符串。
- **`class ProfileUpdatedEvent`**: 画像更新事件：当 StudentProfile 发生变更时触发。
- **`class LearningEventBus`**: 进程内异步事件总线 (单例模式)。
  - **核心方法 (Methods)**:
    - `__init__()`: *无描述*
    - `get_instance()`: 获取全局单例。
    - `subscribe()`: 订阅指定类型的事件。
    - `unsubscribe()`: 取消订阅。
    - `get_event_log()`: 获取最近的事件日志。
    - `_resolve_event_type()`: 将事件对象映射到字符串类型名。

#### ⚙️ 独立函数 (Functions)

- `_run_offline_cognition_pipeline()`: 在后台线程中计算 DKT + BKT 状态，并保存至数据库（解决同步锁 and 高并发响应延迟）
- `register_default_subscribers()`: 注册全局默认订阅器。

---

### 📄 [learning_strategy.py](file:///d:/project-edumatrix/edumatrix-main/learning_strategy.py)

**文件路径**: `learning_strategy.py`

> *暂无详细模块级别文档注释.*

#### 📦 类定义 (Classes)

- **`class TeachingTier`**: 自适应教学档位（任务 7.3）。
- **`class PathPlanner`**: Facade for member 2 micro-graph construction and A* path planning.
  - **核心方法 (Methods)**:
    - `__init__()`: *无描述*
    - `_active_inputs()`: *无描述*
    - `build_micro_graph()`: *无描述*
    - `build_cross_disciplinary_graph()`: *无描述*
    - `plan()`: *无描述*
- **`class LearningStrategyEngine`**: Maps learner-state evidence to concrete learning-science interventions.
  - **核心方法 (Methods)**:
    - `build_plan()`: *无描述*

#### ⚙️ 独立函数 (Functions)

- `invalidate_graph_cache()`: Invalidate the global graph cache for learning strategy planning.
- `detect_teaching_tier()`: 根据目标概念掌握度检测自适应教学档位。
- `_clamp_score()`: *无描述*
- `_concepts_from_dag()`: *无描述*
- `_safe_unique()`: *无描述*
- `_has_forward_path()`: Return True if source can already reach target in concept -> prereqs DAG.
- `_merge_prerequisite()`: *无描述*
- `_animation_index()`: *无描述*
- `_resource_signal()`: *无描述*
- `_resource_text()`: *无描述*
- `_concept_tags()`: Extract lightweight semantic tags from concept/resource text instead of static concept maps.
- `_concept_domain()`: Infer a display domain from resource metadata and generic lexical signals.
- `_domain_label()`: *无描述*
- `_infer_resource_prerequisite_edges()`: Infer missing resource prerequisites from metadata/embedding similarity.
- `build_resource_aware_dag()`: Fuse static seed, GraphRAG edges and local animation concepts into one DAG.
- `_concept_embedding_text()`: *无描述*
- `_concept_embedding_vectors()`: *无描述*
- `compute_concept_tiers()`: Compute stable prerequisite tiers from a concept -> prerequisites graph.
- `_normalize_vector()`: *无描述*
- `build_cross_disciplinary_micro_graph()`: Build a mixed-domain micro-concept graph with real embedding similarity.
- `astar_search()`: 通用 A* 启发式寻路算法。
- `suggest_cross_domain_supports()`: *无描述*
- `build_micro_concept_graph()`: Build weighted prerequisite edges for adaptive path planning.
- `_ancestors_for_target()`: *无描述*
- `_repair_route_topology()`: Applies Kahn's algorithm / topological sort to repair a route that violates dependency order.
- `build_adaptive_astar_route()`: Plan a deterministic multi-constraint A* route over prerequisite edges.
- `_build_session_plan()`: *无描述*
- `_review_candidate_route_with_planner()`: *无描述*
- `_audit_route_topology()`: *无描述*
- `_build_planner_trace()`: *无描述*

---

### 📄 [llm_client.py](file:///d:/project-edumatrix/edumatrix-main/llm_client.py)

**文件路径**: `llm_client.py`

> *暂无详细模块级别文档注释.*

#### 📦 类定义 (Classes)

- **`class LLMBackend`**: *无类文档*
  - **核心方法 (Methods)**:
    - `generate()`: *无描述*
- **`class AsyncLLMBackend`**: *无类文档*
- **`class AsyncOpenAIChatLLM`**: *无类文档*
  - **核心方法 (Methods)**:
    - `__post_init__()`: *无描述*
    - `has_vision()`: *无描述*
- **`class OpenAIChatLLM`**: *无类文档*
  - **核心方法 (Methods)**:
    - `__init__()`: *无描述*
    - `generate()`: *无描述*
- **`class SparkClient`**: *无类文档*
  - **核心方法 (Methods)**:
    - `_create_url()`: *无描述*
    - `generate()`: *无描述*
- **`class AsyncSparkClient`**: *无类文档*
  - **核心方法 (Methods)**:
    - `_create_url()`: *无描述*
    - `_sync_generate()`: *无描述*
- **`class DeterministicEducationLLM`**: *无类文档*
  - **核心方法 (Methods)**:
    - `generate()`: *无描述*
- **`class AsyncDeterministicEducationLLM`**: *无类文档*
- **`class FallbackAsyncLLMWrapper`**: Wrapper that catches any exception from a primary AsyncLLMBackend and falls back to a secondary backend.
  - **核心方法 (Methods)**:
    - `__init__()`: *无描述*
    - `has_vision()`: *无描述*

#### ⚙️ 独立函数 (Functions)

- `build_llm()`: *无描述*
- `build_async_llm()`: *无描述*
- `call_spark_api()`: *无描述*
- `_guess_topic()`: *无描述*
- `_profile_json()`: *无描述*
- `_lecture()`: *无描述*
- `_code()`: *无描述*
- `_mermaid()`: *无描述*
- `_quiz()`: *无描述*
- `_video_script()`: *无描述*
- `_video_recommendations()`: *无描述*
- `get_concept_rich_adaptation()`: Return high-fidelity concept-specific simplified explanation and detailed Mermaid mindmap.
- `_simplified_explanation()`: *无描述*

---

### 📄 [manifold_alignment.py](file:///d:/project-edumatrix/edumatrix-main/manifold_alignment.py)

**文件路径**: `manifold_alignment.py`

> *暂无详细模块级别文档注释.*

#### 📦 类定义 (Classes)

- **`class CouncilDecisionEngine`**: XH-202630 委员会决策引擎：在“分诊 ➔ 平行专家生成 ➔ 共识合成”工作流中，执行事实与相关性得分的定量共识核查。
  - **核心方法 (Methods)**:
    - `__init__()`: *无描述*
    - `synthesize()`: 对平行专家生成的定制资源进行事实性与相关性定量共识核查。
- **`class ManifoldAlignmentVerifier`**: *无类文档*
  - **核心方法 (Methods)**:
    - `__init__()`: *无描述*
    - `verify()`: *无描述*

#### ⚙️ 独立函数 (Functions)

- `apply_manifold_projection()`: 使用线性投影矩阵 W 将专业领域概念向量映射到统一的数学/逻辑流形空间
- `get_dag_depth()`: *无描述*
- `project_to_poincare_ball()`: 使用 tanh 模长变换与拓扑层级自适应，将高维欧氏向量投影到 Poincaré 庞加莱球（模长 < 1）内部
- `poincare_distance()`: 计算单位球内两点 u, v 之间的 Poincaré 双曲距离。
- `_embed_cached()`: *无描述*
- `_embed_safe()`: *无描述*
- `_extract_concept_text()`: *无描述*
- `verify_alignment()`: *无描述*
- `verify_consistency()`: *无描述*

---

### 📄 [math_utils.py](file:///d:/project-edumatrix/edumatrix-main/math_utils.py)

**文件路径**: `math_utils.py`

> EduMatrix 数学工具库 - 统一余弦相似度实现。

P2-2 重构：集中所有余弦相似度计算，消除四处重复实现。

#### ⚙️ 独立函数 (Functions)

- `cosine_similarity()`: 余弦相似度，返回 [0, 1] 范围的值。
- `cosine_similarity_np()`: 使用 NumPy 的余弦相似度。

---

### 📄 [mirt_engine.py](file:///d:/project-edumatrix/edumatrix-main/mirt_engine.py)

**文件路径**: `mirt_engine.py`

> *暂无详细模块级别文档注释.*

#### 📦 类定义 (Classes)

- **`class IRTItemParams`**: *无类文档*
  - **核心方法 (Methods)**:
    - `__post_init__()`: *无描述*
    - `to_dict()`: *无描述*
    - `from_dict()`: *无描述*
- **`class AdaptiveTestEstimator`**: *无类文档*
  - **核心方法 (Methods)**:
    - `__post_init__()`: *无描述*
    - `_logistic()`: *无描述*
    - `_probability_correct()`: 3D MIRT 多维补偿性 3PL 模型概率计算公式
    - `_probability_derivative()`: P 对 theta_dim 维度的偏导数
    - `fisher_information()`: 计算 MIRT 的 Fisher 信息量标量指标 (基于 trace 迹优化，即三维信息量之和)
    - `compute_log_likelihood()`: *无描述*
    - `compute_log_prior()`: *无描述*
    - `compute_log_posterior()`: *无描述*
    - `_estimate_theta_map()`: 多维 MAP (最大后验估计) 能力向量更新 (3D 梯度下降)
    - `_posterior_gradient()`: *无描述*
    - `update_ability()`: *无描述*
    - `_estimate_std()`: *无描述*
    - `compute_d_optimality()`: 计算三维 MIRT 的 Bayesian D-optimality (行列式最大化) 选题指标，包含协方差项
    - `select_next_item()`: *无描述*
    - `_extract_irt_params()`: *无描述*
    - `get_estimated_difficulty_label()`: *无描述*
    - `get_theta_confidence_interval()`: *无描述*
    - `to_dict()`: *无描述*

#### ⚙️ 独立函数 (Functions)

- `difficulty_to_beta()`: *无描述*
- `beta_to_difficulty()`: *无描述*
- `estimate_irt_params_from_profile()`: 根据学情画像与题型特征，自适应投射三维 MIRT 题目参数
- `mcmc_calibrate_item_parameters()`: 基于 Metropolis-Hastings MCMC 采样法校准三维 MIRT 题目参数 (alpha, beta)。

---

### 📄 [models.py](file:///d:/project-edumatrix/edumatrix-main/models.py)

**文件路径**: `models.py`

> *暂无详细模块级别文档注释.*

#### 📦 类定义 (Classes)

- **`class EvidenceModality`**: *无类文档*
- **`class ProfileEvidenceSource`**: *无类文档*
- **`class LearningStateCause`**: *无类文档*
- **`class StrategyType`**: *无类文档*
- **`class Evidence`**: *无类文档*
  - **核心方法 (Methods)**:
    - `with_score()`: *无描述*
    - `with_content()`: 返回替换 content 后的新 Evidence（保留其他字段）。
- **`class GraphContext`**: *无类文档*
  - **核心方法 (Methods)**:
    - `to_prompt()`: *无描述*
- **`class RetrievalBundle`**: *无类文档*
  - **核心方法 (Methods)**:
    - `context_prompt()`: *无描述*
- **`class DebateVerdict`**: *无类文档*
- **`class ProfileEvidence`**: *无类文档*
- **`class DimensionState`**: *无类文档*
- **`class CauseBreakdown`**: *无类文档*
- **`class BloomLevel`**: *无类文档*
- **`class KnowledgeTrace`**: *无类文档*
  - **核心方法 (Methods)**:
    - `update()`: *无描述*
- **`class StrategyAction`**: *无类文档*
- **`class LearningStrategyPlan`**: *无类文档*
- **`class StudentProfile`**: *无类文档*
  - **核心方法 (Methods)**:
    - `add_favorite()`: *无描述*
    - `remove_favorite()`: 根据 ID 移除收藏项
    - `update_favorite_note()`: 更新已有收藏的笔记
    - `update_from_message()`: *无描述*
    - `update_from_feedback()`: *无描述*
    - `apply_llm_features()`: *无描述*
    - `profile_prompt()`: *无描述*
    - `state_report()`: *无描述*
    - `_update_legacy_fields()`: *无描述*
    - `_update_context()`: *无描述*
    - `_update_emotional_state()`: 基于消息内容和历史模式推断情感状态（支持多轮对话上下文）。
    - `update_bloom_level()`: 根据掌握度推断 Bloom 认知层级。
    - `_update_concepts()`: *无描述*
    - `_extract_features()`: *无描述*
    - `_detect_misconception_pattern()`: *无描述*
    - `apply_profile_decay()`: 对全知识点执行艾宾浩斯遗忘衰减。
    - `_extract_cause_breakdowns()`: [SRP Refactored] Extract dynamic learning cause breakdowns from evidences.
    - `_compute_dimension_states()`: [SRP Refactored] Compute 10-dimensional student cognitive states.
    - `_refresh_dynamic_profile()`: *无描述*
- **`class LearningSignal`**: *无类文档*
  - **核心方法 (Methods)**:
    - `needs_replan()`: *无描述*
- **`class AgentOutput`**: *无类文档*
- **`class AlignmentReport`**: *无类文档*
- **`class ResourcePackage`**: *无类文档*

#### ⚙️ 独立函数 (Functions)

- `_utc_now()`: *无描述*
- `_clamp()`: *无描述*

---

### 📄 [multimodal_alignment.py](file:///d:/project-edumatrix/edumatrix-main/multimodal_alignment.py)

**文件路径**: `multimodal_alignment.py`

> 跨模态特征潜空间对齐模块 (Cross-Modal Feature Alignment)

实现文字-图片-公式之间的跨模态搜索：
- 用自然语言描述搜索相关的公式/图片
- 用 LaTeX 公式搜索相关的文字讲解/示意图
- 基于 InfoNCE 对比损失微调的特征映射层实现跨模态对齐

存储方式：JSON 文件持久化 + 内存缓存
依赖：embedding_models.EMBEDDINGS（全局嵌入后端）

#### 📦 类定义 (Classes)

- **`class ProjectionHead`**: Multimodal shared latent space projection network (384 -> 128, L2 norm).
  - **核心方法 (Methods)**:
    - `__init__()`: *无描述*
    - `forward()`: *无描述*
- **`class CrossModalAligner`**: 跨模态特征对齐器：管理文字-图片-公式三模态配对的注册与搜索。
  - **核心方法 (Methods)**:
    - `__init__()`: *无描述*
    - `_cosine()`: *无描述*
    - `_list_to_tensor()`: *无描述*
    - `calibrate()`: Train projection heads via standard InfoNCE contrastive loss.
    - `_get_projection_head()`: Reconstruct ProjectionHead from saved state dict for inference.
    - `_calib_project()`: Project a single vector through the modality's ProjectionHead if calibrated.
    - `_load_from_disk()`: 从 JSON 文件加载对齐数据和投影矩阵。
    - `save_to_disk()`: 将对齐数据和投影矩阵持久化到 JSON 文件。
    - `_build_embeddings()`: 计算所有配对的嵌入向量。
    - `register_pair()`: 注册一个新的跨模态对齐配对。
    - `search()`: 跨模态搜索。
    - `align_batch()`: 批量对齐：将文字段落与图片描述配对注册。
    - `pair_count()`: *无描述*
    - `is_calibrated()`: *无描述*
    - `calibration_loss()`: *无描述*

#### ⚙️ 独立函数 (Functions)

- `get_cross_modal_aligner()`: 获取跨模态对齐器单例（延迟初始化）。

---

### 📄 [note_engine.py](file:///d:/project-edumatrix/edumatrix-main/note_engine.py)

**文件路径**: `note_engine.py`

> *暂无详细模块级别文档注释.*

#### 📦 类定义 (Classes)

- **`class Note`**: *无类文档*
- **`class ReviewSchedule`**: *无类文档*
- **`class LearningProgressReport`**: *无类文档*
- **`class NoteGenerator`**: *无类文档*
  - **核心方法 (Methods)**:
    - `__init__()`: *无描述*
    - `summarize_conversation()`: *无描述*
- **`class LearningProgressAnalyzer`**: *无类文档*
  - **核心方法 (Methods)**:
    - `build_report()`: *无描述*
- **`class ReviewScheduler`**: *无类文档*
  - **核心方法 (Methods)**:
    - `schedule()`: *无描述*

#### ⚙️ 独立函数 (Functions)

- `_utc_now()`: *无描述*

---

### 📄 [observability.py](file:///d:/project-edumatrix/edumatrix-main/observability.py)

**文件路径**: `observability.py`

> *暂无详细模块级别文档注释.*

#### 📦 类定义 (Classes)

- **`class MetricEvent`**: *无类文档*
- **`class TraceSpan`**: *无类文档*
- **`class TelemetrySink`**: Small metrics/tracing sink used by local runs and tests.
  - **核心方法 (Methods)**:
    - `__init__()`: *无描述*
    - `record_metric()`: *无描述*
    - `record_span()`: *无描述*
    - `snapshot()`: *无描述*
    - `clear()`: *无描述*
    - `record_learning_event()`: 记录学习事件（掌握度变化、误概念出现、挫败感波动等）。
    - `record_engagement()`: 记录学生参与度和情感状态。
    - `get_education_summary()`: 获取教育维度的指标汇总。
- **`class timed_span`**: *无类文档*
  - **核心方法 (Methods)**:
    - `__init__()`: *无描述*
    - `__enter__()`: *无描述*
    - `__exit__()`: *无描述*

---

### 📄 [profile_api.py](file:///d:/project-edumatrix/edumatrix-main/profile_api.py)

**文件路径**: `profile_api.py`

> *暂无详细模块级别文档注释.*

#### 📦 类定义 (Classes)

- **`class NarrativeReportGenerator`**: StoryLensEdu 叙事驱动评估报告生成器：
  - **核心方法 (Methods)**:
    - `__init__()`: *无描述*
- **`class ProfileUpdateRequest`**: *无类文档*
- **`class RollbackRequest`**: *无类文档*

#### ⚙️ 独立函数 (Functions)

- `_build_dimension_analysis()`: 构建单个维度的分析文本
- `_build_weak_point_analysis()`: 分析薄弱点的根因
- `load_display_name()`: *无描述*
- `resolve_learning_goals_three_tiers()`: 三级自适应最终目标智能决策器：

---

### 📄 [quiz_api.py](file:///d:/project-edumatrix/edumatrix-main/quiz_api.py)

**文件路径**: `quiz_api.py`

> *暂无详细模块级别文档注释.*

#### ⚙️ 独立函数 (Functions)

- `_parse_llm_json()`: 从 LLM 响应中提取并解析 JSON，支持 markdown 包裹/杂音/单引号。
- `_validate_grading_result()`: 校验 LLM 判卷输出是否符合 JSON Schema，缺失/异常字段用安全值回填。
- `_generate_quiz_id()`: *无描述*
- `_get_fallback_quiz()`: 根据目标概念，返回专家级且内容准确的兜底简答题及参考答案。
- `_calc_streak()`: 计算连续打卡天数。支持时区偏移，避免跨时区截断 bug。

---

### 📄 [rag_engine.py](file:///d:/project-edumatrix/edumatrix-main/rag_engine.py)

**文件路径**: `rag_engine.py`

> *暂无详细模块级别文档注释.*

#### 📦 类定义 (Classes)

- **`class VectorMath`**: *无类文档*
  - **核心方法 (Methods)**:
    - `dot_product()`: *无描述*
    - `cosine_similarity()`: *无描述*
- **`class GraphRAG`**: *无类文档*
  - **核心方法 (Methods)**:
    - `__init__()`: *无描述*
    - `_add_edge()`: *无描述*
    - `_load_dynamic_edges()`: F1 修复：从动态图谱仓库（Neo4j/内存）加载边，与硬编码图谱合并。
    - `_build_professional_knowledge_graph()`: *无描述*
    - `_normalize_target()`: *无描述*
    - `_ancestors()`: *无描述*
    - `_descendants()`: *无描述*
    - `get_path()`: *无描述*
    - `get_context()`: *无描述*
    - `get_subgraph_context()`: *无描述*
- **`class VisRAG`**: *无类文档*
  - **核心方法 (Methods)**:
    - `__init__()`: *无描述*
    - `_builtin_image_evidence()`: *无描述*
    - `search()`: *无描述*
    - `search_evidence()`: *无描述*
- **`class TextKnowledgeIndex`**: *无类文档*
  - **核心方法 (Methods)**:
    - `__init__()`: *无描述*
    - `_builtin_text_evidence()`: *无描述*
    - `search()`: *无描述*
- **`class HybridRAGPipeline`**: *无类文档*
  - **核心方法 (Methods)**:
    - `__init__()`: *无描述*
    - `ingest_user_documents()`: *无描述*
    - `remove_user_documents()`: *无描述*
    - `retrieve()`: *无描述*
    - `_personalized_rerank()`: F3 修复：基于学生概念掌握度的个性化重排序。
    - `_infer_target()`: *无描述*
    - `_is_ml_concept()`: 判断查询是否落在机器学习/深度学习学科范畴。
- **`class FAISSIndexSet`**: *无类文档*
  - **核心方法 (Methods)**:
    - `__init__()`: *无描述*
    - `search()`: *无描述*
    - `search_by_category()`: *无描述*

#### ⚙️ 独立函数 (Functions)

- `_tokens()`: *无描述*
- `_encode_vector()`: *无描述*
- `colpali_maxsim()`: *无描述*
- `jinaclip_text_similarity()`: *无描述*
- `_similarity()`: *无描述*
- `_evidence_text()`: *无描述*
- `pre_filter_index()`: Helper to pre-filter items of an index by doc_constraints and compute similarities.
- `_search_videos_sync()`: 同步包装异步视频搜索函数，支持在各种上下文下（有/无运行中的event loop）正确运行
- `build_rag_pipeline()`: 构建混合 RAG 管线。
- `_query_hash()`: *无描述*
- `check_arxiv_cache()`: 检查 arXiv 缓存表是否命中。
- `save_arxiv_cache()`: 将 arXiv 检索结果写入本地缓存表。

---

### 📄 [report_api.py](file:///d:/project-edumatrix/edumatrix-main/report_api.py)

**文件路径**: `report_api.py`

> 任务 7.6: 一键导出学情诊断与能力对齐PDF报告

核心设计：
1. BrowserPool — FastAPI 全局初始化浏览器池，asyncio.Semaphore(3) 限流
2. Playwright 无头浏览器渲染 A4 PDF，保留背景图表
3. 专用 Print-only 页面排版
4. StreamingResponse 流式返回

接口：
    GET /api/v1/profile/export?student_id=xxx

#### 📦 类定义 (Classes)

- **`class BrowserPool`**: 高并发渲染安全池。
  - **核心方法 (Methods)**:
    - `__init__()`: *无描述*

#### ⚙️ 独立函数 (Functions)

- `_build_report_html()`: 生成标准化学情诊断报告 HTML (Print-only 排版)。

---

### 📄 [retrieval_evaluation.py](file:///d:/project-edumatrix/edumatrix-main/retrieval_evaluation.py)

**文件路径**: `retrieval_evaluation.py`

> *暂无详细模块级别文档注释.*

#### 📦 类定义 (Classes)

- **`class RetrievalEvalCase`**: *无类文档*
- **`class RetrievalEvalReport`**: *无类文档*

#### ⚙️ 独立函数 (Functions)

- `evaluate_retrieval()`: *无描述*
- `_miss_label()`: *无描述*

---

### 📄 [run.py](file:///d:/project-edumatrix/edumatrix-main/run.py)

**文件路径**: `run.py`

> EduMatrix 智教矩阵 - 后端启动入口

用法:
  # 开发模式（默认，不加载 FAISS 和真正嵌入）
  python run.py

  # 生产模式（OpenAI + 真实嵌入）
  set EDUMATRIX_LLM_API_KEY=sk-xxx
  set EDUMATRIX_EMBEDDING_PROVIDER=sentence_transformer
  python run.py

  # 生产模式（FAISS 加速）
  set EDUMATRIX_USE_FAISS=1
  python scripts/seed_faiss.py   # 先构建索引
  python run.py

#### ⚙️ 独立函数 (Functions)

- `_free_port()`: 杀掉占用指定端口的旧进程，防止端口冲突导致启动失败。
- `main()`: *无描述*

---

### 📄 [check_bvid.py](file:///d:/project-edumatrix/edumatrix-main/scratch/check_bvid.py)

**文件路径**: `scratch/check_bvid.py`

> *暂无详细模块级别文档注释.*

---

### 📄 [check_chat_root.py](file:///d:/project-edumatrix/edumatrix-main/scratch/check_chat_root.py)

**文件路径**: `scratch/check_chat_root.py`

> *暂无详细模块级别文档注释.*

---

### 📄 [check_db.py](file:///d:/project-edumatrix/edumatrix-main/scratch/check_db.py)

**文件路径**: `scratch/check_db.py`

> *暂无详细模块级别文档注释.*

#### ⚙️ 独立函数 (Functions)

- `check()`: *无描述*

---

### 📄 [check_simhei_glyphs.py](file:///d:/project-edumatrix/edumatrix-main/scratch/check_simhei_glyphs.py)

**文件路径**: `scratch/check_simhei_glyphs.py`

> *暂无详细模块级别文档注释.*

---

### 📄 [debug_bing_html.py](file:///d:/project-edumatrix/edumatrix-main/scratch/debug_bing_html.py)

**文件路径**: `scratch/debug_bing_html.py`

> *暂无详细模块级别文档注释.*

---

### 📄 [debug_bing_video.py](file:///d:/project-edumatrix/edumatrix-main/scratch/debug_bing_video.py)

**文件路径**: `scratch/debug_bing_video.py`

> *暂无详细模块级别文档注释.*

---

### 📄 [debug_pdf_trace.py](file:///d:/project-edumatrix/edumatrix-main/scratch/debug_pdf_trace.py)

**文件路径**: `scratch/debug_pdf_trace.py`

> *暂无详细模块级别文档注释.*

---

### 📄 [find_3b1b_bvid.py](file:///d:/project-edumatrix/edumatrix-main/scratch/find_3b1b_bvid.py)

**文件路径**: `scratch/find_3b1b_bvid.py`

> *暂无详细模块级别文档注释.*

---

### 📄 [find_all_non_test_users.py](file:///d:/project-edumatrix/edumatrix-main/scratch/find_all_non_test_users.py)

**文件路径**: `scratch/find_all_non_test_users.py`

> *暂无详细模块级别文档注释.*

---

### 📄 [find_template_close.py](file:///d:/project-edumatrix/edumatrix-main/scratch/find_template_close.py)

**文件路径**: `scratch/find_template_close.py`

> *暂无详细模块级别文档注释.*

---

### 📄 [find_template_end.py](file:///d:/project-edumatrix/edumatrix-main/scratch/find_template_end.py)

**文件路径**: `scratch/find_template_end.py`

> *暂无详细模块级别文档注释.*

---

### 📄 [find_user_data.py](file:///d:/project-edumatrix/edumatrix-main/scratch/find_user_data.py)

**文件路径**: `scratch/find_user_data.py`

> *暂无详细模块级别文档注释.*

---

### 📄 [fix_export_pdf.py](file:///d:/project-edumatrix/edumatrix-main/scratch/fix_export_pdf.py)

**文件路径**: `scratch/fix_export_pdf.py`

> *暂无详细模块级别文档注释.*

---

### 📄 [get_file_times.py](file:///d:/project-edumatrix/edumatrix-main/scratch/get_file_times.py)

**文件路径**: `scratch/get_file_times.py`

> *暂无详细模块级别文档注释.*

---

### 📄 [query_db.py](file:///d:/project-edumatrix/edumatrix-main/scratch/query_db.py)

**文件路径**: `scratch/query_db.py`

> *暂无详细模块级别文档注释.*

---

### 📄 [query_db_backup.py](file:///d:/project-edumatrix/edumatrix-main/scratch/query_db_backup.py)

**文件路径**: `scratch/query_db_backup.py`

> *暂无详细模块级别文档注释.*

---

### 📄 [query_db_backup_demo.py](file:///d:/project-edumatrix/edumatrix-main/scratch/query_db_backup_demo.py)

**文件路径**: `scratch/query_db_backup_demo.py`

> *暂无详细模块级别文档注释.*

---

### 📄 [query_db_backup_lzz.py](file:///d:/project-edumatrix/edumatrix-main/scratch/query_db_backup_lzz.py)

**文件路径**: `scratch/query_db_backup_lzz.py`

> *暂无详细模块级别文档注释.*

---

### 📄 [query_db_test.py](file:///d:/project-edumatrix/edumatrix-main/scratch/query_db_test.py)

**文件路径**: `scratch/query_db_test.py`

> *暂无详细模块级别文档注释.*

---

### 📄 [query_db_v2.py](file:///d:/project-edumatrix/edumatrix-main/scratch/query_db_v2.py)

**文件路径**: `scratch/query_db_v2.py`

> *暂无详细模块级别文档注释.*

---

### 📄 [restore_db.py](file:///d:/project-edumatrix/edumatrix-main/scratch/restore_db.py)

**文件路径**: `scratch/restore_db.py`

> *暂无详细模块级别文档注释.*

---

### 📄 [restore_truncate.py](file:///d:/project-edumatrix/edumatrix-main/scratch/restore_truncate.py)

**文件路径**: `scratch/restore_truncate.py`

> *暂无详细模块级别文档注释.*

---

### 📄 [search_html_occurrences.py](file:///d:/project-edumatrix/edumatrix-main/scratch/search_html_occurrences.py)

**文件路径**: `scratch/search_html_occurrences.py`

> *暂无详细模块级别文档注释.*

---

### 📄 [test_alternative_search.py](file:///d:/project-edumatrix/edumatrix-main/scratch/test_alternative_search.py)

**文件路径**: `scratch/test_alternative_search.py`

> *暂无详细模块级别文档注释.*

---

### 📄 [test_baidu_search.py](file:///d:/project-edumatrix/edumatrix-main/scratch/test_baidu_search.py)

**文件路径**: `scratch/test_baidu_search.py`

> *暂无详细模块级别文档注释.*

---

### 📄 [test_bili_api.py](file:///d:/project-edumatrix/edumatrix-main/scratch/test_bili_api.py)

**文件路径**: `scratch/test_bili_api.py`

> *暂无详细模块级别文档注释.*

---

### 📄 [test_bili_cookie.py](file:///d:/project-edumatrix/edumatrix-main/scratch/test_bili_cookie.py)

**文件路径**: `scratch/test_bili_cookie.py`

> *暂无详细模块级别文档注释.*

---

### 📄 [test_bili_search.py](file:///d:/project-edumatrix/edumatrix-main/scratch/test_bili_search.py)

**文件路径**: `scratch/test_bili_search.py`

> *暂无详细模块级别文档注释.*

---

### 📄 [test_bing_redirect.py](file:///d:/project-edumatrix/edumatrix-main/scratch/test_bing_redirect.py)

**文件路径**: `scratch/test_bing_redirect.py`

> *暂无详细模块级别文档注释.*

---

### 📄 [test_bing_search.py](file:///d:/project-edumatrix/edumatrix-main/scratch/test_bing_search.py)

**文件路径**: `scratch/test_bing_search.py`

> *暂无详细模块级别文档注释.*

---

### 📄 [test_bing_unicode.py](file:///d:/project-edumatrix/edumatrix-main/scratch/test_bing_unicode.py)

**文件路径**: `scratch/test_bing_unicode.py`

> *暂无详细模块级别文档注释.*

---

### 📄 [test_code_font.py](file:///d:/project-edumatrix/edumatrix-main/scratch/test_code_font.py)

**文件路径**: `scratch/test_code_font.py`

> *暂无详细模块级别文档注释.*

#### ⚙️ 独立函数 (Functions)

- `patched_make_styles()`: *无描述*

---

### 📄 [test_export_api.py](file:///d:/project-edumatrix/edumatrix-main/scratch/test_export_api.py)

**文件路径**: `scratch/test_export_api.py`

> *暂无详细模块级别文档注释.*

---

### 📄 [test_helvetica_chinese.py](file:///d:/project-edumatrix/edumatrix-main/scratch/test_helvetica_chinese.py)

**文件路径**: `scratch/test_helvetica_chinese.py`

> *暂无详细模块级别文档注释.*

---

### 📄 [test_keyword_search.py](file:///d:/project-edumatrix/edumatrix-main/scratch/test_keyword_search.py)

**文件路径**: `scratch/test_keyword_search.py`

> *暂无详细模块级别文档注释.*

---

### 📄 [test_math_pdf.py](file:///d:/project-edumatrix/edumatrix-main/scratch/test_math_pdf.py)

**文件路径**: `scratch/test_math_pdf.py`

> *暂无详细模块级别文档注释.*

---

### 📄 [test_pdf_long_code.py](file:///d:/project-edumatrix/edumatrix-main/scratch/test_pdf_long_code.py)

**文件路径**: `scratch/test_pdf_long_code.py`

> *暂无详细模块级别文档注释.*

---

### 📄 [test_profile_robustness.py](file:///d:/project-edumatrix/edumatrix-main/scratch/test_profile_robustness.py)

**文件路径**: `scratch/test_profile_robustness.py`

> *暂无详细模块级别文档注释.*

#### 📦 类定义 (Classes)

- **`class TestProfileRobustness`**: *无类文档*
  - **核心方法 (Methods)**:
    - `setUp()`: *无描述*
    - `tearDown()`: *无描述*
    - `test_dynamic_evidence_filtering()`: 1. 审计验证：特征级别证据链精确筛选
    - `test_concept_specific_weak_point_attribution()`: 2. 审计验证：薄弱点成因概念级精细诊断
    - `test_learning_event_bus_dynamic_update()`: 3. 审计验证：测验答题事件总线自动连通与雷达图刷新
    - `test_personalized_suggestions_summary()`: 4. 审计验证：教学建议个性化动态汇总与分层提炼
    - `test_misconception_score_reduction()`: 5. 审计验证：主观陈述误概念后评估分数正确降低

---

### 📄 [test_quote.py](file:///d:/project-edumatrix/edumatrix-main/scratch/test_quote.py)

**文件路径**: `scratch/test_quote.py`

> *暂无详细模块级别文档注释.*

---

### 📄 [test_screenshot_formulas.py](file:///d:/project-edumatrix/edumatrix-main/scratch/test_screenshot_formulas.py)

**文件路径**: `scratch/test_screenshot_formulas.py`

> *暂无详细模块级别文档注释.*

---

### 📄 [test_search_videos.py](file:///d:/project-edumatrix/edumatrix-main/scratch/test_search_videos.py)

**文件路径**: `scratch/test_search_videos.py`

> *暂无详细模块级别文档注释.*

---

### 📄 [test_subsup.py](file:///d:/project-edumatrix/edumatrix-main/scratch/test_subsup.py)

**文件路径**: `scratch/test_subsup.py`

> *暂无详细模块级别文档注释.*

---

### 📄 [test_ultimate_sanitizer.py](file:///d:/project-edumatrix/edumatrix-main/scratch/test_ultimate_sanitizer.py)

**文件路径**: `scratch/test_ultimate_sanitizer.py`

> *暂无详细模块级别文档注释.*

---

### 📄 [try_delete.py](file:///d:/project-edumatrix/edumatrix-main/scratch/try_delete.py)

**文件路径**: `scratch/try_delete.py`

> *暂无详细模块级别文档注释.*

---

### 📄 [stream_api.py](file:///d:/project-edumatrix/edumatrix-main/stream_api.py)

**文件路径**: `stream_api.py`

> *暂无详细模块级别文档注释.*

#### ⚙️ 独立函数 (Functions)

- `_run_formative_check()`: 根据教学内容生成快速理解检查的关键词和判断。
- `_extract_suggested_questions()`: *无描述*
- `_calculate_rdi()`: *无描述*
- `_sse()`: *无描述*
- `_format_chat_history()`: 从 profile.history 中提取最近的对话历史（包含学生提问和助教回答）。
- `_socratic_fallback()`: LLM 不可用时返回模板化兜底解释。

---

### 📄 [swarm_factory.py](file:///d:/project-edumatrix/edumatrix-main/swarm_factory.py)

**文件路径**: `swarm_factory.py`

> *暂无详细模块级别文档注释.*

#### ⚙️ 独立函数 (Functions)

- `build_swarm_from_headers()`: *无描述*

---

### 📄 [swarm_orchestrator.py](file:///d:/project-edumatrix/edumatrix-main/swarm_orchestrator.py)

**文件路径**: `swarm_orchestrator.py`

> *暂无详细模块级别文档注释.*

#### ⚙️ 独立函数 (Functions)

- `build_parser()`: *无描述*
- `main()`: *无描述*

---

### 📄 [test_edumatrix.py](file:///d:/project-edumatrix/edumatrix-main/test_edumatrix.py)

**文件路径**: `test_edumatrix.py`

> *暂无详细模块级别文档注释.*

#### 📦 类定义 (Classes)

- **`class EduMatrixPipelineTests`**: *无类文档*
  - **核心方法 (Methods)**:
    - `test_graph_visrag_retrieves_pooling_context()`: *无描述*
    - `test_drag_keeps_relevant_evidence()`: *无描述*
    - `test_alignment_detects_pooling_conflict()`: *无描述*
    - `test_swarm_generates_full_resource_package()`: *无描述*
    - `test_multi_agent_5_resources_concurrent_generation()`: 验证多智能体并发生成：5种资源类型 + asyncio.gather + 失败容错
    - `test_dialogue_profile_extracts_state_causes_and_percentages()`: *无描述*
    - `test_feedback_updates_mastery_and_metacognition()`: *无描述*
    - `test_behavior_sanity_hard_cap_locks_mastery()`: *无描述*
    - `test_machine_learning_course_flow_generates_strategy_plan()`: *无描述*
    - `test_zpd_path_planning_and_adaptive_teaching()`: 验证 ZPD 三档分类 + 前置回滚 + 自适应二档教学机制
    - `test_teacher_dashboard_exposes_heatmap_and_interventions()`: *无描述*
    - `test_kalman_filter_smoothing_and_state_recovery()`: 验证自适应卡尔曼滤波平滑估计以及从数据库快照冷启动状态恢复
    - `test_dynamic_concept_resolution_and_pronoun_alignment()`: 验证无白名单硬编码的动态指代消解与实体链接功能
    - `test_drag_debate_cleans_low_quality_evidence()`: *无描述*
    - `test_sm2_flashcard_scheduling()`: *无描述*
    - `test_flashcard_bootstrapping_and_due_endpoint()`: *无描述*
    - `test_learning_event_bus_subscribe_publish()`: *无描述*
    - `test_circuit_breaker_opens_after_failures()`: *无描述*
    - `test_visrag_images_exist()`: *无描述*
    - `test_report_api_browser_pool_exists()`: 验证 PDF 导出模块 BrowserPool 存在且功能正确
    - `test_sse_syntax_buffer_in_store()`: 验证 SSE 流式响应语法缓冲（Task 4.1）
    - `test_frontend_core_components_exist()`: 验证测试手册中所有前端核心组件存在且包含关键功能
    - `test_ingestion_pipeline_indexes_future_course_materials()`: *无描述*
    - `test_retrieval_evaluation_reports_recall_and_mrr()`: *无描述*
    - `test_telemetry_records_pipeline_metrics()`: *无描述*
    - `test_database_pool_wash_with_postgres_mock()`: *无描述*
    - `test_stream_disconnect_handling()`: *无描述*
    - `test_guided_decoding_self_healing()`: *无描述*
    - `test_export_note_pdf_endpoint()`: *无描述*
    - `test_sandbox_resource_limits_and_timeout()`: *无描述*
    - `test_sandbox_class_execution()`: *无描述*
    - `test_database_cascade_deletes()`: *无描述*
    - `test_database_concurrency_writes()`: *无描述*
    - `test_coreference_resolution_with_garbage_words()`: 验证口语指代消解在垃圾词打断场景下的自愈与兜底机制
    - `test_automatic_review_plan_generation_on_chat()`: 验证在对话框学习后自动在 review_plans 表生成复习安排的机制
    - `test_manual_review_plan_creation_without_preexisting_profile()`: 验证在学生画像表尚无记录时，手动创建复习计划也能安全自愈通过
    - `test_delete_student_concept_endpoint()`: 验证删除垃圾知识点 API 能够精准清理画像和复习计划表中的条目
    - `test_flashcard_review_updates_persisted_sm2_plan_without_memory_card()`: The review API should update review_plans even if no in-memory card exists.
    - `test_animation_dataset_feeds_resource_aware_planning()`: 本地 animations 数据集应能进入动态图谱，并为路径规划提供资源信号。
    - `test_adaptive_astar_route_expands_prerequisites_deterministically()`: A* 路径应稳定生成，并补齐多前置概念中的必要依赖。
    - `test_path_planner_respects_goal_variants_and_mastered_boundary()`: PathPlanner 应能针对不同目标/薄弱点生成稳定路线，并处理全掌握边界。
    - `test_learning_path_api_exposes_adaptive_astar_route()`: 学习路径 API 应暴露成员 2 的微概念图谱与 A* 动态路线。
    - `test_composite_concept_prerequisite_inference()`: 验证复合知识点（如卷积核与注意力机制的数学统一性）不会因缺少静态条目而跌落至 Tier 0，而是会自动识别其子概念作为前置
    - `test_note_matrix_closed_loop()`: 验证矩阵闭环学习流：笔记更新、AI 润色解析以及错题反思追加这套完整链路的正确性
    - `test_checkin_flow_and_streak()`: 验证复习打卡签到和连续天数（Streak）计算的完整流程
    - `test_checkin_history_filtering()`: 验证签到历史查询与过滤逻辑
    - `test_conversation_history_endpoint()`: 验证对话历史接口的数据返回和属性映射
    - `test_stream_chat_records_conversation_in_history()`: 验证流式对话接口 (/api/stream/chat) 会正确将对话写入数据库中
    - `test_pdf_upload_and_parsing()`: 验证 PDF 上传和解析不会因 BytesIO/seek 属性缺失而导致 500 崩溃
    - `test_docx_upload_and_parsing()`: 验证 Word (.docx) 上传和解析逻辑能够正常提取文本与入库
    - `test_socratic_explain_multi_round()`: 验证苏格拉底即时答疑接口在单轮和多轮追问模式下的参数和路由行为
    - `test_notebooklm_suggested_questions()`: 验证 NotebookLM 式建议追问提取及流式返回正确性
    - `test_component_regeneration_endpoint()`: *无描述*
    - `test_lmcd_knowledge_diffusion()`: 验证 LMCD 知识扩散算法：当某个核心概念变化时，其增量会正确传播到邻近概念
    - `test_council_mode_consensus_synthesis()`: 验证 Council Mode 委员会机制对平行生成的资源进行共识评测与幻觉拦截
    - `test_profile_analysis_includes_narrative_report()`: 验证 StoryLensEdu 叙事驱动评估报告管道：请求画像分析时应包含个性化成长信笺
    - `test_rdi_and_peer_pk_challenge()`: 验证 RDI 风险指数计算以及 👥 找学伴 PK 的对抗拦截推流逻辑
    - `test_profile_update_endpoint()`: 验证学生画像更新接口正确性，能够修改并持久化各个偏好字段，并且清除信笺缓存
    - `test_customized_fields_protection()`: 验证手动设定的画像字段受保护不会被大模型/消息自诊断算法篡改。
    - `test_multi_layer_cognitive_dimension_tracking()`: 验证多层级认知维度分解：单独更新不同维度时，BKT 与画像中的 concept_layers 可以正确分离与同步。
    - `test_collaborative_peer_based_prior_calibration()`: 验证协同画像先验校准：新冷启动学生会根据匹配相似度的 Peer 数据做画像先验合并与状态恢复。
    - `test_uncertainty_aware_active_learning()`: 验证主动探索与不确定性消除：若未显式指定，生成测试题时优先寻找估计误差协方差 p_err 最大的概念。
    - `test_causal_conflict_attribution_and_self_healing()`: 验证因果冲突归因与自愈引擎：一致性冲突发生时，能准确归因责任智能体，并在下次循环中注入自愈提示规则。
    - `test_kalman_filter_duration_noise_adjustment()`: 验证自适应卡尔曼滤波在答题时间极短时调整测量噪声 R
    - `test_poincare_depth_alignment()`: 验证双曲庞加莱圆盘层级对齐：深度越深的概念，投影后半径越大，防止流形退化
    - `test_graph_kalman_propagation()`: 验证图卡尔曼信念传播：更新节点，前置节点与后续依赖节点同步平滑演进
    - `test_dkt_and_ekf_concurrency_and_math_consistency()`: Task 4: 验证 DktService 并发更新的线程安全性、EKF 状态转移矩阵的行和恒为 1.0，以及非阻塞 MDS 异步运行
    - `test_dkt_dynamic_concept_tracking_and_ekf_backward_propagation()`: 验证 DKT 动态概念追踪和 EKF 双向信念传播与行和守恒
    - `test_direct_slash_commands_routing()`: 验证 Slash 快捷指令能够绕过常规意图分类，直接将定向参数及约束传给 EduMatrixSwarm
    - `test_rag_document_constraint_retrieval()`: 验证 @ 课件引用约束能够成功地把检索候选池约束到特定课件
    - `test_multiple_doc_constraints_filtering()`: 验证多文档约束条件下的前置过滤与合并检索
    - `test_add_web_source_endpoint()`: 测试 POST /api/knowledge/add-web-source 接口
    - `test_web_search_category_and_file_type_detection()`: 测试 Web 搜索的分类查询（在线网页/文档）以及返回项的文件类型检测标记
    - `test_web_search_query_normalization_and_relevance()`: 测试 Web 搜索对类似 '深度学习卷积' 模糊词的 Query 规范化与相关度防错防护
    - `test_download_web_file_pipeline()`: 测试在线文档流式下载与本地 RAG 深度导入管道 (Mock 下载和解析)
    - `test_web_source_dehydration_summary()`: 测试网页导入时，LLM 智能脱水总结将其格式化为结构化 Markdown 笔记的过程
    - `test_get_single_document_details()`: 测试 GET /api/knowledge/{doc_id} 接口以获取知识库文档完整文本内容
    - `test_video_embedded_url_mapping()`: *无描述*
    - `test_video_recommender_swarm_flow()`: *无描述*
    - `test_anonymous_data_migration()`: 验证匿名临时ID的数据能够在登录时成功迁移/合并到正式账号中。

---

### 📄 [vector_store.py](file:///d:/project-edumatrix/edumatrix-main/vector_store.py)

**文件路径**: `vector_store.py`

> *暂无详细模块级别文档注释.*

#### 📦 类定义 (Classes)

- **`class VectorIndex`**: *无类文档*
  - **核心方法 (Methods)**:
    - `upsert()`: *无描述*
    - `search()`: *无描述*
    - `count()`: *无描述*
- **`class InMemoryVectorIndex`**: *无类文档*
  - **核心方法 (Methods)**:
    - `upsert()`: *无描述*
    - `remove_by_source()`: *无描述*
    - `search()`: *无描述*
    - `count()`: *无描述*

#### ⚙️ 独立函数 (Functions)

- `evidence_to_text()`: *无描述*
- `_cosine_01()`: *无描述*
- `create_index()`: *无描述*

---

### 📄 [vector_store_faiss.py](file:///d:/project-edumatrix/edumatrix-main/vector_store_faiss.py)

**文件路径**: `vector_store_faiss.py`

> *暂无详细模块级别文档注释.*

#### 📦 类定义 (Classes)

- **`class FaissVectorIndex`**: *无类文档*
  - **核心方法 (Methods)**:
    - `__post_init__()`: *无描述*
    - `_ensure_index()`: *无描述*
    - `_get_all_vectors()`: *无描述*
    - `_embed()`: *无描述*
    - `_embed_text()`: *无描述*
    - `upsert()`: *无描述*
    - `search()`: *无描述*
    - `count()`: *无描述*
    - `save()`: *无描述*
    - `load()`: *无描述*

---

### 📄 [web_demo.py](file:///d:/project-edumatrix/edumatrix-main/web_demo.py)

**文件路径**: `web_demo.py`

> *暂无详细模块级别文档注释.*

#### 📦 类定义 (Classes)

- **`class EduMatrixHandler`**: *无类文档*
  - **核心方法 (Methods)**:
    - `do_GET()`: *无描述*
    - `do_POST()`: *无描述*
    - `_send_json()`: *无描述*
    - `_send_html()`: *无描述*
    - `log_message()`: *无描述*

#### ⚙️ 独立函数 (Functions)

- `_seed_demo_class()`: *无描述*
- `_profile_card()`: *无描述*
- `_teacher_dashboard()`: *无描述*
- `_resource_summary()`: *无描述*
- `_package_response()`: *无描述*
- `main()`: *无描述*

---

### 📄 [web_search_api.py](file:///d:/project-edumatrix/edumatrix-main/web_search_api.py)

**文件路径**: `web_search_api.py`

> *暂无详细模块级别文档注释.*

#### ⚙️ 独立函数 (Functions)

- `_generate_id()`: *无描述*
- `_clean_search_query()`: *无描述*
- `_get_optimized_query_candidates()`: *无描述*
- `_is_result_relevant()`: *无描述*
- `_parse_duckduckgo_lite_html()`: *无描述*
- `_parse_duckduckgo_html()`: *无描述*
- `_parse_baidu_html()`: *无描述*
- `_parse_bing_html()`: *无描述*
- `search_arxiv()`: 内部函数：并发调用的 arXiv 学术检索接口（带自动重试抗压机制）
- `to_embedded_player_url()`: *无描述*

---

