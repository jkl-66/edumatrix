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
</script>

<template>
  <div v-if="route.meta.layout === 'full'" class="h-screen w-screen overflow-hidden bg-[#0b0f19]">
    <div @error.capture="(e) => console.warn('[EduMatrix] 渲染异常:', e)">
      <router-view :key="route.fullPath" :student-id="studentId" />
    </div>
  </div>
  <div v-else class="flex h-screen overflow-hidden bg-gray-50">

    <!-- Sidebar — 根据角色切换样式 -->
    <aside
      class="flex flex-col transition-all duration-200 shrink-0"
      :class="[sidebarCollapsed ? 'w-16' : 'w-56', role === 'teacher' ? 'bg-[#1a1a2e]' : 'bg-[#0f172a]']"
    >
      <!-- Logo -->
      <div class="flex items-center gap-2.5 px-4 h-14 border-b shrink-0" :class="role === 'teacher' ? 'border-white/10' : 'border-white/10'">
        <div class="w-8 h-8 rounded-lg bg-gradient-to-br from-blue-500 to-purple-600 flex items-center justify-center cursor-pointer shrink-0" @click="sidebarCollapsed = !sidebarCollapsed">
          <GraduationCap :size="18" class="text-white" />
        </div>
        <span v-if="!sidebarCollapsed" class="text-white font-semibold text-sm truncate">{{ role === 'teacher' ? '教师端' : 'EduMatrix' }}</span>
      </div>

      <!-- Nav -->
      <nav class="flex-1 p-2.5 space-y-0.5 overflow-y-auto scrollbar-thin">
        <router-link v-for="item in navItems" :key="item.path + item.label"
          :to="item.path"
          class="flex items-center gap-2.5 px-3 py-2 rounded-lg text-xs font-medium transition-colors"
          :class="route.path === item.path ? 'bg-white/15 text-white' : 'text-white/60 hover:text-white hover:bg-white/10'">
          <component :is="item.icon" :size="17" class="shrink-0" />
          <span v-if="!sidebarCollapsed">{{ item.label }}</span>
        </router-link>
      </nav>

      <!-- User footer -->
      <div class="p-2.5 border-t shrink-0" :class="role === 'teacher' ? 'border-white/10' : 'border-white/10'">
        <div class="flex items-center gap-2 px-2 py-1.5">
          <div class="w-7 h-7 rounded-full flex items-center justify-center text-white text-[10px] font-bold shrink-0"
            :class="role === 'teacher' ? 'bg-gradient-to-br from-amber-400 to-orange-500' : 'bg-gradient-to-br from-emerald-400 to-cyan-500'">
            {{ role === 'teacher' ? 'T' : 'S' }}
          </div>
          <div v-if="!sidebarCollapsed" class="min-w-0 flex-1">
            <div class="text-white text-[11px] font-medium truncate">{{ role === 'teacher' ? '教师' : '学生' }}</div>
            <div class="text-white/40 text-[9px] truncate">{{ displayName }}</div>
          </div>
        </div>
        <button @click="logout" class="w-full mt-1 flex items-center gap-2 px-2 py-1.5 rounded-lg text-[10px] text-white/40 hover:text-white/60 hover:bg-white/5 transition-colors">
          <LogOut :size="12" /><span v-if="!sidebarCollapsed">退出登录</span>
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

      <!-- Page content -->
      <main class="flex-1 overflow-y-auto p-5">
        <div @error.capture="(e) => console.warn('[EduMatrix] 渲染异常:', e)">
          <router-view :key="route.fullPath" :student-id="studentId" />
        </div>
      </main>
    </div>
  </div>
</template>
