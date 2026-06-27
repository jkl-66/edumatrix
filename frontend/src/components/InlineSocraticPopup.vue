<script setup>
/**
 * InlineSocraticPopup.vue — 任务 8.1: 行级/公式悬浮苏格拉底即时答疑
 * v3: 支持多轮对话 - 追问输入框 + 对话历史 + 真实 LLM 调用
 */
import { ref, onMounted, nextTick } from 'vue'
import { socraticExplain } from '../api'

const emit = defineEmits(['close'])

const props = defineProps({
  targetText: { type: String, default: '' },
  contextBefore: { type: String, default: '' },
  contextAfter: { type: String, default: '' },
  lineIndex: { type: Number, default: 0 },
  messageIndex: { type: Number, default: -1 },
  studentId: { type: String, default: 'demo-student' },
})

const visible = ref(true)
const steps = ref([])
const loading = ref(false)
const error = ref('')
const followUp = ref('')
const sendingFollowUp = ref(false)
const popupRef = ref(null)

// 对话历史（用于多轮追问上下文）
const conversationHistory = ref('')

async function fetchExplanation(followUpText = '') {
  loading.value = true
  error.value = ''
  try {
    const result = await socraticExplain({
      target_text: props.targetText,
      context_before: props.contextBefore,
      context_after: props.contextAfter,
      student_id: props.studentId,
      follow_up: followUpText,
      history: conversationHistory.value,
    })
    if (result.status === 'success' || result.status === 'fallback') {
      const content = result.content || ''
      const newSteps = content.split('\n').filter(line => line.trim())
      if (followUpText) {
        // 多轮：追加用户追问和AI回答
        steps.value.push('', `🙋 你: ${followUpText}`, '')
        steps.value.push(...newSteps)
      } else {
        steps.value = newSteps
      }
      // 更新对话历史
      if (followUpText) {
        conversationHistory.value += `\n学生: ${followUpText}\n导师: ${content}`
      } else {
        conversationHistory.value = `导师: ${content}`
      }
    }
  } catch (e) {
    error.value = e.message || '请求失败'
    if (!followUpText) {
      steps.value = generateFallback(props.targetText)
    }
  }
  loading.value = false
}

function generateFallback(text) {
  if (!text) return ['无法识别目标内容']
  const lines = []
  const isFormula = text.includes('\\frac') || text.includes('\\partial') || text.includes('$$')
  const isCode = text.includes('def ') || text.includes('import ') || text.includes('class ')
  if (isFormula) {
    lines.push('📐 这是一个数学表达式')
    if (text.includes('\\frac')) lines.push('📝 分数形式: \\frac{分子}{分母}')
    if (text.includes('\\partial')) lines.push('🎯 偏导符号 ∂ 表示偏导数')
    lines.push('', '💡 可追问: "每个符号表示什么？"')
  } else if (isCode) {
    lines.push('💻 这是一段代码语句')
    if (text.includes('def ')) lines.push('📦 函数定义: def 关键字声明代码块')
    else if (text.includes('import ')) lines.push('📚 import 用于引入外部库')
    lines.push('', '💡 可追问: "参数和返回值是什么？"')
  } else {
    lines.push('📖 选取内容: "' + text.slice(0, 60) + '"', '💡 可在下方输入框继续追问')
  }
  return lines
}

onMounted(async () => {
  await nextTick()
  await fetchExplanation()
})

async function sendFollowUp() {
  const text = followUp.value.trim()
  if (!text || sendingFollowUp.value) return
  sendingFollowUp.value = true
  followUp.value = ''
  await fetchExplanation(text)
  sendingFollowUp.value = false
  await nextTick()
  // 滚动到底部
  if (popupRef.value) popupRef.value.scrollTop = popupRef.value.scrollHeight
}

function close() {
  visible.value = false
  emit('close')
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
    <div v-if="visible" class="fixed inset-0 z-50 flex items-start justify-center pt-20" @click.self="close">
      <div
        class="inline-socratic-popup bg-gray-900 border border-gray-700 rounded-lg shadow-2xl w-[460px] max-h-[70vh] flex flex-col"
        @click.stop>
        <!-- 头部 -->
        <div class="flex items-center justify-between px-4 py-3 border-b border-gray-700 shrink-0">
          <span class="text-xs font-semibold text-purple-400">🧠 苏格拉底即时答疑</span>
          <button @click="close" class="text-gray-400 hover:text-white text-sm leading-none">&times;</button>
        </div>
        <!-- 被选中的内容 -->
        <div class="px-4 py-2 bg-gray-800/50 border-b border-gray-700 shrink-0">
          <p class="text-[10px] text-gray-500 mb-1">选中内容 (行 {{ lineIndex }})</p>
          <code class="text-xs text-yellow-300 break-all">{{ targetText.slice(0, 80) }}</code>
        </div>
        <!-- 对话区域 -->
        <div ref="popupRef" class="flex-1 overflow-y-auto p-4 space-y-2">
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
        <!-- 追问输入区 -->
        <div class="border-t border-gray-700 p-3 shrink-0">
          <div class="flex gap-2">
            <input v-model="followUp" class="flex-1 px-3 py-2 text-xs rounded-lg bg-gray-800 border border-gray-600 text-gray-200 placeholder-gray-500 focus:border-purple-500 focus:ring-1 focus:ring-purple-500 outline-none transition-all" placeholder="输入追问..." @keydown.enter="sendFollowUp" :disabled="sendingFollowUp || loading" />
            <button class="px-3 py-2 text-xs font-semibold rounded-lg bg-purple-600 hover:bg-purple-700 text-white transition-all disabled:opacity-50" :disabled="!followUp.trim() || sendingFollowUp || loading" @click="sendFollowUp">
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
  animation: slideDown 0.2s ease-out;
}
@keyframes slideDown {
  from { opacity: 0; transform: translateY(-8px); }
  to { opacity: 1; transform: translateY(0); }
}
</style>
