import { api, buildHeaders } from './common'

export async function getSpeechRuntime() {
  const response = await api.get('/v1/speech/runtime', { headers: buildHeaders() })
  return response.data
}

export async function listSpeechSessions() {
  const response = await api.get('/v1/speech/sessions', { headers: buildHeaders() })
  return response.data
}

export async function createSpeechSession(wavBlob, language = 'auto') {
  const form = new FormData()
  form.append('file', wavBlob, `edumatrix-recording-${Date.now()}.wav`)
  const response = await api.post('/v1/speech/sessions', form, {
    headers: { ...buildHeaders(), 'Content-Type': 'multipart/form-data' },
    params: { language },
  })
  return response.data
}

export async function transcribeSpeechSession(sessionId, language = 'auto') {
  const response = await api.post(
    `/v1/speech/sessions/${encodeURIComponent(sessionId)}/transcribe`,
    { language },
    { headers: buildHeaders() },
  )
  return response.data
}

export async function cancelSpeechSession(sessionId) {
  const response = await api.post(
    `/v1/speech/sessions/${encodeURIComponent(sessionId)}/cancel`,
    {},
    { headers: buildHeaders() },
  )
  return response.data
}

export async function downloadSpeechSubtitles(sessionId) {
  const response = await api.get(
    `/v1/speech/sessions/${encodeURIComponent(sessionId)}/subtitles.vtt`,
    { headers: buildHeaders(), responseType: 'blob' },
  )
  return response.data
}
