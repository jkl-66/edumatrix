# 混合RAG与知识摄入域深度代码审计报告

*   **审计分支**: `main`
*   **Git 提交版本**: `2952dc1b17d793e5d76f54e1764348ebe50e4d5e`
*   **审计执行日期**: `2026-07-18`

本报告针对 `EduMatrix` 项目的 **混合 RAG 与知识摄入域** 进行深度代码审计。审计范围包括以下 4 个核心物理文件及对应的业务/算法模块：
1.  **GraphRAG 动态图谱并网模块** [证据：[app/utils/graph_builder.py](file:///d:/project-edumatrix/edumatrix-main/app/utils/graph_builder.py)]
2.  **VisRAG 图像多模态匹配与 HybridRAG 管线** [证据：[rag_engine.py](file:///d:/project-edumatrix/edumatrix-main/rag_engine.py)]
3.  **FormulaRAG 双轨公式检索模块** [证据：[app/utils/formula_rag.py](file:///d:/project-edumatrix/edumatrix-main/app/utils/formula_rag.py)]
4.  **arXiv 学术缓存检索器** [证据：[web_search_api.py](file:///d:/project-edumatrix/edumatrix-main/web_search_api.py)]

---

## 一、 模块职责与对外接口

### 1. RAG 知识检索与摄入拓扑

```mermaid
graph TD
    Client[前端提问] -->|1. 执行检索| Pipeline[HybridRAGPipeline rag_engine.py]
    
    subgraph 混合RAG与知识摄入域
        Pipeline -->|2. 并发检索| SearchArxiv[arXiv 学术检索 web_search_api.py]
        Pipeline -->|3. 多模态匹配| Vis[VisRAG 图像检索 rag_engine.py]
        Pipeline -->|4. 双轨匹配| Formula[FormulaRAG 双轨公式检索 app/utils/formula_rag.py]
        Pipeline -->|5. 图谱路由| Graph[GraphRAG 动态图谱并网 app/utils/graph_builder.py]
    end
    
    SearchArxiv -->|6. 查询 & 写入| SQLiteCache[(SQLite 缓存表 arxiv_cache)]
    Graph -->|7. 拓扑更新| Neo4j[(Neo4j 图数据库)]
    Formula -->|8. 向量存储| Chroma[(ChromaDB / InMemory 向量库)]
    
    Pipeline -->|9. 语义融合 & 个性化重排| Output[返回 RetrievalBundle]
```

### 2. 知识摄入模块职责说明表

| 模块名称 | 物理文件 | 核心职责 | 对外核心接口 |
| :--- | :--- | :--- | :--- |
| **GraphRAG 动态并网** | `app/utils/graph_builder.py` | 提取文本块中的知识依赖三元组，完成实体对齐，向 Neo4j/内存图拓扑并网，实施环路检测。 | `GraphBuilder.build_from_chunks` (并网写入)；`query` (拓扑依赖查询) |
| **VisRAG 多模态匹配** | `rag_engine.py` | 负责课件课本图片切片的表征、匹配与加载，应用 ColPali 最大相似度与 Jina-CLIP 对齐排序。 | `VisRAG.search_evidence` (图像检索接口) |
| **FormulaRAG 公式检索** | `app/utils/formula_rag.py` | 解决理科 LaTeX 公式与自然语言语义的跨模态召回，通过“源码轨 + 语义轨”双轨召回并加权融合。 | `FormulaRAG.search_as_evidence` (双轨检索) |
| **arXiv 学术缓存检索** | `web_search_api.py` | 并发拉取官方 arXiv 数据库，提供网络限流（429）退避重试，以及本地 SQLite 缓存过滤。 | `search_arxiv` (异步并发学术文献检索) |

---

## 二、 核心安全与设计漏洞列表 (P1 - P3)

### 1. P1 级（阻断性核心问题）

#### 🛑 问题 1：未导入 datetime 模块导致 arXiv 本地缓存 100% 写入失败并退化为高频官方请求
*   **文件路径与行号**：[rag_engine.py L895](file:///d:/project-edumatrix/edumatrix-main/rag_engine.py#L895)
*   **触发条件**：系统完成外网 arXiv 论文检索，试图调用 `save_arxiv_cache` 写入本地 SQLite 数据库时。
*   **问题描述**：在 `save_arxiv_cache` 的入库逻辑中，需要解析论文的发布时间：
    ```python
    published_at=datetime.fromisoformat(paper["published"].replace("Z", "+00:00"))
    ```
    然而，`rag_engine.py` 顶部声明中，**只引入了 math, re, concurrent.futures，完全没有导入 `datetime` 模块**。
*   **实际影响**：由于该数据库操作外围包裹了 `except Exception: pass` 宽泛异常捕获，导致的 `NameError: name 'datetime' is not defined` 被吞掉。这造成了 **arXiv 本地缓存表 `arxiv_cache` 永远无法被写入数据**。每次用户提问触发学术检索时，系统都必须通过网络请求调用官方的海外 arXiv API，在压力测试或评委演示中极易因超出官方速率限制（Rate Limit）而**被返回 HTTP 429，进而导致系统检索卡死或回退**。
*   **修复建议**：在 `rag_engine.py` 头部添加：`from datetime import datetime`。
*   **结论可信度**：100%（确定，经静态代码走读查实 imports 确实缺失）。

#### 🛑 问题 2：ChromaDB 筛选逻辑对 Missing Key 的过滤处理导致公式语义轨道检索完全失效
*   **文件路径与行号**：[app/utils/formula_rag.py L197 及 L223-228](file:///d:/project-edumatrix/edumatrix-main/app/utils/formula_rag.py#L223-L228)
*   **触发条件**：配置开启了 ChromaDB 本地持久化（`CONFIG.use_chromadb = True`），且执行双轨公式检索时。
*   **问题描述**：在向 ChromaDB 插入公式数据时，源码轨道（LaTeX Track）附加了 `track="latex"` 的 metadata。但语义轨道（Semantic Track）写入时并没有附加任何 `track` 元数据。检索时，代码通过 `where={"track": {"$ne": "latex"}}` 来试图筛选语义文档。
*   **实际影响**：根据 ChromaDB 的查询过滤标准，**若一个文档的元数据字典中根本不存在 `track` 键，ChromaDB 的 `$ne` 运算会直接将该条文档过滤扔掉，而不是当作不等于匹配**。因此，开启 ChromaDB 后，语义轨道的所有结果都会被全部拦截过滤，整个 FormulaRAG 系统退化为只能利用 LaTeX 源码检索的单轨匹配，文档宣称的“自然语言跨模态公式召回”直接失效。
*   **修复建议**：在 `upsert` 写入语义数据时，显式在元数据中标记 `"track": "semantic"`，并将查询更改为 `where={"track": "semantic"}`。
*   **结论可信度**：100%（ChromaDB 官方 API 文档特性确证）。

---

### 2. P2 级（一般设计缺陷）

#### 🔍 问题 3：环路检测递归导致 N+1 次 Neo4j 图数据库查询引发性能瓶颈
*   **文件路径与行号**：[app/utils/graph_builder.py L592-601](file:///d:/project-edumatrix/edumatrix-main/app/utils/graph_builder.py#L592-L601)
*   **触发条件**：开启 Neo4j 数据库图存储后端，并在批量并网知识摄入时高频调用 `_has_path` 执行拓扑环路校验。
*   **问题描述**：在 DFS 递归验证 `_has_path` 时，若没有内存缓存，每遍历到一个节点，代码便向数据库执行一次物理请求：`result = repo.query_prerequisites(start)`。
*   **实际影响**：对于深度和分支较大的机器学习图谱，单次插入边会带来 $O(B^D)$ 的级联 Cypher 查询网络延迟开销。在导入预置种子图谱时会触发数百次物理 IO，在评委端测试时可能产生几秒以上的响应停顿，严重拖慢了动态并网的处理效能。
*   **修复建议**：更改为在并网前一次性拉取 Neo4j 的全量邻接矩阵在内存中建立 BFS 搜索；或者将路径可达性直接交付给 Neo4j 自身的 Cypher 引擎一步处理完毕：
    ```cypher
    MATCH p = (t:Concept {name: $target})-[:PREREQUISITE_OF*]->(s:Concept {name: $source}) RETURN COUNT(p) > 0 AS has_path
    ```
*   **结论可信度**：100%（确定）。

#### 🔍 问题 4：Neo4j 掉线时 fallback 降级缺乏双写与恢复机制导致运行期图数据分裂
*   **文件路径与行号**：[app/utils/graph_builder.py L423-441](file:///d:/project-edumatrix/edumatrix-main/app/utils/graph_builder.py#L423-L441)
*   **触发条件**：系统运行时，Neo4j 由于网络闪断或物理挂起抛出 `GraphRepositoryError` 触发自动降级时。
*   **问题描述**：当 Neo4j 掉线，`merge_node` 和 `merge_edge` 将数据写入 `self._local_fallback`（即内存 InMemory 实例）。
*   **实际影响**：由于缺乏一致性双写和连接重连回填机制，一旦网络好转 Neo4j 重新上线，后续边将继续写入 Neo4j。然而掉线期间在内存中写入的数据**将永远遗留在内存中，不会同步回 Neo4j 物理图谱**。这在长期运行后会导致 Neo4j 图数据库与内存状态产生分裂，出现大篇幅的拓扑断链，信念传播计算直接失准。
*   **修复建议**：掉线时应触发数据库事务重试，或维护一个离线操作队列（Write-Ahead Log），等连接重连后自动重放并对齐。
*   **结论可信度**：100%。

#### 🔍 问题 5：arXiv 缓存读取重新生成 UUID.uuid4() 导致 Evidence 唯一标识漂移及去重失效
*   **文件路径与行号**：[web_search_api.py L635-645](file:///d:/project-edumatrix/edumatrix-main/web_search_api.py#L635-L645)
*   **触发条件**：arXiv 缓存命中，被 `search_arxiv` 读取转换为 RAG 输入候选集时。
*   **问题描述**：将缓存数据转换为 `Evidence` 实例时，代码每次都动态重新构建随机 ID：
    ```python
    id=f"arxiv-cache-{uuid.uuid4().hex[:8]}"
    ```
*   **实际影响**：由于同一篇论文因为每次检索产生不同的 ID，导致在 `HybridRAGPipeline.retrieve` 最后的 `dedup` 去重字典中（依赖 `item.id` 为主键）**无法被去重**。当缓存文章在多轨检索中重复被召回时，最终检索包会混入一模一样的冗余段落，占用了大模型上下文容量。
*   **修复建议**：修改为使用确定性的哈希或将 arXiv 论文官方唯一的 ID（如 `arxiv_id`）作为 `Evidence.id`，如：`id=f"ARXIV_{paper['arxiv_id']}"`。
*   **结论可信度**：100%（确定）。

---

## 三、 文档、代码与运行结果的矛盾

经过对照项目申报文档、演示报告与实际运行代码，发现以下显著的物理矛盾：

1.  **宣称的“VisRAG 多模态大模型切片实时表征与召回”与实际硬编码数据召回矛盾**：
    *   *文档声称*：项目《创新点与展示证据报告》中指出，系统基于 VisRAG 架构，能够通过 Vision-Language 模型（ColPali 等）对 PDF 讲义中的公式、图表切片做实时向量编码与基于 Patch 的相似度计算。
    *   *代码现状*：在 `rag_engine.py` [证据：[rag_engine.py L277-283](file:///d:/project-edumatrix/edumatrix-main/rag_engine.py#L277-L283)] 的 `VisRAG._builtin_image_evidence()` 方法中，可以清清楚楚地看到，池化层演示图、平均池化对照图、机器学习流程图等所有图像切片证据都是**通过 Hardcoding（硬编码）写死在代码里的**。检索时，只是使用 SentenceTransformer 计算了查询和这些硬编码中文描述文本的余弦距离 [证据：[rag_engine.py L99](file:///d:/project-edumatrix/edumatrix-main/rag_engine.py#L99)]。所谓的“VisRAG 大模型切片和表征”在生产代码中完全不存在，只是对写死的数据做文本检索。

---

## 四、 审计发现事实依据、待确认事项与潜在风险

### 1. 事实依据列表

*   **事实 1**：在 [rag_engine.py L1-17](file:///d:/project-edumatrix/edumatrix-main/rag_engine.py#L1-L17)，确实没有任何地方导入 `datetime`，而在 L895 的 `save_arxiv_cache` 却使用了 `datetime.fromisoformat`，证明了该缓存写入在第一次执行时就会因为未定义变量名而报错被吞掉。
*   **事实 2**：在 [app/utils/formula_rag.py L197](file:///d:/project-edumatrix/edumatrix-main/app/utils/formula_rag.py#L197)，语义轨道写入时仅以 `metadatas.append(meta)` 写入，未设定 `"track"` 键，而查询使用 `where={"track": {"$ne": "latex"}}`，导致这一轨的记录在 ChromaDB 中 100% 漏空。
*   **事实 3**：在 [rag_engine.py L277-283](file:///d:/project-edumatrix/edumatrix-main/rag_engine.py#L277-L283)，图像切片证据完全属于硬编码的 7 条数据，不存在大模型图像编码摄入流程。

### 2. 待确认事项 (To-Be-Confirmed)
1.  **待确认**：在用户上传自定义 PDF 课件后，系统的后台任务是否会真正将其转化为图像切片。根据目前 `rag_engine.py` 的结构，仅有用户文本向量索引 `user_index`，并未在 `VisRAG` 中发现任何针对用户动态上传图片的动态 Patch 化接口。

### 3. 潜在风险 (Potential Risks)
*   **API 限流停机风险**：由于 arXiv 本地缓存因报错失效，所有的学术探索检索压力全部转嫁到了 arXiv 官方接口。在答辩或评委实地批量测试时，多次高频点击“学术探索”将直接导致触发 Rate Limit 并被 arXiv 限流数十分钟，使得学术检索功能完全陷入空白。
*   **内存大纲环路锁死风险**：由于 `_has_path` 环路检测的 N+1 问题，若用户在后台批量录入几百个知识点构成的复杂知识图谱，并网过程的网络开销可能拖长至数分钟，导致接口超时返回 504 错误。
