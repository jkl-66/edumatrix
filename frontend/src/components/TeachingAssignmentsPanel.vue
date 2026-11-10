<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { listTeachingClasses } from '../api/courseGovernance'
import { userMessage } from '../services/errorTranslator'
import { learningText } from '../utils/learningCopy'

const props = defineProps({ courseId: { type: String, default: '' } })
const classes = ref([]), loading = ref(false), error = ref('')
let request = 0
const assignments = computed(() => classes.value.flatMap(classroom => classroom.tasks.map(task => ({
  ...task, courseId: classroom.course_id, classTitle: classroom.title,
  groupName: classroom.groups.find(group => group.id === task.group_id)?.name || '全班',
}))))
async function load() {
  const current = ++request
  classes.value = []; error.value = ''; loading.value = true
  try {
    const result = await listTeachingClasses(props.courseId || undefined)
    if (current === request) classes.value = result.items.filter(item => !item.can_manage && item.status === 'active')
  } catch (caught) {
    if (current === request) error.value = userMessage(caught, '暂时没能读取老师的安排，请重试。')
  } finally { if (current === request) loading.value = false }
}
function deadline(task) {
  if (!task.due_at) return '未设置截止时间'
  const date = new Date(task.due_at)
  if (!Number.isFinite(date.getTime())) return '截止时间请向老师确认'
  const text = date.toLocaleString('zh-CN', { month: 'long', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false })
  return `${text} 截止${date.getTime() < Date.now() ? ' · 已过截止时间' : ''}`
}
watch(() => props.courseId, load, { immediate: true })
onBeforeUnmount(() => { request += 1 })
</script>

<template>
  <section v-if="assignments.length || error" class="teaching-assignments" data-testid="teaching-assignments">
    <header><div><h2>老师的学习安排</h2><p>查看本班和所在小组的任务，再到课程资料中学习。</p></div><button :disabled="loading" @click="load">刷新安排</button></header>
    <p v-if="error" role="alert">{{ error }}</p>
    <article v-for="task in assignments" :key="task.id">
      <div><h3>{{ task.title }}</h3><span>{{ task.classTitle }} · {{ task.groupName }}</span></div>
      <p>{{ learningText(task.instructions) }}</p>
      <footer><span>{{ deadline(task) }}</span><router-link :to="{ path: `/knowledge/courses/${encodeURIComponent(task.courseId)}`, query: { course_id: task.courseId } }">打开课程资料</router-link></footer>
    </article>
  </section>
</template>

<style scoped>
.teaching-assignments{margin-top:24px;padding:20px;border:1px solid var(--color-border);border-radius:var(--radius-panel);background:var(--color-surface);color:var(--color-text)}
header,footer{display:flex;justify-content:space-between;align-items:center;gap:12px}h2{margin:0;font-size:19px}h3{margin:0 0 6px;font-size:16px}p{margin:8px 0;line-height:1.6;white-space:pre-wrap;font-size:14px}header p,span{color:var(--color-text-secondary);font-size:14px}article{padding:16px 0;border-top:1px solid var(--color-border);margin-top:12px}button,a{border:1px solid var(--color-border-strong);border-radius:var(--radius-control);padding:8px 12px;background:var(--color-surface);color:var(--color-text);font-size:14px;cursor:pointer}footer{flex-wrap:wrap}
</style>
