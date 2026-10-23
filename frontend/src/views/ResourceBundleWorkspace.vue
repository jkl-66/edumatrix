<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  AlertTriangle,
  ArrowLeft,
  ArrowRight,
  BookOpen,
  Boxes,
  Braces,
  Check,
  CircleDashed,
  Clock3,
  Presentation,
  FlaskConical,
  ListChecks,
  Map,
  MessageSquareText,
  PlayCircle,
  RefreshCw,
  RotateCcw,
  Sparkles,
} from '@lucide/vue'
import {
  executeGenerationJob,
  getResourceBundle,
  getGenerationJob,
  recoverGenerationJob,
  retryGenerationItem,
} from '../api'
import ResourceFloatingQa from '../components/ResourceFloatingQa.vue'

const route = useRoute()
const router = useRouter()
const loading = ref(true)
const busyType = ref('')
const error = ref('')
const notice = ref('')
const job = ref(null)
const qaOpen = ref(false)
let pollTimer = null
const isPersonalCopy = computed(() => route.query.mode === 'personal-copy')

const resourceMeta = {
  handout: { label: '个性化讲义', purpose: '结构化理解概念、例子与练习', icon: BookOpen },
  mind_map: { label: '思维导图', purpose: '梳理概念关系和学习顺序', icon: Map },
  quiz: { label: '测验题资源', purpose: '通过即时练习检验理解', icon: ListChecks },
  training_task: { label: '实训任务书', purpose: '明确工程目标、步骤和提交物', icon: Braces },
  code_sandbox: { label: '代码沙盒任务', purpose: '进入真实代码编辑与运行环境', icon: PlayCircle },
  video: { label: '视频推荐', purpose: '按知识点观看讲解片段', icon: Clock3 },
  deck: { label: 'PPT / 网页课件', purpose: '以视觉化课件回顾重点', icon: Presentation },
  interactive_model: { label: '可交互模型', purpose: '调整参数并观察模型规律', icon: FlaskConical },
  feynman: { label: '费曼复述任务', purpose: '用自己的话解释并接受追问', icon: MessageSquareText },
}

const resourceTypeAliases = {
  code: 'code_sandbox',
  exercise: 'quiz',
  ppt: 'deck',
  animation: 'interactive_model',
  lab: 'interactive_model',
}

const items = computed(() => (job.value?.items || []).map(item => ({
  ...resourceMeta[resourceTypeAliases[item.type] || item.type],
  ...item,
})))
const completedCount = computed(() => items.value.filter(item => item.state === 'succeeded').length)
const failedCount = computed(() => items.value.filter(item => item.state === 'failed').length)
const activeCount = computed(() => items.value.filter(item => ['requested', 'queued', 'running'].includes(item.state)).length)
const expectedCount = computed(() => isPersonalCopy.value ? items.value.length : 9)
const progress = computed(() => expectedCount.value ? Math.round((completedCount.value / expectedCount.value) * 100) : 0)
const context = computed(() => job.value?.context || {})
const qaSourceRefIds = computed(() => [...new Set((job.value?.items || []).flatMap(item => item.input?.source_ref_ids || item.source_ref_ids || []))])
const allDone = computed(() => expectedCount.value > 0 && completedCount.value === expectedCount.value)
const hasInterruptedItems = computed(() => items.value.some(item => item.state === 'running'))
const isPolling = computed(() => Boolean(job.value && activeCount.value && !allDone.value))
const statusCopy = computed(() => {
  if (isPersonalCopy.value) {
    if (allDone.value) return { title: '个人资源包已就绪', detail: '这是保存到当前账号的独立副本，可以直接打开其中资源。' }
    return { title: '个人资源包已保留', detail: '可用资源可以继续学习；暂不可用项仍保留发布时快照。' }
  }
  if (allDone.value) return { title: '完整资源包已就绪', detail: '九项资源已分别归档，可以按今日任务顺序开始学习。' }
  if (failedCount.value) return { title: `${completedCount.value} 项已归档，${failedCount.value} 项需要处理`, detail: '已完成的资源会保留，只需重试失败项。' }
  if (isPolling.value) return { title: '正在准备你的学习资源', detail: '可以离开此页，稍后回来会从当前进度继续。' }
  return { title: '资源包正在等待处理', detail: '刷新状态，或在任务中断后恢复未完成项。' }
})

function message(exception, fallback) {
  const detail = exception?.response?.data?.detail
  return detail?.message || (typeof detail === 'string' ? detail : '') || exception?.message || fallback
}

function stateLabel(state) {
  return {
    requested: '等待开始',
    queued: '排队中',
    running: '生成中',
    succeeded: '已归档',
    failed: '生成失败',
    cancelled: '已取消',
    unavailable: '暂不可用',
  }[state] || '等待处理'
}

function stateIcon(item) {
  if (item.state === 'succeeded') return Check
  if (item.state === 'failed') return AlertTriangle
  if (item.state === 'running') return RefreshCw
  return CircleDashed
}

function learnerCompletionRule(item) {
  const raw = String(item?.completion_rule || '').trim()
  if (!raw) return '打开资源并完成页面中的学习活动。'
  return raw
    .replace(/查看其课程来源/g, '完成页面中的学习检查')
    .replace(/查看课程来源/g, '完成页面中的学习检查')
    .replace(/打开至少一个来源/g, '打开至少一个相关内容')
    .replace(/有来源的讲解片段/g, '讲解片段')
    .replace(/可追溯学习证据/g, '学习记录')
    .replace(/可追溯证据/g, '学习记录')
    .replace(/课程来源/g, '相关内容')
    .replace(/来源/g, '相关内容')
}

async function loadJob({ quiet = false } = {}) {
  if (!quiet) loading.value = true
  error.value = ''
  try {
    const bundleId = String(route.params.bundleId || '')
    job.value = isPersonalCopy.value
      ? adaptPersonalBundle(await getResourceBundle(bundleId))
      : await getGenerationJob(bundleId)
    schedulePoll()
  } catch (exception) {
    error.value = message(exception, '资源包状态加载失败，请稍后重试。')
    stopPolling()
  } finally {
    loading.value = false
  }
}

function adaptPersonalBundle(bundle) {
  const version = bundle.current_version || {}
  const bundleItems = version.items || []
  return {
    job_id: bundle.id,
    course_id: bundle.course_id,
    context: {
      course_title: '个人学习空间',
      knowledge_point_title: bundle.title,
      learning_goal: bundle.learning_objective,
      profile_adaptation: '发布者画像已移除，副本只保留适合你继续学习的内容结构。',
      mastery_summary: '保存与浏览个人副本不会改变掌握度。',
      recent_learning_summary: '上游更新或下架不会覆盖这份个人副本。',
      source_count: bundleItems.length,
    },
    items: bundleItems.map(item => ({
      type: resourceTypeAliases[item.resource_type] || item.resource_type,
      label: item.title || resourceMeta[resourceTypeAliases[item.resource_type] || item.resource_type]?.label || '学习资源',
      purpose: item.marketplace_copy_notice || resourceMeta[resourceTypeAliases[item.resource_type] || item.resource_type]?.purpose || '继续使用保存时的冻结学习内容',
      completion_rule: '打开资源并按页面要求完成学习',
      state: item.availability?.status === 'available' && item.route ? 'succeeded' : 'unavailable',
      resource: item.route ? { route: item.route } : null,
      failure: item.availability?.reason ? { message: item.availability.reason } : null,
    })),
  }
}

function stopPolling() {
  if (pollTimer) window.clearTimeout(pollTimer)
  pollTimer = null
}

function schedulePoll() {
  stopPolling()
  if (!isPolling.value) return
  pollTimer = window.setTimeout(async () => {
    await loadJob({ quiet: true })
  }, 2500)
}

async function runLocalDemo(taskId) {
  try {
    return await executeGenerationJob(taskId)
  } catch (exception) {
    const code = exception?.response?.data?.detail?.code || exception?.detail?.code
    if (code !== 'resource_generation.demo_disabled') throw exception
    return getGenerationJob(taskId)
  }
}

async function retryItem(item) {
  if (busyType.value || item.state !== 'failed') return
  busyType.value = item.type
  error.value = ''
  notice.value = ''
  try {
    const retried = await retryGenerationItem(job.value.job_id, item.type)
    job.value = await runLocalDemo(retried.job_id)
    notice.value = `${item.label}已重新处理，其他已完成资源保持不变。`
    schedulePoll()
  } catch (exception) {
    error.value = message(exception, `${item.label}重试失败，请稍后再试。`)
  } finally {
    busyType.value = ''
  }
}

async function recoverInterrupted() {
  if (busyType.value || !hasInterruptedItems.value) return
  busyType.value = 'recover'
  error.value = ''
  notice.value = ''
  try {
    const recovered = await recoverGenerationJob(job.value.job_id)
    job.value = await runLocalDemo(recovered.job_id)
    notice.value = '未完成项已恢复，已归档资源保持不变。'
    schedulePoll()
  } catch (exception) {
    error.value = message(exception, '恢复失败，请稍后重试。')
  } finally {
    busyType.value = ''
  }
}

function openResource(item) {
  if (!item.resource?.route) return
  const target = router.resolve(item.resource.route)
  router.push({
    path: target.path,
    query: {
      ...target.query,
      course_id: route.query.course_id || job.value?.course_id || undefined,
      path_id: job.value?.manifest?.path_id || route.query.path_id || undefined,
      task_id: job.value?.manifest?.task_id || route.query.return_task || undefined,
    },
  })
}

function returnToTodayTask() {
  if (isPersonalCopy.value) {
    router.push('/marketplace/mine')
    return
  }
  router.push({
    name: 'LearningPath',
    query: {
      course_id: route.query.course_id || job.value?.course_id,
      node_id: job.value?.manifest?.task_id || route.query.return_task || undefined,
    },
  })
}

function openResourceCenter() {
  router.push({ name: 'WorkspaceResources', query: { course_id: route.query.course_id || job.value?.course_id } })
}

onMounted(loadJob)
onUnmounted(stopPolling)
</script>

<template>
  <main class="bundle-page" data-testid="resource-bundle-workspace">
    <button type="button" class="back-link" @click="returnToTodayTask">
      <ArrowLeft :size="17" /> {{ isPersonalCopy ? '返回我的内容' : '返回今日任务' }}
    </button>

    <section v-if="loading" class="loading-surface" aria-live="polite">
      <div class="skeleton skeleton--title" />
      <div class="skeleton skeleton--copy" />
      <div v-for="index in 5" :key="index" class="skeleton skeleton--row" />
    </section>

    <section v-else-if="error && !job" class="error-surface" role="alert">
      <AlertTriangle :size="24" />
      <div>
        <h1>暂时无法恢复资源包</h1>
        <p>{{ error }}</p>
      </div>
      <button type="button" class="secondary-button" @click="loadJob()">
        <RefreshCw :size="16" /> 重新加载
      </button>
    </section>

    <template v-else-if="job">
      <header class="page-header">
        <div>
          <p class="eyebrow">{{ context.course_title || '当前课程' }} · 今日知识点 · 完整资源包</p>
          <h1>{{ context.knowledge_point_title || '当前知识点' }}</h1>
          <p>{{ statusCopy.detail }}</p>
        </div>
        <div class="status-block" :class="{ 'status-block--done': allDone }">
          <Sparkles v-if="allDone" :size="20" />
          <RefreshCw v-else :size="20" :class="{ spin: isPolling }" />
          <div>
            <strong>{{ statusCopy.title }}</strong>
            <span>{{ completedCount }} / {{ expectedCount }} {{ isPersonalCopy ? '项可用' : '已归档' }}</span>
          </div>
        </div>
      </header>

      <section class="context-band" aria-label="本次资源生成信息">
        <div class="context-band__primary">
          <span>课程与学习目标</span>
          <strong>{{ context.course_title || '当前课程' }}</strong>
          <p>{{ context.learning_goal || '完成当前知识点的理解与应用' }}</p>
        </div>
        <div class="context-band__adaptation">
          <span>学习适配</span>
          <p data-testid="resource-bundle-profile-adaptation">资源内容已按当前学习情况调整。</p>
        </div>
      </section>
      <p v-if="error" class="feedback feedback--error" role="alert">
        <AlertTriangle :size="17" /> {{ error }}
      </p>
      <p v-else-if="notice" class="feedback" role="status">
        <Check :size="17" /> {{ notice }}
      </p>

      <section class="progress-section" aria-label="资源包生成进度">
        <div class="progress-section__heading">
          <div>
            <p class="eyebrow">生成进度</p>
            <h2>{{ isPersonalCopy ? '个人副本中的学习资源' : '九项资源分别归档' }}</h2>
          </div>
          <strong>{{ progress }}%</strong>
        </div>
        <div class="progress-track" role="progressbar" :aria-valuenow="progress" aria-valuemin="0" aria-valuemax="100">
          <span :style="{ width: `${progress}%` }" />
        </div>
        <p class="progress-note">{{ isPersonalCopy ? '保存副本不等于完成学习；进入资源并完成练习后，系统才会更新学习进度。' : '生成完成不等于学习完成。进入资源并完成规定动作后，今日任务才会更新。' }}</p>
      </section>

      <section class="resource-surface" aria-label="九类学习资源">
        <article v-for="item in items" :key="item.type" class="resource-row" :data-state="item.state" :data-testid="`bundle-item-${item.type}`">
          <div class="resource-row__icon"><component :is="item.icon || Boxes" :size="21" /></div>
          <div class="resource-row__identity">
            <strong>{{ item.label }}</strong>
            <span>{{ item.purpose }}</span>
          </div>
          <div class="resource-row__rule">
            <span>完成条件</span>
            <p>{{ learnerCompletionRule(item) }}</p>
          </div>
          <div class="resource-row__state" :class="`resource-row__state--${item.state}`">
            <component :is="stateIcon(item)" :size="16" :class="{ spin: item.state === 'running' }" />
            <span>{{ stateLabel(item.state) }}</span>
          </div>
          <div class="resource-row__action">
            <button v-if="item.state === 'succeeded' && item.resource?.route" type="button" class="row-button" @click="openResource(item)">
              打开 <ArrowRight :size="16" />
            </button>
            <button v-else-if="item.state === 'failed' && !isPersonalCopy" type="button" class="row-button row-button--retry" :disabled="Boolean(busyType)" @click="retryItem(item)">
              <RefreshCw :size="16" :class="{ spin: busyType === item.type }" />
              {{ busyType === item.type ? '重试中' : '重试此项' }}
            </button>
            <span v-else>{{ item.state === 'unavailable' ? '保留快照' : '无需操作' }}</span>
          </div>
          <p v-if="item.state === 'failed'" class="resource-row__failure">
            {{ item.failure?.message || '这一项暂时没有生成成功，其他已完成资源不受影响。' }}
          </p>
        </article>
      </section>

      <section class="page-actions">
        <p><RotateCcw :size="16" /> {{ isPersonalCopy ? '个人副本独立保存，上游变化不会覆盖当前内容。' : '离开页面不会丢失进度，返回后会自动恢复当前状态。' }}</p>
        <div>
          <button type="button" class="secondary-button" @click="qaOpen = true"><MessageSquareText :size="16" /> 资源内提问</button>
          <button v-if="hasInterruptedItems" type="button" class="secondary-button" :disabled="Boolean(busyType)" @click="recoverInterrupted">
            <RefreshCw :size="16" :class="{ spin: busyType === 'recover' }" /> 恢复中断项
          </button>
          <button v-if="allDone" type="button" class="secondary-button" @click="openResourceCenter">
            <Boxes :size="16" /> 查看资源中心
          </button>
          <button type="button" class="primary-button" @click="returnToTodayTask">
            {{ isPersonalCopy ? '返回我的内容' : '返回今日任务' }} <ArrowRight :size="17" />
          </button>
        </div>
      </section>
      <ResourceFloatingQa
        :open="qaOpen"
        :course-id="job.course_id || route.query.course_id || ''"
        :knowledge-point-id="job.knowledge_point_id || ''"
        :resource-id="job.job_id || route.params.bundleId || ''"
        :resource-title="context.knowledge_point_title || '当前资源包'"
        :source-ref-ids="qaSourceRefIds"
        @close="qaOpen = false"
      />
    </template>
  </main>
</template>

<style scoped>
.bundle-page{width:min(1120px,calc(100% - 48px));margin:0 auto;padding:28px 0 48px;color:var(--color-text)}
.back-link{display:inline-flex;align-items:center;gap:8px;margin:0 0 18px;padding:0;border:0;background:transparent;color:var(--color-text-secondary);font-size:14px;font-weight:600;cursor:pointer}
.back-link:hover{color:var(--color-text)}
.page-header{display:flex;align-items:flex-start;justify-content:space-between;gap:32px;padding:0 0 24px;border-bottom:1px solid var(--color-border)}
.eyebrow{margin:0 0 6px;color:var(--color-text-secondary);font-size:14px;font-weight:650}
.page-header h1{margin:0;font-family:var(--font-heading);font-size:34px;font-weight:700;line-height:1.3}
.page-header>div>p:last-child{max-width:680px;margin:8px 0 0;color:var(--color-text-secondary);font-size:15px}
.status-block{display:flex;min-width:250px;align-items:center;gap:12px;padding:14px 16px;border:1px solid var(--color-border-strong);border-radius:var(--radius-panel);background:var(--color-surface)}
.status-block svg{color:var(--color-text-secondary)}
.status-block strong,.status-block span{display:block}
.status-block strong{font-size:15px}.status-block span{margin-top:2px;color:var(--color-text-muted);font-size:14px}
.context-band{display:grid;grid-template-columns:1.3fr 1fr;margin-top:18px;border:1px solid var(--color-border);border-radius:var(--radius-panel);background:var(--color-surface);overflow:hidden}
.context-band>div{min-width:0;padding:15px 16px;border-right:1px solid var(--color-border)}
.context-band>div:last-child{border-right:0}.context-band span{display:block;color:var(--color-text-muted);font-size:14px}
.context-band strong{display:block;margin-top:5px;font-size:15px;line-height:1.55}.context-band p{margin:5px 0 0;color:var(--color-text-secondary);font-size:14px;line-height:1.55}.context-band__adaptation{display:flex;flex-direction:column;justify-content:center}
.context-band__source{text-align:center}.context-band__source strong{font-size:20px;font-variant-numeric:tabular-nums}
.feedback{display:flex;align-items:center;gap:8px;margin:16px 0 0;padding:11px 13px;border:1px solid var(--color-border);border-radius:var(--radius-control);background:var(--color-accent-soft);font-size:14px}
.feedback--error{color:var(--color-danger);border-color:#e8caca;background:var(--color-danger-soft)}
.progress-section{padding:26px 0 18px}.progress-section__heading{display:flex;align-items:flex-end;justify-content:space-between;gap:20px}.progress-section h2{margin:0;font-size:20px}.progress-section__heading>strong{font-size:22px;font-variant-numeric:tabular-nums}
.progress-track{height:8px;margin-top:14px;border-radius:4px;background:var(--color-surface-muted);overflow:hidden}.progress-track span{display:block;height:100%;background:var(--color-accent)}
.progress-note{margin:10px 0 0;color:var(--color-text-muted);font-size:14px}
.resource-surface{border:1px solid var(--color-border);border-radius:var(--radius-panel);background:var(--color-surface);overflow:hidden}
.resource-row{position:relative;display:grid;grid-template-columns:42px minmax(160px,.9fr) minmax(250px,1.45fr) 112px 108px;gap:14px;align-items:center;min-height:88px;padding:14px 16px;border-bottom:1px solid var(--color-border)}
.resource-row:last-child{border-bottom:0}.resource-row__icon{display:grid;width:40px;height:40px;place-items:center;border:1px solid var(--color-border);border-radius:var(--radius-control);background:var(--color-surface-subtle);color:var(--color-text-secondary)}
.resource-row__identity strong,.resource-row__identity span{display:block}.resource-row__identity strong{font-size:15px}.resource-row__identity span{margin-top:3px;color:var(--color-text-secondary);font-size:14px;line-height:1.45}
.resource-row__rule span{color:var(--color-text-muted);font-size:14px}.resource-row__rule p{margin:3px 0 0;font-size:14px;line-height:1.45}
.resource-row__state{display:flex;align-items:center;gap:7px;color:var(--color-text-secondary);font-size:14px;font-weight:600}.resource-row__state--failed{color:var(--color-danger)}.resource-row__state--succeeded{color:var(--color-accent)}
.resource-row__action{text-align:right}.resource-row__action>span{color:var(--color-text-muted);font-size:14px}
.row-button{display:inline-flex;min-height:36px;align-items:center;justify-content:center;gap:6px;padding:0 11px;border:1px solid var(--color-border-strong);border-radius:var(--radius-control);background:var(--color-surface);color:var(--color-text);font-size:14px;font-weight:650;cursor:pointer}.row-button:hover{background:var(--color-surface-subtle)}.row-button--retry{color:var(--color-danger)}.row-button:disabled{opacity:.48;cursor:not-allowed}
.resource-row__failure{grid-column:3/6;margin:-4px 0 2px;padding:8px 10px;border:1px solid #e8caca;border-radius:var(--radius-control);background:var(--color-danger-soft);color:var(--color-danger);font-size:14px}
.page-actions{display:flex;align-items:center;justify-content:space-between;gap:20px;margin-top:18px;padding-top:18px;border-top:1px solid var(--color-border)}.page-actions>p{display:flex;align-items:center;gap:7px;margin:0;color:var(--color-text-muted);font-size:14px}.page-actions>div{display:flex;gap:10px}
.primary-button,.secondary-button{display:inline-flex;min-height:40px;align-items:center;justify-content:center;gap:8px;padding:0 15px;border-radius:var(--radius-control);font-size:15px;font-weight:650;cursor:pointer}.primary-button{color:#fff;border:1px solid var(--color-accent);background:var(--color-accent)}.primary-button:hover{background:var(--color-text)}.secondary-button{color:var(--color-text);border:1px solid var(--color-border-strong);background:var(--color-surface)}.secondary-button:hover{background:var(--color-surface-subtle)}.primary-button:disabled,.secondary-button:disabled{opacity:.48;cursor:not-allowed}
.loading-surface,.error-surface{padding:28px;border:1px solid var(--color-border);border-radius:var(--radius-panel);background:var(--color-surface)}.error-surface{display:flex;align-items:center;gap:18px}.error-surface h1{margin:0;font-size:21px}.error-surface p{margin:5px 0 0;color:var(--color-text-secondary)}.error-surface .secondary-button{margin-left:auto}
.skeleton{border-radius:var(--radius-control);background:#e7ecee;animation:pulse 1.5s ease-in-out infinite}.skeleton--title{width:38%;height:32px}.skeleton--copy{width:64%;height:18px;margin-top:12px}.skeleton--row{height:72px;margin-top:14px}
.spin{animation:spin .9s linear infinite}@keyframes spin{to{transform:rotate(360deg)}}@keyframes pulse{50%{opacity:.52}}
@media(max-width:1260px){.context-band{grid-template-columns:1.2fr 1fr 90px}.context-band>div:nth-child(3){border-right:0}.context-band>div:nth-child(n+4){border-top:0}.resource-row{grid-template-columns:42px minmax(150px,.8fr) minmax(230px,1.35fr) 104px 100px;gap:10px;padding-inline:14px}}
</style>
