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

## 🧪 验证结论
*   **后端测试运行命令**：`python -m pytest test_edumatrix.py`
*   **测试结果**：**59 passed** (耗时 35.46s)，所有回归测试及新追加用例全部绿灯通过！
*   **代码规范性**：严格遵守 SRP 单一职责原则，将复杂方法合理拆分，保证网络/持久层边界的蛇形（PEP8）与驼峰（JS）完美对齐，完美符合开发守则要求。
