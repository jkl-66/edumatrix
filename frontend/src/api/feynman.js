import { api, authConfig, request } from './common.js'

export function listFeynmanSessions(sourceResourceId, sourceResourceVersionId) {
  return request(api.get('/v1/feynman/sessions', authConfig({
    source_resource_id: sourceResourceId,
    ...(sourceResourceVersionId ? { source_resource_version_id: sourceResourceVersionId } : {}),
  })))
}

export function createFeynmanSession(sourceResourceId, idempotencyKey, sourceResourceVersionId) {
  return request(api.post('/v1/feynman/sessions', {
    source_resource_id: sourceResourceId,
    ...(sourceResourceVersionId ? { source_resource_version_id: sourceResourceVersionId } : {}),
    idempotency_key: idempotencyKey,
  }, authConfig()))
}

export function getFeynmanSession(sessionId) {
  return request(api.get(
    `/v1/feynman/sessions/${encodeURIComponent(sessionId)}`,
    authConfig(),
  ))
}

export function getFeynmanActionTask(sessionId) {
  return request(api.get(`/v1/feynman/sessions/${encodeURIComponent(sessionId)}/action-task`, authConfig()))
}

export function applyFeynmanAction(sessionId, payload) {
  return request(api.post(
    `/v1/feynman/sessions/${encodeURIComponent(sessionId)}/actions`,
    payload,
    authConfig(),
  ))
}
