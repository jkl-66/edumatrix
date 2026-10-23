import { api, buildHeaders } from './common'

export async function getOnboardingStatus() {
  const response = await api.get('/v1/onboarding/status', { headers: buildHeaders() })
  return response.data
}

export async function getOnboardingSession() {
  const response = await api.get('/v1/onboarding/session', { headers: buildHeaders() })
  return response.data
}

export async function submitOnboardingTurn(payload) {
  const response = await api.post('/v1/onboarding/turns', payload, { headers: buildHeaders() })
  return response.data
}

export async function confirmOnboardingTurn(turnId, fields, resolveConflict = false) {
  const response = await api.post(
    `/v1/onboarding/turns/${encodeURIComponent(turnId)}/confirm`,
    { fields, resolve_conflict: resolveConflict },
    { headers: buildHeaders() },
  )
  return response.data
}

export async function uploadOnboardingEvidence(evidenceType, file) {
  const form = new FormData()
  form.append('evidence_type', evidenceType)
  form.append('file', file)
  const response = await api.post('/v1/onboarding/personal-evidence', form, { headers: buildHeaders() })
  return response.data
}

export async function confirmOnboardingEvidence(evidenceId, fields) {
  const response = await api.post(
    `/v1/onboarding/personal-evidence/${encodeURIComponent(evidenceId)}/confirm`,
    { fields },
    { headers: buildHeaders() },
  )
  return response.data
}

export async function discardOnboardingEvidence(evidenceId) {
  const response = await api.post(
    `/v1/onboarding/personal-evidence/${encodeURIComponent(evidenceId)}/discard`,
    null,
    { headers: buildHeaders() },
  )
  return response.data
}

export async function finalizeOnboardingProfile() {
  const response = await api.post('/v1/onboarding/finalize', null, { headers: buildHeaders() })
  return response.data
}

export async function getProfileUpdateSession() {
  const response = await api.get('/v1/onboarding/update/session', { headers: buildHeaders() })
  return response.data
}

export async function startProfileUpdate(courseId = null) {
  const response = await api.post(
    '/v1/onboarding/update/session',
    { course_id: courseId || null },
    { headers: buildHeaders() },
  )
  return response.data
}

export async function submitProfileUpdateTurn(payload) {
  const response = await api.post('/v1/onboarding/update/turns', payload, { headers: buildHeaders() })
  return response.data
}

export async function confirmProfileUpdateTurn(turnId, payload) {
  const response = await api.post(
    `/v1/onboarding/update/turns/${encodeURIComponent(turnId)}/confirm`,
    payload,
    { headers: buildHeaders() },
  )
  return response.data
}

export async function completeProfileUpdate() {
  const response = await api.post('/v1/onboarding/update/complete', null, { headers: buildHeaders() })
  return response.data
}

export async function getProfileUpdateReminder(courseId = null) {
  const params = courseId ? { course_id: courseId } : undefined
  const response = await api.get('/v1/onboarding/update/reminder', { params, headers: buildHeaders() })
  return response.data
}

export async function dismissProfileUpdateReminder(courseId = null) {
  const params = courseId ? { course_id: courseId } : undefined
  const response = await api.post('/v1/onboarding/update/reminder/dismiss', null, { params, headers: buildHeaders() })
  return response.data
}
