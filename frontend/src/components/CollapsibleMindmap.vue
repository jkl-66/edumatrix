<script setup>
import { ref, onMounted, watch, nextTick } from 'vue'
import * as d3 from 'd3'

const props = defineProps({
  code: {
    type: String,
    required: true
  }
})

const svgRef = ref(null)
const containerRef = ref(null)

// --- 1. Parser: Convert Indented Mermaid-like Mindmap text to Hierarchical JSON ---
function parseIndentTextToTree(codeText) {
  if (!codeText) return null
  const lines = codeText.split(/\r?\n/)
  const rootNodes = []
  const stack = []

  const delimPairs = [
    { open: '((', close: '))' },
    { open: '{{', close: '}}' },
    { open: '(', close: ')' },
    { open: '[', close: ']' },
  ]

  for (let line of lines) {
    const trimmed = line.trim()
    if (!trimmed || trimmed === 'mindmap' || trimmed.startsWith('%%')) {
      continue
    }

    const leadingSpaces = line.match(/^(\s*)/)[0].length
    
    // Clean display text
    let cleaned = trimmed.replace(/^[-*+]\s+/, '')
    cleaned = cleaned.replace(/\*\*/g, '').replace(/`/g, '')
    if (cleaned.startsWith('"') && cleaned.endsWith('"')) {
      cleaned = cleaned.slice(1, -1).trim()
    }

    // Match ID + shape delimiters
    let displayText = cleaned
    for (const pair of delimPairs) {
      const escapedOpen = pair.open.replace(/[|\\{}()[\]^$+*?.]/g, '\\$&')
      const escapedClose = pair.close.replace(/[|\\{}()[\]^$+*?.]/g, '\\$&')
      const regex = new RegExp(`^[a-zA-Z0-9_-]+\\s*${escapedOpen}\\s*(.*?)\\s*${escapedClose}$`)
      const match = cleaned.match(regex)
      if (match) {
        displayText = match[1].trim()
        break
      }
    }
    
    if (displayText.startsWith('"') && displayText.endsWith('"')) {
      displayText = displayText.slice(1, -1)
    }
    displayText = displayText
      .replace(/&quot;/g, '"')
      .replace(/&amp;/g, '&')
      .replace(/&lt;/g, '<')
      .replace(/&gt;/g, '>')

    const node = {
      name: displayText,
      children: [],
      _children: null,
      collapsed: false
    }

    if (stack.length === 0) {
      rootNodes.push(node)
      stack.push({ node, indent: leadingSpaces })
    } else {
      while (stack.length > 0 && stack[stack.length - 1].indent >= leadingSpaces) {
        stack.pop()
      }
      if (stack.length > 0) {
        const parent = stack[stack.length - 1].node
        parent.children.push(node)
      } else {
        rootNodes.push(node)
      }
      stack.push({ node, indent: leadingSpaces })
    }
  }

  if (rootNodes.length === 1) return rootNodes[0]
  if (rootNodes.length > 1) {
    return { name: "概念思维导图", children: rootNodes }
  }
  return null
}

// --- 2. D3 Tree Rendering Engine ---
let d3Root = null
let d3Zoom = null
let d3Svg = null
let d3G = null
let treeLayout = null

function initAndRender() {
  const treeData = parseIndentTextToTree(props.code)
  if (!treeData || !svgRef.value) return

  const width = containerRef.value?.clientWidth || 500
  const height = 320

  // Select SVG and clear previous contents
  d3Svg = d3.select(svgRef.value)
  d3Svg.selectAll('*').remove()

  // Setup main group
  d3G = d3Svg.append('g').attr('class', 'mindmap-container-g')

  // Setup zoom behaviour
  d3Zoom = d3.zoom()
    .scaleExtent([0.3, 3])
    .on('zoom', (event) => {
      d3G.attr('transform', event.transform)
    })
  d3Svg.call(d3Zoom)

  // Configure tree layout
  // vertical separation 38px, horizontal step 170px
  treeLayout = d3.tree().nodeSize([38, 170])

  // Convert hierarchy data
  d3Root = d3.hierarchy(treeData)
  d3Root.x0 = height / 2
  d3Root.y0 = 60

  // Collapse deep nodes initially (collapse children starting from depth 2)
  const collapseDeep = (d) => {
    if (d.depth >= 2 && d.children) {
      d._children = d.children
      d.children = null
    }
    if (d.children) d.children.forEach(collapseDeep)
    if (d._children) d._children.forEach(collapseDeep)
  }
  collapseDeep(d3Root)

  // Trigger initial update
  updateTree(d3Root)
  
  // Center the layout
  centerLayout()
}

function updateTree(source) {
  if (!d3Root || !d3G) return

  // Assigns the x and y positions for the nodes
  const treeData = treeLayout(d3Root)

  // Compute the new tree layout.
  const nodes = treeData.descendants()
  const links = treeData.links()

  // Normalize for fixed-depth.
  nodes.forEach(d => { d.y = d.depth * 170 + 60 })

  // --- Node Section ---
  const node = d3G.selectAll('g.node')
    .data(nodes, d => d.id || (d.id = Math.random().toString(36).substr(2, 9)))

  // Enter any new nodes at the parent's previous position.
  const nodeEnter = node.enter().append('g')
    .attr('class', 'node')
    .attr('transform', d => `translate(${source.y0},${source.x0})`)
    .on('click', (event, d) => {
      if (d.children) {
        d._children = d.children
        d.children = null
      } else {
        d.children = d._children
        d._children = null
      }
      updateTree(d)
    })
    .style('cursor', 'pointer')

  // Node shape: Rounded rectangle
  nodeEnter.append('rect')
    .attr('class', 'node-rect')
    .attr('rx', 8)
    .attr('ry', 8)
    .attr('fill', 'transparent')
    .attr('stroke', '#8b5cf6')
    .attr('stroke-width', 1.5)

  // Text label
  nodeEnter.append('text')
    .attr('dy', '0.31em')
    .attr('text-anchor', 'middle')
    .attr('fill', '#1e293b')
    .style('font-size', '10px')
    .style('font-weight', '500')
    .style('user-select', 'none')
    .text(d => d.data.name)

  // Transition nodes to their new position.
  const nodeUpdate = node.merge(nodeEnter)
  nodeUpdate.transition()
    .duration(300)
    .attr('transform', d => `translate(${d.y},${d.x})`)

  // Update rect sizes dynamically based on text length
  nodeUpdate.select('rect')
    .attr('width', d => {
      const name = d.data.name || ''
      let len = 0
      for (let char of name) {
        len += char.charCodeAt(0) > 127 ? 11 : 6.5
      }
      return len + 20
    })
    .attr('height', 22)
    .attr('y', -11)
    .attr('x', d => {
      const name = d.data.name || ''
      let len = 0
      for (let char of name) {
        len += char.charCodeAt(0) > 127 ? 11 : 6.5
      }
      return -(len + 20) / 2
    })
    // Accent indicator for parent node with collapsed children
    .attr('stroke', d => d._children ? '#4f46e5' : '#8b5cf6')
    .attr('stroke-width', d => d._children ? 2.5 : 1.5)
    .attr('fill', d => d._children ? 'rgba(139, 92, 246, 0.04)' : 'transparent')

  // Transition exiting nodes to the parent's new position.
  const nodeExit = node.exit().transition()
    .duration(300)
    .attr('transform', d => `translate(${source.y},${source.x})`)
    .remove()

  nodeExit.select('rect')
    .attr('width', 0)
    .attr('height', 0)

  nodeExit.select('text')
    .style('fill-opacity', 0)

  // --- Link Section ---
  const link = d3G.selectAll('path.link')
    .data(links, d => d.target.id)

  // Enter any new links at the parent's previous position.
  const linkEnter = link.enter().insert('path', 'g')
    .attr('class', 'link')
    .attr('fill', 'none')
    .attr('stroke', '#e2e8f0')
    .attr('stroke-width', 1.5)
    .attr('d', d => {
      const o = { x: source.x0, y: source.y0 }
      return d3.linkHorizontal().x(d => d.y).y(d => d.x)({ source: o, target: o })
    })

  // Transition links to their new position.
  const linkUpdate = link.merge(linkEnter)
  linkUpdate.transition()
    .duration(300)
    .attr('stroke', '#cbd5e1')
    .attr('d', d3.linkHorizontal().x(d => d.y).y(d => d.x))

  // Transition exiting nodes to the parent's new position.
  link.exit().transition()
    .duration(300)
    .attr('d', d => {
      const o = { x: source.x, y: source.y }
      return d3.linkHorizontal().x(d => d.y).y(d => d.x)({ source: o, target: o })
    })
    .remove()

  // Store the old positions for transition.
  nodes.forEach(d => {
    d.x0 = d.x
    d.y0 = d.y
  })
}

function centerLayout() {
  if (!d3Svg || !d3Zoom || !d3Root) return
  const svgEl = svgRef.value
  if (!svgEl) return

  const width = svgEl.clientWidth || 500
  const height = 320

  // Calculate hierarchical bounds
  let minX = Infinity, maxX = -Infinity
  d3Root.each(d => {
    if (d.x < minX) minX = d.x
    if (d.x > maxX) maxX = d.x
  })

  // Midpoint of nodes tree layout
  const treeMidpoint = (minX + maxX) / 2
  const targetX = 40 // Left padding
  const targetY = height / 2 - treeMidpoint

  const initialTransform = d3.zoomIdentity
    .translate(targetX, targetY)
    .scale(0.95)

  d3Svg.transition()
    .duration(500)
    .call(d3Zoom.transform, initialTransform)
}

function expandAll() {
  if (!d3Root) return
  const expand = (d) => {
    if (d._children) {
      d.children = d._children
      d._children = null
    }
    if (d.children) d.children.forEach(expand)
  }
  expand(d3Root)
  updateTree(d3Root)
}

function collapseAll() {
  if (!d3Root) return
  const collapse = (d) => {
    if (d.children && d.depth > 0) {
      d._children = d.children
      d.children = null
    }
    if (d.children) d.children.forEach(collapse)
    if (d._children) d._children.forEach(collapse)
  }
  collapse(d3Root)
  updateTree(d3Root)
}

function resetZoom() {
  centerLayout()
}

watch(() => props.code, () => {
  nextTick(() => {
    initAndRender()
  })
})

onMounted(() => {
  nextTick(() => {
    initAndRender()
  })
})
</script>

<template>
  <div ref="containerRef" class="collapsible-mindmap w-full relative border border-purple-100 rounded-2xl bg-white overflow-hidden shadow-sm my-3 p-1">
    <!-- Header panel -->
    <div class="w-full flex items-center justify-between px-3 py-2 border-b border-gray-50 bg-gray-50/20 z-10 relative">
      <div class="flex items-center gap-1.5">
        <span class="text-base">📊</span>
        <span class="font-bold text-gray-800 text-xs">交互式思维导图</span>
        <span class="text-[9px] bg-purple-50 text-purple-600 px-1.5 py-0.5 rounded font-mono font-medium">可折叠分支</span>
      </div>
      <div class="flex items-center gap-1.5">
        <button @click="expandAll" class="px-2 py-1 bg-purple-50 hover:bg-purple-100 text-purple-600 rounded text-[10px] font-semibold transition-all">
          展开
        </button>
        <button @click="collapseAll" class="px-2 py-1 bg-purple-50 hover:bg-purple-100 text-purple-600 rounded text-[10px] font-semibold transition-all">
          折叠
        </button>
        <button @click="resetZoom" class="px-2 py-1 bg-gray-100 hover:bg-gray-200 text-gray-600 rounded text-[10px] font-semibold transition-all">
          居中
        </button>
      </div>
    </div>
    
    <!-- SVG Mindmap container -->
    <div class="w-full h-[320px] bg-white relative">
      <svg ref="svgRef" class="w-full h-full cursor-grab active:cursor-grabbing select-none"></svg>
      <div class="absolute bottom-2 right-3 text-[9px] text-gray-400 select-none pointer-events-none">
        💡 点击节点折叠/展开 • 拖拽画布移动 • 滚轮缩放
      </div>
    </div>
  </div>
</template>

<style scoped>
.collapsible-mindmap {
  transition: border-color 0.2s ease;
}
.collapsible-mindmap:hover {
  border-color: var(--color-accent, #8b5cf6);
}
.node-rect {
  transition: stroke 0.2s, stroke-width 0.2s, fill 0.2s;
}
.node:hover .node-rect {
  stroke: #4f46e5 !important;
  stroke-width: 2.2px !important;
  fill: rgba(139, 92, 246, 0.08) !important;
}
</style>
