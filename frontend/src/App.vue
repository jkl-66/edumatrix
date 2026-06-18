<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { BookOpen, MessageSquare, LayoutDashboard, StickyNote, Calendar, Presentation, Clock, GraduationCap, Library, Settings, UserCheck, GitBranch } from '@lucide/vue'
import { abortAllStreams } from './api'

const route = useRoute()
const router = useRouter()

// 任务 8.2: 全局页面退出/刷新时释放所有流式连接
onMounted(() => {
  window.addEventListener('beforeunload', abortAllStreams)
})
onUnmounted(() => {
  window.removeEventListener('beforeunload', abortAllStreams)
})

const getOrInitStudentId = () => {
  let id = localStorage.getItem('edumatrix_student_id')
  if (!id) {
    id = 'stu-' + Date.now()
    localStorage.setItem('edumatrix_student_id', id)
  }
  return id
}
const studentId = ref(getOrInitStudentId())
const sidebarCollapsed = ref(false)

const navItems = [
  { path: '/', label: '学习仪表盘', icon: LayoutDashboard },
  { path: '/learn', label: '智能对话', icon: MessageSquare },
  { path: '/notes', label: '学习笔记', icon: StickyNote },
  { path: '/review', label: '复习计划', icon: Calendar },
  { path: '/history', label: '对话历史', icon: Clock },
  { path: '/knowledge', label: '知识库', icon: Library },
  { path: '/profile', label: '学习画像', icon: UserCheck },
  { path: '/teacher', label: '教师看板', icon: Presentation },
  { path: '/settings', label: 'LLM 设置', icon: Settings },
]

const pageTitle = computed(() => {
  const map = {
    '/': '学习仪表盘',
    '/learn': '智能对话',
    '/notes': '学习笔记',
    '/review': '复习计划',
    '/history': '对话历史',
    '/knowledge': '知识库',
    '/profile': '学习画像',
    '/teacher': '教师看板',
    '/settings': 'LLM 设置',
  }
  return map[route.path] || 'EduMatrix'
})

function goHome() {
  router.push('/')
}
</script>

<template>
  <div class="flex h-screen overflow-hidden">
    <!-- Sidebar -->
    <aside
      class="bg-[#0f172a] flex flex-col transition-all duration-200 shrink-0"
      :class="sidebarCollapsed ? 'w-16' : 'w-60'"
    >
      <div class="flex items-center gap-2.5 px-4 h-16 border-b border-white/10 shrink-0">
        <div
          class="w-8 h-8 rounded-lg bg-gradient-to-br from-blue-500 to-purple-600 flex items-center justify-center cursor-pointer shrink-0"
          @click="sidebarCollapsed = !sidebarCollapsed"
        >
          <GraduationCap :size="18" class="text-white" />
        </div>
        <span v-if="!sidebarCollapsed" class="text-white font-semibold text-sm truncate">EduMatrix</span>
      </div>

      <nav class="flex-1 p-3 space-y-1 overflow-y-auto scrollbar-thin">
        <router-link
          v-for="item in navItems"
          :key="item.path"
          :to="item.path"
          class="sidebar-link"
          :class="{ active: route.path === item.path }"
        >
          <component :is="item.icon" :size="20" class="shrink-0" />
          <span v-if="!sidebarCollapsed">{{ item.label }}</span>
        </router-link>
      </nav>

      <div class="p-3 border-t border-white/10 space-y-2">
        <div class="flex items-center gap-2 px-2 py-1.5">
          <div class="w-7 h-7 rounded-full bg-gradient-to-br from-emerald-400 to-cyan-500 flex items-center justify-center text-white text-xs font-bold shrink-0">
            S
          </div>
          <div v-if="!sidebarCollapsed" class="min-w-0">
            <div class="text-white text-xs font-medium truncate">学生</div>
            <div class="text-white/40 text-[10px] truncate">{{ studentId.slice(0, 16) }}...</div>
          </div>
        </div>
        <div v-if="!sidebarCollapsed" class="px-2 py-1 border-t border-white/5">
          <div class="text-white/25 text-[9px] leading-relaxed">
            EduMatrix v1.0 | Apache 2.0
            <br>基于 FastAPI + Vue 3 + Tailwind CSS
          </div>
        </div>
      </div>
    </aside>

    <!-- Main -->
    <div class="flex-1 flex flex-col min-w-0">
      <!-- Top bar -->
      <header class="h-16 bg-white border-b border-gray-200 flex items-center justify-between px-6 shrink-0">
        <h1 class="text-lg font-semibold text-gray-900">{{ pageTitle }}</h1>
        <div class="flex items-center gap-3">
          <button class="btn btn-outline text-xs" @click="goHome">
            <LayoutDashboard :size="14" />
            <span>仪表盘</span>
          </button>
        </div>
      </header>

      <!-- Page content -->
      <main class="flex-1 overflow-y-auto p-6">
        <!-- 任务 8.4: 全局渲染异常拦截器（自动降级，防白屏） -->
        <div @error.capture="(e) => console.warn('[GraphicFallback] 捕获渲染异常:', e)">
          <router-view :student-id="studentId" />
        </div>
      </main>
    </div>
  </div>
</template>
