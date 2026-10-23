<script setup>
import { onMounted, onUnmounted, ref, watch } from 'vue'
import { echarts } from '../lib/echarts-line'

const props = defineProps({ points: { type: Array, default: () => [] } })
const chartEl = ref(null)
let chart

function renderChart() {
  if (!chartEl.value || !props.points.length) {
    chart?.clear()
    return
  }
  chart ||= echarts.init(chartEl.value)
  chart.setOption({
    animationDuration: 300,
    grid: { left: 8, right: 12, top: 18, bottom: 8, containLabel: true },
    tooltip: {
      trigger: 'axis',
      borderWidth: 0,
      backgroundColor: '#11212d',
      textStyle: { color: '#ffffff', fontSize: 14 },
    },
    xAxis: {
      type: 'category',
      boundaryGap: false,
      data: props.points.map(item => item.label),
      axisLine: { lineStyle: { color: '#ccd0cf' } },
      axisTick: { show: false },
      axisLabel: { color: '#60727c', fontSize: 14, margin: 12 },
    },
    yAxis: {
      type: 'value',
      min: 0,
      max: 100,
      splitNumber: 4,
      axisLabel: { color: '#60727c', fontSize: 14, formatter: '{value}%' },
      axisLine: { show: false },
      splitLine: { lineStyle: { color: '#dce2e3', type: 'dashed' } },
    },
    series: [{
      type: 'line',
      smooth: 0.2,
      symbol: 'circle',
      symbolSize: 7,
      data: props.points.map(item => item.value),
      lineStyle: { width: 2, color: '#253745' },
      itemStyle: { color: '#ffffff', borderColor: '#253745', borderWidth: 2 },
    }],
  }, true)
}

function resize() { chart?.resize() }

onMounted(() => {
  renderChart()
  window.addEventListener('resize', resize)
})
watch(() => props.points, renderChart, { deep: true })
onUnmounted(() => {
  window.removeEventListener('resize', resize)
  chart?.dispose()
})
</script>

<template>
  <div
    v-if="points.length"
    ref="chartEl"
    class="learning-trend-chart"
    role="img"
    aria-label="有效学习事件形成的掌握变化折线图"
  />
  <div v-else class="learning-trend-chart learning-trend-chart--empty">
    暂无可用于趋势计算的已处理学习证据。
  </div>
</template>

<style scoped>
.learning-trend-chart {
  width: 100%;
  height: 224px;
}

.learning-trend-chart--empty {
  display: grid;
  place-items: center;
  color: var(--color-text-muted);
  border-block: 1px solid var(--color-border);
  font-size: 14px;
  line-height: 1.6;
  text-align: center;
}
</style>
