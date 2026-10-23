<script setup>
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useCourseContextStore } from '../stores/courseContext'
import {
  ArrowRight, BookOpen, Bot, CalendarCheck, CheckCircle2, ChevronDown, ChevronUp, Circle, Clock3,
  ClipboardCheck, Code2, Copy, FilePlus2, FileText, FlaskConical, ListChecks, LoaderCircle,
  MapPin, MessageSquareText, Pause, Play, Plus, RefreshCw, Save, ShieldCheck, Trash2, X,
} from '@lucide/vue'
import {
  confirmM5Plan, createM5Plan, getM5PlanningTargets,
  getM5TodayWork, getM5WorkspaceOverview, listM5Paths, listM5Plans, reviseM5Plan,
  transitionM5Path, cancelM5Task, createM5TutorContext, getM5Task, preflightM5TutorRequest,
  createM5ResourceVersion, getM5Resource, getM5WorkspaceTaskTimeline, runM5WorkspaceAction,
  retryM5TaskStep, executeM5WorkspaceLocalDemoTask,
  decideM5Misconception, getM5WorkspaceExercise, submitM5AssessmentAttempt,
  getProfileUpdateReminder, dismissProfileUpdateReminder,
} from '../api'
import { recordBrowserLearningEvent, syncPendingLearningEvents } from '../services/learningEvents'

const router = useRouter()
const courseContext = useCourseContextStore()

const targets = ref({ courses: [], artifacts: [] })
const plans = ref([])
const paths = ref([])
const today = ref([])
const selectedPlanId = ref('')
const selectedPathId = ref('')
const loading = ref(false)
const saving = ref(false)
const error = ref('')
const notice = ref('')
const editing = ref(false)
const title = ref('')
const goal = ref('')
const deadline = ref('')
const courseId = ref('')
const nodes = ref([])
const workspace = ref(null)
const mobilePanel = ref('learning')
const selectedObjectId = ref('')
const copiedObjectId = ref('')
const selectedObjectText = ref('')
const contextQuestion = ref('')
const contextBusy = ref(false)
const contextNotice = ref('')
const contextError = ref('')
const actionBusy = ref('')
const actionResult = ref(null)
const taskStatusBusy = ref(false)
const taskTimeline = ref(null)
const artifactDetail = ref(null)
const artifactDraft = ref('')
const artifactBusy = ref(false)
const artifactError = ref('')
const artifactSourceObject = ref(null)
const restoredReadingPosition = ref(null)
const exerciseAnswer = ref('')
const exerciseBusy = ref(false)
const exerciseFeedback = ref(null)
const misconceptionBusy = ref(false)
const misconceptionCategory = ref('strategy_error')
const misconceptionNote = ref('')
const profileReminder = ref(null)
const profileReminderBusy = ref(false)

const selectedPlan = computed(() => plans.value.find(item => item.id === selectedPlanId.value) || null)
const selectedPath = computed(() => paths.value.find(item => item.id === selectedPathId.value) || null)
const selectedCourse = computed(() => targets.value.courses.find(item => item.id === courseId.value) || null)
const workspaceCourse = computed(() => workspace.value?.course || selectedCourse.value || null)
const workspaceCourses = computed(() => {
  const courses = workspace.value?.courses || []
  return courses.length ? courses : (workspaceCourse.value ? [workspaceCourse.value] : [])
})
const workspaceTasks = computed(() => workspace.value?.today_tasks || today.value)
const workspaceProfile = computed(() => workspace.value?.profile || null)
const todayRequiredTasks = computed(() => workspaceTasks.value.filter(item => item.required !== false))
const todayRemainingTasks = computed(() => todayRequiredTasks.value.filter(item => item.status !== 'completed'))
const todayFocusTask = computed(() => todayRemainingTasks.value[0] || workspaceTasks.value[0] || null)
const hasLearningPath = computed(() => Boolean(workspace.value?.current_path))
const todayExamUnlocked = computed(() => hasLearningPath.value && todayRemainingTasks.value.length === 0)
const learningProgress = computed(() => {
  const nodes = workspacePathNodes.value
  if (!nodes.length) return 0
  return Math.round((nodes.filter(item => item.status === 'completed').length / nodes.length) * 100)
})
const workspaceChapters = computed(() => {
  const chapters = workspace.value?.chapters || []
  const children = new Map()
  chapters.forEach(item => {
    const parent = item.parent_id || ''
    children.set(parent, [...(children.get(parent) || []), item])
  })
  const output = []
  const visit = (parentId, depth) => {
    ;(children.get(parentId) || [])
      .sort((left, right) => left.position - right.position || left.title.localeCompare(right.title))
      .forEach(item => {
        output.push({ ...item, depth })
        visit(item.id, depth + 1)
      })
  }
  visit('', 0)
  return output.length === chapters.length ? output : chapters.map(item => ({ ...item, depth: 0 }))
})
const workspacePathNodes = computed(() => workspace.value?.current_path?.nodes || selectedPath.value?.nodes || [])
const completedTasks = computed(() => workspacePathNodes.value.filter(item => item.status === 'completed'))
const chapterNodeByTarget = computed(() => new Map(
  workspacePathNodes.value
    .filter(item => item.node_type === 'chapter' && item.target_object_id)
    .map(item => [item.target_object_id, item]),
))
const currentChapterId = computed(() => {
  const currentTask = workspaceTasks.value.find(item => item.node_type === 'chapter' || chapterNodeByTarget.value.has(item.node_id))
  if (currentTask?.target_object_id) return currentTask.target_object_id
  const chapterNodes = workspacePathNodes.value.filter(item => item.node_type === 'chapter' && item.target_object_id)
  const currentNode = chapterNodes.find(item => item.status !== 'completed') || chapterNodes.at(-1)
  return currentNode?.target_object_id || workspaceChapters.value[0]?.id || ''
})
const sourceCount = computed(() => new Set(
  workspaceChapters.value.map(item => item.source_document_id).filter(Boolean),
).size)
const workspaceObjects = computed(() => workspace.value?.learning_objects || [])
const recentArtifacts = computed(() => workspace.value?.recent_artifacts || [])
const currentArtifactVersion = computed(() => {
  const detail = artifactDetail.value
  if (!detail) return null
  return detail.versions?.find(item => item.id === detail.current_version_id) || detail.versions?.at(-1) || null
})
const objectTypes = [
  { key: 'document', label: '文档', icon: FileText },
  { key: 'code', label: '代码', icon: Code2 },
  { key: 'experiment', label: '实验', icon: FlaskConical },
  { key: 'exercise', label: '练习', icon: ClipboardCheck },
]
const workspaceActions = [
  { key: 'explain', label: '解释', icon: BookOpen },
  { key: 'example', label: '举例', icon: MessageSquareText },
  { key: 'quiz', label: '出题', icon: ClipboardCheck },
  { key: 'experiment', label: '生成实验', icon: FlaskConical },
  { key: 'add_note', label: '加入笔记', icon: FilePlus2 },
  { key: 'add_path', label: '加入路径', icon: ListChecks },
]

const availableObjectTypes = computed(() => objectTypes.filter(type => workspaceObjects.value.some(item => item.object_type === type.key)))
const activeObject = computed(() => workspaceObjects.value.find(item => item.id === selectedObjectId.value)
  || (artifactSourceObject.value?.id === selectedObjectId.value ? artifactSourceObject.value : null)
  || workspaceObjects.value[0]
  || null)
const activeObjectType = computed(() => activeObject.value?.object_type || '')
const readingPosition = computed(() => {
  const restoredPosition = restoredReadingPosition.value?.position
  if (
    restoredReadingPosition.value?.object_id === activeObject.value?.id
    && restoredPosition
    && typeof restoredPosition === 'object'
  ) {
    return restoredPosition
  }
  const render = activeObject.value?.render || {}
  if (render.kind === 'document') return { kind: 'section', label: render.section || activeObject.value?.title || '' }
  if (render.kind === 'code') return { kind: 'line', label: '代码开头', line_number: 1 }
  if (render.kind === 'exercise') return { kind: 'question', label: questionTypeLabel(render.question_type) }
  return { kind: 'object', label: render.template || activeObject.value?.title || '' }
})
const availableObjects = computed(() => {
  const chapters = (selectedCourse.value?.chapters || []).map(item => ({ ...item, type: 'chapter' }))
  const artifacts = targets.value.artifacts
    .filter(item => !courseId.value || !item.course_id || item.course_id === courseId.value)
    .map(item => ({ id: item.id, title: item.title, type: 'artifact' }))
  return [...chapters, ...artifacts]
})

function message(err) {
  const detail = err?.response?.data?.detail || err?.detail
  return detail?.message || (typeof detail === 'string' ? detail : '') || err?.message || '请求失败'
}

function taskStatusLabel(status) {
  return ({
    pending: '待开始', queued: '等待处理', in_progress: '进行中', running: '正在处理',
    blocked: '暂不可用', completed: '已完成', failed: '需要处理', cancelled: '已取消', due: '到期复习',
  })[status] || status || '待开始'
}

function nodeTypeLabel(type) {
  return ({ chapter: '章节学习', interactive: '交互实验', assessment: '课程练习', code: '代码实践', workspace_action: '补充任务' })[type] || '学习任务'
}

function objectStatusLabel(status) {
  return ({
    ready: '可学习', approved: '已审核', published: '已发布', draft: '草稿',
    derived_preview: '教学预览', frozen_initial_demo_artifact: '冻结演示版本',
    configured: '待运行', evaluated: '已运行', passed: '已通过', needs_retry: '需重试',
  })[status] || '状态可用'
}

function evidenceStatusLabel(status) {
  return ({
    passed: '已通过', failed: '未通过', manual_required: '待复核', pending: '处理中',
    not_recorded: '质量检查未记录', not_applicable: '不适用',
  })[status] || '状态未知'
}

function evidenceBlockerLabel(blocker) {
  return ({
    source_evidence_missing: '未记录可核查来源',
    source_reference_invalid: '来源引用无法验证',
    quality_source_reference_invalid: '质量记录引用无法验证',
    source_license_missing: '来源许可证信息缺失',
    object_render_error: '当前对象存在渲染错误',
    runnability_not_verified: '尚未记录可运行性检查',
    structure_check_failed: '结构检查未通过',
    structure_check_manual_required: '结构检查需要复核',
    source_check_failed: '来源检查未通过',
    source_check_manual_required: '来源检查需要复核',
    topic_check_failed: '主题检查未通过',
    topic_check_manual_required: '主题检查需要复核',
    runnable_check_failed: '可运行性检查未通过',
    runnable_check_manual_required: '可运行性检查需要复核',
  })[blocker] || '存在尚未满足的证据条件'
}

function artifactStatusLabel(status) {
  return ({ draft: '草稿', reviewing: '审核中', approved: '已批准', published: '已发布', archived: '已归档', withdrawn: '已下架' })[status] || status || '状态未知'
}

function questionTypeLabel(type) {
  return ({ single_choice: '单选题', multiple_choice: '多选题', true_false: '判断题', fill_blank: '填空题', short_answer: '简答题', code: '代码题', open_task: '开放任务' })[type] || '练习题'
}

function bloomLabel(level) {
  return ({ remember: '记忆', understand: '理解', apply: '应用', analyze: '分析', evaluate: '评价', create: '创造' })[level] || '理解'
}

function chapterSourceLabel(chapter) {
  const format = chapter.source?.file_format?.toUpperCase()
  return format ? `课程教材 · ${format}` : '课程教材'
}

function todayResourceStatusLabel(status) {
  return ({
    existing: '已有资源', ready: '可生成', queued: '生成中', running: '生成中',
    succeeded: '已归档', failed: '需重试', completed: '已完成',
  })[status] || '待准备'
}

function todayPrimaryActionLabel() {
  if (!workspaceCourse.value) return '选择预置课程'
  if (!hasLearningPath.value) return '查看学习路径'
  if (todayFocusTask.value) return '进入今日任务'
  return '查看学习路径'
}

async function openTodayTask(item) {
  if (!item) return
  if (item.task_kind === 'review' && item.continue_route) {
    await router.push(item.continue_route)
    return
  }
  await router.push({
    path: '/workspace/path',
    query: {
      course_id: item.course_id || workspaceCourse.value?.id || undefined,
      node_id: item.node_id || item.id || undefined,
    },
  })
}

async function openTodayPrimaryAction() {
  if (!workspaceCourse.value) {
    await router.push('/knowledge')
    return
  }
  if (!hasLearningPath.value) {
    await router.push('/workspace/path')
    return
  }
  if (todayFocusTask.value) {
    await openTodayTask(todayFocusTask.value)
    return
  }
  await router.push('/workspace/path')
}

async function openProfileReminder() {
  await router.push({
    path: '/profile/update',
    query: { course_id: workspaceCourse.value?.id || undefined, update: '1' },
  })
}

async function dismissProfileReminder() {
  if (profileReminderBusy.value) return
  profileReminderBusy.value = true
  try {
    profileReminder.value = await dismissProfileUpdateReminder(workspaceCourse.value?.id || courseId.value || null)
  } catch (err) {
    error.value = message(err)
  } finally {
    profileReminderBusy.value = false
  }
}

async function openIntelligentExam() {
  if (!todayExamUnlocked.value) return
  await router.push('/workspace/assessment/exams')
}

async function replaceWorkspaceQuery(patch = {}, remove = []) {
  const url = new URL(window.location.href)
  Object.entries(patch).forEach(([key, value]) => {
    if (value === undefined || value === null || value === '') url.searchParams.delete(key)
    else url.searchParams.set(key, String(value))
  })
  remove.forEach(key => url.searchParams.delete(key))
  window.history.replaceState(window.history.state, '', `${url.pathname}${url.search}${url.hash}`)
}

function currentQueryValue(key) {
  return new URLSearchParams(window.location.search).get(key) || ''
}

function workspacePositionKey(object) {
  const version = object?.version?.content_hash?.slice(0, 12) || object?.version?.label || 'current'
  const profile = workspaceProfile.value?.profile_version || workspaceProfile.value?.updated_at || 'profile'
  const position = readingPosition.value
  const anchor = position.line_number ?? position.timestamp_seconds ?? position.char_offset ?? position.label ?? position.kind
  const raw = `workspace-position-${object?.id || 'unknown'}-${version}-${profile}-${anchor}`
  return raw.replace(/[^A-Za-z0-9_.:-]/g, '-').slice(0, 128)
}

async function persistWorkspacePosition() {
  if (!activeObject.value || !workspaceCourse.value) return
  try {
    await createM5TutorContext({
      schema_version: 'm5.tutor-context.v1',
      idempotency_key: workspacePositionKey(activeObject.value),
      course_id: workspaceCourse.value.id,
      context_mode: 'current_resource',
      primary_object_type: 'workspace_object',
      primary_object_id: activeObject.value.id,
      selected_source_ref_ids: activeObject.value.context?.source_ref_ids || [],
      selected_text: '',
      reading_position: readingPosition.value,
      teaching_style: 'progressive',
      explanation_depth: 'standard',
      guidance_mode: 'socratic',
    })
  } catch (err) {
    contextError.value = message(err)
  }
}

async function commitObjectSelection() {
  restoredReadingPosition.value = null
  await nextTick()
  const chapterId = activeObject.value?.context?.chapter_id || activeObject.value?.metadata?.chapter_id || ''
  await replaceWorkspaceQuery({
    course_id: workspaceCourse.value?.id || '',
    chapter_id: chapterId,
    object_id: selectedObjectId.value,
  }, ['source_chapter_id'])
  await persistWorkspacePosition()
}

async function selectObjectType(type) {
  const item = workspaceObjects.value.find(candidate => candidate.object_type === type)
  if (!item) return
  selectedObjectId.value = item.id
  await commitObjectSelection()
}

watch(activeObject, () => {
  selectedObjectText.value = ''
  contextNotice.value = ''
  contextError.value = ''
  exerciseAnswer.value = ''
  exerciseFeedback.value = null
  exerciseBusy.value = false
  misconceptionBusy.value = false
  misconceptionCategory.value = 'strategy_error'
  misconceptionNote.value = ''
  restoreWorkspaceExerciseDecision()
})

function captureObjectSelection(event) {
  const selection = window.getSelection()
  const text = selection?.toString().trim() || ''
  const container = event.currentTarget
  if (!text || !container?.contains(selection?.anchorNode) || !container?.contains(selection?.focusNode)) return
  selectedObjectText.value = text.slice(0, 1200)
  contextNotice.value = '已将选中文本加入当前提问上下文。'
}

async function createCurrentWorkspaceContext(prefix = 'workspace') {
  const sourceRefIds = activeObject.value?.context?.source_ref_ids || []
  return createM5TutorContext({
      schema_version: 'm5.tutor-context.v1',
      idempotency_key: `${prefix}-${Date.now()}-${Math.random().toString(16).slice(2)}`,
      course_id: workspaceCourse.value.id,
      context_mode: 'current_resource',
      primary_object_type: 'workspace_object',
      primary_object_id: activeObject.value.id,
      selected_source_ref_ids: sourceRefIds,
      selected_text: selectedObjectText.value,
      reading_position: readingPosition.value,
      teaching_style: 'progressive',
      explanation_depth: 'standard',
      guidance_mode: 'socratic',
  })
}

async function askWithCurrentContext() {
  const question = contextQuestion.value.trim()
  if (!question || !activeObject.value || !workspaceCourse.value) return
  contextBusy.value = true
  contextError.value = ''
  contextNotice.value = ''
  try {
    const context = await createCurrentWorkspaceContext('workspace-question')
    const preflight = await preflightM5TutorRequest(context.id, { question, intent: 'explain', comparison_context_ids: [] })
    contextNotice.value = preflight.ready ? '上下文已校验，正在进入对话。' : '上下文已校验，文本模型将按当前环境降级。'
    await router.push({ path: '/learn', query: { context_session_id: context.id, prompt: question } })
  } catch (err) {
    contextError.value = message(err)
  } finally {
    contextBusy.value = false
  }
}

async function loadActionTimeline(taskId) {
  if (!taskId || !workspaceCourse.value?.id) return
  taskTimeline.value = await getM5WorkspaceTaskTimeline(taskId, workspaceCourse.value.id)
}

async function restoreLatestActionTask(workspaceData) {
  const recentTasks = workspaceData?.restore?.recent_tasks || workspaceData?.running_tasks || []
  const requestedTaskId = currentQueryValue('task_id')
  const task = recentTasks.find(item => item.id === requestedTaskId)
    || workspaceData?.restore?.task
    || workspaceData?.running_tasks?.[0]
  if (!task) {
    if (requestedTaskId) await replaceWorkspaceQuery({}, ['task_id'])
    return
  }
  const detail = await getM5Task(task.id)
  actionResult.value = { task: { ...task, ...detail, task_id: task.id } }
  await loadActionTimeline(task.id)
  await replaceWorkspaceQuery({ task_id: task.id })
}

async function openWorkspaceArtifact(artifactId, syncRoute = true) {
  if (!artifactId || artifactBusy.value) return
  artifactBusy.value = true
  artifactError.value = ''
  try {
    artifactDetail.value = await getM5Resource(artifactId)
    artifactDraft.value = currentArtifactVersion.value?.content || ''
    if (syncRoute) await replaceWorkspaceQuery({ artifact_id: artifactId })
  } catch (err) {
    artifactError.value = message(err)
  } finally {
    artifactBusy.value = false
  }
}

async function closeWorkspaceArtifact(syncRoute = true, nextQuery = {}) {
  artifactDetail.value = null
  artifactDraft.value = ''
  artifactError.value = ''
  if (syncRoute && currentQueryValue('artifact_id')) {
    await replaceWorkspaceQuery(nextQuery, ['artifact_id'])
  }
}

async function saveWorkspaceArtifactVersion() {
  const detail = artifactDetail.value
  const current = currentArtifactVersion.value
  if (!detail || !current || !artifactDraft.value.trim() || artifactBusy.value) return
  artifactBusy.value = true
  artifactError.value = ''
  try {
    artifactDetail.value = await createM5ResourceVersion(detail.id, {
      expected_lock_version: detail.lock_version,
      source_version_id: current.id,
      content: artifactDraft.value,
      content_format: current.content_format || 'markdown',
    })
    artifactDraft.value = currentArtifactVersion.value?.content || ''
    contextNotice.value = `已创建 ${artifactDetail.value.title} 的 v${currentArtifactVersion.value?.version_number} 草稿版本。`
    await refresh(true)
  } catch (err) {
    artifactError.value = message(err)
  } finally {
    artifactBusy.value = false
  }
}

async function returnToArtifactSource() {
  const current = currentArtifactVersion.value
  const shelfItem = recentArtifacts.value.find(item => item.id === artifactDetail.value?.id)
  const chapterId = current?.metadata?.chapter_id || shelfItem?.source?.chapter_id
  const objectId = chapterId ? `workspace-document:${chapterId}` : ''
  const sourceObject = shelfItem?.source?.learning_object
  if (!objectId || sourceObject?.id !== objectId) {
    artifactError.value = '该产物没有可在当前课程中定位的章节来源。'
    return
  }
  artifactSourceObject.value = sourceObject
  selectedObjectId.value = objectId
  mobilePanel.value = 'learning'
  contextNotice.value = `已回到产物来源：${shelfItem?.source?.label || '课程章节'}。`
  await closeWorkspaceArtifact(true, { source_chapter_id: chapterId, object_id: objectId })
  await persistWorkspacePosition()
  await nextTick()
  document.querySelector('.main-panel')?.scrollIntoView({ block: 'start', behavior: 'smooth' })
}

function restoreArtifactSourceFromRoute() {
  const chapterId = currentQueryValue('source_chapter_id')
  if (!chapterId) return
  const shelfItem = recentArtifacts.value.find(item => item.source?.chapter_id === chapterId)
  const sourceObject = shelfItem?.source?.learning_object
  if (!sourceObject) return
  artifactSourceObject.value = sourceObject
  selectedObjectId.value = sourceObject.id
  mobilePanel.value = 'learning'
}

async function runWorkspaceAction(action) {
  if (!activeObject.value || !workspaceCourse.value || actionBusy.value) return
  actionBusy.value = action
  contextError.value = ''
  contextNotice.value = ''
  actionResult.value = null
  try {
    const context = await createCurrentWorkspaceContext(`workspace-${action}`)
    const result = await runM5WorkspaceAction({
      schema_version: 'r2.workspace-action.v1',
      context_session_id: context.id,
      action,
      idempotency_key: `action-${action}-${Date.now()}-${Math.random().toString(16).slice(2)}`,
      instruction: contextQuestion.value.trim(),
    })
    if (result.execution_mode === 'chat') {
      contextNotice.value = action === 'example' ? '已锁定“举例”能力，正在进入对话。' : '已锁定“解释”能力，正在进入对话。'
      await router.push({
        path: result.chat.route,
        query: { context_session_id: result.context_session_id, prompt: result.chat.prompt },
      })
      return
    }
    actionResult.value = result
    if (result.task) {
      contextNotice.value = `已创建${action === 'quiz' ? '出题' : '实验'}任务，状态为 ${result.task.status}。`
      await loadActionTimeline(result.task.task_id)
      await replaceWorkspaceQuery({ task_id: result.task.task_id, object_id: activeObject.value.id })
    } else if (result.note) {
      contextNotice.value = result.note.created ? '已加入笔记。' : '该笔记已存在。'
    } else if (result.path) {
      contextNotice.value = result.path.created ? '已加入当前学习路径。' : '该路径任务已存在。'
      await refresh(true)
    }
  } catch (err) {
    contextError.value = message(err)
  } finally {
    actionBusy.value = ''
  }
}

async function refreshActionTask() {
  const taskId = actionResult.value?.task?.task_id
  if (!taskId || taskStatusBusy.value) return
  taskStatusBusy.value = true
  contextError.value = ''
  try {
    const task = await getM5Task(taskId)
    actionResult.value = {
      ...actionResult.value,
      task: { ...actionResult.value.task, ...task, task_id: task.task_id || taskId },
    }
    await loadActionTimeline(taskId)
    await replaceWorkspaceQuery({ task_id: taskId })
    contextNotice.value = `任务状态已刷新：${task.status}。`
  } catch (err) {
    contextError.value = message(err)
  } finally {
    taskStatusBusy.value = false
  }
}

async function executeWorkspaceLocalDemoTask() {
  const taskId = actionResult.value?.task?.task_id
  if (!taskId || taskStatusBusy.value) return
  taskStatusBusy.value = true
  contextError.value = ''
  try {
    const result = await executeM5WorkspaceLocalDemoTask(taskId)
    const task = await getM5Task(taskId)
    actionResult.value = {
      ...actionResult.value,
      task: { ...actionResult.value.task, ...task, task_id: taskId },
    }
    await loadActionTimeline(taskId)
    await refresh(true)
    if (result.artifact_id) await openWorkspaceArtifact(result.artifact_id)
    contextNotice.value = result.created
      ? '离线演示任务已完成：首稿经过来源校验和局部返工后生成正式产物。'
      : '已恢复该离线演示任务的正式产物。'
  } catch (err) {
    contextError.value = message(err)
  } finally {
    taskStatusBusy.value = false
  }
}

async function cancelWorkspaceTask() {
  const taskId = actionResult.value?.task?.task_id
  if (!taskId || taskStatusBusy.value) return
  taskStatusBusy.value = true
  contextError.value = ''
  try {
    const task = await cancelM5Task(taskId)
    actionResult.value = {
      ...actionResult.value,
      task: { ...actionResult.value.task, ...task, task_id: taskId },
    }
    await loadActionTimeline(taskId)
    await refresh(true)
    contextNotice.value = '任务已取消，已有事件和进度仍然保留。'
  } catch (err) {
    contextError.value = message(err)
  } finally {
    taskStatusBusy.value = false
  }
}

async function retryWorkspaceTaskStep(sequence) {
  const taskId = actionResult.value?.task?.task_id
  if (!taskId || taskStatusBusy.value) return
  taskStatusBusy.value = true
  contextError.value = ''
  try {
    await retryM5TaskStep(taskId, sequence)
    const task = await getM5Task(taskId)
    actionResult.value = {
      ...actionResult.value,
      task: { ...actionResult.value.task, ...task, task_id: taskId },
    }
    await loadActionTimeline(taskId)
    await replaceWorkspaceQuery({ task_id: taskId })
    contextNotice.value = `已从第 ${sequence} 步继续处理，不会重做已完成阶段。`
  } catch (err) {
    contextError.value = message(err)
  } finally {
    taskStatusBusy.value = false
  }
}

function selectObjectForTask(item) {
  const expectedType = ({ chapter: 'document', interactive: 'experiment', assessment: 'exercise', code: 'code' })[item.node_type]
  const exact = workspaceObjects.value.find(candidate => candidate.id === item.target_object_id)
  const fallback = workspaceObjects.value.find(candidate => candidate.object_type === expectedType)
  selectedObjectId.value = (exact || fallback || activeObject.value)?.id || ''
}

async function copyActiveObject() {
  if (!activeObject.value) return
  const render = activeObject.value.render || {}
  const value = render.content || render.excerpt || render.prompt || activeObject.value.title
  try {
    await navigator.clipboard.writeText(value)
    copiedObjectId.value = activeObject.value.id
    window.setTimeout(() => { copiedObjectId.value = '' }, 1600)
  } catch {
    notice.value = '浏览器未允许复制，请手动选择内容。'
  }
}

async function continueTask(item) {
  if (item.task_kind === 'review' && item.continue_route) {
    await router.push(item.continue_route)
    return
  }
  const path = paths.value.find(candidate => candidate.id === item.path_id) || selectedPath.value
  if (path) {
    selectedPathId.value = path.id
    const plan = plans.value.find(candidate => candidate.confirmed_version_id === path.source_plan_version_id)
    if (plan) selectedPlanId.value = plan.id
  }
  editing.value = false
  mobilePanel.value = 'learning'
  selectObjectForTask(item)
  notice.value = `继续任务：${item.title}`
  await nextTick()
  await commitObjectSelection()
  document.getElementById(`workspace-node-${item.node_id}`)?.scrollIntoView({ block: 'center', behavior: 'smooth' })
}

async function submitWorkspaceExercise() {
  const object = activeObject.value
  const versionId = object?.render?.question_version_id
  if (!versionId || !exerciseAnswer.value || exerciseBusy.value) return
  exerciseBusy.value = true
  exerciseFeedback.value = null
  try {
    exerciseFeedback.value = await submitM5AssessmentAttempt({
      question_version_id: versionId,
      idempotency_key: `workspace-practice-${versionId}-${Date.now()}`,
      mode: 'practice',
      answer: { value: exerciseAnswer.value === 'true' },
    })
  } catch (err) {
    exerciseFeedback.value = { error: message(err) }
  } finally {
    exerciseBusy.value = false
  }
}

async function decideWorkspaceMisconception(decision) {
  const reviewId = exerciseFeedback.value?.misconception_review?.id
  if (!reviewId || misconceptionBusy.value) return
  misconceptionBusy.value = true
  try {
    const result = await decideM5Misconception(reviewId, {
      decision,
      category: decision === 'modify' ? misconceptionCategory.value : '',
      note: misconceptionNote.value,
    })
    exerciseFeedback.value = {
      ...exerciseFeedback.value,
      misconception_review: {
        ...exerciseFeedback.value.misconception_review,
        status: result.status,
        confirmed_category: result.confirmed_category,
        decision_note: result.decision_note,
      },
      misconception_projection: result,
      misconception_error: '',
    }
  } catch (err) {
    exerciseFeedback.value = { ...exerciseFeedback.value, misconception_error: message(err) }
  } finally {
    misconceptionBusy.value = false
  }
}

async function restoreWorkspaceExerciseDecision() {
  const versionId = activeObject.value?.render?.question_version_id
  if (!versionId) return
  try {
    const detail = await getM5WorkspaceExercise(versionId)
    if (detail.latest_attempt?.misconception_review) exerciseFeedback.value = detail.latest_attempt
  } catch (_) {
    // The main workspace load owns the visible load error state.
  }
}

async function openChapter(chapter) {
  selectedObjectId.value = `workspace-document:${chapter.id}`
  const node = chapterNodeByTarget.value.get(chapter.id)
  if (node) {
    await continueTask({ ...node, path_id: workspace.value?.current_path?.id || selectedPath.value?.id })
    return
  }
  notice.value = `当前章节：${chapter.title}`
  await commitObjectSelection()
}

async function selectMobilePanel(panel) {
  mobilePanel.value = panel
  await nextTick()
  document.querySelector('.app-content')?.scrollTo({ top: 0, left: 0, behavior: 'auto' })
}

function key(prefix = 'ui') {
  return `${prefix}-${Date.now()}-${Math.random().toString(16).slice(2)}`
}

function blankNode() {
  return { uiKey: key('node'), objectValue: '', title: '', min: 15, max: 30, extension: false, extensionReason: '' }
}

function latestSpec(plan) {
  return plan?.versions?.find(item => item.id === plan.current_version_id)?.content || null
}

function resetDraft() {
  selectedPlanId.value = ''
  title.value = ''
  goal.value = ''
  deadline.value = ''
  courseId.value = targets.value.courses[0]?.id || ''
  nodes.value = [blankNode()]
  editing.value = true
}

function loadPlanIntoEditor(plan) {
  const spec = latestSpec(plan)
  if (!spec) return
  title.value = plan.title
  goal.value = spec.goal
  deadline.value = spec.deadline ? spec.deadline.slice(0, 16) : ''
  courseId.value = plan.course_id || ''
  nodes.value = spec.nodes.map(item => ({
    uiKey: key('node'),
    objectValue: item.node_type === 'extension' ? '' : `${item.node_type}:${item.target_object_id}`,
    title: item.title,
    min: item.estimate_min_minutes,
    max: item.estimate_max_minutes,
    extension: item.node_type === 'extension',
    extensionReason: item.extension_reason || '',
  }))
  editing.value = true
}

function selectPlan(plan) {
  selectedPlanId.value = plan.id
  const matching = paths.value.find(item => item.source_plan_version_id === plan.confirmed_version_id)
  if (matching) selectedPathId.value = matching.id
  editing.value = false
}

function removeNode(index) {
  if (nodes.value.length > 1) nodes.value.splice(index, 1)
}

function moveNode(index, offset) {
  const target = index + offset
  if (target < 0 || target >= nodes.value.length) return
  const [item] = nodes.value.splice(index, 1)
  nodes.value.splice(target, 0, item)
}

function specPayload() {
  return {
    schema_version: 'm5.plan.v1',
    goal: goal.value.trim(),
    deadline: deadline.value ? new Date(deadline.value).toISOString() : null,
    assumptions: [],
    nodes: nodes.value.map((item, index) => {
      const [nodeType, targetId] = item.objectValue.split(':')
      const extension = item.extension
      return {
        node_key: `step-${index + 1}-${(targetId || 'extension').replace(/[^A-Za-z0-9_.:-]/g, '').slice(0, 48)}`,
        node_type: extension ? 'extension' : nodeType,
        target_object_id: extension ? null : targetId,
        title: item.title.trim(),
        prerequisites: index ? [`step-${index}-${(nodes.value[index - 1].objectValue.split(':')[1] || 'extension').replace(/[^A-Za-z0-9_.:-]/g, '').slice(0, 48)}`] : [],
        resource_status: extension ? 'external_dependency' : 'existing',
        estimate_min_minutes: Number(item.min),
        estimate_max_minutes: Number(item.max),
        extension_reason: extension ? item.extensionReason.trim() : '',
        required: true,
        risk_level: 'normal',
      }
    }),
  }
}

async function refresh(keepSelection = true) {
  loading.value = true
  error.value = ''
  try {
    const requestedCourseId = currentQueryValue('course_id') || courseContext.contextRef?.courseId || ''
    const [targetData, planData, pathData, todayData, workspaceData] = await Promise.all([
      getM5PlanningTargets(), listM5Plans(), listM5Paths(), getM5TodayWork(requestedCourseId),
      getM5WorkspaceOverview(requestedCourseId),
    ])
    targets.value = targetData
    plans.value = planData.items || []
    paths.value = pathData.items || []
    today.value = todayData.items || []
    workspace.value = workspaceData
    courseId.value = workspaceData.course?.id || requestedCourseId || courseId.value
    profileReminder.value = workspaceData.course?.id
      ? await getProfileUpdateReminder(workspaceData.course.id).catch(() => null)
      : null
    const requestedObjectId = currentQueryValue('object_id')
    const requestedChapterId = currentQueryValue('chapter_id')
    const requestedChapterObjectId = workspaceData.chapters?.some(item => item.id === requestedChapterId)
      ? `workspace-document:${requestedChapterId}`
      : ''
    const restoredContext = workspaceData.restore?.context
    const restoredObjectId = workspaceObjects.value.some(item => item.id === requestedObjectId)
      ? requestedObjectId
      : workspaceObjects.value.some(item => item.id === requestedChapterObjectId)
        ? requestedChapterObjectId
      : workspaceObjects.value.some(item => item.id === restoredContext?.object_id)
        ? restoredContext.object_id
        : ''
    if (restoredObjectId) {
      selectedObjectId.value = restoredObjectId
      restoredReadingPosition.value = restoredContext?.object_id === restoredObjectId
        ? { object_id: restoredObjectId, position: restoredContext.reading_position || {} }
        : null
    } else if (!workspaceObjects.value.some(item => item.id === selectedObjectId.value)) {
      const nextTask = workspaceData.today_tasks?.[0]
      if (nextTask) selectObjectForTask(nextTask)
      if (!selectedObjectId.value) selectedObjectId.value = workspaceObjects.value[0]?.id || ''
    }
    if (!keepSelection || !plans.value.some(item => item.id === selectedPlanId.value)) {
      selectedPlanId.value = plans.value[0]?.id || ''
    }
    if (!paths.value.some(item => item.id === selectedPathId.value)) {
      selectedPathId.value = paths.value.find(item => item.status === 'active')?.id || paths.value[0]?.id || ''
    }
    if (!editing.value && !selectedPlanId.value && !plans.value.length) resetDraft()
    if (!keepSelection) {
      await nextTick()
      await restoreLatestActionTask(workspaceData)
    }
    if (selectedObjectId.value) {
      const remove = requestedObjectId && requestedObjectId !== selectedObjectId.value ? ['source_chapter_id'] : []
      const selectedChapterId = activeObject.value?.context?.chapter_id || requestedChapterId || ''
      await replaceWorkspaceQuery({
        course_id: workspaceData.course?.id || requestedCourseId,
        chapter_id: selectedChapterId,
        object_id: selectedObjectId.value,
      }, remove)
    }
  } catch (err) {
    error.value = message(err)
  } finally {
    loading.value = false
  }
}

async function saveDraft() {
  saving.value = true
  error.value = ''
  notice.value = ''
  try {
    const spec = specPayload()
    let response
    if (selectedPlan.value) {
      response = await reviseM5Plan(selectedPlan.value.id, {
        expected_lock_version: selectedPlan.value.lock_version,
        spec,
      })
      notice.value = '新版本已保存，确认前不会替换当前路径。'
      selectedPlanId.value = response.plan.id
    } else {
      response = await createM5Plan({
        course_id: courseId.value || null,
        title: title.value.trim(),
        idempotency_key: key('plan'),
        spec,
      })
      selectedPlanId.value = response.id
      notice.value = '草稿已保存，尚未创建正式学习路径。'
    }
    editing.value = false
    await refresh(true)
  } catch (err) {
    error.value = message(err)
  } finally {
    saving.value = false
  }
}

async function confirmPlan() {
  if (!selectedPlan.value || !window.confirm('确认后将创建正式学习路径，继续吗？')) return
  saving.value = true
  error.value = ''
  try {
    const response = await confirmM5Plan(selectedPlan.value.id, selectedPlan.value.lock_version)
    selectedPathId.value = response.path.id
    notice.value = '计划已确认，正式路径已生效。'
    await refresh(true)
  } catch (err) {
    error.value = message(err)
  } finally {
    saving.value = false
  }
}

async function transitionPath(targetStatus) {
  if (!selectedPath.value) return
  saving.value = true
  error.value = ''
  try {
    await transitionM5Path(selectedPath.value.id, targetStatus, selectedPath.value.lock_version)
    notice.value = targetStatus === 'paused' ? '路径已暂停。' : '路径已恢复。'
    await refresh(true)
  } catch (err) {
    error.value = message(err)
  } finally {
    saving.value = false
  }
}

async function recordNodeActivity(node) {
  saving.value = true
  error.value = ''
  try {
    const result = await recordBrowserLearningEvent({
      schema_version: 'm5.learning-event.v1', idempotency_key: key('event'), event_type: 'resource_opened',
      context: selectedPath.value?.course_id
        ? { courseId: selectedPath.value.course_id, taskId: node.id }
        : null,
      course_id: selectedPath.value?.course_id || null, object_type: node.node_type,
      object_id: node.target_object_id || node.id, occurred_at: new Date().toISOString(), payload: {},
    })
    notice.value = result.status === 'queued'
      ? '学习活动已暂存，联网后同步；它不会改变掌握度。'
      : '学习活动已记录，不影响掌握度。'
    if (result.status === 'synced') await refresh(true)
  } catch (err) {
    error.value = message(err)
  } finally {
    saving.value = false
  }
}

async function replayPendingLearningEvents() {
  const result = await syncPendingLearningEvents()
  if (result.synced.length) {
    notice.value = `已同步 ${result.synced.length} 条离线学习活动。`
    await refresh(true)
  }
  if (result.rejected.length) {
    error.value = `${result.rejected.length} 条暂存活动未通过服务端校验，请重新执行对应操作。`
  }
}

onMounted(async () => {
  window.addEventListener('online', replayPendingLearningEvents)
  await refresh(false)
  restoreArtifactSourceFromRoute()
  const artifactId = currentQueryValue('artifact_id')
  if (artifactId) {
    await openWorkspaceArtifact(artifactId, false)
  }
  await replayPendingLearningEvents()
  await nextTick()
  requestAnimationFrame(() => document.querySelector('.app-content')?.scrollTo({ top: 0, left: 0 }))
})

onUnmounted(() => window.removeEventListener('online', replayPendingLearningEvents))
</script>

<template>
  <section class="workspace-page">
    <header class="today-learning-heading">
      <div>
        <p>学习空间</p>
        <h1>今日学习</h1>
        <span>{{ workspaceCourse?.title || '从预置课程开始你的学习闭环' }}</span>
      </div>
      <div v-if="workspaceCourse" class="today-progress" aria-label="课程学习进度">
        <small>课程进度</small>
        <strong>{{ learningProgress }}%</strong>
      </div>
    </header>

    <div v-if="loading" class="today-state" role="status"><LoaderCircle :size="17" class="spin" />正在读取今日学习安排</div>
    <div v-if="error" class="banner error"><X :size="15" />{{ error }}</div>
    <div v-if="notice" class="banner notice"><CheckCircle2 :size="15" />{{ notice }}</div>

    <section v-if="!loading && !workspaceCourse" class="today-empty" data-testid="today-learning-empty">
      <BookOpen :size="22" />
      <div><h2>还没有可用的学习课程</h2><p>课程内容由系统预置，你不需要先上传教材。</p></div>
      <button class="today-primary-action" type="button" @click="openTodayPrimaryAction"><BookOpen :size="15" />选择预置课程</button>
    </section>

    <template v-else-if="workspaceCourse">
      <div class="today-course-context">
        <div><span>{{ workspaceCourses.length > 1 ? '正在学习的课程' : '当前课程' }}</span>
          <div v-if="workspaceCourses.length > 1" class="today-course-list" data-testid="today-learning-courses">
            <strong v-for="course in workspaceCourses" :key="course.id">{{ course.title }}<small>{{ course.completed_nodes || 0 }}/{{ course.total_nodes || 0 }} 个路径节点完成</small></strong>
          </div>
          <strong v-else>{{ workspaceCourse.title }}</strong>
          <small v-if="workspaceCourses.length <= 1">{{ workspaceCourse.version || '当前版本' }} · {{ workspaceChapters.length }} 个章节 · {{ sourceCount }} 份教材来源</small>
          <small v-else>今日清单汇总所有 active 学习路径课程，任务仍按课程和路径分别进入。</small>
        </div>
        <router-link to="/workspace/path"><MapPin :size="15" />查看总路径</router-link>
      </div>

      <div class="today-learning-layout">
        <main class="today-learning-main">
          <section class="today-focus" data-testid="today-learning-focus">
            <div class="today-focus__eyebrow"><span>现在做什么</span><b>{{ todayFocusTask ? '今日必做' : '已完成' }}</b></div>
            <h2>{{ todayFocusTask?.knowledge_point_title || todayFocusTask?.title || '今日任务已完成' }}</h2>
            <p>{{ todayFocusTask?.recommendation_reason || '今天的必做学习任务已经完成，可以进入智能组卷检验本轮学习结果。' }}</p>
            <div class="today-focus__facts">
              <span><Clock3 :size="15" />{{ todayFocusTask ? `预计 ${todayFocusTask.estimate_minutes[0]}-${todayFocusTask.estimate_minutes[1]} 分钟` : '按你的节奏复习' }}</span>
              <span><CheckCircle2 :size="15" />{{ todayFocusTask?.completion_criteria || '完成今日必做任务并留下有效学习证据' }}</span>
            </div>
            <button class="today-primary-action" type="button" :disabled="loading" @click="openTodayPrimaryAction">
              <ArrowRight :size="16" />{{ todayPrimaryActionLabel() }}
            </button>
          </section>

          <section class="today-task-section" data-testid="today-task-list">
            <header class="today-section-heading"><div><p>今日清单</p><h2>完成这些，才能进入下一步</h2></div><strong>{{ todayRequiredTasks.length + (profileReminder?.due ? 1 : 0) }} 项</strong></header>
            <div v-if="todayRequiredTasks.length || profileReminder?.due" class="today-task-list">
              <article v-if="profileReminder?.due" class="today-profile-reminder" data-testid="today-profile-update-reminder">
                <span class="today-profile-reminder__mark"><RefreshCw :size="16" /></span>
                <div class="today-profile-reminder__body"><strong>更新一下学习画像</strong><small>{{ profileReminder.message }}</small></div>
                <div class="today-profile-reminder__actions"><button type="button" @click="openProfileReminder">现在更新</button><button type="button" :disabled="profileReminderBusy" @click="dismissProfileReminder">稍后提醒</button></div>
              </article>
              <article v-for="(item, index) in todayRequiredTasks" :key="`${item.path_id}:${item.node_key}`" :class="['today-task-row', item.status]" :data-testid="`today-learning-task-${index}`">
                <span class="today-task-row__mark"><CheckCircle2 v-if="item.status === 'completed'" :size="17" /><span v-else>{{ index + 1 }}</span></span>
                <div class="today-task-row__body"><strong>{{ item.knowledge_point_title || item.title }}</strong><small>{{ item.course_title || workspaceCourse.title }} · {{ item.title }} · {{ taskStatusLabel(item.status) }}</small></div>
                <div class="today-task-row__facts"><span><Clock3 :size="14" />{{ item.estimate_minutes[0] }}-{{ item.estimate_minutes[1] }} 分钟</span><span>{{ todayResourceStatusLabel(item.resource_status) }}</span></div>
                <button type="button" :disabled="item.status === 'completed'" @click="openTodayTask(item)">{{ item.status === 'completed' ? '已完成' : '进入任务' }}<ArrowRight :size="14" /></button>
              </article>
            </div>
            <div v-else class="today-task-complete"><CheckCircle2 :size="19" /><span>今日必做任务已全部完成。</span><small>智能组卷已开放，用它检验本轮学习效果。</small></div>
          </section>
        </main>

        <aside class="today-learning-rail" aria-label="今日学习下一步">
          <section class="today-next-step" data-testid="today-next-step">
            <p>做完之后去哪</p>
            <h2>{{ todayExamUnlocked ? '智能组卷已解锁' : '先完成今日必做任务' }}</h2>
            <span v-if="todayExamUnlocked">根据你刚刚的学习证据生成本轮测评，结果会回流画像、路径、错题和复习。</span>
            <span v-else>完成清单中的每项任务后，这里会自动开放智能组卷。</span>
            <button type="button" :disabled="!todayExamUnlocked" @click="openIntelligentExam"><ClipboardCheck :size="15" />{{ todayExamUnlocked ? '进入智能组卷' : `还差 ${todayRemainingTasks.length} 项` }}</button>
          </section>

          <nav class="today-quick-links" aria-label="学习空间快捷入口">
            <router-link to="/workspace/path"><MapPin :size="16" /><span><strong>学习路径</strong><small>查看今天之后的安排</small></span><ArrowRight :size="14" /></router-link>
            <router-link to="/workspace/resources"><ListChecks :size="16" /><span><strong>资源中心</strong><small>打开已归档的学习产物</small></span><ArrowRight :size="14" /></router-link>
            <router-link to="/workspace/review"><RefreshCw :size="16" /><span><strong>复习中心</strong><small>{{ workspace?.review?.due_count || 0 }} 项到期复习</small></span><ArrowRight :size="14" /></router-link>
          </nav>
        </aside>
      </div>
    </template>

    <div v-if="false" aria-hidden="true">
    <header class="workspace-heading">
      <div>
        <p>学习空间</p>
        <h1>{{ workspaceCourse?.title || '选择课程开始学习' }}</h1>
        <span v-if="workspaceCourse">{{ workspaceCourse.version || '当前版本' }} · {{ workspace?.chapters?.length || 0 }} 个章节</span>
        <span v-else>课程、任务与学习伙伴将在这里保持同步。</span>
      </div>
      <div class="workspace-status" v-if="workspaceProfile">
        <small>当前掌握度</small>
        <strong>{{ Math.round((workspaceProfile.mastery || 0) * 100) }}%</strong>
      </div>
    </header>

    <nav class="mobile-workspace-tabs" aria-label="学习空间区域">
          <button :class="{ active: mobilePanel === 'course' }" @click="selectMobilePanel('course')"><ListChecks :size="15" />课程任务</button>
          <button :class="{ active: mobilePanel === 'learning' }" @click="selectMobilePanel('learning')"><BookOpen :size="15" />学习内容</button>
          <button :class="{ active: mobilePanel === 'partner' }" @click="selectMobilePanel('partner')"><Bot :size="15" />AI 伙伴</button>
    </nav>

    <div class="topbar">
          <div class="mode-tabs">
            <button :class="{ active: !editing }" @click="editing = false">执行路径</button>
            <button :class="{ active: editing }" @click="selectedPlan ? loadPlanIntoEditor(selectedPlan) : resetDraft()">计划草稿</button>
          </div>
          <button class="icon-button" title="刷新" :disabled="loading" @click="refresh(true)"><RefreshCw :size="16" :class="{ spin: loading }" /></button>
          <button class="command" @click="resetDraft"><Plus :size="15" />新建计划</button>
    </div>

    <div v-if="error" class="banner error"><X :size="15" />{{ error }}</div>
    <div v-if="notice" class="banner notice"><CheckCircle2 :size="15" />{{ notice }}</div>

    <div class="workspace-grid">
      <aside class="course-rail" :class="{ 'mobile-hidden': mobilePanel !== 'course' }" aria-label="课程与任务">
        <div class="panel-title"><span>课程与任务</span><small>{{ workspaceTasks.length }}</small></div>
        <div v-if="workspaceCourse" class="course-summary">
          <BookOpen :size="17" />
          <div><strong>{{ workspaceCourse.title }}</strong><small>{{ workspaceChapters.length }} 个章节 · {{ sourceCount }} 份教材来源 · {{ workspaceCourse.version || '当前版本' }}</small></div>
        </div>
        <div v-else class="empty compact">尚未选择课程</div>

        <div class="rail-section-title"><span>课程目录</span><small>{{ workspaceChapters.length }}</small></div>
        <div class="chapter-tree" aria-label="课程章节树">
          <button
            v-for="chapter in workspaceChapters"
            :key="chapter.id"
            :class="{ current: chapter.id === currentChapterId, completed: chapterNodeByTarget.get(chapter.id)?.status === 'completed' }"
            :style="{ '--chapter-depth': chapter.depth }"
            :title="chapter.source ? `${chapter.source.title} · ${chapter.source.license || '许可信息见课程来源'}` : '课程教材来源待补充'"
            @click="openChapter(chapter)"
          >
            <CheckCircle2 v-if="chapterNodeByTarget.get(chapter.id)?.status === 'completed'" :size="14" />
            <Circle v-else :size="14" />
            <span><strong>{{ chapter.position }}. {{ chapter.title }}</strong><small><FileText :size="11" />{{ chapterSourceLabel(chapter) }}</small></span>
          </button>
          <div v-if="!workspaceChapters.length && !loading" class="empty compact">课程目录尚未就绪</div>
        </div>

        <div class="rail-section-title"><span>今日任务</span><small>{{ workspaceTasks.length }}</small></div>
        <div class="task-list">
          <article v-for="(item, index) in workspaceTasks" :key="`${item.path_id}:${item.node_key}`" :data-testid="`workspace-today-task-${index}`" :class="[item.status, { primary: index === 0 }]">
            <div><strong>{{ item.title }}</strong><small>{{ index === 0 ? `下一任务 · ${taskStatusLabel(item.status)}` : taskStatusLabel(item.status) }}</small></div>
            <span><Clock3 :size="11" />预计 {{ item.estimate_minutes[0] }}-{{ item.estimate_minutes[1] }} 分钟</span>
            <p class="task-reason">{{ item.recommendation_reason }}</p>
            <p class="task-criteria">完成标准：{{ item.completion_criteria }}</p>
            <button @click="continueTask(item)">{{ index === 0 ? '继续' : '查看' }}<ArrowRight :size="13" /></button>
          </article>
          <div v-if="!workspaceTasks.length" class="empty compact">今日任务已完成，可从下方历史继续查看。</div>
        </div>

        <div class="rail-section-title"><span>已完成</span><small>{{ completedTasks.length }}</small></div>
        <div class="completed-list">
          <button v-for="item in completedTasks" :key="item.id" @click="continueTask({ ...item, path_id: workspace?.current_path?.id || selectedPath?.id })">
            <CheckCircle2 :size="14" /><span><strong>{{ item.title }}</strong><small>已完成 · {{ item.estimate_minutes[0] }}-{{ item.estimate_minutes[1] }} 分钟</small></span>
          </button>
          <div v-if="!completedTasks.length" class="empty compact">完成任务后会保留在这里</div>
        </div>

        <div class="rail-section-title"><span>学习计划</span><small>{{ plans.length }}</small></div>
        <div class="plan-items">
          <button v-for="plan in plans" :key="plan.id" :class="{ active: plan.id === selectedPlanId }" @click="selectPlan(plan); mobilePanel = 'learning'">
            <CalendarCheck :size="16" />
            <span><strong>{{ plan.title }}</strong><small>{{ plan.status }} · v{{ plan.versions.at(-1)?.number || 1 }}</small></span>
          </button>
          <div v-if="!plans.length && !loading" class="empty compact">暂无计划</div>
        </div>
      </aside>

      <main class="main-panel" :class="{ 'mobile-hidden': mobilePanel !== 'learning' }" aria-label="当前学习对象">
        <div class="stage-label"><BookOpen :size="15" /><span>当前学习对象</span><small>{{ selectedPath?.status || workspace?.state || '准备中' }}</small></div>
        <form v-if="editing" class="editor" @submit.prevent="saveDraft">
          <div class="editor-head"><div><p>CONFIRMATION-GATED PLAN</p><h2>{{ selectedPlan ? '编辑计划新版本' : '创建学习计划' }}</h2></div><FilePlus2 :size="22" /></div>
          <div class="fields">
            <label>计划名称<input v-model="title" required maxlength="256" placeholder="例如：两周完成 RAG 实训" /></label>
            <label>课程<select v-model="courseId" required><option value="" disabled>选择课程</option><option v-for="course in targets.courses" :key="course.id" :value="course.id">{{ course.title }}</option></select></label>
            <label class="wide">学习目标<textarea v-model="goal" required maxlength="2000" rows="2" placeholder="明确成果、范围和完成标准" /></label>
            <label>截止时间<input v-model="deadline" type="datetime-local" /></label>
          </div>

          <div class="node-heading"><div><strong>路径节点</strong><small>正式节点必须来自课程章节或本人资源</small></div><button type="button" @click="nodes.push(blankNode())"><Plus :size="14" />添加节点</button></div>
          <div class="node-editor" v-for="(node, index) in nodes" :key="node.uiKey">
            <span class="sequence">{{ index + 1 }}</span>
            <div class="node-fields">
              <label class="extension-toggle"><input v-model="node.extension" type="checkbox" />外部扩展内容</label>
              <select v-if="!node.extension" v-model="node.objectValue" required @change="node.title = availableObjects.find(item => `${item.type}:${item.id}` === node.objectValue)?.title || node.title">
                <option value="" disabled>选择真实章节或资源</option>
                <option v-for="item in availableObjects" :key="`${item.type}:${item.id}`" :value="`${item.type}:${item.id}`">{{ item.type === 'chapter' ? '章节' : '资源' }} · {{ item.title }}</option>
              </select>
              <input v-model="node.title" required maxlength="256" placeholder="节点标题" />
              <input v-if="node.extension" v-model="node.extensionReason" required maxlength="1000" placeholder="说明为什么需要扩展内容" />
              <div class="duration"><Clock3 :size="13" /><input v-model.number="node.min" type="number" min="1" max="10080" /><span>至</span><input v-model.number="node.max" type="number" min="1" max="10080" /><span>分钟</span></div>
            </div>
            <div class="node-actions">
              <button type="button" title="上移" :disabled="index === 0" @click="moveNode(index, -1)"><ChevronUp :size="14" /></button>
              <button type="button" title="下移" :disabled="index === nodes.length - 1" @click="moveNode(index, 1)"><ChevronDown :size="14" /></button>
              <button type="button" title="删除" :disabled="nodes.length === 1" @click="removeNode(index)"><Trash2 :size="14" /></button>
            </div>
          </div>
          <div class="editor-footer"><span>保存草稿不会创建正式路径。</span><button class="command" :disabled="saving"><LoaderCircle v-if="saving" :size="15" class="spin" /><Save v-else :size="15" />保存草稿</button></div>
        </form>

        <template v-else>
          <section class="learning-object-container" data-testid="learning-object-container">
            <header class="object-toolbar">
              <div class="object-tabs" role="tablist" aria-label="学习对象类型">
                <button
                  v-for="type in availableObjectTypes"
                  :key="type.key"
                  type="button"
                  role="tab"
                  :aria-selected="activeObjectType === type.key"
                  :class="{ active: activeObjectType === type.key }"
                  :data-testid="`learning-object-tab-${type.key}`"
                  @click="selectObjectType(type.key)"
                >
                  <component :is="type.icon" :size="14" />{{ type.label }}
                </button>
              </div>
              <button v-if="activeObject" class="object-icon-action" type="button" :title="copiedObjectId === activeObject.id ? '已复制' : '复制当前内容'" @click="copyActiveObject">
                <CheckCircle2 v-if="copiedObjectId === activeObject.id" :size="15" /><Copy v-else :size="15" />
              </button>
            </header>

            <div v-if="activeObject" class="object-stage" :data-object-type="activeObject.object_type" @mouseup="captureObjectSelection" @keyup="captureObjectSelection">
              <header class="object-heading">
                <div>
                  <small>{{ activeObject.subtitle }}</small>
                  <h2>{{ activeObject.title }}</h2>
                  <p>{{ activeObject.source?.title || '课程内学习对象' }} · {{ activeObject.version?.label || '当前版本' }}</p>
                </div>
                <span :class="['object-status', activeObject.status]">{{ objectStatusLabel(activeObject.status) }}</span>
              </header>

              <div v-if="activeObject.error_boundary" class="object-error" role="alert">
                <X :size="16" />
                <div><strong>当前对象无法完整渲染</strong><span>{{ activeObject.error_boundary }}</span></div>
              </div>

              <article v-else-if="activeObject.render.kind === 'document'" class="document-reader" data-testid="learning-object-document">
                <span>{{ activeObject.render.section }}</span>
                <p>{{ activeObject.render.excerpt }}</p>
              </article>

              <div v-else-if="activeObject.render.kind === 'code'" class="code-object" data-testid="learning-object-code">
                <div class="code-language"><Code2 :size="14" />{{ activeObject.render.language }}</div>
                <pre><code>{{ activeObject.render.content }}</code></pre>
                <p>{{ activeObject.truth_boundary }}</p>
              </div>

              <div v-else-if="activeObject.render.kind === 'experiment'" class="experiment-object" data-testid="learning-object-experiment">
                <div class="experiment-summary"><FlaskConical :size="24" /><div><strong>{{ activeObject.render.template }}</strong><span>在统一中栏查看实验版本、参数与最近结果。</span></div></div>
                <div v-if="Object.keys(activeObject.render.parameters || {}).length" class="metric-grid">
                  <div v-for="(value, key) in activeObject.render.parameters" :key="key"><small>{{ key }}</small><strong>{{ value }}</strong></div>
                </div>
                <div v-else class="inline-empty">实验已绑定到当前课程，参数将在首次配置后显示。</div>
                <div v-if="Object.keys(activeObject.render.metrics || {}).length" class="metric-grid results">
                  <div v-for="(value, key) in activeObject.render.metrics" :key="key"><small>{{ key }}</small><strong>{{ value }}</strong></div>
                </div>
              </div>

              <article v-else-if="activeObject.render.kind === 'exercise'" class="exercise-object" data-testid="learning-object-exercise">
                <div class="exercise-meta"><ClipboardCheck :size="15" /><span>{{ questionTypeLabel(activeObject.render.question_type) }} · {{ bloomLabel(activeObject.render.bloom_level) }}</span></div>
                <h3>{{ activeObject.render.prompt }}</h3>
                <div class="practice-options">
                  <label v-for="(option, index) in activeObject.render.options" :key="`${index}:${option}`">
                    <input v-model="exerciseAnswer" type="radio" :value="option === '是' ? 'true' : 'false'" :name="`workspace-exercise-${activeObject.id}`" />
                    <b>{{ String.fromCharCode(65 + index) }}</b><span>{{ option }}</span>
                  </label>
                </div>
                <button class="exercise-submit" type="button" :disabled="exerciseBusy || !exerciseAnswer" data-testid="workspace-exercise-submit" @click="submitWorkspaceExercise">
                  <LoaderCircle v-if="exerciseBusy" class="spin" :size="15" />
                  <ClipboardCheck v-else :size="15" />
                  {{ exerciseBusy ? '正在判分' : '提交答案并查看反馈' }}
                </button>
                <section v-if="exerciseFeedback" class="exercise-feedback" data-testid="workspace-exercise-feedback" aria-live="polite">
                  <strong v-if="exerciseFeedback.error">提交失败：{{ exerciseFeedback.error }}</strong>
                  <template v-else>
                    <strong>{{ exerciseFeedback.correct ? '判定正确' : '判定需要复习' }} · {{ Math.round((exerciseFeedback.score || 0) * 100) }} 分</strong>
                    <p>{{ exerciseFeedback.answer_explanation || activeObject.render.explanation || '服务端已完成客观判分。' }}</p>
                    <small v-if="!exerciseFeedback.correct">错因候选：{{ (activeObject.render.misconception_tags || []).join('、') || 'insufficient_evidence' }}（系统候选，不会自动写成你的判断）</small>
                    <small v-else>判分来源：服务端正式题目版本与 canonical 来源证据。</small>
                    <div v-if="!exerciseFeedback.correct && exerciseFeedback.misconception_review" class="misconception-decision" data-testid="workspace-misconception-decision">
                      <template v-if="exerciseFeedback.misconception_review.status === 'proposed'">
                        <p>请确认系统候选是否符合你的实际错因，也可以修正为更准确的分类。</p>
                        <label>修正分类
                          <select v-model="misconceptionCategory">
                            <option value="knowledge_gap">知识缺口</option>
                            <option value="concept_confusion">概念混淆</option>
                            <option value="strategy_error">策略错误</option>
                            <option value="calculation_error">计算错误</option>
                            <option value="careless">粗心失误</option>
                            <option value="programming_error">编程错误</option>
                            <option value="insufficient_evidence">证据不足</option>
                          </select>
                        </label>
                        <label>补充说明<input v-model="misconceptionNote" maxlength="2000" placeholder="可选：说明你为什么这样判断" /></label>
                        <div>
                          <button type="button" :disabled="misconceptionBusy" data-testid="workspace-misconception-accept" @click="decideWorkspaceMisconception('accept')">确认候选</button>
                          <button type="button" :disabled="misconceptionBusy" data-testid="workspace-misconception-modify" @click="decideWorkspaceMisconception('modify')">按所选分类修正</button>
                          <button type="button" :disabled="misconceptionBusy" @click="decideWorkspaceMisconception('reject')">当前证据不符</button>
                        </div>
                      </template>
                      <template v-else>
                        <strong>错因决定已记录：{{ exerciseFeedback.misconception_review.confirmed_category || '未采纳系统候选' }}</strong>
                        <p>该记录以“学生声明”证据回流画像、学习路径和教师证据；不会仅凭一次声明直接改变掌握度。</p>
                        <small v-if="exerciseFeedback.misconception_projection">事件 {{ exerciseFeedback.misconception_projection.learning_event?.id }} · 证据强度 user_declared · 掌握度未直接改变</small>
                      </template>
                      <strong v-if="exerciseFeedback.misconception_error">回流失败：{{ exerciseFeedback.misconception_error }}</strong>
                    </div>
                  </template>
                </section>
              </article>

              <footer class="object-provenance">
                <span><FileText :size="12" />{{ activeObject.source?.filename || '课程对象' }}<template v-if="activeObject.source?.location"> · {{ activeObject.source.location }}</template></span>
                <span>版本 {{ activeObject.version?.label || '当前' }}<template v-if="activeObject.version?.content_hash"> · {{ activeObject.version.content_hash.slice(0, 10) }}</template></span>
              </footer>
            </div>
            <details v-if="activeObject?.evidence_panel" class="evidence-panel" data-testid="workspace-evidence-panel">
              <summary>
                <span><ShieldCheck :size="14" />来源与质量</span>
                <b :class="activeObject.evidence_panel.readiness">{{ activeObject.evidence_panel.ready ? '证据就绪' : '证据受限' }}</b>
              </summary>
              <div class="evidence-panel-body">
                <section class="evidence-source-list">
                  <header><strong>可核查来源</strong><small>{{ activeObject.evidence_panel.source_summary }}</small></header>
                  <article v-for="source in activeObject.evidence_panel.sources" :key="source.source_ref_id">
                    <MapPin :size="14" />
                    <div>
                      <strong>{{ source.document_title }}</strong>
                      <span>{{ source.filename }} · {{ source.location }}<template v-if="source.page_number"> · 第 {{ source.page_number }} 页</template></span>
                      <small>{{ source.license }} · source_ref {{ source.source_ref_id }}</small>
                    </div>
                  </article>
                  <p v-if="!activeObject.evidence_panel.sources.length">当前对象没有可展示的合法来源证据；非法或跨课程引用不会回显。</p>
                </section>
                <section class="evidence-check-grid" aria-label="质量检查">
                  <div v-for="check in activeObject.evidence_panel.checks" :key="check.category" :class="check.status">
                    <small>{{ check.label }}</small>
                    <strong>{{ evidenceStatusLabel(check.status) }}</strong>
                  </div>
                </section>
                <section class="truth-boundary">
                  <strong>真实性边界</strong>
                  <p>{{ activeObject.evidence_panel.truth_boundary }}</p>
                  <small v-if="activeObject.evidence_panel.blockers.length">当前限制：{{ activeObject.evidence_panel.blockers.map(evidenceBlockerLabel).join('、') }}</small>
                </section>
              </div>
            </details>
            <div v-if="!activeObject" class="empty object-empty">当前课程尚无可展示学习对象</div>
          </section>

          <div v-if="!selectedPlan" class="empty large">选择计划或创建新计划</div>
          <div v-else class="execution">
            <header class="execution-head">
              <div><p>{{ selectedPlan.status }}</p><h2>{{ selectedPlan.title }}</h2><span>{{ latestSpec(selectedPlan)?.goal }}</span></div>
              <div class="head-actions">
                <button title="编辑新版本" @click="loadPlanIntoEditor(selectedPlan)"><Save :size="15" /></button>
                <button v-if="['draft', 'replan_pending'].includes(selectedPlan.status)" class="command" :disabled="saving" @click="confirmPlan"><CheckCircle2 :size="15" />确认并生效</button>
              </div>
            </header>

            <div v-if="selectedPath" class="path-summary">
              <div><strong>{{ selectedPath.status }}</strong><span>{{ selectedPath.nodes.filter(item => item.status === 'completed').length }}/{{ selectedPath.nodes.length }} 节点完成</span></div>
              <button v-if="selectedPath.status === 'active'" @click="transitionPath('paused')"><Pause :size="14" />暂停</button>
              <button v-else-if="selectedPath.status === 'paused'" @click="transitionPath('active')"><Play :size="14" />恢复</button>
            </div>

            <div v-if="selectedPath" class="timeline">
              <article v-for="node in selectedPath.nodes" :id="`workspace-node-${node.id}`" :key="node.id" :class="node.status">
                <div class="timeline-mark"><CheckCircle2 v-if="node.status === 'completed'" :size="18" /><Circle v-else :size="18" /></div>
                <div class="timeline-content"><small>步骤 {{ node.sequence }} · {{ nodeTypeLabel(node.node_type) }}</small><h3>{{ node.title }}</h3><p>{{ node.estimate_minutes[0] }}-{{ node.estimate_minutes[1] }} 分钟 · {{ taskStatusLabel(node.status) }}</p></div>
                <div class="timeline-actions" v-if="selectedPath.status === 'active' && node.status !== 'completed'">
                  <button @click="recordNodeActivity(node)">记录学习活动</button>
                </div>
              </article>
            </div>
            <div v-else class="pending-confirm"><Clock3 :size="20" /><strong>等待确认</strong><span>草稿不会产生正式任务或学习路径。</span></div>
          </div>
        </template>
      </main>

      <aside class="partner-rail" :class="{ 'mobile-hidden': mobilePanel !== 'partner' }" aria-label="AI 学习伙伴">
        <div class="panel-title"><span>AI 学习伙伴</span><small>在线</small></div>
        <div class="partner-intro">
          <span class="partner-icon"><Bot :size="19" /></span>
          <strong>围绕当前课程学习</strong>
          <p>{{ workspaceProfile?.weak_knowledge_points?.length ? `已关注 ${workspaceProfile.weak_knowledge_points.length} 个薄弱知识点` : '准备好后，从当前章节开始提问。' }}</p>
        </div>
        <div class="context-list">
          <div><span>课程</span><strong>{{ workspaceCourse?.title || '未选择' }}</strong></div>
          <div><span>当前对象</span><strong>{{ activeObject?.title || '未选择' }}</strong></div>
          <div><span>阅读位置</span><strong>{{ readingPosition.label || '对象起点' }}</strong></div>
        </div>
        <div v-if="selectedObjectText" class="selection-context" data-testid="workspace-selected-text"><small>选中文本</small><p>{{ selectedObjectText }}</p><button type="button" title="清除选中文本" @click="selectedObjectText = ''"><X :size="13" /></button></div>
        <div class="workspace-action-grid" aria-label="当前对象能力动作">
          <button
            v-for="item in workspaceActions"
            :key="item.key"
            type="button"
            :disabled="!!actionBusy || !activeObject"
            :data-testid="`workspace-action-${item.key}`"
            @click="runWorkspaceAction(item.key)"
          >
            <LoaderCircle v-if="actionBusy === item.key" class="spin" :size="14" />
            <component :is="item.icon" v-else :size="14" />
            <span>{{ item.label }}</span>
          </button>
        </div>
        <form class="context-question" @submit.prevent="askWithCurrentContext">
          <textarea v-model="contextQuestion" rows="3" maxlength="12000" placeholder="围绕当前对象提问"></textarea>
          <button class="partner-action" type="submit" :disabled="contextBusy || !contextQuestion.trim() || !activeObject" data-testid="workspace-context-submit">
            <LoaderCircle v-if="contextBusy" class="spin" :size="16" /><MessageSquareText v-else :size="16" />{{ contextBusy ? '正在校验' : '带当前上下文提问' }}
          </button>
        </form>
        <div v-if="actionResult?.task" class="workspace-action-result" data-testid="workspace-action-task-result">
          <div><small>生成任务</small><strong>{{ taskTimeline?.task?.status_label || actionResult.task.status }}</strong></div>
          <code>{{ actionResult.task.task_id }}</code>
          <div class="task-recovery-actions">
            <button
              v-if="actionResult.task.status === 'queued' && actionResult.task.model === 'deterministic'"
              type="button"
              :disabled="taskStatusBusy"
              data-testid="workspace-task-execute-local-demo"
              @click="executeWorkspaceLocalDemoTask"
            ><Play :size="13" />离线完成演示任务</button>
            <button type="button" :disabled="taskStatusBusy" @click="refreshActionTask"><RefreshCw :size="13" />{{ taskStatusBusy ? '处理中' : '刷新状态' }}</button>
            <button
              v-if="['queued', 'running'].includes(actionResult.task.status)"
              type="button"
              class="danger"
              :disabled="taskStatusBusy"
              data-testid="workspace-task-cancel"
              @click="cancelWorkspaceTask"
            ><X :size="13" />取消任务</button>
          </div>
          <div v-if="taskTimeline" class="agent-timeline" data-testid="workspace-agent-timeline">
            <header><small>Agent 任务进度</small><span>{{ taskTimeline.summary.current_phase }}</span></header>
            <div v-if="taskTimeline.stages?.some(item => item.retryable)" class="task-retry-list">
              <button
                v-for="stage in taskTimeline.stages.filter(item => item.retryable)"
                :key="`retry-${stage.sequence}`"
                type="button"
                :disabled="taskStatusBusy"
                :data-testid="`workspace-task-retry-${stage.sequence}`"
                @click="retryWorkspaceTaskStep(stage.sequence)"
              ><RefreshCw :size="12" />重试：{{ stage.label }}</button>
            </div>
            <ol>
              <li v-for="item in taskTimeline.items" :key="item.id" :class="item.status">
                <span class="agent-timeline-mark"><CheckCircle2 v-if="['completed', 'passed'].includes(item.status)" :size="13" /><LoaderCircle v-else-if="item.status === 'running'" class="spin" :size="13" /><Circle v-else :size="13" /></span>
                <div><strong>{{ item.label }}</strong><p>{{ item.detail }}</p></div>
              </li>
            </ol>
          </div>
        </div>
        <div v-else-if="actionResult?.note" class="workspace-action-result" data-testid="workspace-action-note-result">
          <div><small>学习笔记</small><strong>{{ actionResult.note.created ? '已创建' : '已存在' }}</strong></div>
          <code>{{ actionResult.note.id }}</code>
        </div>
        <div v-else-if="actionResult?.path" class="workspace-action-result" data-testid="workspace-action-path-result">
          <div><small>学习路径</small><strong>{{ actionResult.path.created ? '已加入' : '已存在' }}</strong></div>
          <code>{{ actionResult.path.node_id }}</code>
        </div>
        <p v-if="contextNotice" class="context-feedback success">{{ contextNotice }}</p>
        <p v-if="contextError" class="context-feedback error" role="alert">{{ contextError }}</p>
        <section class="artifact-shelf" data-testid="workspace-artifact-shelf">
          <header><span>最近产物</span><small>{{ recentArtifacts.length }}</small></header>
          <button
            v-for="artifact in recentArtifacts"
            :key="artifact.id"
            type="button"
            :data-testid="`workspace-artifact-${artifact.id}`"
            @click="openWorkspaceArtifact(artifact.id)"
          >
            <FileText :size="14" />
            <span><strong>{{ artifact.title }}</strong><small>v{{ artifact.current_version?.number || '-' }} · {{ artifactStatusLabel(artifact.status) }} · {{ artifact.source?.label }}</small></span>
            <ArrowRight :size="13" />
          </button>
          <p v-if="!recentArtifacts.length">生成完成的讲义、实验和练习会自动出现在这里。</p>
        </section>
      </aside>
    </div>
    </div>

    <Teleport to="body">
      <div v-if="artifactDetail" class="artifact-dialog-backdrop" @click.self="closeWorkspaceArtifact()">
        <section class="artifact-dialog" role="dialog" aria-modal="true" aria-label="产物版本编辑" data-testid="workspace-artifact-dialog">
          <header>
            <div><small>{{ artifactDetail.artifact_type }}</small><h2>{{ artifactDetail.title }}</h2></div>
            <button type="button" title="关闭产物" @click="closeWorkspaceArtifact()"><X :size="17" /></button>
          </header>
          <dl>
            <div><dt>当前版本</dt><dd>v{{ currentArtifactVersion?.version_number || '-' }}</dd></div>
            <div><dt>状态</dt><dd>{{ artifactStatusLabel(artifactDetail.status) }}</dd></div>
            <div><dt>来源</dt><dd>{{ recentArtifacts.find(item => item.id === artifactDetail.id)?.source?.label || '未记录' }}</dd></div>
          </dl>
          <label>版本内容<textarea v-model="artifactDraft" rows="16" maxlength="200000" aria-label="产物版本内容"></textarea></label>
          <p v-if="artifactError" class="artifact-dialog-error" role="alert">{{ artifactError }}</p>
          <footer>
            <button type="button" @click="returnToArtifactSource"><ArrowRight :size="14" />回到来源</button>
            <button class="primary" type="button" :disabled="artifactBusy || !artifactDraft.trim()" data-testid="workspace-artifact-save-version" @click="saveWorkspaceArtifactVersion">
              <LoaderCircle v-if="artifactBusy" class="spin" :size="14" /><Save v-else :size="14" />保存新版本
            </button>
          </footer>
        </section>
      </div>
    </Teleport>
  </section>
</template>

<style scoped>
.workspace-page { width: 100%; max-width: 1480px; margin: 0 auto; color: var(--color-text); font-family: var(--font-sans); }
.workspace-heading { display: flex; min-height: 72px; align-items: center; justify-content: space-between; gap: 20px; margin-bottom: 12px; padding: 0 2px; }.workspace-heading p { margin: 0 0 4px; color: #587462; font-size: 10px; font-weight: 700; }.workspace-heading h1 { margin: 0; font-size: 20px; }.workspace-heading span { display: block; margin-top: 5px; color: #7a877f; font-size: 10px; }.workspace-status { min-width: 112px; padding: 10px 12px; border-left: 3px solid #48765a; background: #f1f6f2; }.workspace-status small, .workspace-status strong { display: block; }.workspace-status small { color: #78877d; font-size: 9px; }.workspace-status strong { margin-top: 3px; color: #315b3e; font-size: 18px; }
.mobile-workspace-tabs { display: none; }
.topbar { display: flex; align-items: center; gap: 8px; margin-bottom: 12px; }
.mode-tabs { display: flex; padding: 3px; border: 1px solid #dce4dd; border-radius: 8px; background: #eef2ee; }
.mode-tabs button { height: 30px; padding: 0 12px; border: 0; border-radius: 6px; background: transparent; color: #7b877e; font-size: 11px; cursor: pointer; }
.mode-tabs button.active { background: #fff; color: #2f4938; box-shadow: 0 1px 4px rgba(40,55,45,.09); }
.icon-button { display: grid; width: 36px; height: 36px; place-items: center; margin-left: auto; border: 1px solid #dce4dd; border-radius: 8px; background: #fff; color: #66746a; cursor: pointer; }
.command { display: inline-flex; height: 36px; align-items: center; gap: 6px; padding: 0 12px; border: 1px solid #315e40; border-radius: 8px; background: #315e40; color: #fff; font-size: 11px; cursor: pointer; }
.command:disabled { opacity: .5; cursor: default; }
.banner { display: flex; align-items: center; gap: 7px; margin-bottom: 10px; padding: 9px 11px; border-radius: 8px; font-size: 11px; }
.banner.error { border: 1px solid #ebcbc7; background: #fff4f2; color: #954f47; }.banner.notice { border: 1px solid #c8dfce; background: #f0f8f2; color: #3c6848; }
.workspace-grid { display: grid; min-height: 650px; grid-template-columns: minmax(210px, 24%) minmax(0, 1fr) minmax(230px, 25%); gap: 10px; align-items: stretch; }
.course-rail, .main-panel, .partner-rail { min-width: 0; overflow: hidden; border: 1px solid #dde5de; border-radius: 8px; background: rgba(255,255,255,.9); }
.partner-rail { overflow-y: auto; padding-bottom: 12px; }
.selection-context { position: relative; margin: 10px 12px 0; padding: 9px 30px 9px 10px; border: 1px solid #d5e2d8; border-radius: 7px; background: #f4f8f5; }.selection-context small { color: #6c7b71; font-size: 8px; }.selection-context p { display: -webkit-box; overflow: hidden; margin: 4px 0 0; color: #3f5045; font-size: 9px; line-height: 1.45; -webkit-box-orient: vertical; -webkit-line-clamp: 3; }.selection-context button { position: absolute; top: 6px; right: 6px; display: grid; width: 22px; height: 22px; place-items: center; border: 0; background: transparent; color: #758279; cursor: pointer; }
.workspace-action-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 6px; margin: 10px 12px 0; }.workspace-action-grid button { display: flex; min-width: 0; height: 34px; align-items: center; justify-content: center; gap: 5px; padding: 0 7px; border: 1px solid #d5e1d8; border-radius: 7px; background: #f8faf8; color: #496151; font-size: 9px; cursor: pointer; }.workspace-action-grid button:hover { border-color: #b9cebf; background: #eef5f0; }.workspace-action-grid button:disabled { opacity: .48; cursor: default; }.workspace-action-grid span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.context-question { margin: 10px 12px 0; }.context-question textarea { min-height: 72px; margin: 0 0 8px; resize: vertical; }.context-question .partner-action { width: 100%; justify-content: center; border: 0; cursor: pointer; }.context-question .partner-action:disabled { opacity: .5; cursor: default; }.context-feedback { margin: 8px 12px 0; font-size: 9px; line-height: 1.45; }.context-feedback.success { color: #3f6b4b; }.context-feedback.error { color: #a04e46; }
.workspace-action-result { margin: 9px 12px 0; padding: 9px 10px; border: 1px solid #d5e2d8; border-radius: 7px; background: #f4f8f5; }.workspace-action-result > div { display: flex; align-items: center; justify-content: space-between; gap: 8px; }.workspace-action-result small { color: #738178; font-size: 8px; }.workspace-action-result strong { color: #315b3e; font-size: 9px; }.workspace-action-result code { display: block; overflow: hidden; margin-top: 6px; color: #647269; font-size: 8px; text-overflow: ellipsis; white-space: nowrap; }.workspace-action-result button { display: flex; height: 28px; align-items: center; justify-content: center; gap: 5px; margin-top: 7px; padding: 0 8px; border: 1px solid #c9d8cc; border-radius: 6px; background: #fff; color: #3f6149; font-size: 8px; cursor: pointer; }.workspace-action-result .task-recovery-actions { justify-content: flex-start; }.task-recovery-actions button { flex: 1; }.task-recovery-actions button.danger { border-color: #e0c7c3; color: #98544d; }.task-retry-list { display: flex !important; flex-wrap: wrap; justify-content: flex-start !important; gap: 5px; margin-top: 7px; }.task-retry-list button { width: 100%; margin-top: 0; }
.agent-timeline { display: block !important; margin-top: 9px; padding-top: 8px; border-top: 1px solid #dce6de; }.agent-timeline header { display: flex; align-items: center; justify-content: space-between; gap: 8px; }.agent-timeline header span { overflow: hidden; color: #42634d; font-size: 8px; text-overflow: ellipsis; white-space: nowrap; }.agent-timeline ol { max-height: 210px; overflow-y: auto; margin: 8px 0 0; padding: 0; list-style: none; }.agent-timeline li { display: grid; grid-template-columns: 16px minmax(0, 1fr); gap: 6px; padding: 6px 0; border-top: 1px solid #e5ece7; }.agent-timeline li:first-child { border-top: 0; }.agent-timeline-mark { display: flex; padding-top: 1px; color: #7b8b80; }.agent-timeline li.completed .agent-timeline-mark, .agent-timeline li.passed .agent-timeline-mark { color: #3f7450; }.agent-timeline li.failed .agent-timeline-mark { color: #a04e46; }.agent-timeline li strong { display: block; color: #405148; font-size: 8px; }.agent-timeline li p { margin: 2px 0 0; color: #77847c; font-size: 8px; line-height: 1.4; }
.artifact-shelf { margin: 12px 12px 0; padding-top: 9px; border-top: 1px solid #dce6de; }.artifact-shelf header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 4px; color: #45574c; font-size: 9px; font-weight: 700; }.artifact-shelf header small { color: #8a968e; font-size: 8px; }.artifact-shelf > button { display: grid; width: 100%; min-height: 46px; grid-template-columns: 17px minmax(0,1fr) 13px; align-items: center; gap: 6px; padding: 7px 0; border: 0; border-bottom: 1px solid #e5ece7; background: transparent; color: #607067; text-align: left; cursor: pointer; }.artifact-shelf > button > span { min-width: 0; }.artifact-shelf strong, .artifact-shelf small { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }.artifact-shelf strong { color: #405148; font-size: 9px; }.artifact-shelf small { margin-top: 3px; color: #849087; font-size: 8px; }.artifact-shelf > p { margin: 8px 0 0; color: #8b968f; font-size: 8px; line-height: 1.5; }
.artifact-dialog-backdrop { position: fixed; z-index: 1000; inset: 0; display: grid; place-items: center; padding: 20px; background: rgba(31,42,35,.42); }.artifact-dialog { display: flex; width: min(720px, calc(100vw - 40px)); max-height: calc(100vh - 40px); flex-direction: column; overflow: hidden; border: 1px solid #d8e1da; border-radius: 8px; background: #fff; box-shadow: 0 22px 60px rgba(28,39,32,.24); }.artifact-dialog > header { display: flex; align-items: flex-start; justify-content: space-between; gap: 14px; padding: 16px 18px; border-bottom: 1px solid #e6ece7; }.artifact-dialog h2 { margin: 3px 0 0; font-size: 18px; }.artifact-dialog header small { color: #78867d; font-size: 9px; }.artifact-dialog header button { display: grid; width: 32px; height: 32px; place-items: center; border: 1px solid #dce4dd; border-radius: 7px; background: #fff; color: #65736a; cursor: pointer; }.artifact-dialog dl { display: grid; grid-template-columns: repeat(3,minmax(0,1fr)); margin: 0; padding: 11px 18px; border-bottom: 1px solid #edf1ee; background: #f6f8f6; }.artifact-dialog dl div { min-width: 0; }.artifact-dialog dt { color: #8a968e; font-size: 8px; }.artifact-dialog dd { overflow: hidden; margin: 3px 0 0; color: #405148; font-size: 10px; text-overflow: ellipsis; white-space: nowrap; }.artifact-dialog > label { display: flex; min-height: 0; flex: 1; flex-direction: column; padding: 14px 18px; color: #68766d; font-size: 9px; }.artifact-dialog textarea { min-height: 280px; flex: 1; resize: vertical; font-family: Consolas, 'Courier New', monospace; font-size: 11px; line-height: 1.55; }.artifact-dialog-error { margin: 0 18px 10px; color: #a04e46; font-size: 9px; }.artifact-dialog footer { display: flex; justify-content: flex-end; gap: 8px; padding: 12px 18px; border-top: 1px solid #e6ece7; }.artifact-dialog footer button { display: inline-flex; height: 34px; align-items: center; gap: 6px; padding: 0 11px; border: 1px solid #cdd9d0; border-radius: 7px; background: #fff; color: #476052; font-size: 10px; cursor: pointer; }.artifact-dialog footer button.primary { border-color: #315e40; background: #315e40; color: #fff; }.artifact-dialog footer button:disabled { opacity: .5; cursor: default; }
.course-rail { overflow-y: auto; }
.panel-title { display: flex; height: 43px; align-items: center; justify-content: space-between; padding: 0 12px; border-bottom: 1px solid #e5ebe6; font-size: 11px; }.panel-title small { color: #8b978e; }
.course-summary { display: grid; grid-template-columns: 22px 1fr; gap: 8px; padding: 12px; border-bottom: 1px solid #edf1ed; background: #f5f8f5; }.course-summary strong, .course-summary small { display: block; overflow: hidden; text-overflow: ellipsis; }.course-summary strong { color: #344238; font-size: 11px; }.course-summary small { margin-top: 4px; color: #87938b; font-size: 9px; }.rail-section-title { display: flex; align-items: center; justify-content: space-between; padding: 10px 12px 6px; color: #6c7970; font-size: 9px; font-weight: 700; }.rail-section-title small { color: #9aa39d; }
.chapter-tree > button { display: grid; width: 100%; min-height: 49px; grid-template-columns: 17px minmax(0, 1fr); align-items: center; gap: 7px; padding: 7px 10px 7px calc(10px + var(--chapter-depth) * 12px); border: 0; border-bottom: 1px solid #edf1ed; background: transparent; color: #7c8980; text-align: left; cursor: pointer; }.chapter-tree > button.current { background: #eef6f0; color: #315b3e; box-shadow: inset 3px 0 #4a7659; }.chapter-tree > button.completed { color: #55735f; }.chapter-tree strong, .chapter-tree small { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }.chapter-tree strong { color: #38463c; font-size: 10px; }.chapter-tree small { display: flex; align-items: center; gap: 4px; margin-top: 3px; color: #87938b; font-size: 8px; }
.task-list article { display: flex; min-width: 0; flex-direction: column; align-items: stretch; gap: 6px; padding: 11px 12px; border-bottom: 1px solid #edf1ed; }.task-list article > div { min-width: 0; }.task-list strong, .task-list small { display: block; overflow-wrap: anywhere; }.task-list strong { color: #3d493f; font-size: 10px; line-height: 1.45; }.task-list small { margin-top: 3px; color: #52705b; font-size: 8px; }.task-list article > span { display: flex; align-items: center; gap: 4px; color: #77857b; font-size: 8px; }.task-list .task-reason, .task-list .task-criteria { margin: 0; color: #647269; font-size: 8px; line-height: 1.55; overflow-wrap: anywhere; }.task-list .task-criteria { padding-top: 5px; border-top: 1px dashed #dce6de; color: #46554a; }.task-list article > button { display: inline-flex; align-self: flex-start; align-items: center; gap: 3px; padding: 5px 7px; border: 1px solid #cbd9ce; border-radius: 6px; background: #f4f8f5; color: #315b3e; font-size: 9px; cursor: pointer; }
.task-list article.primary { background: #f4f8f5; box-shadow: inset 3px 0 #4a7659; }.task-list article.primary small { font-weight: 700; }
.completed-list > button { display: grid; width: 100%; min-height: 47px; grid-template-columns: 17px minmax(0, 1fr); align-items: center; gap: 7px; padding: 8px 11px; border: 0; border-bottom: 1px solid #edf1ed; background: transparent; color: #5e7a67; text-align: left; cursor: pointer; }.completed-list strong, .completed-list small { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }.completed-list strong { color: #405046; font-size: 10px; }.completed-list small { margin-top: 3px; color: #8b978f; font-size: 8px; }
.plan-items > button { display: grid; width: 100%; min-height: 55px; grid-template-columns: 20px minmax(0, 1fr); align-items: center; gap: 7px; padding: 9px 11px; border: 0; border-bottom: 1px solid #edf1ed; background: transparent; color: #68756c; text-align: left; cursor: pointer; }
.plan-items > button.active, .plan-items > button:hover { background: #eef6f0; color: #31523c; }.plan-items strong, .plan-items small { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }.plan-items strong { color: #344038; font-size: 11px; }.plan-items small { margin-top: 4px; color: #929d95; font-size: 9px; }
.main-panel { padding: 0 18px 18px; }.stage-label { display: flex; height: 43px; align-items: center; gap: 7px; margin: 0 -18px 16px; padding: 0 14px; border-bottom: 1px solid #e5ebe6; color: #4c6555; font-size: 10px; font-weight: 700; }.stage-label small { margin-left: auto; color: #8d9891; font-size: 9px; font-weight: 500; }.editor-head, .execution-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 14px; padding-bottom: 14px; border-bottom: 1px solid #e4eae5; }.editor-head p, .execution-head p { margin: 0 0 4px; color: #8a968d; font-size: 9px; }.editor-head h2, .execution-head h2 { margin: 0; font-size: 18px; }.execution-head span { display: block; max-width: 650px; margin-top: 5px; color: #738078; font-size: 11px; line-height: 1.5; }
.fields { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin: 14px 0; }.fields label, .node-fields { color: #68756d; font-size: 10px; }.fields .wide { grid-column: 1 / -1; } input, select, textarea { width: 100%; margin-top: 5px; padding: 8px 9px; border: 1px solid #dce4dd; border-radius: 7px; outline: none; background: #fff; color: #344139; font-size: 11px; box-sizing: border-box; } textarea { resize: vertical; }
.node-heading { display: flex; align-items: center; justify-content: space-between; margin: 14px 0 8px; }.node-heading strong, .node-heading small { display: block; }.node-heading strong { font-size: 12px; }.node-heading small { margin-top: 2px; color: #929c94; font-size: 9px; }.node-heading button { display: flex; align-items: center; gap: 4px; border: 0; background: none; color: #3c6949; font-size: 10px; cursor: pointer; }
.node-editor { display: grid; grid-template-columns: 28px 1fr 30px; gap: 8px; margin-bottom: 8px; padding: 10px; border: 1px solid #e0e7e1; border-radius: 8px; background: #f8faf8; }.sequence { display: grid; width: 24px; height: 24px; place-items: center; border-radius: 7px; background: #e6efe8; color: #42604a; font-size: 10px; }.node-fields { display: grid; grid-template-columns: minmax(140px, 1fr) minmax(150px, 1fr); gap: 7px; }.node-fields input, .node-fields select { margin: 0; }.extension-toggle { display: flex; align-items: center; gap: 5px; grid-column: 1 / -1; }.extension-toggle input { width: auto; margin: 0; }.duration { display: flex; align-items: center; gap: 5px; color: #7d8981; }.duration input { width: 64px; }.node-actions { display: flex; flex-direction: column; gap: 3px; }.node-actions button, .head-actions > button:not(.command) { display: grid; width: 28px; height: 28px; place-items: center; border: 1px solid #dce4dd; border-radius: 7px; background: #fff; color: #69766d; cursor: pointer; }.node-actions button:disabled { opacity: .3; }
.editor-footer { display: flex; align-items: center; justify-content: space-between; margin-top: 14px; color: #849087; font-size: 10px; }.head-actions { display: flex; gap: 7px; }
.path-summary { display: flex; align-items: center; justify-content: space-between; margin: 14px 0; padding: 10px 12px; border-radius: 8px; background: #eef5f0; }.path-summary strong, .path-summary span { display: block; }.path-summary strong { font-size: 11px; text-transform: uppercase; }.path-summary span { margin-top: 3px; color: #718077; font-size: 9px; }.path-summary button { display: flex; align-items: center; gap: 5px; border: 0; background: none; color: #3f644a; font-size: 10px; cursor: pointer; }
.timeline article { display: grid; grid-template-columns: 26px 1fr auto; gap: 8px; min-height: 67px; padding: 10px 0; border-bottom: 1px solid #edf1ed; }.timeline-mark { color: #87948a; }.timeline article.completed .timeline-mark { color: #397149; }.timeline-content small { color: #939d96; font-size: 9px; }.timeline-content h3 { margin: 3px 0; font-size: 12px; }.timeline-content p { margin: 0; color: #7f8b83; font-size: 9px; }.timeline-actions { display: flex; align-items: center; gap: 5px; }.timeline-actions button { height: 29px; padding: 0 8px; border: 1px solid #d7e1d9; border-radius: 7px; background: #fff; color: #607067; font-size: 9px; cursor: pointer; }.timeline-actions button.strong { border-color: #bcd6c3; background: #edf7ef; color: #356342; }
.pending-confirm, .empty { display: grid; min-height: 150px; place-items: center; color: #929d95; font-size: 10px; }.pending-confirm { align-content: center; gap: 5px; }.pending-confirm strong { color: #4c5a50; font-size: 12px; }.empty.large { min-height: 500px; }.empty.compact { min-height: 72px; padding: 10px; text-align: center; }
.learning-object-container { margin-bottom: 18px; border: 1px solid #dce4dd; border-radius: 8px; overflow: hidden; background: #fff; }
.object-toolbar { display: flex; min-height: 43px; align-items: center; justify-content: space-between; gap: 8px; padding: 0 8px; border-bottom: 1px solid #e4eae5; background: #f6f8f6; }
.object-tabs { display: flex; min-width: 0; align-items: center; gap: 3px; overflow-x: auto; }.object-tabs button { display: inline-flex; height: 32px; flex: 0 0 auto; align-items: center; gap: 5px; padding: 0 10px; border: 0; border-radius: 6px; background: transparent; color: #748178; font-size: 10px; cursor: pointer; }.object-tabs button.active { background: #fff; color: #315d40; box-shadow: 0 1px 4px rgba(39,58,45,.12); }.object-icon-action { display: grid; width: 31px; height: 31px; flex: 0 0 auto; place-items: center; border: 1px solid #d7e0d9; border-radius: 6px; background: #fff; color: #607067; cursor: pointer; }
.object-stage { display: flex; height: 430px; min-height: 430px; flex-direction: column; overflow: hidden; }.object-heading { display: flex; min-height: 82px; flex: 0 0 auto; align-items: flex-start; justify-content: space-between; gap: 12px; padding: 15px 17px; border-bottom: 1px solid #edf1ed; box-sizing: border-box; }.object-heading > div { min-width: 0; }.object-heading small { color: #7f8d83; font-size: 9px; }.object-heading h2 { margin: 4px 0; overflow-wrap: anywhere; font-size: 17px; }.object-heading p { margin: 0; color: #7a877e; font-size: 9px; }.object-status { max-width: 92px; flex: 0 0 auto; overflow: hidden; padding: 4px 7px; border: 1px solid #cfddd2; border-radius: 6px; background: #eef6f0; color: #42664d; font-size: 8px; text-overflow: ellipsis; white-space: nowrap; }
.document-reader { min-height: 0; flex: 1; overflow: auto; padding: 28px 30px; background: #fcfdfc; }.document-reader > span { display: block; margin-bottom: 13px; color: #4f6e59; font-size: 10px; font-weight: 700; }.document-reader p { max-width: 760px; margin: 0; color: #354039; font-size: 13px; line-height: 1.9; white-space: pre-wrap; }
.code-object { min-height: 0; flex: 1; overflow: auto; padding: 16px; background: #18211b; color: #e3ebe5; }.code-language { display: flex; align-items: center; gap: 6px; color: #9fb0a4; font-size: 9px; }.code-object pre { margin: 12px 0 0; overflow: auto; }.code-object code { color: #e5ede7; font: 12px/1.8 Consolas, monospace; white-space: pre; }.code-object p { margin: 11px 0 0; padding-top: 10px; border-top: 1px solid #344039; color: #9eaca2; font-size: 9px; }
.experiment-object { min-height: 0; flex: 1; overflow: auto; padding: 22px; background: #fbfcfb; }.experiment-summary { display: flex; align-items: center; gap: 12px; padding: 15px; border-left: 3px solid #4f775c; background: #eef5f0; color: #3c6047; }.experiment-summary strong, .experiment-summary span { display: block; }.experiment-summary strong { font-size: 12px; }.experiment-summary span { margin-top: 4px; color: #6f8075; font-size: 9px; }.metric-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(110px, 1fr)); gap: 8px; margin-top: 15px; }.metric-grid > div { padding: 11px; border: 1px solid #e0e7e1; background: #fff; }.metric-grid small, .metric-grid strong { display: block; }.metric-grid small { color: #859087; font-size: 8px; }.metric-grid strong { margin-top: 5px; color: #3e4c42; font-size: 12px; }.metric-grid.results > div { border-color: #cfe0d2; background: #f3f8f4; }.inline-empty { margin-top: 15px; padding: 18px; border: 1px dashed #d5ddd7; color: #849087; font-size: 10px; text-align: center; }
.exercise-object { min-height: 0; flex: 1; overflow: auto; padding: 22px; background: #fcfdfc; }.exercise-meta { display: flex; align-items: center; gap: 6px; color: #52705c; font-size: 9px; }.exercise-object h3 { margin: 13px 0 16px; font-size: 15px; line-height: 1.55; }.preview-options { display: grid; gap: 8px; }.preview-options > div { display: grid; min-height: 42px; grid-template-columns: 28px minmax(0, 1fr); align-items: center; gap: 8px; padding: 6px 10px; border: 1px solid #e0e7e1; background: #fff; }.preview-options b { display: grid; width: 24px; height: 24px; place-items: center; border-radius: 50%; background: #edf4ef; color: #42634c; font-size: 9px; }.preview-options span { font-size: 11px; }.exercise-object > p { margin: 15px 0 0; color: #849087; font-size: 9px; }
.practice-options { display: grid; gap: 8px; margin-bottom: 14px; }.practice-options label { display: grid; min-height: 42px; grid-template-columns: 18px 28px minmax(0, 1fr); align-items: center; gap: 8px; padding: 7px 10px; border: 1px solid #dfe7e1; border-radius: 7px; background: #fff; cursor: pointer; }.practice-options label:has(input:checked) { border-color: #8eab98; background: #f1f7f3; }.practice-options input { width: 15px; height: 15px; margin: 0; accent-color: #315e40; }.practice-options b { display: grid; width: 24px; height: 24px; place-items: center; border-radius: 50%; background: #edf4ef; color: #42634c; font-size: 9px; }.practice-options span { min-width: 0; color: #35453a; font-size: 11px; line-height: 1.45; overflow-wrap: anywhere; }.exercise-submit { display: inline-flex; min-height: 36px; align-items: center; justify-content: center; gap: 7px; padding: 0 13px; border: 0; border-radius: 7px; background: #315e40; color: #fff; font-size: 10px; font-weight: 700; cursor: pointer; }.exercise-submit:disabled { cursor: not-allowed; opacity: .55; }.exercise-feedback { display: grid; gap: 6px; margin-top: 12px; padding: 12px 13px; border-left: 3px solid #7c9b86; background: #f2f7f3; }.exercise-feedback strong { color: #31483a; font-size: 11px; }.exercise-feedback p { margin: 0; color: #526258; font-size: 10px; line-height: 1.55; }.exercise-feedback small { color: #6e7d73; font-size: 9px; line-height: 1.5; overflow-wrap: anywhere; }
.misconception-decision { display: grid; gap: 8px; margin-top: 6px; padding-top: 10px; border-top: 1px solid #d8e4db; }.misconception-decision label { display: grid; gap: 4px; color: #53635a; font-size: 9px; }.misconception-decision select, .misconception-decision input { width: 100%; min-height: 34px; padding: 0 9px; border: 1px solid #ccd9cf; border-radius: 6px; background: #fff; color: #35453a; font-size: 10px; }.misconception-decision > div { display: flex; flex-wrap: wrap; gap: 6px; }.misconception-decision button { min-height: 32px; padding: 0 10px; border: 1px solid #9cb3a2; border-radius: 6px; background: #fff; color: #315e40; font-size: 9px; cursor: pointer; }.misconception-decision button:first-child { border-color: #315e40; background: #315e40; color: #fff; }.misconception-decision button:disabled { cursor: not-allowed; opacity: .55; }
.object-error { display: flex; flex: 1; align-items: center; justify-content: center; gap: 9px; padding: 24px; color: #96514a; }.object-error strong, .object-error span { display: block; }.object-error strong { font-size: 11px; }.object-error span { margin-top: 4px; font-size: 9px; }.object-provenance { display: flex; min-height: 39px; align-items: center; justify-content: space-between; gap: 10px; margin-top: auto; padding: 0 15px; border-top: 1px solid #e7ece8; background: #f7f9f7; color: #7c8980; font-size: 8px; }.object-provenance span { display: flex; min-width: 0; align-items: center; gap: 4px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }.object-empty { min-height: 430px; }
.evidence-panel { border-top: 1px solid #dde6df; background: #fbfcfb; }.evidence-panel summary { display: flex; min-height: 42px; align-items: center; justify-content: space-between; gap: 10px; padding: 0 14px; color: #415548; font-size: 10px; cursor: pointer; list-style: none; }.evidence-panel summary::-webkit-details-marker { display: none; }.evidence-panel summary span { display: inline-flex; align-items: center; gap: 6px; font-weight: 700; }.evidence-panel summary b { padding: 4px 7px; border-radius: 6px; background: #eef5f0; color: #3d6949; font-size: 8px; }.evidence-panel summary b.blocked { background: #fff1ee; color: #9a5048; }.evidence-panel-body { display: grid; gap: 10px; padding: 0 14px 14px; }.evidence-source-list header { display: flex; align-items: baseline; justify-content: space-between; gap: 8px; }.evidence-source-list header strong { font-size: 10px; }.evidence-source-list header small, .evidence-source-list > p { color: #7f8c83; font-size: 8px; }.evidence-source-list article { display: grid; grid-template-columns: 17px minmax(0,1fr); gap: 7px; margin-top: 7px; padding: 9px; border: 1px solid #e0e7e1; border-radius: 7px; background: #fff; color: #50705a; }.evidence-source-list article strong, .evidence-source-list article span, .evidence-source-list article small { display: block; overflow-wrap: anywhere; }.evidence-source-list article strong { color: #3d4d42; font-size: 9px; }.evidence-source-list article span { margin-top: 3px; color: #65746a; font-size: 8px; }.evidence-source-list article small { margin-top: 3px; color: #8b968e; font-size: 8px; }.evidence-check-grid { display: grid; grid-template-columns: repeat(4,minmax(0,1fr)); gap: 6px; }.evidence-check-grid div { min-width: 0; padding: 8px; border: 1px solid #e0e6e1; border-radius: 7px; background: #fff; }.evidence-check-grid small, .evidence-check-grid strong { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }.evidence-check-grid small { color: #849087; font-size: 8px; }.evidence-check-grid strong { margin-top: 4px; color: #4b5d51; font-size: 8px; }.evidence-check-grid div.passed { border-color: #cfe0d2; background: #f3f8f4; }.evidence-check-grid div.failed, .evidence-check-grid div.manual_required { border-color: #eed3ce; background: #fff5f3; }.evidence-check-grid div.failed strong, .evidence-check-grid div.manual_required strong { color: #9a5048; }.truth-boundary { padding: 9px 10px; border-left: 3px solid #809889; background: #f3f6f4; }.truth-boundary strong { font-size: 9px; }.truth-boundary p { margin: 4px 0 0; color: #5f6f65; font-size: 8px; line-height: 1.5; }.truth-boundary small { display: block; margin-top: 5px; color: #966057; font-size: 8px; overflow-wrap: anywhere; }
.learning-object-container + .execution { padding-top: 2px; }
.partner-intro { padding: 16px 14px; border-bottom: 1px solid #edf1ed; }.partner-icon { display: grid; width: 36px; height: 36px; place-items: center; border-radius: 8px; background: #e8f0ea; color: #396048; }.partner-intro strong { display: block; margin-top: 10px; color: #354239; font-size: 12px; }.partner-intro p { margin: 5px 0 0; color: #7c8980; font-size: 10px; line-height: 1.55; }.context-list { padding: 6px 14px 12px; }.context-list div { padding: 9px 0; border-bottom: 1px solid #edf1ed; }.context-list span, .context-list strong { display: block; }.context-list span { color: #929c95; font-size: 8px; }.context-list strong { margin-top: 4px; overflow: hidden; color: #47554b; font-size: 10px; text-overflow: ellipsis; white-space: nowrap; }.partner-action { display: flex; height: 38px; align-items: center; justify-content: center; gap: 7px; margin: 12px 14px; border: 1px solid #315e40; border-radius: 8px; background: #315e40; color: #fff; font-size: 10px; text-decoration: none; }

/* F1 desktop legibility and neutral palette contract. */
.workspace-page {
  --workspace-ink: var(--color-text);
  --workspace-copy: var(--color-text-secondary);
  --workspace-muted: var(--color-text-muted);
  --workspace-line: var(--color-border);
  --workspace-soft: var(--color-surface-subtle);
  --workspace-accent: var(--color-accent);
  --workspace-accent-soft: var(--color-accent-soft);
  color: var(--workspace-ink);
}
.workspace-page :is(h1, h2, h3, h4) {
  font-family: var(--font-heading);
  line-height: var(--line-height-heading);
}
.workspace-page :is(div, p, span, small, strong, button, label, input, select, textarea, code, dt, dd) { font-size: 14px; }
.workspace-page :is(p, small) { line-height: 1.55; }
.workspace-heading h1 { font-size: 24px; }
.workspace-status strong { font-size: 20px; }
.editor-head h2, .execution-head h2 { font-size: 20px; }
.object-heading h2 { font-size: 18px; }
.exercise-object h3 { font-size: 16px; }
.workspace-heading p, .stage-label, .panel-title, .partner-intro strong, .context-list strong { color: var(--workspace-ink); }
.workspace-heading span, .rail-section-title, .empty, .stage-label small, .partner-intro p, .context-list span { color: var(--workspace-muted); }
.workspace-status { border-left-color: var(--workspace-accent); background: var(--workspace-accent-soft); }
.workspace-status small { color: var(--workspace-muted); }
.workspace-status strong { color: var(--workspace-accent); }
.mode-tabs, .object-toolbar { border-color: var(--workspace-line); background: var(--workspace-soft); }
.mode-tabs button, .object-tabs button { color: var(--workspace-copy); }
.mode-tabs button.active, .object-tabs button.active { background: #fff; color: var(--workspace-accent); box-shadow: 0 1px 4px rgba(65, 45, 34, .1); }
.icon-button, .course-rail, .main-panel, .partner-rail, .learning-object-container { border-color: var(--workspace-line); background: #fff; }
.icon-button { color: var(--workspace-copy); }
.command, .partner-action, .exercise-submit { border-color: var(--workspace-accent); background: var(--workspace-accent); color: #fff; }
.panel-title, .stage-label, .partner-intro, .context-list div { border-color: var(--workspace-line); }
.course-summary, .path-summary, .task-list article.primary, .chapter-tree > button.current, .plan-items > button.active, .plan-items > button:hover { background: var(--workspace-accent-soft); }
.chapter-tree > button.current, .task-list article.primary { color: var(--workspace-accent); box-shadow: inset 3px 0 var(--workspace-accent); }
.course-summary strong, .chapter-tree strong, .task-list strong, .completed-list strong, .plan-items strong { color: var(--workspace-ink); }
.course-summary small, .chapter-tree small, .task-list small, .task-list article > span, .completed-list small, .plan-items small { color: var(--workspace-muted); }
.rail-section-title small, .panel-title small { color: var(--workspace-muted); }
.partner-icon { background: var(--workspace-accent-soft); color: var(--workspace-accent); }
.workspace-action-grid button { border-color: var(--workspace-line); background: var(--workspace-soft); color: var(--workspace-copy); }
.workspace-action-grid button:hover { border-color: var(--color-edu-300); background: var(--workspace-accent-soft); color: var(--workspace-accent); }
.context-question textarea { border-color: var(--workspace-line); color: var(--workspace-ink); }
.context-question .partner-action { background: var(--workspace-accent); color: #fff; }
.workspace-page .workspace-heading p { color: var(--workspace-muted); }
.workspace-page .workspace-heading span { color: var(--workspace-muted); }
.workspace-page .workspace-status { border-left-color: var(--workspace-accent); background: var(--workspace-accent-soft); }
.workspace-page .workspace-status small { color: var(--workspace-muted); }
.workspace-page .workspace-status strong { color: var(--workspace-accent); }
.workspace-page .command,
.workspace-page .partner-action,
.workspace-page .exercise-submit { border-color: var(--workspace-accent); background: var(--workspace-accent); }
.workspace-page .banner.notice { border-color: var(--workspace-line); background: var(--workspace-soft); color: var(--workspace-copy); }
.workspace-page .course-summary,
.workspace-page .path-summary,
.workspace-page .task-list article.primary,
.workspace-page .chapter-tree > button.current,
.workspace-page .plan-items > button.active,
.workspace-page .plan-items > button:hover { background: var(--workspace-accent-soft); }
.workspace-page .chapter-tree > button.current,
.workspace-page .task-list article.primary { color: var(--workspace-accent); box-shadow: inset 3px 0 var(--workspace-accent); }
.workspace-page .partner-icon { background: var(--workspace-accent-soft); color: var(--workspace-accent); }
.workspace-page .workspace-action-grid button:hover { border-color: var(--workspace-line); background: var(--workspace-accent-soft); color: var(--workspace-accent); }
.workspace-page .workspace-action-result,
.workspace-page .selection-context { border-color: var(--workspace-line); background: var(--workspace-soft); }
.workspace-page .workspace-action-result strong { color: var(--workspace-accent); }
.workspace-page .mode-tabs button.active,
.workspace-page .object-tabs button.active { color: var(--workspace-accent); }
.workspace-page .mode-tabs button.active { background: var(--color-surface); }
.spin { animation: spin .8s linear infinite; } @keyframes spin { to { transform: rotate(360deg); } }
@media (max-width: 1180px) { .workspace-grid { grid-template-columns: minmax(190px, 23%) minmax(0, 1fr) minmax(210px, 24%); }.main-panel { padding-right: 14px; padding-left: 14px; }.stage-label { margin-right: -14px; margin-left: -14px; } }
@media (max-width: 900px) { .mobile-workspace-tabs { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 4px; margin-bottom: 10px; padding: 4px; border: 1px solid #dce4dd; border-radius: 8px; background: #eef2ee; }.mobile-workspace-tabs button { display: flex; min-width: 0; height: 36px; align-items: center; justify-content: center; gap: 5px; padding: 0 6px; border: 0; border-radius: 6px; background: transparent; color: #718078; font-size: 10px; cursor: pointer; }.mobile-workspace-tabs button.active { background: #fff; color: #315d40; box-shadow: 0 1px 4px rgba(40,55,45,.09); }.workspace-grid { min-height: 590px; grid-template-columns: minmax(0, 1fr); }.mobile-hidden { display: none; }.course-rail, .partner-rail { min-height: 420px; }.workspace-heading { min-height: 64px; }.workspace-heading h1 { font-size: 17px; }.workspace-status { min-width: 88px; }.topbar { flex-wrap: wrap; }.icon-button { margin-left: 0; }.mode-tabs { flex: 1; } }
@media (max-width: 560px) { .workspace-heading { align-items: flex-start; }.workspace-heading span { max-width: 230px; }.workspace-status { padding: 8px 9px; }.workspace-status strong { font-size: 16px; }.main-panel { padding: 0 12px 12px; }.stage-label { margin-right: -12px; margin-left: -12px; }.fields, .node-fields { grid-template-columns: minmax(0, 1fr); }.fields .wide, .extension-toggle { grid-column: auto; }.node-editor { grid-template-columns: 26px minmax(0, 1fr); }.node-actions { grid-column: 2; flex-direction: row; }.timeline article { grid-template-columns: 24px minmax(0, 1fr); }.timeline-actions { grid-column: 2; flex-wrap: wrap; }.topbar .command { flex: 0 0 auto; }.mode-tabs button { padding: 0 8px; }.editor-footer { align-items: flex-start; gap: 10px; }.editor-footer span { max-width: 150px; }.object-stage { height: 390px; min-height: 390px; }.object-heading { min-height: 86px; flex-wrap: wrap; padding: 12px; }.object-heading h2 { font-size: 14px; }.object-status { max-width: 100%; }.document-reader, .experiment-object, .exercise-object { padding: 15px; }.document-reader p { font-size: 12px; }.object-provenance { align-items: flex-start; flex-direction: column; justify-content: center; padding: 8px 11px; }.object-tabs button { padding: 0 8px; } }
@media (max-width: 560px) { .evidence-check-grid { grid-template-columns: repeat(2,minmax(0,1fr)); }.evidence-source-list header { align-items: flex-start; flex-direction: column; } }
@media (max-width: 560px) { .artifact-dialog-backdrop { padding: 8px; }.artifact-dialog { width: calc(100vw - 16px); max-height: calc(100vh - 16px); }.artifact-dialog > header, .artifact-dialog > label, .artifact-dialog footer { padding-right: 12px; padding-left: 12px; }.artifact-dialog dl { grid-template-columns: 1fr; gap: 7px; padding-right: 12px; padding-left: 12px; }.artifact-dialog textarea { min-height: 240px; }.artifact-dialog footer { justify-content: stretch; }.artifact-dialog footer button { flex: 1; justify-content: center; } }

/* POST-UI-01: the workspace route is a focused, low-load "today learning" entry. */
.today-learning-page { max-width: 1180px; }
.today-learning-heading { display: flex; min-height: 96px; align-items: flex-end; justify-content: space-between; gap: 24px; padding: 12px var(--space-1) 24px; border-bottom: 1px solid var(--color-border); }
.today-learning-heading p, .today-section-heading p, .today-next-step p { margin: 0 0 7px; color: var(--color-text-muted); font-size: 14px; line-height: 1.5; }
.today-learning-heading h1 { margin: 0; color: var(--color-text); font-family: var(--font-heading); font-size: 30px; font-weight: 680; line-height: var(--line-height-heading); letter-spacing: 0; }
.today-learning-heading span { display: block; max-width: 650px; margin-top: 8px; overflow: hidden; color: var(--color-text-secondary); font-size: 15px; line-height: 1.5; text-overflow: ellipsis; white-space: nowrap; }
.today-progress { min-width: 110px; padding-left: 16px; border-left: 1px solid var(--color-border); }
.today-progress small, .today-progress strong { display: block; }
.today-progress small { color: var(--color-text-muted); font-size: 13px; }
.today-progress strong { margin-top: 5px; color: var(--color-text); font-size: 24px; font-weight: 680; }
.today-state { display: flex; min-height: 52px; align-items: center; gap: 9px; color: var(--color-text-secondary); font-size: 14px; }
.today-course-context { display: flex; align-items: center; justify-content: space-between; gap: 20px; padding: 22px 0; border-bottom: 1px solid var(--color-border); }
.today-course-context div { min-width: 0; }
.today-course-list { display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 10px 18px; margin-top: 6px; }
.today-course-list strong { min-width: 0; color: var(--color-text); font-size: 16px; font-weight: 650; }
.today-course-list small { margin-top: 3px; color: var(--color-text-secondary); font-size: 12px; font-weight: 400; }
.today-course-context span, .today-course-context strong, .today-course-context small { display: block; }
.today-course-context span { color: var(--color-text-muted); font-size: 13px; }
.today-course-context strong { margin-top: 4px; overflow: hidden; color: var(--color-text); font-size: 18px; font-weight: 650; text-overflow: ellipsis; white-space: nowrap; }
.today-course-context small { margin-top: 5px; color: var(--color-text-secondary); font-size: 14px; }
.today-course-context a, .today-quick-links a { color: var(--color-text-secondary); text-decoration: none; }
.today-course-context a { display: inline-flex; flex: 0 0 auto; align-items: center; gap: 7px; font-size: 14px; }
.today-course-context a:hover, .today-quick-links a:hover { color: var(--color-text); }
.today-learning-layout { display: grid; grid-template-columns: minmax(0, 1fr) 280px; gap: 28px; padding-top: 26px; }
.today-learning-main { min-width: 0; }
.today-focus { padding: 28px 32px 32px; border: 1px solid var(--color-border); border-radius: var(--radius-panel); background: var(--color-surface); }
.today-focus__eyebrow { display: flex; align-items: center; justify-content: space-between; gap: 12px; color: var(--color-text-muted); font-size: 13px; }
.today-focus__eyebrow b { padding: 4px 8px; color: var(--color-text-secondary); border: 1px solid var(--color-border); border-radius: var(--radius-control); background: var(--color-surface-subtle); font-size: 12px; font-weight: 600; }
.today-focus h2 { max-width: 740px; margin: 24px 0 12px; color: var(--color-text); font-family: var(--font-heading); font-size: 26px; font-weight: 680; line-height: var(--line-height-heading); }
.today-focus > p { max-width: 760px; margin: 0; color: var(--color-text-secondary); font-size: 15px; line-height: 1.65; }
.today-focus__facts { display: grid; gap: 8px; margin: 22px 0; padding-top: 16px; border-top: 1px solid var(--color-border); }
.today-focus__facts span { display: flex; align-items: flex-start; gap: 8px; color: var(--color-text-secondary); font-size: 14px; line-height: 1.5; }
.today-primary-action { display: inline-flex; min-height: 40px; align-items: center; justify-content: center; gap: 8px; padding: 0 15px; color: #fff; border: 1px solid var(--color-accent); border-radius: var(--radius-control); background: var(--color-accent); font-size: 14px; font-weight: 650; cursor: pointer; }
.today-primary-action:hover { background: var(--color-accent-hover); }
.today-primary-action:disabled { cursor: not-allowed; opacity: .55; }
.today-section-heading { display: flex; align-items: flex-end; justify-content: space-between; gap: 16px; margin: 36px 0 14px; padding-inline: var(--space-1); }
.today-section-heading h2 { margin: 0; color: var(--color-text); font-size: 20px; font-weight: 650; }
.today-section-heading > strong { color: var(--color-text-secondary); font-size: 14px; font-weight: 600; }
.today-task-list { overflow: hidden; border-top: 1px solid var(--color-border); border-bottom: 1px solid var(--color-border); background: var(--color-surface); }
.today-task-row { display: grid; grid-template-columns: 30px minmax(0, 1fr) minmax(175px, .5fr) auto; gap: 14px; align-items: center; min-height: 82px; padding: 14px var(--space-row-inline); border-bottom: 1px solid var(--color-border); }
.today-task-row:last-child { border-bottom: 0; }
.today-profile-reminder { display: grid; grid-template-columns: 30px minmax(0, 1fr) auto; gap: 14px; align-items: center; min-height: 76px; padding: 13px var(--space-row-inline); border-bottom: 1px solid #d9e3e7; background: #f1f7f8; }
.today-profile-reminder__mark { display: grid; width: 26px; height: 26px; place-items: center; color: #245965; border: 1px solid #a9c9d0; border-radius: 50%; background: #e8f3f5; }
.today-profile-reminder__body { min-width: 0; }
.today-profile-reminder__body strong, .today-profile-reminder__body small { display: block; }
.today-profile-reminder__body strong { color: #1f5360; font-size: 15px; }
.today-profile-reminder__body small { margin-top: 4px; color: #4a6971; font-size: 14px; line-height: 1.5; }
.today-profile-reminder__actions { display: flex; flex-wrap: wrap; gap: 6px; }
.today-profile-reminder__actions button { min-height: 32px; padding: 0 10px; color: #245965; border: 1px solid #a9c9d0; border-radius: 6px; background: #fff; font: 600 14px/1 var(--font-sans); cursor: pointer; }
.today-profile-reminder__actions button:first-child { color: #fff; border-color: #245965; background: #245965; }
.today-profile-reminder__actions button:disabled { cursor: wait; opacity: .6; }
.today-task-row__mark { display: grid; width: 26px; height: 26px; place-items: center; color: var(--color-text-secondary); border: 1px solid var(--color-border-strong); border-radius: 50%; font-size: 13px; }
.today-task-row.completed .today-task-row__mark { color: var(--color-accent); border-color: var(--color-accent); }
.today-task-row__body { min-width: 0; }
.today-task-row__body strong, .today-task-row__body small { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.today-task-row__body strong { color: var(--color-text); font-size: 15px; font-weight: 620; }
.today-task-row__body small { margin-top: 5px; color: var(--color-text-muted); font-size: 13px; }
.today-task-row__facts { display: grid; gap: 5px; color: var(--color-text-secondary); font-size: 13px; }
.today-task-row__facts span { display: flex; align-items: center; gap: 5px; }
.today-task-row button { display: inline-flex; align-items: center; gap: 5px; padding: 9px 4px 9px 12px; color: var(--color-text-secondary); border: 0; background: transparent; font-family: var(--font-sans); font-size: 14px; line-height: 1.4; cursor: pointer; }
.today-task-row button:hover { color: var(--color-text); }
.today-task-row button:disabled { cursor: default; opacity: .55; }
.today-task-complete { display: grid; grid-template-columns: 24px minmax(0, 1fr); gap: 3px 10px; align-items: center; padding: 20px var(--space-row-inline); color: var(--color-accent); }
.today-task-complete span { color: var(--color-text); font-size: 15px; font-weight: 620; }
.today-task-complete small { grid-column: 2; color: var(--color-text-secondary); font-size: 14px; }
.today-learning-rail { display: grid; align-content: start; gap: 20px; min-width: 0; }
.today-next-step { padding: 21px; border-left: 3px solid var(--color-accent); background: var(--color-surface-subtle); }
.today-next-step h2 { margin: 0 0 9px; color: var(--color-text); font-size: 19px; font-weight: 650; line-height: 1.4; }
.today-next-step > span { display: block; color: var(--color-text-secondary); font-size: 14px; line-height: 1.6; }
.today-next-step button { display: inline-flex; min-height: 38px; align-items: center; gap: 7px; margin-top: 18px; padding: 0 12px; color: var(--color-text); border: 1px solid var(--color-border-strong); border-radius: var(--radius-control); background: var(--color-surface); font-size: 14px; font-weight: 620; cursor: pointer; }
.today-next-step button:hover { border-color: var(--color-accent); }
.today-next-step button:disabled { cursor: not-allowed; opacity: .55; }
.today-quick-links { border-top: 1px solid var(--color-border); }
.today-quick-links a { display: grid; grid-template-columns: 20px minmax(0, 1fr) 14px; gap: 10px; align-items: center; min-height: 66px; border-bottom: 1px solid var(--color-border); }
.today-quick-links a > span { min-width: 0; }
.today-quick-links strong, .today-quick-links small { display: block; }
.today-quick-links strong { color: var(--color-text); font-size: 14px; font-weight: 620; }
.today-quick-links small { margin-top: 4px; overflow: hidden; color: var(--color-text-muted); font-size: 13px; text-overflow: ellipsis; white-space: nowrap; }
.today-empty { display: flex; min-height: 250px; align-items: center; gap: 15px; margin-top: 30px; padding: 30px; color: var(--color-text-secondary); border: 1px solid var(--color-border); border-radius: var(--radius-panel); background: var(--color-surface); }
.today-empty > div { flex: 1; }
.today-empty h2 { margin: 0; color: var(--color-text); font-size: 20px; }
.today-empty p { margin: 7px 0 0; font-size: 14px; }
@media (max-width: 980px) { .today-learning-layout { grid-template-columns: minmax(0, 1fr); }.today-learning-rail { grid-template-columns: repeat(2, minmax(0, 1fr)); }.today-quick-links { border-top: 0; } }
@media (max-width: 700px) { .today-learning-heading { align-items: flex-start; flex-direction: column; }.today-progress { padding-left: 0; border-left: 0; }.today-course-context { align-items: flex-start; flex-direction: column; }.today-task-row { grid-template-columns: 30px minmax(0, 1fr) auto; }.today-task-row__facts { grid-column: 2; }.today-task-row button { grid-column: 3; grid-row: 1 / span 2; }.today-profile-reminder { grid-template-columns: 30px minmax(0, 1fr); }.today-profile-reminder__actions { grid-column: 2; }.today-learning-rail { grid-template-columns: minmax(0, 1fr); }.today-empty { align-items: flex-start; flex-wrap: wrap; }.today-empty .today-primary-action { flex-basis: 100%; } }

/* FB-FE-01: give the primary learning surface more room than its rails. */
.workspace-grid {
  grid-template-columns: minmax(190px, 20%) minmax(0, 1fr) minmax(210px, 21%);
  gap: 18px;
}

.today-learning-page {
  max-width: 1320px;
}

.today-learning-layout {
  grid-template-columns: minmax(0, 1fr) 236px;
  gap: 32px;
}

@media (max-width: 1180px) {
  .workspace-grid {
    grid-template-columns: minmax(180px, 19%) minmax(0, 1fr) minmax(200px, 20%);
  }
}

@media (max-width: 900px) {
  .workspace-grid {
    grid-template-columns: minmax(0, 1fr);
  }

  .today-learning-layout {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
