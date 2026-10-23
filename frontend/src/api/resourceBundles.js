import { api, buildHeaders } from './common.js'

export async function listResourceBundles() { return (await api.get('/v1/resource-bundles', { headers: buildHeaders() })).data }
export async function getResourceBundleWorkspace() { return (await api.get('/v1/resource-bundles/workspace', { headers: buildHeaders() })).data }
export async function getResourceBundle(id) { return (await api.get(`/v1/resource-bundles/${id}`, { headers: buildHeaders() })).data }
export async function getResourceBundleCandidates(courseId) { return (await api.get('/v1/resource-bundles/candidates', { params: { course_id: courseId }, headers: buildHeaders() })).data }
export async function createResourceBundle(payload) { return (await api.post('/v1/resource-bundles', payload, { headers: buildHeaders() })).data }
export async function createResourceBundleVersion(id, payload) { return (await api.post(`/v1/resource-bundles/${id}/versions`, payload, { headers: buildHeaders() })).data }
export async function restoreResourceBundleVersion(id, payload) { return (await api.post(`/v1/resource-bundles/${id}/restore`, payload, { headers: buildHeaders() })).data }

export async function listGenerationJobs(courseId = '') {
  return (await api.get('/v1/resource-bundles/generation-jobs', {
    params: courseId ? { course_id: courseId } : {},
    headers: buildHeaders(),
  })).data
}

export async function getGenerationJob(taskId) {
  return (await api.get(`/v1/resource-bundles/generation-jobs/${encodeURIComponent(taskId)}`, {
    headers: buildHeaders(),
  })).data
}

export async function createGenerationJob(payload) {
  return (await api.post('/v1/resource-bundles/generation-jobs', payload, {
    headers: buildHeaders(),
  })).data
}

export async function executeGenerationJobDemo(taskId) {
  return (await api.post(
    `/v1/resource-bundles/generation-jobs/${encodeURIComponent(taskId)}/execute-demo`,
    {},
    { headers: buildHeaders() },
  )).data
}

export async function executeGenerationJob(taskId) {
  return (await api.post(
    `/v1/resource-bundles/generation-jobs/${encodeURIComponent(taskId)}/execute`,
    {},
    { headers: buildHeaders() },
  )).data
}

export async function startGenerationItem(taskId, resourceType) {
  return (await api.post(
    `/v1/resource-bundles/generation-jobs/${encodeURIComponent(taskId)}/items/${encodeURIComponent(resourceType)}/start`,
    {},
    { headers: buildHeaders() },
  )).data
}

export async function retryGenerationItem(taskId, resourceType) {
  return (await api.post(
    `/v1/resource-bundles/generation-jobs/${encodeURIComponent(taskId)}/items/${encodeURIComponent(resourceType)}/retry`,
    {},
    { headers: buildHeaders() },
  )).data
}

export async function recoverGenerationJob(taskId) {
  return (await api.post(
    `/v1/resource-bundles/generation-jobs/${encodeURIComponent(taskId)}/recover`,
    {},
    { headers: buildHeaders() },
  )).data
}
