<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  AlertCircle, ArrowRight, BarChart3, BookOpen, CalendarDays, Check, ChevronDown,
  Download, ExternalLink, FileQuestion, Filter, History, Loader2, MessageSquareText,
  MoreHorizontal, NotebookPen, Pin, PinOff, RefreshCw, RotateCcw, Save,
  Sparkles, Trash2, X,
} from '@lucide/vue'
import AnkiFlashcard from '../components/AnkiFlashcard.vue'
import SearchField from '../components/ui/SearchField.vue'
import AggregationStatus from '../components/AggregationStatus.vue'
import {
  appendWrongQuestionReflection, deleteWrongQuestion, evaluateQuizAnswer,
  generateFlashcard, generateSimilarQuiz, getWrongConcepts, getWrongQuestions,
  prepareWrongQuestionRedo, togglePinWrongQuestion, updateWrongQuestionNotes,
} from '../api'
import { decideM5Misconception, submitM5AssessmentAttempt } from '../api/m5'

const props = defineProps({ studentId: String })
const route = useRoute()
const router = useRouter()
const activeStudentId = computed(() => String(
  props.studentId || route.query.student_id
  || localStorage.getItem('edumatrix_student_id')
  || localStorage.getItem('edumatrix_username') || '',
))

const wrongQuestions = ref([])
const conceptStats = ref([])
const loading = ref(true)
const loadError = ref('')
const selectedId = ref(null)
const searchQuery = ref('')
const conceptFilter = ref('')
const sourceFilter = ref('all')
const statusFilter = ref('all')
const pinLoading = ref(false)
const deleteLoading = ref(false)
const noteEditing = ref(false)
const noteSaving = ref(false)
const noteDraft = ref('')
const reflectionLoading = ref(false)
const reflectionSaved = ref(false)
const diagnosisLoading = ref(false)
const diagnosisCategory = ref('')
const diagnosisNote = ref('')

const redoOpen = ref(false)
const redoPreparing = ref(false)
const redoResponse = ref(createRedoResponse())
const redoLoading = ref(false)
const redoError = ref('')
const redoResult = ref(null)
const redoKey = ref('')
const redoStartedAt = ref(0)

const flashcard = ref(null)
const flashcardLoading = ref(false)
const flashcardError = ref('')
const similarQuiz = ref(null)
const similarAnswer = ref('')
const similarConfidence = ref(5)
const similarLoading = ref(false)
const similarSubmitting = ref(false)
const similarResult = ref(null)
const similarError = ref('')

const misconceptionCategories = [
  { value: 'knowledge_gap', label: '知识缺口' },
  { value: 'concept_confusion', label: '概念混淆' },
  { value: 'strategy_error', label: '策略错误' },
  { value: 'calculation_error', label: '计算失误' },
  { value: 'careless', label: '粗心' },
  { value: 'programming_error', label: '编程错误' },
  { value: 'insufficient_evidence', label: '证据不足' },
]
const sourceOptions = [
  { value: 'all', label: '全部来源' },
  { value: 'quiz_resource', label: '测验题资源' },
  { value: 'formal_exam', label: '智能组卷' },
  { value: 'diagnostic', label: '入学诊断' },
  { value: 'retest', label: '延迟复测' },
]
const statusOptions = [
  { value: 'all', label: '全部状态' },
  { value: 'retest_due', label: '复测到期' },
  { value: 'needs_review', label: '需要巩固' },
  { value: 'mastered', label: '已经答对' },
]

const selectedQuestion = computed(() => wrongQuestions.value.find(item => item.id === selectedId.value) || null)
const filteredQuestions = computed(() => {
  const search = searchQuery.value.trim().toLowerCase()
  return wrongQuestions.value.filter((item) => {
    const sources = new Set((item.attempts || []).map(attempt => attempt.source?.type))
    const haystack = [item.concept_name, item.question?.prompt, item.quiz_detail?.question, item.notes]
      .filter(Boolean).join(' ').toLowerCase()
    return (!search || haystack.includes(search))
      && (!conceptFilter.value || item.concept_name === conceptFilter.value)
      && (sourceFilter.value === 'all' || sources.has(sourceFilter.value))
      && (statusFilter.value === 'all' || item.status === statusFilter.value)
  })
})
const summary = computed(() => ({
  total: wrongQuestions.value.length,
  due: wrongQuestions.value.filter(item => item.status === 'retest_due').length,
  mastered: wrongQuestions.value.filter(item => item.status === 'mastered').length,
  concepts: new Set(wrongQuestions.value.map(item => item.concept_name)).size,
}))
const filtersActive = computed(() => Boolean(
  searchQuery.value || conceptFilter.value || sourceFilter.value !== 'all' || statusFilter.value !== 'all',
))
const clusterRows = computed(() => {
  const groups = new Map()
  for (const item of wrongQuestions.value) {
    const key = item.current_diagnosis?.confirmed_category
      || item.current_diagnosis?.candidate_category || item.wrong_reason_category || 'unknown'
    groups.set(key, (groups.get(key) || 0) + 1)
  }
  const total = Math.max(1, wrongQuestions.value.length)
  return [...groups.entries()].map(([key, count]) => ({
    key, count, percent: Math.round(count / total * 100),
  })).sort((left, right) => right.count - left.count)
})

function message(error, fallback) {
  return error?.response?.data?.detail?.message
    || (typeof error?.response?.data?.detail === 'string' ? error.response.data.detail : '')
    || error?.message || fallback
}
function statusLabel(value) { return statusOptions.find(item => item.value === value)?.label || '需要巩固' }
function misconceptionLabel(value) { return misconceptionCategories.find(item => item.value === value)?.label || value || '未分类' }
function formatTime(value) {
  if (!value) return '时间未记录'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '时间未记录' : date.toLocaleString('zh-CN', {
    month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit',
  })
}
function answerText(value) {
  if (value === null || value === undefined || value === '') return '未记录'
  if (Array.isArray(value)) return value.join('、')
  if (typeof value !== 'object') return String(value)
  const direct = value.choice ?? value.value ?? value.text ?? value.answer ?? value.code
  if (direct !== undefined && direct !== '') return String(direct)
  const list = value.choices || value.blanks || value.answers
  return Array.isArray(list) ? list.join('、') : '已提交'
}
function optionKey(option, index) {
  const matched = String(option || '').trim().match(/^([A-Za-z])(?:[.、:：)）\s]|$)/)
  return matched ? matched[1].toUpperCase() : String.fromCharCode(65 + index)
}
function createRedoResponse(item = null) {
  const blankCount = Math.max(1, Number(item?.question?.response_spec?.blank_count || 1))
  return {
    choice: '',
    choices: [],
    value: null,
    blanks: Array.from({ length: blankCount }, () => ''),
    text: '',
    code: '',
  }
}
function resetRedoResponse(item = null) { redoResponse.value = createRedoResponse(item) }
function sourceLabels(item) { return [...new Set((item.attempts || []).map(attempt => attempt.mode_label).filter(Boolean))] }
function hasLegacyQuiz(item) { return Boolean(item?.quiz_record_id) }
function clearFilters() {
  searchQuery.value = ''
  conceptFilter.value = ''
  sourceFilter.value = 'all'
  statusFilter.value = 'all'
}
function resetDetailState(item) {
  noteEditing.value = false
  noteDraft.value = item?.notes || ''
  reflectionSaved.value = false
  diagnosisCategory.value = item?.current_diagnosis?.confirmed_category
    || item?.current_diagnosis?.candidate_category || 'insufficient_evidence'
  diagnosisNote.value = ''
  redoOpen.value = false
  redoPreparing.value = false
  resetRedoResponse(item)
  redoError.value = ''
  redoResult.value = null
  redoKey.value = ''
  flashcard.value = null
  flashcardError.value = ''
  similarQuiz.value = null
  similarAnswer.value = ''
  similarResult.value = null
  similarError.value = ''
}
async function syncSelectionQuery(id) {
  const query = { ...route.query }
  if (id) query.wrong_id = String(id)
  else delete query.wrong_id
  if (String(route.query.wrong_id || '') !== String(query.wrong_id || '')) await router.replace({ query })
}
function selectQuestion(item) {
  if (!item || selectedId.value === item.id) return
  selectedId.value = item.id
  resetDetailState(item)
  void syncSelectionQuery(item.id)
}
async function loadData({ preserveSelection = true } = {}) {
  loading.value = true
  loadError.value = ''
  const previousId = preserveSelection ? selectedId.value : null
  try {
    const [questions, stats] = await Promise.all([
      getWrongQuestions(activeStudentId.value), getWrongConcepts(activeStudentId.value),
    ])
    wrongQuestions.value = Array.isArray(questions) ? questions : []
    conceptStats.value = Array.isArray(stats) ? stats : []
    const requestedId = Number(route.query.wrong_id || previousId || 0)
    const selected = wrongQuestions.value.find(item => item.id === requestedId) || wrongQuestions.value[0] || null
    selectedId.value = selected?.id || null
    resetDetailState(selected)
    await syncSelectionQuery(selected?.id)
  } catch (error) {
    loadError.value = message(error, '错题本暂时无法加载，请保留当前页面后重试。')
  } finally { loading.value = false }
}
async function togglePin() {
  const item = selectedQuestion.value
  if (!item || pinLoading.value) return
  pinLoading.value = true
  try { await togglePinWrongQuestion(item.id, activeStudentId.value); await loadData() }
  catch (error) { loadError.value = message(error, '置顶状态保存失败，请重试。') }
  finally { pinLoading.value = false }
}
async function deleteQuestion() {
  const item = selectedQuestion.value
  if (!item || deleteLoading.value) return
  if (!window.confirm(`确认从错题本移除“${item.concept_name}”这条记录？历史测评证据不会被删除。`)) return
  deleteLoading.value = true
  try { await deleteWrongQuestion(item.id, activeStudentId.value); selectedId.value = null; await loadData({ preserveSelection: false }) }
  catch (error) { loadError.value = message(error, '错题记录移除失败，请重试。') }
  finally { deleteLoading.value = false }
}
function startNoteEdit() { noteDraft.value = selectedQuestion.value?.notes || ''; noteEditing.value = true }
async function saveNote() {
  const item = selectedQuestion.value
  if (!item || noteSaving.value) return
  noteSaving.value = true
  try { await updateWrongQuestionNotes(item.id, noteDraft.value, activeStudentId.value); item.notes = noteDraft.value; noteEditing.value = false }
  catch (error) { loadError.value = message(error, '笔记保存失败，当前输入已保留。') }
  finally { noteSaving.value = false }
}
async function appendReflection() {
  const item = selectedQuestion.value
  if (!item || !hasLegacyQuiz(item) || reflectionLoading.value) return
  reflectionLoading.value = true
  try {
    await appendWrongQuestionReflection({
      student_id: activeStudentId.value, concept: item.concept_name,
      quiz_record_id: item.quiz_record_id, wrong_reason: item.wrong_reason_category || 'misconception',
    })
    reflectionSaved.value = true
  } catch (error) { loadError.value = message(error, '错题反思未能写入笔记本，请重试。') }
  finally { reflectionLoading.value = false }
}
async function decideDiagnosis(decision) {
  const review = selectedQuestion.value?.current_diagnosis
  if (!review || review.status !== 'proposed' || diagnosisLoading.value) return
  diagnosisLoading.value = true
  try {
    await decideM5Misconception(review.id, {
      decision, category: decision === 'modify' ? diagnosisCategory.value : '', note: diagnosisNote.value,
    })
    await loadData()
  } catch (error) { loadError.value = message(error, '错因确认失败，当前选择已保留。') }
  finally { diagnosisLoading.value = false }
}
function beginRedo(item) {
  redoOpen.value = true
  redoError.value = ''
  redoResult.value = null
  resetRedoResponse(item)
  redoKey.value = `wrong-redo:${item.id}:${Date.now()}`
  redoStartedAt.value = Date.now()
}
async function openPrimaryAction() {
  const item = selectedQuestion.value
  if (!item || redoPreparing.value) return
  if (item.actions?.primary?.route) { void router.push(item.actions.primary.route); return }
  redoOpen.value = true
  redoError.value = ''
  redoResult.value = null
  if (item.question_version_id && item.question) { beginRedo(item); return }
  redoPreparing.value = true
  try {
    const prepared = await prepareWrongQuestionRedo(item.id, activeStudentId.value)
    item.id = prepared.wrong_question_id
    item.question_version_id = prepared.question_version_id
    item.question = prepared.question
    selectedId.value = prepared.wrong_question_id
    beginRedo(item)
  } catch (error) {
    redoError.value = message(error, '重做题目准备失败，请重试。')
  } finally {
    redoPreparing.value = false
  }
}
function toggleRedoChoice(key) {
  const values = new Set(redoResponse.value.choices)
  if (values.has(key)) values.delete(key); else values.add(key)
  redoResponse.value.choices = [...values]
}
function redoPayload(item) {
  const type = item.question?.type
  if (type === 'single_choice') return { choice: redoResponse.value.choice }
  if (type === 'multiple_choice') return { choices: redoResponse.value.choices }
  if (type === 'true_false') return { value: redoResponse.value.value }
  if (type === 'fill_blank') return { blanks: redoResponse.value.blanks.map(value => value.trim()) }
  if (type === 'code') return { code: redoResponse.value.code }
  return { text: redoResponse.value.text.trim() }
}
function redoReady(item) {
  if (!item?.question_version_id) return false
  const type = item.question?.type
  if (type === 'single_choice') return Boolean(redoResponse.value.choice)
  if (type === 'multiple_choice') return redoResponse.value.choices.length > 0
  if (type === 'true_false') return redoResponse.value.value !== null
  if (type === 'fill_blank') return redoResponse.value.blanks.length > 0 && redoResponse.value.blanks.every(value => value.trim())
  if (type === 'code') return Boolean(redoResponse.value.code.trim())
  return Boolean(redoResponse.value.text.trim())
}
async function submitRedo() {
  const item = selectedQuestion.value
  if (!item || !redoReady(item) || redoLoading.value) return
  redoLoading.value = true
  redoError.value = ''
  try {
    const response = await submitM5AssessmentAttempt({
      question_version_id: item.question_version_id, idempotency_key: redoKey.value,
      mode: 'practice', answer: redoPayload(item), confidence: 0.7,
      duration_seconds: Math.max(0, Math.round((Date.now() - redoStartedAt.value) / 1000)),
    })
    const submittedResult = response.attempt || response
    await loadData()
    redoOpen.value = true
    redoResult.value = submittedResult
  } catch (error) { redoError.value = message(error, '本次提交没有完成，答案已保留，可直接重试。') }
  finally { redoLoading.value = false }
}
async function loadFlashcard() {
  const item = selectedQuestion.value
  if (!item || !hasLegacyQuiz(item) || flashcardLoading.value) return
  flashcardLoading.value = true
  flashcardError.value = ''
  try { flashcard.value = (await generateFlashcard(activeStudentId.value, item.quiz_record_id)).flashcard }
  catch (error) { flashcardError.value = message(error, '闪卡生成失败，请稍后重试。') }
  finally { flashcardLoading.value = false }
}
async function startSimilarChallenge() {
  const item = selectedQuestion.value
  if (!item || !hasLegacyQuiz(item) || similarLoading.value) return
  similarLoading.value = true
  similarError.value = ''
  similarResult.value = null
  similarAnswer.value = ''
  try { similarQuiz.value = await generateSimilarQuiz(activeStudentId.value, item.quiz_record_id, item.concept_name) }
  catch (error) { similarError.value = message(error, '相似题生成失败，请稍后重试。') }
  finally { similarLoading.value = false }
}
async function submitSimilar() {
  const item = selectedQuestion.value
  if (!item || !similarQuiz.value || !similarAnswer.value.trim() || similarSubmitting.value) return
  similarSubmitting.value = true
  similarError.value = ''
  try {
    const submittedResult = await evaluateQuizAnswer(
      similarQuiz.value.quiz_id, activeStudentId.value, similarAnswer.value,
      similarConfidence.value / 10, 1, item.quiz_record_id,
    )
    const submittedQuiz = similarQuiz.value
    const submittedAnswer = similarAnswer.value
    await loadData()
    similarQuiz.value = submittedQuiz
    similarAnswer.value = submittedAnswer
    similarResult.value = submittedResult
  } catch (error) { similarError.value = message(error, '相似题提交失败，答案已保留。') }
  finally { similarSubmitting.value = false }
}
function openRoute(target) { if (target) void router.push(target) }
function exportSelected() {
  const item = selectedQuestion.value
  if (!item) return
  const lines = [
    `# ${item.concept_name} · 错题复盘`, '', `- 状态：${statusLabel(item.status)}`,
    `- 规范题目版本：${item.question_version_id || '未记录'}`, `- 作答次数：${item.attempt_count || 0}`,
    '', '## 题目', item.question?.prompt || item.quiz_detail?.question || '题目内容暂不可用',
    '', '## 我的笔记', item.notes || '暂无笔记', '', '## 作答历史',
    ...(item.attempts || []).map((attempt, index) => (
      `${index + 1}. ${attempt.mode_label} · ${formatTime(attempt.submitted_at)} · `
      + `${attempt.feedback_released ? (attempt.correct ? '正确' : '错误') : '反馈未开放'} · 答案 ${answerText(attempt.answer)}`
    )), '', '## 来源', ...(item.source_refs || []).map(source => `- ${source.title} · ${source.location}`),
  ]
  const blob = new Blob([lines.join('\n')], { type: 'text/markdown;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = `${item.concept_name || '错题复盘'}.md`
  link.click()
  URL.revokeObjectURL(url)
}

onMounted(() => loadData({ preserveSelection: false }))
watch(activeStudentId, (next, previous) => { if (next && next !== previous) loadData({ preserveSelection: false }) })
watch(filteredQuestions, (rows) => {
  if (rows.length && !rows.some(item => item.id === selectedId.value)) selectQuestion(rows[0])
})
</script>

<template>
  <div class="wrong-workspace" data-testid="wrong-question-workspace">
    <header class="page-heading">
      <div><p class="page-kicker">复习中心</p><h1>错题本</h1><p>把测验题与智能组卷中的同一道题归为一条历史，先看清错误，再完成重做或复测。</p></div>
      <div class="summary-strip" aria-label="错题摘要">
        <span><strong>{{ summary.total }}</strong><small>错题</small></span>
        <span><strong>{{ summary.due }}</strong><small>复测到期</small></span>
        <span><strong>{{ summary.concepts }}</strong><small>知识点</small></span>
      </div>
    </header>

    <AggregationStatus :course-id="String(route.query.course_id || '')" />

    <div v-if="loadError" class="recovery-banner" role="alert" data-testid="wrong-question-error">
      <AlertCircle :size="18" /><span><strong>当前数据未完全更新</strong><small>{{ loadError }}</small></span>
      <button type="button" @click="loadData()"><RefreshCw :size="15" />重试</button>
    </div>

    <section class="filter-bar" aria-label="错题筛选" data-testid="wrong-question-filters">
      <SearchField v-model="searchQuery" class="wrong-question-search" aria-label="搜索知识点、题目或笔记" placeholder="搜索知识点、题目或笔记" />
      <label><span>知识点</span><select v-model="conceptFilter"><option value="">全部知识点</option><option v-for="stat in conceptStats" :key="stat.concept" :value="stat.concept">{{ stat.concept }}（{{ stat.count }}）</option></select></label>
      <label><span>来源</span><select v-model="sourceFilter"><option v-for="option in sourceOptions" :key="option.value" :value="option.value">{{ option.label }}</option></select></label>
      <label><span>状态</span><select v-model="statusFilter"><option v-for="option in statusOptions" :key="option.value" :value="option.value">{{ option.label }}</option></select></label>
      <button v-if="filtersActive" type="button" class="icon-button" title="清除筛选" aria-label="清除筛选" @click="clearFilters"><X :size="17" /></button>
    </section>

    <main class="wrong-grid">
      <aside class="question-list" data-testid="wrong-question-list">
        <header><strong>错题列表</strong><span>{{ filteredQuestions.length }} 条</span></header>
        <div v-if="loading" class="list-loading" aria-label="错题加载中"><span v-for="index in 5" :key="index"></span></div>
        <div v-else-if="!wrongQuestions.length" class="list-empty" data-testid="wrong-question-empty">
          <FileQuestion :size="25" /><strong>还没有错题记录</strong><p>完成测验题资源或智能组卷后，错误题目会自动归入这里。</p>
          <button type="button" @click="router.push('/workspace/resources?type=quiz')">前往测验题资源</button>
        </div>
        <div v-else-if="!filteredQuestions.length" class="list-empty" data-testid="wrong-question-filter-empty">
          <Filter :size="23" /><strong>没有符合条件的错题</strong><p>调整筛选条件后，现有错题仍会保留。</p><button type="button" @click="clearFilters">清除筛选</button>
        </div>
        <ol v-else><li v-for="item in filteredQuestions" :key="item.id">
          <button type="button" class="question-row" :class="{ selected: selectedId === item.id }" :aria-current="selectedId === item.id ? 'true' : undefined" data-testid="wrong-question-list-item" @click="selectQuestion(item)">
            <span class="row-heading"><strong>{{ item.concept_name }}</strong><Pin v-if="item.pinned" :size="14" aria-label="已置顶" /><small :class="`status-${item.status}`">{{ statusLabel(item.status) }}</small></span>
            <span class="row-question">{{ item.question?.prompt || item.quiz_detail?.question || '题目内容暂不可用' }}</span>
            <span class="row-meta"><small>{{ item.attempt_count || 0 }} 次作答</small><small v-for="label in sourceLabels(item).slice(0, 2)" :key="label">{{ label }}</small><ArrowRight :size="15" /></span>
          </button>
        </li></ol>
      </aside>

      <section class="detail-pane" data-testid="wrong-question-detail">
        <div v-if="loading && !selectedQuestion" class="detail-loading" aria-label="详情加载中"><span></span><span></span><span></span><span></span></div>
        <div v-else-if="!selectedQuestion" class="detail-empty"><BookOpen :size="30" /><strong>选择一条错题开始复盘</strong><p>右侧会保留题目、来源、作答历史和下一步。</p></div>
        <template v-else>
          <header class="detail-heading">
            <div><span class="detail-tags"><small :class="`status-${selectedQuestion.status}`">{{ statusLabel(selectedQuestion.status) }}</small><small v-for="label in sourceLabels(selectedQuestion)" :key="label">{{ label }}</small></span><h2>{{ selectedQuestion.concept_name }}</h2><p>{{ selectedQuestion.question?.prompt || selectedQuestion.quiz_detail?.question || '题目内容暂不可用' }}</p></div>
            <div class="detail-actions">
              <button type="button" class="icon-button" :title="selectedQuestion.pinned ? '取消置顶' : '置顶'" :aria-label="selectedQuestion.pinned ? '取消置顶' : '置顶'" :disabled="pinLoading" @click="togglePin"><Loader2 v-if="pinLoading" :size="17" class="spin" /><PinOff v-else-if="selectedQuestion.pinned" :size="17" /><Pin v-else :size="17" /></button>
              <button type="button" class="icon-button" title="导出当前错题复盘" aria-label="导出当前错题复盘" @click="exportSelected"><Download :size="17" /></button>
              <button v-if="selectedQuestion.actions?.chat?.route" type="button" class="secondary-action" @click="openRoute(selectedQuestion.actions.chat.route)"><MessageSquareText :size="17" />问学习伙伴</button>
              <button type="button" class="primary-action" data-testid="wrong-question-primary-action" :disabled="redoPreparing" @click="openPrimaryAction"><Loader2 v-if="redoPreparing" :size="17" class="spin" /><RotateCcw v-else :size="17" />{{ redoPreparing ? '准备重做' : selectedQuestion.actions?.primary?.label || '重做这道题' }}</button>
            </div>
          </header>

          <section class="answer-overview" aria-label="答案与解析">
            <div><span>最近一次答案</span><strong>{{ answerText(selectedQuestion.attempts?.[0]?.answer || selectedQuestion.quiz_detail?.student_answer) }}</strong></div>
            <div><span>参考答案</span><strong v-if="selectedQuestion.question?.answer_available !== false">{{ answerText(selectedQuestion.question?.correct_answer || selectedQuestion.quiz_detail?.correct_answer) }}</strong><strong v-else>反馈尚未开放</strong></div>
            <article><span>解析</span><p v-if="selectedQuestion.question?.answer_available !== false">{{ selectedQuestion.question?.explanation || selectedQuestion.quiz_detail?.feedback || '当前题目没有单独解析。' }}</p><p v-else>{{ selectedQuestion.question?.answer_unavailable_reason }}</p></article>
          </section>

          <section v-if="redoOpen" class="redo-panel" aria-label="重做当前题目" data-testid="wrong-question-redo">
            <header><div><strong>重做当前题目</strong><span>提交并判分后，系统才会记录这次作答。</span></div><button type="button" class="icon-button" title="收起重做区" aria-label="收起重做区" @click="redoOpen = false"><X :size="17" /></button></header>
            <div v-if="redoPreparing" class="redo-preparing" data-testid="wrong-question-redo-prepare"><Loader2 :size="19" class="spin" /><span>正在恢复这道旧错题的规范题目版本，不会新增作答或计分。</span></div>
            <div v-else-if="!selectedQuestion.question_version_id" class="redo-prepare-error">
              <p v-if="redoError" class="inline-error"><AlertCircle :size="16" />{{ redoError }}</p>
              <button type="button" data-testid="wrong-question-redo-prepare" @click="openPrimaryAction"><RefreshCw :size="16" />重新准备题目</button>
            </div>
            <template v-else>
              <div v-if="selectedQuestion.question.type === 'single_choice'" class="redo-options">
                <label v-for="(option, index) in selectedQuestion.question.options" :key="option">
                  <input v-model="redoResponse.choice" type="radio" name="wrong-redo-answer" :value="optionKey(option, index)" />
                  <b>{{ optionKey(option, index) }}</b><span>{{ option }}</span>
                </label>
              </div>
              <div v-else-if="selectedQuestion.question.type === 'multiple_choice'" class="redo-options">
                <label v-for="(option, index) in selectedQuestion.question.options" :key="option">
                  <input type="checkbox" :checked="redoResponse.choices.includes(optionKey(option, index))" @change="toggleRedoChoice(optionKey(option, index))" />
                  <b>{{ optionKey(option, index) }}</b><span>{{ option }}</span>
                </label>
              </div>
              <div v-else-if="selectedQuestion.question.type === 'true_false'" class="redo-boolean" role="group" aria-label="选择判断答案">
                <button type="button" :class="{ selected: redoResponse.value === true }" @click="redoResponse.value = true">正确</button>
                <button type="button" :class="{ selected: redoResponse.value === false }" @click="redoResponse.value = false">错误</button>
              </div>
              <div v-else-if="selectedQuestion.question.type === 'fill_blank'" class="redo-blanks">
                <label v-for="(_, index) in redoResponse.blanks" :key="index"><span>空 {{ index + 1 }}</span><input v-model="redoResponse.blanks[index]" type="text" /></label>
              </div>
              <div v-else-if="selectedQuestion.question.type === 'code'" class="redo-code">
                <span>Python · {{ selectedQuestion.question.response_spec?.hidden_test_count || 0 }} 个隐藏测试</span>
                <textarea v-model="redoResponse.code" rows="10" spellcheck="false" placeholder="def solution(...):"></textarea>
              </div>
              <textarea v-else v-model="redoResponse.text" rows="5" :placeholder="selectedQuestion.question.type === 'open_task' ? '提交你的方案、证据与结论' : '输入你的回答'"></textarea>
              <p v-if="redoError" class="inline-error"><AlertCircle :size="16" />{{ redoError }}</p>
              <p v-if="redoResult" class="inline-result" :class="{ correct: redoResult.correct === true }"><Check v-if="redoResult.correct" :size="16" /><AlertCircle v-else :size="16" />{{ redoResult.correct === true ? '回答正确，这次练习已经记录。' : redoResult.correct === false ? '本次仍需巩固，作答历史已保留。' : '作答已保存，智能初评暂未完成，可稍后重新提交。' }}</p>
              <p v-if="redoResult?.grading?.feedback" class="redo-feedback">{{ redoResult.grading.feedback }}</p>
              <footer><span>失败重试会复用本次提交标识，不会重复计分。</span><button type="button" data-testid="wrong-question-redo-submit" :disabled="redoLoading || !redoReady(selectedQuestion)" @click="submitRedo"><Loader2 v-if="redoLoading" :size="16" class="spin" />{{ redoLoading ? '判分中' : '提交并判分' }}</button></footer>
            </template>
          </section>

          <details class="detail-section" open data-testid="wrong-question-attempt-history">
            <summary><span><History :size="18" /><strong>作答历史</strong></span><small>{{ selectedQuestion.attempt_count || 0 }} 次提交</small><ChevronDown :size="17" /></summary>
            <div class="section-body"><p v-if="!selectedQuestion.attempts?.length" class="section-empty">规范作答历史尚未建立，旧题目内容仍然保留。</p>
              <ol v-else class="attempt-list"><li v-for="(attempt, index) in selectedQuestion.attempts" :key="attempt.id">
                <span class="attempt-index">{{ selectedQuestion.attempts.length - index }}</span><span><strong>{{ attempt.mode_label }}</strong><small>{{ formatTime(attempt.submitted_at) }}</small></span><span><strong>答案 {{ answerText(attempt.answer) }}</strong><small>用时 {{ attempt.duration_seconds ?? '未记录' }} 秒</small></span><span><strong v-if="attempt.feedback_released" :class="attempt.correct ? 'result-correct' : 'result-wrong'">{{ attempt.correct ? '回答正确' : '回答错误' }}</strong><strong v-else>反馈未开放</strong><small v-if="attempt.score !== null && attempt.score !== undefined">得分 {{ Math.round(attempt.score * 100) }}%</small></span><button type="button" :disabled="!attempt.source?.route" @click="openRoute(attempt.source?.route)">查看原题<ExternalLink :size="14" /></button>
              </li></ol>
            </div>
          </details>

          <details class="detail-section" open data-testid="wrong-question-diagnosis">
            <summary><span><Sparkles :size="18" /><strong>错因与复测</strong></span><small>{{ selectedQuestion.current_diagnosis ? '已有诊断' : '等待形成诊断' }}</small><ChevronDown :size="17" /></summary>
            <div class="section-body diagnosis-body">
              <div v-if="selectedQuestion.current_diagnosis" class="diagnosis-summary"><span><strong>{{ misconceptionLabel(selectedQuestion.current_diagnosis.confirmed_category || selectedQuestion.current_diagnosis.candidate_category) }}</strong><small>{{ selectedQuestion.current_diagnosis.status === 'proposed' ? '待你确认' : '已记录你的决定' }}</small></span><p>{{ selectedQuestion.current_diagnosis.candidate_rationale || '系统只提出候选错因，最终分类由你确认。' }}</p></div>
              <p v-else class="section-empty">完成一次有判分结果的重做后，系统会给出可确认的错因候选。</p>
              <div v-if="selectedQuestion.current_diagnosis?.status === 'proposed'" class="diagnosis-form"><label><span>你的判断</span><select v-model="diagnosisCategory"><option v-for="category in misconceptionCategories" :key="category.value" :value="category.value">{{ category.label }}</option></select></label><label><span>补充说明（可选）</span><input v-model="diagnosisNote" type="text" placeholder="例如：我混淆了梯度与更新方向" /></label><div><button type="button" :disabled="diagnosisLoading" @click="decideDiagnosis('accept')">接受候选</button><button type="button" :disabled="diagnosisLoading" @click="decideDiagnosis('modify')">按我的分类记录</button><button type="button" :disabled="diagnosisLoading" @click="decideDiagnosis('reject')">暂不采用</button></div></div>
              <div class="retest-row"><CalendarDays :size="18" /><span v-if="selectedQuestion.retest_task"><strong>{{ selectedQuestion.retest_task.status === 'completed' ? '延迟复测已完成' : selectedQuestion.retest_task.status === 'due' ? '延迟复测已到期' : '延迟复测已排程' }}</strong><small>{{ selectedQuestion.retest_task.due_at ? `计划时间 ${formatTime(selectedQuestion.retest_task.due_at)}` : '等待复测安排' }}</small></span><span v-else><strong>尚未安排延迟复测</strong><small>确认错因后，系统会按现有复习规则安排。</small></span><button v-if="selectedQuestion.retest_task" type="button" @click="openRoute(`/workspace/review/calendar?retest_id=${selectedQuestion.retest_task.id}`)">打开复习日历<ArrowRight :size="14" /></button></div>
            </div>
          </details>

          <details class="detail-section" data-testid="wrong-question-sources">
            <summary><span><BookOpen :size="18" /><strong>来源与关联学习</strong></span><small>{{ selectedQuestion.source_refs?.length || 0 }} 个来源 · {{ selectedQuestion.related_resources?.length || 0 }} 项资源</small><ChevronDown :size="17" /></summary>
            <div class="section-body source-body">
              <section><h3>参考材料</h3><p v-if="!selectedQuestion.source_refs?.length" class="section-empty">这条旧题尚未关联可打开的参考材料。</p><button v-for="source in selectedQuestion.source_refs" :key="source.id" type="button" class="link-row" :disabled="!source.route" @click="openRoute(source.route)"><span><strong>{{ source.title }}</strong><small>{{ source.available ? source.location : '材料已撤回或位置缺失' }}</small></span><ExternalLink v-if="source.route" :size="15" /><AlertCircle v-else :size="15" /></button></section>
              <section data-testid="wrong-question-related-resources"><h3>关联资源</h3><p v-if="!selectedQuestion.related_resources?.length" class="section-empty">当前知识点还没有可直接打开的关联资源。</p><button v-for="resource in selectedQuestion.related_resources" :key="`${resource.type}:${resource.resource_id}`" type="button" class="link-row" @click="openRoute(resource.route)"><span><strong>{{ resource.title }}</strong><small>{{ resource.type }} · {{ resource.status }}</small></span><ArrowRight :size="15" /></button></section>
              <section><h3>复习与测评</h3><button v-if="selectedQuestion.review_plan" type="button" class="link-row" @click="openRoute(selectedQuestion.review_plan.route)"><span><strong>复习计划</strong><small>{{ selectedQuestion.review_plan.next_review_at ? formatTime(selectedQuestion.review_plan.next_review_at) : '当前已到期' }}</small></span><ArrowRight :size="15" /></button><button v-for="exam in selectedQuestion.formal_exam_links" :key="exam.sitting_id" type="button" class="link-row" @click="openRoute(exam.route)"><span><strong>智能组卷记录</strong><small>{{ exam.report_id ? '报告可查看' : '报告尚未生成' }}</small></span><ArrowRight :size="15" /></button><p v-if="!selectedQuestion.review_plan && !selectedQuestion.formal_exam_links?.length" class="section-empty">暂无关联复习计划或正式组卷记录。</p></section>
            </div>
          </details>

          <details class="detail-section" data-testid="wrong-question-notes">
            <summary><span><NotebookPen :size="18" /><strong>笔记与反思</strong></span><small>{{ selectedQuestion.notes ? '已有个人笔记' : '尚未记录' }}</small><ChevronDown :size="17" /></summary>
            <div class="section-body notes-body">
              <template v-if="noteEditing"><textarea v-model="noteDraft" rows="5" placeholder="记录易错点、解题思路或下一次检查方法"></textarea><div class="notes-actions"><button type="button" @click="noteEditing = false">取消</button><button type="button" :disabled="noteSaving" @click="saveNote"><Loader2 v-if="noteSaving" :size="15" class="spin" /><Save v-else :size="15" />保存笔记</button></div></template>
              <template v-else><p>{{ selectedQuestion.notes || '暂无笔记。写下你为什么会错，以及下一次准备怎样检查。' }}</p><button type="button" @click="startNoteEdit"><NotebookPen :size="15" />{{ selectedQuestion.notes ? '编辑笔记' : '添加笔记' }}</button></template>
              <div class="reflection-row"><span><strong>沉淀到笔记本</strong><small>{{ hasLegacyQuiz(selectedQuestion) ? '把原题、解析和错因追加为可继续编辑的反思。' : '这条规范题暂未关联旧笔记写入协议。' }}</small></span><button type="button" :disabled="!hasLegacyQuiz(selectedQuestion) || reflectionLoading || reflectionSaved" @click="appendReflection"><Loader2 v-if="reflectionLoading" :size="15" class="spin" /><Check v-else-if="reflectionSaved" :size="15" /><NotebookPen v-else :size="15" />{{ reflectionSaved ? '已写入笔记本' : '写入笔记本' }}</button></div>
            </div>
          </details>

          <details class="detail-section" data-testid="wrong-question-deep-practice">
            <summary><span><MoreHorizontal :size="18" /><strong>更多巩固方式</strong></span><small>闪卡与相似题</small><ChevronDown :size="17" /></summary>
            <div class="section-body practice-grid">
              <section data-testid="wrong-question-flashcard"><h3>主动召回闪卡</h3><p>先尝试回忆关键概念，再翻面检查答案。</p><div v-if="flashcardLoading" class="practice-loading"><Loader2 :size="20" class="spin" />正在准备闪卡</div><AnkiFlashcard v-else-if="flashcard" :card="flashcard" :student-id="activeStudentId" @reviewed="result => { if (result?.flashcard) flashcard = result.flashcard }" /><p v-if="flashcardError" class="inline-error"><AlertCircle :size="15" />{{ flashcardError }}</p><button v-if="!flashcard" type="button" :disabled="!hasLegacyQuiz(selectedQuestion) || flashcardLoading" @click="loadFlashcard">生成闪卡</button><small v-if="!hasLegacyQuiz(selectedQuestion)">当前规范题没有可用于旧闪卡协议的测验记录。</small></section>
              <section data-testid="wrong-question-similar"><h3>相似题挑战</h3><p>换一个题面检查是否真正理解，而不是记住答案。</p><div v-if="similarLoading" class="practice-loading"><Loader2 :size="20" class="spin" />正在生成相似题</div><template v-else-if="similarQuiz"><strong class="similar-question">{{ similarQuiz.question }}</strong><label v-for="(option, index) in similarQuiz.options || []" :key="option" class="similar-option"><input v-model="similarAnswer" type="radio" name="similar-answer" :value="optionKey(option, index)" /><span>{{ option }}</span></label><textarea v-if="!similarQuiz.options?.length" v-model="similarAnswer" rows="3" placeholder="输入你的答案"></textarea><label class="confidence-field"><span>作答信心 {{ similarConfidence }}/10</span><input v-model.number="similarConfidence" type="range" min="1" max="10" /></label><button type="button" :disabled="similarSubmitting || !similarAnswer.trim()" @click="submitSimilar"><Loader2 v-if="similarSubmitting" :size="15" class="spin" />提交相似题</button><div v-if="similarResult" class="similar-result" :class="{ correct: similarResult.accuracy_score >= 0.7 }" data-testid="wrong-question-similar-result"><strong>{{ similarResult.accuracy_score >= 0.7 ? '本次回答正确' : '本次仍需巩固' }} · 得分 {{ Math.round(Number(similarResult.accuracy_score || 0) * 100) }}%</strong><p>{{ similarResult.feedback || '作答结果已保存。' }}</p><p v-if="similarQuiz.correct_answer"><b>正确答案：</b>{{ similarQuiz.correct_answer }}</p><p v-if="similarQuiz.explanation"><b>解析：</b>{{ similarQuiz.explanation }}</p></div></template><button v-else type="button" :disabled="!hasLegacyQuiz(selectedQuestion)" @click="startSimilarChallenge">生成相似题</button><p v-if="similarError" class="inline-error"><AlertCircle :size="15" />{{ similarError }}</p><small v-if="!hasLegacyQuiz(selectedQuestion)">当前规范题可直接重做，但暂不能调用旧相似题生成协议。</small></section>
            </div>
          </details>

          <details class="detail-section" data-testid="wrong-question-analytics">
            <summary><span><BarChart3 :size="18" /><strong>错因统计</strong></span><small>{{ summary.concepts }} 个知识点</small><ChevronDown :size="17" /></summary>
            <div class="section-body analytics-body"><div class="analytics-summary"><span><strong>{{ summary.total }}</strong><small>错题</small></span><span><strong>{{ summary.due }}</strong><small>复测到期</small></span><span><strong>{{ summary.mastered }}</strong><small>已经答对</small></span></div><div class="cluster-list"><div v-for="row in clusterRows" :key="row.key"><span>{{ misconceptionLabel(row.key) }}</span><i><b :style="{ width: `${row.percent}%` }"></b></i><strong>{{ row.count }}</strong></div></div></div>
          </details>

          <details class="detail-section maintenance-section"><summary><span><MoreHorizontal :size="18" /><strong>记录管理</strong></span><small>低频操作</small><ChevronDown :size="17" /></summary><div class="section-body maintenance-body"><span><strong>从错题本移除</strong><small>只移除当前聚合记录，原始作答与测评证据不会被删除。</small></span><button type="button" :disabled="deleteLoading" @click="deleteQuestion"><Loader2 v-if="deleteLoading" :size="15" class="spin" /><Trash2 v-else :size="15" />移除记录</button></div></details>
        </template>
      </section>
    </main>
  </div>
</template>

<style scoped>
.wrong-workspace{width:min(100%,1540px);margin:0 auto;color:var(--color-text,#06141b);font-family:var(--font-sans)}
.page-heading{display:flex;min-height:112px;align-items:flex-end;justify-content:space-between;gap:28px;padding:8px 2px 20px;border-bottom:1px solid var(--color-border,#dce1e2)}
.page-kicker{margin:0 0 7px;color:var(--color-text-muted,#60727c);font-size:14px;font-weight:700}.page-heading h1{margin:0;font-size:30px;line-height:1.25}.page-heading>div>p:last-child{max-width:760px;margin:8px 0 0;color:var(--color-text-secondary,#4a5c6a);font-size:14px;line-height:1.65}
.summary-strip{display:flex;min-width:300px;align-items:center;border:1px solid var(--color-border,#dce1e2);border-radius:7px;background:var(--color-surface,#fff)}.summary-strip span{display:grid;min-width:100px;gap:2px;padding:12px 16px}.summary-strip span+span{border-left:1px solid var(--color-border,#dce1e2)}.summary-strip strong{font-size:20px;font-variant-numeric:tabular-nums}.summary-strip small{color:var(--color-text-muted,#60727c);font-size:14px}
.recovery-banner{display:grid;grid-template-columns:20px minmax(0,1fr) auto;align-items:center;gap:12px;margin-top:14px;border:1px solid #c99a95;border-radius:6px;background:#fff8f7;padding:12px 14px;color:#842b24}.recovery-banner span{display:grid;gap:3px}.recovery-banner strong,.recovery-banner small{font-size:14px}
.recovery-banner button,.secondary-action,.filter-bar button,.section-body button,.redo-panel button{display:inline-flex;min-height:38px;align-items:center;justify-content:center;gap:7px;border:1px solid var(--color-border-strong,#9ba8ab);border-radius:5px;background:var(--color-surface,#fff);padding:8px 11px;color:var(--color-text,#06141b);font-size:14px;font-weight:700;cursor:pointer}
.filter-bar{display:grid;grid-template-columns:minmax(280px,1fr) repeat(3,minmax(150px,190px)) 40px;gap:10px;align-items:end;padding:16px 0}.filter-bar label{display:grid;gap:6px}.filter-bar label>span{color:var(--color-text-muted,#60727c);font-size:14px;font-weight:700}.filter-bar input,.filter-bar select,.diagnosis-form input,.diagnosis-form select,.redo-panel textarea,.redo-blanks input,.notes-body textarea,.practice-grid textarea{width:100%;box-sizing:border-box;min-height:40px;border:1px solid var(--color-border-strong,#9ba8ab);border-radius:5px;background:var(--color-surface,#fff);padding:8px 10px;color:var(--color-text,#06141b);font-family:inherit;font-size:14px}.search-field{position:relative}.search-field svg{position:absolute;z-index:1;bottom:11px;left:11px;color:var(--color-text-muted,#60727c)}.search-field input{padding-left:38px}
.icon-button{display:inline-grid!important;width:40px;min-width:40px;height:40px;min-height:40px!important;place-items:center;border:1px solid var(--color-border-strong,#9ba8ab)!important;border-radius:5px!important;background:var(--color-surface,#fff)!important;padding:0!important;color:var(--color-text,#06141b)!important;cursor:pointer}
.wrong-grid{display:grid;min-height:640px;grid-template-columns:360px minmax(0,1fr);overflow:hidden;border:1px solid var(--color-border-strong,#9ba8ab);border-radius:8px;background:var(--color-surface,#fff)}.question-list{min-width:0;border-right:1px solid var(--color-border,#dce1e2);background:var(--color-surface-subtle,#f5f7f7)}.question-list>header{display:flex;min-height:48px;align-items:center;justify-content:space-between;padding:0 14px;border-bottom:1px solid var(--color-border,#dce1e2);background:var(--color-surface,#fff)}.question-list>header strong,.question-list>header span{font-size:14px}.question-list>header span{color:var(--color-text-muted,#60727c)}.question-list ol{margin:0;padding:0;list-style:none}.question-list li+li{border-top:1px solid var(--color-border,#dce1e2)}
.question-row{display:grid;width:100%;min-height:132px;gap:9px;border:0;border-left:3px solid transparent;background:transparent;padding:15px 14px 14px 12px;color:var(--color-text,#06141b);text-align:left;cursor:pointer}.question-row:hover{background:#eef2f3}.question-row.selected{border-left-color:#11212d;background:var(--color-surface,#fff)}.row-heading,.row-meta{display:flex;align-items:center;gap:8px}.row-heading strong{min-width:0;flex:1;overflow:hidden;font-size:15px;text-overflow:ellipsis;white-space:nowrap}.row-heading small,.detail-tags small{border:1px solid var(--color-border,#dce1e2);border-radius:999px;padding:3px 7px;background:var(--color-surface,#fff);color:var(--color-text-secondary,#4a5c6a);font-size:14px}.status-retest_due{border-color:#c99a95!important;background:#fff8f7!important;color:#842b24!important}.status-mastered{border-color:#a9b8c1!important;background:#eef2f3!important;color:#11212d!important}.row-question{display:-webkit-box;overflow:hidden;color:var(--color-text-secondary,#4a5c6a);font-size:14px;line-height:1.55;-webkit-box-orient:vertical;-webkit-line-clamp:2}.row-meta{color:var(--color-text-muted,#60727c)}.row-meta small{font-size:14px}.row-meta svg{margin-left:auto}
.list-loading{display:grid;gap:1px}.list-loading span{display:block;height:132px;background:var(--color-surface-subtle,#f5f7f7);animation:pulse 1.4s ease-in-out infinite}.list-empty,.detail-empty{display:grid;place-items:center;align-content:center;gap:10px;min-height:420px;padding:28px;text-align:center}.list-empty strong,.detail-empty strong{font-size:16px}.list-empty p,.detail-empty p{max-width:300px;margin:0;color:var(--color-text-muted,#60727c);font-size:14px;line-height:1.6}
.detail-pane{min-width:0;padding:0 24px 28px}.detail-heading{display:flex;min-height:164px;align-items:flex-start;justify-content:space-between;gap:24px;padding:24px 0 20px;border-bottom:1px solid var(--color-border-strong,#9ba8ab)}.detail-heading>div:first-child{min-width:0;flex:1}.detail-tags{display:flex;flex-wrap:wrap;gap:6px}.detail-heading h2{margin:13px 0 7px;font-size:22px;line-height:1.3}.detail-heading p{max-width:820px;margin:0;color:var(--color-text-secondary,#4a5c6a);font-size:15px;line-height:1.7}.detail-actions{display:flex;flex-wrap:wrap;justify-content:flex-end;gap:8px}.primary-action{display:inline-flex;min-height:40px;align-items:center;justify-content:center;gap:7px;border:1px solid #11212d;border-radius:5px;background:#11212d;padding:8px 14px;color:#fff;font-size:14px;font-weight:700;white-space:nowrap;cursor:pointer}
.answer-overview{display:grid;grid-template-columns:minmax(180px,.7fr) minmax(180px,.7fr) minmax(320px,1.6fr);border-bottom:1px solid var(--color-border,#dce1e2)}.answer-overview>div,.answer-overview>article{display:grid;align-content:start;gap:6px;min-height:104px;padding:18px 16px}.answer-overview>*+*{border-left:1px solid var(--color-border,#dce1e2)}.answer-overview span{color:var(--color-text-muted,#60727c);font-size:14px;font-weight:700}.answer-overview strong{font-size:16px;line-height:1.55}.answer-overview p{margin:0;color:var(--color-text-secondary,#4a5c6a);font-size:14px;line-height:1.65}
.redo-panel{margin-top:18px;border:1px solid #a9b8c1;border-radius:7px;background:#f8fafb;padding:16px}.redo-panel>header{display:flex;align-items:center;justify-content:space-between;gap:12px}.redo-panel>header>div{display:grid;gap:4px}.redo-panel strong,.redo-panel span{font-size:14px}.redo-panel>header span,.redo-panel>footer>span{color:var(--color-text-muted,#60727c)}.redo-options{display:grid;gap:8px;margin-top:15px}.redo-options label{display:grid;min-height:46px;grid-template-columns:18px 30px minmax(0,1fr);align-items:center;gap:9px;border:1px solid var(--color-border,#dce1e2);border-radius:5px;background:#fff;padding:7px 10px;cursor:pointer}.redo-options label:has(input:checked){border-color:#11212d;background:#eef2f3}.redo-options b{display:grid;width:28px;height:28px;place-items:center;border:1px solid currentColor;border-radius:50%;font-size:14px}.redo-options span{line-height:1.5}.redo-panel textarea{min-height:130px;margin-top:15px;resize:vertical}.redo-panel>footer{display:flex;align-items:center;justify-content:space-between;gap:16px;margin-top:13px}.redo-panel>footer button,.notes-actions button:last-child{border-color:#11212d;background:#11212d;color:#fff}
.redo-preparing{display:flex;min-height:96px;align-items:center;justify-content:center;gap:9px;color:var(--color-text-muted,#60727c)}.redo-prepare-error{display:grid;justify-items:start;gap:10px;margin-top:14px}.redo-boolean{display:flex;gap:9px;margin-top:15px}.redo-boolean button{min-width:116px}.redo-boolean button.selected{border-color:#11212d;background:#11212d;color:#fff}.redo-blanks{display:grid;gap:9px;margin-top:15px}.redo-blanks label{display:grid;grid-template-columns:54px minmax(0,1fr);align-items:center;gap:9px}.redo-blanks label>span{font-weight:700}.redo-code{display:grid;margin-top:15px}.redo-code>span{color:var(--color-text-muted,#60727c);font-weight:700}.redo-code textarea{margin-top:7px;font-family:ui-monospace,SFMono-Regular,Consolas,monospace}.redo-feedback{margin:9px 0 0;color:var(--color-text-secondary,#4a5c6a);font-size:14px;line-height:1.65}
.detail-section{border-bottom:1px solid var(--color-border,#dce1e2)}.detail-section>summary{display:grid;min-height:58px;grid-template-columns:minmax(0,1fr) auto 18px;align-items:center;gap:12px;cursor:pointer;list-style:none}.detail-section>summary::-webkit-details-marker{display:none}.detail-section>summary>span{display:flex;align-items:center;gap:9px}.detail-section>summary strong,.detail-section>summary small{font-size:14px}.detail-section>summary small{color:var(--color-text-muted,#60727c)}.detail-section>summary>svg{transition:transform 160ms ease}.detail-section[open]>summary>svg{transform:rotate(180deg)}.section-body{padding:0 0 20px}.section-empty{margin:0;color:var(--color-text-muted,#60727c);font-size:14px;line-height:1.65}
.attempt-list{margin:0;padding:0;list-style:none;border-top:1px solid var(--color-border,#dce1e2)}.attempt-list li{display:grid;min-height:64px;grid-template-columns:34px minmax(120px,.8fr) minmax(180px,1.2fr) minmax(120px,.8fr) auto;align-items:center;gap:12px;border-bottom:1px solid var(--color-border,#dce1e2);padding:8px 4px}.attempt-index{display:grid;width:28px;height:28px;place-items:center;border-radius:50%;background:var(--color-surface-subtle,#f5f7f7);font-size:14px;font-weight:700}.attempt-list li>span:not(.attempt-index){display:grid;gap:3px}.attempt-list strong,.attempt-list small{font-size:14px}.attempt-list small{color:var(--color-text-muted,#60727c)}.attempt-list button{min-height:34px;padding:6px 9px}.result-wrong{color:#842b24}.result-correct{color:#11212d}
.diagnosis-body{display:grid;gap:14px}.diagnosis-summary{display:grid;grid-template-columns:minmax(170px,.6fr) minmax(0,1.4fr);gap:18px;border-top:1px solid var(--color-border,#dce1e2);padding-top:15px}.diagnosis-summary span{display:grid;gap:4px}.diagnosis-summary strong,.diagnosis-summary small,.diagnosis-summary p{font-size:14px}.diagnosis-summary small,.diagnosis-summary p{color:var(--color-text-secondary,#4a5c6a)}.diagnosis-summary p{margin:0;line-height:1.65}.diagnosis-form{display:grid;grid-template-columns:minmax(160px,.7fr) minmax(260px,1.3fr);gap:10px;border:1px solid var(--color-border,#dce1e2);border-radius:6px;padding:12px}.diagnosis-form label{display:grid;gap:5px}.diagnosis-form label span{color:var(--color-text-muted,#60727c);font-size:14px;font-weight:700}.diagnosis-form>div{display:flex;grid-column:1/-1;flex-wrap:wrap;gap:7px}.retest-row,.reflection-row,.maintenance-body{display:grid;grid-template-columns:20px minmax(0,1fr) auto;align-items:center;gap:12px;border-top:1px solid var(--color-border,#dce1e2);padding-top:14px}.retest-row>span,.reflection-row>span,.maintenance-body>span{display:grid;gap:4px}.retest-row strong,.retest-row small,.reflection-row strong,.reflection-row small,.maintenance-body strong,.maintenance-body small{font-size:14px}.retest-row small,.reflection-row small,.maintenance-body small{color:var(--color-text-muted,#60727c)}
.source-body{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:20px}.source-body section{min-width:0;border-top:1px solid var(--color-border,#dce1e2);padding-top:14px}.source-body h3,.practice-grid h3{margin:0 0 10px;font-size:15px}.link-row{display:flex!important;width:100%;min-height:52px!important;justify-content:space-between!important;margin-top:7px;text-align:left}.link-row>span{display:grid;min-width:0;gap:3px}.link-row strong,.link-row small{overflow:hidden;font-size:14px;text-overflow:ellipsis;white-space:nowrap}.link-row small{color:var(--color-text-muted,#60727c);font-weight:400}
.notes-body>p{margin:0 0 12px;color:var(--color-text-secondary,#4a5c6a);font-size:14px;line-height:1.75;white-space:pre-wrap}.notes-body textarea{min-height:120px;resize:vertical}.notes-actions{display:flex;justify-content:flex-end;gap:8px;margin:10px 0 14px}.reflection-row{grid-template-columns:minmax(0,1fr) auto;margin-top:14px}
.practice-grid{display:grid;grid-template-columns:1fr 1fr;gap:20px}.practice-grid>section{min-width:0;border-top:1px solid var(--color-border,#dce1e2);padding-top:14px}.practice-grid>section>p{margin:0 0 12px;color:var(--color-text-muted,#60727c);font-size:14px;line-height:1.6}.practice-grid>section>small{display:block;margin-top:9px;color:var(--color-text-muted,#60727c);font-size:14px;line-height:1.5}.practice-loading{display:flex;min-height:88px;align-items:center;justify-content:center;gap:9px;color:var(--color-text-muted,#60727c);font-size:14px}.similar-question{display:block;margin-bottom:10px;font-size:14px;line-height:1.65}.similar-option{display:flex;min-height:40px;align-items:flex-start;gap:8px;border-top:1px solid var(--color-border,#dce1e2);padding:9px 2px;font-size:14px;line-height:1.5}.confidence-field{display:grid;gap:6px;margin:12px 0}.confidence-field span{font-size:14px;font-weight:700}.confidence-field input{width:100%}
.similar-result{margin-top:14px;border-left:3px solid #11212d;background:#f5f7f7;padding:11px 12px;color:#11212d;font-size:14px;line-height:1.6}.similar-result.correct{border-left-color:#315b3e;background:#f1f7f2}.similar-result strong,.similar-result p{display:block}.similar-result p{margin:6px 0 0}.similar-result b{font-weight:700}
.inline-error,.inline-result{display:flex;align-items:flex-start;gap:7px;margin:12px 0 0;border-left:3px solid #842b24;background:#fff8f7;padding:9px 10px;color:#842b24;font-size:14px;line-height:1.55}.inline-result{border-left-color:#60727c;background:#f5f7f7;color:#11212d}.inline-result.correct{border-left-color:#11212d}
.analytics-body{display:grid;grid-template-columns:minmax(280px,.8fr) minmax(340px,1.2fr);gap:24px}.analytics-summary{display:grid;grid-template-columns:repeat(3,1fr);border:1px solid var(--color-border,#dce1e2);border-radius:6px}.analytics-summary span{display:grid;gap:3px;padding:14px}.analytics-summary span+span{border-left:1px solid var(--color-border,#dce1e2)}.analytics-summary strong{font-size:19px}.analytics-summary small{color:var(--color-text-muted,#60727c);font-size:14px}.cluster-list{display:grid;gap:9px}.cluster-list>div{display:grid;grid-template-columns:100px minmax(0,1fr) 28px;align-items:center;gap:10px}.cluster-list span,.cluster-list strong{font-size:14px}.cluster-list i{display:block;height:8px;overflow:hidden;border-radius:999px;background:#e7ebec}.cluster-list b{display:block;height:100%;border-radius:inherit;background:#60727c}.maintenance-section{border-bottom:0}.maintenance-body{grid-template-columns:minmax(0,1fr) auto}.maintenance-body button{border-color:#c99a95;color:#842b24}.detail-loading{display:grid;gap:14px;padding:28px 0}.detail-loading span{display:block;height:68px;border-radius:5px;background:var(--color-surface-subtle,#f5f7f7);animation:pulse 1.4s ease-in-out infinite}button:disabled{opacity:.5;cursor:not-allowed}.spin{animation:spin 1s linear infinite}
@keyframes pulse{50%{opacity:.55}}@keyframes spin{to{transform:rotate(360deg)}}
@media(max-width:1240px){.filter-bar{grid-template-columns:minmax(240px,1fr) repeat(3,150px) 40px}.wrong-grid{grid-template-columns:320px minmax(0,1fr)}.detail-heading{display:grid}.detail-actions{justify-content:flex-start}.answer-overview{grid-template-columns:1fr 1fr}.answer-overview article{grid-column:1/-1;border-top:1px solid var(--color-border,#dce1e2);border-left:0}.attempt-list li{grid-template-columns:32px minmax(110px,.8fr) minmax(150px,1.2fr) minmax(110px,.8fr)}.attempt-list button{grid-column:2/-1;justify-self:start}.source-body{grid-template-columns:1fr 1fr}.source-body section:last-child{grid-column:1/-1}}

/* FB-FE-01: the question detail is the primary work surface. */
.wrong-grid {
  grid-template-columns: 286px minmax(0, 1fr);
}

.detail-pane {
  padding-right: 28px;
  padding-left: 28px;
}

@media(max-width:1240px) {
  .wrong-grid {
    grid-template-columns: 260px minmax(0, 1fr);
  }
}
</style>
