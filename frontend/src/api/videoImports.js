import { api, buildHeaders } from './common'

const config = () => ({ headers: buildHeaders() })
export const listVideoAssets = async () => (await api.get('/v1/video-imports', config())).data
export const getVideoAsset = async id => (await api.get(`/v1/video-imports/${encodeURIComponent(id)}`, config())).data
export async function uploadVideoAsset(payload) {
  const form = new FormData()
  Object.entries(payload).forEach(([key, value]) => {
    if (value !== null && value !== undefined && value !== '') form.append(key, value)
  })
  return (await api.post('/v1/video-imports', form, config())).data
}
export async function getVideoAssetFile(assetId, versionId, kind) {
  return (await api.get(`/v1/video-imports/${encodeURIComponent(assetId)}/versions/${encodeURIComponent(versionId)}/files/${kind}`, { ...config(), responseType: 'blob' })).data
}
export async function downloadVideoAssetFile(assetId, versionId, kind, filename) {
  const blob = await getVideoAssetFile(assetId, versionId, kind)
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a'); link.href = url; link.download = filename; link.click()
  setTimeout(() => URL.revokeObjectURL(url), 1500)
}
