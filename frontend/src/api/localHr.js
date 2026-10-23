import { api, authConfig as config, request } from './common.js'

export const getLocalHrWorkspace = (params = {}) => request(api.get('/v1/local-hr/workspace', config(params)))
export const createLocalHrMapping = (payload) => request(api.post('/v1/local-hr/mappings', payload, config()))
export const createLocalHrPreview = (payload) => request(api.post('/v1/local-hr/previews', payload, config()))
export const applyLocalHrBatch = (batchId, payload) => request(api.post(`/v1/local-hr/batches/${encodeURIComponent(batchId)}/apply`, payload, config()))
