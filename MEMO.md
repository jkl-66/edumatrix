# 📝 EduMatrix 智教矩阵 — AI 全栈开发极速操作备忘录 (Memo)

本备忘录将你日常开发中**唯二需要手动交互**的关键高光操作（约定式同步与视觉测试）固化下来。建议将此文件常驻在编辑器侧边栏，随时查阅！

> [!NOTE]
> **📢 团队零侵入与绿色安全保障**
> 本项目所集成的所有一键启动器 (`start.bat`)、约定式同步 (`sync.bat`) 等批处理文件为 **“纯绿色、非侵入式”** 辅助脚本。
> * 如果你的队友习惯纯手工传统开发，他们可以**完全无视此文件和脚本**，直接使用他们熟悉的常规 Git 命令和 Node 启动命令，本地不会受到任何干扰。
> * 你的私密大模型 Key 统一在本地被 `.gitignore` 屏蔽的 `.env` 文件中管理，绝对不会被 Push 泄漏，安全性 100%。

---

## 🚀 核心黄金快捷键 (The Golden Hotkeys)

| 快捷键 | 对应绿色脚本 | 触发全自动工作流 |
| :--- | :--- | :--- |
| **`Alt + L`** | `.\start.bat` | **一键双起服务**：自动拉起 FastAPI 后端 (8000)、Vite 前端 (5173)，并自动开浏览器跳转！ |
| **`Alt + P`** | `.\pull.bat` | **一键极速拉取**：自动以 `rebase` 模式安全拉取队友最新的 GitHub 代码并优雅合并。 |
| **`Alt + G`** | `.\sync.bat` | **一键约定式同步**：自动暂存、提交并 push 到 GitHub。支持 Conventional Commit！ |

---

## 📌 手动划重点 1：Conventional Commit 约定式同步 (Alt + G)

当你开发完功能，按下 **`Alt + G`** 准备同步到 GitHub 时，终端会提示你输入提交描述。我们已为你打通了 **“极速”** 与 **“规范”** 的双通道：

### 1. 极速懒人通道 (直接回车)
* **操作**：提示出现时，**不用打任何字，直接敲一下回车（Enter）键**！
* **效果**：脚本会自动使用默认词 `feat(auto): auto-sync update` 进行无阻断 commit 并一键 push 飞速上云。

### 2. 极客规范通道 (输入约定式前缀)
为了在国赛中展现你团队的极致工程素养，建议在有重大修改时，打入符合**约定式提交（Conventional Commits）**规范的格式：

| 规范前缀 | 适用开发场景 | 示例输入内容 (你在终端里打什么) |
| :--- | :--- | :--- |
| **`feat(...)`** | 增加/实现新功能 | `feat(quiz): 增加 Quiz 答题卡概念级细粒度打分` |
| **`fix(...)`** | 修复了某个 Bug | `fix(rag): 解决 TextKnowledgeIndex 属性未定义崩溃` |
| **`docs(...)`** | 只修改了文档或注释 | `docs(guide): 补充 JIT 智能体技能自动唤醒规则` |
| **`style(...)`** | 改了 CSS、主题、毛玻璃等样式 | `style(css): 调整 Chat 气泡透明度与 Swiss font` |
| **`refactor(...)`**| 重构核心代码，不加功能改bug | `refactor(alignment): 优化流形仿射对齐的 NumPy 矩阵运算` |
| **`test(...)`** | 增加/调整了测试用例 | `test(visual): 部署 Playwright 视觉对比测试骨架` |

> [!TIP]
> **为什么要用约定式前缀？**
> AI（`doc-coauthoring` 技能）可以**直接通读你的 Git history 前缀**，在 1 秒内自动帮你分类生成极其专业的《系统迭代与版本更迭白皮书》，直接作为参赛技术报告打包提交，评委直接给满分！

---

## 📌 手动划重点 2：Playwright 前端视觉回归比对测试 (Pixel Comparison)

当 AI 帮你大改了前端 Vue 组件样式后，如果你想做一次像素级的“去 AI 廉价味瑞士风样式防错位校验”：

### 1. 首次生成基准图 (仅需在第一次或 UI 大改版时运行一次)
进入 `frontend` 目录，运行以下命令生成基准快照（会自动在 `tests` 目录下存图）：
```powershell
cd frontend
npx playwright test tests/visual_regression.spec.js --update-snapshots
```

### 2. 日常运行视觉对比校验
当你日常怀疑某处样式被 AI 改错位了，在终端运行以下命令：
```powershell
cd frontend
npx playwright test tests/visual_regression.spec.js
```
* **自动判定结果**：
  * **`PASS`**：页面排版高度对齐，完美符合极简瑞士风！
  * **`FAIL`**：某个圆角、阴影或字体发生偏离/错位，测试会自动抛出红字拦截，强迫 AI 重新修改！
