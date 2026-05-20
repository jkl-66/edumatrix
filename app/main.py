import sys
import os
from dataclasses import asdict
from typing import Any
from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

# 允许 app 导入 root 目录下的模块
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent_swarm import EduMatrixSwarm
from models import DIMENSION_LABELS, StudentProfile
from app.database import init_db, get_db, DBStudentProfile
from app.crud import load_student_profile, save_student_profile, record_alignment_log

# 初始化 SQLite 数据库表
init_db()

app = FastAPI(
    title="EduMatrix 智教矩阵 API",
    description="基于 FastAPI + SQLite + Swarm 智能体的高并发个性化教育系统后端",
    version="1.0.0"
)

# 限制级跨域配置（防 * 安全漏洞，锁定前端Vue开发域）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:8000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

swarm = EduMatrixSwarm()

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

def _seed_demo_class(db: Session) -> None:
    """初始化数据库种子数据（演示专用学生）"""
    samples = {
        "stu-ml-001": "我是计算机专业，期末要考机器学习。逻辑回归和混淆矩阵总混，accuracy 很高但 recall 低我不知道怎么判断，希望用图和例子一步步讲。",
        "stu-ml-002": "我线性回归能看懂公式，但一到项目就不会做数据预处理，只会照着答案改代码，想要代码实操 and 提示。",
        "stu-ml-003": "我过拟合和正则化分不清，训练集分数高就以为模型好，题干长的时候会漏掉验证集条件。",
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

@app.get("/", response_class=HTMLResponse)
async def read_index():
    """提供交互式 Web 演示页面"""
    from web_demo import INDEX_HTML
    return INDEX_HTML

@app.get("/api/teacher")
async def get_teacher_dashboard(db: Session = Depends(get_db)):
    """获取教师端诊断看板（直接从本地 SQLite 数据库中读取，实现实时持久化）"""
    _seed_demo_class(db)
    db_profiles = db.query(DBStudentProfile).all()
    profiles = [load_student_profile(db, db_prof.student_id) for db_prof in db_profiles]
    
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
async def process_student_message(request: Request, db: Session = Depends(get_db)):
    """核心画像提取与多智能体资源生成接口（SQLite 与 Swarm 双轨并网）"""
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")
        
    message = str(payload.get("message") or "").strip()
    student_id = str(payload.get("student_id") or "demo-student").strip()
    
    if not message:
        raise HTTPException(status_code=400, detail="message is required")

    # 1. 物理层：从本地 SQLite 数据库中加载/初始化学生画像
    profile = load_student_profile(db, student_id)
    
    # 2. 内存同步：注入 Swarm 运行上下文
    swarm.profile_store[student_id] = profile
    
    # 3. 编排层：运行 1+3+5 智能体矩阵进行画像抽取与资源交付
    package = await swarm.async_process(message, student_id=student_id)
    
    # 4. 持久化层：将 Swarm 更新后的最新画像存回 SQLite，确保事务完整性
    save_student_profile(db, package.profile)
    
    # 5. 审计层：保存流形对齐校验记录
    record_alignment_log(db, student_id, package.alignment, package.target)
    
    return _package_response(package)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
