<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import { AlertCircle, LoaderCircle, MessageSquareText, Send, X } from '@lucide/vue'
import AgentTimeline from './AgentTimeline.vue'
import IncrementalMarkdownRenderer from './IncrementalMarkdownRenderer.vue'
import { useChatStore } from '../stores/chat'

const props = defineProps({
  open: { type: Boolean, default: false },
  courseId: { type: String, default: '' },
  knowledgePointId: { type: String, default: '' },
  resourceId: { type: String, default: '' },
  resourceTitle: { type: String, default: '当前资源' },
  sourceRefIds: { type: Array, default: () => [] },
})
const emit = defineEmits(['close'])
const chatStore = useChatStore()
const question = ref('')
const error = ref('')
const assistantId = ref('')
const requesting = ref(false)
const sending = computed(() => requesting.value || chatStore.sending)
const assistant = computed(() => chatStore.messages.find(item => item.id === assistantId.value) || null)
const answer = computed(() => assistant.value?.content || '')
const audit = computed(() => assistant.value?.agentAudit || assistant.value?.streamCheckpoint?.agentAudit || null)
const runEvents = computed(() => assistant.value?.runEvents || assistant.value?.streamCheckpoint?.runEvents || [])
const claims = computed(() => assistant.value?.claims || assistant.value?.streamCheckpoint?.claims || [])
const sourceRefs = computed(() => assistant.value?.sourceRefs || [])
const assistantFailure = computed(() => assistant.value?.failure?.message || '')

function contextRefs() {
  return [{
    courseId: props.courseId || null,
    knowledgePointId: props.knowledgePointId || null,
    resourceId: props.resourceId || null,
    sourceRefId: props.sourceRefIds[0] || null,
  }].filter(item => item.courseId)
}

async function prepareConversation() {
  if (!props.courseId) throw new Error('当前资源没有课程上下文')
  if (chatStore.activeConversation?.courseId !== props.courseId) {
    await chatStore.createConversation({ courseId: props.courseId, title: `${props.resourceTitle} · 资源内问答` })
  }
}

async function send() {
  const content = question.value.trim()
  if (!content || sending.value) return
  error.value = ''
  requesting.value = true
  try {
    await prepareConversation()
    const pair = await chatStore.sendMessage({
      content,
      contextRefs: contextRefs(),
      intent: 'course_qa',
      idempotencyKey: `resource-qa-${props.resourceId || 'resource'}-${Date.now()}`,
    })
    assistantId.value = pair?.assistantMessage?.id || ''
    question.value = ''
    await nextTick()
  } catch (exception) {
    error.value = exception?.message || '提问失败，可重试。'
  } finally {
    requesting.value = false
  }
}

async function retry() {
  if (sending.value) return
  error.value = ''
  requesting.value = true
  try {
    if (assistantId.value) {
      await chatStore.continueResponse(assistantId.value)
    } else {
      const pair = await chatStore.retryPendingMessage()
      assistantId.value = pair?.assistantMessage?.id || ''
    }
    question.value = ''
  } catch (exception) {
    error.value = exception?.message || '重试失败，请稍后再试。'
  } finally {
    requesting.value = false
  }
}

watch(() => props.open, value => {
  if (value) error.value = ''
})
</script>

<template>
  <div v-if="open" class="resource-qa-layer" data-testid="resource-floating-qa">
    <section class="resource-qa-panel" role="dialog" aria-modal="true" aria-labelledby="resource-qa-title">
      <header>
        <div><span><MessageSquareText :size="16" />资源内问答</span><h2 id="resource-qa-title">{{ resourceTitle }}</h2></div>
        <button type="button" title="关闭问答" @click="emit('close')"><X :size="18" /></button>
      </header>
      <p class="resource-qa-context">可以继续追问当前内容，回答会留在这个学习页面。</p>
      <div v-if="error || assistantFailure" class="resource-qa-error" role="alert">
        <AlertCircle :size="16" />
        <span>{{ error || assistantFailure }}</span>
        <button v-if="assistantFailure || chatStore.pendingSend" type="button" class="resource-qa-retry" :disabled="sending" @click="retry">重试</button>
      </div>
      <div v-if="answer || sending" class="resource-qa-answer" aria-live="polite">
        <div v-if="sending && !answer" class="resource-qa-loading"><LoaderCircle :size="16" class="spin" />智能体正在协作回答…</div>
        <IncrementalMarkdownRenderer v-else :text="answer" />
        <details v-if="audit || runEvents.length" class="resource-qa-process">
          <summary>查看回答过程</summary>
          <AgentTimeline
            :audit="audit"
            :run-events="runEvents"
            :claims="claims"
            :source-refs="sourceRefs"
            compact
          />
        </details>
      </div>
      <form class="resource-qa-composer" @submit.prevent="send">
        <textarea v-model="question" rows="3" :disabled="sending" placeholder="围绕当前资源提问，例如：这一步为什么这样做？" />
        <button type="submit" :disabled="sending || !question.trim()"><LoaderCircle v-if="sending" :size="16" class="spin" /><Send v-else :size="16" />发送</button>
      </form>
    </section>
  </div>
</template>

<style scoped>
.resource-qa-layer{position:fixed;inset:0;z-index:40;display:flex;align-items:flex-end;justify-content:flex-end;padding:24px;background:rgba(6,20,27,.18)}
.resource-qa-panel{width:min(440px,100%);max-height:min(720px,calc(100vh - 48px));overflow:auto;padding:18px;border:1px solid var(--color-border-strong);border-radius:12px;background:var(--color-surface);box-shadow:0 18px 60px rgba(6,20,27,.2)}
.resource-qa-panel header{display:flex;align-items:flex-start;justify-content:space-between;gap:16px}.resource-qa-panel header span{display:flex;align-items:center;gap:6px;color:var(--color-text-secondary);font-size:13px}.resource-qa-panel h2{margin:6px 0 0;font-size:19px;line-height:1.35}.resource-qa-panel header button{display:grid;width:32px;height:32px;place-items:center;border:1px solid var(--color-border);border-radius:6px;background:var(--color-surface);color:var(--color-text-secondary);cursor:pointer}
.resource-qa-context{margin:12px 0 0;color:var(--color-text-secondary);font-size:14px;line-height:1.5}.resource-qa-error{display:flex;align-items:flex-start;gap:7px;margin-top:12px;padding:9px;border:1px solid #e8caca;border-radius:6px;background:var(--color-danger-soft);color:var(--color-danger);font-size:14px}.resource-qa-error>span{min-width:0;flex:1;line-height:1.5}.resource-qa-retry{min-height:28px;flex:0 0 auto;padding:0 9px;border:1px solid currentColor;border-radius:5px;background:#fff;color:inherit;font-size:14px;cursor:pointer}.resource-qa-retry:disabled{cursor:default;opacity:.55}.resource-qa-answer{margin-top:14px;padding:14px;border:1px solid var(--color-border);border-radius:8px;background:var(--color-surface-subtle)}.resource-qa-process{margin-top:14px;border-top:1px solid var(--color-border);padding-top:10px}.resource-qa-process summary{color:var(--color-text-secondary);font-size:14px;cursor:pointer}.resource-qa-loading{display:flex;align-items:center;gap:7px;color:var(--color-text-secondary);font-size:14px}.resource-qa-composer{display:grid;gap:9px;margin-top:14px}.resource-qa-composer textarea{width:100%;resize:vertical;box-sizing:border-box;padding:10px;border:1px solid var(--color-border-strong);border-radius:7px;background:#fff;color:var(--color-text);font:inherit;line-height:1.5}.resource-qa-composer button{display:inline-flex;min-height:36px;align-items:center;justify-content:center;gap:6px;justify-self:end;padding:0 13px;border:1px solid var(--color-accent);border-radius:6px;background:var(--color-accent);color:#fff;font-weight:650;cursor:pointer}.resource-qa-composer button:disabled{cursor:not-allowed;opacity:.55}.spin{animation:spin .9s linear infinite}@keyframes spin{to{transform:rotate(360deg)}}
</style>
