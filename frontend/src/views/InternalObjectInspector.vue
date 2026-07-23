<script setup>
import { computed, onMounted, ref } from 'vue'
import { Search, RefreshCw, ChevronRight, ShieldCheck, AlertCircle, Route } from '@lucide/vue'
import { getInternalObjects, inspectInternalObject, inspectInternalTrace, normalizeApiError } from '../api'

const mode = ref('objects')
const objectType = ref('artifact')
const status = ref('')
const query = ref('')
const items = ref([])
const nextCursor = ref(null)
const hasMore = ref(false)
const selected = ref(null)
const loading = ref(false)
const error = ref('')
const traceId = ref('')
const traceResult = ref(null)

const typeOptions = [
  { value: 'artifact', label: '产物' },
  { value: 'generation_task', label: '生成任务' },
  { value: 'course', label: '课程' },
  { value: 'source_document', label: '来源文档' },
]

const traceLabels = {
  profile_snapshots: '画像快照',
  tasks: '生成任务',
  agent_runs: 'Agent 运行',
  artifacts: '产物',
  artifact_versions: '产物版本',
  learning_events: '学习事件',
  quality_checks: '质量检查',
  claim_checks: '事实检查',
  debate_rounds: '辩论轮次',
  decisions: '决策记录',
  evaluation_runs: '评测运行',
}

const traceGroups = computed(() => {
  if (!traceResult.value) return []
  return Object.entries(traceResult.value.groups || {})
    .filter(([, rows]) => rows.length)
    .map(([key, rows]) => ({ key, label: traceLabels[key] || key, rows }))
})

const friendlyError = computed(() => {
  if (!error.value) return ''
  return error.value
})

async function load(reset = true) {
  loading.value = true
  error.value = ''
  if (reset) {
    items.value = []
    nextCursor.value = null
    selected.value = null
  }
  try {
    const data = await getInternalObjects({
      object_type: objectType.value,
      status: status.value || undefined,
      q: query.value.trim() || undefined,
      cursor: reset ? undefined : nextCursor.value,
      limit: 25,
    })
    items.value = reset ? data.items : [...items.value, ...data.items]
    nextCursor.value = data.next_cursor
    hasMore.value = data.has_more
  } catch (e) {
    const normalized = normalizeApiError(e)
    error.value = normalized.kind === 'forbidden' ? '当前账号没有内部对象检查权限。' : normalized.detail
  } finally {
    loading.value = false
  }
}

async function inspect(item) {
  error.value = ''
  try {
    selected.value = await inspectInternalObject(objectType.value, item.id)
  } catch (e) {
    const normalized = normalizeApiError(e)
    error.value = normalized.kind === 'not_found' ? '对象已不存在或已被归档。' : normalized.detail
  }
}

async function loadTrace() {
  const value = traceId.value.trim()
  if (!value) return
  loading.value = true
  error.value = ''
  traceResult.value = null
  try {
    traceResult.value = await inspectInternalTrace(value)
  } catch (e) {
    const normalized = normalizeApiError(e)
    error.value = normalized.kind === 'not_found' ? 'Trace 不存在或尚未持久化。'
      : normalized.kind === 'forbidden' ? '当前账号没有内部 Trace 检查权限。' : normalized.detail
  } finally {
    loading.value = false
  }
}

onMounted(() => load())
</script>

<template>
  <section class="inspector-page">
    <div class="inspector-head">
      <div>
        <p class="eyebrow">INTERNAL TRACE</p>
        <h2>对象检查</h2>
        <p class="subhead">查看对象所有者、版本、权限和即时资源血缘。</p>
      </div>
      <div class="operator-badge"><ShieldCheck :size="15" /> 内部权限</div>
    </div>

    <div class="mode-switch" role="tablist" aria-label="检查模式">
      <button :class="{ active: mode === 'objects' }" @click="mode = 'objects'">对象</button>
      <button :class="{ active: mode === 'trace' }" @click="mode = 'trace'"><Route :size="14" /> Trace</button>
    </div>

    <div v-if="mode === 'objects'" class="filters">
      <select v-model="objectType" @change="load()" aria-label="对象类型">
        <option v-for="option in typeOptions" :key="option.value" :value="option.value">{{ option.label }}</option>
      </select>
      <select v-model="status" @change="load()" aria-label="状态过滤">
        <option value="">全部状态</option>
        <option value="draft">draft</option>
        <option value="published">published</option>
        <option value="completed">completed</option>
        <option value="archived">archived</option>
        <option value="failed">failed</option>
      </select>
      <div class="search-box"><Search :size="15" /><input v-model="query" placeholder="按标题或能力搜索" @keyup.enter="load()" /></div>
      <button class="icon-action" title="刷新" aria-label="刷新" @click="load()"><RefreshCw :size="16" /></button>
    </div>
    <div v-else class="filters trace-filter">
      <div class="search-box"><Route :size="15" /><input v-model="traceId" placeholder="输入 Trace ID" @keyup.enter="loadTrace" /></div>
      <button class="trace-action" :disabled="loading || !traceId.trim()" @click="loadTrace">{{ loading ? '查询中...' : '查询 Trace' }}</button>
    </div>

    <p v-if="error" class="error-banner"><AlertCircle :size="16" /> {{ friendlyError }}</p>

    <div v-if="mode === 'objects'" class="inspector-grid">
      <div class="object-list">
        <div v-if="!loading && !items.length" class="empty">暂无匹配对象</div>
        <button v-for="item in items" :key="item.id" class="object-row" :class="{ active: selected?.object_id === item.id }" @click="inspect(item)">
          <span class="object-main"><strong>{{ item.title || item.id }}</strong><small>{{ item.id }}</small></span>
          <span class="object-meta"><em>{{ item.status || 'unknown' }}</em><ChevronRight :size="15" /></span>
        </button>
        <button v-if="hasMore" class="load-more" :disabled="loading" @click="load(false)">{{ loading ? '加载中...' : '加载更多' }}</button>
      </div>

      <div class="detail-panel">
        <div v-if="!selected" class="empty detail-empty">选择一个对象查看检查信息</div>
        <template v-else>
          <div class="detail-title"><div><p class="eyebrow">{{ selected.object_type }}</p><h3>{{ selected.title || selected.object_id }}</h3></div><span class="status-pill">{{ selected.status }}</span></div>
          <dl class="facts">
            <div><dt>对象 ID</dt><dd>{{ selected.object_id }}</dd></div>
            <div><dt>所有者</dt><dd>{{ selected.owner_public_id || '未设置' }}</dd></div>
            <div><dt>当前版本</dt><dd>{{ selected.version || '未设置' }}</dd></div>
          </dl>
          <div class="detail-section"><h4>权限上下文</h4><pre>{{ JSON.stringify(selected.permissions, null, 2) }}</pre></div>
          <div class="detail-section"><h4>资源血缘</h4><pre>{{ JSON.stringify(selected.lineage, null, 2) }}</pre></div>
          <div class="detail-section"><h4>关联任务</h4><pre>{{ JSON.stringify(selected.tasks, null, 2) }}</pre></div>
        </template>
      </div>
    </div>

    <div v-else class="trace-panel">
      <div v-if="!traceResult" class="empty trace-empty">输入 Trace ID 查看证据链</div>
      <template v-else>
        <div class="trace-title">
          <div><p class="eyebrow">TRACE BUNDLE</p><h3>{{ traceResult.trace_id }}</h3></div>
          <span class="status-pill">{{ Object.values(traceResult.counts).reduce((sum, value) => sum + value, 0) }} 项证据</span>
        </div>
        <div class="trace-counts">
          <div v-for="(count, key) in traceResult.counts" :key="key"><strong>{{ count }}</strong><span>{{ traceLabels[key] || key }}</span></div>
        </div>
        <section v-for="group in traceGroups" :key="group.key" class="trace-group">
          <h4>{{ group.label }} <span>{{ group.rows.length }}</span></h4>
          <div class="trace-rows">
            <div v-for="row in group.rows" :key="`${group.key}-${row.id}`" class="trace-row">
              <div><strong>{{ row.id }}</strong><small>{{ row.object_type }}</small></div>
              <pre>{{ JSON.stringify(row, null, 2) }}</pre>
            </div>
          </div>
        </section>
      </template>
    </div>
  </section>
</template>

<style scoped>
.inspector-page { max-width: 1240px; margin: 0 auto; color: #27312b; }
.inspector-head, .filters, .detail-title, .object-row { display: flex; align-items: center; }
.inspector-head { justify-content: space-between; margin-bottom: 22px; }
.eyebrow { margin: 0 0 5px; color: #8a958d; font-size: 10px; font-weight: 750; letter-spacing: .13em; text-transform: uppercase; }
h2, h3, h4 { margin: 0; } h2 { font-size: 24px; } h3 { font-size: 17px; } h4 { font-size: 12px; }
.subhead { margin: 6px 0 0; color: #77837a; font-size: 12px; }
.operator-badge, .status-pill { display: inline-flex; align-items: center; gap: 6px; padding: 6px 9px; color: #496454; border: 1px solid #c9ded0; border-radius: 999px; background: #eff8f1; font-size: 11px; }
.mode-switch { display: inline-flex; gap: 3px; margin-bottom: 12px; padding: 3px; border: 1px solid #dce4dd; border-radius: 9px; background: #f4f7f4; }
.mode-switch button { display: flex; height: 30px; align-items: center; gap: 5px; padding: 0 12px; border: 0; border-radius: 6px; background: transparent; color: #718077; font-size: 12px; cursor: pointer; }
.mode-switch button.active { background: #fff; color: #27312b; box-shadow: 0 1px 3px rgba(35,49,41,.08); }
.filters { gap: 8px; margin-bottom: 14px; }
select, .search-box, .icon-action, .load-more, .trace-action { height: 36px; border: 1px solid #dce4dd; border-radius: 10px; background: #fff; color: #445047; font-size: 12px; }
select { padding: 0 10px; } .search-box { display: flex; flex: 1; align-items: center; gap: 7px; max-width: 360px; padding: 0 10px; color: #8a958d; }
.search-box input { width: 100%; border: 0; outline: 0; color: #27312b; font: inherit; } .icon-action { display: grid; width: 36px; place-items: center; cursor: pointer; }
.trace-filter .search-box { max-width: 540px; } .trace-action { padding: 0 14px; background: #273b30; color: #fff; cursor: pointer; } .trace-action:disabled { opacity: .5; cursor: default; }
.error-banner { display: flex; align-items: center; gap: 8px; margin: 0 0 14px; padding: 10px 12px; color: #8a4c45; border: 1px solid #efd0cb; border-radius: 10px; background: #fff5f3; font-size: 12px; }
.inspector-grid { display: grid; grid-template-columns: minmax(280px, .8fr) minmax(0, 1.4fr); gap: 14px; }
.object-list, .detail-panel { min-height: 480px; padding: 10px; border: 1px solid #e1e8e2; border-radius: 14px; background: rgba(255,255,255,.8); }
.object-row { width: 100%; justify-content: space-between; gap: 10px; padding: 12px 10px; border: 0; border-bottom: 1px solid #edf1ed; background: transparent; color: inherit; text-align: left; cursor: pointer; }
.object-row:hover, .object-row.active { background: #f2f7f3; } .object-main { min-width: 0; } .object-main strong, .object-main small { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.object-main strong { font-size: 12px; } .object-main small { margin-top: 4px; color: #96a099; font-size: 10px; } .object-meta { display: flex; align-items: center; gap: 6px; color: #99a39c; }
.object-meta em { padding: 3px 6px; color: #67746b; border-radius: 999px; background: #f1f4f1; font-size: 10px; font-style: normal; }
.load-more { width: 100%; margin-top: 8px; cursor: pointer; } .empty { display: grid; min-height: 120px; place-items: center; color: #98a29a; font-size: 12px; } .detail-empty { min-height: 460px; }
.detail-panel { padding: 18px; } .detail-title { justify-content: space-between; gap: 10px; padding-bottom: 15px; border-bottom: 1px solid #e6ece7; }
.facts { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; margin: 16px 0; } .facts div { min-width: 0; padding: 10px; border-radius: 9px; background: #f5f7f5; }
dt { color: #8b968e; font-size: 10px; } dd { margin: 5px 0 0; overflow: hidden; color: #445047; font-size: 11px; text-overflow: ellipsis; white-space: nowrap; }
.detail-section { margin-top: 15px; } pre { max-height: 170px; margin: 7px 0 0; padding: 10px; overflow: auto; border-radius: 8px; background: #f4f6f4; color: #56635a; font: 11px/1.55 ui-monospace, SFMono-Regular, Consolas, monospace; white-space: pre-wrap; }
.trace-panel { min-height: 480px; padding: 18px; border: 1px solid #e1e8e2; border-radius: 14px; background: rgba(255,255,255,.8); }
.trace-empty { min-height: 440px; } .trace-title { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding-bottom: 15px; border-bottom: 1px solid #e6ece7; }
.trace-title h3 { overflow-wrap: anywhere; } .trace-counts { display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: 8px; margin: 14px 0 20px; }
.trace-counts div { min-width: 0; padding: 10px; border-radius: 8px; background: #f5f7f5; } .trace-counts strong, .trace-counts span { display: block; }
.trace-counts strong { font-size: 18px; } .trace-counts span { margin-top: 3px; overflow: hidden; color: #829087; font-size: 10px; text-overflow: ellipsis; white-space: nowrap; }
.trace-group { margin-top: 18px; } .trace-group h4 span { margin-left: 5px; color: #91a097; font-weight: 500; }
.trace-rows { display: grid; gap: 8px; margin-top: 8px; } .trace-row { display: grid; grid-template-columns: minmax(180px, .6fr) minmax(0, 1.4fr); gap: 12px; padding: 10px; border: 1px solid #e6ece7; border-radius: 8px; }
.trace-row strong, .trace-row small { display: block; overflow-wrap: anywhere; } .trace-row strong { font-size: 11px; } .trace-row small { margin-top: 4px; color: #93a097; font-size: 10px; }
.trace-row pre { max-height: 130px; margin: 0; }
@media (max-width: 760px) { .inspector-grid { grid-template-columns: 1fr; } .filters { flex-wrap: wrap; } .search-box { min-width: 180px; } .facts { grid-template-columns: 1fr; } }
@media (max-width: 900px) { .trace-counts { grid-template-columns: repeat(3, minmax(0, 1fr)); } .trace-row { grid-template-columns: 1fr; } }
</style>
