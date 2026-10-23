import { api, buildHeaders } from './common'
const config = () => ({ headers: buildHeaders() })
export const listSpatialWorkspaces = async () => (await api.get('/v1/spatial-workspaces', config())).data
export const createSpatialWorkspace = async payload => (await api.post('/v1/spatial-workspaces', payload, config())).data
export const getSpatialWorkspace = async id => (await api.get(`/v1/spatial-workspaces/${encodeURIComponent(id)}`, config())).data
export const applySpatialAction = async (id, payload) => (await api.post(`/v1/spatial-workspaces/${encodeURIComponent(id)}/actions`, payload, config())).data
export const applySpatialCommand = async (id, payload) => (await api.post(`/v1/spatial-workspaces/${encodeURIComponent(id)}/commands`, payload, config())).data
