<script setup>
import { ref, onMounted, computed } from 'vue'
import { 
  getWrongQuestions, getWrongConcepts, 
  generateFlashcard, generateSimilarQuiz, evaluateQuizAnswer 
} from '../api'
import { 
  XCircle, AlertTriangle, Search, Filter, ChevronDown, ChevronUp, BookOpen,
  Sparkles, BrainCircuit, Play, CheckCircle, Loader2 
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
          @click="toggleExpand(q)"
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

              <!-- 答题区 -->
              <div v-else class="flex flex-col justify-between h-[320px] rounded-2xl border border-amber-200 bg-amber-50/30 p-5 shadow-sm">
                <!-- 题目内容 -->
                <div class="overflow-y-auto max-h-[160px] pr-1 text-sm text-gray-800 leading-relaxed font-medium">
                  {{ similarQuizzes[q.id].question }}
                </div>

                <!-- 答题交互 -->
                <div class="space-y-3 pt-3 border-t border-amber-100">
                  <!-- 选择题选项 -->
                  <div v-if="similarQuizzes[q.id].options && similarQuizzes[q.id].options.length > 0" class="grid grid-cols-2 gap-2">
                    <label 
                      v-for="opt in similarQuizzes[q.id].options" 
                      :key="opt"
                      class="flex items-center gap-2 p-2 rounded-lg border bg-white cursor-pointer hover:border-amber-400 transition-colors text-xs text-gray-700"
                      :class="{ 'border-amber-500 bg-amber-50/50': similarAnswers[q.id] === opt[0] }"
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
                    />
                  </div>

                  <!-- 自信度滑动条 -->
                  <div class="flex items-center justify-between text-[10px] text-gray-500">
                    <span>自信度: {{ similarConfidences[q.id] }}0%</span>
                    <input 
                      type="range" 
                      min="1" 
                      max="10" 
                      v-model="similarConfidences[q.id]" 
                      class="w-32 accent-amber-500 cursor-pointer"
                    />
                  </div>

                  <!-- 结果显示 -->
                  <div v-if="similarResults[q.id]" class="text-xs p-2.5 rounded-lg border" :class="similarResults[q.id].accuracy_score >= 0.7 ? 'bg-emerald-50 border-emerald-200 text-emerald-700' : 'bg-red-50 border-red-200 text-red-700'">
                    <div class="flex items-center gap-1.5 font-bold mb-1">
                      <CheckCircle v-if="similarResults[q.id].accuracy_score >= 0.7" :size="14" />
                      <XCircle v-else :size="14" />
                      <span>正确率: {{ (similarResults[q.id].accuracy_score * 100).toFixed(0) }}% ({{ similarResults[q.id].accuracy_score >= 0.7 ? '挑战成功' : '挑战未通过' }})</span>
                    </div>
                    <p class="text-[11px] leading-relaxed opacity-90">{{ similarResults[q.id].feedback }}</p>
                  </div>

                  <!-- 操作按钮 -->
                  <div v-else class="flex justify-end gap-2">
                    <button 
                      @click="startSimilarChallenge(q)"
                      class="px-3 py-1.5 text-xs font-semibold rounded-lg bg-gray-100 hover:bg-gray-200 text-gray-600 transition-colors"
                    >
                      重新生成
                    </button>
                    <button 
                      @click="submitSimilarAnswer(q)"
                      :disabled="!similarAnswers[q.id] || similarSubmitting[q.id]"
                      class="px-4 py-1.5 text-xs font-semibold rounded-lg bg-amber-500 hover:bg-amber-600 text-white shadow-sm active:scale-95 disabled:opacity-50 transition-all flex items-center gap-1"
                    >
                      <Loader2 v-if="similarSubmitting[q.id]" :size="12" class="animate-spin" />
                      <span>提交评估</span>
                    </button>
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
