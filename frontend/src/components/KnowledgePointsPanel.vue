<script setup>
/**
 * KnowledgePointsPanel.vue — 替换双曲圆盘
 * 浮窗显示当前对话涉及的知R识点 + 掌握度 + 讨论次数
 * 可最小化为浮动图标
 */
import { ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import { X, Minimize2, Maximize2, BookOpen, Target, TrendingUp, ExternalLink } from '@lucide/vue'

const props = defineProps({
  concepts: { type: Array, default: () => [] },      // [{name, mastery, count}]
  discussionThemes: { type: Array, default: () => [] }, // 当前讨论主题
  webResults: { type: Array, default: () => [] },       // 联网搜索结果
  inline: { type: Boolean, default: false },
})

const router = useRouter()
const minimized = ref(false)
const collapsed = ref(false)

const sortedConcepts = computed(() => {
  return [...props.concepts].sort((a, b) => (b.count || 0) - (a.count || 0))
})

function masteryColor(score) {
  if (score >= 0.6) return 'text-emerald-400'
  if (score >= 0.3) return 'text-amber-400'
  return 'text-red-400'
}

function barColor(score) {
  if (score >= 0.6) return 'bg-emerald-500'
  if (score >= 0.3) return 'bg-amber-500'
  return 'bg-red-500'
}

function goLearn(concept) {
  router.push({ path: '/learn', query: { q: concept } })
}

function toggleMinimize() { minimized.value = !minimized.value }
function toggleCollapse() { collapsed.value = !collapsed.value }
</script>

<template>
  <!-- 浮动图标（最小化状态） -->
  <div v-if="!inline && minimized"
    class="fixed bottom-6 right-6 z-50 group"
    @click="toggleMinimize">
    <div class="w-12 h-12 rounded-full bg-gradient-to-br from-purple-500 to-indigo-600 shadow-lg flex items-center justify-center cursor-pointer hover:scale-110 transition-all hover:shadow-xl">
      <BookOpen :size="22" class="text-white" />
    </div>
    <!-- Tooltip -->
    <div class="absolute right-full mr-3 top-1/2 -translate-y-1/2 scale-75 opacity-0 group-hover:scale-100 group-hover:opacity-100 transition-all duration-200 bg-gray-900/90 text-white text-xs px-2.5 py-1.5 rounded-lg border border-gray-700/50 shadow-xl pointer-events-none whitespace-nowrap">
      展开知识点速览
    </div>
  </div>

  <div v-else-if="inline || !minimized"
    :class="inline
      ? 'w-full h-full flex flex-col bg-slate-950/40 rounded-2xl border border-slate-800/80 overflow-hidden'
      : 'fixed top-20 right-6 z-50 w-80 max-h-[70vh] bg-gray-900/95 backdrop-blur-md border border-gray-700/50 rounded-2xl shadow-2xl flex flex-col overflow-hidden transition-all duration-200'"
  >

    <!-- Header -->
    <div class="flex items-center justify-between px-4 py-3 border-b border-gray-700/50 shrink-0 bg-gray-800/80">
      <div class="flex items-center gap-2">
        <div class="w-6 h-6 rounded-lg bg-gradient-to-br from-purple-500 to-indigo-600 flex items-center justify-center">
          <BookOpen :size="12" class="text-white" />
        </div>
        <span class="text-xs font-semibold text-gray-200">知识点速览</span>
      </div>
      <div v-if="!inline" class="flex items-center gap-1">
        <button @click="toggleCollapse" class="w-6 h-6 rounded-lg hover:bg-gray-700 flex items-center justify-center text-gray-400 hover:text-gray-200 transition-all">
          <Minimize2 v-if="!collapsed" :size="12" />
          <Maximize2 v-else :size="12" />
        </button>
        <button @click="toggleMinimize" class="w-6 h-6 rounded-lg hover:bg-gray-700 flex items-center justify-center text-gray-400 hover:text-gray-200 transition-all">
          <X :size="12" />
        </button>
      </div>
    </div>

    <!-- Content -->
    <div v-if="inline || !collapsed" class="flex-1 overflow-y-auto p-3 space-y-3 scrollbar-thin">

      <!-- 当前讨论主题 -->
      <div v-if="discussionThemes.length">
        <p class="text-[9px] font-semibold text-gray-500 uppercase tracking-wider mb-1.5">当前讨论</p>
        <div class="flex flex-wrap gap-1">
          <span v-for="t in discussionThemes" :key="t"
            class="px-2 py-0.5 text-[10px] rounded-full bg-purple-500/20 text-purple-300 border border-purple-500/30">
            {{ t }}
          </span>
        </div>
      </div>

      <!-- 知识点列表 -->
      <div v-if="sortedConcepts.length">
        <p class="text-[9px] font-semibold text-gray-500 uppercase tracking-wider mb-1.5 flex items-center gap-1">
          <Target :size="10" /> 涵盖知识点
        </p>
        <div class="space-y-1.5">
          <div v-for="c in sortedConcepts.slice(0, collapsed ? 0 : 8)" :key="c.name"
            class="flex items-center gap-2 py-1.5 px-2 rounded-lg hover:bg-gray-800/50 transition-all cursor-pointer group"
            @click="goLearn(c.name)">
            <div class="flex-1 min-w-0">
              <div class="flex items-center gap-1.5">
                <span class="text-xs text-gray-300 truncate">{{ c.name }}</span>
                <span class="text-[9px] text-gray-500 shrink-0">×{{ c.count || 1 }}</span>
              </div>
              <div class="h-1 bg-gray-800 rounded-full mt-1 overflow-hidden">
                <div class="h-full rounded-full transition-all" :class="barColor(c.mastery || 0)" :style="{ width: Math.min(100, (c.mastery || 0) * 100) + '%' }" />
              </div>
            </div>
            <span class="text-[10px] font-mono shrink-0" :class="masteryColor(c.mastery || 0)">{{ Math.round((c.mastery || 0) * 100) }}%</span>
            <ExternalLink :size="10" class="text-gray-600 opacity-0 group-hover:opacity-100 transition-all shrink-0" />
          </div>
        </div>
      </div>
      <div v-else class="py-4 text-center text-[10px] text-gray-500">暂无知识点数据</div>

      <!-- 联网搜索 -->
      <div v-if="webResults.length">
        <p class="text-[9px] font-semibold text-gray-500 uppercase tracking-wider mb-1.5 flex items-center gap-1">
          <TrendingUp :size="10" /> 联网资料
        </p>
        <div class="space-y-1">
          <a v-for="(r, i) in webResults.slice(0, 3)" :key="i" :href="r.url" target="_blank"
            class="block py-1.5 px-2 rounded-lg hover:bg-gray-800/50 transition-all text-[10px]">
            <p class="text-blue-400 truncate">{{ r.title || r.url }}</p>
            <p class="text-gray-500 truncate mt-0.5">{{ r.snippet || '' }}</p>
          </a>
        </div>
      </div>

    </div>
  </div>
</template>
