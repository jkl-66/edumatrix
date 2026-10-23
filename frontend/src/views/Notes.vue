<script setup>
import { ref, computed, onMounted, watch, nextTick, createApp } from 'vue'
import {
  getNotes, createNote, deleteNote, updateNote, aiPolishNote, exportNotePdf,
  getNoteVersions, restoreNoteVersion
} from '../api'
import CollapsibleMindmap from '../components/CollapsibleMindmap.vue'
import SearchField from '../components/ui/SearchField.vue'
import { useRouter, useRoute } from 'vue-router'
import {
  StickyNote, Plus, Trash2, Tag, Edit3, Eye, Sparkles,
  Download, FileText, Loader2, ChevronRight, ChevronDown,
  X, AlertCircle, Check, RotateCw, Save, History,
  SlidersHorizontal, MoreHorizontal, ArchiveRestore, CircleAlert
} from '@lucide/vue'

const props = defineProps({ studentId: String })
const router = useRouter()
const route = useRoute()

const notes = ref([])
const loading = ref(true)
const loadError = ref('')
const selectedNoteId = ref(null)
const isEditing = ref(false)
const saving = ref(false)
const saveError = ref('')
const saveNotice = ref('')
const conflict = ref(null)
const polishLoading = ref(false)
const polishError = ref('')
const pdfExporting = ref(false)
const versions = ref([])
const versionsLoading = ref(false)
const versionsError = ref('')
const restoringVersion = ref(null)
const newSaving = ref(false)
const newError = ref('')
const activeSourceFilter = ref('all')
const notesListRef = ref(null)
const notesScrollTop = ref(0)
const formHydrating = ref(false)
const operationCache = new Map()

const SOURCE_FILTER_IDS = new Set(['all', 'document', 'resource', 'review', 'wrong', 'personal'])

function routeQueryValue(value) {
  return Array.isArray(value) ? String(value[0] || '') : String(value || '')
}

function normalizedSourceFilter(value) {
  const candidate = routeQueryValue(value)
  return SOURCE_FILTER_IDS.has(candidate) ? candidate : 'all'
}

function restoreNotesListScroll() {
  nextTick(() => {
    if (!notesListRef.value) return
    const requestedScroll = Number.parseInt(routeQueryValue(route.query.notes_scroll), 10)
    notesScrollTop.value = Number.isFinite(requestedScroll) ? Math.max(0, requestedScroll) : notesScrollTop.value
    notesListRef.value.scrollTop = notesScrollTop.value
  })
}

function persistNotesListScroll(event) {
  // Scrolling is a local list interaction.  Keep the position in component
  // state so it never mutates the route or triggers a page-level refresh.
  notesScrollTop.value = Math.max(0, Math.round(event.currentTarget?.scrollTop || 0))
}

async function setSourceFilter(filterId) {
  const nextFilter = normalizedSourceFilter(filterId)
  persistDraft()
  activeSourceFilter.value = nextFilter
  await nextTick()

  const visibleNotes = filteredNotes.value
  if (!visibleNotes.some(note => note.id === selectedNoteId.value)) {
    selectedNoteId.value = visibleNotes[0]?.id || null
  }

  await router.replace({
    query: {
      ...route.query,
      category: nextFilter,
      note_id: selectedNoteId.value || undefined,
      notes_scroll: undefined,
    },
  })
  restoreNotesListScroll()
}

// 过滤和搜索状态
const searchQuery = ref('')
const selectedTags = ref(new Set())
const selectedConcepts = ref(new Set())

// 表单状态（编辑和新建）
const editForm = ref({ content: '', tags: '', concepts: '' })
const showAddModal = ref(false)
const newForm = ref({ content: '', tags: '', concepts: '' })

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    const data = await getNotes(props.studentId)
    notes.value = Array.isArray(data) ? data : data.notes || []
    
    const requestedId = String(route.query.note_id || '')
    const requestedExists = requestedId && notes.value.some(note => note.id === requestedId)
    const selectedExists = selectedNoteId.value && notes.value.some(note => note.id === selectedNoteId.value)
    if (requestedExists) selectedNoteId.value = requestedId
    else if (!selectedExists) selectedNoteId.value = notes.value[0]?.id || null
    restoreNotesListScroll()
  } catch (e) {
    console.error('加载笔记数据失败:', e)
    loadError.value = apiMessage(e, '笔记暂时无法载入，请重试。')
  } finally {
    loading.value = false
  }
}

const selectedNote = computed(() => {
  return notes.value.find(n => n.id === selectedNoteId.value) || null
})

// 监听当前选中笔记，同步编辑表单
const sourceLabels = {
  manual: '手动记录',
  conversation: '智能对话',
  knowledge_selection: '知识库选区',
  handout: '个性化讲义',
  code_sandbox: '代码沙盒',
  review_task: '复习任务',
  wrong_question_reflection: '错题本反思',
  '错题本反思': '错题本反思',
}

function apiMessage(error, fallback) {
  const detail = error?.response?.data?.detail
  if (typeof detail === 'string') return detail
  if (detail && typeof detail === 'object') return detail.message || fallback
  return error?.message || fallback
}

function noteSourceType(note) {
  return note?.source_metadata?.source_type || note?.source || 'manual'
}

function noteSourceLabel(note) {
  return sourceLabels[noteSourceType(note)] || note?.source_context?.title || '学习笔记'
}

function noteTitle(note) {
  if (!note) return '学习笔记'
  if (noteSourceType(note) === 'wrong_question_reflection' || note.source === '错题本反思') {
    return note.concepts?.[0] ? `${note.concepts[0]}错题集` : '错题集'
  }
  return note.concepts?.[0] || note.source_context?.title || '学习笔记'
}

function currentHistoryVersion(note) {
  return Number(note?.current_version_number || note?.lock_version || 1)
}

function sourceGroup(note) {
  const type = noteSourceType(note)
  if (type === 'knowledge_selection') return 'document'
  if (['handout', 'code_sandbox'].includes(type)) return 'resource'
  if (type === 'review_task') return 'review'
  if (type === 'wrong_question_reflection' || note?.source === '错题本反思') return 'wrong'
  return 'personal'
}

function formatDateTime(value) {
  if (!value) return '时间未知'
  return new Date(value).toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function noteExcerpt(note) {
  return String(note?.content || '')
    .replace(/```[\s\S]*?```/g, '[代码片段]')
    .replace(/[#>*_`$]/g, '')
    .replace(/\s+/g, ' ')
    .trim() || '暂无正文'
}

const hasActiveFilters = computed(() => (
  Boolean(searchQuery.value.trim())
  || selectedTags.value.size > 0
  || selectedConcepts.value.size > 0
  || activeSourceFilter.value !== 'all'
))

const versionChangeLabels = {
  created: '首次保存',
  legacy_baseline: '原版基线',
  saved: '内容修改',
  ai_suggestion_applied: '应用 AI 建议',
  restored: '历史恢复',
}

function versionChangeLabel(version) {
  return versionChangeLabels[version?.change_type] || '内容版本'
}

const sourceFilters = computed(() => {
  const definitions = [
    ['all', '全部'],
    ['document', '文档选区'],
    ['resource', '学习资源'],
    ['review', '复习任务'],
    ['wrong', '错题反思'],
    ['personal', '个人记录'],
  ]
  return definitions.map(([id, label]) => ({
    id,
    label,
    count: id === 'all' ? notes.value.length : notes.value.filter(note => sourceGroup(note) === id).length,
  }))
})

function draftStorageKey(noteId) {
  return `edumatrix:note-draft:${props.studentId || 'student'}:${noteId}`
}

function readStoredDraft(note) {
  if (!note || typeof localStorage === 'undefined') return null
  try {
    const parsed = JSON.parse(localStorage.getItem(draftStorageKey(note.id)) || 'null')
    return parsed?.content !== undefined ? parsed : null
  } catch {
    return null
  }
}

function persistDraft() {
  const note = selectedNote.value
  if (!note || formHydrating.value || typeof localStorage === 'undefined') return
  if (!isDirty.value) {
    localStorage.removeItem(draftStorageKey(note.id))
    return
  }
  localStorage.setItem(draftStorageKey(note.id), JSON.stringify({
    ...editForm.value,
    base_version: note.lock_version,
    saved_at: new Date().toISOString(),
  }))
}

function clearStoredDraft(noteId) {
  if (noteId && typeof localStorage !== 'undefined') localStorage.removeItem(draftStorageKey(noteId))
}

function hydrateForm(note) {
  if (!note) return
  const draft = readStoredDraft(note)
  formHydrating.value = true
  editForm.value = draft ? {
    content: draft.content || '',
    tags: draft.tags || '',
    concepts: draft.concepts || '',
  } : {
    content: note.content || '',
    tags: (note.tags || []).join(', '),
    concepts: (note.concepts || []).join(', '),
  }
  formHydrating.value = false
  isEditing.value = Boolean(draft)
  saveNotice.value = draft
    ? (draft.base_version === note.lock_version ? '已恢复上次未保存草稿。' : '已恢复旧草稿；保存前请先同步最新版本。')
    : ''
  saveError.value = ''
  conflict.value = draft && draft.base_version !== note.lock_version
    ? { message: '服务器笔记已有新版本，本地草稿仍完整保留。', currentVersion: note.lock_version }
    : null
  polishError.value = ''
  void loadVersions(note.id)
  nextTick(() => {
    cleanupCustomMindmaps()
    renderAllDiagrams()
  })
}

watch(selectedNote, hydrateForm, { immediate: true })

watch(editForm, () => {
  if (!formHydrating.value) {
    persistDraft()
    operationCache.delete('save')
  }
}, { deep: true })

watch(() => route.query.note_id, (noteId) => {
  const normalized = String(noteId || '')
  if (normalized && notes.value.some(note => note.id === normalized)) selectNote(normalized, false)
})

watch(() => route.query.category, (category) => {
  const normalized = normalizedSourceFilter(category)
  if (activeSourceFilter.value !== normalized) activeSourceFilter.value = normalized
  restoreNotesListScroll()
})

const isDirty = computed(() => {
  const note = selectedNote.value
  if (!note) return false
  return editForm.value.content !== (note.content || '')
    || editForm.value.tags !== (note.tags || []).join(', ')
    || editForm.value.concepts !== (note.concepts || []).join(', ')
})

function newOperationKey(prefix) {
  const random = globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(36).slice(2, 10)}`
  return `${prefix}-${random}`
}

function operationKey(kind, signature) {
  const cached = operationCache.get(kind)
  if (cached?.signature === signature) return cached.key
  const key = newOperationKey(`note-${kind}`)
  operationCache.set(kind, { signature, key })
  return key
}

function replaceNote(updated) {
  const index = notes.value.findIndex(note => note.id === updated.id)
  if (index === -1) notes.value.unshift(updated)
  else notes.value.splice(index, 1, updated)
}

function selectNote(noteId, updateRoute = true) {
  if (!noteId || noteId === selectedNoteId.value) return
  persistDraft()
  selectedNoteId.value = noteId
  if (updateRoute) {
    const scrollTop = notesScrollTop.value
    if (!scrollTop) {
      router.replace({ query: { ...route.query, note_id: noteId } })
      return
    }
    router.replace({
      query: {
        ...route.query,
        note_id: noteId,
        notes_scroll: scrollTop ? String(scrollTop) : undefined,
      },
    })
  }
}

async function loadVersions(noteId) {
  if (!noteId) return
  versionsLoading.value = true
  versionsError.value = ''
  try {
    const data = await getNoteVersions(noteId)
    if (selectedNoteId.value === noteId) versions.value = data.versions || []
  } catch (error) {
    if (selectedNoteId.value === noteId) versionsError.value = apiMessage(error, '历史版本暂时无法载入。')
  } finally {
    if (selectedNoteId.value === noteId) versionsLoading.value = false
  }
}

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
    const q = searchQuery.value.trim().toLowerCase()
    const matchQuery = !searchQuery.value.trim() || 
      (n.content || '').toLowerCase().includes(q) ||
      (n.concepts || []).some(c => c.toLowerCase().includes(q)) ||
      (n.tags || []).some(t => t.toLowerCase().includes(q)) ||
      (n.source === '错题本反思' && ('错题集'.includes(q) || '错题'.includes(q)))
    const matchTags = selectedTags.value.size === 0 || 
      (n.tags || []).some(t => selectedTags.value.has(t))
    const matchConcepts = selectedConcepts.value.size === 0 || 
      (n.concepts || []).some(c => selectedConcepts.value.has(c))
    const matchSource = activeSourceFilter.value === 'all' || sourceGroup(n) === activeSourceFilter.value
    return matchQuery && matchTags && matchConcepts && matchSource
  })
})

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
  activeSourceFilter.value = 'all'
  void router.replace({
    query: {
      ...route.query,
      category: 'all',
      notes_scroll: undefined,
    },
  })
}

async function saveEdit() {
  const note = selectedNote.value
  if (!note || saving.value || !editForm.value.content.trim()) return
  saving.value = true
  saveError.value = ''
  saveNotice.value = ''
  const tags = editForm.value.tags.split(/[,，]/).map(t => t.trim()).filter(Boolean)
  const concepts = editForm.value.concepts.split(/[,，]/).map(c => c.trim()).filter(Boolean)
  const signature = JSON.stringify([note.id, note.lock_version, editForm.value.content, tags, concepts])
  try {
    const updated = await updateNote(note.id, {
      student_id: props.studentId,
      content: editForm.value.content,
      tags,
      concepts,
      expected_version: note.lock_version,
      idempotency_key: operationKey('save', signature),
      change_type: 'saved',
    })
    clearStoredDraft(note.id)
    replaceNote(updated)
    await nextTick()
    operationCache.delete('save')
    conflict.value = null
    isEditing.value = false
    saveNotice.value = `已保存为版本 ${currentHistoryVersion(updated)}。`
    await loadVersions(note.id)
  } catch (e) {
    persistDraft()
    const detail = e?.response?.data?.detail
    if (e?.response?.status === 409 && detail && typeof detail === 'object') {
      conflict.value = {
        message: detail.message || '笔记已在其他位置更新，本地草稿仍完整保留。',
        currentVersion: detail.current_version,
      }
    } else {
      console.error('更新笔记失败:', e)
      saveError.value = apiMessage(e, '保存失败，本地草稿仍保留在当前设备。')
    }
  } finally {
    saving.value = false
  }
}

async function submitAddNote() {
  if (!newForm.value.content.trim() || newSaving.value) return
  newSaving.value = true
  newError.value = ''
  const tags = newForm.value.tags ? newForm.value.tags.split(/[,，]/).map(t => t.trim()).filter(Boolean) : []
  const concepts = newForm.value.concepts ? newForm.value.concepts.split(/[,，]/).map(c => c.trim()).filter(Boolean) : []
  const signature = JSON.stringify([newForm.value.content, tags, concepts])
  try {
    const res = await createNote(props.studentId, {
      content: newForm.value.content,
      source_type: 'manual',
      tags,
      concepts,
      idempotency_key: operationKey('create', signature),
    })
    newForm.value = { content: '', tags: '', concepts: '' }
    operationCache.delete('create')
    showAddModal.value = false
    replaceNote(res)
    selectedNoteId.value = res.id
    router.replace({ query: { ...route.query, note_id: res.id } })
  } catch (e) {
    console.error('添加笔记失败:', e)
    newError.value = apiMessage(e, '新笔记没有保存，输入仍保留。')
  } finally {
    newSaving.value = false
  }
}

// 删除笔记
async function removeNote(id) {
  if (!confirm('确认删除该则学习笔记吗？该操作不可撤销。')) return
  try {
    await deleteNote(id)
    clearStoredDraft(id)
    if (selectedNoteId.value === id) {
      selectedNoteId.value = null
    }
    await load()
  } catch (e) {
    console.error('删除笔记失败:', e)
    saveError.value = apiMessage(e, '删除失败，笔记仍然保留。')
  }
}

async function triggerAiPolish() {
  const note = selectedNote.value
  if (!note || polishLoading.value) return
  if (isDirty.value) {
    polishError.value = '请先保存当前修改，再基于已保存版本生成排版建议。'
    return
  }
  polishLoading.value = true
  polishError.value = ''
  try {
    const signature = JSON.stringify([note.id, note.lock_version, note.content])
    const data = await aiPolishNote({
      content: note.content,
      note_id: note.id,
      expected_version: note.lock_version,
      idempotency_key: operationKey('polish', signature),
    })
    if (data.suggestion_status !== 'ready' || !data.note?.ai_suggestion) {
      polishError.value = 'AI 排版建议暂时不可用，原笔记没有改变。'
      return
    }
    replaceNote(data.note)
    await nextTick()
    operationCache.delete('polish')
    saveNotice.value = 'AI 建议已生成，请在右侧预览后决定是否应用。'
  } catch (e) {
    polishError.value = apiMessage(e, 'AI 排版建议暂时不可用，原笔记没有改变。')
  } finally {
    polishLoading.value = false
  }
}

async function applyAiSuggestion() {
  const note = selectedNote.value
  const suggestion = note?.ai_suggestion
  if (!note || !suggestion || saving.value) return
  if (Number(suggestion.base_version) !== Number(note.lock_version)) {
    polishError.value = '这条建议基于旧版本生成，请重新生成后再应用。'
    return
  }
  saving.value = true
  polishError.value = ''
  try {
    const signature = JSON.stringify([note.id, note.lock_version, suggestion.content])
    const updated = await updateNote(note.id, {
      student_id: props.studentId,
      content: suggestion.content,
      tags: suggestion.tags || note.tags || [],
      concepts: suggestion.concepts || note.concepts || [],
      expected_version: note.lock_version,
      idempotency_key: operationKey('apply-ai', signature),
      change_type: 'ai_suggestion_applied',
    })
    clearStoredDraft(note.id)
    replaceNote(updated)
    await nextTick()
    operationCache.delete('apply-ai')
    isEditing.value = false
    saveNotice.value = `AI 建议已作为版本 ${currentHistoryVersion(updated)} 保存，旧正文仍在历史中。`
    await loadVersions(note.id)
  } catch (error) {
    polishError.value = apiMessage(error, 'AI 建议没有应用，原正文仍保留。')
  } finally {
    saving.value = false
  }
}

async function syncConflictBase() {
  const draft = { ...editForm.value }
  persistDraft()
  try {
    const data = await getNotes(props.studentId)
    notes.value = Array.isArray(data) ? data : data.notes || []
    await nextTick()
    const latest = notes.value.find(note => note.id === selectedNoteId.value)
    if (!latest) throw new Error('最新笔记不存在')
    formHydrating.value = true
    editForm.value = draft
    formHydrating.value = false
    conflict.value = null
    saveNotice.value = `已同步到版本 ${currentHistoryVersion(latest)}，本地草稿仍保留；再次保存会创建新版本。`
    persistDraft()
    operationCache.delete('save')
  } catch (error) {
    saveError.value = apiMessage(error, '最新版本暂时无法载入，本地草稿仍保留。')
  }
}

function discardDraft() {
  const note = selectedNote.value
  if (!note || !confirm('放弃当前未保存草稿并恢复已保存版本？')) return
  clearStoredDraft(note.id)
  hydrateForm(note)
  isEditing.value = false
  conflict.value = null
  saveNotice.value = '已恢复已保存版本。'
}

async function restoreVersion(version) {
  const note = selectedNote.value
  if (!note || restoringVersion.value || !confirm(`恢复到版本 ${version.version_number}？当前正文会切换到该历史版本。`)) return
  restoringVersion.value = version.version_number
  saveError.value = ''
  try {
    const signature = `${note.id}:${note.lock_version}:${version.version_number}`
    const updated = await restoreNoteVersion(note.id, version.version_number, {
      expected_version: note.lock_version,
      idempotency_key: operationKey('restore', signature),
    })
    clearStoredDraft(note.id)
    replaceNote(updated)
    await nextTick()
    operationCache.delete('restore')
    isEditing.value = false
    saveNotice.value = `已恢复到版本 ${currentHistoryVersion(updated)}，历史版本数量未增加。`
    await loadVersions(note.id)
  } catch (error) {
    saveError.value = apiMessage(error, '历史版本没有恢复，当前正文未改变。')
  } finally {
    restoringVersion.value = null
  }
}

function sourceLocation(source) {
  if (!source) return ''
  if (source.location_label) return source.location_label
  if (source.page_number) return `第 ${source.page_number} 页`
  if (source.chapter_title) return source.chapter_title
  if (source.concept) return source.concept
  if (source.resource_version_id) return `资源版本 ${source.resource_version_id}`
  return ''
}

function exportMarkdown(note) {
  if (!note) return
  const source = note.source_context || {}
  const sourceStatus = source.available === false ? '当前不可用，保留历史引用' : '可用'
  const content = [
    `# ${noteTitle(note)}`,
    `> 来源: ${source.title || noteSourceLabel(note)} | ${sourceLocation(source) || '个人记录'} | ${sourceStatus}`,
    `> 创建时间: ${new Date(note.created_at).toLocaleString()} | 当前版本: ${currentHistoryVersion(note)}`,
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
  saveNotice.value = 'Markdown 已导出。'
}

async function exportPdf(note) {
  if (!note || pdfExporting.value) return
  pdfExporting.value = true
  try {
    const noteContent = note.content || note.content_markdown || note.text || editForm.value?.content || ''
    const noteTitle = note.title || (note.concepts && note.concepts[0]) || '学习笔记'
    await exportNotePdf({
      title: noteTitle,
      content: noteContent,
      subtitle: `来源: ${note.source_context?.title || noteSourceLabel(note)} · ${sourceLocation(note.source_context) || '个人记录'}`,
      tags: Array.isArray(note.tags) ? note.tags.join(', ') : (note.tags || ''),
      source: note.source || '学习笔记',
      concepts: Array.isArray(note.concepts) ? note.concepts : [],
    })
    saveNotice.value = 'PDF 已导出。'
  } catch (e) {
    saveError.value = apiMessage(e, 'PDF 导出失败，当前笔记仍保留。')
  } finally {
    pdfExporting.value = false
  }
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
        blockHtml = `<div class="my-3 p-4 bg-white border border-gray-200 rounded-lg text-sm flex flex-col items-center max-w-full"><div class="mermaid w-full flex justify-center" data-code="${escapedCode}"><div class="mermaid-loading flex flex-col items-center justify-center gap-1.5 py-6 text-gray-600 select-none"><div class="w-5 h-5 border-2 border-slate-700 border-t-transparent rounded-full animate-spin"></div><span class="text-sm text-slate-700 font-semibold">正在绘制思维导图...</span></div></div></div>`
      }
    } else {
      const cleanLang = (lang || 'python').trim().toLowerCase()
      blockHtml = `<pre class="p-3 bg-gray-900 rounded-lg overflow-x-auto text-sm leading-relaxed my-2 language-${cleanLang}"><code class="language-${cleanLang}">${code.trim()}</code></pre>`
    }
    const idx = codeBlocks.length
    codeBlocks.push(blockHtml)
    return `@@CODEBLOCKTOKEN${idx}@@`
  })

  // Extract single-backtick inline code blocks to protect them from subscript mangling
  html = html.replace(/`([^`\n]+)`/g, (_, code) => {
    const blockHtml = `<code class="px-1.5 py-0.5 bg-gray-100 text-slate-800 rounded font-mono text-sm font-medium">${code}</code>`
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
      processedLines.push(`<li class="ml-4 text-sm text-gray-700 my-1 leading-relaxed">${content}</li>`)
    } else {
      if (inList) { processedLines.push('</ul>'); inList = false }
      processedLines.push(line)
    }
  }
  if (inTable) processedLines.push(generateTableHtml(tableHeader, tableRows))
  if (inList) processedLines.push('</ul>')
  html = processedLines.join('\n')

  function generateTableHtml(header, rows) {
    let tableHtml = '<div class="overflow-x-auto my-4 border border-gray-200/80 rounded-lg bg-white"><table class="min-w-full divide-y divide-gray-200">'
    if (header?.length) {
      tableHtml += '<thead class="bg-gray-50/75"><tr>'
      header.forEach(h => { tableHtml += `<th class="px-4 py-2.5 text-left text-sm font-semibold text-gray-800">${h}</th>` })
      tableHtml += '</tr></thead>'
    }
    tableHtml += '<tbody class="divide-y divide-gray-100 bg-white">'
    rows.forEach(row => {
      tableHtml += '<tr class="hover:bg-gray-50/50 transition-colors">'
      row.forEach(cell => { tableHtml += `<td class="px-4 py-2 text-sm text-gray-700">${cell}</td>` })
      tableHtml += '</tr>'
    })
    tableHtml += '</tbody></table></div>'
    return tableHtml
  }

  html = html.replace(/!\[([^\]]*)\]\s*\(([^)]+)\)/g, (match, alt, url) => `<img src="${url.replace(/\s+/g, '')}" alt="${alt}" class="max-w-full max-h-[300px] object-contain rounded-lg my-3 border border-gray-100 bg-white p-1" />`)
  html = html.replace(/\*\*([^*]+)\*\*/g, '<strong class="font-bold text-gray-900">$1</strong>')
  html = html.replace(/\*([^*]+)\*/g, '<em class="italic text-gray-800">$1</em>')
  // Inline code is already extracted and protected as @@CODEBLOCKTOKEN@@ above
  html = html.replace(/^### (.*$)/gim, '<h4 class="text-sm font-bold text-gray-800 mt-4 mb-1.5 flex items-center gap-1">$1</h4>')
  html = html.replace(/^## (.*$)/gim, '<h3 class="text-sm font-semibold text-gray-900 mt-5 mb-2 border-b border-gray-100 pb-1 flex items-center gap-1.5">$1</h3>')
  html = html.replace(/^# (.*$)/gim, '<h2 class="text-base font-bold text-gray-900 mt-6 mb-3 flex items-center gap-2">$1</h2>')
  html = html.replace(/\n\n/g, '<div class="h-2.5"></div>')

  function renderMath(math, display) {
    if (window.katex) {
      try { return window.katex.renderToString(math, { displayMode: display, throwOnError: false, trust: true }) } catch (err) { console.error(err) }
    }
    const cleanMath = math.replace(/\\Sigma/g, '∑').replace(/\\sigma/g, 'σ').replace(/\\mu/g, 'μ').replace(/\\beta/g, 'β').replace(/\\theta/g, 'θ').replace(/\\alpha/g, 'α').replace(/\\lambda/g, 'λ').replace(/\\partial/g, '∂').replace(/\\infty/g, '∞').replace(/\\cdot/g, '·').replace(/\\times/g, '×')
    return display ? `<div class="my-3.5 p-4 bg-gray-50/75 border border-gray-100 rounded-lg text-center font-serif text-sm overflow-x-auto text-gray-800">${cleanMath}</div>` : `<span class="font-serif italic bg-gray-50/75 px-1.5 py-0.5 rounded text-sm text-gray-800 border border-gray-100/50">${cleanMath}</span>`
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
            primaryColor: '#edf1f2',
            primaryTextColor: '#06141b',
            lineColor: '#60727c',
            secondaryColor: '#f5f7f7',
            tertiaryColor: '#ffffff',
            fontSize: '14px'
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
  const category = normalizedSourceFilter(route.query.category)
  activeSourceFilter.value = category
  if (routeQueryValue(route.query.category) !== category) {
    await router.replace({ query: { ...route.query, category } })
  }
  if (route.query.search) {
    searchQuery.value = route.query.search
  } else if (route.query.q) {
    searchQuery.value = route.query.q
  }
  await load()
  renderAllDiagrams()
})
</script>

<template>
  <div class="notes-page" data-testid="notes-workspace">
    <section class="notes-shell" aria-label="学习笔记工作区">
      <aside class="notes-sidebar" aria-label="笔记分类与列表" data-testid="notes-explorer">
        <header class="sidebar-header">
          <div class="sidebar-title-row">
            <div>
              <h1>学习笔记</h1>
              <p>{{ notes.length }} 则笔记，按来源归档</p>
            </div>
            <button type="button" class="icon-button" title="新建笔记" aria-label="新建笔记" @click="showAddModal = true">
              <Plus :size="18" />
            </button>
          </div>
          <SearchField
            v-model="searchQuery"
            class="notes-search-field"
            aria-label="搜索笔记"
            placeholder="搜索正文、概念或标签"
          />
        </header>

        <nav class="source-filter-list" aria-label="按来源筛选">
          <button
            v-for="filter in sourceFilters"
            :key="filter.id"
            type="button"
            class="source-filter-button"
            :class="{ 'is-active': activeSourceFilter === filter.id }"
            :aria-pressed="activeSourceFilter === filter.id"
            @click="setSourceFilter(filter.id)"
          >
            <span>{{ filter.label }}</span>
            <span class="filter-count">{{ filter.count }}</span>
          </button>
        </nav>

        <details v-if="allConcepts.length || allTags.length" class="filter-disclosure">
          <summary>
            <span><SlidersHorizontal :size="16" /> 更多筛选</span>
            <ChevronDown :size="16" class="disclosure-chevron" />
          </summary>
          <div class="filter-groups">
            <div v-if="allConcepts.length" class="filter-group">
              <p>知识点</p>
              <div class="filter-options">
                <button
                  v-for="concept in allConcepts"
                  :key="concept"
                  type="button"
                  class="filter-chip"
                  :class="{ 'is-selected': selectedConcepts.has(concept) }"
                  :aria-pressed="selectedConcepts.has(concept)"
                  @click="toggleConceptFilter(concept)"
                >{{ concept }}</button>
              </div>
            </div>
            <div v-if="allTags.length" class="filter-group">
              <p>标签</p>
              <div class="filter-options">
                <button
                  v-for="tag in allTags"
                  :key="tag"
                  type="button"
                  class="filter-chip"
                  :class="{ 'is-selected': selectedTags.has(tag) }"
                  :aria-pressed="selectedTags.has(tag)"
                  @click="toggleTagFilter(tag)"
                >{{ tag }}</button>
              </div>
            </div>
          </div>
        </details>

        <div v-if="hasActiveFilters" class="filter-summary">
          <span>显示 {{ filteredNotes.length }} 则</span>
          <button type="button" @click="clearFilters">清除筛选</button>
        </div>

        <div ref="notesListRef" class="notes-list" aria-live="polite" @scroll.passive="persistNotesListScroll">
          <div v-if="loading" class="sidebar-state">
            <Loader2 :size="22" class="spin" />
            <p>正在载入笔记</p>
          </div>
          <div v-else-if="loadError" class="sidebar-state is-error">
            <AlertCircle :size="22" />
            <p>{{ loadError }}</p>
            <button type="button" class="text-button" @click="load">重新载入</button>
          </div>
          <div v-else-if="filteredNotes.length === 0" class="sidebar-state">
            <StickyNote :size="24" />
            <p>{{ notes.length ? '没有符合筛选条件的笔记' : '还没有学习笔记' }}</p>
            <button v-if="!notes.length" type="button" class="text-button" @click="showAddModal = true">新建第一则</button>
          </div>
          <template v-else>
            <button
              v-for="note in filteredNotes"
              :key="note.id"
              type="button"
              class="note-list-item"
              :class="{ 'is-active': selectedNoteId === note.id }"
              :aria-current="selectedNoteId === note.id ? 'true' : undefined"
              @click="selectNote(note.id)"
            >
              <span class="note-item-topline">
                <strong>{{ noteTitle(note) }}</strong>
                <time :datetime="note.updated_at || note.created_at">{{ ago(note.updated_at || note.created_at) }}</time>
              </span>
              <span class="note-item-excerpt">{{ noteExcerpt(note) }}</span>
              <span class="note-item-meta">
                <span class="source-label">{{ noteSourceLabel(note) }}</span>
                <span v-if="note.current_version_number || note.lock_version" class="version-label">v{{ currentHistoryVersion(note) }}</span>
              </span>
            </button>
          </template>
        </div>
      </aside>

      <main class="note-document" aria-label="笔记正文" data-testid="notes-document">
        <div v-if="loading" class="workspace-state">
          <Loader2 :size="28" class="spin" />
          <h2>正在准备笔记</h2>
          <p>正文、来源与版本历史会在载入后显示。</p>
        </div>
        <div v-else-if="loadError" class="workspace-state is-error">
          <AlertCircle :size="28" />
          <h2>笔记暂时无法载入</h2>
          <p>{{ loadError }}</p>
          <button type="button" class="button secondary" @click="load">重新载入</button>
        </div>
        <div v-else-if="!selectedNote" class="workspace-state">
          <StickyNote :size="32" />
          <h2>{{ notes.length ? '选择一则笔记' : '从第一则笔记开始' }}</h2>
          <p>{{ notes.length ? '左侧选择后即可阅读、编辑和追溯来源。' : '新建笔记，或从知识库选区和学习资源中保存。' }}</p>
          <button v-if="!notes.length" type="button" class="button primary" @click="showAddModal = true">
            <Plus :size="17" /> 新建笔记
          </button>
        </div>

        <template v-else>
          <header class="document-header">
            <div class="document-title-block">
              <div class="document-context-line">
                <span>{{ noteSourceLabel(selectedNote) }}</span>
                <span aria-hidden="true">/</span>
                <span>版本 {{ currentHistoryVersion(selectedNote) }}</span>
                <span v-if="isDirty" class="draft-badge">本地草稿</span>
              </div>
              <h2>{{ noteTitle(selectedNote) }}</h2>
              <p>更新于 {{ formatDateTime(selectedNote.updated_at || selectedNote.created_at) }}</p>
            </div>
            <div class="document-actions">
              <button
                v-if="isEditing"
                type="button"
                class="button secondary"
                @click="isEditing = false"
              >
                <Eye :size="17" /> 预览
              </button>
              <button
                v-else
                type="button"
                class="button secondary"
                @click="isEditing = true"
              >
                <Edit3 :size="17" /> 编辑
              </button>
              <button
                v-if="isEditing"
                type="button"
                class="button primary"
                :disabled="saving || !editForm.content.trim() || !isDirty"
                @click="saveEdit"
              >
                <Loader2 v-if="saving" :size="17" class="spin" />
                <Save v-else :size="17" />
                {{ saving ? '正在保存' : '保存新版本' }}
              </button>
              <details class="toolbar-menu">
                <summary class="icon-button" title="更多操作" aria-label="更多操作">
                  <MoreHorizontal :size="19" />
                </summary>
                <div class="toolbar-popover">
                  <button type="button" @click="forceRefreshDiagrams">
                    <RotateCw :size="17" /> 刷新公式与图表
                  </button>
                  <button type="button" @click="exportMarkdown(selectedNote)">
                    <Download :size="17" /> 导出 Markdown
                  </button>
                  <button type="button" :disabled="pdfExporting" @click="exportPdf(selectedNote)">
                    <FileText :size="17" /> {{ pdfExporting ? '正在导出 PDF' : '导出 PDF' }}
                  </button>
                  <button type="button" class="danger-action" @click="removeNote(selectedNote.id)">
                    <Trash2 :size="17" /> 删除笔记
                  </button>
                </div>
              </details>
            </div>
          </header>

          <div v-if="conflict" class="feedback-banner is-warning" role="alert" data-testid="notes-conflict">
            <CircleAlert :size="19" />
            <div>
              <strong>检测到更新冲突</strong>
              <p>{{ conflict.message }} 当前服务端版本为 {{ conflict.currentVersion }}。</p>
            </div>
            <div class="feedback-actions">
              <button type="button" @click="syncConflictBase">同步最新版本</button>
              <button type="button" @click="discardDraft">放弃本地草稿</button>
            </div>
          </div>
          <div v-else-if="saveError" class="feedback-banner is-error" role="alert">
            <AlertCircle :size="19" />
            <div>
              <strong>操作没有完成</strong>
              <p>{{ saveError }}</p>
            </div>
          </div>
          <div v-else-if="saveNotice" class="feedback-banner" role="status">
            <Check :size="19" />
            <p>{{ saveNotice }}</p>
          </div>

          <div class="document-body">
            <div v-if="!isEditing" class="document-preview">
              <div class="notes-rich-text" v-html="renderMarkdown(editForm.content)" />
            </div>
            <div v-else class="document-editor">
              <div class="editor-toolbar">
                <span>Markdown 正文</span>
                <span>支持公式、代码和 Mermaid 图表</span>
              </div>
              <textarea
                v-model="editForm.content"
                aria-label="笔记正文"
                placeholder="记录你的理解、推导和仍需解决的问题"
              />
              <div class="edit-meta-grid">
                <label>
                  <span>关联知识点</span>
                  <input v-model="editForm.concepts" placeholder="多个知识点用逗号分隔" />
                </label>
                <label>
                  <span>标签</span>
                  <input v-model="editForm.tags" placeholder="多个标签用逗号分隔" />
                </label>
              </div>
              <div class="draft-controls">
                <p>{{ isDirty ? '修改已保存在本机草稿中，点击顶部“保存新版本”后同步。' : '当前内容与已保存版本一致。' }}</p>
                <button v-if="isDirty" type="button" class="text-button" @click="discardDraft">放弃草稿</button>
              </div>
            </div>
          </div>
        </template>
      </main>

      <aside class="note-context" aria-label="建议与历史" data-testid="notes-context">
        <div v-if="!selectedNote" class="context-empty">
          <History :size="24" />
          <p>选择笔记后，这里会显示排版建议和版本历史。</p>
        </div>
        <template v-else>
          <details class="context-section context-disclosure" data-testid="notes-ai-suggestion" open>
            <summary>
              <span><Sparkles :size="17" /> AI 排版建议</span>
              <ChevronDown :size="16" class="disclosure-chevron" />
            </summary>
            <div class="context-content">
              <p class="context-help">建议始终独立预览，只有你确认应用后才会另存新版本。</p>
              <p v-if="polishError" class="inline-error">{{ polishError }}</p>
              <div v-if="selectedNote.ai_suggestion" class="suggestion-preview">
                <div class="suggestion-meta">基于版本 {{ selectedNote.ai_suggestion.base_version }}</div>
                <div class="notes-rich-text compact" v-html="renderMarkdown(selectedNote.ai_suggestion.content)" />
                <button type="button" class="button primary full-width" :disabled="saving" @click="applyAiSuggestion">
                  <Save :size="17" /> 应用并另存新版本
                </button>
              </div>
              <button
                v-else
                type="button"
                class="button secondary full-width"
                :disabled="polishLoading || isDirty"
                @click="triggerAiPolish"
              >
                <Loader2 v-if="polishLoading" :size="17" class="spin" />
                <Sparkles v-else :size="17" />
                {{ polishLoading ? '正在生成建议' : '生成排版建议' }}
              </button>
              <p v-if="isDirty && !selectedNote.ai_suggestion" class="context-help">先保存当前草稿，再生成基于该版本的建议。</p>
            </div>
          </details>

          <details class="context-section context-disclosure" data-testid="notes-history" open>
            <summary>
              <span><History :size="17" /> 版本历史</span>
              <span class="summary-count">{{ selectedNote.version_count || versions.length }}</span>
              <ChevronDown :size="16" class="disclosure-chevron" />
            </summary>
            <div class="context-content version-list">
              <div v-if="versionsLoading" class="inline-state"><Loader2 :size="17" class="spin" /> 正在载入历史</div>
              <div v-else-if="versionsError" class="inline-state is-error">
                <span>{{ versionsError }}</span>
                <button type="button" class="text-button" @click="loadVersions(selectedNote.id)">重试</button>
              </div>
              <div v-else-if="!versions.length" class="inline-state">还没有历史版本</div>
              <template v-else>
                <article v-for="version in versions" :key="version.id" class="version-row">
                  <div>
                    <strong>版本 {{ version.version_number }}</strong>
                    <span>{{ versionChangeLabel(version) }}</span>
                    <time :datetime="version.created_at">{{ formatDateTime(version.created_at) }}</time>
                  </div>
                  <span v-if="version.version_number === currentHistoryVersion(selectedNote)" class="current-version">当前</span>
                  <button
                    v-else
                    type="button"
                    class="icon-button compact-button"
                    :disabled="restoringVersion === version.version_number"
                     :title="`恢复到版本 ${version.version_number}`"
                     :aria-label="`恢复到版本 ${version.version_number}`"
                    @click="restoreVersion(version)"
                  >
                    <Loader2 v-if="restoringVersion === version.version_number" :size="16" class="spin" />
                    <ArchiveRestore v-else :size="16" />
                  </button>
                </article>
              </template>
            </div>
          </details>

        </template>
      </aside>
    </section>

    <div v-if="showAddModal" class="modal-backdrop" role="presentation" @click.self="showAddModal = false">
      <section class="modal-panel add-note-modal" role="dialog" aria-modal="true" aria-labelledby="add-note-title">
        <header class="modal-header">
          <div>
            <h2 id="add-note-title"><Plus :size="18" /> 新建学习笔记</h2>
            <p>个人记录会保存为可继续编辑的版本。</p>
          </div>
          <button type="button" class="icon-button" title="关闭" aria-label="关闭新建笔记" @click="showAddModal = false">
            <X :size="18" />
          </button>
        </header>
        <div class="modal-body">
          <p v-if="newError" class="inline-error" role="alert">{{ newError }}</p>
          <label class="form-field">
            <span>笔记正文</span>
            <textarea v-model="newForm.content" placeholder="记录你的理解、推导和问题，支持 Markdown 与 LaTeX" />
          </label>
          <div class="modal-form-grid">
            <label class="form-field">
              <span>核心知识点</span>
              <input v-model="newForm.concepts" placeholder="例如：卷积核、梯度下降" />
            </label>
            <label class="form-field">
              <span>标签</span>
              <input v-model="newForm.tags" placeholder="例如：重点、待复习" />
            </label>
          </div>
        </div>
        <footer class="modal-footer">
          <button type="button" class="button secondary" @click="showAddModal = false">取消</button>
          <button type="button" class="button primary" :disabled="newSaving || !newForm.content.trim()" @click="submitAddNote">
            <Loader2 v-if="newSaving" :size="17" class="spin" />
            <Save v-else :size="17" />
            {{ newSaving ? '正在保存' : '保存笔记' }}
          </button>
        </footer>
      </section>
    </div>

  </div>
</template>

<style scoped>
.notes-page {
  width: 100%;
  color: var(--color-text);
  font-family: var(--font-sans);
  font-size: 15px;
  line-height: 1.6;
}

.notes-shell {
  display: grid;
  width: 100%;
  height: calc(100vh - 112px);
  min-height: 600px;
  grid-template-columns: 250px minmax(450px, 1fr) 294px;
  overflow: hidden;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-panel);
  background: var(--color-surface);
}

.notes-sidebar,
.note-document,
.note-context {
  min-width: 0;
  min-height: 0;
}

.notes-sidebar {
  display: flex;
  flex-direction: column;
  border-right: 1px solid var(--color-border);
  background: var(--color-surface);
}

.sidebar-header {
  padding: 20px 16px 16px;
  border-bottom: 1px solid var(--color-border);
}

.sidebar-title-row,
.document-header,
.document-actions,
.context-heading,
.context-action-row,
.modal-header,
.modal-footer,
.draft-controls,
.feedback-actions {
  display: flex;
  align-items: center;
}

.sidebar-title-row,
.context-heading,
.modal-header,
.draft-controls {
  justify-content: space-between;
}

.sidebar-title-row h1,
.document-title-block h2,
.workspace-state h2,
.modal-header h2 {
  margin: 0;
  color: var(--color-text);
  letter-spacing: 0;
}

.sidebar-title-row h1 {
  font-size: 20px;
  font-weight: 700;
}

.sidebar-title-row p,
.document-title-block p,
.context-heading p,
.modal-header p {
  margin: 2px 0 0;
  color: var(--color-text-secondary);
  font-size: 14px;
}

.icon-button {
  display: inline-grid;
  width: 36px;
  height: 36px;
  flex: 0 0 36px;
  place-items: center;
  padding: 0;
  color: var(--color-text-secondary);
  border: 1px solid var(--color-border-strong);
  border-radius: var(--radius-control);
  background: var(--color-surface);
  cursor: pointer;
  transition: color 150ms ease, border-color 150ms ease, background-color 150ms ease;
}

.icon-button:hover:not(:disabled) {
  color: var(--color-text);
  border-color: var(--color-text-secondary);
  background: var(--color-surface-subtle);
}

.compact-button {
  width: 32px;
  height: 32px;
  flex-basis: 32px;
}

.notes-search-field { margin-top: 16px; background: var(--color-surface-subtle); }

.source-filter-list {
  padding: 10px 8px;
  border-bottom: 1px solid var(--color-border);
}

.source-filter-button {
  display: flex;
  width: 100%;
  min-height: 36px;
  align-items: center;
  justify-content: space-between;
  padding: 7px 10px;
  color: var(--color-text-secondary);
  border: 0;
  border-radius: var(--radius-control);
  background: transparent;
  font-size: 14px;
  text-align: left;
  cursor: pointer;
}

.source-filter-button:hover,
.source-filter-button.is-active {
  color: var(--color-text);
  background: var(--color-accent-soft);
}

.source-filter-button.is-active {
  font-weight: 650;
}

.filter-count,
.summary-count,
.version-label {
  color: var(--color-text-muted);
  font-variant-numeric: tabular-nums;
}

.filter-disclosure,
.context-disclosure,
.toolbar-menu {
  position: relative;
}

.filter-disclosure {
  border-bottom: 1px solid var(--color-border);
}

.filter-disclosure > summary,
.context-disclosure > summary {
  list-style: none;
  cursor: pointer;
  user-select: none;
}

.filter-disclosure > summary::-webkit-details-marker,
.context-disclosure > summary::-webkit-details-marker,
.toolbar-menu > summary::-webkit-details-marker {
  display: none;
}

.filter-disclosure > summary {
  display: flex;
  min-height: 42px;
  align-items: center;
  justify-content: space-between;
  padding: 8px 16px;
  color: var(--color-text-secondary);
  font-size: 14px;
  font-weight: 600;
}

.filter-disclosure > summary > span,
.context-disclosure > summary > span:first-child {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}

.disclosure-chevron {
  transition: transform 150ms ease;
}

details[open] > summary .disclosure-chevron {
  transform: rotate(180deg);
}

.filter-groups {
  max-height: 220px;
  padding: 0 16px 14px;
  overflow-y: auto;
}

.filter-group + .filter-group {
  margin-top: 14px;
}

.filter-group > p {
  margin: 0 0 7px;
  color: var(--color-text-secondary);
  font-size: 14px;
  font-weight: 600;
}

.filter-options {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.filter-chip {
  min-height: 30px;
  padding: 4px 9px;
  color: var(--color-text-secondary);
  border: 1px solid var(--color-border);
  border-radius: 999px;
  background: var(--color-surface);
  font-size: 14px;
  cursor: pointer;
}

.filter-chip:hover,
.filter-chip.is-selected {
  color: #ffffff;
  border-color: var(--color-accent);
  background: var(--color-accent);
}

.filter-summary {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 16px;
  color: var(--color-text-secondary);
  border-bottom: 1px solid var(--color-border);
  background: var(--color-surface-subtle);
  font-size: 14px;
}

.filter-summary button,
.text-button,
.feedback-actions button {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 0;
  color: var(--color-text);
  border: 0;
  background: transparent;
  font-size: 14px;
  font-weight: 650;
  text-decoration: underline;
  text-underline-offset: 3px;
  cursor: pointer;
}

.notes-list {
  flex: 1;
  overflow-y: auto;
}

.note-list-item {
  display: flex;
  width: 100%;
  flex-direction: column;
  gap: 7px;
  padding: 14px 16px;
  color: var(--color-text);
  border: 0;
  border-bottom: 1px solid var(--color-border);
  border-radius: 0;
  background: var(--color-surface);
  text-align: left;
  cursor: pointer;
}

.note-list-item:hover,
.note-list-item.is-active {
  background: var(--color-surface-subtle);
}

.note-list-item.is-active {
  box-shadow: inset 2px 0 0 var(--color-accent);
}

.note-item-topline,
.note-item-meta {
  display: flex;
  align-items: center;
}

.note-item-topline {
  justify-content: space-between;
  gap: 8px;
}

.note-item-topline strong {
  min-width: 0;
  overflow: hidden;
  font-size: 15px;
  font-weight: 650;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.note-item-topline time,
.note-item-meta,
.note-item-excerpt {
  color: var(--color-text-secondary);
  font-size: 14px;
}

.note-item-topline time {
  flex: 0 0 auto;
  font-variant-numeric: tabular-nums;
}

.note-item-excerpt {
  display: -webkit-box;
  overflow: hidden;
  line-height: 1.55;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}

.note-item-meta {
  min-width: 0;
  gap: 8px;
}

.source-label {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.review-marker {
  margin-left: auto;
}

.sidebar-state,
.workspace-state,
.context-empty,
.inline-state {
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--color-text-secondary);
  text-align: center;
}

.sidebar-state {
  min-height: 180px;
  flex-direction: column;
  gap: 10px;
  padding: 20px;
}

.sidebar-state p,
.workspace-state p,
.context-empty p,
.inline-state {
  margin: 0;
  font-size: 14px;
}

.is-error {
  color: var(--color-danger);
}

.note-document {
  display: flex;
  flex-direction: column;
  background: var(--color-surface);
}

.workspace-state {
  height: 100%;
  flex-direction: column;
  gap: 10px;
  padding: 40px;
}

.workspace-state h2 {
  font-size: 20px;
}

.workspace-state p {
  max-width: 430px;
}

.workspace-state .button {
  margin-top: 8px;
}

.compact-state {
  min-height: 180px;
}

.document-header {
  min-height: 88px;
  justify-content: space-between;
  gap: 18px;
  padding: 16px 20px;
  border-bottom: 1px solid var(--color-border);
}

.document-title-block {
  min-width: 0;
  flex: 1;
}

.document-title-block h2 {
  overflow: hidden;
  font-size: 22px;
  font-weight: 700;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.document-context-line {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 7px;
  margin-bottom: 3px;
  color: var(--color-text-secondary);
  font-size: 14px;
}

.draft-badge,
.status-badge,
.current-version {
  display: inline-flex;
  min-height: 24px;
  align-items: center;
  padding: 2px 8px;
  border: 1px solid var(--color-border-strong);
  border-radius: 999px;
  background: var(--color-surface-subtle);
  font-size: 14px;
  font-weight: 600;
}

.document-actions {
  flex: 0 0 auto;
  gap: 8px;
}

.button {
  display: inline-flex;
  min-height: 38px;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 8px 13px;
  border: 1px solid transparent;
  border-radius: var(--radius-control);
  font-size: 14px;
  font-weight: 650;
  line-height: 1.2;
  cursor: pointer;
  transition: color 150ms ease, background-color 150ms ease, border-color 150ms ease;
}

.button.primary {
  color: #ffffff;
  border-color: var(--color-accent);
  background: var(--color-accent);
}

.button.primary:hover:not(:disabled) {
  background: #06141b;
}

.button.secondary {
  color: var(--color-text);
  border-color: var(--color-border-strong);
  background: var(--color-surface);
}

.button.secondary:hover:not(:disabled) {
  background: var(--color-surface-subtle);
}

.button:disabled,
.icon-button:disabled,
.toolbar-popover button:disabled {
  opacity: 0.48;
  cursor: not-allowed;
}

.full-width {
  width: 100%;
}

.toolbar-menu > summary {
  list-style: none;
}

.toolbar-popover {
  position: absolute;
  z-index: 20;
  top: calc(100% + 8px);
  right: 0;
  width: 210px;
  overflow: hidden;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-panel);
  background: var(--color-surface);
  box-shadow: var(--shadow-popover);
}

.toolbar-popover button {
  display: flex;
  width: 100%;
  min-height: 40px;
  align-items: center;
  gap: 10px;
  padding: 8px 12px;
  color: var(--color-text);
  border: 0;
  border-bottom: 1px solid var(--color-border);
  background: var(--color-surface);
  font-size: 14px;
  text-align: left;
  cursor: pointer;
}

.toolbar-popover button:last-child {
  border-bottom: 0;
}

.toolbar-popover button:hover {
  background: var(--color-surface-subtle);
}

.toolbar-popover .danger-action {
  color: var(--color-danger);
}

.feedback-banner {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  align-items: center;
  gap: 10px;
  padding: 10px 20px;
  color: var(--color-text);
  border-bottom: 1px solid var(--color-border);
  background: var(--color-success-soft);
}

.feedback-banner.is-warning {
  background: var(--color-surface-subtle);
}

.feedback-banner.is-error {
  color: var(--color-danger);
  background: var(--color-danger-soft);
}

.feedback-banner strong,
.feedback-banner p {
  margin: 0;
  font-size: 14px;
}

.feedback-actions {
  gap: 12px;
}

.document-body {
  min-height: 0;
  flex: 1;
  overflow: hidden;
  background: var(--color-page);
}

.document-preview,
.document-editor {
  height: 100%;
}

.document-preview {
  padding: 28px clamp(24px, 4vw, 56px);
  overflow-y: auto;
  background: var(--color-surface);
}

.notes-rich-text {
  max-width: 74ch;
  margin: 0 auto;
  color: var(--color-text);
  font-family: var(--font-sans);
  font-size: 15px;
  line-height: 1.78;
  overflow-wrap: anywhere;
}

.notes-rich-text.compact {
  max-height: 250px;
  margin: 0;
  overflow-y: auto;
  font-size: 14px;
}

.notes-rich-text :deep(h2) {
  font-size: 22px;
}

.notes-rich-text :deep(h3) {
  font-size: 18px;
}

.notes-rich-text :deep(h4),
.notes-rich-text :deep(li),
.notes-rich-text :deep(td),
.notes-rich-text :deep(th),
.notes-rich-text :deep(code) {
  font-size: 14px !important;
}

.notes-rich-text :deep(pre) {
  border-radius: var(--radius-panel) !important;
}

.document-editor {
  display: grid;
  grid-template-rows: auto minmax(260px, 1fr) auto auto;
  background: var(--color-surface);
}

.editor-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 9px 16px;
  color: var(--color-text-secondary);
  border-bottom: 1px solid var(--color-border);
  background: var(--color-surface-subtle);
  font-size: 14px;
}

.editor-toolbar span:first-child {
  color: var(--color-text);
  font-weight: 650;
}

.document-editor > textarea {
  width: 100%;
  height: 100%;
  min-height: 260px;
  padding: 24px;
  resize: none;
  color: var(--color-text);
  border: 0;
  border-radius: 0;
  background: var(--color-surface);
  font-family: var(--font-mono);
  font-size: 15px;
  line-height: 1.75;
  outline: 0;
}

.edit-meta-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 14px;
  padding: 14px 20px;
  border-top: 1px solid var(--color-border);
}

.edit-meta-grid label,
.form-field {
  display: flex;
  flex-direction: column;
  gap: 6px;
  color: var(--color-text-secondary);
  font-size: 14px;
  font-weight: 600;
}

.edit-meta-grid input,
.form-field input,
.form-field textarea {
  width: 100%;
  min-height: 40px;
  padding: 8px 11px;
  color: var(--color-text);
  border: 1px solid var(--color-border-strong);
  border-radius: var(--radius-control);
  background: var(--color-surface);
  font-size: 15px;
  font-weight: 400;
}

.draft-controls {
  gap: 12px;
  padding: 9px 20px;
  color: var(--color-text-secondary);
  border-top: 1px solid var(--color-border);
  background: var(--color-surface-subtle);
}

.draft-controls p {
  margin: 0;
  font-size: 14px;
}

.note-context {
  overflow-y: auto;
  border-left: 1px solid var(--color-border);
  background: var(--color-surface);
}

.context-empty {
  height: 100%;
  flex-direction: column;
  gap: 10px;
  padding: 28px;
}

.context-section {
  padding: 18px 16px;
  border-bottom: 1px solid var(--color-border);
}

.context-heading {
  align-items: flex-start;
  gap: 10px;
}

.context-heading h3 {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 0;
  color: var(--color-text);
  font-size: 16px;
}

.status-badge {
  flex: 0 0 auto;
  color: var(--color-text-secondary);
}

.status-badge.is-unavailable {
  color: var(--color-danger);
  border-color: #e6bcbc;
  background: var(--color-danger-soft);
}

.source-title {
  display: block;
  margin-top: 16px;
  font-size: 15px;
  overflow-wrap: anywhere;
}

.source-location,
.source-warning,
.context-help,
.inline-error,
.suggestion-meta {
  margin: 6px 0 0;
  font-size: 14px;
  line-height: 1.55;
}

.source-location,
.context-help,
.suggestion-meta {
  color: var(--color-text-secondary);
}

.source-warning,
.inline-error {
  color: var(--color-danger);
}

.source-quote {
  max-height: 132px;
  margin: 14px 0 0;
  padding: 10px 12px;
  overflow-y: auto;
  color: var(--color-text-secondary);
  border: 0;
  border-radius: var(--radius-control);
  background: var(--color-surface-subtle);
  font-size: 14px;
  line-height: 1.65;
}

.source-details {
  margin: 14px 0 0;
  border-top: 1px solid var(--color-border);
}

.source-details > div {
  display: grid;
  grid-template-columns: 72px minmax(0, 1fr);
  gap: 8px;
  padding: 7px 0;
  border-bottom: 1px solid var(--color-border);
  font-size: 14px;
}

.source-details dt {
  color: var(--color-text-muted);
}

.source-details dd {
  min-width: 0;
  margin: 0;
  color: var(--color-text);
  overflow-wrap: anywhere;
}

.context-action-row {
  gap: 8px;
  margin-top: 14px;
}

.context-action-row .button {
  flex: 1;
}

.context-disclosure {
  padding: 0;
}

.context-disclosure > summary {
  display: grid;
  min-height: 52px;
  grid-template-columns: minmax(0, 1fr) auto auto;
  align-items: center;
  gap: 8px;
  padding: 12px 16px;
  color: var(--color-text);
  font-size: 15px;
  font-weight: 650;
}

.context-disclosure > summary:hover {
  background: var(--color-surface-subtle);
}

.context-content {
  padding: 0 16px 16px;
}

.context-help:first-child,
.inline-error:first-child {
  margin-top: 0;
}

.suggestion-preview {
  margin-top: 12px;
}

.suggestion-preview .full-width,
.learning-actions .full-width {
  margin-top: 10px;
}

.version-list {
  padding-bottom: 8px;
}

.inline-state {
  min-height: 72px;
  flex-direction: column;
  gap: 8px;
}

.version-row {
  display: flex;
  min-height: 62px;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 9px 0;
  border-top: 1px solid var(--color-border);
}

.version-row:first-of-type {
  border-top: 0;
}

.version-row > div {
  display: grid;
  min-width: 0;
  grid-template-columns: auto 1fr;
  gap: 0 8px;
}

.version-row strong,
.version-row span,
.version-row time {
  font-size: 14px;
}

.version-row span,
.version-row time {
  color: var(--color-text-secondary);
}

.version-row time {
  grid-column: 1 / -1;
  font-variant-numeric: tabular-nums;
}

.current-version {
  color: var(--color-text);
}

.review-schedule {
  display: grid;
  gap: 2px;
  margin-top: 12px;
  padding: 10px 12px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-control);
  background: var(--color-surface-subtle);
}

.review-schedule span,
.review-schedule strong {
  font-size: 14px;
}

.review-schedule span {
  color: var(--color-text-secondary);
}

.align-start {
  margin-top: 12px;
}

.modal-backdrop {
  position: fixed;
  z-index: 60;
  inset: 0;
  display: grid;
  place-items: center;
  padding: 24px;
  background: rgb(6 20 27 / 42%);
}

.modal-panel {
  display: flex;
  width: min(620px, calc(100vw - 48px));
  max-height: calc(100vh - 48px);
  flex-direction: column;
  overflow: hidden;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-panel);
  background: var(--color-surface);
  box-shadow: var(--shadow-popover);
}

.flashcard-modal {
  width: min(700px, calc(100vw - 48px));
}

.modal-header {
  gap: 16px;
  padding: 18px 20px;
  border-bottom: 1px solid var(--color-border);
}

.modal-header h2 {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 19px;
}

.modal-body {
  display: grid;
  gap: 16px;
  padding: 20px;
  overflow-y: auto;
}

.form-field textarea {
  min-height: 220px;
  resize: vertical;
  line-height: 1.7;
}

.modal-form-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 14px;
}

.modal-footer {
  justify-content: flex-end;
  gap: 10px;
  padding: 14px 20px;
  border-top: 1px solid var(--color-border);
  background: var(--color-surface-subtle);
}

.flashcard-body {
  min-height: 300px;
}

.flashcard-section {
  padding: 18px 0;
  border-bottom: 1px solid var(--color-border);
}

.flashcard-section > span {
  color: var(--color-text-secondary);
  font-size: 14px;
  font-weight: 650;
}

.flashcard-section > p {
  margin: 10px 0 0;
  color: var(--color-text);
  font-size: 17px;
  font-weight: 650;
  line-height: 1.7;
}

.answer-section {
  max-height: 330px;
  overflow-y: auto;
}

.reveal-answer {
  justify-self: center;
  margin: 20px 0;
}

.rating-footer {
  display: block;
}

.rating-footer > p {
  margin: 0 0 10px;
  color: var(--color-text-secondary);
  font-size: 14px;
  text-align: center;
}

.rating-options {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 8px;
}

.rating-options button {
  display: flex;
  min-height: 70px;
  flex-direction: column;
  align-items: flex-start;
  justify-content: center;
  gap: 3px;
  padding: 10px 12px;
  color: var(--color-text);
  border: 1px solid var(--color-border-strong);
  border-radius: var(--radius-control);
  background: var(--color-surface);
  text-align: left;
  cursor: pointer;
}

.rating-options button:hover {
  border-color: var(--color-text-secondary);
  background: var(--color-accent-soft);
}

.rating-options strong,
.rating-options span {
  font-size: 14px;
}

.rating-options span {
  color: var(--color-text-secondary);
}

.visually-hidden {
  position: absolute !important;
  width: 1px !important;
  height: 1px !important;
  padding: 0 !important;
  overflow: hidden !important;
  clip: rect(0, 0, 0, 0) !important;
  white-space: nowrap !important;
  border: 0 !important;
}

.spin {
  animation: note-spin 800ms linear infinite;
}

@keyframes note-spin {
  to { transform: rotate(360deg); }
}

@media (max-width: 1380px) {
  .notes-shell {
    grid-template-columns: 238px minmax(430px, 1fr) 282px;
  }

  .document-header {
    padding-inline: 16px;
  }

  .document-preview {
    padding-inline: 28px;
  }
}

@media (prefers-reduced-motion: reduce) {
  .spin {
    animation-duration: 1.6s;
  }
}

/* FB-FE-01: keep the note document dominant while retaining both supporting rails. */
.notes-shell {
  grid-template-columns: 190px minmax(420px, 1fr) 238px;
  gap: 0;
}

.sidebar-header,
.context-section {
  padding-right: 14px;
  padding-left: 14px;
}

.document-preview {
  padding-right: clamp(28px, 5vw, 72px);
  padding-left: clamp(28px, 5vw, 72px);
}

@media (max-width: 1100px) {
  .notes-shell {
    grid-template-columns: 176px minmax(390px, 1fr) 210px;
  }
}
</style>
