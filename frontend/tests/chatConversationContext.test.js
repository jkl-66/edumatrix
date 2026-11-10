import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'

const source = readFileSync(new URL('../src/views/Chat.vue', import.meta.url), 'utf8')
const queryFunction = source.slice(source.indexOf('function conversationQuery('), source.indexOf('async function activateConversation('))

test('answer reference actions expand the collapsed panel and select the requested content', () => {
  const action = source.slice(source.indexOf('function showMessageEvidence('), source.indexOf('function openQuizSource('))
  const state = { activeEvidenceMessageId: { value: 'old' }, evidenceTab: { value: 'trace' }, evidenceRailCollapsed: { value: true } }
  const open = vm.runInNewContext(`${action}; showMessageEvidence`, state)
  open({ id: 'answer-with-sources' }, 'course')
  assert.equal(state.activeEvidenceMessageId.value, 'answer-with-sources')
  assert.equal(state.evidenceTab.value, 'course')
  assert.equal(state.evidenceRailCollapsed.value, false)
  open({ id: 'answer-with-process' }, 'trace')
  assert.equal(state.activeEvidenceMessageId.value, 'answer-with-process')
  assert.equal(state.evidenceTab.value, 'trace')
})

test('submitting a question prevents a duplicate, and a failed retry keeps the same operation', async () => {
  const storeSource = readFileSync(new URL('../src/stores/chat.js', import.meta.url), 'utf8')
  const body = storeSource.slice(storeSource.indexOf('function operationKey(')).replace('export const useChatStore', 'const useChatStore')
  const requests = []
  let resolve, reject
  const options = vm.runInNewContext(`${body}; useChatStore`, {
    defineStore: (_, value) => value,
    clearTimeout() {},
    errorMessageText: (value) => String(value),
    createChatMessage: (_, request) => {
      requests.push(request)
      return new Promise((yes, no) => { resolve = yes; reject = no })
    },
  })
  const store = Object.assign(options.state(), options.actions, {
    activeConversationId: 'chat',
    activeConversation: { id: 'chat', title: '新对话' },
    conversations: [{ id: 'chat', title: '新对话' }],
    startStream() { this.sending = true },
  })
  const first = store.sendMessage({ content: '为什么会过拟合？', sourceMessageId: 'selected-older-answer' })
  assert.equal(store.submitting, true)
  assert.equal(store.error, '')
  assert.equal(await store.sendMessage({ content: '为什么会过拟合？' }), null)
  assert.equal(await store.retryPendingMessage(), null)
  assert.equal(requests.length, 1)
  reject(new Error('连接中断'))
  await assert.rejects(first, /连接中断/)
  assert.equal(store.submitting, false)
  assert.equal(store.pendingSend, requests[0])
  const retried = store.retryPendingMessage()
  assert.equal(store.submitting, true)
  assert.equal(requests[1].idempotency_key, requests[0].idempotency_key)
  assert.equal(requests[1].source_message_id, 'selected-older-answer')
  resolve({ conversation: { id: 'chat', title: '为什么会过拟合？' }, userMessage: { id: 'question', sequence: 1 }, assistantMessage: { id: 'answer', sequence: 2 } })
  await retried
  assert.equal(store.pendingSend, null)
  assert.equal(store.submitting, false)
  assert.equal(store.sending, true)
  assert.equal(store.activeConversation.title, '为什么会过拟合？')
  assert.equal(store.conversations[0].title, '为什么会过拟合？')
  assert.equal(store.messages.length, 2)
})

test('generating from a selected answer binds that answer and sends a usable instruction', async () => {
  const startCode = source.slice(source.indexOf('function startResourceFromMessage('), source.indexOf('function onComposerKeydown('))
  const sendCode = source.slice(source.indexOf('async function sendMessage('), source.indexOf('async function continueWithGeneralKnowledge('))
  const calls = []
  const state = {
    watch() {}, messages: { value: [] },
    resourceSourceMessageId: { value: '' }, activeEvidenceMessageId: { value: 'latest-answer' },
    resourcePickerOpen: { value: false }, localError: { value: '' }, draft: { value: '' },
    canSend: { value: true }, composerResourceTypes: { value: ['handout', 'quiz'] },
    selectedResourceTypes: { value: ['handout', 'quiz'] }, outgoingContextRefs: { value: [] },
    outgoingReturnTo: { value: '' }, nextTick: async () => {}, scrollToBottom() {},
    chatStore: { sendMessage: async value => { calls.push(value); return {} } },
  }
  const actions = vm.runInNewContext(`${startCode}; ${sendCode}; ({ startResourceFromMessage, sendMessage })`, state)
  actions.startResourceFromMessage({ id: 'selected-older-answer' })
  assert.equal(state.resourceSourceMessageId.value, 'selected-older-answer')
  assert.doesNotMatch(state.draft.value, /请描述/)
  await actions.sendMessage()
  assert.equal(calls[0].sourceMessageId, 'selected-older-answer')
  assert.equal(calls[0].intent, 'resource_generation')
  assert.equal(state.resourceSourceMessageId.value, '')
  const onSwitch = source.slice(source.indexOf('watch(() => chatStore.activeConversationId'), source.indexOf('const latestAssistant'))
  state.resourceSourceMessageId.value = 'previous-conversation-answer'
  vm.runInNewContext(onSwitch, { ...state, attachmentsCollapsed: { value: true }, watch: (_, callback) => callback() })
  assert.equal(state.resourceSourceMessageId.value, '')
})

test('resource submission survives offline refresh and retries the same selected answer without SSE', async () => {
  const storeSource = readFileSync(new URL('../src/stores/chat.js', import.meta.url), 'utf8')
  const body = storeSource.slice(storeSource.indexOf('function operationKey(')).replace('export const useChatStore', 'const useChatStore')
  const saved = new Map([['edumatrix_username', 'learner-a']]), timers = new Map(), calls = []
  let nextTimer = 0, failureStatus = 0, fail = true
  const conversation = { id: 'chat', title: '课程问答', messages: [], attachments: [] }
  const options = vm.runInNewContext(`${body}; useChatStore`, {
    defineStore: (_, value) => value, errorMessageText: value => String(value),
    localStorage: { getItem: key => saved.get(key), setItem: (key, value) => saved.set(key, value), removeItem: key => saved.delete(key) },
    setTimeout: (callback, delay) => { const id = ++nextTimer; timers.set(id, { callback, delay }); return id },
    clearTimeout: id => timers.delete(id), getChatConversation: async () => conversation,
    createChatMessage: async (_, request) => {
      calls.push(JSON.parse(JSON.stringify(request)))
      if (fail) throw { message: 'connection lost', response: { status: failureStatus } }
      return { conversation, userMessage: { id: 'user', role: 'user', sequence: 1, idempotencyKey: request.idempotency_key },
        assistantMessage: { id: 'assistant', role: 'assistant', status: 'completed', sequence: 2,
          resourceJobId: 'original-job', resourceAutomation: { state: 'queued' } } }
    },
  })
  const makeStore = () => Object.assign(options.state(), options.actions, { activeConversationId: 'chat',
    activeConversation: conversation, startStream() { throw new Error('A resource POST must not require SSE') } })
  const first = makeStore()
  await assert.rejects(first.sendMessage({ content: '原数据生成练习', intent: 'resource_generation',
    resourceTypes: ['handout', 'quiz'], sourceMessageId: 'older-answer' }))
  assert.ok([...timers.values()].some(timer => timer.delay === 2000))
  assert.equal(await first.sendMessage({ content: '重复点击', intent: 'resource_generation' }), null)
  first.cleanup()
  const restored = makeStore()
  await restored.openConversation('chat')
  assert.equal(restored.pendingSend.source_message_id, 'older-answer')
  fail = false
  await [...timers.values()].find(timer => timer.delay === 2000).callback()
  assert.equal(calls.length, 2)
  assert.deepEqual(calls[1], calls[0])
  assert.equal(restored.pendingSend, null)
  assert.equal(restored.messages.at(-1).resourceJobId, 'original-job')
  assert.equal(saved.size, 1)
  restored.cleanup()

  // Credentials/credits errors stay pending without an automatic probe loop.
  fail = true; failureStatus = 402; timers.clear()
  const unavailable = makeStore()
  await assert.rejects(unavailable.sendMessage({ content: '资源', intent: 'resource_generation', resourceTypes: ['quiz'] }))
  assert.equal(timers.size, 0)
  const afterReload = makeStore()
  await afterReload.openConversation('chat')
  assert.ok(afterReload.pendingSend)
  assert.equal(timers.size, 0)
})

test('file-picker completion during a conversation change cannot send a file into the old conversation', async () => {
  const choose = source.slice(source.indexOf('async function chooseFiles('), source.indexOf('async function retryAttachment('))
  const calls = [], localError = { value: '' }, conversationBusy = { value: true }
  const context = { conversationBusy, localError, preferences: { imageAnalysis: true },
    chatStore: { uploadAttachment: file => calls.push(file.name) } }
  const select = vm.runInNewContext(`${choose}; chooseFiles`, context)
  await select({ target: { files: [{ name: 'notes.txt', type: 'text/plain' }], value: 'notes.txt' } })
  assert.deepEqual(calls, [])
  assert.match(localError.value, /重新选择附件/)
  conversationBusy.value = false
  await select({ target: { files: [{ name: 'notes.txt', type: 'text/plain' }], value: 'notes.txt' } })
  assert.deepEqual(calls, ['notes.txt'])
})
function query(conversation) {
  return JSON.parse(JSON.stringify(vm.runInNewContext(`${queryFunction}; conversationQuery(conversation)`, {
    conversation, isInternalPath: value => typeof value === 'string' && value.startsWith('/') && !value.startsWith('//'),
  })))
}

test('switching to a new course or general chat cannot carry the previous resource URL', () => {
  assert.deepEqual(query({ id: 'new-chat', courseIds: ['new-course'], messages: [] }), {
    conversation_id: 'new-chat', course_id: 'new-course', course_ids: 'new-course',
  })
  assert.deepEqual(query({ id: 'general-chat', courseIds: [], messages: [] }), { conversation_id: 'general-chat' })
})

test('opening history restores the latest question material and exact selected version', () => {
  const conversation = { id: 'history', courseIds: ['course-b'], messages: [
    { role: 'user', contextRefs: [{ context: { courseId: 'course-a', resourceId: 'old-resource' } }] },
    { role: 'user', contextRefs: [{ context: { courseId: 'course-b', resourceId: 'map', resourceVersionId: 'version-2', resourcePartId: 'node-2' } }], returnTo: '/workspace/path' },
    { role: 'assistant', content: 'explanation' },
  ] }
  assert.deepEqual(query(conversation), {
    conversation_id: 'history', course_id: 'course-b', course_ids: 'course-b',
    resource_id: 'map', version_id: 'version-2', resource_part_id: 'node-2', return_to: '/workspace/path',
  })
  conversation.courseIds = []
  assert.deepEqual(query(conversation), { conversation_id: 'history' })
})

test('ordinary follow-up keeps all explicitly selected documents, including after history restoration', () => {
  const conversation = { id: 'scoped-chat', courseIds: ['course'], messages: [{ role: 'user', contextRefs: [
    { context: { courseId: 'course', sourceRefId: 'source-a' } },
    { context: { courseId: 'course', sourceRefId: 'source-b' } },
  ] }] }
  const restored = query(conversation)
  assert.equal(restored.source_ref_ids, 'source-a,source-b')
  assert.equal(restored.source_ref_id, undefined)
  const code = source.slice(source.indexOf('const outgoingContextRefs = computed('), source.indexOf('const outgoingReturnTo = computed('))
  const contexts = vm.runInNewContext(`${code}; outgoingContextRefs.value`, {
    computed: fn => ({ get value() { return fn() } }),
    effectiveCourseIds: { value: ['course'] },
    outgoingContextRef: { value: { courseId: 'course', sourceRefId: 'stale-source', knowledgePointId: 'point' } },
    routeSourceRefIds: { value: restored.source_ref_ids.split(',') },
  })
  assert.deepEqual(JSON.parse(JSON.stringify(contexts)), [
    { courseId: 'course', sourceRefId: 'source-a', knowledgePointId: 'point' },
    { courseId: 'course', sourceRefId: 'source-b', knowledgePointId: 'point' },
  ])
})

test('a fresh course question cannot inherit the resource open in another page', () => {
  const previous = source.slice(source.indexOf('const conversationContextRef = computed('), source.indexOf('const currentKnowledgePointTitle = computed('))
  const outgoing = source.slice(source.indexOf('const outgoingContextRef = computed('), source.indexOf('const outgoingContextRefs = computed('))
  const build = (messages, query = { knowledge_point_id: 'point', source_ref_id: 'source' }) => vm.runInNewContext(`${previous}; ${outgoing}; outgoingContextRef.value`, {
    computed: fn => ({ get value() { return fn() } }), messages: { value: messages },
    currentCourseId: { value: 'course' }, route: { query },
    quizResourceId: { value: '' }, quizSourceRefs: { value: [] },
    courseContext: { contextRef: { courseId: 'course', resourceId: 'unrelated-code', resourceVersionId: 'old-version' } },
  })
  assert.equal(build([]).resourceId, null)
  assert.equal(build([]).resourceVersionId, null)
  assert.equal(build([]).sourceRefId, 'source')
  const history = [{ role: 'user', contextRefs: [{ context: {
    courseId: 'course', knowledgePointId: 'old-point', taskId: 'old-task',
    resourceId: 'selected-code', resourceVersionId: 'selected-version', sourceRefId: 'old-source',
  } }] }]
  const followup = build(history, {})
  assert.equal(followup.resourceId, 'selected-code')
  assert.equal(followup.resourceVersionId, 'selected-version')
  for (const entry of [
    { knowledge_point_id: 'point', source_ref_id: 'source' },
    { intent: 'resource_generation', knowledge_point_id: 'point', source_ref_ids: 'source' },
  ]) {
    const fresh = build(history, entry)
    assert.equal(fresh.knowledgePointId, 'point')
    assert.equal(fresh.taskId, null)
    assert.equal(fresh.resourceId, null)
    assert.equal(fresh.resourceVersionId, null)
    assert.notEqual(fresh.sourceRefId, 'old-source')
  }
  const path = build(history, { intent: 'path_bundle', knowledge_point_id: 'point', task_id: 'new-task' })
  assert.equal(path.taskId, 'new-task')
  assert.equal(path.resourceId, null)
})

test('a chat resource opens in its own question course, task and frozen version', () => {
  const open = source.slice(source.indexOf('function openResourceLink('), source.indexOf('function openReturnPath('))
  const calls = []
  vm.runInNewContext(`${open}; openResourceLink(link, message)`, {
    link: { route: '/workspace/resources/handouts/lesson', resourceVersionId: 'version-2' },
    message: { contextRefs: [{ context: { courseId: 'original-course', knowledgePointId: 'point', taskId: 'path-task' } }] },
    currentCourseId: { value: 'other-course' },
    isInternalPath: value => value.startsWith('/'),
    router: { resolve: path => ({ path, query: {} }), push: value => calls.push(value) },
  })
  assert.equal(calls[0].query.course_id, 'original-course')
  assert.equal(calls[0].query.knowledge_point_id, 'point')
  assert.equal(calls[0].query.task_id, 'path-task')
  assert.equal(calls[0].query.version_id, 'version-2')
})
