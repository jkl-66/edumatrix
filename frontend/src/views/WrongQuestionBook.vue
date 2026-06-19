<script setup>
import { ref, onMounted, computed } from 'vue'
import { getWrongQuestions, getWrongConcepts } from '../api'
import { XCircle, AlertTriangle, Search, Filter, ChevronDown, ChevronUp, BookOpen } from '@lucide/vue'

const props = defineProps({ studentId: String })

const wrongQuestions = ref([])
const conceptStats = ref([])
const loading = ref(true)
const filterConcept = ref('')
const expandedItems = ref(new Set())
const detailLoading = ref(false)

const uniqueConcepts = computed(() => {
  return conceptStats.value.map(c => c.concept)
})

const filteredQuestions = computed(() => {
  if (!filterConcept.value) return wrongQuestions.value
  return wrongQuestions.value.filter(q => q.concept_name === filterConcept.value)
})

async function loadData() {
  loading.value = true
  try {
    const [questions, stats] = await Promise.all([
      getWrongQuestions(props.studentId),
      getWrongConcepts(props.studentId),
    ])
    wrongQuestions.value = questions || []
    conceptStats.value = stats || []
  } catch (e) {
    console.error('加载错题失败:', e)
  } finally {
    loading.value = false
  }
}

function toggleExpand(id) {
  const s = new Set(expandedItems.value)
  s.has(id) ? s.delete(id) : s.add(id)
  expandedItems.value = s
}

function getCategoryLabel(cat) {
  const labels = {
    review: '需复习',
    practice: '需练习',
    advance: '可进阶',
  }
  return labels[cat] || cat || '未分类'
}

function getCategoryColor(cat) {
  const colors = {
    review: 'bg-red-50 text-red-600',
    practice: 'bg-amber-50 text-amber-600',
    advance: 'bg-emerald-50 text-emerald-600',
  }
  return colors[cat] || 'bg-gray-50 text-gray-600'
}

onMounted(loadData)
</script>

<template>
  <div class="space-y-6 max-w-4xl">
    <!-- Header -->
    <div class="flex items-center gap-3">
      <XCircle :size="24" class="text-red-500" />
      <div>
        <h2 class="text-lg font-semibold text-gray-800">错题本</h2>
        <p class="text-xs text-gray-400 mt-0.5">按概念筛选，查看微步断点分析</p>
      </div>
    </div>

    <!-- Concept Stats -->
    <div v-if="conceptStats.length > 0" class="grid grid-cols-2 md:grid-cols-4 gap-3">
      <div
        v-for="stat in conceptStats"
        :key="stat.concept"
        class="card flex items-center gap-3 cursor-pointer hover:border-red-200 transition-colors"
        :class="{ 'border-red-300': filterConcept === stat.concept }"
        @click="filterConcept = filterConcept === stat.concept ? '' : stat.concept"
      >
        <div class="w-8 h-8 rounded-lg bg-red-50 flex items-center justify-center">
          <AlertTriangle :size="16" class="text-red-500" />
        </div>
        <div class="min-w-0">
          <p class="text-sm font-medium text-gray-800 truncate">{{ stat.concept }}</p>
          <p class="text-xs text-gray-400">{{ stat.count }} 道错题</p>
        </div>
      </div>
    </div>

    <!-- Filter -->
    <div v-if="uniqueConcepts.length > 0" class="flex items-center gap-2">
      <Filter :size="14" class="text-gray-400" />
      <select
        v-model="filterConcept"
        class="input text-sm py-1.5 px-3 max-w-xs"
      >
        <option value="">全部概念</option>
        <option v-for="c in uniqueConcepts" :key="c" :value="c">{{ c }}</option>
      </select>
      <p class="text-xs text-gray-400 ml-auto">{{ filteredQuestions.length }} 条记录</p>
    </div>

    <!-- Loading -->
    <div v-if="loading" class="flex items-center justify-center py-12">
      <div class="pulse-dot" />
      <span class="ml-3 text-gray-400 text-sm">加载错题数据...</span>
    </div>

    <!-- Empty -->
    <div v-else-if="filteredQuestions.length === 0" class="card text-center py-12">
      <BookOpen :size="32" class="mx-auto text-gray-300 mb-3" />
      <p class="text-sm text-gray-500">暂无错题记录</p>
      <p class="text-xs text-gray-400 mt-1">完成测验后，错题将自动归档到这里</p>
    </div>

    <!-- Wrong Questions List -->
    <div v-else class="space-y-3">
      <div
        v-for="q in filteredQuestions"
        :key="q.id"
        class="card overflow-hidden"
      >
        <div
          class="flex items-start justify-between cursor-pointer"
          @click="toggleExpand(q.id)"
        >
          <div class="flex items-start gap-3 min-w-0 flex-1">
            <div class="w-8 h-8 rounded-lg bg-red-50 flex items-center justify-center shrink-0 mt-0.5">
              <XCircle :size="16" class="text-red-500" />
            </div>
            <div class="min-w-0 flex-1">
              <p class="text-sm font-medium text-gray-800 truncate">{{ q.concept_name }}</p>
              <div class="flex items-center gap-2 mt-1">
                <span
                  class="text-[10px] px-2 py-0.5 rounded-full font-medium"
                  :class="getCategoryColor(q.wrong_reason_category)"
                >{{ getCategoryLabel(q.wrong_reason_category) }}</span>
                <span class="text-[10px] text-gray-400">{{ q.created_at ? new Date(q.created_at).toLocaleString() : '' }}</span>
              </div>
            </div>
          </div>
          <div class="text-gray-400 shrink-0 ml-2">
            <ChevronDown v-if="!expandedItems.has(q.id)" :size="16" />
            <ChevronUp v-else :size="16" />
          </div>
        </div>

        <!-- Expanded Detail -->
        <div v-if="expandedItems.has(q.id) && q.quiz_detail" class="mt-3 pt-3 border-t border-gray-100 space-y-2">
          <div class="bg-gray-50 rounded-lg p-3">
            <p class="text-[11px] text-gray-500 font-medium mb-1">题目</p>
            <p class="text-sm text-gray-700">{{ q.quiz_detail.question }}</p>
          </div>
          <div class="grid grid-cols-2 gap-2">
            <div class="bg-red-50 rounded-lg p-3">
              <p class="text-[11px] text-red-500 font-medium mb-1">❌ 你的答案</p>
              <p class="text-sm text-gray-700">{{ q.quiz_detail.student_answer || '未作答' }}</p>
            </div>
            <div class="bg-emerald-50 rounded-lg p-3">
              <p class="text-[11px] text-emerald-600 font-medium mb-1">✅ 参考答案</p>
              <p class="text-sm text-gray-700">{{ q.quiz_detail.correct_answer || '-' }}</p>
            </div>
          </div>
          <div v-if="q.quiz_detail.feedback" class="bg-blue-50 rounded-lg p-3">
            <p class="text-[11px] text-blue-500 font-medium mb-1">💡 诊断反馈</p>
            <p class="text-sm text-gray-700">{{ q.quiz_detail.feedback }}</p>
          </div>
          <div class="bg-amber-50 rounded-lg p-3">
            <p class="text-[11px] text-amber-600 font-medium mb-1">📊 准确率</p>
            <div class="flex items-center gap-2">
              <div class="flex-1 h-2 bg-gray-200 rounded-full overflow-hidden">
                <div
                  class="h-full rounded-full transition-all"
                  :class="(q.quiz_detail.accuracy_score || 0) >= 0.6 ? 'bg-emerald-500' : 'bg-red-500'"
                  :style="{ width: ((q.quiz_detail.accuracy_score || 0) * 100) + '%' }"
                />
              </div>
              <span class="text-xs font-medium" :class="(q.quiz_detail.accuracy_score || 0) >= 0.6 ? 'text-emerald-600' : 'text-red-600'">
                {{ ((q.quiz_detail.accuracy_score || 0) * 100).toFixed(0) }}%
              </span>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
