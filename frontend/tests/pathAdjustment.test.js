import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'

const source = readFileSync(new URL('../src/views/LearningPathGraph.vue', import.meta.url), 'utf8')
const selection = source.slice(source.indexOf('function rememberPathSelection('), source.indexOf('async function toggleSubjectPath('))
const generate = source.slice(source.indexOf('async function generateTextbookDraft('), source.indexOf('async function confirmTextbookDraft('))

test('selecting a second subject loads its draft and preserves that selection for refresh', async () => {
  let address = 'http://localhost/workspace/path?course_id=old-course'
  const requested = []
  const state = {
    URL, window: { location: { get href() { return address } }, history: {
      state: {}, replaceState: (_state, _title, url) => { address = new URL(url, address).href },
    } },
    selectedSubjectId: { value: 'old-course' }, pathViewMode: { value: 'total' },
    pathAdjustment: { value: 'supplement' }, textbookDraftLoading: { value: false },
    requestedDraftId: { value: 'prior-report-draft' },
    m5Path: { value: null }, pathRecords: { value: [{ course_id: 'chosen-course', id: 'chosen-path' }] },
    textbookDraft: { value: { course: { id: 'old-course' } } }, textbookDraftError: { value: '' },
    selectedScheduleDay: { value: 3 }, selectScheduleDay: async () => {},
    getM5TextbookPathDraft: async id => { requested.push(id); return { course: { id } } },
    message: String,
    resetPathTask: () => {}, restorePathTask: async () => {},
  }
  await vm.runInNewContext(`${selection}; selectSubject({id:'chosen-course'})`, state)
  assert.deepEqual(requested, ['chosen-course'])
  assert.equal(state.textbookDraft.value.course.id, 'chosen-course')
  assert.equal(state.m5Path.value.id, 'chosen-path')
  assert.equal(new URL(address).searchParams.get('course_id'), 'chosen-course')
  assert.equal(new URL(address).searchParams.get('view'), 'subject')
  assert.equal(new URL(address).searchParams.get('adjustment'), 'supplement')
  assert.equal(new URL(address).searchParams.get('schedule_day'), '3')
  assert.equal(state.requestedDraftId.value, '')
  assert.equal(new URL(address).searchParams.has('draft_id'), false)
})

test('generation uses the chosen course even when the initial route has another course', async () => {
  const requested = []
  const state = {
    URL, window: { location: { href: 'http://localhost/workspace/path?course_id=chosen-course&draft_id=prior-report' },
      history: { state: {}, replaceState: () => {} } }, requestedDraftId: { value: 'prior-report' },
    route: { query: { course_id: 'old-course' } }, currentCourseId: { value: 'chosen-course' },
    isPersonalPath: { value: false }, textbookDraftLoading: { value: false },
    pathTaskBusy: { value: false }, acceptPathTask: async () => {},
    pathAdjustment: { value: 'supplement' },
    textbookDraftError: { value: '' }, textbookDraft: { value: null }, generationNotice: { value: '' },
    generateM5TextbookPathDraft: async (id, budget, fullCoverage) => { requested.push(id); assert.equal(fullCoverage, true); return { changed: false, course: { id } } },
    message: String,
  }
  await vm.runInNewContext(`${generate}; generateTextbookDraft()`, state)
  assert.deepEqual(requested, ['chosen-course'])
  assert.equal(state.textbookDraft.value.course.id, 'chosen-course')
  assert.match(state.generationNotice.value, /学习情况没有变化/)
  assert.equal(state.textbookDraftLoading.value, false)
})
