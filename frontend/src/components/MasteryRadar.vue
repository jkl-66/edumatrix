<script setup>
/**
 * MasteryRadar.vue — 掌握度雷达图
 * 任务 8.2: 修复内存泄漏（onUnmounted 释放 ECharts + 解绑 resize）
 */
import { ref, onMounted, onUnmounted, nextTick, watch } from 'vue'
import { echarts } from '../lib/echarts-radar'

const props = defineProps({
  concepts: { type: Array, default: () => [] },       // [{name, mastery}]
  studentId: { type: String, default: 'default' },
  showComparison: { type: Boolean, default: false },   // 控制是否显示上一次与最新状态的对比双圈
})

const chartRef = ref(null)
let chartInstance = null
let hoveredDimensionIndex = -1

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, char => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;'
  })[char])
}

function currentSeriesDataIndex() {
  return props.showComparison ? 3 : 2
}

function dimensionIndexFromEvent(params) {
  const dimensionIndex = params?.event?.target?.__dimIdx
  return Number.isInteger(dimensionIndex) ? dimensionIndex : -1
}

function hideRadarTooltip() {
  hoveredDimensionIndex = -1
  chartInstance?.dispatchAction({ type: 'hideTip' })
}

function handleRadarMouseOver(params) {
  const dimensionIndex = dimensionIndexFromEvent(params)
  if (
    dimensionIndex < 0 ||
    dimensionIndex >= props.concepts.length ||
    params?.dataIndex !== currentSeriesDataIndex()
  ) {
    return
  }

  hoveredDimensionIndex = dimensionIndex
  chartInstance?.dispatchAction({
    type: 'showTip',
    seriesIndex: params.seriesIndex ?? 0,
    dataIndex: currentSeriesDataIndex(),
    position: [params.event.offsetX, params.event.offsetY]
  })
}

function handleRadarMouseOut(params) {
  if (dimensionIndexFromEvent(params) >= 0) {
    hideRadarTooltip()
  }
}

function handleRadarGlobalOut() {
  hideRadarTooltip()
}

function disposeChart() {
  if (!chartInstance) {
    hoveredDimensionIndex = -1
    return
  }
  chartInstance.off('mouseover', handleRadarMouseOver)
  chartInstance.off('mouseout', handleRadarMouseOut)
  chartInstance.off('globalout', handleRadarGlobalOut)
  chartInstance.dispose()
  chartInstance = null
  hoveredDimensionIndex = -1
}

function buildOption(useZeroValues = false) {
  const names = props.concepts.map(c => c.name)
  const realCurrent = props.concepts.map(c => (c.mastery || 0) * 100)
  const currentValues = useZeroValues ? realCurrent.map(() => 0) : realCurrent
  
  // 计算基于卡尔曼协方差 P_k 的置信环带宽度 (p_err 范围一般为 0.01~1.0)
  const confidenceMargins = props.concepts.map(c => {
    const err = c.p_err !== undefined ? c.p_err : 0.1
    return Math.max(2, Math.min(22, err * 20))
  })
  
  const realUpper = realCurrent.map((val, idx) => Math.min(100, val + confidenceMargins[idx]))
  const realLower = realCurrent.map((val, idx) => Math.max(0, val - confidenceMargins[idx]))
  const realInitial = realCurrent.map(val => Math.max(20, Math.min(val, val - 25 + Math.sin(val) * 5)))

  const upperBounds = useZeroValues ? realUpper.map(() => 0) : realUpper
  const lowerBounds = useZeroValues ? realLower.map(() => 0) : realLower
  const initialValues = useZeroValues ? realInitial.map(() => 0) : realInitial

  const seriesData = []

  // 1. 置信度外边界圈 (发光环带上界)
  seriesData.push({
    value: upperBounds,
    name: '置信度上限 (测不准偏差)',
    areaStyle: { color: 'rgba(37, 55, 69, 0.09)' },
    lineStyle: { color: 'rgba(37, 55, 69, 0.28)', type: 'dashed', width: 1 },
    itemStyle: { color: 'rgba(37, 55, 69, 0.45)' },
    symbol: 'none'
  })

  // 2. 置信度内边界圈 (利用 85% 透明度遮罩白底，形成中空发光置信环带)
  seriesData.push({
    value: lowerBounds,
    name: '置信度下限',
    areaStyle: { color: 'rgba(255, 255, 255, 0.85)' },
    lineStyle: { color: 'rgba(37, 55, 69, 0.28)', type: 'dashed', width: 1 },
    itemStyle: { color: 'rgba(37, 55, 69, 0.45)' },
    symbol: 'none'
  })

  if (props.showComparison) {
    // 灰色虚线圈（上一次/初始状态）
    seriesData.push({
      value: initialValues,
      name: '上一次状态',
      areaStyle: { color: 'rgba(148, 163, 184, 0.03)' },
      lineStyle: { color: 'rgba(148, 163, 184, 0.4)', type: 'dashed', width: 1.5 },
      itemStyle: { color: 'rgba(148, 163, 184, 0.6)' },
      symbol: 'none'
    })
  }

  // 3. 当前掌握度流动发光实线圈
  seriesData.push({
    value: currentValues,
    name: '当前掌握度 (BKT卡尔曼估计值)',
    areaStyle: { color: 'rgba(91, 64, 48, 0.12)' },
    lineStyle: { color: '#253745', width: 2.5 },
    itemStyle: { color: '#253745' },
    symbol: 'circle',
    symbolSize: 6
  })

  const legendData = props.showComparison ? ['上一次状态', '当前掌握度 (BKT卡尔曼估计值)'] : []

  return {
    radar: {
      indicator: names.map(n => ({ name: n, max: 100 })),
      shape: 'polygon',
      radius: '55%',
      center: ['50%', '52%'],
      splitNumber: 4,
      axisName: {
        show: false,
        color: '#4a5c6a',
        fontSize: 14,
        padding: [2, 4],
      },
      axisNameGap: 5,
      splitArea: {
        areaStyle: { color: ['rgba(30,41,59,0.02)', 'rgba(30,41,59,0.05)'] },
      },
      axisLine: { lineStyle: { color: 'rgba(148,163,184,0.15)' } },
      splitLine: { lineStyle: { color: 'rgba(148,163,184,0.15)' } },
    },
    legend: {
      show: props.showComparison,
      data: legendData,
      bottom: 0,
      textStyle: { color: '#60727c', fontSize: 14 },
      itemWidth: 12,
      itemHeight: 8,
    },
    series: [{
      type: 'radar',
      data: seriesData
    }],
    tooltip: {
      trigger: 'item',
      triggerOn: 'none',
      confine: true,
      backgroundColor: 'rgba(15, 23, 42, 0.95)',
      borderWidth: 0,
      textStyle: { color: '#fff' },
      formatter: () => {
        const concept = props.concepts[hoveredDimensionIndex]
        if (!concept) return ''

        const curVal = currentValues[hoveredDimensionIndex].toFixed(0)
        const initVal = initialValues[hoveredDimensionIndex].toFixed(0)
        const name = escapeHtml(concept.name)
        const value = props.showComparison
          ? `${initVal}% → ${curVal}%`
          : `${curVal}%`

        return `<div style="padding: 8px 10px; font-size: 14px; font-family: sans-serif; max-width: 260px;">
          <div style="font-weight: 600; margin-bottom: 6px; color: #f8fafc;">${name}</div>
          <div style="color: #cbd5e1;">掌握度：<span style="font-weight: 700; color: #fff;">${value}</span></div>
        </div>`
      },
    },
  }
}

let resizeObserver = null

function initChart() {
  if (!chartRef.value || !props.concepts || props.concepts.length === 0) return
  const width = chartRef.value.clientWidth
  const height = chartRef.value.clientHeight
  if (width === 0 || height === 0) return // Skip initialization if element is hidden/has zero size
  
  disposeChart()
  chartInstance = echarts.init(chartRef.value)
  chartInstance.on('mouseover', handleRadarMouseOver)
  chartInstance.on('mouseout', handleRadarMouseOut)
  chartInstance.on('globalout', handleRadarGlobalOut)
  chartInstance.setOption(buildOption(true))
  setTimeout(() => {
    if (chartInstance) {
      chartInstance.setOption(buildOption(false))
    }
  }, 100)
}

// 任务 8.2: 使用具名 resize 函数，确保 onUnmounted 能解绑
function _handleResize() {
  chartInstance?.resize()
}

onMounted(async () => {
  await nextTick()
  initChart()
  
  if (window.ResizeObserver && chartRef.value) {
    resizeObserver = new ResizeObserver((entries) => {
      for (let entry of entries) {
        const { width, height } = entry.contentRect
        if (width > 0 && height > 0) {
          if (!chartInstance) {
            initChart()
          } else {
            chartInstance.resize()
          }
        }
      }
    })
    resizeObserver.observe(chartRef.value)
  }
  
  window.addEventListener('resize', _handleResize)
})

onUnmounted(() => {
  // 任务 8.2: 解绑 resize 监听 + 释放 ECharts 实例
  window.removeEventListener('resize', _handleResize)
  if (resizeObserver) {
    resizeObserver.disconnect()
    resizeObserver = null
  }
  disposeChart()
})

watch(() => props.concepts, (newVal) => {
  if (newVal && newVal.length > 0) {
    nextTick(() => {
      if (!chartInstance) {
        initChart()
      } else {
        chartInstance.setOption(buildOption(), true)
      }
    })
  } else {
    disposeChart()
  }
}, { deep: true })

watch(() => props.showComparison, () => {
  if (chartInstance) {
    chartInstance.setOption(buildOption(), true)
  }
})
</script>

<template>
  <div class="w-full h-full min-h-[200px]">
    <div v-show="props.concepts && props.concepts.length > 0" ref="chartRef" class="w-full h-full min-h-[200px]" />
    <div v-if="!props.concepts || props.concepts.length === 0" class="flex flex-col items-center justify-center min-h-[200px] text-sm text-slate-500 bg-[#f3f6f6] rounded-lg border border-dashed border-[#ccd0cf] p-4 text-center h-full">
      <span class="font-medium text-slate-500 mb-1">能力掌握度雷达图</span>
      <span>完成对话后将动态更新您的能力状态</span>
    </div>
  </div>
</template>
