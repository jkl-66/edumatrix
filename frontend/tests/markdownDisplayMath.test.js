import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import vm from 'node:vm'

const source = fs.readFileSync(new URL('../src/components/IncrementalMarkdownRenderer.vue', import.meta.url), 'utf8')
const start = source.indexOf('const BlockType =')
const end = source.indexOf('// 2. 渲染逻辑', start)
const parse = vm.runInNewContext(`${source.slice(start, end)}\nparseSegments`)

test('live bracket and dollar display formulas become complete math blocks', () => {
  const blocks = parse('先计算：\\[\nG=1-\\sum_k p_k^2\n\\]再比较$$a+b$$。')
  assert.deepEqual(Array.from(blocks, item => item.type), ['text', 'math_block', 'text', 'math_block', 'text'])
  assert.ok(blocks[1].closed)
  assert.equal(blocks[1].content, '\\[\nG=1-\\sum_k p_k^2\n\\]')
  const pending = parse('\\[G=1-')
  assert.equal(pending[0].closed, false)
})

test('formula syntax inside teaching code remains literal code', () => {
  const inline = parse('正则符号 `\\[` 和 `$$` 保留原样。')
  assert.equal(inline.length, 1)
  assert.equal(inline[0].type, 'text')
  const fenced = parse('```python\npattern = r"\\["\n```')
  assert.equal(fenced[0].type, 'fenced_code')
  assert.equal(fenced[0].content, 'pattern = r"\\["\n')
})

const inlineSource = source.slice(source.indexOf('function escapeHtml('), source.indexOf('function renderTextBlock('))
const renderInline = vm.runInNewContext(`${inlineSource}\nrenderInlineMarkdown`, { window: {} })

test('plain teaching multiplication and powers survive across a complete question', () => {
  const question = '仍用 z=w*x+w、L=z²。w 同时出现在 w*x 与 +w 两项中。'
  assert.equal(renderInline(question), question)
  assert.equal(renderInline('x**2 与 y**2，(x+1)*w，2*3*4'), 'x**2 与 y**2，(x+1)*w，2*3*4')
})

test('literal formulas do not break intentional emphasis, code or math', () => {
  assert.equal(renderInline('先看**共享参数**，再看*两条路径*。'), '先看<strong>共享参数</strong>，再看<em>两条路径</em>。')
  assert.equal(renderInline('**计算 w*x** 与 `w*x`'), '<strong>计算 w*x</strong> 与 <code class="inc-inline-code">w*x</code>')
  assert.equal(renderInline('$w*x$'), '<span class="inc-math-inline">w*x</span>')
})

test('starred mathematical variables stay literal instead of spanning an emphasis region', () => {
  const question = '极小点为 w*=4，误差为 e_t=w_t−w*；从 w* 出发保持不变。'
  assert.equal(renderInline(question), question)
  assert.equal(renderInline('θ*=2，θ* 与 w_0* 都是标记。'), 'θ*=2，θ* 与 w_0* 都是标记。')
  assert.equal(renderInline('*w* 和 *斜体文字*，以及 *value*。'), '<em>w</em> 和 <em>斜体文字</em>，以及 <em>value</em>。')
})

const textSource = source.slice(source.indexOf('function renderTextBlock('), source.indexOf('function renderMathBlock('))
const renderText = vm.runInNewContext(`${inlineSource}\n${textSource}\nrenderTextBlock`, { window: {} })

test('table cells preserve absolute-value formulas, code pipes and escaped pipes', () => {
  const html = renderText('| 条件 | 结果 |\n|---|---|\n| \\(|1-18\\eta|<1\\) | $|w|$下降 |\n| `a|b` | x\\|y |')
  assert.equal((html.match(/<td>/g) || []).length, 4)
  assert.ok(html.includes('|1-18\\eta|&lt;1'))
  assert.ok(html.includes('<code class="inc-inline-code">a|b</code>'))
  assert.ok(html.includes('x|y'))
})

test('legitimate teaching terminology keeps its meaning', () => {
  assert.ok(renderText('确定性梯度下降与随机梯度下降的区别。').includes('确定性梯度下降'))
  assert.ok(!renderText('本地确定性演示').includes('本地确定性'))
})

test('assessed content preserves terminology, variable names and line breaks without allowing HTML', () => {
  const html = renderText('source_ref 是本题变量；学习画像依据和约束条件如下：\n<script>alert(1)</script>', true)
  assert.ok(html.includes('source_ref 是本题变量；学习画像依据和约束条件如下：<br>'))
  assert.ok(html.includes('&lt;script&gt;alert(1)&lt;/script&gt;'))
  assert.ok(!html.includes('<script>'))
  assert.ok(renderText('**Git commit** 与 `source_ref`', true).includes('<strong>Git commit</strong>'))
})
