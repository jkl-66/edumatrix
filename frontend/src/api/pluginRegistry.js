import { api, buildHeaders } from './common'
const config=()=>({headers:buildHeaders()})
export const listPlugins=async()=>(await api.get('/v1/plugins',config())).data
export const getPlugin=async id=>(await api.get(`/v1/plugins/${encodeURIComponent(id)}`,config())).data
export const installPlugin=async id=>(await api.post(`/v1/plugins/${encodeURIComponent(id)}/install`,{},config())).data
export const uninstallPlugin=async(id,expected_version)=>(await api.post(`/v1/plugins/${encodeURIComponent(id)}/uninstall`,{expected_version},config())).data
