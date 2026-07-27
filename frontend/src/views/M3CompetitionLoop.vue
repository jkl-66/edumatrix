<script setup>
import { computed, onMounted, ref } from 'vue'
import {
  AlertCircle, BarChart3, Beaker, BookOpen, Check, CheckCircle2, ChevronRight,
  FileCheck2, Gauge, LoaderCircle, Play, RefreshCw, RotateCcw, Send, ShieldCheck,
  SlidersHorizontal, Sparkles, TriangleAlert, Trophy,
} from '@lucide/vue'
import {
  applyM3InteractiveAction, buildM3Decision, buildM3MatchingReport,
  createM3InteractiveManifest, createM3InteractiveSession, createM3Task,
  diagnoseM3Task, generateM3Resources, getLatestM3Task, getM3Bundle, getM3Profiles,
  recordM3InteractiveEvidence, reviewM3Resources, startM3Task,
} from '../api'

const profiles = ref([])
const selectedProfileId = ref('')
const task = ref(null)
const bundle = ref(null)
const loading = ref(true)
const action = ref('')
const error = ref('')
const resourceTab = ref('lesson')
const evidence = ref(null)
const params = ref({ keyword_weight: 0.4, vector_weight: 0.6, top_k: 5, rerank_threshold: 0.55 })
const faultType = ref('index_version_mismatch')
const diagnosis = ref('索引版本与任务冻结版本不一致')
const recoveryAction = ref('select_matching_index_version')

const roleLabels = {
  diagnosis: '画像诊断', domain_generation: '领域生成',
  evidence_review: '证据审查', decision_orchestration: '决策编排',
}
const archetypeLabels = { beginner: '零基础转入', theory_practice_gap: '理论强实操弱', advanced: '进阶工程型' }
const resourceTabs = [
  { type: 'lesson', label: '讲义', icon: BookOpen },
  { type: 'lab_guide', label: '实操', icon: Beaker },
  { type: 'tiered_quiz', label: '测验', icon: FileCheck2 },
]
const faultOptions = [
  { value: 'low_confidence', label: '低置信度', recovery: 'increase_evidence_and_adjust_threshold' },
  { value: 'owner_filter_empty', label: 'Owner 过滤为空', recovery: 'verify_scope_and_refuse_if_empty' },
  { value: 'index_version_mismatch', label: '索引版本错配', recovery: 'select_matching_index_version' },
  { value: 'reranker_unavailable', label: '重排器不可用', recovery: 'use_declared_no_rerank_fallback' },
]

function readContent(artifact) {
  const value = artifact?.versions?.at(-1)?.content
  if (!value) return null
  if (typeof value === 'object') return value
  try { return JSON.parse(value) } catch { return value }
}

const selectedProfile = computed(() => profiles.value.find(item => item.profile_id === selectedProfileId.value))
const artifacts = computed(() => bundle.value?.artifacts || {})
const resource = computed(() => artifacts.value[resourceTab.value]?.[0] || null)
const resourceContent = computed(() => readContent(resource.value))
const debate = computed(() => readContent(artifacts.value.m3_debate_report?.[0]))
const matching = computed(() => readContent(artifacts.value.m3_matching_report?.[0]))
const decision = computed(() => readContent(artifacts.value.m3_decision_comparison?.[0]))
const manifest = computed(() => readContent(artifacts.value.interactive_skill_artifact?.[0]))
const sessionArtifact = computed(() => artifacts.value.interactive_skill_session?.[0] || null)
const interactiveState = computed(() => readContent(sessionArtifact.value))
const canCreate = computed(() => selectedProfileId.value && !action.value)
const taskFinished = computed(() => task.value?.status === 'completed')
const allRolesDone = computed(() => task.value?.steps?.every(step => step.status === 'completed'))

function errorMessage(e) {
  const detail = e?.response?.data?.detail
  return detail?.message || detail?.code || e?.message || '操作失败'
}

async function refreshBundle() {
  if (!task.value?.id) return
  task.value = await getLatestM3Task()
  bundle.value = await getM3Bundle(task.value.id)
  if (task.value.profile_id) selectedProfileId.value = task.value.profile_id
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const response = await getM3Profiles()
    profiles.value = response.profiles
    selectedProfileId.value ||= profiles.value[0]?.profile_id || ''
    try {
      task.value = await getLatestM3Task()
      if (task.value.profile_id) selectedProfileId.value = task.value.profile_id
      bundle.value = await getM3Bundle(task.value.id)
    } catch (e) {
      if (e?.response?.status !== 404) throw e
    }
  } catch (e) {
    error.value = errorMessage(e)
  } finally {
    loading.value = false
  }
}

async function createTask() {
  action.value = 'create'
  error.value = ''
  evidence.value = null
  try {
    task.value = await createM3Task({
      profile_id: selectedProfileId.value,
      idempotency_key: `m3-ui-${selectedProfileId.value}-${Date.now()}`,
      model: 'configured-structured-backend',
    })
    bundle.value = await getM3Bundle(task.value.id)
  } catch (e) { error.value = errorMessage(e) } finally { action.value = '' }
}

async function runLoop() {
  if (!task.value) return
  action.value = 'loop'
  error.value = ''
  try {
    if (task.value.status === 'queued') await startM3Task(task.value.id)
    await refreshBundle()
    const calls = [diagnoseM3Task, generateM3Resources, reviewM3Resources]
    for (let index = 0; index < calls.length; index += 1) {
      if (task.value.steps?.[index]?.status !== 'completed') {
        await calls[index](task.value.id)
        await refreshBundle()
      }
    }
    if (task.value.steps?.[3]?.status !== 'completed') {
      await buildM3MatchingReport(task.value.id)
      await buildM3Decision(task.value.id)
      await refreshBundle()
    }
  } catch (e) {
    error.value = errorMessage(e)
    try { await refreshBundle() } catch {}
  } finally { action.value = '' }
}

async function ensureInteractive() {
  action.value = 'interactive'
  error.value = ''
  try {
    await createM3InteractiveManifest(task.value.id)
    await createM3InteractiveSession(task.value.id, `m3-ui-session-${task.value.id}`)
    await refreshBundle()
  } catch (e) { error.value = errorMessage(e) } finally { action.value = '' }
}

async function interactiveAction(kind, extra = {}) {
  if (!sessionArtifact.value) return
  action.value = `interactive-${kind}`
  error.value = ''
  try {
    await applyM3InteractiveAction(sessionArtifact.value.id, {
      idempotency_key: `m3-ui-${kind}-${Date.now()}`,
      action: kind,
      ...extra,
    })
    await refreshBundle()
  } catch (e) { error.value = errorMessage(e) } finally { action.value = '' }
}

function configure() { return interactiveAction('configure', { parameters: { ...params.value } }) }
function injectFault() { return interactiveAction('inject_fault', { fault_type: faultType.value }) }
function diagnoseFault() {
  return interactiveAction('diagnose', { diagnosis: diagnosis.value, recovery_action: recoveryAction.value })
}
function changeFault() {
  recoveryAction.value = faultOptions.find(item => item.value === faultType.value)?.recovery || ''
}

async function recordEvidence() {
  action.value = 'evidence'
  error.value = ''
  try {
    evidence.value = await recordM3InteractiveEvidence(sessionArtifact.value.id)
    await refreshBundle()
  } catch (e) { error.value = errorMessage(e) } finally { action.value = '' }
}

onMounted(load)
</script>

<template>
  <section class="m3-page">
    <header class="page-head">
      <div>
        <p class="eyebrow">M3 · COMPETITION LOOP</p>
        <h2>调优混合检索并保持数据隔离</h2>
        <div class="context-line"><span>JOB-05</span><span>KP-11 / 12 / 13</span><span><ShieldCheck :size="13" />事实与安全标准不变</span></div>
      </div>
      <div class="head-actions">
        <button class="icon-button" title="刷新" aria-label="刷新" :disabled="loading" @click="load"><RefreshCw :size="16" /></button>
        <button v-if="!task" class="primary" :disabled="!canCreate" @click="createTask"><Play :size="15" />创建对照任务</button>
        <button v-else-if="!taskFinished" class="primary" :disabled="Boolean(action)" @click="runLoop">
          <LoaderCircle v-if="action === 'loop'" class="spin" :size="15" /><Play v-else :size="15" />{{ action === 'loop' ? '执行中' : '继续四角色闭环' }}
        </button>
        <span v-else class="complete"><CheckCircle2 :size="15" />四角色完成</span>
      </div>
    </header>

    <p v-if="error" class="error"><AlertCircle :size="16" />{{ error }}</p>

    <section class="profile-band" aria-label="画像对照">
      <button v-for="profile in profiles" :key="profile.profile_id" :class="{ active: selectedProfileId === profile.profile_id }" :disabled="Boolean(task)" @click="selectedProfileId = profile.profile_id">
        <span class="profile-number">{{ profile.archetype === 'beginner' ? '01' : profile.archetype === 'theory_practice_gap' ? '02' : '03' }}</span>
        <div><strong>{{ archetypeLabels[profile.archetype] }}</strong><small>{{ profile.adaptation_strategy.difficulty_band }} · {{ profile.adaptation_strategy.task_openness }}</small></div>
        <Check v-if="selectedProfileId === profile.profile_id" :size="15" />
      </button>
    </section>

    <div class="profile-detail" v-if="selectedProfile">
      <div><span>目标</span><strong>{{ selectedProfile.goal }}</strong></div>
      <div><span>脚手架</span><strong>{{ selectedProfile.adaptation_strategy.scaffolding }}</strong></div>
      <div><span>步骤粒度</span><strong>{{ selectedProfile.adaptation_strategy.step_granularity }}</strong></div>
      <div><span>题目重点</span><strong>{{ selectedProfile.adaptation_strategy.quiz_emphasis }}</strong></div>
    </div>

    <section class="role-rail" aria-label="四角色进度">
      <div v-for="(step, index) in task?.steps || [0,1,2,3]" :key="step.id || index" :data-status="step.status || 'pending'">
        <span><Check v-if="step.status === 'completed'" :size="13" /><template v-else>{{ index + 1 }}</template></span>
        <div><strong>{{ roleLabels[step.agent_role] || Object.values(roleLabels)[index] }}</strong><small>{{ step.status || 'pending' }}</small></div>
        <ChevronRight v-if="index < 3" class="arrow" :size="14" />
      </div>
    </section>

    <div v-if="!task && !loading" class="empty">选择画像后创建对照任务</div>

    <template v-if="task">
      <div class="main-grid">
        <section class="resource-panel">
          <div class="tabs" role="tablist">
            <button v-for="tab in resourceTabs" :key="tab.type" :class="{ active: resourceTab === tab.type }" @click="resourceTab = tab.type">
              <component :is="tab.icon" :size="14" />{{ tab.label }}<i :class="{ ready: artifacts[tab.type]?.length }" />
            </button>
          </div>
          <div v-if="!resourceContent" class="empty resource-empty">领域资源尚未生成</div>
          <article v-else class="resource-body">
            <div class="section-head"><div><p class="eyebrow">{{ resourceContent.schema_version }}</p><h3>{{ resourceContent.title }}</h3></div><span>{{ resourceContent.personalization?.difficulty_band }}</span></div>
            <p class="objective">{{ resourceContent.objective || resourceContent.instructions }}</p>
            <template v-if="resourceTab === 'lesson'">
              <section v-for="item in resourceContent.sections" :key="item.heading" class="content-block"><h4>{{ item.heading }}</h4><p>{{ item.body_markdown }}</p></section>
              <div class="summary"><strong>总结</strong>{{ resourceContent.summary }}</div>
            </template>
            <template v-else-if="resourceTab === 'lab_guide'">
              <ol class="steps"><li v-for="item in resourceContent.steps" :key="item.step_number"><span>{{ item.step_number }}</span><div><h4>{{ item.title }}</h4><p>{{ item.instruction }}</p><code>{{ item.command_or_action }}</code><small>{{ item.expected_result }}</small></div></li></ol>
            </template>
            <template v-else>
              <section v-for="tier in resourceContent.tiers" :key="tier.level" class="quiz-tier"><h4>{{ tier.level }}</h4><div v-for="question in tier.questions" :key="question.id"><strong>{{ question.id }}</strong><p>{{ question.prompt }}</p><small>{{ question.bloom_level }} · {{ question.scoring_rule }}</small></div></section>
            </template>
          </article>
        </section>

        <aside class="audit-panel">
          <div class="section-head"><div><p class="eyebrow">EVIDENCE REVIEW</p><h3>原子事实辩论</h3></div><Trophy :size="17" /></div>
          <div v-if="!debate" class="empty audit-empty">等待证据审查</div>
          <template v-else>
            <div class="verdict-summary"><strong>{{ debate.overall_status }}</strong><span>不评估真实语义质量</span></div>
            <div v-for="result in debate.results" :key="result.claim.claim_id" class="claim-row">
              <span :data-verdict="result.final_verdict">{{ result.final_verdict }}</span>
              <div><strong>{{ result.claim.atomic_claim }}</strong><small>{{ result.rounds.length }} 轮 · {{ result.stopping_reason }}</small></div>
            </div>
          </template>
        </aside>
      </div>

      <div class="report-grid">
        <section class="report-panel">
          <div class="section-head"><div><p class="eyebrow">MATCHING</p><h3>学情与资源匹配</h3></div><Gauge :size="17" /></div>
          <div v-if="matching" class="match-body">
            <div class="interval"><span>推荐难度</span><strong>{{ matching.recommended_interval.lower }}–{{ matching.recommended_interval.upper }}</strong><small>不确定性 {{ matching.recommended_interval.uncertainty_width }}</small></div>
            <div class="match-list"><div v-for="item in matching.resource_matches" :key="item.artifact_type"><span>{{ item.artifact_type }}</span><strong>{{ item.status }}</strong><small>{{ item.aggregate_difficulty }}</small></div></div>
            <div class="gaps"><span v-for="gap in matching.knowledge_gaps" :key="gap.knowledge_point_code">{{ gap.knowledge_point_code }} · {{ gap.state }}</span></div>
          </div>
          <div v-else class="empty report-empty">等待匹配报告</div>
        </section>
        <section class="report-panel">
          <div class="section-head"><div><p class="eyebrow">PROPOSED DECISION</p><h3>动态决策候选</h3></div><Sparkles :size="17" /></div>
          <div v-if="decision" class="decision-body">
            <div class="selected-decision"><span>{{ decision.evidence_state }}</span><strong>{{ decision.selected_decision_type }}</strong><small>置信度 {{ Math.round(decision.confidence * 100) }}% · 未确认</small></div>
            <div class="candidate-list"><span v-for="item in decision.candidates" :key="item.decision_type" :class="{ selected: item.decision_type === decision.selected_decision_type }">{{ item.decision_type }}</span></div>
            <p><ShieldCheck :size="14" />掌握状态未变更，路径执行未授权</p>
          </div>
          <div v-else class="empty report-empty">等待决策编排</div>
        </section>
      </div>

      <section v-if="taskFinished" class="interactive-band">
        <div class="interactive-head"><div><p class="eyebrow">RESTRICTED INTERACTIVE SKILL</p><h3>混合检索调优实验</h3></div><span v-if="manifest"><ShieldCheck :size="14" />{{ manifest.runtime_mode }}</span><button v-else class="primary" :disabled="Boolean(action)" @click="ensureInteractive"><SlidersHorizontal :size="15" />初始化实验</button></div>
        <template v-if="interactiveState">
          <div class="interactive-grid">
            <div class="controls">
              <label><span>关键词权重 <strong>{{ params.keyword_weight }}</strong></span><input v-model.number="params.keyword_weight" type="range" min="0" max="1" step="0.1" @input="params.vector_weight = Number((1 - params.keyword_weight).toFixed(1))" /></label>
              <label><span>向量权重 <strong>{{ params.vector_weight }}</strong></span><input :value="params.vector_weight" type="range" min="0" max="1" step="0.1" disabled /></label>
              <label><span>Top K</span><input v-model.number="params.top_k" type="number" min="1" max="10" /></label>
              <label><span>重排阈值</span><input v-model.number="params.rerank_threshold" type="number" min="0" max="1" step="0.05" /></label>
              <button class="secondary" :disabled="action || interactiveState.status === 'running'" @click="configure"><SlidersHorizontal :size="14" />应用参数</button>
            </div>
            <div class="metrics">
              <div><span>状态</span><strong>{{ interactiveState.status }}</strong></div>
              <div><span>Recall@K</span><strong>{{ interactiveState.metrics?.recall_at_k ?? '—' }}</strong></div>
              <div><span>排序分</span><strong>{{ interactiveState.metrics?.ranking_score ?? '—' }}</strong></div>
              <div><span>隔离泄露</span><strong>{{ interactiveState.metrics?.isolation_leaks ?? '—' }}</strong></div>
            </div>
          </div>

          <div class="action-strip">
            <button v-if="interactiveState.status === 'configured'" class="primary" :disabled="Boolean(action)" @click="interactiveAction('run')"><Play :size="14" />运行</button>
            <button v-if="interactiveState.status === 'running'" class="primary" :disabled="Boolean(action)" @click="interactiveAction('evaluate')"><BarChart3 :size="14" />评估</button>
            <button v-if="interactiveState.status === 'evaluated'" class="primary" :disabled="Boolean(action)" @click="interactiveAction('submit')"><Send :size="14" />提交隐藏验收</button>
            <button v-if="interactiveState.status !== 'running'" class="secondary" :disabled="Boolean(action)" @click="interactiveAction('reset')"><RotateCcw :size="14" />重置</button>
            <button v-if="['failed','diagnosed','evaluated','needs_retry'].includes(interactiveState.status)" class="secondary" :disabled="Boolean(action)" @click="interactiveAction('request_hint')">提示 {{ interactiveState.hint_count }}</button>
          </div>

          <div class="fault-panel">
            <div><TriangleAlert :size="16" /><strong>故障注入与恢复</strong></div>
            <select v-model="faultType" :disabled="interactiveState.status !== 'configured'" @change="changeFault"><option v-for="item in faultOptions" :key="item.value" :value="item.value">{{ item.label }}</option></select>
            <button v-if="interactiveState.status === 'configured'" class="secondary danger" :disabled="Boolean(action)" @click="injectFault">注入故障</button>
            <template v-if="interactiveState.status === 'failed'">
              <input v-model="diagnosis" aria-label="诊断说明" />
              <select v-model="recoveryAction"><option v-for="item in faultOptions" :key="item.recovery" :value="item.recovery">{{ item.recovery }}</option></select>
              <button class="secondary" @click="diagnoseFault">提交诊断</button>
            </template>
            <button v-if="interactiveState.status === 'diagnosed' && interactiveState.recovery_verified" class="secondary" @click="interactiveAction('rerun')">按恢复方案重跑</button>
          </div>

          <div v-if="interactiveState.hidden_acceptance" class="acceptance">
            <CheckCircle2 :size="20" /><div><strong>隐藏验收 {{ interactiveState.hidden_acceptance.passed_count }}/{{ interactiveState.hidden_acceptance.total_count }}</strong><span>{{ interactiveState.hidden_acceptance.failure_categories.join('、') || '无失败类别' }}</span></div>
            <button v-if="interactiveState.status === 'passed' && !evidence" class="primary" :disabled="Boolean(action)" @click="recordEvidence">记录技能证据</button>
            <span v-if="evidence" class="evidence-level">{{ evidence.skill_evidence_level }} · mastery none</span>
          </div>
        </template>
      </section>
    </template>
  </section>
</template>

<style scoped>
.m3-page { max-width: 1320px; margin: 0 auto; color: #253029; }
.page-head,.head-actions,.context-line,.section-head,.interactive-head,.action-strip,.acceptance { display:flex; align-items:center; }
.page-head { justify-content:space-between; gap:24px; margin-bottom:16px; }.page-head > div:first-child { min-width:0; }.page-head h2 { margin:0 0 7px; overflow-wrap:anywhere; font-size:25px; letter-spacing:0; }
.eyebrow { margin:0 0 5px; color:#7e8981; font-size:10px; font-weight:750; letter-spacing:0; text-transform:uppercase; }.context-line { gap:10px; color:#69756d; font-size:11px; }.context-line span { display:inline-flex; align-items:center; gap:4px; padding-right:10px; border-right:1px solid #d9dfda; }.context-line span:last-child { border:0; }
.head-actions { gap:8px; }.icon-button,.primary,.secondary { display:inline-flex; min-height:36px; align-items:center; justify-content:center; gap:7px; border-radius:7px; cursor:pointer; font-size:11px; font-weight:650; }.icon-button { width:36px; border:1px solid #d7ded8; background:#fff; color:#536158; }.primary { padding:0 14px; border:1px solid #2d4536; background:#304a39; color:#fff; }.secondary { padding:0 11px; border:1px solid #d2dbd4; background:#fff; color:#435249; }.primary:disabled,.secondary:disabled,.icon-button:disabled { opacity:.5; cursor:default; }.complete { display:inline-flex; align-items:center; gap:6px; padding:8px 10px; border:1px solid #b9d5c2; border-radius:7px; background:#edf7f0; color:#356047; font-size:11px; }.error { display:flex; align-items:center; gap:8px; padding:10px 12px; border:1px solid #e6c1bd; border-radius:7px; background:#fff3f1; color:#8e4039; font-size:12px; }
.profile-band { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); border:1px solid #dce3dd; border-radius:8px 8px 0 0; background:#fff; }.profile-band button { display:grid; grid-template-columns:32px 1fr 16px; gap:10px; align-items:center; min-width:0; padding:13px; text-align:left; border:0; border-right:1px solid #e3e8e4; background:transparent; color:#4b584f; cursor:pointer; }.profile-band button:last-child { border:0; }.profile-band button.active { background:#edf4ef; box-shadow:inset 0 -2px #416950; }.profile-band button:disabled { cursor:default; }.profile-number { color:#9aa39c; font:11px ui-monospace,Consolas,monospace; }.profile-band strong,.profile-band small { display:block; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }.profile-band strong { font-size:12px; }.profile-band small { margin-top:4px; color:#859087; font-size:9px; }
.profile-detail { display:grid; grid-template-columns:1.5fr repeat(3,1fr); border:1px solid #dce3dd; border-top:0; border-radius:0 0 8px 8px; background:#f8faf8; }.profile-detail div { min-width:0; padding:10px 12px; border-right:1px solid #e5e9e5; }.profile-detail div:last-child { border:0; }.profile-detail span,.profile-detail strong { display:block; }.profile-detail span { color:#929b94; font-size:9px; }.profile-detail strong { margin-top:4px; overflow:hidden; font-size:10px; text-overflow:ellipsis; white-space:nowrap; }
.role-rail { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); margin:14px 0; border:1px solid #dce3dd; border-radius:8px; background:#fff; }.role-rail > div { position:relative; display:flex; min-width:0; align-items:center; gap:9px; padding:11px; border-right:1px solid #e5e9e6; }.role-rail > div:last-child { border:0; }.role-rail > div > span { display:grid; width:24px; height:24px; flex:0 0 24px; place-items:center; border:1px solid #d4ddd6; border-radius:50%; color:#7a877e; font-size:10px; }.role-rail strong,.role-rail small { display:block; }.role-rail strong { font-size:10px; }.role-rail small { margin-top:3px; color:#929a94; font-size:9px; }.role-rail [data-status='completed'] > span { border-color:#4d755c; background:#4d755c; color:#fff; }.arrow { position:absolute; right:-8px; z-index:2; color:#aeb6b0; background:#fff; }
.empty { display:grid; min-height:170px; place-items:center; color:#929b94; font-size:11px; }.main-grid { display:grid; grid-template-columns:minmax(0,1fr) 330px; gap:14px; }.resource-panel,.audit-panel,.report-panel,.interactive-band { border:1px solid #dce3dd; border-radius:8px; background:rgba(255,255,255,.9); }.resource-panel { min-height:480px; overflow:hidden; }.tabs { display:flex; gap:3px; padding:8px; border-bottom:1px solid #e2e7e3; background:#f5f7f5; }.tabs button { display:flex; height:32px; align-items:center; gap:6px; padding:0 11px; border:0; border-radius:6px; background:transparent; color:#66736a; font-size:11px; cursor:pointer; }.tabs button.active { background:#fff; color:#26322a; box-shadow:0 1px 3px rgba(28,42,32,.1); }.tabs i { width:5px; height:5px; border-radius:50%; background:#c6cec8; }.tabs i.ready { background:#4d7b5b; }.resource-empty { min-height:430px; }.resource-body { padding:18px; }.section-head { justify-content:space-between; gap:10px; padding-bottom:12px; border-bottom:1px solid #e4e8e5; }.section-head h3 { margin:0; font-size:15px; }.section-head > span { color:#65746a; font-size:10px; }.objective { margin:14px 0; color:#56635a; font-size:12px; line-height:1.7; }.content-block { padding:12px 0; border-top:1px solid #edf0ed; }.content-block h4,.steps h4,.quiz-tier h4 { margin:0 0 6px; font-size:12px; }.content-block p { margin:0; white-space:pre-wrap; color:#4e5b52; font-size:12px; line-height:1.75; }.summary { margin-top:14px; padding:11px; border-left:3px solid #4e7359; background:#f1f6f2; font-size:11px; }.summary strong { margin-right:10px; }.steps { margin:0; padding:0; list-style:none; }.steps li { display:grid; grid-template-columns:26px 1fr; gap:9px; padding:12px 0; border-top:1px solid #edf0ed; }.steps li > span { display:grid; width:24px; height:24px; place-items:center; border-radius:50%; background:#53675a; color:#fff; font-size:10px; }.steps p { margin:0 0 6px; color:#56635a; font-size:11px; }.steps code { display:block; padding:8px; overflow-wrap:anywhere; border-radius:5px; background:#252d28; color:#eef3ef; font-size:10px; }.steps small { display:block; margin-top:6px; color:#758178; font-size:9px; }.quiz-tier { margin-top:14px; }.quiz-tier > div { margin-top:7px; padding:10px; border:1px solid #e3e7e4; border-radius:7px; background:#fbfcfb; }.quiz-tier strong { color:#7c877f; font-size:9px; }.quiz-tier p { margin:5px 0; font-size:11px; }.quiz-tier small { color:#758078; font-size:9px; }
.audit-panel { padding:15px; }.audit-empty { min-height:380px; }.verdict-summary { padding:13px 0; }.verdict-summary strong,.verdict-summary span { display:block; }.verdict-summary strong { color:#3f6750; font-size:14px; }.verdict-summary span { margin-top:3px; color:#909991; font-size:9px; }.claim-row { display:flex; gap:8px; padding:10px 0; border-top:1px solid #e9edea; }.claim-row > span { height:20px; padding:0 6px; border-radius:4px; background:#edf4ef; color:#426650; font-size:8px; line-height:20px; }.claim-row strong,.claim-row small { display:block; }.claim-row strong { font-size:10px; line-height:1.45; }.claim-row small { margin-top:4px; color:#879188; font-size:8px; }
.report-grid { display:grid; grid-template-columns:1fr 1fr; gap:14px; margin-top:14px; }.report-panel { padding:15px; }.report-empty { min-height:150px; }.match-body,.decision-body { padding-top:12px; }.interval { display:grid; grid-template-columns:1fr auto; gap:2px 10px; padding:10px; border-left:3px solid #4c7158; background:#f2f6f3; }.interval span,.interval small { color:#7b877f; font-size:9px; }.interval strong { grid-row:1/3; grid-column:2; align-self:center; font-size:18px; }.match-list { display:grid; grid-template-columns:repeat(3,1fr); gap:6px; margin-top:8px; }.match-list div { padding:8px; border:1px solid #e2e7e3; border-radius:6px; }.match-list span,.match-list strong,.match-list small { display:block; }.match-list span { color:#7d8981; font-size:8px; }.match-list strong { margin:4px 0; font-size:9px; }.match-list small { font-size:10px; }.gaps { display:flex; flex-wrap:wrap; gap:5px; margin-top:8px; }.gaps span,.candidate-list span { padding:4px 6px; border-radius:4px; background:#eef1ef; color:#667269; font-size:8px; }.selected-decision span,.selected-decision strong,.selected-decision small { display:block; }.selected-decision span { color:#7d8981; font-size:9px; }.selected-decision strong { margin:5px 0; font-size:14px; }.selected-decision small { color:#7d8981; font-size:9px; }.candidate-list { display:flex; flex-wrap:wrap; gap:5px; margin:10px 0; }.candidate-list span.selected { background:#dcebe0; color:#355941; }.decision-body p { display:flex; align-items:center; gap:6px; margin:10px 0 0; color:#57655b; font-size:10px; }
.interactive-band { margin-top:14px; padding:15px; }.interactive-head { justify-content:space-between; gap:12px; }.interactive-head h3 { margin:0; font-size:16px; }.interactive-head > span { display:flex; align-items:center; gap:5px; color:#51705b; font-size:9px; }.interactive-grid { display:grid; grid-template-columns:1.5fr 1fr; gap:12px; margin-top:14px; }.controls { display:grid; grid-template-columns:1.2fr 1.2fr .7fr .8fr auto; gap:9px; align-items:end; }.controls label { min-width:0; color:#68746c; font-size:9px; }.controls label span { display:flex; justify-content:space-between; margin-bottom:5px; }.controls input { width:100%; height:32px; box-sizing:border-box; accent-color:#476f55; }.controls input[type='number'],.fault-panel input,.fault-panel select { padding:0 7px; border:1px solid #d5ddd7; border-radius:5px; background:#fff; color:#3d4a41; font-size:9px; }.metrics { display:grid; grid-template-columns:repeat(4,1fr); border:1px solid #dfe5e0; border-radius:7px; }.metrics div { padding:9px; border-right:1px solid #e5e9e6; }.metrics div:last-child { border:0; }.metrics span,.metrics strong { display:block; }.metrics span { color:#879188; font-size:8px; }.metrics strong { margin-top:5px; font-size:11px; }.action-strip { gap:7px; margin-top:10px; }.fault-panel { display:flex; flex-wrap:wrap; gap:8px; align-items:center; margin-top:10px; padding:10px; border:1px solid #eaded4; border-radius:7px; background:#fffaf6; }.fault-panel > div { display:flex; align-items:center; gap:6px; margin-right:auto; color:#795d4a; font-size:10px; }.fault-panel select,.fault-panel input { height:32px; min-width:150px; }.danger { color:#8a463d; border-color:#e2c4bf; }.acceptance { gap:9px; margin-top:10px; padding:11px; border:1px solid #bfd9c6; border-radius:7px; background:#eff8f1; color:#365f43; }.acceptance div { margin-right:auto; }.acceptance strong,.acceptance span { display:block; }.acceptance strong { font-size:11px; }.acceptance span { margin-top:3px; font-size:9px; }.evidence-level { padding:6px 8px; border-radius:5px; background:#dceee1; font-weight:700; }.spin { animation:spin 1s linear infinite; }@keyframes spin { to { transform:rotate(360deg); } }
@media (max-width:1050px) { .main-grid { grid-template-columns:1fr; }.audit-panel { order:-1; }.audit-empty { min-height:120px; }.interactive-grid,.report-grid { grid-template-columns:1fr; }.controls { grid-template-columns:repeat(2,1fr); }.controls .secondary { width:100%; } }
@media (max-width:700px) { .page-head { align-items:flex-start; flex-direction:column; }.page-head > div:first-child { width:100%; }.head-actions { width:100%; }.head-actions .primary { min-width:0; flex:1; }.profile-band,.profile-detail,.role-rail { grid-template-columns:1fr; }.profile-band button,.profile-detail div,.role-rail > div { border-right:0; border-bottom:1px solid #e3e8e4; }.profile-band button:last-child,.profile-detail div:last-child,.role-rail > div:last-child { border-bottom:0; }.arrow { display:none; }.match-list,.metrics { grid-template-columns:1fr 1fr; }.metrics div:nth-child(2) { border-right:0; }.metrics div:nth-child(-n+2) { border-bottom:1px solid #e5e9e6; }.controls { grid-template-columns:1fr; }.context-line { align-items:flex-start; flex-direction:column; gap:5px; }.context-line span { max-width:100%; padding-right:0; border:0; overflow-wrap:anywhere; }.resource-body { padding:14px; }.fault-panel { align-items:stretch; flex-direction:column; }.fault-panel > div { margin-right:0; }.fault-panel select,.fault-panel input { width:100%; } }
</style>
