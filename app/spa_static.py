"""Static frontend serving with a constrained Vue Router history fallback."""

from __future__ import annotations

from pathlib import PurePosixPath

from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException


class SPAStaticFiles(StaticFiles):
    def __init__(self, *args, **kwargs):
        kwargs["html"] = False
        super().__init__(*args, **kwargs)

    async def _index_response(self, scope):
        response = await super().get_response("index.html", scope)
        response.headers["Cache-Control"] = "no-store"
        return response

    async def get_response(self, path: str, scope):
        request_path = str(scope.get("path", path)).lstrip("/")
        if path in {"", "."}:
            return await self._index_response(scope)
        try:
            response = await super().get_response(path, scope)
        except HTTPException as exc:
            if exc.status_code != 404 or not self._is_frontend_route(request_path):
                raise
            return await self._index_response(scope)
        if response.status_code == 404 and self._is_frontend_route(request_path):
            return await self._index_response(scope)
        if path == "index.html":
            response.headers["Cache-Control"] = "no-store"
        return response

    @staticmethod
    def _is_frontend_route(path: str) -> bool:
        normalized = path.strip("/")
        if normalized.startswith(("api/", "data/")):
            return False
        return not PurePosixPath(normalized).suffix
