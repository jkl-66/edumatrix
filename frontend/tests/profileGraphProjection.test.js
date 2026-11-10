import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import { projectCourseMasteryNode } from '../src/utils/courseGraphProjection.js'

const source = readFileSync(new URL('../src/views/StudentAnalysis.vue', import.meta.url), 'utf8')
const graphCode = source.slice(source.indexOf('const knowledgeGraph = computed('), source.indexOf('const knowledgeGraphNodes = computed('))

function project(current) {
  const old = { knowledgePointId: 'numpy', name: 'NumPy', nodeType: 'knowledge_point', masteryScore: 0, masteryStatus: 'weak', masteryEvidenceCount: 1 }
  return vm.runInNewContext(`${graphCode}; knowledgeGraph.value.nodes[0]`, {
    computed: fn => ({ value: fn() }), courseGraph: { value: { nodes: [old] } },
    legacyKnowledgeNodesById: { value: new Map(current ? [['numpy', current]] : []) },
    legacyKnowledgeGraph: { value: {} }, profileCourseId: { value: 'course' },
    projectCourseMasteryNode,
  })
}

test('current mastery, judgment and evidence stay together instead of mixing with initial diagnosis', () => {
  const node = project({ mastery: .67, masteryBand: 'developing', judgement: '仍需巩固', evidenceCount: 7 })
  assert.equal(node.mastery, .67)
  assert.equal(node.masteryBand, 'developing')
  assert.equal(node.judgement, '仍需巩固')
  assert.equal(node.evidenceCount, 7)
  assert.equal(project({ mastery: 0, masteryBand: 'weak', evidenceCount: 2 }).mastery, 0)
})

test('initial diagnosis remains usable before subsequent learning evidence exists', () => {
  assert.equal(project(null).mastery, 0)
  assert.equal(project(null).masteryBand, 'weak')
  assert.equal(project(null).evidenceCount, 1)
})

test('current unknown and conflict judgments do not revive an older diagnosis', () => {
  assert.equal(project({ mastery: null, masteryBand: 'unknown', evidenceCount: 0 }).mastery, null)
  assert.equal(project({ mastery: null, masteryBand: 'unknown', evidenceCount: 0 }).evidenceCount, 0)
  const conflict = projectCourseMasteryNode({ masteryScore: .9 }, { mastery: .4, masteryBand: 'conflict', evidenceCount: 2 })
  assert.equal(conflict.masteryBand, 'conflict')
  assert.equal(conflict.masteryScore, conflict.mastery)
  assert.equal(conflict.masteryEvidenceCount, conflict.evidenceCount)
})

test('radar and average follow current course graph; unknown is not a zero score', () => {
  const code = source.slice(source.indexOf('const conceptMastery = computed('), source.indexOf('// 数字孪生画像'))
  const run = nodes => vm.runInNewContext(`${code}; ({ concepts: conceptMastery.value, average: avgMastery.value })`, {
    computed: fn => ({ get value() { return fn() } }), knowledgeGraph: { value: { nodes } },
    analysis: { value: { raw_profile: { concept_mastery: { '另一门课': .99 } } } },
  })
  const empty = run([{ name: '新课程', mastery: null }])
  assert.equal(empty.concepts.length, 0)
  assert.equal(empty.average, null)
  const scored = run([{ name: '本课作答', mastery: 0 }, { name: '已练习', mastery: .6 }, { mastery: null }])
  assert.equal(scored.concepts.length, 2)
  assert.equal(scored.average, 30)
})

test('graph selection and view retain the mounted page while course changes replace it', () => {
  const app = readFileSync(new URL('../src/App.vue', import.meta.url), 'utf8')
  const code = app.slice(app.indexOf('function pageViewKey('), app.indexOf('\nwatch(', app.indexOf('function pageViewKey(')))
  const key = vm.runInNewContext(`${code}; pageViewKey`)
  const route = { path: '/profile/learning', query: { course_id: 'course-a' } }
  const focus = { ...route, query: { ...route.query, graph_view: 'structure', knowledge_point_id: 'kp-a' } }
  assert.equal(key(route), key(focus))
  assert.notEqual(key(focus), key({ ...focus, query: { ...focus.query, course_id: 'course-b' } }))
})

test('qualitative learning state stays descriptive and unknown never becomes zero percent', () => {
  const code = source.slice(source.indexOf('const currentLearningState = computed('), source.indexOf('const dimensions = computed('))
  const label = state => vm.runInNewContext(`${code}; currentStateLabel('frustration_index')`, {
    computed: fn => ({ get value() { return fn() } }),
    analysis: { value: { learning_state: { frustration_index: state } } },
    profileAwaitingEvidence: { value: false },
  })
  assert.equal(label({ value: null, description: '我不紧张，愿意尝试' }), '我不紧张，愿意尝试')
  assert.equal(label({ value: null }), '待了解')
  assert.equal(label({ value: 0 }), '0%')
})

test('available courses do not choose a subject for a learner with no current course', async () => {
  const code = source.slice(source.indexOf('async function loadGraphCourses()'), source.indexOf('async function changeGraphCourse()'))
  for (const selected of ['', 'removed-course', 'photography']) {
    const selectedGraphCourseId = { value: selected }
    await vm.runInNewContext(`${code}; loadGraphCourses()`, {
      listKnowledgeCourseShelf: async () => [{ id: 'machine-learning' }, { id: 'photography' }],
      selectableCourseOptions: value => value,
      selectedGraphCourseId, graphCourseOptions: { value: [] }, graphCourseStatus: { value: '' },
    })
    assert.equal(selectedGraphCourseId.value, selected === 'photography' ? selected : '')
  }
})
