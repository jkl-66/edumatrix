<script setup>
/**
 * GraphicFallback.vue — 任务 8.4: 绘图异常降级兜底
 *
 * 全局部署渲染异常拦截器，SVG/图表参数报错时不直接白屏崩溃，
 * 自动降级展示 Mermaid/ASCII 文本示意图。
 */
import { ref, computed, onErrorCaptured } from 'vue'

const props = defineProps({
  originalType: { type: String, default: 'mermaid' },  // 'mermaid' | 'echarts' | 'svg'
  errorMessage: { type: String, default: '渲染异常' },
  fallbackText: { type: String, default: '' },
  // 若需显示替代示意图
  altDiagram: { type: String, default: '' },
})

const showFallback = ref(false)

onErrorCaptured((err, instance, info) => {
  console.warn('[GraphicFallback] 捕获渲染组件异常:', err, info)
  showFallback.value = true
  return false // 阻止错误向上冒泡
})

// 将 Mermaid 或错误文本转换为纯文本 ASCII 示意图
const asciiDiagram = computed(() => {
  if (props.altDiagram) return props.altDiagram
  if (props.fallbackText) {
    // 尝试提取纯文本描述
    const lines = props.fallbackText.split('\n').filter(l => l.trim())
    if (lines.length <= 3) {
      return [
        '╔══════════════════════════╗',
        `║  ${lines[0] || props.originalType}  ║`,
        '╚══════════════════════════╝',
      ].join('\n')
    }
    return props.fallbackText
  }
  return [
    '┌────────────────────────┐',
    `│  ${props.originalType.toUpperCase()} 示意图 (文本降级)  │`,
    '├────────────────────────┤',
    '│  对  A  ──────────→  B  │',
    '│  于        │            │',
    '│  当        ↓            │',
    '│  前        C            │',
    '│  主                     │',
    '│  题  请参考后续文本描述  │',
    '└────────────────────────┘',
  ].join('\n')
})

function retry() {
  showFallback.value = false
  // 重新触发父组件渲染
  window.dispatchEvent(new CustomEvent('graphic-retry', { detail: { type: props.originalType } }))
}

function copyText() {
  navigator.clipboard.writeText(asciiDiagram.value)
}
</script>

<template>
  <div v-if="showFallback" class="graphic-fallback border border-yellow-700/50 bg-yellow-900/10 rounded-lg p-4 my-2">
    <div class="flex items-center gap-2 mb-2">
      <span class="text-yellow-500 text-xs font-semibold">⚠️ 图示渲染异常</span>
      <span class="text-[10px] text-gray-500">{{ errorMessage }}</span>
    </div>

    <!-- ASCII 示意图降级展示 -->
    <pre class="text-xs text-green-400 bg-gray-900/50 rounded p-3 overflow-x-auto font-mono">{{ asciiDiagram }}</pre>

    <div class="flex gap-2 mt-2">
      <button @click="retry" class="px-2 py-1 bg-yellow-700 hover:bg-yellow-600 text-white rounded text-[10px] transition-colors">
        重试渲染
      </button>
      <button @click="copyText" class="px-2 py-1 bg-gray-700 hover:bg-gray-600 text-gray-300 rounded text-[10px] transition-colors">
        复制文本图
      </button>
    </div>

    <p class="text-[10px] text-gray-500 mt-2">
      💡 提示: 该图示已降级为文本格式，不影响学习内容阅读
    </p>
  </div>
  <slot v-else />
</template>
