# EduMatrix 后端防幻觉与域外平滑降级设计报告 (Backend Hallucination Prevention & Out-of-Domain Graceful Degradation Report)

## 一、 背景与挑战

1. **幻觉控制 (Hallucination Control)**: 当用户输入与知识库低相关或不相关的查询 (如随机字符 `"xyz123"`) 时，检索到的证据相关度极低。若系统强行送至下游生成模块，极易导致大语言模型产生严重幻觉。
2. **知识图谱域锁定 (Knowledge Graph Domain Locking)**: 系统内置标准的机器学习知识图谱。如果用户输入非机器学习概念 (如文学人物 `"李白"`), 传统的意图解析器通常会因为缺乏匹配节点而将其强制映射至默认节点 (如 `"池化层"`), 从而返回完全不相关的池化图谱与讲义，导致用户体验受损。

---

## 二、 解决方案实现

### 1. 低置信度拦截防御线 (Low-Confidence Prevention)

为了拦截低相关度输入，在以下模块中实施了级联判定与防御：

*   **数据模型扩充 ([models.py](file:///d:/project-edumatrix/edumatrix-main/models.py))**:
    *   在 `RetrievalBundle` 数据类中添加了 `low_confidence: bool = False` 状态字段。
*   **检索通道阈值拦截 ([rag_engine.py](file:///d:/project-edumatrix/edumatrix-main/rag_engine.py))**:
    *   在 `HybridRAGPipeline.retrieve` 与 `retrieve_async` 方法中，对最终合并并重排后的证据相关度分数计算 `max_score`。
    *   如果 `max_score < 0.20`，则判定为低置信度，并将 `low_confidence` 标记设为 `True`。
*   **辩论清洗判定 ([drag_debate.py](file:///d:/project-edumatrix/edumatrix-main/drag_debate.py))**:
    *   在 `DebateResult` 类中添加 `low_confidence: bool = False`。
    *   在双智能体辩论与数据清洗末尾，若清洗后的证据集为空或清洗后的证据最高分 `max_clean_score < 0.20`，则判定 `low_confidence` 为 `True`。
*   **主控协同调度拦截 ([agent_swarm.py](file:///d:/project-edumatrix/edumatrix-main/agent_swarm.py))**:
    *   在 `EduMatrixSwarm.async_process` 编排管线中，在完成检索与辩论后，首先执行低置信度校验。
    *   一旦 `debate_result.low_confidence` 或 `retrieval.low_confidence` 为 `True`，系统立即熔断，**直接绕过后续的资源生成工厂和对撞校验**，向学生返回标准防幻觉话术：
        `"抱歉，系统在知识库中未检索到与您提问相关的充足高置信度证据，为避免幻觉，建议您在‘课件管理’页面中上传包含该概念的教学资料。"`

### 2. 域外平滑降级防御线 (Out-of-Domain Graceful Degradation)

为了识别并优雅地处理非专业领域提问，在以下模块中实施了逻辑优化：

*   **数据模型扩充 ([models.py](file:///d:/project-edumatrix/edumatrix-main/models.py))**:
    *   在 `RetrievalBundle` 中引入了 `out_of_domain: bool = False`。
*   **领域感知识别 ([rag_engine.py](file:///d:/project-edumatrix/edumatrix-main/rag_engine.py))**:
    *   在 `HybridRAGPipeline` 中设计了 `_is_ml_concept(query)` 助手方法，通过对图谱所有节点名词以及标准术语别名（如机器学习、Deep Learning、AI、Pooling 等）进行匹配。
    *   若不匹配，则置 `out_of_domain = True`，**并完全跳过 GraphRAG 路径推理**，避免匹配至默认的“池化层”节点；检索时仅通过原始查询对普通多模态文本索引、arXiv 索引以及用户上传文档进行拉取。
*   **降级提示追加 ([agent_swarm.py](file:///d:/project-edumatrix/edumatrix-main/agent_swarm.py))**:
    *   在 `EduMatrixSwarm.async_process` 资源组装末尾，当检测到 `retrieval.out_of_domain` 为 `True` 时，系统将平滑降级提示信息自动追加在 `理论教授` 生成的 `专业讲义` 资源内容底部：
        `"\n\n*(提示：EduMatrix 标准学科大纲知识图谱暂未涵盖该领域，系统已自动切换至多模态混合文本检索与实时互联网检索模式进行解答，您可以上传相关课件以扩充图谱。)*"`

---

## 三、 测试与验证

### 1. 回归测试用例设计 ([tests/test_hallucination_prevention.py](file:///d:/project-edumatrix/edumatrix-main/tests/test_hallucination_prevention.py))

*   `test_low_confidence_blocking`:
    *   使用查询 `"xyz123"` 输入系统，验证 RAG 管道能够正确识别出 `low_confidence = True`。
    *   验证 `EduMatrixSwarm.process` 能够提前熔断并为所有五大智能体角色内容返回统一步调的课件上传提示文本，确保对齐。
*   `test_out_of_domain_graceful_degradation`:
    *   使用查询 `"李白"` 输入系统，验证 `out_of_domain` 属性成功被置为 `True`，且 `graph_context.learning_path` 为空。
    *   验证 `EduMatrixSwarm` 产出的 `专业讲义` 后缀中包含平滑降级切换多模态/实时检索的告知内容。

### 2. 运行结果

在工作空间中运行 `python -m pytest tests/test_hallucination_prevention.py -v` 验证结果如下：

```
tests/test_hallucination_prevention.py::TestHallucinationPrevention::test_low_confidence_blocking PASSED [ 50%]
tests/test_hallucination_prevention.py::TestHallucinationPrevention::test_out_of_domain_graceful_degradation PASSED [100%]

======================== 2 passed, 1 warning in 4.70s =========================
```

同时运行项目全体单元测试以保障向后兼容性：

```
======================= 23 passed, 1 warning in 34.02s ========================
```

所有功能完全就绪并 100% 验证通过。
