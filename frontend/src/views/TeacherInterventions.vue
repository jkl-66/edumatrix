<script setup>
import { computed, onMounted, ref } from 'vue'
import {
  AlertCircle,
  BookOpen,
  Check,
  CheckCircle2,
  ChevronDown,
  ClipboardPlus,
  RefreshCw,
  ShieldCheck,
  UserCheck,
} from '@lucide/vue'
import { getTeacherCourses, getTeacherStudent } from '../api/teacher'
import {
  confirmM6TeacherIntervention,
  getM6TeacherInterventions,
  publishM6TeacherIntervention,
} from '../api/m6'

const courses = ref([])
const selectedCourseId = ref('')
const selectedStudentId = ref('')
const data = ref({ students: [], interventions: [] })
const detail = ref(null)
const loading = ref(true)
const detailLoading = ref(false)
const busy = ref('')
const error = ref('')
const notice = ref('')

const students = computed(() => data.value.students || [])
const interventions = computed(() => data.value.interventions || [])
const selectedStudent = computed(() => (
  students.value.find((student) => student.public_id === selectedStudentId.value) || null
))
const selectedCourse = computed(() => (
  courses.value.find((course) => course.id === selectedCourseId.value) || null
))
const selectedIntervention = computed(() => (
  interventions.value.find((item) => item.learner_public_id === selectedStudentId.value) || null
))
const pendingConfirmations = computed(() => (
  interventions.value.filter((item) => item.learner_event_id && !item.teacher_confirmed).length
))

const agentRoleLabels = {
  analysis: '学情分析',
  generation: '方案生成',
  validation: '交叉校验',
  decision: '最终决定',
}

function errorMessage(value) {
  const detailValue = value?.response?.data?.detail || value?.detail || value?.message
  if (typeof detailValue === 'string') return detailValue
  return detailValue?.message || '操作未完成，当前结果已保留，请稍后重试。'
}

function statusLabel(value) {
  return {
    pending: '待开始',
    in_progress: '进行中',
    completed: '已完成',
  }[value] || '待处理'
}

function masteryLabel(value) {
  return Number.isFinite(Number(value)) ? `${Math.round(Number(value) * 100)}%` : '证据不足'
}

async function loadDetail(studentId, { clear = true } = {}) {
  if (!studentId || !selectedCourseId.value) {
    detail.value = null
    return
  }
  detailLoading.value = true
  if (clear) detail.value = null
  try {
    detail.value = await getTeacherStudent(studentId, selectedCourseId.value)
  } catch (value) {
    error.value = errorMessage(value)
  } finally {
    detailLoading.value = false
  }
}

async function load() {
  loading.value = true
  error.value = ''
  notice.value = ''
  try {
    const coursePayload = await getTeacherCourses()
    courses.value = coursePayload.items || []
    const storedCourseId = localStorage.getItem('edumatrix_course_id') || ''
    if (!courses.value.some((course) => course.id === selectedCourseId.value)) {
      selectedCourseId.value = courses.value.some((course) => course.id === storedCourseId)
        ? storedCourseId
        : courses.value[0]?.id || ''
    }
    if (!selectedCourseId.value) {
      data.value = { students: [], interventions: [] }
      detail.value = null
      return
    }
    data.value = await getM6TeacherInterventions(selectedCourseId.value)
    if (!students.value.some((student) => student.public_id === selectedStudentId.value)) {
      selectedStudentId.value = students.value[0]?.public_id || ''
    }
    await loadDetail(selectedStudentId.value)
  } catch (value) {
    error.value = errorMessage(value)
  } finally {
    loading.value = false
  }
}

async function changeCourse() {
  const course = selectedCourse.value
  if (course) {
    localStorage.setItem('edumatrix_course_id', course.id)
    localStorage.setItem('edumatrix_course_title', course.title)
  }
  selectedStudentId.value = ''
  await load()
}

async function selectStudent(studentId) {
  if (studentId === selectedStudentId.value && detail.value) return
  error.value = ''
  selectedStudentId.value = studentId
  await loadDetail(studentId)
}

async function publish() {
  if (!selectedStudent.value || !selectedCourseId.value) return
  const studentId = selectedStudent.value.public_id
  busy.value = `publish-${studentId}`
  error.value = ''
  notice.value = ''
  try {
    const result = await publishM6TeacherIntervention({
      course_id: selectedCourseId.value,
      learner_public_id: studentId,
      idempotency_key: `teacher-intervention-${selectedCourseId.value}-${studentId}`,
    })
    notice.value = result.created
      ? '干预任务已加入学生路径，等待学生完成并提交学习证据。'
      : '该干预任务已经存在，没有重复创建。'
    data.value = await getM6TeacherInterventions(selectedCourseId.value)
    await loadDetail(studentId, { clear: false })
  } catch (value) {
    error.value = errorMessage(value)
  } finally {
    busy.value = ''
  }
}

async function confirm(item) {
  busy.value = `confirm-${item.path_id}`
  error.value = ''
  notice.value = ''
  try {
    await confirmM6TeacherIntervention(item.path_id, item.learner_event_id)
    notice.value = '教师复核已记录，干预任务现在标记为完成。'
    data.value = await getM6TeacherInterventions(selectedCourseId.value)
  } catch (value) {
    error.value = errorMessage(value)
  } finally {
    busy.value = ''
  }
}

onMounted(load)
</script>

<template>
  <main class="intervention-page" data-testid="teacher-interventions-page">
    <header class="page-heading">
      <div>
        <h1>干预任务</h1>
        <p>依据学生的真实学习证据安排下一步任务。发布只增加学习路径任务，不会直接改变掌握度。</p>
      </div>
      <button class="icon-button" type="button" title="刷新当前课程" aria-label="刷新干预任务" :disabled="loading" @click="load">
        <RefreshCw :size="18" :class="{ spin: loading }" />
      </button>
    </header>

    <section class="context-bar" aria-label="当前教学范围">
      <label>
        <span>当前课程</span>
        <select v-model="selectedCourseId" :disabled="loading || !courses.length" @change="changeCourse">
          <option v-for="course in courses" :key="course.id" :value="course.id">{{ course.title }}</option>
        </select>
      </label>
      <div class="context-summary">
        <span><strong>{{ students.length }}</strong> 名学生</span>
        <span><strong>{{ interventions.length }}</strong> 项干预</span>
        <span><strong>{{ pendingConfirmations }}</strong> 项待复核</span>
      </div>
    </section>

    <div v-if="error" class="feedback error" role="alert"><AlertCircle :size="18" />{{ error }}</div>
    <div v-if="notice" class="feedback notice" role="status"><CheckCircle2 :size="18" />{{ notice }}</div>

    <section v-if="loading" class="state-panel" aria-live="polite">
      <RefreshCw class="spin" :size="21" />
      <div><strong>正在核对授权课程与学生证据</strong><span>页面会保留当前课程和已完成结果。</span></div>
    </section>

    <section v-else-if="!courses.length" class="state-panel empty">
      <BookOpen :size="28" />
      <div><strong>当前账号还没有可管理课程</strong><span>请先在课程与资源中确认教师归属，再回到这里安排干预。</span></div>
    </section>

    <section v-else-if="!students.length" class="state-panel empty">
      <UserCheck :size="28" />
      <div><strong>{{ selectedCourse?.title }} 暂无在读学生</strong><span>学生加入课程并形成学习证据后，会出现在这里。</span></div>
    </section>

    <template v-else>
      <section class="evidence-workspace">
        <aside class="student-list" aria-label="课程学生">
          <div class="pane-heading">
            <div><h2>选择学生</h2><p>先看证据，再安排干预。</p></div>
            <span>{{ students.length }} 人</span>
          </div>
          <button
            v-for="student in students"
            :key="student.public_id"
            type="button"
            class="student-row"
            :class="{ active: selectedStudentId === student.public_id }"
            @click="selectStudent(student.public_id)"
          >
            <span class="avatar">{{ (student.display_name || '学').slice(-1) }}</span>
            <span class="student-copy">
              <strong>{{ student.display_name || '未命名学生' }}</strong>
              <small>{{ student.weakest_concept }} · {{ masteryLabel(student.mastery) }}</small>
            </span>
            <span v-if="interventions.some((item) => item.learner_public_id === student.public_id)" class="row-state"><Check :size="15" />已安排</span>
            <span v-else class="row-state muted">待判断</span>
          </button>
        </aside>

        <section class="student-detail" aria-live="polite">
          <div v-if="detailLoading" class="detail-loading"><RefreshCw class="spin" :size="20" />正在读取该学生的学习证据</div>
          <template v-else-if="detail && selectedStudent">
            <header class="detail-heading">
              <div><span>当前学生</span><h2>{{ selectedStudent.display_name }}</h2><p>{{ detail.profile?.evidenceMessage || '正在等待更多可信学习证据。' }}</p></div>
              <span class="evidence-state">{{ detail.profile?.evidenceState === 'sufficient' ? '证据充分' : '证据待补充' }}</span>
            </header>

            <section class="weak-points">
              <h3>需要优先关注</h3>
              <div v-if="detail.profile?.weakPoints?.length" class="weak-list">
                <article v-for="point in detail.profile.weakPoints.slice(0, 3)" :key="point.id">
                  <div><strong>{{ point.title }}</strong><span>{{ point.judgement || '根据当前学习事件形成的判断' }}</span></div>
                  <div class="point-evidence"><b>{{ masteryLabel(point.mastery) }}</b><small>{{ point.evidenceCount }} 条证据</small></div>
                </article>
              </div>
              <p v-else class="inline-empty">证据不足，暂不建议发布干预。</p>
            </section>

            <details class="agent-audit">
              <summary>
                <span><ShieldCheck :size="18" /><strong>查看 AI 建议的公开校验摘要</strong></span>
                <span>{{ detail.agentAudit?.items?.length || 0 }} 个步骤</span>
                <ChevronDown :size="18" />
              </summary>
              <div v-if="detail.agentAudit?.state === 'complete'" class="agent-list">
                <article v-for="(agent, index) in detail.agentAudit.items" :key="`${agent.role}-${index}`">
                  <header><strong>{{ agentRoleLabels[agent.role] || agent.role }}</strong><span>{{ agent.status === 'completed' ? '已完成' : '未完成' }}</span></header>
                  <p><b>候选：</b>{{ agent.candidateSummary || '未形成候选摘要' }}</p>
                  <p><b>分歧：</b>{{ agent.disagreement || '本次没有记录分歧' }}</p>
                  <p><b>校验：</b>{{ agent.validation || '未记录校验摘要' }}</p>
                  <p><b>修订：</b>{{ agent.revision || '本次没有记录修订' }}</p>
                  <p><b>决定：</b>{{ agent.decisionSummary || '未形成公开决定摘要' }}</p>
                </article>
              </div>
              <p v-else class="inline-empty">{{ detail.agentAudit?.message || '当前没有可公开的协作证据。' }}</p>
            </details>

            <footer class="intervention-action">
              <div>
                <strong>{{ selectedIntervention ? '该学生已有干预任务' : '将当前证据转成学习任务' }}</strong>
                <span>{{ selectedIntervention ? '等待学生提交证据，之后由教师确认完成。' : '任务进入学生路径；只有后续可信学习行为才能更新掌握度。' }}</span>
              </div>
              <span v-if="selectedIntervention" class="completed-mark"><Check :size="17" />{{ statusLabel(selectedIntervention.node_status) }}</span>
              <button v-else class="primary-button" type="button" :disabled="busy.startsWith('publish-') || !detail.profile?.weakPoints?.length" @click="publish">
                <ClipboardPlus :size="18" />{{ busy.startsWith('publish-') ? '正在发布' : '发布干预任务' }}
              </button>
            </footer>
          </template>
          <div v-else class="detail-loading">选择一名学生查看证据</div>
        </section>
      </section>

      <section class="intervention-list">
        <div class="section-heading">
          <div><h2>执行与复核</h2><p>学生完成任务并提交学习证据后，教师才能确认完成。</p></div>
          <span>{{ interventions.length }} 项</span>
        </div>
        <div class="table-head" aria-hidden="true"><span>学生</span><span>干预任务</span><span>路径状态</span><span>学习证据</span><span>下一步</span></div>
        <article v-for="item in interventions" :key="item.path_id" class="intervention-row">
          <strong>{{ item.learner_name }}</strong>
          <span>{{ item.title }}</span>
          <span class="status-label">{{ statusLabel(item.node_status) }}</span>
          <span>{{ item.learner_event_id ? '已提交' : '等待学生' }}</span>
          <button v-if="item.learner_event_id && !item.teacher_confirmed" class="secondary-button" type="button" :disabled="busy === `confirm-${item.path_id}`" @click="confirm(item)">
            <ShieldCheck :size="17" />{{ busy === `confirm-${item.path_id}` ? '正在确认' : '确认完成' }}
          </button>
          <span v-else-if="item.teacher_confirmed" class="completed-mark"><Check :size="17" />已复核</span>
          <span v-else class="muted">证据到达后可复核</span>
        </article>
        <div v-if="!interventions.length" class="list-empty">当前课程还没有干预任务。先选择学生并核对证据。</div>
      </section>
    </template>
  </main>
</template>

<style scoped>
.intervention-page{width:100%;max-width:1220px;margin:0 auto;padding:0 0 40px;color:var(--color-text);font-family:var(--font-sans);font-size:15px;line-height:var(--line-height-body)}
.page-heading{display:flex;align-items:flex-end;justify-content:space-between;gap:24px;padding:18px 0 24px;border-bottom:1px solid var(--color-border-strong)}
.page-heading h1{margin:0 0 8px;font-size:28px;line-height:1.3}.page-heading p{max-width:720px;margin:0;color:var(--color-text-muted);font-size:15px}
.icon-button{display:grid;width:42px;height:42px;flex:0 0 42px;place-items:center;border:1px solid var(--color-border-strong);border-radius:6px;background:var(--color-surface);color:var(--color-accent);cursor:pointer}.icon-button:hover:not(:disabled){background:var(--color-surface-subtle)}.icon-button:disabled{color:var(--color-text-muted);cursor:not-allowed}
.context-bar{display:flex;min-height:76px;align-items:center;justify-content:space-between;gap:24px;border-bottom:1px solid var(--color-border)}.context-bar label{display:flex;align-items:center;gap:12px;font-size:14px;font-weight:700}.context-bar select{min-width:280px;padding:8px 36px 8px 11px}.context-summary{display:flex;align-items:center;gap:22px;color:var(--color-text-secondary);font-size:14px}.context-summary span{display:flex;align-items:baseline;gap:5px}.context-summary strong{color:var(--color-text);font-size:18px}
.feedback{display:flex;align-items:center;gap:9px;margin-top:14px;padding:12px 14px;border:1px solid var(--color-border);border-radius:6px;background:var(--color-surface);font-size:14px}.feedback.error{border-color:#d9a6a6;background:var(--color-danger-soft);color:var(--color-danger)}.feedback.notice{background:var(--color-success-soft);color:var(--color-text)}
.state-panel{display:flex;min-height:180px;align-items:center;justify-content:center;gap:14px;border-bottom:1px solid var(--color-border);color:var(--color-text-secondary)}.state-panel>div{display:grid;gap:3px}.state-panel strong{color:var(--color-text);font-size:17px}.state-panel span{font-size:14px}.state-panel.empty{min-height:300px}
.evidence-workspace{display:grid;grid-template-columns:340px minmax(0,1fr);min-height:590px;margin-top:24px;border:1px solid var(--color-border-strong);border-radius:8px;overflow:hidden;background:var(--color-surface)}.student-list{border-right:1px solid var(--color-border);background:var(--color-surface-subtle)}
.pane-heading,.section-heading{display:flex;align-items:flex-end;justify-content:space-between;gap:16px;padding:20px}.pane-heading h2,.section-heading h2{margin:0;font-size:19px}.pane-heading p,.section-heading p{margin:4px 0 0;color:var(--color-text-muted);font-size:14px}.pane-heading>span,.section-heading>span{color:var(--color-text-secondary);font-size:14px}
.student-row{display:grid;width:100%;grid-template-columns:40px minmax(0,1fr) auto;align-items:center;gap:11px;min-height:76px;padding:12px 16px;border:0;border-top:1px solid var(--color-border);background:transparent;color:var(--color-text);text-align:left;cursor:pointer}.student-row:hover,.student-row.active{background:var(--color-surface)}.student-row.active{box-shadow:inset 2px 0 0 var(--color-accent)}
.avatar{display:grid;width:38px;height:38px;place-items:center;border-radius:50%;background:var(--color-accent);color:#fff;font-size:14px;font-weight:700}.student-copy{display:grid;min-width:0;gap:2px}.student-copy strong{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:15px}.student-copy small{overflow:hidden;color:var(--color-text-muted);font-size:14px;text-overflow:ellipsis;white-space:nowrap}.row-state,.completed-mark{display:inline-flex;align-items:center;gap:5px;color:var(--color-accent);font-size:14px;font-weight:700}.muted{color:var(--color-text-muted);font-size:14px;font-weight:400}
.student-detail{min-width:0;padding:24px}.detail-loading{display:flex;min-height:340px;align-items:center;justify-content:center;gap:10px;color:var(--color-text-muted);font-size:14px}.detail-heading{display:flex;align-items:flex-start;justify-content:space-between;gap:18px;padding-bottom:20px;border-bottom:1px solid var(--color-border)}.detail-heading>div>span{color:var(--color-text-secondary);font-size:14px;font-weight:700}.detail-heading h2{margin:4px 0 6px;font-size:23px}.detail-heading p{max-width:620px;margin:0;color:var(--color-text-muted);font-size:14px}
.evidence-state,.status-label{display:inline-flex;min-height:30px;align-items:center;border:1px solid var(--color-border-strong);border-radius:999px;background:var(--color-surface-subtle);padding:4px 9px;color:var(--color-text-secondary);font-size:14px;white-space:nowrap}.weak-points{padding:20px 0}.weak-points h3{margin:0 0 10px;font-size:17px}.weak-list{display:grid}.weak-list article{display:grid;grid-template-columns:minmax(0,1fr) auto;align-items:center;gap:18px;min-height:70px;border-top:1px solid var(--color-border);padding:11px 2px}.weak-list article>div:first-child{display:grid;gap:3px}.weak-list strong{font-size:15px}.weak-list span,.point-evidence small{color:var(--color-text-muted);font-size:14px}.point-evidence{display:grid;text-align:right}.point-evidence b{font-size:17px}
.agent-audit{border-top:1px solid var(--color-border);border-bottom:1px solid var(--color-border)}.agent-audit summary{display:grid;grid-template-columns:minmax(0,1fr) auto 18px;align-items:center;gap:10px;padding:14px 2px;cursor:pointer;list-style:none}.agent-audit summary::-webkit-details-marker{display:none}.agent-audit summary>span:first-child{display:flex;align-items:center;gap:8px}.agent-audit summary>span:nth-child(2){color:var(--color-text-muted);font-size:14px}.agent-audit[open] summary>svg{transform:rotate(180deg)}.agent-list{display:grid;gap:0;padding-bottom:12px}.agent-list article{border-top:1px solid var(--color-border);padding:14px 2px}.agent-list header{display:flex;justify-content:space-between;gap:12px}.agent-list header span{color:var(--color-text-muted);font-size:14px}.agent-list p{margin:7px 0 0;color:var(--color-text-secondary);font-size:14px}.agent-list b{color:var(--color-text)}.inline-empty{margin:0;padding:14px 2px;color:var(--color-text-muted);font-size:14px}
.intervention-action{display:flex;align-items:center;justify-content:space-between;gap:24px;padding-top:20px}.intervention-action>div{display:grid;gap:3px}.intervention-action strong{font-size:16px}.intervention-action span{color:var(--color-text-muted);font-size:14px}.primary-button,.secondary-button{display:inline-flex;min-height:42px;align-items:center;justify-content:center;gap:8px;border-radius:6px;padding:9px 15px;font-size:14px;font-weight:700;cursor:pointer}.primary-button{border:1px solid var(--color-accent);background:var(--color-accent);color:#fff}.primary-button:hover:not(:disabled){background:#06141b}.secondary-button{border:1px solid var(--color-border-strong);background:var(--color-surface);color:var(--color-accent)}.secondary-button:hover:not(:disabled){background:var(--color-surface-subtle)}.primary-button:disabled,.secondary-button:disabled{color:var(--color-text-muted);border-color:var(--color-border);background:var(--color-surface-muted);cursor:not-allowed}
.intervention-list{margin-top:28px;border-top:1px solid var(--color-border-strong);border-bottom:1px solid var(--color-border-strong);background:var(--color-surface)}.table-head,.intervention-row{display:grid;grid-template-columns:minmax(110px,.8fr) minmax(220px,1.6fr) minmax(100px,.7fr) minmax(110px,.7fr) minmax(150px,1fr);align-items:center;gap:14px;padding:12px 20px}.table-head{border-top:1px solid var(--color-border);background:var(--color-surface-subtle);color:var(--color-text-secondary);font-size:14px;font-weight:700}.intervention-row{min-height:70px;border-top:1px solid var(--color-border);font-size:14px}.intervention-row>span:nth-child(2){color:var(--color-text-secondary)}.list-empty{min-height:120px;display:grid;place-items:center;border-top:1px solid var(--color-border);color:var(--color-text-muted);font-size:14px}
.spin{animation:spin .8s linear infinite}@keyframes spin{to{transform:rotate(360deg)}}
</style>
