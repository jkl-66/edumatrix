import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'

const source = readFileSync(new URL('../src/views/FormalExamWorkspace.vue', import.meta.url), 'utf8')
const loadCode = source.slice(source.indexOf('async function load()'), source.indexOf('async function loadTodayWork()'))

async function restore(sittingId) {
  const ref = value => ({ value })
  const selectedId = ref('')
  const exams = ref([])
  const state = {
    loading: ref(false), error: ref(''), todayWorkError: ref(''), studentNeedsCourse: ref(false),
    manager: ref(false), context: ref(null), gate: ref(null), courseCatalog: ref([]),
    courseId: ref('course-current'), reviewTaskId: ref(''), exams, selectedId,
    route: { query: { sitting_id: sittingId } },
    selected: { get value() { return exams.value.find(item => item.id === selectedId.value) } },
    listM5FormalExams: async () => ({ items: [
      { id: 'exam-current', course_id: 'course-current', sitting: { id: 'sitting-current', status: 'submitted' }, drafts: [{ answer: 'saved answer' }] },
      { id: 'exam-other', course_id: 'course-other', sitting: { id: 'sitting-other' } },
    ] }),
    getM5IntelligentExamContext: async () => ({ gate: { unlocked: true } }),
    listKnowledgeCourseShelf: async () => ({}), courseOptionsFromShelf: () => [],
    loadTodayWork: async () => {}, initializeLearnerForm: () => {},
    observeGeneration: async () => {},
    selectExam: exam => { selectedId.value = exam.id },
    hydrateExam: exam => { state.restoredDrafts = exam.drafts },
    messageFrom: error => error.message,
  }
  await vm.runInNewContext(`${loadCode}; load()`, state)
  return state
}

test('history sitting link restores the submitted exam and its saved answers', async () => {
  const state = await restore('sitting-current')
  assert.equal(state.selectedId.value, 'exam-current')
  assert.equal(state.restoredDrafts[0].answer, 'saved answer')
  assert.equal(state.error.value, '')
})

test('history does not select a sitting from another course or replace a missing sitting', async () => {
  for (const id of ['sitting-other', 'missing']) {
    const state = await restore(id)
    assert.equal(state.selectedId.value, '')
    assert.equal(state.exams.value.length, 1)
    assert.match(state.error.value, /没有找到这次作答/)
    assert.equal(state.restoredDrafts, undefined)
  }
})

test('opening a saved review exam preserves its own task scope', () => {
  const selectCode = source.slice(source.indexOf('function selectExam('), source.indexOf('function backToBuilder('))
  for (const reviewTask of ['review-plan:9', '']) {
    let destination
    const exam = { id: 'exam-review', course_id: 'saved-course', version: { configuration: { review_task_id: reviewTask } } }
    vm.runInNewContext(`${selectCode}; selectExam(exam)`, {
      exam, manager: { value: false }, selectedId: {}, reportEnvelope: {}, hydrateExam() {},
      router: { replace(value) { destination = value } },
    })
    assert.equal(destination.path, '/workspace/assessment/exams/exam-review')
    assert.equal(destination.query.course_id, 'saved-course')
    assert.equal(destination.query.review_task, reviewTask || undefined)
  }
})

test('a short-answer reference is displayed as teaching content without replacing its code', () => {
  const code = source.slice(source.indexOf('function displayAnswer('), source.indexOf('function sourceLabel('))
  const answer = 'arr[(arr % 2 != 0) & (arr >= 5)]，得到 [5, 7, 9]。'
  assert.equal(vm.runInNewContext(`${code}; displayAnswer({reference_answer: answer})`, { answer }), answer)
})
