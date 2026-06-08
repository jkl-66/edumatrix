from __future__ import annotations

from dataclasses import asdict
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse

from agent_swarm import EduMatrixSwarm
from models import DIMENSION_LABELS, StudentProfile
from observability import TELEMETRY

# 👇 这里就是你刚刚丢失的 HOST 和 PORT 变量
HOST = "127.0.0.1"
PORT = 8000

swarm = EduMatrixSwarm()

MACHINE_LEARNING_DATASETS = [
    {
        "name": "Iris",
        "task": "分类入门、特征可视化、KNN/逻辑回归",
        "url": "https://archive.ics.uci.edu/dataset/53/iris",
        "note": "150 条样本、4 个特征、3 类鸢尾花，适合作为第一节机器学习实验。",
    },
    {
        "name": "Wine",
        "task": "多分类、标准化、正则化对比",
        "url": "https://archive.ics.uci.edu/dataset/109/wine",
        "note": "适合讲特征缩放、逻辑回归、SVM 和交叉验证。",
    },
    {
        "name": "Breast Cancer Wisconsin Diagnostic",
        "task": "二分类、混淆矩阵、precision/recall/F1",
        "url": "https://archive.ics.uci.edu/dataset/17/breast+cancer+wisconsin+diagnostic",
        "note": "569 条样本、30 个连续特征，适合模型评估与医学 AI 伦理讨论。",
    },
    {
        "name": "Diabetes",
        "task": "线性回归、回归评估、特征解释",
        "url": "https://scikit-learn.org/stable/datasets/toy_dataset.html#diabetes-dataset",
        "note": "scikit-learn 内置回归数据，可离线加载，适合回归单元。",
    },
    {
        "name": "California Housing",
        "task": "回归项目、数据划分、泛化误差",
        "url": "https://scikit-learn.org/stable/modules/generated/sklearn.datasets.fetch_california_housing.html",
        "note": "20640 条样本、8 个特征，适合作为综合回归项目。",
    },
    {
        "name": "MNIST 784",
        "task": "图像分类、多模态扩展、神经网络入门",
        "url": "https://www.openml.org/d/554",
        "note": "70000 张手写数字图像，作为拓展项目，不作为首轮核心依赖。",
    },
]


def _seed_demo_class() -> None:
    if swarm.profile_store:
        return
    samples = {
        "stu-ml-001": "我是计算机专业，期末要考机器学习。逻辑回归和混淆矩阵总混，accuracy 很高但 recall 低我不知道怎么判断，希望用图和例子一步步讲。",
        "stu-ml-002": "我线性回归能看懂公式，但一到项目就不会做数据预处理，只会照着答案改代码，想要代码实操和提示。",
        "stu-ml-003": "我过拟合和正则化分不清，训练集分数高就以为模型好，题干长的时候会漏掉验证集条件。",
    }
    for student_id, message in samples.items():
        profile = swarm.profile_store.setdefault(student_id, StudentProfile(student_id=student_id))
        if hasattr(swarm.profile_probe, "update"):
            swarm.profile_probe.update(profile, message)


def _profile_card(profile: StudentProfile) -> dict[str, Any]:
    causes = sorted(profile.learning_state_causes.values(), key=lambda item: item.percentage, reverse=True)
    dimensions = [
        {
            "key": key,
            "label": state.label,
            "score": state.score,
            "confidence": state.confidence,
            "status": state.status,
        }
        for key, state in profile.dimension_states.items()
    ]
    return {
        "student_id": profile.student_id,
        "course": profile.target_course,
        "major": profile.major or profile.major_preference,
        "goals": profile.learning_goals,
        "weak_points": profile.weak_points,
        "preferences": profile.interaction_preferences,
        "causes": [asdict(item) for item in causes],
        "dimensions": dimensions,
        "concept_mastery": profile.concept_mastery,
        "report": profile.state_report(),
        "favorites": getattr(profile, "favorites", [])
    }


def _teacher_dashboard() -> dict[str, Any]:
    _seed_demo_class()
    profiles = list(swarm.profile_store.values())
    heatmap = []
    for profile in profiles:
        row = {"student_id": profile.student_id}
        for key in DIMENSION_LABELS:
            state = profile.dimension_states.get(key)
            row[key] = state.score if state else 0.0
        heatmap.append(row)

    misconception_rank: dict[str, float] = {}
    intervention_rank: dict[str, int] = {}
    for profile in profiles:
        for name, value in profile.misconception_patterns.items():
            misconception_rank[name] = misconception_rank.get(name, 0.0) + value
        for cause in profile.learning_state_causes.values():
            for intervention in cause.recommended_interventions:
                intervention_rank[intervention] = intervention_rank.get(intervention, 0) + 1

    return {
        "course": "机器学习导论",
        "dimensions": DIMENSION_LABELS,
        "heatmap": heatmap,
        "misconceptions": sorted(
            [{"name": name, "score": round(score, 2)} for name, score in misconception_rank.items()],
            key=lambda item: item["score"],
            reverse=True,
        ),
        "interventions": sorted(
            [{"name": name, "count": count} for name, count in intervention_rank.items()],
            key=lambda item: item["count"],
            reverse=True,
        )[:8],
        "profiles": [_profile_card(profile) for profile in profiles],
    }


def _resource_summary(package) -> list[dict[str, Any]]:
    return [
        {
            "agent": resource.agent,
            "type": resource.resource_type,
            "content": resource.content,
            "citations": resource.citations,
        }
        for resource in package.resources
    ]


def _package_response(package) -> dict[str, Any]:
    return {
        "student_id": package.student_id,
        "target": package.target,
        "path": package.retrieval.graph_context.learning_path,
        "profile": _profile_card(package.profile),
        "strategy_plan": asdict(package.strategy_plan) if package.strategy_plan else None,
        "resources": _resource_summary(package),
        "alignment": asdict(package.alignment),
        "learning_signal": asdict(package.learning_signal),
        "kept_evidence": [verdict.evidence_id for verdict in package.verdicts if verdict.keep],
    }


class EduMatrixHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/":
            self._send_html(INDEX_HTML)
            return
        if path == "/api/teacher":
            self._send_json(_teacher_dashboard())
            return
        if path == "/api/datasets":
            self._send_json({"course": "机器学习导论", "datasets": MACHINE_LEARNING_DATASETS})
            return
        if path == "/api/health":
            self._send_json(
                {
                    "status": "ok",
                    "course": "机器学习导论",
                    "profiles": len(swarm.profile_store),
                    "rag": {
                        "visual_index_count": swarm.rag.visual_index.index.count(),
                        "text_index_count": swarm.rag.text_index.index.count(),
                    },
                }
            )
            return
        if path == "/api/metrics":
            self._send_json(TELEMETRY.snapshot())
            return
        self.send_error(404, "Not Found")

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        
        # 处理收藏夹逻辑
        if path == "/api/favorite":
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            student_id = str(payload.get("student_id") or "demo-student").strip()
            profile = swarm.profile_store.get(student_id)
            if profile:
                profile.add_favorite(payload["target"], payload["resource_type"], payload["content"], payload.get("note", ""), payload.get("fav_id", ""))
            self._send_json({"status": "ok", "message": "已成功加入收藏夹"})
            return

        if path == "/api/favorite/delete":
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            student_id = str(payload.get("student_id") or "demo-student").strip()
            profile = swarm.profile_store.get(student_id)
            if profile:
                profile.remove_favorite(payload["id"])
            self._send_json({"status": "ok", "message": "删除成功"})
            return

        if path == "/api/favorite/note":
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            student_id = str(payload.get("student_id") or "demo-student").strip()
            profile = swarm.profile_store.get(student_id)
            if profile:
                profile.update_favorite_note(payload["id"], payload["note"])
            self._send_json({"status": "ok", "message": "笔记保存成功"})
            return

        # 核心多智能体流程处理
        if path != "/api/process":
            self.send_error(404, "Not Found")
            return
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length).decode("utf-8")
        try:
            payload = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            self.send_error(400, "Invalid JSON")
            return
        message = str(payload.get("message") or "").strip()
        student_id = str(payload.get("student_id") or "demo-student").strip()
        if not message:
            self.send_error(400, "message is required")
            return
        package = swarm.process(message, student_id=student_id)
        self._send_json(_package_response(package))

    def _send_json(self, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, html: str) -> None:
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:
        return


INDEX_HTML = r"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>EduMatrix 智教矩阵 | 数理化全能渲染引擎</title>
  
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/katex@0.16.8/dist/katex.min.css">
  <script src="https://cdn.jsdelivr.net/npm/katex@0.16.8/dist/katex.min.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/katex@0.16.8/dist/contrib/mhchem.min.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/katex@0.16.8/dist/contrib/auto-render.min.js"></script>
  <script src="https://unpkg.com/smiles-drawer@1.0.10/dist/smiles-drawer.min.js"></script>
  <script src="https://unpkg.com/d3@3/d3.min.js"></script>
  <script src="https://unpkg.com/function-plot@1/dist/function-plot.js"></script>

  <style>
    :root {
      --ink: #17202a;
      --muted: #657282;
      --line: #dbe2ea;
      --panel: #ffffff;
      --bg: #f5f7fb;
      --brand: #0f766e;
      --brand-2: #2563eb;
      --warn: #b45309;
      --danger: #b91c1c;
      --ok: #15803d;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      color: var(--ink);
      background: var(--bg);
    }
    header {
      min-height: 52vh;
      color: white;
      background:
        linear-gradient(rgba(6, 38, 35, .72), rgba(6, 42, 55, .66)),
        url("https://images.unsplash.com/photo-1519389950473-47ba0277781c?auto=format&fit=crop&w=1800&q=80");
      background-size: cover;
      background-position: center;
      display: grid;
      align-items: end;
      padding: 40px clamp(18px, 5vw, 72px);
    }
    .hero { max-width: 980px; }
    .eyebrow { font-weight: 700; letter-spacing: .04em; opacity: .92; }
    h1 {
      font-size: clamp(36px, 7vw, 72px);
      line-height: 1;
      margin: 14px 0 18px;
      letter-spacing: 0;
    }
    .hero p { max-width: 780px; font-size: clamp(17px, 2vw, 22px); line-height: 1.6; margin: 0 0 28px; }
    .hero-actions { display: flex; gap: 12px; flex-wrap: wrap; }
    button, .chip {
      border: 0;
      border-radius: 8px;
      padding: 11px 15px;
      font-weight: 700;
      cursor: pointer;
    }
    .primary { background: #ffffff; color: #0f766e; }
    .secondary { background: rgba(255,255,255,.16); color: white; border: 1px solid rgba(255,255,255,.42); }
    main { padding: 28px clamp(14px, 4vw, 48px) 48px; }
    .grid { display: grid; grid-template-columns: minmax(320px, 1.05fr) minmax(320px, .95fr); gap: 18px; align-items: start; }
    .panel {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: 0 8px 24px rgba(20, 31, 45, .06);
      overflow: hidden;
    }
    .panel h2 { margin: 0; font-size: 20px; }
    .panel-head { padding: 18px 20px; border-bottom: 1px solid var(--line); display: flex; justify-content: space-between; gap: 12px; align-items: center; }
    .panel-body { padding: 18px 20px; }
    label { display: block; font-weight: 700; margin-bottom: 8px; }
    input, textarea, select {
      width: 100%;
      border: 1px solid #cbd5e1;
      border-radius: 8px;
      padding: 11px 12px;
      font: inherit;
      background: white;
      color: var(--ink);
    }
    textarea { min-height: 144px; resize: vertical; line-height: 1.55; }
    .row { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-bottom: 14px; }
    .muted { color: var(--muted); }
    .tabs { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 14px; }
    .tab { background: #e8eef5; color: #243142; }
    .tab.active { background: var(--brand); color: white; }
    .kpis { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; margin-bottom: 14px; }
    .kpi { border: 1px solid var(--line); border-radius: 8px; padding: 12px; background: #fbfdff; }
    .kpi strong { display: block; font-size: 22px; margin-top: 4px; }
    .cause { margin: 10px 0; }
    .bar { height: 10px; background: #e2e8f0; border-radius: 999px; overflow: hidden; }
    .bar span { display: block; height: 100%; background: linear-gradient(90deg, var(--brand), var(--brand-2)); }
    .resource {
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 14px;
      margin-bottom: 12px;
      background: #fbfdff;
    }
    .resource h3 { margin: 0 0 8px; font-size: 16px; color: #0f766e; }
    
    .content-box { 
      white-space: pre-wrap; 
      word-break: break-word; 
      background: #0f172a; 
      color: #e2e8f0; 
      padding: 18px; 
      border-radius: 8px; 
      overflow: hidden; 
      font-family: Consolas, monospace;
      font-size: 15px;
      line-height: 1.6;
    }
    
    .molecule-board {
      background: #ffffff;
      color: #17202a;
      padding: 20px;
      border-radius: 8px;
      text-align: center;
      margin: 16px 0;
      box-shadow: inset 0 2px 8px rgba(0,0,0,0.05);
      font-family: Inter, sans-serif;
    }

    .heatmap { overflow-x: auto; }
    table { border-collapse: collapse; width: 100%; font-size: 13px; }
    th, td { border: 1px solid var(--line); padding: 8px; text-align: center; }
    th { background: #f1f5f9; position: sticky; top: 0; }
    .score { color: white; border-radius: 6px; font-weight: 700; }
    .dataset-list { display: grid; grid-template-columns: repeat(2, minmax(220px, 1fr)); gap: 12px; }
    .dataset { border: 1px solid var(--line); border-radius: 8px; padding: 13px; background: #fbfdff; }
    a { color: #1d4ed8; text-decoration: none; font-weight: 700; }
    .loading { opacity: .72; pointer-events: none; }
    
    .scrollable-panel::-webkit-scrollbar { width: 6px; }
    .scrollable-panel::-webkit-scrollbar-track { background: #f1f5f9; border-radius: 4px; }
    .scrollable-panel::-webkit-scrollbar-thumb { background: #cbd5e1; border-radius: 4px; }
    .scrollable-panel::-webkit-scrollbar-thumb:hover { background: #94a3b8; }

    @media (max-width: 960px) {
      .grid, .row, .dataset-list, .kpis { grid-template-columns: 1fr; }
      header { min-height: 44vh; }
    }
  </style>
</head>
<body>
  <header>
    <section class="hero">
      <div class="eyebrow">机器学习导论 · 个性化学习智能体 Web Demo</div>
      <h1>EduMatrix 智教矩阵</h1>
      <p>突破理科可视化盲区！内置 <strong>KaTeX + mhchem</strong> 数学与化学方程式排版、<strong>SmilesDrawer</strong> 分子结构式渲染，以及 <strong>Function-Plot</strong> 与 <strong>SVG</strong> 实时数理互动绘图引擎。</p>
      <div class="hero-actions">
        <button class="primary" onclick="scrollToApp()">开始体验</button>
        <button class="secondary" onclick="loadTeacher()">查看教师端</button>
      </div>
    </section>
  </header>

  <main id="app">
    <section class="grid">
      <div class="panel">
        <div class="panel-head">
          <h2>学生端：画像驱动学习生成</h2>
          <span class="muted">固定课程：机器学习导论</span>
        </div>
        <div class="panel-body">
          <div class="row">
            <div>
              <label for="student">学生 ID</label>
              <input id="student" value="demo-student" />
            </div>
            <div>
              <label for="preset">典型场景</label>
              <select id="preset" onchange="usePreset()">
                <option value="">选择一个赛题演示场景</option>
                <option>我是计算机专业，期末要考机器学习。逻辑回归和混淆矩阵总混，accuracy 很高但 recall 低我不知道怎么判断，希望用图和例子一步步讲。</option>
                <option>我线性回归能看懂公式，但一到项目就不会做数据预处理，只会照着答案改代码，想要代码实操 and 提示。</option>
                <option>我过拟合和正则化分不清，训练集分数高就以为模型好，题干长的时候会漏掉验证集条件。</option>
              </select>
            </div>
          </div>
          <label for="message">学生自然语言反馈</label>
          <textarea id="message">我是计算机专业，期末要考机器学习。逻辑回归和混淆矩阵总混，accuracy 很高但 recall 低我不知道怎么判断，希望用图和例子一步步讲。</textarea>
          <div style="display:flex; gap:10px; margin-top:14px; flex-wrap:wrap;">
            <button class="primary" style="background:#0f766e;color:white" onclick="runStudent()">生成个性化资源</button>
            <button class="tab" onclick="loadTeacher()">刷新教师端</button>
            <button class="secondary" style="background:#dc2626;color:white;border:none;font-weight:bold;" onclick="triggerAllSTEMDemo()">🚀 一键测试数理化全能渲染</button>
          </div>
        </div>
      </div>

      <div class="panel">
        <div class="panel-head">
          <h2>学习状态画像</h2>
          <span id="target" class="muted">等待生成</span>
        </div>
        <div class="panel-body">
          <div class="kpis">
            <div class="kpi">对齐状态<strong id="align">-</strong></div>
            <div class="kpi">预测正确率<strong id="acc">-</strong></div>
            <div class="kpi">目标知识点<strong id="targetKpi">-</strong></div>
          </div>
          <div id="causes" class="muted">学生画像将在这里展示。</div>
        </div>
      </div>
    </section>

    <section class="grid" style="margin-top:18px;">
      <div class="panel">
        <div class="panel-head">
          <h2>📊 知识点掌握进度</h2>
          <span class="muted">根据对话自动量化</span>
        </div>
        <div class="panel-body" id="progress-panel">
          <span class="muted">提问后将自动更新进度...</span>
        </div>
      </div>
      
      <div class="panel">
        <div class="panel-head">
          <h2>⭐ 我的收藏夹</h2>
          <span class="muted">点击标题沉浸阅读 / 支持滚动浏览</span>
        </div>
        <div class="panel-body scrollable-panel" id="favorites-panel" style="max-height: 480px; overflow-y: auto; overflow-x: hidden;">
          <span class="muted">暂无收藏。</span>
        </div>
      </div>
    </section>

    <section class="panel" style="margin-top:18px;">
      <div class="panel-head">
        <h2>多智能体资源包</h2>
        <span class="muted">智能排版渲染引擎加载区</span>
      </div>
      <div class="panel-body" id="resources">
        <span class="muted">点击上方按钮生成，或点击【一键测试数理化全能渲染】体验震撼效果。</span>
      </div>
    </section>

    <section class="grid" style="margin-top:18px;">
      <div class="panel">
        <div class="panel-head">
          <h2>学习策略引擎</h2>
          <span class="muted">检索练习 / 间隔复习 / worked example / 提示阶梯</span>
        </div>
        <div class="panel-body" id="strategies">
          <span class="muted">等待画像触发。</span>
        </div>
      </div>
      
      <div class="panel">
        <div class="panel-head">
          <h2>学术探索专区 (arXiv)</h2>
          <span class="muted">硬核前沿论文直搜</span>
        </div>
        <div class="panel-body">
          <div style="display:flex; gap:10px; margin-bottom: 14px;">
            <input id="arxiv-query" placeholder="输入学术概念，如：Transformer" style="flex:1;" />
            <button class="primary" style="background:#2563eb; color:white;" onclick="searchArxiv()">检索论文</button>
          </div>
          <div id="arxiv-results" style="display:flex; flex-direction:column; gap:12px;">
            <span class="muted">输入关键词，开始探索权威文献。</span>
          </div>
        </div>
      </div>
    </section>
    
    <section class="panel" style="margin-top:18px;">
      <div class="panel-head">
        <h2>机器学习课程数据集</h2>
        <span class="muted">公开教学数据源</span>
      </div>
      <div class="panel-body dataset-list" id="datasets"></div>
    </section>

    <section class="panel" style="margin-top:18px;">
      <div class="panel-head">
        <h2>教师端：班级诊断面板</h2>
        <span class="muted">热力图 · 误概念排行 · 干预建议</span>
      </div>
      <div class="panel-body">
        <div class="tabs">
          <button class="tab active" onclick="loadTeacher()">刷新班级画像</button>
        </div>
        <div id="teacher">等待加载。</div>
      </div>
    </section>
  </main>

  <div id="fav-modal" style="display:none; position:fixed; top:0; left:0; width:100%; height:100%; background:rgba(0,0,0,0.6); z-index:9999; justify-content:center; align-items:center;">
    <div style="background:var(--panel); width:85%; max-width:900px; max-height:85vh; border-radius:12px; display:flex; flex-direction:column; overflow:hidden; box-shadow: 0 20px 40px rgba(0,0,0,0.3); border:1px solid var(--line);">
      <div style="padding:16px 20px; border-bottom:1px solid var(--line); display:flex; justify-content:space-between; align-items:center; background:white;">
        <h3 id="fav-modal-title" style="margin:0; color:#0f766e; font-size:18px;"></h3>
        <button onclick="closeFavModal()" style="background:transparent; border:none; font-size:24px; cursor:pointer; color:var(--muted);">&times;</button>
      </div>
      <div id="fav-modal-content" class="content-box scrollable-panel" style="padding:24px; overflow-y:auto; flex:1; background:#0f172a; color:#e2e8f0; font-size:15px; border-radius:0;"></div>
    </div>
  </div>

  <script>
    const $ = (id) => document.getElementById(id);
    function scrollToApp(){ $('app').scrollIntoView({behavior:'smooth'}); }
    function usePreset(){ if ($('preset').value) $('message').value = $('preset').value; }
    function esc(s){ return String(s ?? '').replace(/[&<>"']/g, m => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[m])); }

    window.currentFavs = []; 
    window.lastRealProfile = null;

    function triggerAllSTEMDemo() {
      const demoData = {
        path: ["理科基础", "多模态可视化", "智能体排版"],
        alignment: { passed: true },
        learning_signal: { accuracy: 0.99 },
        target: "理科可视化引擎验收",
        profile: { 
            causes: [], 
            concept_mastery: window.lastRealProfile ? window.lastRealProfile.concept_mastery : {}, 
            favorites: window.currentFavs || [] 
        },
        resources: [
          {
            agent: "理论教授 (Agent 5)",
            type: "深度讲义 (物理篇)",
            citations: ["基础物理学"],
            content: `这道题我们首先进行受力分析。假设一个蓝色物块静止在粗糙的斜面上，它受到重力(G)向下，以及斜面的支持力(N)和摩擦力(f)。\n大模型在遇到物理题时，可以通过直接生成 SVG 代码来代替干巴巴的语言描述：\n\n<svg width="300" height="200" viewBox="0 0 300 200">\n  <polygon points="50,180 250,180 250,100" fill="#e2e8f0" stroke="#64748b" stroke-width="2"/>\n  <rect x="130" y="110" width="40" height="40" transform="rotate(22 150 130)" fill="#3b82f6" opacity="0.8"/>\n  <line x1="150" y1="130" x2="150" y2="190" stroke="#ef4444" stroke-width="3" />\n  <polygon points="145,185 155,185 150,195" fill="#ef4444" />\n  <text x="160" y="180" fill="#ef4444" font-weight="bold">G</text>\n  <line x1="150" y1="130" x2="135" y2="70" stroke="#22c55e" stroke-width="3" />\n  <polygon points="130,75 140,73 133,63" fill="#22c55e" />\n  <text x="115" y="70" fill="#22c55e" font-weight="bold">N</text>\n</svg>`
          },
          {
            agent: "逻辑画师 (Agent 6)",
            type: "数学公式推演 (数学篇)",
            citations: ["微积分与代数"],
            content: `在机器学习中，我们常常需要对比平滑的函数与产生过拟合抖动的函数。\n比如最简单的二次函数 $y=x^2$，和带有高频噪声的函数 $y=x^2 + \\sin(8x)$。\n\n系统通过拦截特定的 \`<plot>\` 标签，可以直接召唤出一个可以**用鼠标拖拽和滚轮缩放**的坐标系：\n<plot>x^2, x^2 + sin(8*x)</plot>\n你可以把鼠标放上去，观察它是如何显示每个点的精确坐标的。`
          },
          {
            agent: "极客助教 (Agent 7)",
            type: "分子与方程式 (化学篇)",
            citations: ["有机化学基础"],
            content: `最后来看看化学能力。通过 KaTeX 的 mhchem 扩展，化学方程式的排版极其优雅（注意下标和反应条件）：\n$$ \\ce{C7H6O3 + C4H6O3 ->[H+] C9H8O4 + C2H4O2} $$\n\n纯文字往往无法传达有机物的立体结构。现在，只要大模型输出一行 SMILES 码，前端就能瞬间绘制出阿司匹林（Aspirin）的分子图谱：\n<smiles>CC(=O)OC1=CC=CC=C1C(=O)O</smiles>\n\n这一切，都完美地无缝嵌在了一个对话资源包中！`
          }
        ]
      };
      renderStudent(demoData);
      setTimeout(() => {
         document.getElementById('resources').scrollIntoView({behavior:'smooth', block: 'start'});
      }, 200);
    }

    function formatContent(text) {
      let safeText = esc(text);
      safeText = safeText.replace(/&lt;svg([\s\S]*?)&lt;\/svg&gt;/g, function(match, inner) {
        let svgCode = "<svg" + inner + "</svg>";
        svgCode = svgCode.replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&quot;/g, '"').replace(/&#039;/g, "'").replace(/&amp;/g, '&');
        return `<div class="molecule-board" style="background:#f1f5f9;"><div style="font-weight:bold; color:#0f766e; margin-bottom:8px;">📐 物理/几何矢量分析图</div>${svgCode}</div>`;
      });
      safeText = safeText.replace(/&lt;smiles&gt;(.*?)&lt;\/smiles&gt;/g, function(match, smilesCode) {
        return `<div class="molecule-board"><div style="font-weight:bold; color:#0f766e; margin-bottom:8px;">🧪 化学结构实时渲染</div><canvas class="smiles-canvas" data-smiles="${smilesCode}"></canvas><div style="color: #64748b; font-size: 12px; margin-top: 8px;">SMILES: ${smilesCode}</div></div>`;
      });
      safeText = safeText.replace(/&lt;plot&gt;(.*?)&lt;\/plot&gt;/g, function(match, functions) {
        let plotId = 'plot-' + Math.random().toString(36).substr(2, 9);
        let rawFuncs = functions.replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&quot;/g, '"').replace(/&#039;/g, "'");
        return `<div class="molecule-board" style="padding:10px;"><div style="font-weight:bold; color:#0f766e; margin-bottom:8px;">📈 可交互数学函数</div><div id="${plotId}" class="math-plot" data-funcs="${esc(rawFuncs)}" style="display:flex; justify-content:center;"></div></div>`;
      });
      return safeText;
    }

    function renderMathAndMolecules() {
      if (window.renderMathInElement) {
        renderMathInElement(document.body, {
          delimiters: [
            {left: '$$', right: '$$', display: true},
            {left: '$', right: '$', display: false},
            {left: '\\(', right: '\\)', display: false},
            {left: '\\[', right: '\\]', display: true}
          ],
          throwOnError: false
        });
      }
      if (window.SmilesDrawer) {
        let smilesDrawer = new SmilesDrawer.Drawer({ width: 400, height: 300, bondThickness: 1.5 });
        document.querySelectorAll('.smiles-canvas').forEach(canvas => {
          let smilesString = canvas.getAttribute('data-smiles');
          SmilesDrawer.parse(smilesString, function(tree) {
            smilesDrawer.draw(tree, canvas, 'light', false);
          }, function(err) { console.error("分子绘制失败:", err); });
        });
      }
      if (window.functionPlot) {
        document.querySelectorAll('.math-plot').forEach(container => {
          if(container.innerHTML !== "") return; 
          let funcsStr = container.getAttribute('data-funcs');
          let dataArray = funcsStr.split(',').map(f => {
              return { fn: f.replace(/[\u4e00-\u9fa5:：]/g, '').trim() };
          }).filter(d => d.fn.length > 0);
          try {
            functionPlot({ target: '#' + container.id, width: 500, height: 300, grid: true, data: dataArray });
          } catch (err) {
            container.innerHTML = `<span style="color:#b45309;font-size:13px;">⚠️ 函数图表加载拦截：大模型输出了不支持的格式 (${esc(funcsStr)})</span>`;
          }
        });
      }
    }

    async function runStudent(){
      document.body.classList.add('loading');
      try {
        const res = await fetch('/api/process', {
          method: 'POST',
          headers: {'Content-Type':'application/json'},
          body: JSON.stringify({student_id: $('student').value, message: $('message').value})
        });
        const data = await res.json();
        window.lastRealProfile = data.profile; 
        renderStudent(data);
        await loadTeacher();
      } finally {
        document.body.classList.remove('loading');
      }
    }

    function renderStudent(data) {
      $('target').textContent = data.path.join(' -> ');
      $('align').textContent = data.alignment.passed ? '通过' : '需回滚';
      $('align').style.color = data.alignment.passed ? '#15803d' : '#b91c1c';
      $('acc').textContent = Number(data.learning_signal.accuracy).toFixed(2);
      $('targetKpi').textContent = data.target;
      
      const causes = data.profile.causes || [];
      $('causes').innerHTML = causes.map(c => `
        <div class="cause">
          <div style="display:flex;justify-content:space-between;gap:10px;"><strong>${esc(c.label)}</strong><span>${Number(c.percentage).toFixed(1)}%</span></div>
          <div class="bar"><span style="width:${Number(c.percentage)}%"></span></div>
          <div class="muted">${esc((c.evidence_fragments || [])[0] || '暂无证据')}</div>
        </div>
      `).join('') || '<span class="muted">暂无画像原因。</span>';

      $('resources').innerHTML = data.resources.map((r, idx) => {
        const favKey = esc(data.target) + '|' + esc(r.type);
        return `
        <article class="resource">
          <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:10px;">
            <h3>${esc(r.agent)} / ${esc(r.type)}</h3>
            <div style="display:flex; gap:8px; align-items:center;">
               <input id="pre-note-${idx}" type="text" placeholder="在这输入收藏笔记..." style="font-size:12px; padding:5px 8px; width:160px; border:1px solid #cbd5e1; border-radius:6px;">
               <button class="secondary fav-btn" data-fav-key="${favKey}" style="padding: 5px 12px; font-size: 12px; color: white; background: #0f766e; border:none; cursor:pointer;"
                       onclick="toggleFav('${esc(data.target)}', '${esc(r.type)}', \`${esc(r.content).replace(/`/g, "'")}\`, 'pre-note-${idx}', this)">
                 ⭐ 收藏
               </button>
            </div>
          </div>
          <div class="content-box">${formatContent(r.content)}</div>
          <div class="muted" style="margin-top: 10px;">证据：${esc((r.citations || []).join(', '))}</div>
        </article>
      `}).join('');

      setTimeout(renderMathAndMolecules, 100);

      const actions = data.strategy_plan?.actions || [];
      $('strategies').innerHTML = actions.map(a => `
        <article class="resource">
          <h3>${esc(a.title)}</h3>
          <p>${esc(a.description)}</p>
          <div class="muted">触发原因：${esc(a.trigger)} · 时间：${esc(a.scheduled_after)}</div>
        </article>
      `).join('') || '<span class="muted">暂无策略。</span>';
      
      renderProgress(data.profile);
      
      window.currentFavs = data.profile.favorites || window.currentFavs || [];
      renderFavoritesPanel();
    }
    
    function renderProgress(profile) { 
      if (profile.concept_mastery && Object.keys(profile.concept_mastery).length > 0) { 
        $('progress-panel').innerHTML = Object.entries(profile.concept_mastery).map(([concept, score]) => { 
          let pct = (score * 100).toFixed(0); 
          let color = score > 0.7 ? '#15803d' : (score > 0.4 ? '#0f766e' : '#b45309'); 
          return `<div style="margin-bottom: 12px;"> 
              <div style="display:flex;justify-content:space-between;font-size:14px;margin-bottom:4px;"><strong>${esc(concept)}</strong> <span style="color:${color};font-weight:bold;">${pct}%</span></div> 
              <div class="bar" style="height:8px; background:#e2e8f0;"><span style="width:${pct}%; background:${color};"></span></div> 
            </div>`; 
        }).join(''); 
      } else {
        $('progress-panel').innerHTML = '<span class="muted">提问后将自动更新进度...</span>'; 
      }
    } 

    function renderFavoritesPanel() {
      let favPanel = $('favorites-panel');
      if (!window.currentFavs || window.currentFavs.length === 0) { 
        favPanel.innerHTML = '<span class="muted">暂无收藏。</span>'; 
      } else {
        let favs = [...window.currentFavs].reverse(); 
        favPanel.innerHTML = favs.map(f => ` 
          <div class="fav-item" style="border-bottom: 1px solid var(--line); padding-bottom: 14px; margin-bottom: 14px; animation: fadeIn 0.3s;"> 
            <div style="display:flex; justify-content:space-between; align-items:flex-start;">
              <div style="font-size: 14px; font-weight: bold; color: #0f766e; cursor: pointer; text-decoration: underline;" onclick="openFavModal('${f.id}')" title="点击看大图和公式详情">📌 ${esc(f.target)} - ${esc(f.resource_type)}</div> 
              <button onclick="deleteFav('${f.id}')" style="background:transparent; border:none; cursor:pointer; font-size:14px;" title="取消此收藏">🗑️</button>
            </div>
            <div class="muted" style="font-size: 12px; margin-top: 6px; line-height:1.5;">${esc(f.content_snippet)}</div> 
            <div style="margin-top: 10px; display:flex; gap:8px;">
               <input id="note-${f.id}" type="text" value="${esc(f.note || '')}" placeholder="随时修改个人笔记..." style="flex:1; font-size:12px; padding:6px 10px; border:1px solid #cbd5e1; border-radius:6px; background:#f8fafc;">
               <button onclick="saveNote('${f.id}')" style="padding:6px 12px; font-size:12px; background:#e2e8f0; color:#334155; border-radius:6px; border:none; cursor:pointer; font-weight:bold;">保存</button>
            </div>
          </div> 
        `).join(''); 
      }
      
      setTimeout(() => {
          document.querySelectorAll('.fav-btn').forEach(btn => {
              const key = btn.getAttribute('data-fav-key');
              const isFav = window.currentFavs.some(f => (f.target + '|' + f.resource_type) === key);
              if (isFav) {
                  btn.textContent = "✅ 已收藏";
                  btn.style.background = "#dcfce7";
                  btn.style.color = "#15803d";
              } else {
                  btn.textContent = "⭐ 收藏";
                  btn.style.background = "#0f766e";
                  btn.style.color = "white";
              }
          });
      }, 50);
    }
 
    async function toggleFav(target, type, content, noteInputId, btn) { 
      const existingFav = window.currentFavs.find(f => f.target === target && f.resource_type === type);
      
      if (existingFav) {
          await deleteFav(existingFav.id);
          return;
      }

      let noteValue = $(noteInputId) ? $(noteInputId).value : '';
      let tempId = 'fav_' + Date.now();
      
      await fetch('/api/favorite', { 
        method: 'POST', 
        headers: {'Content-Type':'application/json'}, 
        body: JSON.stringify({ student_id: $('student').value, fav_id: tempId, target: target, resource_type: type, content: content, note: noteValue }) 
      }); 
      
      let snippet = content.length > 120 ? content.substring(0, 120) + "..." : content; 
      window.currentFavs.push({ id: tempId, target: target, resource_type: type, content: content, note: noteValue, content_snippet: snippet });
      
      renderFavoritesPanel();
      if($(noteInputId)) $(noteInputId).value = ''; 
    }

    async function deleteFav(id) {
      if(!confirm("确定要取消/删除这条收藏吗？")) return;
      
      await fetch('/api/favorite/delete', {
        method: 'POST', headers: {'Content-Type':'application/json'},
        body: JSON.stringify({ student_id: $('student').value, id: id })
      });
      
      window.currentFavs = window.currentFavs.filter(f => f.id !== id);
      renderFavoritesPanel();
    }

    async function saveNote(id) {
      let noteContent = document.getElementById('note-' + id).value;
      await fetch('/api/favorite/note', {
        method: 'POST', headers: {'Content-Type':'application/json'},
        body: JSON.stringify({ student_id: $('student').value, id: id, note: noteContent })
      });
      let fav = window.currentFavs.find(f => f.id === id);
      if(fav) fav.note = noteContent;
      alert("✅ 笔记已妥善保存！");
    }

    function openFavModal(id) {
      let fav = window.currentFavs.find(f => f.id === id);
      if(!fav) return;
      document.getElementById('fav-modal-title').innerText = fav.target + ' - ' + fav.resource_type;
      document.getElementById('fav-modal-content').innerHTML = formatContent(fav.content);
      document.getElementById('fav-modal').style.display = 'flex';
      setTimeout(renderMathAndMolecules, 100); 
    }

    function closeFavModal() {
      document.getElementById('fav-modal').style.display = 'none';
      document.getElementById('fav-modal-content').innerHTML = '';
    }

    async function searchArxiv() {
      const query = $('arxiv-query').value.trim();
      if (!query) return;
      $('arxiv-results').innerHTML = '<span class="muted">正在跨洋检索 arXiv 数据库...</span>';
      try {
        const res = await fetch(`/api/web/arxiv-search?query=${encodeURIComponent(query)}&max_results=3`);
        const data = await res.json();
        if (data.papers && data.papers.length > 0) {
          $('arxiv-results').innerHTML = data.papers.map(p => `
            <article class="resource" style="background:#f8fafc; border-left: 4px solid #2563eb; text-align: left;">
              <h3 style="color:#1e293b; margin: 0 0 4px; font-size: 15px;">${esc(p.title)}</h3>
              <div class="muted" style="font-size:12px; margin-bottom: 8px;">👨‍🔬 作者: ${esc(p.authors.join(', '))}</div>
              <p style="font-size:13px; display:-webkit-box; -webkit-line-clamp:3; -webkit-box-orient:vertical; overflow:hidden; margin-bottom:10px; text-align: justify;">${esc(p.abstract)}</p>
              <a href="${esc(p.pdf_url)}" target="_blank" rel="noreferrer" style="color:#2563eb; background:#dbeafe; padding:6px 10px; border-radius:4px; font-size:12px; display:inline-block;">📄 阅读 PDF 原文</a>
            </article>
          `).join('');
        } else {
          $('arxiv-results').innerHTML = '<span class="muted">未找到相关论文。</span>';
        }
      } catch (e) {
        $('arxiv-results').innerHTML = `<span style="color:var(--danger)">检索失败：请检查后端服务是否启动。(${e.message})</span>`;
      }
    }

    async function loadTeacher(){
      const res = await fetch('/api/teacher');
      const data = await res.json();
      const keys = Object.keys(data.dimensions);
      const heat = `
        <div class="heatmap">
          <table>
            <thead><tr><th>学生</th>${keys.map(k => `<th>${esc(data.dimensions[k])}</th>`).join('')}</tr></thead>
            <tbody>
              ${data.heatmap.map(row => `<tr><td><strong>${esc(row.student_id)}</strong></td>${keys.map(k => {
                const v = Number(row[k] || 0);
                const color = v > .7 ? '#15803d' : (v > .5 ? '#b45309' : '#b91c1c');
                return `<td><span class="score" style="background:${color};padding:5px 8px;">${v.toFixed(2)}</span></td>`;
              }).join('')}</tr>`).join('')}
            </tbody>
          </table>
        </div>`;
      const misconceptions = (data.misconceptions.length ? data.misconceptions : [{name:'待继续收集误概念证据', score:0}])
        .map(m => `<li>${esc(m.name)} <strong>${Number(m.score).toFixed(2)}</strong></li>`).join('');
      const interventions = data.interventions.map(i => `<li>${esc(i.name)} <strong>${i.count}</strong></li>`).join('');
      $('teacher').innerHTML = `
        ${heat}
        <div class="grid" style="margin-top:16px;">
          <div class="resource"><h3>高频误概念排行</h3><ol>${misconceptions}</ol></div>
          <div class="resource"><h3>教师干预建议</h3><ol>${interventions}</ol></div>
        </div>`;
    }

    loadDatasets();
    loadTeacher();
  </script>
</body>
</html>"""


def main() -> None:
    server = ThreadingHTTPServer((HOST, PORT), EduMatrixHandler)
    print(f"EduMatrix Web Demo running at http://{HOST}:{PORT}")
    server.serve_forever()


if __name__ == "__main__":
    main()