<script setup lang="ts">
import { ref, nextTick, computed, onMounted, onUnmounted, watch, createApp } from 'vue'
import { useRoute } from 'vue-router'
import CollapsibleMindmap from '../components/CollapsibleMindmap.vue'
import {
  processMessage, getHistory,
  generateQuiz, evaluateQuizAnswer, adaptQuiz,
  webSearch, loadUrl, searchArxiv,
  runCode, getStudentProfile, regenerateComponent,
  aiPolishNote, createNote, createReviewPlan,
  getLocalAnimations, uploadBehaviorLogs,
} from '../api'
import {
  Send, Bot, User, Loader2, BookOpen, Code2, LayoutGrid, HelpCircle, Video, Cpu,
  CheckCircle2, XCircle, AlertTriangle, ChevronDown, ChevronUp,
  Search, Globe, ExternalLink, Terminal, Play, Trash2, MessageSquare,
  BrainCircuit, Target, TrendingUp, Sparkles, Users,
  RotateCcw, RotateCw, Download, FileText, Maximize2, Minimize2, Lightbulb, Copy, Calendar, X, Film, Upload
} from '@lucide/vue'
import { useChatStore } from '../stores/chat'
import { useQuizStore } from '../stores/quiz'
import SandboxConsole from '../components/SandboxConsole.vue'
import InlineSocraticPopup from '../components/InlineSocraticPopup.vue'
import GraphicFallback from '../components/GraphicFallback.vue'
import KnowledgePointsPanel from '../components/KnowledgePointsPanel.vue'
import SandboxVisualizer from '../components/SandboxVisualizer.vue'
import AgentTimeline from '../components/AgentTimeline.vue'
import MasteryRadar from '../components/MasteryRadar.vue'
import VideoRenderPanel from '../components/VideoRenderPanel.vue'
import LocalVideoPlayer from '../components/LocalVideoPlayer.vue'
import VideoPlayerCard from '../components/VideoPlayerCard.vue'
import ManifoldVisualizer from '../components/ManifoldVisualizer.vue'
import IncrementalMarkdownRenderer from '../components/IncrementalMarkdownRenderer.vue'

const props = defineProps({ studentId: String })
const chatStore = useChatStore()
const quizStore = useQuizStore()
const route = useRoute()



// --- Chat State ---
const messages = computed(() => chatStore.messages)
const sending = computed(() => chatStore.sending)
const streamingContent = computed(() => chatStore.streamingContent || '')

const capturedInitialProfile = ref(null)
const latestProfile = ref(null)

// --- AI 笔记提炼预览舱状态 ---
const showNoteModal = ref(false)
const noteModalLoading = ref(false)
const noteModalForm = ref({ content: '', tags: '', concepts: '', source: '对话同步' })

// --- 思维导图放大模态框状态 ---
const zoomModal = ref({
  visible: false,
  code: '',
})
const zoomScale = ref(1.0)
const panOffset = ref({ x: 0, y: 0 })
const isZoomMindmap = computed(() => /^\s*mindmap\b/i.test(zoomModal.value.code || ''))
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
  if (newVal && !isZoomMindmap.value) {
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
  if (typeof window.Prism !== 'undefined') {
    nextTick(() => {
      window.Prism.highlightAll()
    })
  }
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
            const rawCode = decodeURIComponent(el.getAttribute('data-code') || '')
            if (rawCode) {
              el.textContent = rawCode
            }
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


// --- 任务 7.3: 隐式反馈行为采集 (悬停时长与复制记录) ---
const hoverTimers: Record<number, number> = {}

function startHover(idx: number, concept?: string) {
  if (!concept) return
  hoverTimers[idx] = Date.now()
}

async function endHover(idx: number, concept?: string) {
  const start = hoverTimers[idx]
  if (!start) return
  delete hoverTimers[idx]
  const duration = (Date.now() - start) / 1000
  
  if (duration >= 2.0) {
    try {
      await uploadBehaviorLogs({
        student_id: props.studentId || 'default',
        actual_stay_seconds: duration,
        concept: concept,
        action: 'lecture'
      })
      console.log(`[Behavior Log] Uploaded hover: ${concept}, duration: ${duration.toFixed(2)}s`)
    } catch (e) {
      console.warn('Failed to upload hover logs:', e)
    }
  }
}

async function handleCopyEvent(e: ClipboardEvent) {
  const selection = window.getSelection()?.toString()
  if (!selection || selection.length < 5) return
  
  const card = (e.target as HTMLElement).closest('.chat-message')
  if (!card) return
  
  const msgIndexStr = (card as HTMLElement).dataset?.msgIndex
  if (!msgIndexStr) return
  const msgIndex = parseInt(msgIndexStr)
  if (isNaN(msgIndex) || msgIndex < 0) return
  
  const msg = messages.value[msgIndex]
  if (msg && msg.target) {
    try {
      await uploadBehaviorLogs({
        student_id: props.studentId || 'default',
        actual_stay_seconds: 5.0,
        concept: msg.target,
        action: 'code',
        page_accuracy: 0.8
      })
      console.log(`[Behavior Log] Uploaded copy action for concept: ${msg.target}`)
    } catch (e) {
      console.warn('Failed to upload copy logs:', e)
    }
  }
}

onMounted(() => {
  renderAllDiagrams()
  document.addEventListener('copy', handleCopyEvent)
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

const showComparison = computed(() => {
  return activeTab.value === 'quiz' && quizStore.quizState === 'adapting'
})

watch(sending, async (newVal, oldVal) => {
  if (newVal && !oldVal) {
    // 开始对话时（sending 从 false 变为 true）立即跳到底端一次
    scrollToBottom()
  } else if (!newVal && oldVal) {
    // 生成完毕时（sending 从 true 变为 false）
    try {
      const profile = await getStudentProfile(props.studentId)
      latestProfile.value = profile
    } catch (e) {
      console.error('更新最新学生画像失败:', e)
    }
    // 用多段延迟平滑落底，处理 Mermaid/KaTeX/图片异步排版扩展的高度
    for (const delay of [10, 100, 300, 600, 1000]) {
      setTimeout(scrollToBottom, delay)
    }
  }
})

// 任务 8.2: 页面销毁时不释放流式连接，以支持路由切换导航时后台继续生成
onUnmounted(() => {
  cleanupCustomMindmaps()
  document.removeEventListener('copy', handleCopyEvent)
})

function clearChat() {
  if (confirm('确认清空所有对话历史吗？该操作不可撤销。')) {
    chatStore.clearHistory()
  }
}

const messageListRef = ref(null)

function scrollToTop() {
  const container = document.querySelector('main')
  if (container) {
    container.scrollTo({ top: 0, behavior: 'smooth' })
  }
}

function scrollToBottom() {
  const container = document.querySelector('main')
  if (container) {
    container.scrollTo({ top: container.scrollHeight, behavior: 'smooth' })
  }
}

// Watch for new assistant messages to trigger TTS and auto-scroll
watch(messages, (newMsgs, oldMsgs) => {
  if (!newMsgs || newMsgs.length === 0) return
  
  const lengthIncreased = newMsgs.length > (oldMsgs?.length || 0)
  
  if (lengthIncreased) {
    // 仅在非资源生成期间，新消息到达才自动滚动落底
    if (!sending.value) {
      nextTick(() => {
        scrollToBottom()
      })
    }
    // 自动检测知识点并预加载本地动画
    if (lastMsg.role === 'assistant' && lastMsg.target && !lastMsg.error) {
      const idx = newMsgs.length - 1
      if (!localVideoAttached.value.has(idx)) {
        localVideoAttached.value.add(idx)
        getLocalAnimations(lastMsg.target).then(data => {
          if (data.videos?.length > 0) {
            lastMsg._localVideos = data.videos
            lastMsg._localVideoKp = data.knowledge_point || lastMsg.target
          }
        }).catch(() => {})
      }
    }
  }
}, { deep: true })

const input = ref('')
const showSuggest = ref(false)
const suggestType = ref('') // 'command' | 'file'
const suggestQuery = ref('')
const suggestIndex = ref(0)
const availableCommands = ref([
  { name: '/explain', desc: '强制指定理论教授生成理论讲义', label: '理论精讲' },
  { name: '/map', desc: '强制指定逻辑画师生成 Mermaid 拓扑图', label: '思维导图' },
  { name: '/code', desc: '强制指定极客助教生成 PyTorch 实操代码', label: '代码案例' },
  { name: '/quiz', desc: '强制指定考官智能体生成测验题', label: '随堂测试' },
  { name: '/video', desc: '强制指定虚拟导演生成视频解说脚本', label: '视频讲解' }
])
const availableDocuments = ref([])

import { listKnowledgeDocuments, addWebSource, downloadWebFile, getKnowledgeDocument } from '../api'

const docs = ref([])
const selectedDocIds = ref([])
const leftPanelCollapsed = ref(true)

function getFileIcon(filename, type) {
  if (filename && (filename.startsWith('[网页]') || type === 'web')) return Globe
  if (type && ['mp4', 'avi', 'mov', 'video'].includes(type)) return Film
  return FileText
}

function getFileColorClass(filename, type) {
  if (filename && (filename.startsWith('[网页]') || type === 'web')) return 'text-blue-500 bg-blue-50'
  if (type && ['mp4', 'avi', 'mov', 'video'].includes(type)) return 'text-purple-500 bg-purple-50'
  if (type === 'pptx') return 'text-orange-500 bg-orange-50'
  if (type === 'pdf') return 'text-red-500 bg-red-50'
  return 'text-emerald-500 bg-emerald-50 hover:bg-emerald-100/50'
}

async function loadDocuments() {
  try {
    const data = await listKnowledgeDocuments(props.studentId || 'default')
    docs.value = Array.isArray(data) ? data : []
    // 首次加载时，默认全部勾选
    if (selectedDocIds.value.length === 0) {
      selectedDocIds.value = docs.value.map(d => d.id)
    }
  } catch (e) {
    console.error('Failed to load documents:', e)
  }
}

async function ingestWebSearchItem(item) {
  if (!item || item.adding) return
  item.adding = true
  try {
    const studentId = props.studentId || 'default'
    if (item.is_file) {
      await downloadWebFile(item.url, item.file_type, item.title, studentId)
    } else {
      await addWebSource(searchQuery.value || '未知搜索', item.title, item.url || '', item.snippet || '', studentId)
    }
    // 成功后，重新加载文档列表，使勾选框中能显示新导入的文档
    await loadDocuments()
  } catch (e) {
    console.error('Failed to ingest web search item:', e)
    alert('导入失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    item.adding = false
  }
}

const showDocViewerModal = ref(false)
const docViewerLoading = ref(false)
const activeDocViewer = ref({ title: '', content: '', filename: '', file_type: '', file_size: 0 })

async function openDocViewer(doc) {
  showDocViewerModal.value = true
  docViewerLoading.value = true
  activeDocViewer.value = {
    title: doc.title || doc.filename,
    content: '',
    filename: doc.filename,
    file_type: doc.file_type || 'txt',
    file_size: doc.file_size || 0
  }
  try {
    const studentId = props.studentId || 'default'
    const data = await getKnowledgeDocument(doc.id, studentId)
    activeDocViewer.value.content = data.content || '无文本内容'
  } catch (e) {
    console.error('Failed to load document content:', e)
    activeDocViewer.value.content = '加载失败: ' + (e.message || '未知错误')
  } finally {
    docViewerLoading.value = false
  }
}

const isAllSelected = computed({
  get() {
    return docs.value.length > 0 && selectedDocIds.value.length === docs.value.length
  },
  set(val) {
    if (val) {
      selectedDocIds.value = docs.value.map(d => d.id)
    } else {
      selectedDocIds.value = []
    }
  }
})

async function loadDocsForAutocomplete() {
  try {
    await loadDocuments()
    availableDocuments.value = docs.value.map(d => ({
      name: `@${d.filename}`,
      desc: d.title,
      label: `${(d.file_size / 1024).toFixed(1)} KB`
    }))
  } catch (e) {
    console.error('Failed to load documents for autocomplete:', e)
  }
}

const showDocSelector = ref(false)
const docSelectorQuery = ref('')

function toggleDocSelector() {
  showDocSelector.value = !showDocSelector.value
  if (showDocSelector.value) {
    loadDocsForAutocomplete()
  }
}

const filteredDocSelectorList = computed(() => {
  const list = availableDocuments.value
  if (!docSelectorQuery.value) return list
  const q = docSelectorQuery.value.toLowerCase()
  return list.filter(item => 
    (item.name && item.name.toLowerCase().includes(q)) || 
    (item.desc && item.desc.toLowerCase().includes(q))
  )
})

function insertDocReference(docName) {
  const currentVal = input.value
  if (currentVal.endsWith('@')) {
    input.value = currentVal.slice(0, -1) + docName + ' '
  } else {
    const suffix = currentVal && !currentVal.endsWith(' ') ? ' ' : ''
    input.value = currentVal + suffix + docName + ' '
  }
  showDocSelector.value = false
  docSelectorQuery.value = ''
}

const closeDocSelectorOnOutsideClick = (e: MouseEvent) => {
  const target = e.target as HTMLElement
  if (showDocSelector.value && !target.closest('.doc-selector-trigger') && !target.closest('.doc-selector-panel')) {
    showDocSelector.value = false
  }
}
onMounted(() => {
  window.addEventListener('click', closeDocSelectorOnOutsideClick)
  loadDocuments()
})
onUnmounted(() => {
  window.removeEventListener('click', closeDocSelectorOnOutsideClick)
})

watch(input, (newVal) => {
  if (!newVal) {
    showSuggest.value = false
    return
  }
  const lastWordMatch = newVal.match(/[\/@][^\s]*$/)
  if (lastWordMatch) {
    const trigger = lastWordMatch[0][0]
    const query = lastWordMatch[0].slice(1)
    suggestType.value = trigger === '/' ? 'command' : 'file'
    suggestQuery.value = query
    showSuggest.value = true
    suggestIndex.value = 0
    if (trigger === '@') {
      loadDocsForAutocomplete()
    }
  } else {
    showSuggest.value = false
  }
})

const filteredSuggestions = computed(() => {
  const list = suggestType.value === 'command' ? availableCommands.value : availableDocuments.value
  if (!suggestQuery.value) return list
  const q = suggestQuery.value.toLowerCase()
  return list.filter(item => 
    (item.name && item.name.toLowerCase().includes(q)) || 
    (item.desc && item.desc.toLowerCase().includes(q))
  )
})

function selectSuggestion(item) {
  const currentVal = input.value
  const lastWordMatch = currentVal.match(/[\/@][^\s]*$/)
  if (lastWordMatch) {
    const startIdx = lastWordMatch.index
    input.value = currentVal.slice(0, startIdx) + item.name + ' '
  }
  showSuggest.value = false
}

const showResources = ref(new Set())
watch(showResources, () => {
  renderAllDiagrams()
}, { deep: true })
const activeTab = ref(quizStore.quizState !== 'idle' ? 'quiz' : 'chat') // chat | quiz | code | websearch

const socraticPopup = ref({
  visible: false,
  targetText: '',
  contextBefore: '',
  contextAfter: '',
  lineIndex: 0,
  messageIndex: -1,
  anchorX: null,
  anchorY: null,
})

const textSelection = ref({
  visible: false,
  x: 0,
  y: 0,
  text: '',
})

const quotedContent = ref(null) // { text: '', source: '' }
const isDragging = ref(false)
const dragOffset = { x: 0, y: 0 }

// --- 任务 8.4: 双栏阻尼排版 ---
const rightPanelCollapsed = ref(false)
const rightPanelActiveTab = ref('canvas')
const sandboxInitialCode = ref("import numpy as np\nprint('Hello, EduMatrix!')")

function extractCodeFromMarkdown(mdText) {
  if (!mdText) return ''
  const regex = /```(?:python|javascript|js|py)?\s*\n([\s\S]*?)```/gi
  const codes = []
  let match
  while ((match = regex.exec(mdText)) !== null) {
    codes.push(match[1].trim())
  }
  if (codes.length > 0) {
    return codes.join('\n\n')
  }
  return mdText.trim()
}

function mountToSandbox(rawContent) {
  const code = extractCodeFromMarkdown(rawContent)
  sandboxInitialCode.value = code
  rightPanelActiveTab.value = 'sandbox'
  rightPanelCollapsed.value = false
}

// 任务 8.5: 视频渲染面板状态
const showVideoPanel = ref(false)
const currentVideoKp = ref('')
function toggleVideoPanel() {
  showVideoPanel.value = !showVideoPanel.value
  if (showVideoPanel.value) {
    // 从最近的消息中提取当前知识点
    const msgs = messages.value
    for (let i = msgs.length - 1; i >= 0; i--) {
      const m = msgs[i]
      if (m.role === 'assistant' && m.target) {
        currentVideoKp.value = m.target
        return
      }
    }
    currentVideoKp.value = ''
  }
}

// 本地动画播放器状态
const showLocalVideo = ref(false)
const localVideos = ref([])
const localVideoKnowledgePoint = ref('')
const localVideosLoading = ref(false)
const localVideoAttached = ref(new Set()) // 已附加动画按钮的消息索引
const inlineVideoIndex = ref(-1) // 内嵌视频播放的资源索引

async function loadLocalAnimations(knowledgePoint) {
  localVideosLoading.value = true
  localVideoKnowledgePoint.value = knowledgePoint
  try {
    const data = await getLocalAnimations(knowledgePoint)
    localVideos.value = data.videos || []
    if (localVideos.value.length > 0) {
      showLocalVideo.value = true
    }
  } catch (e) {
    console.error('加载本地动画失败:', e)
    localVideos.value = []
  } finally {
    localVideosLoading.value = false
  }
}

function openLocalVideo(knowledgePoint) {
  localVideoKnowledgePoint.value = knowledgePoint
  loadLocalAnimations(knowledgePoint)
}

// --- Quiz State (Pinia Integrated) ---
const quizState = computed(() => quizStore.quizState)
const quizData = computed(() => quizStore.quizData)
const quizAnswer = computed({
  get: () => quizStore.quizAnswer,
  set: (val) => { quizStore.quizAnswer = val }
})
const quizConfidence = computed({
  get: () => quizStore.quizConfidence,
  set: (val) => { quizStore.setConfidence(val) }
})
const quizResult = computed(() => quizStore.quizResult)
const quizAttempt = computed(() => quizStore.quizAttempt)
const quizConcept = computed({
  get: () => quizStore.quizConcept,
  set: (val) => { quizStore.quizConcept = val }
})

// 物理抖动 + 彩带粒子触发
const shakeCard = ref(false)
const showConfetti = ref(false)
const confettiParticles = ref<Array<{ x: number; color: string; delay: number; size: number }>>([])

const CONFETTI_COLORS = ['#f43f5e', '#f97316', '#fbbf24', '#22c55e', '#3b82f6', '#8b5cf6', '#ec4899']

function spawnConfetti() {
  const particles = []
  for (let i = 0; i < 40; i++) {
    particles.push({
      x: 10 + Math.random() * 80,
      color: CONFETTI_COLORS[i % CONFETTI_COLORS.length],
      delay: Math.random() * 0.5,
      size: 4 + Math.random() * 8,
    })
  }
  confettiParticles.value = particles
  showConfetti.value = true
  setTimeout(() => {
    showConfetti.value = false
    confettiParticles.value = []
  }, 2000)
}

watch(quizResult, (val) => {
  if (!val) return
  const score = val.accuracy_score ?? 0
  if (score >= 0.7) {
    spawnConfetti()
  } else {
    shakeCard.value = true
    setTimeout(() => { shakeCard.value = false }, 700)
  }
})
const quizSessionId = computed(() => quizStore.quizSessionId)

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
const searchCategory = ref('all')
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
    /!\[可视化输出\]\s*\(data:image\/png;base64,([^)]+)\)/gi,
    (_, b64) => {
      const cleanB64 = b64.replace(/\s+/g, '')
      return `<img src="data:image/png;base64,${cleanB64}" style="max-width:100%;border-radius:8px;margin:8px 0" />`
    }
  )
})

// --- Image QA / Lightbox State ---
const uploadedImages = ref([])
const lightboxImage = ref(null)

function handleImageUpload(e) {
  const file = e.target.files[0]
  if (!file) return
  const reader = new FileReader()
  reader.onload = (event) => {
    uploadedImages.value.push(event.target.result)
  }
  reader.readAsDataURL(file)
  e.target.value = ''
}

function removeUploadedImage(idx) {
  uploadedImages.value.splice(idx, 1)
}

function openImageModal(img) {
  lightboxImage.value = img
}

function getMatchedSlides(msg) {
  if (!msg.resources) return []
  return msg.resources.filter(r => r.type === 'slide_reference')
}

function getRegularResources(msg) {
  if (!msg.resources) return []
  return msg.resources.filter(r => r.type !== 'slide_reference')
}

function getSlideName(content) {
  if (!content) return '课件切片'
  const parts = content.split('/')
  const filename = parts[parts.length - 1]
  if (filename === 'pooling_2x2.png') return '2x2 最大池化矩阵'
  if (filename === 'avg_pooling.png') return '平均池化对照'
  if (filename === 'conv_stride.png') return '卷积核步长滑动'
  if (filename === 'backprop_math.png') return '反向传播链式法则'
  if (filename === 'ml_pipeline.png') return '机器学习流程图'
  if (filename === 'overfit_curve.png') return '过拟合欠拟合曲线'
  if (filename === 'confusion_matrix.png') return '混淆矩阵指标'
  return filename
}

function getCleanUserQuery(idx) {
  if (idx > 0 && messages.value[idx - 1]?.role === 'user') {
    const rawContent = messages.value[idx - 1].content
    const parsed = parseQuoteFromMessage(rawContent)
    return parsed.remaining.trim()
  }
  return null
}

async function triggerMatrixGeneration(concept, idx) {
  if (!concept || sending.value) return
  activeTab.value = 'chat'
  
  // 智能继承上下文：提取上一轮用户提问的真实意图，防止资源与用户提问意图错位
  let queryText = concept
  if (idx !== undefined && idx > 0) {
    const originalQuery = getCleanUserQuery(idx)
    if (originalQuery && originalQuery !== concept) {
      queryText = `一键生成资源包: ${originalQuery} (知识点: ${concept})`
    }
  }
  
  try {
    await chatStore.sendChatMessage(queryText, props.studentId, 'matrix', [], selectedDocIds.value)
  } catch (e) {
    console.error('Swarm generation failed:', e)
  }
}

// ======================== CHAT ========================

function triggerPeerPK(targetConcept = '') {
  if (targetConcept && typeof targetConcept === 'string') {
    input.value = "找学伴PK " + targetConcept
  } else {
    input.value = "找学伴PK"
  }
  send()
}

async function send() {
  const text = input.value.trim()
  const imgs = [...uploadedImages.value]
  if ((!text && imgs.length === 0) || sending.value) return
  
  let finalMsg = text
  if (quotedContent.value) {
    finalMsg = `[引用: ${quotedContent.value.source}] "${quotedContent.value.text}"\n\n我的追问: ${text}`
    quotedContent.value = null
  }

  input.value = ''
  uploadedImages.value = []
  
  // 斜杠命令
  if (text.startsWith('/quiz ')) {
    quizConcept.value = text.slice(6).trim()
    activeTab.value = 'quiz'
    await nextTick()
    startQuiz()
    return
  }
  if (text.startsWith('/search ')) {
    searchQuery.value = text.slice(8).trim()
    activeTab.value = 'websearch'
    await nextTick()
    doWebSearch()
    return
  }
  if (text.startsWith('/code')) {
    activeTab.value = 'code'
    return
  }
  if (text.startsWith('/matrix ')) {
    const concept = text.slice(8).trim()
    activeTab.value = 'chat'
    await nextTick()
    try {
      await chatStore.sendChatMessage(concept, props.studentId, 'matrix', [], selectedDocIds.value)
    } catch (e) {
      console.error('Matrix generation failed:', e)
    }
    return
  }
  
  await nextTick()
  try {
    await chatStore.sendChatMessage(finalMsg || '分析以下题目截图：', props.studentId, 'chat', imgs, selectedDocIds.value)
  } catch (e) {
    console.error('Streaming failed:', e)
  }
}

async function askSuggestedQuestion(q) {
  if (sending.value) return
  try {
    const studentId = props.studentId || 'default'
    await chatStore.sendChatMessage(q, studentId, 'chat', [], selectedDocIds.value)
  } catch (e) {
    console.error('Sending suggested question failed:', e)
  }
}

function toggleResource(msgIdx, resIdx) {
  const key = `${msgIdx}-${resIdx}`
  const s = new Set(showResources.value)
  s.has(key) ? s.delete(key) : s.add(key)
  showResources.value = s
}

function usePreset(text) { input.value = text; send() }
function handleKeydown(e) {
  if (showSuggest.value && filteredSuggestions.value.length > 0) {
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      suggestIndex.value = (suggestIndex.value + 1) % filteredSuggestions.value.length;
      return;
    }
    if (e.key === 'ArrowUp') {
      e.preventDefault();
      suggestIndex.value = (suggestIndex.value - 1 + filteredSuggestions.value.length) % filteredSuggestions.value.length;
      return;
    }
    if (e.key === 'Enter') {
      e.preventDefault();
      selectSuggestion(filteredSuggestions.value[suggestIndex.value]);
      return;
    }
    if (e.key === 'Escape') {
      e.preventDefault();
      showSuggest.value = false;
      return;
    }
  }
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    send();
  }
}

// ======================== QUIZ ========================

async function startQuiz() {
  await quizStore.startQuizAction(props.studentId, quizConcept.value)
}

async function submitQuizAnswer() {
  await quizStore.submitQuizAnswerAction(props.studentId)
  // 答完题后，立刻从数据库拉取最新的学情画像，以触发掌握度雷达图实时更新！
  try {
    const profile = await getStudentProfile(props.studentId)
    latestProfile.value = profile
  } catch (e) {
    console.error('更新最新学生画像失败:', e)
  }
}

async function continueQuiz() {
  await quizStore.continueQuizAction(props.studentId)
}

function resetQuiz() {
  quizStore.resetQuiz()
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

function openSocraticPopup(targetText, contextBefore = '', contextAfter = '', lineIndex = 0, messageIndex = -1) {
  const anchorX = textSelection.value.visible ? textSelection.value.x : null
  const anchorY = textSelection.value.visible ? textSelection.value.y : null
  socraticPopup.value = {
    visible: true,
    targetText: targetText ? targetText.slice(0, 30000) : '',
    contextBefore: contextBefore ? contextBefore.slice(0, 10000) : '',
    contextAfter: contextAfter ? contextAfter.slice(0, 10000) : '',
    lineIndex,
    messageIndex,
    anchorX,
    anchorY,
  }
  textSelection.value.visible = false
}

function setQuote(text, source) {
  quotedContent.value = {
    text: text,
    source: source
  }
  textSelection.value.visible = false
  nextTick(() => {
    const el = document.querySelector('textarea')
    if (el) el.focus()
  })
}

function parseQuoteFromMessage(content) {
  if (!content) return { hasQuote: false, source: '', text: '', remaining: '' }
  const match = content.match(/^\[引用:\s*([^\]]+)\]\s*"([\s\S]*?)"\n\n([\s\S]*)$/)
  if (match) {
    return {
      hasQuote: true,
      source: match[1],
      text: match[2],
      remaining: match[3]
    }
  }
  return { hasQuote: false, source: '', text: '', remaining: content }
}

function handleGlobalMouseUp(e) {
  if (e && e.target && e.target.closest('.selection-capsule')) {
    return
  }
  setTimeout(() => {
    if (isDragging.value) return
    const selection = window.getSelection()
    const text = selection.toString().trim()
    if (text.length > 2) {
      try {
        const range = selection.getRangeAt(0)
        const rect = range.getBoundingClientRect()
        textSelection.value = {
          visible: true,
          x: rect.left + rect.width / 2,
          y: rect.top - 38,
          text: text
        }
      } catch (err) {
        textSelection.value.visible = false
      }
    } else {
      textSelection.value.visible = false
    }
  }, 10)
}

function handleGlobalMouseDown(e) {
  if (e && e.target && e.target.closest('.selection-capsule')) {
    return
  }
  textSelection.value.visible = false
}

function startDrag(e) {
  if (!textSelection.value.visible) return
  isDragging.value = true
  dragOffset.x = e.clientX - textSelection.value.x
  dragOffset.y = e.clientY - textSelection.value.y
  document.addEventListener('mousemove', onDrag)
  document.addEventListener('mouseup', stopDrag)
}

function onDrag(e) {
  if (!isDragging.value) return
  textSelection.value.x = e.clientX - dragOffset.x
  textSelection.value.y = e.clientY - dragOffset.y
}

function stopDrag() {
  isDragging.value = false
  document.removeEventListener('mousemove', onDrag)
  document.removeEventListener('mouseup', stopDrag)
}

/**
 * 处理 Markdown 渲染后的代码块/公式点击
 * 在 Chat 组件挂载后需绑定点击事件到渲染内容
 */
onMounted(async () => {
  document.addEventListener('mouseup', handleGlobalMouseUp)
  document.addEventListener('mousedown', handleGlobalMouseDown)
  // 委托监听：捕获 Markdown 卡片内的代码块和公式点击
  document.addEventListener('click', handleMarkdownClick)

  window.mountCodeToSandbox = (btn) => {
    const parent = btn.closest('.relative')
    const pre = parent ? parent.querySelector('pre') : null
    if (pre) {
      const rawCode = pre.textContent || ''
      mountToSandbox(rawCode)
    }
  }

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

  // 检查是否有从仪表盘等其他页面挂载的代码
  const mountedCode = localStorage.getItem('edumatrix_sandbox_mount_code')
  if (mountedCode) {
    localStorage.removeItem('edumatrix_sandbox_mount_code')
    mountToSandbox(mountedCode)
  }

  // 时空回溯与跳转触发
  if (route.query.quiz) {
    activeTab.value = 'quiz'
    quizConcept.value = route.query.quiz
    startQuiz()
  } else if (route.query.prompt) {
    input.value = route.query.prompt
    send()
  }
})

onUnmounted(() => {
  document.removeEventListener('mouseup', handleGlobalMouseUp)
  document.removeEventListener('mousedown', handleGlobalMouseDown)
  document.removeEventListener('click', handleMarkdownClick)
  window.startInteractiveQuiz = null
  window.startInteractiveVideo = null
  window.mountCodeToSandbox = null
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
  if (name.includes('video') || name.includes('recommender') || name.includes('视频') || name.includes('推荐官') || name.includes('director')) {
    return { label: '视频推荐官', color: 'text-emerald-600 bg-emerald-50 border-emerald-100', icon: 'Film' }
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
    Film,
    Bot
  }
  return mapping[iconName] || Bot
}

function safeParseJson(str, fallback = []) {
  if (!str) return fallback
  let cleaned = str.trim()
  
  // 1. 自动剥离 Markdown json 代码块包裹（如 ```json ... ``` 或 ``` ... ```）
  if (cleaned.startsWith('```')) {
    cleaned = cleaned.replace(/^```[a-zA-Z]*\s*/, '').replace(/\s*```$/, '').trim()
  }
  
  // 2. 智能截取首个 '[' 到最后一个 ']' 之间的 JSON 数组内容
  const startIdx = cleaned.indexOf('[')
  const endIdx = cleaned.lastIndexOf(']')
  if (startIdx !== -1 && endIdx !== -1 && endIdx > startIdx) {
    cleaned = cleaned.substring(startIdx, endIdx + 1)
  }
  
  try {
    return JSON.parse(cleaned)
  } catch (e) {
    console.error("JSON parse failed in Chat.vue, attempting fuzzy recovery:", e, str)
    try {
      // 3. 容错净化：修复常见的小尾巴逗号或未闭合转义符
      const fixed = cleaned
        .replace(/,\s*]/g, ']')
        .replace(/,\s*}/g, '}')
      return JSON.parse(fixed)
    } catch (e2) {
      console.error("Fuzzy JSON recovery failed:", e2)
      return fallback
    }
  }
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
      chatStore.saveMessages()
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
  codeInput.value = extractCodeFromMarkdown(content)
  activeTab.value = 'code'
  codeOutput.value = ''
  codeError.value = ''
  nextTick(() => runUserCode())
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
  codeInput.value = extractCodeFromMarkdown(content)
  activeTab.value = 'code'
  codeOutput.value = ''
  codeError.value = ''
  conceptCodePopup.value = null
  nextTick(() => runUserCode())
}

async function openSaveNoteModal(msgIdx) {
  const msg = chatStore.messages[msgIdx]
  if (!msg) return
  showNoteModal.value = true
  noteModalLoading.value = true
  noteModalForm.value = {
    content: '正在调用 AI 智能提炼这堂课的精要笔记大纲与数学推导公式...',
    tags: '',
    concepts: msg.target || '',
    source: '对话同步'
  }
  try {
    // 结合主回复内容以及所有子智能体生成的讲义与资源，传给后端提炼
    let fullContext = msg.content || ''
    if (msg.resources && msg.resources.length > 0) {
      fullContext += '\n\n### 关联教学资源及讲义详情：\n'
      msg.resources.forEach((r) => {
        fullContext += `\n#### 【${r.resource_type || r.type || r.agent}】\n${r.content}\n`
      })
    }
    const data = await aiPolishNote({ content: fullContext })
    if (data && data.polished_content) {
      noteModalForm.value.content = data.polished_content
      noteModalForm.value.tags = (data.tags || []).join(', ')
      noteModalForm.value.concepts = (data.concepts || []).join(', ') || msg.target || ''
    } else {
      noteModalForm.value.content = fullContext
    }
  } catch (e) {
    console.error('AI 智能提炼失败，降级为原始排版:', e)
    // 降级时也使用合并后的内容，保证内容全面
    let fallbackContext = msg.content || ''
    if (msg.resources && msg.resources.length > 0) {
      fallbackContext += '\n\n### 关联教学资源及讲义详情：\n'
      msg.resources.forEach((r) => {
        fallbackContext += `\n#### 【${r.resource_type || r.type || r.agent}】\n${r.content}\n`
      })
    }
    noteModalForm.value.content = fallbackContext
  } finally {
    noteModalLoading.value = false
  }
}

async function confirmSaveNote() {
  try {
    const tagsArray = noteModalForm.value.tags.split(/[,，]/).map(t => t.trim()).filter(Boolean)
    const conceptsArray = noteModalForm.value.concepts.split(/[,，]/).map(c => c.trim()).filter(Boolean)
    await createNote(props.studentId, {
      content: noteModalForm.value.content,
      source: noteModalForm.value.source,
      tags: tagsArray,
      concepts: conceptsArray
    })
    showNoteModal.value = false
    alert('精要笔记已成功保存到您的笔记本中！')
  } catch (e) {
    alert('保存笔记失败: ' + (e.message || e))
  }
}

async function generateReviewPlan(msgIdx) {
  const msg = chatStore.messages[msgIdx]
  if (!msg || !msg.target) return
  try {
    await createReviewPlan(props.studentId, {
      concept: msg.target,
      priority: 1.0
    })
    alert('艾宾浩斯复习计划已添加')
  } catch (e) {
    console.error('添加复习计划失败:', e)
    alert('添加复习计划失败')
  }
}

async function regenerateMessage(idx) {
  if (chatStore.sending) return
  // Find the corresponding user message
  let userMsg = null
  let userMsgIndex = -1
  for (let i = idx - 1; i >= 0; i--) {
    if (chatStore.messages[i].role === 'user') {
      userMsg = chatStore.messages[i]
      userMsgIndex = i
      break
    }
  }
  if (!userMsg) return

  // Remove all messages after the user message
  chatStore.messages.splice(userMsgIndex + 1)
  chatStore.saveMessages()

  // Resend the user message
  try {
    const studentId = props.studentId || 'default'
    await chatStore.sendChatMessage(userMsg.content, studentId, 'chat', userMsg.images || [], selectedDocIds.value)
  } catch (err) {
    console.error('Regenerate failed:', err)
  }
}

async function regenerateFromUserMsg(idx) {
  if (chatStore.sending) return
  const userMsg = chatStore.messages[idx]
  if (!userMsg || userMsg.role !== 'user') return

  // Remove the user message and all subsequent messages
  chatStore.messages.splice(idx)
  chatStore.saveMessages()

  // Resend
  try {
    const studentId = props.studentId || 'default'
    await chatStore.sendChatMessage(userMsg.content, studentId, 'chat', userMsg.images || [], selectedDocIds.value)
  } catch (err) {
    console.error('Regenerate failed:', err)
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
  return true
})

watch(hasVisualContent, (newVal) => {
  if (newVal) {
    rightPanelActiveTab.value = 'canvas'
    rightPanelCollapsed.value = false
  }
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
  return Object.entries(profile.concept_mastery).map(([name, score]) => {
    const coords = profile.coordinate_map?.[name] || [0.0, 0.0]
    return {
      name,
      mastery: score,
      x: coords[0],
      y: coords[1]
    }
  })
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
  return Object.keys(profile.concept_mastery).map(name => {
    const coords = profile.coordinate_map?.[name] || [0.0, 0.0]
    return {
      name,
      x: coords[0],
      y: coords[1]
    }
  })
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
  // 1. 如果是 Swarm 矩阵生成场景，优先使用消息级别的 RAG 流形对齐距离
  const msgDist = lastAssistantMessage.value?.alignment?.distance
  if (msgDist !== undefined && msgDist !== 0) {
    return msgDist
  }
  // 2. 否则，根据学生当前的 concept_mastery 动态计算平均偏差 (1.0 - 平均掌握度) 作为认知对齐散度
  const profile = latestProfile.value || capturedInitialProfile.value
  if (!profile || !profile.concept_mastery) return 0.45 // 默认中等散度
  const scores = Object.values(profile.concept_mastery)
  if (scores.length === 0) return 0.45
  const avgMastery = scores.reduce((sum, val) => sum + val, 0) / scores.length
  return Math.max(0.0, Math.min(1.0, 1.0 - avgMastery))
})

const conflictDetected = computed(() => {
  const msgPassed = lastAssistantMessage.value?.alignment?.passed
  if (msgPassed !== undefined) {
    return !msgPassed
  }
  // 认知冲突阈值：当散度 KL > 0.45 (即平均掌握度低于 55%) 时触发预警
  return klDivergence.value > 0.45
})

const alignmentProgress = computed(() => {
  const dist = klDivergence.value
  return Math.max(0, Math.min(100, (1 - dist) * 100))
})

// 知识点列表（用于 KnowledgePointsPanel 浮窗）
const conceptList = computed(() => {
  const profile = latestProfile.value || capturedInitialProfile.value
  if (!profile || !profile.concept_mastery) return []
  return Object.entries(profile.concept_mastery).map(([name, mastery]) => ({
    name,
    mastery: Math.min(1, Math.max(0, mastery || 0)),
    count: (profile.discussion_counts || {})[name] || 0,
  }))
})

const discussionThemes = computed(() => {
  const msgs = messages.value
  const lastMsgs = msgs.slice(-4).map(m => m.content || '')
  const themes = []
  for (const msg of lastMsgs) {
    const found = (msg.match(/(机器学习|深度学习|神经网络|线性回归|逻辑回归|SVM|决策树|梯度下降|反向传播|CNN|RNN|Transformer|注意力|池化|卷积|过拟合|正则化|交叉验证|模型评估|数据预处理|特征工程|聚类|降维|PCA)/g) || [])
    themes.push(...found.slice(0, 3))
  }
  return [...new Set(themes)].slice(0, 5)
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
    const data = await webSearch(searchQuery.value, props.studentId, searchCategory.value)
    searchResults.value = data.results || []
    searchSummary.value = data.summary || ''
  } catch (e) {
    searchSummary.value = '搜索失败: ' + (e.message || '未知错误')
  } finally {
    searchLoading.value = false
  }
}

function getDomain(urlStr) {
  if (!urlStr) return ''
  try {
    return new URL(urlStr).hostname.replace('www.', '')
  } catch {
    return urlStr
  }
}

function openUrl(urlStr) {
  if (!urlStr) return
  window.open(urlStr, '_blank')
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
      const regex = new RegExp(`^([^({[\\]\\s]+)\\s*(${escapedOpen})\\s*(.*?)\\s*(${escapedClose})$`)
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
  
  // 自动闭合未闭合的代码块 (```) 与双美元公式块 ($$)，防止内容被截断时导致排版崩溃
  const openTicksCount = (cleaned.match(/```/g) || []).length
  if (openTicksCount % 2 !== 0) {
    cleaned += '\n```'
  }
  const doubleDollarCount = (cleaned.match(/\$\$/g) || []).length
  if (doubleDollarCount % 2 !== 0) {
    cleaned += '\n$$'
  }

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

  const layoutBlocks = []
  function protectLayout(htmlTag) {
    const idx = layoutBlocks.length
    layoutBlocks.push(htmlTag)
    return `@@LAYOUTTOKEN${idx}@@`
  }

  function buildThreeLevelHintLadderHtml(rawContent) {
    if (!rawContent) return ''

    let text = rawContent
      .replace(/<details[\s\S]*?>/gi, '')
      .replace(/<\/details>/gi, '')
      .replace(/<summary>[\s\S]*?<\/summary>/gi, '')
      .replace(/^[#*\s]*💡?\s*提示阶梯[（(]点击展开[）)]?[#*\s]*\n+/gim, '')
      .trim()

    // 匹配 第1层/第2层/第3层 (支持数字与中文一二三, 兼容 **双星号, 冒号在内外等各种LLM输出变体)
    const layer1Match = text.match(/(?:[-*+\s]*)\*?\*?第\s*[1一]\s*层[（(]([^）)]+)[）)]\*?\*?\s*[：:]\s*([\s\S]*?)(?=(?:[-*+\s]*)\*?\*?第\s*[2二]\s*层|$)/i)
    const layer2Match = text.match(/(?:[-*+\s]*)\*?\*?第\s*[2二]\s*层[（(]([^）)]+)[）)]\*?\*?\s*[：:]\s*([\s\S]*?)(?=(?:[-*+\s]*)\*?\*?第\s*[3三]\s*层|$)/i)
    const layer3Match = text.match(/(?:[-*+\s]*)\*?\*?第\s*[3三]\s*层[（(]([^）)]+)[）)]\*?\*?\s*[：:]\s*([\s\S]*?)(?=$)/i)

    const layers = []
    if (layer1Match) layers.push({ num: 1, name: layer1Match[1].trim(), content: layer1Match[2].trim() })
    if (layer2Match) layers.push({ num: 2, name: layer2Match[1].trim(), content: layer2Match[2].trim() })
    if (layer3Match) layers.push({ num: 3, name: layer3Match[1].trim(), content: layer3Match[2].trim() })

    // 如果未成功按 3 层切分，则退化为单卡片输出
    if (layers.length === 0) {
      const cardStart = protectLayout(`<div class="edumatrix-accordion-card border border-slate-200/80 dark:border-slate-800/80 rounded-xl my-3 overflow-hidden shadow-sm bg-slate-50/40 dark:bg-slate-900/40 transition-all duration-300">
  <div onclick="const body=this.nextElementSibling; const icon=this.querySelector('.accordion-icon'); if(body.style.display==='none'||!body.style.display){ body.style.display='block'; if(icon) icon.textContent='▼'; }else{ body.style.display='none'; if(icon) icon.textContent='▶'; }" class="px-4 py-3 font-semibold text-slate-800 dark:text-slate-200 cursor-pointer bg-slate-100/60 dark:bg-slate-800/40 hover:bg-slate-100 dark:hover:bg-slate-800/60 transition-colors flex items-center justify-between select-none text-xs">
    <span class="flex items-center gap-1.5">💡 提示阶梯（点击展开）</span>
    <span class="accordion-icon text-[10px] text-slate-400 font-mono">▶</span>
  </div>
  <div class="accordion-body px-5 py-4 border-t border-slate-100 dark:border-slate-800/60 text-slate-700 dark:text-slate-300 leading-relaxed text-xs" style="display: none;">`)
      const cardEnd = protectLayout(`</div></div>`)
      return `\n\n${cardStart}\n\n${text}\n\n${cardEnd}\n\n`
    }

    const itemsHtml = layers.map(l => {
      const cardStart = protectLayout(`<div class="edumatrix-accordion-card border border-sky-200/80 dark:border-sky-900/50 rounded-xl my-2 overflow-hidden shadow-sm bg-sky-50/20 dark:bg-slate-900/40 transition-all duration-300">
  <div onclick="const body=this.nextElementSibling; const icon=this.querySelector('.accordion-icon'); if(body.style.display==='none'||!body.style.display){ body.style.display='block'; if(icon) icon.textContent='▼'; }else{ body.style.display='none'; if(icon) icon.textContent='▶'; }" class="px-4 py-2.5 font-semibold text-sky-900 dark:text-sky-200 cursor-pointer bg-sky-50/80 dark:bg-sky-950/40 hover:bg-sky-100/80 dark:hover:bg-sky-900/60 transition-colors flex items-center justify-between select-none text-xs">
    <span class="flex items-center gap-1.5">💡 <strong class="text-sky-800 dark:text-sky-300">第 ${l.num} 层提示</strong> · ${l.name}（点击展开）</span>
    <span class="accordion-icon text-[10px] text-sky-600 dark:text-sky-400 font-mono">▶</span>
  </div>
  <div class="accordion-body px-5 py-3.5 border-t border-sky-100 dark:border-sky-900/50 text-slate-700 dark:text-slate-300 leading-relaxed text-xs bg-white/40 dark:bg-slate-900/20" style="display: none;">`)
      const cardEnd = protectLayout(`</div></div>`)
      return `\n\n${cardStart}\n\n${l.content}\n\n${cardEnd}\n\n`
    }).join('\n')

    const wrapperStart = protectLayout(`<div class="edumatrix-hint-ladder-wrapper my-3.5 p-3.5 bg-gradient-to-br from-sky-50/70 via-blue-50/40 to-slate-50/60 dark:from-slate-900/80 dark:via-sky-950/30 dark:to-slate-900/90 rounded-2xl border border-sky-200/80 dark:border-sky-900/50 shadow-sm">
  <div class="text-xs font-bold text-sky-900 dark:text-sky-300 mb-2 flex items-center gap-1.5 px-1">
    <span>🪜</span>
    <span>三层递进提示阶梯（点击各层按需展开查看）：</span>
  </div>`)
    const wrapperEnd = protectLayout(`</div>`)

    return `\n\n${wrapperStart}\n${itemsHtml}\n${wrapperEnd}\n\n`
  }

  // 1. Match <details> blocks from LLM output
  cleaned = cleaned.replace(/(?:^|\n)\s*[-*+]*\s*(?:[#*\s]*提示阶梯[：:]*\s*\n+)?<details[\s\S]*?>([\s\S]*?)<\/details>/gi, (match, bodyContent) => {
    return buildThreeLevelHintLadderHtml(bodyContent)
  })

  // 2. If no <details> tag exists, auto-wrap un-folded "提示阶梯" plain markdown list into 3-level cards
  if (!cleaned.includes('@@LAYOUTTOKEN')) {
    cleaned = cleaned.replace(
      /(?:[#*]*\s*提示阶梯[：:]?\s*[#*]*\s*\n+)?((?:[-*]\s*\*?第[123一二三]层[\s\S]*?)(?=\n\s*\n(?![-\s]*\*?第[123一二三]层)|\n[#*]{1,3}\s+|<div|$))/gi,
      (match, hintsContent) => {
        return buildThreeLevelHintLadderHtml(hintsContent)
      }
    )
  }

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
            <div class="mermaid w-full flex justify-center" data-code="${escapedCode}"><div class="mermaid-loading flex flex-col items-center justify-center gap-1.5 py-6 text-gray-400 select-none"><div class="w-5 h-5 border-2 border-indigo-500 border-t-transparent rounded-full animate-spin"></div><span class="text-[10px] text-indigo-500 font-semibold animate-pulse">正在绘制思维导图...</span></div></div>
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
      const cleanLang = (lang || 'python').trim().toLowerCase()
      blockHtml = `<div class="relative group my-3">
        <pre class="p-3 bg-gray-900 rounded-lg overflow-x-auto text-xs leading-relaxed language-${cleanLang}"><code class="language-${cleanLang}">${code.trim()}</code></pre>
        <button onclick="window.mountCodeToSandbox && window.mountCodeToSandbox(this)" class="absolute top-2 right-2 opacity-0 group-hover:opacity-100 transition-opacity px-2.5 py-1 bg-green-700 hover:bg-green-600 text-white rounded text-[10px] flex items-center gap-1 shadow-sm font-semibold transition-all">
          💻 挂载至沙箱
        </button>
      </div>`
    }
    const idx = codeBlocks.length
    codeBlocks.push(blockHtml)
    return `@@CODEBLOCKTOKEN${idx}@@`
  })

  // Extract single-backtick inline code blocks to protect them from subscript mangling
  html = html.replace(/`([^`\n]+)`/g, (_, code) => {
    const blockHtml = `<code class="px-1.5 py-0.5 bg-gray-100 text-red-600 rounded font-mono text-xs font-medium">${code}</code>`
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
  html = html.replace(/!\[([^\]]*)\]\s*\(([^)]+)\)/g, (match, alt, url) => {
    const cleanUrl = url.replace(/\s+/g, '')
    return `<img src="${cleanUrl}" alt="${alt}" class="max-w-full max-h-[300px] object-contain rounded-xl my-3 shadow-sm border border-gray-100 bg-white p-1" />`
  })
  html = html.replace(/\*\*([^*]+)\*\*/g, '<strong class="font-bold text-gray-900">$1</strong>')
  html = html.replace(/\*([^*]+)\*/g, '<em class="italic text-gray-800">$1</em>')
  // Inline code is already extracted and protected as @@CODEBLOCKTOKEN@@ above
  html = html.replace(/^### (.*$)/gim, '<h4 class="text-xs font-bold text-gray-800 mt-4 mb-1.5 flex items-center gap-1">$1</h4>')
  html = html.replace(/^## (.*$)/gim, '<h3 class="text-sm font-semibold text-gray-900 mt-5 mb-2 border-b border-gray-100 pb-1 flex items-center gap-1.5">$1</h3>')
  html = html.replace(/^# (.*$)/gim, '<h2 class="text-base font-bold text-gray-900 mt-6 mb-3 flex items-center gap-2">$1</h2>')

  // Paragraph spacing
  html = html.replace(/\n\n/g, '<div class="h-2.5"></div>')

  // Helper to render math
  function renderMath(math, display) {
    const cleanMathContent = math
      .replace(/&amp;/g, '&')
      .replace(/&lt;/g, '<')
      .replace(/&gt;/g, '>')
      .replace(/&quot;/g, '"')
      .replace(/&#39;/g, "'")

    if (window.katex) {
      try {
        return window.katex.renderToString(cleanMathContent, {
          displayMode: display,
          throwOnError: false,
          trust: true
        })
      } catch (err) {
        console.error('KaTeX rendering error:', err)
      }
    }
    // Fallback: raw but clean formatting with math symbols
    const cleanMath = cleanMathContent
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

  // 5. Restore layout blocks, math, code, and SVG blocks
  layoutBlocks.forEach((block, idx) => {
    html = html.split(`@@LAYOUTTOKEN${idx}@@`).join(block)
  })

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
  <div class="chat-workspace flex gap-5 h-full soft-reveal">
    <!-- Left panel: NotebookLM-style Checked Sources -->
    <div
      v-if="activeTab === 'chat'"
      class="chat-source-panel shrink-0 border border-gray-100 rounded-2xl bg-white shadow-sm flex flex-col p-4 transition-all duration-300"
      :class="leftPanelCollapsed ? 'w-0 border-r-0 overflow-hidden px-0 py-0 opacity-0' : 'w-[260px] opacity-100'"
    >
      <div class="flex items-center justify-between mb-4 border-b border-gray-100 pb-2 shrink-0">
        <span class="text-xs font-bold text-gray-700 flex items-center gap-1.5">
          <BookOpen :size="14" class="text-blue-500" /> 知识库源 ({{ selectedDocIds.length }}/{{ docs.length }})
        </span>
        <button @click="leftPanelCollapsed = true" class="text-gray-400 hover:text-gray-600 hover:bg-gray-50 p-1 rounded-lg transition-colors">
          <Minimize2 :size="12" />
        </button>
      </div>

      <div class="flex-1 overflow-y-auto space-y-2 mb-3 min-h-0 scrollbar-thin">
        <!-- Select All checkbox -->
        <label v-if="docs.length > 0" class="flex items-center gap-2 p-2 hover:bg-gray-50 rounded-xl cursor-pointer text-xs font-semibold text-gray-600 border border-transparent select-none">
          <input type="checkbox" v-model="isAllSelected" class="rounded text-blue-500 cursor-pointer" />
          全选 (Select All)
        </label>
        
        <div v-if="docs.length === 0" class="h-full flex flex-col items-center justify-center text-center p-4">
          <BookOpen :size="24" class="text-gray-300 mb-2" />
          <p class="text-[11px] text-gray-400">知识库为空</p>
        </div>

        <div v-for="doc in docs" :key="doc.id" class="flex items-center gap-2 p-2 hover:bg-gray-50 rounded-xl border border-transparent text-xs select-none group" :class="{ 'bg-blue-50/40 border-blue-100/50': selectedDocIds.includes(doc.id) }">
          <input type="checkbox" :value="doc.id" v-model="selectedDocIds" class="rounded text-blue-500 cursor-pointer shrink-0" />
          <div class="flex items-center gap-1.5 min-w-0 flex-1 cursor-pointer" @click="openDocViewer(doc)">
            <component :is="getFileIcon(doc.filename, doc.file_type)" :size="12" class="shrink-0" :class="getFileColorClass(doc.filename, doc.file_type)" />
            <span class="truncate text-gray-700 font-medium hover:text-blue-600 hover:underline flex-1" :title="doc.filename">{{ doc.filename }}</span>
            <ExternalLink :size="10" class="text-gray-300 opacity-0 group-hover:opacity-100 shrink-0 transition-opacity" />
          </div>
        </div>
      </div>
      
      <!-- Upload / Add Website Shortcut buttons -->
      <div class="border-t border-gray-100 pt-3 flex flex-col gap-2 shrink-0">
        <router-link to="/knowledge" class="w-full py-2 text-xs font-semibold text-blue-600 bg-blue-50 hover:bg-blue-100 rounded-xl transition-all flex items-center justify-center gap-1 select-none">
          <Upload :size="12" /> 管理知识库
        </router-link>
      </div>
    </div>

    <!-- Main content area -->
    <div class="chat-main-column flex-1 flex flex-col min-w-0 overflow-hidden">
      <!-- Premium Tabs -->
      <div class="chat-toolbar flex items-center justify-between mb-5 border-b border-gray-100 pb-3 gap-3">
        <div class="flex gap-1 bg-white/80 backdrop-blur-sm rounded-2xl p-1.5 shadow-sm border border-slate-200/80">
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
        <div class="flex items-center gap-2">
          <button v-if="activeTab === 'chat' && leftPanelCollapsed"
            @click="leftPanelCollapsed = false"
            class="px-2.5 py-1 text-xs font-semibold text-indigo-600 hover:text-indigo-700 hover:bg-indigo-100 bg-indigo-50 rounded-lg flex items-center gap-1 transition-all border border-indigo-200">
            <BookOpen :size="12" /> 展开源文件列表
          </button>
          <button v-if="activeTab === 'chat' && messages.length > 0"
            @click="clearChat"
            class="px-2.5 py-1 text-xs font-semibold text-red-600 hover:text-red-700 hover:bg-red-100 bg-red-50 rounded-lg flex items-center gap-1 transition-all border border-red-200">
            <Trash2 :size="12" /> 清空对话
          </button>
          <button v-if="activeTab === 'chat' && rightPanelCollapsed"
            @click="rightPanelCollapsed = false"
            class="px-2.5 py-1 text-xs font-semibold text-blue-600 hover:text-blue-700 hover:bg-blue-100 bg-blue-50 rounded-lg flex items-center gap-1 transition-all border border-blue-200">
            <Maximize2 :size="12" /> 展开可视化画板
          </button>
        </div>
      </div>

      <!-- CHAT TAB -->
      <div v-if="activeTab === 'chat'" class="chat-reading-column relative flex flex-col flex-1 min-h-0 max-w-[880px] mb-6">
        <div class="flex flex-wrap gap-2 mb-4">
          <button v-for="preset in presets" :key="preset" class="btn btn-outline text-xs py-1.5" @click="usePreset(preset)">
            {{ preset.slice(0, 20) }}{{ preset.length > 20 ? '...' : '' }}
          </button>
        </div>

        <div ref="messageListRef" class="flex-1 overflow-y-auto space-y-4 mb-4 scrollbar-thin">
          <div v-if="messages.length === 0" class="flex flex-col items-center justify-center h-full text-center text-gray-400">
            <Bot :size="48" class="mb-3 text-gray-300" />
            <p class="text-sm font-medium">输入问题开始学习</p>
            <p class="text-xs mt-1">EduMatrix 将调用多个智能体为你生成完整教学资源</p>
          </div>

          <div v-for="(msg, idx) in messages" :key="idx">
            <div v-if="msg.role === 'user'" class="flex justify-end items-center gap-2 mb-3">
              <!-- 重新提问按钮 (顺时针旋转小箭头) -->
              <button 
                class="w-7 h-7 rounded-lg border border-gray-200/60 bg-white hover:bg-purple-50 text-gray-400 hover:text-purple-600 shadow-sm hover:shadow active:scale-95 transition-all flex items-center justify-center cursor-pointer shrink-0"
                title="重新问一遍问题" 
                :disabled="sending"
                @click="regenerateFromUserMsg(idx)"
              >
                <RotateCw :size="12" />
              </button>

              <!-- 用户消息气泡：圆角矩形，加深蓝色精致边框，大行距，优雅字体 -->
              <div class="max-w-[75%] chat-card-user text-blue-600 shadow-sm flex flex-col gap-2">
                <template v-if="parseQuoteFromMessage(msg.content).hasQuote">
                  <div class="border-l-2 border-blue-500 pl-2.5 py-1 mb-1 bg-slate-50/50 dark:bg-slate-900/40 rounded text-[11px] text-slate-550 dark:text-slate-400 font-mono italic max-h-[80px] overflow-y-auto break-all text-left">
                    <span class="font-bold text-[9px] text-blue-600 dark:text-blue-450 block not-italic uppercase tracking-wider mb-0.5">引用 · {{ parseQuoteFromMessage(msg.content).source }}</span>
                    "{{ parseQuoteFromMessage(msg.content).text }}"
                  </div>
                  <p class="text-sm whitespace-pre-wrap leading-relaxed text-left">{{ parseQuoteFromMessage(msg.content).remaining }}</p>
                </template>
                <template v-else>
                  <p class="text-sm whitespace-pre-wrap leading-relaxed text-left">{{ msg.content }}</p>
                </template>
                <div v-if="msg.images && msg.images.length > 0" class="flex gap-2 flex-wrap mt-1">
                  <div v-for="(img, imgIdx) in msg.images" :key="imgIdx" class="w-24 h-24 rounded-lg overflow-hidden border border-blue-200 shadow-sm bg-white shrink-0">
                    <img :src="img" class="w-full h-full object-cover cursor-pointer" @click="openImageModal(img)" />
                  </div>
                </div>
              </div>
            </div>

            <!-- 任务 8.1: data-msg-index 用于行级点击定位 -->
            <div v-else-if="msg.content || (msg.resources && msg.resources.length > 0)"
                 class="mb-4 chat-message"
                 :data-msg-index="idx"
                 @mouseenter="startHover(idx, msg.target)"
                 @mouseleave="endHover(idx, msg.target)">
              <div class="flex items-start gap-3">
                <div class="w-8 h-8 rounded-xl bg-gradient-to-br from-blue-500 to-purple-600 flex items-center justify-center shrink-0">
                  <Bot :size="16" class="text-white" />
                </div>
                <div class="flex-1 min-w-0">
                  <div class="card chat-card-assistant">
                    <!-- 任务 8.3: 讲义操作栏 -->
                    <div class="flex items-center justify-end gap-1 mb-1 pb-1 border-b border-gray-100">
                      <button @click="triggerPeerPK(msg.target)" class="text-[10px] text-orange-600 hover:text-orange-700 hover:bg-orange-50 flex items-center gap-0.5 px-1.5 py-0.5 rounded transition-colors font-medium border border-orange-200/30"
                        title="针对当前概念进行学伴对战" :disabled="sending">
                        <Users :size="10" /> 👥 找同伴 PK
                      </button>
                      <button @click="openSaveNoteModal(idx)" class="text-[10px] text-gray-400 hover:text-amber-600 flex items-center gap-0.5 px-1.5 py-0.5 hover:bg-amber-50 rounded transition-colors"
                        title="保存到知识笔记">
                        <BookOpen :size="10" /> 笔记
                      </button>
                      <button @click="generateReviewPlan(idx)" class="text-[10px] text-gray-400 hover:text-blue-600 flex items-center gap-0.5 px-1.5 py-0.5 hover:bg-blue-50 rounded transition-colors"
                        title="生成复习计划">
                        <Calendar :size="10" /> 复习
                      </button>
                      <button @click="exportAsMarkdown(idx)" class="text-[10px] text-gray-400 hover:text-blue-600 flex items-center gap-0.5 px-1.5 py-0.5 hover:bg-blue-50 rounded transition-colors"
                        title="导出为 Markdown">
                        <Download :size="10" /> 导出
                      </button>
                      <button @click="regenerateMessage(idx)" class="text-[10px] text-gray-400 hover:text-purple-600 flex items-center gap-0.5 px-1.5 py-0.5 hover:bg-purple-50 rounded transition-colors"
                        title="重新回答" :disabled="sending">
                        <RotateCcw :size="10" /> 重新回答
                      </button>
                      <span class="text-[9px] text-gray-300">💡 点击代码块/公式可即时答疑</span>
                    </div>
                    <!-- Inline Agent Traces Panel -->
                    <div class="mb-3">
                      <!-- Live Progress Traces (When streaming) -->
                      <div v-if="idx === messages.length - 1 && chatStore.sending" class="flex flex-wrap gap-1.5 p-2 bg-gray-50 border border-gray-150 rounded-xl">
                        <span class="text-[9px] text-gray-400 font-mono w-full mb-1 flex items-center gap-1">
                          <Loader2 :size="8" class="animate-spin text-indigo-500" /> Swarm 协同执行轨迹:
                        </span>
                        <!-- Coord -->
                        <span class="px-2 py-0.5 rounded text-[10px] font-mono flex items-center gap-1 border"
                              :class="chatStore.streamingProgress >= 10 ? 'bg-green-50 text-green-600 border-green-200/60 font-medium' : 'bg-white text-gray-400 border-gray-200/80'">
                          🎯 主控官
                        </span>
                        <!-- Diag -->
                        <span class="px-2 py-0.5 rounded text-[10px] font-mono flex items-center gap-1 border"
                              :class="chatStore.streamingProgress >= 25 ? 'bg-green-50 text-green-600 border-green-200/60 font-medium' : 'bg-white text-gray-400 border-gray-200/80'">
                          🔍 诊断官
                        </span>
                        <!-- Planner -->
                        <span class="px-2 py-0.5 rounded text-[10px] font-mono flex items-center gap-1 border"
                              :class="chatStore.streamingProgress >= 40 ? 'bg-green-50 text-green-600 border-green-200/60 font-medium' : 'bg-white text-gray-400 border-gray-200/80'">
                          🗺️ 规划官
                        </span>
                        <!-- Parallel Agent Factory (理論, 邏輯, 極客, 考官, 導演) -->
                        <template v-for="agent in ['理论教授', '逻辑画师', '极客助教', '考官智能体', '虚拟导演']">
                          <span v-if="chatStore.streamingAgents[agent]" :key="agent" 
                                class="px-2 py-0.5 rounded text-[10px] font-mono flex items-center gap-1 border"
                                :class="chatStore.streamingAgents[agent]?.done ? 'bg-green-50 text-green-600 border-green-200/60 font-medium' : 'bg-blue-50 text-blue-600 border-blue-200/60 animate-pulse font-medium'">
                            <span v-if="agent === '理论教授'">📚 理论教授</span>
                            <span v-else-if="agent === '逻辑画师'">🎨 逻辑画师</span>
                            <span v-else-if="agent === '极客助教'">💻 极客助教</span>
                            <span v-else-if="agent === '考官智能体'">📝 考官智能体</span>
                            <span v-else-if="agent === '虚拟导演'">🎬 虚拟导演</span>
                          </span>
                        </template>
                      </div>

                      <!-- Completed Static Traces (When finished) -->
                      <div v-else-if="msg.resources && msg.resources.length > 0" class="flex flex-wrap gap-1.5 p-2 bg-gray-50 border border-gray-150 rounded-xl">
                        <span class="text-[9px] text-gray-400 font-mono w-full mb-1">
                          🛠️ 本轮调用工具与智能体 (共 {{ msg.resources.length }} 个):
                        </span>
                        <div v-for="res in msg.resources" :key="res.agent" 
                             class="relative group px-2 py-0.5 rounded-lg text-[10px] font-medium bg-white border border-gray-200/80 text-gray-600 shadow-sm flex items-center gap-1 hover:border-indigo-400 hover:text-indigo-600 transition-all cursor-help">
                          <span v-if="res.agent === '理论教授'">📚 理论教授 ({{ res.type }})</span>
                          <span v-else-if="res.agent === '逻辑画师'">🎨 逻辑画师 ({{ res.type }})</span>
                          <span v-else-if="res.agent === '极客助教'">💻 极客助教 ({{ res.type }})</span>
                          <span v-else-if="res.agent === '考官智能体'">📝 考官智能体 ({{ res.type }})</span>
                          <span v-else-if="res.agent === '虚拟导演'">🎬 虚拟导演 ({{ res.type }})</span>
                          <span v-else>🤖 {{ res.agent }} ({{ res.type }})</span>

                          <!-- Custom Tooltip -->
                          <div class="absolute bottom-full left-1/2 transform -translate-x-1/2 mb-2 hidden group-hover:block w-80 p-3 bg-gray-950 text-gray-200 rounded-xl border border-gray-800 shadow-2xl z-50 pointer-events-none transition-all duration-200">
                            <div class="font-bold text-indigo-400 mb-1 flex items-center gap-1">
                              <span>{{ res.agent }}</span>
                              <span class="text-[8px] px-1 py-0.1 bg-indigo-950 text-indigo-300 rounded border border-indigo-900/50">{{ res.type }}</span>
                            </div>
                            <div class="text-gray-300 font-sans leading-relaxed whitespace-pre-line text-left text-[10px]"
                                 style="display: -webkit-box; -webkit-line-clamp: 6; -webkit-box-orient: vertical; overflow: hidden;">
                              {{ res.content.slice(0, 300) + (res.content.length > 300 ? '...' : '') }}
                            </div>
                            <div class="absolute top-full left-1/2 transform -translate-x-1/2 border-4 border-transparent border-t-gray-950"></div>
                          </div>
                        </div>
                      </div>
                    </div>

                    <!-- 增量渲染：流式消息用 IncrementalMarkdownRenderer，完成消息用 renderMarkdown -->
                    <IncrementalMarkdownRenderer v-if="idx === messages.length - 1 && chatStore.sending && streamingContent" :text="streamingContent" class="prose prose-sm max-w-none text-sm" />
                    <div v-else class="prose prose-sm max-w-none text-sm" v-html="renderMarkdown(msg.content)"></div>
                    <!-- 打字光标 -->
                    <span v-if="idx === messages.length - 1 && chatStore.sending && chatStore.streamingMode !== 'matrix'"
                      class="inline-block w-[2px] h-4 bg-blue-500 animate-pulse ml-0.5 align-text-bottom" />

                    <!-- Suggested Questions (NotebookLM style) -->
                    <div v-if="msg.suggested_questions && msg.suggested_questions.length > 0 && !msg.streaming" class="mt-4 pt-3 border-t border-slate-100 dark:border-slate-850 flex flex-col gap-2 text-left">
                      <p class="text-[10px] font-semibold text-slate-400 dark:text-slate-500 uppercase tracking-wider flex items-center gap-1.5 select-none">
                        <Sparkles :size="10" class="text-blue-500" /> 您可能还想了解：
                      </p>
                      <div class="flex flex-col gap-1.5">
                        <button v-for="(q, qIdx) in msg.suggested_questions" :key="qIdx"
                          @click="askSuggestedQuestion(q)"
                          class="w-full text-left text-xs text-slate-700 dark:text-slate-350 px-3.5 py-2.5 rounded-xl border border-slate-200/80 dark:border-slate-800 bg-slate-50/50 dark:bg-slate-900/30 hover:border-blue-400 hover:bg-blue-50/30 dark:hover:border-blue-700 dark:hover:bg-blue-900/20 active:scale-[0.99] transition-all flex items-center gap-2 group cursor-pointer font-medium"
                          :disabled="sending">
                          <span class="w-1.5 h-1.5 rounded-full bg-blue-500 group-hover:scale-125 transition-transform" />
                          <span class="flex-1 truncate">{{ q }}</span>
                          <span class="text-[10px] text-blue-500 font-semibold opacity-0 group-hover:opacity-100 transition-opacity">🚀 发送</span>
                        </button>
                      </div>
                    </div>

                    <!-- 本地动画播放按钮 -->
                    <div v-if="msg._localVideos?.length" class="mt-3 pt-2 border-t border-gray-100">
                      <button
                        class="flex items-center gap-2 px-3 py-2 bg-gradient-to-r from-blue-500 to-purple-600 text-white rounded-lg text-sm font-medium hover:from-blue-600 hover:to-purple-700 transition-all shadow-sm"
                        @click="openLocalVideo(msg._localVideoKp || msg.target)"
                      >
                        <Film :size="16" /> 播放本地动画 ({{ msg._localVideos.length }} 个视频)
                      </button>
                    </div>

                    <!-- Grounded VisRAG Slide reference diagrams -->
                    <div v-if="getMatchedSlides(msg).length > 0" class="mt-3 bg-indigo-50/30 border border-indigo-100/50 p-3 rounded-xl">
                      <p class="text-xs font-semibold text-indigo-700 mb-2 flex items-center gap-1.5">
                        <LayoutGrid :size="12" /> 关联参考课件图谱 (VisRAG)
                      </p>
                      <div class="flex gap-2 flex-wrap">
                        <div v-for="(slide, sIdx) in getMatchedSlides(msg)" :key="sIdx" 
                          class="group relative w-32 rounded-lg overflow-hidden border border-gray-200 bg-white shadow-sm hover:shadow transition-all duration-200 cursor-pointer flex flex-col"
                          @click="openImageModal('/' + slide.content)">
                          <div class="h-20 bg-gray-50 overflow-hidden relative">
                            <img :src="'/' + slide.content" class="w-full h-full object-cover group-hover:scale-105 transition-transform duration-300" />
                          </div>
                          <div class="p-1 px-2 border-t border-gray-100 bg-white text-[9px] font-medium text-gray-500 truncate" :title="getSlideName(slide.content)">
                            {{ getSlideName(slide.content) }}
                          </div>
                        </div>
                      </div>
                    </div>

                    <!-- 一键矩阵资源生成按钮 -->
                    <div v-if="msg.target && getRegularResources(msg).length === 0 && !msg.streaming" class="mt-3.5 pt-3 border-t border-gray-100/60 flex items-center justify-between">
                      <span class="text-[11px] text-gray-400 font-medium">深度学习该概念的讲义、思维导图、代码沙箱及小测：</span>
                      <button @click="triggerMatrixGeneration(msg.target, idx)" class="btn text-xs font-semibold py-1.5 px-3 bg-gradient-to-r from-blue-600 to-purple-600 hover:from-blue-700 hover:to-purple-700 text-white rounded-xl shadow-sm hover:shadow-blue-500/10 active:scale-95 transition-all flex items-center gap-1.5 cursor-pointer font-semibold" :disabled="sending">
                        <Sparkles :size="12" /> 一键生成专属教学资源包
                      </button>
                    </div>

                    <!-- RDI 幻觉风险溯源指数 (创新点1) -->
                    <div v-if="msg.rdi" class="mt-3 pt-2.5 border-t border-gray-100 flex flex-wrap items-center gap-2 text-[10px]">
                      <span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-md font-medium"
                        :class="msg.rdi.score < 0.15 ? 'bg-emerald-50 text-emerald-700 border border-emerald-100' : msg.rdi.score < 0.4 ? 'bg-amber-50 text-amber-700 border border-amber-100' : 'bg-red-50 text-red-700 border border-red-100'">
                        🛡️ RDI 幻觉风险指数: {{ Math.round(msg.rdi.score * 100) }}% ({{ msg.rdi.category }})
                      </span>
                      <span class="text-gray-400 font-medium">{{ msg.rdi.explanation }}</span>
                      
                      <!-- 溯源实体展示 -->
                      <div v-if="msg.rdi.details?.matched_entities?.length" class="w-full flex items-center gap-1 flex-wrap mt-1">
                        <span class="text-gray-400">已比对知识库实体:</span>
                        <span v-for="ent in msg.rdi.details.matched_entities" :key="ent" class="px-1.5 py-0.5 bg-gray-50 border border-gray-200 text-gray-500 rounded text-[9px] font-mono">
                          🔗 {{ ent }}
                        </span>
                      </div>
                    </div>
                  </div>

                  <!-- 任务 8.3: 资源卡片 + 局部重生成按钮 -->
                  <div v-if="getRegularResources(msg).length" class="mt-3 space-y-2.5">
                    <template v-for="(res, ri) in msg.resources" :key="ri">
                      <div v-if="res.type !== 'slide_reference' && res.resource_type !== 'slide_reference'"
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
                          <!-- 视频推荐官/自适应推荐视频卡片：免跳转视频播放舱 -->
                          <div v-if="res.agent === '视频推荐官' || res.agent === '虚拟导演' || res.resource_type === '自适应推荐视频' || res.resource_type === '虚拟人视频脚本' || res.type === '自适应推荐视频'">
                            <!-- 如果是新版的 JSON 视频列表 -->
                            <template v-if="safeParseJson(res.content).length > 0">
                              <VideoPlayerCard 
                                :videos="safeParseJson(res.content)" 
                                :concept="msg.target" 
                              />
                            </template>
                            <!-- 如果是旧版的 Markdown 文本格式，且有本地动画匹配 -->
                            <template v-else-if="msg._localVideos?.length">
                              <div class="space-y-2">
                                <div class="flex items-center gap-2 text-xs text-gray-500">
                                  <Film :size="14" class="text-blue-500" />
                                  <span>本地动画 · {{ msg._localVideoKp || msg.target }}</span>
                                  <span class="text-gray-300">|</span>
                                  <span>{{ msg._localVideos.length }} 个视频</span>
                                </div>
                                <div class="grid gap-2">
                                  <div v-for="(v, vi) in msg._localVideos.slice(0, 3)" :key="vi"
                                    class="bg-white rounded-lg border border-gray-200 overflow-hidden">
                                    <div class="flex items-center justify-between px-3 py-2 bg-gray-50 border-b border-gray-100">
                                      <span class="text-xs text-gray-600 truncate flex-1">{{ v.filename }}</span>
                                      <span class="text-[10px] text-gray-400 ml-2">{{ (v.size / 1024 / 1024).toFixed(1) }}MB</span>
                                    </div>
                                    <div v-if="inlineVideoIndex === ri + '_' + vi" class="bg-black">
                                      <video
                                        :src="v.url"
                                        class="w-full"
                                        style="max-height: 300px"
                                        controls
                                        autoplay
                                        @ended="inlineVideoIndex = -1"
                                      />
                                    </div>
                                    <div v-else class="p-2">
                                      <button
                                        class="flex items-center gap-1.5 px-3 py-1.5 text-xs bg-blue-500 text-white rounded-lg hover:bg-blue-600 transition-colors"
                                        @click="inlineVideoIndex = ri + '_' + vi"
                                      >
                                        <Play :size="12" /> 播放
                                      </button>
                                    </div>
                                  </div>
                                </div>
                                <p class="text-[10px] text-gray-400 mt-1">视频脚本：{{ res.content.slice(0, 200) }}{{ res.content.length > 200 ? '...' : '' }}</p>
                              </div>
                            </template>
                            <!-- 普通 Markdown 渲染 fallback -->
                            <template v-else>
                              <div class="prose prose-sm max-w-none text-xs text-gray-700 leading-relaxed" v-html="renderMarkdown(res.content, res.type || res.resource_type || res.agent, msg.target)"></div>
                            </template>
                            <div class="mt-3 flex justify-end gap-2">
                              <button @click="setQuote(res.content, getAgentConfig(res.agent, res.resource_type || res.type).label)" class="px-3 py-1.5 bg-blue-50 hover:bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:hover:bg-blue-900/50 dark:text-blue-400 border border-blue-200/50 dark:border-blue-800/40 rounded-lg text-[10px] font-semibold shadow-sm transition-all flex items-center gap-1">
                                <MessageSquare :size="10" /> 💬 追问 →
                              </button>
                            </div>
                          </div>
                          <!-- 普通资源卡片：Markdown 渲染 -->
                          <div v-else>
                            <div class="prose prose-sm max-w-none text-xs text-gray-700 leading-relaxed" v-html="renderMarkdown(res.content, res.type || res.resource_type || res.agent, msg.target)"></div>
                            <div class="mt-3 flex justify-end gap-2">
                              <!-- 如果是极客助教资源，添加一键挂载至沙箱按钮 -->
                              <button v-if="getAgentConfig(res.agent, res.resource_type || res.type).label === '极客助教'" @click="mountToSandbox(res.content)" class="px-3 py-1.5 bg-green-50 hover:bg-green-100 text-green-700 dark:bg-green-900/30 dark:hover:bg-green-900/50 dark:text-green-400 border border-green-200/50 dark:border-green-800/40 rounded-lg text-[10px] font-semibold shadow-sm transition-all flex items-center gap-1">
                                <Terminal :size="10" /> 挂载至沙箱 →
                              </button>
                              <button @click="setQuote(res.content, getAgentConfig(res.agent, res.resource_type || res.type).label)" class="px-3 py-1.5 bg-blue-50 hover:bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:hover:bg-blue-900/50 dark:text-blue-400 border border-blue-200/50 dark:border-blue-800/40 rounded-lg text-[10px] font-semibold shadow-sm transition-all flex items-center gap-1">
                                <MessageSquare :size="10" /> 💬 追问 →
                              </button>
                            </div>
                          </div>
                        </div>
                      </div>
                    </template>
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

        <!-- 一键回到顶端/底端悬浮按钮 -->
        <Teleport to="body">
          <div v-if="messages.length > 0" class="scroll-fab-container" :class="{ 'has-right-panel': shouldShowRightPanel }">
            <button @click="scrollToTop" class="w-8 h-8 rounded-xl bg-white/95 hover:bg-blue-600 text-gray-500 hover:text-white border border-gray-200/80 shadow-md hover:shadow-blue-500/10 transition-all duration-200 hover:scale-115 active:scale-90 flex items-center justify-center backdrop-blur-md cursor-pointer" title="回到最顶端">
              <ChevronUp :size="16" />
            </button>
            <button @click="scrollToBottom" class="w-8 h-8 rounded-xl bg-white/95 hover:bg-blue-600 text-gray-500 hover:text-white border border-gray-200/80 shadow-md hover:shadow-blue-500/10 transition-all duration-200 hover:scale-115 active:scale-90 flex items-center justify-center backdrop-blur-md cursor-pointer" title="回到最底端">
              <ChevronDown :size="16" />
            </button>
          </div>
        </Teleport>

        <!-- 输入区域容器 -->
        <div class="relative mt-2 shrink-0">
          <!-- 📚 课件选择面板 -->
          <div v-if="showDocSelector" id="doc-selector-panel" class="doc-selector-panel absolute bottom-full mb-2 left-0 w-80 bg-white border border-gray-200 rounded-2xl shadow-2xl p-3.5 z-50 flex flex-col gap-2.5 animate-fade-in">
            <div class="flex items-center justify-between pb-2 border-b border-gray-100">
              <span class="text-xs font-semibold text-gray-800 flex items-center gap-1.5">
                <BookOpen :size="13" class="text-indigo-500" /> 选择并引用课件文件
              </span>
              <button @click="showDocSelector = false" class="text-gray-400 hover:text-gray-600 border-none bg-transparent cursor-pointer flex items-center justify-center">
                <X :size="13" />
              </button>
            </div>
            <!-- 搜索框 -->
            <div class="relative flex items-center">
              <Search :size="12" class="absolute left-3 text-gray-400" />
              <input v-model="docSelectorQuery" 
                     class="w-full pl-8 pr-3 py-1.5 text-xs rounded-lg border border-gray-200 focus:border-indigo-300 focus:ring-2 focus:ring-indigo-50 outline-none transition-all placeholder:text-gray-400" 
                     placeholder="搜索课件名称..." />
            </div>
            <!-- 课件列表 -->
            <div class="max-h-56 overflow-y-auto flex flex-col gap-1.5 pr-1 custom-scrollbar">
              <div v-if="filteredDocSelectorList.length === 0" class="text-[10px] text-gray-400 py-6 text-center">
                暂无匹配课件，请先在知识库页面上传
              </div>
              <button v-for="doc in filteredDocSelectorList" :key="doc.name"
                      @click="insertDocReference(doc.name)"
                      class="w-full min-h-[42px] px-2.5 py-2 text-left rounded-xl hover:bg-indigo-50/50 transition-all border-none bg-transparent cursor-pointer flex items-center justify-between gap-2 group">
                <div class="flex flex-col min-w-0 flex-1 pr-1 leading-snug">
                  <span class="text-xs font-medium text-gray-700 truncate group-hover:text-indigo-600" :title="doc.desc">{{ doc.desc }}</span>
                  <span class="text-[9px] text-gray-400 truncate mt-0.5" :title="doc.name">{{ doc.name }}</span>
                </div>
                <span class="text-[9px] leading-none px-1.5 py-1 rounded-md bg-gray-100 text-gray-500 shrink-0 group-hover:bg-indigo-100 group-hover:text-indigo-600 transition-colors">{{ doc.label }}</span>
              </button>
            </div>
          </div>

          <!-- Autocomplete Suggestions Dropdown -->
          <div v-if="showSuggest && filteredSuggestions.length > 0" class="absolute bottom-full mb-2 left-0 right-0 bg-white border border-indigo-100 rounded-xl shadow-xl overflow-hidden z-50 max-h-48 overflow-y-auto">
            <div v-for="(item, idx) in filteredSuggestions" :key="item.name" 
                 class="flex items-center justify-between px-4 py-2 cursor-pointer text-xs transition-colors border-b border-gray-100 last:border-b-0 animate-fade-in"
                 :class="idx === suggestIndex ? 'bg-indigo-600 text-white' : 'text-slate-700 hover:bg-indigo-50'"
                 @click="selectSuggestion(item)">
              <div class="flex items-center gap-2">
                <span class="font-bold text-indigo-600" :class="{'text-white': idx === suggestIndex}">{{ item.name }}</span>
                <span class="text-slate-500 text-[10px]" :class="{'text-indigo-100': idx === suggestIndex}">{{ item.desc }}</span>
              </div>
              <span class="px-1.5 py-0.5 rounded text-[10px] bg-indigo-50 text-indigo-600" :class="{'bg-indigo-700 text-white': idx === suggestIndex}">{{ item.label }}</span>
            </div>
          </div>

          <!-- 图片预览 row -->
          <div v-if="uploadedImages.length > 0" class="flex gap-2 flex-wrap mb-2 p-2 bg-gray-50 rounded-xl border border-gray-200/60 shadow-inner">
            <div v-for="(img, idx) in uploadedImages" :key="idx" class="relative w-16 h-16 rounded-lg overflow-hidden border border-gray-200 shadow-sm bg-white shrink-0">
              <img :src="img" class="w-full h-full object-cover" />
              <button @click="removeUploadedImage(idx)" class="absolute top-1 right-1 w-4 h-4 rounded-full bg-black/60 hover:bg-black text-white flex items-center justify-center cursor-pointer transition-all border-none" title="移除图片">
                <X :size="10" />
              </button>
            </div>
          </div>

          <!-- Doubao-style Quote Reference Bar -->
          <div 
            v-if="quotedContent" 
            class="flex items-center justify-between gap-3 px-3 py-2 bg-blue-50/70 dark:bg-blue-950/20 border border-blue-100 dark:border-blue-900/60 rounded-xl mb-2 text-xs text-slate-600 dark:text-slate-400 backdrop-blur-md animate-fade-in shadow-sm select-none"
          >
            <div class="flex items-center gap-2 truncate">
              <span class="text-[10px] bg-blue-100 text-blue-700 dark:bg-blue-900/50 dark:text-blue-300 px-1.5 py-0.5 rounded font-semibold shrink-0">引用 · {{ quotedContent.source }}</span>
              <span class="truncate font-mono italic text-slate-500 dark:text-slate-400">"{{ quotedContent.text }}"</span>
            </div>
            <button 
              @click="quotedContent = null" 
              class="p-1 hover:bg-blue-100 dark:hover:bg-blue-900/60 rounded-lg text-blue-400 hover:text-blue-700 dark:hover:text-blue-300 transition-colors shrink-0 border-none bg-transparent cursor-pointer"
              title="清除引用"
            >
              <X :size="14" />
            </button>
          </div>

          <div class="flex items-end gap-2 bg-white border border-gray-200 rounded-xl p-2 shadow-sm">
            <!-- 📚 课件选择按钮 -->
            <button @click.stop="toggleDocSelector" 
                    class="doc-selector-trigger p-2 text-gray-400 hover:text-indigo-600 rounded-lg hover:bg-gray-50 shrink-0 cursor-pointer transition-all flex items-center justify-center border-none bg-transparent" 
                    title="选择并引用课件文件">
              <BookOpen :size="16" />
            </button>
            <!-- 📎 图片上传按钮 -->
            <label class="p-2 text-gray-400 hover:text-indigo-600 rounded-lg hover:bg-gray-50 shrink-0 cursor-pointer transition-all flex items-center justify-center" title="上传题目截图/数学公式图片">
              <FileText :size="16" />
              <input type="file" accept="image/*" class="hidden" @change="handleImageUpload" />
            </label>
            <textarea v-model="input" class="flex-1 resize-none outline-none text-sm px-2 py-1.5 max-h-32" placeholder="输入学习问题，可使用 / 调用智能体，使用 @ 引用知识库文件..." rows="1" @keydown="handleKeydown" />
            <button class="btn btn-primary shrink-0" :disabled="(!input.trim() && uploadedImages.length === 0) || sending" @click="send"><Send :size="16" /></button>
          </div>
        </div>
      </div>

      <!-- QUIZ TAB -->
      <div v-if="activeTab === 'quiz'" class="flex flex-col flex-1 min-h-0 max-w-4xl mb-6">
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
          <div class="card mb-4 space-y-3 relative" :class="{ 'shake-trigger': shakeCard }">
            <!-- 彩带粒子层 -->
            <div v-if="showConfetti" class="absolute inset-0 overflow-hidden pointer-events-none rounded-xl z-10">
              <div
                v-for="(p, i) in confettiParticles"
                :key="i"
                class="confetti-particle"
                :style="{
                  left: p.x + '%',
                  backgroundColor: p.color,
                  animationDelay: p.delay + 's',
                  width: p.size + 'px',
                  height: p.size + 'px',
                }"
              />
            </div>
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
      <div v-if="activeTab === 'code'" class="flex flex-col flex-1 min-h-0 max-w-4xl mb-6">
        <div class="flex items-center justify-between mb-3">
          <h3 class="text-sm font-semibold text-gray-800 flex items-center gap-2">
            <Terminal :size="16" class="text-emerald-600" /> Python 代码沙箱
          </h3>
          <div class="flex gap-1">
            <button v-for="preset in codePresets" :key="preset.label" class="px-2.5 py-1 text-[10px] font-medium rounded-lg border border-gray-200 bg-white hover:bg-emerald-50 hover:border-emerald-200 hover:text-emerald-700 text-gray-500 transition-all" @click="insertCodeSnippet(preset.code)">{{ preset.label }}</button>
          </div>
        </div>

        <div class="flex-1 flex flex-col min-h-0">
          <div class="flex-1 flex flex-col rounded-xl border border-slate-200 overflow-hidden shadow-sm bg-white">
            <div class="bg-slate-50 text-slate-700 text-xs px-4 py-2 flex items-center justify-between border-b border-slate-200">
              <div class="flex items-center gap-2">
                <span class="w-2.5 h-2.5 rounded-full bg-red-400" />
                <span class="w-2.5 h-2.5 rounded-full bg-yellow-400" />
                <span class="w-2.5 h-2.5 rounded-full bg-green-400" />
                <span class="ml-2 font-mono text-slate-500">sandbox.py</span>
              </div>
              <button class="px-3 py-1 text-[10px] font-semibold rounded-lg bg-emerald-500 hover:bg-emerald-600 text-white transition-all flex items-center gap-1.5" :disabled="!codeInput.trim() || codeRunning" @click="runUserCode">
                <Play :size="10" /> {{ codeRunning ? '运行中...' : '运行' }}
              </button>
            </div>
            <textarea v-model="codeInput" class="flex-1 bg-slate-50 text-slate-800 font-mono text-xs p-4 resize-none outline-none leading-relaxed placeholder:text-slate-400" placeholder="# 在这里输入 Python 代码..." spellcheck="false" />
            <!-- 行号和复制按钮 -->
            <div class="absolute top-9 right-2 flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
              <button class="p-1.5 rounded-md bg-white hover:bg-slate-100 text-slate-400 hover:text-slate-700 transition-all" title="复制代码" @click="copyCode">
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
      <div v-if="activeTab === 'websearch'" class="flex flex-col flex-1 min-h-0 max-w-4xl mb-6">
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

            <!-- 分类选择器 -->
            <div class="flex items-center gap-1.5 mt-3 p-1 bg-gray-50 rounded-xl w-fit border border-gray-100/50">
              <button 
                v-for="cat in [
                  { id: 'all', label: '全部资源' },
                  { id: 'web', label: '在线网页' },
                  { id: 'document', label: '学术文档' }
                ]"
                :key="cat.id"
                @click="searchCategory = cat.id"
                class="px-3 py-1.5 text-xs font-semibold rounded-lg transition-all border border-transparent"
                :class="searchCategory === cat.id 
                  ? 'bg-white text-blue-600 shadow-sm border-gray-100' 
                  : 'text-gray-500 hover:text-gray-800'"
              >
                {{ cat.label }}
              </button>
            </div>

            <div v-if="searchLoading" class="flex items-center gap-2 mt-3 text-gray-400 text-xs">
              <div class="w-4 h-4 border-2 border-blue-400 border-t-transparent rounded-full animate-spin" />
              正在搜索并索引...
            </div>
            <div v-if="searchSummary" class="mt-3 text-sm text-gray-700 bg-gradient-to-r from-blue-50 to-indigo-50/50 rounded-xl p-4 whitespace-pre-wrap border border-blue-100/50 leading-relaxed">{{ searchSummary }}</div>
            <div v-if="searchResults.length" class="mt-3 space-y-1">
              <div v-for="(r, i) in searchResults" :key="i" class="flex items-start justify-between gap-3 p-3 rounded-xl hover:bg-gray-50 transition-all cursor-pointer" @click="openUrl(r.url)">
                <div class="flex items-start gap-3 min-w-0 flex-1">
                  <div class="w-6 h-6 rounded-lg flex items-center justify-center shrink-0 mt-0.5"
                       :class="r.is_file
                         ? (r.file_type === 'pdf' ? 'bg-red-50 text-red-500' : 'bg-orange-50 text-orange-500')
                         : 'bg-blue-50 text-blue-500'">
                    <component :is="r.is_file ? FileText : Globe" :size="12" />
                  </div>
                  <div class="min-w-0 flex-1">
                    <p class="text-xs font-semibold text-gray-800 hover:text-blue-600 flex items-center gap-1.5 truncate">
                      <span v-if="r.is_file" 
                            class="px-1 py-0.5 text-[8px] font-bold rounded uppercase shrink-0"
                            :class="r.file_type === 'pdf' ? 'bg-red-100 text-red-700' : 'bg-orange-100 text-orange-700'">
                        {{ r.file_type }}
                      </span>
                      {{ r.title }}
                    </p>
                    <p class="text-[10px] text-gray-400 mt-0.5 line-clamp-2 leading-relaxed">{{ r.snippet }}</p>
                    <p v-if="r.url" class="text-[9px] text-gray-300 mt-0.5 truncate flex items-center gap-1">
                      <Globe :size="8" class="shrink-0" />
                      {{ getDomain(r.url) }}
                    </p>
                  </div>
                </div>
                <div class="flex items-center self-center shrink-0">
                  <button
                    @click.stop="ingestWebSearchItem(r)"
                    :disabled="r.adding || docs.some(d => d.filename.includes(r.title))"
                    class="px-2.5 py-1.5 text-[10px] font-bold rounded-lg border flex items-center gap-1 transition-all"
                    :class="docs.some(d => d.filename.includes(r.title)) 
                      ? 'bg-emerald-50 text-emerald-600 border-emerald-200 cursor-not-allowed' 
                      : 'bg-blue-50 text-blue-600 border-blue-200 hover:bg-blue-100/70 hover:text-blue-700'"
                  >
                    <component :is="docs.some(d => d.filename.includes(r.title)) ? CheckCircle2 : Sparkles" :size="10" />
                    {{ docs.some(d => d.filename.includes(r.title)) ? '已导入' : r.adding ? (r.is_file ? '下载解析中...' : '总结导入中...') : (r.is_file ? '下载并解析文件' : '导入知识库') }}
                  </button>
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
      <div class="w-full max-w-4xl hidden xl:flex flex-col gap-6 overflow-y-auto scrollbar-none pb-4 shrink-0">
            
            <div class="grid grid-cols-2 gap-6 shrink-0 items-stretch">
              <AgentTimeline 
                class="w-full shrink-0"
                :progress="chatStore.streamingProgress" 
                :status="chatStore.streamingStatus" 
                :agents="chatStore.streamingAgents" 
              />
              <div class="card p-4 bg-white border border-gray-200 shadow-sm flex flex-col justify-center min-h-[360px] shrink-0">
                <h3 class="text-xs font-bold text-gray-700 mb-2 flex items-center gap-1.5 justify-center border-b border-gray-100 pb-2">
                  <BrainCircuit :size="14" class="text-blue-500" />
                  <span>能力掌握度雷达图</span>
                </h3>
                <div class="flex-1 flex items-center justify-center min-h-[290px] w-full overflow-visible">
                  <MasteryRadar 
                    class="w-full h-full min-h-[290px]"
                    :concepts="radarConcepts" 
                    :show-comparison="showComparison"
                    :student-id="props.studentId" 
                  />
                </div>
              </div>
            </div>

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
      class="chat-tool-panel sticky top-6 self-start transition-all duration-300 overflow-hidden shrink-0 rounded-2xl shadow-xl"
      :class="shouldShowRightPanel ? 'w-[360px] lg:w-[420px]' : 'w-0 border-l-0'">
      <div v-if="shouldShowRightPanel" class="h-[calc(100vh-120px)] flex flex-col p-3">
        <!-- 面板切换栏 -->
        <div class="flex items-center justify-between mb-3 border-b border-gray-800 pb-2">
          <div class="flex flex-wrap gap-1">
            <button
              @click="rightPanelActiveTab = 'canvas'"
              class="px-2 py-1 rounded text-[10px] transition-all font-semibold"
              :class="rightPanelActiveTab === 'canvas' ? 'bg-blue-600 text-white shadow-sm' : 'bg-white text-slate-600 hover:bg-slate-100'"
            >
              🎨 双曲圆盘
            </button>
            <button
              @click="rightPanelActiveTab = 'sandbox'"
              class="px-2 py-1 rounded text-[10px] transition-all font-semibold"
              :class="rightPanelActiveTab === 'sandbox' ? 'bg-green-600 text-white shadow-sm' : 'bg-white text-slate-600 hover:bg-slate-100'"
            >
              💻 沙箱
            </button>
            <button
              @click="rightPanelActiveTab = 'knowledge'"
              class="px-2 py-1 rounded text-[10px] transition-all font-semibold"
              :class="rightPanelActiveTab === 'knowledge' ? 'bg-purple-600 text-white shadow-sm' : 'bg-white text-slate-600 hover:bg-slate-100'"
            >
              📖 知识点
            </button>
            <button
              @click="rightPanelActiveTab = 'visualizer'"
              class="px-2 py-1 rounded text-[10px] transition-all font-semibold"
              :class="rightPanelActiveTab === 'visualizer' ? 'bg-teal-600 text-white shadow-sm' : 'bg-white text-slate-600 hover:bg-slate-100'"
            >
              📊 可视化
            </button>
          </div>
          <button
            @click="rightPanelCollapsed = true"
            class="w-6 h-6 rounded-lg hover:bg-gray-800 flex items-center justify-center text-gray-400 hover:text-gray-200 transition-all shrink-0"
            title="折叠面板"
          >
            <Minimize2 :size="12" />
          </button>
        </div>

        <!-- 1. 代码沙箱 -->
        <SandboxConsole v-if="rightPanelActiveTab === 'sandbox'"
          :studentId="props.studentId"
          :initialCode="sandboxInitialCode" />

        <!-- 2. 知识点速览 -->
        <KnowledgePointsPanel v-else-if="rightPanelActiveTab === 'knowledge'"
          :concepts="conceptList"
          :discussionThemes="discussionThemes"
          :webResults="[]"
          :inline="true" />

        <!-- 3. 可视化分析 -->
        <SandboxVisualizer v-else-if="rightPanelActiveTab === 'visualizer'"
          :studentId="props.studentId"
          :inline="true" />

        <!-- 4. 绘图区域/画布 -->
        <div v-else class="flex-1 flex flex-col min-h-0">
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

    <!-- 全局划词即时追问悬浮胶囊 -->
    <Teleport to="body">
      <div
        v-if="textSelection.visible"
        class="fixed z-[100] animate-fade-in flex items-center gap-1.5 bg-white/95 dark:bg-slate-900/95 rounded-full px-3 py-1.5 shadow-xl border border-slate-200 dark:border-slate-800/80 backdrop-blur-md selection-capsule select-none"
        :style="{ left: textSelection.x + 'px', top: textSelection.y + 'px', transform: 'translateX(-50%)' }"
      >
      <!-- Drag handle -->
      <div 
        @mousedown="startDrag" 
        class="cursor-grab active:cursor-grabbing px-1 text-slate-400 dark:text-slate-500 hover:text-slate-600 dark:hover:text-slate-350 text-xs flex items-center justify-center font-bold"
        title="按住拖拽移动位置"
      >
        ⋮⋮
      </div>
      <button 
        @mousedown.stop
        @click="openSocraticPopup(textSelection.text, '', '', 0, -1)"
        class="flex items-center gap-1.5 px-1 py-0.5 text-slate-700 dark:text-slate-200 rounded-full text-xs font-bold hover:scale-105 active:scale-95 transition-transform cursor-pointer whitespace-nowrap bg-transparent border-none outline-none"
      >
        <MessageSquare :size="12" class="text-blue-600 dark:text-blue-400 shrink-0" />
        <span>💬 追问</span>
      </button>
      </div>
    </Teleport>

    <!-- ========== 任务 8.1: 行级悬浮苏格拉底即时答疑弹窗 ========== -->
    <InlineSocraticPopup
      v-if="socraticPopup.visible"
      :targetText="socraticPopup.targetText"
      :contextBefore="socraticPopup.contextBefore"
      :contextAfter="socraticPopup.contextAfter"
      :lineIndex="socraticPopup.lineIndex"
      :messageIndex="socraticPopup.messageIndex"
      :anchorX="socraticPopup.anchorX"
      :anchorY="socraticPopup.anchorY"
      :activeTab="activeTab"
      :studentId="props.studentId"
      :rightPanelCollapsed="rightPanelCollapsed"
      @close="socraticPopup.visible = false" />

    <!-- 可视化分析悬浮按钮 -->
    <Teleport to="body">
    <div v-if="activeTab === 'chat'" class="chat-fab fixed bottom-[140px] right-6 z-50 group">
      <button
        class="w-11 h-11 rounded-2xl bg-gradient-to-br from-emerald-400 to-cyan-500 text-white shadow-lg hover:scale-105 transition-all flex items-center justify-center cursor-pointer"
        @click="rightPanelActiveTab = 'visualizer'; rightPanelCollapsed = false"
      >
        <span class="text-xl">📊</span>
      </button>
      <!-- Tooltip -->
      <div class="absolute right-full mr-3 top-1/2 -translate-y-1/2 scale-75 opacity-0 group-hover:scale-100 group-hover:opacity-100 transition-all duration-200 bg-gray-900/90 text-white text-xs px-2.5 py-1.5 rounded-lg border border-gray-700/50 shadow-xl pointer-events-none whitespace-nowrap">
        可视化分析
      </div>
    </div>

    <!-- 任务 8.5: 视频渲染面板 -->
    <div v-if="activeTab === 'chat'" class="chat-fab fixed bottom-[84px] right-6 z-50 group">
      <button
        class="w-11 h-11 rounded-2xl bg-gradient-to-br from-blue-500 to-indigo-600 text-white shadow-lg hover:scale-105 transition-all flex items-center justify-center cursor-pointer"
        @click="toggleVideoPanel"
      >
        <Film :size="20" />
      </button>
      <!-- Tooltip -->
      <div class="absolute right-full mr-3 top-1/2 -translate-y-1/2 scale-75 opacity-0 group-hover:scale-100 group-hover:opacity-100 transition-all duration-200 bg-gray-900/90 text-white text-xs px-2.5 py-1.5 rounded-lg border border-gray-700/50 shadow-xl pointer-events-none whitespace-nowrap">
        本地动画库
      </div>
    </div>

    <!-- 知识点速览悬浮按钮 -->
    <div v-if="activeTab === 'chat'" class="chat-fab fixed bottom-7 right-6 z-50 group">
      <button
        class="w-11 h-11 rounded-2xl bg-gradient-to-br from-violet-500 to-indigo-600 shadow-lg flex items-center justify-center cursor-pointer hover:scale-105 transition-all hover:shadow-xl"
        @click="rightPanelActiveTab = 'knowledge'; rightPanelCollapsed = false"
      >
        <BookOpen :size="22" class="text-white" />
      </button>
      <!-- Tooltip -->
      <div class="absolute right-full mr-3 top-1/2 -translate-y-1/2 scale-75 opacity-0 group-hover:scale-100 group-hover:opacity-100 transition-all duration-200 bg-gray-900/90 text-white text-xs px-2.5 py-1.5 rounded-lg border border-gray-700/50 shadow-xl pointer-events-none whitespace-nowrap">
        展开知识点速览
      </div>
    </div>
    </Teleport>
    <VideoRenderPanel
      :visible="showVideoPanel"
      :studentId="props.studentId"
      :knowledgePoint="currentVideoKp"
      @close="showVideoPanel = false" />
    <LocalVideoPlayer
      :visible="showLocalVideo"
      :videos="localVideos"
      :knowledgePoint="localVideoKnowledgePoint"
      @close="showLocalVideo = false" />

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
              class="zoom-mermaid-target transition-transform duration-200 origin-center bg-white p-4 rounded-xl shadow-md border border-gray-100 flex items-center justify-center animate-fade-in min-w-full min-h-full"
              :style="{ transform: `scale(${zoomScale}) translate(${panOffset.x}px, ${panOffset.y}px)` }"
            >
              <CollapsibleMindmap v-if="isZoomMindmap" :code="zoomModal.code" class="w-full" />
              <div v-else class="mermaid flex justify-center">{{ zoomModal.code }}</div>
            </div>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- ========== AI 笔记提炼预览舱 Modal ========== -->
    <Teleport to="body">
      <div v-if="showNoteModal" class="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm" @click.self="showNoteModal = false">
        <div class="bg-white rounded-2xl shadow-2xl w-[600px] max-h-[85vh] flex flex-col overflow-hidden border border-gray-100">
          <div class="flex items-center justify-between px-5 py-3.5 border-b border-gray-100 bg-blue-50/20 shrink-0">
            <h3 class="text-sm font-bold text-gray-800 flex items-center gap-1.5">
              <Sparkles :size="15" class="text-blue-600" />
              <span>AI 笔记智能提炼舱</span>
            </h3>
            <button class="text-gray-400 hover:text-gray-600 text-lg leading-none" @click="showNoteModal = false"><X :size="16" /></button>
          </div>
          <div class="flex-1 overflow-y-auto p-5 space-y-4">
            <div v-if="noteModalLoading" class="flex flex-col items-center justify-center py-12 text-gray-400">
              <Loader2 :size="24" class="animate-spin text-blue-500 mb-2" />
              <span class="text-xs">量化评估师正在梳理这堂课的知识脉络与核心推导...</span>
            </div>
            <div v-else class="space-y-4">
              <div class="flex flex-col gap-1">
                <label class="text-[10px] font-bold text-gray-400 uppercase tracking-wider">提炼后的 Markdown 笔记</label>
                <textarea v-model="noteModalForm.content" class="w-full h-64 p-3 font-mono text-xs rounded-xl border border-gray-200 bg-slate-900 text-slate-200 focus:border-blue-300 focus:ring-2 focus:ring-blue-100 outline-none transition-all resize-none" />
              </div>
              <div class="grid grid-cols-2 gap-4">
                <div class="flex flex-col gap-1">
                  <label class="text-[10px] font-bold text-gray-400 uppercase tracking-wider">关联概念</label>
                  <input v-model="noteModalForm.concepts" class="w-full px-3 py-2 text-xs rounded-xl border border-gray-200 bg-white focus:border-blue-300 focus:ring-2 focus:ring-blue-100 outline-none transition-all" placeholder="核心概念(英文逗号隔开)" />
                </div>
                <div class="flex flex-col gap-1">
                  <label class="text-[10px] font-bold text-gray-400 uppercase tracking-wider">推荐标签</label>
                  <input v-model="noteModalForm.tags" class="w-full px-3 py-2 text-xs rounded-xl border border-gray-200 bg-white focus:border-blue-300 focus:ring-2 focus:ring-blue-100 outline-none transition-all" placeholder="推荐标签(英文逗号隔开)" />
                </div>
              </div>
            </div>
          </div>
          <div class="flex items-center justify-end gap-2 px-5 py-3 border-t border-gray-100 bg-gray-50 shrink-0">
            <button class="px-4 py-2 bg-gray-100 hover:bg-gray-200 text-gray-600 rounded-xl text-xs font-semibold transition-all" @click="showNoteModal = false">取消</button>
            <button class="px-5 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-xl text-xs font-semibold shadow-sm transition-all" :disabled="noteModalLoading" @click="confirmSaveNote">确认保存到笔记本</button>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- ========== 知识库源内容预览 Modal ========== -->
    <Teleport to="body">
      <div v-if="showDocViewerModal" class="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm" @click.self="showDocViewerModal = false">
        <div class="bg-white rounded-2xl shadow-2xl w-[700px] max-h-[85vh] flex flex-col overflow-hidden border border-gray-100 animate-fade-in">
          <div class="flex items-center justify-between px-5 py-3.5 border-b border-gray-100 bg-blue-50/20 shrink-0">
            <h3 class="text-sm font-bold text-gray-800 flex items-center gap-1.5 min-w-0">
              <component :is="getFileIcon(activeDocViewer.filename, activeDocViewer.file_type)" :size="15" :class="getFileColorClass(activeDocViewer.filename, activeDocViewer.file_type)" class="shrink-0" />
              <span class="truncate pr-4">{{ activeDocViewer.title }}</span>
            </h3>
            <button class="text-gray-400 hover:text-gray-600 text-lg leading-none shrink-0" @click="showDocViewerModal = false"><X :size="16" /></button>
          </div>
          <div class="flex-1 overflow-y-auto p-5 min-h-0">
            <div v-if="docViewerLoading" class="flex flex-col items-center justify-center py-20 text-gray-400">
              <Loader2 :size="24" class="animate-spin text-blue-500 mb-2" />
              <span class="text-xs">正在流式加载并解析文档内容...</span>
            </div>
            <div v-else class="h-full flex flex-col">
              <div class="bg-gray-50 border border-gray-150 rounded-xl p-4 flex-1 overflow-y-auto max-h-[50vh] min-h-[300px]">
                <pre class="text-xs text-gray-700 whitespace-pre-wrap font-sans leading-relaxed break-all">{{ activeDocViewer.content }}</pre>
              </div>
              <div class="mt-3 text-[10px] text-gray-400 flex items-center justify-between">
                <span>文件类型: <span class="font-semibold uppercase">{{ activeDocViewer.file_type }}</span></span>
                <span>大小: <span class="font-semibold">{{ (activeDocViewer.file_size / 1024).toFixed(1) }} KB</span></span>
              </div>
            </div>
          </div>
          <div class="flex items-center justify-end px-5 py-3 border-t border-gray-100 bg-gray-50 shrink-0">
            <button class="px-5 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-xl text-xs font-semibold shadow-sm transition-all animate-fade-in" @click="showDocViewerModal = false">关闭窗口</button>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- Lightbox Modal -->
    <div v-if="lightboxImage" class="fixed inset-0 bg-black/80 flex items-center justify-center z-50 p-4" @click="lightboxImage = null">
      <div class="relative max-w-4xl max-h-[90vh]" @click.stop>
        <img :src="lightboxImage" class="max-w-full max-h-[90vh] rounded-lg shadow-2xl" />
        <button @click="lightboxImage = null" class="absolute top-2 right-2 w-8 h-8 rounded-full bg-black/60 hover:bg-black text-white flex items-center justify-center cursor-pointer transition-colors border-none" title="关闭">
          <X :size="18" />
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.tab-btn {
  display: inline-flex;
  align-items: center;
  gap: 0.375rem;
  padding: 0.5rem 1rem;
  border-radius: 0.75rem;
  font-size: 0.8125rem;
  font-weight: 600;
  color: #64748b;
  background: transparent;
  border: none;
  cursor: pointer;
  transition: color 180ms ease, background-color 180ms ease, box-shadow 180ms ease, transform 180ms ease;
}
.tab-btn:hover {
  background: #f4f7fb;
  color: #334155;
  transform: translateY(-1px);
}
.tab-btn.active {
  background: linear-gradient(135deg, #edf6ff, #f0efff);
  color: #245fc8;
  box-shadow: 0 6px 16px rgba(50, 127, 242, 0.11);
}

.chat-workspace {
  position: relative;
  isolation: isolate;
}

.chat-source-panel {
  background: rgba(255, 255, 255, 0.86);
  border-color: rgba(220, 228, 239, 0.9);
  box-shadow: 0 14px 40px rgba(38, 61, 101, 0.065);
  backdrop-filter: blur(18px);
}

.chat-toolbar {
  position: relative;
  z-index: 5;
}

.chat-reading-column {
  width: 100%;
  margin-left: auto;
  margin-right: auto;
  max-width: none;
}

.chat-tool-panel {
  background:
    radial-gradient(circle at 100% 0%, rgba(96, 165, 250, 0.16), transparent 16rem),
    linear-gradient(180deg, #f8fbff, #eef4fb);
  border: 1px solid #d8e3ef;
  box-shadow: 0 22px 58px rgba(54, 83, 121, 0.14);
}

.chat-main-column {
  min-width: 0;
}

.chat-fab button {
  border: 1px solid rgba(255, 255, 255, 0.3);
  box-shadow: 0 12px 28px rgba(44, 62, 110, 0.2), inset 0 1px 0 rgba(255, 255, 255, 0.28);
  backdrop-filter: blur(12px);
}

.chat-fab button:hover {
  box-shadow: 0 16px 34px rgba(44, 62, 110, 0.28), inset 0 1px 0 rgba(255, 255, 255, 0.35);
}
.scroll-fab-container {
  position: fixed;
  bottom: 280px;
  right: 80px;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  z-index: 30;
  transition: all 0.3s ease;
}

/* 当右侧面板显示时，微调固定按钮位置以防重叠 */
@media (min-width: 1024px) {
  .scroll-fab-container.has-right-panel {
    right: 440px;
  }
}
@media (max-width: 1023px) {
  .scroll-fab-container.has-right-panel {
    right: 380px;
  }

  .chat-workspace {
    gap: 0.75rem;
  }

  .chat-tool-panel {
    position: fixed;
    top: 84px;
    right: 16px;
    bottom: 16px;
    z-index: 40;
    max-width: calc(100vw - 32px);
  }
}

@media (max-width: 767px) {
  .chat-source-panel {
    position: fixed;
    top: 84px;
    left: 16px;
    bottom: 16px;
    z-index: 45;
    max-width: calc(100vw - 32px);
  }

  .chat-toolbar {
    align-items: flex-start;
    flex-direction: column;
  }

  .chat-toolbar > div:first-child {
    width: 100%;
    overflow-x: auto;
  }

  .tab-btn {
    flex: 1;
    justify-content: center;
    min-width: 74px;
  }

  .chat-reading-column {
    max-width: 100%;
  }

  .chat-fab {
    right: 1rem;
  }
}

/* ===== 物理抖动动画（答错时触发）===== */
@keyframes physicsShake {
  0%, 100% { transform: translateX(0); }
  10% { transform: translateX(-6px) rotate(-0.5deg); }
  20% { transform: translateX(5px) rotate(0.4deg); }
  30% { transform: translateX(-4px) rotate(-0.3deg); }
  40% { transform: translateX(3px) rotate(0.2deg); }
  50% { transform: translateX(-2px); }
  60% { transform: translateX(1px); }
  70% { transform: translateX(0); }
}

.shake-trigger {
  animation: physicsShake 0.6s ease-out;
}

/* ===== 彩带粒子特效（答对时触发）===== */
@keyframes confettiDrop {
  0% {
    transform: translateY(-10px) rotate(0deg) scale(1);
    opacity: 1;
  }
  100% {
    transform: translateY(120px) rotate(720deg) scale(0);
    opacity: 0;
  }
}

.confetti-particle {
  position: absolute;
  width: 8px;
  height: 8px;
  border-radius: 2px;
  animation: confettiDrop 1.2s ease-out forwards;
  pointer-events: none;
}

@keyframes scorePop {
  0% { transform: scale(0.5); opacity: 0; }
  50% { transform: scale(1.2); }
  100% { transform: scale(1); opacity: 1; }
}

.score-animate {
  animation: scorePop 0.5s cubic-bezier(0.34, 1.56, 0.64, 1) forwards;
}
</style>
