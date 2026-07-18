# 🏆 EduMatrix 智教矩阵 — NotebookLM 级资源解析与高保真知识库构建实施方案

本方案旨在为 **EduMatrix 智教矩阵系统** 打造媲美 Google NotebookLM 的高保真知识库构建与资源解析体验。通过升级版面重建能力、引入双轨父子切片、实现异步文档导读（Document Guides & FAQs）以及跨源拓扑关联，全面提升系统在学术和技术教育场景下的专业表现力。

---

## 一、 核心痛点与整改目标

1.  **PDF 文本提取杂乱无序**：当前采用 `PyPDF2` 简单提取文本，遇到表格容易错行，遇到 LaTeX 数学公式会变成乱码字符。我们将引入 `pdfplumber` 自动还原 Markdown 表格，并保证数学公式的 LaTeX 高保真解析。
2.  **RAG 切片语意断裂**：当前使用固定的 520 字符强行切片，切片极易在半句话中折断。我们将引入 **Parent-Child Chunking（父子分块）** 双轨索引，用子块（Child）匹配相似度，大模型阅读时还原为父块（Parent）以获得完整语意。
3.  **缺乏文档整体视角**：用户上传文件后，无法像 NotebookLM 那样瞬间看到核心提炼、FAQs 和关键看点。我们将设计 **异步文档导读（Document Guide & Auto FAQs）** 任务，并将数据渲染在前端预览 Modal 顶部。
4.  **多文档间缺乏拓扑共现关系**：各个知识文档在向量空间中是孤立的。我们将通过 `manifold_alignment` 流形相似度与 `GraphRAG`，自动建立跨文档的共现连接边（`CO_OCCUR`），实现跨文档知识互补。

---

## 二、 详细实施路径与Proposed Changes

### 1. 结构化版面重建（Markdown / LaTeX 还原）

#### 📂 涉及文件：[document_parser.py](file:///d:/project-edumatrix/edumatrix-main/document_parser.py)
*   **优化 `_parse_pdf(raw: bytes)` 提取算法**：
    *   引入 `pdfplumber` 作为高优先级 PDF 文本及表格分析器。
    *   在逐页解析时，自动调用 `page.extract_tables()` 提取页面中的物理表格数据。
    *   将提取出的表格通过格式化处理转化为标准的 Markdown 表格（例如 `| 概念 | 掌握度 |`），插入至页面文本的相应位置。
    *   支持页面中数学公式的 LaTeX 还原与标记提取，确保 KaTeX 排版正常。

---

### 2. 双轨父子分块机制（Parent-Child Semantic Chunking）

#### 📂 涉及文件：[document_parser.py](file:///d:/project-edumatrix/edumatrix-main/document_parser.py)
*   **重构 `chunk_document` 方法**：
    *   **父块（Parent Chunk - ~1000 - 1500字）**：按照自然段落或大页面单位切分，保存丰富的上下文信息。
    *   **子块（Child Chunk - ~200 - 250字）**：在父块内部进一步细切，用于向量匹配。
    *   在子块的 `Evidence.metadata` 属性中注入 `"parent_content": parent_chunk_text`。

#### 📂 涉及文件：[rag_engine.py](file:///d:/project-edumatrix/edumatrix-main/rag_engine.py)
*   **优化 `HybridRAGPipeline.retrieve` 检索合并链路**：
    *   在提取本地及用户知识库切片时，判断 `Evidence.metadata` 中是否含有 `"parent_content"` 属性。
    *   如果存在，在组装给大模型渲染的 Context 中，**自动使用父块的完整内容替换子块的局限内容**。
    *   这能保证检索匹配时极为精准，而大模型阅读时信息又连贯无损。

---

### 3. NotebookLM-Style 自动文档导读与 FAQs

#### 📂 涉及文件：[knowledge_api.py](file:///d:/project-edumatrix/edumatrix-main/knowledge_api.py)
*   **异步后台任务生成文档指南**：
    *   在上传（`POST /upload`）和下载（`POST /add-web-source`）接口中，注册一个异步非阻塞任务（Background Task）。
    *   调用系统统一 LLM 客户端（`llm_client.py`），对文档全文发出特定的 Prompt 提炼指令：
        ```text
        请仔细阅读以下文档内容，并生成一个 JSON 字典：
        {
          "brief_summary": "一句话核心梗概",
          "highlights": ["核心看点1", "核心看点2", "核心看点3", "核心看点4", "核心看点5"],
          "faqs": [
            {"q": "常见问题1", "a": "答案1"},
            {"q": "常见问题2", "a": "答案2"},
            {"q": "常见问题3", "a": "答案3"}
          ]
        }
        ```
    *   将返回的 JSON 字典保存到 `DBKnowledgeDocument.multimodal_metadata["doc_guide"]` 中。

#### 📂 涉及文件：[frontend/src/views/Chat.vue](file:///d:/project-edumatrix/edumatrix-main/frontend/src/views/Chat.vue)
*   **前端预览弹窗渲染升级**：
    *   在源预览弹窗（`DocViewerModal`）内，如果接口返回的文档数据含有 `doc_guide`：
    *   在 Modal 顶部新增一个毛玻璃渐变卡片（**导读指南面板**），以精致的排版展示“一句话概述”、“5大看点折叠面板”和“3个常见 FAQs 问答对”，完美复刻 NotebookLM 的体验。

---

### 4. 跨文档流形共现拓扑关联（GraphRAG 并网）

#### 📂 涉及文件：[knowledge_api.py](file:///d:/project-edumatrix/edumatrix-main/knowledge_api.py)
*   **跨文档相似度连线**：
    *   当新文档完成解析入库后，自动遍历其切片向量，计算与 FAISS 中已有其他文档切片向量的余弦相似度（Cosine Similarity）。
    *   当相似度高于阈值 **`0.85`** 时，在图谱数据库中为这两个切片对应的实体概念建立一条 **`CO_OCCUR`（共现交叉关联）** 边。
    *   图谱自生长模块能自动在前端力导向星图上画出虚线，指示“该文档内容与另一篇文档高强度互补相关”，打通多文档全局共现网络。

---

## 三、 验证方案 (Verification Plan)

### 1. 自动化单元测试
在 [test_edumatrix.py](file:///d:/project-edumatrix/edumatrix-main/test_edumatrix.py) 中编写并执行以下测试用例：
*   `test_pdf_layout_markdown_tables`：验证 `pdfplumber` 成功将 PDF 中的表格提取并序列化为标准 Markdown 表格。
*   `test_parent_child_context_replacement`：验证 RAG 提取结果成功用 `parent_content` 替换子切片。
*   `test_async_doc_guide_generation`：验证上传文档后，后台任务正确将 summary 和 FAQs 写入 DB 元数据中。

### 2. 手动功能演练
*   **编译构建**：运行 `npm run build`，确保前端依赖正常打包。
*   **预览演练**：在知识库中上传一篇复杂的课件 PDF，等待 5 秒解析，双击打开预览，验证弹窗顶部是否渲染出精美的一体化“导读指南与 FAQ”。
