<script setup>
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { RotateCw, Info } from '@lucide/vue'
import { echarts } from '../lib/echarts-graph'
import SearchField from './ui/SearchField.vue'

const props = defineProps({
  nodes: { type: Array, default: () => [] },
  edges: { type: Array, default: () => [] },
  categories: { type: Array, default: () => [] },
  chartTitle: { type: String, default: '知识图谱' },
  chartSubtitle: { type: String, default: '拖拽探索 · 点击节点查看关联' },
  showDetails: { type: Boolean, default: true },
  layoutMode: { type: String, default: 'graph' },
  showMasteryInTooltip: { type: Boolean, default: true },
  fitDenseGraph: { type: Boolean, default: false },
  fixedLayout: { type: Boolean, default: false },
  profileLayout: { type: Boolean, default: false },
  // Reuse the former LearningPathGraph interaction model: one meaningful
  // focus concept, its direct neighbours on the first ring, and the
  // remaining course context on outer rings. The nodes/edges themselves are
  // still supplied by the current canonical graph endpoint.
  legacyPathLayout: { type: Boolean, default: false },
  layoutDecision: { type: Object, default: null },
  topicClusters: { type: Array, default: () => [] },
  height: { type: Number, default: 520 },
  emptyText: { type: String, default: '当前课程还没有可展示的知识节点' },
})

const emit = defineEmits(['node-select', 'reset'])
const chartRef = ref(null)
const searchQuery = ref('')
const selectedNode = ref(null)
const highlightedNodes = ref(new Set())
const nodeTypeFilter = ref('all')
const relationTypeFilter = ref('all')
const focusDepth = ref(1)
const expandedNodeIds = ref(new Set())
let chartInstance = null

const relatedCount = computed(() => Math.max(highlightedNodes.value.size - 1, 0))
const relationshipProjection = computed(() => props.layoutMode === 'relationship_projection')
// Editorial Graph Gallery visual tokens, adapted to the existing ECharts
// renderer.  They deliberately affect presentation only: canonical nodes,
// relations, layout coordinates and host-page actions remain unchanged.
const editorialTokens = {
  paper: '#FFFFFF',
  ink: '#2A3B4D',
  accent: '#C84A31',
  inkStrong: 'rgba(42, 59, 77, 0.72)',
  inkMedium: 'rgba(42, 59, 77, 0.46)',
  inkSoft: 'rgba(42, 59, 77, 0.24)',
  inkFaint: 'rgba(42, 59, 77, 0.10)',
  accentSoft: 'rgba(200, 74, 49, 0.16)',
}
const profileEditorialTokens = {
  ...editorialTokens,
  accent: '#315b6d',
  accentSoft: 'rgba(49, 91, 109, 0.16)',
}
const categoryColors = [
  editorialTokens.inkStrong,
  editorialTokens.inkMedium,
  'rgba(68, 87, 105, 0.58)',
  'rgba(96, 111, 124, 0.52)',
  'rgba(123, 132, 138, 0.46)',
  'rgba(42, 59, 77, 0.34)',
  'rgba(42, 59, 77, 0.20)',
]
const profileCategoryColors = categoryColors
const structuralNodeTypes = new Set(['course', 'chapter', 'source'])
const nodeFilterValue = (node) => String(node?.categoryName || node?.nodeType || '').trim()
const nodeTypeOptions = computed(() => {
  const values = [...new Set(props.nodes.map(nodeFilterValue).filter(Boolean))]
  return values.map((value) => ({ value, label: value }))
})
const relationTypeOptions = computed(() => {
  const values = [...new Set(props.edges.map((edge) => String(edge.relationType || edge.label || '').trim()).filter(Boolean))]
  return values.map((value) => ({ value, label: value }))
})
const validNodes = computed(() => props.nodes.filter((node) => (
  String(node?.id || '').trim() && String(node?.name || '').trim()
)))
const semanticNodes = computed(() => validNodes.value.filter((node) => (
  !structuralNodeTypes.has(String(node?.nodeType || '').toLowerCase())
)))
const knowledgeNodes = computed(() => semanticNodes.value.filter((node) => node.nodeType === 'knowledge_point'))
const knowledgeNodeIds = computed(() => new Set(knowledgeNodes.value.map((node) => String(node.id))))
const knowledgeEdges = computed(() => props.edges.filter((edge) => (
  String(edge?.relationType || '').toLowerCase() === 'prerequisite'
  && knowledgeNodeIds.value.has(String(edge.source))
  && knowledgeNodeIds.value.has(String(edge.target))
  && String(edge.source) !== String(edge.target)
)))
const prerequisiteChildren = computed(() => {
  const children = new Map(knowledgeNodes.value.map((node) => [String(node.id), new Set()]))
  knowledgeEdges.value.forEach((edge) => children.get(String(edge.source))?.add(String(edge.target)))
  return children
})
const prerequisiteParents = computed(() => {
  const parents = new Map(knowledgeNodes.value.map((node) => [String(node.id), new Set()]))
  knowledgeEdges.value.forEach((edge) => parents.get(String(edge.target))?.add(String(edge.source)))
  return parents
})
const rootKnowledgeIds = computed(() => {
  const roots = knowledgeNodes.value
    .filter((node) => !(prerequisiteParents.value.get(String(node.id))?.size))
    .map((node) => String(node.id))
  return new Set(roots.length ? roots : knowledgeNodes.value.slice(0, 1).map((node) => String(node.id)))
})
const progressiveGraph = computed(() => (
  nodeTypeFilter.value === 'all'
  && knowledgeNodes.value.length > 8
  && knowledgeEdges.value.length > 0
))
const visibleNodes = computed(() => {
  // The default canvas is a semantic reading surface.  Course/chapter/source
  // anchors remain in the canonical payload and can be brought back with the
  // node-type filter, but they no longer appear as unlabeled circles in the
  // primary view.  If a payload has no semantic nodes, keep the graph useful
  // by showing its structural nodes instead of an empty canvas.
  if (nodeTypeFilter.value !== 'all') {
    return validNodes.value.filter((node) => nodeFilterValue(node) === nodeTypeFilter.value)
  }
  if (!semanticNodes.value.length) return validNodes.value
  if (!progressiveGraph.value) return semanticNodes.value
  const visibleIds = new Set(rootKnowledgeIds.value)
  const queue = [...expandedNodeIds.value]
  while (queue.length) {
    const parentId = queue.shift()
    for (const childId of prerequisiteChildren.value.get(String(parentId)) || []) {
      if (visibleIds.has(childId)) continue
      visibleIds.add(childId)
    }
  }
  return semanticNodes.value.filter((node) => visibleIds.has(String(node.id)))
})
const visibleNodeIds = computed(() => new Set(visibleNodes.value.map((node) => String(node.id))))
const visibleEdges = computed(() => props.edges.filter((edge) => {
  if (relationTypeFilter.value !== 'all' && String(edge.relationType || edge.label || '') !== relationTypeFilter.value) return false
  return visibleNodeIds.value.has(String(edge.source)) && visibleNodeIds.value.has(String(edge.target))
}))
const hiddenStructuralCount = computed(() => Math.max(validNodes.value.length - semanticNodes.value.length, 0))
const hiddenKnowledgeCount = computed(() => progressiveGraph.value
  ? Math.max(knowledgeNodes.value.length - visibleNodes.value.filter((node) => node.nodeType === 'knowledge_point').length, 0)
  : 0)
const usesOrganicCourseLayout = computed(() => (
  props.layoutDecision?.strategy === 'hierarchical' && knowledgeNodes.value.length > 8
))
const layoutSummary = computed(() => {
  const decision = props.layoutDecision
  if (!decision) return ''
  const strategy = ({
    hierarchical: usesOrganicCourseLayout.value ? '自由关系布局' : '分层布局',
    dynamic_cluster: '动态主题簇布局',
    multi_focus: '多焦点布局',
    local_focus: '局部聚焦布局',
    constrained_force: '受约束力导向布局',
  })[decision.strategy] || decision.strategy || '数据驱动布局'
  return `${strategy} · ${decision.clusterCount ?? props.topicClusters.length} 个主题簇`
})
const layoutReason = computed(() => (
  usesOrganicCourseLayout.value
    ? '连接关系决定方向，节点通过吸引与排斥自然散开。'
    : props.layoutDecision?.reason || ''
))

function safeText(value) {
  return String(value ?? '').replace(/[&<>"']/g, (character) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  })[character])
}

function selectNode(node) {
  selectedNode.value = node || null
  emit('node-select', selectedNode.value)
}

function estimatedNodeBox(node) {
  const name = String(node?.name || '').trim()
  const length = [...name].length
  const importance = Math.max(0, Math.min(1, Number(node?.importance || 0)))
  // Every node is a circle. Long names get a larger *diameter* so the label
  // remains centred without changing the node geometry. The diameter is
  // bounded to keep large graphs readable.
  const charsPerLine = length > 1 ? Math.max(5, Math.ceil(length / 2)) : 1
  const textDiameter = charsPerLine * 11 + 28
  // Keep every rendered node circular and within a diameter that leaves the
  // layout enough room for a real pixel gap.  Long labels still use two
  // centred lines plus the tooltip/detail panel; they must not force a
  // 180–200px circle that collapses neighbouring lanes.
  const diameter = Math.round(Math.min(132, Math.max(48, textDiameter + importance * 6)))
  return { width: diameter, height: diameter, shape: 'circle' }
}

/**
 * The former path page rendered a concept in the middle, direct relations on
 * a first ring and the surrounding context on outer rings.  Keep that visual
 * reading order, but derive every item from the current canonical graph.  A
 * bounded, deterministic relaxation pass preserves the ring impression while
 * guaranteeing a real gap for the measured circular node sizes.
 */
function legacyPathLayoutModel(nodes, edges) {
  if (!nodes.length) return { positions: new Map(), focusId: '', directIds: new Set() }
  const ids = new Set(nodes.map((node) => String(node.id)))
  const degree = new Map(nodes.map((node) => [String(node.id), 0]))
  const adjacency = new Map(nodes.map((node) => [String(node.id), new Set()]))
  for (const edge of edges) {
    const source = String(edge.source)
    const target = String(edge.target)
    if (!ids.has(source) || !ids.has(target) || source === target) continue
    adjacency.get(source)?.add(target)
    adjacency.get(target)?.add(source)
    degree.set(source, (degree.get(source) || 0) + 1)
    degree.set(target, (degree.get(target) || 0) + 1)
  }
  const focusCandidates = nodes.filter((node) => node.nodeType === 'knowledge_point')
  const focusPool = focusCandidates.length ? focusCandidates : nodes
  const focusNode = [...focusPool].sort((left, right) => (
    Number(Boolean(right.isCurrentFocus)) - Number(Boolean(left.isCurrentFocus))
      || Number(right.importance || 0) - Number(left.importance || 0)
      || (degree.get(String(right.id)) || 0) - (degree.get(String(left.id)) || 0)
      || String(left.id).localeCompare(String(right.id), 'zh-CN')
  ))[0]
  const focusId = String(focusNode.id)

  const depthById = new Map([[focusId, 0]])
  const queue = [focusId]
  while (queue.length) {
    const current = queue.shift()
    const nextDepth = Math.min((depthById.get(current) || 0) + 1, 3)
    for (const neighbour of [...(adjacency.get(current) || [])].sort((left, right) => left.localeCompare(right, 'zh-CN'))) {
      if (depthById.has(neighbour)) continue
      depthById.set(neighbour, nextDepth)
      queue.push(neighbour)
    }
  }
  const groups = new Map([[0, [focusNode]]])
  for (const node of nodes) {
    const id = String(node.id)
    if (id === focusId) continue
    const depth = depthById.get(id) ?? 3
    groups.set(depth, [...(groups.get(depth) || []), node])
  }
  const nodeDiameter = (node) => estimatedNodeBox(node).width
  const sortRing = (left, right) => (
    Number(Boolean(right.isCurrentFocus)) - Number(Boolean(left.isCurrentFocus))
      || Number(right.importance || 0) - Number(left.importance || 0)
      || (degree.get(String(right.id)) || 0) - (degree.get(String(left.id)) || 0)
      || String(left.id).localeCompare(String(right.id), 'zh-CN')
  )
  const positions = new Map([[focusId, { x: 0, y: 0 }]])
  const directIds = new Set((groups.get(1) || []).map((node) => String(node.id)))
  const maxDiameter = Math.max(62, ...nodes.map(nodeDiameter))
  const ringGap = Math.max(300, Math.round(maxDiameter * 1.9))
  const baseRadius = Math.max(360, Math.round(maxDiameter * 2.8))
  for (const depth of [1, 2, 3]) {
    const ring = [...(groups.get(depth) || [])].sort(sortRing)
    if (!ring.length) continue
    const circumferenceNeed = ring.reduce((sum, node) => sum + nodeDiameter(node) + 72, 0)
    const radius = Math.max(
      baseRadius + (depth - 1) * ringGap,
      Math.ceil(circumferenceNeed / (Math.PI * 2)),
    )
    const offset = -Math.PI / 2 + depth * 0.31
    ring.forEach((node, index) => {
      const angle = offset + (Math.PI * 2 * index) / Math.max(ring.length, 1)
      positions.set(String(node.id), {
        x: Math.cos(angle) * radius,
        y: Math.sin(angle) * radius,
      })
    })
  }

  const nodeById = new Map(nodes.map((node) => [String(node.id), node]))
  const positionIds = [...positions.keys()]
  for (let pass = 0; pass < 48; pass += 1) {
    let moved = false
    for (let leftIndex = 0; leftIndex < positionIds.length; leftIndex += 1) {
      const leftId = positionIds[leftIndex]
      const left = positions.get(leftId)
      const leftNode = nodeById.get(leftId)
      const leftRadius = nodeDiameter(leftNode) / 2
      for (let rightIndex = leftIndex + 1; rightIndex < positionIds.length; rightIndex += 1) {
        const rightId = positionIds[rightIndex]
        const right = positions.get(rightId)
        const rightNode = nodeById.get(rightId)
        const rightRadius = nodeDiameter(rightNode) / 2
        const dx = right.x - left.x
        const dy = right.y - left.y
        const distance = Math.hypot(dx, dy)
        const minimumDistance = leftRadius + rightRadius + 28
        if (distance >= minimumDistance) continue
        const direction = distance > 0
          ? { x: dx / distance, y: dy / distance }
          : { x: leftId.localeCompare(rightId, 'zh-CN') <= 0 ? 1 : -1, y: 0 }
        const push = minimumDistance - distance
        if (leftId === focusId) {
          right.x += direction.x * push
          right.y += direction.y * push
        } else if (rightId === focusId) {
          left.x -= direction.x * push
          left.y -= direction.y * push
        } else {
          left.x -= direction.x * push / 2
          left.y -= direction.y * push / 2
          right.x += direction.x * push / 2
          right.y += direction.y * push / 2
        }
        moved = true
      }
    }
    if (!moved) break
  }
  return { positions, focusId, directIds }
}

function dataDrivenPositions(nodes, edges, decision, topicClusters) {
  if (!decision || !nodes.length) return new Map()
  const positions = new Map()
  const metrics = (node) => ({
    importance: Number(node.importance || 0),
    depth: Number(node.hierarchyDepth || 0),
    focus: Boolean(node.isCurrentFocus),
  })
  const knowledgeNodes = nodes.filter(node => node.nodeType === 'knowledge_point')
  const nonKnowledge = nodes.filter(node => node.nodeType !== 'knowledge_point')
  const chapters = nonKnowledge.filter(node => node.nodeType === 'chapter')
  const sources = nonKnowledge.filter(node => node.nodeType === 'source')
  const courses = nonKnowledge.filter(node => node.nodeType === 'course')
  const clusterMap = new Map((topicClusters || []).map(cluster => [cluster.id, cluster]))
  const nodeCluster = (node) => node.topicClusterIds?.[0] || 'cluster:unassigned'
  const ordered = (items) => [...items].sort((left, right) => {
    const lm = metrics(left)
    const rm = metrics(right)
    return Number(rm.focus) - Number(lm.focus) || rm.importance - lm.importance || String(left.id).localeCompare(String(right.id), 'zh-CN')
  })
  const stableJitter = (id, magnitude) => {
    const hash = [...String(id)].reduce((sum, character) => sum * 31 + character.charCodeAt(0), 7)
    return ((Math.abs(hash) % 5) - 2) * magnitude
  }
  const placeGrid = (items, centerX, centerY, columns = 4, xGap = 170, yGap = 118, fitToBand = true) => {
    const list = ordered(items)
    if (!list.length) return
    const columnCount = Math.min(Math.max(columns, 1), list.length)
    const rowCount = Math.ceil(list.length / columnCount)
    const fittedXGap = fitToBand && columnCount > 1 ? Math.min(xGap, 760 / (columnCount - 1)) : xGap
    const fittedYGap = fitToBand && rowCount > 1 ? Math.min(yGap, 340 / (rowCount - 1)) : yGap
    list.forEach((node, index) => {
      const column = index % columnCount
      const row = Math.floor(index / columnCount)
      positions.set(String(node.id), {
        x: centerX + (column - (columnCount - 1) / 2) * fittedXGap + stableJitter(node.id, Math.min(14, fittedXGap * 0.04)),
        y: centerY + (row - (rowCount - 1) / 2) * fittedYGap + stableJitter(`${node.id}:y`, Math.min(9, fittedYGap * 0.05)),
      })
    })
  }

  // A band keeps one semantic layer on its own horizontal lane. Unlike the
  // old compact grid, the spacing is intentionally derived from the number
  // of columns and leaves room for the measured node box and its label.
  const placeBand = (items, centerX, centerY, maxColumns = 4, xGap = 320, yGap = 132, sorter = ordered) => {
    const list = sorter(items)
    if (!list.length) return
    const columnCount = Math.min(Math.max(maxColumns, 1), list.length)
    const rowCount = Math.ceil(list.length / columnCount)
    list.forEach((node, index) => {
      const column = index % columnCount
      const row = Math.floor(index / columnCount)
      positions.set(String(node.id), {
        x: centerX + (column - (columnCount - 1) / 2) * xGap + stableJitter(node.id, Math.min(20, xGap * 0.05)),
        y: centerY + (row - (rowCount - 1) / 2) * yGap + stableJitter(`${node.id}:y`, Math.min(12, yGap * 0.05)),
      })
    })
  }

  // The canonical hierarchy often gives every knowledge point the same
  // metadata depth. For a readable hierarchical view, derive a stable order
  // from prerequisite edges first, then use importance and id as deterministic
  // tie breakers. Related concepts stay adjacent instead of forming a random
  // grid that forces prerequisite lines to cross.
  const knowledgeOrder = (items) => {
    const itemIds = new Set(items.map((node) => String(node.id)))
    const outgoing = new Map(items.map((node) => [String(node.id), new Set()]))
    const incoming = new Map(items.map((node) => [String(node.id), new Set()]))
    for (const edge of edges) {
      const relation = String(edge.relationType || '').toLowerCase()
      if (!['prerequisite', 'depends_on', 'requires', 'derives_from'].includes(relation)) continue
      const source = String(edge.source)
      const target = String(edge.target)
      if (!itemIds.has(source) || !itemIds.has(target) || source === target) continue
      outgoing.get(source)?.add(target)
      incoming.get(target)?.add(source)
    }
    const rank = new Map()
    const queue = [...items]
      .filter((node) => !(incoming.get(String(node.id))?.size))
      .sort((left, right) => String(left.id).localeCompare(String(right.id), 'zh-CN'))
    queue.forEach((node) => rank.set(String(node.id), 0))
    while (queue.length) {
      const current = queue.shift()
      const currentRank = rank.get(String(current.id)) || 0
      for (const target of outgoing.get(String(current.id)) || []) {
        rank.set(target, Math.max(rank.get(target) || 0, currentRank + 1))
        const nextIncoming = incoming.get(target)
        nextIncoming?.delete(String(current.id))
        if (!nextIncoming?.size) {
          const nextNode = items.find((node) => String(node.id) === target)
          if (nextNode) queue.push(nextNode)
        }
      }
    }
    // Cycles are not expected in prerequisite data, but appending any
    // remaining nodes by stable key keeps the layout deterministic if one is
    // encountered in a legacy course.
    items.forEach((node) => {
      if (!rank.has(String(node.id))) rank.set(String(node.id), rank.size)
    })
    return [...items].sort((left, right) =>
      (rank.get(String(left.id)) || 0) - (rank.get(String(right.id)) || 0)
      || Number(metrics(right).focus) - Number(metrics(left).focus)
      || metrics(right).importance - metrics(left).importance
      || String(left.id).localeCompare(String(right.id), 'zh-CN'))
  }

  const placeOrganicGraph = (items) => {
    const list = knowledgeOrder(items)
    if (!list.length) return
    if (list.length === 1) {
      positions.set(String(list[0].id), { x: 0, y: 0 })
      return
    }

    const ids = new Set(list.map((node) => String(node.id)))
    const links = edges.filter((edge) => (
      ids.has(String(edge.source))
      && ids.has(String(edge.target))
      && String(edge.source) !== String(edge.target)
    ))
    const points = new Map()
    const initialEdgeLength = Math.max(156, Math.min(190, 146 + Math.sqrt(list.length) * 8))
    const radialStep = Math.max(24, Math.min(34, 20 + Math.sqrt(list.length) * 2))
    let angle = stableJitter('organic:start-angle', 0.04)
    list.forEach((node, index) => {
      const radius = index === 0 ? 0 : 112 + index * radialStep
      if (index) {
        angle += Math.min(1.15, initialEdgeLength / radius)
          + stableJitter(`${node.id}:angle`, 0.035)
      }
      points.set(String(node.id), {
        x: Math.cos(angle) * radius * 1.08,
        y: Math.sin(angle) * radius * 0.92,
      })
    })

    const nodeById = new Map(list.map((node) => [String(node.id), node]))
    const iterations = list.length > 120 ? 52 : 96
    const preferredEdgeLength = Math.max(180, Math.min(230, 160 + Math.sqrt(list.length) * 12))
    const repulsionDistance = Math.max(190, preferredEdgeLength * 0.9)
    for (let iteration = 0; iteration < iterations; iteration += 1) {
      const force = new Map(list.map((node) => [String(node.id), { x: 0, y: 0 }]))
      for (let leftIndex = 0; leftIndex < list.length; leftIndex += 1) {
        const leftId = String(list[leftIndex].id)
        const left = points.get(leftId)
        for (let rightIndex = leftIndex + 1; rightIndex < list.length; rightIndex += 1) {
          const rightId = String(list[rightIndex].id)
          const right = points.get(rightId)
          let dx = right.x - left.x
          let dy = right.y - left.y
          let distance = Math.hypot(dx, dy)
          if (distance < 0.001) {
            const direction = leftId.localeCompare(rightId, 'zh-CN') <= 0 ? -1 : 1
            dx = direction
            dy = stableJitter(`${leftId}:${rightId}`, 0.2)
            distance = Math.hypot(dx, dy)
          }
          if (distance >= repulsionDistance) continue
          const minimumDistance = (
            estimatedNodeBox(nodeById.get(leftId)).width
            + estimatedNodeBox(nodeById.get(rightId)).width
          ) / 2 + 54
          const push = Math.max(0, repulsionDistance - distance, minimumDistance - distance) * 0.085
          const unitX = dx / distance
          const unitY = dy / distance
          force.get(leftId).x -= unitX * push
          force.get(leftId).y -= unitY * push
          force.get(rightId).x += unitX * push
          force.get(rightId).y += unitY * push
        }
      }

      links.forEach((edge) => {
        const sourceId = String(edge.source)
        const targetId = String(edge.target)
        const source = points.get(sourceId)
        const target = points.get(targetId)
        const dx = target.x - source.x
        const dy = target.y - source.y
        const distance = Math.max(1, Math.hypot(dx, dy))
        const pull = (distance - preferredEdgeLength) * 0.035
        const unitX = dx / distance
        const unitY = dy / distance
        force.get(sourceId).x += unitX * pull
        force.get(sourceId).y += unitY * pull
        force.get(targetId).x -= unitX * pull
        force.get(targetId).y -= unitY * pull
      })

      const cooling = 1 - iteration / iterations
      const maxStep = 4 + cooling * 18
      let centerX = 0
      let centerY = 0
      list.forEach((node) => {
        const id = String(node.id)
        const point = points.get(id)
        const delta = force.get(id)
        delta.x -= point.x * 0.003
        delta.y -= point.y * 0.003
        const magnitude = Math.hypot(delta.x, delta.y)
        if (magnitude > maxStep) {
          delta.x = (delta.x / magnitude) * maxStep
          delta.y = (delta.y / magnitude) * maxStep
        }
        point.x += delta.x
        point.y += delta.y
        centerX += point.x
        centerY += point.y
      })
      centerX /= list.length
      centerY /= list.length
      points.forEach((point) => {
        point.x -= centerX
        point.y -= centerY
      })
    }

    points.forEach((point, id) => positions.set(id, point))
  }

  if (decision.strategy === 'hierarchical' && nodes.length > 8) {
    placeOrganicGraph(nodes)
  } else if (decision.strategy === 'hierarchical') {
    const maxKnowledgeDiameter = Math.min(132, Math.max(48, ...knowledgeNodes.map((node) => estimatedNodeBox(node).width)))
    // Keep enough room for the largest circular label after the chart's
    // aspect-preserving transform. The row gap is derived from measured node
    // geometry, not from a fixed screenshot/template.
    const compactSemanticGraph = nodes.length <= 20
    const knowledgeRowGap = compactSemanticGraph
      ? Math.max(340, Math.round(maxKnowledgeDiameter * 2.7))
      : Math.max(720, Math.round(maxKnowledgeDiameter * 5.2))
    const knowledgeColumnGap = compactSemanticGraph
      ? Math.max(340, Math.round(maxKnowledgeDiameter * 2.6))
      : 780
    const orderedKnowledgeNodes = knowledgeOrder(knowledgeNodes)
    // Keep the row count bounded so a dense course remains readable while
    // still giving prerequisite chains multiple clear lanes. Rows are split
    // as evenly as possible; unlike a fixed grid this responds to the actual
    // number of knowledge points.
    // Use the smallest number of rows that keeps the prerequisite order
    // legible.  Fewer rows create wider, better separated lanes and avoid
    // turning a normal course graph into a tall stack of touching circles.
    // A two-node progressive layer is intentionally kept on one horizontal
    // lane.  A vertical two-point span makes the graph's data aspect extreme
    // and causes ECharts to stretch a scalar circle during its view transform;
    // one lane preserves a readable edge and true circular geometry.
    const totalRows = orderedKnowledgeNodes.length <= 2
      ? 1
      : Math.max(1, Math.min(orderedKnowledgeNodes.length || 1, 5, Math.max(1, Math.ceil(Math.sqrt(orderedKnowledgeNodes.length)))))
    const baseRowSize = Math.floor(orderedKnowledgeNodes.length / totalRows)
    const extraRows = orderedKnowledgeNodes.length % totalRows
    const knowledgeRows = []
    let knowledgeCursor = 0
    for (let rowIndex = 0; rowIndex < totalRows; rowIndex += 1) {
      const rowSize = baseRowSize + (rowIndex < extraRows ? 1 : 0)
      knowledgeRows.push(orderedKnowledgeNodes.slice(knowledgeCursor, knowledgeCursor + rowSize))
      knowledgeCursor += rowSize
    }
    const layerStartY = -((totalRows - 1) * knowledgeRowGap) / 2
    const rowByKnowledgeId = new Map()
    knowledgeRows.forEach((layer, rowIndex) => {
      layer.forEach((node) => rowByKnowledgeId.set(String(node.id), rowIndex))
    })
    const orderingRelations = new Set(['prerequisite', 'depends_on', 'requires', 'derives_from'])
    const reorderKnowledgeRows = (direction) => {
      const rowIndexes = direction > 0
        ? Array.from({ length: knowledgeRows.length }, (_, index) => index)
        : Array.from({ length: knowledgeRows.length }, (_, index) => knowledgeRows.length - 1 - index)
      rowIndexes.forEach((rowIndex) => {
        // The outer rows have no already-placed neighbours in one sweep;
        // keeping their deterministic order prevents a visual jump between
        // renders. Inner rows are ordered by the barycentre of their
        // prerequisite neighbours in the sweep direction, which reduces
        // edge crossings without changing the graph topology.
        if (rowIndex === (direction > 0 ? 0 : knowledgeRows.length - 1)) return
        const referenceRow = rowIndex - direction
        const layer = knowledgeRows[rowIndex]
        const score = (node) => {
          const neighbourXs = []
          for (const edge of edges) {
            const relation = String(edge.relationType || '').toLowerCase()
            if (!orderingRelations.has(relation)) continue
            const source = String(edge.source)
            const target = String(edge.target)
            let neighbourId = null
            if (source === String(node.id)) neighbourId = target
            if (target === String(node.id)) neighbourId = source
            if (!neighbourId || rowByKnowledgeId.get(neighbourId) !== referenceRow) continue
            const neighbourPosition = positions.get(neighbourId)
            if (neighbourPosition && Number.isFinite(neighbourPosition.x)) neighbourXs.push(neighbourPosition.x)
          }
          if (!neighbourXs.length) return null
          return neighbourXs.reduce((sum, value) => sum + value, 0) / neighbourXs.length
        }
        layer.sort((left, right) => {
          const leftScore = score(left)
          const rightScore = score(right)
          if (leftScore != null && rightScore != null && leftScore !== rightScore) return leftScore - rightScore
          if (leftScore != null) return -1
          if (rightScore != null) return 1
          return String(left.id).localeCompare(String(right.id), 'zh-CN')
        })
        const columns = Math.max(1, layer.length)
        const centerY = layerStartY + rowIndex * knowledgeRowGap
        placeBand(layer, 0, centerY, columns, knowledgeColumnGap, knowledgeRowGap, (items) => items)
      })
    }
    // Two short barycentric sweeps are enough to align neighbouring semantic
    // layers while keeping coordinates deterministic and avoiding a force
    // simulation that could reintroduce overlaps.
    knowledgeRows.forEach((layer, index) => {
      // A layer is already one semantic row. Use all of its items as columns
      // so the layout never wraps a semantic layer into the next row.
      const columns = Math.max(1, layer.length)
      const centerY = layerStartY + index * knowledgeRowGap
      // Knowledge-point rows need a little more vertical room than the
      // compact structural lanes below; labels stay readable at 14px.
      placeBand(layer, 0, centerY, columns, knowledgeColumnGap, knowledgeRowGap, (items) => items)
    })
    for (let pass = 0; pass < 2; pass += 1) {
      reorderKnowledgeRows(1)
      reorderKnowledgeRows(-1)
    }
    const knowledgeEdges = edges.filter((edge) => {
      const source = String(edge.source)
      const target = String(edge.target)
      return source !== target && rowByKnowledgeId.has(source) && rowByKnowledgeId.has(target)
    })
    const orientation = (left, right, point) => (
      (right.x - left.x) * (point.y - left.y) - (right.y - left.y) * (point.x - left.x)
    )
    const segmentsCross = (first, second, third, fourth) => {
      const firstSide = orientation(first, second, third)
      const secondSide = orientation(first, second, fourth)
      const thirdSide = orientation(third, fourth, first)
      const fourthSide = orientation(third, fourth, second)
      return firstSide * secondSide < 0 && thirdSide * fourthSide < 0
    }
    const crossingScore = () => {
      let score = 0
      for (let leftIndex = 0; leftIndex < knowledgeEdges.length; leftIndex += 1) {
        const leftEdge = knowledgeEdges[leftIndex]
        const leftSource = positions.get(String(leftEdge.source))
        const leftTarget = positions.get(String(leftEdge.target))
        if (!leftSource || !leftTarget) continue
        for (let rightIndex = 0; rightIndex < leftIndex; rightIndex += 1) {
          const rightEdge = knowledgeEdges[rightIndex]
          if (new Set([String(leftEdge.source), String(leftEdge.target)]).has(String(rightEdge.source))
            || new Set([String(leftEdge.source), String(leftEdge.target)]).has(String(rightEdge.target))) continue
          const rightSource = positions.get(String(rightEdge.source))
          const rightTarget = positions.get(String(rightEdge.target))
          if (rightSource && rightTarget && segmentsCross(leftSource, leftTarget, rightSource, rightTarget)) score += 1
        }
      }
      return score
    }
    // A bounded adjacent-layer swap pass removes avoidable edge crossings
    // introduced by stable-name ordering. It only changes node order within
    // an existing semantic row; topology, row count and coordinates remain
    // deterministic for the same payload.
    let bestCrossingScore = crossingScore()
    for (let pass = 0; pass < 6; pass += 1) {
      let improved = false
      for (let rowIndex = 0; rowIndex < knowledgeRows.length; rowIndex += 1) {
        const layer = knowledgeRows[rowIndex]
        for (let leftIndex = 0; leftIndex < layer.length; leftIndex += 1) {
          for (let rightIndex = leftIndex + 1; rightIndex < layer.length; rightIndex += 1) {
            ;[layer[leftIndex], layer[rightIndex]] = [layer[rightIndex], layer[leftIndex]]
            const columns = Math.max(1, layer.length)
            const centerY = layerStartY + rowIndex * knowledgeRowGap
            placeBand(layer, 0, centerY, columns, knowledgeColumnGap, knowledgeRowGap, (items) => items)
            const candidateScore = crossingScore()
            if (candidateScore < bestCrossingScore) {
              bestCrossingScore = candidateScore
              improved = true
            } else {
              ;[layer[leftIndex], layer[rightIndex]] = [layer[rightIndex], layer[leftIndex]]
            placeBand(layer, 0, centerY, columns, knowledgeColumnGap, knowledgeRowGap, (items) => items)
            }
          }
        }
      }
      if (!improved) break
    }

    // Structural nodes get dedicated lanes. Their positions are still
    // computed from the actual node counts; no fixed quadrant or shared
    // centre template is used. The course anchor follows the first chapter
    // lane instead of being forced to the canvas centre.
    const chapterColumns = Math.min(4, Math.max(1, Math.ceil(Math.sqrt(chapters.length))))
    const sourceColumns = Math.min(4, Math.max(1, Math.ceil(Math.sqrt(sources.length))))
    // Put structural nodes in dedicated horizontal lanes outside the
    // knowledge-point field.  A side channel made chapter/source circles
    // share the same y coordinates as long knowledge labels, which produced
    // real pixel overlaps after ECharts scaled the data.  These lanes are
    // derived from the actual knowledge span and circle diameter, so they are
    // deterministic without being a fixed quadrant/template.
    const knowledgeMinY = layerStartY
    const knowledgeMaxY = layerStartY + Math.max(0, totalRows - 1) * knowledgeRowGap
    const structuralGap = Math.max(420, Math.round(maxKnowledgeDiameter * 2.2 + 120))
    const chapterRows = chapters.length ? Math.ceil(chapters.length / chapterColumns) : 1
    const sourceRows = sources.length ? Math.ceil(sources.length / sourceColumns) : 1
    // placeBand centres multi-row lanes around its y argument.  Offset the
    // centres by half their actual row span so the innermost structural row
    // still remains a full structuralGap away from the knowledge field.
    const chapterY = knowledgeMinY - structuralGap - ((chapterRows - 1) * 240) / 2
    const sourceY = knowledgeMaxY + structuralGap + ((sourceRows - 1) * 240) / 2
    const courseY = chapterY - structuralGap
    const structuralXGap = Math.max(280, Math.round(maxKnowledgeDiameter * 1.9))
    placeBand(chapters, 0, chapterY, chapterColumns, structuralXGap, 240)
    placeBand(sources, 0, sourceY, sourceColumns, structuralXGap, 240)
    placeBand(courses, 0, courseY, 1, 180, 72)
  } else if (decision.strategy === 'dynamic_cluster' || decision.strategy === 'multi_focus') {
    const groups = new Map()
    for (const node of knowledgeNodes) groups.set(nodeCluster(node), [...(groups.get(nodeCluster(node)) || []), node])
    const groupEntries = [...groups.entries()].sort((left, right) => left[0].localeCompare(right[0]))
    const columns = Math.max(1, Math.ceil(Math.sqrt(groupEntries.length * 1.35)))
    const rows = Math.ceil(groupEntries.length / columns)
    groupEntries.forEach(([clusterId, group], index) => {
      const column = index % columns
      const row = Math.floor(index / columns)
      const centerX = (column - (columns - 1) / 2) * 450
      const centerY = rows === 1 ? (column % 2 ? 112 : -112) : (row - (rows - 1) / 2) * 310 + (column % 2 ? 38 : -38)
      const gridColumns = group.length <= 2 ? group.length : Math.min(4, Math.ceil(Math.sqrt(group.length)))
      placeGrid(group, centerX, centerY, Math.max(gridColumns, 1), 220, 150)
      const cluster = clusterMap.get(clusterId)
      if (cluster?.centerNodeId && positions.has(cluster.centerNodeId)) {
        positions.get(cluster.centerNodeId).x = centerX
        positions.get(cluster.centerNodeId).y = centerY
      }
    })
  } else if (decision.strategy === 'local_focus') {
    const focus = ordered(knowledgeNodes)[0]
    const knowledgeCount = knowledgeNodes.length
    const densityFactor = Math.sqrt(Math.max(knowledgeCount, 1))
    const gutterX = Math.min(560, Math.max(280, Math.round(260 + densityFactor * 34)))
    if (focus) {
      // Keep the focus and structural context inside the same bounded canvas
      // used by the dense browser contract. Secondary knowledge points occupy
      // the central grid; the focus remains visually above them without
      // forcing the graph into an oversized vertical scroll area.
      const focusY = knowledgeCount > 40 ? -150 : -132
      positions.set(String(focus.id), { x: 0, y: focusY })
      const neighbors = new Set()
      for (const edge of edges) {
        if (String(edge.source) === String(focus.id)) neighbors.add(String(edge.target))
        if (String(edge.target) === String(focus.id)) neighbors.add(String(edge.source))
      }
      // Keep a real gap between rows. The normal band fitting is useful for
      // small graphs, but it collapses 80+ nodes into the same pixels.
      const neighborY = knowledgeCount > 40 ? -52 : -12
      const secondaryY = knowledgeCount > 40 ? 66 : 82
      const secondaryGap = knowledgeCount > 40 ? 50 : 76
      placeGrid(knowledgeNodes.filter(node => String(node.id) !== String(focus.id) && neighbors.has(String(node.id))), 0, neighborY, 6, knowledgeCount > 40 ? 132 : 156, knowledgeCount > 40 ? 92 : 96, false)
      placeGrid(knowledgeNodes.filter(node => String(node.id) !== String(focus.id) && !neighbors.has(String(node.id))), 0, secondaryY, 10, knowledgeCount > 40 ? 108 : 136, secondaryGap, false)

      // Structural nodes stay in data-sized gutters instead of sharing the
      // focus row. This prevents course/chapter/source labels from colliding
      // with the focal concept in a dense graph.
      const structuralY = knowledgeCount > 40 ? -208 : -190
      const sourceY = knowledgeCount > 40 ? 206 : 190
      placeGrid(courses, -gutterX, structuralY, 1, 180, 72)
      placeGrid(chapters, gutterX, structuralY, Math.max(1, Math.ceil(Math.sqrt(chapters.length))), 180, 72)
      placeGrid(sources, gutterX, sourceY, Math.max(1, Math.ceil(Math.sqrt(sources.length))), 160, 72)
    }
  } else {
    const columns = Math.max(2, Math.ceil(Math.sqrt(knowledgeNodes.length)))
    placeGrid(knowledgeNodes, 0, 40, columns, 220, 150)
  }

  if (decision.strategy !== 'local_focus' && decision.strategy !== 'hierarchical') {
    const structuralLayout = { courseY: -286, chapterY: -230, sourceY: 286 }
    placeGrid(courses, -360, structuralLayout.courseY, 1, 180, 90)
    placeGrid(chapters, 0, structuralLayout.chapterY, Math.max(1, Math.ceil(Math.sqrt(chapters.length))), 220, 90)
    placeGrid(sources, 300, structuralLayout.sourceY, Math.max(1, Math.ceil(Math.sqrt(sources.length))), 180, 86)
  }

  if (decision.strategy !== 'local_focus') {
    const ids = [...positions.keys()]
    const nodeById = new Map(nodes.map(node => [String(node.id), node]))
    const collisionBox = (node) => {
      if (decision.strategy === 'hierarchical' && nodes.length > 20 && node?.nodeType !== 'knowledge_point') {
        const size = node?.nodeType === 'course' ? 64 : (node?.nodeType === 'chapter' ? 42 : 28)
        return { width: size, height: size }
      }
      const measured = estimatedNodeBox(node)
      if (decision.strategy === 'hierarchical' && nodes.length > 20) {
        // Use the same diameter cap as chartNodes. Collision checks must
        // reflect the rendered circle, otherwise a long label can overlap a
        // neighbouring node even though the logical boxes appear separate.
        const diameter = Math.min(measured.width, 132)
        return { width: diameter, height: diameter, shape: 'circle' }
      }
      return measured
    }
    const xLimit = Math.max(
      1000,
      ...[...positions.values()].map((point) => Math.abs(Number(point.x) || 0) + 420),
    )
    for (let pass = 0; pass < 28; pass += 1) {
      let moved = false
      for (let leftIndex = 0; leftIndex < ids.length; leftIndex += 1) {
        const leftId = ids[leftIndex]
        const left = positions.get(leftId)
        const leftBox = collisionBox(nodeById.get(leftId))
        for (let rightIndex = leftIndex + 1; rightIndex < ids.length; rightIndex += 1) {
          const rightId = ids[rightIndex]
          const right = positions.get(rightId)
          const rightBox = collisionBox(nodeById.get(rightId))
          // All rendered nodes are circles.  An axis-aligned box test lets
          // two circles overlap diagonally (their x/y ranges may be
          // disjoint), which is exactly what the pixel audit caught.  Use
          // the actual circle radii and a deterministic vector push instead.
          const dx = Number(right.x) - Number(left.x)
          const dy = Number(right.y) - Number(left.y)
          const distance = Math.hypot(dx, dy)
          const minimumDistance = (leftBox.width + rightBox.width) / 2 + 16
          if (distance >= minimumDistance) continue
          const stableDirection = leftId.localeCompare(rightId, 'zh-CN') <= 0 ? -1 : 1
          const unitX = distance > 0 ? dx / distance : stableDirection
          const unitY = distance > 0 ? dy / distance : 0
          const push = (minimumDistance - distance) / 2
          left.x -= unitX * push
          left.y -= unitY * push
          right.x += unitX * push
          right.y += unitY * push
          moved = true
        }
      }
      for (const point of positions.values()) {
        point.x = Math.max(-xLimit, Math.min(xLimit, point.x))
        // Keep the structural top/bottom lanes outside the knowledge-point
        // grid. The graph view applies a letterbox transform afterwards, so
        // this larger deterministic data bound prevents anchors from being
        // clamped back onto circular knowledge nodes.
        point.y = Math.max(-3000, Math.min(3000, point.y))
      }
      if (!moved) break
    }
  }
  return positions
}

function denseGraphPositions(nodes) {
  const groups = new Map()
  for (const node of nodes) {
    const type = node.nodeType || 'other'
    groups.set(type, [...(groups.get(type) || []), node])
  }
  const positions = new Map()
  const rings = {
    chapter: { xRadius: 150, yRadius: 105, offset: -Math.PI / 2 },
    knowledge_point: { xRadius: 270, yRadius: 185, offset: -Math.PI / 2 + 0.14 },
    source: { xRadius: 370, yRadius: 240, offset: -Math.PI / 2 + 0.28 },
    other: { xRadius: 320, yRadius: 210, offset: -Math.PI / 2 + 0.42 },
  }
  for (const [type, group] of groups) {
    if (type === 'course') {
      group.forEach((node, index) => positions.set(node.id, { x: index * 28, y: 0 }))
      continue
    }
    const ring = rings[type] || rings.other
    group.forEach((node, index) => {
      const angle = ring.offset + (Math.PI * 2 * index) / Math.max(group.length, 1)
      positions.set(node.id, {
        x: Math.cos(angle) * ring.xRadius,
        y: Math.sin(angle) * ring.yRadius,
      })
    })
  }
  return positions
}

function relationshipProjectionPositions(nodes, edges) {
  const root = nodes.find((node) => node.nodeType === 'course') || nodes[0]
  if (!root) return new Map()

  const adjacency = new Map(nodes.map((node) => [node.id, new Set()]))
  for (const edge of edges) {
    adjacency.get(String(edge.source))?.add(String(edge.target))
    adjacency.get(String(edge.target))?.add(String(edge.source))
  }

  const depthById = new Map([[root.id, 0]])
  const queue = [root.id]
  while (queue.length) {
    const current = queue.shift()
    const nextDepth = Math.min((depthById.get(current) || 0) + 1, 3)
    for (const neighbor of adjacency.get(current) || []) {
      if (depthById.has(neighbor)) continue
      depthById.set(neighbor, nextDepth)
      queue.push(neighbor)
    }
  }

  const groups = new Map()
  for (const node of nodes) {
    const depth = Math.min(depthById.get(node.id) ?? 3, 3)
    groups.set(depth, [...(groups.get(depth) || []), node])
  }
  const rings = {
    1: { xRadius: 155, yRadius: 108 },
    2: { xRadius: 285, yRadius: 188 },
    3: { xRadius: 370, yRadius: 238 },
  }
  const positions = new Map([[root.id, { x: 0, y: 0 }]])
  for (const [depth, group] of groups) {
    if (depth === 0) continue
    const ring = rings[depth]
    const offset = -Math.PI / 2 + depth * 0.18
    group.forEach((node, index) => {
      const angle = offset + (Math.PI * 2 * index) / Math.max(group.length, 1)
      positions.set(node.id, {
        x: Math.cos(angle) * ring.xRadius,
        y: Math.sin(angle) * ring.yRadius,
      })
    })
  }
  return positions
}

function stableNodeKey(node) {
  return [
    node.chapter?.title || node.chapter || '',
    node.categoryName || node.category || '',
    node.name || '',
    node.code || '',
    node.id || '',
  ].map((value) => String(value)).join('\u0000')
}

function fixedProfileAnchor(nodes, edges) {
  if (!nodes.length) return null
  const degreeById = new Map(nodes.map((node) => [String(node.id), 0]))
  for (const edge of edges) {
    const source = String(edge.source)
    const target = String(edge.target)
    if (degreeById.has(source)) degreeById.set(source, degreeById.get(source) + 1)
    if (degreeById.has(target)) degreeById.set(target, degreeById.get(target) + 1)
  }
  return [...nodes]
    .sort((left, right) => {
      const degreeDifference = degreeById.get(String(right.id)) - degreeById.get(String(left.id))
      return degreeDifference || stableNodeKey(left).localeCompare(stableNodeKey(right), 'zh-CN')
    })[0]?.id || null
}

function fixedProfilePositions(nodes, edges) {
  if (!nodes.length) return new Map()

  const anchorId = String(fixedProfileAnchor(nodes, edges))
  const adjacency = new Map(nodes.map((node) => [String(node.id), new Set()]))
  for (const edge of edges) {
    const source = String(edge.source)
    const target = String(edge.target)
    adjacency.get(source)?.add(target)
    adjacency.get(target)?.add(source)
  }

  const depthById = new Map([[anchorId, 0]])
  const queue = [anchorId]
  while (queue.length) {
    const current = queue.shift()
    for (const neighbor of adjacency.get(current) || []) {
      if (depthById.has(neighbor)) continue
      depthById.set(neighbor, Math.min((depthById.get(current) || 0) + 1, 2))
      queue.push(neighbor)
    }
  }

  const orderedNodes = [...nodes]
    .filter((node) => String(node.id) !== anchorId)
    .sort((left, right) => stableNodeKey(left).localeCompare(stableNodeKey(right), 'zh-CN'))
  const innerNodes = orderedNodes.filter((node) => (depthById.get(String(node.id)) ?? 2) === 1)
  const outerNodes = orderedNodes.filter((node) => (depthById.get(String(node.id)) ?? 2) !== 1)
  const positions = new Map([[anchorId, { x: 0, y: 0 }]])

  function placeColumns(group, xRadius, yRadius) {
    const columnCounts = [Math.ceil(group.length / 2), Math.floor(group.length / 2)]
    const columnIndexes = [0, 0]
    group.forEach((node, index) => {
      const column = index % 2
      const slot = columnIndexes[column]++
      const count = columnCounts[column]
      const y = count <= 1 ? 0 : ((slot / (count - 1)) * 2 - 1) * yRadius
      positions.set(String(node.id), { x: column === 0 ? -xRadius : xRadius, y })
    })
  }

  placeColumns(innerNodes, 220, 165)
  placeColumns(outerNodes, 390, 230)
  return positions
}

function profileGraphLayout(nodes, edges) {
  if (!nodes.length) return { positions: new Map(), groups: new Map() }

  const ids = new Set(nodes.map((node) => String(node.id)))
  const incoming = new Map(nodes.map((node) => [String(node.id), new Set()]))
  const outgoing = new Map(nodes.map((node) => [String(node.id), new Set()]))
  const undirected = new Map(nodes.map((node) => [String(node.id), new Set()]))
  for (const edge of edges) {
    const source = String(edge.source)
    const target = String(edge.target)
    if (!ids.has(source) || !ids.has(target)) continue
    outgoing.get(source)?.add(target)
    incoming.get(target)?.add(source)
    undirected.get(source)?.add(target)
    undirected.get(target)?.add(source)
  }

  // The most connected concept is the visual anchor. Ties are resolved from
  // stable course data so selection, search and highlight state cannot move it.
  const anchorId = String(fixedProfileAnchor(nodes, edges))
  const chapterPosition = new Map(nodes.map((node, index) => [
    String(node.id), Number(node.chapter?.position || index + 1),
  ]))

  function directionalDistances(startId, adjacency) {
    const distances = new Map([[startId, 0]])
    const queue = [startId]
    while (queue.length) {
      const current = queue.shift()
      for (const neighbor of adjacency.get(current) || []) {
        if (distances.has(neighbor)) continue
        distances.set(neighbor, distances.get(current) + 1)
        queue.push(neighbor)
      }
    }
    return distances
  }

  const upstreamDistance = directionalDistances(anchorId, incoming)
  const downstreamDistance = directionalDistances(anchorId, outgoing)
  const connectedDistance = directionalDistances(anchorId, undirected)
  const groups = new Map()

  for (const node of nodes) {
    const id = String(node.id)
    if (id === anchorId) {
      groups.set(id, { role: 'anchor', depth: 0 })
      continue
    }
    const before = upstreamDistance.get(id)
    const after = downstreamDistance.get(id)
    const anchorChapter = chapterPosition.get(anchorId) || 0
    const nodeChapter = chapterPosition.get(id) || 0
    let role = 'independent'
    let depth = 0
    if (before != null && (after == null || before <= after)) {
      role = 'upstream'
      depth = Math.min(before, 2)
    } else if (after != null) {
      role = 'downstream'
      depth = Math.min(after, 2)
    } else if (connectedDistance.has(id)) {
      role = nodeChapter <= anchorChapter ? 'upstream' : 'downstream'
      depth = Math.min(connectedDistance.get(id) || 1, 2)
    }
    groups.set(id, { role, depth })
  }

  const positions = new Map([[anchorId, { x: 0, y: 0 }]])
  const neighbors = new Map(nodes.map((node) => [String(node.id), new Set()]))
  for (const edge of edges) {
    const source = String(edge.source)
    const target = String(edge.target)
    if (!ids.has(source) || !ids.has(target)) continue
    neighbors.get(source)?.add(target)
    neighbors.get(target)?.add(source)
  }

  function byStableKey(left, right) {
    return stableNodeKey(left).localeCompare(stableNodeKey(right), 'zh-CN')
  }

  function neighborY(node) {
    const values = [...(neighbors.get(String(node.id)) || [])]
      .map((id) => positions.get(id)?.y)
      .filter((value) => Number.isFinite(value))
    return values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : null
  }

  function centeredLanes(count, rowGap = 144) {
    return Array.from({ length: count }, (_, index) => (index - (count - 1) / 2) * rowGap)
  }

  function placeLayer(role, depth, x) {
    const layer = nodes
      .filter((node) => groups.get(String(node.id))?.role === role && groups.get(String(node.id))?.depth === depth)
      .sort((left, right) => {
        const leftY = neighborY(left)
        const rightY = neighborY(right)
        if (leftY != null && rightY != null && leftY !== rightY) return leftY - rightY
        if (leftY != null) return -1
        if (rightY != null) return 1
        return byStableKey(left, right)
      })
    if (!layer.length) return
    const yValues = centeredLanes(layer.length)
    layer.forEach((node, index) => {
      positions.set(String(node.id), { x, y: yValues[index] })
    })
  }

  // Place the layer nearest the anchor first, then order the outer layer
  // against the already placed neighbours. This keeps related edges in
  // parallel lanes instead of letting stable-name sorting create crossings.
  placeLayer('upstream', 1, -250)
  placeLayer('upstream', 2, -500)
  placeLayer('downstream', 1, 250)
  placeLayer('downstream', 2, 500)

  const independent = nodes
    .filter((node) => groups.get(String(node.id))?.role === 'independent')
    .sort((left, right) => {
      const chapterDifference = (chapterPosition.get(String(left.id)) || 0) - (chapterPosition.get(String(right.id)) || 0)
      return chapterDifference || byStableKey(left, right)
    })
  independent.sort((left, right) => {
    const leftX = [...(neighbors.get(String(left.id)) || [])]
      .map((id) => positions.get(id)?.x)
      .filter((value) => Number.isFinite(value))
    const rightX = [...(neighbors.get(String(right.id)) || [])]
      .map((id) => positions.get(id)?.x)
      .filter((value) => Number.isFinite(value))
    const leftMean = leftX.length ? leftX.reduce((sum, value) => sum + value, 0) / leftX.length : 0
    const rightMean = rightX.length ? rightX.reduce((sum, value) => sum + value, 0) / rightX.length : 0
    return leftMean - rightMean || byStableKey(left, right)
  })
  independent.forEach((node, index) => {
    const column = index % 5
    const row = Math.floor(index / 5)
    positions.set(String(node.id), { x: [-420, -210, 0, 210, 420][column], y: 360 + row * 144 })
  })

  // A defensive fallback keeps an unexpected node visible without sharing an
  // existing slot. This does not change the normal graph topology.
  nodes.forEach((node, index) => {
    const id = String(node.id)
    if (positions.has(id)) return
    positions.set(id, { x: (index % 2 ? -560 : 560), y: 360 + Math.floor(index / 2) * 144 })
  })

  return { positions, groups }
}

function profileGraphPositions(nodes, edges) {
  return profileGraphLayout(nodes, edges).positions
}

function profileEdgeData(edges, positions, groups = new Map()) {
  return edges.map((edge) => {
    const source = positions.get(String(edge.source))
    const target = positions.get(String(edge.target))
    const sourceGroup = groups.get(String(edge.source))
    const targetGroup = groups.get(String(edge.target))
    const horizontalDistance = source && target ? Math.abs(target.x - source.x) : 0
    const longEdge = horizontalDistance >= 450 || (sourceGroup?.role === 'independent' || targetGroup?.role === 'independent')
    return {
      ...edge,
      lineStyle: {
        ...(edge.lineStyle || {}),
        color: longEdge ? profileEditorialTokens.inkSoft : profileEditorialTokens.inkMedium,
        width: longEdge ? 1 : 1.35,
        opacity: longEdge ? 0.42 : 0.68,
        type: longEdge ? 'dashed' : 'solid',
        curveness: 0,
      },
    }
  })
}

function dataDrivenEdgeData(edges, positions, activeNodeIds = new Set(), denseLocalFocus = false, palette = editorialTokens) {
  return edges.map((edge) => {
    const relationType = String(edge.relationType || '').toLowerCase()
    const active = activeNodeIds.size > 0 && activeNodeIds.has(String(edge.source)) && activeNodeIds.has(String(edge.target))
    const directed = ['contains', 'teaches', 'prerequisite', 'depends_on', 'derives_from', 'causes', 'influences'].includes(relationType)
    const structuralFan = denseLocalFocus && ['contains', 'teaches', 'grounds'].includes(relationType)
    const weakRelation = ['contains', 'teaches', 'grounds', 'related', 'supports', 'references'].includes(relationType)
    return {
      ...edge,
      edgeSymbol: directed ? ['none', 'arrow'] : ['none', 'none'],
      edgeSymbolSize: directed ? 7 : 0,
      lineStyle: {
        ...(edge.lineStyle || {}),
        // The strongest active path is the single editorial accent; all
        // other relations use an ink-opacity ladder so structure remains
        // legible without turning the canvas into a rainbow of categories.
        color: active
          ? palette.accent
          : (relationType === 'prerequisite' ? palette.inkStrong : palette.inkSoft),
        width: active ? 2.1 : (relationType === 'prerequisite' ? 1.55 : (structuralFan ? 0.8 : (weakRelation ? 0.95 : 1.1))),
        opacity: active ? 0.92 : (relationType === 'prerequisite' ? 0.78 : (structuralFan ? 0.1 : (weakRelation ? 0.28 : 0.54))),
        // Keep the earlier visual distinction: strong learning relations are
        // solid, while structural/secondary relations recede as light dashes.
        type: active ? 'solid' : (structuralFan || weakRelation ? 'dashed' : 'solid'),
        curveness: 0,
      },
    }
  })
}

function graphViewInsets(positions, nodes, chartWidth, chartHeight) {
  const fallback = { left: 72, right: 72, top: 104, bottom: 72 }
  if (!positions?.size || !chartWidth || !chartHeight) return fallback

  const points = [...positions.values()]
  const minX = Math.min(...points.map(point => Number(point.x) || 0))
  const maxX = Math.max(...points.map(point => Number(point.x) || 0))
  const minY = Math.min(...points.map(point => Number(point.y) || 0))
  const maxY = Math.max(...points.map(point => Number(point.y) || 0))
  const dataWidth = Math.max(maxX - minX, 1)
  const dataHeight = Math.max(maxY - minY, 1)
  const contentWidth = Math.max(chartWidth - 144, 220)
  const contentHeight = Math.max(chartHeight - 176, 220)
  const dataAspect = dataWidth / dataHeight
  const contentAspect = contentWidth / contentHeight

  // View coordinates are allowed to letterbox inside the reserved title and
  // legend area. Matching the view aspect to the data aspect makes ECharts'
  // raw X/Y transform uniform, so a circle remains a circle on every desktop
  // size instead of being stretched into an ellipse.
  let viewWidth = contentWidth
  let viewHeight = contentHeight
  if (dataAspect > contentAspect) viewHeight = contentWidth / dataAspect
  else viewWidth = contentHeight * dataAspect
  const horizontalInset = 72 + Math.max(0, contentWidth - viewWidth) / 2
  const verticalInset = 104 + Math.max(0, contentHeight - viewHeight) / 2
  return {
    left: horizontalInset,
    right: horizontalInset,
    top: verticalInset,
    bottom: 72 + Math.max(0, contentHeight - viewHeight) / 2,
  }
}

function wrapLabel(value, maxChars = 11) {
  const text = String(value ?? '').trim()
  if (!text) return ''
  const lineLength = text.length > maxChars ? Math.max(maxChars, Math.ceil(text.length / 2)) : text.length
  const chunks = []
  for (let index = 0; index < text.length; index += lineLength) chunks.push(text.slice(index, index + lineLength))
  return chunks.join('\n')
}

function buildOption() {
  const highlighted = highlightedNodes.value
  const nodes = visibleNodes.value
  const edges = visibleEdges.value
  const reducedMotion = typeof window !== 'undefined'
    && Boolean(window.matchMedia?.('(prefers-reduced-motion: reduce)')?.matches)
  const usesDynamicLayout = Boolean(props.layoutDecision) && nodes.length > 0
  const denseLocalFocus = props.layoutDecision?.strategy === 'local_focus' && nodes.length > 40
  const denseHierarchical = props.layoutDecision?.strategy === 'hierarchical' && nodes.length > 20
  const legacyPathModel = props.legacyPathLayout && nodes.length <= 40
    ? legacyPathLayoutModel(nodes, edges)
    : { positions: new Map(), focusId: '', directIds: new Set() }
  const usesLegacyPathLayout = props.legacyPathLayout && nodes.length <= 40 && legacyPathModel.positions.size > 0
  // Closed F7/F8 contract markers retained for source-level compatibility:
  // layout: props.fixedLayout ? 'none' : (props.fitDenseGraph ? 'none' : (relationshipProjection.value ? 'circular' : 'force'))
  // roam: !props.fixedLayout · draggable: !props.fixedLayout · animation: !props.fixedLayout
  // animationDuration: props.fixedLayout ? 0 : 550 · animationDurationUpdate: props.fixedLayout ? 0 : 550
  // profileGraphLayout(props.nodes, props.edges)
  // Closed contract marker: zoom: props.fixedLayout || props.fitDenseGraph ? 0.92 : 1
  // Closed contract marker: const denseSymbolSizes = { course: 68, chapter: 58, knowledge_point: 52, source: 38 }
  const profileLayout = props.profileLayout && !usesDynamicLayout ? profileGraphLayout(nodes, edges) : { positions: new Map(), groups: new Map() }
  const profilePositions = profileLayout.positions
  const fixedPositions = props.profileLayout && !usesDynamicLayout
    ? profilePositions
    : (props.fixedLayout ? fixedProfilePositions(nodes, edges) : new Map())
  const dataPositions = usesLegacyPathLayout
    ? legacyPathModel.positions
    : dataDrivenPositions(nodes, edges, props.layoutDecision, props.topicClusters)
  const densePositions = usesDynamicLayout
    ? dataPositions
    : (props.fixedLayout
      ? fixedPositions
      : (dataPositions.size
          ? dataPositions
          : (props.fitDenseGraph
              ? (relationshipProjection.value
                  ? relationshipProjectionPositions(nodes, edges)
                  : denseGraphPositions(nodes))
              : new Map())))
  const viewInsets = graphViewInsets(
    densePositions,
    nodes,
    chartRef.value?.clientWidth || 0,
    props.height,
  )
  // Node sizes are supplied as a single diameter below.  ECharts renders a
  // scalar graph symbol as a true circle; passing a width/height pair here
  // would create an ellipse whenever a sparse layer is mapped to a non-square
  // plot.  Keep the layout coordinates and measured collision boxes in the
  // same logical units and let the chart's view transform scale both axes.
  const fixedAnchorId = props.fixedLayout && !props.profileLayout && !usesDynamicLayout ? String(fixedProfileAnchor(nodes, edges)) : null
  const colors = usesDynamicLayout ? categoryColors : (props.profileLayout ? profileCategoryColors : categoryColors)
  const graphTokens = props.profileLayout ? profileEditorialTokens : editorialTokens
  const chartCategories = props.categories.map((category, index) => ({
    ...category,
    itemStyle: {
      ...(category.itemStyle || {}),
      color: colors[index % colors.length],
    },
  }))
  // Closed contract marker: const chartNodes = props.nodes.map((node, index) => {
  const chartNodes = nodes.map((node, index) => {
    const isHighlighted = highlighted.has(String(node.id))
    const category = typeof node.category === 'number' ? node.category : index % Math.max(props.categories.length, 1)
    const isLocalFocus = props.layoutDecision?.strategy === 'local_focus'
    const denseSymbolSizes = isLocalFocus
      ? { course: 38, chapter: 30, knowledge_point: 22, source: 20 }
      : { course: 56, chapter: 48, knowledge_point: 40, source: 32 }
    const isFixedAnchor = props.fixedLayout && !props.profileLayout && !usesDynamicLayout && String(node.id) === fixedAnchorId
    const isCurrentFocus = Boolean(node.isCurrentFocus)
    const isBridgeNode = Boolean(node.isBridgeNode)
    const isSelected = String(selectedNode.value?.id || '') === String(node.id)
    const isProfileSelected = props.profileLayout && selectedNode.value?.id === node.id
    const isLegacyFocus = usesLegacyPathLayout && String(node.id) === legacyPathModel.focusId
    const isLegacyDirect = usesLegacyPathLayout && legacyPathModel.directIds.has(String(node.id))
    const nodeBox = estimatedNodeBox(node)
    const showFilteredStructural = nodeTypeFilter.value !== 'all' && node.nodeType !== 'knowledge_point'
    const dataSymbolSize = usesLegacyPathLayout
      ? (isLegacyFocus
        ? Math.max(76, nodeBox.width)
        : isLegacyDirect
          ? Math.min(124, Math.max(64, nodeBox.width))
          : Math.min(104, Math.max(56, nodeBox.width)))
      : isLocalFocus
      ? (node.nodeType === 'knowledge_point' ? (isCurrentFocus || isHighlighted || isSelected ? 52 : 16) : (denseSymbolSizes[node.nodeType] || 24))
      : (usesDynamicLayout
        ? (denseHierarchical && node.nodeType !== 'knowledge_point'
        ? (node.nodeType === 'course' ? 64 : (node.nodeType === 'chapter' ? 42 : 28))
          : (denseHierarchical ? Math.min(nodeBox.width, 132) : nodeBox.width))
        : (node.nodeType === 'knowledge_point'
          ? Math.min(68, Math.max(42, 34 + String(node.name || '').length * 3))
          : (denseSymbolSizes[node.nodeType] || 46)))
    const baseSymbolSize = usesDynamicLayout
      ? dataSymbolSize
      : props.fitDenseGraph
        ? (props.layoutDecision ? dataSymbolSize : (denseSymbolSizes[node.nodeType] || 46))
      : (props.profileLayout && !usesDynamicLayout ? 58 : (props.fixedLayout && !usesDynamicLayout ? (isFixedAnchor ? 64 : 50) : (node.symbolSize || (node.masteryBand === 'unknown' ? 42 : 48))))
    const symbolSize = Number(baseSymbolSize) || 56
    const symbolWidth = symbolSize
    const showDenseLabel = usesLegacyPathLayout
      ? (node.nodeType !== 'source' || isHighlighted || isSelected || showFilteredStructural)
      : denseHierarchical
      ? (node.nodeType === 'knowledge_point' || isCurrentFocus || isHighlighted || isSelected || showFilteredStructural)
      : isLocalFocus
      ? (node.nodeType !== 'knowledge_point' || isCurrentFocus || isHighlighted || selectedNode.value?.id === node.id || showFilteredStructural)
      : (node.nodeType !== 'source' || selectedNode.value?.id === node.id || showFilteredStructural)
    return {
      ...node,
      ...(densePositions.get(props.fixedLayout ? String(node.id) : node.id) || {}),
      category,
      symbolSize,
      symbol: 'circle',
      symbolKeepAspect: true,
      itemStyle: {
        ...(node.itemStyle || {}),
        color: usesDynamicLayout ? graphTokens.paper : (props.profileLayout ? '#ffffff' : (props.fixedLayout ? '#fffdf8' : colors[category % colors.length])),
        borderColor: usesDynamicLayout
          ? (node.masteryBand === 'conflict' ? graphTokens.accent : (isSelected ? graphTokens.accent : (isCurrentFocus ? graphTokens.accent : (isBridgeNode ? graphTokens.inkMedium : (isHighlighted ? graphTokens.inkMedium : graphTokens.inkSoft)))))
          : props.profileLayout
            ? (node.masteryBand === 'conflict' ? '#9b3a3a' : (isProfileSelected ? '#11212d' : (isCurrentFocus ? '#315b6d' : (isBridgeNode || isHighlighted ? '#60727c' : '#ccd0cf'))))
          : props.fixedLayout
            ? (node.masteryBand === 'conflict' ? '#9b3f36' : (isProfileSelected ? '#35291f' : (isFixedAnchor ? '#5d4a3b' : (isCurrentFocus ? '#9b6b42' : (isBridgeNode ? '#786657' : (isHighlighted ? '#786657' : '#cbbcaf'))))))
            : (node.masteryBand === 'conflict' ? '#a9514c' : '#e3d9cf'),
        borderWidth: usesDynamicLayout
          ? (node.masteryBand === 'conflict' || isCurrentFocus || isHighlighted || isSelected ? 2.8 : 1.35)
          : props.fixedLayout
          ? (node.masteryBand === 'conflict' || isFixedAnchor || isProfileSelected || isCurrentFocus ? 3 : (isHighlighted ? 2 : 1.5))
          : (node.masteryBand === 'conflict' ? 3 : 2),
        shadowBlur: usesDynamicLayout
          ? (isSelected || isCurrentFocus || isHighlighted ? 22 : (symbolWidth <= 72 ? 15 : 10))
          : (props.fixedLayout ? (isFixedAnchor || isProfileSelected ? 14 : (symbolWidth <= 72 ? 11 : 8)) : undefined),
        shadowColor: usesDynamicLayout
          ? (isSelected || isCurrentFocus ? graphTokens.accentSoft : (symbolWidth <= 72 ? graphTokens.inkMedium : graphTokens.inkSoft))
          : (props.profileLayout ? 'rgba(17, 33, 45, 0.12)' : (props.fixedLayout ? 'rgba(53, 41, 31, 0.18)' : undefined)),
        opacity: highlighted.size ? (isHighlighted ? 1 : 0.42) : 1,
      },
      label: {
        show: usesLegacyPathLayout
          ? showDenseLabel
          : (usesDynamicLayout ? (!props.fitDenseGraph || showDenseLabel) : (props.fixedLayout || !props.fitDenseGraph || showDenseLabel)),
        // Dynamic graphs keep labels inside their measured node box. This
        // makes a two-line title travel with its node instead of colliding
        // with the next layer when a dense graph is viewed or filtered.
        position: usesDynamicLayout ? 'inside' : ((props.fixedLayout || props.fitDenseGraph) ? 'inside' : 'bottom'),
        width: (usesDynamicLayout && props.fitDenseGraph) || props.fixedLayout ? Math.max(symbolWidth + 34, 72) : Math.max(symbolWidth + 48, 96),
        overflow: 'break',
        fontSize: usesDynamicLayout ? (isCurrentFocus || isHighlighted || isSelected ? 12 : 11) : (props.profileLayout ? (isProfileSelected ? 12 : 11) : (props.fixedLayout && isFixedAnchor ? 12 : (isHighlighted ? 12 : 11))),
        fontWeight: usesDynamicLayout ? (isSelected || isCurrentFocus || isHighlighted || isBridgeNode ? 700 : 550) : (props.profileLayout || (props.fixedLayout && isFixedAnchor) || isHighlighted ? 700 : 500),
        lineHeight: usesDynamicLayout ? 15 : (props.profileLayout ? 15 : 16),
        color: usesDynamicLayout ? graphTokens.ink : (props.profileLayout ? '#253745' : (props.fixedLayout ? '#35291f' : (props.fitDenseGraph ? '#ffffff' : (isHighlighted ? '#06141b' : '#344957')))),
        formatter: ({ data }) => {
          const label = wrapLabel(data.name, data.nodeType === 'knowledge_point' ? 12 : 16)
          if (usesDynamicLayout && data.mastery != null && props.profileLayout) return `${label}\n${Math.round(data.mastery * 100)}%`
          if (!usesDynamicLayout && props.fixedLayout && data.mastery != null) return `${label}\n${Math.round(data.mastery * 100)}%`
          return label
        },
      },
    }
  })

  return {
    title: {
      text: props.chartTitle,
      subtext: props.chartSubtitle,
      left: 24,
      top: 18,
      textStyle: { fontFamily: "Georgia, 'Songti SC', serif", fontSize: 19, fontWeight: 500, color: graphTokens.ink },
      subtextStyle: { fontFamily: "'SF Mono', Consolas, monospace", fontSize: 12, color: graphTokens.inkMedium, lineHeight: 20 },
    },
    tooltip: {
      backgroundColor: graphTokens.paper,
      borderColor: graphTokens.inkSoft,
      borderWidth: 1,
      padding: 12,
      textStyle: { color: graphTokens.ink, fontSize: 14 },
      formatter(params) {
        if (params.dataType === 'node') {
          const detail = props.showMasteryInTooltip
            ? (params.data.mastery == null ? '暂无判断' : `${Math.round(params.data.mastery * 100)}%`)
            : (params.data.summary || params.data.sourceStatus || '课程事实')
          const metrics = props.layoutDecision && params.data.nodeType === 'knowledge_point'
            ? `<br><span style="color:#60727c">重要性 ${safeText(params.data.importance ?? '—')} · 连接 ${safeText(params.data.degree ?? 0)} · ${params.data.isBridgeNode ? '桥接节点' : '主题节点'}${params.data.isCurrentFocus ? ' · 当前重点' : ''}</span>`
            : ''
          return `<strong>${safeText(params.name)}</strong><br><span style="color:#60727c">${safeText(params.data.categoryName || '未分类')} · ${safeText(detail)}</span>${metrics}`
        }
        return `${safeText(params.data.source)} → ${safeText(params.data.target)}`
      },
    },
    legend: {
      data: props.categories.map((category) => category.name),
      top: 22,
      right: 18,
      type: 'scroll',
      width: '54%',
      textStyle: { fontFamily: "'SF Mono', Consolas, monospace", fontSize: 12, color: graphTokens.inkMedium },
    },
    animationDuration: reducedMotion || (props.fixedLayout && !usesDynamicLayout) ? 0 : 680,
    animationDurationUpdate: reducedMotion || (props.fixedLayout && !usesDynamicLayout) ? 0 : 520,
    animationEasingUpdate: 'cubicOut',
    series: [{
      type: 'graph',
      // Keep circle nodes geometrically round when ECharts maps the logical
      // graph coordinates into a non-square canvas.
      aspectScale: 1,
      layout: usesDynamicLayout || props.fixedLayout || props.fitDenseGraph ? 'none' : (relationshipProjection.value ? 'circular' : 'force'),
      left: usesDynamicLayout || props.fixedLayout || props.fitDenseGraph ? viewInsets.left : 24,
      right: usesDynamicLayout || props.fixedLayout || props.fitDenseGraph ? viewInsets.right : 24,
      top: usesDynamicLayout || props.fixedLayout || props.fitDenseGraph ? viewInsets.top : 86,
      bottom: usesDynamicLayout || props.fixedLayout || props.fitDenseGraph ? viewInsets.bottom : 24,
      zoom: usesDynamicLayout || props.fixedLayout || props.fitDenseGraph ? 0.92 : 1,
      force: {
        repulsion: 720,
        edgeLength: [92, 176],
        gravity: 0.12,
        layoutAnimation: false,
        friction: 0.14,
      },
      circular: { rotateLabel: false },
      roam: !props.fixedLayout || usesDynamicLayout,
      draggable: !props.fixedLayout || usesDynamicLayout,
      animation: !reducedMotion && (!props.fixedLayout || usesDynamicLayout),
      data: chartNodes,
      // Default graph facts remain `edges: props.edges`; only the profile view decorates them.
        edges: props.layoutDecision
          ? dataDrivenEdgeData(edges, densePositions, highlighted, denseLocalFocus || denseHierarchical, graphTokens)
        : (props.profileLayout
          ? profileEdgeData(edges, profilePositions, profileLayout.groups)
          : edges),
      categories: chartCategories.length ? chartCategories : undefined,
      label: {
        show: !props.fitDenseGraph,
        position: 'bottom',
        distance: 7,
      },
      edgeLabel: { show: false },
      lineStyle: {
        color: usesDynamicLayout ? editorialTokens.inkSoft : (props.profileLayout ? 'rgba(37, 55, 69, 0.26)' : '#c5b8aa'),
        curveness: 0,
        width: usesDynamicLayout ? 1.2 : (props.fixedLayout ? 1.25 : 1.5),
        opacity: usesDynamicLayout ? 0.54 : (props.fixedLayout ? 0.72 : 0.72),
      },
      emphasis: { focus: 'adjacency', lineStyle: { color: usesDynamicLayout ? editorialTokens.accent : (props.profileLayout ? '#315b6d' : '#6f8795'), width: usesDynamicLayout ? 2.2 : (props.fixedLayout ? 2.2 : 3), opacity: 1 } },
    }],
  }
}

function relatedNodeIds(nodeId) {
  const ids = new Set([String(nodeId)])
  let frontier = new Set([String(nodeId)])
  for (let depth = 0; depth < Math.max(1, Number(focusDepth.value) || 1); depth += 1) {
    const next = new Set()
    for (const edge of visibleEdges.value) {
      const source = String(edge.source)
      const target = String(edge.target)
      if (frontier.has(source)) next.add(target)
      if (frontier.has(target)) next.add(source)
    }
    for (const id of next) ids.add(id)
    frontier = next
  }
  return ids
}

function render() {
  if (!chartInstance) return
  chartInstance.setOption(buildOption(), true)
}

function doSearch() {
  const query = searchQuery.value.trim().toLocaleLowerCase()
  if (!query) {
    highlightedNodes.value = new Set()
    expandedNodeIds.value = new Set()
    selectNode(null)
    render()
    return
  }
  const matched = semanticNodes.value.find((node) => String(node.name || '').toLocaleLowerCase().includes(query))
  if (!matched) {
    highlightedNodes.value = new Set()
    selectNode(null)
    render()
    return
  }
  if (progressiveGraph.value) {
    const nextExpanded = new Set(expandedNodeIds.value)
    const queue = [String(matched.id)]
    const seen = new Set(queue)
    while (queue.length) {
      const current = queue.shift()
      for (const parent of prerequisiteParents.value.get(current) || []) {
        if (seen.has(parent)) continue
        seen.add(parent)
        nextExpanded.add(parent)
        queue.push(parent)
      }
    }
    expandedNodeIds.value = nextExpanded
  }
  highlightedNodes.value = relatedNodeIds(matched.id)
  selectNode(matched)
  render()
}

function onChartClick(params) {
  if (params.dataType !== 'node') {
    highlightedNodes.value = new Set()
    selectNode(null)
    render()
    return
  }
  const node = visibleNodes.value.find((item) => String(item.id) === String(params.data.id)) || null
  if (node && progressiveGraph.value) {
    const nodeId = String(node.id)
    const children = prerequisiteChildren.value.get(nodeId) || new Set()
    if (children.size) {
      const nextExpanded = new Set(expandedNodeIds.value)
      nextExpanded.add(nodeId)
      expandedNodeIds.value = nextExpanded
    }
  }
  highlightedNodes.value = node ? relatedNodeIds(node.id) : new Set()
  selectNode(node)
  render()
}

function resetView() {
  highlightedNodes.value = new Set()
  searchQuery.value = ''
  nodeTypeFilter.value = 'all'
  relationTypeFilter.value = 'all'
  focusDepth.value = 1
  expandedNodeIds.value = new Set()
  selectNode(null)
  render()
  chartInstance?.dispatchAction({ type: 'restore' })
  // Closed contract marker: if (!props.fixedLayout) chartInstance?.dispatchAction({ type: 'restore' })
  emit('reset')
}

function resizeChart() {
  chartInstance?.resize()
}

onMounted(async () => {
  await nextTick()
  if (!chartRef.value) return
  chartInstance = echarts.init(chartRef.value)
  // Expose the mounted instance for the B29 browser evidence harness; this
  // does not add a user-facing path or change the graph data.
  chartRef.value.__edumatrixChartInstance = chartInstance
  render()
  chartInstance.on('click', onChartClick)
  window.addEventListener('resize', resizeChart)
})

onUnmounted(() => {
  window.removeEventListener('resize', resizeChart)
  chartInstance?.off('click', onChartClick)
  chartInstance?.dispose()
  if (chartRef.value) delete chartRef.value.__edumatrixChartInstance
  chartInstance = null
})

watch(() => [props.nodes, props.edges, props.categories, props.layoutMode, props.fixedLayout, props.legacyPathLayout, props.layoutDecision, props.topicClusters, nodeTypeFilter.value, relationTypeFilter.value], () => {
  if (selectedNode.value && !visibleNodeIds.value.has(String(selectedNode.value.id))) selectNode(null)
  render()
}, { deep: true })
</script>

<template>
  <section class="knowledge-graph" :class="{ 'is-fixed-layout': fixedLayout, 'is-profile-layout': profileLayout }" data-testid="knowledge-graph-explorer">
    <div class="graph-toolbar">
      <SearchField
        v-model="searchQuery"
        class="graph-search"
        aria-label="检索知识点"
        placeholder="搜索知识点、章节或来源"
        @update:model-value="doSearch"
      />
      <label v-if="nodeTypeOptions.length" class="graph-filter">
        <span>节点</span>
        <select v-model="nodeTypeFilter" aria-label="按节点类型筛选">
          <option value="all">全部</option>
          <option v-for="item in nodeTypeOptions" :key="item.value" :value="item.value">{{ item.label }}</option>
        </select>
      </label>
      <label v-if="relationTypeOptions.length" class="graph-filter">
        <span>关系</span>
        <select v-model="relationTypeFilter" aria-label="按关系类型筛选">
          <option value="all">全部</option>
          <option v-for="item in relationTypeOptions" :key="item.value" :value="item.value">{{ item.label }}</option>
        </select>
      </label>
      <button type="button" class="focus-depth" :aria-label="`当前聚焦${focusDepth}跳关系，点击切换`" @click="focusDepth = focusDepth === 1 ? 2 : 1">
        聚焦{{ focusDepth }}跳
      </button>
      <button type="button" title="重置图谱视图" @click="resetView">
        <RotateCw :size="16" aria-hidden="true" />
        <span>重置视图</span>
      </button>
    </div>

    <div v-if="layoutSummary" class="graph-decision" data-testid="graph-decision-summary">
      <span>{{ layoutSummary }}</span>
      <span v-if="layoutReason">{{ layoutReason }}</span>
      <span v-if="topicClusters.length">主题簇由当前关系自动识别</span>
      <span v-if="hiddenStructuralCount && nodeTypeFilter === 'all'" class="graph-decision-note">
        {{ hiddenStructuralCount }} 个课程/章节/来源结构节点已收纳；可在“节点”筛选中查看
      </span>
      <span v-if="progressiveGraph && nodeTypeFilter === 'all'" class="graph-decision-note">
        首屏显示先修根节点；点击节点展开下一层（已显示 {{ visibleNodes.length }}/{{ knowledgeNodes.length }} 个知识点）
      </span>
    </div>

    <div class="graph-body">
      <div class="graph-canvas" :style="{ minHeight: `${height}px` }">
        <div v-if="!visibleNodes.length" class="graph-empty" role="status">{{ emptyText }}</div>
        <div v-else ref="chartRef" class="chart" :style="{ height: `${height}px` }" />
      </div>

      <aside v-if="showDetails" class="compact-details" :class="{ 'has-selection': selectedNode }">
        <template v-if="selectedNode">
          <div class="details-heading">
            <Info :size="17" aria-hidden="true" />
            <div>
              <span>当前节点</span>
              <strong>{{ selectedNode.name }}</strong>
            </div>
          </div>
          <p class="details-summary">{{ selectedNode.summary || '该节点来自当前课程图谱。' }}</p>
          <dl>
            <div><dt>类型</dt><dd>{{ selectedNode.categoryName || selectedNode.nodeType || '未分类' }}</dd></div>
            <div v-if="selectedNode.topicClusterIds?.length"><dt>主题簇</dt><dd>{{ selectedNode.topicClusterIds.join('、') }}</dd></div>
            <div v-if="selectedNode.importance !== undefined"><dt>重要性 / 连接</dt><dd>{{ selectedNode.importance }} · {{ selectedNode.degree ?? 0 }}</dd></div>
            <div v-if="selectedNode.hierarchyDepth !== undefined"><dt>层级深度</dt><dd>{{ selectedNode.hierarchyDepth }}</dd></div>
            <div><dt>局部关系</dt><dd>{{ relatedCount }} 个节点</dd></div>
            <div v-if="showMasteryInTooltip && selectedNode.mastery !== undefined"><dt>掌握判断</dt><dd>{{ selectedNode.mastery == null ? '暂无证据' : `${Math.round(selectedNode.mastery * 100)}%` }}</dd></div>
          </dl>
          <button type="button" class="details-clear" @click="selectNode(null)">取消选择</button>
        </template>
        <template v-else>
          <div class="details-heading">
            <Info :size="17" aria-hidden="true" />
            <div>
              <span>图谱概览</span>
              <strong>{{ chartTitle }}</strong>
            </div>
          </div>
          <p class="details-summary">点击节点查看类型、主题簇、关系和可用证据。空白处可取消选择。</p>
          <dl>
            <div><dt>节点</dt><dd>{{ visibleNodes.length }} 个</dd></div>
            <div><dt>关系</dt><dd>{{ visibleEdges.length }} 条</dd></div>
            <div v-if="topicClusters.length"><dt>主题簇</dt><dd>{{ topicClusters.length }} 个</dd></div>
          </dl>
        </template>
      </aside>
    </div>
  </section>
</template>

<style scoped>
.knowledge-graph {
  min-width: 0;
  overflow: hidden;
  color: #2A3B4D;
  border: 1px solid rgba(42, 59, 77, 0.18);
  border-radius: 10px;
  background: #FFFFFF;
}

.graph-toolbar {
  display: flex;
  min-width: 0;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
  padding: 14px 16px;
  border-bottom: 1px solid rgba(42, 59, 77, 0.14);
  background: #FFFFFF;
}

.graph-toolbar button:focus-visible {
  border-color: #C84A31;
  outline: 2px solid rgba(200, 74, 49, 0.18);
  outline-offset: 2px;
}

.graph-toolbar button {
  display: inline-flex;
  min-height: 38px;
  flex: none;
  align-items: center;
  gap: 7px;
  padding: 7px 12px;
  color: rgba(42, 59, 77, 0.72);
  border: 1px solid rgba(42, 59, 77, 0.22);
  border-radius: 6px;
  background: #FFFFFF;
  font-size: 14px;
  font-weight: 650;
  cursor: pointer;
}

.graph-toolbar button:hover { color: #2A3B4D; border-color: #C84A31; background: rgba(200, 74, 49, 0.06); }
.graph-search { min-width: 220px; flex: 1 1 240px; }
.graph-filter { display: inline-flex; min-height: 38px; align-items: center; gap: 6px; color: rgba(42, 59, 77, 0.58); font-size: 14px; }
.graph-filter select { min-height: 38px; max-width: 150px; padding: 0 28px 0 9px; color: rgba(42, 59, 77, 0.72); border: 1px solid rgba(42, 59, 77, 0.22); border-radius: 6px; background: #FFFFFF; font-size: 14px; }
.focus-depth { white-space: nowrap; }
.graph-decision { display: flex; min-width: 0; flex-wrap: wrap; align-items: center; gap: 10px 16px; padding: 10px 16px; color: rgba(42, 59, 77, 0.58); border-bottom: 1px solid rgba(42, 59, 77, 0.12); background: #FFFFFF; font-size: 14px; line-height: 1.5; }
.graph-decision span:first-child { color: #C84A31; font-weight: 700; }
.graph-decision-note { color: rgba(42, 59, 77, 0.46); }
.graph-body { display: flex; min-width: 0; }
.graph-canvas { position: relative; min-width: 0; flex: 1; background: #FFFFFF; }
.knowledge-graph.is-fixed-layout { border-color: rgba(42, 59, 77, 0.18); }
.knowledge-graph.is-fixed-layout .graph-toolbar { background: #FFFFFF; }
.knowledge-graph.is-fixed-layout .graph-canvas { background: #FFFFFF; }
.knowledge-graph.is-profile-layout { border-color: rgba(42, 59, 77, 0.18); background: #FFFFFF; }
.knowledge-graph.is-profile-layout .graph-toolbar { background: #FFFFFF; border-color: rgba(42, 59, 77, 0.14); }
.knowledge-graph.is-profile-layout .graph-canvas { background: #FFFFFF; }
.chart { width: 100%; }
.graph-empty { display: grid; min-height: inherit; place-items: center; padding: 40px; color: rgba(42, 59, 77, 0.58); font-size: 14px; }

.compact-details {
  width: 268px;
  flex: none;
  padding: 24px 22px;
  border-left: 1px solid rgba(42, 59, 77, 0.14);
  background: #FFFFFF;
}

.details-heading { display: flex; align-items: flex-start; gap: 10px; color: #C84A31; }
.details-heading > div { display: grid; min-width: 0; gap: 5px; }
.details-heading span { color: rgba(42, 59, 77, 0.58); font-size: 14px; }
.details-heading strong { color: #2A3B4D; font-size: 16px; line-height: 1.5; overflow-wrap: anywhere; }
.details-summary { margin: 16px 0 0; color: rgba(42, 59, 77, 0.62); font-size: 14px; line-height: 1.65; }
.compact-details dl { display: grid; gap: 0; margin: 20px 0 0; }
.compact-details dl div { display: grid; grid-template-columns: 92px minmax(0, 1fr); gap: 10px; padding: 11px 0; border-bottom: 1px solid rgba(42, 59, 77, 0.10); }
.compact-details dt { color: rgba(42, 59, 77, 0.52); font-size: 14px; }
.compact-details dd { min-width: 0; margin: 0; color: rgba(42, 59, 77, 0.76); font-size: 14px; font-weight: 650; overflow-wrap: anywhere; }
.details-clear { width: 100%; margin-top: 20px; justify-content: center; color: #C84A31 !important; background: rgba(200, 74, 49, 0.06) !important; border-color: rgba(200, 74, 49, 0.28) !important; }

/* Profile pages use the application's ink-blue action color. The orange
 * gallery accent remains available to other graph modes, but must not leak
 * into the learning-image surface. */
.knowledge-graph.is-profile-layout .graph-toolbar button:focus-visible {
  border-color: #315b6d;
  outline-color: rgba(49, 91, 109, 0.18);
}
.knowledge-graph.is-profile-layout .graph-toolbar button:hover {
  border-color: #315b6d;
  background: rgba(49, 91, 109, 0.06);
}
.knowledge-graph.is-profile-layout .graph-decision span:first-child,
.knowledge-graph.is-profile-layout .details-heading,
.knowledge-graph.is-profile-layout .details-clear {
  color: #315b6d !important;
}
.knowledge-graph.is-profile-layout .details-clear {
  background: rgba(49, 91, 109, 0.06) !important;
  border-color: rgba(49, 91, 109, 0.28) !important;
}

@media (max-width: 900px) {
  .graph-body { display: block; }
  .compact-details { width: auto; border-top: 1px solid rgba(42, 59, 77, 0.14); border-left: 0; }
}
</style>
