<script setup>
import { AlertTriangle, CheckCircle2, Clock3, Info, LoaderCircle, RotateCcw } from '@lucide/vue'

const props = defineProps({
  state: { type: String, default: 'info' },
  title: { type: String, required: true },
  message: { type: String, default: '' },
  actionLabel: { type: String, default: '' },
})

defineEmits(['action'])

const icons = {
  info: Info,
  loading: LoaderCircle,
  processing: Clock3,
  success: CheckCircle2,
  warning: AlertTriangle,
  error: AlertTriangle,
  recovery: RotateCcw,
}
</script>

<template>
  <div class="task-state" :class="`task-state--${state}`" role="status">
    <component :is="icons[props.state] || Info" :size="18" :class="{ 'task-state__spin': state === 'loading' }" />
    <div class="task-state__copy">
      <strong>{{ title }}</strong>
      <span v-if="message">{{ message }}</span>
    </div>
    <button v-if="actionLabel" type="button" class="task-state__action" @click="$emit('action')">
      {{ actionLabel }}
    </button>
  </div>
</template>

<style scoped>
.task-state {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 12px 14px;
  color: var(--color-text-secondary);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-panel);
  background: var(--color-surface-subtle);
  font-size: 14px;
}

.task-state__copy {
  display: grid;
  flex: 1;
  gap: 2px;
}

.task-state__copy strong {
  color: var(--color-text);
  font-weight: 600;
}

.task-state__action {
  padding: 0;
  color: var(--color-accent);
  border: 0;
  background: transparent;
  font-weight: 600;
  cursor: pointer;
}

.task-state--success {
  color: var(--color-success);
  border-color: #d8cbc1;
  background: var(--color-success-soft);
}

.task-state--warning,
.task-state--processing {
  color: var(--color-warning);
  border-color: #ead9bb;
  background: var(--color-warning-soft);
}

.task-state--error {
  color: var(--color-danger);
  border-color: #e8caca;
  background: var(--color-danger-soft);
}

.task-state--recovery {
  color: var(--color-accent);
  border-color: #d7c8bd;
  background: var(--color-accent-soft);
}

.task-state__spin {
  animation: task-state-spin 900ms linear infinite;
}

@keyframes task-state-spin {
  to { transform: rotate(360deg); }
}
</style>
