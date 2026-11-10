<script setup>
import { userMessage } from '../services/errorTranslator.js'
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as d3 from 'd3'
import IncrementalMarkdownRenderer from './IncrementalMarkdownRenderer.vue'

const props = defineProps({
  code: { type: String, default: '' },
  nodes: { type: Array, default: () => [] },
  rootNodeId: { type: String, default: '' },
  selectedNodeId: { type: String, default: '' },
  height: { type: Number, default: 560 },
  showToolbar: { type: Boolean, default: true },
})

const emit = defineEmits(['select', 'view-change', 'render-error'])
const svgRef = ref(null)
const fullscreenSvgRef = ref(null)
const containerRef = ref(null)
const isFullscreen = ref(false)
const rendering = ref(true)
const renderError = ref('')
// Flowcharts describe explicit edges, not indentation. Use the shared diagram
// renderer so cross-links and teaching labels remain intact.
const flowchartCode = computed(() => {
  if (props.nodes.length) return ''
  const code = props.code.trim().replace(/^```mermaid\s*\n?/i, '').replace(/\n?```$/, '')
  return /^(?:graph|flowchart)\s+(?:TD|TB|BT|RL|LR)\b/.test(code) ? `\`\`\`mermaid\n${code}\n\`\`\`` : ''
})

let svg = null
let group = null
let zoom = null
let root = null
let layout = null
let resizeObserver = null
let currentTransform = d3.zoomIdentity
const collapsedNodeIds = new Set()
const NODE_SIZE = Object.freeze({
  rootHeight: 46,
  regularHeight: 40,
  minWidth: 142,
  maxWidth: 344,
  horizontalGap: 380,
  verticalGap: 96,
  toggleRadius: 11,
})

function cleanLegacyLabel(value) {
  let text = String(value || '').trim().replace(/^[-*+]\s+/, '').replace(/\*\*/g, '').replace(/`/g, '')
  const pairs = [['((', '))'], ['{{', '}}'], ['(', ')'], ['[', ']']]
  for (const [opening, closing] of pairs) {
    const escapedOpen = opening.replace(/[|\\{}()[\]^$+*?.]/g, '\\$&')
    const escapedClose = closing.replace(/[|\\{}()[\]^$+*?.]/g, '\\$&')
    const match = text.match(new RegExp(`^[a-zA-Z0-9_-]+\\s*${escapedOpen}\\s*(.*?)\\s*${escapedClose}$`))
    if (match) {
      text = match[1].trim()
      break
    }
  }
  return text.replace(/^"|"$/g, '').replace(/&quot;/g, '"').replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>')
}

// Compatibility path retained from the old system for Markdown/Mermaid resources.
function legacyTree(code) {
  const roots = []
  const stack = []
  let index = 0
  for (const line of String(code || '').split(/\r?\n/)) {
    const trimmed = line.trim()
    if (!trimmed || trimmed === 'mindmap' || trimmed.startsWith('%%')) continue
    const indent = line.match(/^(\s*)/)?.[0].length || 0
    const node = {
      nodeId: `legacy-${index += 1}`,
      label: cleanLegacyLabel(trimmed),
      summary: '',
      relation: stack.length ? '层级' : '主题',
      depth: stack.length,
      masteryBand: 'unknown',
      sourceRefs: [],
      linkedResourceIds: [],
      children: [],
    }
    while (stack.length && stack.at(-1).indent >= indent) stack.pop()
    if (stack.length) stack.at(-1).node.children.push(node)
    else roots.push(node)
    stack.push({ indent, node })
  }
  if (roots.length === 1) return roots[0]
  if (roots.length > 1) return { nodeId: 'legacy-root', label: '概念思维导图', relation: '主题', depth: 0, masteryBand: 'unknown', children: roots }
  return null
}

function structuredTree() {
  if (!props.nodes.length) return legacyTree(props.code)
  const byId = new Map(props.nodes.map(item => [item.nodeId, { ...item, label: item.label || item.name || item.nodeId, children: [] }]))
  for (const item of byId.values()) {
    if (item.parentNodeId) byId.get(item.parentNodeId)?.children.push(item)
  }
  return byId.get(props.rootNodeId) || [...byId.values()].find(item => !item.parentNodeId) || null
}

function bandLabel(value) {
  return ({ unknown: '尚无证据', needs_work: '需要巩固', developing: '正在建立', secure: '较为稳固' })[value] || '尚无证据'
}

function colors(datum) {
  const selected = datum.data.nodeId === props.selectedNodeId
  if (selected) return { fill: 'var(--color-success)', stroke: 'var(--color-success)', text: '#ffffff', line: 'var(--color-success)' }
  if (datum.depth === 0) return { fill: 'var(--color-accent-soft)', stroke: 'var(--color-accent)', text: 'var(--color-text)', line: 'var(--color-accent)' }
  if (datum.depth === 1) return { fill: 'var(--color-success-soft)', stroke: 'var(--color-success)', text: 'var(--color-text)', line: 'var(--color-success)' }
  return { fill: 'var(--color-reading-paper)', stroke: 'var(--color-border-strong)', text: 'var(--color-text)', line: 'var(--color-text-muted)' }
}

function escapeHtml(value) {
  return String(value || '')
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;')
}

// The old component rendered formulas in foreignObject. Keep that capability,
// but escape learner/model text before inserting it into HTML.
function renderNodeHtml(value) {
  const raw = String(value || '')
  if (raw.includes('$') && typeof window !== 'undefined' && window.katex) {
    const pattern = /\$([^$]+)\$/g
    let result = ''
    let cursor = 0
    let match
    while ((match = pattern.exec(raw))) {
      result += escapeHtml(raw.slice(cursor, match.index))
      try {
        result += window.katex.renderToString(match[1], { throwOnError: false, displayMode: false })
      } catch (_error) {
        result += escapeHtml(match[0])
      }
      cursor = match.index + match[0].length
    }
    return result + escapeHtml(raw.slice(cursor))
  }
  return escapeHtml(raw)
}

function visibleChildren(node) {
  return collapsedNodeIds.has(node.nodeId) ? null : node.children
}

function emitViewChange() {
  emit('view-change', {
    transform: { x: currentTransform.x, y: currentTransform.y, k: currentTransform.k },
    collapsedNodeIds: [...collapsedNodeIds],
  })
}

function labelWidth(value) {
  const text = String(value || '')
  const width = [...text].reduce((sum, char) => sum + (char.charCodeAt(0) > 127 ? 11 : 6.5), 0)
  const formulaPadding = /[$_^{}\\]/.test(text) ? 52 : 28
  return Math.max(NODE_SIZE.minWidth, Math.min(NODE_SIZE.maxWidth, width + formulaPadding))
}

function draw(source = root) {
  if (!root || !group || !layout) return
  const tree = layout(root)
  const nodes = tree.descendants()
  const links = tree.links()
  nodes.forEach((item) => {
    item.y = item.depth * NODE_SIZE.horizontalGap + 80
    item.halfWidth = labelWidth(item.data.label) / 2
    item.nodeHeight = item.depth === 0 ? NODE_SIZE.rootHeight : NODE_SIZE.regularHeight
  })

  const linkGenerator = d3.linkHorizontal().x(point => point.y).y(point => point.x)
  group.selectAll('path.mindmap-link')
    .data(links, link => link.target.data.nodeId)
    .join(
      enter => enter.insert('path', 'g').attr('class', 'mindmap-link').attr('d', () => {
        const point = { x: source.x0 || source.x || 0, y: source.y0 || source.y || 0 }
        return linkGenerator({ source: point, target: point })
      }),
      update => update,
      exit => exit.remove(),
    )
    .attr('fill', 'none')
    .attr('stroke', link => colors(link.source).line)
    .attr('stroke-opacity', link => link.source.depth === 0 ? 0.85 : link.source.depth === 1 ? 0.72 : 0.55)
    .attr('stroke-width', link => link.source.depth === 0 ? 2.2 : link.source.depth === 1 ? 1.8 : 1.35)
    .attr('stroke-dasharray', link => ['关联', '相关', '辅助'].includes(link.target.data.relation) ? '5 5' : null)
    .style('stroke-linecap', 'round')
    .attr('d', link => linkGenerator({
      source: { x: link.source.x, y: link.source.y + link.source.halfWidth },
      target: { x: link.target.x, y: link.target.y - link.target.halfWidth },
    }))

  const node = group.selectAll('g.mindmap-node')
    .data(nodes, item => item.data.nodeId)
    .join(
      enter => {
        const next = enter.append('g').attr('class', 'mindmap-node').attr('tabindex', 0).attr('role', 'button')
        next.append('rect').attr('class', 'mindmap-node__rect').attr('rx', 8).attr('ry', 8)
        next.append('foreignObject').attr('class', 'mindmap-node__fo').style('overflow', 'visible')
          .append('xhtml:div').attr('class', 'mindmap-node-content')
        next.append('circle').attr('class', 'mindmap-node__toggle').attr('r', NODE_SIZE.toggleRadius)
        next.append('text').attr('class', 'mindmap-node__toggle-label').attr('text-anchor', 'middle').attr('aria-hidden', 'true')
        next.append('title')
        return next
      },
      update => update,
      exit => exit.remove(),
    )
    .attr('transform', item => `translate(${item.y},${item.x})`)
    .attr('aria-label', item => `${item.data.label}，${bandLabel(item.data.masteryBand)}`)
    .on('click', (event, item) => {
      if (event.target.classList.contains('mindmap-node__toggle') || event.target.classList.contains('mindmap-node__toggle-label')) return
      emit('select', item.data)
    })
    .on('keydown', (event, item) => {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault()
        emit('select', item.data)
      }
    })

  node.select('.mindmap-node__rect')
    .attr('x', item => -item.halfWidth)
    .attr('y', item => -item.nodeHeight / 2)
    .attr('width', item => item.halfWidth * 2)
    .attr('height', item => item.nodeHeight)
    .attr('fill', item => colors(item).fill)
    .attr('stroke', item => colors(item).stroke)
    .attr('stroke-width', item => item.data.nodeId === props.selectedNodeId ? 2.6 : 1.5)

  node.select('.mindmap-node__fo')
    .attr('x', item => -item.halfWidth + 8)
    .attr('y', item => -item.nodeHeight / 2 + 4)
    .attr('width', item => Math.max(1, item.halfWidth * 2 - 16))
    .attr('height', item => Math.max(1, item.nodeHeight - 8))
  node.select('.mindmap-node-content')
    .html(item => renderNodeHtml(item.data.label))
    .style('color', item => colors(item).text)
    .style('font-size', item => item.depth === 0 ? '16px' : '15px')
    .style('font-weight', item => item.depth === 0 ? '700' : '600')

  node.select('.mindmap-node__toggle')
    .attr('cx', item => item.halfWidth)
    .attr('cy', 0)
    .attr('display', item => item.data.children?.length ? null : 'none')
    .attr('fill', '#ffffff')
    .attr('stroke', item => colors(item).stroke)
    .on('click', (event, item) => {
      event.stopPropagation()
      if (collapsedNodeIds.has(item.data.nodeId)) collapsedNodeIds.delete(item.data.nodeId)
      else collapsedNodeIds.add(item.data.nodeId)
      root = d3.hierarchy(structuredTree(), visibleChildren)
      root.x0 = item.x
      root.y0 = item.y
      draw(root)
      emitViewChange()
    })
  node.select('.mindmap-node__toggle-label')
    .attr('x', item => item.halfWidth)
    .attr('y', 5)
    .attr('display', item => item.data.children?.length ? null : 'none')
    .attr('fill', item => colors(item).text)
    .text(item => collapsedNodeIds.has(item.data.nodeId) ? '+' : '−')
  node.select('title').text(item => `${item.data.label}${item.data.summary ? `\n${item.data.summary}` : ''}`)

  nodes.forEach((item) => {
    item.x0 = item.x
    item.y0 = item.y
  })
}

function activeSvgElement() {
  return isFullscreen.value ? fullscreenSvgRef.value : svgRef.value
}

function center({ animate = true } = {}) {
  const element = activeSvgElement()
  if (!element || !svg || !zoom || !root || !group) return
  const bounds = group.node()?.getBBox()
  if (!bounds || !Number.isFinite(bounds.width) || !bounds.width) return
  const width = element.clientWidth || 900
  const height = element.clientHeight || props.height
  const scale = Math.max(0.15, Math.min(1.2, 0.88 / Math.max(bounds.width / width, bounds.height / height)))
  const transform = d3.zoomIdentity
    .translate(width / 2 - scale * (bounds.x + bounds.width / 2), height / 2 - scale * (bounds.y + bounds.height / 2))
    .scale(scale)
  const target = animate ? svg.transition().duration(260) : svg
  target.call(zoom.transform, transform)
}

function init({ applyInitialCollapse = true } = {}) {
  if (flowchartCode.value) {
    rendering.value = false
    root = null
    return
  }
  rendering.value = true
  renderError.value = ''
  try {
    const data = structuredTree()
    const element = activeSvgElement()
    if (!data || !element) throw new Error('没有可绘制的导图节点。')
    svg = d3.select(element)
    svg.selectAll('*').remove()
    group = svg.append('g').attr('class', 'mindmap-container-g')
    zoom = d3.zoom().scaleExtent([0.15, 4]).on('zoom', event => {
      currentTransform = event.transform
      group.attr('transform', currentTransform)
    }).on('end', emitViewChange)
    svg.call(zoom)
    if (applyInitialCollapse && collapsedNodeIds.size === 0) {
      const collapseDeep = (item, depth = 0) => {
        if (depth >= 1 && item.children?.length) collapsedNodeIds.add(item.nodeId)
        item.children?.forEach(child => collapseDeep(child, depth + 1))
      }
      collapseDeep(data)
    }
    root = d3.hierarchy(data, visibleChildren)
    root.x0 = (element.clientHeight || props.height) / 2
    root.y0 = 80
    layout = d3.tree().nodeSize([NODE_SIZE.verticalGap, NODE_SIZE.horizontalGap])
    draw(root)
    nextTick(() => center({ animate: false }))
  } catch (error) {
    renderError.value = error?.message || '思维导图绘制失败。'
    emit('render-error', renderError.value)
  } finally {
    rendering.value = false
  }
}

function zoomBy(factor) {
  if (svg && zoom) svg.transition().duration(160).call(zoom.scaleBy, factor)
}

function expandAll() {
  collapsedNodeIds.clear()
  init({ applyInitialCollapse: false })
  emitViewChange()
}

function collapseAll() {
  const data = structuredTree()
  const visit = item => {
    if (item.children?.length) collapsedNodeIds.add(item.nodeId)
    item.children?.forEach(visit)
  }
  if (data) visit(data)
  init({ applyInitialCollapse: false })
  emitViewChange()
}

function toggleFullscreen() {
  isFullscreen.value = !isFullscreen.value
  nextTick(() => init({ applyInitialCollapse: false }))
}

function focusNode(nodeId) {
  // Search may target a node hidden inside a collapsed branch.
  const ancestors = (node, path = []) => {
    if (node.nodeId === nodeId) return path
    for (const child of node.children || []) {
      const found = ancestors(child, [...path, node.nodeId])
      if (found) return found
    }
    return null
  }
  const data = structuredTree()
  const path = data ? ancestors(data) : null
  if (path?.some(id => collapsedNodeIds.has(id))) {
    path.forEach(id => collapsedNodeIds.delete(id))
    init({ applyInitialCollapse: false })
  }
  const item = root?.descendants().find(value => value.data.nodeId === nodeId)
  const element = activeSvgElement()
  if (!item || !element || !svg || !zoom) return false
  const scale = Math.max(1, currentTransform.k)
  const transform = d3.zoomIdentity
    .translate((element.clientWidth || 900) / 2 - item.y * scale, (element.clientHeight || props.height) / 2 - item.x * scale)
    .scale(scale)
  nextTick(() => svg.transition().duration(220).call(zoom.transform, transform))
  emit('select', item.data)
  return true
}

function restoreView(value) {
  collapsedNodeIds.clear()
  for (const nodeId of value?.collapsedNodeIds || []) collapsedNodeIds.add(nodeId)
  init({ applyInitialCollapse: false })
  const transform = value?.transform
  if (transform && svg && zoom) nextTick(() => svg.call(zoom.transform, d3.zoomIdentity.translate(transform.x, transform.y).scale(transform.k)))
}

defineExpose({ center, collapseAll, expandAll, focusNode, restoreView, zoomBy, toggleFullscreen })

watch(() => [props.code, props.nodes, props.rootNodeId], () => {
  collapsedNodeIds.clear()
  nextTick(() => init())
}, { deep: true })
watch(() => props.selectedNodeId, () => draw(root))

onMounted(() => {
  nextTick(() => init())
  let observedSize = null
  resizeObserver = new ResizeObserver(([entry]) => {
    const size = `${entry.contentRect.width}:${entry.contentRect.height}`
    // The first notification is not a resize; initial layout/restoration already
    // placed the canvas. Re-centering here would discard a restored zoom level.
    if (observedSize !== null && observedSize !== size) center({ animate: false })
    observedSize = size
  })
  if (containerRef.value) resizeObserver.observe(containerRef.value)
})

onBeforeUnmount(() => resizeObserver?.disconnect())
</script>

<template>
  <div ref="containerRef" class="collapsible-mindmap" :class="{ 'collapsible-mindmap--embedded': !showToolbar }" :style="{ '--mindmap-height': `${height}px` }">
    <div v-show="!isFullscreen" class="mindmap-card">
      <div v-if="showToolbar" class="mindmap-toolbar">
        <div class="mindmap-toolbar__title"><strong>思维导图</strong></div>
        <div class="mindmap-toolbar__actions">
          <button v-if="!flowchartCode" type="button" @click="expandAll">展开</button>
          <button v-if="!flowchartCode" type="button" @click="collapseAll">折叠</button>
          <button v-if="!flowchartCode" type="button" @click="center()">居中</button>
          <button type="button" @click="toggleFullscreen">放大/全屏</button>
        </div>
      </div>
      <div v-if="flowchartCode" class="mindmap-canvas mindmap-flowchart">
        <IncrementalMarkdownRenderer :text="flowchartCode" />
      </div>
      <div v-else class="mindmap-canvas">
        <div v-if="rendering" class="mindmap-state" role="status">正在整理知识关系...</div>
        <div v-else-if="renderError" class="mindmap-state mindmap-state--error" role="alert">{{ userMessage(renderError) }}</div>
        <svg ref="svgRef" class="mindmap-svg" aria-label="可缩放、可折叠的思维导图画布" />
        <div class="mindmap-help">拖动平移 · 滚轮缩放</div>
      </div>
    </div>

    <Teleport to="body">
      <div v-if="isFullscreen" class="mindmap-modal" role="dialog" aria-label="全屏思维导图" @click.self="toggleFullscreen">
        <div class="mindmap-modal__panel">
          <div class="mindmap-toolbar mindmap-toolbar--modal">
            <div class="mindmap-toolbar__title"><strong>思维导图</strong></div>
            <div class="mindmap-toolbar__actions">
              <button v-if="!flowchartCode" type="button" @click="expandAll">展开分支</button>
              <button v-if="!flowchartCode" type="button" @click="collapseAll">折叠分支</button>
              <button v-if="!flowchartCode" type="button" @click="center()">视图居中</button>
              <button type="button" aria-label="关闭全屏" @click="toggleFullscreen">关闭</button>
            </div>
          </div>
          <div v-if="flowchartCode" class="mindmap-modal__canvas mindmap-flowchart">
            <IncrementalMarkdownRenderer :text="flowchartCode" />
          </div>
          <div v-else class="mindmap-modal__canvas">
            <svg ref="fullscreenSvgRef" class="mindmap-svg" aria-label="全屏可缩放、可折叠的思维导图画布" />
            <div class="mindmap-help">拖拽移动 · 滚轮缩放 · 节点右侧圆钮折叠/展开</div>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
.mindmap-flowchart { overflow: auto; padding: 12px; }
.mindmap-flowchart :deep(.inc-mermaid svg) { min-width: 720px; }
.collapsible-mindmap{position:relative;width:100%;height:var(--mindmap-height);min-height:420px;overflow:hidden;background:var(--color-surface);border:1px solid var(--color-border);border-radius:var(--radius-panel)}
.collapsible-mindmap--embedded{border:0;border-radius:0}
.mindmap-card{height:100%;background:var(--color-surface)}
.mindmap-toolbar{height:48px;display:flex;align-items:center;justify-content:space-between;padding:0 14px;border-bottom:1px solid var(--color-border);background:var(--color-surface-subtle);gap:12px}
.mindmap-toolbar__title,.mindmap-toolbar__actions{display:flex;align-items:center;gap:8px}.mindmap-toolbar__title{color:var(--color-text);font-size:14px}
.mindmap-toolbar__actions button{border:0;border-radius:var(--radius-control);background:var(--color-surface-muted);color:var(--color-text-secondary);padding:6px 9px;font-size:14px;cursor:pointer}.mindmap-toolbar__actions button:hover{background:var(--color-accent-soft);color:var(--color-text)}.mindmap-toolbar__actions button:focus-visible{outline:2px solid var(--color-accent);outline-offset:2px}
.mindmap-canvas,.mindmap-modal__canvas{position:relative;height:calc(100% - 48px);background:var(--color-surface)}.mindmap-modal__canvas{height:calc(100% - 58px)}
.collapsible-mindmap--embedded .mindmap-canvas{height:100%}
.mindmap-svg{display:block;width:100%;height:100%;cursor:grab;outline:none;touch-action:none}.mindmap-svg:active{cursor:grabbing}
.mindmap-state{position:absolute;inset:0;z-index:2;display:grid;place-items:center;background:rgba(255,255,255,.94);color:#526475;font-size:14px}.mindmap-state--error{color:#a33d3d}
.mindmap-help{position:absolute;right:14px;bottom:10px;z-index:1;pointer-events:none;color:#64748b;font-size:14px;background:rgba(255,255,255,.92);padding:3px 6px;border-radius:4px}
:deep(.mindmap-node){cursor:pointer;outline:none}:deep(.mindmap-node:focus-visible .mindmap-node__rect){stroke:#172b3a;stroke-width:3}
:deep(.mindmap-node-content){display:flex;align-items:center;justify-content:center;width:100%;height:100%;padding:0 6px;text-align:center;line-height:1.3;word-break:break-word;overflow:hidden;user-select:none}
:deep(.mindmap-node-content .katex){font-size:1em}:deep(.mindmap-node__toggle){cursor:pointer}:deep(.mindmap-node__toggle-label){font:700 16px/1 var(--font-sans);pointer-events:none}
.mindmap-modal{position:fixed;inset:0;z-index:80;display:flex;align-items:center;justify-content:center;padding:24px;background:rgba(15,23,42,.62)}.mindmap-modal__panel{width:min(1240px,96vw);height:min(88vh,820px);display:flex;flex-direction:column;overflow:hidden;background:var(--color-surface);border-radius:14px;box-shadow:0 20px 60px rgba(15,23,42,.3)}.mindmap-toolbar--modal{height:58px}
@media (max-width:760px){.mindmap-toolbar{padding:0 8px}.mindmap-toolbar__title strong{display:none}.mindmap-toolbar__actions{gap:4px}.mindmap-toolbar__actions button{padding:5px 6px;font-size:14px}.mindmap-help{font-size:14px;right:6px}}
</style>
