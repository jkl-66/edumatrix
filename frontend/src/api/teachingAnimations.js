import { api, buildHeaders } from './common'

const config = () => ({ headers: buildHeaders() })
const path = id => `/v1/teaching-animations/${encodeURIComponent(id)}`

export async function listTeachingAnimationTemplates() {
  return (await api.get('/v1/teaching-animations/templates', config())).data
}

export async function listTeachingAnimations() {
  return (await api.get('/v1/teaching-animations', config())).data
}

export async function createTeachingAnimation(payload) {
  return (await api.post('/v1/teaching-animations', payload, config())).data
}

export async function getTeachingAnimation(id) {
  return (await api.get(path(id), config())).data
}

export async function createTeachingAnimationVersion(id, payload) {
  return (await api.post(`${path(id)}/versions`, payload, config())).data
}

export async function saveTeachingAnimationPlayback(id, payload) {
  return (await api.put(`${path(id)}/playback`, payload, config())).data
}
