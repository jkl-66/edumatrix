<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  AlertTriangle,
  ArrowRight,
  BookOpen,
  Boxes,
  Calendar,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Clock,
  ListChecks,
  Loader2,
  MessageSquareText,
  NotebookPen,
  RefreshCw,
  RotateCcw,
} from '@lucide/vue'
import {
  completeReviewScheduleTask,
  createReviewResourceJob,
  executeGenerationJob,
  getReviewSchedule,
} from '../api'
import { getM5RetestTask, submitM5Retest } from '../api/m5'
import TaskState from './TaskState.vue'

const props = defineProps({
  noteBusyId: { type: String, default: '' },
})
const emit = defineEmits(['note', 'view-change'])

const route = useRoute()
const router = useRouter()

function shanghaiDateParts(value = new Date()) {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: 'Asia/Shanghai',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).formatToParts(value)
  const byType = Object.fromEntries(parts.map(item => [item.type, item.value]))
  return { date: `${byType.year}-${byType.month}-${byType.day}`, month: `${byType.year}-${byType.month}` }
}

function validMonth(value) {
  return /^\d{4}-(0[1-9]|1[0-2])$/.test(String(value || ''))
}

function errorMessage(exception, fallback) {
  const detail = exception?.response?.data?.detail
  return detail?.message || (typeof detail === 'string' ? detail : '') || exception?.message || fallback
}

function routeActionNotice(value) {
  if (value === 'review-completed') return '复习已完成，新的复习安排已经更新。'
  if (value === 'review-recorded') return '这次复习已记录，系统没有重复计入证据。'
  if (value === 'retest-completed') return '复测通过，服务端证据已回流画像与学习路径。'
  return ''
}

const now = shanghaiDateParts()
const month = ref(validMonth(route.query.month) ? String(route.query.month) : now.month)
const courseId = ref(String(route.query.review_course || route.query.course_id || 'all'))
const selectedDate = ref(String(route.query.date || now.date))
const activeView = ref('calendar')
const schedule = ref({ days: [], tasks: [], courses: [], weekdays: ['一', '二', '三', '四', '五', '六', '日'], summary: {} })
const loading = ref(true)
const loadError = ref('')
const actionNotice = ref(routeActionNotice(route.query.review_notice))
const actionError = ref('')
const failedAction = ref(null)
const activeTaskId = ref('')
const taskBusy = ref('')
const reviewDraft = ref({ recall_score: 0.65, duration_minutes: 10 })
const retestPanel = ref(null)
const retestAnswer = ref('')
const retestFeedback = ref('')
const reviewedResourceTasks = ref({})
const assessmentEventByTask = ref({})
const idempotencyKeys = new Map()
let routeTaskOpened = false

const recallOptions = [
  { value: 0.35, label: '困难', detail: '只能回忆少量关键内容' },
  { value: 0.65, label: '一般', detail: '能说明主线，但仍有停顿' },
  { value: 0.9, label: '简单', detail: '可以完整解释并举例' },
]

const taskStatusLabels = {
  due: '今天到期',
  overdue: '已逾期',
  scheduled: '未来安排',
  completed: '已完成',
}

const monthLabel = computed(() => {
  const [year, monthNumber] = month.value.split('-')
  return `${year} 年 ${Number(monthNumber)} 月`
})

const selectedDay = computed(() => schedule.value.days.find(day => day.date === selectedDate.value) || null)
const selectedTasks = computed(() => schedule.value.tasks.filter(task => task.date === selectedDate.value))
const activeTask = computed(() => schedule.value.tasks.find(task => task.id === activeTaskId.value) || null)
const selectedDateLabel = computed(() => formatDate(selectedDate.value, { month: 'long', day: 'numeric', weekday: 'long' }))
// "未归类计划" remains available in history payloads for audit, but it is
// not a selectable course because it is not part of the active knowledge base.
const courses = computed(() => [
  { id: 'all', title: '全部课程' },
  ...(schedule.value.courses || []).filter(course => course.id !== 'unclassified'),
])

function formatDate(value, options = {}) {
  if (!value) return '待安排'
  return new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', ...options })
    .format(new Date(`${value}T00:00:00+08:00`))
}

function formatTime(value) {
  if (!value) return '待安排'
  return new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(new Date(value))
}

function humanTaskType(task) {
  const value = String(task?.type || '').trim()
  const withoutEnginePrefix = value.replace(/^[A-Za-z]+(?:-\d+)?\s+/, '').trim()
  return withoutEnginePrefix && /[^\x00-\x7F]/.test(withoutEnginePrefix)
    ? withoutEnginePrefix
    : '复习安排'
}

function taskStatus(task) {
  return taskStatusLabels[task.status] || '待处理'
}

function daySummary(day) {
  if (!day.counts?.total) return '无安排'
  if (day.state === 'completed') return `完成 ${day.counts.completed} 项`
  if (day.state === 'overdue') return `逾期 ${day.counts.pending} 项`
  if (day.state === 'today') return `今日 ${day.counts.pending} 项`
  return `待复习 ${day.counts.pending} 项`
}

function dayMarkerState(day) {
  if (day.state === 'today') return 'today'
  if (day.state === 'overdue') return 'overdue'
  if (day.state === 'future' && day.counts?.total) return 'future'
  return ''
}

function stableKey(scope, taskId) {
  const mapKey = `${scope}:${taskId}`
  if (!idempotencyKeys.has(mapKey)) {
    idempotencyKeys.set(mapKey, `f8-ui-${scope}-${Date.now()}-${Math.random().toString(16).slice(2)}`)
  }
  return idempotencyKeys.get(mapKey)
}

function syncQuery(patch = {}) {
  const query = {
    ...route.query,
    month: month.value,
    date: selectedDate.value,
    ...patch,
  }
  if (patch.review_notice && !Object.prototype.hasOwnProperty.call(patch, 'review_event')) {
    delete query.review_event
  }
  delete query.review_course
  if (courseId.value === 'unclassified') {
    delete query.course_id
    query.review_course = 'unclassified'
  } else if (courseId.value === 'all') {
    delete query.course_id
  } else {
    query.course_id = courseId.value
  }
  for (const [key, value] of Object.entries(query)) {
    if (value == null || value === '') delete query[key]
  }
  return router.replace({ query }).catch(() => {})
}

function isReviewAssessmentTask(task) {
  return task?.action?.kind === 'review_assessment' || task?.source_type === 'sm2_review_plan'
}

function hasReviewedResource(task) {
  return Boolean(reviewedResourceTasks.value[task?.id])
}

async function loadSchedule({ keepNotice = false } = {}) {
  loading.value = true
  loadError.value = ''
  actionError.value = ''
  failedAction.value = null
  if (!keepNotice) actionNotice.value = ''
  try {
    const result = await getReviewSchedule(month.value, courseId.value)
    schedule.value = result
    if (!result.days.some(day => day.date === selectedDate.value)) {
      const fallback = result.days.find(day => day.date === result.today)
        || result.days.find(day => day.in_month)
        || result.days[0]
      selectedDate.value = fallback?.date || `${month.value}-01`
    }
    if (!courses.value.some(course => course.id === courseId.value)) courseId.value = 'all'
    syncQuery()
    await openRequestedTask()
  } catch (exception) {
    loadError.value = errorMessage(exception, '复习安排加载失败，请保留当前日期后重试。')
  } finally {
    loading.value = false
  }
}

async function openRequestedTask() {
  if (routeTaskOpened) return
  const requested = route.query.review_task
    ? String(route.query.review_task)
    : route.query.retest_id
      ? `retest:${route.query.retest_id}`
      : ''
  if (!requested) return
  const task = schedule.value.tasks.find(item => item.id === requested)
  if (!task) return
  routeTaskOpened = true
  selectedDate.value = task.date
  await startTask(task, { sync: false })
}

async function changeMonth(offset) {
  const [year, monthNumber] = month.value.split('-').map(Number)
  const target = new Date(Date.UTC(year, monthNumber - 1 + offset, 1))
  month.value = `${target.getUTCFullYear()}-${String(target.getUTCMonth() + 1).padStart(2, '0')}`
  selectedDate.value = `${month.value}-01`
  activeTaskId.value = ''
  routeTaskOpened = false
  syncQuery({ review_task: null, retest_id: null, review_notice: null })
  await loadSchedule()
}

async function returnToday() {
  const current = shanghaiDateParts()
  month.value = current.month
  selectedDate.value = current.date
  activeTaskId.value = ''
  routeTaskOpened = false
  syncQuery({ review_task: null, retest_id: null, review_notice: null })
  await loadSchedule()
}

async function changeCourse() {
  activeTaskId.value = ''
  routeTaskOpened = false
  syncQuery({ review_task: null, retest_id: null, review_notice: null })
  await loadSchedule()
}

function selectDate(day) {
  selectedDate.value = day.date
  activeTaskId.value = ''
  actionError.value = ''
  failedAction.value = null
  retestPanel.value = null
  retestAnswer.value = ''
  syncQuery({ review_task: null, retest_id: null, review_notice: null })
}

async function startTask(task, { sync = true } = {}) {
  if (!task.action?.enabled) return
  if (sync) {
    await syncQuery(task.action.kind === 'delayed_retest'
      ? { review_task: null, retest_id: task.source_id, review_notice: null }
      : { review_task: task.id, retest_id: null, review_notice: null })
    return
  }
  activeTaskId.value = task.id
  actionError.value = ''
  failedAction.value = null
  actionNotice.value = ''
  retestPanel.value = null
  retestAnswer.value = ''
  retestFeedback.value = ''
  reviewDraft.value = { recall_score: 0.65, duration_minutes: 10 }
  if (isReviewAssessmentTask(task) && route.query.review_task === task.id) {
    const eventId = String(route.query.review_event || '')
    if (eventId) {
      assessmentEventByTask.value = { ...assessmentEventByTask.value, [task.id]: eventId }
      reviewedResourceTasks.value = { ...reviewedResourceTasks.value, [task.id]: true }
    }
  }
  if (task.action.kind === 'delayed_retest') await loadRetest(task)
}

function closeTask() {
  activeTaskId.value = ''
  actionError.value = ''
  failedAction.value = null
  retestPanel.value = null
  retestAnswer.value = ''
  syncQuery({ review_task: null, retest_id: null, review_notice: null })
}

async function completeReview(task) {
  if (taskBusy.value) return
  taskBusy.value = `complete:${task.id}`
  actionError.value = ''
  failedAction.value = null
  try {
    if (isReviewAssessmentTask(task) && !assessmentEventByTask.value[task.id]) {
      actionError.value = '请先回顾资源并完成智能组卷作答，再提交复习完成。'
      failedAction.value = null
      return
    }
    const result = await completeReviewScheduleTask(task.id, {
      idempotency_key: stableKey('complete', task.id),
      recall_score: reviewDraft.value.recall_score,
      duration_minutes: reviewDraft.value.duration_minutes,
      ...(assessmentEventByTask.value[task.id]
        ? { assessment_event_id: assessmentEventByTask.value[task.id] }
        : {}),
    })
    const noticeCode = result.created === false ? 'review-recorded' : 'review-completed'
    actionNotice.value = result.created === false
      ? '这次复习已记录，系统没有重复计入证据。'
      : `复习已完成，下一次安排在 ${formatTime(result.next_review_at)}。`
    activeTaskId.value = ''
    await syncQuery({ review_task: null, retest_id: null, review_notice: noticeCode })
  } catch (exception) {
    actionError.value = errorMessage(exception, '复习结果提交失败，当前选择已保留，请重试。')
    failedAction.value = { kind: 'complete', taskId: task.id }
  } finally {
    taskBusy.value = ''
  }
}

async function loadRetest(task) {
  taskBusy.value = `retest-load:${task.id}`
  actionError.value = ''
  failedAction.value = null
  try {
    retestPanel.value = await getM5RetestTask(task.source_id)
  } catch (exception) {
    actionError.value = errorMessage(exception, '复测题目加载失败，请重试。')
    failedAction.value = { kind: 'retest-load', taskId: task.id }
  } finally {
    taskBusy.value = ''
  }
}

function retestOptionValue(option, index) {
  if (typeof option === 'object' && option) return String(option.value || option.id || String.fromCharCode(65 + index))
  const matched = String(option).match(/^\s*([A-Z])(?:[.、:：\s]|$)/i)
  return matched ? matched[1].toUpperCase() : String.fromCharCode(65 + index)
}

function retestOptionLabel(option) {
  return typeof option === 'object' && option ? (option.label || option.text || option.value) : option
}

async function submitRetestAnswer(task) {
  if (!retestPanel.value || !String(retestAnswer.value || '').trim() || taskBusy.value) return
  taskBusy.value = `retest-submit:${task.id}`
  actionError.value = ''
  failedAction.value = null
  try {
    const hasOptions = Array.isArray(retestPanel.value.question?.options) && retestPanel.value.question.options.length > 0
    const result = await submitM5Retest(task.source_id, {
      idempotency_key: stableKey('retest', task.id),
      answer: hasOptions ? { choice: retestAnswer.value } : { text: retestAnswer.value },
    })
    if (result.task.status === 'completed') {
      actionNotice.value = '复测通过，服务端证据已回流画像与学习路径。'
      activeTaskId.value = ''
      await syncQuery({ review_task: null, retest_id: null, review_notice: 'retest-completed' })
    } else {
      retestFeedback.value = result.attempt.grading_status === 'manual_required'
        ? '当前题目需要进一步审核，尚未形成掌握证据。'
        : '本次尚未通过，答案已保留，可以复习后再次提交。'
    }
  } catch (exception) {
    actionError.value = errorMessage(exception, '复测提交失败，当前答案已保留，请重试。')
    failedAction.value = { kind: 'retest-submit', taskId: task.id }
  } finally {
    taskBusy.value = ''
  }
}

async function generateResources(task) {
  if (taskBusy.value || !task.resource_generation?.ready) return
  taskBusy.value = `resources:${task.id}`
  actionError.value = ''
  failedAction.value = null
  try {
    const created = await createReviewResourceJob(task.id, stableKey('resources', task.id))
    let job = created
    try {
      job = await executeGenerationJob(created.job_id)
    } catch (exception) {
      const code = exception?.response?.data?.detail?.code || exception?.detail?.code
      if (code !== 'resource_generation.demo_disabled') throw exception
    }
    await router.push({
      name: 'ResourceBundle',
      params: { bundleId: job.job_id || created.job_id },
      query: { course_id: task.course_id, return_to: route.fullPath },
    })
  } catch (exception) {
    actionError.value = errorMessage(exception, '资源包创建失败，已完成的内容不会丢失，请重试。')
    failedAction.value = { kind: 'resources', taskId: task.id }
  } finally {
    taskBusy.value = ''
  }
}

async function retryFailedAction() {
  const failure = failedAction.value
  if (!failure) return
  const task = schedule.value.tasks.find(item => item.id === failure.taskId)
  if (!task) {
    await loadSchedule()
    return
  }
  if (failure.kind === 'complete') await completeReview(task)
  else if (failure.kind === 'retest-load') await loadRetest(task)
  else if (failure.kind === 'retest-submit') await submitRetestAnswer(task)
  else if (failure.kind === 'resources') await generateResources(task)
}

function openResources(task) {
  if (!task.course_id || !task.knowledge_point_id) return
  if (isReviewAssessmentTask(task)) {
    reviewedResourceTasks.value = { ...reviewedResourceTasks.value, [task.id]: true }
    actionNotice.value = '已打开当前知识点资源；请完成回顾后进入智能组卷。'
  }
  router.push({
    name: 'WorkspaceResources',
    query: {
      course_id: task.course_id,
      knowledge_point_id: task.knowledge_point_id,
      return_to: route.fullPath,
    },
  })
}

function openExam(task) {
  if (isReviewAssessmentTask(task)) {
    if (!hasReviewedResource(task)) {
      actionError.value = '请先打开并回顾当前知识点资源。'
      return
    }
    router.push({
      name: 'IntelligentExams',
      query: {
        course_id: task.course_id,
        knowledge_point_id: task.knowledge_point_id,
        review_task: task.id,
      },
    })
    return
  }
  if (task.exam_gate?.unlocked) {
    router.push({ name: 'IntelligentExams', query: { course_id: task.course_id } })
    return
  }
  router.push({ path: task.exam_gate?.next_route || '/workspace/path', query: { course_id: task.course_id || undefined } })
}

function openChat(task) {
  router.push(task.chat_route || '/learn')
}

function setView(view) {
  if (!['calendar', 'tools'].includes(view) || activeView.value === view) return
  activeView.value = view
  emit('view-change', view)
}

onMounted(() => loadSchedule({ keepNotice: Boolean(actionNotice.value) }))
</script>

<template>
  <section class="review-board" data-testid="review-schedule-board" aria-labelledby="review-schedule-title">
    <header class="review-board__header">
      <div class="review-board__heading">
        <h1 id="review-schedule-title">复习中心</h1>
        <p>按日期处理到期任务。完成条件由每项任务单独说明，真实提交后才会更新画像与路径。</p>
        <div class="review-board__summary" aria-label="本月复习摘要">
          <span>共 {{ schedule.summary?.total || 0 }} 项</span>
          <span>今日 {{ schedule.summary?.due || 0 }} 项</span>
          <span>逾期 {{ schedule.summary?.overdue || 0 }} 项</span>
          <span>完成 {{ schedule.summary?.completed || 0 }} 项</span>
        </div>
      </div>

      <div class="review-board__controls">
        <div class="review-board__views" aria-label="复习视图">
          <button
            type="button"
            :class="{ 'is-active': activeView === 'calendar' }"
            :aria-pressed="activeView === 'calendar'"
            @click="setView('calendar')"
          >日历安排</button>
          <button
            type="button"
            :class="{ 'is-active': activeView === 'tools' }"
            :aria-pressed="activeView === 'tools'"
            @click="setView('tools')"
          >复习工具与历史</button>
        </div>
        <label v-if="activeView === 'calendar'" class="review-board__course">
          <span>课程</span>
          <select v-model="courseId" aria-label="筛选复习课程" @change="changeCourse">
            <option v-for="course in courses" :key="course.id" :value="course.id">{{ course.title }}</option>
          </select>
        </label>
      </div>
    </header>

    <TaskState
      v-if="activeView === 'calendar' && actionNotice"
      class="review-board__state"
      state="success"
      title="复习状态已更新"
      :message="actionNotice"
    />
    <TaskState
      v-if="activeView === 'calendar' && actionError"
      class="review-board__state"
      state="error"
      title="当前操作没有完成"
      :message="actionError"
      :action-label="failedAction ? '重试当前操作' : ''"
      @action="retryFailedAction"
    />
    <TaskState
      v-if="activeView === 'calendar' && loadError"
      class="review-board__state"
      state="error"
      title="复习安排暂时无法加载"
      :message="loadError"
      action-label="重新加载"
      @action="loadSchedule"
    />

    <div v-show="activeView === 'calendar'" class="review-schedule" :aria-busy="loading">
      <section class="review-calendar" aria-label="真实复习月历">
        <header class="review-calendar__toolbar">
          <div>
            <strong>{{ monthLabel }}</strong>
            <span>Asia/Shanghai</span>
          </div>
          <div class="review-calendar__actions">
            <button type="button" title="上个月" aria-label="查看上个月" @click="changeMonth(-1)">
              <ChevronLeft :size="18" />
            </button>
            <button type="button" class="review-calendar__today" @click="returnToday">回到今天</button>
            <button type="button" title="下个月" aria-label="查看下个月" @click="changeMonth(1)">
              <ChevronRight :size="18" />
            </button>
          </div>
        </header>

        <div class="review-calendar__weekdays" aria-hidden="true">
          <span v-for="weekday in schedule.weekdays" :key="weekday">{{ weekday }}</span>
        </div>

        <div v-if="loading" class="review-calendar__loading" data-testid="review-calendar-loading">
          <Loader2 :size="22" class="review-spin" />
          <span>正在读取真实复习安排</span>
        </div>
        <div v-else class="review-calendar__grid" data-testid="review-calendar-grid">
          <button
            v-for="day in schedule.days"
            :key="day.date"
            type="button"
            class="review-day"
            :data-date="day.date"
            :class="[
              `review-day--${day.state}`,
              { 'is-selected': day.date === selectedDate, 'is-outside': !day.in_month },
            ]"
            :aria-label="`${formatDate(day.date, { month: 'long', day: 'numeric' })}，${daySummary(day)}`"
            :aria-pressed="day.date === selectedDate"
            @click="selectDate(day)"
          >
            <span class="review-day__number">{{ day.day }}</span>
            <span
              v-if="dayMarkerState(day)"
              class="review-day__marker"
              :class="`review-day__marker--${dayMarkerState(day)}`"
              aria-hidden="true"
            />
          </button>
        </div>

        <footer class="review-calendar__legend" aria-label="日历状态说明">
          <span><i class="legend-dot legend-dot--today" />今日</span>
          <span><i class="legend-dot legend-dot--overdue" />逾期</span>
          <span><i class="legend-dot legend-dot--future" />未来安排</span>
        </footer>
      </section>

      <aside class="review-agenda" aria-label="选中日期的复习任务">
        <header class="review-agenda__header">
          <div>
            <strong>{{ selectedDateLabel }}</strong>
            <span>{{ selectedDay?.counts?.total || 0 }} 项安排</span>
          </div>
          <Calendar :size="20" />
        </header>

        <div v-if="loading" class="review-agenda__loading">
          <span v-for="index in 3" :key="index" />
        </div>
        <div v-else-if="!selectedTasks.length" class="review-agenda__empty" data-testid="review-agenda-empty">
          <Calendar :size="28" />
          <strong>这一天没有复习安排</strong>
          <p>回到今天查看当前任务，或选择日历中带数量的日期。</p>
          <button type="button" class="ui-button ui-button--secondary" @click="returnToday">回到今天</button>
        </div>
        <div v-else class="review-agenda__list" data-testid="review-agenda-list">
          <article
            v-for="task in selectedTasks"
            :key="task.id"
            class="review-task"
            :class="{ 'is-active': activeTaskId === task.id }"
            :data-task-id="task.id"
          >
            <div class="review-task__summary">
              <div class="review-task__icon" aria-hidden="true">
                <CheckCircle2 v-if="task.status === 'completed'" :size="18" />
                <AlertTriangle v-else-if="task.status === 'overdue'" :size="18" />
                <Clock v-else :size="18" />
              </div>
              <div class="review-task__copy">
                <div class="review-task__title">
                  <strong>{{ task.knowledge_point_title }}</strong>
                  <span :class="`review-status review-status--${task.status}`">{{ taskStatus(task) }}</span>
                </div>
                <p>{{ task.reason }}</p>
                <dl>
                  <div><dt>到期</dt><dd>{{ formatTime(task.due_at) }}</dd></div>
                  <div><dt>安排</dt><dd>{{ humanTaskType(task) }}</dd></div>
                  <div><dt>方式</dt><dd>{{ task.method }}</dd></div>
                  <div><dt>完成</dt><dd>{{ task.completion_rule }}</dd></div>
                </dl>
              </div>
              <button
                v-if="task.action?.enabled"
                type="button"
                class="review-task__enter"
                :aria-expanded="activeTaskId === task.id"
                @click="activeTaskId === task.id ? closeTask() : startTask(task)"
              >
                {{ activeTaskId === task.id ? '收起' : task.action.label }}
                <ArrowRight :size="16" />
              </button>
              <span v-else class="review-task__done">已记录</span>
            </div>

            <section v-if="activeTaskId === task.id" class="review-task__workspace" aria-label="当前复习任务操作区">
              <div class="review-task__workspace-head">
                <div>
                  <strong>完成当前复习</strong>
                  <span>{{ task.completion_rule }}</span>
                </div>
                <button type="button" class="review-link" @click="closeTask">关闭</button>
              </div>

              <template v-if="isReviewAssessmentTask(task)">
                <div class="review-sequence" data-testid="review-assessment-sequence">
                  <article :class="{ 'is-complete': hasReviewedResource(task) }">
                    <strong>1. 回顾知识点资源</strong>
                    <span>{{ hasReviewedResource(task) ? '已打开当前课程资源，可以进入智能组卷。' : '先查看当前课程授权资源，再开始作答。' }}</span>
                    <button type="button" class="ui-button ui-button--secondary" @click="openResources(task)">
                      <BookOpen :size="16" />{{ hasReviewedResource(task) ? '再次查看资源' : '打开资源并回顾' }}
                    </button>
                  </article>
                  <article :class="{ 'is-complete': Boolean(assessmentEventByTask[task.id]) }">
                    <strong>2. 完成智能组卷作答</strong>
                    <span>{{ assessmentEventByTask[task.id] ? '服务端已返回本知识点的判分事件。' : '题目会绑定当前知识点和课程上下文，提交后才产生复习证据。' }}</span>
                    <button type="button" class="ui-button ui-button--secondary" :disabled="!hasReviewedResource(task)" @click="openExam(task)">
                      <ListChecks :size="16" />{{ assessmentEventByTask[task.id] ? '重新查看组卷结果' : '进入智能组卷' }}
                    </button>
                  </article>
                </div>
                <label class="duration-field">
                  <span>实际复习时长</span>
                  <input v-model.number="reviewDraft.duration_minutes" type="number" min="1" max="240" />
                  <em>分钟</em>
                </label>
                <button
                  type="button"
                  class="ui-button ui-button--primary review-primary-action"
                  :disabled="Boolean(taskBusy) || !assessmentEventByTask[task.id]"
                  @click="completeReview(task)"
                >
                  <Loader2 v-if="taskBusy === `complete:${task.id}`" :size="17" class="review-spin" />
                  <CheckCircle2 v-else :size="17" />
                  {{ taskBusy === `complete:${task.id}` ? '正在提交' : '提交复习完成' }}
                </button>
              </template>

              <template v-else-if="task.action.kind === 'review_feedback'">
                <fieldset class="recall-fieldset">
                  <legend>这次回忆的实际感受</legend>
                  <label v-for="option in recallOptions" :key="option.value" :class="{ 'is-selected': reviewDraft.recall_score === option.value }">
                    <input v-model.number="reviewDraft.recall_score" type="radio" name="recall-score" :value="option.value" />
                    <span><strong>{{ option.label }}</strong><small>{{ option.detail }}</small></span>
                  </label>
                </fieldset>
                <label class="duration-field">
                  <span>实际复习时长</span>
                  <input v-model.number="reviewDraft.duration_minutes" type="number" min="1" max="240" />
                  <em>分钟</em>
                </label>
                <button
                  type="button"
                  class="ui-button ui-button--primary review-primary-action"
                  :disabled="Boolean(taskBusy)"
                  @click="completeReview(task)"
                >
                  <Loader2 v-if="taskBusy === `complete:${task.id}`" :size="17" class="review-spin" />
                  <CheckCircle2 v-else :size="17" />
                  {{ taskBusy === `complete:${task.id}` ? '正在提交' : '完成复习并更新安排' }}
                </button>
              </template>

              <template v-else-if="task.action.kind === 'delayed_retest'">
                <div v-if="taskBusy === `retest-load:${task.id}`" class="inline-loading">
                  <Loader2 :size="18" class="review-spin" />正在加载真实复测题目
                </div>
                <div v-else-if="retestPanel" class="retest-workspace">
                  <strong>{{ retestPanel.question?.prompt }}</strong>
                  <div v-if="retestPanel.question?.options?.length" class="retest-options">
                    <label v-for="(option, index) in retestPanel.question.options" :key="retestOptionValue(option, index)">
                      <input v-model="retestAnswer" type="radio" :value="retestOptionValue(option, index)" />
                      <span>{{ retestOptionLabel(option) }}</span>
                    </label>
                  </div>
                  <textarea v-else v-model="retestAnswer" rows="4" placeholder="输入你的复测答案" />
                  <p v-if="retestFeedback" class="retest-feedback">{{ retestFeedback }}</p>
                  <button
                    type="button"
                    class="ui-button ui-button--primary review-primary-action"
                    :disabled="Boolean(taskBusy) || !String(retestAnswer || '').trim()"
                    @click="submitRetestAnswer(task)"
                  >
                    <Loader2 v-if="taskBusy === `retest-submit:${task.id}`" :size="17" class="review-spin" />
                    <ListChecks v-else :size="17" />
                    {{ taskBusy === `retest-submit:${task.id}` ? '正在判分' : '提交复测' }}
                  </button>
                </div>
                <button v-else type="button" class="ui-button ui-button--secondary" @click="loadRetest(task)">
                  <RefreshCw :size="17" />重新加载题目
                </button>
              </template>

              <div class="review-task__links">
                <button
                  v-if="task.source_type === 'sm2_review_plan'"
                  type="button"
                  :disabled="Boolean(taskBusy) || noteBusyId === task.id"
                  @click="emit('note', task)"
                >
                  <Loader2 v-if="noteBusyId === task.id" :size="17" class="review-spin" />
                  <NotebookPen v-else :size="17" />{{ noteBusyId === task.id ? '正在归档' : '记笔记' }}
                </button>
                <button type="button" :disabled="!task.course_id || !task.knowledge_point_id" @click="openResources(task)">
                  <BookOpen :size="17" />查看已有资源
                </button>
                <button
                  type="button"
                  :disabled="Boolean(taskBusy) || !task.resource_generation?.ready"
                  :title="task.resource_generation?.block_reason || '生成九类复习资源包'"
                  @click="generateResources(task)"
                >
                  <Loader2 v-if="taskBusy === `resources:${task.id}`" :size="17" class="review-spin" />
                  <Boxes v-else :size="17" />生成复习资源包
                </button>
                <button type="button" @click="openChat(task)">
                  <MessageSquareText :size="17" />带当前上下文提问
                </button>
                <button type="button" @click="openExam(task)">
                  <ListChecks :size="17" />{{ task.exam_gate?.unlocked ? '进入智能组卷' : '查看组卷解锁条件' }}
                </button>
              </div>
              <p v-if="!task.resource_generation?.ready" class="review-task__boundary">
                资源包暂不可生成：{{ task.resource_generation?.block_reason || '当前上下文不完整。' }}
              </p>
              <p class="review-task__boundary">
                {{ task.exam_gate?.message }}{{ task.exam_gate?.unlocked ? '' : ' 复习页不会增加或绕过任何解锁条件。' }}
              </p>
            </section>
          </article>
        </div>
      </aside>
    </div>

    <div
      v-show="activeView === 'tools'"
      class="review-tools-surface"
      data-testid="review-tools-surface"
      aria-label="复习工具与历史"
    >
      <slot name="tools">
        <div class="review-tools-surface__empty">当前页面没有可用的复习工具。</div>
      </slot>
    </div>

    <footer v-if="activeView === 'calendar'" class="review-board__footer">
      <RotateCcw :size="17" />
      <span>切换月份、课程或日期只改变当前视图，不会写入学习证据。</span>
    </footer>
  </section>
</template>

<style scoped>
.review-board {
  width: min(100%, 1240px);
  margin: 0 auto;
  color: var(--color-text);
  font-family: var(--font-sans);
}

.review-board__header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 32px;
  margin-bottom: 20px;
}

.review-board__heading {
  min-width: 0;
}

.review-board__heading h1 {
  margin: 0;
  font-size: 24px;
  font-weight: 700;
  line-height: 1.35;
}

.review-board__heading > p {
  max-width: 68ch;
  margin: 6px 0 0;
  color: var(--color-text-secondary);
  font-size: 15px;
  line-height: 1.6;
}

.review-board__summary {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 18px;
  margin-top: 12px;
  color: var(--color-text-muted);
  font-size: 14px;
  font-variant-numeric: tabular-nums;
}

.review-board__summary span + span {
  position: relative;
}

.review-board__summary span + span::before {
  position: absolute;
  top: 50%;
  left: -10px;
  width: 2px;
  height: 2px;
  border-radius: 50%;
  background: var(--color-border-strong);
  content: '';
}

.review-board__controls {
  display: flex;
  flex: 0 0 auto;
  align-items: flex-end;
  gap: 12px;
}

.review-board__views {
  display: flex;
  min-height: 40px;
  padding: 3px;
  border: 1px solid var(--color-border);
  border-radius: 6px;
  background: var(--color-surface-subtle);
}

.review-board__views button {
  min-height: 32px;
  padding: 0 12px;
  color: var(--color-text-secondary);
  border: 0;
  border-radius: 4px;
  background: transparent;
  font-size: 14px;
  cursor: pointer;
}

.review-board__views button.is-active {
  color: #ffffff;
  background: var(--color-accent);
  font-weight: 600;
}

.review-board__course {
  display: grid;
  gap: 4px;
  color: var(--color-text-muted);
  font-size: 14px;
}

.review-board__course select {
  width: 190px;
  min-height: 40px;
  padding: 0 34px 0 11px;
  color: var(--color-text);
  border: 1px solid var(--color-border-strong);
  border-radius: 6px;
  background: var(--color-surface);
  font-size: 14px;
}

.review-board__state {
  margin-bottom: 12px;
}

.review-schedule {
  display: grid;
  min-height: 596px;
  grid-template-columns: minmax(0, 1.38fr) minmax(380px, 1fr);
  overflow: hidden;
  border: 1px solid var(--color-border);
  border-radius: 8px;
  background: var(--color-surface);
}

.review-tools-surface {
  min-height: 596px;
  overflow: hidden;
  border: 1px solid var(--color-border);
  border-radius: 8px;
  background: var(--color-surface);
}

.review-tools-surface__empty {
  display: grid;
  min-height: 300px;
  place-items: center;
  padding: 24px;
  color: var(--color-text-muted);
  font-size: 14px;
}

.review-calendar,
.review-agenda {
  min-width: 0;
}

.review-calendar {
  padding: 20px;
  border-right: 1px solid var(--color-border);
}

.review-calendar__toolbar,
.review-agenda__header {
  display: flex;
  min-height: 48px;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}

.review-calendar__toolbar > div:first-child,
.review-agenda__header > div {
  display: grid;
  gap: 2px;
}

.review-calendar__toolbar strong,
.review-agenda__header strong {
  font-size: 17px;
  font-weight: 650;
}

.review-calendar__toolbar span,
.review-agenda__header span {
  color: var(--color-text-muted);
  font-size: 14px;
}

.review-calendar__actions {
  display: flex;
  align-items: center;
  gap: 6px;
}

.review-calendar__actions button {
  display: inline-grid;
  min-width: 36px;
  min-height: 36px;
  place-items: center;
  color: var(--color-text-secondary);
  border: 1px solid var(--color-border);
  border-radius: 6px;
  background: var(--color-surface);
  cursor: pointer;
}

.review-calendar__actions button:hover {
  color: var(--color-text);
  border-color: var(--color-border-strong);
  background: var(--color-surface-subtle);
}

.review-calendar__actions .review-calendar__today {
  padding: 0 11px;
  font-size: 14px;
}

.review-calendar__weekdays,
.review-calendar__grid {
  display: grid;
  grid-template-columns: repeat(7, minmax(0, 1fr));
}

.review-calendar__weekdays {
  margin-top: 14px;
  border-bottom: 1px solid var(--color-border);
}

.review-calendar__weekdays span {
  padding: 8px 4px;
  color: var(--color-text-muted);
  font-size: 14px;
  text-align: center;
}

.review-calendar__grid {
  border-left: 1px solid var(--color-border);
}

.review-day {
  position: relative;
  display: flex;
  min-width: 0;
  min-height: 64px;
  align-items: flex-start;
  padding: 11px 12px;
  color: var(--color-text-secondary);
  border: 0;
  border-right: 1px solid var(--color-border);
  border-bottom: 1px solid var(--color-border);
  background: var(--color-surface);
  text-align: left;
  cursor: pointer;
}

.review-day:hover {
  background: var(--color-surface-subtle);
}

.review-day.is-selected {
  color: var(--color-text);
  background: var(--color-surface);
  box-shadow: inset 0 0 0 2px var(--color-accent);
}

.review-day.is-outside:not(.is-selected) {
  color: var(--color-text-muted);
  background: #fafbfb;
  opacity: 0.62;
}

.review-day__number {
  font-size: 15px;
  font-weight: 650;
  font-variant-numeric: tabular-nums;
}

.review-day__marker {
  position: absolute;
  top: 12px;
  right: 12px;
  width: 9px;
  height: 9px;
  border-radius: 50%;
}

.review-day__marker--today { background: #2f9e64; }
.review-day__marker--overdue { background: var(--color-danger); }
.review-day__marker--future { background: #466f91; }

.review-calendar__loading {
  display: flex;
  min-height: 432px;
  align-items: center;
  justify-content: center;
  gap: 10px;
  color: var(--color-text-muted);
  border: 1px solid var(--color-border);
  border-top: 0;
  font-size: 14px;
}

.review-calendar__legend {
  display: flex;
  flex-wrap: wrap;
  gap: 14px;
  padding-top: 14px;
  color: var(--color-text-muted);
  font-size: 14px;
}

.review-calendar__legend span {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.legend-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--color-border-strong);
}

.legend-dot--today { background: #2f9e64; }
.legend-dot--overdue { background: var(--color-danger); }
.legend-dot--future { background: #466f91; }

.review-agenda {
  display: flex;
  max-height: 596px;
  flex-direction: column;
  background: #fbfcfc;
}

.review-agenda__header {
  flex: 0 0 auto;
  padding: 18px 20px 14px;
  border-bottom: 1px solid var(--color-border);
}

.review-agenda__header > svg {
  color: var(--color-text-muted);
}

.review-agenda__list {
  min-height: 0;
  overflow-y: auto;
}

.review-task {
  background: var(--color-surface);
  border-bottom: 1px solid var(--color-border);
}

.review-task__summary {
  display: grid;
  grid-template-columns: 28px minmax(0, 1fr) auto;
  align-items: start;
  gap: 10px;
  padding: 16px 18px;
}

.review-task__icon {
  display: grid;
  width: 28px;
  height: 28px;
  place-items: center;
  color: var(--color-text-muted);
  border-radius: 6px;
  background: var(--color-surface-subtle);
}

.review-task__copy {
  min-width: 0;
}

.review-task__title {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 8px;
}

.review-task__title > strong {
  min-width: 0;
  overflow-wrap: anywhere;
  font-size: 15px;
  font-weight: 650;
}

.review-status {
  flex: 0 0 auto;
  color: var(--color-text-secondary);
  font-size: 14px;
  font-weight: 600;
}

.review-status--overdue { color: var(--color-danger); }
.review-status--completed { color: var(--color-success); }

.review-task__copy > p {
  margin: 5px 0 9px;
  color: var(--color-text-secondary);
  font-size: 14px;
  line-height: 1.5;
}

.review-task dl {
  display: grid;
  gap: 5px;
  margin: 0;
}

.review-task dl div {
  display: grid;
  grid-template-columns: 42px minmax(0, 1fr);
  gap: 6px;
  font-size: 14px;
  line-height: 1.45;
}

.review-task dt {
  color: var(--color-text-muted);
}

.review-task dd {
  margin: 0;
  color: var(--color-text-secondary);
}

.review-task__enter,
.review-link {
  padding: 0;
  color: var(--color-accent);
  border: 0;
  background: transparent;
  font-size: 14px;
  font-weight: 650;
  cursor: pointer;
}

.review-task__enter {
  display: inline-flex;
  min-height: 36px;
  align-items: center;
  gap: 4px;
  white-space: nowrap;
}

.review-task__done {
  color: var(--color-success);
  font-size: 14px;
  font-weight: 650;
}

.review-task__workspace {
  padding: 16px 18px 18px 56px;
  border-top: 1px solid var(--color-border);
  background: var(--color-surface-subtle);
}

.review-task__workspace-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 14px;
}

.review-task__workspace-head > div {
  display: grid;
  gap: 2px;
}

.review-task__workspace-head strong {
  font-size: 15px;
}

.review-task__workspace-head span {
  color: var(--color-text-secondary);
  font-size: 14px;
  line-height: 1.5;
}

.review-sequence {
  display: grid;
  gap: 8px;
}

.review-sequence article {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 4px 12px;
  align-items: center;
  padding: 12px;
  border: 1px solid var(--color-border);
  border-radius: 6px;
  background: var(--color-surface);
}

.review-sequence article.is-complete {
  border-color: var(--color-accent);
}

.review-sequence article strong,
.review-sequence article span {
  grid-column: 1;
}

.review-sequence article strong {
  font-size: 14px;
}

.review-sequence article span {
  color: var(--color-text-secondary);
  font-size: 14px;
  line-height: 1.45;
}

.review-sequence article button {
  grid-column: 2;
  grid-row: 1 / span 2;
  white-space: nowrap;
}

.recall-fieldset {
  display: grid;
  gap: 8px;
  margin: 0;
  padding: 0;
  border: 0;
}

.recall-fieldset legend {
  margin-bottom: 8px;
  font-size: 14px;
  font-weight: 650;
}

.recall-fieldset label {
  display: grid;
  grid-template-columns: 18px minmax(0, 1fr);
  gap: 8px;
  padding: 9px 10px;
  border: 1px solid var(--color-border);
  border-radius: 6px;
  background: var(--color-surface);
  cursor: pointer;
}

.recall-fieldset label.is-selected {
  border-color: var(--color-accent);
  box-shadow: inset 0 0 0 1px var(--color-accent);
}

.recall-fieldset input {
  margin-top: 4px;
}

.recall-fieldset label span {
  display: grid;
  gap: 2px;
}

.recall-fieldset strong,
.recall-fieldset small {
  font-size: 14px;
}

.recall-fieldset small {
  color: var(--color-text-secondary);
}

.duration-field {
  display: grid;
  grid-template-columns: 1fr 82px auto;
  align-items: center;
  gap: 8px;
  margin-top: 12px;
  color: var(--color-text-secondary);
  font-size: 14px;
}

.duration-field input {
  width: 82px;
  min-height: 38px;
  padding: 0 8px;
}

.duration-field em {
  font-style: normal;
}

.review-primary-action {
  width: 100%;
  margin-top: 14px;
}

.review-task__links {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
  margin-top: 14px;
}

.review-task__links button {
  display: inline-flex;
  min-height: 38px;
  align-items: center;
  justify-content: flex-start;
  gap: 7px;
  padding: 0 10px;
  color: var(--color-text-secondary);
  border: 1px solid var(--color-border);
  border-radius: 6px;
  background: var(--color-surface);
  font-size: 14px;
  cursor: pointer;
}

.review-task__links button:hover:not(:disabled) {
  color: var(--color-text);
  border-color: var(--color-border-strong);
}

.review-task__links button:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.review-task__boundary,
.retest-feedback {
  margin: 10px 0 0;
  color: var(--color-text-secondary);
  font-size: 14px;
  line-height: 1.5;
}

.inline-loading {
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--color-text-secondary);
  font-size: 14px;
}

.retest-workspace {
  display: grid;
  gap: 10px;
}

.retest-workspace > strong {
  font-size: 15px;
  line-height: 1.55;
}

.retest-options {
  display: grid;
  gap: 7px;
}

.retest-options label {
  display: grid;
  grid-template-columns: 18px minmax(0, 1fr);
  gap: 8px;
  padding: 9px 10px;
  border: 1px solid var(--color-border);
  border-radius: 6px;
  background: var(--color-surface);
  font-size: 14px;
  cursor: pointer;
}

.retest-workspace textarea {
  width: 100%;
  resize: vertical;
  padding: 10px;
  font-size: 14px;
}

.review-agenda__loading {
  display: grid;
  gap: 1px;
}

.review-agenda__loading span {
  height: 132px;
  background: var(--color-surface-subtle);
}

.review-agenda__empty {
  display: flex;
  min-height: 360px;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 28px;
  color: var(--color-text-muted);
  text-align: center;
}

.review-agenda__empty strong {
  margin-top: 12px;
  color: var(--color-text);
  font-size: 16px;
}

.review-agenda__empty p {
  max-width: 34ch;
  margin: 6px 0 16px;
  font-size: 14px;
  line-height: 1.6;
}

.review-board__footer {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 2px 0;
  color: var(--color-text-muted);
  font-size: 14px;
}

.review-spin {
  animation: review-spin 900ms linear infinite;
}

@keyframes review-spin {
  to { transform: rotate(360deg); }
}
</style>
