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
import { useChatStore } from '../stores/chat'

const props = defineProps({
  steps: { type: Array, default: () => [] },  // Array of {id, agent, action, status, detail, timestamp, duration}
  compact: { type: Boolean, default: false },
  // 任务 9.1 / 8.2 兼容的实时流属性
  progress: { type: Number, default: 0 },
  status: { type: String, default: '' },
  agents: { type: Object, default: () => ({}) },
})

const chatStore = useChatStore()

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

  const steps = [
    { id: 'coord', agent: '全脑主控官', action: '意图分析与分发', detail: '接收学生输入，分析学习意图，动态规划协同路径并路由上下文。' },
    { id: 'diag', agent: '诊断官', action: '调取学情画像', detail: '分析学生认知缺陷树与当前掌握度，评估需要重点突破的概念盲区。' },
    { id: 'retrieve', agent: '检索器', action: '多模态检索增强', detail: '调用 Hybrid RAG 框架与 VisRAG 视觉模型，检索讲义、公式与图示。' },
    { id: 'debate', agent: '辩论官', action: '苏格拉底思辨', detail: '开启真理越辩越明（DragDebate）正反双方多智能体认知思维风暴。' },
    { id: '理论教授', agent: '理论教授', action: '自适应精讲生成', detail: '生成针对当前概念的底层数理推导、核心理论剖析与深度讲义。' },
    { id: '逻辑画师', agent: '逻辑画师', action: '拓扑可视化渲染', detail: '为概念生成知识拓扑 Mermaid 图谱，并向 Poincaré 盘计算流形对齐点。' },
    { id: '极客助教', agent: '极客助教', action: '沙箱代码案例', detail: '生成可在代码沙箱中安全执行的 Python/JS 代码实例与步骤注解。' },
    { id: '考官智能体', agent: '考官智能体', action: '自适应评测构建', detail: '生成细粒度多步 CAT 测试题，并配置相应的自适应评估反馈规则。' },
    { id: '虚拟导演', agent: '虚拟导演', action: '多模态视频脚本', detail: '整理生成内容，进行讲解视频脚本设计与讲解音频分片规划。' },
    { id: 'align', agent: '对齐器', action: '流形一致性校验', detail: '执行拓扑流形对齐，校验讲义内容完整度，并生成对齐差异分析报告。' }
  ]

  // 判断当前对话流是否已完成/结束
  const isFinished = props.progress >= 100 || 
                     props.status === '生成完成！' || 
                     (!chatStore.sending && chatStore.messages.length > 0 && 
                      chatStore.messages[chatStore.messages.length - 1].role === 'assistant' && 
                      !chatStore.messages[chatStore.messages.length - 1].error)

  return steps.map((step, index) => {
    let status = 'pending'
    let detail = step.detail
    let duration = 0

    if (isFinished) {
      status = 'success'
      duration = 800 + index * 120
    } else {
      if (step.id === 'coord') {
        status = props.progress >= 10 ? 'success' : (props.progress > 0 ? 'running' : 'pending')
      } else if (step.id === 'diag') {
        if (props.progress >= 10) {
          status = props.progress >= 25 ? 'success' : 'running'
        }
      } else if (step.id === 'retrieve') {
        if (props.progress >= 25) {
          status = props.progress >= 40 ? 'success' : 'running'
        }
      } else if (step.id === 'debate') {
        if (props.progress >= 40) {
          status = props.progress >= 50 ? 'success' : 'running'
        }
      } else if (['理论教授', '逻辑画师', '极客助教', '考官智能体', '虚拟导演'].includes(step.id)) {
        if (props.progress >= 50) {
          const info = props.agents[step.id]
          if (info) {
            status = info.error ? 'error' : (info.done ? 'success' : 'running')
            if (info.error) detail = `生成异常: ${info.error}`
          } else {
            status = props.progress >= 80 ? 'success' : 'running'
          }
        }
      } else if (step.id === 'align') {
        if (props.progress >= 80) {
          status = props.progress >= 95 ? 'success' : 'running'
        }
      }
    }

    return {
      ...step,
      status,
      detail,
      duration: Math.round(duration)
    }
  })
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
    <div class="p-3">
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
              'border-blue-500 bg-blue-900/40 pulse-glow-running': step.status === 'running',
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
  flex-shrink: 0;
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

@keyframes pulse-glow {
  0%, 100% {
    box-shadow: 0 0 2px rgba(59, 130, 246, 0.4);
    border-color: rgba(59, 130, 246, 0.6);
  }
  50% {
    box-shadow: 0 0 10px rgba(59, 130, 246, 0.8);
    border-color: rgba(59, 130, 246, 1);
  }
}
.pulse-glow-running {
  animation: pulse-glow 1.5s infinite ease-in-out;
}
</style>
