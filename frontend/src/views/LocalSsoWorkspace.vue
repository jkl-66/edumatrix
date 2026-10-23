<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import {
  AlertTriangle, BadgeCheck, Ban, CircleAlert, CloudOff, Fingerprint,
  KeyRound, Link2, LockKeyhole, Plus, RefreshCw, RotateCcw, ShieldCheck,
  Unlink, UserRoundCheck, UsersRound,
} from '@lucide/vue'
import {
  bindLocalSsoAssertion, createEmergencyAdminSession, createLocalSsoProvider,
  createLocalSsoSession, getLocalSsoWorkspace, previewLocalSsoAssertion,
  revokeLocalSsoMapping, updateLocalSsoProviderStatus,
} from '../api/localSso'

const workspace = ref({ organizations: [], selected: null, truthfulness: null })
const loading = ref(true)
const action = ref('')
const error = ref('')
const notice = ref('')
const preview = ref(null)
const selected = computed(() => workspace.value.selected)
const truth = computed(() => workspace.value.truthfulness)
const provider = computed(() => selected.value?.providers?.[0] || null)
const activeMappings = computed(() => selected.value?.mappings?.filter((item) => item.status === 'active') || [])
const form = ref({ subject: 'synthetic:learner-001', groups: ['learners'], target_user_public_id: '' })
const emergencyReason = ref('本地 IdP 故障演练期间保留管理员入口')

function detailText(value) {
  if (typeof value === 'string') return value
  return value?.message || value?.code || '操作失败'
}

function nextAssertionId(prefix = 'assertion') {
  return `${prefix}-${Date.now()}`
}

async function load(params = {}) {
  loading.value = true
  error.value = ''
  try {
    workspace.value = await getLocalSsoWorkspace(params)
    if (!form.value.target_user_public_id && selected.value?.members?.length) {
      const learner = selected.value.members.find((item) => item.organization_role !== 'admin')
      form.value.target_user_public_id = (learner || selected.value.members[0]).user_public_id
    }
  } catch (e) { error.value = detailText(e.detail || e.message) }
  finally { loading.value = false }
}

async function run(key, command, message) {
  action.value = key
  error.value = ''
  notice.value = ''
  try {
    await command()
    notice.value = message
    await load({ organization_id: selected.value?.organization?.id })
  } catch (e) { error.value = detailText(e.detail || e.message) }
  finally { action.value = '' }
}

async function createProvider() {
  await run('provider', () => createLocalSsoProvider({
    organization_id: selected.value.organization.id,
    provider_key: 'competition-local-idp',
    display_name: 'EduMatrix 比赛本地 IdP',
    protocol_style: 'oidc',
  }), '本地模拟 IdP 已创建，映射规则版本已冻结')
}

function assertionPayload(includeTarget = true) {
  const payload = {
    organization_id: selected.value.organization.id,
    provider_id: provider.value.id,
    assertion_id: nextAssertionId(),
    subject: form.value.subject.trim(),
    groups: form.value.groups,
  }
  if (includeTarget) payload.target_user_public_id = form.value.target_user_public_id
  return payload
}

async function doPreview() {
  action.value = 'preview'
  error.value = ''
  notice.value = ''
  try { preview.value = await previewLocalSsoAssertion(assertionPayload()) }
  catch (e) { error.value = detailText(e.detail || e.message) }
  finally { action.value = '' }
}

async function bind() {
  if (!preview.value) return
  const payload = {
    organization_id: selected.value.organization.id,
    provider_id: provider.value.id,
    assertion_id: preview.value.assertion_id,
    subject: preview.value.subject,
    groups: preview.value.groups,
    target_user_public_id: preview.value.target_user_public_id,
  }
  await run('bind', () => bindLocalSsoAssertion(payload), 'subject 已绑定，组织角色映射已应用')
  preview.value = null
}

async function login(mapping) {
  const groups = Object.entries(provider.value.group_role_map)
    .filter(([, role]) => role === selected.value.members.find((m) => m.user_public_id === mapping.user_public_id)?.organization_role)
    .map(([group]) => group)
  await run(`login:${mapping.id}`, () => createLocalSsoSession({
    organization_id: selected.value.organization.id,
    provider_id: provider.value.id,
    assertion_id: nextAssertionId('login'),
    subject: mapping.external_subject,
    groups: groups.length ? groups : ['learners'],
  }), '本地模拟登录已接受，已生成短时演示会话')
}

async function toggleProvider() {
  const nextStatus = provider.value.status === 'active' ? 'disabled' : 'active'
  await run('status', () => updateLocalSsoProviderStatus(provider.value.id, {
    organization_id: selected.value.organization.id,
    status: nextStatus,
    expected_lock_version: provider.value.lock_version,
  }), nextStatus === 'active' ? '本地模拟 IdP 已恢复' : '本地模拟 IdP 已停用，可验证应急入口')
}

async function revoke(mapping) {
  await run(`revoke:${mapping.id}`, () => revokeLocalSsoMapping(mapping.id, selected.value.organization.id), '映射和关联演示会话已撤销')
}

async function emergency() {
  await run('emergency', () => createEmergencyAdminSession({
    organization_id: selected.value.organization.id,
    reason: emergencyReason.value,
  }), '应急管理员演示会话已建立，未签发应用访问令牌')
}

watch(() => form.value.target_user_public_id, () => { preview.value = null })
watch(() => form.value.subject, () => { preview.value = null })
watch(() => form.value.groups, () => { preview.value = null }, { deep: true })
onMounted(() => load())
</script>

<template>
  <div class="sso-page">
    <header class="page-header">
      <div>
        <p class="eyebrow"><Fingerprint :size="14" /> FC4 identity integration</p>
        <h1>本地 SSO 身份映射</h1>
        <p>在本地确定性 IdP 中验证 subject、组角色映射、冲突、撤销和应急管理员流程。</p>
      </div>
      <button class="icon-button" title="刷新" aria-label="刷新本地 SSO 工作台" @click="load()"><RefreshCw :size="17" /></button>
    </header>

    <div v-if="error" class="message error"><CircleAlert :size="16" />{{ error }}</div>
    <div v-if="notice" class="message success"><BadgeCheck :size="16" />{{ notice }}</div>
    <div v-if="loading" class="message loading"><RefreshCw :size="16" class="spin" />正在恢复 SSO 状态</div>
    <section v-if="!loading && truth" class="boundary-band" aria-label="本地 SSO 模拟边界">
      <CloudOff :size="18" />
      <div><strong>{{ truth.data_label }}</strong><span>{{ truth.disclaimer }}</span></div>
    </section>

    <section v-if="!loading && !selected" class="empty-state">
      <UsersRound :size="36" /><h2>尚无可管理的演示组织</h2>
      <p>先在企业培训工作台初始化冻结合成组织和演示成员。</p>
      <RouterLink class="primary" to="/enterprise-training">前往企业培训</RouterLink>
    </section>

    <template v-else-if="!loading">
      <section class="status-strip">
        <div><span>组织</span><strong>{{ selected.organization.name }}</strong></div>
        <div><span>真实 IdP</span><strong>未连接</strong></div>
        <div><span>协议认证</span><strong>未验证</strong></div>
        <div><span>应用 Token</span><strong>不签发</strong></div>
      </section>

      <section v-if="!provider" class="setup-block">
        <LockKeyhole :size="28" />
        <div><h2>建立本地模拟 IdP</h2><p>创建 OIDC 风格 provider 和不可变的 groups → organization role 映射规则。</p></div>
        <button class="primary" :disabled="action === 'provider'" @click="createProvider"><Plus :size="15" />创建本地 IdP</button>
      </section>

      <template v-else>
        <section class="provider-bar">
          <div class="provider-title"><KeyRound :size="19" /><div><span>{{ provider.protocol_style.toUpperCase() }} 风格</span><strong>{{ provider.display_name }}</strong></div></div>
          <code>{{ provider.issuer }}</code>
          <span class="state" :class="provider.status">{{ provider.status === 'active' ? '运行中' : '已停用' }}</span>
          <button class="secondary" :disabled="action === 'status'" @click="toggleProvider">
            <Ban v-if="provider.status === 'active'" :size="14" /><RotateCcw v-else :size="14" />
            {{ provider.status === 'active' ? '模拟 IdP 故障' : '恢复 IdP' }}
          </button>
        </section>

        <div class="work-grid">
          <section class="section-block assertion-section">
            <div class="section-heading"><div><h2>1. 冻结合成 assertion</h2><p>先预览映射和冲突，再执行写入。</p></div><span>规则 v{{ provider.mapping_version }}</span></div>
            <label>绑定成员<select v-model="form.target_user_public_id"><option v-for="member in selected.members" :key="member.user_public_id" :value="member.user_public_id">{{ member.display_name }} · {{ member.organization_role }}</option></select></label>
            <label>subject<input v-model="form.subject" maxlength="256" /></label>
            <fieldset><legend>合成 groups</legend><label v-for="(roleName, group) in provider.group_role_map" :key="group" class="check"><input v-model="form.groups" type="checkbox" :value="group" /><span>{{ group }}</span><small>{{ roleName }}</small></label></fieldset>
            <button class="secondary wide" :disabled="!form.subject.trim() || action === 'preview'" @click="doPreview"><Fingerprint :size="15" />预览映射</button>
            <div v-if="preview" class="preview-box" :class="{ conflict: !preview.can_bind }">
              <div><span>解析角色</span><strong>{{ preview.resolved_role }}</strong></div>
              <div><span>命中规则</span><strong>{{ preview.matched_rules.length }} 条</strong></div>
              <div><span>写入判断</span><strong>{{ preview.can_bind ? '可绑定' : preview.conflict_code }}</strong></div>
              <button v-if="preview.can_bind" class="primary wide" :disabled="action === 'bind'" @click="bind"><Link2 :size="15" />确认绑定并应用角色</button>
            </div>
          </section>

          <section class="section-block">
            <div class="section-heading"><div><h2>2. 身份绑定与登录</h2><p>撤销后 fail-closed；重复 subject 不会跨用户接管。</p></div><span>{{ activeMappings.length }} 个有效映射</span></div>
            <div v-if="!selected.mappings.length" class="inline-empty">完成 assertion 预览和确认后显示绑定。</div>
            <article v-for="mapping in selected.mappings" :key="mapping.id" class="mapping-row">
              <div class="mapping-main"><UserRoundCheck :size="17" /><div><strong>{{ mapping.display_name }}</strong><code>{{ mapping.external_subject }}</code></div><span class="state" :class="mapping.status">{{ mapping.status === 'active' ? '有效' : '已撤销' }}</span></div>
              <div v-if="mapping.status === 'active'" class="row-actions">
                <button class="primary" :disabled="provider.status !== 'active' || action.includes(mapping.id)" @click="login(mapping)"><ShieldCheck :size="14" />模拟登录</button>
                <button class="danger" :disabled="action.includes(mapping.id)" @click="revoke(mapping)"><Unlink :size="14" />撤销</button>
              </div>
            </article>
          </section>
        </div>

        <section class="section-block recovery-block">
          <div class="section-heading"><div><h2>3. 故障与应急入口</h2><p>本地 IdP 停用时，组织管理员仍可建立 10 分钟应急演示会话。</p></div><span>独立于 provider</span></div>
          <div class="recovery-form"><label>应急原因<input v-model="emergencyReason" maxlength="256" /></label><button class="warning" :disabled="emergencyReason.trim().length < 8 || action === 'emergency'" @click="emergency"><AlertTriangle :size="15" />启用应急管理员</button></div>
        </section>

        <section class="audit-grid">
          <div><h2>演示会话</h2><p v-if="!selected.sessions.length" class="inline-empty">尚无会话。</p><div v-for="session in selected.sessions.slice(0, 6)" :key="session.id" class="audit-row"><span>{{ session.login_mode === 'emergency_admin' ? '应急管理员' : '模拟 SSO' }}</span><strong>{{ session.resolved_organization_role }} · {{ session.status }}</strong><code>{{ session.assertion_id }}</code></div></div>
          <div><h2>不可变决策事件</h2><p v-if="!selected.events.length" class="inline-empty">尚无事件。</p><div v-for="event in selected.events.slice(0, 6)" :key="event.id" class="audit-row"><span>{{ event.action }}</span><strong>{{ event.outcome }}</strong><code>{{ event.evidence_hash.slice(0, 18) }}...</code></div></div>
        </section>
      </template>
    </template>
  </div>
</template>

<style scoped>
.sso-page{max-width:1320px;margin:0 auto;padding:4px 2px 42px;color:#20272a}.page-header{display:flex;justify-content:space-between;align-items:flex-start;padding:24px 2px 20px;border-bottom:1px solid #dce2e5}.page-header h1{font-size:24px;line-height:1.2;font-weight:750;margin:6px 0}.page-header>div>p:last-child{max-width:780px;color:#667177;font-size:13px}.eyebrow{display:flex;align-items:center;gap:7px;color:#1f6370;font-size:11px;font-weight:700;text-transform:uppercase}.icon-button{width:36px;height:36px;display:grid;place-items:center;border:1px solid #d8dfe2;background:#fff;border-radius:7px;color:#516068}.message{display:flex;align-items:center;gap:8px;padding:11px 14px;margin-top:12px;font-size:11px}.message.error{background:#fff1ef;color:#963f35}.message.success{background:#eef8f1;color:#276046}.message.loading{background:#f4f7f8;color:#56646a}.boundary-band{display:flex;align-items:center;gap:10px;padding:12px 15px;border-bottom:1px solid #e4d7ad;background:#fff8e6;color:#65511f}.boundary-band div{display:flex;flex-wrap:wrap;align-items:baseline;gap:5px 14px}.boundary-band strong{font-size:11px}.boundary-band span{font-size:10px;color:#78693f}.status-strip{display:grid;grid-template-columns:repeat(4,1fr);border-bottom:1px solid #dce2e5;background:#f6f9fa}.status-strip div{padding:14px 18px;border-right:1px solid #e0e6e8}.status-strip div:last-child{border:0}.status-strip span{display:block;color:#77858a;font-size:9px}.status-strip strong{font-size:12px}.setup-block{min-height:310px;display:flex;align-items:center;justify-content:center;gap:18px;border-bottom:1px solid #dce2e5}.setup-block h2{font-size:16px}.setup-block p{color:#758187;font-size:10px;margin-top:4px}.provider-bar{display:grid;grid-template-columns:minmax(220px,.7fr) minmax(220px,1fr) auto auto;align-items:center;gap:14px;padding:17px 18px;border-bottom:1px solid #dce2e5}.provider-title{display:flex;align-items:center;gap:10px}.provider-title div{display:flex;flex-direction:column}.provider-title span{font-size:9px;color:#748086}.provider-title strong{font-size:12px}.provider-bar code{font-size:9px;color:#52656d;overflow-wrap:anywhere}.state{width:max-content;padding:4px 7px;border-radius:4px;font-size:9px}.state.active{background:#edf7f0;color:#246246}.state.disabled,.state.revoked{background:#fff0ed;color:#93463d}.work-grid{display:grid;grid-template-columns:minmax(320px,.85fr) minmax(400px,1.15fr);gap:28px;border-bottom:1px solid #dce2e5}.section-block{padding:25px 0}.work-grid .section-block:first-child{padding-right:28px;border-right:1px solid #dce2e5}.section-heading{display:flex;justify-content:space-between;align-items:flex-end;gap:10px;margin-bottom:16px}.section-heading h2,.audit-grid h2{font-size:15px;font-weight:720}.section-heading p{font-size:10px;color:#748087;margin-top:4px}.section-heading>span{font-size:9px;color:#47717a;border:1px solid #c8d8dc;padding:5px 8px;border-radius:5px}.section-block>label,.recovery-form label{display:flex;flex-direction:column;gap:5px;margin-bottom:11px;font-size:10px;color:#6a777d}.section-block input,.section-block select{height:35px;border:1px solid #d4dde0;border-radius:5px;padding:0 9px;background:#fff;color:#253036;font-size:11px}.section-block fieldset{border:1px solid #dce2e5;padding:10px;margin:3px 0 12px}.section-block legend{font-size:9px;color:#6e7b81;padding:0 5px}.check{display:grid;grid-template-columns:auto 1fr auto;align-items:center;gap:8px;padding:5px 2px;font-size:10px}.check input{width:14px;height:14px}.check small{color:#79858a}.preview-box{display:grid;grid-template-columns:repeat(3,1fr);gap:1px;background:#dbe4e6;border:1px solid #dbe4e6;margin-top:12px}.preview-box>div{background:#f5faf8;padding:10px}.preview-box span{display:block;font-size:8px;color:#748087}.preview-box strong{font-size:10px}.preview-box button{grid-column:1/-1;border-radius:0}.preview-box.conflict>div{background:#fff3f0}.mapping-row{border:1px solid #dce2e5;margin-top:9px;background:#fff}.mapping-main{display:grid;grid-template-columns:auto 1fr auto;align-items:center;gap:9px;padding:12px}.mapping-main>div{display:flex;flex-direction:column;min-width:0}.mapping-main strong{font-size:11px}.mapping-main code{font-size:9px;color:#617077;overflow-wrap:anywhere}.row-actions{display:flex;justify-content:flex-end;gap:7px;padding:9px 12px;border-top:1px solid #e5eaec;background:#f8fafb}.recovery-block{border-bottom:1px solid #dce2e5}.recovery-form{display:grid;grid-template-columns:1fr auto;gap:12px;align-items:end}.recovery-form label{margin:0}.audit-grid{display:grid;grid-template-columns:1fr 1fr;gap:28px;padding-top:24px}.audit-grid>div:first-child{padding-right:28px;border-right:1px solid #dce2e5}.audit-row{display:grid;grid-template-columns:1fr auto;gap:4px 10px;padding:10px 0;border-bottom:1px solid #e3e8ea}.audit-row span{font-size:10px}.audit-row strong{font-size:9px;color:#42646c}.audit-row code{grid-column:1/-1;font-size:8px;color:#7a878c;overflow-wrap:anywhere}.primary,.secondary,.danger,.warning{display:inline-flex;align-items:center;justify-content:center;gap:7px;border:0;border-radius:6px;padding:8px 11px;font-size:10px;font-weight:650;cursor:pointer;text-decoration:none}.primary{background:#245f69;color:#fff}.secondary{background:#eaf2f4;color:#285d67}.danger{background:#fff0ed;color:#93463d}.warning{background:#fff1cf;color:#76551b}.wide{width:100%}.primary:disabled,.secondary:disabled,.danger:disabled,.warning:disabled{opacity:.5;cursor:not-allowed}.inline-empty{padding:24px;text-align:center;color:#78858a;font-size:10px;border:1px dashed #d1dadd}.empty-state{min-height:380px;display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center;gap:9px}.empty-state h2{font-size:17px}.empty-state p{color:#748086;font-size:11px}.spin{animation:spin 1s linear infinite}@keyframes spin{to{transform:rotate(360deg)}}
@media(max-width:800px){.status-strip{grid-template-columns:1fr 1fr}.status-strip div:nth-child(2){border-right:0}.provider-bar{grid-template-columns:1fr}.provider-bar .secondary{width:100%}.work-grid{grid-template-columns:1fr;gap:0}.work-grid .section-block:first-child{padding-right:0;border-right:0;border-bottom:1px solid #dce2e5}.section-heading{align-items:flex-start;flex-direction:column}.preview-box{grid-template-columns:1fr}.preview-box button{grid-column:auto}.recovery-form{grid-template-columns:1fr}.audit-grid{grid-template-columns:1fr}.audit-grid>div:first-child{padding-right:0;border-right:0}.row-actions{flex-direction:column}.row-actions button{width:100%}}
</style>
