# 大模型基础：Transformer 到 Mini-GPT

> 课程：人工智能与深度学习：从机器学习基础到大模型智能体  \n> 来源角色：大模型与智能体专题  \n> 上游仓库：llm-beginner（固定版本 `446a1ce01a89b8eabaffcef83096f344b10c7a6b`）  \n> 上游文件：`task-1-transformer/README.md;task-2-mini-gpt/README.md`  \n> 许可标识：MIT；详见 `LICENSES.md`

## 本章学习目标

围绕 AI-KP-10, AI-KP-15 建立可解释、可实践、可检索的知识单元；正文保留上游章节结构并由系统按知识点切分。

## 教材正文

<!-- 上游文件: task-1-transformer/README.md -->

# 任务一：熟悉 Transformer

> 主大纲见仓库根 [README](../README.md)；本目录是该任务的资源、自检与提交入口。

## 一句话目标

用约 300 行 PyTorch 从零写一个 Transformer encoder，在 ChnSentiCorp 中文情感二分类上做到 dev 准确率 ≥ 0.80（参考基线约 0.85），并能用注意力热图说清楚模型「在看什么」。

## 任务情境

假装你刚入职某 NLP 团队，组长让你「先把 Transformer 自己撸一遍」。规则：

- 不许调 `nn.MultiheadAttention` 或任何高层封装
- 不许加载预训练模型
- 两周后周会要汇报：dev 准确率 + 几张注意力热图 + 你对 mask、residual、LayerNorm 的理解

这就是本任务。

## 输入 / 输出

| | 内容 |
|---|---|
| **给你** | ChnSentiCorp 数据（HF 自动拉，约 9.6K 训练样本，二分类）/ PyTorch 2.7+ / 单卡 8GB GPU（CPU 也能跑但慢 ~10×） |
| **交付** | 1. `ckpt/best.pt`（训练好的模型，预期 5–50 MB） 2. `figures/` 下 ≥ 3 张注意力热图 3. `eval/result.json`（自检结果） 4. 一段 200–500 字的实验观察文字 |

## Definition of Done

必做 5 项，缺一不算完成：

- [ ] **M1** 手写 `scaled_dot_product_attention`，自检 `attention_correctness` 通过（与官方实现误差 < 1e-5）
- [ ] **M2** 手写 `MultiHeadAttention` + `TransformerBlock`，前向不报错且形状对
- [ ] **M3** 在 ChnSentiCorp 上训练分类器，dev 准确率 ≥ 0.80（参考基线 ~0.85）
- [ ] **M4** 改一遍代码加 causal mask 跑 toy 语言模型，自检 `causal_mask` 通过（未来词元不泄漏）
- [ ] **M5** 输出 ≥ 3 张注意力热图（建议：1 正面样本、1 负面样本、1 长句样本）

加分（任选）：

- [ ] **S1** head 数 / 层数消融（≥ 3 组配置 + 准确率表）
- [ ] **S2** 拆掉 residual 或 LayerNorm，记录训练是否还能收敛
- [ ] **S3** dev 准确率 > 0.88（强结果）
- [ ] **S4** 把绝对 PE 换成 RoPE 对比

## 实施步骤（建议节奏：2 周）

### 第 1-3 天：环境 + 数据

```bash
pip install -r requirements.txt
python data/download.py
```

跑完应看到 `data/{train,validation,test}.parquet` 三个文件。

### 第 4-6 天：手写 attention（M1 + M2）

**输入**：随机张量 Q/K/V，形状 `(B, H, T, D)`
**输出**：`src/attention.py` 完整，能通过 `python eval/run.py` 的前两项自检

实现内容：

1. `scaled_dot_product_attention(Q, K, V, mask=None)` —— 缩放点积 + mask + softmax + 加权求和
2. `class MultiHeadAttention(nn.Module)` —— 拼分 head、Q/K/V 投影、输出投影

**常见坑**：

- mask 用乘 0 而不是填 `-inf`：softmax 后还有概率泄漏
- 缩放因子写成 `sqrt(d_model)` 而不是 `sqrt(d_k)`
- multi-head reshape 忘加 `.contiguous()` 导致 view 报错

### 第 7-9 天：搭模型 + 训练（M3）

**输入**：ChnSentiCorp 训练集
**输出**：`ckpt/best.pt`、训练 loss 曲线

实现内容：

1. `src/block.py`：`TransformerBlock` = attention + FFN + 两个 residual + 两个 LayerNorm
2. `src/model.py`：`TransformerClassifier` 堆 N 层 block + pooling（[CLS] 位或 mean）+ 分类 head
3. `train.py`：AdamW、cosine LR schedule、padding mask、early stopping by dev acc

**建议超参起点**（不要照搬，做实验）：d_model=128, n_heads=4, n_layers=4, lr=3e-4, batch=32, epochs=5

**常见坑**：

- 忘加 padding mask 导致 PAD token 参与了 attention
- pooling 用 mean 时没排除 padding 位置
- 验证集准确率震荡：lr 太大 / batch 太小 / 没 warmup

### 第 10-11 天：causal mask + toy 语言模型（M4）

**输入**：任意小段文本（可复用唐诗或自己造）
**输出**：自检 `causal_mask` 通过

把同一个 attention 加上 causal mask（上三角 `-inf`），跑一个 toy 语言模型（next-token prediction），验证未来位置 V 改动不影响过去输出。这一步是任务二的预热。

### 第 12-14 天：注意力可视化 + 写报告（M5）

**输入**：训练好的模型 + 几个测试句子
**输出**：`figures/` 下 ≥ 3 张热图 + 报告文字

用 matplotlib 画 attention weights：选一个 head、一个 layer，把 `(T, T)` 矩阵用 imshow 画出来，x/y 轴标词元。在情感正/负样本上对比：模型是否真的在看「不错」「失望」这类词？

## 实现约定

`eval/run.py` 会自动检测以下接口；接口对上就能跑自检：

| 文件 | 必须导出 |
|---|---|
| `src/attention.py` | `scaled_dot_product_attention(Q, K, V, mask=None)` —— Q/K/V 形状 `(B, H, T, D)`；`mask` 形状广播到此，`True` = 被屏蔽 |
| `src/model.py` | `class TransformerClassifier` + `load_for_eval(ckpt_path: str) -> (model, tokenize_fn)` 工厂函数；自检按此契约调用：`tokenize_fn(text: str) -> LongTensor 形状 (T,)`、`model(ids)` 接受形状 `(B, T)` 的 id 张量并返回形状 `(B, num_classes)` 的 logits |
| `ckpt/best.pt` | 训练好的 state_dict |

接口可以改，但改了请同步调整 `eval/run.py`。

## 自检

```bash
python eval/run.py
```

| 测试 | 通过标准 | 对应 DoD |
|---|---|---|
| `attention_correctness` | 与 `F.scaled_dot_product_attention` 误差 < 1e-5 | M1 |
| `causal_mask` | 未来词元的 V 改动后，过去位置输出不变 | M4 |
| `classifier_accuracy` | dev set 准确率 ≥ 0.80 | M3 |

结果写入 `eval/result.json`，提交时附上。

## AI Tutor 反馈

把 [eval/tutor_prompt.md](eval/tutor_prompt.md) 整段贴给 Claude / Qwen / DeepSeek，连同你的代码。模型会按统一格式（必检 / 加分 / 优先级）给你针对性 review。

## 前置阅读（非必需）

- [Attention Is All You Need](https://arxiv.org/abs/1706.03762)
- [The Annotated Transformer](http://nlp.seas.harvard.edu/annotated-transformer/)
- [The Illustrated Transformer](https://jalammar.github.io/illustrated-transformer/)
- NNDL2 第 8 章「注意力机制」「自注意力」「Transformer 模型」三节
- 实践书 v2《注意力机制》章

## 提交

到 [nndl-discussion](https://github.com/nndl/nndl-discussion/discussions) 「llm-beginner 实践成果」分类发帖，附：

1. 你的 fork 仓库链接
2. `eval/result.json` 内容（贴文本即可）
3. DoD checklist 勾选状态
4. ≥ 3 张注意力热图
5. 200-500 字实验观察：你做了哪些消融、看到了什么有意思的现象

## 时间

约 2 周。如果在 M3（训练）卡住超过 3 天，建议把模型缩到 d_model=64 / n_layers=2 先跑通，再回头调参。


<!-- 上游文件: task-2-mini-gpt/README.md -->

# 任务二：从零实现 mini-GPT

> 主大纲见仓库根 [README](../README.md)；本目录是该任务的资源、自检与提交入口。

## 一句话目标

用 PyTorch 从零搭一个 decoder-only mini-GPT：手写 BPE 分词、集成 RoPE、实现 KV cache，在中文小语料上预训练到困惑度达标，并能自回归生成连贯文本。**扩展**实践书 v2「nanoGPT 模型」的带读——nanoGPT 用绝对位置编码、只讲不实现 KV cache，这里都亲手补上。

## 任务情境

假装你要给团队做一个「最小可用」的语言模型底座，组长的要求是：

- 不许用 `tiktoken` / `sentencepiece`，分词器自己写
- 位置编码要用 RoPE，不要绝对位置编码
- 推理要带 KV cache，能讲清楚它省了什么
- 三周后汇报：困惑度曲线 + 几段生成样例 + 你对 BPE、RoPE、KV cache 的理解

这就是本任务。

## 输入 / 输出

| | 内容 |
|---|---|
| **给你** | 三档语料（唐诗 ~49KB quick-start / TinyStories / SkyPile 子集，`data/download.py` 自动准备）/ PyTorch 2.7+ / 唐诗档 CPU 即可，TinyStories CPU 可训但慢、建议 GPU，SkyPile 子集建议 GPU |
| **交付** | 1. `ckpt/tokenizer.json`（训练好的 BPE 词表） 2. `ckpt/best.pt`（预训练模型 state_dict） 3. 几段生成样例（不同采样策略对比） 4. `eval/result.json`（自检结果） 5. 一段 200–500 字实验观察 |

## Definition of Done

必做 5 项，缺一不算完成：

- [ ] **M1** 手写简化版 BPE tokenizer，自检 `tokenizer_roundtrip` 通过（encode→decode 能还原中文）
- [ ] **M2** 手写 decoder-only 模型并集成 **RoPE**，前向不报错且形状对
- [ ] **M3** 实现 **KV cache**，自检 `kv_cache_equivalence` 通过（开/关 cache logits 误差 < 1e-4）
- [ ] **M4** 在语料上预训练，自检 `perplexity_on_dev` 低于阈值（唐诗 < 50 / TinyStories < 10）
- [ ] **M5** 实现 greedy / top-k / top-p / temperature 四种采样，能生成连贯文本

加分（任选）：

- [ ] **S1** 参数量扫描（10M / 50M / 100M）vs 困惑度
- [ ] **S2** 绝对位置编码 vs RoPE 在长序列外推上的差异
- [ ] **S3** KV cache 开 / 关的推理速度对比（同样词元数计时）
- [ ] **S4** TinyStories 上复现 10M 参数模型涌现叙事能力

## 实施步骤（建议节奏：3 周）

### 第 1-2 天：环境 + 数据

```bash
pip install -r requirements.txt

# 三档数据，按设备和目标选；不加参数默认 poetry，适合先跑通
python data/download.py                         # ~49KB 唐诗 quick-start
python data/download.py --dataset poetry        # ~49KB，CPU 即可，5 分钟跑通
python data/download.py --dataset tinystories   # 英文故事语料，CPU 可训，看小模型叙事能力
python data/download.py --dataset skypile       # ~1GB+，建议 GPU
```

脚本统一生成 `data/train.txt`、`data/dev.txt`、`data/dataset_info.json`。训练代码读 `train.txt`，自检用 `dev.txt` 算困惑度；自行换中文语料也请保持这两个文件名。

### 第 3-6 天：BPE tokenizer（M1）

**输入**：`train.txt` 语料
**输出**：`src/tokenizer.py` 完整，`ckpt/tokenizer.json` 词表，能通过 `tokenizer_roundtrip` 自检

实现 `class BPETokenizer`：统计相邻 token 对频率、迭代 merge、导出词表，`encode`/`decode`/`from_pretrained` 齐全。

**常见坑**：

- 字节级（byte-level）还是字符级没想清楚：中文若按字符级，未登录字会丢；按字节级要保证 `decode` 能跨 UTF-8 多字节边界还原
- merge 顺序错：合并必须每轮取当前频率最高的对，且 `decode` 时按训练时的 merge 表反向还原
- `vocab_size` 没暴露，下游建 embedding 时对不上

### 第 7-12 天：模型 + RoPE + KV cache（M2 + M3）

**输入**：tokenizer 编码后的 id 序列
**输出**：`src/model.py` 完整，通过 `kv_cache_equivalence` 自检

实现内容：

1. `src/rope.py`：旋转位置编码，作用在 Q/K 上
2. `src/attention.py`：causal multi-head attention，支持传入并更新 KV cache
3. `src/model.py`：`class MiniGPT`，`forward(ids, kv_cache=None, return_cache=False)` + `generate(...)`

**常见坑**：

- RoPE 维度配对方式（相邻两维一组 vs 前后折半）实现与解码要一致；频率基底常用 `base=10000`
- RoPE 只加在 Q/K，**不要**加在 V
- KV cache 增量解码时，新词元的 position 要接着历史长度算（否则 RoPE 角度错、和全量前向对不上，`kv_cache_equivalence` 直接挂）
- cache 拼接维度搞反（应在序列长度 T 维上 append）

### 第 13-16 天：训练（M4）

**输入**：`train.txt`
**输出**：`ckpt/best.pt`、困惑度曲线

`train.py`：next-token prediction，AdamW，cosine schedule，gradient clipping，留出 dev split 监控困惑度。

**常见坑**：

- 唐诗语料小，容易过拟合：困惑度先降后升就该早停
- 没做 gradient clipping，loss 偶发 spike
- block_size 设得比 dev 文本短没关系（自检会按 `block_size` 非重叠分块），但训练/推理的上下文长度要一致

### 第 17-21 天：采样 + 生成 + 写报告（M5）

**输入**：训练好的模型
**输出**：`src/sampling.py`，几段不同策略的生成样例 + 报告文字

实现 greedy / top-k / top-p / temperature，对比同一 prompt 下的生成多样性与连贯度。

**常见坑**：

- top-p 要先按概率降序累加到阈值再截断，别忘了重新归一化
- `temperature=0` 应退化为 greedy，别让它触发除零
- 生成时如果不接 KV cache，每步重算全序列会很慢——正好印证 M3 的价值

## 实现约定

`eval/run.py` 会自动检测以下接口；接口对上就能跑自检：

| 文件 | 必须导出 |
|---|---|
| `src/tokenizer.py` | `class BPETokenizer` 含 `encode(text) -> List[int]`、`decode(ids) -> str`、`vocab_size`、`from_pretrained(path)` |
| `src/model.py` | `class MiniGPT(nn.Module)` 含 `forward(ids, kv_cache=None, return_cache=False)`、`generate(prompt_ids, max_new_tokens, top_k, top_p, temperature)`、属性 `block_size`/`max_seq_len`（自检按它对困惑度切窗，取不到默认 256）；`load_for_eval(ckpt_path) -> (model, tokenizer)` |
| `ckpt/tokenizer.json` | 训练好的 BPE 词表 |
| `ckpt/best.pt` | 训练好的模型 state_dict |

接口可以改，但改了请同步调整 `eval/run.py`。

## 自检

```bash
python eval/run.py
```

| 测试 | 通过标准 | 对应 DoD |
|---|---|---|
| `tokenizer_roundtrip` | encode → decode 还原中文文本（除已知 UTF-8 边界 case） | M1 |
| `kv_cache_equivalence` | 开 KV cache 与不开的 logits 一致（误差 < 1e-4） | M3 |
| `perplexity_on_dev` | dev set 困惑度低于阈值（唐诗默认 < 50，TinyStories 默认 < 10） | M4 |

> `perplexity_on_dev` 读取 `data/dev.txt`（最多取前 4096 个词元），按模型上下文长度非重叠分块累加 NLL 后求困惑度——窗口取 `MiniGPT.block_size` 或 `max_seq_len`，取不到则默认 256。因此小上下文模型也能跑通、不会越界或 OOM；建议给 `MiniGPT` 暴露 `block_size` 或 `max_seq_len` 属性，让自检按你的真实训练长度切窗。

结果写入 `eval/result.json`，提交时附上。

## AI Tutor 反馈

把 [eval/tutor_prompt.md](eval/tutor_prompt.md) 整段贴给 Claude / Qwen / DeepSeek，连同你的代码。模型会按统一格式（必检 / 加分 / 优先级）给你针对性 review。

## 前置阅读（非必需）

- [nanoGPT](https://github.com/karpathy/nanoGPT)
- [TinyStories 原论文](https://arxiv.org/abs/2305.07759)
- [RoFormer (RoPE)](https://arxiv.org/abs/2104.09864)
- NNDL2 第 8 章「现代 Transformer 的常见优化」
- 实践书 v2《大语言模型与智能体》「nanoGPT 模型」「预训练循环」「解码 / 采样策略」三节

## 提交

到 [nndl-discussion](https://github.com/nndl/nndl-discussion/discussions) 「llm-beginner 实践成果」分类发帖，附：

1. 你的 fork 仓库链接
2. `eval/result.json` 内容（贴文本即可）
3. DoD checklist 勾选状态
4. 几段生成样例（不同采样策略对比）
5. 200-500 字实验观察：你做了哪些消融、看到了什么有意思的现象（如涌现、外推差异）

## 时间

约 3 周。如果在 M4（训练）卡住，先把模型缩小（如 4 层、d_model=128）在唐诗上跑通整条 pipeline，再扩大规模。
