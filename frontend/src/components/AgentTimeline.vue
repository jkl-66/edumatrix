<script setup>
import { computed, ref } from 'vue'
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
  sourceRefs: { type: Array, default: () => [] },
  returnTo: { type: String, default: '' },
  compact: { type: Boolean, default: true },
  hideCompleted: { type: Boolean, default: false },
})

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
  needs_input: '待补充输入',
}
const stageLabels = {
  question_understanding: '问题理解',
  context_check: '相关知识梳理',
  retrieval: '内容查找',
  subject_expert: '学科讲解',
  challenger: '边界检查',
  evidence_verification: '内容核对',
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
const publicRoleTerms = [
  ['Evidence Verifier', '内容核对'],
  ['Pedagogical Agent', '表达整理'],
  ['Resource Reviewer', '质量检查'],
  ['Resource Planner', '资源安排'],
  ['Resource Generator', '内容生成'],
  ['Chat Orchestrator', '问题梳理'],
  ['Context Builder', '相关知识整理'],
  ['Subject Expert', '学科讲解'],
  ['Answer Agent', '内容讲解'],
  ['Synthesizer', '回答整理'],
  ['Challenger', '边界检查'],
  ['Publisher', '保存资源'],
  ['Retrieval', '内容查找'],
  ['Router', '问题理解'],
  ['Verifier', '内容核对'],
  ['Supervisor', '进度协调'],
  [' Agent', ''],
]

function translatePublicText(value) {
  let text = String(value ?? '')
  for (const [from, to] of publicRoleTerms) text = text.split(from).join(to)
  return text
    .replace(/已冻结课程、来源和\s*\d+\s*个附件的本次上下文/g, '已整理课程内容和附件')
    .replace(/已冻结课程、来源/g, '已整理课程内容')
    .replace(/\b(?:f\d+-)?(?:kp|event|trace|run|claim|source|task|chat)-[a-z0-9-]{4,}\b/gi, '')
    .replace(/\b[a-f0-9]{24,}\b/gi, '')
    .replace(/source_ref(?:_id)?/gi, '')
    .replace(/课程来源/g, '相关内容')
    .replace(/上下文/g, '相关内容')
    .replace(/来源/g, '参考材料')
    .replace(/证据核验/g, '内容核对')
    .replace(/确定性/g, '稳定')
    .replace(/冻结/g, '')
    .replace(/\s{2,}/g, ' ')
    .trim()
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
  const suffix = resourceType
    ? ` · ${resourceTypeLabels[resourceType] || '资源项'}`
    : stageId
      ? ` · ${stageLabels[stageId] || '协作阶段'}`
      : ''
  return {
    id: String(firstValue(item, 'eventId', 'event_id') || `${eventType}-${index}`),
    role: `${ownerLabels[owner] || '协作智能体'}${suffix}`,
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

function eventStepKey(item) {
  if (item.eventType.startsWith('run.')) return 'run'
  if (item.resourceType) return `resource:${item.resourceType}`
  if (item.resourceItemId) return `resource-item:${item.resourceItemId}`
  if (item.stageId) return `stage:${item.stageId}`
  return `event:${item.eventType}:${item.id}`
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
  const eventItems = sourceEvents.map(normalizeEvent).filter(Boolean)
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
  const stageKeys = new Set()
  const resourceStates = new Map()
  for (const item of currentEventItems) {
    if (item.eventType.startsWith('resource.item')) {
      const key = item.resourceType || item.resourceItemId
      if (!key) continue
      resourceStates.set(key, item.status)
      continue
    }
    const key = eventStepKey(item)
    if (key && !item.eventType.startsWith('claim.')) stageKeys.add(key)
  }
  const resourceValues = [...resourceStates.values()]
  return {
    runId: String(firstValue(props.audit, 'runId', 'run_id') || props.runEvents[0]?.runId || ''),
    mode: String(firstValue(props.audit, 'mode') || 'live'),
    status: String(firstValue(props.audit, 'status') || props.runEvents.at(-1)?.publicStatus || 'pending'),
    items,
    stageCount: stageKeys.size || allItems.length,
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
  return item.candidateSummary || item.validation || item.decisionSummary || statusLabels[item.status] || '状态未记录'
}

function details(item) {
  return [
    ['当前进展', item.candidateSummary],
    ['需要留意', item.disagreement],
    ['检查结果', item.validation],
    ['调整内容', item.revision],
    ['完成情况', item.decisionSummary],
  ].filter(([, value]) => Array.isArray(value) ? value.length : Boolean(value))
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
        <span v-if="normalizedAudit">{{ normalizedAudit.stageCount }} 个步骤</span>
      </div>
      <span v-if="normalizedAudit" class="agent-audit__overall" :data-status="normalizedAudit.status">
        {{ statusLabel(normalizedAudit.status) }}
      </span>
    </header>

    <div v-if="normalizedAudit?.resourceProgress" class="agent-audit__progress" data-testid="agent-audit-resource-progress">
      <strong>资源进度</strong>
      <span>{{ normalizedAudit.resourceProgress.completed }}/{{ normalizedAudit.resourceProgress.total }}</span>
      <small v-if="normalizedAudit.resourceProgress.failed">· {{ normalizedAudit.resourceProgress.failed }} 项失败，可重试</small>
    </div>

    <p v-if="!normalizedAudit || !normalizedAudit.items.length" class="agent-audit__empty">
      {{ normalizedAudit && hideCompleted ? '当前没有正在执行的协作项。' : '当前没有可公开的处理记录。' }}
    </p>

    <ol v-else class="agent-audit__steps">
      <li v-for="item in normalizedAudit.items" :key="item.id" :data-status="item.status">
        <button type="button" :disabled="!details(item).length" :aria-expanded="expanded.has(item.id)" @click="toggle(item)">
          <component :is="statusIcon(item.status)" :size="17" :class="{ spin: item.status === 'running' }" />
          <span class="agent-audit__step-copy">
            <strong>{{ roleLabels[item.role] || item.role }}</strong>
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

    <div v-if="normalizedAudit?.historicalResult" class="agent-audit__history">
      <AlertCircle :size="17" />
      <div>
        <strong>{{ normalizedAudit.historicalResult.label || '可以查看之前的回答' }}</strong>
        <p v-if="normalizedAudit.historicalResult.preview">{{ normalizedAudit.historicalResult.preview }}</p>
        <RouterLink v-if="normalizedAudit.historicalResult.route" :to="normalizedAudit.historicalResult.route">查看历史回答</RouterLink>
      </div>
    </div>
  </section>
</template>

<style scoped>
.agent-audit {
  color: var(--color-text, #06141b);
  background: var(--color-surface, #ffffff);
}

.agent-audit__heading {
  display: flex;
  min-height: 50px;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  border-bottom: 1px solid var(--color-border, #dce2e3);
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
  color: var(--color-text-muted, #60727c);
}

.agent-audit__overall {
  flex: 0 0 auto;
  color: var(--color-text-secondary, #4a5c6a);
}

.agent-audit__overall[data-status="failed"],
.agent-audit__overall[data-status="stopped"],
.agent-audit__steps li[data-status="failed"],
.agent-audit__steps li[data-status="stopped"] {
  color: var(--color-danger, #8b3d35);
}

.agent-audit__progress {
  display: flex;
  align-items: baseline;
  gap: 7px;
  min-height: 36px;
  padding: 8px 0;
  border-bottom: 1px solid var(--color-border, #dce2e3);
  font-size: 14px;
}

.agent-audit__progress span {
  color: var(--color-text-secondary, #4a5c6a);
  font-weight: 650;
}

.agent-audit__progress small {
  color: var(--color-danger, #8b3d35);
}

.agent-audit__empty {
  margin: 0;
  padding: 14px 0;
  color: var(--color-text-muted, #60727c);
  line-height: 1.6;
}

.agent-audit__steps {
  display: grid;
  margin: 0;
  padding: 0;
  list-style: none;
}

.agent-audit__steps > li {
  border-bottom: 1px solid var(--color-border, #dce2e3);
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
  background: var(--color-surface-subtle, #eef2f2);
}

.agent-audit__steps button:focus-visible,
.agent-audit__history a:focus-visible {
  outline: 2px solid var(--color-accent, #11212d);
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
  color: var(--color-text-secondary, #4a5c6a);
}

.agent-audit__details dd span {
  display: block;
}

.agent-audit__history {
  display: grid;
  grid-template-columns: 20px minmax(0, 1fr);
  gap: 9px;
  padding: 12px 0;
  color: var(--color-danger, #8b3d35);
}

.agent-audit__history p {
  margin: 3px 0;
  color: var(--color-text-secondary, #4a5c6a);
  line-height: 1.5;
}

.agent-audit__history a {
  color: var(--color-text, #06141b);
  text-underline-offset: 3px;
}

.claim-evidence {
  display: grid;
  gap: 10px;
  margin-top: 14px;
  padding-top: 14px;
  border-top: 1px solid var(--color-border, #dce2e3);
}

.claim-evidence__heading,
.claim-evidence__card-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
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
  color: var(--color-text-muted, #60727c);
}

.claim-evidence__card {
  display: grid;
  gap: 8px;
  min-width: 0;
  padding: 12px;
  border: 1px solid var(--color-border, #dce2e3);
  border-radius: 8px;
  background: var(--color-surface-subtle, #f7f9f9);
}

.claim-evidence__card-heading strong {
  font-weight: 680;
}

.claim-evidence__support {
  padding: 2px 7px;
  border-radius: 999px;
  color: var(--color-text-secondary, #4a5c6a);
  background: var(--color-surface, #ffffff);
  white-space: nowrap;
}

.claim-evidence__support[data-support="supported"] {
  color: #2f6046;
}

.claim-evidence__support[data-support="partially_supported"] {
  color: #765b25;
}

.claim-evidence__support[data-support="contradicted"],
.claim-evidence__support[data-support="unsupported"] {
  color: var(--color-danger, #8b3d35);
}

.claim-evidence__claim,
.claim-evidence__quote,
.claim-evidence__unbound {
  margin: 0;
  overflow-wrap: anywhere;
}

.claim-evidence__claim {
  color: var(--color-text, #06141b);
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
  color: var(--color-text-secondary, #4a5c6a);
}

.claim-evidence__quote {
  padding: 8px 10px;
  border-left: 3px solid var(--color-border-strong, #b8c2c6);
  color: var(--color-text-secondary, #4a5c6a);
  background: var(--color-surface, #ffffff);
}

.claim-evidence__sources {
  display: grid;
  gap: 3px;
}

.claim-evidence__unbound {
  color: var(--color-danger, #8b3d35);
}

.spin {
  animation: agent-audit-spin .8s linear infinite;
}

@keyframes agent-audit-spin {
  to { transform: rotate(360deg); }
}
</style>
