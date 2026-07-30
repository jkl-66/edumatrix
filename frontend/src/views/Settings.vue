<script setup>
import { ref, onMounted } from 'vue'
import { Settings, CheckCircle2, Sparkles, AlertTriangle, Loader2, Zap, ShieldCheck } from '@lucide/vue'
import { api, buildHeaders } from '../api/common'

const testing = ref(false)
const testResult = ref(null)
const health = ref(null)
const teachingStyle = ref(localStorage.getItem('edumatrix_teaching_style') || 'socratic')
const styleSaved = ref(false)
const showCredits = ref(false)

const credits = [
  ['FastAPI', 'MIT'], ['SQLAlchemy', 'MIT'], ['Vue 3', 'MIT'],
  ['Vite', 'MIT'], ['Tailwind CSS', 'MIT'], ['ECharts', 'Apache-2.0'],
  ['MathJax', 'Apache-2.0'], ['KaTeX', 'MIT'], ['FAISS', 'MIT'],
  ['PyMuPDF', 'AGPL-3.0'], ['SQLite', 'Public Domain'], ['Lucide', 'ISC'],
]

function saveTeachingStyle() {
  localStorage.setItem('edumatrix_teaching_style', teachingStyle.value)
  styleSaved.value = true
  setTimeout(() => { styleSaved.value = false }, 3000)
}

async function loadHealth() {
  try {
    health.value = (await api.get('/health')).data
  } catch {
    health.value = { status: 'unavailable', dependencies: {} }
  }
}

async function testConnection() {
  testing.value = true
  testResult.value = null
  try {
    testResult.value = (await api.get('/llm/test', { headers: buildHeaders(), timeout: 30000 })).data
  } catch (error) {
    testResult.value = { status: 'error', message: error.detail || '后端模型连接测试失败' }
  } finally {
    testing.value = false
    await loadHealth()
  }
}

onMounted(() => {
  // Remove secrets persisted by releases that predate backend-only key handling.
  localStorage.removeItem('edumatrix_llm_config')
  loadHealth()
})
</script>

<template>
  <div class="max-w-2xl mx-auto">
    <div class="flex items-center gap-3 mb-6">
      <Settings :size="24" class="text-gray-700" />
      <div>
        <h2 class="text-lg font-semibold text-gray-800">系统与学习偏好</h2>
        <p class="text-xs text-gray-400 mt-0.5">模型凭证只由管理员在后端环境或密钥管理器配置</p>
      </div>
    </div>

    <div class="card space-y-4">
      <div class="flex items-start gap-3 rounded-lg bg-blue-50 p-3 text-sm text-blue-800">
        <ShieldCheck :size="19" class="mt-0.5 shrink-0" />
        <div>
          <p class="font-medium">浏览器不保存或发送模型密钥</p>
          <p class="mt-1 text-xs text-blue-600">请在部署环境中设置 EDUMATRIX_LLM_* 与多模态变量，修改后重启后端。</p>
        </div>
      </div>

      <div v-if="health" class="grid grid-cols-2 gap-2 text-xs">
        <div v-for="(item, key) in health.dependencies" :key="key" class="rounded-lg border border-gray-100 p-2.5">
          <div class="flex items-center gap-2">
            <span class="h-2 w-2 rounded-full" :class="item.available ? 'bg-emerald-500' : 'bg-gray-300'"></span>
            <span class="text-gray-600">{{ key }}</span>
          </div>
          <p v-if="item.mode" class="mt-1 text-[10px] text-gray-400">{{ item.mode }}</p>
        </div>
      </div>

      <button class="btn btn-outline w-full justify-center" :disabled="testing" @click="testConnection">
        <Loader2 v-if="testing" :size="16" class="animate-spin" />
        <Zap v-else :size="16" />
        测试后端文本模型
      </button>
      <div v-if="testResult" class="rounded-lg border p-3 text-xs" :class="testResult.status === 'ok' ? 'border-emerald-200 bg-emerald-50 text-emerald-700' : 'border-amber-200 bg-amber-50 text-amber-700'">
        <div class="flex items-center gap-1.5">
          <CheckCircle2 v-if="testResult.status === 'ok'" :size="14" />
          <AlertTriangle v-else :size="14" />
          <span class="font-medium">{{ testResult.message }}</span>
        </div>
        <p v-if="testResult.hint" class="mt-1">{{ testResult.hint }}</p>
      </div>
    </div>

    <div class="card mt-4">
      <h3 class="mb-4 flex items-center gap-2 text-sm font-bold text-gray-800">
        <Sparkles :size="16" class="text-purple-500" /> 教学风格偏好
      </h3>
      <div class="space-y-3">
        <label v-for="option in [{ value: 'socratic', title: '苏格拉底式启发答疑', detail: '以追问引导思考' }, { value: 'formal', title: '严谨系统讲授', detail: '侧重结构化讲解与理论推导' }]" :key="option.value" class="flex cursor-pointer items-center gap-3">
          <input v-model="teachingStyle" type="radio" :value="option.value" class="accent-purple-500" @change="saveTeachingStyle" />
          <div><p class="text-sm font-medium text-gray-700">{{ option.title }}</p><p class="text-xs text-gray-400">{{ option.detail }}</p></div>
        </label>
        <p v-if="styleSaved" class="text-xs text-emerald-600">教学风格已更新</p>
      </div>
    </div>

    <div class="card mt-4">
      <div class="flex cursor-pointer items-center justify-between" @click="showCredits = !showCredits">
        <h3 class="text-sm font-bold text-gray-800">❤️ 开源致谢墙</h3>
        <span class="text-xs text-gray-400">{{ showCredits ? '收起' : '展开' }}</span>
      </div>
      <div v-if="showCredits" class="mt-4 grid grid-cols-2 gap-2">
        <div v-for="dep in credits" :key="dep[0]" class="rounded-lg bg-gray-50 p-2.5">
          <p class="text-xs font-medium text-gray-700">{{ dep[0] }}</p><p class="text-[10px] text-gray-400">{{ dep[1] }}</p>
        </div>
      </div>
    </div>
  </div>
</template>
