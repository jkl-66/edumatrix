# 运行包第三方来源

课程使用现有已授权素材，原始课程、仓库来源与许可证保存在 `data/raw/github_repos`、`data/manifest` 和各课程的 `course_manifest.json`。知识正文保留来源回跳。

HippoRAG 2 使用官方 OSU-NLP-Group/HippoRAG，固定提交 `d5c8329422e0a0b834a15874545cb6a74b4f9b26`。本包 wheel 从该提交的官方源码构建，未修改源码或依赖元数据，许可证随 wheel 分发。wheel SHA-256：`24f1aa23a5b1366499a0e72c380d9164b7c4556e6ec2fc44a19521de6eb48e4a`。

GEPA 使用公开发布的 `gepa==0.1.4`；Python 依赖及版本见 `requirements-lock.txt`，各依赖许可证随安装包保留。未使用的 instructor 不进入运行环境。

本地检索模型为 intfloat/multilingual-e5-small，模型卡和许可说明随 `data/models/multilingual-e5-small/README.md` 分发。前端第三方资源和字体许可随构建目录及项目 NOTICE 保留。

预置学习者、诊断输入、练习回答为合成资料；资源正文来自项目已记录的真实模型生成与修订。它们用于体验产品，不作为真人学习效果或外部独立评价。
