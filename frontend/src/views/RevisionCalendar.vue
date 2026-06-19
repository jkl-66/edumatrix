<script setup>
import { ref, onMounted, computed } from 'vue'
import { getReviewPlans, checkinReview, getCheckinStreak } from '../api'
import { Calendar, CheckCircle2, Clock, TrendingUp, Flame, BookOpen, Loader2 } from '@lucide/vue'

const props = defineProps({ studentId: String })

const reviewPlans = ref([])
const checkinStreak = ref(0)
const loading = ref(true)
const checkinLoading = ref(false)
const checkedIn = ref(false)
const checkinDuration = ref(10)
const selectedConcept = ref('')

// Group by priority
const urgentReviews = computed(() =>
  reviewPlans.value
    .filter(p => p.mastery < 0.5 || (p.priority || 1.0) < 1.5)
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
  checkinLoading.value = true
  try {
    const result = await checkinReview(props.studentId, selectedConcept.value, checkinDuration.value)
    checkedIn.value = true
    checkinStreak.value = result.streak || checkinStreak.value
    setTimeout(() => { checkedIn.value = false }, 3000)
  } catch (e) {
    console.error('打卡失败:', e)
  } finally {
    checkinLoading.value = false
  }
}

function getMasteryColor(m) {
  if (m >= 0.8) return 'bg-emerald-500'
  if (m >= 0.5) return 'bg-amber-500'
  return 'bg-red-500'
}

onMounted(loadData)
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
        <div class="flex-1 min-w-[200px]">
          <label class="text-xs text-gray-500 mb-1 block">复习知识点（可选）</label>
          <input
            v-model="selectedConcept"
            class="input text-sm"
            placeholder="如：逻辑回归"
          />
        </div>
        <div class="w-32">
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
          class="btn btn-primary text-sm"
          :disabled="checkinLoading || checkedIn"
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
            class="card flex items-center gap-4"
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
            class="card flex items-center gap-4"
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
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
