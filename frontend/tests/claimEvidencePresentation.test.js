import { test } from 'node:test'
import assert from 'node:assert/strict'
import { claimEvidenceStatus, hasAnswerRevision, answerRevisionPresentation, answerRevisionEntries } from '../src/utils/claimEvidencePresentation.js'

test('correct worked calculation is distinguished from a missing textbook quotation', () => {
  assert.deepEqual(claimEvidenceStatus({ support: 'unsupported', basis: 'worked_example', revisionNeeded: false,
    calculations: [{ checked: true, agrees: true, calculated: '4.9141125', claimed: '4.914', approximate: true }] }),
  { support: 'worked_example', label: '按题设验算' })
  assert.equal(claimEvidenceStatus({ support: 'unsupported', basis: 'worked_example', revisionNeeded: false }).label, '题设推导')
})

test('unresolved evidence and calculation failures cannot receive a worked-result label', () => {
  assert.equal(claimEvidenceStatus({ support: 'unsupported', basis: 'source', revisionNeeded: false }).label, '资料不足')
  assert.equal(claimEvidenceStatus({ support: 'unsupported', basis: 'worked_example', revisionNeeded: true }).support, 'unsupported')
  assert.equal(claimEvidenceStatus({ support: 'contradicted', basis: 'worked_example', revisionNeeded: false }).support, 'contradicted')
  assert.equal(claimEvidenceStatus({ support: 'unsupported', basis: 'worked_example', revisionNeeded: false,
    calculations: [{ checked: true, agrees: false }] }).label, '计算需修正')
  assert.equal(claimEvidenceStatus({ support: 'unsupported', basis: 'worked_example', revisionNeeded: false,
    calculations: [{ checked: false }] }).label, '题设推导')
})

test('an empty or partial revision object does not claim the answer was corrected', () => {
  for (const value of [null, {}, { before: '', after: '' }, { before: '旧稿' }, { before: ' ', after: '新稿' }]) {
    assert.equal(hasAnswerRevision(value), false)
  }
  assert.equal(hasAnswerRevision({ before: '旧稿', after: '新稿' }), true)
})

test('a saved revision without a finished review is not presented as an approved answer', () => {
  for (const decision of ['unverified', undefined, 'unexpected']) {
    const presentation = answerRevisionPresentation({ decision, before: '旧稿', after: '待核稿' })
    assert.match(presentation.message, /尚未核对完成，暂未作为答案/)
    assert.equal(presentation.afterLabel, '查看尚未核对完成的讲解')
  }
  assert.match(answerRevisionPresentation({ decision: 'rejected' }).message, /还有矛盾/)
  assert.match(answerRevisionPresentation({ decision: 'verified' }).message, /已经修正/)
  assert.match(answerRevisionPresentation({ decision: 'qualified' }).message, /仍缺少依据/)
})

test('calculation labels preserve an explicit denial of the wrong value', () => {
  const claim = { support: 'unsupported', basis: 'worked_example', revisionNeeded: false }
  assert.equal(claimEvidenceStatus({ ...claim,
    calculations: [{ checked: true, agrees: false, resultNegated: true, claimConsistent: true }] }).label, '按题设验算')
  assert.equal(claimEvidenceStatus({ ...claim,
    calculations: [{ checked: true, agrees: true, resultNegated: true, claimConsistent: false }] }).label, '计算需修正')
})

test('a verified absence observation is distinguished from an unsupported teaching claim', () => {
  assert.deepEqual(claimEvidenceStatus({ support: 'unsupported', basis: 'source_scope', revisionNeeded: false }),
    { support: 'source_scope', label: '本次资料范围' })
  for (const support of ['unsupported', 'contradicted']) {
    assert.equal(claimEvidenceStatus({ support, basis: 'source_scope', revisionNeeded: true }).support, support)
  }
})

test('retry keeps current and previous revisions separate without shortening or changing the saved drafts', () => {
  const longDraft = '旧稿中的完整推导。'.repeat(1000)
  const history = [{ attempt: 1, revision: { before: '首稿', after: longDraft, decision: 'unverified',
    claimsBefore: [{ claim: '第一轮问题', support: 'unsupported', supportReason: '第一轮依据' }] } },
  { attempt: 2, revision: { before: '第二稿', after: '仍有错误', decision: 'rejected' } }]
  const original = structuredClone(history)
  const current = { before: '本次原稿', after: '本次修订稿', decision: 'verified',
    claimsBefore: [{ claim: '本次问题', revisionNeeded: true, review: { revision: '本次意见' } }] }
  const entries = answerRevisionEntries(current, history)
  assert.deepEqual(entries.map(item => item.title), ['本次核对与修正', '第 2 次保留的讲解', '第 1 次保留的讲解'])
  assert.equal(entries[2].revision.after, longDraft)
  assert.deepEqual(entries[0].issues, [{ claim: '本次问题', reason: '本次意见' }])
  assert.deepEqual(entries[2].issues, [{ claim: '第一轮问题', reason: '第一轮依据' }])
  assert.match(entries[1].presentation.message, /当时仍有矛盾，未作为答案/)
  assert.match(entries[2].presentation.message, /当时尚未完成核对，未作为答案/)
  assert.doesNotMatch(entries[2].presentation.message, /可以重试/)
  assert.deepEqual(history, original)
})

test('saved revisions remain available while the next attempt has no candidate yet', () => {
  const saved = { attempt: 3, revision: { before: '原稿', after: '待核稿', decision: 'unverified' } }
  assert.deepEqual(answerRevisionEntries(null, [null, {}, { revision: { before: '未完整生成' } }, saved])
    .map(item => item.title), ['第 3 次保留的讲解'])
  assert.deepEqual(answerRevisionEntries({}, null), [])
})
