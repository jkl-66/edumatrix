import { api, authConfig as config, request } from './common.js'

export function bootstrapM6TrainingDemo() {
  return request(api.post('/v1/m6/demo/bootstrap', {}, config()))
}

export function getM6EnterpriseWorkspace(params = {}) {
  return request(api.get('/v1/m6/enterprise/workspace', config(params)))
}

export function recordM6SkillEvidence(payload) {
  return request(api.post('/v1/m6/enterprise/evidence', payload, config()))
}

export function issueM6Certification(payload) {
  return request(api.post('/v1/m6/enterprise/certifications', payload, config()))
}

export function getM6TeacherInterventions(courseId) {
  return request(api.get('/v1/m6/teacher/interventions', config({ course_id: courseId })))
}

export function publishM6TeacherIntervention(payload) {
  return request(api.post('/v1/m6/teacher/interventions', payload, config()))
}

export function confirmM6TeacherIntervention(pathId, learnerEventId) {
  return request(api.post(`/v1/m6/teacher/interventions/${encodeURIComponent(pathId)}/confirm`, {
    learner_event_id: learnerEventId,
  }, config()))
}
