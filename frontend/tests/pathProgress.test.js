import test from 'node:test'
import assert from 'node:assert/strict'
import { projectedTaskStatus, pathProgress, progressLabel, estimatedPathMinutes } from '../src/utils/pathProgress.js'

test('diagnostic exemptions are not claimed as completed learning actions', () => {
  const nodes = [
    { status: projectedTaskStatus({ status: 'pending' }, { status: 'skipped' }) },
    { status: projectedTaskStatus({ status: 'completed' }, { status: 'pending' }) },
    { status: projectedTaskStatus({ status: 'pending' }, { status: 'pending', scheduled_day: 1 }) },
    { status: projectedTaskStatus({ status: 'pending' }, { status: 'pending', scheduled_day: 2 }) },
  ]
  assert.equal(nodes[2].status, 'in_progress')
  assert.equal(nodes[3].status, 'pending')
  const summary = pathProgress(nodes)
  assert.deepEqual(summary, { total: 4, completed: 1, skipped: 1, percentage: 50 })
  assert.equal(progressLabel(summary), '1/4 项完成 · 1 项测评已通过')
})

test('path duration uses the displayed tasks including ranged and exact estimates', () => {
  assert.equal(estimatedPathMinutes([
    { estimate_minutes: [18, 20] }, { estimate_minutes: [12, 15] },
    { estimate_min_minutes: 30, estimate_max_minutes: 35 }, { estimate_minutes: 20 },
  ]), 90)
  assert.equal(estimatedPathMinutes([]), 0)
})
