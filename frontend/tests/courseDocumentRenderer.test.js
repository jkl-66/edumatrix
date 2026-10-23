import assert from 'node:assert/strict'
import { readFileSync, readdirSync } from 'node:fs'
import test from 'node:test'
import { cacheKey, readCachedCourseDocument, renderCourseDocument } from '../src/utils/courseDocumentRenderer.js'

function assertSourceText(result, text, expectedStart = result.plainText.indexOf(text)) {
  assert.ok(expectedStart >= 0)
  assert.ok(result.html.includes(`data-source-start="${expectedStart}" data-source-end="${expectedStart + text.length}">${text}</span>`), `Missing original source range for ${text}`)
}

test('hides escaped source metadata without rewriting the document or following text offsets', () => {
  const source = '# 课程\n\n> 课程：机器学习  \\n> 上游来源：教材  \\n> 转换说明：未执行\n\n正文保持位置\n\n```text\n\\n> 上游来源：代码示例\n<a name="code"></a>\n```'
  const result = renderCourseDocument(source)
  assert.equal(result.plainText, source)
  assert.doesNotMatch(result.html, /课程：机器学习|转换说明：未执行/)
  assert.match(result.html, /\\n&gt; 上游来源：代码示例/)
  assert.match(result.html, /&lt;a name=&quot;code&quot;&gt;&lt;\/a&gt;/)
  assertSourceText(result, '正文保持位置')
})

test('keeps invisible anchors and local links usable without exposing HTML markers', () => {
  const result = renderCourseDocument('<a name="1"></a>\n\n[返回小节](#1)\n\n<a href="https://example.com/lesson" onclick="bad()">学习资料</a>')
  assert.match(result.html, /id="course-anchor-1" aria-hidden="true"/)
  assert.doesNotMatch(result.html, /&lt;a|onclick|lesson-block--explanation[^]*?aria-hidden[^]*?<\/p>/)
  assert.match(result.html, /href="#course-anchor-1">/)
  assert.match(result.html, /href="https:\/\/example.com\/lesson" target="_blank" rel="noopener noreferrer"/)
  assertSourceText(result, '返回小节')
  assertSourceText(result, '学习资料')
})

test('presents upstream notebook badges as readable links with their original text range', () => {
  const source = '<table align="left">\n  <td>\n    <a href="https://colab.research.google.com/example" target="_parent"><img src="badge.svg" alt="Open In Colab"/></a>\n  </td>\n</table>'
  const result = renderCourseDocument(source, { query: 'Open In Colab' })
  assert.doesNotMatch(result.html, /&lt;\/?(?:table|td|img)|_parent/)
  assert.match(result.html, /href="https:\/\/colab.research.google.com\/example"/)
  assert.match(result.html, /course-search-hit--current/)
  assertSourceText(result, 'Open In Colab')
})

test('repeated table cells retain their own source offsets after earlier document blocks', () => {
  const source = '# 前文\n\n普通段落\n\n| 名称 | 数值 |\n| --- | --- |\n| 相同 | 相同 |\n| 相同 | 不同 |'
  const result = renderCourseDocument(source)
  const positions = [...source.matchAll(/相同/g)].map((match) => match.index)
  for (const start of positions) assertSourceText(result, '相同', start)
  assertSourceText(result, '名称')
  assertSourceText(result, '不同')
})

test('all current foundations chapters render without escaped metadata or visible empty anchors', () => {
  const directory = new URL('../../data/curated/machine_learning_foundations_v1/chapters/', import.meta.url)
  const chapters = readdirSync(directory).filter((name) => name.endsWith('.md'))
  assert.equal(chapters.length, 12)
  for (const name of chapters) {
    const source = readFileSync(new URL(name, directory), 'utf8')
    const result = renderCourseDocument(source)
    assert.equal(result.plainText, source.replace(/\r\n?/g, '\n'), name)
    assert.doesNotMatch(result.html, /\\n&gt; 上游来源|&lt;a name=|&lt;table align=/, name)
  }
})

test('renderer changes invalidate earlier document caches', () => {
  const priorWindow = globalThis.window
  const oldKey = 'edumatrix.course-document.preview.doc.version.course-document-renderer-v3'
  globalThis.window = { localStorage: { getItem: () => JSON.stringify({ rendererVersion: 'course-document-renderer-v3', html: 'stale preview' }) } }
  try {
    assert.notEqual(cacheKey('doc', 'version'), oldKey)
    assert.equal(readCachedCourseDocument(oldKey), null)
  } finally {
    globalThis.window = priorWindow
  }
})

test('allowed presentation tags render in prose while inline HTML examples stay literal', () => {
  const result = renderCourseDocument('H<sub>2</sub>O\n\n`<sub>2</sub>` <script>bad()</script>')
  assert.match(result.html, /H<\/span><sub>/)
  assert.match(result.html, /<\/sub>/)
  assert.match(result.html, /&lt;sub&gt;2&lt;\/sub&gt;/)
  assert.doesNotMatch(result.html, /<script>/)
})
