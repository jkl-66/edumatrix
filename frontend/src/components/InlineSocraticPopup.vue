<script setup>
/**
 * InlineSocraticPopup.vue — v5: 智能即时追问悬浮舱
 * 支持亮暗自适应毛玻璃风格，多轮对话气泡渲染，高解析 Markdown/KaTeX 渲染，以及一键就地追问。
 */
import { ref, onMounted, nextTick, watch } from 'vue'
import { socraticExplainStream } from '../api'
import { Play, Sparkles, User, X, Minimize2, Send, HelpCircle, Loader2 } from '@lucide/vue'

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
const messages = ref([]) // { role: 'user'|'assistant', content: '...' }
const loading = ref(false)
const error = ref('')
const followUp = ref('')
const sendingFollowUp = ref(false)
const popupRef = ref(null)
const conversationHistory = ref('')

onMounted(async () => {
  visible.value = true
})

watch(() => props.targetText, async (newVal) => {
  if (newVal) {
    minimized.value = false
    messages.value = []
    conversationHistory.value = ''
    followUp.value = ''
  }
})

let streamController = null

const popupPosition = ref({ x: null, y: null })
const isDragging = ref(false)
const dragStart = { x: 0, y: 0 }

function startDrag(e) {
  if (e.target.closest('button') || e.target.closest('input')) return
  isDragging.value = true
  
  const el = e.currentTarget.closest('.inline-socratic-popup')
  if (el) {
    const rect = el.getBoundingClientRect()
    popupPosition.value.x = rect.left
    popupPosition.value.y = rect.top
  }
  
  dragStart.x = e.clientX - (popupPosition.value.x || 0)
  dragStart.y = e.clientY - (popupPosition.value.y || 0)
  
  document.addEventListener('mousemove', onDrag)
  document.addEventListener('mouseup', stopDrag)
}

function onDrag(e) {
  if (!isDragging.value) return
  popupPosition.value.x = e.clientX - dragStart.x
  popupPosition.value.y = e.clientY - dragStart.y
}

function stopDrag() {
  isDragging.value = false
  document.removeEventListener('mousemove', onDrag)
  document.removeEventListener('mouseup', stopDrag)
}

async function fetchExplanation(followUpText = '') {
  loading.value = true
  error.value = ''
  
  if (followUpText) {
    messages.value.push({ role: 'user', content: followUpText })
  }
  
  // 压入一个空的 AI 回复占位符
  messages.value.push({ role: 'assistant', content: '' })
  const assistantMsgIndex = messages.value.length - 1
  
  let accumulatedContent = ''
  
  streamController = socraticExplainStream({
    target_text: props.targetText,
    context_before: props.contextBefore,
    context_after: props.contextAfter,
    student_id: props.studentId,
    follow_up: followUpText,
    history: conversationHistory.value,
  },
  (token) => {
    accumulatedContent += token
    messages.value[assistantMsgIndex].content = accumulatedContent
    nextTick(() => {
      if (popupRef.value) popupRef.value.scrollTop = popupRef.value.scrollHeight
    })
  },
  (fullContent, data) => {
    if (followUpText) {
      conversationHistory.value += `\n学生: ${followUpText}\n导师: ${fullContent}`
    } else {
      conversationHistory.value = `导师: ${fullContent}`
    }
    loading.value = false
    streamController = null
  },
  (err) => {
    error.value = err.message || '请求失败'
    if (!followUpText) {
      messages.value[assistantMsgIndex].content = generateFallback(props.targetText)
    }
    loading.value = false
    streamController = null
  })
}

function generateFallback(text) {
  if (!text) return '无法识别当前选中的内容。'
  const isFormula = /\\[a-zA-Z]|\\frac|\\partial|\$\$/.test(text)
  const isCode = /def |import |class |\bfor\b|\bif\b|return /.test(text)
  if (isFormula) {
    return '📐 **数学表达式解析**\n\n该公式涉及复杂的数理推导，您可以尝试追问：\n- "这个符号在此公式中代表什么物理意义？"\n- "如何对这个公式的各项进行展开演算？"'
  } else if (isCode) {
    return '💻 **代码片段解析**\n\n该代码包含特定控制流与算子，您可以尝试追问：\n- "这段代码的时间复杂度和执行逻辑是什么？"\n- "这里的变量在反向传播时是如何进行梯度流转的？"'
  } else {
    return `📖 **概念概念解析**\n\n关于您选中的段落：\n> ${text.slice(0, 60)}...\n\n您可以直接在下方输入您的任何追问，伴学助教将实时启发式引导解答。`
  }
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
  emit('close')
}

// 高保真 Markdown / KaTeX 解析渲染函数（与主 Chat.vue 渲染引擎对齐）
function renderMarkdown(text) {
  if (!text) return ''

  let cleaned = text.trim()

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

  // Math extraction
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

  // Format inline text styles
  html = html
    .replace(/\*\*([^*]+)\*\*/g, '<strong class="font-bold text-slate-900 dark:text-slate-100">$1</strong>')
    .replace(/\*([^*]+)\*/g, '<em class="italic text-slate-800 dark:text-slate-200">$1</em>')
    .replace(/`([^`\n]+)`/g, '<code class="px-1.5 py-0.5 bg-slate-100 dark:bg-slate-800 text-rose-600 dark:text-rose-400 rounded font-mono text-xs font-medium">$1</code>')
    .replace(/\n/g, '<br />')

  // Render Math function
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
    return display
      ? `<div class="my-2.5 p-3 bg-slate-100 dark:bg-slate-800/80 border border-slate-200 dark:border-slate-700/50 rounded-xl text-center font-serif text-xs overflow-x-auto text-slate-800 dark:text-slate-200">${math}</div>`
      : `<span class="font-serif italic bg-slate-100 dark:bg-slate-800/80 px-1 py-0.5 rounded text-xs text-slate-800 dark:text-slate-200">${math}</span>`
  }



  // Restore Math tokens and layout blocks
  blockMath.forEach((item, idx) => {
    html = html.split(`@@BLOCKMATHTOKEN${idx}@@`).join(renderMath(item.math, true))
  })
  inlineMath.forEach((item, idx) => {
    html = html.split(`@@INLINEMATHTOKEN${idx}@@`).join(renderMath(item.math, false))
  })
  layoutBlocks.forEach((block, idx) => {
    html = html.split(`@@LAYOUTTOKEN${idx}@@`).join(block)
  })

  return html
}
</script>

<template>
  <Teleport to="body">
    <!-- 浮动图标（最小化状态） -->
    <div v-if="minimized && activeTab === 'chat' && rightPanelCollapsed"
      class="fixed bottom-[216px] right-6 z-50 group"
      @click="restore">
      <div class="w-12 h-12 rounded-full bg-blue-600 dark:bg-blue-500 shadow-lg flex items-center justify-center cursor-pointer hover:bg-blue-500 hover:scale-110 transition-all hover:shadow-xl border border-white/20">
        <Sparkles class="text-white w-5 h-5 animate-pulse" />
      </div>
      <!-- Tooltip -->
      <div class="absolute right-full mr-3 top-1/2 -translate-y-1/2 scale-75 opacity-0 group-hover:scale-100 group-hover:opacity-100 transition-all duration-200 bg-slate-900/90 text-white text-xs px-2.5 py-1.5 rounded-lg border border-slate-800 shadow-xl pointer-events-none whitespace-nowrap">
        展开即时追问 (Follow-up)
      </div>
    </div>

    <!-- 主弹窗悬浮舱 (毛玻璃设计系统，取消背景遮罩，支持 Header 拖拽) -->
    <div 
      v-if="visible && !minimized && activeTab === 'chat'" 
      class="fixed z-50 inline-socratic-popup bg-white/90 dark:bg-slate-950/90 backdrop-blur-md border border-slate-200/60 dark:border-slate-850 rounded-2xl shadow-2xl w-[92vw] md:w-[450px] h-[72vh] max-h-[580px] flex flex-col overflow-hidden select-none"
      :style="popupPosition.x !== null ? { left: popupPosition.x + 'px', top: popupPosition.y + 'px', right: 'auto', bottom: 'auto' } : { right: '24px', top: '100px' }"
    >
      <!-- 头部 Header (按住拖拽) -->
      <div 
        @mousedown="startDrag"
        class="flex items-center justify-between px-4 py-3 border-b border-slate-250/50 dark:border-slate-850 shrink-0 bg-slate-50/50 dark:bg-slate-900/40 cursor-move select-none"
      >
        <div class="flex items-center gap-2">
          <Sparkles :size="16" class="text-blue-500 dark:text-blue-400" />
          <span class="text-xs font-bold text-slate-800 dark:text-slate-200">即时追问舱</span>
          <span class="px-1.5 py-0.5 text-[9px] font-semibold rounded bg-blue-100/60 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400 border border-blue-200/50 dark:border-blue-800/40">浮动</span>
        </div>
        <div class="flex items-center gap-1.5">
          <button @click="minimize" class="w-6 h-6 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-850 flex items-center justify-center text-slate-400 hover:text-slate-600 dark:hover:text-slate-200 transition-all border-none bg-transparent cursor-pointer" title="最小化">
            <Minimize2 :size="14" />
          </button>
          <button @click="close" class="w-6 h-6 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-850 flex items-center justify-center text-slate-400 hover:text-slate-600 dark:hover:text-slate-200 transition-all border-none bg-transparent cursor-pointer" title="关闭">
            <X :size="16" />
          </button>
        </div>
      </div>

      <!-- 选中内容 Context (KaTeX) -->
      <div class="px-4 py-3 bg-slate-50/30 dark:bg-slate-900/10 border-b border-slate-200/60 dark:border-slate-850 shrink-0">
        <p class="text-[10px] font-semibold text-slate-400 dark:text-slate-500 uppercase tracking-wider mb-1.5">选中的追问内容</p>
        <div class="text-xs text-slate-700 dark:text-slate-350 p-2.5 rounded-lg bg-slate-100/50 dark:bg-slate-900 border border-slate-200/60 dark:border-slate-800 max-h-[220px] overflow-y-auto break-all font-mono leading-relaxed" v-html="renderMarkdown(targetText)" />
      </div>

      <!-- 对话展示区 messages bubbles -->
      <div ref="popupRef" class="flex-1 overflow-y-auto p-4 space-y-4 scrollbar-thin bg-white/30 dark:bg-slate-950/30">
        
        <!-- Welcome Guide when no messages yet -->
        <div v-if="messages.length === 0" class="flex flex-col items-center justify-center h-full text-center p-6 animate-fade-in select-none">
          <div class="w-12 h-12 rounded-2xl bg-blue-50 dark:bg-blue-900/20 border border-blue-100 dark:border-blue-800 flex items-center justify-center mb-3">
            <Sparkles :size="20" class="text-blue-600 dark:text-blue-400 animate-pulse" />
          </div>
          <h4 class="text-xs font-bold text-slate-800 dark:text-slate-200 mb-1">选区追问就地闭环</h4>
          <p class="text-[10px] text-slate-500 dark:text-slate-400 max-w-[240px] leading-relaxed">
            选中的文本已成功载入为背景上下文。请在下方输入您的具体追问，伴学助教将在本窗口中为您实时推导解答。
          </p>
        </div>

        <div v-for="(msg, i) in messages" :key="i" class="flex flex-col animate-fade-in text-left">
          <!-- User bubble -->
          <div v-if="msg.role === 'user'" class="flex gap-2.5 max-w-[85%] self-end flex-row-reverse text-left">
            <div class="w-7 h-7 rounded-full bg-blue-100 dark:bg-blue-900/40 border border-blue-200/60 dark:border-blue-800 flex items-center justify-center shrink-0">
              <User :size="14" class="text-blue-600 dark:text-blue-400" />
            </div>
            <div class="px-3.5 py-2.5 rounded-2xl rounded-tr-none bg-blue-600 text-white shadow-sm text-xs leading-relaxed text-left">
              {{ msg.content }}
            </div>
          </div>

          <!-- Assistant bubble -->
          <div v-else class="flex gap-2.5 max-w-[85%] self-start text-left">
            <div class="w-7 h-7 rounded-full bg-emerald-100 dark:bg-emerald-900/40 border border-emerald-200/60 dark:border-emerald-800 flex items-center justify-center shrink-0">
              <Sparkles :size="14" class="text-emerald-600 dark:text-emerald-400" />
            </div>
            <div class="flex flex-col space-y-1 text-left">
              <span class="text-[9px] font-semibold text-slate-400 ml-1">伴学助教</span>
              <div class="px-3.5 py-2.5 rounded-2xl rounded-tl-none bg-slate-100/80 dark:bg-slate-900/80 text-slate-700 dark:text-slate-200 border border-slate-200/50 dark:border-slate-800/80 shadow-sm text-xs leading-relaxed break-words overflow-x-auto text-left">
                <div v-if="!msg.content && loading" class="flex items-center gap-1.5 py-1 text-slate-400 text-left">
                  <Loader2 :size="12" class="animate-spin text-blue-500" />
                  正在推导启发思路...
                </div>
                <div v-else v-html="renderMarkdown(msg.content)" />
              </div>
            </div>
          </div>
        </div>

        <div v-if="error" class="text-xs text-red-500 bg-red-50/50 dark:bg-red-950/20 border border-red-200/60 dark:border-red-900/40 rounded-xl p-3 text-center">
          ⚠️ 出现异常: {{ error }}
        </div>
      </div>

      <!-- 底部输入框 Input followUp -->
      <div class="border-t border-slate-200/80 dark:border-slate-850 p-3 shrink-0 bg-slate-50/50 dark:bg-slate-900/40">
        <div class="flex gap-2">
          <input 
            v-model="followUp" 
            class="flex-1 px-3.5 py-2 text-xs rounded-xl bg-white dark:bg-slate-900 border border-slate-250 dark:border-slate-800 text-slate-800 dark:text-slate-200 placeholder-slate-400 focus:border-blue-500 focus:ring-1 focus:ring-blue-500 outline-none transition-all duration-200" 
            placeholder="输入您的追问问题..." 
            @keydown.enter="sendFollowUp" 
            :disabled="sendingFollowUp || loading" 
          />
          <button 
            class="w-8 h-8 rounded-xl bg-blue-600 hover:bg-blue-500 dark:bg-blue-600 dark:hover:bg-blue-500 text-white flex items-center justify-center transition-all shadow-sm active:scale-95 disabled:opacity-50 disabled:active:scale-100 disabled:hover:bg-blue-600 border-none cursor-pointer" 
            :disabled="!followUp.trim() || sendingFollowUp || loading" 
            @click="sendFollowUp"
          >
            <Send :size="14" />
          </button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.inline-socratic-popup {
  animation: popIn 0.25s cubic-bezier(0.16, 1, 0.3, 1);
}
@keyframes popIn {
  from { opacity: 0; transform: translateY(-12px) scale(0.97); }
  to { opacity: 1; transform: translateY(0) scale(1); }
}
</style>
