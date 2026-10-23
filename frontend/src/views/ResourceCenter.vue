<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  AlertCircle,
  BookOpenText, Braces, CheckSquare, FileText, LayoutGrid, List,
  LoaderCircle, Map as MapIcon, MessageSquareText, MonitorPlay, Presentation,
  RefreshCw, SlidersHorizontal, Sparkles, Wrench, X,
} from '@lucide/vue'
import {
  compareM5ResourceVersions,
  completeM5Resource,
  createM5ResourceVersion,
  exportM5Resource,
  getCanonicalCourseOutline,
  getM5PlanningTargets,
  getM5Resource,
  getM5ResourceGenerationJob,
  getM5TodayWork,
  getM5WorkspaceOverview,
  listM5Resources,
  recoverM5ResourceGenerationJob,
  restoreM5ResourceVersion,
  retryM5ResourceGenerationItem,
} from '../api'
import ResourcePreviewDrawer from '../components/ResourcePreviewDrawer.vue'
import SearchField from '../components/ui/SearchField.vue'
import ResourceHistoryDrawer from '../components/ResourceHistoryDrawer.vue'
import ResourceEditorDialog from '../components/ResourceEditorDialog.vue'
import ResourceTypeStage from '../components/ResourceTypeStage.vue'
import { useCourseContextStore } from '../stores/courseContext'

const route = useRoute()
const router = useRouter()
const courseContext = useCourseContextStore()

const typeDefinitions = [
  { id: 'handout', label: '个性化讲义', icon: BookOpenText, kicker: '阅读与批注', description: '目录、重点解释、图表公式、例子反例与随堂检查组成一份可持续编辑的讲义。' },
  { id: 'mind_map', label: '思维导图', icon: MapIcon, kicker: '结构化理解', description: '用稳定节点画布组织概念、机制、应用和来源，并从节点继续展开学习。' },
  { id: 'quiz', label: '测验题', icon: CheckSquare, kicker: '即时练习', description: '围绕当前知识点动态出题、原位判分，并保留答案解析与追问入口。' },
  { id: 'training_task', label: '实训任务书', icon: Wrench, kicker: '工程任务指导', description: '明确目标、环境、数据、步骤、检查点、提交物和评分标准。' },
  { id: 'code_sandbox', label: '代码沙盒', icon: Braces, kicker: '编辑与运行', description: '在任务、代码和输出三栏中完成编写、运行、调试、图表查看与 AI 点评。' },
  { id: 'video', label: '视频推荐', icon: MonitorPlay, kicker: '视频学习队列', description: '按知识点和画像组织核心讲解、工程案例与短时复习片段。' },
  { id: 'deck', label: 'PPT/网页课件', icon: Presentation, kicker: '演示式学习', description: '以缩略页和主舞台呈现概念、图表、案例与逐页讲解。' },
  { id: 'interactive_model', label: '可交互模型', icon: SlidersHorizontal, kicker: '参数实验', description: '通过参数控制、曲线变化和实验对比观察模型规律，而不是阅读静态说明。' },
  { id: 'feynman', label: '费曼复述', icon: MessageSquareText, kicker: '表达与追问', description: '完成首次复述、AI 追问、再次解释与前后对比，暴露并修正理解断点。' },
]

const resources = ref([])
const typeCounts = ref(Object.fromEntries(typeDefinitions.map(item => [item.id, 0])))
const total = ref(0)
const selected = ref(null)
const detail = ref(null)
const loading = ref(false)
const detailLoading = ref(false)
const downloading = ref(false)
const error = ref('')
const detailError = ref('')
const query = ref(String(route.query.q || ''))
const artifactType = ref(String(route.query.type || ''))
const status = ref(String(route.query.status || ''))
const sourceStatus = ref(String(route.query.source || ''))
const includeArchived = ref(route.query.archived === '1')
const viewMode = ref(route.query.view === 'list' ? 'list' : 'grid')
const historyOpen = ref(false)
const historyError = ref('')
const restoringId = ref('')
const comparingId = ref('')
const compareResult = ref(null)
const completing = ref(false)
const actionNotice = ref('')
const generationOpen = ref(false)
const generationType = ref('handout')
const generationLoading = ref(false)
const generationError = ref('')
const generationNotice = ref('')
const generationJob = ref(null)
const generationContext = ref(null)
const generationKnowledgePoints = ref([])
const generationKnowledgePointId = ref('')
const generationGoal = ref('')
const generationCourses = ref([])
const generationCourseId = ref('')
const generationTypeLocked = ref(false)
const editorOpen = ref(false)
const editorDraft = ref('')
const editorFormat = ref('markdown')
const editorSourceVersionId = ref('')
const editorSaving = ref(false)
const editorError = ref('')
let generationTimer

const currentCourseId = computed(() => (
  courseContext.contextRef?.courseId || String(route.query.course_id || '')
))
const currentCourseLabel = computed(() => courseContext.label || '当前课程')
const hasFilters = computed(() => Boolean(
  query.value || artifactType.value || status.value || sourceStatus.value || includeArchived.value
))
const historyItems = computed(() => detail.value?.history?.items || [])
const currentVersionId = computed(() => detail.value?.history?.current_version_id || detail.value?.current_version_id || '')
const generationItems = computed(() => generationJob.value?.items || [])
const generationActive = computed(() => generationItems.value.some(item => ['requested', 'queued', 'running'].includes(item.state)))
const generationDone = computed(() => generationItems.value.some(item => item.state === 'succeeded'))
const activeTypeDefinition = computed(() => typeDefinitions.find(item => item.id === artifactType.value) || null)
const activeRecentResource = computed(() => resources.value[0] || null)
const selectedGenerationPoint = computed(() => (
  generationKnowledgePoints.value.find(item => item.id === generationKnowledgePointId.value) || null
))
const generationCanStart = computed(() => Boolean(
  generationContext.value?.course_id
  && selectedGenerationPoint.value?.id
  && selectedGenerationPoint.value?.source_ref_ids?.length
  && generationType.value
))

function message(err, fallback = '请求失败') {
  const detailValue = err?.response?.data?.detail || err?.detail
  return detailValue?.message || (typeof detailValue === 'string' ? detailValue : '') || err?.message || fallback
}

function newIdempotencyKey(prefix) {
  const uuid = globalThis.crypto?.randomUUID?.()
  return `${prefix}-${uuid || `${Date.now()}-${Math.random().toString(36).slice(2, 10)}`}`
}

function currentResourceVersionId() {
  return detail.value?.current_version_id
    || detail.value?.resource?.version?.id
    || detail.value?.catalog?.current_version_id
    || ''
}

function openHistory() {
  historyError.value = ''
  compareResult.value = null
  historyOpen.value = true
}

function closeHistory() {
  historyOpen.value = false
  compareResult.value = null
  historyError.value = ''
}

async function compareHistory(versionId) {
  if (!selected.value || comparingId.value) return
  const left = historyItems.value.find(item => item.id === versionId)
  const right = historyItems.value.find(item => item.id === currentVersionId.value)
  if (!left || !right) return
  comparingId.value = versionId
  historyError.value = ''
  try {
    compareResult.value = await compareM5ResourceVersions(selected.value.id, left.number, right.number)
  } catch (err) {
    historyError.value = message(err)
  } finally {
    comparingId.value = ''
  }
}

async function restoreHistory(versionId) {
  if (!selected.value || restoringId.value || selected.value.archived) return
  restoringId.value = versionId
  historyError.value = ''
  try {
    detail.value = await restoreM5ResourceVersion(selected.value.id, {
      expected_lock_version: detail.value.lock_version,
      version_id: versionId,
    })
    selected.value = decorate(detail.value.catalog)
    actionNotice.value = '历史版本已恢复为新的当前版本，原版本仍保留。'
    await loadResources()
  } catch (err) {
    historyError.value = message(err, '恢复失败，当前版本未改变。')
  } finally {
    restoringId.value = ''
  }
}

async function completeSelectedResource() {
  const versionId = currentResourceVersionId()
  const rule = String(selected.value?.completion?.rule || '').trim()
  if (!selected.value || !versionId || !rule || completing.value) return
  completing.value = true
  detailError.value = ''
  actionNotice.value = ''
  try {
    await completeM5Resource(selected.value.id, {
      resource_version_id: versionId,
      completion_rule: rule,
      idempotency_key: newIdempotencyKey(`resource-complete-${selected.value.id}`),
      actual_minutes: null,
      context: {
        courseId: selected.value.course_id || currentCourseId.value || null,
        pathId: selected.value.path_id || String(route.query.path_id || '') || null,
        taskId: selected.value.task_id || String(route.query.task_id || '') || null,
      },
    })
    actionNotice.value = '学习完成事件已记录；掌握度和组卷门禁仍由有效学习证据聚合。'
    await selectResource(selected.value, { updateUrl: false })
    await loadResources()
  } catch (err) {
    detailError.value = message(err, '当前资源还不能记录完成，请先完成页面要求。')
  } finally {
    completing.value = false
  }
}

function openEditor() {
  if (!selected.value || selected.value.archived) return
  const versionId = currentResourceVersionId()
  const source = (detail.value?.versions || []).find(item => item.id === versionId)
  if (!source) {
    detailError.value = '当前版本内容暂时无法编辑，请重新加载资源。'
    return
  }
  editorSourceVersionId.value = source.id
  editorFormat.value = source.content_format || 'markdown'
  editorDraft.value = source.content || ''
  editorError.value = ''
  editorOpen.value = true
}

function closeEditor() {
  if (editorSaving.value) return
  editorOpen.value = false
  editorError.value = ''
}

async function saveEditorVersion() {
  if (!selected.value || !editorSourceVersionId.value || editorSaving.value) return
  editorSaving.value = true
  editorError.value = ''
  try {
    detail.value = await createM5ResourceVersion(selected.value.id, {
      expected_lock_version: detail.value.lock_version,
      source_version_id: editorSourceVersionId.value,
      content: editorDraft.value,
      content_format: editorFormat.value,
    })
    selected.value = decorate(detail.value.catalog)
    editorOpen.value = false
    actionNotice.value = '新版本已保存；旧版本和来源记录仍可在历史中查看。'
    await loadResources()
  } catch (err) {
    editorError.value = err?.status === 409
      ? '资源已在其他页面更新。草稿仍保留，请重新加载版本状态后再保存。'
      : message(err, '保存失败，当前版本未改变。')
  } finally {
    editorSaving.value = false
  }
}

function flattenOutlineKnowledgePoints(outline) {
  const points = new Map()
  for (const chapter of outline || []) {
    for (const point of chapter.knowledge_points || []) {
      const current = points.get(point.id) || {
        id: point.id,
        code: point.code || '',
        title: point.title || '未命名知识点',
        chapter_titles: [],
        source_ref_ids: [],
        position: chapter.position || 0,
      }
      if (chapter.title && !current.chapter_titles.includes(chapter.title)) current.chapter_titles.push(chapter.title)
      if (chapter.source_ref_id && !current.source_ref_ids.includes(chapter.source_ref_id)) current.source_ref_ids.push(chapter.source_ref_id)
      current.position = Math.min(current.position, chapter.position || current.position)
      points.set(point.id, current)
    }
  }
  return [...points.values()].sort((left, right) => (
    left.position - right.position || left.code.localeCompare(right.code) || left.title.localeCompare(right.title, 'zh-CN')
  ))
}

async function openGeneration({ type = '', knowledgePointId = '', prompt = '' } = {}) {
  const resource = detail.value?.resource || {}
  const courseId = resource.course_id || selected.value?.course_id || currentCourseId.value
  const pointId = knowledgePointId || resource.knowledge_point_id || selected.value?.knowledge_point?.id || ''
  const chapterId = resource.chapter_id || selected.value?.knowledge_point?.chapter_id || ''
  const sourceIds = [...new Set([
    ...(resource.source_ref_ids || []),
    ...(selected.value?.source_ref_ids || []),
    ...(generationContext.value?.source_ref_ids || []),
  ].map(item => String(item || '').trim()).filter(Boolean))]
  const selectedTypes = type ? [type] : typeDefinitions.map(item => item.id)
  await router.push({
    path: '/chat',
    query: {
      intent: 'resource_generation',
      course_id: courseId || undefined,
      chapter_id: chapterId || undefined,
      knowledge_point_id: pointId || undefined,
      resource_types: selectedTypes.join(','),
      source_ref_ids: sourceIds.length ? sourceIds.join(',') : undefined,
      prompt: prompt || undefined,
      request_id: newIdempotencyKey('resource-center-generation'),
      return_to: route.fullPath,
    },
  })
}

function openTypeGeneration() {
  openGenerationDialog({
    type: artifactType.value || 'handout',
    lockType: true,
    knowledgePointId: selected.value?.knowledge_point?.id || '',
  })
}

function openPreviewGeneration() {
  openGenerationDialog({
    type: selected.value?.type || artifactType.value || 'handout',
    lockType: true,
    knowledgePointId: selected.value?.knowledge_point?.id || '',
  })
}

function openGenericGeneration() {
  openGenerationDialog({ type: artifactType.value || 'handout' })
}

function openGenerationDialog({ type = 'handout', lockType = false, knowledgePointId = '' } = {}) {
  generationOpen.value = true
  generationJob.value = null
  generationError.value = ''
  generationNotice.value = ''
  generationTypeLocked.value = lockType
  generationType.value = type
  generationKnowledgePointId.value = knowledgePointId
  generationGoal.value = ''
  generationLoading.value = true
  void loadGenerationContext()
}

async function loadGenerationContext() {
  try {
    const targets = await getM5PlanningTargets()
    generationCourses.value = targets.courses || []
    const preferred = currentCourseId.value && generationCourses.value.some(item => item.id === currentCourseId.value)
      ? currentCourseId.value
      : generationCourses.value[0]?.id || ''
    generationCourseId.value = preferred
    await loadGenerationCourse(preferred)
  } catch (err) {
    generationError.value = message(err, '课程和知识点暂时无法读取。')
    generationContext.value = null
  } finally {
    generationLoading.value = false
  }
}

async function loadGenerationCourse(selectedCourseId) {
  if (!selectedCourseId) {
    generationContext.value = null
    generationKnowledgePoints.value = []
    generationKnowledgePointId.value = ''
    return
  }
  generationLoading.value = true
  generationError.value = ''
  try {
    const [outline, workspace] = await Promise.all([
      getCanonicalCourseOutline(selectedCourseId),
      getM5WorkspaceOverview(selectedCourseId),
    ])
    generationKnowledgePoints.value = flattenOutlineKnowledgePoints(outline)
    const preferredPoint = generationKnowledgePoints.value.find(item => item.id === generationKnowledgePointId.value)
      || generationKnowledgePoints.value[0]
    generationKnowledgePointId.value = preferredPoint?.id || ''
    generationContext.value = {
      course_id: selectedCourseId,
      profile_snapshot_id: workspace.profile?.snapshot_id || '',
      source_ref_ids: preferredPoint?.source_ref_ids || [],
    }
  } catch (err) {
    generationError.value = message(err, '课程知识点暂时无法读取。')
    generationContext.value = null
    generationKnowledgePoints.value = []
    generationKnowledgePointId.value = ''
  } finally {
    generationLoading.value = false
  }
}

watch(generationCourseId, (value, oldValue) => {
  if (generationOpen.value && value && value !== oldValue) void loadGenerationCourse(value)
})
watch(generationKnowledgePointId, (value) => {
  const point = generationKnowledgePoints.value.find(item => item.id === value)
  if (generationContext.value) generationContext.value = { ...generationContext.value, source_ref_ids: point?.source_ref_ids || [] }
})

function stopGenerationPolling() {
  if (generationTimer) window.clearTimeout(generationTimer)
  generationTimer = undefined
}

function scheduleGenerationPolling() {
  stopGenerationPolling()
  if (!generationActive.value) return
  generationTimer = window.setTimeout(() => loadGenerationJob({ quiet: true }), 1800)
}

async function loadGenerationJob({ quiet = false } = {}) {
  if (!generationJob.value?.job_id) return
  if (!quiet) generationLoading.value = true
  try {
    generationJob.value = await getM5ResourceGenerationJob(generationJob.value.job_id)
    scheduleGenerationPolling()
    if (generationDone.value) await loadResources()
  } catch (err) {
    generationError.value = message(err, '生成任务状态暂时无法读取。')
    stopGenerationPolling()
  } finally {
    if (!quiet) generationLoading.value = false
  }
}

async function startSingleGeneration() {
  await openGeneration({
    type: generationType.value,
    knowledgePointId: generationKnowledgePointId.value,
    prompt: generationGoal.value.trim()
      ? `请基于所选课程和知识点生成${typeDefinitions.find(item => item.id === generationType.value)?.label || '学习资源'}。辅助要求：${generationGoal.value.trim()}`
      : `请基于所选课程和知识点生成${typeDefinitions.find(item => item.id === generationType.value)?.label || '学习资源'}，并展示协作步骤。`,
  })
}

async function retryGenerationItem(item) {
  if (!generationJob.value?.job_id || generationLoading.value || item.state !== 'failed') return
  generationLoading.value = true
  generationError.value = ''
  try {
    await retryM5ResourceGenerationItem(generationJob.value.job_id, item.type)
    generationJob.value = await getM5ResourceGenerationJob(generationJob.value.job_id)
    generationNotice.value = `${item.title}已重新排队，其他成功资源保持不变。`
    scheduleGenerationPolling()
  } catch (err) {
    generationError.value = message(err, '重试失败。')
  } finally {
    generationLoading.value = false
  }
}

async function recoverGeneration() {
  if (!generationJob.value?.job_id || generationLoading.value) return
  generationLoading.value = true
  generationError.value = ''
  try {
    generationJob.value = await recoverM5ResourceGenerationJob(generationJob.value.job_id)
    generationNotice.value = '未完成项已恢复，已成功资源保持不变。'
    scheduleGenerationPolling()
  } catch (err) {
    generationError.value = message(err, '恢复生成任务失败。')
  } finally {
    generationLoading.value = false
  }
}

function formatDate(value) {
  if (!value) return '未记录'
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit',
  }).format(new Date(value))
}

function displayStatus(item) {
  if (item.archived) return '已归档'
  if (item.source_unavailable_count > 0) return '来源失效'
  const state = item.generation_state
  if (['queued', 'requested', 'pending'].includes(state)) return '等待生成'
  if (['running', 'retry_queued'].includes(state)) return '生成中'
  if (state === 'failed') return '生成失败'
  const labels = { draft: '草稿', reviewing: '审核中', approved: '可学习', published: '已发布', withdrawn: '已撤回' }
  return labels[item.status] || '可学习'
}

function completionText(item) {
  const progress = item.completion?.progress
  if (typeof progress === 'number') return `${Math.round(progress * 100)}%`
  if (item.completion?.status === 'completed') return '已完成'
  return '未记录'
}

function decorate(item) {
  return {
    ...item,
    display_status: displayStatus(item),
    completion_text: completionText(item),
    icon: typeDefinitions.find(type => type.id === item.type)?.icon || FileText,
  }
}

function queryState(selectedId = selected.value?.id || '') {
  return Object.fromEntries(Object.entries({
    q: query.value || undefined,
    type: artifactType.value || undefined,
    status: status.value || undefined,
    source: sourceStatus.value || undefined,
    archived: includeArchived.value ? '1' : undefined,
    view: viewMode.value === 'list' ? 'list' : undefined,
    resource_id: selectedId || undefined,
    course_id: currentCourseId.value || undefined,
    // Keep the learning-path context while selecting a resource so completion
    // events can be consumed by the path and intelligent-exam gate.
    path_id: String(route.query.path_id || '') || undefined,
    task_id: String(route.query.task_id || '') || undefined,
  }).filter(([, value]) => value !== undefined))
}

async function syncQuery(selectedId = selected.value?.id || '') {
  if (route.path !== '/workspace/resources') return
  await router.replace({ query: queryState(selectedId) })
}

async function loadResources({ preserveSelection = true } = {}) {
  loading.value = true
  error.value = ''
  try {
    const data = await listM5Resources({
      q: query.value || undefined,
      artifact_type: artifactType.value || undefined,
      course_id: currentCourseId.value || undefined,
      status: status.value || undefined,
      source_status: sourceStatus.value || undefined,
      include_archived: includeArchived.value,
      limit: 100,
    })
    resources.value = (data.items || []).map(decorate)
    typeCounts.value = data.type_counts || typeCounts.value
    total.value = data.total || 0
    const requestedId = String(route.params.resourceId || route.query.resource_id || '')
    const preferredId = preserveSelection ? (selected.value?.id || requestedId) : requestedId
    const preferred = resources.value.find(item => item.id === preferredId)
    if (preferred) await selectResource(preferred, { updateUrl: false })
    else if (requestedId) await loadDeepLinkedResource(requestedId)
    else if (resources.value.length) await selectResource(resources.value[0], { updateUrl: false })
    else {
      selected.value = null
      detail.value = null
      detailError.value = ''
    }
  } catch (err) {
    error.value = message(err)
  } finally {
    loading.value = false
  }
}

async function loadDeepLinkedResource(resourceId) {
  detailLoading.value = true
  detailError.value = ''
  try {
    const payload = await getM5Resource(resourceId)
    selected.value = decorate(payload.catalog)
    detail.value = payload
  } catch (err) {
    selected.value = null
    detail.value = null
    detailError.value = message(err)
  } finally {
    detailLoading.value = false
  }
}

async function selectResource(item, { updateUrl = true, loadDetail = true } = {}) {
  selected.value = item
  detail.value = null
  detailError.value = ''
  if (!loadDetail) return
  detailLoading.value = true
  try {
    if (updateUrl) await syncQuery(item.id)
    const payload = await getM5Resource(item.id)
    // The list projection omits version-level completion metadata. Replace
    // the selected summary with the server detail projection so the learner
    // can see and submit the current completion rule.
    selected.value = decorate(payload.catalog || item)
    detail.value = payload
  } catch (err) {
    detailError.value = message(err)
  } finally {
    detailLoading.value = false
  }
}

function previewResource(item) {
  if (selected.value?.id === item.id) return
  selectResource(item, { updateUrl: false, loadDetail: false })
}

async function retryPreview() {
  if (selected.value) await selectResource(selected.value, { updateUrl: false })
}

async function openResource() {
  if (!selected.value?.route) return
  await router.push({
    path: selected.value.route,
    query: currentCourseId.value ? { course_id: currentCourseId.value } : {},
  })
}

async function downloadResource() {
  if (!selected.value) return
  downloading.value = true
  detailError.value = ''
  try {
    const versionNumber = detail.value?.versions?.find(
      item => item.id === detail.value.current_version_id,
    )?.version_number || selected.value.version_number
    const payload = await exportM5Resource(selected.value.id, versionNumber)
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `${selected.value.title || 'resource'}-v${versionNumber || 'current'}.json`
    document.body.appendChild(link)
    link.click()
    link.remove()
    window.setTimeout(() => URL.revokeObjectURL(url), 1000)
  } catch (err) {
    detailError.value = message(err)
  } finally {
    downloading.value = false
  }
}

function clearFilters() {
  query.value = ''
  artifactType.value = ''
  status.value = ''
  sourceStatus.value = ''
  includeArchived.value = false
}

function setView(mode) {
  viewMode.value = mode
  syncQuery()
}

let searchTimer
watch(query, () => {
  window.clearTimeout(searchTimer)
  searchTimer = window.setTimeout(async () => {
    await syncQuery('')
    await loadResources({ preserveSelection: false })
  }, 250)
})
watch([artifactType, status, sourceStatus, includeArchived], async () => {
  await syncQuery('')
  await loadResources({ preserveSelection: false })
})
watch(currentCourseId, () => loadResources({ preserveSelection: false }))

onMounted(() => loadResources())
onBeforeUnmount(stopGenerationPolling)
</script>

<template>
  <section class="resource-page" data-testid="resource-center">
    <header class="page-heading">
      <div>
        <h1>资源中心</h1>
        <p>查找、预览并继续学习 {{ currentCourseLabel }} 的九类资源。</p>
      </div>
      <div class="heading-actions">
        <div class="resource-summary" aria-label="资源统计">
          <strong>{{ total }}</strong>
          <span>项已归档资源</span>
        </div>
        <button type="button" class="resource-create" @click="openGenericGeneration">
          <Sparkles :size="17" />新建资源
        </button>
      </div>
    </header>

    <div class="resource-workspace">
      <aside class="type-rail" aria-label="资源类型">
        <div class="rail-heading">
          <strong>资源类型</strong>
          <span>9 类</span>
        </div>
        <button
          type="button"
          class="type-option"
          data-resource-type="all"
          :class="{ active: artifactType === '' }"
          @click="artifactType = ''"
        >
          <FileText :size="18" />
          <span>全部资源</span>
          <strong>{{ total }}</strong>
        </button>
        <button
          v-for="type in typeDefinitions"
          :key="type.id"
          type="button"
          class="type-option"
          :data-resource-type="type.id"
          :class="{ active: artifactType === type.id }"
          @click="artifactType = type.id"
        >
          <component :is="type.icon" :size="18" />
          <span>{{ type.label }}</span>
          <strong>{{ typeCounts[type.id] || 0 }}</strong>
        </button>
      </aside>

      <main class="catalog-panel">
        <div class="catalog-toolbar">
          <SearchField v-model="query" class="resource-search-field" style="flex: 1 1 160px" clearable aria-label="搜索资源" placeholder="搜索资源" />

          <select v-model="status" aria-label="资源状态">
            <option value="">全部状态</option>
            <option value="draft">草稿</option>
            <option value="reviewing">审核中</option>
            <option value="approved">可学习</option>
            <option value="published">已发布</option>
            <option value="withdrawn">已撤回</option>
          </select>
          <select v-model="sourceStatus" aria-label="来源状态">
            <option value="">全部来源</option>
            <option value="available">来源可用</option>
            <option value="unavailable">来源失效</option>
            <option value="not_recorded">未记录来源</option>
          </select>
          <label class="archive-toggle">
            <input v-model="includeArchived" type="checkbox" />
            <span>显示归档</span>
          </label>
          <div class="view-switch" aria-label="资源布局">
            <button type="button" title="网格视图" :class="{ active: viewMode === 'grid' }" @click="setView('grid')">
              <LayoutGrid :size="18" />
            </button>
            <button type="button" title="列表视图" :class="{ active: viewMode === 'list' }" @click="setView('list')">
              <List :size="18" />
            </button>
          </div>
          <button type="button" class="refresh-button" title="刷新资源" :disabled="loading" @click="loadResources()">
            <RefreshCw :size="18" :class="{ spin: loading }" />
          </button>
        </div>

        <ResourceTypeStage
          v-if="activeTypeDefinition"
          :definition="activeTypeDefinition"
          :resource-count="resources.length"
          :recent-resource="activeRecentResource"
          :knowledge-point="selected?.knowledge_point?.title || ''"
          @generate="openTypeGeneration"
          @open-recent="selectResource(activeRecentResource)"
        />

        <div v-if="error" class="catalog-error" role="alert">
          <span>{{ error }}</span>
          <button type="button" @click="loadResources()">重新加载</button>
        </div>

        <div class="result-heading">
          <strong>{{ artifactType ? typeDefinitions.find(item => item.id === artifactType)?.label : '全部资源' }}</strong>
          <span>{{ resources.length }} 项结果</span>
        </div>

        <div v-if="loading && !resources.length" class="resource-skeletons" aria-label="正在加载资源">
          <div v-for="index in 6" :key="index" class="resource-skeleton" />
        </div>

        <div v-else-if="!resources.length && activeTypeDefinition" class="type-history-empty">
          <strong>还没有{{ activeTypeDefinition.label }}历史</strong>
          <span>使用上方“自定义生成”选择课程知识点；生成成功后会自动归档在这里。</span>
        </div>

        <div v-else-if="!resources.length" class="catalog-empty">
          <FileText :size="28" />
          <strong>{{ hasFilters ? '没有符合条件的资源' : '当前课程还没有归档资源' }}</strong>
          <span>{{ hasFilters ? '调整筛选条件后重新查看。' : '从今日知识点生成资源包后，产物会自动进入这里。' }}</span>
          <button v-if="hasFilters" type="button" @click="clearFilters">清除筛选</button>
          <button v-else type="button" @click="$router.push('/workspace/path')">前往学习路径</button>
        </div>

        <div v-else class="resource-results" :class="`mode-${viewMode}`">
          <button
            v-for="item in resources"
            :key="item.id"
            type="button"
            class="resource-item"
            :data-resource-id="item.id"
            :class="{ active: selected?.id === item.id }"
            @mouseenter="previewResource(item)"
            @focus="previewResource(item)"
            @click="selectResource(item)"
          >
            <span class="resource-icon"><component :is="item.icon" :size="20" /></span>
            <span class="resource-main">
              <strong :title="item.title">{{ item.title }}</strong>
              <span>{{ item.knowledge_point?.title || item.module || '未记录知识点' }}</span>
            </span>
            <span class="resource-meta">
              <span>{{ item.display_status }}</span>
              <span>v{{ item.version_number || '-' }}</span>
              <span>{{ formatDate(item.updated_at) }}</span>
            </span>
          </button>
        </div>
      </main>

      <ResourcePreviewDrawer
        :resource="selected"
        :detail="detail"
        :loading="detailLoading"
        :error="detailError"
        :downloading="downloading"
        @open="openResource"
        @download="downloadResource"
        @retry="retryPreview"
        @history="openHistory"
        @complete="completeSelectedResource"
        @generate="openPreviewGeneration"
        @edit="openEditor"
      />
    </div>

    <p v-if="actionNotice" class="resource-notice" role="status">
      <CheckSquare :size="17" />{{ actionNotice }}
      <button type="button" title="关闭提示" @click="actionNotice = ''"><X :size="15" /></button>
    </p>

    <ResourceHistoryDrawer
      :open="historyOpen"
      :title="`${selected?.title || '资源'} · 版本历史`"
      :items="historyItems"
      :current-version-id="currentVersionId"
      :selected-version-id="currentVersionId"
      :restoring-id="restoringId"
      :error="historyError"
      :compare-result="compareResult"
      :comparing-id="comparingId"
      :compare-disabled="Boolean(comparingId)"
      :restore-disabled="Boolean(selected?.archived)"
      @close="closeHistory"
      @compare="compareHistory"
      @restore="restoreHistory"
      @compare-close="compareResult = null"
    />

    <ResourceEditorDialog
      :open="editorOpen"
      :title="selected?.title || '资源'"
      :version-label="currentVersionId ? `版本 ${currentVersionId}` : ''"
      :content="editorDraft"
      :content-format="editorFormat"
      :saving="editorSaving"
      :error="editorError"
      @close="closeEditor"
      @update:content="editorDraft = $event"
      @save="saveEditorVersion"
    />

    <div v-if="generationOpen" class="generation-layer">
      <button type="button" class="generation-backdrop" aria-label="关闭资源生成" @click="generationOpen = false" />
      <section class="generation-dialog" role="dialog" aria-modal="true" aria-labelledby="generation-title">
        <header>
          <div><span>自定义资源</span><h2 id="generation-title">选择知识点并生成{{ typeDefinitions.find(item => item.id === generationType)?.label || '学习资源' }}</h2></div>
          <button type="button" class="dialog-close" title="关闭资源生成" @click="generationOpen = false"><X :size="18" /></button>
        </header>
        <p class="generation-context">先选择课程、知识点和辅助要求，再跳转智能对话完成生成</p>
        <div v-if="generationLoading && !generationJob" class="generation-state" role="status"><LoaderCircle :size="22" class="spin" />{{ generationContext ? '正在创建生成任务' : '正在读取课程、来源和画像上下文' }}</div>
        <div v-else-if="generationError && !generationContext" class="generation-state generation-state--error" role="alert"><AlertCircle :size="22" /><span>{{ generationError }}</span></div>
        <template v-else>
          <div class="generation-form">
            <label class="generation-select">
              <span>学习课程</span>
              <select v-model="generationCourseId" :disabled="Boolean(generationJob) || generationLoading">
                <option value="" disabled>选择课程</option>
                <option v-for="course in generationCourses" :key="course.id" :value="course.id">{{ course.title }}</option>
              </select>
            </label>
            <label class="generation-select">
              <span>资源类型</span>
              <select v-model="generationType" :disabled="generationTypeLocked || Boolean(generationJob)">
                <option v-for="type in typeDefinitions" :key="type.id" :value="type.id">{{ type.label }}</option>
              </select>
            </label>
            <label class="generation-select">
              <span>课程知识点</span>
              <select v-model="generationKnowledgePointId" :disabled="Boolean(generationJob)">
                <option v-for="point in generationKnowledgePoints" :key="point.id" :value="point.id">
                  {{ point.code ? `${point.code} · ` : '' }}{{ point.title }}{{ point.source_ref_ids.length ? '' : '（暂无来源）' }}
                </option>
              </select>
            </label>
            <label class="generation-select">
              <span>学习重点</span>
              <textarea
                v-model="generationGoal"
                :disabled="Boolean(generationJob)"
                rows="3"
                maxlength="512"
                placeholder="例如：结合工程案例解释关键机制，并突出我容易混淆的部分"
              />
            </label>
          </div>
          <div v-if="selectedGenerationPoint" class="generation-selection" aria-live="polite">
            <span>{{ selectedGenerationPoint.chapter_titles.join(' / ') || '未绑定章节' }}</span>
            <strong>{{ selectedGenerationPoint.source_ref_ids.length }} 项可追溯来源</strong>
          </div>
          <p v-if="selectedGenerationPoint && !selectedGenerationPoint.source_ref_ids.length" class="generation-help generation-help--blocked">
            该知识点尚未绑定可用章节来源。请先在知识库补充并解析课程资料，再返回生成。
          </p>
          <p v-else class="generation-help">提交后会跳转智能对话并自动发送生成请求；协作轨迹、失败和资源子空间跳转都在统一对话中展示。</p>
          <div v-if="generationError" class="generation-error" role="alert"><AlertCircle :size="17" />{{ generationError }}</div>
          <div v-if="generationNotice" class="generation-notice" role="status"><CheckSquare :size="17" />{{ generationNotice }}</div>
          <div v-if="generationJob" class="generation-job" data-testid="single-generation-job">
            <div class="generation-job-heading"><strong>{{ generationJob.scope === 'single' ? '单项资源任务' : '资源任务' }}</strong><span>{{ generationJob.status }}</span></div>
            <div v-for="item in generationItems" :key="item.type" class="generation-item">
              <span>{{ item.title }}</span><strong>{{ item.state }}</strong>
              <button v-if="item.state === 'failed'" type="button" @click="retryGenerationItem(item)">重试</button>
            </div>
            <button v-if="generationItems.some(item => item.state === 'running')" type="button" class="secondary-action" @click="recoverGeneration">恢复未完成项</button>
          </div>
          <button v-if="!generationJob" type="button" class="generation-primary" :disabled="!generationCanStart || generationLoading" @click="startSingleGeneration"><Sparkles :size="17" />{{ generationLoading ? '准备中' : '进入智能对话生成' }}</button>
        </template>
      </section>
    </div>
  </section>
</template>

<style scoped>
.resource-page { width: 100%; color: #06141b; letter-spacing: 0; }
.page-heading { display: flex; align-items: flex-end; justify-content: space-between; gap: 24px; margin-bottom: 18px; }
.page-heading h1 { margin: 0; font-size: 28px; line-height: 1.25; }
.page-heading p { margin: 7px 0 0; color: #4a5c6a; font-size: 15px; line-height: 1.6; }
.heading-actions { display: flex; align-items: center; gap: 14px; }
.resource-summary { display: flex; align-items: baseline; gap: 8px; color: #4a5c6a; white-space: nowrap; }
.resource-summary strong { color: #11212d; font-size: 24px; }
.resource-summary span { font-size: 14px; }
.resource-create { display: inline-flex; min-height: 40px; align-items: center; gap: 8px; border: 1px solid #11212d; border-radius: 8px; padding: 0 14px; background: #11212d; color: #fff; font-size: 14px; font-weight: 650; cursor: pointer; }
.resource-workspace { display: grid; height: calc(100vh - 178px); min-height: 540px; grid-template-columns: 216px minmax(360px, 1fr) 320px; gap: 14px; }
.type-rail, .catalog-panel { min-width: 0; overflow: hidden; border: 1px solid #ccd0cf; border-radius: 8px; background: #fff; }
.type-rail { padding: 8px; overflow-y: auto; }
.rail-heading { display: flex; align-items: center; justify-content: space-between; min-height: 42px; padding: 0 10px 7px; border-bottom: 1px solid #dfe4e5; }
.rail-heading strong, .rail-heading span { font-size: 14px; }
.rail-heading span { color: #60727c; }
.type-option { display: grid; width: 100%; min-height: 44px; grid-template-columns: 20px minmax(0, 1fr) auto; align-items: center; gap: 9px; margin-top: 4px; padding: 0 10px; border: 0; border-radius: 6px; background: #fff; color: #4a5c6a; text-align: left; cursor: pointer; }
.type-option span, .type-option strong { min-width: 0; font-size: 14px; }
.type-option strong { color: #60727c; font-variant-numeric: tabular-nums; }
.type-option:hover { background: #f5f7f7; color: #11212d; }
.type-option.active { background: #11212d; color: #fff; }
.type-option.active strong { color: #fff; }
.catalog-panel { display: flex; flex-direction: column; }
.catalog-toolbar { display: flex; align-items: center; gap: 8px; padding: 12px; border-bottom: 1px solid #dfe4e5; }
.search-field { display: flex; min-width: 44px; height: 40px; flex: 1 1 160px; align-items: center; gap: 8px; padding: 0 10px; border: 1px solid #ccd0cf; border-radius: 8px; color: #60727c; }
.search-field:focus-within { border-color: #11212d; box-shadow: 0 0 0 2px rgba(17, 33, 45, .12); }
.search-field input { min-width: 0; flex: 1; border: 0; outline: 0; color: #06141b; font: inherit; font-size: 14px; }
.search-field button { display: grid; width: 28px; height: 28px; place-items: center; border: 0; background: transparent; color: #4a5c6a; cursor: pointer; }
select { min-width: 0; height: 40px; border: 1px solid #ccd0cf; border-radius: 8px; padding: 0 9px; background: #fff; color: #253745; font: inherit; font-size: 14px; }
.catalog-toolbar > select { width: 118px; flex: 0 1 118px; }
.catalog-toolbar > select:nth-of-type(2) { width: 124px; flex-basis: 124px; }
.archive-toggle { display: flex; height: 40px; flex: 0 0 auto; align-items: center; gap: 7px; padding: 0 9px; border: 1px solid #ccd0cf; border-radius: 8px; color: #344957; white-space: nowrap; }
.archive-toggle span { font-size: 14px; }
.view-switch { display: grid; width: 90px; flex: 0 0 90px; grid-template-columns: repeat(2, 44px); overflow: hidden; border: 1px solid #ccd0cf; border-radius: 8px; }
.view-switch button, .refresh-button { display: grid; min-width: 0; height: 40px; place-items: center; border: 0; background: #fff; color: #4a5c6a; cursor: pointer; }
.view-switch button + button { border-left: 1px solid #ccd0cf; }
.view-switch button.active { background: #11212d; color: #fff; }
.refresh-button { width: 42px; flex: 0 0 42px; border: 1px solid #ccd0cf; border-radius: 8px; }
.result-heading { display: flex; min-height: 46px; align-items: center; justify-content: space-between; padding: 0 14px; border-bottom: 1px solid #eef2f2; }
.result-heading strong, .result-heading span { font-size: 14px; }
.result-heading span { color: #60727c; }
.resource-results { min-height: 0; flex: 1; overflow: auto; padding: 12px; }
.resource-results.mode-grid { display: grid; align-content: start; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }
.resource-results.mode-list { display: grid; align-content: start; gap: 6px; }
.resource-item { display: grid; min-width: 0; min-height: 96px; grid-template-columns: 40px minmax(0, 1fr); gap: 10px; padding: 13px; border: 1px solid #dfe4e5; border-radius: 8px; background: #fff; color: #253745; text-align: left; cursor: pointer; }
.resource-item:hover { border-color: #9ba8ab; background: #f7f9f9; }
.resource-item.active { border-color: #11212d; box-shadow: inset 0 0 0 1px #11212d; }
.resource-icon { display: grid; width: 38px; height: 38px; place-items: center; border-radius: 7px; background: #eef2f2; color: #11212d; }
.resource-main { min-width: 0; }
.resource-main strong { display: -webkit-box; overflow: hidden; color: #06141b; font-size: 15px; line-height: 1.45; -webkit-box-orient: vertical; -webkit-line-clamp: 2; }
.resource-main > span { display: block; margin-top: 5px; overflow: hidden; color: #60727c; font-size: 14px; text-overflow: ellipsis; white-space: nowrap; }
.resource-meta { display: flex; grid-column: 1 / -1; align-items: center; gap: 9px; color: #4a5c6a; }
.resource-meta span { font-size: 14px; white-space: nowrap; }
.mode-grid .resource-main strong { display: block; text-overflow: ellipsis; white-space: nowrap; -webkit-line-clamp: unset; }
.mode-list .resource-item { min-height: 72px; grid-template-columns: 40px minmax(0, 1fr) auto; align-items: center; }
.mode-list .resource-meta { grid-column: auto; justify-content: flex-end; }
.catalog-empty, .catalog-error { margin: 12px; border: 1px solid #dfe4e5; border-radius: 8px; }
.type-history-empty { display: flex; min-height: 72px; align-items: center; justify-content: space-between; gap: 18px; padding: 14px 18px; border-top: 1px solid #eef2f2; color: #60727c; }
.type-history-empty strong { color: #11212d; font-size: 15px; white-space: nowrap; }
.type-history-empty span { max-width: 48ch; font-size: 14px; line-height: 1.55; text-align: right; }
.catalog-empty { display: grid; min-height: 240px; place-content: center; justify-items: center; gap: 10px; padding: 24px; color: #4a5c6a; text-align: center; }
.catalog-empty strong { color: #06141b; font-size: 16px; }
.catalog-empty span { max-width: 38ch; font-size: 14px; line-height: 1.6; }
.catalog-empty button, .catalog-error button { min-height: 38px; border: 1px solid #11212d; border-radius: 8px; padding: 0 13px; background: #11212d; color: #fff; font-size: 14px; cursor: pointer; }
.catalog-error { display: flex; align-items: center; justify-content: space-between; gap: 14px; padding: 10px 12px; border-color: #d8aaa5; background: #fff5f3; color: #8b3d35; }
.catalog-error span { font-size: 14px; }
.resource-notice { position: fixed; z-index: 40; right: 24px; bottom: 24px; display: flex; max-width: min(520px, calc(100vw - 48px)); align-items: center; gap: 8px; margin: 0; padding: 12px 14px; border: 1px solid #ccd0cf; border-radius: 8px; background: #fff; box-shadow: 0 8px 22px rgba(6, 20, 27, .12); color: #253745; font-size: 14px; line-height: 1.5; }
.resource-notice button { display: grid; width: 26px; height: 26px; place-items: center; margin-left: auto; border: 0; background: transparent; color: #60727c; cursor: pointer; }
.generation-layer { position: fixed; z-index: 90; inset: 0; display: grid; place-items: center; padding: 24px; }
.generation-backdrop { position: absolute; inset: 0; border: 0; background: rgba(6, 20, 27, .24); cursor: default; }
.generation-dialog { position: relative; width: min(560px, 100%); max-height: min(720px, calc(100vh - 48px)); overflow: auto; border: 1px solid #ccd0cf; border-radius: 8px; background: #fff; color: #06141b; box-shadow: 0 16px 36px rgba(6, 20, 27, .16); }
.generation-dialog > header { display: flex; align-items: flex-start; justify-content: space-between; gap: 14px; padding: 20px; border-bottom: 1px solid #dfe4e5; }
.generation-dialog > header span { color: #60727c; font-size: 14px; }
.generation-dialog h2 { margin: 5px 0 0; font-size: 20px; line-height: 1.35; }
.dialog-close { display: grid; width: 36px; height: 36px; place-items: center; border: 1px solid #ccd0cf; border-radius: 8px; background: #fff; color: #11212d; cursor: pointer; }
.generation-context, .generation-help { margin: 0; padding: 14px 20px; color: #4a5c6a; font-size: 14px; line-height: 1.6; }
.generation-form { display: grid; gap: 14px; padding: 0 20px; }
.generation-select { display: grid; gap: 7px; color: #253745; font-size: 14px; font-weight: 650; }
.generation-select select, .generation-select textarea { width: 100%; box-sizing: border-box; }
.generation-select textarea { resize: vertical; min-height: 84px; border: 1px solid #ccd0cf; border-radius: 8px; padding: 10px 11px; background: #fff; color: #253745; font: inherit; font-size: 14px; line-height: 1.55; }
.generation-select textarea::placeholder { color: #7b888e; }
.generation-selection { display: flex; align-items: center; justify-content: space-between; gap: 16px; margin: 14px 20px 0; padding: 10px 12px; border: 1px solid #dfe4e5; border-radius: 8px; background: #f7f9f9; color: #4a5c6a; }
.generation-selection span { min-width: 0; overflow: hidden; font-size: 14px; text-overflow: ellipsis; white-space: nowrap; }
.generation-selection strong { flex: 0 0 auto; color: #11212d; font-size: 14px; }
.generation-help { padding-top: 10px; }
.generation-help--blocked { color: #8b3d35; }
.generation-primary { display: inline-flex; min-height: 42px; align-items: center; gap: 8px; margin: 0 20px 20px; padding: 0 15px; border: 1px solid #11212d; border-radius: 8px; background: #11212d; color: #fff; font-size: 14px; font-weight: 650; cursor: pointer; }
.generation-primary:disabled { cursor: default; opacity: .48; }
.generation-error, .generation-notice { display: flex; gap: 8px; margin: 0 20px 12px; padding: 10px; border: 1px solid #d8aaa5; border-radius: 8px; background: #fff5f3; color: #8b3d35; font-size: 14px; line-height: 1.5; }
.generation-notice { border-color: #ccd0cf; background: #f7f9f9; color: #253745; }
.generation-state { display: flex; min-height: 150px; align-items: center; justify-content: center; gap: 9px; padding: 24px; color: #4a5c6a; font-size: 14px; text-align: center; }
.generation-state--error { color: #8b3d35; }
.generation-job { margin: 0 20px 20px; padding: 12px; border: 1px solid #dfe4e5; border-radius: 8px; }
.generation-job-heading { display: flex; align-items: center; justify-content: space-between; gap: 8px; padding-bottom: 8px; border-bottom: 1px solid #eef2f2; }
.generation-job-heading span { color: #60727c; font-size: 14px; }
.generation-item { display: grid; grid-template-columns: minmax(0, 1fr) auto auto; gap: 8px; align-items: center; padding: 10px 0; border-bottom: 1px solid #eef2f2; color: #253745; font-size: 14px; }
.generation-item strong { color: #60727c; font-size: 14px; }
.generation-item button, .generation-job > .secondary-action { min-height: 32px; border: 1px solid #ccd0cf; border-radius: 7px; padding: 0 9px; background: #fff; color: #11212d; font-size: 14px; cursor: pointer; }
.generation-job > .secondary-action { margin-top: 12px; }
.dialog-close:focus-visible, .generation-primary:focus-visible, .generation-item button:focus-visible { outline: 2px solid #11212d; outline-offset: 2px; }
.resource-skeletons { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; padding: 12px; }
.resource-skeleton { height: 96px; border-radius: 8px; background: #eef2f2; animation: pulse 1.2s ease-in-out infinite alternate; }
button:focus-visible, select:focus-visible, input:focus-visible, textarea:focus-visible { outline: 2px solid #11212d; outline-offset: 2px; }
button:disabled { cursor: default; opacity: .48; }
.spin { animation: spin .8s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
@keyframes pulse { to { background: #dfe4e5; } }
@media (max-width: 1220px) {
  .resource-workspace { grid-template-columns: 196px minmax(340px, 1fr) 300px; gap: 10px; }
  .catalog-toolbar > select { width: auto; flex: 1 1 100px; }
  .archive-toggle { display: none; }
  .resource-results.mode-grid { grid-template-columns: 1fr; }
}

/* FB-FE-01: the result/catalog surface is primary; type and detail rails stay compact. */
.resource-workspace {
  grid-template-columns: 176px minmax(420px, 1fr) 248px;
  gap: 20px;
}

.type-rail {
  padding: 12px 10px;
}

.catalog-toolbar {
  padding: 14px 16px;
}

.resource-results {
  padding: 16px;
}

@media (max-width: 1220px) {
  .resource-workspace {
    grid-template-columns: 168px minmax(360px, 1fr) 250px;
    gap: 14px;
  }
}
</style>
