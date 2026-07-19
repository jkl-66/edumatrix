<script setup>
import { ref, onMounted, computed } from 'vue'
import { getStudentProfile, getQuizHistory, getWrongQuestions } from '../api'
import { useRouter } from 'vue-router'
import {
  BrainCircuit, Target, TrendingUp, BookOpen, AlertTriangle,
  User, Lightbulb, BarChart3, Layers, Activity, Zap, Heart,
  ChevronRight, ArrowRight, GraduationCap, Sparkles,
} from '@lucide/vue'

const router = useRouter()
const props = defineProps({ studentId: String })
const profile = ref(null)
const loading = ref(true)
const error = ref('')
const quizHistory = ref([])
const wrongQuestions = ref([])

const dimLabels = {
  knowledge_mastery: '知识基础与掌握度', misconception_profile: '易错点与概念解构',
  understanding_fluency_transfer: '理解熟练与迁移能力', cognitive_processing: '认知加工与负荷调控',
  learning_strategy: '自适应学习策略', metacognition: '元认知与自我调节',
  motivation_and_purpose: '内在动机与目标指引', affect_resilience: '情绪信心与抗挫韧性',
  interaction_preference: '表达互动与模式偏好', learning_context: '学习情境与全环境支持',
}

const sortedMastery = computed(() => {
  if (!profile.value?.concept_mastery) return []
  return Object.entries(profile.value.concept_mastery)
    .sort(([, a], [, b]) => a - b)
    .map(([concept, score]) => ({ concept, score: Math.round(score * 100) }))
})

const avgMastery = computed(() => {
  const m = profile.value?.concept_mastery
  if (!m || Object.keys(m).length === 0) return 0
  const v = Object.values(m)
  return Math.round(v.reduce((a, b) => a + b, 0) / v.length * 100)
})

const dims = computed(() => {
  if (!profile.value?.dimensions) return []
  return Object.entries(profile.value.dimensions).map(([k, v]) => ({
    key: k, label: dimLabels[k] || k, score: Math.round((v.score || 0) * 100),
  }))
})

function masteryColor(s) {
  if (s >= 80) return 'bg-emerald-500'
  if (s >= 50) return 'bg-amber-500'
  return 'bg-red-500'
}

function dimColor(s) {
  if (s >= 66) return 'bg-emerald-500'
  if (s >= 33) return 'bg-amber-500'
  return 'bg-red-500'
}

function goLearn(concept) {
  router.push({ path: '/learn', query: { q: concept } })
}

onMounted(async () => {
  try {
    const [p, qh, wq] = await Promise.all([
      getStudentProfile(props.studentId || 'default'),
      getQuizHistory(props.studentId || 'default').catch(() => []),
      getWrongQuestions(props.studentId || 'default').catch(() => []),
    ])
    profile.value = p
    quizHistory.value = Array.isArray(qh) ? qh : []
    wrongQuestions.value = Array.isArray(wq) ? wq : []
  } catch (e) {
    error.value = e.message || '加载失败'
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div v-if="loading" class="flex items-center justify-center h-64"><div class="animate-spin w-5 h-5 border-2 border-purple-500 border-t-transparent rounded-full" /></div>
  <div v-else-if="error" class="text-center py-12 text-red-500 text-sm">{{ error }}</div>
  <div v-else class="max-w-5xl mx-auto space-y-6">

    <!-- 学生概览卡 -->
    <div class="bg-white rounded-2xl border border-gray-100 shadow-sm p-6">
      <div class="flex items-center gap-4">
        <div class="w-12 h-12 rounded-2xl bg-gradient-to-br from-purple-500 to-indigo-600 flex items-center justify-center">
          <User :size="22" class="text-white" />
        </div>
        <div class="flex-1">
          <h2 class="text-lg font-bold text-gray-800">{{ profile?.name || profile?.student_id || '未知' }}</h2>
          <p class="text-xs text-gray-400 mt-0.5">{{ profile?.major || '未设置专业' }} · {{ profile?.target_course || '未选课程' }}</p>
        </div>
        <div class="text-right">
          <p class="text-2xl font-bold" :class="avgMastery >= 60 ? 'text-emerald-600' : avgMastery >= 30 ? 'text-amber-600' : 'text-red-600'">{{ avgMastery }}%</p>
          <p class="text-[10px] text-gray-400">平均掌握度</p>
        </div>
      </div>
      <div class="flex gap-3 mt-4 flex-wrap">
        <span class="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg text-[10px] font-medium bg-blue-50 text-blue-700">
          <Lightbulb :size="11" /> {{ profile?.cognitive_style || '未诊断' }}
        </span>
        <span class="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg text-[10px] font-medium bg-amber-50 text-amber-700">
          <Heart :size="11" /> 挫败感: {{ profile?.frustration_index != null ? Math.round(profile.frustration_index * 100) + '%' : 'N/A' }}
        </span>
        <span class="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg text-[10px] font-medium bg-indigo-50 text-indigo-700">
          <Zap :size="11" /> 认知负荷: {{ profile?.cognitive_load != null ? Math.round(profile.cognitive_load * 100) + '%' : 'N/A' }}
        </span>
      </div>
    </div>

    <!-- 知识掌握度 -->
    <div class="bg-white rounded-2xl border border-gray-100 shadow-sm p-5">
      <h3 class="text-sm font-semibold text-gray-800 mb-3 flex items-center gap-2"><BrainCircuit :size="16" class="text-purple-500" /> 知识掌握度</h3>
      <div class="space-y-2">
        <div v-for="item in sortedMastery" :key="item.concept" class="flex items-center gap-3 group cursor-pointer" @click="goLearn(item.concept)">
          <span class="text-xs text-gray-600 w-28 truncate shrink-0">{{ item.concept }}</span>
          <div class="flex-1 h-2.5 bg-gray-100 rounded-full overflow-hidden">
            <div class="h-full rounded-full transition-all" :class="masteryColor(item.score)" :style="{ width: item.score + '%' }" />
          </div>
          <span class="text-xs font-mono w-10 text-right" :class="item.score >= 60 ? 'text-emerald-600' : item.score >= 30 ? 'text-amber-600' : 'text-red-600'">{{ item.score }}%</span>
          <ChevronRight :size="14" class="text-gray-300 opacity-0 group-hover:opacity-100 transition-opacity shrink-0" />
        </div>
      </div>
    </div>

    <!-- 学习路径推荐 -->
    <div class="bg-white rounded-2xl border border-gray-100 shadow-sm p-5">
      <h3 class="text-sm font-semibold text-gray-800 mb-3 flex items-center gap-2"><TrendingUp :size="16" class="text-emerald-500" /> 推荐学习路径</h3>
      <div class="space-y-2">
        <div v-for="(item, i) in sortedMastery.filter(m => m.score < 60).slice(0, 5)" :key="item.concept" class="flex items-center gap-3 p-3 rounded-xl hover:bg-amber-50 transition-all cursor-pointer border border-transparent hover:border-amber-200" @click="goLearn(item.concept)">
          <div class="w-6 h-6 rounded-full bg-amber-100 text-amber-700 flex items-center justify-center text-xs font-bold shrink-0">{{ i + 1 }}</div>
          <div class="flex-1 min-w-0">
            <p class="text-sm font-medium text-gray-800">{{ item.concept }}</p>
            <p class="text-[10px] text-gray-400">当前掌握度 {{ item.score }}% — 需要加强</p>
          </div>
          <button class="px-3 py-1.5 text-[10px] font-semibold rounded-lg bg-gradient-to-r from-purple-600 to-indigo-600 text-white hover:from-purple-700 hover:to-indigo-700 transition-all shrink-0 flex items-center gap-1">
            <BookOpen :size="10" /> 去学习
          </button>
        </div>
        <div v-if="sortedMastery.filter(m => m.score < 60).length === 0" class="text-center py-6 text-gray-400 text-sm">
          <Sparkles :size="32" class="mx-auto mb-2 text-emerald-300" />
          <p>当前所有知识点已掌握良好！<br>可以尝试学习更深层的概念。</p>
        </div>
      </div>
    </div>

    <!-- 维度状态 -->
    <div class="grid grid-cols-2 gap-3">
      <div v-for="dim in dims" :key="dim.key" class="bg-white rounded-xl border border-gray-100 shadow-sm p-4">
        <p class="text-xs font-medium text-gray-600 mb-2">{{ dim.label }}</p>
        <div class="h-2 bg-gray-100 rounded-full overflow-hidden">
          <div class="h-full rounded-full" :class="dimColor(dim.score)" :style="{ width: dim.score + '%' }" />
        </div>
        <p class="text-xs font-mono mt-1" :class="dim.score >= 66 ? 'text-emerald-600' : dim.score >= 33 ? 'text-amber-600' : 'text-red-600'">{{ dim.score }}%</p>
      </div>
    </div>

    <!-- 学习活动 -->
    <div class="bg-white rounded-2xl border border-gray-100 shadow-sm p-5">
      <h3 class="text-sm font-semibold text-gray-800 mb-3 flex items-center gap-2"><Activity :size="16" class="text-blue-500" /> 最近学习活动</h3>
      <div v-if="quizHistory.length === 0" class="text-center py-6 text-gray-400 text-xs">暂无答题记录，开始学习吧</div>
      <div v-else class="space-y-1">
        <div v-for="(q, i) in quizHistory.slice(0, 5)" :key="i" class="flex items-center gap-3 text-xs text-gray-600 py-1.5">
          <div class="w-1.5 h-1.5 rounded-full" :class="(q.accuracy_score || 0) >= 0.7 ? 'bg-green-400' : 'bg-amber-400'" />
          <span class="w-20 text-gray-400">{{ new Date(q.created_at).toLocaleDateString() }}</span>
          <span class="flex-1 truncate">{{ q.question?.slice(0, 40) || q.target_concept }}</span>
          <span class="font-mono" :class="(q.accuracy_score || 0) >= 0.7 ? 'text-green-600' : 'text-amber-600'">{{ Math.round((q.accuracy_score || 0) * 100) }}%</span>
        </div>
      </div>
    </div>

  </div>
</template>
