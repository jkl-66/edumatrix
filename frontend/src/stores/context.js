import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { getCurrentIdentity, api, buildHeaders, normalizeApiError } from '../api'

export const useContextStore = defineStore('context', () => {
  const identity = ref(null)
  const course = ref(null)
  const loading = ref(false)
  const loadedToken = ref('')

  const role = computed(() => identity.value?.role || localStorage.getItem('edumatrix_role') || '')
  const isOperator = computed(() => ['admin', 'teacher'].includes(role.value))

  async function ensureIdentity(force = false) {
    const token = localStorage.getItem('edumatrix_token') || ''
    if (!token) {
      identity.value = null
      loadedToken.value = ''
      return null
    }
    if (!force && identity.value && loadedToken.value === token) return identity.value
    loading.value = true
    try {
      identity.value = await getCurrentIdentity()
      loadedToken.value = token
      localStorage.setItem('edumatrix_role', identity.value.role || '')
      localStorage.setItem('edumatrix_username', identity.value.username || '')
      localStorage.setItem('edumatrix_display_name', identity.value.display_name || identity.value.username || '')
      return identity.value
    } catch (error) {
      identity.value = null
      loadedToken.value = ''
      throw normalizeApiError(error)
    } finally {
      loading.value = false
    }
  }

  async function loadCourse(courseId) {
    if (!courseId) {
      course.value = null
      return null
    }
    const r = await api.get(`/v1/courses/${encodeURIComponent(courseId)}`, { headers: buildHeaders() })
    course.value = r.data
    localStorage.setItem('edumatrix_course_id', courseId)
    return course.value
  }

  function clear() {
    identity.value = null
    course.value = null
    loadedToken.value = ''
  }

  return { identity, course, loading, role, isOperator, ensureIdentity, loadCourse, clear }
})
