import axios from 'axios'

function getLLMConfig() {
  try {
    const raw = localStorage.getItem('edumatrix_llm_config')
    if (raw) return JSON.parse(raw)
  } catch {}
  return {}
}

function buildHeaders() {
  const cfg = getLLMConfig()
  const headers = {}
  if (cfg.apiKey) headers['X-EduMatrix-Api-Key'] = cfg.apiKey
  if (cfg.endpoint) headers['X-EduMatrix-Endpoint'] = cfg.endpoint
  if (cfg.model) headers['X-EduMatrix-Model'] = cfg.model
  if (cfg.temperature != null) headers['X-EduMatrix-Temperature'] = String(cfg.temperature)
  if (cfg.maxTokens) headers['X-EduMatrix-Max-Tokens'] = String(cfg.maxTokens)
  return headers
}

const api = axios.create({ baseURL: '/api' })

export async function healthCheck() {
  const r = await api.get('/health', { headers: buildHeaders() })
  return r.data
}

export async function processMessage(message, studentId = 'stu-' + Date.now()) {
  const r = await api.post('/process', { message, student_id: studentId }, { headers: buildHeaders() })
  return r.data
}

export async function getTeacherDashboard() {
  const r = await api.get('/teacher', { headers: buildHeaders() })
  return r.data
}

export async function getDatasets() {
  const r = await api.get('/datasets', { headers: buildHeaders() })
  return r.data
}

export async function getHistory(studentId) {
  const r = await api.get(`/history/${studentId}`, { headers: buildHeaders() })
  return r.data
}

export async function getProgress(studentId) {
  const r = await api.get(`/progress/${studentId}`, { headers: buildHeaders() })
  return r.data
}

export async function getNotes(studentId) {
  const r = await api.get(`/notes/${studentId}`, { headers: buildHeaders() })
  return r.data
}

export async function createNote(studentId, data) {
  const r = await api.post(`/notes/${studentId}`, data, { headers: buildHeaders() })
  return r.data
}

export async function deleteNote(noteId) {
  await api.delete(`/notes/${noteId}`, { headers: buildHeaders() })
}

export async function getReviewPlans(studentId) {
  const r = await api.get(`/review/${studentId}`, { headers: buildHeaders() })
  return r.data
}

export async function createReviewPlan(studentId, data) {
  const r = await api.post(`/review/${studentId}`, data, { headers: buildHeaders() })
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

export async function getSession(sid) {
  const r = await api.get(`/sessions/${sid}`, { headers: buildHeaders() })
  return r.data
}
