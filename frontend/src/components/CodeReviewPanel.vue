<script setup>
import { computed, ref, watch } from 'vue'
import {
  AlertCircle,
  Bot,
  CheckCircle2,
  ChevronDown,
  FileDiff,
  LoaderCircle,
  ShieldAlert,
  Sparkles,
  TriangleAlert,
} from '@lucide/vue'
import { applyCodeReview, createCodeReview, getLatestCodeReview } from '../api/codeSandbox'

const props = defineProps({
  resourceId: { type: String, required: true },
  run: { type: Object, default: null },
  resourceLockVersion: { type: Number, required: true },
})

const emit = defineEmits(['applied'])

const focus = ref('')
const review = ref(null)
const loading = ref(false)
const generating = ref(false)
const applying = ref(false)
const error = ref('')
const notice = ref('')
let loadSequence = 0

const eligibleStatuses = new Set(['success', 'runtime_error', 'timeout'])
const eligible = computed(() => Boolean(props.run && eligibleStatuses.has(props.run.status)))
const evidenceLabel = computed(() => {
  if (!props.run) return '尚未选择运行记录'
  return `${statusLabel(props.run.status)} · ${shortId(props.run.runAttemptId)}`
})
const disabledReason = computed(() => {
  if (!props.run) return '请先运行当前代码，或从左侧历史选择一条已经结束的真实运行。'
  if (['queued', 'running'].includes(props.run.status)) return '本次运行尚未结束，结束后才能基于完整证据生成点评。'
  if (props.run.status === 'stopped') return '主动停止的运行缺少完整结果，请重新运行后再点评。'
  return ''
})
const applied = computed(() => review.value?.application || null)
const reviewModeLabel = computed(() => {
  if (!review.value) return '点评模式将在结果中明确标注'
  if (review.value.reviewMode === 'model_generated' && review.value.modelState === 'completed') {
    return '真实模型点评 · 已结合本次运行结果'
  }
  return '真实模型点评'
})

function message(caught, fallback = '代码点评暂时不可用，请稍后重试。') {
  const value = caught?.response?.data?.detail || caught?.detail
  return value?.message || (typeof value === 'string' ? value : '') || caught?.message || fallback
}

function shortId(value) {
  const text = String(value || '')
  return text.length > 16 ? `${text.slice(0, 7)}…${text.slice(-7)}` : text
}

function statusLabel(status) {
  return ({ success: '运行成功', runtime_error: '运行报错', timeout: '运行超时' })[status] || '运行未结束'
}

function severityLabel(severity) {
  return ({ error: '需修复', warning: '需关注', info: '已核对' })[severity] || '提示'
}

function riskLabel(level) {
  return ({ high: '高风险', medium: '中风险', low: '低风险' })[level] || '风险'
}

function idempotencyKey() {
  const input = `${props.run?.runAttemptId || ''}|${focus.value.trim()}`
  let hash = 2166136261
  for (let index = 0; index < input.length; index += 1) {
    hash ^= input.charCodeAt(index)
    hash = Math.imul(hash, 16777619)
  }
  return `code-review-${String(props.run?.runAttemptId || '').slice(-12)}-${(hash >>> 0).toString(16)}`
}

async function loadReview() {
  const sequence = ++loadSequence
  review.value = null
  error.value = ''
  notice.value = ''
  if (!props.run?.runAttemptId || !eligible.value) {
    loading.value = false
    return
  }
  loading.value = true
  try {
    const response = await getLatestCodeReview(props.resourceId, props.run.runAttemptId)
    if (sequence !== loadSequence) return
    review.value = response.item || null
    if (review.value?.focus) focus.value = review.value.focus
  } catch (caught) {
    if (sequence === loadSequence) error.value = message(caught, '已有点评暂时无法恢复；代码运行结果不受影响。')
  } finally {
    if (sequence === loadSequence) loading.value = false
  }
}

async function requestReview() {
  if (!eligible.value || generating.value) return
  generating.value = true
  error.value = ''
  notice.value = ''
  try {
    review.value = await createCodeReview(props.resourceId, {
      run_attempt_id: props.run.runAttemptId,
      code_sha256: props.run.codeSha256,
      focus: focus.value.trim(),
      idempotency_key: idempotencyKey(),
    })
    notice.value = '点评已绑定本次真实运行。你可以先核对建议，再决定是否另存为新版本。'
  } catch (caught) {
    error.value = message(caught)
  } finally {
    generating.value = false
  }
}

async function applySuggestion() {
  if (!review.value || applying.value || applied.value) return
  applying.value = true
  error.value = ''
  notice.value = ''
  try {
    const result = await applyCodeReview(review.value.reviewId, {
      expected_lock_version: props.resourceLockVersion,
      idempotency_key: `apply-${review.value.reviewId}`,
    })
    review.value = { ...review.value, application: {
      resourceVersionId: result.resourceVersionId,
      resourceVersionNumber: result.resourceVersionNumber,
      appliedAt: result.appliedAt,
    } }
    notice.value = `建议已另存为 v${result.resourceVersionNumber}。下一步点击顶部“运行代码”，再从运行历史比较前后结果。`
    emit('applied', result)
  } catch (caught) {
    error.value = message(caught, '建议未能应用；原代码和运行记录均未改变。')
  } finally {
    applying.value = false
  }
}

watch(() => props.run?.runAttemptId, loadReview, { immediate: true })
</script>

<template>
  <section class="review-panel" data-testid="code-review-panel" aria-live="polite">
    <header class="review-header">
      <span class="review-icon"><Bot :size="19" /></span>
      <div>
        <strong>运行证据点评</strong>
        <p>{{ reviewModeLabel }}</p>
      </div>
    </header>

    <div class="evidence-strip">
      <span>{{ evidenceLabel }}</span>
      <code v-if="run?.codeSha256">code {{ shortId(run.codeSha256) }}</code>
    </div>

    <div v-if="error" class="review-message error" role="alert">
      <AlertCircle :size="16" /><span>{{ error }}</span><button type="button" @click="error = ''">关闭</button>
    </div>
    <div v-else-if="notice" class="review-message notice" role="status">
      <CheckCircle2 :size="16" /><span>{{ notice }}</span><button type="button" @click="notice = ''">关闭</button>
    </div>

    <div v-if="loading" class="review-state">
      <LoaderCircle :size="22" class="spin" /><strong>正在恢复已有点评</strong><p>运行结果仍可在其他标签中查看。</p>
    </div>

    <div v-else-if="error" class="review-state review-state--error">
      <AlertCircle :size="23" /><strong>暂时无法完成点评</strong><p>{{ error }}</p>
      <button type="button" class="review-action" :disabled="generating" @click="requestReview">
        <LoaderCircle v-if="generating" :size="16" class="spin" /><Sparkles v-else :size="16" />
        {{ generating ? '正在重新请求模型' : '重新请求点评' }}
      </button>
    </div>

    <div v-else-if="!eligible" class="review-state">
      <ShieldAlert :size="23" /><strong>当前不能生成点评</strong><p>{{ disabledReason }}</p>
    </div>

    <template v-else>
      <label class="focus-field">
        <span>点评重点 <small>可选</small></span>
        <textarea v-model="focus" maxlength="1000" rows="3" placeholder="例如：重点检查边界条件、时间复杂度或代码可读性" />
      </label>
      <button type="button" class="review-action" :disabled="generating || applying" @click="requestReview">
        <LoaderCircle v-if="generating" :size="16" class="spin" /><Sparkles v-else :size="16" />
        {{ generating ? '正在分析运行证据' : review ? '按当前重点重新点评' : '基于本次运行生成点评' }}
      </button>

      <div v-if="!review && !generating" class="review-state compact">
        <FileDiff :size="22" /><strong>真实证据已就绪</strong><p>点评将引用当前 runAttemptId、代码哈希、输入、输出、错误和检查结果。</p>
      </div>

      <article v-else-if="review" class="review-result">
        <section class="review-section">
          <div class="section-heading"><h3>问题定位</h3><span>{{ review.findings?.length || 0 }} 项</span></div>
          <ul class="finding-list">
            <li v-for="finding in review.findings" :key="finding.id">
              <span class="finding-mark" :class="finding.severity"><TriangleAlert v-if="finding.severity !== 'info'" :size="15" /><CheckCircle2 v-else :size="15" /></span>
              <div>
                <span class="row-meta">{{ severityLabel(finding.severity) }} · {{ finding.location }}</span>
                <strong>{{ finding.title }}</strong>
                <p>{{ finding.evidence }}</p>
                <small>{{ finding.recommendation }}</small>
              </div>
            </li>
          </ul>
        </section>

        <section class="review-section">
          <div class="section-heading"><h3>点评重点</h3></div>
          <p class="focus-result">
            <strong>{{ review.focusStrategy?.label || '通用审阅' }}</strong>
            <span>{{ review.focus || '未指定额外重点，已按运行错误、必需检查和代码结构完成通用审阅。' }}</span>
          </p>
        </section>

        <section class="review-section">
          <div class="section-heading"><h3>潜在风险</h3><span>{{ review.risks?.length || 0 }} 项</span></div>
          <ul class="risk-list">
            <li v-for="risk in review.risks" :key="risk.id">
              <span>{{ riskLabel(risk.level) }}</span><strong>{{ risk.title }}</strong><p>{{ risk.detail }}</p>
            </li>
          </ul>
        </section>

        <section class="review-section">
          <div class="section-heading"><h3>改进代码</h3><span>建议草稿</span></div>
          <pre class="improved-code">{{ review.improvedCode }}</pre>
        </section>

        <section class="review-section">
          <div class="section-heading"><h3>应用建议</h3></div>
          <ol class="advice-list">
            <li v-for="item in review.applicationAdvice" :key="item">{{ item }}</li>
          </ol>
          <div v-if="applied" class="applied-state">
            <CheckCircle2 :size="18" /><div><strong>已另存为 v{{ applied.resourceVersionNumber }}</strong><p>原版本和原运行记录仍保留。点击顶部“运行代码”后，可在左侧历史比较前后结果。</p></div>
          </div>
          <button v-else type="button" class="apply-action" :disabled="applying || generating" @click="applySuggestion">
            <LoaderCircle v-if="applying" :size="16" class="spin" /><FileDiff v-else :size="16" />
            {{ applying ? '正在创建新版本' : '应用建议并另存新版本' }}
          </button>
        </section>

        <details class="audit-details">
          <summary><span>可审计协作摘要</span><ChevronDown :size="16" /></summary>
          <p>仅展示职责、输入引用、候选结论、分歧、校验、修订和最终决策摘要。</p>
          <ol>
            <li v-for="agent in review.agentAudit" :key="agent.runId">
              <strong>{{ agent.role }}</strong>
              <span>{{ agent.candidateSummary }}</span>
              <small>校验：{{ agent.validation }}</small>
              <small>修订：{{ agent.revision }}</small>
              <small>决策：{{ agent.decisionSummary }}</small>
            </li>
          </ol>
        </details>

        <footer class="review-evidence">
          <span>证据引用</span>
          <code>run {{ shortId(review.evidenceRefs.runAttemptId) }}</code>
          <code>stderr {{ shortId(review.evidenceRefs.stderrSha256) }}</code>
        </footer>
      </article>
    </template>
  </section>
</template>

<style scoped>
.review-panel { min-width: 0; color: #06141b; font-family: 'Source Han Sans SC', 'Noto Sans CJK SC', 'Microsoft YaHei', sans-serif; }
.review-header { display: flex; align-items: center; gap: 9px; padding: 14px; border-bottom: 1px solid #e4e8e8; }
.review-icon { display: grid; width: 34px; height: 34px; flex: 0 0 34px; place-items: center; border-radius: 8px; background: #eef2f2; color: #11212d; }
.review-header div { min-width: 0; }.review-header strong { display: block; font-size: 15px; line-height: 1.4; }.review-header p { margin: 2px 0 0; color: #60727c; font-size: 14px; line-height: 1.4; }
.evidence-strip { display: flex; min-width: 0; align-items: center; justify-content: space-between; gap: 8px; padding: 8px 14px; border-bottom: 1px solid #e4e8e8; background: #f7f9f9; color: #4a5c6a; font-size: 14px; }
.evidence-strip span { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }.evidence-strip code { flex: 0 0 auto; color: #253745; font: 14px/1.4 'Cascadia Code', Consolas, monospace; }
.review-message { display: grid; grid-template-columns: 18px minmax(0, 1fr) auto; align-items: start; gap: 7px; margin: 10px 12px 0; padding: 9px; border: 1px solid #ccd0cf; border-radius: 8px; font-size: 14px; line-height: 1.5; }
.review-message.error { border-color: #d8aaa5; background: #fff5f3; color: #873d35; }.review-message.notice { background: #f6f8f8; color: #253745; }.review-message button { border: 0; padding: 0; background: transparent; color: inherit; font-size: 14px; text-decoration: underline; text-underline-offset: 3px; cursor: pointer; }
.review-state { display: grid; min-height: 210px; place-content: center; justify-items: center; gap: 7px; padding: 22px; color: #60727c; text-align: center; }.review-state.compact { min-height: 150px; border-top: 1px solid #e4e8e8; }.review-state strong { color: #06141b; font-size: 15px; }.review-state p { max-width: 31ch; margin: 0; font-size: 14px; line-height: 1.6; }
.focus-field { display: grid; gap: 7px; padding: 13px 14px; }.focus-field > span { color: #253745; font-size: 14px; font-weight: 650; }.focus-field small { color: #60727c; font-size: 14px; font-weight: 400; }.focus-field textarea { min-width: 0; resize: vertical; border: 1px solid #ccd0cf; border-radius: 8px; padding: 9px 10px; background: #fff; color: #06141b; font-family: inherit; font-size: 14px; line-height: 1.55; }
.review-action, .apply-action { display: inline-flex; min-height: 38px; align-items: center; justify-content: center; gap: 7px; border: 1px solid #11212d; border-radius: 8px; padding: 0 11px; background: #11212d; color: #fff; font-size: 14px; font-weight: 650; cursor: pointer; }
.review-action { width: calc(100% - 28px); margin: 0 14px 13px; }.apply-action { width: 100%; margin-top: 12px; }.review-action:disabled, .apply-action:disabled { cursor: default; opacity: .48; }
button:focus-visible, textarea:focus-visible, summary:focus-visible { outline: 2px solid #11212d; outline-offset: 2px; }
.review-result { border-top: 1px solid #ccd0cf; }.review-section { padding: 14px; border-bottom: 1px solid #e4e8e8; }.section-heading { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-bottom: 9px; }.section-heading h3 { margin: 0; font-size: 15px; line-height: 1.4; }.section-heading > span { color: #60727c; font-size: 14px; }
.finding-list, .risk-list, .advice-list { margin: 0; padding: 0; list-style: none; }.finding-list li { display: grid; grid-template-columns: 24px minmax(0, 1fr); gap: 8px; padding: 10px 0; border-top: 1px solid #eef1f1; }.finding-list li:first-child { padding-top: 0; border-top: 0; }.finding-mark { display: grid; width: 24px; height: 24px; place-items: center; border-radius: 7px; background: #eef2f2; color: #253745; }.finding-mark.error, .finding-mark.warning { background: #fff2f0; color: #873d35; }.finding-list li > div { display: grid; min-width: 0; gap: 4px; }.finding-list strong { font-size: 14px; line-height: 1.45; }.finding-list p, .finding-list small { margin: 0; overflow-wrap: anywhere; color: #4a5c6a; font-size: 14px; line-height: 1.55; }.finding-list small { color: #60727c; }.row-meta { color: #60727c; font-size: 14px; line-height: 1.4; }
.focus-result { margin: 0; overflow-wrap: anywhere; color: #4a5c6a; font-size: 14px; line-height: 1.65; }.risk-list { display: grid; gap: 10px; }.risk-list li { display: grid; grid-template-columns: auto minmax(0, 1fr); gap: 4px 7px; }.risk-list li > span { grid-row: 1 / 3; align-self: start; border: 1px solid #ccd0cf; border-radius: 7px; padding: 3px 6px; color: #4a5c6a; font-size: 14px; white-space: nowrap; }.risk-list strong { font-size: 14px; line-height: 1.45; }.risk-list p { grid-column: 2; margin: 0; overflow-wrap: anywhere; color: #60727c; font-size: 14px; line-height: 1.5; }
.improved-code { max-height: 270px; margin: 0; overflow: auto; padding: 11px; background: #10181d; color: #eef3f3; font: 14px/1.6 'Cascadia Code', Consolas, monospace; white-space: pre-wrap; overflow-wrap: anywhere; }.advice-list { display: grid; gap: 7px; counter-reset: advice; }.advice-list li { display: grid; grid-template-columns: 24px minmax(0, 1fr); gap: 7px; color: #4a5c6a; font-size: 14px; line-height: 1.55; counter-increment: advice; }.advice-list li::before { content: counter(advice); display: grid; width: 22px; height: 22px; place-items: center; border-radius: 6px; background: #eef2f2; color: #253745; font-size: 14px; font-variant-numeric: tabular-nums; }
.applied-state { display: grid; grid-template-columns: 22px minmax(0, 1fr); gap: 8px; margin-top: 12px; padding: 10px; border: 1px solid #ccd0cf; border-radius: 8px; background: #f7f9f9; color: #253745; }.applied-state strong { font-size: 14px; }.applied-state p { margin: 3px 0 0; color: #60727c; font-size: 14px; line-height: 1.5; }
.audit-details { border-bottom: 1px solid #e4e8e8; }.audit-details summary { display: flex; min-height: 44px; align-items: center; justify-content: space-between; gap: 8px; padding: 0 14px; color: #253745; font-size: 14px; font-weight: 650; cursor: pointer; list-style: none; }.audit-details summary::-webkit-details-marker { display: none; }.audit-details[open] summary svg { transform: rotate(180deg); }.audit-details > p { margin: 0; padding: 0 14px 10px; color: #60727c; font-size: 14px; line-height: 1.5; }.audit-details ol { display: grid; gap: 0; margin: 0; padding: 0 14px 14px; list-style: none; }.audit-details li { display: grid; gap: 4px; padding: 10px 0; border-top: 1px solid #e4e8e8; }.audit-details strong, .audit-details span, .audit-details small { overflow-wrap: anywhere; font-size: 14px; line-height: 1.5; }.audit-details span { color: #4a5c6a; }.audit-details small { color: #60727c; }
.review-evidence { display: flex; flex-wrap: wrap; gap: 6px; padding: 11px 14px; background: #f7f9f9; color: #60727c; font-size: 14px; }.review-evidence span { width: 100%; color: #253745; font-weight: 650; }.review-evidence code { min-width: 0; max-width: 100%; overflow: hidden; border: 1px solid #e0e5e5; border-radius: 6px; padding: 3px 6px; background: #fff; color: #4a5c6a; font: 14px/1.4 'Cascadia Code', Consolas, monospace; text-overflow: ellipsis; white-space: nowrap; }
.spin { animation: spin .8s linear infinite; }@keyframes spin { to { transform: rotate(360deg); } }
@media (prefers-reduced-motion: reduce) { .spin { animation-duration: 1.6s; } }
</style>
