import assert from 'node:assert/strict'
import test from 'node:test'
import { buildHeaders } from '../src/api/common.js'
import { api, authConfig, clearAuthSession, EduMatrixApiError, request } from '../src/api/common.js'
import { listM5Resources, exportM5Deck, createM5ResourceVersion, restoreM5ResourceVersion } from '../src/api/m5.js'
import { startCodeSandboxRun } from '../src/api/codeSandbox.js'
import { createFeynmanSession, listFeynmanSessions } from '../src/api/feynman.js'
import { getDiagnosticPreflight } from '../src/api/diagnostics.js'
import { getAdminAccounts } from '../src/api/admin.js'
import { getIntegrationFaultDrills } from '../src/api/integrationFaultDrill.js'
import { getIntegrationReconciliation } from '../src/api/integrationReconciliation.js'
import { getJobStandardImpactWorkspace } from '../src/api/jobStandardImpact.js'
import { getLocalHrWorkspace } from '../src/api/localHr.js'
import { getStudentJourneyWorkspace } from '../src/api/competitionJourney.js'
import { getLocalLmsWorkspace } from '../src/api/localLms.js'
import { getLocalSsoWorkspace } from '../src/api/localSso.js'
import { getM7IntegrationWorkspace } from '../src/api/m7.js'
import { getM6EnterpriseWorkspace } from '../src/api/m6.js'
import { listTeachingAnalyticsReports } from '../src/api/teachingAnalytics.js'

function setup(t, adapter) {
  const values = new Map([['edumatrix_token', 'synthetic-test-token'], ['edumatrix_teaching_style', 'guided']])
  const priorStorage = globalThis.localStorage
  const priorWindow = globalThis.window
  const priorAdapter = api.defaults.adapter
  globalThis.localStorage = { getItem: (key) => values.get(key) ?? null, setItem: (key, value) => values.set(key, value), removeItem: (key) => values.delete(key) }
  globalThis.window = { location: { pathname: '/login', assign() {} } }
  api.defaults.adapter = adapter
  t.after(() => {
    api.defaults.adapter = priorAdapter
    globalThis.localStorage = priorStorage
    globalThis.window = priorWindow
  })
  return values
}

const response = (config, data = { ok: true }) => ({ data, status: 200, statusText: 'OK', headers: {}, config })

test('saved answer depth reaches chat requests and ignores unsupported values', t => {
  const values = setup(t, async config => response(config))
  values.set('edumatrix_response_depth', 'detailed')
  assert.equal(buildHeaders()['X-EduMatrix-Response-Depth'], 'detailed')
  values.set('edumatrix_response_depth', 'unexpected')
  assert.equal(buildHeaders()['X-EduMatrix-Response-Depth'], undefined)
})

test('editing or restoring a resource refreshes its context without losing the selected course', async t => {
  const values = setup(t, async config => response(config))
  for (const action of [createM5ResourceVersion, restoreM5ResourceVersion]) {
    values.set('edumatrix_context_ref', JSON.stringify({courseId:'course-1',resourceId:'resource-1',version:'old'}))
    await action('resource-1', {version_id:'historical'})
    const current = JSON.parse(values.get('edumatrix_context_ref'))
    assert.equal(current.version,null)
    assert.equal(current.courseId,'course-1')
    assert.equal(current.resourceId,'resource-1')
    values.set('edumatrix_context_ref', JSON.stringify({courseId:'course-2',resourceId:'resource-2',version:'keep'}))
    await action('resource-1', {})
    assert.equal(JSON.parse(values.get('edumatrix_context_ref')).version,'keep')
  }
})

test('a failed resource restore retains the previous learning context', async t => {
  const values = setup(t, async () => { throw {response:{status:409,data:{detail:'版本已更新'}}} })
  const stored = JSON.stringify({courseId:'course-1',resourceId:'resource-1',version:'old'})
  values.set('edumatrix_context_ref',stored)
  await assert.rejects(restoreM5ResourceVersion('resource-1',{}))
  assert.equal(values.get('edumatrix_context_ref'),stored)
})

test('common configuration reads current authentication and teaching style for each request', (t) => {
  const values = setup(t)
  const params = { limit: 0, include_complete: false }
  assert.deepEqual(authConfig(params), { params, headers: { Authorization: 'Bearer synthetic-test-token', 'X-EduMatrix-Teaching-Style': 'guided' } })
  values.clear()
  assert.deepEqual(authConfig(params), { params, headers: {} })
})

test('resource, sandbox, Feynman and diagnostic clients preserve request contracts', async (t) => {
  const calls = []
  setup(t, async (config) => { calls.push(config); return response(config) })
  assert.deepEqual(await listM5Resources({ course_id: 'course-1' }), { ok: true })
  await startCodeSandboxRun('resource/one', { code: 'print(1)' })
  await createFeynmanSession('resource-2', 'idempotency-1')
  await getDiagnosticPreflight({ course_id: 'course-1' })
  assert.equal(calls[0].url, '/v1/m5/resources')
  assert.deepEqual(calls[0].params, { course_id: 'course-1' })
  assert.equal(calls[1].url, '/v1/code-sandbox/resources/resource%2Fone/runs')
  assert.equal(calls[1].method, 'post')
  assert.deepEqual(JSON.parse(calls[1].data), { code: 'print(1)' })
  assert.deepEqual(JSON.parse(calls[2].data), { source_resource_id: 'resource-2', idempotency_key: 'idempotency-1' })
  assert.deepEqual(calls[3].params, { course_id: 'course-1' })
  for (const config of calls) {
    assert.equal(config.baseURL, '/api')
    assert.equal(config.headers.Authorization, 'Bearer synthetic-test-token')
    assert.equal(config.headers['X-EduMatrix-Teaching-Style'], 'guided')
  }
})

test('Feynman session creation and history retain the selected material version', async (t) => {
  const calls = []
  setup(t, async config => { calls.push(config); return response(config) })
  await createFeynmanSession('resource-1', 'attempt-key', 'old-version')
  await listFeynmanSessions('resource-1', 'old-version')
  assert.deepEqual(JSON.parse(calls[0].data), { source_resource_id: 'resource-1',
    source_resource_version_id: 'old-version', idempotency_key: 'attempt-key' })
  assert.deepEqual(calls[1].params, { source_resource_id: 'resource-1', source_resource_version_id: 'old-version' })
})

test('remaining migrated clients keep their endpoints and query shapes', async (t) => {
  const calls = []
  setup(t, async (config) => { calls.push(config); return response(config) })
  for (const run of [getAdminAccounts, getIntegrationFaultDrills, getIntegrationReconciliation, () => getJobStandardImpactWorkspace('org-1'), getLocalHrWorkspace, getStudentJourneyWorkspace, getLocalLmsWorkspace, getLocalSsoWorkspace, getM7IntegrationWorkspace, getM6EnterpriseWorkspace, () => listTeachingAnalyticsReports('class-1')]) {
    assert.deepEqual(await run(), { ok: true })
  }
  assert.deepEqual(calls.map((config) => config.url), [
    '/v1/admin/accounts', '/v1/integration-fault-drills/workspace', '/v1/integration-reconciliation/workspace', '/v1/job-standard-impact/workspace', '/v1/local-hr/workspace', '/v1/competition-journeys/student', '/v1/local-lms/workspace', '/v1/local-sso/workspace', '/v1/m7/integrations/workspace', '/v1/m6/enterprise/workspace', '/v1/teaching-analytics/reports',
  ])
  assert.deepEqual(calls[3].params, { organization_id: 'org-1' })
  assert.deepEqual(calls.at(-1).params, { class_id: 'class-1' })
  for (const config of calls) assert.equal(config.headers['X-EduMatrix-Teaching-Style'], 'guided')
})

test('binary resource downloads preserve blob configuration and version selection', async (t) => {
  const blob = new Blob(['synthetic deck'])
  let call
  setup(t, async (config) => { call = config; return response(config, blob) })
  assert.equal(await exportM5Deck('deck/1', 'pdf', 'version-2'), blob)
  assert.equal(call.url, '/v1/m5/resources/deck%2F1/deck-export/pdf')
  assert.equal(call.responseType, 'blob')
  assert.deepEqual(call.params, { version_id: 'version-2' })
})

test('shared data handling preserves structured API errors and existing normalized errors', async () => {
  const detail = { message: '版本已变更' }
  await assert.rejects(request(Promise.reject({ response: { status: 409, data: { detail } } })), (error) => error instanceof EduMatrixApiError && error.status === 409 && error.kind === 'conflict' && error.detail === detail && error.message === '版本已变更')
  const prior = new EduMatrixApiError(403, '无权查看')
  await assert.rejects(request(Promise.reject(prior)), (error) => error === prior)
})

test('migrated client errors still pass through the common authentication interceptor', async (t) => {
  const values = setup(t, async config => { throw { config, response: { status: 401, data: { detail: '已过期' } } } })
  values.set('edumatrix_context_ref', JSON.stringify({ userId: 'previous-user', sourceRefId: 'previous-source' }))
  values.set('edumatrix_course_id', 'previous-course')
  const redirects = []
  globalThis.window.location = { pathname: '/workspace/resources/handouts/example', search: '?course_id=math&version_id=v2', hash: '#quiz', assign: url => redirects.push(url) }
  await assert.rejects(getAdminAccounts(), (error) => error instanceof EduMatrixApiError && error.kind === 'unauthorized')
  assert.equal(values.has('edumatrix_token'), false)
  assert.equal(values.has('edumatrix_context_ref'), false)
  assert.equal(values.has('edumatrix_course_id'), false)
  assert.equal(new URL(redirects[0], 'http://localhost').searchParams.get('redirect'), '/workspace/resources/handouts/example?course_id=math&version_id=v2#quiz')
})

test('late unauthorized responses cannot turn logout into expiry or clear a newly signed-in account', async t => {
  let rejectPending
  const values = setup(t, config => new Promise((resolve, reject) => {
    rejectPending = () => reject({config,response:{status:401,data:{detail:'已过期'}}})
  }))
  const redirects = []
  globalThis.window.location = {pathname:'/landing',assign:url=>redirects.push(url)}
  for (const nextToken of [null, 'new-account-token']) {
    values.set('edumatrix_token','old-account-token')
    const pending = getAdminAccounts()
    clearAuthSession()
    if (nextToken) values.set('edumatrix_token', nextToken)
    rejectPending()
    await assert.rejects(pending, error=>error.kind === 'unauthorized')
    assert.equal(values.get('edumatrix_token') || null, nextToken)
  }
  assert.deepEqual(redirects, [])
})

test('account changes clear previous learning position and chat state while preserving local display preferences', (t) => {
  const values = setup(t)
  for (const key of ['edumatrix_context_ref', 'edumatrix_course_id', 'edumatrix_course_title', 'edumatrix_chat_messages', 'edumatrix_onboarded', 'edumatrix_viewing_student']) values.set(key, 'previous-account-state')
  values.set('edumatrix_display_density', 'comfortable')
  clearAuthSession()
  assert.deepEqual([...values], [['edumatrix_teaching_style', 'guided'], ['edumatrix_display_density', 'comfortable']])
})
