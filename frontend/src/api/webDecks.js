import { api, buildHeaders } from './common'

const config = () => ({ headers: buildHeaders() })
const path = id => `/v1/web-decks/${encodeURIComponent(id)}`

export async function getWebDeckCapabilities() { return (await api.get('/v1/web-decks/capabilities', config())).data }
export async function listWebDecks() { return (await api.get('/v1/web-decks', config())).data }
export async function createWebDeck(payload) { return (await api.post('/v1/web-decks', payload, config())).data }
export async function getWebDeck(id) { return (await api.get(path(id), config())).data }
export async function createWebDeckVersion(id, payload) { return (await api.post(`${path(id)}/versions`, payload, config())).data }
export async function restoreWebDeckVersion(id, payload) { return (await api.post(`${path(id)}/restore`, payload, config())).data }
export async function saveWebDeckPlayback(id, payload) { return (await api.put(`${path(id)}/playback`, payload, config())).data }
export async function exportWebDeck(id, format, versionId = '') {
  return (await api.get(`${path(id)}/export/${format}`, { ...config(), params: versionId ? { version_id: versionId } : {}, responseType: 'blob' })).data
}
