<script setup>
import { ref, onMounted, onUnmounted, computed, watch, nextTick } from 'vue'
import * as echarts from 'echarts'
import { 
  getWrongQuestions, getWrongConcepts, 
  generateFlashcard, generateSimilarQuiz, evaluateQuizAnswer,
  appendWrongQuestionReflection,
  deleteWrongQuestion, togglePinWrongQuestion, updateWrongQuestionNotes
} from '../api'
import { 
  XCircle, AlertTriangle, Search, Filter, ChevronDown, ChevronUp, BookOpen,
  Sparkles, BrainCircuit, Play, CheckCircle, Loader2, RotateCw,
  Pin, PinOff, Trash2, Pencil, Save, X
} from '@lucide/vue'
import AnkiFlashcard from '../components/AnkiFlashcard.vue'

const props = defineProps({ studentId: String })

const wrongQuestions = ref([])
const conceptStats = ref([])
const loading = ref(true)
const filterConcept = ref('')
const expandedItems = ref(new Set())
const detailLoading = ref(false)

// Anki and Similar Quiz States
const flashcards = ref({})
const flashcardLoading = ref({})
const similarQuizzes = ref({})
const similarLoading = ref({})
const similarAnswers = ref({})
const similarConfidences = ref({})
const similarResults = ref({})
const similarSubmitting = ref({})
const similarFlipped = ref({})

// 置顶 / 删除 / 笔记 状态
const pinLoading = ref({})
const deleteLoading = ref({})
const editingNotes = ref({})
const notesText = ref({})

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

async function toggleExpand(q) {
  const id = q.id
  const s = new Set(expandedItems.value)
  if (s.has(id)) {
    s.delete(id)
  } else {
    s.add(id)
    if (!flashcards.value[id]) {
      loadOrGenerateFlashcard(q)
    }
  }
  expandedItems.value = s
}

async function loadOrGenerateFlashcard(q) {
  const id = q.id
  flashcardLoading.value[id] = true
  try {
    const res = await generateFlashcard(props.studentId, q.quiz_record_id)
    flashcards.value[id] = res.flashcard
  } catch (e) {
    console.error('加载或生成闪卡失败:', e)
  } finally {
    flashcardLoading.value[id] = false
  }
}

function handleFlashcardReviewed(id, res) {
  if (res && res.flashcard) {
    flashcards.value[id] = res.flashcard
  }
}

async function startSimilarChallenge(q) {
  const id = q.id
  similarLoading.value[id] = true
  similarResults.value[id] = null
  similarAnswers.value[id] = ''
  similarConfidences.value[id] = 5
  try {
    const res = await generateSimilarQuiz(props.studentId, q.quiz_record_id, q.concept_name)
    similarQuizzes.value[id] = res
  } catch (e) {
    console.error('生成相似题失败:', e)
  } finally {
    similarLoading.value[id] = false
  }
}

async function submitSimilarAnswer(q) {
  const id = q.id
  const quiz = similarQuizzes.value[id]
  const answer = similarAnswers.value[id]
  const confidence = similarConfidences.value[id]
  if (!answer || !answer.trim()) return
  
  similarSubmitting.value[id] = true
  try {
    const res = await evaluateQuizAnswer(
      quiz.quiz_id,
      props.studentId,
      answer,
      confidence / 10,
      1,
      q.quiz_record_id // 关联原错题ID，答对时自动消解原题紧迫度
    )
    similarResults.value[id] = res
    if (res.accuracy_score >= 0.7) {
      // 答对后自动刷新错题本状态以更新复习紧迫度
      loadData()
    }
  } catch (e) {
    console.error('提交相似题评估失败:', e)
  } finally {
    similarSubmitting.value[id] = false
  }
}

function getCategoryLabel(cat) {
  const labels = {
    review: '概念未掌握',
    practice: '熟练度不足',
    advance: '粗心/笔误',
    misconception: '概念误解',
    unknown: '未分类',
  }
  return labels[cat] || cat || '未分类'
}

function getCategoryColor(cat) {
  const colors = {
    review: 'bg-red-50 text-red-600',
    practice: 'bg-amber-50 text-amber-600',
    advance: 'bg-emerald-50 text-emerald-600',
    misconception: 'bg-purple-50 text-purple-600',
  }
  return colors[cat] || 'bg-gray-50 text-gray-600'
}

// 矩阵闭环学习流：记入笔记反思相关状态与方法
const reflectionLoading = ref({})
const reflectionAppended = ref({})

async function appendReflectionToNote(q) {
  const id = q.id
  reflectionLoading.value[id] = true
  try {
    await appendWrongQuestionReflection({
      student_id: props.studentId,
      concept: q.concept_name,
      quiz_record_id: q.quiz_record_id,
      wrong_reason: q.wrong_reason_category || 'misconception'
    })
    reflectionAppended.value[id] = true
    alert(`已成功将错题反思自动追加到 [${q.concept_name} 错题集] 笔记中！`)
  } catch (e) {
    console.error('记入笔记反思失败:', e)
    alert('记入笔记反思失败: ' + (e.response?.data?.detail || e.message || e))
  } finally {
    reflectionLoading.value[id] = false
  }
}

// 置顶/取消置顶
async function togglePin(q) {
  const id = q.id
  pinLoading.value[id] = true
  try {
    const res = await togglePinWrongQuestion(id, props.studentId)
    // 刷新列表以按新排序展示
    await loadData()
  } catch (e) {
    console.error('置顶操作失败:', e)
  } finally {
    pinLoading.value[id] = false
  }
}

// 删除错题
async function deleteQuestion(q) {
  const id = q.id
  if (!confirm(`确定删除「${q.concept_name}」的这条错题记录吗？`)) return
  deleteLoading.value[id] = true
  try {
    await deleteWrongQuestion(id, props.studentId)
    await loadData()
  } catch (e) {
    console.error('删除错题失败:', e)
    alert('删除失败: ' + (e.response?.data?.detail || e.message || e))
  } finally {
    deleteLoading.value[id] = false
  }
}

// 开始编辑笔记
function startEditNotes(q) {
  const id = q.id
  editingNotes.value[id] = true
  notesText.value[id] = q.notes || ''
}

// 取消编辑笔记
function cancelEditNotes(q) {
  const id = q.id
  editingNotes.value[id] = false
  notesText.value[id] = ''
}

// 保存笔记
async function saveNotes(q) {
  const id = q.id
  try {
    await updateWrongQuestionNotes(id, notesText.value[id] || '', props.studentId)
    q.notes = notesText.value[id] || ''
    editingNotes.value[id] = false
  } catch (e) {
    console.error('保存笔记失败:', e)
    alert('保存笔记失败: ' + (e.response?.data?.detail || e.message || e))
  }
}

function toggleSimilarCard(q) {
  if (similarResults.value[q.id]) {
    const s = !similarFlipped.value[q.id]
    similarFlipped.value[q.id] = s
  }
}

// === 任务 10: 错题本错因诊断图谱与聚类大盘 ===
const showDiagnosisDashboard = ref(false)

const diagnosisClusters = computed(() => {
  const clusters = {}
  for (const q of wrongQuestions.value) {
    const cat = q.wrong_reason_category || 'unknown'
    if (!clusters[cat]) {
      clusters[cat] = { label: getCategoryLabel(cat), count: 0, concepts: new Set(), total: 0 }
    }
    clusters[cat].count++
    clusters[cat].concepts.add(q.concept_name)
    clusters[cat].total += (q.quiz_detail?.accuracy_score || 0)
  }
  return Object.entries(clusters).map(([key, val]) => ({
    key,
    label: val.label,
    count: val.count,
    conceptCount: val.concepts.size,
    totalAccuracy: val.total,
    avgAccuracy: val.count > 0 ? val.total / val.count : 0,
    concepts: [...val.concepts],
  }))
})

const diagnosisTopConcepts = computed(() => {
  const conceptMap = {}
  for (const q of wrongQuestions.value) {
    const concept = q.concept_name
    if (!conceptMap[concept]) {
      conceptMap[concept] = { count: 0, categories: {} }
    }
    conceptMap[concept].count++
    const cat = q.wrong_reason_category || 'unknown'
    conceptMap[concept].categories[cat] = (conceptMap[concept].categories[cat] || 0) + 1
  }
  return Object.entries(conceptMap)
    .sort((a, b) => b[1].count - a[1].count)
    .slice(0, 10)
    .map(([concept, info]) => ({
      concept,
      count: info.count,
      categories: info.categories,
    }))
})

const diagnosisSummary = computed(() => {
  const total = wrongQuestions.value.length
  if (total === 0) return null
  const reviewCount = wrongQuestions.value.filter(q => q.wrong_reason_category === 'review').length
  const practiceCount = wrongQuestions.value.filter(q => q.wrong_reason_category === 'practice').length
  const advanceCount = wrongQuestions.value.filter(q => q.wrong_reason_category === 'advance').length
  const avgAccuracy = wrongQuestions.value.reduce((s, q) => s + (q.quiz_detail?.accuracy_score || 0), 0) / total
  const avgConfidence = wrongQuestions.value.reduce((s, q) => {
    const sim = similarResults.value[q.id]
    return s + (sim?.student_confidence || 0.5)
  }, 0) / total
  return {
    total,
    reviewCount,
    practiceCount,
    advanceCount,
    avgAccuracy,
    avgConfidence,
    conceptsCovered: new Set(wrongQuestions.value.map(q => q.concept_name)).size,
  }
})

const clusterColors = {
  review: { bg: 'bg-red-50', text: 'text-red-600', bar: 'bg-red-400', border: 'border-red-200' },
  practice: { bg: 'bg-amber-50', text: 'text-amber-600', bar: 'bg-amber-400', border: 'border-amber-200' },
  advance: { bg: 'bg-emerald-50', text: 'text-emerald-600', bar: 'bg-emerald-400', border: 'border-emerald-200' },
  misconception: { bg: 'bg-purple-50', text: 'text-purple-600', bar: 'bg-purple-400', border: 'border-purple-200' },
  unknown: { bg: 'bg-gray-50', text: 'text-gray-500', bar: 'bg-gray-300', border: 'border-gray-200' },
}

// ECharts Chart Reference and Instance
const chartRef = ref(null)
let chartInstance = null

function initOrUpdateChart() {
  if (!showDiagnosisDashboard.value) return
  
  nextTick(() => {
    if (!showDiagnosisDashboard.value || !chartRef.value) return
    try {
      const isDark = document.documentElement.classList.contains('dark') || document.body.classList.contains('dark')
      if (chartInstance) {
        chartInstance.dispose()
        chartInstance = null
      }
      chartInstance = echarts.init(chartRef.value, isDark ? 'dark' : null, { backgroundColor: 'transparent' })
      
      const colorMap = {
        review: '#f87171',
        practice: '#fbbf24',
        advance: '#34d399',
        misconception: '#a78bfa',
      }
      
      const pieData = diagnosisClusters.value.map(c => ({
        value: c.count,
        name: c.label,
        itemStyle: { color: colorMap[c.key] || '#94a3b8' }
      }))
      
      const option = {
        tooltip: {
          trigger: 'item',
          formatter: '{b}: {c} ({d}%)'
        },
        legend: {
          bottom: '0%',
          left: 'center',
          textStyle: { color: isDark ? '#9ca3af' : '#6b7280', fontSize: 10 }
        },
        series: [
          {
            name: '错因归类',
            type: 'pie',
            radius: ['45%', '70%'],
            avoidLabelOverlap: false,
            itemStyle: {
              borderRadius: 6,
              borderColor: isDark ? 'transparent' : '#fff',
              borderWidth: 2
            },
            label: {
              show: false,
              position: 'center'
            },
            emphasis: {
              label: {
                show: true,
                fontSize: 11,
                fontWeight: 'bold'
              }
            },
            labelLine: {
              show: false
            },
            data: pieData
          }
        ]
      }
      chartInstance.setOption(option)
    } catch (err) {
      console.error('ECharts init error:', err)
    }
  })
}

watch([showDiagnosisDashboard, wrongQuestions], () => {
  if (showDiagnosisDashboard.value) {
    initOrUpdateChart()
  } else {
    if (chartInstance) {
      chartInstance.dispose()
      chartInstance = null
    }
  }
})

const handleResize = () => {
  if (chartInstance && typeof chartInstance.resize === 'function') {
    chartInstance.resize()
  }
}

onMounted(() => {
  loadData()
  window.addEventListener('resize', handleResize)
})

onUnmounted(() => {
  window.removeEventListener('resize', handleResize)
  if (chartInstance) {
    chartInstance.dispose()
    chartInstance = null
  }
})
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

    <!-- === 任务 10: 错题本错因诊断图谱与聚类大盘 === -->
    <div v-if="wrongQuestions.length > 0" class="card overflow-hidden">
      <div
        class="flex items-center justify-between cursor-pointer"
        @click="showDiagnosisDashboard = !showDiagnosisDashboard"
      >
        <div class="flex items-center gap-2">
          <div class="w-7 h-7 rounded-lg bg-gradient-to-br from-violet-400 to-indigo-500 flex items-center justify-center">
            <Sparkles :size="14" class="text-white" />
          </div>
          <span class="text-sm font-semibold text-gray-700">错因诊断图谱与聚类大盘</span>
          <span v-if="diagnosisSummary" class="text-[10px] text-gray-400 ml-1">
            {{ diagnosisSummary.total }} 题 · {{ diagnosisSummary.conceptsCovered }} 概念
          </span>
        </div>
        <ChevronDown v-if="!showDiagnosisDashboard" :size="16" class="text-gray-400" />
        <ChevronUp v-else :size="16" class="text-gray-400" />
      </div>

      <div v-if="showDiagnosisDashboard && diagnosisSummary" class="mt-4 space-y-4">
        <!-- 总览与图表 (ECharts 环形图并网) -->
        <div class="grid grid-cols-1 md:grid-cols-2 gap-4 items-center bg-gray-50/30 p-4 rounded-xl border border-gray-100/80">
          <!-- ECharts 环形图 -->
          <div class="flex flex-col items-center justify-center p-2 bg-white rounded-xl border border-gray-100 shadow-sm">
            <p class="text-[11px] font-semibold text-gray-500 mb-1">错因分类诊断图</p>
            <div ref="chartRef" class="w-full h-40"></div>
          </div>

          <!-- 总览与指标 -->
          <div class="space-y-3">
            <div class="grid grid-cols-3 gap-2">
              <div class="bg-red-50/60 rounded-xl p-2.5 text-center border border-red-100">
                <p class="text-xl font-bold text-red-600">{{ diagnosisSummary.reviewCount }}</p>
                <p class="text-[9px] text-red-500 font-medium">概念未掌握</p>
              </div>
              <div class="bg-amber-50/60 rounded-xl p-2.5 text-center border border-amber-100">
                <p class="text-xl font-bold text-amber-600">{{ diagnosisSummary.practiceCount }}</p>
                <p class="text-[9px] text-amber-500 font-medium">熟练度不足</p>
              </div>
              <div class="bg-emerald-50/60 rounded-xl p-2.5 text-center border border-emerald-100">
                <p class="text-xl font-bold text-emerald-600">{{ diagnosisSummary.advanceCount }}</p>
                <p class="text-[9px] text-emerald-500 font-medium">粗心/笔误</p>
              </div>
            </div>
            
            <div class="bg-white p-3 rounded-xl border border-gray-100 space-y-1.5 text-xs text-gray-500 shadow-sm">
              <div class="flex justify-between">
                <span>平均答题准确率:</span>
                <span class="font-semibold text-gray-700">{{ (diagnosisSummary.avgAccuracy * 100).toFixed(1) }}%</span>
              </div>
              <div class="flex justify-between">
                <span>覆盖核心概念数:</span>
                <span class="font-semibold text-gray-700">{{ diagnosisSummary.conceptsCovered }} 个</span>
              </div>
              <div class="flex justify-between">
                <span>时序诊断偏置 (EMA):</span>
                <span class="font-semibold text-gray-700">
                  {{ (diagnosisSummary.avgConfidence - diagnosisSummary.avgAccuracy).toFixed(2) }}
                </span>
              </div>
            </div>
          </div>
        </div>

        <!-- 聚类条形图 -->
        <div class="space-y-2">
          <p class="text-[11px] font-semibold text-gray-600">错因聚类分布</p>
          <div v-for="cluster in diagnosisClusters" :key="cluster.key" class="flex items-center gap-2">
            <span class="text-[10px] w-12 text-right font-medium" :class="(clusterColors[cluster.key] || clusterColors.unknown).text">
              {{ cluster.label }}
            </span>
            <div class="flex-1 h-5 bg-gray-100 rounded-full overflow-hidden">
              <div
                class="h-full rounded-full transition-all duration-500"
                :class="(clusterColors[cluster.key] || clusterColors.unknown).bar"
                :style="{ width: Math.max((cluster.count / diagnosisSummary.total) * 100, 4) + '%' }"
              ></div>
            </div>
            <span class="text-[10px] text-gray-500 w-8">{{ cluster.count }}</span>
          </div>
        </div>

        <!-- Top 10 高频错题概念 -->
        <div class="space-y-2">
          <p class="text-[11px] font-semibold text-gray-600">高频错题概念 Top 10</p>
          <div class="space-y-1.5">
            <div v-for="(item, idx) in diagnosisTopConcepts" :key="item.concept"
              class="flex items-center gap-2 p-2 rounded-lg hover:bg-gray-50 cursor-pointer"
              @click="filterConcept = item.concept"
            >
              <span class="text-[10px] font-bold w-5 text-gray-400">#{{ idx + 1 }}</span>
              <span class="text-xs text-gray-700 flex-1 truncate">{{ item.concept }}</span>
              <span class="text-[10px] font-semibold text-gray-500">{{ item.count }} 题</span>
              <div class="flex gap-0.5">
                <span v-if="item.categories.review" class="w-2 h-2 rounded-full bg-red-400" title="概念未掌握"></span>
                <span v-if="item.categories.practice" class="w-2 h-2 rounded-full bg-amber-400" title="熟练度不足"></span>
                <span v-if="item.categories.advance" class="w-2 h-2 rounded-full bg-emerald-400" title="粗心/笔误"></span>
              </div>
            </div>
          </div>
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
      <span class="pulse-dot" />
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
        :class="{ 'border-amber-300 bg-amber-50/30': q.pinned }"
      >
        <div class="flex items-start justify-between">
          <!-- 置顶按钮 -->
          <button
            @click.stop="togglePin(q)"
            :disabled="pinLoading[q.id]"
            class="shrink-0 mt-0.5 mr-2 p-1 rounded-md transition-colors"
            :class="q.pinned ? 'text-amber-500 hover:text-amber-600' : 'text-gray-300 hover:text-amber-400'"
            :title="q.pinned ? '取消置顶' : '置顶关注'"
          >
            <Loader2 v-if="pinLoading[q.id]" :size="16" class="animate-spin" />
            <Pin v-else-if="q.pinned" :size="16" />
            <PinOff v-else :size="16" />
          </button>

          <div
            class="flex items-start gap-3 min-w-0 flex-1 cursor-pointer"
            @click="toggleExpand(q)"
          >
            <div class="w-8 h-8 rounded-lg bg-red-50 flex items-center justify-center shrink-0 mt-0.5">
              <XCircle :size="16" class="text-red-500" />
            </div>
            <div class="min-w-0 flex-1">
              <div class="flex items-center gap-1.5">
                <p class="text-sm font-medium text-gray-800 truncate">{{ q.concept_name }}</p>
                <span v-if="q.pinned" class="text-[10px] px-1.5 py-0.5 rounded-full bg-amber-100 text-amber-700 font-semibold shrink-0">置顶</span>
              </div>
              <div class="flex items-center gap-2 mt-1">
                <span
                  class="text-[10px] px-2 py-0.5 rounded-full font-medium"
                  :class="getCategoryColor(q.wrong_reason_category)"
                >{{ getCategoryLabel(q.wrong_reason_category) }}</span>
                <span class="text-[10px] text-gray-400">{{ q.created_at ? new Date(q.created_at).toLocaleString() : '' }}</span>
              </div>
            </div>
          </div>
          <div class="flex items-center gap-1 shrink-0 ml-2">
            <!-- 删除按钮 -->
            <button
              @click.stop="deleteQuestion(q)"
              :disabled="deleteLoading[q.id]"
              class="p-1.5 rounded-md text-gray-300 hover:text-red-500 hover:bg-red-50 transition-colors"
              title="删除错题"
            >
              <Loader2 v-if="deleteLoading[q.id]" :size="14" class="animate-spin" />
              <Trash2 v-else :size="14" />
            </button>
            <div class="text-gray-400 cursor-pointer" @click="toggleExpand(q)">
              <ChevronDown v-if="!expandedItems.has(q.id)" :size="16" />
              <ChevronUp v-else :size="16" />
            </div>
          </div>
        </div>

        <!-- Expanded Detail (3D 信封折叠) -->
        <div
          class="envelope-fold"
          :class="{ 'envelope-open': expandedItems.has(q.id) }"
        >
          <div class="envelope-inner" v-if="expandedItems.has(q.id) && q.quiz_detail">
            <div class="mt-3 pt-3 border-t border-gray-100 space-y-2">
          <div class="bg-gray-50 rounded-lg p-3">
            <p class="text-[11px] text-gray-500 font-medium mb-1">题目</p>
            <p class="text-sm text-gray-700">{{ q.quiz_detail.question }}</p>
            <!-- 选择题选项 -->
            <div v-if="q.quiz_detail.options && q.quiz_detail.options.length > 0" class="mt-2 space-y-1">
              <p class="text-[10px] text-gray-400 font-medium mb-1">选项</p>
              <div 
                v-for="opt in q.quiz_detail.options" 
                :key="opt"
                class="text-xs px-2.5 py-1 rounded-md"
                :class="opt.startsWith(q.quiz_detail.correct_answer) || opt[0] === q.quiz_detail.correct_answer
                  ? 'bg-emerald-50 text-emerald-700 font-semibold border border-emerald-200'
                  : (opt.startsWith(q.quiz_detail.student_answer) || opt[0] === q.quiz_detail.student_answer)
                    ? 'bg-red-50 text-red-700 border border-red-200'
                    : 'bg-white text-gray-600 border border-gray-100'"
              >
                <span class="text-[10px] mr-1.5" :class="opt.startsWith(q.quiz_detail.correct_answer) || opt[0] === q.quiz_detail.correct_answer ? 'text-emerald-500' : 'text-gray-400'">
                  {{ opt.startsWith(q.quiz_detail.correct_answer) || opt[0] === q.quiz_detail.correct_answer ? '✓' : '' }}
                </span>
                {{ opt }}
              </div>
            </div>
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
                <span
                  class="h-full rounded-full transition-all block"
                  :class="(q.quiz_detail.accuracy_score || 0) >= 0.6 ? 'bg-emerald-500' : 'bg-red-500'"
                  :style="{ width: ((q.quiz_detail.accuracy_score || 0) * 100) + '%' }"
                ></span>
              </div>
              <span class="text-xs font-medium" :class="(q.quiz_detail.accuracy_score || 0) >= 0.6 ? 'text-emerald-600' : 'text-red-600'">
                {{ ((q.quiz_detail.accuracy_score || 0) * 100).toFixed(0) }}%
              </span>
            </div>
          </div>

          <!-- 个人笔记 -->
          <div class="bg-violet-50 rounded-lg p-3 border border-violet-100">
            <div class="flex items-center justify-between mb-2">
              <p class="text-[11px] text-violet-600 font-medium flex items-center gap-1">
                <Pencil :size="12" />
                <span>我的笔记</span>
              </p>
              <button
                v-if="!editingNotes[q.id]"
                @click="startEditNotes(q)"
                class="text-[10px] text-violet-500 hover:text-violet-700 font-medium transition-colors"
              >
                {{ q.notes ? '编辑' : '添加笔记' }}
              </button>
            </div>
            <!-- 编辑模式 -->
            <div v-if="editingNotes[q.id]" class="space-y-2">
              <textarea
                v-model="notesText[q.id]"
                rows="3"
                placeholder="记录这道题的易错点、解题思路或心得..."
                class="w-full text-xs rounded-lg border border-violet-200 p-2.5 resize-none focus:outline-none focus:ring-1 focus:ring-violet-400"
              />
              <div class="flex justify-end gap-2">
                <button
                  @click="cancelEditNotes(q)"
                  class="py-1 px-3 text-[10px] font-medium rounded-lg bg-gray-100 hover:bg-gray-200 text-gray-600 transition-colors flex items-center gap-1"
                >
                  <X :size="10" />
                  取消
                </button>
                <button
                  @click="saveNotes(q)"
                  class="py-1 px-3 text-[10px] font-semibold rounded-lg bg-violet-500 hover:bg-violet-600 text-white shadow-sm transition-all flex items-center gap-1"
                >
                  <Save :size="10" />
                  保存
                </button>
              </div>
            </div>
            <!-- 查看模式 -->
            <p v-else-if="q.notes" class="text-xs text-gray-600 leading-relaxed whitespace-pre-wrap">{{ q.notes }}</p>
            <p v-else class="text-[10px] text-gray-400 italic">暂无笔记，点击"添加笔记"记录你的思考</p>
          </div>

          <!-- 矩阵闭环学习流：记入笔记反思 -->
          <div class="flex justify-between items-center bg-slate-50 rounded-lg p-3 border border-slate-100 mt-2">
            <div class="flex flex-col">
              <span class="text-xs font-semibold text-slate-700 flex items-center gap-1">
                <Sparkles :size="12" class="text-indigo-500" />
                <span>矩阵闭环学习流：错题记入笔记反思</span>
              </span>
              <span class="text-[10px] text-slate-400 mt-0.5">将错题、解析及系统错因诊断一键沉淀为该概念的学习笔记</span>
            </div>
            <button
              @click="appendReflectionToNote(q)"
              :disabled="reflectionLoading[q.id] || reflectionAppended[q.id]"
              class="py-1.5 px-4 text-xs font-semibold rounded-lg shadow-sm transition-all active:scale-95 flex items-center gap-1.5 shrink-0"
              :class="reflectionAppended[q.id] 
                ? 'bg-emerald-50 border border-emerald-200 text-emerald-600 cursor-not-allowed'
                : 'bg-indigo-600 hover:bg-indigo-700 text-white disabled:opacity-50'"
            >
              <Loader2 v-if="reflectionLoading[q.id]" :size="12" class="animate-spin" />
              <CheckCircle v-else-if="reflectionAppended[q.id]" :size="12" />
              <BookOpen v-else :size="12" />
              <span>{{ reflectionAppended[q.id] ? '已记入笔记反思' : '一键记入笔记反思' }}</span>
            </button>
          </div>

          <!-- 自适应 3D Anki 闪卡与相似题挑战区域 -->
          <div class="grid grid-cols-1 md:grid-cols-2 gap-4 mt-4 pt-4 border-t border-gray-100">
            <!-- Left: Anki Flashcard -->
            <div class="space-y-2">
              <div class="flex items-center gap-1.5 text-xs font-bold text-slate-700">
                <BrainCircuit :size="14" class="text-indigo-500" />
                <span>Anki 主动召回闪卡</span>
              </div>
              
              <!-- 加载中 -->
              <div v-if="flashcardLoading[q.id]" class="flex flex-col items-center justify-center h-[320px] rounded-2xl bg-slate-900/5 border border-dashed border-slate-300">
                <Loader2 :size="24" class="text-indigo-500 animate-spin mb-2" />
                <span class="text-xs text-slate-400">正在生成卡片与诊断信息...</span>
              </div>
              
              <!-- 闪卡组件 -->
              <AnkiFlashcard 
                v-else-if="flashcards[q.id]" 
                :card="flashcards[q.id]" 
                :student-id="props.studentId"
                @reviewed="(res) => handleFlashcardReviewed(q.id, res)"
              />
              
              <!-- 兜底生成按钮 -->
              <div v-else class="flex flex-col items-center justify-center h-[320px] rounded-2xl bg-slate-50 border border-dashed border-slate-200 p-6 text-center">
                <p class="text-xs text-gray-400 mb-4">当前错题还没有生成 Anki 记忆卡</p>
                <button 
                  @click="loadOrGenerateFlashcard(q)"
                  class="py-2 px-4 text-xs font-semibold rounded-xl bg-indigo-600 hover:bg-indigo-700 text-white shadow-md active:scale-95 transition-all flex items-center gap-1.5"
                >
                  <Sparkles :size="12" />
                  生成 Anki 闪卡
                </button>
              </div>
            </div>

            <!-- Right: Similar Quiz Challenge -->
            <div class="space-y-2">
              <div class="flex items-center gap-1.5 text-xs font-bold text-slate-700">
                <Sparkles :size="14" class="text-amber-500" />
                <span>同阶相似题二次重测</span>
              </div>

              <!-- 未开始挑战 -->
              <div v-if="!similarQuizzes[q.id] && !similarLoading[q.id]" class="flex flex-col items-center justify-center h-[320px] rounded-2xl bg-slate-50 border border-dashed border-slate-200 p-6 text-center">
                <p class="text-xs text-gray-400 mb-4">通过智能相似题练习彻底吃透此考点</p>
                <button 
                  @click="startSimilarChallenge(q)"
                  class="py-2 px-4 text-xs font-semibold rounded-xl bg-amber-500 hover:bg-amber-600 text-white shadow-md active:scale-95 transition-all flex items-center gap-1.5"
                >
                  <Play :size="12" />
                  开启相似题挑战
                </button>
              </div>

              <!-- 加载中 -->
              <div v-else-if="similarLoading[q.id]" class="flex flex-col items-center justify-center h-[320px] rounded-2xl bg-slate-900/5 border border-dashed border-slate-300">
                <Loader2 :size="24" class="text-amber-500 animate-spin mb-2" />
                <span class="text-xs text-slate-400">大模型正在结合隔离沙箱出题中...</span>
              </div>

              <!-- 答题区（翻转卡片） -->
              <div v-else class="similar-perspective h-[320px]">
                <div 
                  class="similar-card-inner relative w-full h-full cursor-pointer select-none"
                  :class="{ 'is-flipped': similarResults[q.id] && !similarFlipped[q.id] }"
                  @click="toggleSimilarCard(q)"
                >
                  <!-- ========== 正面：题目 + 答题 ========== -->
                  <div class="similar-card-face similar-card-front absolute inset-0 rounded-2xl border border-amber-200 bg-amber-50/30 p-5 shadow-sm flex flex-col">
                    <div class="overflow-y-auto max-h-[140px] pr-1 text-sm text-gray-800 leading-relaxed font-medium mb-3">
                      {{ similarQuizzes[q.id].question }}
                    </div>

                    <div class="space-y-3 pt-3 border-t border-amber-100 mt-auto">
                  <!-- 选择题选项 -->
                  <div v-if="similarQuizzes[q.id].options && similarQuizzes[q.id].options.length > 0" class="grid grid-cols-2 gap-2">
                    <label 
                      v-for="opt in similarQuizzes[q.id].options" 
                      :key="opt"
                      class="flex items-center gap-2 p-2 rounded-lg border bg-white cursor-pointer hover:border-amber-400 transition-colors text-xs text-gray-700"
                      :class="{ 'border-amber-500 bg-amber-50/50': similarAnswers[q.id] === opt[0] }"
                      @click.stop
                    >
                      <input 
                        type="radio" 
                        :name="'similar-opt-' + q.id" 
                        :value="opt[0]" 
                        v-model="similarAnswers[q.id]"
                        class="accent-amber-500"
                      />
                      <span>{{ opt }}</span>
                    </label>
                  </div>

                  <!-- 主观填空题 -->
                  <div v-else>
                    <input 
                      type="text" 
                      placeholder="请输入你的解答步骤或最终答案..."
                      v-model="similarAnswers[q.id]"
                      class="input text-xs w-full py-2 px-3"
                      @click.stop
                    />
                  </div>

                  <!-- 自信度滑动条 -->
                      <div v-if="!similarResults[q.id]" class="flex items-center justify-between text-[10px] text-gray-500">
                        <span>自信度: {{ similarConfidences[q.id] }}0%</span>
                        <input type="range" min="1" max="10" v-model="similarConfidences[q.id]" class="w-32 accent-amber-500 cursor-pointer" @click.stop />
                      </div>

                      <div v-if="!similarResults[q.id]" class="flex justify-end gap-2">
                        <button @click.stop="startSimilarChallenge(q)" class="px-3 py-1.5 text-xs font-semibold rounded-lg bg-gray-100 hover:bg-gray-200 text-gray-600 transition-colors">重新生成</button>
                        <button @click.stop="submitSimilarAnswer(q)" :disabled="!similarAnswers[q.id] || similarSubmitting[q.id]" class="px-4 py-1.5 text-xs font-semibold rounded-lg bg-amber-500 hover:bg-amber-600 text-white shadow-sm active:scale-95 disabled:opacity-50 transition-all flex items-center gap-1">
                          <Loader2 v-if="similarSubmitting[q.id]" :size="12" class="animate-spin" />
                          <span>提交评估</span>
                        </button>
                      </div>

                      <div v-else class="flex items-center gap-1 text-[10px] text-amber-600 opacity-60">
                        <RotateCw :size="10" />
                        <span>点击卡片翻转查看详细分析</span>
                      </div>
                    </div>
                  </div>

                  <!-- ========== 反面：分析结果 ========== -->
                  <div class="similar-card-face similar-card-back absolute inset-0 rounded-2xl border shadow-sm flex flex-col bg-gradient-to-br from-slate-900 to-slate-800 border-slate-700 text-slate-200 p-5">
                    <div class="flex items-center justify-between mb-3">
                      <div class="flex items-center gap-2">
                        <CheckCircle v-if="similarResults[q.id] && similarResults[q.id].accuracy_score >= 0.7" :size="18" class="text-emerald-400" />
                        <XCircle v-else :size="18" class="text-amber-400" />
                        <span class="font-bold text-sm">
                          正确率: {{ similarResults[q.id] ? (similarResults[q.id].accuracy_score * 100).toFixed(0) : '--' }}%
                        </span>
                      </div>
                      <span class="text-[10px] uppercase font-bold tracking-wider px-2 py-0.5 rounded-full"
                        :class="similarResults[q.id] && similarResults[q.id].accuracy_score >= 0.7 
                          ? 'text-emerald-400 bg-emerald-950/50 border border-emerald-900/50' 
                          : 'text-amber-400 bg-amber-950/50 border border-amber-900/50'"
                      >
                        {{ similarResults[q.id] && similarResults[q.id].accuracy_score >= 0.7 ? '优势分析' : '诊断分析' }}
                      </span>
                    </div>

                    <p class="flex-1 overflow-y-auto text-[12px] leading-relaxed text-slate-300 whitespace-pre-line scrollbar-thin pr-1">
                      {{ similarResults[q.id] ? similarResults[q.id].feedback : '' }}
                    </p>

                    <div class="pt-3 mt-2 border-t border-slate-700/50 flex items-center justify-between text-[10px] text-slate-500">
                      <span v-if="similarResults[q.id]">AI 置信度: {{ (similarResults[q.id].ai_confidence * 100).toFixed(0) }}%</span>
                      <span v-if="similarResults[q.id] && similarResults[q.id].metacognitive_gap">自评偏差: {{ similarResults[q.id].metacognitive_gap }}</span>
                      <span class="flex items-center gap-1 text-slate-400 hover:text-indigo-400 transition-colors cursor-pointer">
                        <RotateCw :size="10" />
                        翻回看题
                      </span>
                    </div>

                    <div class="flex justify-end gap-2 mt-3">
                      <button @click.stop="startSimilarChallenge(q)" class="px-3 py-1.5 text-xs font-semibold rounded-lg bg-slate-700 hover:bg-slate-600 text-slate-200 transition-colors">重新生成</button>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
            </div>
        </div>
      </div>
    </div>
  </div>
</div>
</template>

<style scoped>
.envelope-fold {
  display: grid;
  grid-template-rows: 0fr;
  transition: grid-template-rows 0.5s cubic-bezier(0.34, 1.56, 0.64, 1);
  transform-origin: top center;
  perspective: 800px;
}

.envelope-fold.envelope-open {
  grid-template-rows: 1fr;
}

.envelope-inner {
  overflow: hidden;
  animation: envelopeUnfold 0.6s cubic-bezier(0.34, 1.56, 0.64, 1) forwards;
  transform-origin: top center;
}

@keyframes envelopeUnfold {
  0% {
    opacity: 0;
    transform: rotateX(-90deg) translateY(-20px);
  }
  40% {
    opacity: 0.6;
    transform: rotateX(10deg) translateY(-5px);
  }
  70% {
    transform: rotateX(-3deg) translateY(2px);
  }
  100% {
    opacity: 1;
    transform: rotateX(0deg) translateY(0);
  }
}

.card {
  background: #ffffff;
  border: 1px solid #e5e7eb;
  border-radius: 12px;
  padding: 16px;
  transition: all 0.3s ease;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04);
}

:global(.dark) .card {
  background: rgba(15, 23, 42, 0.4);
  backdrop-filter: blur(12px);
  border-color: rgba(51, 65, 85, 0.5);
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.2);
}

.card:hover {
  border-color: #fca5a5;
  box-shadow: 0 4px 12px rgba(239, 68, 68, 0.08);
}

:global(.dark) .card:hover {
  border-color: rgba(248, 113, 113, 0.6);
  box-shadow: 0 4px 16px rgba(248, 113, 113, 0.12);
}

.card.expanded {
  border-color: #f87171;
  box-shadow: 0 8px 24px rgba(239, 68, 68, 0.12);
}

:global(.dark) .card.expanded {
  border-color: #f87171;
  box-shadow: 0 8px 24px rgba(239, 68, 68, 0.25);
}

/* Fluid Dark Mode Overrides for light-themed Tailwind components inside card */
:global(.dark) h2, :global(.dark) h3, :global(.dark) .text-gray-800 {
  color: #f1f5f9 !important;
}

:global(.dark) .text-gray-700 {
  color: #cbd5e1 !important;
}

:global(.dark) .text-gray-600 {
  color: #94a3b8 !important;
}

:global(.dark) .text-gray-500 {
  color: #64748b !important;
}

:global(.dark) .text-gray-400 {
  color: #94a3b8 !important;
}

:global(.dark) .bg-white {
  background-color: rgba(15, 23, 42, 0.6) !important;
  border-color: rgba(51, 65, 85, 0.5) !important;
}

:global(.dark) .border-gray-100 {
  border-color: rgba(51, 65, 85, 0.4) !important;
}

:global(.dark) .bg-gray-50\/30 {
  background-color: rgba(15, 23, 42, 0.3) !important;
  border-color: rgba(51, 65, 85, 0.4) !important;
}

:global(.dark) .bg-gray-100 {
  background-color: rgba(30, 41, 59, 0.8) !important;
}

:global(.dark) .hover\:bg-gray-50:hover {
  background-color: rgba(30, 41, 59, 0.4) !important;
}

:global(.dark) .bg-red-50 {
  background-color: rgba(239, 68, 68, 0.15) !important;
}

:global(.dark) .bg-red-50\/60 {
  background-color: rgba(239, 68, 68, 0.15) !important;
  border-color: rgba(239, 68, 68, 0.25) !important;
}

:global(.dark) .bg-amber-50\/60 {
  background-color: rgba(245, 158, 11, 0.15) !important;
  border-color: rgba(245, 158, 11, 0.25) !important;
}

:global(.dark) .bg-emerald-50\/60 {
  background-color: rgba(16, 185, 129, 0.15) !important;
  border-color: rgba(16, 185, 129, 0.25) !important;
}

:global(.dark) .border-amber-300.bg-amber-50\/30 {
  border-color: rgba(245, 158, 11, 0.5) !important;
  background-color: rgba(245, 158, 11, 0.08) !important;
}

:global(.dark) select.input {
  background-color: rgba(15, 23, 42, 0.6) !important;
  border-color: rgba(51, 65, 85, 0.5) !important;
  color: #e2e8f0 !important;
}

.chevron-icon {
  transition: transform 0.4s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.chevron-icon.rotated {
  transform: rotate(180deg);
}

/* 相似题整卡翻转 */
.similar-perspective {
  perspective: 800px;
}

.similar-card-inner {
  transition: transform 0.6s cubic-bezier(0.4, 0, 0.2, 1);
  transform-style: preserve-3d;
}

.similar-card-inner.is-flipped {
  transform: rotateY(180deg);
}

.similar-card-face {
  backface-visibility: hidden;
}

.similar-card-back {
  transform: rotateY(180deg);
}

/* 反馈文本滚动条 */
.scrollbar-thin::-webkit-scrollbar {
  width: 3px;
}
.scrollbar-thin::-webkit-scrollbar-track {
  background: transparent;
}
.scrollbar-thin::-webkit-scrollbar-thumb {
  background: rgba(148, 163, 184, 0.3);
  border-radius: 2px;
}
</style>