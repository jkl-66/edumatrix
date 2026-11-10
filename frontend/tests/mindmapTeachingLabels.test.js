import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync, readdirSync } from 'node:fs'
import vm from 'node:vm'
const mermaidChunks = new URL('../node_modules/mermaid/dist/chunks/mermaid.core/', import.meta.url)
const mindmapModule = readdirSync(mermaidChunks).find(name => /^mindmap-definition-.*\.mjs$/.test(name))
const { diagram } = await import(new URL(mindmapModule, mermaidChunks))

const source = readFileSync(new URL('../src/components/IncrementalMarkdownRenderer.vue', import.meta.url), 'utf8')
const functions = source.slice(source.indexOf('async function renderMermaidDiagrams()'), source.indexOf('// 3. 单块渲染函数'))
const normalize = vm.runInNewContext(`${functions}; normalizeMindmapCode`)

function parse(code) {
  const nodes = []
  const parser = new diagram.parser.Parser()
  parser.yy = {
    getLogger: () => ({ trace() {}, info() {} }),
    addNode: (indent, id, label) => nodes.push({ indent, id, label }),
    decorateNode() {}, getType: () => 1, nodeType: { DEFAULT: 0 },
  }
  parser.parse(code)
  return nodes
}

test('NumPy indexing in teaching labels draws with its complete text and hierarchy', () => {
  const code = 'mindmap\n  root((NumPy数组与向量化))\n    选择\n      sensor[1] 第2条\n      sensor[:,1] 振动列\n      sensor[1,1] 0.9\n    机制\n      temp > 65 得掩码'
  assert.throws(() => parse(code))
  const nodes = parse(normalize(code))
  assert.equal(nodes.find(n => n.label === 'sensor[:,1] 振动列').indent, 6)
  assert.ok(nodes.some(n => n.label === 'sensor[1] 第2条'))
  assert.ok(nodes.some(n => n.label === 'sensor[1,1] 0.9'))
  assert.ok(nodes.some(n => n.id === 'root' && n.label === 'NumPy数组与向量化'))
})

test('valid node shapes, decorations and non-mindmap diagrams remain unchanged', () => {
  const code = 'mindmap\n  root((主题))\n    a["数组 [1,2]"]\n    ::icon(fa fa-book)\n    :::learning\n    b(检查)'
  assert.equal(normalize(code), code)
  assert.equal(normalize('flowchart LR\nA[数组] --> B[结果]'), 'flowchart LR\nA[数组] --> B[结果]')
})

test('a failed render stays inside its own block and leaves readable feedback', async () => {
  const el = { dataset: { code: encodeURIComponent('invalid diagram') }, textContent: '' }
  const state = {
    rootRef: { value: { querySelectorAll: () => [el], contains: item => item === el } },
    diagramId: 'test', diagramSequence: 0, console: { warn() {} },
    window: { mermaid: { render: async (_id, _code, container) => {
      assert.equal(container, el)
      el.textContent = 'Syntax error in text'
      throw new Error('invalid diagram')
    } } },
  }
  await vm.runInNewContext(`${functions}; renderMermaidDiagrams()`, state)
  assert.equal(el.dataset.processed, 'failed')
  assert.equal(el.textContent, '这张图暂时未能绘制，请结合下方讲解继续学习。')
})
