import assert from 'node:assert/strict'
import test from 'node:test'
import { readPreference, writePreference } from '../src/utils/learningPreferenceStorage.js'

test('preferences restore per account without copying the first learner into the next', t => {
  const previous = globalThis.localStorage
  const data = new Map([['edumatrix_username', 'learner-a'], ['edumatrix_read_aloud_enabled', 'true']])
  globalThis.localStorage = { getItem: k => data.get(k) ?? null, setItem: (k, v) => data.set(k, String(v)) }
  t.after(() => { globalThis.localStorage = previous })
  const key = 'edumatrix_read_aloud_enabled'
  assert.equal(readPreference(key, 'false'), 'true')
  writePreference(key, 'false')
  data.set('edumatrix_username', 'learner-b')
  assert.equal(readPreference(key, 'false'), 'false')
  writePreference(key, 'true')
  data.set('edumatrix_username', 'learner-a')
  assert.equal(readPreference(key), 'false')
  data.set('edumatrix_username', 'learner-b')
  assert.equal(readPreference(key), 'true')
})
