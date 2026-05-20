from __future__ import annotations

from dataclasses import asdict
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse

from agent_swarm import EduMatrixSwarm
from models import DIMENSION_LABELS, StudentProfile
from observability import TELEMETRY


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
  <title>EduMatrix 智教矩阵 | 机器学习导论</title>
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
    pre { white-space: pre-wrap; word-break: break-word; background: #0f172a; color: #e2e8f0; padding: 12px; border-radius: 8px; overflow: auto; }
    .heatmap { overflow-x: auto; }
    table { border-collapse: collapse; width: 100%; font-size: 13px; }
    th, td { border: 1px solid var(--line); padding: 8px; text-align: center; }
    th { background: #f1f5f9; position: sticky; top: 0; }
    .score { color: white; border-radius: 6px; font-weight: 700; }
    .dataset-list { display: grid; grid-template-columns: repeat(2, minmax(220px, 1fr)); gap: 12px; }
    .dataset { border: 1px solid var(--line); border-radius: 8px; padding: 13px; background: #fbfdff; }
    a { color: #1d4ed8; text-decoration: none; font-weight: 700; }
    .loading { opacity: .72; pointer-events: none; }
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
      <p>围绕赛题核心要求，固定机器学习课程场景，提供对话式学习画像、多智能体资源生成、个性化学习路径、智能辅导、学习效果评估与教师端诊断。</p>
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
                <option>我线性回归能看懂公式，但一到项目就不会做数据预处理，只会照着答案改代码，想要代码实操和提示。</option>
                <option>我过拟合和正则化分不清，训练集分数高就以为模型好，题干长的时候会漏掉验证集条件。</option>
              </select>
            </div>
          </div>
          <label for="message">学生自然语言反馈</label>
          <textarea id="message">我是计算机专业，期末要考机器学习。逻辑回归和混淆矩阵总混，accuracy 很高但 recall 低我不知道怎么判断，希望用图和例子一步步讲。</textarea>
          <div style="display:flex; gap:10px; margin-top:14px; flex-wrap:wrap;">
            <button class="primary" style="background:#0f766e;color:white" onclick="runStudent()">生成个性化资源</button>
            <button class="tab" onclick="loadTeacher()">刷新教师端</button>
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

    <section class="panel" style="margin-top:18px;">
      <div class="panel-head">
        <h2>多智能体资源包</h2>
        <span class="muted">讲义 · 导图 · 代码 · 练习 · 视频脚本</span>
      </div>
      <div class="panel-body" id="resources">
        <span class="muted">点击生成后展示。</span>
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
          <h2>机器学习课程数据集</h2>
          <span class="muted">公开教学数据源</span>
        </div>
        <div class="panel-body dataset-list" id="datasets"></div>
      </div>
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

  <script>
    const $ = (id) => document.getElementById(id);
    function scrollToApp(){ $('app').scrollIntoView({behavior:'smooth'}); }
    function usePreset(){ if ($('preset').value) $('message').value = $('preset').value; }
    function esc(s){ return String(s ?? '').replace(/[&<>"']/g, m => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[m])); }

    async function runStudent(){
      document.body.classList.add('loading');
      try {
        const res = await fetch('/api/process', {
          method: 'POST',
          headers: {'Content-Type':'application/json'},
          body: JSON.stringify({student_id: $('student').value, message: $('message').value})
        });
        const data = await res.json();
        renderStudent(data);
        await loadTeacher();
      } finally {
        document.body.classList.remove('loading');
      }
    }

    function renderStudent(data){
      $('target').textContent = data.path.join(' -> ');
      $('align').textContent = data.alignment.passed ? '通过' : '需回滚';
      $('align').style.color = data.alignment.passed ? '#15803d' : '#b91c1c';
      $('acc').textContent = Number(data.learning_signal.accuracy).toFixed(2);
      $('targetKpi').textContent = data.target;
      const causes = data.profile.causes || [];
      $('causes').innerHTML = causes.map(c => `
        <div class="cause">
          <div style="display:flex;justify-content:space-between;gap:10px;">
            <strong>${esc(c.label)}</strong><span>${Number(c.percentage).toFixed(1)}%</span>
          </div>
          <div class="bar"><span style="width:${Number(c.percentage)}%"></span></div>
          <div class="muted">${esc((c.evidence_fragments || [])[0] || '暂无证据')}</div>
        </div>
      `).join('') || '<span class="muted">暂无画像原因。</span>';

      $('resources').innerHTML = data.resources.map(r => `
        <article class="resource">
          <h3>${esc(r.agent)} / ${esc(r.type)}</h3>
          <pre>${esc(r.content)}</pre>
          <div class="muted">证据：${esc((r.citations || []).join(', '))}</div>
        </article>
      `).join('');

      const actions = data.strategy_plan?.actions || [];
      $('strategies').innerHTML = actions.map(a => `
        <article class="resource">
          <h3>${esc(a.title)}</h3>
          <p>${esc(a.description)}</p>
          <div class="muted">触发原因：${esc(a.trigger)} · 时间：${esc(a.scheduled_after)}</div>
        </article>
      `).join('') || '<span class="muted">暂无策略。</span>';
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

    async function loadDatasets(){
      const res = await fetch('/api/datasets');
      const data = await res.json();
      $('datasets').innerHTML = data.datasets.map(d => `
        <article class="dataset">
          <strong>${esc(d.name)}</strong>
          <p class="muted">${esc(d.task)}</p>
          <p>${esc(d.note)}</p>
          <a href="${esc(d.url)}" target="_blank" rel="noreferrer">数据集 URL</a>
        </article>
      `).join('');
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
