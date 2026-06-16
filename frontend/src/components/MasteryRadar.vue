<script setup>
import { ref, onMounted, watch, nextTick } from 'vue'
import * as echarts from 'echarts'

const props = defineProps({
  initialData: { type: Object, default: () => ({}) },
  latestData: { type: Object, default: () => ({}) }
})

const chartRef = ref(null)
let chart = null

const indicators = [
  { name: '基础概念', max: 100, key: 'concept' },
  { name: '进阶理论', max: 100, key: 'theory' },
  { name: '实战应用', max: 100, key: 'practice' },
  { name: '逻辑推导', max: 100, key: 'logic' },
  { name: '测验表现', max: 100, key: 'quiz' }
]

function formatData(data) {
  // If data is empty, return defaults
  if (!data || Object.keys(data).length === 0) return [0, 0, 0, 0, 0]
  
  // Extract values based on indicators or use default 0
  return indicators.map(ind => {
    const val = data[ind.key] || data[ind.name] || 0
    return Math.round(val * 100)
  })
}

function initChart() {
  if (!chartRef.value) return
  chart = echarts.init(chartRef.value)
  updateChart()
}

function updateChart() {
  if (!chart) return

  const initialValues = formatData(props.initialData)
  const latestValues = formatData(props.latestData)

  const option = {
    backgroundColor: 'transparent',
    radar: {
      indicator: indicators,
      radius: '65%',
      splitNumber: 4,
      axisName: {
        color: '#64748b',
        fontSize: 10
      },
      splitLine: {
        lineStyle: {
          color: 'rgba(203, 213, 225, 0.4)'
        }
      },
      splitArea: {
        areaStyle: {
          color: ['rgba(248, 250, 252, 0.3)', 'rgba(241, 245, 249, 0.3)']
        }
      },
      axisLine: {
        lineStyle: {
          color: 'rgba(203, 213, 225, 0.4)'
        }
      }
    },
    series: [
      {
        type: 'radar',
        data: [
          {
            value: initialValues,
            name: '初始学情',
            symbol: 'none',
            itemStyle: { color: '#cbd5e1' },
            lineStyle: { width: 1, type: 'dashed' },
            areaStyle: { color: 'rgba(203, 213, 225, 0.2)' }
          },
          {
            value: latestValues,
            name: '最新学情',
            symbolSize: 4,
            itemStyle: { color: '#3b82f6' },
            lineStyle: { width: 2 },
            areaStyle: {
              color: new echarts.graphic.RadialGradient(0.5, 0.5, 1, [
                { offset: 0, color: 'rgba(59, 130, 246, 0.1)' },
                { offset: 1, color: 'rgba(59, 130, 246, 0.4)' }
              ])
            }
          }
        ],
        animationDuration: 1500,
        animationEasing: 'cubicOut'
      }
    ]
  }

  chart.setOption(option)
}

onMounted(() => {
  initChart()
  window.addEventListener('resize', () => chart?.resize())
})

watch(() => [props.initialData, props.latestData], () => {
  updateChart()
}, { deep: true })

</script>

<template>
  <div class="space-y-4">
    <div class="flex items-center gap-2 mb-2">
      <div class="w-1 h-4 bg-blue-600 rounded-full"></div>
      <h3 class="text-sm font-semibold text-gray-800">能力掌握度双圈图</h3>
    </div>
    
    <div class="card p-0 overflow-hidden bg-white/50 backdrop-blur-sm border-dashed">
      <div ref="chartRef" class="w-full h-56"></div>
      
      <div class="flex justify-center gap-6 pb-4 border-t border-gray-50 pt-3">
        <div class="flex items-center gap-1.5">
          <div class="w-2 h-2 rounded-full bg-gray-300"></div>
          <span class="text-[10px] text-gray-500 font-medium">初始学情</span>
        </div>
        <div class="flex items-center gap-1.5">
          <div class="w-2 h-2 rounded-full bg-blue-500 shadow-[0_0_8px_rgba(59,130,246,0.5)]"></div>
          <span class="text-[10px] text-blue-600 font-bold">最新学情</span>
        </div>
      </div>
    </div>
  </div>
</template>
