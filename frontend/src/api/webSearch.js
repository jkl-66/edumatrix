import { api, buildHeaders } from './common'

// --- Web Search API ---
export async function webSearch(query, studentId = 'default', category = 'all') {
  const r = await api.post('/web/search', {
    query,
    student_id: studentId,
    category
  }, { headers: buildHeaders() })
  return r.data
}

export async function searchArxiv(query, maxResults = 5) {
  const r = await api.get('/web/arxiv-search', {
    params: { query, max_results: maxResults },
    headers: buildHeaders(),
  })
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
