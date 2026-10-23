<script setup>
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  AlertTriangle,
  ArrowLeft,
  BookOpen,
  Check,
  Clipboard,
  Download,
  FileJson,
  FileText,
  GitCompare,
  History,
  LoaderCircle,
  MessageSquareText,
  Pencil,
  RefreshCw,
  Save,
  Send,
  X,
} from '@lucide/vue'
import IncrementalMarkdownRenderer from '../components/IncrementalMarkdownRenderer.vue'
import {
  compareM5ResourceVersions,
  createM5ResourceVersion,
  exportM5Resource,
  getM5Resource,
  restoreM5ResourceVersion,
} from '../api/m5'
import ResourceHistoryDrawer from '../components/ResourceHistoryDrawer.vue'
import ResourceToolbar from '../components/ResourceToolbar.vue'
import SourceCitation from '../components/SourceCitation.vue'
import ResourceFloatingQa from '../components/ResourceFloatingQa.vue'
import ResourceProfileAdaptation from '../components/ResourceProfileAdaptation.vue'
import { createNote, getNotes, updateNote } from '../api/notes'

const route = useRoute()
const router = useRouter()
const loading = ref(true)
const error = ref('')
const detail = ref(null)
const selectedVersionId = ref('')
const activeSectionId = ref('')
const readingProgress = ref(0)
const editing = ref(false)
const saving = ref(false)
const exporting = ref(false)
const comparing = ref(false)
const historyOpen = ref(false)
const historyError = ref('')
const restoringId = ref('')
const comparingId = ref('')
const compareResult = ref(null)
const actionError = ref('')
const notice = ref('')
const draft = ref(null)
const selectedAnswers = ref({})
const checkedAnswers = ref({})
const partnerQuestion = ref('')
const partnerNotice = ref('')
const qaOpen = ref(false)
const noteBusy = ref(false)

// prompt: question is handled by ResourceFloatingQa so the same teacher-style
// answer surface is available from the handout and other resource pages.

const resourceId = computed(() => String(route.params.resourceId || ''))
const activeStudentId = computed(() => localStorage.getItem('edumatrix_student_id') || localStorage.getItem('edumatrix_username') || '')
const versions = computed(() => detail.value?.handout?.versions || [])
const currentVersionId = computed(() => detail.value?.handout?.current_version_id || '')
const historyItems = computed(() => versions.value.map(item => ({
  ...item,
  revision_origin: item.revision_origin || item.metadata?.revision_origin,
  source_status: item.source_status || 'available',
  content_format: item.content_format || 'json',
})))
const selectedVersion = computed(() => (
  versions.value.find(item => item.id === selectedVersionId.value)
  || versions.value.find(item => item.id === currentVersionId.value)
  || null
))
const projection = computed(() => selectedVersion.value?.projection || null)
const structured = computed(() => projection.value?.structured || null)
const legacy = computed(() => projection.value?.legacy || null)
const invalid = computed(() => projection.value?.invalid || null)
const sourceRefs = computed(() => projection.value?.source_refs || [])
const catalog = computed(() => detail.value?.catalog || {})
const isHistorical = computed(() => Boolean(selectedVersionId.value && selectedVersionId.value !== currentVersionId.value))
const isStructured = computed(() => projection.value?.mode === 'structured')
const isInvalidStructured = computed(() => projection.value?.mode === 'invalid_structured')
const usesJsonFormat = computed(() => projection.value?.content_format === 'json')
const genericTitleSuffixes = ['当前学习资源', '当前课程资源', '当前教材文件', '当前教材选区', '当前资源']
function displayHandoutTitle(value) {
  const raw = String(value || '').trim()
  const point = String(catalog.value?.knowledge_point?.title || '').trim()
  if (!raw || !point) return raw || '个性化讲义'
  const generic = genericTitleSuffixes.some((suffix) => raw === suffix || raw === `个性化讲义 · ${suffix}`)
  return generic ? `个性化讲义 · ${point}` : raw
}
const title = computed(() => displayHandoutTitle(structured.value?.title || legacy.value?.title || detail.value?.title || '个性化讲义'))
const summary = computed(() => structured.value?.summary || legacy.value?.summary || '')
const outline = computed(() => {
  if (structured.value?.outline?.length) {
    // Footnote markers such as “[1]” belong in the optional materials panel,
    // not in the learner's reading outline where they look like empty IDs.
    return structured.value.outline.filter((item) => {
      const title = String(item?.title || '').trim()
      const id = String(item?.id || '').trim()
      return !/^\[\d+\]$/.test(title) && !/^source-\d+$/.test(id)
    })
  }
  return [{ id: 'legacy-content', title: '讲义正文' }]
})
const readiness = computed(() => projection.value?.source_readiness || {})
const versionLabel = computed(() => selectedVersion.value ? `v${selectedVersion.value.number}` : '-')
const primaryLabel = computed(() => {
  if (editing.value) return saving.value ? '正在保存' : '保存为新版本'
  if (isHistorical.value) return '从此版本继续编辑'
  return '编辑讲义'
})

function sourceForFootnote(footnote) {
  const sourceRefId = String(footnote?.sourceRefId || '')
  return sourceRefs.value.find(item => String(item.source_ref_id || item.sourceRefId || item.id || '') === sourceRefId) || {
    sourceRefId,
    title: footnote?.title || '课程来源',
    locationLabel: footnote?.location || '',
  }
}

function message(exception, fallback) {
  const detailMessage = exception?.response?.data?.detail?.message || exception?.detail?.message
  return detailMessage || (typeof exception?.detail === 'string' ? exception.detail : '') || exception?.message || fallback
}

function clone(value) {
  return JSON.parse(JSON.stringify(value))
}

function resetReadingState() {
  activeSectionId.value = outline.value[0]?.id || ''
  readingProgress.value = 0
  selectedAnswers.value = {}
  checkedAnswers.value = {}
}

async function loadResource({ preserveVersion = false } = {}) {
  loading.value = true
  error.value = ''
  try {
    const payload = await getM5Resource(resourceId.value)
    if (payload?.catalog?.type !== 'handout') throw new Error('当前资源不是个性化讲义。')
    detail.value = payload
    const keep = preserveVersion && versions.value.some(item => item.id === selectedVersionId.value)
    if (!keep) selectedVersionId.value = payload.handout?.current_version_id || ''
    resetReadingState()
  } catch (exception) {
    error.value = message(exception, '讲义加载失败，请稍后重试。')
  } finally {
    loading.value = false
  }
}

function startEditing() {
  actionError.value = ''
  notice.value = ''
  draft.value = isStructured.value
    ? clone(structured.value)
    : isInvalidStructured.value
      ? invalid.value?.raw_content || ''
      : legacy.value?.markdown || ''
  editing.value = true
}

function cancelEditing() {
  editing.value = false
  draft.value = null
  actionError.value = ''
}

function structuredPayload() {
  return JSON.stringify(draft.value)
}

async function saveVersion() {
  if (!editing.value || saving.value || !selectedVersion.value) return
  saving.value = true
  actionError.value = ''
  notice.value = ''
  try {
    const payload = await createM5ResourceVersion(resourceId.value, {
      expected_lock_version: detail.value.lock_version,
      source_version_id: selectedVersion.value.id,
      content: isStructured.value ? structuredPayload() : String(draft.value || ''),
      content_format: usesJsonFormat.value ? 'json' : 'markdown',
    })
    detail.value = payload
    selectedVersionId.value = payload.handout?.current_version_id || payload.current_version_id
    editing.value = false
    draft.value = null
    notice.value = '新版本已保存，原版本仍可在历史中查看。'
    await nextTick()
    resetReadingState()
  } catch (exception) {
    actionError.value = exception?.status === 409
      ? '讲义已在别处更新。你的草稿仍保留，请刷新版本状态后再次保存。'
      : message(exception, '保存失败，草稿已保留，请重试。')
  } finally {
    saving.value = false
  }
}

async function refreshAfterConflict() {
  const savedDraft = clone(draft.value)
  const sourceVersion = selectedVersionId.value
  await loadResource({ preserveVersion: true })
  draft.value = savedDraft
  if (versions.value.some(item => item.id === sourceVersion)) selectedVersionId.value = sourceVersion
  editing.value = true
  actionError.value = ''
}

function downloadBlob(content, filename, type) {
  const url = URL.createObjectURL(new Blob([content], { type }))
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  link.click()
  URL.revokeObjectURL(url)
}

function escapeHtml(value) {
  return String(value || '').replace(/[&<>"']/g, character => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  })[character])
}

function handoutHtml(content) {
  const sections = [
    ...content.concepts.map(item => `<section><h2>${escapeHtml(item.title)}</h2><p>${escapeHtml(item.explanation)}</p></section>`),
    ...content.figures.map(item => `<section><h2>${escapeHtml(item.title)}</h2><pre>${escapeHtml(item.content)}</pre><p>${escapeHtml(item.caption)}</p></section>`),
    ...content.examples.map(item => `<section><h2>${escapeHtml(item.title)}</h2><p>${escapeHtml(item.body)}</p></section>`),
    ...content.counterExamples.map(item => `<section><h2>${escapeHtml(item.title)}</h2><p>${escapeHtml(item.body)}</p></section>`),
    ...content.codeBlocks.map(item => `<section><h2>${escapeHtml(item.title)}</h2><pre><code>${escapeHtml(item.code)}</code></pre><p>${escapeHtml(item.explanation)}</p></section>`),
    ...content.miniQuiz.map(item => `<section><h2>学习检查</h2><h3>${escapeHtml(item.question)}</h3><ol>${item.options.map(option => `<li>${escapeHtml(option)}</li>`).join('')}</ol><p><strong>答案：</strong>${escapeHtml(item.options[item.correctIndex])}</p><p>${escapeHtml(item.explanation)}</p></section>`),
  ].join('')
  const sources = content.footnotes.map(item => `<li>${escapeHtml(item.label)} ${escapeHtml(item.title)} · ${escapeHtml(item.location)}</li>`).join('')
  return `<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>${escapeHtml(content.title)}</title><style>body{max-width:840px;margin:48px auto;padding:0 28px;color:#06141b;font:16px/1.75 "Source Han Sans SC","Microsoft YaHei",sans-serif}h1{font:700 38px/1.25 "Source Han Serif SC",serif}h2{margin-top:42px;border-bottom:1px solid #dce2e3;padding-bottom:10px;font-size:23px}pre{overflow:auto;padding:18px;background:#f1f4f4;border:1px solid #dce2e3;border-radius:6px}p,li{max-width:72ch}</style></head><body><h1>${escapeHtml(content.title)}</h1><p>${escapeHtml(content.summary)}</p><section><h2>学习目标</h2><p>${escapeHtml(content.learningGoal)}</p><p><strong>预计学习：</strong>${escapeHtml(content.estimatedMinutes)} 分钟</p></section>${sections}<section><h2>来源脚注</h2><ol>${sources}</ol></section></body></html>`
}

async function exportVersion(format) {
  if (exporting.value || !selectedVersion.value) return
  exporting.value = true
  actionError.value = ''
  try {
    const payload = await exportM5Resource(resourceId.value, selectedVersion.value.number)
    const safeTitle = title.value.replace(/[\\/:*?"<>|]+/g, '-').slice(0, 80) || '个性化讲义'
    if (format === 'html' && isStructured.value) {
      downloadBlob(handoutHtml(structured.value), `${safeTitle}-${versionLabel.value}.html`, 'text/html;charset=utf-8')
    } else {
      downloadBlob(JSON.stringify(payload, null, 2), `${safeTitle}-${versionLabel.value}.json`, 'application/json;charset=utf-8')
    }
    notice.value = format === 'html' && isStructured.value ? 'HTML 讲义已导出。' : '资源版本数据已导出。'
  } catch (exception) {
    actionError.value = message(exception, '导出失败，当前讲义内容仍然保留。')
  } finally {
    exporting.value = false
  }
}

function openHistory() {
  historyError.value = ''
  compareResult.value = null
  historyOpen.value = true
}

function closeHistory() {
  historyOpen.value = false
  historyError.value = ''
  compareResult.value = null
}

function selectHistoryVersion(versionId) {
  if (editing.value) return
  selectedVersionId.value = versionId
  closeHistory()
}

async function compareHistory(versionId) {
  if (comparingId.value) return
  const left = versions.value.find(item => item.id === versionId)
  const right = versions.value.find(item => item.id === currentVersionId.value)
  if (!left || !right) return
  comparingId.value = versionId
  historyError.value = ''
  try {
    compareResult.value = await compareM5ResourceVersions(resourceId.value, left.number, right.number)
  } catch (exception) {
    historyError.value = message(exception, '版本比较失败，请稍后重试。')
  } finally {
    comparingId.value = ''
  }
}

async function restoreHistory(versionId) {
  if (editing.value || saving.value || restoringId.value || versionId === currentVersionId.value) return
  restoringId.value = versionId
  historyError.value = ''
  try {
    detail.value = await restoreM5ResourceVersion(resourceId.value, {
      expected_lock_version: detail.value.lock_version,
      version_id: versionId,
    })
    selectedVersionId.value = detail.value.handout?.current_version_id || detail.value.current_version_id || ''
    resetReadingState()
    notice.value = '历史版本已恢复为新的当前版本，原版本仍保留。'
    closeHistory()
  } catch (exception) {
    historyError.value = message(exception, '恢复失败，当前讲义版本没有改变。')
  } finally {
    restoringId.value = ''
  }
}

async function compareWithCurrent() {
  if (comparing.value || !selectedVersion.value || !isHistorical.value) return
  comparing.value = true
  actionError.value = ''
  try {
    const current = versions.value.find(item => item.id === currentVersionId.value)
    const result = await compareM5ResourceVersions(resourceId.value, selectedVersion.value.number, current.number)
    const label = result.changed ? '所选版本与当前版本存在内容差异。' : '所选版本与当前版本内容一致。'
    notice.value = label
  } catch (exception) {
    actionError.value = message(exception, '版本比较失败，请重试。')
  } finally {
    comparing.value = false
  }
}

function jumpTo(sectionId) {
  activeSectionId.value = sectionId
  document.getElementById(`handout-${sectionId}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

function updateProgress(event) {
  const element = event.currentTarget
  const scrollable = element.scrollHeight - element.clientHeight
  readingProgress.value = scrollable > 0 ? Math.min(100, Math.round((element.scrollTop / scrollable) * 100)) : 100
}

function checkAnswer(item) {
  if (selectedAnswers.value[item.id] === undefined) return
  checkedAnswers.value = { ...checkedAnswers.value, [item.id]: true }
}

async function copyCode(code) {
  await navigator.clipboard.writeText(code)
  notice.value = '代码已复制；真实运行请进入代码沙盒。'
}

function askPartner() {
  const question = partnerQuestion.value.trim()
  if (!question) return
  partnerNotice.value = '问答窗已打开，可以继续追问当前讲义。'
  qaOpen.value = true
}

function handoutNoteMarkdown() {
  if (legacy.value?.markdown) return legacy.value.markdown.trim()

  const content = structured.value
  if (!content) return String(invalid.value?.raw_content || '').trim()

  const lines = [`# ${content.title || title.value}`, '']
  if (content.summary) lines.push(content.summary.trim(), '')
  if (content.learningGoal || content.estimatedMinutes) {
    lines.push('## 学习目标', '')
    if (content.learningGoal) lines.push(content.learningGoal.trim(), '')
    if (content.estimatedMinutes) lines.push(`预计学习时间：${content.estimatedMinutes} 分钟`, '')
  }
  if (Array.isArray(content.concepts) && content.concepts.length) {
    lines.push('## 核心概念', '')
    content.concepts.forEach((item) => {
      lines.push(`### ${item.title || '概念'}`, '', String(item.explanation || '').trim(), '')
    })
  }
  if (Array.isArray(content.figures) && content.figures.length) {
    lines.push('## 图示与公式', '')
    content.figures.forEach((item) => {
      lines.push(`### ${item.title || '图示'}`, '')
      if (item.content) lines.push(`~~~${item.kind === 'formula' ? 'text' : ''}`, String(item.content).trim(), '~~~', '')
      if (item.caption) lines.push(item.caption.trim(), '')
    })
  }
  if (Array.isArray(content.examples) && content.examples.length) {
    lines.push('## 应用示例', '')
    content.examples.forEach((item) => lines.push(`### ${item.title || '示例'}`, '', String(item.body || '').trim(), ''))
  }
  if (Array.isArray(content.counterExamples) && content.counterExamples.length) {
    lines.push('## 边界与反例', '')
    content.counterExamples.forEach((item) => lines.push(`### ${item.title || '边界情况'}`, '', String(item.body || '').trim(), ''))
  }
  if (Array.isArray(content.codeBlocks) && content.codeBlocks.length) {
    lines.push('## 代码阅读', '')
    content.codeBlocks.forEach((item) => {
      lines.push(`### ${item.title || '代码示例'}`, '', `~~~${item.language || ''}`, String(item.code || '').trim(), '~~~', '')
      if (item.explanation) lines.push(item.explanation.trim(), '')
    })
  }
  if (Array.isArray(content.miniQuiz) && content.miniQuiz.length) {
    lines.push('## 学习检查', '')
    content.miniQuiz.forEach((item) => {
      lines.push(`### ${item.question || '检查题'}`, '')
      ;(item.options || []).forEach((option, index) => lines.push(`${String.fromCharCode(65 + index)}. ${option}`))
      if (item.options?.[item.correctIndex] !== undefined) lines.push('', `**答案：** ${item.options[item.correctIndex]}`)
      if (item.explanation) lines.push('', item.explanation.trim())
      lines.push('')
    })
  }
  if (Array.isArray(content.footnotes) && content.footnotes.length) {
    lines.push('## 参考材料', '')
    content.footnotes.forEach((item) => {
      const location = item.location ? ` · ${item.location}` : ''
      lines.push(`- ${item.label || ''} ${item.title || '课程来源'}${location}`.trim())
    })
  }
  return lines.join('\n').replace(/\n{3,}/g, '\n\n').trim()
}

async function openSourceNote() {
  if (!activeStudentId.value || !selectedVersion.value || noteBusy.value) return
  noteBusy.value = true
  actionError.value = ''
  const content = handoutNoteMarkdown()
  const sourceMetadata = {
    resource_id: resourceId.value,
    resource_version_id: selectedVersion.value.id,
  }
  const tags = ['个性化讲义']
  const concepts = catalog.value?.knowledge_point?.title ? [catalog.value.knowledge_point.title] : []
  const idempotencyKey = `handout-note-${resourceId.value}-${selectedVersion.value.id}`
  try {
    let note
    try {
      note = await createNote(activeStudentId.value, {
        source_type: 'handout',
        source_metadata: sourceMetadata,
        content,
        tags,
        concepts,
        idempotency_key: idempotencyKey,
      })
    } catch (exception) {
      // Upgrade a note created by the former title-only action in place.
      if (exception?.response?.status !== 409) throw exception
      const listed = await getNotes(activeStudentId.value)
      const notes = Array.isArray(listed) ? listed : listed?.notes || []
      const legacyNote = notes.find((item) => (
        String(item?.source_metadata?.resource_id || '') === resourceId.value
        && String(item?.source_metadata?.resource_version_id || '') === String(selectedVersion.value.id)
      ))
      if (!legacyNote) throw exception
      const sameContent = legacyNote.content === content
        && JSON.stringify(legacyNote.tags || []) === JSON.stringify(tags)
        && JSON.stringify(legacyNote.concepts || []) === JSON.stringify(concepts)
      if (sameContent) {
        // The complete handout is already present; a replay must only reopen it.
        note = legacyNote
      } else {
        note = await updateNote(legacyNote.id, {
          student_id: activeStudentId.value,
          content,
          tags,
          concepts,
          expected_version: legacyNote.lock_version,
          // Include the current lock version so a prior completed upgrade cannot
          // collide with a later, genuinely changed handout save.
          idempotency_key: `handout-note-upgrade-${resourceId.value}-${selectedVersion.value.id}-${legacyNote.lock_version}`,
          change_type: 'saved',
        })
      }
    }
    // Use a full navigation so the lazy notebook view cannot remain behind
    // the shell's out-in transition on a cold desktop route load.
    const notesUrl = router.resolve({ name: 'Notes', query: { note_id: note.id } }).href
    window.location.assign(notesUrl)
  } catch (exception) {
    actionError.value = exception?.response?.data?.detail || exception?.message || '来源笔记没有创建，讲义内容未受影响。'
  } finally {
    noteBusy.value = false
  }
}

function renderFormula(content) {
  if (!window.katex) return ''
  try {
    return window.katex.renderToString(content, { displayMode: true, throwOnError: false, trust: false })
  } catch {
    return ''
  }
}

watch(selectedVersionId, () => {
  if (!editing.value) resetReadingState()
})

onMounted(loadResource)
</script>

<template>
  <!--
  THESIS: 讲义是可持续阅读与修订的学习出版物，拒绝聊天长文本和卡片墙。
  OWN-WORLD: 雾白应用面、连续白纸正文、墨蓝灰细线与紧凑编辑工具。
  STORY: 学生先定位章节，再阅读证据化内容，完成小测，并把修订保存为新版本。
  FIRST VIEWPORT: 220px目录、中央连续正文、300px伙伴/来源/进度；右上唯一主动作随状态变化。
  FORM: 编辑部式学习报告，继承F1浅色极简桌面系统。
  FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, and DESIGN.md
  -->
  <main class="handout-page" data-testid="handout-workspace">
      <ResourceToolbar
        :title="title"
        :type-label="`${catalog.course?.title || '当前课程'} · ${catalog.knowledge_point?.title || '个性化讲义'}`"
        :version-label="versionLabel"
        :history-count="historyItems.length"
        :can-edit="Boolean(selectedVersion)"
        :edit-label="primaryLabel"
        :editing="editing"
        :saving="saving"
        :loading="loading"
        :history-disabled="!historyItems.length || editing"
        show-note
        :note-disabled="!selectedVersion || editing"
        :note-busy="noteBusy"
        @back="router.push({ name: 'WorkspaceResources' })"
        @history="openHistory"
        @edit="startEditing"
        @save="saveVersion"
        @cancel="cancelEditing"
        @reload="loadResource"
        @note="openSourceNote"
      />
      <div class="workspace-version-row">
        <label class="version-select">
          <History :size="16" />
          <span>版本</span>
          <select v-model="selectedVersionId" :disabled="editing" aria-label="讲义版本">
            <option v-for="version in [...versions].reverse()" :key="version.id" :value="version.id">
              v{{ version.number }}{{ version.id === currentVersionId ? ' · 当前' : ' · 历史' }}
            </option>
          </select>
        </label>
      </div>

      <div v-if="loading" class="workspace-state" aria-live="polite">
      <LoaderCircle :size="26" class="spin" />
      <strong>正在恢复讲义</strong>
      <span>目录、正文和版本状态会在同一位置恢复。</span>
    </div>

    <div v-else-if="error" class="workspace-state workspace-state--error" role="alert">
      <AlertTriangle :size="27" />
      <strong>暂时无法打开讲义</strong>
      <span>{{ error }}</span>
      <button type="button" class="primary-action" @click="loadResource()"><RefreshCw :size="17" />重新加载</button>
    </div>

    <template v-else-if="detail && projection">
      <div v-if="actionError || notice" class="status-line" :class="{ 'status-line--error': actionError }" role="status">
        <AlertTriangle v-if="actionError" :size="17" />
        <Check v-else :size="17" />
        <span>{{ actionError || notice }}</span>
        <button v-if="actionError.includes('别处更新')" type="button" @click="refreshAfterConflict">刷新版本状态</button>
        <button v-else type="button" title="关闭提示" @click="actionError = ''; notice = ''"><X :size="16" /></button>
      </div>

      <section class="workspace-grid">
        <aside class="outline-panel" aria-label="讲义目录">
          <div class="panel-heading">
            <div><BookOpen :size="18" /><strong>目录</strong></div>
            <span>{{ versionLabel }}</span>
          </div>
          <nav>
            <button
              v-for="(item, index) in outline"
              :key="item.id"
              type="button"
              :class="{ active: activeSectionId === item.id }"
              @click="jumpTo(item.id)"
            >
              <span>{{ String(index + 1).padStart(2, '0') }}</span>
              <strong>{{ item.title }}</strong>
            </button>
          </nav>
          <div class="outline-progress">
            <div><span>阅读位置</span><strong>{{ readingProgress }}%</strong></div>
            <div class="progress-track"><span :style="{ width: `${readingProgress}%` }" /></div>
            <p>仅记录本页阅读位置，不等同于知识掌握度。</p>
          </div>
        </aside>

        <article class="reading-panel" @scroll="updateProgress">
          <div v-if="isHistorical" class="historical-banner">
            <History :size="17" />
            <span>正在只读查看 {{ versionLabel }}。编辑会另存为新版本，不覆盖历史。</span>
            <button type="button" :disabled="comparing" @click="compareWithCurrent">
              <GitCompare :size="16" />{{ comparing ? '比较中' : '与当前版本比较' }}
            </button>
          </div>

          <template v-if="editing && isStructured">
            <section class="editor-section editor-lead">
              <label>讲义标题<input v-model="draft.title" maxlength="256" /></label>
              <label>适配摘要<textarea v-model="draft.summary" rows="4" maxlength="4000" /></label>
              <label>学习目标<textarea v-model="draft.learningGoal" rows="3" maxlength="2000" /></label>
            </section>
            <section v-for="item in draft.concepts" :key="item.id" class="editor-section">
              <label>关键概念<input v-model="item.title" /></label>
              <label>概念解释<textarea v-model="item.explanation" rows="7" /></label>
            </section>
            <section v-for="item in draft.figures" :key="item.id" class="editor-section">
              <label>图表或公式标题<input v-model="item.title" /></label>
              <label>内容<textarea v-model="item.content" rows="6" /></label>
              <label>说明<textarea v-model="item.caption" rows="3" /></label>
            </section>
            <section v-for="item in draft.examples" :key="item.id" class="editor-section">
              <label>示例标题<input v-model="item.title" /></label>
              <label>示例正文<textarea v-model="item.body" rows="6" /></label>
            </section>
            <section v-for="item in draft.counterExamples" :key="item.id" class="editor-section">
              <label>反例标题<input v-model="item.title" /></label>
              <label>反例正文<textarea v-model="item.body" rows="6" /></label>
            </section>
            <section v-for="item in draft.codeBlocks" :key="item.id" class="editor-section">
              <label>代码标题<input v-model="item.title" /></label>
              <label>代码<textarea v-model="item.code" class="code-input" rows="10" spellcheck="false" /></label>
              <label>代码说明<textarea v-model="item.explanation" rows="4" /></label>
            </section>
            <section v-for="item in draft.miniQuiz" :key="item.id" class="editor-section">
              <label>小测问题<textarea v-model="item.question" rows="3" /></label>
              <label v-for="(_, index) in item.options" :key="index">选项 {{ index + 1 }}<input v-model="item.options[index]" /></label>
              <label>解析<textarea v-model="item.explanation" rows="4" /></label>
            </section>
            <section class="editor-section">
              <label>画像适配说明<textarea v-model="draft.profileAdaptation.summary" rows="4" /></label>
              <label>阅读支架<textarea v-model="draft.profileAdaptation.scaffolding[0]" rows="3" /></label>
              <p class="source-edit-boundary">来源脚注与引用 ID 来自预置知识库，不能在正文编辑器中随意改写。</p>
            </section>
          </template>

          <section v-else-if="editing" class="legacy-editor">
            <label for="legacy-markdown">{{ isInvalidStructured ? '结构化讲义 JSON' : 'Markdown 讲义正文' }}</label>
            <textarea id="legacy-markdown" v-model="draft" spellcheck="false" />
            <p v-if="isInvalidStructured">修复缺失章节后保存；校验失败时原内容和草稿都会保留。</p>
            <p v-else>旧讲义按原格式另存新版本；系统不会自动补造缺失的图表、小测或来源。</p>
          </section>

          <template v-else-if="isStructured">
            <ResourceProfileAdaptation
              :adaptation="structured?.profileAdaptation"
              :plan="detail?.resource?.profile_adaptation_plan"
              :summary="structured?.profileAdaptation?.summary || ''"
              resource-type="handout"
            />
            <header class="document-lead">
              <span>{{ catalog.knowledge_point?.title || '当前知识点' }}</span>
              <h2>{{ title }}</h2>
              <p>{{ structured.summary }}</p>
              <dl>
                <div><dt>学习目标</dt><dd>{{ structured.learningGoal }}</dd></div>
              </dl>
            </header>

            <section
              v-for="item in structured.concepts"
              :id="`handout-${item.id}`"
              :key="item.id"
              class="document-section"
            >
              <span class="section-kind">关键概念</span><h3>{{ item.title }}</h3><p>{{ item.explanation }}</p>
            </section>

            <section
              v-for="item in structured.figures"
              :id="`handout-${item.id}`"
              :key="item.id"
              class="document-section"
            >
              <span class="section-kind">{{ item.kind === 'formula' ? '公式' : item.kind === 'chart' ? '图表' : '机制图解' }}</span>
              <h3>{{ item.title }}</h3>
              <div class="figure-surface">
                <div v-if="item.kind === 'formula' && renderFormula(item.content)" class="formula" v-html="renderFormula(item.content)" />
                <pre v-else>{{ item.content }}</pre>
              </div>
              <p class="caption">{{ item.caption }}</p>
            </section>

            <section
              v-for="item in structured.examples"
              :id="`handout-${item.id}`"
              :key="item.id"
              class="document-section example-section"
            >
              <span class="section-kind">应用示例</span><h3>{{ item.title }}</h3><p>{{ item.body }}</p>
            </section>

            <section
              v-for="item in structured.counterExamples"
              :id="`handout-${item.id}`"
              :key="item.id"
              class="document-section counter-section"
            >
              <span class="section-kind">边界与反例</span><h3>{{ item.title }}</h3><p>{{ item.body }}</p>
            </section>

            <section
              v-for="item in structured.codeBlocks"
              :id="`handout-${item.id}`"
              :key="item.id"
              class="document-section"
            >
              <div class="section-title-row"><div><span class="section-kind">代码阅读 · {{ item.language }}</span><h3>{{ item.title }}</h3></div><button type="button" title="复制代码" @click="copyCode(item.code)"><Clipboard :size="17" /></button></div>
              <pre class="code-block"><code>{{ item.code }}</code></pre>
              <p>{{ item.explanation }}</p>
            </section>

            <section
              v-for="item in structured.miniQuiz"
              :id="`handout-${item.id}`"
              :key="item.id"
              class="document-section quiz-section"
            >
              <span class="section-kind">学习检查</span><h3>{{ item.question }}</h3>
              <label v-for="(option, index) in item.options" :key="index" class="quiz-option" :class="{ selected: selectedAnswers[item.id] === index }">
                <input v-model="selectedAnswers[item.id]" type="radio" :name="item.id" :value="index" />
                <span>{{ option }}</span>
              </label>
              <button type="button" class="quiz-submit" :disabled="selectedAnswers[item.id] === undefined" @click="checkAnswer(item)">检查答案</button>
              <div v-if="checkedAnswers[item.id]" class="quiz-feedback" :class="{ correct: selectedAnswers[item.id] === item.correctIndex }">
                <Check v-if="selectedAnswers[item.id] === item.correctIndex" :size="18" />
                <AlertTriangle v-else :size="18" />
                <div><strong>{{ selectedAnswers[item.id] === item.correctIndex ? '回答正确' : '再想一想' }}</strong><p>{{ item.explanation }}</p></div>
              </div>
            </section>

            <section class="document-section footnotes-section">
              <span class="section-kind">延伸阅读</span><h3>相关材料</h3>
              <ol>
                <li v-for="item in structured.footnotes" :id="`handout-${item.id}`" :key="item.id">
                  <SourceCitation :source="sourceForFootnote(item)" :return-to="route.fullPath" />
                </li>
              </ol>
            </section>
          </template>

          <section v-else-if="legacy" id="handout-legacy-content" class="legacy-reader">
            <div class="legacy-warning"><AlertTriangle :size="18" /><span>{{ projection.warnings?.[0] }}</span></div>
            <IncrementalMarkdownRenderer :text="legacy.markdown" type="lesson" :concept-name="catalog.knowledge_point?.title || ''" />
          </section>

          <section v-else class="invalid-reader" role="alert">
            <AlertTriangle :size="28" />
            <h2>讲义结构需要修复</h2>
            <p>{{ projection.warnings?.[0] || '当前版本缺少完整学习章节，暂时不能按正式讲义发布。' }}</p>
            <button type="button" class="primary-action" @click="startEditing"><Pencil :size="17" />修复并另存新版本</button>
          </section>
        </article>

        <aside class="support-panel">
          <section class="support-section">
            <div class="panel-heading"><div><MessageSquareText :size="18" /><strong>AI 学习伙伴</strong></div></div>
            <p>遇到不理解的概念，可以留在当前讲义里继续追问。</p>
            <textarea v-model="partnerQuestion" rows="4" placeholder="针对本讲义提问" />
            <button type="button" class="secondary-action" :disabled="!partnerQuestion.trim()" @click="askPartner"><Send :size="16" />在资源内提问</button>
            <span v-if="partnerNotice" class="support-note">{{ partnerNotice }}</span>
          </section>

          <details class="support-section source-details">
            <summary class="panel-heading"><div><FileJson :size="18" /><strong>参考材料</strong></div><span>{{ sourceRefs.length }} 项</span></summary>
            <div class="source-readiness" :class="{ ready: readiness.publishable }">
              <Check v-if="readiness.publishable" :size="17" /><AlertTriangle v-else :size="17" />
              <span>{{ readiness.reason }}</span>
            </div>
            <SourceCitation
              v-for="source in sourceRefs"
              :key="source.source_ref_id || source.sourceRefId || source.id"
              :source="source"
              :return-to="route.fullPath"
              compact
            />
          </details>

          <section class="support-section export-section">
            <div class="panel-heading"><div><Download :size="18" /><strong>导出</strong></div></div>
            <button v-if="isStructured" type="button" class="secondary-action" :disabled="exporting" @click="exportVersion('html')"><FileText :size="16" />导出 HTML</button>
            <button type="button" class="secondary-action" :disabled="exporting" @click="exportVersion('json')"><FileJson :size="16" />导出版本数据</button>
            <p>浏览器打印 HTML 可生成 PDF；导出失败不会影响当前讲义与草稿。</p>
          </section>
        </aside>
      </section>
    </template>

    <ResourceFloatingQa
      :open="qaOpen"
      :course-id="catalog.course?.id || ''"
      :knowledge-point-id="catalog.knowledge_point?.id || ''"
      :resource-id="resourceId"
      :resource-title="title"
      :source-ref-ids="sourceRefs.map(item => item.source_ref_id || item.sourceRefId || item.id).filter(Boolean)"
      @close="qaOpen = false"
    />

    <ResourceHistoryDrawer
      :open="historyOpen"
      :title="`${title} · 版本历史`"
      :items="historyItems"
      :current-version-id="currentVersionId"
      :selected-version-id="selectedVersionId"
      :restoring-id="restoringId"
      :error="historyError"
      :compare-result="compareResult"
      :comparing-id="comparingId"
      :compare-disabled="Boolean(comparingId)"
      :restore-disabled="Boolean(editing || saving)"
      @close="closeHistory"
      @select="selectHistoryVersion"
      @compare="compareHistory"
      @restore="restoreHistory"
      @compare-close="compareResult = null"
    />
  </main>
</template>

<style scoped>
.handout-page { display: grid; min-width: 0; min-height: 100%; grid-template-rows: 82px auto minmax(0, 1fr); color: var(--color-text); background: var(--color-page); }
.workspace-header { display: grid; min-width: 0; grid-template-columns: 42px minmax(260px, 1fr) auto; align-items: center; gap: 14px; padding: 12px 20px; border-bottom: 1px solid var(--color-border); background: var(--color-surface); }
.header-copy { min-width: 0; }
.header-copy > span { display: block; overflow: hidden; color: var(--color-text-muted); font-size: 14px; text-overflow: ellipsis; white-space: nowrap; }
.header-copy h1 { margin: 3px 0 0; overflow: hidden; color: var(--color-text); font-family: var(--font-heading); font-size: 23px; line-height: 1.3; text-overflow: ellipsis; white-space: nowrap; }
.header-meta { display: flex; min-width: 0; align-items: center; gap: 8px; }
.header-meta > span { color: var(--color-text-secondary); font-size: 14px; white-space: nowrap; }
.icon-action, .primary-action, .secondary-action, .quiz-submit { display: inline-flex; min-height: 40px; align-items: center; justify-content: center; gap: 7px; border-radius: var(--radius-control); font-size: 14px; cursor: pointer; }
.icon-action { width: 40px; padding: 0; color: var(--color-text-secondary); border: 1px solid var(--color-border-strong); background: var(--color-surface); }
.primary-action { padding: 0 15px; color: #fff; border: 1px solid var(--color-accent); background: var(--color-accent); font-weight: 650; }
.primary-action:hover { background: var(--color-text); }
.primary-action:disabled, .secondary-action:disabled, .quiz-submit:disabled { opacity: .46; cursor: default; }
.version-select { display: flex; height: 40px; align-items: center; gap: 7px; padding-left: 10px; border: 1px solid var(--color-border-strong); border-radius: var(--radius-control); background: var(--color-surface); }
.workspace-version-row { display: flex; justify-content: flex-end; margin: 10px 0 0; }
.version-select select { min-width: 98px; height: 38px; padding: 0 8px 0 0; border: 0; background: transparent; font-size: 14px; }
.workspace-grid { display: grid; min-width: 0; min-height: calc(100vh - 138px); grid-template-columns: 220px minmax(500px, 1fr) 300px; overflow: hidden; }
.outline-panel, .support-panel { min-width: 0; min-height: 0; overflow-y: auto; background: var(--color-surface); }
.outline-panel { border-right: 1px solid var(--color-border); }
.support-panel { border-left: 1px solid var(--color-border); }
.panel-heading { display: flex; min-height: 46px; align-items: center; justify-content: space-between; gap: 10px; border-bottom: 1px solid var(--color-border); }
.panel-heading > div { display: flex; align-items: center; gap: 8px; }
.panel-heading strong, .panel-heading span { font-size: 14px; }
.panel-heading span { color: var(--color-text-muted); font-variant-numeric: tabular-nums; }
.outline-panel > .panel-heading { padding: 0 14px; }
.outline-panel nav { padding: 10px 8px; }
.outline-panel nav button { display: grid; width: 100%; min-height: 46px; grid-template-columns: 28px minmax(0, 1fr); align-items: center; gap: 8px; padding: 7px 9px; color: var(--color-text-secondary); border: 0; border-radius: 6px; background: transparent; text-align: left; cursor: pointer; }
.outline-panel nav button:hover { background: var(--color-surface-subtle); }
.outline-panel nav button.active { color: #fff; background: var(--color-accent); }
.outline-panel nav button span { font-size: 14px; font-variant-numeric: tabular-nums; }
.outline-panel nav button strong { overflow: hidden; font-size: 14px; line-height: 1.4; text-overflow: ellipsis; white-space: nowrap; }
.outline-progress { margin-top: auto; padding: 16px 14px; border-top: 1px solid var(--color-border); }
.outline-progress > div:first-child { display: flex; justify-content: space-between; font-size: 14px; }
.progress-track { height: 5px; margin-top: 9px; overflow: hidden; border-radius: 3px; background: var(--color-surface-muted); }
.progress-track span { display: block; height: 100%; background: var(--color-accent); }
.outline-progress p { margin: 10px 0 0; color: var(--color-text-muted); font-size: 14px; line-height: 1.55; }
.reading-panel { min-width: 0; min-height: 0; overflow-y: auto; scroll-behavior: smooth; background: var(--color-surface); }
.document-lead, .document-section, .legacy-reader, .legacy-editor, .editor-section, .invalid-reader { width: min(760px, calc(100% - 64px)); margin-inline: auto; }
.document-lead { padding: 56px 0 42px; border-bottom: 1px solid var(--color-border); }
.document-lead > span, .section-kind { color: var(--color-text-muted); font-size: 14px; font-weight: 650; }
.document-lead h2 { max-width: 20ch; margin: 10px 0 18px; font-family: var(--font-display); font-size: 38px; line-height: 1.22; }
.document-lead > p { max-width: 68ch; margin: 0; color: var(--color-text-secondary); font-size: 17px; line-height: 1.8; }
.document-lead dl { display: grid; grid-template-columns: 1fr 1fr; gap: 28px; margin: 34px 0 0; }
.document-lead dl div { padding-top: 14px; border-top: 1px solid var(--color-border-strong); }
.document-lead dt { color: var(--color-text-muted); font-size: 14px; }
.document-lead dd { margin: 7px 0 0; font-size: 15px; line-height: 1.7; }
.document-section { scroll-margin-top: 18px; padding: 46px 0; border-bottom: 1px solid var(--color-border); }
.document-section h3 { max-width: 28ch; margin: 7px 0 15px; font-size: 24px; line-height: 1.35; }
.document-section > p, .caption { max-width: 72ch; margin: 0; color: var(--color-text-secondary); font-size: 16px; line-height: 1.8; }
.section-title-row { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; }
.section-title-row h3 { margin-top: 7px; }
.section-title-row button { display: grid; width: 38px; height: 38px; flex: 0 0 38px; place-items: center; border: 1px solid var(--color-border-strong); border-radius: 6px; background: var(--color-surface); cursor: pointer; }
.figure-surface { min-height: 150px; margin: 22px 0 14px; padding: 28px; overflow-x: auto; border: 1px solid var(--color-border); border-radius: 8px; background: var(--color-surface-subtle); }
.figure-surface pre { margin: 0; color: var(--color-text); font: 15px/1.8 var(--font-mono); white-space: pre-wrap; }
.formula { overflow-x: auto; text-align: center; }
.formula :deep(.katex) { font-size: 20px; }
.caption { font-size: 14px; }
.example-section { position: relative; }
.example-section::before, .counter-section::before { position: absolute; top: 50px; left: -24px; width: 1px; height: 68px; background: var(--color-border-strong); content: ''; }
.code-block { margin: 18px 0 14px; padding: 22px; overflow: auto; border: 1px solid #253745; border-radius: 8px; color: #f7f9f9; background: #11212d; font: 14px/1.7 var(--font-mono); }
.quiz-section h3 { max-width: 44ch; }
.quiz-option { display: flex; min-height: 48px; align-items: center; gap: 10px; margin-top: 8px; padding: 10px 12px; border: 1px solid var(--color-border); border-radius: 6px; cursor: pointer; }
.quiz-option:hover, .quiz-option.selected { border-color: var(--color-accent); background: var(--color-surface-subtle); }
.quiz-option input { width: 17px; height: 17px; accent-color: var(--color-accent); }
.quiz-option span { font-size: 15px; }
.quiz-submit { margin-top: 16px; padding: 0 14px; color: var(--color-text); border: 1px solid var(--color-border-strong); background: var(--color-surface); }
.quiz-feedback { display: flex; align-items: flex-start; gap: 10px; margin-top: 14px; padding: 14px; border: 1px solid #d8aaa5; border-radius: 6px; background: var(--color-danger-soft); }
.quiz-feedback.correct { border-color: var(--color-border-strong); background: var(--color-success-soft); }
.quiz-feedback strong, .quiz-feedback p { font-size: 14px; }
.quiz-feedback p { margin: 3px 0 0; line-height: 1.6; }
.footnotes-section ol { display: grid; gap: 0; padding-left: 24px; }
.historical-banner { position: sticky; z-index: 2; top: 0; display: flex; min-height: 44px; align-items: center; justify-content: center; gap: 10px; padding: 7px 20px; color: var(--color-text-secondary); border-bottom: 1px solid var(--color-border); background: var(--color-surface-subtle); }
.historical-banner span, .historical-banner button { font-size: 14px; }
.historical-banner button { display: inline-flex; min-height: 30px; align-items: center; gap: 6px; border: 0; background: transparent; color: var(--color-text); cursor: pointer; font-weight: 650; }
.support-section { padding: 14px 16px 18px; border-bottom: 1px solid var(--color-border); }
.source-details > summary { cursor: pointer; list-style: none; }
.source-details > summary::-webkit-details-marker { display: none; }
.support-section .panel-heading { min-height: 38px; border: 0; }
.support-section > p, .support-note { display: block; margin: 8px 0 0; color: var(--color-text-secondary); font-size: 14px; line-height: 1.6; }
.support-section textarea { width: 100%; min-height: 92px; margin-top: 12px; resize: vertical; padding: 10px; }
.secondary-action { width: 100%; margin-top: 9px; padding: 0 12px; color: var(--color-text); border: 1px solid var(--color-border-strong); background: var(--color-surface); }
.secondary-action:hover { background: var(--color-surface-subtle); }
.plain-list { display: grid; gap: 9px; margin: 8px 0 0; padding-left: 20px; }
.plain-list li { color: var(--color-text-secondary); font-size: 14px; line-height: 1.55; }
.source-readiness { display: flex; align-items: flex-start; gap: 8px; margin-top: 8px; padding: 10px; color: var(--color-danger); border: 1px solid #d8aaa5; border-radius: 6px; background: var(--color-danger-soft); }
.source-readiness.ready { color: var(--color-text-secondary); border-color: var(--color-border-strong); background: var(--color-success-soft); }
.source-readiness span { font-size: 14px; line-height: 1.55; }
.export-section .secondary-action { justify-content: flex-start; }
.editor-section { display: grid; gap: 14px; padding: 32px 0; border-bottom: 1px solid var(--color-border); }
.editor-lead { padding-top: 42px; }
.editor-section label, .legacy-editor label { display: grid; gap: 6px; color: var(--color-text-secondary); font-size: 14px; font-weight: 650; }
.editor-section input, .editor-section textarea, .legacy-editor textarea { width: 100%; padding: 10px 12px; resize: vertical; color: var(--color-text); }
.editor-section textarea, .legacy-editor textarea { line-height: 1.65; }
.code-input, .legacy-editor textarea { font-family: var(--font-mono); }
.source-edit-boundary { margin: 0; padding: 12px; color: var(--color-text-secondary); border: 1px solid var(--color-border); border-radius: 6px; background: var(--color-surface-subtle); font-size: 14px; }
.legacy-editor { display: grid; min-height: calc(100% - 64px); grid-template-rows: auto minmax(460px, 1fr) auto; gap: 10px; padding: 32px 0; }
.legacy-editor textarea { min-height: 520px; }
.legacy-editor p { margin: 0; color: var(--color-text-muted); font-size: 14px; }
.legacy-reader { padding: 42px 0; }
.invalid-reader { display: grid; min-height: 420px; align-content: center; justify-items: start; gap: 12px; padding: 42px 0; color: var(--color-text-secondary); }
.invalid-reader h2 { margin: 0; color: var(--color-text); font-size: 24px; }
.invalid-reader p { max-width: 58ch; margin: 0; font-size: 15px; line-height: 1.7; }
.invalid-reader .primary-action { margin-top: 8px; }
.legacy-warning { display: flex; align-items: flex-start; gap: 9px; margin-bottom: 24px; padding: 12px; border: 1px solid var(--color-border-strong); border-radius: 6px; background: var(--color-surface-subtle); }
.legacy-warning span { font-size: 14px; line-height: 1.6; }
.status-line { display: flex; min-height: 42px; align-items: center; gap: 9px; padding: 7px 20px; color: var(--color-text-secondary); border-bottom: 1px solid var(--color-border); background: var(--color-success-soft); }
.status-line--error { color: var(--color-danger); background: var(--color-danger-soft); }
.status-line span { min-width: 0; flex: 1; font-size: 14px; }
.status-line button { display: inline-flex; min-height: 30px; align-items: center; border: 0; background: transparent; color: currentColor; font-size: 14px; cursor: pointer; font-weight: 650; }
.workspace-state { display: grid; min-height: calc(100vh - 138px); place-content: center; justify-items: center; gap: 10px; color: var(--color-text-secondary); }
.workspace-state strong { color: var(--color-text); font-size: 18px; }
.workspace-state span { max-width: 44ch; font-size: 14px; text-align: center; }
.workspace-state .primary-action { margin-top: 8px; }
.workspace-state--error { color: var(--color-danger); }
.spin { animation: spin .8s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
@media (max-width: 1300px) {
  .workspace-grid { grid-template-columns: 202px minmax(470px, 1fr) 278px; }
  .workspace-header { grid-template-columns: 42px minmax(230px, 1fr) auto; padding-inline: 14px; }
  .header-meta > span { display: none; }
  .document-lead, .document-section, .legacy-reader, .legacy-editor, .editor-section, .invalid-reader { width: min(720px, calc(100% - 44px)); }
}
</style>
