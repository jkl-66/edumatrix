import { api, buildHeaders } from './common'

export async function getCompetitionDemoContext() {
  const response = await api.get('/v1/competition-demo/context', { headers: buildHeaders() })
  return response.data
}

export async function initializeCompetitionDemo() {
  const response = await api.post('/v1/competition-demo/initialize', {}, { headers: buildHeaders() })
  return response.data
}

export async function resetCompetitionDemo() {
  const response = await api.post('/v1/competition-demo/reset', {}, { headers: buildHeaders() })
  return response.data
}
