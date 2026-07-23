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
