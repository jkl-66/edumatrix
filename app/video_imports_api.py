from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse

from config import CONFIG
from app.auth import get_current_user
from app.authorization import require_course_access
from app.database import DBChapter, DBCourse, DBUser, run_db_op
from app.video_imports import SUBTITLE_MAX_BYTES, VideoImportError, asset_file, get_asset, import_asset, list_assets


router = APIRouter(prefix="/api/v1/video-imports", tags=["video-imports"])


def _http(exc: VideoImportError) -> HTTPException:
    if exc.code.endswith("_unknown") or exc.code in {"video_import.file_missing"}:
        code = status.HTTP_404_NOT_FOUND
    elif "forbidden" in exc.code:
        code = status.HTTP_403_FORBIDDEN
    elif "conflict" in exc.code:
        code = status.HTTP_409_CONFLICT
    elif "too_large" in exc.code:
        code = status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
    else:
        code = status.HTTP_422_UNPROCESSABLE_CONTENT
    return HTTPException(code, detail={"code": exc.code, "message": str(exc)})


def _binding(db, actor: DBUser, course_id: str, chapter_id: str) -> tuple[str | None, str | None]:
    clean_course = course_id.strip() or None
    clean_chapter = chapter_id.strip() or None
    if clean_chapter and not clean_course:
        raise HTTPException(422, detail={"code": "video_import.chapter_without_course", "message": "绑定章节时必须同时选择课程"})
    if clean_course:
        course = db.get(DBCourse, clean_course)
        if course is None:
            raise HTTPException(404, detail={"code": "video_import.course_unknown", "message": "课程不存在"})
        from course_catalog import course_is_selectable
        if not course_is_selectable(db, course):
            raise HTTPException(409, detail={"code": "video_import.course_unavailable", "message": "课程已停止发布或没有可用学习资料"})
        require_course_access(db, actor, course_id=course.id, action="read", visibility=course.visibility)
    if clean_chapter:
        chapter = db.get(DBChapter, clean_chapter)
        if chapter is None or chapter.course_id != clean_course:
            raise HTTPException(422, detail={"code": "video_import.chapter_invalid", "message": "章节不存在或不属于所选课程"})
    return clean_course, clean_chapter


@router.get("")
async def listing(current_user: DBUser = Depends(get_current_user)):
    return await run_db_op(lambda db: list_assets(db, current_user))


@router.get("/{asset_id}")
async def detail(asset_id: str, current_user: DBUser = Depends(get_current_user)):
    def operation(db):
        try:
            return get_asset(db, actor=current_user, asset_id=asset_id)
        except VideoImportError as exc:
            raise _http(exc) from exc
    return await run_db_op(operation)


@router.post("", status_code=201)
async def upload(
    video: UploadFile = File(...), subtitle: UploadFile | None = File(default=None),
    title: str = Form(..., min_length=1, max_length=256), language: str = Form(default="", max_length=32),
    course_id: str = Form(default="", max_length=128), chapter_id: str = Form(default="", max_length=64),
    source_url: str = Form(default="", max_length=2048), source_author: str = Form(default="", max_length=256),
    license_status: str = Form(default="owner_provided", max_length=64),
    license_text: str = Form(default="上传者声明其有权在本地教学演示中使用该文件", max_length=4000),
    asset_id: str = Form(default="", max_length=64), expected_lock_version: int | None = Form(default=None, ge=1),
    current_user: DBUser = Depends(get_current_user),
):
    video_raw = await video.read(CONFIG.max_upload_bytes + 1)
    if len(video_raw) > CONFIG.max_upload_bytes:
        raise HTTPException(413, detail={"code": "video_import.video_too_large", "message": f"视频超过 {CONFIG.max_upload_bytes} bytes"})
    subtitle_raw = await subtitle.read(SUBTITLE_MAX_BYTES + 1) if subtitle else b""
    if len(subtitle_raw) > SUBTITLE_MAX_BYTES:
        raise HTTPException(413, detail={"code": "video_import.subtitle_too_large", "message": f"字幕超过 {SUBTITLE_MAX_BYTES} bytes"})

    def operation(db):
        try:
            bound_course, bound_chapter = _binding(db, current_user, course_id, chapter_id)
            result = import_asset(
                db, actor=current_user, video_raw=video_raw, video_filename=video.filename or "",
                subtitle_raw=subtitle_raw, subtitle_filename=(subtitle.filename or "") if subtitle else "",
                title=title, language=language, course_id=bound_course, chapter_id=bound_chapter,
                source_url=source_url, source_author=source_author, license_status=license_status,
                license_text=license_text, asset_id=asset_id.strip() or None,
                expected_lock_version=expected_lock_version,
            )
            db.commit()
            return result
        except VideoImportError as exc:
            db.rollback()
            raise _http(exc) from exc
    return await run_db_op(operation)


@router.get("/{asset_id}/versions/{version_id}/files/{kind}")
async def download(asset_id: str, version_id: str, kind: str, current_user: DBUser = Depends(get_current_user)):
    def locate(db):
        try:
            path, media_type = asset_file(db, actor=current_user, asset_id=asset_id, version_id=version_id, kind=kind)
            return str(path), media_type
        except VideoImportError as exc:
            raise _http(exc) from exc
    path, media_type = await run_db_op(locate)
    return FileResponse(path, media_type=media_type, filename=Path(path).name)
