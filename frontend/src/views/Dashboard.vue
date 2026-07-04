<script setup>
import { ref, onMounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import { getStudentProfile, getLearningPath, getReviewPlans, getRecommendations } from '../api'
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
const loading = ref(true)

const showVideoPanel = ref(false)
const videoPanelUrl = ref('')

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
function goAnalysis() { router.push('/student-analysis') }
function goReview() { router.push('/review') }

function goNotes(concept) {
  router.push({ path: '/notes', query: { search: concept } })
}

function playVideo(url) {
  videoPanelUrl.value = url
  showVideoPanel.value = true
}

onMounted(async () => {
  try {
    const sid = props.studentId || localStorage.getItem('edumatrix_student_id') || 'demo-student'
    const [p, lp, rv, recs] = await Promise.all([
      getStudentProfile(sid),
      getLearningPath(sid).catch(() => null),
      getReviewPlans(sid).catch(() => []),
      getRecommendations(sid).catch(() => []),
    ])
    profile.value = p
    learningPath.value = lp
    reviews.value = Array.isArray(rv) ? rv : (rv?.plans || rv?.due_reviews || [])
    recommendations.value = recs || []
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

    <!-- 智能自适应资源推送 -->
    <div v-if="recommendations.length" class="space-y-3">
      <h2 class="text-sm font-bold text-gray-800 flex items-center gap-2">
        <Sparkles :size="15" class="text-indigo-500" />
        <span>智教自适应资源推送</span>
        <span class="px-2 py-0.5 text-[9px] font-semibold bg-indigo-50 text-indigo-600 rounded-full border border-indigo-100 animate-pulse">AI Agent 推荐</span>
      </h2>
      
      <div class="grid grid-cols-1 md:grid-cols-3 gap-3">
        <div v-for="item in recommendations" :key="item.title"
          class="bg-white rounded-2xl border border-slate-100 shadow-sm hover:shadow-md hover:border-indigo-100/50 transition-all p-4 flex flex-col justify-between relative group overflow-hidden">
          
          <!-- Background Accent decoration depending on resource type -->
          <div class="absolute -right-6 -top-6 w-16 h-16 rounded-full opacity-5 pointer-events-none transition-transform group-hover:scale-125"
            :class="{
              'bg-blue-500': item.resource_type === 'document',
              'bg-emerald-500': item.resource_type === 'code',
              'bg-indigo-500': item.resource_type === 'video'
            }" />
            
          <div>
            <!-- Header Badges -->
            <div class="flex items-center justify-between mb-2">
              <span class="px-2 py-0.5 text-[9px] font-bold rounded-lg border"
                :class="{
                  'bg-rose-50 text-rose-600 border-rose-100': item.badge === '🔥 薄弱强化',
                  'bg-purple-50 text-purple-600 border-purple-100': item.badge === '💡 探索进阶',
                  'bg-indigo-50 text-indigo-600 border-indigo-100': item.badge === '⚡ 微课视频'
                }">
                {{ item.badge }}
              </span>
              <span class="text-[9px] text-gray-400 font-medium truncate max-w-[120px]">{{ item.source_name }}</span>
            </div>

            <!-- Custom reasoning -->
            <p class="text-[10px] text-slate-400 leading-normal mb-1.5">{{ item.reason }}</p>
            
            <!-- Title -->
            <h3 class="text-xs font-bold text-gray-800 line-clamp-1 mb-2">{{ item.title }}</h3>
            
            <!-- Content preview -->
            <div class="bg-slate-50/70 border border-slate-100/50 rounded-xl p-3 mb-4 min-h-[72px] flex items-center">
              <!-- Code Snippet preview style -->
              <pre v-if="item.resource_type === 'code'" class="text-[9px] text-gray-600 font-mono overflow-x-auto w-full leading-relaxed">{{ item.content.replace(/```python|```/g, '').trim() }}</pre>
              
              <!-- Video preview style -->
              <div v-else-if="item.resource_type === 'video'" class="flex items-center gap-2.5 w-full">
                <div class="w-10 h-10 rounded-lg bg-indigo-50 border border-indigo-100 flex items-center justify-center shrink-0">
                  <Play :size="16" class="text-indigo-500 fill-indigo-200" />
                </div>
                <div class="flex-1 min-w-0">
                  <p class="text-[10px] text-slate-600 font-medium line-clamp-2 leading-relaxed">{{ item.content }}</p>
                </div>
              </div>
              
              <!-- Standard doc style -->
              <p v-else class="text-[10px] text-slate-600 line-clamp-3 leading-relaxed w-full">{{ item.content }}</p>
            </div>
          </div>

          <!-- Bottom Action Buttons -->
          <div class="mt-auto">
            <button v-if="item.resource_type === 'video'"
              @click="playVideo(item.url)"
              class="w-full py-1.5 bg-indigo-50 hover:bg-indigo-100 text-indigo-700 text-xs font-semibold rounded-xl flex items-center justify-center gap-1.5 transition-all border border-indigo-100">
              <Play :size="12" class="fill-indigo-300" /> 播放讲解视频
            </button>
            <button v-else-if="item.resource_type === 'code'"
              @click="goLearn(item.concept)"
              class="w-full py-1.5 bg-emerald-50 hover:bg-emerald-100 text-emerald-700 text-xs font-semibold rounded-xl flex items-center justify-center gap-1.5 transition-all border border-emerald-100">
              <Activity :size="12" /> 进入沙箱运行
            </button>
            <button v-else
              @click="goNotes(item.concept)"
              class="w-full py-1.5 bg-blue-50 hover:bg-blue-100 text-blue-700 text-xs font-semibold rounded-xl flex items-center justify-center gap-1.5 transition-all border border-blue-100">
              <BookOpen :size="12" /> 阅读笔记/讲义
            </button>
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

  </div>
</template>
