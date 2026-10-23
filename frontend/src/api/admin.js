import { api, authConfig as config, request } from './common.js'

export const getAdminAccounts = () => request(api.get('/v1/admin/accounts', config()))
export const updateAdminAccount = (publicId, payload) => request(
  api.patch(`/v1/admin/accounts/${encodeURIComponent(publicId)}`, payload, config()),
)
export const getAdminModels = () => request(api.get('/v1/admin/models', config()))
export const getAdminSystem = () => request(api.get('/v1/admin/system', config()))
export const retryAdminTask = (taskId) => request(
  api.post(`/v1/admin/system/tasks/${encodeURIComponent(taskId)}/retry`, {}, config()),
)
export const cancelAdminTask = (taskId) => request(
  api.post(`/v1/admin/system/tasks/${encodeURIComponent(taskId)}/cancel`, {}, config()),
)
