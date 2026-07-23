<script setup>
import { ref, onMounted, computed, nextTick, watch, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { getLearningPath, getRecommendations } from '../api'
import { echarts } from '../lib/echarts-graph'
import {
  BookOpen, BrainCircuit, Target, TrendingUp, ChevronRight,
  ArrowRight, AlertTriangle, CheckCircle2, Layers, Sparkles,
  Clock, Zap, ChevronLeft, Play, Activity, Unlock, RefreshCw, Search,
  Maximize2, Minimize2, Move
} from '@lucide/vue'
import VideoRenderPanel from '../components/VideoRenderPanel.vue'

const route = useRoute()
const router = useRouter()
const studentId = ref(route.query.student_id || localStorage.getItem('edumatrix_student_id') || 'demo-student')
const pathData = ref(null)
const recommendations = ref([])
const loading = ref(true)
const error = ref('')
const showAll = ref(false)
const isTeacher = computed(() => localStorage.getItem('edumatrix_role') === 'teacher')
const regenerating = ref(false)
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

const totalSteps = computed(() => learningChain.value.length)
const masteredCount = computed(() => learningChain.value.filter(n => n.mastered).length)

const displayChain = computed(() => {
  if (showAll.value) return learningChain.value
  return learningChain.value.slice(0, 15)
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

function goAnalysis() {
  router.push({ path: '/student-analysis', query: { student_id: studentId.value } })
}

function playVideo(url, concept = '') {
  videoPanelUrl.value = url
  videoPanelConcept.value = concept
  showVideoPanel.value = true
}

async function loadData() {
  loading.value = true
  error.value = ''
  try {
    const [path, recs] = await Promise.all([
      getLearningPath(studentId.value),
      getRecommendations(studentId.value).catch(() => []),
    ])
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
    error.value = e.response?.data?.detail || e.message || '加载失败'
  } finally {
    loading.value = false
    regenerating.value = false
    await nextTick()
    renderSemanticGraph()
  }
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
  const palette = ['#0f766e', '#2563eb', '#d97706', '#be123c', '#475569', '#7c3aed']
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
        color: isFocus ? '#111827' : colorByCategory.get(domain),
        opacity: isFocus || isDirect ? 1 : 0.68,
        borderColor: '#ffffff',
        borderWidth: isFocus ? 4 : 2,
        shadowBlur: isFocus ? 22 : isDirect ? 10 : 3,
        shadowColor: isFocus ? 'rgba(15, 118, 110, .45)' : 'rgba(15, 23, 42, .16)',
      },
      label: {
        show: isFocus || isDirect || routeSet.has(name),
        fontSize: isFocus ? 12 : 9,
        fontWeight: isFocus || score >= 0.75 ? 700 : 500,
        color: isFocus ? '#111827' : '#334155',
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
        color: touchesFocus ? (score >= 0.75 ? '#0f766e' : '#0891b2') : '#94a3b8',
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
      backgroundColor: 'rgba(15, 23, 42, 0.95)',
      borderWidth: 1,
      borderColor: 'rgba(51, 65, 85, 0.5)',
      textStyle: { color: '#f8fafc', fontSize: 10, fontFamily: 'system-ui, sans-serif' },
      padding: [8, 12],
      borderRadius: 10,
      shadowBlur: 10,
      shadowColor: 'rgba(0, 0, 0, 0.5)',
      formatter: params => {
        if (params.dataType === 'edge') {
          return `<div style="display:flex; flex-direction:column; gap:2px;">
            <span style="font-size:10px; color:#94a3b8;">知识关联</span>
            <span style="font-weight:600;">${params.data.source} → ${params.data.target}</span>
            <span style="font-size:10px; color:#5eead4; margin-top:2px;">点击节点查看关联证据</span>
          </div>`
        }
        const stateColor = params.value >= 60 ? '#10b981' : (params.value >= 30 ? '#f59e0b' : '#ef4444')
        return `<div style="display:flex; flex-direction:column; gap:4px;">
          <div style="display:flex; align-items:center; gap:6px;">
            <span style="display:inline-block; width:8px; height:8px; border-radius:50%; background:${stateColor};"></span>
            <span style="font-weight:700; color:#e2e8f0;">${params.name}</span>
          </div>
          <span style="font-size:10px; color:#94a3b8;">${params.data.domain} · 掌握度 <b style="color:#5eead4;">${params.value}%</b></span>
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
          color: '#0f766e',
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
  <div v-if="loading" class="flex items-center justify-center h-64">
    <div class="animate-spin w-5 h-5 border-2 border-purple-500 border-t-transparent rounded-full" />
  </div>
  <div v-else-if="error" class="text-center py-12 text-red-500 text-sm">{{ error }}</div>
  <div v-else class="max-w-4xl mx-auto space-y-6">

    <!-- Header -->
    <div class="flex items-center justify-between">
      <div class="flex items-center gap-3">
        <button 
          v-if="isTeacher"
          class="px-2.5 py-1.5 text-xs font-semibold rounded-lg bg-gray-100 text-gray-700 hover:bg-gray-200 transition-all flex items-center gap-1 shrink-0"
          @click="router.push('/teacher/students')"
        >
          <ChevronLeft :size="12" /> 返回学生列表
        </button>
        <div>
          <h1 class="text-lg font-bold text-gray-800">学习路径</h1>
          <p class="text-xs text-gray-400 mt-0.5">按前置依赖链条推进 · 逐关解锁</p>
        </div>
      </div>
      <div class="text-right">
        <p class="text-lg font-bold text-emerald-600">{{ masteredCount }}/{{ totalSteps }}</p>
        <p class="text-[10px] text-gray-400">已完成</p>
      </div>
    </div>

    <!-- Progress summary -->
    <div class="grid grid-cols-2 sm:grid-cols-4 gap-2">
      <div class="bg-white rounded-xl border border-gray-100 shadow-sm p-3 text-center">
        <p class="text-[9px] text-gray-500">已完成</p>
        <p class="text-lg font-bold text-emerald-600 mt-0.5">{{ progress.mastered || 0 }}</p>
      </div>
      <div class="bg-white rounded-xl border border-gray-100 shadow-sm p-3 text-center">
        <p class="text-[9px] text-gray-500">进行中</p>
        <p class="text-lg font-bold text-blue-600 mt-0.5">{{ progress.in_progress || 0 }}</p>
      </div>
      <div class="bg-white rounded-xl border border-gray-100 shadow-sm p-3 text-center">
        <p class="text-[9px] text-gray-500">未解锁</p>
        <p class="text-lg font-bold text-gray-400 mt-0.5">{{ progress.locked || 0 }}</p>
      </div>
      <div class="bg-white rounded-xl border border-gray-100 shadow-sm p-3 text-center">
        <p class="text-[9px] text-gray-500">总概念</p>
        <p class="text-lg font-bold text-gray-700 mt-0.5">{{ progress.total_concepts || 0 }}</p>
      </div>
    </div>

    <!-- Adaptive A* route -->
    <div v-if="routeNodes.length" class="bg-white rounded-2xl border border-indigo-100 shadow-sm p-5">
      <div class="flex flex-col md:flex-row md:items-start md:justify-between gap-3 mb-4">
        <div>
          <h2 class="text-sm font-semibold text-gray-800 flex items-center gap-2">
            <BrainCircuit :size="15" class="text-indigo-500" /> A* 动态推荐路线
          </h2>
          <p class="text-[10px] text-gray-400 mt-1">根据微概念图谱、掌握缺口、认知负荷和情绪阻力生成</p>
        </div>
        <div class="flex flex-col items-stretch gap-2 shrink-0">
          <button
            type="button"
            class="self-end inline-flex items-center gap-1.5 rounded-lg border border-indigo-100 bg-white px-3 py-1.5 text-[10px] font-semibold text-indigo-700 hover:bg-indigo-50 disabled:opacity-60 transition-colors"
            :disabled="regenerating"
            @click="regeneratePath"
          >
            <RefreshCw :size="12" :class="regenerating ? 'animate-spin' : ''" />
            {{ regenerating ? '生成中' : '重新生成路线' }}
          </button>
          <div class="grid grid-cols-2 sm:grid-cols-4 gap-2 text-center">
            <div class="px-3 py-2 rounded-xl bg-indigo-50 border border-indigo-100">
              <p class="text-[9px] text-indigo-500">本阶段</p>
              <p class="text-xs font-bold text-indigo-700 truncate max-w-[90px]">{{ routeStageTarget }}</p>
            </div>
            <div class="px-3 py-2 rounded-xl bg-violet-50 border border-violet-100">
              <p class="text-[9px] text-violet-500">最终目标</p>
              <p class="text-xs font-bold text-violet-700 truncate max-w-[90px]">{{ routeFinalTarget }}</p>
            </div>
            <div class="px-3 py-2 rounded-xl bg-slate-50 border border-slate-100">
              <p class="text-[9px] text-slate-500">今日建议</p>
              <p class="text-xs font-bold text-slate-700">{{ formatMinutes(visibleEstimatedMinutes) }}</p>
            </div>
            <div class="px-3 py-2 rounded-xl bg-emerald-50 border border-emerald-100">
              <p class="text-[9px] text-emerald-500">置信度</p>
              <p class="text-xs font-bold text-emerald-700">{{ routeConfidence }}%</p>
            </div>
          </div>
        </div>
      </div>

      <div class="flex flex-wrap items-stretch gap-2">
        <template v-for="(node, idx) in routeNodes" :key="node.concept">
          <div
            class="min-w-[118px] flex-1 rounded-xl border px-3 py-3 text-left transition-all duration-300"
            :class="node.concept === activeLearningTarget 
              ? 'border-amber-400/80 bg-amber-500/5 shadow-[0_0_15px_rgba(245,158,11,0.12)] ring-2 ring-amber-400/30 ring-offset-1 scale-[1.01] animate-pulse'
              : 'border-gray-100 bg-gray-50/70 hover:border-indigo-200 hover:bg-indigo-50/50'"
            role="button"
            tabindex="0"
            @click="goLearn(node.concept)"
            @keydown.enter="goLearn(node.concept)"
          >
            <div class="flex items-center justify-between gap-2">
              <span class="w-6 h-6 rounded-full flex items-center justify-center text-[10px] font-bold shrink-0"
                :class="node.concept === activeLearningTarget ? 'bg-amber-500 text-white' : 'bg-indigo-100 text-indigo-700'">
                {{ node.step }}
              </span>
              <span v-if="node.concept === activeLearningTarget" class="text-[8px] font-extrabold px-1.5 py-0.5 rounded bg-amber-100 text-amber-800 border border-amber-200 animate-pulse">🔥 当前主攻</span>
              <span v-else class="text-[9px] px-1.5 py-0.5 rounded border" :class="routeActionColor(node.action)">{{ node.action }}</span>
            </div>
            <p class="text-xs font-semibold text-gray-800 mt-2 truncate">{{ node.concept }}</p>
            <div class="mt-2 h-1.5 bg-white rounded-full overflow-hidden">
              <div class="h-full rounded-full" :class="masteryBarColor(node.percentage)" :style="{ width: node.percentage + '%' }" />
            </div>
            <p class="text-[9px] text-gray-500 mt-1">掌握 {{ node.percentage }}% · 预计 {{ formatMinutes(node.estimated_minutes) }}</p>
            <div v-if="node.resource?.has_animation" class="mt-2 flex items-center justify-between gap-2 rounded-lg bg-white/80 border border-indigo-100 px-2 py-1">
              <span class="text-[9px] text-indigo-700 truncate">{{ node.resource.video_count }} 个本地动画</span>
              <button
                type="button"
                class="text-[9px] font-semibold text-indigo-700 hover:text-indigo-900 shrink-0"
                @click.stop="playVideo(node.resource.first_video_url, node.concept)"
              >
                播放
              </button>
            </div>
          </div>
          <div v-if="idx < routeNodes.length - 1" class="hidden md:flex items-center text-indigo-300">
            <ArrowRight :size="14" />
          </div>
        </template>
      </div>

      <div class="mt-4 grid grid-cols-1 md:grid-cols-2 gap-3">
        <div class="rounded-xl bg-indigo-50/60 border border-indigo-100 p-3">
          <p class="text-[10px] font-bold text-indigo-700 mb-2">路径解释</p>
          <div class="space-y-1.5">
            <p v-for="reason in adaptiveRoute.reasons || []" :key="reason" class="text-[10px] text-indigo-700 leading-relaxed">· {{ reason }}</p>
            <p v-if="remainingRoute.length" class="text-[10px] text-indigo-700 leading-relaxed">
              · 后续承接：{{ remainingRoute.slice(0, 6).join(' → ') }}{{ remainingRoute.length > 6 ? ' …' : '' }}
            </p>
          </div>
        </div>
        <div class="rounded-xl bg-slate-50 border border-slate-100 p-3">
          <p class="text-[10px] font-bold text-slate-700 mb-2">推荐依据</p>
          <div class="grid grid-cols-2 gap-2 text-[10px] text-slate-600">
            <p>知识联系：{{ graphEdgeCount }} 条</p>
            <p>今日建议：{{ formatMinutes(visibleEstimatedMinutes) }}</p>
            <p>认知负荷：{{ Math.round((adaptiveRoute.constraints?.cognitive_load || 0) * 100) }}%</p>
            <p>目标掌握：{{ Math.round((adaptiveRoute.constraints?.mastery_threshold || 0.7) * 100) }}%</p>
            <p>动态图谱：{{ graphFusion.active_node_count || 0 }} 节点</p>
            <p>动画命中：{{ routeResourceSummary.matched_route_nodes || 0 }} 个</p>
            <p class="col-span-2">阶段总量：{{ formatMinutes(adaptiveRoute.estimated_minutes) }}</p>
          </div>
        </div>
      </div>

      <div v-if="plannerReview.personalized_guidance" class="mt-3 rounded-xl bg-violet-50/70 border border-violet-100 p-3">
        <div class="flex flex-col md:flex-row md:items-start justify-between gap-3">
          <div class="min-w-0">
            <p class="text-[10px] font-bold text-violet-700 mb-1">Planner Agent 导学寄语</p>
            <p class="text-[10px] text-violet-700 leading-relaxed">{{ plannerReview.personalized_guidance }}</p>
          </div>
          <div v-if="todayPlan.today_concepts?.length" class="shrink-0 rounded-lg bg-white/80 border border-violet-100 px-3 py-2">
            <p class="text-[9px] font-bold text-violet-600">今日切片</p>
            <p class="text-[10px] text-violet-700 mt-1">{{ todayPlan.today_concepts.join(' → ') }}</p>
          </div>
        </div>
        <div v-if="plannerReview.action_dispatch?.length" class="mt-3 flex flex-wrap gap-2">
          <span
            v-for="item in plannerReview.action_dispatch.slice(0, 6)"
            :key="`${item.concept}-${item.action}`"
            class="rounded-lg bg-white/80 border border-violet-100 px-2.5 py-1 text-[9px] text-violet-700"
          >
            {{ item.concept }} · {{ item.mode }}
          </span>
        </div>
      </div>

      <div v-if="routeResourceNodes.length" class="mt-3 rounded-xl bg-sky-50/70 border border-sky-100 p-3">
        <div class="flex items-center justify-between gap-3 mb-2">
          <p class="text-[10px] font-bold text-sky-700">资源感知规划</p>
          <span class="text-[9px] text-sky-600">本地动画数据集 {{ routeResourceSummary.animation_concept_count || 0 }} 个知识点</span>
        </div>
        <div class="flex flex-wrap gap-2">
          <button
            v-for="node in routeResourceNodes"
            :key="`resource-${node.concept}`"
            type="button"
            class="px-2.5 py-1.5 rounded-lg bg-white border border-sky-100 text-[10px] text-sky-700 hover:border-sky-300 hover:bg-sky-50 transition-colors"
            @click="playVideo(node.resource.first_video_url, node.concept)"
          >
            {{ node.concept }} · {{ node.resource.video_count }} 个动画
          </button>
        </div>
      </div>

      <Teleport to="body" :disabled="!isSemanticFullscreen">
        <div 
          v-if="crossGraph"
          :class="[
            isSemanticFullscreen 
              ? 'fixed inset-0 z-[999] bg-slate-900/40 backdrop-blur-sm flex items-center justify-center p-4 select-none' 
              : 'mt-3 w-full'
          ]"
          @click.self="isSemanticFullscreen ? toggleSemanticFullscreen() : null"
        >
          <section
            :class="[
              'semantic-panel border transition-all duration-300 relative flex flex-col bg-white border-slate-200 overflow-hidden',
              isSemanticFullscreen 
                ? 'w-[94vw] max-w-6xl h-[88vh] shadow-2xl rounded-lg'
                : 'rounded-lg shadow-sm'
            ]"
          >
            <div class="flex flex-col md:flex-row md:items-center justify-between gap-3 border-b border-slate-100 px-4 py-3">
              <div>
                <div class="flex items-center gap-2">
                  <span class="semantic-live-dot" aria-hidden="true" />
                  <p class="text-xs font-bold text-slate-800">语义相关性图谱</p>
                  <span class="rounded bg-teal-50 px-1.5 py-0.5 text-[9px] font-semibold text-teal-700">聚焦模式</span>
                  <span v-if="isSemanticArranging" class="semantic-arranging-badge" aria-live="polite">
                    <span class="semantic-arranging-spinner" /> 正在整理
                  </span>
                </div>
                <p class="text-[10px] text-slate-400 mt-1">中心为当前概念，距离和连线强度表示知识相关性</p>
              </div>
              <div class="flex flex-wrap items-center gap-2">
                <label class="flex h-8 items-center gap-1.5 rounded-md border border-slate-200 bg-slate-50 px-2 focus-within:border-teal-500 focus-within:bg-white">
                  <Search :size="13" class="text-slate-400" />
                  <input
                    v-model="semanticQuery"
                    class="w-32 bg-transparent text-[11px] text-slate-700 outline-none"
                    placeholder="搜索并聚焦概念"
                  />
                </label>
                <button
                  type="button"
                  class="h-8 rounded-md border border-slate-200 px-2.5 text-[10px] font-semibold text-slate-600 hover:bg-slate-50 transition-colors"
                  @click="showSimilarityLog = !showSimilarityLog"
                >
                  {{ showSimilarityLog ? '收起全部' : '查看全部关系' }}
                </button>
                <button
                  type="button"
                  class="flex h-8 w-8 items-center justify-center rounded-md border border-slate-200 text-slate-600 hover:bg-slate-50 transition-colors"
                  title="重置节点布局"
                  aria-label="重置节点布局"
                  @click="resetSemanticLayout"
                >
                  <RefreshCw :size="14" />
                </button>
                <button
                  type="button"
                  class="flex h-8 w-8 items-center justify-center rounded-md border border-slate-200 text-slate-600 hover:bg-slate-50 transition-colors"
                  :title="isSemanticFullscreen ? '退出全屏' : '全屏探索'"
                  :aria-label="isSemanticFullscreen ? '退出全屏' : '全屏探索'"
                  @click="toggleSemanticFullscreen"
                >
                  <Maximize2 v-if="!isSemanticFullscreen" :size="14" />
                  <Minimize2 v-else :size="14" />
                </button>
              </div>
            </div>
            <div class="grid min-h-0 flex-1 grid-cols-1 md:grid-cols-[minmax(0,1fr)_240px]">
              <div class="relative flex min-h-0 flex-col border-b border-slate-100 md:border-b-0 md:border-r">
                <div class="semantic-legend flex flex-wrap items-center gap-x-4 gap-y-1 border-b border-slate-100 bg-white px-3 py-2 text-[9px] text-slate-500">
                  <span class="flex items-center gap-1.5"><i class="h-2 w-2 rounded-full bg-slate-900" />当前焦点</span>
                  <span class="flex items-center gap-1.5"><i class="h-[3px] w-5 rounded bg-teal-600" />强关联</span>
                  <span class="flex items-center gap-1.5"><i class="h-0 w-5 border-t border-dashed border-slate-400" />补充关系</span>
                  <span class="ml-auto hidden items-center gap-1 text-slate-400 sm:flex"><Move :size="11" />拖动节点整理布局</span>
                </div>
                <div class="semantic-chart-stage relative min-h-0 flex-1">
                  <div class="semantic-focus-ripple" aria-hidden="true" />
                  <div
                    ref="semanticChartRef"
                    class="semantic-graph w-full"
                    :class="isSemanticFullscreen ? 'h-full min-h-[520px]' : 'h-[380px]'"
                  />
                </div>
              </div>
              <aside class="min-h-0 bg-slate-50/70 p-3 md:overflow-y-auto">
                <div class="border-b border-slate-200 pb-3">
                  <p class="text-[9px] font-semibold text-slate-400">当前分析概念</p>
                  <p class="mt-1 truncate text-sm font-bold text-slate-900">{{ semanticFocusConcept }}</p>
                  <p class="mt-1 text-[9px] leading-relaxed text-slate-500">点击任意节点可重新聚焦，图谱位置保持稳定。</p>
                </div>
                <div class="mt-3 flex items-center justify-between">
                  <p class="text-[10px] font-bold text-slate-700">关联概念</p>
                  <span class="text-[9px] text-slate-400">关联证据</span>
                </div>
                <div v-if="semanticMatches.length" class="mt-2 space-y-3">
                  <button
                    v-for="item in semanticMatches"
                    :key="`match-${item.concept}`"
                    type="button"
                    class="block w-full text-left"
                    @click="selectedSemanticConcept = item.concept; semanticQuery = item.concept"
                  >
                    <span class="flex items-center justify-between gap-2">
                      <span class="truncate text-[10px] font-semibold text-slate-700">{{ item.concept }}</span>
                    </span>
                    <span class="mt-1 line-clamp-2 block text-[9px] leading-relaxed text-slate-400">{{ item.evidence }}</span>
                  </button>
                </div>
                <p v-else class="mt-3 rounded-md border border-dashed border-slate-200 p-3 text-[9px] leading-relaxed text-slate-500">
                  该概念暂无直接相似度记录，可点击图中相邻节点继续探索。
                </p>
                <div class="mt-4 border-t border-slate-200 pt-3 text-[9px] leading-relaxed text-slate-500">
                  <p><span class="font-semibold text-slate-700">实线</span> 表示当前概念的直接关联</p>
                  <p class="mt-1"><span class="font-semibold text-slate-700">虚线</span> 表示周边知识的补充关系</p>
                </div>
              </aside>
            </div>
            <div v-if="showSimilarityLog" class="max-h-[28vh] overflow-y-auto border-t border-slate-100 bg-white p-3">
              <div class="grid grid-cols-1 gap-2 md:grid-cols-2">
                <div
                  v-for="item in semanticLog"
                  :key="`${item.source}-${item.target}`"
                  class="rounded-md border border-slate-100 bg-slate-50 px-3 py-2 text-slate-600"
                >
                  <div class="flex items-center justify-between gap-2">
                    <p class="truncate text-[10px] font-semibold text-slate-700">{{ item.source }} → {{ item.target }}</p>
                  </div>
                  <p class="mt-1 text-[9px] text-slate-500">{{ item.evidence }}</p>
                </div>
              </div>
            </div>
          </section>
        </div>
      </Teleport>

      <div v-if="plannerTrace.length" class="mt-3 swarm-terminal rounded-xl border border-slate-800 bg-slate-950 p-3">
        <div class="flex items-center justify-between mb-2">
          <p class="text-[10px] font-bold text-slate-100">Swarm Terminal</p>
          <span class="text-[9px] text-emerald-300">Planner Agent 已审核</span>
        </div>
        <div class="space-y-1.5">
          <p
            v-for="(line, i) in plannerTrace"
            :key="line"
            class="terminal-line text-[10px] leading-relaxed text-emerald-100"
            :style="{ animationDelay: `${i * 120}ms` }"
          >
            {{ line }}
          </p>
        </div>
      </div>

      <div v-if="crossDomainSupports.length" class="mt-3 rounded-xl bg-amber-50/70 border border-amber-100 p-3">
        <div class="flex items-center justify-between gap-3 mb-2">
          <p class="text-[10px] font-bold text-amber-700">跨学科补强</p>
          <span class="text-[9px] text-amber-600">跨学科图谱推荐</span>
        </div>
        <div class="grid grid-cols-1 md:grid-cols-2 gap-2">
          <div v-for="item in crossDomainSupports" :key="`${item.concept}-${item.target}`" class="rounded-lg bg-white/70 border border-amber-100 px-3 py-2">
            <p class="text-xs font-semibold text-gray-800">{{ item.concept }} → {{ item.target }}</p>
            <p class="text-[9px] text-amber-700 mt-0.5">{{ item.domain_label || item.domain }}补强 · 指向 {{ item.target_domain_label || item.target_domain || '目标概念' }}</p>
            <p class="text-[9px] text-gray-500 mt-1 line-clamp-2">{{ item.reason }}</p>
          </div>
        </div>
      </div>
    </div>

    <!-- Next steps (prominent) -->
    <div v-if="nextSteps.length" class="bg-blue-50 rounded-2xl border border-blue-200 p-5">
      <h2 class="text-sm font-semibold text-blue-800 mb-3 flex items-center gap-2">
        <Unlock :size="15" /> 下一步学习推荐
      </h2>
      <p class="text-[10px] text-blue-600 mb-3">以下知识点前置依赖已满足，当前最适合学习</p>
      <div class="space-y-2">
        <div v-for="(step, i) in nextSteps" :key="step.concept"
          class="flex items-center gap-3 bg-white rounded-xl p-3 border border-blue-100 cursor-pointer hover:shadow-sm transition-all"
          @click="goLearn(step.concept)">
          <div class="w-7 h-7 rounded-full bg-blue-100 text-blue-700 flex items-center justify-center text-xs font-bold shrink-0">{{ i + 1 }}</div>
          <div class="flex-1">
            <p class="text-sm font-semibold text-gray-800">{{ step.concept }}</p>
            <p class="text-[10px] text-gray-400">Step {{ step.step }} · 前置就绪 · 当前掌握 {{ step.percentage }}%</p>
          </div>
          <span class="px-2 py-0.5 text-[9px] font-semibold rounded-lg bg-blue-100 text-blue-700">去学习 →</span>
        </div>
      </div>
    </div>

    <!-- Chain progression -->
    <div class="bg-white rounded-2xl border border-gray-100 shadow-sm p-5">
      <h2 class="text-sm font-semibold text-gray-800 mb-3 flex items-center gap-2">
        <Layers :size="15" class="text-purple-500" /> 学习链条
      </h2>
      <p class="text-[10px] text-gray-400 mb-3">按从基础到进阶的顺序逐步推进，前置概念未掌握时后续概念自动锁定</p>

      <div class="space-y-1">
        <div v-for="node in displayChain" :key="node.concept"
          class="flex items-center gap-3 py-2.5 px-3 rounded-lg transition-all"
          :class="statusColor(node.status)"
          @click="goLearn(node.concept)">

          <!-- Step number -->
          <div class="w-6 h-6 rounded-full flex items-center justify-center text-[10px] font-bold shrink-0"
            :class="node.mastered ? 'bg-emerald-200 text-emerald-700' : node.status === '当前可学' ? 'bg-blue-200 text-blue-700' : 'bg-gray-200 text-gray-400'">
            {{ node.step }}
          </div>

          <!-- Content -->
          <div class="flex-1 min-w-0">
            <div class="flex items-center gap-2">
              <span class="text-sm font-medium"
                :class="node.mastered ? 'text-gray-700' : node.status === '当前可学' ? 'text-blue-800 font-semibold' : 'text-gray-400'">
                {{ node.concept }}
              </span>
              <span class="text-[10px]">{{ statusIcon(node.status) }}</span>
              <span class="text-[9px] font-medium px-1.5 py-0.5 rounded"
                :class="{
                  'bg-emerald-50 text-emerald-600': node.bloom_level === '记忆' || node.bloom_level === '理解',
                  'bg-blue-50 text-blue-600': node.bloom_level === '应用',
                  'bg-purple-50 text-purple-600': node.bloom_level === '分析' || node.bloom_level === '评价',
                  'bg-rose-50 text-rose-600': node.bloom_level === '创造'
                }">
                {{ node.bloom_level }}
              </span>
            </div>
            <!-- Tier badge -->
            <p class="text-[9px] text-gray-400 mt-0.5">Tier {{ node.tier }} · {{ node.status }}</p>
          </div>

          <!-- Mastery bar -->
          <div class="w-20">
            <div class="h-1.5 bg-gray-100 rounded-full overflow-hidden">
              <div class="h-full rounded-full" :class="masteryBarColor(node.percentage)" :style="{ width: node.percentage + '%' }" />
            </div>
            <p class="text-[9px] font-mono text-right mt-0.5" :class="masteryColor(node.percentage)">{{ node.percentage }}%</p>
          </div>
        </div>

        <!-- Step guidance (shown for first few non-mastered steps) -->
        <div v-for="n in nextSteps.slice(0, 1)" :key="'guide-' + n.concept" class="mt-4 px-4 py-3 bg-blue-50/80 rounded-xl border border-blue-100">
          <p class="text-xs font-semibold text-blue-800 mb-1">📖 当前步骤学习引导：{{ n.concept }}</p>
          <div class="text-[10px] text-blue-700 space-y-1">
            <p>🎯 学什么：{{ n.guidance?.summary || '掌握核心概念与原理' }}</p>
            <p>💡 怎么学：{{ n.guidance?.strategy || '结合理论学习和代码实践' }}</p>
            <p>✅ 验证标准：{{ n.guidance?.verify || '能用自己的话解释核心概念' }}</p>
            <p>⏱ 预估时间：{{ n.estimated_minutes || 45 }} 分钟</p>
          </div>

          <!-- 智能资源推荐 (ZPD Matched Resources) -->
          <div v-if="!isTeacher && conceptRecommendations.length" class="mt-3 pt-2.5 border-t border-blue-100/50">
            <p class="text-[10px] font-bold text-indigo-700 flex items-center gap-1 mb-2">
              <Sparkles :size="10" /> 关联推荐学习资源：
            </p>
            <div class="grid grid-cols-1 md:grid-cols-2 gap-2">
              <div v-for="item in conceptRecommendations" :key="item.title"
                class="bg-white/80 backdrop-blur-sm rounded-xl p-2.5 border border-blue-100 hover:border-indigo-200 hover:bg-white transition-all flex flex-col justify-between">
                <div>
                  <div class="flex items-center justify-between mb-1">
                    <span class="px-1.5 py-0.2 text-[8px] font-bold rounded bg-indigo-50 text-indigo-600 border border-indigo-100/50">{{ item.badge }}</span>
                    <span class="text-[8px] text-gray-400 truncate max-w-[100px]">{{ item.source_name }}</span>
                  </div>
                  <h4 class="text-[10px] font-bold text-gray-800 truncate mb-1">{{ item.title }}</h4>
                  <p class="text-[9px] text-gray-500 line-clamp-2 leading-relaxed mb-2">{{ item.content.replace(/```python|```/g, '').trim() }}</p>
                </div>
                <button v-if="item.resource_type === 'video'"
                  @click.stop="playVideo(item.url)"
                  class="w-full py-1 bg-indigo-50 hover:bg-indigo-100 text-indigo-700 text-[9px] font-semibold rounded-lg flex items-center justify-center gap-1 transition-all border border-indigo-100/50">
                  <Play :size="9" class="fill-indigo-300" /> 播放视频
                </button>
                <button v-else-if="item.resource_type === 'code'"
                  @click.stop="goLearn(item.concept)"
                  class="w-full py-1 bg-emerald-50 hover:bg-emerald-100 text-emerald-700 text-[9px] font-semibold rounded-lg flex items-center justify-center gap-1 transition-all border border-emerald-100/50">
                  <Activity :size="9" /> 沙箱运行
                </button>
                <button v-else
                  @click.stop="goNotes(item.concept)"
                  class="w-full py-1 bg-blue-50 hover:bg-blue-100 text-blue-700 text-[9px] font-semibold rounded-lg flex items-center justify-center gap-1 transition-all border border-blue-100/50">
                  <BookOpen :size="9" /> 查看笔记
                </button>
              </div>
            </div>
          </div>

          <div v-if="!isTeacher" class="flex gap-2 mt-3">
            <button class="px-3 py-1 text-[9px] font-semibold rounded-lg bg-blue-100 text-blue-700 hover:bg-blue-200 transition-all" @click.stop="goLearn(n.concept)">开始学习</button>
            <button class="px-3 py-1 text-[9px] font-semibold rounded-lg bg-purple-100 text-purple-700 hover:bg-purple-200 transition-all" @click.stop="goQuiz(n.concept)">🎯 生成练习题</button>
            <button class="px-3 py-1 text-[9px] font-semibold rounded-lg bg-emerald-100 text-emerald-700 hover:bg-emerald-200 transition-all" @click.stop="goNotes(n.concept)">📝 查看笔记</button>
          </div>
        </div>
      </div>

      <!-- Show more / less -->
      <button v-if="learningChain.length > 15" class="w-full mt-3 py-2 text-xs font-semibold text-purple-600 hover:bg-purple-50 rounded-lg transition-all"
        @click="showAll = !showAll">
        {{ showAll ? '收起' : `展开全部 (${learningChain.length} 步)` }}
      </button>
    </div>

    <!-- Gap chains -->
    <div v-if="gapChains.length" class="bg-white rounded-2xl border border-amber-100 shadow-sm p-5">
      <h2 class="text-sm font-semibold text-amber-700 mb-3 flex items-center gap-2">
        <AlertTriangle :size="15" /> 前置依赖缺口
      </h2>
      <p class="text-[10px] text-gray-500 mb-3">以下概念因前置知识未掌握而无法学习</p>
      <div class="space-y-2">
        <div v-for="chain in gapChains" :key="chain.target" class="bg-amber-50 rounded-xl p-3">
          <p class="text-xs font-semibold text-gray-700 mb-1">目标: {{ chain.target }}</p>
          <div class="space-y-1">
            <div v-for="(gap, gi) in chain.chain" :key="gi"
              class="flex items-center gap-2 text-[10px] ml-3"
              :style="{ marginLeft: (gap.depth * 12) + 'px' }">
              <span class="text-amber-500">↳</span>
              <span class="text-gray-600">{{ gap.action }} ({{ Math.round(gap.mastery * 100) }}%)</span>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Stages overview -->
    <div class="bg-white rounded-2xl border border-gray-100 shadow-sm p-5">
      <h2 class="text-sm font-semibold text-gray-800 mb-3 flex items-center gap-2">
        <TrendingUp :size="15" class="text-emerald-500" /> 阶段总览
      </h2>
      <div class="space-y-3">
        <div v-for="(stage, i) in stages" :key="i" class="flex items-start gap-3">
          <div class="w-8 h-8 rounded-full flex items-center justify-center text-xs font-bold shrink-0"
            :class="['bg-emerald-100 text-emerald-700', 'bg-blue-100 text-blue-700', 'bg-purple-100 text-purple-700'][i]">
            {{ ['入门', '核心', '进阶'][i] }}
          </div>
          <div class="flex-1">
            <div class="flex items-center gap-2">
              <span class="text-sm font-semibold text-gray-800">{{ stage.name }}</span>
              <span class="text-[9px] text-gray-400">{{ stage.range }}</span>
            </div>
            <div class="flex flex-wrap gap-1 mt-1">
              <span v-for="c in stage.concepts.slice(0, 8)" :key="c"
                class="px-1.5 py-0.5 text-[9px] rounded bg-gray-50 text-gray-600">{{ c }}</span>
              <span v-if="stage.concepts.length > 8" class="text-[9px] text-gray-400">+{{ stage.concepts.length - 8 }}</span>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Strategy suggestions -->
    <div v-if="strategySuggestions.length" class="bg-white rounded-2xl border border-gray-100 shadow-sm p-5">
      <h2 class="text-sm font-semibold text-gray-800 mb-3 flex items-center gap-2">
        <Sparkles :size="15" class="text-purple-500" /> 学习建议
      </h2>
      <div class="space-y-2">
        <div v-for="ss in strategySuggestions" :key="ss.concept"
          class="flex items-start gap-2 p-3 rounded-lg bg-purple-50/50">
          <div class="w-5 h-5 rounded-full bg-purple-100 text-purple-700 flex items-center justify-center text-[9px] font-bold shrink-0 mt-0.5">S{{ ss.step }}</div>
          <div class="flex-1">
            <p class="text-xs font-semibold text-gray-800">{{ ss.concept }}</p>
            <div v-for="(s, si) in ss.suggestions" :key="si" class="text-[10px] text-gray-600 flex items-start gap-1 mt-0.5">
              <span class="text-purple-400">→</span>
              <span>{{ s }}</span>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Nav -->
    <div class="text-center py-2">
      <button class="px-4 py-2 text-xs font-semibold rounded-lg bg-purple-50 text-purple-700 hover:bg-purple-100 transition-all" @click="goAnalysis">
        查看完整画像分析 →
      </button>
    </div>

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
.swarm-terminal {
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.06);
}

.semantic-graph {
  min-height: 16rem;
  background-color: #fff;
  background-image:
    radial-gradient(circle at 50% 50%, rgba(13, 148, 136, 0.06), transparent 42%),
    linear-gradient(rgba(148, 163, 184, 0.09) 1px, transparent 1px),
    linear-gradient(90deg, rgba(148, 163, 184, 0.09) 1px, transparent 1px);
  background-size: auto, 28px 28px, 28px 28px;
}

.semantic-legend {
  box-shadow: 0 1px 0 rgba(15, 23, 42, 0.03);
}

.semantic-arranging-badge {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  border-radius: 999px;
  background: #fff7ed;
  color: #c2410c;
  padding: 3px 7px;
  font-size: 9px;
  font-weight: 700;
}

.semantic-arranging-spinner {
  width: 8px;
  height: 8px;
  border: 1px solid rgba(194, 65, 12, 0.28);
  border-top-color: #c2410c;
  border-radius: 999px;
  animation: semantic-spin 700ms linear infinite;
}

.semantic-live-dot {
  width: 7px;
  height: 7px;
  border-radius: 999px;
  background: #0f766e;
  box-shadow: 0 0 0 4px rgba(15, 118, 110, 0.1);
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
  border: 1px solid rgba(15, 118, 110, 0.25);
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
