from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import auto, Enum
from pathlib import Path
from typing import Generator, Protocol

import requests

# ---------------------------------------------------------------------------
# Windows / 终端 ANSI 颜色支持检测
# ---------------------------------------------------------------------------
_SUPPORTS_COLOR: bool = False
if os.name == "nt":
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)
        mode = ctypes.c_uint32()
        if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
            kernel32.SetConsoleMode(handle, mode.value | ENABLE_VIRTUAL_TERMINAL_PROCESSING)
            _SUPPORTS_COLOR = True
    except Exception:
        _SUPPORTS_COLOR = sys.stdout.isatty()
else:
    _SUPPORTS_COLOR = sys.stdout.isatty()

# ---------------------------------------------------------------------------
# 将项目根目录加入 sys.path，方便导入 EduMatrix 核心模块
# ---------------------------------------------------------------------------
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

# ---------------------------------------------------------------------------
# 从 .env 文件加载环境变量（无需 python-dotenv，纯标准库）
# ---------------------------------------------------------------------------
def _load_dotenv(path: str | None = None) -> None:
    if path is None:
        path = os.path.join(_PROJECT_ROOT, ".env")
    if not os.path.isfile(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip("'\"")
            if key and not os.environ.get(key):
                os.environ[key] = value

_load_dotenv()

# ---------------------------------------------------------------------------
# 豆包 API 配置（通过 .env / 环境变量注入）
# ---------------------------------------------------------------------------
DOUBAO_API_KEY: str = os.getenv("DOUBAO_API_KEY", "")
DOUBAO_ENDPOINT: str = os.getenv("DOUBAO_ENDPOINT", "https://windhub.cc/v1/chat/completions")
DOUBAO_MODEL: str = os.getenv("DOUBAO_MODEL", "doubao-1-5-pro-32k-250115")
DOUBAO_TIMEOUT: int = int(os.getenv("DOUBAO_TIMEOUT", "120"))


# ===========================================================================
#  Part 1: DoubaoLLMBackend —— 豆包适配器，实现 LLMBackend 协议
# ===========================================================================
class LLMBackend(Protocol):
    """与 llm_client.py 一致的 LLM 协议接口。"""
    def generate(self, system_prompt: str, user_prompt: str, *, role: str) -> str: ...


_DOUBAO_SESSION: requests.Session | None = None

def _get_session() -> requests.Session:
    global _DOUBAO_SESSION
    if _DOUBAO_SESSION is None:
        _DOUBAO_SESSION = requests.Session()
        adapter = requests.adapters.HTTPAdapter(
            max_retries=requests.urllib3.Retry(
                total=3,
                backoff_factor=1.0,
                allowed_methods={"POST"},
                status_forcelist={429, 500, 502, 503, 504},
            ),
        )
        _DOUBAO_SESSION.mount("https://", adapter)
        _DOUBAO_SESSION.mount("http://", adapter)
    return _DOUBAO_SESSION


def _doubao_api_call(
    messages: list[dict],
    temperature: float = 0.7,
    max_tokens: int = 4096,
) -> dict:
    if not DOUBAO_API_KEY:
        raise RuntimeError("缺少 DOUBAO_API_KEY 环境变量。请在 .env 文件中配置。")

    payload = {
        "model": DOUBAO_MODEL,
        "messages": list(messages),
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {DOUBAO_API_KEY}",
    }

    last_error: Exception | None = None
    session = _get_session()
    for attempt in range(3):
        try:
            resp = session.post(DOUBAO_ENDPOINT, json=payload, headers=headers, timeout=DOUBAO_TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
            if "error" in data:
                raise RuntimeError(f"豆包 API 返回错误: {data['error']}")
            return data
        except requests.exceptions.SSLError as e:
            last_error = e
            time.sleep(1.0 * (attempt + 1))
        except requests.exceptions.ConnectionError as e:
            last_error = e
            time.sleep(1.5 * (attempt + 1))
        except requests.exceptions.HTTPError as e:
            status = e.response.status_code if e.response is not None else 0
            detail = ""
            try:
                detail = (e.response.text or "")[:500] if e.response is not None else ""
            except Exception:
                pass
            raise RuntimeError(f"豆包 API HTTP {status} 错误: {detail}") from e
        except requests.exceptions.Timeout as e:
            last_error = e
            time.sleep(2.0 * (attempt + 1))
    raise RuntimeError(f"豆包 API 连接失败（重试 3 次后）: {last_error}") from last_error


@dataclass
class DoubaoLLM:
    """豆包大模型后端,实现 LLMBackend 协议,可直接注入 EduMatrixSwarm。"""

    timeout: int = DOUBAO_TIMEOUT

    def generate(self, system_prompt: str, user_prompt: str, *, role: str = "助手") -> str:
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        data = _doubao_api_call(messages, temperature=0.7, max_tokens=4096)
        return data["choices"][0]["message"]["content"].strip()


# ===========================================================================
#  Part 2: Agent 日志 & 颜色系统
# ===========================================================================
class AgentLogger:
    colors = {
        "swarm":   "92",   # green - 编排引擎
        "profile": "93",   # yellow - 画像探针
        "planner": "96",   # cyan - 路径规划师
        "debate":  "95",   # magenta - DRAG 辩论
        "factory": "94",   # blue - 资源兵工厂
        "theory":  "97",   # white/bright
        "mapper":  "91",   # red
        "coder":   "92",   # green
        "quiz":    "93",   # yellow
        "director":"96",   # cyan
        "alignment":"95",  # magenta
        "evaluator":"94",  # blue
        "strategy":"92",   # green
        "info":    "0",    # default
        "error":   "91",
    }

    @staticmethod
    def _c(agent: str, text: str) -> str:
        if not _SUPPORTS_COLOR:
            return text
        code = AgentLogger.colors.get(agent, "0")
        return f"\033[{code}m{text}\033[0m"

    @staticmethod
    def header(agent: str, label: str) -> str:
        icon = {
            "swarm":  " [SWARM]",
            "profile":" [画像探针]",
            "planner":" [路径规划师]",
            "debate": " [DRAG辩论]",
            "factory":" [资源兵工厂]",
            "theory": "  [理论教授]",
            "mapper": "  [逻辑画师]",
            "coder":  "  [极客助教]",
            "quiz":   "  [考官智能体]",
            "director":" [虚拟导演]",
            "alignment":"[流形对齐]",
            "evaluator":"[量化评估师]",
            "strategy":" [学习策略]",
            "info":   "    INFO",
        }.get(agent, f"  [{agent.upper()}]")
        return AgentLogger._c(agent, f"\n{'='*64}\n{icon} {label}\n{'-'*64}")

    @staticmethod
    def trace(agent: str, line: str) -> str:
        return f"  {AgentLogger._c(agent, '|')} {line}"

    @staticmethod
    def divider(agent: str = "info") -> str:
        return AgentLogger._c(agent, f"{'='*64}")


# ===========================================================================
#  Part 3: 对话引擎 —— 接入完整 1+3+5 EduMatrixSwarm
# ===========================================================================
_PROFILES_DIR = Path(_PROJECT_ROOT) / "data" / "profiles"
_HISTORY_DIR = Path(_PROJECT_ROOT) / "data" / "chat_history"


@dataclass
class TurnRecord:
    step: int
    user_input: str
    profile_json: dict | None = None
    target: str = ""
    resource_summary: str = ""
    alignment_passed: bool = False
    learning_accuracy: float = 0.0
    strategy_actions: list[str] = field(default_factory=list)
    resource_contents: list[dict] = field(default_factory=list)
    timestamp: str = ""


@dataclass
class ChatSession:
    student_id: str = "chat-doubao-user"
    history: list[TurnRecord] = field(default_factory=list)
    step: int = 0
    verbose: bool = False

    def _ensure_history_dir(self) -> None:
        _HISTORY_DIR.mkdir(parents=True, exist_ok=True)

    def history_path(self) -> Path:
        self._ensure_history_dir()
        return _HISTORY_DIR / f"{self.student_id}.json"

    def save_history(self) -> None:
        self._ensure_history_dir()
        data = {
            "student_id": self.student_id,
            "total_turns": len(self.history),
            "updated": _utc_now(),
            "turns": [
                {
                    "step": t.step,
                    "user_input": t.user_input,
                    "target": t.target,
                    "alignment_passed": t.alignment_passed,
                    "learning_accuracy": t.learning_accuracy,
                    "resource_summary": t.resource_summary,
                    "strategy_actions": t.strategy_actions,
                    "profile_json": t.profile_json,
                    "resource_contents": t.resource_contents,
                    "timestamp": t.timestamp,
                }
                for t in self.history
            ],
        }
        with open(self.history_path(), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def load_history(self) -> list[TurnRecord]:
        p = self.history_path()
        if not p.exists():
            return []
        try:
            with open(p, encoding="utf-8") as f:
                data = json.load(f)
            turns = []
            for td in data.get("turns", []):
                turns.append(TurnRecord(
                    step=td["step"],
                    user_input=td["user_input"],
                    profile_json=td.get("profile_json"),
                    target=td.get("target", ""),
                    resource_summary=td.get("resource_summary", ""),
                    alignment_passed=td.get("alignment_passed", False),
                    learning_accuracy=td.get("learning_accuracy", 0),
                    strategy_actions=td.get("strategy_actions", []),
                    resource_contents=td.get("resource_contents", []),
                    timestamp=td.get("timestamp", ""),
                ))
            return turns
        except Exception:
            return []

    def profile_path(self) -> Path:
        return _PROFILES_DIR / f"{self.student_id}.json"

    def save_profile(self, profile_dict: dict) -> None:
        _PROFILES_DIR.mkdir(parents=True, exist_ok=True)
        with open(self.profile_path(), "w", encoding="utf-8") as f:
            json.dump({"student_id": self.student_id, "updated": _utc_now(), **profile_dict},
                      f, ensure_ascii=False, indent=2)

    def load_profile(self) -> dict | None:
        p = self.profile_path()
        if p.exists():
            try:
                with open(p, encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return None
        return None


def _utc_now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _swarm_process_msg(user_input: str, student_id: str, verbose: bool) -> Generator[str, None, dict]:
    """用真实 EduMatrixSwarm 管线处理一条用户消息。

    1+3+5 管线:
      [1 Hub]   Swarm Orchestrator 编排入口
      [3 Gov]   画像探针 → 路径规划师 → 量化评估师
      [DRAG]    正方/反方/法官 证据辩论清洗
      [5 Fac]   理论教授 | 逻辑画师 | 极客助教 | 考官智能体 | 虚拟导演
      [Align]   双曲流形跨模态对齐验证
      [Strategy]学习策略引擎
    """

    from agent_swarm import AGENT_MATRIX, EduMatrixSwarm, render_console_summary
    from config import CONFIG
    from models import CAUSE_LABELS, DIMENSION_LABELS, StudentProfile
    from rag_engine import hybrid_rag as _hybrid_rag

    # 展示 1+3+5 Agent 拓扑矩阵
    if verbose:
        yield AgentLogger.header("swarm", "1+3+5 Agent 拓扑矩阵")
        bands = {}
        for spec in AGENT_MATRIX:
            bands.setdefault(spec.band, []).append((spec.key, spec.name, spec.responsibility))
        for band_name, agents in bands.items():
            yield AgentLogger._c("swarm", f"\n  [{band_name}]")
            for key, name, resp in agents:
                yield f"    {AgentLogger._c(key, name)}  - {resp[:50]}"
        yield AgentLogger.divider("swarm")

    # 构建带豆包后端的 Swarm
    llm = DoubaoLLM()
    swarm = EduMatrixSwarm(rag=_hybrid_rag, llm=llm)

    # Step 1: Profile Probe Agent（画像探针）
    if verbose:
        yield AgentLogger.header("profile", "Agent 2: 画像探针 正在分析 10 维动态画像")
        yield AgentLogger.trace("profile", f"输入: {user_input[:80]}")
        t0 = time.time()

    try:
        package = swarm.process(user_input, student_id=student_id)
    except Exception as e:
        yield AgentLogger._c("error", f"\n[Swarm 管线错误] {e}\n")
        return
    elapsed = time.time() - (t0 if verbose else time.time())

    _save_swarm_profile(student_id, package.profile)

    # Step 1: Profile 结果 - 10 维画像
    if verbose:
        yield AgentLogger.trace("profile", f"耗时: {elapsed:.1f}s (全管线)")
        yield AgentLogger.trace("profile", f"目标知识点: {package.target}")
        yield AgentLogger._c("profile", "\n  ═══ 10 维动态学生画像 ═══")
        for line in _yield_dimension_report(package):
            yield line

        # Step 2: ZPD Planner（路径规划师）
        yield AgentLogger.header("planner", "Agent 3: 路径规划师 GraphRAG ZPD 学习路径")
        path_str = " -> ".join(package.retrieval.graph_context.learning_path)
        yield AgentLogger.trace("planner", f"知识路径: {path_str}")
        yield AgentLogger.trace("planner", f"召回证据: {len(package.retrieval.evidence)} 条")

        # Step 3: DRAG 辩论
        yield AgentLogger.header("debate", "DRAG 三角色证据辩论清洗")
        yield AgentLogger.trace("debate", "角色: 正方 / 反方 / 法官")
        kept = sum(1 for v in package.verdicts if v.keep)
        total = len(package.verdicts)
        yield AgentLogger.trace("debate", f"保留/总数: {kept}/{total}")
        for v in package.verdicts:
            mark = "✓ 保留" if v.keep else "✗ 剔除"
            yield f"  {AgentLogger._c('debate', mark)} {v.evidence_id}: pro={v.pro_score:.2f} con={v.con_score:.2f} judge={v.judge_score:.2f}"

        # Step 4-8: Resource Factory 5 Agents (并行)
        yield AgentLogger.header("factory", "Agent 5-9: 资源兵工厂 (5 Agent 并发生成)")
        agents = {
            "理论教授": ("theory", "专业讲义"),
            "逻辑画师": ("mapper", "思维导图"),
            "极客助教": ("coder", "代码实操案例"),
            "考官智能体": ("quiz", "练习题"),
            "虚拟导演": ("director", "虚拟人视频脚本"),
        }
        agent_order = {name: i for i, (name, _) in enumerate(agents.items())}
        for res in sorted(package.resources, key=lambda r: agent_order.get(r.agent, 99)):
            agent_key = agents.get(res.agent, (res.agent,))[0]
            yield AgentLogger.header(agent_key, f"{res.agent} → {res.resource_type}")
            yield AgentLogger.trace(agent_key, f"引用证据: {', '.join(res.citations)}")
            preview = res.content[:120].replace("\n", " ").strip()
            yield AgentLogger.trace(agent_key, f"输出预览: {preview}...")

        # Step 9: Manifold Alignment
        yield AgentLogger.header("alignment", "双曲流形跨模态对齐验证")
        status_text = "通过 ✓" if package.alignment.passed else "失败 ✗"
        yield AgentLogger.trace("alignment", f"对齐状态: {status_text}")
        yield AgentLogger.trace("alignment", f"Poincare 距离: {package.alignment.distance:.3f} (阈值: {package.alignment.threshold:.3f})")
        if package.alignment.conflicts:
            yield AgentLogger.trace("alignment", f"冲突: {', '.join(package.alignment.conflicts)}")
        if package.alignment.advice:
            yield AgentLogger.trace("alignment", f"建议: {package.alignment.advice}")

        # Step 10: Effect Evaluator
        yield AgentLogger.header("evaluator", "Agent 4: 量化评估师 回收信号")
        yield AgentLogger.trace("evaluator", f"预测正确率: {package.learning_signal.accuracy:.2%}")
        yield AgentLogger.trace("evaluator", f"沙盒错误率: {package.learning_signal.sandbox_error_rate:.2%}")
        yield AgentLogger.trace("evaluator", f"需重规划: {'是 ⚠' if package.learning_signal.needs_replan else '否 ✓'}")

        # Step 11: Learning Strategy
        yield AgentLogger.header("strategy", "学习策略引擎")
        if package.strategy_plan:
            yield AgentLogger.trace("strategy", f"核心原则: {package.strategy_plan.rationale}")
            for i, action in enumerate(package.strategy_plan.actions, 1):
                icon = "★" if action.priority == 1 else ("●" if action.priority == 2 else "○")
                yield f"  {icon} [{action.strategy.value}] {action.title}"
                yield f"    {AgentLogger._c('strategy', action.description[:120])}"

        yield AgentLogger.divider("swarm")

    # 构建返回数据
    resource_summaries = []
    for r in package.resources:
        resource_summaries.append(f"[{r.agent}] {r.resource_type}: {r.content[:60].replace(chr(10), ' ')}...")

    strategy_actions_list = []
    if package.strategy_plan:
        for a in package.strategy_plan.actions:
            strategy_actions_list.append(f"{a.title}: {a.description[:50]}")

    yield "__SWARM_RESULT__"
    yield {
        "target": package.target,
        "profile_dict": asdict(package.profile),
        "resource_summaries": resource_summaries,
        "alignment_passed": package.alignment.passed,
        "learning_accuracy": package.learning_signal.accuracy,
        "strategy_actions": strategy_actions_list,
        "package": package,
    }


def _yield_dimension_report(package) -> list[str]:
    lines: list[str] = []
    profile = package.profile
    from models import DIMENSION_LABELS

    for dim in profile.dimension_states.values():
        bar = _score_bar(dim.score)
        lines.append(f"    {AgentLogger._c('profile', dim.label[:8])}: {bar} {dim.score:.2f} | {dim.status}")

    if profile.learning_state_causes:
        lines.append(AgentLogger._c("profile", "\n    不会原因占比:"))
        for cause in sorted(profile.learning_state_causes.values(), key=lambda c: c.percentage, reverse=True):
            lines.append(f"      {cause.label}: {cause.percentage:.1f}% (置信度={cause.confidence:.2f}, 证据数={cause.evidence_count})")
            for intervention in cause.recommended_interventions:
                lines.append(f"        → {intervention}")
    return lines


def _score_bar(score: float, width: int = 10) -> str:
    filled = int(score * width)
    empty = width - filled
    return f"[{'█' * filled}{'░' * empty}]"


def _save_swarm_profile(student_id: str, profile) -> None:
    _PROFILES_DIR.mkdir(parents=True, exist_ok=True)
    path = _PROFILES_DIR / f"{student_id}.json"
    try:
        d = asdict(profile)
        d["_updated"] = _utc_now()
        with open(path, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _build_text_reply(package) -> str:
    """从 ResourcePackage 构建纯文本回复。"""
    parts = []
    for r in package.resources:
        parts.append(f"## {r.agent} / {r.resource_type}\n\n{r.content}")
    return "\n\n".join(parts)


# ===========================================================================
#  Part 4: 交互式 REPL
# ===========================================================================
_HELP_TEXT = """命令说明:
  /verbose   开关详细日志 (显示 1+3+5 Agent 完整编排)
  /profile   查看当前学生 10 维画像 (从 data/profiles/ 加载)
  /10d       查看 10 维画像明细
  /history   查看对话历史 (含每轮证据)
  /help      显示帮助
  /reset     重置对话
  /quit      退出"""


def _cmd_profile(session: ChatSession) -> None:
    pdata = session.load_profile()
    if not pdata:
        print(AgentLogger._c("profile", "  尚未生成学生画像。先问一个问题让 Agent 诊断。"))
        return

    from models import DIMENSION_LABELS, CAUSE_LABELS

    print()
    print(AgentLogger.header("profile", "10 维动态学生画像"))
    dims = pdata.get("dimension_states", {})
    for key, label in DIMENSION_LABELS.items():
        d = dims.get(key, {})
        score = d.get("score", 0)
        status = d.get("status", "N/A")
        bar = _score_bar(score)
        print(f"  {label:12s} {bar} {score:.2f} | {status}")

    causes = pdata.get("learning_state_causes", {})
    if causes:
        print(AgentLogger._c("profile", "\n  不会原因占比:"))
        for c in sorted(causes.values(), key=lambda x: x.get("percentage", 0), reverse=True):
            print(f"    {c['label']}: {c['percentage']:.1f}%")

    print(f"\n  画像文件: {session.profile_path()}")


def _cmd_history(session: ChatSession) -> None:
    n = len(session.history)
    hp = session.history_path()
    print(f"\n  {AgentLogger._c('info', f'对话历史 (共 {n} 轮)')}")
    print(f"  持久化文件: {hp}")
    if n == 0:
        print("  暂无对话历史。")
        return
    print(f"  {'='*50}")
    for i, turn in enumerate(session.history, 1):
        print(f"\n  [{i}] 用户: {turn.user_input[:60]}...")
        print(f"      时间: {turn.timestamp}")
        print(f"      目标: {turn.target}")
        print(f"      对齐: {'通过' if turn.alignment_passed else '失败'} | 正确率: {turn.learning_accuracy:.1%}")
        if turn.resource_summary:
            print(f"      资源: {turn.resource_summary[:60]}...")
        if turn.strategy_actions:
            for a in turn.strategy_actions[:3]:
                print(f"      >> {a[:60]}")
        if turn.resource_contents:
            print(f"      完整资源数: {len(turn.resource_contents)} 条（含 Agent 生成内容全文）")


def interactive_loop() -> None:
    print("=" * 70)
    print("  EduMatrix Agent (豆包 Doubao)  ——  全管线 1+3+5 Swarm")
    print("  " + "=" * 42)
    print("  输入 /verbose 开启详细日志 (观察所有 Agent 内部操作)")
    print("  输入 /profile 查看 10 维学生画像 (已持久化到文件)")
    print("  输入 /help 查看所有命令")
    print("=" * 70)

    session = ChatSession()

    # 启动时自动加载历史
    saved_history = session.load_history()
    if saved_history:
        session.history = saved_history
        session.step = len(saved_history)
        print(AgentLogger._c("info", f"  已加载 {len(saved_history)} 条历史对话（从 {session.history_path()}）"))
    else:
        print(AgentLogger._c("info", "  未找到历史对话，新会话开始。"))

    while True:
        try:
            user_input = input("\n>> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n再见！")
            break

        if not user_input:
            continue

        if user_input.lower() in ("/quit", "/exit", "/q"):
            print("再见！")
            break

        if user_input.lower() == "/help":
            print(_HELP_TEXT)
            continue

        if user_input.lower() == "/verbose":
            session.verbose = not session.verbose
            status = AgentLogger._c("swarm", "开启") if session.verbose else "关闭"
            print(f"Verbose 模式: {status}")
            if session.verbose:
                print(AgentLogger._c("info",
                    "  将展示: 1+3+5 Agent 拓扑 → 画像探针(10维) → 路径规划 → "
                    "DRAG辩论 → 5 Agent并发生成 → 流形对齐 → 量化评估 → 学习策略"))
            continue

        if user_input.lower() == "/profile" or user_input.lower() == "/10d":
            _cmd_profile(session)
            continue

        if user_input.lower() == "/history":
            _cmd_history(session)
            continue

        if user_input.lower() == "/reset":
            session = ChatSession()
            # also clear profile
            pp = session.profile_path()
            if pp.exists():
                pp.unlink()
            hp = session.history_path()
            if hp.exists():
                hp.unlink()
            print("对话已重置，历史记录已清除。")
            continue

        if session.verbose:
            print(AgentLogger._c("info", "\n>> 全管线 1+3+5 Swarm 运行中...\n"))

        session.step += 1
        print()

        result_data = {}
        for chunk in _swarm_process_msg(user_input, session.student_id, session.verbose):
            if isinstance(chunk, str) and chunk == "__SWARM_RESULT__":
                continue
            if isinstance(chunk, dict):
                result_data = chunk
            else:
                print(chunk, end="", flush=True)
        print()

        if result_data:
            # Build resource contents for persistence
            pkg = result_data.get("package")
            res_contents = []
            if pkg:
                for r in pkg.resources:
                    res_contents.append({
                        "agent": r.agent,
                        "resource_type": r.resource_type,
                        "content": r.content,
                        "citations": r.citations,
                    })
            turn = TurnRecord(
                step=session.step,
                user_input=user_input,
                profile_json=result_data.get("profile_dict"),
                target=result_data.get("target", ""),
                resource_summary="; ".join(result_data.get("resource_summaries", [])),
                alignment_passed=result_data.get("alignment_passed", False),
                learning_accuracy=result_data.get("learning_accuracy", 0),
                strategy_actions=result_data.get("strategy_actions", []),
                resource_contents=res_contents,
                timestamp=_utc_now(),
            )
            session.history.append(turn)
            session.save_history()  # 自动持久化
        else:
            session.history.append(TurnRecord(
                step=session.step,
                user_input=user_input,
                target="未知(管线异常)",
                timestamp=_utc_now(),
            ))
            session.save_history()

        # Display final reply
        if result_data and "package" in result_data:
            pkg = result_data["package"]
            # Show a compact text reply to the user
            for r in pkg.resources:
                header = AgentLogger._c(r.agent if r.agent in AgentLogger.colors else "info",
                                        f"\n{'─'*40}\n  [{r.agent}] {r.resource_type}\n{'─'*40}")
                print(header)
                # Show first 1000 chars per resource
                content = r.content[:1000]
                if len(r.content) > 1000:
                    content += "\n... (内容过长，已截断，完整内容见 data/profiles/)"
                print(content)

        # 保存画像摘要
        if session.verbose:
            _cmd_profile(session)


# ===========================================================================
#  Part 5: CLI 入口
# ===========================================================================
if __name__ == "__main__":
    if len(sys.argv) > 1:
        args = sys.argv[1:]
        verbose = "--verbose" in args or "-v" in args
        args = [a for a in args if a not in ("--verbose", "-v")]
        query = " ".join(args) if args else ""
        if query:
            session = ChatSession()
            session.verbose = verbose
            print(AgentLogger._c("info", f"处理: {query}"))
            print()
            for chunk in _swarm_process_msg(query, session.student_id, verbose):
                if isinstance(chunk, str) and chunk == "__SWARM_RESULT__":
                    continue
                print(chunk, end="", flush=True)
            print()
        else:
            print("用法: python scripts/chat_doubao.py [--verbose|-v] \"你的学习问题\"")
    else:
        interactive_loop()
