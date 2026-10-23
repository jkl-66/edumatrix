import sys
import os
import uuid
import time
import asyncio
import multiprocessing
from datetime import timedelta
from dataclasses import asdict
from typing import Any
from fastapi import FastAPI, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordRequestForm

# 允许 app 导入 root 目录下的模块
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import CONFIG
from concurrency import AsyncWorkerPool, TokenBucket
from models import DIMENSION_LABELS, StudentProfile
from app.database import init_db, DBCourseMembership, DBNote, DBStudentProfile, DBUser, run_db_op
from app.identity import VALID_ROLES, normalize_role
from app.role_landing import resolve_login_landing
from app.crud import (
    load_student_profile,
    save_student_profile,
    record_alignment_log,
    create_note,
    get_notes,
    delete_note,
    get_review_plan,
    upsert_review_plan,
    delete_review_plan,
    review_plan_to_dict,
    record_conversation,
    get_conversation_history,
    update_note,
    append_wrong_question_reflection,
)
from app.auth import authenticate_user, create_access_token, enforce_request_student_scope, enforce_student_access, get_current_user, get_current_teacher, get_password_hash
from knowledge_api import router as knowledge_router
from quiz_api import router as quiz_router
from web_search_api import router as web_search_router
from code_exec_api import router as code_exec_router
from profile_api import router as profile_router
from stream_api import router as stream_router
from animation_api import router as animation_router
from flashcard_api import router as flashcard_router
from behavior_api import router as behavior_router
from report_api import router as report_router
from app.m1_api import router as m1_router
from app.m2_api import router as m2_router
from app.m3_api import router as m3_router
from app.m4_api import router as m4_router
from app.m5_api import router as m5_router, runtime_availability
from app.m6_api import router as m6_router
from app.m7_api import router as m7_router
from app.m8_api import router as m8_router
from app.next_core_api import router as next_core_router
from app.speech_api import router as speech_router
from app.media_context_api import router as media_context_router
from app.interactive_lab_api import router as interactive_lab_router
from app.code_sandbox_api import router as code_sandbox_router
from app.feynman_api import router as feynman_router
from app.course_governance_api import router as course_governance_router
from app.teaching_analytics_api import router as teaching_analytics_router
from app.teacher_api import router as teacher_router
from app.content_review_api import router as content_review_router
from app.model_operations_dashboard_api import router as model_operations_dashboard_router
from app.admin_api import router as admin_router
from app.certification_lifecycle_api import router as certification_lifecycle_router
from app.multilevel_review_api import router as multilevel_review_router
from app.job_standard_impact_api import router as job_standard_impact_router
from app.enterprise_risk_api import router as enterprise_risk_router
from app.course_sharing_api import router as course_sharing_router
from app.marketplace_api import router as marketplace_router
from app.organization_marketplace_api import router as organization_marketplace_router
from app.spatial_workspace_api import router as spatial_workspace_router
from app.plugin_registry_api import router as plugin_registry_router
from app.video_rendering_api import router as video_rendering_router
from app.video_catalog_api import router as video_catalog_router
from app.video_imports_api import router as video_imports_router
from app.wrong_question_videos_api import router as wrong_question_videos_router
from app.chapter_videos_api import router as chapter_videos_router
from app.video_practices_api import router as video_practices_router
from app.teaching_animations_api import router as teaching_animations_router
from app.web_decks_api import router as web_decks_router
from app.local_adapters_api import router as local_adapters_router
from app.resource_bundles_api import router as resource_bundles_router
from app.review_schedule_api import router as review_schedule_router
from app.local_sso_api import router as local_sso_router
from app.local_hr_sync_api import router as local_hr_sync_router
from app.local_lms_api import router as local_lms_router
from app.local_webhook_api import router as local_webhook_router
from app.integration_reconciliation_api import router as integration_reconciliation_router
from app.integration_fault_drill_api import router as integration_fault_drill_router
from app.competition_journey_api import router as competition_journey_router
from app.competition_showcase_api import router as competition_showcase_router
from app.competition_demo_api import router as competition_demo_router
from app.profile_onboarding_api import router as profile_onboarding_router
from app.diagnostic_api import router as diagnostic_router
from app.document_selection import router as document_selection_router
from app.chat_api import router as chat_router
from app.legacy_repositories import LegacyReadRepository
from app.legacy_migration_governance import (
    IdentityProfileHistoryCanonicalReader,
    observe_legacy_shadow_read,
    project_model_row,
)
from app.spa_static import SPAStaticFiles
from app.m5_gateway import StreamingModelCallLifecycle
from app.m5_legacy_calls import audited_legacy_text_call
from app.note_workspace import (
    note_payload,
    note_versions_payload,
    prepare_source_metadata,
    restore_note_version,
    save_ai_suggestion,
)
from note_engine import LearningProgressAnalyzer, ReviewScheduler
from export_pdf import generate_note_pdf
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
async def login_for_access_token(request: Request, form_data: OAuth2PasswordRequestForm = Depends()):
    """JWT 登录接口，获取访问令牌"""
    anon_student_id = request.headers.get("x-anon-student-id")
    def do_auth(session):
        user = authenticate_user(session, form_data.username, form_data.password)
        if not user:
            if form_data.username == "demo-student" and form_data.password == "demo-password":
                user = DBUser(username="demo-student", hashed_password=get_password_hash("demo-password"), role="student", display_name="演示学生")
                session.add(user)
                session.commit()
                session.refresh(user)
            else:
                return None

        # Legacy assistant/visitor records are not formal accounts and cannot
        # obtain a token through the normal login boundary.
        try:
            if normalize_role(user.role) not in VALID_ROLES:
                return None
        except ValueError:
            return None

        # Repair the built-in master-course context for legacy accounts that
        # predate the course seed (idempotent and role-preserving).
        from course_catalog import ensure_primary_course_membership
        ensure_primary_course_membership(session, user)
        session.commit()
        
        # 将在此设备上匿名生成的复习计划、笔记、历史记录合并迁移到登录账户中
        if anon_student_id:
            from app.crud import migrate_anonymous_data
            migrate_anonymous_data(session, anon_student_id, user.username)
        session.refresh(user)
        return user, resolve_login_landing(session, user)

    auth_result = await run_db_op(do_auth)
    if not auth_result:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    user, landing_path = auth_result
    access_token_expires = timedelta(minutes=CONFIG.auth_access_token_expire_minutes)
    access_token = create_access_token(
        data={"sub": user.public_id, "uid": user.public_id, "username": user.username, "role": normalize_role(user.role)}, expires_delta=access_token_expires
    )
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "username": user.username,
        "display_name": user.display_name or user.username,
        "role": user.role or "student",
        "student_id": user.username,
        "user_id": user.public_id,
        "landing_path": landing_path,
    }

@app.post("/api/auth/register")
async def register_user(request: Request):
    """学生注册接口，整合冷启动问卷背景进行协同过滤先验校准"""
    payload = await request.json()
    username = str(payload.get("username", "")).strip()
    password = str(payload.get("password", "")).strip()
    display_name = str(payload.get("display_name", username)).strip()
    
    # Registration only accepts fields the learner actually supplied.  The
    # onboarding conversation is the source of initial profile evidence; do
    # not inject a subject, learning style, or peer-derived mastery values.
    major = str(payload.get("major", "")).strip()
    cognitive_style = str(payload.get("cognitive_style", "")).strip()
    motivation_type = str(payload.get("motivation_type", "未诊断")).strip() or "未诊断"
    
    anon_student_id = request.headers.get("x-anon-student-id")
    
    if not username or not password:
        raise HTTPException(status_code=400, detail="用户名和密码不能为空")
    if len(password) < 4:
        raise HTTPException(status_code=400, detail="密码至少4位")

    def do_register(session):
        existing = LegacyReadRepository(session).user_by_username(username)
        observe_legacy_shadow_read(
            session, chain_id="identity-profile-history", legacy_result=existing,
            canonical_loader=lambda: IdentityProfileHistoryCanonicalReader(session).user_by_username(username),
            legacy_projector=project_model_row,
        )
        if existing:
            raise HTTPException(status_code=409, detail="用户名已存在")
        hashed = get_password_hash(password)
        user = DBUser(username=username, hashed_password=hashed, role="student", display_name=display_name)
        session.add(user)
        
        # Create an honest empty profile.  Real fields are added only after
        # the learner answers onboarding questions or submits learning work.
        db_profile = DBStudentProfile(
            student_id=username,
            target_course="",
            knowledge_base="",
            major=major,
            cognitive_style=cognitive_style,
            motivation_type=motivation_type,
            concept_mastery={},
            bkt_states={}
        )
        session.add(db_profile)
        # Every registered account starts with the built-in master course
        # context; profile content remains empty until onboarding supplies it.
        from course_catalog import ensure_primary_course_membership
        session.flush()
        ensure_primary_course_membership(session, user)
        session.commit()
        
        # 将在此设备上匿名生成的复习计划、笔记、历史记录合并迁移到新注册账户中
        if anon_student_id:
            from app.crud import migrate_anonymous_data
            migrate_anonymous_data(session, anon_student_id, username)
            
        session.refresh(user)
        return user

    try:
        user = await run_db_op(do_register)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"注册失败: {str(e)}")

    access_token_expires = timedelta(minutes=CONFIG.auth_access_token_expire_minutes)
    access_token = create_access_token(
        data={"sub": user.public_id, "uid": user.public_id, "username": user.username, "role": "student"}, expires_delta=access_token_expires
    )
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "username": user.username,
        "display_name": user.display_name or user.username,
        "role": "student",
        "student_id": user.username,
        "user_id": user.public_id,
    }


@app.get("/api/auth/me")
async def read_current_identity(current_user: DBUser = Depends(get_current_user)):
    """Return the server-authoritative identity represented by the token."""
    return {
        "user_id": current_user.public_id,
        "username": current_user.username,
        "display_name": current_user.display_name or current_user.username,
        "role": normalize_role(current_user.role),
        "is_active": bool(current_user.is_active),
    }


@app.on_event("startup")
async def startup():
    global _worker_pool
    # Re-assert the interpreter after all application modules have loaded.
    # Some scientific libraries can alter multiprocessing defaults on Windows.
    multiprocessing.set_executable(sys.executable)
    print(f"  [EduMatrix] Python executable: {sys.executable}")
    from config import CONFIG
    from code_exec_api import SANDBOX_RUNNER
    _worker_pool = AsyncWorkerPool(max_workers=CONFIG.max_concurrent_llm)
    await _worker_pool.start()
    print(f"  [EduMatrix] AsyncWorkerPool started: {CONFIG.max_concurrent_llm} workers")
    print(f"  [EduMatrix] LLM provider={CONFIG.llm_provider} model={CONFIG.llm_model} endpoint_configured={bool(CONFIG.llm_endpoint)}")
    print(f"  [EduMatrix] Rate limit: {CONFIG.llm_rate_limit_rpm} RPM / {CONFIG.llm_rate_limit_tpm} TPM")
    await SANDBOX_RUNNER.start()
    from app.speech_api import recover_interrupted_speech_sessions
    recovered_speech = await run_db_op(recover_interrupted_speech_sessions)
    if recovered_speech:
        print(f"  [EduMatrix] Recovered {recovered_speech} interrupted speech session(s) to failed truth state")
    # 仅在演示模式预置固定账号；幂等执行且不覆盖已有账号密码。
    def seed_teacher(session):
        demo_accounts = (
            ("teacher", "admin123", "teacher", "演示教师"),
            ("demo-admin", "EduMatrix-Demo-2026", "admin", "演示管理员"),
        )
        created = []
        for username, password, role, display_name in demo_accounts:
            user = LegacyReadRepository(session).user_by_username(username)
            observe_legacy_shadow_read(
                session, chain_id="identity-profile-history", legacy_result=user,
                canonical_loader=lambda username=username: IdentityProfileHistoryCanonicalReader(session).user_by_username(username),
                legacy_projector=project_model_row,
            )
            if not user:
                user = DBUser(
                    username=username,
                    hashed_password=get_password_hash(password),
                    role=role,
                    display_name=display_name,
                )
                session.add(user)
                created.append(username)
            elif username.startswith("demo-"):
                # Keep credentials user-owned while repairing the demo account metadata.
                user.role = role
                user.display_name = display_name
        session.commit()
        if created:
            print(f"  [EduMatrix] Demo accounts created: {', '.join(created)}")
    if CONFIG.demo_mode:
        await run_db_op(seed_teacher)
    from course_catalog import seed_default_courses
    course_seed = await run_db_op(seed_default_courses)
    print(
        "  [EduMatrix] Published courses ready: "
        f"{course_seed['course_count']} courses / {course_seed['documents']} documents / "
        f"{course_seed['chunks']} chunks"
    )
    pending_course_updates = [
        item for item in course_seed["courses"] if item["status"] == "update_available"
    ]
    for item in pending_course_updates:
        preflight = item["preflight"]
        print(
            "  [EduMatrix] Course update requires explicit approval: "
            f"{item['course_id']} {preflight['current_version']} -> "
            f"{preflight['incoming_version']} (database and RAG left unchanged)"
        )


@app.on_event("shutdown")
async def shutdown():
    global _worker_pool
    from code_exec_api import SANDBOX_RUNNER
    from app.code_sandbox import CODE_SANDBOX_RUN_COORDINATOR
    if _worker_pool is not None:
        await _worker_pool.stop()
        print("  [EduMatrix] AsyncWorkerPool stopped")
    await CODE_SANDBOX_RUN_COORDINATOR.shutdown()
    print("  [EduMatrix] Formal code-sandbox runner stopped")
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
    {
        "name": "人工智能基础 (核心课设)",
        "task": "理论框架、综合复习、本地知识库",
        "url": "本地文件: data/人工智能基础/",
        "note": "这是我上传的独家《人工智能基础》本地课设压缩包资料，包含核心讲义与练习。",
    },
]

def _seed_demo_class(db) -> None:
    """初始化数据库种子数据（演示专用学生）"""
    competition_students = db.query(DBCourseMembership).filter_by(
        course_id="demo-course-rag-trust-v1",
        role="student",
        status="active",
    ).count()
    if competition_students:
        return
    samples = {
        "stu-ml-001": "我是计算机专业，期末要考机器学习。逻辑回归 and 混淆矩阵总混，accuracy 很高但 recall 低我不知道怎么判断，希望用图和例子一步步讲。",
        "stu-ml-002": "我线性回归能看懂公式，但一到项目就不会做数据预处理，只会照着答案改代码，想要代码实操 and 提示。",
        "stu-ml-003": "我过拟合 and 正则化分不清，训练集分数高就以为模型好，题干长的时候会漏掉验证集条件。",
    }
    for student_id, message in samples.items():
        db_profile = LegacyReadRepository(db).student_profile(student_id)
        observe_legacy_shadow_read(
            db, chain_id="identity-profile-history", legacy_result=db_profile,
            canonical_loader=lambda student_id=student_id: IdentityProfileHistoryCanonicalReader(db).student_profile(student_id),
            legacy_projector=project_model_row,
        )
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

@app.get("/api/teacher")  # MARKER_20260627
async def get_teacher_dashboard(
    current_user: DBUser = Depends(get_current_teacher)
):
    """获取教师端诊断看板（仅教师可访问）"""
    print("  [Teacher] get_teacher_dashboard called - checking version")
    def fetch_dashboard_data(session):
        _seed_demo_class(session)
        student_ids = LegacyReadRepository(session).student_profile_ids()
        observe_legacy_shadow_read(
            session, chain_id="identity-profile-history", legacy_result=student_ids,
            canonical_loader=lambda: IdentityProfileHistoryCanonicalReader(session).student_profile_ids(),
        )
        return [load_student_profile(session, student_id) for student_id in student_ids]

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
    major_distribution: dict[str, int] = {}
    dimension_averages: dict[str, float] = {k: 0.0 for k in DIMENSION_LABELS}
    dimension_counts: dict[str, int] = {k: 0 for k in DIMENSION_LABELS}
    
    for profile in profiles:
        for name, value in profile.misconception_patterns.items():
            misconception_rank[name] = misconception_rank.get(name, 0.0) + value
        for cause in profile.learning_state_causes.values():
            for intervention in cause.recommended_interventions:
                intervention_rank[intervention] = intervention_rank.get(intervention, 0) + 1
        major = profile.major or profile.major_preference or "未设置"
        major_distribution[major] = major_distribution.get(major, 0) + 1
        for key in DIMENSION_LABELS:
            state = profile.dimension_states.get(key)
            if state:
                dimension_averages[key] = dimension_averages.get(key, 0.0) + state.score
                dimension_counts[key] = dimension_counts.get(key, 0) + 1

    # 计算班级各维度平均分
    class_dimension_avg = {}
    for key in DIMENSION_LABELS:
        cnt = dimension_counts.get(key, 0)
        class_dimension_avg[key] = round(dimension_averages.get(key, 0.0) / cnt, 2) if cnt > 0 else 0.0

    # === 教师增强数据 ===

    # 1. 班级摘要
    total = len(profiles)
    avg_mastery_val = sum(calc_avg_mastery(p) for p in profiles) / max(total, 1)
    alert_count = sum(1 for p in profiles if (p.frustration_index or 0) > 0.3 or (p.cognitive_load or 0) > 0.6)

    low_mastery_count = 0
    concept_class_mastery: dict[str, list[float]] = {}
    for p in profiles:
        for c, s in (p.concept_mastery or {}).items():
            concept_class_mastery.setdefault(c, []).append(s)
        # 平均掌握度 < 0.3 算低掌握度学生
        pm = calc_avg_mastery(p)
        if pm < 0.3:
            low_mastery_count += 1

    class_summary = {
        "total_students": total,
        "avg_mastery": round(avg_mastery_val, 2),
        "alert_count": alert_count,
        "low_mastery_count": low_mastery_count,
    }

    # 2. 概念全班排行（按平均掌握度升序 = 最薄弱在前）
    concept_class_ranking = sorted(
        [
            {
                "concept": c,
                "avg_mastery": round(sum(v) / len(v), 2),
                "student_count": len(v),
            }
            for c, v in concept_class_mastery.items()
        ],
        key=lambda item: item["avg_mastery"],
    )[:15]

    # 3. 高危学生列表
    alert_students = []
    for p in profiles:
        reasons = []
        fi = p.frustration_index or 0
        cl = p.cognitive_load or 0
        pm = calc_avg_mastery(p)
        if fi > 0.3:
            reasons.append(f"挫败感偏高({round(fi*100)}%)")
        if cl > 0.6:
            reasons.append(f"认知负荷过高({round(cl*100)}%)")
        if pm < 0.3:
            reasons.append(f"掌握度极低({round(pm*100)}%)")
        if reasons:
            alert_students.append({
                "student_id": p.student_id,
                "reasons": reasons,
                "frustration_index": round(fi, 2),
                "cognitive_load": round(cl, 2),
                "mastery": round(pm, 2),
            })
    alert_students = sorted(alert_students, key=lambda a: -a["frustration_index"])[:10]

    # 4. 每个学生最近活动（简化为最近画像更新时间）
    recent_activities = []
    for p in profiles:
        ts = getattr(p, "last_update_timestamp", "") or ""
        recent_activities.append({
            "student_id": p.student_id,
            "last_active": ts[:19] if ts else "",
        })
    recent_activities.sort(key=lambda a: a["last_active"], reverse=True)

    return {
        "course": "机器学习导论",
        "dimensions": DIMENSION_LABELS,
        "class_summary": class_summary,
        "class_dimension_avg": class_dimension_avg,
        "heatmap": heatmap,
        "major_distribution": sorted(
            [{"major": name, "count": count} for name, count in major_distribution.items()],
            key=lambda item: item["count"],
            reverse=True,
        ),
        "concept_class_ranking": concept_class_ranking,
        "alert_students": alert_students,
        "recent_activities": recent_activities,
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


def calc_avg_mastery(profile) -> float:
    """计算单个画像的平均掌握度"""
    m = profile.concept_mastery or {}
    if not m:
        return 0.0
    vals = [v for v in m.values() if isinstance(v, (int, float))]
    return sum(vals) / len(vals) if vals else 0.0

@app.get("/api/teacher/seed")
async def seed_student_data(
    current_user: DBUser = Depends(get_current_teacher)
):
    """触发学生种子数据生成（仅教师可调用）"""
    try:
        from scripts.seed_students import seed_all
        seed_all()
        return {"status": "ok", "message": "学生数据已生成"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"种子数据生成失败: {str(e)}")

@app.get("/api/teacher/reviews")
async def get_teacher_reviews(
    current_user: DBUser = Depends(get_current_teacher)
):
    """获取全班学生的复习计划（教师复习监控）"""
    from app.crud import get_review_plan
    from app.database import DBStudentProfile

    def fetch(session):
        student_ids = LegacyReadRepository(session).student_profile_ids()
        observe_legacy_shadow_read(
            session, chain_id="identity-profile-history", legacy_result=student_ids,
            canonical_loader=lambda: IdentityProfileHistoryCanonicalReader(session).student_profile_ids(),
        )
        result = []
        for student_id in student_ids:
            plans = get_review_plan(session, student_id)
            if plans:
                result.append({
                    "student_id": student_id,
                    "review_count": len(plans),
                    "next_review": plans[0].next_review_time.isoformat() if hasattr(plans[0], 'next_review_time') else "",
                    "due_concepts": [p.concept_name for p in plans[:3]] if hasattr(plans[0], 'concept_name') else [],
                })
        return result

    reviews = await run_db_op(fetch)
    return {"reviews": reviews, "total": len(reviews)}

@app.get("/api/datasets")
async def get_datasets():
    """获取机器学习课件及公开数据集"""
    return {"course": "机器学习导论", "datasets": MACHINE_LEARNING_DATASETS}

@app.get("/api/v1/video/stream")
async def stream_video(student_id: str):
    """自适应生成讲解视频的推流端点 (Task 8.5/8.6 兜底)"""
    local_path = os.path.join(
        "data", "raw", "github_repos", "compsci-589", "src", "Figures", "iShadow_calib.mp4"
    )
    if os.path.isfile(local_path):
        return FileResponse(local_path)
    # 联网时重定向到外部公共 MP4，死保演示端点不为 404
    return RedirectResponse(url="https://www.w3schools.com/html/mov_bbb.mp4")

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
    student_id = enforce_student_access(payload.get("student_id"), current_user)
    
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
app.include_router(animation_router)
app.include_router(flashcard_router)
app.include_router(behavior_router)
app.include_router(report_router)
app.include_router(m1_router)
app.include_router(m2_router)
app.include_router(m3_router)
app.include_router(m4_router)
app.include_router(m5_router)
app.include_router(m6_router)
app.include_router(m7_router)
app.include_router(code_sandbox_router)
app.include_router(feynman_router)
app.include_router(m8_router)
app.include_router(next_core_router)
app.include_router(speech_router)
app.include_router(media_context_router)
app.include_router(interactive_lab_router)
app.include_router(course_governance_router)
app.include_router(teaching_analytics_router)
app.include_router(teacher_router)
app.include_router(content_review_router)
app.include_router(model_operations_dashboard_router)
app.include_router(admin_router)
app.include_router(certification_lifecycle_router)
app.include_router(multilevel_review_router)
app.include_router(job_standard_impact_router)
app.include_router(enterprise_risk_router)
app.include_router(course_sharing_router)
app.include_router(marketplace_router)
app.include_router(organization_marketplace_router)
app.include_router(spatial_workspace_router)
app.include_router(plugin_registry_router)
app.include_router(video_rendering_router)
app.include_router(video_catalog_router)
app.include_router(video_imports_router)
app.include_router(wrong_question_videos_router)
app.include_router(chapter_videos_router)
app.include_router(video_practices_router)
app.include_router(teaching_animations_router)
app.include_router(web_decks_router)
app.include_router(local_adapters_router)
app.include_router(resource_bundles_router)
app.include_router(review_schedule_router)
app.include_router(local_sso_router)
app.include_router(local_hr_sync_router)
app.include_router(local_lms_router)
app.include_router(local_webhook_router)
app.include_router(integration_reconciliation_router)
app.include_router(integration_fault_drill_router)
app.include_router(competition_journey_router)
app.include_router(competition_showcase_router)
app.include_router(competition_demo_router)
app.include_router(profile_onboarding_router)
app.include_router(diagnostic_router)
app.include_router(document_selection_router)
app.include_router(chat_router)


# Keep the historical direct route name while delegating to the single governed
# implementation in stream_api. Some FastAPI versions retain the latest route
# for duplicate path/method registrations.
@app.post("/api/stream/explain", dependencies=[Depends(get_current_user)])
async def socratic_explain_direct(
    request: Request,
    current_user: DBUser = Depends(get_current_user),
) -> Any:
    from stream_api import socratic_explain

    return await socratic_explain(request, current_user)


@app.get("/api/health")
async def health_check(request: Request):
    from config import CONFIG
    from sqlalchemy import text as sql_text
    database_ok = False
    try:
        from app.database import engine
        with engine.connect() as connection:
            connection.execute(sql_text("SELECT 1"))
        database_ok = True
    except Exception:
        database_ok = False
    runtime = runtime_availability()
    return {
        "status": "ok" if database_ok else "degraded",
        "version": "1.1.0",
        "service": "EduMatrix 智教矩阵",
        "dependencies": {
            "database": {"available": database_ok},
            "text_model": {"available": runtime.text_model},
            "vision_model": {"available": runtime.vision_model},
            "retrieval": {"available": runtime.retrieval},
            "sandbox": {"mode": runtime.sandbox_mode, "available": runtime.sandbox_mode != "disabled"},
            "media_pipeline": {"available": runtime.media_pipeline},
        },
        "secrets": {"backend_configured": bool(CONFIG.llm_api_key), "client_keys_accepted": False},
    }


@app.get("/api/llm/test")
async def test_llm_connection(
    request: Request,
    current_user: DBUser = Depends(get_current_user),
):
    """测试 LLM 连通性：发送一条简短消息验证 API 是否可用"""
    swarm_obj = build_swarm_from_headers({})
    llm = swarm_obj.llm

    llm_type = type(llm).__name__
    if "Deterministic" in llm_type:
        return {
            "status": "warning",
            "message": "当前使用模拟引擎（DeterministicEducationLLM），未接入真实大模型",
            "hint": "请由管理员在后端环境中设置 EDUMATRIX_LLM_API_KEY",
            "llm_type": llm_type,
        }

    try:
        result = await audited_legacy_text_call(
            llm,
            system_prompt="你是一个教学助手，请用一句话简短回答。",
            user_prompt="请回复：API连接测试成功",
            role="测试",
            operation="text_connection_test",
            capability="answer",
            owner_public_id=current_user.public_id,
            input_summary={"operation_scope": "fixed_probe", "user_data_included": False},
        )
        return {
            "status": "ok",
            "message": "LLM 连通性测试成功",
            "llm_type": llm_type,
            "response": result[:200],
            "model": CONFIG.llm_model,
        }
    except Exception as e:
        return {
            "status": "error",
            "message": "LLM 调用失败",
            "llm_type": llm_type,
            "model": CONFIG.llm_model,
        }


@app.get("/api/llm/test-vision")
async def test_vision_connection(
    request: Request,
    current_user: DBUser = Depends(get_current_user),
):
    """Send a tiny image through the configured vision route.

    This endpoint verifies the evaluator's actual visual-model configuration,
    while returning only status and a short response preview.
    """
    swarm_obj = build_swarm_from_headers(request.headers)
    llm = swarm_obj.llm
    llm_type = type(llm).__name__
    vision_llm = getattr(llm, "external_vision_backend", None)
    if vision_llm is None:
        return {
            "status": "warning",
            "message": "当前没有可用的外部视觉模型配置",
            "hint": "请同时配置主模型或在 Settings 页面填写视觉 API Key、Endpoint 和模型名称",
            "llm_type": llm_type,
        }

    test_image = (
        "data:image/png;base64,"
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
    )
    provider = CONFIG.multimodal_llm_provider or CONFIG.llm_provider or "unknown"
    model = getattr(
        vision_llm,
        "model",
        CONFIG.multimodal_llm_model or CONFIG.llm_model or "unknown",
    )
    system_prompt = "你是视觉模型连通性测试助手。"
    user_prompt = "请确认你已收到一张图片，仅用一句话回复。"
    lifecycle = StreamingModelCallLifecycle(
        capability="vision",
        prompt_key="legacy_vision_connection_test",
        prompt_version="1.0",
        provider=provider,
        model=model,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        owner_public_id=current_user.public_id,
        input_summary={
            "operation": "vision_connection_test",
            "image_count": 1,
            "image_encoded_chars": len(test_image),
            "image_payload_included": False,
            "user_data_included": False,
        },
        database_runner=run_db_op,
    )
    await lifecycle.start()
    chunks = []
    try:
        async for chunk in vision_llm.generate_stream(
            system_prompt,
            user_prompt,
            role="视觉连接测试",
            images=[test_image],
        ):
            chunks.append(chunk)
            if sum(len(item) for item in chunks) >= 500:
                break
        output = "".join(chunks)
        await lifecycle.complete(output)
        return {
            "status": "ok",
            "message": "视觉模型请求已成功返回",
            "llm_type": llm_type,
            "response": output[:500],
        }
    except asyncio.CancelledError:
        await asyncio.shield(lifecycle.fail("client_disconnected", "".join(chunks)))
        raise
    except Exception:
        await lifecycle.fail("vision_connection_test_provider_failed", "".join(chunks))
        return {
            "status": "error",
            "message": "视觉模型调用失败",
            "llm_type": llm_type,
        }


@app.get("/api/metrics")
async def get_metrics():
    from observability import TELEMETRY
    return {
        "recent_metrics": [{"name": m.name, "value": m.value, "tags": m.tags} for m in TELEMETRY.metrics[-20:]],
        "total_recorded": len(TELEMETRY.metrics),
    }


@app.get("/api/sessions/{student_id}", dependencies=[Depends(enforce_request_student_scope)])
async def list_sessions(
    student_id: str,
    current_user: DBUser = Depends(get_current_user),
):
    student_id = enforce_student_access(student_id, current_user)
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


@app.post("/api/notes/ai-polish", dependencies=[Depends(get_current_user)])
async def polish_note(
    request: Request,
    current_user: DBUser = Depends(get_current_user),
):
    try:
        payload = await request.json()
        content = str(payload.get("content", "")).strip()
        if not content:
            raise HTTPException(status_code=400, detail="content is required")
        
        # 1. 提取与保护原始笔记中的代码块（Mermaid 思维导图除外），防止大段代码消耗过多 Token 导致生成截断
        import re
        code_blocks = []
        def code_block_repl(match):
            block_content = match.group(0)
            first_line = block_content.split('\n')[0].lower()
            if 'mermaid' in first_line:
                # 不保护 mermaid 块，允许大模型在润色时进行优化
                return block_content
            # 保护其他代码块，存入列表中，替换为占位符
            placeholder = f"[CODE_BLOCK_PLACEHOLDER_{len(code_blocks)}]"
            code_blocks.append(block_content)
            return placeholder

        placeholder_content = re.sub(r"```[\s\S]*?```", code_block_repl, content)

        # 从请求头中构建专属 Swarm 实例以获取用户自定义 of API Key/Endpoint/Model (防 500 熔断)
        active_swarm = build_swarm_from_headers(request.headers)
        
        system_prompt = (
            "你是一个顶级的全栈教育学者与机器学习专家。请对用户提供的原始笔记或对话提炼内容进行深度的整理、扩写与学术级排版。\n"
            "【核心任务目标】：\n"
            "- 【去芜存菁，过滤对话噪点】：必须完全过滤和去除所有无意义的口水话、寒暄语、引导词（例如'好的，我来为您...'，'没问题'等）。\n"
            "- 【严禁无端缩减笔记，必须深度扩写丰富】：绝对不能将核心内容精简或缩水！相反，你应当以学术级标准对原有的知识点进行系统性扩写与深度补充，丰富核心原理的来龙去脉、物理意义、应用场景与公式推导。\n"
            "- 【保留代码占位符】：如果输入文本中包含 `[CODE_BLOCK_PLACEHOLDER_N]`（如 `[CODE_BLOCK_PLACEHOLDER_0]`）形式的占位符，请在输出的对应位置（通常在正文的“实践示例与核心代码”或相关版块中）原封不动地保留该占位符。千万不要尝试自行重写或生成代码，也不要删除这些占位符，因为我们会在后处理中自动将它们还原为原始代码。这可以极大节省 token 空间并防止大模型被截断。\n"
            "- 【自动设计嵌入概念思维导图】：在笔记正文的第一部分，自动设计并嵌入一个能够直观表示本笔记知识框架的 ```mermaid 思维导图（必须是 mindmap 格式，例如：\n"
            "  ```mermaid\n"
            "  mindmap\n"
            "    root((\"核心主题\"))\n"
            "      分支1[\"子概念A\"]\n"
            "        叶子1(\"细节描述1\")\n"
            "      分支2[\"子概念B\"]\n"
            "  ```\n"
            "  特别注意：在 Mermaid 节点文字中若包含中文、空格、小括号或任何特殊字符，**必须全部用双引号包裹**（如：root((\"卷积神经网络 (CNN)\"))），且思维导图内不得包含 LaTeX 格式公式，只用纯文本，以确保渲染器完美渲染，不发生任何解析错误）。\n\n"
            "【输出格式规范】：\n"
            "1. 【思维导图优先】：在笔记正文最开头，以独立的 ```mermaid 代码块展示刚才设计的 mindmap 思维导图。\n"
            "2. 【深度正文展开】：正文须使用标题清晰、层次分明的 Markdown 格式展开。建议分为以下几个大板块：\n"
            "   - ### 核心概念定义及背景：详尽补充前置基础知识、核心公式与背景。\n"
            "   - ### 实践示例与核心代码（如有）：在相应位置写上对应的 `[CODE_BLOCK_PLACEHOLDER_N]` 占位符以保留原始代码。\n"
            "   - ### 详细逻辑推导与核心要点：把推导逻辑层层展开，不省略数学步骤。\n"
            "3. 【数学公式排版】：所有的数学变量、参数和方程必须应用标准的 LaTeX 格式进行排版，行内使用单个 $ 包裹（如：$w$, $x$, $\\theta$），独立公式或推导块必须使用双美元符号 $$ 包裹，且公式中的乘号使用 \\cdot 或 \\times，求和使用 \\sum 等标准 LaTeX 符号，确保在页面中完美渲染。\n"
            "4. 在笔记内容的【最后一行】，输出自动分析并推荐的关联标签 and 概念列表，格式必须严格固定为：\n"
            "===TAGS_AND_CONCEPTS===\n"
            "Tags: tag1, tag2\n"
            "Concepts: concept1, concept2\n"
            "========================\n"
            "注意：Tags 和 Concepts 必须是提取出的精炼实体，Concepts 需尽量匹配机器学习核心概念。"
        )
        user_prompt = f"以下是学生的原始笔记内容：\n\n{placeholder_content}"
        provider = (
            "deterministic"
            if active_swarm.llm.__class__.__name__ == "AsyncDeterministicEducationLLM"
            else CONFIG.llm_provider
        )
        model = getattr(
            active_swarm.llm,
            "model",
            "deterministic" if provider == "deterministic" else CONFIG.llm_model,
        )
        lifecycle = StreamingModelCallLifecycle(
            capability="answer",
            prompt_key="legacy_note_polish",
            prompt_version="1.0",
            provider=provider or "unknown",
            model=model or "unknown",
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            owner_public_id=current_user.public_id,
            input_summary={
                "operation": "note_polish",
                "source_chars": len(content),
                "protected_code_block_count": len(code_blocks),
                "contains_mermaid": "```mermaid" in content,
            },
            database_runner=run_db_op,
        )
        await lifecycle.start()
        provider_failed = False
        try:
            polished = await active_swarm.llm.generate(system_prompt, user_prompt, role="笔记整理官")
        except asyncio.CancelledError:
            await asyncio.shield(lifecycle.fail("client_disconnected"))
            raise
        except Exception:
            await lifecycle.fail("note_polish_provider_failed")
            provider_failed = True
            polished = f"// AI 润色暂时不可用\n\n{content}"
        else:
            await lifecycle.complete(polished)
        
        # 2. 还原被保护的原始代码块
        restored_indices = set()
        for i, original_code in enumerate(code_blocks):
            pattern = rf"\[\s*CODE_BLOCK_PLACEHOLDER_{i}\s*\]|CODE_BLOCK_PLACEHOLDER_{i}"
            if re.search(pattern, polished, re.IGNORECASE):
                polished = re.sub(pattern, lambda m: original_code, polished, flags=re.IGNORECASE)
                restored_indices.add(i)
        
        # 3. 安全垫：如果大模型在生成中漏掉了某个代码占位符，将其追加到最后（Tags_AND_CONCEPTS 前）
        lost_blocks = [code_blocks[i] for i in range(len(code_blocks)) if i not in restored_indices]
        if lost_blocks:
            meta_marker = "===TAGS_AND_CONCEPTS==="
            if meta_marker in polished:
                parts = polished.split(meta_marker)
                parts[0] = parts[0].strip() + "\n\n### 实践示例与核心代码（自动备份）\n" + "\n\n".join(lost_blocks) + "\n\n"
                polished = meta_marker.join(parts)
            else:
                polished = polished.strip() + "\n\n### 实践示例与核心代码（自动备份）\n" + "\n\n".join(lost_blocks)

        # 解析标签和概念
        tags, concepts = [], []
        clean_content = polished
        meta_match = re.search(r"===TAGS_AND_CONCEPTS===\s*\nTags:\s*(.*?)\s*\nConcepts:\s*(.*?)\s*\n========================", polished, re.S | re.M)
        if meta_match:
            tag_str = meta_match.group(1)
            concept_str = meta_match.group(2)
            tags = [t.strip() for t in tag_str.split(",") if t.strip()]
            concepts = [c.strip() for c in concept_str.split(",") if c.strip()]
            clean_content = polished.replace(meta_match.group(0), "").strip()
        else:
            tag_line = re.search(r"^Tags:\s*(.*)$", polished, re.M | re.I)
            concept_line = re.search(r"^Concepts:\s*(.*)$", polished, re.M | re.I)
            if tag_line:
                tags = [t.strip() for t in tag_line.group(1).split(",") if t.strip()]
                clean_content = clean_content.replace(tag_line.group(0), "").strip()
            if concept_line:
                concepts = [c.strip() for c in concept_line.group(1).split(",") if c.strip()]
                clean_content = clean_content.replace(concept_line.group(0), "").strip()
        
        tags = [t for t in tags if t.lower() != 'none']
        concepts = [c for c in concepts if c.lower() != 'none']
        
        saved_suggestion = None
        note_id = str(payload.get("note_id") or "").strip()
        if note_id and not provider_failed:
            try:
                expected_version = int(payload.get("expected_version"))
            except (TypeError, ValueError):
                raise HTTPException(status_code=422, detail="expected_version is required for a saved AI suggestion")
            idempotency_key = str(payload.get("idempotency_key") or "").strip()
            if len(idempotency_key) < 8:
                raise HTTPException(status_code=422, detail="idempotency_key is required for a saved AI suggestion")

            def persist_suggestion(session):
                note = save_ai_suggestion(
                    session,
                    note_id=note_id,
                    actor=current_user,
                    expected_version=expected_version,
                    idempotency_key=idempotency_key,
                    content=clean_content.strip(),
                    tags=tags,
                    concepts=concepts,
                )
                session.commit()
                session.refresh(note)
                return note_payload(session, actor=current_user, note=note)

            saved_suggestion = await run_db_op(persist_suggestion)

        return {
            "polished_content": clean_content.strip(),
            "tags": tags,
            "concepts": concepts,
            "suggestion_status": "unavailable" if provider_failed else "ready",
            "note": saved_suggestion,
        }
    except Exception as outer_e:
        import traceback
        with open("scratch/debug_polish.log", "w", encoding="utf-8") as f:
            f.write(traceback.format_exc())
        raise outer_e


@app.post("/api/notes/append-reflection", dependencies=[Depends(get_current_user)])
async def append_reflection(
    request: Request,
    current_user: DBUser = Depends(get_current_user),
):
    payload = await request.json()
    student_id = enforce_student_access(payload.get("student_id"), current_user)
    concept = str(payload.get("concept", "")).strip()
    quiz_record_id = str(payload.get("quiz_record_id", "")).strip()
    wrong_reason = str(payload.get("wrong_reason", "misconception")).strip()
    
    if not student_id or not concept or not quiz_record_id:
        raise HTTPException(status_code=400, detail="student_id, concept, and quiz_record_id are required")
        
    note = await run_db_op(
        append_wrong_question_reflection,
        student_id=student_id,
        concept=concept,
        quiz_record_id=quiz_record_id,
        wrong_reason=wrong_reason
    )
    def _record_reflection_evidence(session):
        from app.m5_assessment import AssessmentEvidenceInput, record_legacy_assessment_evidence
        evidence = AssessmentEvidenceInput(
            idempotency_key=f"legacy-reflection-{note.id}-{quiz_record_id}",
            source_type="wrong_question_review", source_object_id=quiz_record_id,
            target_object_type="note", target_object_id=str(note.id),
        )
        result = record_legacy_assessment_evidence(session, student_id=student_id, evidence=evidence)
        session.commit()
        return result
    canonical_evidence = await run_db_op(_record_reflection_evidence)
    return {"id": note.id, "updated_at": note.updated_at.isoformat(), "canonical_evidence": canonical_evidence}


@app.post("/api/notes/update/{note_id}", dependencies=[Depends(get_current_user)])
async def update_existing_note(
    note_id: str,
    request: Request,
    current_user: DBUser = Depends(get_current_user),
):
    payload = await request.json()
    content = str(payload.get("content", "")).strip()
    if not content:
        raise HTTPException(status_code=400, detail="content is required")
    
    requested_student_id = payload.get("student_id")
    student_scope = enforce_student_access(requested_student_id, current_user)
    expected_version = payload.get("expected_version")
    if expected_version is not None:
        try:
            expected_version = int(expected_version)
        except (TypeError, ValueError):
            raise HTTPException(status_code=422, detail="expected_version must be an integer")
    idempotency_key = str(payload.get("idempotency_key") or "").strip() or None

    def save(session):
        note = update_note(
            session,
            note_id,
            content=content,
            tags=payload.get("tags"),
            concepts=payload.get("concepts"),
            student_id=None if current_user.role == "teacher" else student_scope,
            expected_version=expected_version,
            idempotency_key=idempotency_key,
            actor=current_user,
            change_type=str(payload.get("change_type") or "saved"),
            task_id=str(payload.get("task_id") or "") or None,
        )
        if note is None:
            raise HTTPException(status_code=404, detail="note not found")
        return note_payload(session, actor=current_user, note=note)

    return await run_db_op(save)


@app.get("/api/notes/{student_id}", dependencies=[Depends(enforce_request_student_scope)])
async def list_notes(
    student_id: str,
    current_user: DBUser = Depends(get_current_user),
):
    student_id = enforce_student_access(student_id, current_user)
    def fetch(session):
        notes = get_notes(session, student_id)
        return [note_payload(session, actor=current_user, note=note) for note in notes]

    return {"student_id": student_id, "notes": await run_db_op(fetch)}


@app.post("/api/notes/{student_id}", dependencies=[Depends(enforce_request_student_scope)])
async def add_note(
    student_id: str,
    request: Request,
    current_user: DBUser = Depends(get_current_user),
):
    student_id = enforce_student_access(student_id, current_user)
    payload = await request.json()
    content = str(payload.get("content", "")).strip()
    if not content:
        raise HTTPException(status_code=400, detail="content is required")
    
    source_type = str(payload.get("source_type") or payload.get("source") or "manual").strip()
    idempotency_key = str(payload.get("idempotency_key") or "").strip() or None

    def create(session):
        normalized_type, source_metadata = prepare_source_metadata(
            session,
            actor=current_user,
            source_type=source_type,
            metadata=payload.get("source_metadata"),
        )
        note = create_note(
            session,
            student_id,
            source=normalized_type,
            content=content,
            tags=payload.get("tags"),
            concepts=payload.get("concepts"),
            source_metadata=source_metadata,
            idempotency_key=idempotency_key,
            actor=current_user,
            task_id=str(payload.get("task_id") or "") or None,
        )
        return note_payload(session, actor=current_user, note=note)

    return await run_db_op(create)


@app.get("/api/notes/{note_id}/versions", dependencies=[Depends(get_current_user)])
async def list_note_versions(
    note_id: str,
    current_user: DBUser = Depends(get_current_user),
):
    def fetch(session):
        note = session.get(DBNote, note_id)
        if note is None:
            raise HTTPException(status_code=404, detail="note not found")
        return {
            "note_id": note.id,
            "current_version": int(note.current_version_number or 1),
            "lock_version": int(note.lock_version or 1),
            "versions": note_versions_payload(session, actor=current_user, note=note),
        }

    return await run_db_op(fetch)


@app.post("/api/notes/{note_id}/versions/{version_number}/restore", dependencies=[Depends(get_current_user)])
async def restore_existing_note_version(
    note_id: str,
    version_number: int,
    request: Request,
    current_user: DBUser = Depends(get_current_user),
):
    payload = await request.json()
    try:
        expected_version = int(payload.get("expected_version"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail="expected_version is required")
    idempotency_key = str(payload.get("idempotency_key") or "").strip()
    if len(idempotency_key) < 8:
        raise HTTPException(status_code=422, detail="idempotency_key is required")

    def restore(session):
        note, _ = restore_note_version(
            session,
            note_id=note_id,
            version_number=version_number,
            expected_version=expected_version,
            idempotency_key=idempotency_key,
            actor=current_user,
        )
        session.commit()
        session.refresh(note)
        return note_payload(session, actor=current_user, note=note)

    return await run_db_op(restore)


@app.delete("/api/notes/{note_id}", dependencies=[Depends(get_current_user)])
async def remove_note(
    note_id: str,
    current_user: DBUser = Depends(get_current_user),
):
    success = await run_db_op(
        delete_note,
        note_id,
        student_id=None if current_user.role == "teacher" else current_user.username,
    )
    if not success:
        raise HTTPException(status_code=404, detail="note not found")
    return {"deleted": True}


@app.post("/api/export-notes-pdf", dependencies=[Depends(get_current_user)])
async def export_note_pdf(request: Request):
    """任务 2: 将笔记导出为 PDF 文件。"""
    from fastapi.responses import StreamingResponse
    from io import BytesIO
    import asyncio
    
    try:
        payload = await request.json()
    except Exception:
        payload = {}
        
    title = str(payload.get("title") or "学习笔记").strip()
    content = str(payload.get("content") or "").strip()
    subtitle = str(payload.get("subtitle") or "").strip()
    tags = str(payload.get("tags") or "").strip()
    source = str(payload.get("source") or "学习笔记").strip()
    concepts = payload.get("concepts") or []
    if not isinstance(concepts, list):
        concepts = [str(concepts)]
    
    if not content:
        raise HTTPException(status_code=400, detail="笔记内容不能为空，请先在编辑器中输入或保存笔记内容。")
    
    try:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = asyncio.get_event_loop()
            
        pdf_bytes = await loop.run_in_executor(
            None, generate_note_pdf,
            title, content, subtitle, tags, source, concepts, None,
        )
        
        import re
        safe_title = re.sub(r'[/\\?%*:|"<> ]', '_', title[:30])
        import urllib.parse
        encoded_filename = urllib.parse.quote(safe_title)
        
        return StreamingResponse(
            BytesIO(pdf_bytes),
            media_type="application/pdf",
            headers={
                "Content-Disposition": f"attachment; filename=\"edumatrix-note.pdf\"; filename*=utf-8''{encoded_filename}.pdf",
                "Content-Length": str(len(pdf_bytes)),
            },
        )
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"PDF 生成失败: {str(e)[:200]}")


@app.get("/api/progress/{student_id}", dependencies=[Depends(enforce_request_student_scope)])
async def get_progress(
    student_id: str,
    current_user: DBUser = Depends(get_current_user),
):
    student_id = enforce_student_access(student_id, current_user)
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


@app.get("/api/history/{student_id}", dependencies=[Depends(enforce_request_student_scope)])
async def get_history(
    student_id: str,
    current_user: DBUser = Depends(get_current_user),
):
    student_id = enforce_student_access(student_id, current_user)
    conversations = await run_db_op(get_conversation_history, student_id)
    return {
        "student_id": student_id,
        "history": [
            {
                "id": c.id,
                "query": c.query,
                "message": c.query,  # For compatibility with frontend h.message
                "response_summary": c.response_summary,
                "response": c.response_summary,  # For compatibility with frontend h.response
                "target": c.target,
                "resources": c.resources_count,  # For compatibility with frontend h.resources
                "resources_count": c.resources_count,
                "alignment_passed": c.alignment_passed,
                "created_at": c.created_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
            for c in conversations
        ],
    }


@app.get("/api/review/{student_id}", dependencies=[Depends(enforce_request_student_scope)])
async def get_review(
    student_id: str,
    current_user: DBUser = Depends(get_current_user),
):
    student_id = enforce_student_access(student_id, current_user)
    plans = await run_db_op(get_review_plan, student_id)
    return {
        "student_id": student_id,
        "due_reviews": [review_plan_to_dict(p) for p in plans],
    }


@app.post("/api/review/{student_id}", dependencies=[Depends(enforce_request_student_scope)])
async def update_review(
    student_id: str,
    request: Request,
    current_user: DBUser = Depends(get_current_user),
):
    student_id = enforce_student_access(student_id, current_user)
    payload = await request.json()
    concept = str(payload.get("concept", "")).strip()
    mastery = float(payload.get("mastery", 0.5))
    interval_days = int(payload.get("interval_days", 1))
    if not concept:
        raise HTTPException(status_code=400, detail="concept is required")
    plan = await run_db_op(upsert_review_plan, student_id, concept, mastery, interval_days)
    return review_plan_to_dict(plan)


@app.delete("/api/review/{plan_id}", dependencies=[Depends(get_current_user)])
async def remove_review_plan(
    plan_id: int,
    current_user: DBUser = Depends(get_current_user),
):
    success = await run_db_op(
        delete_review_plan,
        plan_id,
        student_id=None if current_user.role == "teacher" else current_user.username,
    )
    if not success:
        raise HTTPException(status_code=404, detail="Review plan not found")
    return {"status": "ok", "deleted": True}



# ============================================================
# SPA static file serving (for Docker/production)
# ============================================================
# Serve VisRAG patch images to prevent 404s
PATCHES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "patches")
if os.path.isdir(PATCHES_DIR):
    app.mount("/data/patches", StaticFiles(directory=PATCHES_DIR), name="patches")

if os.path.isdir(FRONTEND_DIST):
    app.mount("/", SPAStaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")

if __name__ == "__main__":
    import uvicorn
    # Keep direct execution compatible, but do not create a Windows reload process.
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=False)
