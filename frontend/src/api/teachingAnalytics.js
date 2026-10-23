import { api, buildHeaders, request } from './common.js'

const config = (extra = {}) => ({ headers: buildHeaders(), ...extra })

export function createTeachingAnalyticsReport(payload) {
  return request(api.post('/v1/teaching-analytics/reports', payload, config()))
}

export function listTeachingAnalyticsReports(classId) {
  return request(api.get('/v1/teaching-analytics/reports', config({ params: { class_id: classId } })))
}

export async function downloadTeachingAnalyticsReport(reportId, format) {
  const response = await api.get(`/v1/teaching-analytics/reports/${encodeURIComponent(reportId)}/export/${format}`, config({ responseType: 'blob' }))
  const url = URL.createObjectURL(response.data)
  const link = document.createElement('a')
  link.href = url
  link.download = `teaching-analytics-${reportId}.${format}`
  link.click()
  URL.revokeObjectURL(url)
}
