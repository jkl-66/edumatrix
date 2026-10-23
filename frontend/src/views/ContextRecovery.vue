<script setup>
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { AlertTriangle, ArrowLeft, BookOpen, Info } from '@lucide/vue'
import { useCourseContextStore } from '../stores/courseContext'
import { roleLandingPath } from '../utils/roleLanding'

const route = useRoute()
const router = useRouter()
const context = useCourseContextStore()

const reason = computed(() => String(route.query.reason || 'context_unknown'))
const isContextIssue = computed(() => reason.value.startsWith('context_'))
const isUnavailableCourse = computed(() => (
  ['context_course_unavailable', 'context_object_not_found'].includes(reason.value)
  && String(route.query.field || '') === 'courseId'
))
const sourceValue = computed(() => {
  if (isContextIssue.value) return '原学习位置已清除'
  return String(route.query.legacy_path || '当前地址')
})

const recoveryCopy = {
  context_course_required: { title: '需要重新选择课程', message: '原链接没有包含可验证的课程上下文。', sourceLabel: '原对象' },
  context_course_unavailable: { title: '原课程已不可用', message: '这门课程已停止使用或暂时没有可用学习资料，请从当前知识库重新选择。', sourceLabel: '恢复状态' },
  context_object_not_found: { title: '原学习对象已不可用', message: '对象可能已删除、迁移或链接不完整。', sourceLabel: '原对象' },
  context_version_stale: { title: '学习内容已有新版本', message: '为避免覆盖最近进度，请从当前课程重新进入。', sourceLabel: '原对象' },
  context_forbidden: { title: '当前账号无权访问', message: '请切换到有权限的账号或选择自己的课程。', sourceLabel: '原对象' },
  context_cross_user: { title: '这不是当前账号的学习对象', message: '系统已阻止跨用户读取，原对象不会被复制到当前账号。', sourceLabel: '原对象' },
  context_course_mismatch: { title: '对象与课程不一致', message: '请从课程路径、资源中心或测评中心重新打开。', sourceLabel: '原对象' },
  context_object_unavailable: { title: '学习对象已归档或撤回', message: '历史记录仍会保留，但该对象不能继续编辑。', sourceLabel: '原对象' },
  context_service_unavailable: { title: '暂时无法恢复学习位置', message: '课程服务与兼容入口均暂时不可用，请稍后重试或重新选择课程。', sourceLabel: '原对象' },
  feature_deferred: { title: '此功能暂未开放', message: '当前版本优先保证完整学习闭环，这个独立入口暂不作为正式功能提供。', sourceLabel: '原入口' },
  feature_internal: { title: '此入口仅供内部验证', message: '它不属于学生、教师或管理员的日常工作入口，请返回当前账号首页继续使用。', sourceLabel: '原入口' },
  feature_removed: { title: '此入口已停止使用', message: '相关能力已合并到正式学习流程，旧的独立工作台不再开放。', sourceLabel: '原入口' },
  route_unknown: { title: '没有找到这个页面', message: '地址可能已经更新或输入有误。你的课程和学习记录没有发生变化。', sourceLabel: '原地址' },
  context_unknown: { title: '学习位置需要恢复', message: '系统无法确认原链接中的课程、对象或版本。', sourceLabel: '原对象' },
}

const copy = computed(() => {
  if (isUnavailableCourse.value) return recoveryCopy.context_course_unavailable
  return recoveryCopy[reason.value] || recoveryCopy.context_unknown
})
const homeLabel = computed(() => {
  const role = localStorage.getItem('edumatrix_role')
  if (role === 'teacher') return '返回教学总览'
  if (role === 'admin') return '返回系统管理'
  return '返回学习首页'
})

function reselectCourse() {
  context.clear({ keepCourse: false })
  router.push({ path: '/workspace', query: { context: 'select-course' } })
}

function returnHome() {
  context.clear({ keepCourse: false })
  router.push('/')
}

function returnToRoleHome() {
  router.push(roleLandingPath(localStorage.getItem('edumatrix_role')))
}

function handlePrimaryAction() {
  if (isContextIssue.value) reselectCourse()
  else returnToRoleHome()
}
</script>

<template>
  <section class="context-recovery" aria-labelledby="context-recovery-title">
    <div class="context-recovery__icon" :class="{ 'context-recovery__icon--danger': isContextIssue }" aria-hidden="true">
      <component :is="isContextIssue ? AlertTriangle : Info" :size="24" />
    </div>
    <p class="context-recovery__eyebrow">学习位置恢复</p>
    <h1 id="context-recovery-title">{{ copy.title }}</h1>
    <p class="context-recovery__message">{{ copy.message }}</p>

    <dl class="context-recovery__facts">
      <div>
        <dt>{{ copy.sourceLabel }}</dt>
        <dd>{{ sourceValue }}</dd>
      </div>
      <div>
        <dt>处理结果</dt>
        <dd>没有创建空对象，也没有修改现有学习记录</dd>
      </div>
    </dl>

    <div class="context-recovery__actions">
      <button type="button" class="button-primary" @click="handlePrimaryAction">
        <BookOpen v-if="isContextIssue" :size="17" />
        <ArrowLeft v-else :size="17" />
        {{ isContextIssue ? '重新选择课程' : homeLabel }}
      </button>
      <button v-if="isContextIssue" type="button" class="button-secondary" @click="returnHome">
        <ArrowLeft :size="17" />
        返回首页
      </button>
    </div>
  </section>
</template>

<style scoped>
.context-recovery {
  width: min(720px, calc(100% - 48px));
  margin: 72px auto;
  color: var(--color-text);
}

.context-recovery__icon {
  display: grid;
  width: 48px;
  height: 48px;
  place-items: center;
  color: var(--color-accent);
  border: 1px solid var(--color-border-strong);
  border-radius: 8px;
  background: var(--color-surface-card);
}

.context-recovery__icon--danger {
  color: var(--color-danger);
  border-color: color-mix(in srgb, var(--color-danger) 28%, var(--color-border));
}

.context-recovery__eyebrow {
  margin: 28px 0 8px;
  color: var(--color-text-muted);
  font-size: 14px;
}

h1 {
  margin: 0;
  font-size: 30px;
  line-height: 1.28;
  letter-spacing: 0;
}

.context-recovery__message {
  max-width: 620px;
  margin: 14px 0 0;
  color: var(--color-text-secondary);
  font-size: 16px;
  line-height: 1.75;
}

.context-recovery__facts {
  display: grid;
  margin: 34px 0 0;
  border-top: 1px solid var(--color-border);
  border-bottom: 1px solid var(--color-border);
}

.context-recovery__facts div {
  display: grid;
  grid-template-columns: 112px minmax(0, 1fr);
  gap: 20px;
  padding: 16px 0;
}

.context-recovery__facts div + div {
  border-top: 1px solid var(--color-border);
}

dt,
dd {
  margin: 0;
  font-size: 15px;
  line-height: 1.6;
}

dt {
  color: var(--color-text-muted);
}

dd {
  overflow-wrap: anywhere;
}

.context-recovery__actions {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 28px;
}

.context-recovery__actions button {
  display: inline-flex;
  min-height: 40px;
  align-items: center;
  gap: 8px;
  padding: 0 16px;
  border-radius: 6px;
  font-size: 15px;
  font-weight: 600;
  cursor: pointer;
}

.button-primary {
  color: #ffffff;
  border: 1px solid var(--color-accent);
  background: var(--color-accent);
}

.button-secondary {
  color: var(--color-text);
  border: 1px solid var(--color-border-strong);
  background: var(--color-surface);
}

.context-recovery__actions button:focus-visible {
  outline: 2px solid var(--color-accent);
  outline-offset: 2px;
}
</style>
