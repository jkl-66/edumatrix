import { api, buildHeaders } from './common'

const config = () => ({ headers: buildHeaders() })

export async function listInteractiveTemplates() {
  return (await api.get('/v1/interactive-lab/templates', config())).data
}

export async function listInteractiveInstances() {
  return (await api.get('/v1/interactive-lab/instances', config())).data
}

export async function getInteractiveInstance(instanceId) {
  return (await api.get(`/v1/interactive-lab/instances/${encodeURIComponent(instanceId)}`, config())).data
}

export async function createInteractiveInstance(payload) {
  return (await api.post('/v1/interactive-lab/instances', payload, config())).data
}

export async function applyInteractiveAction(instanceId, payload) {
  return (await api.post(`/v1/interactive-lab/instances/${encodeURIComponent(instanceId)}/actions`, payload, config())).data
}
