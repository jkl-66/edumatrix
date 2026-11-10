import assert from 'node:assert/strict'
import test from 'node:test'
import { sourceCitationRoute } from '../src/utils/sourceCitationRoute.js'
import { groupSourcePassages, passagePreview, sourcePassageKey } from '../src/utils/sourceCitationRoute.js'

test('source groups keep distinct original positions and versions, and omit only identical entries', () => {
  const one = { sourceDocumentId: 'book', sourceRefId: 'ref', documentVersion: 'v1', charStart: 0, charEnd: 8, title: '教材', quote: '# 动量法\n迭代更新。' }
  const two = { ...one, charStart: 20, charEnd: 30, quote: '平方梯度按权重累积。' }
  const next = { ...one, documentVersion: 'v2' }
  const groups = groupSourcePassages([one, two, { ...one }, next])
  assert.equal(groups.length, 2)
  assert.deepEqual(groups[0].passages.map(item => item.source), [one, two])
  assert.equal(groups[1].passages[0].source, next)
  assert.notEqual(sourcePassageKey(one), sourcePassageKey(two))
  assert.equal(passagePreview(one), '动量法')
  assert.equal(passagePreview(two), '平方梯度按权重累积。')
  assert.equal(passagePreview({ quote: '选择$\\rho = 0.9$时观察权重。' }), '选择…')
})

const latest = { source_document_id: 'doc', document_version: 'v2', route: '/knowledge/documents/doc?source_ref_id=chapter&char_start=0&char_end=5000' }

test('resolving a chapter citation retains the exact verified quote range', () => {
  const route = sourceCitationRoute(latest, { sourceDocumentId: 'doc', documentVersion: 'v2', charStart: 800, charEnd: 820 })
  const params = new URL(route, 'http://localhost').searchParams
  assert.equal(params.get('source_ref_id'), 'chapter')
  assert.equal(params.get('char_start'), '800')
  assert.equal(params.get('char_end'), '820')
})

test('a different version, document or unknown quote position never reuses an old offset', () => {
  for (const selected of [
    { sourceDocumentId: 'other', documentVersion: 'v2', charStart: 800, charEnd: 820 },
    { sourceDocumentId: 'doc', documentVersion: 'v1', charStart: 800, charEnd: 820 },
    { sourceDocumentId: 'doc', documentVersion: 'v2', charStart: null, charEnd: null },
  ]) assert.equal(sourceCitationRoute(latest, selected), latest.route)
  assert.equal(sourceCitationRoute({ route: '//elsewhere' }, {}), '')
})

test('a note returns to its saved text or image selection after resolving the source', () => {
  for (const range of [{ charStart: 800, charEnd: 820 }, { charStart: null, charEnd: null }]) {
    const selected = { sourceDocumentId: 'doc', documentVersion: 'v2', selection_id: 'saved-selection', ...range }
    const params = new URL(sourceCitationRoute(latest, selected), 'http://localhost').searchParams
    assert.equal(params.get('selection_id'), 'saved-selection')
    assert.equal(sourceCitationRoute(latest, { ...selected, documentVersion: 'v1' }), latest.route)
  }
})
