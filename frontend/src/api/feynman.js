import { api, authConfig, request } from './common.js'

export function listFeynmanSessions(sourceResourceId) {
  return request(api.get('/v1/feynman/sessions', authConfig({
    source_resource_id: sourceResourceId,
  })))
}

export function createFeynmanSession(sourceResourceId, idempotencyKey) {
  return request(api.post('/v1/feynman/sessions', {
    source_resource_id: sourceResourceId,
    idempotency_key: idempotencyKey,
  }, authConfig()))
}

export function getFeynmanSession(sessionId) {
  return request(api.get(
    `/v1/feynman/sessions/${encodeURIComponent(sessionId)}`,
    authConfig(),
  ))
}

export function applyFeynmanAction(sessionId, payload) {
  return request(api.post(
    `/v1/feynman/sessions/${encodeURIComponent(sessionId)}/actions`,
    payload,
    authConfig(),
  ))
}
