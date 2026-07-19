<script setup>
/**
 * KnowledgeGraphExplorer.vue — 任务 8.6: 多模态课件知识图谱网络探索器
 *
 * 对接 Neo4j → ECharts-Graph 星空网络图渲染，
 * 节点区分概念/图表/公式，连线代表前置依赖、资源归属。
 * 支持关键词模糊检索、高亮两级上下游关联节点。
 */
import { ref, onMounted, onUnmounted, nextTick, computed, watch } from 'vue'
import * as echarts from 'echarts'
import { Search, Filter, ZoomIn, ZoomOut, RotateCw, Info } from '@lucide/vue'

const props = defineProps({
  nodes: { type: Array, default: () => [] },         // [{id, name, category, symbolSize, itemStyle}]
  edges: { type: Array, default: () => [] },         // [{source, target, label}]
  categories: { type: Array, default: () => [] },    // [{name, itemStyle}]
})

const chartRef = ref(null)
const searchQuery = ref('')
const selectedNode = ref(null)
let chartInstance = null
let highlightedNodes = new Set()

const categoryColors = ['#4f8a9a', '#c28b3c', '#4b9b7e', '#7b819c', '#b4778e', '#5c9eaa']

function buildOption() {
  // 处理高亮
  const chartNodes = props.nodes.map(n => {
    const isHighlighted = highlightedNodes.has(n.id)
    return {
      ...n,
      itemStyle: {
        ...(n.itemStyle || {}),
        opacity: highlightedNodes.size > 0 ? (isHighlighted ? 1 : 0.2) : 1,
      },
      label: {
        show: true,
        fontSize: isHighlighted ? 13 : 10,
        fontWeight: isHighlighted ? 'bold' : 'normal',
        color: isHighlighted ? '#243128' : '#607267',
      },
    }
  })

  return {
    title: {
      text: '知识图谱 (Neo4j)',
      subtext: '拖拽探索 · 点击节点高亮两级关联',
      left: 'center',
      top: 8,
      textStyle: { fontSize: 14, color: '#243128' },
      subtextStyle: { fontSize: 10, color: '#718076' },
    },
    tooltip: {
      backgroundColor: '#ffffff',
      borderColor: '#dbe5df',
      borderWidth: 1,
      textStyle: { color: '#35433a' },
      formatter: (params) => {
        if (params.dataType === 'node') {
          return `<div style="font-size:12px;font-weight:bold;color:#243128">${params.name}</div>
            <div style="font-size:10px;color:#718076">类别: ${params.data.categoryName || params.data.category || '未知'}</div>`
        }
        return `${params.data.source} → ${params.data.target}`
      },
    },
    legend: {
      data: props.categories.length ? props.categories.map(c => c.name) : [],
      top: 50,
      left: 'center',
      textStyle: { fontSize: 10, color: '#607267' },
    },
    animationDuration: 800,
    animationEasingUpdate: 'quinticInOut',
    series: [{
      type: 'graph',
      layout: 'force',
      force: {
        repulsion: 600,
        edgeLength: [80, 200],
        layoutAnimation: false,
        friction: 0.1,
      },
      roam: true,
      draggable: true,
      data: chartNodes,
      edges: props.edges,
      categories: props.categories.length ? props.categories : undefined,
      label: {
        show: true,
        position: 'bottom',
        fontSize: 10,
        color: '#607267',
      },
      edgeLabel: { show: false },
      lineStyle: {
        color: 'source',
        curveness: 0.1,
        width: 1.5,
        opacity: 0.5,
      },
      emphasis: {
        focus: 'adjacency',
        lineStyle: { width: 3, opacity: 0.8 },
      },
    }],
  }
}

function doSearch() {
  const q = searchQuery.value.trim().toLowerCase()
  highlightedNodes.clear()

  if (!q) {
    chartInstance?.setOption(buildOption(), true)
    selectedNode.value = null
    return
  }

  // 查找匹配节点
  props.nodes.forEach(n => {
    if (n.name.toLowerCase().includes(q)) {
      highlightedNodes.add(n.id)
      // 两级上下游
      props.edges.forEach(e => {
        if (e.source === n.id) highlightedNodes.add(e.target)
        if (e.target === n.id) highlightedNodes.add(e.source)
        // 二级
        props.edges.forEach(e2 => {
          if (e2.source === e.target && e.source === n.id) highlightedNodes.add(e2.target)
          if (e2.target === e.source && e.target === n.id) highlightedNodes.add(e2.source)
        })
      })
    }
  })

  if (highlightedNodes.size > 0) {
    const matched = props.nodes.find(n => n.name.toLowerCase().includes(q))
    if (matched) selectedNode.value = matched
  }

  chartInstance?.setOption(buildOption(), true)
}

// 节点点击 -> 高亮两级关联
function onChartClick(params) {
  if (params.dataType === 'node') {
    highlightedNodes.clear()
    const nodeId = params.data.id
    highlightedNodes.add(nodeId)

    props.edges.forEach(e => {
      if (e.source === nodeId) highlightedNodes.add(e.target)
      if (e.target === nodeId) highlightedNodes.add(e.source)
      props.edges.forEach(e2 => {
        if (e2.source === e.target && e.source === nodeId) highlightedNodes.add(e2.target)
        if (e2.target === e.source && e.target === nodeId) highlightedNodes.add(e2.source)
      })
    })

    selectedNode.value = props.nodes.find(n => n.id === nodeId) || null
    chartInstance?.setOption(buildOption(), true)
  }
}

function resetView() {
  highlightedNodes.clear()
  selectedNode.value = null
  searchQuery.value = ''
  chartInstance?.setOption(buildOption(), true)
  chartInstance?.dispatchAction({ type: 'restore' })
}

onMounted(async () => {
  await nextTick()
  if (chartRef.value) {
    chartInstance = echarts.init(chartRef.value)
    chartInstance.setOption(buildOption())
    chartInstance.on('click', onChartClick)
    window.addEventListener('resize', () => chartInstance?.resize())
  }
})

onUnmounted(() => {
  window.removeEventListener('resize', () => chartInstance?.resize())
  chartInstance?.dispose()
})

watch(() => [props.nodes, props.edges], () => {
  chartInstance?.setOption(buildOption(), true)
}, { deep: true })
</script>

<template>
  <div class="knowledge-graph bg-white rounded-lg border border-slate-200 overflow-hidden shadow-sm">
    <!-- 工具栏 -->
    <div class="flex items-center gap-2 px-3 py-2 bg-slate-50 border-b border-slate-200">
      <div class="flex-1 flex items-center gap-2">
        <Search :size="14" class="text-slate-500 shrink-0" />
        <input v-model="searchQuery" @input="doSearch" placeholder="检索知识点..."
          class="flex-1 bg-white text-slate-700 placeholder:text-slate-400 text-xs px-2 py-1 rounded border border-slate-200 outline-none focus:border-emerald-500 focus:ring-1 focus:ring-emerald-500/20" />
      </div>
      <button @click="resetView" class="px-2 py-1 text-[10px] bg-white hover:bg-emerald-50 text-slate-600 rounded border border-slate-200 transition-colors flex items-center gap-1">
        <RotateCw :size="10" /> 重置
      </button>
    </div>

    <div class="flex">
      <!-- 图谱 -->
      <div class="flex-1 bg-[#f8fbf9]">
        <div ref="chartRef" class="w-full h-[500px]" />
      </div>

      <!-- 选中节点详情 -->
      <div v-if="selectedNode" class="w-52 border-l border-slate-200 p-3 bg-white">
        <div class="flex items-center gap-2 mb-2">
          <Info :size="14" class="text-emerald-700" />
          <span class="text-xs font-semibold text-slate-800">{{ selectedNode.name }}</span>
        </div>
        <div class="space-y-2 text-[10px]">
          <div class="flex justify-between">
            <span class="text-gray-500">类别</span>
            <span class="text-gray-300">{{ selectedNode.categoryName || selectedNode.category || '-' }}</span>
          </div>
          <div class="flex justify-between">
            <span class="text-gray-500">关联数</span>
            <span class="text-gray-300">{{ highlightedNodes.size - 1 }}</span>
          </div>
          <div class="flex justify-between">
            <span class="text-gray-500">符号</span>
            <span class="text-gray-300">{{ selectedNode.symbol || 'circle' }}</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.knowledge-graph :deep(.text-gray-500) { color: #64756b !important; }
.knowledge-graph :deep(.text-gray-300) { color: #405349 !important; }
</style>
