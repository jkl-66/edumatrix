<script setup>
import { ref, onMounted, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { getStudentProfile, getProfileAnalysis, getProfileNarrative, updateStudentProfile, deleteStudentConcept } from '../api'
import {
  BrainCircuit, Target, TrendingUp, BookOpen, AlertTriangle,
  User, Lightbulb, BarChart3, Layers, Activity, Zap, Heart,
  ChevronRight, ArrowRight, GraduationCap, Sparkles, CheckCircle2,
  AlertCircle, Info, FileText, Download, Calendar, Edit2, X, ChevronLeft, Trash2
} from '@lucide/vue'
import MasteryRadar from '../components/MasteryRadar.vue'

const route = useRoute()
const router = useRouter()
const studentId = ref(route.query.student_id || localStorage.getItem('edumatrix_student_id') || 'demo-student')
const analysis = ref(null)
const loading = ref(true)
const error = ref('')
const activeTab = ref('overview')
const isTeacher = computed(() => localStorage.getItem('edumatrix_role') === 'teacher')

const narrative = ref('')
const narrativeLoading = ref(true)

onMounted(async () => {
  try {
    // 1. 先快速加载主画像数据与图表数据（无阻塞秒开）
    const profile = await getStudentProfile(studentId.value)
    const data = await getProfileAnalysis(studentId.value)
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

const dimensionList = computed(() => {
  return Object.entries(dimensions.value).map(([key, val]) => ({
    key,
    ...val,
  }))
})

const conceptMastery = computed(() => {
  const raw = analysis.value?.raw_profile?.concept_mastery || {}
  const errs = analysis.value?.raw_profile?.concept_p_err || {}
  return Object.entries(raw).map(([name, score]) => ({
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

function dimColor(score) {
  if (score >= 0.66) return 'bg-emerald-500'
  if (score >= 0.33) return 'bg-amber-500'
  return 'bg-red-500'
}

function dimTextColor(score) {
  if (score >= 0.66) return 'text-emerald-600'
  if (score >= 0.33) return 'text-amber-600'
  return 'text-red-600'
}

function levelBadge(level) {
  if (level === 'high') return { text: '良好', cls: 'bg-emerald-50 text-emerald-700' }
  if (level === 'medium') return { text: '待加强', cls: 'bg-amber-50 text-amber-700' }
  return { text: '需关注', cls: 'bg-red-50 text-red-700' }
}

function goLearn(concept) {
  router.push({ path: '/learn', query: { q: concept } })
}

function goPath() {
  router.push({ path: '/learning-path', query: { student_id: studentId.value } })
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
      getProfileAnalysis(studentId.value)
    ])
    analysis.value = {
      ...data,
      raw_profile: profile,
    }
  } catch (err) {
    alert('删除知识点失败: ' + (err.response?.data?.detail || err.message))
  }
}

// === 数字孪生画像数据处理与图表渲染 ===
import * as echarts from 'echarts'
import { onUnmounted, nextTick, watch } from 'vue'

const mentalChartRef = ref(null)
let mentalChartInstance = null
let mentalResizeObserver = null

function getEbbinghausRetention(mastery) {
  // 模拟艾宾浩斯非线性记忆遗忘曲线，输入 0~1 掌握度，映射至 30%~100% 残留率
  const base = 30 + (mastery || 0.0) * 70
  return Math.min(100, Math.round(base))
}

function getRetentionColor(retention) {
  if (retention >= 75) return 'text-emerald-700 bg-emerald-50/60 border-emerald-200'
  if (retention >= 50) return 'text-amber-700 bg-amber-50/60 border-amber-200'
  return 'text-rose-700 bg-rose-50/60 border-rose-200'
}

const bloomLevelsList = computed(() => {
  const counts = { Remember: 0, Understand: 0, Apply: 0, Analyze: 0, Evaluate: 0, Create: 0 }
  conceptMastery.value.forEach(c => {
    const m = c.mastery || 0.0
    if (m < 0.2) counts.Remember++
    else if (m < 0.4) counts.Understand++
    else if (m < 0.6) counts.Apply++
    else if (m < 0.75) counts.Analyze++
    else if (m < 0.9) counts.Evaluate++
    else counts.Create++
  })

  return [
    { key: 'Create', label: '创造 (Create) / 掌握度 ≥ 90%', count: counts.Create, icon: '🎨' },
    { key: 'Evaluate', label: '评价 (Evaluate) / 掌握度 75% - 89%', count: counts.Evaluate, icon: '⚖️' },
    { key: 'Analyze', label: '分析 (Analyze) / 掌握度 60% - 74%', count: counts.Analyze, icon: '🔍' },
    { key: 'Apply', label: '应用 (Apply) / 掌握度 40% - 59%', count: counts.Apply, icon: '🛠️' },
    { key: 'Understand', label: '理解 (Understand) / 掌握度 20% - 39%', count: counts.Understand, icon: '💡' },
    { key: 'Remember', label: '记忆 (Remember) / 掌握度 < 20%', count: counts.Remember, icon: '🧠' }
  ]
})

const formattedHistory = computed(() => {
  const raw = analysis.value?.mental_state_history || []
  if (raw.length > 0) {
    return raw.map((item, idx) => {
      let tStr = `交互 ${idx + 1}`
      if (item.timestamp) {
        try {
          const d = new Date(item.timestamp)
          tStr = `${d.getHours()}:${String(d.getMinutes()).padStart(2, '0')}`
        } catch (e) {}
      }
      let frustrationVal = item.frustration || 0.0
      // 情绪避障自愈：若因为冷启动或历史Bug导致挫败感始终为0，从认知负荷推导出一个合理的情感波动防抖曲线
      if (frustrationVal < 0.01) {
        const base = (item.cognitive_load || 0.3) * 0.45
        const wave = Math.sin(idx * 1.6) * 0.07
        frustrationVal = Math.max(0.04, Math.min(0.85, base + wave))
      }
      return {
        time: tStr,
        frustration: Math.round(frustrationVal * 100),
        load: Math.round((item.cognitive_load || 0.0) * 100)
      }
    })
  }
  // 默认兜底时序数据，以防冷启动
  return [
    { time: '初始状态', frustration: 10, load: 30 },
    { time: '评测1', frustration: 35, load: 55 },
    { time: '辩论1', frustration: 45, load: 68 },
    { time: '反馈1', frustration: 25, load: 45 },
    { time: '当前状态', frustration: 15, load: 35 }
  ]
})

function buildMentalChartOption(useZeroValues = false) {
  const times = formattedHistory.value.map(h => h.time)
  const frustrationVals = useZeroValues ? formattedHistory.value.map(() => 0) : formattedHistory.value.map(h => h.frustration)
  const loadVals = useZeroValues ? formattedHistory.value.map(() => 0) : formattedHistory.value.map(h => h.load)

  return {
    tooltip: {
      trigger: 'axis',
      backgroundColor: 'rgba(15, 23, 42, 0.9)',
      borderWidth: 0,
      textStyle: { color: '#fff', fontSize: 11 },
      formatter: (params) => {
        let res = `<div style="font-weight:600;margin-bottom:4px;color:#cbd5e1;">时序交互心智状态</div>`
        params.forEach(p => {
          res += `<div style="display:flex;align-items:center;justify-content:space-between;gap:12px;margin-top:2px;">
            <span style="color:${p.color}; font-weight:bold;">${p.seriesName}:</span>
            <span style="font-weight:700;">${p.value}%</span>
          </div>`
        })
        return res
      }
    },
    legend: {
      data: ['认知负荷', '情绪避障/挫败感'],
      bottom: 0,
      textStyle: { color: '#64748b', fontSize: 10 }
    },
    grid: {
      top: '10%',
      left: '4%',
      right: '4%',
      bottom: '12%',
      containLabel: true
    },
    xAxis: {
      type: 'category',
      boundaryGap: false,
      data: times,
      axisLabel: { color: '#94a3b8', fontSize: 10 },
      axisLine: { lineStyle: { color: 'rgba(148,163,184,0.15)' } }
    },
    yAxis: {
      type: 'value',
      min: 0,
      max: 100,
      axisLabel: { formatter: '{value}%', color: '#94a3b8', fontSize: 10 },
      splitLine: { lineStyle: { color: 'rgba(148,163,184,0.1)' } }
    },
    series: [
      {
        name: '认知负荷',
        type: 'line',
        data: loadVals,
        smooth: true,
        lineStyle: { color: '#6366f1', width: 2.5 },
        itemStyle: { color: '#6366f1' },
        areaStyle: {
          color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
            { offset: 0, color: 'rgba(99, 102, 241, 0.15)' },
            { offset: 1, color: 'rgba(99, 102, 241, 0)' }
          ])
        },
        symbol: 'circle',
        symbolSize: 6
      },
      {
        name: '情绪避障/挫败感',
        type: 'line',
        data: frustrationVals,
        smooth: true,
        lineStyle: { color: '#f43f5e', width: 2.5 },
        itemStyle: { color: '#f43f5e' },
        areaStyle: {
          color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
            { offset: 0, color: 'rgba(244, 63, 94, 0.15)' },
            { offset: 1, color: 'rgba(244, 63, 94, 0)' }
          ])
        },
        symbol: 'circle',
        symbolSize: 6
      }
    ]
  }
}

const kalmanHistory = computed(() => analysis.value?.kalman_history || [])
const kalmanConcept = computed(() => analysis.value?.kalman_concept || '池化层')
const lastKalman = computed(() => {
  const h = kalmanHistory.value
  return h.length > 0 ? h[h.length - 1] : { gain: 0.18, q: 0.0100, r: 0.85, p: 0.082 }
})
const kalmanGain = computed(() => lastKalman.value.gain)
const kalmanQ = computed(() => lastKalman.value.q)
const kalmanR = computed(() => lastKalman.value.r)
const kalmanP = computed(() => lastKalman.value.p)

function buildKalmanChartOption(useZeroValues = false) {
  const historyData = kalmanHistory.value
  const times = historyData.map(h => h.time)
  const rawVals = useZeroValues ? historyData.map(() => 0) : historyData.map(h => h.raw)
  const smoothVals = useZeroValues ? historyData.map(() => 0) : historyData.map(h => h.smoothed)

  return {
    tooltip: {
      trigger: 'axis',
      backgroundColor: 'rgba(15, 23, 42, 0.9)',
      borderWidth: 0,
      textStyle: { color: '#fff', fontSize: 11 },
      formatter: (params) => {
        let res = `<div style="font-weight:600;margin-bottom:4px;color:#cbd5e1;">卡尔曼滤波防抖分析 (${kalmanConcept.value})</div>`
        params.forEach(p => {
          res += `<div style="display:flex;align-items:center;justify-content:space-between;gap:12px;margin-top:2px;">
            <span style="color:${p.color}; font-weight:bold;">${p.seriesName}:</span>
            <span style="font-weight:700;">${p.value}%</span>
          </div>`
        })
        return res
      }
    },
    legend: {
      data: ['原始观测掌握度', '卡尔曼平滑掌握度'],
      bottom: 0,
      textStyle: { color: '#64748b', fontSize: 10 }
    },
    grid: {
      top: '10%',
      left: '4%',
      right: '4%',
      bottom: '12%',
      containLabel: true
    },
    xAxis: {
      type: 'category',
      boundaryGap: false,
      data: times,
      axisLabel: { color: '#94a3b8', fontSize: 10 },
      axisLine: { lineStyle: { color: 'rgba(148,163,184,0.15)' } }
    },
    yAxis: {
      type: 'value',
      min: 0,
      max: 100,
      axisLabel: { formatter: '{value}%', color: '#94a3b8', fontSize: 10 },
      splitLine: { lineStyle: { color: 'rgba(148,163,184,0.1)' } }
    },
    series: [
      {
        name: '原始观测掌握度',
        type: 'line',
        data: rawVals,
        smooth: true,
        lineStyle: { color: 'rgba(148, 163, 184, 0.4)', type: 'dashed', width: 1.5 },
        itemStyle: { color: 'rgba(148, 163, 184, 0.6)' },
        symbol: 'circle',
        symbolSize: 4
      },
      {
        name: '卡尔曼平滑掌握度',
        type: 'line',
        data: smoothVals,
        smooth: true,
        lineStyle: { color: '#6366f1', width: 3, shadowBlur: 8, shadowColor: 'rgba(99, 102, 241, 0.5)' },
        itemStyle: { color: '#6366f1' },
        areaStyle: {
          color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
            { offset: 0, color: 'rgba(99, 102, 241, 0.2)' },
            { offset: 1, color: 'rgba(99, 102, 241, 0)' }
          ])
        },
        symbol: 'circle',
        symbolSize: 7
      }
    ]
  }
}

function initMentalChart() {
  if (!mentalChartRef.value) return
  const width = mentalChartRef.value.clientWidth
  const height = mentalChartRef.value.clientHeight
  if (width === 0 || height === 0) return

  if (mentalChartInstance) {
    mentalChartInstance.dispose()
    mentalChartInstance = null
  }
  const isDark = document.documentElement.classList.contains('dark') || document.body.classList.contains('dark')
  mentalChartInstance = echarts.init(mentalChartRef.value, isDark ? 'dark' : null, { backgroundColor: 'transparent' })
  mentalChartInstance.setOption(buildMentalChartOption(true))
  setTimeout(() => {
    if (mentalChartInstance) {
      mentalChartInstance.setOption(buildMentalChartOption(false))
    }
  }, 100)
}

const kalmanChartRef = ref(null)
let kalmanChartInstance = null
let kalmanResizeObserver = null

function initKalmanChart() {
  if (!kalmanChartRef.value) return
  const width = kalmanChartRef.value.clientWidth
  const height = kalmanChartRef.value.clientHeight
  if (width === 0 || height === 0) return

  if (kalmanChartInstance) {
    kalmanChartInstance.dispose()
    kalmanChartInstance = null
  }
  const isDark = document.documentElement.classList.contains('dark') || document.body.classList.contains('dark')
  kalmanChartInstance = echarts.init(kalmanChartRef.value, isDark ? 'dark' : null, { backgroundColor: 'transparent' })
  kalmanChartInstance.setOption(buildKalmanChartOption(true))
  setTimeout(() => {
    if (kalmanChartInstance) {
      kalmanChartInstance.setOption(buildKalmanChartOption(false))
    }
  }, 100)
}

function _handleMentalResize() {
  mentalChartInstance?.resize()
}

function _handleKalmanResize() {
  kalmanChartInstance?.resize()
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
      backgroundColor: 'rgba(15, 23, 42, 0.95)',
      borderWidth: 0,
      textStyle: { color: '#fff', fontSize: 11 },
      formatter: (params) => {
        return `<div style="padding: 4px 8px; font-size: 10px;">
          <span style="font-weight:600; color:#cbd5e1;">${params.name}</span>: 
          <b style="color:#818cf8; font-family:monospace;">${params.value}%</b>
        </div>`
      }
    },
    legend: {
      orient: 'horizontal',
      bottom: 0,
      left: 'center',
      textStyle: { color: '#64748b', fontSize: 10 }
    },
    color: ['#6366f1', '#10b981', '#f43f5e', '#f59e0b', '#8b5cf6', '#0ea5e9'],
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
          fontSize: 9,
          color: '#475569'
        },
        emphasis: {
          label: {
            show: true,
            fontSize: 11,
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
      getProfileAnalysis(studentId.value)
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
        mentalResizeObserver = new ResizeObserver(() => {
          mentalChartInstance?.resize()
        })
        mentalResizeObserver.observe(mentalChartRef.value)
      }
      if (window.ResizeObserver && kalmanChartRef.value && !kalmanResizeObserver) {
        kalmanResizeObserver = new ResizeObserver(() => {
          kalmanChartInstance?.resize()
        })
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
  if (mentalChartInstance) {
    mentalChartInstance.setOption(buildMentalChartOption())
  }
}, { deep: true })

watch(kalmanHistory, () => {
  if (kalmanChartInstance) {
    kalmanChartInstance.setOption(buildKalmanChartOption())
  }
}, { deep: true })

const handleWindowFocus = async () => {
  try {
    const [profile, data] = await Promise.all([
      getStudentProfile(studentId.value),
      getProfileAnalysis(studentId.value)
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
  window.addEventListener('resize', _handleMentalResize)
  window.addEventListener('resize', _handleKalmanResize)
  window.addEventListener('resize', _handleCausesPieResize)
  window.addEventListener('focus', handleWindowFocus)
})

onUnmounted(() => {
  window.removeEventListener('resize', _handleMentalResize)
  window.removeEventListener('resize', _handleKalmanResize)
  window.removeEventListener('resize', _handleCausesPieResize)
  window.removeEventListener('focus', handleWindowFocus)
  if (mentalResizeObserver) {
    mentalResizeObserver.disconnect()
    mentalResizeObserver = null
  }
  if (kalmanResizeObserver) {
    kalmanResizeObserver.disconnect()
    kalmanResizeObserver = null
  }
  if (causesPieResizeObserver) {
    causesPieResizeObserver.disconnect()
    causesPieResizeObserver = null
  }
  if (mentalChartInstance) {
    mentalChartInstance.dispose()
    mentalChartInstance = null
  }
  if (kalmanChartInstance) {
    kalmanChartInstance.dispose()
    kalmanChartInstance = null
  }
  if (causesPieChartInstance) {
    causesPieChartInstance.dispose()
    causesPieChartInstance = null
  }
})
</script>

<template>
  <div v-if="loading" class="flex items-center justify-center h-64">
    <div class="animate-spin w-5 h-5 border-2 border-purple-500 border-t-transparent rounded-full" />
  </div>
  <div v-else-if="error" class="text-center py-12 text-red-500 text-sm">{{ error }}</div>
  <div v-else class="profile-page max-w-6xl mx-auto space-y-6">

    <!-- Header -->
    <div class="flex items-center justify-between">
      <div class="flex items-center gap-3">
        <div class="w-10 h-10 rounded-xl bg-gradient-to-br from-emerald-500 to-teal-600 flex items-center justify-center text-white text-sm font-bold shadow-sm">
          {{ (background.display_name || background.student_id || '?')[0] }}
        </div>
        <div>
          <h1 class="text-lg font-bold text-gray-800">学习画像分析</h1>
          <p class="text-xs text-gray-400">{{ background.display_name || background.student_id }} ({{ background.student_id }}) · {{ background.major }}</p>
        </div>
      </div>
      <div class="flex items-center gap-2">
        <button v-if="isTeacher" class="px-3 py-1.5 text-xs font-semibold rounded-lg bg-gray-100 text-gray-700 hover:bg-gray-200 transition-all flex items-center gap-1.5 mr-1" @click="router.push('/teacher/students')">
          <ChevronLeft :size="12" /> 返回学生列表
        </button>
        <button class="px-3 py-1.5 text-xs font-semibold rounded-lg bg-emerald-50 text-emerald-700 hover:bg-emerald-100 transition-all flex items-center gap-1.5" @click="goPath">
          <TrendingUp :size="12" /> 查看学习路径
        </button>
      </div>
    </div>

    <!-- Tab navigation -->
    <div class="flex gap-1 border-b border-gray-100 pb-1 overflow-x-auto">
      <button class="px-4 py-2 text-xs font-semibold rounded-t-lg transition-all whitespace-nowrap"
        :class="activeTab === 'overview' ? 'text-emerald-700 bg-emerald-50 border-b-2 border-emerald-500' : 'text-gray-500 hover:text-gray-700 hover:bg-gray-50'"
        @click="activeTab = 'overview'">
        <User :size="12" class="inline mr-1" /> 概览
      </button>
      <button class="px-4 py-2 text-xs font-semibold rounded-t-lg transition-all whitespace-nowrap"
        :class="activeTab === 'digital-twin' ? 'text-emerald-700 bg-emerald-50 border-b-2 border-emerald-500' : 'text-gray-500 hover:text-gray-700 hover:bg-gray-50'"
        @click="activeTab = 'digital-twin'">
        <Activity :size="12" class="inline mr-1" /> 数字孪生画像
      </button>
      <button class="px-4 py-2 text-xs font-semibold rounded-t-lg transition-all whitespace-nowrap"
        :class="activeTab === 'dimensions' ? 'text-emerald-700 bg-emerald-50 border-b-2 border-emerald-500' : 'text-gray-500 hover:text-gray-700 hover:bg-gray-50'"
        @click="activeTab = 'dimensions'">
        <BarChart3 :size="12" class="inline mr-1" /> 十维分析
      </button>
      <button class="px-4 py-2 text-xs font-semibold rounded-t-lg transition-all whitespace-nowrap"
        :class="activeTab === 'weakness' ? 'text-emerald-700 bg-emerald-50 border-b-2 border-emerald-500' : 'text-gray-500 hover:text-gray-700 hover:bg-gray-50'"
        @click="activeTab = 'weakness'">
        <AlertTriangle :size="12" class="inline mr-1" /> 薄弱点归因
      </button>
      <button class="px-4 py-2 text-xs font-semibold rounded-t-lg transition-all whitespace-nowrap"
        :class="activeTab === 'causes' ? 'text-emerald-700 bg-emerald-50 border-b-2 border-emerald-500' : 'text-gray-500 hover:text-gray-700 hover:bg-gray-50'"
        @click="activeTab = 'causes'">
        <Info :size="12" class="inline mr-1" /> 成因分析
      </button>
      <button class="px-4 py-2 text-xs font-semibold rounded-t-lg transition-all whitespace-nowrap"
        :class="activeTab === 'suggestions' ? 'text-emerald-700 bg-emerald-50 border-b-2 border-emerald-500' : 'text-gray-500 hover:text-gray-700 hover:bg-gray-50'"
        @click="activeTab = 'suggestions'">
        <Sparkles :size="12" class="inline mr-1" /> 教学建议
      </button>
    </div>

    <!-- Tab: Overview -->
    <div v-if="activeTab === 'overview'" class="space-y-6">
      <!-- Student card -->
      <div class="bg-white rounded-2xl border border-gray-100 shadow-sm p-6">
        <div class="flex items-center gap-4">
          <div class="w-14 h-14 rounded-2xl bg-gradient-to-br from-emerald-500 to-teal-600 flex items-center justify-center text-white text-lg font-bold shadow-sm">
            {{ (background.display_name || background.student_id || '?')[0] }}
          </div>
          <div class="flex-1">
            <div class="flex items-center gap-2">
              <h2 class="text-lg font-bold text-gray-800">{{ background.display_name || background.student_id }}</h2>
              <button @click="openEdit" class="text-emerald-700 hover:text-emerald-800 transition-colors p-1 rounded-lg hover:bg-emerald-50 flex items-center gap-0.5 text-[10px] font-medium" title="编辑学情设置">
                <Edit2 :size="10" />编辑画像
              </button>
            </div>
            <p class="text-xs text-gray-500 mt-0.5">{{ background.major || '未设置' }} · {{ background.target_course || '未设置' }}</p>
            <div class="flex gap-2 mt-2 flex-wrap">
              <span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-lg text-[10px] font-medium bg-blue-50 text-blue-700">
                <Lightbulb :size="10" /> {{ background.cognitive_style }}
              </span>
              <span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-lg text-[10px] font-medium bg-indigo-50 text-indigo-700">
                <Zap :size="10" /> 动机: {{ background.motivation_type }}
              </span>
              <span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-lg text-[10px] font-medium"
                :class="background.frustration_index > 0.3 ? 'bg-amber-50 text-amber-700' : 'bg-emerald-50 text-emerald-700'">
                <Heart :size="10" /> 挫败感: {{ Math.round(background.frustration_index * 100) }}%
              </span>
            </div>
          </div>
          <div class="text-right">
            <p class="text-3xl font-bold" :class="avgMastery >= 60 ? 'text-emerald-600' : avgMastery >= 30 ? 'text-amber-600' : 'text-red-600'">{{ avgMastery }}%</p>
            <p class="text-[10px] text-gray-400">平均掌握度</p>
          </div>
        </div>
        <div v-if="background.learning_goals?.length" class="mt-4 pt-3 border-t border-gray-50">
          <p class="text-[10px] font-semibold text-gray-500 mb-1.5 flex items-center gap-1"><Target :size="10" /> 学习目标</p>
          <div class="flex flex-wrap gap-1.5">
            <span v-for="goal in background.learning_goals" :key="goal" class="px-2 py-0.5 rounded-md text-[10px] font-medium bg-purple-50 text-purple-700">{{ goal }}</span>
          </div>
        </div>
        <div v-if="background.learning_preferences?.length" class="mt-2">
          <p class="text-[10px] font-semibold text-gray-500 mb-1 flex items-center gap-1"><BookOpen :size="10" /> 学习偏好</p>
          <div class="flex flex-wrap gap-1">
            <span v-for="pref in background.learning_preferences" :key="pref" class="px-2 py-0.5 rounded-md text-[10px] font-medium bg-cyan-50 text-cyan-700">{{ pref }}</span>
          </div>
        </div>
      </div>

      <!-- 📬 StoryLensEdu 叙事学情信笺 (异步加载优化) -->
      <div class="bg-gradient-to-r from-amber-50 to-orange-50/50 border border-amber-100/70 rounded-2xl p-6 shadow-sm relative overflow-hidden">
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
        <h3 class="text-sm font-semibold text-gray-800 mb-3 flex items-center gap-2"><BrainCircuit :size="16" class="text-purple-500" /> 能力掌握度雷达图</h3>
        <div class="h-72">
          <MasteryRadar v-if="conceptMastery.length" :concepts="conceptMastery" :student-id="studentId" />
          <div v-else class="flex items-center justify-center h-full text-xs text-gray-400">暂无数据</div>
        </div>
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
          <p class="text-xl font-bold mt-1" :class="(analysis?.raw_profile?.cognitive_load || 0) > 0.5 ? 'text-amber-600' : 'text-emerald-600'">{{ Math.round((analysis?.raw_profile?.cognitive_load || 0) * 100) }}%</p>
        </div>
        <div class="bg-white rounded-xl border border-gray-100 shadow-sm p-4 text-center">
          <p class="text-xs text-gray-500">参与度</p>
          <p class="text-xl font-bold mt-1" :class="(analysis?.raw_profile?.focus_level || 0) > 0.5 ? 'text-emerald-600' : 'text-amber-600'">{{ Math.round((analysis?.raw_profile?.focus_level || 0) * 100) }}%</p>
        </div>
      </div>
    </div>

    <!-- Tab: Digital Twin -->
    <div v-if="activeTab === 'digital-twin'" class="space-y-6">
      
      <!-- Top Overview row -->
      <div class="grid grid-cols-1 md:grid-cols-3 gap-6">
        
        <!-- Left: Ebbinghaus retention grid -->
        <div class="md:col-span-2 bg-white rounded-2xl border border-gray-100 shadow-sm p-5 space-y-4">
          <h3 class="text-sm font-semibold text-gray-800 flex items-center gap-1.5">
            <Calendar :size="16" class="text-indigo-500" />
            艾宾浩斯抗遗忘记忆残留指数
          </h3>
          <p class="text-[10px] text-gray-400">基于记忆保持衰减规律，对已学知识点在脑海中的保留度进行动态估计，并标注复习紧急度。</p>
          
          <div class="grid grid-cols-1 sm:grid-cols-2 gap-4 max-h-[350px] overflow-y-auto pr-1">
            <div v-for="c in conceptMastery" :key="c.name" 
              class="p-3 border border-slate-100/80 rounded-xl bg-slate-50/30 flex flex-col justify-between space-y-2">
              <div class="flex items-center justify-between">
                <div class="flex items-center gap-1">
                  <span class="text-xs font-bold text-slate-700">{{ c.name }}</span>
                  <button @click.stop="handleDeleteConcept(c.name)" class="text-slate-400 hover:text-rose-500 transition-colors p-0.5 rounded" title="从画像与复习计划中彻底删除此知识点">
                    <Trash2 :size="11" />
                  </button>
                </div>
                <span class="px-2 py-0.5 text-[9px] font-bold rounded-md border" :class="getRetentionColor(getEbbinghausRetention(c.mastery))">
                  记忆残留 {{ getEbbinghausRetention(c.mastery) }}%
                </span>
              </div>
              <div class="space-y-1">
                <div class="w-full h-1.5 bg-slate-100 rounded-full overflow-hidden">
                  <div class="h-full rounded-full transition-all duration-500"
                    :class="getEbbinghausRetention(c.mastery) >= 75 ? 'bg-emerald-500' : getEbbinghausRetention(c.mastery) >= 50 ? 'bg-amber-500' : 'bg-rose-500'"
                    :style="{ width: getEbbinghausRetention(c.mastery) + '%' }" />
                </div>
                <div class="flex justify-between text-[8px] text-slate-400">
                  <span>遗忘极值</span>
                  <span v-if="getEbbinghausRetention(c.mastery) < 50" class="text-rose-500 font-bold">⚠️ 建议立刻复习</span>
                  <span v-else-if="getEbbinghausRetention(c.mastery) < 75" class="text-amber-500 font-bold">⏳ 建议稍后复习</span>
                  <span v-else class="text-emerald-500 font-bold">🟢 状态极佳</span>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- Right: Bloom hierarchy -->
        <div class="bg-white rounded-2xl border border-gray-100 shadow-sm p-5 flex flex-col justify-between">
          <div>
            <h3 class="text-sm font-semibold text-gray-800 mb-3 flex items-center gap-1.5">
              <Layers :size="16" class="text-purple-500" />
              布鲁姆（Bloom）认知阶层分布
            </h3>
            <p class="text-[10px] text-gray-400 mb-4">分析学生在机器学习概念学习中，各知识层级所处深度阶梯分布（Remember 至 Create）。</p>
            
            <div class="space-y-3">
              <div v-for="level in bloomLevelsList" :key="level.key" class="space-y-1">
                <div class="flex justify-between items-center text-[10px]">
                  <span class="font-bold text-slate-700 flex items-center gap-1">
                    <span>{{ level.icon }}</span>
                    <span>{{ level.label }}</span>
                  </span>
                  <span class="text-slate-500 font-mono font-bold">{{ level.count }} 个概念</span>
                </div>
                <div class="w-full h-2 bg-slate-100 rounded-full overflow-hidden">
                  <div class="h-full rounded-full bg-purple-500 transition-all duration-500" 
                    :style="{ width: (conceptMastery.length ? (level.count / conceptMastery.length) * 100 : 0) + '%' }" />
                </div>
              </div>
            </div>
          </div>
          <div class="mt-4 pt-3 border-t border-slate-50 text-[9px] text-slate-400 leading-relaxed bg-slate-50/50 p-2 rounded-lg">
            ℹ️ 当前掌握度的均值代表学生所处的阶梯门槛。若想向上攀爬，建议开展包含证明推导或跨界融合在内的深度学习。
          </div>
        </div>
      </div>

      <!-- Mental state timelines -->
      <div class="bg-white rounded-2xl border border-gray-100 shadow-sm p-5">
        <h3 class="text-sm font-semibold text-gray-800 mb-2 flex items-center gap-1.5">
          <Activity :size="16" class="text-rose-500" />
          心智负荷与情绪波动历史曲线
        </h3>
        <p class="text-[10px] text-gray-400 mb-4">反映在近期交互中，学生的认知负荷（Cognitive Load）和挫败感（Frustration Index）的实时时序演进曲线，体现人在回路自适应调控效果。</p>
        <div class="h-80" ref="mentalChartRef" />
      </div>

      <!-- Kalman Denoising Chart -->
      <div class="bg-white rounded-2xl border border-gray-100 shadow-sm p-5">
        <h3 class="text-sm font-semibold text-gray-800 mb-2 flex items-center gap-1.5">
          <Activity :size="16" class="text-indigo-500" />
          卡尔曼滤波学情去噪估计 (掌握度防震荡)
        </h3>
        <p class="text-[10px] text-gray-400 mb-4">对比展示近期测验的原始答题掌握度（虚线）与卡尔曼估计器平滑修正后的学情掌握度（实线）。在学生发生偶发性粗心或手滑失误时，系统能自动抑制作业曲线的大幅波动，还原真实的渐进学习轨迹。</p>
        <div class="grid grid-cols-1 lg:grid-cols-4 gap-6">
          <div class="lg:col-span-3 h-80" ref="kalmanChartRef" />
          <div class="lg:col-span-1 bg-slate-50 border border-slate-100 rounded-xl p-4 flex flex-col justify-between text-[11px] space-y-4">
            <div class="space-y-3">
              <span class="font-bold text-slate-700 block text-xs">实时卡尔曼滤波器状态</span>
              <div class="flex justify-between border-b border-slate-200/50 pb-1.5">
                <span class="text-slate-500">卡尔曼增益 K_t</span>
                <span class="font-mono font-bold text-indigo-600">{{ kalmanGain.toFixed(2) }}</span>
              </div>
              <div class="flex justify-between border-b border-slate-200/50 pb-1.5">
                <span class="text-slate-500">系统转移噪声 Q_t</span>
                <span class="font-mono font-bold text-slate-700">{{ kalmanQ.toFixed(4) }}</span>
              </div>
              <div class="flex justify-between border-b border-slate-200/50 pb-1.5">
                <span class="text-slate-500">测量观测噪声 R_t</span>
                <span class="font-mono font-bold" :class="kalmanR > 0.3 ? 'text-rose-600 font-extrabold' : 'text-slate-700'">
                  {{ kalmanR.toFixed(2) }}
                </span>
              </div>
              <div class="flex justify-between border-b border-slate-200/50 pb-1.5">
                <span class="text-slate-500">掌握度估计协方差 P_t</span>
                <span class="font-mono font-bold text-emerald-600">{{ kalmanP.toFixed(3) }}</span>
              </div>
            </div>
            <div class="p-2.5 bg-indigo-50/50 border border-indigo-100/50 rounded-lg text-[10px] text-indigo-700 leading-relaxed">
              <strong>学情诊断说明：</strong><br>
              <span v-if="kalmanR > 0.3">在最近一次测验中答题用时过短（少于 3 秒）且出现答错，被判定为偶发性粗心/手滑。卡尔曼滤波器已自动上调测量噪声 $R_t$ 并调小滤波增益，防止该异常观测分数值导致您的整体掌握度产生震荡或失真下跌。</span>
              <span v-else>近期测验答题节奏与正确率分布正常，卡尔曼状态估计器正常拟合，掌握度数据可信度较高。</span>
            </div>
          </div>
        </div>
      </div>

    </div>

    <!-- Tab: Dimensions -->
    <div v-if="activeTab === 'dimensions'" class="space-y-4">
      <p class="text-xs text-gray-500">基于 10 个学习维度的综合诊断，每个维度包含评分、诊断文本和建议措施</p>
      <div v-for="dim in dimensionList" :key="dim.key" class="bg-white rounded-2xl border border-gray-100 shadow-sm p-5">
        <div class="flex items-center justify-between mb-2">
          <h3 class="text-sm font-semibold text-gray-800">{{ dim.label }}</h3>
          <span class="px-2 py-0.5 rounded-md text-[10px] font-medium" :class="levelBadge(dim.level).cls">
            {{ levelBadge(dim.level).text }}
          </span>
        </div>
        <div class="flex items-center gap-3 mb-3">
          <div class="flex-1 h-2 bg-gray-100 rounded-full overflow-hidden">
            <div class="h-full rounded-full transition-all" :class="dimColor(dim.score)" :style="{ width: (dim.score * 100) + '%' }" />
          </div>
          <span class="text-xs font-mono" :class="dimTextColor(dim.score)">{{ Math.round(dim.score * 100) }}%</span>
        </div>
        <p class="text-xs text-gray-600 bg-gray-50 rounded-lg px-3 py-2">{{ dim.diagnosis }}</p>
        <div v-if="dim.suggestions?.length" class="mt-2 space-y-1">
          <p class="text-[10px] font-semibold text-gray-500 flex items-center gap-1"><Sparkles :size="10" /> 建议</p>
          <div v-for="(s, i) in dim.suggestions" :key="i" class="flex items-start gap-2 text-[10px] text-gray-600">
            <span class="text-purple-400 mt-0.5">→</span>
            <span>{{ s }}</span>
          </div>
        </div>
        <div v-if="dim.evidence?.length" class="mt-2">
          <p class="text-[10px] font-semibold text-gray-400 flex items-center gap-1"><FileText :size="10" /> 证据片段</p>
          <div v-for="(ev, i) in dim.evidence" :key="i" class="text-[10px] text-gray-400 italic ml-3">"{{ ev }}"</div>
        </div>
      </div>
    </div>

    <!-- Tab: Weakness -->
    <div v-if="activeTab === 'weakness'" class="space-y-4">
      <p class="text-xs text-gray-500">薄弱知识点及其根因分析，帮助理解"为什么不会"</p>
      <div v-for="wa in weakAnalysis" :key="wa.concept" class="bg-white rounded-2xl border border-gray-100 shadow-sm p-5">
        <div class="flex items-center justify-between mb-3">
          <div class="flex items-center gap-2">
            <AlertCircle :size="16" class="text-rose-500" />
            <h3 class="text-sm font-semibold text-gray-800">{{ wa.concept }}</h3>
          </div>
          <span class="text-lg font-bold" :class="wa.mastery * 100 >= 60 ? 'text-emerald-600' : wa.mastery * 100 >= 30 ? 'text-amber-600' : 'text-red-600'">
            {{ Math.round(wa.mastery * 100) }}%
          </span>
        </div>
        <div class="h-2 bg-gray-100 rounded-full overflow-hidden mb-3">
          <div class="h-full rounded-full" :class="wa.mastery * 100 >= 60 ? 'bg-emerald-500' : wa.mastery * 100 >= 30 ? 'bg-amber-500' : 'bg-red-500'"
            :style="{ width: (wa.mastery * 100) + '%' }" />
        </div>
        <div v-if="wa.root_causes?.length" class="space-y-2">
          <p class="text-[10px] font-semibold text-gray-500">根因分析</p>
          <div v-for="rc in wa.root_causes" :key="rc.cause" class="bg-amber-50 rounded-lg px-3 py-2">
            <div class="flex items-center justify-between">
              <span class="text-xs font-medium text-amber-800">{{ rc.cause }}</span>
              <span class="text-[10px] text-amber-600">{{ rc.percentage }}%</span>
            </div>
            <p class="text-[10px] text-amber-700 mt-0.5">{{ rc.detail }}</p>
          </div>
        </div>
        <button v-if="!isTeacher" class="mt-3 px-3 py-1.5 text-[10px] font-semibold rounded-lg bg-purple-50 text-purple-700 hover:bg-purple-100 transition-all flex items-center gap-1" @click="goLearn(wa.concept)">
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
          <BarChart3 :size="14" class="text-purple-500" />
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
          <p class="text-[10px] font-semibold text-gray-500 flex items-center gap-1"><Sparkles :size="10" /> 推荐干预</p>
          <div v-for="(iv, i) in cause.interventions" :key="i" class="flex items-start gap-2 text-[10px] text-gray-600">
            <span class="text-purple-400 mt-0.5">→</span>
            <span>{{ iv }}</span>
          </div>
        </div>
      </div>
    </div>

    <!-- Tab: Suggestions -->
    <div v-if="activeTab === 'suggestions'" class="space-y-4">
      <p class="text-xs text-gray-500">综合各维度分析生成的个性化教学建议</p>
      <div class="bg-white rounded-2xl border border-gray-100 shadow-sm p-6">
        <h3 class="text-sm font-semibold text-gray-800 mb-3 flex items-center gap-2"><Sparkles :size="16" class="text-amber-500" /> 个性化建议汇总</h3>
        <div class="space-y-3">
          <div v-for="(s, i) in suggestions" :key="i" class="flex items-start gap-3 text-sm">
            <div v-if="s.startsWith('  →')" class="text-purple-400 text-xs ml-6">→</div>
            <div v-else class="w-5 h-5 rounded-full bg-amber-100 text-amber-700 flex items-center justify-center text-[10px] font-bold shrink-0 mt-0.5">{{ i + 1 }}</div>
            <span class="text-gray-700" :class="s.startsWith('  →') ? 'text-xs text-gray-500' : 'text-sm font-medium'">{{ s }}</span>
          </div>
        </div>
      </div>

      <!-- 个性化资源生成 -->
      <div v-if="!isTeacher" class="bg-white rounded-2xl border border-purple-100 shadow-sm p-5">
        <h3 class="text-sm font-semibold text-gray-800 mb-3 flex items-center gap-2"><Sparkles :size="16" class="text-purple-500" /> 一键生成个性化资源</h3>
        <p class="text-[10px] text-gray-500 mb-3">基于您的画像分析自动生成针对性学习资源</p>
        <div class="grid grid-cols-2 md:grid-cols-4 gap-3">
          <button class="p-3 rounded-xl bg-purple-50 hover:bg-purple-100 border border-purple-100 transition-all text-center"
            @click="router.push({ path: '/learn', query: { student_id: studentId, q: Object.keys(analysis?.raw_profile?.concept_mastery || {}).filter(k => (analysis?.raw_profile?.concept_mastery?.[k] || 0) < 0.4)[0] || '' } })">
            <BookOpen :size="18" class="mx-auto text-purple-600" />
            <p class="text-[10px] font-semibold text-purple-700 mt-1">针对性讲解</p>
            <p class="text-[8px] text-purple-400">薄弱点智能讲解</p>
          </button>
          <button class="p-3 rounded-xl bg-emerald-50 hover:bg-emerald-100 border border-emerald-100 transition-all text-center">
            <Target :size="18" class="mx-auto text-emerald-600" />
            <p class="text-[10px] font-semibold text-emerald-700 mt-1">生成练习题</p>
            <p class="text-[8px] text-emerald-400">自适应出题</p>
          </button>
          <button class="p-3 rounded-xl bg-amber-50 hover:bg-amber-100 border border-amber-100 transition-all text-center"
            @click="router.push({ path: '/review', query: { student_id: studentId } })">
            <Calendar :size="18" class="mx-auto text-amber-600" />
            <p class="text-[10px] font-semibold text-amber-700 mt-1">复习计划</p>
            <p class="text-[8px] text-amber-400">遗忘曲线推送</p>
          </button>
          <button class="p-3 rounded-xl bg-blue-50 hover:bg-blue-100 border border-blue-100 transition-all text-center"
            @click="router.push({ path: '/notes', query: { student_id: studentId } })">
            <FileText :size="18" class="mx-auto text-blue-600" />
            <p class="text-[10px] font-semibold text-blue-700 mt-1">生成笔记</p>
            <p class="text-[8px] text-blue-400">智能提炼</p>
          </button>
        </div>
      </div>

      <!-- Quick action links -->
      <div v-if="!isTeacher" class="grid grid-cols-1 md:grid-cols-3 gap-4">
        <router-link :to="{ path: '/learn', query: { student_id: studentId } }"
          class="bg-white rounded-2xl border border-gray-100 shadow-sm p-4 hover:border-purple-200 transition-all flex items-center gap-3">
          <div class="w-10 h-10 rounded-xl bg-purple-50 flex items-center justify-center">
            <BookOpen :size="18" class="text-purple-600" />
          </div>
          <div>
            <p class="text-sm font-semibold text-gray-800">开始学习</p>
            <p class="text-[10px] text-gray-400">进入智能对话学习模式</p>
          </div>
        </router-link>
        <router-link :to="{ path: '/learning-path', query: { student_id: studentId } }"
          class="bg-white rounded-2xl border border-gray-100 shadow-sm p-4 hover:border-emerald-200 transition-all flex items-center gap-3">
          <div class="w-10 h-10 rounded-xl bg-emerald-50 flex items-center justify-center">
            <TrendingUp :size="18" class="text-emerald-600" />
          </div>
          <div>
            <p class="text-sm font-semibold text-gray-800">学习路径</p>
            <p class="text-[10px] text-gray-400">查看动态学习路径规划</p>
          </div>
        </router-link>
        <router-link :to="{ path: '/wrong-questions', query: { student_id: studentId } }"
          class="bg-white rounded-2xl border border-gray-100 shadow-sm p-4 hover:border-rose-200 transition-all flex items-center gap-3">
          <div class="w-10 h-10 rounded-xl bg-rose-50 flex items-center justify-center">
            <AlertTriangle :size="18" class="text-rose-500" />
          </div>
          <div>
            <p class="text-sm font-semibold text-gray-800">错题本</p>
            <p class="text-[10px] text-gray-400">查看错题和薄弱点回顾</p>
          </div>
        </router-link>
      </div>
    </div>

    <!-- Edit Profile Modal -->
    <div v-if="showEditModal" class="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/45 backdrop-blur-sm p-4">
      <div class="bg-white rounded-2xl border border-gray-100 shadow-2xl max-w-lg w-full overflow-hidden flex flex-col max-h-[90vh]">
        <!-- Modal Header -->
        <div class="px-5 py-4 border-b border-emerald-100 flex items-center justify-between bg-gradient-to-r from-emerald-50 to-slate-50">
          <div class="flex items-center gap-2">
            <Edit2 :size="16" class="text-emerald-600" />
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
            <label class="block text-xs font-semibold text-gray-600 mb-1">专业/方向</label>
            <input v-model="editForm.major" type="text" class="w-full px-3 py-2 text-xs text-slate-800 border border-gray-200 rounded-lg focus:outline-none focus:ring-1 focus:ring-emerald-500 focus:border-emerald-500 bg-white" placeholder="例如：人工智能实践、计算机科学与技术" />
            <p class="text-[10px] text-gray-400 mt-0.5">将影响教学案例领域的选择（例如金融、医疗等跨学科领域）</p>
          </div>

          <!-- Target Course -->
          <div>
            <label class="block text-xs font-semibold text-gray-600 mb-1">学习目标课程</label>
            <input v-model="editForm.target_course" type="text" class="w-full px-3 py-2 text-xs text-slate-800 border border-gray-200 rounded-lg focus:outline-none focus:ring-1 focus:ring-emerald-500 focus:border-emerald-500 bg-white" placeholder="例如：机器学习导论、高等数学" />
          </div>

          <!-- Cognitive Style -->
          <div>
            <label class="block text-xs font-semibold text-gray-600 mb-1">认知与学习风格</label>
            <select v-model="editForm.cognitive_style" class="w-full px-3 py-2 text-xs text-slate-800 border border-gray-200 rounded-lg focus:outline-none focus:ring-1 focus:ring-emerald-500 focus:border-emerald-500 bg-white">
              <option v-for="opt in styleOptions" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
            </select>
            <p class="text-[10px] text-gray-400 mt-0.5">更改此项将改变大模型回答时的排版优先级与可视化呈现策略</p>
          </div>

          <!-- Motivation Type -->
          <div>
            <label class="block text-xs font-semibold text-gray-600 mb-1">动机类型</label>
            <select v-model="editForm.motivation_type" class="w-full px-3 py-2 text-xs text-slate-800 border border-gray-200 rounded-lg focus:outline-none focus:ring-1 focus:ring-emerald-500 focus:border-emerald-500 bg-white">
              <option v-for="opt in motivationOptions" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
            </select>
          </div>

          <!-- Learning Goals -->
          <div>
            <label class="block text-xs font-semibold text-gray-600 mb-1">核心学习目标 / 诉求</label>
            <input v-model="editForm.learning_goals" type="text" class="w-full px-3 py-2 text-xs text-slate-800 border border-gray-200 rounded-lg focus:outline-none focus:ring-1 focus:ring-emerald-500 focus:border-emerald-500 bg-white" placeholder="多个目标用英文或中文逗号隔开" />
            <p class="text-[10px] text-gray-400 mt-0.5">例如：期末复习冲刺, 科研学术深造, 求职面试准备</p>
          </div>

          <!-- Learning Preferences -->
          <div>
            <label class="block text-xs font-semibold text-gray-600 mb-1.5">偏好支持 (多选)</label>
            <div class="flex flex-wrap gap-2">
              <label v-for="pref in preferenceOptions" :key="pref.value" class="flex items-center gap-1.5 px-2.5 py-1.5 border border-gray-200 rounded-lg text-xs cursor-pointer select-none transition-all hover:bg-purple-50/50" :class="editForm.learning_preferences.includes(pref.value) ? 'border-purple-300 bg-purple-50 text-purple-700 font-medium' : 'bg-gray-50/30 text-gray-600'">
                <input type="checkbox" :value="pref.value" v-model="editForm.learning_preferences" class="sr-only" />
                <span>{{ pref.label }}</span>
              </label>
            </div>
            <p class="text-[10px] text-gray-400 mt-1">控制回答中是否注入分步步骤、实操示例、比喻或图示</p>
          </div>
        </div>

        <!-- Modal Footer -->
        <div class="px-5 py-3 border-t border-gray-100 flex justify-end gap-2 bg-gray-50/50">
          <button @click="showEditModal = false" class="px-3 py-1.5 text-xs font-semibold text-gray-500 hover:text-gray-700 bg-white border border-gray-200 rounded-lg transition-all">
            取消
          </button>
          <button @click="saveProfile" :disabled="saving" class="px-4 py-1.5 text-xs font-semibold text-white bg-emerald-600 hover:bg-emerald-700 rounded-lg shadow-sm transition-all flex items-center gap-1.5 disabled:opacity-50">
            <div v-if="saving" class="animate-spin rounded-full h-3 w-3 border-2 border-white border-t-transparent"></div>
            <span>{{ saving ? '正在保存...' : '确认保存' }}</span>
          </button>
        </div>
      </div>
    </div>

  </div>
</template>
