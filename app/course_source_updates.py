"""Retain cited source bodies when a packaged course replaces a document."""
from __future__ import annotations

from copy import deepcopy
from difflib import SequenceMatcher
import hashlib

from app.database import DBChapter, DBChapterKnowledgePoint, DBCourseDocument, DBSourceDocument, DBSourceRef
from app.source_refs import current_chapter_clause


def _id(prefix, *parts):
    return prefix + '-' + hashlib.sha256(':'.join(map(str, parts)).encode()).hexdigest()[:24]


def _copy(row, **changes):
    values = {column.name: deepcopy(getattr(row, column.name)) for column in row.__table__.columns}
    return type(row)(**{**values, **changes})


def revised_text_positions(before, after):
    """Map unchanged boundaries exactly, including offsets after local errata.

    Line alignment keeps long documents inexpensive. Only changed lines need
    character alignment; a boundary inside replaced text encloses that edit.
    """
    old_lines, new_lines = before.splitlines(keepends=True), after.splitlines(keepends=True)
    def offsets(lines):
        result = [0]
        for line in lines:
            result.append(result[-1] + len(line))
        return result
    old_offsets, new_offsets = offsets(old_lines), offsets(new_lines)
    edits = []
    for tag, a, b, c, d in SequenceMatcher(None, old_lines, new_lines, autojunk=False).get_opcodes():
        left, right, target, end = old_offsets[a], old_offsets[b], new_offsets[c], new_offsets[d]
        if tag == 'equal':
            edits.append((tag, left, right, target, end))
        else:
            for kind, i, j, k, l in SequenceMatcher(None, before[left:right], after[target:end]).get_opcodes():
                edits.append((kind, left+i, left+j, target+k, target+l))
    def position(value, *, end=False):
        if value == len(before):
            return len(after)
        for tag, a, b, c, d in edits:
            if a <= value < b or a == b == value:
                if tag == 'equal':
                    return c + value - a
                if value == a:
                    return c
                return d if end else c
        return len(after)
    return position


def preserve_bundle_source_versions(db, course, documents):
    """Reuse existing source replacement/history storage, within the update transaction.

    Original source/chapter/ref identities remain intact for frozen learning
    records. The current document ID remains stable for catalog callers.
    """
    from app.course_structure import _inventory

    workspace = deepcopy((course.manifest_data or {}).get('structure_workspace') or {})
    fingerprint = _inventory(db, course)[-1] if workspace else None
    source_changes, chapter_ids = {}, {}
    for item in documents:
        document = db.get(DBCourseDocument, item['id'])
        source = db.query(DBSourceDocument).filter_by(course_id=course.id, legacy_document_id=item['id']).first()
        if document is None or source is None:
            continue
        digest = hashlib.sha256(item['content'].encode()).hexdigest()
        parser = item.get('parser_version', source.parser_version)
        if document.content == item['content'] and source.parser_version == parser:
            continue
        new_id = _id('src', source.id, digest, parser)
        archive_id = _id('doc', source.id, 'original')
        db.add(_copy(document, id=archive_id, status='retired'))
        source.legacy_document_id = archive_id
        metadata = deepcopy(source.parser_metadata or {})
        source.parser_metadata = {**metadata, 'replaced_by_source_id': new_id}
        # Release the unique (course, legacy document) key before replacement.
        db.flush()
        replacement = _copy(source, id=new_id, legacy_document_id=item['id'],
            parser_metadata={**metadata, 'previous_source_id': source.id})
        db.add(replacement)
        db.flush()
        remap = revised_text_positions(document.content or '', item['content'])
        source_changes[source.id] = (new_id, remap)
        chapters = db.query(DBChapter).filter(DBChapter.source_document_id == source.id,
            current_chapter_clause()).all()
        chapter_keys = {ch.id: ch.stable_key for ch in chapters}
        for ch in chapters:
            chapter_ids[ch.id] = _id('ch', ch.id, new_id)
            ch.stable_key = 'structure-history:' + ch.id
        db.flush()
        for ch in chapters:
            start, end = remap(ch.char_start), remap(ch.char_end, end=True)
            clone = _copy(ch, id=chapter_ids[ch.id], source_document_id=new_id,
                stable_key=chapter_keys[ch.id], char_start=start, char_end=end)
            db.add(clone)
            db.flush()
            for relation in db.query(DBChapterKnowledgePoint).filter_by(chapter_id=ch.id):
                db.add(_copy(relation, id=_id('ckp', clone.id, relation.knowledge_point_id, relation.relation_type),
                    chapter_id=clone.id))
            for ref in db.query(DBSourceRef).filter_by(chapter_id=ch.id, location_kind='chapter',
                    parser_version=source.parser_version):
                db.add(_copy(ref, id=_id('ref', clone.id, new_id), source_document_id=new_id,
                    chapter_id=clone.id, parser_version=parser, content_hash=digest,
                    char_start=start, char_end=end, quote=item['content'][start:end][:300]))
    if not source_changes:
        return None
    db.flush()
    for new_id in chapter_ids.values():
        ch = db.get(DBChapter, new_id)
        ch.parent_id = chapter_ids.get(ch.parent_id, ch.parent_id)
    applied = workspace.get('applied') or {}
    if applied:
        applied['chapter_mapping'] = {key: chapter_ids.get(value, value)
            for key, value in applied.get('chapter_mapping', {}).items()}
        structure = applied.get('structure') or {}
        structure['reference_chapter_ids'] = [chapter_ids.get(value, value)
            for value in structure.get('reference_chapter_ids', [])]
        for unit in structure.get('units', []):
            unit['primary_chapter_keys'] = [chapter_ids.get(value, value)
                for value in unit.get('primary_chapter_keys', [])]
    draft = workspace.get('draft')
    if draft:
        for ch in draft['structure']['chapters']:
            ch['key'] = chapter_ids.get(ch['key'], ch['key'])
            ch['member_ids'] = [chapter_ids.get(value, value) for value in ch['member_ids']]
            ch['parent_key'] = chapter_ids.get(ch.get('parent_key'), ch.get('parent_key'))
            change = source_changes.get(ch['source_document_id'])
            if change:
                ch['source_document_id'], remap = change
                ch['char_start'], ch['char_end'] = remap(ch['char_start']), remap(ch['char_end'], end=True)
        for unit in draft['structure'].get('units', []):
            unit['primary_chapter_keys'] = [chapter_ids.get(value, value)
                for value in unit.get('primary_chapter_keys', [])]
    workspace['revision'] = workspace.get('revision', 0) + 1
    return {'workspace': workspace, 'fingerprint': fingerprint}


def finish_bundle_source_versions(db, course, update):
    if update is None:
        return
    from app.course_structure import _inventory, _issues, _seed

    workspace = update['workspace']
    course.manifest_data = {**(course.manifest_data or {}), 'structure_workspace': deepcopy(workspace)}
    db.flush()
    inventory = _inventory(db, course)
    # Preserve pre-existing unconfirmed edits and their stale state. A mapped
    # structure that no longer forms valid ranges must be reviewed, not blessed.
    applied = workspace.get('applied')
    if applied and applied.get('source_fingerprint') == update['fingerprint']:
        if not _issues(db, course, _seed(db, course, inventory), inventory):
            applied['source_fingerprint'] = inventory[-1]
    draft = workspace.get('draft')
    if draft and draft.get('source_fingerprint') == update['fingerprint']:
        if not _issues(db, course, draft['structure'], inventory):
            draft['source_fingerprint'] = inventory[-1]
    course.manifest_data = {**(course.manifest_data or {}), 'structure_workspace': deepcopy(workspace)}
