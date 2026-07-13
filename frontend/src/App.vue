<script setup>
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  BookOpen, MessageSquare, LayoutDashboard, StickyNote, Calendar,
  Presentation, Clock, GraduationCap, Library, Settings, UserCheck,
  GitBranch, BarChart3, TrendingUp, LogOut, Users, Flame,
} from '@lucide/vue'
import { abortAllStreams } from './api'

const route = useRoute()
const router = useRouter()

const getOrInitStudentId = () => {
  let id = localStorage.getItem('edumatrix_student_id')
  if (!id) {
    id = 'stu-' + Date.now()
    localStorage.setItem('edumatrix_student_id', id)
  }
  return id
}

const studentId = ref('')
const role = ref('student')
const displayName = ref('')
const isNarrowViewport = () => typeof window !== 'undefined' && window.innerWidth < 768
const sidebarCollapsed = ref(isNarrowViewport())

function syncSidebarForViewport() {
  if (isNarrowViewport()) sidebarCollapsed.value = true
}

onMounted(() => {
  window.addEventListener('beforeunload', abortAllStreams)
  window.addEventListener('resize', syncSidebarForViewport)
  syncSidebarForViewport()
})
onUnmounted(() => {
  window.removeEventListener('beforeunload', abortAllStreams)
  window.removeEventListener('resize', syncSidebarForViewport)
})

const updateSessionInfo = () => {
  studentId.value = localStorage.getItem('edumatrix_student_id') || getOrInitStudentId()
  role.value = localStorage.getItem('edumatrix_role') || 'student'
  displayName.value = localStorage.getItem('edumatrix_display_name') || studentId.value.slice(0, 16)
}

watch(() => route.path, () => {
  updateSessionInfo()
}, { immediate: true })

// 学生导航 — 只展示学习相关内容
const studentNav = [
  { path: '/', label: '学习仪表盘', icon: LayoutDashboard },
  { path: '/learn', label: '智能对话', icon: MessageSquare },
  { path: '/student-analysis', label: '学习画像', icon: UserCheck },
  { path: '/learning-path', label: '学习路径', icon: GitBranch },
  { path: '/notes', label: '学习笔记', icon: StickyNote },
  { path: '/review', label: '复习计划', icon: Calendar },
  { path: '/revision-calendar', label: '复习打卡', icon: Flame },
  { path: '/wrong-questions', label: '错题本', icon: BookOpen },
  { path: '/history', label: '对话历史', icon: Clock },
  { path: '/knowledge', label: '知识库', icon: Library },
  { path: '/settings', label: '设置', icon: Settings },
]

// 教师导航 — 分层清晰（独立路由）
const teacherNav = [
  { path: '/teacher', label: '教学看板', icon: Presentation },
  { path: '/teacher/students', label: '学生管理', icon: Users },
  { path: '/teacher/reviews', label: '复习监控', icon: Calendar },
  { path: '/teacher/reports', label: '学习报告', icon: BarChart3 },
  { path: '/settings', label: '设置', icon: Settings },
]

const navItems = computed(() => role.value === 'teacher' ? teacherNav : studentNav)

const pageTitle = computed(() => {
  const map = {
    '/': '学习仪表盘', '/learn': '智能对话', '/learning-path': '学习路径',
    '/wrong-questions': '错题本', '/notes': '学习笔记', '/review': '复习计划',
    '/revision-calendar': '复习日历', '/history': '对话历史', '/knowledge': '知识库',
    '/profile': '学习画像', '/teacher': '教学看板', '/settings': '设置',
    '/student-analysis': '学习画像',
  }
  return map[route.path] || (role.value === 'teacher' ? '教学看板' : 'EduMatrix')
})

function goHome() { router.push(role.value === 'teacher' ? '/teacher' : '/') }

function logout() {
  ['edumatrix_token','edumatrix_role','edumatrix_username','edumatrix_display_name','edumatrix_student_id','edumatrix_viewing_student','edumatrix_chat_messages']
    .forEach(k => localStorage.removeItem(k))
  router.push('/login')
}
function handleCaptureError(e) {
  // 过滤掉 img/video/audio 等媒体资源的加载失败（404等），它们是浏览器正常行为，不属于 Vue 渲染异常
  if (e.target && ['IMG', 'VIDEO', 'AUDIO'].includes(e.target.tagName)) {
    return
  }
  console.warn('[EduMatrix] 渲染异常:', e)
}
</script>

<template>
  <div v-if="route.meta.layout === 'full'" class="h-screen w-screen overflow-hidden bg-[#0b0f19]">
    <div @error.capture="handleCaptureError">
      <router-view :key="route.fullPath" :student-id="studentId" />
    </div>
  </div>
  <div v-else class="flex h-screen overflow-hidden bg-gray-50">

    <!-- Sidebar — 玻璃拟态侧边栏 -->
    <aside
      class="flex flex-col shrink-0 relative border-r border-white/5 backdrop-blur-xl"
      style="transition: width 300ms cubic-bezier(0.4, 0, 0.2, 1);"
      :style="{
        width: sidebarCollapsed ? '64px' : '224px',
        background: role === 'teacher' ? 'rgba(26, 26, 46, 0.75)' : 'rgba(15, 23, 42, 0.75)'
      }"
    >
      <!-- 玻璃光晕装饰 -->
      <div class="pointer-events-none absolute top-0 left-0 w-full h-32 bg-gradient-to-b from-white/[0.04] to-transparent rounded-t-none" />

      <!-- Logo -->
      <div class="flex items-center gap-2.5 px-4 h-14 border-b border-white/10 shrink-0">
        <div
          class="w-8 h-8 rounded-lg flex items-center justify-center cursor-pointer shrink-0 transition-transform duration-200 hover:scale-110 active:scale-95"
          :class="role === 'teacher' ? 'bg-gradient-to-br from-amber-400 to-orange-600' : 'bg-gradient-to-br from-blue-500 to-purple-600'"
          @click="sidebarCollapsed = !sidebarCollapsed"
        >
          <GraduationCap :size="18" class="text-white" />
        </div>
        <Transition name="sidebar-label">
          <span v-if="!sidebarCollapsed" class="text-white font-semibold text-sm truncate">
            {{ role === 'teacher' ? '教师端' : 'EduMatrix' }}
          </span>
        </Transition>
      </div>

      <!-- Nav -->
      <nav class="flex-1 p-2.5 space-y-0.5 overflow-y-auto scrollbar-thin">
        <router-link v-for="item in navItems" :key="item.path + item.label"
          :to="item.path"
          class="flex items-center gap-2.5 px-3 py-2 rounded-lg text-xs font-medium transition-all duration-200 relative overflow-hidden group"
          :class="route.path === item.path
            ? 'bg-white/15 text-white shadow-sm'
            : 'text-white/60 hover:text-white hover:bg-white/8'"
        >
          <!-- 激活状态左侧发光边条 -->
          <span v-if="route.path === item.path"
                class="absolute left-0 top-1/2 -translate-y-1/2 w-0.5 h-5 rounded-full"
                :class="role === 'teacher' ? 'bg-amber-400 shadow-[0_0_8px_2px_rgba(251,191,36,0.5)]' : 'bg-blue-400 shadow-[0_0_8px_2px_rgba(96,165,250,0.5)]'"
          />
          <component :is="item.icon" :size="17" class="shrink-0 transition-transform duration-200 group-hover:scale-110" />
          <Transition name="sidebar-label">
            <span v-if="!sidebarCollapsed">{{ item.label }}</span>
          </Transition>
        </router-link>
      </nav>

      <!-- User footer -->
      <div class="p-2.5 border-t border-white/10 shrink-0">
        <div class="flex items-center gap-2 px-2 py-1.5">
          <div class="w-7 h-7 rounded-full flex items-center justify-center text-white text-[10px] font-bold shrink-0 ring-1 ring-white/20"
               :class="role === 'teacher' ? 'bg-gradient-to-br from-amber-400 to-orange-500' : 'bg-gradient-to-br from-emerald-400 to-cyan-500'">
            {{ role === 'teacher' ? 'T' : 'S' }}
          </div>
          <Transition name="sidebar-label">
            <div v-if="!sidebarCollapsed" class="min-w-0 flex-1">
              <div class="text-white text-[11px] font-medium truncate">{{ role === 'teacher' ? '教师' : '学生' }}</div>
              <div class="text-white/40 text-[9px] truncate">{{ displayName }}</div>
            </div>
          </Transition>
        </div>
        <button @click="logout" class="w-full mt-1 flex items-center gap-2 px-2 py-1.5 rounded-lg text-[10px] text-white/40 hover:text-white/70 hover:bg-white/8 transition-colors">
          <LogOut :size="12" />
          <Transition name="sidebar-label">
            <span v-if="!sidebarCollapsed">退出登录</span>
          </Transition>
        </button>
      </div>
    </aside>

    <!-- Main -->
    <div class="flex-1 flex flex-col min-w-0">
      <!-- Top bar -->
      <header class="h-14 bg-white border-b border-gray-200 flex items-center justify-between px-5 shrink-0">
        <div class="flex items-center gap-2.5">
          <h1 class="text-base font-semibold text-gray-800">{{ pageTitle }}</h1>
          <span class="px-2 py-0.5 text-[9px] font-semibold rounded-full"
            :class="role === 'teacher' ? 'bg-amber-100 text-amber-700' : 'bg-emerald-100 text-emerald-700'">
            {{ role === 'teacher' ? '教师' : '学生' }}
          </span>
        </div>
        <button class="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg border border-gray-200 text-gray-600 hover:bg-gray-50 transition-colors" @click="goHome">
          <LayoutDashboard :size="13" />
          <span>{{ role === 'teacher' ? '看板' : '首页' }}</span>
        </button>
      </header>

      <!-- Page content — 300ms 页面切换平滑动效 -->
      <main class="flex-1 overflow-y-auto p-5">
        <div @error.capture="handleCaptureError">
          <router-view v-slot="{ Component, route: r }" :student-id="studentId">
            <Transition name="page" mode="out-in">
              <component :is="Component" :key="r.fullPath" :student-id="studentId" />
            </Transition>
          </router-view>
        </div>
      </main>
    </div>
  </div>
</template>

<style scoped>
/* ── 300ms 页面切换淡入淡出 ── */
.page-enter-active,
.page-leave-active {
  transition: opacity 180ms ease, transform 180ms ease;
}
.page-enter-from {
  opacity: 0;
  transform: translateY(6px);
}
.page-leave-to {
  opacity: 0;
  transform: translateY(-4px);
}

/* ── 侧边栏标签文字淡入淡出 ── */
.sidebar-label-enter-active,
.sidebar-label-leave-active {
  transition: opacity 150ms ease, transform 150ms ease;
}
.sidebar-label-enter-from,
.sidebar-label-leave-to {
  opacity: 0;
  transform: translateX(-4px);
}
</style>
