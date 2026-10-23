import { api, buildHeaders } from './common'

const config = (params) => ({ headers: buildHeaders(), params })
const data = async promise => (await promise).data

export const getCourseGovernanceCatalog = () => data(api.get('/v1/course-governance/catalog', config()))
export const listTeachingClasses = courseId => data(api.get('/v1/course-governance/classes', config(courseId ? { course_id: courseId } : {})))
export const getTeachingClass = classId => data(api.get(`/v1/course-governance/classes/${encodeURIComponent(classId)}`, config()))
export const createTeachingClass = payload => data(api.post('/v1/course-governance/classes', payload, config()))
export const createTeachingGroup = (classId, payload) => data(api.post(`/v1/course-governance/classes/${encodeURIComponent(classId)}/groups`, payload, config()))
export const saveTeachingMember = (classId, payload) => data(api.put(`/v1/course-governance/classes/${encodeURIComponent(classId)}/members`, payload, config()))
export const createTeachingTask = (classId, payload) => data(api.post(`/v1/course-governance/classes/${encodeURIComponent(classId)}/tasks`, payload, config()))
export const publishTeachingTask = (taskId, expectedVersion) => data(api.post(`/v1/course-governance/tasks/${encodeURIComponent(taskId)}/publish`, { expected_version: expectedVersion }, config()))
export const withdrawGovernedCourse = (courseId, payload) => data(api.post(`/v1/course-governance/courses/${encodeURIComponent(courseId)}/withdraw`, payload, config()))
