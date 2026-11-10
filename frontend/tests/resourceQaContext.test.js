import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import { ref } from 'vue'
import * as Vue from 'vue'
import { compile } from '@vue/compiler-dom'
import { parse } from '@vue/compiler-sfc'
import { renderToString } from '@vue/server-renderer'

const source = readFileSync(new URL('../src/components/ResourceFloatingQa.vue', import.meta.url), 'utf8')
const functions = source.slice(source.indexOf('function contextRefs()'), source.indexOf('async function retry()'))

test('a failed resource answer with no body still renders its saved process and revision history', async () => {
  const template = parse(source).descriptor.template.content
  const render = new Function('Vue', compile(template, { mode: 'function' }).code)(Vue)
  const history = [{ attempt: 1, revision: { before: '原稿', after: '保留稿', decision: 'unverified' } }]
  let received
  let bodyRendered = false
  const state = { open: true, resourceTitle: '测试资源', restoring: false, error: '', assistantFailure: '尚未完成核对',
    answer: '', sending: false, audit: { status: 'failed' }, runEvents: [], claims: [], sourceRefs: [],
    assistant: { streamCheckpoint: { answerRevisionHistory: history } }, route: { fullPath: '/workspace/resources' },
    question: '', chatStore: {}, userMessage: value => value, retry() {}, send() {}, emit() {} }
  const app = Vue.createSSRApp({ render, setup: () => state })
  const icon = { render: () => null }
  for (const name of ['MessageSquareText', 'X', 'AlertCircle', 'LoaderCircle', 'Send']) app.component(name, icon)
  app.component('AgentTimeline', { props: ['answerRevisionHistory'], setup(props) {
    received = props.answerRevisionHistory
    return () => Vue.h('span', '已保存的讲解过程')
  } })
  app.component('IncrementalMarkdownRenderer', { setup() { bodyRendered = true; return () => Vue.h('p') } })
  const html = await renderToString(app)
  assert.match(html, /查看回答过程/)
  assert.match(html, /已保存的讲解过程/)
  assert.deepEqual(received, history)
  assert.equal(bodyRendered, false)
})

test('resource question selects current video and creates a new conversation when its segment changes', async () => {
  const sent = []
  const saved = new Map()
  let conversations = 0
  const props = { courseId: 'course', resourceId: 'video', resourceVersionId: 'v1', resourcePartId: 'second-video',
    sourceRefIds: ['source-two'], resourceRefs: [], resourceSegmentId: '', resourceTitle: '条件筛选' }
  const state = { props, conversationScope: ref(''), conversationId: ref(''), assistantId: ref(''),
    question: ref('我正在看哪一条？'), sending: ref(false), requesting: ref(false), error: ref(''), nextTick: async () => {},
    writePreference: (key, value) => saved.set(key, value),
    chatStore: {
      activeConversation: null,
      async createConversation() { this.activeConversation = { id: `chat-${++conversations}` } },
      async sendMessage(value) { sent.push(value); return { assistantMessage: { id: `answer-${sent.length}` } } },
    },
  }
  const ctx = vm.createContext(state)
  vm.runInContext(functions, ctx)
  // The production computed is reactive to Vue props; this fixture recomputes from mutable test inputs.
  Object.defineProperty(state, 'scope', { get: () => ({ value: JSON.stringify(ctx.contextRefs()) }) })
  Object.defineProperty(state, 'conversationKey', { get: () => ({ value: 'edumatrix:resource-qa:' + state.scope.value }) })
  await ctx.send()
  assert.equal(sent[0].contextRefs[0].resourcePartId, 'second-video')
  assert.equal(sent[0].contextRefs[0].sourceRefId, 'source-two')
  assert.equal(saved.get(state.conversationKey.value), 'chat-1')
  state.question.value = '继续说明'
  await ctx.send()
  assert.equal(conversations, 1)
  props.resourceSegmentId = 'filter-step'
  state.question.value = '这一段讲什么？'
  await ctx.send()
  assert.equal(conversations, 2)
  assert.equal(sent[2].contextRefs[0].resourceSegmentId, 'filter-step')
  props.resourcePartId = 'first-video'
  props.resourceSegmentId = ''
  state.question.value = '当前视频名称？'
  await ctx.send()
  assert.equal(conversations, 3)
  assert.equal(sent[3].contextRefs[0].resourcePartId, 'first-video')
  assert.equal(sent[3].contextRefs[0].resourceSegmentId, null)
})
