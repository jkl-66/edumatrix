import { api, buildHeaders } from './common'

const config = () => ({ headers: buildHeaders() })

export async function generateWrongQuestionVideo(studentId, wrongQuestionId) {
  return (await api.post('/v1/wrong-question-videos', {
    student_id: studentId,
    wrong_question_id: wrongQuestionId,
  }, config())).data
}

export async function listWrongQuestionVideos(studentId, wrongQuestionId = null) {
  const params = { student_id: studentId }
  if (wrongQuestionId) params.wrong_question_id = wrongQuestionId
  return (await api.get('/v1/wrong-question-videos', { ...config(), params })).data
}
