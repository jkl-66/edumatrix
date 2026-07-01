import { api, buildHeaders } from './common'

// 任务 7.6: 一键导出学情诊断 PDF
export async function exportProfilePDF(studentId) {
  const r = await api.get('/v1/profile/export', {
    params: { student_id: studentId },
    headers: { ...buildHeaders(), Accept: 'application/pdf' },
    responseType: 'blob',
  })
  return r.data
}

// --- Profile API ---
export async function getStudentProfile(studentId) {
  const r = await api.get(`/profile/${studentId}`, { headers: buildHeaders() })
  return r.data
}

export async function getProfileAnalysis(studentId) {
  const r = await api.get(`/profile/${studentId}/analysis`, { headers: buildHeaders() })
  return r.data
}

export async function getProfileNarrative(studentId) {
  const r = await api.get(`/profile/${studentId}/narrative`, { headers: buildHeaders() })
  return r.data
}

export async function updateStudentProfile(studentId, data) {
  const r = await api.post(`/profile/${studentId}/update`, data, { headers: buildHeaders() })
  return r.data
}
