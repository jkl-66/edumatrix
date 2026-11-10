import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'

const source = readFileSync(new URL('../src/views/EntryDiagnostic.vue', import.meta.url), 'utf8')
const recovery = source.slice(source.indexOf('function generationParams()'), source.indexOf('async function loadCourses()'))

function scenario(getTask) {
  const context = {
    generationTask: { value: { id: 'original-task', status: 'running' } },
    generating: { value: true }, generationStarted: true, generationFailed: { value: false },
    blueprint: { value: null }, errorKind: { value: '' }, error: { value: '' },
    pollVersion: 0, pollTimer: null, disposed: false,
    courseId: { value: 'course' }, questionCount: { value: 15 }, selfRating: { value: 'foundation' },
    multiCourse: { value: false }, selectedStageId: { value: '' },
    getDiagnosticGenerationTask: getTask,
    findDiagnosticGenerationTask: async () => { throw new Error('must follow the original task') },
    clearTimeout: () => {}, setTimeout: (_, delay) => { context.delay = delay; return 1 },
  }
  vm.createContext(context)
  vm.runInContext(recovery, context)
  return context
}

test('a lost status response preserves the original diagnostic and retries only its status', async () => {
  const requested = []
  const state = scenario(async id => { requested.push(id); throw new Error('offline') })
  await state.pollGeneration()
  assert.equal(state.generating.value, true)
  assert.equal(state.generationFailed.value, false)
  assert.equal(state.errorKind.value, 'generation-status')
  assert.equal(state.delay, 10000)
  state.getDiagnosticGenerationTask = async id => {
    requested.push(id)
    return { task: { id, status: 'completed', blueprint: { id: 'saved-paper' } } }
  }
  await state.pollGeneration()
  assert.deepEqual(requested, ['original-task', 'original-task'])
  assert.equal(state.blueprint.value.id, 'saved-paper')
  assert.equal(state.generating.value, false)
  assert.equal(state.error.value, '')
})

test('changing page while a status request is pending ignores the late result', async () => {
  let finish
  const state = scenario(() => new Promise(resolve => { finish = resolve }))
  const pending = state.pollGeneration()
  state.stopPolling()
  finish({ task: { id: 'original-task', status: 'completed', blueprint: { id: 'stale-paper' } } })
  await pending
  assert.equal(state.blueprint.value, null)
})

test('a genuine backend failure is displayed without automatically starting another run', async () => {
  const state = scenario(async id => ({ task: { id, status: 'failed', message: '题目核对尚未完成。' } }))
  await state.pollGeneration()
  assert.equal(state.generating.value, false)
  assert.equal(state.generationStarted, false)
  assert.equal(state.generationFailed.value, true)
  assert.equal(state.error.value, '题目核对尚未完成。')
  assert.equal(state.delay, undefined)
})

test('multi-course refresh observes the saved request through retry and completion', async () => {
  const state = scenario(() => { throw new Error('single-course API must not run') })
  const requests = [], results = []
  state.multiCourse.value = true
  state.idempotencyKey = () => 'saved-multicourse-request'
  state.applyMulticourseResult = result => { results.push(result); state.blueprint.value = result.items[0].blueprint }
  state.getMulticourseGenerationTask = async params => {
    requests.push(params.idempotency_key)
    return { task: { id:'multi-original', status:'failed', automation:{ enabled:true, state:'retry_wait' } } }
  }
  await state.pollGeneration()
  assert.equal(state.generating.value, true)
  assert.equal(state.generationFailed.value, false)
  state.getMulticourseGenerationTask = async params => {
    requests.push(params.idempotency_key)
    return { task: { id:'multi-original', status:'completed', automation:{ enabled:true, state:'completed' },
      result:{ items:[{ blueprint:{ id:'course-a-paper' } }, { blueprint:{ id:'course-b-paper' } }] } } }
  }
  await state.pollGeneration()
  assert.deepEqual(requests, ['saved-multicourse-request','saved-multicourse-request'])
  assert.equal(results[0].items.length, 2)
  assert.equal(state.generating.value, false)
})
