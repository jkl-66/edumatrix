<script setup>
import { computed, onMounted, ref } from 'vue'
import { AlertTriangle, ArrowDownToLine, FileDiff, GitFork, History, RefreshCw, Save, ShieldCheck } from '@lucide/vue'
import { createMarketplaceFork, createMarketplaceForkVersion, decideMarketplaceForkUpdate, getMarketplaceForks } from '../api/marketplace'

const data = ref(null)
const selectedId = ref('')
const busy = ref('')
const error = ref('')
const notice = ref('')
const summary = ref('建立正式分叉并保留来源与许可证')
const edit = ref({ title: '', description: '' })
const selected = computed(() => data.value?.forks?.find(item => item.id === selectedId.value) || data.value?.forks?.[0] || null)
const available = computed(() => data.value?.acquisitions?.filter(item => !item.has_fork) || [])
const localChanges = computed(() => Object.entries(selected.value?.update_preview?.local_changes || {}))
const upstreamChanges = computed(() => Object.entries(selected.value?.update_preview?.upstream_changes || {}))

function message(exc) { return exc?.detail?.message || exc?.detail || exc?.message || '操作失败' }
function syncEdit() {
  const course = selected.value?.current_version?.course || {}
  edit.value = { title: course.title || '', description: course.description || '' }
}
async function load(preferred = selectedId.value) {
  busy.value = 'load'; error.value = ''
  try {
    data.value = await getMarketplaceForks()
    selectedId.value = data.value.forks.some(item => item.id === preferred) ? preferred : (data.value.forks[0]?.id || '')
    syncEdit()
  } catch (exc) { error.value = message(exc) } finally { busy.value = '' }
}
async function createFork(item) {
  busy.value = 'create'; error.value = ''
  try {
    const fork = await createMarketplaceFork(item.listing_id, { modification_summary: summary.value })
    notice.value = '正式分叉已建立，来源、许可证与 v1 快照已冻结'
    await load(fork.id)
  } catch (exc) { error.value = message(exc) } finally { busy.value = '' }
}
async function saveVersion() {
  if (!selected.value) return
  busy.value = 'version'; error.value = ''
  try {
    await createMarketplaceForkVersion(selected.value.id, {
      expected_version: selected.value.lock_version,
      modification_summary: summary.value,
      patch: { course: { title: edit.value.title, description: edit.value.description } },
    })
    notice.value = '本地修改已冻结为新的不可变分叉版本'
    await load(selected.value.id)
  } catch (exc) { error.value = message(exc) } finally { busy.value = '' }
}
async function decide(action) {
  const preview = selected.value?.update_preview
  if (!preview) return
  busy.value = action; error.value = ''
  try {
    await decideMarketplaceForkUpdate(selected.value.id, {
      upstream_listing_id: preview.upstream_listing.id,
      action,
      reason: summary.value,
      expected_version: selected.value.lock_version,
    })
    notice.value = action === 'accept_non_conflicting' ? '无冲突上游修改已合并，冲突字段保留本地值' : action === 'keep_local' ? '已切换新上游基线并保留全部本地内容' : '已忽略本次上游更新'
    await load(selected.value.id)
  } catch (exc) { error.value = message(exc) } finally { busy.value = '' }
}
function selectFork(id) { selectedId.value = id; syncEdit() }
onMounted(load)
</script>

<template>
  <main class="fork-page" data-testid="marketplace-fork-workspace">
    <header class="page-head">
      <div><p>MARKETPLACE VERSION FORKS</p><h2>资源分叉与上游更新</h2><span>将已获取课程修改为独立版本线，三方差异由服务端计算</span></div>
      <button class="icon" aria-label="刷新资源分叉" @click="load()"><RefreshCw :size="16" /></button>
    </header>
    <section class="truth"><ShieldCheck :size="18"/><div><strong>{{ data?.truth_label || '正式资源分叉 · 独立不可变版本线 · 三方差异' }}</strong><span>{{ data?.boundary }}</span></div></section>
    <p v-if="error" class="error"><AlertTriangle :size="15"/>{{ error }}</p>
    <p v-if="notice" class="notice">{{ notice }}</p>

    <section v-if="available.length" class="acquisitions">
      <h3>可建立分叉的市场副本</h3>
      <article v-for="item in available" :key="item.id">
        <div><strong>{{ item.listing.title }}</strong><span>课程 v{{ item.listing.course_version }} · {{ item.listing.snapshot_hash.slice(0, 12) }}</span><small>{{ item.listing.license.course_license || '未记录许可证' }}</small></div>
        <button :disabled="Boolean(busy)" @click="createFork(item)"><GitFork :size="15"/>建立正式分叉</button>
      </article>
    </section>

    <section v-if="data?.forks?.length" class="workspace">
      <aside>
        <h3>我的分叉</h3>
        <button v-for="item in data.forks" :key="item.id" :class="{ active: selected?.id === item.id }" @click="selectFork(item.id)">
          <strong>{{ item.current_version.course.title }}</strong>
          <span>fork v{{ item.current_version.version_number }} · {{ item.upstream_status }}</span>
        </button>
      </aside>
      <div v-if="selected" class="detail">
        <div class="fork-title"><div><h3>{{ selected.current_version.course.title }}</h3><span>{{ selected.derived_course_id }}</span></div><em>{{ selected.upstream_status }}</em></div>
        <div class="hashes"><span>基线 {{ selected.baseline_hash.slice(0, 12) }}</span><span>本地 {{ selected.current_version.local_snapshot_hash.slice(0, 12) }}</span><span>锁版本 {{ selected.lock_version }}</span></div>
        <p class="boundary">{{ selected.boundary }}</p>
        <label>修改摘要<input v-model="summary" aria-label="分叉修改摘要" /></label>
        <div class="edit-grid"><label>课程标题<input v-model="edit.title" aria-label="分叉课程标题" /></label><label>课程说明<textarea v-model="edit.description" aria-label="分叉课程说明" /></label></div>
        <button class="primary" :disabled="Boolean(busy)" @click="saveVersion"><Save :size="15"/>冻结新版本</button>

        <section v-if="selected.update_preview && !selected.update_preview.decision" class="diff" data-testid="fork-three-way-diff">
          <div class="diff-head"><div><FileDiff :size="17"/><h3>上游 v{{ selected.update_preview.upstream_listing.course_version }} 三方差异</h3></div><strong>冲突 {{ selected.update_preview.conflict_count }}</strong></div>
          <div class="three-way"><article><b>基线</b><code>{{ selected.update_preview.baseline_snapshot_hash.slice(0, 16) }}</code></article><article><b>本地</b><code>{{ selected.update_preview.local_snapshot_hash.slice(0, 16) }}</code><small>{{ localChanges.length }} 项修改</small></article><article><b>上游</b><code>{{ selected.update_preview.upstream_snapshot_hash.slice(0, 16) }}</code><small>{{ upstreamChanges.length }} 项修改</small></article></div>
          <div v-if="selected.update_preview.conflicts.length" class="conflicts"><strong>需显式保留的冲突字段</strong><span v-for="path in selected.update_preview.conflicts" :key="path">{{ path }}</span></div>
          <details><summary>本地差异 {{ localChanges.length }}</summary><span v-for="([path]) in localChanges" :key="path">{{ path }}</span></details>
          <details><summary>上游差异 {{ upstreamChanges.length }}</summary><span v-for="([path]) in upstreamChanges" :key="path">{{ path }}</span></details>
          <div class="decision-actions"><button @click="decide('accept_non_conflicting')"><ArrowDownToLine :size="14"/>合并无冲突项</button><button @click="decide('keep_local')">保留全部本地</button><button class="quiet" @click="decide('ignore')">忽略本次更新</button></div>
        </section>
        <section v-else class="current"><ShieldCheck :size="16"/><span>{{ selected.update_preview?.decision ? `上游版本已处理：${selected.update_preview.decision.action}` : '当前没有待处理的上游版本' }}</span></section>

        <section class="history"><h3><History :size="16"/>独立版本历史</h3><article v-for="version in selected.versions" :key="version.id"><strong>fork v{{ version.version_number }}</strong><span>{{ version.modification_summary }}</span><small>{{ version.local_snapshot_hash }} · {{ version.inherited_license.course_license || '未记录许可证' }}</small></article></section>
      </div>
    </section>
    <section v-else-if="!available.length && !busy" class="empty"><GitFork :size="22"/><strong>尚无可分叉资源</strong><span>请先从公共学习市场获取一个课程副本。</span></section>
  </main>
</template>

<style scoped>
.fork-page{max-width:1180px;margin:0 auto;color:#26342c}.page-head,.truth,.fork-title,.diff-head,.diff-head>div,.current,.history h3{display:flex;align-items:center}.page-head,.fork-title,.diff-head{justify-content:space-between}.page-head p{margin:0;color:#75837a;font-size:10px;font-weight:800;letter-spacing:.12em}.page-head h2{margin:4px 0;font-size:24px}.page-head span,.truth span{display:block;color:#718078;font-size:10px}.icon{display:grid;width:36px;height:36px;place-items:center;border:1px solid #dce5de;border-radius:7px;background:#fff}.truth{gap:9px;margin:14px 0;padding:11px;border-left:3px solid #3a715b;background:#eef6f1}.truth strong{font-size:11px}.error,.notice{padding:9px;font-size:10px}.error{display:flex;gap:6px;background:#fff0ed;color:#984d42}.notice{background:#edf5ef;color:#365845}.acquisitions,.workspace,.empty{border:1px solid #dde6df;background:#fff}.acquisitions{padding:12px;margin-bottom:10px}.acquisitions h3,aside h3,.detail h3{margin:0;font-size:12px}.acquisitions article{display:flex;align-items:center;justify-content:space-between;gap:10px;padding:9px;border-top:1px solid #e5ece7}.acquisitions article strong,.acquisitions article span,.acquisitions article small{display:block;font-size:9px}.acquisitions button,.primary,.decision-actions button{display:flex;align-items:center;justify-content:center;gap:5px;padding:9px;border:0;border-radius:6px;background:#304b3d;color:#fff}.workspace{display:grid;grid-template-columns:250px minmax(0,1fr)}aside{border-right:1px solid #dde6df;padding:12px}aside>button{display:block;width:100%;padding:10px;border:0;border-bottom:1px solid #e5ece7;background:#fff;text-align:left}aside>button.active{background:#edf4ef}aside strong,aside span{display:block;font-size:9px}.detail{padding:14px;min-width:0}.fork-title span{font-size:8px;color:#738078;overflow-wrap:anywhere}.fork-title em{padding:4px 7px;background:#edf4ef;font-size:8px;font-style:normal}.hashes{display:flex;flex-wrap:wrap;gap:6px;margin:9px 0}.hashes span{padding:5px 7px;background:#f1f5f2;font-size:8px}.boundary{padding:8px;border-left:3px solid #c8a45c;background:#fff8ec;font-size:9px}.detail label{display:block;font-size:9px}.detail input,.detail textarea{display:block;width:100%;box-sizing:border-box;margin-top:4px;padding:9px;border:1px solid #d7e0da;border-radius:5px}.detail textarea{min-height:70px;resize:vertical}.edit-grid{display:grid;grid-template-columns:1fr 1.5fr;gap:8px;margin:9px 0}.diff{margin-top:14px;padding:12px;border:1px solid #d8e3db;background:#fbfcfb}.diff-head>div{gap:6px}.diff-head strong{font-size:9px;color:#945340}.three-way{display:grid;grid-template-columns:repeat(3,1fr);gap:6px;margin:9px 0}.three-way article{padding:9px;background:#eef3ef}.three-way b,.three-way code,.three-way small{display:block;font-size:8px}.three-way code{margin:4px 0;overflow-wrap:anywhere}.conflicts{padding:9px;background:#fff0ed}.conflicts strong,.conflicts span,.diff details span{display:block;font-size:9px}.conflicts span,.diff details span{margin-top:4px;font-family:monospace}.diff details{margin-top:6px;padding:7px;border:1px solid #e0e7e2;font-size:9px}.decision-actions{display:flex;flex-wrap:wrap;gap:6px;margin-top:9px}.decision-actions .quiet{background:#6f7772}.current{gap:7px;margin-top:14px;padding:10px;background:#edf5ef;font-size:10px}.history{margin-top:14px}.history h3{gap:6px}.history article{padding:9px;border-top:1px solid #e2e9e4}.history strong,.history span,.history small{display:block;font-size:9px}.history small{margin-top:4px;overflow-wrap:anywhere;color:#748078}.empty{display:grid;gap:6px;padding:30px;place-items:center;text-align:center}.empty strong{font-size:12px}.empty span{font-size:10px;color:#748078}@media(max-width:800px){.workspace{grid-template-columns:1fr}aside{border-right:0;border-bottom:1px solid #dde6df}.edit-grid{grid-template-columns:1fr}}@media(max-width:600px){.acquisitions article{align-items:stretch;flex-direction:column}.three-way{grid-template-columns:1fr}.decision-actions{align-items:stretch;flex-direction:column}.hashes{align-items:stretch;flex-direction:column}.primary{width:100%}}
</style>
