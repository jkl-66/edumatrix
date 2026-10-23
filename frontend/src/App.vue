<script setup>
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  BookOpen,
  BrainCircuit,
  ClipboardCheck,
  Gauge,
  Home,
  Library,
  ListChecks,
  MessageSquare,
  PanelsTopLeft,
  Settings,
  ShieldCheck,
  Store,
  UserRound,
  Users,
} from '@lucide/vue'
import { abortAllStreams, clearAuthSession } from './api'
import AppShell from './components/AppShell.vue'
import { useContextStore } from './stores/context'
import { useCourseContextStore } from './stores/courseContext'
import { roleLandingPath } from './utils/roleLanding'

const route = useRoute()
const router = useRouter()
const context = useContextStore()
const courseContext = useCourseContextStore()

const role = ref('student')
const displayName = ref('学习者')
const studentId = ref('')

const studentNav = [
  { path: '/', label: '首页', icon: Home },
  { path: '/profile', label: '个人中心', icon: UserRound },
  { path: '/profile/learning', label: '学习画像', icon: BrainCircuit },
  { path: '/workspace', label: '学习空间', icon: PanelsTopLeft },
  { path: '/learn', label: '智能对话', icon: MessageSquare },
  { path: '/knowledge', label: '知识库', icon: Library },
  { path: '/marketplace', label: '学习市场', icon: Store },
  { path: '/settings', label: '设置', icon: Settings },
]

const teacherNav = [
  { path: '/teacher/overview', label: '教学总览', icon: Gauge },
  { path: '/teacher/courses', label: '课程与资源', icon: BookOpen },
  { path: '/teacher/students', label: '学生学情', icon: Users },
  { path: '/teacher/assessment', label: '测评管理', icon: ListChecks },
  { path: '/teacher/interventions', label: '干预任务', icon: ClipboardCheck },
]

const adminNav = [
  { path: '/admin/accounts', label: '账号权限', icon: Users },
  { path: '/admin/models', label: '模型配置', icon: BrainCircuit },
  { path: '/admin/content-review', label: '内容审核', icon: ClipboardCheck },
  { path: '/admin/system', label: '系统状态', icon: ShieldCheck },
]

const navItems = computed(() => {
  if (role.value === 'admin') return adminNav
  if (role.value === 'teacher') return teacherNav
  return studentNav
})

const activePath = computed(() => {
  const candidates = navItems.value
    .filter((item) => item.path === route.path || (item.path !== '/' && route.path.startsWith(`${item.path}/`)))
    .sort((left, right) => right.path.length - left.path.length)
  return candidates[0]?.path || (route.path === '/' ? '/' : '')
})

const roleUi = computed(() => {
  if (role.value === 'admin') {
    return { brand: 'EduMatrix', roleLabel: '管理工作区', avatar: '管' }
  }
  if (role.value === 'teacher') {
    return { brand: 'EduMatrix', roleLabel: '教师工作区', avatar: '师' }
  }
  return { brand: 'EduMatrix', roleLabel: '个人学习空间', avatar: '学' }
})

const pageTitle = computed(() => route.meta.title || 'EduMatrix')
const pageSection = computed(() => route.meta.section || roleUi.value.roleLabel)
const courseLabel = computed(() => courseContext.label || context.course?.title || '选择当前课程')
const homePath = computed(() => roleLandingPath(role.value))
const showStudentTools = computed(() => role.value === 'student')
const showCourseTool = computed(() => showStudentTools.value && route.path !== '/learn')

const routeNotice = computed(() => {
  const notices = {
    'golden-loop': '原单画像闭环已并入学习空间，课程、任务和反馈现在从同一入口继续。',
    'competition-loop': '原竞赛闭环已并入学习空间，画像、路径与资源现在共享同一课程上下文。',
    'legacy-route': '已为你打开这一能力在新产品结构中的正式位置。',
    'role-restricted': '当前账号不能访问原页面，已返回与你角色一致的工作区。',
  }
  if (route.query.compat && notices[route.query.compat]) return notices[route.query.compat]
  if (route.query.access === 'forbidden') return '当前账号没有访问该页面的权限，已返回角色首页。'
  if (route.query.access === 'course-not-found') return '原链接中的课程当前不可用，请重新选择课程。'
  return ''
})

function syncSession() {
  role.value = localStorage.getItem('edumatrix_role') || 'student'
  displayName.value = localStorage.getItem('edumatrix_display_name') || localStorage.getItem('edumatrix_username') || '学习者'
  studentId.value = localStorage.getItem('edumatrix_student_id') || localStorage.getItem('edumatrix_username') || ''
}

function dismissRouteNotice() {
  const query = { ...route.query }
  delete query.compat
  delete query.access
  router.replace({ path: route.path, query })
}

function logout() {
  abortAllStreams()
  clearAuthSession()
  context.clear()
  courseContext.clear({ keepCourse: false })
  router.push('/landing')
}

function handleCaptureError(event) {
  if (event.target && ['IMG', 'VIDEO', 'AUDIO'].includes(event.target.tagName)) return
  console.warn('[EduMatrix] 页面渲染异常', event)
}

watch(
  () => route.fullPath,
  () => {
    syncSession()
    nextTick(() => document.querySelector('.app-content')?.scrollTo({ top: 0, left: 0 }))
  },
  { immediate: true },
)

onMounted(() => window.addEventListener('beforeunload', abortAllStreams))
onUnmounted(() => window.removeEventListener('beforeunload', abortAllStreams))
</script>

<template>
  <div v-if="route.meta.layout === 'full'" class="full-layout" @error.capture="handleCaptureError">
    <router-view :key="route.fullPath" :student-id="studentId" />
  </div>

  <AppShell
    v-else
    :nav-items="navItems"
    :active-path="activePath"
    :brand="roleUi.brand"
    :role-label="roleUi.roleLabel"
    :avatar="roleUi.avatar"
    :display-name="displayName"
    :page-title="pageTitle"
    :page-section="pageSection"
    :course-label="courseLabel"
    :home-path="homePath"
    :show-course-context="showCourseTool"
    :show-search="showStudentTools"
    :route-notice="routeNotice"
    @logout="logout"
    @dismiss-notice="dismissRouteNotice"
  >
    <div @error.capture="handleCaptureError">
      <router-view v-slot="{ Component, route: currentRoute }" :student-id="studentId">
        <Transition name="page-fade" mode="out-in">
          <component :is="Component" :key="currentRoute.fullPath" :student-id="studentId" />
        </Transition>
      </router-view>
    </div>
  </AppShell>
</template>

<style scoped>
.full-layout {
  width: 100vw;
  height: 100vh;
  min-width: 1180px;
  overflow: hidden;
  background: var(--color-page);
}

.page-fade-enter-active,
.page-fade-leave-active {
  transition: opacity 120ms ease;
}

.page-fade-enter-from,
.page-fade-leave-to {
  opacity: 0;
}
</style>
