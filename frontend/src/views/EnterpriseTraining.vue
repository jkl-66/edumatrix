<script setup>
import { computed, onMounted, ref } from 'vue'
import {
  Award, BriefcaseBusiness, Check, CircleAlert, ClipboardCheck,
  RefreshCw, ShieldCheck, Target, UserRoundCheck,
} from '@lucide/vue'
import {
  bootstrapM6TrainingDemo,
  getM6EnterpriseWorkspace,
  issueM6Certification,
  recordM6SkillEvidence,
} from '../api/m6'

const loading = ref(true)
const action = ref('')
const error = ref('')
const payload = ref(null)

const selected = computed(() => payload.value?.selected || null)
const truthfulness = computed(() => payload.value?.truthfulness || null)
const competencies = computed(() => selected.value?.competencies || [])
const passedEvidenceIds = computed(() => competencies.value.flatMap(item =>
  item.evidence.filter(evidence => evidence.result === 'passed').map(evidence => evidence.id),
))

function detailText(value) {
  if (typeof value === 'string') return value
  return value?.message || value?.code || JSON.stringify(value || '')
}

async function load(params = {}) {
  loading.value = true
  error.value = ''
  try { payload.value = await getM6EnterpriseWorkspace(params) }
  catch (e) { error.value = detailText(e.detail || e.message) }
  finally { loading.value = false }
}

async function bootstrap() {
  action.value = 'bootstrap'
  error.value = ''
  try {
    const result = await bootstrapM6TrainingDemo()
    await load({ organization_id: result.organization_id, learner_public_id: result.learner_public_id })
  } catch (e) { error.value = detailText(e.detail || e.message) }
  finally { action.value = '' }
}

async function approveEvidence(item) {
  action.value = item.standard_id
  error.value = ''
  const evidenceType = item.required_evidence_types[0] || 'artifact'
  try {
    await recordM6SkillEvidence({
      organization_id: selected.value.organization_id,
      learner_public_id: selected.value.learner.public_id,
      competency_standard_id: item.standard_id,
      evidence_type: evidenceType,
      source_object_id: `training-review-${item.skill_level}-${Date.now()}`,
      result: 'passed',
      score: evidenceType === 'expert_observation' ? 0.93 : 0.9,
      hidden_test_result: evidenceType === 'hidden_test' ? { passed: 4, total: 4 } : {},
    })
    await load({
      organization_id: selected.value.organization_id,
      learner_public_id: selected.value.learner.public_id,
    })
  } catch (e) { error.value = detailText(e.detail || e.message) }
  finally { action.value = '' }
}

async function certify() {
  action.value = 'certify'
  error.value = ''
  try {
    await issueM6Certification({
      organization_id: selected.value.organization_id,
      learner_public_id: selected.value.learner.public_id,
      job_level_id: selected.value.assignment.standard_snapshot.job_level_id,
      evidence_ids: passedEvidenceIds.value,
      retraining_rule: { cycle_days: 180, reason: '岗位标准周期复核' },
    })
    await load({
      organization_id: selected.value.organization_id,
      learner_public_id: selected.value.learner.public_id,
    })
  } catch (e) { error.value = detailText(e.detail || e.message) }
  finally { action.value = '' }
}

onMounted(() => load())
</script>

<template>
  <div class="training-page">
    <header class="training-header">
      <div>
        <p class="eyebrow"><BriefcaseBusiness :size="14" /> Enterprise skills</p>
        <h1>岗位能力与转岗培训</h1>
        <p>用统一岗位标准核对能力差距，让培训、实操证据、人工签核与认证保持同一数据链。</p>
      </div>
      <button class="icon-button" title="刷新" aria-label="刷新企业培训数据" @click="load()"><RefreshCw :size="17" /></button>
    </header>

    <div v-if="error" class="error-band"><CircleAlert :size="16" />{{ error }}</div>
    <div v-if="loading" class="loading-band"><RefreshCw :size="16" class="spin" />正在核对岗位标准与技能证据</div>
    <section v-if="!loading && truthfulness" class="truthfulness-band" aria-label="企业培训演示边界">
      <ShieldCheck :size="18" />
      <div><strong>{{ truthfulness.data_label }}</strong><span>{{ truthfulness.review_label }}</span></div>
    </section>

    <section v-if="!loading && !selected" class="empty-state">
      <ShieldCheck :size="34" />
      <h2>尚未建立企业培训样例</h2>
      <p>初始化将创建本地演示组织、冻结合成岗位标准、培训批次、转岗学员和一条演示基础证据。</p>
      <button class="primary-command" :disabled="action === 'bootstrap'" @click="bootstrap">
        <ClipboardCheck :size="16" />{{ action === 'bootstrap' ? '正在初始化' : '初始化比赛培训样例' }}
      </button>
    </section>

    <template v-if="!loading && selected">
      <section class="summary-band">
        <div class="job-identity">
          <span>{{ selected.job.family }} · {{ selected.job.level_code }}</span>
          <h2>{{ selected.job.level }}</h2>
          <p>标准版本 {{ selected.job.version }} · {{ selected.assignment.program }} {{ selected.assignment.program_version }}</p>
        </div>
        <div class="metric"><strong>{{ selected.summary.satisfied }}/{{ selected.summary.required }}</strong><span>必修能力已满足</span></div>
        <div class="metric"><strong>{{ selected.summary.gaps }}</strong><span>待补能力差距</span></div>
        <div class="metric"><strong>{{ Math.round(selected.summary.completion_rate * 100) }}%</strong><span>岗位匹配度</span></div>
      </section>

      <section class="context-strip">
        <div><UserRoundCheck :size="15" /><span>转岗学员</span><strong>{{ selected.learner.display_name }}</strong></div>
        <div><Target :size="15" /><span>分配来源</span><strong>岗位转岗计划</strong></div>
        <div><ShieldCheck :size="15" /><span>标准快照</span><strong>{{ selected.assignment.standard_snapshot.job_level_version }}</strong></div>
      </section>

      <section class="competency-section">
        <div class="section-heading">
          <div><h2>能力差距矩阵</h2><p>只有有效、通过且类型匹配的证据才能关闭差距；高风险能力在本地比赛环境中由演示角色复核。</p></div>
          <span class="snapshot-tag">批次快照已锁定</span>
        </div>
        <div class="competency-table">
          <div class="table-head"><span>能力层级</span><span>目标要求</span><span>验收证据</span><span>状态</span><span>操作</span></div>
          <div v-for="item in competencies" :key="item.standard_id" class="table-row">
            <div><strong>{{ item.skill_title }}</strong><small>{{ item.skill_level }} · {{ item.risk_level === 'high' ? '高风险' : '常规' }}</small></div>
            <span>{{ item.requirement_level }}</span>
            <span>{{ item.required_evidence_types.join(' / ') }}</span>
            <span class="status" :class="item.status"><Check v-if="item.status === 'satisfied'" :size="13" />{{ item.status === 'satisfied' ? '证据满足' : '需要培训' }}</span>
            <button v-if="item.status !== 'satisfied'" class="review-command" :disabled="action === item.standard_id" @click="approveEvidence(item)">
              <ClipboardCheck :size="14" />{{ item.risk_level === 'high' ? '演示角色复核' : '验收通过' }}
            </button>
            <span v-else class="evidence-count">{{ item.evidence.length }} 条证据</span>
          </div>
        </div>
      </section>

      <section class="certification-band" :class="{ ready: selected.summary.certification_ready }">
        <div>
          <Award :size="24" />
          <div><h2>{{ selected.certifications.length ? '本地演示认证已签发' : selected.summary.certification_ready ? '已达到演示认证门槛' : '演示认证门槛尚未满足' }}</h2>
          <p>{{ selected.certifications.length ? '演示认证绑定当前标准快照，并在 180 天后进入复训复核；不代表真实企业认证。' : '必须覆盖全部必修能力；系统不会自动执行调岗、晋升或人事决定。' }}</p></div>
        </div>
        <button v-if="selected.summary.certification_ready && !selected.certifications.length" class="primary-command" :disabled="action === 'certify'" @click="certify">
          <Award :size="16" />{{ action === 'certify' ? '正在签发' : '签发本地演示认证' }}
        </button>
        <span v-else-if="selected.certifications.length" class="certified-mark"><Check :size="15" />Active · 180 天复训</span>
      </section>
    </template>
  </div>
</template>

<style scoped>
.training-page{max-width:1320px;margin:0 auto;padding:4px 2px 42px;color:#202a24}.training-header{display:flex;align-items:flex-start;justify-content:space-between;padding:24px 2px 20px;border-bottom:1px solid #dfe4df}.training-header h1{font-size:24px;line-height:1.2;font-weight:750;margin:6px 0}.training-header>div>p:last-child{max-width:760px;color:#657168;font-size:13px}.eyebrow{display:flex;align-items:center;gap:7px;color:#356b50;font-size:11px;font-weight:700;text-transform:uppercase}.icon-button{width:36px;height:36px;display:grid;place-items:center;border:1px solid #d9dfda;background:#fff;border-radius:7px;color:#526057}.summary-band{display:grid;grid-template-columns:minmax(320px,1.8fr) repeat(3,minmax(110px,.55fr));border-bottom:1px solid #dfe4df;background:#f8faf8}.job-identity{padding:24px 22px;border-right:1px solid #dfe4df}.job-identity span{font-size:11px;color:#4d705d}.job-identity h2{font-size:18px;font-weight:720;margin:4px 0}.job-identity p{font-size:11px;color:#748078}.metric{display:flex;flex-direction:column;justify-content:center;padding:20px;border-right:1px solid #dfe4df}.metric:last-child{border-right:0}.metric strong{font-size:24px;color:#285a42}.metric span{font-size:10px;color:#748078;margin-top:4px}.context-strip{display:flex;gap:28px;padding:13px 20px;border-bottom:1px solid #dfe4df;background:#fff}.context-strip div{display:flex;align-items:center;gap:7px;font-size:11px}.context-strip span{color:#7b867f}.context-strip strong{font-weight:650}.competency-section{padding:26px 0}.section-heading{display:flex;justify-content:space-between;align-items:flex-end;margin-bottom:13px}.section-heading h2{font-size:16px;font-weight:720}.section-heading p{font-size:11px;color:#758078;margin-top:4px}.snapshot-tag{font-size:10px;padding:5px 8px;border:1px solid #bad2c3;color:#356b50;background:#f2f8f4;border-radius:5px}.competency-table{border:1px solid #dfe4df;background:#fff}.table-head,.table-row{display:grid;grid-template-columns:1.35fr 1.1fr 1fr .8fr .8fr;align-items:center;gap:14px;padding:12px 16px}.table-head{font-size:10px;color:#748078;background:#f5f7f5;border-bottom:1px solid #dfe4df}.table-row{min-height:67px;border-bottom:1px solid #e7ebe7;font-size:11px}.table-row:last-child{border-bottom:0}.table-row>div{display:flex;flex-direction:column}.table-row strong{font-size:12px}.table-row small{font-size:9px;color:#7d8880;margin-top:3px}.status{display:inline-flex;align-items:center;gap:5px;width:max-content;padding:4px 7px;border-radius:4px}.status.satisfied{color:#276444;background:#edf7f0}.status.training_required{color:#8a5720;background:#fff5e8}.review-command,.primary-command{display:inline-flex;align-items:center;justify-content:center;gap:7px;border:0;border-radius:6px;font-size:11px;font-weight:650;cursor:pointer}.review-command{padding:7px 9px;background:#edf3ef;color:#315d46}.primary-command{padding:9px 13px;background:#285a42;color:white}.review-command:disabled,.primary-command:disabled{opacity:.55;cursor:wait}.evidence-count{font-size:10px;color:#778179}.certification-band{display:flex;align-items:center;justify-content:space-between;padding:18px 20px;border:1px solid #e0d7c4;background:#fffaf0}.certification-band.ready{border-color:#a9cbb6;background:#f1f8f3}.certification-band>div{display:flex;align-items:center;gap:13px}.certification-band h2{font-size:14px;font-weight:720}.certification-band p{font-size:10px;color:#6e786f;margin-top:4px}.certified-mark{display:inline-flex;align-items:center;gap:6px;color:#286044;font-size:11px;font-weight:700}.empty-state{min-height:380px;display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center;gap:9px}.empty-state h2{font-size:17px}.empty-state p{font-size:11px;color:#758078;max-width:520px;margin-bottom:8px}.error-band,.loading-band{display:flex;align-items:center;gap:8px;padding:12px 16px;margin-top:14px;font-size:11px}.error-band{background:#fff1ef;color:#9b3f34}.loading-band{background:#f5f7f5;color:#556159}.spin{animation:spin 1s linear infinite}@keyframes spin{to{transform:rotate(360deg)}}
.truthfulness-band{display:flex;align-items:center;gap:10px;padding:11px 14px;border-bottom:1px solid #e6d7aa;background:#fff8e6;color:#65511f}.truthfulness-band div{display:flex;flex-wrap:wrap;align-items:baseline;gap:6px 14px}.truthfulness-band strong{font-size:11px}.truthfulness-band span{font-size:10px;color:#78693f}
@media(max-width:800px){.summary-band{grid-template-columns:1fr 1fr}.job-identity{grid-column:1/-1}.metric{border-top:1px solid #dfe4df}.context-strip{flex-direction:column;gap:8px}.section-heading{align-items:flex-start;gap:10px;flex-direction:column}.competency-table{overflow-x:auto}.table-head,.table-row{min-width:760px}.certification-band{align-items:flex-start;gap:16px;flex-direction:column}}
</style>
