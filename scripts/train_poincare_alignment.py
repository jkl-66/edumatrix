import os
import sys
import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim

# Add project root to sys.path to allow imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from embedding_models import EMBEDDINGS
from bkt_engine import CONCEPT_TO_INDEX, get_dag_depth

def train_projection():
    print("[Poincaré Alignment] Initializing training script...")
    
    # 1. 提取课程核心概念及其 384 维嵌入表示
    concepts = list(CONCEPT_TO_INDEX.keys())
    concept_embeddings = []
    
    for concept in concepts:
        vec = EMBEDDINGS.embed(concept)
        if not vec or len(vec) != 384:
            # 兜底：若没有返回有效的 384 维向量，使用确定性伪随机数生成合成向量
            np.random.seed(hash(concept) % 12345)
            vec = np.random.normal(0, 0.1, 384).tolist()
        concept_embeddings.append(vec)
        
    X = torch.tensor(concept_embeddings, dtype=torch.float32)  # (M, 384)
    M = len(concepts)
    
    # 2. 从依赖图中提取正/负相关对
    from bkt_engine import get_dag_depth
    # 获取 DAG
    try:
        from profile_api import KNOWLEDGE_DAG
    except Exception:
        from agent_swarm import DEFAULT_KNOWLEDGE_DAG as KNOWLEDGE_DAG
        
    # 正样本对：在依赖图中有直接前置或后继关系的概念
    pos_pairs = []
    for concept, idx in CONCEPT_TO_INDEX.items():
        prereqs = KNOWLEDGE_DAG.get(concept, [])
        for p in prereqs:
            if p in CONCEPT_TO_INDEX:
                pos_pairs.append((idx, CONCEPT_TO_INDEX[p]))
                
    # 负样本对：随机抽取没有直接关联的概念
    neg_pairs = []
    for i in range(M):
        for j in range(i + 1, M):
            if (i, j) not in pos_pairs and (j, i) not in pos_pairs:
                neg_pairs.append((i, j))
                
    # 限制负样本数量与正样本大体相当
    np.random.seed(42)
    if len(neg_pairs) > len(pos_pairs) * 2:
        selected_idx = np.random.choice(len(neg_pairs), len(pos_pairs) * 2, replace=False)
        neg_pairs = [neg_pairs[idx] for idx in selected_idx]
        
    print(f"[Poincaré Alignment] Loaded {M} concepts. Pos pairs: {len(pos_pairs)}, Neg pairs: {len(neg_pairs)}")
    
    # 3. 声明可训练的对齐矩阵 W，使用近恒等阵初始化
    W = nn.Parameter(torch.eye(384) + torch.randn(384, 384) * 0.01)
    optimizer = optim.Adam([W], lr=0.005)
    
    # 庞加莱投影与距离函数 (PyTorch 版本)
    def project_to_ball_torch(vecs, max_norm=0.82):
        norms = torch.norm(vecs, p=2, dim=1, keepdim=True)
        norms = torch.clamp(norms, min=1e-9)
        direction = vecs / norms
        # 利用 tanh 模长限制
        hyperbolic_norm = max_norm * torch.tanh(norms)
        return direction * hyperbolic_norm
        
    def poincare_distance_torch(u, v, eps=1e-5):
        norm_u_sq = torch.sum(u * u, dim=1)
        norm_v_sq = torch.sum(v * v, dim=1)
        
        diff_sq = torch.sum((u - v) * (u - v), dim=1)
        numerator = 2.0 * diff_sq
        denominator = (1.0 - norm_u_sq) * (1.0 - norm_v_sq)
        denominator = torch.clamp(denominator, min=eps)
        
        delta = 1.0 + numerator / denominator
        delta = torch.clamp(delta, min=1.0)
        # acosh(x) = ln(x + sqrt(x^2 - 1))
        return torch.log(delta + torch.sqrt(torch.clamp(delta*delta - 1.0, min=eps)))

    # 4. 对比优化循环
    epochs = 60
    margin = 2.0
    for epoch in range(epochs):
        optimizer.zero_grad()
        
        # 投影到流形并压缩到庞加莱球
        H = torch.matmul(X, W)
        Z = project_to_ball_torch(H)
        
        # 正样本损失：拉近关联点距离
        pos_u = Z[[p[0] for p in pos_pairs]]
        pos_v = Z[[p[1] for p in pos_pairs]]
        d_pos = poincare_distance_torch(pos_u, pos_v)
        loss_pos = torch.mean(d_pos ** 2)
        
        # 负样本损失：推远不关联点距离至 margin 以上
        neg_u = Z[[n[0] for n in neg_pairs]]
        neg_v = Z[[n[1] for n in neg_pairs]]
        d_neg = poincare_distance_torch(neg_u, neg_v)
        loss_neg = torch.mean(torch.clamp(margin - d_neg, min=0.0) ** 2)
        
        loss = loss_pos + loss_neg
        loss.backward()
        optimizer.step()
        
        if (epoch + 1) % 10 == 0:
            print(f"Epoch {epoch+1:02d}/{epochs:02d} | Loss: {loss.item():.4f} (Pos: {loss_pos.item():.4f}, Neg: {loss_neg.item():.4f})")
            
    # 5. 保存训练好的 numpy 权重文件
    W_np = W.detach().cpu().numpy()
    # 规范化算子
    W_np /= np.linalg.norm(W_np, ord=2)
    
    out_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "poincare_projection.npy")
    np.save(out_path, W_np)
    print(f"[Poincaré Alignment] Training completed. Projection matrix saved to {out_path}")

if __name__ == "__main__":
    train_projection()
