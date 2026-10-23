<script setup>
import { computed, onMounted, ref } from 'vue'
import { Archive, BookOpenCheck, CalendarClock, CircleAlert, Layers3, Plus, Send, ShieldCheck, UserPlus, UsersRound } from '@lucide/vue'
import { createTeachingClass, createTeachingGroup, createTeachingTask, getCourseGovernanceCatalog, listTeachingClasses, publishTeachingTask, saveTeachingMember, withdrawGovernedCourse } from '../api'

const catalog = ref({ courses: [], candidate_members: [] })
const classes = ref([])
const selectedClassId = ref('')
const selectedCourseId = ref('')
const loading = ref(true)
const busy = ref('')
const error = ref('')
const notice = ref('')
const classForm = ref({ title: '2026 秋季 AI 实训班', term: '2026 秋' })
const groupForm = ref({ name: '项目 A 组', description: '协作完成检索实验' })
const memberForm = ref({ user_public_id: '', role: 'student', group_id: '' })
const taskForm = ref({ title: '完成虚拟实验并提交结果', instructions: '运行实验、通过隐藏验收并记录反思。', group_id: '', due_at: '' })
const withdrawalReason = ref('课程版本停止教学，暂停成员与未归档任务并保留历史证据。')

const selectedClass = computed(() => classes.value.find(item => item.id === selectedClassId.value) || classes.value[0] || null)
const selectedCourse = computed(() => catalog.value.courses.find(item => item.id === selectedCourseId.value) || null)

function detail(caught, fallback) {
  const value = caught?.response?.data?.detail
  return value?.message || (typeof value === 'string' ? value : '') || caught?.message || fallback
}

async function load(courseId = selectedCourseId.value) {
  loading.value = true; error.value = ''
  try {
    catalog.value = await getCourseGovernanceCatalog()
    if (!selectedCourseId.value && catalog.value.courses.length) selectedCourseId.value = catalog.value.courses.find(item => item.status !== 'withdrawn')?.id || catalog.value.courses[0].id
    classes.value = (await listTeachingClasses(courseId || selectedCourseId.value)).items
    if (!classes.value.some(item => item.id === selectedClassId.value)) selectedClassId.value = classes.value[0]?.id || ''
    if (!memberForm.value.user_public_id) memberForm.value.user_public_id = catalog.value.candidate_members.find(item => item.role === 'student')?.public_id || ''
  } catch (caught) { error.value = detail(caught, '治理工作台加载失败') }
  finally { loading.value = false }
}

async function selectCourse() { selectedClassId.value = ''; await load(selectedCourseId.value) }
async function execute(key, callback, success) {
  busy.value = key; error.value = ''; notice.value = ''
  try {
    const result = await callback()
    if (result?.id && result?.course_id && result?.groups) selectedClassId.value = result.id
    await load(selectedCourseId.value); notice.value = success
  } catch (caught) { error.value = detail(caught, '操作失败') }
  finally { busy.value = '' }
}

const addClass = () => execute('class', () => createTeachingClass({ course_id:selectedCourseId.value, ...classForm.value }), '班级已建立。')
const addGroup = () => execute('group', () => createTeachingGroup(selectedClass.value.id, groupForm.value), '分组已建立。')
const addMember = () => execute('member', () => saveTeachingMember(selectedClass.value.id, { ...memberForm.value, group_id:memberForm.value.group_id || null, expected_version:null }), '成员已加入，课程权限已同步。')
const addTask = () => execute('task', () => createTeachingTask(selectedClass.value.id, { ...taskForm.value, group_id:taskForm.value.group_id || null, due_at:taskForm.value.due_at || null, idempotency_key:`task-ui-${Date.now()}` }), '教学任务草稿已保存。')
const publishTask = task => execute(`publish-${task.id}`, () => publishTeachingTask(task.id, task.lock_version), '教学任务已发布。')
async function withdrawCourse() {
  if (!selectedCourse.value || !window.confirm('撤回会暂停该课程的班级、成员和未归档任务，且不会自动恢复。确认继续？')) return
  await execute('withdraw', () => withdrawGovernedCourse(selectedCourse.value.id, { reason:withdrawalReason.value, expected_status:selectedCourse.value.status }), '课程已撤回，影响快照已冻结。')
}

onMounted(() => load())
</script>

<template>
  <main class="governance" data-testid="course-governance-workspace">
    <header><div><p class="eyebrow">TEACHING GOVERNANCE</p><h1>班级与教学任务治理</h1><p>以课程成员为授权事实源，管理班级、分组、任务与撤回影响。</p></div><span class="guard"><ShieldCheck :size="17" />角色与版本门禁</span></header>
    <p v-if="error" class="notice error"><CircleAlert :size="15" />{{ error }}</p><p v-if="notice" class="notice success">{{ notice }}</p>
    <p v-if="loading" class="notice">正在恢复治理状态...</p>
    <template v-else>
      <section class="course-band">
        <label>管理课程<select v-model="selectedCourseId" aria-label="管理课程" @change="selectCourse"><option v-for="course in catalog.courses" :key="course.id" :value="course.id">{{ course.title }} · {{ course.status }}</option></select></label>
        <div><span>版本</span><strong>{{ selectedCourse?.version || '-' }}</strong></div><div><span>状态</span><strong>{{ selectedCourse?.status || '-' }}</strong></div>
        <button class="danger" :disabled="busy || !selectedCourse || selectedCourse.status === 'withdrawn'" @click="withdrawCourse"><Archive :size="15" />撤回课程</button>
      </section>
      <label class="withdraw-reason">撤回原因<input v-model="withdrawalReason" aria-label="撤回原因" /></label>

      <div class="governance-grid">
        <aside>
          <div class="section-title"><span>班级</span><small>{{ classes.length }}</small></div>
          <button v-for="item in classes" :key="item.id" data-testid="teaching-class" :class="{ active:selectedClass?.id === item.id }" @click="selectedClassId=item.id"><BookOpenCheck :size="15" /><span><strong>{{ item.title }}</strong><small>{{ item.term }} · {{ item.status }}</small></span></button>
          <div class="compact-form"><input v-model="classForm.title" aria-label="班级名称" placeholder="班级名称" :disabled="selectedCourse?.status === 'withdrawn'" /><input v-model="classForm.term" aria-label="学期" placeholder="学期" :disabled="selectedCourse?.status === 'withdrawn'" /><button :disabled="Boolean(busy) || !selectedCourseId || selectedCourse?.status === 'withdrawn'" @click="addClass"><Plus :size="14" />新建班级</button></div>
        </aside>

        <section v-if="selectedClass" class="class-panel" data-testid="class-management-panel">
          <div class="section-title"><span>{{ selectedClass.title }}</span><small>v{{ selectedClass.lock_version }} · {{ selectedClass.status }}</small></div>
          <div class="stats"><div><UsersRound :size="17" /><strong>{{ selectedClass.members.length }}</strong><span>成员</span></div><div><Layers3 :size="17" /><strong>{{ selectedClass.groups.length }}</strong><span>分组</span></div><div><CalendarClock :size="17" /><strong>{{ selectedClass.tasks.length }}</strong><span>任务</span></div></div>

          <div class="columns">
            <article><h2>分组</h2><div class="chips"><span v-for="group in selectedClass.groups" :key="group.id">{{ group.name }}</span></div><div class="inline-form"><input v-model="groupForm.name" aria-label="分组名称" :disabled="selectedClass.status !== 'active'" /><input v-model="groupForm.description" aria-label="分组说明" :disabled="selectedClass.status !== 'active'" /><button :disabled="Boolean(busy) || selectedClass.status !== 'active'" title="添加分组" @click="addGroup"><Plus :size="15" /></button></div></article>
            <article><h2>成员</h2><div class="member" v-for="member in selectedClass.members" :key="member.id"><span><strong>{{ member.user.display_name || member.user.username }}</strong><small>{{ member.role }} · {{ member.status }}</small></span><em>{{ selectedClass.groups.find(group => group.id === member.group_id)?.name || '未分组' }}</em></div><div class="member-form"><select v-model="memberForm.user_public_id" aria-label="候选成员" :disabled="selectedClass.status !== 'active'"><option v-for="user in catalog.candidate_members" :key="user.public_id" :value="user.public_id">{{ user.display_name || user.username }} · {{ user.role }}</option></select><select v-model="memberForm.group_id" aria-label="成员分组" :disabled="selectedClass.status !== 'active'"><option value="">未分组</option><option v-for="group in selectedClass.groups" :key="group.id" :value="group.id">{{ group.name }}</option></select><button :disabled="Boolean(busy) || !memberForm.user_public_id || selectedClass.status !== 'active'" @click="addMember"><UserPlus :size="14" />加入</button></div></article>
          </div>

          <article class="tasks"><h2>教学任务</h2><div v-for="task in selectedClass.tasks" :key="task.id" data-testid="teaching-task" class="task"><span class="task-status">{{ task.status }}</span><div><strong>{{ task.title }}</strong><p>{{ task.instructions }}</p><small>{{ task.group_id ? selectedClass.groups.find(group => group.id === task.group_id)?.name : '全班任务' }} · {{ task.due_at || '无截止时间' }}</small></div><button v-if="task.status === 'draft'" :disabled="Boolean(busy) || selectedClass.status !== 'active'" @click="publishTask(task)"><Send :size="14" />发布</button></div><div class="task-form"><input v-model="taskForm.title" aria-label="任务名称" :disabled="selectedClass.status !== 'active'" /><textarea v-model="taskForm.instructions" aria-label="任务说明" :disabled="selectedClass.status !== 'active'"></textarea><select v-model="taskForm.group_id" aria-label="任务范围" :disabled="selectedClass.status !== 'active'"><option value="">全班</option><option v-for="group in selectedClass.groups" :key="group.id" :value="group.id">{{ group.name }}</option></select><input v-model="taskForm.due_at" aria-label="截止时间" type="datetime-local" :disabled="selectedClass.status !== 'active'" /><button :disabled="Boolean(busy) || selectedClass.status !== 'active'" @click="addTask"><Plus :size="14" />保存任务草稿</button></div></article>
        </section>
        <section v-else class="empty">选择课程并建立第一个班级。</section>
      </div>
    </template>
  </main>
</template>

<style scoped>
.governance{max-width:1180px;margin:0 auto;color:#28342c}.governance>header{display:flex;justify-content:space-between;gap:20px;padding-bottom:20px;border-bottom:1px solid #dce2dd}.eyebrow{margin:0 0 6px;color:#4c7059;font-size:10px;font-weight:800}.governance h1{margin:0;font-size:22px;letter-spacing:0}.governance header p:last-child{margin:7px 0 0;color:#69756d;font-size:12px}.guard{display:flex;align-items:center;gap:7px;align-self:center;padding:10px 13px;border:1px solid #cee0d3;background:#f2f8f4;color:#365f43;font-size:10px;font-weight:700}.notice{display:flex;gap:7px;margin:12px 0;padding:10px;background:#f3f5f3;font-size:11px}.notice.error{background:#fff1ef;color:#8b493e}.notice.success{background:#eef8f1;color:#386548}.course-band{display:grid;grid-template-columns:minmax(280px,1fr) 100px 100px auto;gap:10px;align-items:end;margin-top:16px;padding:14px;border:1px solid #dce3de;background:#fff}.course-band label,.withdraw-reason{color:#6e7a72;font-size:9px}.course-band select,.withdraw-reason input,.compact-form input,.inline-form input,.member-form select,.task-form input,.task-form select,.task-form textarea{width:100%;box-sizing:border-box;border:1px solid #d5ddd7;background:#fff}.course-band select{height:36px;margin-top:5px;padding:0 8px}.course-band div span,.course-band div strong{display:block}.course-band div span{font-size:8px;color:#7c877f}.course-band div strong{margin-top:7px;font-size:11px}.course-band button,.compact-form button,.member-form button,.task-form button,.task button{display:inline-flex;align-items:center;justify-content:center;gap:5px;min-height:34px;padding:0 10px;border:1px solid #ccd7cf;background:#fff;font-size:10px}.course-band .danger{border-color:#e1c5bf;color:#8b4e43}.withdraw-reason{display:block;margin:9px 0 14px}.withdraw-reason input{height:34px;margin-top:4px;padding:0 9px}.governance-grid{display:grid;grid-template-columns:230px minmax(0,1fr);gap:14px}.governance-grid>aside,.class-panel,.empty{border:1px solid #dce2de;background:#fff}.governance-grid>aside,.class-panel{padding:13px}.section-title{display:flex;justify-content:space-between;padding-bottom:10px;border-bottom:1px solid #e5e9e6}.section-title span{font-size:12px;font-weight:750}.section-title small{font-size:9px;color:#78837b}aside>button{display:flex;width:100%;gap:8px;padding:10px 5px;text-align:left;border:0;border-bottom:1px solid #edf0ee;background:transparent}aside>button.active{background:#f1f7f3}aside button span,aside button strong,aside button small{display:block}aside button strong{font-size:10px}aside button small{margin-top:3px;color:#7b867f;font-size:8px}.compact-form{display:grid;gap:6px;margin-top:12px}.compact-form input,.inline-form input{height:33px;padding:0 8px}.stats{display:grid;grid-template-columns:repeat(3,1fr);margin:12px 0;border:1px solid #e0e6e1}.stats div{display:grid;grid-template-columns:auto 1fr;gap:1px 8px;padding:10px;border-right:1px solid #e5e9e6}.stats div:last-child{border:0}.stats svg{grid-row:1/3}.stats strong{font-size:14px}.stats span{font-size:8px;color:#7b867f}.columns{display:grid;grid-template-columns:1fr 1fr;gap:12px}.columns article,.tasks{padding:12px;border:1px solid #e0e5e1}.columns h2,.tasks h2{margin:0 0 9px;font-size:11px}.chips{display:flex;flex-wrap:wrap;gap:5px}.chips span{padding:5px 7px;background:#edf4ef;color:#44614e;font-size:8px}.inline-form{display:grid;grid-template-columns:1fr 1fr auto;gap:5px;margin-top:9px}.member{display:flex;justify-content:space-between;gap:8px;padding:7px 0;border-bottom:1px solid #edf0ee}.member span,.member strong,.member small{display:block}.member strong{font-size:9px}.member small,.member em{margin-top:2px;color:#7b867f;font-size:8px;font-style:normal}.member-form{display:grid;grid-template-columns:1fr 1fr auto;gap:5px;margin-top:8px}.member-form select{height:33px;padding:0 5px;font-size:8px}.tasks{margin-top:12px}.task{display:grid;grid-template-columns:auto 1fr auto;gap:9px;align-items:start;padding:10px 0;border-top:1px solid #edf0ee}.task-status{padding:4px 6px;background:#eef3ef;color:#4b6554;font-size:8px}.task strong{font-size:10px}.task p{margin:4px 0;color:#657168;font-size:9px}.task small{font-size:8px;color:#7e8981}.task-form{display:grid;grid-template-columns:1fr 1.3fr .8fr .9fr auto;gap:6px;margin-top:10px}.task-form input,.task-form select{height:34px;padding:0 7px;font-size:9px}.task-form textarea{height:34px;padding:7px;resize:vertical;font-size:9px}.empty{display:grid;min-height:260px;place-items:center;color:#7c877f;font-size:11px}@media(max-width:900px){.course-band{grid-template-columns:1fr 1fr}.course-band label{grid-column:1/-1}.governance-grid{grid-template-columns:1fr}.columns{grid-template-columns:1fr}.task-form{grid-template-columns:1fr 1fr}.task-form textarea{grid-column:1/-1}}@media(max-width:520px){.governance>header{flex-direction:column}.guard{align-self:flex-start}.course-band{grid-template-columns:1fr}.course-band label{grid-column:auto}.stats{grid-template-columns:1fr}.stats div{border-right:0;border-bottom:1px solid #e5e9e6}.inline-form,.member-form,.task-form{grid-template-columns:1fr}.task-form textarea{grid-column:auto}.task{grid-template-columns:1fr}.course-band button,.compact-form button,.member-form button,.task-form button,.task button{width:100%}}
.governance :disabled{cursor:not-allowed;opacity:.48}
</style>
