<script setup>
import { learningText } from '../utils/learningCopy.js'
import { userMessage } from '../services/errorTranslator.js'
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { AlertCircle, BookOpen, ExternalLink, LoaderCircle } from '@lucide/vue'
import { getCanonicalSourceRef } from '../api/m1'
import { sourceCitationRoute } from '../utils/sourceCitationRoute.js'

const props = defineProps({
  source: { type: Object, default: () => ({}) },
  sourceRefId: { type: String, default: '' },
  returnTo: { type: String, default: '' },
  compact: { type: Boolean, default: false },
  displayTitle: { type: String, default: '' },
  hideLocation: { type: Boolean, default: false },
})

const emit = defineEmits(['resolved', 'navigation-error', 'navigation-complete'])
const router = useRouter()
const resolvedSource = ref(null)
const loading = ref(false)
const loadError = ref('')

function firstValue(source, ...keys) {
  for (const key of keys) {
    const value = source?.[key]
    if (value !== undefined && value !== null && value !== '') return value
  }
  return null
}

function normalizeSource(source) {
  const value = source || {}
  return {
    id: String(firstValue(value, 'sourceRefId', 'source_ref_id', 'id') || ''),
    documentId: String(firstValue(value, 'sourceDocumentId', 'source_document_id', 'documentId', 'document_id') || ''),
    documentVersion: String(firstValue(value, 'documentVersion', 'document_version') || ''),
    title: learningText(firstValue(value, 'title', 'filename'), '课程来源'),
    chapterTitle: String(firstValue(value, 'chapterTitle', 'chapter_title', 'sectionTitle', 'section_title') || ''),
    pageNumber: firstValue(value, 'pageNumber', 'page_number'),
    charStart: firstValue(value, 'charStart', 'char_start'),
    charEnd: firstValue(value, 'charEnd', 'char_end'),
    imageRegion: firstValue(value, 'imageRegion', 'image_region', 'normalizedRect', 'normalized_rect'),
    locationLabel: String(firstValue(value, 'locationLabel', 'location_label') || ''),
    available: value.available !== false,
    reason: String(firstValue(value, 'reason', 'reasonCode', 'reason_code') || ''),
    route: String(firstValue(value, 'route') || ''),
    quote: String(firstValue(value, 'quote') || ''),
  }
}

const citation = computed(() => {
  const normalized = normalizeSource(resolvedSource.value || props.source)
  if (!normalized.id && props.sourceRefId) normalized.id = props.sourceRefId
  return normalized
})

const locationText = computed(() => {
  if (citation.value.locationLabel && citation.value.locationLabel !== citation.value.title) return citation.value.locationLabel
  const parts = []
  if (citation.value.chapterTitle && citation.value.chapterTitle !== citation.value.title) parts.push(citation.value.chapterTitle)
  if (citation.value.pageNumber !== null) parts.push(`第 ${citation.value.pageNumber} 页`)
  if (citation.value.charStart !== null && citation.value.charEnd !== null) {
    parts.push('原文相关段落')
  }
  if (citation.value.imageRegion) parts.push('图片选区')
  return parts.join(' · ')
})

function isInternalPath(value) {
  return Boolean(value && value.startsWith('/') && !value.startsWith('//'))
}

function routeWithReturnTo(target) {
  if (!isInternalPath(target)) return ''
  const [path, query = ''] = target.split('?')
  const params = new URLSearchParams(query)
  if (isInternalPath(props.returnTo) && props.returnTo.split('?')[0] !== path) params.set('return_to', props.returnTo)
  const suffix = params.toString()
  return suffix ? `${path}?${suffix}` : path
}

async function resolveCanonicalSource() {
  if (resolvedSource.value || !citation.value.id) return resolvedSource.value || props.source
  loading.value = true
  loadError.value = ''
  try {
    resolvedSource.value = await getCanonicalSourceRef(citation.value.id)
    emit('resolved', resolvedSource.value)
    return resolvedSource.value
  } catch (error) {
    loadError.value = error?.response?.data?.detail || error?.message || '来源暂时无法核对'
    emit('navigation-error', loadError.value)
    return null
  } finally {
    loading.value = false
  }
}

async function openSource() {
  if (props.source?.available === false) {
    loadError.value = props.source.reason || '保存时的来源当前不可用'
    return
  }
  const latest = citation.value.id && props.source?.kind !== 'resource_version'
    ? await resolveCanonicalSource() : props.source
  if (!latest) return
  const normalized = normalizeSource(latest)
  if (!normalized.available) {
    loadError.value = normalized.reason || '来源当前不可用'
    return
  }
  const target = routeWithReturnTo(sourceCitationRoute(latest, props.source))
  if (!target) {
    loadError.value = '来源没有可返回的原文位置'
    return
  }
  await router.push(target)
  emit('navigation-complete')
}
</script>

<template>
  <div
    class="source-citation"
    :class="{ compact, unavailable: !citation.available }"
    data-testid="canonical-source-citation"
    :data-source-ref-id="citation.id"
  >
    <button
      type="button"
      class="source-citation__action"
      :disabled="loading || (!citation.id && !citation.route)"
      :aria-label="`查看来源：${displayTitle || citation.title}`"
      @click="openSource"
    >
      <LoaderCircle v-if="loading" :size="17" class="source-citation__spin" />
      <AlertCircle v-else-if="!citation.available" :size="17" />
      <BookOpen v-else :size="17" />
      <span class="source-citation__copy">
        <strong>{{ learningText(displayTitle, citation.title) }}</strong>
        <small v-if="!citation.available || (!hideLocation && locationText)">{{ citation.available ? locationText : learningText(citation.reason, '这份资料暂时不可用，请选择其他课程内容。') }}</small>
      </span>
      <ExternalLink v-if="citation.available" :size="15" />
    </button>
    <p v-if="loadError" class="source-citation__error" role="status">{{ userMessage(loadError) }}</p>
  </div>
</template>

<style scoped>
.source-citation {
  min-width: 0;
  border-bottom: 1px solid var(--color-border, var(--color-border));
}

.source-citation:last-child {
  border-bottom: 0;
}

.source-citation__action {
  display: grid;
  width: 100%;
  min-height: 54px;
  grid-template-columns: 20px minmax(0, 1fr) 18px;
  align-items: center;
  gap: 9px;
  border: 0;
  padding: 9px 2px;
  color: var(--color-text, var(--color-text));
  background: transparent;
  text-align: left;
  cursor: pointer;
}

.source-citation.compact .source-citation__action {
  min-height: 48px;
  padding: 7px 0;
}

.source-citation__action:hover:not(:disabled) {
  background: var(--color-surface-subtle, var(--color-surface-subtle));
}

.source-citation__action:focus-visible {
  outline: 2px solid var(--color-accent, var(--color-text));
  outline-offset: 2px;
}

.source-citation__action:disabled {
  cursor: default;
  opacity: .64;
}

.source-citation__copy {
  display: grid;
  min-width: 0;
  gap: 2px;
}

.source-citation__copy strong,
.source-citation__copy small {
  overflow: hidden;
  font-size: 14px;
  line-height: 1.45;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.source-citation__copy strong {
  font-weight: 620;
}

.source-citation__copy small {
  color: var(--color-text-muted, var(--color-text-muted));
}

.source-citation.unavailable .source-citation__action,
.source-citation__error {
  color: var(--color-danger, var(--color-danger));
}

.source-citation__error {
  margin: -3px 0 8px 29px;
  font-size: 14px;
  line-height: 1.5;
}

.source-citation__spin {
  animation: source-citation-spin .8s linear infinite;
}

@keyframes source-citation-spin {
  to { transform: rotate(360deg); }
}
</style>
