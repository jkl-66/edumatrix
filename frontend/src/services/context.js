import { api, buildHeaders } from '../api'

export const CONTEXT_STORAGE_KEY = 'edumatrix_context_ref'

const EMPTY_CONTEXT = Object.freeze({
  userId: null,
  courseId: null,
  chapterId: null,
  knowledgePointId: null,
  taskId: null,
  resourceId: null,
  sourceRefId: null,
  attemptId: null,
  version: null,
})

function value(input) {
  const normalized = String(input || '').trim()
  return normalized || null
}

export function normalizeContextRef(input = {}) {
  return Object.fromEntries(
    Object.keys(EMPTY_CONTEXT).map((key) => [key, value(input[key])]),
  )
}

export function loadStoredContext() {
  try {
    return normalizeContextRef(JSON.parse(localStorage.getItem(CONTEXT_STORAGE_KEY) || '{}'))
  } catch {
    return { ...EMPTY_CONTEXT }
  }
}

export function saveStoredContext(context) {
  const normalized = normalizeContextRef(context)
  localStorage.setItem(CONTEXT_STORAGE_KEY, JSON.stringify(normalized))
  if (normalized.courseId) localStorage.setItem('edumatrix_course_id', normalized.courseId)
  return normalized
}

export function clearStoredContext({ keepCourse = true } = {}) {
  const current = loadStoredContext()
  const next = { ...EMPTY_CONTEXT, courseId: keepCourse ? current.courseId : null }
  saveStoredContext(next)
  if (!keepCourse) {
    localStorage.removeItem('edumatrix_course_id')
    localStorage.removeItem('edumatrix_course_title')
  }
  return next
}

export function discardStoredCourse() {
  return clearStoredContext({ keepCourse: false })
}

function routeValue(route, camel, snake = '') {
  return value(
    route?.params?.[camel]
      || route?.query?.[camel]
      || (snake ? route?.query?.[snake] : null),
  )
}

export function contextRefFromRoute(route) {
  const stored = loadStoredContext()
  const explicitCourseId = routeValue(route, 'courseId', 'course_id')
  const courseChanged = Boolean(explicitCourseId && explicitCourseId !== stored.courseId)
  const inherited = courseChanged
    ? { ...EMPTY_CONTEXT, userId: stored.userId }
    : stored
  const candidate = {
    ...inherited,
    courseId: explicitCourseId || inherited.courseId,
    chapterId: routeValue(route, 'chapterId', 'chapter_id') || inherited.chapterId,
    knowledgePointId: routeValue(route, 'knowledgePointId', 'knowledge_point_id') || inherited.knowledgePointId,
    taskId: routeValue(route, 'taskId', 'task_id') || inherited.taskId,
    resourceId: routeValue(route, 'resourceId', 'resource_id') || inherited.resourceId,
    sourceRefId: routeValue(route, 'sourceRefId', 'source_ref_id') || inherited.sourceRefId,
    attemptId: routeValue(route, 'attemptId', 'attempt_id') || inherited.attemptId,
  }
  const identityChanged = Object.keys(EMPTY_CONTEXT)
    .filter((key) => key !== 'version' && key !== 'userId')
    .some((key) => value(candidate[key]) !== value(stored[key]))
  candidate.version = identityChanged
    ? routeValue(route, 'contextVersion', 'context_version')
    : routeValue(route, 'contextVersion', 'context_version') || stored.version
  return normalizeContextRef(candidate)
}

export function isContextResolutionError(error) {
  const detail = error?.contextDetail
  return Boolean(detail && String(detail.code || '').startsWith('context_'))
}

export async function resolveContext(context) {
  const response = await api.post(
    '/v1/m5/context/resolve',
    { context: normalizeContextRef(context) },
    { headers: buildHeaders() },
  )
  return response.data
}

export function contextErrorDetail(error) {
  const detail = error?.detail || error?.response?.data?.detail
  const code = detail && typeof detail === 'object' ? value(detail.code) : null
  if (!code?.startsWith('context_')) return null
  return {
    code,
    message: value(detail.message) || '学习上下文无法恢复',
    field: value(detail.field),
  }
}
