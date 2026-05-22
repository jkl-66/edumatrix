<script setup>
import { ref, nextTick } from 'vue'
import { processMessage, getHistory } from '../api'
import {
  Send, Bot, User, Loader2, BookOpen, Code2, LayoutGrid, HelpCircle, Video,
  CheckCircle2, XCircle, AlertTriangle, ChevronDown, ChevronUp
} from '@lucide/vue'

const props = defineProps({ studentId: String })

const messages = ref([])
const input = ref('')
const sending = ref(false)
const showResources = ref(new Set())
const showProfile = ref(false)

// Preset questions
const presets = [
  '什么是机器学习？',
  '过拟合的表现和正则化方法？',
  '什么是逻辑回归？sigmoid函数如何工作？',
  '最大池化和平均池化的区别？我总混淆',
]

async function send() {
  const text = input.value.trim()
  if (!text || sending.value) return
  input.value = ''
  sending.value = true

  messages.value.push({ role: 'user', content: text })
  await nextTick()

  try {
    const data = await processMessage(text, props.studentId)
    const agentOutputs = data.resources || []
    const alignment = data.alignment || {}
    const signal = data.learning_signal || {}

    messages.value.push({
      role: 'assistant',
      content: `## 学习目标：${data.target || '未识别'}\n\n` +
        (alignment.passed ? '✅ 多模态内容一致性校验通过' : `⚠️ 内容一致性需优化: ${alignment.advice || ''}`) +
        (data.strategy_plan?.actions?.length ? `\n\n**推荐学习策略：**\n${data.strategy_plan.actions.map((a, i) => `${i+1}. ${a.description || a}`).join('\n')}` : ''),
      resources: agentOutputs,
      alignment,
      signal,
      profile: data.profile,
      strategy: data.strategy_plan,
    })
  } catch (e) {
    messages.value.push({
      role: 'assistant',
      content: `❌ 请求失败：${e.message || '请检查后端服务是否运行'}`,
      error: true,
    })
  } finally {
    sending.value = false
  }
}

function toggleResource(idx) {
  const s = new Set(showResources.value)
  s.has(idx) ? s.delete(idx) : s.add(idx)
  showResources.value = s
}

const resourceIcons = {
  '专业讲义': BookOpen,
  '代码实操案例': Code2,
  '思维导图': LayoutGrid,
  '练习题': HelpCircle,
  '虚拟人视频脚本': Video,
}

function resourceIcon(type) {
  return resourceIcons[type] || BookOpen
}

function handleKeydown(e) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    send()
  }
}

function usePreset(text) {
  input.value = text
  send()
}
</script>

<template>
  <div class="flex flex-col h-full max-w-5xl mx-auto">
    <!-- Presets -->
    <div class="flex flex-wrap gap-2 mb-4">
      <button
        v-for="preset in presets"
        :key="preset"
        class="btn btn-outline text-xs py-1.5"
        @click="usePreset(preset)"
      >
        {{ preset.slice(0, 20) }}{{ preset.length > 20 ? '...' : '' }}
      </button>
    </div>

    <!-- Messages -->
    <div class="flex-1 overflow-y-auto space-y-4 mb-4 scrollbar-thin">
      <div v-if="messages.length === 0" class="flex flex-col items-center justify-center h-full text-center text-gray-400">
        <Bot :size="48" class="mb-3 text-gray-300" />
        <p class="text-sm font-medium">输入问题开始学习</p>
        <p class="text-xs mt-1">EduMatrix 将调用 9 个智能体为你生成完整教学资源</p>
      </div>

      <div v-for="(msg, idx) in messages" :key="idx">
        <!-- User message -->
        <div v-if="msg.role === 'user'" class="flex justify-end mb-3">
          <div class="max-w-[75%] bg-blue-600 text-white rounded-2xl rounded-br-sm px-4 py-2.5">
            <p class="text-sm whitespace-pre-wrap">{{ msg.content }}</p>
          </div>
        </div>

        <!-- Assistant message -->
        <div v-else class="mb-4">
          <div class="flex items-start gap-3">
            <div class="w-8 h-8 rounded-xl bg-gradient-to-br from-blue-500 to-purple-600 flex items-center justify-center shrink-0">
              <Bot :size="16" class="text-white" />
            </div>
            <div class="flex-1 min-w-0">
              <div class="card">
                <div class="prose prose-sm max-w-none" v-html="msg.content.replace(/\n/g, '<br>')"></div>
              </div>

              <!-- Strategy -->
              <div v-if="msg.strategy?.actions?.length" class="mt-2 flex flex-wrap gap-2">
                <span v-for="(action, ai) in msg.strategy.actions" :key="ai" class="badge bg-blue-50 text-blue-700 text-[10px]">
                  {{ (action.description || action).slice(0, 40) }}{{ (action.description || action).length > 40 ? '...' : '' }}
                </span>
              </div>

              <!-- Resources -->
              <div v-if="msg.resources?.length" class="mt-3 space-y-1.5">
                <div
                  v-for="(res, ri) in msg.resources"
                  :key="ri"
                  class="border border-gray-200 rounded-lg overflow-hidden"
                >
                  <div
                    class="flex items-center justify-between px-3 py-2 cursor-pointer hover:bg-gray-50 transition-colors"
                    @click="toggleResource(ri)"
                  >
                    <div class="flex items-center gap-2 min-w-0">
                      <component :is="resourceIcon(res.resource_type)" :size="14" class="text-gray-500 shrink-0" />
                      <span class="text-xs font-medium text-gray-700 truncate">{{ res.resource_type || res.agent }}</span>
                      <span v-if="res.citations?.length" class="text-[10px] text-gray-400">引用{{ res.citations.length }}条</span>
                    </div>
                    <ChevronDown v-if="!showResources.has(ri)" :size="14" class="text-gray-400 shrink-0" />
                    <ChevronUp v-else :size="14" class="text-gray-400 shrink-0" />
                  </div>
                  <div v-if="showResources.has(ri)" class="px-3 py-2 border-t border-gray-100 bg-gray-50/50">
                    <p class="text-xs text-gray-700 whitespace-pre-wrap font-mono leading-relaxed">{{ res.content.slice(0, 1000) }}{{ res.content.length > 1000 ? '...' : '' }}</p>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- Typing indicator -->
      <div v-if="sending" class="flex items-start gap-3 mb-4">
        <div class="w-8 h-8 rounded-xl bg-gradient-to-br from-blue-500 to-purple-600 flex items-center justify-center shrink-0">
          <Bot :size="16" class="text-white" />
        </div>
        <div class="flex items-center gap-2 text-gray-400 text-sm">
          <Loader2 :size="16" class="animate-spin" />
          正在生成 5 路资源...
        </div>
      </div>
    </div>

    <!-- Input -->
    <div class="flex items-end gap-2 bg-white border border-gray-200 rounded-xl p-2">
      <textarea
        v-model="input"
        class="flex-1 resize-none outline-none text-sm px-2 py-1.5 max-h-32"
        placeholder="输入你的学习问题..."
        rows="1"
        @keydown="handleKeydown"
      />
      <button
        class="btn btn-primary shrink-0"
        :disabled="!input.trim() || sending"
        @click="send"
      >
        <Send :size="16" />
      </button>
    </div>
  </div>
</template>
