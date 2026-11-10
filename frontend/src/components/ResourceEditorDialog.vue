<script setup>
import { userMessage } from '../services/errorTranslator.js'
import { computed } from 'vue'
import { AlertCircle, Save, X } from '@lucide/vue'
import { resourceContentFields, updateResourceContent } from '../utils/resourceContentFields.js'

const props = defineProps({
  open: { type: Boolean, default: false },
  title: { type: String, default: '编辑资源' },
  versionLabel: { type: String, default: '' },
  content: { type: String, default: '' },
  contentFormat: { type: String, default: 'markdown' },
  saving: { type: Boolean, default: false },
  error: { type: String, default: '' },
  canRefresh: { type: Boolean, default: false },
  refreshing: { type: Boolean, default: false },
  saveDisabled: { type: Boolean, default: false },
})

const emit = defineEmits(['close', 'update:content', 'save', 'refresh'])
const lineCount = computed(() => props.content.split('\n').length)
const structuredContent = computed(() => {
  if (props.contentFormat !== 'json') return null
  try { return JSON.parse(props.content) } catch { return null }
})
const learningFields = computed(() => resourceContentFields(structuredContent.value))
function editField(field, value) {
  emit('update:content', JSON.stringify(updateResourceContent(structuredContent.value, field.path, value), null, 2))
}
const videoContent = computed(() => {
  if (props.contentFormat !== 'json') return null
  try {
    const value = JSON.parse(props.content)
    return value.schemaVersion === 'f5.video-recommendation.v1' ? value : null
  } catch { return null }
})

function editVideo(path, value) {
  const content = JSON.parse(props.content)
  let parent = content
  for (const key of path.slice(0, -1)) parent = parent[key]
  parent[path.at(-1)] = value
  emit('update:content', JSON.stringify(content, null, 2))
}

function addAlternative(index) {
  editVideo(['recommendations', index, 'alternatives'], [
    ...(videoContent.value.recommendations[index].alternatives || []),
    {id: `alternative-${Date.now()}`, title: '', url: '', reason: ''},
  ])
}

function removeAlternative(index, alternativeIndex) {
  editVideo(['recommendations', index, 'alternatives'],
    videoContent.value.recommendations[index].alternatives.filter((_, i) => i !== alternativeIndex))
}
</script>

<template>
  <div v-if="open" class="editor-layer">
    <button type="button" class="editor-backdrop" aria-label="关闭资源编辑" @click="emit('close')" />
    <section class="editor-dialog" role="dialog" aria-modal="true" :aria-labelledby="`${title}-editor-title`">
      <header class="editor-heading">
        <div><span>从 {{ versionLabel }} 开始编辑</span><h2 :id="`${title}-editor-title`">{{ title }}</h2></div>
        <button type="button" class="editor-close" title="关闭资源编辑" @click="emit('close')"><X :size="18" /></button>
      </header>
      <p class="editor-notice">保存后会产生新版本，原版本和来源记录仍可查看。请核对标题、学习说明及链接，再保存。</p>
      <div v-if="error" class="editor-error" role="alert"><AlertCircle :size="17" />{{ userMessage(error) }}</div>
      <div v-if="saveDisabled" class="editor-conflicts"><slot name="conflicts" /></div>
      <div v-if="videoContent" class="video-editor">
        <label v-for="field in [{key:'title',label:'资源标题'},{key:'summary',label:'学习说明'},{key:'learningGoal',label:'学习目标'},{key:'adaptationSummary',label:'学习建议'}]" :key="field.key">
          <span>{{ field.label }}</span>
          <textarea :aria-label="field.label" :value="videoContent[field.key]" rows="2" @input="editVideo([field.key], $event.target.value)" />
        </label>
        <section v-for="(item,index) in videoContent.recommendations" :key="item.id" class="video-edit-card">
          <h3>视频 {{ index + 1 }}</h3>
          <label><span>视频标题</span><input :aria-label="`视频${index + 1}标题`" :value="item.title" @input="editVideo(['recommendations',index,'title'], $event.target.value)" /></label>
          <template v-if="item.sourceKind === 'external_url'">
            <label><span>观看地址</span><input :aria-label="`视频${index + 1}观看地址`" :value="item.url" @input="editVideo(['recommendations',index,'url'], $event.target.value)" /></label>
            <label><span>来源状态</span><select :aria-label="`视频${index + 1}来源状态`" :value="item.availability" @change="editVideo(['recommendations',index,'availability'], $event.target.value)"><option value="external_only">可尝试观看</option><option value="unavailable">已确认暂不可用</option></select></label>
          </template>
          <p v-else>站内视频素材</p>
          <label><span>推荐理由</span><textarea :aria-label="`视频${index + 1}推荐理由`" :value="item.reason" rows="3" @input="editVideo(['recommendations',index,'reason'], $event.target.value)" /></label>
          <div v-for="(segment,segmentIndex) in item.segments" :key="segment.id" class="video-edit-segment">
            <label><span>分段标题</span><input :aria-label="`视频${index + 1}分段${segmentIndex + 1}标题`" :value="segment.title" @input="editVideo(['recommendations',index,'segments',segmentIndex,'title'], $event.target.value)" /></label>
            <div class="video-edit-time">
              <label><span>开始秒数</span><input type="number" min="0" :aria-label="`视频${index + 1}分段${segmentIndex + 1}开始秒数`" :value="segment.startSeconds" @input="editVideo(['recommendations',index,'segments',segmentIndex,'startSeconds'], Number($event.target.value))" /></label>
              <label><span>结束秒数</span><input type="number" min="1" :aria-label="`视频${index + 1}分段${segmentIndex + 1}结束秒数`" :value="segment.endSeconds" @input="editVideo(['recommendations',index,'segments',segmentIndex,'endSeconds'], Number($event.target.value))" /></label>
            </div>
            <label><span>分段学习重点</span><textarea :aria-label="`视频${index + 1}分段${segmentIndex + 1}学习重点`" :value="segment.learningFocus" rows="2" @input="editVideo(['recommendations',index,'segments',segmentIndex,'learningFocus'], $event.target.value)" /></label>
          </div>
          <div v-for="(alternative,alternativeIndex) in item.alternatives" :key="alternative.id" class="video-edit-segment">
            <label v-for="field in [{key:'title',label:'标题'},{key:'url',label:'观看地址'},{key:'reason',label:'学习说明'}]" :key="field.key">
              <span>替代来源{{ field.label }}</span><input :aria-label="`视频${index + 1}替代${alternativeIndex + 1}${field.label}`" :value="alternative[field.key]" @input="editVideo(['recommendations',index,'alternatives',alternativeIndex,field.key], $event.target.value)" />
            </label>
            <button type="button" class="editor-secondary" @click="removeAlternative(index,alternativeIndex)">移除此替代来源</button>
          </div>
          <button type="button" class="editor-secondary" :aria-label="`视频${index + 1}添加替代来源`" @click="addAlternative(index)">添加替代来源</button>
        </section>
      </div>
      <div v-else-if="learningFields.length" class="video-editor" aria-label="编辑学习内容">
        <label v-for="field in learningFields" :key="JSON.stringify(field.path)">
          <span>{{ field.label }}</span>
          <input v-if="field.type === 'number'" type="number" min="1" :aria-label="field.label" :value="field.value" @input="editField(field, $event.target.value)" />
          <textarea v-else :aria-label="field.label" :class="{ 'teaching-code': field.code }" :value="field.value" :rows="field.code ? 8 : 3" @input="editField(field, $event.target.value)" />
        </label>
      </div>
      <p v-else-if="contentFormat === 'json'" class="editor-notice">这份资源暂时无法整理为可编辑的学习内容，请打开其他有效版本，或重新生成后再编辑。</p>
      <label v-else class="editor-field">
        <span>资源内容 · {{ lineCount }} 行</span>
        <textarea :value="content" spellcheck="false" @input="emit('update:content', $event.target.value)" />
      </label>
      <footer class="editor-actions">
        <button v-if="canRefresh" type="button" class="editor-secondary" :disabled="saving || refreshing || saveDisabled" @click="emit('refresh')">{{ refreshing ? '正在合并更新' : '刷新版本状态' }}</button>
        <button type="button" class="editor-secondary" :disabled="saving" @click="emit('close')">取消</button>
        <button type="button" class="editor-primary" :disabled="saving || refreshing || saveDisabled || !content.trim() || (contentFormat === 'json' && !videoContent && !learningFields.length)" @click="emit('save')"><Save :size="16" />{{ saving ? '保存中' : '保存为新版本' }}</button>
      </footer>
    </section>
  </div>
</template>

<style scoped>
.editor-layer { position: fixed; z-index: 95; inset: 0; display: grid; place-items: center; padding: 24px; }
.video-editor textarea.teaching-code { font-family: Consolas, monospace; }
.editor-conflicts { overflow: auto; flex: 0 1 380px; padding: 0 20px; }
.video-editor{display:grid;gap:14px;min-height:0;overflow-y:auto;padding:16px 20px}.video-editor label{display:grid;gap:6px;color:var(--color-text-secondary);font-size:14px}.video-editor input,.video-editor textarea,.video-editor select{box-sizing:border-box;width:100%;padding:9px 10px;border:1px solid var(--color-border-strong);border-radius:6px;background:var(--color-surface);color:var(--color-text);font:inherit;line-height:1.5}.video-editor textarea{resize:vertical}.video-edit-card{display:grid;gap:12px;padding:14px;border:1px solid var(--color-border);border-radius:8px}.video-edit-card h3{margin:0;color:var(--color-text);font-size:17px}.video-edit-segment{display:grid;gap:10px;border-top:1px solid var(--color-border);padding-top:12px}.video-edit-time{display:grid;grid-template-columns:1fr 1fr;gap:12px}.video-editor button{justify-self:start}
.editor-backdrop { position: absolute; inset: 0; border: 0; background: rgba(6,20,27,.24); cursor: default; }
.editor-dialog { position: relative; display: flex; width: min(860px,100%); max-height: min(760px,calc(100vh - 48px)); flex-direction: column; overflow: hidden; border: 1px solid var(--color-border-strong); border-radius: 8px; background: var(--color-surface); color: var(--color-text); box-shadow: 0 16px 36px rgba(6,20,27,.16); }
.editor-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 14px; padding: 20px; border-bottom: 1px solid var(--color-border); }
.editor-heading span { color: var(--color-text-muted); font-size: 14px; }
.editor-heading h2 { margin: 5px 0 0; font-size: 20px; line-height: 1.35; overflow-wrap: anywhere; }
.editor-close { display: grid; width: 36px; height: 36px; place-items: center; border: 1px solid var(--color-border-strong); border-radius: 8px; background: var(--color-surface); color: var(--color-text); cursor: pointer; }
.editor-notice { margin: 0; padding: 13px 20px; border-bottom: 1px solid var(--color-surface-subtle); color: var(--color-text-secondary); font-size: 14px; line-height: 1.6; }
.editor-error { display: flex; gap: 8px; margin: 14px 20px 0; padding: 10px; border: 1px solid #d8aaa5; border-radius: 8px; background: var(--color-danger-soft); color: var(--color-danger); font-size: 14px; line-height: 1.5; }
.editor-field { display: grid; min-height: 0; gap: 8px; margin: 16px 20px; color: var(--color-text); font-size: 14px; font-weight: 650; }
.editor-field textarea { min-height: 360px; resize: vertical; border: 1px solid var(--color-border-strong); border-radius: 8px; padding: 13px; outline: 0; background: #fbfcfc; color: var(--color-text); font: 14px/1.6 Consolas, 'Microsoft YaHei', monospace; }
.editor-field textarea:focus { border-color: var(--color-text); box-shadow: 0 0 0 2px rgba(17,33,45,.12); }
.editor-actions { display: flex; justify-content: flex-end; gap: 8px; padding: 14px 20px 20px; border-top: 1px solid var(--color-border); }
.editor-primary, .editor-secondary { display: inline-flex; min-height: 40px; align-items: center; gap: 7px; border: 1px solid var(--color-border-strong); border-radius: 8px; padding: 0 13px; background: var(--color-surface); color: var(--color-text); font-size: 14px; cursor: pointer; }
.editor-primary { border-color: var(--color-text); background: var(--color-text); color: #fff; font-weight: 650; }
.editor-primary:disabled, .editor-secondary:disabled { cursor: default; opacity: .48; }
.editor-close:focus-visible, .editor-primary:focus-visible, .editor-secondary:focus-visible { outline: 2px solid var(--color-text); outline-offset: 2px; }
</style>
