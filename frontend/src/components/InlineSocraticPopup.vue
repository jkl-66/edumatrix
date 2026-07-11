<script setup>
/**
 * InlineSocraticPopup.vue — v4: 浮动图标模式
 * 背景点击→最小化到浮动图标，X按钮→关闭
 */
import { ref, onMounted, nextTick, watch } from 'vue'
import { socraticExplainStream } from '../api'

const emit = defineEmits(['close'])

const props = defineProps({
  targetText: { type: String, default: '' },
  contextBefore: { type: String, default: '' },
  contextAfter: { type: String, default: '' },
  lineIndex: { type: Number, default: 0 },
  messageIndex: { type: Number, default: -1 },
  studentId: { type: String, default: 'demo-student' },
  activeTab: { type: String, default: 'chat' },
  rightPanelCollapsed: { type: Boolean, default: true },
})

const visible = ref(false)
const minimized = ref(false)
const steps = ref([])
const loading = ref(false)
const error = ref('')
const followUp = ref('')
const sendingFollowUp = ref(false)
const popupRef = ref(null)
const conversationHistory = ref('')

onMounted(async () => {
  visible.value = true
  await nextTick()
  await fetchExplanation()
})

watch(() => props.targetText, async (newVal) => {
  if (newVal) {
    minimized.value = false
    steps.value = []
    conversationHistory.value = ''
    followUp.value = ''
    await nextTick()
    await fetchExplanation()
  }
})

let streamController = null

async function fetchExplanation(followUpText = '') {
  loading.value = true
  error.value = ''
  
  // 先添加用户追问到步骤列表
  if (followUpText) {
    steps.value.push('', `🙋 你: ${followUpText}`, '')
  }
  
  let accumulatedContent = ''
  const firstIndex = steps.value.length
  
  streamController = socraticExplainStream({
    target_text: props.targetText,
    context_before: props.contextBefore,
    context_after: props.contextAfter,
    student_id: props.studentId,
    follow_up: followUpText,
    history: conversationHistory.value,
  },
  // onContent: 每收到一个 token 追加到最后一行
  (token) => {
    accumulatedContent += token
    // 持续更新最后一行
    const lines = accumulatedContent.split('\n').filter(l => l.trim())
    if (firstIndex === 0 && !followUpText) {
      steps.value = lines
    } else {
      // 保留前面的内容，只更新最后的流式行
      const baseSteps = steps.value.slice(0, firstIndex)
      if (followUpText) {
        // 第一次追问后：保留 "🙋 你: xxx" 那行
        const beforeSteps = steps.value.slice(0, firstIndex)
        steps.value = [...beforeSteps, ...lines]
      } else {
        steps.value = [...baseSteps, ...lines]
      }
    }
  },
  // onComplete: 流式结束
  (fullContent, data) => {
    if (followUpText) {
      conversationHistory.value += `\n学生: ${followUpText}\n导师: ${fullContent}`
    } else {
      conversationHistory.value = `导师: ${fullContent}`
    }
    loading.value = false
    streamController = null
  },
  // onError
  (err) => {
    error.value = err.message || '请求失败'
    if (!followUpText) steps.value = generateFallback(props.targetText)
    loading.value = false
    streamController = null
  })
}

function generateFallback(text) {
  if (!text) return ['无法识别']
  const lines = []
  const isFormula = /\\[a-zA-Z]|\\frac|\\partial|\$\$/.test(text)
  const isCode = /def |import |class |\bfor\b|\bif\b|return /.test(text)
  if (isFormula) {
    lines.push('📐 数学表达式')
    if (/\\frac/.test(text)) lines.push('📝 分数: \\frac{分子}{分母}')
    lines.push('', '💡 追问: "符号表示什么？"')
  } else if (isCode) {
    lines.push('💻 代码语句')
    lines.push('', '💡 追问: "参数和返回值？"')
  } else {
    lines.push('📖 "' + text.slice(0, 60) + '"', '💡 可继续追问')
  }
  return lines
}

async function sendFollowUp() {
  const text = followUp.value.trim()
  if (!text || sendingFollowUp.value) return
  sendingFollowUp.value = true
  followUp.value = ''
  await fetchExplanation(text)
  sendingFollowUp.value = false
  await nextTick()
  if (popupRef.value) popupRef.value.scrollTop = popupRef.value.scrollHeight
}

function minimize() {
  minimized.value = true
}

function restore() {
  minimized.value = false
}

function close() {
  minimized.value = true
}

function renderMarkdown(text) {
  if (!text) return ''
  let html = text.trim()
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  const blockMath = []
  html = html.replace(/\$\$([\s\S]*?)\$\$/g, (_, math) => {
    const idx = blockMath.length
    blockMath.push({ math: math.trim(), display: true })
    return `@@BLOCKMATHTOKEN${idx}@@`
  })
  const inlineMath = []
  html = html.replace(/\$([^$\n]+?)\$/g, (_, math) => {
    const idx = inlineMath.length
    inlineMath.push({ math: math.trim(), display: false })
    return `@@INLINEMATHTOKEN${idx}@@`
  })
  html = html
    .replace(/\*\*([^*]+)\*\*/g, '<strong class="font-bold text-white">$1</strong>')
    .replace(/\*([^*]+)\*/g, '<em class="italic text-gray-200">$1</em>')
    .replace(/`([^`]+)`/g, '<code class="px-1.5 py-0.5 bg-gray-800 text-yellow-300 rounded font-mono text-xs">$1</code>')
  function renderMath(math, display) {
    if (window.katex) {
      try { return window.katex.renderToString(math, { displayMode: display, throwOnError: false, trust: true }) }
      catch (err) { console.error('KaTeX error:', err) }
    }
    return display
      ? `<div class="my-2 p-2 bg-gray-800/80 text-center font-serif text-xs overflow-x-auto text-gray-200 border border-gray-700 rounded">${math}</div>`
      : `<span class="font-serif italic px-1 bg-gray-850 rounded text-gray-200">${math}</span>`
  }
  blockMath.forEach((item, idx) => { html = html.split(`@@BLOCKMATHTOKEN${idx}@@`).join(renderMath(item.math, true)) })
  inlineMath.forEach((item, idx) => { html = html.split(`@@INLINEMATHTOKEN${idx}@@`).join(renderMath(item.math, false)) })
  return html
}
</script>

<template>
  <Teleport to="body">
    <!-- 浮动图标（最小化状态） -->
    <div v-if="minimized && activeTab === 'chat' && rightPanelCollapsed"
      class="fixed bottom-[216px] right-6 z-50 group"
      @click="restore">
      <div class="w-12 h-12 rounded-full bg-purple-600 shadow-lg flex items-center justify-center cursor-pointer hover:bg-purple-500 hover:scale-110 transition-all hover:shadow-xl">
        <span class="text-white text-xl">🧠</span>
      </div>
      <!-- Tooltip -->
      <div class="absolute right-full mr-3 top-1/2 -translate-y-1/2 scale-75 opacity-0 group-hover:scale-100 group-hover:opacity-100 transition-all duration-200 bg-gray-900/90 text-white text-xs px-2.5 py-1.5 rounded-lg border border-gray-700/50 shadow-xl pointer-events-none whitespace-nowrap">
        恢复即时答疑 (Socratic)
      </div>
    </div>

    <!-- 主弹窗 -->
    <div v-if="visible && !minimized && activeTab === 'chat'" class="fixed inset-0 z-50 flex items-start justify-center pt-16 md:pt-24" @click.self="minimize">
      <div
        class="inline-socratic-popup bg-gray-900/95 backdrop-blur-sm border border-gray-700/60 rounded-2xl shadow-2xl w-[90vw] md:w-[480px] max-h-[80vh] flex flex-col"
        @click.stop>
        <!-- 头部 -->
        <div class="flex items-center justify-between px-4 py-3 border-b border-gray-700/50 shrink-0">
          <div class="flex items-center gap-2">
            <span class="text-xs font-semibold text-purple-400">🧠 苏格拉底即时答疑</span>
            <span class="px-1.5 py-0.5 text-[8px] font-medium rounded-md bg-purple-500/20 text-purple-300">BETA</span>
          </div>
          <div class="flex items-center gap-1">
            <button @click="minimize" class="w-6 h-6 rounded-lg hover:bg-gray-700 flex items-center justify-center text-gray-400 hover:text-gray-200 transition-all" title="最小化">
              <span class="text-sm leading-none">_</span>
            </button>
            <button @click="close" class="w-6 h-6 rounded-lg hover:bg-gray-700 flex items-center justify-center text-gray-400 hover:text-gray-200 transition-all" title="关闭">
              <span class="text-sm leading-none">&times;</span>
            </button>
          </div>
        </div>
        <!-- 提示 -->
        <div class="px-4 py-2 bg-purple-500/10 border-b border-purple-500/20 shrink-0">
          <p class="text-[10px] text-purple-300 leading-relaxed">💡 选中公式/代码后点击即可触发即时答疑 · 点击背景最小化</p>
        </div>
        <!-- 选中内容（支持 KaTeX 渲染） -->
        <div class="px-4 py-2.5 bg-gray-800/50 border-b border-gray-700/50 shrink-0">
          <p class="text-[9px] text-gray-500 mb-1">选中内容 <span class="text-gray-600">(行 {{ lineIndex }})</span></p>
          <div class="text-xs text-yellow-300 break-all leading-relaxed" v-html="renderMarkdown(targetText.slice(0, 160))" />
        </div>
        <!-- 对话区域 -->
        <div ref="popupRef" class="flex-1 overflow-y-auto p-4 space-y-2 scrollbar-thin">
          <div v-if="loading && steps.length === 0" class="flex items-center gap-2 text-gray-400 text-xs py-8 justify-center">
            <div class="animate-spin w-3 h-3 border border-purple-500 border-t-transparent rounded-full" />
            正在推导...
          </div>
          <div v-if="error && steps.length === 0" class="text-xs text-red-400 mb-2">{{ error }}</div>
          <div v-for="(step, i) in steps" :key="i"
            class="text-xs leading-relaxed"
            :class="step.startsWith('🙋') ? 'text-blue-300 font-medium' : step.startsWith('💡') ? 'text-purple-300 font-medium' : step.startsWith('📐')||step.startsWith('💻')||step.startsWith('📖') ? 'text-yellow-300 font-medium' : 'text-gray-300'"
            v-html="renderMarkdown(step)">
          </div>
          <div v-if="loading && steps.length > 0" class="flex items-center gap-2 text-gray-500 text-xs py-1">
            <div class="animate-spin w-2.5 h-2.5 border border-purple-400 border-t-transparent rounded-full" />
            思考中...
          </div>
        </div>
        <!-- 追问 -->
        <div class="border-t border-gray-700/50 p-3 shrink-0">
          <div class="flex gap-2">
            <input v-model="followUp" class="flex-1 px-3 py-2 text-xs rounded-xl bg-gray-800 border border-gray-600 text-gray-200 placeholder-gray-500 focus:border-purple-500 focus:ring-1 focus:ring-purple-500 outline-none transition-all" placeholder="输入追问..." @keydown.enter="sendFollowUp" :disabled="sendingFollowUp || loading" />
            <button class="px-3 py-2 text-xs font-semibold rounded-xl bg-purple-600 hover:bg-purple-500 text-white transition-all disabled:opacity-50 disabled:hover:bg-purple-600" :disabled="!followUp.trim() || sendingFollowUp || loading" @click="sendFollowUp">
              {{ sendingFollowUp ? '...' : '追问' }}
            </button>
          </div>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.inline-socratic-popup {
  animation: popIn 0.2s cubic-bezier(0.16, 1, 0.3, 1);
}
@keyframes popIn {
  from { opacity: 0; transform: translateY(-12px) scale(0.96); }
  to { opacity: 1; transform: translateY(0) scale(1); }
}
</style>
