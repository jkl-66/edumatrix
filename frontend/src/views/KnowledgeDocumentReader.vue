<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  ArrowLeft,
  BookOpen,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Download,
  FileSearch,
  Focus,
  LoaderCircle,
  MessageSquareText,
  Maximize2,
  Minimize2,
  Minus,
  NotebookPen,
  Plus,
  RefreshCw,
  RotateCcw,
  ShieldCheck,
  WandSparkles,
  X,
} from '@lucide/vue'
import SelectionToolbar from '../components/SelectionToolbar.vue'
import CourseDocumentPreview from '../components/CourseDocumentPreview.vue'
import IncrementalMarkdownRenderer from '../components/IncrementalMarkdownRenderer.vue'
import SearchField from '../components/ui/SearchField.vue'
import TaskState from '../components/TaskState.vue'
import AgentTimeline from '../components/AgentTimeline.vue'
import SourceCitation from '../components/SourceCitation.vue'
import {
  askDocumentSelection,
  createDocumentSelection,
  generateDocumentResource,
  generateDocumentSelectionResource,
  getDocumentReaderDocument,
  getDocumentReaderExport,
  getDocumentReaderMedia,
  getDocumentReaderPage,
  getDocumentReaderSlidePreview,
  getDocumentReaderState,
  retryDocumentSelectionOcr,
  saveDocumentReadingPosition,
  saveDocumentSelectionNote,
} from '../api/knowledge'

const props = defineProps({ studentId: { type: String, default: '' } })
const route = useRoute()
const router = useRouter()

const readerDoc = ref(null)
const loading = ref(true)
const loadError = ref('')
const positionNotice = ref('')
const readingViewport = ref(null)
const contentRef = ref(null)
const coursePreviewRef = ref(null)
const searchMarkRef = ref(null)
const pageFrameRef = ref(null)
const pptxStageRef = ref(null)
const questionInput = ref(null)
const noteInput = ref(null)

const activePage = ref(1)
const activeSlideNumber = ref(1)
const slideAssetUrls = ref({})
const slideAssetsLoading = ref(false)
const slideAssetsError = ref('')
const pptxFullscreen = ref(false)
const pageAssetUrl = ref('')
const pageAssetLoading = ref(false)
const pageAssetError = ref('')
const mediaAssetUrl = ref('')
const mediaAssetLoading = ref(false)
const mediaAssetError = ref('')
const originalPdfUrl = ref('')
const originalPdfLoading = ref(false)
const originalPdfError = ref('')
const exportBusy = ref(false)
const exportError = ref('')
const exportNotice = ref('')
const zoom = ref(1)
const activeSectionId = ref('')
const charOffset = ref(0)
const scrollRatio = ref(0)
const restoredAt = ref('')

const searchQuery = ref('')
const searchIndex = ref(0)
const selection = ref(null)
const toolbarVisible = ref(false)
const toolbarPosition = ref({ left: 0, top: 0 })
const selectionError = ref('')
const busyAction = ref('')
const activeSideTab = ref('source')
const questionDraft = ref('')
const noteDraft = ref('')
const resourceType = ref('handout')
const generationScope = ref('document')
const generationResult = ref(null)
const generationError = ref('')
const noteResult = ref(null)
const noteError = ref('')
const answerError = ref('')
const operationKeys = reactive({ ask: '', note: '', selectionGenerate: '', documentGenerate: '' })

const imageDrag = reactive({ active: false, pointerId: null, startX: 0, startY: 0, rect: null })
let positionTimer = null
let pageRequest = 0
let slideAssetRequest = 0
let initialized = false

const sourceDocumentId = computed(() => String(route.params.documentId || ''))
const hasPages = computed(() => Boolean(readerDoc.value?.pages?.length))
const isVideo = computed(() => readerDoc.value?.media?.kind === 'video')
const isPptxDocument = computed(() => {
  const type = String(readerDoc.value?.file_type || '').toLowerCase()
  const filename = String(readerDoc.value?.filename || '').toLowerCase()
  return type === 'pptx' || type === 'ppt' || filename.endsWith('.pptx') || filename.endsWith('.ppt')
})
const slides = computed(() => Array.isArray(readerDoc.value?.slides) ? readerDoc.value.slides : [])
const hasSlides = computed(() => isPptxDocument.value && slides.value.length > 0)
const activeSlide = computed(() => slides.value.find(item => Number(item.slide_num) === Number(activeSlideNumber.value)) || slides.value[0] || null)
const hasSlidePreviews = computed(() => (
  readerDoc.value?.pptx_preview?.status === 'ready'
  && slides.value.some(item => item.preview_url)
))
const canUsePptxFullscreen = computed(() => (
  typeof document !== 'undefined'
  && Boolean(document.fullscreenEnabled)
  && typeof pptxStageRef.value?.requestFullscreen === 'function'
))
const activeSlideAssetUrl = computed(() => slideAssetUrls.value[Number(activeSlideNumber.value)] || '')
const pptxSlideStyle = computed(() => ({ width: `${Math.round(zoom.value * 100)}%` }))
const isCoursePreviewDocument = computed(() => {
  if (readerDoc.value?.reader_mode) return readerDoc.value.reader_mode === 'course_preview'
  const type = String(readerDoc.value?.file_type || '').toLowerCase()
  const filename = String(readerDoc.value?.filename || '').toLowerCase()
  return !hasPages.value && !isVideo.value && (
    ['md', 'markdown', 'txt', 'text', 'json', 'ipynb', 'notebook', 'py', 'python_code', 'docx', 'word', 'pptx', 'presentation', 'ppt', 'csv', 'tex', 'epub'].includes(type)
    || filename.endsWith('.md')
    || filename.endsWith('.markdown')
    || filename.endsWith('.txt')
    || filename.endsWith('.ipynb')
    || filename.endsWith('.docx')
    || filename.endsWith('.pptx')
  )
})
const isPdfDocument = computed(() => {
  const type = String(readerDoc.value?.file_type || '').toLowerCase()
  const filename = String(readerDoc.value?.filename || '').toLowerCase()
  return type === 'pdf' || type === 'application/pdf' || filename.endsWith('.pdf')
})
const activePageMeta = computed(() => (
  readerDoc.value?.pages?.find(item => Number(item.page_number) === Number(activePage.value)) || null
))
const chapters = computed(() => readerDoc.value?.chapters || [])
const sourceRefs = computed(() => readerDoc.value?.source_refs || [])
const selectionTextRegions = computed(() => readerDoc.value?.selection_text_regions || [])
const activePageTextRegions = computed(() => selectionTextRegions.value.filter(item => (
  Number(item.page_number) === Number(activePage.value)
)))
const requestedSourceRefId = computed(() => String(route.query.source_ref_id || ''))
const requestedSourceRef = computed(() => sourceRefs.value.find(item => (
  String(item.id || item.source_ref_id || item.sourceRefId || '') === requestedSourceRefId.value
)) || null)
const activeChapter = computed(() => (
  chapters.value.find(item => item.id === activeSectionId.value)
  || chapters.value.find(item => Number(item.char_start) <= charOffset.value && Number(item.char_end) >= charOffset.value)
  || chapters.value[0]
  || null
))
const activeSourceRef = computed(() => {
  if (requestedSourceRef.value) return requestedSourceRef.value
  if (selection.value?.source_ref_id) {
    return sourceRefs.value.find(item => item.id === selection.value.source_ref_id) || null
  }
  if (hasPages.value) {
    return sourceRefs.value.find(item => Number(item.page_number) === Number(activePage.value)) || sourceRefs.value[0] || null
  }
  if (activeChapter.value?.source_ref_id) {
    return sourceRefs.value.find(item => item.id === activeChapter.value.source_ref_id) || null
  }
  return sourceRefs.value.find(item => (
    Number(item.char_start) <= charOffset.value && Number(item.char_end) >= charOffset.value
  )) || sourceRefs.value[0] || null
})
const currentLocationLabel = computed(() => {
  if (hasPages.value) return `第 ${activePage.value} 页`
  if (activeChapter.value) return activeChapter.value.title
  return '文档开头'
})
function buildReaderPresentation(value) {
  const source = String(value || '')
  const displayToSource = [0]
  const literalBreak = / {2}\\n(?=\s*(?:>|#{1,6}\s|[-*+]\s|\d+\.\s|$))/g
  let text = ''
  let cursor = 0
  let match = literalBreak.exec(source)

  const appendSource = (start, end) => {
    for (let index = start; index < end; index += 1) {
      text += source[index]
      displayToSource.push(index + 1)
    }
  }

  while (match) {
    appendSource(cursor, match.index)
    text += '\n'
    displayToSource.push(match.index + match[0].length)
    cursor = match.index + match[0].length
    match = literalBreak.exec(source)
  }
  appendSource(cursor, source.length)
  return { text, displayToSource }
}

const readerPresentation = computed(() => buildReaderPresentation(readerDoc.value?.content))

function sourceOffsetForDisplay(offset) {
  const map = readerPresentation.value.displayToSource
  const index = Math.min(map.length - 1, Math.max(0, Number(offset) || 0))
  return map[index]
}

function displayOffsetForSource(offset) {
  const map = readerPresentation.value.displayToSource
  const target = Math.max(0, Number(offset) || 0)
  let low = 0
  let high = map.length - 1
  while (low < high) {
    const middle = Math.ceil((low + high) / 2)
    if (map[middle] <= target) low = middle
    else high = middle - 1
  }
  return low
}

const searchMatches = computed(() => {
  const content = readerPresentation.value.text
  const query = searchQuery.value.trim().toLocaleLowerCase()
  if (!query) return []
  const haystack = content.toLocaleLowerCase()
  const matches = []
  let cursor = 0
  while (cursor < haystack.length && matches.length < 500) {
    const index = haystack.indexOf(query, cursor)
    if (index < 0) break
    matches.push(index)
    cursor = index + Math.max(query.length, 1)
  }
  return matches
})
const searchParts = computed(() => {
  const content = readerPresentation.value.text
  const query = searchQuery.value.trim()
  const start = searchMatches.value[searchIndex.value]
  if (!query || start === undefined) return { before: content, hit: '', after: '' }
  return {
    before: content.slice(0, start),
    hit: content.slice(start, start + query.length),
    after: content.slice(start + query.length),
  }
})
const visibleImageRect = computed(() => {
  if (imageDrag.active && imageDrag.rect) return imageDrag.rect
  if (
    selection.value?.selection_type === 'image'
    && Number(selection.value.page_number) === Number(activePage.value)
  ) return selection.value.normalized_rect
  if (requestedSourceRef.value && Number(requestedSourceRef.value.page_number) === Number(activePage.value)) {
    return requestedSourceRef.value.image_region || requestedSourceRef.value.imageRegion || null
  }
  return null
})
const imageRectStyle = computed(() => {
  const rect = visibleImageRect.value
  if (!rect) return {}
  return {
    left: `${Number(rect.x) * 100}%`,
    top: `${Number(rect.y) * 100}%`,
    width: `${Number(rect.width) * 100}%`,
    height: `${Number(rect.height) * 100}%`,
  }
})
const documentContentStyle = computed(() => ({
  fontSize: `${Math.max(14, 16 * zoom.value)}px`,
}))
const toolbarStyle = computed(() => ({
  left: `${toolbarPosition.value.left}px`,
  top: `${toolbarPosition.value.top}px`,
}))
const selectionSummary = computed(() => {
  if (!selection.value) return '先在正文中划选文字，或在页图上拖框。'
  if (selection.value.stale) return '原文已更新，请重新选择内容。'
  if (selection.value.selection_type === 'image') {
    const text = selection.value.ocr_text?.trim()
    return text || `第 ${selection.value.page_number} 页图片区域`
  }
  return buildReaderPresentation(selection.value.quote).text || '已选择文字'
})
const canUseSelection = computed(() => Boolean(selection.value?.id && !selection.value?.stale))
const sideTabs = [
  { id: 'source', label: '来源' },
  { id: 'ask', label: '提问' },
  { id: 'actions', label: '笔记与生成' },
]
const resourceOptions = [
  { value: 'handout', label: '个性化讲义' },
  { value: 'mind_map', label: '思维导图' },
  { value: 'quiz', label: '测验题资源' },
  { value: 'training_task', label: '实训任务书' },
]

function apiMessage(error, fallback) {
  const detail = error?.detail || error?.response?.data?.detail || error?.message
  if (typeof detail === 'string' && detail.trim()) return detail
  if (detail?.message) return detail.message
  return fallback
}

function operationKey(kind) {
  if (!operationKeys[kind]) {
    const suffix = globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(16).slice(2)}`
    operationKeys[kind] = `f7-reader-${kind}-${suffix}`
  }
  return operationKeys[kind]
}

function resetOperationKey(kind) {
  operationKeys[kind] = ''
}

function revokePageAsset() {
  if (pageAssetUrl.value) URL.revokeObjectURL(pageAssetUrl.value)
  pageAssetUrl.value = ''
}

function revokeSlideAssets() {
  Object.values(slideAssetUrls.value).forEach(url => URL.revokeObjectURL(url))
  slideAssetUrls.value = {}
}

async function loadSlideAssets() {
  const previewSlides = slides.value.filter(item => item.preview_url)
  if (!previewSlides.length || !readerDoc.value?.source_document_id) return
  const sourceId = readerDoc.value.source_document_id
  const request = ++slideAssetRequest
  slideAssetsLoading.value = true
  slideAssetsError.value = ''
  revokeSlideAssets()
  const loaded = {}
  try {
    await Promise.all(previewSlides.map(async (slide) => {
      try {
        loaded[Number(slide.slide_num)] = await getDocumentReaderSlidePreview(sourceId, slide.slide_num)
      } catch {
        // A missing page remains available through the parsed reading view below.
      }
    }))
    if (request !== slideAssetRequest) {
      Object.values(loaded).forEach(url => URL.revokeObjectURL(url))
      return
    }
    slideAssetUrls.value = loaded
    if (!Object.keys(loaded).length) {
      slideAssetsError.value = '原版幻灯片暂时无法显示，你仍可查看下方文字阅读版或下载原文件。'
    } else if (Object.keys(loaded).length < previewSlides.length) {
      slideAssetsError.value = '部分幻灯片暂时无法显示，其他页面和文字阅读版仍可使用。'
    }
  } finally {
    if (request === slideAssetRequest) slideAssetsLoading.value = false
  }
}

function revokeMediaAsset() {
  if (mediaAssetUrl.value) URL.revokeObjectURL(mediaAssetUrl.value)
  mediaAssetUrl.value = ''
}

function revokeOriginalPdf() {
  if (originalPdfUrl.value) URL.revokeObjectURL(originalPdfUrl.value)
  originalPdfUrl.value = ''
}

async function loadOriginalPdf() {
  if (!isPdfDocument.value || !readerDoc.value?.source_document_id) return
  originalPdfLoading.value = true
  originalPdfError.value = ''
  revokeOriginalPdf()
  try {
    const result = await getDocumentReaderExport(readerDoc.value.source_document_id)
    const contentType = String(result.headers?.['content-type'] || '').toLowerCase()
    if (!contentType.includes('application/pdf')) {
      throw new Error('当前来源没有可预览的原始 PDF 文件，解析文本仍可继续阅读。')
    }
    originalPdfUrl.value = URL.createObjectURL(result.blob)
  } catch (error) {
    originalPdfError.value = apiMessage(error, '原始 PDF 暂时无法预览，解析内容仍可继续阅读。')
  } finally {
    originalPdfLoading.value = false
  }
}

async function loadPageAsset() {
  if (!hasPages.value || !readerDoc.value?.source_document_id) return
  const request = ++pageRequest
  pageAssetLoading.value = true
  pageAssetError.value = ''
  revokePageAsset()
  try {
    const url = await getDocumentReaderPage(readerDoc.value.source_document_id, activePage.value)
    if (request !== pageRequest) {
      URL.revokeObjectURL(url)
      return
    }
    pageAssetUrl.value = url
  } catch (error) {
    if (request === pageRequest) pageAssetError.value = apiMessage(error, '这一页暂时无法显示，请重试。')
  } finally {
    if (request === pageRequest) pageAssetLoading.value = false
  }
}

async function loadMediaAsset() {
  if (!isVideo.value || !readerDoc.value?.source_document_id) return
  mediaAssetLoading.value = true
  mediaAssetError.value = ''
  revokeMediaAsset()
  try {
    mediaAssetUrl.value = await getDocumentReaderMedia(readerDoc.value.source_document_id)
  } catch (error) {
    mediaAssetError.value = apiMessage(error, '视频暂时无法播放，文字说明仍可继续阅读。')
  } finally {
    mediaAssetLoading.value = false
  }
}

function currentPositionPayload() {
  return {
    document_version: readerDoc.value.document_version,
    page_number: hasPages.value ? Number(activePage.value) : null,
    section_id: activeChapter.value?.id || null,
    char_offset: Math.max(0, Math.round(charOffset.value)),
    scroll_ratio: Math.min(1, Math.max(0, Number(scrollRatio.value) || 0)),
    zoom: zoom.value,
  }
}

async function savePosition() {
  if (!initialized || !readerDoc.value) return
  const documentId = String(readerDoc.value.source_document_id || sourceDocumentId.value || '')
  if (!documentId) return
  positionNotice.value = ''
  try {
    const saved = await saveDocumentReadingPosition(documentId, currentPositionPayload())
    restoredAt.value = saved.updated_at || restoredAt.value
  } catch (error) {
    positionNotice.value = apiMessage(error, '当前位置未能保存，阅读内容不受影响。')
  }
}

function schedulePositionSave() {
  if (!initialized) return
  clearTimeout(positionTimer)
  positionTimer = setTimeout(savePosition, 350)
}

function handleReaderScroll(event) {
  const element = event.currentTarget
  const max = Math.max(0, element.scrollHeight - element.clientHeight)
  scrollRatio.value = max ? element.scrollTop / max : 0
  if (!hasPages.value && readerDoc.value?.content) {
    charOffset.value = Math.round(readerDoc.value.content.length * scrollRatio.value)
    const chapter = chapters.value.find(item => (
      Number(item.char_start) <= charOffset.value && Number(item.char_end) >= charOffset.value
    ))
    if (chapter) activeSectionId.value = chapter.id
  }
  schedulePositionSave()
}

async function restoreScroll(ratio) {
  await nextTick()
  const element = readingViewport.value
  if (!element) return
  const max = Math.max(0, element.scrollHeight - element.clientHeight)
  element.scrollTop = max * Math.min(1, Math.max(0, Number(ratio) || 0))
}

async function loadReader() {
  loading.value = true
  loadError.value = ''
  initialized = false
  try {
    const [documentResult, stateResult] = await Promise.all([
      getDocumentReaderDocument(sourceDocumentId.value),
      getDocumentReaderState(sourceDocumentId.value),
    ])
    const expectedCourseId = String(route.query.course_id || '')
    if (expectedCourseId && expectedCourseId !== documentResult.course?.id) {
      throw new Error('当前文档不属于链接指定的课程')
    }
    readerDoc.value = documentResult
    if (isPdfDocument.value) void loadOriginalPdf()
    const position = stateResult.position && !stateResult.position.stale ? stateResult.position : null
    const deepLinkRef = documentResult.source_refs?.find(item => (
      String(item.id || item.source_ref_id || item.sourceRefId || '') === String(route.query.source_ref_id || '')
    )) || null
    const requestedPage = Number(route.query.page || deepLinkRef?.page_number || deepLinkRef?.pageNumber)
    const requestedChar = Number(route.query.char_start ?? deepLinkRef?.char_start ?? deepLinkRef?.charStart)
    const hasRequestedPage = Number.isFinite(requestedPage)
      && documentResult.pages?.some(item => Number(item.page_number) === requestedPage)
    const hasRequestedChar = Number.isFinite(requestedChar) && requestedChar >= 0
    zoom.value = Number(position?.zoom || 1)
    activePage.value = Number(hasRequestedPage ? requestedPage : (position?.page_number || documentResult.pages?.[0]?.page_number || 1))
    const requestedSlide = Number(route.query.slide || 1)
    activeSlideNumber.value = slides.value.some(item => Number(item.slide_num) === requestedSlide)
      ? requestedSlide
      : Number(slides.value[0]?.slide_num || 1)
    if (hasSlidePreviews.value) await loadSlideAssets()
    activeSectionId.value = String(
      route.query.chapter_id
      || deepLinkRef?.chapter_id
      || deepLinkRef?.chapterId
      || position?.section_id
      || documentResult.chapters?.[0]?.id
      || '',
    )
    charOffset.value = Number(hasRequestedChar ? requestedChar : (position?.char_offset || 0))
    scrollRatio.value = hasRequestedPage || hasRequestedChar ? 0 : Number(position?.scroll_ratio || 0)
    restoredAt.value = position?.updated_at || ''
    selection.value = stateResult.selection || null
    questionDraft.value = stateResult.selection?.question_draft || ''
    if (stateResult.selection?.answer_text) activeSideTab.value = 'ask'
    if (hasPages.value) await loadPageAsset()
    if (isVideo.value) await loadMediaAsset()
    loading.value = false
    if (hasRequestedChar && !hasPages.value) await scrollToOffset(charOffset.value)
    else if (route.query.chapter_id) await jumpToChapter(activeChapter.value, false)
    else await restoreScroll(scrollRatio.value)
    if (route.query.source_ref_id && !deepLinkRef) positionNotice.value = '当前引用不属于这份文档，已保留文档可读内容。'
    initialized = true
  } catch (error) {
    loadError.value = apiMessage(error, '文档阅读器加载失败。')
    loading.value = false
  }
}

function pageStep(delta) {
  const pages = readerDoc.value?.pages || []
  const index = pages.findIndex(item => Number(item.page_number) === Number(activePage.value))
  const target = pages[index + delta]
  if (target) selectPage(target.page_number)
}

function slideStep(delta) {
  if (!slides.value.length) return
  const index = slides.value.findIndex(item => Number(item.slide_num) === Number(activeSlideNumber.value))
  const next = Math.min(slides.value.length - 1, Math.max(0, index + delta))
  activeSlideNumber.value = Number(slides.value[next]?.slide_num || 1)
}

function selectSlide(slideNumber) {
  if (slides.value.some(item => Number(item.slide_num) === Number(slideNumber))) {
    activeSlideNumber.value = Number(slideNumber)
  }
}

async function togglePptxFullscreen() {
  const stage = pptxStageRef.value
  if (!stage || !canUsePptxFullscreen.value) return
  if (document.fullscreenElement === stage) await document.exitFullscreen()
  else await stage.requestFullscreen()
}

function syncPptxFullscreen() {
  pptxFullscreen.value = document.fullscreenElement === pptxStageRef.value
}

function slideImageUrl(image) {
  const data = String(image?.data || '')
  if (!data) return ''
  const contentType = String(image?.content_type || 'image/png').toLowerCase()
  const safeType = /^image\/[a-z0-9.+-]+$/.test(contentType) ? contentType : 'image/png'
  return `data:${safeType};base64,${data}`
}

function pptxThumbnailStyle(slide) {
  const width = Number(slide?.preview_width)
  const height = Number(slide?.preview_height)
  return { aspectRatio: width > 0 && height > 0 ? `${width} / ${height}` : '16 / 9' }
}

async function selectPage(pageNumber) {
  const page = readerDoc.value?.pages?.find(item => Number(item.page_number) === Number(pageNumber))
  if (!page) return
  activePage.value = Number(page.page_number)
  const ref = sourceRefs.value.find(item => Number(item.page_number) === Number(activePage.value))
  if (ref?.chapter_id) activeSectionId.value = ref.chapter_id
  scrollRatio.value = 0
  await loadPageAsset()
  schedulePositionSave()
}

function adjustZoom(delta) {
  const minimum = hasPages.value ? 0.5 : 0.9
  zoom.value = Math.min(2, Math.max(minimum, Math.round((zoom.value + delta) * 10) / 10))
}

function findTextNodeAtOffset(root, offset) {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT)
  let remaining = Math.max(0, offset)
  let node = walker.nextNode()
  while (node) {
    if (remaining <= node.textContent.length) return { node, offset: remaining }
    remaining -= node.textContent.length
    node = walker.nextNode()
  }
  return null
}

async function scrollToOffset(offset) {
  await nextTick()
  if (isCoursePreviewDocument.value) {
    coursePreviewRef.value?.scrollToSourceOffset?.(offset)
    return
  }
  const root = contentRef.value
  const viewport = readingViewport.value
  if (!root || !viewport) return
  const point = findTextNodeAtOffset(root, displayOffsetForSource(offset))
  if (!point) return
  const range = document.createRange()
  range.setStart(point.node, point.offset)
  range.setEnd(point.node, Math.min(point.node.textContent.length, point.offset + 1))
  const rect = range.getBoundingClientRect()
  const viewportRect = viewport.getBoundingClientRect()
  viewport.scrollTop += rect.top - viewportRect.top - 96
}

async function jumpToChapter(chapter, persist = true) {
  if (!chapter) return
  activeSectionId.value = chapter.id
  charOffset.value = Number(chapter.char_start || 0)
  await scrollToOffset(charOffset.value)
  if (persist) schedulePositionSave()
}

async function moveSearch(direction) {
  if (!searchMatches.value.length) return
  searchIndex.value = (searchIndex.value + direction + searchMatches.value.length) % searchMatches.value.length
  charOffset.value = sourceOffsetForDisplay(searchMatches.value[searchIndex.value])
  await nextTick()
  if (isCoursePreviewDocument.value) coursePreviewRef.value?.scrollToCurrentMatch?.()
  else searchMarkRef.value?.scrollIntoView({ block: 'center' })
  schedulePositionSave()
}

function sourceRefForText(start, end) {
  return sourceRefs.value.find(item => (
    Number.isFinite(Number(item.char_start))
    && Number.isFinite(Number(item.char_end))
    && Number(item.char_start) <= start
    && Number(item.char_end) >= end
  )) || activeSourceRef.value
}

function setToolbarPosition(left, top) {
  toolbarPosition.value = {
    left: Math.max(236, Math.min(window.innerWidth - 420, left)),
    top: Math.max(64, Math.min(window.innerHeight - 58, top)),
  }
}

function trimSourceSelection(start, end) {
  const source = String(readerDoc.value?.content || '')
  const rawQuote = String(readerDoc.value?.content || '').slice(start, end)
  let nextStart = Math.max(0, Math.min(source.length, Number(start) || 0))
  let nextEnd = Math.max(nextStart, Math.min(source.length, Number(end) || 0))
  while (nextStart < nextEnd && /\s/.test(source[nextStart])) nextStart += 1
  while (nextEnd > nextStart && /\s/.test(source[nextEnd - 1])) nextEnd -= 1
  const quote = nextStart === start && nextEnd === end ? rawQuote : source.slice(nextStart, nextEnd)
  return { start: nextStart, end: nextEnd, quote }
}

function textLengthToBoundary(element, container, offset) {
  if (!element.contains(container) && element !== container) return 0
  const measure = document.createRange()
  measure.selectNodeContents(element)
  measure.setEnd(container, offset)
  return measure.toString().length
}

function pageSelectionBounds(range) {
  const root = pageFrameRef.value
  if (!root) return null
  const regions = Array.from(root.querySelectorAll('[data-selection-region]'))
    .filter(region => {
      try { return range.intersectsNode(region) } catch { return false }
    })
    .sort((left, right) => Number(left.dataset.charStart) - Number(right.dataset.charStart))
  if (!regions.length) return null
  const first = regions[0]
  const last = regions[regions.length - 1]
  const startOffset = first.contains(range.startContainer)
    ? textLengthToBoundary(first, range.startContainer, range.startOffset)
    : 0
  const endOffset = last.contains(range.endContainer)
    ? textLengthToBoundary(last, range.endContainer, range.endOffset)
    : last.textContent.length
  return {
    start: Number(first.dataset.charStart) + startOffset,
    end: Number(last.dataset.charStart) + Math.max(endOffset, 1),
    sourceRefId: first.dataset.sourceRefId || last.dataset.sourceRefId || '',
    pageNumber: Number(first.dataset.pageNumber || activePage.value),
  }
}

function markdownSelectionBounds(range) {
  const root = coursePreviewRef.value?.getSelectionRoot?.()
  if (!root || !root.contains(range.startContainer) || !root.contains(range.endContainer)) return null
  const leaves = Array.from(root.querySelectorAll('[data-source-start][data-source-end]')).filter((element) => (
    !element.querySelector('[data-source-start][data-source-end]')
  )).filter((element) => {
    try { return range.intersectsNode(element) } catch { return false }
  })
  if (!leaves.length) return null
  const first = leaves[0]
  const last = leaves[leaves.length - 1]
  const startWithin = first.contains(range.startContainer) ? textLengthToBoundary(first, range.startContainer, range.startOffset) : 0
  const endWithin = last.contains(range.endContainer) ? textLengthToBoundary(last, range.endContainer, range.endOffset) : last.textContent.length
  return {
    start: Number(first.dataset.sourceStart) + startWithin,
    end: Number(last.dataset.sourceStart) + Math.max(endWithin, 1),
    sourceRefId: '',
    pageNumber: null,
  }
}

function textSelectionBounds(range) {
  if (isCoursePreviewDocument.value && !hasPages.value) return markdownSelectionBounds(range)
  const root = hasPages.value ? pageFrameRef.value : contentRef.value
  if (!root) return null
  if (!root.contains(range.startContainer) || !root.contains(range.endContainer)) return null
  if (hasPages.value) return pageSelectionBounds(range)
  const prefix = document.createRange()
  prefix.selectNodeContents(root)
  prefix.setEnd(range.startContainer, range.startOffset)
  const displayStart = prefix.toString().length
  const displayEnd = displayStart + range.toString().length
  const trimmed = trimSourceSelection(
    sourceOffsetForDisplay(displayStart),
    sourceOffsetForDisplay(displayEnd),
  )
  return { ...trimmed, sourceRefId: '', pageNumber: null }
}

async function handleTextSelection() {
  if (busyAction.value) return
  const browserSelection = window.getSelection()
  if (!browserSelection || browserSelection.rangeCount < 1 || browserSelection.isCollapsed) return
  const range = browserSelection.getRangeAt(0)
  const displayQuote = range.toString()
  if (!displayQuote.trim()) return
  const bounds = textSelectionBounds(range)
  if (!bounds) return
  const { start, end, quote } = trimSourceSelection(bounds.start, bounds.end)
  if (!quote.trim() || end <= start) return
  const ref = bounds.sourceRefId
    ? sourceRefs.value.find(item => String(item.id) === String(bounds.sourceRefId))
    : sourceRefForText(start, end)
  const chapter = chapters.value.find(item => Number(item.char_start) <= start && Number(item.char_end) >= end)
  const rect = range.getBoundingClientRect()
  setToolbarPosition(rect.left, rect.bottom + 8)
  toolbarVisible.value = true
  selectionError.value = ''
  busyAction.value = 'selection'
  try {
    selection.value = await createDocumentSelection({
      source_document_id: sourceDocumentId.value,
      document_version: readerDoc.value.document_version,
      selection_type: 'text',
      source_ref_id: ref?.id || null,
      section_id: chapter?.id || activeChapter.value?.id || null,
      page_number: bounds.pageNumber || null,
      char_start: start,
      char_end: end,
      quote,
      idempotency_key: operationKey(`text-${start}-${end}`),
    })
    charOffset.value = start
    activeSectionId.value = chapter?.id || activeSectionId.value
    questionDraft.value = ''
    noteDraft.value = displayQuote.trim()
    generationScope.value = 'selection'
    resetOperationKey('ask')
    resetOperationKey('note')
    resetOperationKey('selectionGenerate')
    schedulePositionSave()
  } catch (error) {
    selectionError.value = apiMessage(error, '选中文字未能保存，请重新选择。')
    selection.value = null
  } finally {
    busyAction.value = ''
  }
}

function normalizedPointer(event) {
  const bounds = event.currentTarget.getBoundingClientRect()
  return {
    x: Math.min(1, Math.max(0, (event.clientX - bounds.left) / bounds.width)),
    y: Math.min(1, Math.max(0, (event.clientY - bounds.top) / bounds.height)),
  }
}

function beginImageSelection(event) {
  if (!pageAssetUrl.value || busyAction.value) return
  const point = normalizedPointer(event)
  imageDrag.active = true
  imageDrag.pointerId = event.pointerId
  imageDrag.startX = point.x
  imageDrag.startY = point.y
  imageDrag.rect = { x: point.x, y: point.y, width: 0, height: 0 }
  event.currentTarget.setPointerCapture?.(event.pointerId)
}

function moveImageSelection(event) {
  if (!imageDrag.active || event.pointerId !== imageDrag.pointerId) return
  const point = normalizedPointer(event)
  imageDrag.rect = {
    x: Math.min(imageDrag.startX, point.x),
    y: Math.min(imageDrag.startY, point.y),
    width: Math.abs(point.x - imageDrag.startX),
    height: Math.abs(point.y - imageDrag.startY),
  }
}

async function finishImageSelection(event) {
  if (!imageDrag.active || event.pointerId !== imageDrag.pointerId) return
  moveImageSelection(event)
  const rect = { ...imageDrag.rect }
  imageDrag.active = false
  imageDrag.pointerId = null
  if (rect.width < 0.01 || rect.height < 0.01) {
    imageDrag.rect = null
    return
  }
  const page = activePageMeta.value
  const ref = sourceRefs.value.find(item => Number(item.page_number) === Number(activePage.value)) || activeSourceRef.value
  const frame = event.currentTarget.getBoundingClientRect()
  setToolbarPosition(frame.left + (rect.x + rect.width) * frame.width - 330, frame.top + (rect.y + rect.height) * frame.height + 8)
  toolbarVisible.value = true
  selectionError.value = ''
  busyAction.value = 'selection'
  try {
    selection.value = await createDocumentSelection({
      source_document_id: sourceDocumentId.value,
      document_version: readerDoc.value.document_version,
      selection_type: 'image',
      source_ref_id: ref?.id || null,
      section_id: ref?.chapter_id || activeChapter.value?.id || null,
      page_number: Number(activePage.value),
      page_width: Number(page.width),
      page_height: Number(page.height),
      normalized_rect: rect,
      idempotency_key: operationKey(`image-${activePage.value}-${Date.now()}`),
    })
    imageDrag.rect = null
    questionDraft.value = selection.value.question_draft || ''
    noteDraft.value = selection.value.ocr_text || ''
    generationScope.value = 'selection'
    resetOperationKey('ask')
    resetOperationKey('note')
    resetOperationKey('selectionGenerate')
    schedulePositionSave()
  } catch (error) {
    selectionError.value = apiMessage(error, '图片区域未能保存，请重新框选。')
    toolbarVisible.value = false
    imageDrag.rect = null
  } finally {
    busyAction.value = ''
  }
}

function cancelImageSelection() {
  imageDrag.active = false
  imageDrag.pointerId = null
  imageDrag.rect = null
}

function clearToolbar() {
  toolbarVisible.value = false
  selectionError.value = ''
  window.getSelection()?.removeAllRanges()
}

async function retryTextSelection() {
  selectionError.value = ''
  await nextTick()
  await handleTextSelection()
}

async function focusQuestion() {
  if (!canUseSelection.value) return
  activeSideTab.value = 'ask'
  await nextTick()
  questionInput.value?.focus()
}

async function submitQuestion() {
  if (!canUseSelection.value || !questionDraft.value.trim()) return
  busyAction.value = 'ask'
  answerError.value = ''
  try {
    selection.value = await askDocumentSelection(selection.value.id, {
      question: questionDraft.value.trim(),
      idempotency_key: operationKey('ask'),
    })
    toolbarVisible.value = false
  } catch (error) {
    answerError.value = apiMessage(error, '问题暂时无法回答，问题和选区均已保留。')
  } finally {
    busyAction.value = ''
  }
}

async function openNoteComposer() {
  if (!canUseSelection.value) return
  activeSideTab.value = 'actions'
  if (!noteDraft.value) noteDraft.value = selection.value.quote || selection.value.ocr_text || ''
  await nextTick()
  noteInput.value?.focus()
}

async function saveNote() {
  if (!canUseSelection.value || !noteDraft.value.trim()) return
  busyAction.value = 'note'
  noteError.value = ''
  try {
    noteResult.value = await saveDocumentSelectionNote(selection.value.id, {
      content: noteDraft.value.trim(),
      idempotency_key: operationKey('note'),
    })
    selection.value = noteResult.value.selection
    toolbarVisible.value = false
  } catch (error) {
    noteError.value = apiMessage(error, '笔记暂时没有保存，正文和来源仍保留在这里。')
  } finally {
    busyAction.value = ''
  }
}

function openSavedNote() {
  if (!noteResult.value?.note_id) return
  router.push({ name: 'Notes', query: { note_id: noteResult.value.note_id } })
}

async function generateResource(scope = generationScope.value) {
  if (scope === 'selection' && !canUseSelection.value) return
  busyAction.value = 'generate'
  generationError.value = ''
  generationScope.value = scope
  try {
    const payload = {
      resource_type: resourceType.value,
      idempotency_key: operationKey(scope === 'selection' ? 'selectionGenerate' : 'documentGenerate'),
    }
    generationResult.value = scope === 'selection'
      ? await generateDocumentSelectionResource(selection.value.id, payload)
      : await generateDocumentResource(sourceDocumentId.value, payload)
    if (generationResult.value.selection_id && selection.value) {
      selection.value = { ...selection.value, generation_task_id: generationResult.value.job?.job_id }
    }
    toolbarVisible.value = false
    activeSideTab.value = 'actions'
  } catch (error) {
    generationError.value = apiMessage(error, '生成任务没有创建，当前文档和选区仍可继续使用。')
  } finally {
    busyAction.value = ''
  }
}

async function retryOcr() {
  if (!canUseSelection.value || selection.value.selection_type !== 'image') return
  busyAction.value = 'ocr'
  selectionError.value = ''
  try {
    selection.value = await retryDocumentSelectionOcr(selection.value.id)
    noteDraft.value = selection.value.ocr_text || noteDraft.value
  } catch (error) {
    selectionError.value = apiMessage(error, 'OCR 仍未识别到文字，图片区域已保留。')
  } finally {
    busyAction.value = ''
  }
}

async function locateSelection() {
  if (!selection.value) return
  if (selection.value.selection_type === 'image' && selection.value.page_number) {
    await selectPage(selection.value.page_number)
    return
  }
  if (Number.isFinite(Number(selection.value.char_start))) {
    charOffset.value = Number(selection.value.char_start)
    await scrollToOffset(charOffset.value)
  }
}

function exportFilename(headers) {
  const disposition = String(headers?.['content-disposition'] || '')
  const encoded = disposition.match(/filename\*=UTF-8''([^;]+)/i)?.[1]
  if (encoded) {
    try { return decodeURIComponent(encoded) } catch {}
  }
  const plain = disposition.match(/filename="?([^";]+)"?/i)?.[1]
  return plain || `${String(readerDoc.value?.filename || readerDoc.value?.title || '知识文件')}`
}

async function exportKnowledgeDocument() {
  if (!readerDoc.value?.source_document_id || exportBusy.value) return
  exportBusy.value = true
  exportError.value = ''
  exportNotice.value = ''
  try {
    const result = await getDocumentReaderExport(readerDoc.value.source_document_id)
    const url = URL.createObjectURL(result.blob)
    const link = document.createElement('a')
    link.href = url
    link.download = exportFilename(result.headers)
    link.click()
    setTimeout(() => URL.revokeObjectURL(url), 0)
    const revision = result.headers?.['x-document-revision'] || readerDoc.value.document_version || '当前修订'
    const sourceHash = result.headers?.['x-source-sha256'] || readerDoc.value.source?.source_sha256 || '未标注'
    exportNotice.value = `知识文件已导出 · 修订 ${revision} · 源哈希 ${sourceHash}`
  } catch (error) {
    exportError.value = apiMessage(error, '知识文件暂时无法导出，原文和阅读位置仍可继续使用。')
  } finally {
    exportBusy.value = false
  }
}

function openResourceCenter() {
  router.push({ path: '/workspace/resources', query: { course_id: readerDoc.value?.course?.id || undefined } })
}

function backToKnowledge() {
  const returnTo = String(route.query.return_to || '')
  if (returnTo.startsWith('/') && !returnTo.startsWith('//')) {
    router.push(returnTo)
    return
  }
  const courseId = readerDoc.value?.course?.id || String(route.query.course_id || '')
  router.push(courseId ? `/knowledge/courses/${encodeURIComponent(courseId)}` : '/knowledge')
}

watch(searchQuery, () => {
  searchIndex.value = 0
  if (searchMatches.value.length) {
    charOffset.value = sourceOffsetForDisplay(searchMatches.value[0])
    nextTick(() => searchMarkRef.value?.scrollIntoView({ block: 'center' }))
  }
})
watch(zoom, schedulePositionSave)
watch(questionDraft, () => resetOperationKey('ask'))
watch(noteDraft, () => resetOperationKey('note'))
watch(resourceType, () => {
  resetOperationKey('selectionGenerate')
  resetOperationKey('documentGenerate')
})

onMounted(() => {
  document.addEventListener('fullscreenchange', syncPptxFullscreen)
  loadReader()
})
onBeforeUnmount(() => {
  clearTimeout(positionTimer)
  slideAssetRequest += 1
  slideAssetsLoading.value = false
  if (initialized) savePosition()
  revokePageAsset()
  revokeSlideAssets()
  revokeMediaAsset()
  revokeOriginalPdf()
  document.removeEventListener('fullscreenchange', syncPptxFullscreen)
})
</script>

<template>
  <section class="reader-page" aria-label="课程文档阅读器">
    <header class="reader-header">
      <button type="button" class="icon-button" title="返回知识库" aria-label="返回知识库" @click="backToKnowledge">
        <ArrowLeft :size="19" />
      </button>
      <div class="reader-title">
        <span>{{ readerDoc?.course?.title || '课程知识库' }} · {{ currentLocationLabel }}</span>
        <h1>{{ readerDoc?.title || '正在打开文档' }}</h1>
      </div>
      <div class="reader-header__actions">
        <span v-if="restoredAt" class="save-state"><CheckCircle2 :size="15" />已恢复上次位置</span>
        <button type="button" class="secondary-button" title="导出解析文本（知识文件）" :disabled="!readerDoc?.source_document_id || exportBusy" @click="exportKnowledgeDocument">
          <LoaderCircle v-if="exportBusy" :size="17" class="spin" />
          <Download v-else :size="17" />{{ exportBusy ? '正在导出知识文件' : '导出知识文件' }}
        </button>
      </div>
    </header>

    <div v-if="exportNotice || exportError" class="reader-export-status" role="status">
      <p v-if="exportNotice" class="inline-notice">{{ exportNotice }}</p>
      <div v-if="exportError" class="inline-error reader-export-error">
        <span>{{ exportError }}</span>
        <button type="button" class="text-button" :disabled="exportBusy" @click="exportKnowledgeDocument">重试导出</button>
      </div>
    </div>

    <div class="reader-layout">
      <aside class="reader-outline" aria-label="课程与章节目录">
        <div class="outline-course">
          <BookOpen :size="18" />
          <div>
            <strong>{{ readerDoc?.course?.title || '课程目录' }}</strong>
            <span v-if="readerDoc?.course?.version">版本 {{ readerDoc.course.version }}</span>
          </div>
        </div>
        <div class="outline-document">
          <FileSearch :size="16" />
          <span>{{ readerDoc?.filename || '当前文档' }}</span>
        </div>
        <nav class="chapter-list" aria-label="文档章节">
          <p>章节</p>
          <button
            v-for="chapter in chapters"
            :key="chapter.id"
            type="button"
            :class="{ active: activeChapter?.id === chapter.id }"
            @click="jumpToChapter(chapter)"
          >
            <span>{{ chapter.position }}</span>
            <strong>{{ chapter.title }}</strong>
          </button>
          <TaskState
            v-if="!loading && !chapters.length"
            state="info"
            title="暂无章节目录"
            message="仍可阅读和搜索完整原文。"
          />
        </nav>
      </aside>

      <main class="reader-main">
        <div class="reader-toolbar" aria-label="阅读工具栏">
          <div class="reader-search">
            <SearchField
              v-model="searchQuery"
              class="reader-search__field"
              :bordered="false"
              aria-label="在当前文档中搜索"
              placeholder="在当前文档中搜索"
            />
            <span v-if="searchQuery">{{ searchMatches.length ? `${searchIndex + 1}/${searchMatches.length}` : '无结果' }}</span>
            <button type="button" title="上一个搜索结果" aria-label="上一个搜索结果" :disabled="!searchMatches.length" @click="moveSearch(-1)">
              <ChevronLeft :size="17" />
            </button>
            <button type="button" title="下一个搜索结果" aria-label="下一个搜索结果" :disabled="!searchMatches.length" @click="moveSearch(1)">
              <ChevronRight :size="17" />
            </button>
          </div>
          <div v-if="hasPages" class="page-control">
            <button type="button" title="上一页" aria-label="上一页" @click="pageStep(-1)"><ChevronLeft :size="17" /></button>
            <span>第 {{ activePage }} / {{ readerDoc.pages.length }} 页</span>
            <button type="button" title="下一页" aria-label="下一页" @click="pageStep(1)"><ChevronRight :size="17" /></button>
          </div>
          <div class="zoom-control" aria-label="缩放">
            <button type="button" title="缩小" aria-label="缩小" @click="adjustZoom(-0.1)"><Minus :size="17" /></button>
            <span>{{ Math.round(zoom * 100) }}%</span>
            <button type="button" title="放大" aria-label="放大" @click="adjustZoom(0.1)"><Plus :size="17" /></button>
          </div>
        </div>

        <p v-if="positionNotice" class="inline-notice">{{ positionNotice }}</p>
        <p v-if="selectionError" class="inline-error">{{ selectionError }}</p>

        <div ref="readingViewport" class="reading-viewport" @scroll.passive="handleReaderScroll">
          <TaskState
            v-if="loading"
            state="loading"
            title="正在打开原文"
            message="目录、正文和上次阅读位置会一起恢复。"
          />
          <TaskState
            v-else-if="loadError"
            state="error"
            title="文档暂时无法打开"
            :message="loadError"
            action-label="重新加载"
            @action="loadReader"
          />
          <template v-else>
            <section v-if="isPptxDocument" class="pptx-reader" data-testid="pptx-reader">
              <header class="pptx-reader__header">
                <div>
                  <strong>幻灯片阅读</strong>
                  <span>{{ hasSlidePreviews ? '按原始版式查看演示文稿；文字阅读版用于搜索和提问。' : '文字阅读版仍可用于搜索、选中和提问。' }}</span>
                </div>
                <span class="pptx-reader__count">{{ hasSlides ? `${activeSlideNumber} / ${slides.length}` : '暂无页面' }}</span>
              </header>
              <TaskState
                v-if="!hasSlides"
                state="info"
                title="暂时没有可显示的幻灯片"
                message="下面仍保留已解析的正文；原始文件无法读取时不会伪造幻灯片画面。"
              />
              <p v-if="slideAssetsLoading" class="pptx-preview-notice">正在准备原版幻灯片...</p>
              <p v-else-if="slideAssetsError || readerDoc?.pptx_preview?.message" class="pptx-preview-notice">
                {{ slideAssetsError || readerDoc.pptx_preview.message }}
              </p>
              <div v-if="hasSlides" class="pptx-reader__layout">
                <nav class="pptx-thumbnails" aria-label="幻灯片导航">
                  <button
                    v-for="slide in slides"
                    :key="slide.slide_num"
                    type="button"
                    class="pptx-thumbnail"
                    :class="{ active: Number(slide.slide_num) === Number(activeSlideNumber) }"
                    :aria-label="`第 ${slide.slide_num} 张幻灯片`"
                    :aria-current="Number(slide.slide_num) === Number(activeSlideNumber) ? 'page' : undefined"
                    @click="selectSlide(slide.slide_num)"
                  >
                    <span class="pptx-thumbnail__number">{{ slide.slide_num }}</span>
                    <span class="pptx-thumbnail__body">
                      <img
                        v-if="slideAssetUrls[Number(slide.slide_num)]"
                        :src="slideAssetUrls[Number(slide.slide_num)]"
                        :style="pptxThumbnailStyle(slide)"
                        alt=""
                      />
                      <img
                        v-else-if="slide.images?.[0] && slideImageUrl(slide.images[0])"
                        :src="slideImageUrl(slide.images[0])"
                        alt=""
                      />
                      <span v-else-if="slide.text" class="pptx-thumbnail__text-only">文字页</span>
                      <span v-else class="pptx-thumbnail__empty">空白页</span>
                      <span v-if="slide.text" class="pptx-thumbnail__label">{{ slide.text.split('\n').filter(Boolean)[0] }}</span>
                    </span>
                  </button>
                </nav>
                <section ref="pptxStageRef" class="pptx-reader__stage" aria-label="当前幻灯片">
                  <div class="pptx-reader__controls">
                    <button type="button" class="icon-button" title="上一张幻灯片" aria-label="上一张幻灯片" :disabled="Number(activeSlideNumber) <= Number(slides[0]?.slide_num)" @click="slideStep(-1)">
                      <ChevronLeft :size="18" />
                    </button>
                    <span>第 {{ activeSlideNumber }} / {{ slides.length }} 张</span>
                    <button type="button" class="icon-button" title="下一张幻灯片" aria-label="下一张幻灯片" :disabled="Number(activeSlideNumber) >= Number(slides[slides.length - 1]?.slide_num)" @click="slideStep(1)">
                      <ChevronRight :size="18" />
                    </button>
                    <button type="button" class="icon-button" :disabled="!canUsePptxFullscreen" :title="canUsePptxFullscreen ? (pptxFullscreen ? '退出全屏' : '全屏查看') : '当前浏览器不支持全屏'" :aria-label="pptxFullscreen ? '退出全屏' : '全屏查看幻灯片'" @click="togglePptxFullscreen">
                      <Minimize2 v-if="pptxFullscreen" :size="18" />
                      <Maximize2 v-else :size="18" />
                    </button>
                  </div>
                  <article class="pptx-slide-canvas" data-testid="pptx-slide-canvas">
                    <img
                      v-if="activeSlideAssetUrl"
                      class="pptx-slide-canvas__page"
                      :src="activeSlideAssetUrl"
                      :style="pptxSlideStyle"
                      :alt="`${readerDoc.title} 第 ${activeSlide.slide_num} 张幻灯片`"
                    />
                    <div v-else-if="activeSlide?.images?.length" class="pptx-slide-canvas__images">
                      <img
                        v-for="(image, index) in activeSlide.images"
                        :key="`${activeSlide.slide_num}-image-${index}`"
                        :src="slideImageUrl(image)"
                        :alt="`${readerDoc.title} 第 ${activeSlide.slide_num} 张幻灯片图片 ${index + 1}`"
                      />
                    </div>
                    <div v-if="!activeSlideAssetUrl && activeSlide?.text" class="pptx-slide-canvas__text">
                      <p v-for="(line, index) in activeSlide.text.split('\n').filter(Boolean)" :key="`${activeSlide.slide_num}-line-${index}`">{{ line }}</p>
                    </div>
                    <div v-if="!activeSlideAssetUrl && !activeSlide?.text && !activeSlide?.images?.length" class="pptx-slide-canvas__empty">
                      <BookOpen :size="28" />
                      <strong>这张幻灯片为空白页</strong>
                      <span>没有可提取的文字或图片，仍可通过页码继续浏览。</span>
                    </div>
                  </article>
                  <details v-if="activeSlide?.notes" class="pptx-slide-notes">
                    <summary>演讲者备注</summary>
                    <p>{{ activeSlide.notes }}</p>
                  </details>
                </section>
              </div>
              <section v-if="readerDoc?.content" class="pptx-parsed-fallback">
                <div class="pptx-parsed-fallback__heading">
                  <strong>解析正文</strong>
                  <span>可搜索、可选择的文字版，不替代上方幻灯片布局。</span>
                </div>
                <CourseDocumentPreview
                  :text="readerDoc.content"
                  :document-id="readerDoc.source_document_id"
                  :document-version="readerDoc.document_version"
                  :search-query="searchQuery"
                  :search-index="searchIndex"
                  @mouseup="handleTextSelection"
                />
              </section>
            </section>

            <section v-else-if="isPdfDocument" class="original-pdf-preview" data-testid="original-pdf-preview">
              <header class="original-pdf-preview__header">
                <div>
                  <strong>原始 PDF</strong>
                  <span>保留上传资料的原有格式；解析文本和知识点仅用于检索与定位。</span>
                </div>
                <button type="button" class="text-button" :disabled="originalPdfLoading" @click="loadOriginalPdf">
                  <RefreshCw :size="15" :class="{ spin: originalPdfLoading }" />重试预览
                </button>
              </header>
              <TaskState
                v-if="originalPdfLoading"
                state="loading"
                title="正在加载原始 PDF"
                message="不会影响下方解析内容、页码和来源定位。"
              />
              <TaskState
              v-else-if="originalPdfError"
                state="error"
                title="原始 PDF 暂时无法预览"
                :message="originalPdfError"
                action-label="重试预览"
                @action="loadOriginalPdf"
              />
              <section v-if="originalPdfUrl && pageAssetUrl" class="pdf-native-page" data-testid="pdf-native-page">
                <div class="pdf-native-page__heading">
                  <strong>原始页面预览</strong>
                  <span>当前页的原始 PDF 渲染图；保持版式并支持页码切换。</span>
                </div>
                <img :src="pageAssetUrl" :alt="`${readerDoc.title} 原始 PDF 第 ${activePage} 页`" />
              </section>
              <iframe
                v-if="originalPdfUrl"
                class="original-pdf-preview__frame"
                :src="originalPdfUrl"
                :title="`${readerDoc.title} 原始 PDF`"
              />
              <section v-if="readerDoc?.content" class="pdf-content-fallback" data-testid="pdf-content-fallback">
                <div class="pdf-content-fallback__heading">
                  <strong>解析正文</strong>
                  <span>原始 PDF 保留在上方；这里提供可搜索、可选择的课程阅读版。</span>
                </div>
                <CourseDocumentPreview
                  :text="readerDoc.content"
                  :document-id="readerDoc.source_document_id"
                  :document-version="readerDoc.document_version"
                  :search-query="searchQuery"
                  :search-index="searchIndex"
                  @mouseup="handleTextSelection"
                />
              </section>
            </section>

            <section v-if="hasPages" class="parsed-page-preview">
              <div class="parsed-page-preview__heading"><strong>解析页图与来源定位</strong><span>页码、文字层和选区仍按解析索引工作</span></div>
              <TaskState
                v-if="pageAssetLoading"
                state="loading"
                title="正在加载解析页图"
                message="已加载的来源和选区不会丢失。"
              />
              <TaskState
                v-else-if="pageAssetError"
                state="error"
                title="这一页暂时无法显示"
                :message="pageAssetError"
                action-label="重试本页"
                @action="loadPageAsset"
              />
              <div
                v-else
                ref="pageFrameRef"
                class="page-frame"
                :style="{ width: `${zoom * 100}%`, aspectRatio: `${activePageMeta?.width || 4} / ${activePageMeta?.height || 3}` }"
                @mouseup="handleTextSelection"
              >
                <img :src="pageAssetUrl" :alt="`${readerDoc.title} 第 ${activePage} 页解析页图`" draggable="false" />
                <div class="page-text-layer" aria-label="可选择的页面文字">
                  <span
                    v-for="region in activePageTextRegions"
                    :key="region.region_id"
                    class="page-text-region"
                    data-selection-region
                    :data-char-start="region.char_start"
                    :data-char-end="region.char_end"
                    :data-page-number="region.page_number"
                    :data-source-ref-id="region.source_ref_id"
                    :style="{ left: `${region.bbox.x * 100}%`, top: `${region.bbox.y * 100}%`, width: `${region.bbox.width * 100}%`, height: `${region.bbox.height * 100}%` }"
                  >{{ region.text }}</span>
                </div>
                <div
                  class="image-selection-layer"
                  role="application"
                  aria-label="在页图上拖动以框选图片区域"
                  @pointerdown="beginImageSelection"
                  @pointermove="moveImageSelection"
                  @pointerup="finishImageSelection"
                  @pointercancel="cancelImageSelection"
                >
                  <span v-if="visibleImageRect" class="image-selection-rect" :style="imageRectStyle" />
                </div>
              </div>
            </section>
          <div v-else-if="isVideo" class="media-reader">
            <TaskState
              v-if="mediaAssetLoading"
              state="loading"
              title="正在加载课程视频"
              message="视频说明与来源已经保留。"
            />
            <TaskState
              v-else-if="mediaAssetError"
              state="error"
              title="视频暂时无法播放"
              :message="mediaAssetError"
              action-label="重试视频"
              @action="loadMediaAsset"
            />
            <video v-else :src="mediaAssetUrl" controls preload="metadata" :aria-label="readerDoc.title" />
            <div class="media-transcript__heading">
              <strong>视频说明与可检索文字</strong>
              <span>{{ readerDoc.media.transcript_status === 'team_authored_visual_description' ? '团队画面说明' : '视频文字' }}</span>
            </div>
            <pre ref="contentRef" class="document-content media-transcript" :style="documentContentStyle" @mouseup="handleTextSelection"><span>{{ searchParts.before }}</span><mark v-if="searchParts.hit" ref="searchMarkRef">{{ searchParts.hit }}</mark><span>{{ searchParts.after }}</span></pre>
          </div>
          <CourseDocumentPreview
            v-else-if="isCoursePreviewDocument && readerDoc?.content"
            ref="coursePreviewRef"
            :text="readerDoc.content"
            :document-id="readerDoc.source_document_id"
            :document-version="readerDoc.document_version"
            :search-query="searchQuery"
            :search-index="searchIndex"
            @mouseup="handleTextSelection"
          />
          <pre v-else-if="readerDoc?.content" ref="contentRef" class="document-content" :style="documentContentStyle" @mouseup="handleTextSelection"><span>{{ searchParts.before }}</span><mark v-if="searchParts.hit" ref="searchMarkRef">{{ searchParts.hit }}</mark><span>{{ searchParts.after }}</span></pre>
          <TaskState
            v-else
            state="info"
            title="当前文档没有可读正文"
            message="返回知识库选择其他已完成解析的资料。"
            action-label="返回知识库"
            @action="backToKnowledge"
          />
          </template>
        </div>
      </main>

      <aside class="reader-context" aria-label="来源、问答与笔记">
        <div class="context-tabs" role="tablist" aria-label="阅读上下文">
          <button
            v-for="tab in sideTabs"
            :key="tab.id"
            type="button"
            role="tab"
            :aria-selected="activeSideTab === tab.id"
            :class="{ active: activeSideTab === tab.id }"
            @click="activeSideTab = tab.id"
          >{{ tab.label }}</button>
        </div>

        <div v-if="activeSideTab === 'source'" class="context-panel" role="tabpanel">
          <div class="context-heading"><ShieldCheck :size="18" /><strong>当前来源</strong></div>
          <dl class="source-list">
            <div><dt>课程</dt><dd>{{ readerDoc?.course?.title || '未知课程' }}</dd></div>
            <div><dt>位置</dt><dd>{{ activeSourceRef?.location_label || currentLocationLabel }}</dd></div>
            <div><dt>格式</dt><dd>{{ (readerDoc?.file_type || 'text').toUpperCase() }}</dd></div>
            <div><dt>许可</dt><dd>{{ readerDoc?.source?.license || '未单独声明' }}</dd></div>
            <div><dt>解析状态</dt><dd>{{ readerDoc?.source?.processing_status === 'ready' ? '已完成解析' : '状态待确认' }}</dd></div>
          </dl>
          <button v-if="selection" type="button" class="text-button" @click="locateSelection"><Focus :size="16" />定位当前选区</button>
          <details class="source-details">
            <summary>查看来源详情</summary>
            <p>{{ readerDoc?.source?.url || readerDoc?.source?.path || '团队预置课程来源' }}</p>
            <p>解析器 {{ readerDoc?.source?.parser_version || '未标注' }}</p>
            <code>{{ readerDoc?.document_version || '' }}</code>
          </details>
        </div>

        <div v-else-if="activeSideTab === 'ask'" class="context-panel" role="tabpanel">
          <div class="context-heading"><MessageSquareText :size="18" /><strong>问选中内容</strong></div>
          <p class="selection-summary">{{ selectionSummary }}</p>
          <textarea ref="questionInput" v-model="questionDraft" rows="4" :disabled="!canUseSelection" placeholder="针对选中的原文或图片提问" aria-label="针对选区的问题" />
          <button type="button" class="primary-button" :disabled="!canUseSelection || !questionDraft.trim() || Boolean(busyAction)" @click="submitQuestion">
            <LoaderCircle v-if="busyAction === 'ask'" :size="17" class="spin" />
            <MessageSquareText v-else :size="17" />
            {{ busyAction === 'ask' ? '正在生成讲解' : '提交问题' }}
          </button>
          <p v-if="answerError" class="inline-error">{{ answerError }}</p>
          <div v-if="selection?.answer_text" class="answer-result">
            <strong>{{ selection.answer_status === 'ready' ? '基于选区的回答' : '暂时无法回答' }}</strong>
            <IncrementalMarkdownRenderer v-if="selection.answer_status === 'ready'" :text="selection.answer_text" />
            <p v-else>{{ selection.answer_text }}</p>
            <SourceCitation
              v-if="selection.answer_source || selection.source"
              :source="selection.answer_source || selection.source"
              :return-to="route.fullPath"
              compact
            />
            <AgentTimeline v-if="selection.agent_audit" :audit="selection.agent_audit" compact />
            <button type="button" class="text-button" @click="locateSelection"><Focus :size="16" />回到原文</button>
          </div>
          <div v-if="selection?.selection_type === 'image' && selection?.ocr_status === 'failed'" class="recovery-block">
            <strong>图片区域已保留</strong>
            <p>本次没有识别到可验证文字。可只重试 OCR，也可调整框选范围。</p>
            <button type="button" class="secondary-button" :disabled="Boolean(busyAction)" @click="retryOcr">
              <RotateCcw :size="16" />重试 OCR
            </button>
          </div>
        </div>

        <div v-else class="context-panel" role="tabpanel">
          <div class="context-heading"><NotebookPen :size="18" /><strong>来源笔记</strong></div>
          <p class="selection-summary">{{ selectionSummary }}</p>
          <textarea ref="noteInput" v-model="noteDraft" rows="4" :disabled="!canUseSelection" placeholder="记录当前选区，来源会自动保存" aria-label="选区笔记" />
          <button type="button" class="secondary-button full-button" :disabled="!canUseSelection || !noteDraft.trim() || Boolean(busyAction)" @click="saveNote">
            <LoaderCircle v-if="busyAction === 'note'" :size="17" class="spin" />
            <NotebookPen v-else :size="17" />保存到笔记本
          </button>
          <p v-if="noteError" class="inline-error">{{ noteError }}</p>
          <div v-if="noteResult" class="saved-note-result">
            <p class="success-line"><CheckCircle2 :size="16" />已保存，文档位置与选区引用已归档。</p>
            <button type="button" class="text-button" @click="openSavedNote">进入笔记本<ChevronRight :size="16" /></button>
          </div>

          <div class="context-divider" />
          <div class="context-heading"><WandSparkles :size="18" /><strong>生成学习资源</strong></div>
          <div class="scope-switch" aria-label="生成范围">
            <button type="button" :class="{ active: generationScope === 'document' }" @click="generationScope = 'document'">当前文件</button>
            <button type="button" :disabled="!canUseSelection" :class="{ active: generationScope === 'selection' }" @click="generationScope = 'selection'">当前选区</button>
          </div>
          <label class="field-label" for="reader-resource-type">资源类型</label>
          <select id="reader-resource-type" v-model="resourceType">
            <option v-for="option in resourceOptions" :key="option.value" :value="option.value">{{ option.label }}</option>
          </select>
          <button type="button" class="primary-button" :disabled="Boolean(busyAction) || (generationScope === 'selection' && !canUseSelection)" @click="generateResource()">
            <LoaderCircle v-if="busyAction === 'generate'" :size="17" class="spin" />
            <WandSparkles v-else :size="17" />
            {{ busyAction === 'generate' ? '正在创建任务' : '生成并归档' }}
          </button>
          <p v-if="generationError" class="inline-error">{{ generationError }}</p>
          <div v-if="generationResult?.job" class="generation-result">
            <strong>任务已进入资源中心</strong>
            <span>{{ generationResult.job.items?.[0]?.title || '学习资源' }}</span>
            <button type="button" class="text-button" @click="openResourceCenter">前往资源中心<ChevronRight :size="16" /></button>
          </div>
        </div>
      </aside>
    </div>

    <SelectionToolbar
      v-if="toolbarVisible && (canUseSelection || selectionError)"
      v-model:resource-type="resourceType"
      :style="toolbarStyle"
      :busy-action="busyAction"
      :disabled="!canUseSelection"
      :error-message="selectionError"
      :selection-type="selection?.selection_type || 'text'"
      @ask="focusQuestion"
      @note="openNoteComposer"
      @generate="generateResource('selection')"
      @clear="clearToolbar"
      @retry="retryTextSelection"
    />
  </section>
</template>

<style scoped>
.reader-page {
  display: grid;
  width: 100%;
  height: calc(100vh - var(--topbar-height));
  min-height: 640px;
  overflow: hidden;
  color: var(--color-text);
  background: var(--color-page);
  grid-template-rows: 72px minmax(0, 1fr);
}

.reader-header {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: 14px;
  padding: 0 20px;
  border-bottom: 1px solid var(--color-border);
  background: var(--color-surface);
}

.reader-title {
  display: grid;
  min-width: 0;
  flex: 1;
  gap: 2px;
}

.reader-title span {
  overflow: hidden;
  color: var(--color-text-muted);
  font-size: 14px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.reader-title h1 {
  margin: 0;
  overflow: hidden;
  font-size: 18px;
  font-weight: 650;
  letter-spacing: 0;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.reader-header__actions,
.reader-toolbar,
.page-control,
.zoom-control,
.reader-search,
.save-state,
.context-heading,
.success-line,
.text-button,
.primary-button,
.secondary-button,
.icon-button {
  display: flex;
  align-items: center;
}

.reader-header__actions { gap: 10px; }
.save-state { gap: 6px; color: var(--color-text-muted); font-size: 14px; white-space: nowrap; }
.reader-export-status { display: grid; gap: 4px; padding: 8px 20px 0; background: var(--color-surface); }
.reader-export-status p { margin: 0; }
.reader-export-error { display: flex; align-items: center; justify-content: space-between; gap: 12px; }

.reader-layout {
  display: grid;
  min-width: 0;
  min-height: 0;
  grid-template-columns: minmax(190px, 20fr) minmax(540px, 58fr) minmax(230px, 22fr);
}

.reader-outline,
.reader-context,
.reader-main {
  min-width: 0;
  min-height: 0;
  background: var(--color-surface);
}

.reader-outline {
  overflow-y: auto;
  border-right: 1px solid var(--color-border);
}

.outline-course {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 20px 16px 16px;
  border-bottom: 1px solid var(--color-border);
}

.outline-course div { display: grid; min-width: 0; gap: 3px; }
.outline-course strong { font-size: 15px; line-height: 1.45; }
.outline-course span { color: var(--color-text-muted); font-size: 14px; }

.outline-document {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 14px 16px;
  color: var(--color-text-secondary);
  border-bottom: 1px solid var(--color-border);
  font-size: 14px;
}

.outline-document span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.chapter-list { display: grid; gap: 2px; padding: 14px 10px 24px; }
.chapter-list > p { margin: 0 6px 8px; color: var(--color-text-muted); font-size: 14px; font-weight: 600; }
.chapter-list > button {
  display: grid;
  min-height: 42px;
  align-items: center;
  gap: 9px;
  padding: 7px 9px;
  color: var(--color-text-secondary);
  border: 1px solid transparent;
  border-radius: 6px;
  background: transparent;
  grid-template-columns: 24px minmax(0, 1fr);
  text-align: left;
  cursor: pointer;
}
.chapter-list > button span { color: var(--color-text-muted); font-size: 14px; text-align: center; }
.chapter-list > button strong { overflow: hidden; font-size: 14px; font-weight: 500; line-height: 1.4; text-overflow: ellipsis; white-space: nowrap; }
.chapter-list > button:hover { color: var(--color-text); background: var(--color-surface-subtle); }
.chapter-list > button.active { color: var(--color-text); border-color: var(--color-border-strong); background: var(--color-accent-soft); }
.chapter-list > button.active strong { font-weight: 650; }

.reader-main {
  display: grid;
  overflow: hidden;
  background: var(--color-page);
  grid-template-rows: 52px auto auto minmax(0, 1fr);
}

.reader-toolbar {
  min-width: 0;
  justify-content: space-between;
  gap: 10px;
  padding: 7px 12px;
  border-bottom: 1px solid var(--color-border);
  background: var(--color-surface);
}

.reader-search {
  min-width: 210px;
  height: 36px;
  flex: 1;
  gap: 7px;
  padding-left: 10px;
  color: var(--color-text-muted);
  border: 1px solid var(--color-border);
  border-radius: 6px;
  background: var(--color-surface-subtle);
}
.reader-search input { min-width: 60px; height: 100%; flex: 1; border: 0; outline: 0; background: transparent; font: inherit; font-size: 14px; }
.reader-search > span { font-size: 14px; white-space: nowrap; }
.reader-search button,
.page-control button,
.zoom-control button {
  display: inline-flex;
  width: 32px;
  height: 32px;
  align-items: center;
  justify-content: center;
  padding: 0;
  color: var(--color-text-secondary);
  border: 0;
  border-radius: 6px;
  background: transparent;
  cursor: pointer;
}
.reader-search button:hover:not(:disabled), .page-control button:hover, .zoom-control button:hover { color: var(--color-text); background: var(--color-surface-muted); }
.reader-search button:disabled { opacity: 0.4; cursor: not-allowed; }
.page-control, .zoom-control { min-height: 36px; gap: 3px; color: var(--color-text-secondary); font-size: 14px; white-space: nowrap; }
.zoom-control { border-left: 1px solid var(--color-border); padding-left: 8px; }
.zoom-control span { min-width: 48px; text-align: center; }

.inline-notice,
.inline-error {
  margin: 0;
  padding: 8px 14px;
  border-bottom: 1px solid var(--color-border);
  font-size: 14px;
  line-height: 1.5;
}
.inline-notice { color: var(--color-text-secondary); background: var(--color-surface-subtle); }
.inline-error { color: var(--color-danger); background: var(--color-danger-soft); }

.reading-viewport {
  min-width: 0;
  min-height: 0;
  overflow: auto;
  padding: 24px clamp(20px, 4vw, 52px) 80px;
  scroll-behavior: smooth;
}

.original-pdf-preview,
.parsed-page-preview {
  display: grid;
  gap: 12px;
  width: min(100%, 1080px);
  margin: 0 auto 24px;
  padding: 16px;
  border: 1px solid var(--color-border);
  border-radius: 8px;
  background: var(--color-surface);
  box-shadow: 0 8px 24px rgb(6 20 27 / 6%);
}

.pptx-reader {
  display: grid;
  gap: 14px;
  width: min(100%, 1180px);
  margin: 0 auto 24px;
  padding: 16px;
  border: 1px solid var(--color-border);
  border-radius: 8px;
  background: var(--color-surface);
  box-shadow: 0 8px 24px rgb(6 20 27 / 6%);
}
.pptx-reader__header,
.pptx-reader__controls,
.pptx-reader__header > div {
  display: flex;
  align-items: center;
  gap: 10px;
}
.pptx-reader__header { justify-content: space-between; }
.pptx-reader__header > div { align-items: flex-start; flex-direction: column; gap: 3px; }
.pptx-reader__header strong { font-size: 15px; }
.pptx-reader__header span { color: var(--color-text-muted); font-size: 14px; line-height: 1.5; }
.pptx-reader__count { white-space: nowrap; }
.pptx-preview-notice { margin: 0; padding: 10px 12px; color: var(--color-text-secondary); border: 1px solid var(--color-border); border-radius: 5px; background: var(--color-surface-subtle); font-size: 14px; line-height: 1.55; }
.pptx-reader__layout { display: grid; min-width: 0; gap: 16px; grid-template-columns: 160px minmax(0, 1fr); }
.pptx-thumbnails { display: grid; align-content: start; gap: 8px; max-height: 620px; overflow: auto; padding-right: 3px; }
.pptx-thumbnail {
  display: grid;
  min-width: 0;
  grid-template-columns: 22px minmax(0, 1fr);
  gap: 6px;
  padding: 5px;
  color: var(--color-text-secondary);
  border: 1px solid var(--color-border);
  border-radius: 6px;
  background: var(--color-surface-subtle);
  text-align: left;
  cursor: pointer;
}
.pptx-thumbnail:hover { border-color: var(--color-border-strong); }
.pptx-thumbnail.active { border-color: var(--color-accent); background: var(--color-accent-soft); }
.pptx-thumbnail__number { padding-top: 4px; color: var(--color-text-muted); font-size: 14px; text-align: center; }
.pptx-thumbnail__body { display: grid; min-width: 0; gap: 4px; }
.pptx-thumbnail__body img { display: block; width: 100%; aspect-ratio: 16 / 9; object-fit: contain; border: 1px solid var(--color-border); background: #fff; }
.pptx-thumbnail__empty,
.pptx-thumbnail__text-only { display: grid; height: 54px; place-items: center; border: 1px dashed var(--color-border-strong); background: #fff; font-size: 14px; }
.pptx-thumbnail__empty { color: var(--color-text-muted); }
.pptx-thumbnail__text-only { color: var(--color-text-secondary); }
.pptx-thumbnail__label { overflow: hidden; color: var(--color-text-secondary); font-size: 14px; line-height: 1.35; text-overflow: ellipsis; white-space: nowrap; }
.pptx-reader__stage { display: grid; min-width: 0; gap: 10px; }
.pptx-reader__controls { justify-content: center; min-height: 34px; color: var(--color-text-secondary); font-size: 14px; }
.pptx-reader__controls .icon-button:disabled { opacity: .4; cursor: not-allowed; }
.pptx-slide-canvas {
  display: grid;
  align-content: start;
  justify-items: center;
  min-height: 390px;
  gap: 18px;
  overflow: auto;
  padding: clamp(14px, 2vw, 24px);
  border: 1px solid var(--color-border-strong);
  border-radius: 6px;
  background: #f7f9f9;
}
.pptx-slide-canvas__page { display: block; max-width: none; height: auto; border: 1px solid var(--color-border-strong); background: #fff; box-shadow: 0 10px 24px rgb(6 20 27 / 12%); }
.pptx-slide-canvas__images { display: grid; gap: 12px; justify-items: center; }
.pptx-slide-canvas__images img { display: block; max-width: 100%; max-height: 440px; object-fit: contain; background: #fff; box-shadow: 0 8px 20px rgb(6 20 27 / 9%); }
.pptx-slide-canvas__text { display: grid; gap: 6px; padding: 18px 20px; border: 1px solid var(--color-border); border-radius: 5px; background: #fff; }
.pptx-slide-canvas__text p { margin: 0; color: var(--color-text); font-size: 16px; line-height: 1.65; white-space: pre-wrap; }
.pptx-slide-canvas__empty { display: grid; min-height: 280px; align-content: center; justify-items: center; gap: 8px; color: var(--color-text-muted); text-align: center; }
.pptx-slide-canvas__empty strong { color: var(--color-text-secondary); font-size: 16px; }
.pptx-slide-canvas__empty span { font-size: 14px; }
.pptx-slide-notes { padding: 10px 12px; color: var(--color-text-secondary); border: 1px solid var(--color-border); border-radius: 5px; background: var(--color-surface-subtle); font-size: 14px; }
.pptx-slide-notes p { margin: 8px 0 0; line-height: 1.6; white-space: pre-wrap; }
.pptx-reader__stage:fullscreen { height: 100%; padding: 18px; background: #edf1f2; grid-template-rows: auto minmax(0, 1fr) auto; }
.pptx-reader__stage:fullscreen .pptx-slide-canvas { min-height: 0; }
.pptx-reader__stage:fullscreen .pptx-slide-canvas__page {
  width: auto !important;
  max-width: 100%;
  max-height: calc(100vh - 124px);
  object-fit: contain;
}
.pptx-parsed-fallback { display: grid; gap: 10px; }
.pptx-parsed-fallback__heading { display: grid; gap: 3px; padding: 4px 2px 0; }
.pptx-parsed-fallback__heading strong { font-size: 15px; }
.pptx-parsed-fallback__heading span { color: var(--color-text-muted); font-size: 14px; line-height: 1.5; }
.pptx-parsed-fallback .course-document-reader__toolbar { margin-bottom: 0; }
.pptx-parsed-fallback .course-document-preview { width: 100%; max-width: none; box-shadow: none; }

.original-pdf-preview__header,
.parsed-page-preview__heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 14px;
}

.original-pdf-preview__header > div,
.parsed-page-preview__heading {
  display: grid;
  gap: 4px;
}

.original-pdf-preview__header strong,
.parsed-page-preview__heading strong { font-size: 15px; }
.original-pdf-preview__header span,
.parsed-page-preview__heading span { color: var(--color-text-muted); font-size: 14px; line-height: 1.5; }

.original-pdf-preview__frame {
  width: 100%;
  min-height: 420px;
  max-height: 620px;
  border: 1px solid var(--color-border);
  border-radius: 5px;
  background: #f3f6f6;
}
.pdf-native-page { display: grid; gap: 8px; }
.pdf-native-page__heading { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; }
.pdf-native-page__heading strong { font-size: 15px; }
.pdf-native-page__heading span { color: var(--color-text-muted); font-size: 14px; line-height: 1.5; }
.pdf-native-page img { display: block; width: min(100%, 760px); max-height: 760px; margin: 0 auto; object-fit: contain; border: 1px solid var(--color-border-strong); background: #fff; box-shadow: 0 10px 24px rgb(6 20 27 / 8%); }

.pdf-content-fallback {
  display: grid;
  gap: 12px;
}

.pdf-content-fallback__heading {
  display: grid;
  gap: 4px;
  padding: 4px 2px 0;
}

.pdf-content-fallback__heading strong { font-size: 15px; }
.pdf-content-fallback__heading span { color: var(--color-text-muted); font-size: 14px; line-height: 1.5; }
.pdf-content-fallback .course-document-reader__toolbar { margin-bottom: 0; }
.pdf-content-fallback .course-document-preview { width: 100%; max-width: none; box-shadow: none; }

@media (max-width: 780px) {
  .pptx-reader__layout { grid-template-columns: 1fr; }
  .pptx-thumbnails { display: flex; max-height: none; overflow-x: auto; padding-bottom: 4px; }
  .pptx-thumbnail { min-width: 132px; }
  .pptx-slide-canvas { min-height: 300px; }
}

.parsed-page-preview .page-frame { width: 100% !important; }

.document-content {
  width: min(100%, 900px);
  min-height: 100%;
  margin: 0 auto;
  padding: 38px clamp(34px, 5vw, 68px) 80px;
  color: var(--color-text);
  border: 1px solid var(--color-border);
  border-radius: 6px;
  background: var(--color-surface);
  box-shadow: 0 10px 28px rgb(6 20 27 / 7%);
  font-family: var(--font-sans);
  font-size: 16px;
  line-height: 1.9;
  overflow-wrap: anywhere;
  white-space: pre-wrap;
  user-select: text;
}
.document-content mark { padding: 1px 2px; color: var(--color-text); background: #e2e7e8; }

.page-frame {
  position: relative;
  min-width: 520px;
  max-width: 1180px;
  margin: 0 auto;
  overflow: hidden;
  border: 1px solid var(--color-border-strong);
  border-radius: 4px;
  background: var(--color-surface);
  box-shadow: 0 12px 30px rgb(6 20 27 / 9%);
}
.page-frame img { display: block; width: 100%; height: 100%; object-fit: contain; pointer-events: none; user-select: none; }
.page-text-layer { position: absolute; z-index: 2; inset: 0; pointer-events: none; }
.page-text-region {
  position: absolute;
  display: block;
  overflow: hidden;
  color: transparent;
  white-space: pre-wrap;
  user-select: text;
  pointer-events: auto;
  cursor: text;
}
.page-text-region::selection { color: var(--color-text); background: rgb(17 33 45 / 20%); }
.image-selection-layer { position: absolute; z-index: 1; inset: 0; cursor: crosshair; touch-action: none; }
.image-selection-rect { position: absolute; border: 2px solid var(--color-accent); background: rgb(17 33 45 / 12%); pointer-events: none; }

.reader-context {
  overflow-y: auto;
  border-left: 1px solid var(--color-border);
}
.context-tabs {
  display: grid;
  position: sticky;
  z-index: 2;
  top: 0;
  padding: 8px;
  border-bottom: 1px solid var(--color-border);
  background: var(--color-surface);
  grid-template-columns: repeat(3, minmax(0, 1fr));
}
.context-tabs button {
  min-height: 36px;
  padding: 0 6px;
  color: var(--color-text-muted);
  border: 0;
  border-radius: 5px;
  background: transparent;
  font-size: 14px;
  cursor: pointer;
}
.context-tabs button:hover { color: var(--color-text); background: var(--color-surface-subtle); }
.context-tabs button.active { color: var(--color-text); background: var(--color-accent-soft); font-weight: 650; }

.context-panel { display: grid; gap: 14px; padding: 18px 16px 32px; }
.context-heading { gap: 8px; }
.context-heading strong { font-size: 15px; }
.source-list { display: grid; gap: 0; margin: 0; }
.source-list div { display: grid; gap: 6px; padding: 10px 0; border-bottom: 1px solid var(--color-border); grid-template-columns: 56px minmax(0, 1fr); }
.source-list dt { color: var(--color-text-muted); font-size: 14px; }
.source-list dd { margin: 0; color: var(--color-text-secondary); font-size: 14px; line-height: 1.5; overflow-wrap: anywhere; }
.source-details { padding-top: 4px; color: var(--color-text-secondary); font-size: 14px; }
.source-details summary { color: var(--color-text); cursor: pointer; }
.source-details p { margin: 10px 0 0; line-height: 1.55; overflow-wrap: anywhere; }
.source-details code { display: block; margin-top: 10px; overflow-wrap: anywhere; color: var(--color-text-muted); font-family: var(--font-mono); font-size: 14px; }

.selection-summary {
  display: -webkit-box;
  margin: 0;
  overflow: hidden;
  color: var(--color-text-secondary);
  font-size: 14px;
  line-height: 1.6;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 5;
}
.context-panel textarea,
.context-panel select {
  width: 100%;
  color: var(--color-text);
  border: 1px solid var(--color-border-strong);
  border-radius: 6px;
  background: var(--color-surface);
  font: inherit;
  font-size: 14px;
}
.context-panel textarea { min-height: 104px; resize: vertical; padding: 10px 11px; line-height: 1.6; }
.context-panel select { height: 40px; padding: 0 10px; }
.context-panel textarea:focus, .context-panel select:focus { border-color: var(--color-accent); outline: 2px solid rgb(17 33 45 / 14%); }
.context-panel textarea:disabled { background: var(--color-surface-subtle); cursor: not-allowed; }
.field-label { color: var(--color-text-secondary); font-size: 14px; font-weight: 600; }

.answer-result,
.generation-result,
.recovery-block {
  display: grid;
  min-width: 0;
  gap: 9px;
  padding: 12px 0 0;
  border-top: 1px solid var(--color-border);
}
.answer-result strong, .generation-result strong, .recovery-block strong { font-size: 14px; }
.answer-result p, .recovery-block p { margin: 0; color: var(--color-text-secondary); font-size: 14px; line-height: 1.65; white-space: pre-wrap; }
.answer-result .incremental-md-renderer { min-width: 0; overflow-wrap: anywhere; word-break: break-word; }
.answer-result .incremental-md-renderer :deep(.inc-paragraph),
.answer-result .incremental-md-renderer :deep(.inc-heading),
.answer-result .incremental-md-renderer :deep(.inc-list-content) { overflow-wrap: anywhere; word-break: break-word; }
.generation-result span { color: var(--color-text-secondary); font-size: 14px; line-height: 1.5; }
.context-divider { height: 1px; margin: 4px 0; background: var(--color-border); }
.success-line { gap: 7px; margin: 0; color: var(--color-success); font-size: 14px; line-height: 1.5; }

.scope-switch { display: grid; padding: 3px; border: 1px solid var(--color-border); border-radius: 6px; background: var(--color-surface-subtle); grid-template-columns: 1fr 1fr; }
.scope-switch button { min-height: 34px; color: var(--color-text-muted); border: 0; border-radius: 4px; background: transparent; font-size: 14px; cursor: pointer; }
.scope-switch button.active { color: var(--color-text); background: var(--color-surface); box-shadow: 0 1px 3px rgb(6 20 27 / 10%); font-weight: 650; }
.scope-switch button:disabled { opacity: 0.45; cursor: not-allowed; }

.primary-button,
.secondary-button,
.icon-button,
.text-button {
  justify-content: center;
  gap: 8px;
  min-height: 38px;
  border-radius: 6px;
  font-size: 14px;
  font-weight: 650;
  cursor: pointer;
}
.primary-button { width: 100%; padding: 0 14px; color: #ffffff; border: 1px solid var(--color-accent); background: var(--color-accent); }
.primary-button:hover:not(:disabled) { background: #1c303d; }
.secondary-button { padding: 0 12px; color: var(--color-text-secondary); border: 1px solid var(--color-border-strong); background: var(--color-surface); }
.secondary-button:hover:not(:disabled) { color: var(--color-text); background: var(--color-surface-subtle); }
.full-button { width: 100%; }
.icon-button { width: 38px; padding: 0; color: var(--color-text-secondary); border: 1px solid var(--color-border); background: var(--color-surface); }
.icon-button:hover { color: var(--color-text); background: var(--color-surface-subtle); }
.text-button { width: fit-content; min-height: 32px; justify-content: flex-start; padding: 0; color: var(--color-accent); border: 0; background: transparent; }
.text-button:hover { text-decoration: underline; }
.primary-button:disabled, .secondary-button:disabled { opacity: 0.48; cursor: not-allowed; }
.spin { animation: reader-spin 850ms linear infinite; }

.media-reader {
  display: grid;
  gap: 18px;
  width: min(100%, 920px);
  margin: 0 auto;
}

.media-reader video {
  display: block;
  width: 100%;
  aspect-ratio: 16 / 9;
  border: 1px solid var(--color-border);
  border-radius: 6px;
  background: #111111;
}

.media-transcript__heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding-top: 4px;
  color: var(--color-text-secondary);
  font-size: 14px;
}

.media-transcript__heading strong { color: var(--color-text); font-size: 16px; }
.media-transcript { min-height: 260px; }

button:focus-visible,
input:focus-visible,
textarea:focus-visible,
select:focus-visible,
summary:focus-visible {
  outline: 2px solid var(--color-accent);
  outline-offset: 2px;
}

@keyframes reader-spin { to { transform: rotate(360deg); } }
</style>
