<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  ArrowLeft,
  Ban,
  BookMarked,
  CheckCircle2,
  ExternalLink,
  FileSearch,
  FileText,
  Globe2,
  RotateCw,
  Search,
  ShieldAlert,
  XCircle,
} from '@lucide/vue'
import TaskState from '../components/TaskState.vue'
import SearchField from '../components/ui/SearchField.vue'
import {
  admitWebSourceCandidate,
  discoverKnowledgeMaterials,
  listKnowledgeCourseShelf,
  listWebSourceCandidates,
  rejectWebSourceCandidate,
  saveWebSourceCandidate,
  withdrawWebSourceCandidate,
} from '../api/knowledge'
import { errorMessageText } from '../api/common'
import { selectableCourseOptions } from '../utils/assessmentConfiguration'

const route = useRoute()
const router = useRouter()

const query = ref(String(route.query.q || ''))
const activeView = ref('results')
const searchStatus = ref('idle')
const searchError = ref('')
const searchResults = ref([])
const searchBoundary = ref('')
const filteredResultCount = ref(0)
const searchQueryUsed = ref('')
const queryPlan = ref(null)
const profileBasis = ref(null)
const rankingSummary = ref(null)
const candidatesStatus = ref('loading')
const candidatesError = ref('')
const candidates = ref([])
const selectedItem = ref(null)
const selectedKind = ref('')
const formatFilter = ref('all')
const licenseFilter = ref('all')
const reviewFilter = ref('all')
const busyAction = ref('')
const actionError = ref('')
const actionNotice = ref('')
const courseOptions = ref([])
const courseCatalog = ref([])
const courseStatus = ref('loading')
const contextCourseId = ref(String(route.query.course_id || ''))
const profileSnapshotId = ref(String(route.query.profile_snapshot_id || ''))

const admissionForm = reactive({
  course_id: '',
  author_or_organization: '',
  license_status: 'unknown',
  license_text: '',
  usage_hint: '',
  trust_level: 'unverified',
})

const allowedLicenses = new Set(['personal_use_allowed', 'open_permissive'])

const contextCourseOptions = computed(() => {
  const all = [...courseCatalog.value, ...courseOptions.value]
  const seen = new Set()
  return all.filter((course) => {
    if (!course?.id || seen.has(course.id)) return false
    seen.add(course.id)
    return true
  })
})

const selectedContextCourse = computed(() => (
  contextCourseOptions.value.find((course) => course.id === contextCourseId.value) || null
))

const formatOptions = computed(() => {
  const values = new Set([
    ...searchResults.value.map((item) => item.fileFormat),
    ...candidates.value.map((item) => item.fileFormat),
  ].filter(Boolean))
  return [...values].sort()
})

const visibleSearchResults = computed(() => searchResults.value.filter(matchesFilters))
const visibleCandidates = computed(() => candidates.value.filter((item) => (
  matchesFilters(item)
  && (reviewFilter.value === 'all' || item.reviewStatus === reviewFilter.value)
)))

const activeItems = computed(() => (
  activeView.value === 'results' ? visibleSearchResults.value : visibleCandidates.value
))

const selectedCandidate = computed(() => (
  selectedKind.value === 'candidate' ? selectedItem.value : null
))

const canSubmitAdmission = computed(() => {
  const candidate = selectedCandidate.value
  return Boolean(
    candidate
    && ['pending_review', 'license_required'].includes(candidate.reviewStatus)
    && admissionForm.course_id
    && allowedLicenses.has(admissionForm.license_status)
    && admissionForm.usage_hint.trim(),
  )
})

const canReject = computed(() => (
  selectedCandidate.value
  && ['pending_review', 'license_required'].includes(selectedCandidate.value.reviewStatus)
))
const authorityBoundaryText = computed(() => (
  selectedKind.value === 'candidate'
    ? (selectedItem.value?.reviewStatus === 'imported'
        ? '该资料已经完成原站下载、解析和课程归属；来源和许可信息与资料一起保留。'
        : '候选资料尚未进入课程、图谱或检索；只有实际下载和解析成功后才会改变状态。')
    : (searchBoundary.value || '搜索结果只供来源核验，未经保存和审核不会进入课程或资源生成。')
))

const parsingEntries = computed(() => {
  const impact = selectedItem.value?.parsingImpact
  if (!impact || typeof impact !== 'object') return []
  return Object.entries(impact)
    .filter(([key]) => !['summary', 'pipeline'].includes(key))
    .map(([key, value]) => ({ key, label: parsingLabel(key), value: parsingValue(value) }))
})

const pipelineEntries = computed(() => {
  const pipeline = selectedItem.value?.processingPipeline
  if (!pipeline || typeof pipeline !== 'object') return []
  return ['download', 'parse', 'citation', 'admission']
    .map((key) => ({ key, ...(pipeline[key] || {}) }))
})

function matchesFilters(item) {
  return (formatFilter.value === 'all' || item.fileFormat === formatFilter.value)
    && (licenseFilter.value === 'all' || item.licenseStatus === licenseFilter.value)
}

function errorMessage(error, fallback) {
  return errorMessageText(
    error?.response?.data?.detail ?? error?.detail ?? error?.message,
    fallback,
  )
}

function statusLabel(status) {
  return {
    not_saved: '尚未保存',
    pending_review: '待核验',
    license_required: '许可待补全',
    imported: '已导入课程',
    rejected: '已拒绝',
    withdrawn: '已撤回',
  }[status] || status || '未知状态'
}

function processingStatusLabel(status) {
  return {
    candidate: '候选待处理',
    in_progress: '处理中',
    failed: '处理失败，可重试',
    admitted: '已准入且可引用',
  }[status] || status || '待确认'
}

function stageLabel(stage) {
  return {
    download: '下载',
    parse: '解析',
    citation: '可引用',
    admission: '课程准入',
  }[stage] || stage
}

function stageStatusLabel(status) {
  return {
    not_started: '未开始',
    pending: '等待',
    in_progress: '进行中',
    completed: '已完成',
    ready: '已就绪',
    blocked: '等待前置阶段',
    failed: '失败，可重试',
    revoked: '已撤回',
    admitted: '已准入',
    candidate: '候选中',
    rejected: '已拒绝',
    withdrawn: '已撤回',
  }[status] || status || '未知'
}

function licenseLabel(status) {
  return {
    unknown: '许可未核验',
    restricted: '限制使用',
    personal_use_allowed: '允许个人学习使用',
    open_permissive: '开放许可',
  }[status] || status || '许可未提供'
}

function trustLabel(level) {
  return {
    unverified: '尚未核验',
    source_declared: '依据原站声明',
  }[level] || level || '尚未核验'
}

function formatLabel(format) {
  return String(format || 'html').toUpperCase()
}

function parsingLabel(key) {
  return {
    text: '正文',
    images: '图片',
    tables: '表格',
    formulas: '公式',
    code: '代码',
    outputs: '运行输出',
    metadata: '媒体信息',
    transcript: '转写',
  }[key] || key
}

function parsingValue(value) {
  if (value === true) return '可解析'
  if (value === false) return '暂不解析'
  if (value === 'best_effort') return '尽力解析，需复核'
  if (value === 'metadata_only') return '仅元数据，不作为正文'
  if (value === 'metadata_and_authorized_ocr') return '图片地址/说明，授权后 OCR'
  if (value === 'when_authorized') return '取得授权后可用'
  if (value === 'when_available') return '有字幕时可用'
  if (value === 'pending_download') return '下载后确认'
  if (value === 'not_guaranteed') return '不保证'
  if (value === 'not_applicable') return '不适用'
  return String(value || '未说明')
}

function resetFeedback() {
  actionError.value = ''
  actionNotice.value = ''
}

function selectResult(item) {
  selectedKind.value = 'result'
  selectedItem.value = item
  resetFeedback()
}

function fillAdmissionForm(candidate) {
  if (!admissionForm.course_id) admissionForm.course_id = courseOptions.value[0]?.id || ''
  admissionForm.author_or_organization = candidate.authorOrOrganization === '原站未提供'
    ? ''
    : (candidate.authorOrOrganization || '')
  admissionForm.license_status = candidate.licenseStatus || 'unknown'
  admissionForm.license_text = candidate.licenseText || ''
  admissionForm.usage_hint = candidate.usageHint || ''
  admissionForm.trust_level = candidate.trustLevel || 'unverified'
}

function selectCandidate(candidate) {
  selectedKind.value = 'candidate'
  selectedItem.value = candidate
  fillAdmissionForm(candidate)
  resetFeedback()
}

function replaceCandidate(candidate) {
  const index = candidates.value.findIndex((item) => item.id === candidate.id)
  if (index === -1) candidates.value.unshift(candidate)
  else candidates.value.splice(index, 1, candidate)
  selectCandidate(candidate)
}

async function searchMaterials() {
  const normalized = query.value.trim()
  if (normalized.length < 2) {
    searchStatus.value = 'failed'
    searchError.value = '请输入至少两个字的教材或课程主题。'
    return
  }
  searchStatus.value = 'searching'
  searchError.value = ''
  // Keep the exact user-entered query visible even when query generation or
  // every remote provider fails; the retry action submits this same value.
  searchQueryUsed.value = normalized
  resetFeedback()
  try {
    const payload = await discoverKnowledgeMaterials(normalized, 8, {
      courseId: contextCourseId.value,
      profileSnapshotId: profileSnapshotId.value,
    })
    searchResults.value = payload.items || []
    searchBoundary.value = payload.authorityBoundary || ''
    filteredResultCount.value = Number(payload.filteredResultCount || 0)
    searchQueryUsed.value = payload.generatedQuery || payload.query || normalized
    queryPlan.value = payload.queryPlan || null
    profileBasis.value = payload.profileBasis || null
    rankingSummary.value = payload.ranking || null
    searchStatus.value = payload.status === 'provider_failed'
      ? 'failed'
      : (searchResults.value.length ? 'ready' : 'empty')
    searchError.value = payload.status === 'provider_failed'
      ? (payload.message || '联网搜索暂时不可用，搜索词和已有候选已保留。')
      : ''
    activeView.value = 'results'
    selectedKind.value = searchResults.value.length ? 'result' : ''
    selectedItem.value = searchResults.value[0] || null
  } catch (error) {
    searchStatus.value = 'failed'
    searchError.value = errorMessage(error, '联网发现暂时不可用，搜索词和已有候选已保留。')
  }
}

async function loadCandidates({ keepFeedback = false } = {}) {
  candidatesStatus.value = 'loading'
  candidatesError.value = ''
  try {
    const payload = await listWebSourceCandidates()
    candidates.value = payload.items || []
    candidatesStatus.value = candidates.value.length ? 'ready' : 'empty'
    if (selectedCandidate.value) {
      const fresh = candidates.value.find((item) => item.id === selectedCandidate.value.id)
      if (fresh) {
        selectedItem.value = fresh
      }
    }
  } catch (error) {
    candidatesStatus.value = 'failed'
    candidatesError.value = errorMessage(error, '候选来源暂时无法读取。')
  }
}

async function loadCourses() {
  courseStatus.value = 'loading'
  try {
    const payload = await listKnowledgeCourseShelf()
    const selectable = selectableCourseOptions(payload)
    courseCatalog.value = selectable
    courseOptions.value = selectable.filter(course => course.can_manage)
    if (contextCourseId.value && !selectable.some((course) => String(course.id) === String(contextCourseId.value))) {
      contextCourseId.value = ''
    }
    if (!contextCourseId.value) {
      contextCourseId.value = payload.shelf?.[0]?.id || payload.recommendations?.[0]?.id || ''
    }
    admissionForm.course_id = courseOptions.value.some(course => course.id === admissionForm.course_id)
      ? admissionForm.course_id
      : courseOptions.value[0]?.id || ''
    courseStatus.value = courseOptions.value.length ? 'ready' : 'empty'
  } catch (error) {
    courseOptions.value = []
    courseStatus.value = 'failed'
  }
}

async function saveCandidate(result) {
  busyAction.value = `save:${result.url}`
  resetFeedback()
  try {
    const payload = await saveWebSourceCandidate({
      query: searchQueryUsed.value || query.value.trim(),
      title: result.title,
      url: result.url,
      snippet: result.snippet || '',
    })
    replaceCandidate(payload.candidate)
    activeView.value = 'candidates'
    actionNotice.value = payload.created
      ? '已保存到候选区。请核对许可与用途后再决定是否准入。'
      : '该原站地址已在候选区，已打开现有记录。'
    candidatesStatus.value = 'ready'
  } catch (error) {
    actionError.value = errorMessage(error, '保存候选失败，搜索结果仍保留。')
  } finally {
    busyAction.value = ''
  }
}

async function admitCandidate() {
  const candidate = selectedCandidate.value
  if (!candidate || !canSubmitAdmission.value) return
  busyAction.value = `admit:${candidate.id}`
  resetFeedback()
  try {
    const payload = await admitWebSourceCandidate(candidate.id, { ...admissionForm })
    replaceCandidate(payload.candidate)
    actionNotice.value = payload.document?.duplicate
      ? '该资料已在目标课程中，本次未重复导入。'
      : '资料已从原站下载、解析并加入目标课程。'
  } catch (error) {
    actionError.value = errorMessage(error, '准入失败。已填写的核验信息仍保留在页面中。')
    await loadCandidates({ keepFeedback: true })
  } finally {
    busyAction.value = ''
  }
}

async function rejectCandidate() {
  const candidate = selectedCandidate.value
  if (!candidate || !canReject.value) return
  busyAction.value = `reject:${candidate.id}`
  resetFeedback()
  try {
    const payload = await rejectWebSourceCandidate(candidate.id)
    replaceCandidate(payload.candidate)
    actionNotice.value = '候选已拒绝，未进入任何课程或资源生成范围。'
  } catch (error) {
    actionError.value = errorMessage(error, '拒绝候选失败，请稍后重试。')
  } finally {
    busyAction.value = ''
  }
}

async function withdrawCandidate() {
  const candidate = selectedCandidate.value
  if (!candidate || candidate.reviewStatus !== 'imported') return
  busyAction.value = `withdraw:${candidate.id}`
  resetFeedback()
  try {
    const payload = await withdrawWebSourceCandidate(candidate.id)
    replaceCandidate(payload.candidate)
    actionNotice.value = '候选审核记录已撤回。已导入的课程资料不会被自动删除。'
  } catch (error) {
    actionError.value = errorMessage(error, '撤回失败，请稍后重试。')
  } finally {
    busyAction.value = ''
  }
}

function switchView(view) {
  activeView.value = view
  selectedItem.value = null
  selectedKind.value = ''
  resetFeedback()
}

onMounted(() => Promise.all([loadCandidates(), loadCourses()]))
</script>

<template>
  <main class="discovery-workspace" data-testid="knowledge-discovery-workspace">
    <header class="workspace-header">
      <button type="button" class="back-action" @click="router.push('/knowledge')">
        <ArrowLeft :size="18" aria-hidden="true" />返回知识库
      </button>
      <div class="workspace-header__copy">
        <h1>教材与来源发现</h1>
        <p>先搜索真实原站，再保存为候选并核对许可。只有原文真实下载、解析成功后，才会显示为已导入。</p>
      </div>
      <button type="button" class="secondary-action" :disabled="candidatesStatus === 'loading'" @click="loadCandidates">
        <RotateCw :size="17" aria-hidden="true" />刷新候选
      </button>
    </header>

    <form class="search-panel" role="search" @submit.prevent="searchMaterials">
      <label for="material-search">查找教材、课程讲义或公开学习资料</label>
      <div class="discovery-context-grid">
        <label class="context-field" for="discovery-course-select">
          <span>当前课程（用于画像驱动推荐）</span>
          <select id="discovery-course-select" v-model="contextCourseId" data-testid="discovery-course-select" :disabled="courseStatus === 'loading'">
            <option value="">{{ courseStatus === 'loading' ? '正在读取课程' : '不指定课程' }}</option>
            <option v-for="course in contextCourseOptions" :key="course.id" :value="course.id">{{ course.title }}</option>
          </select>
        </label>
        <div class="context-summary">
          <span>推荐依据</span>
          <strong v-if="profileBasis?.status === 'available'">当前画像快照：课程目标、学习目标和薄弱方向</strong>
          <strong v-else-if="profileBasis?.status === 'missing'">尚无画像快照，将保留用户搜索词并明确提示</strong>
          <strong v-else>{{ selectedContextCourse?.title || '搜索前选择课程' }}</strong>
          <small v-if="profileSnapshotId">画像版本：{{ profileSnapshotId }}</small>
        </div>
      </div>
      <div class="search-row">
        <SearchField
          id="material-search"
          v-model="query"
          autocomplete="off"
          placeholder="例如：机器学习基础 公开课程讲义"
          aria-label="查找教材、课程讲义或公开学习资料"
          class="discovery-search-field"
          data-testid="discovery-search-input"
        />
        <button
          type="submit"
          class="search-submit"
          :class="{ 'search-submit--secondary': activeView === 'candidates' }"
          :disabled="searchStatus === 'searching'"
          data-testid="discovery-search-submit"
        >
          <RotateCw v-if="searchStatus === 'searching'" :size="17" class="spin" aria-hidden="true" />
          <Search v-else :size="17" aria-hidden="true" />
          {{ searchStatus === 'searching' ? '正在搜索' : '联网搜索' }}
        </button>
      </div>
      <p>搜索仅返回带 HTTP(S) 原站地址的结果。未核验许可的资料只能保存到候选区。</p>
    </form>

    <section v-if="queryPlan || profileBasis" class="query-plan-card" data-testid="discovery-query-plan" aria-label="画像联网推荐依据">
      <div class="query-plan-heading">
        <div>
          <span>画像驱动联网推荐</span>
          <h2>{{ profileBasis?.status === 'available' ? '已按当前课程画像生成搜索词' : '当前没有可用画像快照' }}</h2>
        </div>
        <span class="query-plan-status">{{ rankingSummary?.scoredCount || 0 }} 条候选 · 去重 {{ rankingSummary?.deduplicatedCount || 0 }} 条</span>
      </div>
      <dl class="query-plan-facts">
        <div><dt>实际搜索词</dt><dd>{{ queryPlan?.query || searchQueryUsed || query }}</dd></div>
        <div><dt>关注方向</dt><dd>{{ queryPlan?.focus_terms?.join('、') || '未形成画像关注词' }}</dd></div>
        <div><dt>课程</dt><dd>{{ profileBasis?.courseTitle || selectedContextCourse?.title || '未指定' }}</dd></div>
        <div><dt>模型</dt><dd>{{ queryPlan?.model?.model || '未调用（画像缺失）' }}<span v-if="queryPlan?.model"> · reasoning max</span></dd></div>
      </dl>
      <p class="query-plan-rationale">{{ queryPlan?.rationale || '画像快照缺失时不把普通搜索伪装成画像推荐；完成画像后可重新搜索。' }}</p>
    </section>

    <TaskState
      v-if="searchStatus === 'failed'"
      state="error"
      title="联网搜索没有完成"
      :message="searchError"
      action-label="使用原搜索词重试"
      @action="searchMaterials"
    />
    <TaskState
      v-else-if="searchStatus === 'empty'"
      state="info"
      title="没有找到带真实原站地址的结果"
      :message="filteredResultCount ? `已过滤 ${filteredResultCount} 条无法核验原站的结果，可更换关键词重试。` : '可增加课程名称、学校或资料格式后重试。'"
    />

    <section class="source-toolbar" aria-label="发现结果与候选筛选">
      <div class="view-switch" role="tablist" aria-label="资料状态">
        <button
          type="button"
          role="tab"
          :aria-selected="activeView === 'results'"
          @click="switchView('results')"
        >搜索结果 <span>{{ searchResults.length }}</span></button>
        <button
          type="button"
          role="tab"
          :aria-selected="activeView === 'candidates'"
          @click="switchView('candidates')"
        >我的候选 <span>{{ candidates.length }}</span></button>
      </div>
      <label>
        <span>格式</span>
        <select v-model="formatFilter" data-testid="discovery-format-filter">
          <option value="all">全部格式</option>
          <option v-for="format in formatOptions" :key="format" :value="format">{{ formatLabel(format) }}</option>
        </select>
      </label>
      <label>
        <span>许可</span>
        <select v-model="licenseFilter" data-testid="discovery-license-filter">
          <option value="all">全部许可</option>
          <option value="unknown">未核验</option>
          <option value="restricted">限制使用</option>
          <option value="personal_use_allowed">个人学习可用</option>
          <option value="open_permissive">开放许可</option>
        </select>
      </label>
      <label v-if="activeView === 'candidates'">
        <span>审核状态</span>
        <select v-model="reviewFilter" data-testid="discovery-review-filter">
          <option value="all">全部状态</option>
          <option value="pending_review">待核验</option>
          <option value="license_required">许可待补全</option>
          <option value="imported">已准入个人参考</option>
          <option value="rejected">已拒绝</option>
          <option value="withdrawn">已撤回</option>
        </select>
      </label>
      <span class="result-count">{{ activeItems.length }} 条</span>
    </section>

    <div class="discovery-layout" data-testid="discovery-list-preview-layout">
      <section class="source-results" :aria-label="activeView === 'results' ? '联网搜索结果' : '我的候选来源'">
        <TaskState
          v-if="activeView === 'candidates' && candidatesStatus === 'loading'"
          state="loading"
          title="正在读取候选来源"
          message="已保存的搜索词和审核状态不会改变。"
        />
        <TaskState
          v-else-if="activeView === 'candidates' && candidatesStatus === 'failed'"
          state="error"
          title="候选来源暂时无法读取"
          :message="candidatesError"
          action-label="重新读取"
          @action="loadCandidates"
        />
        <div v-else-if="activeView === 'results' && searchStatus === 'idle'" class="list-empty">
          <FileSearch :size="26" aria-hidden="true" />
          <strong>输入主题开始查找</strong>
          <span>搜索结果先供检查，不会自动加入书架或课程知识库。</span>
        </div>
        <div v-else-if="activeItems.length === 0" class="list-empty">
          <FileText :size="26" aria-hidden="true" />
          <strong>{{ activeView === 'results' ? '当前筛选没有结果' : '当前没有符合条件的候选' }}</strong>
          <span>调整格式、许可或审核状态即可查看其他资料。</span>
        </div>
        <ol v-else class="source-list">
          <li v-for="item in activeItems" :key="item.id || item.url">
            <div
              class="source-row"
              :class="{ 'source-row--active': selectedItem === item }"
            >
              <button
                type="button"
                class="source-select"
                @click="activeView === 'results' ? selectResult(item) : selectCandidate(item)"
              >
                <span class="source-icon"><FileText :size="19" aria-hidden="true" /></span>
                <span class="source-copy">
                  <strong>{{ item.title }}</strong>
                  <span>{{ item.authorOrOrganization || item.sourceDomain || '原站未提供机构' }} · {{ formatLabel(item.fileFormat) }}</span>
                  <small>{{ item.snippet || '原站没有提供摘要，请打开原站核对内容。' }}</small>
                  <small v-if="activeView === 'results'" class="source-relevance">相关度 {{ Math.round(Number(item.relevanceScore || 0) * 100) }}% · {{ item.recommendationReason || '候选仍需核对来源和许可。' }}</small>
                </span>
              </button>
              <span class="source-state">
                <span class="status-badge" :data-status="item.reviewStatus">{{ statusLabel(item.reviewStatus) }}</span>
                <span v-if="activeView === 'candidates'" class="processing-badge" :data-status="item.processingStatus">
                  {{ processingStatusLabel(item.processingStatus) }}
                </span>
                <button
                  v-if="activeView === 'results'"
                  type="button"
                  class="save-candidate"
                  :disabled="busyAction === `save:${item.url}`"
                  @click.stop="saveCandidate(item)"
                >
                  <BookMarked :size="16" aria-hidden="true" />
                  {{ busyAction === `save:${item.url}` ? '保存中' : '保存为候选' }}
                </button>
              </span>
            </div>
          </li>
        </ol>
      </section>

      <aside class="source-preview" data-testid="discovery-source-preview">
        <div v-if="!selectedItem" class="preview-empty">
          <Globe2 :size="28" aria-hidden="true" />
          <h2>查看来源证据</h2>
          <p>选择左侧资料后，这里会显示原站、格式、许可、用途和解析影响。</p>
        </div>

        <template v-else>
          <header class="preview-header">
            <div>
              <span>{{ selectedKind === 'candidate' ? statusLabel(selectedItem.reviewStatus) : '联网搜索结果' }}</span>
              <h2>{{ selectedItem.title }}</h2>
            </div>
            <a :href="selectedItem.url" target="_blank" rel="noopener noreferrer">
              打开原站<ExternalLink :size="15" aria-hidden="true" />
            </a>
          </header>

          <dl class="source-facts">
            <div><dt>原站</dt><dd>{{ selectedItem.sourceDomain || '原站未提供' }}</dd></div>
            <div><dt>作者或机构</dt><dd>{{ selectedItem.authorOrOrganization || '原站未提供' }}</dd></div>
            <div><dt>资料格式</dt><dd>{{ formatLabel(selectedItem.fileFormat) }}</dd></div>
            <div><dt>识别方式</dt><dd>{{ selectedItem.formatDetection || '等待下载确认' }} · {{ selectedItem.formatConfidence || '未知置信度' }}</dd></div>
            <div><dt>许可状态</dt><dd>{{ licenseLabel(selectedItem.licenseStatus) }}</dd></div>
            <div><dt>可信等级</dt><dd>{{ trustLabel(selectedItem.trustLevel) }}</dd></div>
            <div><dt>审核状态</dt><dd>{{ statusLabel(selectedItem.reviewStatus) }}</dd></div>
            <div v-if="selectedKind === 'result'"><dt>画像相关度</dt><dd>{{ Math.round(Number(selectedItem.relevanceScore || 0) * 100) }}% · {{ selectedItem.recommendationReason || '候选仍需核对来源和许可。' }}</dd></div>
            <div v-if="selectedKind === 'candidate'"><dt>处理状态</dt><dd>{{ processingStatusLabel(selectedItem.processingStatus) }}</dd></div>
            <div v-if="selectedKind === 'candidate'"><dt>可引用状态</dt><dd>{{ stageStatusLabel(selectedItem.citationStatus) }}</dd></div>
          </dl>

          <section class="evidence-section">
            <h3>用途提示</h3>
            <p>{{ selectedItem.usageHint || '尚未核验允许用途，当前资料不能准入。' }}</p>
          </section>
          <section class="evidence-section">
            <h3>解析影响</h3>
            <p>{{ selectedItem.parsingImpact?.summary || '原站没有提供可解析范围。' }}</p>
            <ul v-if="parsingEntries.length" class="parsing-list">
              <li v-for="entry in parsingEntries" :key="entry.key"><span>{{ entry.label }}</span><strong>{{ entry.value }}</strong></li>
            </ul>
          </section>

          <section v-if="selectedKind === 'candidate' && pipelineEntries.length" class="evidence-section">
            <h3>下载、解析与准入阶段</h3>
            <ol class="pipeline-list">
              <li v-for="entry in pipelineEntries" :key="entry.key" :data-status="entry.status">
                <div><strong>{{ stageLabel(entry.key) }}</strong><span>{{ stageStatusLabel(entry.status) }}</span></div>
                <p>{{ entry.message || '暂无阶段说明。' }}</p>
                <small v-if="entry.code">错误码：{{ entry.code }}</small>
              </li>
            </ol>
          </section>

          <section v-if="selectedKind === 'candidate'" class="admission-section">
            <div class="section-heading">
              <div><h3>来源核验与导入</h3><p>选择个人课程，核对许可后实际下载和解析。</p></div>
              <ShieldAlert :size="20" aria-hidden="true" />
            </div>

            <div v-if="selectedItem.blockers?.length" class="blocker-list" role="status">
              <strong>当前不能准入</strong>
              <span v-for="blocker in selectedItem.blockers" :key="blocker">{{ blocker }}</span>
            </div>

            <div v-if="['pending_review', 'license_required'].includes(selectedItem.reviewStatus)" class="admission-form">
              <label>
                <span>目标学习课程</span>
                <select v-model="admissionForm.course_id" data-testid="candidate-course-select" :disabled="courseStatus !== 'ready'">
                  <option value="">{{ courseStatus === 'loading' ? '正在读取课程' : courseStatus === 'empty' ? '请先在知识库新建课程' : '选择课程' }}</option>
                  <option v-for="course in courseOptions" :key="course.id" :value="course.id">{{ course.title }}</option>
                </select>
              </label>
              <label>
                <span>作者或机构</span>
                <input v-model="admissionForm.author_or_organization" type="text" placeholder="按原站署名填写" />
              </label>
              <label>
                <span>许可状态</span>
                <select v-model="admissionForm.license_status" data-testid="candidate-license-select">
                  <option value="unknown">尚未核验</option>
                  <option value="restricted">限制使用，仅保留原站</option>
                  <option value="personal_use_allowed">允许个人学习使用</option>
                  <option value="open_permissive">开放许可</option>
                </select>
              </label>
              <label>
                <span>许可原文或名称</span>
                <textarea v-model="admissionForm.license_text" rows="2" placeholder="例如：CC BY 4.0；找不到时保持为空并选择尚未核验" />
              </label>
              <label>
                <span>允许用途</span>
                <textarea v-model="admissionForm.usage_hint" rows="3" placeholder="说明是否允许个人学习引用、下载、改编，以及需要保留的署名" />
              </label>
              <label>
                <span>可信等级</span>
                <select v-model="admissionForm.trust_level">
                  <option value="unverified">尚未核验</option>
                  <option value="source_declared">依据原站声明</option>
                </select>
              </label>
            </div>

            <div v-if="actionError" class="action-feedback action-feedback--error" role="alert">
              <TaskState state="error" title="操作没有完成" :message="actionError" />
              <button
                v-if="selectedItem.retryable && canSubmitAdmission"
                type="button"
                class="retry-action"
                :disabled="busyAction === `admit:${selectedItem.id}`"
                @click="admitCandidate"
              >
                <RotateCw :size="16" aria-hidden="true" />重新下载并解析
              </button>
            </div>
            <TaskState v-else-if="actionNotice" state="success" title="状态已更新" :message="actionNotice" />

            <div v-if="['pending_review', 'license_required'].includes(selectedItem.reviewStatus)" class="admission-actions">
              <button
                type="button"
                class="admit-action"
                :disabled="!canSubmitAdmission || busyAction === `admit:${selectedItem.id}`"
                data-testid="candidate-admit"
                @click="admitCandidate"
              >
                <CheckCircle2 :size="17" aria-hidden="true" />
                {{ busyAction === `admit:${selectedItem.id}` ? '正在下载与解析' : '导入目标课程' }}
              </button>
              <p v-if="!canSubmitAdmission">请选择允许使用的许可并填写用途说明。</p>
              <button v-if="canReject" type="button" class="reject-action" @click="rejectCandidate">
                <XCircle :size="16" aria-hidden="true" />拒绝该候选
              </button>
            </div>
            <div v-else-if="selectedItem.reviewStatus === 'imported'" class="admission-actions">
              <div class="imported-version"><CheckCircle2 :size="17" /><span>已导入课程 · {{ selectedItem.importedVersion }}</span></div>
              <button type="button" class="withdraw-action" @click="withdrawCandidate">
                <Ban :size="16" aria-hidden="true" />撤回个人参考
              </button>
            </div>
          </section>

          <div class="authority-boundary">
            <ShieldAlert :size="18" aria-hidden="true" />
            <p>{{ authorityBoundaryText }}</p>
          </div>
        </template>
      </aside>
    </div>
  </main>
</template>

<style scoped>
.discovery-workspace {
  display: grid;
  min-width: 0;
  gap: 18px;
  padding: 24px;
  color: var(--color-text);
  background: var(--color-page);
}

.workspace-header {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  align-items: start;
  gap: 18px;
}

.workspace-header__copy h1,
.workspace-header__copy p,
.preview-header h2,
.evidence-section h3,
.evidence-section p,
.section-heading h3,
.section-heading p,
.preview-empty h2,
.preview-empty p { margin: 0; }

.workspace-header__copy h1 { font-size: 24px; line-height: 1.35; font-weight: 650; }
.workspace-header__copy p { max-width: 72ch; margin-top: 5px; color: var(--color-text-secondary); font-size: 15px; }

.back-action,
.secondary-action,
.search-submit,
.view-switch button,
.save-candidate,
.admit-action,
.reject-action,
.withdraw-action,
.preview-header a {
  display: inline-flex;
  min-height: 40px;
  align-items: center;
  justify-content: center;
  gap: 7px;
  border-radius: var(--radius-control);
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
}

.back-action,
.secondary-action { padding: 0 13px; color: var(--color-text-secondary); border: 1px solid var(--color-border-strong); background: var(--color-surface); }
.back-action:hover,
.secondary-action:hover { color: var(--color-text); background: var(--color-surface-subtle); }
.secondary-action:disabled { opacity: .5; cursor: not-allowed; }

.search-panel { display: grid; gap: 8px; padding: 16px; border: 1px solid var(--color-border); border-radius: var(--radius-panel); background: var(--color-surface); }
.search-panel > label { color: var(--color-text); font-size: 15px; font-weight: 650; }
.search-panel > p { margin: 0; color: var(--color-text-muted); font-size: 14px; }
.discovery-context-grid { display: grid; grid-template-columns: minmax(260px, .8fr) minmax(0, 1.2fr); gap: 14px; align-items: end; padding: 12px; border: 1px solid var(--color-border); border-radius: var(--radius-control); background: var(--color-surface-subtle); }
.context-field { display: grid; gap: 5px; color: var(--color-text-secondary); font-size: 14px; font-weight: 550; }
.context-field select { width: 100%; min-height: 38px; padding: 0 32px 0 10px; }
.context-summary { display: grid; min-width: 0; gap: 4px; color: var(--color-text-muted); font-size: 14px; }
.context-summary strong { overflow-wrap: anywhere; color: var(--color-text); font-size: 14px; font-weight: 600; }
.context-summary small { color: var(--color-text-muted); font-size: 14px; }
.search-row { display: grid; grid-template-columns: minmax(0, 1fr) auto; align-items: center; gap: 10px; }
.discovery-search-field { min-width: 0; }
.search-submit { padding: 0 17px; color: #fff; border: 1px solid var(--color-accent); background: var(--color-accent); }
.search-submit:hover { background: var(--color-text); }
.search-submit--secondary { color: var(--color-text); border-color: var(--color-border-strong); background: var(--color-surface); }
.search-submit--secondary:hover { background: var(--color-surface-subtle); }
.search-submit:disabled { opacity: .55; cursor: wait; }
.query-plan-card { display: grid; gap: 12px; padding: 16px; border: 1px solid var(--color-border); border-radius: var(--radius-panel); background: var(--color-surface); }
.query-plan-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 14px; }
.query-plan-heading > div { min-width: 0; }
.query-plan-heading span:first-child { color: var(--color-text-muted); font-size: 14px; font-weight: 600; }
.query-plan-heading h2 { margin: 4px 0 0; color: var(--color-text); font-size: 17px; line-height: 1.45; }
.query-plan-status { flex: none; color: var(--color-text-secondary); font-size: 14px; }
.query-plan-facts { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0 18px; margin: 0; }
.query-plan-facts div { display: grid; grid-template-columns: 82px minmax(0, 1fr); gap: 10px; padding: 9px 0; border-bottom: 1px solid var(--color-border); }
.query-plan-facts dt, .query-plan-facts dd { margin: 0; font-size: 14px; }
.query-plan-facts dt { color: var(--color-text-muted); }
.query-plan-facts dd { overflow-wrap: anywhere; color: var(--color-text); font-weight: 550; }
.query-plan-rationale { margin: 0; color: var(--color-text-secondary); font-size: 14px; line-height: 1.6; }

.source-toolbar {
  display: flex;
  min-width: 0;
  align-items: end;
  gap: 12px;
  padding: 12px 14px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-panel);
  background: var(--color-surface);
}
.source-toolbar > label { display: grid; min-width: 148px; gap: 4px; color: var(--color-text-muted); font-size: 14px; }
.source-toolbar select { min-height: 36px; padding: 0 32px 0 10px; font-size: 14px; }
.view-switch { display: inline-flex; flex: none; padding: 3px; border: 1px solid var(--color-border); border-radius: 8px; background: var(--color-surface-subtle); }
.view-switch button { min-height: 34px; padding: 0 12px; color: var(--color-text-secondary); border: 0; background: transparent; }
.view-switch button[aria-selected="true"] { color: #fff; background: var(--color-accent); }
.view-switch button span { min-width: 20px; font-variant-numeric: tabular-nums; }
.result-count { margin-left: auto; padding-bottom: 8px; color: var(--color-text-muted); font-size: 14px; white-space: nowrap; }

.discovery-layout { display: grid; grid-template-columns: minmax(0, 1.65fr) minmax(360px, .95fr); min-width: 0; gap: 16px; align-items: start; }
.source-results,
.source-preview { min-width: 0; min-height: 610px; border: 1px solid var(--color-border); border-radius: var(--radius-panel); background: var(--color-surface); }
.source-results { overflow: hidden; }
.source-preview { padding: 20px; }

.list-empty,
.preview-empty { display: grid; min-height: 608px; place-content: center; justify-items: center; gap: 8px; padding: 28px; color: var(--color-text-secondary); text-align: center; }
.list-empty strong { color: var(--color-text); font-size: 16px; }
.list-empty span,
.preview-empty p { max-width: 48ch; font-size: 14px; }
.preview-empty h2 { color: var(--color-text); font-size: 18px; }

.source-list { margin: 0; padding: 0; list-style: none; }
.source-list li + li { border-top: 1px solid var(--color-border); }
.source-row { display: grid; width: 100%; min-height: 116px; grid-template-columns: minmax(0, 1fr) auto; align-items: start; gap: 12px; padding: 16px; text-align: left; background: transparent; }
.source-row:hover,
.source-row--active { background: var(--color-surface-subtle); }
.source-row--active { box-shadow: inset 2px 0 var(--color-accent); }
.source-select { display: grid; min-width: 0; grid-template-columns: 38px minmax(0, 1fr); align-items: start; gap: 12px; padding: 0; text-align: left; border: 0; background: transparent; cursor: pointer; }
.source-icon { display: grid; width: 36px; height: 36px; place-items: center; color: var(--color-text-secondary); border: 1px solid var(--color-border); border-radius: var(--radius-control); background: var(--color-surface); }
.source-copy { display: grid; min-width: 0; gap: 3px; }
.source-copy strong { overflow: hidden; color: var(--color-text); font-size: 15px; line-height: 1.45; text-overflow: ellipsis; white-space: nowrap; }
.source-copy > span { overflow: hidden; color: var(--color-text-secondary); font-size: 14px; text-overflow: ellipsis; white-space: nowrap; }
.source-copy small { display: -webkit-box; overflow: hidden; color: var(--color-text-muted); font-size: 14px; line-height: 1.55; -webkit-box-orient: vertical; -webkit-line-clamp: 2; }
.source-copy .source-relevance { color: var(--color-text-secondary); -webkit-line-clamp: 1; }
.source-state { display: grid; min-width: 144px; justify-items: end; gap: 8px; }
.status-badge { display: inline-flex; min-height: 26px; align-items: center; padding: 2px 8px; color: var(--color-text-secondary); border: 1px solid var(--color-border); border-radius: 999px; background: var(--color-surface); font-size: 14px; white-space: nowrap; }
.status-badge[data-status="license_required"] { color: var(--color-warning); border-color: #ead9bb; background: var(--color-warning-soft); }
.status-badge[data-status="rejected"],
.status-badge[data-status="withdrawn"] { color: var(--color-danger); border-color: #e8caca; background: var(--color-danger-soft); }
.processing-badge { display: inline-flex; min-height: 24px; align-items: center; padding: 2px 8px; color: var(--color-text-secondary); border: 1px solid var(--color-border); border-radius: 999px; background: var(--color-surface-subtle); font-size: 14px; text-align: center; }
.processing-badge[data-status="failed"] { color: var(--color-danger); border-color: #e8caca; background: var(--color-danger-soft); }
.processing-badge[data-status="admitted"] { color: var(--color-success); border-color: var(--color-success-soft); background: var(--color-success-soft); }
.save-candidate { min-height: 34px; padding: 0 10px; color: var(--color-text); border: 1px solid var(--color-border-strong); background: var(--color-surface); }
.save-candidate:hover { background: var(--color-surface-muted); }
.save-candidate:disabled { opacity: .5; cursor: wait; }

.preview-header { display: flex; align-items: flex-start; justify-content: space-between; gap: 14px; padding-bottom: 16px; border-bottom: 1px solid var(--color-border); }
.preview-header > div { min-width: 0; }
.preview-header span { color: var(--color-text-muted); font-size: 14px; font-weight: 600; }
.preview-header h2 { margin-top: 5px; font-size: 19px; line-height: 1.45; overflow-wrap: anywhere; }
.preview-header a { min-height: 36px; flex: none; padding: 0 10px; color: var(--color-text-secondary); border: 1px solid var(--color-border-strong); text-decoration: none; }
.preview-header a:hover { color: var(--color-text); background: var(--color-surface-subtle); }

.source-facts { display: grid; margin: 0; }
.source-facts div { display: grid; grid-template-columns: 104px minmax(0, 1fr); gap: 12px; padding: 10px 0; border-bottom: 1px solid var(--color-border); }
.source-facts dt,
.source-facts dd { margin: 0; font-size: 14px; }
.source-facts dt { color: var(--color-text-muted); }
.source-facts dd { color: var(--color-text); font-weight: 550; overflow-wrap: anywhere; }

.evidence-section { padding-top: 18px; }
.evidence-section h3 { font-size: 15px; }
.evidence-section p { margin-top: 6px; color: var(--color-text-secondary); font-size: 14px; line-height: 1.65; }
.parsing-list { display: grid; gap: 0; margin: 10px 0 0; padding: 0; list-style: none; border-top: 1px solid var(--color-border); }
.parsing-list li { display: flex; justify-content: space-between; gap: 14px; padding: 8px 0; border-bottom: 1px solid var(--color-border); font-size: 14px; }
.parsing-list li span { color: var(--color-text-muted); }
.parsing-list li strong { color: var(--color-text); font-weight: 550; text-align: right; }
.pipeline-list { display: grid; gap: 8px; margin: 10px 0 0; padding: 0; list-style: none; }
.pipeline-list li { display: grid; gap: 4px; padding: 10px 12px; border: 1px solid var(--color-border); border-radius: var(--radius-control); background: var(--color-surface-subtle); }
.pipeline-list li > div { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.pipeline-list li > div strong { color: var(--color-text); font-weight: 650; }
.pipeline-list li > div span { color: var(--color-text-secondary); font-size: 14px; }
.pipeline-list li[data-status="failed"] { border-color: #e8caca; background: var(--color-danger-soft); }
.pipeline-list li p,
.pipeline-list li small { margin: 0; color: var(--color-text-muted); font-size: 14px; line-height: 1.5; }
.action-feedback { display: grid; gap: 8px; }
.retry-action { display: inline-flex; min-height: 36px; align-items: center; justify-content: center; gap: 7px; align-self: start; padding: 0 12px; color: var(--color-text); border: 1px solid var(--color-border-strong); border-radius: var(--radius-control); background: var(--color-surface); font-size: 14px; font-weight: 600; cursor: pointer; }
.retry-action:hover { background: var(--color-surface-subtle); }
.retry-action:disabled { opacity: .55; cursor: wait; }

.admission-section { margin-top: 20px; padding-top: 18px; border-top: 1px solid var(--color-border-strong); }
.section-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
.section-heading h3 { font-size: 16px; }
.section-heading p { margin-top: 3px; color: var(--color-text-muted); font-size: 14px; }
.section-heading svg { color: var(--color-text-secondary); }
.blocker-list { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 12px; padding: 10px; color: var(--color-warning); border: 1px solid #ead9bb; border-radius: var(--radius-control); background: var(--color-warning-soft); font-size: 14px; }
.blocker-list strong { width: 100%; color: var(--color-text); }
.blocker-list span { padding: 1px 7px; border: 1px solid #ead9bb; border-radius: 999px; background: var(--color-surface); }
.admission-form { display: grid; gap: 12px; margin-top: 14px; }
.admission-form label { display: grid; gap: 5px; color: var(--color-text-secondary); font-size: 14px; }
.admission-form input,
.admission-form select,
.admission-form textarea { width: 100%; padding: 8px 10px; resize: vertical; }
.admission-actions { display: grid; gap: 9px; margin-top: 14px; }
.admit-action { width: 100%; padding: 0 14px; color: #fff; border: 1px solid var(--color-accent); background: var(--color-accent); }
.admit-action:hover { background: var(--color-text); }
.admit-action:disabled { color: var(--color-text-muted); border-color: var(--color-border); background: var(--color-surface-muted); cursor: not-allowed; }
.admission-actions > p { margin: 0; color: var(--color-text-muted); font-size: 14px; }
.reject-action,
.withdraw-action { justify-self: start; min-height: 34px; padding: 0; color: var(--color-danger); border: 0; background: transparent; }
.reject-action:hover,
.withdraw-action:hover { text-decoration: underline; text-underline-offset: 3px; }
.imported-version { display: flex; align-items: center; gap: 8px; color: var(--color-text-secondary); font-size: 14px; overflow-wrap: anywhere; }

.authority-boundary { display: flex; gap: 9px; margin-top: 20px; padding-top: 16px; color: var(--color-text-secondary); border-top: 1px solid var(--color-border); }
.authority-boundary svg { flex: none; margin-top: 2px; }
.authority-boundary p { margin: 0; font-size: 14px; line-height: 1.65; }

.spin { animation: spin 900ms linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }

@media (max-width: 1240px) {
  .discovery-context-grid { grid-template-columns: 1fr; }
  .query-plan-facts { grid-template-columns: 1fr; }
  .source-toolbar { flex-wrap: wrap; }
  .view-switch { width: 100%; }
  .view-switch button { flex: 1; }
  .result-count { margin-left: 0; }
  .discovery-layout { grid-template-columns: minmax(0, 1.45fr) minmax(350px, 1fr); }
}
</style>
