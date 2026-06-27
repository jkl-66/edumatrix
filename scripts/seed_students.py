"""seed_students.py — 自动生成 12 名差异化虚拟学生（增强版）

每位学生有独特的专业背景、薄弱知识点、学习目标和互动偏好。
现增强为 3 轮对话历史，让画像引擎有足够的上下文进行深度分析。
"""

from __future__ import annotations

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import SessionLocal, DBUser, DBStudentProfile, init_db
from app.auth import get_password_hash
from app.crud import save_student_profile
from models import StudentProfile

STUDENTS = [
    {
        "username": "stu-cs-001",
        "display_name": "张明",
        "password": "123456",
        "major": "计算机科学与技术",
        "conversations": [
            "我是计算机专业大二学生，正在学机器学习。逻辑回归和SVM的概念总混淆，accuracy很高但recall低的时候不知道怎么判断模型好坏。希望用图对比和具体代码例子一步步讲解。",
            "你上次讲了逻辑回归和SVM的区别，对比表很有帮助。但我现在做练习题的时候，遇到一个二分类问题，正样本只有10%的情况下，用accuracy评价直接就90%了，但recall很低。这种情况下应该用什么评价指标好？",
            "谢谢！我试了用PR曲线和F1-score，果然能看出模型的问题。另外还有一个问题：SVM的核函数怎么选？我试了RBF核和多项式核，结果差不多，不知道什么时候该用哪个。",
        ],
    },
    {
        "username": "stu-cs-002",
        "display_name": "李华",
        "password": "123456",
        "major": "软件工程",
        "conversations": [
            "我线性回归能看懂公式，但一到项目就不会做数据预处理，只会照着答案改代码。需要代码实操和分步提示，从特征缩放开始教。",
            "我按你说的试了StandardScaler标准化，确实收敛快了很多。但还是不太清楚什么时候该用标准化，什么时候该用归一化。MinMaxScaler和StandardScaler的区别能再讲讲吗？",
            "懂了！我再问一个：数据里有缺失值，我直接删掉了有缺失的行，但数据一下少了一半。老师说可以用均值填充或插值，这两种方法分别在什么场景下用比较好？",
        ],
    },
    {
        "username": "stu-math-001",
        "display_name": "王芳",
        "password": "123456",
        "major": "数学与应用数学",
        "conversations": [
            "数学专业跨考人工智能。过拟合和正则化分不清，训练集分数高就以为模型好。题干长的时候会漏掉验证集条件，希望有反例对比和分步拆解。",
            "你上次讲了L1和L2正则化的区别，L1会让参数变稀疏这点我理解了。但我在用Ridge回归的时候，alpha值不知道怎么选，试了几个值效果差很多，有没有系统的方法？",
            "交叉验证我试了，5折CV选的alpha确实比瞎猜的好。还有一个问题：我做的房价预测任务，训练集R²有0.92，测试集只有0.67，这应该是过拟合吧？除了正则化还有什么办法？",
        ],
    },
    {
        "username": "stu-ds-001",
        "display_name": "赵雷",
        "password": "123456",
        "major": "数据科学与大数据技术",
        "conversations": [
            "数据科学专业。决策树和随机森林的原理能看懂，但调参总靠运气，GridSearch和交叉验证的逻辑没吃透。希望有参数对比表和可视化调参演示。",
            "我试了你说的GridSearchCV，终于理解了cv参数的作用。但我发现随机森林的n_estimators从100加到500，效果提升不太明显但训练时间长了5倍，这正常吗？一般设多少合适？",
            "另外在做特征重要性分析的时候，随机森林给的feature_importances和用XGBoost算出来的排序不一样，我应该信哪一个？是不是应该做特征交叉验证？",
        ],
    },
    {
        "username": "stu-fin-001",
        "display_name": "陈雪",
        "password": "123456",
        "major": "金融工程",
        "conversations": [
            "金融专业，需要用机器学习做信用评分模型。但对模型评估指标（AUC、KS）理解不深，不知道什么时候该用逻辑回归还是XGBoost。希望结合金融案例讲解。",
            "你上次讲AUC和KS的时候用信贷数据举例很清晰。我试着用逻辑回归做了一个信用评分模型，AUC有0.78。但业务方说想看每个客户的分数而不是概率，怎么把概率映射到评分卡分数？",
            "我按WOE编码和评分卡转换的方法做了，现在模型可解释性好多了。但XGBoost的AUC能做到0.85，为什么业务方还是倾向于用逻辑回归？是因为可解释性的监管要求吗？",
        ],
    },
    {
        "username": "stu-auto-001",
        "display_name": "刘阳",
        "password": "123456",
        "major": "自动化",
        "conversations": [
            "自动化专业。神经网络前向传播能算，但反向传播的链式法则推导总跳步，梯度消失和爆炸不知道怎么调试。需要一步步手算推导加代码验证。",
            "你上次手算了一个3层网络的反向传播，链式法则我终于搞明白了！但我自己写了一个两层的网络做二分类，loss下降到一定程度就不动了，准确率卡在60%左右。是不是梯度消失了？",
            "我试了用ReLU替代Sigmoid，并且加了Batch Normalization，loss确实能继续降了！但还有一个问题：我的网络有5个隐藏层，每层128个神经元，训练特别慢。是不是网络太深了？该怎么确定层数和神经元数？",
        ],
    },
    {
        "username": "stu-ai-001",
        "display_name": "孙丽",
        "password": "123456",
        "major": "人工智能",
        "conversations": [
            "人工智能专业。Transformer的attention机制原理能说个大概，但多头注意力的QKV投影矩阵怎么来的不理解。特别想弄清楚self-attention和cross-attention的区别。",
            "上次你画图解释了QKV的计算过程，我现在理解了每个head是在不同的子空间做投影。但我在看代码实现的时候，发现代码里把d_model=512分成h=8个头，每个头是64维。为什么要这样分？直接用一个512维的attention不行吗？",
            "我试了单头vs多头的对比实验，8个头在翻译任务上BLEU值确实比单头高2个点！另外在实现decoder的时候，masked self-attention的原理我懂，但代码里那个上三角mask矩阵为什么要设置成-1e9而不是0？",
        ],
    },
    {
        "username": "stu-phy-001",
        "display_name": "周博",
        "password": "123456",
        "major": "物理学",
        "conversations": [
            "物理专业转AI。数学推导没问题，但代码实现特别吃力。CNN的卷积核、池化层的参数计算总是搞混，feature map的尺寸变化算不对。希望先给数学公式再给代码对照。",
            "上次你给了公式和代码的对照表，输入32×32用3×3卷积核步长1不填充，输出是30×30。padding='same'的时候输出又是32×32。那如果步长是2呢？输出尺寸怎么算？",
            "懂了！(32-3)/2+1=15.5取整=15。另外池化层的问题：最大池化2×2步长2，我理解是取每个2×2区域的最大值，那如果输入是奇数尺寸呢？比如输入是7×7会怎么样？会自动补零吗？",
        ],
    },
    {
        "username": "stu-ee-001",
        "display_name": "吴昊",
        "password": "123456",
        "major": "电子信息工程",
        "conversations": [
            "电子工程专业。PCA和t-SNE降维的区别不清楚，特征选择总凭感觉。K-means的K值怎么选、聚类评估指标（轮廓系数）不会看。希望有直观的降维可视化对比。",
            "你上次用MNIST数据做了PCA和t-SNE的可视化对比，PCA保留全局结构而t-SNE保留局部结构，这个区别我理解了。但我用PCA做数据压缩的时候，怎么确定保留多少个主成分合适？看累计方差贡献率到95%就够了吗？",
            "我试了用肘部法则和轮廓系数选K值，但两个方法给的结果不一样，肘部法则说K=3，轮廓系数说K=5。这种情况下应该怎么选？是不是要结合实际业务场景来判断？",
        ],
    },
    {
        "username": "stu-bio-001",
        "display_name": "郑悦",
        "password": "123456",
        "major": "生物信息学",
        "conversations": [
            "生物信息学专业。朴素贝叶斯分类器原理简单，但处理高维基因数据时特征之间不是独立的，这会影响模型效果。希望能讲清楚特征相关性对朴素贝叶斯的影响。",
            "你上次解释了为什么朴素贝叶斯的独立性假设在基因数据上不成立——基因之间有共表达关系。我试了用高斯朴素贝叶斯做基因表达数据分类，准确率只有72%。是不是应该换别的模型？",
            "我换了SVM，准确率提到了85%！但是SVM的核函数选哪个好？我用线性核结果还行，但听说RBF核在高维数据上效果更好。我也担心RBF核过拟合，毕竟基因数据特征数远远大于样本数。",
        ],
    },
    {
        "username": "stu-stat-001",
        "display_name": "林枫",
        "password": "123456",
        "major": "统计学",
        "conversations": [
            "统计学专业。假设检验和p值很熟，但机器学习的Bias-Variance Tradeoff总是混淆。偏差大和方差大的情况不知道怎么对应调参，希望能从统计视角讲清楚。",
            "你上次用靶心图解释Bias-Variance Tradeoff很直观：高偏差就是打得不准但集中，高方差就是打得散。那在实际调参中，决策树depth小是高偏差、depth大是高方差，那随机森林怎么通过调参控制这个权衡？",
            "我试了用学习曲线诊断，发现我的XGBoost模型训练误差很低但验证误差高，这是高方差。减少树深度和增加subsample后确实缓解了。那learning_rate和n_estimators应该怎么搭配？先固定一个再调另一个吗？",
        ],
    },
    {
        "username": "stu-se-001",
        "display_name": "郭婷",
        "password": "123456",
        "major": "软件工程",
        "conversations": [
            "软件工程专业。做图像分类项目时，数据增强的策略选择很随意，不知道该翻转还是该裁剪。CNN迁移学习的fine-tuning策略也拿不准，冻结哪些层、学习率怎么调。",
            "上次你建议我按场景选数据增强——医学影像用弹性变形，自然图像用随机翻转裁剪。我试了用ResNet50做迁移学习，冻结了前100层只训练最后几层，准确率只有78%。是不是应该解冻更多层？",
            "我试了分层解冻的策略：先冻结全部训练分类头，然后逐层解冻。准确率提到了86%！但训练时间也翻倍了。还有一个问题：不同数据集适合用不同的预训练模型吗？ImageNet预训练的模型适合医学图像吗？",
        ],
    },
]


def seed_all():
    """执行种子数据注入（增强版：每人3轮对话）"""
    init_db()
    db = SessionLocal()
    try:
        count = 0
        for s in STUDENTS:
            # 创建/更新用户
            existing_user = db.query(DBUser).filter(DBUser.username == s["username"]).first()
            if not existing_user:
                user = DBUser(
                    username=s["username"],
                    hashed_password=get_password_hash(s["password"]),
                    role="student",
                    display_name=s["display_name"],
                )
                db.add(user)

            # 创建/更新画像
            existing_profile = db.query(DBStudentProfile).filter(
                DBStudentProfile.student_id == s["username"]
            ).first()
            
            profile = StudentProfile(student_id=s["username"])
            profile.major = s["major"]
            
            # 依次处理每轮对话，让画像引擎逐步积累上下文
            for msg in s["conversations"]:
                profile.update_from_message(msg)
                
            save_student_profile(db, profile)
            count += 1
            print(f"  [Seed] Enhanced: {s['display_name']} ({s['username']}) - {s['major']} ({len(s['conversations'])} rounds)")

        db.commit()
        print(f"\n  [Seed] Done! {count} students enhanced with multi-round conversations.")
    finally:
        db.close()


def seed_clean():
    """删除所有种子学生数据，用于重新生成"""
    init_db()
    db = SessionLocal()
    try:
        usernames = [s["username"] for s in STUDENTS]
        for uid in usernames:
            db.query(DBUser).filter(DBUser.username == uid).delete()
            profile = db.query(DBStudentProfile).filter(DBStudentProfile.student_id == uid).first()
            if profile:
                db.delete(profile)
        db.commit()
        print(f"  [Seed] Cleaned {len(usernames)} students")
    finally:
        db.close()


if __name__ == "__main__":
    if "--clean" in sys.argv:
        seed_clean()
    else:
        seed_all()
