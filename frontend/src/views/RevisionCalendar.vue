<script setup>
import { ref, onMounted, onUnmounted, computed, nextTick, watch } from 'vue'
import { getReviewPlans, checkinReview, getCheckinStreak, getCheckinHistory, deleteReviewPlan } from '../api'
import { Calendar, CheckCircle2, Clock, TrendingUp, Flame, BookOpen, Loader2, XCircle, ChevronDown, Search, Trash2 } from '@lucide/vue'
import * as echarts from 'echarts'

const props = defineProps({ studentId: String })

const reviewPlans = ref([])
const checkinStreak = ref(0)
const loading = ref(true)
const checkinLoading = ref(false)
const checkedIn = ref(false)
const checkinDuration = ref(10)
const selectedConcept = ref('')

const conceptSearchQuery = ref('')
const isOpen = ref(false)
const dropdownRef = ref(null)
const searchInputRef = ref(null)

const filteredReviewPlansForSelect = computed(() => {
  if (!conceptSearchQuery.value) return reviewPlans.value
  const q = conceptSearchQuery.value.trim().toLowerCase()
  return reviewPlans.value.filter(p => p.concept.toLowerCase().includes(q))
})

function selectConcept(concept) {
  selectedConcept.value = concept
  isOpen.value = false
}

function handleClickOutside(event) {
  if (dropdownRef.value && !dropdownRef.value.contains(event.target)) {
    isOpen.value = false
  }
}

watch(isOpen, async (newVal) => {
  if (newVal) {
    await nextTick()
    searchInputRef.value?.focus()
  }
})

// Modal States
const showModal = ref(false)
const currentConcept = ref('')
const historyData = ref([])
const modalLoading = ref(false)
const chartRef = ref(null)
let chartInstance = null

function _handleResize() {
  chartInstance?.resize()
}

// Group by priority
const urgentReviews = computed(() =>
  reviewPlans.value
    .filter(p => (p.mastery ?? 0) < 0.5)
    .slice(0, 10)
)

const upcomingReviews = computed(() =>
  reviewPlans.value
    .filter(p => !urgentReviews.value.includes(p))
    .slice(0, 10)
)

async function loadData() {
  loading.value = true
  try {
    const [plans, streakData] = await Promise.all([
      getReviewPlans(props.studentId).catch(() => []),
      getCheckinStreak(props.studentId).catch(() => ({ streak: 0 })),
    ])
    reviewPlans.value = plans || []
    checkinStreak.value = streakData.streak || 0
  } catch (e) {
    console.error('加载复习日历失败:', e)
  } finally {
    loading.value = false
  }
}

async function doCheckin() {
  if (!selectedConcept.value) return
  checkinLoading.value = true
  try {
    const result = await checkinReview(props.studentId, selectedConcept.value, checkinDuration.value)
    checkedIn.value = true
    checkinStreak.value = result.streak || checkinStreak.value
    setTimeout(() => { checkedIn.value = false }, 3000)
    selectedConcept.value = ''
    conceptSearchQuery.value = ''
    await loadData()
  } catch (e) {
    console.error('打卡失败:', e)
  } finally {
    checkinLoading.value = false
  }
}

async function removePlan(planId) {
  if (!confirm('确定要删除该复习计划吗？')) return
  try {
    await deleteReviewPlan(planId)
    await loadData()
  } catch (e) {
    console.error('删除复习计划失败:', e)
  }
}


function getMasteryColor(m) {
  if (m >= 0.8) return 'bg-emerald-500'
  if (m >= 0.5) return 'bg-amber-500'
  return 'bg-red-500'
}

async function openHistoryModal(concept) {
  currentConcept.value = concept
  showModal.value = true
  modalLoading.value = true
  historyData.value = []
  
  try {
    const data = await getCheckinHistory(props.studentId, concept)
    historyData.value = Array.isArray(data) ? data : []
    
    await nextTick()
    initChart()
  } catch (e) {
    console.error('获取打卡历史失败:', e)
  } finally {
    modalLoading.value = false
  }
}

function closeModal() {
  showModal.value = false
  if (chartInstance) {
    chartInstance.dispose()
    chartInstance = null
  }
  window.removeEventListener('resize', _handleResize)
}

function initChart() {
  if (!chartRef.value || historyData.value.length === 0) return
  if (chartInstance) {
    chartInstance.dispose()
    chartInstance = null
  }
  chartInstance = echarts.init(chartRef.value)
  
  const xAxisData = historyData.value.map(log => {
    const d = new Date(log.checkin_date)
    const month = String(d.getMonth() + 1).padStart(2, '0')
    const date = String(d.getDate()).padStart(2, '0')
    const hours = String(d.getHours()).padStart(2, '0')
    const minutes = String(d.getMinutes()).padStart(2, '0')
    return `${month}-${date} ${hours}:${minutes}`
  })
  
  const yAxisData = historyData.value.map(log => log.duration_minutes)
  
  const option = {
    tooltip: {
      trigger: 'axis',
      formatter: '{b}<br/>复习时长: <b style="color:#3b82f6">{c}</b> 分钟',
    },
    grid: {
      left: '4%',
      right: '4%',
      bottom: '12%',
      top: '10%',
      containLabel: true
    },
    xAxis: {
      type: 'category',
      data: xAxisData,
      axisLine: { lineStyle: { color: 'rgba(148, 163, 184, 0.2)' } },
      axisLabel: { color: '#64748b', fontSize: 10, rotate: 15 }
    },
    yAxis: {
      type: 'value',
      name: '分钟',
      nameTextStyle: { color: '#64748b', fontSize: 10 },
      axisLine: { show: false },
      splitLine: { lineStyle: { color: 'rgba(148, 163, 184, 0.1)' } },
      axisLabel: { color: '#64748b', fontSize: 10 }
    },
    series: [
      {
        data: yAxisData,
        type: 'line',
        smooth: true,
        symbol: 'circle',
        symbolSize: 8,
        itemStyle: { color: '#3b82f6' },
        lineStyle: { color: '#3b82f6', width: 3 },
        areaStyle: { color: 'rgba(59, 130, 246, 0.1)' }
      }
    ]
  }
  
  chartInstance.setOption(option)
  window.addEventListener('resize', _handleResize)
}

onMounted(() => {
  loadData()
  document.addEventListener('click', handleClickOutside)
})

onUnmounted(() => {
  window.removeEventListener('resize', _handleResize)
  if (chartInstance) {
    chartInstance.dispose()
    chartInstance = null
  }
  document.removeEventListener('click', handleClickOutside)
})
</script>

<template>
  <div class="space-y-6 max-w-4xl">
    <!-- Header -->
    <div class="flex items-center gap-3">
      <Calendar :size="24" class="text-blue-500" />
      <div>
        <h2 class="text-lg font-semibold text-gray-800">抗遗忘复习日历</h2>
        <p class="text-xs text-gray-400 mt-0.5">基于艾宾浩斯遗忘曲线的个性化复习计划</p>
      </div>
    </div>

    <!-- Streak & Check-in Card -->
    <div class="grid grid-cols-1 md:grid-cols-3 gap-4">
      <div class="card flex items-center gap-4">
        <div class="w-12 h-12 rounded-xl bg-orange-50 flex items-center justify-center">
          <Flame :size="24" class="text-orange-500" />
        </div>
        <div>
          <p class="text-2xl font-bold text-gray-800">{{ checkinStreak }}</p>
          <p class="text-xs text-gray-500">连续打卡天数</p>
        </div>
      </div>

      <div class="card flex items-center gap-4">
        <div class="w-12 h-12 rounded-xl bg-blue-50 flex items-center justify-center">
          <TrendingUp :size="24" class="text-blue-500" />
        </div>
        <div>
          <p class="text-2xl font-bold text-gray-800">{{ urgentReviews.length }}</p>
          <p class="text-xs text-gray-500">紧急复习项</p>
        </div>
      </div>

      <div class="card flex items-center gap-4">
        <div class="w-12 h-12 rounded-xl bg-emerald-50 flex items-center justify-center">
          <BookOpen :size="24" class="text-emerald-500" />
        </div>
        <div>
          <p class="text-2xl font-bold text-gray-800">{{ reviewPlans.length }}</p>
          <p class="text-xs text-gray-500">总复习计划</p>
        </div>
      </div>
    </div>

    <!-- Check-in Form -->
    <div class="card">
      <h3 class="text-sm font-semibold text-gray-800 mb-3 flex items-center gap-2">
        <CheckCircle2 :size="16" class="text-emerald-500" />
        今日打卡签到
      </h3>
      <div class="flex flex-wrap items-end gap-3">
        <div class="flex-1 min-w-[320px]">
          <label class="text-xs text-gray-500 mb-1 block">搜索并选择复习计划知识点 (一次只能打卡一项)</label>
          <div ref="dropdownRef" class="relative w-full">
            <!-- Trigger Button -->
            <button
              type="button"
              @click="isOpen = !isOpen"
              class="input text-left flex justify-between items-center bg-white cursor-pointer select-none text-sm pr-3"
              :class="{ 'border-blue-500 ring-2 ring-blue-100': isOpen }"
            >
              <span v-if="selectedConcept" class="text-gray-800 font-medium">
                {{ selectedConcept }} (掌握度 {{ ((reviewPlans.find(p => p.concept === selectedConcept)?.mastery || 0) * 100).toFixed(0) }}%)
              </span>
              <span v-else class="text-gray-400">-- 请选择并搜索打卡知识点 --</span>
              <ChevronDown :size="16" class="text-gray-400 transition-transform duration-200" :class="{ 'rotate-180': isOpen }" />
            </button>

            <!-- Dropdown Menu -->
            <div
              v-if="isOpen"
              class="absolute left-0 right-0 mt-1.5 bg-white border border-gray-200 rounded-xl shadow-xl z-50 p-2 space-y-2 h-[300px] max-h-[70vh] flex flex-col animate-in fade-in slide-in-from-top-2 duration-150"
            >
              <!-- Search box inside dropdown -->
              <div class="relative">
                <Search :size="14" class="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
                <input
                  ref="searchInputRef"
                  v-model="conceptSearchQuery"
                  type="text"
                  class="input text-sm pl-8 py-1.5 focus:border-blue-500"
                  placeholder="输入关键字搜索知识点..."
                  @click.stop
                  @keydown.esc="isOpen = false"
                />
              </div>

              <!-- Options List -->
              <div class="overflow-y-auto flex-1 min-h-0 divide-y divide-gray-50 scrollbar-thin">
                <button
                  v-for="plan in filteredReviewPlansForSelect"
                  :key="plan.concept"
                  type="button"
                  class="w-full text-left px-3 py-2.5 text-sm rounded-lg hover:bg-blue-50 hover:text-blue-600 transition-colors flex items-center justify-between"
                  :class="{ 'bg-blue-50 text-blue-600 font-medium': selectedConcept === plan.concept }"
                  @click="selectConcept(plan.concept)"
                >
                  <span>{{ plan.concept }}</span>
                  <span class="text-xs text-gray-400 font-normal">掌握度 {{ ((plan.mastery || 0) * 100).toFixed(0) }}%</span>
                </button>
                <div v-if="filteredReviewPlansForSelect.length === 0" class="text-center py-6 text-xs text-gray-400">
                  未找到匹配的知识点
                </div>
              </div>
            </div>
          </div>
        </div>
        <div class="w-32 shrink-0">
          <label class="text-xs text-gray-500 mb-1 block">复习时长（分钟）</label>
          <input
            v-model.number="checkinDuration"
            type="number"
            min="5"
            max="120"
            class="input text-sm"
          />
        </div>
        <button
          class="btn btn-primary text-sm shrink-0"
          :disabled="checkinLoading || checkedIn || !selectedConcept"
          @click="doCheckin"
        >
          <Loader2 v-if="checkinLoading" :size="14" class="animate-spin" />
          <CheckCircle2 v-else-if="checkedIn" :size="14" />
          <Clock v-else :size="14" />
          {{ checkedIn ? '已打卡' : '签到' }}
        </button>
      </div>
      <p v-if="checkedIn" class="text-xs text-emerald-600 mt-2">🎉 打卡成功！继续保持！</p>
    </div>

    <!-- Loading -->
    <div v-if="loading" class="flex items-center justify-center py-12">
      <div class="pulse-dot" />
      <span class="ml-3 text-gray-400 text-sm">加载复习计划...</span>
    </div>

    <!-- No Data -->
    <div v-else-if="reviewPlans.length === 0" class="card text-center py-12">
      <Calendar :size="32" class="mx-auto text-gray-300 mb-3" />
      <p class="text-sm text-gray-500">暂无复习计划</p>
      <p class="text-xs text-gray-400 mt-1">完成学习和测验后，复习计划将自动生成</p>
    </div>

    <!-- Review Lists -->
    <div v-else class="space-y-6">
      <!-- Urgent Reviews -->
      <div v-if="urgentReviews.length > 0">
        <h3 class="text-sm font-semibold text-red-600 mb-3 flex items-center gap-2">
          <Clock :size="16" />
          紧急复习（掌握度低于 50%）
        </h3>
        <div class="space-y-2">
          <div
            v-for="plan in urgentReviews"
            :key="plan.id || plan.concept"
            class="card flex items-center gap-4 cursor-pointer hover:border-blue-300 hover:shadow-sm active:scale-[0.99] transition-all"
            @click="openHistoryModal(plan.concept)"
          >
            <div class="flex-1 min-w-0">
              <div class="flex items-center gap-2">
                <p class="text-sm font-medium text-gray-800">{{ plan.concept }}</p>
                <span class="text-[10px] px-2 py-0.5 rounded-full bg-red-50 text-red-600 font-medium">
                  紧急
                </span>
              </div>
              <div class="mt-2 flex items-center gap-2">
                <div class="flex-1 h-1.5 bg-gray-100 rounded-full overflow-hidden">
                  <div
                    class="h-full rounded-full transition-all"
                    :class="getMasteryColor(plan.mastery)"
                    :style="{ width: ((plan.mastery || 0) * 100) + '%' }"
                  />
                </div>
                <span class="text-xs text-gray-500 w-10 text-right">{{ ((plan.mastery || 0) * 100).toFixed(0) }}%</span>
              </div>
              <p v-if="plan.next_review_at" class="text-[10px] text-gray-400 mt-1">
                下次复习: {{ new Date(plan.next_review_at).toLocaleDateString() }}
              </p>
            </div>
            <button
              type="button"
              class="p-1.5 rounded-lg border border-red-100 text-red-500 hover:bg-red-50 hover:border-red-200 transition-colors shrink-0"
              title="删除复习计划"
              @click.stop="removePlan(plan.id)"
            >
              <Trash2 :size="13" />
            </button>
          </div>
        </div>
      </div>

      <!-- Upcoming Reviews -->
      <div v-if="upcomingReviews.length > 0">
        <h3 class="text-sm font-semibold text-gray-800 mb-3">其他复习计划</h3>
        <div class="space-y-2">
          <div
            v-for="plan in upcomingReviews"
            :key="plan.id || plan.concept"
            class="card flex items-center gap-4 cursor-pointer hover:border-blue-300 hover:shadow-sm active:scale-[0.99] transition-all"
            @click="openHistoryModal(plan.concept)"
          >
            <div class="flex-1 min-w-0">
              <p class="text-sm font-medium text-gray-800">{{ plan.concept }}</p>
              <div class="mt-2 flex items-center gap-2">
                <div class="flex-1 h-1.5 bg-gray-100 rounded-full overflow-hidden">
                  <div
                    class="h-full rounded-full transition-all"
                    :class="getMasteryColor(plan.mastery)"
                    :style="{ width: ((plan.mastery || 0) * 100) + '%' }"
                  />
                </div>
                <span class="text-xs text-gray-500 w-10 text-right">{{ ((plan.mastery || 0) * 100).toFixed(0) }}%</span>
              </div>
              <p v-if="plan.next_review_at" class="text-[10px] text-gray-400 mt-1">
                下次复习: {{ new Date(plan.next_review_at).toLocaleDateString() }}
              </p>
            </div>
            <button
              type="button"
              class="p-1.5 rounded-lg border border-red-100 text-red-500 hover:bg-red-50 hover:border-red-200 transition-colors shrink-0"
              title="删除复习计划"
              @click.stop="removePlan(plan.id)"
            >
              <Trash2 :size="13" />
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- History Modal -->
    <div v-if="showModal" class="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/40 backdrop-blur-sm">
      <div class="bg-white rounded-2xl w-full max-w-2xl shadow-xl border border-slate-100 flex flex-col max-h-[90vh] overflow-hidden animate-in fade-in zoom-in-95 duration-200">
        <!-- Modal Header -->
        <div class="flex items-center justify-between px-6 py-4 border-b border-slate-100 shrink-0">
          <div class="flex items-center gap-2">
            <TrendingUp :size="18" class="text-blue-500" />
            <h3 class="text-sm font-semibold text-slate-800">
              <span class="text-blue-600">[{{ currentConcept }}]</span> 复习历史打卡曲线
            </h3>
          </div>
          <button @click="closeModal" class="text-slate-400 hover:text-slate-600 transition-colors p-1 hover:bg-slate-50 rounded-lg">
            <XCircle :size="20" />
          </button>
        </div>

        <!-- Modal Body -->
        <div class="p-6 space-y-4 overflow-y-auto flex-1">
          <!-- Chart Container -->
          <div class="relative bg-slate-50/50 rounded-xl border border-slate-100 p-4">
            <h4 class="text-xs font-medium text-slate-500 mb-2 flex items-center gap-1.5">
              <Clock :size="12" />
              <span>复习时长趋势图 (分钟)</span>
            </h4>
            <div ref="chartRef" class="w-full h-64 min-h-[250px]" />
            <!-- Loading overlay inside chart -->
            <div v-if="modalLoading" class="absolute inset-0 bg-white/60 flex items-center justify-center">
              <Loader2 :size="24" class="text-blue-500 animate-spin" />
            </div>
            <!-- Empty state inside chart -->
            <div v-else-if="historyData.length === 0" class="absolute inset-0 bg-slate-50/50 flex flex-col items-center justify-center text-slate-400 text-xs p-4 text-center">
              <Flame :size="24" class="text-slate-300 mb-2 animate-pulse" />
              <span>暂无该知识点的复习打卡时长记录</span>
              <span class="text-[10px] text-slate-400 mt-0.5">今天打卡签到此概念后即可在此显示</span>
            </div>
          </div>

          <!-- History Logs List -->
          <div>
            <h4 class="text-xs font-semibold text-slate-700 mb-2 flex items-center gap-1.5">
              <Calendar :size="14" class="text-slate-500" />
              <span>详细打卡记录</span>
            </h4>
            
            <div v-if="modalLoading" class="flex items-center justify-center py-8">
              <Loader2 :size="20" class="text-blue-500 animate-spin" />
              <span class="ml-2 text-xs text-slate-400">加载打卡日志...</span>
            </div>
            
            <div v-else-if="historyData.length === 0" class="card text-center py-6 border-dashed bg-slate-50/30 text-slate-400 text-xs">
              暂无打卡日志
            </div>
            
            <div v-else class="border border-slate-100 rounded-xl overflow-hidden bg-white max-h-48 overflow-y-auto">
              <table class="w-full border-collapse text-left text-xs">
                <thead>
                  <tr class="bg-slate-50 border-b border-slate-100 text-slate-500 font-semibold">
                    <th class="px-4 py-2">打卡日期 (UTC)</th>
                    <th class="px-4 py-2 text-right">复习时长 (分钟)</th>
                    <th class="px-4 py-2">所关联的复习概念</th>
                  </tr>
                </thead>
                <tbody class="divide-y divide-slate-50 text-slate-700">
                  <tr v-for="log in historyData" :key="log.id" class="hover:bg-slate-50/50 transition-colors">
                    <td class="px-4 py-2">{{ new Date(log.checkin_date).toLocaleString() }}</td>
                    <td class="px-4 py-2 text-right font-medium text-blue-600">{{ log.duration_minutes }} 分钟</td>
                    <td class="px-4 py-2 text-slate-500 truncate max-w-[200px]" :title="log.concepts_reviewed.join(', ')">
                      {{ log.concepts_reviewed.join(', ') }}
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        </div>

        <!-- Modal Footer -->
        <div class="px-6 py-3 border-t border-slate-100 bg-slate-50 flex justify-end shrink-0">
          <button @click="closeModal" class="btn btn-outline text-xs py-1.5 px-4">关闭</button>
        </div>
      </div>
    </div>
  </div>
</template>
