import { api, buildHeaders } from '../api/common'

export const RESOURCE_TYPES = [
  'handout',
  'mind_map',
  'quiz',
  'training_task',
  'code_sandbox',
  'video',
  'deck',
  'interactive_model',
  'feynman',
]

export async function listResources(params = {}) {
  return (await api.get('/v1/m5/resources', { params, headers: buildHeaders() })).data
}

export async function getResource(resourceId) {
  return (await api.get(`/v1/m5/resources/${resourceId}`, { headers: buildHeaders() })).data
}

export async function createResourceVersion(resourceId, payload) {
  return (await api.post(`/v1/m5/resources/${resourceId}/versions`, payload, { headers: buildHeaders() })).data
}

export async function compareResourceVersions(resourceId, leftVersion, rightVersion) {
  return (await api.get(`/v1/m5/resources/${resourceId}/compare`, {
    params: { left_version: leftVersion, right_version: rightVersion },
    headers: buildHeaders(),
  })).data
}

export async function restoreResourceVersion(resourceId, payload) {
  return (await api.post(`/v1/m5/resources/${resourceId}/restore`, payload, { headers: buildHeaders() })).data
}

export async function createResourceGenerationJob(payload) {
  return (await api.post('/v1/resource-bundles/generation-jobs', payload, { headers: buildHeaders() })).data
}

export async function getResourceGenerationJob(taskId) {
  return (await api.get(`/v1/resource-bundles/generation-jobs/${taskId}`, { headers: buildHeaders() })).data
}

export async function retryResourceGenerationItem(taskId, resourceType) {
  return (await api.post(`/v1/resource-bundles/generation-jobs/${taskId}/items/${resourceType}/retry`, {}, { headers: buildHeaders() })).data
}

export async function recoverResourceGenerationJob(taskId) {
  return (await api.post(`/v1/resource-bundles/generation-jobs/${taskId}/recover`, {}, { headers: buildHeaders() })).data
}

export async function cancelResourceGenerationJob(taskId) {
  return (await api.post(`/v1/resource-bundles/generation-jobs/${taskId}/cancel`, {}, { headers: buildHeaders() })).data
}
