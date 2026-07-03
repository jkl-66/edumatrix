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
        areaStyle: { color: ['rgba(30,41,59,0.02)', 'rgba(30,41,59,0.05)'] },
      },
      axisLine: { lineStyle: { color: 'rgba(148,163,184,0.15)' } },
      splitLine: { lineStyle: { color: 'rgba(148,163,184,0.15)' } },
    },
    series: [{
      type: 'radar',
      data: [
        {
          value: values,
          name: '最新状态',
          areaStyle: { color: 'rgba(59, 130, 246, 0.15)' },
          lineStyle: { color: '#3b82f6', width: 2.5 },
          itemStyle: { color: '#3b82f6' },
          symbol: 'circle',
          symbolSize: 6
        }
      ]
    }],
    tooltip: {
      trigger: 'item',
      backgroundColor: 'rgba(15, 23, 42, 0.9)',
      borderWidth: 0,
      textStyle: { color: '#fff' },
      formatter: (params) => {
        return `<div style="padding: 8px; font-size: 11px; font-family: sans-serif;">
          <div style="font-weight: 600; margin-bottom: 4px; color: #cbd5e1;">当前能力状态</div>
          ${props.concepts.map((c, i) => {
            const val = values[i].toFixed(0)
            return `<div style="display: flex; align-items: center; justify-content: space-between; gap: 16px; margin-top: 4px;">
              <span style="color: #94a3b8;">${c.name}</span>
              <span style="font-weight: 700; color: #60a5fa;">${val}%</span>
            </div>`
          }).join('')}
        </div>`
      },
    },
  }
}

function initChart() {
  if (!chartRef.value || !props.concepts || props.concepts.length === 0) return
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
</script>

<template>
  <div v-show="props.concepts && props.concepts.length > 0" ref="chartRef" class="w-full h-full min-h-[200px]" />
  <div v-if="!props.concepts || props.concepts.length === 0" class="flex flex-col items-center justify-center min-h-[200px] text-xs text-slate-400 bg-slate-50/50 rounded-xl border border-dashed border-slate-200 p-4 text-center">
    <span class="font-medium text-slate-500 mb-1">能力掌握度雷达图</span>
    <span>完成对话后将动态更新您的能力状态</span>
  </div>
</template>
