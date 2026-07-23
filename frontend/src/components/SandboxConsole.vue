<script setup>
/**
 * SandboxConsole.vue — 任务 8.4: Docker 代码沙箱控制台
 *
 * 独立可拖拽代码编辑器 + 实时渲染运行输出流 + Base64 矢量图展示
 */
import { ref, computed, watch, nextTick, onMounted } from 'vue'
import { getCodeStatus, runCode } from '../api'
import { Play, Trash2, Copy, Check, Terminal, Loader2 } from '@lucide/vue'

const props = defineProps({
  studentId: { type: String, default: 'default' },
  initialCode: { type: String, default: 'import numpy as np\nprint("Hello, EduMatrix!")' },
})

const emit = defineEmits(['output', 'error'])

// --- State ---
const code = ref(props.initialCode)
const output = ref('')
const errorMsg = ref('')
const running = ref(false)
const execTime = ref(0)
const history = ref([])
const copied = ref(false)
const showViz = ref(false)
const minimized = ref(false)
const sandboxReady = ref(false)
const sandboxMessage = ref('正在检查代码沙箱状态...')
const sandboxMode = ref('disabled')
const sandboxIsolation = ref('none')
const isTrustedLocal = computed(() => sandboxMode.value === 'trusted_local')
const sandboxLabel = computed(() => {
  if (sandboxMode.value === 'trusted_local') return '本地研究模式'
  if (sandboxMode.value === 'docker') return 'Docker 模式'
  return '未启用'
})

// 代码预设
const presets = [
  { label: 'NumPy', code: 'import numpy as np\narr = np.array([[1,2],[3,4]])\nprint("Array:\\n", arr)\nprint("Mean:", np.mean(arr))' },
  { label: 'Matplotlib', code: 'import matplotlib.pyplot as plt\nimport numpy as np\nx = np.linspace(0, 10, 100)\nplt.plot(x, np.sin(x))\nplt.title("Sine Wave")\nplt.show()' },
  { label: '线性回归', code: 'from sklearn.linear_model import LinearRegression\nimport numpy as np\nX = np.array([[1],[2],[3],[4]])\ny = np.array([2,4,6,8])\nmodel = LinearRegression().fit(X, y)\nprint(f"y = {model.coef_[0]:.2f}x + {model.intercept_:.2f}")' },
]

// 解码 Base64 图片
const vizHtml = computed(() => {
  if (!output.value) return ''
  const out = output.value
  if (!out.includes('![可视化输出]')) return ''
  return out.replace(
    /!\[可视化输出\]\s*\(data:image\/png;base64,([^)]+)\)/gi,
    (_, b64) => {
      const cleanB64 = b64.replace(/\s+/g, '')
      return `<img src="data:image/png;base64,${cleanB64}" style="max-width:100%;border-radius:8px;margin:8px 0" />`
    }
  )
})

async function run() {
  if (!code.value.trim() || running.value) return
  if (!sandboxReady.value) {
    errorMsg.value = sandboxMessage.value
    return
  }
  running.value = true
  output.value = ''
  errorMsg.value = ''
  showViz.value = true
  const start = Date.now()

  try {
    const result = await runCode(code.value, 'python', props.studentId)
    output.value = result.output || ''
    errorMsg.value = result.error || ''
    execTime.value = result.execution_time_ms || (Date.now() - start)
    if (result.exec_id) {
      history.value.unshift({
        id: result.exec_id,
        code: code.value.slice(0, 80),
        time: execTime.value,
        has_error: !!result.error,
      })
      if (history.value.length > 20) history.value.pop()
    }
    emit('output', { output: output.value, error: errorMsg.value, time: execTime.value })
  } catch (e) {
    errorMsg.value = e.message || '执行出错'
    emit('error', e.message)
  } finally {
    running.value = false
  }
}

async function loadSandboxStatus() {
  try {
    const status = await getCodeStatus()
    sandboxReady.value = Boolean(status.execution_enabled)
    sandboxMode.value = status.mode || 'disabled'
    sandboxIsolation.value = status.isolation || 'none'
    sandboxMessage.value = status.message || '代码沙箱当前未启用'
  } catch (error) {
    sandboxReady.value = false
    sandboxMessage.value = '无法读取代码沙箱状态；当前不执行宿主机代码'
  }
}

function clearOutput() {
  output.value = ''
  errorMsg.value = ''
  showViz.value = false
}

function copyCode() {
  navigator.clipboard.writeText(code.value).then(() => {
    copied.value = true
    setTimeout(() => copied.value = false, 1500)
  })
}

function usePreset(p) {
  code.value = p.code
}

function handleKeydown(e) {
  if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
    e.preventDefault()
    run()
  }
}

const terminalRef = ref(null)

function scrollToBottom() {
  nextTick(() => {
    if (terminalRef.value) {
      terminalRef.value.scrollTop = terminalRef.value.scrollHeight
    }
  })
}

watch([output, errorMsg], () => {
  scrollToBottom()
})

watch(() => props.initialCode, (v) => {
  if (v) code.value = v
})

onMounted(loadSandboxStatus)
</script>

<template>
  <div class="sandbox-console bg-gray-900 border border-gray-700 rounded-lg overflow-hidden">
    <!-- 标题栏（可点击折叠） -->
    <div class="flex items-center justify-between px-3 py-2 bg-gray-800 border-b border-gray-700 cursor-pointer select-none"
      @click="minimized = !minimized">
      <div class="flex items-center gap-2">
        <Terminal :size="14" class="text-green-400" />
        <span class="text-xs font-medium text-gray-200">代码沙箱控制台</span>
        <span class="text-[10px] text-gray-400">{{ sandboxLabel }}</span>
        <span v-if="running" class="flex items-center gap-1 text-[10px] text-yellow-400">
          <Loader2 :size="10" class="animate-spin" /> 运行中...
        </span>
        <span v-else-if="execTime > 0" class="text-[10px] text-gray-500">{{ execTime }}ms</span>
      </div>
      <div class="flex items-center gap-1">
        <button @click.stop="run" :disabled="running || !sandboxReady"
          class="px-2 py-1 bg-green-700 hover:bg-green-600 disabled:opacity-50 rounded text-[10px] text-white transition-colors flex items-center gap-1">
          <Play :size="10" /> {{ sandboxReady ? '运行' : '沙箱未启用' }}
        </button>
        <button @click.stop="minimized = !minimized"
          class="text-gray-400 hover:text-white text-xs px-1">
          {{ minimized ? '▼' : '▲' }}
        </button>
      </div>
    </div>

    <div v-if="!sandboxReady" class="px-3 py-2 bg-amber-950/40 border-b border-amber-800/50 text-[10px] text-amber-300">
      {{ sandboxMessage }}。代码编辑、静态检查和资源查看仍可使用。
    </div>
    <div v-if="isTrustedLocal" class="px-3 py-2 bg-amber-950/40 border-b border-amber-800/50 text-[10px] text-amber-300">
      本地可信研究模式：代码在受限 Python 子进程中运行，不具备 Docker 容器隔离，仅适用于本机学术研究与比赛演示。
    </div>

    <!-- 代码预设（仅展开时显示） -->
    <div v-if="!minimized" class="flex gap-1 px-3 py-1.5 bg-gray-850 border-b border-gray-700 flex-wrap">
      <button v-for="p in presets" :key="p.label"
        @click="usePreset(p)" :disabled="running"
        class="px-2 py-0.5 bg-gray-700 hover:bg-gray-600 disabled:opacity-50 rounded text-[10px] text-gray-300 transition-colors">
        {{ p.label }}
      </button>
    </div>

    <!-- 编辑器 + 输出（双栏） -->
    <div v-if="!minimized" class="grid grid-cols-1 lg:grid-cols-2 gap-0">
      <!-- 代码编辑器 -->
      <div class="border-r border-gray-700">
        <textarea v-model="code"
          @keydown="handleKeydown"
          class="w-full h-48 bg-gray-950 text-green-300 text-xs font-mono p-3 resize-none outline-none border-none"
          placeholder="在此输入 Python 代码..."
          spellcheck="false"
        />
        <div class="flex items-center justify-between px-3 py-1 bg-gray-850 border-t border-gray-700">
          <span class="text-[10px] text-gray-500">{{ code.split('\n').length }} 行</span>
          <div class="flex gap-2">
            <button @click="copyCode" class="text-[10px] text-gray-400 hover:text-white flex items-center gap-1">
              <Copy :size="10" /> 复制
            </button>
            <button @click="clearOutput" class="text-[10px] text-gray-400 hover:text-white flex items-center gap-1">
              <Trash2 :size="10" /> 清空
            </button>
          </div>
        </div>
      </div>

      <!-- 输出终端 -->
      <div class="flex flex-col">
        <div ref="terminalRef" class="flex-1 h-48 overflow-y-auto bg-gray-950 p-3 font-mono text-xs">
          <div v-if="!output && !errorMsg" class="text-gray-600 italic">输出将在此显示...</div>
          <div v-if="errorMsg" class="text-red-400 whitespace-pre-wrap mb-2">{{ errorMsg }}</div>
          <div v-if="output" class="text-gray-200 whitespace-pre-wrap">
            <div v-if="!vizHtml" v-html="output.replace(/\n/g, '<br>')" />
            <div v-else v-html="vizHtml" />
          </div>
        </div>
        <!-- 状态栏 -->
        <div class="flex items-center justify-between px-3 py-1 bg-gray-850 border-t border-gray-700">
          <span class="text-[10px]" :class="errorMsg ? 'text-red-400' : 'text-green-400'">
            {{ errorMsg ? '异常退出' : running ? '运行中...' : execTime > 0 ? '正常退出' : '就绪' }}
          </span>
          <span v-if="execTime > 0" class="text-[10px] text-gray-500">{{ execTime }}ms</span>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.sandbox-console {
  box-shadow: 0 4px 12px rgba(0,0,0,0.3);
}
textarea:focus {
  border-color: transparent;
  box-shadow: none;
}
</style>
