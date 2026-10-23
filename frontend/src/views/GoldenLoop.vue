<script setup>
import { computed, onMounted, ref } from 'vue'
import {
  AlertCircle, BookOpen, Check, CheckCircle2, ClipboardCheck, FlaskConical,
  LoaderCircle, Play, RefreshCw, Send, ShieldCheck,
} from '@lucide/vue'
import {
  checkM2Quality, createM2Task, generateM2Artifact, getLatestM2Task,
  getM2Baseline, getM2Bundle, normalizeApiError, retryM2Step,
  startM2Task, submitM2Feedback,
} from '../api'

const baseline = ref(null)
const task = ref(null)
const bundle = ref(null)
const activeResource = ref('lesson')
const loading = ref(false)
const action = ref('')
const error = ref('')
const feedback = ref({ completed: true, accuracy: 67, help_requests: 1, self_reported_difficulty: 3 })

const capabilities = ['lesson.generate_verified', 'lab_guide.generate_verified', 'tiered_quiz.generate_verified']
const resourceTabs = [
  { type: 'lesson', label: '讲义', icon: BookOpen },
  { type: 'lab_guide', label: '实训任务书', icon: FlaskConical },
  { type: 'tiered_quiz', label: '分阶测试', icon: ClipboardCheck },
]
const stepLabels = ['讲义', '实训任务书', '分阶测试', '质量检查']
const context = computed(() => baseline.value?.generation_context || null)
const target = computed(() => baseline.value?.target_knowledge_point_title || '未装配')
const resourceMap = computed(() => Object.fromEntries((bundle.value?.resources || []).map(item => [item.artifact_type, item])))
const selectedResource = computed(() => resourceMap.value[activeResource.value] || null)
const selectedContent = computed(() => {
  const raw = selectedResource.value?.versions?.at(-1)?.content
  if (!raw) return null
  try { return JSON.parse(raw) } catch { return null }
})
const quizVersionId = computed(() => resourceMap.value.tiered_quiz?.versions?.at(-1)?.id || '')
const qualitySummary = computed(() => {
  const rows = bundle.value?.quality_checks || []
  return ['schema', 'source_binding', 'cross_artifact_binding'].map(type => {
    const matches = rows.filter(item => item.check_type === type)
    return { type, total: matches.length, passed: matches.filter(item => item.status === 'passed').length }
  })
})
const canGenerate = computed(() => task.value && !['completed', 'failed', 'cancelled'].includes(task.value.status))
const canSubmitFeedback = computed(() => task.value?.latest_steps?.every(step => step.status === 'completed') && quizVersionId.value && task.value.status !== 'completed')
const decision = computed(() => bundle.value?.decisions?.at(-1) || null)

function errorMessage(e) {
  const normalized = normalizeApiError(e)
  return normalized.response?.data?.detail?.message || normalized.detail || '请求失败'
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    baseline.value = await getM2Baseline()
    try {
      task.value = await getLatestM2Task()
      bundle.value = await getM2Bundle(task.value.task_id)
    } catch (e) {
      const normalized = normalizeApiError(e)
      if (normalized.status !== 404) throw e
      task.value = null
      bundle.value = null
    }
  } catch (e) {
    error.value = errorMessage(e)
  } finally {
    loading.value = false
  }
}

async function createTask() {
  if (!context.value) return
  action.value = 'create'
  error.value = ''
  try {
    task.value = await createM2Task({
      context: context.value,
      idempotency_key: `m2-ui-${baseline.value.baseline_id}`,
      model: 'configured-structured-backend',
    })
    if (task.value.status === 'queued') task.value = await startM2Task(task.value.task_id)
    bundle.value = await getM2Bundle(task.value.task_id)
  } catch (e) {
    error.value = errorMessage(e)
  } finally {
    action.value = ''
  }
}

async function continueGeneration() {
  if (!task.value || !context.value) return
  action.value = 'generate'
  error.value = ''
  try {
    if (task.value.status === 'queued') task.value = await startM2Task(task.value.task_id)
    for (let index = 0; index < 3; index += 1) {
      let step = task.value.latest_steps[index]
      if (step.status === 'failed') {
        await retryM2Step(task.value.task_id, index + 1)
      }
      if (step.status !== 'completed') {
        await generateM2Artifact(task.value.task_id, capabilities[index], context.value)
        task.value = await getLatestM2Task()
      }
    }
    let qualityStep = task.value.latest_steps[3]
    if (qualityStep.status === 'failed') await retryM2Step(task.value.task_id, 4)
    if (qualityStep.status !== 'completed') await checkM2Quality(task.value.task_id, context.value)
    task.value = await getLatestM2Task()
    bundle.value = await getM2Bundle(task.value.task_id)
  } catch (e) {
    error.value = errorMessage(e)
    try { task.value = await getLatestM2Task() } catch {}
  } finally {
    action.value = ''
  }
}

async function sendFeedback() {
  if (!canSubmitFeedback.value) return
  action.value = 'feedback'
  error.value = ''
  try {
    await submitM2Feedback(task.value.task_id, context.value, {
      idempotency_key: `m2-ui-feedback-${task.value.task_id}`,
      artifact_version_id: quizVersionId.value,
      activity_type: 'quiz_attempt',
      completed: feedback.value.completed,
      accuracy: Number(feedback.value.accuracy) / 100,
      help_requests: Number(feedback.value.help_requests),
      self_reported_difficulty: Number(feedback.value.self_reported_difficulty),
      observed_seconds: 600,
      occurred_at: new Date().toISOString(),
      note: '',
    })
    task.value = await getLatestM2Task()
    bundle.value = await getM2Bundle(task.value.task_id)
  } catch (e) {
    error.value = errorMessage(e)
  } finally {
    action.value = ''
  }
}

onMounted(load)
</script>

<template>
  <section class="golden-page">
    <header class="page-head">
      <div>
        <p class="eyebrow">M2 · VERIFIED CONTEXT</p>
        <h2>{{ target }}</h2>
        <div class="context-line">
          <span>{{ baseline?.target_knowledge_point_code || 'KP' }}</span>
          <span>{{ baseline?.estimated_effort_range_minutes?.join('–') || '—' }} 分钟</span>
          <span><ShieldCheck :size="13" /> verified</span>
        </div>
      </div>
      <div class="head-actions">
        <button class="icon-button" title="刷新" aria-label="刷新" :disabled="loading" @click="load"><RefreshCw :size="16" /></button>
        <button v-if="!task" class="primary-command" :disabled="Boolean(action)" @click="createTask"><Play :size="15" />创建任务</button>
        <button v-else-if="canGenerate" class="primary-command" :disabled="Boolean(action)" @click="continueGeneration">
          <LoaderCircle v-if="action === 'generate'" class="spin" :size="15" />
          <Play v-else :size="15" />{{ action === 'generate' ? '处理中' : '生成并检查' }}
        </button>
        <span v-else class="complete-badge"><CheckCircle2 :size="15" />闭环完成</span>
      </div>
    </header>

    <p v-if="error" class="error-banner"><AlertCircle :size="16" />{{ error }}</p>

    <div class="step-rail" aria-label="任务进度">
      <div v-for="(label, index) in stepLabels" :key="label" class="step-item" :data-status="task?.latest_steps?.[index]?.status || 'pending'">
        <span><Check v-if="task?.latest_steps?.[index]?.status === 'completed'" :size="13" />{{ index + 1 }}</span>
        <div><strong>{{ label }}</strong><small>{{ task?.latest_steps?.[index]?.status || 'pending' }} · attempt {{ task?.latest_steps?.[index]?.attempt || 1 }}</small></div>
      </div>
    </div>

    <div v-if="!task && !loading" class="empty-state">尚未创建黄金任务</div>
    <template v-else-if="task">
      <div class="workspace-grid">
        <section class="resource-workspace">
          <div class="segmented" role="tablist" aria-label="资源类型">
            <button v-for="tab in resourceTabs" :key="tab.type" :class="{ active: activeResource === tab.type }" @click="activeResource = tab.type">
              <component :is="tab.icon" :size="14" />{{ tab.label }}
              <span :class="{ ready: resourceMap[tab.type] }" />
            </button>
          </div>
          <div v-if="!selectedContent" class="empty-state resource-empty">资源尚未生成</div>
          <article v-else class="resource-body">
            <div class="resource-title"><div><p class="eyebrow">{{ selectedContent.schema_version }}</p><h3>{{ selectedContent.title }}</h3></div><span>v{{ selectedResource.versions.at(-1).version_number }}</span></div>
            <template v-if="activeResource === 'lesson'">
              <p class="objective">{{ selectedContent.objective }}</p>
              <section v-for="section in selectedContent.sections" :key="section.heading" class="content-section"><h4>{{ section.heading }}</h4><p>{{ section.body_markdown }}</p></section>
              <div class="summary-band"><strong>总结</strong><span>{{ selectedContent.summary }}</span></div>
            </template>
            <template v-else-if="activeResource === 'lab_guide'">
              <p class="objective">{{ selectedContent.objective }}</p>
              <div class="environment"><strong>环境</strong><span v-for="item in selectedContent.environment" :key="item">{{ item }}</span></div>
              <ol class="lab-steps"><li v-for="step in selectedContent.steps" :key="step.step_number"><span>{{ step.step_number }}</span><div><h4>{{ step.title }}</h4><p>{{ step.instruction }}</p><code v-if="step.command_or_action">{{ step.command_or_action }}</code><small>预期：{{ step.expected_result }}</small></div></li></ol>
            </template>
            <template v-else>
              <p class="objective">{{ selectedContent.instructions }}</p>
              <section v-for="tier in selectedContent.tiers" :key="tier.level" class="quiz-tier"><h4>{{ tier.level }}</h4><div v-for="question in tier.questions" :key="question.id" class="question"><span>{{ question.id }}</span><p>{{ question.prompt }}</p><small>{{ question.bloom_level }} · {{ question.scoring_rule }}</small></div></section>
            </template>
          </article>
        </section>

        <aside class="evidence-panel">
          <div class="panel-head"><div><p class="eyebrow">QUALITY GATE</p><h3>质量证据</h3></div><span>{{ bundle?.quality_checks?.filter(item => item.status === 'passed').length || 0 }}/9</span></div>
          <div class="quality-list">
            <div v-for="item in qualitySummary" :key="item.type"><span :class="{ passed: item.total && item.passed === item.total }"><CheckCircle2 :size="14" /></span><div><strong>{{ item.type }}</strong><small>{{ item.passed }} / {{ item.total }} passed</small></div></div>
          </div>
          <dl class="lineage-list">
            <div><dt>Trace</dt><dd>{{ task.trace_id }}</dd></div>
            <div><dt>Profile</dt><dd>{{ context?.profile_snapshot_id }}</dd></div>
            <div><dt>Domain</dt><dd>{{ context?.domain_version_id }}</dd></div>
            <div><dt>Sources</dt><dd>{{ context?.source_ref_ids?.length || 0 }}</dd></div>
          </dl>
        </aside>
      </div>

      <section class="feedback-band">
        <div class="feedback-title"><div><p class="eyebrow">LEARNING SIGNAL</p><h3>学习反馈</h3></div><span v-if="task.status === 'completed'" class="complete-badge"><CheckCircle2 :size="14" />已记录</span></div>
        <div v-if="task.status !== 'completed'" class="feedback-form">
          <label class="check-field"><input v-model="feedback.completed" type="checkbox" />已完成本轮学习</label>
          <label><span>正确率 <strong>{{ feedback.accuracy }}%</strong></span><input v-model="feedback.accuracy" type="range" min="0" max="100" step="1" /></label>
          <label><span>求助次数</span><input v-model.number="feedback.help_requests" type="number" min="0" max="100" /></label>
          <label><span>主观难度</span><select v-model.number="feedback.self_reported_difficulty"><option v-for="value in 5" :key="value" :value="value">{{ value }}</option></select></label>
          <button class="primary-command" :disabled="!canSubmitFeedback || Boolean(action)" @click="sendFeedback"><Send :size="15" />{{ action === 'feedback' ? '提交中' : '提交反馈' }}</button>
        </div>
        <div v-else class="decision-row">
          <div><strong>{{ decision?.execution_impact?.recommended_candidate || 'collect_more_evidence' }}</strong><span>候选决策 · {{ decision?.status || 'proposed' }}</span></div>
          <div><strong>掌握状态未变更</strong><span>等待后续证据</span></div>
          <div><strong>{{ Math.round((decision?.confidence || 0) * 100) }}%</strong><span>决策置信度</span></div>
        </div>
      </section>
    </template>
  </section>
</template>

<style scoped>
.golden-page { max-width: 1280px; margin: 0 auto; color: #263129; }
.page-head, .head-actions, .context-line, .resource-title, .panel-head, .feedback-title { display: flex; align-items: center; }
.page-head { justify-content: space-between; gap: 24px; margin-bottom: 20px; }
.eyebrow { margin: 0 0 5px; color: #818d84; font-size: 10px; font-weight: 750; letter-spacing: 0; text-transform: uppercase; }
h2, h3, h4, p { margin-top: 0; } h2 { margin-bottom: 7px; font-size: 25px; letter-spacing: 0; } h3 { margin-bottom: 0; font-size: 16px; } h4 { margin-bottom: 6px; font-size: 13px; }
.context-line { gap: 8px; color: #6e7a71; font-size: 11px; }
.context-line span { display: inline-flex; align-items: center; gap: 4px; padding-right: 8px; border-right: 1px solid #dbe1dc; }.context-line span:last-child { border: 0; }
.head-actions { gap: 8px; }.icon-button, .primary-command { display: inline-flex; height: 36px; align-items: center; justify-content: center; gap: 7px; border-radius: 7px; cursor: pointer; }
.icon-button { width: 36px; color: #5f6d63; border: 1px solid #d9e0da; background: #fff; }.primary-command { padding: 0 14px; color: #fff; border: 1px solid #263a2e; background: #2e4737; font-size: 12px; font-weight: 650; }.primary-command:disabled, .icon-button:disabled { opacity: .5; cursor: default; }
.complete-badge { display: inline-flex; align-items: center; gap: 6px; padding: 7px 10px; color: #356447; border: 1px solid #bcd7c5; border-radius: 7px; background: #edf7f0; font-size: 11px; }
.error-banner { display: flex; align-items: center; gap: 8px; margin: 0 0 14px; padding: 10px 12px; color: #8d443c; border: 1px solid #e8c7c2; border-radius: 7px; background: #fff4f2; font-size: 12px; }
.step-rail { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); margin-bottom: 16px; border: 1px solid #dfe5e0; border-radius: 8px; background: #fff; }
.step-item { display: flex; min-width: 0; align-items: center; gap: 9px; padding: 12px; border-right: 1px solid #e6ebe7; }.step-item:last-child { border: 0; }.step-item > span { display: grid; width: 24px; height: 24px; flex: 0 0 24px; place-items: center; color: #78857c; border: 1px solid #d7dfd9; border-radius: 50%; font-size: 10px; }.step-item strong, .step-item small { display: block; }.step-item strong { font-size: 11px; }.step-item small { margin-top: 3px; overflow: hidden; color: #909a92; font-size: 9px; text-overflow: ellipsis; white-space: nowrap; }.step-item[data-status='completed'] > span { color: #fff; border-color: #487158; background: #487158; }.step-item[data-status='failed'] > span { color: #963f38; border-color: #deb8b3; background: #fff1ef; }
.workspace-grid { display: grid; grid-template-columns: minmax(0, 1fr) 280px; gap: 14px; }.resource-workspace, .evidence-panel, .feedback-band { border: 1px solid #dfe5e0; border-radius: 8px; background: rgba(255,255,255,.88); }.resource-workspace { min-height: 490px; overflow: hidden; }.segmented { display: flex; gap: 3px; padding: 8px; border-bottom: 1px solid #e4e9e5; background: #f5f7f5; }.segmented button { position: relative; display: flex; height: 32px; align-items: center; gap: 6px; padding: 0 11px; color: #6d7a71; border: 0; border-radius: 6px; background: transparent; font-size: 11px; cursor: pointer; }.segmented button.active { color: #29342c; background: #fff; box-shadow: 0 1px 3px rgba(32,48,38,.1); }.segmented button > span { width: 5px; height: 5px; border-radius: 50%; background: #c5ccc7; }.segmented button > span.ready { background: #4f7f60; }
.empty-state { display: grid; min-height: 180px; place-items: center; color: #929c94; font-size: 12px; }.resource-empty { min-height: 430px; }.resource-body { padding: 20px; }.resource-title, .panel-head, .feedback-title { justify-content: space-between; gap: 12px; padding-bottom: 13px; border-bottom: 1px solid #e4e9e5; }.resource-title > span, .panel-head > span { color: #52645a; font-size: 11px; }.objective { margin: 15px 0; color: #526059; font-size: 12px; line-height: 1.7; }.content-section { padding: 13px 0; border-top: 1px solid #edf0ed; }.content-section p { margin-bottom: 0; color: #4e5a52; font-size: 12px; line-height: 1.75; white-space: pre-wrap; }.summary-band { display: grid; grid-template-columns: 70px 1fr; gap: 10px; margin-top: 14px; padding: 12px; border-left: 3px solid #50725c; background: #f2f7f3; font-size: 11px; }.environment { display: flex; align-items: center; gap: 7px; margin: 13px 0; font-size: 11px; }.environment span { padding: 4px 6px; border-radius: 4px; background: #eef2ee; }.lab-steps { margin: 0; padding: 0; list-style: none; }.lab-steps li { display: grid; grid-template-columns: 26px 1fr; gap: 9px; padding: 13px 0; border-top: 1px solid #edf0ed; }.lab-steps li > span { display: grid; width: 24px; height: 24px; place-items: center; color: #fff; border-radius: 50%; background: #506359; font-size: 10px; }.lab-steps p { margin-bottom: 7px; color: #566259; font-size: 11px; }.lab-steps code { display: block; padding: 8px; overflow-wrap: anywhere; border-radius: 5px; background: #222a25; color: #e8eee9; font-size: 10px; }.lab-steps small { display: block; margin-top: 7px; color: #768279; font-size: 10px; }.quiz-tier { margin-top: 16px; }.quiz-tier > h4 { color: #6d5743; text-transform: capitalize; }.question { padding: 11px; border: 1px solid #e5e7e2; border-radius: 7px; background: #fbfcfa; }.question > span { color: #8e968f; font-size: 9px; }.question p { margin: 5px 0; font-size: 12px; }.question small { color: #758078; font-size: 10px; }
.evidence-panel { padding: 16px; }.quality-list { margin: 12px 0; }.quality-list > div { display: flex; align-items: center; gap: 9px; padding: 10px 0; border-bottom: 1px solid #edf0ed; }.quality-list span { color: #a0a8a2; }.quality-list span.passed { color: #47775a; }.quality-list strong, .quality-list small { display: block; }.quality-list strong { font-size: 10px; }.quality-list small { margin-top: 2px; color: #8a948c; font-size: 9px; }.lineage-list { margin: 15px 0 0; }.lineage-list div { padding: 8px 0; border-bottom: 1px solid #edf0ed; }.lineage-list dt { color: #8a958d; font-size: 9px; }.lineage-list dd { margin: 3px 0 0; overflow: hidden; color: #4f5e54; font: 9px ui-monospace, Consolas, monospace; text-overflow: ellipsis; white-space: nowrap; }
.feedback-band { margin-top: 14px; padding: 16px; }.feedback-form { display: grid; grid-template-columns: 1.1fr 1.5fr .8fr .8fr auto; gap: 12px; align-items: end; padding-top: 14px; }.feedback-form label { min-width: 0; color: #69766d; font-size: 10px; }.feedback-form label > span { display: flex; justify-content: space-between; margin-bottom: 6px; }.feedback-form input[type='range'] { width: 100%; accent-color: #456d54; }.feedback-form input[type='number'], .feedback-form select { width: 100%; height: 34px; padding: 0 8px; border: 1px solid #d9e0da; border-radius: 6px; background: #fff; color: #37443b; }.check-field { display: flex; height: 34px; align-items: center; gap: 7px; }.check-field input { accent-color: #456d54; }.decision-row { display: grid; grid-template-columns: 1.5fr 1fr .7fr; gap: 10px; padding-top: 14px; }.decision-row > div { padding: 10px; border-left: 2px solid #697d70; background: #f5f7f5; }.decision-row strong, .decision-row span { display: block; }.decision-row strong { font-size: 11px; }.decision-row span { margin-top: 4px; color: #808b83; font-size: 9px; }.spin { animation: spin 1s linear infinite; }@keyframes spin { to { transform: rotate(360deg); } }
@media (max-width: 980px) { .workspace-grid { grid-template-columns: 1fr; }.evidence-panel { order: -1; }.feedback-form { grid-template-columns: repeat(2, minmax(0,1fr)); }.feedback-form .primary-command { width: 100%; } }
@media (max-width: 680px) { .page-head { align-items: flex-start; flex-direction: column; }.head-actions { width: 100%; }.primary-command { flex: 1; }.step-rail { grid-template-columns: repeat(2, minmax(0,1fr)); }.step-item:nth-child(2) { border-right: 0; }.step-item:nth-child(-n+2) { border-bottom: 1px solid #e6ebe7; }.segmented { overflow-x: auto; }.segmented button { flex: 0 0 auto; }.feedback-form, .decision-row { grid-template-columns: 1fr; }.resource-body { padding: 15px; } }
</style>
