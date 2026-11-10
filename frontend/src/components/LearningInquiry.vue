<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { api, authConfig, request } from '../api/common.js'
import { submitM5AssessmentAttempt } from '../api/m5.js'
import { userMessage } from '../services/errorTranslator.js'
import IncrementalMarkdownRenderer from './IncrementalMarkdownRenderer.vue'

const props = defineProps({ attemptId: { type: String, required: true } })
const saved = ref(null), response = ref(''), busy = ref(false), error = ref('')
const choice = ref(''), attemptKey = ref('')
let revision = 0
let pollHandle = null
const preparing = computed(() => ['queued', 'running', 'retry_wait', 'waiting_configuration'].includes(saved.value?.generation?.automation?.state))
const preparingMessage = computed(() => saved.value?.generation?.automation?.message || '正在准备…')
function schedulePoll() {
  if (pollHandle) clearTimeout(pollHandle)
  if (!preparing.value) return
  const current = revision
  const url = endpoint()
  pollHandle = setTimeout(async () => {
    try {
      const value = await request(api.get(url, authConfig()))
      if (current !== revision) return
      saved.value = value
      if (value.response) response.value = value.response
    } catch { /* A disconnected observer does not interrupt the saved job. */ }
    if (current === revision) schedulePoll()
  }, 2500)
}
function endpoint() { return `/v1/m5/assessment/attempts/${encodeURIComponent(props.attemptId)}/inquiry` }
async function load() {
  const current = ++revision
  if (pollHandle) clearTimeout(pollHandle)
  saved.value = null; response.value = ''; choice.value = ''; error.value = ''; busy.value = false
  try {
    const value = await request(api.get(endpoint(), authConfig()))
    if (current !== revision) return
    saved.value = value; response.value = value.response || ''
    choice.value = value.feedback?.next_task?.latest_attempt?.answer?.choice || ''
    schedulePoll()
  } catch (exception) { if (current === revision) error.value = userMessage(exception) }
}
watch(() => props.attemptId, load, { immediate: true })
async function run(action) {
  const current = revision
  busy.value = true; error.value = ''
  try { const value = await action(); if (current === revision) { saved.value = value; schedulePoll() } }
  catch (exception) { if (current === revision) error.value = userMessage(exception) }
  finally { if (current === revision) busy.value = false }
}
onBeforeUnmount(() => { revision += 1; if (pollHandle) clearTimeout(pollHandle) })
function start() { return run(() => request(api.post(endpoint(), {}, authConfig()))) }
function submit() { return run(() => request(api.post(`${endpoint()}/answer`, { response: response.value.trim() }, authConfig()))) }
async function practice() {
  await run(async () => {
    if (!attemptKey.value) attemptKey.value = `inquiry-practice-${crypto.randomUUID()}`
    await submitM5AssessmentAttempt({ question_version_id: saved.value.feedback.next_task.question_version_id,
      idempotency_key: attemptKey.value, mode: 'practice', answer: { choice: choice.value } })
    attemptKey.value = ''
    return request(api.get(endpoint(), authConfig()))
  })
}
</script>

<template>
  <section class="learning-inquiry" data-testid="learning-inquiry">
    <p v-if="preparing" role="status">{{ preparingMessage }}</p>
    <button v-if="!saved?.question && !preparing" type="button" :disabled="busy" @click="start">{{ busy ? '正在准备追问…' : '找出这次卡在哪' }}</button>
    <template v-else-if="saved?.question">
      <p class="inquiry-question">{{ saved.question }}</p>
      <template v-if="!saved.feedback">
        <textarea v-model="response" aria-label="我的判断过程" rows="3" :disabled="busy || preparing || !!saved.response" />
        <button v-if="!preparing" type="button" :disabled="busy || !response.trim()" @click="submit">{{ busy ? '正在整理反馈…' : saved.response ? '继续获取反馈' : '保存并继续' }}</button>
      </template>
      <template v-else>
        <p class="learner-response">{{ saved.response }}</p>
        <IncrementalMarkdownRenderer :text="saved.feedback.feedback" preserve-content />
        <div class="next-practice">
          <IncrementalMarkdownRenderer :text="saved.feedback.next_task.prompt" preserve-content />
          <fieldset :disabled="busy"><legend class="sr-only">选择一个答案</legend>
            <label v-for="(option, index) in saved.feedback.next_task.options" :key="index">
              <input v-model="choice" type="radio" :value="String.fromCharCode(65 + index)" />
              <span>{{ String.fromCharCode(65 + index) }}. {{ option.replace(/^[A-Z][.、)\s]+/, '') }}</span>
            </label>
          </fieldset>
          <button type="button" :disabled="busy || !choice" @click="practice">{{ busy ? '正在保存…' : '提交练习' }}</button>
          <template v-if="saved.feedback.next_task.latest_attempt">
            <p>{{ saved.feedback.next_task.latest_attempt.correct ? '回答正确' : '再想一想' }}</p>
            <IncrementalMarkdownRenderer :text="saved.feedback.next_task.explanation" preserve-content />
          </template>
        </div>
      </template>
    </template>
    <p v-if="error" role="alert">{{ error }}</p>
  </section>
</template>

<style scoped>
.learning-inquiry { margin: 20px 24px; color: var(--color-text, var(--color-text)); line-height: 1.7; }
.inquiry-question { font-weight: 600; }
.learner-response { color: var(--color-text-muted, var(--color-text-muted)); padding-left: 12px; border-left: 2px solid var(--color-accent, #9d7772); }
textarea { display: block; width: 100%; box-sizing: border-box; margin-bottom: 12px; padding: 10px 12px; border: 1px solid #cdd3d6; border-radius: 6px; background: var(--color-surface, #faf8f5); color: inherit; font: inherit; resize: vertical; }
button { min-height: 38px; padding: 7px 14px; border: 1px solid #cdd3d6; border-radius: 6px; background: var(--color-surface, #faf8f5); color: inherit; font: inherit; cursor: pointer; }
button:disabled { opacity: .6; cursor: default; }
.next-practice { margin-top: 24px; }
fieldset { border: 0; padding: 0; margin: 12px 0; }
label { display: flex; align-items: baseline; gap: 10px; padding: 6px 0; cursor: pointer; }
.sr-only { position: absolute; width: 1px; height: 1px; overflow: hidden; clip-path: inset(50%); }
</style>
