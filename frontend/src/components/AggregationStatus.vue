<script setup>
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import {
  AlertCircle, ArrowRight, Check, ChevronDown, Clock3, RefreshCw,
} from '@lucide/vue'
import {
  getLatestM5LearningFeedback,
  getM5LearningAggregation,
  replayM5LearningEvent,
} from '../api/m5'
import { useCourseContextStore } from '../stores/courseContext'

const props = defineProps({
  courseId: { type: String, default: '' },
  eventId: { type: String, default: '' },
  initialFeedback: { type: Object, default: null },
  mode: { type: String, default: 'compact' },
  showEmpty: { type: Boolean, default: false },
})

const emit = defineEmits(['recovered'])
const router = useRouter()
const courseContext = useCourseContextStore()
const feedback = ref(null)
const loading = ref(false)
const retrying = ref(false)
const error = ref('')
const expanded = ref(props.mode === 'result')
// Once the learner explicitly retries, the parent-provided snapshot may be
// stale (for example, it can still say "反馈仍在处理"). Force the next load
// to read the server's current aggregation instead of reusing that snapshot.
const ignoreInitialFeedback = ref(false)
let requestSequence = 0

const activeCourseId = computed(() => String(
  props.courseId || courseContext.contextRef?.courseId || '',
))
const visible = computed(() => Boolean(
  loading.value
    || error.value
    || (feedback.value && feedback.value.status !== 'processed')
    || (props.showEmpty && !feedback.value),
))
const state = computed(() => {
  if (error.value) return 'failed'
  if (!feedback.value) return loading.value ? 'loading' : 'empty'
  if (feedback.value.status === 'processed') return 'completed'
  if (feedback.value.views?.some(item => item.status === 'failed')) return 'partial'
  return 'pending'
})
const headline = computed(() => ({
  loading: '正在核对学习结果',
  empty: '还没有可用的学习反馈',
  pending: '学习结果处理中',
  partial: '部分学习结果待恢复',
  failed: '学习反馈暂时无法读取',
  completed: '本次学习已记录',
}[state.value]))
const summary = computed(() => {
  if (error.value) return error.value
  if (!feedback.value) return props.showEmpty ? '完成一项学习任务后，这里会显示跨页面更新。' : ''
  const source = feedback.value.event?.label || '本次学习'
  if (state.value === 'completed') {
    return `${source}完成，学习结果已更新到相关页面。`
  }
  return `${source}结果已经保存，已更新 ${feedback.value.completedCount || 0}/${feedback.value.totalCount || 6} 项。`
})
const nextSchedule = computed(() => feedback.value?.nextDaySchedule?.[0] || null)
const shortToken = computed(() => feedback.value?.consistencyToken?.slice(0, 10) || '')

function statusText(status) {
  return ({ completed: '已更新', failed: '待恢复', pending: '等待中' })[status] || '等待中'
}

function messageFrom(value) {
  return value?.detail?.message || value?.message || '暂时无法读取学习反馈，请稍后重试。'
}

async function loadFeedback() {
  const sequence = ++requestSequence
  error.value = ''
  const initial = props.initialFeedback
  if (!ignoreInitialFeedback.value && initial && (!props.eventId || initial.event?.id === props.eventId)) {
    feedback.value = initial
    loading.value = false
    return
  }
  loading.value = !feedback.value
  try {
    const response = props.eventId
      ? await getM5LearningAggregation(props.eventId)
      : await getLatestM5LearningFeedback({ course_id: activeCourseId.value || undefined })
    if (sequence !== requestSequence) return
    feedback.value = response.feedback
  } catch (value) {
    if (sequence !== requestSequence) return
    error.value = messageFrom(value)
  } finally {
    if (sequence === requestSequence) loading.value = false
  }
}

async function retry() {
  const eventId = feedback.value?.event?.id || props.eventId
  if (!eventId || retrying.value) return
  retrying.value = true
  error.value = ''
  try {
    await replayM5LearningEvent(eventId)
    ignoreInitialFeedback.value = true
    feedback.value = null
    await loadFeedback()
    emit('recovered', feedback.value)
  } catch (value) {
    error.value = messageFrom(value)
  } finally {
    retrying.value = false
  }
}

function openView(item) {
  if (!item?.route) return
  router.push({
    path: item.route,
    query: activeCourseId.value ? { course_id: activeCourseId.value } : {},
  })
}

watch(
  [() => props.eventId, activeCourseId, () => props.initialFeedback],
  loadFeedback,
  { immediate: true },
)
watch(() => props.mode, value => { expanded.value = value === 'result' })
</script>

<template>
  <section
    v-if="visible"
    class="aggregation-status"
    :class="`aggregation-status--${state}`"
    data-testid="aggregation-status"
    :aria-live="state === 'partial' || state === 'failed' ? 'assertive' : 'polite'"
  >
    <div class="aggregation-summary">
      <span class="aggregation-mark" aria-hidden="true">
        <RefreshCw v-if="state === 'loading' || retrying" :size="18" class="spin" />
        <AlertCircle v-else-if="state === 'failed' || state === 'partial'" :size="18" />
        <Check v-else-if="state === 'completed'" :size="18" />
        <Clock3 v-else :size="18" />
      </span>
      <div class="aggregation-copy">
        <strong>{{ headline }}</strong>
        <span v-if="summary">{{ summary }}</span>
      </div>
      <button
        v-if="feedback?.recoverable"
        type="button"
        class="aggregation-retry"
        :disabled="retrying"
        @click="retry"
      >
        <RefreshCw :size="16" :class="{ spin: retrying }" />{{ retrying ? '正在恢复' : '重试同步' }}
      </button>
      <button
        v-if="feedback"
        type="button"
        class="aggregation-toggle"
        :aria-expanded="expanded"
        @click="expanded = !expanded"
      >
        {{ expanded ? '收起明细' : '查看明细' }}
        <ChevronDown :size="17" :class="{ rotated: expanded }" />
      </button>
    </div>

    <div v-if="expanded && feedback" class="aggregation-details">
      <ul class="aggregation-views" aria-label="跨页面同步状态">
        <li v-for="item in feedback.views" :key="item.id">
          <span class="view-state" :class="`view-state--${item.status}`" aria-hidden="true">
            <Check v-if="item.status === 'completed'" :size="15" />
            <AlertCircle v-else-if="item.status === 'failed'" :size="15" />
            <Clock3 v-else :size="15" />
          </span>
          <span class="view-copy"><strong>{{ item.label }}</strong><small>{{ statusText(item.status) }}</small></span>
          <button type="button" :title="`进入${item.label}`" :aria-label="`进入${item.label}`" @click="openView(item)">
            <ArrowRight :size="17" />
          </button>
        </li>
      </ul>

      <div v-if="nextSchedule" class="aggregation-next">
        <div>
          <span>下一日安排</span>
          <strong>{{ nextSchedule.title }}</strong>
          <small>{{ nextSchedule.reason }}</small>
        </div>
        <button type="button" class="aggregation-next-action" @click="openView({ route: nextSchedule.target_route })">
          查看安排<ArrowRight :size="16" />
        </button>
      </div>

      <footer v-if="shortToken">
        <span>一致版本 {{ shortToken }}</span>
        <span>{{ feedback.event?.label }} · {{ new Date(feedback.event?.occurredAt).toLocaleString('zh-CN') }}</span>
      </footer>
    </div>
  </section>
</template>

<style scoped>
.aggregation-status {
  width: 100%;
  color: #11212d;
  background: #ffffff;
  border: 1px solid #d9dedf;
  border-radius: 8px;
  font-family: var(--font-sans, "Noto Sans CJK SC", "Source Han Sans SC", sans-serif);
  font-size: 14px;
  letter-spacing: 0;
  overflow: hidden;
}

.aggregation-status--partial,
.aggregation-status--failed {
  background: #fff9f7;
  border-color: #dfc3bd;
}

.aggregation-summary {
  min-height: 58px;
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 14px;
}

.aggregation-mark {
  width: 32px;
  height: 32px;
  flex: 0 0 32px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: #ffffff;
  background: #11212d;
  border-radius: 7px;
}

.aggregation-status--partial .aggregation-mark,
.aggregation-status--failed .aggregation-mark {
  background: #8f3f38;
}

.aggregation-copy {
  min-width: 0;
  flex: 1;
  display: grid;
  gap: 2px;
}

.aggregation-copy strong,
.view-copy strong,
.aggregation-next strong {
  font-size: 15px;
  line-height: 1.45;
  font-weight: 700;
  overflow-wrap: anywhere;
}

.aggregation-copy span,
.view-copy small,
.aggregation-next span,
.aggregation-next small,
.aggregation-details footer {
  color: #4a5c6a;
  font-size: 14px;
  line-height: 1.5;
  overflow-wrap: anywhere;
}

.aggregation-retry,
.aggregation-toggle,
.aggregation-next-action,
.aggregation-views button {
  min-height: 36px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  border-radius: 7px;
  font-size: 14px;
  font-weight: 650;
  transition: background 160ms ease, color 160ms ease, border-color 160ms ease;
}

.aggregation-retry {
  padding: 7px 12px;
  color: #ffffff;
  background: #11212d;
  border: 1px solid #11212d;
}

.aggregation-toggle,
.aggregation-next-action {
  padding: 7px 10px;
  color: #253745;
  background: #ffffff;
  border: 1px solid #c8d0d2;
}

.aggregation-retry:hover:not(:disabled) { background: #253745; }
.aggregation-toggle:hover,
.aggregation-next-action:hover,
.aggregation-views button:hover { background: #edf1f2; }
.aggregation-retry:disabled { cursor: wait; opacity: 0.65; }

.aggregation-retry:focus-visible,
.aggregation-toggle:focus-visible,
.aggregation-next-action:focus-visible,
.aggregation-views button:focus-visible {
  outline: 2px solid #11212d;
  outline-offset: 2px;
}

.aggregation-toggle svg { transition: transform 160ms ease; }
.aggregation-toggle svg.rotated { transform: rotate(180deg); }

.aggregation-details {
  border-top: 1px solid #e1e5e6;
}

.aggregation-views {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  margin: 0;
  padding: 0;
  list-style: none;
}

.aggregation-views li {
  min-width: 0;
  min-height: 58px;
  display: flex;
  align-items: center;
  gap: 9px;
  padding: 10px 12px;
  border-bottom: 1px solid #edf0f1;
}

.aggregation-views li:not(:nth-child(3n)) { border-right: 1px solid #edf0f1; }

.view-state {
  width: 24px;
  height: 24px;
  flex: 0 0 24px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: #4a5c6a;
  border: 1px solid #c8d0d2;
  border-radius: 50%;
}

.view-state--completed { color: #11212d; border-color: #11212d; }
.view-state--failed { color: #8f3f38; border-color: #c99187; }

.view-copy {
  min-width: 0;
  flex: 1;
  display: grid;
}

.view-copy strong { font-size: 14px; }
.view-copy small { white-space: nowrap; }

.aggregation-views button {
  width: 34px;
  min-height: 34px;
  flex: 0 0 34px;
  color: #253745;
  background: transparent;
  border: 0;
}

.aggregation-next {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 12px 14px;
  background: #f7f8f8;
  border-bottom: 1px solid #e1e5e6;
}

.aggregation-next > div {
  min-width: 0;
  flex: 1;
  display: grid;
  gap: 2px;
}

.aggregation-next span { font-weight: 650; }

.aggregation-details footer {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  padding: 9px 14px;
  font-variant-numeric: tabular-nums;
}

.spin { animation: aggregation-spin 850ms linear infinite; }

@keyframes aggregation-spin {
  to { transform: rotate(360deg); }
}

@media (max-width: 1180px) {
  .aggregation-views { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .aggregation-views li:not(:nth-child(3n)) { border-right: 0; }
  .aggregation-views li:nth-child(odd) { border-right: 1px solid #edf0f1; }
}
</style>
