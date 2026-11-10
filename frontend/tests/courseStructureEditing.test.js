import test from 'node:test'
import assert from 'node:assert/strict'
import { acceptStructureSuggestion, canAcceptStructureSuggestion, remapUnitChapters, splitChapterAtQuote } from '../src/utils/courseStructureEditing.js'

test('splitting a reactive chapter preserves Unicode source ranges and independent point lists', () => {
  const body = '前言\n\n🌱训练集用来拟合参数。\n\n验证集用于选择超参数。\n\n测试集留作最终评估。'
  const chapter = new Proxy({ key: 'old', title: '模型评估', source_document_id: 'source',
    member_ids: ['original'], char_start: 4, char_end: Array.from(body).length,
    parent_key: null, knowledge_point_ids: ['training', 'validation'] }, {})
  const next = splitChapterAtQuote(chapter, body, '验证集用于选择超参数。', 'new')
  assert.equal(Array.from(body).slice(next.char_start, next.char_end).join(''), '验证集用于选择超参数。\n\n测试集留作最终评估。')
  assert.equal(chapter.char_end, Array.from(body).length)
  assert.notEqual(next.knowledge_point_ids, chapter.knowledge_point_ids)
  assert.deepEqual(next.member_ids, ['original'])
})

test('ambiguous or out-of-chapter excerpts do not silently move a split', () => {
  const chapter = { char_start: 0, char_end: 8 }
  assert.throws(() => splitChapterAtQuote(chapter, '开头重复重复结束', '重复', 'new'), /多次/)
  assert.throws(() => splitChapterAtQuote(chapter, '开头重复重复结束', '开头', 'new'), /中间/)
  assert.throws(() => splitChapterAtQuote(chapter, '开头重复重复结束另章内容', '另章', 'new'), /中间/)
})

test('accepting an equivalent concept changes the draft and redirects existing dependencies', () => {
  const structure = { concepts: [{ id: 'a', title: '训练误差' }, { id: 'b', title: '经验误差' }, { id: 'c', title: '泛化误差' }],
    prerequisites: [{ prerequisite_id: 'b', dependent_id: 'a' }, { prerequisite_id: 'b', dependent_id: 'c' }] }
  const suggestion = { kind: 'same_concept', keys: ['a', 'b'], titles: ['训练误差', '经验误差'], title: '训练误差' }
  assert.equal(acceptStructureSuggestion(structure, suggestion), true)
  assert.equal(structure.concepts[1].merge_into, 'a')
  assert.deepEqual(structure.prerequisites, [{ prerequisite_id: 'a', dependent_id: 'c' }])
  assert.equal(canAcceptStructureSuggestion(structure, suggestion), false)
})

test('chapter merge keeps all sources and points; edited suggestions cannot be applied', () => {
  const structure = { units: [{ primary_chapter_keys: ['b'] }], chapters: [
    { key: 'a', title: '正则化', source_document_id: 's', member_ids: ['a'], char_start: 0, char_end: 100, knowledge_point_ids: ['x'] },
    { key: 'b', title: '正则项', source_document_id: 's', member_ids: ['b'], char_start: 100, char_end: 200, knowledge_point_ids: ['y'] },
  ] }
  const suggestion = { kind: 'adjacent_chapters', keys: ['a', 'b'], titles: ['正则化', '正则项'], title: '正则化' }
  structure.chapters[0].title = '已手动修改'
  assert.equal(acceptStructureSuggestion(structure, suggestion), false)
  structure.chapters[0].title = '正则化'
  assert.equal(acceptStructureSuggestion(structure, suggestion), true)
  assert.equal(structure.chapters.length, 1)
  assert.equal(structure.chapters[0].char_end, 200)
  assert.deepEqual(structure.chapters[0].member_ids, ['a', 'b'])
  assert.deepEqual(structure.chapters[0].knowledge_point_ids, ['x', 'y'])
  assert.deepEqual(structure.units[0].primary_chapter_keys, ['a'])
})

test('splitting preserves both parts of selected primary reading without changing unselected units', () => {
  const structure = { units: [{ primary_chapter_keys: ['a', 'c'] }, { primary_chapter_keys: [] }, {}] }
  remapUnitChapters(structure, 'a', ['a', 'b'])
  assert.deepEqual(structure.units, [{ primary_chapter_keys: ['a', 'b', 'c'] }, { primary_chapter_keys: [] }, {}])
})

test('automatic merging does not mix reference reading with scheduled teaching', () => {
  const structure={chapters:[{key:'a',title:'讲解',source_document_id:'s',char_end:10,learning_role:'teaching'},
    {key:'b',title:'参考',source_document_id:'s',char_start:10,learning_role:'reference'}]}
  assert.equal(canAcceptStructureSuggestion(structure,{kind:'adjacent_chapters',keys:['a','b'],titles:['讲解','参考']}),false)
  const chapter={key:'b',title:'参考',source_document_id:'s',member_ids:['b'],char_start:0,char_end:8,
    learning_role:'reference',knowledge_point_ids:[]}
  assert.equal(splitChapterAtQuote(chapter,'前段内容后段内容','后段','new').learning_role,'reference')
})
