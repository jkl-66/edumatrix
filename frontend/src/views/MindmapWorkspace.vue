<script setup>
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  AlertTriangle,
  ArrowLeft,
  BookOpen,
  ChevronDown,
  ChevronRight,
  ExternalLink,
  FileQuestion,
  Focus,
  GitBranch,
  ListTree,
  MessageSquareText,
  NotebookPen,
  RefreshCw,
  ZoomIn,
  ZoomOut,
} from '@lucide/vue'
import CollapsibleMindmap from '../components/CollapsibleMindmap.vue'
import SearchField from '../components/ui/SearchField.vue'
import ResourceHistoryDrawer from '../components/ResourceHistoryDrawer.vue'
import ResourceToolbar from '../components/ResourceToolbar.vue'
import ResourceProfileAdaptation from '../components/ResourceProfileAdaptation.vue'
import { compareM5ResourceVersions, getM5Resource, restoreM5ResourceVersion } from '../api/m5'

const route = useRoute()
const router = useRouter()
const graphRef = ref(null)
const loading = ref(true)
const error = ref('')
const detail = ref(null)
const selectedVersionId = ref('')
const selectedNodeId = ref('')
const query = ref('')
const graphError = ref('')
const notice = ref('')
const historyOpen = ref(false)
const historyError = ref('')
const restoringId = ref('')
const comparingId = ref('')
const compareResult = ref(null)

const resourceId = computed(() => String(route.params.resourceId || ''))
const versions = computed(() => detail.value?.mindmap?.versions || [])
const currentVersionId = computed(() => detail.value?.mindmap?.current_version_id || '')
const historyItems = computed(() => versions.value.map(item => ({
  ...item,
  revision_origin: item.revision_origin || item.metadata?.revision_origin,
  source_status: item.source_status || 'available',
  content_format: item.content_format || 'json',
})))
const selectedVersion = computed(() => (
  versions.value.find(item => item.id === selectedVersionId.value)
  || versions.value.find(item => item.id === currentVersionId.value)
  || null
))
const projection = computed(() => selectedVersion.value?.projection || detail.value?.mindmap?.current || null)
const structured = computed(() => projection.value?.structured || null)
const fallbackHierarchy = computed(() => (
  projection.value?.legacy?.hierarchy || projection.value?.invalid?.hierarchy || []
))
const nodes = computed(() => {
  if (structured.value?.nodes?.length) return structured.value.nodes
  const projected = fallbackHierarchy.value.map(item => ({
    nodeId: item.nodeId,
    parentNodeId: item.parentNodeId || null,
    label: item.label,
    summary: item.summary || '',
    relation: item.relation || (item.parentNodeId ? '层级' : '主题'),
    depth: Number.isInteger(item.depth) ? item.depth : 0,
    sourceRefs: item.sourceRefs || [],
    masteryBand: item.masteryBand || 'unknown',
    linkedResourceIds: item.linkedResourceIds || [],
  }))
  const roots = projected.filter(node => !node.parentNodeId)
  if (roots.length <= 1) return projected
  const wrapperId = 'legacy-root'
  return [
    {
      nodeId: wrapperId,
      parentNodeId: null,
      label: projection.value?.legacy?.title || projection.value?.invalid?.title || detail.value?.title || '概念思维导图',
      summary: '旧版多根导图的兼容容器。',
      relation: '主题',
      depth: 0,
      sourceRefs: [],
      masteryBand: 'unknown',
      linkedResourceIds: [],
    },
    ...projected.map(node => roots.includes(node)
      ? { ...node, parentNodeId: wrapperId, depth: node.depth + 1 }
      : node),
  ]
})
const graphRootNodeId = computed(() => (
  structured.value?.rootNodeId || nodes.value.find(node => !node.parentNodeId)?.nodeId || ''
))
const sourceRefs = computed(() => projection.value?.source_refs || [])
const linkedResources = computed(() => projection.value?.linked_resources || [])
const catalog = computed(() => detail.value?.catalog || {})
const selectedNode = computed(() => (
  nodes.value.find(node => node.nodeId === selectedNodeId.value)
  || nodes.value.find(node => node.nodeId === structured.value?.rootNodeId)
  || null
))
const selectedSources = computed(() => {
  const wanted = new Set(selectedNode.value?.sourceRefs || [])
  return sourceRefs.value.filter(source => wanted.has(source.source_ref_id))
})
const selectedResources = computed(() => {
  const wanted = new Set(selectedNode.value?.linkedResourceIds || [])
  return linkedResources.value.filter(resource => wanted.has(resource.id))
})
const searchResults = computed(() => {
  const keyword = query.value.trim().toLocaleLowerCase()
  if (!keyword) return []
  return nodes.value.filter((node) => (
    `${node.label} ${node.summary} ${node.relation}`.toLocaleLowerCase().includes(keyword)
  )).slice(0, 12)
})
const isStructured = computed(() => projection.value?.mode === 'structured')
const title = computed(() => structured.value?.title || projection.value?.legacy?.title || detail.value?.title || '思维导图')
const summary = computed(() => structured.value?.summary || '按层级理解知识关系，并从节点进入下一步学习。')
const versionLabel = computed(() => selectedVersion.value ? `v${selectedVersion.value.number}` : '-')
const canvasHeight = computed(() => 568)

function message(exception, fallback) {
  const detailMessage = exception?.response?.data?.detail?.message || exception?.detail?.message
  return detailMessage || (typeof exception?.detail === 'string' ? exception.detail : '') || exception?.message || fallback
}

function preferenceKey() {
  return `edumatrix:mindmap-view:${resourceId.value}:${selectedVersionId.value || currentVersionId.value}`
}

function versionPreferenceKey() {
  return `edumatrix:mindmap-version:${resourceId.value}`
}

function readPreference() {
  try {
    return JSON.parse(localStorage.getItem(preferenceKey()) || 'null')
  } catch {
    return null
  }
}

function savePreference(view) {
  localStorage.setItem(preferenceKey(), JSON.stringify({
    ...view,
    selectedNodeId: selectedNodeId.value,
  }))
}

function saveSelectedNodePreference() {
  const current = readPreference() || {}
  localStorage.setItem(preferenceKey(), JSON.stringify({
    ...current,
    selectedNodeId: selectedNodeId.value,
  }))
}

async function restorePreference() {
  await nextTick()
  const preference = readPreference()
  selectedNodeId.value = nodes.value.some(node => node.nodeId === preference?.selectedNodeId)
    ? preference.selectedNodeId
    : graphRootNodeId.value
  if (preference) graphRef.value?.restoreView(preference)
}

async function loadResource({ preserveVersion = false } = {}) {
  loading.value = true
  error.value = ''
  graphError.value = ''
  try {
    const payload = await getM5Resource(resourceId.value)
    if (payload?.catalog?.type !== 'mind_map') throw new Error('当前资源不是思维导图。')
    detail.value = payload
    const canKeep = preserveVersion && versions.value.some(item => item.id === selectedVersionId.value)
    const preferredVersionId = localStorage.getItem(versionPreferenceKey()) || ''
    const canRestorePreferred = versions.value.some(item => item.id === preferredVersionId)
    if (!canKeep) selectedVersionId.value = canRestorePreferred
      ? preferredVersionId
      : payload.mindmap?.current_version_id || ''
    await restorePreference()
  } catch (exception) {
    error.value = message(exception, '思维导图加载失败，请稍后重试。')
  } finally {
    loading.value = false
  }
}

function selectNode(node) {
  selectedNodeId.value = node.nodeId
  saveSelectedNodePreference()
  notice.value = ''
}

function focusResult(node) {
  selectedNodeId.value = node.nodeId
  saveSelectedNodePreference()
  graphRef.value?.focusNode(node.nodeId)
  query.value = ''
}

function openSource(source) {
  if (!source?.available || !source.source_document_id) return
  router.push({
    name: 'KnowledgeDocument',
    params: { documentId: source.source_document_id },
    query: {
      canonical_source_id: source.source_document_id,
      course_id: catalog.value.course?.id || route.query.course_id,
      focus_source_ref_id: source.source_ref_id,
      return_to: route.fullPath,
    },
  })
}

function openResource(resource) {
  if (resource?.available && resource.route) router.push(resource.route)
}

function askAboutNode() {
  if (!selectedNode.value) return
  router.push({
    name: 'Learn',
    query: {
      resource_id: resourceId.value,
      node_id: selectedNode.value.nodeId,
      source_ref_id: selectedNode.value.sourceRefs?.[0] || undefined,
      prompt: `请解释“${selectedNode.value.label}”，并说明它与上级知识点的关系。`,
    },
  })
}

function createNodeNote() {
  if (!selectedNode.value) return
  router.push({
    name: 'Notes',
    query: {
      resource_id: resourceId.value,
      node_id: selectedNode.value.nodeId,
      source_ref_id: selectedNode.value.sourceRefs?.[0] || undefined,
      title: selectedNode.value.label,
    },
  })
}

function openQuizResource() {
  const quiz = selectedResources.value.find(resource => resource.type === 'quiz' && resource.available)
  if (quiz) {
    openResource(quiz)
    return
  }
  router.push({
    name: 'WorkspaceResources',
    query: {
      type: 'quiz',
      course_id: catalog.value.course?.id || route.query.course_id,
      knowledge_point_id: catalog.value.knowledge_point?.id || undefined,
      source_resource_id: resourceId.value,
      source_node_id: selectedNode.value?.nodeId || undefined,
    },
  })
}

function openHistory() {
  historyError.value = ''
  compareResult.value = null
  historyOpen.value = true
}

function closeHistory() {
  historyOpen.value = false
  historyError.value = ''
  compareResult.value = null
}

function selectHistoryVersion(versionId) {
  selectedVersionId.value = versionId
  closeHistory()
}

async function compareHistory(versionId) {
  if (comparingId.value) return
  const left = versions.value.find(item => item.id === versionId)
  const right = versions.value.find(item => item.id === currentVersionId.value)
  if (!left || !right) return
  comparingId.value = versionId
  historyError.value = ''
  try {
    compareResult.value = await compareM5ResourceVersions(resourceId.value, left.number, right.number)
  } catch (exception) {
    historyError.value = message(exception, '版本比较失败，请稍后重试。')
  } finally {
    comparingId.value = ''
  }
}

async function restoreHistory(versionId) {
  if (restoringId.value || versionId === currentVersionId.value) return
  restoringId.value = versionId
  historyError.value = ''
  try {
    detail.value = await restoreM5ResourceVersion(resourceId.value, {
      expected_lock_version: detail.value.lock_version,
      version_id: versionId,
    })
    selectedVersionId.value = detail.value.mindmap?.current_version_id || detail.value.current_version_id || ''
    notice.value = '历史版本已恢复为新的当前版本，原版本仍保留。'
    closeHistory()
    await restorePreference()
  } catch (exception) {
    historyError.value = message(exception, '恢复失败，当前思维导图没有改变。')
  } finally {
    restoringId.value = ''
  }
}

function masteryLabel(value) {
  return ({ unknown: '尚无证据', needs_work: '需要巩固', developing: '正在建立', secure: '较为稳固' })[value] || '尚无证据'
}

function onGraphError(value) {
  graphError.value = value
}

watch(selectedVersionId, async () => {
  graphError.value = ''
  if (selectedVersionId.value) localStorage.setItem(versionPreferenceKey(), selectedVersionId.value)
  await restorePreference()
})

onMounted(loadResource)
</script>

<template>
  <main class="mindmap-page" data-testid="mindmap-workspace">

    <section v-if="loading" class="page-state" role="status">
      <GitBranch :size="24" />
      <strong>正在打开思维导图</strong>
      <span>正在恢复导图内容和上次视图。</span>
    </section>

    <section v-else-if="error" class="page-state page-state--error" role="alert">
      <AlertTriangle :size="24" />
      <strong>思维导图暂时无法打开</strong>
      <span>{{ error }}</span>
      <button type="button" class="primary-button" @click="loadResource"><RefreshCw :size="17" /> 重新加载</button>
    </section>

    <template v-else>
      <ResourceToolbar
        :title="title"
        :type-label="`${catalog.course?.title || '当前课程'} · ${catalog.knowledge_point?.title || '当前知识点'}`"
        version-label=""
        status-label="沿知识点理解关系"
        :history-count="historyItems.length"
        :history-disabled="!historyItems.length"
        :loading="loading"
        @back="router.push({ name: 'WorkspaceResources', query: { course_id: catalog.course?.id || route.query.course_id } })"
        @history="openHistory"
        @reload="loadResource"
      />
      <p class="toolbar-summary">{{ summary }}</p>

      <ResourceProfileAdaptation
        :plan="detail?.resource?.profile_adaptation_plan"
        :summary="detail?.resource?.profile_adaptation || ''"
        resource-type="mind_map"
      />

      <div v-if="projection?.warnings?.length" class="notice notice--warning" role="status">
        <AlertTriangle :size="17" /> {{ projection.warnings[0] }}
      </div>
      <div v-if="notice" class="notice" role="status">{{ notice }}</div>

      <section class="workspace-shell">
        <div class="workspace-main">
          <div class="toolbar" aria-label="思维导图工具栏">
            <SearchField
              v-model="query"
              class="mindmap-search"
              style="flex: 1"
              aria-label="搜索思维导图节点"
              placeholder="搜索节点、关系或摘要"
            >
              <template #after>
                <div v-if="query" class="search-results">
                  <button v-for="node in searchResults" :key="node.nodeId" type="button" @click="focusResult(node)">
                    <span>{{ node.label }}</span><small>{{ node.relation }}</small>
                  </button>
                  <p v-if="!searchResults.length">没有找到匹配节点。</p>
                </div>
              </template>
            </SearchField>
            <label class="version-control">
              <span>版本</span>
              <select v-model="selectedVersionId" aria-label="选择思维导图版本">
                <option v-for="version in versions" :key="version.id" :value="version.id">v{{ version.number }}</option>
              </select>
              <ChevronDown :size="15" aria-hidden="true" />
            </label>
            <div class="tool-group">
              <button type="button" title="放大" aria-label="放大导图" @click="graphRef?.zoomBy(1.2)"><ZoomIn :size="18" /></button>
              <button type="button" title="缩小" aria-label="缩小导图" @click="graphRef?.zoomBy(0.84)"><ZoomOut :size="18" /></button>
              <button type="button" title="视图居中" aria-label="居中导图" @click="graphRef?.center()"><Focus :size="18" /></button>
              <button type="button" title="折叠分支" aria-label="折叠全部分支" @click="graphRef?.collapseAll()"><ListTree :size="18" /></button>
              <button type="button" title="展开分支" aria-label="展开全部分支" @click="graphRef?.expandAll()"><GitBranch :size="18" /></button>
            </div>
          </div>

          <div v-if="nodes.length && !graphError" class="canvas-wrap">
            <div v-if="!isStructured" class="compatibility-note" role="status">
              这份导图使用兼容阅读方式呈现，节点关系和层级仍然完整保留。
            </div>
            <CollapsibleMindmap
              ref="graphRef"
              :nodes="nodes"
              :root-node-id="graphRootNodeId"
              :selected-node-id="selectedNodeId"
              :height="canvasHeight"
              @select="selectNode"
              @view-change="savePreference"
              @render-error="onGraphError"
            />
          </div>

          <div v-if="!isStructured || !nodes.length || graphError" class="hierarchy-fallback" data-testid="mindmap-hierarchy-fallback">
            <div class="fallback-heading">
              <ListTree :size="20" />
              <div><strong>层级列表</strong><span>{{ isStructured ? '画布暂时不可用时，仍可按层级阅读节点关系。' : '旧版导图仍可按原始层级阅读，节点关系保持不变。' }}</span></div>
            </div>
            <ol>
              <li v-for="node in fallbackHierarchy" :key="node.nodeId" :style="{ '--node-depth': node.depth }">
                <span>{{ node.label }}</span>
              </li>
            </ol>
          </div>
        </div>

        <aside class="node-panel" aria-label="节点详情">
          <template v-if="selectedNode">
            <div class="node-panel__heading">
              <span>{{ selectedNode.relation }}</span>
              <h2>{{ selectedNode.label }}</h2>
              <p>{{ selectedNode.summary }}</p>
            </div>

            <dl class="node-facts">
              <div><dt>掌握程度</dt><dd>{{ masteryLabel(selectedNode.masteryBand) }}</dd></div>
              <div><dt>所在层级</dt><dd>第 {{ selectedNode.depth + 1 }} 层</dd></div>
            </dl>

            <details class="panel-section source-details">
              <summary><h3>相关材料</h3></summary>
              <button
                v-for="source in selectedSources"
                :key="source.source_ref_id"
                type="button"
                class="source-row"
                :disabled="!source.available"
                @click="openSource(source)"
              >
                <BookOpen :size="17" />
                <span><strong>{{ source.title || '参考材料' }}</strong><small>{{ source.location_label || '位置未记录' }}</small></span>
                <ExternalLink v-if="source.available" :size="15" />
              </button>
              <p v-if="!selectedSources.length" class="panel-empty">这个节点暂时没有可打开的补充材料。</p>
            </details>

            <section class="panel-section">
              <h3>关联资源</h3>
              <button
                v-for="resource in selectedResources"
                :key="resource.id"
                type="button"
                class="resource-row"
                :disabled="!resource.available || !resource.route"
                @click="openResource(resource)"
              >
                <span><strong>{{ resource.title || '资源暂不可用' }}</strong><small>{{ resource.type_label || '暂时无法打开' }}</small></span>
                <ChevronRight :size="17" />
              </button>
              <p v-if="!selectedResources.length" class="panel-empty">暂无直接关联资源，可从下方继续学习。</p>
            </section>

            <div class="node-actions">
              <button v-if="selectedResources.some(item => item.available && item.route)" type="button" class="primary-button" @click="openResource(selectedResources.find(item => item.available && item.route))">
                <BookOpen :size="17" /> 打开关联资源
              </button>
              <button v-else type="button" class="primary-button" @click="askAboutNode">
                <MessageSquareText :size="17" /> 询问这个节点
              </button>
              <div>
                <button type="button" class="secondary-button" @click="askAboutNode"><MessageSquareText :size="16" /> 提问</button>
                <button type="button" class="secondary-button" @click="createNodeNote"><NotebookPen :size="16" /> 记笔记</button>
                <button type="button" class="secondary-button" @click="openQuizResource"><FileQuestion :size="16" /> 测验题</button>
              </div>
            </div>

            <p class="evidence-boundary">浏览、搜索、缩放和折叠不会改变掌握度。提交测验、复述、代码、实验或复习结果后，系统才会更新学习进度。</p>
          </template>
          <div v-else class="panel-empty panel-empty--large">选择一个节点查看摘要和下一步。</div>
        </aside>
      </section>
    </template>

    <ResourceHistoryDrawer
      :open="historyOpen"
      :title="`${title} · 版本历史`"
      :items="historyItems"
      :current-version-id="currentVersionId"
      :selected-version-id="selectedVersionId"
      :restoring-id="restoringId"
      :error="historyError"
      :compare-result="compareResult"
      :comparing-id="comparingId"
      :compare-disabled="Boolean(comparingId)"
      :restore-disabled="Boolean(restoringId)"
      @close="closeHistory"
      @select="selectHistoryVersion"
      @compare="compareHistory"
      @restore="restoreHistory"
      @compare-close="compareResult = null"
    />
  </main>
</template>

<style scoped>
.mindmap-page{min-height:100%;padding:24px 28px 32px;background:var(--color-page);color:var(--color-text);font-family:var(--font-sans)}
.back-link{display:inline-flex;align-items:center;gap:8px;margin:0 0 18px;padding:0;border:0;background:transparent;color:var(--color-text-secondary);font-size:14px;font-weight:650;cursor:pointer}
.back-link:hover{color:var(--color-text)}
.page-header{display:grid;grid-template-columns:minmax(0,1fr) minmax(500px,.85fr);gap:36px;align-items:end;padding:0 0 22px;border-bottom:1px solid var(--color-border)}
.context-line{margin:0 0 6px;color:var(--color-text-secondary);font-size:14px;font-weight:650}
.page-header h1{margin:0;font-family:var(--font-heading);font-size:34px;line-height:1.25;letter-spacing:0}
.toolbar-summary{margin:10px 0 0;color:var(--color-text-secondary);font-size:15px;line-height:1.6}
.page-header>div>p:last-child{max-width:70ch;margin:9px 0 0;color:var(--color-text-secondary);font-size:15px;line-height:1.65}
.header-meta{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));border:1px solid var(--color-border);border-radius:8px;background:#fff;overflow:hidden}
.header-meta>div{min-width:0;padding:13px 14px;border-right:1px solid var(--color-border)}
.header-meta>div:last-child{border-right:0}.header-meta span,.header-meta strong{display:block}.header-meta span{color:var(--color-text-muted);font-size:14px}.header-meta strong{margin-top:4px;font-size:14px;line-height:1.45}
.notice{display:flex;align-items:center;gap:8px;margin:14px 0 0;padding:10px 12px;border:1px solid var(--color-border);border-radius:6px;background:#fff;color:var(--color-text-secondary);font-size:14px}
.notice--warning{border-color:#dfcfb4;background:var(--color-warning-soft);color:#6f501e}
.workspace-shell{display:grid;grid-template-columns:minmax(0,74fr) minmax(290px,26fr);min-height:640px;margin-top:18px;border:1px solid var(--color-border-strong);border-radius:8px;background:#fff;overflow:hidden}
.workspace-main{min-width:0;border-right:1px solid var(--color-border)}
.toolbar{position:relative;display:flex;align-items:center;gap:12px;min-height:58px;padding:9px 12px;border-bottom:1px solid var(--color-border);background:#fff}
.search-results{position:absolute;z-index:8;top:46px;left:0;right:0;padding:6px;border:1px solid var(--color-border-strong);border-radius:7px;background:#fff;box-shadow:var(--shadow-popover)}
.search-results button{display:flex;width:100%;align-items:center;justify-content:space-between;gap:12px;padding:9px 10px;border:0;border-radius:5px;background:transparent;color:var(--color-text);font:15px/1.4 var(--font-sans);text-align:left;cursor:pointer}
.search-results button:hover,.search-results button:focus-visible{background:var(--color-accent-soft);outline:none}.search-results small{color:var(--color-text-muted);font-size:14px}.search-results p{margin:10px;color:var(--color-text-muted);font-size:14px}
.version-control{position:relative;display:flex;align-items:center;gap:7px;height:40px;padding:0 9px 0 11px;border:1px solid var(--color-border);border-radius:6px;color:var(--color-text-secondary);font-size:14px}.version-control select{appearance:none;min-width:58px;padding:0 20px 0 0;border:0;outline:0;background:transparent;color:var(--color-text);font:600 14px/1.4 var(--font-sans)}.version-control svg{position:absolute;right:8px;pointer-events:none}
.tool-group{display:flex;gap:4px}.tool-group button{display:grid;width:38px;height:38px;place-items:center;border:1px solid transparent;border-radius:6px;background:transparent;color:var(--color-text-secondary);cursor:pointer}.tool-group button:hover,.tool-group button:focus-visible{border-color:var(--color-border);background:var(--color-surface-subtle);color:var(--color-text);outline:none}
.canvas-wrap{position:relative;height:568px;padding:12px;background:#fff}.canvas-wrap>.mindmap-surface{height:100%}.compatibility-note{position:absolute;z-index:3;top:20px;left:24px;right:24px;padding:9px 14px;border:1px solid var(--color-border);border-radius:6px;background:rgba(255,255,255,.94);color:var(--color-text-secondary);font-size:14px;line-height:1.5;pointer-events:none}.hierarchy-fallback{min-height:568px;padding:24px 28px}.fallback-heading{display:flex;align-items:flex-start;gap:12px;padding-bottom:18px;border-bottom:1px solid var(--color-border)}.fallback-heading strong,.fallback-heading span{display:block}.fallback-heading strong{font-size:17px}.fallback-heading span{margin-top:3px;color:var(--color-text-secondary);font-size:14px}.hierarchy-fallback ol{margin:18px 0 0;padding:0;list-style:none}.hierarchy-fallback li{margin-left:calc(var(--node-depth) * 24px);padding:10px 12px;border-bottom:1px solid var(--color-border);font-size:15px}
.node-panel{min-width:0;padding:22px 20px;background:var(--color-surface-subtle);overflow-y:auto}.node-panel__heading>span{display:inline-block;margin-bottom:8px;color:var(--color-text-secondary);font-size:14px;font-weight:650}.node-panel h2{margin:0;font-size:22px;line-height:1.35}.node-panel__heading p{margin:9px 0 0;color:var(--color-text-secondary);font-size:15px;line-height:1.65}
.node-facts{display:grid;grid-template-columns:1fr;margin:20px 0 0;border-top:1px solid var(--color-border);border-bottom:1px solid var(--color-border)}.node-facts>div{display:flex;align-items:center;justify-content:space-between;gap:16px;padding:10px 0;border-bottom:1px solid var(--color-border)}.node-facts>div:last-child{border-bottom:0}.node-facts dt{color:var(--color-text-muted);font-size:14px}.node-facts dd{margin:0;font-size:14px;font-weight:650;text-align:right}
.panel-section{margin-top:22px}.panel-section h3{margin:0 0 9px;font-size:16px}.source-row,.resource-row{display:flex;width:100%;align-items:center;gap:10px;margin-top:7px;padding:10px;border:1px solid var(--color-border);border-radius:6px;background:#fff;color:var(--color-text);text-align:left;cursor:pointer}.source-row:disabled,.resource-row:disabled{cursor:not-allowed;opacity:.62}.source-row>span,.resource-row>span{flex:1;min-width:0}.source-row strong,.source-row small,.resource-row strong,.resource-row small{display:block;overflow-wrap:anywhere}.source-row strong,.resource-row strong{font-size:14px}.source-row small,.resource-row small{margin-top:3px;color:var(--color-text-muted);font-size:14px}.panel-empty{margin:8px 0 0;color:var(--color-text-muted);font-size:14px;line-height:1.55}.panel-empty--large{display:grid;min-height:400px;place-items:center;text-align:center}
.node-actions{margin-top:24px}.node-actions>div{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:6px;margin-top:8px}.primary-button,.secondary-button{display:inline-flex;align-items:center;justify-content:center;gap:7px;min-height:40px;padding:0 13px;border-radius:6px;font:650 14px/1.3 var(--font-sans);cursor:pointer}.primary-button{width:100%;border:1px solid var(--color-accent);background:var(--color-accent);color:#fff}.secondary-button{border:1px solid var(--color-border-strong);background:#fff;color:var(--color-text)}.primary-button:focus-visible,.secondary-button:focus-visible{outline:2px solid var(--color-accent);outline-offset:2px}
.evidence-boundary{margin:18px 0 0;padding-top:15px;border-top:1px solid var(--color-border);color:var(--color-text-muted);font-size:14px;line-height:1.55}
.page-state{display:grid;min-height:560px;place-items:center;align-content:center;gap:8px;border:1px solid var(--color-border);border-radius:8px;background:#fff;text-align:center}.page-state strong{font-size:18px}.page-state span{color:var(--color-text-secondary);font-size:15px}.page-state .primary-button{width:auto;margin-top:8px}.page-state--error svg{color:var(--color-danger)}
@media (max-width:1380px){.mindmap-page{padding:20px 22px 28px}.page-header{grid-template-columns:minmax(0,1fr) 520px;gap:24px}.workspace-shell{grid-template-columns:minmax(0,72fr) minmax(300px,28fr)}.node-panel{padding:20px 16px}.node-actions>div{grid-template-columns:1fr}.toolbar{gap:8px}.tool-group{gap:2px}}
</style>
