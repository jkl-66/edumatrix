<script setup>
import { ref, onMounted, computed, nextTick, watch, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  confirmM5Plan,
  generateM5TextbookPathDraft,
  getCompetitionDemoContext,
  getLearningPath,
  getM5TextbookPathDraft,
  getM5Plan,
  getRecommendations,
  getM5TodayWork,
  getM5Schedule,
  listM5Paths,
  transitionM5Path,
  listGenerationJobs,
  recoverGenerationJob,
  retryGenerationItem,
} from '../api'
import { echarts } from '../lib/echarts-graph'
import {
  BookOpen, BrainCircuit, Target, TrendingUp, ChevronRight,
  ArrowRight, AlertTriangle, CheckCircle2, Layers, Sparkles,
  Clock, Zap, ChevronLeft, Play, Activity, Unlock, RefreshCw, Search,
  Maximize2, Minimize2, Move
} from '@lucide/vue'
import VideoRenderPanel from '../components/VideoRenderPanel.vue'
import PathTaskList from '../components/PathTaskList.vue'
import AggregationStatus from '../components/AggregationStatus.vue'

const route = useRoute()
const router = useRouter()
const studentId = ref(route.query.student_id || localStorage.getItem('edumatrix_student_id') || 'demo-student')
const pathData = ref(null)
const demoContext = ref(null)
const recommendations = ref([])
const loading = ref(true)
const error = ref('')
const isTeacher = computed(() => localStorage.getItem('edumatrix_role') === 'teacher')
const isLearner = computed(() => localStorage.getItem('edumatrix_role') === 'student')
const isPersonalPath = computed(() => Boolean(route.query.path_id))
const regenerating = ref(false)
const textbookDraft = ref(null)
const textbookDraftLoading = ref(false)
const textbookDraftError = ref('')
const pathViewMode = ref(route.query.view === 'subject' ? 'subject' : 'total')
const selectedSubjectId = ref(route.query.subject_id || '')
const m5Path = ref(null)
const m5Paths = ref([])
const todayWork = ref([])
const schedule = ref(null)
const scheduleLoading = ref(false)
const scheduleError = ref('')
const selectedScheduleDay = ref(1)
const generationJobs = ref([])
const selectedTodayTask = ref(null)
const generationJob = ref(null)
const generationBusy = ref(false)
const generationError = ref('')
const generationNotice = ref('')
const pathLoadError = ref('')
const aggregatePlan = ref(null)
const aggregatePlanError = ref('')
const aggregatePlanLoading = ref(false)
const semanticQuery = ref('')
const showSimilarityLog = ref(false)
const semanticChartRef = ref(null)
let semanticChart = null
const isSemanticFullscreen = ref(false)
const selectedSemanticConcept = ref('')
const isSemanticArranging = ref(false)
let arrangeTimer = null
function toggleSemanticFullscreen() {
  isSemanticFullscreen.value = !isSemanticFullscreen.value
}
function resetSemanticLayout() {
  if (arrangeTimer) {
    clearTimeout(arrangeTimer)
    arrangeTimer = null
  }
  isSemanticArranging.value = false
  if (semanticChart) {
    semanticChart.dispose()
    semanticChart = null
  }
  nextTick(renderSemanticGraph)
}

function autoArrangeAfterDrag(draggedName) {
  if (!semanticChart || !draggedName) return
  if (arrangeTimer) clearTimeout(arrangeTimer)
  const currentData = semanticChart.getOption()?.series?.[0]?.data || []
  if (!currentData.length) return
  const forceData = currentData.map(node => ({
    ...node,
    fixed: node.name === draggedName,
    draggable: true,
  }))
  isSemanticArranging.value = true
  semanticChart.setOption({
    animationDurationUpdate: 900,
    animationEasingUpdate: 'cubicInOut',
    series: [{
      layout: 'force',
      data: forceData,
      force: {
        repulsion: 230,
        edgeLength: 150,
        gravity: 0.08,
        friction: 0.6,
        layoutAnimation: true,
      },
      labelLayout: {
        hideOverlap: false,
        moveOverlap: 'shiftY',
      },
    }],
  })
  arrangeTimer = setTimeout(() => {
    if (!semanticChart) return
    const settledData = semanticChart.getOption()?.series?.[0]?.data || forceData
    semanticChart.setOption({
      animationDurationUpdate: 500,
      series: [{
        layout: 'none',
        data: settledData.map(node => ({
          ...node,
          fixed: false,
          draggable: true,
        })),
      }],
    })
    isSemanticArranging.value = false
    arrangeTimer = null
  }, 1250)
}

const showVideoPanel = ref(false)
const videoPanelUrl = ref('')
const videoPanelConcept = ref('')

const learningChain = computed(() => pathData.value?.learning_chain || [])
const nextSteps = computed(() => pathData.value?.next_steps || [])
const gapChains = computed(() => pathData.value?.gap_chains || [])
const stages = computed(() => pathData.value?.stages || [])
const progress = computed(() => pathData.value?.progress_summary || {})
const strategySuggestions = computed(() => pathData.value?.strategy_suggestions || [])
const adaptiveRoute = computed(() => pathData.value?.adaptive_route || null)
const routeNodes = computed(() => adaptiveRoute.value?.nodes || [])
const routeEdges = computed(() => adaptiveRoute.value?.edges || [])
const routeConfidence = computed(() => Math.round((adaptiveRoute.value?.confidence || 0) * 100))
const plannerTrace = computed(() => adaptiveRoute.value?.planner_trace || [])
const routeResourceSummary = computed(() => adaptiveRoute.value?.resource_summary || {})
const graphFusion = computed(() => adaptiveRoute.value?.graph_fusion || {})
const routeResourceNodes = computed(() =>
  routeNodes.value.filter(node => node.resource?.has_animation)
)
const routeStageTarget = computed(() => adaptiveRoute.value?.stage_target_concept || adaptiveRoute.value?.target_concept || '')
const routeFinalTarget = computed(() => adaptiveRoute.value?.final_goal_concept || adaptiveRoute.value?.target_concept || '')
const activeLearningTarget = computed(() => pathData.value?.active_learning_target || '')
const remainingRoute = computed(() => adaptiveRoute.value?.candidate_draft?.remaining_path || [])
const graphEdgeCount = computed(() => pathData.value?.micro_concept_graph?.metadata?.edge_count || routeEdges.value.length)
const crossGraph = computed(() => pathData.value?.cross_domain_micro_graph || null)
const crossDomainSupports = computed(() => adaptiveRoute.value?.cross_domain_supports || [])
const semanticLog = computed(() => crossGraph.value?.metadata?.similarity_log || [])
const todayPlan = computed(() => adaptiveRoute.value?.session_plan || {})
const visibleEstimatedMinutes = computed(() => todayPlan.value?.today_minutes || adaptiveRoute.value?.estimated_minutes || 0)
const plannerReview = computed(() => adaptiveRoute.value?.planner_review || {})
const textbookDraftNodes = computed(() => textbookDraft.value?.nodes || [])
const textbookDraftReady = computed(() => textbookDraft.value?.state === 'draft_ready')
const textbookGeneration = computed(() => textbookDraft.value?.generation || { status: 'not_started' })
const textbookGenerationLabel = computed(() => ({
  not_started: '尚未调用模型',
  running: '模型定制中',
  completed: '模型草稿已完成，等待确定性校验/确认',
  failed: '模型定制失败，可重试',
  legacy: '已有版本（未记录新模型调用）',
}[textbookGeneration.value.status] || '路径状态待确认'))
const aggregatePlanId = computed(() => String(route.query.aggregate_plan_id || ''))
const aggregatePlanVersion = computed(() => {
  const versions = Array.isArray(aggregatePlan.value?.versions) ? aggregatePlan.value.versions : []
  return versions.find(item => item.id === aggregatePlan.value?.current_version_id) || versions.at(-1) || null
})
const aggregatePlanContent = computed(() => aggregatePlanVersion.value?.content || {})
const aggregatePlanNodes = computed(() => Array.isArray(aggregatePlanContent.value.nodes) ? aggregatePlanContent.value.nodes : [])
const aggregatePlanCourseIds = computed(() => Array.from(new Set(
  aggregatePlanNodes.value
    .map(node => String(node?.node_key || '').split('::', 1)[0])
    .filter(Boolean),
)))
const aggregatePlanMinutes = computed(() => aggregatePlanNodes.value.reduce(
  (total, node) => total + Number(node?.estimate_max_minutes || node?.estimate_min_minutes || 0),
  0,
))
const currentCourseId = computed(() => (
  (isPersonalPath.value ? m5Path.value?.course_id : '')
  || route.query.course_id
  || demoContext.value?.course?.id
  || m5Path.value?.course_id
  || ''
))
const pathRecords = computed(() => {
  const byCourse = new Map()
  for (const path of m5Paths.value) {
    if (!path?.course_id) continue
    const previous = byCourse.get(path.course_id)
    const shouldReplace = !previous
      || (path.status === 'active' && previous.status !== 'active')
      || (path.status === previous.status && String(path.updated_at || '') > String(previous.updated_at || ''))
    if (shouldReplace) byCourse.set(path.course_id, path)
  }
  return Array.from(byCourse.values())
})
const scheduleDays = computed(() => Array.isArray(schedule.value?.days) ? schedule.value.days : [])
const selectedSchedule = computed(() => schedule.value?.selected || { day: selectedScheduleDay.value, tasks: [], total_minutes: 0, progress: { completed: 0, total: 0 } })
const scheduleTasks = computed(() => Array.isArray(selectedSchedule.value.tasks) ? selectedSchedule.value.tasks : [])
const canonicalNodes = computed(() => {
  const nodes = m5Path.value?.nodes || pathData.value?.path_nodes || pathData.value?.nodes || []
  return Array.isArray(nodes) ? nodes : []
})
const subjects = computed(() => {
  const course = demoContext.value?.course || {}
  const records = pathRecords.value.length ? pathRecords.value : (m5Path.value ? [m5Path.value] : [])
  if (!records.length) {
    const completed = canonicalNodes.value.filter(item => item.status === 'completed' || item.status === '已完成').length
    return [{
      id: currentCourseId.value || 'current-course',
      path_id: m5Path.value?.id || '',
      lock_version: m5Path.value?.lock_version,
      title: course.title || pathData.value?.course_title || pathData.value?.course?.title || '当前课程',
      completed,
      total: canonicalNodes.value.length,
      progress: canonicalNodes.value.length ? Math.round(completed / canonicalNodes.value.length * 100) : 0,
      status: m5Path.value?.status || 'active',
    }]
  }
  return records.map(item => {
    const completed = (item.nodes || []).filter(node => node.status === 'completed' || node.status === '已完成').length
    const total = (item.nodes || []).length
    return {
      id: item.course_id,
      path_id: item.id,
      lock_version: item.lock_version,
      title: item.course?.title || (item.course_id === course.id ? course.title : '') || item.course_id || '当前课程',
      completed,
      total,
      progress: total ? Math.round(completed / total * 100) : 0,
      status: item.status || 'active',
    }
  })
})
const activeSubjectId = computed(() => selectedSubjectId.value || subjects.value[0]?.id || '')
const todayTaskIds = computed(() => todayWork.value.map(item => item.node_id || item.node_key || item.id))
const pathTasks = computed(() => {
  const todayByKey = new Map(todayWork.value.map(item => [item.node_id || item.node_key || item.id, item]))
  return canonicalNodes.value.map((item, index) => {
    const key = item.id || item.node_id || item.node_key || `path-node-${index}`
    const today = todayByKey.get(key) || todayWork.value.find(candidate => candidate.node_key === item.node_key)
    return {
      ...item,
      id: key,
      subject_id: activeSubjectId.value,
      required: item.required !== false && !item.is_extension,
      resource_type: item.node_type,
      estimate_minutes: item.estimate_minutes || today?.estimate_minutes || [item.estimate_min_minutes, item.estimate_max_minutes],
      completion_criteria: item.completion_criteria || today?.completion_criteria,
      continue_route: item.continue_route || today?.continue_route || `/workspace?course_id=${encodeURIComponent(currentCourseId.value)}&node_id=${encodeURIComponent(key)}`,
      status: item.status || today?.status || 'pending',
    }
  })
})
const allPathTasks = computed(() => pathRecords.value.flatMap(path => {
  const pathNodes = Array.isArray(path.nodes) ? path.nodes : []
  const scheduleCourse = schedule.value?.courses?.find(item => item.path_id === path.id)
  return pathNodes.map((item, index) => {
    const key = item.id || item.node_id || item.node_key || `${path.id}-node-${index}`
    const scheduleNode = scheduleCourse?.nodes?.find(node => node.id === key || node.node_key === item.node_key)
    return {
      ...item,
      id: key,
      subject_id: path.course_id,
      required: item.required !== false && !item.is_extension,
      resource_type: item.node_type,
      estimate_minutes: item.estimate_minutes || [item.estimate_min_minutes, item.estimate_max_minutes],
      completion_criteria: item.completion_criteria,
      resources: scheduleNode?.resources || item.resources || [],
      generation_context: scheduleNode?.generation_context || item.generation_context || null,
      knowledge_point_id: scheduleNode?.knowledge_point_id || item.knowledge_point_id || '',
      knowledge_point_title: scheduleNode?.knowledge_point_title || item.knowledge_point_title || '',
      continue_route: item.continue_route || `/workspace?course_id=${encodeURIComponent(path.course_id || '')}&node_id=${encodeURIComponent(key)}`,
      status: scheduleNode?.status === 'skipped' ? 'completed' : (item.status || scheduleNode?.status || 'pending'),
    }
  })
}))
const visiblePathTasks = computed(() => {
  if (pathViewMode.value === 'subject' && activeSubjectId.value) {
    return (allPathTasks.value.length ? allPathTasks.value : pathTasks.value).filter(item => !item.subject_id || item.subject_id === activeSubjectId.value)
  }
  return allPathTasks.value.length ? allPathTasks.value : pathTasks.value
})
const visibleSubjects = computed(() => (
  pathViewMode.value === 'subject' && activeSubjectId.value
    ? subjects.value.filter(item => item.id === activeSubjectId.value)
    : subjects.value
))
function coursePathTasks(courseId) {
  return (allPathTasks.value.length ? allPathTasks.value : pathTasks.value)
    .filter(item => !courseId || !item.subject_id || item.subject_id === courseId)
}
const todayTasks = computed(() => {
  const taskMap = new Map(visiblePathTasks.value.map(item => [item.id, item]))
  return todayWork.value.map(item => {
    const pathTask = taskMap.get(item.node_id) || taskMap.get(item.node_key)
    return {
      ...(pathTask || {}),
      ...item,
      id: item.node_id || item.node_key || pathTask?.id,
      title: item.title || pathTask?.title,
      required: item.required !== false && pathTask?.required !== false,
      continue_route: item.continue_route || pathTask?.continue_route,
    }
  })
})
const completedReturnTask = computed(() => {
  const task = selectedTodayTask.value
  if (!task || !['completed', '已完成'].includes(task.status)) return null
  return todayTaskIds.value.includes(task.id) ? null : task
})
const generationResources = [
  { type: 'handout', label: '个性化讲义', routeLabel: '讲义空间', estimate: 12, completionRule: '阅读重点内容并完成讲义内学习检查' },
  { type: 'mind_map', label: '思维导图', routeLabel: '思维导图空间', estimate: 6, completionRule: '查看关键节点并完成一次导图回顾' },
  { type: 'quiz', label: '测验题资源', routeLabel: '测验题资源', estimate: 10, completionRule: '提交答案并获得服务端即时判分' },
  { type: 'training_task', label: '实训任务书', routeLabel: '实训任务书', estimate: 12, completionRule: '按任务书检查点完成规定提交物' },
  { type: 'code_sandbox', label: '代码沙盒任务', routeLabel: '代码沙盒', estimate: 25, completionRule: '完成代码任务并保存一次真实运行结果' },
  { type: 'video', label: '视频推荐', routeLabel: '视频空间', estimate: 8, completionRule: '观看推荐片段并记录一条学习笔记' },
  { type: 'deck', label: 'PPT / 网页课件', routeLabel: '课件空间', estimate: 8, completionRule: '完成课件阅读并通过页面学习检查' },
  { type: 'interactive_model', label: '可交互模型', routeLabel: '交互模型空间', estimate: 15, completionRule: '完成参数实验并提交一次观察结果' },
  { type: 'feynman', label: '费曼复述任务', routeLabel: '复述任务空间', estimate: 8, completionRule: '完成规定阶段的复述、追问与改进' },
]
const selectedGenerationContext = computed(() => selectedTodayTask.value?.generation_context || null)
const generationItems = computed(() => generationResources.map(resource => {
  const item = generationJob.value?.items?.find(candidate => candidate.type === resource.type)
  return { ...resource, ...(item || { type: resource.type, state: 'requested', input: null }) }
}))
const generationCompletedCount = computed(() => generationItems.value.filter(item => item.state === 'succeeded').length)
const generationFailedCount = computed(() => generationItems.value.filter(item => item.state === 'failed').length)
const generationProgress = computed(() => Math.round((generationCompletedCount.value / generationResources.length) * 100))
const generationHasRecoverable = computed(() => generationItems.value.some(item => ['running', 'failed'].includes(item.state)))
const generationStatusLabel = computed(() => {
  if (!generationJob.value) return '尚未生成'
  if (generationJob.value.status === 'succeeded') return '全部已归档'
  if (generationFailedCount.value) return `部分失败 · ${generationFailedCount.value} 项可重试`
  if (generationCompletedCount.value) return `部分完成 · ${generationCompletedCount.value}/${generationResources.length}`
  return generationJob.value.status === 'queued' ? '已进入生成队列' : '生成处理中'
})
const futureTasks = computed(() => visiblePathTasks.value.filter(item => !todayTaskIds.value.includes(item.id)))
const pathProgress = computed(() => {
  const source = visiblePathTasks.value
  const total = source.length
  const completed = source.filter(item => item.status === 'completed' || item.status === '已完成').length
  return { total, completed, percentage: total ? Math.round(completed / total * 100) : 0 }
})
const pathState = computed(() => {
  if (pathLoadError.value || error.value) return 'failed'
  if (loading.value) return 'loading'
  if (!m5Path.value && !canonicalNodes.value.length && !aggregatePlan.value) return 'empty'
  return 'ready'
})

function message(err) {
  const detail = err?.response?.data?.detail || err?.detail
  return detail?.message || (typeof detail === 'string' ? detail : '') || err?.message || '请求失败'
}
const semanticFocusConcept = computed(() => {
  const concepts = (crossGraph.value?.nodes || []).map(node => String(node.concept))
  if (selectedSemanticConcept.value && concepts.includes(selectedSemanticConcept.value)) {
    return selectedSemanticConcept.value
  }
  const query = semanticQuery.value.trim().toLocaleLowerCase()
  if (query) {
    return concepts.find(concept => concept.toLocaleLowerCase() === query)
      || concepts.find(concept => concept.toLocaleLowerCase().includes(query))
      || semanticQuery.value.trim()
  }
  return routeFinalTarget.value || routeStageTarget.value || concepts[0] || ''
})
const semanticMatches = computed(() => {
  const focus = semanticFocusConcept.value
  const matches = new Map()
  semanticLog.value.forEach(item => {
    if (item.source !== focus && item.target !== focus) return
    const concept = item.source === focus ? item.target : item.source
    const previous = matches.get(concept)
    if (!previous || Number(item.similarity || 0) > previous.similarity) {
      matches.set(concept, {
        concept,
        similarity: Number(item.similarity || 0),
        evidence: item.evidence || '语义向量与知识依赖共同命中',
        domain: item.source === focus ? item.target_domain_label : item.source_domain_label,
      })
    }
  })
  ;(crossGraph.value?.edges || []).forEach(edge => {
    if (edge.from !== focus && edge.to !== focus) return
    const concept = edge.from === focus ? edge.to : edge.from
    if (matches.has(concept)) return
    matches.set(concept, {
      concept,
      similarity: Number(edge.similarity ?? 0.68),
      evidence: edge.type === 'cross_domain_prerequisite'
        ? '跨学科前置依赖，可用于补齐当前学习路径'
        : '课程知识图谱中的直接前置关系',
      domain: edge.from === focus ? edge.target_domain_label : edge.source_domain_label,
    })
  })
  return Array.from(matches.values()).sort((a, b) => b.similarity - a.similarity).slice(0, 6)
})

const conceptRecommendations = computed(() => {
  const activeConcept = nextSteps.value[0]?.concept
  if (!activeConcept || !recommendations.value || !Array.isArray(recommendations.value)) return []
  const conceptObj = recommendations.value.find(r => r.concept === activeConcept)
  if (!conceptObj || !conceptObj.resources) return []
  return Object.entries(conceptObj.resources).map(([key, res]) => {
    return {
      concept: activeConcept,
      title: res.resource_type,
      content: res.overview,
      badge: res.status === "generated" ? "✅ 已就绪" : "⚡ 待生成",
      source_name: res.role,
      resource_type: key, // "lecture", "mindmap", "code", "quiz", "video"
      url: key === 'video' ? `/api/v1/video/stream?concept=${activeConcept}&student_id=${studentId.value}` : '',
      status: res.status,
      note_id: res.note_id
    }
  })
})

function statusIcon(status) {
  if (status === '已完成') return '✅'
  if (status === '当前可学') return '▶️'
  return '🔒'
}

function statusColor(status) {
  if (status === '已完成') return 'border-emerald-300 bg-emerald-50'
  if (status === '当前可学') return 'border-blue-300 bg-blue-50 ring-2 ring-blue-200'
  return 'border-gray-200 bg-gray-50'
}

function knowledgePointChipClass(isWeak) {
  return isWeak ? 'path-kp-chip path-kp-chip--weak' : 'path-kp-chip'
}

function stepIndexClass(node) {
  if (node.mastered) return 'path-step-index path-step-index--mastered'
  if (node.status === '当前可学') return 'path-step-index path-step-index--active'
  return 'path-step-index'
}

function statusTextColor(status) {
  if (status === '已完成') return 'text-emerald-700'
  if (status === '当前可学') return 'text-blue-700'
  return 'text-gray-400'
}

function masteryColor(score) {
  if (score >= 60) return 'text-emerald-600'
  if (score >= 30) return 'text-amber-600'
  return 'text-red-600'
}

function masteryBarColor(score) {
  if (score >= 60) return 'bg-emerald-500'
  if (score >= 30) return 'bg-amber-500'
  return 'bg-red-500'
}

function routeActionColor(action) {
  if (action === '快速复核') return 'bg-emerald-50 text-emerald-700 border-emerald-100'
  if (action === '进阶攻克') return 'bg-purple-50 text-purple-700 border-purple-100'
  if (action === '巩固推进') return 'bg-blue-50 text-blue-700 border-blue-100'
  return 'bg-amber-50 text-amber-700 border-amber-100'
}

function formatMinutes(minutes) {
  const value = Number(minutes || 0)
  if (value >= 180) return `${(value / 60).toFixed(1)} 小时`
  return `${Math.round(value)} 分钟`
}

function goLearn(concept) {
  if (isTeacher.value) return // 教师查看路径时静止跳转去学习
  router.push({ path: '/learn', query: { q: concept } })
}

function goQuiz(concept) {
  if (isTeacher.value) return
  router.push({ path: '/learn', query: { quiz: concept } })
}

function goNotes(concept) {
  if (isTeacher.value) return
  router.push({ path: '/notes', query: { search: concept } })
}

function playVideo(url, concept = '') {
  videoPanelUrl.value = url
  videoPanelConcept.value = concept
  showVideoPanel.value = true
}

function canonicalPathAdapter(context) {
  const tasks = context?.path?.tasks || []
  const active = tasks.find(item => item.status === 'in_progress') || tasks.find(item => item.status === 'pending')
  return {
    course_title: context.course?.title || '',
    path_nodes: tasks.map(item => ({
      id: item.id,
      node_key: item.id,
      sequence: item.sequence,
      node_type: item.type || 'chapter',
      target_object_id: item.target_object_id,
      title: item.title,
      status: item.status,
      prerequisites: item.prerequisites || [],
      estimate_minutes: [item.estimate_minutes, item.estimate_minutes],
      is_extension: false,
    })),
    active_learning_target: active?.title || '',
    learning_chain: tasks.map(item => ({
      concept: item.title,
      status: item.status === 'completed' ? '已完成' : item.status === 'in_progress' ? '当前可学' : '待解锁',
      mastered: item.status === 'completed',
      mastery: item.status === 'completed' ? 100 : item.status === 'in_progress' ? 35 : 0,
      estimate_minutes: item.estimate_minutes,
      task_id: item.id,
    })),
    next_steps: tasks.filter(item => item.status !== 'completed').map(item => ({
      concept: item.title,
      estimate_minutes: item.estimate_minutes,
      task_id: item.id,
    })),
    progress_summary: {
      total_concepts: tasks.length,
      mastered: tasks.filter(item => item.status === 'completed').length,
      in_progress: tasks.filter(item => item.status === 'in_progress').length,
      locked: tasks.filter(item => item.status === 'pending').length,
    },
    stages: [{
      name: context.course?.title,
      concepts: tasks.map(item => item.title),
    }],
    adaptive_route: {
      target_concept: tasks.at(-1)?.title || '',
      final_goal_concept: tasks.at(-1)?.title || '',
      stage_target_concept: active?.title || '',
      estimated_minutes: tasks.reduce((sum, item) => sum + Number(item.estimate_minutes || 0), 0),
      confidence: 1,
      nodes: tasks.map(item => ({
        concept: item.title,
        action: item.status === 'in_progress' ? '巩固推进' : '按序学习',
        mastery: item.status === 'completed' ? 1 : item.status === 'in_progress' ? 0.35 : 0,
      })),
      edges: tasks.slice(1).map((item, index) => ({ from: tasks[index].title, to: item.title })),
      session_plan: { today_minutes: tasks.reduce((sum, item) => sum + Number(item.estimate_minutes || 0), 0) },
      planner_trace: ['读取正式学习路径', '按任务前置关系排序', '保留当前进行中任务'],
      resource_summary: { existing: tasks.length },
    },
  }
}

async function loadData() {
  loading.value = true
  error.value = ''
  pathLoadError.value = ''
  aggregatePlanError.value = ''
  aggregatePlan.value = null
  try {
    const [context, recs] = await Promise.all([
      isPersonalPath.value ? Promise.resolve(null) : getCompetitionDemoContext().catch(() => null),
      getRecommendations(studentId.value).catch(() => []),
    ])
    demoContext.value = context
    if (aggregatePlanId.value) {
      aggregatePlanLoading.value = true
      try {
        aggregatePlan.value = await getM5Plan(aggregatePlanId.value)
      } catch (planException) {
        aggregatePlanError.value = message(planException)
        throw new Error(`总路径草稿无法打开：${aggregatePlanError.value}`)
      } finally {
        aggregatePlanLoading.value = false
      }
    }
    const allPathsResponse = await listM5Paths().catch(() => ({ items: [] }))
    m5Paths.value = allPathsResponse.items || []
    const requestedPathId = String(route.query.path_id || '')
    const requestedPath = requestedPathId
      ? m5Paths.value.find(item => String(item.id) === requestedPathId)
      : null
    if (requestedPathId && !requestedPath) throw new Error('这条个人学习路径不存在或不属于当前账号。')
    const courseId = requestedPath?.course_id || route.query.course_id || context?.course?.id || ''
    if (isLearner.value && !isPersonalPath.value && courseId) {
      textbookDraft.value = await getM5TextbookPathDraft(courseId).catch((draftError) => {
        textbookDraftError.value = message(draftError)
        return null
      })
    }
    m5Path.value = requestedPath
      || pathRecords.value.find(item => item.course_id === courseId)
      || pathRecords.value.find(item => item.status === 'active')
      || pathRecords.value[0]
      || null
    scheduleLoading.value = true
    scheduleError.value = ''
    try {
      // A course-scoped path must keep Today work in that course.  The total
      // view is multi-course only when the route itself has no course scope.
      const scheduleCourseId = route.query.course_id
        || (pathViewMode.value === 'subject' ? activeSubjectId.value : '')
      schedule.value = await getM5Schedule(selectedScheduleDay.value, scheduleCourseId)
      selectedScheduleDay.value = Number(schedule.value?.selected_day || selectedScheduleDay.value || 1)
      todayWork.value = scheduleTasks.value
    } catch (scheduleException) {
      scheduleError.value = message(scheduleException)
      schedule.value = null
      todayWork.value = await getM5TodayWork(courseId).then(result => result.items || []).catch(() => [])
    } finally {
      scheduleLoading.value = false
    }
    generationJobs.value = courseId
      ? await listGenerationJobs(courseId).then(result => result.items || []).catch(() => [])
      : []
    const requestedTaskId = route.query.node_id || route.query.return_task || ''
    if (!selectedTodayTask.value && requestedTaskId) {
      selectedTodayTask.value = todayWork.value.find(item => (
        item.node_id === requestedTaskId || item.id === requestedTaskId
      )) || allPathTasks.value.find(item => item.id === requestedTaskId) || null
      generationJob.value = selectedTodayTask.value ? findGenerationJob(selectedTodayTask.value) : null
    } else if (selectedTodayTask.value) {
      const refreshed = todayWork.value.find(item => item.node_id === selectedTodayTask.value.node_id)
        || allPathTasks.value.find(item => item.id === (selectedTodayTask.value.node_id || selectedTodayTask.value.id))
      selectedTodayTask.value = refreshed || null
      generationJob.value = refreshed ? findGenerationJob(refreshed) : null
    }
    const path = context?.path ? canonicalPathAdapter(context) : await getLearningPath(studentId.value)
    pathData.value = path
    recommendations.value = recs || []
    if (!semanticQuery.value && path?.adaptive_route?.final_goal_concept) {
      const finalGoal = path.adaptive_route.final_goal_concept
      const allNodeNames = new Set([
        ...(path.micro_concept_graph?.nodes?.map(n => n.concept) || []),
        ...(path.cross_domain_micro_graph?.nodes?.map(n => n.concept) || [])
      ])
      if (allNodeNames.has(finalGoal)) {
        semanticQuery.value = finalGoal
      } else if (path.adaptive_route.stage_target_concept) {
        semanticQuery.value = path.adaptive_route.stage_target_concept
      }
    }
  } catch (e) {
    error.value = message(e)
    pathLoadError.value = error.value
  } finally {
    loading.value = false
    regenerating.value = false
    await nextTick()
    renderSemanticGraph()
  }
}

async function selectScheduleDay(day) {
  const nextDay = Math.max(1, Number(day || 1))
  selectedScheduleDay.value = nextDay
  scheduleLoading.value = true
  scheduleError.value = ''
  try {
    const scheduleCourseId = route.query.course_id
      || (pathViewMode.value === 'subject' ? activeSubjectId.value : '')
    schedule.value = await getM5Schedule(nextDay, scheduleCourseId)
    selectedScheduleDay.value = Number(schedule.value?.selected_day || nextDay)
    todayWork.value = scheduleTasks.value
    selectedTodayTask.value = null
    generationJob.value = null
  } catch (scheduleException) {
    scheduleError.value = message(scheduleException)
  } finally {
    scheduleLoading.value = false
  }
}

function findGenerationJob(task) {
  const context = task?.generation_context
  if (!context?.knowledge_point_id) return null
  const expectedIdempotencyKey = generationIdempotencyKey(task)
  return generationJobs.value.find(job => (
    job.course_id === task.course_id
    && job.knowledge_point_id === context.knowledge_point_id
    && (!expectedIdempotencyKey || job.idempotency_key === expectedIdempotencyKey)
  )) || null
}

function selectTodayKnowledgePoint(task) {
  if (!task?.knowledge_point_id && !task?.generation_context?.knowledge_point_id) {
    generationError.value = '当前任务还没有绑定课程知识点，暂时不能生成资源包。'
    generationNotice.value = ''
    selectedTodayTask.value = task || null
    generationJob.value = null
    return
  }
  selectedTodayTask.value = task
  generationJob.value = findGenerationJob(task)
  generationError.value = ''
  generationNotice.value = generationJob.value
    ? '已恢复这个知识点上次的资源包生成记录。'
    : '已选择知识点。确认学习内容和当前学习情况后，可以一次生成九类资源。'
}

function taskKnowledgePointTitle(task) {
  return task?.generation_context?.knowledge_point_title
    || task?.knowledge_point_title
    || task?.title
    || '当前知识点'
}

function taskParentChapterTitle(task) {
  const chapterTitle = String(task?.title || '').trim()
  return chapterTitle && chapterTitle !== taskKnowledgePointTitle(task) ? chapterTitle : ''
}

function generationPayload(task) {
  const context = task?.generation_context || {}
  const knowledgePointId = context.knowledge_point_id || task?.knowledge_point_id
  const title = context.knowledge_point_title || task?.knowledge_point_title || task?.title || '今日知识点'
  const sourceRefIds = context.source_ref_ids || []
  const profileSnapshotId = context.profile_snapshot_id
  return {
    course_id: task.course_id || currentCourseId.value,
    knowledge_point_id: knowledgePointId,
    profile_snapshot_id: profileSnapshotId,
    idempotency_key: generationIdempotencyKey(task),
    path_id: task.path_id,
    task_id: task.node_id || task.id,
    learning_goal: [
      activeLearningTarget.value,
      task.completion_criteria || `理解并应用${title}`,
    ].filter(Boolean).join('；').slice(0, 512),
    items: generationResources.map(resource => ({
      type: resource.type,
      title: `${title} · ${resource.label}`,
      source_ref_ids: sourceRefIds,
      completion_rule: resource.completionRule,
    })),
  }
}

function generationIdempotencyKey(task) {
  const context = task?.generation_context || {}
  const knowledgePointId = context.knowledge_point_id || task?.knowledge_point_id || ''
  const pathVersionId = context.path_version_id || task?.path_version_id || 'current'
  const localDate = new Intl.DateTimeFormat('en-CA').format(new Date())
  return `${studentId.value}:${task?.course_id || currentCourseId.value}:${knowledgePointId}:${pathVersionId}:${localDate}`
}

async function generateSelectedResourceBundle() {
  const task = selectedTodayTask.value
  const context = task?.generation_context
  if (!task || generationBusy.value) return
  if (!context?.ready) {
    generationError.value = context?.block_reason || '当前知识点还缺少可用的学习内容或学习情况记录。'
    generationNotice.value = ''
    return
  }
  generationBusy.value = true
  generationError.value = ''
  generationNotice.value = ''
  try {
    await openResourceGenerationChat(task)
  } catch (generationException) {
    generationError.value = message(generationException)
  } finally {
    generationBusy.value = false
  }
}

async function openResourceGenerationChat(task, resourceTypes = generationResources.map(item => item.type)) {
  const context = task?.generation_context || {}
  const knowledgePointId = context.knowledge_point_id || task?.knowledge_point_id || ''
  const title = context.knowledge_point_title || task?.knowledge_point_title || task?.title || '今日知识点'
  const sourceRefIds = [...new Set((context.source_ref_ids || []).map(item => String(item || '').trim()).filter(Boolean))]
  await router.push({
    path: '/chat',
    query: {
      intent: 'path_bundle',
      course_id: task?.course_id || currentCourseId.value || undefined,
      path_id: task?.path_id || context.path_id || undefined,
      task_id: task?.node_id || task?.id || undefined,
      knowledge_point_id: knowledgePointId || undefined,
      knowledge_point_title: title,
      source_ref_ids: sourceRefIds.length ? sourceRefIds.join(',') : undefined,
      resource_types: resourceTypes.join(','),
      request_id: generationIdempotencyKey(task),
      return_to: route.fullPath,
      prompt: `请帮我一键生成“${title}”的完整资源包（${resourceTypes.map(type => generationResources.find(item => item.type === type)?.label || type).join('、')}）。请结合当前课程资料、学习路径和我的学习情况生成，并在过程中展示协作步骤。`,
    },
  })
}

async function retrySelectedGenerationItem(item) {
  if (!generationJob.value?.job_id || generationBusy.value || item.state !== 'failed') return
  generationBusy.value = true
  generationError.value = ''
  generationNotice.value = ''
  try {
    await openResourceGenerationChat(selectedTodayTask.value, [item.type])
  } catch (generationException) {
    generationError.value = message(generationException)
  } finally {
    generationBusy.value = false
  }
}

async function recoverSelectedGenerationJob() {
  if (!generationJob.value?.job_id || generationBusy.value || !generationHasRecoverable.value) return
  generationBusy.value = true
  generationError.value = ''
  generationNotice.value = ''
  try {
    await openResourceGenerationChat(selectedTodayTask.value)
  } catch (generationException) {
    generationError.value = message(generationException)
  } finally {
    generationBusy.value = false
  }
}

function generationStateText(state) {
  return {
    requested: '待开始',
    queued: '排队中',
    retry_queued: '待重试',
    running: '生成中',
    succeeded: '已归档',
    failed: '生成失败',
    cancelled: '已取消',
  }[state] || '待生成'
}

function openGeneratedResource(item) {
  if (!item?.resource?.route) return
  router.push(item.resource.route)
}

function selectPathView(mode) {
  pathViewMode.value = mode
  if (mode === 'total') selectedSubjectId.value = ''
  selectScheduleDay(selectedScheduleDay.value)
}

async function toggleSubjectPath(subject) {
  if (!subject?.path_id || !['active', 'paused'].includes(subject.status)) return
  scheduleError.value = ''
  try {
    await transitionM5Path(
      subject.path_id,
      subject.status === 'paused' ? 'active' : 'paused',
      subject.lock_version,
    )
    await loadData()
  } catch (transitionException) {
    scheduleError.value = message(transitionException)
  }
}

async function prepareSubjectAdjustment(subject, action) {
  if (!subject?.id) return
  selectedSubjectId.value = subject.id
  pathViewMode.value = 'subject'
  generationNotice.value = action === 'supplement'
    ? '已选择补充该科目路径；下方草稿区可继续补充诊断证据。'
    : '已选择重新编排该科目路径；下方草稿区会保留当前版本并等待新的确认。'
  await selectScheduleDay(selectedScheduleDay.value)
  await nextTick()
  document.querySelector('[data-testid="textbook-path-draft"]')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

function openPathTask(task) {
  if (!task?.continue_route) return
  router.push(task.continue_route)
}

async function generateTextbookDraft() {
  const courseId = route.query.course_id || demoContext.value?.course?.id || ''
  if (isPersonalPath.value || !courseId || textbookDraftLoading.value) return
  textbookDraftLoading.value = true
  textbookDraftError.value = ''
  try {
    textbookDraft.value = await generateM5TextbookPathDraft(courseId)
  } catch (draftError) {
    textbookDraftError.value = message(draftError)
  } finally {
    textbookDraftLoading.value = false
  }
}

async function confirmTextbookDraft() {
  const plan = textbookDraft.value?.plan
  if (!plan?.id || !textbookDraftReady.value || textbookDraftLoading.value) return
  textbookDraftLoading.value = true
  textbookDraftError.value = ''
  try {
    await confirmM5Plan(plan.id, plan.lock_version)
    await loadData()
  } catch (draftError) {
    textbookDraftError.value = message(draftError)
  } finally {
    textbookDraftLoading.value = false
  }
}

function openTextbookSource(node) {
  if (node?.source?.route) router.push(node.source.route)
}

async function regeneratePath() {
  regenerating.value = true
  await loadData()
}

function renderSemanticGraph() {
  if (!semanticChartRef.value || !crossGraph.value) return
  if (!semanticChart) {
    semanticChart = echarts.init(semanticChartRef.value)
  }
  const routeSet = new Set(routeNodes.value.map(node => node.concept))
  const allNodes = crossGraph.value.nodes || []
  const focus = semanticFocusConcept.value
  const nodeByName = new Map(allNodes.map(node => [node.concept, node]))
  const scoreByPair = new Map()
  ;(crossGraph.value.edges || []).forEach(edge => {
    const key = [edge.from, edge.to].sort().join('\u0000')
    scoreByPair.set(key, Number(edge.similarity ?? 0.68))
  })
  semanticLog.value.forEach(item => {
    const key = [item.source, item.target].sort().join('\u0000')
    scoreByPair.set(key, Math.max(scoreByPair.get(key) || 0, Number(item.similarity || 0)))
  })

  const directNames = new Set()
  ;(crossGraph.value.edges || []).forEach(edge => {
    if (edge.from === focus) directNames.add(edge.to)
    if (edge.to === focus) directNames.add(edge.from)
  })
  semanticLog.value.forEach(item => {
    if (item.source === focus) directNames.add(item.target)
    if (item.target === focus) directNames.add(item.source)
  })

  const relationScore = concept => scoreByPair.get([focus, concept].sort().join('\u0000')) || 0
  const direct = Array.from(directNames)
    .filter(name => nodeByName.has(name))
    .sort((a, b) => relationScore(b) - relationScore(a))
    .slice(0, 9)
  const context = allNodes
    .filter(node => node.concept !== focus && !directNames.has(node.concept))
    .sort((a, b) => Number(routeSet.has(b.concept)) - Number(routeSet.has(a.concept)))
    .slice(0, 10)
    .map(node => node.concept)
  const visibleNames = [focus, ...direct, ...context].filter((name, index, names) => name && names.indexOf(name) === index)
  const nodeSet = new Set(visibleNames)
  const categoryNames = Array.from(new Set(visibleNames.map(name => nodeByName.get(name)?.domain_label || '课程图谱')))
  const categories = categoryNames.map(name => ({ name }))
  const palette = ['#315b6d', '#4a6570', '#647a82', '#7d8f94', '#53656d', '#819196']
  const colorByCategory = new Map(categoryNames.map((name, index) => [name, palette[index % palette.length]]))

  const ringPosition = (index, count, radius, offset = -Math.PI / 2) => {
    const angle = offset + (Math.PI * 2 * index) / Math.max(count, 1)
    return { x: Math.cos(angle) * radius, y: Math.sin(angle) * radius }
  }
  const graphWidth = semanticChartRef.value.clientWidth || 720
  const graphHeight = semanticChartRef.value.clientHeight || 380
  const graphUnit = Math.min(graphWidth, graphHeight)
  const directRadius = Math.max(140, graphUnit * 0.22)
  const contextRadius = Math.max(260, graphUnit * 0.42)
  const positions = new Map([[focus, { x: 0, y: 0 }]])
  direct.forEach((name, index) => positions.set(name, ringPosition(index, direct.length, directRadius)))
  context.forEach((name, index) => positions.set(name, ringPosition(index, context.length, contextRadius, -Math.PI / 2 + 0.18)))

  const nodes = visibleNames.map(name => {
    const node = nodeByName.get(name) || { concept: name }
    const isFocus = name === focus
    const isDirect = directNames.has(name)
    const score = relationScore(name)
    const domain = node.domain_label || '课程图谱'
    const position = positions.get(name) || { x: 0, y: 0 }
    return {
      id: name,
      name,
      value: Math.round((node.mastery || 0) * 100),
      similarity: score,
      domain,
      category: domain,
      x: position.x,
      y: position.y,
      draggable: true,
      symbolSize: isFocus ? 58 : isDirect ? 30 + score * 12 : routeSet.has(name) ? 28 : 20,
      itemStyle: {
        color: isFocus ? '#11212d' : colorByCategory.get(domain),
        opacity: isFocus || isDirect ? 1 : 0.68,
        borderColor: '#ffffff',
        borderWidth: isFocus ? 4 : 2,
        shadowBlur: isFocus ? 22 : isDirect ? 10 : 3,
        shadowColor: isFocus ? 'rgba(49, 91, 109, .34)' : 'rgba(23, 37, 46, .14)',
      },
      label: {
        show: isFocus || isDirect || routeSet.has(name),
        fontSize: isFocus ? 12 : 9,
        fontWeight: isFocus || score >= 0.75 ? 700 : 500,
        color: isFocus ? '#11212d' : '#253745',
        position: 'bottom',
        distance: isFocus ? 11 : 8,
        width: 92,
        overflow: 'truncate',
        textBorderColor: '#ffffff',
        textBorderWidth: 3,
      },
    }
  })

  const focusLinks = (crossGraph.value.edges || [])
    .filter(edge => nodeSet.has(edge.from) && nodeSet.has(edge.to) && (edge.from === focus || edge.to === focus))
  semanticLog.value.forEach(item => {
    if (!nodeSet.has(item.source) || !nodeSet.has(item.target)) return
    if (item.source !== focus && item.target !== focus) return
    if (!focusLinks.some(edge => edge.from === item.source && edge.to === item.target)) {
      focusLinks.push({ from: item.source, to: item.target, similarity: item.similarity, type: 'semantic_similarity' })
    }
  })
  const contextLinks = (crossGraph.value.edges || [])
    .filter(edge => nodeSet.has(edge.from) && nodeSet.has(edge.to) && edge.from !== focus && edge.to !== focus)
    .slice(0, 12)
  const links = [...focusLinks, ...contextLinks].map(edge => {
    const touchesFocus = edge.from === focus || edge.to === focus
    const score = Number(edge.similarity || scoreByPair.get([edge.from, edge.to].sort().join('\u0000')) || 0.45)
    return {
      source: edge.from,
      target: edge.to,
      value: score,
      lineStyle: {
        color: touchesFocus ? (score >= 0.75 ? '#344957' : '#60727c') : '#9ba8ab',
        opacity: touchesFocus ? 0.48 + score * 0.48 : 0.42,
        width: touchesFocus ? 1.4 + score * 3.2 : 1.35,
        type: touchesFocus ? 'solid' : 'dashed',
        curveness: touchesFocus ? 0.08 : 0.12,
      },
    }
  })

  semanticChart.setOption({
    tooltip: {
      trigger: 'item',
      backgroundColor: 'rgba(23, 37, 46, 0.96)',
      borderWidth: 1,
      borderColor: 'rgba(51, 65, 85, 0.5)',
      textStyle: { color: '#f7f9f9', fontSize: 10, fontFamily: 'system-ui, sans-serif' },
      padding: [8, 12],
      borderRadius: 10,
      shadowBlur: 10,
      shadowColor: 'rgba(23, 37, 46, 0.28)',
      formatter: params => {
        if (params.dataType === 'edge') {
          return `<div style="display:flex; flex-direction:column; gap:2px;">
            <span style="font-size:10px; color:#9ba8ab;">知识关联</span>
            <span style="font-weight:600;">${params.data.source} → ${params.data.target}</span>
            <span style="font-size:10px; color:#9ba8ab; margin-top:2px;">点击节点查看关联证据</span>
          </div>`
        }
        const stateColor = params.value >= 60 ? '#4a5c6a' : (params.value >= 30 ? '#f59e0b' : '#ef4444')
        return `<div style="display:flex; flex-direction:column; gap:4px;">
          <div style="display:flex; align-items:center; gap:6px;">
            <span style="display:inline-block; width:8px; height:8px; border-radius:50%; background:${stateColor};"></span>
            <span style="font-weight:700; color:#dce2e3;">${params.name}</span>
          </div>
          <span style="font-size:10px; color:#9ba8ab;">${params.data.domain} · 掌握度 <b style="color:#9ba8ab;">${params.value}%</b></span>
        </div>`
      },
    },
    animationDuration: 650,
    animationEasingUpdate: 'cubicOut',
    series: [{
      type: 'graph',
      layout: 'none',
      roam: true,
      cursor: 'move',
      categories,
      data: nodes,
      links,
      edgeSymbol: ['none', 'arrow'],
      edgeSymbolSize: [0, 5],
      emphasis: { 
        focus: 'adjacency',
        scale: 1.12,
        lineStyle: {
          width: 4,
          opacity: 1,
          color: '#344957',
        },
        itemStyle: {
          shadowBlur: 18,
          shadowColor: 'rgba(15, 118, 110, .5)'
        }
      },
      labelLayout: {
        hideOverlap: false,
        moveOverlap: 'shiftY',
      },
    }],
  }, true)
  requestAnimationFrame(() => semanticChart?.resize())
  semanticChart.off('click')
  semanticChart.off('mousedown')
  semanticChart.off('mouseup')
  let suppressClick = false
  semanticChart.on('click', params => {
    if (params.dataType !== 'node') return
    if (suppressClick) {
      suppressClick = false
      return
    }
    selectedSemanticConcept.value = params.name
    semanticQuery.value = params.name
  })
  let dragStart = null
  semanticChart.on('mousedown', params => {
    if (params.dataType !== 'node') return
    dragStart = {
      name: params.name,
      x: Number(params.data?.x),
      y: Number(params.data?.y),
    }
  })
  semanticChart.on('mouseup', params => {
    if (!dragStart || params.dataType !== 'node' || params.name !== dragStart.name) {
      dragStart = null
      return
    }
    const currentNode = (semanticChart.getOption()?.series?.[0]?.data || [])
      .find(node => node.name === params.name)
    const currentX = Number(currentNode?.x ?? params.data?.x)
    const currentY = Number(currentNode?.y ?? params.data?.y)
    const moved = Number.isFinite(currentX) && Number.isFinite(currentY) && Number.isFinite(dragStart.x) && Number.isFinite(dragStart.y)
      ? Math.hypot(currentX - dragStart.x, currentY - dragStart.y) > 8
      : true
    dragStart = null
    if (moved) {
      suppressClick = true
      autoArrangeAfterDrag(params.name)
    }
  })
}

watch([crossGraph, routeNodes, semanticFocusConcept], () => nextTick(renderSemanticGraph), { deep: true })
watch(isSemanticFullscreen, () => {
  if (semanticChart) {
    semanticChart.dispose()
    semanticChart = null
  }
  nextTick(() => {
    renderSemanticGraph()
  })
})
function resizeSemanticGraph() {
  semanticChart?.resize()
}

onMounted(() => {
  window.addEventListener('resize', resizeSemanticGraph)
  loadData()
})
onUnmounted(() => {
  window.removeEventListener('resize', resizeSemanticGraph)
  if (semanticChart) {
    semanticChart.dispose()
    semanticChart = null
  }
  if (arrangeTimer) {
    clearTimeout(arrangeTimer)
    arrangeTimer = null
  }
})
</script>

<template>
  <div v-if="loading" class="path-page path-page--loading" data-testid="path-loading">
    <div class="path-skeleton" aria-hidden="true" />
    <p>正在读取你的学习路径…</p>
  </div>
  <div v-else-if="error" class="path-page path-page--error" data-testid="path-error">
    <h1>学习路径暂时无法打开</h1>
    <p>{{ error }}</p>
    <button type="button" class="path-primary-action" @click="loadData">重新读取</button>
  </div>
  <div v-else class="path-page">
    <header class="path-page__header">
      <div class="path-page__heading">
        <button 
          v-if="isTeacher"
          class="path-back-action"
          @click="router.push('/teacher/students')"
        >
          <ChevronLeft :size="16" /> 返回学生列表
        </button>
        <div>
          <p class="path-page__eyebrow">学习空间 / 路径</p>
          <h1>学习路径</h1>
          <p>先完成今日任务，再继续下一阶段。</p>
        </div>
      </div>
      <div class="path-progress-summary">
        <strong>{{ pathProgress.percentage }}%</strong>
        <span>{{ pathProgress.completed }}/{{ pathProgress.total || 0 }} 项完成</span>
      </div>
    </header>

    <AggregationStatus :course-id="currentCourseId" class="path-feedback" />

    <section
      v-if="aggregatePlanId"
      class="aggregate-plan-panel"
      data-testid="aggregate-plan-draft"
      aria-labelledby="aggregate-plan-title"
    >
      <div class="aggregate-plan-panel__heading">
        <div>
          <p class="path-section-label">多课程入学评测</p>
          <h2 id="aggregate-plan-title">总路径草稿</h2>
          <p>这份草稿保留每门课程的边界，并按课程先修关系统一编排。</p>
        </div>
        <span class="aggregate-plan-panel__status">{{ aggregatePlan.status === 'draft' ? '等待确认' : aggregatePlan.status }}</span>
      </div>
      <p v-if="aggregatePlanLoading" class="aggregate-plan-panel__message">正在读取总路径草稿…</p>
      <p v-else-if="aggregatePlanError" class="aggregate-plan-panel__message aggregate-plan-panel__message--error" role="alert">{{ aggregatePlanError }}</p>
      <div v-else class="aggregate-plan-panel__meta">
        <span>版本 {{ aggregatePlanVersion?.number || '当前' }}</span>
        <span>课程 {{ aggregatePlanCourseIds.length }} 门</span>
        <span>任务 {{ aggregatePlanNodes.length }} 项</span>
        <span>预计 {{ formatMinutes(aggregatePlanMinutes) }}</span>
      </div>
      <p v-if="aggregatePlanContent.goal" class="aggregate-plan-panel__goal">{{ aggregatePlanContent.goal }}</p>
      <ol v-if="aggregatePlanNodes.length" class="aggregate-plan-panel__nodes">
        <li v-for="(node, index) in aggregatePlanNodes" :key="node.node_key || index">
          <span>{{ index + 1 }}</span>
          <div>
            <strong>{{ node.title }}</strong>
            <span class="path-supporting-text">{{ node.node_key?.split('::', 1)[0] || '当前课程' }} · {{ node.estimate_max_minutes || node.estimate_min_minutes || 0 }} 分钟</span>
          </div>
        </li>
      </ol>
      <p v-else class="aggregate-plan-panel__message">当前草稿没有可显示的任务。</p>
      <div v-if="aggregatePlanContent.assumptions?.length" class="aggregate-plan-panel__assumptions">
        <strong>计划说明</strong>
        <ul>
          <li v-for="assumption in aggregatePlanContent.assumptions" :key="assumption">{{ assumption }}</li>
        </ul>
      </div>
    </section>

    <nav class="path-view-switch" aria-label="路径视图">
      <button
        type="button"
        :class="{ 'path-view-switch__item--active': pathViewMode === 'total' }"
        data-testid="path-total-view"
        @click="selectPathView('total')"
      >总路径</button>
      <button
        type="button"
        :class="{ 'path-view-switch__item--active': pathViewMode === 'subject' }"
        data-testid="path-subject-view"
        @click="selectPathView('subject')"
      >科目路径</button>
      <span class="path-view-switch__date">{{ selectedSchedule?.date || new Date().toLocaleDateString('zh-CN', { year: 'numeric', month: 'long', day: 'numeric' }) }}</span>
    </nav>

    <section v-if="pathState !== 'empty'" class="path-day-strip" data-testid="path-day-strip" aria-label="学习日历">
      <div class="path-day-strip__heading">
        <div>
          <p class="path-section-label">学习日历</p>
          <strong>{{ scheduleLoading ? '正在调整日程…' : `D${selectedSchedule?.day || selectedScheduleDay}` }}</strong>
        </div>
        <span>{{ schedule?.total_days || 0 }} 天 · {{ selectedSchedule?.date || '日期待加载' }}</span>
      </div>
      <div v-if="scheduleDays.length" class="path-day-strip__days" role="list">
        <button
          v-for="item in scheduleDays"
          :key="item.day"
          type="button"
          role="listitem"
          class="path-day-strip__day"
          :class="{ 'path-day-strip__day--active': Number(selectedSchedule?.day) === Number(item.day) }"
          :aria-pressed="Number(selectedSchedule?.day) === Number(item.day)"
          :data-testid="`path-day-${item.day}`"
          @click="selectScheduleDay(item.day)"
        >D{{ item.day }}</button>
      </div>
      <p v-else class="path-day-strip__empty">当前还没有可投影的跨课程日程。</p>
      <p v-if="scheduleError" class="path-day-strip__error" role="alert">{{ scheduleError }}</p>
    </section>

    <div v-if="pathState === 'empty' && !aggregatePlan" class="path-empty-state" data-testid="path-empty">
      <Target :size="22" />
      <h2>还没有正式学习路径</h2>
      <p>完成入学诊断后，系统会根据你的课程和学习目标生成路径。</p>
      <button type="button" class="path-primary-action" @click="router.push('/workspace/assessment/entry')">进入入学诊断</button>
    </div>

    <section v-else class="path-layout" data-testid="path-overview">
      <main class="path-main-column">
        <section v-if="completedReturnTask" class="path-completion-receipt" data-testid="path-completion-receipt">
          <CheckCircle2 :size="22" />
          <div>
            <p class="path-section-label">本轮学习已完成</p>
            <h2>{{ taskKnowledgePointTitle(completedReturnTask) }}</h2>
            <p>当前任务 1/1 完成，学习记录已经更新。下方日程已推进到下一项。</p>
          </div>
        </section>

        <section class="path-focus-band">
          <div>
            <p class="path-section-label">D{{ selectedSchedule?.day || selectedScheduleDay }} · {{ pathViewMode === 'total' ? '总路径' : '科目路径' }}</p>
            <h2>{{ todayTasks.length ? '进行中 · 今天学什么' : '今天没有必做任务' }}</h2>
            <p>{{ todayTasks.length ? `${todayTasks[0]?.course_title || subjects.find(item => item.id === activeSubjectId)?.title || '当前课程'} · ${taskKnowledgePointTitle(todayTasks[0])}${taskParentChapterTitle(todayTasks[0]) ? ` · 所属章节 ${taskParentChapterTitle(todayTasks[0])}` : ''}` : '可以查看接下来的路径，或调整学习计划。' }}</p>
          </div>
          <div class="path-focus-band__count">
            <strong>{{ todayTasks.length }}</strong>
            <span>项今日任务 · {{ selectedSchedule?.progress?.completed || 0 }}/{{ selectedSchedule?.progress?.total || todayTasks.length }} 完成</span>
          </div>
        </section>

        <section v-if="todayTasks[0]" class="path-current-day-summary" data-testid="current-day-summary">
          <div><span>预计时长</span><strong>{{ formatMinutes(selectedSchedule?.total_minutes || todayTasks.reduce((sum, item) => sum + Number(item.estimate_minutes || 0), 0)) }}</strong></div>
          <div><span>今日进度</span><strong>{{ selectedSchedule?.progress?.completed || 0 }}/{{ selectedSchedule?.progress?.total || todayTasks.length }}</strong></div>
          <div><span>完成标准</span><strong>{{ todayTasks[0]?.completion_criteria || '完成学习并留下可追溯证据' }}</strong></div>
        </section>

        <PathTaskList :tasks="todayTasks" :today-task-ids="todayTaskIds" empty-label="今天暂无必做任务。" @open="openPathTask" />

        <section class="generation-panel path-section" data-testid="today-resource-generation">
          <div class="path-section__heading">
            <div>
              <p class="path-section-label">今日知识点</p>
              <h2>生成完整资源包</h2>
            </div>
            <span v-if="generationJob" class="generation-panel__status">{{ generationStatusLabel }}</span>
          </div>
          <p class="generation-panel__intro">先选择一个今日任务，系统会结合课程内容、你的学习情况和最近学习表现生成九类资源，并分别归档到对应空间。</p>

          <div class="generation-task-picker" data-testid="today-knowledge-points">
            <button
              v-for="task in todayTasks"
              :key="`generate-${task.id}`"
              type="button"
              class="generation-task-picker__item"
              :class="{ 'generation-task-picker__item--selected': selectedTodayTask?.id === task.id }"
              @click="selectTodayKnowledgePoint(task)"
            >
              <span>
                <strong>{{ taskKnowledgePointTitle(task) }}</strong>
                <span class="path-supporting-text">{{ taskParentChapterTitle(task) ? `所属章节 ${taskParentChapterTitle(task)} · ` : '' }}{{ task.required === false ? '可选拓展' : '今日必做' }} · {{ formatMinutes(Array.isArray(task.estimate_minutes) ? task.estimate_minutes[0] : task.estimate_minutes) }}</span>
              </span>
              <CheckCircle2 v-if="generationJob?.knowledge_point_id === (task.knowledge_point_id || task.generation_context?.knowledge_point_id)" :size="17" />
              <ArrowRight v-else :size="17" />
            </button>
            <p v-if="!todayTasks.length" class="generation-panel__empty">今天没有可生成资源包的必做知识点。</p>
          </div>

          <div v-if="selectedTodayTask" class="generation-panel__selected" data-testid="selected-knowledge-point">
            <div class="generation-panel__selected-copy">
              <strong>{{ taskKnowledgePointTitle(selectedTodayTask) }}</strong>
              <span>{{ taskParentChapterTitle(selectedTodayTask) ? `所属章节 ${taskParentChapterTitle(selectedTodayTask)} · ` : '' }}{{ selectedTodayTask.required === false ? '可选拓展' : '今日必做' }} · 完成条件：{{ selectedTodayTask.completion_criteria || '完成学习并留下可追溯证据' }}</span>
            </div>
            <div class="generation-panel__context">
              <span>参考材料 {{ selectedGenerationContext?.source_ref_ids?.length || 0 }} 条</span>
              <span>学习情况 {{ selectedGenerationContext?.profile_snapshot_id ? '已就绪' : '缺失' }}</span>
              <span>{{ generationStatusLabel }}</span>
            </div>
            <p v-if="generationError" class="generation-panel__feedback generation-panel__feedback--error" role="alert">{{ generationError }}</p>
            <p v-else-if="generationNotice" class="generation-panel__feedback" role="status">{{ generationNotice }}</p>
            <p v-if="selectedGenerationContext && !selectedGenerationContext.ready" class="generation-panel__blocker">{{ selectedGenerationContext.block_reason }}</p>
            <button
              type="button"
              class="path-primary-action generation-panel__generate"
              :disabled="generationBusy || !selectedGenerationContext?.ready || Boolean(generationJob)"
              @click="generateSelectedResourceBundle"
            >
              <RefreshCw v-if="generationBusy" :size="16" class="generation-spin" />
              <Zap v-else :size="16" />
              {{ generationJob ? '已创建，等待生成执行' : '一键生成完整资源包' }}
            </button>
          </div>

          <div v-if="generationJob" class="generation-progress" data-testid="resource-generation-status">
            <div class="generation-progress__heading">
              <span>{{ generationStatusLabel }}</span>
              <strong>{{ generationCompletedCount }}/{{ generationResources.length }} · {{ generationProgress }}%</strong>
            </div>
            <div class="generation-progress__track"><span :style="{ width: `${generationProgress}%` }" /></div>
            <p class="generation-panel__note">生成资源不等于已经掌握。进入资源并完成相应练习后，学习路径才会更新。</p>
            <div class="generation-resource-list">
              <article v-for="item in generationItems" :key="item.type" class="generation-resource-item">
                <div class="generation-resource-item__icon"><CheckCircle2 v-if="item.state === 'succeeded'" :size="17" /><Clock v-else :size="17" /></div>
                <div class="generation-resource-item__body">
                  <strong>{{ item.label }}</strong>
                  <span>{{ item.routeLabel }} · 预计 {{ item.estimate }} 分钟 · {{ generationStateText(item.state) }}</span>
                  <span v-if="item.state === 'failed'" class="path-supporting-text">{{ item.failure?.message || '生成执行失败，请只重试此项。' }}</span>
                </div>
                <button v-if="item.state === 'failed'" type="button" class="generation-resource-item__action" :disabled="generationBusy" @click="retrySelectedGenerationItem(item)">重试此项</button>
                <button v-else-if="item.state === 'succeeded' && item.resource?.route" type="button" class="generation-resource-item__action" @click="openGeneratedResource(item)">进入资源</button>
              </article>
            </div>
            <button v-if="generationHasRecoverable" type="button" class="path-secondary-action generation-panel__recover" :disabled="generationBusy" @click="recoverSelectedGenerationJob">
              <RefreshCw :size="15" /> 恢复中断项
            </button>
          </div>
        </section>

        <details class="path-section path-section--future" open>
          <summary>
            <span><strong>接下来</strong><span class="path-supporting-text">按前置关系排列的后续任务</span></span>
            <span>{{ futureTasks.length }} 项</span>
          </summary>
          <PathTaskList :tasks="futureTasks" :today-task-ids="todayTaskIds" empty-label="完成今天的任务后，下一项会出现在这里。" @open="openPathTask" />
        </details>

        <section class="path-section" data-testid="all-course-paths">
          <div class="path-section__heading">
            <div>
              <p class="path-section-label">全部课程路径</p>
              <h2>按课程查看学习任务</h2>
            </div>
            <span class="path-section__progress">{{ subjects.length }} 门课程</span>
          </div>
          <div class="path-course-paths">
            <article v-for="subject in visibleSubjects" :key="subject.id" class="path-course-path">
              <header class="path-course-path__heading">
                <div>
                  <h3>{{ subject.title }}</h3>
                  <span>{{ subject.completed }}/{{ subject.total }} 项完成 · {{ subject.status === 'paused' ? '已暂停' : '可继续学习' }}</span>
                </div>
                <strong>{{ subject.progress }}%</strong>
              </header>
              <div class="path-progress-track" :aria-label="`${subject.title} 完成进度`">
                <span :style="{ width: `${subject.progress}%` }" />
              </div>
              <PathTaskList :tasks="coursePathTasks(subject.id)" :today-task-ids="todayTaskIds" :empty-label="`${subject.title} 暂无可展示任务。`" @open="openPathTask" />
            </article>
          </div>
          <p class="path-section__note">路径会根据有证据的学习行为更新；普通浏览不会改变掌握度。</p>
        </section>
      </main>

      <aside class="path-side-column">
        <section class="path-side-panel">
          <div class="path-side-panel__heading">
            <div>
              <p class="path-section-label">科目进度</p>
              <h2>我的学习安排</h2>
            </div>
            <Layers :size="18" />
          </div>
          <article
            v-for="subject in subjects"
            :key="subject.id"
            class="path-subject"
            :class="{ 'path-subject--active': pathViewMode === 'subject' && activeSubjectId === subject.id }"
          >
            <button type="button" class="path-subject__select" @click="selectedSubjectId = subject.id; pathViewMode = 'subject'; selectScheduleDay(selectedScheduleDay)">
              <span class="path-subject__title">{{ subject.title }}</span>
            </button>
            <span class="path-subject__meta">{{ subject.status === 'paused' ? '已暂停' : subject.status === 'completed' ? '已完成' : '已启用' }} · {{ subject.completed }}/{{ subject.total }} 项完成</span>
            <span class="path-subject__track"><i :style="{ width: `${subject.progress}%` }" /></span>
            <span class="path-subject__actions" @click.stop>
              <button type="button" class="path-subject__action" :data-testid="`subject-toggle-${subject.id}`" @click="toggleSubjectPath(subject)">
                {{ subject.status === 'paused' ? '启用' : '暂停' }}
              </button>
              <button type="button" class="path-subject__action" @click="prepareSubjectAdjustment(subject, 'supplement')">补充</button>
              <button type="button" class="path-subject__action" @click="prepareSubjectAdjustment(subject, 'replan')">重新编排</button>
            </span>
          </article>
        </section>

        <section class="path-side-panel">
          <div class="path-side-panel__heading">
            <div>
              <p class="path-section-label">学习节奏</p>
              <h2>学习时长</h2>
            </div>
            <Clock :size="18" />
          </div>
          <div class="path-budget">
            <strong>{{ formatMinutes(visibleEstimatedMinutes) }}</strong>
            <span>当前路径预计用时，所有任务按先修关系开放</span>
          </div>
        </section>
      </aside>
    </section>

    <section class="path-generated-content">

    <section
      v-if="isLearner && !isPersonalPath"
      data-testid="textbook-path-draft"
      class="border-y border-teal-100 bg-white px-4 py-5 sm:px-5"
    >
      <div class="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div class="min-w-0">
          <div class="flex flex-wrap items-center gap-2">
            <h2
              class="text-sm font-bold text-slate-800"
              data-model="deepseek-v4-flash"
              data-draft-label="教材锚定路径草稿"
              data-draft-policy="用户确认前仅为草稿"
              data-version-label="版本变化"
            >诊断定制路径草稿（教材锚定范围）</h2>
            <span
              data-testid="textbook-path-model-status"
              data-failure-policy="模型失败不会改用模板"
              class="rounded px-2 py-0.5 text-sm font-semibold"
              :class="textbookDraftReady ? 'bg-amber-50 text-amber-700' : textbookGeneration.status === 'failed' ? 'bg-rose-50 text-rose-700' : 'bg-emerald-50 text-emerald-700'"
            >
              {{ textbookDraftReady ? '等待用户确认' : textbookDraft?.state === 'confirmed' ? '已确认版本' : textbookGenerationLabel }}
            </span>
          </div>
        </div>
        <div class="flex flex-wrap items-end gap-2">
          <button
            data-testid="generate-textbook-path-draft"
            type="button"
            class="h-9 rounded bg-teal-700 px-3 text-sm font-semibold text-white hover:bg-teal-800 disabled:opacity-50"
            :disabled="textbookDraftLoading"
            @click="generateTextbookDraft"
          >
            {{ textbookDraftLoading ? '模型处理中' : textbookDraftReady ? '重新生成路径草稿' : '生成诊断定制草稿' }}
          </button>
          <button
            v-if="textbookDraftReady"
            data-testid="confirm-textbook-path-draft"
            type="button"
            class="h-9 rounded border border-emerald-600 px-3 text-sm font-semibold text-emerald-700 hover:bg-emerald-50 disabled:opacity-50"
            :disabled="textbookDraftLoading"
            @click="confirmTextbookDraft"
          >
            确认并发布路径
          </button>
        </div>
      </div>

      <p v-if="textbookDraftError" class="mt-3 text-sm text-rose-600">{{ textbookDraftError }}</p>
      <div v-if="textbookDraft?.plan" class="mt-4 grid gap-3">
        <div class="min-w-0">
          <div class="mb-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-slate-500">
            <span>预计 {{ textbookDraft.plan.total_minutes }} 分钟</span>
          </div>
          <ol class="grid gap-2 sm:grid-cols-2">
            <li
              v-for="(node, index) in textbookDraftNodes"
              :key="node.node_key"
              class="min-w-0 border-l-2 border-teal-500 bg-slate-50 px-3 py-3"
            >
              <div class="flex items-start justify-between gap-2">
                <div class="min-w-0">
              <p class="text-sm font-bold text-teal-700">第 {{ index + 1 }} 步 · 教材第 {{ node.chapter?.position }} 章</p>
                  <p class="mt-1 text-sm font-semibold leading-5 text-slate-800">{{ node.title }}</p>
                </div>
                <span class="shrink-0 text-sm text-slate-500">{{ node.estimate_max_minutes }} 分钟</span>
              </div>
              <div class="mt-2 flex flex-wrap gap-1">
                <span
                  v-for="kp in node.knowledge_points"
                  :key="kp.id"
                  :class="knowledgePointChipClass(kp.is_weak)"
                >
                  {{ kp.title }}{{ kp.is_weak ? ' · 薄弱点' : '' }}
                </span>
              </div>
              <button
                type="button"
                class="mt-2 inline-flex max-w-full items-center gap-1 text-sm font-semibold text-teal-700 hover:text-teal-900"
                @click="openTextbookSource(node)"
              >
                <BookOpen :size="11" />
                <span class="truncate">{{ node.source?.title || '查看教材来源' }}</span>
              </button>
            </li>
          </ol>
        </div>
      </div>
    </section>

    </section>
    <!-- 视频微课播放模态窗 -->
    <VideoRenderPanel
      :visible="showVideoPanel"
      :studentId="studentId"
      :knowledgePoint="videoPanelConcept"
      @close="showVideoPanel = false"
    />

  </div>
</template>

<style scoped>
.path-page {
  width: min(100%, 1320px);
  margin: 0 auto;
  padding: 0 0 48px;
}

.aggregate-plan-panel {
  display: grid;
  gap: 16px;
  margin: 18px 0 20px;
  padding: 22px 24px;
  border: 1px solid var(--color-border-strong);
  border-radius: var(--radius-card);
  background: var(--color-surface);
}

.aggregate-plan-panel__heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 20px;
}

.aggregate-plan-panel__heading h2 {
  margin: 4px 0 0;
  color: var(--color-text);
  font-size: 22px;
}

.aggregate-plan-panel__heading p:last-child {
  margin: 7px 0 0;
  color: var(--color-text-secondary);
  font-size: 14px;
  line-height: 1.55;
}

.aggregate-plan-panel__status {
  flex: 0 0 auto;
  padding: 6px 10px;
  color: var(--color-accent);
  border: 1px solid var(--color-border-strong);
  border-radius: var(--radius-control);
  background: var(--color-accent-soft);
  font-size: 14px;
  font-weight: 650;
}

.aggregate-plan-panel__meta {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 18px;
  color: var(--color-text-secondary);
  font-size: 14px;
}

.aggregate-plan-panel__goal,
.aggregate-plan-panel__message {
  margin: 0;
  color: var(--color-text-secondary);
  font-size: 15px;
  line-height: 1.6;
}

.aggregate-plan-panel__message--error { color: var(--color-danger); }

.aggregate-plan-panel__nodes {
  display: grid;
  gap: 8px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.aggregate-plan-panel__nodes li {
  display: grid;
  grid-template-columns: 30px minmax(0, 1fr);
  align-items: start;
  gap: 10px;
  padding: 10px 12px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-control);
  background: var(--color-surface-subtle);
}

.aggregate-plan-panel__nodes li > span {
  display: grid;
  width: 26px;
  height: 26px;
  place-items: center;
  color: #ffffff;
  border-radius: 50%;
  background: var(--color-accent);
  font-size: 14px;
  font-weight: 700;
}

.aggregate-plan-panel__nodes li > div {
  display: grid;
  gap: 3px;
  min-width: 0;
}

.aggregate-plan-panel__nodes strong {
  color: var(--color-text);
  font-size: 15px;
  line-height: 1.45;
}

.aggregate-plan-panel__nodes .path-supporting-text {
  color: var(--color-text-muted);
  font-size: 14px;
  line-height: 1.45;
}

.aggregate-plan-panel__assumptions {
  display: grid;
  gap: 7px;
  padding-top: 14px;
  border-top: 1px solid var(--color-border);
  color: var(--color-text-secondary);
  font-size: 14px;
  line-height: 1.55;
}

.aggregate-plan-panel__assumptions strong { color: var(--color-text); }
.aggregate-plan-panel__assumptions ul { display: grid; gap: 5px; margin: 0; padding-left: 18px; }

@media (max-width: 700px) {
  .aggregate-plan-panel { padding: 18px; }
  .aggregate-plan-panel__heading { flex-direction: column; gap: 10px; }
}

.path-page--loading,
.path-page--error {
  display: grid;
  min-height: 360px;
  place-items: center;
  align-content: center;
  gap: 12px;
  color: var(--color-text-secondary);
  text-align: center;
}

.path-page--loading p,
.path-page--error p {
  margin: 0;
  font-size: 15px;
}

.path-page--error h1 {
  margin: 0;
  color: var(--color-text);
  font-size: 22px;
}

.path-skeleton {
  width: 34px;
  height: 34px;
  border: 3px solid var(--color-border);
  border-top-color: var(--color-accent);
  border-radius: 50%;
  animation: path-spin 760ms linear infinite;
}

.path-page__header {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 24px;
  margin: 28px 0 20px;
}

.path-page__heading {
  display: flex;
  min-width: 0;
  align-items: flex-start;
  gap: 18px;
}

.path-page__eyebrow,
.path-section-label {
  margin: 0;
  color: var(--color-accent);
  font-size: 14px;
  font-weight: 700;
  letter-spacing: .02em;
  line-height: 1.4;
}

.path-page__heading h1 {
  margin: 4px 0 0;
  color: var(--color-text);
  font-family: var(--font-heading);
  font-size: 30px;
  font-weight: 650;
  line-height: 1.3;
}

.path-page__heading p:last-child {
  margin: 6px 0 0;
  color: var(--color-text-secondary);
  font-size: 15px;
  line-height: 1.55;
}

.path-back-action,
.path-secondary-action,
.path-primary-action {
  display: inline-flex;
  min-height: 40px;
  align-items: center;
  justify-content: center;
  gap: 7px;
  border-radius: var(--radius-control);
  padding: 0 14px;
  font-size: 15px;
  font-weight: 650;
  cursor: pointer;
}

.path-back-action {
  border: 1px solid var(--color-border);
  background: var(--color-surface);
  color: var(--color-text-secondary);
}

.path-back-action:hover,
.path-secondary-action:hover { border-color: var(--color-accent); background: var(--color-accent-soft); }

.path-progress-summary {
  display: grid;
  justify-items: end;
  gap: 2px;
  flex: 0 0 auto;
}

.path-progress-summary strong {
  color: var(--color-accent);
  font-size: 30px;
  font-weight: 700;
  line-height: 1.1;
}

.path-progress-summary span,
.path-section__progress {
  color: var(--color-text-secondary);
  font-size: 14px;
}

.path-view-switch {
  display: flex;
  align-items: center;
  gap: 4px;
  min-height: 48px;
  border-bottom: 1px solid var(--color-border);
}

.path-view-switch button {
  min-height: 48px;
  border: 0;
  border-bottom: 2px solid transparent;
  background: transparent;
  padding: 0 14px;
  color: var(--color-text-secondary);
  font-size: 16px;
  font-weight: 650;
  cursor: pointer;
}

.path-view-switch button:hover,
.path-view-switch__item--active { color: var(--color-accent) !important; border-bottom-color: var(--color-accent) !important; }

.path-view-switch__date {
  margin-left: auto;
  color: var(--color-text-muted);
  font-size: 14px;
}

.path-day-strip {
  display: grid;
  gap: 12px;
  margin-top: 18px;
  padding: 16px 18px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-panel);
  background: var(--color-surface);
}

.path-day-strip__heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}

.path-day-strip__heading strong { color: var(--color-text); font-size: 20px; }
.path-day-strip__heading span { color: var(--color-text-muted); font-size: 14px; }

.path-day-strip__days {
  display: flex;
  gap: 8px;
  overflow-x: auto;
  padding-bottom: 2px;
}

.path-day-strip__day {
  flex: 0 0 auto;
  min-width: 54px;
  min-height: 36px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-control);
  background: var(--color-surface-subtle);
  color: var(--color-text-secondary);
  font-size: 14px;
  font-weight: 650;
  cursor: pointer;
}

.path-day-strip__day:hover,
.path-day-strip__day--active { border-color: var(--color-accent); background: var(--color-accent-soft); color: var(--color-accent); }
.path-day-strip__empty,
.path-day-strip__error { margin: 0; color: var(--color-text-muted); font-size: 14px; }
.path-day-strip__error { color: var(--color-danger); }

.path-current-day-summary {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 1px;
  overflow: hidden;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-panel);
  background: var(--color-border);
}

.path-current-day-summary > div { display: grid; gap: 5px; min-width: 0; padding: 14px 16px; background: var(--color-surface); }
.path-current-day-summary span { color: var(--color-text-muted); font-size: 14px; }
.path-current-day-summary strong { overflow-wrap: anywhere; color: var(--color-text); font-size: 15px; line-height: 1.45; }

.path-layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(260px, 28%);
  gap: 24px;
  margin-top: 24px;
}

.path-main-column,
.path-side-column {
  display: grid;
  align-content: start;
  gap: 20px;
  min-width: 0;
}

.path-focus-band,
.path-completion-receipt,
.path-section,
.path-side-panel,
.path-advanced-section {
  border: 1px solid var(--color-border);
  border-radius: var(--radius-panel);
  background: var(--color-surface);
}

.path-focus-band {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
  padding: 22px 24px;
  background: var(--color-accent);
  color: #fff;
}

.path-completion-receipt {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  gap: 14px;
  align-items: start;
  padding: 18px 20px;
  border-left: 2px solid var(--color-accent);
  background: var(--color-success-soft);
}

.path-completion-receipt h2 { margin: 2px 0 4px; color: var(--color-text); font-size: 20px; line-height: 1.35; }
.path-completion-receipt p:last-child { margin: 0; color: var(--color-text-secondary); font-size: 14px; line-height: 1.55; }

.path-focus-band h2,
.path-section h2,
.path-side-panel h2 {
  margin: 3px 0 0;
  color: inherit;
  font-size: 20px;
  font-weight: 680;
  line-height: 1.4;
}

.path-focus-band .path-section-label { color: #d6e2e5; }
.path-focus-band p:last-child { margin: 6px 0 0; color: #f0f5f6; font-size: 15px; line-height: 1.55; }

.path-focus-band__count {
  display: grid;
  min-width: 86px;
  justify-items: end;
  gap: 3px;
}

.path-focus-band__count strong { font-size: 34px; line-height: 1.15; }
.path-focus-band__count span { color: #d6e2e5; font-size: 14px; white-space: nowrap; }

.path-kp-chip {
  padding: 2px 6px;
  color: var(--color-text-secondary);
  border: 1px solid var(--color-border);
  border-radius: 4px;
  background: var(--color-surface);
  font-size: 14px;
}

.path-kp-chip--weak {
  color: var(--color-danger);
  border-color: color-mix(in srgb, var(--color-danger) 24%, white);
  background: var(--color-danger-soft);
}

.path-step-index {
  display: flex;
  width: 24px;
  height: 24px;
  flex: none;
  align-items: center;
  justify-content: center;
  color: var(--color-text-secondary);
  border-radius: 50%;
  background: var(--color-surface-muted);
  font-size: 14px;
  font-weight: 700;
}

.path-step-index--mastered {
  color: var(--color-text);
  background: var(--color-border);
}

.path-step-index--active {
  color: #ffffff;
  background: var(--color-accent);
}

.path-section { padding: 22px 24px; }
.path-section--future { padding: 0; overflow: hidden; }

.path-section--future summary {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 18px 24px;
  color: var(--color-text-secondary);
  font-size: 15px;
  cursor: pointer;
  list-style: none;
}

.path-section--future summary::-webkit-details-marker { display: none; }
.path-section--future summary > span:first-child { display: grid; gap: 2px; }
.path-section--future summary strong { color: var(--color-text); font-size: 19px; }
.path-section--future summary .path-supporting-text { color: var(--color-text-muted); font-size: 14px; }
.path-section--future > .path-task-list { padding: 0 24px 22px; }

.path-section__heading,
.path-side-panel__heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.path-section__heading h2,
.path-side-panel__heading h2 { color: var(--color-text); }
.path-side-panel__heading > svg { color: var(--color-accent); }

.path-progress-track,
.path-subject__track {
  overflow: hidden;
  height: 8px;
  border-radius: 4px;
  background: var(--color-surface-muted);
}

.path-progress-track { margin-top: 18px; }
.path-progress-track span,
.path-subject__track i { display: block; height: 100%; border-radius: inherit; background: var(--color-accent); }
.path-section__note { margin: 12px 0 0; color: var(--color-text-muted); font-size: 14px; line-height: 1.55; }

.path-course-paths { display: grid; gap: 16px; margin-top: 18px; }
.path-course-path { display: grid; gap: 12px; min-width: 0; padding-top: 16px; border-top: 1px solid var(--color-border); }
.path-course-path:first-child { padding-top: 0; border-top: 0; }
.path-course-path__heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; }
.path-course-path__heading h3 { margin: 0; color: var(--color-text); font-size: 17px; line-height: 1.45; }
.path-course-path__heading span { display: block; margin-top: 4px; color: var(--color-text-secondary); font-size: 14px; line-height: 1.45; }
.path-course-path__heading strong { color: var(--color-accent); font-size: 18px; white-space: nowrap; }
.path-course-path .path-progress-track { margin-top: 0; }

.path-side-panel { padding: 20px; }
.path-side-panel + .path-side-panel { margin-top: 0; }

.path-subject {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 8px;
  width: 100%;
  margin-top: 18px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-control);
  background: var(--color-surface);
  padding: 14px;
  text-align: left;
  cursor: pointer;
}

.path-subject__select {
  display: block;
  min-width: 0;
  border: 0;
  background: transparent;
  padding: 0;
  color: inherit;
  text-align: left;
  cursor: pointer;
}

.path-subject:hover,
.path-subject--active { border-color: var(--color-accent); background: var(--color-accent-soft); }
.path-subject__title { display: block; min-width: 0; overflow-wrap: anywhere; color: var(--color-text); font-size: 15px; font-weight: 650; line-height: 1.45; white-space: normal; }
.path-subject__meta { grid-column: 1; min-width: 0; overflow-wrap: anywhere; color: var(--color-text-secondary); font-size: 14px; line-height: 1.45; white-space: normal; }
.path-subject__track { grid-column: 1 / -1; height: 6px; }
.path-subject__actions { display: flex; grid-column: 1 / -1; flex-wrap: wrap; gap: 6px; }
.path-subject__action { min-height: 30px; border: 1px solid var(--color-border-strong); border-radius: var(--radius-control); background: var(--color-surface); padding: 0 8px; color: var(--color-text-secondary); font-size: 14px; cursor: pointer; }
.path-subject__action:hover { border-color: var(--color-accent); color: var(--color-accent); background: var(--color-accent-soft); }

.path-budget { display: grid; gap: 4px; margin: 18px 0; }
.path-budget strong { color: var(--color-text); font-size: 24px; }
.path-budget span { color: var(--color-text-muted); font-size: 14px; }

.path-secondary-action,
.path-primary-action { width: 100%; border: 1px solid var(--color-border-strong); background: var(--color-surface); color: var(--color-accent); }
.path-primary-action { width: auto; border-color: var(--color-accent); background: var(--color-accent); color: #fff; }
.path-primary-action:hover { background: #24495a; }

.path-empty-state {
  display: grid;
  justify-items: center;
  gap: 10px;
  margin-top: 24px;
  border: 1px dashed var(--color-border-strong);
  border-radius: var(--radius-panel);
  padding: 54px 24px;
  color: var(--color-accent);
  text-align: center;
}

.path-empty-state h2 { margin: 0; color: var(--color-text); font-size: 20px; }
.path-empty-state p { max-width: 520px; margin: 0 0 8px; color: var(--color-text-secondary); font-size: 15px; }

.path-advanced-section { margin-top: 24px; padding: 0 24px; }
.path-advanced-toggle { display: flex; width: 100%; align-items: center; justify-content: space-between; gap: 12px; min-height: 60px; border: 0; background: transparent; color: var(--color-text); font-size: 16px; font-weight: 680; cursor: pointer; }
.path-advanced-toggle span { display: inline-flex; align-items: center; gap: 8px; }
.path-advanced-toggle svg { color: var(--color-accent); transition: transform 160ms ease; }
.path-advanced-toggle__open { transform: rotate(90deg); }
.path-advanced-section > p { margin: -8px 0 18px; color: var(--color-text-muted); font-size: 14px; }
.path-advanced-content { display: grid; gap: 20px; border-top: 1px solid var(--color-border); padding: 20px 0 24px; }

.generation-panel {
  display: grid;
  gap: 18px;
}

.generation-panel__status {
  color: var(--color-accent);
  font-size: 14px;
  font-weight: 700;
}

.generation-panel__intro,
.generation-panel__note,
.generation-panel__empty,
.generation-panel__blocker,
.generation-panel__feedback {
  margin: 0;
  color: var(--color-text-secondary);
  font-size: 14px;
  line-height: 1.55;
}

.generation-task-picker {
  display: grid;
  gap: 8px;
}

.generation-task-picker__item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  min-width: 0;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-control);
  background: var(--color-surface);
  padding: 14px 16px;
  color: var(--color-text);
  text-align: left;
  cursor: pointer;
}

.generation-task-picker__item:hover,
.generation-task-picker__item--selected {
  border-color: var(--color-accent);
  background: var(--color-accent-soft);
}

.generation-task-picker__item > span {
  display: grid;
  min-width: 0;
  gap: 4px;
}

.generation-task-picker__item strong {
  overflow: hidden;
  font-size: 15px;
  font-weight: 700;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.generation-task-picker__item .path-supporting-text {
  color: var(--color-text-secondary);
  font-size: 14px;
}

.generation-task-picker__item > svg { flex: 0 0 auto; color: var(--color-accent); }

.generation-panel__selected {
  display: grid;
  gap: 12px;
  border-top: 1px solid var(--color-border);
  padding-top: 18px;
}

.generation-panel__selected-copy {
  display: grid;
  gap: 4px;
}

.generation-panel__selected-copy strong { color: var(--color-text); font-size: 17px; }
.generation-panel__selected-copy span { color: var(--color-text-secondary); font-size: 14px; line-height: 1.5; }

.generation-panel__context {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 18px;
  color: var(--color-text-secondary);
  font-size: 14px;
}

.generation-panel__feedback { color: var(--color-accent); }
.generation-panel__feedback--error { color: var(--color-danger); }
.generation-panel__blocker { color: var(--color-danger); }
.generation-panel__generate { justify-self: start; min-width: 220px; }

.generation-progress {
  display: grid;
  gap: 14px;
  border-top: 1px solid var(--color-border);
  padding-top: 18px;
}

.generation-progress__heading {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  color: var(--color-text-secondary);
  font-size: 14px;
}

.generation-progress__heading strong { color: var(--color-accent); font-size: 16px; }
.generation-progress__track { overflow: hidden; height: 8px; border-radius: 4px; background: var(--color-surface-muted); }
.generation-progress__track span { display: block; height: 100%; background: var(--color-accent); }

.generation-resource-list {
  display: grid;
  gap: 1px;
  overflow: hidden;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-control);
  background: var(--color-border);
}

.generation-resource-item {
  display: grid;
  grid-template-columns: 24px minmax(0, 1fr) auto;
  align-items: center;
  gap: 12px;
  min-width: 0;
  background: var(--color-surface);
  padding: 13px 14px;
}

.generation-resource-item__icon { display: grid; place-items: center; color: var(--color-accent); }
.generation-resource-item__body { display: grid; min-width: 0; gap: 3px; }
.generation-resource-item__body strong { color: var(--color-text); font-size: 14px; }
.generation-resource-item__body span,
.generation-resource-item__body .path-supporting-text { color: var(--color-text-secondary); font-size: 14px; line-height: 1.45; }
.generation-resource-item__body .path-supporting-text { color: var(--color-danger); }
.path-supporting-text { display: block; min-width: 0; color: var(--color-text-secondary); font-size: 14px; line-height: 1.5; overflow-wrap: anywhere; }

.generation-resource-item__action,
.generation-panel__recover {
  min-height: 34px;
  border: 1px solid var(--color-border-strong);
  border-radius: var(--radius-control);
  background: var(--color-surface);
  padding: 0 10px;
  color: var(--color-accent);
  font-size: 14px;
  font-weight: 700;
  cursor: pointer;
}

.generation-resource-item__action:hover,
.generation-panel__recover:hover { border-color: var(--color-accent); background: var(--color-accent-soft); }
.generation-resource-item__action:disabled,
.generation-panel__recover:disabled { cursor: wait; opacity: .6; }
.generation-panel__recover { display: inline-flex; align-items: center; justify-content: center; gap: 6px; justify-self: start; }
.generation-spin { animation: path-spin 760ms linear infinite; }

@media (max-width: 720px) {
  .path-current-day-summary { grid-template-columns: 1fr; }
  .generation-resource-item { grid-template-columns: 24px minmax(0, 1fr); }
  .generation-resource-item__action { grid-column: 2; justify-self: start; }
  .generation-progress__heading { align-items: flex-start; flex-direction: column; gap: 4px; }
}

@keyframes path-spin { to { transform: rotate(360deg); } }

.swarm-terminal {
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.06);
}

.semantic-graph {
  min-height: 16rem;
  background: var(--color-surface-subtle);
}

.semantic-legend {
  box-shadow: 0 1px 0 rgba(15, 23, 42, 0.03);
}

.semantic-arranging-badge {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  border-radius: 999px;
  background: var(--color-accent-soft);
  color: var(--color-accent);
  padding: 3px 7px;
  font-size: 14px;
  font-weight: 700;
}

.semantic-arranging-spinner {
  width: 8px;
  height: 8px;
  border: 1px solid rgba(49, 91, 109, 0.22);
  border-top-color: var(--color-accent);
  border-radius: 999px;
  animation: semantic-spin 700ms linear infinite;
}

.semantic-live-dot {
  width: 7px;
  height: 7px;
  border-radius: 999px;
  background: var(--color-accent);
  box-shadow: 0 0 0 4px rgba(49, 91, 109, 0.12);
}

.semantic-focus-ripple {
  position: absolute;
  left: 50%;
  top: 50%;
  z-index: 1;
  width: 70px;
  height: 70px;
  pointer-events: none;
  transform: translate(-50%, -50%);
  border: 1px solid rgba(49, 91, 109, 0.24);
  border-radius: 999px;
  animation: semantic-ripple 2.4s ease-out infinite;
}

.semantic-panel {
  min-width: 0;
}

.terminal-line {
  opacity: 0;
  transform: translateY(4px);
  animation: terminal-enter 360ms ease forwards;
}

@keyframes terminal-enter {
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

@keyframes semantic-ripple {
  0% {
    opacity: 0.6;
    transform: translate(-50%, -50%) scale(0.7);
  }
  75%, 100% {
    opacity: 0;
    transform: translate(-50%, -50%) scale(2.1);
  }
}

@keyframes semantic-spin {
  to {
    transform: rotate(360deg);
  }
}

@media (prefers-reduced-motion: reduce) {
  .semantic-focus-ripple,
  .semantic-live-dot {
    animation: none;
  }
}
</style>
