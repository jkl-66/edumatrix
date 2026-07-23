import sqlite3
import json
import os
import sys

# Reuse the application's environment-aware database selection. This keeps
# pytest on edumatrix_test.db while standalone deployment uses edumatrix.db.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.database import DB_PATH

# 预置种子测验题目，保证答辩演示和单元测试的 100% 稳定性与脱网运行能力
SEED_QUESTIONS = [
    # 1. 最大池化 (Max Pooling)
    {
        "id": "item_pool_max_easy",
        "concept": "最大池化",
        "question": "最大池化（Max Pooling）在卷积神经网络（CNN）中的基本作用是什么？",
        "options": [
            "A. 保留局部区域的最大值以提取显著纹理特征并进行空间降维",
            "B. 计算滑动窗口内的均值以平滑特征图并消除高频噪声",
            "C. 增加特征图的分辨率以获取更多细节",
            "D. 提供全连接层的映射参数以完成最终分类"
        ],
        "correct_answer": "A",
        "explanation": "最大池化主要在滑动窗口内提取最大数值，从而保留最显著特征并减少计算量。",
        "difficulty": "easy",
        "irt_alpha": 1.1, "irt_beta": -1.0, "irt_gamma": 0.2
    },
    {
        "id": "item_pool_max_med",
        "concept": "最大池化",
        "question": "在一个 2x2 滑动窗口、步长为 2 的最大池化层中，若输入局部的二维数组为 [[1, 3], [2, 4]]，则其计算输出值是多少？",
        "options": [
            "A. 1",
            "B. 3",
            "C. 4",
            "D. 2.5"
        ],
        "correct_answer": "C",
        "explanation": "2x2 窗口内的元素为 1, 2, 3, 4，其中的最大值为 4，所以池化后的输出为 4。",
        "difficulty": "medium",
        "irt_alpha": 1.3, "irt_beta": 0.0, "irt_gamma": 0.15
    },
    {
        "id": "item_pool_max_hard",
        "concept": "最大池化",
        "question": "为什么说最大池化（Max Pooling）能够为卷积神经网络提供某种程度上的“平移不变性”？",
        "options": [
            "A. 它强行将特征图大小减半，从而减少了平移的自由度",
            "B. 只要输入的微小位移没有让局部最大值移出滑动窗口，输出的池化值就不会改变",
            "C. 它完全丢弃了特征图的全部通道结构，只保留数值",
            "D. 它通过反向传播算法中的链式法则抵消了前向传播的平移变化"
        ],
        "correct_answer": "B",
        "explanation": "由于局部窗口只关心最大值，因此即使输入特征图发生了微小的平移，只要最大值仍在窗口内，输出就不会改变，这就是平移不变性。",
        "difficulty": "hard",
        "irt_alpha": 1.5, "irt_beta": 1.0, "irt_gamma": 0.1
    },
    
    # 2. 平均池化 (Average Pooling)
    {
        "id": "item_pool_avg_easy",
        "concept": "平均池化",
        "question": "平均池化（Average Pooling）与最大池化（Max Pooling）在计算机制上的主要区别是什么？",
        "options": [
            "A. 平均池化不具有降采样和减小特征图空间尺寸的作用",
            "B. 平均池化计算滑动窗口内所有元素的均值，对特征图起到平滑和保留背景的作用",
            "C. 平均池化通常拥有需要通过反向传播来更新的学习参数",
            "D. 平均池化计算出的数值一定是局部窗口内的最大值"
        ],
        "correct_answer": "B",
        "explanation": "平均池化计算滑动窗口内所有值的算术平均值，因此起到平滑信号、保留背景特征的作用。",
        "difficulty": "easy",
        "irt_alpha": 1.0, "irt_beta": -1.0, "irt_gamma": 0.22
    },
    {
        "id": "item_pool_avg_med",
        "concept": "平均池化",
        "question": "如果输入特征图的一个 2x2 局部区域数值为 [[1, 2], [3, 4]]，那么进行平均池化计算的输出值是多少？",
        "options": [
            "A. 4",
            "B. 2.5",
            "C. 3",
            "D. 2"
        ],
        "correct_answer": "B",
        "explanation": "(1 + 2 + 3 + 4) / 4 = 10 / 4 = 2.5。",
        "difficulty": "medium",
        "irt_alpha": 1.2, "irt_beta": 0.0, "irt_gamma": 0.18
    },
    {
        "id": "item_pool_avg_hard",
        "concept": "平均池化",
        "question": "在现代卷积神经网络结构（如 ResNet）的输出层前，为何常常用“全局平均池化 (GAP)”替代传统的多层全连接层？",
        "options": [
            "A. 因为全局平均池化能够引入非线性激活，而全连接层无法做到",
            "B. 因为全局平均池化没有需要学习的权重参数，能极大减少整体参数量防止过拟合，且保持通道空间相关性",
            "C. 因为全局平均池化可以让特征图的分辨率进一步扩大，提高分类精度",
            "D. 因为全连接层在反向传播时无法传导关于通道梯度的误差信号"
        ],
        "correct_answer": "B",
        "explanation": "全局平均池化（Global Average Pooling）将整个特征图的每个通道求平均，不仅极大压缩了参数量以防止过拟合，而且对平移提供了极强的鲁棒性。",
        "difficulty": "hard",
        "irt_alpha": 1.6, "irt_beta": 1.0, "irt_gamma": 0.08
    },

    # 3. Sigmoid函数
    {
        "id": "item_sigmoid_easy",
        "concept": "Sigmoid函数",
        "question": "常用于二分类模型输出层的 Sigmoid 激活函数的输出范围是多少？",
        "options": [
            "A. [-1, 1]",
            "B. [0, +∞)",
            "C. (0, 1)",
            "D. (-∞, +∞)"
        ],
        "correct_answer": "C",
        "explanation": "Sigmoid 激活函数的输出范围是开区间 (0, 1)。",
        "difficulty": "easy",
        "irt_alpha": 1.1, "irt_beta": -1.0, "irt_gamma": 0.25
    },
    {
        "id": "item_sigmoid_med",
        "concept": "Sigmoid函数",
        "question": "若定义 y = sigmoid(x)，则 Sigmoid 函数关于输入 x 的一阶导数可表示为何种简洁形式？",
        "options": [
            "A. y^2",
            "B. y * (1 - y)",
            "C. 1 - y",
            "D. y * (y - 1)"
        ],
        "correct_answer": "B",
        "explanation": "Sigmoid 的导数是 y'(x) = y(x) * (1 - y(x))，这一优良性质使得反向传播时导数非常好计算。",
        "difficulty": "medium",
        "irt_alpha": 1.3, "irt_beta": 0.0, "irt_gamma": 0.12
    },
    {
        "id": "item_sigmoid_hard",
        "concept": "Sigmoid函数",
        "question": "为什么在深度神经网络的隐藏层中，普遍倾向于使用 ReLU 激活函数而非 Sigmoid 函数？",
        "options": [
            "A. Sigmoid 函数的输出只能是整数，限制了梯度精度",
            "B. 当输入自变量绝对值较大时，Sigmoid 函数输出极度饱和且导数接近 0，会引发反向传播中的梯度消失问题",
            "C. Sigmoid 函数不支持多元分类任务的分数归一化",
            "D. Sigmoid 函数的求导公式非常复杂，在 GPU 上无法进行快速矩阵乘法"
        ],
        "correct_answer": "B",
        "explanation": "深层神经网络中，如果隐藏层使用 Sigmoid 激活函数，在反向传播时，由于 Sigmoid 的最大导数仅为 0.25，层层相乘后会导致梯度呈指数衰减，即梯度消失（Gradient Vanishing）问题。",
        "difficulty": "hard",
        "irt_alpha": 1.5, "irt_beta": 1.0, "irt_gamma": 0.1
    },

    # 4. 梯度下降
    {
        "id": "item_gd_easy",
        "concept": "梯度下降",
        "question": "在梯度下降（Gradient Descent）算法中，更新模型参数的移动方向应当是损失函数的什么方向？",
        "options": [
            "A. 梯度的朝向方向",
            "B. 梯度的反方向（即负梯度方向）",
            "C. 沿着损失函数切线平行的方向",
            "D. 保持正交于梯度的法线方向"
        ],
        "correct_answer": "B",
        "explanation": "梯度指向函数值上升最快的方向，为了最小化损失，我们应当沿着梯度的反方向更新参数。",
        "difficulty": "easy",
        "irt_alpha": 1.0, "irt_beta": -1.0, "irt_gamma": 0.2
    },
    {
        "id": "item_gd_med",
        "concept": "梯度下降",
        "question": "在参数更新计算 theta = theta - lr * grad 中，学习率（learning rate, lr）的主要职责是什么？",
        "options": [
            "A. 决定参数每一次沿着负梯度方向更新的步长大小",
            "B. 调整梯度向量的正负号以改变更新的方向",
            "C. 它是用于表示神经网络当前权重的初始权重向量",
            "D. 它决定了目标损失函数是否具有凸包性质"
        ],
        "correct_answer": "A",
        "explanation": "学习率是步长乘数，决定了每次迭代时参数沿着梯度反方向移动的距离。",
        "difficulty": "medium",
        "irt_alpha": 1.2, "irt_beta": 0.0, "irt_gamma": 0.15
    },
    {
        "id": "item_gd_hard",
        "concept": "梯度下降",
        "question": "在梯度下降更新过程中，若设置了过大的学习率（Learning Rate），最容易产生的优化异常现象是什么？",
        "options": [
            "A. 优化算法卡在极小值点无法移动",
            "B. 参数更新跨度过大，在山谷两侧来回剧烈震荡，甚至数值溢出导致发散不收敛",
            "C. 模型由于学习过快而立刻产生严重的过拟合问题",
            "D. 系统会强制将梯度降级为一阶倒数并进入死锁状态"
        ],
        "correct_answer": "B",
        "explanation": "过大的学习率会使得更新步长跨过损失函数的极小值点，并在两边来回震荡甚至数值溢出发散。",
        "difficulty": "hard",
        "irt_alpha": 1.4, "irt_beta": 1.0, "irt_gamma": 0.1
    }
]

def bootstrap():
    print(f"Connecting to database: {DB_PATH}")
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # 创建物理题库表（防止本地启动异常）
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS quiz_items (
            id VARCHAR(64) PRIMARY KEY,
            concept VARCHAR(128),
            question TEXT NOT NULL,
            options TEXT DEFAULT '[]',
            correct_answer TEXT DEFAULT '',
            explanation TEXT DEFAULT '',
            difficulty VARCHAR(32) DEFAULT 'medium',
            irt_alpha FLOAT DEFAULT 1.0,
            irt_beta FLOAT DEFAULT 0.0,
            irt_gamma FLOAT DEFAULT 0.25,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()

    # 清除旧的种子预置题
    cursor.execute("DELETE FROM quiz_items WHERE id LIKE 'item_%'")
    conn.commit()

    inserted = 0
    for q in SEED_QUESTIONS:
        options_json = json.dumps(q["options"], ensure_ascii=False)
        try:
            cursor.execute("""
                INSERT INTO quiz_items (id, concept, question, options, correct_answer, explanation, difficulty, irt_alpha, irt_beta, irt_gamma)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (q["id"], q["concept"], q["question"], options_json, q["correct_answer"], q["explanation"], q["difficulty"], q["irt_alpha"], q["irt_beta"], q["irt_gamma"]))
            inserted += 1
        except Exception as e:
            print(f"Error inserting {q['id']}: {e}")

    conn.commit()
    conn.close()
    print(f"Successfully seeded {inserted} pre-calibrated quiz items into the item bank!")

if __name__ == "__main__":
    bootstrap()
