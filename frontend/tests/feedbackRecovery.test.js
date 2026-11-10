import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'

const source = readFileSync(new URL('../src/views/FeynmanWorkspace.vue', import.meta.url), 'utf8')
const recover = source.slice(source.indexOf('async function recoverActionTask'), source.indexOf('const steps ='))

test('refresh observes a saved feedback action without resubmitting its model work', async () => {
  const task = { id:'original', action:'evaluate_round1', expected_version:2, status:'running' }
  const state = {
    session:{ value:{ session_id:'saved-session' } }, actionPending:{ value:'' },
    storageKey: x => x, localStorage:{ getItem:() => JSON.stringify({ action:'evaluate_round1', expected_version:2 }) },
    getFeynmanActionTask: async () => ({ task }),
    applyFeynmanAction: async () => { throw Error('must not submit twice') },
  }
  const fn = vm.runInNewContext(recover + '; recoverActionTask', state)
  assert.equal((await fn()).task.id, 'original')
  assert.equal(state.actionPending.value, 'evaluate_round1')
})

test('a lost initial request is resent with the exact saved answer and identity', async () => {
  const request = {action:'answer_question', text:'我的疑问', expected_version:4, idempotency_key:'original-key', background:true}
  const calls = []
  const state = {
    session:{ value:{ session_id:'saved-session' } }, actionPending:{ value:'answer_question' },
    storageKey:x => x, localStorage:{ getItem:() => JSON.stringify(request) },
    getFeynmanActionTask: async () => ({task:{ id:'earlier-action', expected_version:2, status:'completed' }}),
    applyFeynmanAction: async (id, payload) => { calls.push([id,JSON.stringify(payload)]); return {task:{id:'original',status:'queued',action:payload.action}} },
  }
  const fn = vm.runInNewContext(recover + '; recoverActionTask', state)
  assert.equal((await fn()).task.id, 'original')
  assert.deepEqual(calls, [['saved-session', JSON.stringify(request)]])
})
