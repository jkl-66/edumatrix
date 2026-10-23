# 课程输入与本地资产

GitHub 保存当前源码、课程清单、来源记录、已附许可的整理课程及小型练习数据。它不是本机数据库或演示材料的完整备份。

## 已纳入仓库的教材

用户于 2026-10-24 确认现有素材已具备所需许可，并明确授权公开提交。`curated/ai_deep_learning_agents_v1/course_manifest.json` 中的 NNDL 和 NNDL Practice 教材已纳入仓库，保留原有来源、版本和哈希记录。

以下四份运行必需文本位于 `data/curated/ai_deep_learning_agents_v1/chapters/`，克隆后无需另行复制：

- `15_NNDL第二版_神经网络与深度学习理论地图.md`
- `16_NNDL第二版完整电子书.md`
- `17_NNDL通识版完整电子书.md`
- `18_NNDL案例与实践_PyTorch工程实践.md`

两份完整电子书的 PDF 原件一并纳入仓库。上游入口为 <https://github.com/nndl/nndl> 与 <https://github.com/nndl/nndl-practice>；固定版本、源文件和哈希见课程清单。已有整理脚本是 `scripts/build_master_ai_course.py`，依赖 `data/raw/github_repos/` 的上游检出；正常运行直接读取已提交的整理文本，无需重新抽取 PDF。

其他收录课程的许可证与署名在各课程目录。AI 课程还附有 `licenses/` 下从本地固定上游检出复制的 D2L Apache-2.0 和 LLM-Beginner MIT 许可全文。仓库根许可证不覆盖第三方素材；历史清单不等于本次独立完成全部许可证审计。

## 其他本地内容

- `.env`、API Key、用户数据库、备份、上传文件和运行缓存不入库；新环境按 `.env.example` 配置并初始化新数据库。
- `111.mp4`、赛题 PDF、历史运行证据和旧提交包留在本地；文档指向这些路径的链接仅在原工作区有效。
- MNIST 大型 CSV 未上传；数据集来源和许可见 `manifest/datasets_manifest.jsonl`，下载入口为 `scripts/download_datasets.py`。
- whisper.cpp 可选二进制及模型不入库；来源、版本、哈希和目标路径见 `vendor/whisper.cpp/runtime-manifest.json`。未安装时语音能力不可用，核心启动预检只提示。
- `outputs/M0_阶段0基线与架构契约/baseline_course/` 与 `datasets/` 是代码仍读取的运行/测试输入，必须保留。
