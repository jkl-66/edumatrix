import { api, authConfig, request } from './common.js'

export function getDiagnosticPreflight(params) {
  return request(api.get('/v1/diagnostics/preflight', authConfig(params)))
}

export function getDiagnosticCourses() {
  return request(api.get('/v1/diagnostics/courses', authConfig()))
}

export function createMulticourseDiagnosticBlueprints(payload) {
  return request(api.post('/v1/diagnostics/multi-course/blueprints', payload, authConfig()))
}

export function createMulticourseDiagnosticPaths(payload) {
  return request(api.post('/v1/diagnostics/multi-course/paths', payload, authConfig()))
}

export function createDiagnosticBlueprint(payload) {
  return request(api.post('/v1/diagnostics/blueprints', payload, authConfig()))
}

export function getDiagnosticBlueprint(blueprintId) {
  return request(api.get(`/v1/diagnostics/blueprints/${encodeURIComponent(blueprintId)}`, authConfig()))
}

export function startDiagnosticSession(blueprintId) {
  return request(api.post(`/v1/diagnostics/blueprints/${encodeURIComponent(blueprintId)}/sessions`, null, authConfig()))
}

export function getDiagnosticSession(sessionId) {
  return request(api.get(`/v1/diagnostics/sessions/${encodeURIComponent(sessionId)}`, authConfig()))
}

export function saveDiagnosticResponse(sessionId, questionVersionId, payload) {
  return request(api.put(
    `/v1/diagnostics/sessions/${encodeURIComponent(sessionId)}/responses/${encodeURIComponent(questionVersionId)}`,
    payload,
    authConfig(),
  ))
}

export function submitDiagnosticSession(sessionId, payload) {
  return request(api.post(`/v1/diagnostics/sessions/${encodeURIComponent(sessionId)}/submit`, payload, authConfig()))
}

export function createDiagnosticReport(sessionId, payload) {
  return request(api.post(`/v1/diagnostics/sessions/${encodeURIComponent(sessionId)}/report`, payload, authConfig()))
}

export function getDiagnosticReport(sessionId) {
  return request(api.get(`/v1/diagnostics/sessions/${encodeURIComponent(sessionId)}/report`, authConfig()))
}

export function generateDiagnosticReportPath(sessionId, payload) {
  return request(api.post(`/v1/diagnostics/sessions/${encodeURIComponent(sessionId)}/report/path`, payload, authConfig()))
}

export function confirmDiagnosticReportPath(sessionId, payload) {
  return request(api.post(`/v1/diagnostics/sessions/${encodeURIComponent(sessionId)}/report/path/confirm`, payload, authConfig()))
}
