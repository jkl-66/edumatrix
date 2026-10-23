<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  AlertCircle,
  ArrowRight,
  BookOpen,
  Check,
  CheckCircle2,
  ClipboardCheck,
  FileSearch,
  Gauge,
  LoaderCircle,
  RefreshCw,
  ShieldCheck,
  Timer,
  UserRoundCheck,
} from '@lucide/vue'
import {
  createDiagnosticBlueprint,
  createMulticourseDiagnosticBlueprints,
  errorMessageText,
  getDiagnosticCourses,
  getDiagnosticPreflight,
} from '../api'
import { useCourseContextStore } from '../stores/courseContext'

const route = useRoute()
const router = useRouter()
const courseContext = useCourseContextStore()
const questionCount = ref(15)
const loading = ref(true)
const coursesLoading = ref(true)
const generating = ref(false)
const error = ref('')
const courseListError = ref('')
const errorKind = ref('preflight')
const generationFailed = ref(false)
const courses = ref([])
const queryCourseIds = (() => {
  const raw = route.query.course_ids
  const values = Array.isArray(raw) ? raw : raw ? String(raw).split(',') : []
  const fromQuery = values.map((item) => String(item).trim()).filter(Boolean)
  return fromQuery.length ? fromQuery : [String(route.query.course_id || courseContext.contextRef?.courseId || '')].filter(Boolean)
})()
const selectedCourseIds = ref(queryCourseIds)
const selectedCourseId = ref(queryCourseIds[0] || '')
const selfRating = ref('foundation')
const preflight = ref(null)
const blueprint = ref(null)
const multicourseResult = ref(null)
let disposed = false
let generationStarted = false

const courseId = computed(() => String(
  selectedCourseId.value
  || route.query.course_id
  || courseContext.contextRef?.courseId
  || '',
))
const selectedCourse = computed(() => courses.value.find((item) => item.id === courseId.value) || {})
const selectedCourses = computed(() => selectedCourseIds.value
  .map((id) => courses.value.find((item) => item.id === id))
  .filter(Boolean))
const multiCourse = computed(() => selectedCourseIds.value.length > 1)
const course = computed(() => blueprint.value?.course || preflight.value?.course || selectedCourse.value || {})
const courseVersionLabel = computed(() => {
  const value = String(course.value.version || '')
  const semanticVersion = value.match(/(\d+(?:\.\d+)+)$/)?.[1]
  return semanticVersion ? `版本 ${semanticVersion}` : value ? `版本 ${value}` : '当前版本'
})
const coverage = computed(() => preflight.value?.coverage || {})
const knowledgePoints = computed(() => blueprint.value?.knowledgePointCoverage || coverage.value.knowledgePoints || [])
const questionTypes = computed(() => blueprint.value?.difficultyBands?.questionTypes || coverage.value.questionTypes || {})
const estimatedMinutes = computed(() => blueprint.value?.estimatedMinutes || preflight.value?.estimatedMinutes || Math.max(6, questionCount.value * 2))
const canGenerate = computed(() => Boolean(courseId.value) && !generating.value && (
  multiCourse.value ? Boolean(preflight.value?.profileBasis) : Boolean(preflight.value?.canGenerate)
))
const profileMissing = computed(() => !preflight.value?.profileBasis)
const stageItems = computed(() => blueprint.value?.generationStages || [
  { key: 'analysis', label: '分析课程、知识库与画像', status: generationFailed.value ? 'failed' : generating.value ? 'processing' : 'pending' },
  { key: 'generation', label: 'AI 定制生成诊断题', status: generationFailed.value ? 'failed' : generating.value ? 'processing' : 'pending' },
  { key: 'validation', label: '校验题量、题型与来源', status: generationFailed.value ? 'failed' : generating.value ? 'processing' : 'pending' },
  { key: 'review', label: '独立模型逐题审核', status: generationFailed.value ? 'failed' : generating.value ? 'processing' : 'pending' },
])

const selfRatingOptions = [
  { value: 'foundation', label: '基础', description: '从核心概念开始检查' },
  { value: 'advanced', label: '进阶', description: '已有基础，增加应用题' },
  { value: 'mastered', label: '完全掌握', description: '优先检查综合与迁移' },
]

const typeLabels = {
  true_false: '判断题',
  single_choice: '选择题',
  short_answer: '简答题',
}

function messageOf(requestError) {
  const detail = requestError?.response?.data?.detail ?? requestError?.detail
  const fallback = requestError?.message === '[object Object]' ? '' : requestError?.message
  return errorMessageText(detail, errorMessageText(fallback, '诊断服务暂不可用，请稍后重试。'))
}

function idempotencyKey() {
  const storageKey = `edumatrix-diagnostic-key:${selectedCourseIds.value.join(',')}:${questionCount.value}:${selfRating.value}`
  let key = sessionStorage.getItem(storageKey)
  if (!key) {
    key = globalThis.crypto?.randomUUID?.() || `diagnostic-${Date.now()}-${Math.random().toString(16).slice(2)}`
    sessionStorage.setItem(storageKey, key)
  }
  return key
}

async function loadCourses() {
  if (disposed || generationStarted) return
  coursesLoading.value = true
  courseListError.value = ''
  try {
    const result = await getDiagnosticCourses()
    if (disposed || generationStarted) return
    courses.value = result.courses || []
    const availableIds = new Set(courses.value.map((item) => item.id))
    selectedCourseIds.value = selectedCourseIds.value.filter((id) => availableIds.has(id))
    if (!selectedCourseIds.value.length) selectedCourseIds.value = courses.value[0]?.id ? [courses.value[0].id] : []
    selectedCourseId.value = selectedCourseIds.value[0] || ''
    if (selectedCourseId.value) {
      if (disposed || generationStarted) return
      await loadPreflight()
    }
  } catch (requestError) {
    courseListError.value = messageOf(requestError)
  } finally {
    coursesLoading.value = false
  }
}

async function loadPreflight() {
  if (disposed || generationStarted) return
  loading.value = true
  error.value = ''
  errorKind.value = 'preflight'
  generationFailed.value = false
  blueprint.value = null
  multicourseResult.value = null
  if (!courseId.value) {
    preflight.value = null
    loading.value = false
    return
  }
  try {
    const nextPreflight = await getDiagnosticPreflight({
      course_id: courseId.value,
      question_count: questionCount.value,
      self_rating: selfRating.value,
    })
    if (disposed || generationStarted) return
    preflight.value = nextPreflight
  } catch (requestError) {
    error.value = messageOf(requestError)
  } finally {
    loading.value = false
  }
}

async function selectCourse() {
  if (disposed || generationStarted) return
  selectedCourseId.value = selectedCourseIds.value[0] || ''
  blueprint.value = null
  multicourseResult.value = null
  generationFailed.value = false
  if (disposed || generationStarted) return
  await loadPreflight()
}

async function toggleCourse(courseIdToToggle) {
  const current = new Set(selectedCourseIds.value)
  if (current.has(courseIdToToggle)) {
    if (current.size === 1) return
    current.delete(courseIdToToggle)
  } else {
    current.add(courseIdToToggle)
  }
  selectedCourseIds.value = courses.value.map((item) => item.id).filter((id) => current.has(id))
  await selectCourse()
}

async function generate() {
  if (!canGenerate.value) return
  generationStarted = true
  generating.value = true
  error.value = ''
  errorKind.value = 'generation'
  generationFailed.value = false
  try {
    if (multiCourse.value) {
      const result = await createMulticourseDiagnosticBlueprints({
        courseIds: selectedCourseIds.value,
        questionCount: questionCount.value,
        selfRating: selfRating.value,
        idempotencyKey: idempotencyKey(),
      })
      multicourseResult.value = result
      sessionStorage.setItem(
        `edumatrix-multicourse-run:${result.run_key || idempotencyKey()}`,
        JSON.stringify({
          blueprints: (result.items || [])
            .filter((item) => item.status === 'ready' && item.blueprint?.id)
            .map((item) => ({ id: item.blueprint.id, courseId: item.course_id, title: item.course?.title || item.course_id })),
          reports: [],
        }),
      )
      const firstReady = (result.items || []).find((item) => item.status === 'ready' && item.blueprint)
      blueprint.value = firstReady?.blueprint || null
      return
    }
    const result = await createDiagnosticBlueprint({
      course_id: courseId.value,
      question_count: questionCount.value,
      self_rating: selfRating.value,
      idempotency_key: idempotencyKey(),
    })
    blueprint.value = result.blueprint
  } catch (requestError) {
    error.value = messageOf(requestError)
    generationFailed.value = true
  } finally {
    generating.value = false
  }
}

function retryError() {
  if (errorKind.value === 'generation') return generate()
  if (courseListError.value) return loadCourses()
  return loadPreflight()
}

function recover() {
  if (profileMissing.value) {
    router.push('/onboarding')
    return
  }
  router.push({ path: '/knowledge', query: { course_id: courseId.value } })
}

function enterFirstQuestion() {
  const firstQuestion = blueprint.value?.questions?.[0]
  if (!firstQuestion) return
  router.push({
    path: '/workspace/assessment',
    query: {
      course_id: courseId.value,
      blueprint_id: blueprint.value.id,
      question_version_id: firstQuestion.id,
      ...(multicourseResult.value?.run_key ? { multi_run_id: multicourseResult.value.run_key } : {}),
    },
  })
}

function enterCourseAssessment(item) {
  const firstQuestion = item?.blueprint?.questions?.[0]
  if (!firstQuestion || !item?.blueprint?.id) return
  router.push({
    path: '/workspace/assessment',
    query: {
      course_id: item.course_id,
      blueprint_id: item.blueprint.id,
      question_version_id: firstQuestion.id,
      ...(multicourseResult.value?.run_key ? { multi_run_id: multicourseResult.value.run_key } : {}),
    },
  })
}

watch(questionCount, loadPreflight)
watch(selfRating, loadPreflight)
onMounted(loadCourses)
onBeforeUnmount(() => { disposed = true })
</script>

<template>
  <div class="entry-diagnostic" data-testid="entry-diagnostic">
    <div v-if="courseListError" class="notice notice--error" role="alert" data-testid="diagnostic-courses-error">
      <AlertCircle :size="18" />
      <span><strong>暂时无法读取可用课程</strong><small>{{ courseListError }}</small></span>
      <button type="button" title="重试课程列表" aria-label="重试课程列表" @click="loadCourses"><RefreshCw :size="17" /></button>
    </div>

    <div v-else-if="error" class="notice notice--error" role="alert" data-testid="diagnostic-error">
      <AlertCircle :size="18" />
      <span><strong>暂时无法完成这一步</strong><small>{{ error }}</small></span>
      <button type="button" title="重试" aria-label="重试" data-testid="diagnostic-error-retry" @click="retryError"><RefreshCw :size="17" /></button>
    </div>

    <div v-else-if="coursesLoading" class="loading-state" data-testid="diagnostic-courses-loading">
      <LoaderCircle class="spin" :size="22" />
      <span><strong>正在读取可用课程</strong><small>只显示你有权访问的知识库课程和当前版本</small></span>
    </div>

    <div v-else-if="loading" class="loading-state" data-testid="diagnostic-loading">
      <LoaderCircle class="spin" :size="22" />
      <span><strong>正在核对诊断条件</strong><small>读取当前课程知识库、已确认画像和可定位来源</small></span>
    </div>

    <div v-else-if="!courses.length" class="empty-state" data-testid="diagnostic-courses-empty">
      <BookOpen :size="24" />
      <strong>当前没有可用于摸底的课程</strong>
      <small>请先在知识库建立课程，或联系课程管理员开通访问权限。</small>
    </div>

    <template v-else-if="preflight">
      <section class="diagnostic-selection" data-testid="diagnostic-selection">
        <div class="selection-field">
          <span>选择学习课程</span>
          <small>课程来自你当前有权访问的知识库，可同时选择多门课程</small>
          <div class="course-choice-list" role="group" aria-label="选择入学评测课程">
            <label
              v-for="item in courses"
              :key="item.id"
              class="course-choice"
              :class="{ selected: selectedCourseIds.includes(item.id) }"
            >
              <input
                type="checkbox"
                :checked="selectedCourseIds.includes(item.id)"
                :disabled="generating"
                :aria-label="`选择课程 ${item.title}`"
                @change="toggleCourse(item.id)"
              />
              <span class="course-choice__copy">
                <strong>{{ item.title }}</strong>
                <small>{{ item.id }} · 版本 {{ item.version || '当前' }} · {{ item.sourceSummary?.readyDocuments || 0 }} 份可用资料</small>
              </span>
              <Check v-if="selectedCourseIds.includes(item.id)" :size="17" aria-hidden="true" />
            </label>
          </div>
          <small class="selection-hint">已选择 {{ selectedCourseIds.length }} 门课程：{{ selectedCourses.map((item) => item.title).join('、') || '请选择至少一门' }}</small>
        </div>
        <fieldset class="rating-field">
          <legend>自评难度起点</legend>
          <small>只用于调整出题先验，不会直接写入掌握度</small>
          <div class="rating-options">
            <label v-for="option in selfRatingOptions" :key="option.value" class="rating-option" :class="{ selected: selfRating === option.value }">
              <input v-model="selfRating" type="radio" name="diagnostic-self-rating" :value="option.value" :disabled="generating" />
              <span><strong>{{ option.label }}</strong><small>{{ option.description }}</small></span>
            </label>
          </div>
        </fieldset>
      </section>

      <section class="diagnostic-intro" aria-labelledby="diagnostic-title">
        <div class="intro-copy">
          <span class="eyebrow"><ClipboardCheck :size="15" /> 初始化评估</span>
          <h2 id="diagnostic-title">先确认你的真实学习起点</h2>
          <p>AI 将结合当前课程知识库、已确认画像和题型要求定制诊断题。结果用于生成第一版学习路径，不会与学习中的测验题资源混用。</p>
        </div>
        <div class="course-identity">
          <BookOpen :size="20" />
          <span><small>当前课程</small><strong>{{ course.title || '当前课程' }}</strong></span>
          <em>{{ courseVersionLabel }}</em>
        </div>
      </section>

      <div class="diagnostic-layout">
        <main class="diagnostic-main">
          <section v-if="!blueprint" class="overview-section" data-testid="diagnostic-overview">
            <header class="section-heading">
              <span><strong>诊断范围</strong><small>开始前可以核对题量、覆盖和画像依据</small></span>
              <label class="count-control">
                <span>题目数量</span>
                <select v-model.number="questionCount" :disabled="generating" aria-label="诊断题目数量">
                  <option :value="15">15 题</option>
                  <option :value="20">20 题</option>
                  <option :value="25">25 题</option>
                </select>
                <small v-if="preflight.questionCountAdjusted" class="count-adjustment">
                  当前课程知识点较多，将按完整覆盖生成 {{ preflight.expectedQuestionCount }} 题
                </small>
              </label>
            </header>

            <div class="metric-row">
              <article>
                <FileSearch :size="18" />
                <span><strong>{{ preflight.expectedQuestionCount }}</strong><small>预计生成题目</small></span>
              </article>
              <article>
                <Timer :size="18" />
                <span><strong>{{ estimatedMinutes }} 分钟</strong><small>预计完成时间</small></span>
              </article>
              <article>
                <Gauge :size="18" />
                <span><strong>{{ knowledgePoints.length }} 个</strong><small>覆盖知识点</small></span>
              </article>
              <article>
                <ShieldCheck :size="18" />
                <span><strong>{{ coverage.sourceCount || 0 }} 处</strong><small>可核查来源</small></span>
              </article>
            </div>

            <div class="coverage-block">
              <div class="coverage-copy">
                <strong>知识覆盖</strong>
                <small>优先覆盖不同知识点，并按画像调整难度</small>
              </div>
              <div class="knowledge-list" data-testid="diagnostic-knowledge-coverage">
                <span v-for="point in knowledgePoints" :key="point.id">{{ point.title }}</span>
              </div>
            </div>

            <div class="kind-grid" aria-label="诊断题型">
              <article v-for="(label, questionType) in typeLabels" :key="questionType">
                <span class="kind-check"><Check :size="14" /></span>
                <span><strong>{{ label }}</strong><small>{{ questionTypes[questionType] || 0 }} 道{{ blueprint ? '已生成' : '计划题' }}</small></span>
              </article>
            </div>

            <div v-if="!preflight.canGenerate" class="blocked-state" data-testid="diagnostic-blocked">
              <AlertCircle :size="20" />
              <span>
                <strong>还不能生成入学诊断</strong>
                <small v-for="blocker in preflight.blockers" :key="blocker">{{ blocker }}</small>
              </span>
              <button type="button" class="secondary-button" @click="recover">
                {{ profileMissing ? '完成学习画像' : '查看课程知识库' }} <ArrowRight :size="16" />
              </button>
            </div>

            <button
              v-else
              type="button"
              class="primary-action"
              :disabled="!canGenerate"
              data-testid="generate-diagnostic"
              @click="generate"
            >
              <LoaderCircle v-if="generating" class="spin" :size="18" />
              <ClipboardCheck v-else :size="18" />
              {{ generating ? 'AI 正在定制题组' : generationFailed ? '重试生成入学诊断' : '生成入学诊断' }}
              <ArrowRight v-if="!generating" :size="17" />
            </button>
          </section>

      <section v-else-if="multicourseResult" class="ready-section multicourse-ready" data-testid="multicourse-diagnostic-ready">
        <div class="ready-heading">
          <span class="ready-icon"><CheckCircle2 :size="24" /></span>
          <span>
            <small>多课程诊断题组已返回</small>
            <h3>{{ multicourseResult.ready_count || 0 }} 门课程可以开始作答</h3>
            <p>每门课程的题目、知识点和来源都独立冻结；失败课程可以单独重试。</p>
          </span>
        </div>
        <div class="multicourse-result-list" data-testid="multicourse-result-list">
          <article
            v-for="item in multicourseResult.items"
            :key="item.course_id"
            class="multicourse-result"
            :class="`multicourse-result--${item.status}`"
          >
            <div class="multicourse-result__heading">
              <span><strong>{{ item.course?.title || item.course_id }}</strong><small>{{ item.course_id }}</small></span>
              <CheckCircle2 v-if="item.status === 'ready'" :size="18" />
              <AlertCircle v-else :size="18" />
            </div>
            <p v-if="item.status === 'ready'">{{ item.blueprint?.questionCount || 0 }} 道题 · {{ item.blueprint?.sourceRefs?.length || 0 }} 处来源 · {{ item.blueprint?.knowledgePointCoverage?.length || 0 }} 个知识点</p>
            <p v-else>{{ errorMessageText(item.error, '本课程暂时无法生成题组。') }}</p>
            <button v-if="item.status === 'ready'" type="button" class="secondary-button" @click="enterCourseAssessment(item)">开始这门课程 <ArrowRight :size="16" /></button>
            <button v-else type="button" class="secondary-button" @click="generate">重试本轮生成 <RefreshCw :size="16" /></button>
          </article>
        </div>
        <div class="ready-actions">
          <button type="button" class="secondary-button" @click="loadPreflight"><RefreshCw :size="16" />重新核对课程</button>
          <button v-if="blueprint" type="button" class="primary-action primary-action--inline" data-testid="enter-diagnostic" @click="enterFirstQuestion">进入第一门课程 <ArrowRight :size="17" /></button>
        </div>
      </section>

      <section v-else class="ready-section" data-testid="diagnostic-ready">
            <div class="ready-heading">
              <span class="ready-icon"><CheckCircle2 :size="24" /></span>
              <span>
                <small>诊断题组已通过校验</small>
                <h3>{{ blueprint.questionCount }} 道题已准备完成</h3>
                <p>覆盖 {{ knowledgePoints.length }} 个知识点、{{ blueprint.sourceRefs.length }} 处课程来源，预计 {{ blueprint.estimatedMinutes }} 分钟。</p>
              </span>
            </div>

            <div class="ready-summary">
              <div>
                <strong>知识点</strong>
                <span>{{ knowledgePoints.map((item) => item.title).join('、') }}</span>
              </div>
              <div>
                <strong>难度分布</strong>
                <span>
                  基础 {{ blueprint.difficultyBands.difficulty.foundation }} ·
                  标准 {{ blueprint.difficultyBands.difficulty.standard }} ·
                  拓展 {{ blueprint.difficultyBands.difficulty.stretch }}
                </span>
              </div>
              <div>
                <strong>题型分布</strong>
                <span>判断 {{ questionTypes.true_false || 0 }} · 选择 {{ questionTypes.single_choice || 0 }} · 简答 {{ questionTypes.short_answer || 0 }}</span>
              </div>
              <div>
                <strong>审核结论</strong>
                <span>{{ blueprint.reviewDecision.decisionSummary }}</span>
              </div>
            </div>

            <div class="ready-actions">
              <button type="button" class="secondary-button" @click="loadPreflight"><RefreshCw :size="16" />重新核对</button>
              <button type="button" class="primary-action primary-action--inline" data-testid="enter-diagnostic" @click="enterFirstQuestion">
                进入第 1 题 <ArrowRight :size="17" />
              </button>
            </div>
          </section>
        </main>

        <aside class="audit-panel" aria-label="诊断生成依据">
          <section class="workflow-section">
            <header><ClipboardCheck :size="18" /><span><strong>摸底流程</strong><small>每一步都会保留当前课程上下文</small></span></header>
            <ol class="diagnostic-steps" data-testid="diagnostic-workflow-steps">
              <li><span>1</span><div><strong>生成测试</strong><small>结合课程、画像和自评起点出题</small></div></li>
              <li><span>2</span><div><strong>完成作答</strong><small>按题目顺序保存可恢复答案</small></div></li>
              <li><span>3</span><div><strong>提交分析</strong><small>提交后生成逐题反馈和学习路径</small></div></li>
            </ol>
          </section>
          <section>
            <header><UserRoundCheck :size="18" /><span><strong>画像依据</strong><small>不会使用未确认的临时信息</small></span></header>
            <template v-if="preflight.profileBasis">
              <dl>
                <div><dt>画像版本</dt><dd>{{ preflight.profileBasis.version }}</dd></div>
                <div><dt>来源</dt><dd>{{ preflight.profileBasis.source }}</dd></div>
                <div v-if="preflight.profileBasis.goal"><dt>学习目标</dt><dd>{{ preflight.profileBasis.goal }}</dd></div>
                <div v-if="preflight.profileBasis.foundation"><dt>基础情况</dt><dd>{{ preflight.profileBasis.foundation }}</dd></div>
              </dl>
            </template>
            <p v-else class="muted-copy">尚未找到已确认画像，完成画像后才能生成诊断。</p>
          </section>

          <section class="stage-section">
            <header><ShieldCheck :size="18" /><span><strong>AI 生成与校验</strong><small>只展示职责和结论，不展示私有推理</small></span></header>
            <ol data-testid="diagnostic-generation-stages">
              <li v-for="stage in stageItems" :key="stage.key" :class="stage.status">
                <span><Check v-if="stage.status === 'completed'" :size="14" /><LoaderCircle v-else-if="stage.status === 'processing'" class="spin" :size="14" /><AlertCircle v-else-if="stage.status === 'failed'" :size="14" />{{ stage.status === 'pending' ? '·' : '' }}</span>
                <div><strong>{{ stage.label }}</strong><small>{{ stage.status === 'completed' ? '已完成' : stage.status === 'processing' ? '处理中' : stage.status === 'failed' ? '失败，可重试' : '等待生成' }}</small></div>
              </li>
            </ol>
          </section>

          <p class="audit-boundary">普通浏览不会改变掌握度。只有后续真实作答证据才会进入学习画像和路径。</p>
        </aside>
      </div>
    </template>
  </div>
</template>

<style scoped>
.entry-diagnostic {
  width: min(1160px, 100%);
  margin: 0 auto;
  color: var(--color-text);
}

.diagnostic-intro {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 32px;
  padding: 8px 0 26px;
  border-bottom: 1px solid var(--color-border);
}

.diagnostic-selection { display: grid; grid-template-columns: minmax(240px, .8fr) minmax(0, 1.2fr); gap: 24px; padding: 22px 0; border-bottom: 1px solid var(--color-border); }
.selection-field, .rating-field { display: grid; align-content: start; gap: 6px; min-width: 0; }
.selection-field > span, .rating-field legend { padding: 0; color: var(--color-text); font-size: 15px; font-weight: 650; }
.selection-field small, .rating-field > small { color: var(--color-text-muted); font-size: 14px; line-height: 1.5; }
.selection-field select { width: 100%; min-height: 42px; margin-top: 5px; }
.course-choice-list { display: grid; gap: 8px; max-height: 224px; margin-top: 8px; overflow: auto; padding: 2px; }
.course-choice { display: grid; grid-template-columns: 18px minmax(0, 1fr) 18px; align-items: center; gap: 10px; min-width: 0; border: 1px solid var(--color-border); border-radius: var(--radius-control); background: var(--color-surface); padding: 10px 12px; cursor: pointer; }
.course-choice:hover, .course-choice.selected { border-color: var(--color-accent); background: var(--color-surface-subtle); }
.course-choice input { margin: 0; accent-color: var(--color-accent); }
.course-choice > svg { color: var(--color-accent); }
.course-choice__copy { display: grid; min-width: 0; gap: 3px; }
.course-choice__copy strong { overflow: hidden; color: var(--color-text); font-size: 15px; text-overflow: ellipsis; white-space: nowrap; }
.course-choice__copy small, .selection-hint { overflow: hidden; color: var(--color-text-muted); font-size: 14px; line-height: 1.45; text-overflow: ellipsis; white-space: nowrap; }
.selection-hint { display: block; margin-top: 5px; }
.rating-field { margin: 0; padding: 0; border: 0; }
.rating-options { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; margin-top: 6px; }
.rating-option { display: flex; min-width: 0; align-items: flex-start; gap: 8px; border: 1px solid var(--color-border); border-radius: var(--radius-control); padding: 10px; background: var(--color-surface); cursor: pointer; }
.rating-option.selected { border-color: var(--color-accent); background: var(--color-surface-subtle); }
.rating-option input { margin-top: 3px; accent-color: var(--color-accent); }
.rating-option span { display: grid; min-width: 0; gap: 3px; }
.rating-option strong { font-size: 14px; }
.rating-option small { color: var(--color-text-muted); font-size: 14px; line-height: 1.4; }

.multicourse-result-list { display: grid; gap: 10px; margin-top: 18px; }
.multicourse-result { display: grid; gap: 8px; border: 1px solid var(--color-border); border-radius: var(--radius-control); background: var(--color-surface); padding: 14px 16px; }
.multicourse-result--failed { border-color: #c7a9a4; background: #fffaf8; }
.multicourse-result__heading { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.multicourse-result__heading > span { display: grid; min-width: 0; gap: 3px; }
.multicourse-result__heading strong { overflow: hidden; font-size: 15px; text-overflow: ellipsis; white-space: nowrap; }
.multicourse-result__heading small, .multicourse-result p { margin: 0; color: var(--color-text-muted); font-size: 14px; line-height: 1.5; }
.multicourse-result__heading > svg { flex: 0 0 auto; color: var(--color-accent); }
.multicourse-result--failed .multicourse-result__heading > svg { color: #9b4e43; }
.multicourse-result .secondary-button { justify-self: start; }

.intro-copy { max-width: 680px; }
.eyebrow { display: inline-flex; align-items: center; gap: 7px; color: var(--color-accent); font-size: 14px; font-weight: 650; }
.intro-copy h2 { margin: 8px 0 7px; font-family: var(--font-display); font-size: 30px; font-weight: 650; line-height: 1.3; }
.intro-copy p { margin: 0; color: var(--color-text-secondary); font-size: 15px; line-height: 1.7; }

.course-identity { display: grid; min-width: 300px; grid-template-columns: 34px minmax(0, 1fr) auto; align-items: center; gap: 10px; padding: 13px 0 2px; }
.course-identity > svg { color: var(--color-accent); }
.course-identity span { display: grid; min-width: 0; }
.course-identity small { color: var(--color-text-muted); font-size: 14px; }
.course-identity strong { overflow: hidden; font-size: 15px; text-overflow: ellipsis; white-space: nowrap; }
.course-identity em { color: var(--color-text-muted); font-size: 14px; font-style: normal; }

.diagnostic-layout { display: grid; grid-template-columns: minmax(0, 1fr) 320px; gap: 0; min-height: 590px; }
.diagnostic-main { min-width: 0; padding: 28px 34px 28px 0; border-right: 1px solid var(--color-border); }
.audit-panel { display: grid; align-content: start; gap: 0; padding: 28px 0 28px 28px; }
.audit-panel section { padding-bottom: 24px; }
.audit-panel section + section { padding-top: 24px; border-top: 1px solid var(--color-border); }
.audit-panel header { display: flex; align-items: flex-start; gap: 10px; }
.audit-panel header > svg { margin-top: 2px; color: var(--color-accent); }
.audit-panel header span { display: grid; }
.audit-panel header strong { font-size: 15px; }
.audit-panel header small { color: var(--color-text-muted); font-size: 14px; line-height: 1.5; }
.diagnostic-steps { display: grid; gap: 12px; margin: 17px 0 0; padding: 0; list-style: none; }
.diagnostic-steps li { display: flex; align-items: flex-start; gap: 10px; }
.diagnostic-steps li > span { display: grid; width: 24px; height: 24px; flex: 0 0 24px; place-items: center; color: #ffffff; border-radius: 50%; background: #253745; font-size: 14px; font-weight: 700; }
.diagnostic-steps li > div { display: grid; gap: 2px; }
.diagnostic-steps strong { font-size: 14px; }
.diagnostic-steps small { color: var(--color-text-muted); font-size: 14px; line-height: 1.45; }

.section-heading { display: flex; align-items: center; justify-content: space-between; gap: 18px; }
.section-heading > span { display: grid; }
.section-heading strong { font-size: 18px; }
.section-heading small { color: var(--color-text-muted); font-size: 14px; }
.count-control { display: flex; align-items: center; gap: 10px; color: var(--color-text-secondary); font-size: 14px; }
.count-adjustment { max-width: 280px; color: var(--color-primary); line-height: 1.45; }
.count-control select { width: 92px; min-height: 38px; padding: 0 30px 0 12px; }

.metric-row { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); margin-top: 23px; border-top: 1px solid var(--color-border); border-bottom: 1px solid var(--color-border); }
.metric-row article { display: flex; min-width: 0; align-items: center; gap: 10px; padding: 18px 13px; }
.metric-row article + article { border-left: 1px solid var(--color-border); }
.metric-row svg { flex: 0 0 auto; color: var(--color-accent); }
.metric-row span { display: grid; }
.metric-row strong { font-size: 17px; font-variant-numeric: tabular-nums; }
.metric-row small { color: var(--color-text-muted); font-size: 14px; white-space: nowrap; }

.coverage-block { margin-top: 27px; }
.coverage-copy { display: flex; align-items: baseline; gap: 10px; }
.coverage-copy strong { font-size: 15px; }
.coverage-copy small { color: var(--color-text-muted); font-size: 14px; }
.knowledge-list { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; }
.knowledge-list span { border: 1px solid var(--color-border-strong); border-radius: var(--radius-control); padding: 6px 10px; background: var(--color-surface); font-size: 14px; }

.kind-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; margin-top: 22px; }
.kind-grid article { display: flex; align-items: center; gap: 10px; padding: 13px 0; border-top: 1px solid var(--color-border); }
.kind-grid article > span:last-child { display: grid; }
.kind-grid strong { font-size: 14px; }
.kind-grid small { color: var(--color-text-muted); font-size: 14px; }
.kind-check { display: grid; width: 25px; height: 25px; flex: 0 0 25px; place-items: center; color: #ffffff; border-radius: 50%; background: #253745; }

.primary-action, .secondary-button { display: inline-flex; min-height: 42px; align-items: center; justify-content: center; gap: 8px; border-radius: var(--radius-control); padding: 0 17px; font-size: 15px; font-weight: 650; cursor: pointer; }
.primary-action { width: 100%; margin-top: 26px; color: #ffffff; border: 1px solid #11212d; background: #11212d; }
.primary-action:hover { background: #000000; }
.primary-action:disabled { opacity: .46; cursor: not-allowed; }
.primary-action--inline { width: auto; margin: 0; }
.secondary-button { color: var(--color-text); border: 1px solid var(--color-border-strong); background: var(--color-surface); }
.secondary-button:hover { background: var(--color-surface-subtle); }

.blocked-state, .notice, .loading-state { display: flex; align-items: center; gap: 12px; border: 1px solid var(--color-border); border-radius: var(--radius-panel); padding: 15px 16px; }
.empty-state { display: grid; justify-items: center; gap: 8px; margin-top: 28px; padding: 50px 20px; color: var(--color-text-secondary); border: 1px solid var(--color-border); border-radius: var(--radius-panel); text-align: center; }
.empty-state svg { color: var(--color-accent); }
.empty-state strong { color: var(--color-text); font-size: 16px; }
.empty-state small { font-size: 14px; }
.blocked-state { margin-top: 24px; background: var(--color-surface-subtle); }
.blocked-state > svg { flex: 0 0 auto; color: var(--color-warning); }
.blocked-state > span { display: grid; min-width: 0; flex: 1; }
.blocked-state small { color: var(--color-text-secondary); font-size: 14px; }
.blocked-state .secondary-button { flex: 0 0 auto; }
.notice { margin-bottom: 18px; }
.notice > span, .loading-state > span { display: grid; flex: 1; }
.notice small, .loading-state small { color: var(--color-text-secondary); font-size: 14px; }
.notice--error { color: var(--color-danger); border-color: #e8caca; background: var(--color-danger-soft); }
.notice button { display: grid; width: 36px; height: 36px; place-items: center; border: 1px solid currentColor; border-radius: var(--radius-control); background: transparent; cursor: pointer; }
.loading-state { min-height: 150px; justify-content: center; margin-top: 40px; background: var(--color-surface-subtle); }

.audit-panel dl { display: grid; gap: 13px; margin: 18px 0 0; }
.audit-panel dl div { display: grid; gap: 3px; }
.audit-panel dt { color: var(--color-text-muted); font-size: 14px; }
.audit-panel dd { margin: 0; color: var(--color-text-secondary); font-size: 14px; line-height: 1.55; overflow-wrap: anywhere; }
.muted-copy, .audit-boundary { color: var(--color-text-muted); font-size: 14px; line-height: 1.6; }
.audit-boundary { margin: 0; padding-top: 20px; border-top: 1px solid var(--color-border); }

.stage-section ol { display: grid; gap: 0; margin: 18px 0 0; padding: 0; list-style: none; }
.stage-section li { display: grid; min-height: 52px; grid-template-columns: 28px minmax(0, 1fr); gap: 9px; align-items: start; }
.stage-section li > span { display: grid; width: 25px; height: 25px; place-items: center; color: var(--color-text-muted); border: 1px solid var(--color-border-strong); border-radius: 50%; background: var(--color-surface); }
.stage-section li.completed > span { color: #ffffff; border-color: #253745; background: #253745; }
.stage-section li.processing > span { color: var(--color-accent); border-color: var(--color-accent); }
.stage-section li div { display: grid; padding-bottom: 13px; }
.stage-section li strong { font-size: 14px; }
.stage-section li small { color: var(--color-text-muted); font-size: 14px; }

.ready-heading { display: flex; align-items: flex-start; gap: 16px; padding-bottom: 25px; border-bottom: 1px solid var(--color-border); }
.ready-icon { display: grid; width: 44px; height: 44px; flex: 0 0 44px; place-items: center; color: #ffffff; border-radius: 50%; background: #253745; }
.ready-heading > span:last-child { display: grid; }
.ready-heading small { color: var(--color-accent); font-size: 14px; font-weight: 650; }
.ready-heading h3 { margin: 4px 0 5px; font-family: var(--font-display); font-size: 26px; font-weight: 650; }
.ready-heading p { margin: 0; color: var(--color-text-secondary); font-size: 15px; }
.ready-summary { display: grid; margin-top: 8px; }
.ready-summary > div { display: grid; grid-template-columns: 110px minmax(0, 1fr); gap: 16px; padding: 17px 0; border-bottom: 1px solid var(--color-border); }
.ready-summary strong { font-size: 14px; }
.ready-summary span { color: var(--color-text-secondary); font-size: 14px; line-height: 1.6; }
.ready-actions { display: flex; justify-content: flex-end; gap: 10px; margin-top: 24px; }

.spin { animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }

@media (max-width: 1220px) {
  .diagnostic-layout { grid-template-columns: minmax(0, 1fr) 290px; }
  .metric-row article { padding-inline: 9px; }
}

@media (max-width: 860px) {
  .diagnostic-selection { grid-template-columns: 1fr; }
  .rating-options { grid-template-columns: 1fr; }
  .diagnostic-intro { align-items: flex-start; flex-direction: column; }
  .course-identity { width: 100%; min-width: 0; }
  .diagnostic-layout { grid-template-columns: 1fr; }
  .diagnostic-main { padding-right: 0; border-right: 0; }
  .audit-panel { padding-left: 0; }
}
</style>
