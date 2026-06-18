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
})

const chartRef = ref(null)
let chartInstance = null

function buildOption() {
  const names = props.concepts.map(c => c.name)
  const values = props.concepts.map(c => (c.mastery || 0) * 100)

  return {
    radar: {
      indicator: names.map(n => ({ name: n, max: 100 })),
      shape: 'polygon',
      splitNumber: 4,
      axisName: { color: '#94a3b8', fontSize: 10 },
      splitArea: {
        areaStyle: { color: ['rgba(59,130,246,0.02)', 'rgba(59,130,246,0.05)'] },
      },
      axisLine: { lineStyle: { color: 'rgba(148,163,184,0.2)' } },
    },
    series: [{
      type: 'radar',
      data: [{ value: values, name: '掌握度', areaStyle: { color: 'rgba(59,130,246,0.15)' } }],
      symbol: 'circle',
      symbolSize: 6,
      itemStyle: { color: '#3b82f6' },
      lineStyle: { color: '#3b82f6', width: 2 },
    }],
    tooltip: {
      formatter: (params) => {
        const vals = params.value
        return `<div style="font-size:12px;color:#333">掌握度雷达</div>`
          + props.concepts.map((c, i) =>
            `<div style="font-size:11px;color:#666">${c.name}: ${vals[i]?.toFixed(0) || 0}%</div>`
          ).join('')
      },
    },
  }
}

function initChart() {
  if (!chartRef.value) return
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
  window.addEventListener('resize', _handleResize)
})

onUnmounted(() => {
  // 任务 8.2: 解绑 resize 监听 + 释放 ECharts 实例
  window.removeEventListener('resize', _handleResize)
  if (chartInstance) {
    chartInstance.dispose()
    chartInstance = null
  }
})

watch(() => props.concepts, () => {
  if (chartInstance) {
    chartInstance.setOption(buildOption(), true)
  }
}, { deep: true })
</script>

<template>
  <div ref="chartRef" class="w-full h-full min-h-[250px]" />
</template>
