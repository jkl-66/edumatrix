<script setup>
import { ref, nextTick, computed } from 'vue'
import {
  processMessage, getHistory,
  generateQuiz, evaluateQuizAnswer, adaptQuiz,
  webSearch, loadUrl,
  runCode,
} from '../api'
import {
  Send, Bot, User, Loader2, BookOpen, Code2, LayoutGrid, HelpCircle, Video,
  CheckCircle2, XCircle, AlertTriangle, ChevronDown, ChevronUp,
  Search, Globe, ExternalLink, Terminal, Play, Trash2, MessageSquare,
  BrainCircuit, Target, TrendingUp, Sparkles,
} from '@lucide/vue'
import { useChatStore } from '../stores/chat'

const props = defineProps({ studentId: String })
const chatStore = useChatStore()

// --- Chat State ---
const messages = computed(() => chatStore.messages)
const sending = computed(() => chatStore.sending)
const input = ref('')
const showResources = ref(new Set())
const activeTab = ref('chat') // chat | quiz | code | websearch

// --- Quiz State ---
const quizState = ref('idle') // idle | generating | answering | evaluating | adapting
const quizData = ref(null)
const quizAnswer = ref('')
const quizConfidence = ref(5)
const quizResult = ref(null)
const quizAttempt = ref(1)
const quizConcept = ref('')
const quizSessionId = ref('')

// --- Code State ---
const codeInput = ref('')
const codeOutput = ref('')
const codeError = ref('')
const codeRunning = ref(false)
const codeExecTime = ref(0)
const codeHistory = ref([])
const showCodeViz = ref(false)

// --- Web Search State ---
const searchQuery = ref('')
const searchResults = ref([])
const searchSummary = ref('')
const searchLoading = ref(false)
const urlInput = ref('')
const urlLoading = ref(false)
const urlResult = ref(null)

const presets = [
  '什么是机器学习？',
  '过拟合的表现和正则化方法？',
  '什么是逻辑回归？sigmoid函数如何工作？',
]

const codeVizHtml = computed(() => {
  if (!codeOutput.value) return ''
  const out = codeOutput.value
  if (!out.includes('![可视化输出]')) return out.replace(/\n/g, '<br>')
  return out.replace(
    /!\[可视化输出\]\(data:image\/png;base64,([^)]+)\)/g,
    (_, b64) => `<img src="data:image/png;base64,${b64}" style="max-width:100%;border-radius:8px;margin:8px 0" />`
  )
})

// ======================== CHAT ========================

async function send() {
  const text = input.value.trim()
  if (!text || sending.value) return
  input.value = ''
  
  await nextTick()
  try {
    await chatStore.sendChatMessage(text, props.studentId)
  } catch (e) {
    console.error('Streaming failed:', e)
  }
}

function toggleResource(idx) {
  const s = new Set(showResources.value)
  s.has(idx) ? s.delete(idx) : s.add(idx)
  showResources.value = s
}

function usePreset(text) { input.value = text; send() }
function handleKeydown(e) { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send() } }

// ======================== QUIZ ========================

async function startQuiz() {
  if (!quizConcept.value.trim()) return
  quizState.value = 'generating'
  quizResult.value = null
  quizAnswer.value = ''
  quizConfidence.value = 5
  quizAttempt.value = 1
  quizSessionId.value = 'session-' + Date.now()

  try {
    const data = await generateQuiz(props.studentId, quizConcept.value, 'medium', quizSessionId.value)
    quizData.value = data
    quizState.value = 'answering'
  } catch (e) {
    quizState.value = 'idle'
    quizData.value = { question: `请解释 ${quizConcept.value} 的核心概念`, hints: ['想想基本定义'] }
    quizState.value = 'answering'
  }
}

async function submitQuizAnswer() {
  if (!quizAnswer.value.trim() || !quizData.value) return
  quizState.value = 'evaluating'

  try {
    const result = await evaluateQuizAnswer(
      quizData.value.quiz_id, props.studentId,
      quizAnswer.value, quizConfidence.value / 10, quizAttempt.value,
    )
    quizResult.value = result
    quizState.value = 'adapting'
  } catch (e) {
    quizResult.value = {
      accuracy_score: 0.5,
      ai_confidence: 0.6,
      feedback: '评估出错，请重试',
      next_action: 'practice',
      concept_mastery_updated: 0.5,
      confidence_calibration: 0.2,
    }
    quizState.value = 'adapting'
  }
}

async function continueQuiz() {
  if (!quizData.value || !quizResult.value) return
  quizState.value = 'generating'
  quizAttempt.value++

  try {
    const data = await adaptQuiz(
      props.studentId,
      quizData.value.quiz_id,
      quizResult.value.next_action,
      quizData.value.concept,
      quizAttempt.value,
      quizSessionId.value,
    )
    quizData.value = data
    quizAnswer.value = ''
    quizConfidence.value = 5
    quizResult.value = null
    quizState.value = 'answering'
  } catch (e) {
    quizState.value = 'answering'
  }
}

function resetQuiz() {
  quizState.value = 'idle'
  quizData.value = null
  quizResult.value = null
  quizAnswer.value = ''
  quizConcept.value = ''
}

function quizScoreClass(score) {
  if (score >= 0.8) return 'text-green-600'
  if (score >= 0.5) return 'text-yellow-600'
  return 'text-red-600'
}

// ======================== CODE VIZ ========================

async function runUserCode() {
  if (!codeInput.value.trim()) return
  codeRunning.value = true
  codeOutput.value = ''
  codeError.value = ''
  showCodeViz.value = true

  try {
    const result = await runCode(codeInput.value, 'python', props.studentId)
    codeOutput.value = result.output || ''
    codeError.value = result.error || ''
    codeExecTime.value = result.execution_time_ms || 0
    if (result.exec_id) {
      codeHistory.value.unshift({
        id: result.exec_id,
        code: codeInput.value.slice(0, 100),
        output: (result.output || '').slice(0, 100),
        has_error: !!result.error,
        time: result.execution_time_ms,
      })
    }
  } catch (e) {
    codeError.value = e.message || '执行出错'
  } finally {
    codeRunning.value = false
  }
}

function closeCodeViz() {
  showCodeViz.value = false
}

function insertCodeSnippet(snippet) {
  codeInput.value = snippet
  showCodeViz.value = true
}

const codePresets = [
  { label: 'NumPy 示例', code: 'import numpy as np\narr = np.array([[1,2,3],[4,5,6]])\nprint("Shape:", arr.shape)\nprint("Mean:", np.mean(arr))\nprint(arr)' },
  { label: 'Matplotlib 绘图', code: 'import matplotlib.pyplot as plt\nimport numpy as np\nx = np.linspace(0, 10, 100)\nplt.plot(x, np.sin(x), label="sin(x)")\nplt.plot(x, np.cos(x), label="cos(x)")\nplt.legend()\nplt.title("Sin and Cos")\nplt.show()' },
  { label: 'Pandas 数据分析', code: 'import pandas as pd\ndf = pd.DataFrame({"Name": ["Alice", "Bob", "Charlie"], "Score": [85, 92, 78]})\nprint(df)\nprint("\\nMean Score:", df["Score"].mean())' },
  { label: '线性回归', code: 'from sklearn.linear_model import LinearRegression\nimport numpy as np\nX = np.array([[1], [2], [3], [4], [5]])\ny = np.array([2, 4, 6, 8, 10])\nmodel = LinearRegression().fit(X, y)\nprint(f"Slope: {model.coef_[0]:.2f}")\nprint(f"Intercept: {model.intercept_:.2f}")\nprint(f"Predict X=6: {model.predict([[6]])[0]:.2f}")' },
]

// ======================== WEB SEARCH ========================

async function doWebSearch() {
  if (!searchQuery.value.trim()) return
  searchLoading.value = true
  searchResults.value = []
  searchSummary.value = ''

  try {
    const data = await webSearch(searchQuery.value, props.studentId)
    searchResults.value = data.results || []
    searchSummary.value = data.summary || ''
  } catch (e) {
    searchSummary.value = '搜索失败: ' + (e.message || '未知错误')
  } finally {
    searchLoading.value = false
  }
}

async function doLoadUrl() {
  if (!urlInput.value.trim()) return
  urlLoading.value = true
  urlResult.value = null

  try {
    const data = await loadUrl(urlInput.value, props.studentId)
    urlResult.value = data
  } catch (e) {
    urlResult.value = { error: e.message || '加载失败' }
  } finally {
    urlLoading.value = false
  }
}
</script>

<template>
  <div class="flex gap-4 h-full">
    <!-- Main content area -->
    <div class="flex-1 flex flex-col min-w-0">
      <!-- Tabs -->
      <div class="flex gap-1 mb-4 border-b border-gray-200 pb-2">
        <button class="tab-btn" :class="{ active: activeTab === 'chat' }" @click="activeTab = 'chat'">
          <MessageSquare :size="14" /> 对话
        </button>
        <button class="tab-btn" :class="{ active: activeTab === 'quiz' }" @click="activeTab = 'quiz'">
          <BrainCircuit :size="14" /> 测验
        </button>
        <button class="tab-btn" :class="{ active: activeTab === 'code' }" @click="activeTab = 'code'">
          <Terminal :size="14" /> 代码
        </button>
        <button class="tab-btn" :class="{ active: activeTab === 'websearch' }" @click="activeTab = 'websearch'">
          <Globe :size="14" /> 联网
        </button>
      </div>

      <!-- CHAT TAB -->
      <div v-if="activeTab === 'chat'" class="flex flex-col flex-1 min-h-0 max-w-4xl">
        <div class="flex flex-wrap gap-2 mb-4">
          <button v-for="preset in presets" :key="preset" class="btn btn-outline text-xs py-1.5" @click="usePreset(preset)">
            {{ preset.slice(0, 20) }}{{ preset.length > 20 ? '...' : '' }}
          </button>
        </div>

        <div class="flex-1 overflow-y-auto space-y-4 mb-4 scrollbar-thin">
          <div v-if="messages.length === 0" class="flex flex-col items-center justify-center h-full text-center text-gray-400">
            <Bot :size="48" class="mb-3 text-gray-300" />
            <p class="text-sm font-medium">输入问题开始学习</p>
            <p class="text-xs mt-1">EduMatrix 将调用多个智能体为你生成完整教学资源</p>
          </div>

          <div v-for="(msg, idx) in messages" :key="idx">
            <div v-if="msg.role === 'user'" class="flex justify-end mb-3">
              <div class="max-w-[75%] bg-blue-600 text-white rounded-2xl rounded-br-sm px-4 py-2.5">
                <p class="text-sm whitespace-pre-wrap">{{ msg.content }}</p>
              </div>
            </div>

            <div v-else class="mb-4">
              <div class="flex items-start gap-3">
                <div class="w-8 h-8 rounded-xl bg-gradient-to-br from-blue-500 to-purple-600 flex items-center justify-center shrink-0">
                  <Bot :size="16" class="text-white" />
                </div>
                <div class="flex-1 min-w-0">
                  <div class="card">
                    <div class="prose prose-sm max-w-none text-sm whitespace-pre-wrap">{{ msg.content }}</div>
                  </div>

                  <div v-if="msg.resources?.length" class="mt-3 space-y-1.5">
                    <div v-for="(res, ri) in msg.resources" :key="ri" class="border border-gray-200 rounded-lg overflow-hidden">
                      <div class="flex items-center justify-between px-3 py-2 cursor-pointer hover:bg-gray-50 transition-colors" @click="toggleResource(ri)">
                        <div class="flex items-center gap-2 min-w-0">
                          <span class="text-xs font-medium text-gray-700 truncate">{{ res.resource_type || res.agent }}</span>
                          <span v-if="res.citations?.length" class="text-[10px] text-gray-400">{{ res.citations.length }} 引用</span>
                        </div>
                        <ChevronDown v-if="!showResources.has(ri)" :size="14" class="text-gray-400 shrink-0" />
                        <ChevronUp v-else :size="14" class="text-gray-400 shrink-0" />
                      </div>
                      <div v-if="showResources.has(ri)" class="px-3 py-2 border-t border-gray-100 bg-gray-50/50">
                        <p class="text-xs text-gray-700 whitespace-pre-wrap font-mono leading-relaxed">{{ res.content.slice(0, 1000) }}{{ res.content.length > 1000 ? '...' : '' }}</p>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <div v-if="sending" class="card mb-4 bg-gradient-to-r from-blue-50/50 to-purple-50/50 border border-blue-100 p-4">
            <div class="flex items-center gap-3 mb-3">
              <div class="w-8 h-8 rounded-xl bg-gradient-to-br from-blue-500 to-purple-600 flex items-center justify-center shrink-0 animate-pulse">
                <BrainCircuit :size="16" class="text-white" />
              </div>
              <div class="flex-1 min-w-0">
                <p class="text-xs font-semibold text-gray-700">{{ chatStore.streamingStatus }}</p>
                <div class="flex items-center gap-2 mt-1.5">
                  <div class="flex-1 h-1.5 bg-gray-200 rounded-full overflow-hidden">
                    <div class="h-full bg-gradient-to-r from-blue-500 to-purple-600 rounded-full transition-all duration-300" :style="{ width: chatStore.streamingProgress + '%' }" />
                  </div>
                  <span class="text-[10px] font-bold text-blue-600 w-8 text-right">{{ chatStore.streamingProgress }}%</span>
                </div>
              </div>
            </div>
            
            <!-- 5大智能体并行状态墙 -->
            <div class="grid grid-cols-5 gap-2 mt-3 pt-3 border-t border-gray-100">
              <div v-for="agent in ['理论教授', '逻辑画师', '极客助教', '考官智能体', '虚拟导演']" :key="agent"
                class="flex flex-col items-center p-2 rounded-lg bg-white border border-gray-100 text-center"
                :class="{ 'border-blue-200 bg-blue-50/30': chatStore.streamingAgents[agent]?.done }">
                <div class="w-5 h-5 rounded-full flex items-center justify-center mb-1 text-[10px]"
                  :class="chatStore.streamingAgents[agent]?.done ? 'bg-green-100 text-green-600' : 'bg-gray-100 text-gray-400 animate-pulse'">
                  <CheckCircle2 v-if="chatStore.streamingAgents[agent]?.done" :size="10" />
                  <Loader2 v-else :size="10" class="animate-spin" />
                </div>
                <span class="text-[9px] font-medium text-gray-600">{{ agent }}</span>
              </div>
            </div>
          </div>
        </div>

        <div class="flex items-end gap-2 bg-white border border-gray-200 rounded-xl p-2">
          <textarea v-model="input" class="flex-1 resize-none outline-none text-sm px-2 py-1.5 max-h-32" placeholder="输入学习问题..." rows="1" @keydown="handleKeydown" />
          <button class="btn btn-primary shrink-0" :disabled="!input.trim() || sending" @click="send"><Send :size="16" /></button>
        </div>
      </div>

      <!-- QUIZ TAB -->
      <div v-if="activeTab === 'quiz'" class="flex flex-col flex-1 min-h-0 max-w-4xl">
        <div class="flex items-center justify-between mb-4">
          <h3 class="text-sm font-semibold text-gray-800 flex items-center gap-2">
            <BrainCircuit :size="16" class="text-purple-600" /> 自适应测验
          </h3>
          <button v-if="quizState !== 'idle'" class="btn btn-outline text-xs py-1" @click="resetQuiz">重新开始</button>
        </div>

        <!-- Idle state -->
        <div v-if="quizState === 'idle'" class="flex-1 flex flex-col items-center justify-center text-center text-gray-400">
          <HelpCircle :size="48" class="mb-3 text-gray-300" />
          <p class="text-sm font-medium text-gray-700 mb-3">选择知识点开始测验</p>
          <div class="flex gap-2 mb-4">
            <button v-for="concept in ['逻辑回归', '池化层', '过拟合', '反向传播', '卷积神经网络']" :key="concept"
              class="btn btn-outline text-xs" @click="quizConcept = concept; startQuiz()">
              {{ concept }}
            </button>
          </div>
          <div class="flex gap-2 w-full max-w-md">
            <input v-model="quizConcept" class="input flex-1" placeholder="输入自定义知识点..." @keydown.enter="startQuiz" />
            <button class="btn btn-primary" :disabled="!quizConcept.trim()" @click="startQuiz">开始</button>
          </div>
        </div>

        <!-- Generating -->
        <div v-if="quizState === 'generating'" class="flex-1 flex items-center justify-center text-gray-400">
          <Loader2 :size="24" class="animate-spin mr-2" /> 正在生成题目...
        </div>

        <!-- Answering -->
        <div v-if="quizState === 'answering' && quizData" class="flex-1 flex flex-col">
          <div class="card mb-4">
            <div class="flex items-center gap-2 mb-2">
              <span class="badge bg-purple-100 text-purple-700 text-xs">第 {{ quizAttempt }} 题</span>
              <span class="badge bg-blue-100 text-blue-700 text-xs">{{ quizData.concept }}</span>
              <span class="badge bg-gray-100 text-gray-600 text-xs">{{ quizData.difficulty }}</span>
            </div>
            <p class="text-sm font-medium text-gray-800 mb-3">{{ quizData.question }}</p>
            <div v-if="quizData.hints?.length" class="text-xs text-gray-500 space-y-1">
              <p class="font-medium text-gray-600">提示：</p>
              <p v-for="(hint, hi) in quizData.hints" :key="hi" class="pl-2 border-l-2 border-gray-200">提示{{ hi + 1 }}: {{ hint }}</p>
            </div>
          </div>

          <div class="flex-1" />
          <textarea v-model="quizAnswer" class="input mb-3 min-h-[100px]" placeholder="输入你的答案..." />
          <div class="flex items-center gap-3 mb-3">
            <span class="text-xs text-gray-500 shrink-0">自评置信度:</span>
            <input type="range" min="1" max="10" v-model.number="quizConfidence" class="flex-1" />
            <span class="text-xs font-medium text-gray-700 w-8 text-right">{{ quizConfidence }}/10</span>
          </div>
          <button class="btn btn-primary w-full" :disabled="!quizAnswer.trim()" @click="submitQuizAnswer">
            <Send :size="14" /> 提交答案
          </button>
        </div>

        <!-- Evaluating -->
        <div v-if="quizState === 'evaluating'" class="flex-1 flex items-center justify-center text-gray-400">
          <Loader2 :size="24" class="animate-spin mr-2" /> AI 正在评估...
        </div>

        <!-- Result -->
        <div v-if="quizState === 'adapting' && quizResult" class="flex-1 flex flex-col">
          <div class="card mb-4 space-y-3">
            <div class="flex items-center justify-between">
              <h4 class="text-sm font-semibold">评估结果</h4>
              <div class="flex items-center gap-2">
                <span class="text-xs text-gray-500">AI置信度:</span>
                <span class="text-sm font-bold" :class="quizScoreClass(quizResult.ai_confidence)">{{ (quizResult.ai_confidence * 100).toFixed(0) }}%</span>
              </div>
            </div>

            <div class="flex items-center gap-4">
              <div class="flex-1">
                <div class="flex justify-between text-xs text-gray-500 mb-1">
                  <span>得分</span>
                  <span :class="quizScoreClass(quizResult.accuracy_score)">{{ (quizResult.accuracy_score * 100).toFixed(0) }}%</span>
                </div>
                <div class="h-2 bg-gray-200 rounded-full overflow-hidden">
                  <div class="h-full rounded-full transition-all" :class="quizResult.accuracy_score >= 0.7 ? 'bg-green-500' : quizResult.accuracy_score >= 0.4 ? 'bg-yellow-500' : 'bg-red-500'"
                    :style="{ width: (quizResult.accuracy_score * 100) + '%' }" />
                </div>
              </div>
              <div class="flex-1">
                <div class="flex justify-between text-xs text-gray-500 mb-1">
                  <span>自评</span>
                  <span>{{ (quizResult.student_confidence * 100).toFixed(0) }}%</span>
                </div>
                <div class="h-2 bg-gray-200 rounded-full overflow-hidden">
                  <div class="h-full bg-blue-500 rounded-full" :style="{ width: (quizResult.student_confidence * 100) + '%' }" />
                </div>
              </div>
            </div>

            <div v-if="quizResult.confidence_calibration > 0.2" class="flex items-start gap-2 p-2 bg-yellow-50 rounded-lg text-xs text-yellow-800">
              <AlertTriangle :size="14" class="shrink-0 mt-0.5" />
              <span>元认知偏差: 你的自信度 ({{ (quizResult.student_confidence * 100).toFixed(0) }}%) 与实际得分 ({{ (quizResult.accuracy_score * 100).toFixed(0) }}%) 差距较大</span>
            </div>

            <div class="text-sm text-gray-700 bg-gray-50 rounded-lg p-3">
              <p class="font-medium text-xs text-gray-500 mb-1">反馈:</p>
              <p>{{ quizResult.feedback }}</p>
            </div>

            <div class="flex items-center gap-2">
              <span class="text-xs text-gray-500">下一动作:</span>
              <span class="badge" :class="quizResult.next_action === 'advance' ? 'bg-green-100 text-green-700' : quizResult.next_action === 'practice' ? 'bg-yellow-100 text-yellow-700' : 'bg-orange-100 text-orange-700'">
                {{ quizResult.next_action === 'advance' ? '可以进阶' : quizResult.next_action === 'practice' ? '继续练习' : '需要复习' }}
              </span>
            </div>
          </div>

          <div class="flex gap-2 mt-auto">
            <button class="btn btn-outline flex-1" @click="resetQuiz">结束测验</button>
            <button class="btn btn-primary flex-1" @click="continueQuiz">
              <Sparkles :size="14" /> 继续下一题
            </button>
          </div>
        </div>
      </div>

      <!-- CODE TAB -->
      <div v-if="activeTab === 'code'" class="flex flex-col flex-1 min-h-0 max-w-4xl">
        <div class="flex items-center justify-between mb-3">
          <h3 class="text-sm font-semibold text-gray-800 flex items-center gap-2">
            <Terminal :size="16" class="text-green-600" /> Python 代码执行
          </h3>
          <div class="flex gap-1">
            <button v-for="preset in codePresets" :key="preset.label" class="btn btn-outline text-[10px] py-1 px-2" @click="insertCodeSnippet(preset.code)">{{ preset.label }}</button>
          </div>
        </div>

        <div class="flex-1 flex flex-col min-h-0">
          <div class="flex-1 flex flex-col border border-gray-200 rounded-lg overflow-hidden">
            <div class="bg-gray-900 text-gray-200 text-xs px-3 py-1.5 flex items-center justify-between">
              <span>main.py</span>
              <button class="btn text-[10px] py-0.5 px-2 bg-green-600 hover:bg-green-700 text-white" :disabled="!codeInput.trim() || codeRunning" @click="runUserCode">
                <Play :size="10" /> {{ codeRunning ? '运行中...' : '运行' }}
              </button>
            </div>
            <textarea v-model="codeInput" class="flex-1 bg-gray-900 text-green-400 font-mono text-xs p-3 resize-none outline-none" placeholder="# 在这里输入 Python 代码..." spellcheck="false" />
          </div>

          <div v-if="codeOutput || codeError" class="mt-3 border border-gray-200 rounded-lg overflow-hidden">
            <div class="bg-gray-100 text-xs px-3 py-1.5 text-gray-500 flex items-center justify-between">
              <span>输出 ({{ codeExecTime }}ms)</span>
              <button class="text-gray-400 hover:text-gray-600" @click="codeOutput = ''; codeError = ''"><Trash2 :size="12" /></button>
            </div>
            <div class="bg-gray-50 p-3 max-h-48 overflow-y-auto">
              <pre v-if="codeOutput" class="text-xs text-gray-800 whitespace-pre-wrap font-mono">{{ codeOutput }}</pre>
              <pre v-if="codeError" class="text-xs text-red-600 whitespace-pre-wrap font-mono">{{ codeError }}</pre>
            </div>
          </div>
        </div>
      </div>

      <!-- WEB SEARCH TAB -->
      <div v-if="activeTab === 'websearch'" class="flex flex-col flex-1 min-h-0 max-w-4xl">
        <h3 class="text-sm font-semibold text-gray-800 flex items-center gap-2 mb-4">
          <Globe :size="16" class="text-blue-600" /> 联网搜索与文档加载
        </h3>

        <div class="space-y-4">
          <div class="card">
            <p class="text-xs font-medium text-gray-600 mb-2">搜索网络</p>
            <div class="flex gap-2">
              <input v-model="searchQuery" class="input flex-1" placeholder="输入搜索关键词..." @keydown.enter="doWebSearch" />
              <button class="btn btn-primary" :disabled="!searchQuery.trim() || searchLoading" @click="doWebSearch">
                <Search :size="14" /> {{ searchLoading ? '搜索中...' : '搜索' }}
              </button>
            </div>
            <div v-if="searchLoading" class="flex items-center gap-2 mt-3 text-gray-400 text-sm">
              <Loader2 :size="14" class="animate-spin" /> 正在搜索并索引...
            </div>
            <div v-if="searchSummary" class="mt-3 text-sm text-gray-700 bg-blue-50 rounded-lg p-3 whitespace-pre-wrap">{{ searchSummary }}</div>
            <div v-if="searchResults.length" class="mt-3 space-y-2">
              <div v-for="(r, i) in searchResults" :key="i" class="flex items-start gap-2 p-2 hover:bg-gray-50 rounded-lg">
                <ExternalLink :size="12" class="text-gray-400 mt-0.5 shrink-0" />
                <div class="min-w-0">
                  <a :href="r.url" target="_blank" class="text-xs font-medium text-blue-600 hover:underline truncate block">{{ r.title }}</a>
                  <p class="text-[10px] text-gray-500 mt-0.5 line-clamp-2">{{ r.snippet }}</p>
                </div>
              </div>
            </div>
          </div>

          <div class="card">
            <p class="text-xs font-medium text-gray-600 mb-2">加载网页 URL</p>
            <div class="flex gap-2">
              <input v-model="urlInput" class="input flex-1" placeholder="输入网页URL..." @keydown.enter="doLoadUrl" />
              <button class="btn btn-primary" :disabled="!urlInput.trim() || urlLoading" @click="doLoadUrl">
                <ExternalLink :size="14" /> {{ urlLoading ? '加载中...' : '加载' }}
              </button>
            </div>
            <div v-if="urlLoading" class="flex items-center gap-2 mt-3 text-gray-400 text-sm">
              <Loader2 :size="14" class="animate-spin" /> 正在加载并索引...
            </div>
            <div v-if="urlResult && !urlResult.error" class="mt-3">
              <div class="bg-green-50 rounded-lg p-3">
                <p class="text-sm font-medium text-gray-800">{{ urlResult.title }}</p>
                <p class="text-[10px] text-gray-500 truncate">{{ urlResult.url }}</p>
                <p class="text-xs text-gray-600 mt-2 whitespace-pre-wrap">{{ urlResult.summary }}</p>
                <p class="text-[10px] text-gray-400 mt-1">{{ urlResult.chunks_ingested }} 个知识块已索引</p>
              </div>
            </div>
            <div v-if="urlResult?.error" class="mt-3 text-sm text-red-600 bg-red-50 rounded-lg p-3">{{ urlResult.error }}</div>
          </div>
        </div>
      </div>
    </div>

    <!-- CODE VIZ FLOATING WINDOW -->
    <Teleport to="body">
      <div v-if="showCodeViz" class="fixed inset-0 z-50 flex items-center justify-center bg-black/30" @click.self="closeCodeViz">
        <div class="bg-white rounded-xl shadow-2xl w-[90vw] max-w-4xl max-h-[85vh] flex flex-col overflow-hidden">
          <div class="flex items-center justify-between px-4 py-3 border-b border-gray-200">
            <h3 class="text-sm font-semibold text-gray-800 flex items-center gap-2">
              <Terminal :size="16" class="text-green-600" /> 代码可视化
            </h3>
            <button class="text-gray-400 hover:text-gray-600" @click="closeCodeViz">&times;</button>
          </div>
          <div class="flex-1 flex flex-col min-h-0 p-4 gap-3">
            <div class="flex-1 flex flex-col border border-gray-200 rounded-lg overflow-hidden">
              <div class="bg-gray-900 text-gray-200 text-xs px-3 py-1.5 flex items-center justify-between">
                <span>Python 代码</span>
                <button class="btn text-[10px] py-0.5 px-2 bg-green-600 hover:bg-green-700 text-white" :disabled="!codeInput.trim() || codeRunning" @click="runUserCode">
                  <Play :size="10" /> {{ codeRunning ? '运行中...' : '运行' }}
                </button>
              </div>
              <textarea v-model="codeInput" class="flex-1 bg-gray-900 text-green-400 font-mono text-xs p-3 resize-none outline-none min-h-[120px]" placeholder="# 输入 Python 代码..." spellcheck="false" />
            </div>
            <div class="flex gap-1 flex-wrap">
              <button v-for="preset in codePresets" :key="preset.label" class="btn btn-outline text-[10px] py-1 px-2" @click="codeInput = preset.code">{{ preset.label }}</button>
            </div>
            <div v-if="codeOutput || codeError" class="border border-gray-200 rounded-lg overflow-hidden">
              <div class="bg-gray-100 text-xs px-3 py-1.5 text-gray-500 flex items-center justify-between">
                <span>输出 ({{ codeExecTime }}ms)</span>
                <button class="text-gray-400 hover:text-gray-600" @click="codeOutput = ''; codeError = ''"><Trash2 :size="12" /></button>
              </div>
              <div class="bg-gray-50 p-3 max-h-60 overflow-y-auto">
                <div v-if="codeVizHtml" v-html="codeVizHtml" class="text-xs text-gray-800" />
                <pre v-if="codeError" class="text-xs text-red-600 whitespace-pre-wrap font-mono">{{ codeError }}</pre>
              </div>
            </div>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
.tab-btn {
  display: inline-flex;
  align-items: center;
  gap: 0.375rem;
  padding: 0.375rem 0.875rem;
  border-radius: 0.5rem;
  font-size: 0.75rem;
  font-weight: 500;
  color: #64748b;
  background: transparent;
  border: none;
  cursor: pointer;
  transition: all 0.15s ease;
}
.tab-btn:hover {
  background: #f1f5f9;
  color: #334155;
}
.tab-btn.active {
  background: #eff6ff;
  color: #2563eb;
  font-weight: 600;
}
</style>
