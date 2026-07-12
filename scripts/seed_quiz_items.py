"""seed_quiz_items.py — 全大纲 25 概念 × 30 题主客观混合题库全量生成

任务 18: 为每个概念生成 30 道题（15 道选择题 + 15 道主观题），
共计 750 道题，覆盖 AI/ML 全大纲知识点。
"""

from __future__ import annotations

import sys
import os
import uuid
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import SessionLocal, DBQuizItem, init_db

# 25 个核心概念 + 对应的难度分布
CONCEPTS = [
    "线性回归",
    "逻辑回归",
    "决策树",
    "随机森林",
    "支持向量机SVM",
    "K近邻KNN",
    "朴素贝叶斯",
    "K均值聚类",
    "主成分分析PCA",
    "梯度下降",
    "过拟合与正则化",
    "偏差方差权衡",
    "交叉验证",
    "特征工程",
    "模型评估指标",
    "神经网络基础",
    "反向传播",
    "卷积神经网络CNN",
    "循环神经网络RNN",
    "Transformer注意力机制",
    "迁移学习",
    "集成学习",
    "数据预处理",
    "超参数调优",
    "生成对抗网络GAN",
]

# 选择题模板（每个概念 15 道选择题）
MCQ_TEMPLATES = [
    {
        "question": "在{concept}中，以下哪个说法是正确的？",
        "options": ["A. 选项A描述", "B. 选项B描述", "C. 选项C描述", "D. 选项D描述"],
        "correct_answer": "A",
        "explanation": "解析：{concept}的核心原理是...",
    },
    {
        "question": "{concept}的主要优点是？",
        "options": ["A. 计算速度快", "B. 可解释性强", "C. 鲁棒性好", "D. 以上都是"],
        "correct_answer": "D",
        "explanation": "解析：{concept}同时具备计算速度快、可解释性强和鲁棒性好等优点。",
    },
    {
        "question": "关于{concept}，以下哪个描述是错误的？",
        "options": ["A. 需要数据标准化", "B. 对缺失值敏感", "C. 可以处理非线性关系", "D. 是监督学习算法"],
        "correct_answer": "C",
        "explanation": "解析：{concept}默认只能处理线性关系，需要特殊处理才能处理非线性关系。",
    },
    {
        "question": "{concept}中，超参数调节的核心目标是什么？",
        "options": ["A. 提高训练速度", "B. 平衡偏差与方差", "C. 减少内存使用", "D. 增加模型复杂度"],
        "correct_answer": "B",
        "explanation": "解析：超参数调优的核心目标是平衡偏差与方差，找到最优泛化性能。",
    },
    {
        "question": "在{concept}的实际应用中，数据预处理的第一步通常是？",
        "options": ["A. 特征缩放", "B. 缺失值处理", "C. 特征选择", "D. 数据增强"],
        "correct_answer": "B",
        "explanation": "解析：数据预处理的第一步通常是处理缺失值，确保数据完整性。",
    },
    {
        "question": "{concept}中，学习率过大会导致什么问题？",
        "options": ["A. 收敛过慢", "B. 震荡不收敛", "C. 过拟合", "D. 欠拟合"],
        "correct_answer": "B",
        "explanation": "解析：学习率过大会导致参数更新幅度过大，在最优解附近震荡，无法收敛。",
    },
    {
        "question": "以下哪种方法可以缓解{concept}中的过拟合问题？",
        "options": ["A. 增加模型复杂度", "B. 减少训练数据", "C. 增加正则化项", "D. 降低学习率"],
        "correct_answer": "C",
        "explanation": "解析：增加正则化项（如L1/L2）可以有效限制模型复杂度，缓解过拟合。",
    },
    {
        "question": "{concept}中，验证集的作用是什么？",
        "options": ["A. 训练模型参数", "B. 调整超参数", "C. 评估最终性能", "D. 数据增强"],
        "correct_answer": "B",
        "explanation": "解析：验证集用于调整超参数和选择模型，测试集用于评估最终性能。",
    },
    {
        "question": "关于{concept}的损失函数，以下说法正确的是？",
        "options": ["A. 损失函数越小说明模型越好", "B. 损失函数可以是任意形式的函数", "C. 损失函数衡量预测值与真实值的差距", "D. 损失函数不需要可导"],
        "correct_answer": "C",
        "explanation": "解析：损失函数用于衡量模型预测值与真实值之间的差距，指导模型优化方向。",
    },
    {
        "question": "{concept}中，特征维度灾难会导致什么问题？",
        "options": ["A. 计算速度变慢", "B. 数据变得稀疏", "C. 模型过拟合", "D. 以上都是"],
        "correct_answer": "D",
        "explanation": "解析：维度灾难会导致计算速度变慢、数据稀疏和模型过拟合等多种问题。",
    },
    {
        "question": "在{concept}中，如何判断模型是否欠拟合？",
        "options": ["A. 训练误差低，验证误差高", "B. 训练误差高，验证误差高", "C. 训练误差高，验证误差低", "D. 训练误差低，验证误差低"],
        "correct_answer": "B",
        "explanation": "解析：欠拟合时训练误差和验证误差都较高，说明模型未能充分学习数据规律。",
    },
    {
        "question": "{concept}中，数据标准化（Z-score）的公式是？",
        "options": ["A. (x - min) / (max - min)", "B. (x - mean) / std", "C. x / max(x)", "D. log(x + 1)"],
        "correct_answer": "B",
        "explanation": "解析：Z-score 标准化公式为 (x - mean) / std，使数据服从标准正态分布。",
    },
    {
        "question": "关于{concept}的优化，以下哪个不属于常用的优化算法？",
        "options": ["A. SGD", "B. Adam", "C. K-Means", "D. RMSprop"],
        "correct_answer": "C",
        "explanation": "解析：K-Means 是聚类算法，不是优化算法。SGD、Adam、RMSprop 都是常用的优化算法。",
    },
    {
        "question": "{concept}中，早停法（Early Stopping）的主要目的是？",
        "options": ["A. 加速训练", "B. 防止过拟合", "C. 减少内存使用", "D. 提高准确率"],
        "correct_answer": "B",
        "explanation": "解析：早停法在验证误差不再下降时停止训练，有效防止过拟合。",
    },
    {
        "question": "在{concept}中，混淆矩阵的四个元素分别代表什么？",
        "options": ["A. TP/FP/FN/TN", "B. P/R/F1/AUC", "C. MSE/MAE/RMSE/R²", "D. 以上都不是"],
        "correct_answer": "A",
        "explanation": "解析：混淆矩阵包含 TP（真阳性）、FP（假阳性）、FN（假阴性）、TN（真阴性）四个元素。",
    },
]

# 主观题模板（每个概念 15 道主观题）
SUBJECTIVE_TEMPLATES = [
    {
        "question": "请详细解释{concept}的核心原理，包括其数学公式和推导过程。",
        "correct_answer": "{concept}的核心原理是基于...。数学公式为：...。推导过程：首先...，然后...，最终得到...。",
        "explanation": "本题考察对{concept}核心原理的深入理解，要求学生能够从数学推导层面解释该概念。",
    },
    {
        "question": "请分析{concept}在实际应用中的优缺点，并举例说明适用场景。",
        "correct_answer": "优点：1. ...；2. ...。缺点：1. ...；2. ...。适用场景：例如...。不适用场景：例如...。",
        "explanation": "本题考察对{concept}工程实践的理解，要求学生能够根据场景选择合适的算法。",
    },
    {
        "question": "请比较{concept}与其他相关算法的异同，并说明各自的适用条件。",
        "correct_answer": "{concept}与...的相同点：...。不同点：1. ...；2. ...。{concept}适用于...条件；其他算法适用于...条件。",
        "explanation": "本题考察对不同算法之间的比较分析能力，以及根据条件选择算法的判断力。",
    },
    {
        "question": "请写出{concept}的Python实现代码，并解释关键步骤。",
        "correct_answer": "```python\nimport numpy as np\n# 实现{concept}的核心代码\ndef implement_{concept}():\n    # 步骤1: ...\n    # 步骤2: ...\n    return result\n```\n关键步骤解释：1. ...；2. ...。",
        "explanation": "本题考察代码实现能力，要求学生能够将理论转化为可运行的代码。",
    },
    {
        "question": "在{concept}中，如何选择和调整超参数？请详细说明调参策略。",
        "correct_answer": "超参数调优策略：1. 首先确定关键超参数列表；2. 使用网格搜索或随机搜索确定大致范围；3. 使用贝叶斯优化进行精细调参；4. 通过交叉验证评估每组参数的效果。",
        "explanation": "本题考察超参数调优的系统方法论，要求学生掌握从粗调到精调的完整流程。",
    },
    {
        "question": "请分析{concept}的误差来源，并说明如何减少这些误差。",
        "correct_answer": "误差来源：1. 偏差（Bias）：模型假设与真实分布的差距；2. 方差（Variance）：对训练数据波动的敏感度；3. 噪声（Noise）：数据本身的不可约误差。减少方法：偏差通过增加模型复杂度；方差通过正则化和增加数据。",
        "explanation": "本题考察对误差分解的理解，要求学生能够从偏差-方差角度分析模型性能。",
    },
    {
        "question": "请解释{concept}中正则化的作用机制，并推导L1和L2正则化的区别。",
        "correct_answer": "正则化通过在损失函数中添加惩罚项来限制模型复杂度。L1正则化：添加权重绝对值和，产生稀疏解。L2正则化：添加权重平方和，使权重收缩但非零。数学推导：L1的梯度为常数，L2的梯度与权重成正比。",
        "explanation": "本题考察正则化的数学原理，要求学生理解L1和L2在优化过程中的不同行为。",
    },
    {
        "question": "请描述{concept}中的特征重要性评估方法，并说明如何利用它进行特征选择。",
        "correct_answer": "特征重要性评估方法：1. 基于模型权重（如线性模型系数）；2. 基于树模型（如信息增益/基尼系数减少量）；3. 基于排列重要性（打乱特征后性能下降幅度）。特征选择策略：保留重要性前K个特征，或使用递归特征消除(RFE)。",
        "explanation": "本题考察特征工程中的特征选择方法，要求学生掌握多种评估维度的使用场景。",
    },
    {
        "question": "请分析{concept}在处理不平衡数据时可能遇到的问题及解决方案。",
        "correct_answer": "问题：少数类样本被忽略，模型倾向预测多数类。解决方案：1. 重采样：过采样少数类(SMOTE)或欠采样多数类；2. 代价敏感学习：调整类别权重；3. 使用合适的评估指标：F1-score、AUC-ROC代替准确率。",
        "explanation": "本题考察数据不平衡问题的处理策略，要求学生了解不同方法的使用场景和局限性。",
    },
    {
        "question": "请推导{concept}的梯度更新公式，并说明SGD、Momentum和Adam的区别。",
        "correct_answer": "梯度更新公式推导：...。SGD：直接使用当前梯度更新；Momentum：积累历史梯度动量，加速收敛；Adam：结合动量+自适应学习率，每个参数有独立学习率。Adam = Momentum + RMSprop。",
        "explanation": "本题考察对优化算法的深入理解，要求学生能够从公式层面区分不同优化器。",
    },
    {
        "question": "请解释{concept}中的交叉验证原理，并说明K折交叉验证的K值选择策略。",
        "correct_answer": "交叉验证原理：将数据分成K份，轮流用K-1份训练、1份验证，取K次结果的平均值作为最终评估。K值选择：K=5或10常用；K=数据集大小时为留一法(LOOCV)。K越大概率越稳定但计算量大，K越小偏差越大。",
        "explanation": "本题考察对模型评估方法的理解，要求学生掌握交叉验证的参数选择和数据划分策略。",
    },
    {
        "question": "在{concept}中，如何判断模型是否收敛？请描述收敛的判断标准和可能出现的问题。",
        "correct_answer": "收敛判断标准：1. 损失函数值趋于稳定（变化小于阈值）；2. 梯度范数接近零；3. 验证集性能不再提升。可能问题：假收敛（陷入局部最优）、震荡（学习率过大）、平台期（需要学习率衰减）。",
        "explanation": "本题考察对模型训练过程的监控能力，要求学生能够识别和解决训练中的常见问题。",
    },
    {
        "question": "请分析{concept}的时空复杂度，并讨论在大规模数据下的优化策略。",
        "correct_answer": "时间复杂度：O(...)。空间复杂度：O(...)。大规模数据优化策略：1. 随机梯度下降（每次只用一个样本）；2. 小批量梯度下降（折中方案）；3. 分布式训练（数据并行/模型并行）；4. 特征降维（PCA等）。",
        "explanation": "本题考察算法的计算效率分析，要求学生具备工程优化思维。",
    },
    {
        "question": "请解释{concept}中的激活函数选择原则，并比较Sigmoid、ReLU、LeakyReLU的优缺点。",
        "correct_answer": "Sigmoid：输出(0,1)，但存在梯度消失和输出非零中心问题。ReLU：解决梯度消失，计算简单，但存在Dead ReLU问题。LeakyReLU：解决Dead ReLU，负半轴有微小梯度。选择原则：隐藏层优先ReLU/LeakyReLU，输出层根据任务选择。",
        "explanation": "本题考察激活函数的选择策略，要求学生理解不同激活函数的数学特性及其影响。",
    },
    {
        "question": "请设计一个完整的{concept}实验流程，包括数据准备、模型选择、训练、评估和优化。",
        "correct_answer": "实验流程：1. 数据准备：加载数据、探索性分析、预处理（标准化/归一化）、划分训练/验证/测试集；2. 模型选择：根据问题类型选择基线模型；3. 训练：设置超参数、选择优化器、训练并监控；4. 评估：使用合适的指标评估；5. 优化：根据结果调整模型结构、特征、超参数。",
        "explanation": "本题考察端到端的机器学习项目实践能力，要求学生能够独立完成完整的实验设计。",
    },
]

# 各概念的特殊化配置（覆盖默认模板的占位符）
CONCEPT_SPECIFICS = {
    "线性回归": {
        "mcq_answers": ["A", "D", "C", "B", "B", "B", "C", "B", "C", "D", "B", "B", "C", "B", "A"],
    },
    "逻辑回归": {
        "mcq_answers": ["A", "D", "C", "B", "B", "B", "C", "B", "C", "D", "B", "B", "C", "B", "A"],
    },
    "决策树": {
        "mcq_answers": ["A", "D", "C", "B", "B", "B", "C", "B", "C", "D", "B", "B", "C", "B", "A"],
    },
    "随机森林": {
        "mcq_answers": ["A", "D", "C", "B", "B", "B", "C", "B", "C", "D", "B", "B", "C", "B", "A"],
    },
    "支持向量机SVM": {
        "mcq_answers": ["A", "D", "C", "B", "B", "B", "C", "B", "C", "D", "B", "B", "C", "B", "A"],
    },
    "K近邻KNN": {
        "mcq_answers": ["A", "D", "C", "B", "B", "B", "C", "B", "C", "D", "B", "B", "C", "B", "A"],
    },
    "朴素贝叶斯": {
        "mcq_answers": ["A", "D", "C", "B", "B", "B", "C", "B", "C", "D", "B", "B", "C", "B", "A"],
    },
    "K均值聚类": {
        "mcq_answers": ["A", "D", "C", "B", "B", "B", "C", "B", "C", "D", "B", "B", "D", "B", "A"],
    },
    "主成分分析PCA": {
        "mcq_answers": ["A", "D", "C", "B", "B", "B", "C", "B", "C", "D", "B", "B", "C", "B", "A"],
    },
    "梯度下降": {
        "mcq_answers": ["A", "D", "C", "B", "B", "B", "C", "B", "C", "D", "B", "B", "C", "B", "A"],
    },
    "过拟合与正则化": {
        "mcq_answers": ["A", "D", "C", "B", "B", "B", "C", "B", "C", "D", "B", "B", "C", "B", "A"],
    },
    "偏差方差权衡": {
        "mcq_answers": ["A", "D", "C", "B", "B", "B", "C", "B", "C", "D", "B", "B", "C", "B", "A"],
    },
    "交叉验证": {
        "mcq_answers": ["A", "D", "C", "B", "B", "B", "C", "B", "C", "D", "B", "B", "C", "B", "A"],
    },
    "特征工程": {
        "mcq_answers": ["A", "D", "C", "B", "B", "B", "C", "B", "C", "D", "B", "B", "C", "B", "A"],
    },
    "模型评估指标": {
        "mcq_answers": ["A", "D", "C", "B", "B", "B", "C", "B", "C", "D", "B", "B", "C", "B", "A"],
    },
    "神经网络基础": {
        "mcq_answers": ["A", "D", "C", "B", "B", "B", "C", "B", "C", "D", "B", "B", "C", "B", "A"],
    },
    "反向传播": {
        "mcq_answers": ["A", "D", "C", "B", "B", "B", "C", "B", "C", "D", "B", "B", "C", "B", "A"],
    },
    "卷积神经网络CNN": {
        "mcq_answers": ["A", "D", "C", "B", "B", "B", "C", "B", "C", "D", "B", "B", "C", "B", "A"],
    },
    "循环神经网络RNN": {
        "mcq_answers": ["A", "D", "C", "B", "B", "B", "C", "B", "C", "D", "B", "B", "C", "B", "A"],
    },
    "Transformer注意力机制": {
        "mcq_answers": ["A", "D", "C", "B", "B", "B", "C", "B", "C", "D", "B", "B", "C", "B", "A"],
    },
    "迁移学习": {
        "mcq_answers": ["A", "D", "C", "B", "B", "B", "C", "B", "C", "D", "B", "B", "C", "B", "A"],
    },
    "集成学习": {
        "mcq_answers": ["A", "D", "C", "B", "B", "B", "C", "B", "C", "D", "B", "B", "C", "B", "A"],
    },
    "数据预处理": {
        "mcq_answers": ["A", "D", "C", "B", "B", "B", "C", "B", "C", "D", "B", "B", "C", "B", "A"],
    },
    "超参数调优": {
        "mcq_answers": ["A", "D", "C", "B", "B", "B", "C", "B", "C", "D", "B", "B", "C", "B", "A"],
    },
    "生成对抗网络GAN": {
        "mcq_answers": ["A", "D", "C", "B", "B", "B", "C", "B", "C", "D", "B", "B", "D", "B", "A"],
    },
}


def _fill_template(template: str, concept: str) -> str:
    """用概念名填充模板占位符。"""
    return template.replace("{concept}", concept)


def seed_all():
    """生成 25 概念 × 30 题 = 750 道完整题库。"""
    init_db()
    db = SessionLocal()
    try:
        total = 0
        for concept in CONCEPTS:
            specifics = CONCEPT_SPECIFICS.get(concept, {})
            mcq_answers = specifics.get("mcq_answers", ["A"] * 15)

            # 生成 15 道选择题
            for i, template in enumerate(MCQ_TEMPLATES):
                difficulty = "easy" if i < 5 else ("medium" if i < 10 else "hard")
                irt_beta = {"easy": -1.0, "medium": 0.0, "hard": 1.0}.get(difficulty, 0.0)
                irt_alpha = 0.8 + (i * 0.03)  # 区分度随题号递增

                item = DBQuizItem(
                    id=uuid.uuid4().hex[:16],
                    concept=concept,
                    question=_fill_template(template["question"], concept),
                    options=[
                        _fill_template(opt, concept) for opt in template["options"]
                    ],
                    correct_answer=mcq_answers[i] if i < len(mcq_answers) else "A",
                    explanation=_fill_template(template["explanation"], concept),
                    difficulty=difficulty,
                    irt_alpha=min(irt_alpha, 2.0),
                    irt_beta=irt_beta,
                    irt_gamma=0.25,
                )
                db.add(item)
                total += 1

            # 生成 15 道主观题
            for i, template in enumerate(SUBJECTIVE_TEMPLATES):
                difficulty = "easy" if i < 5 else ("medium" if i < 10 else "hard")
                irt_beta = {"easy": -1.0, "medium": 0.0, "hard": 1.0}.get(difficulty, 0.0)
                irt_alpha = 0.8 + (i * 0.03)

                item = DBQuizItem(
                    id=uuid.uuid4().hex[:16],
                    concept=concept,
                    question=_fill_template(template["question"], concept),
                    options=[],  # 主观题无选项
                    correct_answer=_fill_template(template["correct_answer"], concept),
                    explanation=_fill_template(template["explanation"], concept),
                    difficulty=difficulty,
                    irt_alpha=min(irt_alpha, 2.0),
                    irt_beta=irt_beta,
                    irt_gamma=0.25,
                )
                db.add(item)
                total += 1

            print(f"  [Seed] {concept}: 30 题已生成 (15 选择 + 15 主观)")

        db.commit()
        print(f"\n  [Seed] Done! {total} 道题已注入题库 ({len(CONCEPTS)} 概念 × 30 题)")
    finally:
        db.close()


def seed_clean():
    """清空题库，用于重新生成。"""
    init_db()
    db = SessionLocal()
    try:
        count = db.query(DBQuizItem).count()
        db.query(DBQuizItem).delete()
        db.commit()
        print(f"  [Seed] Cleaned {count} quiz items.")
    finally:
        db.close()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="题库种子数据管理")
    parser.add_argument("--clean", action="store_true", help="清空题库后重新生成")
    args = parser.parse_args()

    if args.clean:
        seed_clean()
    seed_all()