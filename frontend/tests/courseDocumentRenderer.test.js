import assert from 'node:assert/strict'
import { readFileSync, readdirSync } from 'node:fs'
import test from 'node:test'
import { cacheKey, readCachedCourseDocument, renderCourseDocument, renderCourseMath, documentSearchMatches } from '../src/utils/courseDocumentRenderer.js'

function assertSourceText(result, text, expectedStart = result.plainText.indexOf(text)) {
  assert.ok(expectedStart >= 0)
  assert.ok(result.html.includes(`data-source-start="${expectedStart}" data-source-end="${expectedStart + text.length}">${text}</span>`), `Missing original source range for ${text}`)
}

test('selected excerpts reuse document reference labels and keep literal teaching code intact', () => {
  const original = '# 模型选择\n:label:`sec_model_selection`\n\n正文。'
  const quote = '请看 :numref:`sec_model_selection`，以及 :cite:`Bishop.2006`。\n\n```python\nx = ":numref:`sec_model_selection`"\n```'
  const result = renderCourseDocument(quote, { referenceDocument: original })
  assert.ok(result.readingText.startsWith('请看 模型选择，以及 （Bishop，2006）。'))
  assert.ok(result.readingText.includes('x = ":numref:`sec_model_selection`"'))
  assert.equal(result.plainText, quote)
  assert.equal(renderCourseDocument(':numref:`missing`', { referenceDocument: original }).readingText, '原文相关章节')
  assert.equal(renderCourseDocument('只选普通文字与\\eta').readingText, '只选普通文字与\\eta')
})

test('multiline excerpts share publication-marker hiding without erasing teaching code', () => {
  const quote = '# 条件\n:label:`sec_conditions`\n\n:begin_tab:`pytorch`\n\n教材正文。\n\n:end_tab:\n\n```toc\nother-chapter\n```\n\n```python\nmarker = ":label:`example`"\n```'
  const result = renderCourseDocument(quote)
  assert.ok(result.readingText.includes('PyTorch'))
  assert.ok(result.readingText.includes('教材正文。'))
  assert.ok(result.readingText.includes('marker = ":label:`example`"'))
  assert.ok(!result.readingText.includes('sec_conditions'))
  assert.ok(!result.readingText.includes(':begin_tab:'))
  assert.ok(!result.readingText.includes(':end_tab:'))
  assert.ok(!result.readingText.includes('other-chapter'))
  assert.equal(result.plainText, quote)
})

test('search includes matches beyond 500 and highlights the final occurrence without shifting the source', () => {
  const source = '𝒘\n\n' + Array.from({length: 1203}, (_, index) => `第${index}段 learning`).join('\n\n')
  const positions = documentSearchMatches(source, 'LEARNING')
  assert.equal(positions.length, 1203)
  assert.equal(positions.at(-1), source.lastIndexOf('learning'))
  const result = renderCourseDocument(source, {query:'LEARNING',currentMatch:1202})
  assert.equal(result.matchCount, 1203)
  const start = Array.from(source.slice(0, positions.at(-1))).length
  assert.ok(result.html.includes(`course-search-hit--current" data-source-start="${start}" data-source-end="${start + 8}">learning`))
})

test('literal search preserves original offsets after case-expanding characters and treats regex symbols as text', () => {
  const source = 'İ前缀 𝒘 *[x]+ 末尾 ABC'
  assert.deepEqual(documentSearchMatches(source, 'abc'), [source.indexOf('ABC')])
  assert.deepEqual(documentSearchMatches(source, '*[x]+'), [source.indexOf('*[x]+')])
  assert.deepEqual(documentSearchMatches(source, ''), [])
})

test('astral math letters and normalized newlines keep Python source ranges for prose, code and search', () => {
  const source = '# 𝒘与😀\r\n\r\n𝒘在前，目标句在后。\r\n\r\n```python\r\nvalue = "𝒘"\r\n```\r\n\r\n目标句'
  const result = renderCourseDocument(source, { query: '目标句', currentMatch: 1 })
  const points = Array.from(source)
  const expected = Array.from(source.slice(0, source.lastIndexOf('目标句'))).length
  assert.match(result.html, new RegExp(`course-search-hit--current" data-source-start="${expected}" data-source-end="${expected + 3}"`))
  for (const match of result.html.matchAll(/data-source-start="(\d+)" data-source-end="(\d+)"/g)) {
    assert.ok(+match[1] <= +match[2] && +match[2] <= points.length)
  }
  assert.equal(points.slice(result.blocks.at(-1).start, result.blocks.at(-1).end).join(''), '目标句')
  const start = Array.from(source.slice(0, source.indexOf('𝒘在前'))).length
  assert.ok(result.html.includes(`data-source-start="${start}" data-source-end="${start + 4}">𝒘在前，`))
})

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

test('textbook attribute fences preserve Python code and the following prose as separate blocks', () => {
  const source = '# 练习\n\n```{.python .input}\nvalue = 1\nprint(value)\n```\n\n这段解释属于正文。\n\n~~~python\nvalue += 1\n~~~'
  const result = renderCourseDocument(source)
  assert.equal((result.html.match(/class="course-code"/g) || []).length, 2)
  assert.match(result.html, /<span>python<\/span>/)
  assert.doesNotMatch(result.html, /\{\.python \.input\}|~~~python/)
  assertSourceText(result, 'value = 1\nprint(value)')
  assertSourceText(result, '这段解释属于正文。')
  const code = result.html.match(/<code>([\s\S]*?)<\/code>/)[1]
  assert.doesNotMatch(code, /这段解释/)
  assert.equal(result.plainText, source)
})

test('web textbook inline and display TeX delimiters render with original source positions', () => {
  const source = String.raw`概率为\(\frac{1}{2}\)。

\[y=x^2\]

\[
E=mc^2
\]`
  const result = renderCourseDocument(source)
  assert.match(result.html, /class="course-inline-math" data-math="\\frac\{1\}\{2\}"/)
  assert.equal((result.html.match(/data-math-block=/g)||[]).length, 2)
  assertSourceText(result, String.raw`\frac{1}{2}`)
  assertSourceText(result, 'y=x^2')
  assertSourceText(result, 'E=mc^2')
  assert.equal(result.plainText, source)
})

test('allowed presentation tags render in prose while inline HTML examples stay literal', () => {
  const result = renderCourseDocument('H<sub>2</sub>O\n\n`<sub>2</sub>` <script>bad()</script>')
  assert.match(result.html, /H<\/span><sub>/)
  assert.match(result.html, /<\/sub>/)
  assert.match(result.html, /&lt;sub&gt;2&lt;\/sub&gt;/)
  assert.doesNotMatch(result.html, /<script>/)
})

test('a retrieval excerpt ending inside display math still renders its available source', () => {
  for (const source of ['说明\n\n$$', '说明\n\n$$\np(y|x)=p(y)', '说明\n\n$$p(y|x)=p(y)']) {
    const result = renderCourseDocument(source)
    assert.equal(result.plainText, source)
    assert.match(result.html, /说明/)
    if (source.includes('p(y|x)')) assertSourceText(result, 'p(y|x)=p(y)')
    assert.doesNotMatch(result.html, /undefined|NaN/)
  }
})


test('search highlights teaching code and styled text without altering copied code or source ranges', () => {
  const source = '**accuracy** and `accuracy`\n\n```python\naccuracy = 8 / 10\nprint(f"accuracy: {accuracy:.0%}")\n```'
  const result = renderCourseDocument(source, {query:'accuracy',currentMatch:3})
  assert.equal(result.matchCount,5)
  assert.equal((result.html.match(/class="course-search-hit(?: course-search-hit--current)?"/g)||[]).length,5)
  assert.equal((result.html.match(/course-search-hit--current/g)||[]).length,1)
  const code = result.html.match(/<code>([\s\S]*?)<\/code>/)[1].replace(/<[^>]+>/g,'').replace(/&quot;/g,'"')
  assert.equal(code,'accuracy = 8 / 10\nprint(f"accuracy: {accuracy:.0%}")')
  assert.equal(result.plainText,source)
})

test('publication references use actual local headings and formulas while preserving the original directive range', () => {
  const source = '# 模型选择\n:label:`sec_selection`\n\n𝒘请参见:numref:`sec_selection`和:eqref:`eq_loss`。\n\n$$\nL=x^2\n$$\n:eqlabel:`eq_loss`\n\n![损失曲线](https://example.com/loss.svg)\n:width:`400px`\n:label:`fig_loss`\n\n见:numref:`fig_loss`。'
  const result = renderCourseDocument(source)
  assert.equal(result.plainText, source)
  assert.match(result.html, /href="#course-anchor-sec_selection"><span[^>]+>模型选择<\/span><\/a>/)
  assert.match(result.html, /href="#course-anchor-eq_loss"><span[^>]+>公式<\/span><\/a>/)
  assert.match(result.html, /href="#course-anchor-fig_loss"><span[^>]+>损失曲线<\/span><\/a>/)
  assert.match(result.html, /id="course-anchor-eq_loss" aria-hidden="true"><\/span><section[^>]+lesson-block--formula/)
  assert.doesNotMatch(result.html, /:numref:|:eqref:|:eqlabel:|:label:|:width:|400px/)
  const token = ':numref:`sec_selection`'
  const start = Array.from(source.slice(0, source.indexOf(token))).length
  assert.ok(result.html.includes(`data-source-start="${start}" data-source-end="${start + token.length}" data-source-atomic="true">模型选择`))
  const prose = '𝒘请参见'
  const proseStart = Array.from(source.slice(0, source.indexOf(prose))).length
  assert.ok(result.html.includes(`data-source-start="${proseStart}" data-source-end="${proseStart + Array.from(prose).length}">${prose}</span>`))
})

test('unresolved publication references retain honest original-source cues and citations without invented destinations', () => {
  const source = '请参见:numref:`sec_elsewhere`、:eqref:`eq_elsewhere`及:numref:`fig_elsewhere`。\n\n已有研究:cite:`Bishop.1995,Srivastava.Hinton.Krizhevsky.ea.2014`。\n\n```python\ntext = ":numref:`sec_elsewhere`"\n# :label:`a_teaching_example`\n```'
  const result = renderCourseDocument(source)
  assert.match(result.html, /原文相关章节/)
  assert.match(result.html, /原文公式/)
  assert.match(result.html, /原文图示/)
  assert.match(result.html, /Bishop，1995；Srivastava等，2014/)
  assert.doesNotMatch(result.html, /href="#course-anchor-(?:sec|eq|fig)_elsewhere"/)
  assert.match(result.html, /text = &quot;:numref:`sec_elsewhere`&quot;/)
  assert.match(result.html, /# :label:`a_teaching_example`/)
  assert.equal(result.plainText, source)
})

test('textbook navigation directives are not code exercises and framework names remain understandable', () => {
  const source = '# 多层感知机\n\n```toc\n:maxdepth: 2\n\nmlp\nweight-decay\n```\n\n:begin_tab:`pytorch, tensorflow`\n\n```python\nprint("loss")\n```\n\n:end_tab:\n\n这仍是完整的教学解释。'
  const result = renderCourseDocument(source)
  assert.doesNotMatch(result.html, /maxdepth|weight-decay|:begin_tab:|:end_tab:/)
  assert.match(result.html, /PyTorch \/ TensorFlow/)
  assert.equal((result.html.match(/class="course-code"/g) || []).length, 1)
  assert.equal(result.blocks.filter(block => block.kind === 'code').length, 1)
  assertSourceText(result, '这仍是完整的教学解释。')
  assert.equal(result.plainText, source)
})

test('duplicate textbook labels never link to an arbitrary chapter', () => {
  const source = '# 第一章\n:label:`sec_shared`\n\n# 第二章\n:label:`sec_shared`\n\n参见:numref:`sec_shared`。'
  const result = renderCourseDocument(source)
  assert.match(result.html, /原文相关章节/)
  assert.doesNotMatch(result.html, /(?:href="#|id=")course-anchor-sec_shared/)
  assert.equal(result.plainText, source)
})

test('typeset formulas keep the original expression as one selectable source span', () => {
  const element = { dataset: { math: 'x^2 + y^2' }, textContent: 'x^2 + y^2',
    classList: { contains: () => false },
    querySelector: selector => selector.startsWith('[data-source')
      ? { dataset: { sourceStart: '9', sourceEnd: '18' } } : null }
  renderCourseMath({ querySelectorAll: () => [element] }, { renderToString: () => '<span>typeset formula</span>' })
  assert.equal(element.dataset.sourceStart, '9')
  assert.equal(element.dataset.sourceEnd, '18')
  assert.equal(element.dataset.sourceAtomic, 'true')
  assert.equal(element.dataset.rendered, 'true')
})

test('ordinary Chinese heading links resolve in raw and percent-encoded form', () => {
  const source = '[开始](#快速开始) [编码链接](#%E5%BF%AB%E9%80%9F%E5%BC%80%E5%A7%8B)\n\n## 快速开始\n教学正文。'
  const result = renderCourseDocument(source)
  const target = `course-anchor-${encodeURIComponent('快速开始')}`
  assert.equal((result.html.match(new RegExp(`href="#${target}"`, 'g')) || []).length, 2)
  assert.ok(result.html.includes(`id="${target}"`))
  assert.equal(result.plainText, source)
})

test('full-width link closing punctuation does not consume author citations and nested URL parentheses stay intact', () => {
  const source = '请看[文章](https://example.com/momentum/）（作者是 :cite:`Goh.2017`)，以及[定义](https://example.com/wiki/Function_(math))。'
  const result = renderCourseDocument(source)
  assert.match(result.html, /href="https:\/\/example.com\/momentum\/"/)
  assert.match(result.html, /href="https:\/\/example.com\/wiki\/Function_\(math\)"/)
  assert.match(result.html, /Goh，2017/)
  assert.doesNotMatch(result.html, /:cite:/)
  assert.equal(result.plainText, source)
})

test('each quotation line maps to its actual source after stripping presentation prefixes', () => {
  const source = '> 学习勘误说明。\n> 𝒘请查看`model.fit`。\n\n> [!NOTE] 学习要点\n> 参数保持不变。'
  const result = renderCourseDocument(source)
  for (const text of ['学习勘误说明。', '𝒘请查看', 'model.fit', '学习要点', '参数保持不变。']) {
    const start = Array.from(source.slice(0, source.indexOf(text))).length
    const end = start + Array.from(text).length
    assert.ok(result.html.includes(`data-source-start="${start}" data-source-end="${end}">${text}</span>`), text)
  }
  assert.doesNotMatch(result.html, /\[!NOTE\]/)
  assert.equal(result.plainText, source)
})

test('a wrapped comparison keeps its greater-than sign instead of becoming a quotation', () => {
  const source = '判断工作年限\n> 3 年是否满足条件。\n\n> 这里才是独立的学习提示。'
  const result = renderCourseDocument(source)
  assertSourceText(result, '判断工作年限')
  assert.ok(result.html.includes('&gt; 3 年是否满足条件。'))
  assert.equal(result.blocks.filter(block => block.kind === 'quote').length, 1)
  assert.equal(result.plainText, source)
})

test('unresolved repository-relative links retain their text without a fake jump-to-top button', () => {
  const source = '[README](../README.md) 与 [原网页](https://example.com/readme)。'
  const result = renderCourseDocument(source)
  assertSourceText(result, 'README')
  assert.doesNotMatch(result.html, /href="#"/)
  assert.match(result.html, /href="https:\/\/example.com\/readme"/)
  assert.equal(result.plainText, source)
})
