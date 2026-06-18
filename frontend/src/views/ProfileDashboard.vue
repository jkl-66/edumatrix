<script setup>
import { ref, onMounted, computed } from 'vue'
import { getStudentProfile, getQuizHistory, getCodeHistory, getWebSearchHistory } from '../api'
import {
  BrainCircuit, Target, TrendingUp, BookOpen, AlertTriangle,
  User, Lightbulb, BarChart3, Layers, Activity,
  CheckCircle2, XCircle, Clock, Zap, Heart, RotateCw,
  Brain,
} from '@lucide/vue'

const props = defineProps({ studentId: String })

const profile = ref(null)
const loading = ref(true)
const error = ref('')
const quizHistory = ref([])
const codeHistory = ref([])

const dimensionColors = {
  knowledge_mastery: '#3b82f6',
  misconception_profile: '#ef4444',
  understanding_fluency_transfer: '#10b981',
  cognitive_processing: '#f59e0b',
  learning_strategy: '#8b5cf6',
  metacognition: '#ec4899',
  motivation_and_purpose: '#06b6d4',
  affect_resilience: '#f97316',
  interaction_preference: '#6366f1',
  learning_context: '#14b8a6',
}

const dimensionOrder = [
  'knowledge_mastery', 'misconception_profile', 'understanding_fluency_transfer',
  'cognitive_processing', 'learning_strategy', 'metacognition',
  'motivation_and_purpose', 'affect_resilience', 'interaction_preference', 'learning_context',
]

const sortedDimensions = computed(() => {
  if (!profile.value?.dimensions) return []
  return dimensionOrder
    .filter(k => profile.value.dimensions[k])
    .map(k => ({ key: k, ...profile.value.dimensions[k] }))
})

const sortedCauses = computed(() => {
  if (!profile.value?.causes) return []
  return Object.entries(profile.value.causes)
    .sort(([, a], [, b]) => b.percentage - a.percentage)
    .map(([key, val]) => ({ key, ...val }))
})

const sortedMastery = computed(() => {
  if (!profile.value?.concept_mastery) return []
  return Object.entries(profile.value.concept_mastery)
    .sort(([, a], [, b]) => a - b)
    .map(([concept, score]) => ({ concept, score }))
})

const avgMastery = computed(() => {
  const m = profile.value?.concept_mastery
  if (!m || Object.keys(m).length === 0) return 0
  const vals = Object.values(m)
  return vals.reduce((a, b) => a + b, 0) / vals.length
})

function statusBadge(status) {
  const map = { good: 'bg-green-100 text-green-700', fair: 'bg-yellow-100 text-yellow-700', poor: 'bg-red-100 text-red-700' }
  return map[status] || 'bg-gray-100 text-gray-600'
}

onMounted(async () => {
  try {
    const [p, qh, ch] = await Promise.all([
      getStudentProfile(props.studentId || 'default'),
      getQuizHistory(props.studentId || 'default').catch(() => []),
      getCodeHistory(props.studentId || 'default').catch(() => []),
    ])
    profile.value = p
    quizHistory.value = Array.isArray(qh) ? qh : []
    codeHistory.value = Array.isArray(ch) ? ch : []
  } catch (e) {
    error.value = '加载画像失败: ' + (e.response?.data?.detail || e.message)
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div class="max-w-5xl mx-auto space-y-6">
    <div class="flex items-center justify-between">
      <h2 class="text-sm font-semibold text-gray-800">学习画像分析</h2>
    </div>

    <div v-if="loading" class="flex items-center justify-center py-16">
      <div class="pulse-dot" /><span class="ml-3 text-gray-400 text-sm">加载画像数据...</span>
    </div>

    <div v-else-if="error" class="text-center py-16 text-red-500">{{ error }}</div>

    <template v-else-if="profile">
      <!-- Overview Cards -->
      <div class="grid grid-cols-2 sm:grid-cols-4 gap-4">
        <div class="card">
          <div class="flex items-center gap-2 mb-2">
            <User :size="14" class="text-blue-500" />
            <span class="text-[10px] font-medium text-gray-500">专业方向</span>
          </div>
          <p class="text-sm font-semibold text-gray-800">{{ profile.major || '待设置' }}</p>
          <p class="text-[10px] text-gray-400 mt-0.5">{{ profile.target_course || '' }}</p>
        </div>
        <div class="card">
          <div class="flex items-center gap-2 mb-2">
            <Lightbulb :size="14" class="text-yellow-500" />
            <span class="text-[10px] font-medium text-gray-500">认知风格</span>
          </div>
          <p class="text-sm font-semibold text-gray-800">{{ profile.cognitive_style || '待分析' }}</p>
          <p class="text-[10px] text-gray-400 mt-0.5">{{ (profile.interaction_preferences || []).slice(0, 2).join('、') || '无偏好' }}</p>
        </div>
        <div class="card">
          <div class="flex items-center gap-2 mb-2">
            <BarChart3 :size="14" class="text-green-500" />
            <span class="text-[10px] font-medium text-gray-500">平均掌握度</span>
          </div>
          <p class="text-sm font-semibold" :class="avgMastery >= 0.6 ? 'text-green-600' : avgMastery >= 0.35 ? 'text-yellow-600' : 'text-red-600'">
            {{ (avgMastery * 100).toFixed(0) }}%
          </p>
          <div class="h-1.5 bg-gray-200 rounded-full mt-1.5 overflow-hidden">
            <div class="h-full rounded-full transition-all" :class="avgMastery >= 0.6 ? 'bg-green-500' : avgMastery >= 0.35 ? 'bg-yellow-500' : 'bg-red-500'"
              :style="{ width: (avgMastery * 100) + '%' }" />
          </div>
        </div>
        <div class="card">
          <div class="flex items-center gap-2 mb-2">
            <Activity :size="14" class="text-purple-500" />
            <span class="text-[10px] font-medium text-gray-500">认知负荷</span>
          </div>
          <p class="text-sm font-semibold" :class="profile.cognitive_load < 0.5 ? 'text-green-600' : profile.cognitive_load < 0.7 ? 'text-yellow-600' : 'text-red-600'">
            {{ (profile.cognitive_load * 100).toFixed(0) }}%
          </p>
          <p class="text-[10px] text-gray-400 mt-0.5">专注度: {{ (profile.focus_level * 100).toFixed(0) }}%</p>
        </div>
      </div>

      <!-- === 任务 7.2-4: 情感状态与遗忘指标 === -->
      <div class="grid grid-cols-2 sm:grid-cols-4 gap-4">
        <div class="card">
          <div class="flex items-center gap-2 mb-2">
            <Heart :size="14" class="text-pink-500" />
            <span class="text-[10px] font-medium text-gray-500">挫败感指数</span>
          </div>
          <p class="text-sm font-semibold" :class="profile.frustration_index < 0.3 ? 'text-green-600' : profile.frustration_index < 0.6 ? 'text-yellow-600' : 'text-red-600'">
            {{ (profile.frustration_index * 100).toFixed(0) }}%
          </p>
          <div class="h-1.5 bg-gray-200 rounded-full mt-1.5 overflow-hidden">
            <div class="h-full rounded-full transition-all" :class="profile.frustration_index < 0.3 ? 'bg-green-500' : profile.frustration_index < 0.6 ? 'bg-yellow-500' : 'bg-red-500'"
              :style="{ width: (profile.frustration_index * 100) + '%' }" />
          </div>
        </div>
        <div class="card">
          <div class="flex items-center gap-2 mb-2">
            <Zap :size="14" class="text-amber-500" />
            <span class="text-[10px] font-medium text-gray-500">参与度</span>
          </div>
          <p class="text-sm font-semibold text-blue-600">{{ (profile.engagement_level * 100).toFixed(0) }}%</p>
          <p class="text-[10px] text-gray-400 mt-0.5">动机: {{ profile.motivation_type || '未诊断' }}</p>
        </div>
        <div class="card">
          <div class="flex items-center gap-2 mb-2">
            <RotateCw :size="14" class="text-orange-500" />
            <span class="text-[10px] font-medium text-gray-500">元认知偏差</span>
          </div>
          <p class="text-sm font-semibold" :class="profile.metacognitive_mismatch < 0.3 ? 'text-green-600' : 'text-red-600'">
            {{ (profile.metacognitive_mismatch * 100).toFixed(0) }}%
          </p>
          <p class="text-[10px] text-gray-400 mt-0.5">连续错误: {{ profile.consecutive_errors || 0 }}</p>
        </div>
        <div class="card">
          <div class="flex items-center gap-2 mb-2">
            <Brain :size="14" class="text-violet-500" />
            <span class="text-[10px] font-medium text-gray-500">BKT 追踪概念</span>
          </div>
          <p class="text-sm font-semibold text-gray-800">{{ Object.keys(profile.bkt_states || {}).length || 0 }}</p>
          <p class="text-[10px] text-gray-400 mt-0.5">会话交互: {{ profile.session_interactions || 0 }}</p>
        </div>
      </div>

      <!-- 10 Dimensions Radar-like Display -->
      <div class="card">
        <div class="flex items-center gap-2 mb-4">
          <Layers :size="16" class="text-indigo-500" />
          <span class="text-sm font-semibold text-gray-800">10 维学习画像</span>
        </div>
        <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <div v-for="dim in sortedDimensions" :key="dim.key" class="p-3 rounded-lg border border-gray-100">
            <div class="flex items-center justify-between mb-1.5">
              <span class="text-xs font-medium text-gray-700">{{ dim.label }}</span>
              <span class="badge text-[10px]" :class="statusBadge(dim.status)">{{ dim.status === 'good' ? '良好' : dim.status === 'fair' ? '一般' : '待提升' }}</span>
            </div>
            <div class="flex items-center gap-2">
              <div class="flex-1 h-2 bg-gray-200 rounded-full overflow-hidden">
                <div class="h-full rounded-full transition-all" :style="{
                  width: (dim.score * 100) + '%',
                  backgroundColor: dimensionColors[dim.key] || '#6366f1'
                }" />
              </div>
              <span class="text-[10px] font-mono text-gray-500 w-8 text-right">{{ (dim.score * 100).toFixed(0) }}</span>
            </div>
          </div>
        </div>
      </div>

      <!-- Weak Points & Concept Mastery -->
      <div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <div class="card">
          <div class="flex items-center gap-2 mb-3">
            <AlertTriangle :size="16" class="text-red-500" />
            <span class="text-sm font-semibold text-gray-800">薄弱知识点 ({{ (profile.weak_points || []).length }})</span>
          </div>
          <div v-if="!profile.weak_points?.length" class="text-xs text-gray-400 text-center py-4">暂无薄弱点数据</div>
          <div v-else class="space-y-1.5">
            <div v-for="point in profile.weak_points" :key="point" class="flex items-center justify-between px-2 py-1.5 bg-red-50 rounded-lg">
              <span class="text-xs text-red-700">{{ point }}</span>
              <span class="text-[10px] font-mono text-red-500">
                {{ profile.concept_mastery?.[point] ? (profile.concept_mastery[point] * 100).toFixed(0) + '%' : '待诊断' }}
              </span>
            </div>
          </div>
        </div>

        <div class="card">
          <div class="flex items-center gap-2 mb-3">
            <TrendingUp :size="16" class="text-green-500" />
            <span class="text-sm font-semibold text-gray-800">知识掌握度排行</span>
          </div>
          <div v-if="sortedMastery.length === 0" class="text-xs text-gray-400 text-center py-4">暂无掌握度数据</div>
          <div v-else class="space-y-1.5">
            <div v-for="item in sortedMastery.slice(0, 10)" :key="item.concept" class="flex items-center gap-2">
              <span class="text-xs text-gray-600 w-28 truncate shrink-0">{{ item.concept }}</span>
              <div class="flex-1 h-1.5 bg-gray-200 rounded-full overflow-hidden">
                <div class="h-full rounded-full" :class="item.score >= 0.6 ? 'bg-green-500' : item.score >= 0.35 ? 'bg-yellow-500' : 'bg-red-500'"
                  :style="{ width: (item.score * 100) + '%' }" />
              </div>
              <span class="text-[10px] font-mono text-gray-500 w-8 text-right">{{ (item.score * 100).toFixed(0) }}</span>
            </div>
          </div>
        </div>
      </div>

      <!-- Learning State Causes -->
      <div v-if="sortedCauses.length" class="card">
        <div class="flex items-center gap-2 mb-3">
          <Zap :size="16" class="text-orange-500" />
          <span class="text-sm font-semibold text-gray-800">学习状态诊断</span>
        </div>
        <div class="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-3">
          <div v-for="cause in sortedCauses" :key="cause.key" class="p-3 rounded-lg border border-gray-100">
            <div class="flex items-center justify-between mb-1">
              <span class="text-xs font-medium text-gray-700">{{ cause.label }}</span>
              <span class="text-xs font-bold" :class="cause.percentage > 30 ? 'text-red-600' : cause.percentage > 15 ? 'text-yellow-600' : 'text-green-600'">
                {{ cause.percentage }}%
              </span>
            </div>
            <div class="h-1.5 bg-gray-200 rounded-full overflow-hidden">
              <div class="h-full rounded-full" :class="cause.percentage > 30 ? 'bg-red-500' : cause.percentage > 15 ? 'bg-yellow-500' : 'bg-green-500'"
                :style="{ width: cause.percentage + '%' }" />
            </div>
          </div>
        </div>
      </div>

      <!-- Learning Goals & Preferences -->
      <div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <div class="card">
          <div class="flex items-center gap-2 mb-2">
            <Target :size="16" class="text-blue-500" />
            <span class="text-sm font-semibold text-gray-800">学习目标</span>
          </div>
          <div v-if="!profile.learning_goals?.length" class="text-xs text-gray-400 text-center py-4">对话中自动识别</div>
          <div v-else class="flex flex-wrap gap-1.5">
            <span v-for="goal in profile.learning_goals" :key="goal" class="badge bg-blue-50 text-blue-700 text-xs">{{ goal }}</span>
          </div>
        </div>
        <div class="card">
          <div class="flex items-center gap-2 mb-2">
            <BookOpen :size="16" class="text-purple-500" />
            <span class="text-sm font-semibold text-gray-800">互动偏好</span>
          </div>
          <div v-if="!profile.interaction_preferences?.length" class="text-xs text-gray-400 text-center py-4">对话中自动识别</div>
          <div v-else class="flex flex-wrap gap-1.5">
            <span v-for="pref in profile.interaction_preferences" :key="pref" class="badge bg-purple-50 text-purple-700 text-xs">{{ pref }}</span>
          </div>
        </div>
      </div>
    </template>
  </div>
</template>
