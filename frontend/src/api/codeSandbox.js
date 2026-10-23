import { api, authConfig, request } from './common.js'

export function getCodeSandboxStatus() {
  return request(api.get('/v1/code-sandbox/status', authConfig()))
}

export function listCodeSandboxRuns(resourceId, limit = 20) {
  return request(api.get(
    `/v1/code-sandbox/resources/${encodeURIComponent(resourceId)}/runs`,
    authConfig({ limit }),
  ))
}

export function startCodeSandboxRun(resourceId, payload) {
  return request(api.post(
    `/v1/code-sandbox/resources/${encodeURIComponent(resourceId)}/runs`,
    payload,
    authConfig(),
  ))
}

export function getCodeSandboxRun(runAttemptId, includeComplete = false) {
  return request(api.get(
    `/v1/code-sandbox/runs/${encodeURIComponent(runAttemptId)}`,
    authConfig(includeComplete ? { include_complete: true } : {}),
  ))
}

export function stopCodeSandboxRun(runAttemptId) {
  return request(api.post(
    `/v1/code-sandbox/runs/${encodeURIComponent(runAttemptId)}/stop`,
    {},
    authConfig(),
  ))
}

export function completeCodeSandboxLearning(resourceId, payload) {
  return request(api.post(
    `/v1/code-sandbox/resources/${encodeURIComponent(resourceId)}/complete`,
    payload,
    authConfig(),
  ))
}

export function getLatestCodeReview(resourceId, runAttemptId) {
  return request(api.get(
    `/v1/code-sandbox/resources/${encodeURIComponent(resourceId)}/reviews/latest`,
    authConfig({ run_attempt_id: runAttemptId }),
  ))
}

export function createCodeReview(resourceId, payload) {
  return request(api.post(
    `/v1/code-sandbox/resources/${encodeURIComponent(resourceId)}/reviews`,
    payload,
    authConfig(),
  ))
}

export function applyCodeReview(reviewId, payload) {
  return request(api.post(
    `/v1/code-sandbox/reviews/${encodeURIComponent(reviewId)}/apply`,
    payload,
    authConfig(),
  ))
}
