import { api, authConfig as config, request } from './common.js'

export const getIntegrationFaultDrills = (params = {}) => request(api.get('/v1/integration-fault-drills/workspace', config(params)))
export const createIntegrationFaultDrill = (payload) => request(api.post('/v1/integration-fault-drills/runs', payload, config()))
export const executeIntegrationFaultStep = (runId, payload) => request(api.post(`/v1/integration-fault-drills/runs/${encodeURIComponent(runId)}/next`, payload, config()))
