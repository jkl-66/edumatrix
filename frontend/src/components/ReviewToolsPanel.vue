<script setup>
import { learningText } from '../utils/learningCopy.js'
import { userMessage } from '../services/errorTranslator.js'
import { computed, onMounted, ref, watch } from 'vue'
import {
  Brain,
  CalendarDays,
  CheckCircle2,
  Clock3,
  Download,
  History,
  ListChecks,
  Loader2,
  Plus,
  Trash2,
} from '@lucide/vue'
import {
  createReviewPlan,
  deleteReviewPlan,
  getAllFlashcards,
  getM5ReviewQueue,
  getReviewPlans,
  reviewFlashcard,
} from '../api'
import { exportM5ReviewDiagnosis, getM5RetestTask, submitM5Retest } from '../api/m5'
import AnkiFlashcard from './AnkiFlashcard.vue'
import CollapsibleMindmap from './CollapsibleMindmap.vue'
import ReviewHistoryPanel from './ReviewHistoryPanel.vue'

const props = defineProps({ studentId: { type: String, default: '' }, courseId: { type: String, default: 'all' } })
const emit = defineEmits(['changed'])

const activeStudentId = computed(() => props.studentId || localStorage.getItem('edumatrix_student_id') || localStorage.getItem('edumatrix_username') || '')
const activeTab = ref('queue')
const reviews = ref([])
const unifiedQueue = ref([])
const dueFlashcards = ref([])
const cardsLoading = ref(false)
const cardsLoaded = ref(false)
const cardsError = ref('')
const loading = ref(true)
const loadError = ref('')
const showForm = ref(false)
const savingPlan = ref(false)
const pendingDeletePlanId = ref('')
const deletingPlan = ref(false)
const form = ref({ concept: '', mastery: 0.5, interval_days: 3 })
const actionFeedback = ref('')
const reviewingKey = ref('')
const adaptiveReview = ref(null)
const failedReview = ref(null)
const retestPanels = ref({})
const retestLoading = ref({})
const retestAnswers = ref({})
const retestFeedback = ref({})
const exporting = ref(false)

const intervals = [1, 3, 7, 14, 30]
const qualityActions = [
  { quality: 2, label: '困难' },
  { quality: 4, label: '一般' },
  { quality: 5, label: '简单' },
]

const tabs = computed(() => [
  { id: 'queue', label: '待处理', icon: ListChecks, count: unifiedQueue.value.length },
  { id: 'flashcards', label: '闪卡', icon: Brain, count: cardsLoaded.value ? dueFlashcards.value.length : null },
  { id: 'plans', label: '计划', icon: CalendarDays, count: reviews.value.length },
  { id: 'history', label: '记录', icon: History, count: null },
])

const displayPlans = computed(() => reviews.value.map(plan => ({
  ...plan,
  display_title: conceptLabel(plan.concept),
})))

function errorMessage(exception, fallback) {
  const detail = exception?.response?.data?.detail
  return detail?.message || (typeof detail === 'string' ? detail : '') || exception?.message || fallback
}

function setAction(message) {
  actionFeedback.value = message
  window.setTimeout(() => {
    if (actionFeedback.value === message) actionFeedback.value = ''
  }, 3200)
}

function matchesCourse(item) {
  return !props.courseId || props.courseId === 'all'
    || (props.courseId === 'unclassified' ? !item.course_id : item.course_id === props.courseId)
}

async function load({ refresh = false, changed = false } = {}) {
  if (!activeStudentId.value) return
  if (!refresh) loading.value = true
  loadError.value = ''
  try {
    const [plans, queue] = await Promise.all([
      getReviewPlans(activeStudentId.value),
      getM5ReviewQueue(),
    ])
    reviews.value = (Array.isArray(plans) ? plans : []).filter(matchesCourse)
    unifiedQueue.value = (queue?.items || []).filter(matchesCourse)
    if (changed) emit('changed')
  } catch (exception) {
    loadError.value = errorMessage(exception, '复习工具加载失败，请重试。')
  } finally {
    loading.value = false
  }
}

async function loadCards() {
  if (cardsLoading.value) return
  cardsLoading.value = true
  cardsError.value = ''
  try {
    const result = await getAllFlashcards(activeStudentId.value, props.courseId)
    dueFlashcards.value = result?.cards || []
    cardsLoaded.value = true
    if (result?.failures?.length) cardsError.value = '部分闪卡暂时没有准备好，已准备好的卡片仍可复习。请稍后重试。'
  } catch (exception) {
    cardsError.value = errorMessage(exception, '闪卡暂时没有准备好，请稍后重试。')
  } finally {
    cardsLoading.value = false
  }
}

watch(activeTab, tab => {
  if (tab === 'flashcards' && !cardsLoaded.value) loadCards()
})

async function addPlan() {
  if (!form.value.concept.trim() || savingPlan.value) return
  savingPlan.value = true
  try {
    await createReviewPlan(activeStudentId.value, {
      concept: form.value.concept.trim(),
      mastery: form.value.mastery,
      interval_days: form.value.interval_days,
      course_id: !props.courseId || ['all', 'unclassified'].includes(props.courseId) ? null : props.courseId,
    })
    form.value = { concept: '', mastery: 0.5, interval_days: 3 }
    showForm.value = false
    setAction('复习计划已创建。')
    await load({ changed: true })
  } catch (exception) {
    setAction(errorMessage(exception, '复习计划创建失败。'))
  } finally {
    savingPlan.value = false
  }
}

async function submitReview(plan, quality) {
  if (!plan?.concept || reviewingKey.value) return
  const key = `${plan.id || plan.concept}:${quality}`
  reviewingKey.value = key
  failedReview.value = null
  try {
    const result = await reviewFlashcard(activeStudentId.value, plan.concept, quality, '', plan.id)
    adaptiveReview.value = result?.adaptive_review?.triggered ? result.adaptive_review : null
    const interval = result?.review_plan?.interval_days || result?.interval_new || '-'
    setAction(`反馈已记录，下次复习间隔为 ${interval} 天。`)
    await load({ changed: true })
  } catch (exception) {
    failedReview.value = { plan, quality }
    setAction(`${errorMessage(exception, '真实模型生成失败。')} 可重试。`)
  } finally {
    reviewingKey.value = ''
  }
}

async function retryFailedReview() {
  if (!failedReview.value) return
  const retry = failedReview.value
  await submitReview(retry.plan, retry.quality)
}

async function removePlan(planId) {
  if (deletingPlan.value) return
  deletingPlan.value = true
  try {
    await deleteReviewPlan(planId)
    pendingDeletePlanId.value = ''
    setAction('复习计划已删除。')
    await load({ changed: true })
  } catch (exception) {
    setAction(errorMessage(exception, '复习计划删除失败。'))
  } finally {
    deletingPlan.value = false
  }
}

async function handleCardReviewed() {
  setAction('闪卡复习已记录，下一次安排已经更新。')
  await load({ refresh: true, changed: true })
  await loadCards()
}

async function exportDiagnosis() {
  exporting.value = true
  try {
    const blob = await exportM5ReviewDiagnosis()
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = 'EduMatrix-复习报告.md'
    link.click()
    URL.revokeObjectURL(url)
    setAction('复习报告已导出。')
  } catch (exception) {
    setAction(errorMessage(exception, '复习报告导出失败。'))
  } finally {
    exporting.value = false
  }
}

function conceptLabel(concept) {
  return learningText(concept, '待巩固知识点')
}

function nextReviewDate(plan) {
  if (!plan.next_review_at) return '待安排'
  return new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).format(new Date(plan.next_review_at))
}

function dueText(plan) {
  if (plan.is_due) return '今日到期'
  if (plan.days_until_due == null) return '待安排'
  return `${plan.days_until_due} 天后`
}

function queueTitle(item) {
  return item.source_type === 'sm2_review_plan'
    ? conceptLabel(item.concept)
    : `错因复测 · ${conceptLabel(item.category)}`
}

function queueSource(item) {
  return item.source_type === 'sm2_review_plan' ? '间隔复习' : '错因复测'
}

function queueStatus(item) {
  return ({ due: '今天处理', needs_review: '建议先复习', scheduled: '已安排' })[item.status] || '待处理'
}

function queueDue(item) {
  if (!item.due_at) return '待安排'
  return new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(new Date(item.due_at))
}

function canStartRetest(item) {
  return item.retest_task?.status === 'due'
}

async function openRetest(item) {
  const task = item.retest_task
  if (!task || !canStartRetest(item)) return
  retestLoading.value[task.id] = true
  retestFeedback.value[task.id] = ''
  try {
    retestPanels.value[task.id] = await getM5RetestTask(task.id)
    retestAnswers.value[task.id] = ''
  } catch (exception) {
    retestFeedback.value[task.id] = errorMessage(exception, '复测题目加载失败。')
  } finally {
    retestLoading.value[task.id] = false
  }
}

async function submitRetest(item) {
  const task = item.retest_task
  const panel = retestPanels.value[task.id]
  const rawAnswer = String(retestAnswers.value[task.id] || '').trim()
  if (!panel || !rawAnswer) return
  retestLoading.value[task.id] = true
  try {
    const hasOptions = Array.isArray(panel.question?.options) && panel.question.options.length > 0
    const result = await submitM5Retest(task.id, {
      idempotency_key: `ui-${task.id}-${Date.now()}`,
      answer: hasOptions ? { choice: rawAnswer } : { text: rawAnswer },
    })
    retestFeedback.value[task.id] = result.task.status === 'completed'
      ? '复测通过，结果已回流学习路径。'
      : result.attempt.grading_status === 'manual_required'
        ? '该题仍需审核，本次尚未形成掌握证据。'
        : '本次未通过，可按计划复习后再次尝试。'
    await load({ changed: true })
  } catch (exception) {
    retestFeedback.value[task.id] = errorMessage(exception, '复测提交失败。')
  } finally {
    retestLoading.value[task.id] = false
  }
}

onMounted(load)
</script>

<template>
  <div class="review-tools-panel" data-testid="review-tools-panel">
    <header class="review-tools-panel__nav">
      <nav aria-label="复习工具分类">
        <button
          v-for="tab in tabs"
          :key="tab.id"
          type="button"
          :class="{ 'is-active': activeTab === tab.id }"
          :aria-pressed="activeTab === tab.id"
          @click="activeTab = tab.id"
        >
          <component :is="tab.icon" :size="17" />
          <span>{{ tab.label }}</span>
          <small v-if="tab.count !== null">{{ tab.count }}</small>
        </button>
      </nav>

      <div class="review-tools-panel__actions">
        <button v-if="activeTab === 'plans'" type="button" class="ui-button ui-button--primary" @click="showForm = !showForm">
          <Plus :size="17" />{{ showForm ? '收起表单' : '添加计划' }}
        </button>
        <button v-if="activeTab === 'history'" type="button" class="ui-button ui-button--secondary" :disabled="exporting" @click="exportDiagnosis">
          <Loader2 v-if="exporting" :size="17" class="review-tools-panel__spin" />
          <Download v-else :size="17" />{{ exporting ? '导出中' : '导出复习报告' }}
        </button>
      </div>
    </header>

    <p v-if="actionFeedback" class="review-tools-panel__feedback" role="status">{{ actionFeedback }}</p>
    <div v-if="loadError" class="review-tools-panel__error" role="alert">
      <span>{{ userMessage(loadError) }}</span>
      <button type="button" @click="load">重试</button>
    </div>

    <div v-if="loading" class="review-tools-panel__loading">
      <Loader2 :size="22" class="review-tools-panel__spin" />正在加载复习工具
    </div>

    <template v-else>
      <section v-show="activeTab === 'queue'" class="review-tool-view" aria-labelledby="review-queue-title">
        <header class="review-tool-view__heading">
          <div><h2 id="review-queue-title">待处理</h2><p>优先完成到期复习和已开放的错因复测。</p></div>
        </header>
        <div v-if="unifiedQueue.length" class="review-queue-list">
          <article v-for="item in unifiedQueue" :key="`${item.source_type}:${item.source_id}`">
            <div class="review-queue-list__head">
              <div><strong>{{ queueTitle(item) }}</strong><span>{{ queueSource(item) }}</span></div>
              <span class="review-queue-list__status">{{ queueStatus(item) }}</span>
            </div>
            <p>{{ learningText(item.reason) }}</p>
            <small><Clock3 :size="16" />{{ queueDue(item) }}</small>
            <template v-if="item.retest_task">
              <button
                v-if="canStartRetest(item) && !retestPanels[item.retest_task.id]"
                type="button"
                class="review-queue-list__primary"
                :disabled="retestLoading[item.retest_task.id]"
                @click="openRetest(item)"
              >{{ retestLoading[item.retest_task.id] ? '加载中' : '开始复测' }}</button>
              <span v-else-if="item.retest_task.status === 'scheduled'" class="review-queue-list__waiting">到期后开放复测</span>
              <div v-if="retestPanels[item.retest_task.id]" class="review-retest">
                <strong>{{ retestPanels[item.retest_task.id].question.prompt }}</strong>
                <label v-for="option in retestPanels[item.retest_task.id].question.options" :key="option">
                  <input v-model="retestAnswers[item.retest_task.id]" type="radio" :value="option.slice(0, 1).toUpperCase()" />
                  <span>{{ option }}</span>
                </label>
                <textarea
                  v-if="!retestPanels[item.retest_task.id].question.options.length"
                  v-model="retestAnswers[item.retest_task.id]"
                  rows="3"
                  placeholder="输入复测答案"
                />
                <button type="button" :disabled="retestLoading[item.retest_task.id] || !retestAnswers[item.retest_task.id]" @click="submitRetest(item)">
                  {{ retestLoading[item.retest_task.id] ? '提交中' : '提交复测' }}
                </button>
              </div>
              <p v-if="retestFeedback[item.retest_task.id]" class="review-retest__feedback">{{ retestFeedback[item.retest_task.id] }}</p>
            </template>
          </article>
        </div>
        <div v-else class="review-tool-view__empty">
          <CheckCircle2 :size="30" />
          <strong>当前没有待处理任务</strong>
          <p>新的到期复习或错因复测会自动出现在这里。</p>
        </div>
      </section>

      <section v-show="activeTab === 'flashcards'" class="review-tool-view" aria-labelledby="review-flashcards-title">
        <header class="review-tool-view__heading">
          <div><h2 id="review-flashcards-title">记忆闪卡</h2><p>翻看卡片并按真实回忆情况评分，系统自动安排下一次复习。</p></div>
        </header>
        <p v-if="cardsLoading" role="status">正在准备闪卡，已有复习计划不受影响。</p>
        <div v-if="cardsError" class="review-tools-panel__error" role="alert">
          <span>{{ userMessage(cardsError) }}</span>
          <button type="button" :disabled="cardsLoading" @click="loadCards">重新准备闪卡</button>
        </div>
        <div v-if="dueFlashcards.length" class="review-flashcard-list">
          <article v-for="card in dueFlashcards" :key="card.id" data-testid="canonical-flashcard">
            <header>
              <strong>{{ conceptLabel(card.concept) }}</strong>
              <span>{{ new Date(card.next_review_at) <= new Date() ? '今日到期' : '计划中' }}</span>
            </header>
            <AnkiFlashcard :card="card" :student-id="activeStudentId" @reviewed="handleCardReviewed" />
          </article>
        </div>
        <div v-else-if="!cardsLoading && !cardsError" class="review-tool-view__empty">
          <Brain :size="30" />
          <strong>暂无待复习闪卡</strong>
          <p>完成测验、错题整理或笔记学习后，新的闪卡会进入这里。</p>
        </div>
      </section>

      <section v-show="activeTab === 'plans'" class="review-tool-view" aria-labelledby="review-plans-title">
        <header class="review-tool-view__heading">
          <div><h2 id="review-plans-title">复习计划</h2><p>查看下次日期，并用“困难、一般、简单”更新安排。</p></div>
        </header>

        <form v-if="showForm" class="review-plan-form" @submit.prevent="addPlan">
          <label class="review-plan-form__concept"><span>知识点</span><input v-model="form.concept" maxlength="128" placeholder="输入知识点名称" /></label>
          <label class="review-plan-form__mastery">
            <span>自评熟悉程度 <strong>{{ Math.round(form.mastery * 100) }}%</strong></span>
            <input v-model.number="form.mastery" type="range" min="0" max="1" step="0.05" />
          </label>
          <fieldset>
            <legend>首次间隔</legend>
            <button
              v-for="days in intervals"
              :key="days"
              type="button"
              :class="{ 'is-selected': form.interval_days === days }"
              @click="form.interval_days = days"
            >{{ days }} 天</button>
          </fieldset>
          <div class="review-plan-form__actions">
            <button type="button" class="ui-button ui-button--secondary" @click="showForm = false">取消</button>
            <button type="submit" class="ui-button ui-button--primary" :disabled="!form.concept.trim() || savingPlan">{{ savingPlan ? '正在保存' : '创建计划' }}</button>
          </div>
        </form>

        <section v-if="adaptiveReview" class="review-adaptive" aria-labelledby="review-adaptive-title">
          <header>
            <div><h3 id="review-adaptive-title">{{ adaptiveReview.title }}</h3><p>{{ adaptiveReview.simplified_explanation }}</p></div>
            <span>根据这次复习感受调整讲法</span>
          </header>
          <ol v-if="adaptiveReview.agent_trace?.length" class="review-adaptive__trace" aria-label="学习解释生成过程">
            <li v-for="step in adaptiveReview.agent_trace" :key="step">{{ step }}</li>
          </ol>
          <CollapsibleMindmap v-if="adaptiveReview.mermaid" :code="adaptiveReview.mermaid" />
        </section>
        <section v-if="failedReview" class="review-adaptive review-adaptive--error" role="alert">
          <strong>这次解释暂时没有准备好</strong>
          <p>请重试，学习伙伴会换个说法并配上关系图。</p>
          <button type="button" class="ui-button ui-button--secondary" :disabled="Boolean(reviewingKey)" @click="retryFailedReview">
            {{ reviewingKey ? '重试中' : '重试生成' }}
          </button>
        </section>

        <div v-if="reviews.length" class="review-plan-list">
          <article v-for="plan in reviews" :key="plan.id">
            <div class="review-plan-list__main">
              <div class="review-plan-list__title">
                <strong>{{ conceptLabel(plan.concept) }}</strong>
                <span>{{ dueText(plan) }}</span>
              </div>
              <p>下次复习 {{ nextReviewDate(plan) }} · 已复习 {{ plan.review_count || 0 }} 次</p>
              <div class="review-plan-list__mastery">
                <span>复习参考熟悉度 {{ Math.round((plan.mastery || 0) * 100) }}%</span>
                <i><b :style="{ width: `${(plan.mastery || 0) * 100}%` }" /></i>
              </div>
            </div>
            <div class="review-plan-list__actions">
              <span>本次感受</span>
              <div>
                <button
                  v-for="action in qualityActions"
                  :key="`${plan.id}-${action.quality}`"
                  type="button"
                  :disabled="Boolean(reviewingKey)"
                  @click="submitReview(plan, action.quality)"
                >{{ reviewingKey === `${plan.id || plan.concept}:${action.quality}` ? '提交中' : action.label }}</button>
                <button type="button" class="review-plan-list__delete" title="删除复习计划" aria-label="删除复习计划" @click="pendingDeletePlanId = plan.id">
                  <Trash2 :size="17" />
                </button>
              </div>
              <div v-if="pendingDeletePlanId === plan.id" role="group" aria-label="确认删除复习计划">
                <span>删除这项复习安排？已有学习记录仍保留。</span>
                <button type="button" :disabled="deletingPlan" @click="pendingDeletePlanId = ''">保留计划</button>
                <button type="button" :disabled="deletingPlan" @click="removePlan(plan.id)">{{ deletingPlan ? '删除中' : '确认删除计划' }}</button>
              </div>
            </div>
          </article>
        </div>
        <div v-else class="review-tool-view__empty">
          <CalendarDays :size="30" />
          <strong>暂无复习计划</strong>
          <p>学习和测验会自动生成计划，也可以在这里手动添加。</p>
        </div>
      </section>

      <div v-show="activeTab === 'history'" class="review-tool-view review-tool-view--history">
        <ReviewHistoryPanel :student-id="activeStudentId" :plans="displayPlans" @recorded="load({ changed: true })" />
      </div>
    </template>
  </div>
</template>

<style scoped>
.review-tools-panel {
  min-height: 594px;
  color: var(--color-text);
  font-family: var(--font-sans);
}

.review-tools-panel__nav {
  display: flex;
  min-height: 64px;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
  padding: 10px 16px;
  border-bottom: 1px solid var(--color-border);
  background: var(--color-surface-subtle);
}

.review-tools-panel__nav nav {
  display: flex;
  min-width: 0;
  gap: 4px;
}

.review-tools-panel__nav nav button {
  display: inline-flex;
  min-height: 40px;
  align-items: center;
  gap: 7px;
  padding: 0 12px;
  color: var(--color-text-secondary);
  border: 0;
  border-radius: 6px;
  background: transparent;
  font-size: 14px;
  cursor: pointer;
}

.review-tools-panel__nav nav button:hover { color: var(--color-text); background: var(--color-surface); }
.review-tools-panel__nav nav button.is-active { color: #ffffff; background: var(--color-accent); font-weight: 700; }
.review-tools-panel__nav nav small { display: grid; min-width: 22px; height: 22px; place-items: center; border-radius: 5px; background: rgb(255 255 255 / 16%); font-size: 14px; }
.review-tools-panel__nav nav button:not(.is-active) small { background: var(--color-surface-muted); }
.review-tools-panel__actions { display: flex; flex: 0 0 auto; gap: 8px; }
.review-tools-panel__actions .ui-button { min-height: 40px; }

.review-tools-panel__feedback,
.review-tools-panel__error {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin: 16px 24px 0;
  padding: 10px 12px;
  color: var(--color-text-secondary);
  border: 1px solid var(--color-border);
  border-radius: 6px;
  background: var(--color-surface-subtle);
  font-size: 14px;
}

.review-tools-panel__error { color: var(--color-danger); border-color: #e8caca; background: var(--color-danger-soft); }
.review-tools-panel__error button { color: currentColor; border: 0; background: transparent; font-size: 14px; font-weight: 700; cursor: pointer; }
.review-tools-panel__loading { display: flex; min-height: 420px; align-items: center; justify-content: center; gap: 9px; color: var(--color-text-muted); font-size: 14px; }
.review-tools-panel__spin { animation: review-tools-spin 900ms linear infinite; }

.review-tool-view { min-height: 520px; }
.review-tool-view__heading { display: flex; min-height: 78px; align-items: center; justify-content: space-between; gap: 20px; padding: 18px 26px; border-bottom: 1px solid var(--color-border); }
.review-tool-view__heading h2 { margin: 0; color: var(--color-text); font-size: 18px; font-weight: 700; }
.review-tool-view__heading p { margin: 4px 0 0; color: var(--color-text-secondary); font-size: 14px; }
.review-tool-view__empty { display: flex; min-height: 360px; flex-direction: column; align-items: center; justify-content: center; padding: 32px; color: var(--color-text-muted); text-align: center; }
.review-tool-view__empty strong { margin-top: 10px; color: var(--color-text); font-size: 16px; }
.review-tool-view__empty p { max-width: 48ch; margin: 5px 0 0; font-size: 14px; line-height: 1.6; }

.review-queue-list,
.review-flashcard-list,
.review-plan-list { display: grid; }

.review-queue-list article,
.review-flashcard-list article,
.review-plan-list article { padding: 18px 26px; border-bottom: 1px solid var(--color-border); }

.review-queue-list article:last-child,
.review-flashcard-list article:last-child,
.review-plan-list article:last-child { border-bottom: 0; }

.review-queue-list__head,
.review-flashcard-list article > header,
.review-plan-list article { display: flex; align-items: flex-start; justify-content: space-between; gap: 24px; }
.review-queue-list__head > div { display: flex; align-items: center; gap: 10px; }
.review-queue-list__head strong,
.review-flashcard-list article > header strong,
.review-plan-list__title strong { color: var(--color-text); font-size: 15px; }
.review-queue-list__head > div > span,
.review-flashcard-list article > header span,
.review-plan-list__title span,
.review-queue-list__status { color: var(--color-text-muted); font-size: 14px; }
.review-queue-list__status { padding: 4px 8px; border-radius: 5px; background: var(--color-surface-subtle); }
.review-queue-list article > p { max-width: 78ch; margin: 8px 0; color: var(--color-text-secondary); font-size: 14px; line-height: 1.6; }
.review-queue-list article > small { display: flex; align-items: center; gap: 6px; color: var(--color-text-muted); font-size: 14px; }
.review-queue-list__primary,
.review-retest button { min-height: 38px; margin-top: 12px; padding: 0 12px; color: #ffffff; border: 0; border-radius: 6px; background: var(--color-accent); font-size: 14px; font-weight: 700; cursor: pointer; }
.review-queue-list__primary:disabled,
.review-retest button:disabled { cursor: wait; opacity: 0.55; }
.review-queue-list__waiting { display: inline-block; margin-top: 10px; color: var(--color-text-muted); font-size: 14px; }
.review-retest { display: grid; gap: 9px; margin-top: 14px; padding-top: 14px; border-top: 1px solid var(--color-border); }
.review-retest > strong { font-size: 15px; }
.review-retest label { display: flex; align-items: flex-start; gap: 8px; color: var(--color-text-secondary); font-size: 14px; }
.review-retest label input { margin-top: 3px; }
.review-retest textarea { width: 100%; resize: vertical; padding: 10px; color: var(--color-text); border: 1px solid var(--color-border-strong); border-radius: 6px; background: var(--color-surface); font-size: 14px; }
.review-retest button { justify-self: start; }
.review-retest__feedback { margin-bottom: 0 !important; font-weight: 650; }

.review-flashcard-list { grid-template-columns: repeat(2, minmax(0, 1fr)); }
.review-flashcard-list article:nth-child(odd) { border-right: 1px solid var(--color-border); }
.review-flashcard-list article:only-child { grid-column: 1 / -1; border-right: 0; }
.review-flashcard-list article > header { align-items: center; margin-bottom: 12px; }

.review-plan-form { display: grid; grid-template-columns: minmax(260px, 1.2fr) minmax(220px, 1fr) minmax(250px, auto); gap: 16px 20px; padding: 20px 26px; border-bottom: 1px solid var(--color-border); background: var(--color-surface-subtle); }
.review-plan-form label { display: grid; gap: 7px; color: var(--color-text-secondary); font-size: 14px; }
.review-plan-form input[type='text'],
.review-plan-form__concept input { min-height: 42px; padding: 0 12px; font-size: 14px; }
.review-plan-form__mastery strong { color: var(--color-text); }
.review-plan-form fieldset { display: flex; align-items: flex-end; gap: 6px; margin: 0; padding: 0; border: 0; }
.review-plan-form legend { width: 100%; margin-bottom: 7px; color: var(--color-text-secondary); font-size: 14px; }
.review-plan-form fieldset button { min-height: 34px; padding: 0 9px; color: var(--color-text-secondary); border: 1px solid var(--color-border); border-radius: 5px; background: var(--color-surface); font-size: 14px; cursor: pointer; }
.review-plan-form fieldset button.is-selected { color: #ffffff; border-color: var(--color-accent); background: var(--color-accent); }
.review-plan-form__actions { display: flex; grid-column: 1 / -1; justify-content: flex-end; gap: 8px; }

.review-adaptive { padding: 18px 26px; border-bottom: 1px solid var(--color-border); background: var(--color-surface-subtle); }
.review-adaptive > header { display: flex; align-items: flex-start; justify-content: space-between; gap: 24px; margin-bottom: 14px; }
.review-adaptive h3 { margin: 0; font-size: 16px; }
.review-adaptive p { max-width: 78ch; margin: 5px 0 0; color: var(--color-text-secondary); font-size: 14px; line-height: 1.6; white-space: pre-line; }
.review-adaptive > header > span { flex: 0 0 auto; padding: 5px 8px; color: var(--color-text-secondary); border: 1px solid var(--color-border); border-radius: 5px; background: var(--color-surface); font-size: 14px; }
.review-adaptive__trace { display: grid; gap: 6px; margin: 0 0 14px; padding: 0 0 0 22px; color: var(--color-text-secondary); font-size: 14px; line-height: 1.5; }
.review-adaptive--error { color: var(--color-danger); border-color: var(--color-danger); }
.review-adaptive--error strong { font-size: 15px; }
.review-adaptive--error button { margin-top: 10px; }

.review-plan-list__main { min-width: 0; flex: 1; }
.review-plan-list__title { display: flex; align-items: center; gap: 10px; }
.review-plan-list__title span { padding: 3px 7px; border-radius: 5px; background: var(--color-surface-subtle); }
.review-plan-list__main > p { margin: 6px 0 10px; color: var(--color-text-secondary); font-size: 14px; }
.review-plan-list__mastery { display: grid; max-width: 520px; grid-template-columns: auto minmax(160px, 1fr); align-items: center; gap: 12px; color: var(--color-text-muted); font-size: 14px; }
.review-plan-list__mastery i { height: 6px; overflow: hidden; border-radius: 3px; background: var(--color-surface-muted); }
.review-plan-list__mastery b { display: block; height: 100%; border-radius: inherit; background: var(--color-accent); }
.review-plan-list__actions { flex: 0 0 auto; }
.review-plan-list__actions > span { display: block; margin-bottom: 6px; color: var(--color-text-muted); font-size: 14px; text-align: right; }
.review-plan-list__actions > div { display: flex; gap: 6px; }
.review-plan-list__actions button { min-height: 36px; padding: 0 10px; color: var(--color-text-secondary); border: 1px solid var(--color-border); border-radius: 5px; background: var(--color-surface); font-size: 14px; cursor: pointer; }
.review-plan-list__actions button:hover { color: var(--color-text); background: var(--color-surface-subtle); }
.review-plan-list__actions button:disabled { cursor: wait; opacity: 0.55; }
.review-plan-list__actions .review-plan-list__delete { display: grid; width: 36px; padding: 0; place-items: center; color: var(--color-danger); }
.review-tool-view--history { min-height: 520px; }

@keyframes review-tools-spin { to { transform: rotate(360deg); } }

@media (max-width: 1080px) {
  .review-tools-panel__nav { align-items: flex-start; }
  .review-tools-panel__nav nav { flex-wrap: wrap; }
  .review-flashcard-list { grid-template-columns: 1fr; }
  .review-flashcard-list article:nth-child(odd) { border-right: 0; }
  .review-plan-form { grid-template-columns: 1fr 1fr; }
  .review-plan-form fieldset { grid-column: 1 / -1; }
}
</style>
