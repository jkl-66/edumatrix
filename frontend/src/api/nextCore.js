import { api, buildHeaders } from './common'

export async function getLongTermMemories(includeWithdrawn = false) {
  return (await api.get('/v1/next/core/memories', {
    params: { include_withdrawn: includeWithdrawn }, headers: buildHeaders(),
  })).data
}

export async function createLongTermMemory(payload) {
  return (await api.post('/v1/next/core/memories', payload, { headers: buildHeaders() })).data
}

export async function updateLongTermMemory(memoryId, payload) {
  return (await api.patch(`/v1/next/core/memories/${memoryId}`, payload, { headers: buildHeaders() })).data
}

export async function withdrawLongTermMemory(memoryId, payload) {
  return (await api.post(`/v1/next/core/memories/${memoryId}/withdraw`, payload, { headers: buildHeaders() })).data
}

export async function getMemorySubscriptions() {
  return (await api.get('/v1/next/core/memory-subscriptions', { headers: buildHeaders() })).data
}

export async function saveProfileMemorySubscription(payload) {
  return (await api.put('/v1/next/core/memory-subscriptions/profile', payload, { headers: buildHeaders() })).data
}

export async function revokeProfileMemorySubscription(payload) {
  return (await api.post('/v1/next/core/memory-subscriptions/profile/revoke', payload, { headers: buildHeaders() })).data
}

export async function getMemoryAudit(limit = 30) {
  return (await api.get('/v1/next/core/memory-audit', { params: { limit }, headers: buildHeaders() })).data
}
