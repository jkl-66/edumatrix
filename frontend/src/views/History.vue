<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  AlertCircle,
  ArrowLeft,
  ArrowRight,
  BookOpen,
  ChevronLeft,
  ChevronRight,
  Clock3,
  FileSearch,
  Filter,
  History as HistoryIcon,
  RefreshCw,
  ShieldCheck,
} from '@lucide/vue'
import { getM5PersonalActivity, listKnowledgeCourseShelf } from '../api'
import { selectableCourseOptions } from '../utils/assessmentConfiguration'
import PageHeader from '../components/PageHeader.vue'
import AggregationStatus from '../components/AggregationStatus.vue'
import SearchField from '../components/ui/SearchField.vue'
import { useCourseContextStore } from '../stores/courseContext'

const route = useRoute()
const router = useRouter()
const courseContext = useCourseContextStore()
const pageSize = 12
const loading = ref(true)
const error = ref('')
const data = ref(null)
const courseOptions = ref([])
const kindOptions = ref([])
const selectedCourseId = ref(String(route.query.course_id || courseContext.contextRef?.courseId || ''))
const selectedDays = ref([7, 30, 90].includes(Number(route.query.days)) ? Number(route.query.days) : 30)
const selectedKind = ref(String(route.query.kind || ''))
const searchQuery = ref('')
const offset = ref(Math.max(0, Number(route.query.offset) || 0))
const selectedItemId = ref(String(route.query.event_id || ''))

const rawItems = computed(() => data.value?.activity?.items || [])
const visibleItems = computed(() => {
  const query = searchQuery.value.trim().toLocaleLowerCase('zh-CN')
  if (!query) return rawItems.value
  return rawItems.value.filter(item => [
    item.label,
    item.detail,
    item.course?.title,
    item.eventType,
  ].some(value => String(value || '').toLocaleLowerCase('zh-CN').includes(query)))
})
const selectedItem = computed(() => (
  rawItems.value.find(item => item.id === selectedItemId.value) || visibleItems.value[0] || null
))
const total = computed(() => Number(data.value?.activity?.total || 0))
const pageStart = computed(() => total.value ? offset.value + 1 : 0)
const pageEnd = computed(() => Math.min(offset.value + rawItems.value.length, total.value))
const canPrevious = computed(() => offset.value > 0)
const canNext = computed(() => Boolean(data.value?.activity?.hasMore))

function message(value) {
  const detail = value?.response?.data?.detail || value?.detail
  return detail?.message || (typeof detail === 'string' ? detail : '') || value?.message || '学习历史暂时无法加载'
}

function formatTime(value, long = false) {
  if (!value) return '时间未记录'
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return '时间未记录'
  return new Intl.DateTimeFormat('zh-CN', long
    ? { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }
    : { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }
  ).format(parsed)
}

function routeFor(target) {
  if (!target?.available) return ''
  return typeof target.route === 'string' && target.route.startsWith('/') ? target.route : ''
}

function selectItem(item) {
  selectedItemId.value = item.id
  syncRoute()
}

function openSelected() {
  const target = routeFor(selectedItem.value?.target)
  if (target) router.push(target)
}

async function syncRoute() {
  await router.replace({
    path: '/profile/history',
    query: {
      course_id: selectedCourseId.value || undefined,
      days: selectedDays.value,
      kind: selectedKind.value || undefined,
      offset: offset.value || undefined,
      event_id: selectedItemId.value || undefined,
    },
  })
}

async function loadHistory({ discoverCourses = false } = {}) {
  loading.value = true
  error.value = ''
  try {
    if (discoverCourses) {
      const [overview, shelf] = await Promise.all([
        getM5PersonalActivity({ days: selectedDays.value, limit: 1 }),
        listKnowledgeCourseShelf(),
      ])
      courseOptions.value = selectableCourseOptions(shelf)
      if (selectedCourseId.value && !courseOptions.value.some((course) => String(course.id) === String(selectedCourseId.value))) {
        selectedCourseId.value = courseOptions.value[0]?.id || ''
      }
      kindOptions.value = overview.activity?.kinds || []
    }
    data.value = await getM5PersonalActivity({
      course_id: selectedCourseId.value || undefined,
      days: selectedDays.value,
      kind: selectedKind.value || undefined,
      offset: offset.value,
      limit: pageSize,
    })
    if (!courseOptions.value.length) courseOptions.value = selectableCourseOptions({ shelf: data.value.courses || [] })
    if (!kindOptions.value.length) kindOptions.value = data.value.activity?.kinds || []
    if (!rawItems.value.some(item => item.id === selectedItemId.value)) {
      selectedItemId.value = rawItems.value[0]?.id || ''
    }
    await syncRoute()
  } catch (requestError) {
    error.value = message(requestError)
  } finally {
    loading.value = false
  }
}

async function applyFilters() {
  offset.value = 0
  selectedItemId.value = ''
  await loadHistory()
}

async function resetFilters() {
  selectedCourseId.value = ''
  selectedDays.value = 30
  selectedKind.value = ''
  searchQuery.value = ''
  offset.value = 0
  selectedItemId.value = ''
  await loadHistory()
}

async function changePage(direction) {
  offset.value = Math.max(0, offset.value + direction * pageSize)
  selectedItemId.value = ''
  await loadHistory()
}

onMounted(() => loadHistory({ discoverCourses: true }))
</script>

<template>
  <main class="history-page" data-testid="profile-history">
    <PageHeader
      eyebrow="个人中心 / 学习历史"
      title="学习历史"
      description="按课程和学习对象找回真实记录，确认其是否形成掌握证据，并从原位置继续。"
    >
      <template #actions>
        <button class="button button--secondary" type="button" @click="router.push('/profile')">
          <ArrowLeft :size="16" /> 返回个人中心
        </button>
      </template>
    </PageHeader>

    <AggregationStatus :course-id="selectedCourseId" class="history-feedback" />

    <section v-if="loading" class="history-state" aria-live="polite">
      <RefreshCw :size="20" class="spin" />
      <div>
        <strong>正在读取学习历史</strong>
        <p>筛选区、时间线和详情区会保持稳定。</p>
      </div>
    </section>

    <section v-else-if="error" class="history-state history-state--error" role="alert">
      <AlertCircle :size="22" />
      <div>
        <strong>学习历史加载失败</strong>
        <p>{{ error }}</p>
      </div>
      <button class="button button--primary" type="button" @click="loadHistory({ discoverCourses: true })">
        <RefreshCw :size="16" /> 重试
      </button>
    </section>

    <section v-else class="history-workspace">
      <aside class="filter-panel" data-testid="history-filters" aria-label="学习历史筛选">
        <div class="panel-title">
          <Filter :size="18" />
          <div>
            <h2>筛选记录</h2>
            <p>筛选只改变当前视图。</p>
          </div>
        </div>

        <label class="field">
          <span>课程</span>
          <select v-model="selectedCourseId" @change="applyFilters">
            <option value="">全部课程</option>
            <option v-for="course in courseOptions" :key="course.id" :value="course.id">{{ course.title }}</option>
          </select>
        </label>

        <fieldset class="field period-field">
          <legend>时间范围</legend>
          <label v-for="days in [7, 30, 90]" :key="days">
            <input v-model="selectedDays" type="radio" :value="days" @change="applyFilters">
            <span>近 {{ days }} 天</span>
          </label>
        </fieldset>

        <label class="field">
          <span>学习对象</span>
          <select v-model="selectedKind" @change="applyFilters">
            <option value="">全部类型</option>
            <option v-for="kind in kindOptions" :key="kind.value" :value="kind.value">{{ kind.label }}</option>
          </select>
        </label>

        <div class="field">
          <span>筛选当前页</span>
          <SearchField v-model="searchQuery" class="history-search-field" aria-label="筛选当前页" placeholder="标题、课程或内容" />
        </div>

        <button class="text-action" type="button" @click="resetFilters">清除全部筛选</button>

        <div class="read-boundary">
          <ShieldCheck :size="18" />
          <p>查看、筛选和展开历史不会改变掌握度、路径或复习安排。</p>
        </div>
      </aside>

      <section class="timeline-panel" data-testid="history-timeline" aria-labelledby="history-timeline-title">
        <div class="timeline-heading">
          <div>
            <h2 id="history-timeline-title">学习时间线</h2>
            <p>第 {{ pageStart }}-{{ pageEnd }} 条，共 {{ total }} 条</p>
          </div>
          <HistoryIcon :size="20" />
        </div>

        <div v-if="visibleItems.length" class="timeline-list">
          <button
            v-for="item in visibleItems"
            :key="item.id"
            type="button"
            class="timeline-row"
            :class="{ active: selectedItem?.id === item.id }"
            :aria-pressed="selectedItem?.id === item.id"
            @click="selectItem(item)"
          >
            <span class="timeline-marker" :class="{ evidence: item.evidence?.masteryEligible }" />
            <span class="timeline-copy">
              <strong>{{ item.label }}</strong>
              <small>{{ item.course?.title }} · {{ formatTime(item.occurredAt) }}</small>
              <span>{{ item.detail }}</span>
            </span>
            <ChevronRight :size="17" />
          </button>
        </div>

        <div v-else class="empty-state">
          <FileSearch :size="28" />
          <strong>{{ searchQuery ? '当前页没有匹配记录' : '所选范围内没有学习历史' }}</strong>
          <p>{{ searchQuery ? '更换关键词或翻页继续查找。' : '完成一次真实学习任务后，记录会自动归档。' }}</p>
          <button v-if="!searchQuery" class="button button--primary" type="button" @click="router.push('/workspace')">
            进入学习空间
          </button>
        </div>

        <nav class="pagination" aria-label="学习历史分页">
          <button class="button button--secondary" type="button" :disabled="!canPrevious" @click="changePage(-1)">
            <ChevronLeft :size="16" /> 上一页
          </button>
          <span>第 {{ Math.floor(offset / pageSize) + 1 }} 页</span>
          <button class="button button--secondary" type="button" :disabled="!canNext" @click="changePage(1)">
            下一页 <ChevronRight :size="16" />
          </button>
        </nav>
      </section>

      <aside class="detail-panel" data-testid="history-detail" aria-label="所选学习记录详情">
        <template v-if="selectedItem">
          <div class="detail-heading">
            <p>记录详情</p>
            <h2>{{ selectedItem.label }}</h2>
            <span>{{ formatTime(selectedItem.occurredAt, true) }}</span>
          </div>

          <dl class="detail-list">
            <div>
              <dt>所属课程</dt>
              <dd>{{ selectedItem.course?.title || '未指定课程' }}</dd>
            </div>
            <div>
              <dt>对象类型</dt>
              <dd>{{ kindOptions.find(item => item.value === selectedItem.kind)?.label || '其他记录' }}</dd>
            </div>
            <div>
              <dt>对掌握度的影响</dt>
              <dd>{{ selectedItem.evidence?.label }}</dd>
            </div>
            <div>
              <dt>证据原因</dt>
              <dd>{{ selectedItem.evidence?.reason || '未提供证据原因' }}</dd>
            </div>
            <div v-if="selectedItem.evidence?.knowledgePointTitles?.length">
              <dt>对应知识点</dt>
              <dd>{{ selectedItem.evidence.knowledgePointTitles.join('、') }}</dd>
            </div>
            <div v-if="selectedItem.evidence?.observations?.length">
              <dt>观察值</dt>
              <dd>{{ selectedItem.evidence.observations.map(item => `${item.knowledgePointTitle} ${Math.round(item.value * 100)}%`).join('、') }}</dd>
            </div>
            <div>
              <dt>反馈聚合状态</dt>
              <dd>{{ selectedItem.evidence?.aggregationStatus || '待同步' }}</dd>
            </div>
            <div>
              <dt>记录说明</dt>
              <dd>{{ selectedItem.detail }}</dd>
            </div>
          </dl>

          <div class="source-box">
            <BookOpen :size="18" />
            <div>
              <strong>来源与上下文</strong>
              <p v-if="selectedItem.target?.available">原学习对象仍可打开，继续后才按真实动作记录新事件。</p>
              <p v-else>原学习对象已撤回或不支持直接打开，历史摘要仍被保留。</p>
            </div>
          </div>

          <button
            class="button button--primary detail-primary"
            type="button"
            :disabled="!routeFor(selectedItem.target)"
            @click="openSelected"
          >
            {{ selectedItem.target?.label || '来源不可用' }} <ArrowRight :size="16" />
          </button>

          <details class="evidence-details">
            <summary>查看记录依据</summary>
            <p>事件类型：{{ selectedItem.eventType || '未记录' }}</p>
            <p>对象：{{ selectedItem.objectType || '未记录' }} / {{ selectedItem.objectId || '未记录' }}</p>
            <p>来源事件：{{ selectedItem.sourceEventIds?.join('、') || '未记录' }}</p>
          </details>
        </template>

        <div v-else class="empty-state empty-state--detail">
          <Clock3 :size="27" />
          <strong>请选择一条学习记录</strong>
          <p>这里会显示来源、证据状态和继续动作。</p>
        </div>
      </aside>
    </section>
  </main>
</template>

<style scoped>
.history-page {
  display: grid;
  width: min(100%, 1240px);
  margin: 0 auto;
  gap: 22px;
  color: var(--color-text);
  font-family: var(--font-sans);
}

.button {
  display: inline-flex;
  min-height: 40px;
  align-items: center;
  justify-content: center;
  gap: 7px;
  padding: 0 14px;
  border-radius: var(--radius-control);
  font: 600 14px/1 var(--font-sans);
  cursor: pointer;
}
.button--primary { color: #ffffff; background: var(--color-accent); border: 1px solid var(--color-accent); }
.button--secondary { color: var(--color-text); background: var(--color-surface); border: 1px solid var(--color-border-strong); }
.button:disabled { cursor: not-allowed; opacity: 0.5; }
.button:focus-visible,
.text-action:focus-visible,
.timeline-row:focus-visible,
.field select:focus-visible,
.field input:focus-visible { outline: 3px solid #9ba8ab; outline-offset: 2px; }

.history-state {
  display: flex;
  min-height: 460px;
  align-items: center;
  justify-content: center;
  gap: 16px;
  padding: 32px;
  color: var(--color-text-secondary);
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-panel);
}
.history-state strong,
.history-state p { display: block; margin: 0; font-size: 15px; line-height: 1.6; }
.history-state--error { color: var(--color-danger); }
.spin { animation: spin 0.8s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }

.history-workspace {
  display: grid;
  min-height: 610px;
  grid-template-columns: 220px minmax(360px, 1fr) 300px;
  align-items: stretch;
  gap: 16px;
}
.filter-panel,
.timeline-panel,
.detail-panel {
  min-width: 0;
  padding: 18px;
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-panel);
}

.panel-title,
.timeline-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 10px; }
.panel-title { justify-content: flex-start; padding-bottom: 16px; border-bottom: 1px solid var(--color-border); }
.panel-title h2,
.timeline-heading h2,
.detail-heading h2 { margin: 0; color: var(--color-text); font-size: 17px; line-height: 1.4; }
.panel-title p,
.timeline-heading p,
.detail-heading p,
.detail-heading span { margin: 3px 0 0; color: var(--color-text-muted); font-size: 14px; line-height: 1.5; }

.field { display: grid; gap: 7px; margin-top: 18px; }
.field > span,
.field legend { color: var(--color-text-secondary); font-size: 14px; font-weight: 650; line-height: 1.4; }
.field select,
.search-control {
  width: 100%;
  min-height: 40px;
  color: var(--color-text);
  background: var(--color-surface);
  border: 1px solid var(--color-border-strong);
  border-radius: var(--radius-control);
  font: 500 14px/1.4 var(--font-sans);
}
.field select { padding: 0 10px; }
.period-field { padding: 0; border: 0; }
.period-field label { display: flex; min-height: 34px; align-items: center; gap: 9px; color: var(--color-text-secondary); font-size: 14px; cursor: pointer; }
.period-field input { width: 16px; height: 16px; accent-color: var(--color-accent); }
.search-control { display: grid; grid-template-columns: 18px 1fr; align-items: center; gap: 7px; padding: 0 10px; }
.search-control svg { color: var(--color-text-muted); }
.search-control input { min-width: 0; height: 38px; padding: 0; color: var(--color-text); background: transparent; border: 0; font: 500 14px/1 var(--font-sans); outline: 0; }

.text-action { min-height: 36px; margin-top: 10px; padding: 0; color: var(--color-accent); background: transparent; border: 0; font: 650 14px/1 var(--font-sans); cursor: pointer; }
.read-boundary { display: flex; align-items: flex-start; gap: 9px; margin-top: 18px; padding-top: 16px; color: var(--color-text-muted); border-top: 1px solid var(--color-border); }
.read-boundary p { margin: 0; font-size: 14px; line-height: 1.6; }

.timeline-panel { display: grid; grid-template-rows: auto minmax(0, 1fr) auto; }
.timeline-heading { align-items: center; padding-bottom: 14px; }
.timeline-list { min-height: 0; border-top: 1px solid var(--color-border); }
.timeline-row {
  display: grid;
  width: 100%;
  min-height: 82px;
  grid-template-columns: 12px minmax(0, 1fr) 18px;
  align-items: center;
  gap: 10px;
  padding: 12px 8px;
  color: var(--color-text);
  background: transparent;
  border: 0;
  border-bottom: 1px solid var(--color-border);
  text-align: left;
  cursor: pointer;
}
.timeline-row.active { background: var(--color-accent-soft); box-shadow: inset 3px 0 0 var(--color-accent); }
.timeline-marker { width: 9px; height: 9px; background: var(--color-text-muted); border-radius: 50%; }
.timeline-marker.evidence { background: var(--color-accent); box-shadow: 0 0 0 3px #dce2e3; }
.timeline-copy { display: block; min-width: 0; }
.timeline-copy strong,
.timeline-copy small,
.timeline-copy span { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.timeline-copy strong { font-size: 14px; line-height: 1.5; }
.timeline-copy small { color: var(--color-text-muted); font-size: 14px; line-height: 1.45; }
.timeline-copy span { margin-top: 4px; color: var(--color-text-secondary); font-size: 14px; line-height: 1.45; }

.pagination { display: flex; align-items: center; justify-content: space-between; gap: 10px; padding-top: 16px; }
.pagination span { color: var(--color-text-muted); font-size: 14px; }

.detail-panel { display: flex; flex-direction: column; }
.detail-heading { padding-bottom: 16px; border-bottom: 1px solid var(--color-border); }
.detail-heading p { margin-top: 0; font-weight: 650; }
.detail-heading span { display: block; margin-top: 6px; }
.detail-list { margin: 4px 0 0; }
.detail-list div { padding: 13px 0; border-bottom: 1px solid var(--color-border); }
.detail-list dt { color: var(--color-text-muted); font-size: 14px; line-height: 1.4; }
.detail-list dd { margin: 4px 0 0; color: var(--color-text); font-size: 14px; line-height: 1.6; overflow-wrap: anywhere; }
.source-box { display: flex; align-items: flex-start; gap: 10px; margin-top: 16px; padding: 14px; background: var(--color-surface-subtle); border: 1px solid var(--color-border); border-radius: var(--radius-control); }
.source-box strong,
.source-box p { display: block; margin: 0; font-size: 14px; line-height: 1.6; }
.source-box p { margin-top: 3px; color: var(--color-text-secondary); }
.detail-primary { width: 100%; margin-top: 16px; }
.evidence-details { margin-top: 14px; color: var(--color-text-secondary); font-size: 14px; }
.evidence-details summary { cursor: pointer; font-weight: 650; }
.evidence-details p { margin: 7px 0 0; font-size: 14px; line-height: 1.55; overflow-wrap: anywhere; }

.empty-state { display: grid; min-height: 360px; place-items: center; align-content: center; gap: 8px; color: var(--color-text-muted); text-align: center; }
.empty-state--detail { min-height: 100%; }
.empty-state strong,
.empty-state p { margin: 0; font-size: 14px; line-height: 1.6; }

@media (max-width: 1080px) {
  .history-workspace { grid-template-columns: 210px minmax(360px, 1fr); }
  .detail-panel { grid-column: 1 / -1; min-height: 330px; }
}
</style>
