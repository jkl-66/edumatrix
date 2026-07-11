import { api, buildHeaders } from './common'

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

export async function updateNote(noteId, data) {
  const r = await api.post(`/notes/update/${noteId}`, data, { headers: buildHeaders() })
  return r.data
}

export async function deleteNote(noteId) {
  await api.delete(`/notes/${noteId}`, { headers: buildHeaders() })
}

export async function aiPolishNote(data) {
  const r = await api.post('/notes/ai-polish', data, { headers: buildHeaders() })
  return r.data
}

export async function appendWrongQuestionReflection(data) {
  const r = await api.post('/notes/append-reflection', data, { headers: buildHeaders() })
  return r.data
}

export async function exportNotePdf(data) {
  const r = await api.post('/export-notes-pdf', data, {
    headers: buildHeaders(),
    responseType: 'blob',
  })
  // 触发浏览器下载
  const url = URL.createObjectURL(new Blob([r.data], { type: 'application/pdf' }))
  const a = document.createElement('a')
  a.href = url
  a.download = `edumatrix-${(data.title || '笔记').slice(0, 30)}.pdf`
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
  return true
}
