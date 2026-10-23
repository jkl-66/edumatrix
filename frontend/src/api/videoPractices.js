import { api, buildHeaders } from './common'

const config = () => ({ headers: buildHeaders() })
const path = id => `/v1/video-practices/${encodeURIComponent(id)}`

export async function getVideoPracticeContext(linkId) {
  return (await api.get(`/v1/video-practices/context/${encodeURIComponent(linkId)}`, config())).data
}

export async function getVideoPractice(linkId) {
  return (await api.get(path(linkId), config())).data
}

export async function bindVideoPractice(linkId, payload) {
  return (await api.put(`${path(linkId)}/bindings`, payload, config())).data
}

export async function saveVideoWatchProgress(linkId, payload) {
  return (await api.put(`${path(linkId)}/watch-progress`, payload, config())).data
}

export async function submitVideoPracticeAttempt(linkId, payload) {
  return (await api.post(`${path(linkId)}/attempts`, payload, config())).data
}

export async function linkVideoPracticeAttempt(linkId, attemptId) {
  return (await api.post(`${path(linkId)}/attempt-links`, { attempt_id: attemptId }, config())).data
}

export async function linkVideoPracticeLab(linkId, labInstanceId) {
  return (await api.post(`${path(linkId)}/lab-links`, { lab_instance_id: labInstanceId }, config())).data
}
