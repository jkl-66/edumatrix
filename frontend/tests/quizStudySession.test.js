import test from 'node:test'
import assert from 'node:assert/strict'
import { quizStartQuestion, quizStudySession } from '../src/utils/quizStudySession.js'

test('resume honors explicit question, otherwise continues new work before corrections', () => {
  const questions = [
    { id: 'wrong', attempts: [{ correct: false }] },
    { id: 'done', attempts: [{ correct: true }] },
    { id: 'new', attempts: [] },
  ]
  assert.equal(quizStartQuestion(questions).id, 'new')
  assert.equal(quizStartQuestion(questions, 'done').id, 'done')
  assert.equal(quizStartQuestion(questions, 'old-version-id').id, 'new')
  assert.equal(quizStartQuestion(questions.slice(0, 2)).id, 'wrong')
  assert.equal(quizStartQuestion([]), null)
})

test('segment stop depends on actual submissions, without claiming mastery or changing progress', () => {
  const sessions = [
    { startQuestion: 1, endQuestion: 2, estimatedMinutes: 20 },
    { startQuestion: 3, endQuestion: 4, estimatedMinutes: 20 },
  ]
  const questions = Array.from({ length: 4 }, (_, i) => ({ id: String(i), attempts: [] }))
  const unchanged = JSON.stringify(questions)
  assert.equal(quizStudySession(sessions, questions, 1).attempted, false)
  assert.equal(JSON.stringify(questions), unchanged)
  questions[0].attempts = [{ correct: false }]
  questions[1].attempts = [{ correct: true }]
  const stop = quizStudySession(sessions, questions, 1)
  assert.equal(stop.reachedEnd, true)
  assert.equal(stop.attempted, true)
  assert.equal(stop.nextQuestion, 3)
  assert.equal(quizStudySession(sessions, questions, 0).reachedEnd, false)
  assert.equal(quizStudySession(sessions, questions, 3).nextQuestion, null)
  assert.equal(quizStudySession([], questions, 0), null)
})
