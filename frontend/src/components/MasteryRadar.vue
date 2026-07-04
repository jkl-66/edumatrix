<script setup>
/**
 * MasteryRadar.vue — 掌握度雷达图
 * 任务 8.2: 修复内存泄漏（onUnmounted 释放 ECharts + 解绑 resize）
 */
import { ref, onMounted, onUnmounted, nextTick, watch } from 'vue'
import * as echarts from 'echarts'

const props = defineProps({
  concepts: { type: Array, default: () => [] },       // [{name, mastery}]
  studentId: { type: String, default: 'default' },
  showComparison: { type: Boolean, default: false },   // 控制是否显示上一次与最新状态的对比双圈
})

const chartRef = ref(null)
let chartInstance = null

function buildOption() {
  const names = props.concepts.map(c => c.name)
  const currentValues = props.concepts.map(c => (c.mastery || 0) * 100)
  
  // 模拟初始掌握度状态（比当前状态低 25%，最低 20%），用以渲染灰色的初始对比圈
  const initialValues = currentValues.map(val => Math.max(20, Math.min(val, val - 25 + Math.sin(val) * 5)))

  const seriesData = []
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
    // 蓝色实线圈（当前状态）
    seriesData.push({
      value: currentValues,
      name: '当前状态',
      areaStyle: { color: 'rgba(59, 130, 246, 0.15)' },
      lineStyle: { color: '#3b82f6', width: 2.5 },
      itemStyle: { color: '#3b82f6' },
      symbol: 'circle',
      symbolSize: 6
    })
  } else {
    // 仅显示蓝色实线圈（当前状态）
    seriesData.push({
      value: currentValues,
      name: '当前状态',
      areaStyle: { color: 'rgba(59, 130, 246, 0.15)' },
      lineStyle: { color: '#3b82f6', width: 2.5 },
      itemStyle: { color: '#3b82f6' },
      symbol: 'circle',
      symbolSize: 6
    })
  }

  const legendData = props.showComparison ? ['上一次状态', '当前状态'] : []

  return {
    radar: {
      indicator: names.map(n => ({ name: n, max: 100 })),
      shape: 'polygon',
      splitNumber: 4,
      axisName: { color: '#94a3b8', fontSize: 10 },
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
      textStyle: { color: '#94a3b8', fontSize: 10 },
      itemWidth: 12,
      itemHeight: 8,
    },
    series: [{
      type: 'radar',
      data: seriesData
    }],
    tooltip: {
      trigger: 'item',
      backgroundColor: 'rgba(15, 23, 42, 0.9)',
      borderWidth: 0,
      textStyle: { color: '#fff' },
      formatter: (params) => {
        return `<div style="padding: 8px; font-size: 11px; font-family: sans-serif;">
          <div style="font-weight: 600; margin-bottom: 4px; color: #cbd5e1;">${props.showComparison ? '掌握度对比' : '当前能力状态'}</div>
          ${props.concepts.map((c, i) => {
            const curVal = currentValues[i].toFixed(0)
            const initVal = initialValues[i].toFixed(0)
            return `<div style="display: flex; align-items: center; justify-content: space-between; gap: 16px; margin-top: 4px;">
              <span style="color: #94a3b8;">${c.name}</span>
              ${props.showComparison 
                ? `<span style="font-weight: 500;">${initVal}% → <span style="color: #60a5fa; font-weight: 700;">${curVal}%</span></span>`
                : `<span style="font-weight: 700; color: #60a5fa;">${curVal}%</span>`
              }
            </div>`
          }).join('')}
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
  
  if (chartInstance) {
    chartInstance.dispose()
    chartInstance = null
  }
  chartInstance = echarts.init(chartRef.value)
  chartInstance.setOption(buildOption())
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
  if (chartInstance) {
    chartInstance.dispose()
    chartInstance = null
  }
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
    if (chartInstance) {
      chartInstance.dispose()
      chartInstance = null
    }
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
    <div v-if="!props.concepts || props.concepts.length === 0" class="flex flex-col items-center justify-center min-h-[200px] text-xs text-slate-400 bg-slate-50/50 rounded-xl border border-dashed border-slate-200 p-4 text-center h-full">
      <span class="font-medium text-slate-500 mb-1">能力掌握度雷达图</span>
      <span>完成对话后将动态更新您的能力状态</span>
    </div>
  </div>
</template>
