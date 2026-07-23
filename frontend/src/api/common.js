import axios from 'axios'

export function getLLMConfig() {
  try {
    const raw = localStorage.getItem('edumatrix_llm_config')
    if (raw) return JSON.parse(raw)
  } catch {}
  return {}
}

export function buildHeaders() {
  const cfg = getLLMConfig()
  const headers = {}
  if (cfg.apiKey) headers['X-EduMatrix-Api-Key'] = cfg.apiKey
  if (cfg.endpoint) headers['X-EduMatrix-Endpoint'] = cfg.endpoint
  if (cfg.model) headers['X-EduMatrix-Model'] = cfg.model
  if (cfg.multimodalApiKey) headers['X-EduMatrix-Multimodal-Api-Key'] = cfg.multimodalApiKey
  if (cfg.multimodalEndpoint) headers['X-EduMatrix-Multimodal-Endpoint'] = cfg.multimodalEndpoint
  if (cfg.multimodalModel) headers['X-EduMatrix-Multimodal-Model'] = cfg.multimodalModel
  const token = localStorage.getItem('edumatrix_token')
  if (token) headers['Authorization'] = `Bearer ${token}`
  if (cfg.temperature != null) headers['X-EduMatrix-Temperature'] = String(cfg.temperature)
  if (cfg.maxTokens) headers['X-EduMatrix-Max-Tokens'] = String(cfg.maxTokens)
  // 任务 9.2: 教学风格
  try {
    const style = localStorage.getItem('edumatrix_teaching_style')
    if (style) headers['X-EduMatrix-Teaching-Style'] = style
  } catch {}
  return headers
}

export const api = axios.create({ baseURL: '/api' })

export class EduMatrixApiError extends Error {
  constructor(status, detail, response = null) {
    super(detail || `请求失败 (${status || 'network'})`)
    this.name = 'EduMatrixApiError'
    this.status = status || 0
    this.detail = detail || ''
    this.response = response
    this.kind = status === 403 ? 'forbidden'
      : status === 404 ? 'not_found'
        : status === 409 ? 'conflict'
          : status === 410 ? 'archived' : status === 401 ? 'unauthorized' : 'unknown'
  }
}

export function normalizeApiError(error) {
  if (error instanceof EduMatrixApiError) return error
  const status = error?.response?.status || 0
  const detail = error?.response?.data?.detail || error?.message || '网络请求失败'
  return new EduMatrixApiError(status, detail, error?.response || null)
}

const AUTH_STORAGE_KEYS = [
  'edumatrix_token',
  'edumatrix_role',
  'edumatrix_username',
  'edumatrix_display_name',
  'edumatrix_student_id',
  'edumatrix_viewing_student',
  'edumatrix_onboarded',
]
let authRedirecting = false

function clearExpiredAuth() {
  AUTH_STORAGE_KEYS.forEach((key) => localStorage.removeItem(key))
  if (!authRedirecting && window.location.pathname !== '/login') {
    authRedirecting = true
    window.location.assign('/login?reason=session-expired')
  }
}

// A development server may restart with a new JWT secret. Clear stale browser
// state centrally so protected pages return to login instead of rendering a raw 401.
api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) clearExpiredAuth()
    return Promise.reject(normalizeApiError(error))
  },
)

export async function getCurrentIdentity() {
  const r = await api.get('/auth/me', { headers: buildHeaders() })
  return r.data
}

export async function healthCheck() {
  const r = await api.get('/health', { headers: buildHeaders() })
  return r.data
}

export async function loginUser(username, password) {
  const params = new URLSearchParams()
  params.append('username', username)
  params.append('password', password)
  
  const headers = { 'Content-Type': 'application/x-www-form-urlencoded' }
  const anonId = localStorage.getItem('edumatrix_student_id')
  if (anonId && anonId.startsWith('stu-')) {
    headers['X-Anon-Student-ID'] = anonId
  }

  const r = await api.post('/auth/login', params, { headers })
  return r.data
}

export async function registerUser(username, password, displayName) {
  const headers = {}
  const anonId = localStorage.getItem('edumatrix_student_id')
  if (anonId && anonId.startsWith('stu-')) {
    headers['X-Anon-Student-ID'] = anonId
  }

  const r = await api.post('/auth/register', {
    username,
    password,
    display_name: displayName
  }, { headers })
  return r.data
}

export async function getTeacherDashboard() {
  const r = await api.get('/teacher', { headers: buildHeaders() })
  return r.data
}

export async function submitFeedback(data) {
  const r = await api.post('/feedback', data, { headers: buildHeaders() })
  return r.data
}

export async function getFeedback() {
  const r = await api.get('/feedback', { headers: buildHeaders() })
  return r.data
}

export async function uploadBehaviorLogs(data) {
  const r = await api.post('/behavior/logs', data, { headers: buildHeaders() })
  return r.data
}
