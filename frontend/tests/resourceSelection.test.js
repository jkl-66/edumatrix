import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import { normalizeContextRef } from '../src/services/context.js'

const source = readFileSync(new URL('../src/views/ResourceCenter.vue', import.meta.url), 'utf8')
const selectCode = source.slice(source.indexOf('async function selectResource('), source.indexOf('async function retryPreview('))
const ref = value => ({ value })

test('resource catalogue resolves archived selections through its resource API after refresh', () => {
  const router = readFileSync(new URL('../src/router/index.js', import.meta.url), 'utf8')
  const code = router.slice(router.indexOf('function courseContextOverride('), router.indexOf('function unknownRouteRedirect('))
  const override = vm.runInNewContext(`${code}; courseContextOverride`)
  assert.equal(override({ name: 'WorkspaceResources' }).resourceId, null)
  assert.equal(override({ name: 'InteractiveModelResource', params: { resourceId: 'legacy' } }).resourceId, null)
  assert.equal(override({ name: 'CodeResource', params: { resourceId: 'archived' } }), null)
})

test('Feynman route restores the material course and clears unrelated context without ignoring access errors', async () => {
  const router = readFileSync(new URL('../src/router/index.js', import.meta.url), 'utf8')
  const code = router.slice(router.indexOf('function courseContextOverride('), router.indexOf('function unknownRouteRedirect('))
  const sandbox = { normalizeContextRef, getM5Resource: async id => ({ id, course_id: 'material-course' }) }
  const override = vm.runInNewContext(`${code}; courseContextOverride`, sandbox)
  const context = await override({ name: 'FeynmanResource', params: { resourceId: 'material' }, query: { course_id: 'stale-course', source_ref_id: 'stale-source' } })
  assert.equal(context.courseId, 'material-course')
  assert.equal(context.resourceId, 'material')
  assert.equal(context.sourceRefId, null)
  assert.equal(context.taskId, null)
  sandbox.getM5Resource = async () => { throw Object.assign(new Error('no access'), { status: 403 }) }
  await assert.rejects(override({ name: 'FeynmanResource', params: { resourceId: 'other-owner' } }), { status: 403 })
})

test('review resource selection keeps its topic and return destination across filtering', () => {
  const code = source.slice(source.indexOf('function queryState('), source.indexOf('async function syncQuery('))
  const state = {
    query: ref('实验'), knowledgePointFilter: ref('kp-eda'), artifactType: ref('interactive_model'),
    status: ref(''), sourceStatus: ref(''), includeArchived: ref(false), viewMode: ref('grid'),
    selected: ref({ id: 'eda-lab' }), currentCourseId: ref('course-ml'),
    route: { query: { return_to: '/workspace/review?review_task=review-plan:9' } },
  }
  const ctx = vm.createContext(state)
  vm.runInContext(code, ctx)
  const query = vm.runInContext('queryState()', ctx)
  assert.equal(query.knowledge_point_id, 'kp-eda')
  assert.equal(query.return_to, state.route.query.return_to)
  state.knowledgePointFilter.value = ''
  assert.equal(vm.runInContext('queryState().knowledge_point_id', ctx), undefined)
})

test('code history shows completion for the selected version rather than the newest version', () => {
  const code = readFileSync(new URL('../src/views/CodeSandboxWorkspace.vue', import.meta.url), 'utf8')
  const expression = code.slice(code.indexOf('const completionRecorded ='), code.indexOf('const canRun ='))
  const state = {
    computed: fn => ({ get value() { return fn() } }), completionResult: ref(null),
    projection: ref({ completion: { status: 'completed' } }),
    isCurrentVersion: ref(false), workspace: ref({ completion: { status: 'not_recorded' } }),
    catalog: ref({ completion: { status: 'not_recorded' } }),
  }
  const sandbox = vm.createContext(state)
  assert.equal(vm.runInContext(`${expression}; completionRecorded.value`, sandbox), true)
  state.projection.value.completion.status = 'not_recorded'
  state.workspace.value.completion.status = 'completed'
  state.catalog.value.completion.status = 'completed'
  assert.equal(vm.runInContext('completionRecorded.value', sandbox), false)
})

test('a slow earlier preview never replaces the resource selected afterward', async () => {
  const requests = new Map()
  const state = {
    resourceSelectionRequest: 0, selected: ref(null), detail: ref(null), detailError: ref(''), detailLoading: ref(false),
    syncQuery: async () => {}, decorate: value => value, message: err => err.message,
    getM5Resource: id => new Promise((resolve, reject) => requests.set(id, { resolve, reject })),
  }
  const ctx = vm.createContext(state)
  vm.runInContext(selectCode, ctx)
  const first = vm.runInContext('selectResource({id:"handout"}, {updateUrl:false})', ctx)
  const second = vm.runInContext('selectResource({id:"deck"}, {updateUrl:false})', ctx)
  requests.get('deck').resolve({ catalog: { id: 'deck' }, content: 'new choice' })
  await second
  requests.get('handout').resolve({ catalog: { id: 'handout' }, content: 'old choice' })
  await first
  assert.equal(state.selected.value.id, 'deck')
  assert.equal(state.detail.value.content, 'new choice')
  assert.equal(state.detailLoading.value, false)
})
