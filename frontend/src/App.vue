<script setup>
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  BookOpen, MessageSquare, LayoutDashboard, StickyNote, Calendar,
  Presentation, Clock, GraduationCap, Library, Settings, UserCheck,
  GitBranch, BarChart3, TrendingUp, LogOut, Users, Flame,
  PanelLeftClose, PanelLeftOpen, Search, Bell, Plus, Sparkles,
} from '@lucide/vue'
import { abortAllStreams } from './api'
import SidebarItem from './components/ui/SidebarItem.vue'
import UiButton from './components/ui/UiButton.vue'

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
  { path: '/', label: '学习仪表盘', group: '总览', icon: LayoutDashboard },
  { path: '/learn', label: '智能对话', group: '学习空间', icon: MessageSquare },
  { path: '/student-analysis', label: '学习画像', group: '学习空间', icon: UserCheck },
  { path: '/learning-path', label: '学习路径', group: '学习空间', icon: GitBranch },
  { path: '/notes', label: '学习笔记', group: '知识管理', icon: StickyNote },
  { path: '/knowledge', label: '知识库', group: '知识管理', icon: Library },
  { path: '/review', label: '复习计划', group: '复习提升', icon: Calendar },
  { path: '/revision-calendar', label: '复习打卡', group: '复习提升', icon: Flame },
  { path: '/wrong-questions', label: '错题本', group: '复习提升', icon: BookOpen },
  { path: '/history', label: '对话历史', group: '复习提升', icon: Clock },
  { path: '/settings', label: '设置', group: '系统', icon: Settings },
]

// 教师导航 — 分层清晰（独立路由）
const teacherNav = [
  { path: '/teacher', label: '教学看板', group: '总览', icon: Presentation },
  { path: '/teacher/students', label: '学生管理', group: '教学空间', icon: Users },
  { path: '/teacher/reviews', label: '复习监控', group: '教学空间', icon: Calendar },
  { path: '/teacher/reports', label: '学习报告', group: '教学空间', icon: BarChart3 },
  { path: '/settings', label: '设置', group: '系统', icon: Settings },
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
  <div v-if="route.meta.layout === 'full'" class="h-screen w-screen overflow-hidden bg-[#f1f5f2]">
    <div @error.capture="handleCaptureError">
      <router-view :key="route.fullPath" :student-id="studentId" />
    </div>
  </div>
  <div v-else class="app-shell flex h-screen overflow-hidden">

    <!-- Sidebar -->
    <aside
      class="app-sidebar flex flex-col shrink-0"
      :class="{ 'app-sidebar--collapsed': sidebarCollapsed }"
    >
      <div class="app-brand" @click="sidebarCollapsed = !sidebarCollapsed">
        <div class="app-brand__mark"><GraduationCap :size="19" /></div>
        <Transition name="sidebar-label">
          <div v-if="!sidebarCollapsed" class="app-brand__copy">
            <span>{{ role === 'teacher' ? 'EduMatrix 教学端' : 'EduMatrix' }}</span>
            <small>Adaptive learning OS</small>
          </div>
        </Transition>
      </div>

      <nav class="app-nav scrollbar-thin">
        <template v-for="(item, index) in navItems" :key="item.path + item.label">
          <p v-if="!sidebarCollapsed && (index === 0 || navItems[index - 1].group !== item.group)" class="app-nav__group">{{ item.group }}</p>
          <SidebarItem :item="item" :collapsed="sidebarCollapsed" :active="route.path === item.path" />
        </template>
      </nav>

      <div class="app-sidebar__footer">
        <div class="app-user">
          <div class="app-user__avatar">{{ role === 'teacher' ? 'T' : 'S' }}</div>
          <Transition name="sidebar-label">
            <div v-if="!sidebarCollapsed" class="app-user__copy">
              <strong>{{ displayName }}</strong>
              <span>{{ role === 'teacher' ? '教师工作空间' : '个人学习空间' }}</span>
            </div>
          </Transition>
        </div>
        <button @click="logout" class="app-logout" :title="sidebarCollapsed ? '退出登录' : undefined">
          <LogOut :size="12" />
          <span v-if="!sidebarCollapsed">退出登录</span>
        </button>
      </div>
    </aside>

    <!-- Main -->
    <div class="app-main flex-1 flex flex-col min-w-0">
      <header class="app-header">
        <div class="app-header__title">
          <button class="app-sidebar-toggle" @click="sidebarCollapsed = !sidebarCollapsed" :aria-label="sidebarCollapsed ? '展开导航' : '收起导航'">
            <PanelLeftOpen v-if="sidebarCollapsed" :size="17" />
            <PanelLeftClose v-else :size="17" />
          </button>
          <div>
            <p class="app-header__eyebrow">{{ role === 'teacher' ? '教学工作台' : '学习工作台' }}</p>
            <h1>{{ pageTitle }}</h1>
          </div>
        </div>
        <div class="app-header__tools">
          <button class="app-search" @click="router.push('/learn')"><Search :size="15" /><span>搜索课程、笔记或知识点</span><kbd>⌘ K</kbd></button>
          <button class="app-icon-button" aria-label="通知"><Bell :size="16" /><span class="app-icon-button__badge" /></button>
          <UiButton variant="primary" size="sm" @click="router.push('/learn')"><template #icon><Plus :size="15" /></template>{{ role === 'teacher' ? '新建课程' : '开始学习' }}</UiButton>
        </div>
      </header>

      <div class="app-contextbar">
        <div><Sparkles :size="13" /><span>AI 正在根据你的学习状态实时调整内容</span></div>
        <button @click="goHome"><LayoutDashboard :size="13" />返回总览</button>
      </div>

      <!-- Page content — 300ms 页面切换平滑动效 -->
      <main class="app-content flex-1 overflow-y-auto">
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

.app-shell {
  padding: 12px;
  gap: 12px;
  background: #eef0ec;
}

.app-sidebar {
  width: 248px;
  height: calc(100vh - 24px);
  overflow: hidden;
  border: 1px solid rgba(30, 40, 34, 0.08);
  border-radius: 24px;
  background: rgba(250, 251, 248, 0.88);
  box-shadow: 0 20px 60px rgba(33, 43, 36, 0.08);
  backdrop-filter: blur(24px);
  transition: width 280ms cubic-bezier(.22, 1, .36, 1);
}

.app-sidebar--collapsed { width: 72px; }

.app-brand {
  display: flex;
  align-items: center;
  gap: 11px;
  min-height: 76px;
  padding: 16px;
  cursor: pointer;
}

.app-brand__mark {
  display: grid;
  width: 40px;
  height: 40px;
  flex: 0 0 40px;
  place-items: center;
  color: #f8faf7;
  border-radius: 14px;
  background: #27312b;
  box-shadow: inset 0 1px 0 rgba(255,255,255,.16), 0 8px 20px rgba(39,49,43,.18);
}

.app-brand__copy { min-width: 0; }
.app-brand__copy span { display: block; color: #202823; font-size: 14px; font-weight: 720; letter-spacing: -.02em; white-space: nowrap; }
.app-brand__copy small { display: block; margin-top: 2px; color: #98a098; font-size: 9px; letter-spacing: .08em; text-transform: uppercase; white-space: nowrap; }

.app-nav { flex: 1; overflow-y: auto; padding: 6px 10px 14px; }
.app-nav__group { margin: 18px 10px 7px; color: #69766d; font-size: 9px; font-weight: 750; letter-spacing: .14em; text-transform: uppercase; }

.app-sidebar__footer { padding: 12px; border-top: 1px solid rgba(38,49,42,.07); }
.app-user { display: flex; align-items: center; gap: 10px; padding: 8px; border-radius: 15px; background: rgba(235,238,233,.72); }
.app-user__avatar { display: grid; width: 32px; height: 32px; flex: 0 0 32px; place-items: center; color: #f7f8f6; background: #66736a; border-radius: 11px; font-size: 11px; font-weight: 700; }
.app-user__copy { min-width: 0; }
.app-user__copy strong, .app-user__copy span { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.app-user__copy strong { color: #39423c; font-size: 11px; font-weight: 650; }
.app-user__copy span { margin-top: 2px; color: #989f99; font-size: 9px; }
.app-logout { display: flex; width: 100%; align-items: center; gap: 8px; margin-top: 6px; padding: 8px 10px; color: #9a716d; border: 0; border-radius: 12px; background: transparent; font-size: 10px; cursor: pointer; }
.app-logout:hover { color: #815650; background: #f3e9e7; }

.app-main {
  min-width: 0;
  height: calc(100vh - 24px);
  overflow: hidden;
  border: 1px solid rgba(30, 40, 34, 0.07);
  border-radius: 24px;
  background: rgba(248, 249, 246, 0.82);
  box-shadow: 0 20px 60px rgba(33, 43, 36, 0.06);
}

.app-header {
  display: flex;
  min-height: 76px;
  align-items: center;
  justify-content: space-between;
  gap: 24px;
  padding: 12px 24px;
  border-bottom: 1px solid rgba(37, 48, 41, 0.07);
  background: rgba(252, 253, 250, 0.76);
  backdrop-filter: blur(20px);
}

.app-header__title { display: flex; min-width: 0; align-items: center; gap: 12px; }
.app-header__title h1 { margin: 0; color: #212923; font-size: 18px; font-weight: 680; letter-spacing: -.035em; }
.app-header__eyebrow { margin: 0 0 1px; color: #9aa19b; font-size: 9px; font-weight: 700; letter-spacing: .12em; text-transform: uppercase; }
.app-sidebar-toggle, .app-icon-button { display: grid; width: 36px; height: 36px; place-items: center; color: #69736c; border: 1px solid rgba(53,65,57,.09); border-radius: 12px; background: rgba(255,255,255,.64); cursor: pointer; transition: .2s ease; }
.app-sidebar-toggle:hover, .app-icon-button:hover { color: #27312b; background: #fff; transform: translateY(-1px); }
.app-header__tools { display: flex; align-items: center; gap: 9px; }
.app-search { display: flex; width: min(30vw, 330px); align-items: center; gap: 9px; padding: 9px 11px; color: #9aa19b; border: 1px solid rgba(53,65,57,.09); border-radius: 13px; background: rgba(240,242,238,.75); font-size: 11px; cursor: pointer; }
.app-search span { flex: 1; text-align: left; }
.app-search kbd { padding: 2px 5px; color: #8b938d; border: 1px solid rgba(53,65,57,.1); border-radius: 6px; background: rgba(255,255,255,.7); font-family: inherit; font-size: 9px; }
.app-icon-button { position: relative; }
.app-icon-button__badge { position: absolute; top: 8px; right: 8px; width: 5px; height: 5px; border: 1px solid #fff; border-radius: 50%; background: #bc756e; }

.app-contextbar {
  display: flex;
  min-height: 34px;
  align-items: center;
  justify-content: space-between;
  padding: 0 24px;
  color: #747e76;
  border-bottom: 1px solid rgba(37,48,41,.06);
  background: rgba(239,241,237,.65);
  font-size: 10px;
}
.app-contextbar div, .app-contextbar button { display: flex; align-items: center; gap: 6px; }
.app-contextbar button { color: #68746b; border: 0; background: none; font-size: 10px; cursor: pointer; }
.app-content { padding: 28px clamp(20px, 3vw, 42px) 42px; }

@media (max-width: 1024px) {
  .app-search { width: 42px; }
  .app-search span, .app-search kbd { display: none; }
}

@media (max-width: 767px) {
  .app-shell { padding: 0; gap: 0; }
  .app-sidebar { width: 68px; height: 100vh; border-width: 0 1px 0 0; border-radius: 0; }
  .app-main { height: 100vh; border: 0; border-radius: 0; }
  .app-header { min-height: 68px; padding: 10px 14px; }
  .app-header__eyebrow, .app-icon-button, .app-contextbar { display: none; }
  .app-header__title h1 { font-size: 16px; }
  .app-content { padding: 18px 14px 30px; }
}
</style>
