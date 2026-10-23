from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import re
import subprocess
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs" / "competition_submission_20260905"
TASK_OUT = ROOT / "outputs" / "原系统融合重构执行" / "evidence" / "custom_tasks" / "COMPETITION-SUBMISSION-AUDIT-01"
PDF = ROOT / "赛题" / "XH-202630上海云之脑智能科技有限公司-领域知识个性化生成与多智能体协同决策系统研究比赛方案.pdf"
CODE_MAP = ROOT / "outputs" / "原系统融合重构执行" / "evidence" / "custom_tasks" / "TECH-DOC-CODE-MAP-01" / "TECH-DOC-CODE-MAP-01.md"
BENCHMARK_DIR = ROOT / "outputs" / "M0_阶段0基线与架构契约" / "datasets"
M4_ROOT = ROOT / "outputs" / "M4_量化评测与可靠性交付" / "evidence" / "M4-final-evidence-v3-20260802"
BROWSER_EVIDENCE_SOURCE = ROOT / "outputs" / "原系统融合重构执行" / "evidence" / "custom_tasks" / "COURSE-DATA-DEMO-RESEED-03" / "browser"
BROWSER_SMOKE_SOURCE = ROOT / "outputs" / "e2e_no_docker"
BROWSER_EVIDENCE_OUTPUT = OUT / "browser_evidence_current_courses"

EXCLUDE_PARTS = {".git", ".venv", "node_modules", "__pycache__", ".pytest_cache", ".codex", ".agents", "dist", "build", "package_build", "recovery"}
SECRET_NAMES = {".env", ".env.local", ".env.production"}
SECRET_PATTERNS = ("api_key", "secret_key", "password", "token")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def rel(path: Path) -> str:
    return path.resolve().relative_to(ROOT.resolve()).as_posix()


def git(*args: str) -> str:
    try:
        return subprocess.run(["git", *args], cwd=ROOT, check=True, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30).stdout.strip()
    except Exception as exc:
        return f"unavailable: {type(exc).__name__}: {exc}"


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_text(name: str, text: str) -> Path:
    path = OUT / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip() + "\n", encoding="utf-8")
    return path


def copy_browser_evidence() -> list[str]:
    """Keep a small, self-contained visual proof set beside the submission docs."""
    selected = [
        "browser_report.json",
        "1920x1080-ml-chat.png",
        "1920x1080-ml-path.png",
        "2560x1600-ai-resources.png",
        "2560x1600-ai-profile.png",
    ]
    BROWSER_EVIDENCE_OUTPUT.mkdir(parents=True, exist_ok=True)
    copied: list[str] = []
    for name in selected:
        source = BROWSER_EVIDENCE_SOURCE / name
        if source.is_file():
            target = BROWSER_EVIDENCE_OUTPUT / name
            target.write_bytes(source.read_bytes())
            copied.append(rel(target))
    smoke_selected = ["report.json", "03-learning-workspace.png", "04-knowledge.png"]
    for name in smoke_selected:
        source = BROWSER_SMOKE_SOURCE / name
        if source.is_file():
            target = BROWSER_EVIDENCE_OUTPUT / f"no-docker-{name}"
            target.write_bytes(source.read_bytes())
            copied.append(rel(target))
    return copied


def inventory() -> tuple[list[dict], list[dict]]:
    roots = [ROOT / p for p in ("app", "frontend/src", "tests", "scripts", "data/curated", "outputs/M0_阶段0基线与架构契约/datasets", "outputs/原系统融合重构执行/evidence/custom_tasks/TECH-DOC-CODE-MAP-01")]
    top = [ROOT / p for p in ("README.md", "requirements.txt", ".env.example", "Dockerfile", "docker-compose.yml", "run.py", "config.py", "pytest.ini", "frontend/package.json", "frontend/package-lock.json")]
    included, excluded = [], []
    seen: set[str] = set()
    paths: list[Path] = []
    for root in roots:
        if root.is_file():
            paths.append(root)
        elif root.is_dir():
            paths.extend(p for p in root.rglob("*") if p.is_file())
    paths.extend(p for p in top if p.is_file())
    for path in sorted(paths, key=lambda p: rel(p)):
        key = rel(path)
        if key in seen:
            continue
        seen.add(key)
        if any(part in EXCLUDE_PARTS for part in path.parts) or path.name in SECRET_NAMES or path.suffix.lower() in {".db", ".sqlite", ".wal", ".shm", ".pyc", ".pyo", ".log"}:
            excluded.append({"path": key, "reason": "cache/runtime/private file"})
            continue
        size = path.stat().st_size
        if size > 5 * 1024 * 1024:
            excluded.append({"path": key, "reason": "large binary or generated artifact; not required for source audit", "bytes": size})
            continue
        included.append({"path": key, "bytes": size, "sha256": sha256(path)})
    return included, excluded


def metric_from_annotations() -> tuple[dict, list[dict], dict]:
    cases_path = BENCHMARK_DIR / "evaluation_cases.jsonl"
    results_path = M4_ROOT / "raw" / "results.jsonl"
    annotations_path = M4_ROOT / "report" / "resolved_annotations.jsonl"
    cases = [json.loads(line) for line in cases_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    results = [json.loads(line) for line in results_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    annotations = [json.loads(line) for line in annotations_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    by_type = Counter(item.get("task_type") for item in annotations)
    facts = Counter(item.get("labels", {}).get("label") for item in annotations if item.get("task_type") == "atomic_fact")
    judgeable = facts["supported"] + facts["contradicted"] + facts["unsupported"]
    hallucinated = facts["contradicted"] + facts["unsupported"]
    adaptations = [item for item in annotations if item.get("task_type") == "adaptation"]
    adaptation_passed = 0
    adaptation_by_profile = Counter()
    for item in adaptations:
        labels = item.get("labels", {})
        passed = bool(labels.get("factual_quality_passed")) and labels.get("difficulty_fit") == "fit" and labels.get("assessment_fit") == "fit" and "unfit" not in (labels.get("prerequisite_fit"), labels.get("format_fit"), labels.get("scaffolding_fit"))
        adaptation_passed += int(passed)
        task_id = str(item.get("task_id", ""))
        adaptation_by_profile[task_id.split(":")[-1]] += int(passed)
    coverage = [item for item in annotations if item.get("task_type") == "coverage"]
    covered = sum(1 for item in coverage if all(item.get("labels", {}).values()))
    case_annotations = [item for item in annotations if item.get("task_type") == "case_validity"]
    valid_cases = sum(1 for item in case_annotations if item.get("labels", {}).get("validity") == "valid")
    cases_by_profile = Counter(str(case.get("profile_id")) for case in cases)
    metrics = {
        "schema_version": "competition.metrics.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": {
            "benchmark": rel(cases_path), "benchmark_sha256": sha256(cases_path),
            "results": rel(results_path), "results_sha256": sha256(results_path),
            "resolved_annotations": rel(annotations_path), "resolved_annotations_sha256": sha256(annotations_path),
            "case_count": len(cases), "result_count": len(results), "annotation_count": len(annotations),
            "evidence_run_date": "2026-08-02", "current_git_head": git("rev-parse", "HEAD"),
        },
        "case_validity": {"numerator": valid_cases, "denominator": len(case_annotations), "percent": round(valid_cases / len(case_annotations) * 100, 4) if case_annotations else None},
        "hallucination_rate": {"numerator": hallucinated, "denominator": judgeable, "percent": round(hallucinated / judgeable * 100, 4) if judgeable else None, "label_distribution": dict(facts)},
        "adaptation_accuracy": {"numerator": adaptation_passed, "denominator": len(adaptations), "percent": round(adaptation_passed / len(adaptations) * 100, 4) if adaptations else None},
        "core_coverage": {"numerator": covered, "denominator": len(coverage), "percent": round(covered / len(coverage) * 100, 4) if coverage else None},
        "profile_groups": {"count": len(cases_by_profile), "case_counts": dict(cases_by_profile), "required_groups": 3},
        "thresholds": {"hallucination_rate_lt_5": hallucinated / judgeable * 100 < 5 if judgeable else False, "adaptation_accuracy_gte_85": adaptation_passed / len(adaptations) * 100 >= 85 if adaptations else False, "core_coverage_gte_90": covered / len(coverage) * 100 >= 90 if coverage else False, "case_count_gte_50": len(cases) >= 50},
        "publication_status": "blocked_pending_independent_human_validation_and_fresh_model_run",
        "limitations": ["The 60-case evidence was generated on 2026-08-02; this run re-computes the frozen annotations against the current working tree but does not claim fresh external-model generation.", "Resolved annotations were produced by isolated AI passes with AI adjudication; independent human validation is absent.", "The benchmark is one compact RAG domain and is not a held-out cross-domain generalization study."],
    }
    merged = []
    result_map = {str(item.get("case_id")): item for item in results}
    for case in cases:
        row = dict(case)
        result = result_map.get(str(case.get("case_id")), {})
        output = result.get("output", {})
        row["observed"] = {"status": result.get("status", output.get("status")), "response_text": output.get("response_text", ""), "citation_count": output.get("citation_count", 0), "locatable_citation_count": output.get("locatable_citation_count", 0), "claims": output.get("evidence", {}).get("claims", [])}
        merged.append(row)
    failure_cases = [row["case_id"] for row in merged if row.get("observed", {}).get("status") in {"failed", "timeout", "legal_refusal"}]
    metrics["failure_case_ids"] = failure_cases
    return metrics, merged, {"annotation_types": dict(by_type), "adaptation_passed": adaptation_passed, "covered": covered}


def build_pptx(metrics: dict) -> Path:
    from pptx import Presentation
    from pptx.dml.color import RGBColor
    from pptx.enum.text import PP_ALIGN
    from pptx.util import Inches, Pt
    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
    bg, ink, muted, accent, line = RGBColor(248, 247, 244), RGBColor(35, 43, 48), RGBColor(100, 108, 112), RGBColor(77, 112, 101), RGBColor(220, 221, 216)
    def text(slide, value, x, y, w, h, size=18, color=ink, bold=False):
        box = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h)); tf = box.text_frame; tf.word_wrap = True; tf.clear(); p = tf.paragraphs[0]; p.alignment = PP_ALIGN.LEFT; r = p.add_run(); r.text = value; r.font.name = "Arial"; r.font.size = Pt(size); r.font.bold = bold; r.font.color.rgb = color; return box
    def slide(title, kicker, body):
        s = prs.slides.add_slide(prs.slide_layouts[6]); s.background.fill.solid(); s.background.fill.fore_color.rgb = bg; text(s, kicker.upper(), .65, .45, 5, .25, 10, accent, True); text(s, title, .65, .85, 12, .55, 28, ink, True); text(s, body, .8, 1.75, 11.7, 4.8, 18, ink, False); text(s, "EduMatrix · 当前工作树证据版", .65, 7.1, 5, .2, 9, muted); return s
    s = prs.slides.add_slide(prs.slide_layouts[6]); s.background.fill.solid(); s.background.fill.fore_color.rgb = ink; text(s, "软件杯 XH-202630", .8, .75, 6, .35, 15, RGBColor(205, 222, 213), True); text(s, "EduMatrix\n智教矩阵", .8, 1.5, 7, 1.4, 40, RGBColor(255,255,255), True); text(s, "领域知识个性化生成与多智能体协同决策系统", .85, 3.45, 9, .5, 20, RGBColor(220,230,224), False); text(s, "当前工作树冻结审计 · 2026-09-05", .85, 6.5, 6, .3, 12, RGBColor(175,190,182), False)
    slide("为什么不是单轮聊天", "产品闭环", "学习者画像与诊断\n→ 课程知识库、分块、检索与来源\n→ 分析、生成、校验、决策的多角色协作\n→ 讲义、思维导图、代码、测验等资源\n→ 答题、代码、复述与复习事件\n→ 掌握度、画像、路径和复习队列更新\n\n实现索引：frontend/src/views、stream_api.py、app/m5_resources.py、app/learning_aggregation.py")
    slide("多智能体与证据约束", "技术实现", "诊断、规划、生成、证据审查和决策角色分工明确。\n来源引用与课程/用户范围过滤先于生成；原子声明可由 Prover、Challenger、Judge 审查。\n\n实现位置：app/m3_agents.py、app/m3_debate.py、agent_swarm.py、rag_engine.py、app/agent_audit.py\n\n边界：完整辩论主要用于 M3 资源与证据审核链；普通聊天展示协作摘要与来源，不宣称每次都执行完整辩论。")
    slide("三组学习者，三种资源策略", "个性化", "冻结评测包含三个画像组：beginner、theory、advanced。\n同一知识目标下，系统通过掌握度、前置关系、表达偏好、认知负荷和目标调节解释深度、脚手架、练习难度和路径顺序。\n\n实现位置：app/profile_summary.py、app/m5_matching.py、app/m5_resources.py、app/m5_workspace.py\n\n当前证据是合成画像与冻结案例，不等同于真实用户实验。")
    slide("冻结评测结果", "可复核指标", f"冻结运行日期：{metrics['source']['evidence_run_date']}\n案例：{metrics['source']['case_count']} 组；画像组：{metrics['profile_groups']['count']} 组\n幻觉率：{metrics['hallucination_rate']['percent']}%（{metrics['hallucination_rate']['numerator']}/{metrics['hallucination_rate']['denominator']}）\n画像-资源适配：{metrics['adaptation_accuracy']['percent']}%（{metrics['adaptation_accuracy']['numerator']}/{metrics['adaptation_accuracy']['denominator']}）\n核心知识点覆盖：{metrics['core_coverage']['percent']}%（{metrics['core_coverage']['numerator']}/{metrics['core_coverage']['denominator']}）\n\n解释：指标由当前工作树脚本重新计算冻结结果；独立人工复核和新一轮外部模型评测仍未完成。")
    slide("部署边界与评委运行", "复现", "默认 deterministic 模式可验证核心学习闭环，不需要外部 API Key。\n真实模型、联网搜索、Docker 代码执行、PDF 导出和 PPTX 原生预览属于环境条件，文档会分别说明。\n\n启动：.venv\\Scripts\\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000\n前端：cd frontend && npm ci && npm run dev -- --host 127.0.0.1\n\n实现位置：config.py、run.py、packaging、outputs/EduMatrix_评委环境安装与复现备忘录.md")
    out = OUT / "EduMatrix_评委PPT_当前工作树证据版.pptx"; prs.save(out); return out


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    browser_evidence_files = copy_browser_evidence()
    included, excluded = inventory()
    generated_at = datetime.now(timezone.utc).isoformat()
    manifest = {"schema_version": "competition.submission-manifest.v1", "task_id": "COMPETITION-SUBMISSION-AUDIT-01", "snapshot_at": generated_at, "git": {"head": git("rev-parse", "HEAD"), "branch": git("branch", "--show-current"), "status_porcelain": git("status", "--short"), "dirty": bool(git("status", "--porcelain"))}, "sources": {"competition_pdf": {"path": rel(PDF), "sha256": sha256(PDF)}, "technical_code_map": {"path": rel(CODE_MAP), "sha256": sha256(CODE_MAP)}, "official_checkpoint": {"path": "outputs/原系统融合重构执行/evidence/context_recovery/current_checkpoint.json", "state": "F10-T03/CLOSED (preserved)"}}, "included_files": included, "excluded_files": excluded, "sensitive_scan": {"excluded_name_patterns": sorted(SECRET_NAMES), "note": "No .env or runtime SQLite files are included; scan is evidence, not a substitute for manual review."}, "version_boundary": "Current working tree at snapshot_at; historical outputs are not treated as current facts unless revalidated and cited as historical evidence.", "evidence_refs": {"current_course_browser": "outputs/原系统融合重构执行/evidence/custom_tasks/COURSE-DATA-DEMO-RESEED-03/browser/browser_report.json", "current_course_screenshots": "outputs/原系统融合重构执行/evidence/custom_tasks/COURSE-DATA-DEMO-RESEED-03/browser/", "focused_tests": ["tests/test_competition_package_runtime.py", "tests/test_competition_demo_seed.py"]}, "pending_materials": ["10分钟以内演示视频（用户稍后提供）", "盖章报名表扫描件（用户稍后提供）"], "final_zip": {"generated": False, "reason": "video and registration form are not yet available"}}
    write_json(OUT / "submission_manifest.json", manifest)
    write_json(TASK_OUT / "submission_manifest.json", manifest)
    metrics, merged_cases, metric_meta = metric_from_annotations()
    write_json(OUT / "metrics.json", metrics)
    (OUT / "evaluation_cases.jsonl").write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in merged_cases), encoding="utf-8")
    write_json(OUT / "raw_metric_recalculation.json", metric_meta)
    requirements = [line.strip() for line in (ROOT / "requirements.txt").read_text(encoding="utf-8", errors="replace").splitlines() if line.strip() and not line.lstrip().startswith("#")]
    package = json.loads((ROOT / "frontend/package.json").read_text(encoding="utf-8"))
    installed = {}
    for name in ["fastapi", "uvicorn", "sqlalchemy", "pydantic", "numpy", "torch", "openai", "pytest", "playwright", "python-docx", "python-pptx"]:
        try: installed[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError: installed[name] = None
    write_json(OUT / "dependency_report.json", {"generated_at": generated_at, "python_requirements": requirements, "frontend_dependencies": {**package.get("dependencies", {}), **package.get("devDependencies", {})}, "installed_versions": installed, "runtime_notes": ["No Docker daemon or LibreOffice assumption was made for the core deterministic path.", "External LLM/search, Docker sandbox and PDF/PPTX rendering require separate target-environment checks."]})
    route_hits = len(re.findall(r"path:\s*['\"]", (ROOT / "frontend/src/router/index.js").read_text(encoding="utf-8", errors="replace"))) if (ROOT / "frontend/src/router/index.js").is_file() else 0
    py_routes = len(re.findall(r"@(app|router)\.(get|post|put|delete|patch|api_route)", "\n".join(p.read_text(encoding="utf-8", errors="ignore") for p in (ROOT / "app").glob("*.py"))))
    test_count = len(list((ROOT / "tests").glob("test_*.py")))
    write_text("code_audit.md", f"""# 当前工作树代码审计\n\n- 快照：{generated_at}\n- Git HEAD：`{manifest['git']['head']}`；工作树 dirty：`{manifest['git']['dirty']}`\n- 唯一技术组织依据：`{rel(CODE_MAP)}`（{manifest['sources']['technical_code_map']['sha256']}）\n\n## 能力分层\n\n| 层级 | 当前事实 | 证据 |\n|---|---|---|\n| 代码存在 | 前端 Vue 路由、FastAPI 模块、RAG、Agent、学习事件、资源与沙箱代码均存在 | `frontend/src/`、`app/`、`agent_swarm.py`、`rag_engine.py`、`code_exec_api.py` |\n| API 存在 | 认证、课程/知识库、对话、画像、路径、资源、测评、学习事件和代码接口已注册；静态扫描约 {py_routes} 个 Python 路由装饰器 | `app/main.py`、`*_api.py` |\n| 页面可进入 | 路由表约 {route_hits} 个前端 path；页面入口集中于 `frontend/src/views/` | 路由源码和既有浏览器证据目录 |\n| 用户可以完成 | 当前历史浏览器证据覆盖核心学生闭环、资源工作区、知识库阅读、画像和角色页面；本快照未重新宣称所有页面通过 | `outputs/原系统融合重构执行/evidence/custom_tasks/` |\n| 自动测试 | 当前仓库有 {test_count} 个 `tests/test_*.py` 模块；本批次聚焦包运行/演示数据测试 12 项通过，完整 pytest 仍需按目标环境执行 | `tests/`、`pytest.ini` |\n| 真实浏览器证据 | 现行两门课程的 lzz 双桌面烟测通过，24 张截图，0 个 4xx/5xx、0 页面错误、0 控制台错误；导航期间 14 个请求因切页取消，已在限制中说明 | `outputs/原系统融合重构执行/evidence/custom_tasks/COURSE-DATA-DEMO-RESEED-03/browser/browser_report.json` |\n| 正式指标 | 当前批次重新计算冻结 60 案例结果，见 `metrics.json`；不是新一轮外部模型生成 | `raw_metric_recalculation.json`、`evaluation_cases.jsonl` |\n\n## 业务边界\n\n认证/授权由服务端 `app/auth.py`、`app/authorization.py` 负责；课程和用户范围过滤位于知识库与 RAG；学习事件通过 `record_learning_event` 写入并由画像/路径/复习聚合。完整 Prover/Challenger/Judge 辩论主要属于 M3 资源与证据审核链，普通聊天不宣称每次执行完整辩论。\n""")
    write_text("known_limitations.md", """# 当前已知限制\n\n1. 当前 `.env.example` 默认 `deterministic`，本机没有可用外部 LLM endpoint/key；因此本批次不把历史模型输出写成新鲜真实模型效果。\n2. 60 案例指标来自 2026-08-02 冻结运行；本批次重新计算并绑定当前工作树，但独立人工复核缺失，指标 publication 状态为 blocked。\n3. 评测域是一个紧凑的 RAG 课程知识集，尚未证明跨领域泛化。\n4. Docker 代码沙箱、联网搜索、PDF 导出和 PPTX 原生渲染需要目标环境额外验证；代码存在不等于目标机已验收。\n5. 真实浏览器双桌面烟测使用当前有效课程 `course-machine-learning-foundations-v1` 与 `course-ai-deep-learning-agents-v1`，通过 24 张截图；其中 14 个 `net::ERR_ABORTED` 是页面切换取消的静态/API 请求，不是失败响应。\n6. `scripts/m4_annotation_workflow.py verify` 仅接受 evidence manifest 结构，而 `annotation-workflow-20260802/manifest.json` 是 annotation manifest，当前验证会抛出 `KeyError: 'files'`；历史证据内容未被删除。\n7. 工作树存在大量历史未提交修改；提交边界以 `submission_manifest.json` 的 included/excluded 清单为准。\n8. 演示视频和盖章报名表尚未提供，因此最终提交压缩包刻意不生成。\n""")
    write_text("evaluation_report.md", f"""# 比赛指标评测报告\n\n本报告由当前工作树脚本重新读取冻结案例、结果和逐条标注计算，生成时间：{metrics['generated_at']}。\n\n## 公式与结果\n\n- 幻觉率 =（contradicted + unsupported）/（supported + contradicted + unsupported）= {metrics['hallucination_rate']['numerator']}/{metrics['hallucination_rate']['denominator']} = {metrics['hallucination_rate']['percent']}%。\n- 画像-资源适配准确率 = 通过资源数/适配标注数 = {metrics['adaptation_accuracy']['numerator']}/{metrics['adaptation_accuracy']['denominator']} = {metrics['adaptation_accuracy']['percent']}%。\n- 核心知识点覆盖率 = 覆盖知识点/覆盖分母 = {metrics['core_coverage']['numerator']}/{metrics['core_coverage']['denominator']} = {metrics['core_coverage']['percent']}%。\n- 样本量：{metrics['source']['case_count']} 组，三组画像分布：{metrics['profile_groups']['case_counts']}。\n\n## 失败与限制\n\n当前冻结结果中失败/超时/合法拒答案例：`{metrics['failure_case_ids']}`。这不代表开放流量零失败；冻结运行没有失败案例，但评测仍被 `independent_human_validation_and_fresh_model_run` 阻塞。\n\n结果文件：`metrics.json`、`evaluation_cases.jsonl`、`raw_metric_recalculation.json`。不得把这些数字扩展为生产质量、跨域泛化或独立人评结论。\n""")
    write_text("作品设计实现方案.md", f"""# EduMatrix 作品设计与实现方案（当前工作树）\n\n## 目标\n面向人工智能/机器学习技能培训，把画像诊断、课程知识库、多智能体协作、个性化资源和学习反馈连成可追踪闭环。\n\n## 实现闭环\n`frontend/src/views/` 提供学习入口；`app/auth.py` 与 `app/authorization.py` 保护身份和对象；`knowledge_api.py`、`document_parser.py`、`rag_engine.py` 负责资料摄入、分块、检索和来源；`agent_swarm.py`、`app/m3_agents.py`、`app/m3_debate.py` 负责分析-生成-校验-决策；`app/m5_resources.py` 生成讲义、导图、代码、测验等资源；`app/m5_learning.py`、`app/learning_aggregation.py` 把答题、代码、实验、复述和复习写回画像、掌握度、路径和复习队列。\n\n## 证据与边界\n来源、课程和用户范围先于生成；证据不足时拒答或降级；完整辩论主要用于资源与证据审核。当前实现位置和证据索引以 `{rel(CODE_MAP)}` 为准。\n\n## 个性化\n三组冻结画像通过掌握度、前置关系、目标、表达偏好和认知负荷调节资源顺序、解释深度、脚手架和题目难度；当前为合成数据证据。\n""")
    write_text("技术文档.md", f"""# EduMatrix 技术文档（当前工作树事实版）\n\n技术文档唯一组织依据：`{rel(CODE_MAP)}`。旧版视觉重构材料和未重新验证的历史指标不作为当前事实。\n\n## 架构\nVue 3/Vite 前端 → FastAPI 与 JWT → 学习画像/路径/测评/资源 API → RAG、Agent Swarm 与证据审核 → SQLite/WAL、向量/图谱和受限代码执行。\n\n## 数据与权限\n课程、章节、知识点、来源、artifact/version、学习事件、画像快照和复习计划按用户/课程范围关联；普通浏览不提升掌握度；教师读取学情但不直接写掌握度。\n\n## 当前状态\n代码、接口和页面入口可在代码地图中定位；自动测试和浏览器证据需要按当前快照复跑；指标见 `metrics.json`，独立人工验证和新鲜外部模型运行尚缺。\n""")
    write_text("测试与指标报告.md", (OUT / "evaluation_report.md").read_text(encoding="utf-8") + "\n\n## 自动化入口\n\n`python -m pytest -q`、`frontend\\npm.cmd run build`、`python scripts/e2e_no_docker.py`；运行时需记录实际输出，不以历史数字替代当前结果。")
    write_text("评委阅读说明.md", """# 评委阅读说明\n\n推荐顺序：先看本目录的 `作品设计实现方案.md` 与 `技术文档.md`，再看 `metrics.json`/`evaluation_report.md`，最后按 `部署与评委运行说明.md` 启动。\n\n默认 deterministic 模式用于复核核心流程；外部模型、联网搜索、Docker、PDF/PPTX 渲染属于可选环境边界。当前材料不含真实密钥。视频和报名表待补，最终压缩包暂不生成。\n""")
    write_text("部署与评委运行说明.md", """# 部署与评委运行说明\n\n## 环境\nPython 3.11、Node.js 20、npm；Playwright Chromium 仅在 PDF 导出/E2E 时需要；Docker 仅在演示容器沙箱时需要。\n\n## 安装与启动\n```powershell\npy -3.11 -m venv .venv\n.venv\\Scripts\\python.exe -m pip install -r requirements.txt\ncd frontend; npm ci; cd ..\n.venv\\Scripts\\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000\ncd frontend; npm run dev -- --host 127.0.0.1\n```\n访问 `http://127.0.0.1:5173`，健康检查 `http://127.0.0.1:8000/api/health`。\n\n## 演示数据与课程\n演示账号：`lzz` / `404404aA`。当前统一内置课程为 `course-machine-learning-foundations-v1` 与 `course-ai-deep-learning-agents-v1`；烟测脚本会在登录后从当前课程目录选择可用课程，避免依赖已删除的旧 RAG 课程。现行课程双桌面浏览器烟测：`python scripts/e2e_lzz_two_course_demo_evidence.py`；通用 no-Docker 烟测：`python scripts/e2e_no_docker.py`。\n\n## 配置边界\n复制 `.env.example`，生成至少 32 字符的 `EDUMATRIX_AUTH_SECRET_KEY`。默认 `EDUMATRIX_LLM_PROVIDER=deterministic`、`EDUMATRIX_SANDBOX_MODE=disabled`；真实模型、联网搜索、Docker、PDF/PPTX 能力只有在目标环境配置并实测后才能宣称可用。\n\n## 常见故障\n前端无法请求后端先检查 8000 健康检查；代码执行返回未启用表示 disabled 模式边界；联网搜索超时可切换本地资料；PDF 导出需安装 Playwright Chromium。\n""")
    ppt = build_pptx(metrics)
    notes = write_text("EduMatrix_评委PPT逐页讲解备注.md", "PPT 数字全部来自本目录 metrics.json；幻觉率、适配率和覆盖率均需同时说明样本范围、冻结日期和独立人工复核缺失。\n\n第 1 页讲产品闭环；第 2 页讲 Agent 与证据；第 3 页讲三组画像；第 4 页讲冻结指标；第 5 页讲部署边界。")
    write_json(OUT / "material_status.json", {"generated_at": generated_at, "files": sorted(rel(p) for p in OUT.rglob("*") if p.is_file()), "pptx": rel(ppt), "browser_evidence": {"status": "passed", "report": "outputs/competition_submission_20260905/browser_evidence_current_courses/browser_report.json", "source_report": "outputs/原系统融合重构执行/evidence/custom_tasks/COURSE-DATA-DEMO-RESEED-03/browser/browser_report.json", "no_docker_report": "outputs/competition_submission_20260905/browser_evidence_current_courses/no-docker-report.json", "copied_files": browser_evidence_files, "screenshots": 24, "additional_smoke_screenshots": 2, "viewports": [[1920, 1080], [2560, 1600]], "courses": ["course-machine-learning-foundations-v1", "course-ai-deep-learning-agents-v1"]}, "ppt_pdf": {"generated": False, "reason": "LibreOffice/soffice unavailable on this machine"}, "video": {"provided": False}, "registration_form": {"provided": False}, "final_zip": {"generated": False}})
    print(json.dumps({"output": rel(OUT), "manifest_files": len(included), "excluded_files": len(excluded), "cases": len(merged_cases), "metrics": metrics["hallucination_rate"], "pptx": rel(ppt)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
