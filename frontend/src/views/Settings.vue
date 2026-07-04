<script setup>
import { ref, onMounted } from 'vue'
import { Settings, Save, Key, Globe, Cpu, Thermometer, Eye, EyeOff, CheckCircle2, Sparkles, AlertTriangle, Loader2, Zap } from '@lucide/vue'
import axios from 'axios'

const showKey = ref(false)
const saved = ref(false)
const testing = ref(false)
const testResult = ref(null)

// 任务 9.2: 教学风格与致谢墙
const teachingStyle = ref(localStorage.getItem('edumatrix_teaching_style') || 'socratic')
const styleSaved = ref(false)
const showCredits = ref(false)

const credits = [
  { name: 'FastAPI', license: 'MIT', description: '高性能异步 Python Web 框架' },
  { name: 'SQLAlchemy', license: 'MIT', description: 'Python SQL 工具包与 ORM' },
  { name: 'Vue 3', license: 'MIT', description: '渐进式前端框架' },
  { name: 'Vite', license: 'MIT', description: '下一代前端构建工具' },
  { name: 'Tailwind CSS', license: 'MIT', description: '实用优先的 CSS 框架' },
  { name: 'ECharts', license: 'Apache-2.0', description: '数据可视化图表库' },
  { name: 'MathJax', license: 'Apache-2.0', description: '数学公式渲染引擎' },
  { name: 'KaTeX', license: 'MIT', description: '快速数学公式渲染库' },
  { name: 'FAISS', license: 'MIT', description: '向量相似度搜索库' },
  { name: 'PyMuPDF', license: 'AGPL-3.0', description: 'PDF 文档处理库' },
  { name: 'SQLite', license: 'Public Domain', description: '轻量级嵌入式数据库' },
  { name: 'Lucide', license: 'ISC', description: '开源图标库' },
]

function saveTeachingStyle() {
  localStorage.setItem('edumatrix_teaching_style', teachingStyle.value)
  styleSaved.value = true
  setTimeout(() => { styleSaved.value = false }, 3000)
}

const config = ref({
  apiKey: '',
  endpoint: 'https://ark.cn-beijing.volces.com/api/v3/chat/completions',
  model: 'doubao-seed-2.0-pro',
  temperature: 0.3,
  maxTokens: 4096,
  xfAppId: '',
  xfApiKey: '',
  xfApiSecret: '',
})

function save(silent = false) {
  localStorage.setItem('edumatrix_llm_config', JSON.stringify({
    apiKey: config.value.apiKey,
    endpoint: config.value.endpoint,
    model: config.value.model,
    temperature: config.value.temperature,
    maxTokens: config.value.maxTokens,
    xfAppId: config.value.xfAppId,
    xfApiKey: config.value.xfApiKey,
    xfApiSecret: config.value.xfApiSecret,
  }))
  if (!silent) {
    saved.value = true
    setTimeout(() => { saved.value = false }, 3000)
  }
}

const autoSaved = ref(false)
let autoSaveTimer = null
function triggerAutoSave() {
  save(true)
  autoSaved.value = true
  if (autoSaveTimer) clearTimeout(autoSaveTimer)
  autoSaveTimer = setTimeout(() => { autoSaved.value = false }, 1500)
}

function load() {
  try {
    const raw = localStorage.getItem('edumatrix_llm_config')
    if (raw) {
      const parsed = JSON.parse(raw)
      let needsSave = false
      if (parsed.temperature === undefined) {
        parsed.temperature = 0.3
        needsSave = true
      }
      if (parsed.maxTokens === undefined) {
        parsed.maxTokens = 4096
        needsSave = true
      }
      Object.assign(config.value, parsed)
      if (needsSave) {
        save(true)
      }
    } else {
      save(true)
    }
  } catch {}
}

function clearKey() {
  config.value.apiKey = ''
  save()
}

async function testConnection() {
  testing.value = true
  testResult.value = null
  try {
    const headers = {}
    if (config.value.apiKey) headers['X-EduMatrix-Api-Key'] = config.value.apiKey
    if (config.value.endpoint) headers['X-EduMatrix-Endpoint'] = config.value.endpoint
    if (config.value.model) headers['X-EduMatrix-Model'] = config.value.model

    const r = await axios.get('/api/llm/test', { headers, timeout: 30000 })
    testResult.value = r.data
  } catch (e) {
    testResult.value = {
      status: 'error',
      message: `请求失败: ${e.message || '网络错误'}`,
    }
  } finally {
    testing.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="max-w-2xl mx-auto">
    <div class="flex items-center gap-3 mb-6">
      <Settings :size="24" class="text-gray-700" />
      <div>
        <h2 class="text-lg font-semibold text-gray-800">LLM 设置</h2>
        <p class="text-xs text-gray-400 mt-0.5">配置 API Key 后自动使用真实大模型，否则使用内置模拟引擎</p>
      </div>
    </div>

    <div v-if="saved" class="mb-4 flex items-center gap-2 text-sm text-emerald-600 bg-emerald-50 px-4 py-2.5 rounded-lg">
      <CheckCircle2 :size="16" />
      <span>配置已保存</span>
    </div>

    <div class="card space-y-5">
      <!-- API Key -->
      <div>
        <label class="flex items-center gap-1.5 text-sm font-medium text-gray-700 mb-1.5">
          <Key :size="14" />
          API Key
          <span v-if="autoSaved" class="text-[10px] text-emerald-600 font-normal ml-2 animate-pulse bg-emerald-50 px-1.5 py-0.5 rounded border border-emerald-200/50">已实时保存</span>
        </label>
        <div class="flex gap-2">
          <div class="relative flex-1">
            <input
              v-model="config.apiKey"
              :type="showKey ? 'text' : 'password'"
              class="input pr-9"
              placeholder="sk-... 留空使用模拟引擎"
              @input="triggerAutoSave"
            />
            <button
              class="absolute right-2.5 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600"
              @click="showKey = !showKey"
            >
              <Eye v-if="!showKey" :size="16" />
              <EyeOff v-else :size="16" />
            </button>
          </div>
          <button v-if="config.apiKey" class="btn btn-outline text-xs shrink-0" @click="clearKey">清除</button>
        </div>
        <p class="text-[11px] text-gray-400 mt-1">支持任意 OpenAI 兼容接口的 API Key</p>
      </div>

      <!-- Endpoint -->
      <div>
        <label class="flex items-center gap-1.5 text-sm font-medium text-gray-700 mb-1.5">
          <Globe :size="14" />
          API Endpoint
          <span v-if="autoSaved" class="text-[10px] text-emerald-600 font-normal ml-2 animate-pulse bg-emerald-50 px-1.5 py-0.5 rounded border border-emerald-200/50">已实时保存</span>
        </label>
        <input v-model="config.endpoint" class="input" placeholder="https://api.openai.com/v1/chat/completions" @input="triggerAutoSave" />
      </div>

      <!-- Model -->
      <div>
        <label class="flex items-center gap-1.5 text-sm font-medium text-gray-700 mb-1.5">
          <Cpu :size="14" />
          模型名称
          <span v-if="autoSaved" class="text-[10px] text-emerald-600 font-normal ml-2 animate-pulse bg-emerald-50 px-1.5 py-0.5 rounded border border-emerald-200/50">已实时保存</span>
        </label>
        <input v-model="config.model" class="input" placeholder="gpt-4o-mini" @input="triggerAutoSave" />
      </div>

      <!-- Temperature -->
      <div>
        <label class="flex items-center gap-1.5 text-sm font-medium text-gray-700 mb-1.5">
          <Thermometer :size="14" />
          Temperature ({{ config.temperature }})
          <span v-if="autoSaved" class="text-[10px] text-emerald-600 font-normal ml-2 animate-pulse bg-emerald-50 px-1.5 py-0.5 rounded border border-emerald-200/50">已实时保存</span>
        </label>
        <input v-model.number="config.temperature" type="range" min="0" max="1" step="0.05" class="w-full" @input="triggerAutoSave" />
        <div class="flex justify-between text-[10px] text-gray-400 mt-0.5">
          <span>精确 (0)</span>
          <span>创造性 (1)</span>
        </div>
      </div>

      <!-- Max Tokens -->
      <div>
        <label class="text-sm font-medium text-gray-700 mb-1.5 flex items-center justify-between">
          <span>Max Tokens ({{ config.maxTokens }})</span>
          <span v-if="autoSaved" class="text-[10px] text-emerald-600 font-normal animate-pulse bg-emerald-50 px-1.5 py-0.5 rounded border border-emerald-200/50">已实时保存</span>
        </label>
        <input v-model.number="config.maxTokens" type="range" min="512" max="8192" step="512" class="w-full" @input="triggerAutoSave" />
      </div>

      <div class="border-t border-gray-100 pt-5">
        <h3 class="text-sm font-bold text-gray-800 mb-4 flex items-center gap-2">
          <Sparkles :size="16" class="text-blue-500" />
          科大讯飞 TTS 设置
          <span v-if="autoSaved" class="text-[10px] text-emerald-600 font-normal ml-2 animate-pulse bg-emerald-50 px-1.5 py-0.5 rounded border border-emerald-200/50">已实时保存</span>
        </h3>
        
        <div class="space-y-4">
          <div>
            <label class="text-xs font-medium text-gray-600 mb-1.5 block">APPID</label>
            <input v-model="config.xfAppId" class="input text-sm" placeholder="讯飞控制台获取的 APPID" @input="triggerAutoSave" />
          </div>
          <div>
            <label class="text-xs font-medium text-gray-600 mb-1.5 block">API Key</label>
            <input v-model="config.xfApiKey" class="input text-sm" placeholder="讯飞控制台获取的 API Key" @input="triggerAutoSave" />
          </div>
          <div>
            <label class="text-xs font-medium text-gray-600 mb-1.5 block">API Secret</label>
            <input v-model="config.xfApiSecret" type="password" class="input text-sm" placeholder="讯飞控制台获取的 API Secret" @input="triggerAutoSave" />
          </div>
        </div>
      </div>

      <div class="pt-2 flex gap-2">
        <button class="btn btn-primary flex-1 justify-center" @click="save">
          <Save :size="16" />
          保存配置
        </button>
        <button class="btn btn-outline flex-1 justify-center" :disabled="testing" @click="testConnection">
          <Loader2 v-if="testing" :size="16" class="animate-spin" />
          <Zap v-else :size="16" />
          测试连接
        </button>
      </div>

      <!-- 测试结果 -->
      <div v-if="testResult" class="mt-3 p-3 rounded-lg text-xs" :class="testResult.status === 'ok' ? 'bg-emerald-50 text-emerald-700 border border-emerald-200' : testResult.status === 'warning' ? 'bg-yellow-50 text-yellow-700 border border-yellow-200' : 'bg-red-50 text-red-700 border border-red-200'">
        <div class="flex items-center gap-1.5 mb-1">
          <CheckCircle2 v-if="testResult.status === 'ok'" :size="14" />
          <AlertTriangle v-else :size="14" />
          <span class="font-medium">{{ testResult.message }}</span>
        </div>
        <div v-if="testResult.hint" class="text-gray-500 mt-1">{{ testResult.hint }}</div>
        <div v-if="testResult.response" class="text-gray-500 mt-1 truncate">回复: {{ testResult.response }}</div>
        <div v-if="testResult.endpoint" class="text-gray-400 mt-1">端点: {{ testResult.endpoint }} / {{ testResult.model }}</div>
      </div>
    </div>

    <!-- Status -->
    <div class="card mt-4">
      <p class="text-sm font-medium text-gray-700 mb-2">当前状态</p>
      <div class="space-y-1.5 text-xs">
        <div class="flex items-center gap-2">
          <div class="w-2 h-2 rounded-full" :class="config.apiKey ? 'bg-emerald-500' : 'bg-gray-300'"></div>
          <span class="text-gray-600">{{ config.apiKey ? 'API Key 已配置' : '使用模拟引擎' }}</span>
        </div>
        <div class="flex items-center gap-2">
          <div class="w-2 h-2 rounded-full bg-blue-500"></div>
          <span class="text-gray-600">Endpoint: {{ config.endpoint }}</span>
        </div>
        <div class="flex items-center gap-2">
          <div class="w-2 h-2 rounded-full bg-blue-500"></div>
          <span class="text-gray-600">Model: {{ config.model }}</span>
        </div>
      </div>
    </div>

    <!-- 任务 9.2: 教学风格切换 -->
    <div class="card mt-4">
      <h3 class="text-sm font-bold text-gray-800 mb-4 flex items-center gap-2">
        <Sparkles :size="16" class="text-purple-500" />
        教学风格偏好
      </h3>
      <div class="space-y-3">
        <label class="flex items-center gap-3 cursor-pointer">
          <input
            type="radio"
            v-model="teachingStyle"
            value="socratic"
            class="accent-purple-500"
            @change="saveTeachingStyle"
          />
          <div>
            <p class="text-sm font-medium text-gray-700">苏格拉底式启发答疑</p>
            <p class="text-xs text-gray-400">以追问和反问引导学生自己发现问题，培养批判性思维</p>
          </div>
        </label>
        <label class="flex items-center gap-3 cursor-pointer">
          <input
            type="radio"
            v-model="teachingStyle"
            value="formal"
            class="accent-blue-500"
            @change="saveTeachingStyle"
          />
          <div>
            <p class="text-sm font-medium text-gray-700">严肃严谨讲授</p>
            <p class="text-xs text-gray-400">以系统化、结构化的方式完整讲解知识点，侧重理论推导</p>
          </div>
        </label>
        <p v-if="styleSaved" class="text-xs text-emerald-600">教学风格已更新，将在下一次对话中生效</p>
      </div>
    </div>

    <!-- 任务 9.2: 开源致谢墙 -->
    <div class="card mt-4">
      <div class="flex items-center justify-between cursor-pointer" @click="showCredits = !showCredits">
        <h3 class="text-sm font-bold text-gray-800 flex items-center gap-2">
          <span class="text-lg">❤️</span>
          开源致谢墙
        </h3>
        <span class="text-xs text-gray-400">{{ showCredits ? '收起' : '展开' }}</span>
      </div>
      <div v-if="showCredits" class="mt-4 space-y-3">
        <p class="text-xs text-gray-500">EduMatrix 智教矩阵基于以下优秀的开源项目构建：</p>
        <div class="grid grid-cols-2 gap-2">
          <div v-for="dep in credits" :key="dep.name" class="bg-gray-50 rounded-lg p-2.5">
            <p class="text-xs font-medium text-gray-700">{{ dep.name }}</p>
            <p class="text-[10px] text-gray-400">{{ dep.license }}</p>
            <p class="text-[10px] text-gray-400 truncate">{{ dep.description }}</p>
          </div>
        </div>
        <p class="text-[10px] text-gray-400 mt-2">EduMatrix 遵循 Apache 2.0 开源协议发布</p>
      </div>
    </div>
  </div>
</template>