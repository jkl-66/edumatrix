<script setup>
import { sourceTextLength } from '../utils/sourceTextOffsets.js'
import { computed, nextTick, ref, watch } from 'vue'
import {
  BookOpenText,
  Check,
  Clipboard,
  FileCode2,
  RefreshCw,
} from '@lucide/vue'
import {
  cacheKey,
  documentSearchMatches,
  readCachedCourseDocument,
  renderCourseDocument,
  renderCourseMath,
  writeCachedCourseDocument,
} from '../utils/courseDocumentRenderer'

const props = defineProps({
  text: { type: String, default: '' },
  documentId: { type: String, default: '' },
  documentVersion: { type: String, default: '' },
  searchQuery: { type: String, default: '' },
  searchIndex: { type: Number, default: 0 },
  zoom: { type: Number, default: 1 },
})

const emit = defineEmits(['mouseup', 'mode-change', 'rendered'])
const mode = ref('preview')
const rootRef = ref(null)
const rawRef = ref(null)
const rawMatches = computed(() => documentSearchMatches(props.text, props.searchQuery))
const rawSearchParts = computed(() => {
  const query = props.searchQuery.trim()
  const text = props.text
  if (!query) return { before: text, hit: '', after: '' }
  const start = rawMatches.value[props.searchIndex]
  if (start === undefined) return { before: text, hit: '', after: '' }
  return { before: text.slice(0, start), hit: text.slice(start, start + query.length), after: text.slice(start + query.length) }
})
const presentation = ref({ html: '', blocks: [], matchCount: 0 })
const copiedCode = ref('')
let basePresentation = null
let mermaidSequence = 0

function renderMathAndMermaid() {
  const root = rootRef.value
  if (!root) return
  renderCourseMath(root, window.katex)
  root.querySelectorAll('.course-mermaid[data-mermaid-source]').forEach((element) => {
    if (element.dataset.rendered === 'true' || typeof window.mermaid === 'undefined') return
    const code = decodeURIComponent(element.dataset.mermaidSource || '')
    const host = element.querySelector('.course-mermaid__canvas')
    if (!host) return
    try {
      mermaidSequence += 1
      window.mermaid.render(`course-mermaid-${mermaidSequence}`, code).then(({ svg }) => {
        host.innerHTML = svg
        element.dataset.rendered = 'true'
      }).catch(() => {})
    } catch {}
  })
}

async function copyCode(event) {
  const button = event.target.closest('[data-copy-code]')
  if (!button || !rootRef.value?.contains(button)) return
  const code = button.closest('.lesson-block--practice')?.querySelector('code')?.textContent || ''
  if (!code) return
  try {
    await navigator.clipboard.writeText(code)
  } catch {
    const textarea = document.createElement('textarea')
    textarea.value = code
    textarea.style.position = 'fixed'
    textarea.style.opacity = '0'
    document.body.appendChild(textarea)
    textarea.select()
    document.execCommand('copy')
    textarea.remove()
  }
  copiedCode.value = String(button.dataset.copyCode)
  window.setTimeout(() => { copiedCode.value = '' }, 1600)
}

function buildBasePresentation(refresh = false) {
  const key = cacheKey(props.documentId, props.documentVersion)
  const cached = readCachedCourseDocument(key)
  if (refresh !== true && cached?.html && cached?.rendererVersion) {
    basePresentation = cached
  } else {
    basePresentation = renderCourseDocument(props.text)
    writeCachedCourseDocument(key, basePresentation)
  }
  updatePresentation()
}

function updatePresentation() {
  if (!basePresentation) return
  if (String(props.searchQuery || '').trim()) {
    presentation.value = renderCourseDocument(props.text, { query: props.searchQuery, currentMatch: props.searchIndex })
  } else {
    presentation.value = basePresentation
  }
  nextTick(() => {
    renderMathAndMermaid()
    emit('rendered', presentation.value)
  })
}

function setMode(next) {
  if (mode.value === next) return
  mode.value = next
  emit('mode-change', next)
  nextTick(() => renderMathAndMermaid())
}

async function scrollToCurrentMatch() {
  let root = mode.value === 'raw' ? rawRef.value : rootRef.value
  if (!root) return
  let hit = root.querySelector('.course-search-hit--current')
  // Search includes the complete source, including import notes and markup
  // omitted from the reading layout. Reveal those matches in the original
  // text instead of showing a count for an invisible destination.
  if (!hit && mode.value === 'preview' && rawMatches.value[props.searchIndex] !== undefined) {
    setMode('raw')
    await nextTick()
    root = rawRef.value
    hit = root?.querySelector('.course-search-hit--current')
  }
  hit?.scrollIntoView({ block: 'center', behavior: 'smooth' })
}

function scrollToSourceOffset(offset) {
  const root = mode.value === 'raw' ? rawRef.value : rootRef.value
  if (!root) return
  const target = Number(offset) || 0
  const ranges = Array.from(root.querySelectorAll('[data-source-start][data-source-end]'))
  const containing = ranges.filter(item => Number(item.dataset.sourceStart) <= target && Number(item.dataset.sourceEnd) > target)
    .sort((a, b) => (Number(a.dataset.sourceEnd) - Number(a.dataset.sourceStart)) - (Number(b.dataset.sourceEnd) - Number(b.dataset.sourceStart)))
  // Chapter anchors may point to Markdown markers or whitespace that are not
  // rendered. Continue at the next text block instead of jumping to page one.
  const following = ranges.filter(item => Number(item.dataset.sourceStart) >= target)
    .sort((a, b) => Number(a.dataset.sourceStart) - Number(b.dataset.sourceStart))
  // A chapter starts at the top of the reading pane. Centering it leaves the
  // preceding chapter above it and lets scroll tracking replace the selection.
  const anchor = containing[0] || following[0] || ranges.at(-1)
  const viewport = root.closest?.('.reading-viewport')
  if (anchor && viewport) {
    viewport.scrollTop += anchor.getBoundingClientRect().top - viewport.getBoundingClientRect().top
  } else {
    anchor?.scrollIntoView({ block: 'start', behavior: 'instant' })
  }
}

function handlePreviewClick(event) {
  const root = rootRef.value
  const link = event.target.closest('a[href^="#course-anchor-"]')
  if (link && root?.contains(link)) {
    const id = link.getAttribute('href').slice(1)
    const target = Array.from(root.querySelectorAll('[id]')).find((element) => element.id === id)
    if (target) {
      event.preventDefault()
      // Empty upstream anchors have no scroll box; align the following block.
      let visibleTarget = target
      while (!visibleTarget.getBoundingClientRect().height && visibleTarget.nextElementSibling) {
        visibleTarget = visibleTarget.nextElementSibling
      }
      const viewport = root.closest?.('.reading-viewport')
      if (viewport) {
        viewport.scrollTop += visibleTarget.getBoundingClientRect().top - viewport.getBoundingClientRect().top
      } else {
        visibleTarget.scrollIntoView({ block: 'start', behavior: 'smooth' })
      }
      return
    }
  }
  copyCode(event)
}

watch(() => [props.text, props.documentId, props.documentVersion], buildBasePresentation, { immediate: true })
watch(() => [props.searchQuery, props.searchIndex], updatePresentation)

defineExpose({
  getSelectionRoot: () => mode.value === 'raw' ? rawRef.value : rootRef.value,
  scrollToCurrentMatch,
  scrollToSourceOffset,
})
</script>

<template>
  <div class="course-document-reader" data-testid="course-document-preview">
    <div class="course-document-reader__toolbar" role="toolbar" aria-label="文档阅读视图">
      <div class="course-document-reader__mode-actions">
        <button type="button" :class="{ active: mode === 'preview' }" :aria-pressed="mode === 'preview'" @click="setMode('preview')"><BookOpenText :size="15" />阅读版</button>
        <button type="button" :class="{ active: mode === 'raw' }" :aria-pressed="mode === 'raw'" @click="setMode('raw')"><FileCode2 :size="15" />原文</button>
        <button v-if="mode === 'preview'" type="button" class="icon-action" title="刷新排版" aria-label="刷新排版" @click="buildBasePresentation(true)"><RefreshCw :size="15" /></button>
      </div>
    </div>

    <article
      v-if="mode === 'preview'"
      ref="rootRef"
      class="course-document-preview"
      :style="{ zoom }"
      @click="handlePreviewClick"
      @mouseup="emit('mouseup', $event)"
    >
      <div v-if="!presentation.html" class="course-document-empty">当前文档没有可渲染的正文。</div>
      <div v-else v-html="presentation.html" />
    </article>
    <pre v-else ref="rawRef" class="course-document-raw" :style="{ zoom }" @mouseup="emit('mouseup', $event)"><span data-source-start="0" :data-source-end="sourceTextLength(text)">{{ rawSearchParts.before }}<mark v-if="rawSearchParts.hit" class="course-search-hit course-search-hit--current">{{ rawSearchParts.hit }}</mark>{{ rawSearchParts.after }}</span></pre>

    <div v-if="mode === 'preview' && copiedCode" class="course-document-toast" role="status"><Check :size="15" />代码已复制</div>
  </div>
</template>

<style>
.course-document-reader { position: relative; min-width: 0; }
.course-document-reader__toolbar { display: flex; align-items: center; justify-content: flex-end; margin: 0 auto 12px; }
.course-document-reader__mode-actions, .course-document-reader__mode-actions button, .course-document-toast { display: flex; align-items: center; }
.course-document-reader__mode-actions { gap: 5px; }
.course-document-reader__mode-actions button { gap: 6px; min-height: 34px; padding: 0 10px; color: var(--color-text-muted); border: 1px solid transparent; border-radius: 6px; background: transparent; font-size: 14px; cursor: pointer; }
.course-document-reader__mode-actions button:hover { color: var(--color-text); background: var(--color-surface-subtle); }
.course-document-reader__mode-actions button.active { color: var(--color-accent); border-color: var(--color-border); background: var(--color-accent-soft); font-weight: 650; }
.course-document-reader__mode-actions button.icon-action { width: 34px; justify-content: center; padding: 0; }
.course-document-preview { width: min(100%, 900px); margin: 0 auto; padding: 34px clamp(26px, 5vw, 64px) 72px; color: var(--color-text); border: 1px solid var(--color-border); border-radius: 8px; background: var(--color-surface); box-shadow: 0 10px 28px rgb(6 20 27 / 7%); font-family: var(--font-sans); font-size: 16px; line-height: 1.85; overflow-wrap: anywhere; user-select: text; }
.course-document-raw { width: min(100%, 900px); min-height: 100%; margin: 0 auto; padding: 34px clamp(26px, 5vw, 64px) 72px; color: var(--color-text); border: 1px solid var(--color-border); border-radius: 8px; background: var(--color-surface); font-family: var(--font-mono); font-size: 14px; line-height: 1.8; overflow: auto; white-space: pre-wrap; user-select: text; }
.lesson-block { margin: 0 0 18px; }
.lesson-block--section { margin-top: 28px; margin-bottom: 12px; }
.lesson-block--section:first-child { margin-top: 0; }
.course-heading { margin: 0; color: var(--color-text); font-weight: 700; line-height: 1.35; letter-spacing: 0; }
.course-heading--1 { font-size: 28px; padding-bottom: 12px; border-bottom: 1px solid var(--color-border); }
.course-heading--2 { font-size: 22px; padding-left: 12px; border-left: 3px solid var(--color-accent); }
.course-heading--3, .course-heading--4 { font-size: 18px; color: var(--color-text-secondary); }
.lesson-block__label { margin-bottom: 7px; color: var(--color-text-muted); font-size: 14px; font-weight: 650; letter-spacing: .02em; }
.lesson-block--explanation p, .lesson-block--summary p, .lesson-block--callout p { margin: 0; }
.lesson-block--summary { padding: 14px 16px; border-left: 3px solid var(--color-accent); background: var(--color-accent-soft); }
.lesson-block--callout { padding: 14px 16px; border-left: 3px solid var(--color-border-strong); background: var(--color-surface-subtle); }
.lesson-callout--warning, .lesson-callout--caution { border-left-color: var(--color-danger); }
.lesson-block--steps { padding-left: 8px; }
.course-list { margin: 0; padding-left: 24px; }
.course-list li { margin: 7px 0; padding-left: 4px; }
.course-inline-code { display: inline-block; padding: 1px 6px; color: var(--color-accent); border: 1px solid var(--color-border); border-radius: 4px; background: var(--color-surface-subtle); font-family: var(--font-mono); font-size: .93em; }
.course-link { color: var(--color-accent); text-decoration: underline; text-underline-offset: 3px; }
.course-code-heading { display: flex; align-items: center; justify-content: space-between; min-height: 40px; padding: 0 13px; color: #d9e3e6; background: #11212d; font-family: var(--font-mono); font-size: 14px; }
.course-code-heading button { min-height: 28px; padding: 0 8px; color: #d9e3e6; border: 1px solid #60727c; border-radius: 4px; background: transparent; font-size: 14px; cursor: pointer; }
.course-code-heading button:hover { background: #253745; }
.course-code { margin: 0; overflow: auto; padding: 16px; color: #eef2f2; background: #11212d; font-family: var(--font-mono); font-size: 14px; line-height: 1.7; }
.lesson-block--practice { overflow: hidden; border: 1px solid #253745; border-radius: 8px; background: #11212d; }
.lesson-block--practice .lesson-block__label { margin: 0; padding: 10px 13px; color: #d9e3e6; background: #06141b; }
.course-table-wrap { overflow-x: auto; border: 1px solid var(--color-border); border-radius: 6px; }
.course-table { width: 100%; border-collapse: collapse; font-size: 14px; }
.course-table th, .course-table td { padding: 10px 12px; border-bottom: 1px solid var(--color-border); text-align: left; vertical-align: top; }
.course-table th { color: var(--color-text); background: var(--color-surface-subtle); font-weight: 650; }
.course-table tr:last-child td { border-bottom: 0; }
.course-math { overflow-x: auto; padding: 14px; border: 1px solid var(--color-border); border-radius: 6px; background: var(--color-surface-subtle); text-align: center; }
.course-mermaid { overflow-x: auto; padding: 12px; border: 1px solid var(--color-border); border-radius: 6px; background: var(--color-surface-subtle); }
.course-mermaid__canvas { display: flex; min-height: 80px; align-items: center; justify-content: center; }
.course-mermaid__source { margin: 0; color: var(--color-text-muted); font-family: var(--font-mono); font-size: 14px; white-space: pre-wrap; }
.course-figure { margin: 12px 0; text-align: center; }
.course-figure img { max-width: 100%; max-height: 480px; border: 1px solid var(--color-border); border-radius: 6px; object-fit: contain; }
.course-image-missing { color: var(--color-text-muted); }
.course-search-hit { padding: 1px 2px; background: #f3e3b4; }
.course-search-hit--current { color: var(--color-text); outline: 2px solid var(--color-accent); }
.course-document-empty { padding: 28px; color: var(--color-text-muted); text-align: center; }
.course-document-toast { position: fixed; right: 28px; bottom: 28px; z-index: 5; gap: 7px; padding: 10px 13px; color: var(--color-text); border: 1px solid var(--color-border); border-radius: 6px; background: var(--color-surface); box-shadow: 0 8px 22px rgb(6 20 27 / 12%); font-size: 14px; }
@media (max-width: 760px) {
  .course-document-reader__toolbar { align-items: flex-start; flex-direction: column; }
  .course-document-reader__mode-actions { width: 100%; }
  .course-document-reader__mode-actions button { flex: 1; justify-content: center; }
  .course-heading--1 { font-size: 24px; }
  .course-heading--2 { font-size: 20px; }
  .course-document-preview { padding: 24px 20px 54px; }
}
</style>
