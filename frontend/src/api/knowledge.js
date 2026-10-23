import { api, buildHeaders } from './common'

export async function getDatasets() {
  const r = await api.get('/datasets', { headers: buildHeaders() })
  return r.data
}

export async function uploadKnowledgeDocument(file, studentId = 'default', courseId = '', onProgress) {
  const form = new FormData()
  form.append('file', file)
  form.append('student_id', studentId)
  const params = new URLSearchParams({ student_id: studentId })
  if (courseId) params.set('course_id', courseId)
  const r = await api.post(`/knowledge/upload?${params.toString()}`, form, {
    headers: { ...buildHeaders(), 'Content-Type': 'multipart/form-data' },
    onUploadProgress: onProgress,
  })
  return r.data
}

export async function listKnowledgeDocuments(studentId = 'default') {
  const r = await api.get(`/knowledge/list?student_id=${studentId}`, { headers: buildHeaders() })
  return r.data
}

export async function getKnowledgeDocument(docId, studentId = 'default') {
  const r = await api.get(`/knowledge/${docId}?student_id=${studentId}`, { headers: buildHeaders() })
  return r.data
}

export async function listKnowledgeCourseShelf() {
  const r = await api.get('/knowledge/courses', { headers: buildHeaders() })
  return r.data
}

export async function createKnowledgeCourse(payload) {
  const r = await api.post('/knowledge/courses', payload, { headers: buildHeaders() })
  return r.data
}

export async function addKnowledgeCourseToShelf(courseId) {
  const r = await api.post(
    `/knowledge/courses/${encodeURIComponent(courseId)}/shelf`,
    {},
    { headers: buildHeaders() },
  )
  return r.data
}

export async function getCourseKnowledgeGraph(courseId) {
  const r = await api.get(`/knowledge/courses/${encodeURIComponent(courseId)}/graph`, {
    headers: buildHeaders(),
  })
  return r.data
}

export async function discoverKnowledgeMaterials(query, maxResults = 8, context = {}) {
  const r = await api.get('/knowledge/discovery/search', {
    headers: buildHeaders(),
    params: {
      q: query,
      max_results: maxResults,
      ...(context.courseId ? { course_id: context.courseId } : {}),
      ...(context.profileSnapshotId ? { profile_snapshot_id: context.profileSnapshotId } : {}),
    },
  })
  return r.data
}

export async function listWebSourceCandidates(reviewStatus = '') {
  const r = await api.get('/knowledge/discovery/candidates', {
    headers: buildHeaders(),
    params: reviewStatus ? { review_status: reviewStatus } : undefined,
  })
  return r.data
}

export async function saveWebSourceCandidate(payload) {
  const r = await api.post('/knowledge/discovery/candidates', payload, {
    headers: buildHeaders(),
  })
  return r.data
}

export async function admitWebSourceCandidate(candidateId, payload) {
  const r = await api.post(
    `/knowledge/discovery/candidates/${encodeURIComponent(candidateId)}/admit`,
    payload,
    { headers: buildHeaders() },
  )
  return r.data
}

export async function rejectWebSourceCandidate(candidateId) {
  const r = await api.post(
    `/knowledge/discovery/candidates/${encodeURIComponent(candidateId)}/reject`,
    {},
    { headers: buildHeaders() },
  )
  return r.data
}

export async function withdrawWebSourceCandidate(candidateId) {
  const r = await api.post(
    `/knowledge/discovery/candidates/${encodeURIComponent(candidateId)}/withdraw`,
    {},
    { headers: buildHeaders() },
  )
  return r.data
}

export async function getCanonicalCourseSource(sourceDocumentId) {
  const r = await api.get(`/knowledge/sources/${encodeURIComponent(sourceDocumentId)}`, {
    headers: buildHeaders(),
  })
  return r.data
}

export async function getDocumentReaderDocument(sourceDocumentId) {
  const r = await api.get(`/v1/document-reader/documents/${encodeURIComponent(sourceDocumentId)}`, {
    headers: buildHeaders(),
  })
  return r.data
}

export async function getDocumentReaderState(sourceDocumentId) {
  const r = await api.get(`/v1/document-reader/state/${encodeURIComponent(sourceDocumentId)}`, {
    headers: buildHeaders(),
  })
  return r.data
}

async function getDocumentReaderBlob(path) {
  const r = await api.get(path, {
    headers: buildHeaders(),
    responseType: 'blob',
  })
  return URL.createObjectURL(r.data)
}

export async function getDocumentReaderPage(sourceDocumentId, pageNumber) {
  return getDocumentReaderBlob(
    `/v1/document-reader/documents/${encodeURIComponent(sourceDocumentId)}/pages/${encodeURIComponent(pageNumber)}`,
  )
}

export async function getDocumentReaderSlidePreview(sourceDocumentId, slideNumber) {
  return getDocumentReaderBlob(
    `/v1/document-reader/documents/${encodeURIComponent(sourceDocumentId)}/slide-previews/${encodeURIComponent(slideNumber)}`,
  )
}

export async function getDocumentReaderMedia(sourceDocumentId) {
  return getDocumentReaderBlob(
    `/v1/document-reader/documents/${encodeURIComponent(sourceDocumentId)}/media`,
  )
}

export async function getDocumentReaderExport(sourceDocumentId) {
  const r = await api.get(
    `/v1/document-reader/documents/${encodeURIComponent(sourceDocumentId)}/export`,
    { headers: buildHeaders(), responseType: 'blob' },
  )
  return { blob: r.data, headers: r.headers }
}

export async function saveDocumentReadingPosition(sourceDocumentId, payload) {
  const r = await api.put(
    `/v1/document-reader/positions/${encodeURIComponent(sourceDocumentId)}`,
    payload,
    { headers: buildHeaders() },
  )
  return r.data
}

export async function createDocumentSelection(payload) {
  const r = await api.post('/v1/document-reader/selections', payload, { headers: buildHeaders() })
  return r.data
}

export async function retryDocumentSelectionOcr(selectionId) {
  const r = await api.post(
    `/v1/document-reader/selections/${encodeURIComponent(selectionId)}/ocr/retry`,
    {},
    { headers: buildHeaders() },
  )
  return r.data
}

export async function askDocumentSelection(selectionId, payload) {
  const r = await api.post(
    `/v1/document-reader/selections/${encodeURIComponent(selectionId)}/ask`,
    payload,
    { headers: buildHeaders() },
  )
  return r.data
}

export async function saveDocumentSelectionNote(selectionId, payload) {
  const r = await api.post(
    `/v1/document-reader/selections/${encodeURIComponent(selectionId)}/notes`,
    payload,
    { headers: buildHeaders() },
  )
  return r.data
}

export async function generateDocumentSelectionResource(selectionId, payload) {
  const r = await api.post(
    `/v1/document-reader/selections/${encodeURIComponent(selectionId)}/generation-jobs`,
    payload,
    { headers: buildHeaders() },
  )
  return r.data
}

export async function generateDocumentResource(sourceDocumentId, payload) {
  const r = await api.post(
    `/v1/document-reader/documents/${encodeURIComponent(sourceDocumentId)}/generation-jobs`,
    payload,
    { headers: buildHeaders() },
  )
  return r.data
}

export async function getKnowledgeDocumentOcr(docId, studentId = 'default') {
  const r = await api.get(`/knowledge/${encodeURIComponent(docId)}/ocr`, {
    headers: buildHeaders(),
    params: { student_id: studentId },
  })
  return r.data
}

export async function getKnowledgeDocumentOcrPage(docId, pageNumber, studentId = 'default') {
  const r = await api.get(
    `/knowledge/${encodeURIComponent(docId)}/ocr/pages/${encodeURIComponent(pageNumber)}`,
    {
      headers: buildHeaders(),
      params: { student_id: studentId },
      responseType: 'blob',
    },
  )
  return URL.createObjectURL(r.data)
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

export async function addWebSource(query, title, url, snippet, studentId = 'default') {
  const r = await api.post('/knowledge/add-web-source', {
    query, title, url, snippet, student_id: studentId
  }, { headers: buildHeaders() })
  return r.data
}

export async function uploadKnowledgeDocumentsBatch(files, studentId = 'default', courseId = '', onProgress) {
  const form = new FormData()
  for (const file of files) form.append('files', file)
  const params = new URLSearchParams({ student_id: studentId })
  if (courseId) params.set('course_id', courseId)
  const r = await api.post(`/knowledge/upload-batch?${params.toString()}`, form, {
    headers: { ...buildHeaders(), 'Content-Type': 'multipart/form-data' },
    onUploadProgress: onProgress,
  })
  return r.data
}

export async function crossLanguageCourseSearch(courseId, query, topK = 5) {
  const r = await api.get(`/v1/next/core/courses/${encodeURIComponent(courseId)}/cross-language-search`, {
    headers: buildHeaders(),
    params: { q: query, top_k: topK },
  })
  return r.data
}

export async function downloadWebFile(url, fileType, title, studentId = 'default', courseId = '') {
  const r = await api.post('/knowledge/download-web-file', {
    url, file_type: fileType, title, student_id: studentId, course_id: courseId
  }, { headers: buildHeaders() })
  return r.data
}
