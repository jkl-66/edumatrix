<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import {
  Archive, BookOpen, CheckCircle2, ChevronRight, FileSearch, LoaderCircle,
  MessageSquareText, RefreshCw, SearchCheck, ShieldCheck, X,
} from '@lucide/vue'
import {
  archiveM5TutorContext, createM5TutorContext, getCanonicalCourseOutline,
  getCanonicalSourceRef, getM5PlanningTargets, listM5TutorContexts,
  preflightM5TutorRequest,
} from '../api'

const router = useRouter()
const targets = ref({ courses: [], artifacts: [] })
const outline = ref([])
const sourceDetails = ref({})
const contexts = ref([])
const selectedContext = ref(null)
const preflight = ref(null)
const loading = ref(false)
const actionLoading = ref(false)
const error = ref('')
const notice = ref('')
const form = ref({
  course_id: '', context_mode: 'current_resource', primary_object_type: 'chapter',
  primary_object_id: '', selected_source_ref_ids: [], formula_latex: '',
  video_timestamp_seconds: null, teaching_style: 'progressive',
  explanation_depth: 'standard', guidance_mode: 'socratic',
})
const prompt = ref({ question: '', intent: 'explain', comparison_context_ids: [] })

const selectedCourse = computed(() => targets.value.courses.find(item => item.id === form.value.course_id))
const primaryOptions = computed(() => {
  if (form.value.primary_object_type === 'chapter') return outline.value
  if (form.value.primary_object_type === 'artifact') {
    return targets.value.artifacts.filter(item => !form.value.course_id || item.course_id === form.value.course_id)
  }
  return outline.value.filter(item => item.source_ref_id).map(item => ({
    id: item.source_ref_id, title: item.title + ' · 来源引用', source_ref_id: item.source_ref_id,
  }))
})
const availableSources = computed(() => outline.value.filter(item => item.source_ref_id)
  .map(item => ({ ...item, detail: sourceDetails.value[item.source_ref_id] })))
const activeContexts = computed(() => contexts.value.filter(item => item.status === 'active'))

function detailMessage(err) {
  const detail = err?.response?.data?.detail || err?.detail
  return detail?.message || (typeof detail === 'string' ? detail : '') || err?.message || '请求失败'
}

async function loadOutline() {
  outline.value = []
  sourceDetails.value = {}
  form.value.primary_object_id = ''
  form.value.selected_source_ref_ids = []
  if (!form.value.course_id) return
  outline.value = await getCanonicalCourseOutline(form.value.course_id)
  const details = await Promise.all(outline.value.filter(item => item.source_ref_id).map(async item => {
    const detail = await getCanonicalSourceRef(item.source_ref_id)
    return [item.source_ref_id, detail]
  }))
  sourceDetails.value = Object.fromEntries(details)
  form.value.primary_object_id = primaryOptions.value[0]?.id || ''
  syncPrimarySource()
}

function syncPrimarySource() {
  const option = primaryOptions.value.find(item => item.id === form.value.primary_object_id)
  if (form.value.primary_object_type === 'chapter' && option?.source_ref_id) {
    form.value.selected_source_ref_ids = [option.source_ref_id]
  } else if (form.value.primary_object_type === 'source_ref' && option?.id) {
    form.value.selected_source_ref_ids = [option.id]
  }
}

async function loadAll() {
  loading.value = true
  error.value = ''
  try {
    const [catalog, sessions] = await Promise.all([getM5PlanningTargets(), listM5TutorContexts()])
    targets.value = catalog
    contexts.value = sessions.items || []
    if (!form.value.course_id && targets.value.courses.length) {
      form.value.course_id = localStorage.getItem('edumatrix_course_id') || targets.value.courses[0].id
      if (!targets.value.courses.some(item => item.id === form.value.course_id)) {
        form.value.course_id = targets.value.courses[0].id
      }
    }
    selectedContext.value ||= contexts.value[0] || null
  } catch (err) {
    error.value = detailMessage(err)
  } finally {
    loading.value = false
  }
}

async function refreshContexts(keepSelected = false) {
  const selectedId = keepSelected ? selectedContext.value?.id : null
  const data = await listM5TutorContexts()
  contexts.value = data.items || []
  selectedContext.value = contexts.value.find(item => item.id === selectedId) || contexts.value[0] || null
}

async function createContext() {
  if (!form.value.primary_object_id) return
  actionLoading.value = true
  error.value = ''
  notice.value = ''
  preflight.value = null
  try {
    selectedContext.value = await createM5TutorContext({
      schema_version: 'm5.tutor-context.v1',
      idempotency_key: `tutor-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`,
      ...form.value,
      video_timestamp_seconds: form.value.video_timestamp_seconds === '' ? null : form.value.video_timestamp_seconds,
    })
    notice.value = '上下文已冻结并保存。当前没有调用模型。'
    await refreshContexts(true)
  } catch (err) {
    error.value = detailMessage(err)
  } finally {
    actionLoading.value = false
  }
}

async function runPreflight() {
  if (!selectedContext.value || !prompt.value.question.trim()) return
  actionLoading.value = true
  error.value = ''
  notice.value = ''
  try {
    preflight.value = await preflightM5TutorRequest(selectedContext.value.id, {
      question: prompt.value.question, intent: prompt.value.intent,
      comparison_context_ids: prompt.value.comparison_context_ids,
    })
    notice.value = '调用前检查已完成，仅构造可审计请求，尚未调用模型。'
  } catch (err) {
    error.value = detailMessage(err)
  } finally {
    actionLoading.value = false
  }
}

async function archiveContext() {
  if (!selectedContext.value) return
  actionLoading.value = true
  error.value = ''
  try {
    await archiveM5TutorContext(selectedContext.value.id, selectedContext.value.lock_version)
    preflight.value = null
    notice.value = '上下文已归档。'
    await refreshContexts()
  } catch (err) {
    error.value = detailMessage(err)
  } finally {
    actionLoading.value = false
  }
}

function openBoundChat() {
  if (!selectedContext.value || !prompt.value.question.trim()) return
  router.push({
    path: '/learn',
    query: {
      context_session_id: selectedContext.value.id,
      prompt: prompt.value.question,
    },
  })
}

watch(() => form.value.course_id, async (next, previous) => {
  if (next && next !== previous) {
    try { await loadOutline() } catch (err) { error.value = detailMessage(err) }
  }
})
watch(() => form.value.primary_object_type, () => {
  form.value.primary_object_id = primaryOptions.value[0]?.id || ''
  syncPrimarySource()
})
watch(() => form.value.primary_object_id, syncPrimarySource)
onMounted(loadAll)
</script>

<template>
  <section class="tutor-page">
    <header class="page-head">
      <div><p>当前资源 · 来源可追溯 · 可恢复</p><h2>上下文教师工作台</h2></div>
      <div class="truth-badge"><ShieldCheck :size="16" /><span><strong>生成状态</strong>尚未调用模型</span></div>
    </header>
    <div v-if="error" class="banner error"><X :size="15" />{{ error }}</div>
    <div v-if="notice" class="banner notice"><CheckCircle2 :size="15" />{{ notice }}</div>

    <div class="layout">
      <aside class="setup-panel panel">
        <div class="panel-title"><BookOpen :size="16" /><strong>1. 冻结学习上下文</strong></div>
        <label>课程<select v-model="form.course_id" aria-label="课程"><option v-for="item in targets.courses" :key="item.id" :value="item.id">{{ item.title }}</option></select></label>
        <label>主对象类型<select v-model="form.primary_object_type" aria-label="主对象类型"><option value="chapter">课程章节</option><option value="source_ref">来源引用</option><option value="artifact">个人资源</option></select></label>
        <label>当前资源<select v-model="form.primary_object_id" aria-label="当前资源"><option v-for="item in primaryOptions" :key="item.id" :value="item.id">{{ item.title }}</option></select></label>
        <label>检索范围<select v-model="form.context_mode" aria-label="检索范围"><option value="current_resource">仅当前资源</option><option value="current_course">当前课程</option><option value="personal_resources">个人资源</option><option value="external_allowed">允许外部检索</option></select></label>

        <fieldset><legend>纳入来源（最多 8 条）</legend><label v-for="item in availableSources" :key="item.source_ref_id" class="source-check"><input v-model="form.selected_source_ref_ids" type="checkbox" :value="item.source_ref_id" :disabled="!form.selected_source_ref_ids.includes(item.source_ref_id) && form.selected_source_ref_ids.length >= 8" /><span>{{ item.position }}. {{ item.title }}<small>{{ item.detail?.quote?.slice(0, 72) || '正在读取来源' }}</small></span></label></fieldset>

        <div class="three-cols">
          <label>教学风格<select v-model="form.teaching_style" aria-label="教学风格"><option value="progressive">渐进讲解</option><option value="socratic">苏格拉底</option><option value="case_based">案例驱动</option><option value="close_reading">精读</option><option value="practice_along">边练边学</option></select></label>
          <label>讲解深度<select v-model="form.explanation_depth" aria-label="讲解深度"><option value="concise">简洁</option><option value="standard">标准</option><option value="deep">深入</option></select></label>
          <label>引导模式<select v-model="form.guidance_mode" aria-label="引导模式"><option value="socratic">启发引导</option><option value="direct">直接讲解</option></select></label>
        </div>
        <label>公式（可选）<textarea v-model="form.formula_latex" rows="2" placeholder="例如：P(y=1)=σ(θ-b)" /></label>
        <label>视频时间点（秒，可选）<input v-model.number="form.video_timestamp_seconds" type="number" min="0" placeholder="例如 125" /></label>
        <button class="primary" :disabled="actionLoading || loading || !form.primary_object_id" @click="createContext"><LoaderCircle v-if="actionLoading" class="spin" :size="15" /><SearchCheck v-else :size="15" />创建可恢复上下文</button>
      </aside>

      <main class="work-panel panel">
        <div class="context-toolbar"><div class="panel-title"><MessageSquareText :size="16" /><strong>2. 检查教师请求</strong></div><button class="icon" title="刷新并验证恢复" @click="refreshContexts(true)"><RefreshCw :size="15" /></button></div>
        <div class="context-tabs">
          <button v-for="item in activeContexts" :key="item.id" :class="{ active: selectedContext?.id === item.id }" @click="selectedContext = item; preflight = null"><span>{{ item.context?.primary?.title || item.primary_object_id }}</span><small>{{ item.teaching_style }} · {{ item.context_mode }}</small></button>
          <div v-if="!activeContexts.length" class="empty">创建上下文后可在这里切换和恢复</div>
        </div>

        <template v-if="selectedContext">
          <section class="snapshot">
            <div class="snapshot-head"><div><small>{{ selectedContext.context?.course_title || selectedCourse?.title }}</small><h3>{{ selectedContext.context?.primary?.title }}</h3></div><button class="danger-icon" title="归档上下文" @click="archiveContext"><Archive :size="15" /></button></div>
            <div class="scope-row"><span v-for="(enabled, key) in selectedContext.context?.retrieval_scope" :key="key" :class="{ enabled }">{{ key }}: {{ enabled ? '是' : '否' }}</span></div>
            <div class="sources"><article v-for="source in selectedContext.context?.sources" :key="source.source_ref_id"><div><FileSearch :size="14" /><strong>页码 {{ source.page_number ?? '文本定位' }}</strong><code>{{ source.content_hash?.slice(0, 12) }}…</code></div><blockquote>{{ source.quote || '该引用只保存了定位信息' }}</blockquote><small>字符 {{ source.char_range?.[0] ?? '-' }}–{{ source.char_range?.[1] ?? '-' }} · {{ source.parser_version }}</small></article></div>
          </section>

          <div class="prompt-grid">
            <label>意图<select v-model="prompt.intent" aria-label="问题意图"><option value="explain">讲解</option><option value="example">举例</option><option value="challenge">挑战</option><option value="quiz">出题</option><option value="note">笔记</option><option value="compare">比较</option></select></label>
            <label class="question">你的问题<textarea v-model="prompt.question" rows="4" aria-label="你的问题" placeholder="针对当前冻结资源提出问题" /></label>
          </div>
          <button class="primary" :disabled="actionLoading || !prompt.question.trim()" @click="runPreflight"><ChevronRight :size="15" />执行调用前检查</button>
          <button v-if="preflight?.ready" class="secondary-action" @click="openBoundChat"><MessageSquareText :size="15" />使用该上下文进入智能对话</button>

          <section v-if="preflight" class="preflight" data-testid="preflight-result">
            <header><strong>请求检查结果</strong><span :class="preflight.ready ? 'ready' : 'blocked'">{{ preflight.ready ? '运行依赖就绪' : '存在运行阻塞' }}</span></header>
            <dl><div><dt>模型生成</dt><dd>{{ preflight.generation_started ? '已开始' : '未开始' }}</dd></div><div><dt>来源数量</dt><dd>{{ preflight.context?.sources?.length || 0 }}</dd></div><div><dt>问题意图</dt><dd>{{ preflight.intent }}</dd></div><div><dt>阻塞项</dt><dd>{{ preflight.blockers?.join('、') || '无' }}</dd></div></dl>
            <p>这一步只验证权限、检索范围、来源快照和运行依赖，不产生教师答案，也不消耗外部模型额度。</p>
          </section>
        </template>
        <div v-else-if="loading" class="empty"><LoaderCircle class="spin" :size="20" /></div>
        <div v-else class="empty">请先从左侧创建一个来源绑定的学习上下文</div>
      </main>
    </div>
  </section>
</template>

<style scoped>
.tutor-page{max-width:1440px;margin:0 auto;color:#27322b}.page-head{display:flex;align-items:center;justify-content:space-between;margin-bottom:14px}.page-head p{margin:0 0 3px;color:#718077;font-size:11px}.page-head h2{margin:0;font-size:22px;letter-spacing:0}.truth-badge{display:flex;align-items:center;gap:8px;padding:8px 11px;border:1px solid #b8d4c1;border-radius:8px;background:#f1f8f3;color:#42634c}.truth-badge span,.truth-badge strong{display:block;font-size:11px}.truth-badge strong{color:#263a2c}.banner{display:flex;align-items:center;gap:7px;margin-bottom:10px;padding:9px 11px;border-radius:7px;font-size:12px}.error{border:1px solid #ecc8c3;background:#fff4f2;color:#924c44}.notice{border:1px solid #bfdbc7;background:#f2f9f4;color:#3e6749}.layout{display:grid;grid-template-columns:minmax(340px,430px) minmax(0,1fr);gap:12px}.panel{border:1px solid #dce4dd;border-radius:8px;background:rgba(255,255,255,.9)}.setup-panel{padding:14px}.work-panel{min-height:720px;padding:14px}.panel-title,.context-toolbar{display:flex;align-items:center;gap:7px}.panel-title{margin-bottom:12px}.context-toolbar{justify-content:space-between}.setup-panel>label,.prompt-grid label{display:grid;gap:5px;margin-bottom:9px;color:#647168;font-size:11px}select,input,textarea{width:100%;border:1px solid #d7e0d9;border-radius:7px;background:#fff;color:#2f3932;font:inherit;font-size:12px;outline:0}select,input{height:35px;padding:0 9px}textarea{padding:8px;resize:vertical}select:focus,input:focus,textarea:focus{border-color:#7ba288;box-shadow:0 0 0 2px rgba(89,132,103,.1)}fieldset{max-height:220px;overflow:auto;margin:11px 0;padding:8px;border:1px solid #e1e7e2;border-radius:7px}legend{padding:0 5px;color:#647168;font-size:11px}.source-check{display:flex;align-items:flex-start;gap:7px;padding:7px;border-bottom:1px solid #eef2ef;color:#344039;font-size:11px}.source-check input{width:14px;height:14px}.source-check span,.source-check small{display:block;min-width:0}.source-check small{margin-top:2px;color:#89958d;line-height:1.4}.three-cols{display:grid;grid-template-columns:repeat(3,1fr);gap:7px}.three-cols label{color:#647168;font-size:10px}.primary{display:flex;min-height:36px;align-items:center;justify-content:center;gap:7px;padding:0 12px;border:0;border-radius:7px;background:#3d674b;color:#fff;font-size:12px;cursor:pointer}.primary:disabled{opacity:.5;cursor:not-allowed}.icon,.danger-icon{display:grid;width:32px;height:32px;place-items:center;border:1px solid #dce3dd;border-radius:7px;background:#fff;color:#627067;cursor:pointer}.danger-icon{color:#9a5149}.context-tabs{display:flex;gap:7px;overflow-x:auto;margin-bottom:12px;padding-bottom:5px}.context-tabs button{flex:0 0 180px;overflow:hidden;padding:8px 10px;border:1px solid #dfe5e0;border-radius:7px;background:#fafbf9;text-align:left;cursor:pointer}.context-tabs button.active{border-color:#86a892;background:#eef6f0}.context-tabs span,.context-tabs small{display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.context-tabs span{color:#303b33;font-size:11px;font-weight:600}.context-tabs small{margin-top:3px;color:#7b887f;font-size:9px}.snapshot{margin-bottom:13px;padding:13px;border:1px solid #dfe6e0;border-radius:8px;background:#fbfcfa}.snapshot-head{display:flex;justify-content:space-between}.snapshot-head small{color:#7f8b83;font-size:10px}.snapshot-head h3{margin:2px 0 0;font-size:16px;letter-spacing:0}.scope-row{display:flex;flex-wrap:wrap;gap:5px;margin:10px 0}.scope-row span{padding:3px 6px;border-radius:4px;background:#f0f1ef;color:#8a938d;font-size:9px}.scope-row span.enabled{background:#e7f2ea;color:#40624a}.sources{display:grid;gap:7px}.sources article{padding:9px;border-left:3px solid #7da289;background:#f4f7f4}.sources article>div{display:flex;align-items:center;gap:6px}.sources code{margin-left:auto;color:#87928a;font-size:9px}.sources blockquote{margin:6px 0;color:#3c4740;font-size:11px;line-height:1.55}.sources small{color:#849087;font-size:9px}.prompt-grid{display:grid;grid-template-columns:150px minmax(0,1fr);gap:9px}.prompt-grid .question{grid-column:2}.preflight{margin-top:13px;padding:12px;border:1px solid #cbdccf;border-radius:8px;background:#f6faf7}.preflight header{display:flex;align-items:center;justify-content:space-between}.preflight header span{padding:3px 7px;border-radius:4px;font-size:10px}.ready{background:#dfeee3;color:#376044}.blocked{background:#fff0dc;color:#8a632e}.preflight dl{display:grid;grid-template-columns:repeat(4,1fr);gap:7px}.preflight dl div{padding:8px;background:#fff}.preflight dt{color:#879189;font-size:9px}.preflight dd{margin:3px 0 0;color:#334038;font-size:11px}.preflight p{margin:8px 0 0;color:#718078;font-size:10px}.empty{display:grid;min-height:160px;place-items:center;color:#8b958e;font-size:12px}.spin{animation:spin 1s linear infinite}@keyframes spin{to{transform:rotate(360deg)}}
@media(max-width:900px){.layout{grid-template-columns:1fr}.work-panel{min-height:520px}.three-cols{grid-template-columns:1fr}.prompt-grid{grid-template-columns:1fr}.prompt-grid .question{grid-column:1}.preflight dl{grid-template-columns:repeat(2,1fr)}}@media(max-width:540px){.page-head{align-items:flex-start;gap:8px}.truth-badge{max-width:150px}.setup-panel,.work-panel{padding:10px}.preflight dl{grid-template-columns:1fr}}
.secondary-action{display:flex;min-height:36px;align-items:center;justify-content:center;gap:7px;margin-top:7px;padding:0 12px;border:1px solid #8aaa94;border-radius:7px;background:#f4f8f5;color:#355c42;font-size:12px;cursor:pointer}
</style>
