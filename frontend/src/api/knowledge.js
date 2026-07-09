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

// ── 成员 3: 图谱统计与跨模态搜索 ──
export async function getGraphStats() {
  const r = await api.get('/knowledge/graph/stats', { headers: buildHeaders() })
  return r.data
}

export async function crossModalSearch(query, mode = 'text', topK = 5) {
  const r = await api.get('/knowledge/cross-search', {
    headers: buildHeaders(),
    params: { query, mode, top_k: topK },
  })
  return r.data
}
