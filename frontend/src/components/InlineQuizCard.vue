<script setup>
import { userMessage } from '../services/errorTranslator.js'
import { computed, ref, watch } from 'vue'
import {
  AlertCircle, CheckCircle2, ChevronDown, ChevronUp, ExternalLink,
  LoaderCircle, MessageSquareText, RotateCcw, Send, XCircle,
} from '@lucide/vue'
import { submitM5AssessmentAttempt } from '../api'
import IncrementalMarkdownRenderer from './IncrementalMarkdownRenderer.vue'
import LearningInquiry from './LearningInquiry.vue'

const props = defineProps({
  question: { type: Object, required: true },
  resourceId: { type: String, default: '' },
  resourceVersionId: { type: String, default: '' },
  initialAttempt: { type: Object, default: null },
  position: { type: Number, default: 1 },
  total: { type: Number, default: 1 },
  sourceRefs: { type: Array, default: () => [] },
  compact: { type: Boolean, default: false },
})

const emit = defineEmits(['submitted', 'follow-up', 'open-source'])

const selectedChoice = ref('')
const feedback = ref(null)
const submitting = ref(false)
const error = ref('')
const revising = ref(false)
const followUpOpen = ref(false)
const followUpText = ref('')
const pendingIdempotencyKey = ref('')
const visibleHints = ref(0)
const hints = computed(() => (props.question?.hints || []).filter(item => typeof item === 'string' && item.trim()))
function hintStorageKey() {
  const owner = localStorage.getItem('edumatrix_username') || localStorage.getItem('edumatrix_student_id') || ''
  return `edumatrix:quiz-hints:${owner}:${props.resourceId}:${props.question.id}`
}
function revealHint() {
  visibleHints.value = Math.min(hints.value.length, visibleHints.value + 1)
  try { localStorage.setItem(hintStorageKey(), String(visibleHints.value)) } catch { /* reading remains available */ }
}

const contentIssue = computed(() => {
  if (props.question?.content_issue) return props.question.content_issue
  if (!String(props.question?.prompt || '').trim()) return '题目题干未保存，请重新生成这份测验资源。'
  const options = Array.isArray(props.question?.options) ? props.question.options : []
  if (options.length < 2) return '题目选项正文未保存，请重新生成这份测验资源。'
  const missingBody = options.some((option, index) => {
    const text = optionText(option, index)
    return !text || text.toUpperCase() === optionLabel(option, index)
  })
  return missingBody ? '题目选项正文未保存，请重新生成这份测验资源。' : ''
})
const available = computed(() => props.question?.status !== 'unavailable' && !contentIssue.value)
const unavailableReason = computed(() => props.question?.error || contentIssue.value || '题目版本不存在，请返回资源中心重新生成。')
const supported = computed(() => props.question?.question_type === 'single_choice')
const canSubmit = computed(() => available.value && supported.value && selectedChoice.value && !submitting.value)
const correctChoice = computed(() => feedback.value?.correct_answer?.choice || '')
const explanation = computed(() => feedback.value?.answer_explanation || feedback.value?.grading?.feedback || '')

function optionLabel(option, index) {
  const explicit = option && typeof option === 'object' ? String(option.label || '').trim() : ''
  if (/^[A-Z]$/i.test(explicit)) return explicit.toUpperCase()
  const value = optionValue(option)
  return /^[A-Z][.)、:\s]/i.test(value) ? value.slice(0, 1).toUpperCase() : String.fromCharCode(65 + index)
}

function optionText(option, index) {
  const value = optionValue(option)
  const label = optionLabel(value, index)
  return value.replace(new RegExp(`^${label}[.)、:\\s]+`, 'i'), '').trim() || value
}

function optionValue(option) {
  if (option && typeof option === 'object') {
    return String(option.text || option.content || option.option || option.value || '').trim()
  }
  return String(option || '').trim()
}

function resetFromQuestion() {
  feedback.value = props.initialAttempt || props.question?.latest_attempt || null
  selectedChoice.value = feedback.value?.answer?.choice || ''
  error.value = ''
  revising.value = false
  followUpOpen.value = false
  followUpText.value = ''
  pendingIdempotencyKey.value = ''
  let saved = 0
  try { saved = Number(localStorage.getItem(hintStorageKey())) || 0 } catch { /* start with folded hints */ }
  visibleHints.value = Math.min(hints.value.length, Math.max(0, saved, Number(feedback.value?.answer?.hints_viewed) || 0))
}

watch(() => [props.question?.id, props.initialAttempt?.id], resetFromQuestion, { immediate: true })

function message(exception) {
  const detail = exception?.response?.data?.detail || exception?.detail
  return detail?.message || (typeof detail === 'string' ? detail : '') || exception?.message || '提交失败，请保留当前选择后重试。'
}

function newIdempotencyKey() {
  const suffix = globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(36).slice(2, 9)}`
  return `quiz-practice-${props.question.id}-${suffix}`
}

function attemptIdempotencyKey() {
  if (!pendingIdempotencyKey.value) pendingIdempotencyKey.value = newIdempotencyKey()
  return pendingIdempotencyKey.value
}

async function submit() {
  if (!canSubmit.value) return
  submitting.value = true
  error.value = ''
  try {
    const result = await submitM5AssessmentAttempt({
      question_version_id: props.question.id,
      idempotency_key: attemptIdempotencyKey(),
      mode: 'practice',
      answer: { choice: selectedChoice.value,
        ...(props.resourceVersionId ? { resource_version_id: props.resourceVersionId } : {}),
        ...(visibleHints.value ? { used_hints: true, hints_viewed: visibleHints.value } : {}) },
    })
    feedback.value = result
    revising.value = false
    pendingIdempotencyKey.value = ''
    emit('submitted', result)
  } catch (exception) {
    error.value = message(exception)
  } finally {
    submitting.value = false
  }
}

function revise() {
  revising.value = true
  error.value = ''
}

function submitFollowUp() {
  const text = followUpText.value.trim()
  if (!text) return
  emit('follow-up', {
    text,
    question: props.question,
    attempt: feedback.value,
    resourceId: props.resourceId,
  })
}

function optionState(option, index) {
  if (!feedback.value || revising.value) return ''
  const label = optionLabel(option, index)
  if (label === correctChoice.value) return 'correct'
  if (label === selectedChoice.value && feedback.value.correct === false) return 'incorrect'
  return ''
}
</script>

<template>
  <section class="inline-quiz" :class="{ 'inline-quiz--compact': compact }" data-testid="inline-quiz-card">
    <header class="quiz-heading">
      <div>
        <span>第 {{ position }} / {{ total }} 题</span>
        <strong v-if="!question.required">补充练习</strong>
      </div>
      <button
        v-if="sourceRefs.length || question.source_ref_ids?.length"
        type="button"
        class="source-button"
        @click="emit('open-source', question.source_ref_ids?.[0] || sourceRefs[0]?.id)"
      >
        <ExternalLink :size="15" />查看来源
      </button>
    </header>

    <div v-if="question.prompt" class="question-prompt" role="heading" aria-level="2"><IncrementalMarkdownRenderer :text="question.prompt" preserve-content /></div>

    <div v-if="!available" class="quiz-unavailable" role="alert">
      <AlertCircle :size="20" />
      <div><strong>这道题暂时不可用</strong><p>{{ unavailableReason }}</p></div>
    </div>

    <div v-else-if="!supported" class="quiz-unavailable" role="alert">
      <AlertCircle :size="20" />
      <div><strong>当前题型尚未接入即时练习卡</strong><p>请在资源历史中选择结构化单选题版本。</p></div>
    </div>

    <template v-else>
      <fieldset class="option-list" :disabled="submitting">
        <legend class="sr-only">选择一个答案</legend>
        <label
          v-for="(option, index) in question.options"
          :key="`${question.id}-${index}`"
          :class="[
            { selected: selectedChoice === optionLabel(option, index) },
            optionState(option, index),
          ]"
        >
          <input v-model="selectedChoice" type="radio" :value="optionLabel(option, index)" @change="error = ''" />
          <span class="option-label">{{ optionLabel(option, index) }}</span>
          <div class="option-text"><IncrementalMarkdownRenderer :text="optionText(option, index)" preserve-content /></div>
          <CheckCircle2 v-if="optionState(option, index) === 'correct'" :size="18" />
          <XCircle v-else-if="optionState(option, index) === 'incorrect'" :size="18" />
        </label>
      </fieldset>

      <section v-if="hints.length" class="learning-hints" aria-label="解题提示">
        <div v-for="(hint, index) in hints.slice(0, visibleHints)" :key="index" class="learning-hint">
          <IncrementalMarkdownRenderer :text="hint" />
        </div>
        <button v-if="visibleHints < hints.length" type="button" class="secondary-action" @click="revealHint">
          {{ visibleHints ? '再看一个提示' : '给我一点提示' }}
        </button>
      </section>

      <p v-if="error" class="quiz-error" role="alert"><AlertCircle :size="17" />{{ userMessage(error) }}</p>

      <div class="quiz-actions">
        <button v-if="feedback && !revising" type="button" class="secondary-action" @click="revise">
          <RotateCcw :size="16" />修改答案
        </button>
        <button type="button" class="primary-action" :disabled="!canSubmit" @click="submit">
          <LoaderCircle v-if="submitting" :size="17" class="spin" />
          <Send v-else :size="17" />
          {{ submitting ? '判分中' : feedback ? '提交新答案' : '提交答案' }}
        </button>
      </div>

    </template>

      <section v-if="feedback" class="feedback-panel" :class="{ 'feedback-panel--wrong': feedback.correct === false }" aria-live="polite">
        <div class="feedback-title">
          <CheckCircle2 v-if="feedback.correct" :size="21" />
          <XCircle v-else :size="21" />
          <div>
            <strong>{{ feedback.practice_kind === 'correction' ? (feedback.correct ? '已订正' : '再想一想') : feedback.correct ? '回答正确' : '这次还不正确' }}</strong>
            <span v-if="feedback.practice_kind === 'correction'">订正已保存，再用新题检查理解。</span>
            <span v-else-if="feedback.answer?.used_hints">这次用了提示。</span>
          </div>
        </div>
        <p v-if="correctChoice"><strong>正确答案：</strong>{{ correctChoice }}</p>
        <div v-if="explanation" class="answer-explanation"><strong>解析：</strong><IncrementalMarkdownRenderer :text="explanation" preserve-content /></div>
      </section>

      <LearningInquiry v-if="feedback?.id && feedback.correct === false && available && !revising && feedback.feedback_policy !== 'after_close'" :key="feedback.id" :attempt-id="feedback.id" />
      <section v-if="feedback && available" class="follow-up-panel">
        <button type="button" class="follow-up-toggle" @click="followUpOpen = !followUpOpen">
          <MessageSquareText :size="17" />继续追问这道题
          <ChevronUp v-if="followUpOpen" :size="16" />
          <ChevronDown v-else :size="16" />
        </button>
        <div v-if="followUpOpen" class="follow-up-form">
          <textarea v-model="followUpText" rows="3" placeholder="例如：为什么另一个选项不成立？" />
          <button type="button" :disabled="!followUpText.trim()" @click="submitFollowUp"><Send :size="16" />继续围绕这道题追问</button>
        </div>
      </section>
  </section>
</template>

<style scoped>
.inline-quiz { width: 100%; min-width: 0; border: 1px solid var(--color-border-strong); border-radius: 8px; background: var(--color-surface); color: var(--color-text); }
.quiz-heading { display: flex; min-height: 48px; align-items: center; justify-content: space-between; gap: 12px; border-bottom: 1px solid #e4e8e9; padding: 0 16px; }
.quiz-heading > div { display: flex; align-items: center; gap: 8px; }
.quiz-heading span, .quiz-heading strong { font-size: 14px; line-height: 1.4; }
.quiz-heading span { color: var(--color-text-muted); }
.quiz-heading strong { border-left: 1px solid var(--color-border-strong); padding-left: 8px; color: var(--color-text); }
.source-button, .secondary-action, .primary-action, .follow-up-toggle, .follow-up-form button { display: inline-flex; min-height: 38px; align-items: center; justify-content: center; gap: 7px; border: 1px solid var(--color-border-strong); border-radius: 8px; padding: 0 11px; background: var(--color-surface); color: var(--color-text); font-size: 14px; cursor: pointer; }
.question-prompt { margin: 0; padding: 24px 24px 18px; color: var(--color-text); font-size: 20px; font-weight: 650; line-height: 1.65; }
.question-prompt :deep(.incremental-md-renderer), .option-text :deep(.incremental-md-renderer) { font-size: inherit; line-height: inherit; }
.question-prompt :deep(.inc-text-block p), .option-text :deep(.inc-text-block p) { margin: 0; }
.answer-explanation { margin-top: 10px; color: var(--color-text-secondary); }
.learning-hints { margin: 0 24px 20px; }
.learning-hint { margin-bottom: 12px; padding-left: 14px; border-left: 2px solid var(--color-accent, #9d7772); color: var(--color-text); }
.learning-hint :deep(.incremental-md-renderer) { font-size: 15px; line-height: 1.7; }
.answer-explanation :deep(.incremental-md-renderer) { font-size: 14px; }
.option-list { display: grid; gap: 9px; margin: 0; border: 0; padding: 0 24px 22px; }
.option-list label { display: grid; min-height: 52px; grid-template-columns: 30px minmax(0, 1fr) 20px; align-items: center; gap: 10px; border: 1px solid #d7dddf; border-radius: 8px; padding: 8px 12px; background: var(--color-surface); color: var(--color-text); cursor: pointer; }
.option-list label:hover { border-color: #81909a; }
.option-list label.selected { border-color: var(--color-text); box-shadow: inset 0 0 0 1px var(--color-text); }
.option-list label.correct { border-color: var(--color-text); background: var(--color-surface-subtle); color: var(--color-text); }
.option-list label.incorrect { border-color: #c77e76; background: var(--color-danger-soft); color: #7b332c; }
.option-list input { position: absolute; opacity: 0; pointer-events: none; }
.option-label { display: grid; width: 28px; height: 28px; place-items: center; border: 1px solid #b8c2c6; border-radius: 50%; color: var(--color-text-secondary); font-size: 14px; font-weight: 700; }
.selected .option-label, .correct .option-label { border-color: var(--color-text); background: var(--color-text); color: #fff; }
.incorrect .option-label { border-color: var(--color-danger); background: var(--color-danger); color: #fff; }
.option-text { min-width: 0; font-size: 15px; line-height: 1.55; }
.quiz-actions { display: flex; align-items: center; justify-content: flex-end; gap: 8px; border-top: 1px solid var(--color-surface-subtle); padding: 14px 24px; }
.primary-action, .follow-up-form button { border-color: var(--color-text); background: var(--color-text); color: #fff; font-weight: 650; }
.primary-action:disabled, .follow-up-form button:disabled { cursor: default; opacity: .46; }
.quiz-error { display: flex; align-items: flex-start; gap: 7px; margin: 0 24px 12px; border: 1px solid #d8aaa5; border-radius: 8px; padding: 10px 12px; background: var(--color-danger-soft); color: var(--color-danger); font-size: 14px; line-height: 1.5; }
.feedback-panel { margin: 0 24px 16px; border-left: 3px solid var(--color-text); padding: 12px 14px; background: var(--color-surface-subtle); }
.feedback-panel--wrong { border-left-color: var(--color-danger); background: var(--color-danger-soft); }
.feedback-title { display: flex; align-items: flex-start; gap: 9px; }
.feedback-title > div { display: grid; gap: 2px; }
.feedback-title strong { font-size: 16px; }
.feedback-title span, .feedback-panel p { color: var(--color-text-secondary); font-size: 14px; line-height: 1.6; }
.feedback-panel p { margin: 10px 0 0; }
.feedback-panel p strong { color: var(--color-text); }
.follow-up-panel { border-top: 1px solid var(--color-surface-subtle); padding: 12px 24px 18px; }
.follow-up-toggle { width: 100%; justify-content: flex-start; border-color: transparent; padding: 0; }
.follow-up-toggle svg:last-child { margin-left: auto; }
.follow-up-form { display: grid; gap: 9px; margin-top: 10px; }
.follow-up-form textarea { min-height: 82px; resize: vertical; border: 1px solid var(--color-border-strong); border-radius: 8px; padding: 10px 12px; color: var(--color-text); font: 14px/1.55 "Source Han Sans SC", "Noto Sans CJK SC", "Microsoft YaHei", sans-serif; }
.follow-up-form button { justify-self: end; }
.quiz-unavailable { display: flex; min-height: 180px; align-items: flex-start; justify-content: center; gap: 10px; padding: 40px 24px; color: var(--color-text-secondary); }
.quiz-unavailable strong { color: var(--color-text); font-size: 16px; }
.quiz-unavailable p { max-width: 48ch; margin: 5px 0 0; font-size: 14px; line-height: 1.6; }
.inline-quiz--compact .question-prompt { padding: 20px 20px 15px; font-size: 18px; }
.inline-quiz--compact .option-list { padding: 0 20px 18px; }
.inline-quiz--compact .quiz-actions { padding: 12px 20px; }
.inline-quiz--compact .feedback-panel { margin-right: 20px; margin-left: 20px; }
.inline-quiz--compact .follow-up-panel { padding-right: 20px; padding-left: 20px; }
.source-button:focus-visible, .secondary-action:focus-visible, .primary-action:focus-visible, .follow-up-toggle:focus-visible, .follow-up-form button:focus-visible, .option-list label:focus-within, .follow-up-form textarea:focus-visible { outline: 2px solid var(--color-text); outline-offset: 2px; }
.spin { animation: spin .8s linear infinite; }
.sr-only { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0, 0, 0, 0); white-space: nowrap; }
@keyframes spin { to { transform: rotate(360deg); } }
</style>
