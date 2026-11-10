<script setup>
import { userMessage } from '../services/errorTranslator.js'
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  ArrowLeft,
  Check,
  CheckCircle2,
  ChevronRight,
  Circle,
  History,
  LoaderCircle,
  Mic,
  RotateCcw,
  Send,
  Square,
} from '@lucide/vue'
import {
  applyFeynmanAction,
  createFeynmanSession,
  getFeynmanSession,
  getFeynmanActionTask,
  listFeynmanSessions,
} from '../api/feynman'
import { getM5Resource } from '../api/m5'
import { readPreference, writePreference } from '../utils/learningPreferenceStorage.js'
import FeynmanEvaluationPanel from '../components/FeynmanEvaluationPanel.vue'
import IncrementalMarkdownRenderer from '../components/IncrementalMarkdownRenderer.vue'
import SpeechDraftInput from '../components/SpeechDraftInput.vue'
import { usePathGeneration } from '../composables/usePathGeneration.js'

const route = useRoute()
const router = useRouter()
const resourceId = computed(() => String(route.params.resourceId || ''))
const requestedSourceVersion = computed(() => String(route.query.version_id || route.query.resource_version_id || ''))
let loadSequence = 0

const loading = ref(true)
const actionPending = ref('')
const error = ref('')
const notice = ref('')
const resource = ref(null)
const session = ref(null)
const sessions = ref([])
const round1Draft = ref('')
const questionDraft = ref('')
const round2Draft = ref('')
const { task: actionTask, busy: actionTaskBusy, connectionError: actionConnectionError,
  accept: acceptActionTask, restore: restoreActionTask, reset: resetActionTask } = usePathGeneration({
  getTask: () => recoverActionTask(), findTask: () => recoverActionTask(),
  onComplete: async (_task, stillCurrent) => {
    const updated = await getFeynmanSession(session.value.session_id)
    if (!stillCurrent()) return
    localStorage.removeItem(storageKey('queued-action'))
    session.value = updated
    actionPending.value = ''
    restoreDrafts()
  },
})

async function recoverActionTask() {
  const sessionId = session.value.session_id
  const pending = JSON.parse(localStorage.getItem(storageKey('queued-action')) || 'null')
  let result = await getFeynmanActionTask(sessionId)
  if (pending && (!result.task || result.task.expected_version < pending.expected_version)) {
    result = await applyFeynmanAction(sessionId, pending)
  }
  if (result.task && !['completed', 'cancelled'].includes(result.task.status)) actionPending.value = result.task.action
  return result
}
const steps = [
  { number: 1, title: '第一次复述' },
  { number: 2, title: '提出疑问' },
  { number: 3, title: '第二次复述' },
  { number: 4, title: '理解变化' },
  { number: 5, title: '应用到后续学习' },
]

const statusStep = {
  draft: 1,
  round1_submitted: 1,
  review1_ready: 1,
  question_pending: 2,
  question_answered: 3,
  round2_submitted: 3,
  comparison_ready: 4,
  applied: 5,
}

const currentStep = computed(() => statusStep[session.value?.status] || 1)
const completedSteps = computed(() => (
  steps.filter(step => step.number <= 3 && step.number < currentStep.value)
))
const canSubmitRound1 = computed(() => round1Draft.value.trim().length >= 40)
const canSubmitQuestion = computed(() => questionDraft.value.trim().length >= 6)
const canSubmitRound2 = computed(() => round2Draft.value.trim().length >= 40)
const resourceTitle = computed(() => (
  session.value?.title
  || resource.value?.title
  || resource.value?.catalog?.artifact?.title
  || '费曼复述'
))
const historicalMaterial = computed(() => Boolean(session.value?.source_resource_version_id
  && resource.value?.history?.current_version_id
  && session.value.source_resource_version_id !== resource.value.history.current_version_id))
const comparison = computed(() => session.value?.comparison || null)

function publicLearningText(value) {
  return String(value || '')
    .replace(/\b(?:f\d+-)?(?:kp|event|trace|run)-[a-z0-9-]{6,}\b/gi, '当前知识点')
    .replace(/\b[a-f0-9]{24,}\b/gi, '')
    .replace(/\b(?:feynman_submitted|code_tests_passed|interactive_model_completed)\b/gi, '已完成学习活动')
}

function message(caught, fallback = '请求失败，请稍后重试。') {
  const value = caught?.response?.data?.detail || caught?.detail
  return value?.message || (typeof value === 'string' ? value : '') || caught?.message || fallback
}

function uniqueKey(prefix) {
  return `${prefix}-${globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(36).slice(2, 10)}`}`
}

function storageKey(field, sessionId = session.value?.session_id) {
  return `edumatrix:feynman:${sessionId || resourceId.value}:${field}`
}

function pendingActionKey(action) {
  const key = storageKey(`pending:${action}:${session.value.version_number}`)
  let value = localStorage.getItem(key)
  if (!value) {
    value = uniqueKey(`feynman-${action}`)
    localStorage.setItem(key, value)
  }
  return { key, value }
}

function restoreDrafts() {
  if (!session.value) return
  round1Draft.value = session.value.round1_text || localStorage.getItem(storageKey('round1')) || ''
  questionDraft.value = session.value.question_answer?.question || localStorage.getItem(storageKey('question')) || ''
  round2Draft.value = session.value.round2_text || localStorage.getItem(storageKey('round2')) || ''
}

function updateRouteSession(current) {
  const query = { ...route.query, session_id: current.session_id,
    version_id: current.source_resource_version_id, resource_version_id: current.source_resource_version_id,
    course_id: current.course_id || undefined }
  if (Object.keys(query).every(key => query[key] === route.query[key])) return
  return router.replace({ query })
}

async function selectSession(sessionId) {
  if (loading.value || actionPending.value || sessionId === session.value?.session_id) return
  await router.replace({ query: { ...route.query, session_id: sessionId } })
}

async function createAttempt(sourceId, sourceVersionId, { fresh = false } = {}) {
  const createStorageKey = `edumatrix:feynman:create:${sourceId}:${sourceVersionId}`
  let idempotencyKey = fresh ? '' : readPreference(createStorageKey)
  if (!idempotencyKey) {
    idempotencyKey = uniqueKey('feynman-session')
    if (!fresh) writePreference(createStorageKey, idempotencyKey)
  }
  return createFeynmanSession(sourceId, idempotencyKey, sourceVersionId)
}

async function loadWorkspace() {
  const sequence = ++loadSequence
  resetActionTask()
  actionPending.value = ''
  const sourceId = resourceId.value
  const requestedVersion = requestedSourceVersion.value
  const requestedId = String(route.query.session_id || '')
  loading.value = true
  error.value = ''
  notice.value = ''
  session.value = null
  resource.value = null
  sessions.value = []
  round1Draft.value = ''
  questionDraft.value = ''
  round2Draft.value = ''
  try {
    const [detail, restored] = await Promise.all([
      getM5Resource(sourceId),
      requestedId ? getFeynmanSession(requestedId) : null,
    ])
    if (sequence !== loadSequence) return
    if (restored && restored.source_resource_id !== sourceId) {
      throw new Error('这次复述属于另一份学习材料，请从原资源或复述历史打开。')
    }
    // A saved session owns its frozen material; a bundle without a session pins its selected version.
    const sourceVersion = restored?.source_resource_version_id || requestedVersion || detail.history?.current_version_id
    if (!sourceVersion || !detail.history?.items?.some(item => item.id === sourceVersion)) {
      throw new Error('这版复述材料暂时无法打开，请从资源历史重新选择。')
    }
    const listing = await listFeynmanSessions(sourceId, sourceVersion)
    if (sequence !== loadSequence) return
    const selected = restored || (listing.items?.length
      ? await getFeynmanSession(listing.items[0].session_id)
      : await createAttempt(sourceId, sourceVersion))
    if (sequence !== loadSequence) return
    resource.value = detail
    session.value = selected
    sessions.value = listing.items || []
    if (!sessions.value.some(item => item.session_id === selected.session_id)) {
      sessions.value.unshift(selected)
    }
    restoreDrafts()
    const savedAction = JSON.parse(localStorage.getItem(storageKey('queued-action')) || 'null')
    if (savedAction) actionPending.value = savedAction.action
    await restoreActionTask({ sessionId: selected.session_id })
    if (sequence !== loadSequence) return
    await updateRouteSession(selected)
  } catch (caught) {
    if (sequence === loadSequence) error.value = message(caught, '费曼复述工作台加载失败。')
  } finally {
    if (sequence === loadSequence) loading.value = false
  }
}

async function runAction(action, text, clearedField) {
  if (!session.value || loading.value || actionPending.value) return
  const sequence = loadSequence
  const targetSessionId = session.value.session_id
  actionPending.value = action
  error.value = ''
  notice.value = ''
  const pending = pendingActionKey(action)
  const background = ['evaluate_round1', 'answer_question', 'evaluate_round2'].includes(action)
  const payload = { action, text: text || null, expected_version: session.value.version_number,
    idempotency_key: pending.value, ...(background ? { background: true } : {}) }
  if (background) localStorage.setItem(storageKey('queued-action'), JSON.stringify(payload))
  try {
    const updated = await applyFeynmanAction(targetSessionId, payload)
    localStorage.removeItem(pending.key)
    if (sequence !== loadSequence) return
    if (updated.task) {
      await acceptActionTask(updated.task)
      return
    }
    session.value = updated
    if (clearedField) localStorage.removeItem(storageKey(clearedField))
    restoreDrafts()
  } catch (caught) {
    if (sequence !== loadSequence) return
    if (caught?.status === 409) {
      localStorage.removeItem(storageKey('queued-action'))
      notice.value = '会话已在其他页面更新，输入内容仍保留。已重新读取最新阶段。'
      try {
        const updated = await getFeynmanSession(targetSessionId)
        if (sequence !== loadSequence) return
        session.value = updated
        restoreDrafts()
      } catch (reloadError) {
        error.value = message(reloadError, '重新加载最新阶段失败。')
      }
    } else if (background && (!caught?.status || caught.status >= 500)) {
      await restoreActionTask({ sessionId: targetSessionId })
    } else {
      if (background) localStorage.removeItem(storageKey('queued-action'))
      error.value = message(caught, '本步骤没有完成，已保存内容和之前阶段均未改变。')
    }
  } finally {
    if (!actionTaskBusy.value && !actionConnectionError.value) actionPending.value = ''
  }
}

async function newAttempt() {
  if (loading.value || actionPending.value || !session.value) return
  const sequence = ++loadSequence
  const sourceId = resourceId.value
  const sourceVersion = session.value.source_resource_version_id
  loading.value = true
  error.value = ''
  notice.value = ''
  try {
    const created = await createAttempt(sourceId, sourceVersion, { fresh: true })
    if (sequence !== loadSequence) return
    session.value = created
    restoreDrafts()
    await updateRouteSession(created)
    const listing = await listFeynmanSessions(sourceId, sourceVersion)
    if (sequence !== loadSequence) return
    sessions.value = listing.items || []
    notice.value = '已新建一次独立复述，之前的记录仍保留在历史中。'
  } catch (caught) {
    if (sequence === loadSequence) error.value = message(caught, '新建复述失败，原记录没有改变。')
  } finally {
    if (sequence === loadSequence) loading.value = false
  }
}

function stepState(number) {
  if (session.value?.status === 'applied') return 'complete'
  if (number < currentStep.value) return 'complete'
  if (number === currentStep.value) return 'current'
  return 'pending'
}

function conclusionLabel(value) {
  return ({ improved: '本轮记录显示理解提升', unchanged: '两轮记录暂未显示变化', lower: '第二轮仍需继续巩固' })[value] || '等待比较'
}

function formatDate(value) {
  if (!value) return '时间未记录'
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit',
  }).format(new Date(value))
}

watch(round1Draft, value => {
  if (session.value?.status === 'draft') localStorage.setItem(storageKey('round1'), value)
})
watch(questionDraft, value => {
  if (session.value?.status === 'question_pending') localStorage.setItem(storageKey('question'), value)
})
watch(round2Draft, value => {
  if (session.value?.status === 'question_answered') localStorage.setItem(storageKey('round2'), value)
})
watch(() => [resourceId.value, requestedSourceVersion.value, route.query.session_id].join('|'), () => {
  const current = session.value
  if (current?.source_resource_id === resourceId.value
    && current.source_resource_version_id === requestedSourceVersion.value
    && current.session_id === String(route.query.session_id || '')) return
  loadWorkspace()
})

onMounted(loadWorkspace)

</script>

<template>
  <main class="feynman-page">
    <header class="page-header">
      <button class="icon-button" type="button" title="返回资源中心" @click="router.push('/workspace/resources')">
        <ArrowLeft :size="19" aria-hidden="true" />
      </button>
      <div class="heading-copy">
        <h1>{{ resourceTitle }}</h1>
        <p v-if="historicalMaterial">正在学习第 {{ session.source_resource_version_number }} 版材料</p>
      </div>
      <button class="secondary-button" type="button" :disabled="loading || Boolean(actionPending)" @click="newAttempt">
        <RotateCcw :size="17" aria-hidden="true" />
        新建复述
      </button>
    </header>

    <section class="progress-panel" aria-label="复述进度">
      <ol class="step-list">
        <li v-for="step in steps" :key="step.number" :class="['step-item', stepState(step.number)]" :aria-current="stepState(step.number) === 'current' ? 'step' : undefined">
          <span class="step-marker" aria-hidden="true">
            <Check v-if="stepState(step.number) === 'complete'" :size="16" />
            <Circle v-else :size="13" />
          </span>
          <span>
            <strong>{{ step.number }}. {{ step.title }}</strong>
          </span>
        </li>
      </ol>
    </section>

    <div v-if="loading" class="state-panel" role="status">
      <LoaderCircle class="spin" :size="22" aria-hidden="true" />
      正在恢复费曼复述记录…
    </div>

    <div v-else-if="error && !session" class="state-panel error-panel" role="alert">
      <strong>当前记录无法打开</strong>
      <span>{{ userMessage(error) }}</span>
      <button class="primary-button" type="button" @click="loadWorkspace">重新加载</button>
    </div>

    <template v-else-if="session">
      <p v-if="actionTaskBusy || actionConnectionError" class="notice" role="status">{{ actionConnectionError || actionTask?.automation?.message }}</p>
      <p v-if="notice" class="notice" role="status">{{ notice }}</p>
      <p v-if="error" class="notice error-notice" role="alert">{{ userMessage(error) }}</p>

      <div class="workspace-grid">
        <section class="main-workspace">
          <article v-if="currentStep === 1" class="stage-panel">
            <div class="section-heading">
              <div>
                <h2>第一次复述</h2>
              </div>
              <span class="status-label">{{ session.status === 'draft' ? '等待复述' : session.status === 'round1_submitted' ? '原文已保存' : '评价已完成' }}</span>
            </div>
            <div class="task-prompt">
              <strong>本轮任务</strong>
              <p>{{ publicLearningText(session.task_prompt) }}</p>
            </div>

            <template v-if="session.status === 'draft'">
            <label class="field-label" for="round1">用自己的话复述</label>
              <textarea id="round1" v-model="round1Draft" rows="11" placeholder="用自己的话说明核心含义、过程、条件、例子和容易误用的情形。" />
              <div class="editor-actions">
                <SpeechDraftInput :key="`round1-${session?.id}`" :disabled="Boolean(actionPending)" @transcript="text => round1Draft += (round1Draft ? '\n' : '') + text" />
                <span v-if="round1Draft.trim().length < 40">至少 40 字</span>
                <button class="primary-button" type="button" :disabled="!canSubmitRound1 || Boolean(actionPending)" @click="runAction('submit_round1', round1Draft, 'round1')">
                  <LoaderCircle v-if="actionPending === 'submit_round1'" class="spin" :size="17" aria-hidden="true" />
                  <Send v-else :size="17" aria-hidden="true" />
                  保存第一次复述
                </button>
              </div>
            </template>

            <template v-else>
              <div class="saved-text">
                <span>第一次原始复述</span>
                <p>{{ session.round1_text }}</p>
              </div>
              <button v-if="session.status === 'round1_submitted'" class="primary-button stage-action" type="button" :disabled="Boolean(actionPending)" @click="runAction('evaluate_round1')">
                <LoaderCircle v-if="actionPending === 'evaluate_round1'" class="spin" :size="17" aria-hidden="true" />
                <ChevronRight v-else :size="17" aria-hidden="true" />
                生成第一次评价
              </button>
              <template v-else>
                <FeynmanEvaluationPanel :evaluation="session.round1_evaluation" title="第一次评价" />
                <button class="primary-button stage-action" type="button" :disabled="Boolean(actionPending)" @click="runAction('begin_question')">
                  <ChevronRight :size="17" aria-hidden="true" />
                提出疑问
                </button>
              </template>
            </template>
          </article>

          <article v-else-if="currentStep === 2" class="stage-panel">
            <div class="section-heading">
              <div><h2>提出疑问</h2></div>
            </div>
            <p class="stage-lead">回看评价，问一个还没弄懂的问题。</p>
            <label class="field-label" for="question">我仍然不明白</label>
            <textarea id="question" v-model="questionDraft" rows="6" placeholder="例如：为什么这个机制在某种条件下会失效？" />
            <div class="editor-actions">
              <SpeechDraftInput :key="`question-${session?.id}`" :disabled="Boolean(actionPending)" @transcript="text => questionDraft += (questionDraft ? '\n' : '') + text" />
              <span v-if="questionDraft.trim().length < 6">至少 6 字</span>
              <button class="primary-button" type="button" :disabled="!canSubmitQuestion || Boolean(actionPending)" @click="runAction('answer_question', questionDraft, 'question')">
                <LoaderCircle v-if="actionPending === 'answer_question'" class="spin" :size="17" aria-hidden="true" />
                <Send v-else :size="17" aria-hidden="true" />
                提交疑问并查看回答
              </button>
            </div>
          </article>

          <article v-else-if="currentStep === 3" class="stage-panel">
            <div class="section-heading">
              <div><h2>第二次复述</h2></div>
            </div>
            <div class="question-answer">
              <div><strong>你的疑问</strong><p>{{ session.question_answer?.question }}</p></div>
              <div><strong>回答</strong><IncrementalMarkdownRenderer :text="publicLearningText(session.question_answer?.answer)" /></div>
            </div>
            <template v-if="session.status === 'question_answered'">
              <label class="field-label" for="round2">重新组织你的理解</label>
              <textarea id="round2" v-model="round2Draft" rows="11" placeholder="结合刚才的回答，再用自己的话解释一遍。" />
              <div class="editor-actions">
                <SpeechDraftInput :key="`round2-${session?.id}`" :disabled="Boolean(actionPending)" @transcript="text => round2Draft += (round2Draft ? '\n' : '') + text" />
                <span v-if="round2Draft.trim().length < 40">至少 40 字</span>
                <button class="primary-button" type="button" :disabled="!canSubmitRound2 || Boolean(actionPending)" @click="runAction('submit_round2', round2Draft, 'round2')">
                  <Send :size="17" aria-hidden="true" />
                  保存第二次复述
                </button>
              </div>
            </template>
            <template v-else>
              <div class="saved-text"><span>第二次原始复述</span><p>{{ session.round2_text }}</p></div>
              <button class="primary-button stage-action" type="button" :disabled="Boolean(actionPending)" @click="runAction('evaluate_round2')">
                <LoaderCircle v-if="actionPending === 'evaluate_round2'" class="spin" :size="17" aria-hidden="true" />
                <ChevronRight v-else :size="17" aria-hidden="true" />
                生成第二次评价与对比
              </button>
            </template>
          </article>

          <article v-else-if="currentStep === 4" class="stage-panel">
            <div class="section-heading">
              <div><h2>理解变化</h2></div>
            </div>
            <div class="comparison-summary">
              <div><span>第一次</span><strong>{{ comparison.first_score }}</strong></div>
              <ChevronRight :size="22" aria-hidden="true" />
              <div><span>第二次</span><strong>{{ comparison.second_score }}</strong></div>
              <div class="delta"><span>分数变化</span><strong>{{ comparison.score_delta > 0 ? '+' : '' }}{{ comparison.score_delta }}</strong></div>
            </div>
            <h3>{{ conclusionLabel(comparison.conclusion) }}</h3>
            <div class="comparison-columns">
              <div><strong>本轮改善</strong><p>{{ comparison.improved_dimensions?.join('、') || '没有记录到正向变化' }}</p></div>
              <div><strong>仍需补充</strong><ul v-if="comparison.remaining_gaps?.length"><li v-for="(item, index) in comparison.remaining_gaps" :key="index">{{ publicLearningText(item) }}</li></ul><p v-else>本轮要求已完成</p></div>
              <div><strong>下一步建议</strong><ul><li v-for="item in comparison.next_actions" :key="item">{{ publicLearningText(item) }}</li></ul></div>
            </div>
            <button class="primary-button stage-action" type="button" :disabled="Boolean(actionPending)" @click="runAction('apply')">
              <LoaderCircle v-if="actionPending === 'apply'" class="spin" :size="17" aria-hidden="true" />
              <CheckCircle2 v-else :size="17" aria-hidden="true" />
              应用到后续学习
            </button>
          </article>

          <article v-else class="stage-panel completion-panel">
            <CheckCircle2 :size="34" aria-hidden="true" />
            <h2>已应用到后续学习</h2>
            <div class="completion-actions">
              <button class="primary-button" type="button" @click="router.push('/workspace/path')">查看学习路径</button>
              <button class="secondary-button" type="button" @click="router.push('/workspace/review')">进入复习中心</button>
              <button class="secondary-button" type="button" @click="router.push('/workspace/resources')">返回资源中心</button>
            </div>
          </article>

          <section v-if="completedSteps.length" class="completed-section">
            <h2>复述回顾</h2>
            <details v-for="step in completedSteps" :key="step.number" class="completed-stage">
              <summary><CheckCircle2 :size="17" aria-hidden="true" />{{ step.title }}</summary>
              <div v-if="step.number === 1">
                <p class="preserved-text">{{ session.round1_text }}</p>
                <FeynmanEvaluationPanel :evaluation="session.round1_evaluation" title="第一次评价" />
              </div>
              <div v-else-if="step.number === 2" class="question-answer compact-answer">
                <div><strong>疑问</strong><p>{{ session.question_answer?.question }}</p></div>
                <div><strong>回答</strong><IncrementalMarkdownRenderer :text="publicLearningText(session.question_answer?.answer)" /></div>
              </div>
              <div v-else-if="step.number === 3">
                <p class="preserved-text">{{ session.round2_text }}</p>
                <FeynmanEvaluationPanel :evaluation="session.round2_evaluation" title="第二次评价" />
              </div>
            </details>
          </section>
        </section>

        <aside class="context-rail">
          <details v-if="session.learning_material" class="learning-material">
            <summary>本次学习内容</summary>
            <IncrementalMarkdownRenderer :text="session.learning_material" />
          </details>
          <details>
            <summary><History :size="16" aria-hidden="true" />复述历史 <span v-if="sessions.length > 1">{{ sessions.length }}</span></summary>
            <div class="history-list">
              <button v-for="item in sessions" :key="item.session_id" type="button" :class="{ active: item.session_id === session.session_id }" :disabled="loading || Boolean(actionPending)" @click="selectSession(item.session_id)">
                <span>{{ item.status === 'applied' ? '已应用' : '进行中' }} · {{ formatDate(item.updated_at) }}</span>
                <strong>{{ item.round2_score ?? item.round1_score ?? '未评分' }}</strong>
              </button>
            </div>
          </details>
        </aside>
      </div>
    </template>
  </main>
</template>

<style scoped>
.feynman-page {
  min-height: 100%;
  padding: 28px clamp(24px, 4vw, 56px) 48px;
  color: var(--color-text);
  background: transparent;
  font-family: var(--font-sans);
}

.page-header,
.section-heading,
.editor-actions,
.completion-actions,
.comparison-summary,
.step-item,
.completed-stage summary,
.context-rail details > summary {
  display: flex;
  align-items: center;
}

.page-header { gap: 18px; margin: 0 auto 22px; max-width: 1480px; }
.heading-copy { flex: 1; min-width: 0; }
.heading-copy h1 { margin: 2px 0 6px; font-size: var(--font-size-page-title); line-height: 1.2; letter-spacing: 0; }
.heading-copy > p:last-child { margin: 0; color: var(--color-text-secondary); font-size: 15px; line-height: 1.7; }
.eyebrow { margin: 0; color: var(--color-text-muted); font-size: 14px; font-weight: 700; letter-spacing: 0; }

button { font: inherit; }
.icon-button,
.primary-button,
.secondary-button,
.icon-text-button {
  min-height: 40px;
  border: 1px solid var(--color-border-strong);
  border-radius: 7px;
  cursor: pointer;
}
.icon-button { width: 42px; flex: 0 0 42px; display: grid; place-items: center; color: var(--color-accent); background: var(--color-surface); }
.primary-button,
.secondary-button,
.icon-text-button { display: inline-flex; align-items: center; justify-content: center; gap: 8px; padding: 0 16px; font-weight: 700; }
.primary-button { border-color: var(--color-accent); color: #fff; background: var(--color-accent); }
.secondary-button,
.icon-text-button { color: var(--color-accent); background: var(--color-surface); }
button:disabled { cursor: not-allowed; opacity: .48; }
button:focus-visible,
textarea:focus-visible,
summary:focus-visible { outline: 3px solid color-mix(in srgb, var(--color-accent) 28%, transparent); outline-offset: 2px; }

.progress-panel,
.stage-panel,
.completed-section,
.context-rail > section,
.context-rail > details,
.state-panel {
  border: 0;
  border-radius: var(--radius-panel);
  background: var(--color-surface);
}
.progress-panel { max-width: 1480px; margin: 0 auto 22px; padding: 0; border: 0; background: transparent; }
.section-heading { justify-content: space-between; gap: 18px; margin-bottom: 20px; }
.section-heading h2 { margin: 3px 0 0; font-size: 23px; line-height: 1.25; letter-spacing: 0; }
.compact-heading { margin-bottom: 15px; }
.mode-label,
.status-label { border: 1px solid var(--color-border-strong); border-radius: 999px; padding: 5px 9px; color: var(--color-text-secondary); background: var(--color-surface-subtle); font-size: 14px; font-weight: 700; }
.mode-label small { font-size: 14px; }
.step-list { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 8px; margin: 0; padding: 0; list-style: none; }
.step-item { gap: 10px; min-height: 48px; padding: 10px 12px; border: 1px solid transparent; border-radius: 7px; color: var(--color-text-muted); }
.step-item.current { border-color: transparent; color: var(--color-text); background: var(--color-surface-subtle); }
.step-item.complete { color: var(--color-accent); }
.step-marker { display: grid; place-items: center; width: 26px; height: 26px; flex: 0 0 26px; border: 1px solid var(--color-border-strong); border-radius: 50%; }
.step-item.current .step-marker,
.step-item.complete .step-marker { border-color: var(--color-accent); color: #fff; background: var(--color-accent); }
.step-item strong { display: block; font-size: 14px; line-height: 1.35; }
.step-item small { display: block; margin-top: 3px; font-size: 14px; line-height: 1.35; }

.workspace-grid { display: grid; grid-template-columns: minmax(0, 1fr) minmax(280px, 340px); gap: 22px; max-width: 1480px; margin: 0 auto; align-items: start; }
.main-workspace { min-width: 0; }
.stage-panel { padding: clamp(22px, 3vw, 36px); }
.stage-lead { max-width: 760px; margin: -4px 0 24px; color: var(--color-text-secondary); line-height: 1.75; }
.task-prompt { margin-bottom: 24px; padding: 18px 20px; border-left: 3px solid var(--color-accent); background: var(--color-surface-subtle); }
.task-prompt p { margin: 8px 0; font-size: 16px; line-height: 1.8; }
.task-prompt small { color: var(--color-text-secondary); font-size: 14px; line-height: 1.6; }
.field-label { display: block; margin-bottom: 9px; font-size: 15px; font-weight: 700; }
textarea { box-sizing: border-box; width: 100%; resize: vertical; border: 1px solid var(--color-border-strong); border-radius: 7px; padding: 15px 16px; color: var(--color-text); background: var(--color-surface); font: inherit; font-size: 15px; line-height: 1.75; }
textarea::placeholder { color: var(--color-text-muted); }
.editor-actions { justify-content: flex-end; flex-wrap: wrap; gap: 12px; margin-top: 13px; }
.editor-actions > span { margin-right: auto; color: var(--color-text-muted); font-size: 14px; }
.saved-text,
.preserved-text { padding: 17px 19px; border: 1px solid var(--color-border); border-radius: 7px; background: var(--color-reading-paper); }
.saved-text > span { color: var(--color-text-muted); font-size: 14px; font-weight: 700; }
.saved-text p,
.preserved-text { white-space: pre-wrap; overflow-wrap: anywhere; font-size: 15px; line-height: 1.8; }
.stage-action { margin-top: 22px; }

.comparison-columns { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; margin-top: 18px; }
.comparison-columns > div { padding: 14px 0; min-width: 0; }
.comparison-columns p { margin: 7px 0 0; color: var(--color-text-secondary); line-height: 1.65; }

.question-answer { display: grid; gap: 12px; margin-bottom: 24px; }
.question-answer > div { padding: 16px 18px; border-radius: 7px; }
.question-answer > div:last-child { background: var(--color-surface-subtle); }
.question-answer p { margin: 8px 0 0; white-space: pre-wrap; line-height: 1.75; }
.comparison-summary { gap: 18px; padding: 18px 20px; border: 1px solid var(--color-border); border-radius: 7px; }
.comparison-summary > div { min-width: 105px; }
.comparison-summary span { display: block; color: var(--color-text-muted); font-size: 14px; }
.comparison-summary strong { display: block; margin-top: 3px; font-size: 28px; }
.comparison-summary .delta { margin-left: auto; padding-left: 20px; border-left: 1px solid var(--color-border); }
.comparison-columns { grid-template-columns: 1fr; gap: 0; }
.comparison-columns ul { margin: 8px 0 0; padding-left: 20px; color: var(--color-text-secondary); line-height: 1.65; }
.method-note { color: var(--color-text-muted); font-size: 14px; }
.completion-panel { text-align: center; padding-block: 56px; }
.completion-panel > svg { color: var(--color-accent); }
.completion-panel h2 { margin: 6px 0 10px; font-size: 28px; }
.completion-panel > p:not(.eyebrow) { max-width: 650px; margin: 0 auto; color: var(--color-text-secondary); line-height: 1.75; }
.completion-actions { justify-content: center; flex-wrap: wrap; gap: 10px; margin-top: 24px; }

.completed-section { margin-top: 18px; padding: 20px 22px; }
.completed-section > h2 { margin: 0 0 12px; font-size: 18px; }
.completed-stage { border-top: 1px solid var(--color-border); }
.completed-stage summary { gap: 9px; padding: 14px 2px; cursor: pointer; font-weight: 700; }
.completed-stage summary span { margin-left: auto; color: var(--color-text-muted); font-size: 14px; font-weight: 500; }
.completed-stage > div { padding: 0 0 18px; }
.compact-answer { margin: 0; }

.context-rail { display: grid; gap: 12px; min-width: 0; }
.learning-material :deep(.markdown-content) { overflow-wrap: anywhere; }
.learning-material :deep(pre) { max-width: 100%; overflow-x: auto; }
.context-rail > section,
.context-rail > details { padding: 18px; }
.context-rail h2 { margin: 5px 0 14px; font-size: 20px; }
.context-rail dl { margin: 0; }
.context-rail dl div { display: grid; grid-template-columns: 76px minmax(0, 1fr); gap: 8px; padding: 9px 0; border-top: 1px solid var(--color-border); }
.context-rail dt { color: var(--color-text-muted); font-size: 14px; }
.context-rail dd { margin: 0; overflow-wrap: anywhere; font-size: 14px; }
.context-rail details > summary { gap: 8px; cursor: pointer; font-weight: 700; }
.context-rail details > summary span { margin-left: auto; color: var(--color-text-muted); }
.source-list,
.version-list { margin: 14px 0 0; padding: 0; list-style: none; }
.source-list li { padding: 12px 0; border-top: 1px solid var(--color-border); }
.source-list strong,
.source-list span { display: block; font-size: 14px; }
.source-list span { margin-top: 4px; color: var(--color-text-muted); }
.source-list p { margin: 8px 0 0; color: var(--color-text-secondary); font-size: 14px; line-height: 1.6; }
.history-list { display: grid; gap: 8px; margin-top: 13px; }
.history-list button { display: flex; justify-content: space-between; gap: 8px; width: 100%; border: 1px solid var(--color-border); border-radius: 6px; padding: 10px; text-align: left; color: var(--color-accent); background: var(--color-surface); cursor: pointer; }
.history-list button.active { border-color: var(--color-accent); background: var(--color-surface-subtle); }
.history-list span { font-size: 14px; }
.version-list li { display: flex; justify-content: space-between; gap: 8px; padding: 8px 0; border-top: 1px solid var(--color-border); font-size: 14px; }
.version-list small { color: var(--color-text-muted); font-size: 14px; }
.muted { color: var(--color-text-muted); font-size: 14px; line-height: 1.6; }

.state-panel { display: flex; align-items: center; justify-content: center; gap: 10px; max-width: 1480px; min-height: 180px; margin: 0 auto; color: var(--color-text-secondary); }
.error-panel { flex-direction: column; }
.notice { max-width: 1480px; margin: 0 auto 14px; border: 1px solid var(--color-border-strong); border-radius: 7px; padding: 11px 14px; color: var(--color-accent); background: var(--color-surface); font-size: 14px; }
.error-notice { border-color: #9e6e6e; color: #6f2525; background: #fffafa; }
.spin { animation: spin .8s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }

@media (max-width: 1100px) {
  .step-list { grid-template-columns: repeat(3, minmax(0, 1fr)); }
  .workspace-grid { grid-template-columns: minmax(0, 1fr); }
  .context-rail { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .context-rail > section { grid-column: 1 / -1; }
}

@media (max-width: 760px) {
  .feynman-page { padding: 18px 14px 36px; }
  .page-header { align-items: flex-start; flex-wrap: wrap; }
  .page-header > .secondary-button { margin-left: 60px; }
  .step-list,
  .comparison-columns,
  .context-rail { grid-template-columns: 1fr; }
  .comparison-summary { align-items: flex-start; flex-wrap: wrap; }
  .comparison-summary .delta { width: 100%; margin: 0; padding: 12px 0 0; border-top: 1px solid var(--color-border); border-left: 0; }
}
</style>
