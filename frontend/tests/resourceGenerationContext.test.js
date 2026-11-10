import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'

const source = readFileSync(new URL('../src/views/ResourceCenter.vue', import.meta.url), 'utf8')
const navigate = source.slice(source.indexOf('async function openGeneration('), source.indexOf('function openTypeGeneration('))

test('path restores a prior resource job for the exact task without mixing units sharing one concept', () => {
  const path = readFileSync(new URL('../src/views/LearningPathGraph.vue', import.meta.url), 'utf8')
  const find = path.slice(path.indexOf('function findGenerationJob('), path.indexOf('function selectTodayKnowledgePoint('))
  const task = { node_id: 'unit-a', path_id: 'path-v2', course_id: 'course', generation_context: { knowledge_point_id: 'point' } }
  const unrelated = { course_id: 'course', knowledge_point_id: 'point', idempotency_key: 'old-other', manifest: { task_id: 'unit-b', path_id: 'path-v2' } }
  const prior = { course_id: 'course', knowledge_point_id: 'point', idempotency_key: 'old-format-yesterday', manifest: { task_id: 'unit-a', path_id: 'path-v2' } }
  const state = { generationJobs: { value: [unrelated, prior] }, generationIdempotencyKey: () => 'new-format-today' }
  const restore = vm.runInNewContext(`${find}; findGenerationJob`, state)
  assert.equal(restore(task), prior)
  assert.equal(restore({ ...task, node_id: 'unit-c' }), null)
  assert.equal(restore({ ...task, path_id: 'old-path' }), null)
  assert.equal(restore({ ...task, course_id: 'other-course' }), null)
})

test('path generation request preserves task, plan version, day and conversation within message key length', () => {
  const path = readFileSync(new URL('../src/views/LearningPathGraph.vue', import.meta.url), 'utf8')
  const helper = path.slice(path.indexOf('function generationIdempotencyKey('), path.indexOf('async function generateSelectedResourceBundle('))
  const key = vm.runInNewContext(`${helper}; generationIdempotencyKey`)
  const task = { node_id: 'node-' + 'a'.repeat(32), generation_context: { path_version_id: 'pv-' + 'b'.repeat(32) } }
  const request = key(task)
  assert.ok(request.includes(task.node_id))
  assert.ok(request.includes(task.generation_context.path_version_id))
  assert.match(request, /:\d{4}-\d{2}-\d{2}$/)
  assert.ok(`${request}:conv-${'c'.repeat(32)}`.length <= 128)
  assert.notEqual(request, key({ ...task, node_id: 'node-' + 'd'.repeat(32) }))
})

test('handout history does not present lost option labels as answerable questions', () => {
  const handout = readFileSync(new URL('../src/views/HandoutWorkspace.vue', import.meta.url), 'utf8')
  const helper = handout.slice(handout.indexOf('function hasQuizOptions('), handout.indexOf('function checkAnswer('))
  const usable = vm.runInNewContext(`${helper}; hasQuizOptions`)
  assert.equal(usable({ options: ['A', 'B', 'C', 'D'] }), false)
  assert.equal(usable({ options: ['A.', 'B.', 'C.', 'D.'] }), false)
  assert.equal(usable({ options: ['训练模型', ''] }), false)
  assert.equal(usable({ options: ['A. 创建模型', 'B. 训练模型'] }), true)
  const titleFn = handout.slice(handout.indexOf('function displayHandoutTitle('), handout.indexOf('const title = computed'))
  const display = vm.runInNewContext(`${titleFn}; displayHandoutTitle`, {
    catalog: { value: { knowledge_point: { title: '训练与推理' } } }, genericTitleSuffixes: [],
  })
  assert.equal(display('个性化讲义 · 请' + '完整学习要求'.repeat(12)), '个性化讲义 · 训练与推理')
  assert.equal(display('我的自定义讲义标题'), '我的自定义讲义标题')
})

function context(custom) {
  const destinations = []
  return {
    destinations,
    detail: { value: { resource: { course_id: 'old-course', chapter_id: 'old-chapter', source_ref_ids: ['old-source'] } } },
    selected: { value: null }, currentCourseId: { value: 'old-course' },
    generationOpen: { value: custom },
    generationContext: { value: { course_id: 'chosen-course', source_ref_ids: ['chosen-source'] } },
    typeDefinitions: [{ id: 'handout' }, { id: 'quiz' }],
    route: { fullPath: '/workspace/resources' },
    router: { push: async value => destinations.push(value) },
    newIdempotencyKey: () => 'synthetic-request',
  }
}

test('custom generation carries selected course and sources without stale resource context', async () => {
  const state = context(true)
  await vm.runInNewContext(`${navigate}; openGeneration({type:'quiz',knowledgePointId:'chosen-point',prompt:'练习当前知识点'})`, state)
  const { path, query } = state.destinations[0]
  assert.equal(path, '/chat')
  assert.equal(query.course_id, 'chosen-course')
  assert.equal(query.knowledge_point_id, 'chosen-point')
  assert.equal(query.chapter_id, undefined)
  assert.equal(query.source_ref_ids, 'chosen-source')
  assert.equal(query.resource_types, 'quiz')
  assert.equal(query.prompt, '练习当前知识点')
  assert.equal(query.return_to, '/workspace/resources')
})

test('resource follow-up keeps the resource course and chapter', async () => {
  const state = context(false)
  state.generationContext.value = null
  await vm.runInNewContext(`${navigate}; openGeneration({type:'handout'})`, state)
  const { query } = state.destinations[0]
  assert.equal(query.course_id, 'old-course')
  assert.equal(query.chapter_id, 'old-chapter')
  assert.equal(query.source_ref_ids, 'old-source')
})

test('mindmap follow-up keeps its knowledge point, selected node and version', () => {
  const map = readFileSync(new URL('../src/views/MindmapWorkspace.vue', import.meta.url), 'utf8')
  const navigate = map.slice(map.indexOf('function askAboutNode('), map.indexOf('function createNodeNote('))
  const calls = []
  vm.runInNewContext(`${navigate}; askAboutNode()`, {
    selectedNode: { value: { nodeId: 'split', label: '分裂准则', sourceRefs: ['map-source'] } },
    resourceId: { value: 'map-resource' }, selectedVersionId: { value: 'map-v2' },
    catalog: { value: { course: { id: 'map-course' }, knowledge_point: { id: 'map-point' } } },
    route: { query: { course_id: 'old-course' } }, router: { push: value => calls.push(value) },
  })
  assert.equal(calls[0].query.course_id, 'map-course')
  assert.equal(calls[0].query.knowledge_point_id, 'map-point')
  assert.equal(calls[0].query.node_id, 'split')
  assert.equal(calls[0].query.version_id, 'map-v2')
  assert.equal(calls[0].query.source_ref_id, 'map-source')
})

test('reader generation executes the created job and opens that job rather than an unrelated catalog item', async () => {
  const reader = readFileSync(new URL('../src/views/KnowledgeDocumentReader.vue', import.meta.url), 'utf8')
  const generate = reader.slice(reader.indexOf('async function generateResource('), reader.indexOf('async function retryOcr('))
  const open = reader.slice(reader.indexOf('function openResourceCenter('), reader.indexOf('function backToKnowledge('))
  const calls = []
  const state = {
    generationScope: { value: 'document' }, canUseSelection: { value: false },
    busyAction: { value: '' }, generationError: { value: '' }, resourceType: { value: 'quiz' },
    generationResult: { value: null }, selection: { value: null }, sourceDocumentId: { value: 'selected-source' },
    toolbarVisible: { value: false }, activeSideTab: { value: 'actions' }, readerDoc: { value: { course: { id: 'selected-course' } } },
    operationKey: () => 'synthetic-reader-generation',
    generateDocumentResource: async (source, payload) => { calls.push({ source, payload }); return { job: { job_id: 'created-job' } } },
    executeGenerationJob: async id => { calls.push({ execute: id }); return { job_id: id, status: 'succeeded' } },
    apiMessage: (_error, fallback) => fallback,
    router: { push: value => calls.push({ destination: value }) },
  }
  await vm.runInNewContext(`${generate}; ${open}; generateResource().then(openResourceCenter)`, state)
  assert.equal(calls[0].source, 'selected-source')
  assert.equal(calls[0].payload.resource_type, 'quiz')
  assert.equal(calls[1].execute, 'created-job')
  assert.equal(calls[2].destination.path, '/workspace/resources/bundles/created-job')
  assert.equal(calls[2].destination.query.course_id, 'selected-course')
  assert.equal(state.generationResult.value.job.status, 'succeeded')
  assert.equal(state.busyAction.value, '')
})

test('quiz source navigation retains the exact question, resource version and copied course', () => {
  const quiz = readFileSync(new URL('../src/views/QuizResourceWorkspace.vue', import.meta.url), 'utf8')
  const open = quiz.slice(quiz.indexOf('function openSource('), quiz.indexOf('function startEditing('))
  const calls = []
  const state = {
    sourceRefs: { value: [{ id: 'copied-ref', source_document_id: 'copied-document' }] },
    catalog: { value: { course: { id: 'copied-course' } } },
    selectedVersionId: { value: 'historic-version' }, activeQuestionId: { value: 'third-question' },
    route: { path: '/workspace/resources/quizzes/test-resource', query: { course_id: 'copied-course' } },
    router: {
      resolve: ({ path, query }) => ({ fullPath: path + '?' + new URLSearchParams(query) }),
      push: value => calls.push(value),
    },
    encodeURIComponent,
  }
  vm.runInNewContext(`${open}; openSource('copied-ref')`, state)
  assert.equal(calls[0].path, '/knowledge/documents/copied-document')
  assert.equal(calls[0].query.course_id, 'copied-course')
  assert.equal(calls[0].query.source_ref_id, 'copied-ref')
  const back = new URL(calls[0].query.return_to, 'http://test.invalid')
  assert.equal(back.searchParams.get('resource_version_id'), 'historic-version')
  assert.equal(back.searchParams.get('question_version_id'), 'third-question')
})
