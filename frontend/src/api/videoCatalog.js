import { api, buildHeaders } from './common'

const config = () => ({ headers: buildHeaders() })
export const listVideoCatalog = async params => (await api.get('/v1/video-catalog', { ...config(), params })).data
export const getVideoCatalogItem = async sourceKey => (await api.get(`/v1/video-catalog/${encodeURIComponent(sourceKey)}`, config())).data
