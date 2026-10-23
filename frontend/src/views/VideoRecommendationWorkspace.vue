<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  AlertTriangle,
  ArrowLeft,
  BookOpen,
  Check,
  ChevronDown,
  Clock3,
  ExternalLink,
  FileVideo2,
  Languages,
  Link2,
  MessageSquareText,
  NotebookPen,
  Play,
  RefreshCw,
  RotateCcw,
  ShieldCheck,
} from '@lucide/vue'
import ResourceHistoryDrawer from '../components/ResourceHistoryDrawer.vue'
import ResourceToolbar from '../components/ResourceToolbar.vue'
import ResourceFloatingQa from '../components/ResourceFloatingQa.vue'
import ResourceProfileAdaptation from '../components/ResourceProfileAdaptation.vue'
import { compareM5ResourceVersions, getM5Resource, getM5VideoMedia, restoreM5ResourceVersion } from '../api/m5'

const route = useRoute()
const router = useRouter()
const loading = ref(true)
const mediaLoading = ref(false)
const error = ref('')
const mediaError = ref('')
const notice = ref('')
const detail = ref(null)
const selectedVersionId = ref('')
const selectedRecommendationId = ref('')
const selectedSegmentId = ref('')
const noteDraft = ref('')
const noteSaved = ref(false)
const videoElement = ref(null)
const mediaUrl = ref('')
const embeddedSourceUrl = ref('')
const embeddedSourceLabel = ref('')
const autoplayOnMetadata = ref(false)
const restoringContext = ref(false)
const historyOpen = ref(false)
const historyError = ref('')
const restoringId = ref('')
const comparingId = ref('')
const compareResult = ref(null)
const qaOpen = ref(false)

const resourceId = computed(() => String(route.params.resourceId || ''))
const workspace = computed(() => detail.value?.video || {})
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
const catalog = computed(() => detail.value?.catalog || {})
const recommendations = computed(() => structured.value?.recommendations || [])
const selectedRecommendation = computed(() => (
  recommendations.value.find(item => item.id === selectedRecommendationId.value)
  || recommendations.value[0]
  || null
))
const selectedSegment = computed(() => (
  selectedRecommendation.value?.segments?.find(item => item.id === selectedSegmentId.value)
  || null
))
const sources = computed(() => projection.value?.source_refs || [])
const title = computed(() => structured.value?.title || projection.value?.legacy?.title || catalog.value.title || '视频推荐')
const summary = computed(() => structured.value?.summary || '查看与当前知识点相关、来源边界明确的视频资源。')
const isCurrentVersion = computed(() => selectedVersion.value?.id === currentVersionId.value)
const versionLabel = computed(() => selectedVersion.value ? `v${selectedVersion.value.number}` : '未记录')
const playable = computed(() => selectedRecommendation.value?.playback?.available === true)
const externalOnly = computed(() => selectedRecommendation.value?.playback?.external_only === true)
const embeddedUrl = computed(() => toEmbeddedPlayerUrl(
  embeddedSourceUrl.value || (externalOnly.value ? selectedRecommendation.value?.url : ''),
))
const embeddedTitle = computed(() => embeddedSourceLabel.value || selectedRecommendation.value?.title || '视频来源')
const durationLabel = computed(() => {
  const seconds = selectedRecommendation.value?.durationSeconds
  if (!seconds) return '来源未提供可验证时长'
  const minutes = Math.floor(seconds / 60)
  const rest = seconds % 60
  return `${minutes}:${String(rest).padStart(2, '0')}`
})

function message(exception, fallback) {
  const detailMessage = exception?.response?.data?.detail?.message || exception?.detail?.message
  return detailMessage || (typeof exception?.detail === 'string' ? exception.detail : '') || exception?.message || fallback
}

function queryValue(name) {
  return typeof route.query[name] === 'string' ? route.query[name] : ''
}

function toEmbeddedPlayerUrl(rawUrl) {
  const url = String(rawUrl || '').trim()
  if (!/^https:\/\//i.test(url)) return ''
  const lower = url.toLowerCase()

  if (lower.includes('bilibili.com') || lower.includes('b23.tv')) {
    const bvid = url.match(/(BV[a-zA-Z0-9]{10})/i)?.[1]
    if (bvid) return `https://player.bilibili.com/player.html?bvid=${bvid}&high_quality=1&as_wide=1`
    const avid = url.match(/\/av(\d+)/i)?.[1]
    if (avid) return `https://player.bilibili.com/player.html?aid=${avid}&high_quality=1&as_wide=1`
  }

  if (lower.includes('youtube.com') || lower.includes('youtu.be')) {
    const youtubeId = url.match(/(?:v=|\/embed\/|\/watch\?v=|youtu\.be\/)([a-zA-Z0-9_-]{11})/)?.[1]
    if (youtubeId) return `https://www.youtube.com/embed/${youtubeId}`
  }

  if (lower.includes('v.qq.com')) {
    const qqId = url.match(/\/(?:cover|page)\/(?:[^/]+\/)*([a-zA-Z0-9_-]+)\.html/i)?.[1]
      || url.match(/\/([a-zA-Z0-9_-]+)\.html/i)?.[1]
    if (qqId) return `https://v.qq.com/txp/iframe/player.html?vid=${qqId}`
  }

  if (lower.includes('youku.com')) {
    const youkuId = url.match(/id_([a-zA-Z0-9_=-]+)\.html/i)?.[1]
    if (youkuId) return `https://player.youku.com/embed/${youkuId}`
  }

  // 普通 HTTPS 视频页也留在当前工作区内加载；若来源禁止 iframe，会显示其真实受限状态。
  return url
}

async function syncSelectionQuery() {
  const query = { ...route.query }
  if (selectedVersionId.value) query.version_id = selectedVersionId.value
  else delete query.version_id
  if (selectedRecommendationId.value) query.recommendation_id = selectedRecommendationId.value
  else delete query.recommendation_id
  if (selectedSegmentId.value) query.segment_id = selectedSegmentId.value
  else delete query.segment_id
  if (
    query.version_id !== route.query.version_id
    || query.recommendation_id !== route.query.recommendation_id
    || query.segment_id !== route.query.segment_id
  ) {
    await router.replace({ query })
  }
}

function noteKey() {
  return [
    'edumatrix-video-note', resourceId.value, selectedVersionId.value,
    selectedRecommendation.value?.id || 'empty', selectedSegmentId.value || 'whole',
  ].join(':')
}

function restoreNote() {
  noteDraft.value = localStorage.getItem(noteKey()) || ''
  noteSaved.value = Boolean(noteDraft.value)
}

function saveNote() {
  localStorage.setItem(noteKey(), noteDraft.value)
  noteSaved.value = true
  notice.value = '学习笔记草稿已保存在当前浏览器。'
}

function clearMedia() {
  autoplayOnMetadata.value = false
  if (mediaUrl.value) URL.revokeObjectURL(mediaUrl.value)
  mediaUrl.value = ''
  mediaError.value = ''
}

function clearEmbeddedSource() {
  embeddedSourceUrl.value = ''
  embeddedSourceLabel.value = ''
}

function applySelectedSegmentPosition() {
  const video = videoElement.value
  const segment = selectedSegment.value
  if (!video || !segment) return
  video.currentTime = segment.startSeconds
  if (autoplayOnMetadata.value) {
    autoplayOnMetadata.value = false
    void video.play().catch(() => {})
  }
}

async function loadMedia() {
  clearMedia()
  if (!resourceId.value || !playable.value || !selectedRecommendation.value) return
  mediaLoading.value = true
  try {
    const blob = await getM5VideoMedia(
      resourceId.value,
      selectedRecommendation.value.id,
      selectedVersionId.value,
    )
    mediaUrl.value = URL.createObjectURL(blob)
  } catch (exception) {
    mediaError.value = message(exception, '视频文件暂时无法读取，请使用替代来源。')
  } finally {
    mediaLoading.value = false
  }
}

async function loadResource({ preserveVersion = false } = {}) {
  restoringContext.value = true
  loading.value = true
  error.value = ''
  notice.value = ''
  try {
    const payload = await getM5Resource(resourceId.value)
    if (payload?.catalog?.type !== 'video' || !payload.video) throw new Error('当前资源不是视频推荐。')
    detail.value = payload
    const keep = preserveVersion && versions.value.some(item => item.id === selectedVersionId.value)
    const requestedVersionId = queryValue('version_id')
    if (!keep) {
      selectedVersionId.value = versions.value.some(item => item.id === requestedVersionId)
        ? requestedVersionId
        : payload.video.current_version_id || payload.video.versions?.at(-1)?.id || ''
    }
    const requestedRecommendationId = queryValue('recommendation_id')
    selectedRecommendationId.value = recommendations.value.some(item => item.id === requestedRecommendationId)
      ? requestedRecommendationId
      : recommendations.value[0]?.id || ''
    const requestedSegmentId = queryValue('segment_id')
    selectedSegmentId.value = selectedRecommendation.value?.segments?.some(item => item.id === requestedSegmentId)
      ? requestedSegmentId
      : selectedRecommendation.value?.segments?.[0]?.id || ''
    await syncSelectionQuery()
    restoreNote()
    await loadMedia()
  } catch (exception) {
    error.value = message(exception, '视频推荐加载失败，请稍后重试。')
  } finally {
    loading.value = false
    restoringContext.value = false
  }
}

function selectRecommendation(item) {
  selectedRecommendationId.value = item.id
  selectedSegmentId.value = item.segments?.[0]?.id || ''
  clearEmbeddedSource()
}

async function jumpToSegment(segment) {
  selectedSegmentId.value = segment.id
  if (!playable.value) return
  await nextTick()
  autoplayOnMetadata.value = true
  if (videoElement.value?.readyState >= 1) applySelectedSegmentPosition()
}

function openInAppSource(url, label = '来源') {
  if (!/^https:\/\//i.test(String(url || '').trim())) {
    notice.value = '该来源地址不可用，系统没有打开外部页面。'
    return
  }
  embeddedSourceUrl.value = String(url).trim()
  embeddedSourceLabel.value = label
  notice.value = `${label}已在当前页面打开。若来源禁止嵌入，请更换推荐来源。`
}

function closeEmbeddedSource() {
  clearEmbeddedSource()
  notice.value = ''
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
  } else if (source?.source_url) openInAppSource(source.source_url, '课程来源')
}

function openNotebook() {
  router.push({
    name: 'Notes',
    query: {
      course_id: catalog.value.course?.id || route.query.course_id,
      resource_id: resourceId.value,
      version_id: selectedVersionId.value,
      recommendation_id: selectedRecommendation.value?.id || undefined,
      segment_id: selectedSegmentId.value || undefined,
      search: selectedRecommendation.value?.title || title.value,
    },
  })
}

function askAboutVideo() {
  if (!selectedRecommendation.value) return
  qaOpen.value = true
}

function goBack() {
  const target = typeof route.query.return_to === 'string'
    && route.query.return_to.startsWith('/')
    && !route.query.return_to.startsWith('//')
    ? route.query.return_to
    : { name: 'WorkspaceResources', query: { course_id: catalog.value.course?.id || route.query.course_id } }
  router.push(target)
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
  if (restoringId.value || versionId === currentVersionId.value) return
  restoringId.value = versionId
  historyError.value = ''
  try {
    await restoreM5ResourceVersion(resourceId.value, {
      expected_lock_version: detail.value.lock_version,
      version_id: versionId,
    })
    closeHistory()
    await loadResource()
    notice.value = '历史版本已恢复为新的当前版本，原版本仍保留。'
  } catch (exception) {
    historyError.value = message(exception, '恢复失败，当前视频推荐没有改变。')
  } finally {
    restoringId.value = ''
  }
}

watch(selectedVersionId, async () => {
  if (restoringContext.value) return
  selectedRecommendationId.value = recommendations.value[0]?.id || ''
  selectedSegmentId.value = recommendations.value[0]?.segments?.[0]?.id || ''
  clearEmbeddedSource()
  await syncSelectionQuery()
  restoreNote()
  await loadMedia()
})

watch(selectedRecommendationId, async () => {
  if (restoringContext.value) return
  if (!selectedRecommendation.value?.segments?.some(item => item.id === selectedSegmentId.value)) {
    selectedSegmentId.value = selectedRecommendation.value?.segments?.[0]?.id || ''
  }
  clearEmbeddedSource()
  await syncSelectionQuery()
  restoreNote()
  await loadMedia()
})

watch(selectedSegmentId, async () => {
  if (restoringContext.value) return
  await syncSelectionQuery()
  restoreNote()
})
watch(noteDraft, () => { noteSaved.value = false })
watch(resourceId, loadResource)
onMounted(loadResource)
onBeforeUnmount(clearMedia)
</script>

<template>
  <main class="video-page" data-testid="video-recommendation-workspace">
    <button type="button" class="back-link" @click="goBack">
      <ArrowLeft :size="17" /> 返回资源中心
    </button>

    <section v-if="loading" class="page-state" role="status">
      <FileVideo2 :size="25" />
      <strong>正在打开视频推荐</strong>
      <span>正在恢复推荐来源、许可说明和笔记草稿。</span>
    </section>

    <section v-else-if="error" class="page-state page-state--error" role="alert">
      <AlertTriangle :size="25" />
      <strong>视频推荐暂时无法打开</strong>
      <span>{{ error }}</span>
      <button type="button" class="primary-button" @click="loadResource"><RefreshCw :size="17" /> 重新加载</button>
    </section>

    <template v-else>
      <ResourceToolbar
        :title="title"
        :type-label="`${catalog.course?.title || '当前课程'} · ${catalog.knowledge_point?.title || '当前知识点'}`"
        :version-label="versionLabel"
        status-label="选择可信来源并观看"
        :history-count="historyItems.length"
        :history-disabled="!historyItems.length"
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
        <div class="header-meta" aria-label="视频学习说明">
          <div><span>现在做什么</span><strong>选择可信来源并观看</strong></div>
          <div><span>完成条件</span><strong>按今日任务提交规定证据</strong></div>
          <div><span>下一步</span><strong>记录要点或返回资源中心</strong></div>
        </div>
      </header>

      <div v-if="projection?.warnings?.length" class="notice notice--warning" role="status">
        <AlertTriangle :size="17" /> {{ projection.warnings[0] }}
      </div>
      <div v-if="notice" class="notice" role="status"><Check :size="17" /> {{ notice }}</div>
      <div v-if="!isCurrentVersion" class="notice" role="status">
        <RotateCcw :size="17" /> 当前查看历史版本 {{ versionLabel }}，观看和记笔记不会改变当前资源版本或学习状态。
      </div>

      <section class="workspace-shell">
        <aside class="recommendation-pane" aria-label="视频推荐列表">
          <div class="pane-heading">
            <div><span>推荐列表</span><strong>{{ recommendations.length }} 条来源</strong></div>
            <label class="version-control">
              <span>版本</span>
              <select v-model="selectedVersionId" aria-label="选择视频推荐版本">
                <option v-for="version in versions" :key="version.id" :value="version.id">v{{ version.number }}</option>
              </select>
              <ChevronDown :size="15" aria-hidden="true" />
            </label>
          </div>
          <button
            v-for="(item, index) in recommendations"
            :key="item.id"
            type="button"
            class="recommendation-row"
            :class="{ active: selectedRecommendation?.id === item.id }"
            @click="selectRecommendation(item)"
          >
            <span class="row-index">{{ String(index + 1).padStart(2, '0') }}</span>
            <span class="row-copy">
              <strong>{{ item.title }}</strong>
              <small>{{ item.author }}</small>
              <em>{{ item.availability === 'playable' ? '站内播放' : item.availability === 'external_only' ? '站内嵌入' : '暂不可用' }}</em>
            </span>
          </button>
          <div v-if="!recommendations.length" class="empty-list">
            <FileVideo2 :size="24" />
            <strong>暂无可核验的视频来源</strong>
            <span>系统不会生成或伪造视频文件。请稍后重试或使用其他学习资源。</span>
          </div>
        </aside>

        <section class="player-pane" aria-label="视频播放与分段">
          <template v-if="selectedRecommendation">
            <div class="player-stage">
              <div v-if="mediaLoading" class="player-state" role="status">
                <RefreshCw class="spin" :size="25" />
                <strong>正在读取已登记视频</strong>
                <span>播放器准备完成后将保留当前分段。</span>
              </div>
              <video
                v-else-if="mediaUrl"
                ref="videoElement"
                :src="mediaUrl"
                controls
                preload="metadata"
                data-testid="video-player"
                @loadedmetadata="applySelectedSegmentPosition"
              />
              <iframe
                v-else-if="embeddedUrl"
                :src="embeddedUrl"
                :title="`${embeddedTitle}（站内播放）`"
                class="embedded-player"
                data-testid="embedded-video-player"
                allow="autoplay; encrypted-media; picture-in-picture"
                allowfullscreen
                sandbox="allow-scripts allow-same-origin allow-forms allow-presentation"
                referrerpolicy="no-referrer"
              />
              <div v-else class="player-state" :class="{ 'player-state--error': mediaError }">
                <AlertTriangle v-if="mediaError" :size="25" />
                <Link2 v-else-if="externalOnly" :size="25" />
                <FileVideo2 v-else :size="25" />
                <strong>{{ mediaError ? '站内视频暂时不可读取' : externalOnly ? '该来源暂不允许站内嵌入' : '当前来源不可播放' }}</strong>
                <span>{{ mediaError || (externalOnly ? '系统已尝试在当前页面嵌入该来源；若平台禁止嵌入，请更换推荐来源。' : selectedRecommendation.playback?.reason || '请更换一个可在系统内播放的来源。') }}</span>
                <button
                  v-if="selectedRecommendation.url"
                  type="button"
                  class="primary-button primary-button--auto"
                  @click="openInAppSource(selectedRecommendation.url, '视频来源')"
                >
                  <Link2 :size="17" /> 打开来源（站内）
                </button>
              </div>
              <button
                v-if="embeddedSourceUrl"
                type="button"
                class="embedded-close"
                @click="closeEmbeddedSource"
              >
                <RotateCcw :size="15" /> 返回视频推荐
              </button>
            </div>

            <div class="player-title">
              <div><span>{{ versionLabel }} · {{ selectedRecommendation.language }}</span><h2>{{ selectedRecommendation.title }}</h2></div>
              <div><Clock3 :size="17" /><span>{{ durationLabel }}</span></div>
            </div>

            <ResourceProfileAdaptation
              :summary="structured?.adaptationSummary || ''"
              :plan="detail?.resource?.profile_adaptation_plan"
              resource-type="video"
            />

            <section class="segment-section">
              <div class="section-heading"><span>分段播放</span><strong>{{ selectedRecommendation.segments?.length || 0 }} 个已核验分段</strong></div>
              <button
                v-for="segment in selectedRecommendation.segments || []"
                :key="segment.id"
                type="button"
                class="segment-row"
                :class="{ active: selectedSegment?.id === segment.id }"
                @click="jumpToSegment(segment)"
              >
                <Play :size="16" />
                <span><strong>{{ segment.title }}</strong><small>{{ segment.learningFocus }}</small></span>
                <time>{{ Math.floor(segment.startSeconds / 60) }}:{{ String(segment.startSeconds % 60).padStart(2, '0') }}</time>
              </button>
              <p v-if="!selectedRecommendation.segments?.length" class="empty-copy">
                来源没有提供可验证的时长和章节时间点，因此系统不伪造分段。请在当前播放器中按来源原始目录观看。
              </p>
            </section>
          </template>
          <div v-else class="player-state player-state--large">
            <FileVideo2 :size="28" /><strong>没有可展示的视频推荐</strong><span>返回资源中心继续讲义、导图或实训任务。</span>
          </div>
        </section>

        <aside class="detail-pane" aria-label="推荐理由、来源与许可和笔记">
          <template v-if="selectedRecommendation">
            <section class="detail-section detail-section--lead">
              <span>推荐理由</span>
              <p>{{ selectedRecommendation.reason }}</p>
              <dl class="learning-context">
                <div><dt>学习目标</dt><dd>{{ structured.learningGoal || '当前推荐未登记学习目标。' }}</dd></div>
              </dl>
            </section>

            <section class="detail-section">
              <div class="section-heading"><span>来源与许可</span><ShieldCheck :size="17" /></div>
              <dl class="source-facts">
                <div><dt>作者/维护者</dt><dd>{{ selectedRecommendation.author }}</dd></div>
                <div><dt>许可状态</dt><dd>{{ selectedRecommendation.licenseStatus }}</dd></div>
                <div><dt>观看方式</dt><dd>{{ playable ? '站内已登记素材' : externalOnly ? '站内嵌入来源' : '暂不可用' }}</dd></div>
              </dl>
              <p class="license-copy">{{ selectedRecommendation.licenseLabel }}</p>
              <div class="inline-actions">
                <button v-if="selectedRecommendation.url" type="button" @click="openInAppSource(selectedRecommendation.url, '视频来源')"><Link2 :size="16" /> 打开来源（站内）</button>
                <button v-if="selectedRecommendation.licenseUrl" type="button" @click="openInAppSource(selectedRecommendation.licenseUrl, '许可页')"><ShieldCheck :size="16" /> 查看许可页（站内）</button>
              </div>
              <button
                v-for="source in sources.filter(item => selectedRecommendation.sourceRefIds.includes(item.source_ref_id))"
                :key="source.source_ref_id"
                type="button"
                class="source-row"
                :disabled="!source.available && !source.source_url"
                @click="openSource(source)"
              >
                <BookOpen :size="16" />
                <span><strong>{{ source.title || '课程来源' }}</strong><small>{{ source.location_label || '位置未记录' }}</small></span>
                <ExternalLink :size="15" />
              </button>
            </section>

            <section class="detail-section">
              <span>替代来源</span>
              <button
                v-for="alternative in selectedRecommendation.alternatives || []"
                :key="alternative.id"
                type="button"
                class="alternative-row"
                @click="openInAppSource(alternative.url, '替代来源')"
              >
                <span><strong>{{ alternative.title }}</strong><small>{{ alternative.reason }}</small></span>
                <Link2 :size="15" />
              </button>
              <p v-if="!selectedRecommendation.alternatives?.length" class="empty-copy">暂无已登记替代来源。</p>
            </section>

            <section class="detail-section note-section">
              <div class="section-heading"><span>写学习笔记</span><NotebookPen :size="17" /></div>
              <p>{{ selectedSegment ? `当前分段：${selectedSegment.title}` : '当前笔记关联整条视频推荐。' }}</p>
              <textarea v-model="noteDraft" rows="5" placeholder="记录关键概念、疑问和下一步验证方式" aria-label="视频学习笔记草稿" />
              <div class="note-actions">
                <button type="button" class="primary-button primary-button--auto" @click="saveNote"><Check :size="16" /> {{ noteSaved ? '再次保存' : '保存草稿' }}</button>
                <button type="button" class="secondary-button" @click="openNotebook"><NotebookPen :size="16" /> 打开笔记本</button>
              </div>
              <button type="button" class="question-button" @click="askAboutVideo"><MessageSquareText :size="16" /> 资源内提问</button>
              <button type="button" class="question-button" @click="goBack"><RotateCcw :size="16" /> 返回资源中心重新生成</button>
            </section>

            <p class="evidence-boundary">浏览、站内嵌入、分段播放和保存本地笔记草稿不会自动改变掌握度或解锁智能组卷。</p>
          </template>
        </aside>
      </section>
    </template>

    <ResourceFloatingQa
      :open="qaOpen"
      :course-id="catalog.course?.id || route.query.course_id || ''"
      :knowledge-point-id="catalog.knowledge_point?.id || ''"
      :resource-id="resourceId"
      :resource-title="selectedRecommendation?.title || title"
      :source-ref-ids="sources.map(item => item.source_ref_id || item.sourceRefId || item.id).filter(Boolean)"
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
      :restore-disabled="Boolean(restoringId)"
      @close="closeHistory"
      @select="selectHistoryVersion"
      @compare="compareHistory"
      @restore="restoreHistory"
      @compare-close="compareResult = null"
    />
  </main>
</template>

<style scoped>
.video-page{min-height:100%;padding:24px 28px 32px;background:var(--color-page);color:var(--color-text);font-family:var(--font-sans)}
.back-link{display:inline-flex;align-items:center;gap:8px;margin:0 0 18px;padding:0;border:0;background:transparent;color:var(--color-text-secondary);font-size:14px;font-weight:650;cursor:pointer}.back-link:hover{color:var(--color-text)}
.video-page>.back-link{display:none}
.video-page>.page-header{display:none}
.page-header{display:grid;grid-template-columns:minmax(0,1fr) minmax(500px,.85fr);gap:36px;align-items:end;padding:0 0 22px;border-bottom:1px solid var(--color-border)}.context-line{margin:0 0 6px;color:var(--color-text-secondary);font-size:14px;font-weight:650}.page-header h1{margin:0;font-family:var(--font-heading);font-size:34px;line-height:1.25;letter-spacing:0}.page-header>div>p:last-child{max-width:70ch;margin:9px 0 0;color:var(--color-text-secondary);font-size:15px;line-height:1.65}
.header-meta{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));border:1px solid var(--color-border);border-radius:8px;background:#fff;overflow:hidden}.header-meta>div{min-width:0;padding:13px 14px;border-right:1px solid var(--color-border)}.header-meta>div:last-child{border-right:0}.header-meta span,.header-meta strong{display:block}.header-meta span{color:var(--color-text-muted);font-size:14px}.header-meta strong{margin-top:4px;font-size:14px;line-height:1.45}
.notice{display:flex;align-items:center;gap:8px;margin:14px 0 0;padding:10px 12px;border:1px solid var(--color-border);border-radius:6px;background:#fff;color:var(--color-text-secondary);font-size:14px}.notice--warning{border-color:#dfcfb4;background:var(--color-warning-soft);color:#6f501e}
.workspace-shell{display:grid;grid-template-columns:minmax(235px,20fr) minmax(520px,52fr) minmax(300px,28fr);min-height:650px;margin-top:18px;border:1px solid var(--color-border-strong);border-radius:8px;background:#fff;overflow:hidden}.recommendation-pane,.player-pane{border-right:1px solid var(--color-border)}.recommendation-pane,.detail-pane{min-width:0;background:var(--color-surface-subtle)}
.pane-heading{display:flex;align-items:center;justify-content:space-between;gap:8px;min-height:62px;padding:10px 12px;border-bottom:1px solid var(--color-border);background:#fff}.pane-heading>div span,.pane-heading>div strong{display:block}.pane-heading>div span{color:var(--color-text-muted);font-size:14px}.pane-heading>div strong{margin-top:3px;font-size:14px}.version-control{position:relative;display:flex;align-items:center;gap:6px;height:38px;padding:0 8px;border:1px solid var(--color-border);border-radius:6px;background:#fff;color:var(--color-text-secondary);font-size:14px}.version-control select{appearance:none;min-width:50px;padding:0 18px 0 0;border:0;outline:0;background:transparent;color:var(--color-text);font:650 14px/1.4 var(--font-sans)}.version-control svg{position:absolute;right:7px;pointer-events:none}
.recommendation-row{display:grid;grid-template-columns:28px minmax(0,1fr);gap:9px;width:100%;padding:14px 12px;border:0;border-bottom:1px solid var(--color-border);background:transparent;color:var(--color-text);text-align:left;cursor:pointer}.recommendation-row:hover,.recommendation-row:focus-visible{background:#fff;outline:none}.recommendation-row.active{background:#fff;box-shadow:inset 3px 0 0 var(--color-accent)}.row-index{padding-top:2px;color:var(--color-text-muted);font-size:14px;font-weight:700}.row-copy strong,.row-copy small,.row-copy em{display:block}.row-copy strong{font-size:15px;line-height:1.45}.row-copy small{margin-top:4px;color:var(--color-text-secondary);font-size:14px;line-height:1.45}.row-copy em{width:max-content;margin-top:8px;padding:2px 6px;border:1px solid var(--color-border);border-radius:4px;color:var(--color-text-secondary);font-size:14px;font-style:normal}.empty-list{display:grid;min-height:340px;place-items:center;align-content:center;gap:8px;padding:24px;text-align:center}.empty-list strong{font-size:16px}.empty-list span{color:var(--color-text-secondary);font-size:14px;line-height:1.6}
.player-pane{min-width:0;padding:18px;background:#fff}.player-stage{position:relative;display:grid;width:100%;aspect-ratio:16/9;place-items:center;overflow:hidden;border:1px solid var(--color-border-strong);border-radius:6px;background:#07131a}.player-stage video,.player-stage iframe{width:100%;height:100%;border:0;background:#07131a}.player-state{display:grid;max-width:430px;place-items:center;gap:9px;padding:24px;color:#fff;text-align:center}.player-state strong{font-size:18px}.player-state span{color:#c9d1d4;font-size:14px;line-height:1.6}.player-state--error svg{color:#e0a890}.player-state--large{min-height:560px;color:var(--color-text)}.player-state--large span{color:var(--color-text-secondary)}.embedded-close{position:absolute;top:10px;right:10px;display:inline-flex;align-items:center;gap:6px;min-height:32px;padding:0 9px;border:1px solid rgb(255 255 255 / 35%);border-radius:5px;background:rgb(7 19 26 / 82%);color:#fff;font:650 13px/1.3 var(--font-sans);cursor:pointer}.embedded-close:hover{background:rgb(7 19 26 / 95%)}.spin{animation:spin 1s linear infinite}
.player-title{display:flex;align-items:flex-start;justify-content:space-between;gap:20px;padding:16px 0;border-bottom:1px solid var(--color-border)}.player-title span{color:var(--color-text-secondary);font-size:14px}.player-title h2{margin:5px 0 0;font-size:22px;line-height:1.35}.player-title>div:last-child{display:flex;align-items:center;gap:7px;white-space:nowrap}
.segment-section{padding-top:18px}.section-heading{display:flex;align-items:center;justify-content:space-between;gap:12px}.section-heading span,.section-heading strong{font-size:14px}.section-heading span{font-weight:700}.section-heading strong{color:var(--color-text-muted)}.segment-row{display:grid;grid-template-columns:24px minmax(0,1fr) auto;align-items:center;gap:9px;width:100%;margin-top:8px;padding:10px 11px;border:1px solid var(--color-border);border-radius:6px;background:#fff;color:var(--color-text);text-align:left;cursor:pointer}.segment-row:hover,.segment-row:focus-visible,.segment-row.active{border-color:var(--color-accent);background:var(--color-accent-soft);outline:none}.segment-row strong,.segment-row small{display:block}.segment-row strong{font-size:14px}.segment-row small{margin-top:3px;color:var(--color-text-secondary);font-size:14px;line-height:1.45}.segment-row time{color:var(--color-text-muted);font-size:14px}
.detail-pane{padding:18px;overflow-y:auto}.detail-section{padding:18px 0;border-bottom:1px solid var(--color-border)}.detail-section:first-child{padding-top:0}.detail-section>span,.detail-section .section-heading>span{font-size:15px;font-weight:750}.detail-section--lead>p{margin:9px 0 0;font-size:15px;line-height:1.65}.learning-context{display:grid;gap:9px;margin:14px 0 0}.learning-context>div{padding:10px;border:1px solid var(--color-border);border-radius:6px;background:#fff}.learning-context dt{color:var(--color-text-muted);font-size:14px}.learning-context dd{margin:4px 0 0;color:var(--color-text-secondary);font-size:14px;line-height:1.55}.source-facts{margin:12px 0 0}.source-facts>div{display:grid;grid-template-columns:90px minmax(0,1fr);gap:12px;padding:7px 0;border-bottom:1px solid var(--color-border)}.source-facts dt{color:var(--color-text-muted);font-size:14px}.source-facts dd{margin:0;font-size:14px;line-height:1.5;overflow-wrap:anywhere}.license-copy,.note-section>p,.empty-copy{color:var(--color-text-secondary);font-size:14px;line-height:1.6}.inline-actions,.note-actions{display:flex;gap:7px;flex-wrap:wrap}.inline-actions button,.source-row,.alternative-row,.secondary-button{display:flex;align-items:center;gap:7px;min-height:38px;padding:0 10px;border:1px solid var(--color-border-strong);border-radius:6px;background:#fff;color:var(--color-text);font:650 14px/1.35 var(--font-sans);cursor:pointer}.source-row,.alternative-row{width:100%;height:auto;margin-top:8px;padding:9px 10px;text-align:left}.source-row>span,.alternative-row>span{flex:1;min-width:0}.source-row strong,.source-row small,.alternative-row strong,.alternative-row small{display:block}.source-row strong,.alternative-row strong{font-size:14px}.source-row small,.alternative-row small{margin-top:3px;color:var(--color-text-muted);font-size:14px;line-height:1.45}.source-row:disabled{cursor:not-allowed;opacity:.6}.note-section textarea{box-sizing:border-box;width:100%;margin:8px 0 10px;padding:10px 11px;border:1px solid var(--color-border-strong);border-radius:6px;background:#fff;color:var(--color-text);font:14px/1.6 var(--font-sans);resize:vertical}.note-section textarea:focus{border-color:var(--color-accent);outline:2px solid rgb(17 33 45 / 10%)}
.primary-button{display:inline-flex;align-items:center;justify-content:center;gap:7px;min-height:40px;padding:0 13px;border:1px solid var(--color-accent);border-radius:6px;background:var(--color-accent);color:#fff;font:650 14px/1.3 var(--font-sans);cursor:pointer}.primary-button--auto{width:auto}.secondary-button{justify-content:center}.question-button{display:flex;width:100%;min-height:40px;align-items:center;justify-content:center;gap:7px;margin-top:8px;border:1px solid var(--color-border-strong);border-radius:6px;background:#fff;color:var(--color-text);font:650 14px/1.3 var(--font-sans);cursor:pointer}.question-button:hover{background:var(--color-surface-subtle)}.evidence-boundary{margin:16px 0 0;color:var(--color-text-muted);font-size:14px;line-height:1.55}.page-state{display:grid;min-height:560px;place-items:center;align-content:center;gap:8px;border:1px solid var(--color-border);border-radius:8px;background:#fff;text-align:center}.page-state strong{font-size:18px}.page-state span{color:var(--color-text-secondary);font-size:15px}.page-state .primary-button{margin-top:8px}.page-state--error svg{color:var(--color-danger)}
@keyframes spin{to{transform:rotate(360deg)}}
@media (max-width:1380px){.video-page{padding:20px 22px 28px}.page-header{grid-template-columns:minmax(0,1fr) 520px;gap:24px}.workspace-shell{grid-template-columns:minmax(220px,19fr) minmax(480px,51fr) minmax(292px,30fr)}.player-pane{padding:14px}.detail-pane{padding:14px}}
</style>
