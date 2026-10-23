import { api, buildHeaders } from './common'

const config = () => ({ headers: buildHeaders() })

export async function getChapterVideoContext(courseId = '') {
  const params = courseId ? { course_id: courseId } : {}
  return (await api.get('/v1/chapter-videos/context', { ...config(), params })).data
}

export async function listChapterVideos(courseId = '', chapterId = '') {
  const params = {}
  if (courseId) params.course_id = courseId
  if (chapterId) params.chapter_id = chapterId
  return (await api.get('/v1/chapter-videos', { ...config(), params })).data
}

export async function generateChapterVideo(payload) {
  return (await api.post('/v1/chapter-videos', payload, config())).data
}

export async function getChapterVideo(id) {
  return (await api.get(`/v1/chapter-videos/${encodeURIComponent(id)}`, config())).data
}
