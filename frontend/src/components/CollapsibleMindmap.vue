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
const fullscreenSvgRef = ref(null)
const containerRef = ref(null)
const isFullscreen = ref(false)

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

// --- 2. Color Mapper based on Depth ---
function getNodeColors(d) {
  const depth = d.depth
  if (depth === 0) {
    return {
      fill: '#e8ecfb',        // Soft purple-blue root
      stroke: '#818cf8',      // Indigo border
      text: '#4338ca',        // Indigo text
      line: '#4f46e5'         // Indigo-600 (one level darker than stroke #818cf8)
    }
  } else if (depth === 1) {
    return {
      fill: '#eff6ff',        // Soft sky blue
      stroke: '#3b82f6',      // Blue border
      text: '#1e3a8a',        // Dark blue text
      line: '#2563eb'         // Blue-600 (one level darker than stroke #3b82f6)
    }
  } else {
    return {
      fill: '#ecfdf5',        // Soft mint green
      stroke: '#10b981',      // Emerald border
      text: '#064e3b',        // Dark emerald green text
      line: '#059669'         // Emerald-600 (one level darker than stroke #10b981)
    }
  }
}

// --- 3. D3 Tree Rendering Engine ---
let d3Root = null
let d3Zoom = null
let d3Svg = null
let d3G = null
let treeLayout = null

function initAndRender() {
  const treeData = parseIndentTextToTree(props.code)
  const svgEl = isFullscreen.value ? fullscreenSvgRef.value : svgRef.value
  if (!treeData || !svgEl) return

  const height = isFullscreen.value ? (window.innerHeight - 80) : 320

  // Select SVG and clear previous contents
  d3Svg = d3.select(svgEl)
  d3Svg.selectAll('*').remove()

  // Setup main group
  d3G = d3Svg.append('g').attr('class', 'mindmap-container-g')

  // Setup zoom behaviour
  d3Zoom = d3.zoom()
    .scaleExtent([0.15, 4])
    .on('zoom', (event) => {
      d3G.attr('transform', event.transform)
    })
  d3Svg.call(d3Zoom)

  // Configure tree layout (vertical separation 80px, horizontal step 340px)
  treeLayout = d3.tree().nodeSize([80, 340])

  // Convert hierarchy data
  d3Root = d3.hierarchy(treeData)
  d3Root.x0 = height / 2
  d3Root.y0 = 60

  // Collapse deep nodes initially (depth >= 2)
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

// 渲染节点 HTML (支持 KaTeX 行内渲染与 sub/sup 上下标 fallback 转换)
function renderNodeHtml(text) {
  if (!text) return ''

  // 如果包含 $ 符号，尝试用 KaTeX 渲染
  if (text.includes('$') && window.katex) {
    try {
      return text.replace(/\$([^$]+)\$/g, (_, math) => {
        return window.katex.renderToString(math, {
          throwOnError: false,
          displayMode: false
        })
      })
    } catch (e) {
      console.error('KaTeX error in mindmap node:', e)
    }
  }

  // 兜底的轻量级上下标及希腊字母正则转换
  let rendered = text
    .replace(/([a-zA-Z0-9])_\{([^}]+)\}/g, '$1<sub>$2</sub>')
    .replace(/([a-zA-Z0-9])_([a-zA-Z0-9]+)/g, '$1<sub>$2</sub>')
    .replace(/([a-zA-Z0-9])\^\{([^}]+)\}/g, '$1<sup>$2</sup>')
    .replace(/([a-zA-Z0-9])\^([a-zA-Z0-9+-\\*\\partial]+)/g, '$1<sup>$2</sup>')
    .replace(/\\sigma\b/g, 'σ')
    .replace(/\\Sigma\b/g, '∑')
    .replace(/\\alpha\b/g, 'α')
    .replace(/\\beta\b/g, 'β')
    .replace(/\\theta\b/g, 'θ')
    .replace(/\\cdot/g, '·')

  return rendered
}

function updateTree(source) {
  if (!d3Root || !d3G) return

  // Assigns the x and y positions for the nodes
  const treeData = treeLayout(d3Root)

  // Compute the new tree layout.
  const nodes = treeData.descendants()
  const links = treeData.links()

  // Normalize for fixed-depth and pre-calculate label widths.
  nodes.forEach(d => { 
    d.y = d.depth * 340 + 60 
    
    // Calculate node text length for halfWidth
    const name = d.data.name || ''
    let len = 0
    for (let char of name) {
      len += char.charCodeAt(0) > 127 ? 11 : 6.5
    }
    // 对公式节点和包含 LaTeX 特征的文本，增加 25px 的 padding 缓冲值
    const hasMath = name.includes('$') || name.includes('_') || name.includes('^') || name.includes('{') || name.includes('}') || name.includes('\\')
    d.halfWidth = (len + (hasMath ? 45 : 20)) / 2
  })

  // --- Node Section ---
  const node = d3G.selectAll('g.node')
    .data(nodes, d => d.id || (d.id = Math.random().toString(36).substr(2, 9)))

  // Enter any new nodes at the parent's previous position.
  const nodeEnter = node.enter().append('g')
    .attr('class', 'node')
    .attr('transform', d => `translate(${source.y0 + source.halfWidth},${source.x0})`)
    // No click on the main node to prevent expansion misclicks, clicks are routed to toggle-btn.
    .style('cursor', 'default')

  // Node shape: Rounded rectangle
  nodeEnter.append('rect')
    .attr('class', 'node-rect')
    .attr('rx', 8)
    .attr('ry', 8)
    .attr('fill', 'transparent')
    .attr('stroke', '#818cf8')
    .attr('stroke-width', 1.5)

  // Text label via foreignObject (for rich text/LaTeX rendering)
  const fo = nodeEnter.append('foreignObject')
    .attr('class', 'node-fo')
    .attr('height', 24)
    .attr('y', -12)
    .style('overflow', 'visible')

  fo.append('xhtml:div')
    .attr('class', 'mindmap-node-content')
    .style('width', '100%')
    .style('height', '100%')
    .style('display', 'flex')
    .style('align-items', 'center')
    .style('justify-content', 'center')
    .style('font-size', '10px')
    .style('font-weight', '500')
    .style('user-select', 'none')
    .style('line-height', '1.2')

  // Small circle toggle button `<` or `>` at the right edge center
  const toggleG = nodeEnter.append('g')
    .attr('class', 'toggle-btn')
    .attr('transform', d => `translate(${d.halfWidth}, 0)`)
    .style('cursor', 'pointer')
    .on('click', (event, d) => {
      event.stopPropagation()
      if (d.children) {
        d._children = d.children
        d.children = null
      } else {
        d.children = d._children
        d._children = null
      }
      updateTree(d)
    })

  // Circular toggle background
  toggleG.append('circle')
    .attr('r', 8)
    .attr('fill', '#ffffff')
    .attr('stroke-width', 1.5)

  // Circular toggle label
  toggleG.append('text')
    .attr('dy', '0.31em')
    .attr('text-anchor', 'middle')
    .style('font-size', '8px')
    .style('font-weight', 'bold')
    .style('user-select', 'none')

  // Transition nodes to their new position.
  const nodeUpdate = node.merge(nodeEnter)
  nodeUpdate.transition()
    .duration(300)
    .attr('transform', d => `translate(${d.y},${d.x})`)

  // Update rect sizes dynamically based on text length
  nodeUpdate.select('rect')
    .attr('width', d => d.halfWidth * 2)
    .attr('height', 24)
    .attr('y', -12)
    .attr('x', d => -d.halfWidth)
    .attr('fill', d => getNodeColors(d).fill)
    .attr('stroke', d => getNodeColors(d).stroke)
    .attr('stroke-width', 1.5)

  // Update foreignObject position and content
  const foUpdate = nodeUpdate.select('foreignObject')
    .attr('x', d => -d.halfWidth)
    .attr('width', d => d.halfWidth * 2)

  foUpdate.select('div.mindmap-node-content')
    .html(d => renderNodeHtml(d.data.name))
    .style('color', d => getNodeColors(d).text)

  // Update toggle button position and content
  const toggleUpdate = nodeUpdate.select('g.toggle-btn')
    .attr('transform', d => `translate(${d.halfWidth}, 0)`)
    .style('display', d => (d.children || d._children) ? 'block' : 'none')

  toggleUpdate.select('circle')
    .attr('stroke', d => getNodeColors(d).stroke)

  toggleUpdate.select('text')
    .attr('fill', d => getNodeColors(d).text)
    .text(d => d.children ? '<' : '>')

  // Transition exiting nodes to the parent's new position.
  const nodeExit = node.exit().transition()
    .duration(300)
    .attr('transform', d => `translate(${source.y + source.halfWidth},${source.x})`)
    .remove()

  nodeExit.select('rect')
    .attr('width', 0)
    .attr('height', 0)

  nodeExit.select('foreignObject')
    .style('opacity', 0)

  // --- Link Section ---
  const link = d3G.selectAll('path.link')
    .data(links, d => d.target.id)

  const linkGenerator = d3.linkHorizontal().x(d => d.y).y(d => d.x)

  // Enter any new links at the parent's previous position.
  const linkEnter = link.enter().insert('path', 'g')
    .attr('class', 'link')
    .attr('fill', 'none')
    .attr('stroke', d => getNodeColors(d.source).line)
    .attr('stroke-opacity', d => d.source.depth === 0 ? 0.85 : (d.source.depth === 1 ? 0.8 : 0.75))
    .attr('stroke-width', d => d.source.depth === 0 ? 2.2 : (d.source.depth === 1 ? 1.8 : 1.4))
    .style('stroke-linecap', 'round')
    .attr('d', d => {
      const o = { x: source.x0, y: source.y0 + source.halfWidth }
      return linkGenerator({ source: o, target: o })
    })

  // Transition links to their new position.
  const linkUpdate = link.merge(linkEnter)
  linkUpdate.transition()
    .duration(300)
    .attr('stroke', d => getNodeColors(d.source).line)
    .attr('stroke-opacity', d => d.source.depth === 0 ? 0.85 : (d.source.depth === 1 ? 0.8 : 0.75))
    .attr('stroke-width', d => d.source.depth === 0 ? 2.2 : (d.source.depth === 1 ? 1.8 : 1.4))
    .style('stroke-linecap', 'round')
    .attr('d', d => {
      const s = { y: d.source.y + d.source.halfWidth, x: d.source.x }
      const t = { y: d.target.y - d.target.halfWidth, x: d.target.x }
      return linkGenerator({ source: s, target: t })
    })

  // Transition exiting nodes to the parent's new position.
  link.exit().transition()
    .duration(300)
    .attr('d', d => {
      const o = { x: source.x, y: source.y + source.halfWidth }
      return linkGenerator({ source: o, target: o })
    })
    .remove()

  // Store the old positions for transition.
  nodes.forEach(d => {
    d.x0 = d.x
    d.y0 = d.y
  })
}

function centerLayout() {
  const svgEl = isFullscreen.value ? fullscreenSvgRef.value : svgRef.value
  if (!d3Svg || !d3Zoom || !d3Root || !svgEl) return

  const width = svgEl.clientWidth || 500
  const height = isFullscreen.value ? (window.innerHeight - 80) : 320

  // Calculate hierarchical bounds
  let minX = Infinity, maxX = -Infinity
  d3Root.each(d => {
    if (d.x < minX) minX = d.x
    if (d.x > maxX) maxX = d.x
  })

  const treeMidpoint = (minX + maxX) / 2
  const targetX = isFullscreen.value ? 100 : 40 
  const targetY = height / 2 - treeMidpoint

  const initialTransform = d3.zoomIdentity
    .translate(targetX, targetY)
    .scale(isFullscreen.value ? 1.1 : 0.9)

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

function toggleFullscreen() {
  isFullscreen.value = !isFullscreen.value
  nextTick(() => {
    initAndRender()
  })
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
  <div ref="containerRef" class="collapsible-mindmap w-full relative border border-purple-100 rounded-2xl bg-white overflow-hidden shadow-sm my-3 p-1 transition-all duration-300">
    
    <!-- 1. Card View (When NOT Fullscreen) -->
    <div v-show="!isFullscreen" class="w-full">
      <!-- Card Header -->
      <div class="w-full flex items-center justify-between px-3 py-2 border-b border-gray-50 bg-gray-50/20 z-10 relative">
        <div class="flex items-center gap-1.5">
          <span class="text-base">📊</span>
          <span class="font-bold text-gray-800 text-xs">概念思维导图</span>
          <span class="text-[9px] bg-purple-50 text-purple-600 px-1.5 py-0.5 rounded font-mono font-medium">可折叠分支</span>
        </div>
        <div class="flex items-center gap-1.5 text-xs">
          <button @click="expandAll" class="px-2 py-1 bg-purple-50 hover:bg-purple-100 text-purple-600 rounded text-[10px] font-semibold transition-all">
            展开
          </button>
          <button @click="collapseAll" class="px-2 py-1 bg-purple-50 hover:bg-purple-100 text-purple-600 rounded text-[10px] font-semibold transition-all">
            折叠
          </button>
          <button @click="resetZoom" class="px-2 py-1 bg-gray-100 hover:bg-gray-200 text-gray-600 rounded text-[10px] font-semibold transition-all">
            居中
          </button>
          <button @click="toggleFullscreen" class="px-2 py-1 bg-indigo-50 hover:bg-indigo-100 text-indigo-600 rounded text-[10px] font-semibold transition-all shadow-sm">
            🔍 放大/全屏
          </button>
        </div>
      </div>
      
      <!-- Card SVG Container -->
      <div class="w-full h-[320px] bg-white relative">
        <svg ref="svgRef" class="w-full h-full cursor-grab active:cursor-grabbing select-none"></svg>
        <div class="absolute bottom-2 right-3 text-[9px] text-gray-400 select-none pointer-events-none">
          💡 点击右侧按键折叠/展开 • 拖拽画布移动 • 滚轮缩放
        </div>
      </div>
    </div>

    <!-- 2. Fullscreen Modal View (Teleported to Body) -->
    <Teleport to="body">
      <div v-if="isFullscreen" class="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex items-center justify-center p-6" @click.self="toggleFullscreen">
        <div class="w-full max-w-6xl h-[85vh] bg-white rounded-3xl overflow-hidden shadow-2xl flex flex-col relative animate-fade-in">
          <!-- Modal Header -->
          <div class="w-full flex items-center justify-between px-6 py-4 border-b border-gray-100 bg-gray-50/50">
            <div class="flex items-center gap-2.5">
              <span class="text-xl">📊</span>
              <h3 class="font-bold text-gray-800 text-base">概念思维导图</h3>
              <span class="text-xs bg-purple-50 text-purple-600 px-2 py-0.5 rounded font-mono font-medium">全屏交互画布</span>
            </div>
            <div class="flex items-center gap-3 text-xs">
              <button @click="expandAll" class="px-3 py-1.5 bg-purple-50 hover:bg-purple-100 text-purple-600 rounded-lg font-semibold transition-all">展开分支</button>
              <button @click="collapseAll" class="px-3 py-1.5 bg-purple-50 hover:bg-purple-100 text-purple-600 rounded-lg font-semibold transition-all">折叠分支</button>
              <button @click="resetZoom" class="px-3 py-1.5 bg-gray-100 hover:bg-gray-200 text-gray-600 rounded-lg font-semibold transition-all">视图居中</button>
              <button @click="toggleFullscreen" class="p-1.5 bg-gray-100 hover:bg-red-50 hover:text-red-500 rounded-lg transition-all" title="关闭全屏">
                <span class="text-sm font-bold px-2 select-none">✕</span>
              </button>
            </div>
          </div>

          <!-- Modal SVG Container -->
          <div class="flex-1 bg-white relative">
            <svg ref="fullscreenSvgRef" class="w-full h-full cursor-grab active:cursor-grabbing select-none"></svg>
            <div class="absolute bottom-4 right-6 text-xs text-gray-400 select-none pointer-events-none">
              💡 点击右侧按键折叠/展开 • 拖拽画布移动 • 滚轮无级缩放
            </div>
          </div>
        </div>
      </div>
    </Teleport>
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
  filter: drop-shadow(0 2px 6px rgba(99, 102, 241, 0.12));
}

.animate-fade-in {
  animation: fadeIn 0.25s cubic-bezier(0.4, 0, 0.2, 1) forwards;
}

@keyframes fadeIn {
  from { opacity: 0; transform: scale(0.96); }
  to { opacity: 1; transform: scale(1); }
}
</style>
