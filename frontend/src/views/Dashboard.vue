<script setup>
import { ref, onMounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import { getStudentProfile, getLearningPath, getReviewPlans, getRecommendations, getNotes, regenerateComponent, getProfileAnalysis } from '../api'
import {
  Activity, Brain, ArrowRight, Sparkles, BookOpen, Target, TrendingUp,
  CheckCircle2, Clock, Calendar, GraduationCap, UserCheck, Play
} from '@lucide/vue'
import MasteryRadar from '../components/MasteryRadar.vue'
import VideoRenderPanel from '../components/VideoRenderPanel.vue'

const router = useRouter()
const props = defineProps({ studentId: String })

const profile = ref(null)
const learningPath = ref(null)
const reviews = ref([])
const recommendations = ref([])
const profileAnalysis = ref(null)
const loading = ref(true)

const showVideoPanel = ref(false)
const videoPanelUrl = ref('')

const studentNotes = ref([])
const activeResource = ref(null)
const activeResourceContent = ref('')
const isGenerating = ref(false)
const currentStudentId = ref(props.studentId || localStorage.getItem('edumatrix_student_id') || 'demo-student')

const pathwayLoading = ref({})

async function switchPathway(concept, pathwayCode) {
  pathwayLoading.value[concept] = true
  try {
    const data = await getRecommendations(currentStudentId.value, concept, pathwayCode)
    if (data && data.length) {
      const updatedRec = data[0]
      const idx = recommendations.value.findIndex(r => r.concept === concept)
      if (idx !== -1) {
        recommendations.value[idx] = updatedRec
      }
    }
  } catch (err) {
    console.error('Failed to switch pathway:', err)
  } finally {
    pathwayLoading.value[concept] = false
  }
}

const avgMastery = computed(() => {
  const m = profile.value?.concept_mastery
  if (!m || !Object.keys(m).length) return 0
  const v = Object.values(m)
  return Math.round(v.reduce((a, b) => a + b, 0) / v.length * 100)
})

const weakConcepts = computed(() => {
  const m = profile.value?.concept_mastery
  if (!m) return []
  return Object.entries(m).filter(([, v]) => v < 0.4).sort(([, a], [, b]) => a - b).slice(0, 5)
})

const conceptMastery = computed(() => {
  const raw = profile.value?.concept_mastery || {}
  return Object.entries(raw).map(([name, score]) => ({ name, mastery: score }))
})

const inProgress = computed(() => learningPath.value?.progress_summary?.in_progress || 0)
const mastered = computed(() => learningPath.value?.progress_summary?.mastered || 0)
const locked = computed(() => learningPath.value?.progress_summary?.locked || 0)
const nextUp = computed(() => (learningPath.value?.next_steps || []).slice(0, 3))

const totalConcepts = computed(() => learningPath.value?.progress_summary?.total_concepts || 0)

function goLearn(concept) {
  router.push({ path: '/learn', query: { q: concept } })
}

function goPath() { router.push('/learning-path') }
// Go analysis properly navigates
function goAnalysis() { router.push('/student-analysis') }
function goReview() { router.push('/review') }

function goNotes(concept) {
  router.push({ path: '/notes', query: { search: concept } })
}

function playVideo(url) {
  videoPanelUrl.value = url
  showVideoPanel.value = true
}

function getDimensionIcon(key) {
  if (key === 'lecture') return BookOpen
  if (key === 'mindmap') return Brain
  if (key === 'code') return Activity
  if (key === 'quiz') return Target
  if (key === 'video') return Play
  return BookOpen
}

function getDimensionColorClass(key) {
  if (key === 'lecture') return 'text-blue-500'
  if (key === 'mindmap') return 'text-purple-500'
  if (key === 'code') return 'text-emerald-500'
  if (key === 'quiz') return 'text-amber-500'
  if (key === 'video') return 'text-rose-500'
  return 'text-indigo-500'
}

function getSortedResources(resourcesObj) {
  if (!resourcesObj) return []
  return Object.entries(resourcesObj).map(([key, res]) => ({
    key,
    ...res
  })).sort((a, b) => (b.priority || 0) - (a.priority || 0))
}

function openResourceViewer(concept, key, res) {
  activeResource.value = { concept, key, res }
  activeResourceContent.value = ''
  
  if (res.status === 'generated' && res.note_id) {
    const found = studentNotes.value.find(n => n.id === res.note_id)
    if (found) {
      activeResourceContent.value = found.content
    } else {
      activeResourceContent.value = '未能在本地缓存中查找到该笔记，可能已被删除。'
    }
  }
}

function closeResourceViewer() {
  activeResource.value = null
  activeResourceContent.value = ''
  isGenerating.value = false
}

async function generateResource() {
  if (!activeResource.value) return
  isGenerating.value = true
  
  const { concept, key, res } = activeResource.value
  try {
    const data = await regenerateComponent(currentStudentId.value, res.role, res.resource_type, concept, res.overview)
    if (data && data.status === 'success') {
      const rec = recommendations.value.find(r => r.concept === concept)
      if (rec && rec.resources[key]) {
        rec.resources[key].status = 'generated'
        rec.resources[key].note_id = data.note_id
      }
      
      const noteIdx = studentNotes.value.findIndex(n => n.id === data.note_id)
      const newNoteObj = {
        id: data.note_id,
        source: 'adaptive_hub',
        content: data.content,
        tags: [res.resource_type],
        concepts: [concept],
        created_at: new Date().toISOString()
      }
      if (noteIdx !== -1) {
        studentNotes.value[noteIdx] = newNoteObj
      } else {
        studentNotes.value.push(newNoteObj)
      }
      
      activeResourceContent.value = data.content
      activeResource.value.res.status = 'generated'
      activeResource.value.res.note_id = data.note_id
    }
  } catch (err) {
    console.error('Failed to generate component:', err)
    alert('智能体生成失败，请重试！')
  } finally {
    isGenerating.value = false
  }
}

function openInWorkspace() {
  if (!activeResource.value) return
  const { concept, key, res } = activeResource.value
  
  closeResourceViewer()
  
  if (key === 'lecture' || key === 'mindmap') {
    router.push({ path: '/notes', query: { search: concept } })
  }
  else if (key === 'code') {
    router.push({ path: '/learn', query: { q: concept } })
  }
  else if (key === 'video') {
    const url = `/api/v1/video/stream?student_id=${currentStudentId.value}`
    playVideo(url)
  }
  else if (key === 'quiz') {
    router.push({ path: '/learn', query: { quiz: concept } })
  }
}

onMounted(async () => {
  try {
    const sid = currentStudentId.value
    const [p, lp, rv, recs, notesData, analysisData] = await Promise.all([
      getStudentProfile(sid),
      getLearningPath(sid).catch(() => null),
      getReviewPlans(sid).catch(() => []),
      getRecommendations(sid).catch(() => []),
      getNotes(sid).catch(() => ({ notes: [] })),
      getProfileAnalysis(sid).catch(() => null)
    ])
    profile.value = p
    learningPath.value = lp
    reviews.value = Array.isArray(rv) ? rv : (rv?.plans || rv?.due_reviews || [])
    recommendations.value = recs || []
    studentNotes.value = notesData?.notes || []
    profileAnalysis.value = analysisData
  } catch (e) {
    console.error('Dashboard load error:', e)
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div v-if="loading" class="flex items-center justify-center h-64">
    <div class="pulse-dot" /><span class="ml-3 text-gray-400 text-sm">加载中...</span>
  </div>
  <div v-else class="space-y-5 max-w-5xl mx-auto">

    <!-- 学习进度概览 -->
    <div class="grid grid-cols-1 md:grid-cols-4 gap-3">
      <div class="bg-white rounded-xl border border-gray-100 shadow-sm p-4">
        <div class="flex items-center justify-between mb-1">
          <p class="text-[10px] text-gray-500 font-medium">平均掌握度</p>
          <TrendingUp :size="14" class="text-emerald-500" />
        </div>
        <p class="text-2xl font-bold mt-0.5" :class="avgMastery >= 60 ? 'text-emerald-600' : avgMastery >= 30 ? 'text-amber-600' : 'text-red-600'">{{ avgMastery }}%</p>
      </div>
      <div class="bg-white rounded-xl border border-gray-100 shadow-sm p-4">
        <div class="flex items-center justify-between mb-1">
          <p class="text-[10px] text-gray-500 font-medium">已完成</p>
          <CheckCircle2 :size="14" class="text-emerald-500" />
        </div>
        <p class="text-2xl font-bold text-emerald-600 mt-0.5">{{ mastered }}/{{ totalConcepts }}</p>
      </div>
      <div class="bg-white rounded-xl border border-gray-100 shadow-sm p-4">
        <div class="flex items-center justify-between mb-1">
          <p class="text-[10px] text-gray-500 font-medium">进行中</p>
          <Activity :size="14" class="text-blue-500" />
        </div>
        <p class="text-2xl font-bold text-blue-600 mt-0.5">{{ inProgress }}</p>
      </div>
      <div class="bg-white rounded-xl border border-gray-100 shadow-sm p-4">
        <div class="flex items-center justify-between mb-1">
          <p class="text-[10px] text-gray-500 font-medium">薄弱概念</p>
          <Target :size="14" class="text-rose-500" />
        </div>
        <p class="text-2xl font-bold text-rose-600 mt-0.5">{{ weakConcepts.length }}</p>
      </div>
    </div>

    <!-- 🎓 课程全局学情诊断与自适应评价 -->
    <div v-if="profileAnalysis && profile" class="bg-gradient-to-br from-indigo-50/70 via-white/80 to-purple-50/50 rounded-2xl border border-indigo-100/50 p-5 shadow-sm space-y-4">
      <div class="flex items-center justify-between border-b border-indigo-100/60 pb-3 flex-wrap gap-2">
        <div class="flex items-center gap-2">
          <GraduationCap :size="18" class="text-indigo-600 animate-pulse" />
          <h2 class="text-xs font-bold text-slate-800">课程全局学情诊断与自适应评价</h2>
        </div>
        <div class="flex items-center gap-2 text-[10px] text-slate-500 font-medium">
          <span>📚 目标课程: <strong class="text-indigo-700 font-semibold">{{ profile?.target_course || '机器学习导论' }}</strong></span>
          <span>🎓 专业方向: <strong class="text-indigo-700 font-semibold">{{ profile?.major || '自适应' }}</strong></span>
        </div>
      </div>

      <div class="grid grid-cols-1 md:grid-cols-3 gap-5">
        <!-- 左侧及中间：全局学情诊断报告 (Dashboard Analysis) -->
        <div class="md:col-span-2 bg-slate-50/60 border border-slate-100 rounded-xl p-4 relative overflow-hidden flex flex-col justify-between">
          <Sparkles class="absolute right-3 top-3 text-slate-200/40 w-12 h-12 pointer-events-none" />
          <div class="space-y-2">
            <h3 class="text-xs font-bold text-slate-800 flex items-center gap-1">
              📊 全局学情诊断报告
            </h3>
            <div class="text-[11px] text-slate-700 leading-relaxed whitespace-pre-wrap font-medium">
              {{ profileAnalysis.dashboard_report || '正在加载中...' }}
            </div>
          </div>
        </div>

        <!-- 右侧：全局心智负荷与偏好评价 -->
        <div class="bg-white/90 border border-slate-100 rounded-xl p-4 flex flex-col justify-between space-y-3">
          <div class="space-y-3">
            <h3 class="text-xs font-bold text-slate-800 flex items-center gap-1">
              🧠 脑力心智负荷与风格评价
            </h3>
            
            <div class="space-y-2.5 text-[10px] text-slate-600">
              <div class="flex items-center justify-between">
                <span class="font-medium">认知负荷:</span>
                <span class="font-bold" :class="profile.cognitive_load > 0.6 ? 'text-amber-600' : 'text-emerald-600'">
                  {{ Math.round(profile.cognitive_load * 100) }}%
                </span>
              </div>
              <div class="w-full h-1.5 bg-slate-100 rounded-full overflow-hidden">
                <div class="h-full rounded-full" 
                  :class="profile.cognitive_load > 0.6 ? 'bg-amber-500' : 'bg-emerald-500'"
                  :style="{ width: (profile.cognitive_load * 100) + '%' }" />
              </div>

              <div class="flex items-center justify-between">
                <span class="font-medium">情绪避障/挫败感:</span>
                <span class="font-bold" :class="profile.frustration_index > 0.4 ? 'text-rose-600' : 'text-emerald-600'">
                  {{ Math.round(profile.frustration_index * 100) }}%
                </span>
              </div>
              <div class="w-full h-1.5 bg-slate-100 rounded-full overflow-hidden">
                <div class="h-full rounded-full" 
                  :class="profile.frustration_index > 0.4 ? 'bg-rose-500' : 'bg-emerald-500'"
                  :style="{ width: (profile.frustration_index * 100) + '%' }" />
              </div>
              
              <div class="pt-2 border-t border-slate-100 space-y-1">
                <div class="flex justify-between">
                  <span class="text-slate-500">学习风格:</span>
                  <span class="font-bold text-indigo-600">{{ profile.cognitive_style || '自适应' }}</span>
                </div>
                <div class="flex justify-between">
                  <span class="text-slate-500">学习动机:</span>
                  <span class="font-bold text-indigo-600">{{ profile.motivation_type || '未诊断' }}</span>
                </div>
              </div>
            </div>
          </div>
          
          <button class="w-full py-2 text-center text-xs font-bold text-indigo-600 bg-indigo-50/50 hover:bg-indigo-50 border border-indigo-100/50 rounded-lg transition-all"
            @click="router.push({ path: '/profile', query: { student_id: currentStudentId } })">
            查看数字孪生详细分析 →
          </button>
        </div>
      </div>
    </div>

    <!-- 下一步学习推荐 -->
    <div v-if="nextUp.length" class="bg-blue-50 rounded-2xl border border-blue-100 p-4">
      <h2 class="text-sm font-semibold text-blue-800 mb-2 flex items-center gap-2">
        <Sparkles :size="15" /> 继续学习
      </h2>
      <div class="flex flex-wrap gap-2">
        <button v-for="n in nextUp" :key="n.concept"
          class="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-lg bg-white text-blue-700 border border-blue-200 hover:bg-blue-100 transition-all"
          @click="goLearn(n.concept)">
          {{ n.concept }} <ArrowRight :size="11" />
        </button>
      </div>
    </div>

    <!-- 智能自适应资源推送 (5维矩阵) -->
    <div v-if="recommendations.length" class="space-y-5">
      <h2 class="text-sm font-bold text-gray-800 flex items-center gap-2">
        <Sparkles :size="15" class="text-indigo-500" />
        <span>智教自适应资源推送 (5维矩阵)</span>
        <span class="px-2 py-0.5 text-[9px] font-semibold bg-indigo-50 text-indigo-600 rounded-full border border-indigo-100 animate-pulse">AI Agent 智能体推荐底座</span>
      </h2>

      <div class="space-y-5">
        <!-- Iterate over recommended concepts -->
        <div v-for="conceptRec in recommendations" :key="conceptRec.concept"
          class="bg-white rounded-2xl border border-slate-100 shadow-sm p-5 space-y-4 relative overflow-hidden">
          
          <!-- Concept Header -->
          <div class="flex flex-col md:flex-row md:items-center justify-between gap-3 pb-3 border-b border-slate-100">
            <div class="flex items-center gap-2 flex-wrap">
              <span class="px-2.5 py-0.5 text-xs font-bold rounded-lg border"
                :class="{
                  'bg-rose-50 text-rose-600 border-rose-100': conceptRec.badge === '🔥 薄弱强化',
                  'bg-purple-50 text-purple-600 border-purple-100': conceptRec.badge === '💡 探索进阶'
                }">
                {{ conceptRec.badge }}
              </span>
              <h3 class="text-sm font-bold text-gray-800">
                知识强化目标: <span class="text-indigo-600 text-sm font-extrabold ml-1">{{ conceptRec.concept }}</span>
              </h3>
              <span class="text-[10px] font-semibold px-2 py-0.5 bg-slate-100 text-slate-600 rounded-full">
                当前掌握度: {{ Math.round(conceptRec.mastery * 100) }}%
              </span>
            </div>
            <p class="text-[10px] text-slate-400 font-medium leading-relaxed max-w-md">
              {{ conceptRec.reason }}
            </p>
          </div>

          <!-- Tactical Pathway Switcher -->
          <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-3 p-3 bg-slate-50/60 rounded-xl border border-slate-100/80">
            <div class="flex items-center gap-2">
              <span class="text-xs font-bold text-slate-700">战术编译路线:</span>
              <span class="inline-flex items-center gap-1 px-2 py-0.5 text-[10px] font-bold rounded-md border"
                :class="{
                  'bg-blue-50 text-blue-700 border-blue-100': conceptRec.pathway_meta.code === 'ICE_BREAKER',
                  'bg-emerald-50 text-emerald-700 border-emerald-100': conceptRec.pathway_meta.code === 'PRACTITIONER',
                  'bg-purple-50 text-purple-700 border-purple-100': conceptRec.pathway_meta.code === 'EXPLORER',
                  'bg-rose-50 text-rose-700 border-rose-100': conceptRec.pathway_meta.code === 'RESCUE',
                  'bg-amber-50 text-amber-700 border-amber-100': conceptRec.pathway_meta.code === 'FUSION',
                }">
                <span>{{ conceptRec.pathway_meta.name }}</span>
              </span>
            </div>
            
            <div class="flex flex-wrap gap-1.5">
              <button v-for="pw in [
                { code: 'ICE_BREAKER', name: '破冰', icon: '🚀' },
                { code: 'PRACTITIONER', name: '实操', icon: '🛠️' },
                { code: 'EXPLORER', name: '探究', icon: '🔬' },
                { code: 'RESCUE', name: '防忘', icon: '🚨' },
                { code: 'FUSION', name: '跨界', icon: '📈' }
              ]" :key="pw.code"
                @click="switchPathway(conceptRec.concept, pw.code)"
                :disabled="pathwayLoading[conceptRec.concept]"
                class="px-2.5 py-1 text-[10px] font-bold rounded-lg border transition-all flex items-center gap-1 shadow-sm"
                :class="conceptRec.pathway_meta.code === pw.code
                  ? 'bg-indigo-600 border-indigo-600 text-white font-extrabold shadow-md scale-[1.03]'
                  : 'bg-white border-slate-200 text-slate-600 hover:scale-[1.01] hover:bg-slate-50'">
                <span>{{ pw.icon }}</span>
                <span>{{ pw.name }}</span>
              </button>
            </div>
          </div>

          <!-- 学情诊断与改进意见 (细节分析、原因、意见) -->
          <div v-if="conceptRec.learning_state_overview" class="p-3.5 bg-slate-50 border border-slate-100 rounded-xl space-y-2">
            <h4 class="text-xs font-bold text-slate-800 flex items-center gap-1.5">
              📊 专属学情诊断与改进建议
            </h4>
            <div class="grid grid-cols-1 md:grid-cols-3 gap-4 text-[11px] text-slate-600 leading-relaxed">
              <div class="space-y-0.5">
                <span class="font-bold text-slate-800">🔍 细节分析：</span>
                <p>{{ conceptRec.learning_state_overview.detail_analysis }}</p>
              </div>
              <div class="space-y-0.5">
                <span class="font-bold text-slate-800">🧩 障碍原因：</span>
                <p>{{ conceptRec.learning_state_overview.reason }}</p>
              </div>
              <div class="space-y-0.5">
                <span class="font-bold text-slate-800">💡 教学意见：</span>
                <p>{{ conceptRec.learning_state_overview.advice }}</p>
              </div>
            </div>
          </div>

          <!-- 5-Dimensional Resource Matrix Grid Wrapper -->
          <div class="relative min-h-[160px]">
            <!-- Loading Indicator for compilation -->
            <div v-if="pathwayLoading[conceptRec.concept]" class="absolute inset-0 bg-white/70 backdrop-blur-[1px] z-10 flex flex-col items-center justify-center rounded-xl space-y-2">
              <div class="animate-spin w-6 h-6 border-2 border-indigo-600 border-t-transparent rounded-full" />
              <span class="text-xs font-bold text-indigo-700">战术路线重新编译中...</span>
            </div>

            <!-- Grid -->
            <div class="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-5 gap-4">
              <div v-for="res in getSortedResources(conceptRec.resources)" :key="res.key"
                @click="openResourceViewer(conceptRec.concept, res.key, res)"
                class="relative group overflow-hidden cursor-pointer rounded-2xl p-4 flex flex-col justify-between transition-all duration-300 border border-slate-100 hover:border-indigo-200 shadow-sm hover:shadow-md bg-white hover:bg-slate-50/20">
                
                <div class="space-y-3">
                  <!-- Icon & Title -->
                  <div class="flex items-center justify-between">
                    <div class="flex items-center gap-1.5">
                      <div class="w-6 h-6 rounded-lg flex items-center justify-center transition-transform group-hover:scale-110"
                        :class="{
                          'bg-blue-50 text-blue-600': res.key === 'lecture',
                          'bg-purple-50 text-purple-600': res.key === 'mindmap',
                          'bg-emerald-50 text-emerald-600': res.key === 'code',
                          'bg-amber-50 text-amber-600': res.key === 'quiz',
                          'bg-rose-50 text-rose-600': res.key === 'video'
                        }">
                        <component :is="getDimensionIcon(res.key)" :size="13" />
                      </div>
                      <div class="flex flex-col">
                        <span class="text-xs font-bold text-slate-800 leading-none flex items-center gap-1">
                          {{ res.resource_type }}
                        </span>
                        <span class="text-[9px] text-slate-400 mt-0.5">{{ res.role }}</span>
                      </div>
                    </div>
                    
                    <span class="px-1.5 py-0.5 text-[9px] font-bold rounded-md"
                      :class="res.status === 'generated' 
                        ? 'bg-emerald-50 text-emerald-600 border border-emerald-100' 
                        : 'bg-slate-50 text-slate-400 border border-slate-100'">
                      {{ res.status === 'generated' ? '已就绪' : '待生成' }}
                    </span>
                  </div>

                  <!-- Card Overview Description -->
                  <p class="text-[10px] text-slate-500 line-clamp-4 leading-relaxed min-h-[64px]">{{ res.overview }}</p>
                </div>

                <!-- Action Indicator -->
                <div class="mt-3.5 pt-2.5 border-t border-slate-100 flex items-center justify-between text-[10px] font-bold">
                  <span class="transition-colors" :class="res.status === 'generated' ? 'text-indigo-600 group-hover:text-indigo-700' : 'text-slate-500 group-hover:text-slate-700'">
                    {{ res.status === 'generated' ? '立即学习' : '一键生成' }}
                  </span>
                  <span class="text-xs transition-transform group-hover:translate-x-0.5">→</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 主内容：雷达图 + 薄弱点 -->
    <div class="grid grid-cols-1 md:grid-cols-3 gap-4">
      <!-- 雷达图 -->
      <div class="md:col-span-2 bg-white rounded-2xl border border-gray-100 shadow-sm p-4 overflow-hidden">
        <h2 class="text-sm font-semibold text-gray-800 mb-2 flex items-center gap-2">
          <Brain :size="15" class="text-purple-500" /> 知识掌握度
        </h2>
        <div class="h-56">
          <MasteryRadar v-if="conceptMastery.length" :concepts="conceptMastery" :student-id="props.studentId" />
          <div v-else class="flex items-center justify-center h-full text-xs text-gray-400">暂无数据，开始学习后自动生成</div>
        </div>
      </div>

      <!-- 薄弱点列表 -->
      <div class="bg-white rounded-2xl border border-gray-100 shadow-sm p-4">
        <h2 class="text-sm font-semibold text-gray-800 mb-2 flex items-center gap-2">
          <Target :size="15" class="text-rose-500" /> 需要加强
        </h2>
        <div v-if="weakConcepts.length" class="space-y-2">
          <div v-for="([concept, score], i) in weakConcepts" :key="concept"
            class="flex items-center gap-2 p-2 rounded-lg hover:bg-rose-50 transition-all cursor-pointer group"
            @click="goLearn(concept)">
            <span class="w-5 h-5 rounded-full bg-rose-100 text-rose-700 flex items-center justify-center text-[9px] font-bold shrink-0">{{ i + 1 }}</span>
            <span class="text-xs text-gray-700 flex-1">{{ concept }}</span>
            <span class="text-[10px] font-mono text-rose-600">{{ Math.round(score * 100) }}%</span>
            <ArrowRight :size="11" class="text-gray-300 opacity-0 group-hover:opacity-100 transition-opacity" />
          </div>
        </div>
        <div v-else class="flex flex-col items-center justify-center h-40 text-xs text-gray-400 gap-2">
          <CheckCircle2 :size="24" class="text-emerald-300" />
          <p>暂无薄弱点，继续保持！</p>
        </div>
      </div>
    </div>

    <!-- 快捷入口 -->
    <div class="grid grid-cols-2 md:grid-cols-4 gap-3">
      <button class="bg-white rounded-xl border border-gray-100 shadow-sm p-3 hover:border-purple-200 transition-all text-left flex items-center gap-3"
        @click="goLearn(nextUp[0]?.concept)">
        <div class="w-9 h-9 rounded-xl bg-purple-50 flex items-center justify-center"><BookOpen :size="16" class="text-purple-600" /></div>
        <div><p class="text-xs font-semibold text-gray-800">开始学习</p><p class="text-[9px] text-gray-400">进入对话</p></div>
      </button>
      <button class="bg-white rounded-xl border border-gray-100 shadow-sm p-3 hover:border-emerald-200 transition-all text-left flex items-center gap-3"
        @click="goAnalysis">
        <div class="w-9 h-9 rounded-xl bg-emerald-50 flex items-center justify-center"><UserCheck :size="16" class="text-emerald-600" /></div>
        <div><p class="text-xs font-semibold text-gray-800">学习画像</p><p class="text-[9px] text-gray-400">10维分析</p></div>
      </button>
      <button class="bg-white rounded-xl border border-gray-100 shadow-sm p-3 hover:border-indigo-200 transition-all text-left flex items-center gap-3"
        @click="goPath">
        <div class="w-9 h-9 rounded-xl bg-indigo-50 flex items-center justify-center"><TrendingUp :size="16" class="text-indigo-600" /></div>
        <div><p class="text-xs font-semibold text-gray-800">学习路径</p><p class="text-[9px] text-gray-400">链条推进</p></div>
      </button>
      <button class="bg-white rounded-xl border border-gray-100 shadow-sm p-3 hover:border-amber-200 transition-all text-left flex items-center gap-3"
        @click="goReview">
        <div class="w-9 h-9 rounded-xl bg-amber-50 flex items-center justify-center"><Calendar :size="16" class="text-amber-600" /></div>
        <div><p class="text-xs font-semibold text-gray-800">复习计划</p><p class="text-[9px] text-gray-400">遗忘曲线</p></div>
      </button>
    </div>

    <!-- 待复习概念 -->
    <div v-if="reviews.length" class="bg-white rounded-2xl border border-gray-100 shadow-sm p-4">
      <h2 class="text-sm font-semibold text-gray-800 mb-2 flex items-center gap-2">
        <Clock :size="15" class="text-amber-500" /> 待复习
      </h2>
      <div class="space-y-1">
        <div v-for="r in reviews.slice(0, 5)" :key="r.concept_name || r.id"
          class="flex items-center gap-2 text-xs py-1.5">
          <div class="w-1.5 h-1.5 rounded-full bg-amber-400" />
          <span class="text-gray-700 flex-1">{{ r.concept_name || '未命名概念' }}</span>
          <span class="text-gray-400 text-[10px]">{{ r.next_review_time ? new Date(r.next_review_time).toLocaleDateString() : '' }}</span>
          <button class="text-[10px] text-amber-600 hover:text-amber-800 font-medium" @click="goLearn(r.concept_name)">去复习</button>
        </div>
      </div>
    </div>

    <!-- 视频微课播放模态窗 -->
    <VideoRenderPanel
      :visible="showVideoPanel"
      :videoUrl="videoPanelUrl"
      :studentId="props.studentId"
      @close="showVideoPanel = false"
    />

    <!-- Drawer/Viewer for Resource Matrix -->
    <div v-if="activeResource" class="fixed inset-0 z-50 flex justify-end bg-slate-900/50 backdrop-blur-sm transition-opacity" @click="closeResourceViewer">
      <div class="w-full max-w-2xl bg-white h-full shadow-2xl flex flex-col justify-between overflow-hidden animate-slide-in" @click.stop>
        
        <!-- Drawer Header -->
        <div class="px-6 py-4 border-b border-slate-100 flex items-center justify-between bg-slate-50">
          <div>
            <div class="flex items-center gap-2">
              <span class="px-2 py-0.5 text-[10px] font-bold bg-indigo-50 text-indigo-700 rounded-lg">
                {{ activeResource.res.resource_type }}
              </span>
              <span class="text-xs text-slate-400">智能体：{{ activeResource.res.role }}</span>
            </div>
            <h3 class="text-base font-bold text-gray-800 mt-1">
              概念强化：<span class="text-indigo-600">{{ activeResource.concept }}</span>
            </h3>
          </div>
          <button @click="closeResourceViewer" class="p-1 rounded-lg hover:bg-slate-200 text-slate-400 hover:text-slate-600 transition-colors">
            <span class="text-xl">✕</span>
          </button>
        </div>

        <!-- Drawer Content -->
        <div class="flex-1 overflow-y-auto p-6 space-y-4">
          
          <!-- Case 1: NOT GENERATED -->
          <div v-if="activeResource.res.status === 'not_generated' && !isGenerating" class="flex flex-col items-center justify-center py-12 text-center space-y-4">
            <div class="w-16 h-16 rounded-full bg-slate-100 flex items-center justify-center text-2xl">
              💡
            </div>
            <div class="max-w-md">
              <h4 class="text-sm font-bold text-gray-800">该资源尚未生成</h4>
              <p class="text-xs text-slate-500 mt-1">您可以点击下方按钮，系统将调用专属于该维度的 AI 智能体实时根据您的学情为您量身生成定制内容。</p>
            </div>
            <div class="bg-slate-50 border border-slate-100 rounded-xl p-4 w-full text-left">
              <p class="text-[11px] font-bold text-slate-600 mb-1">🔍 生成预览大纲：</p>
              <p class="text-xs text-slate-500 leading-relaxed">{{ activeResource.res.overview }}</p>
            </div>
            <button @click="generateResource" 
              class="px-5 py-2.5 bg-indigo-600 hover:bg-indigo-700 text-white font-bold text-xs rounded-xl shadow-md transition-all flex items-center gap-1.5">
              🚀 开始一键生成
            </button>
          </div>

          <!-- Case 2: GENERATING -->
          <div v-else-if="isGenerating" class="flex flex-col items-center justify-center py-16 text-center space-y-4">
            <div class="animate-spin w-8 h-8 border-4 border-indigo-600 border-t-transparent rounded-full" />
            <div>
              <h4 class="text-sm font-bold text-gray-800">智能体正在深度生成中...</h4>
              <p class="text-xs text-slate-400 mt-1">正在调用【{{ activeResource.res.role }}】智能体进行推理与编写，请稍候 (5~15秒)...</p>
            </div>
          </div>

          <!-- Case 3: GENERATED / VIEWING -->
          <div v-else-if="activeResource.res.status === 'generated'" class="space-y-4">
            
            <!-- Dynamic Actions depending on type -->
            <div class="bg-indigo-50/50 border border-indigo-100/50 rounded-xl p-4 flex items-center justify-between">
              <div class="space-y-0.5">
                <p class="text-xs font-bold text-indigo-900">✨ 资源已就绪并同步存入您的学习笔记本</p>
                <p class="text-[10px] text-indigo-700">您可以直接在此阅读，也可以点击右侧进入独立的工作空间学习。</p>
              </div>
              
              <!-- Redirection shortcut -->
              <button @click="openInWorkspace" 
                class="px-3.5 py-1.5 bg-indigo-600 hover:bg-indigo-700 text-white text-xs font-bold rounded-lg flex items-center gap-1 shrink-0 shadow-sm transition-all">
                进入工作空间 →
              </button>
            </div>

            <!-- Content Area (Markdown render) -->
            <div class="markdown-body bg-slate-50/50 border border-slate-100 rounded-xl p-5 overflow-x-auto text-xs leading-relaxed max-w-full text-slate-700">
              <div class="whitespace-pre-wrap font-sans text-xs leading-relaxed">{{ activeResourceContent || '内容加载中...' }}</div>
            </div>

          </div>

        </div>

        <!-- Drawer Footer -->
        <div class="px-6 py-4 border-t border-slate-100 bg-slate-50 flex justify-end">
          <button @click="closeResourceViewer" class="px-4 py-2 border border-slate-200 text-slate-600 hover:bg-slate-100 text-xs font-bold rounded-xl transition-all">
            关闭窗口
          </button>
        </div>

      </div>
    </div>

  </div>
</template>

<style scoped>
@keyframes slide-in {
  from {
    transform: translateX(100%);
  }
  to {
    transform: translateX(0);
  }
}

.animate-slide-in {
  animation: slide-in 0.25s cubic-bezier(0.16, 1, 0.3, 1) forwards;
}
</style>
