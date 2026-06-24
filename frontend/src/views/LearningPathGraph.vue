<script setup>
import { ref, onMounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import { getStudentProfile } from '../api'
import {
  BookOpen, BrainCircuit, Target, TrendingUp, ChevronRight,
  ArrowRight, AlertTriangle, CheckCircle2, Layers,
} from '@lucide/vue'

const router = useRouter()
const props = defineProps({ studentId: { type: String, default: 'demo-student' } })
const loading = ref(true)
const profile = ref(null)

// DEFAULT_KNOWLEDGE_DAG 同步自 agent_swarm.py
const KNOWLEDGE_DAG = {
  '池化层': ['卷积核', '特征图'], '卷积核': ['反向传播'], '特征图': ['卷积核'],
  '反向传播': ['链式法则', '梯度下降'], '链式法则': ['梯度下降'],
  '梯度下降': ['线性回归'], '逻辑回归': ['线性回归', '梯度下降'],
  '线性回归': ['机器学习'], '决策树': ['机器学习'],
  '支持向量机': ['线性回归', '机器学习'], '过拟合': ['正则化', '交叉验证'],
  '正则化': ['线性回归'], '交叉验证': ['机器学习'],
  '神经网络': ['反向传播', '梯度下降'], '卷积神经网络': ['神经网络', '卷积核', '池化层'],
  'Transformer': ['注意力机制', '反向传播'], '注意力机制': ['神经网络'],
}

const pathPlan = computed(() => {
  if (!profile.value?.concept_mastery) return { weak: [], prereq_gaps: [], ready: [], strong: [] }
  const mastery = profile.value.concept_mastery
  const weak = Object.entries(mastery).filter(([, v]) => v < 0.4).sort(([, a], [, b]) => a - b)
  const medium = Object.entries(mastery).filter(([, v]) => v >= 0.4 && v < 0.7).sort(([, a], [, b]) => a - b)
  const strong = Object.entries(mastery).filter(([, v]) => v >= 0.7).sort(([, a], [, b]) => b - a)

  // 前置依赖检查：对每个薄弱点，检查其前置概念是否也已掌握
  const prereq_gaps = []
  for (const [concept, score] of weak) {
    const prereqs = KNOWLEDGE_DAG[concept] || []
    for (const p of prereqs) {
      if ((mastery[p] || 0) < 0.4) {
        prereq_gaps.push({ concept, prereq: p, prereq_mastery: mastery[p] || 0 })
      }
    }
  }

  return {
    weak: weak.map(([c, s]) => ({ concept: c, score: Math.round(s * 100) })),
    medium: medium.map(([c, s]) => ({ concept: c, score: Math.round(s * 100) })),
    strong: strong.map(([c, s]) => ({ concept: c, score: Math.round(s * 100) })),
    prereq_gaps,
  }
})

const avgMastery = computed(() => {
  const m = profile.value?.concept_mastery
  if (!m || Object.keys(m).length === 0) return 0
  const v = Object.values(m)
  return Math.round(v.reduce((a, b) => a + b, 0) / v.length * 100)
})

function goLearn(concept) {
  router.push({ path: '/learn', query: { q: concept } })
}

onMounted(async () => {
  try {
    const p = await getStudentProfile(props.studentId || 'default')
    profile.value = p
  } catch {
    // use empty
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div class="max-w-4xl mx-auto space-y-6">
    <div v-if="loading" class="flex items-center justify-center h-64"><div class="animate-spin w-5 h-5 border-2 border-purple-500 border-t-transparent rounded-full" /></div>
    <div v-else-if="!profile" class="text-center py-12 text-gray-400 text-sm">无法加载画像数据</div>
    <div v-else>

      <!-- 概览 -->
      <div class="bg-white rounded-2xl border border-gray-100 shadow-sm p-5">
        <div class="flex items-center gap-4">
          <div class="w-12 h-12 rounded-2xl bg-gradient-to-br from-emerald-500 to-teal-600 flex items-center justify-center">
            <TrendingUp :size="22" class="text-white" />
          </div>
          <div>
            <h2 class="text-lg font-bold text-gray-800">学习路径规划</h2>
            <p class="text-xs text-gray-400">基于 ZPD 最近发展区和前置依赖 DAG 动态生成</p>
          </div>
          <div class="ml-auto text-right">
            <p class="text-2xl font-bold" :class="avgMastery >= 60 ? 'text-emerald-600' : 'text-amber-600'">{{ avgMastery }}%</p>
            <p class="text-[10px] text-gray-400">平均掌握度</p>
          </div>
        </div>
      </div>

      <!-- 前置依赖缺口 -->
      <div v-if="pathPlan.prereq_gaps.length" class="bg-white rounded-2xl border border-red-100 shadow-sm p-5">
        <h3 class="text-sm font-semibold text-red-700 mb-3 flex items-center gap-2"><AlertTriangle :size="16" /> 前置依赖缺口 — 需要先补习这些基础知识</h3>
        <div class="space-y-2">
          <div v-for="(gap, i) in pathPlan.prereq_gaps" :key="i" class="flex items-center gap-3 p-3 rounded-xl bg-red-50 border border-red-100">
            <div class="w-7 h-7 rounded-full bg-red-200 text-red-700 flex items-center justify-center text-xs font-bold shrink-0">{{ i + 1 }}</div>
            <div class="flex-1">
              <p class="text-sm font-medium text-gray-800">{{ gap.prereq }} <span class="text-xs text-gray-400">→</span> {{ gap.concept }}</p>
              <p class="text-[10px] text-red-500 mt-0.5">{{ gap.prereq }} 掌握度仅 {{ Math.round(gap.prereq_mastery * 100) }}%，不满足学习 {{ gap.concept }} 的前置要求</p>
            </div>
            <button class="px-3 py-1.5 text-[10px] font-semibold rounded-lg bg-red-500 hover:bg-red-600 text-white transition-all shrink-0" @click="goLearn(gap.prereq)">去补习</button>
          </div>
        </div>
      </div>

      <!-- 薄弱点 → 紧急复习 -->
      <div class="bg-white rounded-2xl border border-gray-100 shadow-sm p-5">
        <h3 class="text-sm font-semibold text-gray-800 mb-3 flex items-center gap-2"><Target :size="16" class="text-rose-500" /> 薄弱知识点（掌握度 &lt; 40%）</h3>
        <div v-if="!pathPlan.weak.length" class="text-center py-4 text-emerald-600 text-xs flex items-center justify-center gap-2"><CheckCircle2 :size="14" /> 暂无薄弱知识点</div>
        <div v-else class="space-y-2">
          <div v-for="(item, i) in pathPlan.weak" :key="item.concept" class="flex items-center gap-3 p-3 rounded-xl hover:bg-rose-50 transition-all cursor-pointer border border-transparent hover:border-rose-200" @click="goLearn(item.concept)">
            <div class="w-7 h-7 rounded-full bg-rose-100 text-rose-700 flex items-center justify-center text-xs font-bold shrink-0">{{ i + 1 }}</div>
            <div class="flex-1">
              <p class="text-sm font-medium text-gray-800">{{ item.concept }}</p>
              <p class="text-[10px] text-gray-400">掌握度 {{ item.score }}% — 紧急</p>
            </div>
            <button class="px-3 py-1.5 text-[10px] font-semibold rounded-lg bg-rose-500 hover:bg-rose-600 text-white transition-all shrink-0 flex items-center gap-1"><BookOpen :size="10" /> 学习</button>
          </div>
        </div>
      </div>

      <!-- 进阶中 -->
      <div class="bg-white rounded-2xl border border-gray-100 shadow-sm p-5">
        <h3 class="text-sm font-semibold text-gray-800 mb-3 flex items-center gap-2"><Layers :size="16" class="text-amber-500" /> 巩固提升（掌握度 40%~70%）</h3>
        <div v-if="!pathPlan.medium.length" class="text-center py-4 text-gray-400 text-xs">暂无</div>
        <div v-else class="space-y-2">
          <div v-for="(item, i) in pathPlan.medium" :key="item.concept" class="flex items-center gap-3 p-3 rounded-xl hover:bg-amber-50 transition-all cursor-pointer border border-transparent hover:border-amber-200" @click="goLearn(item.concept)">
            <div class="flex-1 flex items-center gap-3">
              <span class="text-xs text-gray-600 w-24">{{ item.concept }}</span>
              <div class="flex-1 h-2 bg-gray-100 rounded-full overflow-hidden">
                <div class="h-full rounded-full bg-amber-500" :style="{ width: item.score + '%' }" />
              </div>
              <span class="text-xs font-mono text-amber-600 w-10 text-right">{{ item.score }}%</span>
            </div>
            <ChevronRight :size="14" class="text-gray-300 shrink-0" />
          </div>
        </div>
      </div>

      <!-- 已掌握 -->
      <div class="bg-white rounded-2xl border border-gray-100 shadow-sm p-5">
        <h3 class="text-sm font-semibold text-gray-800 mb-3 flex items-center gap-2"><CheckCircle2 :size="16" class="text-emerald-500" /> 已掌握（&gt; 70%）</h3>
        <div class="flex flex-wrap gap-2">
          <span v-for="item in pathPlan.strong" :key="item.concept" class="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg text-xs font-medium bg-emerald-50 text-emerald-700">
            {{ item.concept }}
          </span>
          <span v-if="!pathPlan.strong.length" class="text-xs text-gray-400">暂无</span>
        </div>
      </div>

    </div>
  </div>
</template>
