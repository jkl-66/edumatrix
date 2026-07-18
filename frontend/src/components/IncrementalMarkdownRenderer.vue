<script setup>
/**
 * IncrementalMarkdownRenderer.vue
 * 
 * 任务 1 — 增量式虚拟 DOM (VDOM) 修补的流式 Markdown/公式排版渲染机
 * 
 * 核心设计：
 * 1. 增量解析状态机：将文本按 $$、```、```mermaid 分割为稳定块
 * 2. 稳定 key 渲染：已完成的块用固定 key，Vue VDOM 只 patch 增量部分
 * 3. 骨架屏占位：未闭合的块显示 loading 骨架，闭合后替换为真实渲染
 */
import { computed, watch, ref, nextTick, onMounted } from 'vue'

const props = defineProps({
  text: { type: String, default: '' },
  type: { type: String, default: '' },
  conceptName: { type: String, default: '' },
})

const emit = defineEmits(['rendered'])

// ============================================================
// 1. 增量解析状态机
// ============================================================

// 块类型枚举
const BlockType = {
  TEXT: 'text',
  FENCED_CODE: 'fenced_code',       // ```lang ... ```
  MATH_BLOCK: 'math_block',         // $$ ... $$
  MERMAID_BLOCK: 'mermaid_block',   // ```mermaid ... ```
}

// 单一块的数据结构
class Segment {
  constructor(type, content, index) {
    this.type = type
    this.content = content
    this.index = index           // 全局序号，用作稳定 key
    this.closed = false         // 是否已闭合
    this.lang = ''              // 代码块语言
    this.accumulated = content  // 流式累积的内容
  }
}

/**
 * 把原始文本解析成稳定的块列表
 * 每次调用都会检测增量变化，保留已有块的 key
 */
function parseSegments(text, previousSegments = []) {
  if (!text) return []
  
  const segments = []
  let pos = 0
  let segIndex = 0
  
  // 复用之前的 key 映射 { index: Segment }
  const prevMap = new Map()
  for (const s of previousSegments) {
    prevMap.set(s.index, s)
  }
  
  while (pos < text.length) {
    const remaining = text.slice(pos)
    
    // --- 检测 ```mermaid ... ``` 块 ---
    const mermaidMatch = remaining.match(/^```mermaid\s*\n?/i)
    if (mermaidMatch) {
      const start = pos + mermaidMatch[0].length
      const endTag = remaining.indexOf('```', mermaidMatch[0].length)
      const closed = endTag !== -1
      const endPos = closed ? endTag : remaining.length
      const codeContent = text.slice(start, pos + endPos)
      
      const existing = prevMap.get(segIndex)
      const seg = new Segment(BlockType.MERMAID_BLOCK, codeContent, segIndex)
      seg.closed = closed
      seg.accumulated = existing ? existing.accumulated + codeContent.slice(existing.content.length) : codeContent
      if (closed) seg.accumulated = codeContent
      segments.push(seg)
      
      pos = closed ? pos + endPos + 3 : text.length
      segIndex++
      continue
    }
    
    // --- 检测 ``` (代码块) ---
    const fenceMatch = remaining.match(/^```(\w*)\s*\n?/)
    if (fenceMatch && fenceMatch[0].toLowerCase().includes('mermaid') === false) {
      const start = pos + fenceMatch[0].length
      const endTag = remaining.indexOf('```', fenceMatch[0].length)
      const closed = endTag !== -1
      const endPos = closed ? endTag : remaining.length
      const codeContent = text.slice(start, pos + endPos)
      const lang = fenceMatch[1].toLowerCase()
      
      const seg = new Segment(BlockType.FENCED_CODE, codeContent, segIndex)
      seg.closed = closed
      seg.lang = lang
      seg.accumulated = codeContent
      segments.push(seg)
      
      pos = closed ? pos + endPos + 3 : text.length
      segIndex++
      continue
    }
    
    // --- 检测 $$ ... $$ (行间公式) ---
    const mathMatch = remaining.match(/^\$\$[\s\S]*?\$\$/)
    if (mathMatch) {
      const seg = new Segment(BlockType.MATH_BLOCK, mathMatch[0], segIndex)
      seg.closed = true
      segments.push(seg)
      pos += mathMatch[0].length
      segIndex++
      continue
    }
    
    // --- 检测未闭合的 $$ (流式进行中) ---
    if (remaining.startsWith('$$')) {
      // 找闭合标记
      const closePos = remaining.indexOf('$$', 2)
      if (closePos === -1) {
        // 未闭合，显示公式骨架屏占位
        const seg = new Segment(BlockType.MATH_BLOCK, remaining, segIndex)
        seg.closed = false
        seg.accumulated = remaining
        segments.push(seg)
        pos = text.length
        segIndex++
        continue
      }
    }
    
    // --- 普通文本块：取到下一个特殊标记之前 ---
    const nextSpecial = remaining.search(/```|(?<!\$)\$\$(?!\$)/)
    if (nextSpecial === -1) {
      const seg = new Segment(BlockType.TEXT, remaining, segIndex)
      seg.closed = true
      segments.push(seg)
      pos = text.length
    } else {
      const chunk = remaining.slice(0, nextSpecial)
      const seg = new Segment(BlockType.TEXT, chunk, segIndex)
      seg.closed = true
      segments.push(seg)
      pos += nextSpecial
    }
    segIndex++
  }
  
  return segments
}

// ============================================================
// 2. 渲染逻辑
// ============================================================

// 稳定的分段列表（响应式）
const segments = ref([])
// 存储上一次的分段用于 key 复用
let prevSegments = []

watch(() => props.text, (newText) => {
  const parsed = parseSegments(newText, prevSegments)
  segments.value = parsed
  prevSegments = parsed
}, { immediate: true })

// Mermaid 渲染（在 nextTick 后执行）
watch(segments, () => {
  nextTick(() => {
    renderMermaidDiagrams()
    emit('rendered')
  })
}, { deep: true })

function renderMermaidDiagrams() {
  if (typeof window.mermaid === 'undefined') return
  try {
    const elements = document.querySelectorAll('.inc-mermaid:not([data-processed="true"])')
    elements.forEach(el => {
      try {
        window.mermaid.init(undefined, el)
        el.setAttribute('data-processed', 'true')
      } catch (e) {
        console.warn('[IncrementalRenderer] Mermaid render error:', e)
      }
    })
  } catch (e) {
    console.warn('[IncrementalRenderer] Mermaid bulk render error:', e)
  }
}

// ============================================================
// 3. 单块渲染函数
// ============================================================

// HTML 转义
function escapeHtml(text) {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
}

// KaTeX 行内/行间公式同步流式渲染器
function renderMath(math, display) {
  // 解码可能被转义的 HTML 字符，防止 KaTeX 解析失败
  const cleanMath = math
    .replace(/&amp;/g, '&')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")

  if (window.katex) {
    try {
      return window.katex.renderToString(cleanMath, {
        displayMode: display,
        throwOnError: false,
        trust: true
      })
    } catch (err) {
      console.error('KaTeX streaming render error:', err)
    }
  }
  
  // Fallback if KaTeX is not loaded
  return display 
    ? `<div class="my-3.5 p-4 bg-gray-50/75 border border-gray-100 rounded-xl text-center font-serif text-sm overflow-x-auto select-all shadow-inner text-gray-800">${escapeHtml(cleanMath)}</div>`
    : `<span class="font-serif italic bg-gray-50/75 px-1.5 py-0.5 rounded text-xs select-all text-gray-800 border border-gray-100/50">${escapeHtml(cleanMath)}</span>`
}

// 渲染普通文本（支持行内公式 $...$）
function renderTextBlock(content) {
  if (!content) return ''
  
  let html = escapeHtml(content)
  
  // 行内公式 $...$
  html = html.replace(/\$([^$\n]+?)\$/g, (_, math) => {
    return renderMath(math.trim(), false)
  })
  
  // 段落、换行等基本 Markdown
  html = html
    .replace(/\n\n+/g, '</p><p class="my-1.5">')
    .replace(/\n/g, '<br>')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.+?)\*/g, '<em>$1</em>')
  
  return `<p class="my-1.5">${html}</p>`
}

// 渲染代码块
function renderCodeBlock(content, lang) {
  const escaped = escapeHtml(content)
  return `<div class="code-block-wrapper my-3 rounded-xl overflow-hidden border border-gray-200/80 bg-slate-900 shadow-sm">
    ${lang ? `<div class="flex items-center justify-between px-4 py-1.5 bg-slate-800 border-b border-slate-700/60">
      <span class="text-[10px] font-mono text-slate-400">${escapeHtml(lang)}</span>
    </div>` : ''}
    <pre class="p-4 overflow-x-auto text-xs leading-relaxed text-slate-200 font-mono"><code>${escaped}</code></pre>
  </div>`
}

// 渲染行间公式
function renderMathBlock(content) {
  const math = content.replace(/^\$\$/, '').replace(/\$\$$/, '').trim()
  return `<div class="math-block my-3 py-3 px-4 bg-gray-50/60 rounded-xl border border-gray-100 overflow-x-auto flex justify-center">
    ${renderMath(math, true)}
  </div>`
}

// 渲染 Mermaid 块
function renderMermaidBlock(content) {
  const escapedCode = encodeURIComponent(content.trim())
  return `<div class="mermaid-block my-3 p-4 bg-white border border-gray-200 rounded-xl shadow-sm max-w-full overflow-x-auto">
    <div class="inc-mermaid w-full flex justify-center" data-code="${escapedCode}">
      <div class="flex flex-col items-center justify-center gap-2 py-4 text-gray-400 select-none">
        <div class="w-5 h-5 border-2 border-indigo-400 border-t-transparent rounded-full animate-spin"></div>
        <span class="text-[10px] text-indigo-500 font-semibold animate-pulse">绘制思维导图中...</span>
      </div>
    </div>
  </div>`
}

// 渲染骨架占位（未闭合块）
function renderSkeleton(type) {
  const labels = {
    [BlockType.FENCED_CODE]: '代码块加载中...',
    [BlockType.MATH_BLOCK]: '公式渲染中...',
    [BlockType.MERMAID_BLOCK]: '思维导图绘制中...',
  }
  return `<div class="skeleton-block my-2 p-3 bg-gray-50/80 rounded-xl border border-dashed border-gray-200 animate-pulse flex items-center gap-2">
    <div class="w-4 h-4 rounded-full bg-gray-200 animate-spin"></div>
    <span class="text-[11px] text-gray-400">${labels[type] || '内容加载中...'}</span>
  </div>`
}

// ============================================================
// 4. 组合渲染 — 将分段渲染为 HTML 数组
// ============================================================

const renderedBlocks = computed(() => {
  return segments.value.map(seg => {
    let html = ''
    let cls = ''
    
    switch (seg.type) {
      case BlockType.TEXT:
        html = renderTextBlock(seg.content)
        cls = 'inc-text-block'
        break
      case BlockType.FENCED_CODE:
        html = seg.closed ? renderCodeBlock(seg.content, seg.lang) : renderSkeleton(BlockType.FENCED_CODE)
        cls = seg.closed ? 'inc-code-block' : 'inc-skeleton'
        break
      case BlockType.MATH_BLOCK:
        html = seg.closed ? renderMathBlock(seg.content) : renderSkeleton(BlockType.MATH_BLOCK)
        cls = seg.closed ? 'inc-math-block' : 'inc-skeleton'
        break
      case BlockType.MERMAID_BLOCK:
        html = seg.closed ? renderMermaidBlock(seg.content) : renderSkeleton(BlockType.MERMAID_BLOCK)
        cls = seg.closed ? 'inc-mermaid-block' : 'inc-skeleton'
        break
    }
    
    return { key: `seg-${seg.index}`, html, cls, closed: seg.closed, index: seg.index }
  })
})

// 暴露给父组件：获取最后一个未闭合块索引
function getLastIncompleteIndex() {
  for (let i = segments.value.length - 1; i >= 0; i--) {
    if (!segments.value[i].closed) return i
  }
  return -1
}

// 在挂载后尝试渲染 Mermaid
onMounted(() => {
  nextTick(() => renderMermaidDiagrams())
})

defineExpose({ getLastIncompleteIndex })
</script>

<template>
  <div class="incremental-md-renderer">
    <template v-for="block in renderedBlocks" :key="block.key">
      <div :class="['inc-block', block.cls]" v-html="block.html" />
    </template>
  </div>
</template>

<style scoped>
.incremental-md-renderer {
  width: 100%;
  line-height: 1.6;
}

/* KaTeX 渲染完成后样式 */
.math-block :deep(.katex) {
  font-size: 1.05em;
}

.mermaid-block {
  transition: opacity 0.3s ease;
}

/* 骨架屏过渡 */
.skeleton-block {
  transition: all 0.2s ease;
}

/* 代码块 */
.code-block-wrapper pre {
  scrollbar-width: thin;
  scrollbar-color: #4a5568 transparent;
}

/* 增量块入场动画 */
.inc-block {
  animation: incFadeIn 0.15s ease-out;
}

@keyframes incFadeIn {
  from {
    opacity: 0;
    transform: translateY(2px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}
</style>
