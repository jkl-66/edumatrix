import { api, buildHeaders } from './common'
const config = () => ({ headers: buildHeaders() })
export const listVideoProjects = async () => (await api.get('/v1/video-projects', config())).data
export const createVideoProject = async payload => (await api.post('/v1/video-projects', payload, config())).data
export const getVideoProject = async id => (await api.get(`/v1/video-projects/${encodeURIComponent(id)}`, config())).data
export const reviseVideoScript = async (id, payload) => (await api.post(`/v1/video-projects/${encodeURIComponent(id)}/scripts`, payload, config())).data
export const renderVideoProject = async (id, payload) => (await api.post(`/v1/video-projects/${encodeURIComponent(id)}/renders`, payload, config())).data
export const videoOutputUrl = (outputId, filename) => `/api/v1/video-projects/outputs/${encodeURIComponent(outputId)}/files/${encodeURIComponent(filename)}`
export async function getVideoOutputBlob(outputId, filename) {
  return (await api.get(`/v1/video-projects/outputs/${encodeURIComponent(outputId)}/files/${encodeURIComponent(filename)}`, { ...config(), responseType: 'blob' })).data
}
export async function downloadVideoOutput(outputId, filename) {
  const response = await api.get(`/v1/video-projects/outputs/${encodeURIComponent(outputId)}/files/${encodeURIComponent(filename)}`, { ...config(), responseType: 'blob' })
  const url = URL.createObjectURL(response.data); const link = document.createElement('a'); link.href = url; link.download = filename; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1500)
}
