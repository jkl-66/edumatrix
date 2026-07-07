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

    // 计算 Poincaré 圆盘中的真实双曲测地线 (Hyperbolic Geodesics)
    // 测地线在此空间中为正交于边界的圆弧或过原点的直线
    const ux = (sp.x - cx) / radius
    const uy = (sp.y - cy) / radius
    const vx = (tp.x - cx) / radius
    const vy = (tp.y - cy) / radius

    const cross = ux * vy - uy * vx
    let arcInfo = null

    // 渐变色样式
    const grad = ctx.createLinearGradient(sp.x, sp.y, tp.x, tp.y)
    grad.addColorStop(0, `hsla(210, 80%, 60%, ${0.2 + sp.alpha * 0.3})`)
    grad.addColorStop(1, `hsla(45, 90%, 60%, ${0.2 + tp.alpha * 0.3})`)
    ctx.strokeStyle = grad
    ctx.lineWidth = props.conflictDetected ? 3 : 1.5

    if (props.conflictDetected) {
      ctx.setLineDash([5, 5])
      ctx.strokeStyle = `rgba(239, 68, 68, ${0.45 + Math.sin(time * 0.6) * 0.15})`
    }

    if (Math.abs(cross) > 1e-4) {
      // 非共线情况：求解正交于单位圆且通过 u, v 两点圆的圆心和半径
      const u2 = ux * ux + uy * uy
      const v2 = vx * vx + vy * vy
      const denom = 2.0 * cross

      const ox = (vy * (1.0 + u2) - uy * (1.0 + v2)) / denom
      const oy = (ux * (1.0 + v2) - vx * (1.0 + u2)) / denom
      const or = Math.sqrt(ox * ox + oy * oy - 1.0)

      // 投影回 Canvas 物理坐标系
      const canvas_ox = ox * radius + cx
      const canvas_oy = oy * radius + cy
      const canvas_or = or * radius

      // 起始与终止角
      const theta_u = Math.atan2(sp.y - canvas_oy, sp.x - canvas_ox)
      const theta_v = Math.atan2(tp.y - canvas_oy, tp.x - canvas_ox)

      let diff = theta_v - theta_u
      while (diff < -Math.PI) diff += Math.PI * 2
      while (diff > Math.PI) diff -= Math.PI * 2

      ctx.beginPath()
      ctx.arc(canvas_ox, canvas_oy, canvas_or, theta_u, theta_u + diff, diff < 0)
      ctx.stroke()
      ctx.setLineDash([])

      arcInfo = { ox: canvas_ox, oy: canvas_oy, or: canvas_or, theta_u, diff }
    } else {
      // 共线情况：双曲测地线退化为直连线段
      ctx.beginPath()
      ctx.moveTo(sp.x, sp.y)
      ctx.lineTo(tp.x, tp.y)
      ctx.stroke()
      ctx.setLineDash([])
    }

    // 动画粒子沿双曲测地线移动
    let ax, ay
    if (arcInfo) {
      const angle = arcInfo.theta_u + t * arcInfo.diff
      ax = arcInfo.ox + Math.cos(angle) * arcInfo.or
      ay = arcInfo.oy + Math.sin(angle) * arcInfo.or
    } else {
      ax = sp.x + t * (tp.x - sp.x)
      ay = sp.y + t * (tp.y - sp.y)
    }

    ctx.beginPath()
    ctx.arc(ax, ay, 2, 0, Math.PI * 2)
    ctx.fillStyle = props.conflictDetected
      ? `rgba(239, 68, 68, ${0.65 + Math.sin(time * 0.8) * 0.15})`
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

  // 冲突告警动画（柔和平缓呼吸光效，减缓频率，减小波幅）
  if (props.conflictDetected) {
    const pulse = Math.sin(time * 0.5) * 0.2 + 0.8
    ctx.beginPath()
    ctx.arc(cx, cy, radius * (0.8 + pulse * 0.05), 0, Math.PI * 2)
    ctx.strokeStyle = `rgba(239, 68, 68, ${0.15 + (pulse - 0.8) * 0.2})`
    ctx.lineWidth = 1.5
    ctx.stroke()

    ctx.fillStyle = 'rgba(239, 68, 68, 0.8)'  // 警告文本保持高品质静态，防刺眼
    ctx.font = 'bold 13px system-ui, sans-serif'
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
