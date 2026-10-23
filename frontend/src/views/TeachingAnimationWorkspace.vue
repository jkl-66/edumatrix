<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { CircleAlert, Gauge, Pause, Play, RotateCcw, Save, ShieldCheck, SkipForward, Table2 } from '@lucide/vue'
import {
  createTeachingAnimation, createTeachingAnimationVersion, getTeachingAnimation,
  listTeachingAnimations, listTeachingAnimationTemplates, saveTeachingAnimationPlayback,
} from '../api'

const templates = ref([])
const projects = ref([])
const selectedId = ref('')
const project = ref(null)
const parameters = ref({})
const title = ref('梯度下降参数实验')
const loading = ref(true)
const busy = ref(false)
const error = ref('')
const notice = ref('')
const staticMode = ref(false)
const canvasUnavailable = ref(false)
const canvas = ref(null)
let timer = null

const template = computed(() => templates.value[0] || null)
const frames = computed(() => project.value?.current_version?.frames || [])
const currentFrame = computed(() => frames.value[project.value?.current_frame || 0] || null)
const showStatic = computed(() => staticMode.value || canvasUnavailable.value)
const isPlaying = computed(() => project.value?.playback_status === 'playing')

function message(caught, fallback) {
  const detail = caught?.response?.data?.detail
  return detail?.message || (typeof detail === 'string' ? detail : '') || caught?.message || fallback
}

function defaults() {
  const specs = template.value?.parameters || {}
  return Object.fromEntries(Object.entries(specs).map(([key, spec]) => [key, spec.default]))
}

function applyProject(value) {
  project.value = value
  selectedId.value = value?.id || ''
  if (value?.current_version?.parameters) parameters.value = { ...value.current_version.parameters }
  if (value?.title) title.value = value.title
  projects.value = projects.value.map(item => item.id === value.id ? { ...item, ...value } : item)
  if (!projects.value.some(item => item.id === value.id)) projects.value.unshift(value)
  nextTick(draw)
}

async function load() {
  loading.value = true; error.value = ''
  try {
    const [templateData, projectData] = await Promise.all([
      listTeachingAnimationTemplates(), listTeachingAnimations(),
    ])
    templates.value = templateData.items
    projects.value = projectData.items
    parameters.value = defaults()
    if (projects.value.length) await chooseProject(projects.value[0].id)
  } catch (caught) { error.value = message(caught, '教学动画工作台加载失败') }
  finally { loading.value = false }
}

async function chooseProject(id) {
  stopTimer()
  busy.value = true; error.value = ''
  try { applyProject(await getTeachingAnimation(id)) }
  catch (caught) { error.value = message(caught, '动画项目加载失败') }
  finally { busy.value = false }
}

async function createProject() {
  busy.value = true; error.value = ''; notice.value = ''
  try {
    const result = await createTeachingAnimation({
      title: title.value, template_id: template.value.id,
      parameters: parameters.value, course_id: null,
    })
    applyProject(result)
    notice.value = '动画项目和首个不可变参数版本已创建。'
  } catch (caught) { error.value = message(caught, '动画项目创建失败') }
  finally { busy.value = false }
}

async function saveVersion() {
  if (!project.value) return
  stopTimer(); busy.value = true; error.value = ''; notice.value = ''
  try {
    const result = await createTeachingAnimationVersion(project.value.id, {
      parameters: parameters.value, expected_lock_version: project.value.lock_version,
    })
    applyProject(result)
    notice.value = result.version_created ? '新参数版本已生成，播放位置已重置。' : '参数未变化，继续使用现有不可变版本。'
  } catch (caught) {
    error.value = message(caught, '参数版本保存失败')
    if (caught?.kind === 'conflict') await chooseProject(project.value.id)
  } finally { busy.value = false }
}

async function persistFrame(frame, status = 'paused') {
  if (!project.value || busy.value) return false
  busy.value = true; error.value = ''
  try {
    const result = await saveTeachingAnimationPlayback(project.value.id, {
      current_frame: frame, playback_status: status,
      expected_lock_version: project.value.lock_version,
    })
    applyProject(result)
    return true
  } catch (caught) {
    error.value = message(caught, '播放位置保存失败')
    stopTimer()
    if (caught?.kind === 'conflict') await chooseProject(project.value.id)
    return false
  } finally { busy.value = false }
}

function stopTimer() {
  if (timer) window.clearInterval(timer)
  timer = null
}

async function play() {
  if (!project.value || busy.value) return
  if (project.value.current_frame >= project.value.max_frame) await persistFrame(0, 'paused')
  if (!await persistFrame(project.value.current_frame, 'playing')) return
  stopTimer()
  timer = window.setInterval(async () => {
    if (busy.value || !project.value) return
    const next = Math.min(project.value.current_frame + 1, project.value.max_frame)
    const status = next >= project.value.max_frame ? 'paused' : 'playing'
    await persistFrame(next, status)
    if (status === 'paused') stopTimer()
  }, 420)
}

async function pause() { stopTimer(); await persistFrame(project.value.current_frame, 'paused') }
async function step() { stopTimer(); await persistFrame(Math.min(project.value.current_frame + 1, project.value.max_frame), 'paused') }
async function reset() { stopTimer(); await persistFrame(0, 'paused') }

function draw() {
  if (showStatic.value || !canvas.value || !frames.value.length) return
  const context = canvas.value.getContext?.('2d')
  if (!context) { canvasUnavailable.value = true; return }
  const width = canvas.value.width
  const height = canvas.value.height
  const pad = { left: 50, right: 20, top: 24, bottom: 40 }
  context.clearRect(0, 0, width, height)
  context.fillStyle = '#f8faf8'; context.fillRect(0, 0, width, height)
  const params = project.value.current_version.parameters
  const xs = frames.value.map(item => item.x).concat([params.target_x])
  const span = Math.max(1, Math.max(...xs) - Math.min(...xs))
  const minX = Math.min(...xs) - span * 0.18
  const maxX = Math.max(...xs) + span * 0.18
  const maxLoss = Math.max(1, ...frames.value.map(item => item.loss)) * 1.12
  const px = x => pad.left + ((x - minX) / (maxX - minX)) * (width - pad.left - pad.right)
  const py = loss => height - pad.bottom - (loss / maxLoss) * (height - pad.top - pad.bottom)
  context.strokeStyle = '#cdd7d0'; context.lineWidth = 1
  context.beginPath(); context.moveTo(pad.left, pad.top); context.lineTo(pad.left, height - pad.bottom); context.lineTo(width - pad.right, height - pad.bottom); context.stroke()
  context.strokeStyle = '#365f45'; context.lineWidth = 2
  context.beginPath()
  for (let i = 0; i <= 160; i += 1) {
    const x = minX + (i / 160) * (maxX - minX)
    const y = params.curvature * ((x - params.target_x) ** 2)
    if (i === 0) context.moveTo(px(x), py(Math.min(y, maxLoss)))
    else context.lineTo(px(x), py(Math.min(y, maxLoss)))
  }
  context.stroke()
  const visible = frames.value.slice(0, (project.value.current_frame || 0) + 1)
  context.strokeStyle = '#c05a3b'; context.lineWidth = 2; context.beginPath()
  visible.forEach((frame, index) => index ? context.lineTo(px(frame.x), py(frame.loss)) : context.moveTo(px(frame.x), py(frame.loss)))
  context.stroke()
  visible.forEach((frame, index) => {
    context.beginPath(); context.fillStyle = index === visible.length - 1 ? '#c43f2c' : '#f0a25e'
    context.arc(px(frame.x), py(frame.loss), index === visible.length - 1 ? 5 : 3, 0, Math.PI * 2); context.fill()
  })
  context.fillStyle = '#59665d'; context.font = '12px sans-serif'
  context.fillText('参数 x', width / 2 - 18, height - 12)
  context.save(); context.translate(14, height / 2 + 20); context.rotate(-Math.PI / 2); context.fillText('损失 L(x)', 0, 0); context.restore()
}

watch([() => project.value?.current_frame, showStatic], () => nextTick(draw))
onMounted(load)
onBeforeUnmount(stopTimer)
</script>

<template>
  <main class="animation" data-testid="teaching-animation-workspace">
    <header class="animation__header">
      <div><p class="eyebrow">DETERMINISTIC TEACHING ANIMATION</p><h1>参数驱动教学动画</h1><p>调整真实参数，观察服务端确定性计算产生的逐帧优化轨迹。</p></div>
      <div class="trust"><ShieldCheck :size="18" /><span>本地确定性引擎</span><small>无随机结果 · 无外部模型</small></div>
    </header>

    <p v-if="error" class="notice notice--error"><CircleAlert :size="16" />{{ error }}</p>
    <p v-if="notice" class="notice notice--success">{{ notice }}</p>
    <p v-if="loading" class="notice">正在恢复动画项目与播放位置...</p>

    <div v-else class="workspace-grid">
      <aside class="projects">
        <div class="section-title"><strong>动画项目</strong><small>{{ projects.length }} 项</small></div>
        <button v-for="item in projects" :key="item.id" data-testid="animation-project" :class="{ active: selectedId === item.id }" @click="chooseProject(item.id)">
          <Gauge :size="16" /><span><strong>{{ item.title }}</strong><small>帧 {{ item.current_frame }}/{{ item.max_frame }} · {{ item.playback_status }}</small></span>
        </button>
        <p v-if="!projects.length" class="empty">尚无项目。使用右侧默认模板创建首个参数实验。</p>
      </aside>

      <section class="workspace">
        <div class="section-title"><strong>{{ template?.title }}</strong><small>{{ template?.formula.engine_version }}</small></div>
        <p class="summary">{{ template?.description }}</p>

        <div class="parameter-grid" data-testid="animation-parameters">
          <label class="title-field">项目名称<input v-model="title" maxlength="256" aria-label="项目名称" /></label>
          <label v-for="(spec, key) in template?.parameters" :key="key">
            <span>{{ spec.label }} <output>{{ parameters[key] }}</output></span>
            <input v-if="key !== 'step_count'" v-model.number="parameters[key]" type="range" :aria-label="spec.label" :min="spec.minimum" :max="spec.maximum" :step="spec.step" />
            <input v-else v-model.number="parameters[key]" type="number" :aria-label="spec.label" :min="spec.minimum" :max="spec.maximum" :step="spec.step" />
            <small>{{ spec.minimum }} 至 {{ spec.maximum }}</small>
          </label>
        </div>

        <div class="formula-strip">
          <code>{{ template?.formula.loss }}</code><code>{{ template?.formula.update }}</code><strong>{{ template?.formula.stability }}</strong>
        </div>

        <div class="version-actions">
          <button v-if="!project" class="primary" :disabled="busy" @click="createProject"><Save :size="15" />创建动画项目</button>
          <button v-else :disabled="busy" @click="saveVersion"><Save :size="15" />保存参数版本</button>
          <button :aria-pressed="showStatic" title="切换静态数据视图" @click="staticMode = !staticMode"><Table2 :size="15" />{{ showStatic ? '显示动画画布' : '静态数据视图' }}</button>
        </div>

        <template v-if="project">
          <div class="player" data-testid="animation-player">
            <div class="controls">
              <button v-if="!isPlaying" title="播放" aria-label="播放" :disabled="busy" @click="play"><Play :size="17" /></button>
              <button v-else title="暂停" aria-label="暂停" :disabled="busy" @click="pause"><Pause :size="17" /></button>
              <button title="单步" aria-label="单步" :disabled="busy || project.current_frame >= project.max_frame" @click="step"><SkipForward :size="17" /></button>
              <button title="重置" aria-label="重置" :disabled="busy" @click="reset"><RotateCcw :size="17" /></button>
              <div class="progress"><span :style="{ width: `${project.max_frame ? project.current_frame / project.max_frame * 100 : 0}%` }"></span></div>
              <strong data-testid="frame-counter">{{ project.current_frame }} / {{ project.max_frame }}</strong>
            </div>

            <canvas v-show="!showStatic" ref="canvas" width="760" height="360" aria-label="梯度下降损失曲线和迭代轨迹"></canvas>
            <div v-if="showStatic" class="static-view" data-testid="animation-static-fallback">
              <p>静态降级视图：无需 Canvas，逐帧数据仍可完整检查。</p>
              <div class="table-wrap"><table><thead><tr><th>帧</th><th>x</th><th>损失</th><th>梯度</th><th>距目标</th><th>状态</th></tr></thead><tbody><tr v-for="frame in frames" :key="frame.index" :class="{ current: frame.index === project.current_frame }"><td>{{ frame.index }}</td><td>{{ frame.x }}</td><td>{{ frame.loss }}</td><td>{{ frame.gradient }}</td><td>{{ frame.distance_to_target }}</td><td>{{ frame.state }}</td></tr></tbody></table></div>
            </div>
          </div>

          <div v-if="currentFrame" class="metrics" data-testid="animation-state">
            <article><span>当前 x</span><strong>{{ currentFrame.x }}</strong></article>
            <article><span>当前损失</span><strong>{{ currentFrame.loss }}</strong></article>
            <article><span>当前梯度</span><strong>{{ currentFrame.gradient }}</strong></article>
            <article><span>计算状态</span><strong>{{ currentFrame.state === 'converged' ? '已收敛' : '优化中' }}</strong></article>
          </div>

          <div class="version-history">
            <div class="section-title"><strong>不可变版本历史</strong><small>{{ project.versions.length }} 版</small></div>
            <div v-for="version in project.versions" :key="version.id" data-testid="animation-version"><strong>v{{ version.version_number }}</strong><span>学习率 {{ version.parameters.learning_rate }} · 曲率 {{ version.parameters.curvature }} · {{ version.quality.frame_count }} 帧</span><code>{{ version.content_hash.slice(0, 12) }}</code></div>
          </div>
        </template>
      </section>
    </div>
  </main>
</template>

<style scoped>
.animation{max-width:1180px;margin:0 auto;color:#26332b}.animation__header{display:flex;justify-content:space-between;gap:24px;padding-bottom:20px;border-bottom:1px solid #dbe2dc}.eyebrow{margin:0 0 7px;color:#456b52;font-size:10px;font-weight:800}.animation h1{margin:0;font-size:23px;letter-spacing:0}.animation__header p:last-child{margin:7px 0 0;color:#68746c;font-size:13px}.trust{display:grid;grid-template-columns:auto 1fr;align-content:center;min-width:215px;padding:12px 14px;border:1px solid #cfe0d4;background:#f2f8f4;color:#355b42}.trust svg{grid-row:1/3;margin-right:8px}.trust span{font-size:12px;font-weight:750}.trust small{font-size:9px;color:#708078}.notice{display:flex;gap:8px;margin:14px 0;padding:10px;background:#f4f6f4;font-size:12px}.notice--error{background:#fff1ef;color:#88483f}.notice--success{background:#edf7f0;color:#356044}.workspace-grid{display:grid;grid-template-columns:230px minmax(0,1fr);gap:16px;margin-top:18px}.projects,.workspace{border:1px solid #dce2de;background:#fff}.projects{padding:12px}.workspace{min-width:0;padding:18px}.section-title{display:flex;justify-content:space-between;align-items:center;padding-bottom:10px;border-bottom:1px solid #e5e9e6}.section-title strong{font-size:12px}.section-title small{color:#7b867f;font-size:9px}.projects>button{display:flex;width:100%;gap:8px;padding:11px 7px;text-align:left;border:0;border-bottom:1px solid #edf0ee;background:transparent;color:#405047}.projects>button.active{background:#f0f6f2}.projects button span,.projects button strong,.projects button small{display:block}.projects button strong{font-size:10px}.projects button small{margin-top:3px;color:#758078;font-size:8px}.empty,.summary{color:#6e7a72;font-size:11px;line-height:1.6}.parameter-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;padding:14px;background:#f6f8f6}.parameter-grid label{min-width:0;color:#617067;font-size:10px}.parameter-grid label span{display:flex;justify-content:space-between}.parameter-grid output{color:#315e40;font-weight:800}.parameter-grid input{box-sizing:border-box;width:100%;margin-top:7px;accent-color:#477054}.parameter-grid input[type=number],.parameter-grid .title-field input{height:32px;padding:0 8px;border:1px solid #cfd9d1;background:#fff}.parameter-grid label>small{display:block;margin-top:4px;color:#8a948d;font-size:8px}.title-field{grid-column:span 2}.formula-strip{display:grid;gap:5px;margin-top:10px;padding:11px 13px;border-left:3px solid #557662;background:#f2f6f3}.formula-strip code,.formula-strip strong{font-size:10px;white-space:normal}.formula-strip strong{color:#395d44}.version-actions,.controls{display:flex;align-items:center;flex-wrap:wrap;gap:8px;margin-top:12px}.version-actions button,.controls button{display:inline-flex;align-items:center;justify-content:center;gap:6px;min-height:34px;padding:0 11px;border:1px solid #ccd7cf;background:#fff;color:#435047;font-size:10px}.version-actions button.primary{border-color:#456d53;background:#456d53;color:#fff}.version-actions button:disabled,.controls button:disabled{opacity:.42}.player{margin-top:14px;border:1px solid #dce3de}.controls{margin:0;padding:10px 12px;border-bottom:1px solid #e0e5e1;background:#f7f9f7}.controls button{width:34px;padding:0}.progress{flex:1;min-width:110px;height:5px;background:#dce4de}.progress span{display:block;height:100%;background:#c45a3d;transition:width .2s}.controls>strong{min-width:48px;font-size:10px;text-align:right}.player canvas{display:block;width:100%;aspect-ratio:19/9;max-height:420px;background:#f8faf8}.static-view{padding:12px}.static-view>p{margin:0 0 9px;color:#5d6961;font-size:10px}.table-wrap{max-height:320px;overflow:auto}.static-view table{width:100%;border-collapse:collapse;font-size:9px}.static-view th,.static-view td{padding:7px;border-bottom:1px solid #e6ebe7;text-align:right}.static-view th:first-child,.static-view td:first-child{text-align:left}.static-view tr.current{background:#fff0e9;color:#8b3e28}.metrics{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));margin-top:12px;border:1px solid #dce3de}.metrics article{padding:12px;border-right:1px solid #e2e7e3}.metrics article:last-child{border:0}.metrics span,.metrics strong{display:block}.metrics span{color:#758078;font-size:9px}.metrics strong{margin-top:5px;font-size:15px;overflow-wrap:anywhere}.version-history{margin-top:14px}.version-history>div:not(.section-title){display:grid;grid-template-columns:45px 1fr auto;gap:8px;padding:9px 4px;border-bottom:1px solid #edf0ee;font-size:9px}.version-history code{color:#69766d}@media(max-width:800px){.animation__header{flex-direction:column}.trust{min-width:0}.workspace-grid{grid-template-columns:1fr}.projects{max-height:170px;overflow:auto}.parameter-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}@media(max-width:430px){.workspace{padding:12px}.parameter-grid,.metrics{grid-template-columns:1fr}.title-field{grid-column:auto}.metrics article{border-right:0;border-bottom:1px solid #e2e7e3}.version-history>div:not(.section-title){grid-template-columns:36px 1fr}.version-history code{grid-column:2}.controls{gap:6px}.player canvas{aspect-ratio:1/1}}
</style>
