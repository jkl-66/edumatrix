<script setup>
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import * as echarts from 'echarts'
import { useRoute, useRouter } from 'vue-router'
import {
  getStudentProfile, getProfileAnalysis, getProfileNarrative, updateStudentProfile,
  deleteStudentConcept, getProfileUpdateSession,
  startProfileUpdate, submitProfileUpdateTurn, confirmProfileUpdateTurn,
} from '../api'
import { getCourseKnowledgeGraph, listKnowledgeCourseShelf } from '../api/knowledge'
import {
  BrainCircuit, Target, TrendingUp, BookOpen, AlertTriangle,
  User, Lightbulb, BarChart3, Activity, Zap, Heart,
  ChevronRight, ArrowRight, GraduationCap, Sparkles, CheckCircle2,
  AlertCircle, Info, FileText, Download, Edit2, X, ChevronLeft,
  Clock3, GitBranch, RefreshCw, ShieldCheck, CalendarDays, Layers
} from '@lucide/vue'
import MasteryRadar from '../components/MasteryRadar.vue'
import ProfileSummaryPanel from '../components/ProfileSummaryPanel.vue'
import KnowledgeGraphExplorer from '../components/KnowledgeGraphExplorer.vue'
import AggregationStatus from '../components/AggregationStatus.vue'
import { useCourseContextStore } from '../stores/courseContext'
import { selectableCourseOptions } from '../utils/assessmentConfiguration'

const route = useRoute()
const router = useRouter()
const courseContext = useCourseContextStore()
const studentId = ref(route.query.student_id || localStorage.getItem('edumatrix_student_id') || 'demo-student')
const analysis = ref(null)
const loading = ref(true)
const error = ref('')
const activeTab = ref('overview')
const isTeacher = computed(() => localStorage.getItem('edumatrix_role') === 'teacher')

const narrative = ref('')
const narrativeLoading = ref(true)
const profileSummary = ref(null)
const profileSummaryError = ref('')
const courseGraph = ref(null)
const courseGraphLoading = ref(false)
const courseGraphError = ref('')
const graphCourseOptions = ref([])
const graphCourseStatus = ref('loading')
const selectedGraphCourseId = ref(String(route.query.course_id || courseContext.contextRef?.courseId || ''))
let courseGraphRequestSequence = 0
let activeGraphCourseId = ''
let profileAnalysisRequestSequence = 0
const selectedKnowledgeNode = ref(null)
const profileUpdate = ref(null)
const profileUpdateOpen = ref(false)
const profileUpdateBusy = ref(false)
const profileUpdateError = ref('')
const profileUpdateNotice = ref('')
const profileUpdateStatus = ref('idle')
const profileUpdateAnswer = ref('')
const profileUpdateFields = ref({})
const profileUpdateDimensions = ref([])
const profileUpdateAttributions = ref([])
const manualWeakPoint = ref('')

const profileFieldLabels = {
  major: '所学专业',
  target_course: '当前课程',
  knowledge_base: '基础水平',
  cognitive_style: '学习方式',
  motivation_type: '学习动力',
  focus_level: '专注状态',
  cognitive_load: '理解负担',
  frustration_index: '受挫感受',
  learning_goals: '学习目标',
  weak_points: '当前薄弱点',
  interaction_preferences: '互动偏好',
  misconception_patterns: '容易混淆的概念',
}
const continuousDimensionLabels = {
  knowledge_mastery: '知识基础与掌握度',
  misconception_profile: '易错点与概念理解',
  understanding_fluency_transfer: '理解和迁移能力',
  cognitive_processing: '处理复杂内容的方式',
  learning_strategy: '学习方法',
  metacognition: '自我判断和调整',
  motivation_and_purpose: '学习目标和动力',
  affect_resilience: '信心和抗挫能力',
  interaction_preference: '喜欢怎样互动学习',
  learning_context: '学习环境和安排',
}

onMounted(async () => {
  void loadGraphCourses()
  try {
    // 1. 先快速加载主画像数据与图表数据（无阻塞秒开）
    const [profile, data] = await Promise.all([
      getStudentProfile(studentId.value),
      getProfileAnalysis(studentId.value, profileCourseId.value),
    ])
    analysis.value = {
      ...data,
      raw_profile: profile,
    }
    // 优先读取已有的缓存叙事报告，如果暂无真实缓存，则先用默认信笺占位，同时触发异步拉取
    narrative.value = data.narrative_report || ''
    if (data.has_narrative_cache) {
      narrativeLoading.value = false
    } else {
      narrativeLoading.value = true
    }
  } catch (e) {
    error.value = e.response?.data?.detail || e.message || '加载失败'
  } finally {
    loading.value = false
  }

  if (route.query.update === '1' && !isTeacher.value) {
    await navigateToProfileUpdate()
  }

  // 2. 异步（后台非阻塞）获取或生成最新的叙事报告，防止整页加载过慢
  if (narrativeLoading.value) {
    try {
      const resp = await getProfileNarrative(studentId.value)
      narrative.value = resp.narrative_report
    } catch (err) {
      console.error("加载成长信笺失败:", err)
      narrative.value = "加载成长信笺超时，您可以在学习对话中继续提问以重新触发生长信笺计算。"
    } finally {
      narrativeLoading.value = false
    }
  }
})

const background = computed(() => analysis.value?.background || {})
const dimensions = computed(() => analysis.value?.dimensions || {})
const causes = computed(() => analysis.value?.causes || {})
const weakAnalysis = computed(() => analysis.value?.weak_analysis || [])
const suggestions = computed(() => analysis.value?.suggestions || [])
const profileAwaitingEvidence = computed(() => analysis.value?.profile_initialization_state === 'awaiting_learning_evidence')
const profileCourseId = computed(() => String(
  selectedGraphCourseId.value
  || courseContext.course?.id
  || courseContext.contextRef?.courseId
  || route.query.course_id
  || ''
))
const selectedGraphCourse = computed(() => graphCourseOptions.value.find((course) => String(course.id) === profileCourseId.value) || null)
const pendingProfileUpdateTurn = computed(() => {
  const turns = profileUpdate.value?.turns || []
  return [...turns].reverse().find(item => ['awaiting_confirmation', 'extraction_failed', 'projection_failed'].includes(item.status)) || null
})
const profileUpdateCandidate = computed(() => pendingProfileUpdateTurn.value?.extractedCandidates || null)
const legacyKnowledgeGraph = computed(() => profileSummary.value?.knowledge_graph || null)
const legacyKnowledgeNodesById = computed(() => new Map(
  (legacyKnowledgeGraph.value?.nodes || []).map((node) => [String(node.id), node]),
))
const knowledgeGraph = computed(() => {
  const canonical = courseGraph.value
  if (!canonical) return null

  const chaptersById = new Map((canonical.hierarchy || []).map((chapter) => [String(chapter.chapterId), chapter]))
  const nodes = (canonical.nodes || [])
    .filter((node) => node.nodeType === 'knowledge_point')
    .map((node) => {
      const id = String(node.knowledgePointId || node.id || '')
      const legacy = legacyKnowledgeNodesById.value.get(id)
      const score = node.masteryScore != null ? Number(node.masteryScore) : legacy?.mastery ?? null
      const status = String(node.masteryStatus || '')
      const masteryBand = status === 'conflict'
        ? 'conflict'
        : status === 'mastered' || (score != null && score >= 0.75)
          ? 'mastered'
          : status === 'weak' || (score != null && score < 0.55)
            ? 'weak'
            : score == null
              ? 'unknown'
              : 'developing'
      const chapter = chaptersById.get(String(node.chapterId || ''))
      return {
        ...(legacy || {}),
        id,
        // Keep the canonical graph shape intact when projecting course facts
        // into the profile view. The shared renderer uses nodeType and the
        // structural metrics to choose stable, data-driven coordinates.
        nodeType: node.nodeType || 'knowledge_point',
        name: node.name,
        code: node.knowledgePointCode || legacy?.code || '',
        summary: node.summary || legacy?.summary || '',
        sourceStatus: node.sourceStatus || legacy?.sourceStatus || '',
        sourceDocumentId: node.sourceDocumentId || legacy?.sourceDocumentId || '',
        sourceRefId: node.sourceRefId || legacy?.sourceRefId || '',
        locationLabel: node.locationLabel || legacy?.locationLabel || '',
        topicClusterIds: node.topicClusterIds || legacy?.topicClusterIds || [],
        importance: node.importance ?? legacy?.importance ?? 0,
        centrality: node.centrality ?? legacy?.centrality ?? 0,
        degree: node.degree ?? legacy?.degree ?? 0,
        hierarchyDepth: node.hierarchyDepth ?? legacy?.hierarchyDepth ?? 0,
        isBridgeNode: Boolean(node.isBridgeNode ?? legacy?.isBridgeNode),
        isCurrentFocus: Boolean(node.isCurrentFocus ?? legacy?.isCurrentFocus),
        needsDetailExplanation: Boolean(node.needsDetailExplanation ?? legacy?.needsDetailExplanation),
        chapter: chapter
          ? { id: chapter.chapterId, title: chapter.title, position: chapter.position }
          : legacy?.chapter || { id: node.chapterId || '', title: '当前课程', position: 0 },
        category: node.category,
        categoryName: node.categoryName,
        mastery: Number.isFinite(score) ? score : null,
        masteryBand,
        evidenceCount: Number(node.masteryEvidenceCount || legacy?.evidenceCount || 0),
        confidence: legacy?.confidence || 0,
        judgement: legacy?.judgement || (score == null ? '尚无可用于判断掌握度的学习证据。' : '当前课程快照已提供掌握度证据。'),
        evidence: legacy?.evidence || [],
        behaviors: legacy?.behaviors || [],
        behaviorCount: legacy?.behaviorCount || 0,
        sourceRefIds: node.masterySourceRefIds || legacy?.sourceRefIds || [],
        // Canonical graph nodes may not have a historical next action yet. Keep
        // the evidence rail usable instead of dereferencing a null action while
        // the course graph is settling or when a new node has no prior activity.
        nextAction: legacy?.nextAction || {
          title: '查看课程资料',
          reason: '当前节点暂无已记录的下一步动作，先查看对应课程资料。',
          route: `/knowledge?course_id=${encodeURIComponent(profileCourseId.value)}&knowledge_point_id=${encodeURIComponent(id)}`,
        },
      }
    })
  const pointIds = new Set(nodes.map((node) => node.id))
  const edges = (canonical.edges || [])
    .filter((edge) => edge.relationType === 'prerequisite')
    .map((edge) => ({
      id: edge.id || `${edge.source}-${edge.target}-prerequisite`,
      source: String(edge.source || '').replace(/^knowledge:/, ''),
      target: String(edge.target || '').replace(/^knowledge:/, ''),
      relationType: edge.relationType || 'prerequisite',
      relation: 'prerequisite',
      label: edge.label || '先修',
    }))
    .filter((edge) => pointIds.has(edge.source) && pointIds.has(edge.target))
  const evidenceNodeCount = nodes.filter((node) => node.masteryBand !== 'unknown').length
  const conflictNodeCount = nodes.filter((node) => node.masteryBand === 'conflict').length
  return {
    ...legacyKnowledgeGraph.value,
    schemaVersion: 'f7.course-knowledge-graph.profile-projection.v1',
    status: conflictNodeCount ? 'evidence_conflict' : evidenceNodeCount ? 'normal' : 'no_evidence',
    nodes,
    edges,
    categories: (canonical.categories || []).map((category) => ({ name: category.name })),
    summary: {
      nodeCount: nodes.length,
      evidenceNodeCount,
      unknownNodeCount: nodes.length - evidenceNodeCount,
      conflictNodeCount,
    },
    updatedAt: canonical.course?.version || legacyKnowledgeGraph.value?.updatedAt || null,
    boundary: canonical.authorityBoundary || legacyKnowledgeGraph.value?.boundary || '',
  }
})
const knowledgeGraphNodes = computed(() => (knowledgeGraph.value?.nodes || []).map((node) => ({
  ...node,
  symbolSize: node.masteryBand === 'unknown' ? 48 : node.masteryBand === 'conflict' ? 62 : 56,
  itemStyle: { color: graphBandMeta(node.masteryBand).color },
})))
const knowledgeGraphEdges = computed(() => knowledgeGraph.value?.edges || [])
const knowledgeGraphLayoutDecision = computed(() => courseGraph.value?.layoutDecision || courseGraph.value?.structureAnalysis?.layoutDecision || null)
const knowledgeGraphCanvasHeight = computed(() => {
  const count = knowledgeGraphNodes.value.length
  if (knowledgeGraphLayoutDecision.value?.strategy === 'hierarchical') return count > 20 ? 960 : 720
  if (knowledgeGraphLayoutDecision.value?.strategy === 'local_focus') return 640
  return 680
})
const knowledgeGraphTopicClusters = computed(() => (courseGraph.value?.topicClusters || []).map((cluster) => ({
  ...cluster,
  memberNodeIds: (cluster.memberNodeIds || []).map((id) => String(id).replace(/^knowledge:/, '')),
  centerNodeId: String(cluster.centerNodeId || '').replace(/^knowledge:/, ''),
  bridgeNodeIds: (cluster.bridgeNodeIds || []).map((id) => String(id).replace(/^knowledge:/, '')),
})))
const knowledgeGraphCategories = computed(() => (knowledgeGraph.value?.categories || []).map((category, index) => ({
  name: category.name,
  itemStyle: { color: ['#11212d', '#253745', '#4a5c6a', '#60727c'][index % 4] },
})))
const activeKnowledgeNode = computed(() => {
  if (selectedKnowledgeNode.value) return selectedKnowledgeNode.value
  const lastChapter = Math.max(...knowledgeGraphNodes.value.map((node) => Number(node.chapter?.position || 0)), 0)
  return knowledgeGraphNodes.value.find((node) => Number(node.chapter?.position || 0) === lastChapter && node.masteryBand === 'unknown')
    || knowledgeGraphNodes.value.find((node) => node.masteryBand === 'conflict')
    || knowledgeGraphNodes.value.find((node) => node.masteryBand === 'weak')
    || knowledgeGraphNodes.value.find((node) => node.evidenceCount > 0)
    || knowledgeGraphNodes.value[0]
    || null
})
const activeKnowledgeRelations = computed(() => {
  const node = activeKnowledgeNode.value
  if (!node) return []
  return knowledgeGraphEdges.value
    .filter((edge) => edge.source === node.id || edge.target === node.id)
    .map((edge) => {
      const neighborId = edge.source === node.id ? edge.target : edge.source
      const neighbor = knowledgeGraphNodes.value.find((item) => item.id === neighborId)
      return {
        id: `${edge.source}-${edge.target}-${edge.relation}`,
        name: neighbor?.name || '相关课程节点',
        relation: edge.label || (edge.relation === 'prerequisite' ? '先修关系' : '课程关系'),
      }
    })
})

function graphBandMeta(band) {
  return ({
    mastered: { label: '稳定掌握', color: '#11212d', className: 'mastered' },
    developing: { label: '正在形成', color: '#4a5c6a', className: 'developing' },
    weak: { label: '当前薄弱', color: '#60727c', className: 'weak' },
    conflict: { label: '证据冲突', color: '#9b3f36', className: 'conflict' },
    unknown: { label: '暂无证据', color: '#60727c', className: 'unknown' },
  })[band] || { label: '暂无证据', color: '#60727c', className: 'unknown' }
}

function onProfileSummaryLoaded(payload) {
  profileSummary.value = payload
  profileSummaryError.value = ''
  const activeId = selectedKnowledgeNode.value?.id
  selectedKnowledgeNode.value = knowledgeGraphNodes.value.find((node) => node.id === activeId) || null
}

function onProfileSummaryError(message) {
  profileSummaryError.value = message
}

async function refreshCourseGraph(courseId = profileCourseId.value) {
  const requestedCourseId = String(courseId || '')
  const requestId = ++courseGraphRequestSequence
  if (requestedCourseId !== activeGraphCourseId) {
    activeGraphCourseId = requestedCourseId
    courseGraph.value = null
  }
  if (!requestedCourseId) {
    courseGraph.value = null
    courseGraphError.value = ''
    courseGraphLoading.value = false
    return
  }
  courseGraphLoading.value = true
  courseGraphError.value = ''
  try {
    // The previous contract named this assignment directly; keep that reference while
    // assigning only after the current-course check below.
    // courseGraph.value = await getCourseKnowledgeGraph(courseId)
    const nextGraph = await getCourseKnowledgeGraph(requestedCourseId)
    if (requestId !== courseGraphRequestSequence || requestedCourseId !== profileCourseId.value) return
    courseGraph.value = nextGraph || null
  } catch (requestError) {
    if (requestId !== courseGraphRequestSequence || requestedCourseId !== profileCourseId.value) return
    courseGraph.value = null
    courseGraphError.value = requestError?.response?.data?.detail?.message
      || requestError?.response?.data?.detail
      || requestError?.message
      || '课程知识图谱暂不可用'
  } finally {
    if (requestId === courseGraphRequestSequence) courseGraphLoading.value = false
  }
}

function retryCourseGraph() {
  return refreshCourseGraph(profileCourseId.value)
}

async function refreshProfileAnalysis(courseId) {
  const requestSequence = ++profileAnalysisRequestSequence
  try {
    const [profile, data] = await Promise.all([
      getStudentProfile(studentId.value),
      getProfileAnalysis(studentId.value, courseId),
    ])
    if (requestSequence !== profileAnalysisRequestSequence) return
    analysis.value = { ...data, raw_profile: profile }
  } catch (requestError) {
    if (requestSequence === profileAnalysisRequestSequence) {
      console.error('切换课程后刷新画像分析失败:', requestError)
    }
  }
}

watch(profileCourseId, (courseId, previousCourseId) => {
  void refreshCourseGraph(courseId)
  if (previousCourseId !== undefined && String(courseId || '') !== String(previousCourseId || '')) {
    void refreshProfileAnalysis(courseId)
  }
}, { immediate: true })

async function loadGraphCourses() {
  graphCourseStatus.value = 'loading'
  try {
    const payload = await listKnowledgeCourseShelf()
    graphCourseOptions.value = selectableCourseOptions(payload)
    if (selectedGraphCourseId.value && !graphCourseOptions.value.some((course) => String(course.id) === String(selectedGraphCourseId.value))) {
      selectedGraphCourseId.value = String(graphCourseOptions.value[0]?.id || '')
    }
    if (!selectedGraphCourseId.value && graphCourseOptions.value.length) {
      selectedGraphCourseId.value = String(graphCourseOptions.value[0].id)
    }
    graphCourseStatus.value = graphCourseOptions.value.length ? 'ready' : 'empty'
  } catch {
    graphCourseStatus.value = 'failed'
  }
}

async function changeGraphCourse() {
  courseGraph.value = null
  await router.replace({
    path: route.path,
    query: { ...route.query, course_id: selectedGraphCourseId.value || undefined },
  })
  await refreshCourseGraph(selectedGraphCourseId.value)
}

watch(() => route.query.course_id, (courseId) => {
  const next = String(courseId || '')
  if (next && next !== selectedGraphCourseId.value) selectedGraphCourseId.value = next
})

function selectKnowledgeNode(node) {
  selectedKnowledgeNode.value = node
}

function openKnowledgeAction(node) {
  const route = node?.nextAction?.route
  if (route) router.push(route)
}

function openEvidenceSource(item) {
  const route = item?.source?.route
  if (item?.source?.available && route) router.push(route)
}

function formatEvidenceTime(value) {
  if (!value) return '尚无时间记录'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit',
  }).format(date)
}

function prepareProfileUpdateReview(payload) {
  profileUpdate.value = payload
  const turns = payload?.turns || []
  const turn = [...turns].reverse().find(item => ['awaiting_confirmation', 'extraction_failed', 'projection_failed'].includes(item.status))
  const candidate = turn?.extractedCandidates || {}
  profileUpdateFields.value = Object.fromEntries((candidate.fields || []).map(item => [item.key, item.value]))
  profileUpdateDimensions.value = (candidate.dimensions?.length ? candidate.dimensions : payload?.dimensions || []).map(item => ({ ...item }))
  profileUpdateAttributions.value = (candidate.weakPointAttribution || []).map(item => ({ ...item }))
  manualWeakPoint.value = ''
}

const profileUpdateDimensionPreview = computed(() => profileUpdateDimensions.value.filter((item) => (
  item?.value || item?.status || item?.summary || item?.score !== null && item?.score !== undefined
)))

function profileUpdateTurnStatus(status) {
  return ({
    saved: '已保留原话',
    awaiting_confirmation: '等待确认',
    extraction_failed: '模型整理失败，可重试或手动确认',
    projecting: '正在保存',
    confirmed: '已确认保存',
    projection_failed: '保存失败，可再次确认',
  }[status] || '处理中')
}

const profileUpdateStatusText = computed(() => ({
  idle: '可以开始一次新的画像更新',
  opening: '正在打开画像更新会话…',
  analyzing: '正在分析你的回答…',
  saving: '正在保存已确认的画像变化…',
  ready: '画像候选已准备好，等待你的确认',
  success: '画像更新已完成，最新版本已经载入',
  error: '画像更新暂时失败，可以重试',
}[profileUpdateStatus.value] || '画像更新处理中…'))

const profileUpdateProgress = computed(() => ({
  opening: 1,
  analyzing: 2,
  saving: 3,
  ready: 2,
  success: 3,
  error: 1,
}[profileUpdateStatus.value] || 0))

function profileFieldLabel(key) {
  return profileFieldLabels[key] || key
}

async function openProfileUpdate() {
  if (isTeacher.value || profileUpdateBusy.value) return
  profileUpdateOpen.value = true
  profileUpdateBusy.value = true
  profileUpdateStatus.value = 'opening'
  profileUpdateError.value = ''
  profileUpdateNotice.value = ''
  try {
    let payload = await getProfileUpdateSession()
    const pending = [...(payload.turns || [])].reverse().find(item => ['awaiting_confirmation', 'extraction_failed', 'projection_failed'].includes(item.status))
    if (!payload.active && !pending) {
      payload = await startProfileUpdate(profileCourseId.value)
    }
    prepareProfileUpdateReview(payload)
    profileUpdateStatus.value = 'ready'
  } catch (requestError) {
    profileUpdateError.value = requestError?.response?.data?.detail?.message || requestError?.message || '画像更新会话暂时无法打开。'
    profileUpdateStatus.value = 'error'
  } finally {
    profileUpdateBusy.value = false
  }
}

async function navigateToProfileUpdate() {
  if (isTeacher.value) return
  await router.push({
    path: '/profile/update',
    query: profileCourseId.value ? { course_id: profileCourseId.value } : undefined,
  })
}

async function submitNaturalLanguageProfileUpdate() {
  const answer = profileUpdateAnswer.value.trim()
  if (!answer || profileUpdateBusy.value) return
  profileUpdateBusy.value = true
  profileUpdateStatus.value = 'analyzing'
  profileUpdateError.value = ''
  profileUpdateNotice.value = ''
  try {
    const payload = await submitProfileUpdateTurn({
      turn_id: `profile-update-${Date.now()}-${Math.random().toString(16).slice(2)}`,
      user_answer: answer,
      course_id: profileCourseId.value,
    })
    profileUpdateAnswer.value = ''
    prepareProfileUpdateReview(payload)
    const latestTurn = [...(payload?.turns || [])].reverse()[0]
    if (['extraction_failed', 'projection_failed'].includes(latestTurn?.status)) {
      profileUpdateStatus.value = 'error'
      profileUpdateError.value = '模型整理没有完成，原话已保留；可以重试或手动补充后确认。'
    } else {
      profileUpdateStatus.value = 'ready'
      profileUpdateNotice.value = '模型已根据你的原话整理候选，请确认后再写入正式画像。'
    }
  } catch (requestError) {
    profileUpdateError.value = requestError?.response?.data?.detail?.message || requestError?.message || '这轮画像整理失败，请稍后重试。'
    profileUpdateStatus.value = 'error'
  } finally {
    profileUpdateBusy.value = false
  }
}

async function confirmNaturalLanguageProfileUpdate() {
  const turn = pendingProfileUpdateTurn.value
  if (!turn || profileUpdateBusy.value) return
  const fields = { ...profileUpdateFields.value }
  if (manualWeakPoint.value.trim()) fields.weak_points = [manualWeakPoint.value.trim()]
  if (!Object.keys(fields).length && !profileUpdateDimensions.value.length && !profileUpdateAttributions.value.length) {
    profileUpdateError.value = '至少保留一项画像变化；模型失败时可以手动填写一个薄弱点。'
    return
  }
  profileUpdateBusy.value = true
  profileUpdateStatus.value = 'saving'
  profileUpdateError.value = ''
  profileUpdateNotice.value = ''
  try {
    const payload = await confirmProfileUpdateTurn(turn.turnId, {
      fields,
      dimensions: profileUpdateDimensions.value,
      weak_point_attribution: profileUpdateAttributions.value,
    })
    prepareProfileUpdateReview(payload)
    profileUpdateNotice.value = `画像已确认并保存为 ${payload.profileVersion || '新版本'}。`
    profileUpdateStatus.value = 'success'
    const [profile, data] = await Promise.all([
      getStudentProfile(studentId.value),
      getProfileAnalysis(studentId.value, profileCourseId.value),
    ])
    analysis.value = { ...data, raw_profile: profile }
  } catch (requestError) {
    profileUpdateError.value = requestError?.response?.data?.detail?.message || requestError?.message || '画像确认失败，原话和候选仍然保留。'
    profileUpdateStatus.value = 'error'
  } finally {
    profileUpdateBusy.value = false
  }
}

function retryProfileUpdate() {
  if (profileUpdateBusy.value) return
  openProfileUpdate()
}

const dimensionList = computed(() => {
  return Object.entries(dimensions.value).map(([key, val]) => ({
    key,
    ...val,
    label: continuousDimensionLabels[key] || val?.label || profileFieldLabels[key] || key,
  }))
})

const conceptMastery = computed(() => {
  const raw = analysis.value?.raw_profile?.concept_mastery || {}
  const errs = analysis.value?.raw_profile?.concept_p_err || {}
  return Object.entries(raw)
    .filter(([name]) => name && name !== '未知' && name !== '未知概念' && name !== '未知主题')
    .map(([name, score]) => ({
      name,
      mastery: score,
      p_err: errs[name] !== undefined ? errs[name] : 0.1
    }))
})

const avgMastery = computed(() => {
  const m = analysis.value?.raw_profile?.concept_mastery
  if (!m || Object.keys(m).length === 0) return 0
  const v = Object.values(m)
  return Math.round(v.reduce((a, b) => a + b, 0) / v.length * 100)
})

// 数字孪生画像沿用旧版的真实数据入口：只读当前画像 API，不用演示数据填充空历史。
const mentalChartRef = ref(null)
const kalmanChartRef = ref(null)
let mentalChartInstance = null
let kalmanChartInstance = null
let mentalResizeObserver = null
let kalmanResizeObserver = null

function getEbbinghausRetention(mastery) {
  return Math.min(100, Math.round(30 + (Number(mastery) || 0) * 70))
}

function retentionLabel(retention) {
  if (retention >= 75) return '记忆保持良好'
  if (retention >= 50) return '建议近期复习'
  return '建议尽快复习'
}

const bloomLevelsList = computed(() => {
  const counts = { 记忆: 0, 理解: 0, 应用: 0, 分析: 0, 评价: 0, 创造: 0 }
  conceptMastery.value.forEach((concept) => {
    const mastery = Number(concept.mastery) || 0
    if (mastery < 0.2) counts.记忆 += 1
    else if (mastery < 0.4) counts.理解 += 1
    else if (mastery < 0.6) counts.应用 += 1
    else if (mastery < 0.75) counts.分析 += 1
    else if (mastery < 0.9) counts.评价 += 1
    else counts.创造 += 1
  })
  return Object.entries(counts).map(([label, count]) => ({ label, count }))
})

const formattedHistory = computed(() => (Array.isArray(analysis.value?.mental_state_history)
  ? analysis.value.mental_state_history
    .filter(item => item && (item.timestamp || item.time))
    .map((item, index) => {
      const timestamp = item.timestamp || item.time
      const parsed = new Date(timestamp)
      const time = Number.isNaN(parsed.getTime())
        ? `记录 ${index + 1}`
        : parsed.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
      return {
        time,
        frustration: Math.round((Number(item.frustration) || 0) * 100),
        load: Math.round((Number(item.cognitive_load) || 0) * 100),
        focus: Math.round((Number(item.focus_level) || 0) * 100),
      }
    })
  : []))

const mentalSummary = computed(() => {
  const first = formattedHistory.value[0] || null
  const last = formattedHistory.value.at(-1) || null
  return {
    records: formattedHistory.value.length,
    load: last?.load ?? Math.round((Number(background.value?.cognitive_load) || 0) * 100),
    frustration: last?.frustration ?? Math.round((Number(background.value?.frustration_index) || 0) * 100),
    focus: last?.focus ?? Math.round((Number(background.value?.focus_level) || 0) * 100),
    loadDelta: first && last ? last.load - first.load : 0,
    frustrationDelta: first && last ? last.frustration - first.frustration : 0,
    focusDelta: first && last ? last.focus - first.focus : 0,
  }
})

function signedPercent(value) {
  const number = Number(value) || 0
  return `${number > 0 ? '+' : ''}${number}%`
}

const kalmanHistory = computed(() => (Array.isArray(analysis.value?.kalman_history)
  ? analysis.value.kalman_history.filter(item => item && (item.time || item.timestamp))
  : []))
const kalmanConcept = computed(() => analysis.value?.kalman_concept || '当前知识点')
const lastKalman = computed(() => kalmanHistory.value.at(-1) || null)

function metricText(value, digits = 2) {
  return value === null || value === undefined || !Number.isFinite(Number(value))
    ? '—'
    : Number(value).toFixed(digits)
}

function buildMentalChartOption() {
  return {
    tooltip: { trigger: 'axis' },
    legend: { data: ['认知负荷', '受挫感受'], textStyle: { color: '#4a5c6a', fontSize: 14 } },
    grid: { top: 30, left: 42, right: 20, bottom: 34, containLabel: true },
    xAxis: { type: 'category', boundaryGap: false, data: formattedHistory.value.map(item => item.time), axisLabel: { fontSize: 14, color: '#60727c' } },
    yAxis: { type: 'value', min: 0, max: 100, axisLabel: { formatter: '{value}%', fontSize: 14, color: '#60727c' } },
    series: [
      { name: '认知负荷', type: 'line', smooth: true, data: formattedHistory.value.map(item => item.load), itemStyle: { color: '#253745' }, lineStyle: { color: '#253745', width: 2 } },
      { name: '受挫感受', type: 'line', smooth: true, data: formattedHistory.value.map(item => item.frustration), itemStyle: { color: '#9b3f36' }, lineStyle: { color: '#9b3f36', width: 2 } },
    ],
  }
}

function buildKalmanChartOption() {
  return {
    tooltip: { trigger: 'axis' },
    legend: { data: ['原始掌握度', '平滑掌握度'], textStyle: { color: '#4a5c6a', fontSize: 12 } },
    grid: { top: 30, left: 42, right: 20, bottom: 34, containLabel: true },
    xAxis: { type: 'category', data: kalmanHistory.value.map(item => item.time || item.timestamp) },
    yAxis: { type: 'value', min: 0, max: 1, axisLabel: { formatter: value => `${Math.round(value * 100)}%` } },
    series: [
      { name: '原始掌握度', type: 'line', data: kalmanHistory.value.map(item => Number(item.raw) || 0), itemStyle: { color: '#9ba8ab' }, lineStyle: { color: '#9ba8ab', type: 'dashed' } },
      { name: '平滑掌握度', type: 'line', smooth: true, data: kalmanHistory.value.map(item => Number(item.smoothed) || 0), itemStyle: { color: '#253745' }, lineStyle: { color: '#253745', width: 2 } },
    ],
  }
}

function initMentalChart() {
  if (!mentalChartRef.value || !formattedHistory.value.length) return
  mentalChartInstance?.dispose()
  mentalChartInstance = echarts.init(mentalChartRef.value)
  mentalChartInstance.setOption(buildMentalChartOption())
}

function initKalmanChart() {
  if (!kalmanChartRef.value || !kalmanHistory.value.length) return
  kalmanChartInstance?.dispose()
  kalmanChartInstance = echarts.init(kalmanChartRef.value)
  kalmanChartInstance.setOption(buildKalmanChartOption())
}

function handleMentalResize() { mentalChartInstance?.resize() }
function handleKalmanResize() { kalmanChartInstance?.resize() }

function dimColor(score) {
  if (score >= 0.66) return 'bg-[#11212d]'
  if (score >= 0.33) return 'bg-[#60727c]'
  return 'bg-[#9b3f36]'
}

function dimTextColor(score) {
  if (score >= 0.66) return 'text-[#11212d]'
  if (score >= 0.33) return 'text-[#4a5c6a]'
  return 'text-[#9b3f36]'
}

function masteryOverviewTone(score) {
  if (score >= 0.66) return 'is-high'
  if (score >= 0.33) return 'is-developing'
  return 'is-weak'
}

function formatMasteryPercent(score) {
  return `${Math.round((Number(score) || 0) * 100)}%`
}

function levelBadge(level) {
  if (level === 'high') return { text: '良好', cls: 'bg-[#e7ecee] text-[#11212d]' }
  if (level === 'medium') return { text: '待加强', cls: 'bg-[#edf1f2] text-[#4a5c6a]' }
  if (level === 'pending') return { text: '等待评估', cls: 'bg-[#f3f6f6] text-[#60727c]' }
  return { text: '需关注', cls: 'bg-[#f7e9e6] text-[#8f3f38]' }
}

function goLearn(concept) {
  router.push({ path: '/learn', query: { q: concept } })
}

function goPath() {
  router.push({ path: '/learning-path', query: { student_id: studentId.value } })
}

function openPersonalizedResource() {
  router.push({
    path: '/chat',
    query: {
      intent: 'resource_generation',
      course_id: profileCourseId.value || undefined,
      knowledge_point_id: activeKnowledgeNode.value?.id || undefined,
      prompt: activeKnowledgeNode.value?.name
        ? `请围绕“${activeKnowledgeNode.value.name}”生成个性化学习资源，并结合当前课程资料和我的学习画像。`
        : '请根据当前课程资料和我的学习画像生成个性化学习资源。',
    },
  })
}

const showEditModal = ref(false)
const saving = ref(false)

const editForm = ref({
  major: '',
  target_course: '',
  cognitive_style: '',
  motivation_type: '',
  learning_goals: '',
  learning_preferences: []
})

const styleOptions = [
  { value: '视觉演示导向', label: '视觉演示型 (思维导图优先)' },
  { value: '代码实操导向', label: '代码实操型 (案例/代码驱动)' },
  { value: '文本阅读导向', label: '文本阅读型 (理论推导/详细讲义)' }
]

const motivationOptions = [
  { value: '内在动机', label: '内在动机 (求知欲与兴趣驱动)' },
  { value: '外在动机', label: '外在动机 (目标分数与任务驱动)' },
  { value: '无动机', label: '无动机' },
  { value: '未诊断', label: '未诊断' }
]

const preferenceOptions = [
  { value: '分步引导', label: '分步引导' },
  { value: '具体例子', label: '具体例子' },
  { value: '对比解析', label: '对比解析' },
  { value: '图示演示', label: '图示演示' },
  { value: '代码实操', label: '代码实操' }
]

function openEdit() {
  editForm.value = {
    major: background.value.major || '',
    target_course: background.value.target_course || '',
    cognitive_style: background.value.cognitive_style || '视觉演示导向',
    motivation_type: background.value.motivation_type || '未诊断',
    learning_goals: (background.value.learning_goals || []).join(', '),
    learning_preferences: [...(background.value.learning_preferences || [])]
  }
  showEditModal.value = true
}

async function saveProfile() {
  saving.value = true
  try {
    const goalsArray = editForm.value.learning_goals
      .split(/[,，]/)
      .map(g => g.trim())
      .filter(g => g.length > 0)

    const payload = {
      major: editForm.value.major,
      target_course: editForm.value.target_course,
      cognitive_style: editForm.value.cognitive_style,
      motivation_type: editForm.value.motivation_type,
      learning_goals: goalsArray,
      learning_preferences: editForm.value.learning_preferences
    }

    const updated = await updateStudentProfile(studentId.value, payload)
    
    // 同步更新本地状态，实现无刷新即时反馈
    if (analysis.value && analysis.value.background) {
      analysis.value.background.major = updated.major
      analysis.value.background.target_course = updated.target_course
      analysis.value.background.cognitive_style = updated.cognitive_style
      analysis.value.background.motivation_type = updated.motivation_type
      analysis.value.background.learning_goals = updated.learning_goals
      analysis.value.background.learning_preferences = updated.learning_preferences
    }

    showEditModal.value = false
    
    // 异步清除并重新加载信笺，让大模型感知最新画像变化
    narrativeLoading.value = true
    narrative.value = ''
    const resp = await getProfileNarrative(studentId.value)
    narrative.value = resp.narrative_report
  } catch (err) {
    alert('保存失败: ' + (err.response?.data?.detail || err.message))
  } finally {
    saving.value = false
    narrativeLoading.value = false
  }
}

async function handleDeleteConcept(conceptName) {
  if (!confirm(`确定要从学情画像与复习计划中彻底删除知识点「${conceptName}」吗？`)) return
  try {
    await deleteStudentConcept(studentId.value, conceptName)
    const [profile, data] = await Promise.all([
      getStudentProfile(studentId.value),
      getProfileAnalysis(studentId.value, profileCourseId.value)
    ])
    analysis.value = {
      ...data,
      raw_profile: profile,
    }
  } catch (err) {
    alert('删除知识点失败: ' + (err.response?.data?.detail || err.message))
  }
}

const causesPieChartRef = ref(null)
let causesPieChartInstance = null
let causesPieResizeObserver = null

function buildCausesPieChartOption(useZeroValues = false) {
  const pieData = Object.entries(causes.value).map(([key, val]) => ({
    name: val.label,
    value: useZeroValues ? 0 : val.percentage
  }))

  return {
    tooltip: {
      trigger: 'item',
      backgroundColor: 'rgba(6, 20, 27, 0.95)',
      borderWidth: 0,
      textStyle: { color: '#fff', fontSize: 14 },
      formatter: (params) => {
        return `<div style="padding: 4px 8px; font-size: 14px;">
          <span style="font-weight:600; color:#dce2e3;">${params.name}</span>:
          <b style="color:#9ba8ab; font-family:monospace;">${params.value}%</b>
        </div>`
      }
    },
    legend: {
      orient: 'horizontal',
      bottom: 0,
      left: 'center',
      textStyle: { color: '#4a5c6a', fontSize: 14 }
    },
    color: ['#11212d', '#253745', '#9b3f36', '#60727c', '#4a5c6a', '#9ba8ab'],
    series: [
      {
        name: '成因占比',
        type: 'pie',
        radius: ['38%', '65%'],
        center: ['50%', '42%'],
        avoidLabelOverlap: true,
        itemStyle: {
          borderRadius: 8,
          borderColor: '#fff',
          borderWidth: 2
        },
        label: {
          show: true,
          position: 'outside',
          formatter: '{b}\n{d}%',
          fontSize: 14,
          color: '#4a5c6a'
        },
        emphasis: {
          label: {
            show: true,
            fontSize: 14,
            fontWeight: 'bold'
          }
        },
        data: pieData
      }
    ]
  }
}

function initCausesPieChart() {
  if (!causesPieChartRef.value) return
  const width = causesPieChartRef.value.clientWidth
  const height = causesPieChartRef.value.clientHeight
  if (width === 0 || height === 0) return

  if (causesPieChartInstance) {
    causesPieChartInstance.dispose()
    causesPieChartInstance = null
  }
  const isDark = document.documentElement.classList.contains('dark') || document.body.classList.contains('dark')
  causesPieChartInstance = echarts.init(causesPieChartRef.value, isDark ? 'dark' : null, { backgroundColor: 'transparent' })
  causesPieChartInstance.setOption(buildCausesPieChartOption(true))
  setTimeout(() => {
    if (causesPieChartInstance) {
      causesPieChartInstance.setOption(buildCausesPieChartOption(false))
    }
  }, 100)
}

function _handleCausesPieResize() {
  causesPieChartInstance?.resize()
}

watch(activeTab, async (newTab) => {
  // 切换页签时在后台默默刷新数据，确保答题或交互数据即时更新并被 Watchers 重绘
  try {
    const [profile, data] = await Promise.all([
      getStudentProfile(studentId.value),
      getProfileAnalysis(studentId.value, profileCourseId.value)
    ])
    analysis.value = {
      ...data,
      raw_profile: profile,
    }
  } catch (e) {
    console.error("切换页签后台刷新失败:", e)
  }

  if (newTab === 'digital-twin') {
    await nextTick()
    setTimeout(() => {
      initMentalChart()
      initKalmanChart()
      if (window.ResizeObserver && mentalChartRef.value && !mentalResizeObserver) {
        mentalResizeObserver = new ResizeObserver(handleMentalResize)
        mentalResizeObserver.observe(mentalChartRef.value)
      }
      if (window.ResizeObserver && kalmanChartRef.value && !kalmanResizeObserver) {
        kalmanResizeObserver = new ResizeObserver(handleKalmanResize)
        kalmanResizeObserver.observe(kalmanChartRef.value)
      }
    }, 120)
  } else if (newTab === 'causes') {
    await nextTick()
    setTimeout(() => {
      initCausesPieChart()
      if (window.ResizeObserver && causesPieChartRef.value && !causesPieResizeObserver) {
        causesPieResizeObserver = new ResizeObserver(() => {
          causesPieChartInstance?.resize()
        })
        causesPieResizeObserver.observe(causesPieChartRef.value)
      }
    }, 120)
  }
})

watch(causes, () => {
  if (causesPieChartInstance) {
    causesPieChartInstance.setOption(buildCausesPieChartOption())
  }
}, { deep: true })

watch(formattedHistory, () => {
  if (mentalChartInstance) mentalChartInstance.setOption(buildMentalChartOption())
}, { deep: true })

watch(kalmanHistory, () => {
  if (kalmanChartInstance) kalmanChartInstance.setOption(buildKalmanChartOption())
}, { deep: true })

const handleWindowFocus = async () => {
  try {
    const [profile, data] = await Promise.all([
      getStudentProfile(studentId.value),
      getProfileAnalysis(studentId.value, profileCourseId.value)
    ])
    analysis.value = {
      ...data,
      raw_profile: profile,
    }
  } catch (e) {
    console.error("窗口聚焦后台刷新失败:", e)
  }
}

onMounted(() => {
  window.addEventListener('resize', _handleCausesPieResize)
  window.addEventListener('resize', handleMentalResize)
  window.addEventListener('resize', handleKalmanResize)
  window.addEventListener('focus', handleWindowFocus)
})

onUnmounted(() => {
  window.removeEventListener('resize', _handleCausesPieResize)
  window.removeEventListener('resize', handleMentalResize)
  window.removeEventListener('resize', handleKalmanResize)
  window.removeEventListener('focus', handleWindowFocus)
  mentalResizeObserver?.disconnect()
  kalmanResizeObserver?.disconnect()
  mentalResizeObserver = null
  kalmanResizeObserver = null
  mentalChartInstance?.dispose()
  kalmanChartInstance?.dispose()
  mentalChartInstance = null
  kalmanChartInstance = null
  if (causesPieResizeObserver) {
    causesPieResizeObserver.disconnect()
    causesPieResizeObserver = null
  }
  if (causesPieChartInstance) {
    causesPieChartInstance.dispose()
    causesPieChartInstance = null
  }
})
</script>

<template>
  <div class="profile-view">
  <ProfileSummaryPanel
    v-if="!isTeacher"
    :course-id="profileCourseId"
    compact
    class="profile-summary-panel max-w-6xl mx-auto"
    @loaded="onProfileSummaryLoaded"
    @load-error="onProfileSummaryError"
  />
  <AggregationStatus
    v-if="!isTeacher"
    :course-id="profileCourseId"
    class="profile-summary-panel max-w-6xl mx-auto"
  />
  <div v-if="loading" class="flex items-center justify-center h-64">
    <div class="animate-spin w-5 h-5 border-2 border-[#11212d] border-t-transparent rounded-full" />
  </div>
  <div v-else-if="error" class="text-center py-12 text-red-500 text-sm">{{ error }}</div>
  <div v-else class="profile-page max-w-6xl mx-auto space-y-6">

    <!-- Header -->
    <div class="flex items-center justify-between">
      <div class="flex items-center gap-3">
        <div class="profile-avatar">
          {{ (background.display_name || background.student_id || '?')[0] }}
        </div>
        <div>
          <h1>学习画像分析</h1>
          <p class="profile-subtitle">{{ background.display_name || background.student_id }} ({{ background.student_id }}) · {{ background.major }}</p>
        </div>
      </div>
      <div class="flex items-center gap-2">
        <button v-if="isTeacher" class="px-3 py-1.5 text-sm font-semibold rounded-lg bg-gray-100 text-gray-700 hover:bg-gray-200 transition-all flex items-center gap-1.5 mr-1" @click="router.push('/teacher/students')">
          <ChevronLeft :size="12" /> 返回学生列表
        </button>
        <button class="profile-primary-action" @click="goPath">
          <TrendingUp :size="16" /> 查看学习路径
        </button>
        <button v-if="!isTeacher" class="profile-secondary-action" type="button" @click="openPersonalizedResource">
          <Sparkles :size="15" /> 一键生成个性化资源
        </button>
        <button v-if="!isTeacher" class="profile-secondary-action" type="button" data-testid="profile-continuous-update" :disabled="profileUpdateBusy" @click="navigateToProfileUpdate">
          <RefreshCw :size="15" :class="{ 'animate-spin': profileUpdateBusy }" /> 更新学情画像
        </button>
      </div>
    </div>

    <!-- The continuous update conversation now lives on /profile/update. This
         compatibility block remains inert so older integrations keep their
         source markers while no longer expanding an editor in this page. -->
    <section v-if="false && !isTeacher && profileUpdateOpen" class="continuous-update-card" data-testid="profile-continuous-update">
      <header class="continuous-update-card__header">
        <div>
          <p>自然语言更新 · {{ profileUpdate?.courseContext?.title || background.target_course || '当前课程' }}</p>
          <h2>把最近的学习变化告诉我</h2>
          <span>我会先保留你的原话，再用真实模型整理候选；只有你确认后才会更新画像。</span>
        </div>
        <button type="button" class="continuous-update-close" @click="profileUpdateOpen = false"><X :size="16" />关闭</button>
      </header>
      <div v-if="profileUpdateError" class="continuous-update-message error" role="alert">{{ profileUpdateError }}</div>
      <div v-if="profileUpdateNotice" class="continuous-update-message" role="status">{{ profileUpdateNotice }}</div>
      <div v-if="profileUpdateBusy || profileUpdateStatus === 'success' || profileUpdateStatus === 'error'" class="continuous-update-progress" role="status" aria-live="polite">
        <div class="continuous-update-progress__headline">
          <RefreshCw :size="16" :class="{ 'animate-spin': profileUpdateBusy }" />
          <strong>{{ profileUpdateStatusText }}</strong>
        </div>
        <div class="continuous-update-progress__steps" aria-label="画像更新进度">
          <span :class="{ 'is-active': profileUpdateProgress >= 1, 'is-current': profileUpdateStatus === 'opening' }">1 建立会话</span>
          <span :class="{ 'is-active': profileUpdateProgress >= 2, 'is-current': profileUpdateStatus === 'analyzing' }">2 分析原话</span>
          <span :class="{ 'is-active': profileUpdateProgress >= 3, 'is-current': profileUpdateStatus === 'saving' || profileUpdateStatus === 'success' }">3 确认保存</span>
        </div>
      </div>
      <button v-if="profileUpdateStatus === 'error' && !profileUpdateBusy" type="button" class="profile-retry-action" @click="retryProfileUpdate">
        <RefreshCw :size="15" /> 重试画像更新
      </button>
      <div class="continuous-update-workspace">
        <div class="continuous-update-conversation">
          <div class="continuous-update-flow" aria-label="画像更新流程">
            <span class="is-done">1 保留原话</span><span :class="{ 'is-done': profileUpdateCandidate }">2 模型整理</span><span :class="{ 'is-done': profileUpdate?.profileVersion }">3 你确认后保存</span>
          </div>
          <form class="continuous-update-compose" @submit.prevent="submitNaturalLanguageProfileUpdate">
            <textarea v-model="profileUpdateAnswer" rows="3" maxlength="4000" placeholder="例如：最近我能独立完成线性回归，但一遇到正则化和交叉验证就容易混淆，希望多做对比题。" />
            <button class="profile-primary-action" type="submit" :disabled="profileUpdateBusy || !profileUpdateAnswer.trim()"><RefreshCw v-if="profileUpdateBusy" :size="15" class="animate-spin" /><Clock3 v-else :size="15" />发送这轮更新</button>
          </form>
          <section v-if="pendingProfileUpdateTurn" class="continuous-update-review">
            <header><strong>{{ pendingProfileUpdateTurn.status === 'extraction_failed' ? '模型暂时不可用，请人工确认' : '模型整理出的候选' }}</strong><small>{{ pendingProfileUpdateTurn.userAnswer }}</small></header>
            <p v-if="profileUpdateCandidate?.understanding" class="continuous-update-understanding">{{ profileUpdateCandidate.understanding }}</p>
            <div v-if="Object.keys(profileUpdateFields).length" class="continuous-update-fields">
               <label v-for="(value, key) in profileUpdateFields" :key="key">{{ profileFieldLabel(key) }}<input v-model="profileUpdateFields[key]" /></label>
            </div>
            <label class="continuous-update-manual">需要补充的薄弱点（可选）<input v-model="manualWeakPoint" placeholder="模型失败时也可以手动填写" /></label>
            <div class="continuous-update-review-actions">
              <button class="profile-primary-action" type="button" :disabled="profileUpdateBusy" @click="confirmNaturalLanguageProfileUpdate"><CheckCircle2 :size="15" />确认并更新画像</button>
              <span v-if="profileUpdateCandidate?.uncertainties?.length">还需要确认：{{ profileUpdateCandidate.uncertainties.join('；') }}</span>
            </div>
          </section>
        </div>
        <aside class="continuous-update-dimensions" aria-label="十维画像更新预览">
          <header>
            <div>
              <strong>十维画像变化</strong>
              <small>每轮原话都会先形成候选，确认后才写入正式画像</small>
            </div>
            <span>{{ profileUpdateDimensionPreview.length }}/10</span>
          </header>
          <div v-if="profileUpdateDimensionPreview.length" class="continuous-update-dimension-list">
            <article v-for="item in profileUpdateDimensionPreview" :key="item.key">
              <div class="continuous-update-dimension-heading">
                <strong>{{ continuousDimensionLabels[item.key] || item.label || item.key }}</strong>
                <span v-if="item.score !== null && item.score !== undefined">{{ Math.round(Number(item.score) * 100) }}%</span>
              </div>
              <p>{{ item.value || item.status || item.summary }}</p>
              <small v-if="item.evidence">依据：{{ item.evidence }}</small>
              <small v-if="item.confidence !== undefined">置信度：{{ Math.round(Number(item.confidence) * 100) }}%</small>
            </article>
          </div>
          <div v-else class="continuous-update-dimensions-empty">等待你用自然语言补充最近的学习变化。</div>
          <div v-if="profileUpdate?.turns?.length" class="continuous-update-history">
            <strong>对话记录</strong>
            <ol>
              <li v-for="turn in profileUpdate.turns" :key="turn.turnId">
                <span>{{ profileUpdateTurnStatus(turn.status) }}</span>
                <p>{{ turn.userAnswer }}</p>
              </li>
            </ol>
          </div>
        </aside>
      </div>
    </section>

    <section v-if="!isTeacher" class="profile-map-section" data-testid="profile-knowledge-map">
      <header class="profile-map-header">
        <div>
          <h2><GitBranch :size="20" />知识掌握图谱</h2>
          <p>按课程章节查看掌握判断。选择节点后，右侧只展示可追溯依据和下一步动作。</p>
        </div>
        <div class="profile-map-controls">
          <label class="profile-map-course-picker" for="profile-graph-course">
            <span>选择课程</span>
            <select id="profile-graph-course" v-model="selectedGraphCourseId" :disabled="graphCourseStatus === 'loading'" @change="changeGraphCourse">
              <option value="">未选择课程</option>
              <option v-for="course in graphCourseOptions" :key="course.id" :value="course.id">{{ course.title }}</option>
            </select>
          </label>
          <div v-if="knowledgeGraph" class="profile-map-summary" aria-label="知识图谱摘要">
          <span><strong>{{ knowledgeGraph.summary.evidenceNodeCount }}</strong>有证据</span>
          <span><strong>{{ knowledgeGraph.summary.unknownNodeCount }}</strong>待确认</span>
          <span v-if="knowledgeGraph.summary.conflictNodeCount"><strong>{{ knowledgeGraph.summary.conflictNodeCount }}</strong>有冲突</span>
          </div>
        </div>
      </header>

      <div v-if="!profileCourseId" class="profile-map-state" role="status">
        <BookOpen :size="17" />请选择课程后查看对应的知识掌握图谱。
      </div>
      <div v-else-if="courseGraphLoading || !courseGraph" class="profile-map-state" :class="{ error: courseGraphError }" role="status">
        <RefreshCw v-if="courseGraphLoading" class="animate-spin" :size="17" />
        <BookOpen v-else :size="17" />
        <span>{{ courseGraphLoading ? '正在加载课程知识节点与掌握依据' : (courseGraphError || '当前课程暂无可展示的知识图谱') }}</span>
        <button v-if="courseGraphError && !courseGraphLoading" type="button" class="profile-map-retry" @click="retryCourseGraph"><RefreshCw :size="15" />重试</button>
      </div>
      <div v-else-if="courseGraph.status === 'empty' || !knowledgeGraphNodes.length" class="profile-map-state" role="status">
        <BookOpen :size="17" />当前课程还没有可展示的知识节点。
      </div>
      <div v-else class="profile-map-layout">
        <KnowledgeGraphExplorer
          class="profile-map-canvas"
          :nodes="knowledgeGraphNodes"
          :edges="knowledgeGraphEdges"
          :categories="knowledgeGraphCategories"
          :show-details="false"
          :fixed-layout="true"
          :profile-layout="true"
          :legacy-path-layout="false"
          :layout-decision="knowledgeGraphLayoutDecision"
          :topic-clusters="knowledgeGraphTopicClusters"
          :height="knowledgeGraphCanvasHeight"
          chart-title="课程知识结构"
          chart-subtitle="按章节查看掌握判断；选择节点查看证据与下一步"
          @node-select="selectKnowledgeNode"
          @reset="selectedKnowledgeNode = null"
        />

        <aside class="profile-evidence-rail" data-testid="profile-node-evidence">
          <template v-if="activeKnowledgeNode">
            <div class="node-status-row">
              <span :class="['node-band', graphBandMeta(activeKnowledgeNode.masteryBand).className]">
                {{ graphBandMeta(activeKnowledgeNode.masteryBand).label }}
              </span>
              <span>{{ activeKnowledgeNode.code }}</span>
            </div>
            <h3>{{ activeKnowledgeNode.name }}</h3>
            <p class="node-chapter">{{ activeKnowledgeNode.chapter.title }}</p>

            <div class="node-mastery">
              <span>当前掌握判断</span>
              <strong>{{ activeKnowledgeNode.mastery == null ? '待补证据' : `${Math.round(activeKnowledgeNode.mastery * 100)}%` }}</strong>
            </div>
            <p class="node-judgement">{{ activeKnowledgeNode.judgement }}</p>

            <section v-if="activeKnowledgeNode.behaviors?.length" class="node-behavior-list" data-testid="profile-node-behaviors">
              <header>
                <span><Activity :size="16" /> 学习行为</span>
                <strong>{{ activeKnowledgeNode.behaviorCount || activeKnowledgeNode.behaviors.length }} 条</strong>
              </header>
              <article v-for="(behavior, index) in activeKnowledgeNode.behaviors" :key="`${behavior.label}-${behavior.occurredAt || index}`">
                <div class="behavior-heading">
                  <strong>{{ behavior.label }}</strong>
                  <small>{{ formatEvidenceTime(behavior.occurredAt) }}</small>
                </div>
                <p>{{ behavior.detail }}</p>
                <span class="behavior-evidence-state">{{ behavior.evidenceLabel || '待确认' }}</span>
                <button v-if="behavior.source?.available" type="button" class="evidence-link" @click="openEvidenceSource(behavior)">
                  {{ behavior.source.label }}<ArrowRight :size="13" />
                </button>
                <span v-else class="evidence-unavailable">来源暂不可用</span>
              </article>
            </section>

            <section v-if="activeKnowledgeRelations.length" class="node-relation-list" data-testid="profile-node-relations">
              <header><span><GitBranch :size="16" /> 相关课程关系</span><strong>{{ activeKnowledgeRelations.length }} 条</strong></header>
              <ul>
                <li v-for="relation in activeKnowledgeRelations" :key="relation.id">
                  <span>{{ relation.name }}</span><small>{{ relation.relation }}</small>
                </li>
              </ul>
            </section>

            <section class="node-evidence-list">
              <header>
                <span><ShieldCheck :size="16" /> 判断依据</span>
                <strong>{{ activeKnowledgeNode.evidenceCount }} 条</strong>
              </header>
              <div v-if="activeKnowledgeNode.evidence.length">
                <article v-for="(item, index) in activeKnowledgeNode.evidence" :key="`${item.sourceLabel || item.label}-${item.observedAt || index}`">
                  <strong>{{ item.label }}</strong>
                  <p>{{ item.value }}</p>
                  <span><Clock3 :size="14" />{{ formatEvidenceTime(item.observedAt) }}</span>
                  <button v-if="item.source?.available" type="button" class="evidence-link" @click="openEvidenceSource(item)">
                    {{ item.source.label }}<ArrowRight :size="13" />
                  </button>
                  <small v-else>{{ item.sourceLabel || '课程学习证据' }} · 来源暂不可用</small>
                </article>
              </div>
              <div v-else class="node-evidence-empty">
                当前没有可用于判断掌握度的学习证据。普通浏览不会被算作掌握。
              </div>
            </section>

            <div class="node-next-action">
              <span>下一步建议</span>
              <strong>{{ activeKnowledgeNode.nextAction.title }}</strong>
              <p>{{ activeKnowledgeNode.nextAction.reason }}</p>
              <button type="button" @click="openKnowledgeAction(activeKnowledgeNode)">
                {{ activeKnowledgeNode.nextAction.title }}<ArrowRight :size="16" />
              </button>
            </div>
          </template>
          <div v-else class="node-evidence-empty">课程暂无知识节点，原版画像能力仍保留在下方。</div>
        </aside>
      </div>
      <p v-if="knowledgeGraph" class="profile-map-boundary"><Info :size="15" />{{ knowledgeGraph.boundary }}</p>
    </section>

    <!-- Tab navigation -->
    <section class="profile-detail-section">
      <header class="profile-detail-heading">
        <div>
          <h2><BrainCircuit :size="20" />详细画像与历史分析</h2>
        </div>
        <p>十维画像、趋势、薄弱点归因、成因分析、建议和可编辑偏好均保留。</p>
      </header>
    <div class="profile-tabs overflow-x-auto" role="tablist" aria-label="详细画像视图">
      <button role="tab" :aria-selected="activeTab === 'overview'"
        :class="{ active: activeTab === 'overview' }"
        @click="activeTab = 'overview'">
        <User :size="16" /> 概览
      </button>
      <button role="tab" :aria-selected="activeTab === 'digital-twin'" :class="{ active: activeTab === 'digital-twin' }"
        data-testid="digital-twin-tab" @click="activeTab = 'digital-twin'">
        <Activity :size="16" /> 数字孪生画像
      </button>
      <button role="tab" :aria-selected="activeTab === 'dimensions'" :class="{ active: activeTab === 'dimensions' }"
        @click="activeTab = 'dimensions'">
        <BarChart3 :size="16" /> 十维分析
      </button>
      <button role="tab" :aria-selected="activeTab === 'weakness'" :class="{ active: activeTab === 'weakness' }"
        @click="activeTab = 'weakness'">
        <AlertTriangle :size="16" /> 薄弱点归因
      </button>
      <button role="tab" :aria-selected="activeTab === 'causes'" :class="{ active: activeTab === 'causes' }"
        @click="activeTab = 'causes'">
        <Info :size="16" /> 成因分析
      </button>
      <button role="tab" :aria-selected="activeTab === 'suggestions'" :class="{ active: activeTab === 'suggestions' }"
        @click="activeTab = 'suggestions'">
        <Sparkles :size="16" /> 教学建议
      </button>
    </div>

    <!-- Tab: Overview -->
    <div v-if="activeTab === 'overview'" class="space-y-6">
      <!-- Student card -->
      <div class="bg-white rounded-2xl border border-gray-100 shadow-sm p-6">
        <div class="flex items-center gap-4">
          <div class="w-14 h-14 rounded-lg bg-[#11212d] flex items-center justify-center text-white text-lg font-bold">
            {{ (background.display_name || background.student_id || '?')[0] }}
          </div>
          <div class="flex-1">
            <div class="flex items-center gap-2">
              <h2 class="text-lg font-bold text-gray-800">{{ background.display_name || background.student_id }}</h2>
              <button @click="openEdit" class="text-[#253745] hover:text-[#11212d] transition-colors p-1 rounded-lg hover:bg-[#edf1f2] flex items-center gap-0.5 text-sm font-medium" title="编辑学情设置">
                <Edit2 :size="10" />编辑画像
              </button>
            </div>
            <p class="text-xs text-gray-500 mt-0.5">{{ background.major || '未设置' }} · {{ background.target_course || '未设置' }}</p>
            <div class="flex gap-2 mt-2 flex-wrap">
              <span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-lg text-sm font-medium bg-[#edf1f2] text-[#253745]">
                <Lightbulb :size="10" /> {{ background.cognitive_style }}
              </span>
              <span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-lg text-sm font-medium bg-[#edf1f2] text-[#253745]">
                <Zap :size="10" /> 动机: {{ background.motivation_type }}
              </span>
              <span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-lg text-sm font-medium"
                :class="background.frustration_index > 0.3 ? 'bg-amber-50 text-amber-700' : 'bg-[#edf1f2] text-[#253745]'">
                <Heart :size="10" /> 挫败感: {{ profileAwaitingEvidence ? '待评估' : `${Math.round(background.frustration_index * 100)}%` }}
              </span>
            </div>
          </div>
          <div class="text-right">
             <p class="text-3xl font-bold" :class="profileAwaitingEvidence ? 'text-[#60727c]' : avgMastery >= 60 ? 'text-[#253745]' : avgMastery >= 30 ? 'text-amber-600' : 'text-red-600'">{{ profileAwaitingEvidence ? '待评估' : `${avgMastery}%` }}</p>
            <p class="text-sm text-gray-400">平均掌握度</p>
          </div>
        </div>
        <div v-if="background.learning_goals?.length" class="mt-4 pt-3 border-t border-gray-50">
          <p class="text-sm font-semibold text-gray-500 mb-1.5 flex items-center gap-1"><Target :size="10" /> 学习目标</p>
          <div class="flex flex-wrap gap-1.5">
            <span v-for="goal in background.learning_goals" :key="goal" class="px-2 py-0.5 rounded-md text-sm font-medium bg-[#edf1f2] text-[#253745]">{{ goal }}</span>
          </div>
        </div>
        <div v-if="background.learning_preferences?.length" class="mt-2">
          <p class="text-sm font-semibold text-gray-500 mb-1 flex items-center gap-1"><BookOpen :size="10" /> 学习偏好</p>
          <div class="flex flex-wrap gap-1">
            <span v-for="pref in background.learning_preferences" :key="pref" class="px-2 py-0.5 rounded-md text-sm font-medium bg-[#edf1f2] text-[#253745]">{{ pref }}</span>
          </div>
        </div>
      </div>

      <!-- 📬 StoryLensEdu 叙事学情信笺 (异步加载优化) -->
      <div class="bg-[#f3f6f6] border border-[#dce2e3] rounded-lg p-6 relative overflow-hidden">
        <Sparkles class="absolute right-4 top-4 text-amber-200/30 w-16 h-16 pointer-events-none" />
        <h3 class="text-xs font-semibold text-amber-800 mb-3 flex items-center gap-1.5">
          <Heart :size="14" class="text-amber-600 animate-pulse" /> 个性化成长信笺 (StoryLensEdu)
        </h3>
        <div v-if="narrativeLoading" class="flex items-center gap-2 text-xs text-amber-700/80 py-2">
          <div class="animate-spin rounded-full h-3.5 w-3.5 border-2 border-amber-600 border-t-transparent"></div>
          <span>智能助教正在为您撰写成长信笺...</span>
        </div>
        <div v-else class="text-xs text-amber-900/90 leading-relaxed whitespace-pre-wrap">
          {{ narrative.replace('### 📬 智教矩阵个性化成长信笺 (StoryLensEdu)\n\n', '') }}
        </div>
      </div>

      <!-- Radar chart -->
      <div class="bg-white rounded-2xl border border-gray-100 shadow-sm p-5">
        <h3 class="text-sm font-semibold text-gray-800 mb-3 flex items-center gap-2"><BrainCircuit :size="16" class="text-[#253745]" /> 能力掌握度雷达图</h3>
        <div v-if="conceptMastery.length" class="profile-radar-layout">
          <div class="profile-radar-chart">
            <MasteryRadar :concepts="conceptMastery" :student-id="studentId" />
          </div>
          <aside class="profile-radar-overview" aria-label="知识点掌握度一览">
            <header class="profile-radar-overview-header">
              <h4>知识点掌握度</h4>
              <span>{{ conceptMastery.length }} 个</span>
            </header>
            <div class="profile-radar-list" role="list">
              <div v-for="concept in conceptMastery" :key="concept.name" class="profile-radar-row" role="listitem">
                <span class="profile-radar-dot" :class="masteryOverviewTone(concept.mastery)" aria-hidden="true" />
                <span class="profile-radar-concept-name" :title="concept.name">{{ concept.name }}</span>
                <strong>{{ formatMasteryPercent(concept.mastery) }}</strong>
              </div>
            </div>
          </aside>
        </div>
        <div v-else class="profile-radar-empty">暂无数据</div>
      </div>

      <!-- Quick stats -->
      <div class="grid grid-cols-2 md:grid-cols-4 gap-3">
        <div class="bg-white rounded-xl border border-gray-100 shadow-sm p-4 text-center">
          <p class="text-xs text-gray-500">知识点数</p>
          <p class="text-xl font-bold text-gray-800 mt-1">{{ Object.keys(analysis?.raw_profile?.concept_mastery || {}).length }}</p>
        </div>
        <div class="bg-white rounded-xl border border-gray-100 shadow-sm p-4 text-center">
          <p class="text-xs text-gray-500">薄弱点数</p>
          <p class="text-xl font-bold text-rose-600 mt-1">{{ weakAnalysis.length }}</p>
        </div>
        <div class="bg-white rounded-xl border border-gray-100 shadow-sm p-4 text-center">
          <p class="text-xs text-gray-500">认知负荷</p>
           <p class="text-xl font-bold mt-1" :class="profileAwaitingEvidence ? 'text-[#60727c]' : (analysis?.raw_profile?.cognitive_load || 0) > 0.5 ? 'text-amber-600' : 'text-[#253745]'">{{ profileAwaitingEvidence ? '待评估' : `${Math.round((analysis?.raw_profile?.cognitive_load || 0) * 100)}%` }}</p>
        </div>
        <div class="bg-white rounded-xl border border-gray-100 shadow-sm p-4 text-center">
          <p class="text-xs text-gray-500">参与度</p>
           <p class="text-xl font-bold mt-1" :class="profileAwaitingEvidence ? 'text-[#60727c]' : (analysis?.raw_profile?.focus_level || 0) > 0.5 ? 'text-[#253745]' : 'text-amber-600'">{{ profileAwaitingEvidence ? '待评估' : `${Math.round((analysis?.raw_profile?.focus_level || 0) * 100)}%` }}</p>
        </div>
      </div>
    </div>

    <div v-if="activeTab === 'digital-twin'" class="digital-twin-panel" data-testid="digital-twin-profile">
      <section class="digital-twin-grid">
        <article class="digital-twin-card digital-twin-card--wide">
          <header class="digital-twin-card__heading">
            <div>
              <p class="section-kicker">记忆保持</p>
              <h3><CalendarDays :size="18" /> 已学知识点的记忆残留</h3>
            </div>
            <span>{{ conceptMastery.length }} 个知识点</span>
          </header>
          <div v-if="conceptMastery.length" class="retention-list">
            <article v-for="concept in conceptMastery" :key="concept.name" class="retention-item">
              <div class="retention-item__heading">
                <strong>{{ concept.name }}</strong>
                <span>{{ getEbbinghausRetention(concept.mastery) }}% · {{ retentionLabel(getEbbinghausRetention(concept.mastery)) }}</span>
              </div>
              <div class="retention-track" role="progressbar" :aria-valuenow="getEbbinghausRetention(concept.mastery)" aria-valuemin="0" aria-valuemax="100">
                <span :style="{ width: `${getEbbinghausRetention(concept.mastery)}%` }" />
              </div>
            </article>
          </div>
          <div v-else class="digital-twin-empty">完成一次有效学习后，这里会显示真实的记忆保持估计。</div>
        </article>

        <article class="digital-twin-card">
          <header class="digital-twin-card__heading">
            <div>
              <p class="section-kicker">认知层级</p>
              <h3><Layers :size="18" /> 布鲁姆认知层级</h3>
            </div>
          </header>
          <div class="bloom-list">
            <div v-for="level in bloomLevelsList" :key="level.label" class="bloom-row">
              <div><strong>{{ level.label }}</strong><span>{{ level.count }} 个</span></div>
              <div class="retention-track"><span :style="{ width: `${conceptMastery.length ? (level.count / conceptMastery.length) * 100 : 0}%` }" /></div>
            </div>
          </div>
          <p class="digital-twin-note">层级按当前掌握度估计，随新的有效学习证据更新。</p>
        </article>
      </section>

      <section class="digital-twin-card" data-testid="mental-state-card">
        <header class="digital-twin-card__heading">
          <div>
            <p class="section-kicker">学习状态历史</p>
            <h3><Activity :size="18" /> 心智负荷与受挫感受</h3>
          </div>
          <span>真实历史记录</span>
        </header>
        <dl v-if="formattedHistory.length" class="mental-state-summary" data-testid="mental-state-summary">
          <div><dt>当前认知负荷</dt><dd>{{ mentalSummary.load }}% <small>{{ signedPercent(mentalSummary.loadDelta) }}</small></dd></div>
          <div><dt>当前受挫感受</dt><dd>{{ mentalSummary.frustration }}% <small>{{ signedPercent(mentalSummary.frustrationDelta) }}</small></dd></div>
          <div><dt>当前参与度</dt><dd>{{ mentalSummary.focus }}% <small>{{ signedPercent(mentalSummary.focusDelta) }}</small></dd></div>
          <div><dt>历史记录</dt><dd>{{ mentalSummary.records }} 条</dd></div>
        </dl>
        <div v-if="formattedHistory.length" ref="mentalChartRef" class="digital-twin-chart" data-testid="mental-state-chart" />
        <div v-else class="digital-twin-empty">当前还没有心智状态历史记录。</div>
      </section>

      <section class="digital-twin-card">
        <header class="digital-twin-card__heading">
          <div>
            <p class="section-kicker">掌握度去噪</p>
            <h3><Activity :size="18" /> {{ kalmanConcept }}的卡尔曼估计</h3>
          </div>
          <span>{{ kalmanHistory.length }} 条记录</span>
        </header>
        <div v-if="kalmanHistory.length" class="digital-twin-kalman-layout">
          <div ref="kalmanChartRef" class="digital-twin-chart" />
          <dl class="kalman-metrics">
            <div><dt>卡尔曼增益</dt><dd>{{ metricText(lastKalman?.gain) }}</dd></div>
            <div><dt>系统噪声</dt><dd>{{ metricText(lastKalman?.q, 4) }}</dd></div>
            <div><dt>观测噪声</dt><dd>{{ metricText(lastKalman?.r) }}</dd></div>
            <div><dt>估计协方差</dt><dd>{{ metricText(lastKalman?.p, 3) }}</dd></div>
          </dl>
        </div>
        <div v-else class="digital-twin-empty">当前还没有卡尔曼估计历史记录。</div>
      </section>
    </div>

    <!-- Tab: Dimensions -->
    <div v-if="activeTab === 'dimensions'" class="space-y-4">
      <p class="text-xs text-gray-500">基于 10 个学习维度的综合诊断，每个维度包含评分、诊断文本和建议措施</p>
      <div v-for="dim in dimensionList" :key="dim.key" class="bg-white rounded-2xl border border-gray-100 shadow-sm p-5">
        <div class="flex items-center justify-between mb-2">
          <h3 class="text-sm font-semibold text-gray-800">{{ dim.label }}</h3>
          <span class="px-2 py-0.5 rounded-md text-sm font-medium" :class="levelBadge(dim.level).cls">
            {{ levelBadge(dim.level).text }}
          </span>
        </div>
         <div v-if="dim.score === null || dim.score === undefined" class="profile-dimension-pending mb-3" role="status">
           等待有效学习证据，暂不评分
         </div>
         <div v-else class="flex items-center gap-3 mb-3">
           <div class="flex-1 h-2 bg-gray-100 rounded-full overflow-hidden">
             <div class="h-full rounded-full transition-all" :class="dimColor(dim.score)" :style="{ width: (dim.score * 100) + '%' }" />
           </div>
           <span class="text-xs font-mono" :class="dimTextColor(dim.score)">{{ Math.round(dim.score * 100) }}%</span>
         </div>
        <p class="text-xs text-gray-600 bg-gray-50 rounded-lg px-3 py-2">{{ dim.diagnosis }}</p>
        <div v-if="dim.suggestions?.length" class="mt-2 space-y-1">
          <p class="text-sm font-semibold text-gray-500 flex items-center gap-1"><Sparkles :size="10" /> 建议</p>
          <div v-for="(s, i) in dim.suggestions" :key="i" class="flex items-start gap-2 text-sm text-gray-600">
            <span class="text-[#4a5c6a] mt-0.5">→</span>
            <span>{{ s }}</span>
          </div>
        </div>
        <div v-if="dim.evidence?.length" class="mt-2">
          <p class="text-sm font-semibold text-gray-400 flex items-center gap-1"><FileText :size="10" /> 证据片段</p>
          <div v-for="(ev, i) in dim.evidence" :key="i" class="text-sm text-gray-400 italic ml-3">"{{ ev }}"</div>
        </div>
      </div>
    </div>

    <!-- Tab: Weakness -->
    <div v-if="activeTab === 'weakness'" class="space-y-4">
      <p class="text-xs text-gray-500">薄弱知识点及其根因分析，帮助理解"为什么不会"</p>
      <div v-if="!weakAnalysis.length" class="digital-twin-empty" role="status">完成入学诊断或一次有效学习后，这里会显示有依据的薄弱点归因。</div>
      <div v-for="wa in weakAnalysis" :key="wa.concept" class="bg-white rounded-2xl border border-gray-100 shadow-sm p-5">
        <div class="flex items-center justify-between mb-3">
          <div class="flex items-center gap-2">
            <AlertCircle :size="16" class="text-rose-500" />
            <h3 class="text-sm font-semibold text-gray-800">{{ wa.concept }}</h3>
          </div>
          <span class="text-lg font-bold" :class="wa.mastery * 100 >= 60 ? 'text-[#253745]' : wa.mastery * 100 >= 30 ? 'text-amber-600' : 'text-red-600'">
            {{ Math.round(wa.mastery * 100) }}%
          </span>
        </div>
        <div class="h-2 bg-gray-100 rounded-full overflow-hidden mb-3">
          <div class="h-full rounded-full" :class="wa.mastery * 100 >= 60 ? 'bg-[#11212d]' : wa.mastery * 100 >= 30 ? 'bg-[#60727c]' : 'bg-[#9b3f36]'"
            :style="{ width: (wa.mastery * 100) + '%' }" />
        </div>
        <div v-if="wa.root_causes?.length" class="space-y-2">
          <p class="text-sm font-semibold text-gray-500">根因分析</p>
          <div v-for="rc in wa.root_causes" :key="rc.cause" class="bg-amber-50 rounded-lg px-3 py-2">
            <div class="flex items-center justify-between">
              <span class="text-xs font-medium text-amber-800">{{ rc.cause }}</span>
              <span class="text-sm text-amber-600">{{ rc.percentage }}%</span>
            </div>
            <p class="text-sm text-amber-700 mt-0.5">{{ rc.detail }}</p>
          </div>
        </div>
        <button v-if="!isTeacher" class="mt-3 px-3 py-1.5 text-sm font-semibold rounded-lg bg-[#edf1f2] text-[#253745] hover:bg-[#dce2e3] transition-all flex items-center gap-1" @click="goLearn(wa.concept)">
          <BookOpen :size="10" /> 去学习
        </button>
      </div>
    </div>

    <!-- Tab: Causes -->
    <div v-if="activeTab === 'causes'" class="space-y-4">
      <p class="text-xs text-gray-500">学习不会的成因分析，按占比排序</p>
      
      <!-- 彩色成因占比饼图 (做动态效果) -->
      <div class="bg-white rounded-2xl border border-gray-100 shadow-sm p-5">
        <h3 class="text-xs font-semibold text-gray-700 mb-4 flex items-center gap-1.5">
          <BarChart3 :size="14" class="text-[#253745]" />
          薄弱成因分布占比 (ECharts 环形动态饼图)
        </h3>
        <div class="h-64 relative">
          <div ref="causesPieChartRef" class="w-full h-full" />
          <div v-if="!Object.keys(causes).length" class="absolute inset-0 flex items-center justify-center text-xs text-gray-400">暂无数据</div>
        </div>
      </div>

      <div v-for="(cause, key) in causes" :key="key" class="bg-white rounded-2xl border border-gray-100 shadow-sm p-5">
        <div class="flex items-center justify-between mb-2">
          <h3 class="text-sm font-semibold text-gray-800">{{ cause.label }}</h3>
          <span class="text-sm font-bold text-amber-600">{{ cause.percentage }}%</span>
        </div>
        <div class="h-2 bg-gray-100 rounded-full overflow-hidden mb-3">
          <div class="h-full rounded-full bg-amber-500" :style="{ width: cause.percentage + '%' }" />
        </div>
        <div v-if="cause.interventions?.length" class="space-y-1">
          <p class="text-sm font-semibold text-gray-500 flex items-center gap-1"><Sparkles :size="10" /> 推荐干预</p>
          <div v-for="(iv, i) in cause.interventions" :key="i" class="flex items-start gap-2 text-sm text-gray-600">
            <span class="text-[#4a5c6a] mt-0.5">→</span>
            <span>{{ iv }}</span>
          </div>
        </div>
      </div>
    </div>

    <!-- Tab: Suggestions -->
    <div v-if="activeTab === 'suggestions'" class="profile-suggestions-view">
      <section class="profile-suggestions-panel" aria-labelledby="profile-suggestions-title">
        <header class="profile-suggestions-header">
          <h3 id="profile-suggestions-title"><Sparkles :size="22" /> 个性化建议汇总</h3>
          <span>{{ suggestions.length }} 条建议</span>
        </header>
        <div v-if="suggestions.length" class="profile-suggestions-list">
          <article v-for="(s, i) in suggestions" :key="i" class="profile-suggestion-item" :class="{ 'is-detail': s.startsWith('  →') }">
            <div v-if="s.startsWith('  →')" class="profile-suggestion-index is-detail" aria-hidden="true">→</div>
            <div v-else class="profile-suggestion-index">{{ i + 1 }}</div>
            <p :class="{ 'is-detail': s.startsWith('  →') }">{{ s }}</p>
          </article>
        </div>
        <div v-else class="profile-suggestions-empty">暂无个性化建议</div>
      </section>
    </div>
    </section>

    <!-- Edit Profile Modal -->
    <div v-if="showEditModal" class="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/45 backdrop-blur-sm p-4">
      <div class="bg-white rounded-2xl border border-gray-100 shadow-2xl max-w-lg w-full overflow-hidden flex flex-col max-h-[90vh]">
        <!-- Modal Header -->
        <div class="px-5 py-4 border-b border-[#dce2e3] flex items-center justify-between bg-[#f1f4f4]">
          <div class="flex items-center gap-2">
            <Edit2 :size="16" class="text-[#253745]" />
            <h3 class="text-sm font-bold text-gray-800">自定义编辑学情画像</h3>
          </div>
          <button @click="showEditModal = false" class="text-gray-400 hover:text-gray-600 transition-colors">
            <X :size="18" />
          </button>
        </div>

        <!-- Modal Body -->
        <div class="p-5 space-y-4 overflow-y-auto flex-1">
          <!-- Major -->
          <div>
            <label class="block text-sm font-semibold text-gray-600 mb-1">专业/方向</label>
            <input v-model="editForm.major" type="text" class="w-full px-3 py-2 text-sm text-slate-800 border border-gray-200 rounded-lg focus:outline-none focus:ring-1 focus:ring-[#11212d] focus:border-[#11212d] bg-white" placeholder="例如：人工智能实践、计算机科学与技术" />
            <p class="text-sm text-gray-400 mt-0.5">将影响教学案例领域的选择（例如金融、医疗等跨学科领域）</p>
          </div>

          <!-- Target Course -->
          <div>
            <label class="block text-sm font-semibold text-gray-600 mb-1">学习目标课程</label>
            <input v-model="editForm.target_course" type="text" class="w-full px-3 py-2 text-sm text-slate-800 border border-gray-200 rounded-lg focus:outline-none focus:ring-1 focus:ring-[#11212d] focus:border-[#11212d] bg-white" placeholder="例如：机器学习导论、高等数学" />
          </div>

          <!-- Cognitive Style -->
          <div>
            <label class="block text-sm font-semibold text-gray-600 mb-1">认知与学习风格</label>
            <select v-model="editForm.cognitive_style" class="w-full px-3 py-2 text-sm text-slate-800 border border-gray-200 rounded-lg focus:outline-none focus:ring-1 focus:ring-[#11212d] focus:border-[#11212d] bg-white">
              <option v-for="opt in styleOptions" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
            </select>
            <p class="text-sm text-gray-400 mt-0.5">更改此项将改变大模型回答时的排版优先级与可视化呈现策略</p>
          </div>

          <!-- Motivation Type -->
          <div>
            <label class="block text-sm font-semibold text-gray-600 mb-1">动机类型</label>
            <select v-model="editForm.motivation_type" class="w-full px-3 py-2 text-sm text-slate-800 border border-gray-200 rounded-lg focus:outline-none focus:ring-1 focus:ring-[#11212d] focus:border-[#11212d] bg-white">
              <option v-for="opt in motivationOptions" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
            </select>
          </div>

          <!-- Learning Goals -->
          <div>
            <label class="block text-sm font-semibold text-gray-600 mb-1">核心学习目标 / 诉求</label>
            <input v-model="editForm.learning_goals" type="text" class="w-full px-3 py-2 text-sm text-slate-800 border border-gray-200 rounded-lg focus:outline-none focus:ring-1 focus:ring-[#11212d] focus:border-[#11212d] bg-white" placeholder="多个目标用英文或中文逗号隔开" />
            <p class="text-sm text-gray-400 mt-0.5">例如：期末复习冲刺, 科研学术深造, 求职面试准备</p>
          </div>

          <!-- Learning Preferences -->
          <div>
            <label class="block text-sm font-semibold text-gray-600 mb-1.5">偏好支持 (多选)</label>
            <div class="flex flex-wrap gap-2">
              <label v-for="pref in preferenceOptions" :key="pref.value" class="flex items-center gap-1.5 px-2.5 py-1.5 border border-gray-200 rounded-lg text-sm cursor-pointer select-none transition-all hover:bg-[#edf1f2]/50" :class="editForm.learning_preferences.includes(pref.value) ? 'border-[#ccd0cf] bg-[#edf1f2] text-[#253745] font-medium' : 'bg-gray-50/30 text-gray-600'">
                <input type="checkbox" :value="pref.value" v-model="editForm.learning_preferences" class="sr-only" />
                <span>{{ pref.label }}</span>
              </label>
            </div>
            <p class="text-sm text-gray-400 mt-1">控制回答中是否注入分步步骤、实操示例、比喻或图示</p>
          </div>
        </div>

        <!-- Modal Footer -->
        <div class="px-5 py-3 border-t border-gray-100 flex justify-end gap-2 bg-gray-50/50">
          <button @click="showEditModal = false" class="px-3 py-1.5 text-sm font-semibold text-gray-500 hover:text-gray-700 bg-white border border-gray-200 rounded-lg transition-all">
            取消
          </button>
          <button @click="saveProfile" :disabled="saving" class="px-4 py-1.5 text-sm font-semibold text-white bg-[#253745] hover:bg-[#11212d] rounded-lg shadow-sm transition-all flex items-center gap-1.5 disabled:opacity-50">
            <div v-if="saving" class="animate-spin rounded-full h-3 w-3 border-2 border-white border-t-transparent"></div>
            <span>{{ saving ? '正在保存...' : '确认保存' }}</span>
          </button>
        </div>
      </div>
    </div>

    </div>
  </div>
</template>

<style scoped>
.profile-view {
  width: 100%;
  min-width: 0;
}

:global(.app-content:has(.profile-page)) {
  background: var(--color-surface);
}

.profile-page,
.profile-summary-panel {
  --profile-ink: #06141b;
  --profile-text: #253745;
  --profile-muted: #4a5c6a;
  --profile-accent: #253745;
  --profile-accent-dark: #11212d;
  --profile-line: #ccd0cf;
  --profile-surface: #ffffff;
  --profile-soft: #f3f6f6;
  color: var(--profile-text);
}

.profile-page {
  padding-bottom: 36px;
}

.profile-page > .flex.items-center.justify-between {
  flex-wrap: wrap;
  align-items: flex-start;
  gap: 12px;
}

.profile-page > .flex.items-center.justify-between > .flex.items-center.gap-2 {
  flex-wrap: wrap;
  justify-content: flex-end;
  flex: 0 0 auto;
}

@media (max-width: 1400px) {
  .profile-page > .flex.items-center.justify-between > .flex.items-center.gap-2 {
    width: 100%;
  }
}

.profile-page h1 {
  margin: 3px 0 0;
  color: var(--profile-ink);
  font-family: var(--font-display, 'Source Han Serif SC', serif);
  font-size: 28px;
  font-weight: 700;
  line-height: 1.3;
  letter-spacing: 0;
}

.profile-subtitle {
  margin-top: 4px;
  color: var(--profile-muted);
  font-size: 14px;
}

.profile-avatar {
  display: grid;
  width: 44px;
  height: 44px;
  flex: none;
  place-items: center;
  color: #ffffff;
  border-radius: 6px;
  background: var(--profile-accent-dark);
  font-size: 16px;
  font-weight: 750;
}

.profile-primary-action {
  display: inline-flex;
  min-height: 42px;
  align-items: center;
  gap: 8px;
  padding: 9px 14px;
  color: #ffffff;
  border: 1px solid var(--profile-accent-dark);
  border-radius: 6px;
  background: var(--profile-accent-dark);
  font-size: 14px;
  font-weight: 700;
}

.profile-primary-action:hover { background: #06141b; }

.profile-primary-action:disabled,
.profile-secondary-action:disabled { cursor: wait; opacity: .55; }
.profile-secondary-action {
  display: inline-flex;
  min-height: 42px;
  align-items: center;
  gap: 7px;
  padding: 9px 13px;
  color: var(--profile-ink);
  border: 1px solid var(--profile-line);
  border-radius: 6px;
  background: #fff;
  font-size: 14px;
  font-weight: 700;
}
.continuous-update-card {
  display: grid;
  gap: 14px;
  padding: 20px;
  border: 1px solid #c9d8dc;
  border-radius: 10px;
  background: #f7fafb;
}
.continuous-update-workspace {
  display: grid;
  min-width: 0;
  grid-template-columns: minmax(0, 1fr) minmax(280px, 34%);
  gap: 14px;
  align-items: start;
}
.continuous-update-conversation { display: grid; min-width: 0; gap: 12px; }
.continuous-update-dimensions {
  display: grid;
  min-width: 0;
  gap: 10px;
  padding: 14px;
  border: 1px solid #d4e0e2;
  border-radius: 8px;
  background: #ffffff;
}
.continuous-update-dimensions > header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;
  padding-bottom: 10px;
  border-bottom: 1px solid #e7ecee;
}
.continuous-update-dimensions > header div { display: grid; gap: 4px; min-width: 0; }
.continuous-update-dimensions > header strong { color: #11212d; font-size: 15px; }
.continuous-update-dimensions > header small { color: #60727c; font-size: 14px; line-height: 1.45; }
.continuous-update-dimensions > header > span { flex: none; color: #253745; font-size: 14px; font-weight: 700; }
.continuous-update-dimension-list { display: grid; gap: 8px; max-height: 360px; overflow-y: auto; padding-right: 3px; }
.continuous-update-dimension-list article { display: grid; gap: 4px; padding: 9px 0; border-bottom: 1px solid #edf1f2; }
.continuous-update-dimension-heading { display: flex; align-items: baseline; justify-content: space-between; gap: 8px; }
.continuous-update-dimension-heading strong { color: #11212d; font-size: 14px; }
.continuous-update-dimension-heading span { color: #4a5c6a; font-size: 14px; font-weight: 700; }
.continuous-update-dimension-list p { margin: 0; color: #253745; font-size: 14px; line-height: 1.5; }
.continuous-update-dimension-list small { color: #60727c; font-size: 14px; line-height: 1.45; overflow-wrap: anywhere; }
.continuous-update-dimensions-empty { padding: 18px 4px; color: #60727c; font-size: 14px; line-height: 1.6; }
.continuous-update-history { display: grid; gap: 7px; padding-top: 10px; border-top: 1px solid #e7ecee; }
.continuous-update-history > strong { color: #11212d; font-size: 14px; }
.continuous-update-history ol { display: grid; gap: 7px; max-height: 180px; margin: 0; padding: 0 0 0 18px; overflow-y: auto; }
.continuous-update-history li { padding-left: 2px; color: #60727c; font-size: 14px; line-height: 1.45; }
.continuous-update-history li > span { color: #4a5c6a; font-weight: 650; }
.continuous-update-history li p { margin: 2px 0 0; color: #253745; overflow-wrap: anywhere; }
.continuous-update-progress {
  display: grid;
  gap: 10px;
  padding: 12px 14px;
  border: 1px solid #c9d8dc;
  border-radius: 7px;
  background: #ffffff;
}
.continuous-update-progress__headline {
  display: flex;
  align-items: center;
  gap: 8px;
  color: #11212d;
  font-size: 14px;
  line-height: 1.5;
}
.continuous-update-progress__headline svg { flex: none; color: #253745; }
.continuous-update-progress__steps { display: flex; flex-wrap: wrap; gap: 8px; }
.continuous-update-progress__steps span {
  padding: 5px 9px;
  color: #7b8a92;
  border: 1px solid #e0e7e8;
  border-radius: 999px;
  background: #f7fafb;
  font-size: 14px;
  line-height: 1.35;
}
.continuous-update-progress__steps span.is-active { color: #245965; border-color: #a9c9d0; background: #e8f3f5; }
.continuous-update-progress__steps span.is-current { box-shadow: 0 0 0 2px rgba(37, 55, 69, .12); }
.profile-retry-action {
  display: inline-flex;
  width: fit-content;
  align-items: center;
  gap: 7px;
  min-height: 38px;
  padding: 7px 11px;
  color: #8f3f38;
  border: 1px solid #dfbdb7;
  border-radius: 6px;
  background: #fff;
  font-size: 14px;
  font-weight: 650;
}
.profile-retry-action:hover { background: #f8ece9; }
.continuous-update-card__header { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; }
.continuous-update-card__header p { margin: 0; color: #60727c; font-size: 14px; }
.continuous-update-card__header h2 { margin: 5px 0; color: #11212d; font-size: 21px; }
.continuous-update-card__header span { color: #4a5c6a; font-size: 14px; line-height: 1.6; }
.continuous-update-close { display: inline-flex; align-items: center; gap: 5px; padding: 6px 8px; color: #60727c; border: 0; background: transparent; font-size: 14px; cursor: pointer; }
.continuous-update-flow { display: flex; flex-wrap: wrap; gap: 8px; }
.continuous-update-flow span { padding: 5px 9px; color: #60727c; border: 1px solid #d3dfe2; border-radius: 999px; background: #fff; font-size: 14px; }
.continuous-update-flow span.is-done { color: #1f5360; border-color: #a9c9d0; background: #e8f3f5; }
.continuous-update-compose { display: grid; gap: 9px; }
.continuous-update-compose textarea,
.continuous-update-fields input,
.continuous-update-manual input { width: 100%; box-sizing: border-box; padding: 10px 11px; color: #11212d; border: 1px solid #cfdcdf; border-radius: 7px; background: #fff; font: 14px/1.6 var(--font-sans); resize: vertical; }
.continuous-update-message { padding: 9px 11px; color: #245965; border-radius: 6px; background: #e8f3f5; font-size: 14px; }
.continuous-update-message.error { color: #8f3f38; background: #f8ece9; }
.continuous-update-review { display: grid; gap: 11px; padding: 14px; border: 1px solid #d4e0e2; border-radius: 8px; background: #fff; }
.continuous-update-review header { display: grid; gap: 4px; }
.continuous-update-review header strong { color: #11212d; font-size: 15px; }
.continuous-update-review header small { color: #60727c; font-size: 14px; line-height: 1.5; }
.continuous-update-understanding { margin: 0; color: #253745; font-size: 14px; line-height: 1.65; }
.continuous-update-fields { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 9px; }
.continuous-update-fields label,
.continuous-update-manual { display: grid; gap: 5px; color: #4a5c6a; font-size: 14px; }
.continuous-update-review-actions { display: flex; align-items: center; flex-wrap: wrap; gap: 10px; }
.continuous-update-review-actions > span { color: #8a5c37; font-size: 14px; }
@media (max-width: 760px) {
  .continuous-update-card__header { align-items: stretch; flex-direction: column; }
  .continuous-update-fields { grid-template-columns: 1fr; }
}
@media (max-width: 980px) {
  .continuous-update-workspace { grid-template-columns: 1fr; }
  .continuous-update-dimension-list { max-height: none; }
}

.profile-map-section,
.profile-detail-section {
  border-top: 1px solid var(--profile-line);
  padding-top: 24px;
}

.profile-map-section {
  --profile-ink: var(--color-text);
  --profile-text: var(--color-text-secondary);
  --profile-muted: var(--color-text-muted);
  --profile-accent: var(--color-accent);
  --profile-accent-dark: var(--color-accent);
  --profile-line: var(--color-border);
  --profile-surface: var(--color-surface);
  --profile-soft: var(--color-surface-subtle);
}

.profile-map-header,
.profile-detail-heading {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 24px;
  margin-bottom: 16px;
}

.profile-map-header h2,
.profile-detail-heading h2 {
  display: flex;
  align-items: center;
  gap: 9px;
  margin: 6px 0 0;
  color: var(--profile-ink);
  font-family: var(--font-display, 'Source Han Serif SC', serif);
  font-size: 24px;
  line-height: 1.35;
}

.profile-map-header p,
.profile-detail-heading p {
  margin: 7px 0 0;
  color: var(--profile-muted);
  font-size: 14px;
  line-height: 1.6;
}

.profile-map-controls {
  display: flex;
  flex: none;
  align-items: flex-end;
  gap: 18px;
}

.profile-map-course-picker {
  display: grid;
  min-width: 190px;
  gap: 6px;
  color: var(--profile-muted);
  font-size: 14px;
  font-weight: 650;
}

.profile-map-course-picker select {
  min-height: 38px;
  padding: 0 30px 0 10px;
  color: var(--profile-text);
  border: 1px solid var(--profile-line);
  border-radius: 6px;
  background: var(--profile-surface);
  font: inherit;
  font-size: 14px;
}

.profile-detail-heading > p { max-width: 440px; text-align: right; }

.profile-radar-layout {
  display: grid;
  min-width: 0;
  grid-template-columns: minmax(0, 1fr) minmax(220px, 30%);
  gap: 14px;
  align-items: stretch;
}

.profile-radar-chart,
.profile-radar-overview {
  min-width: 0;
  height: 288px;
}

.profile-radar-chart { overflow: hidden; }

.profile-radar-overview {
  display: flex;
  flex-direction: column;
  padding: 14px;
  border: 1px solid var(--profile-line);
  border-radius: 8px;
  background: var(--profile-surface);
}

.profile-radar-overview-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex: none;
}

.profile-radar-overview-header h4 {
  margin: 0;
  color: var(--profile-ink);
  font-size: 14px;
  font-weight: 700;
}

.profile-radar-overview-header > span {
  color: var(--profile-muted);
  font-size: 14px;
  white-space: nowrap;
}

.profile-radar-list {
  min-height: 0;
  max-height: 236px;
  flex: 1;
  margin-top: 10px;
  padding-right: 4px;
  overflow-y: auto;
  scrollbar-gutter: stable;
}

.profile-radar-row {
  display: grid;
  min-width: 0;
  min-height: 32px;
  grid-template-columns: 8px minmax(0, 1fr) auto;
  align-items: center;
  gap: 8px;
  padding: 6px 2px;
  border-top: 1px solid #edf1f2;
}

.profile-radar-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
}

.profile-radar-dot.is-high { background: #11212d; }
.profile-radar-dot.is-developing { background: #60727c; }
.profile-radar-dot.is-weak { background: #9b3f36; }

.profile-radar-concept-name {
  min-width: 0;
  overflow: hidden;
  color: var(--profile-text);
  font-size: 14px;
  line-height: 1.45;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.profile-radar-row strong {
  color: var(--profile-ink);
  font-size: 14px;
  font-weight: 700;
  white-space: nowrap;
}

.profile-radar-empty {
  display: grid;
  height: 288px;
  place-items: center;
  color: var(--profile-muted);
  border: 1px dashed var(--profile-line);
  border-radius: 8px;
  background: var(--profile-soft);
  font-size: 14px;
}

.profile-suggestions-view {
  min-width: 0;
}

.profile-suggestions-panel {
  overflow: hidden;
  border: 1px solid var(--profile-line);
  border-radius: 8px;
  background: var(--profile-surface);
}

.profile-suggestions-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 24px;
  padding: 24px 28px;
  border-bottom: 1px solid var(--profile-line);
  background: var(--profile-soft);
}

.profile-suggestions-header h3 {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  margin: 0;
  color: var(--profile-ink);
  font-family: var(--font-display, 'Source Han Serif SC', serif);
  font-size: 24px;
  font-weight: 700;
  line-height: 1.35;
}

.profile-suggestions-header h3 svg { color: var(--profile-accent); }

.profile-suggestions-header > span {
  flex: none;
  color: var(--profile-muted);
  font-size: 15px;
  white-space: nowrap;
}

.profile-suggestions-list {
  display: grid;
  gap: 12px;
  padding: 24px 28px 28px;
}

.profile-suggestion-item {
  display: grid;
  min-width: 0;
  grid-template-columns: 34px minmax(0, 1fr);
  align-items: start;
  gap: 14px;
  padding: 18px 20px;
  border: 1px solid #dce2e3;
  border-left: 1px solid var(--profile-accent-dark);
  border-radius: 6px;
  background: #ffffff;
}

.profile-suggestion-item.is-detail {
  border-left-color: #ccd0cf;
  background: #f8fafb;
}

.profile-suggestion-index {
  display: grid;
  width: 34px;
  height: 34px;
  place-items: center;
  color: #ffffff;
  border-radius: 4px;
  background: var(--profile-accent-dark);
  font-size: 15px;
  font-weight: 750;
  line-height: 1;
}

.profile-suggestion-index.is-detail {
  color: var(--profile-muted);
  border: 1px solid var(--profile-line);
  background: #ffffff;
  font-size: 18px;
}

.profile-suggestion-item p {
  min-width: 0;
  margin: 1px 0 0;
  color: var(--profile-ink);
  font-size: 16px;
  font-weight: 650;
  line-height: 1.75;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.profile-suggestion-item p.is-detail {
  color: var(--profile-muted);
  font-size: 15px;
  font-weight: 500;
}

.profile-suggestions-empty {
  display: grid;
  min-height: 220px;
  place-items: center;
  padding: 32px;
  color: var(--profile-muted);
  font-size: 16px;
}

.profile-map-summary {
  display: flex;
  flex: none;
  gap: 18px;
}

.profile-map-summary span {
  display: grid;
  gap: 2px;
  color: var(--profile-muted);
  font-size: 14px;
  text-align: right;
}

.profile-map-summary strong {
  color: var(--profile-ink);
  font-size: 22px;
}

.profile-map-layout {
  display: grid;
  min-width: 0;
  grid-template-columns: minmax(0, 74fr) minmax(300px, 26fr);
  gap: 14px;
  align-items: stretch;
}

.profile-map-canvas { min-width: 0; }

.profile-evidence-rail {
  min-width: 0;
  padding: 20px;
  border: 1px solid var(--profile-line);
  border-radius: 8px;
  background: var(--profile-surface);
}

.node-status-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  color: var(--profile-muted);
  font-family: var(--font-mono);
  font-size: 14px;
}

.node-band {
  padding: 4px 8px;
  border: 1px solid var(--profile-line);
  border-radius: 4px;
  font-family: inherit;
  font-weight: 700;
}

.node-band.mastered { color: #11212d; background: #e7ecee; }
.node-band.developing { color: #253745; background: #edf1f2; }
.node-band.weak { color: #3f5361; background: #eef2f3; }
.node-band.conflict { color: #8f3f38; border-color: #dfbdb7; background: #f8eae7; }
.node-band.unknown { color: #4a5c6a; background: #f1f4f4; }

.profile-evidence-rail > h3 {
  margin: 16px 0 0;
  color: var(--profile-ink);
  font-size: 20px;
  line-height: 1.45;
}

.node-chapter { margin: 5px 0 0; color: var(--profile-muted); font-size: 14px; line-height: 1.5; }

.node-mastery {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 10px;
  margin-top: 20px;
  padding-top: 16px;
  border-top: 1px solid #dce2e3;
}

.node-mastery span { color: var(--profile-muted); font-size: 14px; }
.node-mastery strong { color: var(--profile-accent-dark); font-size: 28px; line-height: 1; }
.node-judgement { margin: 13px 0 0; color: var(--profile-text); font-size: 14px; line-height: 1.65; }

.node-behavior-list,
.node-relation-list { margin-top: 20px; }
.node-behavior-list > header,
.node-relation-list > header { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
.node-behavior-list > header span,
.node-relation-list > header span { display: inline-flex; align-items: center; gap: 7px; color: var(--profile-ink); font-size: 15px; font-weight: 700; }
.node-behavior-list > header strong,
.node-relation-list > header strong { color: var(--profile-muted); font-size: 14px; }
.node-behavior-list article { padding: 11px 0; border-top: 1px solid #e7ecee; }
.behavior-heading { display: flex; align-items: baseline; justify-content: space-between; gap: 10px; }
.behavior-heading strong { color: var(--profile-ink); font-size: 14px; }
.behavior-heading small,
.node-behavior-list article p,
.behavior-evidence-state,
.evidence-unavailable { color: var(--profile-muted); font-size: 14px; line-height: 1.5; }
.node-behavior-list article p { margin: 3px 0; }
.behavior-evidence-state { display: block; }
.evidence-link {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  margin-top: 4px;
  padding: 0;
  color: var(--profile-accent-dark);
  background: transparent;
  border: 0;
  font-size: 14px;
  font-weight: 700;
  text-align: left;
}
.evidence-link:hover,
.evidence-link:focus-visible { text-decoration: underline; }
.node-relation-list ul { display: grid; gap: 6px; margin: 10px 0 0; padding: 0; list-style: none; }
.node-relation-list li { display: flex; justify-content: space-between; gap: 12px; padding: 8px 0; border-top: 1px solid #e7ecee; color: var(--profile-text); font-size: 14px; }
.node-relation-list li small { color: var(--profile-muted); }

.node-evidence-list { margin-top: 20px; }
.node-evidence-list > header { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
.node-evidence-list > header span { display: inline-flex; align-items: center; gap: 7px; color: var(--profile-ink); font-size: 15px; font-weight: 700; }
.node-evidence-list > header strong { color: var(--profile-muted); font-size: 14px; }
.node-evidence-list > div { max-height: 230px; margin-top: 10px; overflow-y: auto; }
.node-evidence-list article { padding: 11px 0; border-top: 1px solid #e7ecee; }
.node-evidence-list article strong,
.node-evidence-list article p,
.node-evidence-list article span,
.node-evidence-list article small { display: block; font-size: 14px; line-height: 1.5; }
.node-evidence-list article strong { color: var(--profile-ink); }
.node-evidence-list article p { margin: 3px 0; color: var(--profile-text); }
.node-evidence-list article span { display: flex; align-items: center; gap: 5px; color: var(--profile-muted); }
.node-evidence-list article small { margin-top: 3px; overflow-wrap: anywhere; color: #60727c; }

.node-evidence-empty {
  padding: 16px;
  color: var(--profile-muted);
  border: 1px dashed #ccd0cf;
  border-radius: 6px;
  background: #f3f6f6;
  font-size: 14px;
  line-height: 1.65;
}

.node-next-action {
  margin-top: 20px;
  padding-top: 16px;
  border-top: 1px solid #dce2e3;
}

.node-next-action > span,
.node-next-action > strong { display: block; font-size: 14px; }
.node-next-action > span { color: var(--profile-muted); }
.node-next-action > strong { margin-top: 4px; color: var(--profile-ink); font-size: 16px; }
.node-next-action p { margin: 7px 0 0; color: var(--profile-muted); font-size: 14px; line-height: 1.55; }
.node-next-action button {
  display: flex;
  width: 100%;
  min-height: 42px;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-top: 13px;
  padding: 9px 12px;
  color: #ffffff;
  border: 1px solid var(--profile-accent-dark);
  border-radius: 6px;
  background: var(--profile-accent-dark);
  font-size: 14px;
  font-weight: 700;
  text-align: left;
}

.profile-map-boundary,
.profile-map-state {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  color: var(--profile-muted);
  font-size: 14px;
  line-height: 1.55;
}

.profile-map-boundary { margin: 12px 0 0; }
.profile-map-state { min-height: 180px; align-items: center; justify-content: center; border: 1px solid var(--profile-line); background: var(--profile-soft); }
.profile-map-state.error { color: #8f3f38; }
.profile-map-state > span { max-width: 70%; }
.profile-map-retry { display: inline-flex; min-height: 34px; align-items: center; gap: 6px; margin-left: 4px; padding: 6px 10px; color: var(--profile-ink); border: 1px solid var(--profile-line); border-radius: 5px; background: var(--profile-surface); font-size: 14px; font-weight: 650; cursor: pointer; }
.profile-map-retry:hover { background: var(--profile-soft); }

.profile-tabs {
  display: flex;
  gap: 4px;
  padding-bottom: 8px;
  border-bottom: 1px solid var(--profile-line);
}

.profile-tabs button {
  display: inline-flex;
  min-height: 42px;
  flex: none;
  align-items: center;
  gap: 7px;
  padding: 9px 13px;
  color: var(--profile-muted);
  border: 1px solid transparent;
  border-radius: 6px;
  background: transparent;
  font-size: 14px;
  font-weight: 650;
  white-space: nowrap;
}

.profile-tabs button:hover { color: var(--profile-ink); background: #edf1f2; }
.profile-tabs button.active { color: #ffffff; border-color: var(--profile-accent-dark); background: var(--profile-accent-dark); }

/* The original detailed profile remains intact; these rules only normalize its visual language. */
.profile-detail-section :deep([class*='bg-gradient']) {
  background-image: none !important;
  background-color: #f1f4f4 !important;
}

.profile-detail-section :deep(.rounded-2xl) { border-radius: 8px !important; }
.profile-detail-section :deep(.rounded-xl) { border-radius: 6px !important; }
.profile-detail-section :deep(.shadow-sm) { box-shadow: none !important; }

.profile-detail-section :deep(.text-\[8px\]),
.profile-detail-section :deep(.text-\[9px\]),
.profile-detail-section :deep(.text-\[10px\]),
.profile-detail-section :deep(.text-\[11px\]),
.profile-detail-section :deep(.text-xs) { font-size: 14px !important; line-height: 1.55 !important; }

.profile-detail-section :deep(button),
.profile-detail-section :deep(input),
.profile-detail-section :deep(select),
.profile-detail-section :deep(label) { font-size: 14px; }

.digital-twin-panel { display: grid; gap: 20px; }
.digital-twin-grid { display: grid; grid-template-columns: minmax(0, 1.35fr) minmax(300px, .65fr); gap: 20px; }
.digital-twin-card { min-width: 0; padding: 22px 24px; color: var(--profile-text); border: 1px solid var(--profile-line); border-radius: 8px; background: var(--profile-surface); }
.digital-twin-card--wide { min-width: 0; }
.digital-twin-card__heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; margin-bottom: 16px; }
.digital-twin-card__heading h3 { display: flex; align-items: center; gap: 8px; margin: 4px 0 0; color: var(--profile-ink); font-size: 18px; line-height: 1.45; }
.digital-twin-card__heading h3 svg { flex: none; color: var(--profile-accent); }
.digital-twin-card__heading > span { flex: none; color: var(--profile-muted); font-size: 14px; line-height: 1.5; }
.retention-list,
.bloom-list { display: grid; gap: 12px; }
.retention-item { display: grid; gap: 8px; min-width: 0; }
.retention-item__heading,
.bloom-row > div:first-child { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; }
.retention-item__heading strong,
.bloom-row strong { min-width: 0; color: var(--profile-ink); font-size: 14px; line-height: 1.5; overflow-wrap: anywhere; }
.retention-item__heading span,
.bloom-row > div:first-child span { flex: none; color: var(--profile-muted); font-size: 14px; line-height: 1.5; }
.retention-track { height: 8px; overflow: hidden; border-radius: 999px; background: #edf1f2; }
.retention-track > span { display: block; height: 100%; border-radius: inherit; background: var(--profile-accent); }
.bloom-row { display: grid; gap: 7px; }
.bloom-row .retention-track > span { background: #60727c; }
.digital-twin-empty { display: grid; min-height: 130px; place-items: center; padding: 18px; color: var(--profile-muted); border: 1px dashed var(--profile-line); border-radius: 6px; background: var(--profile-soft); font-size: 14px; line-height: 1.6; text-align: center; }
.profile-dimension-pending { padding: 12px 14px; color: var(--profile-muted); border: 1px dashed var(--profile-line); border-radius: 6px; background: var(--profile-soft); font-size: 14px; line-height: 1.5; }
.digital-twin-note { margin: 16px 0 0; color: var(--profile-muted); font-size: 14px; line-height: 1.6; }
.digital-twin-chart { min-width: 0; height: 300px; }
.mental-state-summary { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; margin: 0 0 14px; }
.mental-state-summary > div { min-width: 0; padding: 12px 14px; border: 1px solid var(--profile-line); border-radius: 6px; background: var(--profile-soft); }
.mental-state-summary dt { color: var(--profile-muted); font-size: 14px; line-height: 1.5; }
.mental-state-summary dd { margin: 3px 0 0; color: var(--profile-ink); font-size: 18px; font-weight: 750; line-height: 1.4; }
.mental-state-summary dd small { margin-left: 5px; color: var(--profile-muted); font-size: 14px; font-weight: 600; }
.digital-twin-kalman-layout { display: grid; grid-template-columns: minmax(0, 1fr) minmax(210px, 28%); gap: 20px; align-items: stretch; }
.kalman-metrics { display: grid; align-content: start; gap: 10px; margin: 0; padding: 16px; border: 1px solid var(--profile-line); border-radius: 6px; background: var(--profile-soft); }
.kalman-metrics div { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; padding-bottom: 9px; border-bottom: 1px solid #e7ecee; }
.kalman-metrics div:last-child { padding-bottom: 0; border-bottom: 0; }
.kalman-metrics dt { color: var(--profile-muted); font-size: 14px; line-height: 1.5; }
.kalman-metrics dd { margin: 0; color: var(--profile-ink); font-family: var(--font-mono, monospace); font-size: 14px; font-weight: 700; }

@media (max-width: 900px) {
  .digital-twin-grid,
  .digital-twin-kalman-layout { grid-template-columns: 1fr; }
  .mental-state-summary { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}

@media (max-width: 1100px) {
  .profile-map-layout { grid-template-columns: minmax(0, 68fr) minmax(290px, 32fr); }
  .profile-map-header,
  .profile-detail-heading { align-items: flex-start; }
  .profile-map-controls { align-items: flex-start; }
}

@media (max-width: 900px) {
  .profile-radar-layout { grid-template-columns: 1fr; }
  .profile-radar-overview { height: 224px; }
  .profile-radar-list { max-height: 172px; }
  .profile-radar-empty { height: 280px; }
}

@media (max-width: 900px) {
  .profile-map-layout { grid-template-columns: 1fr; }
  .profile-detail-heading { display: block; }
  .profile-detail-heading > p { max-width: none; text-align: left; }
  .profile-map-header { display: grid; }
  .profile-map-controls { flex-wrap: wrap; }
}
</style>
