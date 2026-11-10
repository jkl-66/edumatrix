import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import { ref } from 'vue'

const source = readFileSync(new URL('../src/views/FeynmanWorkspace.vue', import.meta.url), 'utf8')
const functions = source.slice(source.indexOf('function updateRouteSession'), source.indexOf('async function runAction'))
function workspace() {
  const calls = []
  const state = {
    route: { query: {} }, resourceId: ref('resource'), requestedSourceVersion: ref('old'),
    loading: ref(false), actionPending: ref(''), error: ref(''), notice: ref(''),
    session: ref(null), resource: ref(null), sessions: ref([]),
    round1Draft: ref(''), questionDraft: ref(''), round2Draft: ref(''),
    readPreference: () => null, writePreference: () => {}, uniqueKey: () => 'attempt',
    restoreDrafts() {}, message: error => error.message,
    resetActionTask() {}, async restoreActionTask() {},
    storageKey: field => field, localStorage: { getItem: () => null },
    async getM5Resource() { return { history: { current_version_id: 'new', items: [{ id: 'old' }, { id: 'new' }] } } },
    async getFeynmanSession(id) { return { session_id: id, source_resource_id: 'resource', source_resource_version_id: 'old', course_id: 'course' } },
    async listFeynmanSessions(id, version) { calls.push(['list', id, version]); return { items: [] } },
    async createFeynmanSession(id, key, version) {
      calls.push(['create', id, version])
      return { session_id: 'created', source_resource_id: id, source_resource_version_id: version, course_id: 'course' }
    },
  }
  state.router = { async replace({ query }) { state.route.query = query } }
  const context = vm.createContext(state)
  vm.runInContext('let loadSequence = 0;\n' + functions, context)
  return { state, context, calls }
}

test('old bundle creates a session for its material, fixes the course and preserves version on refresh', async () => {
  const { state, context, calls } = workspace()
  state.route.query.course_id = 'stale-course'
  await context.loadWorkspace()
  assert.deepEqual(calls, [['list', 'resource', 'old'], ['create', 'resource', 'old']])
  assert.equal(state.route.query.course_id, 'course')
  assert.equal(state.route.query.version_id, 'old')
  await context.loadWorkspace()
  assert.equal(calls.filter(c => c[0] === 'create').length, 1)
  assert.equal(state.session.value.source_resource_version_id, 'old')
})

test('explicit history uses its frozen source, while invalid material or foreign session cannot fall back', async () => {
  const { state, context, calls } = workspace()
  state.route.query.session_id = 'saved-session'
  state.requestedSourceVersion.value = 'new'
  await context.loadWorkspace()
  assert.deepEqual(calls, [['list', 'resource', 'old']])
  assert.equal(state.route.query.version_id, 'old')
  state.getFeynmanSession = async () => ({ source_resource_id: 'other-resource' })
  await context.loadWorkspace()
  assert.match(state.error.value, /另一份/)
  assert.equal(state.session.value, null)
  state.route.query = {}
  state.requestedSourceVersion.value = 'missing'
  await context.loadWorkspace()
  assert.match(state.error.value, /重新选择/)
  assert.equal(calls.filter(c => c[0] === 'create').length, 0)
})

test('slow previous material cannot replace the active resource or create an unwanted attempt', async () => {
  const { state, context, calls } = workspace()
  const original = state.getM5Resource
  let release
  state.getM5Resource = () => new Promise(resolve => { release = resolve })
  const pending = context.loadWorkspace()
  state.resourceId.value = 'second-resource'
  state.requestedSourceVersion.value = 'new'
  state.getM5Resource = original
  await context.loadWorkspace()
  release(await original())
  await pending
  assert.equal(state.session.value.source_resource_id, 'second-resource')
  assert.deepEqual(calls, [['list', 'second-resource', 'new'], ['create', 'second-resource', 'new']])
})
