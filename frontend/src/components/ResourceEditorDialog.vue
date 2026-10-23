<script setup>
import { computed } from 'vue'
import { AlertCircle, Save, X } from '@lucide/vue'

const props = defineProps({
  open: { type: Boolean, default: false },
  title: { type: String, default: '编辑资源' },
  versionLabel: { type: String, default: '' },
  content: { type: String, default: '' },
  contentFormat: { type: String, default: 'markdown' },
  saving: { type: Boolean, default: false },
  error: { type: String, default: '' },
})

const emit = defineEmits(['close', 'update:content', 'save'])
const lineCount = computed(() => props.content.split('\n').length)
</script>

<template>
  <div v-if="open" class="editor-layer">
    <button type="button" class="editor-backdrop" aria-label="关闭资源编辑" @click="emit('close')" />
    <section class="editor-dialog" role="dialog" aria-modal="true" :aria-labelledby="`${title}-editor-title`">
      <header class="editor-heading">
        <div><span>从 {{ versionLabel }} 开始编辑</span><h2 :id="`${title}-editor-title`">{{ title }}</h2></div>
        <button type="button" class="editor-close" title="关闭资源编辑" @click="emit('close')"><X :size="18" /></button>
      </header>
      <p class="editor-notice">保存会创建新的当前版本；原版本、来源引用和历史内容不会被覆盖。服务器会按资源类型校验结构化内容。</p>
      <div v-if="error" class="editor-error" role="alert"><AlertCircle :size="17" />{{ error }}</div>
      <label class="editor-field">
        <span>资源内容 · {{ contentFormat }} · {{ lineCount }} 行</span>
        <textarea :value="content" spellcheck="false" @input="emit('update:content', $event.target.value)" />
      </label>
      <footer class="editor-actions">
        <button type="button" class="editor-secondary" :disabled="saving" @click="emit('close')">取消</button>
        <button type="button" class="editor-primary" :disabled="saving || !content.trim()" @click="emit('save')"><Save :size="16" />{{ saving ? '保存中' : '保存为新版本' }}</button>
      </footer>
    </section>
  </div>
</template>

<style scoped>
.editor-layer { position: fixed; z-index: 95; inset: 0; display: grid; place-items: center; padding: 24px; }
.editor-backdrop { position: absolute; inset: 0; border: 0; background: rgba(6,20,27,.24); cursor: default; }
.editor-dialog { position: relative; display: flex; width: min(860px,100%); max-height: min(760px,calc(100vh - 48px)); flex-direction: column; overflow: hidden; border: 1px solid #ccd0cf; border-radius: 8px; background: #fff; color: #06141b; box-shadow: 0 16px 36px rgba(6,20,27,.16); }
.editor-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 14px; padding: 20px; border-bottom: 1px solid #dfe4e5; }
.editor-heading span { color: #60727c; font-size: 14px; }
.editor-heading h2 { margin: 5px 0 0; font-size: 20px; line-height: 1.35; overflow-wrap: anywhere; }
.editor-close { display: grid; width: 36px; height: 36px; place-items: center; border: 1px solid #ccd0cf; border-radius: 8px; background: #fff; color: #11212d; cursor: pointer; }
.editor-notice { margin: 0; padding: 13px 20px; border-bottom: 1px solid #eef2f2; color: #4a5c6a; font-size: 14px; line-height: 1.6; }
.editor-error { display: flex; gap: 8px; margin: 14px 20px 0; padding: 10px; border: 1px solid #d8aaa5; border-radius: 8px; background: #fff5f3; color: #8b3d35; font-size: 14px; line-height: 1.5; }
.editor-field { display: grid; min-height: 0; gap: 8px; margin: 16px 20px; color: #253745; font-size: 14px; font-weight: 650; }
.editor-field textarea { min-height: 360px; resize: vertical; border: 1px solid #ccd0cf; border-radius: 8px; padding: 13px; outline: 0; background: #fbfcfc; color: #06141b; font: 14px/1.6 Consolas, 'Microsoft YaHei', monospace; }
.editor-field textarea:focus { border-color: #11212d; box-shadow: 0 0 0 2px rgba(17,33,45,.12); }
.editor-actions { display: flex; justify-content: flex-end; gap: 8px; padding: 14px 20px 20px; border-top: 1px solid #dfe4e5; }
.editor-primary, .editor-secondary { display: inline-flex; min-height: 40px; align-items: center; gap: 7px; border: 1px solid #ccd0cf; border-radius: 8px; padding: 0 13px; background: #fff; color: #11212d; font-size: 14px; cursor: pointer; }
.editor-primary { border-color: #11212d; background: #11212d; color: #fff; font-weight: 650; }
.editor-primary:disabled, .editor-secondary:disabled { cursor: default; opacity: .48; }
.editor-close:focus-visible, .editor-primary:focus-visible, .editor-secondary:focus-visible { outline: 2px solid #11212d; outline-offset: 2px; }
</style>
