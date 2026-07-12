<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { getHistory } from '../api'
import { rollbackProfile } from '../api/profile'
import {
  Clock, MessageSquare, Search, ArrowRight, Bot, Sparkles,
  BrainCircuit, CheckCircle2, AlertTriangle, ArrowUpRight,
  GraduationCap, RotateCcw, Loader2, X, Info
} from '@lucide/vue'

const props = defineProps({ studentId: String })
const router = useRouter()

const history = ref([])
const loading = ref(true)
const searchFilter = ref('')

// 时空回溯状态
const rollbackingId = ref(null)
const toast = ref(null)   // { type: 'success'|'error', msg: string }
let toastTimer = null

function showToast(type, msg) {
  if (toastTimer) clearTimeout(toastTimer)
  toast.value = { type, msg }
  toastTimer = setTimeout(() => { toast.value = null }, 3500)
}

onMounted(async () => {
  try {
    const data = await getHistory(props.studentId)
    const raw = data.conversations || data.history || []
    history.value = Array.isArray(raw) ? raw : []
  } catch (e) {
    console.error(e)
  } finally {
    loading.value = false
  }
})

const filtered = computed(() => {
  if (!searchFilter.value) return history.value
  const q = searchFilter.value.toLowerCase()
  return history.value.filter(h =>
    (h.query || h.message || '').toLowerCase().includes(q) ||
    (h.target || '').toLowerCase().includes(q) ||
    (h.response_summary || h.response || '').toLowerCase().includes(q)
  )
})

function parseTimestamp(ts) {
  if (!ts) return null
  if (ts instanceof Date) return ts
  if (typeof ts === 'number') return new Date(ts)
  let str = String(ts).trim()
  if (str.includes(' ') && !str.includes('T')) str = str.replace(' ', 'T')
  if (str.includes('-') && str.includes(':') && !str.endsWith('Z') && !/\+\d{2}:?\d{2}$/.test(str) && !/-\d{2}:?\d{2}$/.test(str)) str += 'Z'
  const d = new Date(str)
  return isNaN(d.getTime()) ? null : d
}

function ago(ts) {
  const d = parseTimestamp(ts)
  if (!d) return '未知时间'
  const s = Math.floor((Date.now() - d.getTime()) / 1000)
  if (s < 0) return '刚刚'
  if (s < 60) return '刚刚'
  if (s < 3600) return `${Math.floor(s / 60)}分钟前`
  if (s < 86400) return `${Math.floor(s / 3600)}小时前`
  if (s < 259200) return `${Math.floor(s / 86400)}天前`
  return d.toLocaleDateString('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit' })
}

function backtrackDialogue(item) {
  router.push({ path: '/learn', query: { prompt: item.query || item.message } })
}

function startQuiz(concept) {
  if (typeof window.startInteractiveQuiz === 'function') {
    window.startInteractiveQuiz(concept)
  } else {
    router.push({ path: '/learn', query: { quiz: concept } })
  }
}

// 时空回溯：将快照还原到当前画像
async function handleRollback(item) {
  const cid = item.id
  if (!cid || rollbackingId.value) return
  rollbackingId.value = cid
  try {
    const res = await rollbackProfile(props.studentId, cid)
    showToast('success',
      `✅ 已将认知状态回溯至 "${ago(item.created_at || item.timestamp)}"（${res.applied_fields?.join(', ')}）`
    )
  } catch (err) {
    showToast('error', `⚠️ 回溯失败：${err?.response?.data?.detail || err.message}`)
  } finally {
    rollbackingId.value = null
  }
}

function parseResponseSummary(summary) {
  if (!summary) return []
  return summary.split(';').map(part => {
    const splitted = part.split(':').map(s => s.trim())
    if (splitted.length < 2) return null
    return { agent: splitted[0], rtype: splitted[1] }
  }).filter(Boolean)
}

function getResourceBadgeClass(rtype) {
  const mapping = {
    '专业讲义': 'bg-blue-50/80 text-blue-700 border border-blue-100/50 dark:bg-blue-950/20 dark:text-blue-300 dark:border-blue-900/30',
    '思维导图': 'bg-purple-50/80 text-purple-700 border border-purple-100/50 dark:bg-purple-950/20 dark:text-purple-300 dark:border-purple-900/30',
    '代码实操案例': 'bg-amber-50/80 text-amber-700 border border-amber-100/50 dark:bg-amber-950/20 dark:text-amber-300 dark:border-amber-900/30',
    '练习题': 'bg-rose-50/80 text-rose-700 border border-rose-100/50 dark:bg-rose-950/20 dark:text-rose-300 dark:border-rose-900/30',
    '虚拟人视频脚本': 'bg-emerald-50/80 text-emerald-700 border border-emerald-100/50 dark:bg-emerald-950/20 dark:text-emerald-300 dark:border-emerald-900/30',
  }
  return mapping[rtype] || 'bg-gray-50/80 text-gray-700 border border-gray-100/50 dark:bg-gray-850 dark:text-gray-300 dark:border-gray-800'
}

// FSM 模式标签与颜色
function fsmBadge(mode) {
  const map = {
    'intensive':  { label: '强化模式', cls: 'bg-rose-50 text-rose-700 border-rose-200 dark:bg-rose-950/30 dark:text-rose-300' },
    'challenge':  { label: '拓展模式', cls: 'bg-purple-50 text-purple-700 border-purple-200 dark:bg-purple-950/30 dark:text-purple-300' },
    'relaxed':    { label: '舒缓模式', cls: 'bg-teal-50 text-teal-700 border-teal-200 dark:bg-teal-950/30 dark:text-teal-300' },
    'normal':     { label: '常规模式', cls: 'bg-gray-50 text-gray-600 border-gray-200 dark:bg-gray-800 dark:text-gray-300' },
  }
  return map[mode] || map['normal']
}

// 掌握度 chip 颜色
function masteryColor(v) {
  if (v >= 0.7) return 'text-emerald-600 dark:text-emerald-400'
  if (v >= 0.4) return 'text-amber-600 dark:text-amber-400'
  return 'text-rose-500 dark:text-rose-400'
}

function hasSnapshot(item) {
  return !!item.profile_snapshot
}

function snapshotMastery(item) {
  const snap = item.profile_snapshot
  if (!snap || !snap.concept_mastery) return []
  return Object.entries(snap.concept_mastery)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 5)
}
</script>

<template>
  <div class="max-w-4xl mx-auto pb-12">

    <!-- Toast 通知 -->
    <Transition name="toast">
      <div v-if="toast"
           class="fixed top-6 right-6 z-50 flex items-start gap-3 max-w-sm px-4 py-3 rounded-2xl shadow-xl text-sm font-medium border backdrop-blur-lg"
           :class="toast.type === 'success'
             ? 'bg-white/90 dark:bg-gray-900/90 border-emerald-200 dark:border-emerald-800 text-gray-800 dark:text-gray-200'
             : 'bg-white/90 dark:bg-gray-900/90 border-rose-200 dark:border-rose-800 text-gray-800 dark:text-gray-200'">
        <span class="mt-0.5">{{ toast.msg }}</span>
        <button @click="toast = null" class="ml-auto text-gray-400 hover:text-gray-600 shrink-0">
          <X :size="14" />
        </button>
      </div>
    </Transition>

    <!-- Header Controls -->
    <div class="flex items-center justify-between mb-8">
      <div>
        <h2 class="text-lg font-bold text-gray-900 dark:text-white">对话时空历史</h2>
        <p class="text-xs text-gray-500 mt-0.5">追溯您的自适应学习路径，随时进行时空回溯或自适应测试</p>
      </div>
      <div class="relative w-64">
        <Search :size="14" class="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
        <input v-model="searchFilter" class="input pl-8 py-1.5" placeholder="搜索问题、知识点或智能体..." />
      </div>
    </div>

    <!-- Loading State -->
    <div v-if="loading" class="flex flex-col items-center justify-center py-20">
      <div class="pulse-dot" />
      <span class="mt-4 text-gray-400 text-sm">正在读取时空对话载荷...</span>
    </div>

    <!-- Empty State -->
    <div v-else-if="filtered.length === 0" class="text-center py-20 bg-white dark:bg-gray-900 border border-gray-100 dark:border-gray-800 rounded-2xl shadow-sm">
      <MessageSquare :size="48" class="mx-auto mb-4 text-gray-300 dark:text-gray-700" />
      <p class="text-sm font-medium text-gray-600 dark:text-gray-400">{{ searchFilter ? '未找到匹配的时空历史记录' : '暂无对话历史记录' }}</p>
      <p class="text-xs text-gray-400 mt-1.5">去智能对话页面开始您的探究式学习吧</p>
      <router-link to="/learn" class="btn btn-primary mt-6 text-xs px-4 py-2 inline-flex items-center gap-1.5">
        开启对话学习 <ArrowRight :size="12" />
      </router-link>
    </div>

    <!-- Timeline Cards List -->
    <div v-else class="relative pl-6 border-l-2 border-gray-200/60 dark:border-gray-800/80 space-y-6">
      <div v-for="item in filtered" :key="item.id || item.timestamp"
           class="relative bg-white dark:bg-gray-900 border border-gray-100/90 dark:border-gray-800/90 rounded-2xl p-5 shadow-sm hover:shadow-md transition-all duration-200 group"
           :class="item.alignment_passed ? 'border-l-4 border-l-success' : 'border-l-4 border-l-warning'">

        <!-- Timeline Dot -->
        <div class="absolute -left-[32px] top-[22px] w-4.5 h-4.5 rounded-full border-2 bg-white dark:bg-gray-950 flex items-center justify-center transition-transform group-hover:scale-110"
             :class="item.alignment_passed ? 'border-success text-success' : 'border-warning text-warning'">
          <div class="w-2 h-2 rounded-full" :class="item.alignment_passed ? 'bg-success' : 'bg-warning'" />
        </div>

        <!-- Card Header -->
        <div class="flex flex-wrap items-center justify-between gap-3 pb-3.5 mb-4 border-b border-gray-100 dark:border-gray-800/60 text-xs">
          <div class="flex flex-wrap items-center gap-2">
            <!-- Alignment badge -->
            <span v-if="item.alignment_passed"
                  class="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-emerald-700 dark:text-emerald-300 bg-emerald-50 dark:bg-emerald-950/40 font-medium">
              <CheckCircle2 :size="12" /> 认知流形对齐通过
            </span>
            <span v-else
                  class="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-amber-700 dark:text-amber-300 bg-amber-50 dark:bg-amber-950/40 font-medium">
              <AlertTriangle :size="12" /> 认知流形偏离警告
            </span>

            <!-- FSM mode badge（来自 profile_snapshot）-->
            <span v-if="item.profile_snapshot?.fsm_mode"
                  class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-semibold border"
                  :class="fsmBadge(item.profile_snapshot.fsm_mode).cls">
              {{ fsmBadge(item.profile_snapshot.fsm_mode).label }}
            </span>

            <!-- Target concept badge -->
            <span v-if="item.target"
                  class="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-blue-700 dark:text-blue-300 bg-blue-50 dark:bg-blue-950/40 font-medium">
              <GraduationCap :size="12" /> 目标概念: {{ item.target }}
            </span>
          </div>

          <!-- Timestamp -->
          <div class="flex items-center gap-1 text-gray-400 dark:text-gray-500 font-medium shrink-0">
            <Clock :size="12" /> {{ ago(item.created_at || item.timestamp) }}
          </div>
        </div>

        <!-- Card Body -->
        <div class="space-y-4">
          <!-- Student query -->
          <div class="flex items-start gap-3">
            <div class="w-7 h-7 rounded-lg bg-blue-50 dark:bg-blue-950/40 flex items-center justify-center text-blue-600 dark:text-blue-400 text-xs font-extrabold shrink-0 border border-blue-100/50 dark:border-blue-900/30">
              问
            </div>
            <div class="flex-1 min-w-0">
              <h4 class="text-[10px] font-bold text-gray-400 dark:text-gray-500 uppercase tracking-wider mb-0.5">学生提问</h4>
              <p class="text-sm font-medium text-gray-800 dark:text-gray-200 leading-normal">{{ item.query || item.message || item.question || '-' }}</p>
            </div>
          </div>

          <!-- Swarm agent chain -->
          <div class="flex items-start gap-3">
            <div class="w-7 h-7 rounded-lg bg-purple-50 dark:bg-purple-950/40 flex items-center justify-center text-purple-600 dark:text-purple-400 text-xs font-extrabold shrink-0 border border-purple-100/50 dark:border-purple-900/30">
              答
            </div>
            <div class="flex-1 min-w-0">
              <h4 class="text-[10px] font-bold text-gray-400 dark:text-gray-500 uppercase tracking-wider mb-2">1+3+5 智能体 Swarm 协同响应</h4>
              <div v-if="parseResponseSummary(item.response_summary).length > 0" class="flex flex-wrap items-center gap-2 mb-3">
                <span class="text-xs text-gray-400 dark:text-gray-500 flex items-center gap-1 mr-1">
                  <Bot :size="12" /> Swarm 协作链:
                </span>
                <span v-for="(agentItem, idx) in parseResponseSummary(item.response_summary)" :key="idx"
                      class="inline-flex items-center gap-1.5 px-2 py-0.5 rounded text-[11px] font-semibold transition-all"
                      :class="getResourceBadgeClass(agentItem.rtype)">
                  <Sparkles v-if="agentItem.rtype === '思维导图'" :size="10" />
                  <GraduationCap v-else-if="agentItem.rtype === '专业讲义'" :size="10" />
                  <BrainCircuit v-else-if="agentItem.rtype === '练习题'" :size="10" />
                  <span class="opacity-75">[{{ agentItem.agent }}]</span>
                  <span>{{ agentItem.rtype }}</span>
                </span>
              </div>
              <div v-if="item.response || item.response_summary"
                   class="bg-gray-50/50 dark:bg-gray-900/40 border border-gray-100/60 dark:border-gray-800/40 rounded-xl p-3 text-xs text-gray-600 dark:text-gray-400 leading-relaxed font-sans italic">
                {{ item.response || item.response_summary }}
              </div>
            </div>
          </div>

          <!-- 快照认知状态预览（仅当存在时展示）-->
          <div v-if="hasSnapshot(item)" class="rounded-xl bg-gradient-to-br from-indigo-50/60 to-purple-50/40 dark:from-indigo-950/20 dark:to-purple-950/10 border border-indigo-100/50 dark:border-indigo-900/30 p-3">
            <div class="flex items-center gap-1.5 mb-2 text-[10px] font-bold text-indigo-500 dark:text-indigo-400 uppercase tracking-wider">
              <Info :size="10" /> 当时认知快照
              <span class="ml-auto font-normal normal-case text-gray-400">掌握度 Top 5</span>
            </div>
            <div class="flex flex-wrap gap-2">
              <span v-for="([concept, score]) in snapshotMastery(item)" :key="concept"
                    class="inline-flex items-center gap-1 text-[11px] px-2 py-0.5 rounded-lg bg-white/60 dark:bg-gray-800/60 border border-white/80 dark:border-gray-700/50 font-medium">
                <span class="text-gray-600 dark:text-gray-300">{{ concept }}</span>
                <span :class="masteryColor(score)" class="font-bold">{{ Math.round(score * 100) }}%</span>
              </span>
            </div>
            <div v-if="item.profile_snapshot?.mastery_score != null" class="mt-2 text-[10px] text-gray-400">
              综合掌握度：<span class="font-bold" :class="masteryColor(item.profile_snapshot.mastery_score)">
                {{ Math.round((item.profile_snapshot.mastery_score || 0) * 100) }}%
              </span>
            </div>
          </div>
        </div>

        <!-- Card Footer Action Buttons -->
        <div class="flex items-center justify-end gap-3 mt-4 pt-3.5 border-t border-gray-100/80 dark:border-gray-800/40">
          <!-- 时空回溯对话 -->
          <button @click="backtrackDialogue(item)"
                  class="btn btn-outline py-1.5 px-3 rounded-lg text-xs flex items-center gap-1.5 hover:bg-blue-50/50 dark:hover:bg-blue-950/20 hover:text-blue-600 dark:hover:text-blue-400 hover:border-blue-200 dark:hover:border-blue-900 transition-colors">
            <ArrowUpRight :size="12" /> 继续对话
          </button>

          <!-- 画像状态回滚按钮（仅当该条目有快照时才显示）-->
          <button v-if="hasSnapshot(item)"
                  @click="handleRollback(item)"
                  :disabled="rollbackingId === item.id"
                  class="btn py-1.5 px-3 rounded-lg text-xs flex items-center gap-1.5 font-medium transition-all border
                         bg-gradient-to-r from-indigo-50 to-purple-50 dark:from-indigo-950/30 dark:to-purple-950/20
                         text-indigo-700 dark:text-indigo-300 border-indigo-200/60 dark:border-indigo-800/40
                         hover:from-indigo-100 hover:to-purple-100 dark:hover:from-indigo-950/50 dark:hover:to-purple-950/40
                         disabled:opacity-50 disabled:cursor-not-allowed">
            <Loader2 v-if="rollbackingId === item.id" :size="12" class="animate-spin" />
            <RotateCcw v-else :size="12" />
            跳转认知状态
          </button>

          <!-- 自适应小测 -->
          <button v-if="item.target"
                  @click="startQuiz(item.target)"
                  class="btn btn-primary py-1.5 px-3 rounded-lg text-xs flex items-center gap-1.5 shadow-sm hover:shadow transition-all bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-700 hover:to-indigo-700 text-white font-medium">
            <BrainCircuit :size="12" /> 自适应小测
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.toast-enter-active,
.toast-leave-active {
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}
.toast-enter-from,
.toast-leave-to {
  opacity: 0;
  transform: translateY(-12px) scale(0.95);
}
</style>
