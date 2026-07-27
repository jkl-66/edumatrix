import { api, buildHeaders } from './common'

const config = () => ({ headers: buildHeaders() })
const post = async (path, payload = null) => (await api.post(path, payload, config())).data

export async function getM3Profiles() {
  return (await api.get('/v1/m3/profiles', config())).data
}

export async function createM3Task(payload) { return post('/v1/m3/tasks', payload) }
export async function getLatestM3Task() { return (await api.get('/v1/m3/tasks/latest', config())).data }
export async function getM3Task(taskId) { return (await api.get(`/v1/m3/tasks/${encodeURIComponent(taskId)}`, config())).data }
export async function startM3Task(taskId) { return post(`/v1/m3/tasks/${encodeURIComponent(taskId)}/start`) }
export async function diagnoseM3Task(taskId) { return post(`/v1/m3/tasks/${encodeURIComponent(taskId)}/diagnose`) }
export async function generateM3Resources(taskId) { return post(`/v1/m3/tasks/${encodeURIComponent(taskId)}/generate`) }
export async function reviewM3Resources(taskId) { return post(`/v1/m3/tasks/${encodeURIComponent(taskId)}/review`) }
export async function buildM3MatchingReport(taskId) { return post(`/v1/m3/tasks/${encodeURIComponent(taskId)}/matching-report`) }
export async function buildM3Decision(taskId) { return post(`/v1/m3/tasks/${encodeURIComponent(taskId)}/decision`) }
export async function getM3Bundle(taskId) { return (await api.get(`/v1/m3/tasks/${encodeURIComponent(taskId)}/bundle`, config())).data }
export async function createM3InteractiveManifest(taskId) { return post(`/v1/m3/tasks/${encodeURIComponent(taskId)}/interactive/manifest`) }
export async function createM3InteractiveSession(taskId, idempotencyKey) {
  return post(`/v1/m3/tasks/${encodeURIComponent(taskId)}/interactive/sessions`, { idempotency_key: idempotencyKey })
}
export async function applyM3InteractiveAction(sessionId, payload) {
  return post(`/v1/m3/interactive/sessions/${encodeURIComponent(sessionId)}/actions`, payload)
}
export async function recordM3InteractiveEvidence(sessionId) {
  return post(`/v1/m3/interactive/sessions/${encodeURIComponent(sessionId)}/evidence`)
}
