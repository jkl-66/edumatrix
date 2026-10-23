<script setup>
import { computed, onMounted, ref } from 'vue'
import {
  ArrowRight, Check, CircleAlert, CloudOff, Database, RefreshCw,
  RotateCcw, Send, ShieldCheck, Waypoints, Inbox, Play, LogOut,
  KeyRound, Webhook,
} from '@lucide/vue'
import {
  attemptM7Delivery,
  deliverM7ToLocalLrs,
  enqueueM7Delivery,
  getM7IntegrationWorkspace,
  launchM7Cmi5Session,
  requeueM7Delivery,
  transitionM7Cmi5Session,
  getLocalWebhookWorkspace,
  createLocalWebhookEndpoint,
  createLocalWebhookEvent,
  enqueueLocalWebhookEvent,
  sendLocalWebhookDelivery,
} from '../api/m7'

const workspace = ref({ organizations: [], selected: null })
const loading = ref(true)
const action = ref('')
const error = ref('')
const webhookWorkspace = ref({ endpoints: [], candidates: [], events: [], deliveries: [], receipts: [], security: {} })
const selected = computed(() => workspace.value.selected)
const truthfulness = computed(() => workspace.value.truthfulness || null)
const latestDelivery = computed(() => selected.value?.deliveries?.[0] || null)
const cmi5Session = computed(() => selected.value?.cmi5_sessions?.[0] || null)
const cmi5Candidate = computed(() => selected.value?.events?.find((item) => item.owner_public_id) || null)

function detailText(value) {
  if (typeof value === 'string') return value
  return value?.message || value?.code || '操作失败'
}

async function load(params = {}) {
  loading.value = true
  error.value = ''
  try {
    workspace.value = await getM7IntegrationWorkspace(params)
    if (workspace.value.selected) webhookWorkspace.value = await getLocalWebhookWorkspace(workspace.value.selected.organization.id)
  }
  catch (e) { error.value = detailText(e.detail || e.message) }
  finally { loading.value = false }
}

async function enqueue(event) {
  action.value = `enqueue:${event.id}`
  error.value = ''
  try {
    await enqueueM7Delivery({
      organization_id: selected.value.organization.id,
      event_id: event.id,
      destination_key: 'competition-mock-lrs',
    })
    await load({ organization_id: selected.value.organization.id })
  } catch (e) { error.value = detailText(e.detail || e.message) }
  finally { action.value = '' }
}

async function attempt(row, outcome) {
  action.value = `${outcome}:${row.id}`
  error.value = ''
  try {
    await attemptM7Delivery(row.id, outcome)
    await load({ organization_id: selected.value.organization.id })
  } catch (e) { error.value = detailText(e.detail || e.message) }
  finally { action.value = '' }
}

async function localLrs(row) {
  action.value = `lrs:${row.id}`; error.value = ''
  try { await deliverM7ToLocalLrs(row.id); await load({ organization_id: selected.value.organization.id }) }
  catch (e) { error.value = detailText(e.detail || e.message) }
  finally { action.value = '' }
}

async function requeue(row) {
  action.value = `requeue:${row.id}`; error.value = ''
  try { await requeueM7Delivery(row.id); await load({ organization_id: selected.value.organization.id }) }
  catch (e) { error.value = detailText(e.detail || e.message) }
  finally { action.value = '' }
}

async function launchCmi5() {
  action.value = 'cmi5:launch'; error.value = ''
  try {
    await launchM7Cmi5Session({ organization_id: selected.value.organization.id, learner_public_id: cmi5Candidate.value.owner_public_id, course_id: cmi5Candidate.value.course_id || null, launch_key: 'competition-cmi5-launch-001' })
    await load({ organization_id: selected.value.organization.id })
  } catch (e) { error.value = detailText(e.detail || e.message) }
  finally { action.value = '' }
}

async function transitionCmi5(kind) {
  action.value = `cmi5:${kind}`; error.value = ''
  try { await transitionM7Cmi5Session(cmi5Session.value.id, { action: kind, expected_lock_version: cmi5Session.value.lock_version }); await load({ organization_id: selected.value.organization.id }) }
  catch (e) { error.value = detailText(e.detail || e.message) }
  finally { action.value = '' }
}

async function initializeWebhook() {
  action.value = 'webhook:init'; error.value = ''
  try {
    await createLocalWebhookEndpoint({ organization_id: selected.value.organization.id, destination_key: 'competition-local-webhook' })
    await load({ organization_id: selected.value.organization.id })
  } catch (e) { error.value = detailText(e.detail || e.message) }
  finally { action.value = '' }
}

async function createWebhookEvent(candidate) {
  action.value = `webhook:event:${candidate.event_type}`; error.value = ''
  try {
    await createLocalWebhookEvent({ organization_id: selected.value.organization.id, event_type: candidate.event_type, source_object_id: candidate.source_object_id })
    await load({ organization_id: selected.value.organization.id })
  } catch (e) { error.value = detailText(e.detail || e.message) }
  finally { action.value = '' }
}

async function enqueueWebhook(row) {
  action.value = `webhook:enqueue:${row.id}`; error.value = ''
  try {
    await enqueueLocalWebhookEvent({ event_id: row.id, endpoint_id: webhookWorkspace.value.endpoints[0].id })
    await load({ organization_id: selected.value.organization.id })
  } catch (e) { error.value = detailText(e.detail || e.message) }
  finally { action.value = '' }
}

async function sendWebhook(row, fault = 'none') {
  action.value = `webhook:send:${row.id}`; error.value = ''
  try {
    await sendLocalWebhookDelivery(row.id, fault)
    await load({ organization_id: selected.value.organization.id })
  } catch (e) { error.value = detailText(e.detail || e.message); await load({ organization_id: selected.value.organization.id }) }
  finally { action.value = '' }
}

function statusLabel(status) {
  return ({ pending: '等待发送', failed: '等待重试', delivered: '已送达', dead_letter: '死信' })[status] || status
}

onMounted(() => load())
</script>

<template>
  <div class="integration-page">
    <header class="page-header">
      <div>
        <p class="eyebrow"><Waypoints :size="14" /> Integration sandbox</p>
        <h1>学习记录集成沙箱</h1>
        <p>将正式学习事件映射为最小 xAPI 语句，经过幂等队列写入持久化本地 LRS，并演示 cmi5 启动、会话、完成与退出子集。</p>
      </div>
      <button class="icon-button" title="刷新" aria-label="刷新集成工作台" @click="load()"><RefreshCw :size="17" /></button>
    </header>

    <div v-if="error" class="error-band"><CircleAlert :size="16" />{{ error }}</div>
    <div v-if="loading" class="loading-band"><RefreshCw :size="16" class="spin" />正在读取集成队列</div>
    <section v-if="!loading && truthfulness" class="boundary-band" aria-label="集成模拟边界">
      <CloudOff :size="17" />
      <div><strong>{{ truthfulness.data_label }}</strong><span>{{ truthfulness.disclaimer }}</span></div>
    </section>

    <section v-if="!loading && !selected" class="empty-state">
      <Database :size="34" />
      <h2>尚无可管理的企业组织</h2>
      <p>先在企业培训工作台初始化本地合成演示组织，再将该组织成员的学习事件送入本地集成沙箱。</p>
      <RouterLink to="/enterprise-training" class="primary-command"><ArrowRight :size="16" />前往企业培训</RouterLink>
    </section>

    <template v-else>
      <section class="truth-band">
        <div><Database :size="18" /><span>本地权威源</span><strong>{{ selected.organization.name }}</strong></div>
        <ArrowRight :size="17" />
        <div><Waypoints :size="18" /><span>适配与队列</span><strong>xAPI 1.0.3 map v1</strong></div>
        <ArrowRight :size="17" />
        <div><Inbox :size="18" /><span>接收端</span><strong>持久化本地 LRS</strong></div>
      </section>

      <section class="section-block">
        <div class="section-heading">
          <div><h2>可发送学习事件</h2><p>只显示当前组织成员的正式事件；重复入队复用同一幂等记录。</p></div>
          <span>{{ selected.events.length }} 条候选</span>
        </div>
        <div v-if="!selected.events.length" class="inline-empty">当前组织尚无学习事件，可先完成一次教师干预或学习任务。</div>
        <div v-else class="event-list">
          <div v-for="event in selected.events" :key="event.id" class="event-row">
            <div><strong>{{ event.event_type }}</strong><small>{{ event.object_type }} · {{ event.object_id }}</small></div>
            <code>{{ event.id }}</code>
            <button class="secondary-command" :disabled="action === `enqueue:${event.id}`" @click="enqueue(event)">
              <Send :size="14" />{{ action === `enqueue:${event.id}` ? '正在入队' : '映射并入队' }}
            </button>
          </div>
        </div>
      </section>

      <section class="section-block queue-section">
        <div class="section-heading">
          <div><h2>集成交付队列</h2><p>失败只更新队列；第五次失败进入死信，必须显式重入队后才能写入本地 LRS。</p></div>
          <span>{{ selected.deliveries.length }} 条记录</span>
        </div>
        <div v-if="!selected.deliveries.length" class="inline-empty">选择一条学习事件建立首个 xAPI 交付记录。</div>
        <div v-for="row in selected.deliveries" :key="row.id" class="delivery-row">
          <div class="delivery-main">
            <span class="status" :class="row.status"><Check v-if="row.status === 'delivered'" :size="13" />{{ statusLabel(row.status) }}</span>
            <div><strong>{{ row.destination_key }}</strong><small>{{ row.adapter_version }} · 尝试 {{ row.attempt_count }} 次</small></div>
            <code>{{ row.idempotency_key }}</code>
          </div>
          <div v-if="row.last_error_code" class="failure-note"><CloudOff :size="14" />{{ row.last_error_code }} · 本地事件未改变</div>
          <div class="payload-grid">
            <div><span>事件</span><strong>{{ row.payload?.verb?.display?.['en-US'] }}</strong></div>
            <div><span>对象</span><strong>{{ row.payload?.object?.definition?.type?.split('/').pop() }}</strong></div>
            <div><span>载荷哈希</span><code>{{ row.payload_hash.slice(0, 16) }}...</code></div>
          </div>
          <div v-if="row.status !== 'delivered' && row.status !== 'dead_letter'" class="delivery-actions">
            <button class="failure-command" :disabled="action.includes(row.id)" @click="attempt(row, 'failure')"><CloudOff :size="14" />模拟 LRS 不可用</button>
            <button class="primary-command" :disabled="action.includes(row.id)" @click="attempt(row, 'success')"><RotateCcw :size="14" />模拟恢复并送达</button>
            <button class="primary-command" :disabled="action.includes(row.id)" @click="localLrs(row)"><Inbox :size="14" />写入本地 LRS</button>
          </div>
          <div v-else-if="row.status === 'dead_letter'" class="delivery-actions"><button class="failure-command" :disabled="action.includes(row.id)" @click="requeue(row)"><RotateCcw :size="14" />显式重入队</button></div>
        </div>
      </section>

      <section class="section-block">
        <div class="section-heading"><div><h2>本地 LRS 收件箱</h2><p>每条已接收 xAPI statement 按 statement ID 幂等并冻结载荷与哈希。</p></div><span>{{ selected.lrs_statements.length }} 条语句</span></div>
        <div v-if="!selected.lrs_statements.length" class="inline-empty">选择“写入本地 LRS”后显示不可变接收记录。</div>
        <div v-else class="statement-list"><div v-for="item in selected.lrs_statements" :key="item.id" class="statement-row"><span class="status delivered"><Check :size="13" />已接收</span><div><strong>{{ item.verb_id.split('/').pop() }}</strong><small>{{ item.object_id }}</small></div><code>{{ item.statement_id }}</code><small>{{ item.statement_hash.slice(0, 16) }}...</small></div></div>
      </section>

      <section class="section-block cmi5-section">
        <div class="section-heading"><div><h2>cmi5 会话子集</h2><p>仅演示 launched → active → completed → exited；每次转换生成不可变事件和 xAPI delivery。</p></div><span>不宣称完整 cmi5 认证</span></div>
        <div v-if="!cmi5Session" class="cmi5-empty"><div><strong>冻结演示启动请求</strong><small>{{ cmi5Candidate ? `${cmi5Candidate.owner_public_id} · ${cmi5Candidate.course_id || '无课程绑定'}` : '等待组织学习事件' }}</small></div><button class="primary-command" :disabled="!cmi5Candidate || Boolean(action)" @click="launchCmi5"><Play :size="14" />启动 cmi5 会话</button></div>
        <div v-else class="cmi5-console"><div class="cmi5-facts"><div><span>registration</span><code>{{ cmi5Session.registration }}</code></div><div><span>状态</span><strong>{{ cmi5Session.status }}</strong></div><div><span>版本</span><strong>v{{ cmi5Session.lock_version }}</strong></div></div><div class="cmi5-actions"><button v-if="cmi5Session.status === 'launched'" class="primary-command" :disabled="Boolean(action)" @click="transitionCmi5('activate')"><Play :size="14" />进入学习会话</button><button v-if="cmi5Session.status === 'active'" class="primary-command" :disabled="Boolean(action)" @click="transitionCmi5('complete')"><Check :size="14" />标记完成</button><button v-if="['active','completed'].includes(cmi5Session.status)" class="secondary-command" :disabled="Boolean(action)" @click="transitionCmi5('exit')"><LogOut :size="14" />退出会话</button></div></div>
        <div v-if="selected.cmi5_events.length" class="timeline"><div v-for="item in selected.cmi5_events" :key="item.id"><span>{{ item.action }}</span><strong>{{ item.from_status }} → {{ item.to_status }}</strong><code>{{ item.event_hash.slice(0, 14) }}...</code></div></div>
      </section>

      <section class="section-block webhook-section">
        <div class="section-heading">
          <div><h2>签名 Webhook</h2><p>从培训与认证权威对象生成最小字段事件，使用 HMAC-SHA256、时间窗和 nonce 防重放。</p></div>
          <span>{{ webhookWorkspace.receipts.length }} 条接收日志</span>
        </div>
        <div v-if="!webhookWorkspace.endpoints.length" class="webhook-setup">
          <div><KeyRound :size="18" /><span><strong>尚未建立本地签名接收端</strong><small>密钥只保存在本地数据库，API 和页面只显示 SHA-256 指纹。</small></span></div>
          <button class="primary-command" :disabled="Boolean(action)" @click="initializeWebhook"><Webhook :size="14" />初始化接收端</button>
        </div>
        <template v-else>
          <div class="webhook-security">
            <div><span>算法</span><strong>{{ webhookWorkspace.security.algorithm }}</strong></div>
            <div><span>密钥指纹</span><code>{{ webhookWorkspace.endpoints[0].secret_fingerprint.slice(0, 20) }}...</code></div>
            <div><span>重放门禁</span><strong>时间窗 · nonce · event</strong></div>
            <div><span>敏感字段</span><strong>姓名/邮箱/分数/证据正文均排除</strong></div>
          </div>
          <div class="webhook-candidates">
            <button v-for="item in webhookWorkspace.candidates.filter((row) => row.eligible)" :key="`${item.event_type}:${item.source_object_id}`" class="candidate-command" :disabled="Boolean(action)" @click="createWebhookEvent(item)">
              <span>{{ item.event_type }}</span><strong>{{ item.label }}</strong><small>{{ item.status }}</small>
            </button>
          </div>
          <div v-if="webhookWorkspace.events.length" class="webhook-events">
            <div v-for="item in webhookWorkspace.events" :key="item.id" class="webhook-event-row">
              <div><strong>{{ item.event_type }}</strong><small>{{ item.source_object_type }} · {{ item.source_object_id }}</small></div>
              <code>{{ item.payload_hash.slice(0, 18) }}...</code>
              <button class="secondary-command" :disabled="Boolean(action)" @click="enqueueWebhook(item)"><Send :size="14" />签名队列</button>
            </div>
          </div>
          <div v-if="webhookWorkspace.deliveries.length" class="webhook-deliveries">
            <div v-for="row in webhookWorkspace.deliveries" :key="row.id" class="webhook-delivery-row">
              <span class="status" :class="row.status">{{ statusLabel(row.status) }}</span>
              <div><strong>{{ row.event_id }}</strong><small>尝试 {{ row.attempt_count }} 次 · {{ row.last_error_code || '无错误' }}</small></div>
              <div class="webhook-actions">
                <button v-if="!['delivered','dead_letter'].includes(row.status)" class="failure-command" :disabled="Boolean(action)" @click="sendWebhook(row, 'invalid_signature')"><ShieldCheck :size="14" />制造验签失败</button>
                <button v-if="!['delivered','dead_letter'].includes(row.status)" class="primary-command" :disabled="Boolean(action)" @click="sendWebhook(row)"><Webhook :size="14" />签名发送</button>
                <button v-if="row.status === 'dead_letter'" class="failure-command" :disabled="Boolean(action)" @click="requeue(row)"><RotateCcw :size="14" />显式重入队</button>
              </div>
            </div>
          </div>
          <div v-if="webhookWorkspace.receipts.length" class="webhook-receipts">
            <div v-for="receipt in webhookWorkspace.receipts" :key="receipt.id">
              <span class="status" :class="receipt.outcome === 'accepted' ? 'delivered' : 'failed'">{{ receipt.outcome === 'accepted' ? '已验签接收' : '已拒绝' }}</span>
              <div><strong>{{ receipt.reason_code }}</strong><small>{{ receipt.event_id }}</small></div>
              <code>{{ receipt.signature_prefix }}...</code>
            </div>
          </div>
        </template>
      </section>

      <section v-if="latestDelivery" class="assurance-band">
        <ShieldCheck :size="21" />
        <div><h2>能力声明边界</h2><p>{{ selected.transport.capability_claim }}。当前网络发送状态：{{ selected.transport.network_sent ? '已发送' : '未发送' }}。</p></div>
      </section>
    </template>
  </div>
</template>

<style scoped>
.integration-page{max-width:1320px;margin:0 auto;padding:4px 2px 42px;color:#20272a}.page-header{display:flex;justify-content:space-between;align-items:flex-start;padding:24px 2px 20px;border-bottom:1px solid #dce2e5}.page-header h1{font-size:24px;line-height:1.2;font-weight:750;margin:6px 0}.page-header>div>p:last-child{max-width:780px;color:#667177;font-size:13px}.eyebrow{display:flex;align-items:center;gap:7px;color:#1f6370;font-size:11px;font-weight:700;text-transform:uppercase}.icon-button{width:36px;height:36px;display:grid;place-items:center;border:1px solid #d8dfe2;background:#fff;border-radius:7px;color:#516068}.truth-band{display:grid;grid-template-columns:1fr auto 1fr auto 1fr;align-items:center;gap:16px;padding:20px;border-bottom:1px solid #dce2e5;background:#f6f9fa}.truth-band>div{display:grid;grid-template-columns:auto 1fr;column-gap:9px;align-items:center}.truth-band svg{grid-row:1/3}.truth-band span{font-size:10px;color:#728087}.truth-band strong{font-size:12px}.section-block{padding:26px 0;border-bottom:1px solid #dce2e5}.section-heading{display:flex;justify-content:space-between;align-items:flex-end;margin-bottom:13px}.section-heading h2{font-size:16px;font-weight:720}.section-heading p{font-size:11px;color:#748087;margin-top:4px}.section-heading>span{font-size:10px;color:#47717a;border:1px solid #c8d8dc;padding:5px 8px;border-radius:5px}.event-list,.delivery-row{border:1px solid #dce2e5;background:#fff}.event-row{display:grid;grid-template-columns:1.2fr 1fr auto;align-items:center;gap:16px;min-height:64px;padding:10px 14px;border-bottom:1px solid #e5eaec}.event-row:last-child{border-bottom:0}.event-row>div{display:flex;flex-direction:column}.event-row strong{font-size:12px}.event-row small{font-size:9px;color:#78848a;margin-top:3px}.event-row code,.delivery-main code{font-size:9px;color:#52656d;overflow-wrap:anywhere}.delivery-row{margin-top:10px}.delivery-main{display:grid;grid-template-columns:auto minmax(180px,.8fr) 1.2fr;align-items:center;gap:14px;padding:14px 16px}.delivery-main>div{display:flex;flex-direction:column}.delivery-main strong{font-size:12px}.delivery-main small{font-size:9px;color:#78848a;margin-top:3px}.status{display:inline-flex;align-items:center;gap:5px;width:max-content;padding:4px 7px;border-radius:4px;font-size:10px}.status.pending{color:#76571e;background:#fff6df}.status.failed,.status.dead_letter{color:#9a4439;background:#fff0ed}.status.delivered{color:#246246;background:#edf7f0}.failure-note{display:flex;align-items:center;gap:7px;padding:8px 16px;background:#fff4f1;color:#98483d;font-size:10px}.payload-grid{display:grid;grid-template-columns:1fr 1fr 1.2fr;border-top:1px solid #e5eaec}.payload-grid>div{display:flex;flex-direction:column;gap:3px;padding:11px 16px;border-right:1px solid #e5eaec}.payload-grid>div:last-child{border-right:0}.payload-grid span{font-size:9px;color:#7b878c}.payload-grid strong,.payload-grid code{font-size:10px}.delivery-actions{display:flex;justify-content:flex-end;gap:8px;padding:11px 16px;border-top:1px solid #e5eaec;background:#f8fafb}.primary-command,.secondary-command,.failure-command{display:inline-flex;align-items:center;justify-content:center;gap:7px;border:0;border-radius:6px;padding:8px 11px;font-size:11px;font-weight:650;cursor:pointer;text-decoration:none}.primary-command{background:#245f69;color:#fff}.secondary-command{background:#eaf2f4;color:#285d67}.failure-command{background:#fff0ed;color:#93463d}.primary-command:disabled,.secondary-command:disabled,.failure-command:disabled{opacity:.55;cursor:wait}.assurance-band{display:flex;gap:12px;align-items:center;padding:18px 20px;margin-top:22px;border:1px solid #bdd3c5;background:#f1f8f3;color:#285e43}.assurance-band h2{font-size:13px}.assurance-band p{font-size:10px;margin-top:3px}.inline-empty,.empty-state{color:#738086;font-size:11px}.inline-empty{padding:28px;text-align:center;border:1px dashed #cfd8dc}.empty-state{min-height:380px;display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center;gap:9px}.empty-state h2{font-size:17px;color:#20272a}.empty-state p{max-width:520px;margin-bottom:8px}.error-band,.loading-band{display:flex;align-items:center;gap:8px;padding:12px 16px;margin-top:14px;font-size:11px}.error-band{background:#fff1ef;color:#9b3f34}.loading-band{background:#f5f7f8;color:#55636a}.spin{animation:spin 1s linear infinite}@keyframes spin{to{transform:rotate(360deg)}}
.boundary-band{display:flex;align-items:center;gap:9px;padding:11px 14px;border-bottom:1px solid #e4d7ad;background:#fff8e6;color:#65511f}.boundary-band div{display:flex;flex-wrap:wrap;align-items:baseline;gap:5px 13px}.boundary-band strong{font-size:11px}.boundary-band span{font-size:10px;color:#78693f}
.statement-list{border:1px solid #dce2e5}.statement-row{display:grid;grid-template-columns:auto .9fr 1fr .6fr;align-items:center;gap:14px;padding:12px 14px;border-bottom:1px solid #e5eaec}.statement-row:last-child{border:0}.statement-row>div{display:flex;flex-direction:column}.statement-row strong{font-size:11px}.statement-row small,.statement-row code{font-size:8px;color:#748087;overflow-wrap:anywhere}.cmi5-empty{display:flex;align-items:center;justify-content:space-between;gap:16px;padding:18px;border:1px dashed #cfd8dc}.cmi5-empty>div{display:flex;flex-direction:column}.cmi5-empty strong{font-size:12px}.cmi5-empty small{font-size:9px;color:#748087;margin-top:3px}.cmi5-console{border:1px solid #dce2e5}.cmi5-facts{display:grid;grid-template-columns:1.4fr .7fr .5fr}.cmi5-facts>div{padding:13px;border-right:1px solid #e5eaec}.cmi5-facts span{display:block;font-size:8px;color:#748087}.cmi5-facts code,.cmi5-facts strong{font-size:10px}.cmi5-actions{display:flex;gap:8px;justify-content:flex-end;padding:11px;border-top:1px solid #e5eaec;background:#f8fafb}.timeline{display:grid;grid-template-columns:repeat(4,1fr);margin-top:12px;border:1px solid #dce2e5}.timeline>div{padding:11px;border-right:1px solid #e5eaec;display:flex;flex-direction:column}.timeline span{font-size:9px;color:#2e6872}.timeline strong{font-size:10px;margin:3px 0}.timeline code{font-size:8px;color:#748087}
.webhook-setup{display:flex;align-items:center;justify-content:space-between;gap:16px;padding:18px;border:1px dashed #cfd8dc}.webhook-setup>div{display:flex;align-items:center;gap:10px}.webhook-setup span{display:flex;flex-direction:column}.webhook-setup strong{font-size:12px}.webhook-setup small{font-size:9px;color:#748087}.webhook-security{display:grid;grid-template-columns:repeat(4,1fr);border:1px solid #dce2e5;background:#f7faf9}.webhook-security>div{padding:12px;border-right:1px solid #dce2e5;display:flex;flex-direction:column}.webhook-security>div:last-child{border:0}.webhook-security span{font-size:8px;color:#748087}.webhook-security strong,.webhook-security code{font-size:9px;overflow-wrap:anywhere}.webhook-candidates{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-top:12px}.candidate-command{min-height:72px;padding:10px;border:1px solid #d8e1e3;background:#fff;text-align:left;display:flex;flex-direction:column;cursor:pointer}.candidate-command span{font-size:8px;color:#2d6872}.candidate-command strong{font-size:10px;margin:4px 0}.candidate-command small{font-size:8px;color:#758188}.webhook-events,.webhook-deliveries,.webhook-receipts{margin-top:12px;border:1px solid #dce2e5}.webhook-event-row,.webhook-delivery-row,.webhook-receipts>div{display:grid;grid-template-columns:1fr .8fr auto;gap:12px;align-items:center;padding:11px;border-bottom:1px solid #e5eaec}.webhook-event-row:last-child,.webhook-delivery-row:last-child,.webhook-receipts>div:last-child{border:0}.webhook-event-row>div,.webhook-delivery-row>div,.webhook-receipts>div>div{display:flex;flex-direction:column}.webhook-event-row strong,.webhook-delivery-row strong,.webhook-receipts strong{font-size:10px}.webhook-event-row small,.webhook-delivery-row small,.webhook-receipts small,.webhook-event-row code,.webhook-receipts code{font-size:8px;color:#748087;overflow-wrap:anywhere}.webhook-actions{display:flex;flex-direction:row!important;gap:7px;justify-content:flex-end}
@media(max-width:800px){.truth-band{grid-template-columns:1fr}.truth-band>svg{display:none}.section-heading{align-items:flex-start;gap:10px;flex-direction:column}.event-row,.statement-row{grid-template-columns:1fr}.event-row button{width:100%}.delivery-main{grid-template-columns:1fr}.payload-grid{grid-template-columns:1fr}.payload-grid>div{border-right:0;border-bottom:1px solid #e5eaec}.payload-grid>div:last-child{border-bottom:0}.delivery-actions,.cmi5-actions{flex-direction:column}.delivery-actions button,.cmi5-actions button{width:100%}.cmi5-empty,.webhook-setup{align-items:flex-start;flex-direction:column}.cmi5-empty button,.webhook-setup button{width:100%}.cmi5-facts,.timeline,.webhook-security,.webhook-candidates{grid-template-columns:1fr}.cmi5-facts>div,.timeline>div,.webhook-security>div{border-right:0;border-bottom:1px solid #e5eaec}.webhook-event-row,.webhook-delivery-row,.webhook-receipts>div{grid-template-columns:1fr}.webhook-actions{flex-direction:column!important}.webhook-actions button,.webhook-event-row button{width:100%}}
</style>
