<script setup>
import { displayLabel, referenceTitle, learningText } from '../utils/learningCopy.js'
import { userMessage } from '../services/errorTranslator.js'
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { AlertTriangle, ArrowDownToLine, GitCompareArrows, RefreshCw, Share2, ShieldCheck } from '@lucide/vue'
import { createCourseCopy, decideCourseUpdate, getCourseSharingWorkspace, propagateCourseWithdrawals, publishCourseShare } from '../api/courseSharing'

const data = ref(null), busy = ref(''), error = ref(''), selected = ref(null)
const router = useRouter()
const form = ref({ course_id: '', target_type: 'class', target_id: '', title: '课程共享发布版' })
const reason = ref('已核对来源、许可证继承和本地冲突，确认本次处理决定')
const targets = computed(() => form.value.target_type === 'class' ? data.value?.manageable_classes || [] : data.value?.manageable_organizations || [])
function changeLabel(path) {
  const labels = { 'course.title':'课程名称', 'course.description':'课程说明', 'course.subject':'学习方向', 'course.version':'课程版本', 'course.language':'资料语言', 'course.content_origin':'来源说明', 'course.manifest_version':'课程结构', 'course.manifest_data':'课程结构', 'course.domain_pack':'课程方向' }
  return labels[path] || String(path).replace(/^documents\./, '资料：').replace(/^sources\./, '来源说明：')
}

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
    <header><div><p>共享学习资料</p><h2>课程分享与上游更新</h2><span>分享当前课程版本，接收者保留自己的副本，并自行选择是否更新</span></div><button class="icon" title="刷新课程分享" aria-label="刷新课程分享" @click="load"><RefreshCw :size="16" /></button></header>
    <div class="truth"><ShieldCheck :size="18" /><div><strong>保留自己的课程副本</strong><span>老师更新课程后，你可以先查看变化，再决定是否使用新版本。</span></div></div>
    <p v-if="error" class="error"><AlertTriangle :size="15" />{{ userMessage(error) }}</p>

    <section v-if="data?.manageable_courses?.length" class="publisher">
      <div><h3>发布课程副本</h3><span>选择你有管理权限的已发布课程，分享时会保留正文、来源和使用许可。</span></div>
      <select v-model="form.course_id" aria-label="待分享课程"><option v-for="x in data?.manageable_courses || []" :key="x.id" :value="x.id">{{ x.title }} · {{ x.version }}</option></select>
      <div class="segments" aria-label="分享范围"><button :class="{ active: form.target_type === 'class' }" @click="form.target_type='class';syncDefaults()">教学班</button><button :class="{ active: form.target_type === 'organization' }" @click="form.target_type='organization';syncDefaults()">组织</button></div>
      <select v-model="form.target_id" aria-label="分享目标"><option v-for="x in targets" :key="x.id" :value="x.id">{{ x.title || x.name }}</option></select>
      <input v-model="form.title" aria-label="发布标题" />
      <button class="primary" :disabled="Boolean(busy) || !form.course_id || !form.target_id" @click="publish"><Share2 :size="15" />分享当前课程版本</button>
    </section>

    <div v-if="data?.manageable_courses?.length" class="toolbar"><button :disabled="Boolean(busy)" @click="propagate">检查课程是否停止分享</button><span>课程停止分享后，已保存的副本和学习记录仍会保留。</span></div>
    <section class="layout">
      <aside><h3>可接收发布</h3><article v-for="x in data?.releases || []" :key="x.id"><div><strong>{{ x.title }}</strong><span>{{ x.source_course_version }} · {{ x.target_type === 'class' ? '教学班' : '组织' }} · {{ displayLabel(x.status) }}</span></div><small>{{ referenceTitle(x) }}</small><button :disabled="Boolean(busy) || x.status !== 'published'" title="保存课程副本" @click="derive(x)"><ArrowDownToLine :size="14" />创建副本</button></article><p v-if="!data?.releases?.length">当前范围暂无共享课程</p></aside>
      <div class="copies"><nav><button v-for="x in data?.copies || []" :key="x.id" :class="{ active: selected?.id === x.id }" @click="selected=x"><strong>{{ x.derived_course.title }}</strong><span>{{ x.derived_course.version }} · {{ displayLabel(x.upstream_status) }}</span></button></nav>
        <div v-if="selected" class="detail">
          <div class="title"><div><h3>{{ selected.derived_course.title }}</h3><span>{{ referenceTitle(selected.derived_course) }}</span></div><em>{{ displayLabel(selected.upstream_status) }}</em></div>
          <button class="primary" @click="router.push({ path: `/knowledge/courses/${encodeURIComponent(selected.derived_course.id)}`, query: { course_id: selected.derived_course.id } })">打开课程资料</button>
          <div class="facts"><article><span>当前版本</span><strong>{{ selected.derived_course.version }}</strong></article><article><span>可见范围</span><strong>{{ displayLabel(selected.derived_course.visibility) }}</strong></article></div>
          <section class="license"><h3>许可证继承</h3><p>{{ selected.derived_course.license_text || '来源未提供许可证文本' }}</p><small>许可证文本按已发布内容原样继承，不代表系统给出法律兼容性意见。</small></section>
          <template v-if="selected.update_preview">
            <div class="update-title"><GitCompareArrows :size="17" /><div><strong>发现新的课程分享：{{ selected.update_preview.release.title }}</strong><span>老师更新 {{ Object.keys(selected.update_preview.upstream_changes).length }} 项 · 自己修改 {{ Object.keys(selected.update_preview.local_changes).length }} 项 · 双方修改了同一部分 {{ selected.update_preview.conflict_count }} 项</span></div></div>
            <div class="conflicts"><span v-for="x in selected.update_preview.conflicts" :key="x">{{ changeLabel(x) }}</span><em v-if="!selected.update_preview.conflicts.length">与自己的修改没有冲突</em></div>
            <details v-for="(change, index) in selected.update_preview.change_details || []" :key="index" class="change-comparison">
              <summary>{{ change.label }}{{ change.conflict ? ' · 双方均有修改' : '' }}</summary>
              <div><section><h4>{{ change.conflict ? '你目前保存的内容' : '更新前' }}</h4><p>{{ change.conflict ? change.local : change.before }}</p></section><section><h4>老师的新内容</h4><p>{{ change.after }}</p></section></div>
            </details>
            <p v-if="selected.update_preview.conflict_count && !selected.update_preview.decision" class="conflict-explanation">请先对照双方的修改。使用这个版本会以老师的内容替换冲突部分；想保留当前内容，可以忽略此版本。</p>
            <div v-if="selected.update_preview.decision" class="decision"><strong>已决定 {{ displayLabel(selected.update_preview.decision.action) }}</strong><span>{{ learningText(selected.update_preview.decision.reason) }}</span></div>
            <div v-else class="actions"><input v-model="reason" aria-label="更新处理理由" /><button :disabled="Boolean(busy)" @click="decide('ignore')">忽略此版本</button><button class="primary" :disabled="Boolean(busy) || selected.update_preview.release.status !== 'published'" @click="decide('accept')">使用这个版本</button></div>
          </template>
          <div v-else class="current">当前没有待处理的上游更新</div>
        </div><div v-else class="empty">选择老师分享的课程，保存自己的副本</div>
      </div>
    </section>
  </main>
</template>

<style scoped>
.change-comparison{margin:8px 0;border:1px solid var(--color-border);border-radius:var(--radius-control);font-size:14px}.change-comparison summary{padding:10px;cursor:pointer}.change-comparison>div{display:grid;grid-template-columns:1fr 1fr;gap:12px;padding:0 12px 12px}.change-comparison section{min-width:0}.change-comparison h4{margin:4px 0 8px}.change-comparison p{white-space:pre-wrap;overflow-wrap:anywhere;line-height:1.6;margin:0;max-height:360px;overflow:auto}.conflict-explanation{font-size:14px;line-height:1.6}@media(max-width:900px){.change-comparison>div{grid-template-columns:1fr}}
.sharing-page{max-width:1200px;margin:0 auto;color:#26352d}header,.truth,.publisher,.toolbar,.title,.update-title,.actions{display:flex;align-items:center}header{justify-content:space-between}header p{margin:0;color:#78877e;font-size:12px;font-weight:800;letter-spacing:.12em}h2{margin:4px 0;font-size:24px}header span,.truth span,.publisher span,.toolbar span,.title span,.update-title span,.decision span{display:block;color:#718078;font-size:12px}.icon{display:grid;width:36px;height:36px;place-items:center;border:1px solid #dce6df;border-radius:7px;background:#fff}.truth{gap:9px;margin:14px 0;padding:11px;border-left:3px solid #3d7760;background:#eef6f1}.truth strong{font-size:12px}.publisher{display:grid;grid-template-columns:minmax(190px,1.3fr) 1fr auto 1fr 1fr auto;gap:8px;align-items:end;padding:12px;border:1px solid #dfe8e1;background:#fff}.publisher h3{margin:0 0 4px;font-size:13px}.publisher select,.publisher input,.actions input{min-width:0;padding:9px;border:1px solid #d8e3db;border-radius:6px;background:#fff}.segments{display:flex;height:34px;border:1px solid #d8e3db;border-radius:6px;overflow:hidden}.segments button{border:0;background:#fff;color:#596a60}.segments button.active{background:#304b3d;color:#fff}.primary,.toolbar button,aside article button,.actions button{display:flex;align-items:center;justify-content:center;gap:5px;padding:9px;border:0;border-radius:6px;background:#304b3d;color:#fff}.primary:disabled,.toolbar button:disabled,aside button:disabled,.actions button:disabled{opacity:.45}.toolbar{gap:10px;margin:10px 0}.layout{display:grid;grid-template-columns:310px minmax(0,1fr);gap:10px}aside,.copies,.detail,.empty{border:1px solid #dfe8e1;background:#fff}aside{padding:12px}aside h3{margin:0 0 8px;font-size:12px}aside article{padding:10px 0;border-top:1px solid #e6ede8}aside strong,aside span,aside small{display:block}aside strong{font-size:12px}aside span{font-size:12px;color:#748178}aside small{margin:6px 0;overflow-wrap:anywhere;color:#879289;font-size:12px}aside article button{padding:7px;font-size:12px}.copies{display:grid;grid-template-columns:210px minmax(0,1fr);min-height:390px}.copies nav{border-right:1px solid #e1e9e3}.copies nav button{display:block;width:100%;padding:11px;border:0;border-bottom:1px solid #e7eee9;background:#fff;text-align:left}.copies nav button.active{background:#edf4ef}.copies nav strong,.copies nav span{display:block;font-size:12px}.copies nav span{color:#748078}.detail{padding:13px;border:0}.title{justify-content:space-between}.title h3{margin:0;font-size:14px}.title span{overflow-wrap:anywhere}.title em{padding:5px 8px;background:#eaf3ed;font-size:12px;font-style:normal}.facts{display:grid;grid-template-columns:repeat(3,1fr);gap:7px;margin:11px 0}.facts article{padding:10px;background:#f4f7f5}.facts span,.facts strong{display:block;font-size:12px}.facts strong{margin-top:3px}.license{padding:10px;border-left:3px solid #c7a45c;background:#fff8ec}.license h3,.license p{margin:0 0 5px;font-size:12px}.license small{color:#7d715d;font-size:12px}.update-title{gap:8px;margin-top:12px;padding:10px;background:#eef4f0}.conflicts{display:flex;flex-wrap:wrap;gap:5px;padding:8px 0}.conflicts span{padding:4px 7px;border:1px solid #d8a99e;background:#fff0ec;color:#874b40;font-size:12px}.conflicts em{color:#65766b;font-size:12px}.actions{gap:7px}.actions input{flex:1}.decision,.current,.empty{padding:12px;color:#64736a;font-size:12px}.decision{background:#edf5ef}.decision strong,.decision span{display:block}.empty{display:grid;place-items:center}.error{display:flex;gap:6px;padding:8px;background:#fff0ed;color:#984e42;font-size:12px}@media(max-width:900px){.publisher{grid-template-columns:1fr 1fr}.layout{grid-template-columns:1fr}.copies{grid-template-columns:1fr}.copies nav{border-right:0;border-bottom:1px solid #e1e9e3}}@media(max-width:600px){.publisher,.facts{grid-template-columns:1fr}.actions,.toolbar{align-items:stretch;flex-direction:column}.copies{min-width:0}.detail{overflow:hidden}.title{align-items:flex-start;gap:6px}.publisher .primary{width:100%}}
</style>
