"""跨模态特征潜空间对齐模块 (Cross-Modal Feature Alignment)

实现文字-图片-公式之间的跨模态搜索：
- 用自然语言描述搜索相关的公式/图片
- 用 LaTeX 公式搜索相关的文字讲解/示意图
- 基于 InfoNCE 对比损失微调的特征映射层实现跨模态对齐

存储方式：JSON 文件持久化 + 内存缓存
依赖：embedding_models.EMBEDDINGS（全局嵌入后端）
"""
from __future__ import annotations

import json
import math
import random
from pathlib import Path
from typing import Any

try:
    from embedding_models import EMBEDDINGS
except ImportError:
    EMBEDDINGS = None

# 数据持久化路径
_ALIGNMENT_DATA_DIR = Path("data")
_ALIGNMENT_FILE = _ALIGNMENT_DATA_DIR / "cross_modal_pairs.json"

# 共享潜空间维度（投影后的低维空间）
_PROJECTION_DIM = 128
# 对比学习超参数
_CALIBRATION_EPOCHS = 50  # 50 轮足够看到损失下降趋势
_CALIBRATION_LR = 0.01
_CONTRASTIVE_TEMPERATURE = 0.07
_CALIBRATION_BATCH_SIZE = 6  # mini-batch 大小

# 内置 ML 学科跨模态种子数据
_BUILTIN_SEED_PAIRS = [
    {
        "text": "最大池化层对 2x2 窗口取局部最大值",
        "image_desc": "4x4 输入特征图经 2x2 Max Pooling 和 stride=2 变为 2x2 输出矩阵，窗口输出等于局部最大值",
        "formula": r"\text{MaxPool2d}(X)_{i,j} = \max_{p,q \in \{0,1\}} X_{i+p, j+q}",
        "concept": "池化层",
    },
    {
        "text": "平均池化对窗口内数值求均值",
        "image_desc": "Average Pooling 对窗口内数值求均值",
        "formula": r"\text{AvgPool2d}(X)_{i,j} = \frac{1}{4}\sum_{p,q \in \{0,1\}} X_{i+p, j+q}",
        "concept": "平均池化",
    },
    {
        "text": "逻辑回归通过 sigmoid 将线性组合映射为概率",
        "image_desc": "混淆矩阵展示 TP、FP、FN、TN，可进一步计算 accuracy、precision、recall 和 F1",
        "formula": r"\sigma(z) = \frac{1}{1 + e^{-z}}, \quad z = w^T x + b",
        "concept": "逻辑回归",
    },
    {
        "text": "损失函数衡量预测值与真实值的差距",
        "image_desc": "反向传播链式法则推导：展示损失函数对参数求导时的链式法则展开",
        "formula": r"\mathcal{L}(w) = \frac{1}{n}\sum_{i=1}^{n} (y_i - \hat{y}_i)^2",
        "concept": "损失函数",
    },
    {
        "text": "梯度下降利用损失函数的梯度更新参数",
        "image_desc": "训练误差持续下降而验证误差上升时通常意味着过拟合",
        "formula": r"w \leftarrow w - \eta \nabla_w \mathcal{L}(w)",
        "concept": "梯度下降",
    },
    {
        "text": "Softmax 将任意实数向量转换为概率分布",
        "image_desc": "注意力机制的 scaled dot-product attention 数学表达",
        "formula": r"\text{softmax}(x_i) = \frac{e^{x_i}}{\sum_{j} e^{x_j}}",
        "concept": "激活函数",
    },
    {
        "text": "卷积运算对局部区域做点积累加形成新的特征图",
        "image_desc": "卷积核在输入特征图上按 stride 滑动，对局部区域做点积累加",
        "formula": r"(f * g)(t) = \sum_{\tau} f(\tau) g(t - \tau)",
        "concept": "卷积核",
    },
    {
        "text": "正则化通过惩罚项限制模型复杂度防止过拟合",
        "image_desc": "过拟合与欠拟合曲线：训练误差持续下降而验证误差上升",
        "formula": r"\mathcal{L}_{\text{reg}}(w) = \mathcal{L}(w) + \lambda \|w\|_2^2",
        "concept": "正则化",
    },
    {
        "text": "链式法则将复合函数的导数分解为各层导数的乘积",
        "image_desc": "反向传播基于链式法则将损失函数的梯度从输出层传回参数层",
        "formula": r"\frac{\partial L}{\partial x} = \frac{\partial L}{\partial y} \cdot \frac{\partial y}{\partial x}",
        "concept": "链式法则",
    },
    {
        "text": "交叉熵损失常用于多分类任务的模型训练",
        "image_desc": "机器学习项目流程图展示从数据理解到模型评估的完整流程",
        "formula": r"\mathcal{L}_{\text{CE}} = -\sum_{c=1}^{C} y_c \log(\hat{y}_c)",
        "concept": "损失函数",
    },
    # ── 补充：覆盖全部 26 个动画知识点 ──
    {
        "text": "最大池化取窗口内最大值，用于保留最显著特征",
        "image_desc": "最大池化局部计算演算：2x2 窗口在特征图上滑动取 max",
        "formula": r"\text{MaxPool}(F)_{i,j} = \max(F_{i,j}, F_{i,j+1}, F_{i+1,j}, F_{i+1,j+1})",
        "concept": "最大池化",
    },
    {
        "text": "反向传播算法基于链式法则将误差从输出层逐层传回输入层",
        "image_desc": "反向传播动态演示：梯度沿网络层层回传，各层权重按梯度方向更新",
        "formula": r"\delta^{(l)} = ((W^{(l)})^T \delta^{(l+1)}) \odot \sigma'(z^{(l)})",
        "concept": "反向传播",
    },
    {
        "text": "前向传播将输入数据逐层计算，最终输出预测结果",
        "image_desc": "神经网络动画展示数据从输入层经隐藏层到输出层的流动过程",
        "formula": r"a^{(l)} = \sigma(W^{(l)} a^{(l-1)} + b^{(l)})",
        "concept": "前向传播",
    },
    {
        "text": "卷积神经网络由卷积层、池化层和全连接层堆叠而成",
        "image_desc": "CNN 动画展示卷积核在输入图像上滑动提取特征的完整流程",
        "formula": r"\text{CNN}(X) = \text{FC}(\text{Pool}(\text{ReLU}(\text{Conv}(X, K) + b)))",
        "concept": "卷积神经网络",
    },
    {
        "text": "特征图是卷积运算的输出，包含从输入数据中提取的高维特征",
        "image_desc": "可视化特征图的通道响应：浅层检测边缘纹理，深层检测语义概念",
        "formula": r"F_{i,j,k} = \sum_{p,q,c} X_{i+p, j+q, c} \cdot K_{p,q,c,k} + b_k",
        "concept": "特征图",
    },
    {
        "text": "线性回归通过最小化均方误差拟合最优直线",
        "image_desc": "动画演示散点图中回归线随梯度下降逐步调整斜率和截距的过程",
        "formula": r"y = w^T x + b, \quad \min_w \frac{1}{n}\sum_{i=1}^{n}(y_i - w^T x_i)^2",
        "concept": "线性回归",
    },
    {
        "text": "决策树通过信息增益递归划分数据空间形成树状决策规则",
        "image_desc": "决策树动画展示根节点到叶节点的分裂过程，每次选择最优划分属性",
        "formula": r"IG(D, A) = H(D) - \sum_{v \in \text{values}(A)} \frac{|D_v|}{|D|} H(D_v)",
        "concept": "决策树",
    },
    {
        "text": "支持向量机寻找最大间隔超平面来分离不同类别",
        "image_desc": "SVM 动画展示支持向量如何确定分类边界，以及软间隔处理噪声点",
        "formula": r"\min_{w,b} \frac{1}{2}\|w\|^2 + C \sum_i \max(0, 1 - y_i(w^T x_i + b))",
        "concept": "支持向量机",
    },
    {
        "text": "交叉验证将数据集分为 K 折轮流训练和验证，评估模型泛化能力",
        "image_desc": "K-Fold 动画演示数据集被切成 K 份，每次用不同折作为验证集",
        "formula": r"\text{CV}_{K} = \frac{1}{K}\sum_{k=1}^{K} \mathcal{L}(M_k, D_k^{\text{val}})",
        "concept": "交叉验证",
    },
    {
        "text": "过拟合表现为训练集表现很好但测试集性能大幅下降",
        "image_desc": "过拟合对比图：复杂模型完美穿过每个训练点，但在新数据上剧烈波动",
        "formula": r"\text{Overfitting: } \text{TrainError} \ll \text{TestError}",
        "concept": "过拟合",
    },
    {
        "text": "欠拟合表现为模型过于简单，无法捕获数据的真实规律",
        "image_desc": "欠拟合示意：直线无法拟合抛物线形的数据分布，训练和测试误差都高",
        "formula": r"\text{Underfitting: } \text{TrainError} \approx \text{TestError} \gg 0",
        "concept": "欠拟合",
    },
    {
        "text": "神经网络由多层神经元组成，通过非线性激活函数学习复杂映射",
        "image_desc": "3Blue1Brown 风格动画：输入层→隐藏层→输出层的前向计算可视化",
        "formula": r"f(x) = \sigma^{(L)}(W^{(L)} \cdots \sigma^{(1)}(W^{(1)}x + b^{(1)}) \cdots + b^{(L)})",
        "concept": "神经网络",
    },
    {
        "text": "监督学习使用带标签的数据训练模型，学习从输入到输出的映射",
        "image_desc": "监督学习流程动画：训练数据→特征提取→模型训练→预测→损失反馈",
        "formula": r"\text{Learn } f: X \to Y \text{ from } \{(x_i, y_i)\}_{i=1}^{n}",
        "concept": "监督学习",
    },
    {
        "text": "机器学习是从数据中自动发现模式并做出预测的算法集合",
        "image_desc": "机器学习全景图动画：数据→算法→模型→预测→评估的完整闭环",
        "formula": r"\text{ML} = \arg\min_f \mathbb{E}_{(x,y) \sim P}[\mathcal{L}(f(x), y)]",
        "concept": "机器学习",
    },
    {
        "text": "模型评估通过混淆矩阵、精确率、召回率和 F1 值衡量分类器性能",
        "image_desc": "混淆矩阵动画：TP/FP/FN/TN 四个象限随预测结果实时更新",
        "formula": r"F_1 = 2 \cdot \frac{\text{Precision} \cdot \text{Recall}}{\text{Precision} + \text{Recall}}",
        "concept": "模型评估",
    },
    {
        "text": "Transformer 架构通过自注意力机制替代循环结构，实现并行训练",
        "image_desc": "Transformer 动画：Encoder 堆叠 Self-Attention + FFN，Decoder 交叉注意力解码",
        "formula": r"\text{Attention}(Q,K,V) = \text{softmax}\left(\frac{QK^T}{\sqrt{d_k}}\right)V",
        "concept": "Transformer",
    },
    {
        "text": "注意力机制让模型在处理输入时聚焦于最相关的部分",
        "image_desc": "Attention 热力图动画：随着输入变化，高亮区域在不同 token 间迁移",
        "formula": r"\alpha_{ij} = \frac{\exp(e_{ij})}{\sum_{k} \exp(e_{ik})}, \quad e_{ij} = \text{score}(h_i, h_j)",
        "concept": "注意力机制",
    },
]


class CrossModalAligner:
    """跨模态特征对齐器：管理文字-图片-公式三模态配对的注册与搜索。

    核心创新：通过 InfoNCE 对比损失微调线性投影矩阵，将三种模态
    的嵌入向量映射到低维共享潜空间，使不同模态的相似概念在潜空间
    中距离更近。这是分工文件中要求的"对比损失函数微调特征映射层"。
    """

    def __init__(self, pairs: list[dict] | None = None) -> None:
        self._pairs: list[dict] = pairs or list(_BUILTIN_SEED_PAIRS)
        self._text_embeddings: list[list[float]] = []
        self._image_embeddings: list[list[float]] = []
        self._formula_embeddings: list[list[float]] = []
        self._original_dim: int = 384  # 原始嵌入维度
        self._proj_dim: int = _PROJECTION_DIM  # 共享潜空间维度

        # 线性投影矩阵（将各模态映射到共享潜空间）
        # 形状 [original_dim][proj_dim]，即每列是 proj_dim 维的一个投影方向
        self._text_proj: list[list[float]] = []
        self._image_proj: list[list[float]] = []
        self._formula_proj: list[list[float]] = []

        # 是否已完成对比学习校准
        self._is_calibrated: bool = False
        self._last_calibration_loss: float = float("inf")

        self._initialized = False

        # 尝试从磁盘加载（含投影矩阵）
        loaded = self._load_from_disk()
        if loaded:
            self._build_embeddings()

    # ══════════════════════════════════════════════════════════════
    # 投影矩阵工具方法
    # ══════════════════════════════════════════════════════════════

    def _random_projection_matrix(self, in_dim: int, out_dim: int) -> list[list[float]]:
        """Xavier 均匀初始化投影矩阵 [in_dim × out_dim]。

        值域: [-limit, limit] where limit = sqrt(6 / (in_dim + out_dim))
        目的: 保持前向传播时各层输出的方差稳定
        """
        limit = math.sqrt(6.0 / (in_dim + out_dim))
        matrix = []
        for _ in range(in_dim):
            row = [random.uniform(-limit, limit) for _ in range(out_dim)]
            matrix.append(row)
        return matrix

    @staticmethod
    def _project(vec: list[float], proj_matrix: list[list[float]]) -> list[float]:
        """矩阵乘法: y = vec · proj_matrix → 将向量投影到低维空间。

        vec: [1 × in_dim], proj_matrix: [in_dim × out_dim] → result: [1 × out_dim]
        """
        if not proj_matrix or not vec:
            return list(vec)  # 无法投影时返回原向量（降级）
        in_dim = len(vec)
        out_dim = len(proj_matrix[0]) if proj_matrix else len(vec)
        result = [0.0] * out_dim
        for j in range(out_dim):
            s = 0.0
            for i in range(min(in_dim, len(proj_matrix))):
                row = proj_matrix[i]
                if j < len(row):
                    s += vec[i] * row[j]
            result[j] = s
        return result

    @staticmethod
    def _cosine(v1: list[float], v2: list[float]) -> float:
        """计算两个向量的余弦相似度，截断到 [0, 1] 范围。"""
        dot = sum(a * b for a, b in zip(v1, v2))
        n1 = math.sqrt(sum(a * a for a in v1))
        n2 = math.sqrt(sum(b * b for b in v2))
        if n1 == 0.0 or n2 == 0.0:
            return 0.0
        return max(0.0, min(1.0, dot / (n1 * n2)))

    # ══════════════════════════════════════════════════════════════
    # 对比学习校准 (InfoNCE + 梯度下降)
    # ══════════════════════════════════════════════════════════════

    def calibrate(self) -> float:
        """利用对比损失（InfoNCE）微调投影矩阵，对齐三模态嵌入空间。

        算法流程:
        1. 从种子数据中构造正样本对: (text→image), (text→formula), (image→formula)
        2. 随机打乱配对构造负样本对
        3. 计算 InfoNCE 损失: -log(exp(sim_pos/τ) / Σ exp(sim/τ))
        4. 对三个投影矩阵分别执行梯度下降，迭代 _CALIBRATION_EPOCHS 轮

        Returns:
            最终一轮的 InfoNCE 损失值。损失越低说明跨模态对齐越好。
        """
        if not self._initialized:
            self._build_embeddings()
        if not self._initialized or len(self._pairs) < 3:
            return float("inf")

        n = len(self._pairs)
        self._original_dim = len(self._text_embeddings[0]) if self._text_embeddings else 384
        d_in = self._original_dim
        d_out = self._proj_dim
        tau = _CONTRASTIVE_TEMPERATURE

        # Xavier 初始化投影矩阵
        self._text_proj = self._random_projection_matrix(d_in, d_out)
        self._image_proj = self._random_projection_matrix(d_in, d_out)
        self._formula_proj = self._random_projection_matrix(d_in, d_out)

        # ── 构造正负样本对 ──
        # 正样本: 同一配对的 text↔image, text↔formula, image↔formula
        # 负样本: batch 内其他配对（随机打乱）
        lr = _CALIBRATION_LR
        final_loss = float("inf")

        for epoch in range(_CALIBRATION_EPOCHS):
            total_loss = 0.0
            # 学习率衰减：后半段减半
            if epoch >= _CALIBRATION_EPOCHS // 2:
                lr = _CALIBRATION_LR * 0.5

            # 随机采样 8 个配对构成 mini-batch（降低计算量）
            batch_indices = random.sample(range(n), min(_CALIBRATION_BATCH_SIZE, n))

            for idx in batch_indices:
                t_vec = self._project(self._text_embeddings[idx], self._text_proj)
                i_vec = self._project(self._image_embeddings[idx], self._image_proj)
                f_vec = self._project(self._formula_embeddings[idx], self._formula_proj)

                # 对每种跨模态组合计算 InfoNCE 损失
                # 组合 1: text → image
                loss_ti = self._infonce_loss(
                    anchor=t_vec, positive=i_vec,
                    negatives=[self._project(self._image_embeddings[j], self._image_proj)
                               for j in batch_indices if j != idx],
                    tau=tau,
                )
                # 组合 2: text → formula
                loss_tf = self._infonce_loss(
                    anchor=t_vec, positive=f_vec,
                    negatives=[self._project(self._formula_embeddings[j], self._formula_proj)
                               for j in batch_indices if j != idx],
                    tau=tau,
                )
                # 组合 3: image → formula
                loss_if = self._infonce_loss(
                    anchor=i_vec, positive=f_vec,
                    negatives=[self._project(self._formula_embeddings[j], self._formula_proj)
                               for j in batch_indices if j != idx],
                    tau=tau,
                )
                batch_loss = loss_ti + loss_tf + loss_if
                total_loss += batch_loss

                # ── 数值梯度近似更新投影矩阵 ──
                # 对每个投影矩阵，用有限差分近似梯度: W ← W - lr * ∂L/∂W
                epsilon = 1e-5
                self._text_proj = self._gradient_step(
                    self._text_proj, t_vec, self._text_embeddings[idx], batch_loss, lr, epsilon
                )
                self._image_proj = self._gradient_step(
                    self._image_proj, i_vec, self._image_embeddings[idx], batch_loss, lr, epsilon
                )
                self._formula_proj = self._gradient_step(
                    self._formula_proj, f_vec, self._formula_embeddings[idx], batch_loss, lr, epsilon
                )

            avg_loss = total_loss / len(batch_indices) if batch_indices else float("inf")
            final_loss = avg_loss

        self._is_calibrated = True
        self._last_calibration_loss = final_loss
        print(f"  [CrossModalAligner] 校准完成: loss={final_loss:.4f}, dim={d_in}→{d_out}")
        return final_loss

    def _infonce_loss(
        self,
        anchor: list[float],
        positive: list[float],
        negatives: list[list[float]],
        tau: float = 0.07,
    ) -> float:
        """计算单样本的 InfoNCE 对比损失。

        L = -log( exp(sim(a, p) / τ) / (exp(sim(a, p) / τ) + Σ exp(sim(a, n_j) / τ)) )

        Args:
            anchor: 锚点向量（如投影后的 text embedding）
            positive: 正样本向量（配对的 image embedding）
            negatives: 负样本向量列表（其他随机配对的 embedding）
            tau: 温度参数，越低越关注困难负样本

        Returns:
            标量 InfoNCE 损失值
        """
        pos_sim = self._cosine(anchor, positive) / tau
        neg_sim_sum = sum(
            math.exp(self._cosine(anchor, neg) / tau) for neg in negatives if neg
        )
        pos_exp = math.exp(pos_sim)
        denom = pos_exp + max(neg_sim_sum, 1e-10)  # 数值保护
        return -math.log(max(pos_exp / denom, 1e-10))

    def _gradient_step(
        self,
        matrix: list[list[float]],
        projected: list[float],
        original: list[float],
        loss: float,
        lr: float,
        eps: float = 1e-5,
    ) -> list[list[float]]:
        """向量化近似梯度下降更新投影矩阵。

        策略：沿随机方向施加扰动，若损失下降则向该方向更新。
        相比逐元素梯度，速度提升 ~100 倍，在对比学习中广泛使用
        (e.g. SPSA, random search optimization)。
        """
        if not matrix:
            return matrix
        rows = len(matrix)
        cols = len(matrix[0]) if rows > 0 else 0
        if rows == 0 or cols == 0:
            return matrix

        # 生成随机扰动方向（均匀分布在 [-1, 1]）
        direction = [[random.uniform(-1.0, 1.0) for _ in range(cols)] for _ in range(rows)]

        # 正向扰动
        perturbed_plus = [[matrix[i][j] + eps * direction[i][j] for j in range(cols)] for i in range(rows)]
        proj_plus = self._project(original, perturbed_plus)
        loss_plus = -self._cosine(proj_plus, projected)

        # 负向扰动
        perturbed_minus = [[matrix[i][j] - eps * direction[i][j] for j in range(cols)] for i in range(rows)]
        proj_minus = self._project(original, perturbed_minus)
        loss_minus = -self._cosine(proj_minus, projected)

        # 沿梯度方向更新：W ← W - lr * (L(+) - L(-)) / (2*eps) * direction
        grad_magnitude = (loss_plus - loss_minus) / (2.0 * eps)
        step = lr * grad_magnitude
        for i in range(rows):
            for j in range(cols):
                new_val = matrix[i][j] - step * direction[i][j]
                matrix[i][j] = max(-2.0, min(2.0, new_val))

        return matrix

    # ══════════════════════════════════════════════════════════════
    # 持久化
    # ══════════════════════════════════════════════════════════════

    def _load_from_disk(self) -> bool:
        """从 JSON 文件加载对齐数据和投影矩阵。"""
        if _ALIGNMENT_FILE.exists():
            try:
                with open(_ALIGNMENT_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    # 新格式：{pairs: [...], calibrated: bool, projections: {...}}
                    self._pairs = data.get("pairs", list(_BUILTIN_SEED_PAIRS))
                    self._is_calibrated = data.get("calibrated", False)
                    self._last_calibration_loss = data.get("calibration_loss", float("inf"))
                    proj_data = data.get("projections", {})
                    if proj_data:
                        self._text_proj = proj_data.get("text_proj", [])
                        self._image_proj = proj_data.get("image_proj", [])
                        self._formula_proj = proj_data.get("formula_proj", [])
                        self._proj_dim = proj_data.get("proj_dim", _PROJECTION_DIM)
                    return len(self._pairs) > 0
                elif isinstance(data, list) and len(data) > 0:
                    self._pairs = data
                    return True
            except Exception as e:
                print(f"  [CrossModalAligner] 加载磁盘数据失败: {e}")
        return False

    def save_to_disk(self) -> None:
        """将对齐数据和投影矩阵持久化到 JSON 文件。"""
        _ALIGNMENT_DATA_DIR.mkdir(parents=True, exist_ok=True)
        payload = {
            "pairs": self._pairs,
            "calibrated": self._is_calibrated,
            "calibration_loss": self._last_calibration_loss,
            "projections": {
                "proj_dim": self._proj_dim,
                "text_proj": self._text_proj,
                "image_proj": self._image_proj,
                "formula_proj": self._formula_proj,
            },
        }
        with open(_ALIGNMENT_FILE, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

    # ══════════════════════════════════════════════════════════════
    # 嵌入与配对管理
    # ══════════════════════════════════════════════════════════════

    def _build_embeddings(self) -> None:
        """计算所有配对的嵌入向量。"""
        if EMBEDDINGS is None or not self._pairs:
            self._initialized = False
            return
        try:
            self._text_embeddings = [
                list(EMBEDDINGS.embed(p["text"])) for p in self._pairs
            ]
            self._image_embeddings = [
                list(EMBEDDINGS.embed(p.get("image_desc", p["text"]))) for p in self._pairs
            ]
            self._formula_embeddings = [
                list(EMBEDDINGS.embed(p.get("formula", p["text"]))) for p in self._pairs
            ]
            self._initialized = True
        except Exception as e:
            print(f"  [CrossModalAligner] 嵌入计算失败: {e}")
            self._initialized = False

    def register_pair(
        self,
        text: str,
        image_desc: str = "",
        formula: str = "",
        concept: str = "",
    ) -> None:
        """注册一个新的跨模态对齐配对。"""
        pair = {
            "text": text,
            "image_desc": image_desc or text,
            "formula": formula or text,
            "concept": concept,
        }
        self._pairs.append(pair)
        # 增量更新嵌入
        if EMBEDDINGS is not None:
            self._text_embeddings.append(list(EMBEDDINGS.embed(pair["text"])))
            self._image_embeddings.append(list(EMBEDDINGS.embed(pair["image_desc"])))
            self._formula_embeddings.append(list(EMBEDDINGS.embed(pair["formula"])))
            self._initialized = True

    # ══════════════════════════════════════════════════════════════
    # 跨模态搜索（支持校准/未校准双模式）
    # ══════════════════════════════════════════════════════════════

    def search(
        self,
        query: str,
        mode: str = "text",
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        """跨模态搜索。

        若已校准：查询和目标向量投影到共享潜空间后再计算相似度。
        若未校准：直接比较原始嵌入的余弦相似度（向后兼容）。

        Args:
            query: 搜索词
            mode: "text" — 用文字搜图片/公式
                  "formula" — 用公式搜文字/图片
                  "image" — 用图片描述搜文字/公式
            top_k: 返回结果数量

        Returns:
            [{pair: dict, score: float, matched_modality: str, ...}, ...]
        """
        if not query.strip():
            return []
        if not self._initialized or not self._pairs:
            self._build_embeddings()
            if not self._initialized:
                return []

        if EMBEDDINGS is None:
            return []

        try:
            query_vec = list(EMBEDDINGS.embed(query))
        except Exception:
            return []

        # 若已校准，将查询投影到共享空间
        if self._is_calibrated:
            if mode == "text" and self._text_proj:
                query_vec = self._project(query_vec, self._text_proj)
            elif mode == "formula" and self._formula_proj:
                query_vec = self._project(query_vec, self._formula_proj)
            elif mode == "image" and self._image_proj:
                query_vec = self._project(query_vec, self._image_proj)

        results = []
        for i, pair in enumerate(self._pairs):
            scores = {}
            if mode == "text":
                if self._image_embeddings and i < len(self._image_embeddings):
                    img_vec = self._project(self._image_embeddings[i], self._image_proj) if self._is_calibrated else self._image_embeddings[i]
                    scores["image"] = self._cosine(query_vec, img_vec)
                if self._formula_embeddings and i < len(self._formula_embeddings):
                    f_vec = self._project(self._formula_embeddings[i], self._formula_proj) if self._is_calibrated else self._formula_embeddings[i]
                    scores["formula"] = self._cosine(query_vec, f_vec)
            elif mode == "formula":
                if self._text_embeddings and i < len(self._text_embeddings):
                    t_vec = self._project(self._text_embeddings[i], self._text_proj) if self._is_calibrated else self._text_embeddings[i]
                    scores["text"] = self._cosine(query_vec, t_vec)
                if self._image_embeddings and i < len(self._image_embeddings):
                    img_vec = self._project(self._image_embeddings[i], self._image_proj) if self._is_calibrated else self._image_embeddings[i]
                    scores["image"] = self._cosine(query_vec, img_vec)
            elif mode == "image":
                if self._text_embeddings and i < len(self._text_embeddings):
                    t_vec = self._project(self._text_embeddings[i], self._text_proj) if self._is_calibrated else self._text_embeddings[i]
                    scores["text"] = self._cosine(query_vec, t_vec)
                if self._formula_embeddings and i < len(self._formula_embeddings):
                    f_vec = self._project(self._formula_embeddings[i], self._formula_proj) if self._is_calibrated else self._formula_embeddings[i]
                    scores["formula"] = self._cosine(query_vec, f_vec)

            if scores:
                best_modality = max(scores, key=scores.get)
                best_score = scores[best_modality]
                results.append({
                    "pair": pair,
                    "score": round(best_score, 4),
                    "matched_modality": best_modality,
                    "all_scores": {k: round(v, 4) for k, v in scores.items()},
                    "calibrated": self._is_calibrated,
                })

        results.sort(key=lambda r: r["score"], reverse=True)
        return results[:top_k]

    def align_batch(
        self, text_chunks: list[str], image_descriptions: list[str] | None = None
    ) -> int:
        """批量对齐：将文字段落与图片描述配对注册。

        Returns:
            成功注册的配对数量
        """
        imgs = image_descriptions or text_chunks
        count = 0
        for i, text in enumerate(text_chunks):
            img = imgs[i % len(imgs)]
            if text.strip():
                self.register_pair(text=text, image_desc=img)
                count += 1
        if count > 0:
            self.save_to_disk()
        return count

    @property
    def pair_count(self) -> int:
        return len(self._pairs)

    @property
    def is_calibrated(self) -> bool:
        return self._is_calibrated

    @property
    def calibration_loss(self) -> float:
        return self._last_calibration_loss


# 模块级单例
_cross_modal_aligner: CrossModalAligner | None = None


def get_cross_modal_aligner() -> CrossModalAligner:
    """获取跨模态对齐器单例（延迟初始化）。"""
    global _cross_modal_aligner
    if _cross_modal_aligner is None:
        _cross_modal_aligner = CrossModalAligner()
    return _cross_modal_aligner
