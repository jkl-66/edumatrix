<script setup>
import { ref, onMounted } from 'vue'
import { getTeacherDashboard, getDatasets } from '../api'
import {
  BarChart3, Users, AlertTriangle, Lightbulb, TrendingUp,
  Brain, BookOpen, Target, Activity, Zap, Shield, Eye
} from '@lucide/vue'

const props = defineProps({ studentId: String })

const data = ref(null)
const datasets = ref([])
const loading = ref(true)

onMounted(async () => {
  try {
    const [td, ds] = await Promise.all([
      getTeacherDashboard(),
      getDatasets().catch(() => ({ datasets: [] })),
    ])
    data.value = td
    datasets.value = ds.datasets || []
  } catch (e) {
    console.error(e)
  } finally {
    loading.value = false
  }
})

const dimIcons = {
  knowledge_mastery: Brain,
  misconception_profile: AlertTriangle,
  cognitive_loading: Zap,
  learning_strategy: Lightbulb,
  metacognition: Eye,
  motivation: TrendingUp,
  affect: Activity,
  interaction: Users,
}

function dimIcon(key) {
  return dimIcons[key] || Activity
}

function dimColor(val) {
  if (val >= 0.66) return 'bg-emerald-500'
  if (val >= 0.33) return 'bg-amber-500'
  return 'bg-red-500'
}

const dimBgClass = {
  knowledge_mastery: 'bg-blue-50 text-blue-700',
  misconception_profile: 'bg-red-50 text-red-700',
  cognitive_loading: 'bg-amber-50 text-amber-700',
  learning_strategy: 'bg-purple-50 text-purple-700',
  metacognition: 'bg-cyan-50 text-cyan-700',
  motivation: 'bg-emerald-50 text-emerald-700',
  affect: 'bg-pink-50 text-pink-700',
  interaction: 'bg-indigo-50 text-indigo-700',
}

function dimBg(key) {
  return dimBgClass[key] || 'bg-gray-50 text-gray-700'
}
</script>

<template>
  <div v-if="loading" class="flex items-center justify-center h-64">
    <div class="pulse-dot" />
    <span class="ml-3 text-gray-400 text-sm">加载教师看板...</span>
  </div>

  <div v-else-if="!data" class="text-center py-12 text-gray-400">
    <BarChart3 :size="48" class="mx-auto mb-3 text-gray-300" />
    <p class="text-sm">无法加载教师看板</p>
  </div>

  <div v-else class="space-y-6 max-w-6xl">
    <!-- Overview -->
    <div class="grid grid-cols-1 md:grid-cols-4 gap-4">
      <div class="card">
        <p class="text-xs text-gray-500 font-medium">学生数量</p>
        <p class="text-2xl font-bold mt-1">{{ data.profiles?.length || 0 }}</p>
      </div>
      <div class="card">
        <p class="text-xs text-gray-500 font-medium">维度数量</p>
        <p class="text-2xl font-bold mt-1">{{ Object.keys(data.dimensions || {}).length }}</p>
      </div>
      <div class="card">
        <p class="text-xs text-gray-500 font-medium">误概念模式</p>
        <p class="text-2xl font-bold mt-1">{{ data.misconceptions?.length || 0 }}</p>
      </div>
      <div class="card">
        <p class="text-xs text-gray-500 font-medium">干预推荐</p>
        <p class="text-2xl font-bold mt-1">{{ data.interventions?.length || data.recommendations?.length || 0 }}</p>
      </div>
    </div>

    <!-- Heatmap dimensions -->
    <div class="card">
      <h2 class="text-sm font-semibold text-gray-800 mb-4">学生画像维度热力图</h2>
      <div class="space-y-3">
        <div v-for="(dim, key) in data.dimensions" :key="key" class="flex items-center gap-4">
          <div class="w-36 shrink-0 flex items-center gap-2">
            <component :is="dimIcon(key)" :size="14" class="text-gray-500" />
            <span class="text-xs text-gray-600 truncate">{{ dim.label || key }}</span>
          </div>
          <div class="flex-1 h-3 bg-gray-100 rounded-full overflow-hidden">
            <div
              class="h-full rounded-full transition-all"
              :class="dimColor(dim.value || 0)"
              :style="{ width: ((dim.value || 0) * 100) + '%' }"
            />
          </div>
          <span class="w-10 text-right text-xs font-medium" :class="dimColor(dim.value || 0).replace('bg-', 'text-')">
            {{ ((dim.value || 0) * 100).toFixed(0) }}%
          </span>
        </div>
      </div>
    </div>

    <!-- Profiles -->
    <div class="card">
      <h2 class="text-sm font-semibold text-gray-800 mb-4">学生概况</h2>
      <div class="space-y-3">
        <div v-for="profile in data.profiles" :key="profile.student_id" class="flex items-center gap-4 p-3 bg-gray-50 rounded-lg">
          <div class="w-8 h-8 rounded-full bg-gradient-to-br from-blue-400 to-purple-500 flex items-center justify-center text-white text-xs font-bold shrink-0">
            {{ (profile.student_id || '?')[0] }}
          </div>
          <div class="flex-1 min-w-0">
            <div class="flex items-center gap-2">
              <span class="text-sm font-medium text-gray-800">{{ profile.student_id?.slice(0, 20) }}</span>
              <span v-if="profile.major" class="badge bg-gray-100 text-gray-600 text-[10px]">{{ profile.major }}</span>
            </div>
            <div class="flex flex-wrap gap-1 mt-1">
              <span v-for="(cause, i) in (profile.causes || profile.learning_state_causes || [])" :key="i" class="badge text-[10px]" :class="cause.percentage > 0.5 ? 'bg-red-50 text-red-700' : 'bg-amber-50 text-amber-700'">
                {{ cause.cause || cause }}
              </span>
            </div>
            <div class="flex flex-wrap gap-3 mt-1 text-[10px] text-gray-400">
              <span v-if="profile.weak_points">弱项: {{ profile.weak_points.join(',') }}</span>
              <span v-if="profile.concept_mastery">概念掌握: {{ Object.keys(profile.concept_mastery).length }}个</span>
            </div>
          </div>
          <div class="shrink-0 text-right">
            <p class="text-xs font-medium text-gray-700">画像维度</p>
            <p class="text-xs text-gray-400">{{ Object.keys(profile.dimensions || []).length || 0 }}维</p>
          </div>
        </div>
      </div>
    </div>

    <!-- Misconceptions -->
    <div class="card">
      <div class="flex items-center justify-between mb-4">
        <h2 class="text-sm font-semibold text-gray-800">高频误概念模式</h2>
        <AlertTriangle :size="16" class="text-amber-500" />
      </div>
      <div class="space-y-2">
        <div v-for="(mc, i) in (data.misconceptions || [])" :key="i" class="flex items-center gap-3">
          <div class="w-6 h-6 rounded-full bg-red-50 flex items-center justify-center text-red-600 text-xs font-bold shrink-0">{{ i + 1 }}</div>
          <div class="flex-1 text-sm text-gray-700">{{ mc.concept || mc }}</div>
          <span class="badge bg-red-50 text-red-700 shrink-0">{{ mc.count || mc.frequency || '' }}</span>
        </div>
        <div v-if="!(data.misconceptions?.length)" class="text-sm text-gray-400 text-center py-4">暂无明显误概念模式</div>
      </div>
    </div>

    <!-- Interventions -->
    <div v-if="data.interventions?.length || data.recommendations?.length" class="card">
      <div class="flex items-center justify-between mb-4">
        <h2 class="text-sm font-semibold text-gray-800">干预推荐</h2>
        <Lightbulb :size="16" class="text-amber-500" />
      </div>
      <div class="space-y-2">
        <div v-for="(inv, i) in (data.interventions || data.recommendations)" :key="i" class="flex items-start gap-3 p-3 bg-amber-50 rounded-lg">
          <Lightbulb :size="16" class="text-amber-600 shrink-0 mt-0.5" />
          <p class="text-sm text-amber-800">{{ inv.description || inv }}</p>
        </div>
      </div>
    </div>
  </div>
</template>
