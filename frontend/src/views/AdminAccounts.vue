<script setup>
import { computed, onMounted, ref } from 'vue'
import { Check, Pencil, RefreshCw, X } from '@lucide/vue'
import PageHeader from '../components/PageHeader.vue'
import RecoveryBanner from '../components/RecoveryBanner.vue'
import TaskState from '../components/TaskState.vue'
import SearchField from '../components/ui/SearchField.vue'
import { getAdminAccounts, updateAdminAccount } from '../api/admin'

const accounts = ref([])
const loading = ref(true)
const refreshing = ref(false)
const loadError = ref('')
const actionError = ref('')
const recoveryMessage = ref('')
const query = ref('')
const roleFilter = ref('all')
const editingId = ref('')
const draft = ref(null)
const savingId = ref('')

const roleOptions = [
  { value: 'student', label: '学生' },
  { value: 'teacher', label: '教师' },
  { value: 'admin', label: '管理员' },
]

const filteredAccounts = computed(() => {
  const keyword = query.value.trim().toLowerCase()
  return accounts.value.filter((account) => {
    const matchesRole = roleFilter.value === 'all' || account.role === roleFilter.value
    const matchesKeyword = !keyword || [account.username, account.display_name]
      .some((value) => String(value || '').toLowerCase().includes(keyword))
    return matchesRole && matchesKeyword
  })
})

function errorMessage(error, fallback) {
  const detail = error?.detail
  if (typeof detail === 'string') return detail
  return detail?.message || error?.message || fallback
}

function roleLabel(role) {
  return roleOptions.find((item) => item.value === role)?.label || '未知角色'
}

function formatDate(value) {
  if (!value) return '未记录'
  return new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium' }).format(new Date(value))
}

async function loadAccounts({ quiet = false } = {}) {
  if (quiet) refreshing.value = true
  else loading.value = true
  loadError.value = ''
  try {
    const response = await getAdminAccounts()
    accounts.value = response.items || []
  } catch (error) {
    loadError.value = errorMessage(error, '账号列表加载失败，请稍后重试')
  } finally {
    loading.value = false
    refreshing.value = false
  }
}

function beginEdit(account) {
  actionError.value = ''
  recoveryMessage.value = ''
  editingId.value = account.public_id
  draft.value = {
    display_name: account.display_name,
    role: account.role,
    is_active: account.is_active,
  }
}

function cancelEdit() {
  editingId.value = ''
  draft.value = null
  actionError.value = ''
}

async function saveAccount(account) {
  if (!draft.value || savingId.value) return
  savingId.value = account.public_id
  actionError.value = ''
  recoveryMessage.value = ''
  try {
    const updated = await updateAdminAccount(account.public_id, {
      expected_version: account.version,
      display_name: draft.value.display_name.trim(),
      role: draft.value.role,
      is_active: draft.value.is_active,
    })
    accounts.value = accounts.value.map((item) => (
      item.public_id === updated.public_id ? updated : item
    ))
    editingId.value = ''
    draft.value = null
    recoveryMessage.value = `已保存 ${updated.username} 的账号设置。`
  } catch (error) {
    actionError.value = errorMessage(error, '账号保存失败，您的修改已保留')
  } finally {
    savingId.value = ''
  }
}

async function recoverConflict() {
  const pendingId = editingId.value
  const pendingDraft = draft.value ? { ...draft.value } : null
  actionError.value = ''
  refreshing.value = true
  try {
    const response = await getAdminAccounts()
    accounts.value = response.items || []
    const current = accounts.value.find((item) => item.public_id === pendingId)
    if (!current || !pendingDraft) {
      cancelEdit()
      recoveryMessage.value = '账号列表已刷新，请重新选择要编辑的账号。'
      return
    }
    draft.value = pendingDraft
    recoveryMessage.value = '已载入账号的最新版本，您的修改仍保留，请确认后再次保存。'
  } catch (error) {
    actionError.value = errorMessage(error, '刷新失败，您的修改仍保留')
  } finally {
    refreshing.value = false
  }
}

onMounted(() => loadAccounts())
</script>

<template>
  <main class="admin-page" data-testid="admin-accounts-page">
    <PageHeader
      eyebrow="管理工作区"
      title="账号权限"
      description="查找账号并调整显示名、角色或启用状态。一次只编辑一个账号，保存后即完成本页任务。"
    >
      <template #actions>
        <button
          type="button"
          class="icon-button"
          aria-label="刷新账号列表"
          title="刷新账号列表"
          :disabled="refreshing || savingId"
          @click="loadAccounts({ quiet: true })"
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
      v-if="loadError && !accounts.length"
      state="error"
      title="账号列表暂时不可用"
      :message="loadError"
      action-label="重新加载"
      @action="loadAccounts()"
    />

    <section v-else class="account-panel" aria-label="账号列表">
      <div class="account-toolbar">
        <SearchField v-model="query" class="admin-search-field" aria-label="搜索账号" placeholder="搜索账号或显示名" />
        <label class="filter-field">
          <span>角色</span>
          <select v-model="roleFilter" aria-label="按角色筛选">
            <option value="all">全部角色</option>
            <option v-for="item in roleOptions" :key="item.value" :value="item.value">
              {{ item.label }}
            </option>
          </select>
        </label>
        <p class="result-count">{{ filteredAccounts.length }} 个账号</p>
      </div>

      <TaskState
        v-if="actionError"
        state="error"
        title="修改尚未保存"
        :message="actionError"
        action-label="刷新并保留修改"
        @action="recoverConflict"
      />

      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>账号</th>
              <th>显示名</th>
              <th>角色</th>
              <th>状态</th>
              <th>创建时间</th>
              <th class="action-column">操作</th>
            </tr>
          </thead>
          <tbody v-if="loading">
            <tr v-for="index in 4" :key="index" class="skeleton-row">
              <td colspan="6"><span /></td>
            </tr>
          </tbody>
          <tbody v-else>
            <tr v-for="account in filteredAccounts" :key="account.public_id">
              <td>
                <strong>{{ account.username }}</strong>
                <span class="account-id">{{ account.public_id }}</span>
              </td>
              <td>
                <input
                  v-if="editingId === account.public_id"
                  v-model="draft.display_name"
                  class="inline-input"
                  :aria-label="`编辑 ${account.username} 的显示名`"
                  maxlength="64"
                />
                <span v-else>{{ account.display_name || '未设置' }}</span>
              </td>
              <td>
                <select
                  v-if="editingId === account.public_id"
                  v-model="draft.role"
                  class="inline-select"
                  :aria-label="`编辑 ${account.username} 的角色`"
                >
                  <option v-for="item in roleOptions" :key="item.value" :value="item.value">
                    {{ item.label }}
                  </option>
                </select>
                <span v-else class="role-badge">{{ roleLabel(account.role) }}</span>
              </td>
              <td>
                <label v-if="editingId === account.public_id" class="active-control">
                  <input v-model="draft.is_active" type="checkbox" />
                  <span>{{ draft.is_active ? '已启用' : '已停用' }}</span>
                </label>
                <span v-else class="status-label" :class="{ inactive: !account.is_active }">
                  <i aria-hidden="true" />{{ account.is_active ? '已启用' : '已停用' }}
                </span>
              </td>
              <td>{{ formatDate(account.created_at) }}</td>
              <td class="row-actions">
                <template v-if="editingId === account.public_id">
                  <button
                    type="button"
                    class="save-button"
                    :disabled="Boolean(savingId)"
                    :aria-label="`保存 ${account.username}`"
                    @click="saveAccount(account)"
                  >
                    <Check :size="17" />{{ savingId === account.public_id ? '保存中' : '保存' }}
                  </button>
                  <button
                    type="button"
                    class="icon-button"
                    aria-label="取消编辑"
                    title="取消编辑"
                    :disabled="Boolean(savingId)"
                    @click="cancelEdit"
                  >
                    <X :size="17" />
                  </button>
                </template>
                <button
                  v-else
                  type="button"
                  class="edit-button"
                  :disabled="Boolean(editingId)"
                  :aria-label="`编辑 ${account.username}`"
                  @click="beginEdit(account)"
                >
                  <Pencil :size="17" />编辑
                </button>
              </td>
            </tr>
            <tr v-if="!filteredAccounts.length">
              <td colspan="6" class="empty-cell">没有符合当前筛选条件的账号。</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>
  </main>
</template>

<style scoped>
.admin-page {
  display: grid;
  width: min(100%, 1240px);
  margin: 0 auto;
  gap: 20px;
}

.account-panel {
  overflow: hidden;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-panel);
  background: var(--color-surface);
}

.account-toolbar {
  display: grid;
  grid-template-columns: minmax(300px, 1fr) 220px auto;
  align-items: end;
  gap: 16px;
  padding: 18px 20px;
  border-bottom: 1px solid var(--color-border);
}

.search-field {
  display: flex;
  min-height: var(--control-height);
  align-items: center;
  gap: 10px;
  padding: 0 12px;
  color: var(--color-text-muted);
  border: 1px solid var(--color-border-strong);
  border-radius: var(--radius-control);
  background: var(--color-surface);
}

.search-field:focus-within {
  border-color: var(--color-accent);
  box-shadow: 0 0 0 3px rgb(17 33 45 / 14%);
}

.search-field input {
  width: 100%;
  min-height: 36px !important;
  padding: 0 !important;
  border: 0 !important;
  outline: 0;
  box-shadow: none !important;
}

.filter-field {
  display: grid;
  gap: 5px;
  color: var(--color-text-secondary);
  font-size: var(--font-size-supporting);
}

.filter-field select {
  padding: 0 10px;
}

.result-count {
  margin: 0 0 8px;
  color: var(--color-text-secondary);
  font-size: var(--font-size-supporting);
  white-space: nowrap;
}

.table-wrap {
  overflow: auto;
}

table {
  width: 100%;
  min-width: 950px;
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

th:nth-child(1) { width: 20%; }
th:nth-child(2) { width: 19%; }
th:nth-child(3) { width: 14%; }
th:nth-child(4) { width: 14%; }
th:nth-child(5) { width: 15%; }
th:nth-child(6) { width: 18%; }

td strong,
.account-id {
  display: block;
}

td strong {
  overflow-wrap: anywhere;
  line-height: 1.35;
}

.account-id {
  overflow: hidden;
  margin-top: 2px;
  color: var(--color-text-muted);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.inline-input,
.inline-select {
  width: 100%;
  padding: 0 10px;
}

.role-badge,
.status-label {
  display: inline-flex;
  align-items: center;
  gap: 7px;
}

.role-badge {
  min-height: 28px;
  padding: 2px 9px;
  border: 1px solid var(--color-border);
  border-radius: 999px;
  background: var(--color-surface-subtle);
}

.status-label i {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--color-success);
}

.status-label.inactive {
  color: var(--color-text-muted);
}

.status-label.inactive i {
  background: var(--color-border-strong);
}

.active-control {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}

.active-control input {
  width: 17px;
  height: 17px;
  accent-color: var(--color-accent);
}

.row-actions {
  white-space: nowrap;
}

.row-actions,
.edit-button,
.save-button,
.icon-button {
  align-items: center;
}

.row-actions,
.edit-button,
.save-button {
  display: flex;
  gap: 8px;
}

.edit-button,
.save-button,
.icon-button {
  min-height: 36px;
  justify-content: center;
  border-radius: var(--radius-control);
  font-weight: 600;
  cursor: pointer;
}

.edit-button {
  padding: 0 11px;
  color: var(--color-text-secondary);
  border: 1px solid var(--color-border-strong);
  background: var(--color-surface);
}

.save-button {
  padding: 0 12px;
  color: #ffffff;
  border: 1px solid var(--color-accent);
  background: var(--color-accent);
}

.icon-button {
  display: inline-grid;
  width: 40px;
  padding: 0;
  place-items: center;
  color: var(--color-text-secondary);
  border: 1px solid var(--color-border-strong);
  background: var(--color-surface);
}

button:disabled {
  opacity: 0.48;
  cursor: not-allowed;
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
  .account-toolbar {
    grid-template-columns: minmax(260px, 1fr) 200px auto;
  }
}
</style>
