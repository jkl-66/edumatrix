import hashlib

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database import Base, DBCourse, DBCourseDocument, DBSourceDocument, DBSourceRef
from app.source_refs import source_ref_teaching_text
from app.resource_bundles import _source_snapshots


def test_chapter_context_uses_verified_body_and_preserves_reference_bounds():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    content = "# 教材\n> 上游文件与许可证：" + "metadata " * 50 + "\n## 精选教材内容\nUse fit to train and predict for inference.\n```python\nmodel.fit(X, y)\n```"
    digest = hashlib.sha256(content.encode()).hexdigest()
    with Session(engine) as db:
        db.add(DBCourse(id="course", version="1", title="机器学习", status="published", manifest_version="1"))
        document = DBCourseDocument(id="doc", course_id="course", chapter_order=1, filename="lesson.md", content=content, content_hash=digest)
        source = DBSourceDocument(id="src", course_id="course", legacy_document_id="doc", title="教材", filename="lesson.md", file_format="markdown", content_hash=digest, processed_sha256=digest, parser_version="v1", processing_status="ready")
        ref = DBSourceRef(id="ref", source_document_id="src", parser_version="v1", content_hash=digest, char_start=0, char_end=len(content), location_kind="chapter", quote=content[:300])
        db.add_all([document, source, ref]); db.flush()
        text = source_ref_teaching_text(db, ref)
        assert "model.fit(X, y)" in text and "metadata" not in text
        assert text in content
        assert _source_snapshots(db, course_id="course", source_ref_ids=["ref"], require_available=True)[0]["quote"] == text
        ref.char_start = content.index("Use fit")
        ref.char_end = content.index("\n```python")
        assert source_ref_teaching_text(db, ref) == "Use fit to train and predict for inference."
        ref.char_end = len(content) + 1
        assert source_ref_teaching_text(db, ref) == ""
        ref.char_end = len(content)
        document.content += "Changed version"
        assert source_ref_teaching_text(db, ref) == ""
        document.content = content
        ref.content_hash = "old-version"
        assert source_ref_teaching_text(db, ref) == ""
        ref.content_hash = digest
        ref.location_kind = "selection"
        ref.quote = "Use fit to train"
        assert source_ref_teaching_text(db, ref) == ref.quote
    engine.dispose()


def test_chat_reads_verified_chapter_body_but_keeps_selected_fragments():
    from types import SimpleNamespace
    from app.chat_api import _stream_source_materials
    from app.database import DBUser
    from app.source_refs import chat_source_ref, project_source_ref

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    content = "# 决策树\n来源说明\n## 精选教材内容\n以训练集拟合，验证集选树深度。\n```python\nmodel.fit(X_train, y_train)\n```"
    digest = hashlib.sha256(content.encode()).hexdigest()
    with Session(engine) as db:
        actor = DBUser(public_id="chat-owner", username="chat-owner", hashed_password="test", role="student")
        db.add(actor)
        db.add(DBCourse(id="chat-course", version="1", title="机器学习", status="published",
                        manifest_version="1", owner_public_id=actor.public_id))
        document = DBCourseDocument(id="chat-doc", course_id="chat-course", chapter_order=1,
                                   filename="lesson.md", content=content, content_hash=digest)
        source = DBSourceDocument(id="chat-source", course_id="chat-course", legacy_document_id="chat-doc",
                                  title="教材", filename="lesson.md", file_format="markdown", content_hash=digest,
                                  processed_sha256=digest, parser_version="v1", processing_status="ready")
        ref = DBSourceRef(id="chat-ref", source_document_id="chat-source", parser_version="v1",
                         content_hash=digest, char_start=0, char_end=len(content), location_kind="chapter",
                         quote="# 决策树\n来源说明")
        db.add_all([document, source, ref]); db.flush()
        conversation = SimpleNamespace(course_id="chat-course")
        frozen = chat_source_ref(project_source_ref(db, ref.id, actor=actor))
        def read(snapshot):
            return _stream_source_materials(db, actor, conversation, [snapshot])[0]
        material = read(frozen)
        assert material["available"]
        assert "model.fit(X_train, y_train)" in material["quote"]
        assert "来源说明" not in material["quote"]
        assert frozen["quote"] == ref.quote  # Keep history/citation projection unchanged.
        selection = {**frozen, "charStart": content.index("以训练集"),
                     "charEnd": content.index("。") + 1, "quote": "以训练集拟合，验证集选树深度。"}
        assert read(selection)["quote"] == selection["quote"]
        document.content += "变更后的教材"
        assert not read(frozen)["available"]
        document.content = content
        source.processed_sha256 = "new-version"
        assert not read(frozen)["available"]
    engine.dispose()


def test_chat_named_topic_focus_keeps_explicit_sources_multicourse_and_changes(monkeypatch):
    from types import SimpleNamespace
    import app.chat_api as chat
    import app.canonical_retrieval as retrieval

    def source(name, title, course="ml", available=True):
        return {"source_ref_id": name, "title": title, "course_id": course, "available": available,
                "reason_code": "source_document_changed" if not available else ""}
    catalogs={"ml": [source("numpy", "NumPy 数组"), source("tree", "决策树分类"),
                     source("regression", "线性回归"), source("changed", "已更新材料", available=False)],
              "ai": [source("agent", "Agent 工具使用", "ai")]}
    monkeypatch.setattr(retrieval, "list_canonical_source_refs", lambda _db, *, course_id, **kwargs: catalogs[course_id])
    requests=[]
    def ranked(_db, *, course_id, query, chapter_ids=None, **kwargs):
        requests.append((course_id, chapter_ids))
        indexes = [0] if course_id == 'ai' else [1, 2] if '比较' in query else [0]
        return {'low_confidence': False, 'items': [{'source_ref': catalogs[course_id][i],
                'evidence': SimpleNamespace(content='actual matched passage', metadata={'char_start': 10, 'char_end': 32})}
                for i in indexes]}
    monkeypatch.setattr(retrieval, 'retrieve_canonical_sources', ranked)
    monkeypatch.setattr(chat, "chat_source_ref", lambda projection: {"sourceRefId":projection["source_ref_id"], **projection})
    monkeypatch.setattr(chat, "project_source_ref", lambda *args, **kwargs: catalogs["ml"][1])
    conversation=SimpleNamespace(course_id="ml")
    db=SimpleNamespace(get=lambda *_: None)
    def selected(question, contexts=None):
        return [s["sourceRefId"] for s in chat._context_source_refs(db,None,conversation,
            contexts or [{"courseId":"ml"}],question=question)]
    assert selected("NumPy 数组乘以2") == ["numpy","changed"]
    assert selected("比较决策树和逻辑回归") == ["tree","regression","changed"]
    assert selected("概括课程主要内容") == ["numpy","tree","regression","changed"]
    assert selected("NumPy数组",[{"courseId":"ml"},{"courseId":"ai"}]) == ["numpy","changed","agent"]
    assert selected("NumPy数组",[{"sourceRef":{"id":"tree","courseId":"ml"}}]) == ["tree"]
    assert selected("NumPy数组",[{"courseId":"ml","chapterId":"chosen"}]) == ["numpy","changed"]
    assert requests[-1] == ('ml', ['chosen'])
    frozen=chat._context_source_refs(None,None,conversation,[{'courseId':'ml'}],question='NumPy数组')
    assert frozen[0]['quote']=='actual matched passage' and frozen[0]['char_start']==10
    monkeypatch.setattr(retrieval, 'retrieve_canonical_sources', lambda *args, **kwargs: {'low_confidence':True,'items':[]})
    assert selected('无关问题')==['changed']
