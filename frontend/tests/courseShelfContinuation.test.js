import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'

const source = readFileSync(new URL('../src/components/KnowledgeCourseShelf.vue', import.meta.url), 'utf8')
const selection = source.slice(source.indexOf('const continuingCourse ='), source.indexOf('function apiErrorMessage'))

function target(courseId, shelf) {
  return vm.runInNewContext(`${selection}; ({ continuing: continuingCourse.value?.id, target: firstShelfCourse.value?.id })`, {
    courseContext: { contextRef: { courseId } }, shelfCourses: { value: shelf },
    computed: read => ({ get value() { return read() } }),
  })
}

test('continue learning opens the current course even when it is not first on the shelf', () => {
  const result = target('current', [{ id: 'first' }, { id: 'current' }])
  assert.equal(result.continuing, 'current')
  assert.equal(result.target, 'current')
})

test('a missing or unavailable course cannot masquerade as a resumed course', () => {
  for (const id of ['', 'no-longer-accessible']) {
    const result = target(id, [{ id: 'available' }])
    assert.equal(result.continuing, undefined)
    assert.equal(result.target, 'available')
  }
  assert.equal(target('old-account-course', []).target, undefined)
})
