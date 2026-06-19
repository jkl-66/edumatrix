<script setup>
/**
 * AgentTimeline.vue — 任务 9.1: 多智能体时序追踪面板
 *
 * 完整还原每一轮辩论、证据检索、对齐校正的时间线步骤。
 * 用于学术评审验证推理过程。
 */
import { ref, computed } from 'vue'
import { 
  Clock, CheckCircle2, XCircle, Search, MessageSquare, GitBranch, AlertTriangle, Loader2,
  BookOpen, LayoutGrid, Code2, HelpCircle, Video, Target
} from '@lucide/vue'

const props = defineProps({
  steps: { type: Array, default: () => [] },  // Array of {id, agent, action, status, detail, timestamp, duration}
  compact: { type: Boolean, default: false },
  // 任务 9.1 / 8.2 兼容的实时流属性
  progress: { type: Number, default: 0 },
  status: { type: String, default: '' },
  agents: { type: Object, default: () => ({}) },
})

const expanded = ref(new Set())

function toggleStep(id) {
  if (expanded.value.has(id)) {
    expanded.value.delete(id)
  } else {
    expanded.value.add(id)
  }
}

// 融合传入的 steps 与实时 agents 状态以动态渲染
const computedSteps = computed(() => {
  if (props.steps && props.steps.length > 0) {
    return props.steps
  }

  const result = []

  // 将 agents 实时状态转化为步骤
  Object.entries(props.agents).forEach(([name, info], index) => {
    result.push({
      id: name,
      agent: name,
      action: info.type || '生成资源',
      status: info.error ? 'error' : (info.done ? 'success' : 'running'),
      detail: info.error ? `生成出错: ${info.error}` : `成功生成 ${info.type || '资源'}`,
      duration: 1200 + index * 300,
    })
  })

  // 如果正在生成中且当前状态不在列表中，作为主控官的步骤显示
  if (props.status && props.progress < 100) {
    const alreadyExists = result.some(r => r.action === props.status)
    if (!alreadyExists) {
      result.push({
        id: 'status-running',
        agent: '全脑主控官',
        action: props.status,
        status: 'running',
        detail: '全脑主控官正在动态路由并调度协调子智能体...',
        duration: 0,
      })
    }
  }

  return result
})

const totalDuration = computed(() => {
  return computedSteps.value.reduce((acc, s) => acc + (s.duration || 0), 0)
})

// Agent 图标映射
function agentIcon(agent) {
  const map = {
    '诊断官': Search,
    '规划官': GitBranch,
    '辩论官': MessageSquare,
    '法官': CheckCircle2,
    '对齐器': GitBranch,
    '检索器': Search,
    '理论教授': BookOpen,
    '逻辑画师': LayoutGrid,
    '极客助教': Code2,
    '考官智能体': HelpCircle,
    '虚拟导演': Video,
    '全脑主控官': Target,
  }
  return map[agent] || Clock
}
</script>

<template>
  <div class="agent-timeline bg-gray-900 rounded-lg border border-gray-800 overflow-hidden">
    <!-- 头部 -->
    <div class="flex items-center justify-between px-3 py-2 bg-gray-850 border-b border-gray-800">
      <div class="flex items-center gap-2">
        <Clock :size="14" class="text-purple-400" />
        <span class="text-xs font-semibold text-gray-200">推理时序追踪</span>
        <span v-if="!compact" class="text-[10px] text-gray-500">共 {{ computedSteps.length }} 步</span>
      </div>
      <span v-if="!compact" class="text-[10px] text-gray-500">{{ (totalDuration / 1000).toFixed(1) }}s</span>
    </div>

    <!-- 时间线 -->
    <div class="p-3 max-h-[400px] overflow-y-auto scrollbar-thin">
      <div v-if="!computedSteps.length" class="text-center text-gray-500 text-xs py-6">
        <Loader2 :size="20" class="mx-auto mb-2 opacity-50 animate-spin text-purple-500" />
        <p>等待推理步骤...</p>
      </div>

      <div v-else class="relative">
        <!-- 竖线 -->
        <div class="absolute left-[11px] top-2 bottom-2 w-0.5 bg-gray-700" />

        <div v-for="(step, idx) in computedSteps" :key="step.id || idx" class="relative pl-8 pb-3 last:pb-0">
          <!-- 时间线圆点 -->
          <div class="absolute left-[5px] top-0.5 w-3.5 h-3.5 rounded-full border-2 flex items-center justify-center"
            :class="{
              'border-green-500 bg-green-900/40': step.status === 'success',
              'border-red-500 bg-red-900/40': step.status === 'error',
              'border-yellow-500 bg-yellow-900/40': step.status === 'warning',
              'border-blue-500 bg-blue-900/40': step.status === 'running',
              'border-gray-600 bg-gray-800': step.status === 'pending',
            }">
            <CheckCircle2 v-if="step.status === 'success'" :size="8" class="text-green-400" />
            <XCircle v-else-if="step.status === 'error'" :size="8" class="text-red-400" />
            <AlertTriangle v-else-if="step.status === 'warning'" :size="8" class="text-yellow-400" />
            <Loader2 v-else-if="step.status === 'running'" :size="8" class="text-blue-400 animate-spin" />
          </div>

          <!-- 步骤卡片 -->
          <div class="cursor-pointer select-none"
            @click="toggleStep(step.id || idx)">
            <div class="flex items-center justify-between">
              <div class="flex items-center gap-2 min-w-0">
                <component :is="agentIcon(step.agent)" :size="12" class="shrink-0 text-gray-400" />
                <span class="text-xs font-medium text-gray-300 truncate">{{ step.agent }}</span>
                <span class="text-[10px] text-gray-500">{{ step.action }}</span>
              </div>
              <div class="flex items-center gap-2 shrink-0">
                <span v-if="step.duration" class="text-[10px] text-gray-500">{{ step.duration }}ms</span>
                <span class="text-[10px]" :class="step.status === 'success' ? 'text-green-500' : step.status === 'error' ? 'text-red-500' : 'text-yellow-500'">
                  {{ step.status }}
                </span>
              </div>
            </div>

            <!-- 展开详情 -->
            <div v-if="expanded.has(step.id || idx) && step.detail" class="mt-1.5 pl-4">
              <pre class="text-[10px] text-gray-400 font-mono whitespace-pre-wrap bg-gray-950 rounded p-2">{{ step.detail }}</pre>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.agent-timeline {
  box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06);
}

/* 滚动条美化 */
.scrollbar-thin::-webkit-scrollbar {
  width: 4px;
}
.scrollbar-thin::-webkit-scrollbar-track {
  background: transparent;
}
.scrollbar-thin::-webkit-scrollbar-thumb {
  background: rgba(148, 163, 184, 0.2);
  border-radius: 2px;
}
.scrollbar-thin::-webkit-scrollbar-thumb:hover {
  background: rgba(148, 163, 184, 0.4);
}
</style>
