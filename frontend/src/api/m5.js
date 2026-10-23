import { api, authConfig, request, normalizeApiError } from './common.js'

export {
  createGenerationJob as createM5ResourceGenerationJob,
  getGenerationJob as getM5ResourceGenerationJob,
  executeGenerationJobDemo as executeM5ResourceGenerationDemo,
  executeGenerationJob as executeM5ResourceGeneration,
  retryGenerationItem as retryM5ResourceGenerationItem,
  recoverGenerationJob as recoverM5ResourceGenerationJob,
} from './resourceBundles.js'

export function listM5Resources(params = {}) {
  return request(api.get('/v1/m5/resources', authConfig(params)))
}

export function getM5Resource(artifactId) {
  return request(api.get(`/v1/m5/resources/${encodeURIComponent(artifactId)}`, authConfig()))
}

export function createM5ResourceVersion(artifactId, payload) {
  return request(api.post(
    `/v1/m5/resources/${encodeURIComponent(artifactId)}/versions`,
    payload,
    authConfig(),
  ))
}

export function restoreM5ResourceVersion(artifactId, payload) {
  return request(api.post(
    `/v1/m5/resources/${encodeURIComponent(artifactId)}/restore`,
    payload,
    authConfig(),
  ))
}

export function completeM5Resource(artifactId, payload) {
  return request(api.post(
    `/v1/m5/resources/${encodeURIComponent(artifactId)}/complete`,
    payload,
    authConfig(),
  ))
}

export function compareM5ResourceVersions(artifactId, leftVersion, rightVersion) {
  return request(api.get(`/v1/m5/resources/${encodeURIComponent(artifactId)}/compare`, authConfig({
    left_version: leftVersion,
    right_version: rightVersion,
  })))
}

export function exportM5Resource(artifactId, versionNumber) {
  return request(api.get(`/v1/m5/resources/${encodeURIComponent(artifactId)}/export`, authConfig({
    version_number: versionNumber,
  })))
}

export async function exportM5Deck(artifactId, format, versionId) {
  try {
    const config = authConfig({ version_id: versionId || undefined })
    config.responseType = 'blob'
    return (await api.get(
      `/v1/m5/resources/${encodeURIComponent(artifactId)}/deck-export/${encodeURIComponent(format)}`,
      config,
    )).data
  } catch (error) {
    throw normalizeApiError(error)
  }
}

export async function getM5VideoMedia(artifactId, recommendationId, versionId) {
  try {
    const config = authConfig({ version_id: versionId || undefined })
    config.responseType = 'blob'
    return (await api.get(
      `/v1/m5/resources/${encodeURIComponent(artifactId)}/video-media/${encodeURIComponent(recommendationId)}`,
      config,
    )).data
  } catch (error) {
    throw normalizeApiError(error)
  }
}

export function archiveM5Resource(artifactId, archived, expectedLockVersion) {
  const config = authConfig()
  return request(api.post(`/v1/m5/resources/${encodeURIComponent(artifactId)}/archive`, {
    archived,
    expected_lock_version: expectedLockVersion,
  }, config))
}

export function getM5ModelGovernance() {
  return request(api.get('/v1/m5/model-governance', authConfig()))
}

export function getM5ModelOperations() {
  return request(api.get('/v1/m5/model-operations', authConfig()))
}

export function getM5Task(taskId, afterEventSequence = 0) {
  return request(api.get(`/v1/m5/tasks/${encodeURIComponent(taskId)}`, authConfig({
    after_event_sequence: afterEventSequence,
  })))
}

export function cancelM5Task(taskId) {
  return request(api.post(`/v1/m5/tasks/${encodeURIComponent(taskId)}/cancel`, {}, authConfig()))
}

export function retryM5TaskStep(taskId, sequence) {
  return request(api.post(
    `/v1/m5/tasks/${encodeURIComponent(taskId)}/steps/${sequence}/retry`,
    {},
    authConfig(),
  ))
}

export function reworkM5TaskStep(taskId, sequence, reasonCode) {
  return request(api.post(
    `/v1/m5/tasks/${encodeURIComponent(taskId)}/steps/${sequence}/rework`,
    { reason_code: reasonCode },
    authConfig(),
  ))
}

export function getM5LegacyMigrationGovernance() {
  return request(api.get('/v1/m5/legacy-migration-governance', authConfig()))
}

export function getM5PlanningTargets() {
  return request(api.get('/v1/m5/planning-targets', authConfig()))
}

export function listM5Plans(params = {}) {
  return request(api.get('/v1/m5/plans', authConfig(params)))
}

export function getM5Plan(planId) {
  return request(api.get(`/v1/m5/plans/${encodeURIComponent(planId)}`, authConfig()))
}

export function createM5Plan(payload) {
  return request(api.post('/v1/m5/plans', payload, authConfig()))
}

export function reviseM5Plan(planId, payload) {
  return request(api.post(`/v1/m5/plans/${encodeURIComponent(planId)}/revisions`, payload, authConfig()))
}

export function confirmM5Plan(planId, expectedLockVersion) {
  return request(api.post(`/v1/m5/plans/${encodeURIComponent(planId)}/confirm`, {
    expected_lock_version: expectedLockVersion,
  }, authConfig()))
}

export function getM5TextbookPathDraft(courseId) {
  return request(api.get('/v1/m5/textbook-path-draft', authConfig({ course_id: courseId })))
}

export function generateM5TextbookPathDraft(courseId, timeBudgetMinutes = 90) {
  return request(api.post('/v1/m5/textbook-path-draft/generate', {
    course_id: courseId,
    time_budget_minutes: timeBudgetMinutes,
  }, authConfig()))
}

export function listM5Paths(params = {}) {
  return request(api.get('/v1/m5/paths', authConfig(params)))
}

export function transitionM5Path(pathId, targetStatus, expectedLockVersion) {
  return request(api.post(`/v1/m5/paths/${encodeURIComponent(pathId)}/transition`, {
    target_status: targetStatus,
    expected_lock_version: expectedLockVersion,
  }, authConfig()))
}

export function getM5TodayWork(courseId = '') {
  return request(api.get('/v1/m5/today', authConfig(courseId ? { course_id: courseId } : {})))
}

export function getM5Schedule(day = 1, courseId = '') {
  return request(api.get('/v1/m5/schedule', authConfig({
    day,
    ...(courseId ? { course_id: courseId } : {}),
  })))
}

export function getM5WorkspaceOverview(courseId = '') {
  return request(api.get('/v1/m5/workspace', authConfig(courseId ? { course_id: courseId } : {})))
}

export function getM5DashboardSummary(courseId = '') {
  return request(api.get('/v1/m5/dashboard', authConfig(courseId ? { course_id: courseId } : {})))
}

export function runM5WorkspaceAction(payload) {
  return request(api.post('/v1/m5/workspace/actions', payload, authConfig()))
}

export function getM5WorkspaceTaskTimeline(taskId, courseId) {
  return request(api.get(
    `/v1/m5/workspace/tasks/${encodeURIComponent(taskId)}/timeline`,
    authConfig({ course_id: courseId }),
  ))
}

export function executeM5WorkspaceLocalDemoTask(taskId) {
  return request(api.post(
    `/v1/m5/workspace/tasks/${encodeURIComponent(taskId)}/execute-local-demo`,
    {},
    authConfig(),
  ))
}

export function createM5LearningEvent(payload) {
  return request(api.post('/v1/m5/learning-events', payload, authConfig()))
}

export function getLatestM5LearningFeedback(params = {}) {
  return request(api.get('/v1/m5/learning-feedback/latest', authConfig(params)))
}

export function getM5LearningAggregation(eventId) {
  return request(api.get(
    `/v1/m5/learning-events/${encodeURIComponent(eventId)}/aggregation`,
    authConfig(),
  ))
}

export function replayM5LearningEvent(eventId) {
  return request(api.post(
    `/v1/m5/learning-events/${encodeURIComponent(eventId)}/process`,
    {},
    authConfig(),
  ))
}

export function getM5ReviewQueue() {
  return request(api.get('/v1/m5/review-queue', authConfig()))
}

export async function exportM5ReviewDiagnosis() {
  try {
    const response = await api.get('/v1/m5/review-export', {
      ...authConfig(),
      responseType: 'blob',
    })
    return response.data
  } catch (error) {
    throw normalizeApiError(error)
  }
}

export function decideM5Misconception(reviewId, payload) {
  return request(api.post(
    `/v1/m5/assessment/misconceptions/${encodeURIComponent(reviewId)}/decision`,
    payload,
    authConfig(),
  ))
}

export function getM5RetestTask(taskId) {
  return request(api.get(`/v1/m5/assessment/retests/${encodeURIComponent(taskId)}`, authConfig()))
}

export function submitM5Retest(taskId, payload) {
  return request(api.post(
    `/v1/m5/assessment/retests/${encodeURIComponent(taskId)}/attempts`,
    payload,
    authConfig(),
  ))
}

export function listM5AssessmentQuestions(params = {}) {
  return request(api.get('/v1/m5/assessment/questions', authConfig(params)))
}

export function getM5AssessmentQuestion(versionId) {
  return request(api.get(`/v1/m5/assessment/questions/${encodeURIComponent(versionId)}`, authConfig()))
}

export function getM5NextCatQuestion(payload = {}) {
  return request(api.post('/v1/m5/assessment/cat/next', payload, authConfig()))
}

export function getM5AssessmentAbility(params = {}) {
  return request(api.get('/v1/m5/assessment/ability', authConfig(params)))
}

export function getM5ProfileSummary(params = {}) {
  return request(api.get('/v1/m5/profile-summary', authConfig(params)))
}

export function getM5PersonalActivity(params = {}) {
  return request(api.get('/v1/m5/personal-activity', authConfig(params)))
}

export function submitM5AssessmentAttempt(payload) {
  return request(api.post('/v1/m5/assessment/attempts', payload, authConfig()))
}

export function getM5WorkspaceExercise(questionVersionId) {
  return request(api.get(`/v1/m5/workspace/exercises/${encodeURIComponent(questionVersionId)}`, authConfig()))
}

export function getM5AssessmentAttempt(attemptId) {
  return request(api.get(`/v1/m5/assessment/attempts/${encodeURIComponent(attemptId)}`, authConfig()))
}

export function listM5FormalExams() {
  return request(api.get('/v1/m5/assessment/exams', authConfig()))
}

export function getM5IntelligentExamGate(courseId) {
  return request(api.get('/v1/m5/assessment/exam-gate', authConfig({ course_id: courseId })))
}

export function getM5IntelligentExamContext(courseId) {
  return request(api.get('/v1/m5/assessment/intelligent-exams/context', authConfig({ course_id: courseId })))
}

export function createM5IntelligentExam(payload) {
  return request(api.post('/v1/m5/assessment/intelligent-exams', payload, authConfig()))
}

export function createM5FormalExam(payload) {
  return request(api.post('/v1/m5/assessment/exams', payload, authConfig()))
}

export function transitionM5FormalExam(examId, payload) {
  return request(api.post(`/v1/m5/assessment/exams/${encodeURIComponent(examId)}/transition`, payload, authConfig()))
}

export function assignM5FormalExam(examId, learnerPublicId) {
  return request(api.post(`/v1/m5/assessment/exams/${encodeURIComponent(examId)}/assignments`, { learner_public_id: learnerPublicId }, authConfig()))
}

export function startM5FormalSitting(sittingId, expectedLockVersion) {
  return request(api.post(`/v1/m5/assessment/exam-sittings/${encodeURIComponent(sittingId)}/start`, { expected_lock_version: expectedLockVersion }, authConfig()))
}

export function answerM5FormalSitting(sittingId, payload) {
  return request(api.post(`/v1/m5/assessment/exam-sittings/${encodeURIComponent(sittingId)}/responses`, payload, authConfig()))
}

export function submitM5FormalSitting(sittingId, expectedLockVersion) {
  return request(api.post(`/v1/m5/assessment/exam-sittings/${encodeURIComponent(sittingId)}/submit`, { expected_lock_version: expectedLockVersion }, authConfig()))
}

export function requestM5FormalReview(sittingId, attemptId, reason) {
  return request(api.post(`/v1/m5/assessment/exam-sittings/${encodeURIComponent(sittingId)}/reviews`, { attempt_id: attemptId, reason }, authConfig()))
}

export function listM5FormalReviews() {
  return request(api.get('/v1/m5/assessment/exam-reviews', authConfig()))
}

export function completeM5FormalReview(reviewId, payload) {
  return request(api.post(`/v1/m5/assessment/exam-reviews/${encodeURIComponent(reviewId)}/complete`, payload, authConfig()))
}

export function generateM5FormalReport(sittingId) {
  return request(api.post(`/v1/m5/assessment/exam-sittings/${encodeURIComponent(sittingId)}/reports`, {}, authConfig()))
}

export function formalReportExportUrl(reportId, format = 'json') {
  return `/api/v1/m5/assessment/exam-reports/${encodeURIComponent(reportId)}/export/${format}`
}

export function createM5TutorContext(payload) {
  return request(api.post('/v1/m5/tutor-contexts', payload, authConfig()))
}

export function listM5TutorContexts(params = {}) {
  return request(api.get('/v1/m5/tutor-contexts', authConfig(params)))
}

export function getM5TutorContext(contextId) {
  return request(api.get(`/v1/m5/tutor-contexts/${encodeURIComponent(contextId)}`, authConfig()))
}

export function archiveM5TutorContext(contextId, expectedLockVersion) {
  return request(api.post(`/v1/m5/tutor-contexts/${encodeURIComponent(contextId)}/archive`, {
    expected_lock_version: expectedLockVersion,
  }, authConfig()))
}

export function preflightM5TutorRequest(contextId, payload) {
  return request(api.post(`/v1/m5/tutor-contexts/${encodeURIComponent(contextId)}/preflight`, payload, authConfig()))
}
