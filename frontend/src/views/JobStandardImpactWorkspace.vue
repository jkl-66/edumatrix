<script setup>
import { computed, onMounted, ref } from 'vue'
import { AlertTriangle, ArrowRight, CheckCircle2, FileDiff, RefreshCw, ShieldCheck } from '@lucide/vue'
import { getM6EnterpriseWorkspace } from '../api/m6'
import {
  confirmJobStandardImpact, createJobStandardImpactPreview,
  getJobStandardImpactWorkspace, prepareSyntheticJobStandard,
} from '../api/jobStandardImpact'

const organizationId = ref('')
const workspace = ref(null)
const sourceId = ref('')
const targetId = ref('')
const selected = ref(null)
const reason = ref('已核对冻结影响范围，同意按目标版本安排演示复训')
const busy = ref('')
const error = ref('')

const levels = computed(() => workspace.value?.job_levels || [])
const source = computed(() => levels.value.find(item => item.id === sourceId.value))
const compatibleTargets = computed(() => levels.value.filter(item =>
  item.id !== sourceId.value && item.job_family_id === source.value?.job_family_id && item.level_code === source.value?.level_code
))
const impact = computed(() => selected.value?.impact || {})
const diff = computed(() => selected.value?.diff || {})
const scheduling = computed(() => selected.value?.confirmation?.scheduling || null)

function chooseDefaults() {
  if (!levels.value.length) return
  if (!levels.value.some(item => item.id === sourceId.value)) sourceId.value = levels.value[0].id
  const targets = levels.value.filter(item => item.id !== sourceId.value && item.job_family_id === source.value?.job_family_id && item.level_code === source.value?.level_code)
  if (!targets.some(item => item.id === targetId.value)) targetId.value = targets.at(-1)?.id || ''
  selected.value = workspace.value?.previews?.[0] || null
}

async function load() {
  error.value = ''
  busy.value = 'load'
  try {
    if (!organizationId.value) {
      const enterprise = await getM6EnterpriseWorkspace()
      organizationId.value = enterprise.selected?.organization_id || enterprise.organizations?.[0]?.id || ''
    }
    if (!organizationId.value) throw new Error('请先在企业培训工作台准备合成组织样例')
    workspace.value = await getJobStandardImpactWorkspace(organizationId.value)
    chooseDefaults()
  } catch (cause) {
    error.value = cause.detail?.message || cause.detail || cause.message || '加载岗位标准失败'
  } finally { busy.value = '' }
}

async function prepare() {
  if (!sourceId.value) return
  busy.value = 'prepare'; error.value = ''
  try {
    const result = await prepareSyntheticJobStandard({ organization_id: organizationId.value, source_job_level_id: sourceId.value, target_version: '2026.2' })
    await load(); targetId.value = result.job_level_id
  } catch (cause) { error.value = cause.detail?.message || cause.detail || '准备样例失败'; busy.value = '' }
}

async function preview() {
  if (!sourceId.value || !targetId.value) return
  busy.value = 'preview'; error.value = ''
  try {
    const result = await createJobStandardImpactPreview({ organization_id: organizationId.value, source_job_level_id: sourceId.value, target_job_level_id: targetId.value })
    selected.value = result.preview
    await load()
    selected.value = workspace.value.previews.find(item => item.id === result.preview.id) || result.preview
  } catch (cause) { error.value = cause.detail?.message || cause.detail || '影响预览失败'; busy.value = '' }
}

async function confirm() {
  if (!selected.value || reason.value.trim().length < 4) return
  busy.value = 'confirm'; error.value = ''
  try {
    const result = await confirmJobStandardImpact(selected.value.id, { preview_hash: selected.value.preview_hash, reason: reason.value })
    selected.value = result.preview
    await load()
    selected.value = workspace.value.previews.find(item => item.id === result.preview.id) || result.preview
  } catch (cause) { error.value = cause.detail?.message || cause.detail || '确认调度失败'; busy.value = '' }
}

onMounted(load)
</script>

<template>
  <main class="impact-page">
    <header>
      <div><p>JOB STANDARD GOVERNANCE</p><h2>岗位标准升级影响与复训调度</h2><span>先冻结影响证据，再由主管显式确认调度</span></div>
      <button class="icon-button" aria-label="刷新岗位标准影响" @click="load"><RefreshCw :size="16" /></button>
    </header>

    <div class="truth"><ShieldCheck :size="17" /><div><strong>{{ workspace?.truth_label || '冻结合成岗位标准 · 比赛演示数据' }}</strong><span>{{ workspace?.disclaimer || '不宣称来自真实企业，不自动作出高风险人事决定。' }}</span></div></div>
    <p v-if="error" class="error"><AlertTriangle :size="15" />{{ error }}</p>

    <section class="selector">
      <label>源版本<select v-model="sourceId" @change="chooseDefaults"><option v-for="item in levels" :key="item.id" :value="item.id">{{ item.level_code }} · {{ item.version }} · {{ item.title }}</option></select></label>
      <ArrowRight :size="18" />
      <label>目标版本<select v-model="targetId"><option value="">尚未准备</option><option v-for="item in compatibleTargets" :key="item.id" :value="item.id">{{ item.level_code }} · {{ item.version }} · {{ item.title }}</option></select></label>
      <button v-if="!compatibleTargets.length && workspace?.role === 'admin'" :disabled="Boolean(busy)" @click="prepare">准备合成升级样例</button>
      <button :disabled="Boolean(busy) || !targetId" @click="preview"><FileDiff :size="15" />生成冻结影响预览</button>
    </section>

    <section class="layout">
      <aside>
        <h3>历史预览</h3>
        <button v-for="item in workspace?.previews || []" :key="item.id" :class="{ active: selected?.id === item.id }" @click="selected = item">
          <strong>{{ item.diff.source.version }} → {{ item.diff.target.version }}</strong>
          <span>{{ item.status }} · {{ item.impact.counts.learners }} 人</span>
        </button>
        <p v-if="!workspace?.previews?.length">尚无冻结预览</p>
      </aside>

      <div v-if="selected" class="detail">
        <div class="title"><div><h3>{{ diff.source?.version }} → {{ diff.target?.version }}</h3><span>预览哈希 {{ selected.preview_hash }}</span></div><em :class="selected.status">{{ selected.status }}</em></div>
        <div class="metrics">
          <article><strong>{{ impact.counts?.learners }}</strong><span>受影响人员</span></article>
          <article><strong>{{ impact.counts?.programs }}</strong><span>培训项目</span></article>
          <article><strong>{{ impact.counts?.cohorts }}</strong><span>培训班次</span></article>
          <article><strong>{{ impact.counts?.assignments }}</strong><span>既有分配</span></article>
          <article><strong>{{ impact.counts?.certifications }}</strong><span>关联认证</span></article>
        </div>

        <div class="diff-grid">
          <article><h4>职责变化</h4><p>{{ diff.responsibilities?.before?.join('；') || '无' }}</p><ArrowRight :size="14" /><p>{{ diff.responsibilities?.after?.join('；') || '无' }}</p></article>
          <article><h4>能力结构</h4><p>新增 {{ diff.competencies?.added?.length || 0 }} · 移除 {{ diff.competencies?.removed?.length || 0 }} · 变更 {{ diff.competencies?.changed?.length || 0 }}</p><pre>{{ JSON.stringify(diff.competencies, null, 2) }}</pre></article>
        </div>

        <div v-if="selected.status === 'pending'" class="confirm-box">
          <label>确认理由<input v-model="reason" aria-label="岗位标准升级确认理由" /></label>
          <button :disabled="Boolean(busy) || reason.trim().length < 4" @click="confirm"><CheckCircle2 :size="15" />确认影响并安排复训</button>
          <span>确认只针对上方 SHA-256；不匹配或陈旧预览将被拒绝。</span>
        </div>
        <div v-else class="scheduled">
          <CheckCircle2 :size="18" /><div><strong>已完成显式确认和幂等调度</strong><span>操作者 {{ selected.confirmation.actor_role }} · {{ selected.confirmation.actor_public_id }}</span></div>
          <dl><dt>新培训项目</dt><dd>{{ scheduling?.program_id }}</dd><dt>新培训班次</dt><dd>{{ scheduling?.cohort_id }}</dd><dt>新增分配</dt><dd>{{ scheduling?.assignment_ids_created?.length || 0 }}</dd><dt>复训任务</dt><dd>{{ scheduling?.retraining_task_ids_created?.length || 0 }}</dd></dl>
        </div>
      </div>
      <div v-else class="empty">选择两个版本并生成影响预览</div>
    </section>
  </main>
</template>

<style scoped>
.impact-page{max-width:1180px;margin:0 auto;color:#26322b}header,.truth,.selector,.title,.metrics,.confirm-box,.scheduled{display:flex;align-items:center}header{justify-content:space-between}header p{margin:0;color:#748078;font-size:10px;font-weight:800;letter-spacing:.12em}h2{margin:4px 0;font-size:24px}header span,.truth span,.title span,.scheduled span{display:block;color:#77857c;font-size:10px}.icon-button{display:grid;width:36px;height:36px;place-items:center;border:1px solid #dce5de;border-radius:7px;background:#fff}.truth{gap:9px;margin:14px 0;padding:11px;border-left:3px solid #c7a457;background:#fff9ed}.truth strong{font-size:11px}.selector{gap:10px;padding:12px;border:1px solid #dfe7e1;background:#fff}.selector label{min-width:0;flex:1;font-size:10px;font-weight:700}.selector select,.confirm-box input{display:block;width:100%;box-sizing:border-box;margin-top:5px;padding:8px;border:1px solid #d9e3dc;border-radius:6px;background:#fff}.selector button,.confirm-box button{display:flex;align-items:center;gap:5px;flex:0 0 auto;padding:9px;border:0;border-radius:6px;background:#30443a;color:#fff}.selector button:disabled,.confirm-box button:disabled{opacity:.45}.layout{display:grid;grid-template-columns:250px minmax(0,1fr);gap:10px;margin-top:10px}aside,.detail,.empty{min-width:0;padding:12px;border:1px solid #dfe7e1;background:#fff}aside h3{margin:0 0 8px;font-size:13px}aside button{display:block;width:100%;padding:10px;border:0;border-bottom:1px solid #e7eee9;background:transparent;text-align:left}aside button.active{background:#eef5f0}aside strong,aside span{display:block;font-size:10px}aside span{margin-top:4px;color:#77857d}.title{justify-content:space-between}.title h3{margin:0}.title span{max-width:520px;overflow-wrap:anywhere}.title em{padding:4px 7px;background:#f4e9cf;font-size:10px;font-style:normal}.title em.confirmed{background:#e4f1e8;color:#356044}.metrics{display:grid;grid-template-columns:repeat(5,1fr);gap:7px;margin:12px 0}.metrics article{padding:10px;background:#f4f7f5}.metrics strong,.metrics span{display:block}.metrics strong{font-size:19px}.metrics span{color:#748078;font-size:9px}.diff-grid{display:grid;grid-template-columns:1fr 1fr;gap:8px}.diff-grid article{min-width:0;padding:10px;border:1px solid #e3eae5}.diff-grid h4{margin:0 0 7px;font-size:11px}.diff-grid p{font-size:10px;line-height:1.5}.diff-grid pre{max-height:180px;overflow:auto;margin:0;padding:8px;background:#f5f7f5;font:9px/1.5 Consolas,monospace;white-space:pre-wrap}.confirm-box{align-items:flex-end;gap:8px;margin-top:10px;padding:10px;background:#fff8eb}.confirm-box label{min-width:0;flex:1;font-size:10px;font-weight:700}.confirm-box span{max-width:180px;color:#806d48;font-size:9px}.scheduled{align-items:flex-start;gap:8px;margin-top:10px;padding:11px;background:#edf6ef}.scheduled dl{display:grid;grid-template-columns:auto 1fr;gap:3px 8px;margin:0 0 0 auto;font-size:9px}.scheduled dt{color:#718078}.scheduled dd{margin:0;overflow-wrap:anywhere}.empty{display:grid;min-height:280px;place-items:center;color:#7d8982}.error{display:flex;align-items:center;gap:6px;padding:9px;background:#fff0ed;color:#994c40;font-size:11px}@media(max-width:760px){.selector,.confirm-box,.scheduled{align-items:stretch;flex-direction:column}.selector>svg{transform:rotate(90deg);align-self:center}.layout,.diff-grid{grid-template-columns:1fr}.metrics{grid-template-columns:repeat(2,1fr)}.scheduled dl{margin:8px 0 0}.title{align-items:flex-start;gap:8px}.title span{max-width:260px}}
</style>
