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
import { computed, watch, ref, nextTick, onMounted, useId } from 'vue'

const props = defineProps({
  text: { type: String, default: '' },
  type: { type: String, default: '' },
  conceptName: { type: String, default: '' },
  preserveContent: { type: Boolean, default: false },
})

const emit = defineEmits(['rendered'])
const rootRef = ref(null)
const diagramId = useId()
let diagramSequence = 0

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
    const fenceMatch = remaining.match(/^```([A-Za-z0-9_+#.-]*)\s*\n?/)
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
    
    // Both common display-math delimiters occur in live model answers.
    const mathMatch = remaining.match(/^(?:\$\$[\s\S]*?\$\$|\\\[[\s\S]*?\\\])/)
    if (mathMatch) {
      const seg = new Segment(BlockType.MATH_BLOCK, mathMatch[0], segIndex)
      seg.closed = true
      segments.push(seg)
      pos += mathMatch[0].length
      segIndex++
      continue
    }
    
    // --- 检测未闭合的 $$ (流式进行中) ---
    if (remaining.startsWith('$$') || remaining.startsWith('\\[')) {
      // 找闭合标记
      const closePos = remaining.indexOf(remaining.startsWith('$$') ? '$$' : '\\]', 2)
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
    const marker = /```|`[^`\n]*`|(?<!\$)\$\$(?!\$)|\\\[/g
    let match
    let nextSpecial = -1
    while ((match = marker.exec(remaining))) {
      if (match[0].startsWith('`') && !match[0].startsWith('```')) continue
      nextSpecial = match.index
      break
    }
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

async function renderMermaidDiagrams() {
  if (!rootRef.value || !window.mermaid) return
  const elements = rootRef.value.querySelectorAll('.inc-mermaid:not([data-processed])')
  for (const el of elements) {
    el.dataset.processed = 'pending'
    try {
      const code = normalizeMindmapCode(decodeURIComponent(el.dataset.code || ''))
      // Keep Mermaid's temporary SVG (including parse errors) inside this block.
      const { svg, bindFunctions } = await window.mermaid.render(`inc-${diagramId}-${++diagramSequence}`, code, el)
      if (!rootRef.value?.contains(el)) continue
      el.innerHTML = svg
      bindFunctions?.(el)
      el.dataset.processed = 'true'
    } catch (e) {
      el.textContent = '这张图暂时未能绘制，请结合下方讲解继续学习。'
      el.dataset.processed = 'failed'
      console.warn('[IncrementalRenderer] Mermaid render error:', e)
    }
  }
}

function normalizeMindmapCode(code) {
  if (!/^\s*mindmap\b/i.test(code)) return code
  return code.split('\n').map((line) => {
    const label = line.trim()
    if (!label || /^(?:mindmap\b|%%|::)/i.test(label) || !/[()[\]{}]/.test(label)) return line
    // Preserve explicit Mermaid node shapes. Plain teaching labels such as
    // "sensor[:,1] 振动列" need quoting so brackets remain visible text.
    const shaped = /^(?:[^()[\]{}]+)?(?:\(\(.*\)\)|\(.*\)|\[.*\]|\{\{.*\}\}|\)\).*\(\(|\).*\(|-\).*\(-)$/
    if (shaped.test(label)) return line
    const quoted = label.replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    return `${line.match(/^\s*/)[0]}["${quoted}"]`
  }).join('\n')
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
    ? `<div class="inc-math-fallback">${escapeHtml(cleanMath)}</div>`
    : `<span class="inc-math-inline">${escapeHtml(cleanMath)}</span>`
}

// 渲染行内 Markdown。先把代码和公式替换成占位符，避免后续强调/链接
// 规则误处理其中的字符；所有用户文本在进入这里前都经过 escapeHtml。
function renderInlineMarkdown(content) {
  let html = escapeHtml(String(content || ''))
  const placeholders = []
  const placeholder = (value) => {
    const token = `\u0000inc-inline-${placeholders.length}\u0000`
    placeholders.push(value)
    return token
  }

  html = html.replace(/`([^`\n]+)`/g, (_, code) => (
    placeholder(`<code class="inc-inline-code">${code}</code>`)
  ))
  html = html.replace(/\\\((.+?)\\\)/g, (_, math) => (
    placeholder(renderMath(math.trim(), false))
  ))
  html = html.replace(/\$([^$\n]+?)\$/g, (_, math) => (
    placeholder(renderMath(math.trim(), false))
  ))
  // Plain teaching formulas also use Python-style multiplication/powers.
  // Keep these operators literal; two separate products are not emphasis.
  html = html.replace(/(?<=[A-Za-z0-9_\u0370-\u03ff)\]])\*{1,2}(?=[A-Za-z0-9_\u0370-\u03ff(\[])/g,
    operator => placeholder(operator))
  // A suffix such as w* names an optimum. It must not open an italic span
  // ending at the next w*, while explicit *w* emphasis remains supported.
  html = html.replace(/(?<![A-Za-z0-9_*\u0370-\u03ff])([A-Za-z\u0370-\u03ff](?:_[A-Za-z0-9]+)?)\*(?=$|[\s=+−\-，。；：、,;:()\[\]）])/g,
    (_, variable) => variable + placeholder('*'))
  html = html.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, (_, label, href) => (
    `<a class="inc-link" href="${href}" target="_blank" rel="noopener noreferrer">${label}</a>`
  ))
  html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
  html = html.replace(/~~(.+?)~~/g, '<del>$1</del>')
  html = html.replace(/(?<!\*)\*(\S(?:[^*\n]*?\S)?)\*(?!\*)/g, '<em>$1</em>')

  return html.replace(/\u0000inc-inline-(\d+)\u0000/g, (_, index) => placeholders[Number(index)] || '')
}

// 渲染普通文本。这里只实现回答中实际使用的 Markdown 子集，避免引入
// 第二套 Markdown 依赖，同时保持流式分段的稳定 key 和安全转义。
function renderTextBlock(content, preserveContent = false) {
  if (!content) return ''

  const learnerText = preserveContent ? String(content) : String(content)
    .replace(/^\s*<details\b[^>]*>\s*/gim, '')
    .replace(/<\/details>\s*$/gim, '')
    .replace(/^\s*<summary\b[^>]*>(.*?)<\/summary>\s*$/gim, '### $1\n')
    .replace(/(?:运行|模型|生成|回答)模式\s*[:：]?\s*[A-Za-z0-9_.-]+/gi, '')
    .replace(/(?:知识点\s*)?(?:内部编号|哈希|指纹)\s*[:：]?\s*[A-Za-z0-9_.-]*/gi, '')
    .replace(/依据课程来源|根据课程来源|基于课程来源/g, '')
    .replace(/本地确定性演示/g, '可复现演示')
    .replace(/本地确定性/g, '可复现')
    .replace(/上下文重点/g, '本轮重点')
    .replace(/冻结课程来源/g, '已选课程内容')
    .replace(/课程来源/g, '课程内容')
    .replace(/来源版本/g, '材料范围')
    .replace(/来源片段/g, '相关片段')
    .replace(/证据不足/g, '现有信息还不够')
    .replace(/证据链/g, '核对过程')
    .replace(/学习记录/g, '学习记录')
    .replace(/评分证据/g, '评分记录')
    .replace(/证据/g, '可核对信息')
    .replace(/来源/g, '参考材料')
    .replace(/课文/g, '学习内容')
    .replace(/依据/g, '理由')
    .replace(/约束条件/g, '限制条件')
    .replace(/约束/g, '限制')
    .replace(/\b(?:demo-)?(?:kp|source|event|trace|run|claim|chat|task)-[a-z0-9-]{4,}\b/gi, '')
    .replace(/\bf\d+\.[a-z0-9_.-]+\.v\d+\b/gi, '')
    .replace(/\b[a-f0-9]{24,}\b/gi, '')
    .replace(/\b(?:deterministic_local|llm_grounded|reasoning_content)\b/gi, '')
    .replace(/\b(?:source[_ -]?ref(?:[_ -]?id)?|knowledge[_ -]?point[_ -]?id|context[_ -]?fingerprint|content[_ -]?hash|rubric[_ -]?version|generation[_ -]?mode|run[_ -]?id|message[_ -]?id|event[_ -]?id)\b\s*[:=：]?\s*[A-Za-z0-9_.:-]*/gi, '')
    .replace(/\[(?:S|A)\d+\]|\[source[_ -]?ref\]/gi, '')
  const lines = learnerText.replace(/\r\n?/g, '\n').split('\n')
  const blocks = []
  let paragraph = []
  let listType = ''
  let listItems = []
  let quoteLines = []
  let tableRows = []

  const flushParagraph = () => {
    if (!paragraph.length) return
    const body = paragraph.map(line => renderInlineMarkdown(line)).join('<br>')
    blocks.push(`<p class="inc-paragraph">${body}</p>`)
    paragraph = []
  }
  const flushList = () => {
    if (!listItems.length) return
    const tag = listType === 'ol' ? 'ol' : 'ul'
    const className = listType === 'ol' ? 'inc-list inc-list--ordered' : 'inc-list'
    const marker = listType === 'ol' ? (index) => `${index + 1}.` : () => '•'
    blocks.push(`<${tag} class="${className}">${listItems.map((item, index) => (
      `<li><span class="inc-list-marker" aria-hidden="true">${marker(index)}</span><span class="inc-list-content">${item}</span></li>`
    )).join('')}</${tag}>`)
    listType = ''
    listItems = []
  }
  const flushQuote = () => {
    if (!quoteLines.length) return
    const body = quoteLines.map(line => renderInlineMarkdown(line)).join('<br>')
    blocks.push(`<blockquote class="inc-blockquote">${body}</blockquote>`)
    quoteLines = []
  }
  const flushTable = () => {
    if (!tableRows.length) return
    const head = tableRows[0]
    const body = tableRows.slice(1).filter(row => !row.every(cell => /^:?-{3,}:?$/.test(cell.trim())))
    const rowHtml = (row, tag) => `<tr>${row.map(cell => `<${tag}>${renderInlineMarkdown(cell.trim())}</${tag}>`).join('')}</tr>`
    blocks.push(`<div class="inc-table-wrap"><table class="inc-table"><thead>${rowHtml(head, 'th')}</thead>${body.length ? `<tbody>${body.map(row => rowHtml(row, 'td')).join('')}</tbody>` : ''}</table></div>`)
    tableRows = []
  }
  const flushAll = () => {
    flushParagraph()
    flushList()
    flushQuote()
    flushTable()
  }

  for (const rawLine of lines) {
    const line = rawLine.trimEnd()
    const heading = line.match(/^\s{0,3}(#{1,6})\s+(.+?)\s*#*\s*$/)
    const unordered = line.match(/^\s*[-*+]\s+(.+)$/)
    const ordered = line.match(/^\s*\d+[.)]\s+(.+)$/)
    const quote = line.match(/^\s*>\s?(.*)$/)
    const divider = /^\s*(?:\*\s*){3,}$|^\s*(?:-\s*){3,}$|^\s*(?:_\s*){3,}$/.test(line)
    const table = line.trim().startsWith('|') && line.trim().endsWith('|')

    if (!line.trim()) {
      flushAll()
      continue
    }
    if (table) {
      flushParagraph(); flushList(); flushQuote()
      // Literal pipes in inline formulas/code are content, not column edges.
      const protectedCells = []
      const row = line.trim().slice(1, -1).replace(/`[^`]*`|\\\([^\n]*?\\\)|\$[^$\n]*\$|\\\|/g, value => {
        const key = `\u0000cell-${protectedCells.length}\u0000`
        protectedCells.push(value === '\\|' ? '|' : value)
        return key
      })
      tableRows.push(row.split('|').map(cell => cell.replace(/\u0000cell-(\d+)\u0000/g, (_, index) => protectedCells[Number(index)])))
      continue
    }
    if (tableRows.length) flushTable()
    if (heading) {
      flushAll()
      const level = Math.min(heading[1].length, 4)
      blocks.push(`<h${level} class="inc-heading inc-heading--${level}">${renderInlineMarkdown(heading[2])}</h${level}>`)
      continue
    }
    if (divider) {
      flushAll()
      blocks.push('<hr class="inc-divider">')
      continue
    }
    if (unordered || ordered) {
      flushParagraph()
      flushQuote()
      const nextType = ordered ? 'ol' : 'ul'
      if (listType && listType !== nextType) flushList()
      listType = nextType
      listItems.push(renderInlineMarkdown((ordered || unordered)[1]))
      continue
    }
    if (quote) {
      flushParagraph()
      flushList()
      quoteLines.push(quote[1])
      continue
    }

    flushList()
    flushQuote()
    paragraph.push(line)
  }

  flushAll()
  return blocks.join('')
}

// 渲染代码块
function renderCodeBlock(content, lang) {
  const escaped = escapeHtml(content)
  return `<div class="code-block-wrapper">
    ${lang ? `<div class="code-block-heading">
      <span>${escapeHtml(lang)}</span>
    </div>` : ''}
    <pre><code>${escaped}</code></pre>
  </div>`
}

// 渲染行间公式
function renderMathBlock(content) {
  const math = content.replace(/^(?:\$\$|\\\[)/, '').replace(/(?:\$\$|\\\])$/, '').trim()
  return `<div class="math-block">
    ${renderMath(math, true)}
  </div>`
}

// 渲染 Mermaid 块
function renderMermaidBlock(content) {
  const escapedCode = encodeURIComponent(content.trim())
  return `<div class="mermaid-block">
    <div class="inc-mermaid" data-code="${escapedCode}">
      <div class="inc-mermaid-loading">
        <span class="inc-spinner"></span>
        <span>绘制思维导图中...</span>
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
  return `<div class="skeleton-block">
    <span class="inc-spinner"></span>
    <span>${labels[type] || '内容加载中...'}</span>
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
        html = renderTextBlock(seg.content, props.preserveContent)
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
  <div ref="rootRef" class="incremental-md-renderer">
    <template v-for="block in renderedBlocks" :key="block.key">
      <div :class="['inc-block', block.cls]" v-html="block.html" />
    </template>
  </div>
</template>

<style scoped>
.incremental-md-renderer {
  width: 100%;
  color: var(--color-text);
  font-size: 15px;
  line-height: 1.75;
}

.incremental-md-renderer :deep(.inc-paragraph) {
  margin: 0 0 12px;
}

.incremental-md-renderer :deep(.inc-paragraph:last-child) {
  margin-bottom: 0;
}

.incremental-md-renderer :deep(.inc-table-wrap) {
  margin: 14px 0;
  overflow-x: auto;
  border: 1px solid var(--color-border);
  border-radius: 8px;
}

.incremental-md-renderer :deep(.inc-table) {
  width: 100%;
  min-width: 460px;
  border-collapse: collapse;
  background: var(--color-surface);
  font-size: 14px;
  line-height: 1.55;
}

.incremental-md-renderer :deep(.inc-table th),
.incremental-md-renderer :deep(.inc-table td) {
  padding: 9px 12px;
  border-bottom: 1px solid #e5eaeb;
  text-align: left;
  vertical-align: top;
}

.incremental-md-renderer :deep(.inc-table th) {
  color: #17384a;
  background: #f1f5f5;
  font-weight: 700;
  white-space: nowrap;
}

.incremental-md-renderer :deep(.inc-heading) {
  margin: 22px 0 10px;
  color: #132b39;
  font-weight: 680;
  line-height: 1.35;
  letter-spacing: 0;
}

.incremental-md-renderer :deep(.inc-heading:first-child) {
  margin-top: 2px;
}

.incremental-md-renderer :deep(.inc-heading--1) {
  font-size: 1.28rem;
}

.incremental-md-renderer :deep(.inc-heading--2) {
  font-size: 1.16rem;
}

.incremental-md-renderer :deep(.inc-heading--3),
.incremental-md-renderer :deep(.inc-heading--4) {
  font-size: 1rem;
}

.incremental-md-renderer :deep(.inc-list) {
  margin: 8px 0 16px;
  padding-left: 0;
  list-style: none;
}

.incremental-md-renderer :deep(.inc-list li) {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding-left: 0;
}

.incremental-md-renderer :deep(.inc-list li + li) {
  margin-top: 7px;
}

.incremental-md-renderer :deep(.inc-list-marker) {
  flex: 0 0 20px;
  color: var(--color-text-muted);
  text-align: right;
  font-weight: 600;
}

.incremental-md-renderer :deep(.inc-list-content) {
  min-width: 0;
  flex: 1;
}

.incremental-md-renderer :deep(.inc-blockquote) {
  margin: 14px 0;
  border-left: 3px solid #9aabb2;
  border-radius: 0 8px 8px 0;
  padding: 10px 14px;
  color: #4a5b63;
  background: var(--color-surface-subtle);
}

.incremental-md-renderer :deep(.inc-divider) {
  margin: 18px 0;
  border: 0;
  border-top: 1px solid var(--color-border);
}

.incremental-md-renderer :deep(.inc-inline-code) {
  border: 1px solid var(--color-border);
  border-radius: 4px;
  padding: 2px 5px;
  color: #17384a;
  background: #f1f5f5;
  font-family: var(--font-mono);
  font-size: 0.91em;
}

.incremental-md-renderer :deep(.inc-link) {
  color: #315c7d;
  text-decoration: underline;
  text-decoration-thickness: 1px;
  text-underline-offset: 2px;
}

.incremental-md-renderer :deep(del) {
  color: #7d8588;
}

.incremental-md-renderer :deep(.inc-math-inline) {
  display: inline-block;
  border: 1px solid var(--color-border);
  border-radius: 4px;
  padding: 0 4px;
  background: var(--color-surface-subtle);
  font-family: var(--font-display);
  font-size: 14px;
}

.incremental-md-renderer :deep(.inc-math-fallback),
.incremental-md-renderer :deep(.math-block) {
  margin: 14px 0;
  overflow-x: auto;
  border: 1px solid var(--color-border);
  border-radius: 8px;
  padding: 14px 16px;
  background: var(--color-surface-subtle);
  text-align: center;
  font-family: var(--font-display);
  font-size: 14px;
}

.incremental-md-renderer :deep(.math-block .katex) {
  font-size: 1.05em;
}

.incremental-md-renderer :deep(.code-block-wrapper) {
  margin: 14px 0;
  overflow: hidden;
  border: 1px solid var(--color-text);
  border-radius: 8px;
  background: var(--color-text);
}

.incremental-md-renderer :deep(.code-block-heading) {
  display: flex;
  min-height: 38px;
  align-items: center;
  padding: 0 14px;
  border-bottom: 1px solid var(--color-text-secondary);
  color: var(--color-border-strong);
  background: var(--color-text);
  font-family: var(--font-mono);
  font-size: 14px;
}

.incremental-md-renderer :deep(.code-block-wrapper pre) {
  margin: 0;
  overflow-x: auto;
  padding: 16px;
  color: var(--color-surface-subtle);
  background: var(--color-text);
  font-family: var(--font-mono);
  font-size: 14px;
  line-height: 1.7;
  scrollbar-width: thin;
  scrollbar-color: var(--color-text-muted) transparent;
}

.incremental-md-renderer :deep(.mermaid-block) {
  margin: 14px 0;
  max-width: 100%;
  overflow-x: auto;
  border: 1px solid var(--color-border);
  border-radius: 8px;
  padding: 16px;
  background: var(--color-surface);
}

.incremental-md-renderer :deep(.inc-mermaid) {
  display: flex;
  width: 100%;
  justify-content: center;
}

.incremental-md-renderer :deep(.inc-mermaid-loading),
.incremental-md-renderer :deep(.skeleton-block) {
  display: flex;
  min-height: 48px;
  align-items: center;
  justify-content: center;
  gap: 9px;
  color: var(--color-text-muted);
  font-size: 14px;
}

.incremental-md-renderer :deep(.skeleton-block) {
  margin: 10px 0;
  justify-content: flex-start;
  border: 1px dashed var(--color-border-strong);
  border-radius: 8px;
  padding: 12px 14px;
  background: var(--color-surface-subtle);
}

.incremental-md-renderer :deep(.inc-spinner) {
  width: 16px;
  height: 16px;
  flex: 0 0 16px;
  border: 2px solid var(--color-border-strong);
  border-top-color: var(--color-text);
  border-radius: 50%;
  animation: incSpin .8s linear infinite;
}

.inc-block {
  animation: incFadeIn 0.15s ease-out;
}

@keyframes incSpin {
  to { transform: rotate(360deg); }
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
