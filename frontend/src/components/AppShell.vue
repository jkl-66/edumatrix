<script setup>
import { computed } from 'vue'
import { BookOpen, CalendarCheck, ClipboardCheck, FilePlus2, FileText, ListChecks, LogOut, MapPin, Search } from '@lucide/vue'
import { useRoute, useRouter } from 'vue-router'
import PageHeader from './PageHeader.vue'
import RecoveryBanner from './RecoveryBanner.vue'
import SidebarItem from './ui/SidebarItem.vue'

defineProps({
  navItems: { type: Array, required: true },
  activePath: { type: String, default: '' },
  brand: { type: String, default: 'EduMatrix' },
  roleLabel: { type: String, default: '学习空间' },
  avatar: { type: String, default: 'S' },
  avatarUrl: { type: String, default: '' },
  displayName: { type: String, default: '' },
  pageTitle: { type: String, default: 'EduMatrix' },
  pageSection: { type: String, default: '' },
  courseLabel: { type: String, default: '人工智能与机器学习工程' },
  homePath: { type: String, default: '/' },
  showCourseContext: { type: Boolean, default: true },
  showSearch: { type: Boolean, default: true },
  routeNotice: { type: String, default: '' },
})

defineEmits(['logout', 'dismiss-notice'])

const router = useRouter()
const route = useRoute()

const workspaceNavItems = [
  { path: '/workspace', label: '今日学习', icon: BookOpen },
  { path: '/workspace/path', label: '学习路径', icon: MapPin },
  { path: '/workspace/resources', label: '资源中心', icon: FileText },
  { path: '/workspace/assessment', label: '测评中心', icon: ClipboardCheck },
  { path: '/workspace/review', label: '复习中心', icon: CalendarCheck },
  { path: '/workspace/notes', label: '笔记本', icon: FilePlus2 },
  { path: '/workspace/review/wrong-questions', label: '错题本', icon: ListChecks },
]

const isWorkspaceRoute = computed(() => route.path === '/workspace' || route.path.startsWith('/workspace/'))
const activeWorkspaceNavPath = computed(() => workspaceNavItems
  .filter((item) => route.path === item.path || (item.path !== '/workspace' && route.path.startsWith(`${item.path}/`)))
  .sort((left, right) => right.path.length - left.path.length)[0]?.path || '')
</script>

<template>
  <div class="app-shell">
    <aside class="app-sidebar" aria-label="主导航">
      <button type="button" class="app-brand" aria-label="返回当前工作区首页" @click="router.push(homePath)">
        <span class="app-brand__mark">E</span>
        <span class="app-brand__copy">
          <strong>{{ brand }}</strong>
        </span>
      </button>

      <nav class="app-nav">
        <SidebarItem
          v-for="item in navItems"
          :key="item.path"
          :item="item"
          :active="activePath === item.path"
        />
      </nav>

      <div class="app-sidebar__footer">
        <div class="app-user">
          <span class="app-user__avatar"><img v-if="avatarUrl" :src="avatarUrl" alt="我的头像" /><template v-else>{{ avatar }}</template></span>
          <span class="app-user__copy">
            <strong>{{ displayName }}</strong>
            </span>
        </div>
        <button type="button" class="app-logout" title="退出登录" aria-label="退出登录" @click="$emit('logout')">
          <LogOut :size="17" />
        </button>
      </div>
    </aside>

    <section class="app-frame">
      <header class="app-topbar">
        <PageHeader :title="pageTitle" compact />
        <div v-if="showCourseContext || showSearch" class="app-topbar__tools">
          <button v-if="showCourseContext" type="button" class="app-course-context" @click="router.push('/workspace')">
            <BookOpen :size="16" />
            <span>{{ courseLabel }}</span>
          </button>
          <button v-if="showSearch" type="button" class="app-search" aria-label="打开智能对话搜索" title="搜索与提问" @click="router.push('/learn')">
            <Search :size="17" />
          </button>
        </div>
      </header>

      <RecoveryBanner
        v-if="routeNotice"
        :message="routeNotice"
        variant="recovery"
        @dismiss="$emit('dismiss-notice')"
      />

      <main class="app-content">
        <div class="app-content__layout" :class="{ 'app-content__layout--workspace': isWorkspaceRoute, 'app-content__layout--reader': route.name === 'KnowledgeDocument' }">
          <nav v-if="isWorkspaceRoute" class="workspace-subnav" aria-label="学习空间内部导航">
            <div class="workspace-subnav__title">
              <strong>学习空间</strong>
            </div>
            <div class="workspace-subnav__links">
              <router-link
                v-for="item in workspaceNavItems"
                :key="item.path"
                :to="item.path"
                :class="{ active: activeWorkspaceNavPath === item.path }"
                :aria-current="activeWorkspaceNavPath === item.path ? 'page' : undefined"
              >
                <component :is="item.icon" :size="16" />
                <span>
                  <strong>{{ item.label }}</strong>
                </span>
              </router-link>
            </div>
          </nav>
          <div class="app-content__page">
            <slot />
          </div>
        </div>
      </main>
    </section>
  </div>
</template>

<style scoped>
.app-shell {
  display: grid;
  grid-template-columns: var(--nav-width) minmax(0, 1fr);
  width: 100%; height: 100dvh; min-width: 0;
  gap: 12px; padding: 12px; overflow: hidden;
  background: var(--color-shell-gradient);
}
.app-sidebar {
  display: flex; flex-direction: column; min-width: 0; min-height: 0;
  border: 1px solid rgb(255 255 255 / 55%); border-radius: 14px;
  background: linear-gradient(165deg, rgb(255 255 255 / 40%), rgb(255 253 250 / 66%)); overflow: hidden;
}
.app-brand {
  display: flex; align-items: center; justify-content: center; flex-direction: column;
  min-height: 100px; gap: 7px; padding: 14px 6px;
  border: 0; background: transparent; text-align: center; cursor: pointer;
}
.app-brand__mark {
  display: grid; place-items: center; width: 34px; height: 34px; flex: 0 0 34px;
  color: #fffdf9; background: #435866; border-radius: 11px;
  font-family: var(--font-display); font-size: 24px; box-shadow: 0 3px 8px rgb(49 67 79 / 12%);
}
.app-brand__copy, .app-user__copy { display: grid; justify-items: center; min-width: 0; width: 100%; }
.app-brand__copy strong { color: var(--color-text); font-size: 14px; font-weight: 700; }
.app-brand__copy small { display: none; }
.app-nav { display: grid; align-content: start; flex: 1; min-height: 0; gap: 5px; padding: 8px; overflow-y: auto; }
.app-nav :deep(.sidebar-item) {
  min-height: 62px; justify-content: center; flex-direction: column; gap: 5px;
  padding: 8px 4px; border-radius: 10px; text-align: center; font-size: 14px; line-height: 1.3;
}
.app-nav :deep(.sidebar-item--active) { color: var(--color-accent); background: rgb(253 252 249 / 85%); box-shadow: 0 2px 8px rgb(63 56 50 / 5%); }
.app-nav :deep(.sidebar-item::before) { inset: 14px auto 14px 0; height: auto; width: 3px; border-radius: 2px; }
.app-nav :deep(.sidebar-item--active::before) { background: var(--color-accent); }
.app-nav :deep(.sidebar-item__icon) { width: 22px; height: 22px; flex-basis: 22px; }
.app-nav :deep(.sidebar-item__label) { max-width: 100%; white-space: normal; }
.app-sidebar__footer { display: grid; justify-items: center; gap: 9px; padding: 12px 6px; border-top: 1px solid rgb(95 106 111 / 12%); }
.app-user { display: flex; min-width: 0; align-items: center; flex-direction: column; gap: 7px; text-align: center; }
.app-user__avatar { display: grid; width: 32px; height: 32px; place-items: center; border-radius: 50%; background: var(--color-accent-soft); color: var(--color-accent); font-size: 14px; }
.app-user__avatar img { width: 100%; height: 100%; object-fit: cover; border-radius: inherit; }
.app-user__copy strong { width: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--color-text-secondary); font-size: 13px; font-weight: 500; }
.app-user__copy small { display: none; }
.app-logout, .app-search { display: grid; place-items: center; width: 34px; height: 34px; color: var(--color-text-secondary); border: 1px solid transparent; border-radius: 8px; background: transparent; cursor: pointer; }
.app-logout:hover, .app-search:hover { background: var(--color-surface); border-color: var(--color-border); }
.app-frame { display: flex; flex-direction: column; min-width: 0; min-height: 0; overflow: hidden; border: 1px solid rgb(255 255 255 / 80%); border-radius: 14px; background: var(--gradient-workspace); box-shadow: var(--shadow-panel); }
.app-topbar { display: flex; flex: 0 0 var(--topbar-height); min-width: 0; align-items: center; justify-content: space-between; gap: 18px; padding: 7px 24px; border-bottom: 0; background: rgb(255 255 255 / 35%); }
.app-topbar__tools { display: flex; min-width: 0; align-items: center; gap: 8px; }
.app-course-context { display: flex; max-width: 300px; min-width: 0; min-height: 34px; align-items: center; gap: 8px; padding: 0 10px; color: var(--color-text-secondary); border: 0; border-radius: 8px; background: rgb(255 255 255 / 55%); font-size: 14px; cursor: pointer; }
.app-course-context svg { flex: none; }
.app-course-context span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.app-course-context:hover { background: var(--color-surface); }
.app-content { flex: 1; min-width: 0; min-height: 0; overflow: auto; background: transparent; }
.app-content__layout { min-width: 0; min-height: 100%; }
.app-content__layout--reader > .app-content__page { padding-top: 0; padding-bottom: 0; }
.app-content__layout--workspace > .app-content__page { padding: 0; }
.app-content__layout--workspace { display: grid; grid-template-columns: 136px minmax(0, 1fr); align-items: stretch; gap: 18px; padding: 20px; }
.app-content__page { min-width: 0; box-sizing: border-box; padding: 18px clamp(18px, 2vw, 32px) 28px; }
.app-content__layout--reader, .app-content__layout--reader > .app-content__page { height: 100%; }
.app-content__layout--reader > .app-content__page { padding-top: 0; padding-bottom: 0; }
.app-content__layout--workspace > .app-content__page { padding: 0; }
.workspace-subnav { display: flex; flex-direction: column; position: sticky; top: 20px; align-self: start; height: calc(100dvh - var(--topbar-height) - 66px); min-width: 0; overflow-y: auto; border: 0; border-radius: var(--radius-panel); background: var(--gradient-rail); }
.workspace-subnav__title { display: grid; gap: 4px; padding: 18px 12px 8px; }
.workspace-subnav__title strong { font-size: 14px; }
.workspace-subnav__title span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 14px; color: var(--color-text-muted); }
.workspace-subnav__links { display: grid; gap: 3px; padding: 10px 6px; }
.workspace-subnav__links a { display: flex; min-width: 0; min-height: 42px; align-items: center; gap: 7px; padding: 8px 7px; color: var(--color-text-secondary); border-radius: var(--radius-control); text-decoration: none; }
.workspace-subnav__links a:hover { background: var(--color-surface-subtle); }
.workspace-subnav__links a.active { color: var(--color-accent); background: var(--color-accent-soft); }
.workspace-subnav__links a > span { display: grid; min-width: 0; gap: 2px; }
.workspace-subnav__links strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 14px; }
@media (max-width: 1260px) {
  .app-content__layout--workspace { grid-template-columns: 120px minmax(0, 1fr); gap: 14px; padding: 16px; }
  .workspace-subnav { top: 16px; }
}
@media (max-width: 1100px) {
  .app-shell { --nav-width: 84px; gap: 8px; padding: 8px; }
  .app-topbar { padding-inline: 18px; }
  .app-course-context { max-width: 240px; }
  .app-content__page { padding-inline: 18px; }
  .app-brand__copy strong { font-size: 12px; }
}
@media (max-width: 760px) {
  .app-shell { --nav-width: 68px; gap: 5px; padding: 5px; }
  .app-brand__copy { display: none; }
  .app-brand { min-height: 66px; }
  .app-nav { padding: 5px; }
  .app-nav :deep(.sidebar-item) { font-size: 12px; }
  .app-course-context { max-width: 145px; }
  .app-content__layout--workspace { grid-template-columns: 1fr; }
  .workspace-subnav { position: static; height: auto; }
  .workspace-subnav__title { display: none; }
  .workspace-subnav__links { display: flex; overflow: auto; }
  .workspace-subnav__links a { flex: none; }
}
</style>
