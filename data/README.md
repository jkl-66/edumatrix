# 课程输入与本地资产

GitHub 保存当前源码、课程清单、来源记录、已附许可的整理课程及小型练习数据。它不是本机数据库或演示材料的完整备份。

## 首次克隆须补齐的教材

`ai_deep_learning_agents_v1/course_manifest.json` 保留本机完整课程定义。NNDL 和 NNDL Practice 的上游未提供可确认的公开再分发许可，本次不上传它们的副本；本机文件保留。不要把 `LICENSES.md` 中的“用户已取得使用许可”当作公开再分发授权。

启动时会严格校验完整课程，缺少以下四个文件会阻止默认课程初始化，因此克隆后须先从具有合法使用权限的本地工作区复制到 `data/curated/ai_deep_learning_agents_v1/chapters/`，并保持内容与清单哈希一致：

- `15_NNDL第二版_神经网络与深度学习理论地图.md`
- `16_NNDL第二版完整电子书.md`
- `17_NNDL通识版完整电子书.md`
- `18_NNDL案例与实践_PyTorch工程实践.md`

完整 PDF 原件同样只保留在本地。上游入口为 <https://github.com/nndl/nndl> 与 <https://github.com/nndl/nndl-practice>；固定版本、源文件和哈希见课程清单。已有整理脚本是 `scripts/build_master_ai_course.py`，依赖 `data/raw/github_repos/` 的上游检出；本次没有重新执行它，也不保证在不同依赖下重建出完全相同的 PDF 抽取文本。

其他收录课程的许可证与署名在各课程目录。AI 课程还附有 `licenses/` 下从本地固定上游检出复制的 D2L Apache-2.0 和 LLM-Beginner MIT 许可全文。仓库根许可证不覆盖第三方素材；历史清单不等于本次独立完成全部许可证审计。

## 其他本地内容

- `.env`、API Key、用户数据库、备份、上传文件和运行缓存不入库；新环境按 `.env.example` 配置并初始化新数据库。
- `111.mp4`、赛题 PDF、历史运行证据和旧提交包留在本地；文档指向这些路径的链接仅在原工作区有效。
- MNIST 大型 CSV 未上传；数据集来源和许可见 `manifest/datasets_manifest.jsonl`，下载入口为 `scripts/download_datasets.py`。
- whisper.cpp 可选二进制及模型不入库；来源、版本、哈希和目标路径见 `vendor/whisper.cpp/runtime-manifest.json`。未安装时语音能力不可用，核心启动预检只提示。
- `outputs/M0_阶段0基线与架构契约/baseline_course/` 与 `datasets/` 是代码仍读取的运行/测试输入，必须保留。
