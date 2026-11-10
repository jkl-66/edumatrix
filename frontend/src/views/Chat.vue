<script setup>
import { displayLabel, learningText } from '../utils/learningCopy.js'
import { userMessage } from '../services/errorTranslator.js'
import { groupSourcePassages, passagePreview, sourcePassageKey } from '../utils/sourceCitationRoute.js'
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  AlertCircle,
  Archive,
  BookOpen,
  CheckCircle2,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  ChevronUp,
  Clock3,
  ExternalLink,
  File,
  FileText,
  Image as ImageIcon,
  Library,
  ListChecks,
  LoaderCircle,
  MessageSquareText,
  Network,
  Paperclip,
  Plus,
  RefreshCw,
  Send,
  Sparkles,
  Square,
  X,
} from '@lucide/vue'
import { getM5Resource } from '../api'
import AgentTimeline from '../components/AgentTimeline.vue'
import InlineQuizCard from '../components/InlineQuizCard.vue'
import IncrementalMarkdownRenderer from '../components/IncrementalMarkdownRenderer.vue'
import ReadAloudButton from '../components/ReadAloudButton.vue'
import { useLearningPreferences } from '../services/learningPreferences'
import SourceCitation from '../components/SourceCitation.vue'
import SearchField from '../components/ui/SearchField.vue'
import { useChatStore } from '../stores/chat'
import { useCourseContextStore } from '../stores/courseContext'

const route = useRoute()
const router = useRouter()
const chatStore = useChatStore()
const courseContext = useCourseContextStore()

const draft = ref('')
const initializing = ref(true)
const switchingConversation = ref(false)
const fileInput = ref(null)
const preferences = useLearningPreferences()
const messageScroller = ref(null)
const activeEvidenceMessageId = ref('')
const localError = ref('')
const coursePickerOpen = ref(false)
const pendingCourseIds = ref([])
const courseSearch = ref('')
const attachmentsCollapsed = ref(false)
const courseSelectionError = ref('')
const routeResourceMessageStarted = ref(false)
const resourcePickerOpen = ref(false)
const selectedResourceTypes = ref([])
const resourceSourceMessageId = ref('')
const quizLoading = ref(false)
const quizError = ref('')
const quizDetail = ref(null)
const evidenceTab = ref('course')
const evidenceRailCollapsed = ref(true)

const messages = computed(() => chatStore.messages)
const conversations = computed(() => chatStore.conversations)
const visibleAttachments = computed(() => chatStore.attachments.filter((item) => item.status !== 'removed'))
const removedAttachments = computed(() => chatStore.attachments.filter((item) => item.status === 'removed'))
const uploading = computed(() => Object.values(chatStore.attachmentActions).some((value) => value === 'uploading'))
const routeCourseIds = computed(() => {
  const raw = route.query.course_ids || route.query.course_id || ''
  const values = Array.isArray(raw) ? raw : String(raw).split(',')
  return [...new Set(values.map((value) => String(value || '').trim()).filter(Boolean))]
})
const resourceIntent = computed(() => {
  const value = cleanQueryValue(route.query.intent)
  return value === 'resource_generation' || value === 'path_bundle' ? value : ''
})
const routeResourceTypes = computed(() => {
  const raw = route.query.resource_types || route.query.resourceTypes || ''
  const values = Array.isArray(raw) ? raw : String(raw).split(',')
  return [...new Set(values.map((value) => String(value || '').trim()).filter(Boolean))]
})
const resourceTypeLabels = {
  handout: '个性化讲义',
  mind_map: '思维导图',
  quiz: '测验题',
  training_task: '实训任务书',
  code_sandbox: '代码沙盒',
  video: '视频推荐',
  deck: 'PPT/网页课件',
  interactive_model: '可交互模型',
  feynman: '费曼复述',
}
const allResourceTypes = Object.keys(resourceTypeLabels)
const effectiveResourceTypes = computed(() => {
  const selected = routeResourceTypes.value.filter((type) => allResourceTypes.includes(type))
  return selected.length ? selected : (resourceIntent.value ? allResourceTypes : [])
})
const routeSourceRefIds = computed(() => {
  const raw = route.query.source_ref_ids || route.query.sourceRefIds || ''
  const values = Array.isArray(raw) ? raw : String(raw).split(',')
  const singular = cleanQueryValue(route.query.source_ref_id || route.query.sourceRefId)
  return [...new Set([...values, singular].map((value) => String(value || '').trim()).filter(Boolean))]
})
const resourceMessageTitle = computed(() => (
  cleanQueryValue(route.query.knowledge_point_title)
  || cleanQueryValue(route.query.resource_title)
  || cleanQueryValue(route.query.title)
  || currentKnowledgePointTitle.value
  || currentCourseTitle.value
))
const resourceMessageText = computed(() => {
  const supplied = cleanQueryValue(route.query.prompt || route.query.message)
  if (supplied) return supplied.slice(0, 50000)
  const labels = effectiveResourceTypes.value.map((type) => resourceTypeLabels[type]).join('、')
  if (resourceIntent.value === 'path_bundle') {
    return `请帮我一键生成“${resourceMessageTitle.value}”的完整资源包（${labels}）。请结合当前课程资料、学习路径和我的学习情况生成，并在过程中展示协作步骤。`
  }
  return `请基于当前课程“${currentCourseTitle.value}”和已选资料，帮我定制生成${labels}，主题围绕“${resourceMessageTitle.value}”。请根据我的学习情况控制难度，并在生成过程中展示规划、协作和审核步骤。`
})
const resourceMessageContextRefs = computed(() => outgoingContextRefs.value)
const selectedCourseIds = computed(() => chatStore.selectedCourseIds)
const selectedCourses = computed(() => selectedCourseIds.value
  .map((id) => chatStore.availableCourses.find((course) => String(course.id) === String(id)))
  .filter(Boolean))
const displayCourseIds = computed(() => (coursePickerOpen.value ? pendingCourseIds.value : selectedCourseIds.value))
const displayCourses = computed(() => displayCourseIds.value
  .map((id) => chatStore.availableCourses.find((course) => String(course.id) === String(id)))
  .filter(Boolean))
const recentCourseIds = computed(() => {
  const ids = []
  for (const conversation of conversations.value) {
    for (const course of conversation?.courses || []) {
      const id = String(course?.id || '').trim()
      if (id && !ids.includes(id)) ids.push(id)
    }
    const fallback = String(conversation?.courseId || '').trim()
    if (fallback && !ids.includes(fallback)) ids.push(fallback)
  }
  return ids
})
const filteredCourseOptions = computed(() => {
  const query = courseSearch.value.trim().toLowerCase()
  if (!query) return chatStore.availableCourses
  return chatStore.availableCourses.filter((course) => (
    String(course.title || '').toLowerCase().includes(query)
    || String(course.subject || '').toLowerCase().includes(query)
  ))
})
const recentCourseOptions = computed(() => {
  if (courseSearch.value.trim()) return []
  const byId = new Map(chatStore.availableCourses.map((course) => [String(course.id), course]))
  return recentCourseIds.value.map((id) => byId.get(id)).filter(Boolean).slice(0, 5)
})
const otherCourseOptions = computed(() => {
  const recent = new Set(recentCourseOptions.value.map((course) => String(course.id)))
  return filteredCourseOptions.value.filter((course) => !recent.has(String(course.id)))
})
const effectiveCourseIds = computed(() => selectedCourseIds.value.length
  ? selectedCourseIds.value
  : routeCourseIds.value)
const currentCourseId = computed(() => String(effectiveCourseIds.value[0] || ''))
const currentCourseTitle = computed(() => {
  if (displayCourses.value.length === 1) return displayCourses.value[0].title
  if (displayCourses.value.length > 1) return `已选择 ${displayCourses.value.length} 门课程`
  return '未绑定课程（通用对话）'
})
const courseSelectionLabel = computed(() => {
  if (chatStore.loadingCourses) return '正在加载课程…'
  if (displayCourses.value.length === 1) return displayCourses.value[0].title
  if (displayCourses.value.length > 1) return `已选择 ${displayCourses.value.length} 门课程`
  return '通用对话（未绑定课程）'
})
const conversationContextRef = computed(() => {
  // An entry from another learning page supplies its own scope. Omitted fields
  // must stay empty, even when we reuse a conversation for the same course.
  if (!route.query.conversation_id && [
    'intent', 'chapter_id', 'knowledge_point_id', 'task_id', 'resource_id',
    'quiz_resource_id', 'source_ref_id', 'source_ref_ids', 'attempt_id',
  ].some(key => route.query[key])) return {}
  const previousQuestion = [...messages.value].reverse().find(message => message.role === 'user')
  const previous = previousQuestion?.contextRefs?.find(item => item.context?.courseId === currentCourseId.value)
  return previous?.context || {}
})
const currentKnowledgePointId = computed(() => String(
  route.query.knowledge_point_id
  || conversationContextRef.value.knowledgePointId
  || '',
))
const currentKnowledgePointTitle = computed(() => (
  currentKnowledgePointId.value
    ? (cleanQueryValue(route.query.knowledge_point_title)
      || messages.value.findLast(message => message.role === 'user')?.contextRefs?.find(item => item.knowledgePoint?.id === currentKnowledgePointId.value)?.knowledgePoint?.title
      || '当前知识点')
    : currentCourseTitle.value
))

const selectedAttachmentCount = computed(() => chatStore.selectedAttachments.length)
const attachmentQueueSummary = computed(() => {
  const count = visibleAttachments.value.length
  const selected = selectedAttachmentCount.value
  const processing = visibleAttachments.value.filter((item) => ['queued', 'parsing'].includes(item.status)).length
  const failed = visibleAttachments.value.filter((item) => ['failed', 'failed_retryable', 'partial_failed'].includes(item.status)).length
  const parts = [`${count} 个附件`]
  if (selected) parts.push(`${selected} 个将随本次发送`)
  if (processing) parts.push(`${processing} 个处理中`)
  if (failed) parts.push(`${failed} 个需要处理`)
  return parts.join(' · ')
})
const hasDraftContent = computed(() => Boolean(draft.value.trim() || selectedAttachmentCount.value))
const conversationBusy = computed(() => initializing.value || switchingConversation.value || chatStore.creatingConversation || chatStore.loading)
const sendDisabledReason = computed(() => {
  if (conversationBusy.value) return '正在打开对话'
  if (chatStore.submitting) return '正在发送问题'
  if (chatStore._pendingRetry) return '等待连接恢复'
  if (chatStore.sending) return '当前回答尚未结束'
  if (chatStore.attachmentBlockReason) return chatStore.attachmentBlockReason
  if (resourceSourceMessageId.value && !selectedResourceTypes.value.length) return '请选择要生成的资源'
  if (!hasDraftContent.value) return '请输入问题或添加附件'
  return ''
})
const canSend = computed(() => !sendDisabledReason.value)

watch(() => chatStore.activeConversationId, () => {
  attachmentsCollapsed.value = false
  resourceSourceMessageId.value = ''
})

const latestAssistant = computed(() => (
  [...messages.value].reverse().find((message) => message.role === 'assistant') || null
))
const evidenceMessage = computed(() => (
  messages.value.find((message) => message.id === activeEvidenceMessageId.value)
  || latestAssistant.value
  || [...messages.value].reverse()[0]
  || null
))
const evidenceContextRefs = computed(() => evidenceMessage.value?.contextRefs || [])
const evidenceSourceRefs = computed(() => evidenceMessage.value?.sourceRefs || [])
const evidenceSourceGroups = computed(() => groupSourcePassages(evidenceSourceRefs.value))
const evidenceCandidateSourceRefs = computed(() => {
  const explicit = evidenceMessage.value?.streamCheckpoint?.candidateSourceRefs
  if (Array.isArray(explicit)) return explicit
  return evidenceSourceRefs.value.filter((source) => (
    source?.selection === 'candidate' || source?.available === false
  ))
})
const evidenceResourceLinks = computed(() => evidenceMessage.value?.resourceLinks || [])
const evidenceAttachments = computed(() => messageAttachments(evidenceMessage.value))
const evidenceReturnTo = computed(() => String(evidenceMessage.value?.streamCheckpoint?.returnTo || ''))
const evidenceAgentAudit = computed(() => messageAgentAudit(evidenceMessage.value))
const evidenceRunEvents = computed(() => (
  evidenceMessage.value?.runEvents
  || evidenceMessage.value?.streamCheckpoint?.runEvents
  || evidenceAgentAudit.value?.events
  || []
))
const evidenceProfileAdaptation = computed(() => {
  const snapshot = evidenceMessage.value?.contextSnapshot || evidenceMessage.value?.streamCheckpoint?.contextSnapshot || {}
  return snapshot.profile_adaptation_plan || snapshot.profile_context || null
})
const evidenceProfileAdaptationSummary = computed(() => {
  const snapshot = evidenceMessage.value?.contextSnapshot || evidenceMessage.value?.streamCheckpoint?.contextSnapshot || {}
  return snapshot.profile_adaptation_summary || evidenceProfileAdaptation.value?.summary || ''
})
const evidenceClaims = computed(() => (
  evidenceMessage.value?.claims
  || evidenceMessage.value?.streamCheckpoint?.claims
  || []
))
const evidenceResourceJob = computed(() => evidenceMessage.value?.resourceJob || null)

const quizResourceId = computed(() => String(route.query.quiz_resource_id || ''))
const quizProjection = computed(() => quizDetail.value?.quiz?.current || null)
const quizQuestions = computed(() => quizProjection.value?.questions || [])
const quizQuestion = computed(() => {
  const requested = String(route.query.question_version_id || '')
  return quizQuestions.value.find((item) => item.id === requested) || quizQuestions.value[0] || null
})
const quizSourceRefs = computed(() => quizProjection.value?.source_refs || [])
const quizTitle = computed(() => (
  quizProjection.value?.structured?.title
  || quizDetail.value?.catalog?.title
  || '当前测验题'
))
const quizQuestionPosition = computed(() => {
  const index = quizQuestions.value.findIndex((item) => item.id === quizQuestion.value?.id)
  return index >= 0 ? index + 1 : 0
})
const quizResourceLocation = computed(() => ({
  path: `/workspace/resources/quizzes/${encodeURIComponent(quizResourceId.value)}`,
  query: {
    question_version_id: quizQuestion.value?.id || cleanQueryValue(route.query.question_version_id) || undefined,
    course_id: currentCourseId.value || undefined,
  },
}))

const outgoingContextRef = computed(() => {
  const inherited = conversationContextRef.value
  const quizSource = quizSourceRefs.value[0]
  const value = {
    courseId: currentCourseId.value || null,
    chapterId: route.query.chapter_id || inherited.chapterId || null,
    knowledgePointId: currentKnowledgePointId.value || null,
    taskId: route.query.task_id || inherited.taskId || null,
    resourceId: quizResourceId.value || route.query.resource_id || inherited.resourceId || null,
    resourceVersionId: route.query.version_id || inherited.resourceVersionId || null,
    resourcePartId: route.query.resource_part_id || route.query.slide_id || route.query.node_id || inherited.resourcePartId || null,
    sourceRefId: route.query.source_ref_id || quizSource?.id || inherited.sourceRefId || null,
    attemptId: route.query.attempt_id || inherited.attemptId || null,
  }
  return value.courseId ? value : null
})
const outgoingContextRefs = computed(() => {
  const ids = effectiveCourseIds.value
  if (!ids.length) return []
  const base = outgoingContextRef.value
  if (base) {
    const primary = routeSourceRefIds.value.length
      ? routeSourceRefIds.value.map((sourceRefId) => ({ ...base, sourceRefId }))
      : [base]
    return [...primary, ...ids.slice(1).map((courseId) => ({ courseId }))]
  }
  return ids.map((courseId) => ({ courseId }))
})
const outgoingReturnTo = computed(() => {
  const requested = String(route.query.return_to || '')
  if (isInternalPath(requested)) return requested
  if (quizResourceId.value) {
    const query = new URLSearchParams()
    if (route.query.question_version_id) query.set('question_version_id', String(route.query.question_version_id))
    const suffix = query.toString() ? `?${query.toString()}` : ''
    return `/workspace/resources/quizzes/${encodeURIComponent(quizResourceId.value)}${suffix}`
  }
  return ''
})

const resourceOptions = [
  { type: 'handout', label: '个性化讲义', icon: FileText },
  { type: 'mind_map', label: '思维导图', icon: Network },
  { type: 'quiz', label: '测验题', icon: ListChecks },
  { type: 'training_task', label: '实训任务书', icon: BookOpen },
  { type: 'code_sandbox', label: '代码沙盒', icon: File },
  { type: 'video', label: '视频推荐', icon: ImageIcon },
  { type: 'deck', label: 'PPT/网页课件', icon: Library },
  { type: 'interactive_model', label: '可交互模型', icon: Network },
  { type: 'feynman', label: '费曼复述任务', icon: MessageSquareText },
]

const composerResourceTypes = computed(() => (
  selectedResourceTypes.value.filter((type) => allResourceTypes.includes(type))
))
const composerPlaceholder = computed(() => {
  if (!composerResourceTypes.value.length) return '输入你的问题'
  const labels = composerResourceTypes.value.map((type) => resourceTypeLabels[type]).join('、')
  return `请描述你希望生成的${labels}，例如：请用入门方式讲解当前章节并结合我的学习情况设计练习`
})

function isInternalPath(value) {
  return Boolean(value && value.startsWith('/') && !value.startsWith('//'))
}

function cleanQueryValue(value) {
  return Array.isArray(value) ? String(value[0] || '') : String(value || '')
}

function stableHash(value) {
  let hash = 2166136261
  for (const character of String(value || '')) {
    hash ^= character.codePointAt(0)
    hash = Math.imul(hash, 16777619)
  }
  return (hash >>> 0).toString(36)
}

const resourceMessageIdempotencyKey = computed(() => {
  const requested = cleanQueryValue(route.query.idempotency_key || route.query.request_id)
  if (requested) {
    // The route request id is stable for refresh/reconnect, while the active
    // conversation scopes the actual canonical message pair. This prevents a
    // previous conversation using the same daily path request from blocking
    // the current Chat entry with a cross-conversation idempotency conflict.
    const conversationId = String(chatStore.activeConversationId || '').trim() || 'pending'
    return `${requested}:${conversationId}`.slice(0, 128)
  }
  if (!resourceIntent.value) return ''
  const parts = [
    resourceIntent.value,
    ...effectiveCourseIds.value,
    cleanQueryValue(route.query.chapter_id),
    cleanQueryValue(route.query.knowledge_point_id),
    cleanQueryValue(route.query.path_id),
    cleanQueryValue(route.query.task_id),
    ...effectiveResourceTypes.value,
    ...routeSourceRefIds.value,
  ]
  return `chat-auto-${stableHash(parts.join('|'))}`
})

function conversationCourseLabel(conversation) {
  const courses = conversation?.courses || []
  if (courses.length === 1) return courses[0].title || courses[0].id
  if (courses.length > 1) return `已选择 ${courses.length} 门课程`
  if (conversation?.courseId) {
    const course = chatStore.availableCourses.find((item) => String(item.id) === String(conversation.courseId))
    return course?.title || String(conversation.courseId)
  }
  return '通用对话 · 未绑定课程'
}

function syncSelectedCourses(ids) {
  const next = chatStore.setSelectedCourseIds(ids)
  courseContext.setChatCourseIds(next)
  return next
}

function openCoursePicker() {
  pendingCourseIds.value = [...selectedCourseIds.value]
  courseSearch.value = ''
  resourcePickerOpen.value = false
  coursePickerOpen.value = !coursePickerOpen.value
}

function toggleCourse(courseId) {
  const current = new Set(pendingCourseIds.value)
  if (current.has(courseId)) current.delete(courseId)
  else current.add(courseId)
  pendingCourseIds.value = [...current]
  courseSelectionError.value = ''
}

async function finishCourseSelection() {
  const next = [...pendingCourseIds.value]
  const previous = [...selectedCourseIds.value]
  if (next.join(',') === previous.join(',')) {
    coursePickerOpen.value = false
    return
  }
  if (chatStore.sending) {
    courseSelectionError.value = '当前回答进行中，请完成或停止后再切换课程'
    return
  }
  try {
    const first = next[0] || ''
    const course = chatStore.availableCourses.find((item) => String(item.id) === first)
    const conversation = await chatStore.createConversation({
      courseId: first,
      courseIds: next,
      title: course?.title ? `${course.title}对话` : '通用对话',
    })
    // The create response normally echoes the authorized course IDs. Keep the
    // just-committed selection visible even when an older compatible response
    // only returns the conversation shell.
    chatStore.setSelectedCourseIds(next)
    courseContext.setChatCourseIds(next)
    coursePickerOpen.value = false
    courseSelectionError.value = ''
    await activateConversation(conversation)
  } catch (error) {
    courseSelectionError.value = error?.message || '切换课程失败，请重试'
  }
}

async function useGeneralChat() {
  pendingCourseIds.value = []
  await finishCourseSelection()
  coursePickerOpen.value = false
}

function courseIsSelected(courseId) {
  return pendingCourseIds.value.includes(String(courseId))
}

async function redirectLegacyWorkbench() {
  if (route.query.quiz_follow_up) return false
  const tab = cleanQueryValue(route.query.tab).toLowerCase()
  if (tab === 'websearch' || tab === 'search' || route.query.websearch) {
    await router.replace({
      path: '/knowledge/discover',
      query: { course_id: currentCourseId.value || undefined, compat: 'legacy-route' },
    })
    return true
  }
  if (tab === 'code' || route.query.q) {
    const resourceId = cleanQueryValue(route.query.code_resource_id || route.query.resource_id)
    await router.replace(resourceId
      ? { path: `/workspace/code/${encodeURIComponent(resourceId)}`, query: { course_id: currentCourseId.value || undefined, compat: 'legacy-route' } }
      : { path: '/workspace/resources', query: { type: 'code_sandbox', search: cleanQueryValue(route.query.q), compat: 'legacy-route' } })
    return true
  }
  if (tab === 'quiz' || route.query.quiz) {
    const resourceId = cleanQueryValue(route.query.quiz_resource_id)
    await router.replace(resourceId
      ? {
          path: `/workspace/resources/quizzes/${encodeURIComponent(resourceId)}`,
          query: {
            question_version_id: cleanQueryValue(route.query.question_version_id) || undefined,
            course_id: currentCourseId.value || undefined,
            compat: 'legacy-route',
          },
        }
      : { path: '/workspace/resources', query: { type: 'quiz', search: cleanQueryValue(route.query.quiz), compat: 'legacy-route' } })
    return true
  }
  return false
}

function formatTime(value) {
  if (!value) return '刚刚'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '刚刚'
  const now = new Date()
  const sameDay = date.toDateString() === now.toDateString()
  return new Intl.DateTimeFormat('zh-CN', sameDay
    ? { hour: '2-digit', minute: '2-digit' }
    : { month: '2-digit', day: '2-digit' }).format(date)
}

function formatBytes(value) {
  const bytes = Number(value || 0)
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function resourceAutomation(message) {
  return message?.resourceAutomation || message?.streamCheckpoint?.resourceAutomation || {}
}

function statusText(message) {
  if (message?.resourceJobId) {
    const automation = resourceAutomation(message)
    const labels = {
      queued: '排队准备', running: '正在准备资源',
      retry_wait: automation.phase === 'repairing' ? '正在调整内容' : '等待自动继续',
      waiting_configuration: '等待服务恢复', needs_attention: '生成遇到问题',
      completed: '资源已就绪', cancelled: '已取消生成',
    }
    if (labels[automation.state]) return labels[automation.state]
    if (['succeeded', 'completed'].includes(message.resourceStatus)) return '资源已就绪'
    return ['failed', 'stopped'].includes(message.status) ? '资源尚未就绪' : '正在准备资源'
  }
  const labels = {
    queued: '等待回答',
    streaming: '正在回答',
    completed: '回答完成',
    stopped: '已停止',
    failed: '回答失败',
    needs_input: '等待补充信息',
  }
  return labels[message?.status] || '状态未记录'
}

function attachmentStatus(item) {
  const labels = {
    queued: '等待解析',
    parsing: '正在解析',
    ready: '可发送',
    partial_failed: item.partialConfirmed ? '已确认可用部分' : '部分解析失败',
    failed: '解析失败',
    failed_retryable: '失败可重试',
    removed: '已移除',
  }
  return labels[item.status] || '状态未知'
}

function attachmentIcon(item) {
  if (['png', 'jpg', 'jpeg', 'webp'].includes(item.fileFormat)) return ImageIcon
  if (item.fileFormat === 'pptx') return Library
  if (['pdf', 'docx', 'md', 'txt'].includes(item.fileFormat)) return FileText
  return File
}

function attachmentSummary(item) {
  const summary = item.summary || {}
  if (summary.page_count) return `${summary.page_count} 页`
  if (summary.slide_count) return `${summary.slide_count} 张幻灯片`
  if (summary.paragraph_count) return `${summary.paragraph_count} 个段落`
  if (summary.width && summary.height) return `${summary.width} x ${summary.height}`
  return formatBytes(item.fileSize)
}

function messageAttachments(message) {
  if (!message?.attachmentIds?.length) return []
  const ids = new Set(message.attachmentIds)
  return chatStore.attachments.filter((item) => ids.has(item.id))
}

function contextRows(refs) {
  const rows = []
  for (const item of refs || []) {
    for (const [key, label] of [
      ['course', '课程'],
      ['chapter', '章节'],
      ['knowledgePoint', '知识点'],
      ['task', '学习任务'],
      ['resource', '学习资源'],
      ['attempt', '作答记录'],
    ]) {
      const value = item?.[key]
      if (value?.id) rows.push({ key: `${key}-${value.id}`, label, title: value.title || value.id, status: value.status || '' })
    }
  }
  return rows
}

function showMessageEvidence(message, tab) {
  activeEvidenceMessageId.value = message.id
  evidenceTab.value = tab
  evidenceRailCollapsed.value = false
}

function openQuizSource(sourceId) {
  const source = quizSourceRefs.value.find((item) => item.id === sourceId) || quizSourceRefs.value[0]
  if (!source) return
  const documentId = source.source_document_id || source.document_id
  if (documentId) {
    router.push({
      path: `/knowledge/documents/${encodeURIComponent(documentId)}`,
      query: { course_id: currentCourseId.value || undefined, source_ref_id: source.id, return_to: route.fullPath },
    })
    return
  }
  openSource({ ...source, sourceRefId: source.id, courseId: currentCourseId.value })
}

function quizSourceTitle(source, index) {
  return source?.title || source?.document_title || source?.filename || source?.locator || `课程来源 ${index + 1}`
}

function openQuizResource() {
  if (quizResourceId.value) router.push(quizResourceLocation.value)
}

function handleQuizSubmitted(result) {
  if (quizQuestion.value && result) quizQuestion.value.latest_attempt = result
}

async function handleQuizFollowUp(payload) {
  const text = String(payload?.text || '').trim()
  if (!text) return
  localError.value = ''
  try {
    if (!chatStore.activeConversationId && currentCourseId.value) {
      await chatStore.createConversation({
        courseId: currentCourseId.value,
        courseIds: effectiveCourseIds.value,
        title: quizTitle.value,
      })
    }
    const question = payload.question || quizQuestion.value
    const source = quizSourceRefs.value[0]
    const questionContext = {
      courseId: currentCourseId.value || null,
      knowledgePointId: question?.primary_knowledge_point_id || quizProjection.value?.structured?.knowledgePoint?.id || currentKnowledgePointId.value || null,
      resourceId: quizResourceId.value || null,
      sourceRefId: source?.id || source?.source_ref_id || null,
      attemptId: payload.attempt?.id || null,
    }
    const contextRefs = effectiveCourseIds.value.length
      ? [questionContext, ...effectiveCourseIds.value.slice(1).map((courseId) => ({ courseId }))]
      : []
    await chatStore.sendMessage({
      content: text,
      contextRefs,
      returnTo: outgoingReturnTo.value,
    })
  } catch (error) {
    localError.value = error?.message || '追问发送失败，当前题目仍已保留'
  }
}

function openResourceLink(link, message = evidenceMessage.value) {
  if (!isInternalPath(link?.route)) return
  const target = router.resolve(link.route)
  const context = message?.contextRefs?.[0]?.context || {}
  router.push({ path: target.path, query: {
    ...target.query,
    course_id: context.courseId || currentCourseId.value || undefined,
    knowledge_point_id: context.knowledgePointId || undefined,
    task_id: context.taskId || undefined,
    version_id: link.resourceVersionId || undefined,
  } })
}

function openReturnPath() {
  if (isInternalPath(evidenceReturnTo.value)) router.push(evidenceReturnTo.value)
}

function openCourseKnowledge() {
  if (!currentCourseId.value) return
  router.push({
    path: `/knowledge/courses/${encodeURIComponent(currentCourseId.value)}`,
    query: { return_to: route.fullPath },
  })
}

function messageAgentAudit(message) {
  const audit = message?.agentAudit || message?.streamCheckpoint?.agentAudit || null
  if (!message?.resourceJobId) return audit
  const events = message.runEvents || message.streamCheckpoint?.runEvents || []
  if (!events.length) return null
  const state = resourceAutomation(message).state
  const status = { retry_wait: 'running', needs_attention: 'failed', cancelled: 'stopped' }[state] || state || audit?.status
  return { ...audit, status, events, items: [] }
}

function workflowEventCount(message) {
  return message?.runEvents?.length
    || message?.streamCheckpoint?.runEvents?.length
    || messageAgentAudit(message)?.events?.length
    || 0
}

function messageGroundingLevel(message) {
  return String(
    message?.orchestration?.groundingLevel
      || message?.streamCheckpoint?.orchestration?.groundingLevel
      || '',
  ).toUpperCase()
}

function conversationQuery(conversation) {
  const ids = Array.isArray(conversation?.courseIds) ? conversation.courseIds : (conversation?.courseId ? [conversation.courseId] : [])
  const query = { conversation_id: conversation.id }
  if (ids.length) {
    query.course_id = ids[0]
    query.course_ids = ids.join(',')
  }
  const latest = [...(conversation.messages || [])].reverse().find(message => message.role === 'user')
  const context = latest?.contextRefs?.[0]?.context || {}
  if (ids.includes(context.courseId)) {
    for (const [key, field] of Object.entries({ chapter_id: 'chapterId', knowledge_point_id: 'knowledgePointId',
      resource_id: 'resourceId', version_id: 'resourceVersionId', resource_part_id: 'resourcePartId',
      source_ref_id: 'sourceRefId', task_id: 'taskId', attempt_id: 'attemptId' })) {
      if (context[field]) query[key] = context[field]
    }
    const sourceIds = [...new Set((latest.contextRefs || [])
      .filter(item => item.context?.courseId === context.courseId)
      .map(item => item.context?.sourceRefId).filter(Boolean))]
    if (sourceIds.length > 1) {
      delete query.source_ref_id
      query.source_ref_ids = sourceIds.join(',')
    }
    if (isInternalPath(latest.returnTo)) query.return_to = latest.returnTo
  }
  return query
}

async function activateConversation(conversation) {
  switchingConversation.value = true
  const previousPath = route.fullPath
  courseContext.clear({ keepCourse: false })
  activeEvidenceMessageId.value = ''
  try {
    await router.replace({ path: '/learn', query: conversationQuery(conversation) })
  } finally {
    // A changed route remounts this workspace. Keep the departing composer
    // disabled so a new draft cannot be entered and lost during that change.
    if (route.fullPath === previousPath) switchingConversation.value = false
  }
}

async function createConversation() {
  if (conversationBusy.value) return
  localError.value = ''
  try {
    const conversation = await chatStore.createConversation({
      courseId: effectiveCourseIds.value[0] || '',
      courseIds: effectiveCourseIds.value,
      title: '新对话',
    })
    draft.value = ''
    activeEvidenceMessageId.value = ''
    await activateConversation(conversation)
  } catch (error) {
    localError.value = error?.message || '新建对话失败'
  }
}

async function openConversation(conversationId) {
  if (!conversationId || conversationId === chatStore.activeConversationId) return
  localError.value = ''
  try {
    const conversation = await chatStore.openConversation(conversationId)
    await activateConversation(conversation)
  } catch (error) {
    localError.value = error?.message || '打开对话失败'
  }
}

async function archiveConversation(conversationId) {
  localError.value = ''
  try {
    await chatStore.archiveConversation(conversationId)
    if (String(route.query.conversation_id || '') === conversationId && chatStore.activeConversation) {
      await activateConversation(chatStore.activeConversation)
    }
  } catch (error) {
    localError.value = error?.message || '归档对话失败'
  }
}

async function chooseFiles(event) {
  const files = [...(event.target.files || [])]
  event.target.value = ''
  if (conversationBusy.value) {
    localError.value = '对话还在加载，请稍后重新选择附件。'
    return
  }
  for (const file of files) {
    if (!preferences.imageAnalysis && (file.type.startsWith('image/') || /\.(png|jpe?g|webp)$/i.test(file.name))) {
      localError.value = '图片理解已关闭，可以在设置中开启后再上传。'
      continue
    }
    try {
      await chatStore.uploadAttachment(file)
    } catch {
      // The store keeps the sanitized file-specific error and refreshes server truth.
    }
  }
}

async function retryAttachment(attachmentId) {
  try {
    await chatStore.retryAttachment(attachmentId)
  } catch {
    // The store keeps the sanitized failure for the row.
  }
}

async function confirmPartialAttachment(attachmentId) {
  try {
    await chatStore.confirmPartialAttachment(attachmentId)
  } catch {
    // The store keeps the sanitized failure for the row.
  }
}

async function removeAttachment(attachmentId) {
  try {
    await chatStore.removeAttachment(attachmentId)
  } catch {
    // The store keeps the sanitized failure for the row.
  }
}

function reselectAttachments() {
  fileInput.value?.click()
}

async function sendMessage(intentOverride = '') {
  if (!canSend.value) return
  localError.value = ''
  try {
    const resourceTypes = [...composerResourceTypes.value]
    const intent = intentOverride || (resourceTypes.length ? 'resource_generation' : 'chat')
    const pair = await chatStore.sendMessage({
      content: draft.value,
      contextRefs: intent === 'general_qa' ? [] : outgoingContextRefs.value,
      returnTo: outgoingReturnTo.value,
      intent,
      resourceTypes: intent === 'general_qa' ? [] : resourceTypes,
      sourceMessageId: intent === 'resource_generation' ? resourceSourceMessageId.value : '',
    })
    if (pair) {
      draft.value = ''
      selectedResourceTypes.value = []
      resourceSourceMessageId.value = ''
      resourcePickerOpen.value = false
    }
    await nextTick()
    scrollToBottom()
  } catch (error) {
    localError.value = error?.message || '发送失败，问题已保留'
  }
}

async function continueWithGeneralKnowledge(message) {
  resourceSourceMessageId.value = ''
  const userMessage = messages.value.find((item) => item.id === message?.replyToMessageId)
  const question = String(userMessage?.content || '').trim()
  draft.value = question
    ? `请用通用知识继续回答这个问题：\n${question}`
    : '请用通用知识继续回答。'
  selectedResourceTypes.value = []
  resourcePickerOpen.value = false
  await sendMessage('general_qa')
}

function toggleResourceType(type) {
  const current = new Set(composerResourceTypes.value)
  if (current.has(type)) current.delete(type)
  else current.add(type)
  selectedResourceTypes.value = resourceOptions
    .map((option) => option.type)
    .filter((value) => current.has(value))
}

function selectAllResourceTypes() {
  selectedResourceTypes.value = resourceOptions.map((option) => option.type)
}

function clearResourceTypes() {
  selectedResourceTypes.value = []
}

async function retryPendingMessage() {
  try {
    await chatStore.retryPendingMessage()
  } catch {
    // The store keeps the draft request and error.
  }
}

async function stopResponse() {
  try {
    await chatStore.stopActiveResponse()
  } catch {
    // The store refreshes optimistic-lock conflicts.
  }
}

async function continueResponse(messageId) {
  try {
    await chatStore.continueResponse(messageId)
    await nextTick()
    scrollToBottom()
  } catch {
    // The store exposes the recoverable error.
  }
}

function startResourceFromMessage(message) {
  resourceSourceMessageId.value = message?.id || ''
  activeEvidenceMessageId.value = message?.id || activeEvidenceMessageId.value
  resourcePickerOpen.value = true
  localError.value = ''
  if (!draft.value.trim()) {
    draft.value = '基于这条回答生成所选学习资源，保留原问题的数据和推导，并安排新的独立练习。'
  }
}

watch(() => chatStore.pendingSend, (pending, previous) => {
  if (!pending && previous && messages.value.some(message =>
    message.role === 'user' && message.idempotencyKey === previous.idempotency_key)) {
    draft.value = ''
    localError.value = ''
    selectedResourceTypes.value = []
    resourceSourceMessageId.value = ''
    resourcePickerOpen.value = false
  }
})

function onComposerKeydown(event) {
  if (event.key !== 'Enter' || event.shiftKey || event.isComposing) return
  event.preventDefault()
  void sendMessage()
}

function scrollToBottom(smooth = true) {
  const element = messageScroller.value
  if (!element) return
  element.scrollTo({ top: element.scrollHeight, behavior: smooth ? 'smooth' : 'auto' })
}

async function loadQuizContext() {
  if (!quizResourceId.value) return
  quizLoading.value = true
  quizError.value = ''
  try {
    const payload = await getM5Resource(quizResourceId.value)
    if (payload?.catalog?.type !== 'quiz') throw new Error('当前链接不是测验题资源')
    quizDetail.value = payload
  } catch (error) {
    quizError.value = error?.response?.data?.detail?.message || error?.message || '测验题上下文加载失败'
  } finally {
    quizLoading.value = false
  }
}

async function sendRouteResourceMessage() {
  if (!resourceIntent.value || routeResourceMessageStarted.value) return
  const idempotencyKey = resourceMessageIdempotencyKey.value
  if (!idempotencyKey) return
  const existing = messages.value.find((message) => (
    message.role === 'user' && message.idempotencyKey === idempotencyKey
  ))
  if (existing) {
    routeResourceMessageStarted.value = true
    draft.value = ''
    selectedResourceTypes.value = []
    resourcePickerOpen.value = false
    return
  }
  if (chatStore.sending) return
  routeResourceMessageStarted.value = true
  localError.value = ''
  try {
    await chatStore.sendMessage({
      content: resourceMessageText.value,
      contextRefs: resourceMessageContextRefs.value,
      returnTo: outgoingReturnTo.value,
      intent: resourceIntent.value,
      resourceTypes: effectiveResourceTypes.value,
      contextSnapshotId: cleanQueryValue(route.query.context_snapshot_id || route.query.contextSnapshotId),
      idempotencyKey,
    })
    draft.value = ''
    selectedResourceTypes.value = []
    resourcePickerOpen.value = false
    await nextTick()
    scrollToBottom()
  } catch (error) {
    routeResourceMessageStarted.value = false
    localError.value = error?.message || '资源请求发送失败，内容仍可重试'
  }
}

watch(
  () => [messages.value.length, chatStore.streamingContent, chatStore.sending],
  () => nextTick(() => scrollToBottom()),
)

// A resource route can open while an older answer is still streaming. Keep
// the route request in the composer until that stream becomes idle, then send
// it through the same canonical path exactly once.
watch(
  () => chatStore.sending,
  (sending, wasSending) => {
    if (wasSending && !sending && resourceIntent.value && !routeResourceMessageStarted.value) {
      void sendRouteResourceMessage()
    }
  },
)

// A conversation may first contain a failed resource-generation reply and
// then receive a normal question.  Keep the evidence inspector attached to
// the newly completed assistant message instead of leaving the old failure
// selected while the visible answer has already completed.
watch(
  () => chatStore.sending,
  (sending, wasSending) => {
    if (!wasSending || sending) return
    const latest = latestAssistant.value
    if (latest?.id) activeEvidenceMessageId.value = latest.id
  },
)

watch(
  () => evidenceMessage.value?.id,
  (messageId) => {
    if (!activeEvidenceMessageId.value && messageId) activeEvidenceMessageId.value = messageId
  },
)

onMounted(async () => {
  if (await redirectLegacyWorkbench()) return
  draft.value = cleanQueryValue(route.query.quiz_follow_up || route.query.prompt)
  try {
    await chatStore.loadCourseOptions()
  } catch (error) {
    courseSelectionError.value = error?.message || '课程列表加载失败，请稍后重试'
  }
  try {
    const inheritedCourseId = routeCourseIds.value[0] || courseContext.contextRef?.courseId || ''
    if (route.query.resource_id && !route.query.conversation_id && !resourceIntent.value) {
      const conversation = await chatStore.createConversation({
        courseId: inheritedCourseId,
        title: cleanQueryValue(route.query.context) || '学习材料问答',
      })
      await router.replace({ query: { ...route.query, conversation_id: conversation.id } })
      return
    }
    const conversation = await chatStore.initialize({
      courseId: inheritedCourseId,
      conversationId: cleanQueryValue(route.query.conversation_id),
      createIfEmpty: !quizResourceId.value,
    })
    const restoredIds = Array.isArray(conversation?.courseIds)
      ? conversation.courseIds
      : (routeCourseIds.value.length ? routeCourseIds.value : (inheritedCourseId ? [inheritedCourseId] : []))
    syncSelectedCourses(restoredIds)
  } catch {
    // The page renders the store's recoverable load error.
  }
  await loadQuizContext()
  initializing.value = false
  await sendRouteResourceMessage()
  await nextTick()
  if (quizResourceId.value) {
    messageScroller.value?.scrollTo({ top: 0, behavior: 'auto' })
  } else {
    scrollToBottom(false)
  }
})

onUnmounted(() => chatStore.cleanup())
</script>

<template>
  <main class="chat-workspace" :class="{ 'chat-workspace--rail-collapsed': evidenceRailCollapsed }" aria-label="智能对话学习工作台" data-testid="focused-chat-workspace">
    <aside class="conversation-rail" aria-label="对话列表" data-testid="chat-conversation-rail">
      <div class="rail-heading">
        <div>
          <span>会话</span>
        </div>
        <button type="button" class="icon-button" title="新建对话" aria-label="新建对话" :disabled="conversationBusy" @click="createConversation">
          <LoaderCircle v-if="chatStore.creatingConversation" :size="18" class="spin" />
          <Plus v-else :size="18" />
        </button>
      </div>

      <div v-if="chatStore.loading && !conversations.length" class="rail-state" data-testid="chat-conversation-loading">
        <LoaderCircle :size="18" class="spin" />
        <span>正在恢复会话</span>
      </div>

      <div v-else-if="!conversations.length" class="rail-state" data-testid="chat-conversation-empty">
        <MessageSquareText :size="20" />
        <span>暂无会话</span>
      </div>

      <div v-else class="conversation-list">
        <div
          v-for="conversation in conversations"
          :key="conversation.id"
          class="conversation-item"
          :class="{ active: conversation.id === chatStore.activeConversationId }"
          :data-conversation-id="conversation.id"
        >
          <button
            type="button"
            class="conversation-select"
            :aria-current="conversation.id === chatStore.activeConversationId ? 'page' : undefined"
            @click="openConversation(conversation.id)"
          >
            <span class="conversation-copy">
              <strong>{{ learningText(conversation.title, '新对话') }}</strong>
              <small>{{ formatTime(conversation.updatedAt) }}</small>
              <small class="conversation-course" :title="conversationCourseLabel(conversation)" data-testid="conversation-course-label">{{ conversationCourseLabel(conversation) }}</small>
            </span>
          </button>
          <button
            class="archive-action"
            type="button"
            title="归档对话"
            aria-label="归档对话"
            @click="archiveConversation(conversation.id)"
          >
            <Archive :size="15" />
          </button>
        </div>
      </div>

    </aside>

    <section class="answer-workspace" data-testid="chat-answer-workspace">
      <header class="answer-heading">
        <div>
          <span v-if="currentKnowledgePointId" class="answer-heading__context" :title="currentKnowledgePointTitle">{{ currentKnowledgePointTitle }}</span>
          <h1 class="answer-heading__title" :title="chatStore.activeConversation?.title || '新对话'">{{ chatStore.activeConversation?.title || '新对话' }}</h1>
        </div>
        <div class="answer-heading__actions">
          <div class="course-picker" data-testid="chat-course-picker">
            <button
              type="button"
              class="course-picker__trigger"
              :aria-expanded="coursePickerOpen"
              aria-haspopup="dialog"
              @click="openCoursePicker"
            >
              <BookOpen :size="16" />
              <span data-testid="chat-current-course-label" :title="currentCourseTitle">{{ chatStore.loadingCourses ? courseSelectionLabel : currentCourseTitle }}</span>
              <span class="course-picker__chevron">⌄</span>
            </button>
            <div v-if="coursePickerOpen" class="course-picker__panel" role="dialog" aria-label="选择对话课程">
              <header>
                <strong>选择对话课程</strong>
                <button type="button" class="icon-button" aria-label="关闭课程选择" title="关闭" @click="coursePickerOpen = false"><X :size="15" /></button>
              </header>
              <p>课程只影响后续新消息，历史消息保留当时选择的课程。</p>
              <SearchField v-model="courseSearch" placeholder="搜索课程或专业" aria-label="搜索课程或专业" clearable />
              <div v-if="chatStore.loadingCourses" class="course-picker__state"><LoaderCircle :size="16" class="spin" />正在加载可用课程</div>
              <div v-else-if="chatStore.courseCatalogError" class="course-picker__error" role="alert">
                <AlertCircle :size="16" />{{ userMessage(courseSelectionError || chatStore.courseCatalogError) }}
                <button type="button" class="text-button" @click="chatStore.loadCourseOptions"><RefreshCw :size="15" />重试</button>
              </div>
              <div v-else-if="!chatStore.availableCourses.length" class="course-picker__state">暂无可用课程，可以使用通用对话。</div>
              <template v-else>
                <div v-if="recentCourseOptions.length" class="course-picker__group">
                  <span class="course-picker__group-title">最近课程</span>
                  <label v-for="course in recentCourseOptions" :key="`recent-${course.id}`" class="course-picker__option">
                    <input type="checkbox" :checked="courseIsSelected(course.id)" @change="toggleCourse(String(course.id))" />
                    <span><strong>{{ course.title }}</strong><small>{{ course.subject || '课程资料' }}</small></span>
                  </label>
                </div>
                <div class="course-picker__group">
                  <span class="course-picker__group-title">{{ courseSearch.trim() ? '搜索结果' : '全部课程' }}</span>
                  <label v-for="course in otherCourseOptions" :key="course.id" class="course-picker__option">
                    <input type="checkbox" :checked="courseIsSelected(course.id)" @change="toggleCourse(String(course.id))" />
                    <span><strong>{{ course.title }}</strong><small>{{ course.subject || '课程资料' }}</small></span>
                  </label>
                  <p v-if="!recentCourseOptions.length && !otherCourseOptions.length" class="course-picker__state">没有匹配的课程。</p>
                </div>
              </template>
              <footer>
                <button type="button" class="text-button" :disabled="!selectedCourseIds.length" @click="useGeneralChat">使用通用对话</button>
                <button type="button" class="text-button" @click="finishCourseSelection">完成</button>
              </footer>
            </div>
          </div>
          <span v-if="latestAssistant && latestAssistant.status !== 'completed'" class="answer-status" :data-status="latestAssistant.status" aria-live="polite">
            <span class="status-dot" />
            {{ latestAssistant ? statusText(latestAssistant) : '等待提问' }}
          </span>
        </div>
      </header>

      <div ref="messageScroller" class="message-scroller" role="log" aria-live="polite" aria-relevant="additions text" data-testid="chat-message-scroller">
        <section v-if="quizResourceId" class="quiz-context" data-testid="chat-quiz-context">
          <header>
            <div>
              <span>当前测验题</span>
              <strong>{{ quizTitle }}</strong>
            </div>
            <span>当前题目可直接作答，完整历史仍归测验题资源</span>
          </header>
          <div v-if="quizLoading" class="inline-state"><LoaderCircle :size="18" class="spin" />正在加载题目</div>
          <div v-else-if="quizError" class="inline-error" role="alert">
            <AlertCircle :size="18" />
            <span>{{ userMessage(quizError) }}</span>
            <button type="button" class="text-button" @click="loadQuizContext"><RefreshCw :size="16" />重试</button>
          </div>
          <div v-else-if="quizQuestion" class="quiz-context__body">
            <InlineQuizCard
              :question="quizQuestion"
              :resource-id="quizResourceId"
              :initial-attempt="quizQuestion.latest_attempt"
              :position="quizQuestionPosition"
              :total="quizQuestions.length"
              :source-refs="quizSourceRefs"
              compact
              @submitted="handleQuizSubmitted"
              @follow-up="handleQuizFollowUp"
              @open-source="openQuizSource"
            />
            <div class="quiz-context__summary">
              <small>作答、判分、解析和历史记录会保留在这道题的学习记录中；这里的追问会围绕当前题目展开。</small>
            </div>
            <details v-if="quizSourceRefs.length" class="quiz-context__sources" aria-label="题目相关材料">
              <summary>查看相关材料</summary>
              <button
                v-for="(source, index) in quizSourceRefs"
                :key="source.id || source.source_ref_id || index"
                type="button"
                @click="openQuizSource(source.id || source.source_ref_id)"
              >
                <BookOpen :size="16" />{{ quizSourceTitle(source, index) }}
              </button>
            </details>
            <button type="button" class="quiz-context__primary" @click="openQuizResource">
              <ExternalLink :size="17" />进入测验题资源作答
            </button>
          </div>
          <div v-else class="quiz-context__empty">
            <div><AlertCircle :size="18" /><span>当前版本没有可显示的题目，请在测验题资源中查看版本或重新生成。</span></div>
            <button type="button" class="quiz-context__primary" @click="openQuizResource">
              <ExternalLink :size="17" />进入测验题资源
            </button>
          </div>
        </section>

        <div v-if="chatStore.loading && !messages.length" class="center-state" data-testid="chat-messages-loading">
          <LoaderCircle :size="22" class="spin" />
          <strong>正在恢复对话</strong>
        </div>

        <div v-else-if="!messages.length" class="empty-conversation" data-testid="chat-messages-empty">
          <span class="empty-mark"><MessageSquareText :size="24" /></span>
          <h2>今天想先弄懂什么？</h2>
          <p>{{ currentKnowledgePointId ? `已带入“${currentKnowledgePointTitle}”的学习内容。` : '可以直接提问，也可以从学习路径或资源页带着学习内容进入。' }}</p>
        </div>

        <div v-else class="message-list">
          <article
            v-for="message in messages"
            :key="message.id"
            class="message-row"
            :class="[`message-row--${message.role}`, { selected: evidenceMessage?.id === message.id }]"
            :data-message-id="message.id"
            @click="activeEvidenceMessageId = message.id"
          >
            <template v-if="message.role === 'user'">
              <div class="user-message">
                <p v-if="message.content">{{ message.content }}</p>
                <div v-if="messageAttachments(message).length" class="message-file-list">
                  <span v-for="item in messageAttachments(message)" :key="item.id">
                    <component :is="attachmentIcon(item)" :size="15" />{{ item.filename }}
                  </span>
                </div>
              </div>
              <time>{{ formatTime(message.createdAt) }}</time>
            </template>

            <template v-else>
              <div class="assistant-label">
                <span class="assistant-mark">E</span>
                <strong>EduMatrix</strong>
                <span>{{ statusText(message) }}</span>
                <time>{{ formatTime(message.updatedAt || message.createdAt) }}</time>
              </div>

              <div class="assistant-answer">
                <IncrementalMarkdownRenderer v-if="message.content" :text="message.content" />
                <div v-else-if="['queued', 'streaming'].includes(message.status)" class="answer-pending">
                  <LoaderCircle :size="18" class="spin" />
                  <span>{{ chatStore.streamingStatus || '正在组织回答' }}</span>
                </div>
              </div>

              <details v-if="workflowEventCount(message) || message.claims?.length || messageAgentAudit(message)" class="message-workflow">
                <summary><Network :size="16" />{{ message.resourceJobId ? '查看生成过程' : '查看回答过程' }}</summary>
                <AgentTimeline
                  :audit="messageAgentAudit(message)"
                  :run-events="message.runEvents"
                  :claims="message.claims || message.streamCheckpoint?.claims || []"
                  :answer-revision="message.streamCheckpoint?.answerRevision"
                  :answer-revision-history="message.streamCheckpoint?.answerRevisionHistory || []"
                   :source-refs="message.sourceRefs || []"
                   :return-to="route.fullPath"
                   hide-completed
                   compact
                />
              </details>

              <div v-if="message.status === 'streaming'" class="stream-progress" aria-live="polite">
                <span :style="{ width: `${Math.max(8, chatStore.streamingProgress)}%` }" />
              </div>

              <div v-if="message.status === 'failed'" class="message-failure" role="alert">
                <AlertCircle :size="18" />
                <div>
                  <strong>{{ message.resourceJobId ? '学习资源还未准备好' : '回答暂时中断' }}</strong>
                  <span>{{ message.failure?.message || '已保留当前内容，可以继续回答。' }}</span>
                </div>
              </div>

              <button
                v-if="message.status === 'completed' && messageGroundingLevel(message) === 'D'"
                type="button"
                class="text-button grounding-action"
                data-testid="chat-general-knowledge-action"
                @click.stop="continueWithGeneralKnowledge(message)"
              >
                <MessageSquareText :size="16" />用通用知识继续回答
              </button>

              <div v-if="message.resourceLinks?.length" class="resource-link-list" data-testid="chat-compact-resource-links">
                <button v-for="link in message.resourceLinks" :key="`${link.type}-${link.taskId}`" type="button" @click.stop="openResourceLink(link, message)">
                  <Library :size="17" />
                  <span><strong>{{ link.title }}</strong><small>{{ link.status === 'completed' ? '已生成' : link.status === 'failed' ? '需要重试' : '正在学习空间中准备' }}</small></span>
                  <ExternalLink :size="15" />
                </button>
              </div>

              <div class="message-actions">
                <ReadAloudButton v-if="message.status === 'completed'" :text="message.content" />
                <button v-if="message.resourceJobId" type="button" class="text-button" @click.stop="router.push(`/workspace/resources/bundles/${message.resourceJobId}`)">
                  <Library :size="16" />{{ resourceAutomation(message).state === 'completed' ? '查看资源包' : '查看准备进度' }}
                </button>
                <button v-else-if="['stopped', 'failed'].includes(message.status)" type="button" class="text-button" @click.stop="continueResponse(message.id)">
                  <RefreshCw :size="16" />继续回答
                </button>
                <button v-if="message.status === 'completed' && !message.resourceJobId" type="button" class="text-button" @click.stop="startResourceFromMessage(message)">
                  <Plus :size="16" />在输入框生成资源
                </button>
                <button v-if="message.sourceRefs?.length" type="button" class="text-button" @click.stop="showMessageEvidence(message, 'course')">
                  <BookOpen :size="16" />参考内容
                </button>
                <button v-if="messageAgentAudit(message)" type="button" class="text-button" @click.stop="showMessageEvidence(message, 'trace')">
                  <Network :size="16" />AI 协作
                </button>
              </div>
            </template>
          </article>
        </div>
      </div>

      <footer class="composer" data-testid="chat-composer">
        <div v-if="visibleAttachments.length" class="attachment-queue" data-testid="chat-attachment-queue">
          <div class="attachment-queue__header">
            <div class="attachment-queue__summary">
              <Paperclip :size="17" aria-hidden="true" />
              <strong>附件</strong>
              <span>{{ attachmentQueueSummary }}</span>
            </div>
            <button
              type="button"
              class="attachment-toggle"
              :aria-expanded="String(!attachmentsCollapsed)"
              aria-controls="chat-attachment-list"
              :title="attachmentsCollapsed ? '向上展开附件' : '向下隐藏附件'"
              :aria-label="attachmentsCollapsed ? '向上展开附件' : '向下隐藏附件'"
              data-testid="chat-attachment-toggle"
              @click="attachmentsCollapsed = !attachmentsCollapsed"
            >
              <ChevronUp v-if="attachmentsCollapsed" :size="17" aria-hidden="true" />
              <ChevronDown v-else :size="17" aria-hidden="true" />
              <span>{{ attachmentsCollapsed ? '展开' : '隐藏' }}</span>
            </button>
          </div>
          <div
            id="chat-attachment-list"
            v-show="!attachmentsCollapsed"
            class="attachment-queue__list"
            :aria-hidden="String(attachmentsCollapsed)"
          >
            <article
              v-for="item in visibleAttachments"
              :id="`attachment-${item.id}`"
              :key="item.id"
              class="attachment-row"
              :data-status="item.status"
            >
              <label class="attachment-select" :title="item.canSend ? '选择是否随本次问题发送' : attachmentStatus(item)">
                <input
                  type="checkbox"
                  :checked="chatStore.selectedAttachmentIds.includes(item.id)"
                  :disabled="!item.canSend"
                  @change="chatStore.toggleAttachmentSelection(item.id)"
                />
                <span><CheckCircle2 :size="15" /></span>
              </label>
              <component :is="attachmentIcon(item)" :size="19" class="attachment-type" />
              <div class="attachment-copy">
                <strong>{{ item.filename }}</strong>
                <span>{{ attachmentSummary(item) }} · {{ attachmentStatus(item) }}</span>
                <small v-if="item.failure?.message">{{ item.failure.message }}</small>
                <small v-else-if="item.warnings?.length">{{ item.warnings[0] }}</small>
              </div>
              <div class="attachment-actions">
                <button
                  v-if="['failed', 'failed_retryable'].includes(item.status)"
                  type="button"
                  class="icon-button"
                  title="重试解析"
                  aria-label="重试解析"
                  :disabled="chatStore.attachmentActions[item.id] === 'parsing'"
                  @click="retryAttachment(item.id)"
                >
                  <RefreshCw :size="16" />
                </button>
                <button
                  v-if="item.status === 'partial_failed' && !item.partialConfirmed"
                  type="button"
                  class="confirm-button"
                  :disabled="chatStore.attachmentActions[item.id] === 'confirming'"
                  @click="confirmPartialAttachment(item.id)"
                >
                  确认可用部分
                </button>
                <button type="button" class="icon-button" title="移除附件" aria-label="移除附件" @click="removeAttachment(item.id)">
                  <X :size="16" />
                </button>
              </div>
              <span v-if="['queued', 'parsing'].includes(item.status)" class="attachment-progress" :style="{ width: `${Math.max(6, Number(item.progress || 0) * 100)}%` }" />
            </article>
          </div>
        </div>

        <div class="composer-box">
          <button v-if="resourceSourceMessageId" type="button" class="resource-picker-trigger"
            aria-label="取消引用所选回答" @click="resourceSourceMessageId = ''">
            <span>基于所选回答</span><X :size="14" />
          </button>
          <textarea
            v-model="draft"
            class="composer-input"
            rows="3"
            :placeholder="composerPlaceholder"
            aria-label="输入问题"
            :disabled="conversationBusy"
            @keydown="onComposerKeydown"
          />
          <div class="composer-tools">
            <input
              ref="fileInput"
              hidden
              type="file"
              multiple
              :disabled="conversationBusy || uploading"
              :accept="preferences.imageAnalysis ? '.ppt,.pdf,.pptx,.docx,.md,.txt,.png,.jpg,.jpeg,.webp' : '.ppt,.pdf,.pptx,.docx,.md,.txt'"
              @change="chooseFiles"
            />
            <button type="button" class="icon-button" title="添加附件" aria-label="添加附件" :disabled="conversationBusy || uploading" @click="fileInput?.click()">
              <LoaderCircle v-if="uploading" :size="18" class="spin" />
              <Paperclip v-else :size="18" />
            </button>
            <div class="composer-resource-picker" :class="{ open: resourcePickerOpen }">
              <button
                type="button"
                class="resource-picker-trigger"
                :aria-expanded="String(resourcePickerOpen)"
                aria-controls="composer-resource-options"
                title="选择要生成的资源"
                @click="resourcePickerOpen = !resourcePickerOpen; coursePickerOpen = false"
              >
                <Plus :size="17" />
                <span>生成资源</span>
                <small v-if="composerResourceTypes.length">{{ composerResourceTypes.length }}</small>
              </button>
              <div v-if="resourcePickerOpen" id="composer-resource-options" class="resource-picker-panel" role="dialog" aria-label="选择生成资源类型">
                <header>
                  <strong>选择生成资源</strong>
                  <span>{{ composerResourceTypes.length }}/{{ resourceOptions.length }}</span>
                </header>
                <div class="resource-picker-actions">
                  <button type="button" @click="selectAllResourceTypes">全选</button>
                  <button type="button" @click="clearResourceTypes">清空</button>
                </div>
                <label v-for="option in resourceOptions" :key="option.type" class="resource-picker-option">
                  <input
                    type="checkbox"
                    :checked="composerResourceTypes.includes(option.type)"
                    @change="toggleResourceType(option.type)"
                  />
                  <component :is="option.icon" :size="16" />
                  <span>{{ option.label }}</span>
                </label>
                <p v-if="composerResourceTypes.length" class="resource-picker-hint">输入你的学习要求后发送，可以在这段对话中查看资源准备进展。</p>
                <p v-else class="resource-picker-hint">选择一种或多种资源，输入框会显示生成要求模板。</p>
              </div>
            </div>
            <span v-if="sendDisabledReason && hasDraftContent && !chatStore.submitting" class="send-reason">{{ sendDisabledReason }}</span>
            <button v-if="chatStore.sending" type="button" class="stop-button" @click="stopResponse">
              <Square :size="16" />停止
            </button>
            <button v-else type="button" class="send-button" :disabled="!canSend" @click="sendMessage()">
              <Send :size="17" />{{ chatStore.submitting ? '发送中…' : '发送' }}
            </button>
          </div>
        </div>

        <div v-if="chatStore.pendingSend && !chatStore.submitting" class="composer-recovery" role="alert">
          <AlertCircle :size="17" />
          <span>{{ chatStore._pendingRetry ? '连接恢复后会自动继续准备资源。' : '问题尚未成功提交，内容已保留。' }}</span>
          <button v-if="!chatStore._pendingRetry" type="button" class="text-button" @click="retryPendingMessage"><RefreshCw :size="16" />重试发送</button>
        </div>
        <p v-if="!chatStore._pendingRetry && (localError || chatStore.error || chatStore.attachmentError)" class="composer-error" role="alert">
          <AlertCircle :size="17" />{{ userMessage(localError || chatStore.attachmentError || chatStore.error) }}
        </p>
      </footer>
    </section>

    <aside
      class="evidence-rail"
      :class="{ collapsed: evidenceRailCollapsed }"
      aria-label="学习详情"
      data-testid="chat-evidence-rail"
    >
      <div class="evidence-heading">
        <span v-if="!evidenceRailCollapsed">学习详情</span>
        <button
          type="button"
          class="icon-button"
          :aria-expanded="String(!evidenceRailCollapsed)"
          :aria-label="evidenceRailCollapsed ? '展开学习详情' : '折叠学习详情'"
          :title="evidenceRailCollapsed ? '展开学习详情' : '折叠学习详情'"
          data-testid="chat-evidence-toggle"
          @click="evidenceRailCollapsed = !evidenceRailCollapsed"
        >
          <ChevronRight v-if="evidenceRailCollapsed" :size="18" aria-hidden="true" />
          <ChevronLeft v-else :size="18" aria-hidden="true" />
        </button>
      </div>

      <template v-if="!evidenceRailCollapsed">
        <nav class="evidence-tabs" aria-label="学习详情标签">
          <button type="button" :class="{ active: evidenceTab === 'trace' }" data-testid="chat-tab-trace" @click="evidenceTab = 'trace'">{{ evidenceMessage?.resourceJobId ? '生成过程' : '回答过程' }}</button>
          <button type="button" :class="{ active: evidenceTab === 'course' }" data-testid="chat-tab-course" @click="evidenceTab = 'course'">相关内容</button>
          <button type="button" :class="{ active: evidenceTab === 'attachments' }" data-testid="chat-tab-attachments" @click="evidenceTab = 'attachments'">附件</button>
        </nav>

        <template v-if="evidenceTab === 'trace'">
          <section class="evidence-section" data-testid="chat-processing-state">
            <header><Clock3 :size="17" /><strong>{{ evidenceMessage?.resourceJobId ? '资源状态' : '回答状态' }}</strong></header>
            <dl v-if="evidenceMessage">
              <div><dt>状态</dt><dd>{{ statusText(evidenceMessage) }}</dd></div>

            </dl>
            <p v-else class="evidence-empty">当前还没有回答记录。</p>
          </section>
          <section v-if="evidenceAgentAudit || evidenceRunEvents.length || evidenceClaims.length" class="evidence-section evidence-section--agent" data-testid="chat-agent-audit">
            <AgentTimeline
              :audit="evidenceAgentAudit"
              :run-events="evidenceRunEvents"
               :claims="evidenceClaims"
               :answer-revision="evidenceMessage?.streamCheckpoint?.answerRevision"
               :answer-revision-history="evidenceMessage?.streamCheckpoint?.answerRevisionHistory || []"
               :source-refs="evidenceSourceRefs"
               :return-to="route.fullPath"
               hide-completed
               compact
            />
          </section>
          <section v-if="evidenceResourceLinks.length" class="evidence-section" data-testid="chat-resource-links">
            <header><ListChecks :size="17" /><strong>生成资源</strong></header>
            <div class="source-list">
              <button v-for="link in evidenceResourceLinks" :key="`${link.type}-${link.taskId}`" type="button" @click="openResourceLink(link)">
                <span><strong>{{ link.title }}</strong><small>{{ displayLabel(link.status) }}</small></span>
                <ExternalLink :size="15" />
              </button>
            </div>
          </section>
          <button v-if="evidenceReturnTo" type="button" class="return-button" @click="openReturnPath">
            <ExternalLink :size="16" />返回原学习位置
          </button>
        </template>

        <template v-else-if="evidenceTab === 'course'">
          <section class="evidence-section" data-testid="chat-context-refs">
            <header><BookOpen :size="17" /><strong>本轮学习范围</strong></header>
            <div v-if="contextRows(evidenceContextRefs).length" class="context-list">
              <div v-for="item in contextRows(evidenceContextRefs)" :key="item.key">
                <span>{{ item.label }}</span>
                <strong>{{ item.title }}</strong>
                <small v-if="item.status">{{ displayLabel(item.status) }}</small>
              </div>
            </div>
            <div v-else class="context-list">
              <div><span>课程</span><strong>{{ currentCourseTitle }}</strong></div>
              <div v-if="currentKnowledgePointId"><span>知识点</span><strong>{{ currentKnowledgePointTitle }}</strong></div>
            </div>
          </section>
          <section class="evidence-section" data-testid="chat-source-list">
            <header><Library :size="17" /><strong>相关学习内容</strong></header>
            <div v-if="evidenceSourceRefs.length" class="source-list">
              <section v-for="group in evidenceSourceGroups" :key="group.key" class="course-source-group">
                <h3 v-if="group.passages.length > 1">{{ learningText(group.title, '课程来源') }}</h3>
                <div v-for="passage in group.passages" :key="passage.key" class="course-source-entry">
                  <SourceCitation
                    :source="passage.source"
                    :display-title="group.passages.length > 1 ? passagePreview(passage.source) : ''"
                    :hide-location="group.passages.length > 1"
                    :return-to="route.fullPath"
                    compact
                  />
                </div>
              </section>
            </div>
            <p v-else class="evidence-empty">本轮没有附加阅读内容。</p>
          </section>
          <details v-if="evidenceCandidateSourceRefs.length" class="evidence-section" data-testid="chat-candidate-source-list">
            <summary>候选但未采用来源</summary>
            <div class="source-list">
              <div v-for="source in evidenceCandidateSourceRefs" :key="sourcePassageKey(source)" class="course-source-entry">
                <SourceCitation :source="source" :return-to="route.fullPath" compact />
                <small class="course-source-meta">{{ learningText(source.reason || source.reasonMessage || '未作为本轮回答依据') }}</small>
              </div>
            </div>
          </details>
          <button v-if="currentCourseId" type="button" class="return-button" data-testid="chat-open-course-knowledge" @click="openCourseKnowledge">
            <BookOpen :size="16" />打开课程知识库
          </button>
        </template>

        <template v-else>
          <section class="evidence-section" data-testid="chat-evidence-attachments">
            <header><Paperclip :size="17" /><strong>附件文件夹</strong></header>
            <div v-if="evidenceAttachments.length || removedAttachments.length" class="evidence-file-list">
              <div v-for="item in evidenceAttachments" :key="item.id" class="evidence-file-entry">
                <component :is="attachmentIcon(item)" :size="17" />
                <span><strong>{{ item.filename }}</strong><small>{{ attachmentStatus(item) }} · {{ attachmentSummary(item) }}</small><small v-if="item.failure?.message">{{ item.failure.message }}</small></span>
                <div class="evidence-file-actions">
                  <button v-if="['failed', 'failed_retryable'].includes(item.status)" type="button" class="icon-button" title="重试解析" aria-label="重试解析" :disabled="chatStore.attachmentActions[item.id] === 'parsing'" @click="retryAttachment(item.id)"><RefreshCw :size="15" /></button>
                  <button v-if="item.status === 'partial_failed' && !item.partialConfirmed" type="button" class="confirm-button" :disabled="chatStore.attachmentActions[item.id] === 'confirming'" @click="confirmPartialAttachment(item.id)">确认可用部分</button>
                  <button type="button" class="icon-button" title="移除附件" aria-label="移除附件" :disabled="chatStore.attachmentActions[item.id] === 'removing'" @click="removeAttachment(item.id)"><X :size="15" /></button>
                </div>
              </div>
              <div v-for="item in removedAttachments" :key="item.id" class="removed-file">
                <X :size="17" />
                <span><strong>{{ item.filename }}</strong><small>已移除，不再参与上下文</small></span>
              </div>
            </div>
            <p v-else class="evidence-empty">当前对话还没有附件。</p>
            <button type="button" class="return-button" @click="reselectAttachments"><Paperclip :size="16" />重新选择/上传附件</button>
          </section>
        </template>
      </template>
    </aside>
  </main>
</template>

<style scoped>
.chat-workspace {
  --chat-page: var(--color-page);
  --chat-surface: var(--color-surface);
  --chat-text: var(--color-text);
  --chat-primary: var(--color-accent);
  --chat-secondary: var(--color-text-secondary);
  --chat-muted: var(--color-text-muted);
  --chat-border: var(--color-border);
  --chat-border-strong: var(--color-border-strong);
  --chat-subtle: var(--color-accent-soft);
  --chat-danger: var(--color-danger);
  display: grid;
  width: 100%;
  height: calc(100dvh - var(--topbar-height) - 76px);
  min-width: 0;
  min-height: 560px;
  grid-template-columns: clamp(236px, 15vw, 300px) minmax(0, 1fr) clamp(304px, 20vw, 392px);
  border: 0;
  border-radius: var(--radius-panel);
  overflow: hidden;
  color: var(--chat-text);
  background: var(--gradient-paper);
  font-family: var(--font-sans);
}

.chat-workspace--rail-collapsed {
  grid-template-columns: clamp(236px, 15vw, 300px) minmax(0, 1fr) 56px;
}

button,
textarea,
input {
  font: inherit;
}

button {
  color: inherit;
}

.conversation-rail,
.evidence-rail,
.answer-workspace {
  min-width: 0;
  min-height: 0;

  background: var(--gradient-paper);
}

.conversation-rail,
.evidence-rail {
  display: flex;
  flex-direction: column;
  background: var(--color-surface);
}

.conversation-rail {
  border-right: 0;
}

.evidence-rail {
  overflow-y: auto;
  border-left: 0;
  background: var(--gradient-rail);
}

.evidence-rail.collapsed {
  overflow: hidden;
}

.evidence-rail.collapsed .evidence-heading {
  justify-content: center;
  padding: 0 8px;
}

.rail-heading,
.evidence-heading,
.answer-heading {
  display: flex;
  min-height: 72px;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  border-bottom: 0;
}

.rail-heading,
.evidence-heading {
  padding: 0 18px;
}

.rail-heading > div,
.evidence-heading {
  color: var(--chat-secondary);
  font-size: 14px;
  letter-spacing: .02em;
}

.rail-heading > div {
  display: flex;
  align-items: center;
  gap: 8px;
}

.rail-heading strong,
.evidence-heading strong {
  color: var(--chat-text);
  font-size: 15px;
}

.icon-button {
  display: inline-grid;
  width: 36px;
  height: 36px;
  flex: 0 0 36px;
  place-items: center;
  border: 1px solid var(--chat-border);
  border-radius: 6px;
  background: var(--color-surface);
  cursor: pointer;
}

.icon-button:hover:not(:disabled) {
  border-color: var(--chat-border-strong);
  background: var(--chat-subtle);
}

.icon-button:disabled {
  cursor: default;
  opacity: .48;
}

.rail-state,
.center-state {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 9px;
  color: var(--chat-muted);
  font-size: 14px;
}

.rail-state {
  min-height: 120px;
  padding: 20px;
}

.conversation-list {
  flex: 1;
  overflow-y: auto;
  padding: 14px 10px 18px;
}

.conversation-item {
  display: grid;
  width: 100%;
  min-height: 68px;
  grid-template-columns: minmax(0, 1fr) 30px;
  align-items: center;
  gap: 6px;
  border: 0;
  border-left: 3px solid transparent;
  border-radius: 7px;
  padding: 10px 8px 10px 12px;
  background: transparent;
  text-align: left;
  cursor: pointer;
}

.conversation-select {
  display: block;
  min-width: 0;
  padding: 0;
  border: 0;
  background: transparent;
  color: inherit;
  text-align: left;
  cursor: pointer;
}

.conversation-select:focus-visible {
  outline: 2px solid var(--chat-primary);
  outline-offset: 2px;
}

.conversation-item:hover,
.conversation-item.active {
  background: var(--chat-subtle);
}

.conversation-item.active {
  border-left-color: var(--chat-primary);
  box-shadow: inset 0 0 0 1px rgba(36, 72, 90, .08);
}

.conversation-copy {
  display: grid;
  min-width: 0;
  gap: 3px;
}

.conversation-copy strong,
.conversation-copy small {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.conversation-copy strong {
  color: var(--chat-text);
  font-size: 15px;
  font-weight: 620;
}

.conversation-copy small {
  color: var(--chat-muted);
  font-size: 14px;
}

.archive-action {
  display: grid;
  width: 30px;
  height: 30px;
  place-items: center;
  color: var(--chat-muted);
  border: 0;
  background: transparent;
  cursor: pointer;
  border-radius: 6px;
  opacity: 0;
}

.conversation-item:hover .archive-action,
.conversation-item.active .archive-action,
.archive-action:focus-visible {
  opacity: 1;
}

.archive-action:hover {
  color: var(--chat-text);
  background: var(--color-surface);
}

.answer-workspace {
  display: grid;
  grid-template-rows: auto minmax(0, 1fr) auto;
  background: var(--gradient-paper);
}

.answer-heading {
  padding: 10px clamp(20px, 2.2vw, 36px);
  background: var(--gradient-paper);
}

.answer-heading > div:first-child {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  min-width: 0;
  gap: 4px;
}

.answer-heading__actions {
  display: flex;
  align-items: center;
  gap: 12px;
}

.answer-heading span,
.answer-heading h1 {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.answer-heading > div:first-child > span {
  color: var(--chat-muted);
  font-size: 14px;
}

.answer-heading h1 {
  margin: 0;
  color: var(--chat-text);
  font-size: 20px;
  font-weight: 650;
}

.answer-status {
  display: inline-flex;
  min-height: 32px;
  align-items: center;
  gap: 7px;
  padding: 0 9px;
  border: 1px solid var(--chat-border);
  border-radius: 7px;
  color: var(--chat-secondary);
  background: var(--color-surface);
  font-size: 14px;
}

.status-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--chat-muted);
}

.answer-status[data-status="streaming"] .status-dot,
.answer-status[data-status="queued"] .status-dot {
  background: var(--chat-primary);
  animation: pulse 1.2s ease-in-out infinite;
}

.answer-status[data-status="failed"] .status-dot {
  background: var(--chat-danger);
}

.course-picker {
  position: relative;
}

.course-picker__trigger {
  display: inline-flex;
  max-width: 300px;
  min-height: 36px;
  align-items: center;
  gap: 7px;
  border: 1px solid var(--chat-border);
  border-radius: 6px;
  padding: 0 10px;
  background: var(--color-surface);
  color: var(--chat-secondary);
  font-size: 14px;
  cursor: pointer;
}

.course-picker__trigger span:nth-child(2) {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.course-picker__trigger:hover {
  border-color: var(--chat-border-strong);
  background: var(--chat-subtle);
}

.course-picker__chevron {
  color: var(--chat-muted);
  font-size: 16px;
}

.course-picker__panel {
  position: absolute;
  top: calc(100% + 8px);
  right: 0;
  z-index: 20;
  display: grid;
  width: 320px;
  gap: 10px;
  border: 1px solid var(--chat-border);
  border-radius: 8px;
  padding: 14px;
  background: var(--color-surface);
  box-shadow: 0 16px 34px rgb(6 20 27 / 14%);
}

.course-picker__panel > header,
.course-picker__panel > footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.course-picker__panel > header strong {
  color: var(--chat-text);
  font-size: 14px;
}

.course-picker__panel > p {
  margin: 0;
  color: var(--chat-muted);
  font-size: 14px;
  line-height: 1.5;
}

.course-picker__group {
  display: grid;
  gap: 3px;
  max-height: 220px;
  overflow-y: auto;
}

.course-picker__group-title {
  padding: 3px 4px;
  color: var(--chat-muted);
  font-size: 14px;
  font-weight: 620;
}

.course-picker__option {
  display: flex;
  min-width: 0;
  align-items: flex-start;
  gap: 9px;
  padding: 7px 4px;
  border-radius: 6px;
  cursor: pointer;
}

.course-picker__option:hover {
  background: var(--chat-subtle);
}

.course-picker__option input {
  width: 16px;
  height: 16px;
  flex: 0 0 16px;
  margin-top: 2px;
  accent-color: var(--chat-primary);
}

.course-picker__option span {
  display: grid;
  min-width: 0;
  gap: 2px;
}

.course-picker__option strong,
.course-picker__option small {
  overflow: hidden;
  font-size: 14px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.course-picker__option strong {
  color: var(--chat-text);
}

.course-picker__option small {
  color: var(--chat-muted);
}

.course-picker__state,
.course-picker__error {
  display: flex;
  min-height: 36px;
  align-items: center;
  gap: 8px;
  color: var(--chat-muted);
  font-size: 14px;
  line-height: 1.45;
}

.course-picker__error {
  flex-wrap: wrap;
  color: var(--chat-danger);
}

.message-scroller {
  min-height: 0;
  overflow-y: auto;
  background: var(--gradient-paper);
  scrollbar-gutter: stable;
}

.quiz-context {
  width: min(760px, calc(100% - 48px));
  margin: 24px auto 8px;
}

.quiz-context > header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 10px;
}

.quiz-context > header > div {
  display: grid;
  gap: 2px;
}

.quiz-context > header span {
  color: var(--chat-muted);
  font-size: 14px;
}

.quiz-context > header strong {
  font-size: 16px;
}

.quiz-context > header > span {
  color: var(--chat-secondary);
  font-size: 14px;
}

.quiz-context__body,
.quiz-context__empty {
  display: grid;
  gap: 14px;
  border: 1px solid var(--chat-border);
  border-radius: 8px;
  padding: 18px;
  background: transparent;
}

.quiz-context__summary {
  display: grid;
  gap: 7px;
}

.quiz-context__summary > span,
.quiz-context__summary small,
.quiz-context__sources > span {
  color: var(--chat-muted);
  font-size: 14px;
  line-height: 1.55;
}

.quiz-context__summary p {
  margin: 0;
  color: var(--chat-text);
  font-size: 16px;
  font-weight: 650;
  line-height: 1.65;
}

.quiz-context__sources {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}

.quiz-context__sources button,
.quiz-context__primary {
  display: inline-flex;
  min-height: 38px;
  align-items: center;
  justify-content: center;
  gap: 7px;
  border: 1px solid var(--chat-border-strong);
  border-radius: 8px;
  padding: 0 11px;
  background: var(--color-surface);
  color: var(--chat-primary);
  font-family: inherit;
  font-size: 14px;
  cursor: pointer;
}

.quiz-context__primary {
  justify-self: start;
  border-color: var(--chat-primary);
  background: var(--chat-primary);
  color: #ffffff;
  font-weight: 650;
}

.quiz-context__empty > div {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  color: var(--chat-secondary);
  font-size: 14px;
  line-height: 1.55;
}

.quiz-context__sources button:focus-visible,
.quiz-context__primary:focus-visible {
  outline: 2px solid var(--chat-primary);
  outline-offset: 2px;
}

.inline-state,
.inline-error {
  display: flex;
  min-height: 72px;
  align-items: center;
  justify-content: center;
  gap: 9px;
  padding: var(--space-panel-block) var(--space-row-inline);
  border: 1px solid var(--chat-border);
  border-radius: 8px;
  color: var(--chat-secondary);
  background: transparent;
  font-size: 14px;
}

.inline-error {
  color: var(--chat-danger);
}

.center-state {
  min-height: 240px;
  flex-direction: column;
}

.empty-conversation {
  display: grid;
  min-height: min(460px, 100%);
  place-content: center;
  justify-items: center;
  padding: 64px 40px 90px;
  text-align: center;
}

.empty-mark {
  display: grid;
  width: 48px;
  height: 48px;
  place-items: center;
  border: 1px solid var(--chat-border);
  border-radius: 8px;
  color: var(--chat-primary);
  background: transparent;
}

.empty-conversation h2 {
  margin: 18px 0 7px;
  font-family: var(--font-heading);
  font-size: 28px;
  font-weight: 620;
}

.empty-conversation p {
  max-width: 48ch;
  margin: 0;
  color: var(--chat-secondary);
  font-size: 15px;
  line-height: 1.7;
}

.message-list {
  width: min(880px, calc(100% - 64px));
  margin: 0 auto;
  padding: 34px 0 48px;
}

.message-row {
  position: relative;
  display: grid;
  min-width: 0;
  margin-bottom: 28px;
}

.message-row--user {
  justify-items: end;
}

.message-row--user > time {
  margin-top: 5px;
  color: var(--chat-muted);
  font-size: 14px;
}

.user-message {
  max-width: min(78%, 620px);
  border-radius: 8px 8px 2px 8px;
  padding: 11px 14px;
  color: var(--chat-text);
  background: var(--chat-subtle);
}

.user-message p {
  margin: 0;
  white-space: pre-wrap;
  font-size: 15px;
  line-height: 1.7;
}

.message-file-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 9px;
}

.message-file-list span {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  color: var(--chat-secondary);
  font-size: 14px;
}

.assistant-label {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
  color: var(--chat-muted);
  font-size: 14px;
}

.assistant-label strong {
  color: var(--chat-text);
  font-size: 14px;
}

.assistant-label time {
  margin-left: auto;
}

.assistant-mark {
  display: grid;
  width: 28px;
  height: 28px;
  place-items: center;
  border-radius: 6px;
  color: #ffffff;
  background: var(--chat-primary);
  font-size: 14px;
  font-weight: 700;
}

.assistant-answer {
  min-width: 0;
  max-width: 760px;
  padding-left: 40px;
  color: var(--chat-text);
  font-size: 16px;
  line-height: 1.82;
}

.answer-pending {
  display: flex;
  min-height: 44px;
  align-items: center;
  gap: 9px;
  color: var(--chat-secondary);
  font-size: 14px;
}

.stream-progress {
  height: 2px;
  margin: 12px 0 0 36px;
  overflow: hidden;
  background: var(--chat-subtle);
}

.stream-progress span {
  display: block;
  height: 100%;
  background: var(--chat-primary);
}

.message-failure {
  display: flex;
  align-items: flex-start;
  gap: 9px;
  margin: 14px 0 0 36px;
  border: 1px solid var(--chat-border);
  padding: 10px 12px;
  color: var(--chat-danger);
  background: var(--color-danger-soft);
}

.message-failure > div {
  display: grid;
  gap: 2px;
}

.message-workflow {
  margin: 14px 0 0 36px;
  border: 1px solid var(--chat-border);
  border-radius: 8px;
  background: var(--color-surface);
}

.message-workflow summary {
  display: flex;
  min-height: 40px;
  align-items: center;
  gap: 8px;
  padding: 0 12px;
  color: var(--chat-secondary);
  font-size: 14px;
  cursor: pointer;
}

.message-workflow :deep(.agent-audit) {
  border-top: 1px solid var(--chat-border);
  padding: 0 12px;
}

.message-failure strong,
.message-failure span {
  font-size: 14px;
}

.resource-link-list {
  display: grid;
  gap: 6px;
  margin: 14px 0 0 36px;
}

.resource-link-list button,
.source-list button {
  display: grid;
  width: 100%;
  grid-template-columns: 20px minmax(0, 1fr) 18px;
  align-items: center;
  gap: 9px;
  border: 1px solid var(--chat-border);
  border-radius: 6px;
  padding: 9px 10px;
  background: var(--color-surface);
  text-align: left;
  cursor: pointer;
}

.resource-link-list button:hover,
.source-list button:hover {
  border-color: var(--chat-border-strong);
  background: transparent;
}

.resource-link-list button > span,
.source-list button > span {
  display: grid;
  min-width: 0;
  gap: 1px;
}

.resource-link-list strong,
.source-list strong,
.resource-link-list small,
.source-list small {
  overflow: hidden;
  font-size: 14px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.resource-link-list small,
.source-list small {
  color: var(--chat-muted);
}

.message-actions {
  display: flex;
  min-height: 38px;
  align-items: center;
  gap: 8px;
  margin: 12px 0 0 36px;
}

.grounding-action {
  margin: 12px 0 0 36px;
}

.text-button,
.stop-button,
.send-button,
.confirm-button,
.return-button {
  display: inline-flex;
  min-height: 36px;
  align-items: center;
  justify-content: center;
  gap: 7px;
  border: 1px solid var(--chat-border);
  border-radius: 6px;
  padding: 0 10px;
  background: var(--color-surface);
  font-size: 14px;
  cursor: pointer;
}

.text-button:hover,
.confirm-button:hover,
.return-button:hover {
  border-color: var(--chat-border-strong);
  background: transparent;
}

.composer {
  position: relative;
  z-index: 5;
  border-top: 1px solid var(--chat-border);
  padding: 14px clamp(20px, 2.2vw, 36px) 18px;
  background: transparent;

  box-shadow: none;
}

.attachment-queue {
  margin-bottom: 8px;
  overflow: hidden;
  border: 1px solid var(--chat-border);
  border-radius: 8px;
  background: var(--color-surface);
}

.attachment-queue__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  min-height: 44px;
  padding: 7px 10px 7px 12px;
  border-bottom: 0;
}

.attachment-queue__summary {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: 8px;
}

.attachment-queue__summary > span {
  overflow: hidden;
  color: var(--chat-muted);
  font-size: 14px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.attachment-toggle {
  display: inline-flex;
  flex: 0 0 auto;
  align-items: center;
  gap: 6px;
  min-height: 32px;
  padding: 4px 8px;
  border: 1px solid var(--chat-border-strong);
  border-radius: 6px;
  color: var(--chat-secondary);
  background: var(--color-surface);
  cursor: pointer;
  font-size: 14px;
}

.attachment-toggle:hover {
  border-color: var(--chat-primary);
  color: var(--chat-primary);
}

.attachment-toggle:focus-visible {
  outline: 2px solid var(--chat-primary);
  outline-offset: 2px;
}

.attachment-queue__list {
  max-height: 190px;
  overflow-y: auto;
}

.attachment-row {
  position: relative;
  display: grid;
  min-height: 62px;
  grid-template-columns: 30px 24px minmax(0, 1fr) auto;
  align-items: center;
  gap: 8px;
  padding: 8px 9px;
  overflow: hidden;
  border-bottom: 0;
}

.attachment-row:last-child {
  border-bottom: 0;
}

.attachment-select {
  display: grid;
  width: 30px;
  height: 30px;
  place-items: center;
  cursor: pointer;
}

.attachment-select input {
  position: absolute;
  opacity: 0;
  pointer-events: none;
}

.attachment-select span {
  display: grid;
  width: 22px;
  height: 22px;
  place-items: center;
  border: 1px solid var(--chat-border-strong);
  border-radius: 4px;
  color: transparent;
  background: var(--color-surface);
}

.attachment-select input:checked + span {
  color: #ffffff;
  border-color: var(--chat-primary);
  background: var(--chat-primary);
}

.attachment-select input:disabled + span {
  background: var(--chat-subtle);
  cursor: default;
}

.attachment-type {
  color: var(--chat-secondary);
}

.attachment-copy {
  display: grid;
  min-width: 0;
  gap: 1px;
}

.attachment-copy strong,
.attachment-copy span,
.attachment-copy small {
  overflow: hidden;
  font-size: 14px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.attachment-copy span {
  color: var(--chat-muted);
}

.attachment-copy small {
  color: var(--chat-danger);
}

.attachment-actions {
  display: flex;
  align-items: center;
  gap: 5px;
}

.attachment-actions .icon-button {
  width: 32px;
  height: 32px;
  flex-basis: 32px;
}

.confirm-button {
  min-height: 32px;
}

.attachment-progress {
  position: absolute;
  bottom: 0;
  left: 0;
  height: 2px;
  background: var(--chat-primary);
}

.composer-box {
  border: 1px solid var(--chat-border-strong);
  border-radius: 16px;
  background: var(--color-surface);

  box-shadow: 0 6px 24px rgb(68 53 52 / 5%);
}

.composer-box:focus-within {
  border-color: var(--chat-primary);
  box-shadow: 0 0 0 2px rgba(17, 33, 45, .08);
}

.composer-input {
  display: block;
  width: 100%;
  min-height: 70px;
  max-height: 160px;
  resize: none;
  border: 0;
  padding: 12px 14px 6px;
  outline: 0;
  color: var(--chat-text);
  background: transparent;
  font-size: 15px;
  line-height: 1.6;
}

.composer-input::placeholder {
  color: var(--chat-muted);
}

.composer-tools {
  display: flex;
  min-height: 44px;
  align-items: center;
  gap: 8px;
  padding: 5px 7px 7px;
}

.composer-tools .icon-button {
  border-color: transparent;
}

.composer-resource-picker {
  position: relative;
}

.resource-picker-trigger {
  display: inline-flex;
  min-height: 32px;
  align-items: center;
  gap: 6px;
  border: 1px solid transparent;
  border-radius: 6px;
  padding: 0 8px;
  color: var(--chat-secondary);
  background: transparent;
  font-size: 14px;
  cursor: pointer;
}

.resource-picker-trigger:hover,
.composer-resource-picker.open .resource-picker-trigger {
  border-color: var(--chat-border);
  background: var(--chat-subtle);
  color: var(--chat-text);
}

.resource-picker-trigger small {
  display: grid;
  min-width: 18px;
  height: 18px;
  place-items: center;
  border-radius: 9px;
  color: #ffffff;
  background: var(--chat-primary);
  font-size: 14px;
  line-height: 1;
}

.resource-picker-panel {
  position: absolute;
  z-index: 12;
  bottom: calc(100% + 8px);
  left: 0;
  display: grid;
  width: min(330px, calc(100vw - 40px));
  gap: 8px;
  padding: 12px;
  border: 1px solid var(--chat-border-strong);
  border-radius: 8px;
  background: var(--color-surface);
  box-shadow: 0 14px 30px rgba(17, 33, 45, .14);
}

.resource-picker-panel header,
.resource-picker-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.resource-picker-panel header {
  justify-content: space-between;
  padding-bottom: 4px;
  border-bottom: 0;
}

.resource-picker-panel header span {
  color: var(--chat-muted);
  font-size: 14px;
}

.resource-picker-actions {
  justify-content: flex-end;
}

.resource-picker-actions button {
  border: 0;
  padding: 2px 4px;
  color: var(--chat-secondary);
  background: transparent;
  font-size: 14px;
  cursor: pointer;
}

.resource-picker-actions button:hover {
  color: var(--chat-text);
  text-decoration: underline;
}

.resource-picker-option {
  display: flex;
  min-height: 32px;
  align-items: center;
  gap: 9px;
  padding: 4px 6px;
  border-radius: 6px;
  color: var(--chat-secondary);
  cursor: pointer;
}

.resource-picker-option:hover {
  background: var(--chat-subtle);
  color: var(--chat-text);
}

.resource-picker-option input {
  width: 15px;
  height: 15px;
  accent-color: var(--chat-primary);
}

.resource-picker-hint {
  margin: 2px 0 0;
  color: var(--chat-muted);
  font-size: 14px;
  line-height: 1.45;
}

.send-reason {
  overflow: hidden;
  font-size: 14px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.send-reason {
  margin-left: auto;
  color: var(--chat-muted);
}

.send-button,
.stop-button {
  min-width: 78px;
  margin-left: auto;
  border-color: var(--chat-primary);
  color: #ffffff;
  background: var(--chat-primary);
  font-weight: 620;
}

.send-reason + .send-button,
.send-reason + .stop-button {
  margin-left: 0;
}

.send-button:disabled {
  cursor: default;
  opacity: .42;
}

.composer-recovery,
.composer-error {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 8px 0 0;
  color: var(--chat-danger);
  font-size: 14px;
  line-height: 1.5;
}

.composer-recovery .text-button {
  margin-left: auto;
}

.evidence-heading {
  position: sticky;
  top: 0;
  z-index: 2;
  background: var(--color-surface);
}

.evidence-tabs {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 4px;
  border-bottom: 0;
  padding: 8px;
  background: var(--color-surface);
}

.evidence-tabs button {
  min-height: 34px;
  border: 1px solid transparent;
  border-radius: 5px;
  padding: 0 6px;
  color: var(--chat-muted);
  background: transparent;
  font-size: 14px;
  cursor: pointer;
}

.evidence-tabs button:hover,
.evidence-tabs button.active {
  border-color: var(--chat-border);
  color: var(--chat-text);
  background: transparent;
}

.evidence-section {
  border-bottom: 0;
  padding: 16px;
}

.evidence-section--agent {
  padding-top: 6px;
  padding-bottom: 6px;
}
.profile-adaptation-section{background:var(--chat-subtle);border:1px solid var(--chat-border);border-radius:8px}
.profile-adaptation-summary{margin:8px 0;color:var(--chat-secondary);font-size:14px;line-height:1.55}
.profile-adaptation-section dl{display:grid;gap:6px;margin:8px 0 0}.profile-adaptation-section dl>div{display:flex;justify-content:space-between;gap:10px}.profile-adaptation-section dt{color:var(--chat-muted);font-size:14px}.profile-adaptation-section dd{margin:0;text-align:right;font-size:14px;line-height:1.4;overflow-wrap:anywhere}

.evidence-section > header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
  color: var(--chat-secondary);
}

.evidence-section > header strong {
  color: var(--chat-text);
  font-size: 14px;
}

.evidence-section dl {
  display: grid;
  gap: 8px;
  margin: 0;
}

.evidence-section dl > div {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.evidence-section dt,
.evidence-section dd {
  margin: 0;
  font-size: 14px;
}

.evidence-section dt {
  color: var(--chat-muted);
}

.evidence-section dd {
  color: var(--chat-text);
  text-align: right;
}

.context-list,
.source-list,
.evidence-file-list {
  display: grid;
  gap: 7px;
}

.context-list > div {
  display: grid;
  gap: 2px;
  border-left: 2px solid var(--chat-border-strong);
  padding-left: 9px;
}

.context-list span,
.context-list strong,
.context-list small {
  overflow: hidden;
  font-size: 14px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.context-list span,
.context-list small {
  color: var(--chat-muted);
}

.source-list button {
  grid-template-columns: minmax(0, 1fr) 18px;
}

.course-source-entry {
  display: grid;
  gap: 4px;
  min-width: 0;
}

.course-source-group { min-width: 0; }
.course-source-group h3 { margin: 8px 0 5px; font-size: 15px; line-height: 1.5; color: var(--chat-text); }
.course-source-group .course-source-entry { border-left: 1px solid var(--color-border); padding-left: 10px; }

.course-source-meta {
  padding-left: 2px;
  color: var(--chat-muted);
  line-height: 1.45;
  overflow-wrap: anywhere;
}

.evidence-file-list > div {
  display: grid;
  grid-template-columns: 20px minmax(0, 1fr);
  align-items: center;
  gap: 8px;
  padding: 5px 0;
}

.evidence-file-list > div > span {
  display: grid;
  min-width: 0;
  gap: 1px;
}

.evidence-file-entry {
  grid-template-columns: 18px minmax(0, 1fr) auto !important;
  align-items: start !important;
}

.evidence-file-actions {
  display: flex;
  gap: 4px;
  align-items: center;
}

.evidence-file-list strong,
.evidence-file-list small {
  overflow: hidden;
  font-size: 14px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.evidence-file-list small {
  color: var(--chat-muted);
}

.removed-file {
  color: var(--chat-muted);
}

.evidence-empty {
  margin: 0;
  color: var(--chat-muted);
  font-size: 14px;
  line-height: 1.6;
}

.return-button {
  width: calc(100% - 32px);
  margin: 16px;
}

.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
}

button:focus-visible,
textarea:focus-visible,
.archive-action:focus-visible,
.attachment-select:focus-within {
  outline: 2px solid var(--chat-primary);
  outline-offset: 2px;
}

/* The composer owns the focus ring; avoid a second outline inside the same field. */
.composer-input:focus,
.composer-input:focus-visible {
  outline: 0;
  outline-offset: 0;
}

.spin {
  animation: spin .8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

@keyframes pulse {
  50% { opacity: .35; }
}

/* Phase 6: quiet editorial workspace refinements. Existing stores, APIs and
 * interaction contracts remain unchanged; these rules tune hierarchy and
 * resilient desktop behavior. */
.chat-workspace {
  isolation: isolate;
  box-shadow: 0 10px 28px rgb(19 36 43 / 5%);
}

.conversation-rail {
  background: var(--gradient-rail);
}

.rail-heading > div {
  gap: 9px;
  letter-spacing: .04em;
}

.rail-heading > div::before {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: var(--chat-primary);
  content: '';
}

.conversation-list,
.message-scroller,
.evidence-rail,
.course-picker__panel {
  scrollbar-color: var(--chat-border-strong) transparent;
  scrollbar-width: thin;
}

.conversation-item {
  transition: background-color .18s ease, box-shadow .18s ease;
}

.conversation-item:active,
.text-button:active,
.icon-button:active,
.course-picker__trigger:active,
.resource-picker-trigger:active,
.send-button:active,
.stop-button:active {
  transform: translateY(1px);
}

.conversation-copy strong {
  overflow-wrap: anywhere;
  white-space: normal;
}

.conversation-copy strong {
  display: -webkit-box;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}

.answer-heading {
  min-width: 0;
  gap: 18px;
}

.answer-heading > div:first-child {
  flex: 1 1 auto;
  min-width: 0;
}

.answer-heading__context,
.answer-heading__title {
  min-width: 0;
  max-width: 100%;
  overflow-wrap: anywhere;
  white-space: normal !important;
}

.answer-heading__context {
  white-space: nowrap !important;
  color: var(--chat-muted) !important;
  font-size: 14px !important;
  line-height: 1.35;
}

.answer-heading__title {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap !important;
  line-height: 1.3;
}

.answer-heading__actions {
  min-width: 0;
  flex: 0 0 auto;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.course-picker__trigger {
  max-width: min(340px, 30vw);
}

.course-picker__panel {
  max-height: min(620px, calc(100vh - 120px));
  overflow-y: auto;
}

.empty-conversation {
  align-content: start;
  min-height: min(480px, 100%);
  padding-top: clamp(76px, 10vh, 144px);
}

.empty-conversation h2 {
  font-family: var(--font-editorial);
  font-weight: 400;
  font-size: 32px;
  max-width: 20ch;
  line-height: 1.25;
}

.empty-conversation p {
  max-width: 54ch;
}

.message-row {
  margin-bottom: 34px;
}

.user-message {
  max-width: min(78%, 660px);
  padding: 13px 16px;
  background: var(--gradient-highlight);
}

.user-message p {
  font-size: 16px;
  line-height: 1.72;
  overflow-wrap: anywhere;
}

.assistant-label {
  margin-bottom: 12px;
}

.assistant-answer {
  overflow-wrap: anywhere;
}

.assistant-answer :deep(.incremental-md-renderer) {
  max-width: 72ch;
  font-size: 16px;
  line-height: 1.82;
}

.assistant-answer :deep(.inc-paragraph) {
  margin-bottom: 16px;
}

.assistant-answer :deep(.inc-heading) {
  margin-top: 28px;
  margin-bottom: 12px;
  color: var(--color-text);
}

.assistant-answer :deep(.inc-heading--1) {
  font-size: 22px;
}

.assistant-answer :deep(.inc-heading--2) {
  font-size: 19px;
}

.assistant-answer :deep(.inc-heading--3),
.assistant-answer :deep(.inc-heading--4) {
  font-size: 17px;
}

.assistant-answer :deep(.inc-list) {
  margin-top: 10px;
  margin-bottom: 20px;
}

.assistant-answer :deep(.inc-list li) {
  line-height: 1.78;
}

.assistant-answer :deep(.inc-blockquote) {
  margin-block: 20px;
  border-left-width: 2px;
  padding: 13px 17px;
  background: var(--color-surface-subtle);
}

.assistant-answer :deep(.code-block-wrapper),
.assistant-answer :deep(.math-block),
.assistant-answer :deep(.mermaid-block) {
  max-width: 100%;
}

.assistant-answer :deep(.code-block-wrapper) {
  margin-block: 20px;
  box-shadow: 0 8px 20px rgb(19 36 43 / 9%);
}

.assistant-answer :deep(.code-block-wrapper pre) {
  max-width: 100%;
  overflow-x: auto;
  white-space: pre;
  scrollbar-color: #708791 transparent;
  scrollbar-width: thin;
}

.assistant-answer :deep(.inc-link) {
  overflow-wrap: anywhere;
}

.message-workflow,
.resource-link-list,
.message-actions,
.grounding-action,
.stream-progress,
.message-failure {
  margin-left: 40px;
}

.resource-link-list button,
.source-list button {
  min-width: 0;
}

.composer {
  box-shadow: 0 -8px 20px rgb(19 36 43 / 4%);
}

.composer-box {
  border-radius: 10px;
  box-shadow: 0 2px 0 rgb(19 36 43 / 2%);
}

.composer-input {
  min-height: 78px;
  max-height: 190px;
  padding: 14px 16px 8px;
  font-size: 16px;
  line-height: 1.65;
}

.composer-tools {
  min-width: 0;
  flex-wrap: wrap;
  row-gap: 6px;
}

.send-reason {
  max-width: 250px;
  overflow-wrap: anywhere;
  white-space: normal;
  text-align: right;
}

.evidence-rail.collapsed .evidence-heading button {
  border-color: var(--chat-border-strong);
  background: var(--color-surface);
}

.evidence-tabs {
  position: sticky;
  top: 72px;
  z-index: 2;
}

.evidence-section {
  padding: 18px;
}

.evidence-section > header strong {
  font-size: 15px;
}

.context-list strong,
.course-source-meta,
.evidence-file-list strong,
.evidence-file-list small {
  overflow-wrap: anywhere;
  white-space: normal;
}

.return-button {
  max-width: calc(100% - 36px);
  overflow-wrap: anywhere;
  white-space: normal;
}

@media (min-width: 2200px) {
  .chat-workspace {
    grid-template-columns: 300px minmax(0, 1fr) 392px;
  }

  .chat-workspace--rail-collapsed {
    grid-template-columns: 300px minmax(0, 1fr) 56px;
  }
}

@media (max-width: 1500px) {
  .chat-workspace {
    grid-template-columns: 236px minmax(0, 1fr) 304px;
  }

  .chat-workspace--rail-collapsed {
    grid-template-columns: 236px minmax(0, 1fr) 56px;
  }

  .answer-heading {
    gap: 10px;
  }

  .course-picker__trigger {
    max-width: 260px;
  }
}

@media (prefers-reduced-motion: reduce) {
  .chat-workspace *,
  .chat-workspace *::before,
  .chat-workspace *::after {
    animation-duration: .01ms !important;
    animation-iteration-count: 1 !important;
    scroll-behavior: auto !important;
    transition-duration: .01ms !important;
  }
}
</style>
