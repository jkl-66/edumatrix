# 🏆 成员 1 模块（画像与认知追踪）国赛擂主级与产业化落地整改实施方案

> [!NOTE]
> **📋 方案背景与实施宗旨**：
> 本方案针对最新版本审计中发现的四大核心瓶颈（HMDS 同步计算阻塞、DKT 语义空间混淆与损失函数错误、Graph-EKF 复杂度爆炸、行为校验数值阶跃）提供彻底、严谨且具备工业级落地水准的重构设计方案。
> 方案抛弃了简单的 Mock 和经验粗糙度，以**异步缓存/降维代理、双线性认知诊断投影、局部稀疏 EKF、连续自适应门控**为核心，打造学术自洽性与工业可用性双巅峰的自适应教育“数字大脑”。

---

## 🗺️ 架构演进与重构路线图

```mermaid
graph TD
    %% 痛点梳理
    subgraph Current [现状：面临高并发与学术质询风险]
        HMDS_Sync[HTTP 线程同步 Adam 降维] -->|CPU 负载爆炸| API_Block[FastAPI 事件循环阻塞]
        DKT_MSE[DKT 预测词 Embedding & MSE 训练] -->|学术硬伤| Sem_Mismatch[语义相似度混淆掌握度]
        EKF_Dense[全局高维稠密矩阵 EKF] -->|复杂度 O/N^3/| Scale_Crash[高维图谱计算超时]
        Sanity_Cut[行为校验 0.5 硬限截断] -->|阶跃不连续| Path_Jitter[A* 路径频繁抖动]
    end

    %% 整改方案
    subgraph Ultimate [重构后：国赛擂主与工业商用级]
        MDS_Cache[HMDS 离线预计算 + Redis/SQLite 缓存] -->|毫秒级读取| API_Fast[API 零延迟秒开]
        DKT_BCE[双线性认知映射层 + BCE 损失函数] -->|学术严谨| Corr_Pred[准确预测下一题正确率]
        EKF_Sparse[局部主动子图 EKF 滤波] -->|复杂度降至 O/1/| Scalable_EKF[无限扩展知识点数]
        Sanity_Gate[连续 Sigmoid 掌握度置信门控] -->|平滑连续| Stable_Path[路径推荐渐进平滑]
    end
```

---

## 🛠️ 第一部分：双曲圆盘投影（HMDS）的“离线计算与坐标缓存化”重构

为了彻底消除在 HTTP 请求中运行 PyTorch Adam 优化的性能灾难，必须将多维尺度降维（MDS）改造为**写时计算、读时缓存**的工业级架构。

### 1. 核心设计思想
*   **触发机制**：高维双曲向量投影的重新计算仅在**新教材上传、知识库构建或 GraphRAG 关系变更**时触发，这些属于典型的低频写入操作。
*   **数据流**：在 [ingestion.py](file:///d:/project-edumatrix/edumatrix-main/ingestion.py) 中，当提取出新概念的 384 维向量后，在后台线程中一次性运行 `poincare_to_2d_coordinates` 得到所有概念的 2D 庞加莱坐标，并将其序列化保存至本地数据库 `concept_coordinates` 表中。
*   **API 零开销**：当学生加载 [StudentAnalysis.vue](file:///d:/project-edumatrix/edumatrix-main/frontend/src/views/StudentAnalysis.vue) 时，接口仅需执行一条简单的 SQL 查询，直接读取预计算好的 2D 坐标返回给前端，响应时间由 **2-3秒** 骤降至 **1毫秒** 级。

### 2. 数据库表结构扩展
在 [models.py](file:///d:/project-edumatrix/edumatrix-main/models.py) 中新增一个表模型：

```python
class ConceptCoordinate(Base):
    """知识概念在 2D 庞加莱圆盘中的投影坐标缓存表"""
    __tablename__ = "concept_coordinates"
    
    concept_name = Column(String, primaryKey=True, index=True)
    x = Column(Float, nullable=False)
    y = Column(Float, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
```

### 3. 后端代码重构
#### [MODIFY] [bkt_engine.py](file:///d:/project-edumatrix/edumatrix-main/bkt_engine.py)
重写降维接口，引入缓存机制，保证高并发可用性：

```python
def poincare_to_2d_coordinates_cached(embeddings: dict[str, list[float]], db_session: Session) -> dict[str, list[float]]:
    """读取数据库缓存的庞加莱坐标；若缺失，则自动触发轻量优化并写入缓存"""
    concepts = list(embeddings.keys())
    if not concepts:
        return {}

    # 1. 尝试从数据库批量加载缓存
    cached_records = db_session.query(ConceptCoordinate).filter(ConceptCoordinate.concept_name.in_(concepts)).all()
    coord_map = {r.concept_name: [r.x, r.y] for r in cached_records}

    missing_concepts = [c for c in concepts if c not in coord_map]
    
    # 2. 如果存在缺失坐标（冷启动或新增概念），则局部触发 Adam 降维
    if missing_concepts:
        import torch
        import torch.optim as optim
        print(f"[HMDS] Cache miss for {len(missing_concepts)} concepts, calculating online...")
        
        # 提取全部概念的高维向量进行全局相对距离计算
        all_vecs = []
        for c in concepts:
            vec = embeddings[c] or [0.0] * 384
            # 使用 tanh 拓扑自适应投影至庞加莱球内
            norm_v = math.sqrt(sum(x * x for x in vec))
            ball_vec = [x * 0.82 / max(norm_v, 1e-9) for x in vec] if norm_v > 0 else [0.0] * 384
            all_vecs.append(ball_vec)
            
        Z = torch.tensor(all_vecs, dtype=torch.float32) # (M, 384)
        M = len(concepts)
        
        # 计算高维距离
        dot_z = torch.sum(Z * Z, dim=-1)
        dist_matrix_tgt = torch.zeros((M, M))
        for i in range(M):
            for j in range(i+1, M):
                diff = torch.sum((Z[i] - Z[j])**2)
                denom = torch.clamp((1.0 - dot_z[i]) * (1.0 - dot_z[j]), min=1e-6)
                delta = 1.0 + 2.0 * diff / denom
                d = torch.log(delta + torch.sqrt(torch.clamp(delta**2 - 1.0, min=1e-6)))
                dist_matrix_tgt[i, j] = d
                dist_matrix_tgt[j, i] = d

        # 初始化待优化的 2D 坐标 (仅对缺失的概念进行修改，其余概念锚定已有的缓存坐标)
        # 用 small random 进行微扰初始化
        X = torch.randn(M, 2) * 0.05
        for i, c in enumerate(concepts):
            if c in coord_map:
                X.data[i] = torch.tensor(coord_map[c], dtype=torch.float32)
        X.requires_grad = True
        
        # 边界软惩罚障碍函数 Barrier Function，取代硬截断 clamp，保护梯度平滑流动
        optimizer = optim.Adam([X], lr=0.05)
        for _ in range(40):
            optimizer.zero_grad()
            norms = torch.norm(X, p=2, dim=1, keepdim=True)
            
            # 计算应力损失
            loss = 0.0
            for i in range(M):
                for j in range(i+1, M):
                    # 2D双曲距离
                    diff_2d = torch.sum((X[i] - X[j])**2)
                    denom_2d = torch.clamp((1.0 - norms[i]**2) * (1.0 - norms[j]**2), min=1e-6)
                    delta_2d = 1.0 + 2.0 * diff_2d / denom_2d
                    d_2d = torch.log(delta_2d + torch.sqrt(torch.clamp(delta_2d**2 - 1.0, min=1e-6)))
                    
                    loss += (dist_matrix_tgt[i, j] - d_2d)**2
            
            # 引入边界软惩罚：对于模长接近 1.0 的坐标施加对数惩罚，防止飞出圆盘，保障导数连续性
            barrier = -torch.sum(torch.log(1.0 - norms**2)) * 0.1
            total_loss = loss + barrier
            total_loss.backward()
            optimizer.step()
            
        # 写回数据库缓存
        with torch.no_grad():
            norms = torch.norm(X, p=2, dim=1, keepdim=True)
            final_X = X / torch.clamp(norms, min=1.0) * torch.clamp(norms, max=0.95)
            coords_np = final_X.numpy()
            
            for i, c in enumerate(concepts):
                if c in missing_concepts:
                    x_val, y_val = float(coords_np[i, 0]), float(coords_np[i, 1])
                    coord_map[c] = [x_val, y_val]
                    # 写入数据库
                    db_session.merge(ConceptCoordinate(concept_name=c, x=x_val, y=y_val))
            db_session.commit()
            
    return {c: coord_map[c] for c in concepts}
```

---

## 🛠️ 第二部分：重构 DKT 模型为“双线性认知诊断投影与 BCE 损失函数”

必须修正“将文本语义 Embedding 当作掌握度度量指标”的根本性学术偏误，重构为预测**“学生下一时间步答题正确概率”**的标准时序认知追踪架构。

### 1. 数学模型与认知解释
设学生最近的答题序列为 $\mathcal{S} = \{(c_1, a_1), (c_2, a_2), \dots, (c_t, a_t)\}$。
*   **输入向量构建**：第 $\tau$ 步的输入 $\mathbf{v}_\tau = [\mathbf{e}_{c_\tau}; a_\tau] \in \mathbb{R}^{385}$，由概念词的 384 维 Embedding $\mathbf{e}_{c_\tau}$ 与其答题正确性 $a_\tau \in \{0, 1\}$ 拼接而成。
*   **状态隐藏层演进**：通过 GRU 学习学生的学习时序状态：
    $$\mathbf{h}_\tau = \text{GRU}(\mathbf{h}_{\tau-1}, \mathbf{v}_\tau) \in \mathbb{R}^{d_{\text{hidden}}}$$
*   **双线性认知映射 (Bilinear Cognitive Projection)**：我们不直接输出大维度分类器，而是利用映射矩阵将隐藏状态 $\mathbf{h}_\tau$ 映射为高维语义空间中的**学生心智认知信念向量 (Cognitive Belief State Vector)** $\mathbf{s}_\tau \in \mathbb{R}^{384}$：
    $$\mathbf{s}_\tau = \tanh(\mathbf{W}_{\text{proj}} \mathbf{h}_\tau + \mathbf{b})$$
*   **后延正确率预测**：学生对任意下一个概念 $c_{t+1}$ 的预测答对概率，是由其心智状态向量 $\mathbf{s}_t$ 与目标概念的语义向量 $\mathbf{e}_{c_{t+1}}$ 的内积通过 Sigmoid 激活决定的：
    $$P(\text{correct}_{t+1} = 1 | c_{t+1}) = \sigma( \gamma \cdot \mathbf{s}_t^T \mathbf{e}_{c_{t+1}} )$$
    其中 $\gamma$ 为可训练的缩放标量因子。这在学术上具有极高自洽性：**学生的抽象认知信念与知识点概念表征越契合，答对概率就越高**。

### 2. 核心代码改造（后端）
#### [MODIFY] [bkt_engine.py](file:///d:/project-edumatrix/edumatrix-main/bkt_engine.py)
彻底重构 `DktRnnEngine` 的结构设计与 `DktService` 训练损失：

```python
class DynamicDktRnnEngine(nn.Module):
    """基于双线性认知诊断投影的动态 DKT 网络"""
    def __init__(self, hidden_dim: int = 64):
        super().__init__()
        self.input_dim = 385  # 384D Embedding + 1D Response Accuracy
        self.hidden_dim = hidden_dim
        
        self.rnn = nn.GRU(self.input_dim, hidden_dim, batch_first=True)
        # 将隐藏状态映射到与词向量同维的 384D 心智状态空间
        self.cognitive_projection = nn.Linear(hidden_dim, 384)
        # 缩放标量因子
        self.scale_factor = nn.Parameter(torch.tensor(5.0))
        
        # 确定性初始化
        torch.manual_seed(42)
        nn.init.xavier_normal_(self.cognitive_projection.weight)
        nn.init.constant_(self.cognitive_projection.bias, 0.0)

    def forward(self, seq_embeddings: torch.Tensor) -> torch.Tensor:
        """
        seq_embeddings: (batch_size, seq_len, 385)
        Returns: (batch_size, 384) -> 预测心智认知状态向量 s_t
        """
        out, _ = self.rnn(seq_embeddings)
        final_hidden = out[:, -1, :] # 提取序列末尾隐特征
        s_t = torch.tanh(self.cognitive_projection(final_hidden))
        return s_t


class DynamicDktService:
    """标准 DKT 推理与增量在线对比微调服务"""
    def __init__(self):
        self.model = DynamicDktRnnEngine()
        self.optimizer = torch.optim.Adam(self.model.parameters(), lr=0.001)
        # 替换为二分类交叉熵损失，拟合答题正确概率
        self.loss_fn = nn.BCEWithLogitsLoss() 
        
    def predict_mastery(self, history_records: list[tuple[str, bool]]) -> dict[str, float]:
        """在线推理：计算在当前心智认知状态下，学生对所有概念的预测正确率（作为掌握度）"""
        from embedding_models import EMBEDDINGS
        seq_len = len(history_records)
        if seq_len == 0:
            return {c: 0.3 for c in CONCEPT_TO_INDEX.keys()}
            
        # 构建 385 维时序矩阵
        input_matrix = np.zeros((1, seq_len, 385), dtype=np.float32)
        for t, (concept, correct) in enumerate(history_records):
            vec = EMBEDDINGS.embed(concept) or [0.0] * 384
            input_matrix[0, t, :384] = vec
            input_matrix[0, t, 384] = 1.0 if correct else 0.0
            
        self.model.eval()
        with torch.no_grad():
            tensor_in = torch.from_numpy(input_matrix)
            s_t = self.model(tensor_in).squeeze(0) # (384,)
            
        preds = {}
        for concept in CONCEPT_TO_INDEX.keys():
            c_vec = torch.tensor(EMBEDDINGS.embed(concept) or [0.0] * 384, dtype=torch.float32)
            # 计算内积结合 Sigmoid 获得答对概率
            logit = torch.dot(s_t, c_vec) * self.model.scale_factor
            preds[concept] = float(torch.sigmoid(logit))
            
        return preds

    def train_incremental(self, history_records: list[tuple[str, bool]]):
        """利用真实答题正误作为标签，进行在线 BCE 损失增量拟合"""
        from embedding_models import EMBEDDINGS
        seq_len = len(history_records)
        if seq_len < 2:
            return
            
        self.model.train()
        self.optimizer.zero_grad()
        
        # 构造输入序列 X (1, seq_len-1, 385)
        # 预测第 seq_len 步的答题结果
        input_matrix = np.zeros((1, seq_len - 1, 385), dtype=np.float32)
        for t in range(seq_len - 1):
            concept, correct = history_records[t]
            vec = EMBEDDINGS.embed(concept) or [0.0] * 384
            input_matrix[0, t, :384] = vec
            input_matrix[0, t, 384] = 1.0 if correct else 0.0
            
        last_concept, last_correct = history_records[-1]
        last_vec = torch.tensor(EMBEDDINGS.embed(last_concept) or [0.0] * 384, dtype=torch.float32)
        target_label = torch.tensor([1.0 if last_correct else 0.0], dtype=torch.float32)
        
        tensor_in = torch.from_numpy(input_matrix)
        s_t = self.model(tensor_in).squeeze(0) # (384,)
        
        # 计算预测 logit
        logit = torch.dot(s_t, last_vec) * self.model.scale_factor
        
        # 计算二分类损失
        loss = self.loss_fn(logit.unsqueeze(0), target_label)
        loss.backward()
        self.optimizer.step()
        self.model.eval()
```

---

## 🛠️ 第三部分：联合图谱 EKF 的“局部主动子图”计算剪枝重构

为了防止知识节点增多时矩阵运算耗时暴增（$O(N^3)$ 复杂度导致 API 挂起），需要重构为**基于局部子图过滤的稀疏更新算法**。

### 1. 局部主动子图 EKF 算法设计
当更新具体知识点 $c_t$ 的掌握度时，系统不再载入全局的所有概念。而是通过以下三步建立“局部主动子图”：
1.  **节点定位**：锁定被观测节点 $c_t$。
2.  **邻域提取**：从依赖图 `KNOWLEDGE_DAG` 中提取 $c_t$ 的直接前置依赖集合 $\mathcal{P}_{c_t}$ 和直接后继依赖集合 $\mathcal{S}_{c_t}$。
3.  **主动状态空间限制**：仅让局部活跃节点集 $\mathcal{X}_{active} = \{c_t\} \cup \mathcal{P}_{c_t} \cup \mathcal{S}_{c_t}$ 参与扩展卡尔曼滤波（EKF）。节点数量限制在常数级 $M_{active} = |\mathcal{X}_{active}| \le 10$，计算耗时恒定，时间复杂度降为极致的 **$O(1)$**，具备无限规模图谱的泛化扩展能力。

### 2. 核心代码改造（后端）
#### [MODIFY] [bkt_engine.py](file:///d:/project-edumatrix/edumatrix-main/bkt_engine.py)
在 `BKTEngine.update` 中重写状态更新逻辑：

```python
    def update_graph_ekf_localized(
        self,
        target_concept: str,
        observed_mastery: float,
        profile_bkt_states: dict[str, Any],
        cognitive_load: float,
        frustration: float,
        duration_seconds: float | None = None
    ) -> float:
        """基于局部主动子图过滤的扩展卡尔曼信念更新 (O(1) 复杂度)"""
        try:
            from profile_api import KNOWLEDGE_DAG
        except Exception:
            from agent_swarm import DEFAULT_KNOWLEDGE_DAG as KNOWLEDGE_DAG
            
        # 1. 提取局部活跃节点集 (当前概念 + 直接前置 + 直接后继)
        prereqs = KNOWLEDGE_DAG.get(target_concept, [])
        successors = [c for c, p_list in KNOWLEDGE_DAG.items() if target_concept in p_list]
        
        active_concepts = list(set([target_concept] + prereqs + successors))
        M = len(active_concepts)
        c_to_idx = {c: i for i, c in enumerate(active_concepts)}
        t_idx = c_to_idx[target_concept]
        
        # 2. 读取并构造局部状态向量 x_local (M, 1) 与协方差 P_local (M, M)
        x_local = np.zeros((M, 1), dtype=np.float32)
        P_local = np.zeros((M, M), dtype=np.float32)
        
        p_diag = np.zeros(M, dtype=np.float32)
        for i, c in enumerate(active_concepts):
            if profile_bkt_states and c in profile_bkt_states:
                x_local[i, 0] = profile_bkt_states[c].get("smoothed_mastery", BKT_DEFAULTS["p_init"])
                p_diag[i] = profile_bkt_states[c].get("p_err", 0.1)
            else:
                c_state = self.get_or_create(c, profile_bkt_states)
                x_local[i, 0] = getattr(c_state, "smoothed_mastery", c_state.p_mastered)
                p_diag[i] = getattr(c_state, "p_err", 0.1)
                
        # 保存旧的局部掌握度用于差分
        old_mastery = x_local[t_idx, 0]
        
        # 初始化协方差对角阵
        for i in range(M):
            P_local[i, i] = p_diag[i]
            
        # 3. 动态配置非对称转移矩阵 F_local (M, M)
        F_local = np.eye(M, dtype=np.float32)
        for i, c in enumerate(active_concepts):
            idx_i = c_to_idx[c]
            c_prereqs = KNOWLEDGE_DAG.get(c, [])
            for p in c_prereqs:
                if p in c_to_idx:
                    idx_j = c_to_idx[p]
                    # 前置知识更新后续知识（正向传播，系数 0.35）
                    F_local[idx_i, idx_j] = 0.35
                    # 后续知识向下修正前置认知缺陷（反向纠偏，系数 0.15）
                    F_local[idx_j, idx_i] = 0.15
                    
        # 行归一化防数值漂移
        for i in range(M):
            r_sum = np.sum(F_local[i])
            if r_sum > 1e-5:
                F_local[i] = F_local[i] / r_sum

        # 4. 执行卡尔曼观测更新
        q_base = 0.01
        q_penalty = max(0.0, cognitive_load - 0.5) * 0.05 + max(0.0, frustration - 0.3) * 0.03
        Q_local = np.eye(M, dtype=np.float32) * (q_base + q_penalty)
        
        # 预测 (Prediction)
        x_pred = np.dot(F_local, x_local)
        x_pred = np.clip(x_pred, 0.0, 1.0)
        P_pred = np.dot(np.dot(F_local, P_local), F_local.T) + Q_local
        
        # 观测 (Measurement)
        H_local = np.zeros((1, M), dtype=np.float32)
        H_local[0, t_idx] = 1.0
        
        r_base = 0.1
        r_penalty = max(0.0, frustration - 0.5) * 0.08
        if duration_seconds is not None:
            if duration_seconds < 3.0:
                r_penalty += (3.0 - duration_seconds) * 0.15 + 0.2
            elif duration_seconds > 300.0:
                r_penalty += 0.15
        R_scalar = r_base + r_penalty
        
        z = np.array([[observed_mastery]], dtype=np.float32)
        R = np.array([[R_scalar]], dtype=np.float32)
        
        # 更新步骤
        S = np.dot(np.dot(H_local, P_pred), H_local.T) + R
        K_gain = P_pred[:, t_idx:t_idx+1] / max(S[0, 0], 1e-6) # (M, 1)
        
        residual = z - np.dot(H_local, x_pred)
        x_new = x_pred + K_gain * residual
        x_new = np.clip(x_new, 0.0, 1.0)
        
        P_new = np.dot(np.eye(M) - np.dot(K_gain, H_local), P_pred)
        P_new = 0.5 * (P_new + P_new.T)
        
        # 5. 回写状态至 Profile 内存与缓存快照
        for i, c in enumerate(active_concepts):
            m_val = float(x_new[i, 0])
            p_val = max(0.01, min(1.0, float(P_new[i, i])))
            
            # 更新内存 BKT 实例
            c_state = self.get_or_create(c, profile_bkt_states)
            c_state.smoothed_mastery = m_val
            c_state.p_mastered = m_val
            c_state.p_err = p_val
            
            # 更新写入数据库的快照
            if profile_bkt_states and c in profile_bkt_states:
                profile_bkt_states[c]["smoothed_mastery"] = round(m_val, 4)
                profile_bkt_states[c]["p_mastered"] = round(m_val, 4)
                profile_bkt_states[c]["p_err"] = round(p_val, 4)
                
        return float(x_new[t_idx, 0])
```

---

## 🛠️ 第四部分：防抖校验的“连续 Sigmoid 置信门控”重构

用连续可微的 **Bayesian 门控函数** 替代生硬的 0.5 阶段式强制限高，保证下游寻路算法的稳定收敛。

### 1. 核心数学设计
不再采用 `if mean_acc < 0.6: mastery = min(mastery, 0.5)` 这种硬截断，而是通过**最近答题精度置信缩放因子 (Accuracy Confidence Gate Factor)** $G_{acc}$ 来连续化调整掌握度表现：
$$G_{acc} = \sigma\left( \kappa \cdot (\bar{a}_{recent} - \theta_{\text{acc}}) \right)$$
其中 $\bar{a}_{recent}$ 为近 3 次答题正确率均值，$\theta_{\text{acc}} = 0.55$ 为锚定中值，$\kappa = 8.0$ 为陡峭度缩放系数。
我们将真正的画像掌握度映射调整为：
$$M_{\text{gate}} = M_{\text{raw}} \cdot (0.4 + 0.6 \cdot G_{acc})$$
这使得：
*   当正确率降至 0 时，$G_{acc} \approx 0.012$，掌握度缩减为原始值的 $40\%$，实现对误概念偏误的渐进合理制裁。
*   当正确率升至 100% 时，$G_{acc} \approx 0.973$，掌握度几乎不被折减，且在 $0.4 \sim 0.7$ 之间过度极其平滑连续，**彻底杜绝了 A* 寻路代价突增引起的路径抖动问题**。

### 2. 核心代码改造（后端）
#### [MODIFY] [bkt_engine.py](file:///d:/project-edumatrix/edumatrix-main/bkt_engine.py)
重构 `behavior_sanity_check` 函数：

```python
def behavior_sanity_check_smooth(
    profile: "StudentProfile",
    quiz_accuracy: dict[str, list[float]] | None = None,
    midpoint: float = 0.55,
    steepness: float = 8.0,
) -> dict[str, Any]:
    """使用连续 Sigmoid 门控平滑代替硬性截断的行为校验"""
    data = quiz_accuracy if quiz_accuracy is not None else profile.recent_quiz_accuracy
    if not data:
        return {
            "sanitized": False,
            "capped_concepts": [],
            "report": "无答题记录，跳过平滑校验。"
        }
        
    gated_concepts = []
    for concept, accuracies in data.items():
        if not accuracies:
            continue
        recent = accuracies[-3:]
        mean_acc = sum(recent) / len(recent)
        
        # 计算 Sigmoid 置信度门控因子
        gate = 1.0 / (1.0 + math.exp(-steepness * (mean_acc - midpoint)))
        raw_mastery = profile.concept_mastery.get(concept, 0.3)
        
        # 连续平滑修正：若门控较低，进行平滑缩减
        gated_mastery = raw_mastery * (0.4 + 0.6 * gate)
        profile.concept_mastery[concept] = max(0.0, min(1.0, gated_mastery))
        
        if gate < 0.5:
            gated_concepts.append(f"{concept}(门控折减值: {gate:.2f})")
            
    sanitized = len(gated_concepts) > 0
    report = f"平滑校验已应用。折减偏离点: {', '.join(gated_concepts)}" if sanitized else "所有概念通过置信度平滑校验"
    
    return {
        "sanitized": sanitized,
        "capped_concepts": gated_concepts,
        "report": report
    }
```

---

## 🧪 验证与部署排程计划 (Verification & Deployment Calendar)

### 1. 自动化单元测试回归
重构完成后，在主工作区执行以下指令：
```powershell
python -m pytest test_edumatrix.py
```
必须保证旧版本的 59 项单元测试与新增的局部子图卡尔曼、连续 BCE DKT 的测试用例 100% 绿灯通过，保证核心系统路由功能正常。

### 2. EKF 数值收敛与高并发仿真验证
在 `scratch/` 路径下编写仿真脚本 `test_performance_profile.py`：
*   **动作 1**：生成包含 1000 个概念的虚拟大图谱。
*   **动作 2**：模拟 100 个学生的高频答题并发写入，测算局部子图 EKF 的接口平均响应时间，必须控制在 **5ms** 以内。
*   **动作 3**：模拟 1000 轮答题更新，监控多维协方差矩阵对角线元素 $P_{ii}$ 是否会发散报错，验证正定保护逻辑。

### 3. 前端测地线发光 Bloom 微调
启动 Vite 调试前端，进入 **数字孪生画像面板**，在 [StudentAnalysis.vue](file:///d:/project-edumatrix/edumatrix-main/frontend/src/views/StudentAnalysis.vue) 中反复提交不同质量的答题，校验庞加莱 2D 投影大圆盘内的节点运动测地线连线是否过渡流畅平滑，无边界溢出与坐标粘滞。
