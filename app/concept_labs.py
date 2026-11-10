"""Small executable experiments for the AI course's individual concepts.

All data below are fixed teaching examples. Outputs are calculated from the
controls, with the inputs and intermediate values returned for inspection.
"""
from __future__ import annotations

import json
import math
import numpy as np


# key, title, topics, control (label,min,max,step,default), metrics, computation
SPECS = [
    ("derivative", "变化率与导数", ["导数与变化率", "偏导数、梯度与链式法则"],
     ("输入 x", -2, 2, .1, 1), ("函数值", "解析导数", "差分导数"),
     "计算 f(x)=(x²+1)²，解析导数4x(x²+1)，中心差分步长0.0001；反馈展开链式法则两因子。"),
    ("conditional", "列联表与条件概率", ["条件概率与独立性"],
     ("A且B的计数", 0, 40, 1, 20), ("P(A|B)", "P(A)", "独立性偏差"),
     "100个等权样本，B共40、非B共60；A且非B固定30，改变A且B计数。实际比较P(A|B)与P(A)，以及P(A∩B)−P(A)P(B)。"),
    ("transpose", "矩阵转置与乘法", ["矩阵的行列与转置"],
     ("首行首元素", -3, 6, 1, 1), ("转置前元素和", "转置后元素和", "AAᵀ迹"),
     "构造A=[[x,2,3],[4,5,6]]，实际转置为3×2矩阵，计算AAᵀ并核对转置两次还原。"),
    ("variance", "均值与方差", ["均值、期望与方差"],
     ("第五个观测值", 0, 20, 1, 5), ("均值", "总体方差", "样本方差"),
     "对[1,2,3,4,x]逐项计算均值、除以n的经验总体方差与除以n−1的样本方差；五值等概率时均值也是期望。"),
    ("encoding", "类别编码与距离", ["类别特征的数值编码"],
     ("比较类别编号", 0, 2, 1, 1), ("整数编码距离", "独热编码距离", "独热向量和"),
     "三个无序类别红、绿、蓝使用编号0、1、2和单位向量；比较所选类别与红的欧氏距离，展示整数编号引入的顺序。"),
    ("squared-loss", "平方损失", ["平方损失与预测误差"],
     ("统一预测偏移", -2, 2, .1, 0), ("均方误差", "平均绝对误差", "最大绝对误差"),
     "真实值[1,2,4]、基础预测[1.2,1.8,3.5]；每个预测加x，逐行计算残差、平方和平均。"),
    ("cross-entropy", "二分类交叉熵", ["交叉熵损失"],
     ("正类 logit", -5, 5, .25, 0), ("正类概率", "正类标签损失", "logit梯度"),
     "真实标签为1，概率sigmoid(x)，损失−log(p)，对logit的梯度p−1；逐点实际计算，不拟合分类器。"),
    ("linear-model", "线性模型预测", ["线性模型的权重、偏置与预测"],
     ("第一个特征权重", -2, 3, .1, 1), ("第一个样本预测", "第二个样本预测", "均方误差"),
     "X=[[1,2],[2,1]]，w=[x,0.5]，偏置0.2，标签[2.2,2.7]；逐行计算Xw+b与MSE。"),
    ("batches", "训练数据分批读取", ["数据批次与训练数据读取"],
     ("批量大小", 1, 10, 1, 4), ("批次数", "最后一批大小", "访问样本数"),
     "固定10条编号样本按顺序切成小批量，保留最后不满的一批；反馈展示每一批的样本编号。"),
    ("initialization", "连乘梯度与初始化", ["梯度消失、梯度爆炸与参数初始化"],
     ("每层线性增益", .2, 2, .1, 1), ("十层输出", "输入梯度", "平方损失"),
     "输入1经过10层一维线性网络，每层权重x；实际前向连乘与反向链式连乘，目标为0。"),
    ("regularization", "权重衰减与随机失活", ["权重衰减与Dropout"],
     ("Dropout概率", 0, .8, .1, .5), ("失活后均值", "失活后方差", "衰减后权重"),
     "固定种子7对1000个值1应用inverted dropout，保留值除以1−p；另对权重2用学习率0.1、衰减系数p执行w←w−0.1*p*w，数据梯度设0。"),
    ("cross-validation", "K折验证", ["K折交叉验证"],
     ("折数 K", 2, 6, 1, 3), ("平均验证MSE", "折间MSE标准差", "验证样本总数"),
     "12个固定x与y=x²+0.1sin(3x)，按样本序号模K分折；每折只用其余样本拟合线性回归，再计算留出折MSE。"),
    ("data-split", "训练、验证与测试分工", ["训练集、验证集与测试集"],
     ("多项式阶数", 1, 4, 1, 2), ("训练MSE", "验证MSE", "预留测试样本数"),
     "固定14点y=x²+0.1sin(7x)，前8训练、随后4验证、末2预留作测试；只训练前8点并计算训练与验证MSE，测试仅显示数量。这是划分规则的教学案例。"),
    ("serialization", "参数保存与预测还原", ["网络模块、参数管理与模型保存"],
     ("线性层权重", -2, 3, .1, 1), ("保存前预测", "恢复后预测", "还原误差"),
     "线性层w=x、b=0.5，对输入2预测；将参数字典序列化为JSON并重新读取，比较恢复前后的输出。"),
    ("momentum", "小批量与动量更新", ["随机梯度、小批量与动量"],
     ("动量系数", 0, .9, .1, .5), ("普通SGD末权重", "动量末权重", "末步速度"),
     "固定三个小批量的数据梯度均值依次为1、−0.5、0.8，起始w=2、v=0、学习率0.1；逐步计算v=βv+g、w=w−0.1v，并与SGD比较。"),
    ("convolution", "共享卷积核", ["卷积核、局部连接与参数共享"],
     ("卷积核中心权重", -2, 2, .25, 1), ("输出和", "输出最大值", "共享参数数"),
     "对5×5的0至24数组，使用[[0,0,0],[0,x,0],[0,0,0]]执行无填充互相关，输出3×3；反馈显示输入、核与输出。"),
    ("stride-pool", "步幅与池化", ["填充、步幅、通道与池化"],
     ("滑动步幅", 1, 3, 1, 1), ("卷积输出边长", "输出和", "2×2最大池化和"),
     "单通道5×5数据0至24，零填充1，3×3均值核按所选步幅滑动；随后对结果用不重叠2×2窗口最大池化，末端不足窗口略过。"),
    ("cnn-shape", "卷积网络形状与参数", ["LeNet与深层卷积网络"],
     ("第二卷积层通道数", 4, 32, 4, 16), ("第二池化输出元素数", "卷积参数总数", "首层通道数"),
     "输入32×32×1，5×5卷积6通道，2×2池化，再5×5卷积x通道和2×2池化；按含偏置卷积公式逐层计算形状与参数。"),
    ("batchnorm-residual", "批量规范化与残差", ["批量规范化与残差连接"],
     ("输入平移量", -5, 5, .5, 0), ("规范化均值", "规范化方差", "残差输出均值"),
     "批次[1,2,3,4]+x，用当前批次总体方差和epsilon=1e−5规范化，γ=1、β=0；计算残差输出输入+规范化结果。"),
    ("tokens", "词元窗口与语言建模", ["序列、词元与语言建模"],
     ("上下文窗口词元数", 1, 4, 1, 2), ("训练样本对数", "首个输入词元数", "首个目标编号"),
     "词元编号序列[1,2,3,1,2,4,1,2]，滑动窗口生成输入词元与下一词元监督对；反馈完整展示配对。"),
    ("beam-search", "自回归解码与束搜索", ["编码器解码器、seq2seq与束搜索"],
     ("束宽", 1, 4, 1, 2), ("最优序列概率", "保留序列数", "扩展候选总数"),
     "固定首词A/B概率0.6/0.4；A后A/B为0.5/0.5，B后A/B为0.9/0.1。实际运行两步束搜索，以累计对数概率排序；展示候选和选择。"),
    ("gates", "LSTM与GRU记忆门", ["GRU与LSTM的门控记忆"],
     ("门的 logit", -4, 4, .5, 0), ("LSTM新记忆", "LSTM隐藏值", "GRU新隐藏值"),
     "门g=sigmoid(x)，旧记忆0.8、候选记忆−0.3、输出门0.7；LSTM取遗忘g输入1−g；GRU取更新g保留旧隐藏0.8，候选−0.3。"),
    ("distributed-gradient", "分片梯度同步", ["参数服务器与分布式训练", "多GPU数据并行与梯度同步"],
     ("第一分片样本数", 1, 9, 1, 5), ("按样本加权梯度", "分片均值简单平均", "同步更新后权重"),
     "10个样本梯度为1至10，前x个分在设备1，其余在设备2；计算两个局部均值，比较按样本数加权汇总与简单平均；w=1、学习率0.1。"),
    ("augmentation", "图像增广与微调", ["数据增广与迁移微调"],
     ("亮度缩放", .5, 1.5, .1, 1), ("增广后像素均值", "冻结特征输出", "更新后分类头权重"),
     "2×2图像[[0.1,0.2],[0.7,0.9]]先水平翻转再缩放并裁剪到[0,1]；冻结特征为像素均值，头w=1用目标1的平方损失执行一步学习率0.1更新。"),
    ("vision-compare", "固定视觉样本比较", ["视觉任务的实验比较"],
     ("分类阈值", .1, .9, .1, .5), ("均值特征准确率", "最大值特征准确率", "样本数"),
     "固定四个2×2图像与标签，分别以像素均值和最大像素为分数，在同一阈值下比较预测与标签；反馈完整提供图像和每行结果。"),
    ("boxes", "检测框与交并比", ["检测框、锚框与目标检测"],
     ("候选框水平偏移", -2, 2, .25, 0), ("交集面积", "并集面积", "IoU"),
     "真实框[0,0,2,2]，候选框[x,0,x+2,2]，按连续坐标计算面积和IoU；框平移时比较重叠变化。"),
    ("segmentation", "分割与转置卷积", ["语义分割、转置卷积与全卷积网络"],
     ("分割阈值", .1, .9, .1, .5), ("预测前景像素数", "像素准确率", "前景IoU"),
     "2×2分数[[0.1,0.8],[0.6,0.3]]经步幅2、2×2全1核的转置卷积得到4×4；与固定4×4前景掩码逐像素比较。"),
    ("embeddings", "词向量与负采样", ["词嵌入、负采样与子词表示"],
     ("中心词第一维", -2, 2, .25, 1), ("正例点积", "负例点积", "负采样损失"),
     "中心词向量[x,0.5]，正例[1,0]、负例[−1,1]；计算−log sigmoid(正点积)−log sigmoid(负点积的相反数)，另显示两个子词向量均值。"),
    ("preference", "偏好奖励与策略约束", ["偏好数据、奖励与RLHF"],
     ("优选答案奖励差", -3, 3, .25, 1), ("偏好模型概率", "成对偏好损失", "KL约束策略概率"),
     "固定偏好A优于B、奖励差x；Bradley–Terry概率sigmoid(x)，成对损失−log概率；均匀参考策略、KL系数2时最优两动作策略P(A)=sigmoid(x/2)。"),
    ("autoencoder", "线性编码与重建", ["自编码器与表示学习", "主成分分析与降维重建"],
     ("瓶颈维数", 1, 3, 1, 1), ("重建MSE", "保留能量比例", "编码维数"),
     "固定4×3矩阵居中后SVD，用前k个右奇异向量编码再解码，计算重建误差与保留的平方奇异值比例。"),
    ("graph-message", "邻域聚合与图卷积", ["消息传递、邻域聚合与图卷积", "图网络的过平滑与过压缩", "图数据、节点边任务与图级读出"],
     ("聚合层数", 1, 12, 1, 2), ("节点特征方差", "图均值读出", "首尾节点差"),
     "四节点路径图加自环，初始标量特征[1,0,0,−1]；每层实际按度归一化邻域均值更新。展示每层节点值与图均值读出，观察重复聚合的平滑。"),
    ("contrastive", "对比表示与温度", ["自监督任务与对比表示"],
     ("温度", .1, 2, .1, .5), ("正例概率", "InfoNCE损失", "正负相似度差"),
     "锚点[1,0]、正例[0.8,0.6]、负例[0,1]和[−1,0]均为单位向量；按余弦相似度除温度后softmax，计算正例负对数概率。"),
    ("tool-recovery", "工具参数校验与恢复", ["工具选择、参数校验与执行恢复"],
     ("注入的暂时失败次数", 0, 3, 1, 1), ("工具调用次数", "最终计算结果", "实际完成次数"),
     "固定请求sum(values=[2,3,5])，先校验工具名和数值数组；前x次调用注入暂时连接错误，保留同一操作身份后重试，实际计算一次和10。"),
    ("context-packing", "上下文示例选择", ["上下文学习与推理增强", "技能加载、子任务隔离与上下文管理"],
     ("上下文词元预算", 40, 200, 20, 100), ("载入示例数", "使用词元数", "剩余词元数"),
     "固定任务说明40词元，三条已按相关性排序的示例分别30、50、60词元；按预算逐条装入完整示例，独立子任务使用新上下文字典，展示实际装入和隔离结果。"),
    ("preprocessing", "预处理拟合与泄漏", ["预处理参数的拟合与数据泄漏"],
     ("验证样本偏移", 0, 10, .5, 3), ("训练均值", "混合均值", "验证标准化值差"),
     "训练[0,1,2,3]、验证[4+x,5+x]，分别用训练统计量与全体统计量标准化验证数据，比较均值和首条变换差；不据此推断分数一定变好。"),
    ("tensor-shape", "张量形状与元素", ["标量、向量与张量形状"],
     ("批次样本数", 1, 8, 1, 2), ("张量阶数", "元素总数", "展平后的长度"),
     "将0至6n−1的整数重排为(n,2,3)，再展平；实际展示形状、标量索引和一个样本，重排不改变元素总数。"),
    ("dot-product", "点积与加权和", ["向量点积与加权和"],
     ("第一项权重", -2, 3, .25, 1), ("第一项贡献", "第二项贡献", "点积"),
     "输入向量[2,3]、权重[x,0.5]，计算逐项乘积及其和；展示负权重、零权重与正权重的作用。"),
    ("matrix-vector", "矩阵作用于向量", ["矩阵向量乘法"],
     ("向量第一项", -2, 3, .25, 1), ("输出第一项", "输出第二项", "输出第三项"),
     "固定3×2矩阵[[1,2],[0,−1],[2,1]]乘向量[x,1]，逐行计算点积，得到长度3的输出。"),
    ("imputation", "训练均值填补缺失值", ["缺失值与数据预处理"],
     ("第三个训练观测值", 0, 10, .5, 4), ("训练非缺失均值", "填补后训练均值", "验证缺失值填补结果"),
     "训练[1,缺失,3,x]，验证[缺失,100]；仅用训练非缺失值拟合均值，应用于两组缺失位置，保留验证中的100。"),
    ("softmax", "多类分数与概率", ["softmax与多类分类概率"],
     ("第一类 logit", -4, 4, .5, 1), ("第一类概率", "第二类概率", "第三类概率"),
     "对三个给定logit[x,0,−1]减最大值后取指数并归一化，展示三类概率和及预测类别；没有二分类阈值。"),
    ("linear-training", "实际线性回归训练", ["线性回归的实现与训练循环", "小批量随机梯度下降"],
     ("训练轮数", 1, 20, 1, 5), ("末轮权重", "末轮偏置", "全训练集MSE"),
     "固定X=[−1,0,1,2]、y=2X+1；w=b=0、学习率0.05、顺序两样本小批量。每批按MSE梯度更新，记录各轮参数与全训练集误差。"),
    ("mlp", "非线性隐藏层与反向传播", ["隐藏层、非线性激活与多层感知机", "计算图、前向传播与反向传播"],
     ("隐藏层第一权重", -2, 2, .25, 1), ("网络输出", "平方损失的一半", "第一权重梯度"),
     "输入[1,2]，隐藏层tanh([w*1+0.5*2,−0.5*1+1*2])，输出权重[1,−1]、目标0.2；实际计算前向值和链式法则梯度，并用中心差分核对。"),
    ("quadratic-descent", "二次目标的梯度下降", ["优化目标、凸性与梯度下降"],
     ("学习率", .05, 1.25, .05, .25), ("末步参数", "末步目标值", "末步梯度"),
     "凸函数f(w)=(w−3)²，从w=0按w←w−η*2(w−3)更新10步；展示完整轨迹，比较稳定、振荡和发散。"),
    ("adam", "Adam的一阶与二阶矩", ["自适应优化器与Adam"],
     ("学习率", .01, .2, .01, .1), ("Adam末权重", "SGD末权重", "末步校正二阶矩"),
     "固定梯度序列[1,−0.5,0.8]，w=2；Adam使用β1=0.9、β2=0.999、epsilon=1e−8及偏差校正，并与相同梯度的SGD比较。"),
    ("lr-schedule", "学习率调度与损失轨迹", ["学习率调度与训练诊断"],
     ("每步学习率衰减因子", .5, 1, .05, .9), ("最后学习率", "末步目标值", "固定学习率目标值"),
     "f(w)=(w−3)²、w=0，共10步；调度ηt=0.2*γ^t，与固定0.2对照，记录每步实际损失。"),
    ("recurrent", "循环状态与时间梯度", ["循环状态与通过时间反向传播"],
     ("循环权重", -1.5, 1.5, .1, .5), ("最终隐藏状态", "损失的一半平方", "循环权重梯度"),
     "序列[0.2,−0.1,0.3]、h0=0，ht=tanh(w*h前+x_t)，目标0.5；实际递推dh/dw=(1−h²)*(h前+w*dh前/dw)，与中心差分核对。"),
    ("attention", "查询与加权读取", ["查询、键、值与注意力评分"],
     ("查询第一维", -2, 2, .25, 1), ("第一项权重", "输出第一维", "输出第二维"),
     "Q=[x,1]，K=[[1,0],[0,1],[1,1]]，V=[[1,0],[0,2],[2,1]]；计算softmax(QKᵀ/√2)V，完整展示分数、权重和加权输出。"),
    ("multihead", "两个注意力头与位置", ["多头、自注意力与位置编码"],
     ("位置编码系数", 0, 1, .1, .5), ("头一读取值", "头二读取值", "两头输出之差"),
     "三个二维词元[[1,0],[0,1],[1,1]]加系数乘位置编码[sin位置,cos位置]；两个头分别取一列为Q/K/V，对末词实际计算标量点积注意力，最后拼接。"),
    ("causal-attention", "因果掩码与未来信息", ["Transformer结构与因果掩码", "BERT预训练与上下文表示"],
     ("第三个词元数值", -2, 4, .5, 2), ("因果读取结果", "双向读取结果", "因果未来权重"),
     "三个标量词元[1,0.5,x]直接作为Q/K/V；在第二个位置计算注意力，比较只允许前两项的因果掩码与三项可见的双向读取，展示权重；不执行完整Transformer或BERT训练。"),
    ("text-classification", "文本特征与分类更新", ["情感分类、自然语言推断与微调"],
     ("分类头训练步数", 0, 20, 1, 5), ("好评概率", "差评概率", "两样本交叉熵"),
     "两句教学文本‘好’和‘差’用固定特征1和−1表示，标签1和0；固定编码器，分类头权重从0按学习率0.2实际更新二分类交叉熵。只演示情感分类头，不等同自然语言推断。"),
    ("perplexity", "词元概率与困惑度", ["自回归生成、困惑度与解码策略"],
     ("解码温度", .2, 2, .2, 1), ("真实词元概率", "三词元平均负对数似然", "困惑度"),
     "固定三个预测位置logit分别为[2,0]、[0,1]、[1,−1]，真实目标[0,1,1]；除温度后softmax，计算三个目标概率、平均负对数似然及exp得到困惑度，并展示贪心结果。"),
    ("token-budget", "分词长度与训练预算", ["大模型预训练、分词与规模规律"],
     ("每批序列数", 1, 8, 1, 2), ("字符词元数", "合并后词元数", "每步处理词元数"),
     "固定文本‘机器学习机器学习’，按字符分词，再将每个‘机器’与‘学习’分别合并；每序列补齐8个位置，计算每批位置预算。只比较明确分词和预算，不模拟经验规模规律或预测模型质量。"),
    ("tiny-language-training", "小型自回归预测训练", ["小型GPT的训练与生成实验"],
     ("训练步数", 0, 30, 1, 10), ("训练交叉熵", "A后B概率", "B后A概率"),
     "序列A,B,A,B,A,B；用2×2可训练转移logit预测下一词，零初始化、全批学习率0.5，实际更新softmax交叉熵并贪心生成四词。它是小型自回归基线，未实现GPT的Transformer层。"),
    ("low-rank", "冻结权重与低秩适配", ["指令微调与参数高效微调"],
     ("适配矩阵秩", 1, 3, 1, 1), ("低秩可训练参数数", "全量参数数", "增量重建MSE"),
     "冻结4×3零权重，目标增量为固定4×3矩阵；SVD取前r项构造B*A，比较参数r*(4+3)与全量12、计算重建误差。高秩不一定节省参数；这是低秩适配线性代数，不冒称完成大模型微调。"),
    ("dpo", "DPO偏好对的目标", ["DPO与策略优化方法的比较"],
     ("优选与劣选的对数比差", -3, 3, .25, 1), ("DPO损失", "对差值的梯度", "隐式奖励差"),
     "固定一对偏好回答，x=log(π优/πref优)−log(π劣/πref劣)，β=0.2；计算−log sigmoid(βx)及梯度−β sigmoid(−βx)。与奖励模型训练的差别由正文说明，此计算不运行在线RL。"),
    ("retrieval-ranking", "固定文档检索与排序", ["检索增强生成的证据链", "文档切分、向量索引与召回", "重排序与检索质量评价"],
     ("返回文档数 K", 1, 4, 1, 2), ("召回率", "精确率", "重排后首条相关"),
     "固定四段资料：训练拟合、测试封存、验证选型、数据存储；查询‘用什么选择模型’，相关集合为训练与验证两段。初排固定为测试、验证、存储、训练；在前K段内按固定相关性分数重排，实际计算检索指标并展示原文及编号。"),
    ("evidence-ablation", "回答主张与证据覆盖", ["回答忠实性与RAG消融实验"],
     ("取用证据段数", 0, 3, 1, 2), ("有直接证据的主张数", "待核主张数", "证据覆盖比例"),
     "三条固定主张分别为训练拟合参数、验证选模型、测试最终评价，三段原文按此顺序提供；逐条按预先标明的主张/证据对应核对。它是有限案例的直接支持检查，不充当任意文本的自动事实评价。"),
    ("agent-state", "工具协作与任务状态", ["智能体状态、规划与ReAct", "多智能体分工、共享信息与协作", "智能体任务评价与过程治理", "MCP工具接口与调用协议", "个性化学习智能体综合项目"],
     ("注入的暂时工具失败次数", 0, 3, 1, 1), ("工具调用次数", "完成的计算结果", "验证通过次数"),
     "教学状态机完成sum([2,3,5])：规划者生成带id/name/arguments的调用，执行者校验后计算，核对者以逐项累加复算。前x次注入连接失败，同id恢复；完整展示共享消息和状态轨迹。是本地协议与协作案例，不连接MCP服务器或调用真实多智能体模型。"),
    ("code-cycle", "修改与断言验证", ["代码智能体的修改验证循环"],
     ("初稿偏差", -2, 2, 1, 0), ("修订前通过数", "修订后通过数", "实际修订次数"),
     "固定候选函数f(n)=n+偏差，要求返回n；对0、2、−1运行三条断言。失败时由固定规则移除偏差后重跑，保留前后输出。演示修改验证循环，不调用代码生成模型。"),
]

TOPIC_LABS = {topic.casefold(): f"concept-{key}" for key, _, topics, *_ in SPECS for topic in topics}
BY_ID = {f"concept-{row[0]}": row for row in SPECS}


def template_specs():
    for key, title, topics, control, metrics, calculation in SPECS:
        label, low, high, step, default = control
        yield {
            "template_id": f"concept-{key}", "template_version": "1.0.0", "title": title,
            "summary": calculation, "skill_target": "比较参数改变前后的计算过程，并解释结果。",
            "applicability": "、".join(topics), "sweep_parameter_key": "value",
            "parameters": [{"key": "value", "label": label, "kind": "integer" if isinstance(step, int) else "float",
                            "minimum": low, "maximum": high, "step": step, "default": default,
                            "description": calculation}],
            "metrics": [{"key": f"m{i}", "label": name, "higher_is_better": None, "acceptance_threshold": None}
                        for i, name in enumerate(metrics)],
            "public_scenarios": (calculation,), "checker_version": f"lab.concept-{key}.v1",
            "hidden_categories": ("finite_computation",),
            "static_fallback": "阅读给定输入与计算规则，恢复运行后再比较输出。",
        }


def execution_info(template_id):
    row = BY_ID[template_id]
    return {"mode": "synthetic_data_computation", "label": "教学样例计算",
            "description": row[5], "capabilities": row[5]}


def _softmax(logits):
    logits = np.asarray(logits, dtype=float)
    weights = np.exp(logits - logits.max(axis=-1, keepdims=True))
    return weights / weights.sum(axis=-1, keepdims=True)


def evaluate(template_id, parameters):
    key = template_id.removeprefix("concept-")
    x = parameters["value"]
    details = {}
    if key == "derivative":
        f = lambda z: (z*z + 1)**2
        values = (f(x), 4*x*(x*x+1), (f(x+1e-4)-f(x-1e-4))/2e-4)
        details = {"外层导数": 2*(x*x+1), "内层导数": 2*x}
    elif key == "conditional":
        joint, a, b = x/100, (x+30)/100, .4
        values = (x/40, a, joint-a*b)
        details = {"表格行A/非A，列B/非B": [[x,30],[40-x,30]], "总数": 100}
    elif key == "transpose":
        a = np.array([[x,2,3],[4,5,6]])
        values = (a.sum(), a.T.sum(), np.trace(a @ a.T))
        details = {"A": a.tolist(), "转置": a.T.tolist(), "AAᵀ": (a @ a.T).tolist()}
    elif key == "variance":
        a = np.array([1,2,3,4,x]); values = (a.mean(), a.var(), a.var(ddof=1))
        details = {"观测值": a.tolist(), "离均差平方": ((a-a.mean())**2).tolist()}
    elif key == "encoding":
        a = np.eye(3)[int(x)]; values = (abs(x), np.linalg.norm(a-np.eye(3)[0]), a.sum())
        details = {"类别": ["红","绿","蓝"][int(x)], "独热向量": a.tolist()}
    elif key == "squared-loss":
        target = np.array([1,2,4]); prediction = np.array([1.2,1.8,3.5])+x
        error = prediction-target; values = ((error**2).mean(), abs(error).mean(), abs(error).max())
        details = {"标签": target.tolist(), "预测": prediction.tolist(), "残差": error.tolist()}
    elif key == "cross-entropy":
        p = 1/(1+math.exp(-x)); values = (p, -math.log(p), p-1)
        details = {"标签": 1, "logit": x}
    elif key == "linear-model":
        a = np.array([[1,2],[2,1]]); pred = a @ np.array([x,.5])+.2
        values = (pred[0], pred[1], ((pred-[2.2,2.7])**2).mean())
        details = {"特征": a.tolist(), "权重": [x,.5], "偏置": .2, "预测": pred.tolist()}
    elif key == "batches":
        batches = [list(range(i,min(i+int(x),10))) for i in range(0,10,int(x))]
        values = (len(batches), len(batches[-1]), sum(map(len,batches))); details = {"各批编号": batches}
    elif key == "initialization":
        value = 1.; layers = []
        for _ in range(10): value *= x; layers.append(value)
        values = (value, x**10, value**2); details = {"各层输出": layers, "各层权重": x}
    elif key == "regularization":
        a = (np.random.default_rng(7).random(1000) >= x).astype(float)/(1-x)
        values = (a.mean(), a.var(), 2-.1*x*2)
        details = {"保留个数": int(np.count_nonzero(a)), "保留值": 1/(1-x), "前十个输出": a[:10].tolist()}
    elif key == "cross-validation":
        z = np.linspace(-1,1,12); y = z*z+.1*np.sin(3*z); errors=[]; fold_rows=[]
        for fold in range(int(x)):
            mask = np.arange(12)%int(x) == fold
            coeff = np.polyfit(z[~mask],y[~mask],1)
            errors.append(float(np.mean((np.polyval(coeff,z[mask])-y[mask])**2)))
            fold_rows.append(np.where(mask)[0].tolist())
        values = (np.mean(errors), np.std(errors), sum(map(len,fold_rows)))
        details = {"验证行": fold_rows, "每折MSE": errors}
    elif key == "data-split":
        z=np.linspace(-1,1,14); y=z*z+.1*np.sin(7*z); c=np.polyfit(z[:8],y[:8],int(x))
        values=(np.mean((np.polyval(c,z[:8])-y[:8])**2),np.mean((np.polyval(c,z[8:12])-y[8:12])**2),2)
        details={"训练行":list(range(8)),"验证行":list(range(8,12)),"预留测试行":[12,13],"系数":c.tolist()}
    elif key == "serialization":
        saved=json.dumps({"weight":x,"bias":.5}); restored=json.loads(saved)
        a=2*x+.5; b=2*restored["weight"]+restored["bias"]; values=(a,b,abs(a-b)); details={"保存内容":saved}
    elif key == "momentum":
        w=2.; v=0.; states=[]
        for g in [1,-.5,.8]: v=x*v+g; w-=.1*v; states.append({"梯度":g,"速度":v,"权重":w})
        values=(2-.1*sum([1,-.5,.8]),w,v); details={"逐步更新":states}
    elif key in {"convolution","stride-pool"}:
        a=np.arange(25).reshape(5,5); kernel=np.zeros((3,3)); kernel[1,1]=x
        stride=1
        if key == "stride-pool": a=np.pad(a,1); kernel=np.ones((3,3))/9; stride=int(x)
        out=np.array([[np.sum(a[i:i+3,j:j+3]*kernel) for j in range(0,a.shape[1]-2,stride)]
                      for i in range(0,a.shape[0]-2,stride)])
        if key == "convolution": values=(out.sum(),out.max(),9)
        else:
            pooled=[out[i:i+2,j:j+2].max() for i in range(0,out.shape[0]-1,2) for j in range(0,out.shape[1]-1,2)]
            values=(out.shape[0],out.sum(),sum(pooled))
        details={"输入":a.tolist(),"核":kernel.tolist(),"输出":out.tolist()}
    elif key == "cnn-shape":
        values=(25*x,6*(25+1)+x*(6*25+1),6)
        details={"逐层形状":[[1,32,32],[6,28,28],[6,14,14],[int(x),10,10],[int(x),5,5]]}
    elif key == "batchnorm-residual":
        a=np.array([1,2,3,4])+x; b=(a-a.mean())/math.sqrt(a.var()+1e-5)
        values=(b.mean(),b.var(),(a+b).mean()); details={"输入":a.tolist(),"规范化":b.tolist(),"残差输出":(a+b).tolist()}
    elif key == "tokens":
        tokens=[1,2,3,1,2,4,1,2]; n=int(x); pairs=[{"输入":tokens[i:i+n],"目标":tokens[i+n]} for i in range(len(tokens)-n)]
        values=(len(pairs),n,pairs[0]["目标"]); details={"词元序列":tokens,"监督对":pairs}
    elif key == "beam-search":
        beams=[("",1.)]; expanded=0
        for _ in range(2):
            candidates=[]
            for prefix,probability in beams:
                probs=(.6,.4) if not prefix else (.5,.5) if prefix[-1]=="A" else (.9,.1)
                candidates += [(prefix+token,probability*p) for token,p in zip("AB",probs)]
            expanded+=len(candidates); beams=sorted(candidates,key=lambda item:(-item[1],item[0]))[:int(x)]
        values=(beams[0][1],len(beams),expanded); details={"最终序列与概率":beams}
    elif key == "gates":
        g=1/(1+math.exp(-x)); c=g*.8+(1-g)*(-.3)
        values=(c,.7*math.tanh(c),g*.8+(1-g)*(-.3)); details={"遗忘或更新门":g,"输入门":1-g,"输出门":.7}
    elif key == "distributed-gradient":
        a=np.arange(1,11,dtype=float); n=int(x); left=a[:n].mean(); right=a[n:].mean(); weighted=(n*left+(10-n)*right)/10
        values=(weighted,(left+right)/2,1-.1*weighted); details={"分片1":a[:n].tolist(),"分片2":a[n:].tolist(),"局部均值":[left,right]}
    elif key == "augmentation":
        a=np.array([[.1,.2],[.7,.9]]); b=np.clip(np.fliplr(a)*x,0,1); feature=b.mean(); w=1-.1*2*(feature-1)*feature
        values=(b.mean(),feature,w); details={"原图":a.tolist(),"增广图":b.tolist(),"冻结特征":feature}
    elif key == "vision-compare":
        a=np.array([[[0,0],[0,1]],[[1,1],[0,0]],[[1,1],[1,0]],[[0,0],[0,0]]]); target=np.array([0,1,1,0]); mean=a.mean(axis=(1,2)); maximum=a.max(axis=(1,2))
        values=(np.mean((mean>=x)==target),np.mean((maximum>=x)==target),4)
        details={"图像":a.tolist(),"标签":target.tolist(),"均值分数":mean.tolist(),"最大值分数":maximum.tolist()}
    elif key == "boxes":
        intersection=max(0,min(2,x+2)-max(0,x))*2; union=8-intersection
        values=(intersection,union,intersection/union); details={"真实框":[0,0,2,2],"候选框":[x,0,x+2,2]}
    elif key == "segmentation":
        coarse=np.array([[.1,.8],[.6,.3]]); expanded=np.kron(coarse,np.ones((2,2))); target=np.array([[0,0,1,1],[0,0,1,1],[1,1,0,0],[1,0,0,0]],dtype=bool); pred=expanded>=x
        values=(pred.sum(),np.mean(pred==target),np.sum(pred & target)/np.sum(pred | target))
        details={"转置卷积输入":coarse.tolist(),"输出":expanded.tolist(),"目标掩码":target.astype(int).tolist(),"预测掩码":pred.astype(int).tolist()}
    elif key == "embeddings":
        pos=x; neg=-x+.5; loss=np.logaddexp(0,-pos)+np.logaddexp(0,neg)
        values=(pos,neg,loss); details={"中心词":[x,.5],"正例":[1,0],"负例":[-1,1],"子词均值":np.mean([[.2,.4],[.6,.8]],axis=0).tolist()}
    elif key == "preference":
        p=1/(1+math.exp(-x)); values=(p,-math.log(p),1/(1+math.exp(-x/2))); details={"偏好":"A优于B","奖励差":x,"KL系数":2}
    elif key == "autoencoder":
        a=np.array([[1,2,0],[2,1,1],[3,4,2],[4,2,3]],dtype=float); mean=a.mean(axis=0); centered=a-mean; _,s,v=np.linalg.svd(centered,full_matrices=False); n=int(x); code=centered@v[:n].T; decoded=code@v[:n]+mean
        values=(np.mean((decoded-a)**2),sum(s[:n]**2)/sum(s**2),n); details={"输入":a.tolist(),"编码":code.tolist(),"重建":decoded.tolist()}
    elif key == "graph-message":
        a=np.eye(4)+np.diag(np.ones(3),1)+np.diag(np.ones(3),-1); p=a/a.sum(axis=1,keepdims=True); h=np.array([1.,0,0,-1]); states=[h.tolist()]
        for _ in range(int(x)): h=p@h; states.append(h.tolist())
        values=(h.var(),h.mean(),abs(h[0]-h[-1])); details={"邻接矩阵":a.tolist(),"每层节点特征":states}
    elif key == "contrastive":
        similarities=np.array([.8,0,-1]); logits=similarities/x; probabilities=np.exp(logits-logits.max()); probabilities/=probabilities.sum()
        values=(probabilities[0],-math.log(probabilities[0]),.8); details={"相似度":similarities.tolist(),"候选概率":probabilities.tolist()}
    elif key == "tool-recovery":
        request={"tool":"sum","values":[2,3,5]}; attempts=[]; result=None
        assert request["tool"] == "sum" and all(isinstance(v,(int,float)) for v in request["values"])
        for attempt in range(int(x)+1):
            if attempt<int(x): attempts.append("暂时连接失败")
            else: result=sum(request["values"]); attempts.append("计算完成")
        values=(len(attempts),result,1); details={"输入":request,"同一操作的各次结果":attempts}
    elif key == "context-packing":
        context={"task_tokens":40,"examples":[]}; used=40
        for name,size in [("定义示例",30),("边界示例",50),("迁移示例",60)]:
            if used+size<=x: context["examples"].append(name); used+=size
        other={"task_tokens":40,"examples":[]}; values=(len(context["examples"]),used,x-used)
        details={"本任务上下文":context,"新子任务上下文":other}
    elif key == "preprocessing":
        train=np.array([0,1,2,3]); valid=np.array([4,5])+x; all_rows=np.r_[train,valid]; correct=(valid-train.mean())/train.std(); leaked=(valid-all_rows.mean())/all_rows.std()
        values=(train.mean(),all_rows.mean(),correct[0]-leaked[0]); details={"训练":train.tolist(),"验证":valid.tolist(),"仅训练拟合的变换":correct.tolist(),"混合拟合的变换":leaked.tolist()}
    elif key == "tensor-shape":
        tensor = np.arange(6 * int(x)).reshape(int(x), 2, 3)
        values = (tensor.ndim, tensor.size, len(tensor.reshape(-1)))
        details = {"形状": list(tensor.shape), "第一个样本": tensor[0].tolist(), "标量索引[0,0,0]": int(tensor[0,0,0])}
    elif key == "dot-product":
        products = np.array([2,3]) * [x,.5]
        values = (*products, products.sum())
        details = {"输入": [2,3], "权重": [x,.5], "逐项乘积": products.tolist()}
    elif key == "matrix-vector":
        matrix = np.array([[1,2],[0,-1],[2,1]])
        values = matrix @ [x,1]
        details = {"矩阵": matrix.tolist(), "输入": [x,1], "各行点积": values.tolist()}
    elif key == "imputation":
        mean = (1+3+x)/3
        filled = [1,mean,3,x]
        values = (mean, np.mean(filled), mean)
        details = {"训练原值": [1,None,3,x], "填补后训练": filled, "填补后验证": [mean,100]}
    elif key == "softmax":
        probabilities = _softmax([x,0,-1]); values = probabilities
        details = {"logit": [x,0,-1], "概率和": float(probabilities.sum()), "预测类别索引": int(probabilities.argmax())}
    elif key == "linear-training":
        inputs = np.array([-1.,0,1,2]); targets = 2*inputs+1
        w = b = 0.; history = []
        for epoch in range(int(x)):
            for start in (0,2):
                batch = inputs[start:start+2]; residual = w*batch+b-targets[start:start+2]
                dw, db = 2*np.mean(residual*batch), 2*residual.mean()
                w -= .05*dw; b -= .05*db
            mse = np.mean((w*inputs+b-targets)**2)
            history.append({"轮次": epoch+1, "权重": w, "偏置": b, "MSE": mse})
        values = (w,b,mse); details = {"输入": inputs.tolist(), "目标": targets.tolist(), "训练记录": history}
    elif key == "mlp":
        def forward(weight):
            hidden = np.tanh([weight+1,1.5]); output = hidden[0]-hidden[1]
            return hidden, output, .5*(output-.2)**2
        hidden, output, loss = forward(x)
        gradient = (output-.2)*(1-hidden[0]**2)
        numerical = (forward(x+1e-5)[2]-forward(x-1e-5)[2])/2e-5
        values = (output,loss,gradient)
        details = {"隐藏层": hidden.tolist(), "中心差分梯度": numerical, "链式梯度": gradient}
    elif key == "quadratic-descent":
        w=0.; history=[w]
        for _ in range(10):
            w -= x*2*(w-3); history.append(w)
        values=(w,(w-3)**2,2*(w-3)); details={"参数轨迹": history}
    elif key == "adam":
        w=sgd=2.; m=v=0.; history=[]
        for step,g in enumerate([1.,-.5,.8],1):
            m=.9*m+.1*g; v=.999*v+.001*g*g
            corrected_m=m/(1-.9**step); corrected_v=v/(1-.999**step)
            w -= x*corrected_m/(math.sqrt(corrected_v)+1e-8); sgd -= x*g
            history.append({"步":step,"梯度":g,"一阶矩":m,"二阶矩":v,"校正一阶矩":corrected_m,
                            "校正二阶矩":corrected_v,"Adam权重":w,"SGD权重":sgd})
        values=(w,sgd,corrected_v); details={"更新":history}
    elif key == "lr-schedule":
        w=fixed=0.; history=[]
        for step in range(10):
            rate=.2*x**step; w-=rate*2*(w-3); fixed-=.2*2*(fixed-3)
            history.append({"步":step+1,"学习率":rate,"调度损失":(w-3)**2,"固定损失":(fixed-3)**2})
        values=(rate,(w-3)**2,(fixed-3)**2); details={"训练轨迹":history}
    elif key == "recurrent":
        def forward(weight):
            h=dh=0.; history=[]
            for token in [.2,-.1,.3]:
                previous=h; h=math.tanh(weight*previous+token)
                dh=(1-h*h)*(previous+weight*dh); history.append(h)
            return h,.5*(h-.5)**2,(h-.5)*dh,history
        h,loss,gradient,history=forward(x)
        values=(h,loss,gradient)
        details={"隐藏轨迹":history,"中心差分梯度":(forward(x+1e-5)[1]-forward(x-1e-5)[1])/2e-5}
    elif key == "attention":
        query=np.array([x,1]); keys=np.array([[1,0],[0,1],[1,1]]); vectors=np.array([[1,0],[0,2],[2,1]])
        scores=query@keys.T/math.sqrt(2); weights=_softmax(scores); output=weights@vectors
        values=(weights[0],*output); details={"分数":scores.tolist(),"权重":weights.tolist(),"V":vectors.tolist(),"输出":output.tolist()}
    elif key == "multihead":
        positions=np.arange(3); vectors=np.array([[1.,0],[0,1],[1,1]])+x*np.column_stack([np.sin(positions),np.cos(positions)])
        weights=[_softmax(vectors[-1,i]*vectors[:,i]) for i in range(2)]
        outputs=[weights[i]@vectors[:,i] for i in range(2)]
        values=(*outputs,outputs[0]-outputs[1]); details={"加入位置后的词元":vectors.tolist(),"两头权重":[w.tolist() for w in weights],"拼接输出":outputs}
    elif key == "causal-attention":
        tokens=np.array([1.,.5,x]); full=_softmax(.5*tokens); causal=np.r_[_softmax(.5*tokens[:2]),0.]
        values=(causal@tokens,full@tokens,causal[-1]); details={"词元":tokens.tolist(),"因果权重":causal.tolist(),"双向权重":full.tolist()}
    elif key == "text-classification":
        features=np.array([1.,-1]); targets=np.array([1.,0]); w=0.
        for _ in range(int(x)):
            probabilities=1/(1+np.exp(-w*features)); w-=.2*np.mean((probabilities-targets)*features)
        logits=w*features; probabilities=1/(1+np.exp(-logits)); loss=np.mean(np.logaddexp(0,logits)-targets*logits)
        values=(*probabilities,loss); details={"文本":["好","差"],"固定特征":features.tolist(),"目标":targets.tolist(),"分类头权重":w}
    elif key == "perplexity":
        logits=np.array([[2.,0],[0,1],[1,-1]])/x; probabilities=_softmax(logits); correct=probabilities[np.arange(3),[0,1,1]]
        loss=-np.log(correct).mean(); values=(correct[0],loss,math.exp(loss))
        details={"各位置概率":probabilities.tolist(),"真实目标":[0,1,1],"目标概率":correct.tolist(),"贪心类别":probabilities.argmax(axis=1).tolist()}
    elif key == "token-budget":
        characters=list("机器学习机器学习"); merged=["机器","学习","机器","学习"]
        values=(len(characters),len(merged),8*int(x)); details={"字符词元":characters,"合并词元":merged,"每序列位置":8,"批次序列数":int(x)}
    elif key == "tiny-language-training":
        sequence=np.array([0,1,0,1,0,1]); inputs=sequence[:-1]; targets=sequence[1:]; logits=np.zeros((2,2)); history=[]
        for _ in range(int(x)):
            probabilities=_softmax(logits[inputs]); derivative=probabilities.copy(); derivative[np.arange(5),targets]-=1
            gradient=np.zeros((2,2)); np.add.at(gradient,inputs,derivative/5); logits-=.5*gradient
            history.append(float(-np.log(_softmax(logits)[inputs,targets]).mean()))
        probabilities=_softmax(logits); generated=[0]
        for _ in range(4): generated.append(int(probabilities[generated[-1]].argmax()))
        values=(-np.log(probabilities[inputs,targets]).mean(),probabilities[0,1],probabilities[1,0])
        details={"训练序列":sequence.tolist(),"logit":logits.tolist(),"损失轨迹":history,"从A贪心生成":["AB"[i] for i in generated]}
    elif key == "low-rank":
        target=np.array([[1.,2,0],[0,1,3],[2,0,1],[1,1,1]]); u,s,v=np.linalg.svd(target,full_matrices=False); rank=int(x)
        left=u[:,:rank]*s[:rank]; right=v[:rank]; reconstructed=left@right
        values=(rank*7,12,np.mean((reconstructed-target)**2)); details={"目标增量":target.tolist(),"B":left.tolist(),"A":right.tolist(),"BA":reconstructed.tolist()}
    elif key == "dpo":
        z=.2*x; values=(np.logaddexp(0,-z),-.2/(1+math.exp(z)),z)
        details={"beta":.2,"策略与参考的对数比差":x,"偏好方向":"优选回答优于劣选回答"}
    elif key == "retrieval-ranking":
        docs=[{"id":"train","text":"模型参数使用训练数据拟合。","score":.8},
              {"id":"test","text":"测试数据用于冻结方案后的最终评价。","score":.2},
              {"id":"validation","text":"验证数据用于比较候选并选择模型。","score":1.},
              {"id":"storage","text":"文件可存储为表格。","score":.1}]
        candidates=[docs[i] for i in [1,2,3,0]][:int(x)]; reranked=sorted(candidates,key=lambda d:-d['score'])
        relevant={"train","validation"}; hits=sum(d['id'] in relevant for d in candidates)
        values=(hits/2,hits/int(x),int(reranked[0]['id'] in relevant)); details={"相关文档集合":sorted(relevant),"初排返回":candidates,"重排结果":reranked}
    elif key == "evidence-ablation":
        claims=["训练拟合参数","验证选择模型","测试最终评价"]; evidence=claims[:int(x)]
        values=(len(evidence),len(claims)-len(evidence),len(evidence)/3)
        details={"给定证据":evidence,"逐条核对":[{"主张":c,"直接支持":c in evidence} for c in claims]}
    elif key == "agent-state":
        request={"id":"sum-demo-1","name":"sum","arguments":{"values":[2,3,5]}}
        messages=[{"角色":"规划","调用":request}]; result=None
        for attempt in range(int(x)+1):
            if attempt<int(x): messages.append({"角色":"执行","调用id":request['id'],"结果":"暂时连接失败"})
            else:
                assert request['name']=='sum' and all(isinstance(v,(int,float)) for v in request['arguments']['values'])
                result=sum(request['arguments']['values']); messages.append({"角色":"执行","调用id":request['id'],"结果":result})
        verified=0
        for value in request['arguments']['values']: verified+=value
        messages.append({"角色":"核对","逐项累加":verified,"通过":verified==result})
        values=(int(x)+1,result,int(verified==result)); details={"消息轨迹":messages}
    elif key == "code-cycle":
        cases=[0,2,-1]; before=[n+x for n in cases]; needs_fix=any(a!=b for a,b in zip(before,cases)); after=[n for n in cases] if needs_fix else before
        values=(sum(a==b for a,b in zip(before,cases)),sum(a==b for a,b in zip(after,cases)),int(needs_fix))
        details={"输入与期望":cases,"初稿输出":before,"最终输出":after,"修改":"移除额外偏差" if needs_fix else "原稿已通过"}
    else:
        raise ValueError(f"Unknown concept experiment: {key}")
    metrics={f"m{i}":round(float(value),10) for i,value in enumerate(values)}
    if not all(math.isfinite(value) for value in metrics.values()):
        raise ValueError("Experiment produced a nonfinite result")
    return metrics, (json.dumps(details, ensure_ascii=False, default=lambda v: float(v)),)
