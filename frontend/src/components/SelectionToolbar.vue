<script setup>
import { computed } from 'vue'
import { LoaderCircle, MessageSquareText, NotebookPen, WandSparkles, X } from '@lucide/vue'

const props = defineProps({
  busyAction: { type: String, default: '' },
  disabled: { type: Boolean, default: false },
  errorMessage: { type: String, default: '' },
  resourceType: { type: String, default: 'handout' },
  selectionType: { type: String, default: 'text' },
})

const emit = defineEmits(['ask', 'note', 'generate', 'clear', 'retry', 'update:resourceType'])
const selectedResource = computed({
  get: () => props.resourceType,
  set: value => emit('update:resourceType', value),
})
</script>

<template>
  <div class="selection-toolbar" role="toolbar" :aria-label="selectionType === 'image' ? '图片选区操作' : '文本选区操作'">
    <div v-if="errorMessage" class="selection-toolbar__error" role="alert">
      <span>{{ errorMessage }}</span>
      <button type="button" class="selection-toolbar__retry" :disabled="Boolean(busyAction)" @click="emit('retry')">重新选择</button>
    </div>
    <button type="button" class="selection-toolbar__action" :disabled="disabled || Boolean(busyAction)" title="针对选区提问" @click="emit('ask')">
      <LoaderCircle v-if="busyAction === 'ask'" :size="16" class="selection-toolbar__spinner" />
      <MessageSquareText v-else :size="16" />
      <span>提问</span>
    </button>
    <button type="button" class="selection-toolbar__icon" :disabled="disabled || Boolean(busyAction)" title="把选区记入笔记" aria-label="把选区记入笔记" @click="emit('note')">
      <NotebookPen :size="17" />
    </button>
    <label class="selection-toolbar__resource">
      <span class="sr-only">生成资源类型</span>
      <select v-model="selectedResource" :disabled="disabled || Boolean(busyAction)">
        <option value="handout">讲义</option>
        <option value="mind_map">思维导图</option>
        <option value="quiz">测验题</option>
        <option value="training_task">实训任务书</option>
      </select>
    </label>
    <button type="button" class="selection-toolbar__icon" :disabled="disabled || Boolean(busyAction)" title="基于选区生成资源" aria-label="基于选区生成资源" @click="emit('generate')">
      <LoaderCircle v-if="busyAction === 'generate'" :size="17" class="selection-toolbar__spinner" />
      <WandSparkles v-else :size="17" />
    </button>
    <span class="selection-toolbar__divider" aria-hidden="true" />
    <button type="button" class="selection-toolbar__icon" :disabled="Boolean(busyAction)" title="取消选区" aria-label="取消选区" @click="emit('clear')">
      <X :size="17" />
    </button>
  </div>
</template>

<style scoped>
.selection-toolbar {
  position: fixed;
  z-index: 80;
  display: flex;
  min-height: 42px;
  align-items: center;
  gap: 3px;
  padding: 4px;
  color: #06141b;
  border: 1px solid #ccd0cf;
  border-radius: 8px;
  background: #ffffff;
  box-shadow: 0 16px 40px rgb(6 20 27 / 16%);
}

.selection-toolbar__error {
  display: grid;
  max-width: 260px;
  gap: 4px;
  padding: 4px 8px;
  color: var(--color-danger);
  border-right: 1px solid #dce2e3;
  font-size: 14px;
  line-height: 1.35;
}

.selection-toolbar__retry {
  min-height: 26px !important;
  justify-self: start;
  padding: 0 7px !important;
  color: var(--color-text) !important;
  background: var(--color-surface-subtle) !important;
}

.selection-toolbar button,
.selection-toolbar select {
  min-height: 34px;
  border: 0;
  border-radius: 6px;
  background: transparent;
  font-size: 14px;
}

.selection-toolbar button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: #344957;
  cursor: pointer;
}

.selection-toolbar button:hover:not(:disabled),
.selection-toolbar select:hover:not(:disabled) {
  color: #06141b;
  background: #edf1f2;
}

.selection-toolbar button:disabled,
.selection-toolbar select:disabled {
  opacity: 0.48;
  cursor: not-allowed;
}

.selection-toolbar__action {
  gap: 7px;
  padding: 0 10px;
  font-weight: 650;
}

.selection-toolbar__icon {
  width: 34px;
  padding: 0;
}

.selection-toolbar__resource select {
  max-width: 106px;
  padding: 0 25px 0 9px;
  color: #344957;
  border: 0;
  cursor: pointer;
}

.selection-toolbar__divider {
  width: 1px;
  height: 22px;
  margin: 0 2px;
  background: #dce2e3;
}

.selection-toolbar__spinner {
  animation: toolbar-spin 800ms linear infinite;
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

@keyframes toolbar-spin {
  to { transform: rotate(360deg); }
}
</style>
