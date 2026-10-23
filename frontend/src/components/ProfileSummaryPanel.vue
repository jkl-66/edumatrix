<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import {
  Activity, AlertCircle, ArrowRight, BrainCircuit, CheckCircle2,
  Clock3, LoaderCircle, RefreshCw, Target,
} from '@lucide/vue'
import { getM5ProfileSummary } from '../api'

const props = defineProps({
  courseId: { type: String, default: '' },
  compact: { type: Boolean, default: false },
  onboarding: { type: Boolean, default: false },
  session: { type: Object, default: null },
})
const emit = defineEmits(['loaded', 'load-error'])

const router = useRouter()
const loading = ref(true)
const error = ref('')
const data = ref(null)
let requestSequence = 0
let activeCourseId = ''

const icons = { skill: Target, cognitive: BrainCircuit, behavior: Activity }
const evidenceCount = computed(() => data.value?.summary?.evidence_count || 0)
const compactWeakPoint = computed(() => {
  const sections = data.value?.sections || []
  const skillSection = sections.find((section) => section.key === 'skill')
  return skillSection?.difficulties?.find(Boolean)
    || sections.flatMap((section) => section.difficulties || []).find(Boolean)
    || '完成一次诊断后生成薄弱点判断'
})
const compactNextAction = computed(() => data.value?.summary?.next_action || null)
const onboardingEntries = computed(() => Object.entries(props.session?.confirmedFields || {}).map(([key, value]) => ({ key, ...value })))
const onboardingMissing = computed(() => (props.session?.dimensions || []).filter((item) => item.status !== 'confirmed'))
const onboardingEvidence = computed(() => (props.session?.personalEvidence || []).filter((item) => item.status === 'confirmed'))
const onboardingSignals = computed(() => props.session?.profileSignals || [])

function message(err) {
  const detail = err?.response?.data?.detail || err?.detail
  return detail?.message || (typeof detail === 'string' ? detail : '') || err?.message || '画像摘要暂不可用'
}

async function refresh() {
  if (props.onboarding) return
  const requestedCourseId = String(props.courseId || '')
  const requestId = ++requestSequence
  if (requestedCourseId !== activeCourseId) {
    activeCourseId = requestedCourseId
    data.value = null
  }
  if (!props.courseId) {
    data.value = null
    error.value = ''
    loading.value = false
    emit('loaded', null)
    return
  }
  loading.value = !data.value
  error.value = ''
  try {
    const nextData = await getM5ProfileSummary({ course_id: requestedCourseId })
    if (requestId !== requestSequence || requestedCourseId !== String(props.courseId || '')) return
    data.value = nextData
    emit('loaded', data.value)
  } catch (err) {
    if (requestId !== requestSequence || requestedCourseId !== String(props.courseId || '')) return
    error.value = message(err)
    emit('load-error', error.value)
  } finally {
    if (requestId === requestSequence) loading.value = false
  }
}

function openNext(section) {
  const route = section?.next_step?.route || data.value?.summary?.next_action?.route
  if (route) router.push(route)
}

watch(() => props.courseId, refresh)
onMounted(() => { if (!props.onboarding) refresh() })
defineExpose({ refresh })
</script>

<template>
  <aside v-if="onboarding" class="onboarding-profile" data-testid="onboarding-profile-summary">
    <header>
      <div>
        <span class="eyebrow"><BrainCircuit :size="15" /> 实时画像</span>
        <h2>只记录你确认过的信息</h2>
      </div>
      <span class="profile-count">{{ onboardingEntries.length }}/5</span>
    </header>

    <div v-if="!onboardingEntries.length" class="onboarding-empty">
      <Target :size="20" />
      <strong>画像会在对话中逐步形成</strong>
      <span>回答并确认第一轮后，这里会逐步显示你的学习目标、节奏和更顺手的互动方式。</span>
    </div>

    <div v-else class="confirmed-profile-list">
      <article v-for="entry in onboardingEntries" :key="entry.key" class="confirmed-profile-item">
        <div class="confirmed-heading">
          <CheckCircle2 :size="16" />
          <strong>{{ entry.label }}</strong>
        </div>
        <p>{{ entry.summary }}</p>
      </article>
    </div>

    <section v-if="onboardingSignals.length" class="onboarding-signals">
      <h3>学习伙伴已经注意到</h3>
      <div class="signal-list">
        <span v-for="signal in onboardingSignals" :key="signal.key" class="signal-chip">
          <strong>{{ signal.label }}</strong><em>{{ signal.value }}</em>
        </span>
      </div>
      <p>这些线索会影响后续讲解节奏、例子和练习安排。</p>
    </section>

    <section class="missing-profile">
      <h3>待补充</h3>
      <div v-if="onboardingMissing.length" class="missing-list">
        <span v-for="item in onboardingMissing" :key="item.key" :class="item.status">
          <Clock3 :size="13" />{{ item.label }}
        </span>
      </div>
      <p v-else>五个维度已确认，可以进入入学诊断。</p>
    </section>

    <section v-if="onboardingEvidence.length" class="personal-evidence-summary">
      <h3>已确认个人资料</h3>
      <div v-for="item in onboardingEvidence" :key="item.evidenceId">
        <strong>{{ item.evidenceLabel }} · {{ item.filename }}</strong>
        <span>{{ item.confirmedFields.length }} 个字段已确认，均保留来源与确认时间</span>
      </div>
    </section>

    <footer>
      <span>当前课程</span>
      <strong>{{ session?.courseContext?.title || '尚未选择课程' }}</strong>
      <small>{{ session?.courseContext?.source || '选择课程后，这里会显示当前课程' }}</small>
    </footer>
  </aside>

  <section v-else class="profile-summary" :class="{ compact }" data-testid="profile-summary">
    <header>
      <div>
        <span class="eyebrow"><BrainCircuit :size="14" /> {{ compact ? '当前学习重点' : '三画像可解释摘要' }}</span>
        <h2 v-if="!compact">{{ data?.summary?.title || '会什么、哪里困难、下一步做什么' }}</h2>
        <p v-if="data">{{ data.course.title }} · {{ evidenceCount }} 条当前证据 · {{ data.summary.diagnostic_response_count }} 次有效诊断作答</p>
      </div>
      <button type="button" title="刷新画像摘要" :disabled="loading" @click="refresh"><RefreshCw :size="15" /></button>
    </header>

    <div v-if="loading" class="summary-state"><LoaderCircle class="spin" :size="16" />正在组合课程画像证据</div>
    <div v-else-if="error && !data" class="summary-state error" role="alert">
      <AlertCircle :size="16" /><span>{{ error }}</span>
      <button type="button" class="summary-retry" @click="refresh">重试</button>
    </div>

    <div v-if="error && data" class="summary-stale" role="status">
      <AlertCircle :size="15" /><span>新证据暂时加载失败，当前保留最近一次成功画像。</span>
      <button type="button" class="summary-retry" :disabled="loading" @click="refresh">重试</button>
    </div>

    <div v-else-if="data && compact" class="compact-focus" data-testid="profile-compact-focus">
      <div class="compact-focus-row">
        <div class="compact-focus-item">
          <span>当前薄弱点</span>
          <strong>{{ compactWeakPoint }}</strong>
        </div>
        <button class="compact-next-action" type="button" @click="openNext(compactNextAction)">
          <span><small>建议下一步</small><strong>{{ compactNextAction?.title || '继续当前学习任务' }}</strong></span>
          <ArrowRight :size="16" />
        </button>
      </div>

      <details class="compact-evidence-disclosure">
        <summary>查看画像依据 <small>{{ evidenceCount }} 条</small></summary>
        <div class="compact-evidence-grid">
          <article
            v-for="section in data.sections"
            :key="section.key"
            :data-testid="`profile-section-${section.key}`"
          >
            <div class="section-title">
              <component :is="icons[section.key]" :size="16" />
              <span><small>{{ section.question }}</small><strong>{{ section.title }}</strong></span>
            </div>
            <p class="headline">{{ section.headline }}</p>
            <div class="compact-signals">
              <span><CheckCircle2 :size="12" />{{ section.strengths[0] }}</span>
              <span><AlertCircle :size="12" />{{ section.difficulties[0] }}</span>
            </div>
            <div v-for="item in section.evidence" :key="`${item.source_type}-${item.source_id}`" class="evidence-row">
              <strong>{{ item.label }} · {{ item.value }}</strong>
              <span>{{ item.source_type }} / {{ item.source_id }}</span>
              <span><Clock3 :size="11" />{{ item.observed_at || '时间未记录' }}</span>
              <p>{{ item.recommendation_impact }}</p>
            </div>
            <div v-if="!section.evidence.length" class="evidence-empty">当前证据不足，系统不会形成固定判断。</div>
          </article>
        </div>
        <p class="compact-boundary">{{ data.boundary }}</p>
      </details>
    </div>

    <div v-else-if="data" class="profile-grid">
      <article
        v-for="section in data.sections"
        :key="section.key"
        :data-testid="`profile-section-${section.key}`"
      >
        <div class="section-title">
          <component :is="icons[section.key]" :size="16" />
          <span><small>{{ section.question }}</small><strong>{{ section.title }}</strong></span>
        </div>
        <p class="headline">{{ section.headline }}</p>
        <div class="signal-list">
          <span><CheckCircle2 :size="12" />{{ section.strengths[0] }}</span>
          <span><AlertCircle :size="12" />{{ section.difficulties[0] }}</span>
        </div>
        <details>
          <summary>查看来源、时间与推荐影响</summary>
          <div v-for="item in section.evidence" :key="`${item.source_type}-${item.source_id}`" class="evidence-row">
            <strong>{{ item.label }} · {{ item.value }}</strong>
            <span>{{ item.source_type }} / {{ item.source_id }}</span>
            <span><Clock3 :size="11" />{{ item.observed_at || '时间未记录' }}</span>
            <p>{{ item.recommendation_impact }}</p>
          </div>
          <div v-if="!section.evidence.length" class="evidence-empty">当前证据不足，系统不会形成固定判断。</div>
        </details>
        <button class="next-action" type="button" @click="openNext(section)">
          <span><small>下一步</small><strong>{{ section.next_step.title }}</strong></span>
          <ArrowRight :size="15" />
        </button>
      </article>
    </div>

    <footer v-if="data && !compact">
      <span>{{ data.boundary }}</span>
      <small>推荐使用：{{ data.recommendation_inputs.join('、') }}</small>
    </footer>
  </section>
</template>

<style scoped>
.onboarding-profile {
  display: flex;
  min-width: 0;
  height: 100%;
  flex-direction: column;
  overflow: hidden;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-panel);
  background: var(--color-surface);
}

.onboarding-profile > header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding: 22px 22px 18px;
  border-bottom: 1px solid var(--color-border);
}

.onboarding-profile h2 {
  margin: 5px 0 0;
  color: var(--color-text);
  font-size: 18px;
  line-height: 1.4;
}

.profile-count {
  min-width: 44px;
  padding: 4px 8px;
  color: #ffffff;
  border-radius: 6px;
  background: var(--color-accent);
  font-size: 14px;
  font-weight: 700;
  text-align: center;
}

.onboarding-empty {
  display: grid;
  place-items: center;
  gap: 8px;
  padding: 44px 28px;
  color: var(--color-text-secondary);
  text-align: center;
}

.onboarding-empty strong {
  color: var(--color-text);
  font-size: 15px;
}

.onboarding-empty span {
  max-width: 300px;
  font-size: 14px;
  line-height: 1.65;
}

.confirmed-profile-list {
  display: grid;
  gap: 0;
  overflow-y: auto;
}

.confirmed-profile-item {
  padding: 17px 22px;
  border-bottom: 1px solid var(--color-border);
}

.confirmed-heading {
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--color-accent);
}

.confirmed-profile-item p {
  margin: 8px 0 5px;
  color: var(--color-text);
  font-size: 15px;
  line-height: 1.65;
  white-space: pre-line;
}

.confirmed-profile-item > span {
  color: var(--color-text-muted);
  font-size: 14px;
}

.onboarding-signals {
  display: grid;
  gap: 10px;
  padding: 17px 22px;
  border-top: 1px solid var(--color-border);
  background: #fbfcfb;
}

.onboarding-signals h3 { margin: 0; font-size: 15px; }
.signal-list { display: flex; flex-wrap: wrap; gap: 7px; }
.signal-chip {
  display: inline-flex;
  max-width: 100%;
  align-items: baseline;
  gap: 5px;
  padding: 6px 8px;
  color: var(--color-text-secondary);
  border: 1px solid var(--color-border);
  border-radius: 999px;
  background: #ffffff;
  font-size: 12px;
  line-height: 1.4;
}
.signal-chip strong { color: var(--color-accent); font-weight: 700; }
.signal-chip em { max-width: 190px; overflow: hidden; color: var(--color-text); font-style: normal; text-overflow: ellipsis; white-space: nowrap; }
.onboarding-signals p { margin: 0; color: var(--color-text-muted); font-size: 12px; line-height: 1.5; }

.missing-profile {
  padding: 18px 22px;
  border-top: 1px solid var(--color-border);
  background: var(--color-surface-subtle);
}

.missing-profile h3 {
  margin: 0 0 10px;
  font-size: 15px;
}

.missing-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.missing-list span {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 5px 8px;
  color: var(--color-text-secondary);
  border: 1px solid var(--color-border);
  border-radius: 6px;
  background: var(--color-surface);
  font-size: 14px;
}

.missing-list span.current {
  color: var(--color-accent);
  border-color: var(--color-border-strong);
  font-weight: 700;
}

.missing-profile p {
  margin: 0;
  color: var(--color-text-secondary);
  font-size: 14px;
}

.personal-evidence-summary {
  display: grid;
  gap: 9px;
  padding: 17px 22px;
  border-top: 1px solid var(--color-border);
}

.personal-evidence-summary h3 { margin: 0; font-size: 15px; }
.personal-evidence-summary div { display: grid; gap: 3px; }
.personal-evidence-summary strong { color: var(--color-text); font-size: 14px; }
.personal-evidence-summary span { color: var(--color-text-muted); font-size: 14px; line-height: 1.5; }

.onboarding-profile > footer {
  display: grid;
  gap: 2px;
  margin-top: auto;
  padding: 17px 22px;
  color: var(--color-text-secondary);
  border-top: 1px solid var(--color-border);
  background: var(--color-surface-muted);
  font-size: 14px;
}

.onboarding-profile > footer strong {
  color: var(--color-text);
  font-size: 15px;
}

.onboarding-profile > footer small {
  color: var(--color-text-muted);
  font-size: 14px;
}

.profile-summary {
  width: min(1180px, 100%);
  margin: 0 auto 20px;
  padding: 20px 0;
  color: var(--color-text);
  border-block: 1px solid var(--color-border);
  background: var(--color-surface-subtle);
}

.profile-summary > header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding: 0 2px 16px;
}

.eyebrow {
  display: flex;
  align-items: center;
  gap: 7px;
  color: var(--color-accent);
  font-size: 14px;
  font-weight: 700;
}

.profile-summary h2 {
  margin: 5px 0 0;
  font-size: 20px;
  font-weight: 700;
  letter-spacing: 0;
}

.profile-summary header p {
  margin: 6px 0 0;
  color: var(--color-text-secondary);
  font-size: 14px;
}

.profile-summary header button {
  display: grid;
  width: 38px;
  height: 38px;
  flex: none;
  place-items: center;
  color: var(--color-text-secondary);
  border: 1px solid var(--color-border);
  border-radius: 6px;
  background: var(--color-surface);
}

.summary-state {
  display: flex;
  min-height: 96px;
  align-items: center;
  justify-content: center;
  gap: 8px;
  color: var(--color-text-muted);
  font-size: 14px;
}

.summary-state.error {
  color: var(--color-danger);
}

.summary-retry {
  min-height: 32px;
  margin-left: 4px;
  padding: 5px 10px;
  color: var(--color-text);
  border: 1px solid var(--color-border-strong);
  border-radius: 5px;
  background: var(--color-surface);
  font-size: 14px;
  font-weight: 650;
  cursor: pointer;
}

.summary-retry:disabled { color: var(--color-text-muted); cursor: not-allowed; }

.summary-stale {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 0 0 12px;
  padding: 10px 12px;
  color: var(--color-danger);
  border: 1px solid color-mix(in srgb, var(--color-danger) 28%, white);
  border-radius: 6px;
  background: var(--color-danger-soft);
  font-size: 14px;
}

.profile-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  border: 1px solid var(--color-border);
  border-radius: 8px;
  background: var(--color-surface);
}

.profile-grid article {
  min-width: 0;
  padding: 18px;
}

.profile-grid article + article {
  border-left: 1px solid var(--color-border);
}

.section-title {
  display: flex;
  align-items: center;
  gap: 9px;
  color: var(--color-accent);
}

.section-title span,
.section-title small,
.section-title strong {
  display: block;
}

.section-title small {
  color: var(--color-text-muted);
  font-size: 14px;
}

.section-title strong {
  margin-top: 2px;
  font-size: 16px;
}

.headline {
  min-height: 48px;
  margin: 14px 0;
  color: var(--color-text);
  font-size: 14px;
  font-weight: 650;
  line-height: 1.6;
}

.signal-list {
  display: grid;
  gap: 8px;
}

.signal-list span {
  display: flex;
  align-items: flex-start;
  gap: 7px;
  color: var(--color-text-secondary);
  font-size: 14px;
  line-height: 1.5;
}

.signal-list span:first-child {
  color: var(--color-accent);
}

.signal-list span:last-child {
  color: var(--color-warning);
}

details {
  margin-top: 14px;
  padding-top: 11px;
  border-top: 1px solid var(--color-border);
}

summary {
  color: var(--color-accent);
  font-size: 14px;
  font-weight: 700;
  cursor: pointer;
}

.evidence-row {
  margin-top: 10px;
  padding-left: 10px;
  border-left: 2px solid var(--color-border-strong);
}

.evidence-row strong,
.evidence-row span,
.evidence-row p {
  display: block;
  font-size: 14px;
  line-height: 1.5;
}

.evidence-row strong {
  color: var(--color-text);
}

.evidence-row span {
  margin-top: 3px;
  color: var(--color-text-muted);
  font-family: var(--font-mono);
}

.evidence-row span:has(svg) {
  display: flex;
  align-items: center;
  gap: 5px;
}

.evidence-row p {
  margin: 5px 0 0;
  color: var(--color-text-secondary);
}

.evidence-empty {
  margin-top: 9px;
  color: var(--color-text-muted);
  font-size: 14px;
}

.next-action {
  display: flex;
  width: 100%;
  min-height: 52px;
  align-items: center;
  justify-content: space-between;
  gap: 9px;
  margin-top: 14px;
  padding: 9px 11px;
  color: var(--color-text);
  border: 1px solid var(--color-border);
  border-radius: 6px;
  background: var(--color-surface-subtle);
  text-align: left;
}

.next-action span,
.next-action small,
.next-action strong {
  display: block;
}

.next-action small,
.next-action strong {
  font-size: 14px;
}

.next-action small {
  color: var(--color-text-muted);
}

.next-action strong {
  margin-top: 3px;
  line-height: 1.4;
}

.profile-summary footer {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 14px;
  padding: 13px 2px 0;
  color: var(--color-text-secondary);
  font-size: 14px;
  line-height: 1.55;
}

.profile-summary footer small {
  flex: none;
  color: var(--color-text-muted);
  font-size: 14px;
}

.profile-summary.compact {
  margin: 0 auto 12px;
  padding: 14px 0;
}

.profile-summary.compact > header {
  align-items: center;
  padding-bottom: 12px;
}

.profile-summary.compact header p {
  margin-top: 3px;
}

.compact-focus {
  border: 1px solid var(--color-border);
  border-radius: var(--radius-panel);
  background: var(--color-surface);
}

.compact-focus-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(320px, 0.8fr);
}

.compact-focus-item,
.compact-next-action {
  min-width: 0;
  padding: 16px 18px;
}

.compact-focus-item > span,
.compact-next-action small {
  display: block;
  color: var(--color-text-muted);
  font-size: 14px;
  font-weight: 600;
}

.compact-focus-item > strong,
.compact-next-action strong {
  display: block;
  margin-top: 5px;
  color: var(--color-text);
  font-size: 15px;
  line-height: 1.5;
}

.compact-next-action {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  border: 0;
  border-left: 1px solid var(--color-border);
  background: transparent;
  text-align: left;
  cursor: pointer;
}

.compact-next-action:hover {
  background: var(--color-accent-soft);
}

.compact-evidence-disclosure {
  margin: 0;
  padding: 0;
  border-top: 1px solid var(--color-border);
}

.compact-evidence-disclosure > summary {
  display: flex;
  min-height: 42px;
  align-items: center;
  justify-content: space-between;
  padding: 0 18px;
  color: var(--color-text-secondary);
  list-style: none;
}

.compact-evidence-disclosure > summary::-webkit-details-marker {
  display: none;
}

.compact-evidence-disclosure > summary::after {
  content: "+";
  margin-left: auto;
  color: var(--color-text-muted);
  font-size: 18px;
  font-weight: 400;
}

.compact-evidence-disclosure[open] > summary::after {
  content: "−";
}

.compact-evidence-disclosure > summary small {
  margin-left: 8px;
  margin-right: 10px;
  color: var(--color-text-muted);
  font-size: 14px;
  font-weight: 500;
}

.compact-evidence-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  border-top: 1px solid var(--color-border);
}

.compact-evidence-grid article {
  min-width: 0;
  padding: 16px 18px;
}

.compact-evidence-grid article + article {
  border-left: 1px solid var(--color-border);
}

.compact-evidence-grid .headline {
  min-height: 0;
  margin: 10px 0;
}

.compact-signals {
  display: grid;
  gap: 6px;
  margin-top: 10px;
}

.compact-signals span {
  display: flex;
  align-items: flex-start;
  gap: 7px;
  color: var(--color-text-secondary);
  font-size: 14px;
  line-height: 1.5;
}

.compact-boundary {
  margin: 0;
  padding: 12px 18px 14px;
  color: var(--color-text-muted);
  border-top: 1px solid var(--color-border);
  font-size: 14px;
  line-height: 1.55;
}

.spin {
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

@media (max-width: 760px) {
  .profile-grid {
    grid-template-columns: 1fr;
  }

  .compact-focus-row,
  .compact-evidence-grid {
    grid-template-columns: 1fr;
  }

  .compact-next-action,
  .compact-evidence-grid article + article {
    border-top: 1px solid var(--color-border);
    border-left: 0;
  }

  .profile-grid article + article {
    border-top: 1px solid var(--color-border);
    border-left: 0;
  }

  .profile-summary footer {
    flex-direction: column;
  }

  .profile-summary footer small {
    flex: auto;
  }

  .headline {
    min-height: 0;
  }
}

</style>
