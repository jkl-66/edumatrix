# EduMatrix 本地代码运行故障诊断说明

> 诊断日期：2026-07-19  
> 适用环境：Windows、Python 3.11、无 Docker、`trusted_local` 本地研究演示模式  
> 诊断对象：打开页面或运行代码时提示 `ModuleNotFoundError: No module named 'matplotlib'`

## 1. 诊断结论

本次故障的直接原因不是项目依赖被转移、删除或卸载，而是后端服务使用的 Python 解释器与项目依赖所在的 Python 虚拟环境不一致。

当前项目的 `.venv` 环境中已经可以正常导入 Matplotlib、Pandas 和 scikit-learn；但是 `8000` 端口的实际监听进程是系统 Python：

```text
C:\Program Files\Python311\python.exe
```

项目依赖安装在：

```text
D:\project-edumatrix\edumatrix-main\.venv\Scripts\python.exe
```

代码执行接口会使用后端进程自身的 `sys.executable` 创建 Python 子进程。因此，只要浏览器连接到由系统 Python 启动的后端，代码子进程就会继续使用系统 Python，而不会自动使用项目 `.venv`。

故障链如下：

```text
旧的/混用的后端进程占用 8000
        -> 浏览器请求进入系统 Python 后端
        -> code_exec_api.py 使用该后端的 sys.executable
        -> 代码子进程继承系统 Python
        -> 系统环境没有项目所需的科学计算依赖
        -> ModuleNotFoundError: No module named 'matplotlib'
```

## 2. 用户可见现象

### 2.1 预期行为

在项目虚拟环境已经安装完整依赖，并将后端固定使用该虚拟环境时，以下代码应当能够运行：

```python
import matplotlib
import pandas
from sklearn.linear_model import LinearRegression
print("scientific dependencies are available")
```

### 2.2 实际行为

页面可以打开或部分功能可以使用，但点击代码运行、运行涉及 Matplotlib/Pandas/scikit-learn 的示例时出现模块导入错误：

```text
ModuleNotFoundError: No module named 'matplotlib'
```

这说明前端页面本身不一定完全不可用，而是当前后端解释器无法提供代码运行所需的依赖。页面能打开并不能证明代码执行使用了正确环境。

## 3. 已验证证据

### 3.1 项目 `.venv` 依赖验证成功

使用项目解释器执行导入检查，结果为：

```text
exe= D:\project-edumatrix\edumatrix-main\.venv\Scripts\python.exe
imports=OK
versions= 3.11.1 3.0.3 1.9.0
```

| 依赖 | 已验证版本 | 结论 |
|---|---:|---|
| Matplotlib | 3.11.1 | `.venv` 中存在且可导入 |
| Pandas | 3.0.3 | `.venv` 中存在且可导入 |
| scikit-learn | 1.9.0 | `.venv` 中存在且可导入 |

因此，当前不能把故障解释为“安装命令把依赖搬走了”。

### 3.2 `requirements.txt` 已声明相关依赖

当前依赖文件包含：

```text
matplotlib>=3.8.0
pandas>=2.2.0
scikit-learn>=1.4.0
```

依赖声明决定新环境应安装哪些包，但不会自动改变已经启动的 Python 进程，也不会替换占用端口的旧服务。

### 3.3 8000 端口实际由系统 Python 监听

端口查询结果显示：

```text
LocalAddress  LocalPort  State   OwningProcess
0.0.0.0       8000       Listen  38488
```

PID `38488` 的实际命令为：

```text
"C:\Program Files\Python311\python.exe" -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

这意味着浏览器访问 `http://127.0.0.1:8000` 时，实际访问的是系统 Python 服务，而不是一个明确由项目 `.venv` 提供的服务。

### 3.4 当前存在解释器混用的进程树

观察到的进程关系为：

```text
PID 14148  D:\project-edumatrix\edumatrix-main\.venv\Scripts\python.exe -m uvicorn ...
    |
    +-- PID 38488  C:\Program Files\Python311\python.exe -m uvicorn ...
```

这表明当前后端启动状态不是一个清晰的“单一 `.venv` 解释器服务”。它可能由旧启动窗口残留、重复启动或 Windows 下不同启动入口叠加造成。仅凭进程树无法断言系统 Python 子进程的历史来源，但可以确认解释器混用已经发生。

### 3.5 项目启动入口并不唯一

| 入口 | 当前行为 | 风险 |
|---|---|---|
| `start.bat` | 直接调用 `.venv\Scripts\python.exe -m uvicorn` | 新启动路径正确，但会绕过 `run.py` |
| `run.py` | 读取 `EDUMATRIX_RELOAD` 后调用 `uvicorn.run` | 可集中处理配置，但不能与旧进程并存 |
| `app/main.py` | 直接执行文件时固定使用 `reload=True` | 不应作为比赛演示启动入口 |

相关代码位置：

- [start.bat](D:/project-edumatrix/edumatrix-main/start.bat)：项目启动脚本和虚拟环境路径
- [run.py](D:/project-edumatrix/edumatrix-main/run.py)：`EDUMATRIX_RELOAD` 和 Uvicorn 启动逻辑
- [app/main.py](D:/project-edumatrix/edumatrix-main/app/main.py)：直接运行文件时的旧式 reload 入口
- [code_exec_api.py](D:/project-edumatrix/edumatrix-main/code_exec_api.py)：使用 `sys.executable` 创建代码执行子进程

## 4. 根因分析

### 4.1 直接根因：后端服务解释器错误

代码执行模块让子进程使用当前后端的 Python 解释器。这个设计能保证代码执行和后端使用同一依赖环境；但后端一旦由错误解释器启动，代码执行必然继承错误环境。

必须保证：

```text
8000 端口监听进程 = 项目 .venv 解释器
代码执行子进程解释器 = 8000 端口监听进程解释器
```

目前第一项不满足，第二项也随之错误。

### 4.2 诱发因素：旧服务没有被干净替换

修改 `start.bat` 只影响之后的新进程，不会让已经运行的系统 Python 进程自动切换解释器。旧进程继续占用 8000 时，新 `.venv` 服务可能启动失败，或者处于未监听端口的状态。

因此会出现“启动脚本看起来已经使用 `.venv`，但浏览器仍然访问旧系统 Python 服务”的现象。

### 4.3 诱发因素：多个启动入口行为不一致

`start.bat` 直接执行 Uvicorn，`run.py` 负责加载 `.env` 并控制 reload，而 `app/main.py` 的直接运行入口又固定开启 reload。多个入口同时存在时，用户从不同终端或 IDE 启动项目，可能产生重复服务、重载进程或不同解释器进程。

比赛演示应当只保留一条明确启动路径，并在启动前检查 8000 端口。

### 4.4 不应误判 `sys._base_executable`

Windows 虚拟环境内部的 `sys._base_executable` 可能显示：

```text
C:\Program Files\Python311\python.exe
```

这是虚拟环境基于哪个基础 Python 创建的元信息，不等于当前进程没有使用虚拟环境。判断当前环境应当看：

```python
import sys
print(sys.executable)
```

本次 `.venv` 导入检查已经确认当前项目解释器路径正确。

## 5. 为什么之前可以正常运行

目前没有保存此前每次启动时的进程命令、解释器路径和依赖快照，因此无法从证据还原唯一历史原因。合理可能性包括：

1. 之前的后端由项目 `.venv` 启动，代码子进程能够找到依赖。
2. 之前占用 8000 的系统 Python 环境中曾经安装过所需依赖。
3. 之前只运行了不需要 Matplotlib/Pandas/scikit-learn 的基础代码。
4. 修改启动文件后，旧服务仍在运行，新旧进程混在一起，浏览器访问的不是刚修改后的服务。

第 4 项与当前端口和进程证据最吻合。可以确定的是，不能通过“以前能运行”推断当前服务仍使用同一个解释器。

## 6. 修改内容与故障关系

### 6.1 依赖修改

`requirements.txt` 增加 Matplotlib、Pandas、scikit-learn，是为了覆盖代码示例和算法模块的实际导入需求，属于依赖补全，不会转移已有依赖。安装结果已经在项目 `.venv` 中验证成功。

### 6.2 启动修改

启动脚本已改为显式引用：

```text
D:\project-edumatrix\edumatrix-main\.venv\Scripts\python.exe
```

同时将默认 reload 关闭，以减少 Windows 下重复进程和解释器混用的机会。但是，启动脚本修改不会清理此前已经运行的系统 Python 进程。

### 6.3 结论

```text
依赖补全本身没有破坏项目；
启动环境没有完全收敛，旧服务与新服务发生了混用；
错误是在解释器错位后暴露出来的。
```

## 7. 影响范围

直接受影响的功能：

- 代码沙箱中的 Matplotlib 图表生成
- 使用 Pandas 的数据处理示例
- 使用 scikit-learn 的机器学习示例
- 任何依赖这些包的代码运行任务

不一定受影响的功能：

- 前端静态页面加载
- 认证和基础 API
- 不导入科学计算库的 Python 代码
- 默认不启用代码执行时的普通学习闭环

因此，页面能够打开、登录能够成功，并不能证明代码执行环境正确。

安全边界方面，`trusted_local` 是面向可信本机研究演示的受限子进程模式，不是 Docker 容器隔离，也不适合执行不可信用户代码。解释器修复只解决依赖一致性，不会把它变成生产级安全沙箱。

## 8. 建议修复顺序

以下步骤是建议方案，不等同于本报告生成时已经执行。

### 第一步：识别并关闭旧后端

只处理命令行中明确包含 `uvicorn app.main:app` 的后端，不要直接结束所有 Python 进程，以免关闭 IDE 语言服务。

```powershell
Get-CimInstance Win32_Process |
  Where-Object { $_.CommandLine -match 'uvicorn app\.main:app' } |
  Select-Object ProcessId, ParentProcessId, ExecutablePath, CommandLine
```

确认无误后结束列出的后端 PID：

```powershell
Stop-Process -Id <后端PID> -Force
```

### 第二步：确认 8000 已释放

```powershell
Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue
```

该命令不应再返回监听状态。

### 第三步：只使用项目 `.venv` 启动后端

```powershell
Set-Location D:\project-edumatrix\edumatrix-main
$env:EDUMATRIX_RELOAD = '0'
$env:EDUMATRIX_SANDBOX_MODE = 'trusted_local'
.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

比赛现场也可以使用 `start.bat`，但应先确保没有旧的 8000 服务。

### 第四步：核对监听进程解释器

```powershell
$backendConnection = Get-NetTCPConnection -LocalPort 8000 -State Listen
$backendPid = $backendConnection.OwningProcess
Get-CimInstance Win32_Process -Filter "ProcessId = $backendPid" |
  Select-Object ProcessId, ExecutablePath, CommandLine
```

合格结果的 `ExecutablePath` 必须是：

```text
D:\project-edumatrix\edumatrix-main\.venv\Scripts\python.exe
```

如果仍显示 `C:\Program Files\Python311\python.exe`，说明故障尚未修复。

## 9. 修复后的验证清单

### 9.1 解释器与依赖

```powershell
.venv\Scripts\python.exe -c "import sys; print(sys.executable); import matplotlib, pandas, sklearn; print('imports ok'); print(matplotlib.__version__, pandas.__version__, sklearn.__version__)"
```

预期：`sys.executable` 指向项目 `.venv`，输出 `imports ok` 和三个版本号。

### 9.2 后端健康检查

```powershell
Invoke-WebRequest http://127.0.0.1:8000/api/health
```

预期：返回 HTTP 200。

### 9.3 代码执行模式

```powershell
.venv\Scripts\python.exe scripts\trusted_local_smoke.py
```

预期：

- `mode` 为 `trusted_local`
- `execution_enabled` 为 `true`
- `print(6 * 7)` 输出 `42`
- `import os` 等不允许操作被拦截
- `outputs/trusted_local_smoke.json` 的 `result` 为 `passed`

### 9.4 科学计算依赖

在页面代码运行区依次执行：

```python
import matplotlib
print(matplotlib.__version__)
```

```python
import pandas as pd
data = pd.DataFrame({"score": [1, 2, 3]})
print(data["score"].sum())
```

```python
from sklearn.linear_model import LinearRegression
model = LinearRegression().fit([[1], [2], [3]], [2, 4, 6])
print(round(float(model.coef_[0]), 6))
```

预期输出分别为版本号、`6` 和 `2.0`。

### 9.5 进程一致性验收标准

| 检查项 | 合格标准 |
|---|---|
| 8000 端口监听进程 | 项目 `.venv` Python |
| 后端启动参数 | `python.exe -m uvicorn app.main:app` |
| reload | 比赛演示固定为关闭 |
| 代码执行子进程 | 由后端 `sys.executable` 创建 |
| 三个科学计算库 | 在同一 `.venv` 中可导入 |
| smoke test | `passed` |
| 系统 Python Uvicorn | 不占用项目 8000 端口 |

## 10. 后续工程改进建议

### 10.1 统一唯一启动入口

比赛交付时明确规定只使用 `start.bat`，或只使用 `run.py`，不要交替执行 `app/main.py`、`python run.py` 和手写 Uvicorn 命令。

### 10.2 启动时打印解释器路径

启动日志应明确输出：

```text
Python executable: D:\project-edumatrix\edumatrix-main\.venv\Scripts\python.exe
```

如果路径不是项目 `.venv`，应在服务启动阶段直接报错。

### 10.3 启动前增加端口归属检查

启动脚本应展示 8000 的 PID、命令行和解释器路径。这样可以在比赛现场第一时间发现旧服务。

### 10.4 启动前增加依赖检查

至少检查：

```python
import matplotlib
import pandas
import sklearn
```

检查失败时应显示当前 `sys.executable` 路径，而不是只显示笼统的服务器错误。

### 10.5 保留可复现环境信息

每次验收报告建议记录：

- Python 版本和 `sys.executable`
- 关键依赖版本
- 8000 端口监听进程路径
- `EDUMATRIX_SANDBOX_MODE`
- `EDUMATRIX_RELOAD`
- smoke test 结果
- 启动命令和执行日期

## 11. 事实等级

### 已确认事实

- 项目 `.venv` 可以导入 Matplotlib、Pandas、scikit-learn。
- `requirements.txt` 已声明这三个依赖。
- 8000 端口当时由系统 Python 进程监听。
- `code_exec_api.py` 使用后端的 `sys.executable` 创建代码执行子进程。
- 当前启动入口存在多套行为不完全一致的路径。

### 高可信根因判断

- 浏览器请求进入了错误或混用的 Python 后端环境。
- 代码子进程继承该后端解释器，因而找不到项目科学计算依赖。

### 尚未从历史日志确认的内容

- 之前正常运行时具体使用的是哪一个 Python 解释器。
- 系统 Python 环境是否曾经安装过 Matplotlib。
- 系统 Python 子进程究竟由旧启动窗口、重复启动还是 Windows 进程重载产生。

这些未确认项不影响当前修复方向，因为只要保证 8000 端口由项目 `.venv` 监听，代码执行链路就会回到同一个依赖环境。

## 12. 最终结论

本次故障本质是“运行时解释器错位”，不是“项目依赖被转移”。项目 `.venv` 中的依赖仍然存在，当前需要解决的是旧系统 Python 后端占用端口以及多启动入口造成的进程混用。

修复完成的判定条件不是“页面重新打开”，而是同时满足：

1. 8000 端口监听进程的 `ExecutablePath` 指向项目 `.venv`。
2. `.venv` 解释器可以导入 Matplotlib、Pandas 和 scikit-learn。
3. `trusted_local` smoke test 与页面中的科学计算代码均通过。

## 13. 修复后复验记录

本报告生成后已完成一键启动修复，最终复验时间为 2026-07-19。当前 `start.bat` 的执行顺序为：

```text
项目 .venv 预检
    -> 数据库健康检查
    -> 统一使用 .venv 启动 run.py
    -> 清理仅属于 EduMatrix 的旧后端
    -> 等待 /api/health 返回 200
    -> 检查并复用已有 Vite 5173 服务
    -> 打开 http://127.0.0.1:5173
```

### 13.1 运行时状态证据

通过当前服务的 `GET /api/code/status` 得到：

```json
{
  "mode": "trusted_local",
  "execution_enabled": true,
  "isolation": "trusted_local_child_process",
  "python_executable": "D:\\project-edumatrix\\edumatrix-main\\.venv\\Scripts\\python.exe",
  "multiprocessing_executable": "D:\\project-edumatrix\\edumatrix-main\\.venv\\Scripts\\python.exe"
}
```

Windows 进程管理器在虚拟环境派生进程上可能显示基础 Python 的宿主路径；因此最终判定以服务内部 `sys.executable`、代码子进程导入结果和 smoke test 为准，而不是只看 WMI 的 `ExecutablePath` 字段。

### 13.2 真实代码执行结果

通过认证后的 `/api/code/run` 实测：

| 场景 | 结果 |
|---|---|
| Pandas DataFrame 求和 | 输出 `6` |
| scikit-learn LinearRegression | 输出 `2.0` |
| Matplotlib 导入和绘图 | 成功，返回 Base64 图片 |
| `trusted_local` 基础 smoke | PASS |
| 不允许的 `os` 导入 | 被安全策略拦截 |

此前 Matplotlib 测试中显式导入 `io` 被代码安全策略拦截，错误内容是“沙箱禁用模块 io”，不是 Matplotlib 缺失；改用正常绘图示例后已经成功。

### 13.3 回归和构建结果

- 启动链路回归测试：5 passed；
- 正式测试：141 passed，1 skipped；
- 前端 `npm run build`：成功；
- 第二次执行 `start.bat`：后端重新健康启动，已有 Vite 服务复用，没有新增监听端口。

因此，本次故障的用户可见目标已经达到：在依赖已安装的前提下，双击 `start.bat` 即可拉起并直接使用，无需手动选择系统 Python，也无需安装 Docker。

## 14. 3D 示例输出截断修复记录

### 14.1 新故障现象

一键启动修复后，运行前端内置 3D 曲面示例时仍可能显示：

```text
输出已截断：超过本地研究模式的输出上限。
```

这不是 Python 依赖错误。3D 图像经过 PNG 编码和 Base64 编码后，通常大于普通文本上限 100KB。

### 14.2 原因

旧实现将普通 `print` 输出、错误输出和 Matplotlib 图片 Markdown 全部写入同一个 `LimitedBuffer(100000)`。3D 图片超过 100KB 后，Base64 字符串被从中间截断，前端得到不完整的 data URI，随后后端追加了普通输出截断提示。

### 14.3 修复

- 普通 stdout 保持 100KB 上限；
- Matplotlib 图片改用独立 `visual_buffer`；
- 新增 `EDUMATRIX_SANDBOX_MAX_VISUAL_BYTES`，默认 5MB；
- 子进程输出增加 `===VISUAL_SEPARATOR===`，后端解析后再合并为前端兼容的图片 Markdown；
- 图片超过 5MB 时显示专门的可视化截断提示，不伪装成普通文本截断；
- `/api/code/status` 新增 `max_visual_bytes`，便于现场确认配置。

### 14.4 复验结果

使用前端同款 50×50 网格 3D 曲面代码，通过真实认证 API 复验：

| 项目 | 结果 |
|---|---|
| 返回图像 | 完整 PNG Base64，输出约 196KB |
| 普通文本截断 | `false` |
| 可视化截断 | `false` |
| `max_output_bytes` | 100000 |
| `max_visual_bytes` | 5000000 |
| 3D 回归测试 | 通过 |
| 正式测试 | `143 passed, 1 skipped` |
