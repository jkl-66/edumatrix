<script setup>
import { computed } from 'vue'
import { CheckCircle2, Loader2 } from '@lucide/vue'

const props = defineProps({
  progress: { type: Number, default: 0 },
  status: { type: String, default: '' },
  agents: { type: Object, default: () => ({}) }
})

const steps = [
  { id: 'intent', label: '意图识别', threshold: 15 },
  { id: 'search', label: '联网搜索', threshold: 30 },
  { id: 'theory', label: '理论教授', agent: '理论教授' },
  { id: 'logic', label: '逻辑画师', agent: '逻辑画师' },
  { id: 'geek', label: '极客助教', agent: '极客助教' },
  { id: 'quiz', label: '考官智能体', agent: '考官智能体' },
  { id: 'summary', label: '内容汇总', threshold: 95 }
]

const currentStepIndex = computed(() => {
  if (props.progress >= 100) return steps.length
  
  // Find based on agent status first
  for (let i = steps.length - 1; i >= 0; i--) {
    const s = steps[i]
    if (s.agent && props.agents[s.agent]?.done) return i + 1
    if (s.threshold && props.progress >= s.threshold) return i + 1
  }
  return 0
})

function getStepState(index) {
  if (index < currentStepIndex.value) return 'done'
  if (index === currentStepIndex.value && props.progress > 0 && props.progress < 100) return 'active'
  return 'pending'
}
</script>

<template>
  <div class="space-y-4">
    <div class="flex items-center gap-2 mb-4">
      <div class="w-1 h-4 bg-blue-600 rounded-full"></div>
      <h3 class="text-sm font-semibold text-gray-800">智能体协作轨迹</h3>
    </div>

    <div class="relative pl-6 space-y-6">
      <!-- Line -->
      <div class="absolute left-[11px] top-2 bottom-2 w-0.5 bg-gray-100">
        <div 
          class="w-full bg-blue-500 transition-all duration-500" 
          :style="{ height: (currentStepIndex / steps.length * 100) + '%' }"
        />
      </div>

      <div v-for="(step, i) in steps" :key="step.id" class="relative flex items-start gap-3">
        <!-- Dot -->
        <div class="absolute -left-[20px] mt-1 flex items-center justify-center">
          <div v-if="getStepState(i) === 'done'" class="text-blue-500 bg-white">
            <CheckCircle2 :size="18" />
          </div>
          <div v-else-if="getStepState(i) === 'active'" class="relative">
            <div class="w-4 h-4 bg-blue-500 rounded-full breathing-light"></div>
            <div class="absolute inset-0 w-4 h-4 bg-blue-400 rounded-full animate-ping opacity-75"></div>
          </div>
          <div v-else class="w-4 h-4 rounded-full border-2 border-gray-200 bg-white"></div>
        </div>

        <div class="flex-1 min-w-0">
          <p class="text-xs font-medium transition-colors duration-300" 
            :class="getStepState(i) === 'pending' ? 'text-gray-400' : 'text-gray-700'">
            {{ step.label }}
          </p>
          <p v-if="getStepState(i) === 'active'" class="text-[10px] text-blue-500 mt-0.5 animate-pulse">
            {{ status || '正在处理...' }}
          </p>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.breathing-light {
  box-shadow: 0 0 0 0 rgba(37, 99, 235, 0.7);
  animation: breathe 2s infinite cubic-bezier(0.4, 0, 0.6, 1);
}

@keyframes breathe {
  0% {
    transform: scale(0.9);
    box-shadow: 0 0 0 0 rgba(37, 99, 235, 0.7);
  }
  70% {
    transform: scale(1.1);
    box-shadow: 0 0 0 10px rgba(37, 99, 235, 0);
  }
  100% {
    transform: scale(0.9);
    box-shadow: 0 0 0 0 rgba(37, 99, 235, 0);
  }
}
</style>
