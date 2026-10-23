<script setup>
import { computed, onMounted, ref } from 'vue'
import {
  BookOpenText,
  Check,
  ChevronDown,
  ChevronRight,
  FileCheck2,
  FileText,
  RefreshCw,
  RotateCcw,
  Send,
  ShieldCheck,
  Undo2,
} from '@lucide/vue'
import PageHeader from '../components/PageHeader.vue'
import RecoveryBanner from '../components/RecoveryBanner.vue'
import TaskState from '../components/TaskState.vue'
import {
  decideContentReview,
  getContentReviewCase,
  getContentReviewQueue,
} from '../api/contentReview'

const statusOptions = [
  { value: '', label: '全部案件' },
  { value: 'pending', label: '待审核' },
  { value: 'changes_requested', label: '待返工' },
  { value: 'approved', label: '待发布' },
  { value: 'published', label: '已发布' },
  { value: 'withdrawn', label: '已下架' },
]

const statusLabels = {
  pending: '待审核',
  changes_requested: '待返工',
  approved: '待发布',
  published: '已发布',
  withdrawn: '已下架',
  completed: '已完成',
  failed: '失败',
}

const roleLabels = {
  analysis: '内容分析',
  generation: '候选生成',
  validation: '交叉校验',
  decision: '审核决策',
}

const loading = ref(true)
const refreshing = ref(false)
const detailLoading = ref(false)
const busy = ref('')
const loadError = ref('')
const actionError = ref('')
const recoveryMessage = ref('')
const filter = ref('')
const items = ref([])
const selectedId = ref('')
const detail = ref(null)
const reason = ref('')

const selectedSummary = computed(() => (
  items.value.find((item) => item.id === selectedId.value) || null
))

const actions = computed(() => {
  if (detail.value?.status === 'pending') {
    return [
      { key: 'request_changes', label: '要求返工', icon: RotateCcw, primary: false },
      { key: 'approve', label: '批准内容', icon: Check, primary: true },
    ]
  }
  if (detail.value?.status === 'approved') {
    return [{ key: 'publish', label: '发布内容', icon: Send, primary: true }]
  }
  if (detail.value?.status === 'published') {
    return [{ key: 'withdraw', label: '下架内容', icon: Undo2, primary: true }]
  }
  return []
})

const reasonReady = computed(() => reason.value.trim().length >= 4)

function errorMessage(error, fallback) {
  const value = error?.detail || error?.message
  if (typeof value === 'string') return value
  return value?.message || fallback
}

function statusLabel(status) {
  return statusLabels[status] || '状态未知'
}

function formatDate(value) {
  if (!value) return '未记录'
  return new Intl.DateTimeFormat('zh-CN', {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(new Date(value))
}

function sourceLabel(sourceRefId) {
  const source = detail.value?.evidence?.sources?.find((item) => item.id === sourceRefId)
  return source?.document_title || sourceRefId || '未关联来源'
}

async function loadCase(caseId, { keepPrevious = true } = {}) {
  if (!caseId) {
    detail.value = null
    return
  }
  if (!keepPrevious) detail.value = null
  detailLoading.value = true
  actionError.value = ''
  try {
    detail.value = await getContentReviewCase(caseId)
  } catch (error) {
    actionError.value = errorMessage(error, '案件详情加载失败，已保留当前内容')
  } finally {
    detailLoading.value = false
  }
}

async function loadQueue({ quiet = false, preserveReason = true } = {}) {
  if (quiet) refreshing.value = true
  else loading.value = true
  loadError.value = ''
  const pendingReason = reason.value
  const previousId = selectedId.value
  try {
    const response = await getContentReviewQueue(filter.value)
    items.value = response.items || []
    const nextId = items.value.some((item) => item.id === previousId)
      ? previousId
      : items.value[0]?.id || ''
    if (nextId !== previousId && preserveReason) reason.value = ''
    selectedId.value = nextId
    if (!nextId) detail.value = null
    else await loadCase(nextId)
    if (preserveReason && nextId === previousId) reason.value = pendingReason
  } catch (error) {
    loadError.value = errorMessage(error, '审核队列加载失败，已保留上一次结果')
  } finally {
    loading.value = false
    refreshing.value = false
  }
}

async function selectCase(caseId) {
  if (caseId === selectedId.value) return
  selectedId.value = caseId
  reason.value = ''
  actionError.value = ''
  recoveryMessage.value = ''
  await loadCase(caseId, { keepPrevious: false })
}

async function changeFilter() {
  selectedId.value = ''
  detail.value = null
  reason.value = ''
  recoveryMessage.value = ''
  await loadQueue()
}

async function recoverConflict() {
  const pendingReason = reason.value
  try {
    const latest = await getContentReviewCase(selectedId.value)
    detail.value = latest
    items.value = items.value.map((item) => item.id === latest.id ? latest : item)
    reason.value = pendingReason
    actionError.value = ''
    recoveryMessage.value = '案件已更新到最新版本，未提交的审核理由仍保留，请核对后再次操作。'
  } catch (error) {
    actionError.value = errorMessage(error, '刷新失败，未提交的审核理由仍保留')
  }
}

async function act(action) {
  if (!detail.value || !reasonReady.value || busy.value) return
  busy.value = action
  actionError.value = ''
  recoveryMessage.value = ''
  try {
    await decideContentReview(detail.value.id, {
      action,
      reason: reason.value.trim(),
      expected_version: detail.value.lock_version,
    })
    reason.value = ''
    recoveryMessage.value = '审核决定已保存，责任记录和资源可见性已经同步。'
    await loadQueue({ quiet: true, preserveReason: false })
  } catch (error) {
    if (error?.kind === 'conflict' || error?.status === 409) await recoverConflict()
    else actionError.value = errorMessage(error, '审核决定保存失败，理由和当前结果均已保留')
  } finally {
    busy.value = ''
  }
}

onMounted(() => loadQueue())
</script>

<template>
  <main class="review-page" data-testid="content-review-page">
    <PageHeader
      title="内容审核"
      description="选择一个待办，核对冻结版本、来源和校验结果，再完成返工、批准、发布或下架。"
    >
      <template #actions>
        <button
          type="button"
          class="icon-button"
          aria-label="刷新审核队列"
          title="刷新审核队列"
          :disabled="refreshing || Boolean(busy)"
          @click="loadQueue({ quiet: true })"
        >
          <RefreshCw :size="18" :class="{ spinning: refreshing }" />
        </button>
      </template>
    </PageHeader>

    <RecoveryBanner
      v-if="recoveryMessage"
      :message="recoveryMessage"
      variant="recovery"
      @dismiss="recoveryMessage = ''"
    />

    <TaskState
      v-if="loadError && !items.length"
      state="error"
      title="审核队列暂时不可用"
      :message="loadError"
      action-label="重新加载"
      @action="loadQueue()"
    />

    <section v-else class="review-workspace" aria-label="内容审核工作区">
      <aside class="case-panel" aria-label="审核案件列表">
        <div class="case-toolbar">
          <div>
            <strong>审核队列</strong>
            <span>{{ items.length }} 个案件</span>
          </div>
          <label>
            <span class="sr-only">按状态筛选</span>
            <select v-model="filter" aria-label="按状态筛选" @change="changeFilter">
              <option v-for="option in statusOptions" :key="option.value" :value="option.value">
                {{ option.label }}
              </option>
            </select>
          </label>
        </div>

        <div v-if="loading" class="case-loading" aria-label="正在读取审核队列">
          <span v-for="index in 5" :key="index" />
        </div>
        <div v-else-if="!items.length" class="case-empty">
          <FileCheck2 :size="28" aria-hidden="true" />
          <strong>当前没有审核案件</strong>
          <span>切换筛选条件可查看其他状态。</span>
        </div>
        <div v-else class="case-list">
          <button
            v-for="item in items"
            :key="item.id"
            type="button"
            class="case-row"
            :class="{ active: selectedId === item.id }"
            data-testid="review-case"
            @click="selectCase(item.id)"
          >
            <span class="case-copy">
              <strong>{{ item.artifact.title }}</strong>
              <small>{{ item.artifact.type }} · 版本 {{ item.version.number }}</small>
            </span>
            <span class="case-status">{{ statusLabel(item.status) }}</span>
            <ChevronRight :size="17" aria-hidden="true" />
          </button>
        </div>
      </aside>

      <section class="detail-panel" data-testid="review-detail">
        <TaskState
          v-if="detailLoading && !detail"
          state="loading"
          title="正在读取审核详情"
          message="冻结版本和来源记录正在载入。"
        />
        <TaskState
          v-else-if="actionError && !detail"
          state="error"
          title="案件详情暂时不可用"
          :message="actionError"
          action-label="重新加载"
          @action="loadCase(selectedId, { keepPrevious: false })"
        />
        <div v-else-if="!selectedSummary" class="detail-empty">
          <ShieldCheck :size="34" aria-hidden="true" />
          <h2>从左侧选择一个审核案件</h2>
          <p>案件详情会显示冻结版本、来源定位、校验结论和可执行动作。</p>
        </div>

        <template v-else-if="detail">
          <TaskState
            v-if="loadError"
            state="warning"
            title="刷新失败，当前结果仍可查看"
            :message="loadError"
            action-label="再次刷新"
            @action="loadQueue({ quiet: true })"
          />
          <TaskState
            v-if="actionError"
            state="error"
            title="操作尚未完成"
            :message="actionError"
          />

          <header class="detail-heading">
            <div>
              <span class="status-text">{{ statusLabel(detail.status) }}</span>
              <h2>{{ detail.artifact.title }}</h2>
              <p>
                {{ detail.artifact.type }} · 冻结版本 {{ detail.version.number }} ·
                提交于 {{ formatDate(detail.submitted_at) }}
              </p>
            </div>
            <FileText :size="22" aria-hidden="true" />
          </header>

          <dl class="version-meta">
            <div>
              <dt>内容格式</dt>
              <dd>{{ detail.version.format }}</dd>
            </div>
            <div>
              <dt>版本摘要</dt>
              <dd :title="detail.version.content_hash">{{ detail.version.content_hash.slice(0, 16) }}…</dd>
            </div>
            <div>
              <dt>提交说明</dt>
              <dd>{{ detail.submission_note || '提交人未补充说明' }}</dd>
            </div>
          </dl>

          <section class="review-section preview-section">
            <div class="section-heading">
              <div>
                <h3>版本内容</h3>
                <p>以下内容来自当前冻结版本，审核动作不会改写它。</p>
              </div>
              <BookOpenText :size="19" aria-hidden="true" />
            </div>
            <pre>{{ detail.version.preview }}</pre>
          </section>

          <section class="review-section evidence-section">
            <div class="section-heading">
              <div>
                <h3>来源与检查</h3>
                <p>从结论回到文档、章节和具体位置，确认声明是否有依据。</p>
              </div>
              <span class="evidence-count">
                质量 {{ detail.evidence.summary.quality_passed }}/{{ detail.evidence.summary.quality_total }} ·
                声明 {{ detail.evidence.summary.claims_supported }}/{{ detail.evidence.summary.claims_total }}
              </span>
            </div>

            <div class="evidence-columns">
              <div class="evidence-group">
                <h4>可定位来源</h4>
                <div v-if="detail.evidence.sources?.length" class="source-list">
                  <article v-for="source in detail.evidence.sources" :key="source.id" class="source-row">
                    <div>
                      <strong>{{ source.document_title }}</strong>
                      <span v-if="source.available">
                        {{ source.chapter_title || '未标注章节' }} ·
                        {{ source.page_number ? `第 ${source.page_number} 页` : source.location_label || '位置已记录' }}
                      </span>
                      <span v-else>来源记录当前不可用</span>
                    </div>
                    <blockquote v-if="source.quote">{{ source.quote }}</blockquote>
                  </article>
                </div>
                <p v-else class="inline-empty">当前版本尚无可定位来源，不能据此判断声明已获得支持。</p>
              </div>

              <div class="evidence-group">
                <h4>质量检查</h4>
                <div v-if="detail.evidence.quality_checks?.length" class="check-list">
                  <article v-for="check in detail.evidence.quality_checks" :key="check.id" class="check-row">
                    <div>
                      <strong>{{ check.type }}</strong>
                      <span>{{ statusLabel(check.status) }} · 检查器 {{ check.checker_version }}</span>
                    </div>
                    <span>{{ check.score == null ? '未评分' : `${Math.round(check.score * 100)} 分` }}</span>
                  </article>
                </div>
                <p v-else class="inline-empty">尚无质量检查记录。</p>

                <h4 class="claim-heading">声明支持</h4>
                <div v-if="detail.evidence.claim_checks?.length" class="check-list">
                  <article v-for="claim in detail.evidence.claim_checks" :key="claim.id" class="claim-row">
                    <strong>{{ claim.claim }}</strong>
                    <span>{{ claim.support_status }} · {{ sourceLabel(claim.source_ref_id) }}</span>
                  </article>
                </div>
                <p v-else class="inline-empty">尚无声明校验记录。</p>
              </div>
            </div>
          </section>

          <details class="agent-audit">
            <summary>
              <span>
                <strong>公开校验摘要</strong>
                <small>查看职责、来源、候选、分歧、校验、修订和决定</small>
              </span>
              <ChevronDown :size="18" aria-hidden="true" />
            </summary>
            <div class="audit-list">
              <article v-for="item in detail.agent_audit?.items || []" :key="item.runId" class="audit-row">
                <header>
                  <strong>{{ roleLabels[item.role] || item.role }}</strong>
                  <span>{{ statusLabel(item.status) }}</span>
                </header>
                <dl>
                  <div v-if="item.inputRefs?.length"><dt>来源</dt><dd>{{ item.inputRefs.join('、') }}</dd></div>
                  <div v-if="item.candidateSummary"><dt>候选</dt><dd>{{ item.candidateSummary }}</dd></div>
                  <div v-if="item.disagreement"><dt>分歧</dt><dd>{{ item.disagreement }}</dd></div>
                  <div v-if="item.validation"><dt>校验</dt><dd>{{ item.validation }}</dd></div>
                  <div v-if="item.revision"><dt>修订</dt><dd>{{ item.revision }}</dd></div>
                  <div v-if="item.decisionSummary"><dt>决定</dt><dd>{{ item.decisionSummary }}</dd></div>
                </dl>
              </article>
            </div>
          </details>

          <section v-if="actions.length" class="decision-section" aria-label="审核决定">
            <div class="section-heading">
              <div>
                <h3>作出审核决定</h3>
                <p>说明实际依据。理由会写入不可变责任记录，至少填写 4 个字符。</p>
              </div>
            </div>
            <label class="reason-field">
              <span>审核理由</span>
              <textarea
                v-model="reason"
                rows="3"
                maxlength="2000"
                placeholder="例如：来源可定位，声明支持与质量检查均已核对。"
              />
            </label>
            <div class="decision-actions">
              <button
                v-for="action in actions"
                :key="action.key"
                type="button"
                :class="action.primary ? 'primary-action' : 'secondary-action'"
                :disabled="Boolean(busy) || !reasonReady"
                @click="act(action.key)"
              >
                <component :is="action.icon" :size="17" />
                {{ busy === action.key ? '处理中' : action.label }}
              </button>
            </div>
          </section>

          <details class="decision-history">
            <summary>
              <span>责任记录（{{ detail.decisions.length }}）</span>
              <ChevronDown :size="18" aria-hidden="true" />
            </summary>
            <div class="history-list">
              <article v-for="entry in detail.decisions" :key="entry.id">
                <span>{{ statusLabel(entry.to_status) }}</span>
                <div>
                  <strong>{{ entry.actor_role }} · {{ entry.actor_public_id }}</strong>
                  <p>{{ entry.reason }}</p>
                  <small>{{ formatDate(entry.created_at) }}</small>
                </div>
              </article>
            </div>
          </details>
        </template>
      </section>
    </section>
  </main>
</template>

<style scoped>
.review-page {
  display: grid;
  width: min(100%, 1240px);
  margin: 0 auto;
  gap: 20px;
  color: var(--color-text);
}

.review-workspace {
  display: grid;
  grid-template-columns: 340px minmax(0, 1fr);
  min-height: 680px;
  overflow: hidden;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-panel);
  background: var(--color-surface);
}

.case-panel {
  min-width: 0;
  border-right: 1px solid var(--color-border);
  background: var(--color-surface);
}

.case-toolbar {
  display: flex;
  min-height: 72px;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 14px 16px;
  border-bottom: 1px solid var(--color-border);
}

.case-toolbar > div {
  display: grid;
  gap: 2px;
}

.case-toolbar strong,
.case-toolbar span,
.case-toolbar select {
  font-size: 14px;
}

.case-toolbar span {
  color: var(--color-text-muted);
}

.case-toolbar select {
  min-height: 36px;
  padding: 0 30px 0 10px;
}

.case-list {
  max-height: 720px;
  overflow: auto;
}

.case-row {
  display: grid;
  width: 100%;
  min-height: 76px;
  grid-template-columns: minmax(0, 1fr) auto auto;
  align-items: center;
  gap: 10px;
  padding: 14px 16px;
  color: var(--color-text);
  border: 0;
  border-bottom: 1px solid var(--color-border);
  background: var(--color-surface);
  text-align: left;
  cursor: pointer;
}

.case-row:hover,
.case-row.active {
  background: var(--color-surface-subtle);
}

.case-row.active {
  box-shadow: inset 3px 0 0 var(--color-accent);
}

.case-copy {
  display: grid;
  min-width: 0;
  gap: 4px;
}

.case-copy strong,
.case-copy small {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.case-copy strong {
  font-size: 15px;
}

.case-copy small,
.case-status {
  color: var(--color-text-secondary);
  font-size: 14px;
}

.case-status {
  white-space: nowrap;
}

.case-loading {
  display: grid;
}

.case-loading span {
  height: 76px;
  border-bottom: 1px solid var(--color-border);
  background: var(--color-surface-subtle);
}

.case-empty,
.detail-empty {
  display: grid;
  place-items: center;
  align-content: center;
  gap: 8px;
  min-height: 300px;
  padding: 24px;
  color: var(--color-text-secondary);
  text-align: center;
}

.case-empty strong,
.case-empty span,
.detail-empty p {
  font-size: 14px;
}

.detail-empty h2 {
  margin: 4px 0 0;
  color: var(--color-text);
  font-size: 20px;
}

.detail-empty p {
  margin: 0;
}

.detail-panel {
  min-width: 0;
  padding: 24px;
}

.detail-panel > * + * {
  margin-top: 18px;
}

.detail-heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 20px;
  padding-bottom: 18px;
  border-bottom: 1px solid var(--color-border);
}

.status-text {
  color: var(--color-accent);
  font-size: 14px;
  font-weight: 650;
}

.detail-heading h2 {
  margin: 5px 0 4px;
  font-size: 22px;
  line-height: 1.35;
}

.detail-heading p,
.section-heading p {
  margin: 0;
  color: var(--color-text-secondary);
  font-size: 14px;
  line-height: 1.6;
}

.version-meta {
  display: grid;
  grid-template-columns: 140px 180px minmax(0, 1fr);
  margin: 0;
  padding: 14px 0;
  border-bottom: 1px solid var(--color-border);
}

.version-meta div {
  min-width: 0;
  padding-right: 18px;
}

.version-meta dt,
.version-meta dd {
  margin: 0;
  font-size: 14px;
}

.version-meta dt {
  color: var(--color-text-muted);
}

.version-meta dd {
  overflow-wrap: anywhere;
  margin-top: 4px;
  color: var(--color-text);
}

.review-section {
  padding-top: 2px;
}

.section-heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 18px;
  margin-bottom: 12px;
}

.section-heading h3,
.evidence-group h4 {
  margin: 0;
  color: var(--color-text);
}

.section-heading h3 {
  font-size: 17px;
}

.evidence-group h4 {
  font-size: 15px;
}

.preview-section pre {
  max-height: 260px;
  overflow: auto;
  margin: 0;
  padding: 16px;
  color: var(--color-text);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-control);
  background: var(--color-surface-subtle);
  font: 14px/1.7 ui-monospace, SFMono-Regular, Consolas, monospace;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.evidence-count {
  flex: 0 0 auto;
  color: var(--color-text-secondary);
  font-size: 14px;
}

.evidence-columns {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  border-top: 1px solid var(--color-border);
  border-bottom: 1px solid var(--color-border);
}

.evidence-group {
  min-width: 0;
  padding: 16px 18px 18px 0;
}

.evidence-group + .evidence-group {
  padding-right: 0;
  padding-left: 18px;
  border-left: 1px solid var(--color-border);
}

.source-list,
.check-list {
  margin-top: 10px;
}

.source-row,
.check-row,
.claim-row {
  padding: 11px 0;
  border-top: 1px solid var(--color-border);
}

.source-row:first-child,
.check-row:first-child,
.claim-row:first-child {
  border-top: 0;
}

.source-row > div,
.check-row > div,
.claim-row {
  display: grid;
  gap: 3px;
}

.source-row strong,
.source-row span,
.source-row blockquote,
.check-row strong,
.check-row span,
.claim-row strong,
.claim-row span,
.inline-empty {
  font-size: 14px;
  line-height: 1.55;
}

.source-row span,
.check-row span,
.claim-row span,
.inline-empty {
  color: var(--color-text-secondary);
}

.source-row blockquote {
  margin: 8px 0 0;
  padding-left: 12px;
  color: var(--color-text-secondary);
  border-left: 1px solid var(--color-border-strong);
}

.check-row {
  display: flex;
  justify-content: space-between;
  gap: 12px;
}

.claim-heading {
  margin-top: 18px !important;
}

.inline-empty {
  margin: 10px 0 0;
}

.agent-audit,
.decision-history {
  border-top: 1px solid var(--color-border);
  border-bottom: 1px solid var(--color-border);
}

.agent-audit summary,
.decision-history summary {
  display: flex;
  min-height: 54px;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  cursor: pointer;
  list-style: none;
}

.agent-audit summary::-webkit-details-marker,
.decision-history summary::-webkit-details-marker {
  display: none;
}

.agent-audit summary span {
  display: grid;
  gap: 2px;
}

.agent-audit summary strong,
.agent-audit summary small,
.decision-history summary span {
  font-size: 14px;
}

.agent-audit summary small {
  color: var(--color-text-secondary);
}

.agent-audit[open] summary svg,
.decision-history[open] summary svg {
  transform: rotate(180deg);
}

.audit-list,
.history-list {
  padding-bottom: 14px;
}

.audit-row,
.history-list article {
  padding: 13px 0;
  border-top: 1px solid var(--color-border);
}

.audit-row header,
.history-list article {
  display: flex;
  justify-content: space-between;
  gap: 16px;
}

.audit-row header strong,
.audit-row header span,
.audit-row dt,
.audit-row dd,
.history-list article span,
.history-list strong,
.history-list p,
.history-list small {
  font-size: 14px;
}

.audit-row header span,
.audit-row dt,
.history-list article > span,
.history-list small {
  color: var(--color-text-muted);
}

.audit-row dl {
  display: grid;
  gap: 7px;
  margin: 10px 0 0;
}

.audit-row dl div {
  display: grid;
  grid-template-columns: 52px minmax(0, 1fr);
  gap: 10px;
}

.audit-row dd {
  margin: 0;
  color: var(--color-text-secondary);
  overflow-wrap: anywhere;
}

.decision-section {
  padding: 18px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-panel);
  background: var(--color-surface-subtle);
}

.reason-field {
  display: grid;
  gap: 7px;
}

.reason-field span,
.reason-field textarea,
.decision-actions button {
  font-size: 14px;
}

.reason-field span {
  font-weight: 600;
}

.reason-field textarea {
  width: 100%;
  resize: vertical;
}

.decision-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  margin-top: 12px;
}

.decision-actions button,
.icon-button {
  display: inline-flex;
  min-height: 40px;
  align-items: center;
  justify-content: center;
  gap: 7px;
  border-radius: var(--radius-control);
  font-weight: 650;
  cursor: pointer;
}

.primary-action {
  padding: 0 15px;
  color: #ffffff;
  border: 1px solid var(--color-accent);
  background: var(--color-accent);
}

.secondary-action {
  padding: 0 15px;
  color: var(--color-text-secondary);
  border: 1px solid var(--color-border-strong);
  background: var(--color-surface);
}

.icon-button {
  width: 40px;
  padding: 0;
  color: var(--color-text-secondary);
  border: 1px solid var(--color-border-strong);
  background: var(--color-surface);
}

button:disabled {
  opacity: 0.48;
  cursor: not-allowed;
}

.history-list article > span {
  flex: 0 0 76px;
}

.history-list article > div {
  min-width: 0;
}

.history-list p {
  margin: 4px 0;
  color: var(--color-text-secondary);
}

.spinning {
  animation: spin 800ms linear infinite;
}

.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

@media (max-width: 1280px) {
  .detail-panel {
    padding: 20px;
  }

  .version-meta {
    grid-template-columns: 120px 160px minmax(0, 1fr);
  }
}
</style>
