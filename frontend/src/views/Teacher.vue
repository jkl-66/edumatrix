<script setup>
import { ref, onMounted, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { getTeacherDashboard } from '../api'
import {
  BarChart3, Users, AlertTriangle, TrendingUp, Target, Search,
  GraduationCap, ChevronRight, Clock, Sparkles, User, BookOpen,
  AlertCircle, CheckCircle, ArrowRight, Calendar,
} from '@lucide/vue'
import DashboardWidget from '../components/ui/DashboardWidget.vue'
import UiCard from '../components/ui/UiCard.vue'

const route = useRoute()
const router = useRouter()
const data = ref(null)
const loading = ref(true)
const error = ref('')
const searchQuery = ref('')
const selectedMajor = ref('')
const expandedStudent = ref(null)

const activeTab = computed(() => {
  const pathMap = {
    '/teacher': 'overview',
    '/teacher/overview': 'overview',
    '/teacher/students': 'students',
    '/teacher/reviews': 'reviews',
    '/teacher/reports': 'reports',
  }
  return pathMap[route.path] || 'overview'
})

const students = computed(() => data.value?.profiles || [])
const classSummary = computed(() => data.value?.class_summary || {})
const alerts = computed(() => data.value?.alert_students || [])
const conceptRanking = computed(() => data.value?.concept_class_ranking || [])
const recentActivities = computed(() => data.value?.recent_activities || [])
const interventions = computed(() => data.value?.interventions || [])

const filteredStudents = computed(() => {
  let list = students.value
  if (searchQuery.value.trim()) {
    const q = searchQuery.value.trim().toLowerCase()
    list = list.filter(p => (p.student_id || '').toLowerCase().includes(q) || (p.major || '').toLowerCase().includes(q))
  }
  if (selectedMajor.value) list = list.filter(p => (p.major || '未设置') === selectedMajor.value)
  return list
})
const majorOptions = computed(() => [...new Set(students.value.map(p => p.major || '未设置'))].sort())

function calcAvg(p) { const m = p.concept_mastery; if (!m || !Object.keys(m).length) return 0; const v = Object.values(m); return Math.round(v.reduce((a, b) => a + b, 0) / v.length * 100) }
function pct(v) { return Math.round((v || 0) * 100) }
function scoreColor(v) { return v >= 0.6 ? 'text-emerald-600' : v >= 0.3 ? 'text-amber-600' : 'text-red-600' }
function barColor(v) { return v >= 0.6 ? 'bg-emerald-500' : v >= 0.3 ? 'bg-amber-500' : 'bg-red-500' }

function viewStudent(sid) { router.push(`/student-analysis?student_id=${sid}`) }
function viewPath(sid) { router.push(`/learning-path?student_id=${sid}`) }
function setTab(tab) {
  const pathMap = { overview: '/teacher', students: '/teacher/students', reviews: '/teacher/reviews', reports: '/teacher/reports' }
  router.push(pathMap[tab] || '/teacher')
}

onMounted(async () => {
  try { data.value = await getTeacherDashboard() } catch (e) { error.value = e.message || '加载失败' }
  finally { loading.value = false }
})
</script>

<template>
  <div v-if="loading" class="flex items-center justify-center h-64"><div class="animate-spin w-5 h-5 border-2 border-purple-500 border-t-transparent rounded-full" /></div>
  <div v-else-if="error" class="text-center py-12 text-red-500 text-sm">{{ error }}</div>
  <div v-else class="teacher-page max-w-[1380px] mx-auto">
    <UiCard class="teacher-intro" tone="dark">
      <div>
        <span class="teacher-intro__eyebrow"><Sparkles :size="13" /> Teaching intelligence</span>
        <h1>把每一次教学判断，建立在更清晰的学习证据上。</h1>
        <p>聚合班级掌握度、活跃趋势和风险预测，优先发现真正需要干预的学生与知识点。</p>
      </div>
      <div class="teacher-intro__pulse"><span />{{ classSummary.alert_count || 0 }} 个关注信号</div>
    </UiCard>

    <nav class="teacher-tabs" aria-label="教师工作台导航">
      <button :class="{ active: activeTab==='overview' }" @click="setTab('overview')"><BarChart3 :size="14" />教学总览</button>
      <button :class="{ active: activeTab==='students' }" @click="setTab('students')"><Users :size="14" />学生画像</button>
      <button :class="{ active: activeTab==='reviews' }" @click="setTab('reviews')"><Calendar :size="14" />复习监控</button>
      <button :class="{ active: activeTab==='reports' }" @click="setTab('reports')"><BookOpen :size="14" />学习报告</button>
    </nav>

    <!-- TAB: 教学看板 -->
    <div v-if="activeTab==='overview'" class="space-y-5">
      <div class="teacher-metrics">
        <DashboardWidget label="班级学生" :value="classSummary.total_students || 0" detail="当前课程空间" tone="sage"><template #icon><Users :size="16" /></template><template #signal>班级规模</template></DashboardWidget>
        <DashboardWidget label="平均掌握度" :value="`${pct(classSummary.avg_mastery)}%`" detail="全班知识点综合均值" tone="violet"><template #icon><TrendingUp :size="16" /></template><template #signal>学习质量</template></DashboardWidget>
        <DashboardWidget label="需要关注" :value="classSummary.alert_count || 0" detail="由风险模型实时识别" tone="sand"><template #icon><AlertTriangle :size="16" /></template><template #signal>待干预</template></DashboardWidget>
        <DashboardWidget label="低掌握学生" :value="classSummary.low_mastery_count || 0" detail="低于课程掌握阈值" tone="rose"><template #icon><Target :size="16" /></template><template #signal>风险预测</template></DashboardWidget>
      </div>
      <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div class="bg-white rounded-2xl border border-gray-100 shadow-sm p-4">
          <h2 class="text-xs font-semibold text-gray-800 mb-3 flex items-center gap-2"><Target :size="14" class="text-rose-500"/> 全班薄弱概念 TOP5</h2>
          <div v-if="conceptRanking.length" class="space-y-2">
            <div v-for="(c, i) in conceptRanking.slice(0, 5)" :key="c.concept" class="flex items-center gap-2 text-[11px]">
              <span class="w-5 h-5 rounded-full flex items-center justify-center text-[9px] font-bold shrink-0" :class="i<3?'bg-red-100 text-red-700':'bg-gray-100 text-gray-600'">{{ i+1 }}</span>
              <span class="text-gray-700 flex-1 truncate">{{ c.concept }}</span>
              <div class="w-20 h-1.5 bg-gray-100 rounded-full overflow-hidden"><div class="h-full rounded-full" :class="barColor(c.avg_mastery)" :style="{width:(c.avg_mastery*100)+'%'}"/></div>
              <span class="font-mono" :class="scoreColor(c.avg_mastery)">{{ pct(c.avg_mastery) }}%</span>
              <span class="text-[9px] text-gray-400">{{ c.student_count }}人</span>
            </div>
          </div>
          <div v-else class="text-xs text-gray-400 py-4 text-center">暂无数据</div>
        </div>
        <div class="bg-white rounded-2xl border border-gray-100 shadow-sm p-4">
          <h2 class="text-xs font-semibold text-gray-800 mb-3 flex items-center gap-2"><Clock :size="14" class="text-blue-500"/> 最近活跃学生</h2>
          <div class="space-y-1.5">
            <div v-for="act in recentActivities.slice(0, 6)" :key="act.student_id" class="flex items-center gap-2 text-[10px] text-gray-600 py-1">
              <div class="w-1.5 h-1.5 rounded-full" :class="act.last_active ? 'bg-emerald-400' : 'bg-gray-300'"/>
              <span class="font-medium text-gray-700 w-24 truncate">{{ act.student_id }}</span>
              <span class="text-gray-400">{{ act.last_active ? act.last_active.replace('T',' ') : '暂无活动' }}</span>
            </div>
            <div v-if="!recentActivities.length" class="text-xs text-gray-400 py-4 text-center">暂无数据</div>
          </div>
        </div>
      </div>
      <div v-if="alerts.length" class="bg-amber-50 rounded-2xl border border-amber-200 p-4">
        <h2 class="text-xs font-semibold text-amber-800 mb-2 flex items-center gap-2"><AlertCircle :size="14" /> 待处理队列</h2>
        <div class="space-y-1.5">
          <div v-for="a in alerts.slice(0, 4)" :key="a.student_id" class="flex items-center gap-2 text-[11px]">
            <span class="text-amber-600 font-medium w-24 truncate">{{ a.student_id }}</span>
            <span class="text-amber-700">{{ a.reasons?.join('、') }}</span>
            <button class="ml-auto text-[10px] text-purple-600 hover:text-purple-800 font-medium" @click="viewStudent(a.student_id)">查看</button>
          </div>
        </div>
      </div>
    </div>

    <!-- TAB: 学生管理 -->
    <div v-if="activeTab==='students'" class="space-y-4">
      <div class="flex gap-3">
        <div class="relative flex-1"><Search :size="13" class="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400"/><input v-model="searchQuery" class="w-full pl-9 pr-3 py-2 text-xs rounded-xl border border-gray-200 bg-white focus:border-purple-300 outline-none" placeholder="搜索学生ID或专业..."/></div>
        <select v-model="selectedMajor" class="px-3 py-2 text-xs rounded-xl border border-gray-200 bg-white focus:border-purple-300 outline-none appearance-none"><option value="">全部专业</option><option v-for="m in majorOptions" :key="m" :value="m">{{ m }}</option></select>
      </div>
      <div class="bg-white rounded-2xl border border-gray-100 shadow-sm overflow-hidden">
        <div v-for="p in filteredStudents" :key="p.student_id" class="border-b border-gray-50 last:border-0">
          <div class="flex items-center gap-3 px-4 py-3 hover:bg-gray-50 transition-all cursor-pointer" @click="expandedStudent = expandedStudent === p.student_id ? null : p.student_id">
            <div class="w-8 h-8 rounded-full bg-gradient-to-br from-purple-500 to-indigo-600 flex items-center justify-center text-white text-[10px] font-bold shrink-0">{{ (p.student_id||'?').slice(-2).toUpperCase() }}</div>
            <div class="w-28"><p class="text-xs font-semibold text-gray-800 truncate">{{ p.student_id }}</p><p class="text-[9px] text-gray-400 truncate">{{ p.major || '' }}</p></div>
            <div class="flex-1"><div class="h-1.5 bg-gray-100 rounded-full overflow-hidden"><div class="h-full rounded-full" :class="barColor(calcAvg(p)/100)" :style="{width:calcAvg(p)+'%'}"/></div></div>
            <span class="text-[10px] font-mono w-8 text-right" :class="scoreColor(calcAvg(p)/100)">{{ calcAvg(p) }}%</span>
            <div class="flex gap-1">
              <button class="px-2 py-1 text-[9px] font-semibold rounded-lg bg-purple-50 text-purple-700 hover:bg-purple-100 transition-all" @click.stop="viewStudent(p.student_id)">📋 画像</button>
              <button class="px-2 py-1 text-[9px] font-semibold rounded-lg bg-emerald-50 text-emerald-700 hover:bg-emerald-100 transition-all" @click.stop="viewPath(p.student_id)">🛤️ 路径</button>
            </div>
          </div>
          <div v-if="expandedStudent === p.student_id" class="px-4 pb-3 bg-gray-50/50 space-y-1.5 border-t border-gray-50">
            <p class="text-[9px] font-semibold text-gray-600 pt-2">概念掌握详情</p>
            <div v-for="(score, concept) in (p.concept_mastery || {})" :key="concept" class="flex items-center gap-2 text-[10px]">
              <span class="text-gray-600 w-20 truncate">{{ concept }}</span>
              <div class="flex-1 h-1 bg-gray-100 rounded-full overflow-hidden"><div class="h-full rounded-full" :class="barColor(score)" :style="{width:(score*100)+'%'}"/></div>
              <span class="font-mono w-8 text-right" :class="scoreColor(score)">{{ pct(score) }}%</span>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- TAB: 复习监控 -->
    <div v-if="activeTab==='reviews'" class="space-y-4">
      <div class="bg-white rounded-2xl border border-gray-100 shadow-sm p-4">
        <h2 class="text-xs font-semibold text-gray-800 mb-3 flex items-center gap-2"><Calendar :size="14" class="text-amber-500"/> 学生复习计划</h2>
        <p class="text-[10px] text-gray-400 mb-3">每位学生的待复习概念列表（基于遗忘曲线）</p>
        <div v-for="p in students" :key="p.student_id" class="flex items-center gap-3 py-2 border-b border-gray-50 last:border-0">
          <div class="w-7 h-7 rounded-full bg-gradient-to-br from-amber-400 to-orange-500 flex items-center justify-center text-white text-[9px] font-bold shrink-0">{{ (p.student_id||'?').slice(-2).toUpperCase() }}</div>
          <span class="text-xs font-medium text-gray-700 w-28 truncate">{{ p.student_id }}</span>
          <span class="text-[10px] text-gray-400 flex-1">薄弱点: {{ (p.weak_points||[]).slice(0,2).join('、') || '暂无' }}</span>
          <button class="px-2 py-1 text-[9px] font-semibold rounded-lg bg-amber-50 text-amber-700 hover:bg-amber-100 transition-all" @click="viewStudent(p.student_id)">查看复习计划</button>
        </div>
        <div v-if="!students.length" class="text-center py-6 text-xs text-gray-400">暂无数据</div>
      </div>
    </div>

    <!-- TAB: 学习报告 -->
    <div v-if="activeTab==='reports'" class="grid grid-cols-1 md:grid-cols-2 gap-4">
      <div class="bg-white rounded-2xl border border-gray-100 shadow-sm p-4">
        <h2 class="text-xs font-semibold text-gray-800 mb-3 flex items-center gap-2"><Target :size="14" class="text-rose-500"/> 薄弱概念排行</h2>
        <div v-if="conceptRanking.length" class="space-y-2">
          <div v-for="(c,i) in conceptRanking.slice(0,8)" :key="c.concept" class="flex items-center gap-2 text-[11px]">
            <span class="w-5 h-5 rounded-full flex items-center justify-center text-[9px] font-bold shrink-0" :class="i<3?'bg-red-100 text-red-700':'bg-gray-100 text-gray-600'">{{ i+1 }}</span>
            <span class="text-gray-700 flex-1 truncate">{{ c.concept }}</span>
            <div class="w-16 h-1.5 bg-gray-100 rounded-full overflow-hidden"><div class="h-full rounded-full" :class="barColor(c.avg_mastery)" :style="{width:(c.avg_mastery*100)+'%'}"/></div>
            <span class="font-mono" :class="scoreColor(c.avg_mastery)">{{ pct(c.avg_mastery) }}%</span>
            <span class="text-[9px] text-gray-400">{{ c.student_count }}人</span>
          </div>
        </div>
      </div>
      <div class="bg-white rounded-2xl border border-gray-100 shadow-sm p-4">
        <h2 class="text-xs font-semibold text-gray-800 mb-3 flex items-center gap-2"><Sparkles :size="14" class="text-amber-500"/> 干预建议</h2>
        <div v-if="interventions.length" class="space-y-1.5">
          <div v-for="iv in interventions.slice(0, 6)" :key="iv.name" class="flex items-center gap-2 text-[11px] px-3 py-2 rounded-lg bg-amber-50">
            <span class="text-amber-700 flex-1">{{ iv.name }}</span>
            <span class="text-amber-500 font-mono text-[10px] font-semibold">{{ iv.count }}人</span>
          </div>
        </div>
        <div v-else class="text-xs text-gray-400 py-4 text-center">暂无干预数据</div>
      </div>
    </div>

  </div>
</template>

<style scoped>
.teacher-page { padding-bottom: 32px; }
.teacher-intro {
  display: flex;
  min-height: 230px;
  align-items: flex-end;
  justify-content: space-between;
  gap: 30px;
  padding: clamp(26px, 4vw, 44px);
  overflow: hidden;
  background: radial-gradient(circle at 92% 8%, rgba(207,218,210,.16), transparent 34%), #28322c;
}
.teacher-intro__eyebrow { display: inline-flex; align-items: center; gap: 6px; color: #c8d4cb; font-size: 10px; font-weight: 700; letter-spacing: .1em; text-transform: uppercase; }
.teacher-intro h1 { max-width: none; margin: 16px 0 10px; color: #fafcf9; font-size: clamp(25px, 3.4vw, 42px); font-weight: 610; letter-spacing: -.055em; line-height: 1.12; white-space: nowrap; }
.teacher-intro p { max-width: 680px; margin: 0; color: rgba(237,243,238,.58); font-size: 12px; line-height: 1.7; }
.teacher-intro__pulse { display: flex; flex: 0 0 auto; align-items: center; gap: 8px; padding: 10px 13px; color: #d6ddd7; border: 1px solid rgba(255,255,255,.09); border-radius: 13px; background: rgba(255,255,255,.045); font-size: 10px; }
.teacher-intro__pulse span { width: 6px; height: 6px; border-radius: 50%; background: #c99378; box-shadow: 0 0 0 5px rgba(201,147,120,.12); }
.teacher-tabs { display: flex; gap: 5px; width: max-content; max-width: 100%; margin: 18px 0; padding: 5px; overflow-x: auto; border: 1px solid rgba(42,54,46,.07); border-radius: 16px; background: rgba(250,251,248,.72); }
.teacher-tabs button { display: inline-flex; align-items: center; gap: 7px; padding: 9px 13px; color: #7b847d; border: 0; border-radius: 11px; background: transparent; font-size: 10px; font-weight: 620; white-space: nowrap; cursor: pointer; transition: .18s ease; }
.teacher-tabs button:hover { color: #344038; background: #eef1ec; }
.teacher-tabs button.active { color: #f8faf7; background: #344039; box-shadow: 0 7px 16px rgba(52,64,57,.15); }
.teacher-metrics { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 14px; }
.teacher-page :deep(.bg-white.rounded-2xl), .teacher-page :deep(.bg-white.rounded-xl) { border-color: rgba(42,54,46,.075); background: rgba(253,254,251,.86); box-shadow: 0 12px 32px rgba(45,56,49,.05); }
.teacher-page :deep(input), .teacher-page :deep(select) { border-color: rgba(42,54,46,.1); background: rgba(253,254,251,.86); }
@media (max-width: 900px) { .teacher-metrics { grid-template-columns: repeat(2, minmax(0,1fr)); } .teacher-intro { align-items: flex-start; flex-direction: column; } }
@media (max-width: 560px) { .teacher-metrics { grid-template-columns: 1fr; } }
</style>
