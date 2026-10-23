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
  { path: '/workspace', label: '今日学习', detail: '今天学什么、下一步去哪', icon: BookOpen },
  { path: '/workspace/path', label: '学习路径', detail: '查看接下来学什么', icon: MapPin },
  { path: '/workspace/resources', label: '资源中心', detail: '讲义、练习与实训', icon: FileText },
  { path: '/workspace/assessment', label: '测评中心', detail: '入学诊断与智能组卷', icon: ClipboardCheck },
  { path: '/workspace/review', label: '复习中心', detail: '日历与复习安排', icon: CalendarCheck },
  { path: '/workspace/notes', label: '笔记本', detail: '整理学习摘录', icon: FilePlus2 },
  { path: '/workspace/review/wrong-questions', label: '错题本', detail: '回看错误与原因', icon: ListChecks },
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
          <small>{{ roleLabel }}</small>
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
          <span class="app-user__avatar">{{ avatar }}</span>
          <span class="app-user__copy">
            <strong>{{ displayName }}</strong>
            <small>{{ roleLabel }}</small>
          </span>
        </div>
        <button type="button" class="app-logout" title="退出登录" aria-label="退出登录" @click="$emit('logout')">
          <LogOut :size="17" />
        </button>
      </div>
    </aside>

    <section class="app-frame">
      <header class="app-topbar">
        <PageHeader :eyebrow="pageSection" :title="pageTitle" compact />
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
        <div class="app-content__layout" :class="{ 'app-content__layout--workspace': isWorkspaceRoute }">
          <nav v-if="isWorkspaceRoute" class="workspace-subnav" aria-label="学习空间内部导航">
            <div class="workspace-subnav__title">
              <strong>学习空间</strong>
              <span>{{ courseLabel }}</span>
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
                  <small>{{ item.detail }}</small>
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
  width: 100%;
  height: 100vh;
  min-width: 1180px;
  grid-template-columns: var(--nav-width) minmax(0, 1fr);
  gap: 14px;
  padding: 14px;
  overflow: hidden;
  background: var(--color-page);
}

.app-sidebar {
  display: flex;
  min-width: 0;
  flex-direction: column;
  overflow: hidden;
  border: 1px solid var(--color-border);
  border-radius: 14px;
  background: var(--color-surface);
  box-shadow: 0 12px 32px rgb(6 20 27 / 9%);
}

.app-brand {
  display: flex;
  min-height: 72px;
  align-items: center;
  gap: 11px;
  padding: 0 20px;
  border: 0;
  border-bottom: 1px solid var(--color-border);
  background: transparent;
  text-align: left;
  cursor: pointer;
}

.app-brand__mark {
  display: grid;
  width: 34px;
  height: 34px;
  flex: 0 0 34px;
  place-items: center;
  color: #ffffff;
  border-radius: 6px;
  background: var(--color-accent);
  font-size: 16px;
  font-weight: 700;
}

.app-brand__copy,
.app-user__copy {
  display: grid;
  min-width: 0;
}

.app-brand__copy strong {
  color: var(--color-text);
  font-size: 16px;
  font-weight: 680;
}

.app-brand__copy small,
.app-user__copy small {
  overflow: hidden;
  color: var(--color-text-muted);
  font-size: 14px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.app-nav {
  display: grid;
  align-content: start;
  flex: 1;
  gap: 2px;
  padding: 18px 10px;
  overflow-y: auto;
}

.app-nav :deep(.sidebar-item) {
  border-radius: var(--radius-control);
}

.app-nav :deep(.sidebar-item::before) {
  inset: 7px auto 7px 0;
  border-radius: 0 2px 2px 0;
}

.app-sidebar__footer {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 36px;
  align-items: center;
  gap: 8px;
  padding: 14px 16px;
  border-top: 1px solid var(--color-border);
}

.app-user {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: 10px;
}

.app-user__avatar {
  display: grid;
  width: 34px;
  height: 34px;
  flex: 0 0 34px;
  place-items: center;
  color: var(--color-text);
  border: 1px solid var(--color-border);
  border-radius: 50%;
  background: var(--color-surface-subtle);
  font-size: 14px;
  font-weight: 650;
}

.app-user__copy strong {
  overflow: hidden;
  color: var(--color-text);
  font-size: 14px;
  font-weight: 600;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.app-logout,
.app-search {
  display: grid;
  width: 36px;
  height: 36px;
  place-items: center;
  color: var(--color-text-secondary);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-control);
  background: var(--color-surface);
  cursor: pointer;
}

.app-logout:hover,
.app-search:hover {
  color: var(--color-text);
  border-color: var(--color-border-strong);
  background: var(--color-surface-subtle);
}

.app-frame {
  display: grid;
  min-width: 0;
  min-height: 0;
  grid-template-rows: var(--topbar-height) auto minmax(0, 1fr);
  overflow: hidden;
  border: 1px solid var(--color-border);
  border-radius: 14px;
  background: var(--color-page);
}

.app-topbar {
  display: flex;
  min-width: 0;
  align-items: center;
  justify-content: space-between;
  gap: 24px;
  padding: 6px 24px;
  border-bottom: 1px solid var(--color-border);
  background: var(--color-surface);
  font-family: var(--font-sans);
}

.app-topbar__tools {
  display: flex;
  align-items: center;
  gap: 8px;
}

.app-course-context {
  display: flex;
  height: 36px;
  max-width: 320px;
  align-items: center;
  gap: 8px;
  padding: 0 12px;
  color: var(--color-text-secondary);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-control);
  background: var(--color-surface);
  font-size: 14px;
  cursor: pointer;
}

.app-course-context span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.app-course-context:hover {
  color: var(--color-text);
  background: var(--color-surface-subtle);
}

.app-content {
  min-width: 0;
  min-height: 0;
  overflow: auto;
  background: var(--color-page);
}

.app-content__layout {
  display: block;
  min-width: 0;
  min-height: 100%;
}

.app-content__layout--workspace {
  display: grid;
  grid-template-columns: 168px minmax(0, 1fr);
  gap: 12px;
  align-items: stretch;
  padding: 16px;
}

.app-content__page {
  min-width: 0;
  box-sizing: border-box;
  padding-inline: var(--space-panel-inline);
}

.workspace-subnav {
  display: flex;
  min-width: 0;
  min-height: calc(100vh - var(--topbar-height) - 48px);
  height: calc(100vh - var(--topbar-height) - 48px);
  max-height: calc(100vh - var(--topbar-height) - 48px);
  flex-direction: column;
  align-self: start;
  position: sticky;
  top: 16px;
  overflow-y: auto;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-panel);
  background: var(--color-surface);
  box-shadow: 0 4px 14px rgb(6 20 27 / 4%);
}

.workspace-subnav__title {
  display: grid;
  min-width: 0;
  align-content: center;
  gap: 3px;
  padding: 18px 16px;
  border-bottom: 1px solid var(--color-border);
}

.workspace-subnav__title strong {
  color: var(--color-text);
  font-size: 15px;
}

.workspace-subnav__title span {
  overflow: hidden;
  color: var(--color-text-muted);
  font-size: 14px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.workspace-subnav__links {
  display: grid;
  min-width: 0;
  grid-template-columns: 1fr;
  gap: 4px;
  padding: 12px 8px;
}

.workspace-subnav__links a {
  display: flex;
  min-width: 0;
  min-height: 44px;
  align-items: center;
  gap: 8px;
  padding: 10px;
  color: var(--color-text-secondary);
  border-radius: var(--radius-control);
  text-decoration: none;
}

.workspace-subnav__links a:hover {
  color: var(--color-text);
  background: var(--color-surface-subtle);
}

.workspace-subnav__links a.active {
  color: #fff;
  background: var(--color-accent);
}

.workspace-subnav__links a > span {
  display: grid;
  min-width: 0;
  gap: 1px;
}

.workspace-subnav__links strong,
.workspace-subnav__links small {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.workspace-subnav__links strong {
  font-size: 14px;
  font-weight: 650;
}

.workspace-subnav__links small {
  color: var(--color-text-muted);
  font-size: 14px;
  line-height: 1.3;
}

.workspace-subnav__links a.active small {
  color: rgb(255 255 255 / 78%);
}

@media (max-width: 1260px) {
  .app-content__layout--workspace {
    grid-template-columns: 150px minmax(0, 1fr);
    gap: 10px;
    padding: 12px;
  }

  .workspace-subnav__links {
    padding: 8px 6px;
  }

  .workspace-subnav__links a {
    gap: 6px;
    padding-right: 6px;
    padding-left: 6px;
  }

  .workspace-subnav {
    top: 12px;
    min-height: calc(100vh - var(--topbar-height) - 36px);
    height: calc(100vh - var(--topbar-height) - 36px);
    max-height: calc(100vh - var(--topbar-height) - 36px);
  }
}

/* Fast surface migration: keep the shell calm and readable on desktop. */
.app-shell {
  --nav-width: 216px;
  gap: 12px;
  padding: 12px;
  background: var(--color-page);
}

.app-sidebar,
.app-frame {
  border-radius: 8px;
  box-shadow: 0 3px 16px rgb(23 37 46 / 7%);
}

.app-brand {
  min-height: 68px;
  flex-direction: row;
  justify-content: flex-start;
  gap: 10px;
  padding: 0 16px;
  text-align: left;
}

.app-brand__copy { justify-items: start; text-align: left; }
.app-brand__copy strong { font-size: 16px; }

.app-nav {
  gap: 2px;
  padding: 14px 10px;
}

.app-nav :deep(.sidebar-item) {
  min-height: 42px;
  flex-direction: row;
  justify-content: flex-start;
  gap: 10px;
  padding: 0 12px;
  border-radius: 6px;
  text-align: left;
}

.app-nav :deep(.sidebar-item__icon) { width: 19px; height: 19px; flex-basis: 19px; }
.app-nav :deep(.sidebar-item__label) { white-space: nowrap; }

.app-sidebar__footer {
  grid-template-columns: minmax(0, 1fr) 36px;
  padding: 12px 14px;
}

.app-user { flex-direction: row; text-align: left; }
.app-user__copy { justify-items: start; text-align: left; }

.app-content__layout--workspace { grid-template-columns: 168px minmax(0, 1fr); gap: 16px; padding: 16px; }
.app-content__page { padding-inline: clamp(18px, 2vw, 32px); }

@media (min-width: 2200px) {
  .app-shell { --nav-width: 232px; }
  .app-content__layout--workspace { grid-template-columns: 184px minmax(0, 1fr); gap: 20px; padding: 20px; }
}

/* FB-FE-01: let the learning surface carry the width; keep navigation readable. */
.app-shell {
  --nav-width: 104px;
}

.app-brand {
  min-height: 88px;
  align-items: center;
  flex-direction: column;
  justify-content: center;
  gap: 6px;
  padding: 12px 8px;
  text-align: center;
}

.app-brand__mark {
  width: 30px;
  height: 30px;
  flex-basis: 30px;
  font-size: 15px;
}

.app-brand__copy {
  justify-items: center;
  width: 100%;
}

.app-brand__copy strong {
  font-size: 14px;
}

.app-brand__copy small {
  max-width: 100%;
  overflow-wrap: anywhere;
  white-space: normal;
  font-size: 14px;
  line-height: 1.25;
}

.app-nav {
  gap: 6px;
  padding: 12px 8px;
}

.app-nav :deep(.sidebar-item) {
  min-height: 68px;
  align-items: center;
  justify-content: center;
  flex-direction: column;
  gap: 5px;
  padding: 8px 4px;
  text-align: center;
  font-size: 14px;
  line-height: 1.25;
}

.app-nav :deep(.sidebar-item::before) {
  inset: auto 12px 3px;
  width: auto;
  height: 2px;
  border-radius: 2px;
}

.app-nav :deep(.sidebar-item__icon) {
  width: 24px;
  height: 24px;
  flex-basis: 24px;
}

.app-nav :deep(.sidebar-item__label) {
  max-width: 100%;
  overflow-wrap: anywhere;
  white-space: normal;
}

.app-sidebar__footer {
  grid-template-columns: 1fr;
  gap: 8px;
  padding: 12px 8px;
}

.app-user {
  align-items: center;
  flex-direction: column;
  gap: 6px;
  text-align: center;
}

.app-user__copy {
  justify-items: center;
  width: 100%;
  text-align: center;
}

.app-user__copy strong,
.app-user__copy small {
  max-width: 100%;
  overflow-wrap: anywhere;
  white-space: normal;
  line-height: 1.25;
}

.app-logout {
  justify-self: center;
}

.app-content__layout--workspace {
  grid-template-columns: 136px minmax(0, 1fr);
  gap: 18px;
  padding: 20px;
}

.workspace-subnav {
  top: 20px;
  min-height: calc(100vh - var(--topbar-height) - 56px);
  height: calc(100vh - var(--topbar-height) - 56px);
  max-height: calc(100vh - var(--topbar-height) - 56px);
}

.workspace-subnav__title {
  gap: 4px;
  padding: 14px 12px;
}

.workspace-subnav__title strong {
  font-size: 14px;
}

.workspace-subnav__title span {
  font-size: 14px;
}

.workspace-subnav__links {
  gap: 3px;
  padding: 10px 6px;
}

.workspace-subnav__links a {
  min-height: 42px;
  gap: 7px;
  padding: 8px 7px;
}

.workspace-subnav__links strong {
  font-size: 14px;
}

.workspace-subnav__links small {
  font-size: 14px;
}

@media (max-width: 1260px) {
  .app-content__layout--workspace {
    grid-template-columns: 120px minmax(0, 1fr);
    gap: 14px;
    padding: 16px;
  }

  .workspace-subnav {
    top: 16px;
    min-height: calc(100vh - var(--topbar-height) - 48px);
    height: calc(100vh - var(--topbar-height) - 48px);
    max-height: calc(100vh - var(--topbar-height) - 48px);
  }
}
</style>
