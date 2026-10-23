<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  Activity, AlertCircle, Braces, CheckCircle2, ChevronRight, CircleDot,
  ClipboardCheck, Code2, ExternalLink, Gauge, Library, ListChecks, LoaderCircle,
  MapPin, RefreshCw, Sparkles,
} from '@lucide/vue'
import {
  getM5AssessmentAbility, getM5AssessmentAttempt, getM5NextCatQuestion, listM5AssessmentQuestions,
  submitM5AssessmentAttempt,
} from '../api'
import ProfileSummaryPanel from '../components/ProfileSummaryPanel.vue'
import DiagnosticAssessmentSession from '../components/DiagnosticAssessmentSession.vue'
import { useCourseContextStore } from '../stores/courseContext'

const route = useRoute()
const router = useRouter()
const courseContext = useCourseContextStore()
const isAssessmentCenter = computed(() => route.name === 'AssessmentCenter' && !blueprintId.value)
const courseId = computed(() => String(route.query.course_id || courseContext.contextRef?.courseId || ''))
const courseTitle = computed(() => courseContext.course?.title || localStorage.getItem('edumatrix_course_title') || '当前课程')
const blueprintId = computed(() => String(route.query.blueprint_id || ''))
const requestedQuestionId = computed(() => String(route.query.question_version_id || ''))
const loading = ref(true)
const submitting = ref(false)
const error = ref('')
const catalog = ref([])
const active = ref(null)
const result = ref(null)
const ability = ref({ theta: [0, 0, 0], theta_std: [1, 1, 1], response_count: 0 })
const abilityExplanation = ref({ dimensions: [], summary: '', boundary: '' })
const selection = ref(null)
const attemptIds = ref({})
const completedVersionIds = ref([])
const answer = ref({ choice: '', choices: [], value: null, blanks: [], text: '', code: '' })
const summaryPanel = ref(null)

const typeLabels = {
  single_choice: '单选题', multiple_choice: '多选题', true_false: '判断题', fill_blank: '填空题',
  short_answer: '简答题', code: '代码题', open_task: '开放任务',
}
const dimensionLabels = ['理论理解', '代码实践', '数学推理']

const canSubmit = computed(() => {
  if (!active.value) return false
  const type = active.value.question_type
  if (type === 'single_choice') return !!answer.value.choice
  if (type === 'multiple_choice') return answer.value.choices.length > 0
  if (type === 'true_false') return answer.value.value !== null
  if (type === 'fill_blank') return answer.value.blanks.length > 0 && answer.value.blanks.every(item => item.trim())
  if (type === 'code') return !!answer.value.code.trim()
  return !!answer.value.text.trim()
})

function message(err) {
  const detail = err?.detail || err?.response?.data?.detail
  return detail?.message || (typeof detail === 'string' ? detail : '') || err?.message || '测评服务暂不可用'
}

function resetAnswer(question) {
  answer.value = {
    choice: '', choices: [], value: null,
    blanks: Array.from({ length: question?.response_spec?.blank_count || 1 }, () => ''),
    text: '', code: '',
  }
  result.value = null
}

async function selectQuestion(question, catSelection = null) {
  active.value = question
  selection.value = catSelection
  resetAnswer(question)
  const attemptId = attemptIds.value[question.id]
  if (attemptId) {
    try {
      result.value = await getM5AssessmentAttempt(attemptId)
      if (result.value.ability) ability.value = result.value.ability
      if (result.value.ability_explanation) abilityExplanation.value = result.value.ability_explanation
    } catch { /* stale local pointer */ }
  }
}

function optionLabel(option, index) {
  const value = String(option)
  return /^[A-Z][.)、:\s]/i.test(value) ? value.slice(0, 1).toUpperCase() : String.fromCharCode(65 + index)
}

function optionText(option) {
  return String(option || '').trim().replace(/^[A-D](?:[.、:)]\s*|\s+)/i, '')
}

function answerPayload() {
  const type = active.value.question_type
  if (type === 'single_choice') return { choice: answer.value.choice }
  if (type === 'multiple_choice') return { choices: answer.value.choices }
  if (type === 'true_false') return { value: answer.value.value }
  if (type === 'fill_blank') return { blanks: answer.value.blanks }
  if (type === 'code') return { code: answer.value.code }
  return { text: answer.value.text }
}

function abilityPercent(theta) {
  return Math.max(4, Math.min(100, ((Number(theta) + 4) / 8) * 100))
}

async function load() {
  loading.value = true
  error.value = ''
  if (!courseId.value) {
    catalog.value = []
    active.value = null
    result.value = null
    loading.value = false
    return
  }
  try {
    const [questions, state] = await Promise.all([
      listM5AssessmentQuestions({ course_id: courseId.value }),
      getM5AssessmentAbility({ course_id: courseId.value }),
    ])
    catalog.value = questions.items || []
    ability.value = questions.ability || state
    abilityExplanation.value = questions.ability_explanation || state.explanation || abilityExplanation.value
    attemptIds.value = Object.fromEntries((questions.attempts || []).map(item => [item.question_version_id, item.id]))
    completedVersionIds.value = Object.keys(attemptIds.value)
    const requested = catalog.value.find((item) => item.id === requestedQuestionId.value)
    if (requested || (!active.value && catalog.value.length)) selectQuestion(requested || catalog.value[0])
  } catch (err) {
    error.value = message(err)
  } finally {
    loading.value = false
  }
}

async function nextAdaptive() {
  submitting.value = true
  error.value = ''
  try {
    const data = await getM5NextCatQuestion({
      course_id: courseId.value,
      excluded_version_ids: completedVersionIds.value,
    })
    ability.value = data.ability
    abilityExplanation.value = data.ability_explanation || abilityExplanation.value
    selectQuestion(data.question, data.selection)
  } catch (err) {
    error.value = message(err)
  } finally {
    submitting.value = false
  }
}

async function submit() {
  if (!canSubmit.value) return
  submitting.value = true
  error.value = ''
  try {
    const data = await submitM5AssessmentAttempt({
      question_version_id: active.value.id,
      idempotency_key: `assessment-ui-${active.value.id}-${Date.now()}`,
      mode: 'diagnostic',
      answer: answerPayload(),
    })
    result.value = data
    attemptIds.value[active.value.id] = data.id
    if (!completedVersionIds.value.includes(active.value.id)) completedVersionIds.value.push(active.value.id)
    if (data.ability) ability.value = data.ability
    if (data.ability_explanation) abilityExplanation.value = data.ability_explanation
    await summaryPanel.value?.refresh()
  } catch (err) {
    error.value = message(err)
  } finally {
    submitting.value = false
  }
}

function openSource(source) {
  router.push({
    path: '/knowledge',
    query: {
      course_id: courseId.value,
      document_id: source.source_document_id,
    },
  })
}

onMounted(() => {
  if (!isAssessmentCenter.value && !blueprintId.value) load()
})
</script>

<template>
  <main v-if="isAssessmentCenter" class="assessment-center" data-testid="assessment-center">
    <header class="center-heading">
      <span>测评中心</span>
      <h1>用两次关键测评校准学习</h1>
      <p>先确认起点，再在今日必做任务完成后检验本轮学习结果。</p>
    </header>
    <section class="assessment-entry-list" aria-label="测评入口">
      <button type="button" data-testid="entry-diagnostic" @click="router.push({ path: '/workspace/assessment/entry', query: { course_id: courseId } })">
        <span class="entry-index">01</span>
        <span class="entry-content">
          <strong>入学诊断</strong>
          <small>通过课程知识点动态出题，建立本课程的学习起点。</small>
        </span>
        <span class="entry-action">开始诊断 <ChevronRight :size="18" /></span>
      </button>
      <button type="button" data-testid="intelligent-exam-entry" @click="router.push({ path: '/workspace/assessment/exams', query: { course_id: courseId } })">
        <span class="entry-index">02</span>
        <span class="entry-content">
          <strong>智能组卷</strong>
          <small>完成今日必做任务后，按课程范围、知识点和题量生成正式试卷。</small>
        </span>
        <span class="entry-action">查看状态 <ChevronRight :size="18" /></span>
      </button>
    </section>
    <footer class="center-boundary">
      <ListChecks :size="18" />
      <span><strong>测验题资源属于学习空间</strong><small>学习中的即时练习、测试题生成与判分不会出现在测评中心。</small></span>
    </footer>
  </main>
  <DiagnosticAssessmentSession
    v-else-if="blueprintId"
    :blueprint-id="blueprintId"
    :requested-question-id="requestedQuestionId"
  />
  <div v-else-if="!courseId" class="assessment-shell" data-testid="assessment-workspace">
    <section class="course-required-state" data-testid="assessment-course-required" role="status">
      <BookOpen :size="26" />
      <div>
        <h2>请选择课程后开始测评</h2>
        <p>新账号可以先浏览和使用其他学习功能；选择课程后，系统才会读取对应题目、画像和课程来源。</p>
      </div>
      <button type="button" class="primary-button" @click="router.push('/knowledge')">去选择课程 <ChevronRight :size="17" /></button>
    </section>
  </div>
  <div v-else class="assessment-shell" data-testid="assessment-workspace">
    <header class="assessment-header">
      <div>
        <span class="eyebrow"><ClipboardCheck :size="14" /> 主课程短诊断</span>
        <h1>先用几道题确认当前学习起点</h1>
      </div>
      <div class="header-actions">
        <button class="icon-button" type="button" title="刷新题库" :disabled="loading" @click="load"><RefreshCw :size="16" /></button>
        <button data-testid="cat-next" class="adaptive-button" type="button" :disabled="submitting || loading" @click="nextAdaptive">
          <Sparkles :size="15" /> CAT 下一题
        </button>
      </div>
    </header>

    <div v-if="error" class="state-banner error-state" role="alert"><AlertCircle :size="16" />{{ error }}</div>
    <div v-if="loading" class="state-banner"><LoaderCircle class="spin" :size="17" />正在载入测评题库</div>

    <template v-else>
      <section class="diagnostic-context" data-testid="diagnostic-context">
        <div><Library :size="17" /><span><strong>{{ courseTitle }}</strong><small>当前课程的题目与学习记录</small></span></div>
        <span>{{ completedVersionIds.length }}/{{ catalog.length }} 已完成</span>
      </section>
      <section class="ability-strip" aria-label="能力估计">
        <div class="ability-summary">
          <Gauge :size="18" />
          <span><strong>能力估计</strong><small>{{ ability.response_count || 0 }} 次有效作答</small></span>
        </div>
        <div v-for="(label, index) in dimensionLabels" :key="label" class="ability-item">
          <span>{{ label }} <b>{{ Number(ability.theta?.[index] || 0).toFixed(2) }}</b></span>
          <div><i :style="{ width: `${abilityPercent(ability.theta?.[index] || 0)}%` }" /></div>
          <small>{{ abilityExplanation.dimensions?.[index]?.status || '证据积累中' }} · 置信度{{ abilityExplanation.dimensions?.[index]?.confidence || '有限' }}</small>
        </div>
      </section>
      <p class="ability-boundary">{{ abilityExplanation.boundary }}</p>
      <ProfileSummaryPanel
        v-if="ability.response_count > 0"
        ref="summaryPanel"
        :course-id="courseId"
        compact
      />

      <div v-if="!catalog.length" class="empty-state" data-testid="assessment-empty">
        <ListChecks :size="30" />
        <strong>暂无已批准题目</strong>
        <span>题目通过教师审核后会出现在这里。</span>
      </div>

      <div v-else class="assessment-layout">
        <aside class="question-list" aria-label="题目列表">
          <div class="list-title"><span>题库</span><b>{{ catalog.length }}</b></div>
          <button
            v-for="(question, index) in catalog"
            :key="question.id"
            type="button"
            :class="{ active: active?.id === question.id }"
            @click="selectQuestion(question)"
          >
            <span class="question-index">{{ String(index + 1).padStart(2, '0') }}</span>
            <span><strong>{{ typeLabels[question.question_type] }}</strong><small>{{ question.prompt }}</small></span>
            <ChevronRight :size="15" />
          </button>
        </aside>

        <main v-if="active" class="question-stage" data-testid="assessment-question">
          <div class="question-meta">
            <span>{{ typeLabels[active.question_type] }}</span>
            <span v-if="selection"><Activity :size="12" />为你推荐</span>
          </div>
          <section v-if="selection" class="selection-reason" data-testid="cat-selection-reason">
            <Activity :size="15" />
            <span><strong>为什么推荐这道题</strong><small>{{ selection.reason || '根据当前掌握情况安排下一步练习。' }}</small></span>
          </section>
          <details v-if="active.evidence_context" class="question-evidence" data-testid="question-evidence">
            <summary><MapPin :size="15" />课程依据 <span>{{ active.evidence_context?.knowledge_point?.title || '当前知识点' }}</span></summary>
            <div class="question-evidence__body">
              <small>{{ active.evidence_context?.chapter?.title || '当前课程章节' }}</small>
              <button
                v-if="active.evidence_context?.sources?.[0]"
                type="button"
                data-testid="open-question-source"
                @click="openSource(active.evidence_context.sources[0])"
              >
                按需查看原文 <ExternalLink :size="13" />
              </button>
            </div>
          </details>
          <h2>{{ active.prompt }}</h2>

          <div v-if="active.question_type === 'single_choice'" class="option-list">
            <label v-for="(option, index) in active.options" :key="option" :class="{ selected: answer.choice === optionLabel(option, index) }">
              <input v-model="answer.choice" type="radio" :value="optionLabel(option, index)" />
              <b>{{ optionLabel(option, index) }}</b><span>{{ optionText(option) }}</span>
            </label>
          </div>

          <div v-else-if="active.question_type === 'multiple_choice'" class="option-list">
            <label v-for="(option, index) in active.options" :key="option" :class="{ selected: answer.choices.includes(optionLabel(option, index)) }">
              <input v-model="answer.choices" type="checkbox" :value="optionLabel(option, index)" />
              <b>{{ optionLabel(option, index) }}</b><span>{{ optionText(option) }}</span>
            </label>
          </div>

          <div v-else-if="active.question_type === 'true_false'" class="boolean-control">
            <button type="button" :class="{ selected: answer.value === true }" @click="answer.value = true"><CheckCircle2 :size="17" />正确</button>
            <button type="button" :class="{ selected: answer.value === false }" @click="answer.value = false"><CircleDot :size="17" />错误</button>
          </div>

          <div v-else-if="active.question_type === 'fill_blank'" class="blank-list">
            <label v-for="(_, index) in answer.blanks" :key="index"><span>空 {{ index + 1 }}</span><input v-model="answer.blanks[index]" /></label>
          </div>

          <div v-else-if="active.question_type === 'code'" class="code-answer">
            <div><Code2 :size="15" /><span>Python</span><small>{{ active.response_spec?.hidden_test_count || 0 }} 个隐藏测试</small></div>
            <textarea v-model="answer.code" rows="12" spellcheck="false" placeholder="def solution(...):" />
          </div>

          <textarea
            v-else
            v-model="answer.text"
            class="text-answer"
            rows="9"
            :placeholder="active.question_type === 'open_task' ? '提交你的方案、证据与结论' : '输入你的回答'"
          />

          <div class="submit-row">
            <span v-if="active.question_type === 'short_answer' || active.question_type === 'open_task'"><Sparkles :size="13" /> AI 智能初评</span>
            <span v-else-if="active.question_type === 'code'"><Braces :size="13" /> 隐藏测试评分</span>
            <span v-else><CheckCircle2 :size="13" /> 服务端客观评分</span>
            <button data-testid="assessment-submit" type="button" :disabled="!canSubmit || submitting" @click="submit">
              <LoaderCircle v-if="submitting" class="spin" :size="15" />
              <ClipboardCheck v-else :size="15" />
              {{ submitting ? '评分中' : '提交作答' }}
            </button>
          </div>

          <section v-if="result" class="result-panel" data-testid="assessment-result">
            <header>
              <span :class="result.correct === true ? 'pass' : result.correct === false ? 'fail' : 'pending'">
                {{ result.score == null ? '待评分' : `${Math.round(result.score * 100)} 分` }}
              </span>
              <div><strong>{{ result.grading?.label || '评分状态' }}</strong><small>{{ result.grading_status === 'graded' ? '已完成判分' : '作答已保存' }}</small></div>
            </header>
            <p>{{ result.grading?.feedback || '作答已保存。' }}</p>
            <p v-if="result.answer_explanation" class="answer-explanation"><strong>课程解释：</strong>{{ result.answer_explanation }}</p>
            <section v-if="result.ability_update?.applied" class="ability-change" data-testid="ability-change">
              <strong>本题如何改变能力证据</strong>
              <div>
                <span v-for="(label, index) in dimensionLabels" :key="label">
                  {{ label }}
                  <b>{{ Number(result.ability_update.before.theta?.[index] || 0).toFixed(2) }} → {{ Number(result.ability_update.after.theta?.[index] || 0).toFixed(2) }}</b>
                </span>
              </div>
              <small>{{ result.ability_explanation?.summary }} 这不是课程总评，后续作答会继续修正估计。</small>
            </section>
            <div v-if="result.grading?.criterion_results?.length" class="criterion-grid">
              <article v-for="criterion in result.grading.criterion_results" :key="criterion.criterion_id">
                <span>{{ criterion.criterion_id }} <b>{{ Math.round(criterion.score * 100) }}</b></span>
                <p>{{ criterion.justification }}</p>
                <small>{{ criterion.improvement }}</small>
              </article>
            </div>
            <div v-if="result.grading?.evidence?.test_scope === 'hidden'" class="code-evidence">
              隐藏测试已完成：{{ result.grading.evidence.passed_count }}/{{ result.grading.evidence.total_count }}
            </div>
          </section>
        </main>
      </div>
    </template>
  </div>
</template>

<style scoped>
.assessment-center{width:min(1120px,100%);margin:0 auto;padding:30px 0 54px;color:#211d1a}.center-heading{max-width:720px;padding:12px 0 28px;border-bottom:1px solid #d8d2cc}.center-heading>span{font-size:14px;font-weight:700;color:#725e50}.center-heading h1{margin:10px 0 12px;font-family:"Source Han Serif SC","Noto Serif CJK SC",serif;font-size:34px;line-height:1.25;letter-spacing:0}.center-heading p{margin:0;color:#675f59;font-size:16px;line-height:1.75}.assessment-entry-list{display:grid;margin-top:28px;border-top:1px solid #cfc7c0}.assessment-entry-list>button{display:grid;grid-template-columns:62px minmax(0,1fr) 150px;align-items:center;gap:20px;width:100%;min-height:138px;padding:24px 20px;border:0;border-bottom:1px solid #cfc7c0;background:#fff;color:#211d1a;text-align:left;cursor:pointer}.assessment-entry-list>button:hover,.assessment-entry-list>button:focus-visible{background:#f7f4f1;outline:none}.entry-index{align-self:start;padding-top:4px;color:#8a7a6f;font-size:14px;font-weight:700}.entry-content{display:grid;gap:9px}.entry-content strong{font-size:24px;line-height:1.3}.entry-content small{color:#675f59;font-size:15px;line-height:1.7}.entry-action{display:flex;align-items:center;justify-content:flex-end;gap:8px;color:#4a3529;font-size:15px;font-weight:700}.center-boundary{display:flex;align-items:center;gap:12px;margin-top:24px;padding:18px 20px;background:#f3efeb;color:#4f463f}.center-boundary span{display:grid;gap:4px}.center-boundary strong{font-size:15px}.center-boundary small{color:#746b64;font-size:14px;line-height:1.5}
.assessment-shell { width: min(1180px, 100%); margin: 0 auto; color: #253129; }
.course-required-state { display: grid; max-width: 680px; min-height: 260px; grid-template-columns: auto minmax(0, 1fr); align-items: center; gap: 16px; margin: 48px auto; padding: 28px; border: 1px solid #dce4de; border-radius: 8px; background: #fff; color: #253129; }
.course-required-state h2 { margin: 0; font-size: 20px; line-height: 1.45; }
.course-required-state p { margin: 8px 0 0; color: #66736b; font-size: 14px; line-height: 1.65; }
.course-required-state .primary-button { grid-column: 2; justify-self: start; }
.assessment-header { display: flex; align-items: flex-end; justify-content: space-between; gap: 18px; margin-bottom: 18px; }
.eyebrow { display: flex; align-items: center; gap: 6px; color: #55705f; font-size: 11px; font-weight: 700; }.assessment-header h1 { margin: 5px 0 0; font-size: 22px; font-weight: 720; letter-spacing: 0; }
.header-actions { display: flex; gap: 8px; }.header-actions button { display: inline-flex; min-height: 36px; align-items: center; justify-content: center; gap: 7px; border: 1px solid #d7dfd9; border-radius: 7px; background: #fff; color: #425149; }.icon-button { width: 36px; }.adaptive-button { padding: 0 13px; font-size: 11px; font-weight: 700; }.adaptive-button:hover { border-color: #8ba494; background: #f3f7f4; }
.state-banner { display: flex; align-items: center; gap: 8px; margin-bottom: 14px; border: 1px solid #dfe6e1; border-radius: 7px; background: #f8faf8; padding: 10px 12px; color: #66736b; font-size: 11px; }.error-state { border-color: #efceca; background: #fff6f4; color: #a04439; }
.diagnostic-context { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 10px; border: 1px solid #d8e2db; border-radius: 8px; background: #f4f8f5; padding: 11px 13px; }.diagnostic-context > div { display: flex; min-width: 0; align-items: center; gap: 9px; }.diagnostic-context strong, .diagnostic-context small { display: block; }.diagnostic-context strong { font-size: 11px; }.diagnostic-context small { margin-top: 3px; color: #77837b; font-size: 9px; }.diagnostic-context > span { flex: none; color: #42624d; font-size: 10px; font-weight: 700; }
.ability-strip { display: grid; grid-template-columns: 1.05fr repeat(3, 1fr); gap: 1px; overflow: hidden; margin-bottom: 16px; border: 1px solid #dce4de; border-radius: 8px; background: #dce4de; }.ability-strip > div { min-width: 0; background: rgba(255,255,255,.92); padding: 11px 13px; }.ability-summary { display: flex; align-items: center; gap: 8px; }.ability-summary span, .ability-summary strong, .ability-summary small { display: block; }.ability-summary strong { font-size: 11px; }.ability-summary small { margin-top: 2px; color: #89938c; font-size: 9px; }.ability-item span { display: flex; justify-content: space-between; color: #69766e; font-size: 9px; }.ability-item b { color: #365842; }.ability-item > div { height: 4px; margin-top: 7px; overflow: hidden; border-radius: 3px; background: #edf1ee; }.ability-item i { display: block; height: 100%; border-radius: inherit; background: #4f7a5e; transition: width .3s ease; }
.ability-item small { display: block; margin-top: 6px; color: #829087; font-size: 8px; line-height: 1.4; }.ability-boundary { margin: -7px 0 15px; color: #78847c; font-size: 9px; line-height: 1.55; }
.assessment-layout { display: grid; grid-template-columns: 250px minmax(0, 1fr); min-height: 590px; overflow: hidden; border: 1px solid #dce4de; border-radius: 8px; background: #fff; }.question-list { border-right: 1px solid #e1e7e3; background: #f7f9f7; }.list-title { display: flex; height: 45px; align-items: center; justify-content: space-between; border-bottom: 1px solid #e1e7e3; padding: 0 12px; color: #59665e; font-size: 10px; font-weight: 700; }.list-title b { display: grid; width: 22px; height: 22px; place-items: center; border-radius: 6px; background: #e7ede8; }.question-list > button { display: grid; width: 100%; grid-template-columns: 28px minmax(0, 1fr) 16px; align-items: center; gap: 8px; border: 0; border-bottom: 1px solid #e7ece8; background: transparent; padding: 10px; color: #5d6961; text-align: left; }.question-list > button.active { background: #fff; box-shadow: inset 3px 0 #477356; color: #2d4736; }.question-index { font-size: 9px; font-variant-numeric: tabular-nums; }.question-list strong, .question-list small { display: block; }.question-list strong { font-size: 10px; }.question-list small { margin-top: 3px; overflow: hidden; color: #8a948d; font-size: 9px; text-overflow: ellipsis; white-space: nowrap; }
.question-stage { min-width: 0; padding: 25px clamp(18px, 4vw, 42px); }.question-meta { display: flex; flex-wrap: wrap; gap: 6px; }.question-meta span { display: inline-flex; align-items: center; gap: 4px; border-radius: 5px; background: #eef3ef; padding: 4px 7px; color: #55705f; font-size: 9px; font-weight: 700; }.question-stage h2 { margin: 18px 0 22px; color: #27362c; font-size: 17px; font-weight: 660; line-height: 1.65; letter-spacing: 0; }
.selection-reason, .question-evidence { margin-top: 12px; border-left: 3px solid #6f927a; background: #f5f8f6; padding: 9px 11px; color: #587060; }.selection-reason { display: flex; align-items: center; gap: 9px; }.selection-reason span, .selection-reason strong, .selection-reason small { display: block; }.selection-reason strong { font-size: 10px; }.selection-reason small { margin-top: 3px; color: #7d8981; font-size: 8px; line-height: 1.5; }.question-evidence { border-left-color: #7d879f; background: #f7f7fa; color: #505b73; }.question-evidence summary { display: flex; min-height: 25px; align-items: center; gap: 7px; cursor: pointer; list-style: none; font-size: 10px; font-weight: 700; }.question-evidence summary::-webkit-details-marker { display: none; }.question-evidence summary span { margin-left: auto; color: #7d879f; font-weight: 500; }.question-evidence__body { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 8px 0 1px 22px; }.question-evidence__body small { color: #7d879f; font-size: 9px; line-height: 1.5; }.question-evidence button { display: inline-flex; min-height: 30px; flex: none; align-items: center; gap: 5px; border: 1px solid #cfd5e0; border-radius: 6px; background: #fff; padding: 0 9px; color: #4f5d78; font-size: 9px; font-weight: 700; }
.option-list { display: grid; gap: 8px; }.option-list label { display: grid; grid-template-columns: 0 28px minmax(0, 1fr); align-items: center; gap: 9px; min-height: 48px; border: 1px solid #dde5df; border-radius: 7px; padding: 8px 12px; cursor: pointer; }.option-list label.selected { border-color: #6f927a; background: #f1f6f2; }.option-list input { width: 0; opacity: 0; }.option-list b { display: grid; width: 26px; height: 26px; place-items: center; border-radius: 6px; background: #edf1ee; color: #657269; font-size: 10px; }.option-list .selected b { background: #4a7358; color: #fff; }.option-list span { min-width: 0; font-size: 11px; }
.boolean-control { display: grid; grid-template-columns: 1fr 1fr; gap: 9px; }.boolean-control button { display: flex; min-height: 52px; align-items: center; justify-content: center; gap: 8px; border: 1px solid #dce4de; border-radius: 7px; background: #fff; color: #657168; font-size: 11px; font-weight: 650; }.boolean-control button.selected { border-color: #62866d; background: #eff5f0; color: #365b43; }
.blank-list { display: grid; gap: 10px; }.blank-list label { display: grid; grid-template-columns: 48px minmax(0, 1fr); align-items: center; gap: 8px; }.blank-list span { color: #748078; font-size: 10px; }.blank-list input, .text-answer { width: 100%; border: 1px solid #d9e1db; border-radius: 7px; background: #fbfcfb; padding: 11px 12px; color: #303d34; font-size: 11px; outline: none; }.blank-list input:focus, .text-answer:focus, .code-answer textarea:focus { border-color: #73927c; box-shadow: 0 0 0 3px rgba(78,119,90,.08); }.text-answer { resize: vertical; line-height: 1.7; }
.code-answer { overflow: hidden; border: 1px solid #d6ded8; border-radius: 7px; background: #202822; }.code-answer > div { display: flex; height: 37px; align-items: center; gap: 7px; border-bottom: 1px solid rgba(255,255,255,.08); padding: 0 11px; color: #d7e0d9; font-size: 10px; }.code-answer small { margin-left: auto; color: #8fa096; }.code-answer textarea { width: 100%; resize: vertical; border: 0; background: #202822; padding: 13px; color: #dce5df; font: 11px/1.65 Consolas, monospace; outline: none; }
.submit-row { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-top: 18px; border-top: 1px solid #e5eae6; padding-top: 14px; }.submit-row > span { display: inline-flex; align-items: center; gap: 5px; color: #78847c; font-size: 9px; }.submit-row button { display: inline-flex; min-height: 36px; align-items: center; gap: 7px; border: 0; border-radius: 7px; background: #355c43; padding: 0 14px; color: #fff; font-size: 10px; font-weight: 700; }.submit-row button:disabled { opacity: .45; }
.result-panel { margin-top: 18px; border: 1px solid #dbe4dd; border-radius: 8px; background: #f8faf8; padding: 14px; }.result-panel > header { display: flex; align-items: center; gap: 10px; }.result-panel > header > span { display: grid; min-width: 55px; height: 38px; place-items: center; border-radius: 7px; font-size: 11px; font-weight: 750; }.result-panel .pass { background: #e4f2e7; color: #2f7042; }.result-panel .fail { background: #f8e8e5; color: #a14338; }.result-panel .pending { background: #f0eee7; color: #7d6d3f; }.result-panel header strong, .result-panel header small { display: block; }.result-panel header strong { font-size: 11px; }.result-panel header small { margin-top: 3px; color: #87928a; font-size: 9px; }.result-panel > p { margin: 12px 0 0; color: #59675e; font-size: 10px; line-height: 1.6; }.criterion-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 7px; margin-top: 11px; }.criterion-grid article { border: 1px solid #e1e7e2; border-radius: 6px; background: #fff; padding: 9px; }.criterion-grid span { display: flex; justify-content: space-between; color: #536158; font-size: 9px; font-weight: 700; }.criterion-grid p, .criterion-grid small { display: block; margin: 5px 0 0; color: #7b867e; font-size: 8px; line-height: 1.5; }.code-evidence { margin-top: 10px; border-radius: 6px; background: #e9f0eb; padding: 8px 10px; color: #486252; font: 9px Consolas, monospace; }
.answer-explanation { border-top: 1px solid #e1e7e2; padding-top: 10px; }.ability-change { margin-top: 11px; border: 1px solid #dce5df; border-radius: 7px; background: #fff; padding: 10px; }.ability-change > strong { display: block; color: #3e5847; font-size: 10px; }.ability-change > div { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 6px; margin-top: 8px; }.ability-change span { display: grid; gap: 3px; border: 1px solid #e5eae6; border-radius: 6px; padding: 7px; color: #7b877f; font-size: 8px; }.ability-change b { color: #355c43; font-size: 9px; }.ability-change small { display: block; margin-top: 8px; color: #7d8880; font-size: 8px; line-height: 1.5; }
.empty-state { display: grid; min-height: 360px; place-items: center; align-content: center; gap: 8px; border: 1px dashed #d8e0da; border-radius: 8px; background: #fafbfa; color: #89948c; }.empty-state strong { color: #5e6a62; font-size: 12px; }.empty-state span { font-size: 9px; }.spin { animation: spin .8s linear infinite; }@keyframes spin { to { transform: rotate(360deg); } }
.question-stage h2,.option-list label span,.question-evidence small,.selection-reason small{min-width:0;overflow-wrap:anywhere;white-space:normal;word-break:break-word;line-height:1.65}.question-stage h2{font-size:18px}.option-list label span{font-size:14px}
@media (max-width: 760px) { .assessment-header { align-items: stretch; flex-direction: column; }.assessment-header h1 { font-size: 18px; }.header-actions { width: 100%; justify-content: flex-end; }.header-actions .adaptive-button { min-width: 0; flex: 1; padding: 0 9px; }.diagnostic-context { align-items: flex-start; flex-direction: column; }.ability-strip { grid-template-columns: 1fr; }.assessment-layout { grid-template-columns: 1fr; }.question-list { display: flex; overflow-x: auto; border-right: 0; border-bottom: 1px solid #e1e7e3; }.list-title { display: none; }.question-list > button { min-width: 180px; border-right: 1px solid #e4e9e5; border-bottom: 0; }.question-stage { padding: 20px 14px; }.question-stage h2 { font-size: 15px; }.question-evidence { align-items: flex-start; flex-direction: column; }.criterion-grid, .ability-change > div { grid-template-columns: 1fr; }.submit-row { align-items: flex-start; flex-direction: column; }.submit-row button { width: 100%; justify-content: center; }.boolean-control { grid-template-columns: 1fr; } }
</style>
