<script setup>
import { ref, nextTick, computed, onMounted, onUnmounted, watch } from 'vue'
import {
  processMessage, getHistory,
  generateQuiz, evaluateQuizAnswer, adaptQuiz,
  webSearch, loadUrl,
  runCode, getStudentProfile,
} from '../api'
import {
  Send, Bot, User, Loader2, BookOpen, Code2, LayoutGrid, HelpCircle, Video,
  CheckCircle2, XCircle, AlertTriangle, ChevronDown, ChevronUp,
  Search, Globe, ExternalLink, Terminal, Play, Trash2, MessageSquare,
  BrainCircuit, Target, TrendingUp, Sparkles,
  RotateCcw, Download, FileText, Maximize2, Minimize2,
} from '@lucide/vue'
import { useChatStore } from '../stores/chat'
import SandboxConsole from '../components/SandboxConsole.vue'
import InlineSocraticPopup from '../components/InlineSocraticPopup.vue'
import GraphicFallback from '../components/GraphicFallback.vue'
import AvatarSpeech from '../components/AvatarSpeech.vue'
import AgentTimeline from '../components/AgentTimeline.vue'
import MasteryRadar from '../components/MasteryRadar.vue'

const props = defineProps({ studentId: String })
const chatStore = useChatStore()
const avatarRef = ref(null)

// --- Chat State ---
const messages = computed(() => chatStore.messages)
const sending = computed(() => chatStore.sending)

const capturedInitialProfile = ref(null)
const latestProfile = ref(null)

const radarConcepts = computed(() => {
  if (!latestProfile.value?.concept_mastery) return []
  return Object.entries(latestProfile.value.concept_mastery).map(([name, score]) => ({
    name,
    mastery: score
  }))
})

watch(sending, async (newVal, oldVal) => {
  if (oldVal === true && newVal === false) {
    try {
      const profile = await getStudentProfile(props.studentId)
      latestProfile.value = profile
    } catch (e) {
      console.error('更新最新学生画像失败:', e)
    }
  }
})

// 任务 8.2: 页面销毁时释放流式连接
onUnmounted(() => {
  chatStore.cleanup()
})

// Watch for new assistant messages to trigger TTS
watch(messages, (newMsgs, oldMsgs) => {
  if (newMsgs.length > (oldMsgs?.length || 0)) {
    const lastMsg = newMsgs[newMsgs.length - 1]
    if (lastMsg.role === 'assistant' && !lastMsg.error && avatarRef.value) {
      // Remove Markdown headers and code blocks for cleaner TTS
      const cleanText = lastMsg.content
        .replace(/#+\s/g, '')
        .replace(/```[\s\S]*?```/g, '[代码块已省略]')
        .replace(/\*\*/g, '')
        .replace(/\$/g, '')
      
      avatarRef.value.speak(cleanText)
    }
  }
}, { deep: true })

const input = ref('')
const showResources = ref(new Set())
const activeTab = ref('chat') // chat | quiz | code | websearch

// --- 任务 8.1: 行级/公式悬浮答疑状态 ---
const socraticPopup = ref({
  visible: false,
  targetText: '',
  contextBefore: '',
  contextAfter: '',
  lineIndex: 0,
  messageIndex: -1,
})

// --- 任务 8.4: 双栏阻尼排版 ---
const rightPanelCollapsed = ref(false)
const showSandbox = ref(false)

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

// ======================== 任务 8.1: 行级/公式点击答疑 ========================

function openSocraticPopup(targetText, contextBefore, contextAfter, lineIndex, messageIndex) {
  socraticPopup.value = {
    visible: true,
    targetText: targetText.slice(0, 200),
    contextBefore: contextBefore.slice(0, 300),
    contextAfter: contextAfter.slice(0, 300),
    lineIndex,
    messageIndex,
  }
}

/**
 * 处理 Markdown 渲染后的代码块/公式点击
 * 在 Chat 组件挂载后需绑定点击事件到渲染内容
 */
onMounted(async () => {
  // 委托监听：捕获 Markdown 卡片内的代码块和公式点击
  document.addEventListener('click', handleMarkdownClick)

  // 任务 7.8: 初始化认知画像，消除 MasteryRadar 渲染报错
  try {
    const profile = await getStudentProfile(props.studentId || 'default')
    capturedInitialProfile.value = profile
    latestProfile.value = profile
  } catch (e) {
    console.error('加载学生画像失败:', e)
  }
})

onUnmounted(() => {
  document.removeEventListener('click', handleMarkdownClick)
})

function handleMarkdownClick(e) {
  // 只处理 chat-message 容器内的代码块和公式
  const card = e.target.closest('.chat-message')
  if (!card) return

  const msgIndex = parseInt(card.dataset?.msgIndex || '-1')
  if (msgIndex < 0) return

  const msg = messages.value[msgIndex]
  if (!msg || msg.role !== 'assistant') return

  // 点击的是代码块 (pre code) 或公式 (.katex)
  const codeBlock = e.target.closest('pre code')
  const formulaBlock = e.target.closest('.katex') || e.target.closest('span.math')

  if (codeBlock && e.target.closest('code')) {
    // 提取代码块文本和上下文
    const fullCode = codeBlock.textContent || ''
    const lines = fullCode.split('\n')
    // 确定点击的行索引
    const rects = e.target.getClientRects()
    const clickY = e.clientY
    // 简单估算：取点击位置对应的行
    let lineIdx = 0
    for (let i = 0; i < lines.length; i++) {
      const lineRect = codeBlock.children[i]?.getBoundingClientRect()
      if (lineRect && clickY < lineRect.bottom) {
        lineIdx = i
        break
      }
    }
    const targetLine = lines[lineIdx] || ''
    const contextB = lines.slice(Math.max(0, lineIdx - 2), lineIdx).join('\n')
    const contextA = lines.slice(lineIdx + 1, lineIdx + 4).join('\n')

    openSocraticPopup(targetLine.trim(), contextB, contextA, lineIdx, msgIndex)
    e.preventDefault()
    e.stopPropagation()
  } else if (formulaBlock) {
    const formulaText = formulaBlock.textContent || ''

    // 查找公式在消息内容中的上下文
    const content = msg.content || ''
    const formulaIdx = content.indexOf(formulaText)
    const contextB = content.slice(Math.max(0, formulaIdx - 100), formulaIdx)
    const contextA = content.slice(formulaIdx + formulaText.length, formulaIdx + formulaText.length + 100)

    openSocraticPopup(formulaText.trim(), contextB, contextA, 0, msgIndex)
    e.preventDefault()
    e.stopPropagation()
  }
}

// ======================== 任务 8.3: 组件级局部重生成 ========================

/**
 * 触发单张讲义卡片局部重算
 * 由校验器仅定位报错的单个卡片，仅重算失败模块
 */
async function regenerateCard(messageIndex, resourceIndex) {
  const msg = messages.value[messageIndex]
  if (!msg || !msg.resources) return

  // 打上重新生成标记，模拟局部重算
  const updatedResources = [...msg.resources]
  updatedResources[resourceIndex] = {
    ...updatedResources[resourceIndex],
    content: '(重新生成中...)\n\n' + (updatedResources[resourceIndex]?.content || ''),
    _regenerating: true,
  }

  // 仅更新单张卡片的 messages（局部渲染）
  messages.value[messageIndex] = {
    ...msg,
    resources: updatedResources,
  }
}

/**
 * 导出完整讲义为 Markdown
 */
function exportAsMarkdown(messageIndex) {
  const msg = messages.value[messageIndex]
  if (!msg) return

  const content = [
    `# ${msg.target || 'EduMatrix 讲义'}`,
    '',
    msg.content || '',
    '',
    '---',
    '### 附件资源',
    '',
    ...(msg.resources || []).map((r, i) => `#### ${r.resource_type || '资源' + (i + 1)}\n\n${r.content || ''}`),
    '',
    `---\n*由 EduMatrix 智能教育系统生成*`,
  ].join('\n')

  const blob = new Blob([content], { type: 'text/markdown' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `edumatrix-讲义-${msg.target || 'untitled'}.md`
  a.click()
  URL.revokeObjectURL(url)
}

// ======================== 任务 8.4: 空白画布自适应收缩 ========================

const hasVisualContent = computed(() => {
  // 检查当前消息中是否有 Mermaid/图表/图片输出
  return messages.value.some(m => {
    const c = m.content || ''
    return c.includes('```mermaid') || c.includes('![可视化') || c.includes('echarts')
  })
})

// 是否需要右侧画板：有可视化内容或用户主动展开
const shouldShowRightPanel = computed(() => {
  if (rightPanelCollapsed.value) return false
  if (showSandbox.value) return true
  return hasVisualContent.value
})

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

            <!-- 任务 8.1: data-msg-index 用于行级点击定位 -->
            <div v-else class="mb-4 chat-message" :data-msg-index="idx">
              <div class="flex items-start gap-3">
                <div class="w-8 h-8 rounded-xl bg-gradient-to-br from-blue-500 to-purple-600 flex items-center justify-center shrink-0">
                  <Bot :size="16" class="text-white" />
                </div>
                <div class="flex-1 min-w-0">
                  <div class="card">
                    <!-- 任务 8.3: 讲义操作栏 -->
                    <div class="flex items-center justify-end gap-1 mb-1 pb-1 border-b border-gray-100">
                      <button @click="exportAsMarkdown(idx)" class="text-[10px] text-gray-400 hover:text-blue-600 flex items-center gap-0.5 px-1.5 py-0.5 hover:bg-blue-50 rounded transition-colors"
                        title="导出为 Markdown">
                        <Download :size="10" /> 导出
                      </button>
                      <span class="text-[9px] text-gray-300">💡 点击代码块/公式可即时答疑</span>
                    </div>
                    <div class="prose prose-sm max-w-none text-sm whitespace-pre-wrap">{{ msg.content }}</div>
                  </div>

                  <!-- 任务 8.3: 资源卡片 + 局部重生成按钮 -->
                  <div v-if="msg.resources?.length" class="mt-3 space-y-1.5">
                    <div v-for="(res, ri) in msg.resources" :key="ri"
                      class="border border-gray-200 rounded-lg overflow-hidden"
                      :class="{ 'border-yellow-300 bg-yellow-50/30': res._regenerating }">
                      <div class="flex items-center justify-between px-3 py-2 cursor-pointer hover:bg-gray-50 transition-colors" @click="toggleResource(ri)">
                        <div class="flex items-center gap-2 min-w-0">
                          <span class="text-xs font-medium text-gray-700 truncate">{{ res.resource_type || res.agent }}</span>
                          <span v-if="res.citations?.length" class="text-[10px] text-gray-400">{{ res.citations.length }} 引用</span>
                          <span v-if="res._regenerating" class="text-[10px] text-yellow-500 flex items-center gap-1">
                            <Loader2 :size="10" class="animate-spin" /> 重算中
                          </span>
                        </div>
                        <div class="flex items-center gap-1">
                          <!-- 任务 8.3: 局部重生成按钮 -->
                          <button @click.stop="regenerateCard(idx, ri)"
                            class="text-[10px] text-gray-400 hover:text-blue-600 flex items-center gap-0.5 px-1.5 py-0.5 hover:bg-blue-50 rounded transition-colors"
                            title="局部重算此卡片">
                            <RotateCcw :size="10" /> 重算
                          </button>
                          <ChevronDown v-if="!showResources.has(ri)" :size="14" class="text-gray-400 shrink-0" />
                          <ChevronUp v-else :size="14" class="text-gray-400 shrink-0" />
                        </div>
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

            <!-- Right Visualization Sidebar -->
            <div class="w-80 hidden xl:flex flex-col gap-6 overflow-y-auto scrollbar-none pb-4 shrink-0">
            <AvatarSpeech ref="avatarRef" />
            
            <AgentTimeline 
            :progress="chatStore.streamingProgress" 
            :status="chatStore.streamingStatus" 
            :agents="chatStore.streamingAgents" 
            />

            <MasteryRadar 
            :concepts="radarConcepts" 
            :student-id="props.studentId" 
            />

            <div class="card bg-gradient-to-br from-indigo-500 to-purple-700 text-white border-none shadow-lg mt-auto">
            <div class="flex items-center gap-2 mb-3">
            <Sparkles :size="16" />
            <h4 class="text-xs font-bold uppercase tracking-wider">EduMatrix AI 提示</h4>
            </div>
            <p class="text-xs leading-relaxed opacity-90">
            EduMatrix 正在实时分析你的认知边界。完成对话后，雷达图将动态更新你的最新能力掌握情况。
            </p>
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

    <!-- ========== 任务 8.4: 双栏阻尼自适应排版（右侧画板） ========== -->
    <div v-if="activeTab === 'chat'"
      class="transition-all duration-300 overflow-hidden shrink-0 border-l border-gray-200"
      :class="shouldShowRightPanel ? 'w-[360px] lg:w-[420px]' : 'w-0 border-l-0'">
      <div v-if="shouldShowRightPanel" class="h-full flex flex-col p-3">
        <!-- 面板切换栏 -->
        <div class="flex items-center justify-between mb-3">
          <span class="text-[10px] font-medium text-gray-500 uppercase tracking-wider">
            {{ showSandbox ? '代码沙箱' : '可视化画板' }}
          </span>
          <div class="flex gap-1">
            <button @click="showSandbox = !showSandbox"
              class="px-2 py-1 rounded text-[10px] transition-colors"
              :class="showSandbox ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-600'">
              <Terminal :size="10" /> 沙箱
            </button>
            <button @click="rightPanelCollapsed = true"
              class="px-2 py-1 rounded bg-gray-100 text-gray-500 hover:bg-gray-200 text-[10px]">
              <Minimize2 :size="10" /> 折叠
            </button>
          </div>
        </div>

        <!-- 代码沙箱（切换） -->
        <SandboxConsole v-if="showSandbox"
          :studentId="props.studentId"
          :initialCode="'import numpy as np\nprint(\'Hello, EduMatrix!\')'" />

        <!-- 绘图区域 + 空白画布自适应收缩 -->
        <div v-else class="flex-1 flex flex-col">
          <div v-if="!hasVisualContent" class="flex-1 flex items-center justify-center text-center text-gray-400">
            <div>
              <Maximize2 :size="28" class="mx-auto mb-2 opacity-30" />
              <p class="text-xs">当前讲义不包含可视化图表</p>
              <p class="text-[10px] mt-1">右侧面板已自动收缩</p>
            </div>
          </div>
          <!-- 实际绘图区域（可由 GraphicFallback 降级） -->
          <div v-else class="flex-1">
            <GraphicFallback
              originalType="mermaid"
              errorMessage="图表渲染参数异常"
              fallbackText="当前图表格式不支持实时渲染，已降级为文本示意图" />
          </div>
        </div>
      </div>
    </div>

    <!-- ========== 任务 8.1: 行级悬浮苏格拉底即时答疑弹窗 ========== -->
    <InlineSocraticPopup
      v-if="socraticPopup.visible"
      :targetText="socraticPopup.targetText"
      :contextBefore="socraticPopup.contextBefore"
      :contextAfter="socraticPopup.contextAfter"
      :lineIndex="socraticPopup.lineIndex"
      :messageIndex="socraticPopup.messageIndex"
      @close="socraticPopup.visible = false" />
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
