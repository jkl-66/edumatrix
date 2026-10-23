<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  AlertCircle,
  ArrowLeft,
  Check,
  CheckCircle2,
  ChevronRight,
  Circle,
  Clock3,
  FileCode2,
  FileText,
  History,
  Image,
  LoaderCircle,
  NotebookPen,
  Octagon,
  Play,
  RotateCcw,
  Save,
  ShieldAlert,
  Square,
  TerminalSquare,
} from '@lucide/vue'
import * as monaco from 'monaco-editor/editor/editor.api'
import EditorWorker from 'monaco-editor/editor/editor.worker?worker'
import 'monaco-editor/languages/definitions/python/register'
import {
  completeCodeSandboxLearning,
  getCodeSandboxRun,
  getCodeSandboxStatus,
  listCodeSandboxRuns,
  startCodeSandboxRun,
  stopCodeSandboxRun,
} from '../api/codeSandbox'
import {
  compareM5ResourceVersions,
  createM5ResourceVersion,
  getM5Resource,
  restoreM5ResourceVersion,
} from '../api/m5'
import ResourceHistoryDrawer from '../components/ResourceHistoryDrawer.vue'
import CodeReviewPanel from '../components/CodeReviewPanel.vue'
import ResourceProfileAdaptation from '../components/ResourceProfileAdaptation.vue'
import { loadStoredContext, saveStoredContext } from '../services/context'
import { createNote } from '../api/notes'

globalThis.MonacoEnvironment = {
  getWorker() {
    return new EditorWorker()
  },
}

const route = useRoute()
const router = useRouter()
const editorHost = ref(null)
const resourceId = computed(() => String(route.params.resourceId || ''))
const activeStudentId = computed(() => localStorage.getItem('edumatrix_student_id') || localStorage.getItem('edumatrix_username') || '')

const loading = ref(true)
const error = ref('')
const notice = ref('')
const detail = ref(null)
const runtime = ref(null)
const selectedVersionId = ref('')
const activeFilePath = ref('')
const fileContents = ref({})
const standardInput = ref('')
const saving = ref(false)
const running = ref(false)
const stopping = ref(false)
const completing = ref(false)
const noteBusy = ref(false)
const completionResult = ref(null)
const leftTab = ref('task')
const outputTab = ref('stdout')
const runs = ref([])
const selectedRun = ref(null)
const selectedPlotId = ref('')
const completeOutputBusy = ref(false)
const completeOutputView = ref({ stdout: false, stderr: false })

const historyOpen = ref(false)
const historyError = ref('')
const restoringId = ref('')
const comparingId = ref('')
const compareResult = ref(null)

let editor = null
let editorSubscription = null
let pollingTimer = null
let syncingEditor = false

const workspace = computed(() => detail.value?.code_sandbox || {})
const versions = computed(() => workspace.value.versions || [])
const currentVersionId = computed(() => workspace.value.current_version_id || detail.value?.current_version_id || '')
const selectedVersion = computed(() => (
  versions.value.find(item => item.id === selectedVersionId.value)
  || versions.value.find(item => item.id === currentVersionId.value)
  || null
))
const projection = computed(() => selectedVersion.value?.projection || workspace.value.current || null)
const structured = computed(() => projection.value?.structured || null)
const catalog = computed(() => detail.value?.catalog || {})
const isCurrentVersion = computed(() => selectedVersion.value?.id === currentVersionId.value)
const sourceReady = computed(() => projection.value?.source_readiness?.publishable === true)
const currentFile = computed(() => structured.value?.files?.find(item => item.path === activeFilePath.value) || null)
const entryCode = computed(() => fileContents.value[structured.value?.entryFile || ''] || '')
const activeCode = computed(() => fileContents.value[activeFilePath.value] || '')
const activeRun = computed(() => ['queued', 'running'].includes(selectedRun.value?.status))
const selectedPlot = computed(() => (
  selectedRun.value?.plots?.find(item => item.id === selectedPlotId.value)
  || selectedRun.value?.plots?.[0]
  || null
))
const displayedStdout = computed(() => (
  completeOutputView.value.stdout && selectedRun.value?.stdoutComplete?.available
    ? selectedRun.value.stdoutComplete.text
    : selectedRun.value?.stdout || ''
))
const displayedStderr = computed(() => (
  completeOutputView.value.stderr && selectedRun.value?.stderrComplete?.available
    ? selectedRun.value.stderrComplete.text
    : selectedRun.value?.stderr || ''
))
const stderrIsWarning = computed(() => (
  selectedRun.value?.status === 'success' && Boolean(selectedRun.value?.stderr)
))
const stderrLabel = computed(() => stderrIsWarning.value ? '警告' : '错误')
const draftChanged = computed(() => {
  if (!structured.value || !isCurrentVersion.value) return false
  const fileChanged = structured.value.files.some(item => fileContents.value[item.path] !== item.content)
  return fileChanged || standardInput.value !== structured.value.standardInput
})
const allChecksPassed = computed(() => (
  selectedRun.value?.status === 'success'
  && Number(selectedRun.value?.totalCount || 0) > 0
  && selectedRun.value?.passedCount === selectedRun.value?.totalCount
))
const completionRecorded = computed(() => (
  Boolean(completionResult.value)
  || workspace.value?.completion?.status === 'completed'
  || catalog.value?.completion?.status === 'completed'
))
const canRun = computed(() => (
  isCurrentVersion.value
  && sourceReady.value
  && runtime.value?.executionEnabled
  && Boolean(entryCode.value.trim())
  && !activeRun.value
  && !loading.value
  && !saving.value
))
const canComplete = computed(() => (
  allChecksPassed.value
  && selectedRun.value?.sourceResourceVersionId === currentVersionId.value
  && selectedRun.value?.code === entryCode.value.trimEnd()
  && selectedRun.value?.standardInput === standardInput.value
  && !draftChanged.value
  && !completionRecorded.value
  && !completing.value
))
const historyItems = computed(() => versions.value.map(item => ({
  ...item,
  revision_origin: item.revision_origin || item.metadata?.revision_origin,
  source_status: item.projection?.source_readiness?.publishable ? 'available' : 'unavailable',
})))

function message(caught, fallback = '请求失败，请稍后重试。') {
  const value = caught?.response?.data?.detail || caught?.detail
  return value?.message || (typeof value === 'string' ? value : '') || caught?.message || fallback
}

function key(prefix) {
  return `${prefix}-${globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(36).slice(2, 9)}`}`
}

function invalidateStoredContextVersion() {
  saveStoredContext({ ...loadStoredContext(), version: null })
}

function formatDate(value) {
  if (!value) return '时间未记录'
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit',
  }).format(new Date(value))
}

function statusLabel(status) {
  return ({
    queued: '排队中', running: '运行中', stopped: '已停止', success: '运行成功',
    runtime_error: '运行报错', timeout: '运行超时',
  })[status] || '未运行'
}

function statusDetail(run) {
  if (!run) return '运行后将在这里看到真实输出和检查结果。'
  if (run.status === 'success') return `通过 ${run.passedCount}/${run.totalCount} 项必需检查，用时 ${run.executionTimeMs} ms。`
  if (run.status === 'runtime_error') return '程序已结束，但存在运行错误或必需检查未通过。'
  if (run.status === 'timeout') return `运行超过 ${run.timeoutSeconds || structured.value?.runtime?.timeoutSeconds || '--'} 秒，进程树已清理。`
  if (run.status === 'stopped') return '运行已由用户停止，子进程树已清理。'
  return '服务端正在执行当前代码，请稍候。'
}

function versionLabel() {
  return selectedVersion.value ? `v${selectedVersion.value.number}` : '版本未记录'
}

function editorValue(value) {
  if (!editor || editor.getValue() === value) return
  syncingEditor = true
  editor.setValue(value || '')
  syncingEditor = false
}

function syncVersionDraft() {
  const files = structured.value?.files || []
  fileContents.value = Object.fromEntries(files.map(item => [item.path, item.content]))
  standardInput.value = structured.value?.standardInput || ''
  activeFilePath.value = structured.value?.entryFile || files[0]?.path || ''
  completionResult.value = null
  nextTick(() => {
    editorValue(fileContents.value[activeFilePath.value] || '')
    editor?.updateOptions({ readOnly: !isCurrentVersion.value })
  })
}

function mountEditor() {
  if (!editorHost.value || editor) return
  editor = monaco.editor.create(editorHost.value, {
    value: activeCode.value,
    language: currentFile.value?.language || 'python',
    theme: 'vs',
    automaticLayout: true,
    readOnly: !isCurrentVersion.value,
    fontFamily: "'Cascadia Code', Consolas, monospace",
    fontSize: 14,
    lineHeight: 22,
    minimap: { enabled: false },
    scrollBeyondLastLine: false,
    padding: { top: 14, bottom: 14 },
    renderLineHighlight: 'line',
    roundedSelection: false,
    overviewRulerBorder: false,
    wordWrap: 'on',
    tabSize: 4,
  })
  editorSubscription = editor.onDidChangeModelContent(() => {
    if (!syncingEditor && isCurrentVersion.value && activeFilePath.value) {
      fileContents.value = { ...fileContents.value, [activeFilePath.value]: editor.getValue() }
    }
  })
}

function clearPolling() {
  if (pollingTimer) window.clearTimeout(pollingTimer)
  pollingTimer = null
}

async function refreshRuns(preferredRunId = '') {
  const response = await listCodeSandboxRuns(resourceId.value)
  runs.value = response.items || []
  const runId = preferredRunId || selectedRun.value?.runAttemptId || runs.value[0]?.runAttemptId
  if (runId) await selectRun(runId, false)
}

async function loadResource() {
  clearPolling()
  loading.value = true
  error.value = ''
  notice.value = ''
  try {
    const [resource, runtimeStatus, runList] = await Promise.all([
      getM5Resource(resourceId.value),
      getCodeSandboxStatus(),
      listCodeSandboxRuns(resourceId.value),
    ])
    if (!resource?.code_sandbox) throw new Error('当前资源不是正式代码沙盒。')
    detail.value = resource
    runtime.value = runtimeStatus
    runs.value = runList.items || []
    selectedVersionId.value = resource.code_sandbox.current_version_id || resource.current_version_id || ''
    syncVersionDraft()
    if (runs.value[0]?.runAttemptId) await selectRun(runs.value[0].runAttemptId)
  } catch (caught) {
    error.value = message(caught, '代码沙盒暂时无法打开。')
  } finally {
    loading.value = false
    await nextTick()
    if (structured.value) {
      mountEditor()
      editorValue(fileContents.value[activeFilePath.value] || '')
    }
  }
}

function selectFile(path) {
  if (path === activeFilePath.value) return
  activeFilePath.value = path
  editorValue(fileContents.value[path] || '')
  monaco.editor.setModelLanguage(editor?.getModel(), structured.value?.files?.find(item => item.path === path)?.language || 'python')
}

async function saveVersion() {
  if (!draftChanged.value || !isCurrentVersion.value || saving.value) return
  saving.value = true
  error.value = ''
  notice.value = ''
  try {
    const content = JSON.parse(JSON.stringify(structured.value))
    content.files = content.files.map(item => ({ ...item, content: fileContents.value[item.path] }))
    content.standardInput = standardInput.value
    detail.value = await createM5ResourceVersion(resourceId.value, {
      expected_lock_version: detail.value.lock_version,
      source_version_id: currentVersionId.value,
      content: JSON.stringify(content),
      content_format: 'json',
    })
    selectedVersionId.value = detail.value.code_sandbox?.current_version_id || detail.value.current_version_id || ''
    syncVersionDraft()
    invalidateStoredContextVersion()
    await refreshRuns()
    notice.value = '代码和标准输入已另存为新版本。请基于新版本重新运行。'
  } catch (caught) {
    error.value = message(caught, '当前代码未能保存。')
  } finally {
    saving.value = false
  }
}

async function startRun() {
  if (!canRun.value) return
  running.value = true
  error.value = ''
  notice.value = ''
  outputTab.value = 'stdout'
  try {
    const run = await startCodeSandboxRun(resourceId.value, {
      resource_version_id: currentVersionId.value,
      code: entryCode.value,
      standard_input: standardInput.value,
      idempotency_key: key('code-run'),
    })
    selectedRun.value = run
    selectedPlotId.value = ''
    leftTab.value = 'history'
    await refreshRuns(run.runAttemptId)
    schedulePoll(run.runAttemptId)
  } catch (caught) {
    error.value = message(caught, '代码未能开始运行。')
  } finally {
    running.value = false
  }
}

function schedulePoll(runAttemptId) {
  clearPolling()
  if (!['queued', 'running'].includes(selectedRun.value?.status)) return
  pollingTimer = window.setTimeout(async () => {
    try {
      const run = await getCodeSandboxRun(runAttemptId)
      selectedRun.value = run
      const index = runs.value.findIndex(item => item.runAttemptId === runAttemptId)
      const summary = {
        runAttemptId: run.runAttemptId,
        sourceResourceVersionId: run.sourceResourceVersionId,
        status: run.status,
        createdAt: run.createdAt,
        completedAt: run.completedAt,
        executionTimeMs: run.executionTimeMs,
        passedCount: run.passedCount,
        totalCount: run.totalCount,
        codeSha256: run.codeSha256,
        hasStdout: Boolean(run.stdout),
        hasStderr: Boolean(run.stderr),
        stdoutTruncated: Boolean(run.stdoutCapture?.truncated),
        stderrTruncated: Boolean(run.stderrCapture?.truncated),
        stdoutCompleteAvailable: Boolean(run.stdoutComplete?.available),
        stderrCompleteAvailable: Boolean(run.stderrComplete?.available),
        plotCount: run.plots?.length || 0,
      }
      if (index >= 0) runs.value.splice(index, 1, summary)
      else runs.value.unshift(summary)
      if (run.plots?.length && !selectedPlotId.value) selectedPlotId.value = run.plots[0].id
      if (['queued', 'running'].includes(run.status)) schedulePoll(runAttemptId)
      else notice.value = statusDetail(run)
    } catch (caught) {
      error.value = message(caught, '运行状态刷新失败，可从运行历史重新打开。')
    }
  }, 650)
}

async function selectRun(runAttemptId, switchTab = true) {
  clearPolling()
  error.value = ''
  try {
    selectedRun.value = await getCodeSandboxRun(runAttemptId)
    selectedPlotId.value = selectedRun.value.plots?.[0]?.id || ''
    completeOutputView.value = { stdout: false, stderr: false }
    if (switchTab) leftTab.value = 'history'
    if (['queued', 'running'].includes(selectedRun.value.status)) schedulePoll(runAttemptId)
  } catch (caught) {
    error.value = message(caught, '运行记录无法打开。')
  }
}

async function loadCompleteOutput(channel) {
  const run = selectedRun.value
  const field = channel === 'stderr' ? 'stderrComplete' : 'stdoutComplete'
  if (!run?.runAttemptId || !run[field]?.available || completeOutputBusy.value) return
  if (completeOutputView.value[channel]) {
    completeOutputView.value = { ...completeOutputView.value, [channel]: false }
    return
  }
  if (!run.completeOutputIncluded) {
    completeOutputBusy.value = true
    try {
      selectedRun.value = await getCodeSandboxRun(run.runAttemptId, true)
    } catch (caught) {
      error.value = message(caught, '完整运行结果暂时无法读取。')
      return
    } finally {
      completeOutputBusy.value = false
    }
  }
  completeOutputView.value = { ...completeOutputView.value, [channel]: true }
}

async function stopRun() {
  if (!activeRun.value || stopping.value) return
  stopping.value = true
  error.value = ''
  try {
    await stopCodeSandboxRun(selectedRun.value.runAttemptId)
    schedulePoll(selectedRun.value.runAttemptId)
  } catch (caught) {
    error.value = message(caught, '未能停止当前运行。')
  } finally {
    stopping.value = false
  }
}

async function completeLearning() {
  if (!canComplete.value) return
  completing.value = true
  error.value = ''
  try {
    completionResult.value = await completeCodeSandboxLearning(resourceId.value, {
      run_attempt_id: selectedRun.value.runAttemptId,
      idempotency_key: `code-complete-${selectedRun.value.runAttemptId}`,
      context: {
        courseId: catalog.value.course?.id || detail.value.course_id || undefined,
        taskId: route.query.task_id || undefined,
        pathId: route.query.path_id || undefined,
      },
      actual_minutes: null,
    })
    invalidateStoredContextVersion()
    notice.value = '完成证据已记录，画像、路径和今日任务会读取同一条学习事件。'
  } catch (caught) {
    error.value = message(caught, '完成证据未能提交。')
  } finally {
    completing.value = false
  }
}

async function handleReviewApplied(result) {
  detail.value = result.resource
  selectedVersionId.value = result.resource?.code_sandbox?.current_version_id || result.resource?.current_version_id || ''
  syncVersionDraft()
  invalidateStoredContextVersion()
  await refreshRuns(selectedRun.value?.runAttemptId || '')
  outputTab.value = 'review'
  notice.value = `点评建议已另存为 v${result.resourceVersionNumber}。请点击顶部“运行代码”，再从左侧历史比较前后结果。`
}

function selectHistoryVersion(versionId) {
  if (draftChanged.value && versionId !== selectedVersionId.value) {
    historyError.value = '当前代码尚未保存。请先保存新版本，再查看历史版本。'
    return
  }
  selectedVersionId.value = versionId
  historyOpen.value = false
  syncVersionDraft()
}

async function compareHistory(versionId) {
  comparingId.value = versionId
  historyError.value = ''
  try {
    const left = versions.value.find(item => item.id === versionId)
    const right = versions.value.find(item => item.id === currentVersionId.value)
    if (left && right) compareResult.value = await compareM5ResourceVersions(resourceId.value, left.number, right.number)
  } catch (caught) {
    historyError.value = message(caught)
  } finally {
    comparingId.value = ''
  }
}

async function restoreHistory(versionId) {
  if (draftChanged.value || restoringId.value) {
    historyError.value = '当前代码尚未保存，不能恢复其他版本。'
    return
  }
  restoringId.value = versionId
  historyError.value = ''
  try {
    detail.value = await restoreM5ResourceVersion(resourceId.value, {
      expected_lock_version: detail.value.lock_version,
      version_id: versionId,
    })
    selectedVersionId.value = detail.value.code_sandbox?.current_version_id || detail.value.current_version_id || ''
    historyOpen.value = false
    syncVersionDraft()
    invalidateStoredContextVersion()
    await refreshRuns()
    notice.value = '历史内容已恢复并另存为新的当前版本。'
  } catch (caught) {
    historyError.value = message(caught)
  } finally {
    restoringId.value = ''
  }
}

function openSource(source) {
  if (!source?.available || !source.source_document_id) return
  router.push({
    name: 'KnowledgeDocument',
    params: { documentId: source.source_document_id },
    query: {
      course_id: catalog.value.course?.id || detail.value.course_id,
      focus_source_ref_id: source.source_ref_id,
      return_to: route.fullPath,
    },
  })
}

async function openSourceNote() {
  if (!activeStudentId.value || !selectedVersion.value || draftChanged.value || noteBusy.value) return
  noteBusy.value = true
  error.value = ''
  try {
    const note = await createNote(activeStudentId.value, {
      source_type: 'code_sandbox',
      source_metadata: {
        resource_id: resourceId.value,
        resource_version_id: selectedVersion.value.id,
      },
      content: `# ${structured.value?.title || catalog.value.title || '代码实训'}\n\n运行与调试记录：`,
      tags: ['代码沙盒'],
      concepts: structured.value?.knowledgePoint?.title ? [structured.value.knowledgePoint.title] : [],
      idempotency_key: `sandbox-note-${resourceId.value}-${selectedVersion.value.id}`,
    })
    await router.push({ name: 'Notes', query: { note_id: note.id } })
  } catch (caught) {
    error.value = message(caught) || '来源笔记没有创建，代码与运行结果未受影响。'
  } finally {
    noteBusy.value = false
  }
}

watch(resourceId, loadResource)
watch(isCurrentVersion, value => editor?.updateOptions({ readOnly: !value }))
onMounted(loadResource)
onBeforeUnmount(() => {
  clearPolling()
  editorSubscription?.dispose()
  editor?.dispose()
})
</script>

<template>
  <main class="sandbox-page" data-testid="code-sandbox-workspace">
    <header class="sandbox-header">
      <button type="button" class="icon-button" title="返回资源中心" @click="router.push('/workspace/resources')">
        <ArrowLeft :size="18" />
      </button>
      <div class="sandbox-title">
        <span>代码沙盒 · {{ versionLabel() }}</span>
        <h1>{{ structured?.title || catalog.title || '代码实训' }}</h1>
        <p>{{ structured?.knowledgePoint?.title || '当前知识点' }} · {{ draftChanged ? '有未保存修改' : '内容已保存' }}</p>
      </div>
      <div class="header-actions">
        <button
          type="button"
          class="icon-button"
          title="保存当前代码版本的来源笔记"
          aria-label="保存当前代码版本的来源笔记"
          :disabled="!selectedVersion || draftChanged || noteBusy"
          @click="openSourceNote"
        >
          <LoaderCircle v-if="noteBusy" :size="16" class="spin" />
          <NotebookPen v-else :size="17" />
        </button>
        <button type="button" class="secondary-button" :disabled="loading" @click="historyOpen = true">
          <History :size="16" />版本历史 <strong>{{ versions.length }}</strong>
        </button>
        <button type="button" class="secondary-button" :disabled="!draftChanged || saving || !isCurrentVersion" @click="saveVersion">
          <LoaderCircle v-if="saving" :size="16" class="spin" /><Save v-else :size="16" />
          {{ saving ? '保存中' : '保存新版本' }}
        </button>
        <button v-if="activeRun" type="button" class="stop-button" :disabled="stopping" @click="stopRun">
          <LoaderCircle v-if="stopping" :size="16" class="spin" /><Square v-else :size="15" />
          {{ stopping ? '停止中' : '停止' }}
        </button>
        <button v-else type="button" class="primary-button" :disabled="!canRun" @click="startRun">
          <LoaderCircle v-if="running" :size="16" class="spin" /><Play v-else :size="16" />
          {{ running ? '启动中' : '运行代码' }}
        </button>
      </div>
    </header>

    <div v-if="error" class="page-message error-message" role="alert">
      <AlertCircle :size="17" /><span>{{ error }}</span>
      <button type="button" @click="error = ''">关闭</button>
    </div>
    <div v-else-if="notice" class="page-message notice-message" role="status">
      <CheckCircle2 :size="17" /><span>{{ notice }}</span>
      <button type="button" @click="notice = ''">关闭</button>
    </div>

    <section v-if="loading" class="loading-state">
      <LoaderCircle :size="24" class="spin" /><strong>正在恢复代码沙盒</strong><span>代码、版本和运行历史会一并恢复。</span>
    </section>

    <section v-else-if="!structured" class="invalid-state">
      <ShieldAlert :size="28" /><h2>当前版本不能运行</h2>
      <p>{{ projection?.source_readiness?.reason || '代码沙盒结构不完整，请恢复有效版本。' }}</p>
      <button type="button" class="secondary-button" @click="historyOpen = true"><RotateCcw :size="16" />查看版本历史</button>
    </section>

    <template v-else>
      <ResourceProfileAdaptation
        :adaptation="structured?.adaptation"
        :plan="detail?.resource?.profile_adaptation_plan"
        :summary="structured?.adaptation?.profileSummary || ''"
        resource-type="code_sandbox"
      />
      <section class="sandbox-grid">
      <aside class="left-panel" aria-label="任务和历史">
        <div class="panel-tabs" role="tablist">
          <button type="button" :class="{ active: leftTab === 'task' }" @click="leftTab = 'task'">任务</button>
          <button type="button" :class="{ active: leftTab === 'history' }" @click="leftTab = 'history'">运行历史 <span>{{ runs.length }}</span></button>
        </div>

        <div v-if="leftTab === 'task'" class="left-scroll">
          <section class="task-intro">
            <span>{{ structured.courseTitle }}</span>
            <h2>{{ structured.knowledgePoint.title }}</h2>
            <p>{{ structured.summary }}</p>
          </section>
          <ol class="checkpoint-list">
            <li v-for="(checkpoint, index) in structured.checkpoints" :key="checkpoint.id">
              <span class="checkpoint-index">{{ String(index + 1).padStart(2, '0') }}</span>
              <div><strong>{{ checkpoint.title }}</strong><p>{{ checkpoint.instruction }}</p><small>{{ checkpoint.completionHint }}</small></div>
            </li>
          </ol>
          <section class="source-section">
            <h3>课程来源</h3>
            <button v-for="source in projection.source_refs" :key="source.source_ref_id" type="button" :disabled="!source.available" @click="openSource(source)">
              <span><strong>{{ source.title }}</strong><small>{{ source.location_label || '位置未记录' }}</small></span><ChevronRight :size="16" />
            </button>
          </section>
          <section class="runtime-boundary">
            <ShieldAlert :size="17" />
            <div><strong>本地研究模式</strong><p>{{ runtime?.message || structured.runtime.boundary }}</p></div>
          </section>
        </div>

        <div v-else class="left-scroll run-history">
          <button v-for="run in runs" :key="run.runAttemptId" type="button" :class="{ selected: run.runAttemptId === selectedRun?.runAttemptId }" @click="selectRun(run.runAttemptId)">
            <span class="run-status-icon"><LoaderCircle v-if="['queued', 'running'].includes(run.status)" :size="16" class="spin" /><Check v-else-if="run.status === 'success'" :size="16" /><Octagon v-else :size="15" /></span>
            <span><strong>{{ statusLabel(run.status) }}</strong><small>{{ formatDate(run.createdAt) }}</small><small>{{ run.passedCount || 0 }}/{{ run.totalCount || 0 }} 检查 · {{ run.executionTimeMs || 0 }} ms</small></span>
          </button>
          <div v-if="!runs.length" class="panel-empty"><History :size="23" /><strong>还没有运行记录</strong><span>点击“运行代码”后，真实结果会保存在这里。</span></div>
        </div>
      </aside>

      <section class="editor-panel" aria-label="代码编辑器">
        <div class="file-bar">
          <div class="file-tabs">
            <button v-for="file in structured.files" :key="file.path" type="button" :class="{ active: file.path === activeFilePath }" @click="selectFile(file.path)">
              <FileCode2 :size="15" />{{ file.path }}<Circle v-if="isCurrentVersion && fileContents[file.path] !== file.content" :size="8" fill="currentColor" />
            </button>
          </div>
          <span>{{ isCurrentVersion ? '可编辑' : '历史版本只读' }}</span>
        </div>
        <div ref="editorHost" class="editor-host" data-testid="monaco-editor" />
        <label class="stdin-panel">
          <span><TerminalSquare :size="16" />标准输入</span>
          <textarea v-model="standardInput" :readonly="!isCurrentVersion" rows="3" placeholder="程序将从标准输入读取这些内容。" />
        </label>
      </section>

      <aside class="result-panel" aria-label="运行结果">
        <div class="result-summary" :class="`status-${selectedRun?.status || 'idle'}`">
          <span class="result-icon"><LoaderCircle v-if="activeRun" :size="19" class="spin" /><CheckCircle2 v-else-if="selectedRun?.status === 'success'" :size="19" /><AlertCircle v-else-if="selectedRun" :size="19" /><TerminalSquare v-else :size="19" /></span>
          <div><strong>{{ statusLabel(selectedRun?.status) }}</strong><p>{{ statusDetail(selectedRun) }}</p></div>
        </div>

        <div class="panel-tabs result-tabs" role="tablist">
          <button type="button" :class="{ active: outputTab === 'stdout' }" @click="outputTab = 'stdout'">输出</button>
          <button type="button" :class="{ active: outputTab === 'stderr' }" @click="outputTab = 'stderr'">{{ stderrLabel }} <span v-if="selectedRun?.stderr">1</span></button>
          <button type="button" :class="{ active: outputTab === 'plots' }" @click="outputTab = 'plots'">图表 <span>{{ selectedRun?.plots?.length || 0 }}</span></button>
          <button type="button" :class="{ active: outputTab === 'review' }" @click="outputTab = 'review'">AI 点评</button>
        </div>

        <div class="result-scroll">
          <template v-if="outputTab === 'stdout'">
            <div v-if="selectedRun?.stdoutCapture?.truncated" class="capture-note">
              <div>预览保留开头和结尾，省略 {{ selectedRun.stdoutCapture.omittedBytes }} 字节；原始总量 {{ selectedRun.stdoutCapture.totalBytes }} 字节。</div>
              <button v-if="selectedRun.stdoutComplete?.available" type="button" class="complete-output-button" :disabled="completeOutputBusy" @click="loadCompleteOutput('stdout')">
                <LoaderCircle v-if="completeOutputBusy" :size="14" class="spin" /><FileText v-else :size="14" />
                {{ completeOutputView.stdout ? '显示预览' : '查看完整结果' }}
              </button>
              <div v-if="selectedRun.stdoutComplete && !selectedRun.stdoutComplete.available" class="capture-unavailable">完整结果不可用：{{ selectedRun.stdoutComplete.reason }}</div>
            </div>
            <pre v-if="displayedStdout" class="terminal-output">{{ displayedStdout }}</pre>
            <div v-else class="panel-empty"><TerminalSquare :size="23" /><strong>等待标准输出</strong><span>运行当前代码后，print 等真实输出会显示在这里。</span></div>
          </template>
          <template v-else-if="outputTab === 'stderr'">
            <div v-if="selectedRun?.stderrCapture?.truncated" class="capture-note">
              <div>{{ stderrIsWarning ? '警告' : '错误' }}预览省略 {{ selectedRun.stderrCapture.omittedBytes }} 字节；原始总量 {{ selectedRun.stderrCapture.totalBytes }} 字节。</div>
              <button v-if="selectedRun.stderrComplete?.available" type="button" class="complete-output-button" :disabled="completeOutputBusy" @click="loadCompleteOutput('stderr')">
                <LoaderCircle v-if="completeOutputBusy" :size="14" class="spin" /><FileText v-else :size="14" />
                {{ completeOutputView.stderr ? '显示预览' : '查看完整结果' }}
              </button>
              <div v-if="selectedRun.stderrComplete && !selectedRun.stderrComplete.available" class="capture-unavailable">完整结果不可用：{{ selectedRun.stderrComplete.reason }}</div>
            </div>
            <pre v-if="displayedStderr" class="terminal-output" :class="{ 'error-output': !stderrIsWarning }">{{ displayedStderr }}</pre>
            <div v-else class="panel-empty"><CheckCircle2 :size="23" /><strong>没有错误输出</strong><span>{{ selectedRun ? '当前运行未记录 stderr。' : '运行后将在这里显示真实报错。' }}</span></div>
          </template>
          <template v-else-if="outputTab === 'plots'">
            <div v-if="selectedRun?.plots?.length" class="plot-viewer">
              <div class="plot-tabs"><button v-for="plot in selectedRun.plots" :key="plot.id" type="button" :class="{ active: plot.id === selectedPlot?.id }" @click="selectedPlotId = plot.id">{{ plot.title }}</button></div>
              <img v-if="selectedPlot" :src="selectedPlot.dataUrl" :alt="selectedPlot.title" />
              <p v-if="selectedRun.plotError" class="plot-error">{{ selectedRun.plotError }}</p>
            </div>
            <div v-else class="panel-empty"><Image :size="23" /><strong>还没有图表</strong><span>Matplotlib 图表会在真实运行结束后显示。</span></div>
          </template>
          <CodeReviewPanel
            v-else
            :resource-id="resourceId"
            :run="selectedRun"
            :resource-lock-version="detail.lock_version"
            @applied="handleReviewApplied"
          />

          <section v-if="selectedRun" class="check-results">
            <h3>必需检查</h3>
            <ul>
              <li v-for="check in selectedRun.checks || structured.requiredChecks" :key="check.id" :class="{ passed: check.passed }">
                <CheckCircle2 v-if="check.passed" :size="16" /><Circle v-else :size="16" />
                <span><strong>{{ check.label }}</strong><small>{{ check.detail || '等待运行结果' }}</small></span>
              </li>
            </ul>
          </section>
        </div>

        <footer class="completion-bar">
          <div><strong>{{ completionRecorded ? '本次学习已完成' : '完成学习' }}</strong><span>{{ structured.completionRule }}</span></div>
          <button type="button" class="primary-button" :disabled="!canComplete" @click="completeLearning">
            <LoaderCircle v-if="completing" :size="16" class="spin" /><CheckCircle2 v-else :size="16" />
            {{ completionRecorded ? '已记录证据' : completing ? '提交中' : '完成学习' }}
          </button>
        </footer>
      </aside>
      </section>
    </template>

    <ResourceHistoryDrawer
      :open="historyOpen"
      title="代码沙盒版本历史"
      :items="historyItems"
      :current-version-id="currentVersionId"
      :selected-version-id="selectedVersionId"
      :restoring-id="restoringId"
      :comparing-id="comparingId"
      :error="historyError"
      :compare-result="compareResult"
      :restore-disabled="draftChanged"
      @close="historyOpen = false"
      @select="selectHistoryVersion"
      @compare="compareHistory"
      @restore="restoreHistory"
      @compare-close="compareResult = null"
    />
  </main>
</template>

<style scoped>
.sandbox-page { --ink: #06141b; --action: #11212d; --muted: #60727c; --line: #ccd0cf; --soft-line: #e4e8e8; --paper: #fff; min-width: 0; color: var(--ink); font-family: 'Source Han Sans SC', 'Noto Sans CJK SC', 'Microsoft YaHei', sans-serif; }
.sandbox-header { display: flex; min-width: 0; align-items: center; gap: 12px; margin-bottom: 10px; padding: 10px 12px; border: 1px solid var(--line); border-radius: 8px; background: var(--paper); }
.icon-button { display: grid; width: 38px; height: 38px; flex: 0 0 38px; place-items: center; border: 1px solid var(--line); border-radius: 8px; background: #fff; color: var(--action); cursor: pointer; }
.sandbox-title { min-width: 0; flex: 1; }
.sandbox-title > span, .sandbox-title p { color: var(--muted); font-size: 14px; line-height: 1.35; }
.sandbox-title h1 { margin: 2px 0; overflow: hidden; font-size: 19px; line-height: 1.35; text-overflow: ellipsis; white-space: nowrap; }
.sandbox-title p { margin: 0; }
.header-actions { display: flex; flex: 0 0 auto; align-items: center; gap: 7px; }
.secondary-button, .primary-button, .stop-button { display: inline-flex; min-height: 38px; align-items: center; justify-content: center; gap: 6px; border: 1px solid var(--line); border-radius: 8px; padding: 0 10px; background: #fff; color: var(--action); font-size: 14px; cursor: pointer; white-space: nowrap; }
.secondary-button strong { color: var(--muted); font-size: 14px; }
.primary-button { border-color: var(--action); background: var(--action); color: #fff; font-weight: 650; }
.stop-button { border-color: #b87a73; background: #fff7f6; color: #873d35; }
button:disabled { cursor: default; opacity: .45; }
button:focus-visible, textarea:focus-visible { outline: 2px solid var(--action); outline-offset: 2px; }
.page-message { display: flex; min-height: 42px; align-items: center; gap: 8px; margin-bottom: 10px; padding: 8px 11px; border: 1px solid var(--line); border-radius: 8px; font-size: 14px; line-height: 1.5; }
.page-message span { flex: 1; }.page-message button { border: 0; background: transparent; color: inherit; cursor: pointer; font-size: 14px; text-decoration: underline; }
.error-message { border-color: #d8aaa5; background: #fff5f3; color: #873d35; }.notice-message { background: #f6f8f8; color: #253745; }
.loading-state, .invalid-state { display: grid; min-height: 560px; place-content: center; justify-items: center; gap: 9px; border: 1px solid var(--line); border-radius: 8px; background: #fff; text-align: center; }
.loading-state span, .invalid-state p { max-width: 52ch; color: var(--muted); font-size: 14px; line-height: 1.65; }.invalid-state h2 { margin: 0; font-size: 20px; }
.sandbox-grid { display: grid; height: calc(100vh - 158px); min-height: 640px; min-width: 1080px; overflow: hidden; grid-template-columns: 22fr 50fr 28fr; border: 1px solid var(--line); border-radius: 8px; background: #fff; }
.left-panel, .editor-panel, .result-panel { min-width: 0; min-height: 0; background: #fff; }
.left-panel, .editor-panel { border-right: 1px solid var(--line); }
.left-panel, .result-panel { display: flex; flex-direction: column; }
.panel-tabs { display: flex; min-height: 43px; flex: 0 0 43px; align-items: flex-end; gap: 4px; padding: 0 10px; border-bottom: 1px solid var(--soft-line); }
.panel-tabs button { min-height: 42px; border: 0; border-bottom: 2px solid transparent; padding: 0 8px; background: transparent; color: var(--muted); font-size: 14px; cursor: pointer; }
.panel-tabs button.active { border-bottom-color: var(--action); color: var(--ink); font-weight: 650; }.panel-tabs span { font-variant-numeric: tabular-nums; }
.left-scroll, .result-scroll { min-height: 0; flex: 1; overflow: auto; }
.task-intro { padding: 16px; border-bottom: 1px solid var(--soft-line); }.task-intro span { color: var(--muted); font-size: 14px; }.task-intro h2 { margin: 4px 0 7px; font-size: 19px; line-height: 1.35; }.task-intro p { margin: 0; color: #4a5c6a; font-size: 14px; line-height: 1.65; }
.checkpoint-list { margin: 0; padding: 8px 16px; list-style: none; }.checkpoint-list li { display: grid; grid-template-columns: 30px minmax(0, 1fr); gap: 9px; padding: 12px 0; border-bottom: 1px solid var(--soft-line); }.checkpoint-index { color: var(--muted); font-size: 14px; font-variant-numeric: tabular-nums; }.checkpoint-list strong { font-size: 14px; line-height: 1.45; }.checkpoint-list p { margin: 4px 0; color: #4a5c6a; font-size: 14px; line-height: 1.55; }.checkpoint-list small { color: var(--muted); font-size: 14px; line-height: 1.5; }
.source-section { padding: 10px 16px; }.source-section h3, .check-results h3 { margin: 0 0 8px; font-size: 15px; }.source-section button { display: flex; width: 100%; align-items: center; justify-content: space-between; gap: 8px; border: 0; border-top: 1px solid var(--soft-line); padding: 10px 0; background: transparent; color: var(--ink); text-align: left; cursor: pointer; }.source-section button span { display: grid; gap: 3px; }.source-section strong, .source-section small { font-size: 14px; }.source-section small { color: var(--muted); }
.runtime-boundary { display: flex; gap: 9px; margin: 8px 16px 16px; padding: 11px; border: 1px solid var(--line); border-radius: 8px; background: #f7f9f9; }.runtime-boundary svg { flex: 0 0 auto; margin-top: 2px; }.runtime-boundary strong { font-size: 14px; }.runtime-boundary p { margin: 4px 0 0; color: #4a5c6a; font-size: 14px; line-height: 1.55; }
.run-history { padding: 9px; }.run-history > button { display: grid; width: 100%; grid-template-columns: 26px minmax(0, 1fr); gap: 7px; margin-bottom: 7px; border: 1px solid var(--soft-line); border-radius: 8px; padding: 10px; background: #fff; color: var(--ink); text-align: left; cursor: pointer; }.run-history > button.selected { border-color: var(--action); box-shadow: inset 0 0 0 1px var(--action); }.run-status-icon { display: grid; width: 24px; height: 24px; place-items: center; border-radius: 6px; background: #f1f4f4; }.run-history button > span:last-child { display: grid; gap: 3px; }.run-history strong, .run-history small { font-size: 14px; }.run-history small { color: var(--muted); line-height: 1.35; }
.editor-panel { display: grid; grid-template-rows: 43px minmax(0, 1fr) 118px; }.file-bar { display: flex; min-width: 0; align-items: center; justify-content: space-between; gap: 8px; border-bottom: 1px solid var(--soft-line); padding-right: 10px; }.file-bar > span { color: var(--muted); font-size: 14px; white-space: nowrap; }.file-tabs { display: flex; min-width: 0; height: 100%; overflow: auto; }.file-tabs button { display: inline-flex; min-width: 120px; align-items: center; justify-content: center; gap: 6px; border: 0; border-right: 1px solid var(--soft-line); border-bottom: 2px solid transparent; padding: 0 12px; background: #f7f9f9; color: var(--muted); font-size: 14px; cursor: pointer; }.file-tabs button.active { border-bottom-color: var(--action); background: #fff; color: var(--ink); }
.editor-host { min-width: 0; min-height: 0; }.stdin-panel { display: grid; min-height: 0; grid-template-rows: 35px 1fr; border-top: 1px solid var(--line); }.stdin-panel > span { display: flex; align-items: center; gap: 6px; padding: 0 12px; color: #253745; font-size: 14px; font-weight: 650; }.stdin-panel textarea { min-width: 0; resize: none; border: 0; border-top: 1px solid var(--soft-line); padding: 9px 12px; background: #fbfcfc; color: var(--ink); font: 14px/1.5 'Cascadia Code', Consolas, monospace; }
.result-summary { display: flex; min-height: 72px; flex: 0 0 auto; gap: 9px; padding: 12px; border-bottom: 1px solid var(--soft-line); }.result-icon { display: grid; width: 34px; height: 34px; flex: 0 0 34px; place-items: center; border-radius: 8px; background: #f1f4f4; color: var(--action); }.result-summary strong { font-size: 15px; }.result-summary p { margin: 4px 0 0; color: var(--muted); font-size: 14px; line-height: 1.45; }.status-runtime_error .result-icon, .status-timeout .result-icon, .status-stopped .result-icon { background: #fff2f0; color: #873d35; }
.result-tabs { overflow: auto; align-items: stretch; }.result-tabs button { flex: 1 0 auto; padding: 0 7px; }
.capture-note { display: grid; gap: 7px; margin: 10px; padding: 9px; border: 1px solid var(--line); border-radius: 7px; background: #f7f9f9; color: #4a5c6a; font-size: 14px; line-height: 1.5; }.complete-output-button { display: inline-flex; width: fit-content; align-items: center; gap: 6px; border: 1px solid var(--line); border-radius: 7px; padding: 5px 8px; background: #fff; color: var(--action); font-size: 14px; cursor: pointer; }.complete-output-button:disabled { cursor: default; opacity: .55; }.capture-unavailable { color: #873d35; }.terminal-output { min-height: 180px; margin: 0; padding: 13px; overflow: auto; background: #10181d; color: #eef3f3; font: 14px/1.6 'Cascadia Code', Consolas, monospace; white-space: pre-wrap; word-break: break-word; }.error-output { color: #ffd6d1; }
.panel-empty { display: grid; min-height: 210px; place-content: center; justify-items: center; gap: 7px; padding: 20px; color: var(--muted); text-align: center; }.panel-empty strong { color: var(--ink); font-size: 15px; }.panel-empty span { max-width: 29ch; font-size: 14px; line-height: 1.55; }
.plot-viewer { padding: 10px; }.plot-tabs { display: flex; gap: 6px; margin-bottom: 8px; overflow: auto; }.plot-tabs button { min-height: 32px; border: 1px solid var(--line); border-radius: 7px; padding: 0 8px; background: #fff; color: var(--muted); font-size: 14px; cursor: pointer; }.plot-tabs button.active { border-color: var(--action); color: var(--ink); }.plot-viewer img { display: block; width: 100%; height: auto; border: 1px solid var(--soft-line); background: #fff; object-fit: contain; }.plot-error { color: #873d35; font-size: 14px; }
.check-results { padding: 14px; border-top: 1px solid var(--soft-line); }.check-results ul { display: grid; gap: 7px; margin: 0; padding: 0; list-style: none; }.check-results li { display: grid; grid-template-columns: 20px minmax(0, 1fr); gap: 6px; color: var(--muted); }.check-results li.passed { color: var(--ink); }.check-results li span { display: grid; gap: 2px; }.check-results strong, .check-results small { font-size: 14px; }.check-results small { color: var(--muted); line-height: 1.45; }
.completion-bar { display: grid; flex: 0 0 auto; grid-template-columns: minmax(0, 1fr) auto; align-items: center; gap: 10px; padding: 11px; border-top: 1px solid var(--line); background: #f7f9f9; }.completion-bar > div { display: grid; gap: 3px; }.completion-bar strong { font-size: 14px; }.completion-bar span { display: -webkit-box; overflow: hidden; color: var(--muted); font-size: 14px; line-height: 1.4; -webkit-box-orient: vertical; -webkit-line-clamp: 2; }
.spin { animation: spin .8s linear infinite; }@keyframes spin { to { transform: rotate(360deg); } }
@media (max-width: 1240px) { .sandbox-grid { min-width: 1020px; }.secondary-button { padding: 0 8px; }.header-actions .secondary-button strong { display: none; }.sandbox-title h1 { font-size: 18px; } }
</style>
