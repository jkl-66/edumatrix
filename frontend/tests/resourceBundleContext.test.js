import test from 'node:test'
import assert from 'node:assert/strict'
import { bundleResourceReference, bundleResourceReferences } from '../src/utils/resourceBundleContext.js'

test('all nine generated resources retain their frozen versions for questions and opening', () => {
  const types = ['handout', 'mind_map', 'quiz', 'training_task', 'code_sandbox', 'video', 'deck', 'interactive_model', 'feynman']
  const items = types.map((type, i) => ({ type, state: 'succeeded', resource: {
    schema_version: 'f2.resource.v1', resource_id: `art-${i}`, version: { id: `generated-${i}` },
    content_ref: `artifact-version:generated-${i}`, current_version_id: `later-edit-${i}`,
  } }))
  assert.deepEqual(bundleResourceReferences(items), types.map((_,i) => ({ resourceId: `art-${i}`, resourceVersionId: `generated-${i}` })))
})

test('failed or missing versions do not become ready learning material', () => {
  const resource = { resource_id: 'art-a', version: { id: 'v1' } }
  assert.equal(bundleResourceReference({ state: 'failed', resource }), null)
  assert.equal(bundleResourceReference({ state: 'succeeded', resource: { resource_id: 'art-a' } }), null)
  assert.deepEqual(bundleResourceReferences([{ state: 'unavailable', resource }, { state: 'succeeded', resource }]), [{ resourceId: 'art-a', resourceVersionId: 'v1' }])
})
