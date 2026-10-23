<script setup>
import { ref, onMounted, onUnmounted, computed, nextTick, watch, createApp, defineAsyncComponent } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useCourseContextStore } from '../stores/courseContext'
import { getStudentProfile, getLearningPath, getReviewPlans, getRecommendations, getNotes, regenerateComponent, getProfileAnalysis, getM5DashboardSummary, getM5WorkspaceOverview } from '../api'
import {
  Activity, Brain, ArrowRight, BookOpen, Target,
  CheckCircle2, Clock, GraduationCap, Play, CalendarDays,
  ChevronDown, X
} from '@lucide/vue'
import AggregationStatus from '../components/AggregationStatus.vue'
const LearningTrendChart = defineAsyncComponent(() => import('../components/LearningTrendChart.vue'))
const VideoRenderPanel = defineAsyncComponent(() => import('../components/VideoRenderPanel.vue'))
const VideoPlayerCard = defineAsyncComponent(() => import('../components/VideoPlayerCard.vue'))

const router = useRouter()
const route = useRoute()
const courseContext = useCourseContextStore()
const props = defineProps({ studentId: String })

const profile = ref(null)
const learningPath = ref(null)
const reviews = ref([])
const recommendations = ref([])
const profileAnalysis = ref(null)
const workspaceOverview = ref(null)
const dashboardSummary = ref(null)
const dashboardSummaryError = ref('')
const todayTasks = computed(() => workspaceOverview.value?.today_tasks || [])
const loading = ref(true)

const showVideoPanel = ref(false)
const videoPanelUrl = ref('')

const studentNotes = ref([])
const activeResource = ref(null)
const activeResourceContent = ref('')
const isGenerating = ref(false)
const currentStudentId = ref(props.studentId || localStorage.getItem('edumatrix_student_id') || 'demo-student')
const currentCourseId = computed(() => (
  courseContext.course?.id
  || courseContext.contextRef?.courseId
  || String(route.query.course_id || '')
))

const activeLearningTarget = computed(() => dashboardSummary.value?.focus?.title || todayTasks.value[0]?.title || learningPath.value?.active_learning_target || '')
let resourceScrollLock = null

function setResourceScrollLock(locked) {
  const appContent = document.querySelector('.app-content')
  if (!appContent) return

  if (locked && !resourceScrollLock) {
    resourceScrollLock = {
      element: appContent,
      overflow: appContent.style.overflow,
      overscrollBehavior: appContent.style.overscrollBehavior,
    }
    appContent.style.overflow = 'hidden'
    appContent.style.overscrollBehavior = 'none'
  } else if (!locked && resourceScrollLock) {
    resourceScrollLock.element.style.overflow = resourceScrollLock.overflow
    resourceScrollLock.element.style.overscrollBehavior = resourceScrollLock.overscrollBehavior
    resourceScrollLock = null
  }
}

const weakConcepts = computed(() => {
  const m = profile.value?.concept_mastery
  if (!m) return []
  return Object.entries(m).filter(([, v]) => v < 0.4).sort(([, a], [, b]) => a - b).slice(0, 5)
})

const conceptMastery = computed(() => {
  const raw = profile.value?.concept_mastery || {}
  return Object.entries(raw).map(([name, score]) => ({ name, mastery: score }))
})

const focus = computed(() => dashboardSummary.value?.focus || {
  title: activeLearningTarget.value || '继续当前学习安排',
  strategy: '按已确认路径完成当前任务，达到完成标准后再进入下一知识点。',
  reason: '来自当前学习路径。',
  completion_criteria: '完成当前任务并保存有效学习证据。',
  estimated_minutes: todayTasks.value[0]?.estimate_minutes || [],
  source_refs: [],
})
const primaryAction = computed(() => dashboardSummary.value?.primary_action || workspaceOverview.value?.next_action || {
  label: '查看学习路径',
  route: '/workspace/path',
})
const summaryMetrics = computed(() => dashboardSummary.value?.metrics || [])
const summaryStrategies = computed(() => dashboardSummary.value?.knowledge_strategies || [])
const reviewSummary = computed(() => dashboardSummary.value?.review_summary || {
  due_count: reviews.value.length,
  items: reviews.value.slice(0, 3),
})
const weakSummary = computed(() => dashboardSummary.value?.weak_summary || weakConcepts.value.map(([id, mastery]) => ({
  id,
  knowledge_point_id: id,
  title: id,
  mastery,
  mastery_status: 'supported',
  mastery_label: '有掌握证据',
  weak_reason: '来自已有掌握度记录；详细原因待确认。',
  weak_reason_status: 'unknown',
  profile_dimensions: [{ key: 'unknown', label: '关联画像维度', status: '待确认' }],
  course_snapshot: {},
  source_refs: [],
  event_refs: [],
  next_action: { label: '路径待确认', route: null, available: false },
})).slice(0, 3))
const hasProfileSnapshot = computed(() => Boolean(
  dashboardSummary.value?.traceability?.profile_snapshot_id
  || dashboardSummary.value?.profile_alignment?.profile_snapshot?.id
  || workspaceOverview.value?.profile?.snapshot_id
))
const weakSummaryEmptyCopy = computed(() => hasProfileSnapshot.value
  ? '当前画像快照没有确认的薄弱点；继续学习后，系统会用新的证据更新。'
  : '当前没有可用的画像快照，完成诊断或确认画像后才会显示薄弱点。')
const trendPoints = computed(() => dashboardSummary.value?.trend || [])
const activitySummary = computed(() => dashboardSummary.value?.activity_summary || { event_count: 0, active_days: 0 })
const aggregationNotice = computed(() => dashboardSummary.value?.aggregation?.message || dashboardSummaryError.value)

function estimateLabel(range) {
  const values = Array.isArray(range) ? range.filter(value => Number.isFinite(Number(value))) : []
  if (!values.length) return '按当前步骤完成'
  if (values.length === 1 || values[0] === values[1]) return `约 ${values[0]} 分钟`
  return `约 ${values[0]}-${values[1]} 分钟`
}

function sourceLabel(ref) {
  return ref?.label || '当前学习记录'
}

function profileInsight(field) {
  const value = profile.value?.[field]
  if (typeof value === 'string' && value.trim() && value.trim().toLowerCase() !== 'imported') return value.trim()
  return '待生成'
}

function openPrimaryAction() {
  if (primaryAction.value?.route) router.push(primaryAction.value.route)
}

function weakMasteryLabel(item) {
  if (item?.mastery !== null && item?.mastery !== undefined && Number.isFinite(Number(item.mastery))) {
    return `${Math.round(Number(item.mastery) * 100)}% · ${item.mastery_label || '有掌握证据'}`
  }
  return '未知 / 待确认 · 暂无掌握证据'
}

function weakSnapshotLabel(item) {
  const snapshot = item?.course_snapshot || {}
  const course = snapshot.course_title || '当前课程未知'
  const version = snapshot.course_version ? ` v${snapshot.course_version}` : ''
  const profileVersion = snapshot.snapshot_version ? ` · 画像 ${snapshot.snapshot_version}` : ''
  return `${course}${version}${profileVersion}`
}

function openWeakPoint(item) {
  if (item?.next_action?.route) router.push(item.next_action.route)
}

function buildDashboardFallback(overview) {
  const tasks = overview?.today_tasks || []
  const first = tasks[0]
  const nodes = overview?.current_path?.nodes || []
  const completed = nodes.filter(item => item.status === 'completed').length
  return {
    schema_version: 'f4.dashboard-summary.fallback.v1',
    state: first ? 'ready' : overview?.state || 'path_required',
    course: overview?.course || null,
    focus: {
      title: first?.title || (overview?.state === 'course_required' ? '先选择一门预置课程' : '查看下一步学习安排'),
      strategy: first?.recommendation_reason || '已有首页摘要暂时不可用，请从当前路径继续。',
      reason: first ? '来自当前已确认学习路径。' : '来自当前课程状态。',
      completion_criteria: first?.completion_criteria || '完成当前主动作后返回首页查看最新状态。',
      estimated_minutes: first?.estimate_minutes || [],
      source_refs: first?.path_id ? [{ type: 'learning_path', id: first.path_id, label: '当前已确认学习路径' }] : [],
    },
    primary_action: overview?.next_action || { label: '查看学习路径', route: '/workspace/path' },
    knowledge_strategies: tasks.map((item, index) => ({
      id: item.node_id,
      title: item.title,
      is_current: index === 0,
      strategy: item.recommendation_reason,
      recommended_resource: item.task_kind === 'review' ? '复习中心' : '学习空间',
      estimate_minutes: item.estimate_minutes,
      completion_criteria: item.completion_criteria,
      continue_route: item.continue_route,
      source_refs: item.path_id ? [{ type: 'learning_path', id: item.path_id, label: '当前已确认学习路径' }] : [],
    })),
    metrics: [
      { label: '路径进度', value: nodes.length ? `${completed}/${nodes.length}` : '暂无', detail: '已完成任务 / 路径任务', source_refs: [] },
      { label: '到期复习', value: String(overview?.review?.due_count || 0), detail: '来自当前课程复习队列', source_refs: [] },
      { label: '需强化', value: String(overview?.profile?.weak_knowledge_points?.length || 0), detail: '来自最近画像快照', source_refs: [] },
      { label: '最近更新', value: '待同步', detail: '保留当前路径继续学习', source_refs: [] },
    ],
    review_summary: overview?.review || { due_count: 0, items: [] },
    weak_summary: (overview?.profile?.weak_knowledge_points || []).slice(0, 3).map((item) => ({
      id: item?.id || null,
      knowledge_point_id: item?.id || null,
      title: item?.title || item?.id || '未命名知识点',
      mastery: null,
      mastery_status: 'unknown',
      mastery_label: '未知（暂无掌握证据）',
      weak_reason: '当前画像快照记录该知识点需要优先强化；具体原因待确认。',
      weak_reason_status: 'unknown',
      profile_dimensions: [{ key: 'unknown', label: '关联画像维度', status: '待确认' }],
      course_snapshot: {
        course_id: overview?.course?.id || null,
        course_title: overview?.course?.title || null,
        course_version: overview?.course?.version || null,
        snapshot_id: overview?.profile?.snapshot_id || null,
        snapshot_version: overview?.profile?.profile_version || null,
      },
      source_refs: overview?.profile?.snapshot_id ? [{ type: 'profile_snapshot', id: overview.profile.snapshot_id, label: '当前画像快照' }] : [],
      event_refs: [],
      next_action: {
        label: item?.id ? '开始强化' : '路径待确认',
        route: item?.id ? `/workspace/path?course_id=${encodeURIComponent(overview?.course?.id || '')}&knowledge_point_id=${encodeURIComponent(item.id)}` : null,
        available: Boolean(item?.id),
      },
    })),
    aggregation: { status: 'unavailable', message: '首页摘要暂时未同步，当前路径与已有资源仍可继续使用。' },
    trend: [],
    sourceEventIds: [],
  }
}

function goLearn(concept) {
  router.push({ path: '/learn', query: { q: concept } })
}

function continueTodayTask(item = todayTasks.value[0]) {
  if (item?.continue_route) router.push(item.continue_route)
  else goLearn(activeLearningTarget.value)
}

function goPath() { router.push('/learning-path') }
// Go analysis properly navigates
function goReview() { router.push('/review') }

function playVideo(url) {
  videoPanelUrl.value = url
  showVideoPanel.value = true
}

function getDimensionIcon(key) {
  if (key === 'lecture') return BookOpen
  if (key === 'mindmap') return Brain
  if (key === 'code') return Activity
  if (key === 'quiz') return Target
  if (key === 'video') return Play
  return BookOpen
}

function getDimensionColorClass(key) {
  if (key === 'quiz') return 'text-amber-700'
  if (key === 'video') return 'text-rose-700'
  return 'text-edu-600'
}

function getSortedResources(resourcesObj) {
  if (!resourcesObj) return []
  return Object.entries(resourcesObj).map(([key, res]) => ({
    key,
    ...res
  })).sort((a, b) => (b.priority || 0) - (a.priority || 0))
}

function openResourceViewer(concept, key, res) {
  activeResource.value = { concept, key, res }
  activeResourceContent.value = ''
  
  if (res.status === 'generated' && res.note_id) {
    const found = studentNotes.value.find(n => n.id === res.note_id)
    if (found) {
      activeResourceContent.value = found.content
    } else {
      activeResourceContent.value = '未能在本地缓存中查找到该笔记，可能已被删除。'
    }
  }
}

function closeResourceViewer() {
  activeResource.value = null
  activeResourceContent.value = ''
  isGenerating.value = false
}

async function generateResource() {
  if (!activeResource.value) return
  isGenerating.value = true
  
  const { concept, key, res } = activeResource.value
  try {
    const data = await regenerateComponent(currentStudentId.value, res.role, res.resource_type, concept, res.overview)
    if (data && data.status === 'success') {
      const rec = recommendations.value.find(r => r.concept === concept)
      if (rec && rec.resources[key]) {
        rec.resources[key].status = 'generated'
        rec.resources[key].note_id = data.note_id
      }
      
      const noteIdx = studentNotes.value.findIndex(n => n.id === data.note_id)
      const newNoteObj = {
        id: data.note_id,
        source: 'adaptive_hub',
        content: data.content,
        tags: [res.resource_type],
        concepts: [concept],
        created_at: new Date().toISOString()
      }
      if (noteIdx !== -1) {
        studentNotes.value[noteIdx] = newNoteObj
      } else {
        studentNotes.value.push(newNoteObj)
      }
      
      activeResourceContent.value = data.content
      activeResource.value.res.status = 'generated'
      activeResource.value.res.note_id = data.note_id
    }
  } catch (err) {
    console.error('Failed to generate component:', err)
    alert('智能体生成失败，请重试！')
  } finally {
    isGenerating.value = false
  }
}

function openInWorkspace() {
  if (!activeResource.value) return
  const { concept, key, res } = activeResource.value
  
  closeResourceViewer()
  
  if (key === 'lecture' || key === 'mindmap') {
    router.push({ path: '/notes', query: { search: concept } })
  }
  else if (key === 'code') {
    router.push({ path: '/learn', query: { q: concept } })
  }
  else if (key === 'video') {
    const url = `/api/v1/video/stream?student_id=${currentStudentId.value}`
    playVideo(url)
  }
  else if (key === 'quiz') {
    router.push({ path: '/learn', query: { quiz: concept } })
  }
}

let dashboardRefreshing = false
let lastDashboardRefreshAt = 0
async function refreshDashboardSummary() {
  if (dashboardRefreshing || loading.value) return
  if (Date.now() - lastDashboardRefreshAt < 15000) return
  lastDashboardRefreshAt = Date.now()
  dashboardRefreshing = true
  try {
    const courseId = currentCourseId.value
    const [overview, summary] = await Promise.all([
      getM5WorkspaceOverview(courseId).catch(() => null),
      getM5DashboardSummary(courseId),
    ])
    workspaceOverview.value = overview
    dashboardSummary.value = summary
    dashboardSummaryError.value = ''
  } catch (requestError) {
    dashboardSummaryError.value = requestError?.message || '首页摘要暂时未同步，当前路径与已有资源仍可继续使用。'
  } finally {
    dashboardRefreshing = false
  }
}

function refreshDashboardOnVisibility() {
  if (!document.hidden) void refreshDashboardSummary()
}

onMounted(async () => {
  await courseContext.restoreFromRoute(route).catch(() => null)
  window.startInteractiveQuiz = (conceptName) => {
    router.push({ path: '/learn', query: { quiz: conceptName } })
  }
  window.startInteractiveVideo = () => {
    const url = `/api/v1/video/stream?student_id=${currentStudentId.value}`
    playVideo(url)
  }
  window.mountCodeToSandbox = (btn) => {
    const parent = btn.closest('.relative')
    const pre = parent ? parent.querySelector('pre') : null
    if (pre) {
      const rawCode = pre.textContent || ''
      localStorage.setItem('edumatrix_sandbox_mount_code', rawCode)
      router.push({ path: '/learn', query: { q: activeResource.value?.concept || '' } })
    }
  }

  const sid = currentStudentId.value
  const courseId = currentCourseId.value

  try {
    workspaceOverview.value = await getM5WorkspaceOverview(courseId).catch(() => null)
    dashboardSummary.value = await getM5DashboardSummary(courseId)
  } catch (e) {
    console.warn('Dashboard summary unavailable:', e)
    dashboardSummaryError.value = '首页摘要暂时未同步，当前路径与已有资源仍可继续使用。'
    dashboardSummary.value = buildDashboardFallback(workspaceOverview.value)
  }

  try {
    const [p, lp, rv, recs, notesData, analysisData] = await Promise.all([
      getStudentProfile(sid),
      getLearningPath(sid).catch(() => null),
      getReviewPlans(sid).catch(() => []),
      getRecommendations(sid).catch(() => []),
      getNotes(sid).catch(() => ({ notes: [] })),
      getProfileAnalysis(sid, courseId).catch(() => null)
    ])
    profile.value = { ...(profile.value || {}), ...(p || {}) }
    learningPath.value = lp
    reviews.value = Array.isArray(rv) ? rv : (rv?.plans || rv?.due_reviews || [])
    recommendations.value = recs || []
    studentNotes.value = notesData?.notes || []
    profileAnalysis.value = analysisData
  } catch (e) {
    console.error('Dashboard load error:', e)
  } finally {
    loading.value = false
  }
  window.addEventListener('focus', refreshDashboardSummary)
  document.addEventListener('visibilitychange', refreshDashboardOnVisibility)
})

onUnmounted(() => {
  window.removeEventListener('focus', refreshDashboardSummary)
  document.removeEventListener('visibilitychange', refreshDashboardOnVisibility)
  setResourceScrollLock(false)
  window.startInteractiveQuiz = null
  window.startInteractiveVideo = null
  window.mountCodeToSandbox = null
  cleanupCustomMindmaps()
})

watch([activeResource, activeResourceContent], () => {
  if (activeResource.value && activeResourceContent.value) {
    nextTick(() => {
      renderAllDiagrams()
    })
  }
})

watch(activeResource, (resource) => {
  setResourceScrollLock(Boolean(resource))
})

function safeParseJson(str, fallback = []) {
  if (!str) return fallback
  let cleaned = str.trim()
  if (cleaned.startsWith('```')) {
    cleaned = cleaned.replace(/^```[a-zA-Z]*\s*/, '').replace(/\s*```$/, '').trim()
  }
  const startIdx = cleaned.indexOf('[')
  const endIdx = cleaned.lastIndexOf(']')
  if (startIdx !== -1 && endIdx !== -1 && endIdx > startIdx) {
    cleaned = cleaned.substring(startIdx, endIdx + 1)
  }
  try {
    return JSON.parse(cleaned)
  } catch (e) {
    console.error("JSON parse failed in Dashboard.vue, attempting fuzzy recovery:", e, str)
    try {
      const fixed = cleaned
        .replace(/,\s*]/g, ']')
        .replace(/,\s*}/g, '}')
      return JSON.parse(fixed)
    } catch (e2) {
      console.error("Fuzzy JSON recovery failed:", e2)
      return fallback
    }
  }
}

// --- 任务 8.3: 照搬主对话资源生成的 Markdown 渲染引擎与自愈算法 ---
function extractCodeFromMarkdown(mdText) {
  if (!mdText) return ''
  const regex = /```(?:python|javascript|js|py)?\s*\n([\s\S]*?)```/gi
  const codes = []
  let match
  while ((match = regex.exec(mdText)) !== null) {
    codes.push(match[1].trim())
  }
  if (codes.length > 0) {
    return codes.join('\n\n')
  }
  return mdText.trim()
}

function sanitizeMermaidCode(code) {
  let lines = code.split(/\r?\n/)
  let result = []
  let isMindmap = false
  let nodeCounter = 0

  const delimPairs = [
    { open: '((', close: '))' },
    { open: '{{', close: '}}' },
    { open: '(', close: ')' },
    { open: '[', close: ']' },
  ];

  for (let line of lines) {
    let trimmed = line.trim()
    if (!trimmed) {
      result.push(line)
      continue
    }

    if (trimmed === 'mindmap') {
      isMindmap = true
      result.push(line)
      continue
    }

    if (!isMindmap) {
      result.push(line)
      continue
    }

    let indent = line.match(/^(\s*)/)[0]
    let cleaned = trimmed.replace(/^[-*+]\s+/, '')
    cleaned = cleaned.replace(/\*\*/g, '').replace(/`/g, '')

    if (cleaned.startsWith('%%')) {
      result.push(line)
      continue
    }

    if (cleaned.startsWith('"') && cleaned.endsWith('"')) {
      cleaned = cleaned.slice(1, -1).trim()
    }

    let isShape = false
    let id = ''
    let openDelim = ''
    let innerText = ''
    let closeDelim = ''

    for (const pair of delimPairs) {
      const escapedOpen = pair.open.replace(/[|\\{}()[\]^$+*?.]/g, '\\$&')
      const escapedClose = pair.close.replace(/[|\\{}()[\]^$+*?.]/g, '\\$&')
      const regex = new RegExp(`^([^({[\\]\\s]+)\\s*(${escapedOpen})\\s*(.*?)\\s*(${escapedClose})$`)
      const match = cleaned.match(regex)
      if (match) {
        id = match[1]
        openDelim = match[2]
        innerText = match[3]
        closeDelim = match[4]
        isShape = true
        break
      }
    }

    if (isShape) {
      let cleanText = innerText.trim()
      if (cleanText.startsWith('"') && cleanText.endsWith('"')) {
        cleanText = cleanText.slice(1, -1)
      }
      cleanText = cleanText.replace(/\\"/g, '"').replace(/"/g, '&quot;').trim()
      let wrappedText = '"' + cleanText + '"'
      result.push(indent + id + openDelim + wrappedText + closeDelim)
      continue
    }

    const hasSpecial = /[^a-zA-Z0-9_\-]/g.test(cleaned)
    if (hasSpecial) {
      nodeCounter++
      const nodeId = `node_${nodeCounter}`
      let cleanText = cleaned.replace(/\\"/g, '"').replace(/"/g, '&quot;').trim()
      let wrappedText = '"' + cleanText + '"'
      result.push(indent + nodeId + '[' + wrappedText + ']')
    } else {
      let cleanText = cleaned.replace(/\\"/g, '"').replace(/"/g, '&quot;').trim()
      result.push(indent + cleanText)
    }
  }

  return result.join('\n')
}

function renderMarkdown(text, type = '', conceptName = '') {
  if (!text) return ''

  let cleaned = text.trim()
  
  const openTicksCount = (cleaned.match(/```/g) || []).length
  if (openTicksCount % 2 !== 0) {
    cleaned += '\n```'
  }
  const doubleDollarCount = (cleaned.match(/\$\$/g) || []).length
  if (doubleDollarCount % 2 !== 0) {
    cleaned += '\n$$'
  }

  if (cleaned.startsWith('```markdown') && cleaned.endsWith('```')) {
    cleaned = cleaned.slice(11, -3).trim()
  } else if (cleaned.startsWith('```') && cleaned.endsWith('```')) {
    const firstLineEnd = cleaned.indexOf('\n')
    if (firstLineEnd !== -1) {
      const lang = cleaned.substring(3, firstLineEnd).trim().toLowerCase()
      if (lang === '' || lang === 'markdown' || lang === 'text' || lang === 'txt') {
        cleaned = cleaned.substring(firstLineEnd + 1, cleaned.length - 3).trim()
      }
    }
  }

  const svgBlocks = []
  cleaned = cleaned.replace(/(<svg[\s\S]*?<\/svg>)/gi, (match) => {
    const idx = svgBlocks.length
    svgBlocks.push(match)
    return `@@SVGBLOCKTOKEN${idx}@@`
  })

  const layoutBlocks = []
  function protectLayout(htmlTag) {
    const idx = layoutBlocks.length
    layoutBlocks.push(htmlTag)
    return `@@LAYOUTTOKEN${idx}@@`
  }

  function buildThreeLevelHintLadderHtml(rawContent) {
    if (!rawContent) return ''

    let text = rawContent
      .replace(/<details[\s\S]*?>/gi, '')
      .replace(/<\/details>/gi, '')
      .replace(/<summary>[\s\S]*?<\/summary>/gi, '')
      .replace(/^[#*\s]*💡?\s*提示阶梯[（(]点击展开[）)]?[#*\s]*\n+/gim, '')
      .trim()

    const layer1Match = text.match(/(?:[-*+\s]*)\*?\*?第\s*[1一]\s*层[（(]([^）)]+)[）)]\*?\*?\s*[：:]\s*([\s\S]*?)(?=(?:[-*+\s]*)\*?\*?第\s*[2二]\s*层|$)/i)
    const layer2Match = text.match(/(?:[-*+\s]*)\*?\*?第\s*[2二]\s*层[（(]([^）)]+)[）)]\*?\*?\s*[：:]\s*([\s\S]*?)(?=(?:[-*+\s]*)\*?\*?第\s*[3三]\s*层|$)/i)
    const layer3Match = text.match(/(?:[-*+\s]*)\*?\*?第\s*[3三]\s*层[（(]([^）)]+)[）)]\*?\*?\s*[：:]\s*([\s\S]*?)(?=$)/i)

    const layers = []
    if (layer1Match) layers.push({ num: 1, name: layer1Match[1].trim(), content: layer1Match[2].trim() })
    if (layer2Match) layers.push({ num: 2, name: layer2Match[1].trim(), content: layer2Match[2].trim() })
    if (layer3Match) layers.push({ num: 3, name: layer3Match[1].trim(), content: layer3Match[2].trim() })

    if (layers.length === 0) {
      const cardStart = protectLayout(`<div class="resource-accordion">
  <button type="button" onclick="const body=this.nextElementSibling; const icon=this.querySelector('.accordion-icon'); if(body.style.display==='none'||!body.style.display){ body.style.display='block'; if(icon) icon.textContent='收起'; }else{ body.style.display='none'; if(icon) icon.textContent='展开'; }" class="resource-accordion__trigger">
    <span>提示阶梯</span>
    <span class="accordion-icon">展开</span>
  </button>
  <div class="accordion-body resource-accordion__body" style="display: none;">`)
      const cardEnd = protectLayout(`</div></div>`)
      return `\n\n${cardStart}\n\n${text}\n\n${cardEnd}\n\n`
    }

    const itemsHtml = layers.map(l => {
      const cardStart = protectLayout(`<div class="resource-accordion resource-accordion--nested">
  <button type="button" onclick="const body=this.nextElementSibling; const icon=this.querySelector('.accordion-icon'); if(body.style.display==='none'||!body.style.display){ body.style.display='block'; if(icon) icon.textContent='收起'; }else{ body.style.display='none'; if(icon) icon.textContent='展开'; }" class="resource-accordion__trigger">
    <span><strong>第 ${l.num} 层提示</strong> · ${l.name}</span>
    <span class="accordion-icon">展开</span>
  </button>
  <div class="accordion-body resource-accordion__body" style="display: none;">`)
      const cardEnd = protectLayout(`</div></div>`)
      return `\n\n${cardStart}\n\n${l.content}\n\n${cardEnd}\n\n`
    }).join('\n')

    const wrapperStart = protectLayout(`<div class="resource-hint-ladder">
  <div class="resource-hint-ladder__title">
    <span>三层递进提示阶梯</span>
  </div>`)
    const wrapperEnd = protectLayout(`</div>`)

    return `\n\n${wrapperStart}\n${itemsHtml}\n${wrapperEnd}\n\n`
  }

  cleaned = cleaned.replace(/(?:^|\n)\s*[-*+]*\s*(?:[#*\s]*提示阶梯[：:]*\s*\n+)?<details[\s\S]*?>([\s\S]*?)<\/details>/gi, (match, bodyContent) => {
    return buildThreeLevelHintLadderHtml(bodyContent)
  })

  if (!cleaned.includes('@@LAYOUTTOKEN')) {
    cleaned = cleaned.replace(
      /(?:[#*]*\s*提示阶梯[：:]?\s*[#*]*\s*\n+)?((?:[-*]\s*\*?第[123一二三]层[\s\S]*?)(?=\n\s*\n(?![-\s]*\*?第[123一二三]层)|\n[#*]{1,3}\s+|<div|$))/gi,
      (match, hintsContent) => {
        return buildThreeLevelHintLadderHtml(hintsContent)
      }
    )
  }

  let html = cleaned
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')

  const blockMath = []
  html = html.replace(/\DoubleDollar([\s\S]*?)\DoubleDollar/g, (_, math) => {
    const idx = blockMath.length
    blockMath.push({ math: math.trim(), display: true })
    return `@@BLOCKMATHTOKEN${idx}@@`
  }).replace(/\$\$/g, '$$$$') // Escape backslashes for double dollars replacement safely
  html = html.replace(/\\\[([\s\S]*?)\\\]/g, (_, math) => {
    const idx = blockMath.length
    blockMath.push({ math: math.trim(), display: true })
    return `@@BLOCKMATHTOKEN${idx}@@`
  })

  const inlineMath = []
  html = html.replace(/\\\(([\s\S]*?)\\\)/g, (_, math) => {
    const idx = inlineMath.length
    inlineMath.push({ math: math.trim(), display: false })
    return `@@INLINEMATHTOKEN${idx}@@`
  })
  html = html.replace(/\$([^$\n]+?)\$/g, (_, math) => {
    const idx = inlineMath.length
    inlineMath.push({ math: math.trim(), display: false })
    return `@@INLINEMATHTOKEN${idx}@@`
  })

  const codeBlocks = []
  html = html.replace(/```([^\r\n]*)\r?\n([\s\S]*?)```/g, (_, lang, code) => {
    const isMermaid = lang.toLowerCase().includes('mermaid') || code.includes('mindmap') || code.includes('graph ') || code.includes('sequenceDiagram')
    let blockHtml = ''
    if (isMermaid) {
      let cleanCode = code.trim()
        .replace(/&amp;/g, '&')
        .replace(/&lt;/g, '<')
        .replace(/&gt;/g, '>')
        .replace(/&quot;/g, '"')
        .replace(/&#39;/g, "'")

      const tokenRegex = /@@INLINEMATHTOKEN(\d+)@@/g
      cleanCode = cleanCode.replace(tokenRegex, (match, idx) => {
        const item = inlineMath[parseInt(idx)]
        if (item) {
          return item.math
            .replace(/\$/g, '')
            .replace(/\\hat\{([a-zA-Z0-9]+)\}/g, '$1^')
            .replace(/\\frac\{([^}]+)\}\{([^}]+)\}/g, '$1/$2')
            .replace(/\\partial/g, 'd')
            .replace(/\\Sigma/g, 'sum')
            .replace(/\\sigma/g, 'sigma')
            .replace(/\\alpha/g, 'alpha')
            .replace(/\\cdot/g, '·')
            .replace(/\\/g, '')
        }
        return ''
      })

      const blockTokenRegex = /@@BLOCKMATHTOKEN(\d+)@@/g
      cleanCode = cleanCode.replace(blockTokenRegex, (match, idx) => {
        const item = blockMath[parseInt(idx)]
        if (item) {
          return item.math
            .replace(/\$/g, '')
            .replace(/\\hat\{([a-zA-Z0-9]+)\}/g, '$1^')
            .replace(/\\frac\{([^}]+)\}\{([^}]+)\}/g, '$1/$2')
            .replace(/\\partial/g, 'd')
            .replace(/\\Sigma/g, 'sum')
            .replace(/\\sigma/g, 'sigma')
            .replace(/\\alpha/g, 'alpha')
            .replace(/\\cdot/g, '·')
            .replace(/\\/g, '')
        }
        return ''
      })

      cleanCode = sanitizeMermaidCode(cleanCode)
      const escapedCode = encodeURIComponent(cleanCode)

      if (cleanCode.includes('mindmap')) {
        blockHtml = `<div class="custom-mindmap-placeholder" data-code="${escapedCode}"></div>`
      } else {
        blockHtml = `<div class="resource-diagram">
          <div class="resource-diagram__header">
            <span>概念思维导图</span>
            <span class="resource-diagram__format">Mermaid</span>
          </div>
          <div class="mermaid-container resource-diagram__canvas">
            <div class="mermaid" data-code="${escapedCode}"><div class="mermaid-loading resource-rendering"><span class="resource-spinner"></span><span>正在绘制思维导图...</span></div></div>
          </div>
        </div>`
      }
    } else {
      const cleanLang = (lang || 'python').trim().toLowerCase()
      blockHtml = `<div class="resource-code-block">
        <pre class="language-${cleanLang}"><code class="language-${cleanLang}">${code.trim()}</code></pre>
        <button onclick="window.mountCodeToSandbox && window.mountCodeToSandbox(this)" class="resource-code-block__action">
          挂载至沙箱
        </button>
      </div>`
    }
    const idx = codeBlocks.length
    codeBlocks.push(blockHtml)
    return `@@CODEBLOCKTOKEN${idx}@@`
  })

  html = html.replace(/`([^`\n]+)`/g, (_, code) => {
    const blockHtml = `<code class="resource-inline-code">${code}</code>`
    const idx = codeBlocks.length
    codeBlocks.push(blockHtml)
    return `@@CODEBLOCKTOKEN${idx}@@`
  })

  const lines = html.split('\n')
  let inTable = false
  let tableHeader = []
  let tableRows = []
  let inList = false
  const processedLines = []

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i]
    const trimmed = line.trim()
    const isTableRow = trimmed.startsWith('|') && trimmed.endsWith('|')
    if (isTableRow) {
      if (inList) {
        processedLines.push('</ul>')
        inList = false
      }
      const cells = trimmed.slice(1, -1).split('|').map(c => c.trim())
      const isSeparator = cells.every(c => /^[:-]+$/.test(c))
      if (isSeparator) {
        continue
      }
      if (!inTable) {
        inTable = true
        tableHeader = cells
      } else {
        tableRows.push(cells)
      }
      continue
    } else {
      if (inTable) {
        processedLines.push(generateTableHtml(tableHeader, tableRows))
        inTable = false
        tableHeader = []
        tableRows = []
      }
    }

    const listMatch = line.match(/^(\s*)[-*+]\s+(.*)$/)
    if (listMatch) {
      const content = listMatch[2]
      if (!inList) {
        processedLines.push('<ul class="my-2 space-y-1 list-disc list-inside">')
        inList = true
      }
        processedLines.push(`<li class="resource-list-item">${content}</li>`)
    } else {
      if (inList) {
        processedLines.push('</ul>')
        inList = false
      }
      processedLines.push(line)
    }
  }

  if (inTable) {
    processedLines.push(generateTableHtml(tableHeader, tableRows))
  }
  if (inList) {
    processedLines.push('</ul>')
  }

  html = processedLines.join('\n')

  function generateTableHtml(header, rows) {
    let tableHtml = '<div class="resource-table-wrap"><table class="resource-table">'
    if (header && header.length > 0) {
      tableHtml += '<thead class="bg-gray-50/75"><tr>'
      header.forEach(h => {
      tableHtml += `<th>${h}</th>`
      })
      tableHtml += '</tr></thead>'
    }
    tableHtml += '<tbody class="divide-y divide-gray-100 bg-white">'
    rows.forEach(row => {
      tableHtml += '<tr class="hover:bg-gray-50/50 transition-colors">'
      row.forEach(cell => {
        tableHtml += `<td>${cell}</td>`
      })
      tableHtml += '</tr>'
    })
    tableHtml += '</tbody></table></div>'
    return tableHtml
  }

  html = html.replace(/!\[([^\]]*)\]\s*\(([^)]+)\)/g, (match, alt, url) => {
    const cleanUrl = url.replace(/\s+/g, '')
    return `<img src="${cleanUrl}" alt="${alt}" class="resource-image" />`
  })
  html = html.replace(/\*\*([^*]+)\*\*/g, '<strong class="font-bold text-gray-900">$1</strong>')
  html = html.replace(/\*([^*]+)\*/g, '<em class="italic text-gray-800">$1</em>')
  html = html.replace(/^### (.*$)/gim, '<h4 class="resource-heading-4">$1</h4>')
  html = html.replace(/^## (.*$)/gim, '<h3 class="text-sm font-semibold text-gray-900 mt-5 mb-2 border-b border-gray-100 pb-1 flex items-center gap-1.5">$1</h3>')
  html = html.replace(/^# (.*$)/gim, '<h2 class="text-base font-bold text-gray-900 mt-6 mb-3 flex items-center gap-2">$1</h2>')

  html = html.replace(/\n\n/g, '<div class="h-2.5"></div>')

  function renderMath(math, display) {
    const cleanMathContent = math
      .replace(/&amp;/g, '&')
      .replace(/&lt;/g, '<')
      .replace(/&gt;/g, '>')
      .replace(/&quot;/g, '"')
      .replace(/&#39;/g, "'")

    if (window.katex) {
      try {
        return window.katex.renderToString(cleanMathContent, {
          displayMode: display,
          throwOnError: false,
          trust: true
        })
      } catch (err) {
        console.error('KaTeX rendering error:', err)
      }
    }
    const cleanMath = cleanMathContent
      .replace(/\\Sigma/g, '∑')
      .replace(/\\sigma/g, 'σ')
      .replace(/\\mu/g, 'μ')
      .replace(/\\beta/g, 'β')
      .replace(/\\theta/g, 'θ')
      .replace(/\\alpha/g, 'α')
      .replace(/\\lambda/g, 'λ')
      .replace(/\\partial/g, '∂')
      .replace(/\\infty/g, '∞')
      .replace(/\\hat\{([a-zA-Z0-9]+)\}/g, '<span style="text-decoration: overline">$1</span>')
      .replace(/([a-zA-Z0-9]+)_([a-zA-Z0-9]+)/g, '$1<sub>$2</sub>')
      .replace(/([a-zA-Z0-9]+)\^([a-zA-Z0-9]+)/g, '$1<sup>$2</sup>')
      .replace(/\\cdot/g, '·')
      .replace(/\\times/g, '×')
      .replace(/\\frac\{([^}]+)\}\{([^}]+)\}/g, '($1)/($2)')
      .replace(/\\sqrt\{([^}]+)\}/g, '√($1)')
      .replace(/\\text\{([^}]+)\}/g, '$1')
      .replace(/\\quad/g, '&nbsp;&nbsp;')

    if (display) {
      return `<div class="resource-math resource-math--block">${cleanMath}</div>`
    } else {
      return `<span class="resource-math resource-math--inline">${cleanMath}</span>`
    }
  }

  html = html
    .replace(/\\in\b/g, ' ∈ ')
    .replace(/\\sigma\b/g, 'σ')
    .replace(/\\hat\{([a-zA-Z0-9]+)\}/g, '<span style="text-decoration: overline">$1</span>')
    .replace(/\\([{}])/g, '$1')
    .replace(/([a-zA-Z0-9])_([a-zA-Z0-9_]+)/g, '$1<sub>$2</sub>')
    .replace(/([a-zA-Z0-9])_\{([^}]+)\}/g, '$1<sub>$2</sub>')
    .replace(/([a-zA-Z0-9])\^([a-zA-Z0-9+-\\*\\top\\partial]+)/g, (match, base, exp) => {
      const displayExp = exp === '\\top' || exp === 'top' ? 'T' : exp
      return `${base}<sup>${displayExp}</sup>`
    })
    .replace(/([a-zA-Z0-9])\^\{([^}]+)\}/g, (match, base, exp) => {
      const displayExp = exp === '\\top' || exp === 'top' ? 'T' : exp
      return `${base}<sup>${displayExp}</sup>`
    })

  layoutBlocks.forEach((block, idx) => {
    html = html.split(`@@LAYOUTTOKEN${idx}@@`).join(block)
  })

  blockMath.forEach((item, idx) => {
    html = html.split(`@@BLOCKMATHTOKEN${idx}@@`).join(renderMath(item.math, true))
  })
  inlineMath.forEach((item, idx) => {
    html = html.split(`@@INLINEMATHTOKEN${idx}@@`).join(renderMath(item.math, false))
  })
  codeBlocks.forEach((block, idx) => {
    html = html.split(`@@CODEBLOCKTOKEN${idx}@@`).join(block)
  })
  svgBlocks.forEach((block, idx) => {
    html = html.split(`@@SVGBLOCKTOKEN${idx}@@`).join(block)
  })

  const normalizedType = type.toLowerCase()
  if (normalizedType.includes('assess') || normalizedType.includes('quiz') || normalizedType.includes('考官') || normalizedType.includes('评测')) {
    const escapedConcept = (conceptName || '机器学习').replace(/'/g, "\\'")
    html += `<div class="resource-callout">
      <div>
        <strong>评测联动已就绪：</strong>已为您准备了针对此概念的自适应多步评测。
      </div>
      <button onclick="window.startInteractiveQuiz && window.startInteractiveQuiz('${escapedConcept}')" class="resource-callout__action">
        去测验板作答
      </button>
    </div>`
  } else if (normalizedType.includes('director') || normalizedType.includes('video') || normalizedType.includes('导演') || normalizedType.includes('视频')) {
    html += `<div class="resource-callout">
      <div>
        <strong>视频演示已就绪：</strong>已为您量身定制并合成了该知识点的教学短视频。
      </div>
      <button onclick="window.startInteractiveVideo && window.startInteractiveVideo()" class="resource-callout__action">
        播放讲解视频
      </button>
    </div>`
  }

  return html
}

function mountCustomMindmaps() {
  nextTick(async () => {
    try {
      const placeholders = document.querySelectorAll('.custom-mindmap-placeholder:not([data-mounted="true"])')
      if (!placeholders.length) return
      const { default: CollapsibleMindmap } = await import('../components/CollapsibleMindmap.vue')
      placeholders.forEach((el) => {
        const rawCode = decodeURIComponent(el.getAttribute('data-code') || '')
        const app = createApp(CollapsibleMindmap, { code: rawCode })
        app.mount(el)
        el.setAttribute('data-mounted', 'true')
        el.__vue_app__ = app
      })
    } catch (err) {
      console.error('Mount custom mindmaps error:', err)
    }
  })
}

function cleanupCustomMindmaps() {
  const elements = document.querySelectorAll('.custom-mindmap-placeholder[data-mounted="true"]')
  elements.forEach((el) => {
    if (el.__vue_app__) {
      try {
        el.__vue_app__.unmount()
      } catch (e) {}
      delete el.__vue_app__
    }
  })
}

function initMermaid() {
  if (typeof window.mermaid !== 'undefined') {
    nextTick(() => {
      try {
        window.mermaid.initialize({
          startOnLoad: false,
          theme: 'default',
          securityLevel: 'loose',
          themeVariables: {
            background: '#ffffff',
            primaryColor: '#4a5c6a',
            primaryTextColor: '#06141b',
            lineColor: '#253745',
            fontSize: '12px'
          }
        })
        const elements = document.querySelectorAll('.mermaid:not([data-processed="true"])')
        elements.forEach((el) => {
          try {
            const rawCode = decodeURIComponent(el.getAttribute('data-code') || '')
            if (rawCode) {
              el.textContent = rawCode
            }
            window.mermaid.init(undefined, el)
          } catch (err) {
            console.error('Individual Mermaid render error:', err)
          }
        })
      } catch (err) {
        console.error('Mermaid render error:', err)
      }
    })
  }
}

function renderAllDiagrams() {
  initMermaid()
  mountCustomMindmaps()
  if (typeof window.Prism !== 'undefined') {
    nextTick(() => {
      window.Prism.highlightAll()
    })
  }
}
</script>

<template>
  <div v-if="loading" class="dashboard-skeleton" aria-label="正在加载仪表盘">
    <div class="dashboard-skeleton__hero" />
    <div class="dashboard-skeleton__grid"><span v-for="i in 4" :key="i" /></div>
  </div>
  <div v-else class="dashboard-page space-y-7 max-w-[1380px] mx-auto soft-reveal">

    <header class="dashboard-heading">
      <div>
        <h1>今日学习</h1>
        <p>{{ dashboardSummary?.profile_alignment?.course?.title || dashboardSummary?.course?.title || '选择课程后开始个性化学习' }}</p>
      </div>
      <span v-if="dashboardSummary?.aggregation?.updated_at" class="dashboard-updated-at">
        更新于 {{ new Date(dashboardSummary.aggregation.updated_at).toLocaleString() }}
      </span>
    </header>

    <AggregationStatus
      :course-id="dashboardSummary?.course?.id || workspaceOverview?.course?.id || currentCourseId"
      class="dashboard-feedback"
    />

    <section class="dashboard-metrics" aria-label="学习摘要">
      <details v-for="item in summaryMetrics" :key="item.label" class="dashboard-metric">
        <summary>
          <span>{{ item.label }}</span>
          <strong>{{ item.value }}</strong>
          <small>{{ item.detail }}</small>
        </summary>
        <div class="dashboard-metric__sources">
          <template v-if="item.source_refs?.length">
            <span v-for="source in item.source_refs" :key="`${source.type}-${source.id}`">{{ sourceLabel(source) }}</span>
          </template>
          <span v-else>暂无可追溯学习记录</span>
        </div>
      </details>
    </section>

    <p v-if="aggregationNotice" class="dashboard-sync-notice" role="status">
      <Clock :size="16" />{{ aggregationNotice }}
    </p>

    <section data-testid="dashboard-today-tasks" class="dashboard-decision-grid">
      <article class="dashboard-focus" data-testid="dashboard-primary-task">
        <div class="dashboard-focus__meta">
          <span>{{ dashboardSummary?.primary_task?.task_kind === 'review' ? '今日复习' : '今日主任务' }}</span>
          <span>{{ estimateLabel(focus.estimated_minutes) }}</span>
        </div>
        <div class="dashboard-focus__copy">
          <h2>{{ focus.title }}</h2>
          <p class="dashboard-focus__strategy">{{ focus.strategy }}</p>
        </div>
        <dl class="dashboard-focus__facts">
          <div><dt>为什么现在做</dt><dd>{{ focus.reason }}</dd></div>
          <div><dt>完成条件</dt><dd>{{ focus.completion_criteria }}</dd></div>
          <div><dt>建议资源</dt><dd>{{ dashboardSummary?.primary_task?.recommended_resource || '当前学习空间' }}</dd></div>
        </dl>
        <div class="dashboard-focus__footer">
          <details class="dashboard-source-disclosure">
            <summary>查看决策依据</summary>
            <div>
              <span v-for="source in focus.source_refs" :key="`${source.type}-${source.id}`">{{ sourceLabel(source) }}</span>
              <span v-if="!focus.source_refs?.length">依据将在完成画像或路径后显示。</span>
            </div>
          </details>
          <button type="button" class="dashboard-primary-action" data-testid="dashboard-primary-action" @click="openPrimaryAction">
            <Play :size="17" />{{ primaryAction.label }}<ArrowRight :size="17" />
          </button>
        </div>
      </article>

      <aside class="dashboard-side-summary" aria-label="复习与薄弱点摘要">
        <section>
          <header><div><CalendarDays :size="17" /><h2>到期复习</h2></div><span>{{ reviewSummary.due_count }} 项</span></header>
          <ol v-if="reviewSummary.items?.length">
            <li v-for="item in reviewSummary.items.slice(0, 3)" :key="item.id || item.knowledge_point_id">
              <strong>{{ item.title || item.concept || '未命名知识点' }}</strong>
              <span>{{ item.next_review_at ? new Date(item.next_review_at).toLocaleDateString() : '今天' }}</span>
            </li>
          </ol>
          <p v-else>今天没有到期复习。</p>
        </section>
        <section>
          <header><div><Target :size="17" /><h2>优先强化</h2></div><button type="button" @click="router.push('/profile/learning')">查看画像</button></header>
          <ol v-if="weakSummary.length">
            <li v-for="item in weakSummary.slice(0, 3)" :key="item.id || item.title" class="dashboard-weak-item" data-testid="dashboard-weak-item">
              <div class="dashboard-weak-item__heading">
                <strong>{{ item.title || item.id || '未命名知识点' }}</strong>
                <span>{{ weakMasteryLabel(item) }}</span>
              </div>
              <p class="dashboard-weak-item__reason">{{ item.weak_reason || '薄弱原因待确认。' }}</p>
              <div class="dashboard-weak-item__dimensions">
                <span v-for="dimension in (item.profile_dimensions || [])" :key="`${item.id || item.title}-${dimension.key}`">
                  {{ dimension.label || '关联画像维度' }}：{{ dimension.status || '待确认' }}
                </span>
              </div>
              <p class="dashboard-weak-item__snapshot">{{ weakSnapshotLabel(item) }}</p>
              <details class="dashboard-weak-item__evidence">
                <summary>查看来源与学习事件</summary>
                <ul>
                  <li v-for="source in (item.source_refs || [])" :key="`${source.type}-${source.id}-${source.label}`">来源：{{ sourceLabel(source) }}</li>
                  <li v-for="event in (item.event_refs || [])" :key="`event-${event.id}`">学习事件：{{ event.label || '支持该知识点的学习事件' }}</li>
                  <li v-if="!(item.source_refs || []).length && !(item.event_refs || []).length">来源与学习事件：待确认</li>
                </ul>
              </details>
              <button
                v-if="item.next_action?.route"
                type="button"
                class="dashboard-weak-item__action"
                :aria-label="`${item.next_action.label || '开始强化'}：${item.title || item.id}`"
                @click="openWeakPoint(item)"
              >
                {{ item.next_action.label || '开始强化' }} <ArrowRight :size="14" />
              </button>
              <span v-else class="dashboard-weak-item__pending">路径待确认</span>
            </li>
          </ol>
          <div v-else class="dashboard-weak-empty">
            <p>{{ weakSummaryEmptyCopy }}</p>
            <button type="button" @click="router.push(hasProfileSnapshot ? '/profile/learning' : '/onboarding')">
              {{ hasProfileSnapshot ? '查看画像证据' : '完成画像/诊断' }} <ArrowRight :size="14" />
            </button>
          </div>
        </section>
      </aside>
    </section>

    <details v-if="summaryStrategies.length > 1" class="dashboard-next-tasks" data-testid="dashboard-next-tasks">
      <summary>
        <span><strong>接下来还有 {{ summaryStrategies.length - 1 }} 项安排</strong><small>当前任务完成后再进入，不与主动作竞争。</small></span>
        <ChevronDown :size="18" />
      </summary>
      <ol>
        <li v-for="item in summaryStrategies.slice(1)" :key="item.id">
          <div><strong>{{ item.title }}</strong><p>{{ item.strategy }}</p></div>
          <span>{{ item.recommended_resource }} · {{ estimateLabel(item.estimate_minutes) }}</span>
        </li>
      </ol>
    </details>

    <section class="dashboard-trend-summary">
      <header>
        <div><h2>最近学习变化</h2><p>只显示有效学习事件形成的掌握变化。</p></div>
        <button type="button" @click="router.push('/profile')">前往个人中心 <ArrowRight :size="14" /></button>
      </header>
      <LearningTrendChart :points="trendPoints" />
      <p class="dashboard-trend-activity">近 30 天记录 {{ activitySummary.event_count }} 条有效学习活动，分布在 {{ activitySummary.active_days }} 天。掌握度曲线只显示已处理的有效证据。</p>
    </section>

    <details class="dashboard-detail" data-testid="dashboard-detail">
      <summary class="dashboard-detail__summary">
        <span class="dashboard-detail__summary-icon"><GraduationCap :size="19" /></span>
        <span class="dashboard-detail__summary-copy">
          <strong>详细学习分析</strong>
          <span>查看课程学情诊断</span>
        </span>
        <ChevronDown :size="18" class="dashboard-detail__chevron" />
      </summary>
      <div class="dashboard-detail__body">

    <section v-if="profileAnalysis && profile" class="dashboard-detail-section dashboard-analysis-section">
      <header class="dashboard-section-heading">
        <div class="dashboard-section-heading__title">
          <span class="dashboard-section-heading__icon"><GraduationCap :size="18" /></span>
          <div>
            <h2>课程学情诊断</h2>
            <p>基于当前课程和学习状态生成</p>
          </div>
        </div>
        <div class="dashboard-section-heading__meta">
            <span>{{ dashboardSummary?.profile_alignment?.course?.title || dashboardSummary?.course?.title || '当前课程未知' }}</span>
            <span>v{{ dashboardSummary?.profile_alignment?.course?.version || '未知' }}</span>
        </div>
      </header>

      <div class="dashboard-analysis-grid">
        <article class="dashboard-analysis-report">
          <h3>诊断摘要</h3>
            <p>{{ profileAnalysis.dashboard_report || '诊断结果正在生成，完成后会保留在学习画像中。' }}</p>
            <p class="dashboard-analysis-source">
              画像快照：{{ dashboardSummary?.profile_alignment?.profile_snapshot?.version || '未知' }}
            </p>
        </article>

        <aside class="dashboard-analysis-signals" aria-label="当前学习状态">
          <h3>学习状态</h3>
          <div class="dashboard-signal">
            <div><span>认知负荷</span><strong>{{ Math.round(profile.cognitive_load * 100) }}%</strong></div>
            <div class="dashboard-meter"><span :class="{ 'dashboard-meter__fill--warning': profile.cognitive_load > 0.6 }" :style="{ width: (profile.cognitive_load * 100) + '%' }" /></div>
          </div>
          <div class="dashboard-signal">
            <div><span>挫败风险</span><strong>{{ Math.round(profile.frustration_index * 100) }}%</strong></div>
            <div class="dashboard-meter"><span :class="{ 'dashboard-meter__fill--danger': profile.frustration_index > 0.4 }" :style="{ width: (profile.frustration_index * 100) + '%' }" /></div>
          </div>
          <dl class="dashboard-analysis-facts">
            <div><dt>学习风格</dt><dd>{{ profileInsight('cognitive_style') }}</dd></div>
            <div><dt>学习动机</dt><dd>{{ profileInsight('motivation_type') }}</dd></div>
          </dl>
          <button type="button" class="dashboard-secondary-action" @click="router.push({ path: '/profile', query: { student_id: currentStudentId } })">
            查看完整学习画像 <ArrowRight :size="14" />
          </button>
        </aside>
      </div>
    </section>

      </div>
    </details>

    <!-- 视频微课播放模态窗 -->
    <VideoRenderPanel
      :visible="showVideoPanel"
      :videoUrl="videoPanelUrl"
      :studentId="props.studentId"
      @close="showVideoPanel = false"
    />

    <Teleport to="body">
      <div v-if="activeResource" class="dashboard-modal-backdrop" @click="closeResourceViewer">
        <section class="dashboard-modal dashboard-resource-modal" role="dialog" aria-modal="true" aria-labelledby="resource-modal-title" @click.stop>
          <header class="dashboard-modal__header">
            <div>
              <span class="dashboard-status-label">{{ activeResource.res.resource_type }}</span>
              <h3 id="resource-modal-title">{{ activeResource.concept }}</h3>
              <p>生成智能体：{{ activeResource.res.role }}</p>
            </div>
            <button type="button" class="dashboard-icon-action" aria-label="关闭资源预览" title="关闭" @click="closeResourceViewer"><X :size="18" /></button>
          </header>

          <div class="dashboard-resource-modal__body">
            <div v-if="activeResource.res.status === 'not_generated' && !isGenerating" class="dashboard-resource-state">
              <span class="dashboard-resource-state__icon"><BookOpen :size="25" /></span>
              <div><h4>该资源尚未生成</h4><p>系统会依据当前知识点与学习画像生成资源，并保存到对应学习空间。</p></div>
              <div class="dashboard-resource-preview"><strong>内容预览</strong><p>{{ activeResource.res.overview }}</p></div>
              <button type="button" class="dashboard-button dashboard-button--primary" @click="generateResource">开始生成</button>
            </div>

            <div v-else-if="isGenerating" class="dashboard-resource-state">
              <span class="dashboard-spinner dashboard-spinner--large" />
              <div><h4>资源正在生成</h4><p>{{ activeResource.res.role }}正在整理内容，完成后会自动归档。</p></div>
            </div>

            <div v-else-if="activeResource.res.status === 'generated'" class="dashboard-resource-content">
              <div class="dashboard-resource-content__toolbar">
                <div><strong>资源已就绪</strong><p>可在此预览，也可以进入对应学习空间继续。</p></div>
                <button type="button" class="dashboard-button dashboard-button--primary dashboard-button--compact" @click="openInWorkspace">进入学习空间 <ArrowRight :size="14" /></button>
              </div>

              <div v-if="activeResource.res.role === '视频推荐官' || activeResource.res.role === '虚拟导演' || activeResource.res.resource_type === '自适应推荐视频' || activeResource.res.resource_type === '虚拟人视频脚本'" class="dashboard-resource-content__viewer">
                <VideoPlayerCard v-if="safeParseJson(activeResourceContent).length > 0" :videos="safeParseJson(activeResourceContent)" :concept="activeResource.concept" />
                <div v-else class="markdown-body dashboard-markdown" v-html="renderMarkdown(activeResourceContent || '内容加载中...', activeResource?.res?.resource_type || '', activeResource?.concept || '')" />
              </div>
              <div v-else class="markdown-body dashboard-markdown" v-html="renderMarkdown(activeResourceContent || '内容加载中...', activeResource?.res?.resource_type || '', activeResource?.concept || '')" />
            </div>
          </div>

          <footer class="dashboard-modal__footer"><button type="button" class="dashboard-button dashboard-button--secondary" @click="closeResourceViewer">关闭窗口</button></footer>
        </section>
      </div>
    </Teleport>

  </div>
</template>

<style scoped>
.dashboard-page {
  padding-top: var(--space-6);
  padding-bottom: 2rem;
}

.dashboard-heading { display: flex; align-items: end; justify-content: space-between; gap: 24px; }
.dashboard-heading h1 { margin: 0; color: var(--color-text); font-family: var(--font-heading); font-size: 30px; font-weight: 620; line-height: 1.2; }
.dashboard-heading p { margin: 6px 0 0; color: var(--color-text-secondary); font-size: 15px; }
.dashboard-course-alignment { display: block; margin-top: 4px; color: var(--color-text-muted); font-size: 14px; line-height: 1.45; }
.dashboard-analysis-source { margin-top: 8px; color: var(--color-text-secondary); font-size: 14px; line-height: 1.5; }
.dashboard-updated-at { flex: 0 0 auto; color: var(--color-text-muted); font-size: 14px; }

.dashboard-metrics { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); border-block: 1px solid var(--color-border); }
.dashboard-metric { min-width: 0; border-left: 1px solid var(--color-border); }
.dashboard-metric:first-child { border-left: 0; }
.dashboard-metric summary { display: grid; min-height: 96px; align-content: center; gap: 3px; padding: 14px 18px; cursor: pointer; list-style: none; }
.dashboard-metric summary::-webkit-details-marker { display: none; }
.dashboard-metric summary:hover { background: var(--color-surface-subtle); }
.dashboard-metric summary span, .dashboard-metric summary small { color: var(--color-text-secondary); font-size: 14px; }
.dashboard-metric summary strong { color: var(--color-text); font-size: 23px; font-weight: 680; font-variant-numeric: tabular-nums; }
.dashboard-metric__sources { display: grid; gap: 5px; padding: 12px 18px 16px; color: var(--color-text-secondary); border-top: 1px solid var(--color-border); font-size: 14px; line-height: 1.45; }

.dashboard-sync-notice { display: flex; min-height: 42px; align-items: center; gap: 9px; margin: 0; padding: 10px 14px; color: #344957; border: 1px solid #ccd0cf; background: #f1f4f4; font-size: 14px; line-height: 1.5; }

.dashboard-decision-grid { display: grid; grid-template-columns: minmax(0, 2.55fr) minmax(280px, 1fr); gap: 28px; }
.dashboard-focus { display: flex; min-width: 0; min-height: 400px; flex-direction: column; padding: 34px; color: #f3f6f6; border-radius: var(--radius-panel); background: #11212d; }
.dashboard-focus__meta { display: flex; align-items: center; justify-content: space-between; gap: 20px; color: #ccd0cf; font-size: 14px; }
.dashboard-focus__meta span:first-child { color: #ffffff; font-weight: 700; }
.dashboard-focus__copy { margin-top: 42px; }
.dashboard-focus__copy h2 { max-width: 22ch; margin: 0; overflow-wrap: anywhere; color: #ffffff; font-family: var(--font-display); font-size: 34px; font-weight: 620; line-height: 1.23; }
.dashboard-focus__strategy { max-width: 67ch; margin: 16px 0 0; color: #dce2e3; font-size: 16px; line-height: 1.7; }
.dashboard-focus__facts { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 20px; margin: 34px 0 0; padding: 22px 0; border-block: 1px solid #4a5c6a; }
.dashboard-focus__facts div { min-width: 0; }
.dashboard-focus__facts dt { color: #9ba8ab; font-size: 14px; }
.dashboard-focus__facts dd { margin: 7px 0 0; color: #edf1f2; font-size: 14px; line-height: 1.55; }
.dashboard-focus__footer { display: flex; align-items: end; justify-content: space-between; gap: 24px; margin-top: auto; padding-top: 24px; }
.dashboard-source-disclosure { min-width: 0; color: #ccd0cf; font-size: 14px; }
.dashboard-source-disclosure summary { width: fit-content; cursor: pointer; }
.dashboard-source-disclosure div { display: flex; flex-wrap: wrap; gap: 6px 14px; margin-top: 9px; }
.dashboard-primary-action { display: inline-flex; min-height: 46px; flex: 0 0 auto; align-items: center; justify-content: center; gap: 9px; padding: 0 18px; color: #11212d; border: 1px solid #ffffff; border-radius: var(--radius-control); background: #ffffff; font-size: 15px; font-weight: 700; cursor: pointer; }
.dashboard-primary-action:hover { color: #000000; background: #edf1f2; }

.dashboard-side-summary { display: grid; min-width: 0; align-content: start; gap: 0; border-block: 1px solid var(--color-border); }
.dashboard-side-summary > section { padding: 24px 18px; border-bottom: 1px solid var(--color-border); }
.dashboard-side-summary > section:last-child { border-bottom: 0; }
.dashboard-side-summary header { display: flex; align-items: center; justify-content: space-between; gap: 14px; }
.dashboard-side-summary header > div { display: flex; align-items: center; gap: 8px; }
.dashboard-side-summary h2 { margin: 0; color: var(--color-text); font-size: 17px; font-weight: 680; }
.dashboard-side-summary header span, .dashboard-side-summary header button { color: var(--color-accent); font-size: 14px; font-weight: 680; }
.dashboard-side-summary header button { border: 0; background: transparent; cursor: pointer; }
.dashboard-side-summary ol { margin: 14px 0 0; padding: 0; list-style: none; }
.dashboard-side-summary li { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 12px; padding: 11px 0; border-top: 1px solid var(--color-border); }
.dashboard-side-summary li:first-child { border-top: 0; }
.dashboard-side-summary li strong { overflow: hidden; color: var(--color-text); font-size: 14px; font-weight: 650; text-overflow: ellipsis; white-space: nowrap; }
.dashboard-side-summary li span, .dashboard-side-summary p { color: var(--color-text-secondary); font-size: 14px; }
.dashboard-side-summary p { margin: 15px 0 0; line-height: 1.55; }
.dashboard-weak-item { display: block !important; padding: 16px 0 !important; }
.dashboard-weak-item__heading { display: flex; align-items: start; justify-content: space-between; gap: 12px; }
.dashboard-weak-item__heading strong { min-width: 0; overflow-wrap: anywhere; color: var(--color-text); font-size: 15px; font-weight: 680; line-height: 1.45; white-space: normal; }
.dashboard-weak-item__heading span { flex: 0 0 auto; color: var(--color-text-secondary); font-size: 14px; line-height: 1.45; text-align: right; }
.dashboard-weak-item__reason { margin: 8px 0 0 !important; color: var(--color-text-secondary); line-height: 1.55; }
.dashboard-weak-item__dimensions { display: grid; gap: 5px; margin-top: 10px; color: var(--color-text-secondary); font-size: 14px; line-height: 1.45; }
.dashboard-weak-item__snapshot { margin: 9px 0 0 !important; color: var(--color-text-muted) !important; overflow-wrap: anywhere; font-size: 14px !important; }
.dashboard-weak-item__evidence { margin-top: 10px; color: var(--color-text-secondary); font-size: 14px; }
.dashboard-weak-item__evidence summary { width: fit-content; color: var(--color-accent); cursor: pointer; }
.dashboard-weak-item__evidence ul { display: grid; gap: 5px; margin: 8px 0 0; padding: 0; list-style: none; line-height: 1.45; }
.dashboard-weak-item__evidence li { display: block; padding: 0; border: 0; overflow-wrap: anywhere; }
.dashboard-weak-item__action { display: inline-flex; min-height: 36px; align-items: center; gap: 5px; margin-top: 12px; padding: 0 11px; color: #ffffff; border: 1px solid #11212d; border-radius: var(--radius-control); background: #11212d; font-size: 14px; font-weight: 650; cursor: pointer; }
.dashboard-weak-item__action:hover { background: #253745; }
.dashboard-weak-item__pending { display: inline-block; margin-top: 12px; color: var(--color-text-muted); font-size: 14px; }
.dashboard-weak-empty { display: grid; gap: 12px; }
.dashboard-weak-empty p { margin: 15px 0 0; }
.dashboard-weak-empty button { display: inline-flex; width: fit-content; min-height: 36px; align-items: center; gap: 5px; padding: 0 10px; color: var(--color-accent); border: 1px solid var(--color-border-strong); border-radius: var(--radius-control); background: var(--color-surface); font-size: 14px; font-weight: 650; cursor: pointer; }

.dashboard-next-tasks { border-block: 1px solid var(--color-border); }
.dashboard-next-tasks > summary { display: flex; min-height: 68px; align-items: center; justify-content: space-between; gap: 20px; cursor: pointer; list-style: none; }
.dashboard-next-tasks > summary::-webkit-details-marker { display: none; }
.dashboard-next-tasks > summary span { display: grid; gap: 3px; }
.dashboard-next-tasks > summary strong { color: var(--color-text); font-size: 15px; }
.dashboard-next-tasks > summary small { color: var(--color-text-secondary); font-size: 14px; }
.dashboard-next-tasks > summary svg { color: var(--color-text-muted); transition: transform 160ms ease; }
.dashboard-next-tasks[open] > summary svg { transform: rotate(180deg); }
.dashboard-next-tasks ol { margin: 0; padding: 0 0 14px; list-style: none; }
.dashboard-next-tasks li { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 24px; padding: 14px 0; border-top: 1px solid var(--color-border); }
.dashboard-next-tasks li strong { color: var(--color-text); font-size: 15px; }
.dashboard-next-tasks li p { margin: 4px 0 0; color: var(--color-text-secondary); font-size: 14px; line-height: 1.5; }
.dashboard-next-tasks li > span { color: var(--color-text-secondary); font-size: 14px; white-space: nowrap; }

.dashboard-trend-summary { padding-block: 4px; }
.dashboard-trend-summary header { display: flex; align-items: end; justify-content: space-between; gap: 24px; margin-bottom: 12px; }
.dashboard-trend-summary h2 { margin: 0; color: var(--color-text); font-size: 17px; font-weight: 680; }
.dashboard-trend-summary p { margin: 4px 0 0; color: var(--color-text-secondary); font-size: 14px; }
.dashboard-trend-activity { margin: 10px 0 0; color: var(--color-text-secondary); font-size: 14px; line-height: 1.5; }
.dashboard-trend-summary button { display: inline-flex; align-items: center; gap: 6px; color: var(--color-accent); border: 0; background: transparent; font-size: 14px; font-weight: 680; cursor: pointer; }

.dashboard-detail {
  border-top: 1px solid var(--color-border);
  border-bottom: 1px solid var(--color-border);
  background: var(--color-surface);
}

.dashboard-detail__summary {
  display: grid;
  min-height: 76px;
  grid-template-columns: 38px minmax(0, 1fr) auto 20px;
  align-items: center;
  gap: 14px;
  padding: 0 18px;
  color: var(--color-text);
  cursor: pointer;
  list-style: none;
}

.dashboard-detail__summary::-webkit-details-marker { display: none; }
.dashboard-detail__summary:hover { background: var(--color-surface-subtle); }
.dashboard-detail__summary-icon {
  display: grid;
  width: 36px;
  height: 36px;
  place-items: center;
  color: var(--color-accent);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-control);
  background: var(--color-accent-soft);
}
.dashboard-detail__summary-copy { display: grid; min-width: 0; gap: 2px; }
.dashboard-detail__summary-copy strong { font-size: 16px; font-weight: 680; }
.dashboard-detail__summary-copy span,
.dashboard-detail__summary-meta { color: var(--color-text-secondary); font-size: 14px; }
.dashboard-detail__summary-meta { white-space: nowrap; }
.dashboard-detail__chevron { color: var(--color-text-muted); transition: transform 160ms ease; }
.dashboard-detail[open] .dashboard-detail__chevron { transform: rotate(180deg); }
.dashboard-detail__body {
  padding: 0 22px 24px;
  border-top: 1px solid var(--color-border);
  background: #ffffff;
}

.dashboard-detail-section {
  padding: 28px 0;
  border-bottom: 1px solid var(--color-border);
}

.dashboard-detail-section:last-child { border-bottom: 0; }

.dashboard-section-heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 24px;
  margin-bottom: 20px;
}

.dashboard-section-heading--compact { align-items: center; }
.dashboard-section-heading__title { display: flex; min-width: 0; align-items: flex-start; gap: 11px; }
.dashboard-section-heading__icon {
  display: grid;
  width: 34px;
  height: 34px;
  flex: 0 0 34px;
  place-items: center;
  color: var(--color-accent);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-control);
  background: var(--color-accent-soft);
}
.dashboard-section-heading h2,
.dashboard-section-heading h3,
.dashboard-section-heading p { margin: 0; }
.dashboard-section-heading h2 { color: var(--color-text); font-size: 18px; font-weight: 680; line-height: 1.35; }
.dashboard-section-heading p { margin-top: 4px; color: var(--color-text-secondary); font-size: 14px; line-height: 1.5; }
.dashboard-section-heading__meta { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 8px; }
.dashboard-section-heading__meta span,
.dashboard-status-label {
  display: inline-flex;
  min-height: 28px;
  align-items: center;
  padding: 4px 9px;
  color: var(--color-text-secondary);
  border: 1px solid var(--color-border);
  border-radius: 999px;
  background: var(--color-surface-subtle);
  font-size: 14px;
  font-weight: 600;
  line-height: 1.25;
}

.dashboard-analysis-grid { display: grid; grid-template-columns: minmax(0, 1.7fr) minmax(300px, .7fr); gap: 28px; }
.dashboard-analysis-report { padding-right: 28px; border-right: 1px solid var(--color-border); }
.dashboard-analysis-report h3,
.dashboard-analysis-signals h3 { margin: 0 0 12px; color: var(--color-text); font-size: 15px; font-weight: 680; }
.dashboard-analysis-report p { max-width: 72ch; margin: 0; color: var(--color-text-secondary); font-size: 15px; line-height: 1.75; white-space: pre-wrap; }
.dashboard-analysis-signals { display: grid; align-content: start; gap: 16px; }
.dashboard-signal { display: grid; gap: 7px; }
.dashboard-signal > div:first-child { display: flex; align-items: center; justify-content: space-between; gap: 12px; color: var(--color-text-secondary); font-size: 14px; }
.dashboard-signal strong { color: var(--color-text); font-variant-numeric: tabular-nums; }
.dashboard-meter { height: 7px; overflow: hidden; border-radius: 999px; background: var(--color-surface-muted); }
.dashboard-meter > span { display: block; height: 100%; border-radius: inherit; background: var(--color-accent); }
.dashboard-meter > .dashboard-meter__fill--warning { background: var(--color-warning); }
.dashboard-meter > .dashboard-meter__fill--danger { background: var(--color-danger); }
.dashboard-analysis-facts { display: grid; gap: 8px; margin: 0; padding-top: 14px; border-top: 1px solid var(--color-border); }
.dashboard-analysis-facts div { display: flex; align-items: center; justify-content: space-between; gap: 16px; }
.dashboard-analysis-facts dt { color: var(--color-text-secondary); font-size: 14px; }
.dashboard-analysis-facts dd { margin: 0; color: var(--color-text); font-size: 14px; font-weight: 650; }

.dashboard-secondary-action {
  display: inline-flex;
  min-height: 36px;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 0 12px;
  color: var(--color-text-secondary);
  border: 1px solid var(--color-border-strong);
  border-radius: var(--radius-control);
  background: var(--color-surface);
  font-size: 14px;
  font-weight: 650;
  cursor: pointer;
}
.dashboard-secondary-action:hover { color: var(--color-text); background: var(--color-surface-subtle); }

.dashboard-icon-action {
  display: grid;
  width: 36px;
  height: 36px;
  flex: 0 0 36px;
  place-items: center;
  color: var(--color-text-secondary);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-control);
  background: var(--color-surface);
  cursor: pointer;
}
.dashboard-icon-action:hover { color: var(--color-text); background: var(--color-surface-subtle); }
.dashboard-modal-backdrop { position: fixed; inset: 0; z-index: 50; display: grid; place-items: center; padding: 24px; background: rgb(33 28 24 / 46%); }
.dashboard-modal { display: grid; width: min(940px, calc(100vw - 48px)); max-height: calc(100vh - 48px); grid-template-rows: auto minmax(0, 1fr) auto; overflow: hidden; color: var(--color-text); border: 1px solid var(--color-border); border-radius: var(--radius-panel); background: var(--color-surface); box-shadow: var(--shadow-popover); font-family: var(--font-sans); animation: dashboard-modal-in 160ms cubic-bezier(.2,.8,.2,1); }
@keyframes dashboard-modal-in { from { transform: translateY(8px); opacity: .86; } to { transform: translateY(0); opacity: 1; } }
.dashboard-modal__header { display: flex; align-items: flex-start; justify-content: space-between; gap: 20px; padding: 20px 22px; border-bottom: 1px solid var(--color-border); }
.dashboard-modal__header h3 { margin: 0; color: var(--color-text); font-size: 18px; font-weight: 680; }
.dashboard-modal__header p { margin: 5px 0 0; color: var(--color-text-secondary); font-size: 14px; line-height: 1.5; }
.dashboard-modal__footer { display: flex; justify-content: flex-end; padding: 14px 22px; border-top: 1px solid var(--color-border); background: var(--color-surface-subtle); }
.dashboard-button { display: inline-flex; min-height: 40px; align-items: center; justify-content: center; gap: 7px; padding: 0 15px; border: 1px solid transparent; border-radius: var(--radius-control); font-size: 14px; font-weight: 680; cursor: pointer; }
.dashboard-button--compact { min-height: 36px; padding-inline: 12px; }
.dashboard-button--primary { color: #ffffff; border-color: #11212d; background: #11212d; }
.dashboard-button--primary:hover { background: #000000; }
.dashboard-button--secondary { color: var(--color-text-secondary); border-color: var(--color-border-strong); background: var(--color-surface); }
.dashboard-button--secondary:hover { color: var(--color-text); background: var(--color-surface-subtle); }
.dashboard-button:disabled { opacity: .46; cursor: not-allowed; }
.dashboard-spinner,
.resource-spinner { display: inline-block; width: 16px; height: 16px; border: 2px solid var(--color-border-strong); border-top-color: var(--color-accent); border-radius: 50%; animation: dashboard-spin .8s linear infinite; }
.dashboard-spinner--large { width: 30px; height: 30px; border-width: 3px; }
@keyframes dashboard-spin { to { transform: rotate(360deg); } }
.dashboard-inline-state { display: flex; min-height: 96px; align-items: center; justify-content: center; gap: 10px; color: var(--color-text-secondary); font-size: 14px; text-align: center; }
.dashboard-inline-state p { margin: 0; }

.dashboard-resource-modal { width: min(920px, calc(100vw - 48px)); }
.dashboard-resource-modal__body { min-height: 0; padding: 24px; overflow: auto; }
.dashboard-resource-state { display: grid; min-height: 360px; align-content: center; justify-items: center; gap: 16px; text-align: center; }
.dashboard-resource-state__icon { display: grid; width: 54px; height: 54px; place-items: center; color: var(--color-accent); border: 1px solid var(--color-border); border-radius: var(--radius-panel); background: var(--color-accent-soft); }
.dashboard-resource-state h4 { margin: 0; color: var(--color-text); font-size: 18px; font-weight: 680; }
.dashboard-resource-state p { max-width: 58ch; margin: 5px 0 0; color: var(--color-text-secondary); font-size: 14px; line-height: 1.6; }
.dashboard-resource-preview { width: min(620px, 100%); padding: 16px; border: 1px solid var(--color-border); border-radius: var(--radius-panel); background: var(--color-surface-subtle); text-align: left; }
.dashboard-resource-preview strong { color: var(--color-text); font-size: 14px; }
.dashboard-resource-preview p { margin: 5px 0 0; }
.dashboard-resource-content { display: grid; gap: 18px; }
.dashboard-resource-content__toolbar { display: flex; align-items: center; justify-content: space-between; gap: 20px; padding: 14px 16px; border: 1px solid var(--color-border); background: var(--color-surface-subtle); }
.dashboard-resource-content__toolbar strong { color: var(--color-text); font-size: 14px; }
.dashboard-resource-content__toolbar p { margin: 3px 0 0; color: var(--color-text-secondary); font-size: 14px; }
.dashboard-markdown { max-width: 100%; padding: 20px; overflow-x: auto; color: var(--color-text-secondary); border: 1px solid var(--color-border); border-radius: var(--radius-panel); background: var(--color-surface); font-size: 15px; line-height: 1.75; }

.dashboard-markdown :deep(.resource-accordion),
.dashboard-markdown :deep(.resource-hint-ladder),
.dashboard-markdown :deep(.resource-diagram),
.dashboard-markdown :deep(.resource-callout) { margin: 16px 0; border: 1px solid var(--color-border); border-radius: var(--radius-panel); background: var(--color-surface); }
.dashboard-markdown :deep(.resource-accordion--nested) { margin: 8px 0; }
.dashboard-markdown :deep(.resource-accordion__trigger) { display: flex; width: 100%; min-height: 42px; align-items: center; justify-content: space-between; gap: 16px; padding: 0 14px; color: var(--color-text); border: 0; background: var(--color-surface-subtle); font-size: 14px; font-weight: 650; cursor: pointer; }
.dashboard-markdown :deep(.resource-accordion__body) { padding: 14px 16px; border-top: 1px solid var(--color-border); }
.dashboard-markdown :deep(.resource-hint-ladder) { padding: 14px; background: var(--color-surface-subtle); }
.dashboard-markdown :deep(.resource-hint-ladder__title) { margin-bottom: 8px; color: var(--color-text); font-size: 14px; font-weight: 680; }
.dashboard-markdown :deep(.resource-diagram__header) { display: flex; min-height: 44px; align-items: center; justify-content: space-between; gap: 16px; padding: 0 14px; border-bottom: 1px solid var(--color-border); color: var(--color-text); font-size: 14px; font-weight: 680; }
.dashboard-markdown :deep(.resource-diagram__format) { color: var(--color-text-muted); font-family: var(--font-mono); font-size: 14px; font-weight: 500; }
.dashboard-markdown :deep(.resource-diagram__canvas) { max-height: 360px; padding: 16px; overflow: auto; }
.dashboard-markdown :deep(.mermaid) { display: flex; width: 100%; justify-content: center; }
.dashboard-markdown :deep(.resource-rendering) { display: flex; min-height: 120px; flex-direction: column; align-items: center; justify-content: center; gap: 10px; color: var(--color-text-secondary); font-size: 14px; }
.dashboard-markdown :deep(.resource-code-block) { position: relative; margin: 16px 0; }
.dashboard-markdown :deep(.resource-code-block pre) { margin: 0; padding: 18px; overflow-x: auto; color: #f1f4f4; border-radius: var(--radius-panel); background: #11212d; font-family: var(--font-mono); font-size: 14px; line-height: 1.65; }
.dashboard-markdown :deep(.resource-code-block__action) { position: absolute; top: 10px; right: 10px; min-height: 34px; padding: 0 10px; color: #ffffff; border: 1px solid #4a5c6a; border-radius: var(--radius-control); background: #253745; font-size: 14px; font-weight: 650; cursor: pointer; }
.dashboard-markdown :deep(.resource-inline-code) { padding: 2px 5px; color: var(--color-danger); border: 1px solid var(--color-border); border-radius: 4px; background: var(--color-surface-subtle); font-family: var(--font-mono); font-size: 14px; }
.dashboard-markdown :deep(.resource-math) { color: var(--color-text); font-family: var(--font-display); }
.dashboard-markdown :deep(.resource-math--block) { margin: 16px 0; padding: 16px; overflow-x: auto; border: 1px solid var(--color-border); border-radius: var(--radius-panel); background: var(--color-surface-subtle); text-align: center; }
.dashboard-markdown :deep(.resource-math--inline) { padding: 1px 4px; border-bottom: 1px solid var(--color-border-strong); }
.dashboard-markdown :deep(.resource-callout) { display: flex; align-items: center; justify-content: space-between; gap: 18px; padding: 14px 16px; color: var(--color-text-secondary); font-size: 14px; }
.dashboard-markdown :deep(.resource-callout strong) { color: var(--color-text); }
.dashboard-markdown :deep(.resource-callout__action) { min-height: 36px; flex: 0 0 auto; padding: 0 12px; color: #ffffff; border: 1px solid #11212d; border-radius: var(--radius-control); background: #11212d; font-size: 14px; font-weight: 650; cursor: pointer; }
.dashboard-markdown :deep(.resource-list-item) { margin: 6px 0 6px 20px; color: var(--color-text-secondary); font-size: 15px; line-height: 1.65; }
.dashboard-markdown :deep(.resource-table-wrap) { margin: 16px 0; overflow-x: auto; border: 1px solid var(--color-border); border-radius: var(--radius-panel); }
.dashboard-markdown :deep(.resource-table) { width: 100%; border-collapse: collapse; font-size: 14px; }
.dashboard-markdown :deep(.resource-table th),
.dashboard-markdown :deep(.resource-table td) { padding: 10px 12px; border-bottom: 1px solid var(--color-border); text-align: left; }
.dashboard-markdown :deep(.resource-table th) { color: var(--color-text); background: var(--color-surface-subtle); font-weight: 680; }
.dashboard-markdown :deep(.resource-table td) { color: var(--color-text-secondary); }
.dashboard-markdown :deep(.resource-image) { display: block; max-width: 100%; max-height: 360px; margin: 16px auto; object-fit: contain; border: 1px solid var(--color-border); border-radius: var(--radius-panel); }
.dashboard-markdown :deep(.resource-heading-4) { margin: 22px 0 7px; color: var(--color-text); font-size: 16px; font-weight: 680; line-height: 1.4; }

.dashboard-skeleton { max-width: 1380px; margin: 0 auto; }
.dashboard-skeleton__hero, .dashboard-skeleton__grid span { position: relative; overflow: hidden; border-radius: 8px; background: #dce2e3; }
.dashboard-skeleton__hero { height: 318px; }
.dashboard-skeleton__grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; margin-top: 18px; }
.dashboard-skeleton__grid span { height: 150px; }
.dashboard-skeleton__hero::after, .dashboard-skeleton__grid span::after { position: absolute; inset: 0; background: rgba(255,255,255,.42); content: ''; animation: skeleton-pulse 1.4s ease-in-out infinite; }
@keyframes skeleton-pulse { 50% { opacity: .35; } }

@media (max-width: 1100px) {
  .dashboard-overview { grid-template-columns: 1fr; }
  .dashboard-metrics { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}

</style>
