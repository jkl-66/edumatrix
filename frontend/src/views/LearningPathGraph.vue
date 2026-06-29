<script setup>
import { ref, onMounted, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { getLearningPath } from '../api'
import {
  BookOpen, BrainCircuit, Target, TrendingUp, ChevronRight,
  ArrowRight, AlertTriangle, CheckCircle2, Layers, Sparkles,
  Clock, Zap,
} from '@lucide/vue'

const route = useRoute()
const router = useRouter()
const studentId = ref(route.query.student_id || localStorage.getItem('edumatrix_student_id') || 'demo-student')
const pathData = ref(null)
const loading = ref(true)
const error = ref('')
const showAll = ref(false)

const learningChain = computed(() => pathData.value?.learning_chain || [])
const nextSteps = computed(() => pathData.value?.next_steps || [])
const gapChains = computed(() => pathData.value?.gap_chains || [])
const stages = computed(() => pathData.value?.stages || [])
const progress = computed(() => pathData.value?.progress_summary || {})
const strategySuggestions = computed(() => pathData.value?.strategy_suggestions || [])

const totalSteps = computed(() => learningChain.value.length)
const masteredCount = computed(() => learningChain.value.filter(n => n.mastered).length)

const displayChain = computed(() => {
  if (showAll.value) return learningChain.value
  return learningChain.value.slice(0, 15)
})

function statusIcon(status) {
  if (status === '已完成') return '✅'
  if (status === '当前可学') return '▶️'
  return '🔒'
}

function statusColor(status) {
  if (status === '已完成') return 'border-emerald-300 bg-emerald-50'
  if (status === '当前可学') return 'border-blue-300 bg-blue-50 ring-2 ring-blue-200'
  return 'border-gray-200 bg-gray-50'
}

function statusTextColor(status) {
  if (status === '已完成') return 'text-emerald-700'
  if (status === '当前可学') return 'text-blue-700'
  return 'text-gray-400'
}

function masteryColor(score) {
  if (score >= 60) return 'text-emerald-600'
  if (score >= 30) return 'text-amber-600'
  return 'text-red-600'
}

function masteryBarColor(score) {
  if (score >= 60) return 'bg-emerald-500'
  if (score >= 30) return 'bg-amber-500'
  return 'bg-red-500'
}

function goLearn(concept) {
  router.push({ path: '/learn', query: { q: concept } })
}

function goAnalysis() {
  router.push({ path: '/student-analysis', query: { student_id: studentId.value } })
}

onMounted(async () => {
  try {
    pathData.value = await getLearningPath(studentId.value)
  } catch (e) {
    error.value = e.response?.data?.detail || e.message || '加载失败'
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div v-if="loading" class="flex items-center justify-center h-64">
    <div class="animate-spin w-5 h-5 border-2 border-purple-500 border-t-transparent rounded-full" />
  </div>
  <div v-else-if="error" class="text-center py-12 text-red-500 text-sm">{{ error }}</div>
  <div v-else class="max-w-4xl mx-auto space-y-6">

    <!-- Header -->
    <div class="flex items-center justify-between">
      <div>
        <h1 class="text-lg font-bold text-gray-800">学习路径</h1>
        <p class="text-xs text-gray-400 mt-0.5">按前置依赖链条推进 · 逐关解锁</p>
      </div>
      <div class="text-right">
        <p class="text-lg font-bold text-emerald-600">{{ masteredCount }}/{{ totalSteps }}</p>
        <p class="text-[10px] text-gray-400">已完成</p>
      </div>
    </div>

    <!-- Progress summary -->
    <div class="grid grid-cols-4 gap-2">
      <div class="bg-white rounded-xl border border-gray-100 shadow-sm p-3 text-center">
        <p class="text-[9px] text-gray-500">已完成</p>
        <p class="text-lg font-bold text-emerald-600 mt-0.5">{{ progress.mastered || 0 }}</p>
      </div>
      <div class="bg-white rounded-xl border border-gray-100 shadow-sm p-3 text-center">
        <p class="text-[9px] text-gray-500">进行中</p>
        <p class="text-lg font-bold text-blue-600 mt-0.5">{{ progress.in_progress || 0 }}</p>
      </div>
      <div class="bg-white rounded-xl border border-gray-100 shadow-sm p-3 text-center">
        <p class="text-[9px] text-gray-500">未解锁</p>
        <p class="text-lg font-bold text-gray-400 mt-0.5">{{ progress.locked || 0 }}</p>
      </div>
      <div class="bg-white rounded-xl border border-gray-100 shadow-sm p-3 text-center">
        <p class="text-[9px] text-gray-500">总概念</p>
        <p class="text-lg font-bold text-gray-700 mt-0.5">{{ progress.total_concepts || 0 }}</p>
      </div>
    </div>

    <!-- Next steps (prominent) -->
    <div v-if="nextSteps.length" class="bg-blue-50 rounded-2xl border border-blue-200 p-5">
      <h2 class="text-sm font-semibold text-blue-800 mb-3 flex items-center gap-2">
        <Unlock :size="15" /> 下一步学习推荐
      </h2>
      <p class="text-[10px] text-blue-600 mb-3">以下知识点前置依赖已满足，当前最适合学习</p>
      <div class="space-y-2">
        <div v-for="(step, i) in nextSteps" :key="step.concept"
          class="flex items-center gap-3 bg-white rounded-xl p-3 border border-blue-100 cursor-pointer hover:shadow-sm transition-all"
          @click="goLearn(step.concept)">
          <div class="w-7 h-7 rounded-full bg-blue-100 text-blue-700 flex items-center justify-center text-xs font-bold shrink-0">{{ i + 1 }}</div>
          <div class="flex-1">
            <p class="text-sm font-semibold text-gray-800">{{ step.concept }}</p>
            <p class="text-[10px] text-gray-400">Step {{ step.step }} · 前置就绪 · 当前掌握 {{ step.percentage }}%</p>
          </div>
          <span class="px-2 py-0.5 text-[9px] font-semibold rounded-lg bg-blue-100 text-blue-700">去学习 →</span>
        </div>
      </div>
    </div>

    <!-- Chain progression -->
    <div class="bg-white rounded-2xl border border-gray-100 shadow-sm p-5">
      <h2 class="text-sm font-semibold text-gray-800 mb-3 flex items-center gap-2">
        <Layers :size="15" class="text-purple-500" /> 学习链条
      </h2>
      <p class="text-[10px] text-gray-400 mb-3">按从基础到进阶的顺序逐步推进，前置概念未掌握时后续概念自动锁定</p>

      <div class="space-y-1">
        <div v-for="node in displayChain" :key="node.concept"
          class="flex items-center gap-3 py-2.5 px-3 rounded-lg transition-all"
          :class="statusColor(node.status)"
          @click="goLearn(node.concept)">

          <!-- Step number -->
          <div class="w-6 h-6 rounded-full flex items-center justify-center text-[10px] font-bold shrink-0"
            :class="node.mastered ? 'bg-emerald-200 text-emerald-700' : node.status === '当前可学' ? 'bg-blue-200 text-blue-700' : 'bg-gray-200 text-gray-400'">
            {{ node.step }}
          </div>

          <!-- Content -->
          <div class="flex-1 min-w-0">
            <div class="flex items-center gap-2">
              <span class="text-sm font-medium"
                :class="node.mastered ? 'text-gray-700' : node.status === '当前可学' ? 'text-blue-800 font-semibold' : 'text-gray-400'">
                {{ node.concept }}
              </span>
              <span class="text-[10px]">{{ statusIcon(node.status) }}</span>
              <span class="text-[9px] font-medium px-1.5 py-0.5 rounded"
                :class="{
                  'bg-emerald-50 text-emerald-600': node.bloom_level === '记忆' || node.bloom_level === '理解',
                  'bg-blue-50 text-blue-600': node.bloom_level === '应用',
                  'bg-purple-50 text-purple-600': node.bloom_level === '分析' || node.bloom_level === '评价',
                  'bg-rose-50 text-rose-600': node.bloom_level === '创造'
                }">
                {{ node.bloom_level }}
              </span>
            </div>
            <!-- Tier badge -->
            <p class="text-[9px] text-gray-400 mt-0.5">Tier {{ node.tier }} · {{ node.status }}</p>
          </div>

          <!-- Mastery bar -->
          <div class="w-20">
            <div class="h-1.5 bg-gray-100 rounded-full overflow-hidden">
              <div class="h-full rounded-full" :class="masteryBarColor(node.percentage)" :style="{ width: node.percentage + '%' }" />
            </div>
            <p class="text-[9px] font-mono text-right mt-0.5" :class="masteryColor(node.percentage)">{{ node.percentage }}%</p>
          </div>
        </div>

        <!-- Step guidance (shown for first few non-mastered steps) -->
        <div v-for="n in nextSteps.slice(0, 1)" :key="'guide-' + n.concept" class="mt-4 px-4 py-3 bg-blue-50/80 rounded-xl border border-blue-100">
          <p class="text-xs font-semibold text-blue-800 mb-1">📖 当前步骤学习引导：{{ n.concept }}</p>
          <div class="text-[10px] text-blue-700 space-y-1">
            <p>🎯 学什么：{{ n.guidance?.summary || '掌握核心概念与原理' }}</p>
            <p>💡 怎么学：{{ n.guidance?.strategy || '结合理论学习和代码实践' }}</p>
            <p>✅ 验证标准：{{ n.guidance?.verify || '能用自己的话解释核心概念' }}</p>
            <p>⏱ 预估时间：{{ n.estimated_minutes || 45 }} 分钟</p>
          </div>
          <div class="flex gap-2 mt-2">
            <button class="px-3 py-1 text-[9px] font-semibold rounded-lg bg-blue-100 text-blue-700 hover:bg-blue-200 transition-all" @click.stop="goLearn(n.concept)">开始学习</button>
            <button class="px-3 py-1 text-[9px] font-semibold rounded-lg bg-purple-100 text-purple-700 hover:bg-purple-200 transition-all">🎯 生成练习题</button>
            <button class="px-3 py-1 text-[9px] font-semibold rounded-lg bg-emerald-100 text-emerald-700 hover:bg-emerald-200 transition-all">📝 生成笔记</button>
          </div>
        </div>
      </div>

      <!-- Show more / less -->
      <button v-if="learningChain.length > 15" class="w-full mt-3 py-2 text-xs font-semibold text-purple-600 hover:bg-purple-50 rounded-lg transition-all"
        @click="showAll = !showAll">
        {{ showAll ? '收起' : `展开全部 (${learningChain.length} 步)` }}
      </button>
    </div>

    <!-- Gap chains -->
    <div v-if="gapChains.length" class="bg-white rounded-2xl border border-amber-100 shadow-sm p-5">
      <h2 class="text-sm font-semibold text-amber-700 mb-3 flex items-center gap-2">
        <AlertTriangle :size="15" /> 前置依赖缺口
      </h2>
      <p class="text-[10px] text-gray-500 mb-3">以下概念因前置知识未掌握而无法学习</p>
      <div class="space-y-2">
        <div v-for="chain in gapChains" :key="chain.target" class="bg-amber-50 rounded-xl p-3">
          <p class="text-xs font-semibold text-gray-700 mb-1">目标: {{ chain.target }}</p>
          <div class="space-y-1">
            <div v-for="(gap, gi) in chain.chain" :key="gi"
              class="flex items-center gap-2 text-[10px] ml-3"
              :style="{ marginLeft: (gap.depth * 12) + 'px' }">
              <span class="text-amber-500">↳</span>
              <span class="text-gray-600">{{ gap.action }} ({{ Math.round(gap.mastery * 100) }}%)</span>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Stages overview -->
    <div class="bg-white rounded-2xl border border-gray-100 shadow-sm p-5">
      <h2 class="text-sm font-semibold text-gray-800 mb-3 flex items-center gap-2">
        <TrendingUp :size="15" class="text-emerald-500" /> 阶段总览
      </h2>
      <div class="space-y-3">
        <div v-for="(stage, i) in stages" :key="i" class="flex items-start gap-3">
          <div class="w-8 h-8 rounded-full flex items-center justify-center text-xs font-bold shrink-0"
            :class="['bg-emerald-100 text-emerald-700', 'bg-blue-100 text-blue-700', 'bg-purple-100 text-purple-700'][i]">
            {{ ['入门', '核心', '进阶'][i] }}
          </div>
          <div class="flex-1">
            <div class="flex items-center gap-2">
              <span class="text-sm font-semibold text-gray-800">{{ stage.name }}</span>
              <span class="text-[9px] text-gray-400">{{ stage.range }}</span>
            </div>
            <div class="flex flex-wrap gap-1 mt-1">
              <span v-for="c in stage.concepts.slice(0, 8)" :key="c"
                class="px-1.5 py-0.5 text-[9px] rounded bg-gray-50 text-gray-600">{{ c }}</span>
              <span v-if="stage.concepts.length > 8" class="text-[9px] text-gray-400">+{{ stage.concepts.length - 8 }}</span>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Strategy suggestions -->
    <div v-if="strategySuggestions.length" class="bg-white rounded-2xl border border-gray-100 shadow-sm p-5">
      <h2 class="text-sm font-semibold text-gray-800 mb-3 flex items-center gap-2">
        <Sparkles :size="15" class="text-purple-500" /> 学习建议
      </h2>
      <div class="space-y-2">
        <div v-for="ss in strategySuggestions" :key="ss.concept"
          class="flex items-start gap-2 p-3 rounded-lg bg-purple-50/50">
          <div class="w-5 h-5 rounded-full bg-purple-100 text-purple-700 flex items-center justify-center text-[9px] font-bold shrink-0 mt-0.5">S{{ ss.step }}</div>
          <div class="flex-1">
            <p class="text-xs font-semibold text-gray-800">{{ ss.concept }}</p>
            <div v-for="(s, si) in ss.suggestions" :key="si" class="text-[10px] text-gray-600 flex items-start gap-1 mt-0.5">
              <span class="text-purple-400">→</span>
              <span>{{ s }}</span>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Nav -->
    <div class="text-center py-2">
      <button class="px-4 py-2 text-xs font-semibold rounded-lg bg-purple-50 text-purple-700 hover:bg-purple-100 transition-all" @click="goAnalysis">
        查看完整画像分析 →
      </button>
    </div>

  </div>
</template>
