<script setup>
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import {
  CheckCircle2,
  ChevronDown,
  Clock3,
  History,
  Loader2,
  TrendingUp,
  X,
} from '@lucide/vue'
import { checkinReview, getCheckinHistory, getCheckinStreak } from '../api'
import { echarts } from '../lib/echarts-line'
import SearchField from './ui/SearchField.vue'

const props = defineProps({
  studentId: { type: String, default: '' },
  plans: { type: Array, default: () => [] },
})
const emit = defineEmits(['recorded'])

const checkinStreak = ref(0)
const streakLoading = ref(true)
const streakError = ref('')
const checkinLoading = ref(false)
const checkinFeedback = ref('')
const checkinDuration = ref(10)
const selectedConcept = ref('')
const conceptSearchQuery = ref('')
const isOpen = ref(false)
const dropdownRef = ref(null)
const searchInputRef = ref(null)
const showModal = ref(false)
const currentConcept = ref('')
const currentConceptLabel = ref('')
const historyData = ref([])
const modalLoading = ref(false)
const modalError = ref('')
const chartRef = ref(null)
let chartInstance = null

const filteredPlans = computed(() => {
  const query = conceptSearchQuery.value.trim().toLowerCase()
  if (!query) return props.plans
  return props.plans.filter(plan => String(plan.display_title || plan.concept || '').toLowerCase().includes(query))
})

const selectedPlan = computed(() => props.plans.find(plan => plan.concept === selectedConcept.value) || null)

function message(exception, fallback) {
  const detail = exception?.response?.data?.detail
  return detail?.message || (typeof detail === 'string' ? detail : '') || exception?.message || fallback
}

function selectConcept(plan) {
  selectedConcept.value = plan.concept
  isOpen.value = false
  conceptSearchQuery.value = ''
  checkinFeedback.value = ''
}

function handleClickOutside(event) {
  if (dropdownRef.value && !dropdownRef.value.contains(event.target)) isOpen.value = false
}

watch(isOpen, async open => {
  if (!open) return
  await nextTick()
  searchInputRef.value?.focus()
})

async function loadStreak() {
  if (!props.studentId) return
  streakLoading.value = true
  streakError.value = ''
  try {
    const result = await getCheckinStreak(props.studentId)
    checkinStreak.value = result?.streak || 0
  } catch (exception) {
    streakError.value = message(exception, '连续记录暂时无法读取。')
  } finally {
    streakLoading.value = false
  }
}

async function doCheckin() {
  if (!props.studentId || !selectedConcept.value || checkinLoading.value) return
  checkinLoading.value = true
  checkinFeedback.value = ''
  try {
    const result = await checkinReview(props.studentId, selectedConcept.value, checkinDuration.value)
    checkinStreak.value = result?.streak || checkinStreak.value
    checkinFeedback.value = '时长已保存。该记录不会直接改变掌握度。'
    emit('recorded')
  } catch (exception) {
    checkinFeedback.value = message(exception, '时长保存失败，当前选择和时长已保留。')
  } finally {
    checkinLoading.value = false
  }
}

async function openHistory() {
  if (!selectedConcept.value) return
  currentConcept.value = selectedConcept.value
  currentConceptLabel.value = selectedPlan.value?.display_title || selectedConcept.value
  showModal.value = true
  modalLoading.value = true
  modalError.value = ''
  historyData.value = []
  try {
    const data = await getCheckinHistory(props.studentId, selectedConcept.value)
    historyData.value = Array.isArray(data) ? data : []
    await nextTick()
    initChart()
  } catch (exception) {
    modalError.value = message(exception, '复习历史加载失败，请重试。')
  } finally {
    modalLoading.value = false
  }
}

function closeModal() {
  showModal.value = false
  chartInstance?.dispose()
  chartInstance = null
  window.removeEventListener('resize', resizeChart)
}

function resizeChart() {
  chartInstance?.resize()
}

function initChart() {
  if (!chartRef.value || !historyData.value.length) return
  chartInstance?.dispose()
  chartInstance = echarts.init(chartRef.value)
  const labels = historyData.value.map(log => new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(new Date(log.checkin_date)))
  chartInstance.setOption({
    tooltip: { trigger: 'axis', formatter: '{b}<br/>复习时长：<b>{c}</b> 分钟' },
    grid: { left: '4%', right: '4%', bottom: '14%', top: '12%', containLabel: true },
    xAxis: {
      type: 'category',
      data: labels,
      axisLine: { lineStyle: { color: '#ccd0cf' } },
      axisLabel: { color: '#4a5c6a', fontSize: 14, rotate: 15 },
    },
    yAxis: {
      type: 'value',
      name: '分钟',
      nameTextStyle: { color: '#4a5c6a', fontSize: 14 },
      axisLine: { show: false },
      splitLine: { lineStyle: { color: '#e7ecee' } },
      axisLabel: { color: '#4a5c6a', fontSize: 14 },
    },
    series: [{
      data: historyData.value.map(log => log.duration_minutes),
      type: 'line',
      smooth: true,
      symbol: 'circle',
      symbolSize: 7,
      itemStyle: { color: '#11212d' },
      lineStyle: { color: '#11212d', width: 2 },
      areaStyle: { color: 'rgba(17, 33, 45, 0.08)' },
    }],
  })
  window.addEventListener('resize', resizeChart)
}

onMounted(() => {
  document.addEventListener('click', handleClickOutside)
  loadStreak()
})
onUnmounted(() => {
  window.removeEventListener('resize', resizeChart)
  document.removeEventListener('click', handleClickOutside)
  chartInstance?.dispose()
})
</script>

<template>
  <section class="review-history" aria-labelledby="review-history-title">
    <header class="review-history__intro">
      <div>
        <h2 id="review-history-title">复习记录</h2>
        <p>保存真实复习时长，按知识点回看趋势与详细记录。</p>
      </div>
      <div class="review-history__streak" aria-label="连续记录天数">
        <Loader2 v-if="streakLoading" :size="18" class="review-history__spin" />
        <History v-else :size="18" />
        <span><strong>{{ streakLoading ? '—' : checkinStreak }}</strong> 天连续记录</span>
      </div>
    </header>

    <p v-if="streakError" class="review-history__message review-history__message--error" role="alert">
      {{ streakError }}
      <button type="button" @click="loadStreak">重试</button>
    </p>

    <div v-if="plans.length" class="review-history__form">
      <label class="review-history__concept">
        <span>知识点</span>
        <div ref="dropdownRef" class="review-history__select">
          <button
            type="button"
            class="review-history__trigger"
            :aria-expanded="isOpen"
            @click.stop="isOpen = !isOpen"
          >
            <span>{{ selectedPlan?.display_title || '选择要记录的知识点' }}</span>
            <ChevronDown :size="18" :class="{ 'is-open': isOpen }" />
          </button>
          <div v-if="isOpen" class="review-history__menu">
            <SearchField
              ref="searchInputRef"
              v-model="conceptSearchQuery"
              class="review-history__search"
              :bordered="false"
              aria-label="搜索知识点"
              placeholder="搜索知识点"
              @click.stop
              @keydown.esc="isOpen = false"
            />
            <div class="review-history__options">
              <button
                v-for="plan in filteredPlans"
                :key="plan.id || plan.concept"
                type="button"
                :class="{ 'is-selected': selectedConcept === plan.concept }"
                @click="selectConcept(plan)"
              >
                <span>{{ plan.display_title || plan.concept }}</span>
                <small>掌握度 {{ Math.round((plan.mastery || 0) * 100) }}%</small>
              </button>
              <p v-if="!filteredPlans.length">没有匹配的知识点</p>
            </div>
          </div>
        </div>
      </label>

      <label class="review-history__duration">
        <span>本次时长</span>
        <span><input v-model.number="checkinDuration" type="number" min="5" max="120" />分钟</span>
      </label>

      <div class="review-history__actions">
        <button type="button" class="ui-button ui-button--secondary" :disabled="!selectedConcept" @click="openHistory">
          <TrendingUp :size="17" />查看历史
        </button>
        <button type="button" class="ui-button ui-button--primary" :disabled="checkinLoading || !selectedConcept" @click="doCheckin">
          <Loader2 v-if="checkinLoading" :size="17" class="review-history__spin" />
          <CheckCircle2 v-else :size="17" />
          {{ checkinLoading ? '保存中' : '保存时长' }}
        </button>
      </div>
    </div>

    <div v-else class="review-history__empty">
      <Clock3 :size="28" />
      <strong>暂无可记录的复习计划</strong>
      <p>完成学习或在“计划”中添加知识点后，即可记录时长并查看趋势。</p>
    </div>

    <p v-if="checkinFeedback" class="review-history__message" role="status">{{ checkinFeedback }}</p>

    <div v-if="showModal" class="review-history__modal" role="dialog" aria-modal="true" aria-labelledby="review-history-modal-title">
      <div class="review-history__dialog">
        <header>
          <div>
            <TrendingUp :size="19" />
            <h2 id="review-history-modal-title">{{ currentConceptLabel }} · 复习历史</h2>
          </div>
          <button type="button" title="关闭" aria-label="关闭复习历史" @click="closeModal"><X :size="20" /></button>
        </header>
        <div class="review-history__dialog-body">
          <p v-if="modalError" class="review-history__message review-history__message--error" role="alert">{{ modalError }}</p>
          <section class="review-history__chart" aria-labelledby="review-history-chart-title">
            <h3 id="review-history-chart-title">复习时长趋势</h3>
            <div ref="chartRef" class="review-history__chart-canvas" />
            <div v-if="modalLoading" class="review-history__chart-state"><Loader2 :size="20" class="review-history__spin" />加载历史</div>
            <div v-else-if="!historyData.length" class="review-history__chart-state">暂无该知识点的时长记录</div>
          </section>
          <section class="review-history__log" aria-labelledby="review-history-log-title">
            <h3 id="review-history-log-title">详细记录</h3>
            <div v-if="historyData.length" class="review-history__table-wrap">
              <table>
                <thead><tr><th>日期</th><th>时长</th><th>复习内容</th></tr></thead>
                <tbody>
                  <tr v-for="log in historyData" :key="log.id">
                    <td>{{ new Date(log.checkin_date).toLocaleString('zh-CN') }}</td>
                    <td>{{ log.duration_minutes }} 分钟</td>
                    <td>{{ log.concepts_reviewed.join('、') }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
            <p v-else-if="!modalLoading" class="review-history__no-data">暂无详细记录</p>
          </section>
        </div>
        <footer><button type="button" class="ui-button ui-button--secondary" @click="closeModal">关闭</button></footer>
      </div>
    </div>
  </section>
</template>

<style scoped>
.review-history {
  color: var(--color-text);
  font-family: var(--font-sans);
}

.review-history__intro {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 24px;
  padding: 24px 26px 18px;
  border-bottom: 1px solid var(--color-border);
}

.review-history__intro h2,
.review-history__dialog h2,
.review-history__dialog h3 {
  margin: 0;
  color: var(--color-text);
  font-size: 17px;
  font-weight: 700;
}

.review-history__intro p {
  margin: 4px 0 0;
  color: var(--color-text-secondary);
  font-size: 14px;
}

.review-history__streak {
  display: flex;
  min-height: 42px;
  align-items: center;
  gap: 9px;
  padding: 0 12px;
  color: var(--color-text-secondary);
  border: 1px solid var(--color-border);
  border-radius: 7px;
  background: var(--color-surface-subtle);
  font-size: 14px;
  white-space: nowrap;
}

.review-history__streak strong {
  color: var(--color-text);
  font-size: 18px;
  font-variant-numeric: tabular-nums;
}

.review-history__form {
  display: grid;
  grid-template-columns: minmax(320px, 1fr) 150px auto;
  align-items: end;
  gap: 14px;
  padding: 24px 26px;
}

.review-history__concept,
.review-history__duration {
  display: grid;
  gap: 7px;
  color: var(--color-text-secondary);
  font-size: 14px;
}

.review-history__select { position: relative; }

.review-history__trigger {
  display: flex;
  width: 100%;
  min-height: 42px;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 0 12px;
  color: var(--color-text);
  border: 1px solid var(--color-border-strong);
  border-radius: 6px;
  background: var(--color-surface);
  font-size: 14px;
  text-align: left;
  cursor: pointer;
}

.review-history__trigger svg { transition: transform 150ms ease; }
.review-history__trigger svg.is-open { transform: rotate(180deg); }

.review-history__menu {
  position: absolute;
  z-index: 20;
  top: calc(100% + 6px);
  right: 0;
  left: 0;
  padding: 8px;
  border: 1px solid var(--color-border);
  border-radius: 8px;
  background: var(--color-surface);
  box-shadow: var(--shadow-popover);
}

.review-history__search { min-height: 42px; }
.review-history__options { max-height: 240px; margin-top: 7px; overflow-y: auto; }

.review-history__options button {
  display: flex;
  width: 100%;
  min-height: 44px;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  padding: 8px 10px;
  color: var(--color-text-secondary);
  border: 0;
  border-radius: 5px;
  background: transparent;
  font-size: 14px;
  text-align: left;
  cursor: pointer;
}

.review-history__options button:hover,
.review-history__options button.is-selected { color: var(--color-text); background: var(--color-surface-subtle); }
.review-history__options small { color: var(--color-text-muted); font-size: 14px; }
.review-history__options p { margin: 0; padding: 16px; color: var(--color-text-muted); font-size: 14px; text-align: center; }

.review-history__duration > span:last-child {
  display: flex;
  min-height: 42px;
  align-items: center;
  gap: 8px;
}

.review-history__duration input {
  width: 104px;
  min-height: 42px;
  padding: 0 10px;
  font-size: 14px;
}

.review-history__actions { display: flex; gap: 8px; }
.review-history__actions .ui-button { min-height: 42px; white-space: nowrap; }

.review-history__message {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin: 0 26px 20px;
  padding: 10px 12px;
  color: var(--color-text-secondary);
  border: 1px solid var(--color-border);
  border-radius: 6px;
  background: var(--color-surface-subtle);
  font-size: 14px;
}

.review-history__message--error {
  color: var(--color-danger);
  border-color: #e8caca;
  background: var(--color-danger-soft);
}

.review-history__message button {
  color: currentColor;
  border: 0;
  background: transparent;
  font-size: 14px;
  font-weight: 700;
  cursor: pointer;
}

.review-history__empty {
  display: flex;
  min-height: 260px;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 32px;
  color: var(--color-text-muted);
  text-align: center;
}

.review-history__empty strong { margin-top: 10px; color: var(--color-text); font-size: 16px; }
.review-history__empty p { max-width: 48ch; margin: 5px 0 0; font-size: 14px; line-height: 1.6; }

.review-history__modal {
  position: fixed;
  z-index: 60;
  inset: 0;
  display: grid;
  place-items: center;
  padding: 24px;
  background: rgb(6 20 27 / 32%);
}

.review-history__dialog {
  display: flex;
  width: min(780px, calc(100vw - 48px));
  max-height: calc(100vh - 48px);
  flex-direction: column;
  overflow: hidden;
  border-radius: 8px;
  background: var(--color-surface);
  box-shadow: var(--shadow-popover);
}

.review-history__dialog > header,
.review-history__dialog > footer {
  display: flex;
  min-height: 58px;
  flex: 0 0 auto;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 10px 20px;
  border-bottom: 1px solid var(--color-border);
}

.review-history__dialog > header > div { display: flex; align-items: center; gap: 9px; }
.review-history__dialog > header button { display: grid; width: 36px; height: 36px; place-items: center; color: var(--color-text-muted); border: 0; border-radius: 6px; background: transparent; cursor: pointer; }
.review-history__dialog > footer { justify-content: flex-end; border-top: 1px solid var(--color-border); border-bottom: 0; background: var(--color-surface-subtle); }
.review-history__dialog-body { min-height: 0; padding: 20px; overflow-y: auto; }
.review-history__dialog-body > .review-history__message { margin: 0 0 16px; }

.review-history__chart { position: relative; }
.review-history__chart h3,
.review-history__log h3 { font-size: 16px; }
.review-history__chart-canvas { width: 100%; height: 280px; margin-top: 10px; }
.review-history__chart-state { position: absolute; inset: 44px 0 0; display: flex; align-items: center; justify-content: center; gap: 8px; color: var(--color-text-muted); background: rgb(255 255 255 / 90%); font-size: 14px; }
.review-history__log { margin-top: 22px; }
.review-history__table-wrap { margin-top: 10px; overflow: auto; border: 1px solid var(--color-border); border-radius: 7px; }
.review-history__table-wrap table { width: 100%; border-collapse: collapse; font-size: 14px; }
.review-history__table-wrap th,
.review-history__table-wrap td { padding: 11px 13px; border-bottom: 1px solid var(--color-border); text-align: left; }
.review-history__table-wrap th { color: var(--color-text-secondary); background: var(--color-surface-subtle); }
.review-history__table-wrap tbody tr:last-child td { border-bottom: 0; }
.review-history__no-data { margin: 0; padding: 24px; color: var(--color-text-muted); font-size: 14px; text-align: center; }
.review-history__spin { animation: review-history-spin 900ms linear infinite; }

@keyframes review-history-spin { to { transform: rotate(360deg); } }

@media (max-width: 1080px) {
  .review-history__form { grid-template-columns: minmax(280px, 1fr) 140px; }
  .review-history__actions { grid-column: 1 / -1; justify-content: flex-end; }
}
</style>
