import test from 'node:test'
import assert from 'node:assert/strict'
import { arrangeCourseMaterials, readMaterialBrowser, saveMaterialBrowser } from '../src/utils/courseMaterialBrowser.js'

const items = [
  { id: 'a', title: '线性神经网络', chapters: [{ title: '回归与损失函数' }] },
  { id: 'b', title: '卷积网络', chapters: [{ title: '图像与卷积核' }] },
  { id: 'c', title: '优化算法', chapters: [{ title: '梯度下降与学习率' }] },
]

test('material selection and pins are isolated by account and course', () => {
  const map = new Map()
  const storage = { getItem: key => map.get(key), setItem: (key, value) => map.set(key, value) }
  const state = { selected: 'b', type: '文本', query: '卷积', sort: 'recent', pinned: ['b'], recent: ['b', 'a'] }
  saveMaterialBrowser(storage, 'student-one', 'course-one', state)
  assert.deepEqual(readMaterialBrowser(storage, 'student-one', 'course-one'), state)
  assert.deepEqual(readMaterialBrowser(storage, 'student-two', 'course-one'), {})
  assert.deepEqual(readMaterialBrowser(storage, 'student-one', 'course-two'), {})
})

test('material filtering searches chapter titles and keeps empty results empty', () => {
  assert.deepEqual(arrangeCourseMaterials(items, { query: '梯度 学习率' }).map(x => x.id), ['c'])
  assert.deepEqual(arrangeCourseMaterials(items, { query: '未收录的主题' }), [])
})

test('pin and recent sorting do not mutate curriculum order', () => {
  assert.deepEqual(arrangeCourseMaterials(items, { pinned: ['b'], recent: ['c','a'], sort: 'recent' }).map(x => x.id), ['b','c','a'])
  assert.deepEqual(items.map(x => x.id), ['a','b','c'])
})
