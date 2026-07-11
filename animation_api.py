"""
animation_api.py — 本地动画视频服务
提供知识点 → 本地视频文件的映射和静态文件服务
"""
from pathlib import Path
from urllib.parse import quote
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from animation_resources import find_animation_dir, load_animation_resource_index

router = APIRouter(prefix="/api/v1/animations", tags=["animations"])

ROOT = Path(__file__).resolve().parent
ANIMATIONS_DIR = ROOT / "data" / "animations"

# 知识点名称 → 文件夹名映射（中文名作为文件夹名）
KNOWLEDGE_POINTS = [
    "池化层", "最大池化", "平均池化", "卷积核", "特征图",
    "反向传播", "链式法则", "梯度下降", "逻辑回归", "线性回归",
    "决策树", "支持向量机", "过拟合", "正则化", "交叉验证",
    "机器学习", "监督学习", "模型评估", "前向传播", "损失函数",
    "欠拟合", "激活函数",
    "Transformer", "注意力机制", "神经网络", "卷积神经网络",
]

def _animations_dir() -> Path | None:
    return find_animation_dir() or (ANIMATIONS_DIR if ANIMATIONS_DIR.exists() else None)


def _get_knowledge_videos(knowledge_point: str) -> list[dict]:
    """获取某个知识点下的所有本地视频文件"""
    base_dir = _animations_dir()
    if base_dir is None:
        return []
    resource_index = load_animation_resource_index(str(base_dir))
    item = resource_index.get(knowledge_point)
    if item:
        return [dict(file) for file in item.get("local_files", []) if file.get("media_type") == "video"]

    folder = base_dir / knowledge_point
    if not folder.exists():
        return []
    videos = []
    for ext in ("*.mp4", "*.webm", "*.mkv", "*.mov"):
        for f in sorted(folder.glob(ext)):
            videos.append({
                "filename": f.name,
                "path": f"{knowledge_point}/{f.name}",
                "size": f.stat().st_size,
                "url": f"/api/v1/animations/video/{quote(knowledge_point)}/{quote(f.name)}",
                "media_type": "video",
            })
    return videos


@router.get("/list")
async def list_animations():
    """列出所有知识点及其本地动画"""
    base_dir = _animations_dir()
    if base_dir is None:
        return {"knowledge_points": {}, "total": 0, "base_dir": ""}

    result = {}
    for kp in sorted(load_animation_resource_index(str(base_dir))):
        videos = _get_knowledge_videos(kp)
        if videos:
            result[kp] = videos
    return {"knowledge_points": result, "total": sum(len(v) for v in result.values()), "base_dir": str(base_dir)}


@router.get("/for/{knowledge_point}")
async def get_animations_for(knowledge_point: str):
    """获取指定知识点的本地动画列表"""
    base_dir = _animations_dir()
    if base_dir is None:
        return {"knowledge_point": knowledge_point, "videos": []}
    resource_index = load_animation_resource_index(str(base_dir))

    # 尝试精确匹配
    if knowledge_point in resource_index:
        videos = _get_knowledge_videos(knowledge_point)
        if videos:
            return {"knowledge_point": knowledge_point, "videos": videos}

    # 模糊匹配
    for kp in sorted(resource_index):
        if knowledge_point in kp or kp in knowledge_point:
            videos = _get_knowledge_videos(kp)
            if videos:
                return {"knowledge_point": kp, "videos": videos}

    # 尝试文件夹名匹配
    folder = base_dir / knowledge_point
    if folder.exists():
        videos = _get_knowledge_videos(knowledge_point)
        if videos:
            return {"knowledge_point": knowledge_point, "videos": videos}

    return {"knowledge_point": knowledge_point, "videos": []}


@router.get("/video/{knowledge_point}/{filename:path}")
async def serve_video(knowledge_point: str, filename: str):
    """提供本地视频文件（支持 Range 请求）"""
    base_dir = _animations_dir()
    if base_dir is None:
        raise HTTPException(status_code=404, detail="动画数据集不存在")
    file_path = (base_dir / knowledge_point / filename).resolve()
    try:
        file_path.relative_to(base_dir.resolve())
    except ValueError:
        raise HTTPException(status_code=400, detail="非法视频路径")
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="视频文件不存在")
    return FileResponse(
        file_path,
        media_type="video/mp4" if file_path.suffix.lower() == ".mp4" else "video/webm",
        headers={"Accept-Ranges": "bytes"},
    )


@router.get("/search")
async def search_animation(query: str):
    """根据查询文本搜索匹配的知识点动画"""
    base_dir = _animations_dir()
    if base_dir is None:
        return {"matched": [], "total": 0}
    resource_index = load_animation_resource_index(str(base_dir))
    matched = []
    for kp in sorted(resource_index):
        if kp in query:
            videos = _get_knowledge_videos(kp)
            if videos:
                matched.append({
                    "knowledge_point": kp,
                    "videos": videos,
                })
    if not matched:
        # 模糊匹配
        for kp in sorted(resource_index):
            if any(char in query for char in kp):
                videos = _get_knowledge_videos(kp)
                if videos:
                    matched.append({
                        "knowledge_point": kp,
                        "videos": videos,
                    })
    return {"matched": matched, "total": sum(len(m["videos"]) for m in matched)}
