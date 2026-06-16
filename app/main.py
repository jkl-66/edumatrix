import sys
import os
import uuid
import time
from datetime import timedelta
from dataclasses import asdict
from typing import Any
from fastapi import FastAPI, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordRequestForm

# 允许 app 导入 root 目录下的模块
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import CONFIG
from concurrency import AsyncWorkerPool, TokenBucket
from models import DIMENSION_LABELS, StudentProfile
from app.database import init_db, DBStudentProfile, DBUser, run_db_op
from app.crud import (
    load_student_profile,
    save_student_profile,
    record_alignment_log,
    create_note,
    get_notes,
    delete_note,
    get_review_plan,
    upsert_review_plan,
    record_conversation,
    get_conversation_history,
)
from app.auth import authenticate_user, create_access_token, get_current_user, get_password_hash
from knowledge_api import router as knowledge_router
from quiz_api import router as quiz_router
from web_search_api import router as web_search_router
from code_exec_api import router as code_exec_router
from profile_api import router as profile_router
from stream_api import router as stream_router
from note_engine import LearningProgressAnalyzer, ReviewScheduler
from observability import TELEMETRY
from swarm_factory import build_swarm_from_headers

# 初始化 SQLite 数据库表
init_db()

_worker_pool: AsyncWorkerPool | None = None

llm_provider = "swarm_factory"
swarm = build_swarm_from_headers(type("h", (), {"get": lambda s, k, d=None: d})())


app = FastAPI(
    title="EduMatrix 智教矩阵 API",
    description="基于 FastAPI + SQLite + Swarm 智能体的高并发个性化教育 system 后端",
    version="1.1.0"
)

# 限制级跨域配置（防 * 安全漏洞，锁定前端Vue开发域）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:8000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def add_process_time_header(request: Request, call_next):
    start_time = time.perf_counter()
    trace_id = str(uuid.uuid4())
    request.state.trace_id = trace_id
    
    response = await call_next(request)
    
    process_time = time.perf_counter() - start_time
    response.headers["X-Process-Time"] = str(process_time)
    response.headers["X-Trace-ID"] = trace_id
    
    # 写入标准化日志
    TELEMETRY.record_span(
        name="http_request",
        duration_ms=process_time * 1000,
        path=request.url.path,
        method=request.method,
        trace_id=trace_id,
        status_code=response.status_code
    )
    return response


@app.post("/api/auth/login")
async def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends()):
    """JWT 登录接口，获取访问令牌 (Task 2.2)"""
    def do_auth(session):
        user = authenticate_user(session, form_data.username, form_data.password)
        if not user:
            # 如果是首次演示，且数据库为空，自动创建 demo 用户
            if form_data.username == "demo-student" and form_data.password == "demo-password":
                user = DBUser(username="demo-student", hashed_password=get_password_hash("demo-password"))
                session.add(user)
                session.commit()
                session.refresh(user)
            else:
                return None
        return user

    user = await run_db_op(do_auth)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    access_token_expires = timedelta(minutes=CONFIG.auth_access_token_expire_minutes)
    access_token = create_access_token(
        data={"sub": user.username}, expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer"}


@app.on_event("startup")
async def startup():
    global _worker_pool
    from config import CONFIG
    from code_exec_api import SANDBOX_RUNNER
    _worker_pool = AsyncWorkerPool(max_workers=CONFIG.max_concurrent_llm)
    await _worker_pool.start()
    print(f"  [EduMatrix] AsyncWorkerPool started: {CONFIG.max_concurrent_llm} workers")
    print(f"  [EduMatrix] LLM: {CONFIG.llm_provider} @ {CONFIG.llm_endpoint} model={CONFIG.llm_model}")
    print(f"  [EduMatrix] Rate limit: {CONFIG.llm_rate_limit_rpm} RPM / {CONFIG.llm_rate_limit_tpm} TPM")
    await SANDBOX_RUNNER.start()


@app.on_event("shutdown")
async def shutdown():
    global _worker_pool
    from code_exec_api import SANDBOX_RUNNER
    if _worker_pool is not None:
        await _worker_pool.stop()
        print("  [EduMatrix] AsyncWorkerPool stopped")
    await SANDBOX_RUNNER.shutdown()
    print("  [EduMatrix] Sandbox runner stopped")

# 静态课程数据集（来自 web_demo.py）
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

def _seed_demo_class(db) -> None:
    """初始化数据库种子数据（演示专用学生）"""
    samples = {
        "stu-ml-001": "我是计算机专业，期末要考机器学习。逻辑回归 and 混淆矩阵总混，accuracy 很高但 recall 低我不知道怎么判断，希望用图和例子一步步讲。",
        "stu-ml-002": "我线性回归能看懂公式，但一到项目就不会做数据预处理，只会照着答案改代码，想要代码实操 and 提示。",
        "stu-ml-003": "我过拟合 and 正则化分不清，训练集分数高就以为模型好，题干长的时候会漏掉验证集条件。",
    }
    for student_id, message in samples.items():
        db_profile = db.query(DBStudentProfile).filter(DBStudentProfile.student_id == student_id).first()
        if not db_profile:
            profile = StudentProfile(student_id=student_id)
            profile.update_from_message(message)
            save_student_profile(db, profile)

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

FRONTEND_DIST = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend", "dist")

@app.get("/", response_class=HTMLResponse)
async def read_index():
    """提供前端 SPA 入口"""
    index_path = os.path.join(FRONTEND_DIST, "index.html")
    if os.path.isfile(index_path):
        return FileResponse(index_path)
    from web_demo import INDEX_HTML
    return INDEX_HTML

@app.get("/api/teacher")
async def get_teacher_dashboard(
    current_user: DBUser = Depends(get_current_user)
):
    """获取教师端诊断看板（直接从本地 SQLite 数据库中读取，实现实时持久化，受 JWT 保护）"""
    def fetch_dashboard_data(session):
        _seed_demo_class(session)
        db_profiles = session.query(DBStudentProfile).all()
        return [load_student_profile(session, db_prof.student_id) for db_prof in db_profiles]

    profiles = await run_db_op(fetch_dashboard_data)
    
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

@app.get("/api/datasets")
async def get_datasets():
    """获取机器学习课件及公开数据集"""
    return {"course": "机器学习导论", "datasets": MACHINE_LEARNING_DATASETS}

@app.post("/api/process")
async def process_student_message(
    request: Request, 
    current_user: DBUser = Depends(get_current_user)
):
    """核心画像提取与多智能体资源生成接口（SQLite 与 Swarm 双轨并网，受 JWT 保护）"""
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")
        
    message = str(payload.get("message") or "").strip()
    student_id = str(payload.get("student_id") or "demo-student").strip()
    
    if not message:
        raise HTTPException(status_code=400, detail="message is required")

    # 1. 物理层：从本地 SQLite 数据库中加载/初始化学生画像
    profile = await run_db_op(load_student_profile, student_id)

    # 2. 动态 LLM：从前端请求头读取 API 配置，构建或复用 Swarm 实例
    active_swarm = build_swarm_from_headers(request.headers)

    # 3. 内存同步：注入 Swarm 运行上下文
    active_swarm.profile_store[student_id] = profile

    # 4. 编排层：运行 1+3+5 智能体矩阵进行画像抽取与资源交付
    package = await active_swarm.async_process(message, student_id=student_id)
    
    # 4. 持久化层与审计层：在一个 DB 事务中在 run_db_op 里执行，保证事务完整性！
    def save_and_log(session):
        save_student_profile(session, package.profile)
        record_alignment_log(session, package.student_id, package.alignment, package.target)
        resource_summary = "; ".join(f"{r.agent}:{r.resource_type}" for r in package.resources)
        record_conversation(
            session, package.student_id, message, resource_summary,
            package.target, len(package.resources), package.alignment.passed,
        )

    await run_db_op(save_and_log)

    return _package_response(package)


app.include_router(knowledge_router)
app.include_router(quiz_router)
app.include_router(web_search_router)
app.include_router(code_exec_router)
app.include_router(profile_router)
app.include_router(stream_router)


@app.get("/api/health")
async def health_check(request: Request):
    from config import CONFIG
    user_api_key = request.headers.get("x-edumatrix-api-key", "")
    has_user_key = bool(user_api_key)
    return {
        "status": "ok",
        "version": "1.1.0",
        "service": "EduMatrix 智教矩阵",
        "llm_provider": CONFIG.llm_provider,
        "llm_model": CONFIG.llm_model,
        "llm_endpoint": CONFIG.llm_endpoint,
        "llm_api_key_configured": bool(CONFIG.llm_api_key) or has_user_key,
        "user_api_key_provided": has_user_key,
        "embedding_provider": CONFIG.embedding_provider,
        "concurrent_llm": CONFIG.max_concurrent_llm,
        "rate_limit_rpm": CONFIG.llm_rate_limit_rpm,
    }


@app.get("/api/metrics")
async def get_metrics():
    from observability import TELEMETRY
    return {
        "recent_metrics": [{"name": m.name, "value": m.value, "tags": m.tags} for m in TELEMETRY.metrics[-20:]],
        "total_recorded": len(TELEMETRY.metrics),
    }


@app.get("/api/sessions/{student_id}")
async def list_sessions(student_id: str):
    conversations = await run_db_op(get_conversation_history, student_id, limit=20)
    return {
        "student_id": student_id,
        "sessions": [
            {
                "id": c.id,
                "query": c.query[:200],
                "target": c.target,
                "resources_count": c.resources_count,
                "alignment_passed": c.alignment_passed,
                "created_at": c.created_at.isoformat(),
            }
            for c in conversations
        ],
    }


_feedback_count: int = 0
_feedback_sum: int = 0


@app.get("/api/feedback")
async def get_feedback_stats():
    return {
        "total_feedback": _feedback_count,
        "average_rating": round(_feedback_sum / _feedback_count, 2) if _feedback_count > 0 else 0,
    }


@app.post("/api/feedback")
async def submit_feedback(request: Request):
    global _feedback_count, _feedback_sum
    payload = await request.json()
    rating = int(payload.get("rating", 0))
    _feedback_count += 1
    _feedback_sum += rating
    TELEMETRY.record_metric("feedback.rating", rating)
    return {
        "received": True,
        "total_feedback": _feedback_count,
        "average_rating": round(_feedback_sum / _feedback_count, 2) if _feedback_count > 0 else 0,
    }


@app.get("/api/notes/{student_id}")
async def list_notes(student_id: str):
    notes = await run_db_op(get_notes, student_id)
    return {"student_id": student_id, "notes": [{"id": n.id, "source": n.source, "content": n.content[:300], "tags": n.tags, "concepts": n.concepts, "created_at": n.created_at.isoformat()} for n in notes]}


@app.post("/api/notes/{student_id}")
async def add_note(student_id: str, request: Request):
    payload = await request.json()
    content = str(payload.get("content", "")).strip()
    if not content:
        raise HTTPException(status_code=400, detail="content is required")
    
    note = await run_db_op(
        create_note, student_id, source=payload.get("source", "manual"),
        content=content, tags=payload.get("tags"), concepts=payload.get("concepts")
    )
    return {"id": note.id, "created_at": note.created_at.isoformat()}


@app.delete("/api/notes/{note_id}")
async def remove_note(note_id: str):
    success = await run_db_op(delete_note, note_id)
    if not success:
        raise HTTPException(status_code=404, detail="note not found")
    return {"deleted": True}


@app.get("/api/progress/{student_id}")
async def get_progress(student_id: str):
    def fetch_data(session):
        profile = load_student_profile(session, student_id)
        notes = get_notes(session, student_id, limit=5)
        return profile, notes

    profile, notes = await run_db_op(fetch_data)
    analyzer = LearningProgressAnalyzer()
    report = analyzer.build_report(
        student_id, profile.concept_mastery,
        notes=[{"id": n.id, "source": n.source, "content": n.content[:200], "tags": n.tags, "concepts": n.concepts, "created_at": n.created_at.isoformat()} for n in notes],
    )
    return {
        "student_id": report.student_id,
        "total_concepts": report.total_concepts,
        "mastered": report.mastered,
        "in_progress": report.in_progress,
        "needs_review": report.needs_review,
        "average_mastery": report.average_mastery,
        "recent_notes": report.recent_notes[:5],
    }


@app.get("/api/history/{student_id}")
async def get_history(student_id: str):
    conversations = await run_db_op(get_conversation_history, student_id)
    return {
        "student_id": student_id,
        "history": [
            {
                "id": c.id,
                "query": c.query[:500],
                "target": c.target,
                "resources_count": c.resources_count,
                "alignment_passed": c.alignment_passed,
                "created_at": c.created_at.isoformat(),
            }
            for c in conversations
        ],
    }


@app.get("/api/review/{student_id}")
async def get_review(student_id: str):
    plans = await run_db_op(get_review_plan, student_id)
    return {
        "student_id": student_id,
        "due_reviews": [
            {
                "concept": p.concept,
                "interval_days": p.interval_days,
                "next_review_at": p.next_review_at.isoformat(),
                "mastery": p.mastery,
                "review_count": p.review_count,
            }
            for p in plans
        ],
    }


@app.post("/api/review/{student_id}")
async def update_review(student_id: str, request: Request):
    payload = await request.json()
    concept = str(payload.get("concept", "")).strip()
    mastery = float(payload.get("mastery", 0.5))
    if not concept:
        raise HTTPException(status_code=400, detail="concept is required")
    scheduler = ReviewScheduler()
    plan = await run_db_op(upsert_review_plan, student_id, concept, mastery, scheduler.INTERVALS[0])
    return {
        "concept": plan.concept,
        "next_review_at": plan.next_review_at.isoformat(),
        "interval_days": plan.interval_days,
        "mastery": plan.mastery,
    }


# ============================================================
# SPA static file serving (for Docker/production)
# ============================================================
if os.path.isdir(FRONTEND_DIST):
    app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)
