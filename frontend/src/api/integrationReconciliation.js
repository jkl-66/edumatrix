import { api, authConfig as config, request } from './common.js'

export const getIntegrationReconciliation = (params = {}) =>
  request(api.get('/v1/integration-reconciliation/workspace', config(params)))

export const createIntegrationReconciliationRun = (payload) =>
  request(api.post('/v1/integration-reconciliation/runs', payload, config()))

export const decideIntegrationRepair = (runId, payload) =>
  request(api.post(`/v1/integration-reconciliation/runs/${encodeURIComponent(runId)}/decisions`, payload, config()))
