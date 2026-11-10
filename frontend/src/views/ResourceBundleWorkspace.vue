<script setup>
import { userMessage } from '../services/errorTranslator.js'
import { learningText } from '../utils/learningCopy.js'
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
} from '@lucide/vue'
import {
  executeGenerationJob,
  getResourceBundle,
  getGenerationJob,
  recoverGenerationJob,
  retryGenerationItem,
  reviseGenerationJob,
} from '../api'
import ResourceFloatingQa from '../components/ResourceFloatingQa.vue'
import { bundleResourceReference, bundleResourceReferences } from '../utils/resourceBundleContext.js'

const route = useRoute()
const router = useRouter()
const loading = ref(true)
const busyType = ref('')
const error = ref('')
const notice = ref('')
const job = ref(null)
const qaOpen = ref(false)
const revisionOpen = ref(false)
const revisionFeedback = ref('')
const revisionTypes = ref([])
let revisionRequest = null
let pollTimer = null
const isPersonalCopy = computed(() => route.query.mode === 'personal-copy')
const isCancelled = computed(() => job.value?.status === 'cancelled')
const automatic = computed(() => Boolean(job.value?.automation?.enabled))
const automaticPending = computed(() => automatic.value && ['queued', 'running', 'retry_wait', 'waiting_configuration'].includes(job.value?.automation?.state))

const resourceMeta = {
  handout: { label: '个性化讲义', icon: BookOpen },
  mind_map: { label: '思维导图', icon: Map },
  quiz: { label: '测验题资源', icon: ListChecks },
  training_task: { label: '实训任务书', icon: Braces },
  code_sandbox: { label: '代码沙盒任务', icon: PlayCircle },
  video: { label: '视频推荐', icon: Clock3 },
  deck: { label: 'PPT / 网页课件', icon: Presentation },
  interactive_model: { label: '可交互模型', icon: FlaskConical },
  feynman: { label: '费曼复述任务', icon: MessageSquareText },
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
const expectedCount = computed(() => items.value.length)
const reviewPending = computed(() => !isPersonalCopy.value && completedCount.value === expectedCount.value && job.value?.review_gate?.status !== 'passed')
const publishPending = computed(() => !isPersonalCopy.value && completedCount.value === expectedCount.value && job.value?.review_gate?.status === 'passed' && job.value?.publish_gate?.status !== 'completed')
const allDone = computed(() => expectedCount.value > 0 && completedCount.value === expectedCount.value && (isPersonalCopy.value || (job.value?.status === 'succeeded' && job.value?.review_gate?.status === 'passed' && job.value?.publish_gate?.status === 'completed')))
const progress = computed(() => {
  if (!expectedCount.value) return 0
  const value = Math.round((completedCount.value / expectedCount.value) * 100)
  return allDone.value ? value : Math.min(value, 99)
})
const context = computed(() => job.value?.context || {})
const qaSourceRefIds = computed(() => [...new Set((job.value?.items || []).flatMap(item => item.input?.source_ref_ids || item.source_ref_ids || []))])
const qaResourceRefs = computed(() => bundleResourceReferences(job.value?.items || []))
const hasInterruptedItems = computed(() => !isCancelled.value && items.value.some(item => item.state === 'running'))
const reviewFailed = computed(() => !isCancelled.value && !isPersonalCopy.value && reviewPending.value && job.value?.review_gate?.status === 'failed')
const canRetryFailed = computed(() => !isPersonalCopy.value && !isCancelled.value && failedCount.value > 0 && activeCount.value === 0)
const canRecover = computed(() => !automatic.value && (hasInterruptedItems.value || reviewFailed.value || canRetryFailed.value))
const canRevise = computed(() => !automaticPending.value && !isPersonalCopy.value && !isCancelled.value && !activeCount.value
  && job.value?.review_gate?.status !== 'running' && ['succeeded', 'failed', 'partial_success'].includes(job.value?.status))
const isPolling = computed(() => Boolean(job.value && !isCancelled.value && !allDone.value && (automatic.value
  ? automaticPending.value
  : !reviewFailed.value && (activeCount.value || reviewPending.value || publishPending.value))))
const statusCopy = computed(() => {
  if (isCancelled.value) return { title: '本次资源生成已取消', detail: '已生成的内容已保留。' }
  if (isPersonalCopy.value) {
    if (allDone.value) return { title: '个人资源包已就绪', detail: '' }
    return { title: '个人资源包已保留', detail: '部分资源暂不可用，其余可以打开。' }
  }
  if (allDone.value) return { title: '学习资源已就绪', detail: `${expectedCount.value} 项资源已分别归档，可以按学习安排继续。` }
  if (automatic.value) {
    const state = job.value.automation.state
    if (state === 'waiting_configuration') return { title: '等待模型服务恢复', detail: job.value.automation.message }
    if (state === 'needs_attention') return { title: '当前生成暂时中断', detail: job.value.automation.message }
    if (state === 'retry_wait') return { title: '稍后自动继续', detail: '服务暂时繁忙，已保存当前进度。' }
    if (job.value.automation.phase === 'repairing') return { title: '正在调整学习内容', detail: '可以离开此页，完成后回来学习。' }
    if (reviewPending.value || publishPending.value) return { title: '正在核对学习内容', detail: '' }
    return { title: '正在准备学习资源', detail: '可以离开此页，稍后回来查看进度。' }
  }
  if (failedCount.value) return { title: `${failedCount.value} 项内容需要调整`, detail: completedCount.value ? `已生成的 ${completedCount.value} 项内容会保留，重试失败项后再一起核对。` : '本次还没有准备好的资源，请查看原因并重试。' }
  if (reviewFailed.value) return { title: '最后核对暂时未完成', detail: '内容已保留，可以重新核对。' }
  if (reviewPending.value || publishPending.value) return { title: '正在完成最后核对', detail: '' }
  if (isPolling.value) return { title: '正在准备你的学习资源', detail: '可以离开此页，稍后回来会从当前进度继续。' }
  return { title: '资源包正在等待处理', detail: '刷新状态，或在任务中断后恢复未完成项。' }
})

function message(exception, fallback) {
  const detail = exception?.response?.data?.detail
  return detail?.message || (typeof detail === 'string' ? detail : '') || exception?.message || fallback
}

function stateLabel(state, item) {
  if (item?.resource?.status === 'available') return '可学习'
  return {
    requested: '等待开始',
    queued: '排队中',
    running: '生成中',
    succeeded: allDone.value || isPersonalCopy.value ? '可学习' : '初稿已保存',
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

function learnerFailure(item) {
  const raw = String(item?.failure?.message || '').trim()
  if (!raw) return '这一项暂时没有准备好，其他已完成资源不受影响。'
  if (/审核结论|审核意见|resourceType|versionId|resourceId|具体审核意见/.test(raw)) {
    return '这一项的内容需要重新整理，其他已完成资源不受影响。'
  }
  return learningText(raw, '这一项暂时没有准备好，其他已完成资源不受影响。')
}

async function loadJob({ quiet = false } = {}) {
  if (!quiet) loading.value = true
  error.value = ''
  try {
    const bundleId = String(route.params.bundleId || '')
    job.value = isPersonalCopy.value
      ? adaptPersonalBundle(await getResourceBundle(bundleId))
      : await getGenerationJob(bundleId)
    // A saved bundle owns its course; a missing or stale link query must not
    // leave the shell and subsequent learning actions in another course.
    if (job.value?.course_id && route.query.course_id !== job.value.course_id) {
      await router.replace({ query: { ...route.query, course_id: job.value.course_id } })
    }
    schedulePoll()
  } catch (exception) {
    error.value = message(exception, '资源包状态加载失败，请稍后重试。')
    // A temporary failed status read must not leave an active background job
    // frozen on screen until the learner reloads the whole page.
    if (quiet && isPolling.value) schedulePoll()
    else stopPolling()
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
      label: resourceMeta[resourceTypeAliases[item.resource_type] || item.resource_type]?.label || item.title || '学习资源',
      copy_notice: item.marketplace_copy_notice || '',
      completion_rule: '打开资源并按页面要求完成学习',
      state: item.availability?.status === 'available' && item.route ? 'succeeded' : 'unavailable',
      resource: item.route ? { route: item.route, resource_id: item.resource_id, version: { id: item.resource_version_id } } : null,
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
    job.value = retried
    schedulePoll()
    job.value = await runLocalDemo(retried.job_id)
    notice.value = allDone.value ? '内容已核对，可以开始学习。' : '本次重试已结束，请查看结果。'
    schedulePoll()
  } catch (exception) {
    error.value = message(exception, `${item.label}重试失败，请稍后再试。`)
  } finally {
    busyType.value = ''
  }
}

async function recoverInterrupted() {
  if (busyType.value || !canRecover.value) return
  busyType.value = 'recover'
  error.value = ''
  notice.value = ''
  try {
    const recovered = await recoverGenerationJob(job.value.job_id)
    job.value = recovered
    schedulePoll()
    job.value = await runLocalDemo(recovered.job_id)
    notice.value = allDone.value ? '内容已核对，可以开始学习。' : '本次处理已结束，请查看上方结果；已生成内容仍然保留。'
    schedulePoll()
  } catch (exception) {
    error.value = message(exception, '恢复失败，请稍后重试。')
  } finally {
    busyType.value = ''
  }
}

function openRevision() {
  revisionTypes.value = items.value.filter(item => item.state === 'failed').map(item => item.type)
  revisionOpen.value = true
}

async function reviseTeaching() {
  if (busyType.value || !canRevise.value || !revisionFeedback.value.trim() || !revisionTypes.value.length) return
  const feedback = revisionFeedback.value.trim()
  const selected = [...revisionTypes.value]
  const signature = JSON.stringify([job.value.job_id, feedback, selected])
  if (revisionRequest?.signature !== signature) revisionRequest = { signature, key: `resource-revision-${crypto.randomUUID()}` }
  busyType.value = 'revise'
  error.value = ''
  notice.value = ''
  try {
    job.value = await reviseGenerationJob(job.value.job_id, {
      feedback, resource_types: selected, idempotency_key: revisionRequest.key,
    })
    revisionOpen.value = false
    schedulePoll()
    job.value = await runLocalDemo(job.value.job_id)
    notice.value = allDone.value ? '内容已调整，可以继续学习。' : '请查看本次调整结果。'
    revisionRequest = null
    schedulePoll()
  } catch (exception) {
    error.value = message(exception, '这次调整未完成，请重试。')
  } finally {
    busyType.value = ''
  }
}

function openResource(item) {
  if (!item.resource?.route) return
  const target = router.resolve(item.resource.route)
  const reference = bundleResourceReference(item)
  router.push({
    path: target.path,
    query: {
      ...target.query,
      course_id: job.value?.course_id || route.query.course_id || undefined,
      version_id: target.query.version_id || reference?.resourceVersionId || undefined,
      resource_version_id: target.query.resource_version_id || reference?.resourceVersionId || undefined,
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
      course_id: job.value?.course_id || route.query.course_id,
      node_id: job.value?.manifest?.task_id || route.query.return_task || undefined,
    },
  })
}

function openResourceCenter() {
  router.push({ name: 'WorkspaceResources', query: { course_id: job.value?.course_id || route.query.course_id } })
}

onMounted(loadJob)
onUnmounted(stopPolling)
</script>

<template>
  <main class="bundle-page" data-testid="resource-bundle-workspace">
    <button type="button" class="back-link" @click="returnToTodayTask">
      <ArrowLeft :size="17" /> {{ isPersonalCopy ? '返回我的内容' : '返回学习安排' }}
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
        <p>{{ userMessage(error) }}</p>
      </div>
      <button type="button" class="secondary-button" @click="loadJob()">
        <RefreshCw :size="16" /> 重新加载
      </button>
    </section>

    <template v-else-if="job">
      <header class="page-header">
        <div>
          <p class="eyebrow">{{ context.course_title || '当前课程' }}</p>
          <h1>{{ context.knowledge_point_title || '当前知识点' }}</h1>
        </div>
      </header>
      <p v-if="error" class="feedback feedback--error" role="alert">
        <AlertTriangle :size="17" /> {{ userMessage(error) }}
      </p>
      <p v-else-if="notice" class="feedback" role="status">
        <Check :size="17" /> {{ notice }}
      </p>

      <section class="progress-section" aria-label="资源包生成进度">
        <div class="progress-section__heading">
          <div>
            <h2>{{ statusCopy.title }}</h2>
            <p v-if="statusCopy.detail && (!allDone || isPersonalCopy)" class="progress-note">{{ statusCopy.detail }}</p>
          </div>
          <strong>{{ completedCount }} / {{ expectedCount }}</strong>
        </div>
        <div class="progress-track" role="progressbar" :aria-valuenow="progress" aria-valuemin="0" aria-valuemax="100">
          <span :style="{ width: `${progress}%` }" />
        </div>
      </section>

      <section class="resource-surface" aria-label="九类学习资源">
        <article v-for="item in items" :key="item.type" class="resource-row" :data-state="item.state" :data-testid="`bundle-item-${item.type}`">
          <div class="resource-row__icon"><component :is="item.icon || Boxes" :size="21" /></div>
          <div class="resource-row__identity">
            <strong>{{ item.label }}</strong>
            <span v-if="item.copy_notice">{{ item.copy_notice }}</span>
          </div>
          <div class="resource-row__state" :class="`resource-row__state--${item.state}`">
            <component :is="stateIcon(item)" :size="16" :class="{ spin: item.state === 'running' }" />
            <span>{{ stateLabel(item.state, item) }}</span>
          </div>
          <div class="resource-row__action">
            <button v-if="item.state === 'succeeded' && item.resource?.route && (item.resource?.status === 'available' || allDone || isPersonalCopy)" type="button" class="row-button" @click="openResource(item)">
              打开 <ArrowRight :size="16" />
            </button>
            <button v-else-if="item.state === 'failed' && !isPersonalCopy && !automatic" type="button" class="row-button row-button--retry" :disabled="Boolean(busyType)" @click="retryItem(item)">
              <RefreshCw :size="16" :class="{ spin: busyType === item.type }" />
              {{ busyType === item.type ? '重试中' : '重试此项' }}
            </button>
            <span v-else-if="item.state === 'unavailable'">{{ item.failure?.message || '暂不可用' }}</span>
          </div>
          <p v-if="item.state === 'failed' && !automaticPending" class="resource-row__failure">
            {{ learnerFailure(item) }}
          </p>
        </article>
      </section>

      <form v-if="revisionOpen && canRevise" class="teaching-revision" @submit.prevent="reviseTeaching">
        <label for="revision-feedback">希望怎样调整？</label>
        <textarea id="revision-feedback" v-model="revisionFeedback" rows="3" placeholder="例如：先用数据表解释，再带我运行代码。" />
        <fieldset>
          <legend>调整哪些资源</legend>
          <label v-for="item in items" :key="item.type">
            <input v-model="revisionTypes" type="checkbox" :value="item.type" />{{ item.label }}
          </label>
        </fieldset>
        <div>
          <button type="button" class="secondary-button" :disabled="Boolean(busyType)" @click="revisionOpen = false">取消</button>
          <button type="submit" class="primary-button" :disabled="Boolean(busyType) || !revisionFeedback.trim() || !revisionTypes.length">调整内容</button>
        </div>
      </form>
      <section class="page-actions">
        <p v-if="isPersonalCopy">这是你的个人副本。</p>
        <div>
          <button type="button" class="secondary-button" :disabled="!qaResourceRefs.length || (!allDone && !isPersonalCopy)" @click="qaOpen = true"><MessageSquareText :size="16" /> 资源内提问</button>
          <button v-if="canRevise && !revisionOpen" type="button" class="secondary-button" :disabled="Boolean(busyType)" @click="openRevision">调整内容</button>
          <button v-if="canRecover" type="button" class="secondary-button" :disabled="Boolean(busyType)" @click="recoverInterrupted">
            <RefreshCw :size="16" :class="{ spin: busyType === 'recover' }" /> {{ reviewFailed ? '重新核对' : canRetryFailed ? '重试未完成资源' : '恢复中断项' }}
          </button>
          <button v-if="allDone" type="button" class="secondary-button" @click="openResourceCenter">
            <Boxes :size="16" /> 查看资源中心
          </button>
          <button type="button" class="primary-button" @click="returnToTodayTask">
            {{ isPersonalCopy ? '返回我的内容' : '返回学习安排' }} <ArrowRight :size="17" />
          </button>
        </div>
      </section>
      <ResourceFloatingQa
        :open="qaOpen"
        :course-id="job.course_id || route.query.course_id || ''"
        :knowledge-point-id="job.knowledge_point_id || ''"
        :resource-refs="qaResourceRefs"
        :resource-title="context.knowledge_point_title || '当前资源包'"
        :source-ref-ids="qaSourceRefIds"
        @close="qaOpen = false"
      />
    </template>
  </main>
</template>

<style scoped>
.teaching-revision{display:grid;gap:16px;margin:24px 0;padding:22px 0;border-top:1px solid var(--color-border)}
.teaching-revision>label,.teaching-revision legend{font-size:16px;font-weight:600}
.teaching-revision textarea{width:100%;box-sizing:border-box;padding:12px 14px;border:1px solid var(--color-border);border-radius:var(--radius-control);background:var(--color-surface);color:var(--color-text);font:inherit;line-height:1.7;resize:vertical}
.teaching-revision fieldset{display:flex;flex-wrap:wrap;gap:12px 22px;margin:0;padding:0;border:0}
.teaching-revision legend{margin-bottom:12px}.teaching-revision fieldset label{display:flex;align-items:center;gap:7px;font-size:15px}
.teaching-revision>div{display:flex;gap:12px;justify-content:flex-end}
.bundle-page{width:min(1120px,calc(100% - 48px));margin:0 auto;padding:28px 0 48px;color:var(--color-text)}
.back-link{display:inline-flex;align-items:center;gap:8px;margin:0 0 18px;padding:0;border:0;background:transparent;color:var(--color-text-secondary);font-size:14px;font-weight:600;cursor:pointer}
.back-link:hover{color:var(--color-text)}
.page-header{padding:0 0 22px;border-bottom:1px solid var(--color-border)}
.eyebrow{margin:0 0 6px;color:var(--color-text-secondary);font-size:14px;font-weight:650}
.page-header h1{margin:0;font-family:var(--font-heading);font-size:30px;font-weight:700;line-height:1.4;text-wrap:balance}
.feedback{display:flex;align-items:center;gap:8px;margin:16px 0 0;padding:11px 13px;border:1px solid var(--color-border);border-radius:var(--radius-control);background:var(--color-accent-soft);font-size:14px}
.feedback--error{color:var(--color-danger);border-color:#e8caca;background:var(--color-danger-soft)}
.progress-section{padding:26px 0 18px}.progress-section__heading{display:flex;align-items:flex-end;justify-content:space-between;gap:20px}.progress-section h2{margin:0;font-size:20px}.progress-section__heading>strong{font-size:22px;font-variant-numeric:tabular-nums}
.progress-track{height:8px;margin-top:14px;border-radius:4px;background:var(--color-surface-muted);overflow:hidden}.progress-track span{display:block;height:100%;background:var(--color-accent)}
.progress-note{margin:10px 0 0;color:var(--color-text-muted);font-size:14px}
.resource-surface{border:1px solid var(--color-border);border-radius:var(--radius-panel);background:var(--color-surface);overflow:hidden}
.resource-row{position:relative;display:grid;grid-template-columns:42px minmax(0,1fr) 112px 108px;gap:14px;align-items:center;min-height:88px;padding:14px 16px;border-bottom:1px solid var(--color-border)}
.resource-row:last-child{border-bottom:0}.resource-row__icon{display:grid;width:40px;height:40px;place-items:center;border:1px solid var(--color-border);border-radius:var(--radius-control);background:var(--color-surface-subtle);color:var(--color-text-secondary)}
.resource-row__identity strong,.resource-row__identity span{display:block}.resource-row__identity strong{font-size:15px}.resource-row__identity span{margin-top:3px;color:var(--color-text-secondary);font-size:14px;line-height:1.45}
.resource-row__state{display:flex;align-items:center;gap:7px;color:var(--color-text-secondary);font-size:14px;font-weight:600}.resource-row__state--failed{color:var(--color-danger)}.resource-row__state--succeeded{color:var(--color-accent)}
.resource-row__action{text-align:right}.resource-row__action>span{color:var(--color-text-muted);font-size:14px}
.row-button{display:inline-flex;min-height:36px;align-items:center;justify-content:center;gap:6px;padding:0 11px;border:1px solid var(--color-border-strong);border-radius:var(--radius-control);background:var(--color-surface);color:var(--color-text);font-size:14px;font-weight:650;cursor:pointer}.row-button:hover{background:var(--color-surface-subtle)}.row-button--retry{color:var(--color-danger)}.row-button:disabled{opacity:.48;cursor:not-allowed}
.resource-row__failure{grid-column:2/5;margin:-4px 0 2px;padding:8px 10px;border:1px solid #e8caca;border-radius:var(--radius-control);background:var(--color-danger-soft);color:var(--color-danger);font-size:14px}
.page-actions{display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:16px;margin-top:18px;padding-top:18px;border-top:1px solid var(--color-border)}.page-actions>p{display:flex;align-items:center;gap:7px;margin:0;color:var(--color-text-muted);font-size:14px}.page-actions>div{display:flex;flex-wrap:wrap;gap:10px}.page-actions button{white-space:nowrap;flex-shrink:0}
.primary-button,.secondary-button{display:inline-flex;min-height:40px;align-items:center;justify-content:center;gap:8px;padding:0 15px;border-radius:var(--radius-control);font-size:15px;font-weight:650;cursor:pointer}.primary-button{color:#fff;border:1px solid var(--color-accent);background:var(--color-accent)}.primary-button:hover{background:var(--color-text)}.secondary-button{color:var(--color-text);border:1px solid var(--color-border-strong);background:var(--color-surface)}.secondary-button:hover{background:var(--color-surface-subtle)}.primary-button:disabled,.secondary-button:disabled{opacity:.48;cursor:not-allowed}
.loading-surface,.error-surface{padding:28px;border:1px solid var(--color-border);border-radius:var(--radius-panel);background:var(--color-surface)}.error-surface{display:flex;align-items:center;gap:18px}.error-surface h1{margin:0;font-size:21px}.error-surface p{margin:5px 0 0;color:var(--color-text-secondary)}.error-surface .secondary-button{margin-left:auto}
.skeleton{border-radius:var(--radius-control);background:var(--color-surface-muted);animation:pulse 1.5s ease-in-out infinite}.skeleton--title{width:38%;height:32px}.skeleton--copy{width:64%;height:18px;margin-top:12px}.skeleton--row{height:72px;margin-top:14px}
.spin{animation:spin .9s linear infinite}@keyframes spin{to{transform:rotate(360deg)}}@keyframes pulse{50%{opacity:.52}}
@media(max-width:1260px){.resource-row{grid-template-columns:42px minmax(0,1fr) 104px 100px;gap:10px;padding-inline:14px}}
@media(max-width:1200px){.resource-row{grid-template-columns:40px minmax(0,1fr) auto;gap:10px 14px}.resource-row__state{grid-column:3;grid-row:1}.resource-row__action{grid-column:3;grid-row:2}.resource-row__failure{grid-column:2/4}.bundle-page{width:calc(100% - 40px)}}
</style>
