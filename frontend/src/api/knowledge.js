import { api, buildHeaders } from './common'

export async function getDatasets() {
  const r = await api.get('/datasets', { headers: buildHeaders() })
  return r.data
}

export async function uploadKnowledgeDocument(file, studentId = 'default', onProgress) {
  const form = new FormData()
  form.append('file', file)
  form.append('student_id', studentId)
  const r = await api.post(`/knowledge/upload?student_id=${encodeURIComponent(studentId)}`, form, {
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
