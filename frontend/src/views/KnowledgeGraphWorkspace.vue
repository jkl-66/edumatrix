<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  ArrowLeft,
  BookOpen,
  ChevronRight,
  GitBranch,
  Layers3,
  ListTree,
  Network,
  RotateCw,
} from '@lucide/vue'
import { getCourseKnowledgeGraph } from '../api/knowledge'
import { getM5ProfileSummary } from '../api/m5'
import KnowledgeGraphExplorer from '../components/KnowledgeGraphExplorer.vue'
import TaskState from '../components/TaskState.vue'

const route = useRoute()
const router = useRouter()
const graph = ref(null)
const profileSummary = ref(null)
const profileSummaryError = ref('')
const status = ref('loading')
const errorMessage = ref('')
const permissionDenied = ref(false)
const selectedNode = ref(null)
const chapterFilter = ref('all')
const relationFilter = ref('all')
const clusterFilter = ref('all')
const layoutMode = ref('graph')
const showHierarchy = ref(false)

const courseId = computed(() => String(route.params.courseId || ''))
const chapters = computed(() => graph.value?.hierarchy || [])
const allNodes = computed(() => graph.value?.nodes || [])
const allEdges = computed(() => graph.value?.edges || [])
const topicClusters = computed(() => graph.value?.topicClusters || [])
const layoutDecision = computed(() => graph.value?.layoutDecision || graph.value?.structureAnalysis?.layoutDecision || null)
const layoutExplanation = computed(() => (
  layoutDecision.value?.strategy === 'hierarchical'
  && Number(graph.value?.statistics?.knowledgePointCount || 0) > 8
    ? '连接关系决定方向，节点通过吸引与排斥自然散开。'
    : layoutDecision.value?.reason || ''
))
const semanticGraphNodeCount = computed(() => filteredNodes.value.filter((node) => !['course', 'chapter', 'source'].includes(String(node?.nodeType || '').toLowerCase())).length)
const graphCanvasHeight = computed(() => {
  if (layoutDecision.value?.strategy === 'hierarchical') return semanticGraphNodeCount.value > 20 ? 960 : 720
  if (layoutDecision.value?.strategy === 'local_focus') return 640
  return 680
})
const nodeById = computed(() => new Map(allNodes.value.map(node => [node.id, node])))
const profileNodeById = computed(() => new Map(
  (profileSummary.value?.knowledge_graph?.nodes || []).map(node => [String(node.id), node]),
))
const selectedProfileNode = computed(() => {
  const knowledgePointId = selectedNode.value?.knowledgePointId
  return knowledgePointId ? profileNodeById.value.get(String(knowledgePointId)) || null : null
})
const selectedBehaviors = computed(() => selectedProfileNode.value?.behaviors || [])
const selectedEvidence = computed(() => selectedProfileNode.value?.evidence || [])

const chapterNodeIds = computed(() => {
  if (chapterFilter.value === 'all') return null
  const chapter = chapters.value.find(item => item.chapterId === chapterFilter.value)
  if (!chapter) return new Set()
  const ids = new Set([
    `course:${courseId.value}`,
    `chapter:${chapter.chapterId}`,
    `source:${chapter.sourceDocumentId}`,
  ])
  for (const point of chapter.knowledgePoints || []) ids.add(`knowledge:${point.id}`)
  return ids
})

const clusterNodeIds = computed(() => {
  const active = clusterFilter.value === 'all'
    ? null
    : topicClusters.value.find(cluster => cluster.id === clusterFilter.value)?.memberNodeIds || []
  const ids = new Set()
  for (const node of allNodes.value) {
    const inSelectedCluster = !active || active.includes(node.id)
    if (inSelectedCluster) ids.add(node.id)
  }
  return ids
})

const filteredEdges = computed(() => {
  let edges = allEdges.value
  if (chapterNodeIds.value) {
    edges = edges.filter(edge => (
      chapterNodeIds.value.has(String(edge.source))
      && chapterNodeIds.value.has(String(edge.target))
    ))
  }
  if (relationFilter.value !== 'all') {
    edges = edges.filter(edge => edge.relationType === relationFilter.value)
  }
  if (clusterFilter.value !== 'all') {
    edges = edges.filter(edge => clusterNodeIds.value.has(String(edge.source)) && clusterNodeIds.value.has(String(edge.target)))
  }
  return edges
})

const filteredNodes = computed(() => {
  if (!chapterNodeIds.value && relationFilter.value === 'all' && clusterFilter.value === 'all') return allNodes.value
  const visible = new Set(clusterNodeIds.value)
  if (chapterNodeIds.value) {
    for (const id of [...visible]) if (!chapterNodeIds.value.has(id)) visible.delete(id)
  }
  for (const edge of filteredEdges.value) {
    visible.add(String(edge.source))
    visible.add(String(edge.target))
  }
  return allNodes.value.filter(node => visible.has(node.id))
})

const activeEdges = computed(() => {
  if (!selectedNode.value) return []
  return allEdges.value.filter(edge => (
    edge.source === selectedNode.value.id || edge.target === selectedNode.value.id
  ))
})

const neighborNames = computed(() => activeEdges.value.slice(0, 5).map(edge => {
  const neighborId = edge.source === selectedNode.value?.id ? edge.target : edge.source
  return {
    id: `${edge.id}:${neighborId}`,
    name: nodeById.value.get(neighborId)?.name || neighborId,
    relation: edge.label || edge.relationType,
  }
}))

const sourceAvailable = computed(() => Boolean(
  selectedNode.value?.sourceDocumentId
  && selectedNode.value?.sourceStatus === 'ready',
))

function apiErrorMessage(error, fallback) {
  const detail = error?.detail || error?.response?.data?.detail
  if (typeof detail === 'string') return detail
  if (detail?.message) return detail.message
  return error?.message || fallback
}

function nodeTypeLabel(node) {
  return node?.categoryName || {
    course: '课程',
    chapter: '章节',
    knowledge_point: '知识点',
    source: '来源',
  }[node?.nodeType] || '课程节点'
}

async function loadGraph() {
  status.value = 'loading'
  errorMessage.value = ''
  permissionDenied.value = false
  selectedNode.value = null
  profileSummaryError.value = ''
  try {
    const [courseGraph, profile] = await Promise.all([
      getCourseKnowledgeGraph(courseId.value),
      getM5ProfileSummary({ course_id: courseId.value }).catch((error) => {
        profileSummaryError.value = apiErrorMessage(error, '个人掌握证据暂时无法读取')
        return null
      }),
    ])
    graph.value = courseGraph
    profileSummary.value = profile
    clusterFilter.value = 'all'
    status.value = graph.value?.status === 'ready' ? 'ready' : 'empty'
    showHierarchy.value = graph.value?.displayMode === 'hierarchy'
  } catch (error) {
    graph.value = null
    status.value = 'failed'
    permissionDenied.value = error?.response?.status === 403 || error?.status === 403
    errorMessage.value = apiErrorMessage(error, '课程知识图谱暂时无法打开')
    if (permissionDenied.value) errorMessage.value = '当前账号没有查看这门课程图谱的权限。'
  }
}

function selectNode(node) {
  selectedNode.value = node
}

function openSource() {
  if (!sourceAvailable.value) return
  router.push({
    path: `/knowledge/documents/${encodeURIComponent(selectedNode.value.sourceDocumentId)}`,
    query: {
      course_id: courseId.value,
      chapter_id: selectedNode.value.chapterId || undefined,
      source_ref_id: selectedNode.value.sourceRefId || undefined,
    },
  })
}

function openLearningResources() {
  router.push({
    path: '/workspace/resources',
    query: {
      course_id: courseId.value,
      knowledge_point_id: selectedNode.value?.knowledgePointId || undefined,
    },
  })
}

function openPublicSource(item) {
  const route = item?.source?.route
  if (item?.source?.available && route) router.push(route)
}

watch([chapterFilter, relationFilter, clusterFilter], () => {
  if (selectedNode.value && !filteredNodes.value.some(node => node.id === selectedNode.value.id)) {
    selectedNode.value = null
  }
})
watch(courseId, loadGraph)
onMounted(loadGraph)
</script>

<template>
  <main class="graph-workspace" data-testid="course-knowledge-graph-workspace">
    <header class="workspace-header">
      <button type="button" class="back-action" @click="router.push(`/knowledge/courses/${encodeURIComponent(courseId)}`)">
        <ArrowLeft :size="18" aria-hidden="true" />返回课程
      </button>
      <div class="workspace-header__copy">
        <h1>{{ graph?.course?.title || '课程知识图谱' }}</h1>
        <p>查看章节、知识点、先修与来源事实。选择节点后可进入对应原文。</p>
      </div>
      <button type="button" class="secondary-action" :disabled="status === 'loading'" @click="loadGraph">
        <RotateCw :size="17" aria-hidden="true" />重新读取
      </button>
    </header>

    <TaskState
      v-if="status === 'loading'"
      state="loading"
      title="正在读取课程事实"
      message="课程、章节、知识点和来源保持原有版本，不会写入学习证据。"
    />
    <TaskState
      v-else-if="status === 'failed'"
      state="error"
      title="课程知识图谱暂时无法打开"
      :message="errorMessage"
      action-label="重新加载"
      @action="loadGraph"
    />
    <TaskState
      v-else-if="status === 'empty'"
      state="info"
      title="当前课程还没有可展示的图谱"
      message="课程书架和正文仍可使用；完成章节与知识点解析后再返回查看。"
      action-label="返回课程"
      @action="router.push(`/knowledge/courses/${encodeURIComponent(courseId)}`)"
    />

    <template v-else>
      <div class="graph-readonly-note" data-testid="graph-readonly-note">
        <span>{{ graph.availability?.readOnly ? '只读图谱' : '课程图谱' }}</span>
        <p>{{ graph.availability?.message || '浏览、搜索、筛选和来源预览不会写入学习证据。' }}<template v-if="graph.availability?.version"> 当前版本 {{ graph.availability.version }}。</template></p>
      </div>
      <section class="graph-controls" aria-label="课程图谱筛选与视图">
        <label>
          <span>章节</span>
          <select v-model="chapterFilter" data-testid="graph-chapter-filter">
            <option value="all">全部章节</option>
            <option v-for="chapter in chapters" :key="chapter.chapterId" :value="chapter.chapterId">
              第 {{ chapter.position }} 章 · {{ chapter.title }}
            </option>
          </select>
        </label>
        <label>
          <span>关系</span>
          <select v-model="relationFilter" data-testid="graph-relation-filter">
            <option value="all">全部关系</option>
            <option value="contains">章节包含</option>
            <option value="teaches">章节讲授</option>
            <option value="prerequisite">知识先修</option>
            <option value="grounds">来源支撑</option>
          </select>
        </label>
        <label v-if="topicClusters.length">
          <span>主题簇</span>
          <select v-model="clusterFilter" data-testid="graph-cluster-filter">
            <option value="all">全部主题簇</option>
            <option v-for="cluster in topicClusters" :key="cluster.id" :value="cluster.id">
              {{ cluster.title }} · {{ cluster.size }} 个节点
            </option>
          </select>
        </label>
        <div class="view-switch" role="group" aria-label="图谱视图">
          <button
            type="button"
            :aria-pressed="!showHierarchy && layoutMode === 'graph'"
            @click="showHierarchy = false; layoutMode = 'graph'"
          ><Network :size="16" />关系图</button>
          <button
            type="button"
            :aria-pressed="!showHierarchy && layoutMode === 'relationship_projection'"
            @click="showHierarchy = false; layoutMode = 'relationship_projection'"
          ><Layers3 :size="16" />关系投影</button>
          <button
            type="button"
            :aria-pressed="showHierarchy"
            @click="showHierarchy = true"
          ><ListTree :size="16" />层级列表</button>
        </div>
      </section>

      <div class="graph-layout" data-testid="course-graph-75-25-layout">
        <section class="graph-stage" aria-label="课程关系画布">
          <div v-if="filteredNodes.length === 0" class="filter-empty" role="status">
            <GitBranch :size="22" />
            <strong>当前筛选没有可显示的关系</strong>
            <span>更换章节或关系类型即可恢复完整课程图谱。</span>
          </div>
          <div v-else-if="showHierarchy" class="hierarchy-view" data-testid="graph-hierarchy-fallback">
            <header>
              <div><h2>课程层级列表</h2><p>当关系画布不适合阅读时，可使用同一组课程事实继续查看。</p></div>
              <span>{{ chapters.length }} 章</span>
            </header>
            <ol>
              <li v-for="chapter in chapters" :key="chapter.chapterId">
                <button type="button" @click="chapterFilter = chapter.chapterId; showHierarchy = false">
                  <span class="chapter-index">{{ chapter.position }}</span>
                  <span><strong>{{ chapter.title }}</strong><small>{{ chapter.knowledgePoints.length }} 个知识点</small></span>
                  <ChevronRight :size="17" />
                </button>
                <ul>
                  <li v-for="point in chapter.knowledgePoints" :key="point.id">{{ point.title }}</li>
                </ul>
              </li>
            </ol>
          </div>
          <KnowledgeGraphExplorer
            v-else
            :nodes="filteredNodes"
            :edges="filteredEdges"
            :categories="graph.categories"
            :layout-mode="layoutMode"
            :show-details="false"
            :show-mastery-in-tooltip="false"
            :legacy-path-layout="false"
            :layout-decision="layoutDecision"
            :topic-clusters="topicClusters"
            fit-dense-graph
            :height="graphCanvasHeight"
            :chart-title="layoutMode === 'graph' ? '课程关系图' : '中心与邻接关系投影'"
            :chart-subtitle="layoutMode === 'graph' ? '拖拽与缩放只改变视图，不改变掌握度' : '与关系图使用同一组节点、边和来源事实'"
            @node-select="selectNode"
            @reset="selectedNode = null"
          />
        </section>

        <aside class="graph-overview" data-testid="course-graph-overview">
          <template v-if="selectedNode">
            <div class="overview-heading">
              <span>{{ nodeTypeLabel(selectedNode) }}</span>
              <h2>{{ selectedNode.name }}</h2>
              <p>{{ selectedNode.summary || '当前节点来自课程固定版本。' }}</p>
            </div>
            <dl class="overview-facts">
              <div><dt>关联关系</dt><dd>{{ activeEdges.length }} 条</dd></div>
              <div><dt>来源状态</dt><dd>{{ selectedNode.sourceStatus === 'ready' ? '可定位' : '暂无可用来源' }}</dd></div>
              <div v-if="selectedNode.locationLabel"><dt>正文位置</dt><dd>{{ selectedNode.locationLabel }}</dd></div>
              <div v-if="selectedNode.knowledgePointId"><dt>初始掌握证据</dt><dd>{{ selectedNode.masteryStatus === 'known' ? `${selectedNode.masteryLabel} · ${selectedNode.masteryEvidenceCount} 条` : '未知 · 尚无足够诊断证据' }}</dd></div>
              <div v-if="selectedNode.knowledgePointId && selectedNode.masteryEvidenceCount"><dt>交叉证据</dt><dd>{{ selectedNode.masteryCrossEvidence ? '已有多条题目证据' : '目前只有单条题目证据' }}</dd></div>
              <div v-if="selectedNode.topicClusterIds?.length"><dt>主题簇</dt><dd>{{ selectedNode.topicClusterIds.join('、') }}</dd></div>
              <div v-if="selectedNode.nodeType === 'knowledge_point'"><dt>结构指标</dt><dd>重要性 {{ selectedNode.importance ?? '—' }} · 连接 {{ selectedNode.degree ?? 0 }}</dd></div>
              <div v-if="selectedNode.nodeType === 'knowledge_point'"><dt>结构角色</dt><dd>{{ selectedNode.isBridgeNode ? '桥接节点' : '主题节点' }}{{ selectedNode.isCurrentFocus ? ' · 当前重点' : '' }}</dd></div>
              <div v-if="selectedNode.nodeType === 'knowledge_point' && selectedNode.needsDetailExplanation"><dt>详情建议</dt><dd>建议结合来源和掌握证据查看</dd></div>
              <div v-if="selectedProfileNode"><dt>当前掌握判断</dt><dd>{{ selectedProfileNode.mastery == null ? '待补证据' : `${Math.round(selectedProfileNode.mastery * 100)}% · ${selectedProfileNode.judgement}` }}</dd></div>
            </dl>
            <section v-if="selectedBehaviors.length" class="overview-behaviors" data-testid="course-graph-node-behaviors">
              <header><h3>学习行为</h3><span>{{ selectedBehaviors.length }} 条</span></header>
              <article v-for="(behavior, index) in selectedBehaviors" :key="`${behavior.label}-${behavior.occurredAt || index}`">
                <strong>{{ behavior.label }}</strong>
                <time>{{ behavior.occurredAt ? new Date(behavior.occurredAt).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }) : '时间未记录' }}</time>
                <p>{{ behavior.detail }}</p>
                <button v-if="behavior.source?.available" type="button" @click="openPublicSource(behavior)">{{ behavior.source.label }}<ChevronRight :size="14" /></button>
                <small v-else>来源暂不可用，仍保留行为记录</small>
              </article>
            </section>
            <section v-else-if="selectedNode.knowledgePointId" class="overview-evidence-empty" data-testid="course-graph-node-no-behaviors">
              <strong>暂无可展示的学习行为</strong>
              <p>{{ profileSummaryError || '当前没有足够证据形成行为时间线；掌握判断保持待确认。' }}</p>
            </section>
            <section v-if="selectedEvidence.length" class="overview-evidence" data-testid="course-graph-node-evidence">
              <header><h3>判断依据</h3><span>{{ selectedEvidence.length }} 条</span></header>
              <article v-for="(item, index) in selectedEvidence" :key="`${item.sourceLabel || item.label}-${item.observedAt || index}`">
                <strong>{{ item.sourceLabel || item.label }}</strong>
                <p>{{ item.value }}</p>
                <time>{{ item.observedAt ? new Date(item.observedAt).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }) : '时间未记录' }}</time>
                <button v-if="item.source?.available" type="button" @click="openPublicSource(item)">{{ item.source.label }}<ChevronRight :size="14" /></button>
              </article>
            </section>
            <section v-if="neighborNames.length" class="neighbor-list">
              <h3>相邻节点</h3>
              <ul>
                <li v-for="item in neighborNames" :key="item.id"><span>{{ item.name }}</span><small>{{ item.relation }}</small></li>
              </ul>
            </section>
            <div class="overview-actions">
              <button type="button" class="primary-action" :disabled="!sourceAvailable" @click="openSource">
                <BookOpen :size="17" />打开来源正文
              </button>
              <p v-if="!sourceAvailable">该节点没有当前可访问的正文来源，仍可查看课程关系。</p>
              <p v-if="profileSummaryError" class="overview-data-note">个人掌握证据暂时无法读取，课程关系和来源仍可继续查看。</p>
              <button v-if="selectedNode.knowledgePointId" type="button" class="text-action" @click="openLearningResources">
                查看相关学习资源<ChevronRight :size="15" />
              </button>
            </div>
          </template>
          <template v-else>
            <div class="overview-heading">
              <span>课程概览</span>
              <h2>{{ graph.course.title }}</h2>
              <p>{{ graph.course.description || '选择画布中的章节、知识点或来源，查看关系与原文入口。' }}</p>
            </div>
            <dl class="course-statistics">
              <div><dt>章节</dt><dd>{{ graph.statistics.chapterCount }}</dd></div>
              <div><dt>知识点</dt><dd>{{ graph.statistics.knowledgePointCount }}</dd></div>
              <div><dt>来源</dt><dd>{{ graph.statistics.sourceCount }}</dd></div>
              <div><dt>关系</dt><dd>{{ graph.statistics.edgeCount }}</dd></div>
              <div v-if="layoutDecision"><dt>主题簇</dt><dd>{{ layoutDecision.clusterCount }}</dd></div>
            </dl>
            <div v-if="layoutDecision" class="layout-explanation">
              <strong>布局依据</strong>
              <p>{{ layoutExplanation }}</p>
              <small>节点与标签避让、边界约束和右侧详情空间均作为布局约束。</small>
            </div>
            <div class="authority-note">
              <GitBranch :size="18" />
              <p>{{ graph.authorityBoundary }}</p>
            </div>
            <div class="mastery-note" data-testid="graph-mastery-boundary">
              <span>学习掌握证据</span>
              <p>{{ graph.masterySnapshot?.status === 'available' ? '来自本课程最近一次诊断证据快照；查看图谱不会修改掌握度。' : '完成本课程诊断后，这里会显示可回溯的初始掌握证据。' }}</p>
            </div>
          </template>
        </aside>
      </div>
    </template>
  </main>
</template>

<style scoped>
.graph-workspace {
  display: grid;
  min-width: 0;
  gap: 20px;
  padding: 24px;
  color: #4b4039;
  background: #f7f2ea;
}

.mastery-note {
  display: grid;
  gap: 5px;
  margin-top: 16px;
  padding: 12px;
  color: var(--color-text-secondary);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-control);
  background: var(--color-surface-subtle);
}
.mastery-note span { color: var(--color-text); font-size: 14px; font-weight: 650; }
.mastery-note p { margin: 0; font-size: 14px; line-height: 1.55; }

.graph-readonly-note {
  display: grid;
  gap: 4px;
  padding: 11px 14px;
  border: 1px solid #ded3c7;
  border-radius: var(--radius-control);
  background: #fffaf4;
}
.graph-readonly-note span { color: #5b4e45; font-size: 14px; font-weight: 700; }
.graph-readonly-note p { margin: 0; color: #887b70; font-size: 14px; line-height: 1.5; }

.layout-explanation { display: grid; gap: 5px; margin-top: 16px; padding: 13px 14px; border: 1px solid var(--color-border); border-radius: var(--radius-control); background: var(--color-surface-subtle); }
.layout-explanation strong { font-size: 14px; }
.layout-explanation p, .layout-explanation small { margin: 0; color: var(--color-text-secondary); font-size: 14px; line-height: 1.55; }

.workspace-header {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  align-items: start;
  gap: 18px;
}

.workspace-header__copy h1,
.workspace-header__copy p,
.overview-heading h2,
.overview-heading p { margin: 0; }
.workspace-header__copy h1 { font-size: 24px; line-height: 1.35; font-weight: 650; }
.workspace-header__copy p { max-width: 70ch; margin-top: 5px; color: var(--color-text-secondary); font-size: 15px; }

.back-action,
.secondary-action,
.view-switch button,
.primary-action,
.text-action {
  display: inline-flex;
  min-height: 40px;
  align-items: center;
  justify-content: center;
  gap: 7px;
  border-radius: var(--radius-control);
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
}
.back-action,
.secondary-action { padding: 0 13px; color: var(--color-text-secondary); border: 1px solid var(--color-border-strong); background: var(--color-surface); }
.back-action:hover,
.secondary-action:hover { color: var(--color-text); background: var(--color-surface-subtle); }
.secondary-action:disabled { opacity: .5; cursor: not-allowed; }

.graph-controls {
  display: flex;
  min-width: 0;
  align-items: end;
  gap: 14px;
  padding: 14px 16px;
  border: 1px solid #ded3c7;
  border-radius: var(--radius-panel);
  background: #fffef9;
}
.graph-controls label { display: grid; min-width: 180px; gap: 5px; color: var(--color-text-secondary); font-size: 14px; }
.graph-controls select { min-height: 40px; padding: 0 34px 0 11px; color: var(--color-text); border: 1px solid var(--color-border-strong); border-radius: var(--radius-control); background: var(--color-surface); font-size: 14px; }
.view-switch { display: inline-flex; margin-left: auto; padding: 3px; border: 1px solid var(--color-border); border-radius: 8px; background: var(--color-surface-subtle); }
.view-switch button { min-height: 34px; padding: 0 11px; color: var(--color-text-secondary); border: 0; background: transparent; }
.view-switch button[aria-pressed="true"] { color: #fff; background: var(--color-accent); }

.graph-layout {
  display: grid;
  grid-template-columns: minmax(0, 3fr) minmax(280px, 1fr);
  min-width: 0;
  gap: 16px;
  align-items: stretch;
}
.graph-stage { min-width: 0; min-height: 604px; }
.graph-overview { min-width: 0; min-height: 604px; padding: 22px; border: 1px solid #ded3c7; border-radius: var(--radius-panel); background: #fffef9; }
.overview-heading > span { color: var(--color-text-muted); font-size: 14px; font-weight: 600; }
.overview-heading h2 { margin-top: 6px; font-size: 20px; line-height: 1.4; }
.overview-heading p { margin-top: 9px; color: var(--color-text-secondary); font-size: 14px; line-height: 1.65; }

.overview-facts,
.course-statistics { display: grid; gap: 0; margin: 22px 0 0; }
.overview-facts div { display: grid; grid-template-columns: 92px minmax(0, 1fr); gap: 10px; padding: 11px 0; border-bottom: 1px solid var(--color-border); }
.overview-facts dt,
.overview-facts dd,
.course-statistics dt,
.course-statistics dd { margin: 0; font-size: 14px; }
.overview-facts dt { color: var(--color-text-muted); }
.overview-facts dd { color: var(--color-text); font-weight: 600; overflow-wrap: anywhere; }
.course-statistics { grid-template-columns: repeat(2, minmax(0, 1fr)); border-top: 1px solid var(--color-border); border-left: 1px solid var(--color-border); }
.course-statistics div { padding: 14px; border-right: 1px solid var(--color-border); border-bottom: 1px solid var(--color-border); }
.course-statistics dt { color: var(--color-text-muted); }
.course-statistics dd { margin-top: 4px; color: var(--color-text); font-size: 20px; font-weight: 650; font-variant-numeric: tabular-nums; }

.overview-behaviors,
.overview-evidence,
.overview-evidence-empty { margin-top: 22px; padding-top: 16px; border-top: 1px solid var(--color-border); }
.overview-behaviors header,
.overview-evidence header { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
.overview-behaviors h3,
.overview-evidence h3 { margin: 0; font-size: 15px; }
.overview-behaviors header span,
.overview-evidence header span { color: var(--color-text-muted); font-size: 14px; }
.overview-behaviors article,
.overview-evidence article { padding: 10px 0; border-bottom: 1px solid var(--color-border); }
.overview-behaviors article strong,
.overview-evidence article strong { display: block; color: var(--color-text); font-size: 14px; }
.overview-behaviors article time,
.overview-evidence article time { display: block; margin-top: 3px; color: var(--color-text-muted); font-size: 14px; }
.overview-behaviors article p,
.overview-evidence article p { margin: 3px 0; color: var(--color-text-secondary); font-size: 14px; line-height: 1.5; }
.overview-behaviors article button,
.overview-evidence article button { display: inline-flex; align-items: center; gap: 3px; padding: 0; color: var(--color-text); border: 0; background: transparent; font-size: 14px; font-weight: 650; }
.overview-behaviors article button:hover,
.overview-behaviors article button:focus-visible,
.overview-evidence article button:hover,
.overview-evidence article button:focus-visible { text-decoration: underline; }
.overview-behaviors article small,
.overview-evidence-empty p { color: var(--color-text-muted); font-size: 14px; line-height: 1.55; }
.overview-evidence-empty strong { display: block; font-size: 15px; }
.overview-evidence-empty p { margin: 5px 0 0; }
.overview-data-note { color: var(--color-text-muted); }

.neighbor-list { margin-top: 22px; }
.neighbor-list h3 { margin: 0 0 9px; font-size: 15px; }
.neighbor-list ul { margin: 0; padding: 0; list-style: none; border-top: 1px solid var(--color-border); }
.neighbor-list li { display: flex; justify-content: space-between; gap: 10px; padding: 9px 0; border-bottom: 1px solid var(--color-border); font-size: 14px; }
.neighbor-list li span { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.neighbor-list small { flex: none; color: var(--color-text-muted); font-size: 14px; }

.overview-actions { display: grid; gap: 9px; margin-top: 24px; }
.primary-action { width: 100%; padding: 0 14px; color: #fff; border: 1px solid var(--color-accent); background: var(--color-accent); }
.primary-action:hover { background: var(--color-text); }
.primary-action:disabled { color: var(--color-text-muted); border-color: var(--color-border); background: var(--color-surface-muted); cursor: not-allowed; }
.overview-actions p { margin: 0; color: var(--color-text-muted); font-size: 14px; line-height: 1.55; }
.text-action { justify-content: flex-start; padding: 0; color: var(--color-text-secondary); border: 0; background: transparent; }
.text-action:hover { color: var(--color-text); }

.authority-note { display: flex; gap: 10px; margin-top: 22px; padding-top: 16px; color: var(--color-text-secondary); border-top: 1px solid var(--color-border); }
.authority-note svg { flex: none; margin-top: 2px; }
.authority-note p { margin: 0; font-size: 14px; line-height: 1.65; }

.filter-empty { display: grid; min-height: 604px; place-content: center; justify-items: center; gap: 7px; padding: 28px; color: var(--color-text-secondary); border: 1px solid var(--color-border); border-radius: var(--radius-panel); background: var(--color-surface); text-align: center; }
.filter-empty strong { color: var(--color-text); font-size: 16px; }
.filter-empty span { font-size: 14px; }

.hierarchy-view { min-height: 604px; padding: 20px; border: 1px solid var(--color-border); border-radius: var(--radius-panel); background: var(--color-surface); }
.hierarchy-view > header { display: flex; justify-content: space-between; gap: 16px; padding-bottom: 16px; border-bottom: 1px solid var(--color-border); }
.hierarchy-view h2,
.hierarchy-view p { margin: 0; }
.hierarchy-view h2 { font-size: 18px; }
.hierarchy-view p { margin-top: 4px; color: var(--color-text-secondary); font-size: 14px; }
.hierarchy-view > header > span { color: var(--color-text-secondary); font-size: 14px; }
.hierarchy-view ol { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0 20px; margin: 0; padding: 0; list-style: none; }
.hierarchy-view ol > li { min-width: 0; padding: 12px 0; border-bottom: 1px solid var(--color-border); }
.hierarchy-view ol button { display: grid; width: 100%; grid-template-columns: 34px minmax(0, 1fr) auto; align-items: center; gap: 10px; padding: 0; text-align: left; border: 0; background: transparent; cursor: pointer; }
.hierarchy-view ol button > span:not(.chapter-index) { display: grid; min-width: 0; }
.hierarchy-view ol button strong { overflow: hidden; font-size: 14px; text-overflow: ellipsis; white-space: nowrap; }
.hierarchy-view ol button small { color: var(--color-text-muted); font-size: 14px; }
.chapter-index { display: grid; width: 30px; height: 30px; place-items: center; color: #fff; border-radius: 50%; background: var(--color-accent); font-size: 14px; font-variant-numeric: tabular-nums; }
.hierarchy-view ul { display: flex; flex-wrap: wrap; gap: 6px; margin: 10px 0 0 44px; padding: 0; list-style: none; }
.hierarchy-view ul li { padding: 2px 7px; color: var(--color-text-secondary); border: 1px solid var(--color-border); border-radius: 999px; font-size: 14px; }

@media (max-width: 1240px) {
  .graph-controls { flex-wrap: wrap; }
  .view-switch { width: 100%; margin-left: 0; }
  .view-switch button { flex: 1; }
  .graph-layout { grid-template-columns: minmax(0, 2.35fr) minmax(270px, 1fr); }
}
</style>
