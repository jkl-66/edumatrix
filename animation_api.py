"""
animation_api.py — 本地动画视频服务
提供知识点 → 本地视频文件的映射和静态文件服务
"""
from pathlib import Path
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
import json
import re

router = APIRouter(prefix="/api/v1/animations", tags=["animations"])

ROOT = Path(__file__).resolve().parent
ANIMATIONS_DIR = ROOT / "data" / "animations"

# 知识点名称 → 文件夹名映射（中文名作为文件夹名）
KNOWLEDGE_POINTS = [
    "池化层", "最大池化", "平均池化", "卷积核", "特征图",
    "反向传播", "前向传播", "链式法则", "梯度下降", "损失函数",
    "逻辑回归", "线性回归", "决策树", "支持向量机",
    "过拟合", "欠拟合", "正则化", "交叉验证",
    "激活函数", "神经网络", "卷积神经网络",
    "Transformer", "注意力机制",
    "机器学习", "监督学习", "模型评估",
]


def _get_knowledge_videos(knowledge_point: str) -> list[dict]:
    """获取某个知识点下的所有本地视频文件"""
    folder = ANIMATIONS_DIR / knowledge_point
    if not folder.exists():
        return []
    videos = []
    for ext in ("*.mp4", "*.webm", "*.mkv"):
        for f in sorted(folder.glob(ext)):
            videos.append({
                "filename": f.name,
                "path": f"{knowledge_point}/{f.name}",
                "size": f.stat().st_size,
                "url": f"/api/v1/animations/video/{knowledge_point}/{f.name}",
            })
    return videos


@router.get("/list")
async def list_animations():
    """列出所有知识点及其本地动画"""
    result = {}
    for kp in KNOWLEDGE_POINTS:
        videos = _get_knowledge_videos(kp)
        if videos:
            result[kp] = videos
    return {"knowledge_points": result, "total": sum(len(v) for v in result.values())}


@router.get("/for/{knowledge_point}")
async def get_animations_for(knowledge_point: str):
    """获取指定知识点的本地动画列表"""
    # 尝试精确匹配
    if knowledge_point in KNOWLEDGE_POINTS:
        videos = _get_knowledge_videos(knowledge_point)
        if videos:
            return {"knowledge_point": knowledge_point, "videos": videos}

    # 模糊匹配
    for kp in KNOWLEDGE_POINTS:
        if knowledge_point in kp or kp in knowledge_point:
            videos = _get_knowledge_videos(kp)
            if videos:
                return {"knowledge_point": kp, "videos": videos}

    # 尝试文件夹名匹配
    folder = ANIMATIONS_DIR / knowledge_point
    if folder.exists():
        videos = _get_knowledge_videos(knowledge_point)
        if videos:
            return {"knowledge_point": knowledge_point, "videos": videos}

    return {"knowledge_point": knowledge_point, "videos": []}


@router.get("/video/{knowledge_point}/{filename:path}")
async def serve_video(knowledge_point: str, filename: str):
    """提供本地视频文件（支持 Range 请求）"""
    file_path = ANIMATIONS_DIR / knowledge_point / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="视频文件不存在")
    return FileResponse(
        file_path,
        media_type="video/mp4" if file_path.suffix == ".mp4" else "video/webm",
        headers={"Accept-Ranges": "bytes"},
    )


@router.get("/search")
async def search_animation(query: str):
    """根据查询文本搜索匹配的知识点动画"""
    matched = []
    for kp in KNOWLEDGE_POINTS:
        if kp in query:
            videos = _get_knowledge_videos(kp)
            if videos:
                matched.append({
                    "knowledge_point": kp,
                    "videos": videos,
                })
    if not matched:
        # 模糊匹配
        for kp in KNOWLEDGE_POINTS:
            if any(char in query for char in kp):
                videos = _get_knowledge_videos(kp)
                if videos:
                    matched.append({
                        "knowledge_point": kp,
                        "videos": videos,
                    })
    return {"matched": matched, "total": sum(len(m["videos"]) for m in matched)}