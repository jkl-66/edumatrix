import { api, authConfig as config, request } from './common.js'

export const getJobStandardImpactWorkspace = organizationId =>
  request(api.get('/v1/job-standard-impact/workspace', config({ organization_id: organizationId })))

export const prepareSyntheticJobStandard = payload =>
  request(api.post('/v1/job-standard-impact/demo/prepare', payload, config()))

export const createJobStandardImpactPreview = payload =>
  request(api.post('/v1/job-standard-impact/previews', payload, config()))

export const confirmJobStandardImpact = (previewId, payload) =>
  request(api.post(`/v1/job-standard-impact/previews/${encodeURIComponent(previewId)}/confirm`, payload, config()))
