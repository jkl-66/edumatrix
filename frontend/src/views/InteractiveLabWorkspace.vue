<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  Activity,
  AlertTriangle,
  Beaker,
  BookOpen,
  CheckCircle2,
  CircleAlert,
  Database,
  ExternalLink,
  Lightbulb,
  Link2,
  LoaderCircle,
  Play,
  RefreshCw,
  RotateCcw,
  Save,
  Send,
  ShieldCheck,
  SlidersHorizontal,
  X,
} from '@lucide/vue'
import {
  applyInteractiveAction,
  createInteractiveInstance,
  listInteractiveInstances,
  listInteractiveTemplates,
  listMediaContextResources,
} from '../api'
import {
  compareM5ResourceVersions,
  getM5Resource,
  restoreM5ResourceVersion,
} from '../api/m5'
import ResourceHistoryDrawer from '../components/ResourceHistoryDrawer.vue'
import ResourceToolbar from '../components/ResourceToolbar.vue'
import ResourceProfileAdaptation from '../components/ResourceProfileAdaptation.vue'

const route = useRoute()
const router = useRouter()

const resourceId = computed(() => String(route.params.resourceId || 'legacy'))
const legacyMode = computed(() => resourceId.value === 'legacy')

const loading = ref(true)
const busy = ref(false)
const error = ref('')
const detail = ref(null)
const instances = ref([])
const selectedVersionId = ref('')
const parameters = ref({})
const observation = ref('')
const activeSeriesKey = ref('')
const notice = ref('')

const historyOpen = ref(false)
const historyError = ref('')
const restoringId = ref('')
const comparingId = ref('')
const compareResult = ref(null)

const templates = ref([])
const media = ref([])
const selectedTemplateId = ref('')
const selectedInstanceId = ref('')
const linkedMediaId = ref('')
const legacyTitle = ref('')

const workspace = computed(() => detail.value?.interactive_model || {})
const versions = computed(() => workspace.value.versions || [])
const currentVersionId = computed(() => workspace.value.current_version_id || '')
const selectedVersion = computed(() => (
  versions.value.find(item => item.id === selectedVersionId.value)
  || versions.value.find(item => item.id === currentVersionId.value)
  || null
))
const projection = computed(() => selectedVersion.value?.projection || workspace.value.current || null)
const structured = computed(() => projection.value?.structured || null)
const catalog = computed(() => detail.value?.catalog || {})
const sourceRefs = computed(() => projection.value?.source_refs || [])
const isCurrentVersion = computed(() => selectedVersion.value?.id === currentVersionId.value)
const historyItems = computed(() => versions.value.map(item => ({
  ...item,
  revision_origin: item.revision_origin || 'generated',
  source_status: item.projection?.source_readiness?.publishable ? 'available' : 'unavailable',
})))
const resourceInstance = computed(() => instances.value.find(item => (
  item.source_resource_id === resourceId.value
  && item.source_resource_version_id === currentVersionId.value
)) || null)
const experimentReady = computed(() => resourceInstance.value?.status === 'evaluated')
const completed = computed(() => resourceInstance.value?.status === 'passed')
const minimumObservation = computed(() => structured.value?.observationPrompt?.minimumCharacters || 20)
const observationCount = computed(() => observation.value.trim().length)
const canSubmitObservation = computed(() => (
  experimentReady.value && observationCount.value >= minimumObservation.value && !busy.value
))
const computedSeries = computed(() => resourceInstance.value?.computed_series || [])
const activeSeries = computed(() => (
  computedSeries.value.find(item => item.key === activeSeriesKey.value)
  || computedSeries.value[0]
  || null
))
const chartGeometry = computed(() => {
  const points = activeSeries.value?.points || []
  if (!points.length) return { points: '', minX: '', maxX: '', minY: '', maxY: '' }
  const width = 720
  const height = 250
  const padX = 42
  const padY = 26
  const xs = points.map(item => Number(item.x))
  const ys = points.map(item => Number(item.y))
  const minX = Math.min(...xs)
  const maxX = Math.max(...xs)
  const minY = Math.min(...ys)
  const maxY = Math.max(...ys)
  const xRange = maxX - minX || 1
  const yRange = maxY - minY || 1
  const mapped = points.map(item => {
    const x = padX + ((Number(item.x) - minX) / xRange) * (width - padX * 2)
    const y = height - padY - ((Number(item.y) - minY) / yRange) * (height - padY * 2)
    return `${x.toFixed(1)},${y.toFixed(1)}`
  })
  return {
    points: mapped.join(' '),
    minX: formatNumber(minX),
    maxX: formatNumber(maxX),
    minY: formatNumber(minY),
    maxY: formatNumber(maxY),
  }
})

const selectedTemplate = computed(() => templates.value.find(item => item.template_id === selectedTemplateId.value) || null)
const selectedLegacyInstance = computed(() => instances.value.find(item => item.instance_id === selectedInstanceId.value) || null)

function message(caught, fallback = '请求失败，请稍后重试。') {
  const value = caught?.response?.data?.detail
  return value?.message || (typeof value === 'string' ? value : '') || caught?.message || fallback
}

function key(prefix) {
  return `${prefix}-${globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(36).slice(2, 9)}`}`
}

function formatNumber(value) {
  if (!Number.isFinite(Number(value))) return '--'
  const numeric = Number(value)
  if (Math.abs(numeric) >= 10) return numeric.toFixed(0)
  return numeric.toFixed(3).replace(/0+$/, '').replace(/\.$/, '')
}

function defaultParameters(content) {
  return Object.fromEntries((content?.parameters || []).map(item => [item.key, Number(item.default)]))
}

function instanceParameters(instance) {
  return instance ? { ...instance.parameters } : defaultParameters(structured.value)
}

function sameParameters(left, right) {
  const keys = Object.keys(left || {})
  return keys.length === Object.keys(right || {}).length
    && keys.every(item => Number(left[item]) === Number(right[item]))
}

function syncFormalDraft() {
  parameters.value = instanceParameters(resourceInstance.value)
  observation.value = resourceInstance.value?.submitted_observation || ''
  activeSeriesKey.value = resourceInstance.value?.computed_series?.[0]?.key
    || structured.value?.chart?.series?.[0]?.key
    || ''
}

async function loadFormalResource() {
  loading.value = true
  error.value = ''
  notice.value = ''
  try {
    const [resource, instanceData] = await Promise.all([
      getM5Resource(resourceId.value),
      listInteractiveInstances(),
    ])
    detail.value = resource
    if (!resource?.interactive_model) throw new Error('当前资源不是可交互模型。')
    instances.value = instanceData.items || []
    selectedVersionId.value = currentVersionId.value || versions.value.at(-1)?.id || ''
    syncFormalDraft()
  } catch (caught) {
    error.value = message(caught, '可交互模型暂时无法打开。')
  } finally {
    loading.value = false
  }
}

async function applyFormalAction(actionName, payload = {}) {
  const current = resourceInstance.value
  if (!current) throw new Error('实验实例尚未创建。')
  const result = await applyInteractiveAction(current.instance_id, {
    action: actionName,
    parameters: payload.parameters || null,
    observation: payload.observation || null,
    expected_version: current.version_number,
    idempotency_key: key(`interactive-model-${actionName}`),
  })
  instances.value = instances.value.map(item => item.instance_id === result.instance_id ? result : item)
  return result
}

async function runExperiment() {
  if (!structured.value || !isCurrentVersion.value || busy.value) return
  busy.value = true
  error.value = ''
  notice.value = ''
  try {
    let current = resourceInstance.value
    if (!current) {
      current = await createInteractiveInstance({
        template_id: structured.value.templateId,
        title: structured.value.title,
        parameters: parameters.value,
        linked_media_resource_id: null,
        source_resource_id: resourceId.value,
        idempotency_key: key(`interactive-model-create-${resourceId.value}`),
      })
      instances.value = [current, ...instances.value.filter(item => item.instance_id !== current.instance_id)]
    } else {
      if (current.status === 'passed') current = await applyFormalAction('reset')
      if (current.status !== 'configured' || !sameParameters(current.parameters, parameters.value)) {
        current = await applyFormalAction('configure', { parameters: parameters.value })
      }
    }
    const result = await applyInteractiveAction(current.instance_id, {
      action: 'run',
      parameters: null,
      observation: null,
      expected_version: current.version_number,
      idempotency_key: key('interactive-model-run'),
    })
    instances.value = instances.value.map(item => item.instance_id === result.instance_id ? result : item)
    observation.value = ''
    activeSeriesKey.value = result.computed_series?.[0]?.key || ''
    notice.value = '实验结果已更新。调参和运行不会写入学习证据。'
  } catch (caught) {
    error.value = message(caught, '实验运行失败，参数草稿已保留。')
  } finally {
    busy.value = false
  }
}

async function resetExperiment() {
  if (!resourceInstance.value || busy.value) {
    parameters.value = defaultParameters(structured.value)
    return
  }
  busy.value = true
  error.value = ''
  try {
    const result = await applyFormalAction('reset')
    parameters.value = { ...result.parameters }
    observation.value = ''
    activeSeriesKey.value = ''
    notice.value = '已恢复默认参数，本次操作未形成学习证据。'
  } catch (caught) {
    error.value = message(caught, '重置实验失败。')
  } finally {
    busy.value = false
  }
}

async function requestHint() {
  if (!resourceInstance.value || busy.value) return
  busy.value = true
  error.value = ''
  try {
    await applyFormalAction('request_hint')
    notice.value = '提示已加入运行反馈；只有提交观察结论才会形成学习证据。'
  } catch (caught) {
    error.value = message(caught, '提示请求失败。')
  } finally {
    busy.value = false
  }
}

async function submitObservation() {
  if (!canSubmitObservation.value) return
  busy.value = true
  error.value = ''
  notice.value = ''
  try {
    const result = await applyFormalAction('submit', { observation: observation.value })
    observation.value = result.submitted_observation || observation.value
    notice.value = result.learning_evidence?.created
      ? '观察结论已提交，并形成一条可追溯学习证据。'
      : '观察结论已恢复，未重复创建学习证据。'
  } catch (caught) {
    error.value = message(caught, '观察结论提交失败，文字已保留。')
  } finally {
    busy.value = false
  }
}

function openSource(source) {
  if (!source?.available || !source.source_document_id) return
  router.push({
    name: 'KnowledgeDocument',
    params: { documentId: source.source_document_id },
    query: {
      canonical_source_id: source.source_document_id,
      course_id: catalog.value.course?.id || route.query.course_id,
      focus_source_ref_id: source.source_ref_id,
      return_to: route.fullPath,
    },
  })
}

function openHistory() {
  historyError.value = ''
  compareResult.value = null
  historyOpen.value = true
}

function closeHistory() {
  historyOpen.value = false
  historyError.value = ''
  compareResult.value = null
}

function selectHistoryVersion(versionId) {
  selectedVersionId.value = versionId
  parameters.value = defaultParameters(projection.value?.structured)
  closeHistory()
}

async function compareHistory(versionId) {
  if (comparingId.value) return
  const left = versions.value.find(item => item.id === versionId)
  const right = versions.value.find(item => item.id === currentVersionId.value)
  if (!left || !right) return
  comparingId.value = versionId
  historyError.value = ''
  try {
    compareResult.value = await compareM5ResourceVersions(resourceId.value, left.number, right.number)
  } catch (caught) {
    historyError.value = message(caught)
  } finally {
    comparingId.value = ''
  }
}

async function restoreHistory(versionId) {
  if (restoringId.value || versionId === currentVersionId.value) return
  restoringId.value = versionId
  historyError.value = ''
  try {
    detail.value = await restoreM5ResourceVersion(resourceId.value, {
      expected_lock_version: detail.value.lock_version,
      version_id: versionId,
    })
    selectedVersionId.value = detail.value.interactive_model?.current_version_id || ''
    instances.value = (await listInteractiveInstances()).items || []
    syncFormalDraft()
    closeHistory()
  } catch (caught) {
    historyError.value = message(caught)
  } finally {
    restoringId.value = ''
  }
}

function legacyDefaults(template) {
  return Object.fromEntries(template.parameters.map(item => [item.key, Number(item.default)]))
}

function chooseTemplate(templateId) {
  selectedTemplateId.value = templateId
  selectedInstanceId.value = ''
  const template = templates.value.find(item => item.template_id === templateId)
  if (template) {
    parameters.value = legacyDefaults(template)
    legacyTitle.value = template.title
  }
}

function chooseInstance(instanceId) {
  selectedInstanceId.value = instanceId
  const instance = instances.value.find(item => item.instance_id === instanceId)
  if (!instance) return
  selectedTemplateId.value = instance.template_id
  parameters.value = { ...instance.parameters }
  linkedMediaId.value = instance.linked_media_resource_id || ''
  legacyTitle.value = instance.title
}

async function loadLegacy() {
  loading.value = true
  error.value = ''
  try {
    const [templateData, instanceData, mediaData] = await Promise.all([
      listInteractiveTemplates(), listInteractiveInstances(), listMediaContextResources(),
    ])
    templates.value = templateData.items || []
    instances.value = (instanceData.items || []).filter(item => !item.source_resource_id)
    media.value = mediaData.items || []
    if (instances.value.length) chooseInstance(instances.value[0].instance_id)
    else if (templates.value.length) chooseTemplate(templates.value[0].template_id)
  } catch (caught) {
    error.value = message(caught, '兼容实验台加载失败。')
  } finally {
    loading.value = false
  }
}

async function createLegacyLab() {
  busy.value = true
  error.value = ''
  try {
    const result = await createInteractiveInstance({
      template_id: selectedTemplateId.value,
      title: legacyTitle.value,
      parameters: parameters.value,
      linked_media_resource_id: linkedMediaId.value || null,
      source_resource_id: null,
      idempotency_key: key('legacy-lab-create'),
    })
    instances.value = [result, ...instances.value.filter(item => item.instance_id !== result.instance_id)]
    chooseInstance(result.instance_id)
  } catch (caught) {
    error.value = message(caught, '实验实例创建失败。')
  } finally {
    busy.value = false
  }
}

async function legacyAction(actionName) {
  const current = selectedLegacyInstance.value
  if (!current || busy.value) return
  busy.value = true
  error.value = ''
  try {
    const result = await applyInteractiveAction(current.instance_id, {
      action: actionName,
      parameters: actionName === 'configure' ? parameters.value : null,
      observation: null,
      expected_version: current.version_number,
      idempotency_key: key(`legacy-lab-${actionName}`),
    })
    instances.value = instances.value.map(item => item.instance_id === result.instance_id ? result : item)
    chooseInstance(result.instance_id)
  } catch (caught) {
    error.value = message(caught, '实验操作失败。')
  } finally {
    busy.value = false
  }
}

async function load() {
  if (legacyMode.value) await loadLegacy()
  else await loadFormalResource()
}

watch(resourceId, load)
watch(selectedVersionId, () => {
  if (!legacyMode.value && structured.value && !isCurrentVersion.value) {
    parameters.value = defaultParameters(structured.value)
    observation.value = ''
  }
})
onMounted(load)
</script>

<template>
  <main class="interactive-page" data-testid="interactive-lab-workspace">
    <template v-if="legacyMode">
      <header class="legacy-header">
        <div><span>兼容实验入口</span><h1>确定性参数实验</h1><p>保留历史模板与视频练习联动；正式课程资源请从资源中心进入。</p></div>
        <div class="trust-badge"><ShieldCheck :size="19" /><span><strong>本地确定性模拟</strong><small>无外部代码与网络</small></span></div>
      </header>

      <div v-if="error" class="status-line status-line--error" role="alert"><CircleAlert :size="18" />{{ error }}</div>
      <div v-if="loading" class="page-state"><LoaderCircle :size="24" class="spin" /><strong>正在恢复实验状态</strong></div>

      <template v-else>
        <section class="legacy-template-list" data-testid="lab-template-list">
          <button v-for="template in templates" :key="template.template_id" type="button" :class="{ active: selectedTemplateId === template.template_id }" @click="chooseTemplate(template.template_id)">
            <Beaker :size="20" /><span><strong>{{ template.title }}</strong><small>{{ template.summary }}</small></span>
          </button>
        </section>
        <div class="legacy-layout">
          <aside class="legacy-history">
            <header><strong>实验实例</strong><span>{{ instances.length }} 项</span></header>
            <button v-for="item in instances" :key="item.instance_id" type="button" data-testid="lab-instance" :class="{ active: selectedInstanceId === item.instance_id }" @click="chooseInstance(item.instance_id)">
              <span><strong>{{ item.title }}</strong><small>v{{ item.version_number }} · {{ item.status }}</small></span>
            </button>
            <p v-if="!instances.length">尚无实例，请从右侧创建。</p>
          </aside>
          <section v-if="selectedTemplate" class="legacy-workspace">
            <header><div><span>实验目标</span><h2>{{ selectedTemplate.title }}</h2><p>{{ selectedTemplate.skill_target }}</p></div></header>
            <div class="legacy-setup">
              <label><span>实验名称</span><input v-model="legacyTitle" aria-label="实验名称" maxlength="256" /></label>
              <label><span><Link2 :size="16" />联动媒体资源</span><select v-model="linkedMediaId" aria-label="联动媒体资源"><option value="">不绑定</option><option v-for="item in media" :key="item.id" :value="item.id">{{ item.title }}</option></select></label>
            </div>
            <div class="legacy-parameters" data-testid="lab-parameters">
              <label v-for="parameter in selectedTemplate.parameters" :key="parameter.key">
                <span>{{ parameter.label }} <output>{{ parameters[parameter.key] }}</output></span>
                <input v-if="parameter.kind === 'float'" v-model.number="parameters[parameter.key]" :aria-label="parameter.label" type="range" :min="parameter.minimum" :max="parameter.maximum" :step="parameter.step" />
                <input v-else v-model.number="parameters[parameter.key]" :aria-label="parameter.label" type="number" :min="parameter.minimum" :max="parameter.maximum" :step="parameter.step" />
              </label>
            </div>
            <div class="legacy-actions">
              <button v-if="!selectedLegacyInstance" type="button" class="primary-button" :disabled="busy" @click="createLegacyLab"><Save :size="17" />创建实验</button>
              <template v-else>
                <button type="button" :disabled="busy || !['configured','evaluated','needs_retry'].includes(selectedLegacyInstance.status)" @click="legacyAction('configure')"><Save :size="17" />保存参数</button>
                <button type="button" class="primary-button" :disabled="busy || selectedLegacyInstance.status !== 'configured'" @click="legacyAction('run')"><Play :size="17" />运行实验</button>
                <button type="button" :disabled="busy || selectedLegacyInstance.status !== 'evaluated'" @click="legacyAction('submit')"><Send :size="17" />隐藏验收</button>
                <button type="button" title="重置实验" :disabled="busy" @click="legacyAction('reset')"><RotateCcw :size="17" />重置</button>
              </template>
            </div>
            <section v-if="selectedLegacyInstance?.metrics" class="legacy-results" data-testid="lab-results">
              <div v-for="(value, metricKey) in selectedLegacyInstance.metrics" :key="metricKey"><span>{{ selectedTemplate.metrics.find(item => item.key === metricKey)?.label || metricKey }}</span><strong>{{ formatNumber(value) }}</strong></div>
            </section>
            <section v-if="selectedLegacyInstance?.hidden_acceptance" class="legacy-acceptance" data-testid="lab-acceptance">
              <CheckCircle2 :size="20" /><span><strong>{{ selectedLegacyInstance.hidden_acceptance.passed ? '隐藏验收通过' : '需要继续调优' }}</strong><small>未暴露隐藏期望值 · {{ selectedLegacyInstance.hidden_acceptance.passed_count }}/{{ selectedLegacyInstance.hidden_acceptance.total_count }}</small></span>
            </section>
          </section>
        </div>
      </template>
    </template>

    <template v-else>
      <section v-if="loading" class="page-state" role="status"><LoaderCircle :size="26" class="spin" /><strong>正在打开可交互模型</strong><span>正在恢复资源版本、参数实验和课程来源。</span></section>
      <section v-else-if="error && !detail" class="page-state page-state--error" role="alert"><AlertTriangle :size="26" /><strong>可交互模型暂时无法打开</strong><span>{{ error }}</span><button type="button" class="primary-button" @click="loadFormalResource"><RefreshCw :size="17" />重新加载</button></section>

      <template v-else>
        <ResourceToolbar
          :title="structured?.title || catalog.title || '可交互模型'"
          :type-label="`${catalog.course?.title || '当前课程'} · ${catalog.knowledge_point?.title || '当前知识点'}`"
          :version-label="selectedVersion ? `v${selectedVersion.number}` : '版本未记录'"
          :status-label="completed ? '观察已提交' : experimentReady ? '等待观察结论' : '可运行实验'"
          :history-count="historyItems.length"
          :history-disabled="!historyItems.length"
          :loading="loading"
          @back="router.push({ name: 'WorkspaceResources', query: { course_id: catalog.course?.id || route.query.course_id } })"
          @history="openHistory"
          @reload="loadFormalResource"
        />

        <div v-if="error" class="status-line status-line--error" role="alert"><CircleAlert :size="18" /><span>{{ error }}</span><button type="button" title="关闭提示" aria-label="关闭错误提示" @click="error = ''"><X :size="18" aria-hidden="true" /></button></div>
        <div v-else-if="notice" class="status-line" role="status"><CheckCircle2 :size="18" /><span>{{ notice }}</span><button type="button" title="关闭提示" aria-label="关闭状态提示" @click="notice = ''"><X :size="18" aria-hidden="true" /></button></div>
        <div v-if="projection?.warnings?.length" class="status-line status-line--warning" role="status"><AlertTriangle :size="18" />{{ projection.warnings[0] }}</div>
        <div v-if="!isCurrentVersion" class="historical-banner" role="status">当前查看历史版本。参数和来源可以阅读，但实验只能基于当前版本运行。</div>

        <ResourceProfileAdaptation
          v-if="structured"
          :adaptation="structured?.adaptation"
          :plan="detail?.resource?.profile_adaptation_plan"
          :summary="structured?.adaptation?.profileSummary || ''"
          resource-type="interactive_model"
        />

        <section v-if="structured" class="model-layout">
          <aside class="parameter-pane" aria-label="实验参数与约束">
            <section>
              <header><SlidersHorizontal :size="19" /><div><strong>实验参数</strong><span>调整只保存在本地草稿</span></div></header>
              <label v-for="parameter in structured.parameters" :key="parameter.key" class="parameter-control">
                <span><strong>{{ parameter.label }}</strong><output>{{ parameters[parameter.key] }}{{ parameter.unit }}</output></span>
                <input v-if="parameter.kind === 'float'" v-model.number="parameters[parameter.key]" :aria-label="parameter.label" type="range" :min="parameter.minimum" :max="parameter.maximum" :step="parameter.step" :disabled="!isCurrentVersion || busy" />
                <input v-else v-model.number="parameters[parameter.key]" :aria-label="parameter.label" type="number" :min="parameter.minimum" :max="parameter.maximum" :step="parameter.step" :disabled="!isCurrentVersion || busy" />
                <small>{{ parameter.description }}</small>
              </label>
              <div class="parameter-actions">
                <button type="button" class="primary-button" :disabled="!isCurrentVersion || busy" @click="runExperiment"><LoaderCircle v-if="busy" :size="17" class="spin" /><Play v-else :size="17" />{{ resourceInstance ? '按当前参数运行' : '开始实验' }}</button>
                <button type="button" title="恢复默认参数" :disabled="!isCurrentVersion || busy" @click="resetExperiment"><RotateCcw :size="17" /><span>恢复默认</span></button>
              </div>
            </section>

            <section>
              <header><ShieldCheck :size="19" /><div><strong>参数约束</strong><span>运行前由服务端再次校验</span></div></header>
              <div v-for="constraint in structured.constraints" :key="constraint.id" class="constraint-row"><strong>{{ constraint.title }}</strong><p>{{ constraint.description }}</p></div>
            </section>

            <section>
              <header><Database :size="19" /><div><strong>冻结数据集</strong><span>{{ structured.dataset.sampleCount }} 条演示样本</span></div></header>
              <div class="dataset-summary"><strong>{{ structured.dataset.title }}</strong><p>{{ structured.dataset.summary }}</p></div>
            </section>
          </aside>

          <section class="result-pane" aria-label="实验结果">
            <header class="result-lead"><div><span>确定性参数实验</span><h2>{{ structured.summary }}</h2><p>{{ structured.adaptation.learningGoal }}</p></div><div class="runtime-label"><ShieldCheck :size="18" /><span>本地计算</span></div></header>

            <section class="chart-section" data-testid="interactive-model-chart">
              <header><div><strong>结果曲线</strong><span>{{ structured.chart.xAxisLabel }} · {{ activeSeries?.label || structured.chart.yAxisLabel }}</span></div><div class="series-switch" role="tablist" aria-label="结果指标"><button v-for="series in computedSeries" :key="series.key" type="button" :class="{ active: activeSeries?.key === series.key }" @click="activeSeriesKey = series.key">{{ series.label }}</button></div></header>
              <div v-if="activeSeries" class="chart-canvas">
                <svg viewBox="0 0 720 250" role="img" :aria-label="`${activeSeries.label}结果曲线`">
                  <line x1="42" y1="224" x2="678" y2="224" />
                  <line x1="42" y1="26" x2="42" y2="224" />
                  <polyline :points="chartGeometry.points" />
                  <circle v-for="point in chartGeometry.points.split(' ')" :key="point" :cx="point.split(',')[0]" :cy="point.split(',')[1]" r="4" />
                </svg>
                <div class="chart-scale"><span>{{ chartGeometry.minY }}{{ activeSeries.unit }}</span><span>{{ chartGeometry.maxY }}{{ activeSeries.unit }}</span><span>{{ chartGeometry.minX }}</span><span>{{ chartGeometry.maxX }}</span></div>
              </div>
              <div v-else class="result-empty"><Activity :size="25" /><strong>尚未运行实验</strong><span>调整左侧参数并点击“开始实验”，这里会显示稳定可复现的计算曲线。</span></div>
            </section>

            <section class="metric-section" data-testid="lab-results">
              <header><strong>当前参数结果</strong><span>同一组参数重复运行得到相同结果</span></header>
              <div v-if="resourceInstance?.metrics" class="metric-table" role="table" aria-label="实验指标">
                <div v-for="series in computedSeries" :key="series.key" role="row"><span role="cell">{{ series.label }}</span><strong role="cell">{{ formatNumber(resourceInstance.metrics[series.key]) }}{{ series.unit }}</strong></div>
              </div>
              <div v-else class="metric-empty">运行后显示当前指标。</div>
            </section>

            <section v-if="resourceInstance?.feedback?.length" class="feedback-section"><header><Activity :size="18" /><strong>运行反馈</strong><button type="button" :disabled="busy || !['evaluated','needs_retry'].includes(resourceInstance.status)" @click="requestHint"><Lightbulb :size="17" />查看提示</button></header><p v-for="line in resourceInstance.feedback" :key="line">{{ line }}</p></section>
          </section>

          <aside class="observation-pane" aria-label="观察结论与来源">
            <section class="observation-section">
              <header><Beaker :size="19" /><div><strong>观察结论</strong><span>提交后才形成学习证据</span></div></header>
              <p class="observation-prompt">{{ structured.observationPrompt.prompt }}</p>
              <textarea v-model="observation" :disabled="!experimentReady || completed || busy" aria-label="观察结论" :placeholder="experimentReady ? '比较参数、指标变化和你的判断...' : '先运行一次实验后再填写'" />
              <div class="observation-meta"><span>{{ observationCount }}/{{ minimumObservation }} 字</span><span>{{ structured.completionRule }}</span></div>
              <button type="button" class="primary-button submit-button" :disabled="!canSubmitObservation || completed" @click="submitObservation"><Send :size="17" />{{ completed ? '观察已提交' : '提交观察结论' }}</button>
              <div v-if="completed" class="completion-state" data-testid="interactive-model-completion"><CheckCircle2 :size="21" /><div><strong>本次学习已完成</strong><span>观察结论与参数、指标、来源版本已共同归档。</span></div></div>
            </section>

            <section>
              <header><BookOpen :size="19" /><div><strong>课程来源</strong><span>{{ sourceRefs.length }} 处引用</span></div></header>
              <button v-for="source in sourceRefs" :key="source.source_ref_id" type="button" class="source-row" :disabled="!source.available" @click="openSource(source)"><span><strong>{{ source.title || '课程来源' }}</strong><small>{{ source.location_label || '位置未记录' }}</small></span><ExternalLink v-if="source.available" :size="16" /></button>
              <p v-if="!sourceRefs.length" class="panel-empty">当前版本没有登记可追溯来源。</p>
            </section>

          </aside>
        </section>

        <section v-else class="page-state page-state--error" role="alert"><AlertTriangle :size="26" /><strong>当前版本不能运行</strong><span>{{ projection?.warnings?.[0] || '当前内容缺少结构化参数、来源或观察规则。' }}</span><button type="button" @click="router.push({ name: 'WorkspaceResources' })">返回资源中心</button></section>

        <ResourceHistoryDrawer
          :open="historyOpen"
          title="可交互模型版本历史"
          :items="historyItems"
          :current-version-id="currentVersionId"
          :selected-version-id="selectedVersionId"
          :restoring-id="restoringId"
          :comparing-id="comparingId"
          :error="historyError"
          :compare-result="compareResult"
          :compare-disabled="Boolean(comparingId)"
          :restore-disabled="busy"
          @close="closeHistory"
          @select="selectHistoryVersion"
          @compare="compareHistory"
          @restore="restoreHistory"
          @compare-close="compareResult = null"
        />
      </template>
    </template>
  </main>
</template>

<style scoped>
.interactive-page { min-width: 0; padding: 18px; background: #f6f8f8; color: #06141b; font-family: "Source Han Sans SC", "Noto Sans CJK SC", "Microsoft YaHei", sans-serif; letter-spacing: 0; }
.page-state { display: grid; min-height: 430px; place-content: center; justify-items: center; gap: 9px; border: 1px solid #dfe4e5; border-radius: 8px; background: #fff; color: #60727c; text-align: center; }
.page-state strong { color: #06141b; font-size: 18px; }
.page-state span { max-width: 48ch; font-size: 14px; line-height: 1.6; }
.page-state--error { color: #8b3d35; }
.page-state button, .primary-button { display: inline-flex; min-height: 38px; align-items: center; justify-content: center; gap: 7px; border: 1px solid #11212d; border-radius: 8px; padding: 0 12px; background: #11212d; color: #fff; font-size: 14px; font-weight: 650; cursor: pointer; }
.status-line { display: flex; min-height: 42px; align-items: center; gap: 8px; margin-top: 10px; border: 1px solid #ccd0cf; border-radius: 8px; padding: 0 11px; background: #fff; color: #344957; font-size: 14px; }
.status-line span { flex: 1; }
.status-line button { display: grid; width: 30px; height: 30px; flex: 0 0 30px; place-items: center; padding: 0; border: 0; background: transparent; color: currentColor; cursor: pointer; }
.status-line--error { border-color: #d8aaa5; background: #fff5f3; color: #8b3d35; }
.status-line--warning { border-color: #c9c5be; background: #faf9f7; color: #4d4a45; }
.historical-banner { margin-top: 10px; border: 1px solid #ccd0cf; border-radius: 8px; padding: 10px 12px; background: #fff; color: #4a5c6a; font-size: 14px; }
.model-layout { display: grid; min-height: 650px; grid-template-columns: 252px minmax(420px, 1fr) 304px; gap: 12px; margin-top: 12px; }
.parameter-pane, .result-pane, .observation-pane { min-width: 0; border: 1px solid #ccd0cf; border-radius: 8px; background: #fff; }
.parameter-pane, .observation-pane { overflow: auto; }
.parameter-pane > section, .observation-pane > section { border-bottom: 1px solid #e4e8e9; padding: 16px; }
.parameter-pane > section:last-child, .observation-pane > section:last-child { border-bottom: 0; }
.parameter-pane header, .observation-pane header { display: flex; align-items: flex-start; gap: 9px; }
.parameter-pane header strong, .observation-pane header strong { display: block; font-size: 15px; }
.parameter-pane header span, .observation-pane header span { display: block; margin-top: 2px; color: #60727c; font-size: 14px; line-height: 1.45; }
.parameter-control { display: grid; gap: 7px; margin-top: 16px; }
.parameter-control > span { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.parameter-control strong, .parameter-control output { font-size: 14px; }
.parameter-control output { color: #11212d; font-weight: 700; font-variant-numeric: tabular-nums; }
.parameter-control input[type="range"] { width: 100%; accent-color: #11212d; }
.parameter-control input[type="number"] { width: 100%; min-height: 38px; box-sizing: border-box; border: 1px solid #ccd0cf; border-radius: 8px; padding: 0 9px; color: #06141b; font-size: 14px; }
.parameter-control small { color: #60727c; font-size: 14px; line-height: 1.5; }
.parameter-actions { display: grid; grid-template-columns: minmax(0, 1fr) 40px; gap: 7px; margin-top: 18px; }
.parameter-actions > button:last-child { display: grid; width: 40px; min-height: 38px; place-items: center; border: 1px solid #ccd0cf; border-radius: 8px; background: #fff; color: #11212d; cursor: pointer; }
.parameter-actions > button:last-child span { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0, 0, 0, 0); }
.constraint-row, .dataset-summary { margin-top: 13px; }
.constraint-row strong, .dataset-summary strong { font-size: 14px; }
.constraint-row p, .dataset-summary p { margin: 5px 0 0; color: #4a5c6a; font-size: 14px; line-height: 1.55; }
.result-pane { padding: 18px; }
.result-lead { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; border-bottom: 1px solid #e4e8e9; padding-bottom: 16px; }
.result-lead > div:first-child { min-width: 0; }
.result-lead span { color: #60727c; font-size: 14px; }
.result-lead h2 { margin: 5px 0 6px; font-family: "Source Han Serif SC", "Noto Serif CJK SC", SimSun, serif; font-size: 21px; font-weight: 650; line-height: 1.45; }
.result-lead p { margin: 0; color: #4a5c6a; font-size: 14px; line-height: 1.6; }
.runtime-label { display: inline-flex; flex: 0 0 auto; align-items: center; gap: 6px; border: 1px solid #ccd0cf; border-radius: 8px; padding: 8px 10px; background: #f8fafa; }
.runtime-label span { color: #253745; }
.chart-section, .metric-section, .feedback-section { margin-top: 16px; border: 1px solid #dfe4e5; border-radius: 8px; }
.chart-section > header, .metric-section > header { display: flex; min-height: 54px; align-items: center; justify-content: space-between; gap: 12px; border-bottom: 1px solid #e4e8e9; padding: 0 13px; }
.chart-section header strong, .metric-section header strong { display: block; font-size: 15px; }
.chart-section header span, .metric-section header span { color: #60727c; font-size: 14px; }
.series-switch { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 5px; }
.series-switch button { min-height: 32px; border: 1px solid #ccd0cf; border-radius: 7px; padding: 0 8px; background: #fff; color: #4a5c6a; font-size: 14px; cursor: pointer; }
.series-switch button.active { border-color: #11212d; background: #11212d; color: #fff; }
.chart-canvas { position: relative; min-height: 286px; padding: 12px 14px 22px; }
.chart-canvas svg { display: block; width: 100%; height: 250px; }
.chart-canvas line { stroke: #c9d0d2; stroke-width: 1; }
.chart-canvas polyline { fill: none; stroke: #11212d; stroke-width: 3; stroke-linejoin: round; stroke-linecap: round; }
.chart-canvas circle { fill: #fff; stroke: #11212d; stroke-width: 3; }
.chart-scale { position: absolute; inset: 14px 17px 8px; pointer-events: none; color: #60727c; font-size: 14px; }
.chart-scale span { position: absolute; }
.chart-scale span:nth-child(1) { left: 0; bottom: 24px; }
.chart-scale span:nth-child(2) { left: 0; top: 0; }
.chart-scale span:nth-child(3) { left: 38px; bottom: 0; }
.chart-scale span:nth-child(4) { right: 14px; bottom: 0; }
.result-empty { display: grid; min-height: 286px; place-content: center; justify-items: center; gap: 8px; padding: 20px; color: #60727c; text-align: center; }
.result-empty strong { color: #06141b; font-size: 16px; }
.result-empty span { max-width: 46ch; font-size: 14px; line-height: 1.55; }
.metric-table { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); }
.metric-table > div { display: flex; min-height: 58px; align-items: center; justify-content: space-between; gap: 10px; border-right: 1px solid #e4e8e9; border-bottom: 1px solid #e4e8e9; padding: 0 13px; }
.metric-table > div:nth-child(2n) { border-right: 0; }
.metric-table span { color: #4a5c6a; font-size: 14px; }
.metric-table strong { font-size: 18px; font-variant-numeric: tabular-nums; }
.metric-empty { padding: 18px; color: #60727c; font-size: 14px; }
.feedback-section { padding: 13px; }
.feedback-section header { display: flex; align-items: center; gap: 8px; }
.feedback-section header strong { flex: 1; font-size: 15px; }
.feedback-section header button { display: inline-flex; min-height: 34px; align-items: center; gap: 6px; border: 1px solid #ccd0cf; border-radius: 8px; padding: 0 9px; background: #fff; color: #11212d; font-size: 14px; cursor: pointer; }
.feedback-section p { margin: 8px 0 0; color: #4a5c6a; font-size: 14px; line-height: 1.55; }
.observation-prompt { margin: 14px 0 10px; color: #253745; font-size: 14px; line-height: 1.65; }
.observation-section textarea { width: 100%; min-height: 148px; resize: vertical; box-sizing: border-box; border: 1px solid #ccd0cf; border-radius: 8px; padding: 10px 11px; color: #06141b; font: inherit; font-size: 14px; line-height: 1.6; }
.observation-meta { display: grid; gap: 4px; margin-top: 8px; color: #60727c; font-size: 14px; line-height: 1.45; }
.submit-button { width: 100%; margin-top: 12px; }
.completion-state { display: flex; align-items: flex-start; gap: 9px; margin-top: 12px; border: 1px solid #ccd0cf; border-radius: 8px; padding: 11px; background: #f8fafa; }
.completion-state strong, .completion-state span { display: block; font-size: 14px; }
.completion-state span { margin-top: 3px; color: #4a5c6a; line-height: 1.5; }
.source-row { display: flex; width: 100%; min-height: 58px; align-items: center; justify-content: space-between; gap: 9px; border: 0; border-bottom: 1px solid #e4e8e9; padding: 8px 0; background: transparent; color: #253745; text-align: left; cursor: pointer; }
.source-row span { min-width: 0; }
.source-row strong, .source-row small { display: block; font-size: 14px; }
.source-row small { margin-top: 3px; overflow: hidden; color: #60727c; text-overflow: ellipsis; white-space: nowrap; }
.panel-empty { color: #60727c; font-size: 14px; line-height: 1.55; }
.legacy-header { display: flex; align-items: center; justify-content: space-between; gap: 22px; border-bottom: 1px solid #ccd0cf; padding-bottom: 18px; }
.legacy-header span, .legacy-header p { color: #60727c; font-size: 14px; }
.legacy-header h1 { margin: 4px 0 5px; font-size: 22px; }
.legacy-header p { margin: 0; }
.trust-badge { display: flex; align-items: center; gap: 8px; border: 1px solid #ccd0cf; border-radius: 8px; padding: 10px 12px; background: #fff; }
.trust-badge strong, .trust-badge small { display: block; font-size: 14px; }
.trust-badge small { margin-top: 2px; color: #60727c; }
.legacy-template-list { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; margin-top: 14px; }
.legacy-template-list button { display: flex; min-height: 82px; align-items: flex-start; gap: 10px; border: 1px solid #ccd0cf; border-radius: 8px; padding: 13px; background: #fff; color: #253745; text-align: left; cursor: pointer; }
.legacy-template-list button.active { border-color: #11212d; box-shadow: inset 0 0 0 1px #11212d; }
.legacy-template-list strong, .legacy-template-list small { display: block; font-size: 14px; }
.legacy-template-list small { margin-top: 4px; color: #60727c; line-height: 1.5; }
.legacy-layout { display: grid; grid-template-columns: 230px minmax(0, 1fr); gap: 12px; margin-top: 12px; }
.legacy-history, .legacy-workspace { border: 1px solid #ccd0cf; border-radius: 8px; background: #fff; }
.legacy-history { padding: 12px; }
.legacy-history header { display: flex; min-height: 38px; align-items: center; justify-content: space-between; border-bottom: 1px solid #e4e8e9; }
.legacy-history header strong, .legacy-history header span, .legacy-history p { font-size: 14px; }
.legacy-history header span, .legacy-history p { color: #60727c; }
.legacy-history > button { width: 100%; border: 0; border-bottom: 1px solid #e4e8e9; padding: 10px 7px; background: transparent; color: #253745; text-align: left; cursor: pointer; }
.legacy-history > button.active { background: #eef2f2; }
.legacy-history strong, .legacy-history small { display: block; font-size: 14px; }
.legacy-history small { margin-top: 3px; color: #60727c; }
.legacy-workspace { padding: 18px; }
.legacy-workspace > header span, .legacy-workspace > header p { color: #60727c; font-size: 14px; }
.legacy-workspace h2 { margin: 4px 0 5px; font-size: 20px; }
.legacy-workspace p { margin: 0; line-height: 1.55; }
.legacy-setup, .legacy-parameters { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; margin-top: 16px; }
.legacy-setup label, .legacy-parameters label { display: grid; gap: 6px; color: #4a5c6a; font-size: 14px; }
.legacy-setup label > span, .legacy-parameters label > span { display: flex; align-items: center; justify-content: space-between; gap: 6px; }
.legacy-setup input, .legacy-setup select, .legacy-parameters input[type="number"] { width: 100%; min-height: 38px; box-sizing: border-box; border: 1px solid #ccd0cf; border-radius: 8px; padding: 0 9px; background: #fff; color: #06141b; font-size: 14px; }
.legacy-parameters input[type="range"] { width: 100%; accent-color: #11212d; }
.legacy-actions { display: flex; flex-wrap: wrap; gap: 7px; margin-top: 16px; }
.legacy-actions > button { display: inline-flex; min-height: 38px; align-items: center; gap: 6px; border: 1px solid #ccd0cf; border-radius: 8px; padding: 0 11px; background: #fff; color: #11212d; font-size: 14px; cursor: pointer; }
.legacy-actions > .primary-button { border-color: #11212d; background: #11212d; color: #fff; }
.legacy-results { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); margin-top: 16px; border: 1px solid #dfe4e5; border-radius: 8px; }
.legacy-results > div { padding: 12px; border-right: 1px solid #e4e8e9; }
.legacy-results > div:last-child { border-right: 0; }
.legacy-results span, .legacy-results strong { display: block; font-size: 14px; }
.legacy-results span { color: #60727c; }
.legacy-results strong { margin-top: 5px; font-size: 18px; }
.legacy-acceptance { display: flex; align-items: center; gap: 9px; margin-top: 12px; border: 1px solid #ccd0cf; border-radius: 8px; padding: 11px; background: #f8fafa; }
.legacy-acceptance strong, .legacy-acceptance small { display: block; font-size: 14px; }
.legacy-acceptance small { margin-top: 3px; color: #60727c; }
button:disabled, input:disabled, textarea:disabled, select:disabled { cursor: default; opacity: .5; }
button:focus-visible, input:focus-visible, textarea:focus-visible, select:focus-visible { outline: 2px solid #11212d; outline-offset: 2px; }
.spin { animation: spin .8s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
@media (max-width: 1180px) {
  .interactive-page { padding: 14px; }
  .model-layout { grid-template-columns: 226px minmax(390px, 1fr) 276px; gap: 9px; }
  .result-pane { padding: 14px; }
  .series-switch button { padding: 0 6px; }
}
</style>
