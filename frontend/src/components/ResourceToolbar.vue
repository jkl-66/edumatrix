<script setup>
import { displayLabel } from '../utils/learningCopy.js'
import {
  ArrowLeft, History, LoaderCircle, NotebookPen, Pencil, RefreshCw, Save, X,
} from '@lucide/vue'

defineProps({
  title: { type: String, default: '' },
  backLabel: { type: String, default: '返回资源中心' },
  typeLabel: { type: String, default: '学习资源' },
  versionLabel: { type: String, default: '版本未记录' },
  statusLabel: { type: String, default: '' },
  historyCount: { type: Number, default: 0 },
  canEdit: { type: Boolean, default: false },
  editLabel: { type: String, default: '编辑当前版本' },
  editing: { type: Boolean, default: false },
  saving: { type: Boolean, default: false },
  saveDisabled: { type: Boolean, default: false },
  reloadDisabled: { type: Boolean, default: false },
  loading: { type: Boolean, default: false },
  historyDisabled: { type: Boolean, default: false },
  showNote: { type: Boolean, default: false },
  noteDisabled: { type: Boolean, default: false },
  noteBusy: { type: Boolean, default: false },
})

defineEmits(['back', 'history', 'edit', 'save', 'cancel', 'reload', 'note'])
function readableTitle(title) {
  return String(title || '').replace(/([·｜|]\s*)(handout|mind_map|quiz|training_task|code_sandbox|interactive_model|feynman|video|deck)\b/g,
    (_, separator, type) => separator + displayLabel(type, '学习资源'))
}
</script>

<template>
  <header class="resource-toolbar" data-testid="resource-toolbar">
    <button type="button" class="toolbar-back" :title="backLabel" @click="$emit('back')">
      <ArrowLeft :size="18" />
    </button>
    <div class="toolbar-identity">
      <span v-if="typeLabel" class="toolbar-type">{{ typeLabel }}</span>
      <h1>{{ readableTitle(title) }}</h1>
      <p v-if="versionLabel || statusLabel">{{ versionLabel }}<template v-if="versionLabel && statusLabel"> · </template>{{ statusLabel }}</p>
    </div>
    <div class="toolbar-actions">
      <button
        v-if="showNote"
        type="button"
        aria-label="保存到笔记本"
        class="toolbar-button"
        :disabled="noteDisabled || noteBusy"
        @click="$emit('note')"
      >
        <LoaderCircle v-if="noteBusy" :size="16" class="toolbar-spin" />
        <NotebookPen v-else :size="16" />
        <span>{{ noteBusy ? '正在保存' : '保存到笔记本' }}</span>
      </button>
      <button
        type="button"
        class="toolbar-button"
        aria-label="版本历史"
        :disabled="historyDisabled"
        @click="$emit('history')"
      >
        <History :size="16" />
        <span>版本历史</span>
        <strong v-if="historyCount > 1">{{ historyCount }}</strong>
      </button>
      <template v-if="editing">
        <button type="button" class="toolbar-button" :disabled="saving" @click="$emit('cancel')">
          <X :size="16" />取消
        </button>
        <button type="button" class="toolbar-primary" :disabled="saving || saveDisabled" @click="$emit('save')">
          <LoaderCircle v-if="saving" :size="16" class="toolbar-spin" />
          <Save v-else :size="16" />
          {{ saving ? '保存中' : '保存为新版本' }}
        </button>
      </template>
      <button v-else-if="canEdit" type="button" class="toolbar-primary" :disabled="loading" @click="$emit('edit')">
        <Pencil :size="16" />{{ editLabel }}
      </button>
      <button type="button" class="toolbar-icon" title="重新加载资源" :disabled="loading || reloadDisabled" @click="$emit('reload')">
        <RefreshCw :size="17" :class="{ 'toolbar-spin': loading }" />
        <span class="sr-only">重新加载资源</span>
      </button>
    </div>
  </header>
</template>

<style scoped>
.resource-toolbar { display: flex; min-width: 0; align-items: center; gap: 12px; padding: 12px 14px; border: 1px solid var(--color-border-strong); border-radius: 8px; background: var(--color-surface); color: var(--color-text); }
.toolbar-back, .toolbar-icon { display: grid; width: 38px; height: 38px; flex: 0 0 38px; place-items: center; border: 1px solid var(--color-border-strong); border-radius: 8px; background: var(--color-surface); color: var(--color-accent); cursor: pointer; }
.toolbar-identity { min-width: 0; flex: 1; }
.toolbar-type, .toolbar-identity p { display: block; color: var(--color-text-secondary); font-size: 14px; line-height: 1.35; }
.toolbar-identity h1 { margin: 3px 0; overflow: hidden; color: var(--color-text); font-size: 20px; line-height: 1.3; text-overflow: ellipsis; white-space: nowrap; }
.toolbar-identity p { margin: 0; }
.toolbar-actions { display: flex; flex: 0 0 auto; align-items: center; gap: 7px; }
.toolbar-button, .toolbar-primary { display: inline-flex; min-height: 38px; align-items: center; justify-content: center; gap: 6px; border: 1px solid var(--color-border-strong); border-radius: 8px; padding: 0 10px; background: var(--color-surface); color: var(--color-accent); font-size: 14px; cursor: pointer; white-space: nowrap; }
.toolbar-button strong { min-width: 18px; color: var(--color-text-secondary); font-size: 14px; font-variant-numeric: tabular-nums; }
.toolbar-primary { border-color: var(--color-accent); background: var(--color-accent); color: #fff; font-weight: 650; }
.toolbar-button:disabled, .toolbar-primary:disabled, .toolbar-icon:disabled, .toolbar-back:disabled { cursor: default; opacity: .5; }
.toolbar-button:focus-visible, .toolbar-primary:focus-visible, .toolbar-icon:focus-visible, .toolbar-back:focus-visible { outline: 2px solid var(--color-accent); outline-offset: 2px; }
.toolbar-spin { animation: toolbar-spin .8s linear infinite; }
.sr-only { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0, 0, 0, 0); white-space: nowrap; }
@keyframes toolbar-spin { to { transform: rotate(360deg); } }
@media (max-width: 1120px) { .toolbar-identity h1 { font-size: 18px; } .toolbar-button span { display: none; } }
</style>
