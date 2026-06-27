<script setup>
import { ref, onMounted, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { getStudentProfile } from '../api'
import {
  BrainCircuit, Target, TrendingUp, BookOpen, AlertTriangle,
  User, Lightbulb, BarChart3, Layers, Activity, Zap, Heart,
  ChevronRight, ArrowRight, GraduationCap, Sparkles, CheckCircle2,
  AlertCircle, Info, FileText, Download,
} from '@lucide/vue'
import MasteryRadar from '../components/MasteryRadar.vue'

const route = useRoute()
const router = useRouter()
const studentId = ref(route.query.student_id || localStorage.getItem('edumatrix_student_id') || 'demo-student')
const analysis = ref(null)
const loading = ref(true)
const error = ref('')
const activeTab = ref('overview')

onMounted(async () => {
  try {
    // Get raw profile first
    const profile = await getStudentProfile(studentId.value)
    // Then get analysis
    const { default: axios } = await import('axios')
    const token = localStorage.getItem('edumatrix_token')
    const headers = { Authorization: `Bearer ${token}` }
    const lang = localStorage.getItem('edumatrix_lang') || ''
    if (lang) headers['Accept-Language'] = lang
    const resp = await axios.get(`/api/profile/${studentId.value}/analysis`, { headers })
    analysis.value = {
      ...resp.data,
      raw_profile: profile,
    }
  } catch (e) {
    error.value = e.response?.data?.detail || e.message || '加载失败'
  } finally {
    loading.value = false
  }
})

const background = computed(() => analysis.value?.background || {})
const dimensions = computed(() => analysis.value?.dimensions || {})
const causes = computed(() => analysis.value?.causes || {})
const weakAnalysis = computed(() => analysis.value?.weak_analysis || [])
const suggestions = computed(() => analysis.value?.suggestions || [])

const dimensionList = computed(() => {
  return Object.entries(dimensions.value).map(([key, val]) => ({
    key,
    ...val,
  }))
})

const conceptMastery = computed(() => {
  const raw = analysis.value?.raw_profile?.concept_mastery || {}
  return Object.entries(raw).map(([name, score]) => ({ name, mastery: score }))
})

const avgMastery = computed(() => {
  const m = analysis.value?.raw_profile?.concept_mastery
  if (!m || Object.keys(m).length === 0) return 0
  const v = Object.values(m)
  return Math.round(v.reduce((a, b) => a + b, 0) / v.length * 100)
})

function dimColor(score) {
  if (score >= 0.66) return 'bg-emerald-500'
  if (score >= 0.33) return 'bg-amber-500'
  return 'bg-red-500'
}

function dimTextColor(score) {
  if (score >= 0.66) return 'text-emerald-600'
  if (score >= 0.33) return 'text-amber-600'
  return 'text-red-600'
}

function levelBadge(level) {
  if (level === 'high') return { text: '良好', cls: 'bg-emerald-50 text-emerald-700' }
  if (level === 'medium') return { text: '待加强', cls: 'bg-amber-50 text-amber-700' }
  return { text: '需关注', cls: 'bg-red-50 text-red-700' }
}

function goLearn(concept) {
  router.push({ path: '/learn', query: { q: concept } })
}

function goPath() {
  router.push({ path: '/learning-path', query: { student_id: studentId.value } })
}
</script>

<template>
  <div v-if="loading" class="flex items-center justify-center h-64">
    <div class="animate-spin w-5 h-5 border-2 border-purple-500 border-t-transparent rounded-full" />
  </div>
  <div v-else-if="error" class="text-center py-12 text-red-500 text-sm">{{ error }}</div>
  <div v-else class="max-w-6xl mx-auto space-y-6">

    <!-- Header -->
    <div class="flex items-center justify-between">
      <div class="flex items-center gap-3">
        <div class="w-10 h-10 rounded-xl bg-gradient-to-br from-purple-500 to-indigo-600 flex items-center justify-center text-white text-sm font-bold">
          {{ (background.display_name || background.student_id || '?')[0] }}
        </div>
        <div>
          <h1 class="text-lg font-bold text-gray-800">学习画像分析</h1>
          <p class="text-xs text-gray-400">{{ background.student_id }} · {{ background.major }}</p>
        </div>
      </div>
      <div class="flex items-center gap-2">
        <button class="px-3 py-1.5 text-xs font-semibold rounded-lg bg-emerald-50 text-emerald-700 hover:bg-emerald-100 transition-all flex items-center gap-1.5" @click="goPath">
          <TrendingUp :size="12" /> 查看学习路径
        </button>
      </div>
    </div>

    <!-- Tab navigation -->
    <div class="flex gap-1 border-b border-gray-100 pb-1 overflow-x-auto">
      <button class="px-4 py-2 text-xs font-semibold rounded-t-lg transition-all whitespace-nowrap"
        :class="activeTab === 'overview' ? 'text-purple-700 bg-purple-50 border-b-2 border-purple-500' : 'text-gray-500 hover:text-gray-700 hover:bg-gray-50'"
        @click="activeTab = 'overview'">
        <User :size="12" class="inline mr-1" /> 概览
      </button>
      <button class="px-4 py-2 text-xs font-semibold rounded-t-lg transition-all whitespace-nowrap"
        :class="activeTab === 'dimensions' ? 'text-purple-700 bg-purple-50 border-b-2 border-purple-500' : 'text-gray-500 hover:text-gray-700 hover:bg-gray-50'"
        @click="activeTab = 'dimensions'">
        <BarChart3 :size="12" class="inline mr-1" /> 十维分析
      </button>
      <button class="px-4 py-2 text-xs font-semibold rounded-t-lg transition-all whitespace-nowrap"
        :class="activeTab === 'weakness' ? 'text-purple-700 bg-purple-50 border-b-2 border-purple-500' : 'text-gray-500 hover:text-gray-700 hover:bg-gray-50'"
        @click="activeTab = 'weakness'">
        <AlertTriangle :size="12" class="inline mr-1" /> 薄弱点归因
      </button>
      <button class="px-4 py-2 text-xs font-semibold rounded-t-lg transition-all whitespace-nowrap"
        :class="activeTab === 'causes' ? 'text-purple-700 bg-purple-50 border-b-2 border-purple-500' : 'text-gray-500 hover:text-gray-700 hover:bg-gray-50'"
        @click="activeTab = 'causes'">
        <Info :size="12" class="inline mr-1" /> 成因分析
      </button>
      <button class="px-4 py-2 text-xs font-semibold rounded-t-lg transition-all whitespace-nowrap"
        :class="activeTab === 'suggestions' ? 'text-purple-700 bg-purple-50 border-b-2 border-purple-500' : 'text-gray-500 hover:text-gray-700 hover:bg-gray-50'"
        @click="activeTab = 'suggestions'">
        <Sparkles :size="12" class="inline mr-1" /> 教学建议
      </button>
    </div>

    <!-- Tab: Overview -->
    <div v-if="activeTab === 'overview'" class="space-y-6">
      <!-- Student card -->
      <div class="bg-white rounded-2xl border border-gray-100 shadow-sm p-6">
        <div class="flex items-center gap-4">
          <div class="w-14 h-14 rounded-2xl bg-gradient-to-br from-purple-500 to-indigo-600 flex items-center justify-center text-white text-lg font-bold">
            {{ (background.student_id || '?')[0] }}
          </div>
          <div class="flex-1">
            <h2 class="text-lg font-bold text-gray-800">{{ background.student_id }}</h2>
            <p class="text-xs text-gray-500 mt-0.5">{{ background.major }} · {{ background.target_course }}</p>
            <div class="flex gap-2 mt-2 flex-wrap">
              <span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-lg text-[10px] font-medium bg-blue-50 text-blue-700">
                <Lightbulb :size="10" /> {{ background.cognitive_style }}
              </span>
              <span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-lg text-[10px] font-medium bg-indigo-50 text-indigo-700">
                <Zap :size="10" /> 动机: {{ background.motivation_type }}
              </span>
              <span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-lg text-[10px] font-medium"
                :class="background.frustration_index > 0.3 ? 'bg-amber-50 text-amber-700' : 'bg-emerald-50 text-emerald-700'">
                <Heart :size="10" /> 挫败感: {{ Math.round(background.frustration_index * 100) }}%
              </span>
            </div>
          </div>
          <div class="text-right">
            <p class="text-3xl font-bold" :class="avgMastery >= 60 ? 'text-emerald-600' : avgMastery >= 30 ? 'text-amber-600' : 'text-red-600'">{{ avgMastery }}%</p>
            <p class="text-[10px] text-gray-400">平均掌握度</p>
          </div>
        </div>
        <div v-if="background.learning_goals?.length" class="mt-4 pt-3 border-t border-gray-50">
          <p class="text-[10px] font-semibold text-gray-500 mb-1.5 flex items-center gap-1"><Target :size="10" /> 学习目标</p>
          <div class="flex flex-wrap gap-1.5">
            <span v-for="goal in background.learning_goals" :key="goal" class="px-2 py-0.5 rounded-md text-[10px] font-medium bg-purple-50 text-purple-700">{{ goal }}</span>
          </div>
        </div>
        <div v-if="background.learning_preferences?.length" class="mt-2">
          <p class="text-[10px] font-semibold text-gray-500 mb-1 flex items-center gap-1"><BookOpen :size="10" /> 学习偏好</p>
          <div class="flex flex-wrap gap-1">
            <span v-for="pref in background.learning_preferences" :key="pref" class="px-2 py-0.5 rounded-md text-[10px] font-medium bg-cyan-50 text-cyan-700">{{ pref }}</span>
          </div>
        </div>
      </div>

      <!-- Radar chart -->
      <div class="bg-white rounded-2xl border border-gray-100 shadow-sm p-5">
        <h3 class="text-sm font-semibold text-gray-800 mb-3 flex items-center gap-2"><BrainCircuit :size="16" class="text-purple-500" /> 能力掌握度雷达图</h3>
        <div class="h-72">
          <MasteryRadar v-if="conceptMastery.length" :concepts="conceptMastery" :student-id="studentId" />
          <div v-else class="flex items-center justify-center h-full text-xs text-gray-400">暂无数据</div>
        </div>
      </div>

      <!-- Quick stats -->
      <div class="grid grid-cols-2 md:grid-cols-4 gap-3">
        <div class="bg-white rounded-xl border border-gray-100 shadow-sm p-4 text-center">
          <p class="text-xs text-gray-500">知识点数</p>
          <p class="text-xl font-bold text-gray-800 mt-1">{{ Object.keys(analysis?.raw_profile?.concept_mastery || {}).length }}</p>
        </div>
        <div class="bg-white rounded-xl border border-gray-100 shadow-sm p-4 text-center">
          <p class="text-xs text-gray-500">薄弱点数</p>
          <p class="text-xl font-bold text-rose-600 mt-1">{{ weakAnalysis.length }}</p>
        </div>
        <div class="bg-white rounded-xl border border-gray-100 shadow-sm p-4 text-center">
          <p class="text-xs text-gray-500">认知负荷</p>
          <p class="text-xl font-bold mt-1" :class="(analysis?.raw_profile?.cognitive_load || 0) > 0.5 ? 'text-amber-600' : 'text-emerald-600'">{{ Math.round((analysis?.raw_profile?.cognitive_load || 0) * 100) }}%</p>
        </div>
        <div class="bg-white rounded-xl border border-gray-100 shadow-sm p-4 text-center">
          <p class="text-xs text-gray-500">参与度</p>
          <p class="text-xl font-bold mt-1" :class="(analysis?.raw_profile?.focus_level || 0) > 0.5 ? 'text-emerald-600' : 'text-amber-600'">{{ Math.round((analysis?.raw_profile?.focus_level || 0) * 100) }}%</p>
        </div>
      </div>
    </div>

    <!-- Tab: Dimensions -->
    <div v-if="activeTab === 'dimensions'" class="space-y-4">
      <p class="text-xs text-gray-500">基于 10 个学习维度的综合诊断，每个维度包含评分、诊断文本和建议措施</p>
      <div v-for="dim in dimensionList" :key="dim.key" class="bg-white rounded-2xl border border-gray-100 shadow-sm p-5">
        <div class="flex items-center justify-between mb-2">
          <h3 class="text-sm font-semibold text-gray-800">{{ dim.label }}</h3>
          <span class="px-2 py-0.5 rounded-md text-[10px] font-medium" :class="levelBadge(dim.level).cls">
            {{ levelBadge(dim.level).text }}
          </span>
        </div>
        <div class="flex items-center gap-3 mb-3">
          <div class="flex-1 h-2 bg-gray-100 rounded-full overflow-hidden">
            <div class="h-full rounded-full transition-all" :class="dimColor(dim.score)" :style="{ width: (dim.score * 100) + '%' }" />
          </div>
          <span class="text-xs font-mono" :class="dimTextColor(dim.score)">{{ Math.round(dim.score * 100) }}%</span>
        </div>
        <p class="text-xs text-gray-600 bg-gray-50 rounded-lg px-3 py-2">{{ dim.diagnosis }}</p>
        <div v-if="dim.suggestions?.length" class="mt-2 space-y-1">
          <p class="text-[10px] font-semibold text-gray-500 flex items-center gap-1"><Sparkles :size="10" /> 建议</p>
          <div v-for="(s, i) in dim.suggestions" :key="i" class="flex items-start gap-2 text-[10px] text-gray-600">
            <span class="text-purple-400 mt-0.5">→</span>
            <span>{{ s }}</span>
          </div>
        </div>
        <div v-if="dim.evidence?.length" class="mt-2">
          <p class="text-[10px] font-semibold text-gray-400 flex items-center gap-1"><FileText :size="10" /> 证据片段</p>
          <div v-for="(ev, i) in dim.evidence" :key="i" class="text-[10px] text-gray-400 italic ml-3">"{{ ev }}"</div>
        </div>
      </div>
    </div>

    <!-- Tab: Weakness -->
    <div v-if="activeTab === 'weakness'" class="space-y-4">
      <p class="text-xs text-gray-500">薄弱知识点及其根因分析，帮助理解"为什么不会"</p>
      <div v-for="wa in weakAnalysis" :key="wa.concept" class="bg-white rounded-2xl border border-gray-100 shadow-sm p-5">
        <div class="flex items-center justify-between mb-3">
          <div class="flex items-center gap-2">
            <AlertCircle :size="16" class="text-rose-500" />
            <h3 class="text-sm font-semibold text-gray-800">{{ wa.concept }}</h3>
          </div>
          <span class="text-lg font-bold" :class="wa.mastery * 100 >= 60 ? 'text-emerald-600' : wa.mastery * 100 >= 30 ? 'text-amber-600' : 'text-red-600'">
            {{ Math.round(wa.mastery * 100) }}%
          </span>
        </div>
        <div class="h-2 bg-gray-100 rounded-full overflow-hidden mb-3">
          <div class="h-full rounded-full" :class="wa.mastery * 100 >= 60 ? 'bg-emerald-500' : wa.mastery * 100 >= 30 ? 'bg-amber-500' : 'bg-red-500'"
            :style="{ width: (wa.mastery * 100) + '%' }" />
        </div>
        <div v-if="wa.root_causes?.length" class="space-y-2">
          <p class="text-[10px] font-semibold text-gray-500">根因分析</p>
          <div v-for="rc in wa.root_causes" :key="rc.cause" class="bg-amber-50 rounded-lg px-3 py-2">
            <div class="flex items-center justify-between">
              <span class="text-xs font-medium text-amber-800">{{ rc.cause }}</span>
              <span class="text-[10px] text-amber-600">{{ rc.percentage }}%</span>
            </div>
            <p class="text-[10px] text-amber-700 mt-0.5">{{ rc.detail }}</p>
          </div>
        </div>
        <button class="mt-3 px-3 py-1.5 text-[10px] font-semibold rounded-lg bg-purple-50 text-purple-700 hover:bg-purple-100 transition-all flex items-center gap-1" @click="goLearn(wa.concept)">
          <BookOpen :size="10" /> 去学习
        </button>
      </div>
    </div>

    <!-- Tab: Causes -->
    <div v-if="activeTab === 'causes'" class="space-y-4">
      <p class="text-xs text-gray-500">学习不会的成因分析，按占比排序</p>
      <div v-for="(cause, key) in causes" :key="key" class="bg-white rounded-2xl border border-gray-100 shadow-sm p-5">
        <div class="flex items-center justify-between mb-2">
          <h3 class="text-sm font-semibold text-gray-800">{{ cause.label }}</h3>
          <span class="text-sm font-bold text-amber-600">{{ cause.percentage }}%</span>
        </div>
        <div class="h-2 bg-gray-100 rounded-full overflow-hidden mb-3">
          <div class="h-full rounded-full bg-amber-500" :style="{ width: cause.percentage + '%' }" />
        </div>
        <div v-if="cause.interventions?.length" class="space-y-1">
          <p class="text-[10px] font-semibold text-gray-500 flex items-center gap-1"><Sparkles :size="10" /> 推荐干预</p>
          <div v-for="(iv, i) in cause.interventions" :key="i" class="flex items-start gap-2 text-[10px] text-gray-600">
            <span class="text-purple-400 mt-0.5">→</span>
            <span>{{ iv }}</span>
          </div>
        </div>
      </div>
    </div>

    <!-- Tab: Suggestions -->
    <div v-if="activeTab === 'suggestions'" class="space-y-4">
      <p class="text-xs text-gray-500">综合各维度分析生成的个性化教学建议</p>
      <div class="bg-white rounded-2xl border border-gray-100 shadow-sm p-6">
        <h3 class="text-sm font-semibold text-gray-800 mb-3 flex items-center gap-2"><Sparkles :size="16" class="text-amber-500" /> 个性化建议汇总</h3>
        <div class="space-y-3">
          <div v-for="(s, i) in suggestions" :key="i" class="flex items-start gap-3 text-sm">
            <div v-if="s.startsWith('  →')" class="text-purple-400 text-xs ml-6">→</div>
            <div v-else class="w-5 h-5 rounded-full bg-amber-100 text-amber-700 flex items-center justify-center text-[10px] font-bold shrink-0 mt-0.5">{{ i + 1 }}</div>
            <span class="text-gray-700" :class="s.startsWith('  →') ? 'text-xs text-gray-500' : 'text-sm font-medium'">{{ s }}</span>
          </div>
        </div>
      </div>

      <!-- 个性化资源生成 -->
      <div class="bg-white rounded-2xl border border-purple-100 shadow-sm p-5">
        <h3 class="text-sm font-semibold text-gray-800 mb-3 flex items-center gap-2"><Sparkles :size="16" class="text-purple-500" /> 一键生成个性化资源</h3>
        <p class="text-[10px] text-gray-500 mb-3">基于您的画像分析自动生成针对性学习资源</p>
        <div class="grid grid-cols-2 md:grid-cols-4 gap-3">
          <button class="p-3 rounded-xl bg-purple-50 hover:bg-purple-100 border border-purple-100 transition-all text-center"
            @click="router.push({ path: '/learn', query: { student_id: studentId, q: Object.keys(analysis?.raw_profile?.concept_mastery || {}).filter(k => (analysis?.raw_profile?.concept_mastery?.[k] || 0) < 0.4)[0] || '' } })">
            <BookOpen :size="18" class="mx-auto text-purple-600" />
            <p class="text-[10px] font-semibold text-purple-700 mt-1">针对性讲解</p>
            <p class="text-[8px] text-purple-400">薄弱点智能讲解</p>
          </button>
          <button class="p-3 rounded-xl bg-emerald-50 hover:bg-emerald-100 border border-emerald-100 transition-all text-center">
            <Target :size="18" class="mx-auto text-emerald-600" />
            <p class="text-[10px] font-semibold text-emerald-700 mt-1">生成练习题</p>
            <p class="text-[8px] text-emerald-400">自适应出题</p>
          </button>
          <button class="p-3 rounded-xl bg-amber-50 hover:bg-amber-100 border border-amber-100 transition-all text-center"
            @click="router.push({ path: '/review', query: { student_id: studentId } })">
            <Calendar :size="18" class="mx-auto text-amber-600" />
            <p class="text-[10px] font-semibold text-amber-700 mt-1">复习计划</p>
            <p class="text-[8px] text-amber-400">遗忘曲线推送</p>
          </button>
          <button class="p-3 rounded-xl bg-blue-50 hover:bg-blue-100 border border-blue-100 transition-all text-center"
            @click="router.push({ path: '/notes', query: { student_id: studentId } })">
            <FileText :size="18" class="mx-auto text-blue-600" />
            <p class="text-[10px] font-semibold text-blue-700 mt-1">生成笔记</p>
            <p class="text-[8px] text-blue-400">智能提炼</p>
          </button>
        </div>
      </div>

      <!-- Quick action links -->
      <div class="grid grid-cols-1 md:grid-cols-3 gap-4">
        <router-link :to="{ path: '/learn', query: { student_id: studentId } }"
          class="bg-white rounded-2xl border border-gray-100 shadow-sm p-4 hover:border-purple-200 transition-all flex items-center gap-3">
          <div class="w-10 h-10 rounded-xl bg-purple-50 flex items-center justify-center">
            <BookOpen :size="18" class="text-purple-600" />
          </div>
          <div>
            <p class="text-sm font-semibold text-gray-800">开始学习</p>
            <p class="text-[10px] text-gray-400">进入智能对话学习模式</p>
          </div>
        </router-link>
        <router-link :to="{ path: '/learning-path', query: { student_id: studentId } }"
          class="bg-white rounded-2xl border border-gray-100 shadow-sm p-4 hover:border-emerald-200 transition-all flex items-center gap-3">
          <div class="w-10 h-10 rounded-xl bg-emerald-50 flex items-center justify-center">
            <TrendingUp :size="18" class="text-emerald-600" />
          </div>
          <div>
            <p class="text-sm font-semibold text-gray-800">学习路径</p>
            <p class="text-[10px] text-gray-400">查看动态学习路径规划</p>
          </div>
        </router-link>
        <router-link :to="{ path: '/wrong-questions', query: { student_id: studentId } }"
          class="bg-white rounded-2xl border border-gray-100 shadow-sm p-4 hover:border-rose-200 transition-all flex items-center gap-3">
          <div class="w-10 h-10 rounded-xl bg-rose-50 flex items-center justify-center">
            <AlertTriangle :size="18" class="text-rose-500" />
          </div>
          <div>
            <p class="text-sm font-semibold text-gray-800">错题本</p>
            <p class="text-[10px] text-gray-400">查看错题和薄弱点回顾</p>
          </div>
        </router-link>
      </div>
    </div>

  </div>
</template>
