<script setup>
import { ref, onMounted, computed } from 'vue'
import { getTeacherDashboard, getDatasets } from '../api'
import { BarChart3, Users, AlertTriangle, Brain, TrendingUp, Activity, Target } from '@lucide/vue'

const props = defineProps({ studentId: String })
const data = ref(null)
const datasets = ref([])
const loading = ref(true)
const expanded = ref(null)

const studentProfiles = computed(() => data.value?.profiles || [])

const avgMastery = computed(() => {
  const ps = studentProfiles.value
  if (!ps.length) return 0
  const total = ps.reduce((s, p) => s + calcAvg(p), 0)
  return Math.round(total / ps.length)
})

const totalWeak = computed(() => {
  return studentProfiles.value.reduce((s, p) => s + (p.weak_points?.length || 0), 0)
})

function calcAvg(prof) {
  const m = prof.concept_mastery
  if (!m || !Object.keys(m).length) return 0
  const v = Object.values(m)
  return Math.round(v.reduce((a, b) => a + b, 0) / v.length * 100)
}

function masteryColor(score) {
  if (score >= 60) return 'text-emerald-600'
  if (score >= 30) return 'text-amber-600'
  return 'text-red-600'
}

onMounted(async () => {
  try {
    const [td, ds] = await Promise.all([
      getTeacherDashboard().catch(() => getTeacherDashboard()),
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
</script>

<template>
  <div v-if="loading" class="flex items-center justify-center h-64"><div class="animate-spin w-5 h-5 border-2 border-purple-500 border-t-transparent rounded-full" /></div>
  <div v-else-if="!data" class="text-center py-12 text-gray-400"><BarChart3 :size="48" class="mx-auto mb-3 text-gray-300" /><p class="text-sm">无法加载教师看板</p></div>
  <div v-else class="space-y-6 max-w-6xl">
    <!-- Overview stats -->
    <div class="grid grid-cols-4 gap-4">
      <div class="bg-white rounded-xl border border-gray-100 shadow-sm p-4">
        <p class="text-xs text-gray-500 font-medium">学生总数</p>
        <p class="text-2xl font-bold mt-1 text-gray-800">{{ studentProfiles.length }}</p>
      </div>
      <div class="bg-white rounded-xl border border-gray-100 shadow-sm p-4">
        <p class="text-xs text-gray-500 font-medium">平均掌握度</p>
        <p class="text-2xl font-bold mt-1 text-emerald-600">{{ avgMastery }}%</p>
      </div>
      <div class="bg-white rounded-xl border border-gray-100 shadow-sm p-4">
        <p class="text-xs text-gray-500 font-medium">薄弱概念数</p>
        <p class="text-2xl font-bold mt-1 text-rose-600">{{ totalWeak }}</p>
      </div>
      <div class="bg-white rounded-xl border border-gray-100 shadow-sm p-4">
        <p class="text-xs text-gray-500 font-medium">干预推荐</p>
        <p class="text-2xl font-bold mt-1 text-amber-600">{{ data.interventions?.length || 0 }}</p>
      </div>
    </div>

    <!-- Student cards grid -->
    <div class="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
      <div v-for="prof in studentProfiles" :key="prof.student_id"
        class="bg-white rounded-2xl border border-gray-100 shadow-sm p-5 hover:shadow-md transition-all cursor-pointer"
        @click="expanded = expanded === prof.student_id ? null : prof.student_id">
        <div class="flex items-center gap-3 mb-3">
          <div class="w-10 h-10 rounded-xl bg-gradient-to-br from-purple-500 to-indigo-600 flex items-center justify-center text-white text-sm font-bold shrink-0">
            {{ (prof.name || prof.student_id || '?')[0] }}
          </div>
          <div class="flex-1 min-w-0">
            <p class="text-sm font-semibold text-gray-800 truncate">{{ prof.name || prof.student_id }}</p>
            <p class="text-[10px] text-gray-400 truncate">{{ prof.major || '未设置' }} · {{ prof.cognitive_style || '未诊断' }}</p>
          </div>
          <div class="text-right">
            <p class="text-lg font-bold" :class="masteryColor(calcAvg(prof))">{{ calcAvg(prof) }}%</p>
            <p class="text-[9px] text-gray-400">掌握度</p>
          </div>
        </div>
        <div class="flex flex-wrap gap-1.5">
          <span v-for="(wp, wi) in (prof.weak_points || []).slice(0, 3)" :key="wi" class="inline-flex items-center px-2 py-0.5 rounded-md text-[9px] font-medium bg-rose-50 text-rose-600">{{ wp }}</span>
          <span v-if="(prof.weak_points || []).length > 3" class="text-[9px] text-gray-400 px-1">+{{ prof.weak_points.length - 3 }}</span>
        </div>
        <!-- Expanded detail -->
        <div v-if="expanded === prof.student_id" class="mt-4 pt-3 border-t border-gray-100 space-y-2">
          <div v-for="(score, concept) in (prof.concept_mastery || {})" :key="concept" class="flex items-center gap-2 text-xs">
            <span class="text-gray-600 w-20 truncate">{{ concept }}</span>
            <div class="flex-1 h-1.5 bg-gray-100 rounded-full overflow-hidden">
              <div class="h-full rounded-full" :class="score * 100 >= 60 ? 'bg-emerald-400' : 'bg-amber-400'" :style="{ width: (score * 100) + '%' }" />
            </div>
            <span class="font-mono w-8 text-right" :class="score * 100 >= 60 ? 'text-emerald-600' : 'text-amber-600'">{{ Math.round(score * 100) }}%</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
