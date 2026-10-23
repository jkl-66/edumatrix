<script setup>
import { computed, onBeforeUnmount, watch } from 'vue'
import { AlertCircle, Check, Clock3, GitCompare, History, LoaderCircle, RotateCcw, X } from '@lucide/vue'

const props = defineProps({
  open: { type: Boolean, default: false },
  title: { type: String, default: '资源版本历史' },
  items: { type: Array, default: () => [] },
  currentVersionId: { type: String, default: '' },
  selectedVersionId: { type: String, default: '' },
  restoringId: { type: String, default: '' },
  error: { type: String, default: '' },
  compareDisabled: { type: Boolean, default: false },
  restoreDisabled: { type: Boolean, default: false },
  compareResult: { type: Object, default: null },
  comparingId: { type: String, default: '' },
})

const emit = defineEmits(['close', 'select', 'restore', 'compare', 'compare-close'])

const sortedItems = computed(() => [...props.items].sort((left, right) => Number(right.number || 0) - Number(left.number || 0)))

function closeOnEscape(event) {
  if (event.key === 'Escape' && props.open) emit('close')
}

watch(() => props.open, (open) => {
  if (open) window.addEventListener('keydown', closeOnEscape)
  else window.removeEventListener('keydown', closeOnEscape)
})

onBeforeUnmount(() => window.removeEventListener('keydown', closeOnEscape))

function formatDate(value) {
  if (!value) return '时间未记录'
  return new Intl.DateTimeFormat('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }).format(new Date(value))
}

function originLabel(item) {
  if (item.revision_origin === 'history_restore') return `从 v${item.restored_from_version_number || '?'} 恢复另存`
  if (item.revision_origin === 'user_edit') return '用户编辑另存'
  return '生成版本'
}
</script>

<template>
  <Teleport to="body">
    <div v-if="open" class="history-layer" data-testid="resource-history-drawer">
      <button type="button" class="history-backdrop" aria-label="关闭版本历史" @click="emit('close')" />
      <aside class="history-drawer" role="dialog" aria-modal="true" :aria-label="title">
        <header class="history-heading">
          <div><span><History :size="16" />版本管理</span><h2>{{ title }}</h2></div>
          <button type="button" class="history-close" title="关闭版本历史" @click="emit('close')"><X :size="18" /></button>
        </header>

        <p class="history-intro">历史版本只读。恢复会创建新的当前版本，不覆盖任何旧内容。</p>
        <div v-if="error" class="history-error" role="alert"><AlertCircle :size="17" /><span>{{ error }}</span></div>

        <section v-if="compareResult" class="history-compare" aria-label="版本比较结果">
          <div class="history-compare-heading">
            <strong>版本比较</strong>
            <button type="button" class="history-compare-close" title="关闭比较结果" @click="emit('compare-close')"><X :size="15" /></button>
          </div>
          <p>{{ compareResult.changed ? `v${compareResult.left?.version} 与 v${compareResult.right?.version} 存在差异。` : '两个版本内容一致。' }}</p>
          <pre v-if="compareResult.diff">{{ compareResult.diff }}</pre>
        </section>

        <div v-if="!sortedItems.length" class="history-empty">
          <History :size="25" /><strong>还没有可查看的历史</strong><span>保存或生成新版本后，版本会在这里保留。</span>
        </div>
        <ol v-else class="history-list">
          <li v-for="item in sortedItems" :key="item.id" :class="{ selected: selectedVersionId === item.id, current: item.id === currentVersionId }">
            <button type="button" class="history-select" @click="emit('select', item.id)">
              <span class="history-version"><strong>v{{ item.number }}</strong><em v-if="item.id === currentVersionId">当前</em></span>
              <span class="history-origin">{{ originLabel(item) }}</span>
              <span class="history-time"><Clock3 :size="14" />{{ formatDate(item.created_at) }}</span>
              <span class="history-source">来源 {{ item.source_status === 'available' ? '可用' : '需检查' }} · {{ item.content_format || '未记录格式' }}</span>
            </button>
            <div class="history-actions">
              <button v-if="item.id !== currentVersionId" type="button" class="history-action" :disabled="compareDisabled" @click="emit('compare', item.id)">
                <LoaderCircle v-if="comparingId === item.id" :size="15" class="history-spin" />
                <GitCompare v-else :size="15" />{{ comparingId === item.id ? '比较中' : '比较' }}
              </button>
              <button v-if="item.id !== currentVersionId" type="button" class="history-action" :disabled="restoreDisabled || Boolean(restoringId)" @click="emit('restore', item.id)">
                <LoaderCircle v-if="restoringId === item.id" :size="15" class="history-spin" />
                <RotateCcw v-else :size="15" />{{ restoringId === item.id ? '恢复中' : '恢复为当前' }}
              </button>
              <span v-else class="history-current"><Check :size="14" />当前版本</span>
            </div>
          </li>
        </ol>
      </aside>
    </div>
  </Teleport>
</template>

<style scoped>
.history-layer { position: fixed; z-index: 80; inset: 0; display: flex; justify-content: flex-end; }
.history-backdrop { position: absolute; inset: 0; border: 0; background: rgba(6, 20, 27, .22); cursor: default; }
.history-drawer { position: relative; display: flex; width: min(420px, 100vw); height: 100%; flex-direction: column; overflow: hidden; border-left: 1px solid #ccd0cf; background: #fff; color: #06141b; box-shadow: -10px 0 28px rgba(6, 20, 27, .12); }
.history-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 14px; padding: 20px; border-bottom: 1px solid #dfe4e5; }
.history-heading span { display: flex; align-items: center; gap: 6px; color: #60727c; font-size: 14px; }
.history-heading h2 { margin: 5px 0 0; font-size: 20px; line-height: 1.35; }
.history-close { display: grid; width: 36px; height: 36px; place-items: center; border: 1px solid #ccd0cf; border-radius: 8px; background: #fff; color: #11212d; cursor: pointer; }
.history-intro { margin: 0; padding: 14px 20px; border-bottom: 1px solid #eef2f2; color: #4a5c6a; font-size: 14px; line-height: 1.6; }
.history-error { display: flex; gap: 8px; margin: 14px 20px 0; padding: 10px; border: 1px solid #d8aaa5; border-radius: 8px; background: #fff5f3; color: #8b3d35; font-size: 14px; line-height: 1.5; }
.history-compare { margin: 14px 20px 0; padding: 12px; border: 1px solid #ccd0cf; border-radius: 8px; background: #f7f9f9; }
.history-compare-heading { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.history-compare-heading strong { font-size: 15px; }
.history-compare-close { display: grid; width: 28px; height: 28px; place-items: center; border: 1px solid #ccd0cf; border-radius: 6px; background: #fff; color: #11212d; cursor: pointer; }
.history-compare p { margin: 8px 0; color: #4a5c6a; font-size: 14px; line-height: 1.5; }
.history-compare pre { max-height: 180px; margin: 0; overflow: auto; padding: 10px; border: 1px solid #dfe4e5; background: #fff; color: #253745; font: 14px/1.5 Consolas, monospace; white-space: pre-wrap; }
.history-list { min-height: 0; margin: 0; padding: 14px 20px 24px; overflow: auto; list-style: none; }
.history-list li { margin-bottom: 9px; border: 1px solid #dfe4e5; border-radius: 8px; background: #fff; }
.history-list li.selected { border-color: #11212d; box-shadow: inset 0 0 0 1px #11212d; }
.history-select { display: grid; width: 100%; gap: 5px; padding: 13px; border: 0; background: transparent; color: #06141b; text-align: left; cursor: pointer; }
.history-version { display: flex; align-items: center; gap: 7px; }
.history-version strong { font-size: 16px; }
.history-version em { padding: 2px 6px; border-radius: 5px; background: #11212d; color: #fff; font-size: 14px; font-style: normal; }
.history-origin, .history-source, .history-time { display: flex; align-items: center; gap: 5px; color: #60727c; font-size: 14px; line-height: 1.45; }
.history-actions { display: flex; min-height: 42px; align-items: center; gap: 7px; padding: 0 13px 12px; }
.history-action, .history-current { display: inline-flex; min-height: 32px; align-items: center; gap: 5px; border: 1px solid #ccd0cf; border-radius: 7px; padding: 0 8px; background: #fff; color: #11212d; font-size: 14px; cursor: pointer; }
.history-action:disabled { cursor: default; opacity: .48; }
.history-current { border-color: transparent; color: #60727c; cursor: default; }
.history-empty { display: grid; min-height: 260px; place-content: center; justify-items: center; gap: 9px; padding: 24px; color: #60727c; text-align: center; }
.history-empty strong { color: #06141b; font-size: 16px; }
.history-empty span { max-width: 28ch; font-size: 14px; line-height: 1.6; }
.history-spin { animation: history-spin .8s linear infinite; }
.history-close:focus-visible, .history-select:focus-visible, .history-action:focus-visible { outline: 2px solid #11212d; outline-offset: 2px; }
@keyframes history-spin { to { transform: rotate(360deg); } }
</style>
