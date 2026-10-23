import { api, authConfig as config, request } from './common.js'

export const getLocalLmsWorkspace = (params = {}) => request(api.get('/v1/local-lms/workspace', config(params)))
export const bootstrapLocalLmsDemo = () => request(api.post('/v1/local-lms/demo/bootstrap', {}, config()))
export const createLocalLmsConnection = (payload) => request(api.post('/v1/local-lms/connections', payload, config()))
export const exportLocalLmsCatalog = (payload) => request(api.post('/v1/local-lms/catalog-exports', payload, config()))
export const syncLocalLmsAssignment = (payload) => request(api.post('/v1/local-lms/assignment-exchanges', payload, config()))
export const importLocalLmsGrade = (payload) => request(api.post('/v1/local-lms/grade-summaries', payload, config()))
