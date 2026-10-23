<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  AlertTriangle,
  ArrowLeft,
  BookOpen,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Clock3,
  Code2,
  Database,
  ExternalLink,
  FileCheck2,
  Gauge,
  RefreshCw,
  SlidersHorizontal,
  Wrench,
} from '@lucide/vue'
import ResourceHistoryDrawer from '../components/ResourceHistoryDrawer.vue'
import ResourceToolbar from '../components/ResourceToolbar.vue'
import ResourceProfileAdaptation from '../components/ResourceProfileAdaptation.vue'
import { compareM5ResourceVersions, getM5Resource, restoreM5ResourceVersion } from '../api/m5'

const route = useRoute()
const router = useRouter()
const loading = ref(true)
const error = ref('')
const detail = ref(null)
const selectedVersionId = ref('')
const historyOpen = ref(false)
const historyError = ref('')
const restoringId = ref('')
const comparingId = ref('')
const compareResult = ref(null)

const resourceId = computed(() => String(route.params.resourceId || ''))
const workspace = computed(() => detail.value?.training_task || {})
const versions = computed(() => workspace.value.versions || [])
const currentVersionId = computed(() => workspace.value.current_version_id || '')
const historyItems = computed(() => versions.value.map(item => ({
  ...item,
  revision_origin: item.revision_origin || item.metadata?.revision_origin,
  source_status: item.source_status || 'available',
  content_format: item.content_format || 'json',
})))
const selectedVersion = computed(() => (
  versions.value.find(item => item.id === selectedVersionId.value)
  || versions.value.find(item => item.id === currentVersionId.value)
  || null
))
const projection = computed(() => selectedVersion.value?.projection || workspace.value.current || null)
const structured = computed(() => projection.value?.structured || null)
const legacy = computed(() => projection.value?.legacy || null)
const catalog = computed(() => detail.value?.catalog || {})
const sources = computed(() => projection.value?.source_refs || [])
const linkedResources = computed(() => projection.value?.linked_resources || [])
const sandbox = computed(() => linkedResources.value.find(item => item.type === 'code_sandbox') || null)
const model = computed(() => linkedResources.value.find(item => item.type === 'interactive_model') || null)
const completion = computed(() => catalog.value.completion || {})
const executionState = computed(() => {
  const status = completion.value.status || 'not_recorded'
  return ({
    not_recorded: { label: '尚未开始', detail: '阅读任务书不会改变此状态。' },
    partial: { label: '步骤进行中', detail: '继续完成尚未提交的工程步骤。' },
    in_progress: { label: '步骤进行中', detail: '继续完成尚未提交的工程步骤。' },
    submission_pending: { label: '提交待验证', detail: '提交物已保存，等待按评分标准核验。' },
    completed: { label: '已完成', detail: '已存在有效完成证据，可继续查看任务书和运行记录。' },
  })[status] || { label: '状态待确认', detail: '请依据当前任务记录继续处理。' }
})
const isCurrentVersion = computed(() => selectedVersion.value?.id === currentVersionId.value)
const title = computed(() => structured.value?.title || legacy.value?.title || catalog.value.title || '实训任务书')
const objective = computed(() => structured.value?.objective || legacy.value?.objective || '按任务说明完成工程实践。')
const versionLabel = computed(() => selectedVersion.value ? `v${selectedVersion.value.number}` : '未记录')

function message(err) {
  return err?.response?.data?.detail?.message || err?.message || '请求失败，请稍后重试。'
}

async function loadResource() {
  loading.value = true
  error.value = ''
  try {
    detail.value = await getM5Resource(resourceId.value)
    if (!detail.value?.training_task) throw new Error('当前资源不是实训任务书。')
    selectedVersionId.value = currentVersionId.value || versions.value.at(-1)?.id || ''
  } catch (err) {
    error.value = message(err)
  } finally {
    loading.value = false
  }
}

function openSource(source) {
  if (!source?.available || !source.source_document_id) return
  router.push({
    name: 'KnowledgeDocument',
    params: { documentId: source.source_document_id },
    query: {
      canonical_source_id: source.source_document_id,
      course_id: catalog.value.course?.id || route.query.course_id,
      focus_source_ref_id: source.source_ref_id,
      return_to: route.fullPath,
    },
  })
}

function openLinked(resource) {
  if (resource?.available && resource.route) router.push(resource.route)
}

function scrollToSection(id) {
  document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

function openHistory() {
  historyError.value = ''
  compareResult.value = null
  historyOpen.value = true
}

function closeHistory() {
  historyOpen.value = false
  historyError.value = ''
  compareResult.value = null
}

function selectHistoryVersion(versionId) {
  selectedVersionId.value = versionId
  closeHistory()
}

async function compareHistory(versionId) {
  if (comparingId.value) return
  const left = versions.value.find(item => item.id === versionId)
  const right = versions.value.find(item => item.id === currentVersionId.value)
  if (!left || !right) return
  comparingId.value = versionId
  historyError.value = ''
  try {
    compareResult.value = await compareM5ResourceVersions(resourceId.value, left.number, right.number)
  } catch (exception) {
    historyError.value = message(exception)
  } finally {
    comparingId.value = ''
  }
}

async function restoreHistory(versionId) {
  if (restoringId.value || versionId === currentVersionId.value) return
  restoringId.value = versionId
  historyError.value = ''
  try {
    detail.value = await restoreM5ResourceVersion(resourceId.value, {
      expected_lock_version: detail.value.lock_version,
      version_id: versionId,
    })
    selectedVersionId.value = detail.value.training_task?.current_version_id || detail.value.current_version_id || ''
    closeHistory()
  } catch (exception) {
    historyError.value = message(exception)
  } finally {
    restoringId.value = ''
  }
}

watch(resourceId, loadResource)
onMounted(loadResource)
</script>

<template>
  <main class="training-page" data-testid="training-task-workspace">
    <section v-if="loading" class="page-state" role="status">
      <Wrench :size="24" />
      <strong>正在打开实训任务书</strong>
      <span>正在恢复任务版本、课程来源和关联工具。</span>
    </section>

    <section v-else-if="error" class="page-state page-state--error" role="alert">
      <AlertTriangle :size="24" />
      <strong>实训任务书暂时无法打开</strong>
      <span>{{ error }}</span>
      <button type="button" class="primary-button" @click="loadResource"><RefreshCw :size="17" /> 重新加载</button>
    </section>

    <template v-else>
      <ResourceToolbar
        :title="title"
        :type-label="`${catalog.course?.title || '当前课程'} · ${catalog.knowledge_point?.title || '当前知识点'}`"
        :version-label="versionLabel"
        status-label="理解工程目标和检查点"
        :history-count="historyItems.length"
        :history-disabled="!historyItems.length"
        :loading="loading"
        @back="router.push({ name: 'WorkspaceResources', query: { course_id: catalog.course?.id || route.query.course_id } })"
        @history="openHistory"
        @reload="loadResource"
      />

      <ResourceProfileAdaptation
        :plan="detail?.resource?.profile_adaptation_plan"
        :summary="detail?.resource?.profile_adaptation || ''"
        resource-type="training_task"
      />

      <div v-if="projection?.warnings?.length" class="notice notice--warning" role="status">
        <AlertTriangle :size="17" /> {{ projection.warnings[0] }}
      </div>

      <section class="workspace-shell">
        <div class="document-pane">
          <div class="document-toolbar">
            <nav v-if="structured" aria-label="任务书目录">
              <button type="button" @click="scrollToSection('preparation')">准备</button>
              <button type="button" @click="scrollToSection('steps')">步骤</button>
              <button type="button" @click="scrollToSection('checkpoints')">检查点</button>
              <button type="button" @click="scrollToSection('deliverables')">提交物</button>
              <button type="button" @click="scrollToSection('rubric')">评分</button>
            </nav>
            <label class="version-control">
              <span>版本</span>
              <select v-model="selectedVersionId" aria-label="选择实训任务书版本">
                <option v-for="version in versions" :key="version.id" :value="version.id">v{{ version.number }}</option>
              </select>
              <ChevronDown :size="15" aria-hidden="true" />
            </label>
          </div>

          <div v-if="!isCurrentVersion" class="historical-banner" role="status">
            当前查看历史版本 {{ versionLabel }}。阅读历史内容不会改变当前版本或学习状态。
          </div>

          <article v-if="structured" class="task-document">
            <section class="document-lead">
              <div class="lead-icon"><Wrench :size="24" /></div>
              <div>
                <span>工程任务目标</span>
                <h2>{{ structured.objective }}</h2>
              </div>
              <dl>
                <div><dt>难度</dt><dd><Gauge :size="16" />{{ structured.difficulty }}</dd></div>
                <div><dt>预计时长</dt><dd><Clock3 :size="16" />{{ structured.estimatedMinutes }} 分钟</dd></div>
                <div><dt>当前版本</dt><dd>{{ versionLabel }}</dd></div>
              </dl>
            </section>

            <section id="preparation" class="document-section preparation-section">
              <div class="section-heading"><span>开始前</span><h3>准备条件</h3></div>
              <div class="preparation-grid">
                <section>
                  <BookOpen :size="19" />
                  <div><h4>前置知识</h4><ul><li v-for="item in structured.prerequisites" :key="item">{{ item }}</li></ul></div>
                </section>
                <section>
                  <Code2 :size="19" />
                  <div><h4>运行环境</h4><ul><li v-for="item in structured.environment" :key="item">{{ item }}</li></ul></div>
                </section>
                <section>
                  <Database :size="19" />
                  <div><h4>数据与输入</h4><ul><li v-for="item in structured.data" :key="item">{{ item }}</li></ul></div>
                </section>
              </div>
            </section>

            <section id="steps" class="document-section">
              <div class="section-heading"><span>执行过程</span><h3>任务步骤</h3><p>按顺序完成。真实代码、输入和输出保存在代码沙盒，不在任务书中模拟。</p></div>
              <ol class="step-list">
                <li v-for="(step, index) in structured.steps" :key="step.id">
                  <span class="step-number">{{ String(index + 1).padStart(2, '0') }}</span>
                  <div class="step-body">
                    <h4>{{ step.title }}</h4>
                    <p>{{ step.instruction }}</p>
                    <dl>
                      <div><dt>预期结果</dt><dd>{{ step.expectedResult }}</dd></div>
                      <div><dt>出现问题时</dt><dd>{{ step.errorGuidance }}</dd></div>
                    </dl>
                  </div>
                </li>
              </ol>
            </section>

            <section id="checkpoints" class="document-section">
              <div class="section-heading"><span>质量控制</span><h3>检查点</h3><p>检查点只说明如何核对，阅读或展开不会自动标记完成。</p></div>
              <div class="checkpoint-list">
                <section v-for="checkpoint in structured.checkpoints" :key="checkpoint.id">
                  <CheckCircle2 :size="20" />
                  <div><h4>{{ checkpoint.title }}</h4><p>{{ checkpoint.verification }}</p><strong>通过条件：{{ checkpoint.passCondition }}</strong></div>
                </section>
              </div>
            </section>

            <section id="deliverables" class="document-section">
              <div class="section-heading"><span>提交要求</span><h3>提交物</h3></div>
              <div class="deliverable-list">
                <section v-for="item in structured.deliverables" :key="item.id">
                  <FileCheck2 :size="20" />
                  <div><h4>{{ item.title }}</h4><p>{{ item.description }}</p><span>{{ item.format }}</span></div>
                </section>
              </div>
            </section>

            <section id="rubric" class="document-section rubric-section">
              <div class="section-heading"><span>验收标准</span><h3>评分标准</h3><p>总分 100 分，评分依据必须来自真实提交物和运行证据。</p></div>
              <div class="rubric-table" role="table" aria-label="实训评分标准">
                <div class="rubric-head" role="row"><span role="columnheader">评价项</span><span role="columnheader">证据要求</span><span role="columnheader">分值</span></div>
                <div v-for="item in structured.rubric" :key="item.id" class="rubric-row" role="row">
                  <strong role="cell">{{ item.criterion }}</strong><span role="cell">{{ item.evidence }}</span><b role="cell">{{ item.points }}</b>
                </div>
              </div>
            </section>
          </article>

          <article v-else-if="projection?.mode === 'legacy_lab_guide'" class="task-document legacy-document">
            <section class="document-lead">
              <div class="lead-icon"><Wrench :size="24" /></div>
              <div><span>旧版实验说明</span><h2>{{ legacy.objective }}</h2></div>
            </section>
            <section class="document-section"><div class="section-heading"><h3>环境与安全边界</h3></div><ul><li v-for="item in legacy.environment" :key="item">{{ item }}</li></ul><p>{{ legacy.safety_boundary }}</p></section>
            <section class="document-section"><div class="section-heading"><h3>原有步骤</h3></div><ol class="step-list"><li v-for="(step, index) in legacy.steps" :key="step.id"><span class="step-number">{{ String(index + 1).padStart(2, '0') }}</span><div class="step-body"><h4>{{ step.title }}</h4><p>{{ step.instruction }}</p><dl><div><dt>预期结果</dt><dd>{{ step.expectedResult }}</dd></div><div><dt>回退方式</dt><dd>{{ step.errorGuidance }}</dd></div></dl></div></li></ol></section>
            <section class="document-section"><div class="section-heading"><h3>原验收条件</h3></div><ul><li v-for="item in legacy.acceptance_criteria" :key="item">{{ item }}</li></ul></section>
          </article>

          <article v-else-if="projection?.mode === 'legacy_document'" class="task-document legacy-document">
            <section class="document-lead"><div class="lead-icon"><BookOpen :size="24" /></div><div><span>旧版任务说明</span><h2>{{ legacy.title }}</h2></div></section>
            <section class="document-section legacy-content"><pre>{{ legacy.content }}</pre></section>
          </article>

          <section v-else class="invalid-state" role="alert">
            <AlertTriangle :size="26" />
            <h2>任务书结构不完整</h2>
            <p>{{ projection?.warnings?.[0] || '当前内容无法安全展示，请返回资源中心选择其他版本。' }}</p>
            <button type="button" class="secondary-button" @click="router.push({ name: 'WorkspaceResources' })">返回资源中心</button>
          </section>
        </div>

        <aside class="support-panel" aria-label="来源与关联工具">
          <section class="progress-section">
            <h2>任务状态</h2>
            <div class="progress-summary">
              <span>{{ executionState.label }}</span>
              <strong v-if="completion.progress != null">{{ Math.round(Number(completion.progress) * 100) }}%</strong>
            </div>
            <div v-if="completion.progress != null" class="progress-track" aria-hidden="true"><span :style="{ width: `${Math.max(0, Math.min(100, Number(completion.progress) * 100))}%` }" /></div>
            <p>{{ executionState.detail }}</p>
          </section>

          <section>
            <h2>来源</h2>
            <div :class="['source-readiness', { ready: projection?.source_readiness?.publishable }]">
              <CheckCircle2 v-if="projection?.source_readiness?.publishable" :size="17" />
              <AlertTriangle v-else :size="17" />
              <span>{{ projection?.source_readiness?.reason || '未记录来源状态。' }}</span>
            </div>
            <button v-for="source in sources" :key="source.source_ref_id" type="button" class="source-row" :disabled="!source.available" @click="openSource(source)">
              <BookOpen :size="17" />
              <span><strong>{{ source.title || '课程来源' }}</strong><small>{{ source.location_label || '位置未记录' }}</small></span>
              <ExternalLink v-if="source.available" :size="15" />
            </button>
            <p v-if="!sources.length" class="panel-empty">当前版本没有登记可追溯来源。</p>
          </section>

          <section class="tool-section">
            <h2>进入实际操作</h2>
            <p>任务书负责说明做什么；下面两个资源分别承担运行和参数探索。</p>
            <button type="button" class="tool-entry tool-entry--primary" :disabled="!sandbox?.available || !sandbox?.route" @click="openLinked(sandbox)">
              <Code2 :size="19" />
              <span><strong>进入代码沙盒</strong><small>{{ sandbox?.available ? '编辑、运行、调试并保留真实输出' : '关联沙盒尚未生成或不可用' }}</small></span>
              <ChevronRight :size="17" />
            </button>
            <button type="button" class="tool-entry" :disabled="!model?.available || !model?.route" @click="openLinked(model)">
              <SlidersHorizontal :size="19" />
              <span><strong>打开可交互模型</strong><small>{{ model?.available ? '调节参数并观察图表与规律' : '关联模型尚未生成或不可用' }}</small></span>
              <ChevronRight :size="17" />
            </button>
          </section>

          <p class="evidence-boundary">阅读任务书、切换版本、展开内容和查看来源不会完成学习任务，也不会改变掌握度。只有后续提交真实运行、实验或其他规定证据后，系统才会更新学习状态。</p>
        </aside>
      </section>
    </template>

    <ResourceHistoryDrawer
      :open="historyOpen"
      :title="`${title} · 版本历史`"
      :items="historyItems"
      :current-version-id="currentVersionId"
      :selected-version-id="selectedVersionId"
      :restoring-id="restoringId"
      :error="historyError"
      :compare-result="compareResult"
      :comparing-id="comparingId"
      :compare-disabled="Boolean(comparingId)"
      :restore-disabled="Boolean(restoringId)"
      @close="closeHistory"
      @select="selectHistoryVersion"
      @compare="compareHistory"
      @restore="restoreHistory"
      @compare-close="compareResult = null"
    />
  </main>
</template>

<style scoped>
.training-page{min-height:100%;padding:24px 28px 32px;background:var(--color-page);color:var(--color-text);font-family:var(--font-sans)}
.back-link{display:inline-flex;align-items:center;gap:8px;margin:0 0 18px;padding:0;border:0;background:transparent;color:var(--color-text-secondary);font-size:14px;font-weight:650;cursor:pointer}.back-link:hover{color:var(--color-text)}
.page-header{display:grid;grid-template-columns:minmax(0,1fr) minmax(500px,.85fr);gap:36px;align-items:end;padding-bottom:22px;border-bottom:1px solid var(--color-border)}
.context-line{margin:0 0 6px;color:var(--color-text-secondary);font-size:14px;font-weight:650}.page-header h1{margin:0;font-family:var(--font-heading);font-size:34px;line-height:1.25;letter-spacing:0}.page-header>div>p:last-child{max-width:70ch;margin:9px 0 0;color:var(--color-text-secondary);font-size:15px;line-height:1.65}
.header-meta{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));overflow:hidden;border:1px solid var(--color-border);border-radius:8px;background:#fff}.header-meta>div{min-width:0;padding:13px 14px;border-right:1px solid var(--color-border)}.header-meta>div:last-child{border-right:0}.header-meta span,.header-meta strong{display:block}.header-meta span{color:var(--color-text-muted);font-size:14px}.header-meta strong{margin-top:4px;font-size:14px;line-height:1.45}
.notice{display:flex;align-items:center;gap:8px;margin-top:14px;padding:10px 12px;border:1px solid var(--color-border);border-radius:6px;background:#fff;color:var(--color-text-secondary);font-size:14px}.notice--warning{border-color:#dfcfb4;background:var(--color-warning-soft);color:#6f501e}
.workspace-shell{display:grid;grid-template-columns:minmax(0,1fr) 310px;min-height:680px;margin-top:18px;overflow:hidden;border:1px solid var(--color-border-strong);border-radius:8px;background:#fff}.document-pane{min-width:0;border-right:1px solid var(--color-border)}
.document-toolbar{position:sticky;z-index:3;top:0;display:flex;min-height:58px;align-items:center;justify-content:space-between;gap:18px;padding:9px 18px;border-bottom:1px solid var(--color-border);background:#fff}.document-toolbar nav{display:flex;gap:4px}.document-toolbar nav button{min-height:36px;padding:0 10px;border:0;border-radius:6px;background:transparent;color:var(--color-text-secondary);font:650 14px/1.3 var(--font-sans);cursor:pointer}.document-toolbar nav button:hover,.document-toolbar nav button:focus-visible{background:var(--color-surface-subtle);color:var(--color-text);outline:none}
.version-control{position:relative;display:flex;align-items:center;gap:7px;height:38px;padding:0 9px 0 11px;border:1px solid var(--color-border);border-radius:6px;color:var(--color-text-secondary);font-size:14px}.version-control select{appearance:none;min-width:58px;padding-right:20px;border:0;outline:0;background:transparent;color:var(--color-text);font:600 14px/1.4 var(--font-sans)}.version-control svg{position:absolute;right:8px;pointer-events:none}.historical-banner{padding:10px 24px;border-bottom:1px solid var(--color-border);background:var(--color-surface-subtle);color:var(--color-text-secondary);font-size:14px;text-align:center}
.task-document{width:min(820px,calc(100% - 64px));margin-inline:auto}.document-lead{display:grid;grid-template-columns:48px minmax(0,1fr);gap:16px;padding:50px 0 38px;border-bottom:1px solid var(--color-border)}.lead-icon{display:grid;width:44px;height:44px;place-items:center;border:1px solid var(--color-border-strong);border-radius:8px;background:var(--color-surface-subtle)}.document-lead>div:nth-child(2)>span,.section-heading>span{color:var(--color-text-muted);font-size:14px;font-weight:650}.document-lead h2{max-width:28ch;margin:8px 0 0;font-family:var(--font-display);font-size:30px;line-height:1.38;letter-spacing:0}.document-lead dl{grid-column:2;display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:24px;margin:18px 0 0}.document-lead dl div{padding-top:12px;border-top:1px solid var(--color-border-strong)}.document-lead dt{color:var(--color-text-muted);font-size:14px}.document-lead dd{display:flex;align-items:center;gap:7px;margin:5px 0 0;font-size:14px;font-weight:650}
.document-section{scroll-margin-top:70px;padding:40px 0;border-bottom:1px solid var(--color-border)}.section-heading h3{margin:6px 0 0;font-size:23px;line-height:1.35}.section-heading p{max-width:70ch;margin:8px 0 0;color:var(--color-text-secondary);font-size:15px;line-height:1.65}
.preparation-grid{display:grid;gap:0;margin-top:22px;border-top:1px solid var(--color-border)}.preparation-grid>section{display:grid;grid-template-columns:28px minmax(0,1fr);gap:12px;padding:18px 0;border-bottom:1px solid var(--color-border)}.preparation-grid h4{margin:0;font-size:16px}.preparation-grid ul,.legacy-document ul{display:grid;gap:7px;margin:9px 0 0;padding-left:20px}.preparation-grid li,.legacy-document li{color:var(--color-text-secondary);font-size:15px;line-height:1.6}
.step-list{display:grid;gap:0;margin:24px 0 0;padding:0;list-style:none}.step-list>li{display:grid;grid-template-columns:48px minmax(0,1fr);gap:16px;padding:24px 0;border-top:1px solid var(--color-border)}.step-number{font-variant-numeric:tabular-nums;color:var(--color-text-muted);font-size:15px;font-weight:700}.step-body h4{margin:0;font-size:18px}.step-body>p{margin:8px 0 0;color:var(--color-text-secondary);font-size:15px;line-height:1.7}.step-body dl{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin:16px 0 0}.step-body dl div{padding:13px;border:1px solid var(--color-border);border-radius:6px;background:var(--color-surface-subtle)}.step-body dt{color:var(--color-text-muted);font-size:14px}.step-body dd{margin:5px 0 0;font-size:14px;line-height:1.6}
.checkpoint-list,.deliverable-list{display:grid;margin-top:22px;border-top:1px solid var(--color-border)}.checkpoint-list>section,.deliverable-list>section{display:grid;grid-template-columns:28px minmax(0,1fr);gap:12px;padding:18px 0;border-bottom:1px solid var(--color-border)}.checkpoint-list h4,.deliverable-list h4{margin:0;font-size:16px}.checkpoint-list p,.deliverable-list p{margin:6px 0 0;color:var(--color-text-secondary);font-size:15px;line-height:1.6}.checkpoint-list strong,.deliverable-list span{display:block;margin-top:8px;color:var(--color-text);font-size:14px;line-height:1.55}
.rubric-table{margin-top:22px;border:1px solid var(--color-border-strong);border-radius:8px;overflow:hidden}.rubric-head,.rubric-row{display:grid;grid-template-columns:minmax(150px,.75fr) minmax(0,1.5fr) 64px;align-items:center}.rubric-head{min-height:42px;background:var(--color-surface-subtle);color:var(--color-text-muted);font-size:14px;font-weight:650}.rubric-row{min-height:68px;border-top:1px solid var(--color-border)}.rubric-head>* ,.rubric-row>*{padding:10px 14px}.rubric-row strong,.rubric-row span,.rubric-row b{font-size:14px;line-height:1.55}.rubric-row span{color:var(--color-text-secondary)}.rubric-row b{font-variant-numeric:tabular-nums;text-align:right}
.legacy-document>section>p{color:var(--color-text-secondary);font-size:15px;line-height:1.7}.legacy-content pre{margin:0;white-space:pre-wrap;overflow-wrap:anywhere;color:var(--color-text-secondary);font:15px/1.75 var(--font-sans)}
.invalid-state{display:grid;min-height:570px;place-content:center;justify-items:center;gap:10px;padding:40px;text-align:center}.invalid-state h2{margin:0;font-size:23px}.invalid-state p{max-width:52ch;margin:0;color:var(--color-text-secondary);font-size:15px;line-height:1.65}
.support-panel{min-width:0;padding:22px 18px;background:var(--color-surface-subtle);overflow-y:auto}.support-panel section+section{margin-top:28px;padding-top:24px;border-top:1px solid var(--color-border)}.support-panel h2{margin:0 0 10px;font-size:17px}.source-readiness{display:flex;align-items:flex-start;gap:8px;padding:10px;border:1px solid #dfcfb4;border-radius:6px;background:var(--color-warning-soft);color:#6f501e}.source-readiness.ready{border-color:var(--color-border-strong);background:var(--color-success-soft);color:var(--color-text-secondary)}.source-readiness span{font-size:14px;line-height:1.55}.source-row,.tool-entry{display:flex;width:100%;align-items:center;gap:10px;margin-top:8px;padding:10px;border:1px solid var(--color-border);border-radius:6px;background:#fff;color:var(--color-text);text-align:left;cursor:pointer}.source-row:disabled,.tool-entry:disabled{cursor:not-allowed;opacity:.62}.source-row>span,.tool-entry>span{min-width:0;flex:1}.source-row strong,.source-row small,.tool-entry strong,.tool-entry small{display:block;overflow-wrap:anywhere}.source-row strong,.tool-entry strong{font-size:14px}.source-row small,.tool-entry small{margin-top:3px;color:var(--color-text-muted);font-size:14px;line-height:1.45}.tool-section>p{margin:0 0 12px;color:var(--color-text-secondary);font-size:14px;line-height:1.6}.tool-entry--primary{border-color:var(--color-accent);background:var(--color-accent);color:#fff}.tool-entry--primary small{color:#e7ecee}.tool-entry--primary:disabled{border-color:var(--color-border);background:#fff;color:var(--color-text)}.tool-entry--primary:disabled small{color:var(--color-text-muted)}.panel-empty{margin:9px 0 0;color:var(--color-text-muted);font-size:14px;line-height:1.55}.evidence-boundary{margin:28px 0 0;padding-top:18px;border-top:1px solid var(--color-border);color:var(--color-text-muted);font-size:14px;line-height:1.6}
.progress-summary{display:flex;align-items:center;justify-content:space-between;gap:12px}.progress-summary span,.progress-summary strong{font-size:14px}.progress-summary span{font-weight:700}.progress-summary strong{font-variant-numeric:tabular-nums}.progress-track{height:5px;margin-top:10px;overflow:hidden;border-radius:3px;background:var(--color-surface-muted)}.progress-track span{display:block;height:100%;background:var(--color-accent)}.progress-section p{margin:9px 0 0;color:var(--color-text-secondary);font-size:14px;line-height:1.55}
.primary-button,.secondary-button{display:inline-flex;min-height:40px;align-items:center;justify-content:center;gap:7px;padding:0 13px;border-radius:6px;font:650 14px/1.3 var(--font-sans);cursor:pointer}.primary-button{border:1px solid var(--color-accent);background:var(--color-accent);color:#fff}.secondary-button{border:1px solid var(--color-border-strong);background:#fff;color:var(--color-text)}button:focus-visible,select:focus-visible{outline:2px solid var(--color-accent);outline-offset:2px}.page-state{display:grid;min-height:calc(100vh - 150px);place-content:center;justify-items:center;gap:10px;color:var(--color-text-secondary)}.page-state strong{color:var(--color-text);font-size:18px}.page-state span{max-width:44ch;font-size:14px;text-align:center}.page-state .primary-button{margin-top:8px}.page-state--error{color:var(--color-danger)}
@media(max-width:1300px){.training-page{padding-inline:22px}.page-header{grid-template-columns:minmax(0,1fr) minmax(440px,.9fr);gap:24px}.workspace-shell{grid-template-columns:minmax(0,1fr) 288px}.task-document{width:min(760px,calc(100% - 44px))}.document-toolbar{padding-inline:12px}.document-toolbar nav button{padding-inline:8px}}
.training-page .support-panel{max-height:calc(100vh - 280px);overflow-y:auto}
</style>
