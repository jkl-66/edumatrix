import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'

const source = readFileSync(new URL('../src/composables/usePathGeneration.js', import.meta.url), 'utf8')
  .replace(/^import .*\n/gm, '').replace('export function', 'function')

function setup(api) {
  const scheduled = new Map()
  let sequence = 0
  const context = {
    ref: value => ({ value }), computed: fn => ({ get value() { return fn() } }),
    onBeforeUnmount: () => {},
    setTimeout: fn => { const id = ++sequence; scheduled.set(id, fn); return id },
    clearTimeout: id => scheduled.delete(id), ...api,
  }
  const factory = vm.runInNewContext(`${source}; usePathGeneration`, context)
  return { factory, scheduled }
}

test('restoring a running path observes the same job through completion', async () => {
  const reads = [], completed = []
  const { factory, scheduled } = setup({
    findPathGenerationTask: async () => ({ task: { id: 'original', status: 'running' } }),
    getPathGenerationTask: async id => { reads.push(id); return { task: { id, status: 'completed' } } },
  })
  const flow = factory({ onComplete: task => completed.push(task.id) })
  await flow.restore({ course_id: 'course-a' })
  assert.equal(flow.busy.value, true)
  assert.equal(scheduled.size, 1)
  await flow.refresh()
  assert.deepEqual(reads, ['original'])
  assert.deepEqual(completed, ['original'])
  assert.equal(flow.busy.value, false)
  assert.equal(scheduled.size, 0)
})

test('switching courses ignores a late status response from the previous course', async () => {
  let resolveOld
  const completed = []
  const { factory } = setup({
    findPathGenerationTask: ({ course_id }) => course_id === 'old'
      ? new Promise(resolve => { resolveOld = resolve })
      : Promise.resolve({ task: { id: 'new', status: 'running' } }),
  })
  const flow = factory({ onComplete: task => completed.push(task.id) })
  const pending = flow.restore({ course_id: 'old' })
  await flow.restore({ course_id: 'new' })
  resolveOld({ task: { id: 'old', status: 'completed' } })
  await pending
  assert.equal(flow.task.value.id, 'new')
  assert.deepEqual(completed, [])
})

test('network failure retains and automatically observes the original job until reconnection', async () => {
  let unavailable = true
  const { factory, scheduled } = setup({
    getPathGenerationTask: async id => {
      if (unavailable) throw Error('offline')
      return { task: { id, status: 'running' } }
    },
  })
  const flow = factory()
  await flow.accept({ id: 'original', status: 'running' })
  for (let i = 0; i < 3; i++) await flow.refresh()
  assert.equal(scheduled.size, 1)
  assert.equal(flow.task.value.id, 'original')
  assert.equal(flow.busy.value, true)
  assert.match(flow.connectionError.value, /暂时无法读取/)
  unavailable = false
  await flow.refresh()
  assert.equal(flow.connectionError.value, '')
  assert.equal(scheduled.size, 1)
})

test('automatic repair and configuration wait remain attached to the same path', async () => {
  const { factory, scheduled } = setup({})
  const flow = factory()
  for (const state of ['retry_wait', 'waiting_configuration']) {
    await flow.accept({ id:'original', status:'failed', automation:{ enabled:true, state } })
    assert.equal(flow.busy.value, true)
    assert.equal(flow.task.value.id, 'original')
    assert.equal(scheduled.size, 1)
  }
  await flow.accept({ id:'original', status:'cancelled', automation:{ enabled:true, state:'cancelled' } })
  assert.equal(flow.busy.value, false)
  assert.equal(scheduled.size, 0)
})

test('aggregate path uses the same persisted request after a disconnected status read', async () => {
  const { factory } = setup({})
  let disconnected = true
  const completed = []
  const flow = factory({
    findTask: async params => ({ task:{ id:params.idempotency_key, status:'running' } }),
    getTask: async id => {
      if (disconnected) throw Error('offline')
      return { task:{ id, status:'completed', result:{ subjects:['a','b'] } } }
    },
    onComplete: task => completed.push(task.result),
  })
  await flow.restore({ idempotency_key:'original-multi-path' })
  await flow.refresh()
  assert.equal(flow.task.value.id, 'original-multi-path')
  disconnected = false
  await flow.refresh()
  assert.deepEqual(completed, [{ subjects:['a','b'] }])
})
