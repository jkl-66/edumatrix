# EduMatrix 智教矩阵 — 项目开发工作日志

本日志用于实时记录 **EduMatrix 智教矩阵** 自适应教育系统的每日开发进展、代码变动、Bug 修复及协作情况。

---

## 📊 项目基础状态

* **开发人员**：iray666 (lzz20060119@gmail.com)
* **项目角色**：核心全栈开发
* **GitHub 仓库**：[jkl-66/edumatrix](https://github.com/jkl-66/edumatrix)
* **主开发环境**：Vue 3 + Vite + FastAPI + SQLite

---

## 📅 每日开发记录

### 2026-05-24
> **今日概述**：全面梳理了项目整体系统架构，成功编写了详实的系统设计说明书，攻克了系统运行期的初始化 Bug 和本地代理网络拦截问题，并建立了高效率的 Git 团队协作一键流。

#### 1. 系统架构文档建设
* **完成工作**：全面通读了项目 40+ 个核心源文件（包含前后端及 scripts 脚本目录）。
* **产出文档**：在项目根目录生成了核心架构与设计说明书 [AGENTS.md](file:///d:/桌面/edumatrix-main/AGENTS.md)。
  * 包含：1+3+5 智能体协作拓扑图、9 步核心数据流顺序图、前后端 20+ 模块及路由对照表、9 张 SQLite 持久层 E-R 图，以及系统所融合的 7 大经典设计模式。

#### 2. 代码重构与 Bug 修复
* **Bug 修复**：定位并修复了 RAG 核心引擎 [rag_engine.py](file:///d:/桌面/edumatrix-main/rag_engine.py) 中的初始化闪退缺陷。修正了 `TextKnowledgeIndex` 在无本地种子数据时，由于 `self.documents` 未声明而抛出 `AttributeError` 的严重问题。
* **依赖补全**：在 Python 环境中成功补全安装了 FastAPI 文件上传依赖包 `python-multipart`。

#### 3. 网络及代理（梯子）冲突调优
* **核心突破**：解决了挂载全局代理（VPN/梯子）时，浏览器误将本地流量发送至外部代理服务器导致前端网页无法访问的痛点。
* **实施方案**：直接重构了 [frontend/vite.config.js](file:///d:/桌面/edumatrix-main/frontend/vite.config.js) 配置文件，强制让 Vite 服务绑定纯 IP 地址 `127.0.0.1` 运行。利用代理软件默认不拦截本地回环 IP 的特性，实现了**挂着梯子也能正常开发和调试本地项目**。

#### 4. 高效 Git 协作体系建设
* **脚本产出**：编写并优化了纯 ASCII 编码的高鲁棒性同步脚本 [sync.bat](file:///d:/桌面/edumatrix-main/sync.bat)（一键推送）与 [pull.bat](file:///d:/桌面/edumatrix-main/pull.bat)（一键下载队友更新），彻底解决了中文字符导致 Windows cmd.exe 闪退的问题。
* **快捷键绑定**：在编辑器配置文件中完美绑定了以下高频协作热键：
  * **`Alt + G`**：一键 Stage、Commit 并在后台无缝 push 代码到 GitHub 仓库。
  * **`Alt + P`**：一键拉取（`git pull --rebase`）队友的最新代码并合并到本地。

---

### 2026-05-25 (待更新)
> **今日概述**：简要说明今日工作重点。

#### 1. 计划/完成工作
* [ ] 任务 1
* [ ] 任务 2

#### 2. 遗留问题与下一步规划
* 计划 1
* 计划 2

---

### 2026-05-26 (待更新)
> **今日概述**：简要说明今日工作重点。

#### 1. 计划/完成工作
* [ ] 任务 1
* [ ] 任务 2
