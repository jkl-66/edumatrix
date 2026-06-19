<script setup>
/**
 * LearningPathGraph.vue — 任务 7.1 前端: DAG 知识依赖图谱可视化
 *
 * 基于 ECharts-Graph 渲染交互图谱，点击节点可查看详情，
 * ZPD 区间高亮，前置依赖回滚路径展示。
 */
import { ref, onMounted, onUnmounted, nextTick, computed } from 'vue'
import { BookOpen, BrainCircuit, Info, AlertTriangle, ArrowLeft } from '@lucide/vue'
import { getStudentProfile } from '../api'
import * as echarts from 'echarts'

const props = defineProps({
  studentId: { type: String, default: 'demo-student' },
})

const loading = ref(true)
const error = ref('')
const profile = ref(null)
const selectedNode = ref(null)
const chartRef = ref(null)
let chartInstance = null

// 默认知识依赖 DAG（与 agent_swarm.py DEFAULT_KNOWLEDGE_DAG 同步）
const KNOWLEDGE_DAG = {
  '池化层': { level: 1, category: '神经网络' },
  '最大池化': { level: 2, category: '神经网络' },
  '平均池化': { level: 2, category: '神经网络' },
  '卷积核': { level: 1, category: '神经网络' },
  '特征图': { level: 2, category: '神经网络' },
  '反向传播': { level: 1, category: '优化' },
  '链式法则': { level: 2, category: '优化' },
  '梯度下降': { level: 1, category: '优化' },
  '逻辑回归': { level: 1, category: '监督学习' },
  '线性回归': { level: 1, category: '监督学习' },
  '决策树': { level: 1, category: '监督学习' },
  '支持向量机': { level: 2, category: '监督学习' },
  '过拟合': { level: 2, category: '模型评估' },
  '正则化': { level: 2, category: '模型评估' },
  '交叉验证': { level: 2, category: '模型评估' },
  '机器学习': { level: 0, category: '基础' },
  '监督学习': { level: 1, category: '基础' },
  '模型评估': { level: 1, category: '基础' },
  'Transformer': { level: 2, category: '前沿' },
  '注意力机制': { level: 2, category: '前沿' },
  '神经网络': { level: 1, category: '神经网络' },
  '卷积神经网络': { level: 2, category: '神经网络' },
}

const EDGES = [
  ['池化层', '卷积核'], ['池化层', '特征图'],
  ['最大池化', '池化层'], ['平均池化', '池化层'],
  ['卷积核', '反向传播'], ['特征图', '卷积核'],
  ['反向传播', '链式法则'], ['反向传播', '梯度下降'],
  ['链式法则', '梯度下降'], ['梯度下降', '线性回归'],
  ['逻辑回归', '线性回归'], ['逻辑回归', '梯度下降'],
  ['线性回归', '机器学习'], ['决策树', '机器学习'],
  ['支持向量机', '线性回归'], ['支持向量机', '机器学习'],
  ['过拟合', '正则化'], ['过拟合', '交叉验证'],
  ['正则化', '线性回归'], ['交叉验证', '机器学习'],
  ['监督学习', '机器学习'], ['模型评估', '机器学习'],
  ['Transformer', '注意力机制'], ['Transformer', '反向传播'],
  ['注意力机制', '神经网络'],
  ['神经网络', '反向传播'], ['神经网络', '梯度下降'],
  ['卷积神经网络', '神经网络'], ['卷积神经网络', '卷积核'], ['卷积神经网络', '池化层'],
]

const CATEGORIES = ['基础', '监督学习', '优化', '神经网络', '模型评估', '前沿']
const CATEGORY_COLORS = ['#94a3b8', '#3b82f6', '#8b5cf6', '#f97316', '#10b981', '#ec4899']

const nodes = computed(() => {
  if (!profile.value) return []
  const mastery = profile.value.concept_mastery || {}
  return Object.entries(KNOWLEDGE_DAG).map(([name, info]) => {
    const m = mastery[name] || 0
    let color = '#94a3b8' // 默认灰色
    let symbolSize = 30
    let zpdZone = 'unknown'

    if (m >= 0.75) {
      color = '#22c55e' // 绿色 — 已掌握
      symbolSize = 35
      zpdZone = 'mastered'
    } else if (m >= 0.3) {
      color = '#eab308' // 黄色 — ZPD 核心区
      symbolSize = 40
      zpdZone = 'zpd'
    } else if (m > 0) {
      color = '#ef4444' // 红色 — 薄弱
      symbolSize = 38
      zpdZone = 'weak'
    }

    return {
      id: name,
      name,
      value: `${name}\n掌握度: ${(m * 100).toFixed(0)}%\n类别: ${info.category}\nZPD: ${zpdZone}`,
      category: CATEGORIES.indexOf(info.category),
      itemStyle: { color },
      symbolSize,
      mastery: m,
      zpdZone,
      concept: name,
      categoryName: info.category,
    }
  })
})

const edges = computed(() => {
  return EDGES.map(([source, target]) => ({
    source,
    target,
    label: { show: false },
    lineStyle: {
      color: '#475569',
      width: 1.5,
      curveness: 0.1,
      type: 'solid',
    },
  }))
})

function buildChartOption() {
  return {
    title: {
      text: '知识依赖图谱 (DAG)',
      subtext: '节点颜色: 绿色=已掌握  黄色=ZPD发展区  红色=薄弱  灰色=未接触',
      left: 'center',
      top: 10,
      textStyle: { fontSize: 16, color: '#e2e8f0' },
      subtextStyle: { fontSize: 10, color: '#94a3b8' },
    },
    tooltip: {
      formatter: (params) => {
        if (params.dataType === 'node') {
          return `
            <div style="font-size:13px;font-weight:bold">${params.name}</div>
            <div style="font-size:11px;color:#666;margin-top:4px">
              类别: ${params.data.categoryName}<br/>
              掌握度: ${(params.data.mastery * 100).toFixed(0)}%<br/>
              ZPD 区间: ${params.data.zpdZone}
            </div>
          `
        }
        return `${params.data.source} → ${params.data.target}`
      },
    },
    legend: {
      data: CATEGORIES,
      top: 60,
      left: 'center',
      textStyle: { fontSize: 10, color: '#94a3b8' },
    },
    animationDuration: 800,
    animationEasingUpdate: 'quinticInOut',
    series: [{
      type: 'graph',
      layout: 'force',
      force: {
        repulsion: 500,
        edgeLength: [80, 200],
        layoutAnimation: false,
        friction: 0.1,
      },
      roam: true,
      draggable: true,
      data: nodes.value,
      edges: edges.value,
      categories: CATEGORIES.map((name, i) => ({
        name,
        itemStyle: { color: CATEGORY_COLORS[i] },
      })),
      label: {
        show: true,
        position: 'bottom',
        fontSize: 10,
        color: '#cbd5e1',
        offset: [0, 4],
      },
      edgeLabel: { show: false },
      lineStyle: {
        color: 'source',
        curveness: 0.1,
        width: 1.5,
      },
      emphasis: {
        focus: 'adjacency',
        lineStyle: { width: 3 },
      },
      zoom: 0.8,
    }],
  }
}

function onChartClick(params) {
  if (params.dataType === 'node') {
    selectedNode.value = {
      name: params.data.concept,
      mastery: params.data.mastery,
      zpdZone: params.data.zpdZone,
      categoryName: params.data.categoryName,
      // 计算前置依赖
      prerequisites: EDGES
        .filter(([s, t]) => t === params.data.concept)
        .map(([s]) => s),
      // 计算后置依赖
      dependents: EDGES
        .filter(([s, t]) => s === params.data.concept)
        .map(([, t]) => t),
    }
  }
}

onMounted(async () => {
  try {
    const res = await getStudentProfile(props.studentId)
    profile.value = res.data ? (typeof res.data === 'object' ? res.data : JSON.parse(res.data)) : res
  } catch (e) {
    error.value = '加载学生画像失败'
  }
  loading.value = false

  await nextTick()
  if (chartRef.value) {
    chartInstance = echarts.init(chartRef.value)
    chartInstance.setOption(buildChartOption())
    chartInstance.on('click', onChartClick)
    window.addEventListener('resize', () => chartInstance?.resize())
  }
})

onUnmounted(() => {
  chartInstance?.dispose()
})
</script>

<template>
  <div class="min-h-screen bg-gray-950 text-gray-200 p-6">
    <div class="max-w-7xl mx-auto">
      <!-- 页头 -->
      <div class="flex items-center justify-between mb-6">
        <div class="flex items-center gap-3">
          <BrainCircuit :size="22" class="text-purple-400" />
          <div>
            <h1 class="text-lg font-bold">知识依赖图谱</h1>
            <p class="text-[11px] text-gray-400">EduMatrix ZPD 自适应学习路径规划</p>
          </div>
        </div>
        <div class="flex items-center gap-2">
          <span class="inline-flex items-center gap-1 px-2 py-0.5 bg-green-900/30 text-green-400 rounded text-[10px]">
            <span class="w-2 h-2 rounded-full bg-green-500" /> 已掌握
          </span>
          <span class="inline-flex items-center gap-1 px-2 py-0.5 bg-yellow-900/30 text-yellow-400 rounded text-[10px]">
            <span class="w-2 h-2 rounded-full bg-yellow-500" /> ZPD发展区
          </span>
          <span class="inline-flex items-center gap-1 px-2 py-0.5 bg-red-900/30 text-red-400 rounded text-[10px]">
            <span class="w-2 h-2 rounded-full bg-red-500" /> 薄弱
          </span>
        </div>
      </div>

      <!-- 加载 / 错误 -->
      <div v-if="loading" class="flex items-center justify-center py-20">
        <div class="animate-spin w-6 h-6 border-2 border-purple-500 border-t-transparent rounded-full" />
        <span class="ml-3 text-sm text-gray-400">加载图谱数据...</span>
      </div>
      <div v-else-if="error" class="flex items-center justify-center py-20">
        <AlertTriangle :size="18" class="text-red-500 mr-2" />
        <span class="text-sm text-red-400">{{ error }}</span>
      </div>

      <div v-else class="grid grid-cols-1 lg:grid-cols-4 gap-6">
        <!-- 图谱区域 -->
        <div class="lg:col-span-3 bg-gray-900 rounded-lg border border-gray-800 overflow-hidden">
          <div ref="chartRef" class="w-full h-[600px]" />
        </div>

        <!-- 选中节点详情面板 -->
        <div class="bg-gray-900 rounded-lg border border-gray-800 p-4">
          <div v-if="!selectedNode" class="text-center text-gray-500 text-sm py-10">
            <Info :size="32" class="mx-auto mb-2 opacity-40" />
            <p>点击图中的节点<br/>查看详细知识信息</p>
          </div>
          <div v-else>
            <div class="flex items-center gap-2 mb-3">
              <BookOpen :size="16" class="text-purple-400" />
              <h3 class="font-semibold text-sm">{{ selectedNode.name }}</h3>
            </div>

            <div class="space-y-3 text-xs">
              <div class="flex justify-between">
                <span class="text-gray-400">掌握度</span>
                <span :class="selectedNode.mastery >= 0.75 ? 'text-green-400' : selectedNode.mastery >= 0.3 ? 'text-yellow-400' : 'text-red-400'">
                  {{ (selectedNode.mastery * 100).toFixed(0) }}%
                </span>
              </div>
              <div class="flex justify-between">
                <span class="text-gray-400">ZPD 区间</span>
                <span class="text-gray-200">{{ selectedNode.zpdZone }}</span>
              </div>
              <div class="flex justify-between">
                <span class="text-gray-400">类别</span>
                <span class="text-gray-200">{{ selectedNode.categoryName }}</span>
              </div>

              <!-- 前置依赖 -->
              <div v-if="selectedNode.prerequisites.length">
                <p class="text-gray-400 mb-1 mt-3">前置依赖</p>
                <div class="flex flex-wrap gap-1">
                  <span v-for="p in selectedNode.prerequisites" :key="p"
                    class="px-2 py-0.5 bg-blue-900/30 text-blue-400 rounded text-[10px]"
                  >{{ p }}</span>
                </div>
              </div>

              <!-- 后置依赖（进阶） -->
              <div v-if="selectedNode.dependents.length">
                <p class="text-gray-400 mb-1 mt-3">进阶方向</p>
                <div class="flex flex-wrap gap-1">
                  <span v-for="d in selectedNode.dependents" :key="d"
                    class="px-2 py-0.5 bg-purple-900/30 text-purple-400 rounded text-[10px]"
                  >{{ d }}</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
