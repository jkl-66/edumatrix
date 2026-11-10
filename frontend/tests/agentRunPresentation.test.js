import assert from 'node:assert/strict'
import test from 'node:test'
import { translatePublicText, presentRunEvents, runRoleLabel } from '../src/utils/agentRunPresentation.js'

const event = (id, eventType, status, stageId = '') => ({
  id, eventType, status, stageId, candidateSummary: '正在准备讲解。',
})

test('failed answers stop unfinished steps while preserving real completed and failed outcomes', () => {
  const rows = [event('1', 'stage.completed', 'completed', 'retrieval'),
    event('2', 'stage.started', 'running', 'revision_verification'),
    event('3', 'stage.failed', 'failed', 'professional_chain'), event('4', 'run.failed', 'failed')]
  const original = structuredClone(rows)
  const projected = presentRunEvents(rows, 'failed')
  assert.deepEqual(projected.map(row => row.status), ['completed', 'stopped', 'failed', 'failed'])
  assert.match(projected[1].candidateSummary, /已中断/)
  assert.deepEqual(rows, original)
})

test('active stages remain active until a real end or a subsequent attempt is recorded', () => {
  const live = [event('1', 'stage.started', 'running', 'answer_generation')]
  assert.equal(presentRunEvents(live, 'running')[0].status, 'running')
  assert.equal(presentRunEvents(live, 'completed')[0].status, 'unknown')
  assert.match(presentRunEvents(live, 'completed')[0].candidateSummary, /历史记录不完整/)
  const stopped = [...live, event('2', 'run.stopped', 'stopped')]
  assert.equal(presentRunEvents(stopped, 'stopped')[0].status, 'stopped')
})

test('retry keeps previous attempts as history and shows only the current stage as running', () => {
  const rows = [event('1', 'stage.started', 'running', 'answer_generation'),
    event('2', 'run.failed', 'failed'), event('3', 'run.retry', 'queued'),
    event('4', 'stage.started', 'running', 'answer_generation')]
  const projected = presentRunEvents(rows, 'running')
  assert.equal(projected[0].status, 'recorded')
  assert.equal(projected[1].status, 'previous_failed')
  assert.equal(projected[3].status, 'running')
  assert.equal(presentRunEvents(rows.slice(0, 3), 'queued')[0].status, 'stopped')
})

test('successful retries distinguish the earlier failure from the current answer', () => {
  const rows = [event('1', 'stage.failed', 'failed', 'professional_chain'), event('2', 'run.failed', 'failed'),
    event('3', 'run.retry', 'queued'), event('4', 'stage.started', 'running', 'pedagogical'),
    event('5', 'run.completed', 'completed')]
  const projected = presentRunEvents(rows, 'completed')
  assert.equal(projected[0].status, 'previous_failed')
  assert.match(projected[0].candidateSummary, /前次记录/)
  assert.equal(projected[3].status, 'unknown')
  assert.ok(!projected.some(row => row.status === 'running' || row.status === 'failed'))
})

test('completed historical stages never keep an animated start event', () => {
  const projected = presentRunEvents([event('1', 'stage.started', 'running', 'subject_expert'),
    event('2', 'stage.completed', 'completed', 'subject_expert'), event('3', 'run.completed', 'completed')], 'completed')
  assert.deepEqual(projected.map(row => row.status), ['recorded', 'completed', 'completed'])
})

test('resource failures retain their individual results when the answer ends', () => {
  const rows = [
    { ...event('1', 'resource.item.completed', 'completed'), resourceType: 'handout' },
    { ...event('2', 'resource.item.failed', 'failed'), resourceType: 'quiz' },
    { ...event('3', 'resource.item.started', 'running'), resourceType: 'deck' },
    event('4', 'run.failed', 'failed'),
  ]
  assert.deepEqual(presentRunEvents(rows, 'failed').map(row => row.status), ['completed', 'failed', 'stopped', 'failed'])
})

test('legacy execution summaries read as whole learning sentences', () => {
  assert.equal(translatePublicText('正在根据已冻结的上下文生成回答。'), '正在结合本次问题和学习资料准备讲解。')
  for (const text of ['课程综合回答模型失败，已保留当前内容。', '真实模型回答失败，已保留当前内容。']) {
    assert.equal(translatePublicText(text), '这次讲解暂未完成，已保留当前内容，可以重试。')
  }
  assert.equal(translatePublicText('本次运行失败，可从保留的内容继续或重试。'), '这次回答已中断，可以继续回答。')
  assert.equal(translatePublicText('模型的参数数量为3，学习率为0.4。'), '模型的参数数量为3，学习率为0.4。')
})

test('stage headings avoid repeated or invented suffixes', () => {
  assert.equal(runRoleLabel('回答整理', '回答整理'), '回答整理')
  assert.equal(runRoleLabel('内容讲解', undefined), '内容讲解')
  assert.equal(runRoleLabel('质量检查', '测验题'), '质量检查 · 测验题')
})
