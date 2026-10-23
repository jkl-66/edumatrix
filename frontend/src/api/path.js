import { api, buildHeaders } from './common'

export async function getLearningPath(studentId) {
  const r = await api.get(`/profile/${studentId}/learning-path`, { headers: buildHeaders() })
  return r.data
}

export async function getReviewPlans(studentId) {
  const r = await api.get(`/review/${studentId}`, { headers: buildHeaders() })
  return r.data.due_reviews || r.data.plans || r.data
}

export async function getReviewSchedule(month, courseId = 'all') {
  const r = await api.get('/v1/review-schedule', {
    params: { month, course_id: courseId },
    headers: buildHeaders(),
  })
  return r.data
}

export async function completeReviewScheduleTask(taskId, payload) {
  const r = await api.post(
    `/v1/review-schedule/tasks/${encodeURIComponent(taskId)}/complete`,
    payload,
    { headers: buildHeaders() },
  )
  return r.data
}

export async function createReviewResourceJob(taskId, idempotencyKey) {
  const r = await api.post(
    `/v1/review-schedule/tasks/${encodeURIComponent(taskId)}/resource-jobs`,
    { idempotency_key: idempotencyKey },
    { headers: buildHeaders() },
  )
  return r.data
}

export async function createReviewPlan(studentId, data) {
  const r = await api.post(`/review/${studentId}`, data, { headers: buildHeaders() })
  return r.data
}

export async function deleteReviewPlan(planId) {
  const r = await api.delete(`/review/${planId}`, { headers: buildHeaders() })
  return r.data
}


export async function checkinReview(studentId, concept = '', durationMinutes = 10) {
  const r = await api.post(`/quiz/checkin/${studentId}`, {
    concept,
    duration_minutes: durationMinutes,
  }, { headers: buildHeaders() })
  return r.data
}

export async function getCheckinStreak(studentId) {
  const r = await api.get(`/quiz/checkin/streak/${studentId}`, { headers: buildHeaders() })
  return r.data
}

export async function getCheckinHistory(studentId, concept = '') {
  const params = concept ? { concept } : {}
  const r = await api.get(`/quiz/checkin/history/${studentId}`, { params, headers: buildHeaders() })
  return r.data
}

export async function reviewFlashcard(studentId, concept, quality, cardId = '') {
  const r = await api.post('/flashcard/review', {
    student_id: studentId,
    concept,
    quality,
    ...(cardId ? { card_id: cardId } : {}),
  }, { headers: buildHeaders() })
  return r.data
}

export async function getDueFlashcards(studentId, maxCount = 20) {
  const r = await api.get('/flashcard/due', {
    params: { student_id: studentId, max_count: maxCount },
    headers: buildHeaders(),
  })
  return r.data
}

export async function getAllFlashcards(studentId) {
  const r = await api.get('/flashcard/all', {
    params: { student_id: studentId },
    headers: buildHeaders(),
  })
  return r.data
}
