import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'

const source = readFileSync(new URL('../src/views/WrongQuestionBook.vue', import.meta.url), 'utf8')
const begin = source.slice(source.indexOf('function beginRedo('), source.indexOf('async function openPrimaryAction('))
const submit = source.slice(source.indexOf('async function submitRedo('), source.indexOf('async function loadFlashcard('))
const ref = value => ({ value })

function redoState() {
  const calls = []
  const state = {
    selectedQuestion: ref({ id: 17, question_version_id: 'question-a' }),
    redoLoading: ref(false), redoOpen: ref(true), redoError: ref(''), redoResult: ref(null),
    redoKey: ref('first-answer'), redoStartedAt: ref(Date.now()), answer: 'B',
    redoReady: () => Boolean(state.answer), redoPayload: () => ({ choice: state.answer }),
    resetRedoResponse: () => { state.answer = '' }, message: error => error.message,
    submitM5AssessmentAttempt: async payload => { calls.push(payload); return { attempt: { correct: false } } },
    loadData: async () => { state.redoKey.value = ''; state.redoOpen.value = false },
  }
  return { state, calls }
}

test('a new answer after a graded redo gets its own submission identity', async () => {
  const { state, calls } = redoState()
  const context = vm.createContext(state)
  vm.runInContext(`${begin}\n${submit}`, context)
  await vm.runInContext('submitRedo()', context)
  state.answer = 'A'
  await vm.runInContext('submitRedo()', context)
  assert.equal(calls.length, 2)
  assert.ok(calls[1].idempotency_key.length > 1)
  assert.notEqual(calls[1].idempotency_key, calls[0].idempotency_key)
  assert.equal(calls[1].answer.choice, 'A')
})

test('failed submission retains the answer and identity for retry', async () => {
  const { state, calls } = redoState()
  let fail = true
  state.submitM5AssessmentAttempt = async payload => {
    calls.push(payload)
    if (fail) throw new Error('connection interrupted')
    return { attempt: { correct: true } }
  }
  const context = vm.createContext(state)
  vm.runInContext(`${begin}\n${submit}`, context)
  await vm.runInContext('submitRedo()', context)
  assert.equal(state.answer, 'B')
  assert.equal(state.redoError.value, 'connection interrupted')
  fail = false
  await vm.runInContext('submitRedo()', context)
  assert.equal(calls[0].idempotency_key, calls[1].idempotency_key)
})
