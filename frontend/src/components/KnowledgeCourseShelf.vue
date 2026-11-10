<script setup>
import { learningText } from '../utils/learningCopy.js'
import { userMessage } from '../services/errorTranslator.js'
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useCourseContextStore } from '../stores/courseContext'
import {
  ArrowLeft,
  ArrowRight,
  BookOpen,
  Check,
  ChevronRight,
  CircleAlert,
  FileSearch,
  FileText,
  GitBranch,
  Library,
  LoaderCircle,
  Plus,
  Pin,
  RefreshCw,
  Search,
  Upload,
  X,
} from '@lucide/vue'
import {
  addKnowledgeCourseToShelf,
  createKnowledgeCourse,
  crossLanguageCourseSearch,
  getCanonicalCourseSource,
  getCanonicalCourseOutline,
  getKnowledgeDocument,
  listKnowledgeCourseShelf,
  uploadKnowledgeDocumentsBatch,
  retryCourseSourceReading,
} from '../api'
import SearchField from './ui/SearchField.vue'
import CourseStructureEditor from './CourseStructureEditor.vue'
import { renderCourseDocument, renderCourseMath } from '../utils/courseDocumentRenderer.js'
import { arrangeCourseMaterials, readMaterialBrowser, saveMaterialBrowser } from '../utils/courseMaterialBrowser.js'

const emit = defineEmits(['open-source', 'open-search-result'])
const route = useRoute()
const router = useRouter()
const courseContext = useCourseContextStore()

const catalog = ref(null)
const catalogStatus = ref('loading')
const catalogError = ref('')
const addingCourseId = ref('')
const actionMessage = ref('')
const outline = ref([])
const outlineStatus = ref('idle')
const outlineError = ref('')
const selectedChapterId = ref('')
const selectedResourceId = ref('')
const resourceTypeFilter = ref('all')
const materialQuery = ref('')
const materialSort = ref('course')
const pinnedMaterials = ref([])
const recentMaterials = ref([])
const restoredCourseId = ref('')
let outlineRequest = 0
const sourceRequests = new Set()
const sourceDetails = ref({})
const readingRetryId = ref('')
const readingRetryMessage = ref('')
const resourcePreview = computed(() => {
  const content = selectedResourceDetail.value?.content || ''
  const container = document.createElement('div')
  container.innerHTML = renderCourseDocument(content.slice(0, 12000)).html
  container.querySelectorAll('button').forEach(button => button.remove())
  const paragraphs = [...container.querySelectorAll('.lesson-block--explanation p, table tr')]
  const text = (paragraphs.length ? paragraphs.map(item => item.tagName === 'TR'
    ? [...item.cells].map(cell => cell.textContent.trim()).join(' · ')
    : item.textContent).join('\n\n') : container.textContent).replace(/[ \t]+/g, ' ').trim()
  return text.slice(0, 280) + (text.length > 280 ? '…' : '')
})
function searchExcerpt(content) {
  const container = document.createElement('div')
  container.innerHTML = renderCourseDocument(content || '').html
  container.querySelectorAll('button,.lesson-block__label').forEach(element => element.remove())
  renderCourseMath(container, window.katex)
  return container.innerHTML
}
const resourceDetailStatus = ref('idle')
const resourceDetailError = ref('')
const searchQuery = ref('')
const searchStatus = ref('idle')
const searchError = ref('')
const searchReport = ref(null)
const courseDialogOpen = ref(false)
const courseForm = ref({ title: '', subject: '', description: '' })
const courseCreateStatus = ref('idle')
const courseCreateError = ref('')
const uploadInput = ref(null)
const uploadStatus = ref('idle')
const uploadError = ref('')
const uploadMessage = ref('')
const uploadFailures = ref([])
const materialPreview = ref(null)
const materialPreviewStatus = ref('idle')
const materialPreviewError = ref('')
const structureEditorOpen = ref(false)

const shelfCourses = computed(() => catalog.value?.shelf || [])
const recommendations = computed(() => catalog.value?.recommendations || [])
const materialRecommendations = computed(() => catalog.value?.material_recommendations || [])
const currentRole = computed(() => localStorage.getItem('edumatrix_role') || 'student')
const currentUsername = computed(() => (
  localStorage.getItem('edumatrix_username')
  || localStorage.getItem('edumatrix_student_id')
  || 'default'
))
const allCourses = computed(() => [...shelfCourses.value, ...recommendations.value])
const viewKind = computed(() => {
  if (route.name === 'KnowledgeDiscover') return 'discover'
  if (route.name === 'KnowledgeGraph') return 'graph'
  if (route.name === 'KnowledgeCourse' || route.name === 'KnowledgeDocument') return 'course'
  return 'home'
})
const activeCourseId = computed(() => String(route.params.courseId || route.query.course_id || ''))
const activeCourse = computed(() => allCourses.value.find(course => course.id === activeCourseId.value) || null)
const rootChapters = computed(() => outline.value.filter(chapter => !chapter.parent_id))
const selectedChapter = computed(() => (
  rootChapters.value.find(chapter => chapter.id === selectedChapterId.value) || rootChapters.value[0] || null
))
const selectedMaterials = computed(() => (
  selectedChapter.value
    ? [selectedChapter.value, ...outline.value.filter(chapter => chapter.parent_id === selectedChapter.value.id)]
    : []
))
const resourceItems = computed(() => {
  const groups = new Map()
  rootChapters.value.forEach(chapter => {
    const id = chapter.source_document_id || chapter.id
    if (!groups.has(id)) {
      groups.set(id, {
        id,
        source_document_id: chapter.source_document_id || '',
        title: sourceDetails.value[id]?.title || chapter.source_title || chapter.title,
        fileType: chapter.source_file_format || '',
        processingStatus: chapter.source_processing_status || '',
        chapters: [],
        knowledgePointCount: 0,
      })
    }
    const item = groups.get(id)
    item.chapters.push(chapter)
    item.knowledgePointCount += chapter.knowledge_points?.length || 0
  })
  return [...groups.values()].map(item => ({
    ...item,
    fileType: sourceDetails.value[item.id]?.file_type || sourceDetails.value[item.id]?.file_format || item.fileType || 'resource',
    processingStatus: sourceDetails.value[item.id]?.source_processing_status || sourceDetails.value[item.id]?.processing_status || item.processingStatus || 'ready',
  }))
})
const resourceTypeOptions = computed(() => {
  const types = new Set(resourceItems.value.map(item => resourceType(item)))
  return ['all', ...[...types].filter(type => type !== 'all')]
})
const filteredResources = computed(() => arrangeCourseMaterials(
  resourceTypeFilter.value === 'all'
    ? resourceItems.value
    : resourceItems.value.filter(item => resourceType(item) === resourceTypeFilter.value),
  { query: materialQuery.value, sort: materialSort.value, pinned: pinnedMaterials.value, recent: recentMaterials.value },
))
const selectedResource = computed(() => (
  filteredResources.value.find(item => item.id === selectedResourceId.value)
  || filteredResources.value[0]
  || null
))
const selectedResourceDetail = computed(() => (
  selectedResource.value ? sourceDetails.value[selectedResource.value.id] || null : null
))
const imageReadingIncomplete = computed(() => ['partial', 'unavailable'].includes(
  selectedResourceDetail.value?.source_parser_metadata?.visual_reading?.status,
))

async function retryImageReading() {
  const sourceId = selectedResource.value?.source_document_id
  const courseId = activeCourseId.value
  if (!sourceId || readingRetryId.value) return
  readingRetryId.value = sourceId
  readingRetryMessage.value = ''
  try {
    const result = await retryCourseSourceReading(sourceId)
    if (activeCourseId.value !== courseId) return
    if (result.visual_retry === 'unchanged') {
      readingRetryMessage.value = '图片仍未读完整，可先阅读原文件，稍后再试。'
      return
    }
    if (result.source_processing_status !== 'ready') {
      readingRetryMessage.value = '章节暂未整理完成，请稍后再试。'
      return
    }
    await loadCatalog()
    await loadOutline(courseId)
    selectedResourceId.value = result.source_document_id
    await loadSourceDetail(result.source_document_id)
  } catch (error) {
    if (activeCourseId.value === courseId) readingRetryMessage.value = apiErrorMessage(error, '图片暂未读完，请稍后再试。')
  } finally {
    readingRetryId.value = ''
  }
}

watch(() => selectedResource.value?.id, () => { readingRetryMessage.value = '' })
const continuingCourse = computed(() => shelfCourses.value.find(course => course.id === courseContext.contextRef.courseId) || null)
const firstShelfCourse = computed(() => continuingCourse.value || shelfCourses.value[0] || null)

function apiErrorMessage(error, fallback) {
  const detail = error?.response?.data?.detail
  if (typeof detail === 'string') return detail
  if (detail?.message) return detail.message
  return error?.message || fallback
}

function courseMark(course) {
  const text = `${course?.subject || ''} ${course?.title || ''}`.toLowerCase()
  if (text.includes('edge') || text.includes('边缘')) return 'EDGE'
  if (text.includes('rag') || text.includes('检索')) return 'RAG'
  return Array.from(String(course?.title || '课程').trim()).slice(0, 2).join('') || '课程'
}

function sourceLabel(course) {
  if (course?.source_health === 'ready' && course?.index_status === 'ready') return ''
  if (course?.source_health === 'missing') return '来源信息待补充'
  return '部分资料仍在整理'
}

function resourceType(item) {
  const format = String(item?.fileType || '').toLowerCase()
  if (['mp4', 'avi', 'mov', 'mkv', 'webm', 'flv', 'video'].includes(format)) return '视频'
  if (['ppt', 'pptx', 'presentation'].includes(format)) return '演示'
  if (['py', 'ipynb', 'python_code', 'notebook'].includes(format)) return '代码 / Notebook'
  if (['md', 'txt', 'json', 'markdown', 'text'].includes(format)) return '文本'
  return '文档'
}

function resourceIcon(item) {
  const type = resourceType(item)
  if (type === '演示') return BookOpen
  if (type === '视频') return FileSearch
  if (type === '代码 / Notebook') return GitBranch
  return FileText
}

function resourceTypeLabel(type) {
  return type === 'all' ? '全部资源' : type
}

async function loadCatalog() {
  catalogStatus.value = 'loading'
  catalogError.value = ''
  try {
    catalog.value = await listKnowledgeCourseShelf()
    catalogStatus.value = (
      shelfCourses.value.length
      || recommendations.value.length
      || materialRecommendations.value.length
    ) ? 'ready' : 'empty'
  } catch (error) {
    catalogStatus.value = 'failed'
    catalogError.value = apiErrorMessage(error, '课程书架加载失败')
  }
}

async function addCourse(course) {
  if (!course?.id || addingCourseId.value) return
  addingCourseId.value = course.id
  actionMessage.value = ''
  try {
    const result = await addKnowledgeCourseToShelf(course.id)
    await loadCatalog()
    actionMessage.value = result.created ? `《${course.title}》已加入书架` : `《${course.title}》已在书架中`
  } catch (error) {
    actionMessage.value = apiErrorMessage(error, '加入书架失败，请重试')
  } finally {
    addingCourseId.value = ''
  }
}

function materialPreviewScope(material) {
  // Operators may inspect a recommendation owned by public/system or a
  // selected student. Students must always resolve through their own scope;
  // the repository then adds public/system documents without widening access.
  if (['teacher', 'admin'].includes(currentRole.value)) {
    return material?.owner_id || currentUsername.value
  }
  return currentUsername.value
}

async function openMaterial(material) {
  if (!material) return
  if (material.open_mode === 'reader' && material.source_document_id) {
    emit('open-source', {
      courseId: material.course_id || '',
      sourceDocumentId: material.source_document_id,
      chapterId: material.chapter_id || '',
      title: material.title,
    })
    return
  }
  materialPreview.value = material
  materialPreviewStatus.value = 'loading'
  materialPreviewError.value = ''
  try {
    const detail = await getKnowledgeDocument(material.id, materialPreviewScope(material))
    materialPreview.value = { ...material, detail }
    materialPreviewStatus.value = 'ready'
  } catch (error) {
    materialPreviewStatus.value = 'failed'
    materialPreviewError.value = apiErrorMessage(error, '教材预览加载失败，请重试')
  }
}

function closeMaterialPreview() {
  materialPreview.value = null
  materialPreviewStatus.value = 'idle'
  materialPreviewError.value = ''
}

function openCourseCreator() {
  courseForm.value = { title: '', subject: '', description: '' }
  courseCreateError.value = ''
  courseCreateStatus.value = 'idle'
  courseDialogOpen.value = true
}

async function submitCourse() {
  const title = courseForm.value.title.trim()
  if (title.length < 2 || courseCreateStatus.value === 'loading') return
  courseCreateStatus.value = 'loading'
  courseCreateError.value = ''
  try {
    const result = await createKnowledgeCourse({
      title,
      subject: courseForm.value.subject.trim(),
      description: courseForm.value.description.trim(),
    })
    await loadCatalog()
    courseDialogOpen.value = false
    if (result?.course) openCourse(result.course)
  } catch (error) {
    courseCreateStatus.value = 'failed'
    courseCreateError.value = apiErrorMessage(error, '课程创建失败，请重试')
  }
}

function chooseCourseFiles() {
  uploadError.value = ''
  uploadMessage.value = ''
  uploadInput.value?.click()
}

async function uploadCourseFiles(event) {
  const files = [...(event.target.files || [])]
  event.target.value = ''
  if (!files.length || !activeCourse.value?.can_manage || uploadStatus.value === 'loading') return
  uploadStatus.value = 'loading'
  uploadError.value = ''
  uploadMessage.value = ''
  uploadFailures.value = []
  try {
    const result = await uploadKnowledgeDocumentsBatch(files, 'default', activeCourse.value.id)
    uploadFailures.value = (result.results || [])
      .filter(item => item.status === 'failed')
      .map(item => ({
        filename: item.filename,
        message: userMessage({
          detail: item.error || item.document?.knowledge_extraction?.error,
          status: item.http_status,
        }, '这份资料还没有整理完成，请重新选择文件上传。'),
      }))
    uploadMessage.value = `${result.succeeded || 0} 份资料已进入课程${uploadFailures.value.length ? `，${uploadFailures.value.length} 份未完成` : ''}`
    await loadCatalog()
    await loadOutline(activeCourse.value.id)
    uploadStatus.value = uploadFailures.value.length ? 'partial' : 'ready'
  } catch (error) {
    uploadStatus.value = 'failed'
    uploadError.value = apiErrorMessage(error, '资料上传失败，请重试')
  }
}

async function loadOutline(courseId) {
  const request = ++outlineRequest
  if (!courseId) {
    outline.value = []
    outlineStatus.value = 'idle'
    return
  }
  outlineStatus.value = 'loading'
  outlineError.value = ''
  try {
    const result = await getCanonicalCourseOutline(courseId)
    if (request !== outlineRequest) return
    const saved = readMaterialBrowser(localStorage, currentUsername.value, courseId)
    materialQuery.value = typeof saved.query === 'string' ? saved.query : ''
    materialSort.value = ['course', 'title', 'recent'].includes(saved.sort) ? saved.sort : 'course'
    pinnedMaterials.value = Array.isArray(saved.pinned) ? saved.pinned : []
    recentMaterials.value = Array.isArray(saved.recent) ? saved.recent : []
    outline.value = Array.isArray(result) ? result : []
    selectedChapterId.value = rootChapters.value.some(item => item.id === selectedChapterId.value)
      ? selectedChapterId.value
      : rootChapters.value[0]?.id || ''
    resourceTypeFilter.value = resourceTypeOptions.value.includes(saved.type) ? saved.type : 'all'
    selectedResourceId.value = saved.selected || ''
    restoredCourseId.value = courseId
    outlineStatus.value = outline.value.length ? 'ready' : 'empty'
  } catch (error) {
    if (request !== outlineRequest) return
    outline.value = []
    outlineStatus.value = 'failed'
    outlineError.value = apiErrorMessage(error, '课程章节加载失败')
  }
}

async function loadSourceDetail(sourceDocumentId) {
  if (!sourceDocumentId || sourceDetails.value[sourceDocumentId]) return
  const courseId = activeCourseId.value
  const requestKey = `${courseId}:${sourceDocumentId}`
  if (sourceRequests.has(requestKey)) return
  sourceRequests.add(requestKey)
  resourceDetailStatus.value = 'loading'
  resourceDetailError.value = ''
  try {
    const detail = await getCanonicalCourseSource(sourceDocumentId)
    if (courseId !== activeCourseId.value) return
    sourceDetails.value = { ...sourceDetails.value, [sourceDocumentId]: detail }
    if (selectedResource.value?.source_document_id === sourceDocumentId) resourceDetailStatus.value = 'ready'
  } catch (error) {
    if (courseId === activeCourseId.value && selectedResource.value?.source_document_id === sourceDocumentId) {
      resourceDetailStatus.value = 'failed'
      resourceDetailError.value = '这份资料的预览暂时没有打开，请重试，或直接阅读全文。'
    }
  } finally {
    sourceRequests.delete(requestKey)
  }
}

function selectResource(resource) {
  if (!resource) return
  selectedResourceId.value = resource.id
  recentMaterials.value = [resource.id, ...recentMaterials.value.filter(id => id !== resource.id)].slice(0, 40)
  void loadSourceDetail(resource.source_document_id)
}

function toggleMaterialPin() {
  const id = selectedResource.value?.id
  if (!id) return
  pinnedMaterials.value = pinnedMaterials.value.includes(id)
    ? pinnedMaterials.value.filter(item => item !== id)
    : [...pinnedMaterials.value, id]
}

function openResource(resource = selectedResource.value) {
  const chapter = resource?.chapters?.[0]
  if (!resource || !chapter) return
  emit('open-source', {
    courseId: activeCourse.value?.id,
    sourceDocumentId: resource.source_document_id,
    title: resource.title,
  })
}

function openCourse(course) {
  if (!course?.id) return
  router.push(`/knowledge/courses/${encodeURIComponent(course.id)}`)
}

function openChapterSource(chapter) {
  if (!activeCourse.value || !chapter?.source_document_id) return
  emit('open-source', {
    courseId: activeCourse.value.id,
    sourceDocumentId: chapter.source_document_id,
    chapterId: chapter.id,
    title: chapter.title,
  })
}

function openSelectedSource() {
  openChapterSource(selectedChapter.value)
}

function openGraph(course) {
  if (!course?.id) return
  router.push(`/knowledge/graph/${encodeURIComponent(course.id)}`)
}

async function runCourseSearch() {
  const query = searchQuery.value.trim()
  if (!query || !activeCourse.value) return
  searchStatus.value = 'loading'
  searchError.value = ''
  searchReport.value = null
  try {
    searchReport.value = await crossLanguageCourseSearch(activeCourse.value.id, query, 6)
    searchStatus.value = searchReport.value?.items?.length ? 'ready' : 'empty'
  } catch (error) {
    searchStatus.value = 'failed'
    searchError.value = apiErrorMessage(error, '课程正文检索失败')
  }
}

function openSearchResult(item) {
  if (!item?.locatable || !activeCourse.value) return
  emit('open-search-result', { courseId: activeCourse.value.id, item })
}

watch(activeCourseId, courseId => {
  restoredCourseId.value = ''
  outline.value = []
  searchQuery.value = ''
  searchReport.value = null
  searchStatus.value = 'idle'
  sourceDetails.value = {}
  resourceDetailStatus.value = 'idle'
  loadOutline(courseId)
}, { immediate: true })

watch(filteredResources, () => {
  if (!filteredResources.value.some(item => item.id === selectedResourceId.value)) {
    selectedResourceId.value = filteredResources.value[0]?.id || ''
  }
  if (selectedResource.value?.source_document_id) void loadSourceDetail(selectedResource.value.source_document_id)
}, { immediate: true })

watch([selectedResourceId, resourceTypeFilter, materialQuery, materialSort, pinnedMaterials, recentMaterials], () => {
  if (restoredCourseId.value !== activeCourseId.value || outlineStatus.value !== 'ready') return
  saveMaterialBrowser(localStorage, currentUsername.value, activeCourseId.value, {
    selected: selectedResourceId.value, type: resourceTypeFilter.value,
    query: materialQuery.value, sort: materialSort.value,
    pinned: pinnedMaterials.value, recent: recentMaterials.value,
  })
})

onMounted(loadCatalog)
</script>

<template>
  <main class="course-shelf" data-testid="knowledge-course-shelf">
    <section v-if="catalogStatus === 'loading'" class="state-panel" data-testid="course-shelf-loading" aria-live="polite">
      <LoaderCircle :size="22" class="state-spinner" />
      <div>
        <strong>正在整理课程书架</strong>
      </div>
    </section>

    <section v-else-if="catalogStatus === 'failed'" class="state-panel state-panel--error" data-testid="course-shelf-error" role="alert">
      <CircleAlert :size="22" />
      <div>
        <strong>课程书架暂时无法打开</strong>
        <p>{{ userMessage(catalogError) }}</p>
        <button type="button" class="secondary-button" @click="loadCatalog">
          <RefreshCw :size="16" />重新加载
        </button>
      </div>
    </section>

    <section v-else-if="catalogStatus === 'empty'" class="state-panel" data-testid="course-shelf-empty">
      <Library :size="24" />
      <div>
        <strong>还没有可用课程</strong>
        <p>新建一门课程，整理你的学习资料。</p>
        <button type="button" class="primary-button empty-state-create" data-testid="create-personal-course-empty" @click="openCourseCreator">
          <Plus :size="17" />新建课程
        </button>
      </div>
    </section>

    <template v-else-if="viewKind === 'home'">
      <header class="page-intro">
        <div>
          <h1>课程知识库</h1>
        </div>
        <div class="page-intro__actions">
          <button type="button" class="secondary-button" data-testid="create-personal-course" @click="openCourseCreator">
            <Plus :size="17" />新建课程
          </button>
          <button v-if="firstShelfCourse" type="button" class="primary-button" @click="openCourse(firstShelfCourse)">
            {{ continuingCourse ? '继续学习' : '开始学习' }}<ArrowRight :size="17" />
          </button>
        </div>
      </header>

      <section class="shelf-section" aria-labelledby="my-shelf-title">
        <div class="section-heading">
          <div>
            <h2 id="my-shelf-title">我的书架<span class="shelf-count">{{ shelfCourses.length }}</span></h2>
          </div>
        </div>

        <div class="course-grid" data-testid="my-course-shelf">
          <article v-for="course in shelfCourses" :key="course.id" class="course-card" :data-testid="`shelf-course-${course.id}`">
            <div class="course-spine" aria-hidden="true">
              <span>{{ courseMark(course) }}</span>
            </div>
            <div class="course-card__body">
              <div class="course-card__heading">
                <div>
                  <h3>{{ course.title }}</h3>
                  <p v-if="course.subject">{{ course.subject }}</p>
                </div>
                <span v-if="sourceLabel(course)" class="status-badge" data-tone="attention">
                  <CircleAlert :size="14" />{{ sourceLabel(course) }}
                </span>
              </div>
              <p class="course-description">{{ learningText(course.description) }}</p>
              <p class="course-facts" aria-label="课程规模">
                <span>{{ course.chapter_count }} 章</span>
                <span>{{ course.knowledge_point_count }} 个知识点</span>
                <span>{{ course.document_count }} 份资料</span>
              </p>
              <div class="course-card__footer">
                <span>{{ course.language === 'en' ? '英文资料' : course.language === 'zh-CN' || !course.language ? '中文资料' : course.language }}</span>
                <button type="button" class="secondary-button" :data-testid="`open-course-${course.id}`" @click="openCourse(course)">
                  打开课程<ChevronRight :size="16" />
                </button>
              </div>
            </div>
          </article>
        </div>
      </section>

      <section v-if="recommendations.length" class="shelf-section" aria-labelledby="recommendation-title">
        <div class="section-heading">
          <div>
            <h2 id="recommendation-title">智能推荐</h2>
          </div>
        </div>

        <div v-if="recommendations.length" class="recommendation-list" data-testid="course-recommendations">
          <article v-for="course in recommendations" :key="course.id" class="recommendation-item">
            <div class="recommendation-cover" aria-hidden="true">{{ courseMark(course) }}</div>
            <div class="recommendation-copy">
              <h3>{{ course.title }}</h3>
              <p>{{ learningText(course.recommendation_reason) }}</p>
              <span>{{ course.chapter_count }} 章 · {{ course.document_count }} 份文档<span v-if="sourceLabel(course)"> · {{ sourceLabel(course) }}</span></span>
            </div>
            <button type="button" class="secondary-button" :data-testid="`add-course-${course.id}`" :disabled="addingCourseId === course.id" @click="addCourse(course)">
              <LoaderCircle v-if="addingCourseId === course.id" :size="16" class="state-spinner" />
              <Plus v-else :size="16" />
              {{ addingCourseId === course.id ? '正在加入' : '加入书架' }}
            </button>
          </article>
        </div>
      </section>
      <p v-if="actionMessage" class="action-message" aria-live="polite"><Check :size="16" />{{ actionMessage }}</p>

      <section v-if="materialRecommendations.length" class="shelf-section material-recommendation-section" aria-labelledby="material-recommendation-title">
        <div class="section-heading">
          <div>
            <h2 id="material-recommendation-title">教材补充推荐</h2>
            <p>辅助阅读，尚未加入课程。</p>
          </div>
          <span>{{ materialRecommendations.length }} 份资料</span>
        </div>

        <div v-if="materialRecommendations.length" class="material-recommendation-list" data-testid="material-recommendations">
          <article v-for="material in materialRecommendations" :key="material.id" class="material-recommendation-item">
            <div class="material-recommendation-mark" aria-hidden="true">{{ String(material.file_type || 'doc').toUpperCase() }}</div>
            <div class="material-recommendation-copy">
              <div class="material-recommendation-heading">
                <h3>{{ material.title }}</h3>
                <span class="material-quality-badge">{{ material.quality_label }}</span>
              </div>
              <p>{{ learningText(material.recommendation_reason) }}</p>
              <span>{{ material.owner_scope === 'personal' ? '你的资料' : '公共资料' }} · {{ material.traceability === 'canonical_source' ? '可查看原文' : '辅助材料 / 待审核' }}</span>
            </div>
            <button type="button" class="secondary-button" :data-testid="`open-material-${material.id}`" @click="openMaterial(material)">
              <FileText :size="16" />{{ material.open_mode === 'reader' ? '打开教材' : '查看预览' }}
            </button>
          </article>
        </div>
      </section>

      <div v-if="materialPreview" class="material-preview-backdrop" role="presentation" @click.self="closeMaterialPreview">
        <section class="material-preview-dialog" role="dialog" aria-modal="true" aria-labelledby="material-preview-title">
          <header>
            <div>
              <span>辅助材料预览 · 不属于主课程证据</span>
              <h2 id="material-preview-title">{{ materialPreview.title }}</h2>
            </div>
            <button type="button" class="dialog-close" aria-label="关闭教材预览" @click="closeMaterialPreview"><X :size="18" /></button>
          </header>
          <div v-if="materialPreviewStatus === 'loading'" class="material-preview-state"><LoaderCircle :size="20" class="state-spinner" />正在读取教材正文…</div>
          <div v-else-if="materialPreviewStatus === 'failed'" class="material-preview-state material-preview-state--error" role="alert">
            <CircleAlert :size="20" />
            <span>{{ userMessage(materialPreviewError) }}</span>
            <button type="button" class="text-button" @click="openMaterial(materialPreview)">重试</button>
          </div>
          <div v-else class="material-preview-content">
            <div class="material-preview-facts"><span>{{ materialPreview.file_type?.toUpperCase() }}</span><span>待课程审核</span></div>
            <p>{{ materialPreview.detail?.content || materialPreview.content_preview }}</p>
          </div>
        </section>
      </div>

      <section class="discovery-band" aria-labelledby="discovery-title">
        <div class="discovery-band__icon"><FileSearch :size="22" /></div>
        <div>
          <h2 id="discovery-title">联网发现</h2>
          <p>查找公开教材、论文和课程资料。</p>
        </div>
        <button type="button" class="secondary-button" data-testid="enter-knowledge-discovery" @click="router.push('/knowledge/discover')">
          进入联网发现<ArrowRight :size="16" />
        </button>
      </section>
    </template>

    <template v-else-if="viewKind === 'course' || viewKind === 'graph'">
      <header class="course-header">
        <button type="button" class="back-button" aria-label="返回知识库书架" @click="router.push('/knowledge')">
          <ArrowLeft :size="18" />返回书架
        </button>
        <div v-if="activeCourse" class="course-header__main">
          <div>
            <h1>{{ viewKind === 'graph' ? '课程知识图谱' : activeCourse.title }}</h1>
            <p>{{ viewKind === 'graph' ? '查看章节与知识点的关系。' : activeCourse.description }}</p>
          </div>
          <div class="course-header__actions">
            <span v-if="sourceLabel(activeCourse)" class="status-badge" data-tone="attention">
              <CircleAlert :size="14" />{{ sourceLabel(activeCourse) }}
            </span>
            <button v-if="viewKind === 'course' && activeCourse.can_manage" type="button" class="secondary-button" data-testid="add-course-material" :disabled="uploadStatus === 'loading'" @click="chooseCourseFiles">
              <LoaderCircle v-if="uploadStatus === 'loading'" :size="16" class="state-spinner" />
              <Upload v-else :size="16" />
              {{ uploadStatus === 'loading' ? '处理资料中' : '添加资料' }}
            </button>
            <button v-if="viewKind === 'course' && activeCourse.can_manage" type="button" class="secondary-button" data-testid="edit-course-structure" @click="structureEditorOpen = !structureEditorOpen">整理结构</button>
            <button v-if="viewKind === 'course'" type="button" class="secondary-button" data-testid="open-course-structure" @click="openGraph(activeCourse)">
              <GitBranch :size="16" />查看课程结构
            </button>
          </div>
        </div>
      </header>
      <CourseStructureEditor v-if="structureEditorOpen && activeCourse?.can_manage" :key="activeCourseId" :course-id="activeCourseId" @close="structureEditorOpen = false" @applied="loadOutline(activeCourseId); loadCatalog()" />
      <input
        ref="uploadInput"
        class="visually-hidden"
        type="file"
        multiple
        accept=".ppt,.pdf,.docx,.pptx,.ipynb,.md,.html,.htm,.txt,.json,.py,.mp4,.avi,.mov,.mkv,.webm,.flv"
        @change="uploadCourseFiles"
      />
      <p v-if="uploadMessage" class="action-message" aria-live="polite"><Check :size="16" />{{ uploadMessage }}</p>
      <p v-if="uploadError" class="inline-error" role="alert">{{ userMessage(uploadError) }}</p>
      <div v-if="uploadFailures.length" class="inline-error" role="alert">
        <p v-for="item in uploadFailures" :key="item.filename">{{ item.filename }}：{{ item.message }}</p>
        <p>已成功的资料可以继续阅读。请检查未完成的文件，再点“添加资料”重新上传。</p>
      </div>

      <section v-if="!activeCourse" class="state-panel state-panel--error">
        <CircleAlert :size="22" />
        <div>
          <strong>没有找到这门课程</strong>
          <p>课程可能尚未发布，或当前账号没有访问权限。</p>
          <button type="button" class="secondary-button" @click="router.push('/knowledge')">返回书架</button>
        </div>
      </section>

      <section v-else-if="outlineStatus === 'loading'" class="state-panel" data-testid="course-outline-loading" aria-live="polite">
        <LoaderCircle :size="22" class="state-spinner" />
        <div><strong>正在读取课程章节</strong><p>已加载的课程信息会保留在页面上。</p></div>
      </section>

      <section v-else-if="outlineStatus === 'failed'" class="state-panel state-panel--error" data-testid="course-outline-error" role="alert">
        <CircleAlert :size="22" />
        <div>
          <strong>章节暂时无法打开</strong>
          <p>{{ userMessage(outlineError) }}</p>
          <button type="button" class="secondary-button" @click="loadOutline(activeCourse.id)"><RefreshCw :size="16" />重试</button>
        </div>
      </section>

      <section v-else-if="outlineStatus === 'empty'" class="state-panel" data-testid="course-outline-empty">
        <BookOpen :size="22" />
        <div>
          <strong>课程还没有可阅读资料</strong>
          <p>{{ activeCourse.can_manage ? '添加 PDF、DOCX、PPTX、Notebook 或视频后，系统会解析并按章节展示。' : '课程信息会保留，资料发布后可从这里继续。' }}</p>
          <button v-if="activeCourse.can_manage" type="button" class="secondary-button" @click="chooseCourseFiles"><Upload :size="16" />选择资料</button>
        </div>
      </section>

      <section v-else-if="viewKind === 'course'" class="course-main-view" data-testid="course-workspace">
        <section class="course-search course-search--shelf" aria-labelledby="course-search-title">
          <div>
            <h2 id="course-search-title">在课程中找答案</h2>
          </div>
          <form class="search-form" @submit.prevent="runCourseSearch">
            <SearchField v-model="searchQuery" class="course-search-field" style="flex: 1" :bordered="false" maxlength="500" aria-label="课程正文检索词" placeholder="输入概念或问题" />
            <button type="submit" class="secondary-button" :disabled="searchStatus === 'loading' || !searchQuery.trim()">
              {{ searchStatus === 'loading' ? '查找中' : '查找正文' }}
            </button>
          </form>
          <p v-if="searchStatus === 'failed'" class="inline-error" role="alert">{{ userMessage(searchError) }} <button type="button" @click="runCourseSearch">重试</button></p>
          <p v-else-if="searchStatus === 'empty'" class="quiet-state">当前课程正文中没有找到足够匹配的内容，请换一个更具体的说法。</p>
          <div v-else-if="searchStatus === 'ready'" class="search-results" data-testid="course-search-results">
            <article v-for="item in searchReport.items" :key="item.document_id" class="search-result">
              <div>
                <h3>{{ item.title }}</h3>
                <div class="search-excerpt" v-html="searchExcerpt(item.content_excerpt || item.content_preview)"></div>
                <span v-if="item.chapter_title && item.chapter_title !== item.title">{{ item.chapter_title }}</span>
                <details v-if="item.matches?.length > 1" class="search-passages">
                  <summary>其他相关段落</summary>
                  <div v-for="match in item.matches.slice(1)" :key="match.evidence_id" class="search-passage">
                    <div class="search-excerpt" v-html="searchExcerpt(match.content_excerpt || match.content_preview)"></div>
                    <button type="button" class="text-button" @click="openSearchResult({ ...item, ...match })">{{ match.chapter_title || '查看这一段' }}<ArrowRight :size="15" /></button>
                  </div>
                </details>
              </div>
              <button type="button" class="text-button" :disabled="!item.locatable" @click="openSearchResult(item)">打开来源<ArrowRight :size="15" /></button>
            </article>
          </div>
        </section>

        <section class="resource-shelf-layout" aria-label="课程资源">
          <aside class="resource-filters" data-testid="resource-filters" aria-label="资源类型筛选">
            <div class="resource-filters__heading">
              <strong>资料分类</strong>
            </div>
            <button
              v-for="type in resourceTypeOptions"
              :key="type"
              type="button"
              class="resource-filter-button"
              :class="{ 'resource-filter-button--active': resourceTypeFilter === type }"
              :aria-pressed="resourceTypeFilter === type"
              @click="resourceTypeFilter = type"
            >
              <span>{{ resourceTypeLabel(type) }}</span>
              <small v-if="type !== 'all' && resourceTypeOptions.length > 2">{{ resourceItems.filter(item => resourceType(item) === type).length }}</small>
            </button>
          </aside>

          <div class="resource-shelf-content">
            <div class="resource-shelf-heading">
              <h2>课程资源</h2>
              <span>{{ filteredResources.length }} 项</span>
            </div>
            <div class="material-list-tools">
              <SearchField v-model="materialQuery" aria-label="筛选资料名称或章节" placeholder="筛选名称或章节" />
              <label class="material-sort">
                <select v-model="materialSort" aria-label="资料排列方式">
                  <option value="course">课程顺序</option>
                  <option value="title">名称顺序</option>
                  <option value="recent">最近查看</option>
                </select>
              </label>
            </div>

            <div v-if="filteredResources.length" class="resource-grid" data-testid="course-resource-shelf">
              <button
                v-for="resource in filteredResources"
                :key="resource.id"
                type="button"
                class="resource-card"
                :class="{ 'resource-card--selected': selectedResource?.id === resource.id }"
                :data-testid="`resource-card-${resource.id}`"
                :aria-pressed="selectedResource?.id === resource.id"
                @click="selectResource(resource)"
              >
                <span class="resource-card__icon" aria-hidden="true"><component :is="resourceIcon(resource)" :size="23" /></span>
                <span class="resource-card__copy">
                  <strong>{{ resource.title }}</strong>
                </span>
                <Pin v-if="pinnedMaterials.includes(resource.id)" :size="14" aria-label="已置顶" />
                <ChevronRight v-else :size="16" aria-hidden="true" />
              </button>
            </div>
            <div v-else class="quiet-state resource-empty">当前筛选下没有资源，请切换类型或添加资料。</div>
          </div>
            <section v-if="selectedResource" class="resource-detail" data-testid="selected-resource-detail" aria-live="polite">
              <div class="resource-detail__header">
                <div>
                  <h3>{{ selectedResource.title }}</h3>
                </div>
                <button type="button" class="material-pin" :aria-pressed="pinnedMaterials.includes(selectedResource.id)" :aria-label="pinnedMaterials.includes(selectedResource.id) ? '取消置顶资料' : '置顶资料'" @click="toggleMaterialPin"><Pin :size="18" /></button>
              </div>
              <div v-if="imageReadingIncomplete || selectedResource.processingStatus === 'failed'" class="resource-detail__status" role="status">
                <p>{{ readingRetryMessage || (imageReadingIncomplete ? '部分图片尚未读完整，已读文字可以继续阅读。' : '原文件与正文已保留，章节还没有整理完成。') }}</p>
                <button v-if="activeCourse.can_manage" type="button" class="text-button" :disabled="Boolean(readingRetryId)" @click="retryImageReading">
                  {{ readingRetryId === selectedResource.source_document_id ? '正在整理…' : imageReadingIncomplete ? '重新读取图片' : '重新整理章节' }}
                </button>
              </div>
              <p v-if="resourceDetailStatus === 'loading' && !selectedResourceDetail" class="resource-detail__status">正在打开资料预览…</p>
              <div v-else-if="resourceDetailStatus === 'failed' && !selectedResourceDetail" class="inline-error" role="alert">{{ resourceDetailError }} <button type="button" @click="loadSourceDetail(selectedResource.source_document_id)">重试预览</button></div>
              <p v-else-if="selectedResourceDetail?.content" class="resource-preview">{{ resourcePreview }}</p>
              <p v-else class="resource-preview">暂时没有正文预览，可打开原文阅读。</p>
              <div class="resource-reading-action">
                <button type="button" class="primary-button" aria-label="打开本章文档" :disabled="!selectedResource.source_document_id" @click="openResource()"><BookOpen :size="17" />阅读全文<ArrowRight :size="16" /></button>
              </div>
              <h4 class="resource-outline-title">章节</h4>
              <ul class="resource-chapter-list" aria-label="资源章节">
                <li v-for="chapter in selectedResource.chapters" :key="chapter.id">
                  <button type="button" @click="openChapterSource(chapter)"><span>{{ chapter.title }}</span><ChevronRight :size="15" /></button>
                </li>
              </ul>
            </section>
            <section v-else class="resource-detail resource-detail--empty"><FileSearch :size="28" /><h3>选择一份资料开始阅读</h3><p>调整左侧筛选，找到这次要学习的内容。</p></section>
        </section>
      </section>

      <section v-else class="graph-layout" data-testid="course-graph-contract">
        <div class="verified-structure">
          <div class="section-heading">
            <div><h2>已验证课程结构</h2><p>章节与知识点来自预置课程的固定版本。</p></div>
          </div>
          <button
            v-for="chapter in outline"
            :key="chapter.id"
            type="button"
            class="structure-row"
            :aria-current="selectedChapter?.id === chapter.id ? 'true' : undefined"
            @click="selectedChapterId = chapter.id"
          >
            <span>{{ chapter.position }}</span>
            <strong>{{ chapter.title }}</strong>
            <small>{{ chapter.knowledge_points?.length || 0 }} 个知识点</small>
          </button>
        </div>
        <aside v-if="selectedChapter" class="structure-overview">
          <h2>{{ selectedChapter.title }}</h2>
          <p>第 {{ selectedChapter.position }} 章 · {{ selectedChapter.knowledge_points?.length || 0 }} 个知识点</p>
          <ul>
            <li v-for="point in selectedChapter.knowledge_points" :key="point.id">{{ point.title }}</li>
          </ul>
          <button type="button" class="primary-button" :disabled="!selectedChapter.source_document_id" @click="openSelectedSource">
            <FileText :size="17" />进入章节正文
          </button>
        </aside>
      </section>
    </template>

    <template v-else>
      <header class="course-header">
        <button type="button" class="back-button" @click="router.push('/knowledge')"><ArrowLeft :size="18" />返回书架</button>
        <div class="course-header__main">
          <div><h1>联网发现</h1><p>从公开来源寻找新的课程资料，并在加入书架前完成来源、许可和解析影响确认。</p></div>
        </div>
      </header>
      <section class="discovery-workflow" data-testid="knowledge-discovery-boundary">
        <div>
          <FileSearch :size="24" />
          <h2>确认要加入的资料</h2>
          <p>{{ catalog.discovery?.authority_boundary }}</p>
        </div>
        <ol>
          <li><span>1</span><div><strong>查找与预览</strong><p>先查看原站、作者或机构和文件格式。</p></div></li>
          <li><span>2</span><div><strong>确认来源与许可</strong><p>许可或用途信息缺失时，不允许进入权威课程。</p></div></li>
          <li><span>3</span><div><strong>解析后再加入</strong><p>确认版本和解析影响后，资料才会成为可检索课程内容。</p></div></li>
        </ol>
        <p class="discovery-note">当前书架和本地课程在断网时仍可正常阅读与检索。</p>
      </section>
    </template>

    <div v-if="courseDialogOpen" class="dialog-backdrop" role="presentation" @click.self="courseDialogOpen = false">
      <section class="course-dialog" role="dialog" aria-modal="true" aria-labelledby="course-dialog-title">
        <header>
          <div>
            <span>个人学习课程</span>
            <h2 id="course-dialog-title">新建课程</h2>
          </div>
          <button type="button" class="dialog-close" aria-label="关闭" @click="courseDialogOpen = false"><X :size="18" /></button>
        </header>
        <form @submit.prevent="submitCourse">
          <label>
            <span>课程名称</span>
            <input v-model="courseForm.title" maxlength="100" required placeholder="例如：工业视觉缺陷检测" />
          </label>
          <label>
            <span>学习方向</span>
            <input v-model="courseForm.subject" maxlength="80" placeholder="例如：计算机视觉 / 智能制造" />
          </label>
          <label>
            <span>课程说明</span>
            <textarea v-model="courseForm.description" maxlength="1000" rows="4" placeholder="说明想解决的问题和预期能力" />
          </label>
          <p v-if="courseCreateError" class="inline-error" role="alert">{{ userMessage(courseCreateError) }}</p>
          <div class="dialog-actions">
            <button type="button" class="secondary-button" @click="courseDialogOpen = false">取消</button>
            <button type="submit" class="primary-button" :disabled="courseCreateStatus === 'loading' || courseForm.title.trim().length < 2">
              <LoaderCircle v-if="courseCreateStatus === 'loading'" :size="16" class="state-spinner" />
              {{ courseCreateStatus === 'loading' ? '创建中' : '创建并进入课程' }}
            </button>
          </div>
        </form>
      </section>
    </div>
  </main>
</template>

<style scoped>
.course-shelf {
  --shelf-page: var(--color-page);
  --shelf-surface: var(--color-surface);
  --shelf-ink: var(--color-text);
  --shelf-primary: var(--color-accent);
  --shelf-muted: var(--color-text-secondary);
  --shelf-line: var(--color-border);
  --shelf-soft: var(--color-surface-subtle);
  --shelf-danger: #9f352a;
  color: var(--shelf-ink);
  font-family: var(--font-sans);
  font-size: 14px;
  letter-spacing: 0;
}

.course-shelf :is(button, input, textarea) {
  font: inherit;
  letter-spacing: 0;
}

.course-shelf button:focus-visible,
.course-shelf input:focus-visible,
.course-shelf textarea:focus-visible {
  outline: 3px solid rgba(17, 33, 45, 0.28);
  outline-offset: 2px;
}

.page-intro,
.course-header__main,
.section-heading,
.course-card__heading,
.course-card__footer,
.chapter-focus__heading,
.chapter-next {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 24px;
}

.page-intro {
  padding: 8px 0 26px;
  align-items: center;
}

.page-intro__actions,
.course-header__actions,
.dialog-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
}

.page-intro__actions {
  flex-shrink: 0;
}

.page-intro__actions button,
.course-card__footer button {
  flex-shrink: 0;
  white-space: nowrap;
}

.shelf-count {
  margin-left: 12px;
  color: var(--shelf-muted);
  font-size: 16px;
  font-weight: 500;
  font-variant-numeric: tabular-nums;
}

.course-header__actions {
  flex: none;
  flex-wrap: wrap;
}

.visually-hidden {
  position: fixed;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip: rect(0 0 0 0);
  clip-path: inset(50%);
  white-space: nowrap;
}

h1,
h2,
h3,
p {
  margin: 0;
}

h1 {
  font-family: var(--font-display);
  font-size: 28px;
  line-height: 1.35;
  font-weight: 700;
}

.page-intro p,
.course-header__main > div > p {
  max-width: 68ch;
  margin-top: 10px;
  color: var(--shelf-muted);
  font-size: 15px;
  line-height: 1.75;
}

.primary-button,
.secondary-button,
.text-button,
.back-button {
  display: inline-flex;
  min-height: 40px;
  align-items: center;
  justify-content: center;
  gap: 8px;
  border-radius: 6px;
  padding: 0 16px;
  border: 1px solid transparent;
  cursor: pointer;
  font-weight: 650;
  line-height: 1.2;
  transition: background-color 140ms ease, border-color 140ms ease, color 140ms ease;
}

.primary-button {
  color: #ffffff;
  background: var(--shelf-primary);
  border-color: var(--shelf-primary);
}

.primary-button:hover {
  background: #263a47;
  border-color: #263a47;
}

.secondary-button {
  color: var(--shelf-ink);
  background: var(--shelf-surface);
  border-color: #aebbc1;
}

.secondary-button:hover {
  background: var(--shelf-soft);
  border-color: #7f9098;
}

.primary-button:disabled,
.secondary-button:disabled,
.text-button:disabled {
  cursor: not-allowed;
  opacity: 0.48;
}

.text-button,
.back-button {
  min-height: 36px;
  padding: 0;
  color: var(--color-text-secondary);
  background: transparent;
}

.text-button:hover,
.back-button:hover {
  color: var(--shelf-ink);
  text-decoration: underline;
  text-underline-offset: 4px;
}

.shelf-section {
  padding: 34px 0 8px;
}

.section-heading {
  align-items: end;
  margin-bottom: 18px;
}

.section-heading h2,
.discovery-band h2,
.course-search h2,
.chapter-points h3 {
  font-size: 20px;
  line-height: 1.35;
  font-weight: 700;
}

.section-heading p,
.discovery-band p,
.course-search > div > p {
  margin-top: 5px;
  color: var(--shelf-muted);
  line-height: 1.6;
}

.course-grid {
  display: grid;
  gap: 16px;
}

@media (min-width: 1400px) {
  .course-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

.course-card {
  display: grid;
  grid-template-columns: 74px minmax(0, 1fr);
  overflow: hidden;
  border: 1px solid var(--shelf-line);
  border-radius: 8px;
  background: var(--shelf-surface);
}

.course-spine {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: space-between;
  padding: 24px 10px 18px;
  color: #ffffff;
  background: var(--shelf-primary);
}

.course-spine > span {
  font-family: var(--font-display);
  font-size: 21px;
  font-weight: 700;
}

.course-card__body {
  display: flex;
  flex-direction: column;
  min-width: 0;
  padding: 24px;
}

.course-card__heading h3,
.recommendation-copy h3,
.search-result h3 {
  font-size: 17px;
  line-height: 1.4;
  font-weight: 700;
}

.course-card__heading > div > p {
  margin-top: 4px;
  color: var(--shelf-muted);
}

.status-badge {
  display: inline-flex;
  min-height: 30px;
  flex-shrink: 0;
  align-items: center;
  gap: 6px;
  border-radius: 999px;
  padding: 4px 10px;
  color: var(--color-text-secondary);
  background: var(--shelf-soft);
  font-size: 14px;
  font-weight: 650;
}

.status-badge[data-tone="attention"] {
  color: #704c20;
  background: #f4ede2;
}

.course-description {
  max-width: 72ch;
  margin-top: 18px;
  color: var(--color-text-secondary);
  font-size: 14px;
  line-height: 1.75;
}

.course-facts {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 18px;
  margin-top: 16px;
  color: var(--shelf-ink);
  font-variant-numeric: tabular-nums;
}

.course-card__footer {
  margin-top: auto;
  padding-top: 18px;
  align-items: center;
}

.course-card__footer > span,
.recommendation-copy > span,
.search-result span {
  color: var(--shelf-muted);
  font-size: 14px;
}

.recommendation-list {
  border-top: 1px solid var(--shelf-line);
}

.recommendation-item {
  display: grid;
  grid-template-columns: 54px minmax(0, 1fr) auto;
  align-items: center;
  gap: 18px;
  padding: 18px 0;
  border-bottom: 1px solid var(--shelf-line);
}

.recommendation-cover {
  display: flex;
  width: 54px;
  height: 70px;
  align-items: center;
  justify-content: center;
  border-radius: 4px;
  color: #ffffff;
  background: #354956;
  font-family: var(--font-display);
  font-weight: 700;
}

.recommendation-copy p {
  margin: 5px 0 7px;
  color: var(--color-text-secondary);
  line-height: 1.55;
}

.action-message {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 12px;
  color: var(--color-text-secondary);
}

.material-recommendation-section {
  border-top: 1px solid var(--shelf-line);
}

.material-recommendation-list {
  display: grid;
  gap: 10px;
}

.material-recommendation-item {
  display: grid;
  grid-template-columns: 74px minmax(0, 1fr) auto;
  align-items: center;
  gap: 16px;
  padding: 16px;
  border: 1px solid var(--shelf-line);
  background: var(--shelf-surface);
}

.material-recommendation-mark {
  display: grid;
  min-height: 54px;
  place-items: center;
  color: var(--color-text-secondary);
  border: 1px solid var(--shelf-line);
  background: var(--shelf-soft);
  font-size: 14px;
  font-weight: 700;
  letter-spacing: 0.04em;
}

.material-recommendation-copy {
  min-width: 0;
}

.material-recommendation-heading {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}

.material-recommendation-copy h3 {
  font-size: 16px;
  line-height: 1.45;
  font-weight: 700;
}

.material-recommendation-copy p {
  margin: 5px 0 6px;
  color: var(--color-text-secondary);
  line-height: 1.55;
}

.material-recommendation-copy > span {
  color: var(--shelf-muted);
  font-size: 14px;
}

.material-quality-badge {
  padding: 3px 8px;
  color: var(--color-text-secondary);
  border: 1px solid var(--shelf-line);
  background: var(--shelf-soft);
  font-size: 14px;
}

.material-preview-backdrop {
  display: grid;
  position: fixed;
  z-index: 80;
  inset: 0;
  place-items: center;
  padding: 24px;
  background: rgba(6, 20, 27, 0.42);
}

.material-preview-dialog {
  display: grid;
  width: min(100%, 760px);
  max-height: min(82vh, 780px);
  overflow: hidden;
  border: 1px solid var(--shelf-line);
  border-radius: 8px;
  background: var(--shelf-surface);
  box-shadow: 0 24px 70px rgba(6, 20, 27, 0.2);
}

.material-preview-dialog > header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 18px;
  padding: 22px 24px 18px;
  border-bottom: 1px solid var(--shelf-line);
}

.material-preview-dialog > header span {
  color: var(--shelf-muted);
  font-size: 14px;
}

.material-preview-dialog h2 {
  margin-top: 5px;
  font-size: 20px;
  line-height: 1.4;
}

.material-preview-state,
.material-preview-content {
  padding: 22px 24px;
}

.material-preview-state {
  display: flex;
  align-items: center;
  gap: 10px;
  color: var(--shelf-muted);
}

.material-preview-state--error {
  color: var(--shelf-danger);
}

.material-preview-content {
  overflow: auto;
}

.material-preview-facts {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 16px;
}

.material-preview-facts span {
  padding: 5px 9px;
  color: var(--shelf-muted);
  border: 1px solid var(--shelf-line);
  background: var(--shelf-soft);
  font-size: 14px;
}

.material-preview-content p {
  white-space: pre-wrap;
  color: var(--shelf-ink);
  line-height: 1.75;
}

.dialog-backdrop {
  display: grid;
  position: fixed;
  z-index: 80;
  inset: 0;
  place-items: center;
  padding: 24px;
  background: rgba(6, 20, 27, 0.42);
}

.course-dialog {
  width: min(100%, 560px);
  overflow: hidden;
  border: 1px solid var(--shelf-line);
  border-radius: 8px;
  background: var(--shelf-surface);
  box-shadow: 0 24px 70px rgba(6, 20, 27, 0.2);
}

.course-dialog > header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 18px;
  padding: 22px 24px 18px;
  border-bottom: 1px solid var(--shelf-line);
}

.course-dialog > header span {
  color: var(--shelf-muted);
  font-size: 14px;
}

.course-dialog > header h2 {
  margin-top: 4px;
  font-size: 22px;
}

.dialog-close {
  display: grid;
  width: 38px;
  height: 38px;
  flex: none;
  place-items: center;
  padding: 0;
  color: var(--shelf-muted);
  border: 1px solid var(--shelf-line);
  border-radius: 6px;
  background: var(--shelf-surface);
  cursor: pointer;
}

.course-dialog form {
  display: grid;
  gap: 16px;
  padding: 22px 24px 24px;
}

.course-dialog label {
  display: grid;
  gap: 7px;
  color: var(--shelf-ink);
  font-size: 14px;
  font-weight: 650;
}

.course-dialog input,
.course-dialog textarea {
  width: 100%;
  color: var(--shelf-ink);
  border: 1px solid #aebbc1;
  border-radius: 6px;
  background: var(--shelf-surface);
  font-size: 14px;
  font-weight: 400;
}

.course-dialog input {
  min-height: 42px;
  padding: 0 12px;
}

.course-dialog textarea {
  min-height: 104px;
  padding: 10px 12px;
  line-height: 1.6;
  resize: vertical;
}

.dialog-actions {
  padding-top: 2px;
}

.quiet-state {
  padding: 18px 0;
  color: var(--shelf-muted);
  line-height: 1.6;
}

.discovery-band {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: 18px;
  margin-top: 34px;
  padding: 25px 0;
  border-top: 1px solid var(--shelf-line);
  border-bottom: 1px solid var(--shelf-line);
}

.discovery-band__icon {
  display: flex;
  width: 44px;
  height: 44px;
  align-items: center;
  justify-content: center;
  border-radius: 8px;
  color: #ffffff;
  background: var(--shelf-primary);
}

.course-header {
  padding: 0 0 16px;
}

.course-header__main {
  align-items: center;
  margin-top: 8px;
}

.course-header h1 { font-family: var(--font-heading); font-size: 24px; font-weight: 650; }
.course-header .back-button { min-height: 28px; }
.course-header__main > div > p { max-width: 92ch; font-size: 14px; line-height: 1.65; }

.course-main-view {
  display: flex;
  flex-direction: column;
  gap: 18px;
  padding-top: 18px;
}

.course-search--shelf {
  display: grid; grid-template-columns: 210px minmax(0, 1fr); align-items: center;
  gap: 8px 24px; margin: 0; padding: 4px 0;
}
.course-search--shelf h2 { font-size: 16px; font-weight: 650; }
.course-search--shelf p { margin-top: 4px; color: var(--shelf-muted); font-size: 14px; }
.course-search--shelf .search-form { margin-top: 0; }
.course-search--shelf > :is(.search-results, .inline-error, .quiet-state) { grid-column: 1 / -1; }


.resource-shelf-layout {
  display: grid; grid-template-columns: 154px minmax(250px, 0.8fr) minmax(340px, 1.35fr);
  gap: 0; align-items: stretch; min-height: 550px;
  border-radius: 14px;
  background: var(--shelf-surface); overflow: hidden;
}
.resource-filters { display: flex; flex-direction: column; gap: 5px; padding: 18px 10px; background: var(--gradient-rail); }
.resource-filters__heading { display: flex; align-items: center; justify-content: space-between; gap: 8px; padding: 4px 7px 18px; font-size: 14px; }
.resource-filter-button { display: flex; min-height: 42px; align-items: center; justify-content: space-between; gap: 8px; padding: 8px; border: 1px solid transparent; border-radius: 8px; color: var(--shelf-muted); background: transparent; text-align: left; cursor: pointer; }
.resource-filter-button:hover { background: rgb(255 255 255 / 45%); }
.resource-filter-button--active { color: var(--shelf-primary); background: var(--shelf-surface); font-weight: 650; }
.resource-filter-button small { font-size: 14px; font-variant-numeric: tabular-nums; }
.resource-shelf-content { min-width: 0; padding: 18px 12px 12px; background: var(--color-surface); }
.resource-shelf-heading { display: flex; align-items: center; justify-content: space-between; margin: 0 6px 14px; }
.resource-shelf-heading h2 { font-size: 16px; font-weight: 650; }
.resource-shelf-heading > span { color: var(--shelf-muted); font-size: 14px; }
.material-list-tools { display: grid; gap: 9px; margin-bottom: 12px; }
.material-sort { display: flex; align-items: center; justify-content: flex-end; padding-inline: 6px; }
.material-sort select { max-width: 160px; padding: 4px 8px; border: 0; border-radius: 6px; background: transparent; color: var(--shelf-ink); font-size: 14px; cursor: pointer; }
.resource-grid { display: grid; align-content: start; gap: 5px; max-height: 510px; overflow-y: auto; scrollbar-gutter: stable; }
.resource-card { display: grid; min-width: 0; grid-template-columns: 34px minmax(0, 1fr) 14px; align-items: center; gap: 9px; padding: 13px 9px; border: 1px solid transparent; border-radius: 9px; color: var(--shelf-ink); background: transparent; text-align: left; cursor: pointer; }
.resource-card:hover { background: #efeeeb; }
.resource-card--selected { background: var(--color-accent-soft); }
.resource-card--selected:hover { background: var(--color-accent-soft); }
.resource-card__icon { display: grid; place-items: center; width: 34px; height: 40px; border-radius: 6px; color: #5b7281; background: #e4ebec; }
.resource-card--selected .resource-card__icon { color: var(--shelf-primary); background: #fbf7f3; }
.resource-card__copy { min-width: 0; }
.resource-card__copy strong { display: -webkit-box; overflow: hidden; -webkit-box-orient: vertical; -webkit-line-clamp: 2; font-size: 14px; font-weight: 600; line-height: 1.6; overflow-wrap: anywhere; }
.resource-empty { padding: 22px 8px; }
.resource-detail { min-width: 0; padding: 26px 30px; background: var(--gradient-paper); }
.resource-detail__header { display: flex; align-items: flex-start; justify-content: space-between; gap: 14px; }
.resource-detail h3 { font-family: var(--font-display); font-size: 26px; font-weight: 650; line-height: 1.5; overflow-wrap: anywhere; }
.material-pin { display: grid; flex: 0 0 34px; place-items: center; width: 34px; height: 34px; border: 0; border-radius: 8px; color: var(--shelf-muted); background: transparent; cursor: pointer; }
.material-pin:hover { background: var(--color-accent-soft); }
.material-pin[aria-pressed="true"] { color: var(--shelf-primary); background: var(--color-accent-soft); }
.resource-detail__status { margin-top: 22px; color: var(--shelf-muted); }
.resource-preview { margin-top: 22px; color: var(--shelf-ink); font-family: var(--font-display); font-size: 17px; line-height: 1.95; overflow-wrap: anywhere; }
.resource-reading-action { display: flex; padding-block: 22px; }
.resource-outline-title { margin: 8px 0 10px; padding-top: 20px; font-size: 14px; font-weight: 650; color: var(--shelf-muted); }
.resource-chapter-list { display: grid; gap: 6px; max-height: 220px; overflow: auto; margin: 0; padding: 0; list-style: none; }
.resource-chapter-list button { display: flex; align-items: center; justify-content: space-between; gap: 10px; width: 100%; padding: 10px 0; border: 0; background: transparent; color: var(--shelf-ink); text-align: left; cursor: pointer; }
.resource-chapter-list button:hover { color: var(--shelf-primary); }
.resource-chapter-list button svg { flex: none; }
.resource-detail--empty { display: flex; align-items: center; justify-content: center; flex-direction: column; gap: 18px; text-align: center; }
.resource-detail--empty h3 { font-size: 21px; }
.resource-detail--empty p { font-size: 14px; color: var(--shelf-muted); }

.course-layout {
  display: grid;
  grid-template-columns: minmax(250px, 0.32fr) minmax(0, 0.68fr);
  gap: 28px;
  padding-top: 28px;
}

.chapter-rail {
  align-self: start;
  border: 1px solid var(--shelf-line);
  border-radius: 8px;
  background: var(--shelf-surface);
}

.chapter-rail__heading {
  display: flex;
  min-height: 52px;
  align-items: center;
  justify-content: space-between;
  padding: 0 16px;
  border-bottom: 1px solid var(--shelf-line);
}

.chapter-rail__heading span {
  color: var(--shelf-muted);
}

.chapter-button {
  display: grid;
  width: 100%;
  min-height: 50px;
  grid-template-columns: 30px minmax(0, 1fr) auto;
  align-items: center;
  gap: 8px;
  padding: 9px 14px;
  border: 0;
  border-bottom: 1px solid var(--shelf-line);
  color: var(--color-text-secondary);
  background: transparent;
  text-align: left;
  cursor: pointer;
}

.chapter-button:last-child {
  border-bottom: 0;
}

.chapter-button:hover,
.chapter-button[aria-current="step"] {
  color: var(--shelf-ink);
  background: var(--shelf-soft);
}

.chapter-button > span:first-child {
  color: var(--shelf-muted);
  font-variant-numeric: tabular-nums;
}

.course-main {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 28px;
}

.chapter-focus {
  padding: 24px;
  border: 1px solid var(--shelf-line);
  border-radius: 8px;
  background: var(--shelf-surface);
}

.chapter-focus__heading > div > span {
  color: var(--shelf-muted);
  font-size: 14px;
}

.chapter-focus__heading h2 {
  margin-top: 6px;
  font-family: var(--font-display);
  font-size: 24px;
  line-height: 1.35;
}

.chapter-points {
  margin-top: 24px;
  padding-top: 20px;
  border-top: 1px solid var(--shelf-line);
}

.chapter-points ul,
.structure-overview ul {
  display: flex;
  flex-wrap: wrap;
  gap: 9px;
  margin: 14px 0 0;
  padding: 0;
  list-style: none;
}

.chapter-points li,
.structure-overview li {
  border-radius: 999px;
  padding: 7px 11px;
  color: var(--color-text-secondary);
  background: var(--shelf-soft);
}

.chapter-points li span {
  margin-right: 6px;
  color: var(--shelf-muted);
}

.chapter-points > p {
  margin-top: 12px;
  color: var(--shelf-muted);
}

.chapter-materials {
  display: grid;
  gap: 9px;
  margin-top: 24px;
  padding-top: 20px;
  border-top: 1px solid var(--shelf-line);
}

.chapter-materials h3 {
  margin-bottom: 4px;
  font-size: 20px;
  line-height: 1.35;
}

.material-row {
  display: grid;
  width: 100%;
  min-height: 56px;
  grid-template-columns: 22px minmax(0, 1fr) 18px;
  align-items: center;
  gap: 11px;
  padding: 10px 12px;
  color: var(--shelf-ink);
  text-align: left;
  border: 1px solid var(--shelf-line);
  border-radius: 6px;
  background: var(--shelf-surface);
  cursor: pointer;
}

.material-row:hover { background: var(--shelf-soft); }
.material-row > span { display: grid; min-width: 0; gap: 3px; }
.material-row strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.material-row small { color: var(--shelf-muted); font-size: 14px; }

.chapter-next {
  align-items: center;
  margin-top: 22px;
  color: var(--shelf-muted);
}

.course-search > div > p {
  max-width: 65ch;
}

.search-form {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: 10px;
  margin-top: 16px;
  padding: 4px 5px 4px 13px;
  border-radius: 10px;
  background: var(--shelf-surface);
}

.search-form:focus-within {
  outline: 2px solid #526b79;
  outline-offset: 2px;
}

.search-form .secondary-button {
  border: 0;
  border-radius: 7px;
  background: var(--color-surface-muted);
}

.inline-error {
  margin-top: 12px;
  color: var(--shelf-danger);
}

.inline-error button {
  border: 0;
  color: inherit;
  background: transparent;
  text-decoration: underline;
  cursor: pointer;
}

.search-results {
  margin-top: 18px;
  border-top: 1px solid var(--shelf-line);
}

.search-result {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: start;
  gap: 18px;
  padding: 17px 0;
  border-bottom: 1px solid var(--shelf-line);
}

.search-result p {
  display: -webkit-box;
  overflow: hidden;
  margin: 5px 0 7px;
  color: var(--color-text-secondary);
  line-height: 1.55;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}

.search-excerpt { max-height: 6.8em; overflow: hidden; margin: 10px 0; line-height: 1.7; color: var(--shelf-ink); }
.search-excerpt :deep(p) { margin: 0 0 8px; }
.search-excerpt :deep(:is(h1,h2,h3,h4,h5,h6)) { font-size: 1em; margin: 0 0 6px; }
.search-excerpt :deep(pre) { white-space: pre-wrap; }
.search-passages { margin-top: 12px; }
.search-passages summary { cursor: pointer; color: var(--shelf-accent); }
.search-passage { padding-top: 14px; }

.graph-layout {
  display: grid;
  grid-template-columns: minmax(0, 3fr) minmax(260px, 1fr);
  gap: 26px;
  padding-top: 28px;
}

.verified-structure {
  min-width: 0;
}

.structure-row {
  display: grid;
  width: 100%;
  min-height: 56px;
  grid-template-columns: 34px minmax(0, 1fr) auto;
  align-items: center;
  gap: 12px;
  padding: 10px 14px;
  border: 0;
  border-top: 1px solid var(--shelf-line);
  color: var(--color-text-secondary);
  background: transparent;
  text-align: left;
  cursor: pointer;
}

.structure-row:hover,
.structure-row[aria-current="true"] {
  background: var(--shelf-soft);
}

.structure-row > span,
.structure-row small {
  color: var(--shelf-muted);
  font-size: 14px;
}

.structure-overview {
  align-self: start;
  padding: 22px;
  border: 1px solid var(--shelf-line);
  border-radius: 8px;
  background: var(--shelf-surface);
}

.structure-overview h2 {
  font-size: 20px;
  line-height: 1.4;
}

.structure-overview > p {
  margin-top: 7px;
  color: var(--shelf-muted);
}

.structure-overview .primary-button {
  width: 100%;
  margin-top: 22px;
}

.discovery-workflow {
  display: grid;
  grid-template-columns: minmax(260px, 0.8fr) minmax(0, 1.2fr);
  gap: 42px;
  padding: 34px 0;
}

.discovery-workflow > div > h2 {
  margin-top: 14px;
  font-size: 22px;
}

.discovery-workflow > div > p {
  margin-top: 10px;
  color: var(--shelf-muted);
  line-height: 1.75;
}

.discovery-workflow ol {
  margin: 0;
  padding: 0;
  list-style: none;
  border-top: 1px solid var(--shelf-line);
}

.discovery-workflow li {
  display: grid;
  grid-template-columns: 32px minmax(0, 1fr);
  gap: 12px;
  padding: 17px 0;
  border-bottom: 1px solid var(--shelf-line);
}

.discovery-workflow li > span {
  display: flex;
  width: 28px;
  height: 28px;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  color: #ffffff;
  background: var(--shelf-primary);
  font-variant-numeric: tabular-nums;
}

.discovery-workflow li p {
  margin-top: 5px;
  color: var(--shelf-muted);
  line-height: 1.55;
}

.discovery-note {
  grid-column: 1 / -1;
  padding-top: 18px;
  border-top: 1px solid var(--shelf-line);
  color: var(--shelf-muted);
}

.state-panel {
  display: flex;
  min-height: 180px;
  align-items: flex-start;
  gap: 14px;
  padding: 34px;
  border: 1px solid var(--shelf-line);
  border-radius: 8px;
  background: var(--shelf-surface);
}

.state-panel strong {
  display: block;
  font-size: 17px;
}

.state-panel p {
  max-width: 62ch;
  margin: 7px 0 15px;
  color: var(--shelf-muted);
  line-height: 1.6;
}

.state-panel--error {
  color: var(--shelf-danger);
}

.state-spinner {
  animation: shelf-spin 900ms linear infinite;
}

@keyframes shelf-spin {
  to { transform: rotate(360deg); }
}

@media (max-width: 1100px) {
  .course-layout,
  .graph-layout {
    grid-template-columns: minmax(220px, 0.36fr) minmax(0, 0.64fr);
    gap: 20px;
  }

  .resource-grid {
    grid-template-columns: 1fr;
  }

  .course-card__heading,
  .chapter-focus__heading {
    align-items: flex-start;
    flex-direction: column;
  }
}

@media (max-width: 1350px) {
  .resource-shelf-layout { grid-template-columns: minmax(240px, 0.85fr) minmax(320px, 1.2fr); }
  .resource-filters { grid-column: 1 / -1; flex-direction: row; align-items: center; flex-wrap: wrap; padding: 10px 14px; gap: 7px; }
  .resource-filters__heading { padding: 0 14px 0 0; gap: 9px; }
  .resource-filter-button { gap: 12px; min-height: 36px; padding: 5px 12px; }
  .course-header__main { align-items: flex-start; flex-wrap: wrap; gap: 14px; }
  .resource-detail { padding: 24px; }
}
@media (max-width: 850px) {
  .resource-shelf-layout { grid-template-columns: 1fr; }
  .resource-grid { max-height: 260px; }
  .course-search--shelf { grid-template-columns: 1fr; gap: 12px; }
  .course-header h1 { font-size: 23px; }
  .resource-detail { padding: 22px; }
}

@media (prefers-reduced-motion: reduce) {
  .course-shelf *,
  .course-shelf *::before,
  .course-shelf *::after {
    scroll-behavior: auto !important;
    transition-duration: 0.01ms !important;
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
  }
}
</style>
