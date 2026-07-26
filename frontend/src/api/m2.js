import { api, buildHeaders } from './common'

export async function getM2Baseline() {
  const r = await api.get('/v1/m2/baseline', { headers: buildHeaders() })
  return r.data
}

export async function createM2Task(payload) {
  const r = await api.post('/v1/m2/golden-tasks', payload, { headers: buildHeaders() })
  return r.data
}

export async function getLatestM2Task() {
  const r = await api.get('/v1/m2/golden-tasks/latest', { headers: buildHeaders() })
  return r.data
}

export async function getM2Task(taskId, afterEventSequence = 0) {
  const r = await api.get(`/v1/m2/golden-tasks/${encodeURIComponent(taskId)}`, {
    params: { after_event_sequence: afterEventSequence },
    headers: buildHeaders(),
  })
  return r.data
}

export async function startM2Task(taskId) {
  const r = await api.post(`/v1/m2/golden-tasks/${encodeURIComponent(taskId)}/start`, null, {
    headers: buildHeaders(),
  })
  return r.data
}

export async function generateM2Artifact(taskId, capability, context) {
  const r = await api.post(
    `/v1/m2/golden-tasks/${encodeURIComponent(taskId)}/generate/${encodeURIComponent(capability)}`,
    { context },
    { headers: buildHeaders() },
  )
  return r.data
}

export async function retryM2Step(taskId, sequence) {
  const r = await api.post(
    `/v1/m2/golden-tasks/${encodeURIComponent(taskId)}/steps/${sequence}/retry`,
    null,
    { headers: buildHeaders() },
  )
  return r.data
}

export async function checkM2Quality(taskId, context) {
  const r = await api.post(
    `/v1/m2/golden-tasks/${encodeURIComponent(taskId)}/quality`,
    { context },
    { headers: buildHeaders() },
  )
  return r.data
}

export async function submitM2Feedback(taskId, context, feedback) {
  const r = await api.post(
    `/v1/m2/golden-tasks/${encodeURIComponent(taskId)}/feedback`,
    { context, feedback },
    { headers: buildHeaders() },
  )
  return r.data
}

export async function getM2Bundle(taskId) {
  const r = await api.get(`/v1/m2/golden-tasks/${encodeURIComponent(taskId)}/bundle`, {
    headers: buildHeaders(),
  })
  return r.data
}
