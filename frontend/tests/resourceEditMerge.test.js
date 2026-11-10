import assert from 'node:assert/strict'
import test from 'node:test'
import { ref } from 'vue'
import { mergeResourceEdits } from '../src/utils/resourceEditMerge.js'
import { useResourceEditMerge } from '../src/services/useResourceEditMerge.js'

const original = () => ({ title: '数组', slides: [
  { id: 'intro', title: '起点', body: '从0开始', speakerNotes: '原备注' },
  { id: 'practice', title: '练习', body: '取列', speakerNotes: '' },
] })

test('mindmap nodes merge independent edits and conflicting text without exposing identifiers', () => {
  const base = { nodes: [{ nodeId: 'root', label: '数组', summary: '原说明' }, { nodeId: 'child', label: '索引', summary: '从零开始' }] }
  const mine = structuredClone(base), latest = structuredClone(base)
  mine.nodes[0].summary = '本页说明'
  latest.nodes[1].summary = '另一页补充'
  const combined = mergeResourceEdits(base, mine, latest)
  assert.equal(combined.conflicts.length, 0)
  assert.deepEqual(combined.content.nodes.map(n => n.summary), ['本页说明', '另一页补充'])
  latest.nodes[0].summary = '已存说明'
  const result = mergeResourceEdits(base, mine, latest)
  assert.equal(result.conflicts.length, 1)
  assert.equal(result.conflicts[0].label, '资源内容 · 知识点 · 数组 · 内容摘要')
  assert.equal(result.conflicts[0].local, '本页说明')
  const chosen = mergeResourceEdits(base, mine, latest, { [result.conflicts[0].key]: 'latest' })
  assert.deepEqual(chosen.content.nodes.map(n => n.summary), ['已存说明', '另一页补充'])
})

test('stale page keeps its own note and the other page title, added slide and order', () => {
  const base = original(), mine = original(), latest = original()
  mine.slides[0].speakerNotes = '先区分行列'
  latest.title = '数组与向量化'
  latest.slides.splice(1, 0, { id: 'check', title: '过滤后查原记录', body: '相同掩码' })
  const result = mergeResourceEdits(base, mine, latest)
  assert.deepEqual(result.conflicts, [])
  assert.equal(result.content.title, latest.title)
  assert.deepEqual(result.content.slides.map(item => item.id), ['intro', 'check', 'practice'])
  assert.equal(result.content.slides[0].speakerNotes, '先区分行列')
  assert.deepEqual(base, original())
  assert.deepEqual(latest.slides[0], original().slides[0])
})

test('same field conflict requires a choice and keeps unrelated edits', () => {
  const base = original(), mine = original(), latest = original()
  mine.slides[0].body = '本页讲法'
  latest.slides[0].body = '另一页讲法'
  latest.slides[1].body = '先取行，再取列'
  mine.title = '修订课件'
  const draft = ref(mine)
  const editor = useResourceEditMerge(draft)
  editor.refresh(base, latest)
  assert.equal(editor.conflicts.value.length, 1)
  assert.match(editor.conflicts.value[0].label, /起点 · 正文/)
  editor.choose(editor.conflicts.value[0].key, 'latest')
  assert.equal(editor.conflicts.value.length, 0)
  assert.equal(draft.value.slides[0].body, '另一页讲法')
  assert.equal(draft.value.slides[1].body, '先取行，再取列')
  assert.equal(draft.value.title, '修订课件')
})

test('deleting a page edited elsewhere is a conflict, not a silent deletion', () => {
  const base = original(), mine = original(), latest = original()
  mine.slides.pop()
  latest.slides[1].body = '另一页的新练习'
  const result = mergeResourceEdits(base, mine, latest)
  assert.equal(result.conflicts.length, 1)
  const resolved = mergeResourceEdits(base, mine, latest, { [result.conflicts[0].key]: 'latest' })
  assert.equal(resolved.content.slides[1].body, '另一页的新练习')
})

test('different page orders and legacy text expose choices without fabricating a merge', () => {
  const base = original(), mine = original(), latest = original()
  mine.slides.reverse()
  mine.slides[0].body = '本页修改了练习'
  latest.slides.push({ id: 'end', title: '结尾' })
  const result = mergeResourceEdits(base, mine, latest)
  assert.equal(result.conflicts.length, 1)
  assert.match(result.conflicts[0].label, /课件页面/)
  const resolved = mergeResourceEdits(base, mine, latest, { [result.conflicts[0].key]: 'latest' })
  assert.deepEqual(resolved.content.slides.map(item => item.id), ['intro', 'practice', 'end'])
  assert.equal(resolved.content.slides[1].body, '本页修改了练习')
  assert.equal(mergeResourceEdits('旧讲义', '本页文字', '另一页文字').conflicts.length, 1)
})

test('the same final edit on both pages does not require a redundant choice', () => {
  const base = original(), mine = original(), latest = original()
  mine.title = latest.title = '共同修订'
  assert.equal(mergeResourceEdits(base, mine, latest).conflicts.length, 0)
})
