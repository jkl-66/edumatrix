<script setup>
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  AlertCircle,
  ArrowLeft,
  BookOpen,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Clock3,
  FileText,
  FolderOpen,
  Layers3,
  ListChecks,
  LoaderCircle,
  RefreshCw,
  ShieldCheck,
  Sparkles,
  UserRound,
  Users,
} from '@lucide/vue'
import {
  createTeacherIntervention,
  getTeacherCourse,
  getTeacherCourses,
  getTeacherOverview,
  getTeacherStudent,
  getTeacherStudents,
} from '../api/teacher'
import SearchField from '../components/ui/SearchField.vue'

const route = useRoute()
const router = useRouter()

const payload = ref(null)
const loading = ref(true)
const refreshing = ref(false)
const error = ref('')
const studentSearch = ref('')
const courseSearch = ref('')
const courseTab = ref('chapters')
const interventionState = ref('idle')
const interventionMessage = ref('')
let requestSequence = 0
let interventionKey = ''

const viewMode = computed(() => ({
  TeacherOverview: 'overview',
  TeacherCourses: 'courses',
  TeacherCourseDetail: 'course-detail',
  TeacherStudents: 'students',
  TeacherStudentDetail: 'student-detail',
}[route.name] || 'overview'))

const heading = computed(() => ({
  overview: ['教学总览', '先处理当前课程的教学任务，再查看薄弱点和需关注学生。'],
  courses: ['课程与资源', '查看授权课程的章节、来源、资源和班级事实。'],
  'course-detail': [payload.value?.course?.title || '课程详情', '核对课程内容与教学任务，所有数据来自当前授权课程。'],
  students: ['学生学情', '按课程查找学生，依据学习证据决定下一步教学动作。'],
  'student-detail': [payload.value?.student?.displayName || '学生详情', '只读查看画像、路径和学习证据；掌握度不能在教师端直接修改。'],
}[viewMode.value]))

const courses = computed(() => {
  if (viewMode.value === 'courses') return payload.value?.items || []
  return payload.value?.courses || []
})

const filteredCourses = computed(() => {
  const query = courseSearch.value.trim().toLowerCase()
  if (!query) return courses.value
  return courses.value.filter((course) => [course.title, course.subject, course.description]
    .some((value) => String(value || '').toLowerCase().includes(query)))
})

const selectedCourseId = computed(() => (
  payload.value?.selectedCourse?.id
  || payload.value?.course?.id
  || route.query.courseId
  || ''
))

const courseDetailRows = computed(() => ({
  chapters: payload.value?.chapters || [],
  sources: payload.value?.sources || [],
  resources: payload.value?.resources || [],
  classes: payload.value?.classes || [],
}[courseTab.value] || []))

const courseTabs = [
  { id: 'chapters', label: '章节', icon: Layers3 },
  { id: 'sources', label: '来源', icon: FileText },
  { id: 'resources', label: '资源', icon: FolderOpen },
  { id: 'classes', label: '班级与任务', icon: Users },
]

function percentage(value) {
  return Number.isFinite(Number(value)) ? `${Math.round(Number(value) * 100)}%` : '证据不足'
}

function formatTime(value) {
  if (!value) return '未设置'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString('zh-CN', {
    month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit',
  })
}

function evidenceLabel(state) {
  return {
    sufficient: '证据充分',
    snapshot_only: '仅有快照',
    insufficient: '证据不足',
  }[state] || '待核对'
}

function statusLabel(state) {
  return {
    complete: '已读取',
    empty: '暂无数据',
    failed: '读取失败',
    accepted: '已采纳',
    rejected: '未采纳',
    published: '已发布',
    draft: '草稿',
    active: '进行中',
    completed: '已完成',
  }[state] || state || '未知'
}

function actionTitle(action, fallback = '暂无下一步建议') {
  if (!action) return fallback
  if (typeof action === 'string') return action
  return action.title || fallback
}

function actionReason(action) {
  return action && typeof action === 'object' ? action.reason || '' : ''
}

function errorMessage(value) {
  if (value?.kind === 'forbidden') return '当前账号没有查看这一教学范围的权限。'
  if (value?.kind === 'not_found') return '课程或学生不在当前教学范围。'
  return value?.detail || value?.message || '教学数据暂时无法读取，请稍后重试。'
}

async function loadPage({ preserve = false } = {}) {
  const sequence = ++requestSequence
  if (preserve && payload.value) refreshing.value = true
  else {
    payload.value = null
    loading.value = true
  }
  error.value = ''
  interventionState.value = 'idle'
  interventionMessage.value = ''

  try {
    let result
    const courseId = String(route.query.courseId || '')
    if (viewMode.value === 'overview') {
      result = await getTeacherOverview(courseId || undefined)
    } else if (viewMode.value === 'courses') {
      result = await getTeacherCourses()
    } else if (viewMode.value === 'course-detail') {
      result = await getTeacherCourse(String(route.params.courseId))
    } else {
      const courseResult = await getTeacherCourses()
      const activeCourseId = courseId || courseResult.items?.[0]?.id || ''
      if (viewMode.value === 'students') {
        const studentResult = activeCourseId
          ? await getTeacherStudents({ courseId: activeCourseId, query: String(route.query.q || '') })
          : { state: 'empty', course: null, items: [] }
        result = { ...studentResult, courses: courseResult.items || [] }
      } else if (activeCourseId) {
        const studentResult = await getTeacherStudent(String(route.params.studentId), activeCourseId)
        result = { ...studentResult, courses: courseResult.items || [] }
      } else {
        result = { state: 'empty', courses: [], student: null, profile: null, evidenceTimeline: [] }
      }
    }
    if (sequence === requestSequence) payload.value = result
  } catch (value) {
    if (sequence === requestSequence) error.value = errorMessage(value)
  } finally {
    if (sequence === requestSequence) {
      loading.value = false
      refreshing.value = false
    }
  }
}

function replaceQuery(next) {
  router.replace({ path: route.path, query: { ...route.query, ...next } })
}

function selectCourse(courseId) {
  replaceQuery({ courseId: courseId || undefined, q: undefined })
}

function searchStudents() {
  replaceQuery({ q: studentSearch.value.trim() || undefined })
}

function openCourse(courseId) {
  router.push(`/teacher/courses/${encodeURIComponent(courseId)}`)
}

function openStudent(studentId, courseId = selectedCourseId.value) {
  router.push({
    path: `/teacher/students/${encodeURIComponent(studentId)}`,
    query: courseId ? { courseId } : {},
  })
}

function backToStudents() {
  router.push({ path: '/teacher/students', query: selectedCourseId.value ? { courseId: selectedCourseId.value } : {} })
}

async function createIntervention() {
  const studentId = payload.value?.student?.publicId
  const courseId = payload.value?.course?.id
  if (!studentId || !courseId || interventionState.value === 'submitting') return
  if (!interventionKey) {
    interventionKey = `teacher-${courseId}-${studentId}-${Date.now()}`.slice(0, 128)
  }
  interventionState.value = 'submitting'
  interventionMessage.value = ''
  try {
    const result = await createTeacherIntervention({
      courseId,
      studentId,
      idempotencyKey: interventionKey,
    })
    interventionState.value = 'complete'
    interventionMessage.value = result.created
      ? '干预任务已加入学生路径，学生将在学习空间看到下一步任务。'
      : '该干预任务已经存在，没有重复创建。'
  } catch (value) {
    interventionState.value = 'failed'
    interventionMessage.value = errorMessage(value)
  }
}

watch(
  () => route.fullPath,
  () => {
    studentSearch.value = String(route.query.q || '')
    courseTab.value = 'chapters'
    interventionKey = ''
    loadPage()
  },
  { immediate: true },
)
</script>

<template>
  <main class="teacher-workspace" data-testid="teacher-workspace">
    <header class="teacher-heading">
      <div class="heading-copy">
        <button
          v-if="viewMode === 'course-detail'"
          type="button"
          class="back-button"
          aria-label="返回课程列表"
          title="返回课程列表"
          @click="router.push('/teacher/courses')"
        >
          <ArrowLeft :size="18" />
        </button>
        <button
          v-else-if="viewMode === 'student-detail'"
          type="button"
          class="back-button"
          aria-label="返回学生列表"
          title="返回学生列表"
          @click="backToStudents"
        >
          <ArrowLeft :size="18" />
        </button>
        <div>
          <h1>{{ heading[0] }}</h1>
          <p>{{ heading[1] }}</p>
        </div>
      </div>
      <button
        v-if="payload"
        type="button"
        class="icon-button"
        :disabled="refreshing"
        aria-label="刷新当前教学数据"
        title="刷新当前教学数据"
        @click="loadPage({ preserve: true })"
      >
        <RefreshCw :size="18" :class="{ spinning: refreshing }" />
      </button>
    </header>

    <section v-if="loading" class="state-panel" aria-live="polite">
      <LoaderCircle :size="24" class="spinning" />
      <div><strong>正在读取教学数据</strong><p>课程范围和学习证据正在校验。</p></div>
    </section>

    <section v-else-if="error && !payload" class="state-panel state-panel--error" role="alert">
      <AlertCircle :size="24" />
      <div><strong>教学数据暂时无法读取</strong><p>{{ error }}</p></div>
      <button type="button" class="primary-action" @click="loadPage()">重新读取</button>
    </section>

    <template v-else-if="payload">
      <div v-if="error" class="inline-state" role="alert">
        <AlertCircle :size="18" />
        <span>{{ error }} 已保留上一次读取结果。</span>
        <button type="button" @click="loadPage({ preserve: true })">重试</button>
      </div>

      <template v-if="viewMode === 'overview'">
        <section v-if="payload.state === 'empty'" class="state-panel">
          <BookOpen :size="24" />
          <div><strong>暂无可查看课程</strong><p>当前账号还没有有效的课程教学关系。</p></div>
        </section>
        <template v-else>
          <div class="context-toolbar">
            <label for="overview-course">当前课程</label>
            <select id="overview-course" :value="selectedCourseId" @change="selectCourse($event.target.value)">
              <option v-for="course in courses" :key="course.id" :value="course.id">{{ course.title }}</option>
            </select>
            <span class="snapshot-note">更新于 {{ formatTime(payload.updatedAt) }}</span>
            <button type="button" class="primary-action" @click="router.push({ path: '/teacher/students', query: { courseId: selectedCourseId } })">
              查看需关注学生 <ChevronRight :size="18" />
            </button>
          </div>

          <section class="fact-strip" aria-label="当前课程教学摘要">
            <div><span>授权课程</span><strong>{{ payload.summary?.courseCount || 0 }}</strong></div>
            <div><span>课程学生</span><strong>{{ payload.summary?.studentCount || 0 }}</strong></div>
            <div><span>需要关注</span><strong>{{ payload.summary?.attentionCount || 0 }}</strong></div>
            <div><span>待办任务</span><strong>{{ payload.summary?.pendingTaskCount || 0 }}</strong></div>
          </section>

          <section class="workspace-section">
            <div class="section-heading">
              <div><h2>待处理教学任务</h2><p>先确认当前课程仍需发布或跟进的任务。</p></div>
              <button type="button" class="text-action" @click="openCourse(selectedCourseId)">查看课程</button>
            </div>
            <div v-if="payload.pendingTasks?.length" class="row-list">
              <div v-for="task in payload.pendingTasks" :key="task.id" class="task-row">
                <ListChecks :size="18" />
                <div><strong>{{ task.title }}</strong><span>{{ task.classTitle }} · {{ statusLabel(task.status) }}</span></div>
                <time>{{ task.dueAt ? `截止 ${formatTime(task.dueAt)}` : '未设置截止时间' }}</time>
              </div>
            </div>
            <div v-else class="section-empty">当前课程没有待处理教学任务。</div>
          </section>

          <div class="evidence-grid">
            <section class="workspace-section">
              <div class="section-heading"><div><h2>集中薄弱点</h2><p>按需关注学生数排序，不使用虚构掌握度。</p></div></div>
              <div v-if="payload.weakPoints?.length" class="row-list">
                <div v-for="point in payload.weakPoints" :key="point.title" class="signal-row">
                  <span class="signal-index">{{ point.studentCount }}</span>
                  <strong>{{ point.title }}</strong>
                  <span>{{ point.studentCount }} 名学生需要关注</span>
                </div>
              </div>
              <div v-else class="section-empty">当前没有形成稳定的集中薄弱点。</div>
            </section>

            <section class="workspace-section">
              <div class="section-heading"><div><h2>需关注学生</h2><p>依据画像证据和路径进度生成，不支持直接修改掌握度。</p></div></div>
              <div v-if="payload.attentionStudents?.length" class="row-list">
                <button
                  v-for="student in payload.attentionStudents"
                  :key="student.publicId"
                  type="button"
                  class="student-signal"
                  @click="openStudent(student.publicId)"
                >
                  <span class="avatar">{{ student.displayName.slice(0, 1) }}</span>
                  <span><strong>{{ student.displayName }}</strong><small>{{ student.attentionReason }}</small></span>
                  <ChevronRight :size="18" />
                </button>
              </div>
              <div v-else class="section-empty">当前没有需要优先关注的学生。</div>
            </section>
          </div>
        </template>
      </template>

      <template v-else-if="viewMode === 'courses'">
        <div class="filter-toolbar">
          <SearchField v-model="courseSearch" class="teacher-search-field" aria-label="搜索课程、方向或简介" placeholder="搜索课程、方向或简介" />
          <span>{{ filteredCourses.length }} 门授权课程</span>
        </div>
        <section v-if="filteredCourses.length" class="course-list">
          <article v-for="course in filteredCourses" :key="course.id" class="course-row">
            <div class="course-mark"><BookOpen :size="20" /></div>
            <div class="course-main">
              <h2>{{ course.title }}</h2>
              <p>{{ course.description || course.subject || '尚未填写课程简介' }}</p>
              <div class="course-facts">
                <span>{{ course.counts?.chapters || 0 }} 章</span>
                <span>{{ course.counts?.sources || 0 }} 个来源</span>
                <span>{{ course.counts?.resources || 0 }} 份资源</span>
                <span>{{ course.counts?.students || 0 }} 名学生</span>
              </div>
            </div>
            <button type="button" class="row-action" @click="openCourse(course.id)">
              打开课程 <ChevronRight :size="18" />
            </button>
          </article>
        </section>
        <section v-else class="state-panel">
          <BookOpen :size="24" />
          <div><strong>{{ courses.length ? '没有匹配课程' : '暂无可查看课程' }}</strong><p>{{ courses.length ? '请调整搜索关键词。' : '当前账号还没有有效的课程教学关系。' }}</p></div>
        </section>
      </template>

      <template v-else-if="viewMode === 'course-detail'">
        <section class="fact-strip fact-strip--course" aria-label="课程内容摘要">
          <div><span>章节</span><strong>{{ payload.course?.counts?.chapters || 0 }}</strong></div>
          <div><span>来源</span><strong>{{ payload.course?.counts?.sources || 0 }}</strong></div>
          <div><span>资源</span><strong>{{ payload.course?.counts?.resources || 0 }}</strong></div>
          <div><span>学生</span><strong>{{ payload.course?.counts?.students || 0 }}</strong></div>
          <div><span>开放任务</span><strong>{{ payload.course?.counts?.openTasks || 0 }}</strong></div>
        </section>
        <div class="segment-control" role="tablist" aria-label="课程内容分类">
          <button
            v-for="tab in courseTabs"
            :key="tab.id"
            type="button"
            role="tab"
            :aria-selected="courseTab === tab.id"
            :class="{ active: courseTab === tab.id }"
            @click="courseTab = tab.id"
          >
            <component :is="tab.icon" :size="17" /> {{ tab.label }}
          </button>
        </div>
        <section class="workspace-section course-detail-section">
          <div v-if="courseDetailRows.length" class="row-list">
            <div v-for="item in courseDetailRows" :key="item.id" class="detail-row">
              <template v-if="courseTab === 'chapters'">
                <span class="sequence">{{ item.position ?? '-' }}</span>
                <div><strong>{{ item.title }}</strong><span>已关联课程来源</span></div>
                <span>{{ item.headingLevel ? `层级 ${item.headingLevel}` : '标准章节' }}</span>
              </template>
              <template v-else-if="courseTab === 'sources'">
                <FileText :size="18" />
                <div><strong>{{ item.title }}</strong><span>{{ item.filename || item.fileFormat || '课程来源文件' }}</span></div>
                <span>{{ item.licenseText || statusLabel(item.processingStatus) }}</span>
              </template>
              <template v-else-if="courseTab === 'resources'">
                <FolderOpen :size="18" />
                <div><strong>{{ item.title }}</strong><span>{{ item.type || '学习资源' }}</span></div>
                <span>{{ statusLabel(item.status) }} · {{ formatTime(item.updatedAt) }}</span>
              </template>
              <template v-else>
                <Users :size="18" />
                <div><strong>{{ item.title }}</strong><span>{{ item.term || '未设置学期' }}</span></div>
                <span>{{ item.members?.length || 0 }} 名成员 · {{ item.tasks?.length || 0 }} 项任务</span>
              </template>
            </div>
          </div>
          <div v-else class="section-empty">当前分类还没有可显示内容。</div>
        </section>
      </template>

      <template v-else-if="viewMode === 'students'">
        <form class="filter-toolbar" @submit.prevent="searchStudents">
          <label class="course-filter">
            <span>课程</span>
            <select :value="selectedCourseId" @change="selectCourse($event.target.value)">
              <option v-for="course in courses" :key="course.id" :value="course.id">{{ course.title }}</option>
            </select>
          </label>
          <SearchField v-model="studentSearch" class="teacher-search-field" aria-label="搜索姓名或账号" placeholder="搜索姓名或账号" />
          <button type="submit" class="secondary-action">查找</button>
        </form>
        <section v-if="payload.items?.length" class="student-table" aria-label="学生证据列表">
          <div class="student-row student-row--header" aria-hidden="true">
            <span>学生</span><span>主要薄弱点</span><span>证据状态</span><span>路径进度</span><span>进入</span>
          </div>
          <div v-for="student in payload.items" :key="student.publicId" class="student-row">
            <div class="student-name"><span class="avatar">{{ student.displayName.slice(0, 1) }}</span><span><strong>{{ student.displayName }}</strong><small>{{ student.username }}</small></span></div>
            <div><strong>{{ student.weakestPoint?.title || '尚未形成结论' }}</strong><small>{{ actionTitle(student.nextAction, student.evidenceMessage) }}</small></div>
            <span class="status-text" :data-state="student.evidenceState">{{ evidenceLabel(student.evidenceState) }}</span>
            <div><strong>{{ percentage(student.path?.completionRate) }}</strong><small>{{ student.path?.nextTask?.title || '暂无下一任务' }}</small></div>
            <button type="button" class="icon-button" :aria-label="`查看${student.displayName}的学情`" :title="`查看${student.displayName}的学情`" @click="openStudent(student.publicId)">
              <ChevronRight :size="18" />
            </button>
          </div>
        </section>
        <section v-else class="state-panel">
          <Users :size="24" />
          <div><strong>{{ courses.length ? '没有匹配学生' : '暂无可查看课程' }}</strong><p>{{ courses.length ? '请调整课程或搜索条件。' : '当前账号还没有有效的课程教学关系。' }}</p></div>
        </section>
      </template>

      <template v-else>
        <section v-if="payload.state === 'empty'" class="state-panel">
          <UserRound :size="24" />
          <div><strong>暂无可查看学生</strong><p>当前账号还没有有效的课程教学关系。</p></div>
        </section>
        <template v-else>
          <section class="student-summary">
            <span class="avatar avatar--large">{{ payload.student?.displayName?.slice(0, 1) }}</span>
            <div><h2>{{ payload.student?.displayName }}</h2><p>{{ payload.course?.title }} · {{ payload.student?.username }}</p></div>
            <span class="status-text" :data-state="payload.profile?.evidenceState">{{ evidenceLabel(payload.profile?.evidenceState) }}</span>
          </section>

          <div class="student-detail-grid">
            <section class="workspace-section">
              <div class="section-heading"><div><h2>画像与路径</h2><p>{{ payload.profile?.evidenceMessage }}</p></div><span class="readonly-mark"><ShieldCheck :size="17" /> 掌握度只读</span></div>
              <div class="path-line">
                <div><span>学习路径</span><strong>{{ percentage(payload.student?.path?.completionRate) }}</strong></div>
                <div><span>已完成</span><strong>{{ payload.student?.path?.completed || 0 }} / {{ payload.student?.path?.total || 0 }}</strong></div>
                <div><span>下一任务</span><strong>{{ payload.student?.path?.nextTask?.title || '暂无任务' }}</strong></div>
              </div>
              <h3>需要关注的知识点</h3>
              <div v-if="payload.profile?.weakPoints?.length" class="weak-list">
                <details v-for="point in payload.profile.weakPoints" :key="point.id">
                  <summary>
                    <span><strong>{{ point.title }}</strong><small>{{ point.judgement }}</small></span>
                    <span>{{ percentage(point.mastery) }} · {{ point.evidenceCount }} 条证据</span>
                    <ChevronDown :size="17" />
                  </summary>
                  <div class="weak-detail">
                    <p><strong>建议动作：</strong>{{ actionTitle(point.nextAction) }}</p>
                    <p v-if="actionReason(point.nextAction)"><strong>建议理由：</strong>{{ actionReason(point.nextAction) }}</p>
                    <p><strong>证据置信：</strong>{{ percentage(point.confidence) }}</p>
                    <p v-if="point.sourceEventIds?.length"><strong>授权证据编号：</strong>{{ point.sourceEventIds.join('、') }}</p>
                    <p v-else>当前没有可下钻的学习事件。</p>
                  </div>
                </details>
              </div>
              <div v-else class="section-empty">当前证据不足，暂不形成薄弱点判断。</div>
            </section>

            <aside class="intervention-panel" aria-live="polite">
              <Sparkles :size="22" />
              <h2>安排下一步教学动作</h2>
              <p>根据当前薄弱点创建学习干预。该动作只增加路径任务，不会直接修改学生掌握度。</p>
              <button
                v-if="payload.actions?.canCreateIntervention && interventionState !== 'complete'"
                type="button"
                class="primary-action primary-action--wide"
                :disabled="interventionState === 'submitting'"
                @click="createIntervention"
              >
                <LoaderCircle v-if="interventionState === 'submitting'" :size="18" class="spinning" />
                <CheckCircle2 v-else :size="18" />
                {{ interventionState === 'submitting' ? '正在创建' : interventionState === 'failed' ? '重试创建干预' : '创建学习干预' }}
              </button>
              <div v-if="interventionMessage" class="intervention-result" :data-state="interventionState">
                <CheckCircle2 v-if="interventionState === 'complete'" :size="18" />
                <AlertCircle v-else :size="18" />
                <span>{{ interventionMessage }}</span>
              </div>
            </aside>
          </div>

          <section class="workspace-section">
            <div class="section-heading"><div><h2>学习证据</h2><p>按时间查看可信学习事件；普通浏览不会写入新证据。</p></div></div>
            <div v-if="payload.evidenceTimeline?.length" class="timeline">
              <details v-for="event in payload.evidenceTimeline" :key="event.sourceEventId">
                <summary>
                  <Clock3 :size="17" />
                  <span><strong>{{ event.objectType || event.eventType }}</strong><small>{{ event.source }} · {{ formatTime(event.occurredAt) }}</small></span>
                  <span>{{ statusLabel(event.evidenceStatus) }} · {{ event.evidenceStrength || '未分级' }}</span>
                  <ChevronDown :size="17" />
                </summary>
                <div class="evidence-detail">
                  <span>对象：{{ event.objectId || '未记录' }}</span>
                  <span>可用于掌握度：{{ event.masteryEligible ? '是' : '否' }}</span>
                  <span>授权证据编号：{{ event.sourceEventId }}</span>
                </div>
              </details>
            </div>
            <div v-else class="section-empty">当前没有可查看的学习事件。</div>
          </section>

          <details class="agent-audit">
            <summary>
              <span><ShieldCheck :size="18" /><strong>AI 建议的公开校验记录</strong></span>
              <span>{{ payload.agentAudit?.message }}</span>
              <ChevronDown :size="18" />
            </summary>
            <div v-if="payload.agentAudit?.state === 'complete'" class="agent-list">
              <article v-for="(agent, index) in payload.agentAudit.items" :key="`${agent.role}-${index}`">
                <header><strong>{{ agent.role }}</strong><span>{{ statusLabel(agent.status) }}</span></header>
                <p><b>候选：</b>{{ agent.candidateSummary || '未记录候选摘要' }}</p>
                <p><b>分歧：</b>{{ agent.disagreement || '本次没有记录分歧' }}</p>
                <p><b>校验：</b>{{ agent.validation || '未记录校验摘要' }}</p>
                <p><b>修订：</b>{{ agent.revision || '本次没有记录修订' }}</p>
                <p><b>决定：</b>{{ agent.decisionSummary || '未形成公开决定摘要' }}</p>
                <details v-if="agent.inputRefs?.length" class="source-refs"><summary>查看 {{ agent.inputRefs.length }} 个输入来源</summary><p>{{ agent.inputRefs.join('、') }}</p></details>
              </article>
            </div>
            <div v-else class="section-empty">{{ payload.agentAudit?.message || '当前没有可公开的协作证据。' }}</div>
          </details>
        </template>
      </template>
    </template>
  </main>
</template>

<style scoped>
.teacher-workspace {
  width: 100%;
  max-width: 1220px;
  margin: 0 auto;
  padding: 0 0 32px;
  color: var(--color-text);
  font-family: var(--font-sans);
  font-size: 15px;
  line-height: var(--line-height-body);
}

.teacher-heading {
  display: flex;
  min-height: 96px;
  align-items: center;
  justify-content: space-between;
  gap: 24px;
  margin-bottom: 20px;
  border-bottom: 1px solid var(--color-border);
}

.heading-copy { display: flex; min-width: 0; align-items: center; gap: 14px; }
.heading-copy h1 { margin: 0; font-size: 26px; font-weight: 720; line-height: 1.35; letter-spacing: 0; }
.heading-copy p { max-width: 760px; margin: 4px 0 0; color: var(--color-text-secondary); font-size: 15px; }

button, input, select { font: inherit; letter-spacing: 0; }
button { color: inherit; }
button:focus-visible, input:focus-visible, select:focus-visible, summary:focus-visible { outline: 3px solid var(--color-border-strong); outline-offset: 2px; }

.primary-action, .secondary-action, .row-action, .text-action, .back-button, .icon-button {
  display: inline-flex;
  min-height: 40px;
  align-items: center;
  justify-content: center;
  gap: 8px;
  border-radius: var(--radius-control);
  font-size: 15px;
  font-weight: 650;
  cursor: pointer;
}

.primary-action { padding: 0 16px; color: #fff; border: 1px solid var(--color-accent); background: var(--color-accent); }
.primary-action:hover { background: var(--color-text-secondary); }
.primary-action:disabled { cursor: wait; opacity: .62; }
.primary-action--wide { width: 100%; margin-top: 18px; }
.secondary-action { padding: 0 16px; border: 1px solid var(--color-border-strong); background: var(--color-surface); }
.secondary-action:hover, .row-action:hover, .icon-button:hover, .back-button:hover { background: var(--color-accent-soft); }
.row-action { padding: 0 10px; border: 0; background: transparent; }
.text-action { min-height: 36px; padding: 0 8px; color: var(--color-text-secondary); border: 0; background: transparent; }
.text-action:hover { color: var(--color-text); text-decoration: underline; text-underline-offset: 4px; }
.back-button, .icon-button { width: 40px; flex: 0 0 40px; padding: 0; border: 1px solid var(--color-border); background: var(--color-surface); }
.icon-button:disabled { cursor: wait; opacity: .55; }

.state-panel {
  display: flex;
  min-height: 180px;
  align-items: center;
  justify-content: center;
  gap: 16px;
  padding: 28px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-panel);
  background: var(--color-surface);
}
.state-panel strong { display: block; font-size: 17px; }
.state-panel p { margin: 2px 0 0; color: var(--color-text-secondary); font-size: 15px; }
.state-panel .primary-action { margin-left: 20px; }
.state-panel--error { color: var(--color-danger); border-color: color-mix(in srgb, var(--color-danger) 28%, var(--color-border)); }
.state-panel--error p { color: var(--color-text-secondary); }

.inline-state {
  display: flex;
  min-height: 44px;
  align-items: center;
  gap: 10px;
  margin-bottom: 16px;
  padding: 8px 12px;
  color: var(--color-danger);
  border: 1px solid color-mix(in srgb, var(--color-danger) 24%, var(--color-border));
  border-radius: var(--radius-control);
  background: var(--color-danger-soft);
  font-size: 14px;
}
.inline-state span { flex: 1; }
.inline-state button { min-height: 32px; border: 0; background: transparent; font-weight: 700; cursor: pointer; }

.context-toolbar, .filter-toolbar {
  display: flex;
  min-height: 56px;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
}
.context-toolbar label, .course-filter span { color: var(--color-text-secondary); font-size: 14px; font-weight: 650; }
.context-toolbar select, .course-filter select {
  min-width: 220px;
  height: 40px;
  padding: 0 36px 0 12px;
  color: var(--color-text);
  border: 1px solid var(--color-border-strong);
  border-radius: var(--radius-control);
  background: var(--color-surface);
}
.snapshot-note { flex: 1; color: var(--color-text-muted); font-size: 14px; }

.fact-strip {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  margin-bottom: 24px;
  border-block: 1px solid var(--color-border);
  background: var(--color-surface);
}
.fact-strip--course { grid-template-columns: repeat(5, minmax(0, 1fr)); }
.fact-strip > div { display: flex; min-height: 72px; align-items: baseline; justify-content: space-between; gap: 12px; padding: 18px; border-right: 1px solid var(--color-border); }
.fact-strip > div:last-child { border-right: 0; }
.fact-strip span { color: var(--color-text-secondary); font-size: 14px; }
.fact-strip strong { font-size: 22px; font-variant-numeric: tabular-nums; }

.workspace-section { margin-bottom: 24px; padding-top: 4px; }
.section-heading { display: flex; align-items: flex-end; justify-content: space-between; gap: 20px; margin-bottom: 12px; }
.section-heading h2, .intervention-panel h2, .student-summary h2 { margin: 0; font-size: 18px; line-height: 1.4; }
.section-heading p, .intervention-panel p, .student-summary p { margin: 3px 0 0; color: var(--color-text-secondary); font-size: 14px; }
.row-list { border-top: 1px solid var(--color-border); }
.task-row, .detail-row, .signal-row {
  display: grid;
  min-height: 58px;
  align-items: center;
  gap: 12px;
  padding: 10px 4px;
  border-bottom: 1px solid var(--color-border);
}
.task-row { grid-template-columns: 20px minmax(0, 1fr) auto; }
.task-row div, .detail-row div { display: flex; min-width: 0; flex-direction: column; }
.task-row span, .detail-row span, .signal-row span { color: var(--color-text-secondary); font-size: 14px; }
.task-row time { color: var(--color-text-muted); font-size: 14px; }
.section-empty { min-height: 72px; padding: 22px 4px; color: var(--color-text-secondary); border-block: 1px solid var(--color-border); font-size: 15px; }

.evidence-grid, .student-detail-grid { display: grid; grid-template-columns: minmax(0, 1.1fr) minmax(340px, .9fr); gap: 32px; }
.signal-row { grid-template-columns: 36px minmax(0, 1fr) auto; }
.signal-index { display: grid; width: 32px; height: 32px; place-items: center; color: var(--color-text); border-radius: 50%; background: var(--color-accent-soft); font-weight: 750; font-variant-numeric: tabular-nums; }
.student-signal { display: grid; width: 100%; min-height: 62px; grid-template-columns: 36px minmax(0, 1fr) 20px; align-items: center; gap: 12px; padding: 8px 4px; text-align: left; border: 0; border-bottom: 1px solid var(--color-border); background: transparent; cursor: pointer; }
.student-signal:hover { background: var(--color-surface-subtle); }
.student-signal > span:nth-child(2), .student-name > span:last-child { display: flex; min-width: 0; flex-direction: column; }
.student-signal small, .student-name small, .student-row small { overflow: hidden; color: var(--color-text-secondary); font-size: 14px; text-overflow: ellipsis; white-space: nowrap; }
.avatar { display: grid; width: 36px; height: 36px; flex: 0 0 36px; place-items: center; color: #fff; border-radius: 50%; background: var(--color-accent); font-size: 14px; font-weight: 750; }

.filter-toolbar { padding: 8px 0 16px; border-bottom: 1px solid var(--color-border); }
.filter-toolbar > span { margin-left: auto; color: var(--color-text-secondary); font-size: 14px; }
.search-field { display: flex; min-width: 280px; flex: 1; align-items: center; gap: 8px; height: 40px; padding: 0 12px; border: 1px solid var(--color-border-strong); border-radius: var(--radius-control); background: var(--color-surface); }
.search-field input { width: 100%; height: 36px; color: var(--color-text); border: 0; outline: 0; background: transparent; font-size: 15px; }
.course-filter { display: flex; align-items: center; gap: 10px; }

.course-list, .student-table { border-top: 1px solid var(--color-border); }
.course-row { display: grid; min-height: 112px; grid-template-columns: 44px minmax(0, 1fr) auto; align-items: center; gap: 16px; padding: 18px 4px; border-bottom: 1px solid var(--color-border); }
.course-mark { display: grid; width: 44px; height: 44px; place-items: center; border-radius: var(--radius-panel); background: var(--color-accent-soft); }
.course-main { min-width: 0; }
.course-main h2 { margin: 0; font-size: 18px; }
.course-main p { max-width: 72ch; margin: 3px 0 8px; overflow: hidden; color: var(--color-text-secondary); font-size: 14px; text-overflow: ellipsis; white-space: nowrap; }
.course-facts { display: flex; flex-wrap: wrap; gap: 16px; color: var(--color-text-muted); font-size: 14px; }

.segment-control { display: inline-flex; gap: 4px; margin-bottom: 18px; padding: 4px; border: 1px solid var(--color-border); border-radius: var(--radius-panel); background: var(--color-surface-subtle); }
.segment-control button { display: inline-flex; min-height: 38px; align-items: center; gap: 7px; padding: 0 13px; color: var(--color-text-secondary); border: 0; border-radius: var(--radius-control); background: transparent; font-size: 14px; font-weight: 650; cursor: pointer; }
.segment-control button.active { color: #fff; background: var(--color-accent); }
.course-detail-section { margin-bottom: 0; }
.detail-row { grid-template-columns: 24px minmax(0, 1fr) minmax(180px, auto); }
.detail-row > span:last-child { text-align: right; }
.sequence { display: grid; width: 24px; height: 24px; place-items: center; border-radius: 50%; background: var(--color-accent-soft); font-weight: 700; }

.student-row { display: grid; min-height: 76px; grid-template-columns: minmax(170px, 1fr) minmax(210px, 1.5fr) minmax(110px, .7fr) minmax(145px, .9fr) 40px; align-items: center; gap: 16px; padding: 10px 4px; border-bottom: 1px solid var(--color-border); }
.student-row--header { min-height: 44px; color: var(--color-text-secondary); background: var(--color-surface-subtle); font-size: 14px; font-weight: 650; }
.student-name { display: flex; min-width: 0; align-items: center; gap: 10px; }
.student-row > div:not(.student-name) { display: flex; min-width: 0; flex-direction: column; }
.status-text { width: max-content; padding: 3px 8px; color: var(--color-text-secondary); border: 1px solid var(--color-border-strong); border-radius: 999px; background: var(--color-surface-subtle); font-size: 14px; }
.status-text[data-state="insufficient"], .status-text[data-state="snapshot_only"] { color: var(--color-warning); background: var(--color-warning-soft); }

.student-summary { display: flex; align-items: center; gap: 14px; margin-bottom: 20px; padding: 16px 0; border-bottom: 1px solid var(--color-border); }
.student-summary > div { flex: 1; }
.avatar--large { width: 48px; height: 48px; flex-basis: 48px; font-size: 18px; }
.student-detail-grid { align-items: start; }
.readonly-mark { display: inline-flex; align-items: center; gap: 6px; color: var(--color-text-secondary); font-size: 14px; }
.path-line { display: grid; grid-template-columns: .7fr .7fr 1.6fr; margin-bottom: 22px; border-block: 1px solid var(--color-border); }
.path-line div { display: flex; min-height: 68px; flex-direction: column; justify-content: center; padding: 10px 14px; border-right: 1px solid var(--color-border); }
.path-line div:last-child { border-right: 0; }
.path-line span { color: var(--color-text-secondary); font-size: 14px; }
.path-line strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.workspace-section h3 { margin: 0 0 10px; font-size: 16px; }

.weak-list details, .timeline details { border-top: 1px solid var(--color-border); }
.weak-list details:last-child, .timeline details:last-child { border-bottom: 1px solid var(--color-border); }
.weak-list summary, .timeline summary { display: grid; min-height: 62px; align-items: center; gap: 12px; cursor: pointer; list-style: none; }
.weak-list summary { grid-template-columns: minmax(0, 1fr) auto 18px; }
.timeline summary { grid-template-columns: 20px minmax(0, 1fr) auto 18px; }
.weak-list summary::-webkit-details-marker, .timeline summary::-webkit-details-marker, .agent-audit > summary::-webkit-details-marker { display: none; }
.weak-list summary > span:first-child, .timeline summary > span:nth-child(2) { display: flex; min-width: 0; flex-direction: column; }
.weak-list small, .timeline small { color: var(--color-text-secondary); font-size: 14px; }
.weak-list summary > span:nth-child(2), .timeline summary > span:nth-child(3) { color: var(--color-text-secondary); font-size: 14px; }
.weak-detail, .evidence-detail { padding: 2px 30px 16px 0; color: var(--color-text-secondary); background: var(--color-surface-subtle); }
.weak-detail p { margin: 0; padding: 4px 12px; font-size: 14px; overflow-wrap: anywhere; }
.evidence-detail { display: flex; flex-wrap: wrap; gap: 8px 20px; padding: 12px; font-size: 14px; }

.intervention-panel { padding: 22px; border: 1px solid var(--color-border); border-radius: var(--radius-panel); background: var(--color-surface); }
.intervention-panel > svg { margin-bottom: 12px; }
.intervention-result { display: flex; align-items: flex-start; gap: 8px; margin-top: 14px; padding: 10px; color: var(--color-danger); border-radius: var(--radius-control); background: var(--color-danger-soft); font-size: 14px; }
.intervention-result[data-state="complete"] { color: var(--color-text-secondary); background: var(--color-success-soft); }

.agent-audit { margin-top: 28px; border: 1px solid var(--color-border); border-radius: var(--radius-panel); background: var(--color-surface); }
.agent-audit > summary { display: grid; min-height: 62px; grid-template-columns: minmax(0, 1fr) auto 20px; align-items: center; gap: 14px; padding: 0 16px; cursor: pointer; list-style: none; }
.agent-audit > summary > span:first-child { display: inline-flex; align-items: center; gap: 8px; }
.agent-audit > summary > span:nth-child(2) { color: var(--color-text-secondary); font-size: 14px; }
.agent-list { padding: 0 16px 16px; }
.agent-list article { padding: 16px 0; border-top: 1px solid var(--color-border); }
.agent-list header { display: flex; justify-content: space-between; margin-bottom: 8px; }
.agent-list header span { color: var(--color-text-secondary); font-size: 14px; }
.agent-list p { margin: 5px 0; color: var(--color-text-secondary); font-size: 14px; }
.agent-list b { color: var(--color-text); }
.source-refs { margin-top: 10px; font-size: 14px; }
.source-refs summary { width: max-content; color: var(--color-text-secondary); cursor: pointer; text-decoration: underline; text-underline-offset: 4px; }
.source-refs p { overflow-wrap: anywhere; }

.spinning { animation: teacher-spin .8s linear infinite; }
@keyframes teacher-spin { to { transform: rotate(360deg); } }

@media (prefers-reduced-motion: reduce) {
  .spinning { animation: none; }
}
</style>
