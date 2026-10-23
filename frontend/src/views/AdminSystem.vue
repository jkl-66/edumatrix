<script setup>
import { computed, onMounted, ref } from 'vue'
import { Ban, RefreshCw, RotateCcw } from '@lucide/vue'
import PageHeader from '../components/PageHeader.vue'
import RecoveryBanner from '../components/RecoveryBanner.vue'
import TaskState from '../components/TaskState.vue'
import { cancelAdminTask, getAdminSystem, retryAdminTask } from '../api/admin'

const data = ref(null)
const loading = ref(true)
const error = ref('')
const actionError = ref('')
const recoveryMessage = ref('')
const busyTaskId = ref('')
const statusFilter = ref('all')

const statusOptions = [
  { value: 'all', label: '全部任务' },
  { value: 'failed', label: '需要恢复' },
  { value: 'active', label: '进行中' },
  { value: 'completed', label: '已完成' },
  { value: 'cancelled', label: '已取消' },
]

const statusLabels = {
  queued: '等待处理',
  running: '正在处理',
  completed: '已完成',
  failed: '处理失败',
  cancelled: '已取消',
}

const auditActionLabels = {
  'admin.account.update': '账号权限变更',
  'admin.task.retry': '重试失败任务',
  'admin.task.cancel': '取消运行任务',
  'teacher.intervention.publish': '发布教学干预',
  'content_review.submit': '提交内容审核',
  'content_review.approve': '批准内容',
  'content_review.request_changes': '退回内容',
  'content_review.publish': '发布内容',
  'content_review.withdraw': '下架内容',
  'assessment.exam.create': '创建测评',
  'assessment.exam.transition': '更新测评状态',
  'assessment.question.create': '创建测评题目',
  'plan.draft_created': '生成路径草稿',
  'plan.confirmed': '确认学习路径',
}

const auditObjectLabels = {
  user: '账号',
  generation_task: '资源任务',
  content_review_case: '审核内容',
  assessment_exam: '测评',
  assessment_question: '测评题目',
  plan_draft: '学习路径方案',
}

const auditSummaryLabels = {
  active: '启用状态',
  changedFields: '变更字段',
  courseId: '课程',
  created: '是否新建',
  existingResult: '已有结果',
  failureCategory: '失败类型',
  learnerPublicId: '学生',
  pathId: '学习路径',
  role: '角色',
  sameTaskReused: '复用原任务',
  state: '发布状态',
  status: '状态',
}

const auditValueLabels = {
  approved: '已批准',
  failed: '处理失败',
  not_published: '未发布',
  pending: '待审核',
  published: '已发布',
  queued: '等待处理',
  timeout: '执行超时',
}

const filteredTasks = computed(() => {
  const tasks = data.value?.tasks || []
  if (statusFilter.value === 'all') return tasks
  if (statusFilter.value === 'active') {
    return tasks.filter((task) => ['queued', 'running'].includes(task.status))
  }
  return tasks.filter((task) => task.status === statusFilter.value)
})

function errorMessage(value, fallback) {
  const detail = value?.detail
  if (typeof detail === 'string') return detail
  return detail?.message || value?.message || fallback
}

function formatDate(value) {
  if (!value) return '未记录'
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(value))
}

function summaryText(value) {
  const entries = Object.entries(value || {})
  if (!entries.length) return '未记录可公开的变更字段'
  return entries.map(([key, item]) => {
    const renderValue = (entry) => {
      if (typeof entry === 'boolean') return entry ? '是' : '否'
      return auditValueLabels[entry] || String(entry)
    }
    const rendered = Array.isArray(item) ? item.map(renderValue).join('、') : renderValue(item)
    return `${auditSummaryLabels[key] || key}：${rendered}`
  }).join('；')
}

function auditObjectText(audit) {
  return `${auditObjectLabels[audit.objectType] || audit.objectType} / ${audit.objectId}`
}

function replaceTask(task) {
  if (!data.value) return
  data.value.tasks = data.value.tasks.map((item) => item.id === task.id ? task : item)
  const counts = { queued: 0, running: 0, completed: 0, failed: 0, cancelled: 0 }
  data.value.tasks.forEach((item) => {
    if (Object.prototype.hasOwnProperty.call(counts, item.status)) counts[item.status] += 1
  })
  data.value.status_counts = counts
}

async function loadSystem() {
  loading.value = true
  error.value = ''
  try {
    data.value = await getAdminSystem()
  } catch (value) {
    error.value = errorMessage(value, '系统任务加载失败，请稍后重试')
  } finally {
    loading.value = false
  }
}

async function retryTask(task) {
  if (busyTaskId.value) return
  busyTaskId.value = task.id
  actionError.value = ''
  recoveryMessage.value = ''
  try {
    const response = await retryAdminTask(task.id)
    replaceTask(response.task)
    recoveryMessage.value = response.task.has_existing_result
      ? '已从失败步骤重新排队，已有结果保持可用。'
      : '已从失败步骤重新排队，可稍后刷新查看进度。'
  } catch (value) {
    actionError.value = errorMessage(value, '任务重试失败，已有结果未受影响')
  } finally {
    busyTaskId.value = ''
  }
}

async function cancelTask(task) {
  if (busyTaskId.value) return
  busyTaskId.value = task.id
  actionError.value = ''
  recoveryMessage.value = ''
  try {
    const response = await cancelAdminTask(task.id)
    replaceTask(response.task)
    recoveryMessage.value = response.task.has_existing_result
      ? '任务已取消，已有结果保持可用。'
      : '任务已取消。'
  } catch (value) {
    actionError.value = errorMessage(value, '任务取消失败，当前状态已保留')
  } finally {
    busyTaskId.value = ''
  }
}

onMounted(loadSystem)
</script>

<template>
  <main class="admin-page" data-testid="admin-system-page">
    <PageHeader
      eyebrow="管理工作区"
      title="系统状态"
      description="查看学习资源任务是否正常；失败任务只重试失败步骤，运行中的任务可以取消，已有结果始终保留。"
    >
      <template #actions>
        <button
          type="button"
          class="icon-button"
          aria-label="刷新系统任务"
          title="刷新系统任务"
          :disabled="loading || Boolean(busyTaskId)"
          @click="loadSystem"
        >
          <RefreshCw :size="18" :class="{ spinning: loading }" />
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
      v-if="error && !data"
      state="error"
      title="系统任务暂时不可用"
      :message="error"
      action-label="重新加载"
      @action="loadSystem"
    />

    <template v-else>
      <section class="status-strip" aria-label="任务状态汇总">
        <div v-for="status in ['queued', 'running', 'completed', 'failed', 'cancelled']" :key="status">
          <strong>{{ data?.status_counts?.[status] || 0 }}</strong>
          <span>{{ statusLabels[status] }}</span>
        </div>
      </section>

      <details class="audit-panel">
        <summary>
          <span>最近后台操作</span>
          <span>{{ data?.recent_audits?.length || 0 }} 条</span>
        </summary>
        <div class="table-wrap audit-table-wrap">
          <table class="audit-table">
            <thead>
              <tr>
                <th>操作</th>
                <th>操作者</th>
                <th>对象</th>
                <th>变更摘要</th>
                <th>结果</th>
                <th>时间</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="audit in data?.recent_audits || []" :key="audit.id">
                <td>{{ auditActionLabels[audit.action] || audit.action }}</td>
                <td>{{ audit.actorPublicId || '系统' }}</td>
                <td>{{ auditObjectText(audit) }}</td>
                <td class="audit-summary">
                  <span>之前：{{ summaryText(audit.beforeSummary) }}</span>
                  <span>之后：{{ summaryText(audit.afterSummary) }}</span>
                </td>
                <td>{{ audit.outcome === 'success' ? '成功' : '失败' }}</td>
                <td>{{ formatDate(audit.createdAt) }}</td>
              </tr>
              <tr v-if="!data?.recent_audits?.length">
                <td colspan="6" class="empty-cell">暂无后台操作记录。</td>
              </tr>
            </tbody>
          </table>
        </div>
      </details>

      <TaskState
        v-if="actionError"
        state="error"
        title="操作未完成"
        :message="actionError"
        action-label="刷新状态"
        @action="loadSystem"
      />

      <section class="task-panel" aria-labelledby="system-task-title">
        <div class="task-toolbar">
          <div>
            <h2 id="system-task-title">资源任务</h2>
            <p>最近状态就是当前恢复位置；失败不会被显示为完成。</p>
          </div>
          <label>
            <span>任务范围</span>
            <select v-model="statusFilter" aria-label="筛选系统任务">
              <option v-for="item in statusOptions" :key="item.value" :value="item.value">
                {{ item.label }}
              </option>
            </select>
          </label>
        </div>

        <div class="table-wrap">
          <table>
            <thead>
              <tr>
                <th>任务</th>
                <th>状态</th>
                <th>进度</th>
                <th>已有结果</th>
                <th>最近状态</th>
                <th class="action-column">恢复操作</th>
              </tr>
            </thead>
            <tbody v-if="loading && !data">
              <tr v-for="index in 4" :key="index" class="skeleton-row">
                <td colspan="6"><span /></td>
              </tr>
            </tbody>
            <tbody v-else>
              <tr v-for="task in filteredTasks" :key="task.id">
                <td>
                  <strong>{{ task.title }}</strong>
                  <span v-if="task.failure_message" class="failure-message">{{ task.failure_message }}</span>
                </td>
                <td>
                  <span class="status-badge" :class="`status-${task.status}`">
                    {{ statusLabels[task.status] || '未知状态' }}
                  </span>
                </td>
                <td>
                  <div class="progress-cell">
                    <progress :value="task.progress_percent" max="100" />
                    <span>{{ task.progress_percent }}%</span>
                  </div>
                </td>
                <td>{{ task.has_existing_result ? '可继续使用' : '尚未生成' }}</td>
                <td>{{ formatDate(task.updated_at) }}</td>
                <td class="row-actions">
                  <button
                    v-if="task.can_retry"
                    type="button"
                    class="action-button"
                    :disabled="Boolean(busyTaskId)"
                    @click="retryTask(task)"
                  >
                    <RotateCcw :size="17" />{{ busyTaskId === task.id ? '重试中' : '重试失败步骤' }}
                  </button>
                  <button
                    v-else-if="task.can_cancel"
                    type="button"
                    class="action-button"
                    :disabled="Boolean(busyTaskId)"
                    @click="cancelTask(task)"
                  >
                    <Ban :size="17" />{{ busyTaskId === task.id ? '取消中' : '取消任务' }}
                  </button>
                  <span v-else class="no-action">无需操作</span>
                </td>
              </tr>
              <tr v-if="!filteredTasks.length">
                <td colspan="6" class="empty-cell">当前范围没有任务。</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <TaskState
        v-if="error && data"
        state="warning"
        title="刷新未完成"
        :message="`${error}，已保留上一次任务状态。`"
        action-label="再次刷新"
        @action="loadSystem"
      />
    </template>
  </main>
</template>

<style scoped>
.admin-page {
  display: grid;
  width: min(100%, 1240px);
  margin: 0 auto;
  gap: 20px;
}

.status-strip {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  overflow: hidden;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-panel);
  background: var(--color-surface);
}

.status-strip div {
  display: flex;
  min-height: 70px;
  align-items: baseline;
  gap: 9px;
  padding: 18px;
  border-right: 1px solid var(--color-border);
}

.status-strip div:last-child {
  border-right: 0;
}

.status-strip strong {
  font-size: 22px;
  font-weight: 650;
}

.status-strip span {
  color: var(--color-text-secondary);
  font-size: var(--font-size-supporting);
}

.task-panel {
  overflow: hidden;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-panel);
  background: var(--color-surface);
}

.audit-panel {
  overflow: hidden;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-panel);
  background: var(--color-surface);
}

.audit-panel > summary {
  display: flex;
  min-height: 54px;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 0 20px;
  color: var(--color-text);
  font-size: var(--font-size-supporting);
  font-weight: 650;
  cursor: pointer;
}

.audit-panel[open] > summary {
  border-bottom: 1px solid var(--color-border);
}

.audit-table {
  min-width: 1160px;
}

.audit-table th:nth-child(1) { width: 15%; }
.audit-table th:nth-child(2) { width: 16%; }
.audit-table th:nth-child(3) { width: 19%; }
.audit-table th:nth-child(4) { width: 28%; }
.audit-table th:nth-child(5) { width: 8%; }
.audit-table th:nth-child(6) { width: 14%; }

.audit-table td {
  overflow-wrap: anywhere;
  word-break: break-word;
  vertical-align: top;
}

.audit-table td:nth-child(5),
.audit-table td:nth-child(6) {
  white-space: nowrap;
}

.audit-summary span {
  display: block;
  overflow-wrap: anywhere;
}

.audit-summary span + span {
  margin-top: 4px;
}

.task-toolbar {
  display: flex;
  align-items: end;
  justify-content: space-between;
  gap: 20px;
  padding: 18px 20px;
  border-bottom: 1px solid var(--color-border);
}

.task-toolbar h2,
.task-toolbar p {
  margin: 0;
}

.task-toolbar h2 {
  font-size: var(--font-size-section);
  font-weight: 650;
}

.task-toolbar p {
  margin-top: 4px;
  color: var(--color-text-secondary);
  font-size: var(--font-size-supporting);
}

.task-toolbar label {
  display: grid;
  min-width: 190px;
  gap: 5px;
  color: var(--color-text-secondary);
  font-size: var(--font-size-supporting);
}

.task-toolbar select {
  padding: 0 10px;
}

.table-wrap {
  overflow: auto;
}

table {
  width: 100%;
  min-width: 1050px;
  border-collapse: collapse;
  table-layout: fixed;
}

th,
td {
  padding: 13px 16px;
  border-bottom: 1px solid var(--color-border);
  text-align: left;
  vertical-align: middle;
  font-size: var(--font-size-supporting);
}

th {
  color: var(--color-text-secondary);
  background: var(--color-surface-subtle);
  font-weight: 600;
}

tbody tr:last-child td {
  border-bottom: 0;
}

th:nth-child(1) { width: 25%; }
th:nth-child(2) { width: 13%; }
th:nth-child(3) { width: 15%; }
th:nth-child(4) { width: 15%; }
th:nth-child(5) { width: 15%; }
th:nth-child(6) { width: 17%; }

td strong,
.failure-message {
  display: block;
}

.failure-message {
  margin-top: 3px;
  color: var(--color-danger);
}

.status-badge {
  display: inline-flex;
  min-height: 28px;
  align-items: center;
  padding: 2px 9px;
  color: var(--color-text-secondary);
  border: 1px solid var(--color-border);
  border-radius: 999px;
  background: var(--color-surface-subtle);
  white-space: nowrap;
}

.status-failed {
  color: var(--color-danger);
  border-color: #e8caca;
  background: var(--color-danger-soft);
}

.status-running,
.status-queued {
  color: var(--color-warning);
  border-color: #e7d2a8;
  background: var(--color-warning-soft);
}

.progress-cell {
  display: grid;
  grid-template-columns: 1fr auto;
  align-items: center;
  gap: 8px;
}

.progress-cell progress {
  width: 100%;
  height: 8px;
  overflow: hidden;
  border: 0;
  border-radius: 999px;
  background: var(--color-surface-muted);
}

.progress-cell progress::-webkit-progress-bar {
  background: var(--color-surface-muted);
}

.progress-cell progress::-webkit-progress-value {
  background: var(--color-accent);
}

.row-actions {
  white-space: nowrap;
}

.action-button {
  display: inline-flex;
  min-height: 36px;
  align-items: center;
  justify-content: center;
  gap: 7px;
  padding: 0 11px;
  color: var(--color-text);
  border: 1px solid var(--color-border-strong);
  border-radius: var(--radius-control);
  background: var(--color-surface);
  font-weight: 600;
  cursor: pointer;
}

.action-button:disabled,
.icon-button:disabled {
  opacity: 0.48;
  cursor: not-allowed;
}

.no-action {
  color: var(--color-text-muted);
}

.icon-button {
  display: inline-grid;
  width: 40px;
  min-height: 40px;
  padding: 0;
  place-items: center;
  color: var(--color-text-secondary);
  border: 1px solid var(--color-border-strong);
  border-radius: var(--radius-control);
  background: var(--color-surface);
  cursor: pointer;
}

.empty-cell {
  height: 160px;
  color: var(--color-text-secondary);
  text-align: center;
}

.skeleton-row span {
  display: block;
  width: 100%;
  height: 24px;
  border-radius: var(--radius-control);
  background: var(--color-surface-subtle);
}

.spinning {
  animation: spin 800ms linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

@media (max-width: 1280px) {
  .status-strip div {
    padding: 15px;
  }
}
</style>
