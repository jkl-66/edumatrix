<script setup>
import { AlertTriangle, Info, RotateCcw, X } from '@lucide/vue'

defineProps({
  message: { type: String, required: true },
  variant: { type: String, default: 'info' },
  actionLabel: { type: String, default: '' },
  dismissible: { type: Boolean, default: true },
})

defineEmits(['action', 'dismiss'])
</script>

<template>
  <div class="recovery-banner" :class="`recovery-banner--${variant}`" role="status">
    <component :is="variant === 'recovery' ? RotateCcw : variant === 'warning' ? AlertTriangle : Info" :size="17" />
    <span>{{ message }}</span>
    <button v-if="actionLabel" type="button" class="recovery-banner__action" @click="$emit('action')">{{ actionLabel }}</button>
    <button v-if="dismissible" type="button" class="recovery-banner__dismiss" aria-label="关闭提示" title="关闭" @click="$emit('dismiss')">
      <X :size="16" />
    </button>
  </div>
</template>

<style scoped>
.recovery-banner {
  display: flex;
  min-height: 42px;
  align-items: center;
  gap: 10px;
  padding: 8px 20px;
  color: var(--color-text-secondary);
  border-bottom: 1px solid var(--color-border);
  background: var(--color-surface-subtle);
  font-size: 14px;
}

.recovery-banner span {
  flex: 1;
}

.recovery-banner__action,
.recovery-banner__dismiss {
  color: inherit;
  border: 0;
  background: transparent;
  cursor: pointer;
}

.recovery-banner__action {
  font-weight: 600;
}

.recovery-banner__dismiss {
  display: grid;
  width: 32px;
  height: 32px;
  place-items: center;
}

.recovery-banner--warning {
  color: var(--color-warning);
  background: var(--color-warning-soft);
}

.recovery-banner--recovery {
  color: var(--color-accent);
  background: var(--color-accent-soft);
}
</style>
