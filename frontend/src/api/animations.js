import { api, buildHeaders } from './common'

// === 本地动画 API ===
export async function getLocalAnimations(knowledgePoint) {
  const r = await api.get(`/v1/animations/for/${encodeURIComponent(knowledgePoint)}`, { headers: buildHeaders() })
  return r.data
}

export async function searchLocalAnimations(query) {
  const r = await api.get(`/v1/animations/search?query=${encodeURIComponent(query)}`, { headers: buildHeaders() })
  return r.data
}

export async function listAllAnimations() {
  const r = await api.get('/v1/animations/list', { headers: buildHeaders() })
  return r.data
}
