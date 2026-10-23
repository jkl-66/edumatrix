import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { useContextStore } from './context'
import {
  clearStoredContext,
  contextErrorDetail,
  contextRefFromRoute,
  loadStoredContext,
  normalizeContextRef,
  resolveContext,
  saveStoredContext,
} from '../services/context'

const STALE_CONTEXT_CODES = new Set([
  'context_course_unavailable',
  'context_object_not_found',
  'context_forbidden',
])

export const useCourseContextStore = defineStore('course-context', () => {
  const contextRef = ref(loadStoredContext())
  const resolution = ref(null)
  const status = ref(contextRef.value.courseId ? 'restoring' : 'missing_course')
  const error = ref(null)
  const usingLegacyFallback = ref(false)
  const chatCourseIds = ref([])

  const course = computed(() => resolution.value?.course || null)
  const knowledgePoint = computed(() => resolution.value?.knowledgePoint || null)
  const label = computed(() => {
    const courseTitle = course.value?.title
      || (contextRef.value.courseId ? '当前课程' : '选择当前课程')
    return knowledgePoint.value?.title ? `${courseTitle} · ${knowledgePoint.value.title}` : courseTitle
  })

  async function restoreFromRoute(route, contextOverride = null) {
    const candidate = normalizeContextRef({
      ...contextRefFromRoute(route),
      ...(contextOverride || {}),
    })
    contextRef.value = candidate
    chatCourseIds.value = candidate.courseId ? [candidate.courseId] : []
    error.value = null
    usingLegacyFallback.value = false
    if (!candidate.courseId) {
      status.value = 'missing_course'
      resolution.value = null
      return null
    }
    status.value = 'restoring'
    try {
      const result = await resolveContext(candidate)
      resolution.value = result
      contextRef.value = saveStoredContext(result.context)
      useContextStore().setCourse(result.course)
      status.value = 'ready'
      return result
    } catch (requestError) {
      const structuredContextError = contextErrorDetail(requestError)
      const requestStatus = Number(requestError?.status || requestError?.response?.status || 0)
      if (!requestStatus || requestStatus >= 500) {
        try {
          const legacyCourse = await useContextStore().loadCourse(candidate.courseId)
          resolution.value = {
            context: candidate,
            course: legacyCourse,
            knowledgePoint: null,
            fallback: 'legacy_course_picker',
          }
          contextRef.value = saveStoredContext({ ...candidate, version: null })
          usingLegacyFallback.value = true
          status.value = 'fallback'
          return resolution.value
        } catch {
          const unavailable = {
            code: 'context_service_unavailable',
            message: '暂时无法验证当前学习位置，请稍后重试或重新选择课程',
            field: null,
            status: requestStatus,
            context: candidate,
          }
          error.value = unavailable
          status.value = 'invalid'
          throw Object.assign(requestError, { contextDetail: unavailable })
        }
      }
      if (!structuredContextError) {
        error.value = null
        status.value = 'invalid'
        throw requestError
      }
      if (STALE_CONTEXT_CODES.has(structuredContextError.code)) {
        contextRef.value = clearStoredContext({ keepCourse: false })
        resolution.value = null
        chatCourseIds.value = []
        useContextStore().setCourse(null)
      }
      error.value = { ...structuredContextError, status: requestStatus, context: candidate }
      status.value = 'invalid'
      throw Object.assign(requestError, { contextDetail: error.value })
    }
  }

  function clear({ keepCourse = true } = {}) {
    contextRef.value = clearStoredContext({ keepCourse })
    resolution.value = null
    error.value = null
    usingLegacyFallback.value = false
    status.value = contextRef.value.courseId ? 'restoring' : 'missing_course'
    chatCourseIds.value = contextRef.value.courseId ? [contextRef.value.courseId] : []
  }

  function setChatCourseIds(ids = []) {
    chatCourseIds.value = [...new Set((ids || []).map((id) => String(id)).filter(Boolean))]
  }

  return {
    contextRef,
    resolution,
    status,
    error,
    usingLegacyFallback,
    chatCourseIds,
    course,
    knowledgePoint,
    label,
    restoreFromRoute,
    clear,
    setChatCourseIds,
  }
})
