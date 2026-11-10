"""Build the reviewed AI-course teaching map without changing source bodies.

Run with --output to review a candidate; the catalog applies the versioned
manifest through its normal update path. The old broad concepts remain valid
historical identities. This script never opens a learning database.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / 'data/curated/ai_deep_learning_agents_v1'


def code(short):
    return 'AI-KP-' + short.replace('.', '-')


# Each row states an assessable concept, its actual prerequisites and a result
# the learner should be able to explain or produce. These are curriculum
# decisions, not claims that the source explicitly states prerequisite edges.
POINTS = [
 ('06.01','隐藏层、非线性激活与多层感知机','02.04 04.01','计算一层输出，解释连续线性层为什么仍是线性模型'),
 ('06.02','计算图、前向传播与反向传播','06.01 02.06','沿小计算图核算局部梯度与链式传播'),
 ('06.03','梯度消失、梯度爆炸与参数初始化','06.02','从训练曲线和梯度量级判断初始化问题'),
 ('06.04','网络模块、参数管理与模型保存','06.01 04.06','构造网络模块，区分可训练参数并保存和恢复模型'),
 ('07.01','权重衰减与Dropout','05.03 06.01','比较两种正则化的作用以及训练和推理时的差别'),
 ('07.02','优化目标、凸性与梯度下降','04.03 02.06','区分优化误差与泛化误差，解释梯度下降的步长和收敛条件'),
 ('07.03','随机梯度、小批量与动量','07.02 03.04','比较批大小和动量对噪声、速度及训练曲线的影响'),
 ('07.04','自适应优化器与Adam','07.03','解释自适应步长及一二阶矩，比较实际训练结果'),
 ('07.05','学习率调度与训练诊断','07.04 06.03','据训练与验证曲线选择学习率调整并保留对照'),
 ('08.01','卷积核、局部连接与参数共享','06.01','手算小矩阵卷积并说明与全连接层的不同'),
 ('08.02','填充、步幅、通道与池化','08.01','核算输出形状，解释通道和下采样保留了什么'),
 ('08.03','LeNet与深层卷积网络','08.02 06.04','搭建并比较卷积网络的输入输出和参数规模'),
 ('08.04','批量规范化与残差连接','08.03 06.02','解释训练与推理统计量及残差路径的作用'),
 ('09.01','序列、词元与语言建模','03.04 04.05','构造序列样本，解释条件预测与困惑度'),
 ('09.02','循环状态与通过时间反向传播','09.01 06.02','展开循环网络并解释长序列梯度问题'),
 ('09.03','GRU与LSTM的门控记忆','09.02','说明更新、遗忘与输出门如何控制状态'),
 ('09.04','编码器解码器、seq2seq与束搜索','09.03','追踪翻译输入输出，比较贪心与束搜索的局限'),
 ('10.01','查询、键、值与注意力评分','02.04 04.04','计算注意力权重，解释加权汇聚和掩码'),
 ('10.02','多头、自注意力与位置编码','10.01','核算多头形状并说明位置信息如何进入模型'),
 ('10.03','Transformer结构与因果掩码','10.02 09.04 08.04','画出编码解码数据流，区分训练并行与生成依赖'),
 ('11.01','图数据、节点边任务与图级读出','02.04 06.01','按任务选择表示、划分单位和读出方式'),
 ('11.02','消息传递、邻域聚合与图卷积','11.01','手算一次邻居聚合并对比GCN与注意力聚合'),
 ('11.03','图网络的过平滑与过压缩','11.02','区分两种深层图网络问题及适用的缓解方法'),
 ('12.01','主成分分析与降维重建','02.04 02.09','解释投影、方差与重建误差的关系'),
 ('12.02','自编码器与表示学习','06.02 12.01','解释编码、重建目标及压缩表示的局限'),
 ('12.03','聚类、密度估计与无标签评价','02.08 12.01','区分聚类与分类，说明无标签任务的评价依据'),
 ('12.04','自监督任务与对比表示','12.02 04.05','构造监督信号，区分预训练目标与下游效果'),
 ('13.01','数据增广与迁移微调','08.03 05.02','设计不泄漏的数据增广与微调对照'),
 ('13.02','检测框、锚框与目标检测','13.01','计算框重叠，说明类别和位置预测的分工'),
 ('13.03','语义分割、转置卷积与全卷积网络','08.02 13.02','解释逐像素输出与上采样的形状变化'),
 ('13.04','视觉任务的实验比较','13.01 13.03','比较独立验证结果，解释误判样例及适用边界'),
 ('14.01','词嵌入、负采样与子词表示','09.01 04.05','解释词表示的训练信号、近似计算与未登录词处理'),
 ('14.02','BERT预训练与上下文表示','10.03 14.01','区分掩码预训练与自回归生成，说明预训练输入'),
 ('14.03','情感分类、自然语言推断与微调','14.02 05.02','为下游任务选择输出头并解释验证结果'),
 ('15.01','自回归生成、困惑度与解码策略','10.03 09.01','比较温度、贪心和采样，解释困惑度不能直接代表回答正确性'),
 ('15.02','大模型预训练、分词与规模规律','15.01','解释训练数据、词元和计算预算的相互约束'),
 ('15.03','上下文学习与推理增强','15.02','区分示例提示、推理计算和参数更新，核验推理结果'),
 ('15.04','小型GPT的训练与生成实验','15.02 06.04 07.05','运行小规模因果语言模型，记录损失和生成行为'),
 ('16.01','指令微调与参数高效微调','15.02 07.05','说明指令数据、训练目标及LoRA改变的参数'),
 ('16.02','偏好数据、奖励与RLHF','16.01','区分示范答案与偏好比较，解释奖励优化的边界'),
 ('16.03','DPO与策略优化方法的比较','16.02','比较偏好优化目标和所需组件，避免把一种工程顺序当普遍定律'),
 ('17.01','检索增强生成的证据链','15.01','拆开索引、检索和生成，指出每步可能丢失或歪曲的证据'),
 ('17.02','文档切分、向量索引与召回','17.01 03.05','设计保留来源的切分和索引，说明归一化与相似度条件'),
 ('17.03','重排序与检索质量评价','17.02 05.02','计算Recall@k和MRR并比较有无重排的结果'),
 ('17.04','回答忠实性与RAG消融实验','17.03','逐项核对回答依据，区分检索命中、引用存在和内容受支持'),
 ('18.01','智能体状态、规划与ReAct','15.03','追踪观察、决策、行动和状态更新，不把文字计划当执行结果'),
 ('18.02','工具选择、参数校验与执行恢复','18.01','验证工具输入输出，利用实际结果继续任务并处理失败'),
 ('18.03','多智能体分工、共享信息与协作','18.02','比较协作与单体任务流程，追踪交接与纠错依据'),
 ('18.04','智能体任务评价与过程治理','18.03 17.04','分开统计任务完成、工具执行和证据质量，解释失败原因'),
 ('19.01','MCP工具接口与调用协议','18.02','区分协议接口与工具实现，验证枚举、调用和错误返回'),
 ('19.02','技能加载、子任务隔离与上下文管理','19.01 18.03','组织按需加载的技能与子任务信息，检查交接遗漏'),
 ('19.03','代码智能体的修改验证循环','19.02 18.04','完成读代码、修改、测试与结果核对，保留失败和修订'),
 ('21.01','异步计算、并行与性能测量','06.04','测量同步前后的真实耗时，区分延迟和吞吐量'),
 ('21.02','多GPU数据并行与梯度同步','21.01 07.03','追踪批次分配与梯度汇总，解释加速收益和通信代价'),
 ('21.03','参数服务器与分布式训练','21.02','比较集中与分布式参数更新的瓶颈和一致性条件'),
]


def build():
    manifest = json.loads((BASE / 'course_manifest.json').read_text(encoding='utf8'))
    if manifest.get('teaching_structure'):
        raise ValueError('This reviewed migration has already been generated; do not rebuild from an edited manifest.')
    initial_stage = deepcopy(manifest['diagnostic_stages'][0])
    known = {p['code']: p for p in manifest['knowledge_points']}
    for short, title, before, outcome in POINTS:
        cid, parent = code(short), code(short.split('.')[0])
        assert cid not in known
        point = {'code':cid, 'title':title, 'level':known[parent]['level'],
                 'prerequisites':[code(x) for x in before.split()], 'parent_code':parent,
                 'learning_outcome':outcome}
        manifest['knowledge_points'].append(point); known[cid] = point
        manifest['knowledge_refinements'].setdefault(parent, []).append(cid)
    known['AI-KP-20']['prerequisites'] = [code(x) for x in ['17.04','18.04','19.03']]
    for stage in manifest['diagnostic_stages'][3:]:
        stage['knowledge_point_codes'] = [fine for old in stage['knowledge_point_codes']
            for fine in manifest['knowledge_refinements'].get(old, [old])]
    for name, sequence in manifest['pathways'].items():
        manifest['pathways'][name] = [fine for old in sequence for fine in manifest['knowledge_refinements'].get(old,[old])]
    assert manifest['diagnostic_stages'][0] == initial_stage
    chapters, units = [], []
    specs = {}

    def section(doc, heading, points, title=None, goal=None, occurrence=-1):
        specs.setdefault(doc, []).append((heading, points.split(), title, goal, occurrence))

    # Existing foundation concepts keep their identities and diagnostic scope.
    section(0,'引言','01.01 01.02 03.01','从数据理解预测任务','用一张数据表区分样本、特征、标签及回归与分类')
    section(1,'数据操作','02.01','张量与数据操作','表示一批数据并检查形状和索引')
    section(1,'数据预处理','03.02 03.03','缺失值与类别编码','处理缺失和类别数据，解释每一步改变了什么')
    section(1,'线性代数','02.01 02.02 02.03 02.04','向量矩阵与加权预测','核算点积和矩阵乘法并连接模型输入输出')
    section(1,'微积分','02.05 02.06','变化率、梯度与链式法则','从函数变化逐步计算偏导数和复合函数梯度')
    section(1,'自动微分','02.06','自动微分核验','用手算小例子核对自动微分结果')
    section(1,'概率','02.07 02.08 02.09','概率、条件与不确定性','用计数解释条件概率、独立性、期望和方差')
    section(2,'线性回归','04.01 04.02 04.03','线性模型与训练目标','从预测误差推到损失和参数更新')
    section(2,'线性回归的从零开始实现','03.04 04.06','完成线性回归训练循环','读取批次、计算损失并检查一次更新')
    section(2,'softmax回归','04.04 04.05','多类概率与交叉熵','核算类别概率和损失，解释错误预测受到的惩罚')
    section(2,'softmax回归的从零开始实现','04.04 04.05','运行分类与评价实验','完成训练、验证并解释分类错误')
    section(3,'多层感知机','06.01')
    section(3,'多层感知机的从零开始实现','06.01','实现多层网络','核对层间形状、激活和分类结果')
    section(3,'模型选择、欠拟合和过拟合','05.01 05.02 05.03 05.04 05.05','选择能泛化的模型','固定训练验证测试分工，用曲线解释过拟合和选参')
    section(3,'权重衰减','07.01','权重衰减实验','比较不同正则化强度下的训练和验证误差')
    section(3,'暂退法（Dropout）','07.01','Dropout训练与推理','解释随机失活、缩放和推理时的差别')
    section(3,'前向传播、反向传播和计算图','06.02')
    section(3,'数值稳定性和模型初始化','06.03')
    section(3,'环境和分布偏移','05.01 05.03','分布变化与模型失效','分析训练环境改变后预测失效的原因')
    section(3,'实战Kaggle比赛：预测房价','03.02 03.03 05.04 05.05','房价预测的验证实验','完成预处理与交叉验证，记录选择依据和限制')
    for h in ['层和块','参数管理']:
        section(4,h,'06.04',goal='构造网络模块，区分参数、梯度和共享参数')
    section(4,'读写文件','06.04','保存与恢复模型','保存参数并重新加载，核对恢复前后的预测')
    section(5,'优化和深度学习','07.02')
    section(5,'凸性','07.02','凸性与优化条件','区分局部与全局最优以及适用前提')
    section(5,'梯度下降','07.02','梯度下降实验','比较学习率对参数轨迹的影响')
    for h in ['随机梯度下降','小批量随机梯度下降','动量法']: section(5,h,'07.03')
    for h in ['AdaGrad算法','RMSProp算法','Adam算法']: section(5,h,'07.04')
    section(5,'学习率调度器','07.05')
    for h in ['从全连接层到卷积','图像卷积']: section(6,h,'08.01')
    for h in ['填充和步幅','多输入多输出通道','汇聚层']: section(6,h,'08.02')
    section(6,'卷积神经网络（LeNet）','08.03')
    section(7,'使用块的网络（VGG）','08.03','比较卷积块与网络深度','核算不同块配置的形状、参数和训练结果')
    for h in ['批量规范化','残差网络（ResNet）']: section(7,h,'08.04')
    for h in ['序列模型','文本预处理','语言模型和数据集']: section(8,h,'09.01')
    section(8,'循环神经网络','09.02')
    section(8,'循环神经网络的从零开始实现','09.02','运行循环网络','追踪隐藏状态并观察梯度与生成结果')
    section(8,'通过时间反向传播','09.02','时间展开与梯度','沿时间步解释梯度传播和截断')
    for h in ['门控循环单元（GRU）','长短期记忆网络（LSTM）']: section(9,h,'09.03')
    for h in ['编码器-解码器架构','序列到序列学习（seq2seq）','束搜索']: section(9,h,'09.04')
    for h in ['注意力汇聚：Nadaraya-Watson 核回归','注意力评分函数']: section(10,h,'10.01')
    for h in ['多头注意力','自注意力和位置编码']: section(10,h,'10.02')
    section(10,'Transformer','10.03')
    for h in ['异步计算','自动并行','硬件']: section(11,h,'21.01')
    section(11,'多GPU训练','21.02')
    section(11,'参数服务器','21.03')
    for h in ['图像增广','微调']: section(12,h,'13.01')
    for h in ['目标检测和边界框','锚框','单发多框检测（SSD）']: section(12,h,'13.02')
    for h in ['语义分割和数据集','转置卷积','全卷积网络']: section(12,h,'13.03')
    section(12,'实战 Kaggle 比赛：图像分类 (CIFAR-10)','13.04')
    for h in ['词嵌入（word2vec）','近似训练','子词嵌入']: section(13,h,'14.01')
    for h in ['来自Transformers的双向编码器表示（BERT）','预训练BERT']: section(13,h,'14.02')
    for h in ['情感分析：使用循环神经网络','自然语言推断与数据集','针对序列级和词元级应用微调BERT']: section(14,h,'14.03')
    section(19,'任务二：从零实现 mini-GPT','15.04','小型GPT训练与生成','在可用设备上运行小模型并检查损失、因果掩码和生成；硬件不足时从可运行的小规模实验逐步扩大')
    # A task guide supplies implementation constraints, not general theory.
    for doc, heading, points, title, goal in [
      (20,'任务三：指令微调与偏好对齐','16.01 16.02 16.03','微调与偏好对齐实验','按本任务约定比较微调前后输出；说明数据、损失和比较标准，区分任务规则与通用原理'),
      (21,'任务四：RAG 文档问答','17.02 17.03 17.04','完成可核验的文档问答','保留原文位置，比较切分、召回和重排，分别评价检索命中与回答忠实性'),
      (22,'任务五：工具调用 Agent','18.02','工具执行与恢复实验','实现受限工具和执行循环，用任务结果检查成功与失败恢复'),
      (23,'任务六：Mini Coding Agent','19.01 19.02 19.03','代码智能体综合实验','分阶段实现工具接口、技能加载和改码测试循环；以实际测试结果评价，材料中的本地7B和工具数量仅属该工程方案'),
    ]: section(doc,heading,points,title,goal)
    section(24,'Common pitfalls and recommended practices','03.05','预处理参数与数据泄漏','先划分数据，只在训练数据拟合；比较错误预处理与正确流水线')

    def add(doc, start, end, shorts, title, goal=None, reference=False):
        f = manifest['files'][doc]; text=texts[doc]
        key=f'ai-section-{doc:02}-{start}'
        codes=[code(x) for x in shorts]
        if codes:
            title = title or '、'.join(known[c]['title'] for c in codes)
            goal = goal or '；'.join(known[c].get('learning_outcome',known[c]['title']) for c in codes)
        chapters.append({'key':key,'filename':Path(f['path']).name,'title':title,
            'char_start':start,'char_end':end,'content_sha256':hashlib.sha256(text.encode()).hexdigest(),
            'knowledge_point_codes':codes,'learning_role':'reference' if reference else 'teaching'})
        if codes and not reference:
            if 'AI-KP-20' in codes:
                units.append({'key':'unit-'+key,'title':'评价智能体任务与过程',
                    'goal':known['AI-KP-18-04']['learning_outcome'],'knowledge_point_codes':[code('18.04')],'primary_chapter_keys':[key]})
                units.append({'key':'project-'+key,'title':'个性化学习智能体综合项目',
                    'goal':goal,'knowledge_point_codes':[code('20')],'primary_chapter_keys':[key]})
            else:
                units.append({'key':'unit-'+key,'title':title,'goal':goal,'knowledge_point_codes':codes,'primary_chapter_keys':[key]})

    # Match the public Markdown parser's canonical text exactly.
    texts={i:(BASE/f['path']).read_text(encoding='utf8').strip() for i,f in enumerate(manifest['files'])}
    for doc,text in texts.items():
        if doc==16:
            markers={int(m[1]):m.start() for m in re.finditer(r'(?m)^--- 第 (\d+) 页 ---',text)}
            def anchor(page, title):
                start,end=markers[page],markers[page+1]
                matches=list(re.finditer(r'(?m)^'+re.escape(title)+r'\s*$',text[start:end]))
                assert matches,(page,title)
                # Repeated running page headers precede the actual heading.
                return start+matches[-1].start()
            page_ranges=[
              (markers[262],anchor(270,'9.3 图神经网络'),'11.01','图数据与学习任务'),
              (anchor(270,'9.3 图神经网络'),anchor(284,'9.5 图神经网络中的共性问题'),'11.02','消息传递与图网络'),
              (anchor(284,'9.5 图神经网络中的共性问题'),anchor(286,'9.6 总结和扩展阅读'),'11.03','深层图网络的边界'),
              (anchor(293,'10.1.1 主成分分析'),anchor(295,'10.1.2 稀疏编码'),'12.01','主成分分析'),
              (anchor(297,'10.1.3 自编码器'),anchor(301,'10.2 概率密度估计'),'12.02','自编码器'),
              (anchor(301,'10.2 概率密度估计'),anchor(306,'10.4 自监督学习'),'12.03','密度与聚类'),
              (anchor(306,'10.4 自监督学习'),anchor(310,'10.5 总结和扩展阅读'),'12.04','自监督学习'),
              (markers[375],anchor(378,'13.2 大语言模型的预训练'),'15.01','自回归语言模型与生成'),
              (anchor(378,'13.2 大语言模型的预训练'),anchor(382,'13.3 涌现能力'),'15.02','预训练与规模规律'),
              (anchor(382,'13.3 涌现能力'),anchor(384,'13.4 指令微调'),'15.03','上下文学习'),
              (anchor(384,'13.4 指令微调'),anchor(386,'13.5 基于人类反馈的对齐'),'16.01','指令与参数高效微调'),
              (anchor(386,'13.5 基于人类反馈的对齐'),anchor(388,'13.5.4 直接偏好优化'),'16.02','偏好与奖励学习'),
              (anchor(388,'13.5.4 直接偏好优化'),anchor(392,'13.6 推理增强'),'16.03','DPO与策略优化'),
              (anchor(392,'13.6 推理增强'),anchor(395,'13.7 智能体的框架与规划'),'15.03','推理增强与结果验证'),
              (anchor(395,'13.7 智能体的框架与规划'),anchor(397,'13.8 工具使用与多智能体'),'18.01','智能体与ReAct'),
              (anchor(397,'13.8 工具使用与多智能体'),anchor(399,'13.8.3 多模态交互'),'17.01 18.02','工具调用与检索增强'),
              (anchor(399,'13.8.3 多模态交互'),anchor(400,'13.9 智能体评估与流程治理'),'18.03','多模态与多智能体协作'),
              (anchor(400,'13.9 智能体评估与流程治理'),anchor(400,'13.10 总结和扩展阅读'),'18.04 20','智能体评价与学习项目设计'),
            ]
            cursor=0
            for start,end,points,title in page_ranges:
                if start>cursor: add(doc,cursor,start,[],'NNDL理论参考',reference=True)
                goal=None
                if '20' in points.split():
                    goal='设计个性化学习智能体综合项目：明确共同任务、资料证据、用户条件和结果标准，独立完成检索、工具协作与评估；项目要求由本课程综合设计，教材提供评估原理'
                add(doc,start,end,points.split(),title,goal)
                cursor=end
            add(doc,cursor,len(text),[],'NNDL后续理论与参考文献',reference=True)
            continue
        # Exact real Markdown headings, ignoring code comments and fenced code.
        headings=[]; offset=0; fence=None
        for line in text.splitlines(keepends=True):
            mark=re.match(r'^\s*(`{3,}|~{3,})',line)
            if mark:
                if fence is None: fence=mark[1]
                elif mark[1][0]==fence[0] and len(mark[1])>=len(fence): fence=None
            elif fence is None and line.startswith('# '): headings.append((offset,line[2:].strip()))
            offset+=len(line)
        selected={}
        for heading,points,title,goal,occurrence in specs.get(doc,[]):
            matches=[(pos,h) for pos,h in headings if h==heading]
            assert matches,(doc,heading)
            pos,_=matches[occurrence]
            selected[pos]=(points,title or heading,goal)
        bounds=sorted({0,len(text),*[pos for pos,_ in headings]})
        spans=[]
        for start,end in zip(bounds,bounds[1:]):
            item=selected.get(start)
            if not item and spans and spans[-1][2] is None: spans[-1]=(spans[-1][0],end,None)
            elif item and spans and spans[-1][2] and item[0]==spans[-1][2][0] and item[2]==spans[-1][2][2]:
                # Adjacent explanations of one concept form one learning unit,
                # e.g. convolution padding/channels/pooling, not three repeats.
                merged_title='、'.join(known[code(x)]['title'] for x in item[0])
                spans[-1]=(spans[-1][0],end,(item[0],merged_title,item[2]))
            else: spans.append((start,end,item))
        for start,end,item in spans:
            if item:
                points,title,goal=item;add(doc,start,end,points,title,goal)
            else: add(doc,start,end,[],manifest['files'][doc].get('title',Path(manifest['files'][doc]['path']).stem)+' · 参考阅读',reference=True)

    # Ensure every detailed point is taught. Historical broad nodes stay in the
    # manifest so old questions and reports still resolve, but are not retested.
    covered={c for ch in chapters for c in ch['knowledge_point_codes']}
    active={p['code'] for p in manifest['knowledge_points'] if p['code'] not in manifest['knowledge_refinements']}
    assert covered==active,(sorted(active-covered),sorted(covered-active))
    for file in manifest['files']:
        file['knowledge_point_codes']=sorted({c for ch in chapters if ch['filename']==Path(file['path']).name for c in ch['knowledge_point_codes']})
    manifest['teaching_structure']={'schema_version':'edumatrix.curated-teaching-structure.v1',
        'chapters':chapters,'units':units,'prerequisite_basis':'teaching_suggestion',
        'scope_note':'原文完整保留；主教学片段与补充阅读分开；工程任务约定不作为普遍理论；先修为课程教学安排。'}
    manifest['manifest_version']='course-ai-deep-learning-agents-1.4.0'
    manifest['generated_at']=datetime.now(timezone.utc).isoformat()
    return manifest


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();result=build()
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print(json.dumps({'version':result['manifest_version'],'chapters':len(result['teaching_structure']['chapters']),
        'teaching_units':len(result['teaching_structure']['units']),
        'active_concepts':sum(len(f['knowledge_point_codes']) for f in result['diagnostic_stages'])},ensure_ascii=False))
