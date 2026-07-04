import { api, buildHeaders } from './common'

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
