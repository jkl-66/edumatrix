<script setup>
import { ArrowRight, CheckCircle2, Clock3, LockKeyhole, Circle } from '@lucide/vue'

defineProps({
  tasks: { type: Array, default: () => [] },
  todayTaskIds: { type: Array, default: () => [] },
  emptyLabel: { type: String, default: '当前没有可展示的任务。' },
})

const emit = defineEmits(['open'])

function taskStatus(task) {
  if (task.status === 'completed' || task.status === '已完成') return 'completed'
  if (task.status === 'in_progress' || task.status === '当前可学' || task.status === 'due') return 'active'
  return 'locked'
}

function statusLabel(task) {
  const status = taskStatus(task)
  if (status === 'completed') return '已完成'
  if (status === 'active') return task.task_kind === 'review' ? '待复习' : '今日可学'
  return '待解锁'
}

function typeLabel(task) {
  const labels = {
    chapter: '章节学习',
    artifact: '学习资源',
    assessment: '测验题',
    interactive: '交互实验',
    review: '复习任务',
    extension: '拓展任务',
  }
  return labels[task.node_type] || task.resource_type || '学习任务'
}

function minutes(task) {
  const range = Array.isArray(task.estimate_minutes) ? task.estimate_minutes : [task.estimate_minutes]
  const values = range.map(Number).filter(Number.isFinite)
  if (!values.length) return '时间待定'
  if (values.length > 1 && values[0] !== values[1]) return `${values[0]}-${values[1]} 分钟`
  return `${values[0]} 分钟`
}

function openTask(task) {
  if (taskStatus(task) === 'locked' || !task.continue_route) return
  emit('open', task)
}

function resourceItems(task) {
  return Array.isArray(task.resources) ? task.resources : []
}
</script>

<template>
  <div class="path-task-list" data-testid="path-task-list">
    <div v-if="!tasks.length" class="path-task-list__empty">{{ emptyLabel }}</div>
    <div v-else class="path-task-list__rows">
      <article
        v-for="task in tasks"
        :key="task.id || task.node_id || task.node_key || task.title"
        class="path-task"
        :class="`path-task--${taskStatus(task)}`"
        :data-testid="`path-task-${task.id || task.node_id || task.node_key}`"
      >
        <div class="path-task__marker" aria-hidden="true">
          <CheckCircle2 v-if="taskStatus(task) === 'completed'" :size="18" />
          <Circle v-else-if="taskStatus(task) === 'active'" :size="18" />
          <LockKeyhole v-else :size="16" />
        </div>
        <div class="path-task__body">
          <div class="path-task__title-row">
            <h3>{{ task.title }}</h3>
            <span v-if="todayTaskIds.includes(task.id || task.node_id || task.node_key)" class="path-task__today">今日必做</span>
            <span v-else-if="task.required === false || task.is_extension" class="path-task__optional">可选</span>
          </div>
          <div class="path-task__meta">
            <span>知识点：{{ task.knowledge_point_title || task.knowledge_point || task.title }}</span>
            <span>{{ typeLabel(task) }}</span>
            <span><Clock3 :size="14" />{{ minutes(task) }}</span>
            <span>{{ statusLabel(task) }}</span>
          </div>
          <p class="path-task__criteria">完成条件：{{ task.completion_criteria || '完成本项学习并留下可追溯证据。' }}</p>
          <div v-if="resourceItems(task).length" class="path-task__resources" data-testid="path-task-resources">
            <div v-for="resource in resourceItems(task)" :key="`${task.id}-${resource.type}`" class="path-task__resource">
              <strong>{{ resource.label }}</strong>
              <span>{{ resource.explanation }} · {{ resource.estimate_minutes }} 分钟</span>
              <span class="path-task__resource-criteria">完成标准：{{ resource.completion_criteria }}</span>
            </div>
          </div>
        </div>
        <button
          type="button"
          class="path-task__action"
          :disabled="taskStatus(task) === 'locked' || !task.continue_route"
          :aria-label="`${taskStatus(task) === 'completed' ? '查看' : '进入'}${task.title}`"
          @click="openTask(task)"
        >
          {{ taskStatus(task) === 'completed' ? '查看' : '进入' }}
          <ArrowRight :size="16" />
        </button>
      </article>
    </div>
  </div>
</template>

<style scoped>
.path-task-list {
  min-width: 0;
}

.path-task-list__rows {
  display: grid;
  gap: 1px;
  overflow: hidden;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-panel);
  background: var(--color-border);
}

.path-task {
  display: grid;
  grid-template-columns: 28px minmax(0, 1fr) auto;
  align-items: start;
  gap: 12px;
  min-width: 0;
  padding: 16px 18px;
  background: var(--color-surface);
}

.path-task--active {
  background: var(--color-surface);
  box-shadow: inset 3px 0 0 var(--color-accent);
}

.path-task--locked {
  background: var(--color-surface);
}

.path-task__marker {
  display: grid;
  width: 28px;
  height: 28px;
  place-items: center;
  color: var(--color-text-muted);
}

.path-task--completed .path-task__marker { color: var(--color-success); }
.path-task--active .path-task__marker { color: var(--color-accent); }

.path-task__body {
  min-width: 0;
}

.path-task__title-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}

.path-task h3 {
  margin: 0;
  color: var(--color-text);
  font-size: 16px;
  font-weight: 650;
  line-height: 1.45;
}

.path-task__today,
.path-task__optional {
  border-radius: 4px;
  padding: 3px 7px;
  font-size: 14px !important;
  font-weight: 650;
  line-height: 1.3;
}

.path-task__today { background: var(--color-accent-soft); color: var(--color-accent); }
.path-task__optional { border: 1px solid var(--color-border); background: var(--color-surface); color: var(--color-text-secondary); }

.path-task__meta {
  display: flex;
  flex-wrap: wrap;
  gap: 14px;
  margin-top: 7px;
  color: var(--color-text-secondary);
  font-size: 14px;
  line-height: 1.45;
}

.path-task__meta span {
  display: inline-flex;
  align-items: center;
  gap: 5px;
}

.path-task__criteria {
  margin: 8px 0 0;
  color: var(--color-text-muted);
  font-size: 14px;
  line-height: 1.55;
}

.path-task__resources {
  display: grid;
  gap: 6px;
  margin-top: 10px;
}

.path-task__resource {
  display: grid;
  grid-template-columns: minmax(92px, auto) minmax(0, 1fr);
  gap: 2px 10px;
  padding: 8px 10px;
  border-left: 2px solid var(--color-accent-soft);
  border-top: 1px solid var(--color-border);
  background: var(--color-surface);
}

.path-task__resource strong,
.path-task__resource span { min-width: 0; color: var(--color-text-secondary); font-size: 14px; line-height: 1.45; }
.path-task__resource strong { color: var(--color-text); }
.path-task__resource-criteria { grid-column: 1 / -1; color: var(--color-text-muted) !important; }

.path-task__action {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  min-height: 36px;
  align-self: center;
  border: 1px solid var(--color-border-strong);
  border-radius: var(--radius-control);
  background: var(--color-surface);
  padding: 0 11px;
  color: var(--color-accent);
  font-size: 14px;
  font-weight: 650;
  white-space: nowrap;
  cursor: pointer;
}

.path-task__action:hover { border-color: var(--color-accent); background: var(--color-accent-soft); }
.path-task__action:disabled { color: var(--color-text-muted); cursor: not-allowed; opacity: .65; }

.path-task-list__empty {
  border: 1px dashed var(--color-border-strong);
  border-radius: var(--radius-panel);
  padding: 32px 20px;
  color: var(--color-text-muted);
  font-size: 15px;
  text-align: center;
}
</style>
