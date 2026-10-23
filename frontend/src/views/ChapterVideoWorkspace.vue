<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import {
  ArrowRight, Beaker, BookOpenCheck, CheckCircle2, CircleAlert, Download, Film,
  Link2, LoaderCircle, PlayCircle, RefreshCw, ShieldCheck, Sparkles,
  Volume2, VolumeX, X,
} from '@lucide/vue'
import {
  bindVideoPractice,
  downloadVideoOutput, generateChapterVideo, getChapterVideoContext,
  getVideoOutputBlob, getVideoPractice, getVideoPracticeContext, getVideoProject,
  linkVideoPracticeLab, listChapterVideos, renderVideoProject,
  saveVideoWatchProgress, submitVideoPracticeAttempt,
} from '../api'

const context = ref({ courses: [], profiles: [] })
const items = ref([])
const selected = ref(null)
const courseId = ref('')
const chapterId = ref('')
const profileId = ref('')
const loading = ref(true)
const busy = ref(false)
const error = ref('')
const notice = ref('')
const videoUrl = ref('')
const practice = ref(null)
const practiceContext = ref({ questions: [], labs: [] })
const practiceBusy = ref(false)
const selectedQuestions = ref([])
const selectedLabs = ref([])
const answers = ref({})
const watchedSeconds = ref(0)
let videoRequest = 0

const course = computed(() => context.value.courses?.find(item => item.id === courseId.value) || null)
const chapters = computed(() => course.value?.chapters || [])
const latest = computed(() => selected.value?.project?.tasks?.find(item => item.status === 'completed' && item.output) || null)
const script = computed(() => selected.value?.project?.script || null)
const objectiveTypes = new Set(['single_choice', 'multiple_choice', 'true_false', 'fill_blank'])

function detail(caught, fallback = '请求失败') {
  return caught?.response?.data?.detail?.message || caught?.detail?.message || caught?.message || fallback
}

function selectDefaults() {
  if (!courseId.value || !context.value.courses.some(item => item.id === courseId.value)) {
    courseId.value = context.value.courses?.[0]?.id || ''
  }
  if (!chapters.value.some(item => item.id === chapterId.value)) {
    chapterId.value = chapters.value?.[0]?.id || ''
  }
}

async function load(preferred = selected.value?.id || '') {
  loading.value = true
  error.value = ''
  try {
    const [contextData, listData] = await Promise.all([
      getChapterVideoContext(), listChapterVideos(),
    ])
    context.value = contextData
    items.value = listData.items || []
    selectDefaults()
    const next = items.value.find(item => item.id === preferred) || items.value[0] || null
    if (next) await open(next.id)
    else selected.value = null
  } catch (caught) {
    error.value = detail(caught, '章节视频工作区加载失败')
  } finally {
    loading.value = false
  }
}

async function generate() {
  if (!courseId.value || !chapterId.value) return
  busy.value = true
  error.value = ''
  notice.value = ''
  try {
    const row = await generateChapterVideo({
      course_id: courseId.value,
      chapter_id: chapterId.value,
      profile_snapshot_id: profileId.value || null,
    })
    selected.value = row
    items.value = [row, ...items.value.filter(item => item.id !== row.id)]
    await loadPractice()
    notice.value = row.idempotent ? '输入快照未变化，已恢复原章节视频项目。' : '已创建来源绑定的五段章节视频脚本。'
  } catch (caught) {
    error.value = detail(caught, '章节视频生成失败')
  } finally {
    busy.value = false
  }
}

async function render() {
  if (!selected.value) return
  busy.value = true
  error.value = ''
  notice.value = ''
  try {
    const project = selected.value.project
    const task = await renderVideoProject(project.id, {
      idempotency_key: `chapter-${selected.value.id}-${project.script.id}-${Date.now()}`,
    })
    selected.value.project = await getVideoProject(project.id)
    if (task.status === 'completed') notice.value = '本地 MP4、字幕和讲稿已生成。'
    else error.value = task.error_message || '渲染任务未完成'
  } catch (caught) {
    error.value = detail(caught, '离线视频渲染失败')
  } finally {
    busy.value = false
  }
}

async function open(id) {
  selected.value = items.value.find(item => item.id === id) || null
  if (selected.value) {
    courseId.value = selected.value.course_id
    selectDefaults()
    chapterId.value = selected.value.chapter_id
    profileId.value = selected.value.profile_snapshot_id || ''
    await loadPractice()
  }
}

async function loadPractice() {
  practice.value = null
  practiceContext.value = { questions: [], labs: [] }
  selectedQuestions.value = []
  selectedLabs.value = []
  answers.value = {}
  if (!selected.value) return
  try {
    const [state, available] = await Promise.all([
      getVideoPractice(selected.value.id), getVideoPracticeContext(selected.value.id),
    ])
    practice.value = state
    practiceContext.value = available
    selectedQuestions.value = state.questions?.map(item => item.id) || []
    selectedLabs.value = state.labs?.map(item => item.instance_id) || []
    watchedSeconds.value = state.watch?.watched_seconds || 0
    for (const question of state.questions || []) resetAnswer(question)
  } catch (caught) {
    error.value = detail(caught, '视频后练习恢复失败')
  }
}

function resetAnswer(question) {
  if (question.question_type === 'multiple_choice') answers.value[question.id] = { choices: [] }
  else if (question.question_type === 'true_false') answers.value[question.id] = { value: null }
  else if (question.question_type === 'fill_blank') answers.value[question.id] = { blanks: Array(question.response_spec?.blank_count || 1).fill('') }
  else answers.value[question.id] = { choice: '' }
}

function optionLabel(index) {
  return String.fromCharCode(65 + index)
}

async function saveBindings() {
  practiceBusy.value = true
  error.value = ''
  notice.value = ''
  try {
    practice.value = await bindVideoPractice(selected.value.id, {
      question_version_ids: selectedQuestions.value,
      lab_instance_ids: selectedLabs.value,
      expected_lock_version: practice.value?.practice_set?.lock_version || 0,
    })
    for (const question of practice.value.questions || []) resetAnswer(question)
    notice.value = practice.value.binding_created ? `已保存练习绑定 v${practice.value.practice_version.version_number}。` : '绑定内容未变化，已恢复当前练习版本。'
  } catch (caught) {
    error.value = detail(caught, '练习绑定保存失败')
  } finally {
    practiceBusy.value = false
  }
}

function recordTime(event) {
  watchedSeconds.value = Math.max(watchedSeconds.value, event.target.currentTime || 0)
}

async function saveWatch(completed = false) {
  practiceBusy.value = true
  error.value = ''
  try {
    const duration = Number(latest.value?.output?.duration_ms || script.value?.total_duration_ms || 0) / 1000
    practice.value = await saveVideoWatchProgress(selected.value.id, {
      watched_seconds: completed ? duration : Math.min(watchedSeconds.value, duration || watchedSeconds.value),
      duration_seconds: duration, completed,
      expected_lock_version: practice.value?.watch?.lock_version || 0,
    })
    notice.value = completed ? '观看完成已记录为弱证据，能力值未改变。' : '观看进度已保存，能力值未改变。'
  } catch (caught) {
    error.value = detail(caught, '观看进度保存失败')
  } finally {
    practiceBusy.value = false
  }
}

function canSubmitQuestion(question) {
  const answer = answers.value[question.id] || {}
  if (question.question_type === 'single_choice') return !!answer.choice
  if (question.question_type === 'multiple_choice') return !!answer.choices?.length
  if (question.question_type === 'true_false') return answer.value !== null
  if (question.question_type === 'fill_blank') return answer.blanks?.every(item => item.trim())
  return false
}

async function submitQuestion(question) {
  practiceBusy.value = true
  error.value = ''
  try {
    const result = await submitVideoPracticeAttempt(selected.value.id, {
      question_version_id: question.id,
      idempotency_key: `video-practice-${selected.value.id}-${question.id}-${Date.now()}`,
      mode: 'practice', answer: answers.value[question.id],
    })
    await loadPractice()
    const score = Math.round((result.evidence_link?.grading?.score || 0) * 100)
    notice.value = `服务端评分 ${score}%，已形成强证据；下一步：${result.evidence_link?.next_action === 'proceed' ? '继续学习' : '复习后重试'}。`
  } catch (caught) {
    error.value = detail(caught, '微测提交失败')
  } finally {
    practiceBusy.value = false
  }
}

async function attachLab(lab) {
  practiceBusy.value = true
  error.value = ''
  try {
    await linkVideoPracticeLab(selected.value.id, lab.instance_id)
    await loadPractice()
    notice.value = '实验隐藏验收结果已回链为强证据。'
  } catch (caught) {
    error.value = detail(caught, '实验结果尚不能回链，请先在实验台通过隐藏验收')
  } finally {
    practiceBusy.value = false
  }
}

function download(name) {
  if (latest.value) downloadVideoOutput(latest.value.output.id, name)
}

watch(courseId, () => {
  chapterId.value = chapters.value?.[0]?.id || ''
})

watch(() => latest.value?.output?.id, async outputId => {
  const request = ++videoRequest
  if (videoUrl.value) URL.revokeObjectURL(videoUrl.value)
  videoUrl.value = ''
  if (!outputId) return
  try {
    const url = URL.createObjectURL(await getVideoOutputBlob(outputId, 'course-video.mp4'))
    if (request !== videoRequest) return URL.revokeObjectURL(url)
    videoUrl.value = url
  } catch (caught) {
    if (request === videoRequest) error.value = detail(caught, '视频预览加载失败')
  }
}, { immediate: true })

onMounted(load)
onBeforeUnmount(() => {
  videoRequest += 1
  if (videoUrl.value) URL.revokeObjectURL(videoUrl.value)
})
</script>

<template>
  <main class="chapter-workspace" data-testid="chapter-video-workspace">
    <header>
      <div>
        <p class="eyebrow">SOURCE-BOUND COURSE VIDEO</p>
        <h1>课程章节视频生成</h1>
        <p>把课程章节、知识点、原文引用与冻结画像策略编排为可渲染的五段技能微课。</p>
      </div>
      <div class="boundary">
        <ShieldCheck :size="19" />
        <div><strong>课程事实边界</strong><small>没有真实来源摘录或授课知识点时拒绝生成；画像不改变事实标准。</small></div>
      </div>
    </header>

    <p v-if="error" class="notice error"><X :size="14" />{{ error }}<button @click="load"><RefreshCw :size="13" />重试</button></p>
    <p v-if="notice" class="notice success"><CheckCircle2 :size="14" />{{ notice }}</p>
    <p v-if="loading" class="notice"><LoaderCircle :size="14" class="spin" />正在恢复章节视频项目...</p>

    <template v-else>
      <section v-if="context.courses?.length" class="controls">
        <label>课程<select v-model="courseId" aria-label="选择课程"><option v-for="item in context.courses" :key="item.id" :value="item.id">{{ item.title }} · {{ item.version }}</option></select></label>
        <label>章节<select v-model="chapterId" aria-label="选择章节"><option v-for="item in chapters" :key="item.id" :value="item.id">{{ item.position }}. {{ item.title }}</option></select></label>
        <label>画像策略<select v-model="profileId" aria-label="选择画像快照"><option value="">基线讲解策略</option><option v-for="item in context.profiles" :key="item.id" :value="item.id">画像 v{{ item.profile_version }} · {{ item.id.slice(-8) }}</option></select></label>
        <button class="primary" :disabled="busy || !chapterId" @click="generate"><LoaderCircle v-if="busy" :size="15" class="spin" /><Sparkles v-else :size="15" />生成章节脚本</button>
      </section>
      <section v-else class="empty top"><BookOpenCheck :size="28" /><strong>没有可访问的课程章节</strong><span>请先导入并发布带章节、来源引用和知识点关系的课程。</span></section>

      <section v-if="items.length" class="project-picker">
        <label>历史项目<select :value="selected?.id || ''" aria-label="选择章节视频项目" @change="open($event.target.value)"><option v-for="item in items" :key="item.id" :value="item.id">{{ item.project.title }} · script v{{ item.project.script.version_number }}</option></select></label>
        <button @click="load"><RefreshCw :size="14" />刷新恢复</button>
      </section>

      <div v-if="selected" class="layout">
        <section class="evidence">
          <div class="panel-head"><div><strong>课程证据与适配</strong><small>{{ selected.course_id }} / {{ selected.chapter_id }}</small></div><span>input {{ selected.input_hash.slice(0, 12) }}</span></div>
          <div class="truth"><ShieldCheck :size="17" /><p>{{ selected.truth_boundary }}</p></div>
          <div class="columns">
            <article><h2>学习目标</h2><span class="tag">{{ selected.quality.objective_origin === 'course_manifest' ? '课程清单正式字段' : '系统整理目标草案' }}</span><ol><li v-for="item in selected.learning_objectives" :key="item">{{ item }}</li></ol></article>
            <article><h2>画像策略</h2><dl><dt>模式</dt><dd>{{ selected.personalization.mode }}</dd><dt>讲解顺序</dt><dd>{{ selected.personalization.explanation_order }}</dd><dt>示例密度</dt><dd>{{ selected.personalization.example_density }}</dd><dt>节奏</dt><dd>{{ selected.personalization.pace }}</dd></dl></article>
          </div>
          <article class="sources"><h2>可定位课程来源</h2><div v-for="source in selected.sources" :key="source.source_ref_id" class="source"><div><strong>{{ source.document_title }}</strong><span>{{ source.location_label }} · {{ source.source_ref_id }}</span></div><blockquote>{{ source.quote }}</blockquote><small>parser {{ source.parser_version }} · hash {{ source.content_hash }}</small></div></article>
          <article class="script"><h2>五段视频脚本</h2><div v-for="scene in script?.scenes" :key="scene.order" class="scene"><span>{{ scene.order }}</span><div><strong>{{ scene.title }}</strong><p>{{ scene.narration }}</p><small>{{ scene.bullets.join(' · ') }} · {{ (scene.duration_ms / 1000).toFixed(1) }} 秒</small></div></div></article>
        </section>

        <aside>
          <div class="panel-head"><div><strong>视频成品</strong><small>脚本 v{{ script?.version_number }} · {{ (script?.total_duration_ms / 1000).toFixed(1) }} 秒</small></div></div>
          <div class="audio"><Volume2 v-if="latest?.audio_status === 'sapi_zh_cn'" :size="18" /><VolumeX v-else :size="18" /><div><strong>{{ latest?.audio_status === 'sapi_zh_cn' ? '本地中文配音' : '字幕与讲稿模式' }}</strong><small>音轨按实际渲染结果披露</small></div></div>
          <video v-if="latest" :src="videoUrl" controls data-testid="chapter-rendered-video" @timeupdate="recordTime" @ended="saveWatch(true)" />
          <div v-else class="empty"><Film :size="27" /><strong>脚本尚未渲染</strong><span>使用统一离线流水线生成 H.264 MP4、SRT、VTT 与讲稿。</span></div>
          <button class="render" :disabled="busy" @click="render"><LoaderCircle v-if="busy" :size="15" class="spin" /><Film v-else :size="15" />{{ latest ? '重新渲染新版本' : '生成 MP4 与字幕' }}</button>
          <template v-if="latest">
            <dl class="quality"><dt>质量结果</dt><dd>{{ latest.output.quality_report.passed ? 'PASS' : 'FAIL' }}</dd><dt>分辨率</dt><dd>{{ latest.output.quality_report.resolution }}</dd><dt>字幕条数</dt><dd>{{ latest.output.quality_report.subtitle_cues }}</dd><dt>音轨状态</dt><dd>{{ latest.audio_status }}</dd><dt>MP4 SHA-256</dt><dd class="hash">{{ latest.output.mp4_sha256 }}</dd></dl>
            <div class="downloads"><button @click="download('course-video.mp4')"><Download :size="13" />MP4</button><button @click="download('subtitles.srt')"><Download :size="13" />SRT</button><button @click="download('subtitles.vtt')"><Download :size="13" />VTT</button><button @click="download('transcript.json')"><Download :size="13" />讲稿</button></div>
            <div class="watch-proof" data-testid="video-watch-proof"><span><PlayCircle :size="15" />观看 {{ Math.round(practice?.watch?.watched_seconds || watchedSeconds) }} / {{ Math.round(practice?.watch?.duration_seconds || script?.total_duration_ms / 1000 || 0) }} 秒</span><strong>{{ practice?.watch?.completed ? '已完成 · 弱证据' : '未完成 · 弱证据' }}</strong><small>观看进度不会更新能力值；当前作答计数 {{ practice?.ability?.response_count || 0 }}</small><div><button :disabled="practiceBusy" @click="saveWatch(false)">保存进度</button><button data-testid="mark-watch-complete" :disabled="practiceBusy" @click="saveWatch(true)">标记观看完成</button></div></div>
          </template>
        </aside>
      </div>
      <section v-if="selected" class="practice-workspace" data-testid="video-practice-workspace">
        <div class="practice-head"><div><p class="eyebrow">POST-VIDEO STRONG EVIDENCE</p><h2>视频后练习与实操证据</h2><small>{{ practice?.truth_boundary || '先绑定与课程来源一致的题目或实验。' }}</small></div><div class="ability"><span>规范作答</span><strong>{{ practice?.ability?.response_count || 0 }}</strong><small>能力状态 v{{ practice?.ability?.lock_version || 0 }}</small></div></div>

        <div v-if="!practice?.practice_version" class="binding-builder">
          <div><h3>可绑定微测</h3><label v-for="question in practiceContext.questions" :key="question.id"><input v-model="selectedQuestions" type="checkbox" :value="question.id" /><span><strong>{{ question.question_type }}</strong>{{ question.prompt }}</span></label><p v-if="!practiceContext.questions?.length">当前没有同时满足课程、知识点、来源和审核状态的题目。</p></div>
          <div><h3>可绑定交互实验</h3><label v-for="lab in practiceContext.labs" :key="lab.instance_id"><input v-model="selectedLabs" type="checkbox" :value="lab.instance_id" /><span><strong>{{ lab.status }}</strong>{{ lab.title }}</span></label><p v-if="!practiceContext.labs?.length">暂无本人可访问的本地交互实验。</p></div>
          <button data-testid="save-video-practice-bindings" :disabled="practiceBusy || (!selectedQuestions.length && !selectedLabs.length)" @click="saveBindings"><Link2 :size="15" />保存版本化绑定</button>
        </div>

        <template v-else>
          <div class="version-line"><span>练习 v{{ practice.practice_version.version_number }}</span><code>{{ practice.practice_version.content_hash.slice(0, 16) }}</code><button @click="practice.practice_version = null"><RefreshCw :size="13" />创建新绑定版本</button></div>
          <div class="practice-grid">
            <article v-for="question in practice.questions" :key="question.id" class="question-card" :data-question-type="question.question_type">
              <div class="card-meta"><span>{{ question.question_type }}</span><small>题目 v{{ question.version_number }} · 来源和知识点已核验</small></div>
              <h3>{{ question.prompt }}</h3>
              <div v-if="question.question_type === 'single_choice'" class="answer-options"><label v-for="(option, index) in question.options" :key="option"><input v-model="answers[question.id].choice" type="radio" :value="optionLabel(index)" /><b>{{ optionLabel(index) }}</b><span>{{ option }}</span></label></div>
              <div v-else-if="question.question_type === 'multiple_choice'" class="answer-options"><label v-for="(option, index) in question.options" :key="option"><input v-model="answers[question.id].choices" type="checkbox" :value="optionLabel(index)" /><b>{{ optionLabel(index) }}</b><span>{{ option }}</span></label></div>
              <div v-else-if="question.question_type === 'true_false'" class="boolean-row"><button @click="answers[question.id].value = true">正确</button><button @click="answers[question.id].value = false">错误</button></div>
              <div v-else-if="question.question_type === 'fill_blank'" class="blank-row"><input v-for="(_, index) in answers[question.id].blanks" :key="index" v-model="answers[question.id].blanks[index]" :placeholder="`空 ${index + 1}`" /></div>
              <div v-if="objectiveTypes.has(question.question_type)" class="submit-practice"><span><ShieldCheck :size="14" />答案不发送分数，由服务端规范判分</span><button data-testid="submit-video-practice" :disabled="practiceBusy || !canSubmitQuestion(question)" @click="submitQuestion(question)">提交微测<ArrowRight :size="14" /></button></div>
              <div v-else class="external-practice"><CircleAlert :size="16" /><span>{{ question.question_type === 'code' ? '代码题必须在规范测评页运行隐藏测试，完成后才能回链。' : '该题需要先在规范测评页完成评分。' }}</span><RouterLink to="/assessment">打开规范测评</RouterLink></div>
            </article>
            <article v-for="lab in practice.labs" :key="lab.instance_id" class="lab-card"><div class="card-meta"><span>interactive_lab</span><small>{{ lab.template_id }} · v{{ lab.version_number }}</small></div><h3>{{ lab.title }}</h3><p>当前状态：<strong>{{ lab.status }}</strong>；只有状态为 passed 且隐藏验收通过时形成强证据。</p><div><RouterLink to="/interactive-lab"><Beaker :size="14" />打开实验台</RouterLink><button :disabled="practiceBusy" @click="attachLab(lab)"><Link2 :size="14" />回链验收结果</button></div></article>
          </div>
          <div v-if="practice.attempt_links?.length || practice.lab_links?.length" class="evidence-ledger"><h3>不可变强证据</h3><div v-for="item in practice.attempt_links" :key="item.id"><CheckCircle2 :size="15" /><span><strong>测评 {{ Math.round(item.grading.score * 100) }}%</strong>{{ item.grading.label }} · {{ item.next_action === 'proceed' ? '继续学习' : '复习后重试' }}</span><code>{{ item.content_hash.slice(0, 12) }}</code></div><div v-for="item in practice.lab_links" :key="item.id"><CheckCircle2 :size="15" /><span><strong>实验隐藏验收通过</strong>{{ item.lab.title }} · 继续学习</span><code>{{ item.content_hash.slice(0, 12) }}</code></div></div>
        </template>
      </section>
      <section v-else-if="context.courses?.length" class="empty initial"><Film :size="30" /><strong>选择章节生成首个视频项目</strong><span>系统只会使用当前章节已有的课程证据，不会编造脱离来源的视频。</span></section>
    </template>
  </main>
</template>

<style scoped>
.chapter-workspace{max-width:1240px;margin:0 auto;color:#26352e}.chapter-workspace header{display:flex;justify-content:space-between;gap:24px;padding-bottom:18px;border-bottom:1px solid #d9e1dc}.eyebrow{margin:0 0 6px;color:#347358;font-size:10px;font-weight:800}.chapter-workspace h1{margin:0;font-size:24px;letter-spacing:0}.chapter-workspace header p:last-child{margin:6px 0 0;color:#6f7b73;font-size:12px}.boundary{display:flex;gap:9px;align-items:flex-start;max-width:380px;padding:11px 13px;border:1px solid #c9ddd0;background:#f1f7f3;color:#345d45}.boundary div{display:flex;flex-direction:column}.boundary strong{font-size:11px}.boundary small{margin-top:3px;font-size:9px;line-height:1.5}.notice{display:flex;align-items:center;gap:7px;min-height:38px;margin:12px 0 0;padding:8px 11px;background:#f2f5f3;font-size:11px}.notice button{margin-left:auto}.notice.error{background:#fff0ed;color:#8b4338}.notice.success{background:#edf8f2;color:#286548}.controls{display:grid;grid-template-columns:1.2fr 1.2fr 1fr auto;gap:9px;margin-top:14px;padding:13px;border:1px solid #d9e1dc;background:#fff}.controls label,.project-picker label{display:flex;min-width:0;flex-direction:column;gap:5px;color:#718078;font-size:9px}.controls select,.project-picker select{width:100%;height:36px;padding:0 9px;border:1px solid #ced9d2;background:#fff;color:#2d3e35}.controls button,.project-picker button,.render,.downloads button,.notice button{display:inline-flex;align-items:center;justify-content:center;gap:5px;min-height:36px;padding:0 11px;border:1px solid #c8d6cd;background:#fff;color:#34493d}.controls .primary,.render{align-self:end;background:#173f31;color:#fff;border-color:#173f31}.project-picker{display:flex;align-items:flex-end;gap:9px;margin-top:10px}.project-picker label{flex:1}.layout{display:grid;grid-template-columns:minmax(0,1.55fr) minmax(310px,.75fr);gap:14px;margin-top:14px}.evidence,aside{border:1px solid #d9e1dc;background:#fff;padding:14px}.panel-head{display:flex;justify-content:space-between;gap:12px;padding-bottom:11px;border-bottom:1px solid #e4eae6}.panel-head div{display:flex;min-width:0;flex-direction:column}.panel-head strong{font-size:12px}.panel-head small,.panel-head span{overflow-wrap:anywhere;color:#7b8980;font-size:9px}.truth{display:flex;gap:8px;margin-top:11px;padding:9px;background:#f1f6f3;color:#365847}.truth p{margin:0;font-size:10px;line-height:1.6}.columns{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:10px}.columns article,.sources,.script{border:1px solid #e1e7e3;padding:11px}.evidence h2{margin:0 0 8px;font-size:11px;letter-spacing:0}.tag{display:inline-block;padding:3px 6px;background:#e6f1eb;color:#35624a;font-size:9px}.columns ol{margin:8px 0 0;padding-left:19px;font-size:10px;line-height:1.7}.columns dl,.quality{display:grid;grid-template-columns:76px minmax(0,1fr);gap:6px;margin:0;font-size:9px}.columns dt,.quality dt{color:#7b8980}.columns dd,.quality dd{margin:0;overflow-wrap:anywhere}.sources,.script{margin-top:10px}.source{padding:9px 0;border-top:1px solid #edf0ee}.source:first-of-type{border-top:0}.source>div{display:flex;justify-content:space-between;gap:10px}.source strong{font-size:10px}.source span,.source small{overflow-wrap:anywhere;color:#7b8980;font-size:8px}.source blockquote{margin:7px 0;padding-left:9px;border-left:2px solid #6fa187;color:#405048;font-size:10px;line-height:1.6}.scene{display:grid;grid-template-columns:25px minmax(0,1fr);gap:9px;padding:10px 0;border-top:1px solid #edf0ee}.scene>span{display:flex;width:23px;height:23px;align-items:center;justify-content:center;background:#173f31;color:#fff;font-size:9px}.scene strong{font-size:10px}.scene p{margin:4px 0;color:#4f5e56;font-size:10px;line-height:1.55}.scene small{color:#829087;font-size:8px}.audio{display:flex;gap:8px;margin-top:11px;padding:9px;background:#f1f6f3;color:#365847}.audio div{display:flex;flex-direction:column}.audio strong{font-size:10px}.audio small{font-size:8px}aside video{width:100%;margin-top:11px;background:#111a16;aspect-ratio:16/9}.render{width:100%;margin-top:10px}.quality{margin:12px 0;padding-top:11px;border-top:1px solid #e1e7e3}.hash{font-family:monospace}.downloads{display:grid;grid-template-columns:1fr 1fr;gap:6px}.empty{display:flex;min-height:190px;flex-direction:column;align-items:center;justify-content:center;color:#78867e;text-align:center}.empty strong{margin-top:8px;font-size:11px}.empty span{max-width:360px;margin-top:4px;font-size:9px;line-height:1.5}.empty.initial,.empty.top{margin-top:14px;border:1px solid #d9e1dc;background:#fff}.empty.top{min-height:150px}.spin{animation:spin 1s linear infinite}@keyframes spin{to{transform:rotate(360deg)}}@media(max-width:900px){.chapter-workspace header{flex-direction:column}.boundary{max-width:none}.controls{grid-template-columns:1fr 1fr}.controls button{align-self:end}.layout{grid-template-columns:1fr}}@media(max-width:520px){.chapter-workspace h1{font-size:20px}.controls{grid-template-columns:1fr}.project-picker{align-items:stretch;flex-direction:column}.project-picker button{width:100%}.columns{grid-template-columns:1fr}.evidence,aside{padding:10px}.source>div{flex-direction:column;gap:3px}.panel-head{flex-direction:column}.downloads{grid-template-columns:1fr 1fr}}
.layout{align-items:start}
.watch-proof{display:flex;flex-direction:column;gap:5px;margin-top:10px;padding:10px;border:1px solid #dce7e0;background:#f5f9f6;font-size:9px}.watch-proof span{display:flex;align-items:center;gap:5px}.watch-proof strong{color:#35654c}.watch-proof small{color:#748178}.watch-proof div{display:grid;grid-template-columns:1fr 1fr;gap:6px}.watch-proof button{min-height:32px;border:1px solid #c8d6cd;background:#fff}.practice-workspace{margin-top:14px;padding:15px;border:1px solid #d9e1dc;background:#fff}.practice-head{display:flex;justify-content:space-between;gap:18px;padding-bottom:12px;border-bottom:1px solid #e4eae6}.practice-head h2{margin:0;font-size:16px;letter-spacing:0}.practice-head small{color:#718078;font-size:9px}.ability{display:grid;grid-template-columns:auto auto;gap:0 10px;align-items:center;min-width:135px;padding:8px 11px;background:#173f31;color:#fff}.ability span,.ability small{font-size:8px}.ability strong{grid-row:1/3;grid-column:2;font-size:24px}.binding-builder{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:12px}.binding-builder>div{padding:11px;border:1px solid #e0e7e3}.binding-builder h3,.question-card h3,.lab-card h3,.evidence-ledger h3{margin:0 0 9px;font-size:11px;letter-spacing:0}.binding-builder label{display:flex;gap:8px;padding:8px 0;border-top:1px solid #edf1ee;font-size:9px}.binding-builder label span{display:flex;flex-direction:column;gap:2px}.binding-builder label strong{color:#397055}.binding-builder p{color:#78867e;font-size:9px}.binding-builder>button{grid-column:1/-1;justify-self:end;display:flex;align-items:center;gap:6px;min-height:36px;padding:0 13px;border:0;background:#173f31;color:#fff}.version-line{display:flex;align-items:center;gap:10px;margin-top:12px;padding:8px 10px;background:#f2f6f3;font-size:9px}.version-line code{color:#4f6d5c}.version-line button{display:flex;align-items:center;gap:4px;margin-left:auto;border:0;background:transparent;color:#366a50}.practice-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;margin-top:10px}.question-card,.lab-card{padding:12px;border:1px solid #dce4df}.card-meta{display:flex;justify-content:space-between;gap:8px}.card-meta span{padding:3px 6px;background:#e6f1eb;color:#35624a;font-size:8px}.card-meta small{color:#7a877f;font-size:8px}.question-card h3,.lab-card h3{margin-top:10px;line-height:1.5}.answer-options{display:flex;flex-direction:column;gap:5px}.answer-options label{display:grid;grid-template-columns:auto 22px minmax(0,1fr);gap:7px;align-items:center;padding:7px;border:1px solid #e1e7e3;font-size:9px}.answer-options b{display:flex;width:20px;height:20px;align-items:center;justify-content:center;background:#edf3ef}.boolean-row,.blank-row{display:flex;gap:6px}.boolean-row button,.blank-row input{min-height:34px;flex:1;border:1px solid #d2ddd6;background:#fff;padding:0 9px}.submit-practice,.external-practice{display:flex;align-items:center;gap:8px;margin-top:10px;padding-top:9px;border-top:1px solid #edf1ee;font-size:8px}.submit-practice span{display:flex;align-items:center;gap:4px;color:#65756c}.submit-practice button,.external-practice a,.lab-card a,.lab-card button{display:flex;align-items:center;justify-content:center;gap:4px;min-height:32px;margin-left:auto;padding:0 9px;border:1px solid #173f31;background:#173f31;color:#fff;text-decoration:none}.external-practice span{flex:1}.lab-card p{font-size:9px;line-height:1.6}.lab-card>div:last-child{display:flex;gap:6px}.lab-card>div:last-child a,.lab-card>div:last-child button{margin-left:0}.lab-card button{background:#fff;color:#173f31}.evidence-ledger{margin-top:10px;padding:11px;border:1px solid #cfe1d5;background:#f2f8f4}.evidence-ledger>div{display:grid;grid-template-columns:20px minmax(0,1fr) auto;gap:7px;align-items:center;padding:7px 0;border-top:1px solid #dce9e0;font-size:9px;color:#2f6248}.evidence-ledger span{display:flex;flex-direction:column}.evidence-ledger code{font-size:8px;color:#6f7e75}
@media(max-width:900px){.practice-grid{grid-template-columns:1fr}}
@media(max-width:520px){.binding-builder{grid-template-columns:1fr}.binding-builder>button{grid-column:1}.practice-workspace{padding:10px}.practice-head{flex-direction:column;gap:3px}.version-line{align-items:flex-start;flex-direction:column}.version-line button{margin-left:0}.submit-practice,.external-practice{align-items:stretch;flex-direction:column}.submit-practice button,.external-practice a{width:100%;margin-left:0}.card-meta{flex-direction:column}.evidence-ledger>div{grid-template-columns:20px minmax(0,1fr)}.evidence-ledger code{grid-column:2}}
</style>
