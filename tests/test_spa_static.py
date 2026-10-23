from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.testclient import TestClient

from app.spa_static import SPAStaticFiles


def test_spa_history_routes_fallback_without_hiding_missing_assets_or_api(tmp_path: Path):
    (tmp_path / "index.html").write_text("<main>EduMatrix SPA</main>", encoding="utf-8")
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "app.js").write_text("console.log('ok')", encoding="utf-8")
    app = FastAPI()
    app.mount("/", SPAStaticFiles(directory=tmp_path, html=True), name="frontend")
    client = TestClient(app)

    for route in ("/", "/login", "/learning-path", "/knowledge/course-rag"):
        response = client.get(route)
        assert response.status_code == 200
        assert "EduMatrix SPA" in response.text
    assert client.get("/assets/app.js").status_code == 200
    assert client.get("/assets/missing.js").status_code == 404
    assert client.get("/api/missing").status_code == 404
    assert client.get("/data/missing").status_code == 404
