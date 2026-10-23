import { api, buildHeaders } from './common'

export async function getInternalObjects(params = {}) {
  const r = await api.get('/v1/internal/objects', { params, headers: buildHeaders() })
  return r.data
}

export async function inspectInternalObject(objectType, objectId) {
  const r = await api.get(`/v1/internal/objects/${encodeURIComponent(objectType)}/${encodeURIComponent(objectId)}`, {
    headers: buildHeaders(),
  })
  return r.data
}

export async function inspectInternalTrace(traceId) {
  const r = await api.get(`/v1/internal/traces/${encodeURIComponent(traceId)}`, {
    headers: buildHeaders(),
  })
  return r.data
}

export async function listGenerationTasks(params = {}) {
  const r = await api.get('/v1/generation-tasks', { params, headers: buildHeaders() })
  return r.data
}

export async function getCanonicalCourse(courseId) {
  const r = await api.get(`/v1/courses/${encodeURIComponent(courseId)}`, { headers: buildHeaders() })
  return r.data
}

export async function getCanonicalCourseOutline(courseId) {
  const r = await api.get(`/v1/courses/${encodeURIComponent(courseId)}/outline`, { headers: buildHeaders() })
  return r.data
}

export async function getCanonicalSourceRef(sourceRefId) {
  const r = await api.get(`/v1/source-refs/${encodeURIComponent(sourceRefId)}`, { headers: buildHeaders() })
  return r.data
}

export async function getCanonicalSourceEvidenceLocation(sourceRefId, evidenceId) {
  const r = await api.get(
    `/v1/source-refs/${encodeURIComponent(sourceRefId)}/evidence/${encodeURIComponent(evidenceId)}`,
    { headers: buildHeaders() },
  )
  return r.data
}
