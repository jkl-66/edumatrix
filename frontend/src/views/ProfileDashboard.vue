<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  AlertCircle,
  ArrowRight,
  Bookmark,
  CalendarDays,
  Clock3,
  FileText,
  History,
  Pencil,
  RefreshCw,
  Route as RouteIcon,
  UserRound,
} from '@lucide/vue'
import { getM5PersonalActivity, listKnowledgeCourseShelf } from '../api'
import { selectableCourseOptions } from '../utils/assessmentConfiguration'
import LearningTrendChart from '../components/LearningTrendChart.vue'
import PageHeader from '../components/PageHeader.vue'
import { useCourseContextStore } from '../stores/courseContext'

const route = useRoute()
const router = useRouter()
const courseContext = useCourseContextStore()
const loading = ref(true)
const error = ref('')
const activity = ref(null)
const courseOptions = ref([])
const selectedCourseId = ref(String(route.query.course_id || courseContext.contextRef?.courseId || ''))
const selectedDays = ref([7, 30, 90].includes(Number(route.query.days)) ? Number(route.query.days) : 30)

const owner = computed(() => activity.value?.owner || {})
const metrics = computed(() => activity.value?.metrics || {})
const heatmap = computed(() => activity.value?.heatmap?.days || [])
const trend = computed(() => activity.value?.trend?.points || [])
const activityPoints = computed(() => activity.value?.trend?.activityPoints || [])
const recentItems = computed(() => activity.value?.activity?.items || [])
const profileSections = computed(() => activity.value?.profile?.sections || [])
const report = computed(() => activity.value?.report || null)
const periodLabel = computed(() => `近 ${selectedDays.value} 天`)
const initials = computed(() => String(owner.value.displayName || owner.value.username || '学').slice(0, 1))

function errorMessage(value) {
  const detail = value?.response?.data?.detail || value?.detail
  return detail?.message || (typeof detail === 'string' ? detail : '') || value?.message || '个人中心暂时无法加载'
}

function migrationStatusLabel(status) {
  return ({
    preserved_confirmed: '保留已确认值',
    conflict: '待确认差异',
    imported: '已迁入',
    unchanged: '值一致',
  })[status] || status
}

function metricValue(key) {
  const value = metrics.value?.[key]?.value
  return Number.isFinite(Number(value)) ? Number(value) : null
}

function minutes(value) {
  if (value == null) return '暂不可用'
  return `${Number(value).toLocaleString('zh-CN', { maximumFractionDigits: 1 })} 分钟`
}

function formatTime(value) {
  if (!value) return '时间未记录'
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return '时间未记录'
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(parsed)
}

function heatLevel(item) {
  if (!item?.eventCount) return 0
  if (item.activeMinutes >= 45 || item.eventCount >= 5) return 3
  if (item.activeMinutes >= 20 || item.eventCount >= 3) return 2
  return 1
}

function heatTitle(item) {
  if (!item) return ''
  if (!item.eventCount) return `${item.date}：没有有效学习事件`
  return `${item.date}：${item.eventCount} 条有效事件，${item.activeMinutes || 0} 分钟`
}

function routeFor(value, fallback = '') {
  if (typeof value === 'string') return value.startsWith('/') ? value : fallback
  if (value?.available === false) return ''
  return typeof value?.route === 'string' && value.route.startsWith('/') ? value.route : fallback
}

function openTarget(value, fallback = '') {
  const target = routeFor(value, fallback)
  if (target) router.push(target)
}

async function syncRoute() {
  await router.replace({
    path: '/profile',
    query: {
      ...route.query,
      course_id: selectedCourseId.value || undefined,
      days: selectedDays.value,
    },
  })
}

async function loadActivity({ discoverCourses = false, syncUrl = false } = {}) {
  loading.value = true
  error.value = ''
  try {
    if (discoverCourses) {
      const [overview, shelf] = await Promise.all([
        getM5PersonalActivity({ days: selectedDays.value, limit: 5 }),
        listKnowledgeCourseShelf(),
      ])
      courseOptions.value = selectableCourseOptions(shelf)
      if (selectedCourseId.value && !courseOptions.value.some((course) => String(course.id) === String(selectedCourseId.value))) {
        selectedCourseId.value = courseOptions.value[0]?.id || ''
      }
      if (!selectedCourseId.value && courseOptions.value.length) {
        selectedCourseId.value = courseOptions.value[0].id
      }
      if (!selectedCourseId.value) {
        activity.value = overview
        return
      }
    }
    activity.value = await getM5PersonalActivity({
      course_id: selectedCourseId.value || undefined,
      days: selectedDays.value,
      limit: 5,
    })
    if (!courseOptions.value.length) courseOptions.value = selectableCourseOptions({ shelf: activity.value.courses || [] })
    if (selectedCourseId.value) {
      localStorage.setItem('edumatrix_course_id', selectedCourseId.value)
      const selected = courseOptions.value.find(item => item.id === selectedCourseId.value) || activity.value.course
      if (selected?.title) localStorage.setItem('edumatrix_course_title', selected.title)
    }
    if (syncUrl) await syncRoute()
  } catch (requestError) {
    error.value = errorMessage(requestError)
  } finally {
    loading.value = false
  }
}

async function changeCourse() {
  await loadActivity({ syncUrl: true })
}

async function changePeriod(days) {
  if (selectedDays.value === days) return
  selectedDays.value = days
  await loadActivity({ syncUrl: true })
}

let activityRefreshing = false
let lastActivityRefreshAt = 0
async function refreshActivityOnFocus() {
  if (activityRefreshing || loading.value || document.hidden || route.path !== '/profile') return
  if (Date.now() - lastActivityRefreshAt < 15000) return
  lastActivityRefreshAt = Date.now()
  activityRefreshing = true
  try {
    await loadActivity()
  } finally {
    activityRefreshing = false
  }
}

function refreshActivityOnVisibility() {
  if (!document.hidden) void refreshActivityOnFocus()
}

onMounted(async () => {
  await loadActivity({ discoverCourses: true })
  window.addEventListener('focus', refreshActivityOnFocus)
  document.addEventListener('visibilitychange', refreshActivityOnVisibility)
})

onUnmounted(() => {
  window.removeEventListener('focus', refreshActivityOnFocus)
  document.removeEventListener('visibilitychange', refreshActivityOnVisibility)
})
</script>

<template>
  <main class="profile-page" data-testid="profile-dashboard">
    <PageHeader
      eyebrow="个人中心"
      title="我的学习概览"
      description="查看真实学习投入、近期变化和下一步去向。所有统计均来自你的学习事件。"
    >
      <template #actions>
        <label class="course-picker">
          <span class="sr-only">筛选课程</span>
          <select v-model="selectedCourseId" :disabled="loading" @change="changeCourse">
            <option value="">全部课程</option>
            <option v-for="course in courseOptions" :key="course.id" :value="course.id">
              {{ course.title }}
            </option>
          </select>
        </label>
      </template>
    </PageHeader>

    <section v-if="loading" class="profile-state" aria-live="polite">
      <RefreshCw :size="20" class="spin" />
      <div>
        <strong>正在整理个人学习记录</strong>
        <p>页面结构会保持不变，完成后显示真实统计。</p>
      </div>
    </section>

    <section v-else-if="error" class="profile-state profile-state--error" role="alert">
      <AlertCircle :size="22" />
      <div>
        <strong>个人中心加载失败</strong>
        <p>{{ error }}</p>
      </div>
      <button class="button button--primary" type="button" @click="loadActivity({ discoverCourses: true })">
        <RefreshCw :size="16" /> 重试
      </button>
    </section>

    <template v-else-if="activity">
      <section class="identity-band" aria-labelledby="profile-identity-title">
        <div class="avatar" aria-hidden="true">{{ initials }}</div>
        <div class="identity-copy">
          <h2 id="profile-identity-title">{{ owner.displayName || owner.username || '学习者' }}</h2>
          <p>{{ owner.major || '暂未填写专业' }} · {{ activity.course?.title || '全部课程' }}</p>
          <span>学习记录仅对当前账号可见</span>
        </div>
        <div class="identity-actions">
          <button class="button button--secondary" type="button" @click="router.push('/settings?section=profile')">
            <Pencil :size="16" /> 编辑资料
          </button>
          <button class="button button--secondary" type="button" @click="router.push({ path: '/workspace/resources', query: { course_id: selectedCourseId || undefined } })">
            <Bookmark :size="16" /> 收藏资源 {{ owner.favoriteCount || 0 }}
          </button>
        </div>
      </section>

      <section class="facts-band" aria-labelledby="learning-facts-title">
        <div class="section-heading">
          <div>
            <p class="section-kicker">学习投入</p>
            <h2 id="learning-facts-title">最近学习事实</h2>
          </div>
          <div class="period-control" aria-label="统计周期">
            <button
              v-for="days in [7, 30, 90]"
              :key="days"
              type="button"
              :class="{ active: selectedDays === days }"
              :aria-pressed="selectedDays === days"
              @click="changePeriod(days)"
            >
              {{ days }} 天
            </button>
          </div>
        </div>

        <div class="metric-grid">
          <article class="metric-item">
            <Clock3 :size="19" />
            <span>今日学习</span>
            <strong>{{ minutes(metricValue('todayMinutes')) }}</strong>
          </article>
          <article class="metric-item">
            <CalendarDays :size="19" />
            <span>近 7 天学习</span>
            <strong>{{ minutes(metricValue('weekMinutes')) }}</strong>
          </article>
          <article class="metric-item">
            <History :size="19" />
            <span>{{ periodLabel }}累计</span>
            <strong>{{ minutes(metricValue('periodMinutes')) }}</strong>
          </article>
          <article class="metric-item">
            <RouteIcon :size="19" />
            <span>连续学习</span>
            <strong>{{ metricValue('streakDays') ?? '暂不可用' }}<template v-if="metricValue('streakDays') != null"> 天</template></strong>
          </article>
        </div>

        <div class="heatmap-panel" data-testid="profile-heatmap">
          <div class="heatmap-copy">
            <h3>近 30 天学习热力图</h3>
            <p>有明确时长、完成效果或已接受掌握证据的日期才会着色。</p>
          </div>
          <div class="heatmap-grid" role="img" aria-label="近三十天有效学习活动">
            <span
              v-for="day in heatmap"
              :key="day.date"
              class="heatmap-cell"
              :class="`level-${heatLevel(day)}`"
              :title="heatTitle(day)"
              :aria-label="heatTitle(day)"
            />
          </div>
          <details class="calculation-details">
            <summary>查看统计口径与来源</summary>
            <p>{{ activity.calculation?.duration }}</p>
            <p>统计区间：{{ activity.period?.startDate }} 至 {{ activity.period?.endDate }}（{{ activity.period?.timezone }}）</p>
            <p>本期来源事件：{{ report?.sourceEventIds?.length || 0 }} 条</p>
          </details>
        </div>
      </section>

      <section class="insight-grid">
        <article class="content-panel" data-testid="profile-trend">
          <div class="panel-heading">
            <div>
              <p class="section-kicker">掌握变化</p>
              <h2>学习趋势</h2>
            </div>
            <span>{{ periodLabel }}</span>
          </div>
          <LearningTrendChart :points="trend" />
          <p class="panel-footnote">掌握变化只使用已处理的有效证据；近 30 天另有 {{ activityPoints.reduce((sum, item) => sum + Number(item.eventCount || 0), 0) }} 条有效学习活动。</p>
        </article>

        <article class="content-panel" data-testid="profile-activity">
          <div class="panel-heading">
            <div>
              <p class="section-kicker">学习记录</p>
              <h2>最近学习动态</h2>
            </div>
            <button class="text-action" type="button" @click="router.push({ path: '/profile/history', query: { course_id: selectedCourseId || undefined, days: selectedDays } })">
              查看全部 <ArrowRight :size="15" />
            </button>
          </div>
          <div v-if="recentItems.length" class="activity-list">
            <button
              v-for="item in recentItems"
              :key="item.id"
              class="activity-row"
              type="button"
              :disabled="!item.target?.available"
              @click="openTarget(item.target)"
            >
              <span class="activity-dot" :class="{ 'is-evidence': item.evidence?.masteryEligible }" />
              <span class="activity-main">
                <strong>{{ item.label }}</strong>
                <small>{{ item.course?.title }} · {{ formatTime(item.occurredAt) }}</small>
              </span>
              <span class="activity-action">{{ item.target?.label || '查看记录' }}</span>
              <ArrowRight :size="15" />
            </button>
          </div>
          <div v-else class="empty-panel">
            <History :size="24" />
            <strong>所选范围内还没有学习记录</strong>
            <p>开始一个今日任务后，真实动态会出现在这里。</p>
            <button class="button button--primary" type="button" @click="router.push('/workspace')">进入学习空间</button>
          </div>
        </article>
      </section>

      <section class="summary-grid">
        <article class="content-panel" data-testid="profile-summary">
          <div class="panel-heading">
            <div>
              <p class="section-kicker">学习画像</p>
              <h2>最近画像摘要</h2>
            </div>
            <button class="text-action" type="button" @click="openTarget(activity.profile?.fullProfileRoute, '/profile/learning')">
              完整画像 <ArrowRight :size="15" />
            </button>
          </div>
          <div v-if="profileSections.length" class="profile-summary-list">
            <div v-for="section in profileSections" :key="section.key" class="profile-summary-row">
              <div>
                <span>{{ section.title }}</span>
                <strong>{{ section.headline }}</strong>
              </div>
              <button
                v-if="routeFor(section.nextAction)"
                class="text-action"
                type="button"
                @click="openTarget(section.nextAction)"
              >
                {{ section.nextAction.title || '查看下一步' }}
              </button>
            </div>
          </div>
          <div v-else class="empty-panel empty-panel--compact">
            <UserRound :size="23" />
            <strong>当前课程还没有足够的画像证据</strong>
            <p>完成入学诊断或一次有效学习任务后再查看。</p>
          </div>
        </article>

        <article class="content-panel" data-testid="profile-report">
          <div class="panel-heading">
            <div>
              <p class="section-kicker">阶段报告</p>
              <h2>{{ report?.title || '学习报告' }}</h2>
            </div>
            <FileText :size="20" />
          </div>
          <p class="report-summary">{{ report?.summary || '当前没有可汇总的学习事实。' }}</p>
          <dl class="report-highlights">
            <div v-for="item in report?.highlights || []" :key="item.label">
              <dt>{{ item.label }}</dt>
              <dd>{{ item.value }} {{ item.unit }}</dd>
            </div>
          </dl>
          <div class="report-actions">
            <button
              class="button button--primary"
              type="button"
              :disabled="!routeFor(report?.primaryAction, '/workspace/path')"
              @click="openTarget(report?.primaryAction, '/workspace/path')"
            >
              {{ report?.primaryAction?.label || '查看学习路径' }} <ArrowRight :size="16" />
            </button>
            <button class="button button--secondary" type="button" @click="openTarget(report?.historyRoute, '/profile/history')">
              查看报告依据
            </button>
          </div>
        </article>
      </section>
    </template>
  </main>
</template>

<style scoped>
.profile-page {
  display: grid;
  width: min(100%, 1180px);
  margin: 0 auto;
  gap: 24px;
  color: var(--color-text);
  font-family: var(--font-sans);
}

.profile-page :is(h1, h2, h3, h4) {
  font-family: var(--font-heading);
  line-height: var(--line-height-heading);
}

.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}

.course-picker select {
  min-width: 210px;
  height: 40px;
  padding: 0 34px 0 12px;
  color: var(--color-text);
  background: var(--color-surface);
  border: 1px solid var(--color-border-strong);
  border-radius: var(--radius-control);
  font: 500 14px/1 var(--font-sans);
}

.profile-state {
  display: flex;
  min-height: 420px;
  align-items: center;
  justify-content: center;
  gap: 16px;
  padding: 32px;
  color: var(--color-text-secondary);
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-panel);
}

.profile-state strong,
.profile-state p {
  display: block;
  margin: 0;
  font-size: 15px;
  line-height: 1.6;
}

.profile-state--error { color: var(--color-danger); }
.spin { animation: spin 0.8s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }

.identity-band,
.facts-band,
.content-panel {
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-panel);
}

.identity-band {
  display: grid;
  grid-template-columns: 58px minmax(0, 1fr) auto;
  align-items: center;
  gap: 16px;
  padding: 24px var(--space-panel-inline);
}

.avatar {
  display: grid;
  width: 54px;
  height: 54px;
  place-items: center;
  color: #ffffff;
  background: var(--color-accent);
  border-radius: 50%;
  font-size: 20px;
  font-weight: 700;
}

.identity-copy { min-width: 0; }
.identity-copy h2 { margin: 0; font-size: 20px; line-height: var(--line-height-heading); }
.identity-copy p,
.identity-copy span { margin: 4px 0 0; color: var(--color-text-secondary); font-size: 14px; line-height: 1.5; }
.identity-copy span { color: var(--color-text-muted); }
.identity-actions,
.report-actions { display: flex; align-items: center; gap: 8px; }

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
.button:disabled { cursor: not-allowed; opacity: 0.55; }
.button:focus-visible,
.text-action:focus-visible,
.activity-row:focus-visible,
.period-control button:focus-visible,
.course-picker select:focus-visible { outline: 3px solid #9ba8ab; outline-offset: 2px; }

.facts-band { padding: 26px var(--space-panel-inline); }
.section-heading,
.panel-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; }
.section-kicker { margin: 0 0 3px; color: var(--color-text-muted); font-size: 14px; font-weight: 600; line-height: 1.4; }
.section-heading h2,
.panel-heading h2 { margin: 0; font-size: 20px; line-height: var(--line-height-heading); }

.period-control {
  display: inline-grid;
  grid-template-columns: repeat(3, 64px);
  padding: 3px;
  background: var(--color-surface-subtle);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-control);
}
.period-control button {
  min-height: 34px;
  color: var(--color-text-secondary);
  background: transparent;
  border: 0;
  border-radius: 4px;
  font: 600 14px/1 var(--font-sans);
  cursor: pointer;
}
.period-control button.active { color: #ffffff; background: var(--color-accent); }

.metric-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  margin-top: 20px;
  border-block: 1px solid var(--color-border);
}
.metric-item {
  display: grid;
  min-width: 0;
  grid-template-columns: auto 1fr;
  gap: 4px 10px;
  padding: 20px 18px;
  border-right: 1px solid var(--color-border);
}
.metric-item:last-child { border-right: 0; }
.metric-item svg { grid-row: 1 / span 2; align-self: center; color: var(--color-text-secondary); }
.metric-item span { color: var(--color-text-muted); font-size: 14px; line-height: 1.4; }
.metric-item strong { overflow-wrap: anywhere; font-size: 18px; line-height: 1.35; }

.heatmap-panel {
  display: grid;
  grid-template-columns: minmax(220px, 0.8fr) minmax(360px, 1.4fr);
  align-items: center;
  gap: 18px 28px;
  padding-top: 20px;
}
.heatmap-copy h3 { margin: 0; font-size: 16px; line-height: 1.45; }
.heatmap-copy p,
.calculation-details p,
.panel-footnote { margin: 5px 0 0; color: var(--color-text-muted); font-size: 14px; line-height: 1.6; }
.heatmap-grid { display: grid; grid-template-columns: repeat(10, minmax(18px, 1fr)); gap: 6px; }
.heatmap-cell { aspect-ratio: 1; min-width: 18px; background: var(--color-surface-subtle); border: 1px solid var(--color-border); border-radius: 3px; }
.heatmap-cell.level-1 { background: #dce2e3; }
.heatmap-cell.level-2 { background: #9ba8ab; border-color: #9ba8ab; }
.heatmap-cell.level-3 { background: #253745; border-color: #253745; }
.calculation-details { grid-column: 1 / -1; color: var(--color-text-secondary); font-size: 14px; }
.calculation-details summary { width: fit-content; cursor: pointer; font-weight: 600; }

.insight-grid,
.summary-grid { display: grid; grid-template-columns: minmax(0, 1.15fr) minmax(0, 0.85fr); gap: 20px; }
.summary-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
.content-panel { min-width: 0; padding: var(--space-panel-inline); }
.panel-heading { align-items: center; margin-bottom: 16px; }
.panel-heading > span,
.panel-heading > svg { color: var(--color-text-muted); font-size: 14px; }
.panel-footnote { margin-top: 10px; }

.text-action {
  display: inline-flex;
  min-height: 36px;
  align-items: center;
  gap: 5px;
  padding: 0 4px;
  color: var(--color-accent);
  background: transparent;
  border: 0;
  font: 650 14px/1 var(--font-sans);
  cursor: pointer;
}

.activity-list,
.profile-summary-list { border-top: 1px solid var(--color-border); }
.activity-row {
  display: grid;
  width: 100%;
  min-height: 58px;
  grid-template-columns: 10px minmax(0, 1fr) auto 16px;
  align-items: center;
  gap: 10px;
  padding: 10px 4px;
  color: var(--color-text);
  background: transparent;
  border: 0;
  border-bottom: 1px solid var(--color-border);
  text-align: left;
  cursor: pointer;
}
.activity-row:disabled { cursor: default; }
.activity-dot { width: 8px; height: 8px; background: var(--color-text-muted); border-radius: 50%; }
.activity-dot.is-evidence { background: var(--color-accent); box-shadow: 0 0 0 3px var(--color-accent-soft); }
.activity-main { min-width: 0; }
.activity-main strong,
.activity-main small { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.activity-main strong { font-size: 14px; line-height: 1.5; }
.activity-main small { color: var(--color-text-muted); font-size: 14px; line-height: 1.45; }
.activity-action { color: var(--color-text-secondary); font-size: 14px; }
.activity-row:disabled .activity-action { color: var(--color-text-muted); }

.empty-panel {
  display: grid;
  min-height: 220px;
  place-items: center;
  align-content: center;
  gap: 8px;
  color: var(--color-text-muted);
  border-block: 1px solid var(--color-border);
  text-align: center;
}
.empty-panel--compact { min-height: 180px; }
.empty-panel strong,
.empty-panel p { margin: 0; font-size: 14px; line-height: 1.6; }

.profile-summary-row {
  display: flex;
  min-height: 72px;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 12px 2px;
  border-bottom: 1px solid var(--color-border);
}
.profile-summary-row span,
.profile-summary-row strong { display: block; font-size: 14px; line-height: 1.5; }
.profile-summary-row span { color: var(--color-text-muted); }
.profile-summary-row strong { margin-top: 3px; color: var(--color-text); }

.report-summary { min-height: 52px; margin: 0 0 14px; color: var(--color-text-secondary); font-size: 15px; line-height: 1.7; }
.report-highlights { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); margin: 0 0 18px; border-block: 1px solid var(--color-border); }
.report-highlights div { padding: 14px 10px; border-right: 1px solid var(--color-border); }
.report-highlights div:last-child { border-right: 0; }
.report-highlights dt { color: var(--color-text-muted); font-size: 14px; line-height: 1.4; }
.report-highlights dd { margin: 5px 0 0; color: var(--color-text); font-size: 16px; font-weight: 700; line-height: 1.4; }

@media (max-width: 1120px) {
  .identity-band { grid-template-columns: 58px minmax(0, 1fr); }
  .identity-actions { grid-column: 1 / -1; padding-left: 74px; }
  .insight-grid,
  .summary-grid { grid-template-columns: 1fr; }
}

@media (max-width: 900px) {
  .metric-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .metric-item:nth-child(2) { border-right: 0; }
  .metric-item:nth-child(-n+2) { border-bottom: 1px solid var(--color-border); }
  .heatmap-panel { grid-template-columns: 1fr; }
  .calculation-details { grid-column: auto; }
}
</style>
