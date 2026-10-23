import { api, buildHeaders } from './common'

const config = () => ({ headers: buildHeaders() })

export async function listMediaContextResources() {
  const response = await api.get('/v1/media-context/resources', config())
  return response.data
}

export async function getMediaContextResource(resourceId) {
  const response = await api.get(`/v1/media-context/resources/${encodeURIComponent(resourceId)}`, config())
  return response.data
}

export async function createMediaContextResource(payload) {
  const response = await api.post('/v1/media-context/resources', payload, config())
  return response.data
}

export async function saveMediaContextPosition(resourceId, payload) {
  const response = await api.put(`/v1/media-context/resources/${encodeURIComponent(resourceId)}/position`, payload, config())
  return response.data
}

export async function createMediaConversation(resourceId, title) {
  const response = await api.post(`/v1/media-context/resources/${encodeURIComponent(resourceId)}/conversations`, { title }, config())
  return response.data
}

export async function appendMediaMessage(conversationId, payload) {
  const response = await api.post(`/v1/media-context/conversations/${encodeURIComponent(conversationId)}/messages`, payload, config())
  return response.data
}
