<script setup>
import { learningText } from '../utils/learningCopy.js'
import { userMessage } from '../services/errorTranslator.js'
import { computed } from 'vue'
import {
  AlertCircle, Archive, ArchiveRestore, BookOpen, Check, Clock3, Database, Download, ExternalLink,
  FileQuestion, History, LoaderCircle, Pencil, RefreshCw, Sparkles,
} from '@lucide/vue'

const props = defineProps({
  resource: { type: Object, default: null },
  detail: { type: Object, default: null },
  loading: { type: Boolean, default: false },
  error: { type: String, default: '' },
  downloading: { type: Boolean, default: false },
  archiving: { type: Boolean, default: false },
})

defineEmits(['open', 'download', 'retry', 'history', 'complete', 'generate', 'edit', 'generation', 'archive'])

const sources = computed(() => (
  props.detail?.resource?.source_refs || props.resource?.resource?.source_refs || []
))

const currentVersion = computed(() => {
  const versions = props.detail?.versions || []
  return versions.find(item => item.id === props.detail?.current_version_id) || versions.at(-1) || null
})

const historyCount = computed(() => props.detail?.history?.items?.length || 0)
const completionRule = computed(() => String(props.resource?.completion?.display_rule ?? props.resource?.completion?.rule ?? '').trim())
const completionRecorded = computed(() => props.resource?.completion?.status === 'completed')
const learningUnavailable = computed(() => props.detail?.resource?.learning_unavailable_reason || props.resource?.resource?.learning_unavailable_reason || '')
const generationJobId = computed(() => props.detail?.resource?.generation_job_id || props.resource?.resource?.generation_job_id)

function formatDate(value) {
  if (!value) return '未记录'
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit',
  }).format(new Date(value))
}
</script>

<template>
  <aside class="resource-preview" data-testid="resource-preview" aria-label="资源预览" aria-live="polite">
    <div v-if="loading" class="preview-state preview-loading">
      <LoaderCircle :size="24" class="spin" />
      <strong>正在读取资源</strong>
      <span>列表与当前筛选会保持不变</span>
    </div>

    <div v-else-if="error && resource" class="preview-state preview-error">
      <AlertCircle :size="24" />
      <strong>预览暂时不可用</strong>
      <span>{{ userMessage(error) }}</span>
      <button type="button" class="secondary-action" @click="$emit('retry')">
        <RefreshCw :size="16" />重新加载
      </button>
    </div>

    <div v-else-if="!resource" class="preview-state">
      <FileQuestion :size="26" />
      <strong>选择一个资源</strong>
      <span>可先按类型筛选，再从列表或网格中选择。</span>
    </div>

    <template v-else>
      <header class="preview-header">
        <div>
          <span class="resource-kind">{{ resource.type_label }}</span>
          <h2>{{ resource.title }}</h2>
        </div>
        <span class="status-label">{{ resource.display_status }}</span>
      </header>

      <p class="preview-copy">
        {{ learningText(resource.preview?.text, '该资源暂未提供可展示的内容摘要。') }}
      </p>

      <dl class="preview-facts">
        <div>
          <dt><BookOpen :size="16" />课程</dt>
          <dd>{{ resource.course?.title || '未绑定课程' }}</dd>
        </div>
        <div>
          <dt><Database :size="16" />知识点</dt>
          <dd>{{ resource.knowledge_point?.title || '未记录' }}</dd>
        </div>
        <div>
          <dt><Clock3 :size="16" />最近更新</dt>
          <dd>{{ formatDate(resource.updated_at) }}</dd>
        </div>
      </dl>

      <section class="preview-section">
        <div class="section-heading">
          <h3>资源信息</h3>
          <span>v{{ currentVersion?.version_number || resource.version_number || '-' }}</span>
        </div>
        <div class="metadata-grid">
          <span>来源 {{ resource.source_count || 0 }} 项</span>
          <span>完成进度 {{ resource.completion_text }}</span>
          <span>{{ resource.module || '未记录所属模块' }}</span>
        </div>
        <div v-if="resource.tags?.length" class="tag-list" aria-label="资源标签">
          <span v-for="tag in resource.tags" :key="tag">{{ tag }}</span>
        </div>
      </section>

      <section class="completion-section" aria-label="学习完成条件">
        <div class="section-heading"><h3>学习完成条件</h3><Check v-if="completionRecorded" :size="17" /></div>
        <p v-if="completionRule">{{ completionRule }}</p>
        <p v-else>当前版本没有记录可验证的完成条件，请打开资源查看具体学习动作。</p>
        <span v-if="completionRecorded" class="completion-recorded">本次学习已记录。掌握情况会结合你的作答与实践结果判断。</span>
      </section>

      <details class="source-details">
        <summary>查看来源</summary>
        <div v-if="sources.length" class="source-list">
          <div v-for="source in sources" :key="source.source_ref_id">
            <strong>{{ source.title || '来源已失效' }}</strong>
            <span>{{ source.location_label || source.location_kind || '未记录位置' }}</span>
          </div>
        </div>
        <p v-else>此资源未记录来源。</p>
      </details>

      <div class="preview-actions">
        <p v-if="learningUnavailable">{{ learningUnavailable }}</p>
        <button v-if="learningUnavailable && !resource.archived && generationJobId" type="button" class="primary-action" @click="$emit('generation', generationJobId)">
          <RefreshCw :size="17" />查看生成结果
        </button>
        <button
          type="button"
          class="primary-action"
          :disabled="!resource.route || (Boolean(learningUnavailable) && !resource.archived)"
          @click="$emit(resource.archived ? 'history' : 'open')"
        >
          <ExternalLink :size="17" />{{ resource.archived ? '查看版本历史' : '打开资源' }}
        </button>
        <button
          type="button"
          class="secondary-action"
          :disabled="resource.archived || !completionRule || completionRecorded || Boolean(learningUnavailable)"
          @click="$emit('complete')"
        >
          <Check :size="16" />{{ completionRecorded ? '已完成' : '完成学习' }}
        </button>
        <button type="button" class="secondary-action" @click="$emit('history')">
          <History :size="16" />历史 {{ historyCount }}
        </button>
        <button type="button" class="secondary-action" @click="$emit('generate')">
          <Sparkles :size="16" />生成同类资源
        </button>
        <button type="button" class="secondary-action" :disabled="resource.archived" @click="$emit('edit')">
          <Pencil :size="16" />编辑另存
        </button>
        <button type="button" class="secondary-action" :disabled="archiving || !detail" @click="$emit('archive')">
          <LoaderCircle v-if="archiving" :size="16" class="spin" />
          <ArchiveRestore v-else-if="resource.archived" :size="16" />
          <Archive v-else :size="16" />
          {{ resource.archived ? '恢复资源' : '归档资源' }}
        </button>
        <button
          type="button"
          class="icon-action"
          title="下载当前版本"
          :disabled="downloading"
          @click="$emit('download')"
        >
          <LoaderCircle v-if="downloading" :size="17" class="spin" />
          <Download v-else :size="17" />
          <span class="sr-only">下载当前版本</span>
        </button>
      </div>
    </template>
  </aside>
</template>

<style scoped>
.resource-preview {
  box-sizing: border-box;
  min-width: 0;
  height: 100%;
  overflow: auto;
  border: 1px solid var(--color-border-strong);
  border-radius: 8px;
  background: var(--color-surface);
  color: var(--color-text);
}

.preview-state {
  display: grid;
  min-height: 100%;
  place-content: center;
  justify-items: center;
  gap: 10px;
  padding: 28px;
  color: var(--color-text-secondary);
  text-align: center;
}

.preview-state strong { color: var(--color-text); font-size: 16px; }
.preview-state span { max-width: 26ch; font-size: 14px; line-height: 1.6; }
.preview-error { color: var(--color-danger); }

.preview-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 14px;
  padding: 20px 20px 16px;
  border-bottom: 1px solid var(--color-border);
}

.preview-header > div { min-width: 0; }
.resource-kind { color: var(--color-text-secondary); font-size: 14px; font-weight: 650; }
.preview-header h2 { margin: 7px 0 0; font-size: 20px; line-height: 1.35; overflow-wrap: anywhere; }
.status-label { flex: 0 0 auto; padding: 5px 8px; border-radius: 6px; background: var(--color-surface-subtle); color: var(--color-text); font-size: 14px; }
.preview-copy { margin: 0; padding: 18px 20px; color: var(--color-text-secondary); font-size: 15px; line-height: 1.7; }

.preview-facts { display: grid; gap: 0; margin: 0; border-block: 1px solid var(--color-border); }
.preview-facts div { padding: 13px 20px; border-bottom: 1px solid var(--color-surface-subtle); }
.preview-facts div:last-child { border-bottom: 0; }
.preview-facts dt { display: flex; align-items: center; gap: 7px; color: var(--color-text-muted); font-size: 14px; }
.preview-facts dd { margin: 5px 0 0; color: var(--color-text); font-size: 15px; line-height: 1.45; overflow-wrap: anywhere; }
.preview-section { padding: 18px 20px; border-bottom: 1px solid var(--color-border); }
.section-heading { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.section-heading h3 { margin: 0; font-size: 16px; }
.section-heading span { color: var(--color-text-muted); font-size: 14px; }
.metadata-grid { display: grid; gap: 7px; margin-top: 12px; color: var(--color-text-secondary); font-size: 14px; }
.tag-list { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 12px; }
.tag-list span { padding: 4px 7px; border: 1px solid var(--color-border-strong); border-radius: 6px; color: var(--color-text-secondary); font-size: 14px; }
.source-details { padding: 14px 20px; border-bottom: 1px solid var(--color-border); }
.source-details summary { color: var(--color-text); font-size: 14px; font-weight: 650; cursor: pointer; }
.source-list { display: grid; gap: 10px; margin-top: 12px; }
.source-list div { padding-top: 10px; border-top: 1px solid var(--color-surface-subtle); }
.source-list strong, .source-list span { display: block; font-size: 14px; line-height: 1.5; }
.source-list span, .source-details p { color: var(--color-text-muted); }
.source-details p { margin: 10px 0 0; font-size: 14px; line-height: 1.6; }
.preview-actions { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; padding: 16px 20px 20px; }
.primary-action, .secondary-action, .icon-action { display: inline-flex; align-items: center; justify-content: center; gap: 8px; min-height: 42px; border-radius: 8px; font-size: 14px; font-weight: 650; cursor: pointer; }
.primary-action { border: 1px solid var(--color-text); background: var(--color-text); color: #fff; }
.secondary-action { border: 1px solid var(--color-border-strong); padding: 0 13px; background: var(--color-surface); color: var(--color-text); }
.icon-action { border: 1px solid var(--color-border-strong); background: var(--color-surface); color: var(--color-text); }
.completion-section { padding: 16px 20px; border-bottom: 1px solid var(--color-border); }
.completion-section p { margin: 8px 0 0; color: var(--color-text-secondary); font-size: 14px; line-height: 1.6; }
.completion-recorded { display: block; margin-top: 8px; color: var(--color-text-muted); font-size: 14px; line-height: 1.5; }
button:disabled { cursor: default; opacity: .48; }
button:focus-visible, summary:focus-visible { outline: 2px solid var(--color-text); outline-offset: 2px; }
.spin { animation: spin .8s linear infinite; }
.sr-only { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0, 0, 0, 0); white-space: nowrap; }
@keyframes spin { to { transform: rotate(360deg); } }
</style>
