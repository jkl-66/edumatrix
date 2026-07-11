# Walkthrough - 成员 1 第一部分算法优化与前端高感知展示方案实现报告

我们已成功将成员 1 负责的算法重构和前端高感知展示方案落地。经过本地 52 项单元测试的校验，系统所有核心功能完全绿灯通过（All Passed）。

---

## 🛠️ 第一部分：后端算法去硬编码与高精度重构

### 1. Poincaré 双曲几何空间流形对齐
*   **物理文件**：[manifold_alignment.py](file:///d:/project-edumatrix/edumatrix-main/manifold_alignment.py)
*   **重构内容**：
    *   移除了用欧式余弦相似度假冒双曲测地距离的 Hardcode，落地了标准的 Poincaré Ball 测地线距离公式：
        $$d(u,v) = \text{arcosh}\left(1 + 2\frac{\|u-v\|^2}{(1-\|u\|^2)(1-\|v\|^2)}\right)$$
    *   增加了模长截断防御设计（$\|x\| \le 1 - \epsilon$），防止发散引发的 `NaN` 截断。
    *   设计了基于 NumPy 的高维流形变换投影矩阵 $W$ ($384 \times 384$)，将大语言模型提取的多模态语义实体投射到双曲认知流形。

### 2. 自适应噪声卡尔曼平滑估计器
*   **物理文件**：[bkt_engine.py](file:///d:/project-edumatrix/edumatrix-main/bkt_engine.py)、[learning_event_bus.py](file:///d:/project-edumatrix/edumatrix-main/learning_event_bus.py)
*   **重构内容**：
    *   编写了专用于状态平滑防抖的 `KalmanFilter` 状态估计器。根据答题数据反馈的一步测量值 $z_k$，执行学情防震荡平滑。
    *   **自适应噪声调整**：
        *   系统转移噪声 $Q_t$：依据学生心智负荷与挫败感，高负荷时调大 $Q_t$ 使得状态转移更具不确定性。
        *   测量观测噪声 $R_t$：若学生答题极快（秒过/手滑）或挫败感极高，自动调大 $R_t$，降低本次观测的卡尔曼增益。
    *   **状态冷启动反序列化还原**：重构了 `get_or_create` 方法，从持久层数据库中无缝反序列化恢复 `smoothed_mastery` 和误差协方差值 `p_err`。

### 3. 时序知识追踪与动态实体消解
*   **物理文件**：[agent_swarm.py](file:///d:/project-edumatrix/edumatrix-main/agent_swarm.py)
*   **重构内容**：
    *   彻底拆除写死的前置白名单和模糊指代概念映射，改由 `rag_engine.graph_rag.nodes` 动态拉取当前垂直课件领域中活跃的知识点节点。
    *   设计了基于大语言模型上下文检索的**指代消解与实体链接机制**：当提问中包含指示代词（“这个该怎么做”、“刚才说的那个”）时，提取 `profile.history` 最近 5 轮的上下文，通过 LLM 线程安全地消解判定并实体链接回活跃节点，大幅提升系统的人性化。

---

## 🎨 第二部分：前端高感知展示方案（让评委可见可感）

为了将算法底层的复杂度和技术壁垒直观呈现给国赛评委，我们实现了三大高张力、高感知的视觉组件：

### 1. 庞加莱圆盘 Canvas 非线性测地线动画
*   **页面/组件**：[ManifoldVisualizer.vue](file:///d:/project-edumatrix/edumatrix-main/frontend/src/components/ManifoldVisualizer.vue)
*   **视觉效果**：
    *   利用解析几何解出 Poincaré 圆盘下两点间正交于边界的唯一圆弧参数，渲染出**真实的双曲测地线（呈优美的弧线拓扑关系）**，而非生硬的直线。
    *   粒子在双曲测地圆弧线上顺畅流动，代表跨模态流形对齐过程。

### 2. 卡尔曼滤波“去噪防抖”对比折线图
*   **页面/组件**：[StudentAnalysis.vue](file:///d:/project-edumatrix/edumatrix-main/frontend/src/views/StudentAnalysis.vue)
*   **视觉效果**：
    *   在数字孪生面板中，同时呈现两条曲线：**原始观测线（灰白虚线）** 与 **卡尔曼滤波平滑估计线（流动发光实线）**。
    *   右侧配套展示滤波状态监控器（卡尔曼增益 $K_t$、噪声 $Q_t$、$R_t$、协方差 $P_t$），直观反映系统如何平滑抑制偶然手滑/脑雾带来的掌握度急剧跳变。

### 3. 认知置信带雷达图
*   **页面/组件**：[MasteryRadar.vue](file:///d:/project-edumatrix/edumatrix-main/frontend/src/components/MasteryRadar.vue)
*   **视觉效果**：
    *   在雷达图边缘绘制了一圈**半透明的发光环带（置信区间带）**，其宽度由卡尔曼误差协方差 $P_k$ 动态控制。
    *   测试样本少时，环带变宽，代表“测不准，置信度低”；随着做题增多，环带极速收窄并贴合实线圈，代表“测得准，置信度高”，用数学张力惊艳评委。

---

## 🚀 新增：擂主级算法与学术升格重构实现 (国赛擂主级天花板优化)

为了消除“课设级Demo”和“伪流形对齐”的痛点，我们在后端进行了深度学术升级：
1. **Dynamic DKT (动态维度知识追踪)**：
   * 在 [bkt_engine.py](file:///d:/project-edumatrix/edumatrix-main/bkt_engine.py) 中，对 `DktService` 重构，使其动态获取当前模型维度的参数，与权重文件 `dkt_weights.pth` 的输出层进行动态检测。
   * 自动过滤学科概念列表，如发生维度不匹配，则**自动、安全熔断降级**，退回到 HMM-BKT，绝不注入未训练的随机初始化 GRU 权重，防止脏数据污染学情画像。
2. **Graph-Kalman Belief Propagation (图扩展卡尔曼信念传播)**：
   * 将简单的图谱常数扩散（原向上 `0.4` 向下 `0.25` 粗暴加减）升级为 **EKF-style 虚拟卡尔曼量化信念传播**。
   * 相邻节点的更新量由其**自身的当前不确定性协方差 $P_j$** 与**图关联强度 $w_{ij}$** 动态联合控制（$K_j = P_j / (P_j + R_{\text{virtual}})$）。如果邻接节点已经处于低不确定性（高置信度），其学情更新微弱；如果处于高不确定性，其更新显著，且同步扣减其协方差，实现高严谨度的流形信念传导。
3. **Poincaré Contrastive Representation Learning (双曲对比学习对齐)**：
   * 编写了离线训练脚本 [train_poincare_alignment.py](file:///d:/project-edumatrix/edumatrix-main/scripts/train_poincare_alignment.py)。
   * 利用 PyTorch，在双曲庞加莱空间上定义对比损失，采用 Adam 优化器训练出了投影矩阵 $W$ （$384 \times 384$），使得正样本对（在 DAG 中邻近的概念）在 Poincaré 空间测地距离拉近，负样本对被推远（大于设定的 margin 阈值）。
   * 离线编译出 [poincare_projection.npy](file:///d:/project-edumatrix/edumatrix-main/data/poincare_projection.npy) 并在运行期由 [manifold_alignment.py](file:///d:/project-edumatrix/edumatrix-main/manifold_alignment.py) 动态加载。将“伪对齐”升级为真实的非欧空间几何结构对齐，彻底跨越至工业落地水准。

---

## 🧠 第三部分：成员 2 算法脱胎换骨与工业级升格重构实现 (路径规划与复习管理)

为了帮助成员 2 彻底告别“伪智能”与“硬编码妥协”，我们针对图谱构建、A* 路径规划和 Anki 复习引擎进行了以下三项擂主级的算法升级：

### 1. ACT-R 认知物理记忆衰减模型 (针对任务 3/复习打卡)
*   **物理文件**：[anki_engine.py](file:///d:/project-edumatrix/edumatrix-main/anki_engine.py)
*   **重构内容**：
    *   彻底消除了原来手写拼凑的线性扣减常数，引入了经典的 **ACT-R (Adaptive Control of Thought-Rational)** 认知科学记忆衰减公式。
    *   通过 Sigmoid 逻辑函数将学生实时的心智负荷与情绪挫败感平滑映射到记忆衰减率 $d$ 区间（$[0.3, 0.7]$，默认 $0.5$），再根据 $R_t = t^{-d}$ 记忆模型倒推得出复习间隔的动态指数缩放因子：
        $$\text{multiplier} = \left(\frac{0.5}{d}\right)^{1.5}$$
    *   **平滑阻尼调节**：高挫败感/高负荷时，复习间隔以非线性指数级收缩（加快复习频率），低负荷状态时自动平滑延伸间隔，消除原来的“双重惩罚与过度推送”弊端。

### 2. 基于前置约束的自适应拓扑前置展开与 A* 跨域类比混合寻路机制 (Hybrid Routing) (针对任务 2/路径规划)
*   **物理文件**：[learning_strategy.py](file:///d:/project-edumatrix/edumatrix-main/learning_strategy.py)
*   **重构内容**：
    *   **主干拓扑防线**：在学科内部采用自研的自适应拓扑前置展开算法逆向提取未掌握节点并排序，以防跳过前置物理防线，确保学科内的学习路径严格合规。
    *   **跨学科 A* 辅助类比寻路**：激活并重构了 $A^*$ 寻路引擎，在融合了 GraphRAG 关系与 Embedding 相似度分位数桥接的跨学科语义大图上运行。当主干概念面临高认知负荷或掌握度低时，系统利用 $A^*$ 算法从其他领域（如已掌握的数学概念）动态寻找一条最短代价值的支撑“脚手架”类比路径。
    *   **线程池开销消除**：在 `learning_strategy.py` 全局实例化了一个常驻的线程池解析器 `_PLANNER_EXECUTOR = ThreadPoolExecutor(max_workers=4)`。废除了之前每次接口请求都即时创建和销毁线程池的低效设计，消除了线程创建销毁带来的高额系统开销，实现真正非阻塞的 CPU 密集型路径查找。
    *   **Tarjan 环路自愈防御**：在 `build_resource_aware_dag` 中引入了基于 NetworkX `simple_cycles()` 的有向图环路扫描逻辑。一旦 GraphRAG 动态实体抽取在文本中引入了循环依赖冲突边（如 $A \rightarrow B \rightarrow A$），系统会自动识别并将触发冲突的动态边予以剔除，确保 A* 的拓扑自愈 Kahn 算法 100% 可行。

### 3. 自适应分位数动态阈值桥接 (针对任务 1/跨学科关联)
*   **物理文件**：[learning_strategy.py](file:///d:/project-edumatrix/edumatrix-main/learning_strategy.py)
*   **重构内容**：
    *   废除了硬编码的 `0.78`（语义边缘）和 `0.62`（跨域回退）绝对阈值。
    *   改为**动态分位数计算（Percentile-based similarities）**。在跨学科概念对的特征余弦相似度计算中，通过第一遍前向扫描，动态拟合当前领域下所有相似度分数的概率分布，自适应选取 **Top 15%（85th Percentile）** 作为语义桥接阈值，**Top 35%（65th Percentile）** 作为回退前置阈值，并设置合理防御性上下界。
    *   如此重构后，无论队友更换任何大/小维度的 Embedding 向量模型，系统图谱均能保持最合理的连接密度，具有极高的系统鲁棒性与工业泛化度。

---

## 🧪 验证结论
*   **后端测试运行命令**：`python -m pytest test_edumatrix.py`
*   **测试结果**：**64 passed** (耗时 28.18s)，所有回归测试及新追加用例全部绿灯通过！
*   **代码规范性**：严格遵守开发守则与命名转换防线（snake_case ➡️ camelCase），完美保持模块的高内聚低耦合状态。
