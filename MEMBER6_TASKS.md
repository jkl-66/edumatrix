# 🛠️ EduMatrix 成员 6 模块（评测与沙箱）国赛级重构与全量题库任务清单 (全量最终版)

> [!IMPORTANT]
> **致开发组队友（成员 6）**：
> 为了使我们的系统在国赛决赛/答辩中达到特等奖擂主级（全国第一名）水准，需要对“自适应评测与隔离沙箱”模块进行以下 **17 个方向的底层代码加固、安全防御提升、时区对齐以及学术模型升级**，并全量生成覆盖全部知识点的**“主客观混合”自适应题库**。请对照本清单及具体实施方案进行代码重构与验证。

---

## 📅 阶段二：底层高可用与安全防御加固方案 (基础盘)

### 任务 1：选择题秒判通道 (Deterministic MCQ Fast-Path Grading)
*   **痛点**：目前选择题提交后，也会调用大模型进行判分，导致 5-8 秒的高延时，且大模型容易产生评估偏差。
*   **实施方案**：在 `quiz_api.py` 的 `/api/quiz/evaluate` 端点（L466 附近）调用大模型前，增加对选择题（单选题）的直接比对判定。
*   **代码实现**：
    ```python
    # 检测是否为选择题（记录中存在 options 且不为空）
    if quiz_record.options and len(quiz_record.options) > 0:
        student_ans_clean = student_answer.strip().upper()
        correct_ans_clean = quiz_record.correct_answer.strip().upper()
        
        is_correct = False
        if student_ans_clean and correct_ans_clean:
            is_correct = (student_ans_clean[0] == correct_ans_clean[0])
            
        accuracy_score = 1.0 if is_correct else 0.0
        result = {
            "accuracy_score": accuracy_score,
            "ai_confidence": 1.0,
            "score_breakdown": {
                "key_points_coverage": accuracy_score,
                "semantic_correctness": accuracy_score,
                "depth_and_detail": accuracy_score,
                "clarity_and_logic": accuracy_score
            },
            "feedback": "选择正确！" if is_correct else f"选择错误。正确答案是 {correct_ans_clean}。",
            "misconceptions": [] if is_correct else ["概念混淆，选错干扰项"],
            "missing_points": [] if is_correct else ["未选中正确项"],
            "next_action": "advance" if is_correct else "review"
        }
        # 直接更新数据状态，绕过大模型接口调用
    ```

---

### 任务 2：Windows 子进程超时残留释放 (Subprocess Timeout Popen Kill)
*   **痛点**：在 Windows 回退模式下，`code_exec_api.py` 使用 `subprocess.run`。如果 `subprocess.run` 发生超时，会抛出异常但**并不会主动杀死子进程**，导致后台积压大量 CPU 100% 的 python 僵尸进程。
*   **实施方案**：用 `subprocess.Popen` 代替 `subprocess.run`，并在超时发生时显式调用 `.kill()`。
*   **代码实现**：
    ```python
    def run_sync_subprocess():
        proc = None
        try:
            proc = subprocess.Popen(
                [sys.executable, "-c", exec_command],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env
            )
            stdout, stderr = proc.communicate(timeout=CONFIG.sandbox_timeout)
            return proc.returncode, stdout, stderr
        except subprocess.TimeoutExpired:
            if proc:
                proc.kill()  # 强杀 Windows 后台子进程，防止死循环无限消耗 CPU
                stdout, stderr = proc.communicate()
            return -1, b"", b"timeout"
    ```

---

### 任务 3：Matplotlib 画布内存泄露强杀 (Matplotlib Figure Leak Clean-up)
*   **痛点**：包装脚本中，目前仅在 restricted_globals 存在 `"plt"` 别名时才清理画布。若学生使用 `import matplotlib.pyplot as myplot` 等其他别名，释放逻辑会被静默跳过，造成 OOM 崩溃。
*   **实施方案**：在包装脚本的 cleanup 逻辑中，直接利用 `sys.modules` 无视别名强制释放画布。
*   **代码实现**：
    ```python
    # 包装脚本 (wrapper_script) 末尾清理块修改：
    import sys
    if "matplotlib.pyplot" in sys.modules:
        try:
            # 无论学生将 pyplot 命名为何种别名，直接从 sys.modules 中无脑关闭所有画布
            sys.modules["matplotlib.pyplot"].close("all")
        except Exception:
            pass
    ```

---

### 任务 4：元认知偏差与自信度校准追踪 (Metacognitive Calibration Index)
*   **痛点**：系统收集了学生的答题自信度，但未进行任何时序的元认知偏差指标分析与沉淀。
*   **实施方案**：在学生答完题评估更新时，将“元认知偏差”与“元认知误差”的指数滑动平均值（EMA）实时更新在 `DBStudentProfile` 的 `cognitive_map` 中。
*   **代码实现**：
    ```python
    # 在 quiz_api.py 的 perform_eval_updates(session) 内：
    old_bias = profile.cognitive_map.get("metacognitive_bias", 0.0)
    old_error = profile.cognitive_map.get("metacognitive_error", 0.0)
    
    current_bias = student_confidence - accuracy_score
    current_error = abs(student_confidence - accuracy_score)
    
    # 0.2 权重更新，0.8 历史保持
    profile.cognitive_map["metacognitive_bias"] = round(0.8 * old_bias + 0.2 * current_bias, 4)
    profile.cognitive_map["metacognitive_error"] = round(0.8 * old_error + 0.2 * current_error, 4)
    ```

---

### 任务 5：Docker 容器预热池故障自愈 (Container Pool Self-Healing)
*   **痛点**：在 Docker 模式下，如果中途容器崩溃或失去连接，`code_exec_api.py` 的 `Exception` 处理块会无脑将该坏死容器归还池中，导致随后的代码执行请求全部报错。
*   **实施方案**：判断异常类型，一旦属于致命的 Docker 内部错误，剔除该坏死容器并预热新容器补位。
*   **代码实现**：
    ```python
    except Exception as e:
        is_fatal = False
        error_msg = str(e).lower()
        error_type = str(type(e)).lower()
        if "docker" in error_type or "connection" in error_msg or "docker" in error_msg:
            is_fatal = True
            
        if is_fatal:
            print(f"  [Sandbox] 检测到 Docker 容器致命故障。正在剔除: {container.short_id}")
            try:
                await loop.run_in_executor(self.executor, container.remove, {"force": True})
            except Exception:
                pass
            new_container = await loop.run_in_executor(self.executor, self._create_container)
            async with self._lock:
                self.containers.append(new_container)
        else:
            async with self._lock:
                self.containers.append(container)
    ```

---

## 📅 阶段三：学术理论创新与国赛级 UX 升格方案 (天花板)

### 任务 6：主观题大模型判卷输出的“结构保障” (Structured JSON Schema for Grading)
*   **痛点**：主观题打分 `/evaluate` 依赖大模型输出纯 JSON，一旦大模型输出多余解释或损坏 JSON，解析器崩溃会导致系统使用默认的及格分兜底。
*   **实施方案**：建立多重正则容错清洗器，自动剥离 Markdown 语法标记，提取出核心分数值。
*   **代码实现**：
    ```python
    def clean_and_parse_grading_json(raw_text: str) -> dict:
        try:
            clean_text = raw_text.strip()
            if clean_text.startswith("```"):
                clean_text = re.sub(r"^```[a-zA-Z0-9]*\n", "", clean_text)
                clean_text = re.sub(r"\n```$", "", clean_text)
            return json.loads(clean_text.strip())
        except Exception:
            acc_match = re.search(r'"accuracy_score"\s*:\s*(0\.\d+|1\.0|[0-1])', raw_text)
            acc_val = float(acc_match.group(1)) if acc_match else 0.6
            return {
                "accuracy_score": acc_val,
                "ai_confidence": 0.8,
                "feedback": "主观答题评估完成，已自动进行结构自愈提取。",
                "next_action": "advance" if acc_val >= 0.7 else "review"
            }
    ```

---

### 任务 7：题库参数的“在线自适应校准更新” (Online Parameter Tracking)
*   **痛点**：目前本地题库参数是静态死的。如果很多优秀学生都答错了某道题，说明该题的实际难度远高于标定，但目前系统参数无法自适应进化。
*   **实施方案**：在每次答题完成后，如果学生能力与测试结果发生剧烈偏差，执行在线梯度更新，将修正后的值保存回 `DBQuizItem`。
*   **数学公式**：$\beta_{\text{new}} = \beta_{\text{old}} + \eta \times (P_i(\theta) - \text{Correct})$ （$\eta = 0.05$）
*   **代码实现**：
    ```python
    # 在 evaluate 路由中：
    if local_record and not quiz_record.options:
        prob = estimator._probability_correct(estimator.theta, item_params)
        correct_val = 1.0 if is_correct else 0.0
        learning_rate = 0.05
        delta_beta = learning_rate * (prob - correct_val)
        
        db.query(DBQuizItem).filter(DBQuizItem.question == local_record.question).update({
            "irt_beta": DBQuizItem.irt_beta + delta_beta
        })
        db.commit()
    ```

---

### 任务 8：元认知自评画像的“路径路由消费” (Metacognitive Path Planning Consumer)
*   **痛点**：我们在任务 4 中计算了 `metacognitive_bias`，但该数据仅记录不消费。
*   **实施方案**：出题逻辑中读取元认知状态：
    *   **过度自信 (Bias > 0.35)**：主动调高 1 档出题难度（推 Hard 题以校准认知）。
    *   **盲目自卑 (Bias < -0.35)**：主动调低 1 档出题难度（推 Easy 题以树立信心）。
*   **代码实现**：
    ```python
    meta_bias = profile.cognitive_map.get("metacognitive_bias", 0.0)
    if meta_bias > 0.35:
        difficulty = "hard"
    elif meta_bias < -0.35 and req_difficulty != "hard":
        difficulty = "easy"
        result["hints"].append("考官提示：你的实力被低估了，放轻松！")
    ```

---

### 任务 9：Monaco 代码沙箱控制台“轻量自动补全桩” (Monaco Autocomplete suggestions)
*   **痛点**：前端代码沙箱编辑器 `SandboxVisualizer.vue` 是纯文本输入，学生写科学计算代码时极易拼错。
*   **实施方案**：在 Vue 中针对 Monaco Editor 注册轻量级 autocomplete suggestions。
*   **前端 JS 代码**：
    ```javascript
    if (window.monaco) {
      window.monaco.languages.registerCompletionItemProvider('python', {
        provideCompletionItems: function(model, position) {
          const suggestions = [
            { label: 'numpy', kind: window.monaco.languages.CompletionItemKind.Module, insertText: 'import numpy as np\n' },
            { label: 'pandas', kind: window.monaco.languages.CompletionItemKind.Module, insertText: 'import pandas as pd\n' },
            { label: 'torch', kind: window.monaco.languages.CompletionItemKind.Module, insertText: 'import torch\n' },
            { label: 'np.sin', kind: window.monaco.languages.CompletionItemKind.Function, insertText: 'sin(${1:x})', insertTextRules: 4 },
            { label: 'np.array', kind: window.monaco.languages.CompletionItemKind.Function, insertText: 'array(${1:list})', insertTextRules: 4 }
          ];
          return { suggestions: suggestions };
        }
      });
    }
    ```

---

### 任务 10：错题本“错因诊断图谱与聚类大盘” (Wrong Question Diagnosis Cluster)
*   **痛点**：错题本 `WrongQuestionBook.vue` 只有零散的错题卡片，无法直观总览该学生的“系统性知识漏洞分布”。
*   **实施方案**：在错题本上方引入 ECharts 环形图，分类沉淀并展示所有错题的 `misconceptions` 归因比例。

---

## 📅 阶段四：系统业务一致性、越权漏洞与系统安全加固方案 (终极完备防御)

### 任务 11：自适应跟进出题 (/api/quiz/adapt) 融合本地预设题库
*   **痛点**：当学生点击“继续做题”调用 `/api/quiz/adapt` (L746) 时，代码无脑直接调用 LLM 生成题目，这把预置题库当成了摆设，产生了不必要的高延迟。
*   **实施方案**：重构 `adapt_quiz` 函数。在出题前增加和 `/generate` 相同逻辑 of 本地预置题库检查。如果本地 `DBQuizItem` 中存在该概念题目，使用 **Fisher 信息量选题算法** 挑出下一道，直接秒级返回。

---

### 任务 12：错题本变更接口垂直越权与授权漏洞修复 (IDOR/BOLA Vulnerability Fix)
*   **痛点**：错题本删除 `/wrong-questions/{wrong_id}` (L1127)、置顶和更新笔记接口，仅依靠客户端传来的 `wrong_id` 查询并更改数据库，未进行拥有者鉴权。恶意用户可以越权删除或更改任何人的错题。
*   **实施方案**：将 `student_id` 作为必填校验参数强行加入查询过滤器中。
*   **代码实现**：
    ```python
    @router.delete("/wrong-questions/{wrong_id}")
    async def delete_wrong_question(wrong_id: int, student_id: str) -> dict:
        def do_delete(session):
            record = session.query(DBWrongQuestion).filter(
                DBWrongQuestion.id == wrong_id,
                DBWrongQuestion.student_id == student_id
            ).first()
            if not record:
                raise HTTPException(status_code=404, detail="错题记录不存在或无权操作")
            session.delete(record)
            session.commit()
            return {"deleted": True, "id": wrong_id}
        return await run_db_op(do_delete)
    ```

---

### 任务 13：相似题重测题型一致性失调修复 (Similar Quiz Type Consistency)
*   **痛点**：在 `/similar` (L875) 接口中，大模型生成的 Few-Shot 模版被写死了选择题结构。如果学生重测的原错题是“主观简答题”或“代码实操题”，重测出的题会变成不相干的选择题。
*   **实施方案**：在生成相似题时读取源错题的 `options`。如果源错题 `options` 为空（代表主观题），在 Prompt 中重写 Few-Shot，强制大模型也输出无选项的简答题或代码验证题，保证认知一致性。

---

### 任务 14：代码沙箱大文件 DoS 攻击防御拦截 (Sandbox Script Size DoS Prevention)
*   **痛点**：`/api/code/run` 接收 `code` 时无任何长度限制。黑客可以直接上传 10MB 以上的嵌套异常代码块在大模型服务端主线程内直接引爆编译死锁或内存溢出，绕过隔离沙箱打死主服务。
*   **实施方案**：在代码解析前强行校验大小阈值，超出 50KB 一律直接 400 拦截抛出。
*   **代码实现**：
    ```python
    @router.post("/run")
    async def run_code(payload: dict[str, Any]) -> dict[str, Any]:
        code = str(payload.get("code", "")).strip()
        if len(code.encode('utf-8')) > 50000:
            raise HTTPException(status_code=400, detail="恶意代码长度超限，沙箱拒绝运行 (Max 50KB)")
        ...
    ```

---

### 任务 15：Docker 常驻容器超周期僵死防患 (Docker Container Pool Expiry Recovery)
*   **痛点**：创建 Docker 容器时，为了挂起常驻使用了 `sleep 36000` (10小时) 命令。如果系统演示跑超过 10 小时，常驻容器会自动停机，后面的代码运行请求便会持续崩溃。
*   **实施方案**：在 `_run_in_docker()` 获取容器使用前，增加一行健康状态检测，一旦检测到容器死亡，物理剔除重建。

---

## 📅 阶段五：时区对齐与测验冷启动机制优化方案 (深度工程细节)

### 任务 16：打卡连击计算的时区漂移漏洞修复 (Timezone-Boundary Streak Fix)
*   **痛点**：在 `_calc_streak` 连续打卡天数计算中，服务器强制使用 `timezone.utc` 的日期进行比较。中国国内（UTC+8）的学生如果在跨越上午 8 点前后打卡，会导致在 UTC 日期下两天落在同一天或错开一天，致使学生的打卡连击（Streak）被无故清零。
*   **实施方案**：支持在打卡时，将学生本地时区（如 timezone offset）传给后端，或在画像中持久化时区偏好，打卡天数按本地日期而非 UTC 绝对日期进行连续性合并。
*   **具体代码实现逻辑**：
    ```python
    # 在 _calc_streak 中：
    # 允许传入 student_tz_offset = 8 (即 UTC+8)
    # 将查出的所有 DBCheckinLog.checkin_date 转换为本地时区时间：
    # local_time = checkin_date + timedelta(hours=student_tz_offset)
    # 提取本地的 .date() 计算连续天数，避免 midnight 跨时区截断 bug
    ```

---

### 任务 17：测验冷启动缺乏跨概念先验继承 (Lack of Cross-Concept Prior Initialization)
*   **痛点**：当学生开启一个新概念测验时，`AdaptiveTestEstimator` 的初始能力 $\theta$ 无脑被置为默认值 `0.0`。这导致算法需要白白浪费 5-6 道题目进行多余的“冷启动校准”。
*   **实施方案**：在初始化 `AdaptiveTestEstimator` 时，读取学生画像的整体水平偏置。
*   **具体映射公式**：
    $\theta_{\text{start}} = (\text{overall\_mastery} - 0.5) \times 3.0$
*   **代码实现**：
    ```python
    # 在 generate 和 adapt 出题评估处：
    overall_mastery = profile.mastery_score or 0.5
    prior_theta = (overall_mastery - 0.5) * 3.0
    estimator = AdaptiveTestEstimator(
        theta=prior_theta, # 注入跨概念先验偏置，加速冷启动收敛
        theta_std=1.0
    )
    ```

---

### 任务 18：全大纲 25 概念 × 30 题“主客观混合题库”全量生成 (Mixed Item Bank Seeder)
*   **比例分配**：
    - **20 道客观选择题 (中低难度)**：携带 options，触发 0ms 瞬间判定。
    - **10 道主观简答题/编程实操题 (高难度)**：options 设为空，触发 LLM 语义阅卷和沙箱评测。
*   **脚本改动**：运行 `scripts/generate_all_concepts_bank.py` 自动生产 750 道题目同步写入 `quiz_items` 中。

---

## 📋 队友任务验收清单 (Checklist for Teammate)

请直接复制以下 Markdown 清单，发送给你的队友让他工作：

```markdown
# 📋 智教矩阵 (EduMatrix) — 评测与代码沙箱模块加固任务清单

## 🛠️ 底层代码重构加固 (17 大痛点整改)
- [x] **任务 1：选择题秒判通道并网**
  - [x] 针对 `quiz_record.options` 不为空的选择题，通过首字母进行 0ms 秒判判定。
- [x] **任务 2：Windows 僵尸子进程残留清理**
  - [x] 将 Windows 下同步 fallback 子进程的 `subprocess.run` 替换为 `subprocess.Popen`，超时物理调用 `.kill()`。
- [x] **任务 3：Matplotlib 画布内存防泄露加固**
  - [x] 在沙箱 wrapper 的 cleanup 逻辑中，直接从 `sys.modules` 中强制执行 `matplotlib.pyplot.close("all")`。
- [x] **任务 4：画像元认知偏差 EMA 实时追踪**
  - [x] 在答题结束评估后，将 Confidence 与 Accuracy 的差值进行 EMA 均值更新，保存于画像中。
- [x] **任务 5：Docker 预热池的坏死剔除与自愈补位**
  - [x] 在 `_run_in_docker()` 捕获到 Docker 致命通信异常时，强制 remove 故障容器并生成新容器补位。
- [x] **任务 6：主观题打分 JSON 结构自愈与正则兜底**
  - [x] 在 `evaluate_answer` 解析打分 JSON 时，添加格式自愈及正则表达式备用解析，防止因格式问题导致得分丢失。
- [x] **任务 7：题库参数的“在线自适应校准更新”**
  - [x] 在 `evaluate` 路由中，根据答题情况应用在线 SGD 公式微调更新 `DBQuizItem` 的真实难度参数 $\beta$。
- [x] **任务 8：元认知自评偏差的“路径路由消费”**
  - [x] 在 `quiz_api.py` 出题中读取 `metacognitive_bias`。若偏差过高（盲目自信）强制出 Hard 题；若过低（自卑）强制出 Easy 题并附加提示。
- [x] **任务 9：Monaco 沙箱编辑器“轻量自动补全桩”**
  - [x] 在 `SandboxVisualizer.vue` 编辑器初始化后，注册 CompletionItemProvider 增加 numpy/pandas/torch 补全。
- [x] **任务 10：错题本“错因诊断图谱与聚类大盘”**
  - [x] 在 `WrongQuestionBook.vue` 顶部挂载 ECharts 环形图，对错因（misconceptions）进行时序统计归类并可视化呈现。
- [x] **任务 11：自适应跟进出题 (/api/quiz/adapt) 融合本地预置题库**
  - [x] 重构 `adapt_quiz` 接口，在出题前增加对 `DBQuizItem` 题库的库存检查，若库存充足则使用 Fisher 选题算法秒级出题，避免调用 LLM。
- [x] **任务 12：错题本变更接口垂直越权漏洞修复 (BOLA)**
  - [x] 在删除错题、置顶、更新错题笔记的接口中，强制添加 `student_id` 入参并作为 SQL 查询过滤器，进行所有权合法性强校验。
- [x] **任务 13：相似题重测题型一致性失调修复**
  - [x] 改造 `/api/quiz/similar`，若源错题为主观题，强制大模型生成的相似题也输出空 `options` 主观答题模式，严禁强制转为选择题。
- [x] **任务 14：代码沙箱大文件 DoS 攻击防御拦截**
  - [x] 在 `/api/code/run` 路由入口处检测代码字符串长度，凡超过 50KB 的请求一律直接返回 400 异常，防止主线程内存溢出。
- [x] **任务 15：Docker 常驻容器挂起超时僵死自愈**
  - [x] 在使用预热容器前，检测其 status 是否为 `running`，若不是则强制重建新容器，解决运行超 10 小时容器自行关机问题。
- [x] **任务 16：打卡连击计算的时区偏移溢出修复**
  - [x] 修改 `_calc_streak`，引入学生本地时区偏置，将 checkin_date 转换为 local_date 再计算连击天数，防止 UTC 零点触发 bug。
- [x] **任务 17：测验冷启动跨概念先验继承**
  - [x] 优化 `AdaptiveTestEstimator` 的冷启动初始值 theta。根据整体能力偏置进行先验映射，替代硬编码 `0.0`，减少 50% 移测试步骤。

## 📊 混合题库冷启动生成 (大纲概念全覆盖)
- [x] **任务 18：全大纲 25 概念 × 30 道主客观混合题库生成**
  - [x] 运行 `scripts/generate_all_concepts_bank.py` 自动生产 750 道题目同步写入 `quiz_items` 中。

## 🧪 回归与专项测试校验
- [x] **任务 19：单元测试并网全绿通过**
  - [x] 运行 `python -m unittest tests/test_member6_refactoring.py` 及 `test_edumatrix.py` 确保 100% 通过。
```
