from __future__ import annotations

from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
import json

import pytest
from fastapi.testclient import TestClient

import document_parser
import knowledge_api
from app.main import app
from tests.api_test_helpers import auth_headers
from app.database import DBUser, DBKnowledgeDocument, DBSourceDocument, DBStudentProfile, SessionLocal


class _FakeResourceLLM:
    provider = "openai-compatible"
    model = "deepseek-v4-flash"
    thinking_mode = "enabled"
    reasoning_effort = "max"

    def __init__(self, response: str):
        self.response = response

    async def generate(self, _system_prompt: str, _user_prompt: str, *, role: str) -> str:
        return self.response


def _course(client: TestClient, username: str) -> tuple[dict[str, str], str]:
    headers = auth_headers(client, username)
    response = client.post(
        "/api/knowledge/courses",
        headers=headers,
        json={"title": f"B28 {username} 课程", "subject": "语义章节"},
    )
    assert response.status_code == 201, response.text
    return headers, response.json()["course"]["id"]


def _upload(client: TestClient, headers: dict[str, str], course_id: str, filename: str, content: bytes):
    return client.post(
        f"/api/knowledge/upload?course_id={course_id}",
        headers=headers,
        files={"file": (filename, content, "application/octet-stream")},
    )


@pytest.mark.parametrize('role', ['teacher', 'admin'])
def test_course_owner_upload_defaults_to_own_account_for_staff(monkeypatch, tmp_path, role):
    monkeypatch.setattr(knowledge_api, 'UPLOAD_DIR', tmp_path / 'uploads')
    fake = _FakeResourceLLM('{"chapters":[{"title":"数组课堂","char_start":0,"char_end":30,"knowledge_points":[{"code":"KP-A","title":"数组下标"}]}]}')
    monkeypatch.setattr(knowledge_api,'build_swarm_from_headers',lambda _headers:SimpleNamespace(llm=fake))
    monkeypatch.setattr(knowledge_api,'_generate_doc_guide_for_document',lambda **_kwargs:None)
    with TestClient(app) as client:
        username = 'b28_staff_upload_'+role
        headers, course_id = _course(client, username)
        with SessionLocal() as db:
            db.query(DBUser).filter_by(username=username).update({'role':role})
            db.query(DBStudentProfile).filter_by(student_id=username).delete()
            db.commit()
        response = client.post('/api/knowledge/upload-batch?student_id=default&course_id='+course_id,
            headers=headers,files={'files':('array.md','数组[10,20,30]下标从0开始。'.encode(),'text/markdown')})
        assert response.status_code == 200,response.text
        assert response.json()['succeeded'] == 1,response.text
        source_id = response.json()['results'][0]['document']['source_document_id']
        with SessionLocal() as db:
            source = db.get(DBSourceDocument, source_id)
            document = db.get(DBKnowledgeDocument, source.legacy_document_id)
            assert source.course_id == course_id and document.student_id == username
            assert not db.get(DBStudentProfile, username).concept_mastery
        _, other_course_id = _course(client, username+'_other')
        denied = _upload(client, headers, other_course_id, 'array.md', b'not my course')
        assert denied.status_code == 403


def test_batch_accepts_more_than_twenty_files_and_keeps_each_result(monkeypatch):
    received = []

    async def accept_one(**kwargs):
        file = kwargs['file']
        received.append((file.filename, await file.read()))
        return {'source_processing_status': 'ready', 'filename': file.filename}

    monkeypatch.setattr(knowledge_api, 'upload_document', accept_one)
    with TestClient(app) as client:
        headers = auth_headers(client, 'b28_unbounded_batch')
        files = [('files', (f'lesson-{n}.txt', f'lesson {n}'.encode(), 'text/plain')) for n in range(21)]
        response = client.post('/api/knowledge/upload-batch', headers=headers, files=files)
        assert response.status_code == 200, response.text
        payload = response.json()
        assert (payload['total'], payload['succeeded'], payload['failed']) == (21, 21, 0)
        assert [name for name, _ in received] == [f'lesson-{n}.txt' for n in range(21)]
        assert received[-1][1] == b'lesson 20'


def test_non_document_resource_is_exactly_one_chapter_and_binds_model_points(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(knowledge_api, "UPLOAD_DIR", tmp_path / "uploads")
    fake = _FakeResourceLLM(
        '{"chapters":[{"title":"模型输出的错误分段","char_start":0,"char_end":3,"knowledge_points":[{"code":"KP-A","title":"文本检索"}]},{"title":"第二段","char_start":3,"char_end":30,"knowledge_points":[{"code":"KP-B","title":"证据定位"}]}]}'
    )
    monkeypatch.setattr(knowledge_api, "build_swarm_from_headers", lambda _headers: SimpleNamespace(llm=fake))
    monkeypatch.setattr(knowledge_api, "_generate_doc_guide_for_document", lambda **_kwargs: None)

    with TestClient(app) as client:
        headers, course_id = _course(client, "b28_non_document")
        response = _upload(client, headers, course_id, "lesson.txt", "检索正文与证据定位。".encode())

        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["source_processing_status"] == "ready"
        assert payload["knowledge_extraction"]["chapter_strategy"] == "single_resource"
        assert payload["knowledge_extraction"]["knowledge_point_count"] == 2

        outline = client.get(f"/api/v1/courses/{course_id}/outline", headers=headers)
        assert outline.status_code == 200, outline.text
        assert len(outline.json()) == 1
        assert {point["title"] for point in outline.json()[0]["knowledge_points"]} == {"文本检索", "证据定位"}


def test_docx_uses_model_semantic_ranges_instead_of_one_chapter_per_paragraph(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    docx = pytest.importorskip("docx")
    document = docx.Document()
    document.add_heading("第一章", level=1)
    document.add_paragraph("第一章内容。")
    document.add_heading("第二章", level=1)
    document.add_paragraph("第二章内容。")
    raw = BytesIO()
    document.save(raw)

    parsed = document_parser.parse_document(raw.getvalue(), "semantic.docx")
    split = parsed.text.find("第二章")
    assert split > 0
    model_json = (
        '{"chapters":['
        f'{{"title":"第一章","char_start":0,"char_end":{split},"heading_level":1,"knowledge_points":[{{"code":"KP-1","title":"第一章知识"}}]}},'
        f'{{"title":"第二章","char_start":{split},"char_end":{len(parsed.text)},"heading_level":1,"knowledge_points":[{{"code":"KP-2","title":"第二章知识"}}]}}]}}'
    )
    fake = _FakeResourceLLM(model_json)
    monkeypatch.setattr(knowledge_api, "UPLOAD_DIR", tmp_path / "uploads")
    monkeypatch.setattr(knowledge_api, "build_swarm_from_headers", lambda _headers: SimpleNamespace(llm=fake))
    monkeypatch.setattr(knowledge_api, "_generate_doc_guide_for_document", lambda **_kwargs: None)

    with TestClient(app) as client:
        headers, course_id = _course(client, "b28_docx_semantic")
        response = _upload(client, headers, course_id, "semantic.docx", raw.getvalue())
        assert response.status_code == 200, response.text
        assert response.json()["knowledge_extraction"]["chapter_strategy"] == "llm_semantic_sections"

        outline = client.get(f"/api/v1/courses/{course_id}/outline", headers=headers)
        assert outline.status_code == 200, outline.text
        assert [chapter["title"] for chapter in outline.json()] == ["第一章", "第二章"]


def test_invalid_model_output_is_failed_and_retryable_without_fabricated_ready(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(knowledge_api, "UPLOAD_DIR", tmp_path / "uploads")
    fake = _FakeResourceLLM("not-json")
    monkeypatch.setattr(
        knowledge_api,
        "build_swarm_from_headers",
        lambda _headers: SimpleNamespace(llm=fake),
    )
    monkeypatch.setattr(knowledge_api, "_generate_doc_guide_for_document", lambda **_kwargs: None)

    with TestClient(app) as client:
        headers, course_id = _course(client, "b28_invalid_model")
        response = _upload(client, headers, course_id, "invalid.txt", "可解析正文".encode())
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["source_processing_status"] == "failed"
        assert payload["knowledge_extraction"]["status"] == "failed"
        assert payload["knowledge_extraction"]["error"]["retryable"] is True
        source = client.get(f"/api/knowledge/sources/{payload['source_document_id']}", headers=headers)
        assert source.status_code == 200, source.text
        assert source.json()["source_processing_status"] == "failed"

        fake.response = '{"chapters":[{"title":"重试成功章节","char_start":0,"char_end":20,"knowledge_points":[{"code":"KP-RETRY","title":"重试知识点"}]}]}'
        retry = _upload(client, headers, course_id, "invalid.txt", "可解析正文".encode())
        assert retry.status_code == 200, retry.text
        assert retry.json()["source_processing_status"] == "ready"
        assert retry.json()["id"] != payload["id"]


def test_parse_failure_retains_original_file_and_does_not_create_ready_source(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    upload_root = tmp_path / "uploads"
    monkeypatch.setattr(knowledge_api, "UPLOAD_DIR", upload_root)
    monkeypatch.setattr(
        knowledge_api,
        "parse_document",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            document_parser.DocumentParseError("fixture_parse_failed", "fixture parse failed", file_format="docx")
        ),
    )

    with TestClient(app) as client:
        headers, course_id = _course(client, "b28_parse_failure")
        response = _upload(client, headers, course_id, "broken.docx", b"broken")
        assert response.status_code == 422, response.text
        detail = response.json()["detail"]
        assert detail["original_file_retained"] is True
        assert detail["retryable"] is True
        retained = Path(detail["original_file_path"])
        assert retained.is_file()
        assert retained.read_bytes() == b"broken"


def test_resource_shelf_static_contract_keeps_course_controls_out_of_reader() -> None:
    source = Path("frontend/src/components/KnowledgeCourseShelf.vue").read_text(encoding="utf-8")
    reader = Path("frontend/src/views/KnowledgeDocumentReader.vue").read_text(encoding="utf-8")
    assert "resource-shelf-layout" in source
    assert "resource-filters" in source
    assert "selected-resource-detail" in source
    assert "open-course-structure" in source
    assert "getCanonicalCourseSource" in source
    assert "课程正文" in source
    assert "查看课程结构" not in reader
    assert "检索课程正文" not in reader


@pytest.mark.parametrize('file_format', ['md', 'html', 'htm'])
def test_textbook_chapters_have_independent_exact_references_and_reuse_concepts(monkeypatch, tmp_path, file_format):
    from app.database import DBSourceRef, DBKnowledgePoint, DBChapterKnowledgePoint, DBChapter
    from app.source_refs import source_ref_teaching_text
    text = '\n\n'.join(f'第{n}章\n' + f'第{n}章课程内容与解释。' * 40 for n in range(1, 4))
    raw = text.encode() if file_format == 'md' else ('<main>' + ''.join(f'<p>{part}</p>' for part in text.split('\n\n')) + '</main>').encode()
    parsed = document_parser.parse_document(raw, f'chapters.{file_format}')
    starts = [parsed.text.index(f'第{n}章') for n in range(1, 4)]
    ends = [*starts[1:], len(parsed.text)]
    chapters = [{'title': f'第{n+1}章', 'char_start': start, 'char_end': end,
                 'knowledge_points': [{'code': 'KP-A', 'title': '共同概念' if n != 1 else '独立概念'}]}
                for n, (start, end) in enumerate(zip(starts, ends))]
    fake = _FakeResourceLLM(json.dumps({'chapters': chapters}, ensure_ascii=False))
    monkeypatch.setattr(knowledge_api, 'UPLOAD_DIR', tmp_path / 'uploads')
    monkeypatch.setattr(knowledge_api, 'build_swarm_from_headers', lambda _headers: SimpleNamespace(llm=fake))
    monkeypatch.setattr(knowledge_api, '_generate_doc_guide_for_document', lambda **_kwargs: None)
    with TestClient(app) as client:
        headers, course = _course(client, 'b1_chapter_ranges_'+file_format)
        response = _upload(client, headers, course, f'chapters.{file_format}', raw)
        assert response.status_code == 200, response.text
        uploaded = response.json()
        assert uploaded['source_processing_status'] == 'ready', uploaded
        outline = client.get(f'/api/v1/courses/{course}/outline', headers=headers).json()
        assert len(outline) == 3
        with SessionLocal() as db:
            for index, chapter in enumerate(outline):
                ref = db.get(DBSourceRef, chapter['source_ref_id'])
                assert ref.location_kind == 'chapter'
                assert (ref.char_start, ref.char_end) == (starts[index], ends[index])
                assert source_ref_teaching_text(db, ref) == parsed.text[starts[index]:ends[index]]
            nodes = db.query(DBKnowledgePoint).join(DBChapterKnowledgePoint).join(DBChapter).filter(DBChapter.source_document_id == uploaded['source_document_id']).all()
            assert {node.title for node in nodes} == {'共同概念', '独立概念'}
            assert len({node.id for node in nodes}) == 2
        reader = client.get(f'/api/v1/document-reader/documents/{uploaded["source_document_id"]}', headers=headers).json()
        assert [chapter['source_ref_id'] for chapter in reader['chapters']] == [chapter['source_ref_id'] for chapter in outline]
        # Re-uploading a source made before chapter anchors existed must update
        # its projection even when no image needs another reading.
        with SessionLocal() as db:
            old = db.get(DBSourceDocument, uploaded['source_document_id'])
            old.parser_metadata = {key: value for key, value in old.parser_metadata.items() if key != 'chapter_reference_version'}
            db.commit()
        async def unexpected_model_call(*args, **kwargs):
            raise AssertionError('successful analysis segments should be reused')
        monkeypatch.setattr(fake, 'generate', unexpected_model_call)
        refreshed = _upload(client, headers, course, f'chapters.{file_format}', raw).json()
        assert refreshed['source_document_id'] != uploaded['source_document_id']
        assert refreshed['source_processing_status'] == 'ready', refreshed
        assert all(part['reused'] for part in refreshed['source_parser_metadata']['resource_structure']['analysis_segments'])
        new_outline = client.get(f'/api/v1/courses/{course}/outline', headers=headers).json()
        assert len(new_outline) == 3
        assert [chapter['knowledge_points'] for chapter in new_outline] == [chapter['knowledge_points'] for chapter in outline]
