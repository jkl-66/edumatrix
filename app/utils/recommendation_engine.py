from __future__ import annotations

from typing import Any
from sqlalchemy.orm import Session
from app.database import DBStudentProfile, DBKnowledgeDocument
from rag_engine import hybrid_rag
from models import Evidence, EvidenceModality

# 概念对应视频微课配置表
CONCEPT_VIDEO_MAP = {
    "池化层": {
        "title": "最大池化与下采样三维演示微课",
        "url": "/api/v1/video/stream?concept=池化层",
        "duration": "03:45",
    },
    "最大池化": {
        "title": "最大池化局部计算演算微课",
        "url": "/api/v1/video/stream?concept=最大池化",
        "duration": "02:15",
    },
    "平均池化": {
        "title": "平均池化在图像特征提取中的应用视频",
        "url": "/api/v1/video/stream?concept=平均池化",
        "duration": "02:50",
    },
    "逻辑回归": {
        "title": "逻辑回归与分类决策边界直观几何演示",
        "url": "/api/v1/video/stream?concept=逻辑回归",
        "duration": "05:10",
    },
    "梯度下降": {
        "title": "梯度下降收敛过程与学习率（步长）效应演示",
        "url": "/api/v1/video/stream?concept=梯度下降",
        "duration": "04:30",
    },
    "反向传播": {
        "title": "反向传播算法中链式求导手算与计算图演示",
        "url": "/api/v1/video/stream?concept=反向传播",
        "duration": "06:15",
    },
    "过拟合": {
        "title": "过拟合、欠拟合与正则化惩罚项直观演示视频",
        "url": "/api/v1/video/stream?concept=过拟合",
        "duration": "04:12",
    },
    "机器学习": {
        "title": "机器学习全流程概览与数据流图示",
        "url": "/api/v1/video/stream?concept=机器学习",
        "duration": "05:00",
    },
    "监督学习": {
        "title": "监督学习中的分类与回归边界区分微课",
        "url": "/api/v1/video/stream?concept=监督学习",
        "duration": "03:20",
    },
    "线性回归": {
        "title": "一元线性回归与最小二乘拟合演算微课",
        "url": "/api/v1/video/stream?concept=线性回归",
        "duration": "04:05",
    },
    "前向传播": {
        "title": "前向传播计算与多层感知机特征流演示微课",
        "url": "/api/v1/video/stream?concept=前向传播",
        "duration": "03:15",
    },
    "损失函数": {
        "title": "损失函数与优化目标三维空间几何直观演示",
        "url": "/api/v1/video/stream?concept=损失函数",
        "duration": "04:00",
    },
    "欠拟合": {
        "title": "欠拟合表现及其与模型复杂度权衡关系微课",
        "url": "/api/v1/video/stream?concept=欠拟合",
        "duration": "03:30",
    },
    "激活函数": {
        "title": "激活函数非线性转换与梯度流失效应直观演示",
        "url": "/api/v1/video/stream?concept=激活函数",
        "duration": "04:45",
    }
}


def evaluate_tactical_pathway(
    concept: str,
    mastery_val: float,
    frustration: float,
    top_cause: str,
    is_code_style: bool,
    is_theory_style: bool,
    has_code_pref: bool,
    has_theory_pref: bool,
    major_lower: str,
    major: str
) -> dict[str, Any]:
    """根据学情特征多维度评估，决策当前概念对应的自适应教学战术路线"""
    # Decide pathway based on combination of parameters
    if frustration >= 0.60 or top_cause == "affective_barrier":
        return {
            "code": "RESCUE",
            "name": "紧急防忘线",
            "badge": "🚨 遗忘阻击",
            "theme_color": "rose",
            "description": "检测到当前认知阻力较大或面临记忆遗忘，已开启减负与多重记忆激活模式。",
            "difficulty_rating": 2
        }
    elif mastery_val < 0.25 or top_cause == "prerequisite_gap":
        return {
            "code": "ICE_BREAKER",
            "name": "零基础破冰线",
            "badge": "🚀 概念破冰",
            "theme_color": "blue",
            "description": "针对新接触或前置依赖欠缺的概念，开启低负荷概念锚定与拓扑解构机制。",
            "difficulty_rating": 1
        }
    elif (is_code_style or has_code_pref) and any(kw in major_lower for kw in ["计算机", "软件", "cs", "software", "信息", "开发", "技术"]):
        return {
            "code": "PRACTITIONER",
            "name": "实战极客线",
            "badge": "🛠️ 源码实操",
            "theme_color": "emerald",
            "description": "契合您的技术背景与代码直觉，首选代码逻辑与单元测试沙箱实操。",
            "difficulty_rating": 4
        }
    elif (is_theory_style or has_theory_pref) and any(kw in major_lower for kw in ["数学", "math", "统计", "物理", "physics", "理论"]):
        return {
            "code": "EXPLORER",
            "name": "学术探究线",
            "badge": "🔬 学术探究",
            "theme_color": "violet",
            "description": "聚焦于数学公理推导、参数似然估计与严格证明，满足深度学术探究诉求。",
            "difficulty_rating": 5
        }
    elif major_lower and not any(kw in major_lower for kw in ["计算机", "软件", "cs", "software", "数学", "math", "stats", "统计"]):
        return {
            "code": "FUSION",
            "name": "跨界融合线",
            "badge": "📈 应用融合",
            "theme_color": "amber",
            "description": f"结合您的【{major}】专业应用情境，将算法概念映射至特定领域实战中。",
            "difficulty_rating": 3
        }
    else:
        # 默认兜底
        if mastery_val < 0.40:
            return {
                "code": "ICE_BREAKER",
                "name": "零基础破冰线",
                "badge": "🚀 概念破冰",
                "theme_color": "blue",
                "description": "针对偏低掌握度进行渐进式讲解，优先构建底层概念直觉。",
                "difficulty_rating": 2
            }
        else:
            return {
                "code": "PRACTITIONER",
                "name": "实战极客线",
                "badge": "🛠️ 源码实操",
                "theme_color": "emerald",
                "description": "基于中高掌握度，开展算法底座工程化及用例落地训练。",
                "difficulty_rating": 3
            }


def get_concept_specific_overview(concept: str, key: str, pathway: str) -> str:
    # 知识点库定义，为每个知识点的五大维度量身定制说明
    database = {
        "梯度下降": {
            "lecture": {
                "ICE_BREAKER": "【零基础破冰】从‘下山下坡寻低谷’的生活比喻引入，直观理解偏导数和负梯度方向是函数值下降最快的几何意义。",
                "PRACTITIONER": "【工程源码】深入剖析梯度下降的批量、随机及小批量（Mini-batch）迭代更新公式，分析工程落地中的计算效率与内存吞吐。",
                "EXPLORER": "【严谨推导】数学公理偏导推导。严格证明凸优化下梯度下降的收敛性，给出一阶泰勒展开与收敛边界定理的证明。",
                "RESCUE": "【易漏考点】精简提炼梯度下降核心三考点：学习率过大导致震荡不收敛、过小导致收敛极慢以及鞍点危机的几何表征。",
                "FUSION": "【跨界场景】以量化资产组合收益最大化为背景，讲解如何利用梯度更新求解最优资产配比的马科维茨数学计算模型。"
            },
            "code": {
                "ICE_BREAKER": "【极简代码】20行纯 Python 代码，使用一个简单的一元二次函数 $y = x^2$ 演示如何通过迭代 `x = x - lr * grad` 找到最小值点，中文逐行详细注解。",
                "PRACTITIONER": "【工程手写】使用 Python 手写实现 Batch Gradient Descent 类，带有强类型注解和完整的单元测试断言，支持指定不同的学习率和收敛阈值。",
                "EXPLORER": "【矩阵求导】使用 NumPy 从零实现多元线性回归的梯度下降求解。代码中将严格对照矩阵偏导公式进行张量运算，不使用现成框架。",
                "RESCUE": "【错题Debug】提供一段故意写错的梯度更新代码（例如误写成 `w = w + lr * grad` 导致发散），需要你在隔离沙箱中找出 Bug 并成功纠错。",
                "FUSION": "【量化实战】提供使用梯度下降优化马科维茨有效前沿投资组合的 Python 实战项目，针对真实股票历史收益率数据集进行优化预测。"
            },
            "mindmap": {
                "ICE_BREAKER": "【概念解构】梯度下降认知骨架图：梳理偏导数、步长（学习率）、迭代次数到参数更新的极简关系网络，直观展示下山过程。",
                "PRACTITIONER": "【数据流图】最大化收敛能效：TensorFlow/PyTorch 自动求导机制（Autograd）中梯度流（Gradient Flow）的动态传播与张量大小演化架构图。",
                "EXPLORER": "【数理脉络】包含从多元微积分、凸函数定义、一阶泰勒展开到梯度迭代收敛定理一步步严格逻辑推导脉络的思维导图。",
                "RESCUE": "【高能导图】单页极简速记导图，用红色醒目标记‘局部极小值、鞍点、梯度消失、梯度爆炸’等避坑高频考点。",
                "FUSION": "【应用拓扑】展示梯度下降算法作为底层工具，在量化投资、物流路径规划及供应链选址等现实跨界业务流程中的应用拓扑图。"
            },
            "quiz": {
                "ICE_BREAKER": "【概念自测】单步辨析选择题：考察‘梯度’的物理几何含义、以及梯度方向与函数值变化率的关系，不含复杂计算。",
                "PRACTITIONER": "【沙箱写码】设计一组单元测试，要求你在隔离沙箱中补充实现带 Momentum 动量加速的梯度更新核心算子，使测试全部通过。",
                "EXPLORER": "【数理证明】要求给出 Rosenbrock 凸函数在给定学习率下的单步梯度更新计算过程，并证明其在特定区间内的收敛性。",
                "RESCUE": "【混淆自测】3道经典易混淆选择题：辨析 BGD, SGD, MBGD 的样本量级与收敛平滑度差异，配有极细致的分步防错解析。",
                "FUSION": "【业务调优】真实商业案例题：假设当前投资组合面临震荡不收敛，考察你如何调整学习率衰减（Decay）策略以平衡算法稳定度。"
            },
            "video": {
                "ICE_BREAKER": "【3D动画】3分钟生动 3D 动画：把优化过程比作滑雪者在山谷中寻找最低点，生动演示学习率过大和过小在山谷两端的滑行轨迹。",
                "PRACTITIONER": "【断点调试】5分钟分屏录屏：调试工具跟踪训练神经网络时，不同参数的梯度值以及 Adam 优化器内部一阶/二阶动量的实时变化过程。",
                "EXPLORER": "【板书微课】板书推导视频：教授手书一阶泰勒展开式，详细演算梯度下降在非凸损失曲面上如何一步步逼近临界点。",
                "RESCUE": "【考点速记】2分钟高能知识点速记：名师串讲‘局部极小值 vs 鞍点’、‘梯度爆炸 vs 梯度消失’等易错高频概念。",
                "FUSION": "【场景视频】3D 实景演示视频：展示梯度下降如何在航空配餐算法中通过微调供给配比，实现运营成本最小化。"
            }
        },
        "最大池化": {
            "lecture": {
                "ICE_BREAKER": "【零基础破冰】从‘报纸缩图/只保留最亮色块’的通俗类比切入，带你理解为什么要从一个区域中只保留最大值，以及它是如何实现下采样的。",
                "PRACTITIONER": "【工程源码】深入讲解卷积神经网络（CNN）中最大池化层（MaxPool2d）的特征图尺寸计算公式、前向传播与反向传播时梯度流的掩码传播机制。",
                "EXPLORER": "【数理推导】数学公式解析。严格证明最大池化层对输入图像进行微小仿射变换（平移、旋转）时所具备的平移不变性与特征鲁棒性数学原理。",
                "RESCUE": "【避坑卡片】精炼总结最大池化核心考点：最大池化会导致空间结构信息丢失、反向传播时梯度只回传给最大值对应位置等易忘特性。",
                "FUSION": "【跨界场景】以医学影像（核磁共振图 MRI）病灶边缘检测为背景，讲解最大池化如何保留最强病变信号并压制环境背景噪声。"
            },
            "code": {
                "ICE_BREAKER": "【极简代码】20行纯 Python 代码，使用一个简单 $4\\times4$ 的二维列表代表特征图，演示如何用嵌套循环实现步长为2、核大小为2的最大池化，不依赖第三方库。",
                "PRACTITIONER": "【工程手写】使用 Python 和 NumPy 编写手写 CNN 最大池化层算子，实现 `forward` 与 `backward` 方法（包含 Max Mask 梯度的定位传播），附带完整的单元测试用例。",
                "EXPLORER": "【张量重组】使用纯 NumPy 的张量重排（as_strided 技巧）实现极速、无显式循环的高性能最大池化算法，对照滑窗重叠的底层存储布局。",
                "RESCUE": "【反例纠错】提供一段故意写错的最大池化代码（例如将最大值提取误写成了均值，或错算了输出宽度），需要你在沙箱中排查 Bug 并使其通过测试。",
                "FUSION": "【业务实战】提供将最大池化应用在卫星遥感图像水体边界检测中的 Python 建模项目，演示它过滤反射光波干扰、保留清晰河床边缘。"
            },
            "mindmap": {
                "ICE_BREAKER": "【概念解构】最大池化认知图：通过一个带彩色的 $4\\times4$ 矩阵向 $2\\times2$ 矩阵逆采样的动画感图，展示最大池化提取最强特征的流程。",
                "PRACTITIONER": "【算子架构】展示特征图经过最大池化后特征高度/宽度变换、通道数保持不变以及在前向/反向传播过程中 Mask 矩阵 of 流转拓扑图。",
                "EXPLORER": "【数理脉络】梳理最大池化算子、卷积层、全局平均池化层到特征不变性证明逻辑链条的数学脉络导图。",
                "RESCUE": "【救急导图】单页紧凑速记图，醒目高亮‘反向传播只回传给最大索引、非最大值位置梯度为零、输出计算公式的分母进位规则’等致命考点。",
                "FUSION": "【应用拓扑】展示最大池化如何在图像识别、声纹识别以及时序强信号提取（如股票突发高波幅检测）中起到滤波作用的应用拓扑图。"
            },
            "quiz": {
                "ICE_BREAKER": "【概念自测】单步概念辨析题：考察池化层是否有训练参数、池化后通道数是否会改变等核心定义概念。",
                "PRACTITIONER": "【沙箱写码】设计一组测试用例，要求在沙箱中实现最大池化算子的反向传播梯度回传函数，必须正确根据最大值掩码（Mask）将上游梯度分配到正确位置。",
                "EXPLORER": "【数学推导】给定一个具体的 $3\\times3$ 输入矩阵和核参数，手算输出并证明在给定平移变换下其最大池化输出的等价性。",
                "RESCUE": "【高频易错】3道选择题：聚焦于卷积步长与池化步长对特征提取精细度的影响、Padding 填充对池化边界计算的干扰等易错点。",
                "FUSION": "【特定行业】给定一个声学波形图分析场景，考察你如何调整最大池化核的宽度以滤除高频呼吸白噪声并保留声纹主波幅特征。"
            },
            "video": {
                "ICE_BREAKER": "【3D动画】3分钟三维特效动画：将 $4\\times4$ 像素网格拉起，最大数值的像素被提取并合并到 $2\\times2$ 的微型网络上，直观展示下采样降噪。",
                "PRACTITIONER": "【Debug讲解】5分钟录屏：用 Python Debugger 一步步演示特征矩阵反向传播时，非最大值位置的梯度是如何被 Mask 矩阵强制归零的原理。",
                "EXPLORER": "【板书证明】板书推导视频：教授演算最大池化在空间平移不变性上的严格数学界限，推导为什么池化能减小模型的空间敏感度。",
                "RESCUE": "【考点串讲】2分钟避坑速记：快速串讲最大池化与平均池化在信息损耗、梯度回传机制上的核心差异与常考考点。",
                "FUSION": "【业务实战】实景微视频：展示最大池化技术如何在工业流水线缺陷视觉检测中，抓取细微钢板裂纹（最强信号特征）的商业落地应用。"
            }
        }
    }
    
    # 兜底通用生成算法：若数据库没有该概念，则根据概念名 c_node 动态拼接出具有知识点特异性但又符合战术路线风格的描述
    if concept in database:
        if key in database[concept]:
            if pathway in database[concept][key]:
                return database[concept][key][pathway]
                
    # 动态兜底生成，确保每种资源的概括根据知识点内容和战术路线有所不同
    role_map = {
        "lecture": {
            "ICE_BREAKER": f"【零基础破冰】围绕【{concept}】的核心思想，通过通俗易懂的比喻和生活实例，为您搭建起最底层的直观物理模型，避开繁琐的数理障碍。",
            "PRACTITIONER": f"【源码解析】偏向工程落地，主要梳理【{concept}】在实际代码中的数据排布、内存对齐、算子并行化设计与计算瓶颈优化细节。",
            "EXPLORER": f"【理论证明】严谨的数理推导讲义。深入解构【{concept}】的底层数学模型，包含详细的概率测度、极值约束以及收敛性数学证明。",
            "RESCUE": f"【精简复习】针对【{concept}】的常考要点进行卡片式总结，精简了 80% 冗余描述，以极高能量密度提炼出核心考点与经典认知误区。",
            "FUSION": f"【跨界场景】以实际项目应用为背景，阐述【{concept}】算法如何有效应用到具体领域，剖析并解答核心行业痛点。"
        },
        "code": {
            "ICE_BREAKER": f"【极简代码】提供零依赖的极简 Python 代码范例，包含逐行中文详尽注释，确保无第三方复杂模块干扰，帮您快速看清【{concept}】的核心控制回路。",
            "PRACTITIONER": f"【极客源码】提供符合生产规范的工程级 Python 手写实现【{concept}】，配有强类型注解、规范的 docstrings 以及完善的自动化单元测试用例。",
            "EXPLORER": f"【NumPy手写】使用纯 NumPy 张量运算从零实现【{concept}】，严格对应数学公式中的每一个希腊字母和偏导求导算子，不使用高层框架封装。",
            "RESCUE": f"【错题Debug】提供一段在算子实现、张量形状或更新公式中故意写错的【{concept}】代码，需要您在隔离沙箱中排查 Bug 并使其通过断言。",
            "FUSION": f"【应用实战】提供针对真实业务场景数据集的【{concept}】建模预测完整 Python 项目，包含数据预处理、模型训练及评价评估全流程代码。"
        },
        "mindmap": {
            "ICE_BREAKER": f"【极简概念图】梳理【{concept}】最核心的几个基础定义与逻辑依赖关系，排除繁琐的进阶分支，帮您快速构建全局认知脉络。",
            "PRACTITIONER": f"【工程架构图】整理【{concept}】在实际代码架构和多智能体流转中的数据流图、Tensor 形状演变图以及算子层级拓扑结构图。",
            "EXPLORER": f"【数学脉络图】梳理【{concept}】从最基础的数理公理、条件约束到最终求导或模型公式一步步推导过程的数理拓扑关系图。",
            "RESCUE": f"【救急导图】单页高浓度知识脑图，用醒目红色高亮标记【{concept}】的常考盲区、易忘特征与相似概念对比节点，用于极速扫描复习。",
            "FUSION": f"【应用流程图】展现【{concept}】在现实业务体系中从数据流入、算子计算、输出判定到最终商业/科学价值产出的全流程流转网络图。"
        },
        "quiz": {
            "ICE_BREAKER": f"【概念辨析】单步定义选择题与图形匹配题，侧重考察【{concept}】的基础物理直觉与核心名词辨析，不包含任何复杂的计算推导。",
            "PRACTITIONER": f"【沙箱写码】提供一组单元测试用例，要求您在隔离沙箱中补全【{concept}】的核心更新算子或主逻辑函数，使其顺利运行并通过测试套件。",
            "EXPLORER": f"【数理证明】多步细粒度公式推导与参数估计证明题，着重考察【{concept}】在极限边界、凸性收敛等场景下的数学严密性，提供分步解析打分。",
            "RESCUE": f"【高频防错】针对您近期易错和易混淆的认知盲区，智能组合 3 道辨析选择题，附带极其详尽的多步解析，帮您对抗艾宾浩斯遗忘红线。",
            "FUSION": f"【跨界案例】给出一个真实的商业或科学业务案例，考察您如何根据具体限制条件，选择合适的【{concept}】核心参数并微调算法策略以解决问题。"
        },
        "video": {
            "ICE_BREAKER": f"【3D直观动画】3分钟三维概念演示微视频，使用高度通俗的视觉类比，生动展示【{concept}】的内部物理运行和元素流转全过程。",
            "PRACTITIONER": f"【代码Debug讲解】极客导师带您一步步单步 Debug 追踪【{concept}】底层内存与变量变化的录屏讲解微课，助您直观理解代码执行流程。",
            "EXPLORER": f"【公式手书黑板课】名校教授在黑板上手书公式，详细演算【{concept}】数学偏导展开、极值推导与边界证明步骤的板书演进视频。",
            "RESCUE": f"【冲刺必背视频】2分钟高能考点快速串讲视频，高度凝练总结【{concept}】最容易被混淆和漏掉的核心考点与必考速记口诀。",
            "FUSION": f"【业务实景模拟】以真实的跨界场景为背景拍摄的动画实景演示视频，展现【{concept}】如何在工程或商业落地中产生实际的经济与学术效益。"
        }
    }
    return role_map[key][pathway]


def get_smart_recommendations(
    db: Session,
    student_id: str,
    limit: int = 3,
    concept: str | None = None,
    pathway: str | None = None
) -> list[dict[str, Any]]:
    """根据学生认知掌握度、薄弱点与交互偏好，自适应精准推送匹配的学习资源"""
    from app.database import DBNote, DBStudentProfile

    # 1. 读取学生画像
    profile = db.query(DBStudentProfile).filter(
        DBStudentProfile.student_id == student_id
    ).first()

    if not profile:
        # 兜底 fallback 画像
        class DummyProfile:
            concept_mastery = {"机器学习": 0.35, "线性回归": 0.40}
            learning_goals = ["机器学习", "线性回归"]
            weak_points = ["机器学习"]
            interaction_preferences = ["图示演示"]
            cognitive_style = "图示型"
            major = "计算机"
            frustration_index = 0.0
            learning_state_causes = {}
        profile = DummyProfile()

    mastery = profile.concept_mastery or {}
    goals = profile.learning_goals or []
    weak_points = profile.weak_points or []
    major = getattr(profile, "major", "") or ""
    major_lower = major.lower()
    frustration = getattr(profile, "frustration_index", 0.0) or 0.0

    # 提取顶级学习障碍原因
    causes = getattr(profile, "learning_state_causes", {}) or {}
    top_cause = None
    top_cause_percentage = 0
    if causes:
        for k, v in causes.items():
            percentage = getattr(v, "percentage", 0) if not isinstance(v, dict) else v.get("percentage", 0)
            if percentage > top_cause_percentage:
                top_cause = k
                top_cause_percentage = percentage

    # 风格归一化判定
    style = getattr(profile, "cognitive_style", "") or ""
    style_lower = style.lower()
    is_code_style = "code" in style_lower or "代码" in style_lower
    is_visual_style = "visual" in style_lower or "图示" in style_lower or "图形" in style_lower
    is_theory_style = "theory" in style_lower or "理论" in style_lower or "数学" in style_lower

    # 偏好归一化判定
    preferences = getattr(profile, "interaction_preferences", []) or []
    pref_str = "".join(preferences).lower()
    has_code_pref = "code" in pref_str or "代码" in pref_str
    has_visual_pref = "visual" in pref_str or "图示" in pref_str or "图形" in pref_str
    has_video_pref = "video" in pref_str or "视频" in pref_str or "微课" in pref_str
    has_theory_pref = "theory" in pref_str or "理论" in pref_str or "讲义" in pref_str
    has_quiz_pref = "quiz" in pref_str or "做题" in pref_str or "练习" in pref_str or "测验" in pref_str

    # 2. 确定待推荐的目标概念
    if concept:
        target_concepts = [concept]
    else:
        # 当未指定概念时，智能提取当前的 A* 唯一主攻锚点（Active Learning Target）
        from learning_strategy import PathPlanner, build_resource_aware_dag, compute_concept_tiers
        from profile_api import KNOWLEDGE_DAG
        
        all_concepts = set(mastery.keys()) | set(KNOWLEDGE_DAG.keys())
        for prereqs in KNOWLEDGE_DAG.values():
            all_concepts.update(prereqs or [])
        all_concepts.discard("")
        all_concepts.discard(None)
        
        # 1. 最终目标智能定位（三级解析）
        real_goals = [g for g in goals if g in all_concepts]
        resolved_goals = []
        if real_goals:
            resolved_goals = real_goals
        else:
            # 第二级：课件提取
            docs = db.query(DBKnowledgeDocument).filter(DBKnowledgeDocument.student_id == student_id).all()
            doc_concepts = set()
            for doc in docs:
                if doc.tags:
                    tags_list = doc.tags if isinstance(doc.tags, list) else []
                    if not tags_list and isinstance(doc.tags, str):
                        try:
                            import json
                            tags_list = json.loads(doc.tags)
                        except Exception:
                            pass
                    doc_concepts.update([t for t in tags_list if t in all_concepts])
            if doc_concepts:
                sorted_doc_concepts = sorted(doc_concepts, key=lambda c: (mastery.get(c, 0.0), -len(KNOWLEDGE_DAG.get(c, []) or [])))
                resolved_goals = [sorted_doc_concepts[0]]
            else:
                # 第三级：当前课程骨干兜底
                core_backbones = sorted(all_concepts, key=lambda c: (-len(KNOWLEDGE_DAG.get(c, []) or []), c))
                resolved_goals = [core_backbones[0]] if core_backbones else ["机器学习"]
                
        # 2. 运行 A* 路径规划
        planner = PathPlanner(KNOWLEDGE_DAG)
        active_dag, _ = build_resource_aware_dag(KNOWLEDGE_DAG)
        concept_tier = compute_concept_tiers(active_dag, all_concepts)
        
        load_val = getattr(profile, "cognitive_load", 0.45) or 0.45
        frustration_val = getattr(profile, "frustration_index", 0.0) or 0.0
        
        adaptive_route = planner.plan(
            mastery,
            learning_goals=resolved_goals,
            weak_points=weak_points,
            concept_tier=concept_tier,
            cognitive_load=load_val,
            frustration=frustration_val,
            max_steps=8,
        )
        
        # 3. 确定当前主攻点
        active_target = None
        if adaptive_route and "nodes" in adaptive_route:
            for node in adaptive_route["nodes"]:
                c_name = node.get("concept")
                if c_name and mastery.get(c_name, 0.0) < 0.70:
                    active_target = c_name
                    break
                    
        if not active_target:
            # 拓扑排序备选
            tiers = {}
            for c, t in concept_tier.items():
                tiers.setdefault(t, []).append(c)
            learning_chain = []
            for t in sorted(tiers.keys()):
                for c in tiers[t]:
                    prereqs = active_dag.get(c, [])
                    prereqs_ready = all(mastery.get(p, 0.0) >= 0.4 for p in prereqs)
                    learning_chain.append({"concept": c, "mastery": mastery.get(c, 0.0), "prereqs_ready": prereqs_ready})
            next_steps = [n for n in learning_chain if n["mastery"] < 0.70 and n["prereqs_ready"]]
            if next_steps:
                active_target = next_steps[0]["concept"]
                
        if not active_target and mastery:
            active_target = min(mastery.items(), key=lambda x: x[1])[0]
            
        if not active_target:
            active_target = "机器学习"
            
        # 4. 辅助添加其它薄弱点/目标，供卡片流备用且确保不破坏既有单测
        other_candidates = []
        for c, score in sorted(mastery.items(), key=lambda item: item[1]):
            if score < 0.60:
                other_candidates.append(c)
        for wp in weak_points:
            if wp not in other_candidates:
                other_candidates.append(wp)
        for g in goals:
            if g not in other_candidates:
                other_candidates.append(g)
                
        target_concepts = [active_target]
        for c in other_candidates:
            if c not in target_concepts:
                target_concepts.append(c)
                
        target_concepts = target_concepts[:limit]

    # 3. 加载该学生所有的笔记缓存，用于判断 5 维资源是否已生成
    student_notes = db.query(DBNote).filter(DBNote.student_id == student_id).all()

    results = []
    for c_node in target_concepts:
        concept_mastery_val = mastery.get(c_node, 0.40)
        badge = "🔥 薄弱强化" if concept_mastery_val < 0.40 else "💡 探索进阶"

        # 评估本概念的战术路线
        if pathway:
            forced_map = {
                "RESCUE": {
                    "code": "RESCUE",
                    "name": "紧急防忘线",
                    "badge": "🚨 遗忘阻击",
                    "theme_color": "rose",
                    "description": "已手动开启减负与多重记忆激活模式，防止概念遗忘。",
                    "difficulty_rating": 2
                },
                "ICE_BREAKER": {
                    "code": "ICE_BREAKER",
                    "name": "零基础破冰线",
                    "badge": "🚀 概念破冰",
                    "theme_color": "blue",
                    "description": "已手动开启低负荷概念锚定与拓扑解构机制。",
                    "difficulty_rating": 1
                },
                "PRACTITIONER": {
                    "code": "PRACTITIONER",
                    "name": "实战极客线",
                    "badge": "🛠️ 源码实操",
                    "theme_color": "emerald",
                    "description": "已手动切换为实战极客策略，首选代码逻辑与单元测试沙箱实操。",
                    "difficulty_rating": 4
                },
                "EXPLORER": {
                    "code": "EXPLORER",
                    "name": "学术探究线",
                    "badge": "🔬 学术探究",
                    "theme_color": "violet",
                    "description": "已手动切换为深度学术探究，聚焦数学公理与证明推导。",
                    "difficulty_rating": 5
                },
                "FUSION": {
                    "code": "FUSION",
                    "name": "跨界融合线",
                    "badge": "📈 应用融合",
                    "theme_color": "amber",
                    "description": f"已手动切换为跨界融合，结合【{major or '应用学科'}】进行情境化实践。",
                    "difficulty_rating": 3
                }
            }
            pathway_meta = forced_map.get(pathway.upper(), evaluate_tactical_pathway(
                c_node, concept_mastery_val, frustration, top_cause,
                is_code_style, is_theory_style, has_code_pref, has_theory_pref, major_lower, major
            ))
        else:
            pathway_meta = evaluate_tactical_pathway(
                c_node, concept_mastery_val, frustration, top_cause,
                is_code_style, is_theory_style, has_code_pref, has_theory_pref, major_lower, major
            )

        pathway_code = pathway_meta["code"]

        # --- 认知对齐加权得分模型 ---
        scores = {
            "lecture": 50,
            "mindmap": 50,
            "code": 50,
            "quiz": 50,
            "video": 50
        }

        # 认知风格加权
        if is_code_style:
            scores["code"] += 25
        if is_visual_style:
            scores["mindmap"] += 20
            scores["video"] += 25
        if is_theory_style:
            scores["lecture"] += 25

        # 交互偏好加权
        if has_code_pref:
            scores["code"] += 20
        if has_visual_pref:
            scores["mindmap"] += 15
            scores["video"] += 15
        if has_video_pref:
            scores["video"] += 20
        if has_theory_pref:
            scores["lecture"] += 20
        if has_quiz_pref:
            scores["quiz"] += 20

        # 障碍根因加权
        if top_cause == "prerequisite_gap" and top_cause_percentage >= 30:
            scores["lecture"] += 15
            scores["mindmap"] += 15
        elif top_cause == "misconception" and top_cause_percentage >= 30:
            scores["quiz"] += 15
            scores["lecture"] += 15
        elif top_cause == "cognitive_load" and top_cause_percentage >= 30:
            scores["video"] += 15
            scores["mindmap"] += 15

        # 掌握度加权
        if concept_mastery_val < 0.3:
            scores["lecture"] += 10
            scores["quiz"] += 10

        # 根据战术路线进行优先级干预以确保推荐维度对应首选，同时尊重学生的认知风格
        if pathway_code == "ICE_BREAKER":
            if is_code_style:
                scores["code"] += 100
            elif is_theory_style:
                scores["lecture"] += 100
            else:
                scores["lecture"] += 100
        elif pathway_code == "PRACTITIONER":
            scores["code"] += 100
        elif pathway_code == "EXPLORER":
            if is_code_style:
                scores["code"] += 100
            elif is_theory_style:
                scores["lecture"] += 100
            else:
                scores["lecture"] += 100
        elif pathway_code == "RESCUE":
            if is_code_style:
                scores["code"] += 100
            else:
                scores["quiz"] += 100
        elif pathway_code == "FUSION":
            if is_code_style:
                scores["code"] += 100
            elif is_visual_style:
                scores["video"] += 100
            else:
                scores["video"] += 100

        # 确定首选推荐维度
        top_key = max(scores, key=lambda k: (scores[k], ["lecture", "code", "mindmap", "video", "quiz"].index(k)))

        # === Q-learning DRL 决策融合与修正 ===
        try:
            from app.utils.rl_planner import QLearningPathPlanner
            load_val = getattr(profile, "cognitive_load", 0.45) or 0.45
            state_key = QLearningPathPlanner.get_state_key(
                mastery=concept_mastery_val,
                load=load_val,
                frustration=frustration
            )
            rl_best_action = QLearningPathPlanner.get_best_action(profile, state_key, epsilon=0.0)
            if rl_best_action and rl_best_action in scores:
                top_key = rl_best_action
        except Exception:
            pass

        top_name_map = {
            "lecture": "专业讲义",
            "mindmap": "思维导图",
            "code": "代码案例",
            "quiz": "练习题",
            "video": "视频脚本"
        }
        top_res_name = top_name_map[top_key]
        style_desc = getattr(profile, "cognitive_style", "") or "自适应"
        
        cause_desc = "学习路径推进"
        if top_cause == "prerequisite_gap":
            cause_desc = "前置知识欠缺"
        elif top_cause == "misconception":
            cause_desc = "概念易混淆"
        elif top_cause == "cognitive_load":
            cause_desc = "认知负荷过高"
        elif top_cause == "strategy_gap":
            cause_desc = "学习策略欠缺"
        elif top_cause == "affective_barrier":
            cause_desc = "挫败感偏高"

        reason = (
            f"分析您在【{c_node}】上的最新学情：当前掌握度为 {int(concept_mastery_val * 100)}%。"
            f"结合您的【{style_desc}】风格、【{cause_desc}】诊断主因及【{pathway_meta['name']}】策略，"
            f"系统已首选为您定制推送了【{top_res_name}】。"
        )

        # === 专属学情诊断与改进意见（细节分析、原因、意见） ===
        bloom_level = "记忆" if concept_mastery_val < 0.20 else "理解" if concept_mastery_val < 0.40 else "应用" if concept_mastery_val < 0.60 else "分析" if concept_mastery_val < 0.75 else "评价" if concept_mastery_val < 0.90 else "创造"
        
        detail_analysis = f"当前掌握度为 {int(concept_mastery_val * 100)}%，在知识点认知上处于【{bloom_level}】阶段。"
        if concept_mastery_val < 0.35:
            detail_analysis += f"对【{c_node}】的基本定义和核心逻辑建立尚不完整，存在明显的认知薄弱。"
        elif concept_mastery_val < 0.65:
            detail_analysis += f"已掌握【{c_node}】的表层概念，但在计算推导或实际应用中仍存在困难。"
        else:
            detail_analysis += f"已基本掌握【{c_node}】的核心要义，具备较好的分析与迁移能力。"
            
        reason_desc = f"诊断主因为【{cause_desc}】。"
        if top_cause == "prerequisite_gap":
            reason_desc += "前置依赖概念掌握不足，导致在理解当前概念时遇到了理解断层。"
        elif top_cause == "misconception":
            reason_desc += "存在概念混淆（如正反例区分不清），在概念辨析时容易产生混淆。"
        elif top_cause == "cognitive_load":
            reason_desc += "概念本身的数学或逻辑复杂度高，导致单步推理时产生过载。"
        elif top_cause == "affective_barrier":
            reason_desc += "近期连续答错或受阻，产生了明显的学习挫败感。"
        else:
            reason_desc += "常规学习状态推演，未发现显性阻碍漏洞。"
            
        advice_desc = f"建议采取【{pathway_meta['name']}】战术路线进行针对性强化。"
        if pathway_code == "ICE_BREAKER":
            advice_desc += "建议优先看讲义和思维导图，建立物理直觉，暂时不建议强攻代码和复杂数学题。"
        elif pathway_code == "PRACTITIONER":
            advice_desc += "建议直接阅读工程级代码实现并进行沙箱编写，以源码和单元测试驱动概念理解。"
        elif pathway_code == "EXPLORER":
            advice_desc += "建议深入研究 LaTeX 公式推导和收敛界限证明，用数学的严谨性稳固知识结构。"
        elif pathway_code == "RESCUE":
            advice_desc += "建议先阅读易错考点反思卡片，然后做 3 道自适应辨析题以巩固记忆、对抗遗忘。"
        else:
            advice_desc += "建议将概念应用到实际场景中，建立多学科知识融合连接。"
            
        learning_state_overview = {
            "detail_analysis": detail_analysis,
            "reason": reason_desc,
            "advice": advice_desc
        }

        # --- 战术路线大纲编译器 (Overview Compiler) ---
        resources_map = {}

        # 针对每个资源维度，动态或定制化地编译 overview，使其根据知识点内容和路线有所不同
        lecture_overview = get_concept_specific_overview(c_node, "lecture", pathway_code)
        mindmap_overview = get_concept_specific_overview(c_node, "mindmap", pathway_code)
        code_overview = get_concept_specific_overview(c_node, "code", pathway_code)
        quiz_overview = get_concept_specific_overview(c_node, "quiz", pathway_code)
        video_overview = get_concept_specific_overview(c_node, "video", pathway_code)

        res_meta = {
            "lecture": ("10分钟", 2, "核心概念第一直觉"),
            "mindmap": ("4分钟", 1, "核心定义与依赖分级"),
            "code": ("12分钟", 2, "极简代码逐行精读"),
            "quiz": ("8分钟", 2, "单步定义极速自测"),
            "video": ("3分钟", 1, "物理运行动画直觉")
        }

        # 个性化大纲编译器后处理：根据专业背景与心理学脚手架动态修饰 overview
        if any(kw in major_lower for kw in ["计算机", "软件", "cs", "software", "技术"]):
            code_overview += " (代码采用规范工程级写法，便于集成)"
        elif any(kw in major_lower for kw in ["数学", "math", "统计", "物理"]):
            lecture_overview += " (公式经严谨排版与严格证明校验)"

        if frustration >= 0.70:
            code_overview += " （针对您的挫败感，已提供简易数据输入案例以降低上手难度）"
            lecture_overview += " （内容已精简，重点难点有通俗类比，降低理解负荷）"
            quiz_overview += " （配备了渐进式解题提示，助您平稳度过难关）"

        # 收集 5 维维度数据
        DIMENSIONS = [
            ("lecture", "理论教授", "专业讲义", "专业讲义", lecture_overview),
            ("mindmap", "逻辑画师", "思维导图", "思维导图", mindmap_overview),
            ("code", "极客助教", "代码实操案例", "代码案例", code_overview),
            ("quiz", "考官智能体", "练习题", "练习题", quiz_overview),
            ("video", "视频推荐官", "自适应推荐视频", "视频脚本", video_overview)
        ]

        for key, role, res_type, db_tag, compiled_overview in DIMENSIONS:
            matched_note = None
            for note in student_notes:
                concepts_list = note.concepts or []
                tags_list = note.tags or []
                if c_node in concepts_list and db_tag in tags_list:
                    matched_note = note
                    break
            
            is_top = (key == top_key)
            duration_val, brain_load_val, focus_val = res_meta.get(key, ("10分钟", 3, "自适应练习"))
            
            resources_map[key] = {
                "role": role,
                "resource_type": res_type,
                "overview": compiled_overview,
                "status": "generated" if matched_note else "not_generated",
                "note_id": matched_note.id if matched_note else None,
                "priority": scores[key],
                "is_top": is_top,
                # 高表现力元数据
                "duration": duration_val,
                "brain_load": brain_load_val,
                "skill_focus": focus_val
            }

        results.append({
            "concept": c_node,
            "mastery": round(concept_mastery_val, 2),
            "badge": badge,
            "reason": reason,
            "learning_state_overview": learning_state_overview,
            "pathway_meta": pathway_meta,
            "resources": resources_map
        })

    return results
