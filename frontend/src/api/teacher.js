import { api, buildHeaders } from './common'

const config = (params) => ({ headers: buildHeaders(), ...(params ? { params } : {}) })
const data = async (request) => (await request).data

export const getTeacherOverview = (courseId) => data(api.get(
  '/v1/teacher/overview',
  config(courseId ? { course_id: courseId } : undefined),
))

export const getTeacherCourses = () => data(api.get('/v1/teacher/courses', config()))

export const getTeacherCourse = (courseId) => data(api.get(
  `/v1/teacher/courses/${encodeURIComponent(courseId)}`,
  config(),
))

export const getTeacherStudents = ({ courseId, query = '' } = {}) => data(api.get(
  '/v1/teacher/students',
  config({ ...(courseId ? { course_id: courseId } : {}), ...(query ? { query } : {}) }),
))

export const getTeacherStudent = (studentId, courseId) => data(api.get(
  `/v1/teacher/students/${encodeURIComponent(studentId)}`,
  config({ course_id: courseId }),
))

export const createTeacherIntervention = ({ courseId, studentId, idempotencyKey }) => data(api.post(
  '/v1/teacher/interventions',
  {
    course_id: courseId,
    learner_public_id: studentId,
    idempotency_key: idempotencyKey,
  },
  config(),
))
