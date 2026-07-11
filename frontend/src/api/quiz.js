import { api, buildHeaders } from './common'

// --- Quiz API ---
export async function generateQuiz(studentId, targetConcept, difficulty = 'medium', sessionId = '') {
  const r = await api.post('/quiz/generate', {
    student_id: studentId,
    target_concept: targetConcept,
    difficulty,
    session_id: sessionId,
  }, { headers: buildHeaders() })
  return r.data
}

export async function evaluateQuizAnswer(quizId, studentId, answer, studentConfidence = 0.5, attemptNumber = 1, sourceQuizId = '') {
  const payload = {
    quiz_id: quizId,
    student_id: studentId,
    answer,
    student_confidence: studentConfidence,
    attempt_number: attemptNumber,
  }
  if (sourceQuizId) {
    payload.source_quiz_id = sourceQuizId
  }
  const r = await api.post('/quiz/evaluate', payload, { headers: buildHeaders() })
  return r.data
}

export async function adaptQuiz(studentId, quizId, nextAction, targetConcept = '', attemptNumber = 1, sessionId = '') {
  const r = await api.post('/quiz/adapt', {
    student_id: studentId,
    quiz_id: quizId,
    next_action: nextAction,
    target_concept: targetConcept,
    attempt_number: attemptNumber,
    session_id: sessionId,
  }, { headers: buildHeaders() })
  return r.data
}

export async function getQuizHistory(studentId) {
  const r = await api.get(`/quiz/history/${studentId}`, { headers: buildHeaders() })
  return r.data
}

// === 任务 7.4: 错题与复习打卡 API ===
export async function getWrongQuestions(studentId, concept = '') {
  const params = concept ? { concept } : {}
  const r = await api.get(`/quiz/wrong-questions/${studentId}`, { params, headers: buildHeaders() })
  return r.data
}

export async function getWrongConcepts(studentId) {
  const r = await api.get(`/quiz/wrong-concepts/${studentId}`, { headers: buildHeaders() })
  return r.data
}

// --- Anki Flashcard API ---
export async function generateFlashcard(studentId, quizId = '') {
  const r = await api.post('/flashcard/generate', {
    student_id: studentId,
    quiz_id: quizId,
  }, { headers: buildHeaders() })
  return r.data
}

// --- Similar Quiz API ---
export async function generateSimilarQuiz(studentId, sourceQuizId, concept = '') {
  const r = await api.post('/quiz/similar', {
    student_id: studentId,
    source_quiz_id: sourceQuizId,
    concept,
  }, { headers: buildHeaders() })
  return r.data
}

// === 错题管理 API ===
export async function deleteWrongQuestion(wrongId) {
  const r = await api.delete(`/quiz/wrong-questions/${wrongId}`, { headers: buildHeaders() })
  return r.data
}

export async function togglePinWrongQuestion(wrongId) {
  const r = await api.patch(`/quiz/wrong-questions/${wrongId}/pin`, {}, { headers: buildHeaders() })
  return r.data
}

export async function updateWrongQuestionNotes(wrongId, notes) {
  const r = await api.patch(`/quiz/wrong-questions/${wrongId}/notes`, { notes }, { headers: buildHeaders() })
  return r.data
}