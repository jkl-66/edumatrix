import { api, normalizeApiError } from './common'

function authConfig(params) {
  const token = localStorage.getItem('edumatrix_token')
  return {
    params,
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  }
}

async function request(promise) {
  try {
    return (await promise).data
  } catch (error) {
    throw normalizeApiError(error)
  }
}

export function listM5Resources(params = {}) {
  return request(api.get('/v1/m5/resources', authConfig(params)))
}

export function getM5Resource(artifactId) {
  return request(api.get(`/v1/m5/resources/${encodeURIComponent(artifactId)}`, authConfig()))
}

export function compareM5ResourceVersions(artifactId, leftVersion, rightVersion) {
  return request(api.get(`/v1/m5/resources/${encodeURIComponent(artifactId)}/compare`, authConfig({
    left_version: leftVersion,
    right_version: rightVersion,
  })))
}

export function exportM5Resource(artifactId, versionNumber) {
  return request(api.get(`/v1/m5/resources/${encodeURIComponent(artifactId)}/export`, authConfig({
    version_number: versionNumber,
  })))
}

export function archiveM5Resource(artifactId, archived, expectedLockVersion) {
  const config = authConfig()
  return request(api.post(`/v1/m5/resources/${encodeURIComponent(artifactId)}/archive`, {
    archived,
    expected_lock_version: expectedLockVersion,
  }, config))
}

export function createM5TutorContext(payload) {
  return request(api.post('/v1/m5/tutor-contexts', payload, authConfig()))
}

export function listM5TutorContexts(params = {}) {
  return request(api.get('/v1/m5/tutor-contexts', authConfig(params)))
}

export function getM5TutorContext(contextId) {
  return request(api.get(`/v1/m5/tutor-contexts/${encodeURIComponent(contextId)}`, authConfig()))
}

export function archiveM5TutorContext(contextId, expectedLockVersion) {
  return request(api.post(`/v1/m5/tutor-contexts/${encodeURIComponent(contextId)}/archive`, {
    expected_lock_version: expectedLockVersion,
  }, authConfig()))
}

export function preflightM5TutorRequest(contextId, payload) {
  return request(api.post(`/v1/m5/tutor-contexts/${encodeURIComponent(contextId)}/preflight`, payload, authConfig()))
}
