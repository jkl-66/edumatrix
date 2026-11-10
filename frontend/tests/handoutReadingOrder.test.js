import test from 'node:test'
import assert from 'node:assert/strict'
import { orderedHandoutSections, handoutSectionMarkdown } from '../src/utils/handoutReadingOrder.js'

test('an example and runnable snippet remain before the explanation in reading and notes', () => {
  const content = {
    outline: [{ id: 'example' }, { id: 'code' }, { id: 'concept' }, { id: 'example' }],
    concepts: [{ id: 'concept', title: '机制', explanation: '两条路径的贡献相加。' }],
    examples: [{ id: 'example', title: '先算这个例子', body: '12+6=18' }],
    codeBlocks: [{ id: 'code', title: '运行核对', language: 'python', code: '```python\nprint(12 + 6)\n```', explanation: '输出18。' }],
    miniQuiz: [{ id: 'quiz', question: '结果是？', options: ['12', '18'], correctIndex: 1, explanation: '累加。' }],
  }
  const sections = orderedHandoutSections(content)
  assert.deepEqual(sections.map(item => item.id), ['example', 'code', 'concept', 'quiz'])
  const note = sections.map(handoutSectionMarkdown).join('\n\n')
  assert.ok(note.indexOf('print(12 + 6)') < note.indexOf('两条路径'))
  assert.ok(note.includes('答案：** 18'))
  assert.equal(content.outline.length, 4)
  assert.equal(sections[1].code, 'print(12 + 6)')
  assert.ok(content.codeBlocks[0].code.startsWith('```'))
})

test('a partial historical outline cannot hide unlisted content or render footnotes as empty lessons', () => {
  const content = { outline: [{ id: 'source-1' }, { id: 'removed' }],
    concepts: [{ id: 'concept', explanation: '原有概念' }], counterExamples: [{ id: 'boundary', body: '原有边界' }] }
  assert.deepEqual(orderedHandoutSections(content).map(item => item.id), ['concept', 'boundary'])
})

test('transfer questions keep their prompt and support when saved as notes', () => {
  const content = { transferTasks: [{ id: 'transfer-1', title: '变化条件', prompt: '损失取平均会怎样？', hint: '检查批量大小。', successCheck: '梯度除以样本数。' }] }
  const sections = orderedHandoutSections(content)
  assert.equal(sections[0].sectionType, 'transferTasks')
  const markdown = handoutSectionMarkdown(sections[0])
  assert.ok(markdown.includes(content.transferTasks[0].prompt))
  assert.ok(markdown.includes(content.transferTasks[0].hint))
  assert.ok(markdown.includes(content.transferTasks[0].successCheck))
})
