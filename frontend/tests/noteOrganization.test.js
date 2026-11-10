import { test } from 'node:test'
import assert from 'node:assert/strict'
import { noteTemplateContent, arrangeNotes, noteDisplayTitle, noteCourseId, NOTE_TEMPLATES } from '../src/utils/noteOrganization.js'

test('four note outlines retain the exact excerpt and the chosen course', () => {
  for (const template of NOTE_TEMPLATES) {
    const value = noteTemplateContent(template.id, { course: '深度学习', concept: '共享参数', quote: 'w*x+w\n梯度分别是12和6' })
    assert.ok(value.startsWith('# 共享参数'))
    assert.ok(value.includes('课程：深度学习'))
    assert.ok(value.includes('> w*x+w\n> 梯度分别是12和6'))
    for (const heading of template.sections) assert.ok(value.includes(`## ${heading}`))
  }
})

test('pinning and recent reading change ordering without changing notes', () => {
  const notes = [
    { id: 'a', content: '# 参数共享', updated_at: '2026-11-01', source_metadata: { course_id: 'ai' } },
    { id: 'b', content: '# 链式法则', updated_at: '2026-11-02' },
    { id: 'c', concepts: ['梯度检查'], updated_at: '2026-11-03' },
  ]
  const original = JSON.stringify(notes)
  assert.deepEqual(arrangeNotes(notes, { pinned: ['a'], recent: ['b'], sort: 'recent' }).map(note => note.id), ['a', 'b', 'c'])
  assert.equal(JSON.stringify(notes), original)
  assert.equal(noteDisplayTitle(notes[0]), '参数共享')
  assert.equal(noteCourseId(notes[0]), 'ai')
})
