from fastapi import APIRouter, Depends, HTTPException, Query

from app.auth import get_current_user
from app.database import DBUser
from app.video_catalog import VideoCatalogError, get_catalog_item, list_catalog


router = APIRouter(prefix="/api/v1/video-catalog", tags=["video-catalog"])


def _error(exc: VideoCatalogError) -> HTTPException:
    code = 404 if exc.code == "video.catalog_not_found" else 503
    return HTTPException(status_code=code, detail={"code": exc.code, "message": str(exc)})


@router.get("")
async def listing(
    query: str = Query(default="", max_length=120),
    topic: str = Query(default="", max_length=80),
    language: str = Query(default="", max_length=32),
    license_status: str = Query(default="", max_length=64),
    current_user: DBUser = Depends(get_current_user),
):
    try:
        return list_catalog(query=query, topic=topic, language=language, license_status=license_status)
    except VideoCatalogError as exc:
        raise _error(exc) from exc


@router.get("/{source_key}")
async def detail(source_key: str, current_user: DBUser = Depends(get_current_user)):
    try:
        return get_catalog_item(source_key)
    except VideoCatalogError as exc:
        raise _error(exc) from exc
