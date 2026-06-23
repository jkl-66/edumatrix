<script setup>
/**
 * ManifoldVisualizer.vue — 任务 9.1: Poincaré 双曲圆盘可视化
 *
 * 在 Canvas 上渲染双曲几何圆盘：
 * - 学生掌握状态粒子（蓝色）沿测地线向教学大纲知识点（金色）动态对齐
 * - 实时展示 KL 散度、对齐偏差数值
 * - 冲突场景触发红色告警与轨迹动画
 */
import { ref, onMounted, onUnmounted, watch, nextTick } from 'vue'

const props = defineProps({
  studentMastery: { type: Array, default: () => [] },  // [{name, mastery, x, y}]
  targetPoints: { type: Array, default: () => [] },    // [{name, x, y}]
  klDivergence: { type: Number, default: 0 },
  alignmentProgress: { type: Number, default: 0 },     // 0~100
  conflictDetected: { type: Boolean, default: false },
  debugMode: { type: Boolean, default: false },
})

const canvasRef = ref(null)
let ctx = null
let animationFrame = null
let particles = []
let time = 0

// 粒子类
class Particle {
  constructor(x, y, color, label, size = 4) {
    this.x = x
    this.y = y
    this.targetX = x
    this.targetY = y
    this.color = color
    this.label = label
    this.size = size
    this.alpha = 0.7
    this.pulse = Math.random() * Math.PI * 2
  }
}

function initParticles() {
  particles = []
  const w = canvasRef.value?.width || 400
  const h = canvasRef.value?.height || 400
  const cx = w / 2
  const cy = h / 2
  const radius = Math.min(w, h) / 2 - 20

  // 学生掌握状态粒子（蓝色系） - 在圆盘内随机分布
  props.studentMastery.forEach((s, i) => {
    const angle = (i / Math.max(props.studentMastery.length, 1)) * Math.PI * 2
    const dist = s.mastery * radius * 0.7
    const p = new Particle(
      cx + Math.cos(angle) * dist,
      cy + Math.sin(angle) * dist,
      `hsla(${200 + s.mastery * 60}, 80%, 60%, `,
      s.name,
      3 + s.mastery * 4,
    )
    p.targetX = s.x ? cx + s.x * radius * 0.8 : p.x
    p.targetY = s.y ? cy + s.y * radius * 0.8 : p.y
    particles.push(p)
  })

  // 目标知识点粒子（金色系）
  props.targetPoints.forEach((t, i) => {
    const angle = (i / Math.max(props.targetPoints.length, 1)) * Math.PI * 2 + 0.3
    const dist = radius * 0.75
    const p = new Particle(
      cx + Math.cos(angle) * dist,
      cy + Math.sin(angle) * dist,
      `hsla(${45 + i * 15}, 90%, 60%, `,
      t.name,
      6,
    )
    particles.push(p)
  })
}

function drawPoincareDisk() {
  if (!ctx || !canvasRef.value) return
  const w = canvasRef.value.width
  const h = canvasRef.value.height
  const cx = w / 2
  const cy = h / 2
  const radius = Math.min(w, h) / 2 - 20

  ctx.clearRect(0, 0, w, h)

  // 背景
  const bg = ctx.createRadialGradient(cx, cy, 0, cx, cy, radius)
  bg.addColorStop(0, '#0f172a')
  bg.addColorStop(1, '#020617')
  ctx.fillStyle = bg
  ctx.fillRect(0, 0, w, h)

  // 双曲圆盘边界
  ctx.beginPath()
  ctx.arc(cx, cy, radius, 0, Math.PI * 2)
  ctx.strokeStyle = 'rgba(148,163,184,0.3)'
  ctx.lineWidth = 1.5
  ctx.stroke()

  // 内部网格（测地线参考）
  for (let i = 1; i <= 3; i++) {
    ctx.beginPath()
    ctx.arc(cx, cy, radius * i / 4, 0, Math.PI * 2)
    ctx.strokeStyle = 'rgba(148,163,184,0.08)'
    ctx.lineWidth = 0.5
    ctx.stroke()
  }
  for (let i = 0; i < 6; i++) {
    ctx.beginPath()
    ctx.moveTo(cx, cy)
    ctx.lineTo(cx + radius * Math.cos(i * Math.PI / 3), cy + radius * Math.sin(i * Math.PI / 3))
    ctx.strokeStyle = 'rgba(148,163,184,0.08)'
    ctx.lineWidth = 0.5
    ctx.stroke()
  }

  // 测地线连接（学生粒子 → 目标粒子）
  const studentParticles = particles.slice(0, props.studentMastery.length)
  const targetParticles = particles.slice(props.studentMastery.length)
  studentParticles.forEach((sp, i) => {
    const tp = targetParticles[i % Math.max(targetParticles.length, 1)]
    if (!tp) return

    time += 0.008
    const t = (Math.sin(time) + 1) / 2

    // 测地线路径
    ctx.beginPath()
    const grad = ctx.createLinearGradient(sp.x, sp.y, tp.x, tp.y)
    grad.addColorStop(0, `hsla(210, 80%, 60%, ${0.2 + sp.alpha * 0.3})`)
    grad.addColorStop(1, `hsla(45, 90%, 60%, ${0.2 + tp.alpha * 0.3})`)
    ctx.strokeStyle = grad
    ctx.lineWidth = props.conflictDetected ? 3 : 1.5

    // 如果冲突，用虚线 + 红色
    if (props.conflictDetected) {
      ctx.setLineDash([5, 5])
      ctx.strokeStyle = `rgba(239, 68, 68, ${0.4 + Math.sin(time * 3) * 0.3})`
    }

    ctx.moveTo(sp.x, sp.y)
    // 双曲测地线近似：二次贝塞尔弯曲
    const cpX = (sp.x + tp.x) / 2 + (tp.y - sp.y) * (props.conflictDetected ? 0.5 : 0.2)
    const cpY = (sp.y + tp.y) / 2 - (tp.x - sp.x) * (props.conflictDetected ? 0.5 : 0.2)
    ctx.quadraticCurveTo(cpX, cpY, tp.x, tp.y)
    ctx.stroke()
    ctx.setLineDash([])

    // 动画粒子沿测地线移动（代表对齐过程）
    const ax = (1 - t) * (1 - t) * sp.x + 2 * (1 - t) * t * cpX + t * t * tp.x
    const ay = (1 - t) * (1 - t) * sp.y + 2 * (1 - t) * t * cpY + t * t * tp.y
    ctx.beginPath()
    ctx.arc(ax, ay, 2, 0, Math.PI * 2)
    ctx.fillStyle = props.conflictDetected
      ? `rgba(239, 68, 68, ${0.6 + Math.sin(time * 5) * 0.4})`
      : `rgba(59, 130, 246, ${0.5 + Math.sin(time * 3) * 0.3})`
    ctx.fill()
  })

  // 渲染粒子
  particles.forEach(p => {
    // 脉冲动画
    p.pulse += 0.03
    const pulseSize = p.size + Math.sin(p.pulse) * 1.5
    const glow = ctx.createRadialGradient(p.x, p.y, 0, p.x, p.y, pulseSize * 4)
    glow.addColorStop(0, `${p.color}${props.conflictDetected ? 0.4 : 0.3})`)
    glow.addColorStop(1, `${p.color}0)`)
    ctx.fillStyle = glow
    ctx.beginPath()
    ctx.arc(p.x, p.y, pulseSize * 4, 0, Math.PI * 2)
    ctx.fill()

    // 粒子本体
    ctx.beginPath()
    ctx.arc(p.x, p.y, pulseSize, 0, Math.PI * 2)
    ctx.fillStyle = `${p.color}${p.alpha})`
    ctx.fill()
    ctx.strokeStyle = `${p.color}1)`
    ctx.lineWidth = 1
    ctx.stroke()

    // 标签
    ctx.fillStyle = 'rgba(226, 232, 240, 0.8)'
    ctx.font = '9px system-ui, sans-serif'
    ctx.textAlign = 'center'
    ctx.fillText(p.label, p.x, p.y - pulseSize - 6)
  })

  // 冲突告警动画
  if (props.conflictDetected) {
    const pulse = Math.sin(time * 6) * 0.5 + 0.5
    ctx.beginPath()
    ctx.arc(cx, cy, radius * (0.7 + pulse * 0.2), 0, Math.PI * 2)
    ctx.strokeStyle = `rgba(239, 68, 68, ${0.2 + pulse * 0.3})`
    ctx.lineWidth = 2
    ctx.stroke()

    ctx.fillStyle = `rgba(239, 68, 68, ${0.6 + pulse * 0.4})`
    ctx.font = 'bold 14px system-ui, sans-serif'
    ctx.textAlign = 'center'
    ctx.fillText('⚠ 认知冲突检测', cx, 30)
  }

  animationFrame = requestAnimationFrame(drawPoincareDisk)
}

let resizeObserver = null

function resize() {
  if (!canvasRef.value) return
  const parent = canvasRef.value.parentElement
  canvasRef.value.width = parent?.clientWidth || 400
  canvasRef.value.height = 360
}

onMounted(async () => {
  resize()
  window.addEventListener('resize', resize)

  // Use ResizeObserver to auto-detect width changes during slide-out transitions
  if (canvasRef.value && typeof ResizeObserver !== 'undefined') {
    const parent = canvasRef.value.parentElement
    if (parent) {
      resizeObserver = new ResizeObserver(() => {
        resize()
        initParticles()
      })
      resizeObserver.observe(parent)
    }
  }

  await nextTick()
  ctx = canvasRef.value?.getContext('2d')
  initParticles()
  drawPoincareDisk()
})

onUnmounted(() => {
  window.removeEventListener('resize', resize)
  if (resizeObserver) {
    resizeObserver.disconnect()
  }
  if (animationFrame) cancelAnimationFrame(animationFrame)
})

watch(() => [props.studentMastery, props.targetPoints], () => {
  initParticles()
}, { deep: true })
</script>

<template>
  <div class="manifold-visualizer bg-gray-950 rounded-lg border border-gray-800 overflow-hidden">
    <!-- 标题栏 -->
    <div class="flex items-center justify-between px-3 py-2 bg-gray-900 border-b border-gray-800">
      <div class="flex items-center gap-2">
        <span class="text-xs font-semibold text-purple-400">Poincaré 双曲圆盘</span>
        <span class="text-[10px] text-gray-500">知识拓扑流形对齐</span>
      </div>
      <div class="flex items-center gap-3 text-[10px]">
        <span class="text-gray-400">KL: <b :class="klDivergence > 0.5 ? 'text-red-400' : 'text-green-400'">
          {{ klDivergence.toFixed(3) }}</b>
        </span>
        <span class="text-gray-400">对齐: <b :class="alignmentProgress > 80 ? 'text-green-400' : 'text-yellow-400'">
          {{ alignmentProgress.toFixed(0) }}%</b>
        </span>
      </div>
    </div>

    <!-- Canvas -->
    <canvas ref="canvasRef" class="w-full cursor-crosshair" style="min-height: 350px" />

    <!-- 图例 -->
    <div class="flex gap-4 px-3 py-1.5 bg-gray-900 border-t border-gray-800 text-[10px] text-gray-400 flex-wrap">
      <span class="flex items-center gap-1"><span class="w-2 h-2 rounded-full bg-blue-500" /> 学生掌握态</span>
      <span class="flex items-center gap-1"><span class="w-2 h-2 rounded-full bg-amber-500" /> 标准知识节点</span>
      <span class="flex items-center gap-1"><span class="w-2 h-2 rounded-full bg-green-500" /> 已对齐</span>
      <span v-if="conflictDetected" class="flex items-center gap-1 text-red-400">
        <span class="w-2 h-2 rounded-full bg-red-500 animate-pulse" /> 认知冲突
      </span>
    </div>
  </div>
</template>
