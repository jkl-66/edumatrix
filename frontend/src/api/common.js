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

export async function healthCheck() {
  const r = await api.get('/health', { headers: buildHeaders() })
  return r.data
}

export async function loginUser(username, password) {
  const params = new URLSearchParams()
  params.append('username', username)
  params.append('password', password)
  const r = await api.post('/auth/login', params, {
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' }
  })
  return r.data
}

export async function registerUser(username, password, displayName) {
  const r = await api.post('/auth/register', {
    username,
    password,
    display_name: displayName
  })
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
