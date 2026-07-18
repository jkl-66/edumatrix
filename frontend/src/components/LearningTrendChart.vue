<script setup>
import { onMounted, onUnmounted, ref, watch } from 'vue'
import * as echarts from 'echarts'

const props = defineProps({ values: { type: Array, default: () => [] } })
const chartEl = ref(null)
let chart

function renderChart() {
  if (!chartEl.value) return
  chart ||= echarts.init(chartEl.value)
  const values = props.values.length ? props.values : [24, 31, 38, 44, 52, 58, 66]
  chart.setOption({
    animationDuration: 900,
    grid: { left: 8, right: 8, top: 16, bottom: 8, containLabel: true },
    tooltip: { trigger: 'axis', borderWidth: 0, backgroundColor: '#172033', textStyle: { color: '#fff', fontSize: 11 } },
    xAxis: { type: 'category', boundaryGap: false, data: ['周一', '周二', '周三', '周四', '周五', '周六', '今天'], axisLine: { show: false }, axisTick: { show: false }, axisLabel: { color: '#9aa3b2', fontSize: 10, margin: 14 } },
    yAxis: { type: 'value', min: 0, max: 100, splitNumber: 4, axisLabel: { show: false }, axisLine: { show: false }, splitLine: { lineStyle: { color: 'rgba(148, 163, 184, 0.13)' } } },
    series: [{
      type: 'line', smooth: 0.42, symbol: 'circle', symbolSize: 7, data: values,
      lineStyle: { width: 3, color: '#66736a' }, itemStyle: { color: '#fff', borderColor: '#66736a', borderWidth: 2 },
      areaStyle: { color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [{ offset: 0, color: 'rgba(102,115,106,.22)' }, { offset: 1, color: 'rgba(102,115,106,0)' }]) },
    }],
  })
}

function resize() { chart?.resize() }
onMounted(() => { renderChart(); window.addEventListener('resize', resize) })
watch(() => props.values, renderChart, { deep: true })
onUnmounted(() => { window.removeEventListener('resize', resize); chart?.dispose() })
</script>

<template><div ref="chartEl" class="learning-trend-chart" /></template>

