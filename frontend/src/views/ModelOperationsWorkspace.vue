<script setup>
import { computed, onMounted, ref } from 'vue'
import { BrainCircuit, CircleAlert, Image, KeyRound, RefreshCw, Search, Timer } from '@lucide/vue'
import PageHeader from '../components/PageHeader.vue'
import TaskState from '../components/TaskState.vue'
import { getAdminModels } from '../api/admin'

const data = ref(null)
const loading = ref(true)
const error = ref('')

const slotIcons = {
  generation: BrainCircuit,
  multimodal: Image,
  embedding: Search,
}

const healthMeta = {
  authentication: { label: '认证状态', icon: KeyRound },
  capacity: { label: '容量状态', icon: BrainCircuit },
  rate_limit: { label: '限流状态', icon: CircleAlert },
  timeout: { label: '超时状态', icon: Timer },
}

const healthItems = computed(() => Object.entries(healthMeta).map(([key, meta]) => ({
  key,
  ...meta,
  ...(data.value?.health?.[key] || {}),
})))

function errorMessage(value) {
  const detail = value?.detail
  if (typeof detail === 'string') return detail
  return detail?.message || value?.message || '模型状态加载失败，请稍后重试'
}

function modeLabel(mode) {
  return {
    local: '本地运行',
    external: '外部连接',
    disabled: '未启用',
  }[mode] || '待确认'
}

function authenticationLabel(value) {
  return {
    configured: '认证已配置',
    not_required: '无需认证',
    missing_configuration: '缺少认证配置',
    not_configured: '尚未配置',
  }[value] || '状态待确认'
}

function healthStateLabel(state) {
  return {
    not_observed: '近期正常',
    issue_observed: '需要处理',
    missing_configuration: '缺少配置',
  }[state] || '状态待确认'
}

async function loadModels() {
  loading.value = true
  error.value = ''
  try {
    data.value = await getAdminModels()
  } catch (value) {
    error.value = errorMessage(value)
  } finally {
    loading.value = false
  }
}

onMounted(loadModels)
</script>

<template>
  <main class="admin-page" data-testid="admin-models-page">
    <PageHeader
      eyebrow="管理工作区"
      title="模型配置"
      description="检查生成、多模态与知识检索三个能力是否可用。确认配置状态和近期故障分类后，本页任务即完成。"
    >
      <template #actions>
        <button
          type="button"
          class="icon-button"
          aria-label="刷新模型状态"
          title="刷新模型状态"
          :disabled="loading"
          @click="loadModels"
        >
          <RefreshCw :size="18" :class="{ spinning: loading }" />
        </button>
      </template>
    </PageHeader>

    <TaskState
      v-if="error && !data"
      state="error"
      title="模型状态暂时不可用"
      :message="error"
      action-label="重新加载"
      @action="loadModels"
    />

    <template v-else>
      <section class="task-guide" aria-label="当前任务说明">
        <strong>完成条件</strong>
        <span>三个配置槽位都有明确状态，且认证、容量、限流、超时没有未处理问题。</span>
        <span>本页只读取脱敏状态，不会发起模型调用。</span>
      </section>

      <section class="status-panel" aria-labelledby="configuration-title">
        <div class="section-heading">
          <div>
            <h2 id="configuration-title">能力配置</h2>
            <p>仅显示业务所需的配置结果，不回显连接私值。</p>
          </div>
        </div>

        <div v-if="loading && !data" class="configuration-list" aria-label="正在加载配置">
          <div v-for="index in 3" :key="index" class="configuration-row skeleton-row">
            <span class="skeleton-icon" />
            <span class="skeleton-line" />
          </div>
        </div>
        <div v-else class="configuration-list">
          <div v-for="slot in data?.configuration || []" :key="slot.slot" class="configuration-row">
            <span class="row-icon">
              <component :is="slotIcons[slot.slot] || BrainCircuit" :size="20" />
            </span>
            <div class="row-copy">
              <strong>{{ slot.label }}</strong>
              <span>{{ modeLabel(slot.mode) }}</span>
            </div>
            <span class="state-badge" :class="{ issue: !slot.configured && slot.mode !== 'disabled' }">
              {{ authenticationLabel(slot.authentication) }}
            </span>
          </div>
          <TaskState
            v-if="data && !(data.configuration || []).length"
            state="warning"
            title="没有可检查的模型配置"
            message="请在运行环境中完成至少一个模型能力配置后刷新。"
          />
        </div>
      </section>

      <section class="status-panel" aria-labelledby="health-title">
        <div class="section-heading">
          <div>
            <h2 id="health-title">近期可用性</h2>
            <p>按业务可恢复方式区分问题，未观察到的问题不会被描述为已经验证成功。</p>
          </div>
        </div>
        <div class="health-list">
          <div v-for="item in healthItems" :key="item.key" class="health-row">
            <component :is="item.icon" :size="19" />
            <strong>{{ item.label }}</strong>
            <span>{{ item.message || '近期记录中未发现此类异常' }}</span>
            <span class="state-badge" :class="{ issue: item.state !== 'not_observed' }">
              {{ healthStateLabel(item.state) }}
            </span>
          </div>
        </div>
      </section>

      <TaskState
        v-if="error && data"
        state="warning"
        title="刷新未完成"
        :message="`${error}，已保留上一次状态。`"
        action-label="再次刷新"
        @action="loadModels"
      />
    </template>
  </main>
</template>

<style scoped>
.admin-page {
  display: grid;
  width: min(100%, 1120px);
  margin: 0 auto;
  gap: 20px;
}

.task-guide {
  display: grid;
  grid-template-columns: auto 1fr auto;
  align-items: center;
  gap: 14px;
  padding: 13px 16px;
  color: var(--color-text-secondary);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-panel);
  background: var(--color-surface-subtle);
  font-size: var(--font-size-supporting);
}

.task-guide strong {
  color: var(--color-text);
}

.status-panel {
  border: 1px solid var(--color-border);
  border-radius: var(--radius-panel);
  background: var(--color-surface);
}

.section-heading {
  padding: 18px 20px;
  border-bottom: 1px solid var(--color-border);
}

.section-heading h2,
.section-heading p {
  margin: 0;
}

.section-heading h2 {
  font-size: var(--font-size-section);
  font-weight: 650;
}

.section-heading p {
  margin-top: 4px;
  color: var(--color-text-secondary);
  font-size: var(--font-size-supporting);
}

.configuration-list,
.health-list {
  display: grid;
}

.configuration-row {
  display: grid;
  grid-template-columns: 44px 1fr auto;
  min-height: 76px;
  align-items: center;
  gap: 14px;
  padding: 14px 20px;
  border-bottom: 1px solid var(--color-border);
}

.configuration-row:last-child,
.health-row:last-child {
  border-bottom: 0;
}

.row-icon {
  display: grid;
  width: 40px;
  height: 40px;
  place-items: center;
  color: var(--color-accent);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-control);
  background: var(--color-surface-subtle);
}

.row-copy {
  display: grid;
  gap: 2px;
}

.row-copy span,
.health-row > span:not(.state-badge) {
  color: var(--color-text-secondary);
  font-size: var(--font-size-supporting);
}

.state-badge {
  display: inline-flex;
  min-height: 30px;
  align-items: center;
  padding: 3px 10px;
  color: var(--color-text-secondary);
  border: 1px solid var(--color-border);
  border-radius: 999px;
  background: var(--color-surface-subtle);
  font-size: var(--font-size-supporting);
  white-space: nowrap;
}

.state-badge.issue {
  color: var(--color-warning);
  border-color: #e7d2a8;
  background: var(--color-warning-soft);
}

.health-row {
  display: grid;
  grid-template-columns: 24px 130px 1fr auto;
  min-height: 64px;
  align-items: center;
  gap: 12px;
  padding: 12px 20px;
  border-bottom: 1px solid var(--color-border);
}

.health-row > svg {
  color: var(--color-text-secondary);
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

.icon-button:disabled {
  opacity: 0.48;
  cursor: not-allowed;
}

.skeleton-row {
  pointer-events: none;
}

.skeleton-icon,
.skeleton-line {
  display: block;
  background: var(--color-surface-subtle);
}

.skeleton-icon {
  width: 40px;
  height: 40px;
  border-radius: var(--radius-control);
}

.skeleton-line {
  width: 56%;
  height: 20px;
  border-radius: var(--radius-control);
}

.spinning {
  animation: spin 800ms linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

@media (max-width: 1280px) {
  .task-guide {
    grid-template-columns: auto 1fr;
  }

  .task-guide span:last-child {
    grid-column: 2;
  }
}
</style>
