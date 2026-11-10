import test from 'node:test'
import assert from 'node:assert/strict'
import { reviewContentText } from '../src/utils/reviewContentText.js'

test('review shows teaching content, code and the actual answer without internal metadata', () => {
  const code = 'def score(x):\n    return x * 100.0\n'
  const result = reviewContentText(JSON.stringify({
    title: '比例练习', schemaVersion: 'internal.v1', sourceRefIds: ['ref-secret'],
    metadata: { raw_log: 'hidden log' }, codeBlocks: [{ id: 'code-1', language: 'python', code }],
    miniQuiz: [{ prompt: '9条有效记录，共10条，比例是多少？', options: ['0.9', '1.0'], correctIndex: 0 }],
  }))
  assert.ok(result.includes(code))
  assert.ok(result.includes('参考答案：0.9'))
  assert.ok(result.includes('9条有效记录，共10条，比例是多少？'))
  for (const hidden of ['internal.v1', 'ref-secret', 'hidden log', 'correctIndex', 'codeBlocks']) assert.ok(!result.includes(hidden))
})

test('unstructured teaching code and text retain their original spelling', () => {
  const text = '空输入要单独处理。\n```python\nif not values:\n    return 0\n```'
  assert.equal(reviewContentText(text), text)
})
