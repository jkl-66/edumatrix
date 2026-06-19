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

// 任务 7.6: 一键导出学情诊断 PDF
export async function exportProfilePDF(studentId) {
  const r = await api.get('/v1/profile/export', {
    params: { student_id: studentId },
    headers: { ...buildHeaders(), Accept: 'application/pdf' },
    responseType: 'blob',
  })
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

export async function uploadKnowledgeDocument(file, studentId = 'default', onProgress) {
  const form = new FormData()
  form.append('file', file)
  form.append('student_id', studentId)
  const r = await api.post('/knowledge/upload', form, {
    headers: { ...buildHeaders(), 'Content-Type': 'multipart/form-data' },
    onUploadProgress: onProgress,
  })
  return r.data
}

export async function listKnowledgeDocuments(studentId = 'default') {
  const r = await api.get(`/knowledge/list?student_id=${studentId}`, { headers: buildHeaders() })
  return r.data
}

export async function deleteKnowledgeDocument(docId, studentId = 'default') {
  const r = await api.delete(`/knowledge/${docId}?student_id=${studentId}`, { headers: buildHeaders() })
  return r.data
}

// --- Quiz API ---
export async function generateQuiz(studentId, targetConcept, difficulty = 'medium', sessionId = '') {
  const r = await api.post('/quiz/generate', {
    student_id: studentId,
    target_concept: targetConcept,
    difficulty,
    session_id: sessionId,
  }, { headers: buildHeaders() })
  return r.data
}

export async function evaluateQuizAnswer(quizId, studentId, answer, studentConfidence = 0.5, attemptNumber = 1) {
  const r = await api.post('/quiz/evaluate', {
    quiz_id: quizId,
    student_id: studentId,
    answer,
    student_confidence: studentConfidence,
    attempt_number: attemptNumber,
  }, { headers: buildHeaders() })
  return r.data
}

export async function adaptQuiz(studentId, quizId, nextAction, targetConcept = '', attemptNumber = 1, sessionId = '') {
  const r = await api.post('/quiz/adapt', {
    student_id: studentId,
    quiz_id: quizId,
    next_action: nextAction,
    target_concept: targetConcept,
    attempt_number: attemptNumber,
    session_id: sessionId,
  }, { headers: buildHeaders() })
  return r.data
}

export async function getQuizHistory(studentId) {
  const r = await api.get(`/quiz/history/${studentId}`, { headers: buildHeaders() })
  return r.data
}

// --- Web Search API ---
export async function webSearch(query, studentId = 'default') {
  const r = await api.post('/web/search', {
    query,
    student_id: studentId,
  }, { headers: buildHeaders() })
  return r.data
}

export async function loadUrl(url, studentId = 'default') {
  const r = await api.post('/web/load-url', {
    url,
    student_id: studentId,
  }, { headers: buildHeaders() })
  return r.data
}

export async function getWebSearchHistory(studentId) {
  const r = await api.get(`/web/history/${studentId}`, { headers: buildHeaders() })
  return r.data
}

// --- Code Execution API ---
export async function runCode(code, language = 'python', studentId = 'default') {
  const r = await api.post('/code/run', {
    code,
    language,
    student_id: studentId,
  }, { headers: buildHeaders() })
  return r.data
}

export async function getCodeHistory(studentId) {
  const r = await api.get(`/code/history/${studentId}`, { headers: buildHeaders() })
  return r.data
}

// --- Streaming Chat API (任务 8.2: AbortController + 内存泄漏修复) ---
const _activeStreamControllers = new Map()  // studentId -> AbortController

export function abortStream(studentId) {
  const ctrl = _activeStreamControllers.get(studentId)
  if (ctrl) {
    ctrl.abort()
    _activeStreamControllers.delete(studentId)
  }
}

export function abortAllStreams() {
  for (const [sid, ctrl] of _activeStreamControllers) {
    ctrl.abort()
  }
  _activeStreamControllers.clear()
}

export function streamChat(message, studentId, onEvent, onError) {
  // 强制终止该学生的旧连接，防止并发泄漏
  abortStream(studentId)

  const controller = new AbortController()
  _activeStreamControllers.set(studentId, controller)
  const { signal } = controller

  const headers = buildHeaders()
  const url = '/api/stream/chat'

  fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...headers },
    body: JSON.stringify({ message, student_id: studentId }),
    signal,  // 绑定 AbortSignal
  }).then(response => {
    if (!response.ok) {
      if (signal.aborted) return  // 被主动中止，不报错
      onError?.(new Error(`HTTP ${response.status}`))
      return
    }
    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''

    function read() {
      if (signal.aborted) {
        reader.cancel().catch(() => {})
        return
      }
      reader.read().then(({ done, value }) => {
        if (signal.aborted) return
        if (done) {
          _activeStreamControllers.delete(studentId)
          return
        }
        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''
        let currentEvent = ''
        for (const line of lines) {
          if (line.startsWith('event: ')) {
            currentEvent = line.slice(7).trim()
          } else if (line.startsWith('data: ')) {
            try {
              const data = JSON.parse(line.slice(6))
              onEvent?.(currentEvent, data)
            } catch {}
          }
        }
        read()
      }).catch(err => {
        if (err.name === 'AbortError') return
        onError?.(err)
      })
    }
    read()
  }).catch(err => {
    if (err.name === 'AbortError') return
    onError?.(err)
  })

  // 返回 abort 函数供组件销毁时调用
  return () => abortStream(studentId)
}

// --- Profile API ---
export async function getStudentProfile(studentId) {
  const r = await api.get(`/profile/${studentId}`, { headers: buildHeaders() })
  return r.data
}

export async function updateStudentProfile(studentId, data) {
  const r = await api.post(`/profile/${studentId}`, data, { headers: buildHeaders() })
  return r.data
}

// === 任务 7.4: 错题与复习打卡 API ===
export async function getWrongQuestions(studentId, concept = '') {
  const params = concept ? { concept } : {}
  const r = await api.get(`/quiz/wrong-questions/${studentId}`, { params, headers: buildHeaders() })
  return r.data
}

export async function getWrongConcepts(studentId) {
  const r = await api.get(`/quiz/wrong-concepts/${studentId}`, { headers: buildHeaders() })
  return r.data
}

export async function checkinReview(studentId, concept = '', durationMinutes = 10) {
  const r = await api.post(`/quiz/checkin/${studentId}`, {
    concept,
    duration_minutes: durationMinutes,
  }, { headers: buildHeaders() })
  return r.data
}

export async function getCheckinStreak(studentId) {
  const r = await api.get(`/quiz/checkin/streak/${studentId}`, { headers: buildHeaders() })
  return r.data
}
