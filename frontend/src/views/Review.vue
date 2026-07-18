<script setup>
import { ref, onMounted, onUnmounted, nextTick } from 'vue'
import { getReviewPlans, createReviewPlan, reviewFlashcard } from '../api'
import { Calendar, Plus, CheckCircle2, Clock, Brain } from '@lucide/vue'
import CollapsibleMindmap from '../components/CollapsibleMindmap.vue'

const props = defineProps({ studentId: String })

const reviews = ref([])
const loading = ref(true)
const showForm = ref(false)
const form = ref({ concept: '', mastery: 0.5, interval_days: 3 })
const actionFeedback = ref('')
const reviewingKey = ref('')
const adaptiveReview = ref(null)
const morphText = ref('')
const morphTrace = ref([])
const morphing = ref(false)
let morphTimers = []

const qualityActions = [
  { quality: 2, label: '困难', tone: 'border-red-200 text-red-600 hover:bg-red-50' },
  { quality: 4, label: '一般', tone: 'border-amber-200 text-amber-600 hover:bg-amber-50' },
  { quality: 5, label: '简单', tone: 'border-emerald-200 text-emerald-600 hover:bg-emerald-50' },
]

function setAction(fb) {
  actionFeedback.value = fb
  setTimeout(() => actionFeedback.value = '', 3000)
}

function clearMorphTimers() {
  morphTimers.forEach(timer => clearTimeout(timer))
  morphTimers = []
}

function playAdaptiveReview(payload) {
  clearMorphTimers()
  adaptiveReview.value = payload
  morphText.value = ''
  morphTrace.value = []
  morphing.value = true

  const explanation = payload?.simplified_explanation || ''
  const chunks = []
  for (let i = 0; i < explanation.length; i += 28) {
    chunks.push(explanation.slice(i, i + 28))
  }

  chunks.forEach((chunk, index) => {
    const timer = setTimeout(() => {
      morphText.value += chunk
      if (index === chunks.length - 1) {
        morphing.value = false
      }
    }, index * 90)
    morphTimers.push(timer)
  })
  
  if (chunks.length === 0) {
    morphing.value = false
  }

  ;(payload?.agent_trace || []).forEach((line, index) => {
    const timer = setTimeout(() => {
      morphTrace.value.push(line)
    }, 220 + chunks.length * 90 + index * 130)
    morphTimers.push(timer)
  })
}

async function load() {
  loading.value = true
  try {
    const data = await getReviewPlans(props.studentId)
    reviews.value = Array.isArray(data) ? data : []
  } catch (e) {
    console.error(e)
  } finally {
    loading.value = false
  }
}

async function addPlan() {
  if (!form.value.concept.trim()) return
  try {
    await createReviewPlan(props.studentId, {
      concept: form.value.concept,
      mastery: form.value.mastery,
      interval_days: form.value.interval_days,
    })
    form.value = { concept: '', mastery: 0.5, interval_days: 3 }
    showForm.value = false
    setAction('✅ 复习计划已创建')
    await load()
  } catch (e) {
    setAction(`❌ 创建失败: ${e.message}`)
  }
}

async function submitReview(plan, quality) {
  if (!plan?.concept) return
  const key = `${plan.id || plan.concept}:${quality}`
  reviewingKey.value = key
  try {
    const result = await reviewFlashcard(props.studentId, plan.concept, quality)
    const interval = result?.review_plan?.interval_days || result?.interval_new || '-'
    if (result?.adaptive_review?.triggered) {
      playAdaptiveReview(result.adaptive_review)
    } else {
      adaptiveReview.value = null
      morphText.value = ''
      morphTrace.value = []
    }
    setAction(`复习反馈已记录，下次间隔 ${interval} 天`)
    await load()
  } catch (e) {
    setAction(`反馈提交失败: ${e.response?.data?.detail || e.message}`)
  } finally {
    reviewingKey.value = ''
  }
}

const intervals = [1, 3, 7, 14, 30]

function masteryColor(m) {
  if (m >= 0.7) return 'text-emerald-600'
  if (m >= 0.4) return 'text-amber-600'
  return 'text-red-600'
}

function nextReviewDate(plan) {
  if (!plan.next_review_at) return '待安排'
  return new Date(plan.next_review_at).toLocaleDateString('zh-CN')
}

function dueText(plan) {
  if (plan.is_due) return '今日到期'
  if (plan.days_until_due == null) return '待安排'
  return `${plan.days_until_due}天后到期`
}

function statusClass(plan) {
  return plan.is_due ? 'bg-red-50 text-red-700' : 'bg-blue-50 text-blue-700'
}

function easinessText(plan) {
  return Number(plan.easiness_factor || 2.5).toFixed(2)
}

onMounted(load)
onUnmounted(clearMorphTimers)
</script>

<template>
  <div class="max-w-4xl mx-auto">
    <div class="flex items-center justify-between mb-6">
      <div>
        <h2 class="text-sm font-semibold text-gray-800">间隔复习计划</h2>
        <p class="text-xs text-gray-400 mt-0.5">基于 Ebbinghaus 遗忘曲线，{{ reviews.length }} 个知识点在复习</p>
      </div>
      <button class="btn btn-primary" @click="showForm = !showForm">
        <Plus :size="16" />
        <span>添加计划</span>
      </button>
    </div>

    <div v-if="actionFeedback" class="mb-4 text-sm text-emerald-600 bg-emerald-50 px-3 py-2 rounded-lg">
      {{ actionFeedback }}
    </div>

    <div v-if="adaptiveReview" class="mb-4 review-morphing rounded-xl border border-amber-100 bg-amber-50/70 p-4">
      <div class="flex items-start justify-between gap-3">
        <div>
          <p class="text-sm font-semibold text-amber-900">{{ adaptiveReview.title }}</p>
          <p class="text-xs text-amber-700 mt-1 whitespace-pre-line">{{ morphText || adaptiveReview.simplified_explanation }}</p>
        </div>
        <div class="shrink-0 flex flex-col items-end gap-1">
          <span class="rounded-lg bg-white/80 border border-amber-100 px-2 py-1 text-[10px] font-semibold text-amber-700">
            掌握 {{ Math.round((adaptiveReview.mastery || 0) * 100) }}%
          </span>
          <span class="rounded-lg bg-white/80 border border-amber-100 px-2 py-1 text-[9px] font-semibold text-amber-600">
            {{ morphing ? '重组中' : adaptiveReview.llm_backend || 'Visualizer' }}
          </span>
        </div>
      </div>
      <!-- 思维导图可视化区域 (照搬 CollapsibleMindmap 可折叠交互组件) -->
      <div v-if="adaptiveReview.mermaid" class="mt-3 w-full">
        <CollapsibleMindmap :code="adaptiveReview.mermaid" />
      </div>
      <div class="mt-3 grid grid-cols-1 md:grid-cols-2 gap-2">
        <p
          v-for="line in morphTrace"
          :key="line"
          class="morph-trace rounded-lg bg-white/70 border border-amber-100 px-3 py-2 text-[10px] text-amber-800"
        >
          {{ line }}
        </p>
      </div>
    </div>

    <!-- New plan form -->
    <div v-if="showForm" class="card mb-6">
      <div class="space-y-3">
        <input v-model="form.concept" class="input" placeholder="知识点名称（必填）" />
        <div class="grid grid-cols-2 gap-3">
          <div>
            <label class="text-xs text-gray-500 mb-1 block">掌握度 ({{ form.mastery.toFixed(2) }})</label>
            <input v-model.number="form.mastery" type="range" min="0" max="1" step="0.05" class="w-full" />
          </div>
          <div>
            <label class="text-xs text-gray-500 mb-1 block">复习间隔</label>
            <div class="flex gap-1 flex-wrap">
              <button
                v-for="d in intervals"
                :key="d"
                type="button"
                class="btn text-xs py-1"
                :class="form.interval_days === d ? 'btn-primary' : 'btn-outline'"
                @click.prevent="form.interval_days = d"
              >{{ d }}天</button>
            </div>
          </div>
        </div>
        <div class="flex gap-2 justify-end">
          <button type="button" class="btn btn-outline text-xs" @click.prevent="showForm = false">取消</button>
          <button type="button" class="btn btn-primary text-xs" @click.prevent="addPlan">创建</button>
        </div>
      </div>
    </div>

    <!-- List -->
    <div v-if="loading" class="flex items-center justify-center py-12">
      <div class="pulse-dot" />
      <span class="ml-3 text-gray-400 text-sm">加载中...</span>
    </div>

    <div v-else-if="reviews.length === 0" class="text-center py-12 text-gray-400">
      <Calendar :size="40" class="mx-auto mb-3 text-gray-300" />
      <p class="text-sm">暂无复习计划</p>
      <p class="text-xs mt-1">在对话框中学习后自动生成复习安排</p>
    </div>

    <div v-else class="space-y-2">
      <div v-for="plan in reviews" :key="plan.id" class="card flex flex-col sm:flex-row sm:items-center gap-4">
        <CheckCircle2 :size="20" class="text-emerald-500 shrink-0" />
        <div class="flex-1 min-w-0">
          <div class="flex items-center gap-2">
            <span class="text-sm font-medium text-gray-800">{{ plan.concept }}</span>
            <span :class="`badge text-xs ${masteryColor(plan.mastery)}`">
              掌握度 {{ ((plan.mastery || 0) * 100).toFixed(0) }}%
            </span>
          </div>
          <div class="flex items-center gap-3 mt-1 text-xs text-gray-400">
            <span class="flex items-center gap-1"><Clock :size="12" /> 间隔 {{ plan.interval_days || '-' }}天</span>
            <span class="flex items-center gap-1"><Brain :size="12" /> 下次复习 {{ nextReviewDate(plan) }}</span>
            <span>复习 {{ plan.review_count || 0 }} 次</span>
            <span>E-Factor {{ easinessText(plan) }}</span>
          </div>
          <div class="mt-1.5 h-1.5 bg-gray-100 rounded-full overflow-hidden">
            <div
              class="h-full rounded-full"
              :class="(plan.mastery || 0) > 0.6 ? 'bg-emerald-500' : (plan.mastery || 0) > 0.3 ? 'bg-amber-500' : 'bg-red-500'"
              :style="{ width: ((plan.mastery || 0) * 100) + '%' }"
            />
          </div>
        </div>
        <div class="flex flex-col items-end gap-2 shrink-0">
          <span class="badge text-xs" :class="statusClass(plan)">{{ dueText(plan) }}</span>
          <div class="flex gap-1">
            <button
              v-for="action in qualityActions"
              :key="`${plan.id}-${action.quality}`"
              type="button"
              class="px-2 py-1 rounded-lg border text-[11px] font-medium transition-colors disabled:opacity-50"
              :class="action.tone"
              :disabled="!!reviewingKey"
              @click.prevent="submitReview(plan, action.quality)"
            >
              {{ reviewingKey === `${plan.id || plan.concept}:${action.quality}` ? '提交中' : action.label }}
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.review-morphing {
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.65);
  animation: morph-panel 420ms ease both;
}

.morph-trace {
  animation: morph-line 300ms ease both;
}

@keyframes morph-panel {
  from {
    opacity: 0;
    transform: translateY(6px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

@keyframes morph-line {
  from {
    opacity: 0;
    transform: translateY(4px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}
</style>
