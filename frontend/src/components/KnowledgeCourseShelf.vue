<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
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
  RefreshCw,
  Search,
  ShieldCheck,
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
} from '../api'
import SearchField from './ui/SearchField.vue'

const emit = defineEmits(['open-source', 'open-search-result'])
const route = useRoute()
const router = useRouter()

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
const sourceDetails = ref({})
const resourceDetailStatus = ref('idle')
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
const materialPreview = ref(null)
const materialPreviewStatus = ref('idle')
const materialPreviewError = ref('')

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
        title: sourceDetails.value[id]?.title || chapter.title,
        chapters: [],
        knowledgePointCount: 0,
      })
    }
    const item = groups.get(id)
    item.chapters.push(chapter)
    item.knowledgePointCount += chapter.knowledge_points?.length || 0
    if (!sourceDetails.value[id]?.title && chapter.title) item.title = chapter.title
  })
  return [...groups.values()].map(item => ({
    ...item,
    fileType: sourceDetails.value[item.id]?.file_type || sourceDetails.value[item.id]?.file_format || 'resource',
    processingStatus: sourceDetails.value[item.id]?.source_processing_status || sourceDetails.value[item.id]?.processing_status || 'ready',
  }))
})
const resourceTypeOptions = computed(() => {
  const types = new Set(resourceItems.value.map(item => resourceType(item)))
  return ['all', ...[...types].filter(type => type !== 'all')]
})
const filteredResources = computed(() => (
  resourceTypeFilter.value === 'all'
    ? resourceItems.value
    : resourceItems.value.filter(item => resourceType(item) === resourceTypeFilter.value)
))
const selectedResource = computed(() => (
  resourceItems.value.find(item => item.id === selectedResourceId.value)
  || filteredResources.value[0]
  || resourceItems.value[0]
  || null
))
const selectedResourceDetail = computed(() => (
  selectedResource.value ? sourceDetails.value[selectedResource.value.id] || null : null
))
const firstShelfCourse = computed(() => shelfCourses.value[0] || null)

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
  return 'ML'
}

function sourceLabel(course) {
  if (course?.source_health === 'ready' && course?.index_status === 'ready') return '来源与索引完整'
  if (course?.source_health === 'missing') return '来源信息待补充'
  return '部分资料仍在整理'
}

function sourceTone(course) {
  return course?.source_health === 'ready' && course?.index_status === 'ready' ? 'ready' : 'attention'
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
  try {
    const result = await uploadKnowledgeDocumentsBatch(files, 'default', activeCourse.value.id)
    const failedNames = (result.results || [])
      .filter(item => item.status === 'failed')
      .map(item => item.filename)
    uploadMessage.value = `${result.succeeded || 0} 份资料已进入课程${failedNames.length ? `，${failedNames.length} 份失败` : ''}`
    if (failedNames.length) uploadError.value = `未完成：${failedNames.join('、')}`
    await loadCatalog()
    await loadOutline(activeCourse.value.id)
    uploadStatus.value = failedNames.length ? 'partial' : 'ready'
  } catch (error) {
    uploadStatus.value = 'failed'
    uploadError.value = apiErrorMessage(error, '资料上传失败，请重试')
  }
}

async function loadOutline(courseId) {
  if (!courseId) {
    outline.value = []
    outlineStatus.value = 'idle'
    return
  }
  outlineStatus.value = 'loading'
  outlineError.value = ''
  try {
    const result = await getCanonicalCourseOutline(courseId)
    outline.value = Array.isArray(result) ? result : []
    selectedChapterId.value = rootChapters.value.some(item => item.id === selectedChapterId.value)
      ? selectedChapterId.value
      : rootChapters.value[0]?.id || ''
    selectedResourceId.value = ''
    resourceTypeFilter.value = 'all'
    outlineStatus.value = outline.value.length ? 'ready' : 'empty'
  } catch (error) {
    outline.value = []
    outlineStatus.value = 'failed'
    outlineError.value = apiErrorMessage(error, '课程章节加载失败')
  }
}

async function loadSourceDetail(sourceDocumentId) {
  if (!sourceDocumentId || sourceDetails.value[sourceDocumentId]) return
  resourceDetailStatus.value = 'loading'
  try {
    const detail = await getCanonicalCourseSource(sourceDocumentId)
    sourceDetails.value = { ...sourceDetails.value, [sourceDocumentId]: detail }
    resourceDetailStatus.value = 'ready'
  } catch (error) {
    resourceDetailStatus.value = 'failed'
  }
}

function selectResource(resource) {
  if (!resource) return
  selectedResourceId.value = resource.id
  void loadSourceDetail(resource.source_document_id)
}

function openResource(resource = selectedResource.value) {
  const chapter = resource?.chapters?.[0]
  if (!resource || !chapter) return
  emit('open-source', {
    courseId: activeCourse.value?.id,
    sourceDocumentId: resource.source_document_id,
    chapterId: chapter.id,
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
  searchQuery.value = ''
  searchReport.value = null
  searchStatus.value = 'idle'
  sourceDetails.value = {}
  resourceDetailStatus.value = 'idle'
  loadOutline(courseId)
}, { immediate: true })

watch([resourceItems, resourceTypeFilter], () => {
  if (!filteredResources.value.some(item => item.id === selectedResourceId.value)) {
    selectedResourceId.value = filteredResources.value[0]?.id || resourceItems.value[0]?.id || ''
  }
  if (selectedResource.value?.source_document_id) void loadSourceDetail(selectedResource.value.source_document_id)
}, { immediate: true })

onMounted(loadCatalog)
</script>

<template>
  <main class="course-shelf" data-testid="knowledge-course-shelf">
    <section v-if="catalogStatus === 'loading'" class="state-panel" data-testid="course-shelf-loading" aria-live="polite">
      <LoaderCircle :size="22" class="state-spinner" />
      <div>
        <strong>正在整理课程书架</strong>
        <p>读取预置课程、章节和来源状态。</p>
      </div>
    </section>

    <section v-else-if="catalogStatus === 'failed'" class="state-panel state-panel--error" data-testid="course-shelf-error" role="alert">
      <CircleAlert :size="22" />
      <div>
        <strong>课程书架暂时无法打开</strong>
        <p>{{ catalogError }}</p>
        <button type="button" class="secondary-button" @click="loadCatalog">
          <RefreshCw :size="16" />重新加载
        </button>
      </div>
    </section>

    <section v-else-if="catalogStatus === 'empty'" class="state-panel" data-testid="course-shelf-empty">
      <Library :size="24" />
      <div>
        <strong>还没有可用课程</strong>
        <p>课程资料不会要求学生在首次使用时上传；课程发布后会直接显示在这里。</p>
        <button type="button" class="primary-button empty-state-create" data-testid="create-personal-course-empty" @click="openCourseCreator">
          <Plus :size="17" />新建课程
        </button>
      </div>
    </section>

    <template v-else-if="viewKind === 'home'">
      <header class="page-intro">
        <div>
          <h1>课程知识库</h1>
          <p>从团队预置课程直接开始。章节、正文、知识点和来源已经按课程组织，无需先上传教材。</p>
        </div>
        <div class="page-intro__actions">
          <button type="button" class="secondary-button" data-testid="create-personal-course" @click="openCourseCreator">
            <Plus :size="17" />新建课程
          </button>
          <button v-if="firstShelfCourse" type="button" class="primary-button" @click="openCourse(firstShelfCourse)">
            继续学习<ArrowRight :size="17" />
          </button>
        </div>
      </header>

      <section class="shelf-section" aria-labelledby="my-shelf-title">
        <div class="section-heading">
          <div>
            <h2 id="my-shelf-title">我的书架</h2>
            <p>{{ shelfCourses.length }} 门可直接学习的课程</p>
          </div>
        </div>

        <div class="course-grid" data-testid="my-course-shelf">
          <article v-for="course in shelfCourses" :key="course.id" class="course-card" :data-testid="`shelf-course-${course.id}`">
            <div class="course-spine" aria-hidden="true">
              <span>{{ courseMark(course) }}</span>
              <small>{{ course.shelf_origin === 'team_preloaded' ? 'PRESET' : 'SHELF' }}</small>
            </div>
            <div class="course-card__body">
              <div class="course-card__heading">
                <div>
                  <h3>{{ course.title }}</h3>
                  <p>{{ course.subject || course.domain_pack }}</p>
                </div>
                <span class="status-badge" :data-tone="sourceTone(course)">
                  <ShieldCheck :size="14" />{{ sourceLabel(course) }}
                </span>
              </div>
              <p class="course-description">{{ course.description }}</p>
              <dl class="course-facts">
                <div><dt>章节</dt><dd>{{ course.chapter_count }}</dd></div>
                <div><dt>文档</dt><dd>{{ course.document_count }}</dd></div>
                <div><dt>知识点</dt><dd>{{ course.knowledge_point_count }}</dd></div>
                <div><dt>来源</dt><dd>{{ course.source_count }}</dd></div>
              </dl>
              <div class="course-card__footer">
                <span>{{ course.version }} · {{ course.language || '中文' }}</span>
                <button type="button" class="secondary-button" :data-testid="`open-course-${course.id}`" @click="openCourse(course)">
                  打开课程<ChevronRight :size="16" />
                </button>
              </div>
            </div>
          </article>
        </div>
      </section>

      <section class="shelf-section" aria-labelledby="recommendation-title">
        <div class="section-heading">
          <div>
            <h2 id="recommendation-title">智能推荐</h2>
            <p>{{ catalog.profile_basis?.explanation }}</p>
          </div>
        </div>

        <div v-if="recommendations.length" class="recommendation-list" data-testid="course-recommendations">
          <article v-for="course in recommendations" :key="course.id" class="recommendation-item">
            <div class="recommendation-cover" aria-hidden="true">{{ courseMark(course) }}</div>
            <div class="recommendation-copy">
              <h3>{{ course.title }}</h3>
              <p>{{ course.recommendation_reason }}</p>
              <span>{{ course.chapter_count }} 章 · {{ course.document_count }} 份文档 · {{ sourceLabel(course) }}</span>
            </div>
            <button type="button" class="secondary-button" :data-testid="`add-course-${course.id}`" :disabled="addingCourseId === course.id" @click="addCourse(course)">
              <LoaderCircle v-if="addingCourseId === course.id" :size="16" class="state-spinner" />
              <Plus v-else :size="16" />
              {{ addingCourseId === course.id ? '正在加入' : '加入书架' }}
            </button>
          </article>
        </div>
        <div v-else class="quiet-state">当前已审核课程都在你的书架中。</div>
        <p v-if="actionMessage" class="action-message" aria-live="polite"><Check :size="16" />{{ actionMessage }}</p>
      </section>

      <section class="shelf-section material-recommendation-section" aria-labelledby="material-recommendation-title">
        <div class="section-heading">
          <div>
            <h2 id="material-recommendation-title">教材补充推荐</h2>
            <p>这些资料尚未纳入当前课程书架，适合作为辅助阅读；查看不会改变课程检索或学习进度。</p>
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
              <p>{{ material.recommendation_reason }}</p>
              <span>{{ material.chunk_count }} 个解析分块 · {{ material.owner_scope === 'personal' ? '你的资料' : '公共资料' }} · {{ material.traceability === 'canonical_source' ? '来源可定位' : '辅助材料 / 待审核' }}</span>
            </div>
            <button type="button" class="secondary-button" :data-testid="`open-material-${material.id}`" @click="openMaterial(material)">
              <FileText :size="16" />{{ material.open_mode === 'reader' ? '打开教材' : '查看预览' }}
            </button>
          </article>
        </div>
        <div v-else class="quiet-state" data-testid="material-recommendations-empty">暂无符合质量和权限条件的教材补充资料。</div>
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
            <span>{{ materialPreviewError }}</span>
            <button type="button" class="text-button" @click="openMaterial(materialPreview)">重试</button>
          </div>
          <div v-else class="material-preview-content">
            <div class="material-preview-facts"><span>{{ materialPreview.file_type?.toUpperCase() }}</span><span>{{ materialPreview.chunk_count }} 个分块</span><span>待课程审核</span></div>
            <p>{{ materialPreview.detail?.content || materialPreview.content_preview }}</p>
          </div>
        </section>
      </div>

      <section class="discovery-band" aria-labelledby="discovery-title">
        <div class="discovery-band__icon"><FileSearch :size="22" /></div>
        <div>
          <h2 id="discovery-title">联网发现</h2>
          <p>查找新的教材和课程资料。联网结果先作为候选来源，完成来源与许可确认后才能加入课程知识库。</p>
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
            <p>{{ viewKind === 'graph' ? '查看课程中已经验证的章节与知识点结构。浏览不会改变学习掌握度。' : activeCourse.description }}</p>
          </div>
          <div class="course-header__actions">
            <span class="status-badge" :data-tone="sourceTone(activeCourse)">
              <ShieldCheck :size="14" />{{ sourceLabel(activeCourse) }}
            </span>
            <button v-if="viewKind === 'course' && activeCourse.can_manage" type="button" class="secondary-button" data-testid="add-course-material" :disabled="uploadStatus === 'loading'" @click="chooseCourseFiles">
              <LoaderCircle v-if="uploadStatus === 'loading'" :size="16" class="state-spinner" />
              <Upload v-else :size="16" />
              {{ uploadStatus === 'loading' ? '处理资料中' : '添加资料' }}
            </button>
            <button v-if="viewKind === 'course'" type="button" class="secondary-button" data-testid="open-course-structure" @click="openGraph(activeCourse)">
              <GitBranch :size="16" />查看课程结构
            </button>
          </div>
        </div>
      </header>
      <input
        ref="uploadInput"
        class="visually-hidden"
        type="file"
        multiple
        accept=".ppt,.pdf,.docx,.pptx,.ipynb,.md,.txt,.json,.py,.mp4,.avi,.mov,.mkv,.webm,.flv"
        @change="uploadCourseFiles"
      />
      <p v-if="uploadMessage" class="action-message" aria-live="polite"><Check :size="16" />{{ uploadMessage }}</p>
      <p v-if="uploadError" class="inline-error" role="alert">{{ uploadError }}</p>

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
          <p>{{ outlineError }}</p>
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
            <h2 id="course-search-title">检索课程正文</h2>
            <p>结果只来自当前课程已解析正文，并保留章节和来源定位。</p>
          </div>
          <form class="search-form" @submit.prevent="runCourseSearch">
            <SearchField v-model="searchQuery" class="course-search-field" style="flex: 1" :bordered="false" maxlength="500" aria-label="课程正文检索词" placeholder="输入概念或问题" />
            <button type="submit" class="secondary-button" :disabled="searchStatus === 'loading' || !searchQuery.trim()">
              {{ searchStatus === 'loading' ? '检索中' : '检索' }}
            </button>
          </form>
          <p v-if="searchStatus === 'failed'" class="inline-error" role="alert">{{ searchError }} <button type="button" @click="runCourseSearch">重试</button></p>
          <p v-else-if="searchStatus === 'empty'" class="quiet-state">当前课程正文中没有找到足够匹配的内容，请换一个更具体的说法。</p>
          <div v-else-if="searchStatus === 'ready'" class="search-results" data-testid="course-search-results">
            <article v-for="item in searchReport.items" :key="item.document_id" class="search-result">
              <div>
                <h3>{{ item.title }}</h3>
                <p>{{ item.content_preview }}</p>
                <span>{{ item.chapter_title }} · 来源可定位</span>
              </div>
              <button type="button" class="text-button" :disabled="!item.locatable" @click="openSearchResult(item)">打开来源<ArrowRight :size="15" /></button>
            </article>
          </div>
        </section>

        <section class="resource-shelf-layout" aria-label="课程资源">
          <aside class="resource-filters" data-testid="resource-filters" aria-label="资源类型筛选">
            <div class="resource-filters__heading">
              <strong>资源类型</strong>
              <span>{{ resourceItems.length }}</span>
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
              <small>{{ type === 'all' ? resourceItems.length : resourceItems.filter(item => resourceType(item) === type).length }}</small>
            </button>
          </aside>

          <div class="resource-shelf-content">
            <div class="resource-shelf-heading">
              <div>
                <h2>课程资源</h2>
                <p>点击资源查看简介、解析状态和预览；进入资源后才使用完整阅读器。</p>
              </div>
              <span>{{ filteredResources.length }} 项</span>
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
                  <small>{{ resourceType(resource) }} · {{ resource.chapters.length }} 个语义章节</small>
                </span>
                <ChevronRight :size="16" aria-hidden="true" />
              </button>
            </div>
            <div v-else class="quiet-state resource-empty">当前筛选下没有资源，请切换类型或添加资料。</div>

            <section v-if="selectedResource" class="resource-detail" data-testid="selected-resource-detail" aria-live="polite">
              <div class="resource-detail__header">
                <div>
                  <span class="resource-detail__eyebrow">已选资源 · {{ resourceType(selectedResource) }}</span>
                  <h3>{{ selectedResource.title }}</h3>
                  <span class="resource-detail__section-label">本章资料</span>
                </div>
                <button type="button" class="primary-button" aria-label="打开本章文档" :disabled="!selectedResource.source_document_id" @click="openResource()">
                  <FileText :size="17" />进入资源
                </button>
              </div>
              <div class="resource-detail__facts">
                <span>格式：{{ selectedResourceDetail?.file_type || selectedResource.fileType || '待识别' }}</span>
                <span>章节：{{ selectedResource.chapters.length }}</span>
                <span>知识点：{{ selectedResource.knowledgePointCount }}</span>
                <span>状态：{{ selectedResource.processingStatus === 'failed' ? '待重试' : '已解析' }}</span>
              </div>
              <p v-if="resourceDetailStatus === 'loading'" class="resource-detail__status">正在读取资源简介与预览…</p>
              <p v-else-if="selectedResourceDetail?.content" class="resource-preview">{{ selectedResourceDetail.content.slice(0, 420) }}{{ selectedResourceDetail.content.length > 420 ? '…' : '' }}</p>
              <p v-else class="resource-preview">该资源已有 canonical 来源定位，进入资源后可查看完整正文、目录和多格式预览。</p>
              <ul class="resource-chapter-list" aria-label="资源语义章节">
                <li v-for="chapter in selectedResource.chapters" :key="chapter.id">
                  <span>{{ chapter.title }}</span>
                  <small>{{ chapter.knowledge_points?.length || 0 }} 个知识点</small>
                </li>
              </ul>
            </section>
          </div>
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
          <h2>候选资料不会自动进入课程</h2>
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
          <p v-if="courseCreateError" class="inline-error" role="alert">{{ courseCreateError }}</p>
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
  --shelf-page: #f5f7f7;
  --shelf-surface: #ffffff;
  --shelf-ink: #06141b;
  --shelf-primary: #11212d;
  --shelf-muted: #52606a;
  --shelf-line: #d8dfe2;
  --shelf-soft: #edf1f2;
  --shelf-danger: #9f352a;
  color: var(--shelf-ink);
  font-family: "Source Han Sans SC", "Noto Sans CJK SC", sans-serif;
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
  padding: 8px 0 34px;
  align-items: center;
  border-bottom: 1px solid var(--shelf-line);
}

.page-intro__actions,
.course-header__actions,
.dialog-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
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
  font-family: "Source Han Serif SC", "Noto Serif CJK SC", serif;
  font-size: 32px;
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
  color: #334d5c;
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
  min-height: 230px;
  flex-direction: column;
  align-items: center;
  justify-content: space-between;
  padding: 24px 10px 18px;
  color: #ffffff;
  background: var(--shelf-primary);
}

.course-spine > span {
  font-family: "Source Han Serif SC", "Noto Serif CJK SC", serif;
  font-size: 21px;
  font-weight: 700;
}

.course-spine small {
  display: block;
  font-size: 14px;
  line-height: 1.4;
  writing-mode: vertical-rl;
}

.course-card__body {
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
  color: #334d5c;
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
  color: #31434d;
  font-size: 14px;
  line-height: 1.75;
}

.course-facts {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  margin: 22px 0 0;
  padding: 16px 0;
  border-top: 1px solid var(--shelf-line);
  border-bottom: 1px solid var(--shelf-line);
}

.course-facts div {
  padding: 0 14px;
  border-right: 1px solid var(--shelf-line);
}

.course-facts div:first-child {
  padding-left: 0;
}

.course-facts div:last-child {
  border-right: 0;
}

.course-facts dt {
  color: var(--shelf-muted);
  font-size: 14px;
}

.course-facts dd {
  margin: 5px 0 0;
  font-size: 20px;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
}

.course-card__footer {
  margin-top: 18px;
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
  font-family: "Source Han Serif SC", "Noto Serif CJK SC", serif;
  font-weight: 700;
}

.recommendation-copy p {
  margin: 5px 0 7px;
  color: #31434d;
  line-height: 1.55;
}

.action-message {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 12px;
  color: #334d5c;
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
  color: #334d5c;
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
  color: #31434d;
  line-height: 1.55;
}

.material-recommendation-copy > span {
  color: var(--shelf-muted);
  font-size: 14px;
}

.material-quality-badge {
  padding: 3px 8px;
  color: #334d5c;
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
  padding: 4px 0 26px;
  border-bottom: 1px solid var(--shelf-line);
}

.course-header__main {
  align-items: center;
  margin-top: 18px;
}

.course-main-view {
  display: flex;
  flex-direction: column;
  gap: 26px;
  padding-top: 26px;
}

.course-search--shelf {
  margin: 0;
}

.resource-shelf-layout {
  display: grid;
  grid-template-columns: minmax(180px, 0.22fr) minmax(0, 0.78fr);
  gap: 28px;
  align-items: start;
}

.resource-filters {
  display: flex;
  position: sticky;
  top: 20px;
  flex-direction: column;
  gap: 5px;
  padding: 16px;
  border: 1px solid var(--shelf-line);
  border-radius: 8px;
  background: var(--shelf-surface);
}

.resource-filters__heading,
.resource-shelf-heading,
.resource-detail__header,
.resource-detail__facts,
.resource-chapter-list li {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
}

.resource-filters__heading {
  padding: 2px 4px 12px;
  border-bottom: 1px solid var(--shelf-line);
}

.resource-filters__heading span,
.resource-shelf-heading > span,
.resource-detail__facts,
.resource-detail__eyebrow,
.resource-chapter-list small {
  color: var(--shelf-muted);
  font-size: 14px;
}

.resource-filter-button {
  display: flex;
  min-height: 42px;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 0 10px;
  border: 1px solid transparent;
  border-radius: 6px;
  color: #31434d;
  background: transparent;
  text-align: left;
  cursor: pointer;
}

.resource-filter-button:hover,
.resource-filter-button--active {
  color: var(--shelf-ink);
  border-color: var(--shelf-line);
  background: var(--shelf-soft);
}

.resource-filter-button small {
  color: var(--shelf-muted);
  font-size: 14px;
}

.resource-shelf-content {
  min-width: 0;
}

.resource-shelf-heading {
  align-items: flex-end;
  margin-bottom: 16px;
}

.resource-shelf-heading h2 {
  font-size: 22px;
  line-height: 1.35;
}

.resource-shelf-heading p {
  margin-top: 7px;
  color: var(--shelf-muted);
  line-height: 1.6;
}

.resource-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
}

.resource-card {
  display: grid;
  min-width: 0;
  grid-template-columns: 46px minmax(0, 1fr) 18px;
  align-items: center;
  gap: 12px;
  padding: 16px;
  border: 1px solid var(--shelf-line);
  border-radius: 8px;
  color: var(--shelf-ink);
  background: var(--shelf-surface);
  text-align: left;
  cursor: pointer;
  transition: border-color 140ms ease, background-color 140ms ease, transform 140ms ease;
}

.resource-card:hover,
.resource-card--selected {
  border-color: #70838d;
  background: var(--shelf-soft);
}

.resource-card:active {
  transform: translateY(1px);
}

.resource-card__icon {
  display: flex;
  width: 46px;
  height: 46px;
  align-items: center;
  justify-content: center;
  border-radius: 8px;
  color: #ffffff;
  background: var(--shelf-primary);
}

.resource-card__copy {
  display: grid;
  min-width: 0;
  gap: 6px;
}

.resource-card__copy strong {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 15px;
}

.resource-card__copy small {
  color: var(--shelf-muted);
  font-size: 14px;
}

.resource-empty {
  padding: 22px 0;
}

.resource-detail {
  margin-top: 18px;
  padding: 22px;
  border: 1px solid var(--shelf-line);
  border-radius: 8px;
  background: var(--shelf-surface);
}

.resource-detail__header {
  align-items: flex-start;
}

.resource-detail__eyebrow {
  display: block;
  margin-bottom: 6px;
}

.resource-detail h3 {
  font-family: "Source Han Serif SC", "Noto Serif CJK SC", serif;
  font-size: 24px;
  line-height: 1.35;
}

.resource-detail__facts {
  justify-content: flex-start;
  flex-wrap: wrap;
  margin-top: 18px;
  padding: 14px 0;
  border-top: 1px solid var(--shelf-line);
  border-bottom: 1px solid var(--shelf-line);
}

.resource-detail__facts span {
  padding-right: 14px;
  border-right: 1px solid var(--shelf-line);
}

.resource-detail__facts span:last-child {
  border-right: 0;
}

.resource-detail__status {
  margin-top: 16px;
  color: var(--shelf-muted);
}

.resource-preview {
  margin-top: 16px;
  color: #31434d;
  line-height: 1.75;
  white-space: pre-line;
}

.resource-chapter-list {
  display: grid;
  gap: 8px;
  margin: 18px 0 0;
  padding: 0;
  list-style: none;
}

.resource-chapter-list li {
  padding: 10px 12px;
  border-radius: 6px;
  background: var(--shelf-soft);
}

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
  color: #31434d;
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

.chapter-focus,
.course-search {
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
  font-family: "Source Han Serif SC", "Noto Serif CJK SC", serif;
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
  color: #31434d;
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
.material-row small { color: var(--shelf-muted); font-size: 13px; }

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
  grid-template-columns: auto minmax(0, 1fr) auto;
  align-items: center;
  gap: 10px;
  margin-top: 16px;
  padding-left: 13px;
  border: 1px solid #aebbc1;
  border-radius: 7px;
  background: #ffffff;
}

.search-form:focus-within {
  border-color: #526b79;
}

.search-form .secondary-button {
  margin-right: -1px;
  border-radius: 0 6px 6px 0;
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
  color: #31434d;
  line-height: 1.55;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}

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
  color: #31434d;
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
  .resource-shelf-layout,
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
