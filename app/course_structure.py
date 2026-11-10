"""Editable course organization over the existing chapters, concepts and sources."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import re
from difflib import SequenceMatcher
from typing import Literal

from fastapi import HTTPException
from pydantic import Field

from app.authorization import require_course_access
from app.database import (DBChapter, DBChapterKnowledgePoint, DBCourse,
                          DBCourseDocument, DBKnowledgeDocument, DBKnowledgePoint,
                          DBSourceDocument, DBSourceRef)
from app.m2_contracts import StrictModel
from app.source_refs import current_chapter_clause, current_source_clause


class StructureChapter(StrictModel):
    key: str
    title: str
    source_document_id: str
    member_ids: list[str]
    char_start: int = Field(ge=0)
    char_end: int = Field(ge=0)
    parent_key: str | None = None
    knowledge_point_ids: list[str] = Field(default_factory=list)
    learning_role: Literal['teaching', 'reference'] = 'teaching'


class StructureConcept(StrictModel):
    id: str
    title: str
    merge_into: str | None = None


class StructureUnit(StrictModel):
    key: str
    title: str
    goal: str = ''
    knowledge_point_ids: list[str] = Field(default_factory=list)
    primary_chapter_keys: list[str] = Field(default_factory=list)


class StructurePrerequisite(StrictModel):
    prerequisite_id: str
    dependent_id: str
    basis: Literal['teaching_suggestion', 'source_explicit'] = 'teaching_suggestion'
    source_ref_id: str | None = None
    quote: str = ''


class CourseStructure(StrictModel):
    chapters: list[StructureChapter]
    concepts: list[StructureConcept]
    units: list[StructureUnit] = Field(default_factory=list)
    prerequisites: list[StructurePrerequisite] = Field(default_factory=list)


class StructureSave(StrictModel):
    revision: int = Field(ge=0)
    source_fingerprint: str
    structure: CourseStructure


class StructureConfirm(StrictModel):
    revision: int = Field(ge=0)


def _id(prefix, *parts):
    return prefix + '-' + hashlib.sha256(':'.join(map(str, parts)).encode()).hexdigest()[:24]


def _fail(message, status=422):
    raise HTTPException(status_code=status, detail=message)


def _course(db, actor, course_id, *, edit=False):
    course = db.get(DBCourse, course_id)
    if course is None:
        _fail('课程不存在。', 404)
    require_course_access(db, actor, course_id=course_id, visibility=course.visibility)
    if edit and actor.role != 'admin' and course.owner_public_id != actor.public_id:
        _fail('只有课程管理者可以调整课程结构。', 403)
    return course


def _inventory(db, course):
    chapters = db.query(DBChapter).join(DBSourceDocument, DBSourceDocument.id == DBChapter.source_document_id).filter(
        DBChapter.course_id == course.id, current_source_clause(), current_chapter_clause(),
    ).order_by(DBChapter.position, DBChapter.id).all()
    sources = db.query(DBSourceDocument).filter(
        DBSourceDocument.course_id == course.id, current_source_clause(),
    ).order_by(DBSourceDocument.id).all()
    document_order = {row.id: row.chapter_order for row in db.query(DBCourseDocument).filter_by(course_id=course.id)}
    ordered_sources = sorted(sources, key=lambda source: (
        document_order.get(source.legacy_document_id, float('inf')),
        source.created_at, source.id,
    ))
    source_order = {source.id: index for index, source in enumerate(ordered_sources)}
    # Imported chapter positions are local to each document. Confirmed positions
    # are global; retain those and append subsequently added documents.
    chapters.sort(key=lambda ch: (0, ch.position, ch.id) if ch.stable_key.startswith('structure:') else
                  (1, source_order[ch.source_document_id], ch.position, ch.id))
    links = db.query(DBChapterKnowledgePoint).filter(
        DBChapterKnowledgePoint.chapter_id.in_([ch.id for ch in chapters]),
    ).all() if chapters else []
    points = db.query(DBKnowledgePoint).filter(DBKnowledgePoint.id.in_({link.knowledge_point_id for link in links})).all() if links else []
    fingerprint = hashlib.sha256(json.dumps({
        'sources': [(s.id, s.processed_sha256, s.processing_status) for s in sources],
        'chapters': [(ch.id, ch.title, ch.parent_id, ch.char_start, ch.char_end) for ch in chapters],
        'concepts': sorted((p.id, p.title) for p in points),
        'links': sorted((link.chapter_id, link.knowledge_point_id) for link in links),
    }, sort_keys=True).encode()).hexdigest()
    return chapters, sources, links, points, fingerprint


def _seed(db, course, inventory):
    chapters, _, links, points, _ = inventory
    point_ids = {point.id for point in points}
    names = {}
    for point in points:
        names.setdefault(point.title.casefold().strip(), []).append(point.id)
        names.setdefault(point.code.casefold().strip(), []).append(point.id)
    def resolve(value):
        if value in point_ids:
            return value
        matches = set(names.get(str(value).casefold().strip(), []))
        return next(iter(matches)) if len(matches) == 1 else None
    prerequisites, seen = [], set()
    for point in points:
        for raw in point.prerequisites or []:
            before = resolve(raw)
            if before and before != point.id and (before, point.id) not in seen:
                prerequisites.append({'prerequisite_id': before, 'dependent_id': point.id,
                                      'basis': 'teaching_suggestion', 'source_ref_id': None, 'quote': ''})
                seen.add((before, point.id))
    applied = ((course.manifest_data or {}).get('structure_workspace') or {}).get('applied') or {}
    existing = applied.get('structure') or {}
    units = deepcopy(existing.get('units', []))
    for unit in units:
        unit['knowledge_point_ids'] = [id for id in unit['knowledge_point_ids'] if id in point_ids]
    units = [unit for unit in units if unit['knowledge_point_ids']]
    relations = deepcopy(existing.get('prerequisites', prerequisites))
    relations = [r for r in relations if r['prerequisite_id'] in point_ids and r['dependent_id'] in point_ids]
    return {
        'chapters': [{'key': ch.id, 'title': ch.title, 'source_document_id': ch.source_document_id,
                      'member_ids': [ch.id], 'char_start': ch.char_start, 'char_end': ch.char_end,
                      'parent_key': ch.parent_id,
                      'learning_role': 'reference' if ch.id in existing.get('reference_chapter_ids', []) else 'teaching',
                      'knowledge_point_ids': list(dict.fromkeys(link.knowledge_point_id for link in links if link.chapter_id == ch.id))}
                     for ch in chapters],
        'concepts': [{'id': p.id, 'title': p.title, 'merge_into': None} for p in sorted(points, key=lambda p: (p.title, p.id))],
        'units': units if 'units' in existing else [
            {'key': 'unit-'+ch.id, 'title': ch.title, 'goal': '',
             'knowledge_point_ids': list(dict.fromkeys(link.knowledge_point_id for link in links if link.chapter_id == ch.id))}
            for ch in chapters if any(link.chapter_id == ch.id for link in links)
        ],
        'prerequisites': relations,
    }


def _title_terms(title):
    value = re.sub(r'[\W_\d]+', '', title.casefold())
    return value


def _suggestions(structure):
    suggestions = []
    for left, right in zip(structure['chapters'], structure['chapters'][1:]):
        if left['source_document_id'] != right['source_document_id'] or left.get('parent_key') != right.get('parent_key'):
            continue
        a, b = _title_terms(left['title']), _title_terms(right['title'])
        # A title match is only a proposal. It never silently changes a course.
        if a and b and (a == b or SequenceMatcher(None, sorted(a), sorted(b)).ratio() >= .78):
            suggestions.append({'kind': 'adjacent_chapters', 'keys': [left['key'], right['key']],
                                'message': f'“{left["title"]}”与“{right["title"]}”可能属于同一主题。'})
    return suggestions


def structure_signature(structure):
    return hashlib.sha256(json.dumps(structure, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def prepare_structure_analysis(db, actor, course_id):
    course = _course(db, actor, course_id, edit=True)
    state = read_course_structure(db, actor, course_id)
    if state['stale']:
        _fail('课程资料已变化，请先按当前资料重新整理。', 409)
    previous = ((course.manifest_data or {}).get('structure_workspace') or {}).get('semantic_analysis') or {}
    # Confirmation also changes the inventory fingerprint. Keep old batches as
    # internal candidates: the analyzer matches the complete current prompt,
    # including source ids, positions, quotes, titles and permitted pairs.
    # Public reads still hide the old analysis after source/structure changes.
    state['_analysis_batches'] = deepcopy(previous.get('batches') or [])
    sources = db.query(DBSourceDocument).filter(DBSourceDocument.course_id == course.id, current_source_clause()).all()
    return state, {source.id: _content(db, source) for source in sources}


def save_structure_analysis(db, actor, course_id, original, analysis):
    course = _course(db, actor, course_id, edit=True)
    current = read_course_structure(db, actor, course_id)
    if (current['source_fingerprint'] != original['source_fingerprint']
            or current['revision'] != original['revision']
            or structure_signature(current['structure']) != structure_signature(original['structure'])):
        _fail('课程结构已修改，请基于新的结构重新查找合并建议。', 409)
    workspace = deepcopy((course.manifest_data or {}).get('structure_workspace') or {})
    workspace['semantic_analysis'] = {**analysis, 'source_fingerprint': original['source_fingerprint'],
                                    'structure_signature': structure_signature(original['structure'])}
    course.manifest_data = {**(course.manifest_data or {}), 'structure_workspace': workspace}
    db.commit()
    return read_course_structure(db, actor, course_id)


def read_course_structure(db, actor, course_id):
    course = _course(db, actor, course_id)
    inventory = _inventory(db, course)
    chapters, sources, _, _, fingerprint = inventory
    workspace = (course.manifest_data or {}).get('structure_workspace') or {}
    saved = workspace.get('draft')
    structure = deepcopy(saved['structure']) if saved else _seed(db, course, inventory)
    analysis = workspace.get('semantic_analysis') or {}
    analysis_current = (analysis.get('source_fingerprint') == fingerprint
                        and analysis.get('structure_signature') == structure_signature(structure))
    return {'course_id': course.id, 'course_title': course.title,
            'can_edit': actor.role == 'admin' or course.owner_public_id == actor.public_id,
            'revision': workspace.get('revision', 0), 'source_fingerprint': fingerprint,
            'draft_saved': bool(saved), 'stale': bool(saved and saved['source_fingerprint'] != fingerprint),
            'needs_confirmation': not workspace.get('applied') or (workspace['applied'].get('source_fingerprint') != fingerprint),
            'structure': structure, 'suggestions': _suggestions(structure),
            'semantic_analysis': analysis if analysis_current else None,
            'references': [{'id': ref.id, 'label': f'{source.title} · {ref.location_label}'}
                for source in sources for ref in db.query(DBSourceRef).filter(
                    DBSourceRef.source_document_id == source.id, DBSourceRef.location_kind == 'chapter',
                    DBSourceRef.chapter_id.in_([ch.id for ch in chapters]),
                ).order_by(DBSourceRef.location_index).all()],
            'sources': [{'id': s.id, 'title': s.title, 'status': s.processing_status} for s in sources],
            'applied_at': (workspace.get('applied') or {}).get('confirmed_at'),
            'issues': _issues(db, course, structure, inventory)}


def _issues(db, course, structure, inventory):
    issues = []
    chapters, sources, links, points, _ = inventory
    old_chapters = {ch.id: ch for ch in chapters}
    source_by_id = {s.id: s for s in sources}
    point_by_id = {p.id: p for p in points}
    edited = structure['chapters']
    concepts = {p['id']: p for p in structure['concepts']}
    keys = [ch['key'] for ch in edited]
    if len(keys) != len(set(keys)):
        issues.append('章节名称对应的条目重复，请移除重复条目。')
    if set(concepts) != set(point_by_id) or len(concepts) != len(structure['concepts']):
        issues.append('知识点范围已变化，请重新读取课程结构。')
    canonical = {}
    for point in structure['concepts']:
        target = point.get('merge_into') or point['id']
        if not point['title'].strip():
            issues.append('请填写知识点名称。')
        if target not in concepts or (target != point['id'] and concepts[target].get('merge_into')):
            issues.append('合并目标必须是保留的知识点，不能循环合并。')
        canonical[point['id']] = target
    coverage = {}
    for chapter in edited:
        if not chapter['title'].strip():
            issues.append('请填写章节名称。')
        source = source_by_id.get(chapter['source_document_id'])
        members = [old_chapters.get(id) for id in chapter['member_ids']]
        if source is None or source.processing_status != 'ready' or not members or any(m is None or m.source_document_id != source.id for m in members):
            issues.append('章节必须对应当前课程中已读完的资料。')
            continue
        start, end = chapter['char_start'], chapter['char_end']
        lower, upper = min(m.char_start for m in members), max(m.char_end for m in members)
        if not lower <= start < end <= upper:
            issues.append(f'“{chapter["title"]}”的原文范围不正确。')
        if chapter.get('parent_key') and chapter['parent_key'] not in keys:
            issues.append('章节的上级条目不存在。')
        if chapter.get('parent_key') == chapter['key']:
            issues.append('章节不能以自己作为上级。')
        for member in members:
            coverage.setdefault(member.id, []).append((max(start, member.char_start), min(end, member.char_end)))
        if any(id not in concepts for id in chapter['knowledge_point_ids']):
            issues.append('章节包含了当前课程以外的知识点。')
    for id, ch in old_chapters.items():
        ranges = sorted((a, b) for a, b in coverage.get(id, []) if b > a)
        cursor = ch.char_start
        for start, end in ranges:
            if start != cursor:
                break
            cursor = end
        if cursor != ch.char_end:
            issues.append(f'“{ch.title}”的原文范围有遗漏或重叠。')
    def cycle(edges):
        pending, done = set(), set()
        def visit(node):
            if node in pending:
                return True
            if node in done:
                return False
            pending.add(node)
            if any(visit(next) for next in edges.get(node, [])):
                return True
            pending.remove(node); done.add(node)
            return False
        return any(visit(node) for node in edges)
    parents = {ch['key']: [ch['parent_key']] for ch in edited if ch.get('parent_key')}
    if cycle(parents):
        issues.append('章节层级形成了循环，请调整上级条目。')
    taught = {canonical.get(id, id) for ch in edited for id in ch['knowledge_point_ids']}
    if any(canonical.get(id, id) not in taught for id in concepts):
        issues.append('有知识点没有关联任何章节，请为它选择原文。')
    unit_keys = [unit['key'] for unit in structure['units']]
    if len(unit_keys) != len(set(unit_keys)):
        issues.append('学习单元条目重复。')
    for unit in structure['units']:
        if not unit['title'].strip() or not unit['knowledge_point_ids'] or any(id not in concepts for id in unit['knowledge_point_ids']):
            issues.append('每个学习单元需要名称和本课程的知识点。')
        primary = unit.get('primary_chapter_keys') or []
        if primary:
            if any(key not in keys for key in primary):
                issues.append('学习单元的主学习章节已变化，请重新选择。')
            if any(ch.get('learning_role') == 'reference' for ch in edited if ch['key'] in primary):
                issues.append('主学习章节不能同时设为参考阅读，请先调整章节用途。')
            covered = {canonical.get(id, id) for ch in edited if ch['key'] in primary
                       for id in ch['knowledge_point_ids']}
            if not {canonical.get(id, id) for id in unit['knowledge_point_ids']}.issubset(covered):
                issues.append('主学习章节须包含本单元的全部知识点，其余相关章节仍可作为参考。')
    edges = {}
    for relation in structure['prerequisites']:
        before, after = relation['prerequisite_id'], relation['dependent_id']
        if before not in concepts or after not in concepts:
            issues.append('先修关系包含了课程以外的知识点。')
            continue
        before, after = canonical[before], canonical[after]
        if before == after:
            issues.append('合并后的知识点不能以前身作为先修。')
        edges.setdefault(after, []).append(before)
        if relation['basis'] == 'source_explicit':
            ref = db.get(DBSourceRef, relation.get('source_ref_id')) if relation.get('source_ref_id') else None
            source = source_by_id.get(ref.source_document_id) if ref else None
            content = _content(db, source) if source else ''
            quote = relation.get('quote', '').strip()
            if not ref or not source or not quote or quote not in content[int(ref.char_start or 0):int(ref.char_end or len(content))]:
                issues.append('原文明示的先修关系需要可定位的原文摘录；没有依据时可改为教学建议。')
    if cycle(edges):
        issues.append('先修关系形成了循环，请调整学习顺序。')
    return list(dict.fromkeys(issues))


def _content(db, source):
    row = db.get(DBCourseDocument, source.legacy_document_id) if source and source.legacy_document_id else None
    if row is None and source and source.legacy_document_id:
        row = db.get(DBKnowledgeDocument, source.legacy_document_id)
    return str(row.content or '') if row else ''


def save_course_structure(db, actor, course_id, payload: StructureSave):
    course = _course(db, actor, course_id, edit=True)
    workspace = deepcopy((course.manifest_data or {}).get('structure_workspace') or {})
    if payload.revision != workspace.get('revision', 0):
        _fail('课程结构刚刚有新的修改，当前草稿仍在页面中，请重新读取后再保存。', 409)
    inventory = _inventory(db, course)
    if payload.source_fingerprint != inventory[-1]:
        _fail('课程资料已变化，请重新读取结构后继续整理。', 409)
    workspace['revision'] = payload.revision + 1
    workspace['draft'] = {'structure': payload.structure.model_dump(), 'source_fingerprint': inventory[-1]}
    course.manifest_data = {**(course.manifest_data or {}), 'structure_workspace': workspace}
    db.commit()
    return read_course_structure(db, actor, course_id)


def reset_course_structure(db, actor, course_id, payload: StructureConfirm):
    """Explicitly replace an outdated draft with the current course inventory."""
    course = _course(db, actor, course_id, edit=True)
    workspace = deepcopy((course.manifest_data or {}).get('structure_workspace') or {})
    if payload.revision != workspace.get('revision', 0):
        _fail('课程结构刚刚有新的修改，请重新打开后再整理。', 409)
    workspace.pop('draft', None)
    workspace['revision'] = payload.revision + 1
    course.manifest_data = {**(course.manifest_data or {}), 'structure_workspace': workspace}
    db.commit()
    return read_course_structure(db, actor, course_id)


def confirm_course_structure(db, actor, course_id, payload: StructureConfirm):
    course = _course(db, actor, course_id, edit=True)
    workspace = deepcopy((course.manifest_data or {}).get('structure_workspace') or {})
    if payload.revision != workspace.get('revision', 0):
        _fail('课程结构已有新修改，请重新读取后再确认。', 409)
    saved = workspace.get('draft')
    if not saved:
        # Repeated confirmation is idempotent; it cannot create another version.
        if workspace.get('applied'):
            return read_course_structure(db, actor, course_id)
        _fail('请先保存课程结构。')
    inventory = _inventory(db, course)
    if saved['source_fingerprint'] != inventory[-1]:
        _fail('课程资料已变化，请重新读取后再确认。', 409)
    structure = deepcopy(saved['structure'])
    issues = _issues(db, course, structure, inventory)
    if issues:
        _fail('；'.join(issues))
    _apply_structure(db, course, structure, inventory, workspace, payload.revision)
    db.commit()
    return read_course_structure(db, actor, course_id)


def initialize_curated_structure(db, course, template):
    """Apply packaged teaching sections once, preserving all local edits.

    The template is part of the versioned course manifest. It uses document
    filenames and concept codes; actual source/chapter identities are resolved
    inside the same catalog transaction, including on a fresh installation.
    """
    workspace = deepcopy((course.manifest_data or {}).get('structure_workspace') or {})
    if not template or workspace.get('applied') or workspace.get('draft'):
        return
    # Production SessionLocal disables autoflush. The catalog has just added
    # the last document's concept links; include them in the first inventory.
    db.flush()
    inventory = _inventory(db, course)
    chapters, sources, _, points, _ = inventory
    source_by_name = {source.filename: source for source in sources}
    point_by_code = {point.code: point.id for point in points}
    structure = _seed(db, course, inventory)
    structure['chapters'] = []
    for item in template['chapters']:
        source = source_by_name[item['filename']]
        content = _content(db, source)
        if hashlib.sha256(content.encode()).hexdigest() != item['content_sha256']:
            raise ValueError('Curated teaching section does not match source text: '+item['filename'])
        structure['chapters'].append({
            'key': item['key'], 'title': item['title'], 'source_document_id': source.id,
            'member_ids': [ch.id for ch in chapters if ch.source_document_id == source.id],
            'char_start': item['char_start'], 'char_end': item['char_end'], 'parent_key': None,
            'knowledge_point_ids': [point_by_code[code] for code in item['knowledge_point_codes']],
            'learning_role': item.get('learning_role', 'teaching'),
        })
    structure['units'] = [{
        'key': unit['key'], 'title': unit['title'], 'goal': unit['goal'],
        'knowledge_point_ids': [point_by_code[code] for code in unit['knowledge_point_codes']],
        'primary_chapter_keys': unit['primary_chapter_keys'],
    } for unit in template['units']]
    structure = CourseStructure.model_validate(structure).model_dump()
    issues = _issues(db, course, structure, inventory)
    if issues:
        raise ValueError('Invalid curated teaching structure: '+'; '.join(issues))
    workspace['revision'] = workspace.get('revision', 0) + 1
    _apply_structure(db, course, structure, inventory, workspace, workspace['revision'])


def _apply_structure(db, course, structure, inventory, workspace, revision):
    """Persist validated organization; caller owns authorization/transaction."""
    old_chapters, sources, links, points, _ = inventory
    source_by_id = {s.id: s for s in sources}
    point_by_id = {p.id: p for p in points}
    aliases = {p['id']: p.get('merge_into') or p['id'] for p in structure['concepts']}
    point_map = {id: id for id in point_by_id}
    # Imported copies normally already have course-local nodes. If a concept
    # is shared, a rename must not change another teacher's course.
    for edit in structure['concepts']:
        if aliases[edit['id']] != edit['id']:
            continue
        point = point_by_id[edit['id']]
        if point.title != edit['title']:
            shared = db.query(DBChapterKnowledgePoint).join(DBChapter, DBChapter.id == DBChapterKnowledgePoint.chapter_id).filter(
                DBChapterKnowledgePoint.knowledge_point_id == point.id, DBChapter.course_id != course.id,
            ).first()
            if shared:
                clone = DBKnowledgePoint(id=_id('kp', course.id, revision, point.id), domain_pack='structure:'+course.id,
                    code=_id('K', point.id), version=str(revision), title=edit['title'], level=point.level,
                    prerequisites=[], status='active')
                db.add(clone); point_map[point.id] = clone.id
            else:
                point.title = edit['title']
    db.flush()
    def target(id):
        return point_map[aliases[id]]
    chapter_map = {ch['key']: _id('ch', course.id, revision, ch['key']) for ch in structure['chapters']}
    # Keep old chapter identities and source references readable for old paths,
    # resources and selections. Only automatic current-course listings exclude them.
    for ch in old_chapters:
        ch.stable_key = 'structure-history:'+ch.id
    for position, edit in enumerate(structure['chapters'], 1):
        source = source_by_id[edit['source_document_id']]
        chapter = DBChapter(id=chapter_map[edit['key']], course_id=course.id, source_document_id=source.id,
            stable_key=f'structure:{revision}:{edit["key"]}', title=edit['title'], position=position,
            heading_level=1, char_start=edit['char_start'], char_end=edit['char_end'])
        db.add(chapter)
        db.flush()
        text = _content(db, source)
        ref = DBSourceRef(id=_id('ref', chapter.id, source.id), source_document_id=source.id, chapter_id=chapter.id,
            parser_version=source.parser_version, content_hash=source.processed_sha256 or source.content_hash,
            location_kind='chapter', location_index=position, location_label=chapter.title,
            char_start=chapter.char_start, char_end=chapter.char_end, quote=text[chapter.char_start:chapter.char_end][:300],
            location_metadata={'structure_revision': revision})
        db.add(ref)
        for point_id in dict.fromkeys(target(id) for id in edit['knowledge_point_ids']):
            db.add(DBChapterKnowledgePoint(id=_id('ckp', chapter.id, point_id), chapter_id=chapter.id, knowledge_point_id=point_id))
    db.flush()
    for edit in structure['chapters']:
        if edit.get('parent_key'):
            db.get(DBChapter, chapter_map[edit['key']]).parent_id = chapter_map[edit['parent_key']]
    # The relation basis belongs to this course, not to a globally shared node.
    normalized_relations = [{**relation, 'prerequisite_id': target(relation['prerequisite_id']),
                             'dependent_id': target(relation['dependent_id'])} for relation in structure['prerequisites']]
    units = [{**unit, 'knowledge_point_ids': list(dict.fromkeys(target(id) for id in unit['knowledge_point_ids']))}
             for unit in structure['units']]
    for unit in units:
        if unit.get('primary_chapter_keys'):
            unit['primary_chapter_keys'] = [chapter_map[key] for key in unit['primary_chapter_keys']]
    old_aliases = (workspace.get('applied') or {}).get('concept_aliases', {})
    current_aliases = {id: target(id) for id in aliases if id != target(id)}
    current_aliases.update({id: current_aliases.get(mapped, mapped) for id, mapped in old_aliases.items()})
    workspace['applied'] = {'revision': revision, 'confirmed_at': datetime.now(timezone.utc).isoformat(),
        'source_fingerprint': _inventory(db, course)[-1],
        'chapter_mapping': chapter_map, 'concept_aliases': current_aliases,
        'structure': {'units': units, 'prerequisites': normalized_relations,
                      'reference_chapter_ids': [chapter_map[ch['key']] for ch in structure['chapters']
                                                if ch.get('learning_role') == 'reference']}}
    workspace.pop('draft', None)
    course.manifest_data = {**(course.manifest_data or {}), 'structure_workspace': workspace}


def confirmed_structure(course):
    if course is None:
        return {}
    return (((course.manifest_data or {}).get('structure_workspace') or {}).get('applied') or {}).get('structure') or {}


def confirmed_concept_aliases(course):
    if course is None:
        return {}
    return dict((((course.manifest_data or {}).get('structure_workspace') or {}).get('applied') or {}).get('concept_aliases') or {})


def prerequisite_ids(course, point):
    structure = confirmed_structure(course)
    if not structure:
        return list(point.prerequisites or [])
    return list(dict.fromkeys(r['prerequisite_id'] for r in structure.get('prerequisites', []) if r['dependent_id'] == point.id))
