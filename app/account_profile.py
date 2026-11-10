"""Account display details; learning profiles stay in their existing workflow."""
import base64
import binascii
from io import BytesIO

from fastapi import HTTPException
from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import Field

from app.database import DBUser
from app.m2_contracts import StrictModel


class AccountProfileInput(StrictModel):
    display_name: str = Field(min_length=1, max_length=64)
    avatar_url: str = Field(default="", max_length=700_000)


def save_account_profile(db, user_id: str, payload: AccountProfileInput):
    name = payload.display_name.strip()
    if not name:
        raise HTTPException(422, "请填写昵称。")
    avatar = ""
    if payload.avatar_url:
        try:
            header, encoded = payload.avatar_url.split(",", 1)
            if header not in {"data:image/png;base64", "data:image/jpeg;base64", "data:image/webp;base64"}:
                raise ValueError("unsupported image")
            raw = base64.b64decode(encoded, validate=True)
            with Image.open(BytesIO(raw)) as original:
                if original.width * original.height > 4_000_000:
                    raise ValueError("image too large")
                image = ImageOps.exif_transpose(original).convert("RGBA")
                image.thumbnail((256, 256))
                output = BytesIO()
                image.save(output, format="PNG")
            avatar = "data:image/png;base64," + base64.b64encode(output.getvalue()).decode("ascii")
        except (ValueError, binascii.Error, OSError, UnidentifiedImageError, Image.DecompressionBombError):
            raise HTTPException(422, "这张图片暂时无法用作头像，请重新选择 PNG、JPG 或 WebP 图片。") from None
    user = db.query(DBUser).filter_by(public_id=user_id).one()
    user.display_name = name
    user.avatar_url = avatar
    db.commit()
    return {"display_name": name, "avatar_url": avatar}
