from io import BytesIO
from dataclasses import replace

import pytest
from PIL import Image
from pptx import Presentation
from pptx.util import Inches

import document_parser as parser
from models import Evidence, EvidenceModality


def slide_bytes(images=1):
    image = BytesIO()
    Image.new("RGB", (300, 200), "white").save(image, format="PNG")
    deck = Presentation()
    first = deck.slides.add_slide(deck.slide_layouts[6])
    first.shapes.add_textbox(0, 0, Inches(8), Inches(1)).text = "训练误差与验证误差"
    first.shapes.add_picture(BytesIO(image.getvalue()), 0, Inches(1), width=Inches(5))
    if images == 2:
        first.shapes.add_picture(BytesIO(image.getvalue()), Inches(5), Inches(1), width=Inches(5))
    second = deck.slides.add_slide(deck.slide_layouts[6])
    second.shapes.add_textbox(0, 0, Inches(8), Inches(1)).text = "下一页：模型选择"
    output = BytesIO()
    deck.save(output)
    return output.getvalue()


def image_evidence(evidence_id="VIS_test", **metadata):
    return Evidence(id=evidence_id, title="合成表格", content="| 轮次 | 验证误差 |\n| 2 | 0.30 |",
                    modality=EvidenceModality.IMAGE, source="test.pptx", tags=(), anchors=(),
                    metadata=metadata)


def test_native_pptx_does_not_treat_pixels_or_colours_as_course_content():
    parsed = parser.parse_document(slide_bytes(), "lesson.pptx")
    assert "主色调" not in parsed.text
    assert "RGB" not in parsed.text
    assert "图片描述" not in parsed.text
    assert parsed.metadata["image_count"] == 1
    assert "pptx_image_content_pending" in parsed.warnings
    assert "训练误差与验证误差" in parsed.text


def test_visual_reading_is_placed_beside_its_slide_with_exact_offsets():
    original = parser.parse_document(slide_bytes(), "lesson.pptx")
    parsed = parser.merge_document_visual_reading(original, [image_evidence(slide_number=1)])
    assert parsed.text.index("训练误差") < parsed.text.index("0.30") < parsed.text.index("下一页")
    location = next(item for item in parsed.locations if item.kind == "visual_region")
    assert location.slide_number == 1
    assert "0.30" in parsed.text[location.char_start:location.char_end]
    assert parsed.metadata["visual_reading"]["status"] == "ready"
    assert not parsed.warnings
    assert parsed.source_sha256 == original.source_sha256
    assert parsed.processed_sha256 != original.processed_sha256


def test_unread_image_keeps_native_content_and_explicit_incomplete_state():
    original = parser.parse_document(slide_bytes(), "lesson.pptx")
    parsed = parser.merge_document_visual_reading(original, [])
    assert parsed.text == original.text
    assert parsed.locations == original.locations
    assert parsed.metadata["visual_reading"]["status"] == "unavailable"
    assert "document_image_content_incomplete" in parsed.warnings


@pytest.mark.parametrize("answer", [None, "表中第2轮验证误差为0.30"])
def test_pdf_model_failure_never_produces_fake_semantic_evidence(tmp_path, monkeypatch, answer):
    image = BytesIO()
    Image.new("RGB", (100, 100), "white").save(image, format="PNG")
    monkeypatch.setattr(parser, "_check_vision_llm", lambda: True)
    monkeypatch.setattr(parser, "_render_pdf_to_images", lambda *args, **kwargs: [
        {"page": 2, "image_bytes": image.getvalue(), "width": 100, "height": 100},
    ])
    monkeypatch.setattr(parser, "_describe_image_with_multimodal_llm", lambda *args, **kwargs: answer)
    results = parser.parse_pdf_visually(b"synthetic-pdf", "lesson.pdf", owner_public_id="test-owner",
                                       model_call_context={"asset_dir": str(tmp_path)})
    if answer is None:
        assert results == []
    else:
        assert len(results) == 1
        assert results[0].content == answer
        assert results[0].metadata["page"] == 2


def test_pdf_visual_reading_uses_same_page_native_text_and_configured_timeout(monkeypatch):
    import config, requests
    import app.m5_legacy_calls as audit
    calls=[]
    monkeypatch.setattr(config, 'CONFIG', replace(config.CONFIG, multimodal_llm_endpoint='https://test.invalid/vision',
        multimodal_llm_api_key='synthetic-test', multimodal_llm_model='vision-test', llm_timeout=140))
    monkeypatch.setattr(parser, '_check_vision_llm', lambda: True)
    def audited(backend, **kwargs):
        assert kwargs['input_summary']['native_text_chars'] == len('K 0.02\n0.4 0.6628')
        assert kwargs['input_summary']['image_payload_included'] is False
        return backend.generate(kwargs['system_prompt'], kwargs['user_prompt'], role=kwargs['role'])
    monkeypatch.setattr(audit, 'audited_legacy_sync_text_call', audited)
    def post(url, **kwargs):
        calls.append(kwargs)
        class Response:
            def raise_for_status(self): pass
            def json(self): return {'choices':[{'finish_reason':'stop','message':{'content':'k=0.42 对应 0.6628；遮挡单元格按同页原生文字核对。'}}]}
        return Response()
    monkeypatch.setattr(requests, 'post', post)
    result=parser._describe_image_with_multimodal_llm('dGVzdA==',16,'table.pdf',owner_public_id='test',native_text='K 0.02\n0.4 0.6628')
    assert '0.6628' in result
    prompt=calls[0]['json']['messages'][0]['content'][0]['text']
    assert '<same_page_native_text>\nK 0.02\n0.4 0.6628' in prompt
    assert calls[0]['timeout']==(10,140)


def test_pdf_visual_retry_only_reads_missing_page_and_passes_its_text(tmp_path,monkeypatch):
    import pymupdf
    document=pymupdf.open()
    for label in ['First page', 'Table row 0.4 0.6628']:
        page=document.new_page();page.insert_text((72,72),label)
    raw=document.tobytes();document.close()
    calls=[]
    monkeypatch.setattr(parser,'_check_vision_llm',lambda:True)
    def describe(image,page,filename,**kwargs):
        calls.append((page,kwargs['native_text']))
        return 'Table row 0.4 0.6628'
    monkeypatch.setattr(parser,'_describe_image_with_multimodal_llm',describe)
    first=image_evidence(page=1)
    results=parser.parse_pdf_visually(raw,'table.pdf',owner_public_id='test',page_numbers=[1,2],existing=[first],
                                    model_call_context={'asset_dir':str(tmp_path)})
    assert calls==[(2,'Table row 0.4 0.6628\n')]
    assert results[0]==first and results[1].metadata['native_text_used'] is True


def test_upload_uses_image_reading_before_structure_extraction_and_canonical_storage(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.database import SessionLocal, DBSourceDocument, DBSourceRef, DBKnowledgeDocument
    from tests.api_test_helpers import auth_headers
    import knowledge_api

    received = []

    async def structure(parsed, **kwargs):
        received.append(parsed.text)
        return {"status": "ready", "chapters": [{"title": "验证误差", "char_start": 0,
                "char_end": len(parsed.text), "knowledge_points": []}], "knowledge_point_count": 0}

    async def no_guide(**kwargs):
        return None

    monkeypatch.setattr(knowledge_api, "UPLOAD_DIR", tmp_path / "uploads")
    monkeypatch.setattr(knowledge_api, "parse_pptx_visually", lambda *args, **kwargs: [
        image_evidence(slide_number=1), image_evidence("VIS_second", slide_number=1),
    ])
    monkeypatch.setattr(knowledge_api, "_extract_resource_structure", structure)
    monkeypatch.setattr(knowledge_api, "build_swarm_from_headers", lambda *args: type("Swarm", (), {"llm": object()})())
    monkeypatch.setattr(knowledge_api, "_generate_doc_guide_for_document", no_guide)
    monkeypatch.setattr(knowledge_api, "build_graph_after_upload", lambda *args, **kwargs: None)
    monkeypatch.setattr(knowledge_api.hybrid_rag, "ingest_user_documents", lambda *args, **kwargs: None)
    with TestClient(app) as client:
        headers = auth_headers(client, "visual_course_upload_test")
        response = client.post("/api/knowledge/upload", headers=headers,
                               files={"file": ("lesson.pptx", slide_bytes(images=2), "application/vnd.openxmlformats-officedocument.presentationml.presentation")})
        assert response.status_code == 200, response.text
        assert received and "0.30" in received[0]
        payload = response.json()
        assert payload["source_parser_metadata"]["visual_reading"]["status"] == "ready"
        with SessionLocal() as db:
            source = db.get(DBSourceDocument, payload["source_document_id"])
            document = db.get(DBKnowledgeDocument, source.legacy_document_id)
            assert "0.30" in document.content
            refs = db.query(DBSourceRef).filter_by(source_document_id=source.id).all()
            assert len(refs) == 4
            assert len({ref.parser_version for ref in refs}) == 4
            assert any(ref.location_metadata.get("slide_number") == 1 and "0.30" in document.content[ref.char_start:ref.char_end] for ref in refs)


@pytest.mark.parametrize('intermediate_structure_failure', [False, True])
def test_retry_retains_old_citations_and_only_browses_latest_complete_reading(tmp_path, monkeypatch, intermediate_structure_failure):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.database import SessionLocal, DBSourceDocument, DBSourceRef, DBChapter, DBChapterKnowledgePoint
    from app.canonical_retrieval import list_canonical_source_refs
    from app.m1_repository import M1Repository
    from tests.api_test_helpers import auth_headers
    import knowledge_api

    calls = []
    outcomes = [[image_evidence(slide_number=1, image_index=2)], [], [image_evidence('VIS_new', slide_number=1, image_index=3)]]
    if intermediate_structure_failure:
        outcomes.append([])
    structure_calls = []

    def vision(*args, **kwargs):
        previous = kwargs.get('existing') or []
        calls.append(len(previous))
        return previous + outcomes.pop(0)

    async def structure(parsed, **kwargs):
        structure_calls.append(parsed)
        if intermediate_structure_failure and len(structure_calls) == 2:
            return knowledge_api._pending_structure(parsed, model_meta={}, error_code='test_model_failure', message='本次章节未整理完成')
        return {'status': 'ready', 'chapters': [{'title': '验证误差', 'char_start': 0,
                'char_end': len(parsed.text), 'knowledge_points': [{'title': '验证误差'}]}], 'knowledge_point_count': 1}

    async def no_guide(**kwargs):
        return None

    monkeypatch.setattr(knowledge_api, 'PROJECT_ROOT', tmp_path)
    monkeypatch.setattr(knowledge_api, 'UPLOAD_DIR', tmp_path / 'uploads')
    monkeypatch.setattr(knowledge_api, 'parse_pptx_visually', vision)
    monkeypatch.setattr(knowledge_api, '_extract_resource_structure', structure)
    monkeypatch.setattr(knowledge_api, 'build_swarm_from_headers', lambda *args: type('Swarm', (), {'llm': object()})())
    monkeypatch.setattr(knowledge_api, '_generate_doc_guide_for_document', no_guide)
    monkeypatch.setattr(knowledge_api, 'build_graph_after_upload', lambda *args, **kwargs: None)
    monkeypatch.setattr(knowledge_api.hybrid_rag, 'ingest_user_documents', lambda *args, **kwargs: None)
    with TestClient(app) as client:
        headers = auth_headers(client, f'visual_retry_owner_{intermediate_structure_failure}')
        other = auth_headers(client, f'visual_retry_outsider_{intermediate_structure_failure}')
        response = client.post('/api/knowledge/upload', headers=headers,
                               files={'file': ('lesson.pptx', slide_bytes(images=2))})
        assert response.status_code == 200, response.text
        first = response.json()
        assert first['source_parser_metadata']['visual_reading']['status'] == 'partial'
        first_id = first['source_document_id']
        retry_url = f'/api/knowledge/sources/{first_id}/retry-reading'
        assert client.post(retry_url, headers=other).status_code == 403
        unchanged = client.post(retry_url, headers=headers)
        assert unchanged.status_code == 200, unchanged.text
        assert unchanged.json()['visual_retry'] == 'unchanged'
        response = client.post(retry_url, headers=headers)
        assert response.status_code == 200, response.text
        if intermediate_structure_failure:
            failed = response.json()
            assert failed['source_processing_status'] == 'failed'
            assert failed['source_parser_metadata']['visual_reading']['status'] == 'ready'
            response = client.post(f"/api/knowledge/sources/{failed['source_document_id']}/retry-reading", headers=headers)
            assert response.status_code == 200, response.text
        complete = response.json()
        assert complete['source_document_id'] != first_id
        assert complete['source_parser_metadata']['visual_reading']['status'] == 'ready'
        assert calls == ([0, 1, 1, 2] if intermediate_structure_failure else [0, 1, 1])
        assert client.post(retry_url, headers=headers).json()['duplicate'] is True
        with SessionLocal() as db:
            old = db.get(DBSourceDocument, first_id)
            assert old.processed_sha256 == first['processed_sha256']
            assert old.parser_metadata['replaced_by_source_id'] == complete['source_document_id']
            assert db.query(DBSourceRef).filter_by(source_document_id=first_id).count() == 3
            old_points = {row.knowledge_point_id for row in db.query(DBChapterKnowledgePoint).join(DBChapter).filter(DBChapter.source_document_id == first_id).all()}
            new_points = {row.knowledge_point_id for row in db.query(DBChapterKnowledgePoint).join(DBChapter).filter(DBChapter.source_document_id == complete['source_document_id']).all()}
            assert len(old_points) == 1 and new_points == old_points
            outline = M1Repository(db).course_outline(first['course_id'])
            assert {chapter['source_document_id'] for chapter in outline} == {complete['source_document_id']}
            refs = list_canonical_source_refs(db, course_id=first['course_id'])
            assert refs and all(ref['source_document_id'] == complete['source_document_id'] for ref in refs)


def test_grouped_pptx_images_and_text_are_not_silently_skipped():
    deck = Presentation(BytesIO(slide_bytes()))
    slide = deck.slides[0]
    group = slide.shapes.add_group_shape()
    group.shapes.add_textbox(0, 0, Inches(2), Inches(1)).text = '组内教学文字'
    img = BytesIO()
    Image.new('RGB', (40, 40), 'white').save(img, 'PNG')
    group.shapes.add_picture(BytesIO(img.getvalue()), 0, 0, Inches(1))
    out = BytesIO()
    deck.save(out)
    parsed = parser.parse_document(out.getvalue(), 'group.pptx')
    assert '组内教学文字' in parsed.text
    assert parsed.metadata['image_count'] == 2


@pytest.mark.parametrize('sensitive_count', [0, 1])
def test_pdf_image_reading_selects_needed_pages_and_respects_ocr_privacy(tmp_path, monkeypatch, sensitive_count):
    import asyncio
    import knowledge_api

    text, locations = parser._compose_located_blocks([
        ('--- Page 1 ---\nThis page has enough readable course text about model validation.',
         {'kind': 'page', 'index': 1, 'label': '第1页', 'page_number': 1}),
        ('--- Page 2 ---', {'kind': 'page', 'index': 2, 'label': '第2页', 'page_number': 2,
                             'metadata': {'image_count': 1}}),
        ('第二页的本地识别文字', {'kind': 'ocr_region', 'index': 1, 'label': '第2页文字', 'page_number': 2}),
    ])
    original = parser.ParsedDocument('lesson.pdf', 'pdf', 'test-pdf', text, 'hash', 'processed', locations,
                                    {'page_count': 2, 'ocr': {'status': 'ready', 'sensitive_region_count': sensitive_count}})
    calls = []

    def vision(*args, **kwargs):
        calls.append(kwargs['page_numbers'])
        return [image_evidence(page=2)]

    monkeypatch.setattr(knowledge_api, 'parse_pdf_visually', vision)
    parsed, evidence = asyncio.run(knowledge_api._read_course_images(original, b'pdf', owner_public_id='test', course_id='test', asset_dir=tmp_path))
    if sensitive_count:
        assert calls == [] and evidence == []
        assert parsed.metadata['visual_reading']['status'] == 'unavailable'
    else:
        assert calls == [[2]]
        assert parsed.metadata['visual_reading']['status'] == 'ready'
        assert parsed.text.index('course text') < parsed.text.index('0.30')
        assert '本地识别文字' not in parsed.text
        for loc in parsed.locations:
            assert parsed.text[loc.char_start:loc.char_end].strip()


def test_reader_finds_scan_assets_next_to_retained_upload(tmp_path, monkeypatch):
    import hashlib
    from types import SimpleNamespace
    import app.document_selection as reader

    original = tmp_path / 'uploads/learner/doc.pdf'
    original.parent.mkdir(parents=True)
    original.write_bytes(b'retained original')
    asset = original.parent / 'doc/ocr/page-0001-redacted.png'
    asset.parent.mkdir(parents=True)
    asset.write_bytes(b'checked page image')
    monkeypatch.setattr(reader, 'PROJECT_ROOT', tmp_path)
    source = SimpleNamespace(source_path=str(original), legacy_document_id='doc')
    page = {'asset_name': asset.name, 'redacted_image_sha256': hashlib.sha256(asset.read_bytes()).hexdigest()}
    assert reader._page_asset_path(source, page) == asset.resolve()


def test_structure_anchors_resolve_whitespace_without_asking_model_to_count_chars():
    import knowledge_api
    text = '资料标题\n\n梯度   更新\n从当前参数出发。\n\n学习率\n应为  正数。'
    parsed = parser.ParsedDocument('lesson.pdf', 'pdf', 'test', text, 'source', 'body', ())
    result = knowledge_api._normalize_structure_payload({'chapters': [{
        'title': '更新参数', 'start_text': '梯度 更新', 'end_text': '应为 正数。', 'knowledge_points': [],
    }]}, parsed=parsed, model_meta={})
    chapter = result['chapters'][0]
    assert chapter['char_start'] == text.index('梯度')
    assert chapter['char_end'] == len(text)
    with pytest.raises(ValueError, match='未在原文中找到'):
        knowledge_api._normalize_structure_payload({'chapters': [{'title': '编造章节', 'start_text': '不存在的原文'}]}, parsed=parsed, model_meta={})


def test_structure_block_labels_preserve_math_and_reject_missing_or_reversed_positions():
    import knowledge_api
    text = '导数表\n\n\\[\\frac{d}{dx}\\ln x=\\frac{1}{x}\\]\n\n梯度更新\n\n保留边界与符号。'
    parsed = parser.ParsedDocument('lesson.pdf', 'pdf', 'test', text, 'source', 'body', ())
    blocks = knowledge_api._structure_source_blocks(text)
    for block in blocks:
        assert text[block['char_start']:block['char_end']] == block['text']
    result = knowledge_api._normalize_structure_payload({'chapters': [
        {'title': '导数', 'start_block': 'b00001', 'end_block': 'b00002'},
        {'title': '更新', 'start_block': 'b00003', 'end_block': 'b00004'},
    ]}, parsed=parsed, model_meta={}, source_blocks=blocks)
    first, last = result['chapters']
    assert text[first['char_start']:first['char_end']].endswith('\\frac{1}{x}\\]')
    assert last['char_start'] == text.index('梯度更新') and last['char_end'] == len(text)
    for invalid in [('b00001', 'b9999'), ('b00004', 'b00001')]:
        with pytest.raises(ValueError, match='段落未找到'):
            knowledge_api._normalize_structure_payload({'chapters': [{'title': '错误位置', 'start_block': invalid[0], 'end_block': invalid[1]}]}, parsed=parsed, model_meta={}, source_blocks=blocks)


def native_diagram_bytes():
    from pptx.enum.shapes import MSO_SHAPE
    deck = Presentation()
    slide = deck.slides.add_slide(deck.slide_layouts[6])
    slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(1), Inches(1), Inches(2), Inches(1)).text = '训练集拟合模型'
    slide.shapes.add_shape(MSO_SHAPE.RIGHT_ARROW, Inches(3), Inches(1.2), Inches(1), Inches(.6))
    slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(4), Inches(1), Inches(2), Inches(1)).text = '验证集选超参数'
    slide.notes_slide.notes_text_frame.text = '测试集只用于最终评估。'
    out = BytesIO()
    deck.save(out)
    return out.getvalue()


def test_native_diagram_requires_whole_slide_reading_even_without_bitmap_images():
    parsed = parser.parse_document(native_diagram_bytes(), 'native.pptx')
    assert parsed.metadata['image_count'] == 0
    assert parsed.metadata['visual_slide_numbers'] == [1]
    assert parsed.metadata['visual_expected_units'] == 1
    incomplete = parser.merge_document_visual_reading(parsed, [])
    assert incomplete.metadata['visual_reading']['status'] == 'unavailable'
    assert '训练集拟合模型' in incomplete.text


def test_whole_slide_reading_reuses_preview_engine_keeps_notes_and_cached_success(tmp_path, monkeypatch):
    import app.pptx_rendering as rendering
    from app.media_ocr import RapidOCROfflineAdapter
    raw = native_diagram_bytes()
    preview = tmp_path / 'slide.png'
    Image.new('RGB', (200, 100), 'white').save(preview)
    rendered = []
    calls = []
    monkeypatch.setattr(rendering, 'render_pptx_bytes', lambda data: rendered.append(data) or [preview])
    monkeypatch.setattr(parser, '_check_vision_llm', lambda: True)
    monkeypatch.setattr(RapidOCROfflineAdapter, 'runtime', lambda self: (True, None))
    monkeypatch.setattr(RapidOCROfflineAdapter, 'recognize', lambda *args, **kwargs: [])
    monkeypatch.setattr(parser, '_describe_image_with_multimodal_llm', lambda *args, **kwargs: calls.append(args[1]) or '训练集拟合模型 → 验证集选超参数')
    evidence = parser.parse_pptx_visually(raw, 'native.pptx', owner_public_id='test')
    assert len(evidence) == 1 and evidence[0].metadata['whole_slide'] is True
    assert parser.parse_pptx_visually(raw, 'native.pptx', owner_public_id='test', existing=evidence) == evidence
    assert rendered == [raw] and calls == [1]
    result = parser.merge_document_visual_reading(parser.parse_document(raw, 'native.pptx'), evidence)
    assert result.metadata['visual_reading']['status'] == 'ready'
    assert result.text.count('训练集拟合模型') == 1
    assert '测试集只用于最终评估。' in result.text
    assert result.locations[-1].metadata['whole_slide'] is True


def test_full_course_structure_reads_beyond_old_cutoff_and_reuses_successful_parts(monkeypatch):
    import asyncio, json
    import knowledge_api
    text = '\n\n'.join(f'第{n}段。' + ('课程正文。' * 500) for n in range(30)) + '\n\n最后一章：模型部署与维护。'
    parsed = parser.ParsedDocument('long.md', 'md', 'test', text, 'source', 'full-text-hash', ())
    batches = knowledge_api._structure_batches(knowledge_api._structure_source_blocks(text))
    assert len(batches) > 2
    calls = []
    interrupt = {2}

    async def audited(llm, **kwargs):
        value = json.loads(kwargs['user_prompt'])
        calls.append(value['part'])
        if value['part'] in interrupt:
            raise RuntimeError('synthetic interrupted middle segment')
        blocks = value['blocks']
        return json.dumps({'chapters': [{'title': f"段{value['part']}", 'start_block': blocks[0]['id'], 'end_block': blocks[-1]['id'], 'knowledge_points': []}]})

    model = type('Model', (), {'provider': 'openai', 'model': 'deepseek-v4-flash', 'thinking_mode': 'enabled', 'reasoning_effort': 'max'})()
    monkeypatch.setattr(knowledge_api, 'audited_legacy_text_call', audited)
    failed = asyncio.run(knowledge_api._extract_resource_structure(parsed, llm=model, owner_public_id='test', course_id='test'))
    assert failed['status'] == 'failed' and failed['completed_parts'] == len(batches)-1
    interrupt.clear()
    calls.clear()
    done = asyncio.run(knowledge_api._extract_resource_structure(parsed, llm=model, owner_public_id='test', course_id='test', previous_structure=failed))
    assert calls == [2]
    assert done['status'] == 'ready' and done['completed_parts'] == len(batches)
    assert done['chapters'][-1]['char_end'] == len(text)
    assert len(done['chapters']) == len(batches)
    assert done['chapters'][0]['char_start'] == 0
    assert done['analysis_segments'][-1]['char_end'] > 32000
    assert len(knowledge_api._normalize_knowledge_points([{'title': f'知识点{i}'} for i in range(120)])) == 120


def test_unbounded_page_setting_accepts_long_pdf_without_silently_truncating(monkeypatch):
    import fitz
    import config
    from dataclasses import replace
    monkeypatch.setattr(config, 'CONFIG', replace(config.CONFIG, max_document_pages=0))
    document = fitz.open()
    for _ in range(201):
        document.new_page()
    raw = document.tobytes()
    document.close()
    parser.validate_document_limits(raw, 'long.pdf')
    with pytest.raises(parser.DocumentLimitError):
        parser.validate_document_limits(raw, 'long.pdf', max_pages=200)


def test_structure_batch_keeps_example_page_and_small_tail_together():
    import knowledge_api
    texts = ['前章' * 20, '题设：' + '已知量' * 8, '问题：' + '求解' * 10, '结束']
    text = '\n\n'.join(texts)
    blocks = knowledge_api._structure_source_blocks(text)
    locations = (
        parser.DocumentLocation('page', 1, '第1页', 0, blocks[0]['char_end'], page_number=1),
        parser.DocumentLocation('page', 2, '第2页', blocks[1]['char_start'], blocks[2]['char_end'], page_number=2),
        parser.DocumentLocation('page', 3, '第3页', blocks[3]['char_start'], len(text), page_number=3),
    )
    batches = knowledge_api._structure_batches(blocks, batch_chars=80, locations=locations)
    assert [block for batch in batches for block in batch] == blocks
    assert next(i for i,batch in enumerate(batches) if blocks[1] in batch) == next(i for i,batch in enumerate(batches) if blocks[2] in batch)
    assert len(knowledge_api._structure_batches(blocks, batch_chars=92, locations=locations)) == 1


def test_structure_continuation_uses_neighbor_context_but_cannot_cite_it(monkeypatch):
    import asyncio, json
    import knowledge_api
    text = ('完整题设。' * 3000) + '\n\n' + ('题设继续。' * 1800) + '\n\n' + ('求解问题。' * 1500)
    parsed = parser.ParsedDocument('example.md', 'md', 'test', text, 'source', 'example-hash', ())
    calls=[]
    invalid=[False]
    async def audited(llm, **kwargs):
        value=json.loads(kwargs['user_prompt']);calls.append(value)
        blocks=value['blocks'];before=value['adjacent_context']['before']
        return json.dumps({'chapters':[{
            'title':'原题' if value['part']==1 else '同题的提问',
            'start_block':before[-1]['id'] if before and invalid[0] else blocks[0]['id'],
            'end_block':blocks[-1]['id'], 'knowledge_points':[],
            'continues_previous':bool(before),
        }]})
    model=type('Model',(),{'provider':'openai','model':'deepseek-v4-flash','thinking_mode':'enabled','reasoning_effort':'max'})()
    monkeypatch.setattr(knowledge_api,'audited_legacy_text_call',audited)
    result=asyncio.run(knowledge_api._extract_resource_structure(parsed,llm=model,owner_public_id='test',course_id='test'))
    assert result['status']=='ready' and result['total_parts']>1
    assert len(result['chapters'])==1
    assert result['chapters'][0]['char_start']==0 and result['chapters'][0]['char_end']==len(text)
    assert calls[0]['adjacent_context']['after'] and calls[1]['adjacent_context']['before']
    assert not ({b['id'] for b in calls[1]['blocks']} & {b['id'] for b in calls[1]['adjacent_context']['before']})
    invalid[0]=True
    failed=asyncio.run(knowledge_api._extract_resource_structure(parsed,llm=model,owner_public_id='test',course_id='test'))
    assert failed['status']=='failed'
    assert failed['completed_parts']==1
