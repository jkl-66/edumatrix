<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  AlertCircle, ArrowLeft, BookOpen, Check, CheckCircle2, ChevronLeft, ChevronRight,
  ClipboardList, FileCheck2, History, ListChecks, LoaderCircle, LockKeyhole, Minus,
  Play, Plus, RefreshCw, Send, Target, Timer,
} from '@lucide/vue'
import {
  answerM5FormalSitting, assignM5FormalExam, completeM5FormalReview,
  createM5FormalExam, createM5IntelligentExam, generateM5FormalReport,
  getM5IntelligentExamContext, getM5TodayWork, listM5AssessmentQuestions, listM5FormalExams,
  listM5FormalReviews, startM5FormalSitting, submitM5FormalSitting,
  transitionM5FormalExam,
} from '../api/m5'
import { listKnowledgeCourseShelf } from '../api/knowledge'
import AggregationStatus from '../components/AggregationStatus.vue'
import { useCourseContextStore } from '../stores/courseContext'
import {
  calculateAssessmentDuration,
  courseOptionsFromShelf,
  sortKnowledgePoints,
  todayKnowledgePointIds as getTodayKnowledgePointIds,
} from '../utils/assessmentConfiguration'

const route = useRoute()
const router = useRouter()
const courseContext = useCourseContextStore()
const role = localStorage.getItem('edumatrix_role') || 'student'
const manager = computed(() => ['teacher', 'admin'].includes(role))
const courseId = computed(() => String(
  route.query.course_id
  || courseContext.contextRef?.courseId
  || '',
))
const studentNeedsCourse = computed(() => !manager.value && !courseId.value)
const reviewTaskId = computed(() => String(route.query.review_task || ''))
const reviewScoped = computed(() => Boolean(reviewTaskId.value))

const loading = ref(true)
const busy = ref(false)
const savingItemId = ref('')
const error = ref('')
const notice = ref('')
const context = ref(null)
const gate = ref(null)
const exams = ref([])
const questions = ref([])
const reviews = ref([])
const courseCatalog = ref([])
const todayWork = ref([])
const todayWorkError = ref('')
const todayWorkLoading = ref(false)
const generationStatus = ref('idle')
const selectedId = ref(String(route.params.examId || ''))
const currentQuestionIndex = ref(0)
const reportEnvelope = ref(null)
const now = ref(Date.now())
const answers = reactive({})
const drafts = reactive({})
const saveStates = reactive({})
const pendingSaveKeys = reactive({})
const reviewDrafts = reactive({})
const assignLearner = ref('')
const formInitialized = ref(false)
let timerHandle = null

const createForm = reactive({ course_id: '', title: '', duration_minutes: 60, questionIds: [] })
const learnerForm = reactive({
  title: '今日智能组卷',
  theme: '检验今日学习成果',
  chapter_ids: [],
  knowledge_point_ids: [],
  difficulty: 'adaptive',
  source_limit: 8,
  counts: {
    single_choice: 0,
    multiple_choice: 0,
    true_false: 0,
    fill_blank: 0,
    short_answer: 0,
  },
})
const generationKey = ref(newGenerationKey())

const typeLabels = {
  single_choice: '单选题',
  multiple_choice: '多选题',
  true_false: '判断题',
  fill_blank: '填空题',
  short_answer: '简答题',
  code: '代码题',
  open_task: '开放任务',
}
const configurableTypes = ['single_choice', 'multiple_choice', 'true_false', 'fill_blank', 'short_answer']

function optionLabel(option, index) {
  const match = String(option || '').trim().match(/^([A-D])(?:[.、:)]\s*|\s+)/i)
  return match ? match[1].toUpperCase() : String.fromCharCode(65 + index)
}

function optionText(option) {
  return String(option || '').trim().replace(/^[A-D](?:[.、:)]\s*|\s+)/i, '')
}

function publicErrorReason(item) {
  const value = String(item?.error_reason || '').trim()
  if (!value) return ''
  if (/\b(?:f\d+-)?(?:kp|event|trace|run)-[a-z0-9-]{6,}\b|\b[a-f0-9]{24,}\b/i.test(value)) {
    const subject = item?.knowledge_point?.title || '本题知识点'
    return `${subject}的关键条件或判断边界仍需巩固，请结合上方解析复习后再测。`
  }
  return value
}

const difficultyLabels = {
  easy: '基础巩固',
  balanced: '均衡检验',
  challenging: '进阶挑战',
  adaptive: '画像自适应',
}
const selected = computed(() => exams.value.find(item => item.id === selectedId.value) || null)
const sitting = computed(() => selected.value?.sitting || null)
const generationContext = computed(() => selected.value?.version?.generation_context || {})
const liveGenerationEnabled = computed(() => context.value?.llm_generation_required === true)
const generationModeLabel = computed(() => (
  generationContext.value.generation_mode === 'question_bank_fallback'
    ? '已审核题库组卷'
    : '按当前学习进度组卷'
))
const generationModeReason = computed(() => (
  generationContext.value.question_bank_fallback?.used
    ? '本次题目从已审核题库中选取，仍然围绕当前课程和知识点。'
    : '题目围绕当前课程知识点和你的近期学习情况安排，难度与题型已经准备完成。'
))
const canAnswer = computed(() => sitting.value?.status === 'in_progress' && remainingSeconds.value > 0)
const currentQuestion = computed(() => selected.value?.items?.[currentQuestionIndex.value] || null)
const courseTitle = computed(() => (
  context.value?.course?.title
  || localStorage.getItem('edumatrix_course_title')
  || '当前课程'
))
const completedCount = computed(() => gate.value?.completed_task_ids?.length || 0)
const requiredCount = computed(() => gate.value?.required_task_ids?.length || 0)
const requestedCount = computed(() => configurableTypes.reduce(
  (sum, type) => sum + Number(learnerForm.counts[type] || 0), 0,
))
const availableKnowledgePoints = computed(() => {
  const points = context.value?.knowledge_points || []
  const scoped = learnerForm.chapter_ids.length
    ? points.filter(point => point.chapter_ids.some(id => learnerForm.chapter_ids.includes(id)))
    : points
  return sortKnowledgePoints(scoped, todayKnowledgePointIds.value)
})
const todayKnowledgePointIds = computed(() => getTodayKnowledgePointIds(todayWork.value, courseId.value))
const courseOptions = computed(() => {
  const options = courseOptionsFromShelf({ shelf: courseCatalog.value })
  const current = context.value?.course
  if (current?.id && !options.some(item => item.id === current.id)) options.unshift(current)
  return options
})
const computedDurationMinutes = computed(() => calculateAssessmentDuration(learnerForm.counts))
const blueprint = computed(() => configurableTypes
  .filter(type => learnerForm.counts[type] > 0)
  .map(type => ({
    type,
    label: typeLabels[type],
    requested: learnerForm.counts[type],
    available: availableCount(type),
  })))
const selectionComplete = computed(() => (
  requestedCount.value > 0
  && learnerForm.title.trim()
  && learnerForm.theme.trim()
  && (context.value?.approved_source_count || 0) > 0
  && configurableTypes.every(type => learnerForm.counts[type] <= availableCount(type))
))
const scopeLabel = computed(() => {
  if (learnerForm.knowledge_point_ids.length) return `${learnerForm.knowledge_point_ids.length} 个知识点`
  if (learnerForm.chapter_ids.length) return `${learnerForm.chapter_ids.length} 个章节`
  return '当前课程全部知识点'
})
const savedCount = computed(() => Object.keys(drafts).filter(id => drafts[id]).length)
const allDraftsSaved = computed(() => (
  Boolean(selected.value?.items?.length)
  && selected.value.items.every(item => Boolean(drafts[item.id]))
))
const unsavedCount = computed(() => Math.max(0, (selected.value?.items?.length || 0) - savedCount.value))
const reportData = computed(() => reportEnvelope.value?.report || null)
const historical = computed(() => exams.value.filter(item => item.id !== selectedId.value))
const remainingSeconds = computed(() => {
  if (!sitting.value?.due_at || sitting.value.status !== 'in_progress') return null
  const dueAt = parseUtcTimestamp(sitting.value.due_at)
  if (!Number.isFinite(dueAt)) return null
  return Math.max(0, Math.floor((dueAt - now.value) / 1000))
})
const remainingLabel = computed(() => {
  if (remainingSeconds.value === null) return '尚未开始'
  const minutes = Math.floor(remainingSeconds.value / 60)
  const seconds = remainingSeconds.value % 60
  return `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`
})

function newGenerationKey() {
  return `exam-${crypto.randomUUID()}`
}

function newAnswerKey() {
  return `answer-${crypto.randomUUID()}`
}

function parseUtcTimestamp(value) {
  if (!value) return Number.NaN
  return Date.parse(/[zZ]|[+-]\d\d:\d\d$/.test(value) ? value : `${value}Z`)
}

function messageFrom(value) {
  const detail = value?.detail || value?.response?.data?.detail
  return detail?.message || (typeof detail === 'string' ? detail : '') || value?.message || '操作失败，请保留当前页面后重试。'
}

function clearObject(target) {
  Object.keys(target).forEach(key => delete target[key])
}

function availableCount(type) {
  if (liveGenerationEnabled.value) return 50
  return Number(context.value?.question_type_counts?.[type] || 0)
}

function questionTypeAvailabilityLabel(type) {
  const bankCount = Number(context.value?.question_type_counts?.[type] || 0)
  return liveGenerationEnabled.value
    ? `大模型生成 · 题库现有 ${bankCount} 题仅作参考`
    : `无可用模型 · 题库现有 ${bankCount} 题`
}

function initializeLearnerForm() {
  if (formInitialized.value || !context.value) return
  const desired = { single_choice: 2, multiple_choice: 1, true_false: 1, fill_blank: 1, short_answer: 1 }
  configurableTypes.forEach((type) => {
    learnerForm.counts[type] = Math.min(desired[type], availableCount(type))
  })
  if (!requestedCount.value) {
    const first = configurableTypes.find(type => availableCount(type) > 0)
    if (first) learnerForm.counts[first] = 1
  }
  const requestedPoint = String(route.query.knowledge_point_id || '')
  if (requestedPoint && context.value.knowledge_points.some(item => item.id === requestedPoint)) {
    learnerForm.knowledge_point_ids = [requestedPoint]
  }
  formInitialized.value = true
}

function isTodayKnowledgePoint(point) {
  return todayKnowledgePointIds.value.includes(String(point?.id || ''))
}

function answerFromDraft(item, answer) {
  if (!answer) return item.question_type === 'multiple_choice' ? [] : ''
  if (item.question_type === 'single_choice') return answer.choice || ''
  if (item.question_type === 'multiple_choice') return Array.isArray(answer.choices) ? [...answer.choices] : []
  if (item.question_type === 'true_false') return typeof answer.value === 'boolean' ? answer.value : ''
  if (item.question_type === 'fill_blank') return Array.isArray(answer.blanks) ? answer.blanks.join(' | ') : ''
  if (item.question_type === 'code') return answer.code || ''
  return answer.text || ''
}

function hydrateExam(exam) {
  clearObject(answers)
  clearObject(drafts)
  clearObject(saveStates)
  clearObject(pendingSaveKeys)
  ;(exam?.items || []).forEach((item) => {
    answers[item.id] = item.question_type === 'multiple_choice' ? [] : ''
    saveStates[item.id] = 'empty'
  })
  ;(exam?.drafts || []).forEach((draft) => {
    const item = exam.items.find(candidate => candidate.id === draft.exam_item_id)
    if (!item) return
    drafts[item.id] = draft
    answers[item.id] = answerFromDraft(item, draft.answer)
    saveStates[item.id] = 'saved'
  })
  const firstIncomplete = (exam?.items || []).findIndex(item => !drafts[item.id])
  currentQuestionIndex.value = firstIncomplete >= 0 ? firstIncomplete : 0
}

function normalizeReportEnvelope(data) {
  if (data?.report?.report) {
    return {
      ...data.report,
      event_id: data.event_id,
      aggregation: data.aggregation,
      learning_feedback: data.learning_feedback,
      recoverable: data.recoverable,
      feedback_updates: data.feedback_updates,
    }
  }
  return data
}

function handleFeedbackRecovered(feedback) {
  if (!reportEnvelope.value) return
  reportEnvelope.value = {
    ...reportEnvelope.value,
    recoverable: false,
    learning_feedback: feedback || reportEnvelope.value.learning_feedback,
    aggregation: feedback || reportEnvelope.value.aggregation,
  }
  notice.value = '学习反馈已同步，画像、路径和复习安排已更新。'
}

async function load() {
  loading.value = true
  error.value = ''
  todayWorkError.value = ''
  if (studentNeedsCourse.value) {
    exams.value = []
    context.value = null
    gate.value = null
    todayWork.value = []
    try {
      const payload = await listKnowledgeCourseShelf()
      courseCatalog.value = courseOptionsFromShelf(payload)
    } catch (value) {
      courseCatalog.value = []
      error.value = messageFrom(value)
    }
    loading.value = false
    return
  }
  try {
    if (manager.value) {
      const [catalog, questionCatalog, reviewCatalog] = await Promise.all([
        listM5FormalExams(),
        listM5AssessmentQuestions({ course_id: courseId.value }),
        listM5FormalReviews(),
      ])
      exams.value = catalog.items || []
      questions.value = questionCatalog.items || []
      reviews.value = reviewCatalog.items || []
      reviews.value.forEach((review) => {
        if (!reviewDrafts[review.id]) {
          reviewDrafts[review.id] = { score: 0.8, note: '已根据冻结评分证据完成复核。' }
        }
      })
      createForm.course_id ||= courseId.value
    } else {
      const [catalog, examContext] = await Promise.all([
        listM5FormalExams(),
        getM5IntelligentExamContext(courseId.value),
      ])
      exams.value = catalog.items || []
      context.value = examContext
      gate.value = examContext.gate
      try {
        const shelf = await listKnowledgeCourseShelf()
        courseCatalog.value = courseOptionsFromShelf(shelf)
      } catch (value) {
        courseCatalog.value = []
      }
      await loadTodayWork()
      initializeLearnerForm()
      if (selectedId.value && !selected.value) {
        selectedId.value = ''
        await router.replace({
          path: '/workspace/assessment/exams',
          query: {
            course_id: courseId.value,
            ...(reviewTaskId.value ? { review_task: reviewTaskId.value } : {}),
            ...(route.query.knowledge_point_id ? { knowledge_point_id: route.query.knowledge_point_id } : {}),
          },
        })
      }
      if (selected.value) hydrateExam(selected.value)
    }
  } catch (value) {
    error.value = messageFrom(value)
  } finally {
    loading.value = false
  }
}

async function loadTodayWork() {
  if (!courseId.value || manager.value) return
  todayWorkLoading.value = true
  todayWorkError.value = ''
  try {
    const today = await getM5TodayWork(courseId.value)
    todayWork.value = (today.items || []).filter(item => !item.course_id || item.course_id === courseId.value)
  } catch (value) {
    todayWork.value = []
    todayWorkError.value = messageFrom(value)
  } finally {
    todayWorkLoading.value = false
  }
}

async function runManagerAction(callback, success) {
  busy.value = true
  error.value = ''
  notice.value = ''
  try {
    await callback()
    notice.value = success
    await load()
  } catch (value) {
    error.value = messageFrom(value)
  } finally {
    busy.value = false
  }
}

function markConfigChanged() {
  generationKey.value = newGenerationKey()
  if (generationStatus.value !== 'generating') generationStatus.value = 'idle'
}

function resetLearnerConfiguration() {
  learnerForm.chapter_ids = []
  learnerForm.knowledge_point_ids = []
  configurableTypes.forEach((type) => { learnerForm.counts[type] = 0 })
  learnerForm.difficulty = 'adaptive'
  learnerForm.source_limit = 8
  formInitialized.value = false
  generationKey.value = newGenerationKey()
  generationStatus.value = 'idle'
  selectedId.value = ''
  reportEnvelope.value = null
  clearObject(answers)
  clearObject(drafts)
  clearObject(saveStates)
  clearObject(pendingSaveKeys)
  context.value = null
  gate.value = null
  todayWork.value = []
}

function chooseCourse(nextCourseId) {
  const value = String(nextCourseId || '').trim()
  if (!value || value === courseId.value || busy.value) return
  const query = { course_id: value }
  if (reviewTaskId.value) query.review_task = reviewTaskId.value
  router.replace({ path: '/workspace/assessment/exams', query })
}

function changeCount(type, delta) {
  learnerForm.counts[type] = Math.max(0, Math.min(
    availableCount(type),
    learnerForm.counts[type] + delta,
  ))
  markConfigChanged()
}

function toggleChapter(chapterId) {
  const selectedChapters = new Set(learnerForm.chapter_ids)
  if (selectedChapters.has(chapterId)) selectedChapters.delete(chapterId)
  else selectedChapters.add(chapterId)
  learnerForm.chapter_ids = [...selectedChapters]
  const allowed = new Set(availableKnowledgePoints.value.map(item => item.id))
  learnerForm.knowledge_point_ids = learnerForm.knowledge_point_ids.filter(id => allowed.has(id))
  markConfigChanged()
}

function toggleKnowledgePoint(pointId) {
  const selectedPoints = new Set(learnerForm.knowledge_point_ids)
  if (selectedPoints.has(pointId)) selectedPoints.delete(pointId)
  else selectedPoints.add(pointId)
  learnerForm.knowledge_point_ids = [...selectedPoints]
  markConfigChanged()
}

async function createLearnerExam() {
  if (!gate.value?.unlocked || !selectionComplete.value) return
  busy.value = true
  generationStatus.value = 'generating'
  error.value = ''
  notice.value = ''
  try {
    const created = await createM5IntelligentExam({
      configuration: {
        idempotency_key: generationKey.value,
        course_id: courseId.value,
        ...(reviewTaskId.value ? { review_task_id: reviewTaskId.value } : {}),
        title: learnerForm.title.trim(),
        theme: learnerForm.theme.trim(),
        duration_minutes: computedDurationMinutes.value,
        chapter_ids: [...learnerForm.chapter_ids],
        knowledge_point_ids: [...learnerForm.knowledge_point_ids],
        difficulty: learnerForm.difficulty,
        question_type_counts: Object.fromEntries(
          configurableTypes
            .filter(type => learnerForm.counts[type] > 0)
            .map(type => [type, Number(learnerForm.counts[type])]),
        ),
        source_limit: Number(learnerForm.source_limit),
      },
    })
    const existingIndex = exams.value.findIndex(item => item.id === created.id)
    if (existingIndex >= 0) exams.value.splice(existingIndex, 1, created)
    else exams.value.unshift(created)
    selectedId.value = created.id
    generationStatus.value = 'complete'
    reportEnvelope.value = null
    hydrateExam(created)
    await router.replace({
      path: `/workspace/assessment/exams/${created.id}`,
      query: {
        course_id: courseId.value,
        ...(reviewTaskId.value ? { review_task: reviewTaskId.value } : {}),
        ...(route.query.knowledge_point_id ? { knowledge_point_id: route.query.knowledge_point_id } : {}),
      },
    })
    notice.value = created.created === false
      ? '已恢复同一配置生成的试卷，可以继续作答。'
      : '试卷已生成，可以开始作答。'
  } catch (value) {
    generationStatus.value = 'error'
    error.value = messageFrom(value)
  } finally {
    busy.value = false
  }
}

function openMissingTask(task) {
  router.push(task.route || {
    path: '/workspace/path',
    query: { course_id: courseId.value, node_id: task.id },
  })
}

function selectExam(exam) {
  selectedId.value = exam.id
  reportEnvelope.value = null
  hydrateExam(exam)
  router.replace({
    path: `/workspace/assessment/exams/${exam.id}`,
    query: { course_id: courseId.value },
  })
}

function backToBuilder() {
  selectedId.value = ''
  generationStatus.value = 'idle'
  reportEnvelope.value = null
  clearObject(answers)
  clearObject(drafts)
  router.replace({ path: '/workspace/assessment/exams', query: { course_id: courseId.value } })
}

async function createManagedExam() {
  if (!createForm.course_id || !createForm.title || !createForm.questionIds.length) {
    error.value = '请填写课程、考试名称并选择至少一道已审核题目。'
    return
  }
  const points = Math.round((100 / createForm.questionIds.length) * 100) / 100
  await runManagerAction(async () => {
    const created = await createM5FormalExam({
      course_id: createForm.course_id,
      title: createForm.title,
      duration_minutes: Number(createForm.duration_minutes),
      feedback_policy: 'after_close',
      items: createForm.questionIds.map(question_version_id => ({ question_version_id, points, required: true })),
    })
    selectedId.value = created.id
  }, '试卷草稿已创建。')
}

async function transition(target) {
  await runManagerAction(() => transitionM5FormalExam(selected.value.id, {
    expected_lock_version: selected.value.lock_version,
    target_status: target,
  }), `考试已切换为 ${target}。`)
}

async function assign() {
  if (!assignLearner.value.trim()) return
  await runManagerAction(
    () => assignM5FormalExam(selected.value.id, assignLearner.value.trim()),
    '考生场次已分配。',
  )
}

async function finishReview(review) {
  const reviewDraft = reviewDrafts[review.id]
  await runManagerAction(() => completeM5FormalReview(review.id, {
    expected_lock_version: review.lock_version,
    result: {
      score: Number(reviewDraft.score),
      confidence: 0.9,
      note: reviewDraft.note,
      criterion_results: [],
    },
  }), '复核结果已追加为新的评分证据。')
}

async function start() {
  busy.value = true
  error.value = ''
  notice.value = ''
  try {
    const data = await startM5FormalSitting(sitting.value.id, sitting.value.lock_version)
    selected.value.sitting = data
    now.value = Date.now()
    notice.value = '作答已开始。答案逐题保存，刷新页面后仍可继续。'
  } catch (value) {
    error.value = messageFrom(value)
  } finally {
    busy.value = false
  }
}

function markAnswerChanged(item) {
  saveStates[item.id] = 'dirty'
  pendingSaveKeys[item.id] = newAnswerKey()
  delete drafts[item.id]
}

function chooseAnswer(item, value) {
  answers[item.id] = value
  markAnswerChanged(item)
}

function toggleMultipleChoice(item, value) {
  const selectedChoices = new Set(Array.isArray(answers[item.id]) ? answers[item.id] : [])
  if (selectedChoices.has(value)) selectedChoices.delete(value)
  else selectedChoices.add(value)
  answers[item.id] = [...selectedChoices].sort()
  markAnswerChanged(item)
}

function hasAnswer(item) {
  const value = answers[item.id]
  if (item.question_type === 'multiple_choice') return Array.isArray(value) && value.length > 0
  if (item.question_type === 'true_false') return typeof value === 'boolean'
  return String(value || '').trim().length > 0
}

function answerPayload(item) {
  const value = answers[item.id]
  if (item.question_type === 'single_choice') return { choice: value || '' }
  if (item.question_type === 'multiple_choice') return { choices: Array.isArray(value) ? value : [] }
  if (item.question_type === 'true_false') return { value }
  if (item.question_type === 'fill_blank') {
    return { blanks: String(value || '').split('|').map(part => part.trim()).filter(Boolean) }
  }
  if (item.question_type === 'code') return { code: value || '' }
  return { text: value || '' }
}

async function saveAnswer(item, moveNext = false) {
  if (!canAnswer.value || !hasAnswer(item) || savingItemId.value) return false
  savingItemId.value = item.id
  error.value = ''
  notice.value = ''
  pendingSaveKeys[item.id] ||= newAnswerKey()
  try {
    const data = await answerM5FormalSitting(sitting.value.id, {
      exam_item_id: item.id,
      idempotency_key: pendingSaveKeys[item.id],
      answer: answerPayload(item),
    })
    drafts[item.id] = data.draft
    saveStates[item.id] = 'saved'
    delete pendingSaveKeys[item.id]
    selected.value.sitting = data.sitting
    notice.value = `第 ${item.position} 题已保存。`
    if (moveNext && currentQuestionIndex.value < selected.value.items.length - 1) {
      currentQuestionIndex.value += 1
    }
    return true
  } catch (value) {
    saveStates[item.id] = 'error'
    error.value = messageFrom(value)
    return false
  } finally {
    savingItemId.value = ''
  }
}

async function submitExam({ recoverOnly = false } = {}) {
  if (!recoverOnly) {
    if (!allDraftsSaved.value || busy.value) return
    if (!window.confirm('提交后不能再修改答案，确认提交本次试卷吗？')) return
  }
  busy.value = true
  error.value = ''
  notice.value = ''
  try {
    const data = await submitM5FormalSitting(sitting.value.id, sitting.value.lock_version)
    selected.value.sitting = data.sitting
    reportEnvelope.value = normalizeReportEnvelope(data)
    notice.value = data.recoverable
      ? '试卷已提交并完成计分，部分学习反馈仍在处理，可继续恢复。'
      : '试卷已提交，画像、路径、下一日安排、错题和复习计划已记录。'
    if (reviewScoped.value && data.event_id) {
      await router.push({
        path: '/workspace/review',
        query: {
          course_id: courseId.value,
          review_task: reviewTaskId.value,
          review_event: data.event_id,
          review_notice: 'assessment-completed',
        },
      })
    }
  } catch (value) {
    error.value = messageFrom(value)
  } finally {
    busy.value = false
  }
}

async function buildReport() {
  busy.value = true
  error.value = ''
  notice.value = ''
  try {
    const data = await generateM5FormalReport(sitting.value.id)
    reportEnvelope.value = normalizeReportEnvelope(data)
    notice.value = '成绩报告已恢复。'
  } catch (value) {
    error.value = messageFrom(value)
  } finally {
    busy.value = false
  }
}

function displayAnswer(value) {
  if (value === null || value === undefined || value === '') return '未作答'
  if (typeof value === 'boolean') return value ? '正确' : '错误'
  if (Array.isArray(value)) return value.join('、') || '未作答'
  if (typeof value === 'object') {
    if ('choice' in value) return value.choice || '未作答'
    if ('choices' in value) return (value.choices || []).join('、') || '未作答'
    if ('value' in value) return value.value ? '正确' : '错误'
    if ('blanks' in value) return (value.blanks || []).join(' / ') || '未作答'
    if ('text' in value) return value.text || '未作答'
    if ('code' in value) return value.code || '未作答'
    return JSON.stringify(value)
  }
  return String(value)
}

function sourceLabel(source) {
  return [source.document_title, source.chapter_title, source.location_label, source.page_number ? `第 ${source.page_number} 页` : '']
    .filter(Boolean)
    .join(' · ')
}

function goToRetest(action) {
  if (!action?.route) return
  router.push({ path: action.route, query: action.query || {} })
}

onMounted(() => {
  timerHandle = window.setInterval(() => { now.value = Date.now() }, 1000)
  load()
})

watch(courseId, async (nextCourseId, previousCourseId) => {
  if (manager.value || !nextCourseId || nextCourseId === previousCourseId) return
  resetLearnerConfiguration()
  await load()
})

onBeforeUnmount(() => {
  if (timerHandle) window.clearInterval(timerHandle)
})
</script>

<template>
  <main class="exam-shell" data-testid="formal-exam-workspace">
    <header class="page-header">
      <div>
        <span><ClipboardList :size="16" />{{ manager ? '正式测评管理' : '测评中心 · 智能组卷' }}</span>
        <h1>{{ manager ? '试卷管理' : '用一份正式试卷检验今日学习' }}</h1>
        <p>{{ manager ? '管理试卷发布、分配与复核。' : '设置范围并生成试卷，逐题保存后提交；完成后会得到详细讲解和复习建议。' }}</p>
      </div>
      <button class="icon-button" type="button" title="刷新当前状态" :disabled="loading || busy" @click="load">
        <RefreshCw :size="18" />
      </button>
    </header>

    <div v-if="error" class="banner error" role="alert"><AlertCircle :size="17" />{{ error }}</div>
    <div v-else-if="notice" class="banner notice" role="status"><CheckCircle2 :size="17" />{{ notice }}</div>
    <div v-if="loading" class="loading-state"><LoaderCircle class="spin" :size="20" />正在核对课程、今日任务和历史试卷</div>

    <template v-else-if="studentNeedsCourse">
      <section class="course-required-state" data-testid="exam-course-required" role="status">
        <BookOpen :size="26" />
        <div>
          <h2>请选择课程后开始智能组卷</h2>
          <p>选择课程后，就可以按照今天的学习内容安排题目。</p>
        </div>
        <label class="course-picker-field"><span>测评课程</span><select data-testid="exam-course-picker" :value="courseId" aria-label="选择测评课程" @change="chooseCourse($event.target.value)">
          <option value="" disabled>{{ courseCatalog.length ? '请选择课程' : '暂无可用课程' }}</option>
          <option v-for="course in courseOptions" :key="course.id" :value="course.id">{{ course.title }}{{ course.subject ? ` · ${course.subject}` : '' }}</option>
        </select></label>
        <p v-if="!courseCatalog.length && !error" class="course-picker-empty">当前没有可用于智能测评的课程。</p>
        <button v-if="error" type="button" class="secondary-button" @click="load">重新加载课程</button>
      </section>
    </template>

    <template v-else-if="manager">
      <section class="manager-authoring">
        <div class="section-heading"><div><span>教师工具</span><h2>建立正式试卷</h2></div></div>
        <div class="manager-form">
          <input v-model="createForm.course_id" placeholder="课程 ID" aria-label="课程 ID" />
          <input v-model="createForm.title" placeholder="考试名称" aria-label="考试名称" />
          <input v-model.number="createForm.duration_minutes" type="number" min="1" aria-label="考试时长" />
          <button class="primary-button" :disabled="busy" @click="createManagedExam"><FileCheck2 :size="17" />建立试卷</button>
        </div>
        <div class="question-picker">
          <label v-for="question in questions" :key="question.id">
            <input v-model="createForm.questionIds" type="checkbox" :value="question.id" />
            <span>{{ typeLabels[question.question_type] }}</span>
            <strong>{{ question.prompt }}</strong>
          </label>
          <p v-if="!questions.length">暂无可用的已审核题目。</p>
        </div>
      </section>

      <section class="manager-layout">
        <aside class="history-list">
          <h2>考试列表 <span>{{ exams.length }}</span></h2>
          <button v-for="exam in exams" :key="exam.id" :class="{ active: selectedId === exam.id }" @click="selectExam(exam)">
            <strong>{{ exam.title }}</strong><small>{{ exam.status }} · {{ exam.items.length }} 题</small>
          </button>
        </aside>
        <section v-if="selected" class="manager-stage">
          <h2>{{ selected.title }}</h2>
          <p>{{ selected.duration_minutes }} 分钟 · {{ selected.version.total_points }} 分 · {{ selected.status }}</p>
          <div class="manager-tools">
            <button v-if="selected.status === 'draft'" @click="transition('published')">发布</button>
            <button v-if="selected.status === 'published'" @click="transition('open')">开放考试</button>
            <button v-if="selected.status === 'open'" @click="transition('closed')">封卷</button>
            <input v-model="assignLearner" placeholder="考生 public_id" />
            <button :disabled="!assignLearner" @click="assign">分配场次</button>
          </div>
          <ol class="compact-items"><li v-for="item in selected.items" :key="item.id">{{ item.position }}. {{ item.prompt }}</li></ol>
        </section>
        <div v-else class="empty-stage">选择一场考试查看详情。</div>
      </section>

      <section v-if="reviews.length" class="review-queue">
        <h2>复核队列</h2>
        <div v-for="review in reviews" :key="review.id">
          <span>{{ review.reason || '未填写原因' }}</span>
          <input v-model.number="reviewDrafts[review.id].score" type="number" min="0" max="1" step="0.05" />
          <input v-model="reviewDrafts[review.id].note" />
          <button :disabled="review.status === 'completed' || busy" @click="finishReview(review)">完成复核</button>
        </div>
      </section>
    </template>

    <template v-else>
      <section v-if="generationStatus === 'generating'" class="generation-waiting" data-testid="exam-generation-waiting" role="status" aria-live="polite">
        <div class="generation-waiting__icon"><LoaderCircle class="spin" :size="34" /></div>
        <div>
          <span class="eyebrow">智能测评生成中</span>
          <h2>正在根据当前课程生成试卷</h2>
          <p>{{ courseTitle }} · {{ scopeLabel }} · {{ requestedCount }} 题 · 预计 {{ computedDurationMinutes }} 分钟</p>
          <small>题目生成完成后才会显示试卷并开始作答，当前请不要重复点击。</small>
        </div>
      </section>

      <section v-else-if="!selectedId && !gate?.unlocked" class="locked-stage" data-testid="exam-gate-locked">
        <div class="lock-summary">
          <span class="lock-icon"><LockKeyhole :size="25" /></span>
          <div>
            <span>智能组卷尚未解锁</span>
            <h2>先完成今天的 {{ gate?.missing_tasks?.length || 0 }} 项必做任务</h2>
            <p>完成必做练习并提交结果后即可解锁；只浏览资源不会被当作已经学会。</p>
          </div>
          <strong>{{ completedCount }}/{{ requiredCount || (gate?.missing_tasks?.length || 0) }}</strong>
        </div>
        <div v-if="gate?.missing_tasks?.length" class="missing-list">
          <button v-for="(task, index) in gate.missing_tasks" :key="task.id" type="button" @click="openMissingTask(task)">
            <span>{{ String(index + 1).padStart(2, '0') }}</span>
            <span><strong>{{ task.title }}</strong><small>{{ task.completion_criteria }}</small></span>
            <span>去完成<ChevronRight :size="18" /></span>
          </button>
        </div>
        <div v-else class="snapshot-required">
          <span><strong>先从今日知识点生成完整资源包</strong><small>完成其中的必做练习后，就可以开始智能组卷。</small></span>
          <button class="primary-button" @click="router.push({ path: '/workspace/path', query: { course_id: courseId } })">前往学习路径</button>
        </div>
      </section>

      <section v-else-if="!selectedId" class="builder-layout" data-testid="exam-builder-unlocked">
        <aside class="exam-config">
          <div class="unlock-mark"><Check :size="16" />今日必做任务已完成</div>
          <h2>组卷设置</h2>

          <label class="field"><span>试卷名称</span><input v-model="learnerForm.title" maxlength="256" @input="markConfigChanged" /></label>
          <label class="field"><span>检验主题</span><input v-model="learnerForm.theme" maxlength="256" @input="markConfigChanged" /></label>
          <label class="field"><span>课程</span><select data-testid="exam-course-selector" :value="courseId" aria-label="测评课程" @change="chooseCourse($event.target.value)"><option v-for="course in courseOptions" :key="course.id" :value="course.id">{{ course.title }}</option></select></label>

          <fieldset class="scope-fieldset">
            <legend>章节范围</legend>
            <div class="choice-grid">
              <button
                v-for="chapter in context?.chapters || []"
                :key="chapter.id"
                type="button"
                :class="{ selected: learnerForm.chapter_ids.includes(chapter.id) }"
                @click="toggleChapter(chapter.id)"
              ><Check v-if="learnerForm.chapter_ids.includes(chapter.id)" :size="15" />{{ chapter.title }}</button>
            </div>
            <small>不选择时覆盖当前课程全部章节。</small>
          </fieldset>

          <details class="scope-details">
            <summary>精确到知识点 <span>{{ learnerForm.knowledge_point_ids.length ? `已选 ${learnerForm.knowledge_point_ids.length} 项` : '可选' }}</span></summary>
            <div class="choice-grid knowledge-choices">
              <button
                v-for="point in availableKnowledgePoints"
                :key="point.id"
                type="button"
                :class="{ selected: learnerForm.knowledge_point_ids.includes(point.id) }"
                @click="toggleKnowledgePoint(point.id)"
              ><Check v-if="learnerForm.knowledge_point_ids.includes(point.id)" :size="15" /><span class="knowledge-point-title">{{ point.title }}</span><em v-if="isTodayKnowledgePoint(point)" data-testid="today-knowledge-point">今日待测试</em></button>
            </div>
          </details>

          <div class="inline-fields">
            <label class="field"><span>难度</span><select v-model="learnerForm.difficulty" @change="markConfigChanged"><option v-for="option in context?.difficulty_options || []" :key="option" :value="option">{{ difficultyLabels[option] }}</option></select></label>
            <label class="field"><span>考试时间</span><output class="computed-duration">{{ computedDurationMinutes }}<small>分钟</small></output></label>
          </div>

          <p v-if="todayWorkError" class="today-work-warning"><span>今日知识点暂时无法读取，仍可按课程知识点选择测评范围。{{ todayWorkError }}</span><button type="button" :disabled="todayWorkLoading" @click="loadTodayWork">{{ todayWorkLoading ? '重试中' : '重试' }}</button></p>

          <div class="question-counts">
            <span>题型与题量</span>
            <div v-for="type in configurableTypes" :key="type">
              <span><strong>{{ typeLabels[type] }}</strong><small>{{ questionTypeAvailabilityLabel(type) }}</small></span>
              <span class="stepper">
                <button type="button" :disabled="learnerForm.counts[type] <= 0" :aria-label="`减少${typeLabels[type]}`" @click="changeCount(type, -1)"><Minus :size="16" /></button>
                <b>{{ learnerForm.counts[type] }}</b>
                <button type="button" :disabled="learnerForm.counts[type] >= availableCount(type)" :aria-label="`增加${typeLabels[type]}`" @click="changeCount(type, 1)"><Plus :size="16" /></button>
              </span>
            </div>
          </div>

          <p v-if="!selectionComplete" class="config-warning">请至少选择一种题型并设置题量。</p>
          <button class="primary-button generate-button" :disabled="busy || !selectionComplete" @click="createLearnerExam">
            <LoaderCircle v-if="busy" class="spin" :size="18" /><FileCheck2 v-else :size="18" />生成试卷
          </button>
        </aside>

        <section class="exam-preview" data-testid="exam-preview" data-exam-view="blueprint">
          <header>
            <div><span>试卷安排</span><h2>{{ learnerForm.title || '未命名试卷' }}</h2><p>{{ learnerForm.theme || '尚未设置检验主题' }}</p></div>
            <dl><div><dt>题量</dt><dd>{{ requestedCount }}</dd></div><div><dt>时长</dt><dd>{{ computedDurationMinutes }} 分钟</dd></div><div><dt>总分</dt><dd>100</dd></div></dl>
          </header>

          <div class="blueprint-summary">
            <div><Target :size="18" /><span><small>覆盖范围</small><strong>{{ scopeLabel }}</strong></span></div>
            <div><BookOpen :size="18" /><span><small>可用题目</small><strong>{{ context?.approved_question_count || 0 }} 道已审核题</strong></span></div>
            <div><ListChecks :size="18" /><span><small>题目类型</small><strong>{{ blueprint.length }} 种题型</strong></span></div>
          </div>

          <div v-if="blueprint.length" class="blueprint-list">
            <article v-for="(item, index) in blueprint" :key="item.type">
              <span>{{ String(index + 1).padStart(2, '0') }}</span>
              <div><strong>{{ item.label }}</strong><small>题目难度会结合你近期的学习表现进行调整</small></div>
              <b>{{ item.requested }} 题</b>
            </article>
          </div>
          <div v-else class="preview-empty">从左侧设置题型数量后，这里会显示试卷安排。</div>

          <footer class="preview-note">
            <span>生成前不展示具体题目</span>
            <p>点击生成后，会根据所选章节、知识点和难度安排题目。</p>
          </footer>
        </section>
      </section>

      <section v-else-if="selected" class="exam-detail" data-testid="exam-taking">
        <button class="back-button" type="button" @click="backToBuilder"><ArrowLeft :size="17" />返回智能组卷</button>

        <header class="exam-titlebar">
          <div><span>{{ selected.sitting?.status || selected.status }} · {{ selected.items.length }} 题</span><h2>{{ selected.title }}</h2><p>{{ selected.version.configuration?.theme || selected.version.instructions }}</p></div>
          <dl><div><dt>时长</dt><dd>{{ selected.duration_minutes }} 分钟</dd></div><div><dt>已保存</dt><dd>{{ savedCount }}/{{ selected.items.length }}</dd></div><div><dt>总分</dt><dd>{{ selected.version.total_points }}</dd></div></dl>
          <button v-if="sitting?.status === 'assigned'" class="primary-button" :disabled="busy" @click="start"><Play :size="17" />开始作答</button>
          <button v-else-if="sitting?.status === 'in_progress'" class="primary-button" :disabled="busy || !allDraftsSaved" @click="submitExam()"><Send :size="17" />提交试卷</button>
          <button v-else-if="['submitted','released'].includes(sitting?.status) && !reportEnvelope" class="primary-button" :disabled="busy" @click="buildReport"><FileCheck2 :size="17" />查看报告</button>
        </header>

        <div v-if="sitting?.status === 'assigned'" class="frozen-notice" data-testid="generated-exam-preview">
          <FileCheck2 :size="20" />
          <span><strong>试卷已经准备好</strong><small>开始前可以查看题量和范围；开始后会计时，并自动保存每道题的答案。</small></span>
        </div>

        <div class="answer-layout">
          <nav class="question-nav" aria-label="题目导航">
            <span>题目导航</span>
            <button
              v-for="(item, index) in selected.items"
              :key="item.id"
              type="button"
              :class="{ active: currentQuestionIndex === index, saved: drafts[item.id], dirty: saveStates[item.id] === 'dirty', failed: saveStates[item.id] === 'error' }"
              @click="currentQuestionIndex = index"
            ><span>{{ String(item.position).padStart(2, '0') }}</span><small>{{ typeLabels[item.question_type] }}</small><Check v-if="drafts[item.id]" :size="15" /></button>
          </nav>

          <article v-if="currentQuestion" class="answer-stage">
            <header>
              <span>第 {{ currentQuestion.position }} 题 · {{ currentQuestion.points }} 分</span>
              <small>{{ typeLabels[currentQuestion.question_type] }} · {{ currentQuestion.knowledge_point?.title }}</small>
            </header>
            <h3>{{ currentQuestion.prompt }}</h3>

            <div v-if="['single_choice','multiple_choice'].includes(currentQuestion.question_type)" class="option-list">
              <button
                v-for="(option, index) in currentQuestion.options"
                :key="option"
                type="button"
                :disabled="!canAnswer"
                :class="{ selected: currentQuestion.question_type === 'single_choice' ? answers[currentQuestion.id] === optionLabel(option, index) : (answers[currentQuestion.id] || []).includes(optionLabel(option, index)) }"
                @click="currentQuestion.question_type === 'single_choice' ? chooseAnswer(currentQuestion, optionLabel(option, index)) : toggleMultipleChoice(currentQuestion, optionLabel(option, index))"
              ><b>{{ optionLabel(option, index) }}</b><span>{{ optionText(option) }}</span><Check v-if="currentQuestion.question_type === 'single_choice' ? answers[currentQuestion.id] === optionLabel(option, index) : (answers[currentQuestion.id] || []).includes(optionLabel(option, index))" :size="17" /></button>
            </div>

            <div v-else-if="currentQuestion.question_type === 'true_false'" class="binary-options">
              <button type="button" :class="{ selected: answers[currentQuestion.id] === true }" :disabled="!canAnswer" @click="chooseAnswer(currentQuestion, true)">正确</button>
              <button type="button" :class="{ selected: answers[currentQuestion.id] === false }" :disabled="!canAnswer" @click="chooseAnswer(currentQuestion, false)">错误</button>
            </div>

            <textarea
              v-else
              v-model="answers[currentQuestion.id]"
              :disabled="!canAnswer"
              :placeholder="currentQuestion.question_type === 'fill_blank' ? '多个空请使用 | 分隔' : '写下你的完整回答'"
              @input="markAnswerChanged(currentQuestion)"
            />

            <footer>
              <span v-if="saveStates[currentQuestion.id] === 'saved'"><CheckCircle2 :size="16" />答案已保存，仍可修改</span>
              <span v-else-if="saveStates[currentQuestion.id] === 'dirty'">答案已修改，尚未保存</span>
              <span v-else-if="saveStates[currentQuestion.id] === 'error'"><AlertCircle :size="16" />保存失败，未修改答案时重试会复用同一次请求</span>
              <span v-else>{{ canAnswer ? '作答后保存本题' : '开始作答后才能填写答案' }}</span>
              <div>
                <button type="button" :disabled="currentQuestionIndex === 0" title="上一题" @click="currentQuestionIndex -= 1"><ChevronLeft :size="17" /></button>
                <button v-if="canAnswer" type="button" :disabled="savingItemId || !hasAnswer(currentQuestion)" @click="saveAnswer(currentQuestion, true)"><LoaderCircle v-if="savingItemId === currentQuestion.id" class="spin" :size="16" /><Check v-else :size="16" />保存{{ currentQuestionIndex < selected.items.length - 1 ? '并下一题' : '本题' }}</button>
                <button type="button" :disabled="currentQuestionIndex >= selected.items.length - 1" title="下一题" @click="currentQuestionIndex += 1"><ChevronRight :size="17" /></button>
              </div>
            </footer>
          </article>

          <aside class="exam-status">
            <div class="timer-block"><Timer :size="19" /><span><small>剩余时间</small><strong :class="{ expired: remainingSeconds === 0 }">{{ remainingLabel }}</strong></span></div>
            <dl>
              <div><dt>当前进度</dt><dd>{{ savedCount }}/{{ selected.items.length }}</dd></div>
              <div><dt>尚未保存</dt><dd>{{ unsavedCount }} 题</dd></div>
              <div><dt>当前题</dt><dd>{{ currentQuestionIndex + 1 }}/{{ selected.items.length }}</dd></div>
            </dl>
            <p v-if="sitting?.status === 'in_progress' && !allDraftsSaved">保存全部题目后才能提交。刷新页面会从最新保存版本恢复。</p>
            <p v-else-if="sitting?.status === 'in_progress'">全部答案已保存。提交后将立即计分并记录学习反馈。</p>
            <p v-else-if="sitting?.status === 'assigned'">开始后计时。请先确认题量和测评范围。</p>
            <p v-else>试卷已经提交，答案不可再修改。</p>
          </aside>
        </div>

        <section v-if="reportData" class="report-section" data-testid="formal-exam-report">
          <header>
            <div><span>本轮成绩</span><strong>{{ reportData.final_ratio === null ? '待评分' : `${Math.round(reportData.final_ratio * 100)}%` }}</strong><small>{{ reportData.earned_points }} / {{ reportData.total_points }} 分</small></div>
            <div><h2>成绩与反馈报告</h2><p>逐题查看答案、详细讲解和需要优先复习的知识点。</p></div>
            <span :class="['sync-state', { recoverable: reportEnvelope?.recoverable }]">{{ reportEnvelope?.recoverable ? '反馈仍在处理' : '学习闭环已记录' }}</span>
          </header>

          <AggregationStatus
            :course-id="courseId"
            :event-id="reportEnvelope?.event_id || ''"
            :initial-feedback="reportEnvelope?.learning_feedback || null"
            mode="result"
            show-empty
            @recovered="handleFeedbackRecovered"
            data-testid="formal-exam-feedback-status"
          />

          <section class="coverage-section">
            <h3>知识点覆盖</h3>
            <div v-for="item in reportData.coverage || []" :key="item.id">
              <span><strong>{{ item.title }}</strong><small>{{ item.question_count }} 题 · {{ item.earned_points }}/{{ item.total_points }} 分</small></span>
              <b>{{ Math.round((item.ratio || 0) * 100) }}%</b>
            </div>
          </section>

          <section class="answer-review">
            <h3>逐题解析</h3>
            <article v-for="item in reportData.items || []" :key="item.position">
              <header><span>第 {{ item.position }} 题 · {{ typeLabels[item.question_type] }}</span><b :class="{ wrong: item.correct === false }">{{ item.score === null ? '待评分' : `${Math.round(item.score * item.points * 10) / 10}/${item.points} 分` }}</b></header>
              <h4>{{ item.prompt }}</h4>
              <dl>
                <div><dt>你的答案</dt><dd>{{ displayAnswer(item.learner_answer) }}</dd></div>
                <div><dt>正确答案</dt><dd>{{ displayAnswer(item.correct_answer) }}</dd></div>
                <div><dt>解析</dt><dd>{{ item.explanation || '暂无解析' }}</dd></div>
                <div v-if="publicErrorReason(item)"><dt>错误原因</dt><dd>{{ publicErrorReason(item) }}</dd></div>
              </dl>
              <footer v-if="item.correct === false || item.retest_action">
                <button type="button" @click="router.push({ path: '/workspace/review/wrong-questions', query: { course_id: courseId } })">查看错题记录</button>
                <button type="button" @click="router.push({ path: '/workspace/review', query: { course_id: courseId, knowledge_point_id: item.knowledge_point?.id } })">进入复习计划</button>
                <button v-if="item.retest_action" type="button" @click="goToRetest(item.retest_action)">针对该知识点重新组卷</button>
              </footer>
            </article>
          </section>
        </section>
      </section>

      <section v-if="historical.length || (!selectedId && exams.length)" class="history-section" data-testid="historical-exams">
        <h2><History :size="19" />历史试卷与报告</h2>
        <button v-for="exam in (selectedId ? historical : exams)" :key="exam.id" type="button" @click="selectExam(exam)">
          <span><strong>{{ exam.title }}</strong><small>{{ exam.items.length }} 题 · {{ exam.duration_minutes }} 分钟 · {{ exam.sitting?.status || exam.status }}</small></span>
          <ChevronRight :size="18" />
        </button>
      </section>
    </template>
  </main>
</template>

<style scoped>
.exam-shell{width:min(1280px,100%);margin:0 auto;padding:10px 0 56px;color:#06141b;font-family:"Source Han Sans SC","Noto Sans CJK SC","Microsoft YaHei",sans-serif;letter-spacing:0}.page-header{display:flex;align-items:flex-end;justify-content:space-between;gap:24px;padding:18px 0 24px;border-bottom:1px solid #ccd0cf}.page-header>div>span{display:flex;align-items:center;gap:8px;color:#4a5c6a;font-size:14px;font-weight:700}.page-header h1{margin:9px 0 8px;font-family:"Source Han Serif SC","Noto Serif CJK SC",serif;font-size:30px;line-height:1.25;letter-spacing:0}.page-header p{margin:0;color:#60727c;font-size:15px;line-height:1.6}.icon-button{display:grid;width:42px;height:42px;place-items:center;border:1px solid #ccd0cf;border-radius:6px;background:#fff;color:#11212d;cursor:pointer}.icon-button:hover{background:#f5f7f7}.banner,.loading-state{display:flex;align-items:center;gap:9px;margin:16px 0;padding:13px 15px;border:1px solid #ccd0cf;border-radius:6px;background:#fff;font-size:14px}.banner.error{border-color:#c7867d;background:#fff8f7;color:#842b24}.banner.notice{background:#eef2f3;color:#11212d}.loading-state{color:#60727c}.spin{animation:spin .8s linear infinite}@keyframes spin{to{transform:rotate(360deg)}}
.course-required-state{display:grid;max-width:680px;min-height:260px;grid-template-columns:auto minmax(0,1fr);align-items:center;gap:16px;margin:48px auto;padding:28px;border:1px solid #ccd0cf;border-radius:8px;background:#fff}.course-required-state h2{margin:0;font-size:20px;line-height:1.45}.course-required-state p{margin:8px 0 0;color:#60727c;font-size:14px;line-height:1.65}.course-required-state .primary-button{grid-column:2;justify-self:start}
.course-picker-field{grid-column:2;display:grid;gap:7px}.course-picker-field span{font-size:14px;font-weight:700}.course-picker-field select{width:100%;min-height:42px;border:1px solid #b9c2c5;border-radius:5px;background:#fff;padding:9px 11px;color:#06141b;font-size:14px}.course-picker-empty{grid-column:2;margin:0!important}.course-required-state .secondary-button{grid-column:2;justify-self:start;min-height:42px;border:1px solid #9ba8ab;border-radius:6px;background:#fff;padding:10px 17px;color:#11212d;font-size:14px;font-weight:700;cursor:pointer}.generation-waiting{display:flex;max-width:760px;align-items:center;gap:20px;margin:48px auto;padding:34px 30px;border:1px solid #ccd0cf;border-radius:8px;background:#fff}.generation-waiting__icon{display:grid;width:66px;height:66px;flex:0 0 auto;place-items:center;border-radius:50%;background:#eef2f3;color:#11212d}.generation-waiting .eyebrow{color:#60727c;font-size:14px;font-weight:700}.generation-waiting h2{margin:7px 0 6px;font-size:22px}.generation-waiting p{margin:0;color:#4a5c6a;font-size:14px;line-height:1.6}.generation-waiting small{display:block;margin-top:8px;color:#60727c;font-size:14px;line-height:1.55}.today-work-warning{display:flex;align-items:center;justify-content:space-between;gap:12px;margin:0 0 16px;color:#842b24;font-size:14px;line-height:1.55}.today-work-warning span{flex:1}.today-work-warning button{flex:0 0 auto;border:1px solid #b87970;border-radius:5px;background:#fff8f7;padding:6px 10px;color:#842b24;font-size:14px;cursor:pointer}.today-work-warning button:disabled{cursor:not-allowed;opacity:.65}.computed-duration{display:flex;min-height:42px;align-items:center;justify-content:space-between;border:1px solid #b9c2c5;border-radius:5px;background:#eef2f3;padding:9px 11px;color:#06141b;font-size:16px;font-weight:700}.computed-duration small{color:#60727c;font-size:14px;font-weight:400}.knowledge-point-title{min-width:0;flex:1}.knowledge-choices button em{font-style:normal;color:#842b24;font-size:12px;font-weight:700;white-space:nowrap}.knowledge-choices button.selected em{color:#fff}
.primary-button{display:inline-flex;min-height:42px;align-items:center;justify-content:center;gap:8px;border:0;border-radius:6px;background:#11212d;padding:10px 17px;color:#fff;font-size:14px;font-weight:700;cursor:pointer}.primary-button:hover:not(:disabled){background:#06141b}.primary-button:disabled{background:#dce1e2;color:#60727c;cursor:not-allowed}.back-button{display:inline-flex;align-items:center;gap:7px;margin-bottom:16px;border:0;background:transparent;padding:6px 0;color:#11212d;font-size:14px;font-weight:700;cursor:pointer}.back-button:hover{text-decoration:underline}.section-heading span{color:#60727c;font-size:14px;font-weight:700}.section-heading h2{margin:5px 0 0;font-size:21px}
.locked-stage{margin-top:24px;border-top:1px solid #ccd0cf;border-bottom:1px solid #ccd0cf;background:#fff}.lock-summary{display:grid;grid-template-columns:54px minmax(0,1fr) 90px;align-items:center;gap:18px;padding:28px 20px;background:#eef2f3}.lock-icon{display:grid;width:48px;height:48px;place-items:center;border:1px solid #9ba8ab;border-radius:7px;color:#11212d}.lock-summary>div>span{color:#4a5c6a;font-size:14px;font-weight:700}.lock-summary h2{margin:5px 0 8px;font-size:24px;letter-spacing:0}.lock-summary p{margin:0;color:#60727c;font-size:14px;line-height:1.65}.lock-summary>strong{font-size:26px;text-align:right}.missing-list{display:grid}.missing-list>button{display:grid;grid-template-columns:54px minmax(0,1fr) 110px;align-items:center;gap:16px;min-height:92px;padding:18px 20px;border:0;border-top:1px solid #dce1e2;background:#fff;color:#06141b;text-align:left;cursor:pointer}.missing-list>button:hover{background:#f5f7f7}.missing-list>button>span:first-child{color:#60727c;font-size:14px;font-weight:700}.missing-list>button>span:nth-child(2){display:grid;gap:6px}.missing-list strong{font-size:16px}.missing-list small{color:#60727c;font-size:14px;line-height:1.55}.missing-list>button>span:last-child{display:flex;align-items:center;justify-content:flex-end;gap:5px;color:#11212d;font-size:14px;font-weight:700}.snapshot-required{display:flex;align-items:center;justify-content:space-between;gap:24px;padding:24px 20px;border-top:1px solid #dce1e2}.snapshot-required>span{display:grid;gap:5px}.snapshot-required strong{font-size:17px}.snapshot-required small{color:#60727c;font-size:14px}
.builder-layout{display:grid;grid-template-columns:minmax(340px,35fr) minmax(0,65fr);min-height:700px;margin-top:24px;border:1px solid #ccd0cf;border-radius:8px;overflow:hidden;background:#fff}.exam-config{padding:24px;border-right:1px solid #ccd0cf;background:#f5f7f7}.unlock-mark{display:flex;align-items:center;gap:7px;color:#11212d;font-size:14px;font-weight:700}.exam-config h2{margin:9px 0 22px;font-size:23px}.field{display:grid;gap:7px;margin-bottom:16px}.field>span:first-child,.question-counts>span,.scope-fieldset legend{font-size:14px;font-weight:700}.field input,.field select,.manager-form input,.manager-tools input,.review-queue input{width:100%;min-height:42px;box-sizing:border-box;border:1px solid #b9c2c5;border-radius:5px;background:#fff;padding:9px 11px;color:#06141b;font-size:14px}.field input:focus,.field select:focus{border-color:#11212d;outline:2px solid #dce1e2;outline-offset:1px}.field input:disabled{background:#eef2f3;color:#4a5c6a}.inline-fields{display:grid;grid-template-columns:1fr 1fr;gap:12px}.input-unit{position:relative;display:block}.input-unit small{position:absolute;right:12px;top:12px;color:#60727c;font-size:14px}.input-unit input{padding-right:48px}.scope-fieldset{margin:0 0 16px;padding:0;border:0}.choice-grid{display:flex;flex-wrap:wrap;gap:7px;margin-top:9px}.choice-grid button{display:inline-flex;min-height:36px;align-items:center;gap:6px;border:1px solid #b9c2c5;border-radius:5px;background:#fff;padding:7px 10px;color:#11212d;font-size:14px;text-align:left;cursor:pointer}.choice-grid button.selected{border-color:#11212d;background:#11212d;color:#fff}.scope-fieldset>small{display:block;margin-top:8px;color:#60727c;font-size:14px;line-height:1.5}.scope-details{margin-bottom:18px;border-top:1px solid #dce1e2;border-bottom:1px solid #dce1e2;padding:12px 0}.scope-details summary{display:flex;justify-content:space-between;gap:12px;color:#11212d;font-size:14px;font-weight:700;cursor:pointer}.scope-details summary span{color:#60727c;font-weight:400}.knowledge-choices{max-height:180px;overflow:auto;padding:2px}.question-counts{margin-top:4px;border-top:1px solid #ccd0cf;padding-top:18px}.question-counts>div{display:flex;align-items:center;justify-content:space-between;gap:14px;min-height:58px;border-bottom:1px solid #dce1e2}.question-counts>div>span:first-child{display:grid;gap:3px}.question-counts strong{font-size:14px}.question-counts small{color:#60727c;font-size:14px}.stepper{display:grid;grid-template-columns:34px 34px 34px;align-items:center}.stepper button{display:grid;width:34px;height:34px;place-items:center;border:1px solid #b9c2c5;background:#fff;color:#11212d;cursor:pointer}.stepper button:disabled{color:#9ba8ab;cursor:not-allowed}.stepper button:first-child{border-radius:5px 0 0 5px}.stepper button:last-child{border-radius:0 5px 5px 0}.stepper b{display:grid;height:34px;place-items:center;border-top:1px solid #b9c2c5;border-bottom:1px solid #b9c2c5;font-size:14px}.source-limit{margin-top:17px}.config-warning{margin:10px 0 0;color:#842b24;font-size:14px;line-height:1.5}.generate-button{width:100%;margin-top:18px}
.exam-preview{display:flex;min-width:0;flex-direction:column;padding:28px 32px}.exam-preview>header{display:flex;align-items:flex-start;justify-content:space-between;gap:24px;padding-bottom:22px;border-bottom:2px solid #11212d}.exam-preview>header span{color:#60727c;font-size:14px;font-weight:700}.exam-preview h2{margin:7px 0 5px;font-family:"Source Han Serif SC","Noto Serif CJK SC",serif;font-size:27px}.exam-preview header p{margin:0;color:#60727c;font-size:14px}.exam-preview dl,.exam-titlebar dl{display:flex;gap:22px;margin:0}.exam-preview dl div,.exam-titlebar dl div{display:grid;gap:4px;text-align:right}.exam-preview dt,.exam-titlebar dt{color:#60727c;font-size:14px}.exam-preview dd,.exam-titlebar dd{margin:0;font-size:16px;font-weight:700}.blueprint-summary{display:grid;grid-template-columns:repeat(3,1fr);border-bottom:1px solid #ccd0cf}.blueprint-summary>div{display:flex;min-width:0;align-items:flex-start;gap:10px;padding:18px 12px}.blueprint-summary>div:first-child{padding-left:0}.blueprint-summary>div+div{border-left:1px solid #dce1e2}.blueprint-summary span{display:grid;min-width:0;gap:5px}.blueprint-summary small{color:#60727c;font-size:14px}.blueprint-summary strong{overflow-wrap:anywhere;font-size:14px;line-height:1.5}.blueprint-list{display:grid}.blueprint-list article{display:grid;grid-template-columns:42px minmax(0,1fr) 60px;gap:14px;align-items:start;padding:20px 0;border-bottom:1px solid #dce1e2}.blueprint-list article>span{color:#60727c;font-size:14px;font-weight:700}.blueprint-list article>div{display:grid;gap:7px}.blueprint-list strong{font-size:16px}.blueprint-list small{color:#60727c;font-size:14px;line-height:1.55}.blueprint-list article>b{text-align:right;font-size:14px}.preview-empty{display:grid;min-height:300px;place-items:center;color:#60727c;font-size:15px}.preview-note{margin-top:auto;border-top:1px solid #ccd0cf;padding-top:20px}.preview-note span{color:#11212d;font-size:14px;font-weight:700}.preview-note p{margin:7px 0 0;color:#60727c;font-size:14px;line-height:1.65}
.exam-detail{margin-top:24px}.exam-titlebar{display:grid;grid-template-columns:minmax(0,1fr) auto auto;align-items:center;gap:28px;padding:22px 24px;border:1px solid #ccd0cf;border-radius:7px;background:#fff}.exam-titlebar>div>span{color:#4a5c6a;font-size:14px;font-weight:700}.exam-titlebar h2{margin:6px 0 4px;font-size:24px}.exam-titlebar p{margin:0;color:#60727c;font-size:14px}.frozen-notice{display:flex;align-items:center;gap:12px;margin-top:14px;border-left:3px solid #11212d;background:#eef2f3;padding:14px 16px}.frozen-notice>span{display:grid;gap:4px}.frozen-notice strong{font-size:14px}.frozen-notice small{color:#60727c;font-size:14px;line-height:1.5}.answer-layout{display:grid;grid-template-columns:190px minmax(0,1fr) 220px;gap:18px;margin-top:18px}.question-nav,.exam-status{align-self:start;border-top:2px solid #11212d;border-bottom:1px solid #ccd0cf;background:#fff}.question-nav>span{display:block;padding:15px 12px;border-bottom:1px solid #ccd0cf;font-size:14px;font-weight:700}.question-nav>button{display:grid;grid-template-columns:30px minmax(0,1fr) 18px;align-items:center;gap:8px;width:100%;min-height:48px;border:0;border-bottom:1px solid #dce1e2;background:#fff;padding:8px 12px;color:#06141b;text-align:left;cursor:pointer}.question-nav>button:hover{background:#f5f7f7}.question-nav>button.active{background:#11212d;color:#fff}.question-nav>button.saved:not(.active)>span{font-weight:800}.question-nav>button.dirty:not(.active){border-left:3px solid #60727c}.question-nav>button.failed:not(.active){border-left:3px solid #842b24}.question-nav>button span,.question-nav>button small{font-size:14px}.answer-stage{min-width:0;border:1px solid #ccd0cf;border-radius:7px;background:#fff;padding:24px}.answer-stage>header{display:flex;align-items:center;justify-content:space-between;gap:16px}.answer-stage>header span,.answer-stage>header small{color:#60727c;font-size:14px}.answer-stage h3{margin:20px 0;font-size:18px;line-height:1.7;letter-spacing:0}.option-list{display:grid;gap:10px}.option-list>button{display:grid;grid-template-columns:34px minmax(0,1fr) 20px;align-items:center;gap:12px;min-height:52px;border:1px solid #b9c2c5;border-radius:6px;background:#fff;padding:10px 13px;color:#06141b;font-size:14px;text-align:left;cursor:pointer}.option-list>button:hover:not(:disabled){border-color:#11212d;background:#f5f7f7}.option-list>button.selected{border-color:#11212d;background:#11212d;color:#fff}.option-list>button:disabled{cursor:not-allowed}.option-list b{display:grid;width:30px;height:30px;place-items:center;border:1px solid currentColor;border-radius:50%;font-size:14px}.binary-options{display:grid;grid-template-columns:1fr 1fr;gap:10px}.binary-options button{min-height:48px;border:1px solid #b9c2c5;border-radius:5px;background:#fff;color:#11212d;font-size:14px;cursor:pointer}.binary-options button.selected{border-color:#11212d;background:#11212d;color:#fff}.answer-stage>textarea{width:100%;min-height:180px;box-sizing:border-box;border:1px solid #b9c2c5;border-radius:5px;padding:12px;color:#06141b;font-family:inherit;font-size:14px;line-height:1.65;resize:vertical}.answer-stage>textarea:focus{border-color:#11212d;outline:2px solid #dce1e2;outline-offset:1px}.question-sources,.report-sources{margin-top:18px;border-top:1px solid #dce1e2;border-bottom:1px solid #dce1e2;padding:12px 0}.question-sources summary,.report-sources summary{display:flex;justify-content:space-between;gap:12px;font-size:14px;font-weight:700;cursor:pointer}.question-sources summary span,.report-sources summary span{color:#60727c;font-weight:400}.question-sources>div,.report-sources>div{padding:12px 4px 4px}.question-sources strong,.report-sources strong{font-size:14px}.question-sources p,.report-sources p{margin:5px 0 0;color:#60727c;font-size:14px;line-height:1.6}.answer-stage>footer{display:flex;align-items:center;justify-content:space-between;gap:14px;margin-top:18px}.answer-stage>footer>span{display:flex;align-items:center;gap:6px;color:#4a5c6a;font-size:14px;line-height:1.45}.answer-stage>footer>div{display:flex;gap:7px}.answer-stage>footer button{display:inline-flex;min-height:38px;align-items:center;justify-content:center;gap:6px;border:1px solid #9ba8ab;border-radius:5px;background:#fff;padding:8px 11px;color:#11212d;font-size:14px;font-weight:700;cursor:pointer}.answer-stage>footer button:disabled{color:#9ba8ab;cursor:not-allowed}.exam-status{padding:0 14px 16px}.timer-block{display:flex;align-items:center;gap:10px;padding:16px 0;border-bottom:1px solid #ccd0cf}.timer-block>span{display:grid;gap:3px}.timer-block small{color:#60727c;font-size:14px}.timer-block strong{font-variant-numeric:tabular-nums;font-size:24px}.timer-block strong.expired{color:#842b24}.exam-status dl{margin:0}.exam-status dl div{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:13px 0;border-bottom:1px solid #dce1e2}.exam-status dt,.exam-status dd{font-size:14px}.exam-status dd{margin:0;font-weight:700}.exam-status p{margin:14px 0 0;color:#60727c;font-size:14px;line-height:1.65}
.report-section{margin-top:28px;border-top:2px solid #11212d;border-bottom:1px solid #ccd0cf;background:#fff}.report-section>header{display:grid;grid-template-columns:180px minmax(0,1fr) auto;align-items:center;gap:22px;padding:24px;background:#eef2f3}.report-section>header>div:first-child{display:grid}.report-section>header>div:first-child>span,.report-section>header>div:first-child>small{font-size:14px}.report-section>header>div:first-child>strong{font-family:"Source Han Serif SC","Noto Serif CJK SC",serif;font-size:36px}.report-section>header h2{margin:0 0 6px;font-size:21px}.report-section>header p{margin:0;color:#60727c;font-size:14px;line-height:1.6}.sync-state{border:1px solid #9ba8ab;border-radius:999px;padding:7px 10px;color:#11212d;font-size:14px;font-weight:700}.sync-state.recoverable{border-color:#b87970;color:#842b24}.coverage-section,.answer-review{padding:24px}.coverage-section h3,.answer-review>h3{margin:0 0 14px;font-size:18px}.coverage-section>div{display:flex;align-items:center;justify-content:space-between;gap:18px;padding:14px 0;border-top:1px solid #dce1e2}.coverage-section>div>span{display:grid;gap:4px}.coverage-section strong{font-size:14px}.coverage-section small{color:#60727c;font-size:14px}.coverage-section b{font-size:17px}.answer-review{border-top:1px solid #ccd0cf}.answer-review>article{padding:20px 0;border-top:1px solid #dce1e2}.answer-review article>header{display:flex;align-items:center;justify-content:space-between;gap:14px}.answer-review article>header span,.answer-review article>header b{font-size:14px}.answer-review article>header b.wrong{color:#842b24}.answer-review h4{margin:13px 0;font-size:16px;line-height:1.6}.answer-review dl{display:grid;grid-template-columns:1fr 1fr;gap:0;margin:0;border-top:1px solid #dce1e2}.answer-review dl div{display:grid;grid-template-columns:88px minmax(0,1fr);gap:10px;padding:12px 10px;border-bottom:1px solid #dce1e2}.answer-review dl div:nth-child(odd){border-right:1px solid #dce1e2}.answer-review dt{color:#60727c;font-size:14px}.answer-review dd{margin:0;overflow-wrap:anywhere;font-size:14px;line-height:1.6;white-space:pre-wrap}.answer-review article>footer{display:flex;flex-wrap:wrap;gap:8px;margin-top:14px}.answer-review article>footer button{border:1px solid #9ba8ab;border-radius:5px;background:#fff;padding:8px 11px;color:#11212d;font-size:14px;font-weight:700;cursor:pointer}
.history-section{margin-top:32px;border-top:1px solid #ccd0cf}.history-section h2{display:flex;align-items:center;gap:8px;margin:0;padding:20px 4px 14px;font-size:18px}.history-section>button{display:flex;align-items:center;justify-content:space-between;width:100%;min-height:72px;padding:14px 16px;border:0;border-top:1px solid #dce1e2;background:#fff;color:#06141b;text-align:left;cursor:pointer}.history-section>button:hover{background:#f5f7f7}.history-section>button>span{display:grid;gap:5px}.history-section strong{font-size:15px}.history-section small{color:#60727c;font-size:14px}.manager-authoring,.review-queue{margin-top:24px;padding:22px;border-top:1px solid #ccd0cf;border-bottom:1px solid #ccd0cf;background:#f5f7f7}.manager-form{display:grid;grid-template-columns:1fr 1.4fr 120px auto;gap:10px;margin-top:16px}.question-picker{display:grid;max-height:260px;margin-top:15px;overflow:auto;border-top:1px solid #ccd0cf}.question-picker label{display:grid;grid-template-columns:22px 90px minmax(0,1fr);gap:10px;padding:12px 4px;border-bottom:1px solid #dce1e2;font-size:14px}.question-picker strong,.question-picker span{font-size:14px}.manager-layout{display:grid;grid-template-columns:280px minmax(0,1fr);min-height:320px;margin-top:20px;border:1px solid #ccd0cf}.history-list{border-right:1px solid #ccd0cf}.history-list h2{display:flex;justify-content:space-between;margin:0;padding:16px;font-size:17px}.history-list button{display:grid;width:100%;gap:5px;border:0;border-top:1px solid #dce1e2;background:#fff;padding:13px 16px;text-align:left}.history-list button.active{background:#11212d;color:#fff}.history-list strong,.history-list small{font-size:14px}.manager-stage,.empty-stage{padding:22px}.manager-stage h2{margin-top:0}.manager-stage p,.compact-items li{font-size:14px;line-height:1.6}.manager-tools{display:flex;flex-wrap:wrap;gap:8px;margin:16px 0}.manager-tools input{width:220px}.manager-tools button,.review-queue button{border:1px solid #9ba8ab;border-radius:5px;background:#fff;padding:9px 13px;color:#11212d;font-size:14px;font-weight:700}.review-queue h2{margin-top:0}.review-queue>div{display:grid;grid-template-columns:minmax(0,1fr) 100px minmax(220px,1fr) auto;gap:10px;align-items:center;padding:10px 0;border-top:1px solid #dce1e2}.review-queue span{font-size:14px}
.generation-mode-notice{display:flex;align-items:center;gap:12px;margin-top:10px;border:1px solid #ccd0cf;background:#f5f7f7;padding:12px 16px;color:#11212d}.generation-mode-notice>span{display:grid;gap:4px}.generation-mode-notice strong{font-size:14px}.generation-mode-notice small{color:#60727c;font-size:14px;line-height:1.5}
.answer-stage h3,.answer-stage .option-list>button span,.question-sources p,.report-sources p,.answer-review h4{min-width:0;overflow-wrap:anywhere;white-space:normal;word-break:break-word}
@media (max-width:1180px){.answer-layout{grid-template-columns:170px minmax(0,1fr)}.exam-status{grid-column:1/-1;display:grid;grid-template-columns:220px minmax(0,1fr);gap:18px;align-items:center}.exam-status dl{display:grid;grid-template-columns:repeat(3,1fr);gap:16px}.exam-status p{margin:0}}
</style>
