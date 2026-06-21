<script setup>
/**
 * InlineSocraticPopup.vue — 任务 8.1: 行级/公式悬浮苏格拉底即时答疑
 *
 * 监听代码块/公式点击事件，提取行上下文，弹出轻量化悬浮推导窗口。
 * v2: 调用后端 /api/stream/explain 获取真实 AI 解释，LLM 不可用时回退到模板。
 */
import { ref, onMounted, onUnmounted, nextTick } from 'vue'
import { socraticExplain } from '../api'

const emit = defineEmits(['close'])

const props = defineProps({
  targetText: { type: String, default: '' },
  contextBefore: { type: String, default: '' },
  contextAfter: { type: String, default: '' },
  lineIndex: { type: Number, default: 0 },
  messageIndex: { type: Number, default: -1 },
  studentId: { type: String, default: 'demo-student' },
})

const visible = ref(true)
const steps = ref([])
const loading = ref(true)
const error = ref('')
const popupRef = ref(null)

// 调用后端 API 获取苏格拉底式解释
async function fetchSocraticExplanation() {
  if (!props.targetText) {
    steps.value = ['无法识别目标内容']
    loading.value = false
    return
  }
  try {
    const result = await socraticExplain({
      target_text: props.targetText,
      context_before: props.contextBefore,
      context_after: props.contextAfter,
      student_id: props.studentId,
    })
    if (result.status === 'success') {
      // 将返回的文本按行拆分为步骤
      const content = result.content || ''
      steps.value = content.split('\n').filter(line => line.trim())
    } else {
      // fallback 模板
      steps.value = (result.content || '').split('\n').filter(line => line.trim())
    }
  } catch (e) {
    error.value = e.message || '请求失败'
    // 本地兜底
    steps.value = generateFallback(props.targetText)
  }
  loading.value = false
}

// 本地兜底模板（仅 LLM 不可用时）
function generateFallback(text) {
  if (!text) return ['无法识别目标内容']
  const lines = []
  const isFormula = text.includes('\\frac') || text.includes('\\partial') || text.includes('$$')
  const isCode = text.includes('def ') || text.includes('import ') || text.includes('class ')
  if (isFormula) {
    lines.push('📐 这是一个数学表达式')
    if (text.includes('\\frac')) lines.push('📝 分数形式: \\frac{分子}{分母}')
    if (text.includes('\\partial')) lines.push('🎯 偏导符号 ∂ 表示偏导数')
    lines.push('')
    lines.push('💡 可追问: "每个符号表示什么？"')
  } else if (isCode) {
    lines.push('💻 这是一段代码语句')
    if (text.includes('def ')) lines.push('📦 函数定义: def 关键字声明代码块')
    else if (text.includes('import ')) lines.push('📚 import 用于引入外部库')
    lines.push('')
    lines.push('💡 可追问: "参数和返回值是什么？"')
  } else {
    lines.push('📖 选取内容: "' + text.slice(0, 60) + '"')
    lines.push('💡 可在主对话继续追问')
  }
  return lines
}

onMounted(async () => {
  await nextTick()
  await nextTick()
  await fetchSocraticExplanation()
})

function close() {
  visible.value = false
  emit('close')
}

function askDeeper() {
  steps.value = steps.value.concat([
    '',
    '--- 更深层推导 ---',
    `基于上下文: ${props.contextBefore.slice(0, 60)}...`,
    '💡 可在主对话框中继续追问详细推导',
  ])
}
</script>

<template>
  <Teleport to="body">
    <div v-if="visible" class="fixed inset-0 z-50 flex items-start justify-center pt-20"
      @click.self="close">
      <div ref="popupRef"
        class="inline-socratic-popup bg-gray-900 border border-gray-700 rounded-lg shadow-2xl w-[420px] max-h-[60vh] overflow-y-auto"
        @click.stop>
        <!-- 头部 -->
        <div class="flex items-center justify-between px-4 py-3 border-b border-gray-700">
          <span class="text-xs font-semibold text-purple-400">🧠 苏格拉底即时答疑</span>
          <button @click="close" class="text-gray-400 hover:text-white text-sm">&times;</button>
        </div>

        <!-- 被选中的内容 -->
        <div class="px-4 py-2 bg-gray-800/50 border-b border-gray-700">
          <p class="text-[10px] text-gray-500 mb-1">选中内容 (行 {{ lineIndex }})</p>
          <code class="text-xs text-yellow-300 break-all">{{ targetText.slice(0, 80) }}</code>
        </div>

        <!-- 推导步骤 -->
        <div class="p-4">
          <div v-if="loading" class="flex items-center gap-2 text-gray-400 text-xs">
            <div class="animate-spin w-3 h-3 border border-purple-500 border-t-transparent rounded-full" />
            正在推导...
          </div>
          <div v-if="error" class="text-xs text-red-400 mb-2">
            {{ error }}
          </div>
          <div v-else class="space-y-2">
            <div v-for="(step, i) in steps" :key="i"
              class="text-xs text-gray-300"
              :class="{ 'text-purple-300 font-medium': step.startsWith('💡') }">
              {{ step }}
            </div>
            <button @click="askDeeper"
              class="mt-3 px-3 py-1.5 bg-purple-600 hover:bg-purple-700 text-white rounded text-xs transition-colors">
              继续推导
            </button>
          </div>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.inline-socratic-popup {
  animation: slideDown 0.2s ease-out;
}
@keyframes slideDown {
  from { opacity: 0; transform: translateY(-8px); }
  to { opacity: 1; transform: translateY(0); }
}
</style>
