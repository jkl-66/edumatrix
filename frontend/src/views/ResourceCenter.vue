<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import {
  Archive, ArchiveRestore, Check, Download, FileText, GitCompare,
  LoaderCircle, RefreshCw, Search, X,
} from '@lucide/vue'
import {
  archiveM5Resource, compareM5ResourceVersions, exportM5Resource,
  getM5Resource, listM5Resources,
} from '../api'

const resources = ref([])
const selected = ref(null)
const comparison = ref(null)
const loading = ref(false)
const detailLoading = ref(false)
const actionLoading = ref(false)
const error = ref('')
const query = ref('')
const artifactType = ref('')
const status = ref('')
const includeArchived = ref(false)
const leftVersion = ref(null)
const rightVersion = ref(null)

const versions = computed(() => selected.value?.versions || [])
const currentVersion = computed(() => {
  if (!selected.value) return null
  return versions.value.find(item => item.id === selected.value.current_version_id) || versions.value.at(-1) || null
})
const content = computed(() => currentVersion.value?.content || '')

function detailMessage(err) {
  const detail = err?.response?.data?.detail
  return detail?.message || (typeof detail === 'string' ? detail : '') || err?.message || '请求失败'
}

async function loadResources(keepSelection = false) {
  loading.value = true
  error.value = ''
  try {
    const data = await listM5Resources({
      q: query.value || undefined,
      artifact_type: artifactType.value || undefined,
      status: status.value || undefined,
      include_archived: includeArchived.value,
      limit: 100,
    })
    resources.value = data.items || []
    if (keepSelection && selected.value) {
      const stillVisible = resources.value.find(item => item.id === selected.value.id)
      if (stillVisible) await openResource(stillVisible.id)
      else selected.value = null
    } else if (!selected.value && resources.value.length) {
      await openResource(resources.value[0].id)
    }
  } catch (err) {
    error.value = detailMessage(err)
  } finally {
    loading.value = false
  }
}

async function openResource(id) {
  detailLoading.value = true
  error.value = ''
  comparison.value = null
  try {
    selected.value = await getM5Resource(id)
    const numbers = versions.value.map(item => item.version_number)
    rightVersion.value = numbers.at(-1) ?? null
    leftVersion.value = numbers.length > 1 ? numbers.at(-2) : numbers.at(-1) ?? null
  } catch (err) {
    error.value = detailMessage(err)
  } finally {
    detailLoading.value = false
  }
}

async function compareVersions() {
  if (!selected.value || leftVersion.value == null || rightVersion.value == null) return
  actionLoading.value = true
  error.value = ''
  try {
    comparison.value = await compareM5ResourceVersions(selected.value.id, leftVersion.value, rightVersion.value)
  } catch (err) {
    error.value = detailMessage(err)
  } finally {
    actionLoading.value = false
  }
}

async function downloadResource() {
  if (!selected.value || !currentVersion.value) return
  actionLoading.value = true
  error.value = ''
  try {
    const payload = await exportM5Resource(selected.value.id, currentVersion.value.version_number)
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `${selected.value.title || 'resource'}-v${currentVersion.value.version_number}.json`
    link.click()
    URL.revokeObjectURL(url)
  } catch (err) {
    error.value = detailMessage(err)
  } finally {
    actionLoading.value = false
  }
}

async function toggleArchive() {
  if (!selected.value) return
  const next = !selected.value.archived
  const verb = next ? '归档' : '恢复'
  if (!window.confirm(`确认${verb}“${selected.value.title}”？`)) return
  actionLoading.value = true
  error.value = ''
  try {
    selected.value = await archiveM5Resource(selected.value.id, next, selected.value.lock_version)
    await loadResources(true)
  } catch (err) {
    error.value = detailMessage(err)
  } finally {
    actionLoading.value = false
  }
}

let searchTimer
watch(query, () => {
  window.clearTimeout(searchTimer)
  searchTimer = window.setTimeout(() => loadResources(), 250)
})
watch([artifactType, status, includeArchived], () => loadResources())
onMounted(() => loadResources())
</script>

<template>
  <section class="resource-page">
    <div class="toolbar">
      <div class="search-field">
        <Search :size="15" />
        <input v-model="query" type="search" placeholder="搜索资源标题" aria-label="搜索资源标题" />
        <button v-if="query" title="清除搜索" @click="query = ''"><X :size="14" /></button>
      </div>
      <select v-model="artifactType" aria-label="资源类型">
        <option value="">全部类型</option>
        <option value="lesson">讲义</option>
        <option value="lab_guide">实操指南</option>
        <option value="tiered_quiz">分阶测试</option>
        <option value="interactive_skill_artifact">交互工件</option>
        <option value="m3_matching_report">匹配报告</option>
      </select>
      <select v-model="status" aria-label="资源状态">
        <option value="">全部状态</option>
        <option value="draft">草稿</option>
        <option value="reviewing">审核中</option>
        <option value="approved">已批准</option>
        <option value="published">已发布</option>
      </select>
      <label class="archive-toggle"><input v-model="includeArchived" type="checkbox" />显示归档</label>
      <button class="icon-button" title="刷新" :disabled="loading" @click="loadResources(true)">
        <RefreshCw :size="15" :class="{ spin: loading }" />
      </button>
    </div>

    <div v-if="error" class="error-banner"><X :size="15" />{{ error }}</div>

    <div class="workspace">
      <aside class="resource-list" aria-label="资源列表">
        <div class="list-heading"><strong>资源</strong><span>{{ resources.length }}</span></div>
        <div v-if="loading && !resources.length" class="empty"><LoaderCircle :size="18" class="spin" /></div>
        <button
          v-for="item in resources" :key="item.id"
          class="resource-row" :class="{ active: selected?.id === item.id }"
          @click="openResource(item.id)"
        >
          <FileText :size="16" />
          <span><strong>{{ item.title }}</strong><small>{{ item.artifact_type }} · {{ item.status }}</small></span>
          <Archive v-if="item.archived" :size="13" />
        </button>
        <div v-if="!loading && !resources.length" class="empty">暂无资源</div>
      </aside>

      <div class="detail-panel">
        <div v-if="detailLoading" class="empty"><LoaderCircle :size="20" class="spin" /></div>
        <div v-else-if="!selected" class="empty">选择一个资源</div>
        <template v-else>
          <header class="detail-head">
            <div><p>{{ selected.artifact_type }}</p><h2>{{ selected.title }}</h2></div>
            <div class="detail-actions">
              <button title="导出当前版本" :disabled="actionLoading" @click="downloadResource"><Download :size="15" /></button>
              <button :title="selected.archived ? '恢复资源' : '归档资源'" :disabled="actionLoading" @click="toggleArchive">
                <ArchiveRestore v-if="selected.archived" :size="15" /><Archive v-else :size="15" />
              </button>
            </div>
          </header>

          <dl class="facts">
            <div><dt>状态</dt><dd>{{ selected.status }}</dd></div>
            <div><dt>版本</dt><dd>{{ currentVersion?.version_number || '-' }}</dd></div>
            <div><dt>格式</dt><dd>{{ currentVersion?.content_format || '-' }}</dd></div>
            <div><dt>课程</dt><dd>{{ selected.course_id || '未绑定' }}</dd></div>
          </dl>

          <div class="version-tools">
            <select v-model="leftVersion" aria-label="左侧版本"><option v-for="item in versions" :key="item.id" :value="item.version_number">v{{ item.version_number }}</option></select>
            <GitCompare :size="15" />
            <select v-model="rightVersion" aria-label="右侧版本"><option v-for="item in versions" :key="item.id" :value="item.version_number">v{{ item.version_number }}</option></select>
            <button :disabled="actionLoading || versions.length < 2" @click="compareVersions"><Check :size="14" />对比</button>
          </div>

          <pre v-if="comparison" class="content-view diff-view">{{ comparison.diff || '两个版本内容一致' }}</pre>
          <pre v-else class="content-view">{{ content }}</pre>
        </template>
      </div>
    </div>
  </section>
</template>

<style scoped>
.resource-page { max-width: 1320px; margin: 0 auto; color: #27312b; }
.toolbar { display: flex; align-items: center; gap: 8px; margin-bottom: 12px; }
.search-field { display: flex; width: min(380px, 100%); height: 36px; align-items: center; gap: 8px; padding: 0 10px; border: 1px solid #dbe3dc; border-radius: 8px; background: #fff; color: #829087; }
.search-field input { min-width: 0; flex: 1; border: 0; outline: 0; color: #27312b; font-size: 12px; }
.search-field button, .icon-button, .detail-actions button { display: grid; width: 32px; height: 32px; place-items: center; border: 0; background: transparent; color: #68766c; cursor: pointer; }
select { height: 36px; padding: 0 9px; border: 1px solid #dbe3dc; border-radius: 8px; background: #fff; color: #4f5d53; font-size: 12px; }
.archive-toggle { display: flex; height: 36px; align-items: center; gap: 6px; padding: 0 9px; border: 1px solid #dbe3dc; border-radius: 8px; background: #fff; color: #58665c; font-size: 11px; white-space: nowrap; }
.icon-button { flex: 0 0 36px; width: 36px; height: 36px; border: 1px solid #dbe3dc; border-radius: 8px; background: #fff; }
.error-banner { display: flex; align-items: center; gap: 7px; margin-bottom: 12px; padding: 9px 11px; border: 1px solid #edcbc6; border-radius: 8px; background: #fff5f3; color: #934d45; font-size: 12px; }
.workspace { display: grid; min-height: 620px; grid-template-columns: minmax(250px, 320px) minmax(0, 1fr); gap: 12px; }
.resource-list, .detail-panel { overflow: hidden; border: 1px solid #dde5de; border-radius: 8px; background: rgba(255,255,255,.86); }
.resource-list { min-height: 620px; }
.list-heading { display: flex; height: 44px; align-items: center; justify-content: space-between; padding: 0 12px; border-bottom: 1px solid #e5ebe6; font-size: 12px; }
.list-heading span { color: #8a968d; }
.resource-row { display: grid; width: 100%; min-height: 58px; grid-template-columns: 20px minmax(0, 1fr) 16px; align-items: center; gap: 8px; padding: 9px 12px; border: 0; border-bottom: 1px solid #edf1ed; background: transparent; color: #647168; text-align: left; cursor: pointer; }
.resource-row:hover, .resource-row.active { background: #f0f6f1; color: #34523f; }
.resource-row span, .resource-row strong, .resource-row small { display: block; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.resource-row strong { color: #303a33; font-size: 12px; }
.resource-row small { margin-top: 4px; color: #8d9990; font-size: 10px; }
.detail-panel { min-height: 620px; padding: 18px; }
.detail-head { display: flex; min-height: 54px; align-items: flex-start; justify-content: space-between; gap: 12px; padding-bottom: 14px; border-bottom: 1px solid #e4eae5; }
.detail-head p { margin: 0 0 5px; color: #87938a; font-size: 10px; text-transform: uppercase; }
.detail-head h2 { margin: 0; font-size: 19px; line-height: 1.3; overflow-wrap: anywhere; }
.detail-actions { display: flex; gap: 4px; }
.detail-actions button { border: 1px solid #dbe3dc; border-radius: 8px; background: #fff; }
.facts { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 8px; margin: 14px 0; }
.facts div { min-width: 0; padding: 9px; border-radius: 8px; background: #f4f7f4; }
.facts dt { color: #89958c; font-size: 10px; }.facts dd { margin: 4px 0 0; overflow: hidden; color: #3f4d43; font-size: 11px; text-overflow: ellipsis; white-space: nowrap; }
.version-tools { display: flex; height: 38px; align-items: center; gap: 7px; margin-bottom: 10px; }
.version-tools select { height: 32px; }.version-tools button { display: flex; height: 32px; align-items: center; gap: 5px; padding: 0 10px; border: 1px solid #bfd4c4; border-radius: 8px; background: #edf7ef; color: #355d42; font-size: 11px; cursor: pointer; }
.version-tools button:disabled, .detail-actions button:disabled { opacity: .45; cursor: default; }
.content-view { height: 390px; margin: 0; padding: 14px; overflow: auto; border: 1px solid #e2e8e3; border-radius: 8px; background: #f7f9f7; color: #455248; font: 11px/1.65 ui-monospace, SFMono-Regular, Consolas, monospace; white-space: pre-wrap; overflow-wrap: anywhere; }
.diff-view { color: #354e3e; background: #f5f8f5; }
.empty { display: grid; min-height: 180px; place-items: center; color: #909c93; font-size: 12px; }
.spin { animation: spin .8s linear infinite; } @keyframes spin { to { transform: rotate(360deg); } }
@media (max-width: 820px) { .toolbar { flex-wrap: wrap; }.search-field { width: 100%; }.workspace { grid-template-columns: 1fr; }.resource-list { min-height: 240px; max-height: 320px; overflow-y: auto; }.facts { grid-template-columns: repeat(2, minmax(0, 1fr)); }.content-view { height: 340px; } }
@media (max-width: 480px) { .archive-toggle { flex: 1; }.detail-panel { padding: 12px; }.facts { grid-template-columns: 1fr 1fr; }.version-tools { flex-wrap: wrap; height: auto; }.content-view { height: 300px; } }
</style>
