<script setup>
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  AlertTriangle,
  ArrowDown,
  ArrowLeft,
  ArrowRight,
  ArrowUp,
  BookOpen,
  Check,
  ChevronDown,
  Download,
  ExternalLink,
  Presentation,
  MessageSquareText,
  Pencil,
  Plus,
  RefreshCw,
  RotateCcw,
  Save,
  ShieldCheck,
  Trash2,
  X,
} from '@lucide/vue'
import ResourceHistoryDrawer from '../components/ResourceHistoryDrawer.vue'
import ResourceToolbar from '../components/ResourceToolbar.vue'
import ResourceProfileAdaptation from '../components/ResourceProfileAdaptation.vue'
import { compareM5ResourceVersions, createM5ResourceVersion, exportM5Deck, getM5Resource, restoreM5ResourceVersion } from '../api/m5'
import { useCourseContextStore } from '../stores/courseContext'

const route = useRoute()
const router = useRouter()
const courseContext = useCourseContextStore()
const loading = ref(true)
const saving = ref(false)
const exporting = ref('')
const error = ref('')
const actionError = ref('')
const notice = ref('')
const detail = ref(null)
const selectedVersionId = ref('')
const selectedSlideId = ref('')
const editing = ref(false)
const draft = ref(null)
const historyOpen = ref(false)
const historyError = ref('')
const restoringId = ref('')
const comparingId = ref('')
const compareResult = ref(null)

const resourceId = computed(() => String(route.params.resourceId || ''))
const workspace = computed(() => detail.value?.deck || {})
const versions = computed(() => workspace.value.versions || [])
const currentVersionId = computed(() => workspace.value.current_version_id || '')
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
const projection = computed(() => selectedVersion.value?.projection || workspace.value.current || null)
const structured = computed(() => projection.value?.structured || null)
const activeContent = computed(() => editing.value ? draft.value : structured.value)
const legacy = computed(() => projection.value?.legacy || null)
const catalog = computed(() => detail.value?.catalog || {})
const sources = computed(() => projection.value?.source_refs || [])
const isCurrentVersion = computed(() => selectedVersion.value?.id === currentVersionId.value)
const versionLabel = computed(() => selectedVersion.value ? `v${selectedVersion.value.number}` : '未记录')
const slides = computed(() => editing.value ? (draft.value?.slides || []) : (structured.value?.slides || []))
const selectedSlide = computed(() => (
  slides.value.find(item => item.id === selectedSlideId.value)
  || slides.value[0]
  || null
))
const selectedSlideIndex = computed(() => slides.value.findIndex(item => item.id === selectedSlide.value?.id))
const title = computed(() => activeContent.value?.title || legacy.value?.title || catalog.value.title || 'PPT / 网页课件')
const summary = computed(() => activeContent.value?.summary || '查看当前知识点的结构化课件、来源和历史版本。')
const canEdit = computed(() => projection.value?.mode === 'structured' && isCurrentVersion.value)

function clone(value) {
  return value ? JSON.parse(JSON.stringify(value)) : null
}

function message(exception, fallback) {
  const detailMessage = exception?.response?.data?.detail?.message || exception?.detail?.message
  return detailMessage || (typeof exception?.detail === 'string' ? exception.detail : '') || exception?.message || fallback
}

function selectFirstSlide() {
  selectedSlideId.value = slides.value[0]?.id || ''
}

async function loadResource({ preserveVersion = false, preserveDraft = false } = {}) {
  const savedVersionId = selectedVersionId.value
  const savedSlideId = selectedSlideId.value
  const savedDraft = preserveDraft ? clone(draft.value) : null
  loading.value = true
  error.value = ''
  try {
    const payload = await getM5Resource(resourceId.value)
    if (payload?.catalog?.type !== 'deck' || !payload.deck) throw new Error('当前资源不是 PPT / 网页课件。')
    detail.value = payload
    const requestedVersionId = typeof route.query.version_id === 'string' ? route.query.version_id : ''
    selectedVersionId.value = preserveVersion && payload.deck.versions?.some(item => item.id === savedVersionId)
      ? savedVersionId
      : payload.deck.versions?.some(item => item.id === requestedVersionId)
        ? requestedVersionId
        : payload.deck.current_version_id || payload.deck.versions?.at(-1)?.id || ''
    if (savedDraft) {
      draft.value = savedDraft
      editing.value = true
    }
    await nextTick()
    selectedSlideId.value = slides.value.some(item => item.id === savedSlideId)
      ? savedSlideId
      : slides.value[0]?.id || ''
  } catch (exception) {
    error.value = message(exception, '课件加载失败，请稍后重试。')
  } finally {
    loading.value = false
  }
}

function startEditing() {
  if (!canEdit.value) return
  draft.value = clone(structured.value)
  editing.value = true
  actionError.value = ''
  notice.value = ''
}

function cancelEditing() {
  editing.value = false
  draft.value = null
  actionError.value = ''
  selectFirstSlide()
}

function addSlide() {
  if (!editing.value || draft.value.slides.length >= 30) return
  const id = `slide-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`
  draft.value.slides.push({
    id,
    layout: 'content',
    title: '新页面',
    subtitle: '',
    body: '在此填写页面内容。',
    bullets: [],
    speakerNotes: '',
    sourceRefIds: [],
  })
  selectedSlideId.value = id
}

function removeSlide() {
  if (!editing.value || draft.value.slides.length <= 1 || selectedSlideIndex.value < 0) return
  const index = selectedSlideIndex.value
  draft.value.slides.splice(index, 1)
  selectedSlideId.value = draft.value.slides[Math.min(index, draft.value.slides.length - 1)].id
}

function moveSlide(offset) {
  if (!editing.value) return
  const from = selectedSlideIndex.value
  const to = from + offset
  if (from < 0 || to < 0 || to >= draft.value.slides.length) return
  const [item] = draft.value.slides.splice(from, 1)
  draft.value.slides.splice(to, 0, item)
}

function bulletText(slide) {
  return slide?.bullets?.join('\n') || ''
}

function updateBullets(event) {
  if (!selectedSlide.value) return
  selectedSlide.value.bullets = event.target.value
    .split('\n')
    .map(item => item.trim())
    .filter(Boolean)
    .slice(0, 16)
}

function sourceChecked(sourceRefId) {
  return selectedSlide.value?.sourceRefIds?.includes(sourceRefId) === true
}

function toggleSource(sourceRefId) {
  if (!editing.value || !selectedSlide.value) return
  const ids = selectedSlide.value.sourceRefIds || (selectedSlide.value.sourceRefIds = [])
  const index = ids.indexOf(sourceRefId)
  if (index >= 0) ids.splice(index, 1)
  else ids.push(sourceRefId)
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
      content: JSON.stringify(draft.value),
      content_format: 'json',
    })
    detail.value = payload
    courseContext.clear({ keepCourse: true })
    selectedVersionId.value = payload.deck?.current_version_id || payload.current_version_id
    editing.value = false
    draft.value = null
    notice.value = '新版本已保存，原课件仍可在版本历史中查看。'
    await nextTick()
    selectFirstSlide()
  } catch (exception) {
    actionError.value = exception?.status === 409
      ? '课件已在别处更新。你的草稿仍保留，请刷新版本状态后再次保存。'
      : message(exception, '保存失败，当前课件和编辑草稿均已保留。')
  } finally {
    saving.value = false
  }
}

async function refreshAfterConflict() {
  await loadResource({ preserveVersion: true, preserveDraft: true })
  actionError.value = ''
}

function safeFilename(value) {
  return String(value || 'EduMatrix-courseware').replace(/[\\/:*?"<>|]+/g, '-').slice(0, 80)
}

async function exportVersion(format) {
  if (exporting.value || !selectedVersion.value || projection.value?.mode !== 'structured') return
  exporting.value = format
  actionError.value = ''
  notice.value = ''
  try {
    const blob = await exportM5Deck(resourceId.value, format, selectedVersion.value.id)
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `${safeFilename(title.value)}-${versionLabel.value}.${format}`
    link.click()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
    notice.value = `${format.toUpperCase()} 课件已导出。`
  } catch (exception) {
    actionError.value = message(exception, `导出 ${format.toUpperCase()} 失败，当前课件内容没有改变。`)
  } finally {
    exporting.value = ''
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
    selectedVersionId.value = detail.value.deck?.current_version_id || detail.value.current_version_id || ''
    editing.value = false
    draft.value = null
    selectFirstSlide()
    notice.value = '历史版本已恢复为新的当前版本，原版本仍保留。'
    closeHistory()
  } catch (exception) {
    historyError.value = message(exception, '恢复失败，当前课件没有改变。')
  } finally {
    restoringId.value = ''
  }
}

function openSource(source) {
  if (source?.available && source.source_document_id) {
    router.push({
      name: 'KnowledgeDocument',
      params: { documentId: source.source_document_id },
      query: {
        canonical_source_id: source.source_document_id,
        course_id: catalog.value.course?.id || route.query.course_id,
        focus_source_ref_id: source.source_ref_id,
        return_to: route.fullPath,
      },
    })
  } else if (source?.source_url?.startsWith('https://')) {
    window.open(source.source_url, '_blank', 'noopener,noreferrer')
  }
}

function askAboutSlide() {
  if (!selectedSlide.value) return
  router.push({
    name: 'Learn',
    query: {
      course_id: catalog.value.course?.id || route.query.course_id,
      resource_id: resourceId.value,
      version_id: selectedVersionId.value,
      slide_id: selectedSlide.value.id,
      context: selectedSlide.value.title,
      return_to: route.fullPath,
    },
  })
}

function goBack() {
  const target = typeof route.query.return_to === 'string'
    && route.query.return_to.startsWith('/')
    && !route.query.return_to.startsWith('//')
    ? route.query.return_to
    : { name: 'WorkspaceResources', query: { course_id: catalog.value.course?.id || route.query.course_id } }
  router.push(target)
}

watch(selectedVersionId, (versionId) => {
  if (versionId && route.query.version_id !== versionId) {
    router.replace({ query: { ...route.query, version_id: versionId } })
  }
  if (!editing.value) selectFirstSlide()
})
watch(resourceId, loadResource)
onMounted(loadResource)
</script>

<template>
  <main class="deck-page" data-testid="web-deck-workspace">
    <button type="button" class="back-link" @click="goBack"><ArrowLeft :size="17" /> 返回资源中心</button>

    <section v-if="loading" class="page-state" role="status">
      <Presentation :size="26" />
      <strong>正在打开课件</strong>
      <span>正在恢复页面大纲、来源和版本历史。</span>
    </section>

    <section v-else-if="error" class="page-state page-state--error" role="alert">
      <AlertTriangle :size="26" />
      <strong>课件暂时无法打开</strong>
      <span>{{ error }}</span>
      <button type="button" class="primary-button" @click="loadResource"><RefreshCw :size="17" /> 重新加载</button>
    </section>

    <template v-else>
      <ResourceToolbar
        :title="title"
        :type-label="`${catalog.course?.title || '当前课程'} · ${catalog.knowledge_point?.title || '当前知识点'}`"
        :version-label="versionLabel"
        status-label="查看结构化课件并按页学习"
        :history-count="historyItems.length"
        :history-disabled="!historyItems.length || editing"
        :loading="loading"
        @back="goBack"
        @history="openHistory"
        @reload="loadResource"
      />
      <header class="page-header">
        <div>
          <p class="context-line">{{ catalog.course?.title || '当前课程' }} · {{ catalog.knowledge_point?.title || '当前知识点' }}</p>
          <h1>{{ title }}</h1>
          <p>{{ summary }}</p>
        </div>
        <dl class="header-meta" aria-label="课件学习说明">
          <div><dt>现在做什么</dt><dd>按大纲阅读当前课件</dd></div>
          <div><dt>完成条件</dt><dd>按今日任务提交规定证据</dd></div>
          <div><dt>下一步</dt><dd>针对当前页面提问或返回资源中心</dd></div>
        </dl>
      </header>

      <div v-if="projection?.warnings?.length" class="notice notice--warning" role="status">
        <AlertTriangle :size="17" /> {{ projection.warnings[0] }}
      </div>
      <div v-if="notice" class="notice" role="status"><Check :size="17" /> {{ notice }}</div>
      <div v-if="actionError" class="notice notice--error" role="alert">
        <AlertTriangle :size="17" />
        <span>{{ actionError }}</span>
        <button v-if="editing" type="button" @click="refreshAfterConflict"><RefreshCw :size="16" /> 刷新版本状态</button>
      </div>
      <div v-if="!isCurrentVersion" class="notice" role="status">
        <RotateCcw :size="17" /> 正在只读查看历史版本 {{ versionLabel }}。返回当前版本后才能编辑，导出仍使用此历史版本。
      </div>

      <section v-if="projection?.mode === 'structured'" class="workspace-shell">
        <aside class="outline-pane" aria-label="课件大纲">
          <div class="pane-heading">
            <div><span>课件大纲</span><strong>{{ slides.length }} 页</strong></div>
            <button v-if="editing" type="button" title="新增页面" aria-label="新增课件页面" :disabled="slides.length >= 30" @click="addSlide"><Plus :size="17" /></button>
          </div>
          <button
            v-for="(slide, index) in slides"
            :key="slide.id"
            type="button"
            class="outline-row"
            :class="{ active: selectedSlide?.id === slide.id }"
            @click="selectedSlideId = slide.id"
          >
            <span>{{ String(index + 1).padStart(2, '0') }}</span>
            <strong>{{ slide.title }}</strong>
            <small>{{ ({ title: '封面', content: '正文', two_column: '双栏', closing: '结尾' })[slide.layout] }}</small>
          </button>
          <div v-if="editing" class="outline-tools" aria-label="页面排序">
            <button type="button" title="上移页面" aria-label="上移页面" :disabled="selectedSlideIndex <= 0" @click="moveSlide(-1)"><ArrowUp :size="17" /></button>
            <button type="button" title="下移页面" aria-label="下移页面" :disabled="selectedSlideIndex < 0 || selectedSlideIndex >= slides.length - 1" @click="moveSlide(1)"><ArrowDown :size="17" /></button>
            <button type="button" title="删除页面" aria-label="删除页面" :disabled="slides.length <= 1" @click="removeSlide"><Trash2 :size="17" /></button>
          </div>
        </aside>

        <section class="preview-pane" aria-label="课件预览与编辑">
          <div class="preview-heading">
            <div><span>课件预览</span><strong>{{ versionLabel }} · 第 {{ selectedSlideIndex + 1 }} 页</strong></div>
            <div class="preview-actions">
              <button type="button" title="上一页" aria-label="上一页" :disabled="selectedSlideIndex <= 0" @click="selectedSlideId = slides[selectedSlideIndex - 1].id"><ArrowLeft :size="17" /></button>
              <button type="button" title="下一页" aria-label="下一页" :disabled="selectedSlideIndex < 0 || selectedSlideIndex >= slides.length - 1" @click="selectedSlideId = slides[selectedSlideIndex + 1].id"><ArrowRight :size="17" /></button>
            </div>
          </div>

          <ResourceProfileAdaptation
            :summary="activeContent?.adaptationSummary || ''"
            :plan="detail?.resource?.profile_adaptation_plan"
            resource-type="deck"
          />

          <section v-if="editing" class="deck-editor-meta" aria-label="课件整体信息编辑">
            <label>课件标题<input v-model="draft.title" maxlength="256" /></label>
            <label>适配摘要<textarea v-model="draft.summary" rows="3" maxlength="1200" /></label>
            <label>学习目标<textarea v-model="draft.learningGoal" rows="3" maxlength="1200" /></label>
            <label>适配依据<textarea v-model="draft.adaptationSummary" rows="3" maxlength="1600" /></label>
          </section>

          <article v-if="selectedSlide" class="slide-stage" :class="`slide-stage--${selectedSlide.layout}`" data-testid="deck-stage">
            <span class="slide-number">{{ String(selectedSlideIndex + 1).padStart(2, '0') }}</span>
            <div class="slide-copy">
              <h2>{{ selectedSlide.title }}</h2>
              <h3 v-if="selectedSlide.subtitle">{{ selectedSlide.subtitle }}</h3>
              <p v-if="selectedSlide.body">{{ selectedSlide.body }}</p>
              <ul v-if="selectedSlide.bullets?.length"><li v-for="bullet in selectedSlide.bullets" :key="bullet">{{ bullet }}</li></ul>
            </div>
            <footer><span>{{ catalog.knowledge_point?.title || '当前知识点' }}</span><span>EduMatrix · {{ versionLabel }}</span></footer>
          </article>

          <section v-if="editing && selectedSlide" class="slide-editor" aria-label="课件页面编辑器">
            <div class="editor-grid">
              <label>页面标题<input v-model="selectedSlide.title" maxlength="256" /></label>
              <label>版式<select v-model="selectedSlide.layout"><option value="title">封面</option><option value="content">正文</option><option value="two_column">双栏</option><option value="closing">结尾</option></select></label>
              <label class="wide">副标题<input v-model="selectedSlide.subtitle" maxlength="512" /></label>
              <label class="wide">正文<textarea v-model="selectedSlide.body" rows="4" maxlength="8000" /></label>
              <label class="wide">要点，每行一条<textarea :value="bulletText(selectedSlide)" rows="5" @input="updateBullets" /></label>
              <label class="wide">讲者备注<textarea v-model="selectedSlide.speakerNotes" rows="4" maxlength="8000" /></label>
            </div>
            <fieldset class="source-picker">
              <legend>本页来源</legend>
              <label v-for="source in sources" :key="source.source_ref_id">
                <input type="checkbox" :checked="sourceChecked(source.source_ref_id)" @change="toggleSource(source.source_ref_id)" />
                <span>{{ source.title || '课程来源' }} · {{ source.location_label || '位置未记录' }}</span>
              </label>
              <p v-if="!sources.length">当前资源没有登记可选择的课程来源。</p>
            </fieldset>
          </section>

          <div v-if="selectedSlide" class="speaker-note">
            <span>讲者备注</span><p>{{ selectedSlide.speakerNotes || '当前页面没有讲者备注。' }}</p>
          </div>
          <p class="evidence-boundary">翻页、查看来源、编辑和导出不会自动改变掌握度，也不会直接解锁智能组卷。</p>
        </section>

        <aside class="detail-pane" aria-label="来源与版本">
          <section class="detail-section detail-section--lead">
            <div class="section-heading"><span>来源与版本</span><ShieldCheck :size="17" /></div>
            <label class="version-control">
              <span>课件版本</span>
              <select v-model="selectedVersionId" aria-label="选择课件版本" :disabled="editing">
                <option v-for="version in versions" :key="version.id" :value="version.id">v{{ version.number }} · {{ version.projection?.outline?.length || 0 }} 页</option>
              </select>
              <ChevronDown :size="15" aria-hidden="true" />
            </label>
            <p>{{ projection.source_readiness?.reason }}</p>
          </section>

          <section class="detail-section learning-context">
            <span>学习目标</span>
            <dl>
              <div><dt>学习目标</dt><dd>{{ activeContent?.learningGoal || '当前课件未登记学习目标。' }}</dd></div>
            </dl>
          </section>

          <section class="detail-section">
            <span>课程来源</span>
            <button
              v-for="source in sources"
              :key="source.source_ref_id"
              type="button"
              class="source-row"
              :disabled="!source.available && !source.source_url"
              @click="openSource(source)"
            >
              <BookOpen :size="16" />
              <span><strong>{{ source.title || '课程来源' }}</strong><small>{{ source.location_label || '位置未记录' }}</small><small>{{ source.license || '许可说明未记录' }}</small></span>
              <ExternalLink :size="15" />
            </button>
            <p v-if="!sources.length" class="empty-copy">当前课件没有登记来源，因此只能作为未发布草稿查看。</p>
          </section>

          <section class="detail-section action-section">
            <span>编辑与导出</span>
            <template v-if="editing">
              <button type="button" class="primary-button" :disabled="saving" @click="saveVersion"><Save :size="17" /> {{ saving ? '正在保存' : '保存为新版本' }}</button>
              <button type="button" @click="cancelEditing"><X :size="17" /> 取消编辑</button>
            </template>
            <button v-else type="button" :disabled="!canEdit" @click="startEditing"><Pencil :size="17" /> 编辑当前版本</button>
            <button type="button" :disabled="Boolean(exporting)" @click="exportVersion('html')"><Download :size="17" /> {{ exporting === 'html' ? '正在导出' : '导出 HTML' }}</button>
            <button type="button" :disabled="Boolean(exporting)" @click="exportVersion('pptx')"><Download :size="17" /> {{ exporting === 'pptx' ? '正在导出' : '导出 PPTX' }}</button>
            <button type="button" :disabled="!selectedSlide" @click="askAboutSlide"><MessageSquareText :size="17" /> 针对此页提问</button>
            <button type="button" @click="goBack"><RotateCcw :size="17" /> 返回资源中心重新生成</button>
            <p v-if="!canEdit && !editing">历史版本和损坏版本保持只读；编辑请切换到当前有效版本。</p>
          </section>
        </aside>
      </section>

      <section v-else class="page-state page-state--document" role="status">
        <Presentation :size="28" />
        <strong>{{ projection?.mode === 'invalid_structured' ? '当前课件结构无法解析' : '这是旧版课件说明' }}</strong>
        <span>{{ projection?.source_readiness?.reason || '请选择其他有效版本，或返回资源中心重新生成课件。' }}</span>
        <label class="fallback-version">
          <span>查看其他版本</span>
          <select v-model="selectedVersionId"><option v-for="version in versions" :key="version.id" :value="version.id">v{{ version.number }}</option></select>
        </label>
      </section>
    </template>

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
.deck-page{min-height:100%;padding:24px 28px 32px;background:var(--color-page);color:var(--color-text);font-family:var(--font-sans);letter-spacing:0}.back-link{display:inline-flex;align-items:center;gap:8px;margin:0 0 18px;padding:0;border:0;background:transparent;color:var(--color-text-secondary);font-size:14px;font-weight:650;cursor:pointer}.back-link:hover{color:var(--color-text)}
.page-header{display:grid;grid-template-columns:minmax(0,1fr) minmax(500px,.9fr);gap:36px;align-items:end;padding-bottom:22px;border-bottom:1px solid var(--color-border)}.context-line{margin:0 0 6px;color:var(--color-text-secondary);font-size:14px;font-weight:650}.page-header h1{margin:0;font-family:var(--font-heading);font-size:34px;line-height:1.25;letter-spacing:0}.page-header>div>p:last-child{max-width:70ch;margin:9px 0 0;color:var(--color-text-secondary);font-size:15px;line-height:1.65}.header-meta{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));margin:0;border:1px solid var(--color-border);border-radius:8px;background:#fff}.header-meta div{min-width:0;padding:13px 14px}.header-meta div+div{border-left:1px solid var(--color-border)}.header-meta dt{color:var(--color-text-muted);font-size:14px}.header-meta dd{margin:4px 0 0;font-size:14px;font-weight:700;line-height:1.45}
.notice{display:flex;align-items:center;gap:8px;margin:14px 0 0;padding:11px 13px;border:1px solid var(--color-border);border-radius:6px;background:#fff;color:var(--color-text-secondary);font-size:14px;line-height:1.5}.notice--warning{border-color:#e7d2a8;background:var(--color-warning-soft);color:#604429}.notice--error{border-color:#e6caca;background:var(--color-danger-soft);color:var(--color-danger)}.notice span{flex:1}.notice button{display:inline-flex;align-items:center;gap:6px;border:0;background:transparent;color:inherit;font:650 14px/1.3 var(--font-sans);cursor:pointer}
.workspace-shell{display:grid;grid-template-columns:minmax(184px,19fr) minmax(470px,53fr) minmax(244px,28fr);min-height:650px;margin-top:16px;border:1px solid var(--color-border);border-radius:8px;background:#fff;overflow:hidden}.outline-pane,.detail-pane{min-width:0;background:#fff}.outline-pane{border-right:1px solid var(--color-border)}.detail-pane{border-left:1px solid var(--color-border)}.pane-heading,.preview-heading,.section-heading{display:flex;align-items:center;justify-content:space-between;gap:12px}.pane-heading{min-height:64px;padding:13px 14px;border-bottom:1px solid var(--color-border)}.pane-heading>div,.preview-heading>div{display:grid;gap:3px}.pane-heading span,.preview-heading span,.detail-section>span,.section-heading span,.speaker-note>span{color:var(--color-text-muted);font-size:14px}.pane-heading strong,.preview-heading strong{font-size:14px}.pane-heading>button,.preview-actions button,.outline-tools button{display:inline-flex;width:36px;height:36px;align-items:center;justify-content:center;border:1px solid var(--color-border-strong);border-radius:6px;background:#fff;color:var(--color-text);cursor:pointer}.pane-heading button:disabled,.preview-actions button:disabled,.outline-tools button:disabled{opacity:.38;cursor:not-allowed}
.outline-row{display:grid;grid-template-columns:30px minmax(0,1fr);gap:4px 8px;width:100%;min-height:68px;padding:11px 12px;border:0;border-bottom:1px solid var(--color-border);background:#fff;color:var(--color-text);text-align:left;cursor:pointer}.outline-row:hover{background:var(--color-surface-subtle)}.outline-row.active{background:var(--color-accent-soft);box-shadow:inset 3px 0 0 var(--color-accent)}.outline-row>span{grid-row:1/3;color:var(--color-text-muted);font-size:14px;font-variant-numeric:tabular-nums}.outline-row strong{min-width:0;font-size:14px;line-height:1.45;overflow-wrap:anywhere}.outline-row small{color:var(--color-text-muted);font-size:14px}.outline-tools{display:flex;gap:7px;padding:12px;border-top:1px solid var(--color-border)}
  .preview-pane{min-width:0;padding:16px 18px 20px;background:var(--color-surface-subtle)}.preview-heading{min-height:42px;margin-bottom:12px}.preview-actions{display:flex;gap:7px}.slide-stage{position:relative;display:grid;box-sizing:border-box;width:100%;aspect-ratio:16/9;grid-template-rows:minmax(0,1fr) auto;gap:10px;align-items:stretch;padding:5% 7.5% 4%;overflow:hidden;border:1px solid var(--color-border-strong);border-radius:6px;background:#fff;box-shadow:0 14px 30px rgb(6 20 27 / 9%)}.slide-copy{align-self:center;box-sizing:border-box;min-width:0;max-height:100%;width:min(88%,850px);padding-right:4px;overflow:auto}.slide-stage h2{max-width:18ch;margin:0;font-family:var(--font-display);font-size:32px;line-height:1.18;letter-spacing:0}.slide-stage h3{max-width:42ch;margin:10px 0 0;color:var(--color-text-secondary);font-size:18px;font-weight:550;line-height:1.4}.slide-stage p,.slide-stage li{font-size:16px;line-height:1.5}.slide-stage p{max-width:62ch;margin:16px 0 0}.slide-stage ul{display:grid;gap:6px;max-width:62ch;margin:14px 0 0;padding-left:1.2em}.slide-number{position:absolute;top:5%;right:5%;color:var(--color-text-muted);font-size:14px;font-variant-numeric:tabular-nums}.slide-stage footer{display:flex;min-width:0;align-items:center;justify-content:space-between;gap:24px;color:var(--color-text-muted);font-size:14px}.slide-stage--title .slide-copy,.slide-stage--closing .slide-copy{margin:auto;text-align:center}.slide-stage--title h2,.slide-stage--closing h2{max-width:22ch;margin-inline:auto}.slide-stage--title h3,.slide-stage--closing h3,.slide-stage--title p,.slide-stage--closing p{margin-inline:auto}.slide-stage--two_column .slide-copy{display:grid;grid-template-columns:1fr 1fr;column-gap:8%;width:100%;max-width:none}.slide-stage--two_column h2,.slide-stage--two_column h3{grid-column:1/-1}.slide-stage--two_column p{grid-column:1}.slide-stage--two_column ul{grid-column:2;grid-row:3}
.slide-editor{margin-top:14px;padding:16px;border:1px solid var(--color-border);border-radius:8px;background:#fff}.editor-grid{display:grid;grid-template-columns:minmax(0,1fr) 180px;gap:12px}.editor-grid label,.source-picker label,.version-control,.fallback-version{display:grid;gap:6px;color:var(--color-text-secondary);font-size:14px;font-weight:650}.editor-grid .wide{grid-column:1/-1}.editor-grid input,.editor-grid select,.editor-grid textarea,.version-control select,.fallback-version select{box-sizing:border-box;width:100%;min-height:40px;padding:9px 10px;border:1px solid var(--color-border-strong);border-radius:6px;background:#fff;color:var(--color-text);font:14px/1.55 var(--font-sans);letter-spacing:0}.editor-grid textarea{resize:vertical}.editor-grid input:focus,.editor-grid select:focus,.editor-grid textarea:focus,.version-control select:focus{border-color:var(--color-accent);outline:2px solid rgb(17 33 45 / 10%)}.source-picker{display:grid;gap:8px;margin:14px 0 0;padding:13px;border:1px solid var(--color-border);border-radius:6px}.source-picker legend{padding:0 5px;font-size:14px;font-weight:700}.source-picker label{grid-template-columns:auto 1fr;align-items:start;font-weight:500;line-height:1.5}.source-picker input{width:16px;height:16px;margin:2px 0 0;accent-color:var(--color-accent)}.source-picker p{margin:0;color:var(--color-text-muted);font-size:14px}
.deck-editor-meta{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:12px;margin:0 0 14px;padding:15px;border:1px solid var(--color-border);border-radius:8px;background:#fff}.deck-editor-meta label{display:grid;gap:6px;color:var(--color-text-secondary);font-size:14px;font-weight:650}.deck-editor-meta input,.deck-editor-meta textarea{box-sizing:border-box;width:100%;min-height:40px;padding:9px 10px;border:1px solid var(--color-border-strong);border-radius:6px;background:#fff;color:var(--color-text);font:14px/1.55 var(--font-sans);letter-spacing:0}.deck-editor-meta textarea{resize:vertical}.deck-editor-meta input:focus,.deck-editor-meta textarea:focus{border-color:var(--color-accent);outline:2px solid rgb(17 33 45 / 10%)}
.learning-context dl{display:grid;gap:10px;margin:11px 0 0}.learning-context dl>div{padding:10px 0;border-top:1px solid var(--color-border)}.learning-context dt{color:var(--color-text-muted);font-size:14px}.learning-context dd{margin:4px 0 0;color:var(--color-text-secondary);font-size:14px;line-height:1.6;overflow-wrap:anywhere}
.speaker-note{margin-top:14px;padding:13px 15px;border:1px solid var(--color-border);border-radius:6px;background:#fff}.speaker-note p{margin:6px 0 0;color:var(--color-text-secondary);font-size:14px;line-height:1.6}.evidence-boundary{margin:14px 0 0;color:var(--color-text-muted);font-size:14px;line-height:1.55}
.detail-pane{padding:15px}.detail-section{padding:0 0 16px}.detail-section+.detail-section{padding-top:16px;border-top:1px solid var(--color-border)}.detail-section p{margin:9px 0 0;color:var(--color-text-secondary);font-size:14px;line-height:1.6}.version-control{position:relative;margin-top:12px}.version-control select{padding-right:34px;appearance:none}.version-control svg{position:absolute;right:10px;bottom:12px;pointer-events:none}.source-row{display:grid;grid-template-columns:auto minmax(0,1fr) auto;align-items:start;gap:9px;width:100%;margin-top:9px;padding:10px;border:1px solid var(--color-border);border-radius:6px;background:#fff;color:var(--color-text);text-align:left;cursor:pointer}.source-row:hover:not(:disabled){border-color:var(--color-border-strong);background:var(--color-surface-subtle)}.source-row:disabled{opacity:.58;cursor:not-allowed}.source-row>span{display:grid;gap:3px;min-width:0}.source-row strong{font-size:14px;line-height:1.4}.source-row small{color:var(--color-text-muted);font-size:14px;line-height:1.4;overflow-wrap:anywhere}.empty-copy{color:var(--color-text-muted)!important}.action-section{display:grid;gap:8px}.action-section>button,.primary-button{display:inline-flex;min-height:40px;align-items:center;justify-content:center;gap:7px;padding:0 12px;border:1px solid var(--color-border-strong);border-radius:6px;background:#fff;color:var(--color-text);font:650 14px/1.3 var(--font-sans);cursor:pointer}.action-section>button:not(.primary-button):hover:not(:disabled){background:var(--color-surface-subtle)}.action-section>button:disabled{opacity:.45;cursor:not-allowed}.action-section .primary-button,.primary-button{border-color:var(--color-accent);background:var(--color-accent);color:#fff}.action-section .primary-button:hover:not(:disabled),.primary-button:hover:not(:disabled){background:var(--color-accent)}.action-section>span{margin-bottom:2px}
.page-state{display:grid;min-height:560px;place-items:center;align-content:center;gap:8px;border:1px solid var(--color-border);border-radius:8px;background:#fff;text-align:center}.page-state strong{font-size:18px}.page-state>span{max-width:62ch;color:var(--color-text-secondary);font-size:15px;line-height:1.6}.page-state .primary-button{margin-top:8px}.page-state--error svg{color:var(--color-danger)}.page-state--document{margin-top:16px}.fallback-version{width:min(320px,100%);margin-top:12px;text-align:left}
button:focus-visible,select:focus-visible,input:focus-visible,textarea:focus-visible{outline:3px solid rgb(17 33 45 / 22%);outline-offset:2px}::selection{background:#d5dcde;color:#06141b}
  @media (max-width:1380px){.deck-page{padding:20px 22px 28px}.page-header{grid-template-columns:minmax(0,1fr) 520px;gap:24px}.workspace-shell{grid-template-columns:minmax(176px,18fr) minmax(450px,55fr) minmax(230px,27fr)}.preview-pane{padding:14px}.detail-pane{padding:13px}.slide-stage h2{font-size:30px}}
  .deck-page > .back-link,
  .deck-page > .page-header { display: none; }
</style>
