<script setup>
import { ref, computed, onMounted, watch, nextTick, createApp } from 'vue'
import {
  getNotes, createNote, deleteNote, updateNote, aiPolishNote,
  getReviewPlans, createReviewPlan, reviewFlashcard
} from '../api'
import CollapsibleMindmap from '../components/CollapsibleMindmap.vue'
import { useQuizStore } from '../stores/quiz'
import { useRouter } from 'vue-router'
import {
  StickyNote, Plus, Trash2, Tag, Clock, Search, Edit3, Eye, Sparkles, BookOpen,
  Calendar, Download, ArrowRight, Loader2, ChevronRight, X, AlertCircle, HelpCircle, Check, RotateCw
} from '@lucide/vue'

const props = defineProps({ studentId: String })
const quizStore = useQuizStore()
const router = useRouter()

const notes = ref([])
const reviewPlans = ref([])
const loading = ref(true)
const selectedNoteId = ref(null)
const isEditing = ref(false)
const polishLoading = ref(false)

// 过滤和搜索状态
const searchQuery = ref('')
const selectedTags = ref(new Set())
const selectedConcepts = ref(new Set())

// 表单状态（编辑和新建）
const editForm = ref({ content: '', tags: '', concepts: '', source: 'manual' })
const showAddModal = ref(false)
const newForm = ref({ content: '', tags: '', concepts: '', source: 'manual' })

// 闪卡背诵状态
const showAnkiModal = ref(false)
const ankiCard = ref(null) // { concept, question, answer }
const showAnkiAnswer = ref(false)
const ankiLoading = ref(false)

async function load() {
  loading.value = true
  try {
    const data = await getNotes(props.studentId)
    notes.value = Array.isArray(data) ? data : data.notes || []
    
    // 同时加载艾宾浩斯复习计划
    const plansData = await getReviewPlans(props.studentId)
    reviewPlans.value = Array.isArray(plansData) ? plansData : plansData.plans || []
    
    if (notes.value.length > 0 && !selectedNoteId.value) {
      selectedNoteId.value = notes.value[0].id
    }
  } catch (e) {
    console.error('加载笔记数据失败:', e)
  } finally {
    loading.value = false
  }
}

const selectedNote = computed(() => {
  return notes.value.find(n => n.id === selectedNoteId.value) || null
})

// 监听当前选中笔记，同步编辑表单
watch(selectedNote, (newVal) => {
  if (newVal) {
    editForm.value = {
      content: newVal.content,
      tags: (newVal.tags || []).join(', '),
      concepts: (newVal.concepts || []).join(', '),
      source: newVal.source || 'manual'
    }
    isEditing.value = false
    nextTick(() => {
      cleanupCustomMindmaps()
      renderAllDiagrams()
    })
  }
}, { immediate: true })

// 汇总所有提取出的标签和概念
const allTags = computed(() => {
  const tags = new Set()
  notes.value.forEach(n => {
    if (n.tags) n.tags.forEach(t => tags.add(t))
  })
  return Array.from(tags)
})

const allConcepts = computed(() => {
  const concepts = new Set()
  notes.value.forEach(n => {
    if (n.concepts) n.concepts.forEach(c => concepts.add(c))
  })
  return Array.from(concepts)
})

// 过滤后的笔记列表
const filteredNotes = computed(() => {
  return notes.value.filter(n => {
    // 1. 搜索词匹配
    const q = searchQuery.value.toLowerCase()
    const matchQuery = !searchQuery.value.trim() || 
      n.content.toLowerCase().includes(q) ||
      (n.concepts || []).some(c => c.toLowerCase().includes(q)) ||
      (n.tags || []).some(t => t.toLowerCase().includes(q)) ||
      (n.source === '错题本反思' && ('错题集'.includes(q) || '错题'.includes(q)))
    
    // 2. 标签匹配
    const matchTags = selectedTags.value.size === 0 || 
      (n.tags || []).some(t => selectedTags.value.has(t))
      
    // 3. 概念匹配
    const matchConcepts = selectedConcepts.value.size === 0 || 
      (n.concepts || []).some(c => selectedConcepts.value.has(c))
      
    return matchQuery && matchTags && matchConcepts
  })
})

// 获取特定概念的复习计划
const getConceptPlan = (concepts) => {
  if (!concepts || concepts.length === 0) return null
  return reviewPlans.value.find(p => concepts.includes(p.concept)) || null
}

// 标签与概念过滤点击切换
function toggleTagFilter(tag) {
  if (selectedTags.value.has(tag)) {
    selectedTags.value.delete(tag)
  } else {
    selectedTags.value.add(tag)
  }
}

function toggleConceptFilter(concept) {
  if (selectedConcepts.value.has(concept)) {
    selectedConcepts.value.delete(concept)
  } else {
    selectedConcepts.value.add(concept)
  }
}

function clearFilters() {
  selectedTags.value.clear()
  selectedConcepts.value.clear()
  searchQuery.value = ''
}

// 保存编辑
async function saveEdit() {
  if (!selectedNote.value) return
  try {
    await updateNote(selectedNote.value.id, {
      content: editForm.value.content,
      tags: editForm.value.tags.split(/[,，]/).map(t => t.trim()).filter(Boolean),
      concepts: editForm.value.concepts.split(/[,，]/).map(c => c.trim()).filter(Boolean),
      source: editForm.value.source
    })
    isEditing.value = false
    await load()
  } catch (e) {
    console.error('更新笔记失败:', e)
  }
}

// 手动添加笔记
async function submitAddNote() {
  if (!newForm.value.content.trim()) return
  try {
    const res = await createNote(props.studentId, {
      content: newForm.value.content,
      source: newForm.value.source || '手动录入',
      tags: newForm.value.tags ? newForm.value.tags.split(/[,，]/).map(t => t.trim()).filter(Boolean) : [],
      concepts: newForm.value.concepts ? newForm.value.concepts.split(/[,，]/).map(c => c.trim()).filter(Boolean) : [],
    })
    newForm.value = { content: '', tags: '', concepts: '', source: 'manual' }
    showAddModal.value = false
    selectedNoteId.value = res.id
    await load()
  } catch (e) {
    console.error('添加笔记失败:', e)
  }
}

// 删除笔记
async function removeNote(id) {
  if (!confirm('确认删除该则学习笔记吗？该操作不可撤销。')) return
  try {
    await deleteNote(id)
    if (selectedNoteId.value === id) {
      selectedNoteId.value = null
    }
    await load()
  } catch (e) {
    console.error('删除笔记失败:', e)
  }
}

// 一键 AI 润色
async function triggerAiPolish() {
  if (!selectedNote.value) return
  polishLoading.value = true
  try {
    const data = await aiPolishNote({ content: editForm.value.content })
    if (data.polished_content) {
      if (confirm('AI 已经为您完成了笔记的深度扩写、思维脑图设计和排版美化，是否直接保存并应用此版本？\\n(确定将直接更新保存并切换为预览，取消则进入编辑器保留润色内容以供微调)')) {
        const tagsArray = (data.tags || []).map(t => t.trim()).filter(Boolean)
        const conceptsArray = (data.concepts || []).map(c => c.trim()).filter(Boolean)
        await updateNote(selectedNote.value.id, {
          content: data.polished_content,
          tags: tagsArray,
          concepts: conceptsArray
        })
        isEditing.value = false
        await load() // 重新载入以更新界面上的选中笔记及列表
      } else {
        editForm.value.content = data.polished_content
        if (data.tags && data.tags.length > 0) {
          editForm.value.tags = data.tags.join(', ')
        }
        if (data.concepts && data.concepts.length > 0) {
          editForm.value.concepts = data.concepts.join(', ')
        }
        isEditing.value = true // 保持编辑态以允许用户微调
      }
    }
  } catch (e) {
    alert('AI 润色暂时不可用: ' + (e.message || e))
  } finally {
    polishLoading.value = false
  }
}

// 一键测评联动 (Notes ➡️ Quiz)
async function triggerQuiz(concept) {
  if (!concept) return
  try {
    // 强制跳转至智能对话的测验 Tab，并通过 store 启动测验
    quizStore.resetQuiz()
    // 立即启动测验生成，不 await 以免阻塞路由跳转
    quizStore.startQuizAction(props.studentId, concept)
    router.push('/learn')
  } catch (e) {
    console.error(e)
  }
}

// 艾宾浩斯复习联动 (Notes ➡️ Spaced Repetition)
async function startFlashcardReview(concept) {
  if (!concept) return
  ankiLoading.value = true
  showAnkiAnswer.value = false
  showAnkiModal.value = true
  ankiCard.value = {
    concept,
    question: `请结合你的理解，尝试默写并陈述 【${concept}】 笔记的核心内容和数学原理。`,
    answer: selectedNote.value?.content || '暂无详细笔记内容。'
  }
  ankiLoading.value = false
}

// 闪卡背诵评分提交
async function submitAnkiScore(quality) {
  if (!ankiCard.value) return
  try {
    await reviewFlashcard(props.studentId, ankiCard.value.concept, quality)
    showAnkiModal.value = false
    // 重新拉取最新复习排程
    const plansData = await getReviewPlans(props.studentId)
    reviewPlans.value = Array.isArray(plansData) ? plansData : plansData.plans || []
  } catch (e) {
    console.error('闪卡评分提交失败:', e)
  }
}

// 手动添加到复习计划
async function triggerAddReviewPlan(concept) {
  if (!concept) return
  try {
    await createReviewPlan(props.studentId, { concept, priority: 1.0 })
    // 重新拉取
    const plansData = await getReviewPlans(props.studentId)
    reviewPlans.value = Array.isArray(plansData) ? plansData : plansData.plans || []
    alert('该概念已成功加入艾宾浩斯记忆复习库中！')
  } catch (e) {
    console.error(e)
  }
}

// 导出为 Markdown
function exportMarkdown(note) {
  if (!note) return
  const content = [
    `# ${note.concepts?.[0] || '学习笔记'}`,
    `> 来源: ${note.source || '手动记录'} | 创建时间: ${new Date(note.created_at).toLocaleString()}`,
    `> 标签: ${(note.tags || []).join(', ')}`,
    '',
    note.content || '',
    '',
    `---\n*由 EduMatrix 智教矩阵系统归档保存*`
  ].join('\n')
  
  const blob = new Blob([content], { type: 'text/markdown' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `edumatrix-note-${note.concepts?.[0] || note.id}.md`
  a.click()
  URL.revokeObjectURL(url)
}

function ago(ts) {
  if (!ts) return ''
  const s = Math.floor((Date.now() - new Date(ts).getTime()) / 1000)
  if (s < 60) return '刚刚'
  if (s < 3600) return `${Math.floor(s / 60)}分钟前`
  if (s < 86400) return `${Math.floor(s / 3600)}小时前`
  return `${Math.floor(s / 86400)}天前`
}

// ======================== MARKDOWN RENDER ENGINE ========================
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
  ]
  for (let line of lines) {
    let trimmed = line.trim()
    if (!trimmed) { result.push(line); continue }
    if (trimmed === 'mindmap') { isMindmap = true; result.push(line); continue }
    if (!isMindmap) { result.push(line); continue }
    let indent = line.match(/^(\s*)/)[0]
    let cleaned = trimmed.replace(/^[-*+]\s+/, '').replace(/\*\*/g, '').replace(/`/g, '')
    if (cleaned.startsWith('%%')) { result.push(line); continue }
    if (cleaned.startsWith('"') && cleaned.endsWith('"')) { cleaned = cleaned.slice(1, -1).trim() }
    let isShape = false
    let id = '', openDelim = '', innerText = '', closeDelim = ''
    for (const pair of delimPairs) {
      const escapedOpen = pair.open.replace(/[|\\{}()[\]^$+*?.]/g, '\\$&')
      const escapedClose = pair.close.replace(/[|\\{}()[\]^$+*?.]/g, '\\$&')
      const regex = new RegExp(`^([^({[\\]\\s]+)\\s*(${escapedOpen})\\s*(.*?)\\s*(${escapedClose})$`)
      const match = cleaned.match(regex)
      if (match) { id = match[1]; openDelim = match[2]; innerText = match[3]; closeDelim = match[4]; isShape = true; break }
    }
    if (isShape) {
      let cleanText = innerText.trim()
      if (cleanText.startsWith('"') && cleanText.endsWith('"')) { cleanText = cleanText.slice(1, -1) }
      cleanText = cleanText.replace(/\\"/g, '"').replace(/"/g, '&quot;').trim()
      result.push(indent + id + openDelim + '"' + cleanText + '"' + closeDelim)
      continue
    }
    const hasSpecial = /[^a-zA-Z0-9_\-]/g.test(cleaned)
    if (hasSpecial) {
      nodeCounter++
      const nodeId = `node_${nodeCounter}`
      let cleanText = cleaned.replace(/\\"/g, '"').replace(/"/g, '&quot;').trim()
      result.push(indent + nodeId + '[' + '"' + cleanText + '"' + ']')
    } else {
      let cleanText = cleaned.replace(/\\"/g, '"').replace(/"/g, '&quot;').trim()
      result.push(indent + cleanText)
    }
  }
  return result.join('\n')
}

function renderMarkdown(text) {
  if (!text) return ''
  let cleaned = text.trim()

  // 自动闭合未闭合的代码块 (```) 与双美元公式块 ($$)，防止内容被截断时导致排版彻底崩溃
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
  const svgBlocks = []
  cleaned = cleaned.replace(/(<svg[\s\S]*?<\/svg>)/gi, (match) => {
    const idx = svgBlocks.length
    svgBlocks.push(match)
    return `@@SVGBLOCKTOKEN${idx}@@`
  })
  let html = cleaned.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
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
  const codeBlocks = []
  html = html.replace(/```([^\r\n]*)\r?\n([\s\S]*?)```/g, (_, lang, code) => {
    const isMermaid = lang.toLowerCase().includes('mermaid') || code.includes('mindmap') || code.includes('graph ') || code.includes('sequenceDiagram')
    let blockHtml = ''
    if (isMermaid) {
      let cleanCode = code.trim().replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&quot;/g, '"').replace(/&#39;/g, "'")
      const tokenRegex = /@@INLINEMATHTOKEN(\d+)@@/g
      cleanCode = cleanCode.replace(tokenRegex, (match, idx) => {
        const item = inlineMath[parseInt(idx)]
        return item ? item.math.replace(/\$/g, '').replace(/\\hat\{([a-zA-Z0-9]+)\}/g, '$1^').replace(/\\frac\{([^}]+)\}\{([^}]+)\}/g, '$1/$2').replace(/\\partial/g, 'd').replace(/\\Sigma/g, 'sum').replace(/\\/g, '') : ''
      })
      cleanCode = sanitizeMermaidCode(cleanCode)
      if (cleanCode.includes('mindmap')) {
        const escapedCode = encodeURIComponent(cleanCode)
        blockHtml = `<div class="custom-mindmap-placeholder my-3" data-code="${escapedCode}"></div>`
      } else {
        const escapedCode = encodeURIComponent(cleanCode)
        blockHtml = `<div class="my-3 p-4 bg-white border border-gray-200 rounded-xl text-xs flex flex-col items-center shadow-sm max-w-full"><div class="mermaid w-full flex justify-center" data-code="${escapedCode}"><div class="mermaid-loading flex flex-col items-center justify-center gap-1.5 py-6 text-gray-400 select-none"><div class="w-5 h-5 border-2 border-indigo-500 border-t-transparent rounded-full animate-spin"></div><span class="text-[10px] text-indigo-500 font-semibold animate-pulse">正在绘制思维导图...</span></div></div></div>`
      }
    } else {
      const cleanLang = (lang || 'python').trim().toLowerCase()
      blockHtml = `<pre class="p-3 bg-gray-900 rounded-lg overflow-x-auto text-xs leading-relaxed my-2 language-${cleanLang}"><code class="language-${cleanLang}">${code.trim()}</code></pre>`
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
  const lines = html.split('\n')
  let inTable = false, tableHeader = [], tableRows = [], inList = false
  const processedLines = []
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i]
    const trimmed = line.trim()
    const isTableRow = trimmed.startsWith('|') && trimmed.endsWith('|')
    if (isTableRow) {
      if (inList) { processedLines.push('</ul>'); inList = false }
      const cells = trimmed.slice(1, -1).split('|').map(c => c.trim())
      const isSeparator = cells.every(c => /^[:-]+$/.test(c))
      if (isSeparator) continue
      if (!inTable) { inTable = true; tableHeader = cells } else { tableRows.push(cells) }
      continue
    } else {
      if (inTable) { processedLines.push(generateTableHtml(tableHeader, tableRows)); inTable = false; tableHeader = []; tableRows = [] }
    }
    const listMatch = line.match(/^(\s*)[-*+]\s+(.*)$/)
    if (listMatch) {
      const content = listMatch[2]
      if (!inList) { processedLines.push('<ul class="my-2 space-y-1 list-disc list-inside">'); inList = true }
      processedLines.push(`<li class="ml-4 text-xs text-gray-600 my-1 leading-relaxed">${content}</li>`)
    } else {
      if (inList) { processedLines.push('</ul>'); inList = false }
      processedLines.push(line)
    }
  }
  if (inTable) processedLines.push(generateTableHtml(tableHeader, tableRows))
  if (inList) processedLines.push('</ul>')
  html = processedLines.join('\n')

  function generateTableHtml(header, rows) {
    let tableHtml = '<div class="overflow-x-auto my-4 border border-gray-200/80 rounded-xl shadow-sm bg-white"><table class="min-w-full divide-y divide-gray-200">'
    if (header?.length) {
      tableHtml += '<thead class="bg-gray-50/75"><tr>'
      header.forEach(h => { tableHtml += `<th class="px-4 py-2.5 text-left text-xs font-semibold text-gray-700 uppercase tracking-wider">${h}</th>` })
      tableHtml += '</tr></thead>'
    }
    tableHtml += '<tbody class="divide-y divide-gray-100 bg-white">'
    rows.forEach(row => {
      tableHtml += '<tr class="hover:bg-gray-50/50 transition-colors">'
      row.forEach(cell => { tableHtml += `<td class="px-4 py-2 text-xs text-gray-600">${cell}</td>` })
      tableHtml += '</tr>'
    })
    tableHtml += '</tbody></table></div>'
    return tableHtml
  }

  html = html.replace(/!\[([^\]]*)\]\s*\(([^)]+)\)/g, (match, alt, url) => `<img src="${url.replace(/\s+/g, '')}" alt="${alt}" class="max-w-full max-h-[300px] object-contain rounded-xl my-3 shadow-sm border border-gray-100 bg-white p-1" />`)
  html = html.replace(/\*\*([^*]+)\*\*/g, '<strong class="font-bold text-gray-900">$1</strong>')
  html = html.replace(/\*([^*]+)\*/g, '<em class="italic text-gray-800">$1</em>')
  // Inline code is already extracted and protected as @@CODEBLOCKTOKEN@@ above
  html = html.replace(/^### (.*$)/gim, '<h4 class="text-xs font-bold text-gray-800 mt-4 mb-1.5 flex items-center gap-1">$1</h4>')
  html = html.replace(/^## (.*$)/gim, '<h3 class="text-sm font-semibold text-gray-900 mt-5 mb-2 border-b border-gray-100 pb-1 flex items-center gap-1.5">$1</h3>')
  html = html.replace(/^# (.*$)/gim, '<h2 class="text-base font-bold text-gray-900 mt-6 mb-3 flex items-center gap-2">$1</h2>')
  html = html.replace(/\n\n/g, '<div class="h-2.5"></div>')

  function renderMath(math, display) {
    if (window.katex) {
      try { return window.katex.renderToString(math, { displayMode: display, throwOnError: false, trust: true }) } catch (err) { console.error(err) }
    }
    const cleanMath = math.replace(/\\Sigma/g, '∑').replace(/\\sigma/g, 'σ').replace(/\\mu/g, 'μ').replace(/\\beta/g, 'β').replace(/\\theta/g, 'θ').replace(/\\alpha/g, 'α').replace(/\\lambda/g, 'λ').replace(/\\partial/g, '∂').replace(/\\infty/g, '∞').replace(/\\cdot/g, '·').replace(/\\times/g, '×')
    return display ? `<div class="my-3.5 p-4 bg-gray-50/75 border border-gray-100 rounded-xl text-center font-serif text-sm overflow-x-auto shadow-inner text-gray-800">${cleanMath}</div>` : `<span class="font-serif italic bg-gray-50/75 px-1.5 py-0.5 rounded text-xs text-gray-800 border border-gray-100/50">${cleanMath}</span>`
  }

  html = html.replace(/\\in\b/g, ' ∈ ').replace(/\\sigma\b/g, 'σ').replace(/\\([{}])/g, '$1')
    .replace(/([a-zA-Z0-9])_([a-zA-Z0-9_]+)/g, '$1<sub>$2</sub>')
    .replace(/([a-zA-Z0-9])\^([a-zA-Z0-9+-\\*\\top]+)/g, (match, base, exp) => `${base}<sup>${exp === '\\top' ? 'T' : exp}</sup>`)

  blockMath.forEach((item, idx) => { html = html.split(`@@BLOCKMATHTOKEN${idx}@@`).join(renderMath(item.math, true)) })
  inlineMath.forEach((item, idx) => { html = html.split(`@@INLINEMATHTOKEN${idx}@@`).join(renderMath(item.math, false)) })
  codeBlocks.forEach((block, idx) => { html = html.split(`@@CODEBLOCKTOKEN${idx}@@`).join(block) })
  svgBlocks.forEach((block, idx) => { html = html.split(`@@SVGBLOCKTOKEN${idx}@@`).join(block) })
  return html
}

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
  nextTick(() => {
    if (typeof window.mermaid !== 'undefined') {
      try {
        window.mermaid.initialize({
          startOnLoad: false,
          theme: 'default',
          securityLevel: 'loose',
          themeVariables: {
            background: '#ffffff',
            primaryColor: '#ff79c6',
            primaryTextColor: '#111827',
            lineColor: '#6366f1',
            fontSize: '12px'
          }
        })
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
      } catch (e) {
        console.error('Mermaid render error:', e)
      }
    }
    mountCustomMindmaps()
    if (typeof window.Prism !== 'undefined') {
      window.Prism.highlightAll()
    }
  })
}

// 监听选中笔记、编辑模式及内容变化，触发图谱自愈渲染与 Vue 思维导图挂载
watch([selectedNoteId, isEditing, () => editForm.value.content], () => {
  cleanupCustomMindmaps()
  nextTick(() => {
    renderAllDiagrams()
  })
}, { deep: true, immediate: true })

function forceRefreshDiagrams() {
  cleanupCustomMindmaps()
  nextTick(() => {
    renderAllDiagrams()
  })
}

onMounted(async () => {
  await load()
  renderAllDiagrams()
})
</script>

<template>
  <div class="flex gap-4 h-[calc(100vh-120px)] max-w-6xl mx-auto border border-gray-200/60 rounded-2xl overflow-hidden bg-white shadow-lg">
    <!-- Left Explorer Sidebar -->
    <div class="w-80 border-r border-gray-200/80 flex flex-col shrink-0 min-w-[280px]">
      <div class="p-4 border-b border-gray-100 flex flex-col gap-3">
        <div class="flex items-center justify-between">
          <h2 class="text-sm font-bold text-gray-800 flex items-center gap-1.5">
            <BookOpen :size="16" class="text-blue-500" />
            <span>知识库笔记 ({{ filteredNotes.length }})</span>
          </h2>
          <button class="w-7 h-7 rounded-lg bg-blue-50 hover:bg-blue-100 text-blue-600 flex items-center justify-center transition-all border border-blue-100" @click="showAddModal = true">
            <Plus :size="15" />
          </button>
        </div>
        <div class="relative">
          <Search :size="13" class="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
          <input v-model="searchQuery" class="w-full pl-8 pr-3 py-1.5 text-xs rounded-xl border border-gray-200 bg-gray-50/50 focus:bg-white focus:border-blue-300 focus:ring-2 focus:ring-blue-100 outline-none transition-all placeholder:text-gray-300" placeholder="检索笔记/概念/标签..." />
        </div>
      </div>

      <!-- Filters (Pills) -->
      <div class="px-4 py-2 border-b border-gray-50 flex flex-col gap-2 max-h-[140px] overflow-y-auto scrollbar-thin">
        <div v-if="allConcepts.length > 0" class="flex flex-wrap gap-1">
          <span v-for="concept in allConcepts" :key="concept" 
            @click="toggleConceptFilter(concept)" 
            class="text-[9px] px-2 py-0.5 rounded-full cursor-pointer transition-all border select-none"
            :class="selectedConcepts.has(concept) ? 'bg-purple-600 border-purple-600 text-white font-semibold' : 'bg-purple-50 hover:bg-purple-100 border-purple-100 text-purple-700'">
            🧩 {{ concept }}
          </span>
        </div>
        <div v-if="allTags.length > 0" class="flex flex-wrap gap-1">
          <span v-for="tag in allTags" :key="tag" 
            @click="toggleTagFilter(tag)" 
            class="text-[9px] px-2 py-0.5 rounded-full cursor-pointer transition-all border select-none"
            :class="selectedTags.has(tag) ? 'bg-blue-600 border-blue-600 text-white font-semibold' : 'bg-blue-50 hover:bg-blue-100 border-blue-100 text-blue-700'">
            🏷️ {{ tag }}
          </span>
        </div>
        <div v-if="selectedTags.size > 0 || selectedConcepts.size > 0 || searchQuery" class="text-right">
          <button @click="clearFilters" class="text-[9px] text-gray-400 hover:text-blue-500 font-semibold underline">清除所有过滤</button>
        </div>
      </div>

      <!-- Notes List -->
      <div class="flex-1 overflow-y-auto divide-y divide-gray-50 scrollbar-thin">
        <div v-if="filteredNotes.length === 0" class="flex flex-col items-center justify-center h-full text-center text-gray-400 p-6">
          <StickyNote :size="28" class="mb-2 opacity-35" />
          <p class="text-xs">无匹配笔记</p>
        </div>
        <div v-else v-for="note in filteredNotes" :key="note.id" 
          @click="selectedNoteId = note.id"
          class="p-4 cursor-pointer hover:bg-slate-50/70 transition-all border-l-2"
          :class="selectedNoteId === note.id ? 'border-blue-500 bg-blue-50/30' : 'border-transparent'">
          <div class="flex items-center justify-between mb-1">
            <span class="text-xs font-bold text-gray-800 truncate pr-2">
              {{ note.source === '错题本反思' ? (note.concepts?.[0] ? `${note.concepts[0]} 错题集` : '错题集') : (note.concepts?.[0] || '未分类概念') }}
            </span>
            <span class="text-[9px] text-gray-400 shrink-0 font-mono">{{ ago(note.created_at) }}</span>
          </div>
          <p class="text-[11px] text-gray-400 line-clamp-2 leading-relaxed mb-2">{{ note.content.replace(/#+\s/g, '').replace(/```[\s\S]*?```/g, '[代码块]').replace(/\$/g, '') }}</p>
          <div class="flex flex-wrap items-center gap-1">
            <span class="text-[8px] px-1.5 py-0.5 rounded bg-gray-100 text-gray-500 font-semibold border border-gray-200/60">{{ note.source === 'manual' ? '手动录入' : note.source || '对话同步' }}</span>
            <span v-for="tag in (note.tags || []).slice(0, 2)" :key="tag" class="text-[8px] px-1.5 py-0.5 rounded bg-blue-50 text-blue-600 border border-blue-100/50">{{ tag }}</span>
            <span v-if="getConceptPlan(note.concepts)" class="w-1.5 h-1.5 rounded-full bg-orange-500 ml-auto" title="有待复习排程" />
          </div>
        </div>
      </div>
    </div>

    <!-- Right Workspace Details -->
    <div class="flex-1 flex flex-col min-w-0 bg-slate-50/40">
      <div v-if="!selectedNote" class="flex-1 flex flex-col items-center justify-center text-center text-gray-400 p-8">
        <StickyNote :size="48" class="mb-3 opacity-25 text-blue-500" />
        <h3 class="text-sm font-bold text-gray-700">开启您的智能笔记工作站</h3>
        <p class="text-xs text-gray-400 max-w-sm mt-1">在左侧列表选中笔记进行编辑、AI 排版，或启动一键自适应测评及艾宾浩斯记忆闪卡联动。</p>
      </div>

      <div v-else class="flex-1 flex flex-col min-h-0">
        <!-- Header Actions -->
        <div class="px-6 py-3.5 border-b border-gray-200/80 bg-white flex items-center justify-between shadow-sm shrink-0">
          <div>
            <div class="flex items-center gap-2">
              <h2 class="text-sm font-bold text-gray-800">
                {{ selectedNote.source === '错题本反思' ? (selectedNote.concepts?.[0] ? `${selectedNote.concepts[0]} 错题集` : '错题集') : (selectedNote.concepts?.[0] || '学习笔记') }}
              </h2>
              <span class="text-[10px] px-2 py-0.5 rounded-full font-semibold border" 
                :class="selectedNote.source === 'manual' ? 'bg-orange-50 text-orange-600 border-orange-100' : 'bg-blue-50 text-blue-600 border-blue-100'">
                来源: {{ selectedNote.source === 'manual' ? '手动记录' : selectedNote.source || '对话同步' }}
              </span>
              <button @click="forceRefreshDiagrams" 
                class="p-1 text-gray-400 hover:text-blue-500 hover:bg-blue-50 rounded-lg transition-all flex items-center justify-center border border-transparent hover:border-blue-100"
                title="重新渲染/刷新脑图与公式">
                <RotateCw :size="11" />
              </button>
            </div>
            <p class="text-[10px] text-gray-400 mt-0.5">创建于 {{ new Date(selectedNote.created_at).toLocaleString() }}</p>
          </div>

          <div class="flex items-center gap-2">
            <!-- Edit/Preview Toggle -->
            <button @click="isEditing = !isEditing" class="px-3 py-1.5 rounded-xl text-xs font-semibold flex items-center gap-1.5 transition-all"
              :class="isEditing ? 'bg-indigo-50 text-indigo-600 border border-indigo-100' : 'bg-gray-100 text-gray-600 hover:bg-gray-200'">
              <component :is="isEditing ? Eye : Edit3" :size="12" />
              <span>{{ isEditing ? '切换预览' : '编辑笔记' }}</span>
            </button>

            <!-- AI Polish -->
            <button :disabled="polishLoading" @click="triggerAiPolish" 
              class="px-3 py-1.5 bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-700 hover:to-indigo-700 text-white rounded-xl text-xs font-semibold flex items-center gap-1.5 shadow-sm transition-all disabled:opacity-50">
              <Loader2 v-if="polishLoading" :size="12" class="animate-spin" />
              <Sparkles v-else :size="12" />
              <span>AI 智能排版</span>
            </button>

            <!-- Instant Assessment -->
            <button v-if="selectedNote.concepts?.[0]" @click="triggerQuiz(selectedNote.concepts[0])" 
              class="px-3 py-1.5 bg-purple-50 hover:bg-purple-100 text-purple-700 border border-purple-100 rounded-xl text-xs font-semibold flex items-center gap-1.5 transition-all"
              title="针对该笔记对应概念生成自适应测验">
              <BookOpen :size="12" />
              <span>一键测评</span>
            </button>

            <!-- Export & Delete -->
            <button @click="exportMarkdown(selectedNote)" class="p-2 bg-gray-100 hover:bg-gray-200 text-gray-500 hover:text-gray-700 rounded-xl transition-all" title="导出为 Markdown">
              <Download :size="13" />
            </button>
            <button @click="removeNote(selectedNote.id)" class="p-2 bg-red-50 hover:bg-red-100 text-red-500 hover:text-red-600 rounded-xl border border-red-100 transition-all" title="删除笔记">
              <Trash2 :size="13" />
            </button>
          </div>
        </div>

        <!-- Ebbinghaus Tracking -->
        <div v-if="selectedNote.concepts?.[0]" class="mx-6 mt-4 p-3 bg-white border border-gray-200/80 rounded-2xl shadow-sm shrink-0">
          <div class="flex items-center justify-between">
            <div class="flex items-center gap-2">
              <span class="text-xs">📅</span>
              <span class="text-xs font-bold text-gray-700">艾宾浩斯遗忘曲线监控</span>
            </div>
            
            <div v-if="getConceptPlan(selectedNote.concepts)" class="flex items-center gap-4">
              <div class="text-[10px] text-gray-500">
                记忆掌握度: <span class="font-bold text-green-600">{{ (getConceptPlan(selectedNote.concepts).mastery * 100).toFixed(0) }}%</span>
              </div>
              <div class="text-[10px] text-gray-500">
                复习天数间隔: <span class="font-bold text-blue-600">{{ getConceptPlan(selectedNote.concepts).interval_days }}天</span>
              </div>
              <div class="text-[10px] text-gray-500">
                下次复习: <span class="font-bold text-gray-700">{{ new Date(getConceptPlan(selectedNote.concepts).next_review_at).toLocaleDateString() }}</span>
              </div>
              <button @click="startFlashcardReview(selectedNote.concepts[0])" 
                class="px-2.5 py-1 bg-orange-50 hover:bg-orange-100 text-orange-700 border border-orange-200 rounded-lg text-[10px] font-bold transition-all flex items-center gap-0.5 shadow-sm">
                ⚡ 开始闪卡复习
              </button>
            </div>
            <div v-else>
              <button @click="triggerAddReviewPlan(selectedNote.concepts[0])" 
                class="px-2.5 py-1 bg-gray-50 hover:bg-blue-50 hover:text-blue-600 text-gray-600 border border-gray-200/80 rounded-lg text-[10px] font-semibold transition-all">
                + 加入复习计划
              </button>
            </div>
          </div>
        </div>

        <!-- Main Workspace Body -->
        <div class="flex-1 overflow-y-auto px-6 py-4 scrollbar-thin flex flex-col min-h-0">
          <!-- View Mode (Preview) -->
          <div v-if="!isEditing" class="flex-1 bg-white border border-gray-200/60 rounded-2xl p-6 shadow-sm overflow-y-auto scrollbar-thin">
            <div class="prose prose-sm max-w-none text-xs text-gray-800 leading-relaxed" v-html="renderMarkdown(editForm.content)" />
          </div>

          <!-- Edit Mode -->
          <div v-else class="flex-1 flex flex-col gap-3 min-h-0">
            <div class="flex-1 flex flex-col border border-gray-200 rounded-2xl overflow-hidden shadow-sm bg-white min-h-0">
              <div class="bg-slate-50 text-[10px] text-slate-500 px-4 py-2 border-b border-gray-100 font-semibold uppercase tracking-wider flex items-center justify-between">
                <span>Markdown 编辑器</span>
                <span class="font-mono text-[9px] text-slate-400">支持 LaTeX 公式 ($ / $$) 与 Markdown 排版</span>
              </div>
              <textarea v-model="editForm.content" 
                class="flex-1 p-4 bg-[#0f172a] text-slate-200 font-mono text-xs resize-none outline-none leading-relaxed overflow-y-auto"
                placeholder="# 输入您的笔记大纲和内容...可以使用 Markdown 语法和 $ 包裹的 LaTeX 公式" />
            </div>

            <!-- Tags, Concepts, Source Edit -->
            <div class="bg-white border border-gray-200/80 rounded-2xl p-4 shadow-sm grid grid-cols-3 gap-3 shrink-0">
              <div class="flex flex-col gap-1">
                <label class="text-[10px] font-bold text-gray-500 uppercase tracking-wider">关联核心概念</label>
                <input v-model="editForm.concepts" class="w-full px-3 py-2 text-xs rounded-xl border border-gray-200 bg-white focus:border-blue-300 focus:ring-2 focus:ring-blue-100 outline-none transition-all placeholder:text-gray-300" placeholder="概念名词(逗号分隔)" />
              </div>
              <div class="flex flex-col gap-1">
                <label class="text-[10px] font-bold text-gray-500 uppercase tracking-wider">分类标签 (Tags)</label>
                <input v-model="editForm.tags" class="w-full px-3 py-2 text-xs rounded-xl border border-gray-200 bg-white focus:border-blue-300 focus:ring-2 focus:ring-blue-100 outline-none transition-all placeholder:text-gray-300" placeholder="分类标签(逗号分隔)" />
              </div>
              <div class="flex flex-col gap-1">
                <label class="text-[10px] font-bold text-gray-500 uppercase tracking-wider">笔记来源</label>
                <select v-model="editForm.source" class="w-full px-3 py-2 text-xs rounded-xl border border-gray-200 bg-white focus:border-blue-300 focus:ring-2 focus:ring-blue-100 outline-none transition-all">
                  <option value="manual">手动录入</option>
                  <option value="conversation">对话自动保存</option>
                  <option value="错题本反思">错题本反思自动导入</option>
                </select>
              </div>
            </div>

            <!-- Save buttons -->
            <div class="flex items-center justify-end gap-2 shrink-0">
              <button class="px-4 py-2 bg-gray-100 hover:bg-gray-200 text-gray-600 rounded-xl text-xs font-semibold transition-all" @click="isEditing = false">取消</button>
              <button class="px-5 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-xl text-xs font-semibold shadow-sm transition-all" @click="saveEdit">保存修改</button>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Manual Add Note Modal -->
    <div v-if="showAddModal" class="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm" @click.self="showAddModal = false">
      <div class="bg-white rounded-2xl shadow-2xl w-[600px] max-h-[85vh] flex flex-col overflow-hidden border border-gray-100">
        <div class="flex items-center justify-between px-5 py-3 border-b border-gray-100 bg-gray-50/50 shrink-0">
          <h3 class="text-sm font-bold text-gray-800 flex items-center gap-1.5">
            <Plus :size="16" class="text-blue-500" />
            <span>新建学习笔记</span>
          </h3>
          <button class="text-gray-400 hover:text-gray-600 text-lg leading-none" @click="showAddModal = false"><X :size="16" /></button>
        </div>
        <div class="flex-1 overflow-y-auto p-5 space-y-4">
          <div class="flex flex-col gap-1">
            <label class="text-[10px] font-bold text-gray-500 uppercase tracking-wider">笔记内容</label>
            <textarea v-model="newForm.content" class="w-full h-40 p-3 text-xs rounded-xl border border-gray-200 bg-white focus:border-blue-300 focus:ring-2 focus:ring-blue-100 outline-none transition-all resize-none" placeholder="输入您要记录的知识点内容，支持 Markdown 和 LaTeX 公式..." />
          </div>
          <div class="grid grid-cols-2 gap-4">
            <div class="flex flex-col gap-1">
              <label class="text-[10px] font-bold text-gray-500 uppercase tracking-wider">核心概念</label>
              <input v-model="newForm.concepts" class="w-full px-3 py-2 text-xs rounded-xl border border-gray-200 bg-white focus:border-blue-300 focus:ring-2 focus:ring-blue-100 outline-none transition-all placeholder:text-gray-300" placeholder="输入核心概念 (如: 卷积核)" />
            </div>
            <div class="flex flex-col gap-1">
              <label class="text-[10px] font-bold text-gray-500 uppercase tracking-wider">分类标签 (Tags)</label>
              <input v-model="newForm.tags" class="w-full px-3 py-2 text-xs rounded-xl border border-gray-200 bg-white focus:border-blue-300 focus:ring-2 focus:ring-blue-100 outline-none transition-all placeholder:text-gray-300" placeholder="分类标签 (如: CNN, 深度学习)" />
            </div>
          </div>
        </div>
        <div class="flex items-center justify-end gap-2 px-5 py-3 border-t border-gray-100 bg-gray-50 shrink-0">
          <button class="px-4 py-2 bg-gray-100 hover:bg-gray-200 text-gray-600 rounded-xl text-xs font-semibold transition-all" @click="showAddModal = false">取消</button>
          <button class="px-5 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-xl text-xs font-semibold shadow-sm transition-all" :disabled="!newForm.content.trim()" @click="submitAddNote">保存笔记本</button>
        </div>
      </div>
    </div>

    <!-- Anki Flashcard Active Modal -->
    <div v-if="showAnkiModal" class="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm" @click.self="showAnkiModal = false">
      <div class="bg-white rounded-2xl shadow-2xl w-[500px] max-h-[80vh] flex flex-col overflow-hidden border border-gray-100">
        <div class="flex items-center justify-between px-5 py-3.5 border-b border-gray-100 bg-orange-50/20 shrink-0">
          <h3 class="text-sm font-bold text-gray-800 flex items-center gap-1.5">
            <Sparkles :size="15" class="text-orange-500 animate-spin" />
            <span>艾宾浩斯智能复习闪卡 (Anki)</span>
          </h3>
          <button class="text-gray-400 hover:text-gray-600 text-lg leading-none" @click="showAnkiModal = false"><X :size="16" /></button>
        </div>
        <div class="flex-1 overflow-y-auto p-6 space-y-6">
          <div v-if="ankiLoading" class="flex flex-col items-center justify-center py-12 text-gray-400">
            <Loader2 :size="24" class="animate-spin text-orange-500 mb-2" />
            <span class="text-xs">智能加载复习题...</span>
          </div>
          <div v-else-if="ankiCard" class="space-y-4">
            <div class="bg-orange-50/30 border border-orange-100 rounded-2xl p-5 shadow-sm">
              <span class="text-[9px] font-bold text-orange-600 uppercase tracking-wider bg-orange-100/50 px-2 py-0.5 rounded">Prompt / 问题</span>
              <p class="text-xs font-bold text-gray-800 leading-relaxed mt-2.5">{{ ankiCard.question }}</p>
            </div>
            
            <div v-if="showAnkiAnswer" class="bg-green-50/20 border border-green-100 rounded-2xl p-5 shadow-sm max-h-60 overflow-y-auto scrollbar-thin">
              <span class="text-[9px] font-bold text-green-600 uppercase tracking-wider bg-green-100/40 px-2 py-0.5 rounded">答案参考与笔记细节</span>
              <div class="prose prose-sm max-w-none text-xs text-gray-800 leading-relaxed mt-2.5" v-html="renderMarkdown(ankiCard.answer)" />
            </div>
            <div v-else class="text-center py-4">
              <button @click="showAnkiAnswer = true" class="px-5 py-2.5 bg-orange-500 hover:bg-orange-600 text-white rounded-xl text-xs font-semibold shadow-md hover:shadow-orange-500/20 transition-all">显示答案参考</button>
            </div>
          </div>
        </div>
        
        <div v-if="showAnkiAnswer" class="px-5 py-4 border-t border-gray-100 bg-gray-50 flex flex-col gap-3 shrink-0">
          <p class="text-[10px] text-center font-bold text-gray-400 uppercase tracking-wider">自我记忆度反馈 (SM-2 算法核算)</p>
          <div class="grid grid-cols-3 gap-2">
            <button @click="submitAnkiScore(2)" class="px-4 py-2.5 bg-white hover:bg-red-50 text-red-600 hover:text-red-700 border border-red-100 rounded-xl text-xs font-bold shadow-sm transition-all flex flex-col items-center gap-0.5">
              <span>遗忘 / 没记住</span>
              <span class="text-[8px] font-normal text-red-400">评分: 2分 (间隔设为1天)</span>
            </button>
            <button @click="submitAnkiScore(4)" class="px-4 py-2.5 bg-white hover:bg-blue-50 text-blue-600 hover:text-blue-700 border border-blue-100 rounded-xl text-xs font-bold shadow-sm transition-all flex flex-col items-center gap-0.5">
              <span>犹豫 / 需提示</span>
              <span class="text-[8px] font-normal text-blue-400">评分: 4分 (维持原间隔)</span>
            </button>
            <button @click="submitAnkiScore(5)" class="px-4 py-2.5 bg-white hover:bg-green-50 text-green-600 hover:text-green-700 border border-green-100 rounded-xl text-xs font-bold shadow-sm transition-all flex flex-col items-center gap-0.5">
              <span>熟练 / 瞬时记起</span>
              <span class="text-[8px] font-normal text-green-400">评分: 5分 (翻倍复习间隔)</span>
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.scrollbar-thin::-webkit-scrollbar {
  width: 4px;
  height: 4px;
}
.scrollbar-thin::-webkit-scrollbar-track {
  background: transparent;
}
.scrollbar-thin::-webkit-scrollbar-thumb {
  background: #cbd5e1;
  border-radius: 4px;
}
.scrollbar-thin::-webkit-scrollbar-thumb:hover {
  background: #94a3b8;
}
</style>
