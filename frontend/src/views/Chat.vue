<script setup>
import { ref, nextTick, computed, onMounted, onUnmounted, watch, createApp } from 'vue'
import CollapsibleMindmap from '../components/CollapsibleMindmap.vue'
import {
  processMessage, getHistory,
  generateQuiz, evaluateQuizAnswer, adaptQuiz,
  webSearch, loadUrl, searchArxiv,
  runCode, getStudentProfile, regenerateComponent,
} from '../api'
import {
  Send, Bot, User, Loader2, BookOpen, Code2, LayoutGrid, HelpCircle, Video,
  CheckCircle2, XCircle, AlertTriangle, ChevronDown, ChevronUp,
  Search, Globe, ExternalLink, Terminal, Play, Trash2, MessageSquare,
  BrainCircuit, Target, TrendingUp, Sparkles,
  RotateCcw, Download, FileText, Maximize2, Minimize2, Lightbulb, Copy,
} from '@lucide/vue'
import { useChatStore } from '../stores/chat'
import SandboxConsole from '../components/SandboxConsole.vue'
import InlineSocraticPopup from '../components/InlineSocraticPopup.vue'
import GraphicFallback from '../components/GraphicFallback.vue'
import ManifoldVisualizer from '../components/ManifoldVisualizer.vue'
import AvatarSpeech from '../components/AvatarSpeech.vue'
import AgentTimeline from '../components/AgentTimeline.vue'
import MasteryRadar from '../components/MasteryRadar.vue'
import VideoRenderPanel from '../components/VideoRenderPanel.vue'

const props = defineProps({ studentId: String })
const chatStore = useChatStore()
const avatarRef = ref(null)

// --- Chat State ---
const messages = computed(() => chatStore.messages)
const sending = computed(() => chatStore.sending)

const capturedInitialProfile = ref(null)
const latestProfile = ref(null)

// --- 思维导图放大模态框状态 ---
const zoomModal = ref({
  visible: false,
  code: '',
})
const zoomScale = ref(1.0)
const panOffset = ref({ x: 0, y: 0 })
let isPanning = false
let startPanCoords = { x: 0, y: 0 }

function zoomIn() {
  zoomScale.value = Math.min(3.0, zoomScale.value + 0.2)
}
function zoomOut() {
  zoomScale.value = Math.max(0.4, zoomScale.value - 0.2)
}
function resetZoom() {
  zoomScale.value = 1.0
  panOffset.value = { x: 0, y: 0 }
}
function closeZoomModal() {
  zoomModal.value.visible = false
  zoomModal.value.code = ''
}

function startPan(e) {
  isPanning = true
  startPanCoords = { x: e.clientX - panOffset.value.x, y: e.clientY - panOffset.value.y }
}
function doPan(e) {
  if (!isPanning) return
  panOffset.value = { x: e.clientX - startPanCoords.x, y: e.clientY - startPanCoords.y }
}
function endPan() {
  isPanning = false
}

// 绑定全局方法，供 v-html 内按钮点击调用
window.zoomMindmap = (btn) => {
  const mermaidDiv = btn.closest('.my-3').querySelector('.mermaid')
  if (mermaidDiv) {
    const rawCode = decodeURIComponent(mermaidDiv.getAttribute('data-code') || '')
    zoomModal.value.code = rawCode
    zoomModal.value.visible = true
    zoomScale.value = 1.0
    panOffset.value = { x: 0, y: 0 }
  }
}

watch(() => zoomModal.value.code, (newVal) => {
  if (newVal) {
    nextTick(() => {
      if (typeof window.mermaid !== 'undefined') {
        try {
          window.mermaid.init(undefined, document.querySelectorAll('.zoom-mermaid-target .mermaid'))
        } catch (err) {
          console.error('Zoom mermaid init error:', err)
        }
      }
    })
  }
})

function mountCustomMindmaps() {
  nextTick(() => {
    try {
      const placeholders = document.querySelectorAll('.custom-mindmap-placeholder:not([data-mounted="true"])')
      placeholders.forEach((el) => {
        const rawCode = decodeURIComponent(el.getAttribute('data-code') || '')
        const app = createApp(CollapsibleMindmap, { code: rawCode })
        app.mount(el)
        el.setAttribute('data-mounted', 'true')
        el.__vue_app__ = app
      })
    } catch (err) {
      console.error('Mount custom mindmaps error:', err)
    }
  })
}

function cleanupCustomMindmaps() {
  const elements = document.querySelectorAll('.custom-mindmap-placeholder[data-mounted="true"]')
  elements.forEach((el) => {
    if (el.__vue_app__) {
      try {
        el.__vue_app__.unmount()
      } catch (e) {}
      delete el.__vue_app__
    }
  })
}

function renderAllDiagrams() {
  initMermaid()
  mountCustomMindmaps()
}

function initMermaid() {
  if (typeof window.mermaid !== 'undefined') {
    nextTick(() => {
      try {
        window.mermaid.initialize({
          startOnLoad: false,
          theme: 'default', // Using default theme for light background and dopamine-like colors
          securityLevel: 'loose',
          themeVariables: {
            background: '#ffffff',
            primaryColor: '#ff79c6',
            primaryTextColor: '#111827',
            lineColor: '#6366f1',
            fontSize: '12px'
          }
        })
        // Loop through unprocessed elements individually to prevent rendering errors in one diagram from blocking others
        const elements = document.querySelectorAll('.mermaid:not([data-processed="true"])')
        elements.forEach((el) => {
          try {
            window.mermaid.init(undefined, el)
          } catch (err) {
            console.error('Individual Mermaid render error:', err)
          }
        })
      } catch (err) {
        console.error('Mermaid render error:', err)
      }
    })
  }
}

watch(messages, () => {
  renderAllDiagrams()
}, { deep: true })

watch(() => chatStore.sending, () => {
  renderAllDiagrams()
})


onMounted(() => {
  renderAllDiagrams()
})

const nameToRole = {
  '理论教授': 'theory_expert',
  '逻辑画师': 'visualizer',
  '极客助教': 'sandbox_coder',
  '考官智能体': 'assessor',
  '虚拟导演': 'director'
}

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
  cleanupCustomMindmaps()
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
watch(showResources, () => {
  renderAllDiagrams()
}, { deep: true })
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

// 任务 8.5: 视频渲染面板状态
const showVideoPanel = ref(false)
const videoPanelUrl = ref('')
function toggleVideoPanel() {
  showVideoPanel.value = !showVideoPanel.value
  if (showVideoPanel.value) {
    videoPanelUrl.value = '/api/v1/video/stream?student_id=' + props.studentId + '&t=' + Date.now()
  }
}

// --- Quiz State ---
const quizState = ref('idle') // idle | generating | answering | evaluating | adapting
const quizData = ref(null)
const quizAnswer = ref('')
const quizConfidence = ref(parseInt(localStorage.getItem('edumatrix_quiz_confidence') || '5', 10))
watch(quizConfidence, (v) => localStorage.setItem('edumatrix_quiz_confidence', String(v)))
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
const arxivQuery = ref('')
const arxivLoading = ref(false)
const arxivPapers = ref([])
const arxivError = ref('')

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
  // 斜杠命令
  if (text.startsWith('/quiz ')) {
    quizConcept.value = text.slice(6).trim()
    activeTab.value = 'quiz'
    input.value = ''
    await nextTick()
    startQuiz()
    return
  }
  if (text.startsWith('/search ')) {
    searchQuery.value = text.slice(8).trim()
    activeTab.value = 'websearch'
    input.value = ''
    await nextTick()
    doWebSearch()
    return
  }
  if (text.startsWith('/code')) {
    activeTab.value = 'code'
    input.value = ''
    return
  }
  input.value = ''
  await nextTick()
  try {
    await chatStore.sendChatMessage(text, props.studentId)
  } catch (e) {
    console.error('Streaming failed:', e)
  }
}

function toggleResource(msgIdx, resIdx) {
  const key = `${msgIdx}-${resIdx}`
  const s = new Set(showResources.value)
  s.has(key) ? s.delete(key) : s.add(key)
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
  codeOutput.value = ''
  codeError.value = ''
  showCodeViz.value = true
}

async function copyCode() {
  try {
    await navigator.clipboard.writeText(codeInput.value)
  } catch (e) {
    const ta = document.createElement('textarea')
    ta.value = codeInput.value; document.body.appendChild(ta); ta.select()
    document.execCommand('copy'); document.body.removeChild(ta)
  }
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

  // 注册全局 CAT 自适应测验板触发方法
  window.startInteractiveQuiz = (conceptName) => {
    activeTab.value = 'quiz'
    quizConcept.value = conceptName || latestProfile.value?.learning_goals?.[0] || '逻辑回归'
    startQuiz()
  }

  // 注册全局视频触发方法
  window.startInteractiveVideo = () => {
    toggleVideoPanel()
  }

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
  window.startInteractiveQuiz = null
  window.startInteractiveVideo = null
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

function getAgentConfig(agentName, resourceType) {
  const name = (agentName || resourceType || '').toLowerCase()
  if (name.includes('theory') || name.includes('理论') || name.includes('professor')) {
    return { label: '理论教授', color: 'text-blue-600 bg-blue-50 border-blue-100', icon: 'BookOpen' }
  }
  if (name.includes('visual') || name.includes('画师') || name.includes('图示') || name.includes('渲染')) {
    return { label: '逻辑画师', color: 'text-purple-600 bg-purple-50 border-purple-100', icon: 'LayoutGrid' }
  }
  if (name.includes('retrieve') || name.includes('检索') || name.includes('rag')) {
    return { label: '检索专家', color: 'text-indigo-600 bg-indigo-50 border-indigo-100', icon: 'Search' }
  }
  if (name.includes('debate') || name.includes('辩论') || name.includes('socratic')) {
    return { label: '苏格拉底辩手', color: 'text-green-600 bg-green-50 border-green-100', icon: 'HelpCircle' }
  }
  if (name.includes('sandbox') || name.includes('coder') || name.includes('代码') || name.includes('助教')) {
    return { label: '极客助教', color: 'text-amber-600 bg-amber-50 border-amber-100', icon: 'Terminal' }
  }
  if (name.includes('assess') || name.includes('quiz') || name.includes('考官') || name.includes('评测')) {
    return { label: '考官智能体', color: 'text-rose-600 bg-rose-50 border-rose-100', icon: 'BrainCircuit' }
  }
  return { label: agentName || resourceType || '教育智能体', color: 'text-gray-600 bg-gray-50 border-gray-100', icon: 'Bot' }
}

function getIconComponent(iconName) {
  const mapping = {
    BookOpen,
    LayoutGrid,
    Search,
    HelpCircle,
    Terminal,
    BrainCircuit,
    Bot
  }
  return mapping[iconName] || Bot
}

/**
 * 触发单张讲义卡片局部重算
 * 由校验器仅定位报错的单个卡片，仅重算失败模块
 */
async function regenerateCard(messageIndex, resourceIndex) {
  const msg = chatStore.messages[messageIndex]
  if (!msg || !msg.resources) return

  const res = msg.resources[resourceIndex]
  if (!res) return

  let query = ''
  for (let i = messageIndex - 1; i >= 0; i--) {
    if (chatStore.messages[i].role === 'user') {
      query = chatStore.messages[i].content
      break
    }
  }
  if (!query) {
    query = msg.target || ''
  }

  res._regenerating = true

  try {
    const data = await regenerateComponent(
      props.studentId || 'default',
      res.agent,
      res.type || res.resource_type || '',
      query
    )
    if (data && data.status === 'success') {
      res.content = data.content
    }
  } catch (e) {
    console.error('Error regenerating component:', e)
  } finally {
    res._regenerating = false
  }
}

function runResourceCode(messageIndex, resourceIndex) {
  const msg = chatStore.messages[messageIndex]
  if (!msg || !msg.resources) return
  const res = msg.resources[resourceIndex]
  if (!res) return
  const content = res.content || ''
  const m = content.match(/```(?:python)?\s*\n([\s\S]*?)```/)
  codeInput.value = m ? m[1].trim() : content
  activeTab.value = 'code'
  codeOutput.value = ''
  codeError.value = ''
}

// 概念代码浮窗
const conceptCodePopup = ref(null) // { visible, loading, content, target }
async function showConceptCode(msgIdx) {
  const msg = chatStore.messages[msgIdx]
  if (!msg || !msg.target) return
  conceptCodePopup.value = { visible: true, loading: true, content: '', target: msg.target }
  try {
    // 找到对应的用户消息作为 query
    let query = msg.target
    for (let i = msgIdx - 1; i >= 0; i--) {
      if (chatStore.messages[i].role === 'user') {
        query = chatStore.messages[i].content
        break
      }
    }
    const data = await regenerateComponent(props.studentId || 'default', '极客助教', '代码实操案例', query)
    if (data && data.status === 'success') {
      conceptCodePopup.value.content = data.content
    } else {
      conceptCodePopup.value.content = '// 代码生成失败，请重试'
    }
  } catch (e) {
    conceptCodePopup.value.content = '// 错误: ' + (e.message || '未知错误')
  } finally {
    conceptCodePopup.value.loading = false
  }
}
function closeConceptCode() { conceptCodePopup.value = null }
function runConceptCode() {
  if (!conceptCodePopup.value) return
  const content = conceptCodePopup.value.content || ''
  const m = content.match(/```(?:python)?\s*\n([\s\S]*?)```/)
  codeInput.value = m ? m[1].trim() : content
  activeTab.value = 'code'
  codeOutput.value = ''
  codeError.value = ''
  conceptCodePopup.value = null
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
  // 检查当前消息中是否有 Mermaid/图表/图片输出 (包括子智能体资源内容)
  return messages.value.some(m => {
    const c = m.content || ''
    const hasMainVisual = c.includes('```mermaid') || c.includes('![可视化') || c.includes('echarts')
    if (hasMainVisual) return true
    if (m.resources?.length) {
      return m.resources.some(r => {
        const rc = r.content || ''
        return rc.includes('```mermaid') || rc.includes('![可视化') || rc.includes('echarts')
      })
    }
    return false
  })
})

// 是否需要右侧画板：有可视化内容或用户主动展开
const shouldShowRightPanel = computed(() => {
  if (rightPanelCollapsed.value) return false
  if (showSandbox.value) return true
  return hasVisualContent.value
})

const studentMastery = computed(() => {
  let profile = latestProfile.value
  if (!profile) {
    for (let i = messages.value.length - 1; i >= 0; i--) {
      if (messages.value[i].role === 'assistant' && messages.value[i].profile) {
        profile = messages.value[i].profile
        break
      }
    }
  }
  if (!profile || !profile.concept_mastery) return []
  return Object.entries(profile.concept_mastery).map(([name, score]) => ({
    name,
    mastery: score,
  }))
})

const targetPoints = computed(() => {
  let profile = latestProfile.value
  if (!profile) {
    for (let i = messages.value.length - 1; i >= 0; i--) {
      if (messages.value[i].role === 'assistant' && messages.value[i].profile) {
        profile = messages.value[i].profile
        break
      }
    }
  }
  if (!profile || !profile.concept_mastery) return []
  return Object.keys(profile.concept_mastery).map(name => ({
    name
  }))
})

const lastAssistantMessage = computed(() => {
  for (let i = messages.value.length - 1; i >= 0; i--) {
    if (messages.value[i].role === 'assistant') {
      return messages.value[i]
    }
  }
  return null
})

const klDivergence = computed(() => {
  return lastAssistantMessage.value?.alignment?.distance ?? 0.0
})

const conflictDetected = computed(() => {
  return !(lastAssistantMessage.value?.alignment?.passed ?? true)
})

const alignmentProgress = computed(() => {
  const dist = klDivergence.value
  if (dist === 0) return 100
  return Math.max(0, Math.min(100, (1 - dist) * 100))
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

async function doArxivSearch() {
  if (!arxivQuery.value.trim()) return
  arxivLoading.value = true
  arxivPapers.value = []
  arxivError.value = ''
  try {
    const data = await searchArxiv(arxivQuery.value, 8)
    if (data.status === 'success') {
      arxivPapers.value = data.papers || []
    } else {
      arxivError.value = '搜索失败'
    }
  } catch (e) {
    arxivError.value = e.message || '请求失败'
  } finally {
    arxivLoading.value = false
  }
}

function sanitizeMermaidCode(code) {
  let lines = code.split(/\r?\n/)
  let result = []
  let isMindmap = false
  let nodeCounter = 0

  const delimPairs = [
    { open: '((', close: '))' },
    { open: '{{', close: '}}' },
    { open: '(', close: ')' },
    { open: '[', close: ']' },
  ];

  for (let line of lines) {
    let trimmed = line.trim()
    if (!trimmed) {
      result.push(line)
      continue
    }

    if (trimmed === 'mindmap') {
      isMindmap = true
      result.push(line)
      continue
    }

    if (!isMindmap) {
      result.push(line)
      continue
    }

    // Preserve indentation
    let indent = line.match(/^(\s*)/)[0]

    // 1. Remove Markdown list markers: - , * , +
    let cleaned = trimmed.replace(/^[-*+]\s+/, '')

    // 2. Remove markdown bold/italic/backticks inside node text (e.g. **text**)
    cleaned = cleaned.replace(/\*\*/g, '').replace(/`/g, '')

    // 3. Skip comments
    if (cleaned.startsWith('%%')) {
      result.push(line)
      continue
    }

    // 4. Strip outer double quotes if they exist around the entire cleaned text
    if (cleaned.startsWith('"') && cleaned.endsWith('"')) {
      cleaned = cleaned.slice(1, -1).trim()
    }

    // 5. Check if it already matches the ID + shape delimiter syntax
    let isShape = false
    let id = ''
    let openDelim = ''
    let innerText = ''
    let closeDelim = ''

    for (const pair of delimPairs) {
      const escapedOpen = pair.open.replace(/[|\\{}()[\]^$+*?.]/g, '\\$&')
      const escapedClose = pair.close.replace(/[|\\{}()[\]^$+*?.]/g, '\\$&')
      const regex = new RegExp(`^([a-zA-Z0-9_-]+)\\s*(${escapedOpen})\\s*(.*?)\\s*(${escapedClose})$`)
      const match = cleaned.match(regex)
      if (match) {
        id = match[1]
        openDelim = match[2]
        innerText = match[3]
        closeDelim = match[4]
        isShape = true
        break
      }
    }

    if (isShape) {
      // Clean inner text: strip quotes inside shape
      let cleanText = innerText.trim()
      if (cleanText.startsWith('"') && cleanText.endsWith('"')) {
        cleanText = cleanText.slice(1, -1)
      }
      // Replace double quotes inside shape with &quot;
      cleanText = cleanText.replace(/\\"/g, '"').replace(/"/g, '&quot;').trim()
      
      // Wrap in double quotes for Mermaid parsing safety
      let wrappedText = '"' + cleanText + '"'
      result.push(indent + id + openDelim + wrappedText + closeDelim)
      continue
    }

    // 6. For plain nodes:
    // If it contains special characters (any char other than a-z, A-Z, 0-9, _, -), wrap it in square brackets shape and generate a unique ID.
    // Otherwise, output as plain text without quotes.
    const hasSpecial = /[^a-zA-Z0-9_\-]/g.test(cleaned)
    if (hasSpecial) {
      nodeCounter++
      const nodeId = `node_${nodeCounter}`
      let cleanText = cleaned.replace(/\\"/g, '"').replace(/"/g, '&quot;').trim()
      let wrappedText = '"' + cleanText + '"'
      result.push(indent + nodeId + '[' + wrappedText + ']')
    } else {
      let cleanText = cleaned.replace(/\\"/g, '"').replace(/"/g, '&quot;').trim()
      result.push(indent + cleanText)
    }
  }

  return result.join('\n')
}

function renderMarkdown(text, type = '', conceptName = '') {
  if (!text) return ''

  let cleaned = text.trim()
  if (cleaned.startsWith('```markdown') && cleaned.endsWith('```')) {
    cleaned = cleaned.slice(11, -3).trim()
  } else if (cleaned.startsWith('```') && cleaned.endsWith('```')) {
    const firstLineEnd = cleaned.indexOf('\n')
    if (firstLineEnd !== -1) {
      const lang = cleaned.substring(3, firstLineEnd).trim().toLowerCase()
      if (lang === '' || lang === 'markdown' || lang === 'text' || lang === 'txt') {
        cleaned = cleaned.substring(firstLineEnd + 1, cleaned.length - 3).trim()
      }
    }
  }

  // Protect SVG blocks from HTML escaping
  const svgBlocks = []
  cleaned = cleaned.replace(/(<svg[\s\S]*?<\/svg>)/gi, (match) => {
    const idx = svgBlocks.length
    svgBlocks.push(match)
    return `@@SVGBLOCKTOKEN${idx}@@`
  })

  let html = cleaned
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')

  // 1. Math extraction: Block math ($$, \[) and inline math ($, \()
  const blockMath = []
  html = html.replace(/\$\$([\s\S]*?)\$\$/g, (_, math) => {
    const idx = blockMath.length
    blockMath.push({ math: math.trim(), display: true })
    return `@@BLOCKMATHTOKEN${idx}@@`
  })
  html = html.replace(/\\\[([\s\S]*?)\\\]/g, (_, math) => {
    const idx = blockMath.length
    blockMath.push({ math: math.trim(), display: true })
    return `@@BLOCKMATHTOKEN${idx}@@`
  })

  const inlineMath = []
  html = html.replace(/\\\(([\s\S]*?)\\\)/g, (_, math) => {
    const idx = inlineMath.length
    inlineMath.push({ math: math.trim(), display: false })
    return `@@INLINEMATHTOKEN${idx}@@`
  })
  html = html.replace(/\$([^$\n]+?)\$/g, (_, math) => {
    const idx = inlineMath.length
    inlineMath.push({ math: math.trim(), display: false })
    return `@@INLINEMATHTOKEN${idx}@@`
  })

  // 2. Code blocks extraction
  const codeBlocks = []
  html = html.replace(/```([^\r\n]*)\r?\n([\s\S]*?)```/g, (_, lang, code) => {
    const isMermaid = lang.toLowerCase().includes('mermaid') || code.includes('mindmap') || code.includes('graph ') || code.includes('sequenceDiagram')
    let blockHtml = ''
    if (isMermaid) {
      // Unescape HTML entities first (since the message was escaped at the start of renderMarkdown)
      let cleanCode = code.trim()
        .replace(/&amp;/g, '&')
        .replace(/&lt;/g, '<')
        .replace(/&gt;/g, '>')
        .replace(/&quot;/g, '"')
        .replace(/&#39;/g, "'")

      const tokenRegex = /@@INLINEMATHTOKEN(\d+)@@/g
      cleanCode = cleanCode.replace(tokenRegex, (match, idx) => {
        const item = inlineMath[parseInt(idx)]
        if (item) {
          // Strip LaTeX symbols and dollar signs for clean plain text in Mermaid
          return item.math
            .replace(/\$/g, '')
            .replace(/\\hat\{([a-zA-Z0-9]+)\}/g, '$1^')
            .replace(/\\frac\{([^}]+)\}\{([^}]+)\}/g, '$1/$2')
            .replace(/\\partial/g, 'd')
            .replace(/\\Sigma/g, 'sum')
            .replace(/\\sigma/g, 'sigma')
            .replace(/\\alpha/g, 'alpha')
            .replace(/\\cdot/g, '·')
            .replace(/\\/g, '')
        }
        return ''
      })

      const blockTokenRegex = /@@BLOCKMATHTOKEN(\d+)@@/g
      cleanCode = cleanCode.replace(blockTokenRegex, (match, idx) => {
        const item = blockMath[parseInt(idx)]
        if (item) {
          return item.math
            .replace(/\$/g, '')
            .replace(/\\hat\{([a-zA-Z0-9]+)\}/g, '$1^')
            .replace(/\\frac\{([^}]+)\}\{([^}]+)\}/g, '$1/$2')
            .replace(/\\partial/g, 'd')
            .replace(/\\Sigma/g, 'sum')
            .replace(/\\sigma/g, 'sigma')
            .replace(/\\alpha/g, 'alpha')
            .replace(/\\cdot/g, '·')
            .replace(/\\/g, '')
        }
        return ''
      })

      // Run mindmap/syntax auto-heal on Mermaid code
      cleanCode = sanitizeMermaidCode(cleanCode)

      // We HTML-escape the raw Mermaid code inside data-code attribute to prevent issues
      const escapedCode = encodeURIComponent(cleanCode)

      if (cleanCode.includes('mindmap')) {
        blockHtml = `<div class="custom-mindmap-placeholder" data-code="${escapedCode}"></div>`
      } else {
        blockHtml = `<div class="my-3 p-4 bg-white border border-gray-200 rounded-xl text-xs flex flex-col items-center shadow-sm max-w-full">
          <div class="w-full flex items-center justify-between mb-3 pb-2 border-b border-gray-100">
            <div class="flex items-center gap-1.5">
              <span class="text-base">📊</span>
              <span class="font-bold text-gray-800 text-xs">概念思维导图</span>
            </div>
            <div class="flex items-center gap-2">
              <button onclick="window.zoomMindmap && window.zoomMindmap(this)" class="px-2 py-1 bg-indigo-50 hover:bg-indigo-100 text-indigo-600 rounded text-[10px] font-semibold transition-all flex items-center gap-0.5 shadow-sm">
                🔍 放大/全屏
              </button>
              <span class="text-[9px] bg-purple-50 text-purple-600 px-1.5 py-0.5 rounded font-mono font-medium">Mermaid</span>
            </div>
          </div>
          <div class="mermaid-container w-full overflow-auto flex justify-center py-2 bg-white max-h-[300px]" style="cursor: zoom-in;" onclick="window.zoomMindmap && window.zoomMindmap(this)">
            <div class="mermaid w-full flex justify-center" data-code="${escapedCode}">${cleanCode}</div>
          </div>
          <!-- 调试面板：折叠展示原始及清洗后的代码 -->
          <details class="w-full mt-2 pt-2 border-t border-gray-100 text-[10px] text-gray-400 cursor-pointer">
            <summary class="hover:text-gray-600 select-none text-[9px] font-semibold">🔍 查看 Mermaid 源码与自愈调试信息</summary>
            <div class="mt-2 p-2 bg-gray-50 rounded font-mono text-[9px] whitespace-pre overflow-x-auto text-left text-gray-600">
<strong>[自愈清洗后代码]:</strong>\n${cleanCode}\n\n<strong>[大模型原始输出]:</strong>\n${code.trim()}
            </div>
          </details>
        </div>`
      }
    } else {
      blockHtml = `<pre class="my-3 p-3 bg-gray-900 text-green-400 rounded-lg overflow-x-auto font-mono text-xs leading-relaxed">${code.trim()}</pre>`
    }
    const idx = codeBlocks.length
    codeBlocks.push(blockHtml)
    return `@@CODEBLOCKTOKEN${idx}@@`
  })

  // 3. Line-by-line processing for Tables and Lists
  const lines = html.split('\n')
  let inTable = false
  let tableHeader = []
  let tableRows = []
  let inList = false
  const processedLines = []

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i]
    const trimmed = line.trim()

    // Table checking
    const isTableRow = trimmed.startsWith('|') && trimmed.endsWith('|')
    if (isTableRow) {
      if (inList) {
        processedLines.push('</ul>')
        inList = false
      }
      const cells = trimmed.slice(1, -1).split('|').map(c => c.trim())
      const isSeparator = cells.every(c => /^[:-]+$/.test(c))
      if (isSeparator) {
        continue
      }
      if (!inTable) {
        inTable = true
        tableHeader = cells
      } else {
        tableRows.push(cells)
      }
      continue
    } else {
      if (inTable) {
        processedLines.push(generateTableHtml(tableHeader, tableRows))
        inTable = false
        tableHeader = []
        tableRows = []
      }
    }

    // List item checking
    const listMatch = line.match(/^(\s*)[-*+]\s+(.*)$/)
    if (listMatch) {
      const content = listMatch[2]
      if (!inList) {
        processedLines.push('<ul class="my-2 space-y-1 list-disc list-inside">')
        inList = true
      }
      processedLines.push(`<li class="ml-4 text-xs text-gray-600 my-1 leading-relaxed">${content}</li>`)
    } else {
      if (inList) {
        processedLines.push('</ul>')
        inList = false
      }
      processedLines.push(line)
    }
  }

  if (inTable) {
    processedLines.push(generateTableHtml(tableHeader, tableRows))
  }
  if (inList) {
    processedLines.push('</ul>')
  }

  html = processedLines.join('\n')

  // Helper for Table HTML generation
  function generateTableHtml(header, rows) {
    let tableHtml = '<div class="overflow-x-auto my-4 border border-gray-200/80 rounded-xl shadow-sm bg-white"><table class="min-w-full divide-y divide-gray-200">'
    if (header && header.length > 0) {
      tableHtml += '<thead class="bg-gray-50/75"><tr>'
      header.forEach(h => {
        tableHtml += `<th class="px-4 py-2.5 text-left text-xs font-semibold text-gray-700 uppercase tracking-wider">${h}</th>`
      })
      tableHtml += '</tr></thead>'
    }
    tableHtml += '<tbody class="divide-y divide-gray-100 bg-white">'
    rows.forEach(row => {
      tableHtml += '<tr class="hover:bg-gray-50/50 transition-colors">'
      row.forEach(cell => {
        tableHtml += `<td class="px-4 py-2 text-xs text-gray-600">${cell}</td>`
      })
      tableHtml += '</tr>'
    })
    tableHtml += '</tbody></table></div>'
    return tableHtml
  }

  // 4. General inline Markdown replacements
  html = html.replace(/!\[([^\]]*)\]\(([^)]+)\)/g, '<img src="$2" alt="$1" class="max-w-full max-h-[300px] object-contain rounded-xl my-3 shadow-sm border border-gray-100 bg-white p-1" />')
  html = html.replace(/\*\*([^*]+)\*\*/g, '<strong class="font-bold text-gray-900">$1</strong>')
  html = html.replace(/\*([^*]+)\*/g, '<em class="italic text-gray-800">$1</em>')
  html = html.replace(/`([^`]+)`/g, '<code class="px-1.5 py-0.5 bg-gray-100 text-red-600 rounded font-mono text-xs font-medium">$1</code>')
  html = html.replace(/^### (.*$)/gim, '<h4 class="text-xs font-bold text-gray-800 mt-4 mb-1.5 flex items-center gap-1">$1</h4>')
  html = html.replace(/^## (.*$)/gim, '<h3 class="text-sm font-semibold text-gray-900 mt-5 mb-2 border-b border-gray-100 pb-1 flex items-center gap-1.5">$1</h3>')
  html = html.replace(/^# (.*$)/gim, '<h2 class="text-base font-bold text-gray-900 mt-6 mb-3 flex items-center gap-2">$1</h2>')

  // Paragraph spacing
  html = html.replace(/\n\n/g, '<div class="h-2.5"></div>')

  // Helper to render math
  function renderMath(math, display) {
    if (window.katex) {
      try {
        return window.katex.renderToString(math, {
          displayMode: display,
          throwOnError: false,
          trust: true
        })
      } catch (err) {
        console.error('KaTeX rendering error:', err)
      }
    }
    // Fallback: raw but clean formatting with math symbols
    const cleanMath = math
      .replace(/\\Sigma/g, '∑')
      .replace(/\\sigma/g, 'σ')
      .replace(/\\mu/g, 'μ')
      .replace(/\\beta/g, 'β')
      .replace(/\\theta/g, 'θ')
      .replace(/\\alpha/g, 'α')
      .replace(/\\lambda/g, 'λ')
      .replace(/\\partial/g, '∂')
      .replace(/\\infty/g, '∞')
      .replace(/\\hat\{([a-zA-Z0-9]+)\}/g, '<span style="text-decoration: overline">$1</span>')
      .replace(/([a-zA-Z0-9]+)_([a-zA-Z0-9]+)/g, '$1<sub>$2</sub>')
      .replace(/([a-zA-Z0-9]+)\^([a-zA-Z0-9]+)/g, '$1<sup>$2</sup>')
      .replace(/\\cdot/g, '·')
      .replace(/\\times/g, '×')
      .replace(/\\frac\{([^}]+)\}\{([^}]+)\}/g, '($1)/($2)')
      .replace(/\\sqrt\{([^}]+)\}/g, '√($1)')
      .replace(/\\text\{([^}]+)\}/g, '$1')
      .replace(/\\quad/g, '&nbsp;&nbsp;')

    if (display) {
      return `<div class="my-3.5 p-4 bg-gray-50/75 border border-gray-100 rounded-xl text-center font-serif text-sm overflow-x-auto select-all shadow-inner text-gray-800">${cleanMath}</div>`
    } else {
      return `<span class="font-serif italic bg-gray-50/75 px-1.5 py-0.5 rounded text-xs select-all text-gray-800 border border-gray-100/50">${cleanMath}</span>`
    }
  }

  // Format any raw plain LaTeX variables left in text (not inside HTML tags or code blocks)
  html = html
    .replace(/\\in\b/g, ' ∈ ')
    .replace(/\\sigma\b/g, 'σ')
    .replace(/\\hat\{([a-zA-Z0-9]+)\}/g, '<span style="text-decoration: overline">$1</span>')
    .replace(/\\([{}])/g, '$1')
    .replace(/([a-zA-Z0-9])_([a-zA-Z0-9_]+)/g, '$1<sub>$2</sub>')
    .replace(/([a-zA-Z0-9])_\{([^}]+)\}/g, '$1<sub>$2</sub>')
    .replace(/([a-zA-Z0-9])\^([a-zA-Z0-9+-\\*\\top\\partial]+)/g, (match, base, exp) => {
      const displayExp = exp === '\\top' || exp === 'top' ? 'T' : exp
      return `${base}<sup>${displayExp}</sup>`
    })
    .replace(/([a-zA-Z0-9])\^\{([^}]+)\}/g, (match, base, exp) => {
      const displayExp = exp === '\\top' || exp === 'top' ? 'T' : exp
      return `${base}<sup>${displayExp}</sup>`
    })

  // 5. Restore block and inline math, code blocks, and SVG blocks
  blockMath.forEach((item, idx) => {
    html = html.split(`@@BLOCKMATHTOKEN${idx}@@`).join(renderMath(item.math, true))
  })
  inlineMath.forEach((item, idx) => {
    html = html.split(`@@INLINEMATHTOKEN${idx}@@`).join(renderMath(item.math, false))
  })
  codeBlocks.forEach((block, idx) => {
    html = html.split(`@@CODEBLOCKTOKEN${idx}@@`).join(block)
  })
  svgBlocks.forEach((block, idx) => {
    html = html.split(`@@SVGBLOCKTOKEN${idx}@@`).join(block)
  })

  // 6. Append quiz CAT link button for assessor agent or Video button for director agent
  const normalizedType = type.toLowerCase()
  if (normalizedType.includes('assess') || normalizedType.includes('quiz') || normalizedType.includes('考官') || normalizedType.includes('评测')) {
    const escapedConcept = (conceptName || '机器学习').replace(/'/g, "\\'")
    html += `<div class="mt-4 p-3 bg-blue-50/50 rounded-xl border border-blue-100 flex items-center justify-between animate-fade-in">
      <div class="text-xs text-blue-800">
        <strong>📝 评测联动已就绪：</strong>已为您准备了针对此概念的自适应多步评测。
      </div>
      <button onclick="window.startInteractiveQuiz && window.startInteractiveQuiz('${escapedConcept}')" class="px-3.5 py-1.5 bg-blue-600 hover:bg-blue-700 text-white rounded-lg text-xs font-semibold shadow-sm transition-all whitespace-nowrap">
        去测验板作答 (CAT) →
      </button>
    </div>`
  } else if (normalizedType.includes('director') || normalizedType.includes('video') || normalizedType.includes('导演') || normalizedType.includes('视频')) {
    html += `<div class="mt-4 p-3 bg-indigo-50/50 rounded-xl border border-indigo-100 flex items-center justify-between animate-fade-in">
      <div class="text-xs text-indigo-800">
        <strong>🎬 视频演示已就绪：</strong>已为您量身定制并合成了该知识点的教学短视频。
      </div>
      <button onclick="window.startInteractiveVideo && window.startInteractiveVideo()" class="px-3.5 py-1.5 bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg text-xs font-semibold shadow-sm transition-all whitespace-nowrap">
        播放讲解视频 →
      </button>
    </div>`
  }

  return html
}
</script>

<template>
  <div class="flex gap-4 h-full">
    <!-- Main content area -->
    <div class="flex-1 flex flex-col min-w-0">
      <!-- Premium Tabs -->
      <div class="flex items-center justify-between mb-5 border-b border-gray-100 pb-0">
        <div class="flex gap-0.5 bg-gray-50/80 backdrop-blur-sm rounded-xl p-0.5 shadow-sm">
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
        <button v-if="activeTab === 'chat' && rightPanelCollapsed"
          @click="rightPanelCollapsed = false"
          class="px-2.5 py-1 text-xs font-semibold text-indigo-600 bg-indigo-50 hover:bg-indigo-100 rounded-lg flex items-center gap-1 transition-all">
          <Maximize2 :size="12" /> 展开可视化画板
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
              <!-- 用户消息气泡：圆角矩形，加深蓝色精致边框，大行距，优雅字体 -->
              <div class="max-w-[75%] chat-card-user text-blue-600 shadow-sm">
                <p class="text-sm whitespace-pre-wrap leading-relaxed">{{ msg.content }}</p>
              </div>
            </div>

            <!-- 任务 8.1: data-msg-index 用于行级点击定位 -->
            <div v-else class="mb-4 chat-message" :data-msg-index="idx">
              <div class="flex items-start gap-3">
                <div class="w-8 h-8 rounded-xl bg-gradient-to-br from-blue-500 to-purple-600 flex items-center justify-center shrink-0">
                  <Bot :size="16" class="text-white" />
                </div>
                <div class="flex-1 min-w-0">
                  <div class="card chat-card-assistant">
                    <!-- 任务 8.3: 讲义操作栏 -->
                    <div class="flex items-center justify-end gap-1 mb-1 pb-1 border-b border-gray-100">
                      <button v-if="msg.target" @click="showConceptCode(idx)" class="text-[10px] text-gray-400 hover:text-emerald-600 flex items-center gap-0.5 px-1.5 py-0.5 hover:bg-emerald-50 rounded transition-colors"
                        title="查看此概念的代码实现">
                        <Terminal :size="10" /> 代码
                      </button>
                      <button @click="exportAsMarkdown(idx)" class="text-[10px] text-gray-400 hover:text-blue-600 flex items-center gap-0.5 px-1.5 py-0.5 hover:bg-blue-50 rounded transition-colors"
                        title="导出为 Markdown">
                        <Download :size="10" /> 导出
                      </button>
                      <span class="text-[9px] text-gray-300">💡 点击代码块/公式可即时答疑</span>
                    </div>
                    <div class="prose prose-sm max-w-none text-sm" v-html="renderMarkdown(msg.content)"></div>
                    <!-- 打字光标 -->
                    <span v-if="idx === messages.length - 1 && chatStore.sending"
                      class="inline-block w-[2px] h-4 bg-blue-500 animate-pulse ml-0.5 align-text-bottom" />
                  </div>

                  <!-- 任务 8.3: 资源卡片 + 局部重生成按钮 -->
                  <div v-if="msg.resources?.length" class="mt-3 space-y-2.5">
                    <div v-for="(res, ri) in msg.resources" :key="ri"
                      class="border border-gray-200/80 rounded-xl overflow-hidden shadow-sm hover:shadow-md transition-all duration-200 bg-white"
                      :class="{ 'ring-2 ring-yellow-400/50 bg-yellow-50/20': res._regenerating }">
                      <div class="flex items-center justify-between px-4 py-3 cursor-pointer bg-gray-50/75 hover:bg-gray-100/70 transition-colors" @click="toggleResource(idx, ri)">
                        <div class="flex items-center gap-2.5 min-w-0">
                          <span class="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-semibold border shadow-sm"
                            :class="getAgentConfig(res.agent, res.resource_type || res.type).color">
                            <component :is="getIconComponent(getAgentConfig(res.agent, res.resource_type || res.type).icon)" class="w-3.5 h-3.5" />
                            {{ getAgentConfig(res.agent, res.resource_type || res.type).label }}
                          </span>
                          <span v-if="res.citations?.length" class="text-[10px] text-gray-400 font-medium px-1.5 py-0.5 bg-gray-100 rounded-md">{{ res.citations.length }} 引用</span>
                          <span v-if="res._regenerating" class="text-[10px] text-yellow-600 flex items-center gap-1 font-medium bg-yellow-50 border border-yellow-100 px-2 py-0.5 rounded-full">
                            <Loader2 :size="10" class="animate-spin text-yellow-500" /> 正在重新生成...
                          </span>
                        </div>
                        <div class="flex items-center gap-2">
                          <!-- 代码资源：运行按钮 -->
                          <button v-if="(res.resource_type || res.type) === '代码实操案例'"
                            @click.stop="runResourceCode(idx, ri)"
                            class="text-xs text-emerald-600 hover:text-emerald-700 flex items-center gap-1 px-2 py-1 hover:bg-emerald-50 rounded-lg border border-emerald-200/60 shadow-sm transition-all"
                            title="运行此代码">
                            <Play :size="11" /> 运行
                          </button>
                          <button @click.stop="regenerateCard(idx, ri)"
                            class="text-xs text-gray-500 hover:text-blue-600 flex items-center gap-1 px-2 py-1 hover:bg-white rounded-lg border border-gray-200/60 shadow-sm transition-all"
                            title="重新生成此模块">
                            <RotateCcw :size="11" /> 重算
                          </button>
                          <div class="w-5 h-5 rounded-full flex items-center justify-center bg-gray-200/50 text-gray-500">
                            <ChevronDown v-if="!showResources.has(`${idx}-${ri}`)" :size="12" class="shrink-0" />
                            <ChevronUp v-else :size="12" class="shrink-0" />
                          </div>
                        </div>
                      </div>
                      <div v-if="showResources.has(`${idx}-${ri}`)" class="px-5 py-4 border-t border-gray-100 bg-white">
                        <div class="prose prose-sm max-w-none text-xs text-gray-700 leading-relaxed" v-html="renderMarkdown(res.content, res.type || res.resource_type || res.agent, msg.target)"></div>
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
        <div v-if="quizState === 'idle'" class="flex-1 flex flex-col items-center justify-center text-center">
          <div class="w-16 h-16 bg-gradient-to-br from-purple-50 to-purple-100 rounded-2xl flex items-center justify-center mb-4 shadow-sm">
            <BrainCircuit :size="32" class="text-purple-500" />
          </div>
          <p class="text-sm font-semibold text-gray-700 mb-1">自适应测验</p>
          <p class="text-xs text-gray-400 mb-5">选择知识点，AI 将动态生成针对性题目</p>
          <div class="flex gap-2 mb-5 flex-wrap justify-center">
            <button v-for="concept in ['逻辑回归', '池化层', '过拟合', '反向传播', '卷积神经网络']" :key="concept"
              class="px-3.5 py-2 text-xs font-medium rounded-xl border border-gray-200 bg-white hover:bg-purple-50 hover:border-purple-200 hover:text-purple-700 text-gray-600 transition-all shadow-sm"
              @click="quizConcept = concept; startQuiz()">
              {{ concept }}
            </button>
          </div>
          <div class="flex gap-2 w-full max-w-md">
            <input v-model="quizConcept" class="flex-1 px-4 py-2.5 text-sm rounded-xl border border-gray-200 bg-white focus:border-purple-300 focus:ring-2 focus:ring-purple-100 outline-none transition-all placeholder:text-gray-300" placeholder="输入自定义知识点..." @keydown.enter="startQuiz" />
            <button class="px-5 py-2.5 text-sm font-semibold rounded-xl bg-gradient-to-r from-purple-600 to-indigo-600 text-white hover:from-purple-700 hover:to-indigo-700 shadow-sm transition-all" :disabled="!quizConcept.trim()" @click="startQuiz">开始</button>
          </div>
        </div>

        <!-- Generating -->
        <div v-if="quizState === 'generating'" class="flex-1 flex items-center justify-center text-gray-400">
          <Loader2 :size="24" class="animate-spin mr-2" /> 正在生成题目...
        </div>

        <!-- Answering -->
        <div v-if="quizState === 'answering' && quizData" class="flex-1 flex flex-col">
          <div class="bg-white rounded-2xl border border-gray-100 shadow-sm p-5 mb-4">
            <div class="flex items-center gap-2 mb-3">
              <span class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-gradient-to-r from-purple-50 to-purple-100 text-purple-700">第 {{ quizAttempt }} 题</span>
              <span class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-gradient-to-r from-blue-50 to-blue-100 text-blue-700">{{ quizData.concept }}</span>
              <span class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-gradient-to-r from-gray-50 to-gray-100 text-gray-600">{{ quizData.difficulty }}</span>
            </div>
            <p class="text-sm font-medium text-gray-800 leading-relaxed mb-4">{{ quizData.question }}</p>
            <div v-if="quizData.hints?.length" class="bg-amber-50/80 border border-amber-100 rounded-xl p-3.5 space-y-2">
              <p class="text-xs font-semibold text-amber-700 flex items-center gap-1.5">
                <Lightbulb :size="13" /> 提示阶梯
              </p>
              <p v-for="(hint, hi) in quizData.hints" :key="hi" class="text-xs text-amber-700/80 pl-3 border-l-2 border-amber-200 leading-relaxed">{{ hint }}</p>
            </div>
          </div>

          <div class="flex-1" />
          <textarea v-model="quizAnswer" class="w-full px-4 py-3 text-sm rounded-xl border border-gray-200 bg-white focus:border-purple-300 focus:ring-2 focus:ring-purple-100 outline-none transition-all resize-none min-h-[90px] placeholder:text-gray-300" placeholder="输入你的答案..." />
          <div class="flex items-center gap-3 my-3 bg-gray-50/80 rounded-xl px-4 py-2.5">
            <span class="text-xs text-gray-500 shrink-0 font-medium">自评置信度</span>
            <input type="range" min="1" max="10" v-model.number="quizConfidence" class="flex-1 accent-purple-600 h-1.5" />
            <span class="text-xs font-bold text-purple-700 w-8 text-right bg-purple-50 rounded-lg px-2 py-0.5">{{ quizConfidence }}/10</span>
          </div>
          <button class="w-full py-2.5 text-sm font-semibold rounded-xl bg-gradient-to-r from-purple-600 to-indigo-600 text-white hover:from-purple-700 hover:to-indigo-700 shadow-sm transition-all flex items-center justify-center gap-2" :disabled="!quizAnswer.trim()" @click="submitQuizAnswer">
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

            <!-- 逐点对比 -->
            <div v-if="quizResult.student_answer || quizResult.reference_answer" class="grid grid-cols-2 gap-3">
              <div class="bg-blue-50/80 rounded-xl p-3 border border-blue-100/50">
                <p class="font-medium text-xs text-blue-700 mb-1.5 flex items-center gap-1">
                  <span class="w-1.5 h-1.5 rounded-full bg-blue-500" /> 你的答案
                </p>
                <p class="text-xs text-blue-900/70 leading-relaxed whitespace-pre-wrap">{{ quizResult.student_answer || '(空)' }}</p>
              </div>
              <div class="bg-green-50/80 rounded-xl p-3 border border-green-100/50">
                <p class="font-medium text-xs text-green-700 mb-1.5 flex items-center gap-1">
                  <span class="w-1.5 h-1.5 rounded-full bg-green-500" /> 参考答案
                </p>
                <p class="text-xs text-green-900/70 leading-relaxed whitespace-pre-wrap">{{ quizResult.reference_answer || '(空)' }}</p>
              </div>
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
            <Terminal :size="16" class="text-emerald-600" /> Python 代码沙箱
          </h3>
          <div class="flex gap-1">
            <button v-for="preset in codePresets" :key="preset.label" class="px-2.5 py-1 text-[10px] font-medium rounded-lg border border-gray-200 bg-white hover:bg-emerald-50 hover:border-emerald-200 hover:text-emerald-700 text-gray-500 transition-all" @click="insertCodeSnippet(preset.code)">{{ preset.label }}</button>
          </div>
        </div>

        <div class="flex-1 flex flex-col min-h-0">
          <div class="flex-1 flex flex-col rounded-xl border border-gray-200 overflow-hidden shadow-sm">
            <div class="bg-gray-900 text-gray-300 text-xs px-4 py-2 flex items-center justify-between">
              <div class="flex items-center gap-2">
                <span class="w-2.5 h-2.5 rounded-full bg-red-400" />
                <span class="w-2.5 h-2.5 rounded-full bg-yellow-400" />
                <span class="w-2.5 h-2.5 rounded-full bg-green-400" />
                <span class="ml-2 font-mono text-gray-400">sandbox.py</span>
              </div>
              <button class="px-3 py-1 text-[10px] font-semibold rounded-lg bg-emerald-500 hover:bg-emerald-600 text-white transition-all flex items-center gap-1.5" :disabled="!codeInput.trim() || codeRunning" @click="runUserCode">
                <Play :size="10" /> {{ codeRunning ? '运行中...' : '运行' }}
              </button>
            </div>
            <textarea v-model="codeInput" class="flex-1 bg-gray-900 text-emerald-300 font-mono text-xs p-4 resize-none outline-none leading-relaxed" placeholder="# 在这里输入 Python 代码..." spellcheck="false" />
            <!-- 行号和复制按钮 -->
            <div class="absolute top-9 right-2 flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
              <button class="p-1.5 rounded-md bg-gray-800 hover:bg-gray-700 text-gray-400 hover:text-white transition-all" title="复制代码" @click="copyCode">
                <Copy :size="12" />
              </button>
            </div>
          </div>

          <div v-if="codeOutput || codeError" class="mt-3 rounded-xl border border-gray-200 overflow-hidden shadow-sm">
            <div class="bg-gray-100 text-xs px-4 py-2 text-gray-500 flex items-center justify-between">
              <span class="font-medium flex items-center gap-1.5"><Terminal :size="12" /> 输出 ({{ codeExecTime }}ms)</span>
              <button class="text-gray-400 hover:text-gray-600 p-1 rounded-lg hover:bg-gray-200 transition-all" @click="codeOutput = ''; codeError = ''"><Trash2 :size="12" /></button>
            </div>
            <div class="bg-gray-50 p-4 max-h-48 overflow-y-auto">
              <pre v-if="codeOutput" class="text-xs text-gray-800 whitespace-pre-wrap font-mono leading-relaxed">{{ codeOutput }}</pre>
              <pre v-if="codeError" class="text-xs text-red-600 whitespace-pre-wrap font-mono leading-relaxed">{{ codeError }}</pre>
            </div>
          </div>
        </div>
      </div>

      <!-- WEB SEARCH TAB -->
      <div v-if="activeTab === 'websearch'" class="flex flex-col flex-1 min-h-0 max-w-4xl">
        <div class="flex items-center gap-2 mb-4">
          <div class="w-9 h-9 rounded-xl bg-gradient-to-br from-blue-50 to-blue-100 flex items-center justify-center">
            <Globe :size="18" class="text-blue-500" />
          </div>
          <div>
            <h3 class="text-sm font-semibold text-gray-800">联网搜索</h3>
            <p class="text-[10px] text-gray-400">检索互联网资源辅助学习</p>
          </div>
        </div>

        <div class="space-y-4">
          <div class="bg-white rounded-2xl border border-gray-100 shadow-sm p-4">
            <div class="flex gap-2">
              <div class="relative flex-1">
                <Search :size="14" class="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
                <input v-model="searchQuery" class="w-full pl-9 pr-3 py-2.5 text-sm rounded-xl border border-gray-200 bg-white focus:border-blue-300 focus:ring-2 focus:ring-blue-100 outline-none transition-all placeholder:text-gray-300" placeholder="输入搜索关键词..." @keydown.enter="doWebSearch" />
              </div>
              <button class="px-4 py-2.5 text-sm font-semibold rounded-xl bg-gradient-to-r from-blue-600 to-indigo-600 text-white hover:from-blue-700 hover:to-indigo-700 shadow-sm transition-all flex items-center gap-1.5" :disabled="!searchQuery.trim() || searchLoading" @click="doWebSearch">
                <Search :size="14" /> {{ searchLoading ? '搜索中...' : '搜索' }}
              </button>
            </div>
            <div v-if="searchLoading" class="flex items-center gap-2 mt-3 text-gray-400 text-xs">
              <div class="w-4 h-4 border-2 border-blue-400 border-t-transparent rounded-full animate-spin" />
              正在搜索并索引...
            </div>
            <div v-if="searchSummary" class="mt-3 text-sm text-gray-700 bg-gradient-to-r from-blue-50 to-indigo-50/50 rounded-xl p-4 whitespace-pre-wrap border border-blue-100/50 leading-relaxed">{{ searchSummary }}</div>
            <div v-if="searchResults.length" class="mt-3 space-y-1">
              <div v-for="(r, i) in searchResults" :key="i" class="flex items-start gap-3 p-3 rounded-xl hover:bg-gray-50 transition-all cursor-pointer" @click="window.open(r.url, '_blank')">
                <div class="w-6 h-6 rounded-lg bg-gradient-to-br from-blue-50 to-indigo-50 flex items-center justify-center shrink-0 mt-0.5">
                  <FileText :size="12" class="text-blue-500" />
                </div>
                <div class="min-w-0 flex-1">
                  <p class="text-xs font-semibold text-gray-800 hover:text-blue-600 truncate">{{ r.title }}</p>
                  <p class="text-[10px] text-gray-400 mt-0.5 line-clamp-2 leading-relaxed">{{ r.snippet }}</p>
                  <p v-if="r.url" class="text-[9px] text-gray-300 mt-0.5 truncate flex items-center gap-1">
                    <Globe :size="8" class="shrink-0" />
                    {{ new URL(r.url).hostname.replace('www.', '') }}
                  </p>
                </div>
              </div>
            </div>
          </div>

          <div class="bg-white rounded-2xl border border-gray-100 shadow-sm p-4">
            <p class="text-xs font-semibold text-gray-600 mb-3 flex items-center gap-1.5">
              <ExternalLink :size="13" class="text-indigo-500" /> 加载网页内容
            </p>
            <div class="flex gap-2">
              <input v-model="urlInput" class="flex-1 px-4 py-2.5 text-sm rounded-xl border border-gray-200 bg-white focus:border-indigo-300 focus:ring-2 focus:ring-indigo-100 outline-none transition-all placeholder:text-gray-300" placeholder="输入网页URL..." @keydown.enter="doLoadUrl" />
              <button class="px-4 py-2.5 text-sm font-semibold rounded-xl bg-gradient-to-r from-indigo-600 to-blue-600 text-white hover:from-indigo-700 hover:to-blue-700 shadow-sm transition-all flex items-center gap-1.5" :disabled="!urlInput.trim() || urlLoading" @click="doLoadUrl">
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

          <!-- 学术论文搜索 -->
          <div class="bg-white rounded-2xl border border-gray-100 shadow-sm p-4">
            <p class="text-xs font-semibold text-gray-600 mb-3 flex items-center gap-1.5">
              <FileText :size="13" class="text-rose-500" /> 学术论文 (arXiv)
            </p>
            <div class="flex gap-2">
              <input v-model="arxivQuery" class="flex-1 px-4 py-2.5 text-sm rounded-xl border border-gray-200 bg-white focus:border-rose-300 focus:ring-2 focus:ring-rose-100 outline-none transition-all placeholder:text-gray-300" placeholder="搜索学术论文..." @keydown.enter="doArxivSearch" />
              <button class="px-4 py-2.5 text-sm font-semibold rounded-xl bg-gradient-to-r from-rose-600 to-pink-600 text-white hover:from-rose-700 hover:to-pink-700 shadow-sm transition-all flex items-center gap-1.5" :disabled="!arxivQuery.trim() || arxivLoading" @click="doArxivSearch">
                <Search :size="14" /> {{ arxivLoading ? '搜索中...' : '论文' }}
              </button>
            </div>
            <div v-if="arxivLoading" class="flex items-center gap-2 mt-3 text-gray-400 text-xs">
              <div class="w-4 h-4 border-2 border-rose-400 border-t-transparent rounded-full animate-spin" />
              正在检索 arXiv...
            </div>
            <div v-if="arxivPapers.length" class="mt-3 space-y-2">
              <div v-for="(p, i) in arxivPapers" :key="i" class="flex items-start gap-3 p-3 rounded-xl hover:bg-rose-50 transition-all">
                <div class="w-6 h-6 rounded-lg bg-gradient-to-br from-rose-50 to-pink-50 flex items-center justify-center shrink-0 mt-0.5">
                  <FileText :size="12" class="text-rose-500" />
                </div>
                <div class="min-w-0 flex-1">
                  <p class="text-xs font-semibold text-gray-800">{{ p.title }}</p>
                  <p class="text-[10px] text-gray-400 mt-0.5 line-clamp-2 leading-relaxed">{{ p.abstract?.replace(/^摘要: /,'')?.slice(0,200) }}{{ p.abstract?.length > 200 ? '...' : '' }}</p>
                  <div class="flex items-center gap-2 mt-1 flex-wrap">
                    <a v-if="p.pdf_url" :href="p.pdf_url" target="_blank" class="text-[9px] text-rose-500 hover:underline font-medium">📄 PDF</a>
                    <a v-if="p.id" :href="'https://arxiv.org/abs/' + p.id.replace('arxiv-','')" target="_blank" class="text-[9px] text-gray-400 hover:underline">arXiv:{{ p.id.replace('arxiv-','') }}</a>
                  </div>
                </div>
              </div>
            </div>
            <div v-if="arxivError" class="mt-3 text-xs text-red-500">{{ arxivError }}</div>
          </div>
        </div>
      </div>

      <!-- Right Visualization Sidebar -->
      <div class="w-80 hidden xl:flex flex-col gap-6 overflow-y-auto scrollbar-none pb-4 shrink-0">
            <AvatarSpeech ref="avatarRef" class="shrink-0" />
            
            <AgentTimeline 
            class="shrink-0"
            :progress="chatStore.streamingProgress" 
            :status="chatStore.streamingStatus" 
            :agents="chatStore.streamingAgents" 
            />

            <MasteryRadar 
            class="shrink-0"
            :concepts="radarConcepts" 
            :student-id="props.studentId" 
            />

            <div class="p-5 border border-indigo-600/35 rounded-xl bg-gradient-to-br from-indigo-500 to-purple-700 text-white shadow-lg mt-auto">
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

    <!-- 概念代码浮窗 -->
    <Teleport to="body">
      <div v-if="conceptCodePopup" class="fixed inset-0 z-50 flex items-center justify-center bg-black/30" @click.self="closeConceptCode">
        <div class="bg-white rounded-2xl shadow-2xl w-[640px] max-h-[70vh] flex flex-col overflow-hidden">
          <div class="flex items-center justify-between px-5 py-3 border-b border-gray-100">
            <h3 class="text-sm font-semibold text-gray-800 flex items-center gap-2">
              <Terminal :size="16" class="text-emerald-600" /> {{ conceptCodePopup.target }} 代码实现
            </h3>
            <button class="text-gray-400 hover:text-gray-600 text-lg leading-none" @click="closeConceptCode">&times;</button>
          </div>
          <div class="flex-1 overflow-y-auto p-5">
            <div v-if="conceptCodePopup.loading" class="flex items-center justify-center py-12 text-gray-400">
              <Loader2 :size="20" class="animate-spin mr-2" /> 正在生成代码...
            </div>
            <div v-else class="prose prose-sm max-w-none text-xs" v-html="renderMarkdown(conceptCodePopup.content)"></div>
          </div>
          <div v-if="!conceptCodePopup.loading" class="flex items-center justify-end gap-2 px-5 py-3 border-t border-gray-100 bg-gray-50">
            <button class="px-3 py-1.5 text-xs font-medium rounded-lg border border-gray-200 bg-white hover:bg-gray-100 transition-all" @click="closeConceptCode">关闭</button>
            <button class="px-3 py-1.5 text-xs font-semibold rounded-lg bg-emerald-500 hover:bg-emerald-600 text-white transition-all flex items-center gap-1" @click="runConceptCode">
              <Play :size="11" /> 运行代码
            </button>
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
          <div v-else class="flex-1 flex flex-col min-h-0">
            <!-- 图表内容区 -->
            <div class="flex-1 relative overflow-auto min-h-0">
              <div class="h-full">
                <GraphicFallback
                  originalType="mermaid"
                  errorMessage="图表渲染参数异常"
                  fallbackText="当前图表格式不支持实时渲染，已降级为文本示意图"
                >
                  <ManifoldVisualizer
                    :studentMastery="studentMastery"
                    :targetPoints="targetPoints"
                    :klDivergence="klDivergence"
                    :alignmentProgress="alignmentProgress"
                    :conflictDetected="conflictDetected"
                  />
                </GraphicFallback>
              </div>
            </div>
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

    <!-- 任务 8.5: 视频渲染面板 -->
    <button
      v-if="activeTab === 'chat'"
      class="fixed bottom-24 right-6 z-40 w-12 h-12 rounded-full bg-blue-600 text-white shadow-lg hover:bg-blue-700 transition-all flex items-center justify-center"
      :title="showVideoPanel ? '关闭视频面板' : '生成讲解视频'"
      @click="toggleVideoPanel"
    >
      <Video :size="20" />
    </button>
    <VideoRenderPanel
      :visible="showVideoPanel"
      :videoUrl="videoPanelUrl"
      :studentId="props.studentId"
      @close="showVideoPanel = false" />

    <!-- 思维导图放大模态框 -->
    <Teleport to="body">
      <div v-if="zoomModal.visible" class="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm" @click.self="closeZoomModal">
        <div class="bg-white rounded-2xl shadow-2xl w-[95vw] h-[90vh] flex flex-col overflow-hidden border border-gray-100">
          <!-- 头部 -->
          <div class="flex items-center justify-between px-6 py-4 border-b border-gray-100 bg-gray-50/50">
            <div class="flex items-center gap-2">
              <span class="text-lg">📊</span>
              <h3 class="text-sm font-bold text-gray-800">思维导图高解析大图 (支持拖拽/缩放)</h3>
            </div>
            <div class="flex items-center gap-3">
              <!-- 缩放控制键 -->
              <div class="flex items-center bg-white border border-gray-200 rounded-lg shadow-sm">
                <button @click="zoomOut" class="px-3 py-1.5 hover:bg-gray-50 border-r border-gray-200 text-xs font-semibold text-gray-600 transition-colors">- 缩小</button>
                <span class="px-3 text-xs font-mono font-bold text-gray-700">{{ (zoomScale * 100).toFixed(0) }}%</span>
                <button @click="zoomIn" class="px-3 py-1.5 hover:bg-gray-50 border-l border-gray-200 text-xs font-semibold text-gray-600 transition-colors">+ 放大</button>
                <button @click="resetZoom" class="px-3 py-1.5 hover:bg-gray-50 border-l border-gray-200 text-xs font-semibold text-gray-600 transition-colors">重置</button>
              </div>
              <button class="px-3 py-1.5 bg-gray-100 hover:bg-gray-200 text-gray-700 rounded-lg text-xs font-semibold transition-colors" @click="closeZoomModal">关闭</button>
            </div>
          </div>
          <!-- 画布内容 -->
          <div class="flex-1 overflow-auto bg-gray-50 flex items-center justify-center relative p-6 cursor-grab active:cursor-grabbing" @mousedown="startPan" @mousemove="doPan" @mouseup="endPan" @mouseleave="endPan">
            <div 
              :key="zoomModal.code" 
              class="zoom-mermaid-target transition-transform duration-200 origin-center bg-white p-8 rounded-xl shadow-md border border-gray-100 flex items-center justify-center animate-fade-in"
              :style="{ transform: `scale(${zoomScale}) translate(${panOffset.x}px, ${panOffset.y}px)` }"
            >
              <div class="mermaid flex justify-center">{{ zoomModal.code }}</div>
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
