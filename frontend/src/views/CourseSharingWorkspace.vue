<script setup>
import { computed, onMounted, ref } from 'vue'
import { AlertTriangle, ArrowDownToLine, GitCompareArrows, RefreshCw, Share2, ShieldCheck } from '@lucide/vue'
import { createCourseCopy, decideCourseUpdate, getCourseSharingWorkspace, propagateCourseWithdrawals, publishCourseShare } from '../api/courseSharing'

const data = ref(null), busy = ref(''), error = ref(''), selected = ref(null)
const form = ref({ course_id: '', target_type: 'class', target_id: '', title: '课程共享发布版' })
const reason = ref('已核对来源、许可证继承和本地冲突，确认本次处理决定')
const targets = computed(() => form.value.target_type === 'class' ? data.value?.manageable_classes || [] : data.value?.manageable_organizations || [])

function message(e) { return e?.detail?.message || e?.detail || e?.message || '操作失败' }
function syncDefaults() {
  if (!form.value.course_id) form.value.course_id = data.value?.manageable_courses?.[0]?.id || ''
  if (!targets.value.some(x => x.id === form.value.target_id)) form.value.target_id = targets.value[0]?.id || ''
}
async function load() {
  busy.value = 'load'; error.value = ''
  try {
    data.value = await getCourseSharingWorkspace(); syncDefaults()
    selected.value = data.value.copies.find(x => x.id === selected.value?.id) || data.value.copies[0] || null
  } catch (e) { error.value = message(e) } finally { busy.value = '' }
}
async function publish() {
  busy.value = 'publish'; error.value = ''
  try { await publishCourseShare(form.value); await load() } catch (e) { error.value = message(e); busy.value = '' }
}
async function derive(release) {
  busy.value = `copy:${release.id}`; error.value = ''
  try { selected.value = await createCourseCopy(release.id); await load() } catch (e) { error.value = message(e); busy.value = '' }
}
async function decide(action) {
  const upstream = selected.value?.update_preview?.release
  if (!upstream) return
  busy.value = action; error.value = ''
  try {
    selected.value = await decideCourseUpdate(selected.value.id, { upstream_release_id: upstream.id, action, reason: reason.value, expected_version: selected.value.lock_version })
    await load()
  } catch (e) { error.value = message(e); busy.value = '' }
}
async function propagate() {
  busy.value = 'propagate'; error.value = ''
  try { await propagateCourseWithdrawals(); await load() } catch (e) { error.value = message(e); busy.value = '' }
}
onMounted(load)
</script>

<template>
  <main class="sharing-page">
    <header><div><p>COURSE ECOSYSTEM</p><h2>课程分享与上游更新</h2><span>发布不可变快照，接收方持有独立派生副本并显式处理更新</span></div><button class="icon" title="刷新课程分享" aria-label="刷新课程分享" @click="load"><RefreshCw :size="16" /></button></header>
    <div class="truth"><ShieldCheck :size="18" /><div><strong>{{ data?.truth_label || '不可变发布快照 · 派生副本 · 显式更新决定' }}</strong><span>{{ data?.disclaimer }}</span></div></div>
    <p v-if="error" class="error"><AlertTriangle :size="15" />{{ error }}</p>

    <section class="publisher">
      <div><h3>发布课程副本</h3><span>只允许发布本人可管理的已发布课程，并冻结正文、来源、哈希和许可证。</span></div>
      <select v-model="form.course_id" aria-label="待分享课程"><option v-for="x in data?.manageable_courses || []" :key="x.id" :value="x.id">{{ x.title }} · {{ x.version }}</option></select>
      <div class="segments" aria-label="分享范围"><button :class="{ active: form.target_type === 'class' }" @click="form.target_type='class';syncDefaults()">教学班</button><button :class="{ active: form.target_type === 'organization' }" @click="form.target_type='organization';syncDefaults()">组织</button></div>
      <select v-model="form.target_id" aria-label="分享目标"><option v-for="x in targets" :key="x.id" :value="x.id">{{ x.title || x.name }}</option></select>
      <input v-model="form.title" aria-label="发布标题" />
      <button class="primary" :disabled="Boolean(busy) || !form.course_id || !form.target_id" @click="publish"><Share2 :size="15" />发布不可变快照</button>
    </section>

    <div class="toolbar"><button :disabled="Boolean(busy)" @click="propagate">同步上游撤回状态</button><span>撤回只改变上游状态，不删除已创建的派生课程或历史证据。</span></div>
    <section class="layout">
      <aside><h3>可接收发布</h3><article v-for="x in data?.releases || []" :key="x.id"><div><strong>{{ x.title }}</strong><span>{{ x.source_course_version }} · {{ x.target_type }} · {{ x.status }}</span></div><small>{{ x.snapshot_hash }}</small><button :disabled="Boolean(busy) || x.status !== 'published'" title="创建派生副本" @click="derive(x)"><ArrowDownToLine :size="14" />创建副本</button></article><p v-if="!data?.releases?.length">当前范围暂无共享课程</p></aside>
      <div class="copies"><nav><button v-for="x in data?.copies || []" :key="x.id" :class="{ active: selected?.id === x.id }" @click="selected=x"><strong>{{ x.derived_course.title }}</strong><span>{{ x.derived_course.version }} · {{ x.upstream_status }}</span></button></nav>
        <div v-if="selected" class="detail">
          <div class="title"><div><h3>{{ selected.derived_course.title }}</h3><span>{{ selected.derived_course.id }}</span></div><em>{{ selected.upstream_status }}</em></div>
          <div class="facts"><article><span>当前版本</span><strong>{{ selected.derived_course.version }}</strong></article><article><span>可见范围</span><strong>{{ selected.derived_course.visibility }}</strong></article><article><span>基线哈希</span><strong>{{ selected.baseline_hash.slice(0, 12) }}</strong></article></div>
          <section class="license"><h3>许可证继承</h3><p>{{ selected.derived_course.license_text || '来源未提供许可证文本' }}</p><small>许可证文本按发布快照原样继承，不代表系统给出法律兼容性意见。</small></section>
          <template v-if="selected.update_preview">
            <div class="update-title"><GitCompareArrows :size="17" /><div><strong>发现上游 {{ selected.update_preview.release.source_course_version }}</strong><span>上游变更 {{ Object.keys(selected.update_preview.upstream_changes).length }} 项 · 本地变更 {{ Object.keys(selected.update_preview.local_changes).length }} 项 · 冲突 {{ selected.update_preview.conflict_count }} 项</span></div></div>
            <div class="conflicts"><span v-for="x in selected.update_preview.conflicts" :key="x">{{ x }}</span><em v-if="!selected.update_preview.conflicts.length">没有字段级冲突</em></div>
            <div v-if="selected.update_preview.decision" class="decision"><strong>已决定 {{ selected.update_preview.decision.action }}</strong><span>{{ selected.update_preview.decision.reason }}</span></div>
            <div v-else class="actions"><input v-model="reason" aria-label="更新处理理由" /><button :disabled="Boolean(busy)" @click="decide('ignore')">忽略此版本</button><button class="primary" :disabled="Boolean(busy) || selected.update_preview.release.status !== 'published'" @click="decide('accept')">接受并保留审计</button></div>
          </template>
          <div v-else class="current">当前没有待处理的上游更新</div>
        </div><div v-else class="empty">选择共享发布创建派生课程</div>
      </div>
    </section>
  </main>
</template>

<style scoped>
.sharing-page{max-width:1200px;margin:0 auto;color:#26352d}header,.truth,.publisher,.toolbar,.title,.update-title,.actions{display:flex;align-items:center}header{justify-content:space-between}header p{margin:0;color:#78877e;font-size:10px;font-weight:800;letter-spacing:.12em}h2{margin:4px 0;font-size:24px}header span,.truth span,.publisher span,.toolbar span,.title span,.update-title span,.decision span{display:block;color:#718078;font-size:10px}.icon{display:grid;width:36px;height:36px;place-items:center;border:1px solid #dce6df;border-radius:7px;background:#fff}.truth{gap:9px;margin:14px 0;padding:11px;border-left:3px solid #3d7760;background:#eef6f1}.truth strong{font-size:11px}.publisher{display:grid;grid-template-columns:minmax(190px,1.3fr) 1fr auto 1fr 1fr auto;gap:8px;align-items:end;padding:12px;border:1px solid #dfe8e1;background:#fff}.publisher h3{margin:0 0 4px;font-size:13px}.publisher select,.publisher input,.actions input{min-width:0;padding:9px;border:1px solid #d8e3db;border-radius:6px;background:#fff}.segments{display:flex;height:34px;border:1px solid #d8e3db;border-radius:6px;overflow:hidden}.segments button{border:0;background:#fff;color:#596a60}.segments button.active{background:#304b3d;color:#fff}.primary,.toolbar button,aside article button,.actions button{display:flex;align-items:center;justify-content:center;gap:5px;padding:9px;border:0;border-radius:6px;background:#304b3d;color:#fff}.primary:disabled,.toolbar button:disabled,aside button:disabled,.actions button:disabled{opacity:.45}.toolbar{gap:10px;margin:10px 0}.layout{display:grid;grid-template-columns:310px minmax(0,1fr);gap:10px}aside,.copies,.detail,.empty{border:1px solid #dfe8e1;background:#fff}aside{padding:12px}aside h3{margin:0 0 8px;font-size:12px}aside article{padding:10px 0;border-top:1px solid #e6ede8}aside strong,aside span,aside small{display:block}aside strong{font-size:11px}aside span{font-size:9px;color:#748178}aside small{margin:6px 0;overflow-wrap:anywhere;color:#879289;font-size:8px}aside article button{padding:7px;font-size:9px}.copies{display:grid;grid-template-columns:210px minmax(0,1fr);min-height:390px}.copies nav{border-right:1px solid #e1e9e3}.copies nav button{display:block;width:100%;padding:11px;border:0;border-bottom:1px solid #e7eee9;background:#fff;text-align:left}.copies nav button.active{background:#edf4ef}.copies nav strong,.copies nav span{display:block;font-size:10px}.copies nav span{color:#748078}.detail{padding:13px;border:0}.title{justify-content:space-between}.title h3{margin:0;font-size:14px}.title span{overflow-wrap:anywhere}.title em{padding:5px 8px;background:#eaf3ed;font-size:9px;font-style:normal}.facts{display:grid;grid-template-columns:repeat(3,1fr);gap:7px;margin:11px 0}.facts article{padding:10px;background:#f4f7f5}.facts span,.facts strong{display:block;font-size:9px}.facts strong{margin-top:3px}.license{padding:10px;border-left:3px solid #c7a45c;background:#fff8ec}.license h3,.license p{margin:0 0 5px;font-size:11px}.license small{color:#7d715d;font-size:9px}.update-title{gap:8px;margin-top:12px;padding:10px;background:#eef4f0}.conflicts{display:flex;flex-wrap:wrap;gap:5px;padding:8px 0}.conflicts span{padding:4px 7px;border:1px solid #d8a99e;background:#fff0ec;color:#874b40;font-size:9px}.conflicts em{color:#65766b;font-size:9px}.actions{gap:7px}.actions input{flex:1}.decision,.current,.empty{padding:12px;color:#64736a;font-size:10px}.decision{background:#edf5ef}.decision strong,.decision span{display:block}.empty{display:grid;place-items:center}.error{display:flex;gap:6px;padding:8px;background:#fff0ed;color:#984e42;font-size:10px}@media(max-width:900px){.publisher{grid-template-columns:1fr 1fr}.layout{grid-template-columns:1fr}.copies{grid-template-columns:1fr}.copies nav{border-right:0;border-bottom:1px solid #e1e9e3}}@media(max-width:600px){.publisher,.facts{grid-template-columns:1fr}.actions,.toolbar{align-items:stretch;flex-direction:column}.copies{min-width:0}.detail{overflow:hidden}.title{align-items:flex-start;gap:6px}.publisher .primary{width:100%}}
</style>
