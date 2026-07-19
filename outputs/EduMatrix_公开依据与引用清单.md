# EduMatrix 公开依据与引用清单

> 用途：支持赛题背景、技术选型和风险说明。以下资料用于论证问题与方法，不代表 EduMatrix 已取得论文中的实验指标。

## 1. 技术方法依据

1. Lewis, P. et al. (2020). *Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks*. NeurIPS 2020. https://arxiv.org/abs/2005.11401
   - 对应项目：混合 RAG、证据召回、来源与 chunk 追踪。
   - 使用边界：项目只声明实现了证据链路，不声明达到论文实验结果。
2. Nickel, M., & Kiela, D. (2017). *Poincare Embeddings for Learning Hierarchical Representations*. NeurIPS 2017. https://arxiv.org/abs/1705.08039
   - 对应项目：知识层级的双曲空间表示与可视化探索。
   - 使用边界：项目展示实现和代码测试，不把论文指标迁移为项目指标。
3. Piech, C. et al. (2015). *Deep Knowledge Tracing*. NeurIPS 2015. https://papers.nips.cc/paper_files/paper/2015/hash/bac9162b47c56fc8a4d2a3eeb1d5433-Abstract.html
   - 对应项目：DKT/BKT 学习状态追踪的理论背景。
   - 使用边界：当前项目的掌握度更新需要在独立标注集上继续评估。

## 2. 教育与治理依据

4. UNESCO (2023). *Guidance for Generative AI in Education and Research*. https://unesdoc.unesco.org/ark:/48223/pf0000386693
   - 对应项目：合成数据标注、隐私保护、人工复核和可解释证据链。
5. OECD (2023). *Digital Education Outlook 2023: Towards an Effective Digital Education Ecosystem*. https://doi.org/10.1787/c74f03de-en
   - 对应项目：数字化学习服务、学习数据治理和教育系统可持续性背景。
6. ISO/IEC 23894:2023. *Information technology — Artificial intelligence — Guidance on risk management*. https://www.iso.org/standard/77304.html
   - 对应项目：把认证、越权、外部模型、代码执行和数据隔离作为风险项管理。

## 3. 项目内证据对应关系

| 项目材料 | 证据性质 | 不应越界表述 |
|---|---|---|
| `outputs/innovation_evidence/` | 代码实测 + 合成演示数据 | 不称为真实用户实验 |
| `outputs/e2e_no_docker/` | 本地浏览器实测 | 不等于所有评委机器均已验证 |
| `outputs/runtime_security_matrix.json` | A/B/教师运行时安全实测 | 不等于完整生产渗透测试 |
| `test_edumatrix.py`、`tests/` | 自动化测试 | 不等于没有任何未知缺陷 |
| 公开论文和报告 | 外部研究依据 | 不把论文指标写成项目实测指标 |

## 4. 引用规范

- PPT 和主文档统一使用作者、年份、标题、链接四要素。
- 访问日期、版本号和网页截图由团队在最终提交前补齐。
- 公开资料只用于背景和方法论；项目自己的指标必须来自可复现脚本和明确标注的数据集。
