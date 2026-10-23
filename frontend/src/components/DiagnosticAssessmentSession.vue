<script setup>
import { computed, onBeforeUnmount, onMounted, ref, toRaw, watch } from 'vue'
import { onBeforeRouteLeave, useRoute, useRouter } from 'vue-router'
import {
  AlertCircle, ArrowLeft, ArrowRight, BookOpen, Check, CheckCircle2, ChevronDown,
  ChevronUp, Circle, CloudAlert, CloudCheck, FileQuestion, Gauge, LoaderCircle,
  Map, RefreshCw, RotateCcw, Send, ShieldCheck, Target,
} from '@lucide/vue'
import {
  confirmDiagnosticReportPath,
  createMulticourseDiagnosticPaths,
  createDiagnosticReport,
  generateDiagnosticReportPath,
  saveDiagnosticResponse,
  startDiagnosticSession,
  submitDiagnosticSession,
} from '../api'

const props = defineProps({
  blueprintId: { type: String, required: true },
  requestedQuestionId: { type: String, default: '' },
})

const router = useRouter()
const route = useRoute()
const loading = ref(true)
const saving = ref(false)
const submitting = ref(false)
const reportLoading = ref(false)
const pathLoading = ref(false)
const confirmingPath = ref(false)
const error = ref('')
const saveError = ref('')
const reportError = ref('')
const pathError = ref('')
const restored = ref(false)
const session = ref(null)
const blueprint = ref(null)
const activeIndex = ref(0)
const answer = ref({})
const understandingLevel = ref(null)
const saveStates = ref({})
const saveTimer = ref(null)
const activeStartedAt = ref(Date.now())
const restoredDuration = ref(0)
const pendingSave = ref(null)
const hydrating = ref(false)
const report = ref(null)
const expandedEvidenceId = ref('')
const showKnowledgeDetails = ref(false)
const showEvidence = ref(false)
const multiRun = ref(null)
const aggregateResult = ref(null)
const aggregateLoading = ref(false)
const aggregateError = ref('')

const typeLabels = {
  single_choice: '单选题',
  multiple_choice: '多选题',
  true_false: '判断题',
  fill_blank: '填空题',
  short_answer: '简答题',
  code: '代码题',
  open_task: '开放任务',
}
const kindLabels = {
  theory: '理论理解',
  application: '应用判断',
  engineering_judgment: '工程判断',
}
const understandingOptions = [
  { value: 'unfamiliar', label: '不熟悉', confidence: 0.2 },
  { value: 'partial', label: '有些理解', confidence: 0.45 },
  { value: 'mostly', label: '基本理解', confidence: 0.7 },
  { value: 'clear', label: '理解清楚', confidence: 0.9 },
]

const questions = computed(() => blueprint.value?.questions || [])
const activeQuestion = computed(() => questions.value[activeIndex.value] || null)
const responseMap = computed(() => Object.fromEntries((session.value?.responses || []).map((item) => [item.questionVersionId, item])))
const currentResponse = computed(() => activeQuestion.value ? responseMap.value[activeQuestion.value.id] : null)
const progressPercent = computed(() => questions.value.length ? Math.round(((activeIndex.value + 1) / questions.value.length) * 100) : 0)
const completedPercent = computed(() => questions.value.length ? Math.round(((session.value?.completedCount || 0) / questions.value.length) * 100) : 0)
const difficulty = computed(() => blueprint.value?.difficultyBands?.difficulty || {})
const knowledgePoints = computed(() => blueprint.value?.knowledgePointCoverage || [])
const isSubmitted = computed(() => session.value?.status === 'submitted')
const pathReady = computed(() => Boolean(report.value?.path?.plan && report.value?.path?.nodes?.length))
const multiRunId = computed(() => String(route.query.multi_run_id || ''))
const nextMultiCourse = computed(() => {
  if (!multiRun.value) return null
  const completed = new Set((multiRun.value.reports || []).map((item) => typeof item === 'string' ? item : item.blueprintId))
  return (multiRun.value.blueprints || []).find((item) => item.id !== props.blueprintId && !completed.has(item.id)) || null
})
const canAggregate = computed(() => Boolean(multiRun.value && (multiRun.value.reports || []).length >= 2))
const isLastQuestion = computed(() => activeIndex.value === questions.value.length - 1)
const hasUnsavedChanges = computed(() => {
  if (!activeQuestion.value || hydrating.value || isSubmitted.value) return false
  return snapshotCurrent() !== snapshotSaved(currentResponse.value)
})

function messageOf(requestError) {
  const detail = requestError?.detail || requestError?.response?.data?.detail
  return detail?.message || (typeof detail === 'string' ? detail : '') || requestError?.message || '诊断会话暂不可用，请稍后重试。'
}

function pathMessageOf(requestError) {
  const detail = requestError?.detail || requestError?.response?.data?.detail
  const code = detail?.code || requestError?.code || ''
  const messages = {
    provider_call_failed: '模型服务响应超时或暂时不可用，路径尚未创建。请稍后重试。',
    provider_call_cancelled: '本次路径生成已中止，未保存不完整结果。可以重新尝试。',
    structured_output_invalid: '模型已返回内容，但路径结构未通过校验，未保存不完整结果。请重试。',
    path_draft_model_failed: '模型暂时没有完成路径定制，课程和诊断结果仍然保留，可以安全重试。',
  }
  return messages[code] || messageOf(requestError)
}

function loadMultiRun() {
  if (!multiRunId.value) return
  try {
    multiRun.value = JSON.parse(sessionStorage.getItem(`edumatrix-multicourse-run:${multiRunId.value}`) || 'null')
  } catch {
    multiRun.value = null
  }
}

function rememberReport(nextReport) {
  if (!multiRun.value || !nextReport?.id) return
  const existing = (multiRun.value.reports || []).filter((item) => (typeof item === 'string' ? item : item.id) !== nextReport.id)
  const reports = [...existing, { id: nextReport.id, blueprintId: props.blueprintId, courseId: nextReport.course?.id || nextReport.courseId }]
  multiRun.value = { ...multiRun.value, reports }
  sessionStorage.setItem(`edumatrix-multicourse-run:${multiRunId.value}`, JSON.stringify(multiRun.value))
}

function newIdempotencyKey(prefix = 'diagnostic-save') {
  return `${prefix}-${globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(16).slice(2)}`}`
}

function emptyAnswer(question) {
  if (!question) return {}
  if (question.questionType === 'single_choice') return { choice: '' }
  if (question.questionType === 'multiple_choice') return { choices: [] }
  if (question.questionType === 'true_false') return { value: null }
  if (question.questionType === 'fill_blank') {
    const count = Math.max(1, Number(question.responseSpec?.blankCount || 1))
    return { blanks: Array.from({ length: count }, () => '') }
  }
  if (question.questionType === 'code') return { code: '' }
  return { text: '' }
}

function optionLabel(option, index) {
  const value = String(option)
  return /^[A-Z][.)、:\s]/i.test(value) ? value.slice(0, 1).toUpperCase() : String.fromCharCode(65 + index)
}

function snapshot(answerValue, level) {
  return JSON.stringify({ answer: answerValue || {}, understandingLevel: level || null })
}

function snapshotCurrent() {
  return snapshot(answer.value, understandingLevel.value)
}

function snapshotSaved(response) {
  return snapshot(response?.answer || emptyAnswer(activeQuestion.value), response?.understandingLevel || null)
}

function cloneAnswer(value) {
  return structuredClone(toRaw(value))
}

function questionState(questionId) {
  if (saveStates.value[questionId] === 'saving') return 'saving'
  if (saveStates.value[questionId] === 'failed') return 'failed'
  if (responseMap.value[questionId]?.complete) return 'complete'
  if (responseMap.value[questionId]) return 'draft'
  return 'empty'
}

function questionStateLabel(questionId) {
  return {
    saving: '保存中', failed: '保存失败', complete: '已完成', draft: '草稿', empty: '未答',
  }[questionState(questionId)]
}

function responseConfidence() {
  return understandingOptions.find((item) => item.value === understandingLevel.value)?.confidence ?? null
}

function currentDuration() {
  return Math.min(86400, restoredDuration.value + Math.max(0, Math.round((Date.now() - activeStartedAt.value) / 1000)))
}

function syncSession(nextSession) {
  session.value = nextSession
  blueprint.value = nextSession.blueprint
}

function displayPercent(value) {
  return value === null || value === undefined ? '未知' : `${Math.round(Number(value) * 100)}%`
}

function answerText(item) {
  const value = item?.answer || {}
  if (typeof value.value === 'boolean') return value.value ? '正确' : '错误'
  if (value.choice) return value.choice
  if (Array.isArray(value.choices)) return value.choices.join('、')
  if (Array.isArray(value.blanks)) return value.blanks.join(' / ')
  return value.text || value.code || '未记录'
}

function toggleEvidence(id) {
  expandedEvidenceId.value = expandedEvidenceId.value === id ? '' : id
}

function openEvidenceForKnowledgePoint(knowledgePointId) {
  const evidence = report.value?.evidence?.find((item) => item.knowledgePoint.id === knowledgePointId)
  expandedEvidenceId.value = evidence?.questionVersionId || ''
  showEvidence.value = Boolean(evidence)
}

async function loadReport() {
  if (!session.value?.id || reportLoading.value) return
  reportLoading.value = true
  reportError.value = ''
  try {
    const result = await createDiagnosticReport(session.value.id, {
      idempotencyKey: `diagnostic-report-${session.value.id}`,
    })
    report.value = result.report
    rememberReport(result.report)
  } catch (requestError) {
    reportError.value = messageOf(requestError)
  } finally {
    reportLoading.value = false
  }
}

async function buildInitialPath() {
  if (!session.value?.id || pathLoading.value) return
  pathLoading.value = true
  pathError.value = ''
  try {
    const result = await generateDiagnosticReportPath(session.value.id, {
      idempotencyKey: `diagnostic-path-${session.value.id}`,
      timeBudgetMinutes: 90,
    })
    report.value = result.report
  } catch (requestError) {
    pathError.value = pathMessageOf(requestError)
  } finally {
    pathLoading.value = false
  }
}

async function confirmInitialPath() {
  if (!session.value?.id || confirmingPath.value) return
  confirmingPath.value = true
  pathError.value = ''
  try {
    const result = await confirmDiagnosticReportPath(session.value.id, {
      idempotencyKey: `diagnostic-path-confirm-${session.value.id}`,
    })
    await router.push(result.route)
  } catch (requestError) {
    pathError.value = pathMessageOf(requestError)
  } finally {
    confirmingPath.value = false
  }
}

function continueMultiCourse() {
  if (!nextMultiCourse.value) return
  const firstQuestionId = ''
  router.push({
    path: '/workspace/assessment',
    query: {
      course_id: nextMultiCourse.value.courseId,
      blueprint_id: nextMultiCourse.value.id,
      ...(firstQuestionId ? { question_version_id: firstQuestionId } : {}),
      multi_run_id: multiRunId.value,
    },
  })
}

async function generateAggregatePath() {
  if (!canAggregate.value || aggregateLoading.value) return
  aggregateLoading.value = true
  aggregateError.value = ''
  try {
    aggregateResult.value = await createMulticourseDiagnosticPaths({
      reportIds: (multiRun.value.reports || []).map((item) => typeof item === 'string' ? item : item.id),
      idempotencyKey: `multicourse-path-${multiRunId.value}`,
      timeBudgetMinutes: 90,
    })
  } catch (requestError) {
    aggregateError.value = messageOf(requestError)
  } finally {
    aggregateLoading.value = false
  }
}

function hydrateQuestion(index) {
  hydrating.value = true
  activeIndex.value = Math.max(0, Math.min(index, questions.value.length - 1))
  const response = responseMap.value[activeQuestion.value?.id]
  answer.value = cloneAnswer(response?.answer || emptyAnswer(activeQuestion.value))
  understandingLevel.value = response?.understandingLevel || null
  restoredDuration.value = Number(response?.duration || 0)
  activeStartedAt.value = Date.now()
  saveError.value = ''
  pendingSave.value = null
  queueMicrotask(() => { hydrating.value = false })
}

async function loadSession() {
  loading.value = true
  error.value = ''
  try {
    const result = await startDiagnosticSession(props.blueprintId)
    syncSession(result.session)
    const requestedIndex = result.created || !session.value.lastSavedAt
      ? questions.value.findIndex((item) => item.id === props.requestedQuestionId)
      : -1
    const resumeIndex = requestedIndex >= 0 ? requestedIndex : Number(session.value.currentQuestionIndex || 0)
    hydrateQuestion(resumeIndex)
    restored.value = !result.created && Boolean(session.value.lastSavedAt)
    if (isSubmitted.value) {
      // Let the submitted report workspace render its explicit evaluation state
      // while the real model request is still in flight.
      loading.value = false
      await loadReport()
    }
  } catch (requestError) {
    error.value = messageOf(requestError)
  } finally {
    loading.value = false
  }
}

function buildSavePayload(nextQuestionId = null, key = newIdempotencyKey()) {
  return {
    key,
    questionId: activeQuestion.value.id,
    payload: {
      questionVersionId: activeQuestion.value.id,
      answer: cloneAnswer(answer.value),
      understandingLevel: understandingLevel.value,
      duration: currentDuration(),
      confidence: responseConfidence(),
      savedAt: new Date().toISOString(),
      idempotencyKey: key,
      resumeQuestionVersionId: nextQuestionId || activeQuestion.value.id,
    },
  }
}

async function persistCurrent({ nextQuestionId = null, force = false } = {}) {
  if (!session.value || !activeQuestion.value || isSubmitted.value) return true
  if (!force && !hasUnsavedChanges.value && !nextQuestionId) return true
  clearTimeout(saveTimer.value)
  const request = pendingSave.value || buildSavePayload(nextQuestionId)
  if (nextQuestionId) request.payload.resumeQuestionVersionId = nextQuestionId
  pendingSave.value = request
  saving.value = true
  saveError.value = ''
  saveStates.value = { ...saveStates.value, [request.questionId]: 'saving' }
  try {
    const result = await saveDiagnosticResponse(session.value.id, request.questionId, request.payload)
    syncSession(result.session)
    saveStates.value = { ...saveStates.value, [request.questionId]: 'saved' }
    pendingSave.value = null
    restoredDuration.value = Number(responseMap.value[request.questionId]?.duration || request.payload.duration)
    activeStartedAt.value = Date.now()
    return true
  } catch (requestError) {
    saveError.value = messageOf(requestError)
    saveStates.value = { ...saveStates.value, [request.questionId]: 'failed' }
    return false
  } finally {
    saving.value = false
  }
}

function scheduleAutosave() {
  if (hydrating.value || loading.value || isSubmitted.value) return
  clearTimeout(saveTimer.value)
  saveTimer.value = setTimeout(() => persistCurrent(), 700)
}

async function moveTo(index) {
  if (index === activeIndex.value || saving.value || submitting.value) return
  const target = questions.value[index]
  if (!target) return
  const saved = await persistCurrent({ nextQuestionId: target.id, force: hasUnsavedChanges.value })
  if (saved) hydrateQuestion(index)
}

async function nextQuestion() {
  if (isLastQuestion.value) return submitAnswers()
  await moveTo(activeIndex.value + 1)
}

async function submitAnswers() {
  if (submitting.value || saving.value) return
  const saved = await persistCurrent({ force: true })
  if (!saved) return
  if (!session.value.canSubmit) {
    saveError.value = `还有 ${session.value.missingQuestionVersionIds.length} 道题未完成答案或理解程度。`
    return
  }
  submitting.value = true
  saveError.value = ''
  try {
    syncSession(await submitDiagnosticSession(session.value.id, { idempotencyKey: newIdempotencyKey('diagnostic-submit') }))
    await loadReport()
  } catch (requestError) {
    saveError.value = messageOf(requestError)
  } finally {
    submitting.value = false
  }
}

function retrySave() {
  if (pendingSave.value) persistCurrent({ force: true })
}

function backToEntry() {
  router.push({ path: '/workspace/assessment/entry', query: { course_id: blueprint.value?.course?.id } })
}

function beforeUnload(event) {
  if (!hasUnsavedChanges.value && !saving.value && !saveError.value) return
  event.preventDefault()
  event.returnValue = ''
}

watch([answer, understandingLevel], scheduleAutosave, { deep: true })

onBeforeRouteLeave(() => {
  if (!hasUnsavedChanges.value && !saving.value && !saveError.value) return true
  return globalThis.confirm('当前题目尚未可靠保存，确定离开诊断吗？')
})

onMounted(() => {
  loadMultiRun()
  globalThis.addEventListener('beforeunload', beforeUnload)
  loadSession()
})

onBeforeUnmount(() => {
  clearTimeout(saveTimer.value)
  globalThis.removeEventListener('beforeunload', beforeUnload)
})
</script>

<template>
  <div class="diagnostic-session" data-testid="diagnostic-session">
    <header class="session-header">
      <button class="back-button" type="button" title="返回诊断概览" aria-label="返回诊断概览" @click="backToEntry">
        <ArrowLeft :size="18" />
      </button>
      <div class="header-copy">
        <strong>{{ blueprint?.course?.title || '入学诊断' }}</strong>
        <span v-if="!loading">第 {{ activeIndex + 1 }} / {{ questions.length }} 题</span>
      </div>
      <div class="header-progress" aria-label="当前题目进度">
        <div><i :style="{ transform: `scaleX(${progressPercent / 100})` }" /></div>
        <span>{{ progressPercent }}%</span>
      </div>
      <div class="save-indicator" :class="{ failed: saveError }" aria-live="polite">
        <LoaderCircle v-if="saving" class="spin" :size="17" />
        <CloudAlert v-else-if="saveError" :size="17" />
        <CloudCheck v-else :size="17" />
        <span>{{ saving ? '正在保存' : saveError ? '保存失败' : session?.lastSavedAt ? '已自动保存' : '等待作答' }}</span>
      </div>
    </header>

    <div v-if="loading" class="session-loading" data-testid="diagnostic-session-loading">
      <LoaderCircle class="spin" :size="22" />
      <span><strong>正在恢复诊断</strong><small>读取题目、答案和最近保存位置</small></span>
    </div>

    <div v-else-if="error" class="session-failure" role="alert">
      <AlertCircle :size="22" />
      <span><strong>无法打开诊断</strong><small>{{ error }}</small></span>
      <button type="button" @click="loadSession"><RefreshCw :size="16" />重新加载</button>
    </div>

    <section v-else-if="isSubmitted" class="report-workspace" data-testid="diagnostic-submitted">
      <div v-if="reportLoading" class="report-loading" data-testid="diagnostic-report-loading">
        <LoaderCircle class="spin" :size="24" />
        <span><strong>正在准备逐题解析</strong><small>正在分析 {{ session?.blueprint?.questionVersionIds?.length || questions.length }} 道题的作答情况，请稍候。</small></span>
      </div>
      <div v-else-if="reportError && !report" class="report-failure" role="alert" data-testid="diagnostic-report-error">
        <AlertCircle :size="24" />
        <span><strong>报告生成失败，答案仍已保存</strong><small>{{ reportError }}</small></span>
        <button type="button" @click="loadReport"><RefreshCw :size="16" />重新生成报告</button>
      </div>
      <template v-else-if="report">
        <header class="report-hero">
          <div>
            <span class="report-status"><CheckCircle2 :size="16" />诊断结果已保存</span>
            <span v-if="report.evaluation?.status === 'legacy_compatibility'" class="report-evaluation-status">历史诊断结果</span>
            <span v-else-if="report.evaluation" class="report-evaluation-status">逐题解析 {{ report.evaluation.completedCount }}/{{ report.evaluation.totalCount }}</span>
            <h1>你的入学诊断结果</h1>
            <p>{{ report.summary.coreAdvice }}</p>
          </div>
          <div class="score-panel">
            <strong>{{ displayPercent(report.summary.score) }}</strong>
            <span>{{ report.summary.scoreLabel }}</span>
            <small>{{ report.summary.scoredCount }}/{{ report.summary.questionCount }} 道题已完成评分</small>
          </div>
        </header>

        <div class="report-columns">
          <main class="report-main">
            <section class="report-section conclusion-section">
              <header><Target :size="19" /><div><h2>先看结论</h2><p>当前快照只反映这次诊断，不会被当作永久能力标签。</p></div></header>
              <div class="conclusion-grid">
                <article><span>当前强项</span><strong>{{ report.summary.strongest }}</strong></article>
                <article><span>优先补齐</span><strong>{{ report.summary.weakest }}</strong></article>
                <article><span>高信心盲区</span><strong>{{ report.blindSpots.length ? `${report.blindSpots.length} 项` : '暂未发现' }}</strong></article>
              </div>
            </section>

            <section class="report-section report-actions-section" data-testid="report-next-step">
              <header><ArrowRight :size="19" /><div><h2>下一步先做什么</h2><p>先处理最需要补齐的内容，再按需查看每道题的讲解。</p></div></header>
              <div class="report-action-grid">
                <article class="report-action-card report-action-card--primary">
                  <span>优先行动</span>
                  <strong>{{ report.summary.coreAdvice }}</strong>
                </article>
                <article class="report-action-card">
                  <span>薄弱环节</span>
                  <strong>{{ report.weaknesses?.length ? report.weaknesses.slice(0, 3).map((item) => item.title).join('、') : '暂无明确薄弱点' }}</strong>
                  <small>{{ report.weaknesses?.length ? '点击下方知识点可以查看相关题目。' : '继续完成练习，系统会逐步完善学习建议。' }}</small>
                </article>
              </div>
            </section>

            <section class="report-section" data-testid="report-knowledge-progress">
              <header><Gauge :size="19" /><div><h2>知识点掌握情况</h2><p>尚未完成评分的知识点显示“未知”。</p></div></header>
              <div class="report-section-toggle-row">
                <span>{{ report.mastery?.length || 0 }} 个知识点 · {{ report.summary.scoredCount }}/{{ report.summary.questionCount }} 道题已有评分</span>
                <button type="button" class="text-button" data-testid="report-knowledge-toggle" @click="showKnowledgeDetails = !showKnowledgeDetails">
                  {{ showKnowledgeDetails ? '收起知识点' : '查看知识点进度' }} <ChevronDown v-if="!showKnowledgeDetails" :size="16" /><ChevronUp v-else :size="16" />
                </button>
              </div>
              <div v-if="showKnowledgeDetails" class="mastery-list">
                <button
                  v-for="item in report.mastery"
                  :key="item.knowledgePointId"
                  type="button"
                  @click="openEvidenceForKnowledgePoint(item.knowledgePointId)"
                >
                  <span><strong>{{ item.title }}</strong><small>{{ item.evidenceCount }} 次有效作答</small></span>
                  <b>{{ displayPercent(item.score) }}</b>
                  <em>{{ item.label }}</em>
                </button>
              </div>
            </section>

            <section class="report-section" data-testid="report-evidence-drawer">
              <header><BookOpen :size="19" /><div><h2>逐题回顾</h2><p>展开任一题查看你的作答、错误原因和详细讲解。</p></div></header>
              <div class="report-section-toggle-row">
                <span>{{ report.evidence?.length || 0 }} 道题 · 默认收起，按需展开</span>
                <button type="button" class="text-button" data-testid="report-evidence-toggle" @click="showEvidence = !showEvidence">
                  {{ showEvidence ? '收起逐题回顾' : '展开逐题回顾' }} <ChevronDown v-if="!showEvidence" :size="16" /><ChevronUp v-else :size="16" />
                </button>
              </div>
              <div v-if="showEvidence" class="evidence-list">
                <article v-for="(item, index) in report.evidence" :key="item.questionVersionId" :class="{ open: expandedEvidenceId === item.questionVersionId }">
                  <button type="button" @click="toggleEvidence(item.questionVersionId)">
                    <span class="evidence-index">{{ index + 1 }}</span>
                    <span><strong>{{ item.knowledgePoint.title }}</strong><small>{{ item.errorType.label }} · {{ item.understandingLabel }}</small></span>
                    <b>{{ displayPercent(item.score) }}</b>
                    <ChevronUp v-if="expandedEvidenceId === item.questionVersionId" :size="18" />
                    <ChevronDown v-else :size="18" />
                  </button>
                  <div v-if="expandedEvidenceId === item.questionVersionId" class="evidence-detail">
                    <h3>{{ item.prompt }}</h3>
                    <dl>
                      <div><dt>你的作答</dt><dd>{{ answerText(item) }}</dd></div>
                      <div><dt>错误原因</dt><dd>{{ item.judgmentBasis || item.errorType.basis }}</dd></div>
                      <div><dt>详细解析</dt><dd>{{ item.explanation || '这道题暂时没有详细解析。' }}</dd></div>
                      <div v-if="item.evaluation"><dt>点评把握</dt><dd>{{ displayPercent(item.evaluation.confidence) }} · {{ item.evaluation.status === 'insufficient_evidence' ? '还需要更多作答信息' : item.evaluation.status === 'partially_supported' ? '仍有部分内容需要确认' : '点评已完成' }}</dd></div>
                      <div v-if="item.evaluation?.claim"><dt>老师点评</dt><dd>{{ item.evaluation.claim }}</dd></div>
                    </dl>
                  </div>
                </article>
              </div>
            </section>
          </main>

          <aside class="report-side">
            <section class="difficulty-panel">
              <header><Gauge :size="18" /><div><h2>难度匹配</h2><p>目标难度 {{ displayPercent(report.difficultyFit.target) }}</p></div></header>
              <div v-for="band in report.difficultyFit.bands" :key="band.key" class="difficulty-row">
                <span>{{ band.label }}</span><i><b :style="{ width: band.score === null ? '0%' : `${band.score * 100}%` }" /></i><strong>{{ displayPercent(band.score) }}</strong>
              </div>
              <small>{{ report.difficultyFit.basis }}</small>
            </section>

            <section class="path-panel">
              <header><Map :size="18" /><div><h2>初始学习路径</h2><p>路径失败可单独重试，不影响上方报告。</p></div></header>
              <div v-if="pathError" class="inline-error" role="alert"><AlertCircle :size="16" />{{ pathError }}</div>
              <template v-if="pathReady">
                <ol>
                  <li v-for="node in report.path.nodes" :key="node.node_key">
                    <span>{{ node.chapter?.position || '—' }}</span>
                    <div><strong>{{ node.title }}</strong><small>{{ node.reason }} · 难度 {{ displayPercent(node.difficulty) }}</small></div>
                  </li>
                </ol>
                <button class="primary-action path-action" type="button" :disabled="confirmingPath" @click="confirmInitialPath">
                  <LoaderCircle v-if="confirmingPath" class="spin" :size="17" />
                  <ArrowRight v-else :size="17" />
                  {{ confirmingPath ? '正在确认' : '确认并进入总学习路径' }}
                </button>
                <button v-if="nextMultiCourse" class="secondary-action path-action" type="button" @click="continueMultiCourse">
                  <ArrowRight :size="17" />继续下一门课程
                </button>
                <button v-else-if="canAggregate && !aggregateResult" class="secondary-action path-action" type="button" :disabled="aggregateLoading" @click="generateAggregatePath">
                  <LoaderCircle v-if="aggregateLoading" class="spin" :size="17" />
                  <Map v-else :size="17" />
                  {{ aggregateLoading ? '正在统筹多科总路径' : '生成并验证多科总路径' }}
                </button>
                <div v-if="aggregateError" class="inline-error" role="alert"><AlertCircle :size="16" />{{ aggregateError }}</div>
                <div v-if="aggregateResult" class="aggregate-result" data-testid="multicourse-total-path-result">
                  <strong>总路径统筹：{{ aggregateResult.total_validation?.status || aggregateResult.status }}</strong>
                  <small>已合并 {{ aggregateResult.total_validation?.course_ids?.length || 0 }} 门课程，{{ aggregateResult.total_validation?.days?.length || 0 }} 天任务。</small>
                  <small v-if="aggregateResult.total_validation?.issues?.length">发现 {{ aggregateResult.total_validation.issues.length }} 项需要处理的问题：</small>
                  <ul v-if="aggregateResult.total_validation?.issues?.length">
                    <li v-for="issue in aggregateResult.total_validation.issues" :key="`${issue.code}-${issue.course_id || ''}-${issue.node_key || ''}`">{{ issue.message }}</li>
                  </ul>
                  <button v-if="aggregateResult.total_plan" type="button" class="text-button" @click="router.push({ path: '/workspace/path', query: { aggregate_plan_id: aggregateResult.total_plan.id, course_id: aggregateResult.subjects?.find(item => item.course_id)?.course_id || undefined } })">查看总路径草稿 <ArrowRight :size="15" /></button>
                </div>
              </template>
              <button v-else class="primary-action path-action" type="button" :disabled="pathLoading" @click="buildInitialPath">
                <LoaderCircle v-if="pathLoading" class="spin" :size="17" />
                <Map v-else :size="17" />
                {{ pathLoading ? '正在生成路径' : pathError ? '重试生成路径' : '生成初始学习路径' }}
              </button>
            </section>

            <p class="report-boundary"><ShieldCheck :size="16" />{{ report.boundary }}</p>
          </aside>
        </div>
      </template>
    </section>

    <div v-else class="session-grid">
      <aside class="question-rail" aria-label="诊断题目导航">
        <div class="rail-heading">
          <span><strong>题目</strong><small>{{ session.completedCount }}/{{ questions.length }} 已完成</small></span>
          <b>{{ completedPercent }}%</b>
        </div>
        <div class="question-buttons">
          <button
            v-for="(question, index) in questions"
            :key="question.id"
            type="button"
            :class="[questionState(question.id), { active: activeIndex === index }]"
            :aria-current="activeIndex === index ? 'step' : undefined"
            :disabled="saving || submitting"
            @click="moveTo(index)"
          >
            <span class="number">{{ index + 1 }}</span>
            <span><strong>{{ typeLabels[question.questionType] }}</strong><small>{{ questionStateLabel(question.id) }}</small></span>
            <LoaderCircle v-if="questionState(question.id) === 'saving'" class="spin" :size="15" />
            <AlertCircle v-else-if="questionState(question.id) === 'failed'" :size="15" />
            <Check v-else-if="questionState(question.id) === 'complete'" :size="15" />
            <Circle v-else :size="14" />
          </button>
        </div>
        <p>答案与理解程度会一起保存。保存失败时仍停留在当前题。</p>
      </aside>

      <main v-if="activeQuestion" class="question-workspace">
        <div v-if="restored" class="restore-notice" data-testid="diagnostic-restored">
          <RotateCcw :size="16" />已恢复到上次保存位置，原答案未丢失。
          <button type="button" title="关闭提示" aria-label="关闭恢复提示" @click="restored = false">×</button>
        </div>
        <div v-if="saveError" class="save-failure" role="alert" data-testid="diagnostic-save-error">
          <CloudAlert :size="18" />
          <span><strong>当前修改尚未保存</strong><small>{{ saveError }} 本页答案仍保留，可以直接重试。</small></span>
          <button type="button" :disabled="saving" @click="retrySave"><RefreshCw :size="16" />重试保存</button>
        </div>

        <section class="question-heading">
          <div class="question-meta">
            <span>{{ typeLabels[activeQuestion.questionType] }}</span>
            <span>{{ kindLabels[activeQuestion.diagnosticKind] }}</span>
            <span>难度 {{ Number(activeQuestion.expertDifficulty || 0).toFixed(2) }}</span>
          </div>
          <h1>{{ activeQuestion.prompt }}</h1>
        </section>

        <div v-if="activeQuestion.questionType === 'single_choice'" class="option-list">
          <label v-for="(option, index) in activeQuestion.options" :key="option" :class="{ selected: answer.choice === optionLabel(option, index) }">
            <input v-model="answer.choice" type="radio" :value="optionLabel(option, index)" />
            <b>{{ optionLabel(option, index) }}</b><span>{{ option }}</span>
          </label>
        </div>

        <div v-else-if="activeQuestion.questionType === 'multiple_choice'" class="option-list">
          <label v-for="(option, index) in activeQuestion.options" :key="option" :class="{ selected: answer.choices?.includes(optionLabel(option, index)) }">
            <input v-model="answer.choices" type="checkbox" :value="optionLabel(option, index)" />
            <b>{{ optionLabel(option, index) }}</b><span>{{ option }}</span>
          </label>
        </div>

        <div v-else-if="activeQuestion.questionType === 'true_false'" class="boolean-control">
          <button type="button" :class="{ selected: answer.value === true }" @click="answer.value = true"><CheckCircle2 :size="18" />正确</button>
          <button type="button" :class="{ selected: answer.value === false }" @click="answer.value = false"><Circle :size="18" />错误</button>
        </div>

        <div v-else-if="activeQuestion.questionType === 'fill_blank'" class="blank-list">
          <label v-for="(_, index) in answer.blanks" :key="index"><span>空 {{ index + 1 }}</span><input v-model="answer.blanks[index]" /></label>
        </div>

        <div v-else-if="activeQuestion.questionType === 'code'" class="code-answer">
          <div><span>Python 作答</span><small>答案只保存，不在此阶段运行或评分</small></div>
          <textarea v-model="answer.code" rows="12" spellcheck="false" placeholder="输入你的代码" />
        </div>

        <textarea
          v-else
          v-model="answer.text"
          class="text-answer"
          rows="9"
          placeholder="输入你的回答"
        />

        <fieldset class="understanding-control">
          <legend>你对这道题的理解程度</legend>
          <div role="radiogroup" aria-label="理解程度">
            <label v-for="item in understandingOptions" :key="item.value" :class="{ selected: understandingLevel === item.value }">
              <input v-model="understandingLevel" type="radio" :value="item.value" />
              <span>{{ item.label }}</span>
            </label>
          </div>
          <p>请按真实感受选择。这个信息会与答案一起用于后续诊断，不会单独决定分数。</p>
        </fieldset>

        <footer class="question-actions">
          <button type="button" class="secondary-action" :disabled="activeIndex === 0 || saving" @click="moveTo(activeIndex - 1)">
            <ArrowLeft :size="17" />上一题
          </button>
          <span>{{ saving ? '正在保存当前题' : hasUnsavedChanges ? '修改后将自动保存' : currentResponse ? '当前题已保存' : '作答后自动保存' }}</span>
          <button type="button" class="primary-action" :disabled="saving || submitting" @click="nextQuestion">
            <LoaderCircle v-if="submitting" class="spin" :size="17" />
            <Send v-else-if="isLastQuestion" :size="17" />
            <ArrowRight v-else :size="17" />
            {{ submitting ? '正在提交' : isLastQuestion ? '提交本次诊断' : '保存并进入下一题' }}
          </button>
        </footer>
      </main>

      <aside class="overview-rail" aria-label="本次摸底概览">
        <section>
          <header><FileQuestion :size="18" /><span><strong>本次摸底</strong><small>只展示作答所需信息</small></span></header>
          <dl>
            <div><dt>题目数量</dt><dd>{{ questions.length }} 道</dd></div>
            <div><dt>预计时间</dt><dd>{{ blueprint.estimatedMinutes }} 分钟</dd></div>
            <div><dt>当前进度</dt><dd>{{ activeIndex + 1 }} / {{ questions.length }}</dd></div>
            <div><dt>已保存完成</dt><dd>{{ session.completedCount }} 道</dd></div>
          </dl>
        </section>
        <section>
          <header><Gauge :size="18" /><span><strong>难度分布</strong><small>按当前画像选择</small></span></header>
          <div class="difficulty-list">
            <div><span>基础</span><b>{{ difficulty.foundation || 0 }}</b></div>
            <div><span>标准</span><b>{{ difficulty.standard || 0 }}</b></div>
            <div><span>拓展</span><b>{{ difficulty.stretch || 0 }}</b></div>
          </div>
        </section>
        <section>
          <header><BookOpen :size="18" /><span><strong>知识点覆盖</strong><small>{{ knowledgePoints.length }} 个课程知识点</small></span></header>
          <ul>
            <li v-for="point in knowledgePoints" :key="point.id"><Check :size="14" />{{ point.title }}</li>
          </ul>
        </section>
        <p class="evidence-boundary"><ShieldCheck :size="16" />普通浏览不会改变掌握度。提交后才进入诊断报告阶段。</p>
      </aside>
    </div>
  </div>
</template>

<style scoped>
.diagnostic-session { width: 100%; min-width: 0; min-height: calc(100vh - var(--topbar-height)); color: var(--color-text); background: var(--color-surface); }
.session-header { display: grid; min-height: 66px; grid-template-columns: 40px minmax(240px, 1fr) minmax(220px, 360px) 132px; align-items: center; gap: 15px; padding: 0 22px; border-bottom: 1px solid var(--color-border); }
.back-button { display: grid; width: 38px; height: 38px; place-items: center; color: var(--color-text-secondary); border: 1px solid var(--color-border); border-radius: var(--radius-control); background: var(--color-surface); cursor: pointer; }
.back-button:hover { color: var(--color-accent); border-color: var(--color-border-strong); background: var(--color-surface-subtle); }
.header-copy { display: flex; min-width: 0; align-items: baseline; gap: 12px; }
.header-copy strong { overflow: hidden; font-size: 16px; text-overflow: ellipsis; white-space: nowrap; }
.header-copy span { flex: 0 0 auto; color: var(--color-text-muted); font-size: 14px; }
.header-progress { display: grid; grid-template-columns: minmax(120px, 1fr) 44px; align-items: center; gap: 10px; }
.header-progress > div { height: 5px; overflow: hidden; border-radius: 3px; background: var(--color-surface-muted); }
.header-progress i { display: block; width: 100%; height: 100%; border-radius: inherit; background: var(--color-accent); transform-origin: left center; transition: transform 200ms ease; }
.header-progress span { color: var(--color-text-secondary); font-size: 14px; font-variant-numeric: tabular-nums; }
.save-indicator { display: flex; align-items: center; justify-content: flex-end; gap: 7px; color: var(--color-text-secondary); font-size: 14px; }
.save-indicator.failed { color: var(--color-danger); }

.session-grid { display: grid; min-height: calc(100vh - var(--topbar-height) - 66px); grid-template-columns: minmax(168px, 18fr) minmax(500px, 62fr) minmax(210px, 20fr); }
.question-rail, .overview-rail { min-width: 0; background: var(--color-surface-subtle); }
.question-rail { display: grid; grid-template-rows: auto 1fr auto; border-right: 1px solid var(--color-border); }
.rail-heading { display: flex; min-height: 74px; align-items: center; justify-content: space-between; gap: 8px; padding: 14px 16px; border-bottom: 1px solid var(--color-border); }
.rail-heading > span { display: grid; }
.rail-heading strong { font-size: 16px; }
.rail-heading small { color: var(--color-text-muted); font-size: 14px; }
.rail-heading b { color: var(--color-accent); font-size: 14px; font-variant-numeric: tabular-nums; }
.question-buttons { overflow-y: auto; }
.question-buttons button { display: grid; width: 100%; min-height: 64px; grid-template-columns: 34px minmax(0, 1fr) 18px; align-items: center; gap: 9px; padding: 9px 13px; color: var(--color-text-secondary); border: 0; border-bottom: 1px solid var(--color-border); background: transparent; text-align: left; cursor: pointer; }
.question-buttons button:hover { background: var(--color-surface-muted); }
.question-buttons button.active { color: var(--color-text); background: var(--color-surface); box-shadow: inset 3px 0 var(--color-accent); }
.question-buttons button.failed { color: var(--color-danger); }
.question-buttons button:disabled { cursor: wait; }
.question-buttons .number { display: grid; width: 32px; height: 32px; place-items: center; color: var(--color-text-secondary); border: 1px solid var(--color-border-strong); border-radius: var(--radius-control); background: var(--color-surface); font-size: 14px; font-variant-numeric: tabular-nums; }
.question-buttons button.active .number, .question-buttons button.complete .number { color: #ffffff; border-color: var(--color-accent); background: var(--color-accent); }
.question-buttons button > span:nth-child(2) { display: grid; min-width: 0; }
.question-buttons strong, .question-buttons small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.question-buttons strong { font-size: 14px; }
.question-buttons small { color: var(--color-text-muted); font-size: 14px; }
.question-rail > p { margin: 0; padding: 14px 16px; color: var(--color-text-muted); border-top: 1px solid var(--color-border); font-size: 14px; line-height: 1.55; }

.question-workspace { min-width: 0; padding: 24px clamp(24px, 3vw, 44px) 28px; }
.restore-notice, .save-failure { display: flex; min-height: 46px; align-items: center; gap: 10px; margin-bottom: 16px; padding: 10px 12px; border: 1px solid var(--color-border-strong); border-radius: var(--radius-control); background: var(--color-accent-soft); font-size: 14px; }
.restore-notice { color: var(--color-accent); }
.restore-notice button { margin-left: auto; color: inherit; border: 0; background: transparent; font-size: 20px; cursor: pointer; }
.save-failure { color: var(--color-danger); border-color: #dfbcbc; background: var(--color-danger-soft); }
.save-failure > span { display: grid; min-width: 0; flex: 1; }
.save-failure strong, .save-failure small { font-size: 14px; }
.save-failure small { color: #783d3d; line-height: 1.5; }
.save-failure button, .session-failure button { display: inline-flex; min-height: 38px; flex: 0 0 auto; align-items: center; gap: 7px; padding: 0 12px; color: var(--color-danger); border: 1px solid currentColor; border-radius: var(--radius-control); background: var(--color-surface); font-size: 14px; font-weight: 650; cursor: pointer; }
.question-heading { padding-bottom: 22px; border-bottom: 1px solid var(--color-border); }
.question-meta { display: flex; flex-wrap: wrap; gap: 7px; }
.question-meta span { padding: 4px 8px; color: var(--color-text-secondary); border: 1px solid var(--color-border); border-radius: var(--radius-control); background: var(--color-surface-subtle); font-size: 14px; }
.question-heading h1 { max-width: 78ch; margin: 16px 0 0; font-size: 20px; font-weight: 650; line-height: 1.6; }

.option-list { display: grid; gap: 10px; margin-top: 22px; }
.option-list label { display: grid; min-height: 54px; grid-template-columns: 0 32px minmax(0, 1fr); align-items: center; gap: 11px; padding: 9px 13px; border: 1px solid var(--color-border-strong); border-radius: var(--radius-control); background: var(--color-surface); cursor: pointer; }
.option-list label:hover { background: var(--color-surface-subtle); }
.option-list label.selected { color: var(--color-text); border-color: var(--color-accent); background: var(--color-accent-soft); }
.option-list input { width: 0; opacity: 0; }
.option-list b { display: grid; width: 30px; height: 30px; place-items: center; color: var(--color-text-secondary); border: 1px solid var(--color-border); border-radius: var(--radius-control); background: var(--color-surface); font-size: 14px; }
.option-list .selected b { color: #ffffff; border-color: var(--color-accent); background: var(--color-accent); }
.option-list span { font-size: 15px; line-height: 1.55; }
.boolean-control { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; margin-top: 22px; }
.boolean-control button { display: inline-flex; min-height: 58px; align-items: center; justify-content: center; gap: 9px; color: var(--color-text-secondary); border: 1px solid var(--color-border-strong); border-radius: var(--radius-control); background: var(--color-surface); font-size: 15px; font-weight: 650; cursor: pointer; }
.boolean-control button.selected { color: #ffffff; border-color: var(--color-accent); background: var(--color-accent); }
.blank-list { display: grid; gap: 12px; margin-top: 22px; }
.blank-list label { display: grid; grid-template-columns: 60px minmax(0, 1fr); align-items: center; gap: 10px; }
.blank-list span { color: var(--color-text-secondary); font-size: 14px; }
.blank-list input, .text-answer { width: 100%; padding: 11px 12px; color: var(--color-text); border: 1px solid var(--color-border-strong); border-radius: var(--radius-control); background: var(--color-surface); font-size: 15px; }
.text-answer { min-height: 190px; margin-top: 22px; resize: vertical; line-height: 1.65; }
.code-answer { overflow: hidden; margin-top: 22px; border: 1px solid var(--color-accent); border-radius: var(--radius-control); background: var(--color-accent); }
.code-answer > div { display: flex; min-height: 42px; align-items: center; justify-content: space-between; gap: 12px; padding: 0 13px; color: #f2f5f6; border-bottom: 1px solid rgb(255 255 255 / 18%); font-size: 14px; }
.code-answer small { color: #c8d2d6; font-size: 14px; }
.code-answer textarea { width: 100%; min-height: 220px; resize: vertical; color: #f2f5f6; border: 0; background: var(--color-accent); padding: 14px; font: 15px/1.65 var(--font-mono); outline: none; }

.understanding-control { margin: 26px 0 0; padding: 19px 0 0; border: 0; border-top: 1px solid var(--color-border); }
.understanding-control legend { padding: 0; font-size: 16px; font-weight: 650; }
.understanding-control > div { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 8px; margin-top: 12px; }
.understanding-control label { display: grid; min-height: 42px; place-items: center; color: var(--color-text-secondary); border: 1px solid var(--color-border-strong); border-radius: var(--radius-control); background: var(--color-surface); cursor: pointer; }
.understanding-control label.selected { color: #ffffff; border-color: var(--color-accent); background: var(--color-accent); }
.understanding-control input { position: absolute; opacity: 0; pointer-events: none; }
.understanding-control span { font-size: 14px; font-weight: 650; }
.understanding-control p { margin: 10px 0 0; color: var(--color-text-muted); font-size: 14px; line-height: 1.55; }
.question-actions { display: grid; grid-template-columns: auto minmax(150px, 1fr) auto; align-items: center; gap: 14px; margin-top: 24px; padding-top: 18px; border-top: 1px solid var(--color-border); }
.question-actions > span { color: var(--color-text-muted); font-size: 14px; text-align: center; }
.secondary-action, .primary-action, .submitted-state button { display: inline-flex; min-height: 42px; align-items: center; justify-content: center; gap: 8px; padding: 0 16px; border-radius: var(--radius-control); font-size: 15px; font-weight: 650; cursor: pointer; }
.secondary-action { color: var(--color-text); border: 1px solid var(--color-border-strong); background: var(--color-surface); }
.primary-action, .submitted-state button { color: #ffffff; border: 1px solid var(--color-accent); background: var(--color-accent); }
.primary-action:hover, .submitted-state button:hover { background: #000000; }
.secondary-action:disabled, .primary-action:disabled { opacity: .45; cursor: not-allowed; }

.overview-rail { border-left: 1px solid var(--color-border); }
.overview-rail section { padding: 20px 18px; border-bottom: 1px solid var(--color-border); }
.overview-rail header { display: flex; align-items: flex-start; gap: 9px; }
.overview-rail header > svg { margin-top: 2px; color: var(--color-accent); }
.overview-rail header span { display: grid; }
.overview-rail header strong { font-size: 15px; }
.overview-rail header small { color: var(--color-text-muted); font-size: 14px; line-height: 1.5; }
.overview-rail dl { display: grid; gap: 11px; margin: 17px 0 0; }
.overview-rail dl div { display: flex; justify-content: space-between; gap: 10px; }
.overview-rail dt, .overview-rail dd { margin: 0; font-size: 14px; }
.overview-rail dt { color: var(--color-text-muted); }
.overview-rail dd { color: var(--color-text); font-weight: 650; font-variant-numeric: tabular-nums; }
.difficulty-list { display: grid; gap: 9px; margin-top: 15px; }
.difficulty-list div { display: flex; min-height: 36px; align-items: center; justify-content: space-between; padding: 0 10px; border: 1px solid var(--color-border); border-radius: var(--radius-control); background: var(--color-surface); }
.difficulty-list span, .difficulty-list b { font-size: 14px; }
.overview-rail ul { display: grid; gap: 9px; margin: 15px 0 0; padding: 0; list-style: none; }
.overview-rail li { display: flex; align-items: flex-start; gap: 7px; color: var(--color-text-secondary); font-size: 14px; line-height: 1.5; }
.overview-rail li svg { flex: 0 0 auto; margin-top: 3px; color: var(--color-accent); }
.evidence-boundary { display: flex; align-items: flex-start; gap: 8px; margin: 0; padding: 18px; color: var(--color-text-muted); font-size: 14px; line-height: 1.55; }
.evidence-boundary svg { flex: 0 0 auto; margin-top: 3px; color: var(--color-accent); }

.session-loading, .session-failure, .submitted-state { display: grid; min-height: calc(100vh - var(--topbar-height) - 66px); place-items: center; align-content: center; gap: 12px; padding: 32px; text-align: center; }
.session-loading span, .session-failure span { display: grid; gap: 3px; }
.session-loading strong, .session-failure strong { font-size: 17px; }
.session-loading small, .session-failure small { color: var(--color-text-secondary); font-size: 14px; }
.session-failure { color: var(--color-danger); }
.submitted-state svg { color: var(--color-accent); }
.submitted-state h2 { margin: 2px 0 0; font-family: var(--font-display); font-size: 26px; }
.submitted-state p { max-width: 620px; margin: 0; color: var(--color-text-secondary); font-size: 15px; line-height: 1.7; }
.submitted-state button { margin-top: 8px; }
.report-workspace { min-height: calc(100vh - var(--topbar-height) - 66px); padding: 28px clamp(20px, 3vw, 44px) 42px; background: var(--color-page); }
.report-loading, .report-failure { display: flex; min-height: 340px; align-items: center; justify-content: center; gap: 12px; color: var(--color-text-secondary); text-align: left; }
.report-loading span, .report-failure span { display: grid; gap: 4px; }
.report-loading strong, .report-failure strong { color: var(--color-text); font-size: 18px; }
.report-loading small, .report-failure small { font-size: 14px; line-height: 1.55; }
.report-failure { color: var(--color-danger); }
.report-failure button { display: inline-flex; min-height: 40px; align-items: center; gap: 7px; padding: 0 14px; color: var(--color-danger); border: 1px solid currentColor; border-radius: var(--radius-control); background: var(--color-surface); font-size: 14px; font-weight: 650; cursor: pointer; }
.report-hero { display: grid; grid-template-columns: minmax(0, 1fr) 220px; align-items: end; gap: 28px; max-width: 1240px; margin: 0 auto; padding: 28px 30px; border: 1px solid var(--color-border); border-radius: var(--radius-card); background: var(--color-surface); }
.report-status { display: inline-flex; align-items: center; gap: 7px; color: var(--color-accent); font-size: 14px; font-weight: 650; }
.report-evaluation-status { display: inline-flex; margin-left: 10px; color: var(--color-text-muted); font-size: 14px; }
.report-hero h1 { margin: 12px 0 7px; font-family: var(--font-display); font-size: 32px; line-height: 1.25; }
.report-hero p { max-width: 72ch; margin: 0; color: var(--color-text-secondary); font-size: 15px; line-height: 1.65; }
.score-panel { display: grid; justify-items: end; }
.score-panel strong { font-size: 42px; font-weight: 700; line-height: 1; font-variant-numeric: tabular-nums; }
.score-panel span { margin-top: 7px; color: var(--color-accent); font-size: 15px; font-weight: 650; }
.score-panel small { margin-top: 4px; color: var(--color-text-muted); font-size: 14px; }
.report-columns { display: grid; max-width: 1240px; grid-template-columns: minmax(0, 1fr) 330px; gap: 28px; margin: 24px auto 0; align-items: start; }
.report-main { display: grid; gap: 26px; min-width: 0; padding: 28px 30px; border: 1px solid var(--color-border); border-radius: var(--radius-card); background: var(--color-surface); }
.report-section { min-width: 0; padding-bottom: 26px; border-bottom: 1px solid var(--color-border); }
.report-section > header, .difficulty-panel > header, .path-panel > header { display: flex; align-items: flex-start; gap: 10px; }
.report-section > header > svg, .difficulty-panel > header > svg, .path-panel > header > svg { flex: none; margin-top: 3px; color: var(--color-accent); }
.report-section h2, .difficulty-panel h2, .path-panel h2 { margin: 0; font-size: 18px; }
.report-section header p, .difficulty-panel header p, .path-panel header p { margin: 4px 0 0; color: var(--color-text-muted); font-size: 14px; line-height: 1.5; }
.conclusion-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); margin-top: 18px; border-block: 1px solid var(--color-border); }
.conclusion-grid article { display: grid; min-height: 104px; align-content: center; gap: 7px; padding: 16px 18px; border-right: 1px solid var(--color-border); }
.conclusion-grid article:last-child { border-right: 0; }
.conclusion-grid span { color: var(--color-text-muted); font-size: 14px; }
.conclusion-grid strong { font-size: 17px; line-height: 1.45; }
.decision-basis { display: flex; flex-wrap: wrap; gap: 8px 18px; margin: 15px 0 0; padding: 0; list-style: none; }
.decision-basis li { display: flex; align-items: center; gap: 6px; color: var(--color-text-secondary); font-size: 14px; }
.decision-basis svg { color: var(--color-accent); }
.report-actions-section { padding-bottom: 24px; }
.report-action-grid { display: grid; grid-template-columns: minmax(0, 1.35fr) minmax(0, 1fr); gap: 12px; margin-top: 16px; }
.report-action-card { display: grid; min-width: 0; gap: 7px; padding: 16px; border: 1px solid var(--color-border); border-radius: var(--radius-control); background: var(--color-surface-muted); }
.report-action-card--primary { border-color: var(--color-border-strong); background: var(--color-surface-subtle); }
.report-action-card span { color: var(--color-text-muted); font-size: 14px; }
.report-action-card strong { color: var(--color-text); font-size: 15px; line-height: 1.55; }
.report-action-card small { color: var(--color-text-secondary); font-size: 14px; line-height: 1.5; }
.report-section-toggle-row { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-top: 15px; color: var(--color-text-muted); font-size: 14px; line-height: 1.5; }
.text-button { display: inline-flex; min-height: 36px; align-items: center; gap: 5px; flex: 0 0 auto; padding: 0 10px; color: var(--color-accent); border: 1px solid var(--color-border-strong); border-radius: var(--radius-control); background: var(--color-surface); font-size: 14px; font-weight: 650; cursor: pointer; }
.text-button:hover { background: var(--color-surface-subtle); }
.mastery-list { display: grid; margin-top: 16px; border-top: 1px solid var(--color-border); }
.mastery-list button { display: grid; min-height: 68px; grid-template-columns: minmax(0, 1fr) 74px 86px; align-items: center; gap: 14px; padding: 10px 2px; color: var(--color-text); border: 0; border-bottom: 1px solid var(--color-border); background: transparent; text-align: left; cursor: pointer; }
.mastery-list button:hover { background: var(--color-surface-muted); }
.mastery-list button > span { display: grid; gap: 3px; }
.mastery-list strong { font-size: 15px; }
.mastery-list small { color: var(--color-text-muted); font-size: 14px; }
.mastery-list b { font-size: 16px; font-variant-numeric: tabular-nums; }
.mastery-list em { color: var(--color-accent); font-size: 14px; font-style: normal; font-weight: 650; text-align: right; }
.evidence-list { display: grid; margin-top: 16px; border-top: 1px solid var(--color-border); }
.evidence-list article { border-bottom: 1px solid var(--color-border); }
.evidence-list article > button { display: grid; width: 100%; min-height: 68px; grid-template-columns: 34px minmax(0, 1fr) 68px 20px; align-items: center; gap: 12px; padding: 8px 2px; color: var(--color-text); border: 0; background: transparent; text-align: left; cursor: pointer; }
.evidence-list article > button:hover { background: var(--color-surface-muted); }
.evidence-index { display: grid; width: 30px; height: 30px; place-items: center; color: var(--color-text-secondary); border: 1px solid var(--color-border-strong); border-radius: var(--radius-control); font-size: 14px; }
.evidence-list button > span:nth-child(2) { display: grid; gap: 3px; }
.evidence-list button strong { font-size: 15px; }
.evidence-list button small { color: var(--color-text-muted); font-size: 14px; }
.evidence-list button > b { font-size: 15px; font-variant-numeric: tabular-nums; }
.evidence-detail { padding: 4px 46px 20px; }
.evidence-detail h3 { margin: 4px 0 14px; font-size: 15px; font-weight: 600; line-height: 1.6; }
.evidence-detail dl { display: grid; gap: 10px; margin: 0; }
.evidence-detail dl div { display: grid; grid-template-columns: 90px minmax(0, 1fr); gap: 12px; }
.evidence-detail dt { color: var(--color-text-muted); font-size: 14px; }
.evidence-detail dd { margin: 0; font-size: 14px; line-height: 1.6; }
.source-list { display: grid; gap: 7px; margin-top: 14px; }
.source-list :deep(.source-citation) { overflow: hidden; border: 1px solid var(--color-border); border-radius: var(--radius-control); background: var(--color-surface); }
.source-list :deep(.source-citation__action) { padding-inline: 10px; }
.report-side { display: grid; gap: 18px; position: sticky; top: calc(var(--topbar-height) + 18px); }
.difficulty-panel, .path-panel { padding: 18px; border: 1px solid var(--color-border-strong); border-radius: var(--radius-card); background: var(--color-surface); }
.difficulty-row { display: grid; grid-template-columns: 48px minmax(0, 1fr) 48px; align-items: center; gap: 8px; margin-top: 14px; }
.difficulty-row span, .difficulty-row strong { font-size: 14px; }
.difficulty-row strong { text-align: right; font-variant-numeric: tabular-nums; }
.difficulty-row i { height: 6px; overflow: hidden; border-radius: 3px; background: var(--color-surface-muted); }
.difficulty-row b { display: block; height: 100%; border-radius: inherit; background: var(--color-accent); }
.difficulty-panel > small { display: block; margin-top: 14px; color: var(--color-text-muted); font-size: 14px; line-height: 1.55; }
.path-panel ol { display: grid; gap: 0; margin: 15px 0 0; padding: 0; list-style: none; }
.path-panel li { display: grid; grid-template-columns: 28px minmax(0, 1fr); gap: 9px; padding: 11px 0; border-top: 1px solid var(--color-border); }
.path-panel li > span { display: grid; width: 26px; height: 26px; place-items: center; color: #fff; border-radius: var(--radius-control); background: var(--color-accent); font-size: 14px; }
.path-panel li > div { display: grid; gap: 3px; }
.path-panel li strong, .path-panel li small { font-size: 14px; line-height: 1.45; }
.path-panel li small { color: var(--color-text-muted); }
.path-action { width: 100%; margin-top: 15px; }
.aggregate-result { display: grid; gap: 6px; margin-top: 15px; border-top: 1px solid var(--color-border); padding-top: 14px; }
.aggregate-result strong { color: var(--color-text); font-size: 15px; }
.aggregate-result small, .aggregate-result li { color: var(--color-text-muted); font-size: 14px; line-height: 1.5; }
.aggregate-result ul { display: grid; gap: 4px; margin: 2px 0 4px; padding-left: 18px; }
.inline-error { display: flex; align-items: flex-start; gap: 7px; margin-top: 13px; padding: 10px; color: var(--color-danger); border: 1px solid #dfbcbc; border-radius: var(--radius-control); background: var(--color-danger-soft); font-size: 14px; line-height: 1.5; }
.inline-error svg { flex: none; margin-top: 2px; }
.report-boundary { display: flex; align-items: flex-start; gap: 8px; margin: 0; color: var(--color-text-muted); font-size: 14px; line-height: 1.55; }
.report-boundary svg { flex: none; margin-top: 2px; color: var(--color-accent); }
.spin { animation: spin .8s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }

@media (max-width: 1180px) {
  .session-header { grid-template-columns: 40px minmax(180px, 1fr) minmax(180px, 260px) 124px; }
  .session-grid { grid-template-columns: 170px minmax(470px, 1fr) 210px; }
  .question-workspace { padding-inline: 24px; }
  .understanding-control > div { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .report-columns { grid-template-columns: minmax(0, 1fr) 300px; gap: 20px; }
  .report-hero { grid-template-columns: minmax(0, 1fr) 190px; }
  .report-side { position: static; }
}

@media (max-width: 760px) {
  .report-action-grid { grid-template-columns: 1fr; }
  .report-section-toggle-row { align-items: flex-start; flex-direction: column; }
  .text-button { width: 100%; justify-content: center; }
}
</style>
