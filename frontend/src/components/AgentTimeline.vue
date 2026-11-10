<script setup>
import { displayLabel, learningText } from '../utils/learningCopy.js'
import { claimEvidenceStatus, answerRevisionEntries } from '../utils/claimEvidencePresentation.js'
import { computed, ref } from 'vue'
import { translatePublicText, eventStepKey, presentRunEvents, runRoleLabel } from '../utils/agentRunPresentation.js'
import SourceCitation from './SourceCitation.vue'
import IncrementalMarkdownRenderer from './IncrementalMarkdownRenderer.vue'
import {
  AlertCircle,
  CheckCircle2,
  ChevronDown,
  Circle,
  LoaderCircle,
  OctagonX,
  PauseCircle,
} from '@lucide/vue'

const props = defineProps({
  audit: { type: Object, default: null },
  runEvents: { type: Array, default: () => [] },
  claims: { type: Array, default: () => [] },
  answerRevision: { type: Object, default: null },
  answerRevisionHistory: { type: Array, default: () => [] },
  sourceRefs: { type: Array, default: () => [] },
  returnTo: { type: String, default: '' },
  compact: { type: Boolean, default: true },
  hideCompleted: { type: Boolean, default: false },
})
const emit = defineEmits(['source-opened'])
const revisionEntries = computed(() => answerRevisionEntries(props.answerRevision, props.answerRevisionHistory))

const claimCards = computed(() => props.claims.filter(item => item && typeof item.claim === 'string').map((item, index) => {
  const sourceRefIds = Array.isArray(item.sourceRefIds) ? item.sourceRefIds : []
  const citations = Array.isArray(item.citations) ? item.citations : []
  const sources = citations.length ? citations.map(citation => {
    const matches = props.sourceRefs.filter(source => (source.source_ref_id || source.sourceRefId || source.id) === citation.sourceRefId)
    const source = matches.find(source => citation.charStart != null
      && Number(source.charStart ?? source.char_start) <= citation.charStart
      && Number(source.charEnd ?? source.char_end) >= citation.charEnd) || matches[0] || {}
    return { ...source, ...citation }
  }) : sourceRefIds.map(id => props.sourceRefs.find(source => (source.source_ref_id || source.sourceRefId || source.id) === id) || { source_ref_id: id })
  const hasText = ([, value]) => typeof value === 'string' && value.trim()
  const review = [
    ['适用条件', item.conditions],
    ['调整说明', item.review?.revision || (item.revisionNeeded === true ? item.supportReason : '')],
  ].filter(hasText)
  const shown = new Set(review.map(([, value]) => learningText(value).replace(/\s+/g, ' ').trim()))
  const reviewDetails = [
    ['判断依据', item.supportReason],
    ['边界检查', item.review?.challenger],
    ['内容核对', item.review?.verifier],
  ].filter(hasText).filter(([, value]) => {
    const text = learningText(value).replace(/\s+/g, ' ').trim()
    if (shown.has(text)) return false
    shown.add(text)
    return true
  })
  return {
    id: item.claimId || item.claim_id || `claim-${index}`,
    claim: learningText(item.claim),
    ...claimEvidenceStatus(item),
    quote: typeof item.quote === 'string' ? item.quote : '',
    location: item.quoteVerified && typeof item.location === 'string' ? item.location : '',
    sources,
    review,
    reviewDetails,
  }
}))

function claimLocation(value) {
  if (/\bnode-[\w-]+\s*\/\s*summary\b/i.test(value)) return '当前思维导图节点'
  if (/\broot\s*\/\s*summary\b/i.test(value)) return '当前思维导图概览'
  return learningText(value)
}

const expanded = ref(new Set())
const roleOrder = ['analysis', 'generation', 'validation', 'decision']
const roleLabels = {
  analysis: '分析',
  generation: '生成',
  validation: '校验',
  decision: '决策',
}
const statusLabels = {
  pending: '尚未开始',
  queued: '等待执行',
  running: '进行中',
  completed: '已完成',
  failed: '失败',
  stopped: '已停止',
  recorded: '过程记录',
  previous_failed: '前次未完成',
  unknown: '记录不完整',
  needs_input: '待补充输入',
  waiting_configuration: '等待服务恢复',
}
const stageLabels = {
  question_understanding: '问题理解',
  answer_generation: '内容讲解',
  answer_organization: '回答整理',
  context: '相关知识整理',
  safety_boundary: '内容检查',
  profile_adaptation: '学习安排',
  context_check: '相关知识梳理',
  retrieval: '内容查找',
  subject_expert: '学科讲解',
  challenger: '边界检查',
  evidence_verification: '内容核对',
  answer_revision: '讲解修订',
  revision_verification: '修订核对',
  pedagogical: '表达整理',
  synthesizer: '回答整理',
  professional_chain: '深入回答',
  resource_planning: '资源规划',
  resource_generation: '资源生成',
  review_gate: '质量审核',
  publish: '资源发布',
}
const resourceTypeLabels = {
  handout: '个性化讲义',
  mind_map: '思维导图',
  quiz: '测验题',
  training_task: '实训任务书',
  code_sandbox: '代码沙盒',
  video: '视频推荐',
  deck: 'PPT/网页课件',
  interactive_model: '可交互模型',
  feynman: '费曼复述',
}
const ownerLabels = {
  'Chat Orchestrator': '问题梳理',
  'Context Builder': '相关知识整理',
  'Answer Agent': '内容讲解',
  Router: '问题理解',
  Retrieval: '内容查找',
  'Subject Expert': '学科讲解',
  Challenger: '边界检查',
  Verifier: '内容核对',
  Synthesizer: '回答整理',
  'Pedagogical Agent': '表达整理',
  'Resource Planner': '资源安排',
  'Resource Generator': '内容生成',
  'Resource Reviewer': '质量检查',
  Publisher: '保存资源',
  Supervisor: '进度协调',
}
const eventLabels = {
  'run.started': '开始处理',
  'stage.started': '阶段开始',
  'stage.completed': '阶段完成',
  'stage.failed': '阶段失败',
  'claim.checked': '结论已检查',
  'source.bound': '相关内容已准备',
  'resource.item.started': '资源项开始生成',
  'resource.item.completed': '资源项生成完成',
  'run.completed': '处理完成',
}

function firstValue(source, ...keys) {
  for (const key of keys) {
    const value = source?.[key]
    if (value !== undefined && value !== null && value !== '') return value
  }
  return null
}

function normalizeItem(item) {
  const role = String(firstValue(item, 'role') || '')
  if (!roleOrder.includes(role)) return null
  return {
    id: String(firstValue(item, 'runId', 'run_id') || role),
    role,
    status: String(firstValue(item, 'status') || 'pending'),
    inputRefs: firstValue(item, 'inputRefs', 'input_refs') || [],
    candidateSummary: translatePublicText(firstValue(item, 'candidateSummary', 'candidate_summary') || ''),
    disagreement: translatePublicText(firstValue(item, 'disagreement') || ''),
    validation: translatePublicText(firstValue(item, 'validation') || ''),
    revision: translatePublicText(firstValue(item, 'revision') || ''),
    decisionSummary: translatePublicText(firstValue(item, 'decisionSummary', 'decision_summary') || ''),
  }
}

function normalizeEvent(item, index) {
  const eventType = String(firstValue(item, 'eventType', 'event_type') || '')
  if (!eventType) return null
  const owner = String(firstValue(item, 'owner') || 'Chat Orchestrator')
  const stageId = String(firstValue(item, 'stageId', 'stage_id') || '')
  const resourceType = String(
    firstValue(item, 'resourceType', 'resource_type')
    || (stageId.startsWith('resource:') ? stageId.slice('resource:'.length) : ''),
  )
  const stageLabel = resourceType ? (resourceTypeLabels[resourceType] || '资源项') : stageLabels[stageId]
  return {
    id: String(firstValue(item, 'eventId', 'event_id') || `${eventType}-${index}`),
    role: runRoleLabel(ownerLabels[owner] || '学习助手', stageLabel),
    status: String(firstValue(item, 'publicStatus', 'public_status', 'status') || 'pending'),
    inputRefs: firstValue(item, 'inputRefs', 'input_refs') || [],
    outputRefs: firstValue(item, 'outputRefs', 'output_refs') || [],
    candidateSummary: translatePublicText(firstValue(item, 'summary') || eventLabels[eventType] || '阶段处理中'),
    disagreement: '',
    validation: eventType.includes('review') ? translatePublicText(firstValue(item, 'summary') || '') : '',
    revision: '',
    decisionSummary: String(firstValue(item, 'retryable') ? '失败项可重试' : ''),
    eventType,
    eventLabel: eventLabels[eventType] || '协作阶段',
    resourceType,
    resourceItemId: String(firstValue(item, 'resourceItemId', 'resource_item_id') || ''),
    stageId,
  }
}

function latestEventItems(items) {
  const latest = new Map()
  for (const item of items) latest.set(eventStepKey(item), item)
  return [...latest.values()]
}

const normalizedAudit = computed(() => {
  if ((!props.audit || typeof props.audit !== 'object') && !props.runEvents.length) return null
  const sourceEvents = props.runEvents.length
    ? props.runEvents
    : (props.audit.events || [])
  const overallStatus = String(firstValue(props.audit, 'status') || props.runEvents.at(-1)?.publicStatus || 'pending')
  const eventItems = presentRunEvents(sourceEvents.map(normalizeEvent).filter(Boolean), overallStatus)
  const currentEventItems = latestEventItems(eventItems)
  const hasResourceFailure = currentEventItems.some((item) => (
    item.resourceType && item.status === 'failed'
  ))
  const visibleEventItems = currentEventItems.filter((item) => !(
    item.eventType === 'run.failed' && hasResourceFailure
  ))
  const allItems = eventItems.length
    ? (props.hideCompleted ? visibleEventItems : eventItems)
    : (props.audit.items || []).map(normalizeItem).filter(Boolean)
  const items = props.hideCompleted
    ? allItems.filter((item) => item.status !== 'completed')
    : allItems
  const resourceStates = new Map()
  for (const item of currentEventItems) {
    if (item.eventType.startsWith('resource.item')) {
      const key = item.resourceType || item.resourceItemId
      if (!key) continue
      resourceStates.set(key, item.status)
      continue
    }
  }
  const resourceValues = [...resourceStates.values()]
  return {
    runId: String(firstValue(props.audit, 'runId', 'run_id') || props.runEvents[0]?.runId || ''),
    mode: String(firstValue(props.audit, 'mode') || 'live'),
    status: overallStatus,
    items,
    resourceProgress: resourceValues.length
      ? {
          total: resourceValues.length,
          completed: resourceValues.filter((status) => status === 'completed').length,
          failed: resourceValues.filter((status) => status === 'failed').length,
        }
      : null,
    historicalResult: firstValue(props.audit, 'historicalResult', 'historical_result'),
    fromEvents: eventItems.length > 0,
  }
})

function summary(item) {
  return learningText(item.candidateSummary || item.validation || item.decisionSummary || statusLabels[item.status], '暂时没有新的进展')
}

function details(item) {
  return [
    ['当前进展', item.candidateSummary],
    ['需要留意', item.disagreement],
    ['检查结果', item.validation],
    ['调整内容', item.revision],
    ['完成情况', item.decisionSummary],
  ].map(([label, value]) => [label, learningText(value)]).filter(([, value]) => Boolean(value))
}

function toggle(item) {
  if (!details(item).length) return
  const next = new Set(expanded.value)
  if (next.has(item.id)) next.delete(item.id)
  else next.add(item.id)
  expanded.value = next
}

function statusIcon(status) {
  if (status === 'completed') return CheckCircle2
  if (status === 'running') return LoaderCircle
  if (status === 'failed') return OctagonX
  if (status === 'stopped') return PauseCircle
  return Circle
}

function statusLabel(status) {
  return statusLabels[status] || '处理中'
}

</script>

<template>
  <section class="agent-audit" :class="{ compact }" data-testid="agent-audit-timeline">
    <header class="agent-audit__heading">
      <div>
        <strong>回答过程</strong>
      </div>
      <span v-if="normalizedAudit" class="agent-audit__overall" :data-status="normalizedAudit.status">
        {{ statusLabel(normalizedAudit.status) }}
      </span>
    </header>

    <p v-if="normalizedAudit?.mode === 'frozen_demo'" class="agent-audit__empty">这是之前保存的演示内容，并非本次生成。</p>

    <div v-if="normalizedAudit?.resourceProgress" class="agent-audit__progress" data-testid="agent-audit-resource-progress">
      <strong>资源进度</strong>
      <span>{{ normalizedAudit.resourceProgress.completed }}/{{ normalizedAudit.resourceProgress.total }}</span>
      <small v-if="normalizedAudit.resourceProgress.failed">· {{ normalizedAudit.resourceProgress.failed }} 项失败，可重试</small>
    </div>

    <p v-if="(!normalizedAudit || !normalizedAudit.items.length) && !hideCompleted" class="agent-audit__empty">
      暂时没有处理进展。
    </p>

    <ol v-else-if="normalizedAudit?.items.length" class="agent-audit__steps">
      <li v-for="item in normalizedAudit.items" :key="item.id" :data-status="item.status">
        <button type="button" :disabled="!details(item).length" :aria-expanded="expanded.has(item.id)" @click="toggle(item)">
          <component :is="statusIcon(item.status)" :size="17" :class="{ spin: item.status === 'running' }" />
          <span class="agent-audit__step-copy">
            <strong>{{ roleLabels[item.role] || displayLabel(item.role, '学习助手') }}</strong>
            <small>{{ summary(item) }}</small>
          </span>
          <span class="agent-audit__status">{{ statusLabel(item.status) }}</span>
          <ChevronDown v-if="details(item).length" :size="16" class="agent-audit__chevron" :class="{ open: expanded.has(item.id) }" />
        </button>

        <dl v-if="expanded.has(item.id)" class="agent-audit__details">
          <div v-for="([label, value]) in details(item)" :key="label">
            <dt>{{ label }}</dt>
            <dd v-if="Array.isArray(value)">
              <span v-for="entry in value" :key="entry">{{ entry }}</span>
            </dd>
            <dd v-else>{{ value }}</dd>
          </div>
        </dl>
      </li>
    </ol>

    <details v-for="entry in revisionEntries" :key="entry.key" class="claim-evidence" data-testid="answer-revision">
      <summary class="claim-evidence__heading"><strong>{{ entry.title }}</strong><ChevronDown :size="16" class="claim-evidence__chevron" aria-hidden="true" /></summary>
      <p>{{ entry.presentation.message }}</p>
      <div v-for="issue in entry.issues" :key="issue.claim" class="claim-evidence__card">
        <strong>{{ learningText(issue.claim) }}</strong>
        <p v-if="issue.reason">{{ learningText(issue.reason) }}</p>
      </div>
      <details><summary>查看修订前的讲解</summary><IncrementalMarkdownRenderer :text="entry.revision.before" type="lesson" /></details>
      <details><summary>{{ entry.presentation.afterLabel }}</summary><IncrementalMarkdownRenderer :text="entry.revision.after" type="lesson" /></details>
    </details>

    <details v-if="claimCards.length" class="claim-evidence" data-testid="claim-evidence-list">
      <summary class="claim-evidence__heading"><strong>结论与来源</strong><span>{{ claimCards.length }} 条</span><ChevronDown :size="16" class="claim-evidence__chevron" aria-hidden="true" /></summary>
      <article v-for="claim in claimCards" :key="claim.id" class="claim-evidence__card" data-testid="claim-evidence-card">
        <div class="claim-evidence__card-heading">
          <span class="claim-evidence__support" :data-support="claim.support">{{ claim.label }}</span>
        </div>
        <p class="claim-evidence__claim">{{ learningText(claim.claim) }}</p>
        <blockquote v-if="claim.quote" class="claim-evidence__quote">{{ claim.quote }}</blockquote>
        <p v-if="claim.location" class="claim-evidence__label">{{ claimLocation(claim.location) }}</p>
        <div v-if="claim.sources.length" class="claim-evidence__sources">
          <SourceCitation v-for="(source, index) in claim.sources" :key="`${source.source_ref_id || source.sourceRefId || source.id}:${source.charStart ?? index}`" :source="source" :return-to="returnTo" compact @navigation-complete="emit('source-opened')" />
        </div>
        <p v-else-if="!['worked_example', 'source_scope'].includes(claim.support)" class="claim-evidence__unbound">这条结论尚未关联可核对的资料。</p>
        <dl v-if="claim.review.length" class="claim-evidence__review">
          <div v-for="([label, value]) in claim.review" :key="label"><dt>{{ label }}</dt><dd>{{ learningText(value) }}</dd></div>
        </dl>
        <details v-if="claim.reviewDetails.length" class="claim-evidence__detail" data-testid="claim-review-details">
          <summary>查看核对说明</summary>
          <dl class="claim-evidence__review">
            <div v-for="([label, value]) in claim.reviewDetails" :key="label"><dt>{{ label }}</dt><dd>{{ learningText(value) }}</dd></div>
          </dl>
        </details>
      </article>
    </details>

    <div v-if="normalizedAudit?.historicalResult" class="agent-audit__history">
      <AlertCircle :size="17" />
      <div>
        <strong>{{ normalizedAudit.historicalResult.label || '历史已完成回答（非本次结果）' }}</strong>
        <p v-if="normalizedAudit.historicalResult.preview">{{ normalizedAudit.historicalResult.preview }}</p>
        <RouterLink v-if="normalizedAudit.historicalResult.route" :to="normalizedAudit.historicalResult.route">查看历史回答</RouterLink>
      </div>
    </div>
  </section>
</template>

<style scoped>
.agent-audit {
  color: var(--color-text, var(--color-text));
  background: var(--color-surface, #ffffff);
}

.agent-audit__heading {
  display: flex;
  min-height: 50px;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  border-bottom: 1px solid var(--color-border, var(--color-border));
  padding: 8px 0;
}

.agent-audit__heading > div {
  display: grid;
  min-width: 0;
  gap: 2px;
}

.agent-audit__heading strong,
.agent-audit__heading span,
.agent-audit__overall,
.agent-audit__empty,
.agent-audit__steps strong,
.agent-audit__steps small,
.agent-audit__status,
.agent-audit__details dt,
.agent-audit__details dd,
.agent-audit__history strong,
.agent-audit__history p,
.agent-audit__history a {
  font-size: 14px;
}

.agent-audit__heading > div > span,
.agent-audit__steps small,
.agent-audit__details dt {
  color: var(--color-text-muted, var(--color-text-muted));
}

.agent-audit__overall {
  flex: 0 0 auto;
  color: var(--color-text-secondary, var(--color-text-secondary));
}

.agent-audit__overall[data-status="failed"],
.agent-audit__overall[data-status="stopped"],
.agent-audit__steps li[data-status="failed"],
.agent-audit__steps li[data-status="stopped"] {
  color: var(--color-danger, var(--color-danger));
}

.agent-audit__progress {
  display: flex;
  align-items: baseline;
  gap: 7px;
  min-height: 36px;
  padding: 8px 0;
  border-bottom: 1px solid var(--color-border, var(--color-border));
  font-size: 14px;
}

.agent-audit__progress span {
  color: var(--color-text-secondary, var(--color-text-secondary));
  font-weight: 650;
}

.agent-audit__progress small {
  color: var(--color-danger, var(--color-danger));
}

.agent-audit__empty {
  margin: 0;
  padding: 14px 0;
  color: var(--color-text-muted, var(--color-text-muted));
  line-height: 1.6;
}

.agent-audit__steps {
  display: grid;
  margin: 0;
  padding: 0;
  list-style: none;
}

.agent-audit__steps > li {
  border-bottom: 1px solid var(--color-border, var(--color-border));
}

.agent-audit__steps button {
  display: grid;
  width: 100%;
  min-height: 62px;
  grid-template-columns: 20px minmax(0, 1fr) auto 16px;
  align-items: center;
  gap: 8px;
  border: 0;
  padding: 9px 0;
  color: inherit;
  background: transparent;
  text-align: left;
  cursor: pointer;
}

.agent-audit__steps button:hover:not(:disabled) {
  background: var(--color-surface-subtle, var(--color-surface-subtle));
}

.agent-audit__steps button:focus-visible,
.agent-audit__history a:focus-visible {
  outline: 2px solid var(--color-accent, var(--color-text));
  outline-offset: 2px;
}

.agent-audit__steps button:disabled {
  cursor: default;
}

.agent-audit__step-copy {
  display: grid;
  min-width: 0;
  gap: 2px;
}

.agent-audit__step-copy strong {
  font-weight: 620;
}

.agent-audit__step-copy small {
  display: -webkit-box;
  overflow: hidden;
  line-height: 1.45;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}

.agent-audit__status {
  white-space: nowrap;
}

.agent-audit__chevron {
  transition: transform .16s ease-out;
}

.agent-audit__chevron.open {
  transform: rotate(180deg);
}

.agent-audit__details {
  display: grid;
  gap: 10px;
  margin: 0;
  padding: 0 0 14px 28px;
}

.agent-audit__details > div {
  display: grid;
  gap: 3px;
}

.agent-audit__details dt,
.agent-audit__details dd {
  margin: 0;
  line-height: 1.55;
  overflow-wrap: anywhere;
}

.agent-audit__details dd {
  color: var(--color-text-secondary, var(--color-text-secondary));
}

.agent-audit__details dd span {
  display: block;
}

.agent-audit__history {
  display: grid;
  grid-template-columns: 20px minmax(0, 1fr);
  gap: 9px;
  padding: 12px 0;
  color: var(--color-danger, var(--color-danger));
}

.agent-audit__history p {
  margin: 3px 0;
  color: var(--color-text-secondary, var(--color-text-secondary));
  line-height: 1.5;
}

.agent-audit__history a {
  color: var(--color-text, var(--color-text));
  text-underline-offset: 3px;
}

.claim-evidence {
  margin-top: 8px;
  border-top: 1px solid var(--color-border, var(--color-border));
}

.claim-evidence > :not(summary) {
  margin-top: 10px;
}

.claim-evidence[open] {
  padding-bottom: 8px;
}

.claim-evidence__heading,
.claim-evidence__card-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.claim-evidence__heading {
  min-height: 40px;
  padding: 8px 0;
  box-sizing: border-box;
  cursor: pointer;
  list-style: none;
}

.claim-evidence__heading::-webkit-details-marker {
  display: none;
}

.claim-evidence__heading > strong {
  flex: 1;
}

.claim-evidence__heading:focus-visible {
  outline: 2px solid var(--color-border-strong, #8095a5);
  outline-offset: 2px;
  border-radius: 3px;
}

.claim-evidence__chevron {
  flex-shrink: 0;
  transform: rotate(-90deg);
}

.claim-evidence[open] > summary .claim-evidence__chevron {
  transform: rotate(0deg);
}

.claim-evidence__heading strong,
.claim-evidence__heading span,
.claim-evidence__card-heading strong,
.claim-evidence__support,
.claim-evidence__label,
.claim-evidence__facts dt,
.claim-evidence__facts dd,
.claim-evidence__review dt,
.claim-evidence__review dd,
.claim-evidence__claim,
.claim-evidence__quote,
.claim-evidence__unbound {
  font-size: 14px;
  line-height: 1.55;
}

.claim-evidence__heading span,
.claim-evidence__facts dt,
.claim-evidence__review dt,
.claim-evidence__label {
  color: var(--color-text-muted, var(--color-text-muted));
}

.claim-evidence__card {
  display: grid;
  gap: 8px;
  min-width: 0;
  padding: 12px;
  border: 1px solid var(--color-border, var(--color-border));
  border-radius: 8px;
  background: var(--color-surface-subtle, var(--color-surface-subtle));
}

.claim-evidence__card-heading strong {
  font-weight: 680;
}

.claim-evidence__card + .claim-evidence__card {
  margin-top: 8px;
}

.claim-evidence__support {
  padding: 2px 7px;
  border-radius: 999px;
  color: var(--color-text-secondary, var(--color-text-secondary));
  background: var(--color-surface, #ffffff);
  white-space: nowrap;
}

.claim-evidence__support[data-support="supported"] {
  color: var(--color-success);
}

.claim-evidence__support[data-support="partially_supported"] {
  color: var(--color-warning);
}

.claim-evidence__support[data-support="contradicted"],
.claim-evidence__support[data-support="unsupported"] {
  color: var(--color-danger, var(--color-danger));
}

.claim-evidence__claim,
.claim-evidence__quote,
.claim-evidence__unbound {
  margin: 0;
  overflow-wrap: anywhere;
}

.claim-evidence__claim {
  color: var(--color-text, var(--color-text));
  font-weight: 620;
}

.claim-evidence__facts,
.claim-evidence__review {
  display: grid;
  gap: 6px;
  margin: 0;
}

.claim-evidence__facts > div,
.claim-evidence__review > div {
  display: grid;
  grid-template-columns: minmax(70px, auto) minmax(0, 1fr);
  gap: 9px;
  align-items: start;
}

.claim-evidence__facts dt,
.claim-evidence__facts dd,
.claim-evidence__review dt,
.claim-evidence__review dd {
  margin: 0;
  overflow-wrap: anywhere;
}

.claim-evidence__facts dd,
.claim-evidence__review dd {
  color: var(--color-text-secondary, var(--color-text-secondary));
}

.claim-evidence__quote {
  padding: 8px 10px;
  border-left: 3px solid var(--color-border-strong, #b8c2c6);
  color: var(--color-text-secondary, var(--color-text-secondary));
  background: var(--color-surface, #ffffff);
}

.claim-evidence__sources {
  display: grid;
  gap: 3px;
}

.claim-evidence__detail > summary {
  width: fit-content;
  color: var(--color-text-secondary, var(--color-text-secondary));
  font-size: 14px;
  line-height: 1.55;
  cursor: pointer;
}

.claim-evidence__detail[open] > summary {
  margin-bottom: 8px;
}

.claim-evidence__unbound {
  color: var(--color-danger, var(--color-danger));
}

.spin {
  animation: agent-audit-spin .8s linear infinite;
}

@keyframes agent-audit-spin {
  to { transform: rotate(360deg); }
}
</style>
