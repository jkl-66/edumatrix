import test from 'node:test'
import assert from 'node:assert/strict'
import { resourceContentFields, updateResourceContent } from '../src/utils/resourceContentFields.js'

test('learning editors keep source, mastery and execution identities out of the form', () => {
  const value = { schemaVersion: 'f5.mindmap.v1', title: '测试导图', rootNodeId: 'root', nodes: [
    { nodeId: 'root', label: '数组', summary: '按位置读取', masteryBand: 'secure', sourceRefs: ['source-1'], linkedResourceIds: ['art-1'] },
  ], semanticContext: { profileSnapshotId: 'profile-1', summary: '内部摘要' } }
  assert.deepEqual(resourceContentFields(value).map(f => f.label), ['标题', '知识点 1 · 名称', '知识点 1 · 内容说明'])
  const updated = updateResourceContent(value, ['nodes', 0, 'summary'], '下标从零开始')
  assert.equal(updated.nodes[0].summary, '下标从零开始')
  assert.equal(value.nodes[0].summary, '按位置读取')
  assert.deepEqual({ ...updated.nodes[0], summary: value.nodes[0].summary }, value.nodes[0])
  assert.deepEqual(updated.semanticContext, value.semanticContext)
  assert.equal(updateResourceContent(value, ['nodes', 0, 'masteryBand'], 'unknown'), value)
})

test('practice instructions can change without replacing linked experiments or grading references', () => {
  const value = { schemaVersion: 'f5.training-task.v1', title: '练习', linkedSandboxId: 'code-1', linkedModelId: 'model-1',
    steps: [{ id: 'step-1', title: '运行', instruction: '先预测', sourceRefIds: ['source-1'] }],
    rubric: [{ id: 'rubric-1', points: 100, evidence: '实际输出' }] }
  const updated = updateResourceContent(value, ['steps', 0, 'instruction'], '先预测，再运行核对')
  assert.equal(updated.steps[0].instruction, '先预测，再运行核对')
  assert.equal(updated.linkedModelId, 'model-1')
  assert.deepEqual(updated.rubric, value.rubric)
  assert.deepEqual(updated.steps[0].sourceRefIds, ['source-1'])
})

test('teaching code stays literal and unknown serialized content is not exposed', () => {
  const value = { schemaVersion: 'f6.code-sandbox.v1', files: [{ path: 'main.py', content: 'print("hi")\n' }], completionRule: 'run-tests' }
  const [field] = resourceContentFields(value)
  assert.equal(field.code, true)
  const code = 'print("你好")\n# student example\n'
  assert.equal(updateResourceContent(value, field.path, code).files[0].content, code)
  assert.deepEqual(resourceContentFields({ schemaVersion: 'unknown', title: 'internal' }), [])
})
