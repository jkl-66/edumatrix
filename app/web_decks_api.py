from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import Field

from app.auth import get_current_user
from app.database import DBUser, run_db_op
from app.m2_contracts import StrictModel
from app.web_decks import (
    WebDeckError, capabilities, create_deck, create_version, get_deck, list_decks,
    render_html, render_pdf, render_pptx, restore_version, update_playback,
)


router = APIRouter(prefix="/api/v1/web-decks", tags=["web-decks"])


class SlideInput(StrictModel):
    id: str | None = Field(default=None, max_length=64)
    order: int | None = Field(default=None, ge=0, exclude=True)
    layout: str = Field(default="content", max_length=32)
    title: str = Field(min_length=1, max_length=160)
    subtitle: str = Field(default="", max_length=240)
    body: str = Field(default="", max_length=1200)
    bullets: list[str] = Field(default_factory=list, max_length=8)
    speaker_notes: str = Field(default="", max_length=2000)
    accent: str = Field(default="#355B42", max_length=16)


class DeckInput(StrictModel):
    title: str = Field(min_length=1, max_length=256)
    course_id: str | None = Field(default=None, max_length=128)
    slides: list[SlideInput] = Field(min_length=1, max_length=30)


class VersionInput(StrictModel):
    slides: list[SlideInput] = Field(min_length=1, max_length=30)
    expected_lock_version: int = Field(ge=1)
    change_summary: str = Field(default="", max_length=256)


class RestoreInput(StrictModel):
    version_id: str = Field(min_length=1, max_length=64)
    expected_lock_version: int = Field(ge=1)


class PlaybackInput(StrictModel):
    current_slide: int = Field(ge=0)
    playback_status: str = Field(min_length=1, max_length=16)
    expected_lock_version: int = Field(ge=1)


def _http(exc: WebDeckError) -> HTTPException:
    code = exc.code
    if code.endswith("unknown"):
        http_status = status.HTTP_404_NOT_FOUND
    elif "forbidden" in code:
        http_status = status.HTTP_403_FORBIDDEN
    elif "conflict" in code:
        http_status = status.HTTP_409_CONFLICT
    elif code.endswith("pdf_unavailable"):
        http_status = status.HTTP_503_SERVICE_UNAVAILABLE
    else:
        http_status = status.HTTP_422_UNPROCESSABLE_CONTENT
    return HTTPException(http_status, detail={"code": code, "message": str(exc)})


def _op(fn, *, commit: bool = False):
    def operation(db):
        try:
            result = fn(db)
            if commit:
                db.commit()
            return result
        except WebDeckError as exc:
            db.rollback()
            raise _http(exc) from exc
    return operation


@router.get("/capabilities")
async def deck_capabilities(current_user: DBUser = Depends(get_current_user)):
    return capabilities()


@router.get("")
async def decks(current_user: DBUser = Depends(get_current_user)):
    return await run_db_op(_op(lambda db: list_decks(db, actor=current_user)))


@router.post("", status_code=201)
async def deck_create(payload: DeckInput, current_user: DBUser = Depends(get_current_user)):
    return await run_db_op(_op(lambda db: create_deck(
        db, actor=current_user, title=payload.title, course_id=payload.course_id,
        slides=[item.model_dump() for item in payload.slides],
    ), commit=True))


@router.get("/{deck_id}")
async def deck_detail(deck_id: str, current_user: DBUser = Depends(get_current_user)):
    return await run_db_op(_op(lambda db: get_deck(db, actor=current_user, deck_id=deck_id)))


@router.post("/{deck_id}/versions")
async def version_create(deck_id: str, payload: VersionInput, current_user: DBUser = Depends(get_current_user)):
    return await run_db_op(_op(lambda db: create_version(
        db, actor=current_user, deck_id=deck_id,
        slides=[item.model_dump() for item in payload.slides],
        expected_lock_version=payload.expected_lock_version,
        change_summary=payload.change_summary,
    ), commit=True))


@router.post("/{deck_id}/restore")
async def version_restore(deck_id: str, payload: RestoreInput, current_user: DBUser = Depends(get_current_user)):
    return await run_db_op(_op(lambda db: restore_version(
        db, actor=current_user, deck_id=deck_id, version_id=payload.version_id,
        expected_lock_version=payload.expected_lock_version,
    ), commit=True))


@router.put("/{deck_id}/playback")
async def playback(deck_id: str, payload: PlaybackInput, current_user: DBUser = Depends(get_current_user)):
    return await run_db_op(_op(lambda db: update_playback(
        db, actor=current_user, deck_id=deck_id, current_slide=payload.current_slide,
        playback_status=payload.playback_status, expected_lock_version=payload.expected_lock_version,
    ), commit=True))


@router.get("/{deck_id}/export/{format_name}")
async def export(deck_id: str, format_name: str, version_id: str | None = None, current_user: DBUser = Depends(get_current_user)):
    if format_name not in {"html", "pptx", "pdf"}:
        raise HTTPException(422, detail={"code": "web_deck.export_invalid", "message": "仅支持 HTML、PPTX 和 PDF"})
    render = {"html": render_html, "pptx": render_pptx, "pdf": render_pdf}[format_name]
    content = await run_db_op(_op(lambda db: render(db, actor=current_user, deck_id=deck_id, version_id=version_id)))
    media = {"html": "text/html; charset=utf-8", "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation", "pdf": "application/pdf"}[format_name]
    return Response(content, media_type=media, headers={
        "Content-Disposition": f'attachment; filename="edumatrix-deck-{deck_id}.{format_name}"',
        "Cache-Control": "private, no-store",
    })
