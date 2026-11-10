import test from 'node:test'
import assert from 'node:assert/strict'
import { renderCourseDocument } from '../src/utils/courseDocumentRenderer.js'

test('legacy import instructions stay out of reading without moving source locations', () => {
  const source = '# 线性网络\n\n## 本章学习目标\n\n围绕 AI-KP-04 建立可解释、可实践、可检索的知识单元；正文保留上游章节结构并由系统按知识点切分。\n\n## 教材正文\n\n最小化预测值与真实值之间的误差。'
  const result = renderCourseDocument(source)
  assert.doesNotMatch(result.html, /AI-KP-04|本章学习目标|系统按知识点切分/)
  assert.ok(result.blocks.every(block => block.title !== '本章学习目标'))
  assert.match(result.html, /最小化预测值/)
  const start = source.indexOf('最小化预测值')
  assert.ok(result.html.includes(`data-source-start="${start}"`))
  assert.equal(result.plainText, source)
})

test('real learning objectives and teaching code remain visible', () => {
  const source = '## 本章学习目标\n\n理解梯度与损失函数。\n\n```python\ncode = "AI-KP-04"\n```'
  const result = renderCourseDocument(source)
  assert.match(result.html, /本章学习目标/)
  assert.match(result.html, /理解梯度/)
  assert.match(result.html, /AI-KP-04/)
})

test('scan markers disappear while table values, formula and source offsets remain', () => {
  const source = '--- Page 1 ---\n\n[OCR 第 1 页 · text]\n训练与验证误差\n\n[第 1 页图片内容]\n\n| 轮次 | 误差 |\n| --- | --- |\n| 2 | 0.30 |\n\n\\[\nL=\\frac{1}{n}\\sum(y-\\hat y)^2\n\\]'
  const result = renderCourseDocument(source)
  assert.doesNotMatch(result.html, /--- Page|OCR 第|页图片内容/)
  assert.match(result.html, /训练与验证误差/)
  assert.match(result.html, /0\.30/)
  assert.ok(result.blocks.some(block => block.kind === 'math'))
  assert.ok(result.html.includes(`data-source-start="${source.indexOf('0.30')}"`))
  assert.equal(result.plainText, source)
})
