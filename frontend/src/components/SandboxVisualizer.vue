<script setup>
/**
 * SandboxVisualizer.vue — 浮动代码沙箱可视化窗
 * 选择图表类型→自动生成代码→运行→显示图像→生成讲解
 */
import { ref, computed } from 'vue'

const emit = defineEmits(['close'])
const props = defineProps({ studentId: { type: String, default: 'demo-student' } })

const visible = ref(true)
const activeChart = ref('line')
const code = ref('')
const output = ref('')
const imageUrl = ref('')
const running = ref(false)
const explaining = ref(false)
const explanation = ref('')
const error = ref('')

const chartTypes = [
  { id: 'line', label: '折线图', icon: '📈' },
  { id: 'bar', label: '柱状图', icon: '📊' },
  { id: 'scatter', label: '散点图', icon: '🔵' },
  { id: 'function', label: '函数曲线', icon: '📐' },
  { id: '3d', label: '3D 图', icon: '🧊' },
]

const chartCode = {
  line: `import matplotlib.pyplot as plt
import numpy as np

x = np.linspace(0, 10, 50)
y1 = np.sin(x)
y2 = np.cos(x)

plt.figure(figsize=(8, 4))
plt.plot(x, y1, 'b-', label='sin(x)', linewidth=2)
plt.plot(x, y2, 'r--', label='cos(x)', linewidth=2)
plt.xlabel('x')
plt.ylabel('y')
plt.title('正弦与余弦曲线')
plt.legend()
plt.grid(alpha=0.3)
plt.tight_layout()
plt.show()`,

  bar: `import matplotlib.pyplot as plt
import numpy as np

categories = ['线性回归', '决策树', 'SVM', 'CNN', 'RNN']
scores = [85, 72, 68, 91, 78]

colors = ['#4f86c6', '#6c9fd8', '#89b8ea', '#a3d1fc', '#bde8ff']
plt.figure(figsize=(8, 4))
bars = plt.bar(categories, scores, color=colors, edgecolor='white', linewidth=1.5)
for bar, score in zip(bars, scores):
    plt.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 1,
             str(score), ha='center', fontsize=10, fontweight='bold')
plt.xlabel('算法')
plt.ylabel('准确率 (%)')
plt.title('不同算法准确率对比')
plt.ylim(0, 100)
plt.tight_layout()
plt.show()`,

  scatter: `import matplotlib.pyplot as plt
import numpy as np

np.random.seed(42)
x = np.random.randn(100)
y = 2 * x + np.random.randn(100) * 0.5

plt.figure(figsize=(8, 4))
plt.scatter(x, y, c='#6c9fd8', alpha=0.7, edgecolors='white', linewidth=0.5, s=50)
z = np.polyfit(x, y, 1)
p = np.poly1d(z)
plt.plot(sorted(x), p(sorted(x)), 'r--', linewidth=2, label=f'y={z[0]:.2f}x+{z[1]:.2f}')
plt.xlabel('X')
plt.ylabel('Y')
plt.title('散点图与线性拟合')
plt.legend()
plt.grid(alpha=0.2)
plt.tight_layout()
plt.show()`,

  function: `import matplotlib.pyplot as plt
import numpy as np

x = np.linspace(-5, 5, 500)
y1 = x**2
y2 = x**3
y3 = np.exp(-x**2)

plt.figure(figsize=(8, 4))
plt.plot(x, y1, 'b-', label='y = x²', linewidth=2)
plt.plot(x, y2, 'g--', label='y = x³', linewidth=2)
plt.plot(x, y3, 'r-.', label='y = e^(-x²)', linewidth=2)
plt.axhline(y=0, color='gray', linewidth=0.5)
plt.axvline(x=0, color='gray', linewidth=0.5)
plt.xlabel('x')
plt.ylabel('y')
plt.title('常见函数曲线')
plt.legend()
plt.grid(alpha=0.3)
plt.ylim(-5, 10)
plt.tight_layout()
plt.show()`,

  '3d': `import matplotlib.pyplot as plt
import numpy as np
from mpl_toolkits.mplot3d import Axes3D

x = np.linspace(-5, 5, 50)
y = np.linspace(-5, 5, 50)
X, Y = np.meshgrid(x, y)
Z = np.sin(np.sqrt(X**2 + Y**2))

fig = plt.figure(figsize=(8, 5))
ax = fig.add_subplot(111, projection='3d')
surf = ax.plot_surface(X, Y, Z, cmap='viridis', edgecolor='none', alpha=0.9)
fig.colorbar(surf, ax=ax, shrink=0.5, aspect=5)
ax.set_xlabel('X')
ax.set_ylabel('Y')
ax.set_zlabel('Z')
ax.set_title('3D 曲面: z = sin(√(x²+ y²))')
plt.tight_layout()
plt.show()`,
}

function selectChart(id) {
  activeChart.value = id
  code.value = chartCode[id] || ''
  output.value = ''
  imageUrl.value = ''
  error.value = ''
  explanation.value = ''
}

async function runCode() {
  running.value = true
  error.value = ''
  output.value = ''
  imageUrl.value = ''
  try {
    const { default: axios } = await import('axios')
    const token = localStorage.getItem('edumatrix_token')
    const headers = { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' }
    const resp = await axios.post('/api/code/run', {
      code: code.value,
      language: 'python',
      student_id: props.studentId,
    }, { headers })
    const result = resp.data
    if (result.status === 'success' || result.status === 'completed') {
      output.value = result.stdout || ''
      if (result.image_base64) {
        imageUrl.value = `data:image/png;base64,${result.image_base64}`
      }
    } else {
      error.value = result.stderr || '执行失败'
    }
  } catch (e) {
    error.value = e.response?.data?.detail || e.message || '请求失败'
  }
  running.value = false
}

async function generateExplanation() {
  explaining.value = true
  try {
    const { default: axios } = await import('axios')
    const headers = { Authorization: `Bearer ${localStorage.getItem('edumatrix_token')}`, 'Content-Type': 'application/json' }
    const resp = await axios.post('/api/stream/explain', {
      target_text: `以下是一张${chartTypes.find(c => c.id === activeChart.value)?.label || ''}图表，展示了机器学习相关的数据可视化。请解释这张图表展示了什么，以及从中可以得出什么结论。\n\n图表代码：\n${code.value}`,
      student_id: props.studentId,
    }, { headers })
    explanation.value = resp.data.content || '无法生成讲解'
  } catch (e) {
    explanation.value = '讲解生成失败'
  }
  explaining.value = false
}

function close() {
  visible.value = false
  emit('close')
}

// 初始化默认代码
selectChart('line')
</script>

<template>
  <div v-if="visible"
    class="fixed bottom-6 left-6 z-50 w-[92vw] md:w-[560px] max-h-[80vh] bg-gray-900/95 backdrop-blur-md border border-gray-700/50 rounded-2xl shadow-2xl flex flex-col overflow-hidden transition-all duration-200">

    <!-- Header -->
    <div class="flex items-center justify-between px-4 py-3 border-b border-gray-700/50 shrink-0 bg-gray-800/80">
      <div class="flex items-center gap-2">
        <div class="w-6 h-6 rounded-lg bg-gradient-to-br from-green-500 to-teal-600 flex items-center justify-center">
          <span class="text-white text-xs">📊</span>
        </div>
        <span class="text-xs font-semibold text-gray-200">可视化分析</span>
      </div>
      <button @click="close" class="w-6 h-6 rounded-lg hover:bg-gray-700 flex items-center justify-center text-gray-400 hover:text-gray-200 transition-all">
        <span class="text-sm leading-none">&times;</span>
      </button>
    </div>

    <!-- Chart type selector -->
    <div class="flex gap-1.5 px-3 py-2.5 border-b border-gray-800 overflow-x-auto shrink-0 bg-gray-850">
      <button v-for="ct in chartTypes" :key="ct.id"
        class="px-3 py-1.5 text-[10px] font-semibold rounded-lg transition-all whitespace-nowrap"
        :class="activeChart === ct.id ? 'bg-teal-600 text-white shadow-sm' : 'bg-gray-800 text-gray-400 hover:bg-gray-700 hover:text-gray-200'"
        @click="selectChart(ct.id)">
        {{ ct.icon }} {{ ct.label }}
      </button>
    </div>

    <!-- Main content -->
    <div class="flex-1 overflow-y-auto p-3 space-y-3 scrollbar-thin">

      <!-- Code preview -->
      <div class="bg-gray-800/80 rounded-xl overflow-hidden border border-gray-700/50">
        <div class="flex items-center justify-between px-3 py-1.5 bg-gray-800 border-b border-gray-700/50">
          <span class="text-[9px] text-gray-500 font-mono">matplotlib 代码</span>
          <button class="px-3 py-1 text-[9px] font-semibold rounded-lg transition-all"
            :class="running ? 'bg-gray-700 text-gray-400 cursor-wait' : 'bg-teal-600 text-white hover:bg-teal-500'"
            :disabled="running" @click="runCode">
            {{ running ? '⏳ 运行中...' : '▶ 运行' }}
          </button>
        </div>
        <pre class="p-3 text-[10px] font-mono text-gray-300 overflow-x-auto leading-relaxed max-h-32">{{ code }}</pre>
      </div>

      <!-- Result: image or output -->
      <div v-if="imageUrl" class="bg-gray-800/80 rounded-xl overflow-hidden border border-gray-700/50">
        <div class="flex items-center justify-between px-3 py-1.5 bg-gray-800 border-b border-gray-700/50">
          <span class="text-[9px] text-gray-500">📊 生成图表</span>
          <button class="px-2 py-1 text-[9px] font-semibold rounded-lg bg-purple-600 text-white hover:bg-purple-500 transition-all"
            :disabled="explaining" @click="generateExplanation">
            {{ explaining ? '生成中...' : '💡 生成讲解' }}
          </button>
        </div>
        <div class="p-2 flex justify-center bg-gray-900">
          <img :src="imageUrl" alt="生成图表" class="max-w-full rounded-lg" />
        </div>
      </div>

      <!-- Text output -->
      <div v-if="output && !imageUrl" class="bg-gray-800/80 rounded-xl p-3 border border-gray-700/50">
        <p class="text-[9px] text-gray-500 mb-1">控制台输出</p>
        <pre class="text-[10px] font-mono text-green-400 whitespace-pre-wrap">{{ output }}</pre>
      </div>

      <!-- Error -->
      <div v-if="error" class="bg-red-900/30 rounded-xl p-3 border border-red-700/30">
        <p class="text-[10px] text-red-400">{{ error }}</p>
      </div>

      <!-- Explanation -->
      <div v-if="explanation" class="bg-purple-900/20 rounded-xl p-3 border border-purple-700/30">
        <p class="text-[9px] text-purple-400 mb-1">💡 图表讲解</p>
        <p class="text-[10px] text-gray-300 leading-relaxed">{{ explanation }}</p>
      </div>

    </div>
  </div>
</template>
