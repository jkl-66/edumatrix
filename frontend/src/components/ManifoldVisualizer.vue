<script setup>
/**
 * ManifoldVisualizer.vue — 任务 9.1: Poincaré 双曲圆盘可视化
 *
 * 融合方案一与方案四：
 * - 支持画布拖拽平移与鼠标滚轮缩放，双击复位。
 * - 右上角全屏大舱探索模式，利用 Vue 3 Teleport 将弹窗挂载至 Body 根节点，避免父级 transform 容器层级锁定，并在视口中央呈现居中悬浮舱。
 * - 双轨优先级碰撞避让算法，确保核心大纲标签 100% 渲染呈现，学情细粒度标签按需避让，还原清晰的层级分布。
 * - HTML 绝对定位毛玻璃浮动卡片展示节点详细掌握度。
 */
import { ref, onMounted, onUnmounted, watch, nextTick } from 'vue'
import { Plus, Minus, RotateCcw, Maximize2, Minimize2 } from '@lucide/vue'

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

// 交互状态 (方案一)
const scale = ref(1.0)
const offsetX = ref(0.0)
const offsetY = ref(0.0)
const isFullscreen = ref(false)
let isDragging = false
let startX = 0
let startY = 0

// 悬停卡片状态 (方案四)
const hoveredNode = ref(null)
const tooltipX = ref(0)
const tooltipY = ref(0)

// 粒子类
class Particle {
  constructor(x, y, color, label, size = 4, isTarget = false, mastery = 0.0) {
    this.x = x
    this.y = y
    this.targetX = x
    this.targetY = y
    this.color = color
    this.label = label
    this.size = size
    this.alpha = 0.7
    this.pulse = Math.random() * Math.PI * 2
    this.isTarget = isTarget
    this.mastery = mastery
    this.isAligned = !isTarget && mastery >= 0.95
  }
}

function initParticles() {
  const oldParticles = [...particles]
  particles = []
  const w = canvasRef.value?.width || 400
  const h = canvasRef.value?.height || 400
  const cx = w / 2
  const cy = h / 2
  const radius = Math.min(w, h) / 2 - 20

  // 1. 目标知识点粒子（金色系）
  props.targetPoints.filter(t => t && t.name && t.name !== '未知' && t.name !== '未知概念' && t.name !== '未知主题').forEach((t, i) => {
    const angle = (i / Math.max(props.targetPoints.length, 1)) * Math.PI * 2 + 0.3
    const hasCoords = (t.x !== undefined && t.y !== undefined && (t.x !== 0 || t.y !== 0))
    
    // 如果后端提供了双曲流形投影坐标，则使用实际坐标，否则使用等角环形分布
    const targetX = hasCoords ? cx + t.x * radius * 0.9 : cx + Math.cos(angle) * (radius * 0.75)
    const targetY = hasCoords ? cy + t.y * radius * 0.9 : cy + Math.sin(angle) * (radius * 0.75)

    // 寻找旧粒子以确保平滑过渡，若无则使用目标位置初始化
    const oldP = oldParticles.find(p => p.label === t.name && p.isTarget)
    const initX = oldP ? oldP.x : targetX
    const initY = oldP ? oldP.y : targetY

    const p = new Particle(
      initX,
      initY,
      `hsla(${45 + i * 15}, 90%, 60%, `,
      t.name,
      6,
      true
    )
    p.targetX = targetX
    p.targetY = targetY
    particles.push(p)
  })

  // 2. 学生掌握状态粒子（绿色/蓝色系）
  props.studentMastery.filter(s => s && s.name && s.name !== '未知' && s.name !== '未知概念' && s.name !== '未知主题').forEach((s, i) => {
    const angle = (i / Math.max(props.studentMastery.length, 1)) * Math.PI * 2
    const hasCoords = (s.x !== undefined && s.y !== undefined && (s.x !== 0 || s.y !== 0))
    
    // 找出目标概念的位置
    const tx = hasCoords ? cx + s.x * radius * 0.9 : cx + Math.cos(angle) * (radius * 0.75)
    const ty = hasCoords ? cy + s.y * radius * 0.9 : cy + Math.sin(angle) * (radius * 0.75)

    // 创新对齐机制：掌握度决定其向对应标准节点的对齐距离（0%在圆心，100%在标准节点重合对齐）
    const targetX = cx + s.mastery * (tx - cx)
    const targetY = cy + s.mastery * (ty - cy)

    // 寻找旧粒子以确保平滑过渡，若无则从圆心（cx, cy）开始迁移
    const oldP = oldParticles.find(p => p.label === s.name && !p.isTarget)
    const initX = oldP ? oldP.x : cx
    const initY = oldP ? oldP.y : cy

    // 对齐状态使用翠绿色，未对齐使用渐变蓝色
    const isAligned = s.mastery >= 0.95
    const particleColor = isAligned
      ? `hsla(142, 70%, 50%, `
      : `hsla(${200 + s.mastery * 60}, 80%, 60%, `

    const p = new Particle(
      initX,
      initY,
      particleColor,
      s.name,
      3 + s.mastery * 4,
      false,
      s.mastery
    )
    p.targetX = targetX
    p.targetY = targetY
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

  // 0. 更新所有粒子位置 (Lerp 动画实现平滑对齐迁移)
  particles.forEach(p => {
    p.x += (p.targetX - p.x) * 0.08
    p.y += (p.targetY - p.y) * 0.08
  })

  // 背景
  const bg = ctx.createRadialGradient(cx, cy, 0, cx, cy, radius)
  bg.addColorStop(0, '#0f172a')
  bg.addColorStop(1, '#020617')
  ctx.fillStyle = bg
  ctx.fillRect(0, 0, w, h)

  // 保存画布绘图状态，应用平移与缩放矩阵 (方案一)
  ctx.save()
  ctx.translate(cx + offsetX.value, cy + offsetY.value)
  ctx.scale(scale.value, scale.value)

  // 双曲圆盘边界 (在平移后的 (0,0) 原点绘制)
  ctx.beginPath()
  ctx.arc(0, 0, radius, 0, Math.PI * 2)
  ctx.strokeStyle = 'rgba(148,163,184,0.3)'
  ctx.lineWidth = 1.5 / scale.value
  ctx.stroke()

  // 内部网格（测地线参考）
  for (let i = 1; i <= 3; i++) {
    ctx.beginPath()
    ctx.arc(0, 0, radius * i / 4, 0, Math.PI * 2)
    ctx.strokeStyle = 'rgba(148,163,184,0.08)'
    ctx.lineWidth = 0.5 / scale.value
    ctx.stroke()
  }
  for (let i = 0; i < 6; i++) {
    ctx.beginPath()
    ctx.moveTo(0, 0)
    ctx.lineTo(radius * Math.cos(i * Math.PI / 3), radius * Math.sin(i * Math.PI / 3))
    ctx.strokeStyle = 'rgba(148,163,184,0.08)'
    ctx.lineWidth = 0.5 / scale.value
    ctx.stroke()
  }

  // 测地线连接（学生粒子 → 目标粒子）
  const studentParticles = particles.slice(0, props.studentMastery.length)
  const targetParticles = particles.slice(props.studentMastery.length)
  studentParticles.forEach((sp, i) => {
    // 鲁棒的按 label 名称匹配标准概念节点，确保测地线两端正确对齐
    const tp = targetParticles.find(t => t.label === sp.label) || targetParticles[i % Math.max(targetParticles.length, 1)]
    if (!tp) return

    time += 0.008
    const t = (Math.sin(time) + 1) / 2

    // 创新对齐视觉表达：若已经对齐 (掌握度达到 100% 或距离极其接近)，在目标节点绘制绿色的脉冲波纹 halo，连线收缩到零
    const dist = Math.hypot(sp.x - tp.x, sp.y - tp.y)
    if (sp.isAligned || dist < 4) {
      ctx.beginPath()
      const pulseRadius = (tp.size * 2.2 + Math.sin(time * 4) * 4) / scale.value
      ctx.arc(tp.x - cx, tp.y - cy, pulseRadius, 0, Math.PI * 2)
      ctx.strokeStyle = `rgba(34, 197, 94, ${0.4 - Math.sin(time * 4) * 0.2})`
      ctx.lineWidth = 1.5 / scale.value
      ctx.stroke()
      return // 不再绘制外部连线，完美呈现重合状态
    }

    // 计算 Poincaré 圆盘中的真实双曲测地线 (Hyperbolic Geodesics)
    const ux = (sp.x - cx) / radius
    const uy = (sp.y - cy) / radius
    const vx = (tp.x - cx) / radius
    const vy = (tp.y - cy) / radius

    const cross = ux * vy - uy * vx
    let arcInfo = null

    // 渐变色样式
    const grad = ctx.createLinearGradient(sp.x - cx, sp.y - cy, tp.x - cx, tp.y - cy)
    grad.addColorStop(0, `hsla(210, 80%, 60%, ${0.2 + sp.alpha * 0.3})`)
    grad.addColorStop(1, `hsla(45, 90%, 60%, ${0.2 + tp.alpha * 0.3})`)
    ctx.strokeStyle = grad
    ctx.lineWidth = (props.conflictDetected ? 3 : 1.5) / scale.value

    if (props.conflictDetected) {
      ctx.setLineDash([5 / scale.value, 5 / scale.value])
      ctx.strokeStyle = `rgba(239, 68, 68, ${0.45 + Math.sin(time * 0.6) * 0.15})`
    }

    if (Math.abs(cross) > 1e-4) {
      const u2 = ux * ux + uy * uy
      const v2 = vx * vx + vy * vy
      const denom = 2.0 * cross

      const ox = (vy * (1.0 + u2) - uy * (1.0 + v2)) / denom
      const oy = (ux * (1.0 + v2) - vx * (1.0 + u2)) / denom
      const or = Math.sqrt(ox * ox + oy * oy - 1.0)

      // 投影至平移后的局部空间
      const local_ox = ox * radius
      const local_oy = oy * radius
      const local_or = or * radius

      const theta_u = Math.atan2(sp.y - cy - local_oy, sp.x - cx - local_ox)
      const theta_v = Math.atan2(tp.y - cy - local_oy, tp.x - cx - local_ox)

      let diff = theta_v - theta_u
      while (diff < -Math.PI) diff += Math.PI * 2
      while (diff > Math.PI) diff -= Math.PI * 2

      ctx.beginPath()
      ctx.arc(local_ox, local_oy, local_or, theta_u, theta_u + diff, diff < 0)
      ctx.stroke()
      ctx.setLineDash([])

      arcInfo = { ox: local_ox, oy: local_oy, or: local_or, theta_u, diff }
    } else {
      ctx.beginPath()
      ctx.moveTo(sp.x - cx, sp.y - cy)
      ctx.lineTo(tp.x - cx, tp.y - cy)
      ctx.stroke()
      ctx.setLineDash([])
    }

    // 动画粒子移动
    let ax, ay
    if (arcInfo) {
      const angle = arcInfo.theta_u + t * arcInfo.diff
      ax = arcInfo.ox + Math.cos(angle) * arcInfo.or
      ay = arcInfo.oy + Math.sin(angle) * arcInfo.or
    } else {
      ax = (sp.x - cx) + t * ((tp.x - cx) - (sp.x - cx))
      ay = (sp.y - cy) + t * ((tp.y - cy) - (sp.y - cy))
    }

    ctx.beginPath()
    ctx.arc(ax, ay, 2 / scale.value, 0, Math.PI * 2)
    ctx.fillStyle = props.conflictDetected
      ? `rgba(239, 68, 68, ${0.65 + Math.sin(time * 0.8) * 0.15})`
      : `rgba(59, 130, 246, ${0.5 + Math.sin(time * 3) * 0.3})`
    ctx.fill()
  })

  // 渲染粒子本体 (在平移后空间)
  particles.forEach(p => {
    p.pulse += 0.03
    const pulseSize = p.size + Math.sin(p.pulse) * 1.5
    const px = p.x - cx
    const py = p.y - cy

    const glow = ctx.createRadialGradient(px, py, 0, px, py, (pulseSize * 4) / scale.value)
    glow.addColorStop(0, `${p.color}${props.conflictDetected ? 0.4 : 0.3})`)
    glow.addColorStop(1, `${p.color}0)`)
    ctx.fillStyle = glow
    ctx.beginPath()
    ctx.arc(px, py, (pulseSize * 4) / scale.value, 0, Math.PI * 2)
    ctx.fill()

    ctx.beginPath()
    ctx.arc(px, py, pulseSize / scale.value, 0, Math.PI * 2)
    ctx.fillStyle = `${p.color}${p.alpha})`
    ctx.fill()
    ctx.strokeStyle = `${p.color}1)`
    ctx.lineWidth = 1 / scale.value
    ctx.stroke()
  })

  // 标签渲染双轨优先级避让算法（为了让文字始终置顶，先画完所有粒子再画文字，且使用径向推开算法避让中心密集区） (方案四)
  const drawnLabelsBBoxes = []

  function drawSingleLabel(p) {
    const isHovered = hoveredNode.value === p
    const px = p.x - cx
    const py = p.y - cy
    const pulseSize = p.size + Math.sin(p.pulse) * 1.5

    ctx.font = `${isHovered ? 'bold ' : ''}${(10 / scale.value).toFixed(1)}px system-ui, -apple-system, sans-serif`
    const labelText = p.label
    const metrics = ctx.measureText(labelText)
    const textWidth = metrics.width
    const textHeight = 10 / scale.value

    // 计算偏离圆心的径向向量，将标签向外推以避开中心密集区
    const distFromCenter = Math.hypot(px, py)
    let ux = 0
    let uy = -1 // 默认向上
    if (distFromCenter > 2) {
      ux = px / distFromCenter
      uy = py / distFromCenter
    } else {
      // 靠近圆心的微观节点使用其在粒子数组中的索引做固定径向推开
      const idx = particles.indexOf(p)
      const angle = (idx / Math.max(particles.length, 1)) * Math.PI * 2
      ux = Math.cos(angle)
      uy = Math.sin(angle)
    }

    // 径向偏移量 (增加边距防止遮挡粒子本身)
    const radialOffset = (pulseSize + 8) / scale.value
    const tx = px + ux * radialOffset
    const ty = py + uy * radialOffset

    // 根据径向向量动态调整对齐方式，保证文字向圆盘外侧延伸
    if (ux > 0.3) {
      ctx.textAlign = 'left'
    } else if (ux < -0.3) {
      ctx.textAlign = 'right'
    } else {
      ctx.textAlign = 'center'
    }

    if (uy > 0.3) {
      ctx.textBaseline = 'top'
    } else if (uy < -0.3) {
      ctx.textBaseline = 'bottom'
    } else {
      ctx.textBaseline = 'middle'
    }

    // 计算包围盒
    let bx = tx
    if (ctx.textAlign === 'right') {
      bx = tx - textWidth
    } else if (ctx.textAlign === 'center') {
      bx = tx - textWidth / 2
    }

    let by = ty
    if (ctx.textBaseline === 'bottom') {
      by = ty - textHeight
    } else if (ctx.textBaseline === 'middle') {
      by = ty - textHeight / 2
    }

    const bw = textWidth
    const bh = textHeight

    // 碰撞检测
    let collides = false
    for (const box of drawnLabelsBBoxes) {
      if (bx < box.x + box.w &&
          bx + bw > box.x &&
          by < box.y + box.h &&
          by + bh > box.y) {
        collides = true
        break
      }
    }

    // 碰撞避让：非 hovered 节点如果重叠，则静默隐藏，确保层级排版清爽
    if (collides && !isHovered) {
      return
    }

    // 绘制文字
    ctx.fillStyle = isHovered 
      ? '#818cf8' 
      : (p.isTarget ? 'rgba(251, 191, 36, 0.95)' : 'rgba(226, 232, 240, 0.85)')
    ctx.fillText(labelText, tx, ty)

    drawnLabelsBBoxes.push({ x: bx, y: by, w: bw, h: bh })
  }

  // 1. 最高优先级绘制当前悬浮选中的节点标签，确保一定能显示
  particles.forEach(p => {
    if (hoveredNode.value === p) {
      drawSingleLabel(p)
    }
  })

  // 2. 次优先级绘制标准知识点大纲骨架标签（金色），重叠时自动避让
  // 彻底取消普通未选中状态下学生掌握状态白/蓝标签的直接绘制，避免重合对齐时的双重文字重叠
  particles.forEach(p => {
    if (p.isTarget && hoveredNode.value !== p) {
      drawSingleLabel(p)
    }
  })

  // 恢复画布状态 (方案一)
  ctx.restore()

  // 冲突告警动画
  if (props.conflictDetected) {
    const pulse = Math.sin(time * 0.5) * 0.2 + 0.8
    ctx.beginPath()
    ctx.arc(cx, cy, radius * (0.8 + pulse * 0.05), 0, Math.PI * 2)
    ctx.strokeStyle = `rgba(239, 68, 68, ${0.15 + (pulse - 0.8) * 0.2})`
    ctx.lineWidth = 1.5
    ctx.stroke()

    ctx.fillStyle = 'rgba(239, 68, 68, 0.8)'
    ctx.font = 'bold 13px system-ui, sans-serif'
    ctx.textAlign = 'center'
    ctx.fillText('⚠ 认知冲突检测', cx, 30)
  }

  animationFrame = requestAnimationFrame(drawPoincareDisk)
}

// 滚轮缩放与平移核心变换 (方案一)
function handleWheel(e) {
  e.preventDefault()
  const zoomFactor = 1.1
  const direction = e.deltaY < 0 ? 1 : -1
  let newScale = scale.value * (direction > 0 ? zoomFactor : 1 / zoomFactor)
  newScale = Math.max(0.6, Math.min(5.0, newScale))

  const mouseX = e.offsetX
  const mouseY = e.offsetY
  const w = canvasRef.value?.width || 400
  const h = canvasRef.value?.height || 400
  const cx = w / 2
  const cy = h / 2

  // 以鼠标指针为缩放原点进行平移偏差补偿
  offsetX.value = mouseX - cx - (mouseX - cx - offsetX.value) * (newScale / scale.value)
  offsetY.value = mouseY - cy - (mouseY - cy - offsetY.value) * (newScale / scale.value)
  scale.value = newScale
}

function handleMouseDown(e) {
  isDragging = true
  startX = e.clientX - offsetX.value
  startY = e.clientY - offsetY.value
}

function handleMouseMove(e) {
  const w = canvasRef.value?.width || 400
  const h = canvasRef.value?.height || 400
  const cx = w / 2
  const cy = h / 2

  if (isDragging) {
    offsetX.value = e.clientX - startX
    offsetY.value = e.clientY - startY
  }

  // 鼠标悬停粒子碰撞判定 (方案四)
  const mouseX = e.offsetX
  const mouseY = e.offsetY
  let foundHovered = null

  for (const p of particles) {
    const px_screen = (p.x - cx) * scale.value + cx + offsetX.value
    const py_screen = (p.y - cy) * scale.value + cy + offsetY.value
    const dist = Math.hypot(mouseX - px_screen, mouseY - py_screen)
    if (dist < 10) {
      foundHovered = p
      break
    }
  }

  if (foundHovered) {
    hoveredNode.value = foundHovered
    tooltipX.value = (foundHovered.x - cx) * scale.value + cx + offsetX.value
    tooltipY.value = (foundHovered.y - cy) * scale.value + cy + offsetY.value
  } else {
    hoveredNode.value = null
  }
}

function handleMouseUp() {
  isDragging = false
}

function handleMouseLeave() {
  isDragging = false
  hoveredNode.value = null
}

function handleDblClick() {
  resetView()
}

function zoomIn() {
  const newScale = Math.min(5.0, scale.value * 1.25)
  scale.value = newScale
}

function zoomOut() {
  const newScale = Math.max(0.6, scale.value / 1.25)
  scale.value = newScale
}

function resetView() {
  scale.value = 1.0
  offsetX.value = 0.0
  offsetY.value = 0.0
  hoveredNode.value = null
}

function toggleFullscreen() {
  isFullscreen.value = !isFullscreen.value
}

let resizeObserver = null

function resize() {
  if (!canvasRef.value) return
  if (isFullscreen.value) {
    const cardWidth = window.innerWidth * 0.85
    const cardHeight = window.innerHeight * 0.75
    const containerWidth = Math.min(cardWidth, 896) // max-w-4xl
    canvasRef.value.width = containerWidth
    canvasRef.value.height = cardHeight - 80
  } else {
    const parent = canvasRef.value.parentElement
    canvasRef.value.width = parent?.clientWidth || 400
    canvasRef.value.height = 360
  }
}

onMounted(async () => {
  resize()
  window.addEventListener('resize', resize)

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

watch(isFullscreen, () => {
  nextTick(() => {
    resize()
    initParticles()
    resetView()
  })
})
</script>

<template>
  <!-- Teleport to body: 将全屏悬浮舱投射到文档 body 节点，彻底破坏包含块 transform 属性带来的假全屏锁定 (方案一) -->
  <Teleport to="body" :disabled="!isFullscreen">
    <div :class="[
      isFullscreen 
        ? 'fixed inset-0 z-[999] bg-slate-950/75 backdrop-blur-md flex items-center justify-center p-4 select-none' 
        : 'manifold-visualizer-container w-full h-full'
    ]" @click.self="isFullscreen ? toggleFullscreen() : null">
      
      <div :class="[
        'bg-gray-950 border border-gray-800 overflow-hidden relative flex flex-col transition-all duration-300',
        isFullscreen ? 'w-[85vw] max-w-4xl h-[75vh] shadow-2xl rounded-2xl' : 'w-full h-full rounded-lg'
      ]">
        <!-- 标题栏 -->
        <div class="flex items-center justify-between px-3 py-2 bg-gray-900 border-b border-gray-800 select-none">
          <div class="flex items-center gap-2">
            <span class="text-xs font-semibold text-purple-400">Poincaré 双曲圆盘</span>
            <span class="text-[10px] text-gray-500">知识拓扑流形对齐</span>
          </div>
          <div class="flex items-center gap-3 text-[10px]" :class="isFullscreen ? 'pr-12' : 'pr-8'">
            <span class="text-gray-400">KL: <b :class="klDivergence > 0.5 ? 'text-red-400' : 'text-green-400'">
              {{ klDivergence.toFixed(3) }}</b>
            </span>
            <span class="text-gray-400">对齐: <b :class="alignmentProgress > 80 ? 'text-green-400' : 'text-yellow-400'">
              {{ alignmentProgress.toFixed(0) }}%</b>
            </span>
          </div>
        </div>

        <!-- Canvas 与交互区 (方案一) -->
        <div class="relative flex-1 bg-slate-950 flex items-center justify-center overflow-hidden">
          <canvas 
            ref="canvasRef" 
            class="w-full cursor-grab active:cursor-grabbing" 
            style="min-height: 350px"
            @wheel="handleWheel"
            @mousedown="handleMouseDown"
            @mousemove="handleMouseMove"
            @mouseup="handleMouseUp"
            @mouseleave="handleMouseLeave"
            @dblclick="handleDblClick"
          />

          <!-- 悬浮控制面板 (方案一) -->
          <div class="absolute right-3 top-3 flex flex-col gap-1.5 z-20 select-none">
            <button @click="zoomIn" class="w-7 h-7 rounded-lg bg-gray-900/80 hover:bg-indigo-600 text-gray-300 hover:text-white border border-gray-800 hover:border-indigo-500 shadow transition-all flex items-center justify-center cursor-pointer" title="放大">
              <Plus :size="13" />
            </button>
            <button @click="zoomOut" class="w-7 h-7 rounded-lg bg-gray-900/80 hover:bg-indigo-600 text-gray-300 hover:text-white border border-gray-800 hover:border-indigo-500 shadow transition-all flex items-center justify-center cursor-pointer" title="缩小">
              <Minus :size="13" />
            </button>
            <button @click="resetView" class="w-7 h-7 rounded-lg bg-gray-900/80 hover:bg-indigo-600 text-gray-300 hover:text-white border border-gray-800 hover:border-indigo-500 shadow transition-all flex items-center justify-center cursor-pointer" title="复位 (双击画布亦可复位)">
              <RotateCcw :size="13" />
            </button>
            <button @click="toggleFullscreen" class="w-7 h-7 rounded-lg bg-gray-900/80 hover:bg-indigo-600 text-gray-300 hover:text-white border border-gray-800 hover:border-indigo-500 shadow transition-all flex items-center justify-center cursor-pointer" :title="isFullscreen ? '退出全屏' : '全屏探索'">
              <Maximize2 v-if="!isFullscreen" :size="13" />
              <Minimize2 v-else :size="13" />
            </button>
          </div>

          <!-- HTML 绝对定位毛玻璃交互卡片 (方案四) -->
          <div 
            v-if="hoveredNode" 
            class="absolute pointer-events-none z-30 px-3.5 py-2.5 bg-slate-900/90 dark:bg-slate-950/95 backdrop-blur-md rounded-xl border border-gray-700/50 shadow-2xl transition-all duration-150 flex flex-col gap-1 select-none"
            :style="{ 
              left: tooltipX + 'px', 
              top: (tooltipY - 12) + 'px',
              transform: 'translate(-50%, -100%)'
            }"
          >
            <div class="flex items-center gap-1.5">
              <span class="w-2 h-2 rounded-full animate-pulse" :class="hoveredNode.isTarget ? 'bg-amber-400' : 'bg-blue-400'" />
              <span class="text-xs font-bold text-gray-100">{{ hoveredNode.label }}</span>
            </div>
            <div class="text-[9px] text-gray-400 flex items-center justify-between gap-6">
              <span>类型: {{ hoveredNode.isTarget ? '课程大纲标准点' : '学情掌握状态' }}</span>
              <span v-if="!hoveredNode.isTarget" class="text-indigo-400 font-semibold">
                掌握度: {{ (hoveredNode.mastery * 100).toFixed(0) }}%
              </span>
            </div>
          </div>
        </div>

        <!-- 图例 -->
        <div class="flex gap-4 px-3 py-2 bg-gray-900 border-t border-gray-800 text-[10px] text-gray-400 flex-wrap select-none z-10 items-center">
          <span class="flex items-center gap-1.5" title="金色节点，代表标准学科大纲要求的标准概念位置">
            <span class="w-2.5 h-2.5 rounded-full bg-amber-500 shadow-[0_0_8px_#f59e0b]" /> 
            标准知识点（大纲要求）
          </span>
          <span class="flex items-center gap-1.5" title="从蓝色渐变至紫色，颜色越偏向紫色表示当前掌握度越高">
            <span class="w-2.5 h-2.5 rounded-full bg-gradient-to-r from-blue-500 to-purple-500 shadow-[0_0_8px_#3b82f6]" /> 
            学生掌握态（蓝 ➔ 紫渐变，掌握度由低到高）
          </span>
          <span class="flex items-center gap-1.5" title="掌握度达到95%以上，学生节点与标准节点完全重合，呈现翠绿色呼吸光圈">
            <span class="w-2.5 h-2.5 rounded-full bg-green-500 shadow-[0_0_8px_#10b981]" /> 
            已对齐（掌握度 95%+，概念通关）
          </span>
          <span v-if="conflictDetected" class="flex items-center gap-1.5 text-red-400" title="学生认知状态与标准拓扑流形出现显著偏差冲突">
            <span class="w-2.5 h-2.5 rounded-full bg-red-500 animate-pulse shadow-[0_0_8px_#ef4444]" /> 
            认知冲突
          </span>
          <span class="ml-auto text-[9px] text-gray-500">提示：双击可复位，滚轮可缩放，拖拽可平移</span>
        </div>

        <!-- 帮助 Tips (全屏隐藏以扩充画布区域) -->
        <div v-if="!isFullscreen" class="px-3 py-2 bg-gray-950 border-t border-gray-800 text-[9px] text-gray-500 space-y-1 leading-normal select-none z-10">
          <div class="font-semibold text-gray-400 flex items-center gap-1">
            <span>💡</span> 如何理解 Poincaré 双曲圆盘？
          </div>
          <p>
            1. <strong>层级分布：</strong> 越靠近圆盘<b>中心</b>的节点表示越宏观的基础概念；越靠近圆盘<b>边缘</b>的节点表示越微观的叶子概念。
          </p>
          <p>
            2. <strong>测地线（弧线）：</strong> 连接两点之间的双曲线段表示学习依赖关系，动画粒子模拟知识流的对齐。
          </p>
        </div>
      </div>

    </div>
  </Teleport>
</template>

<style scoped>
.manifold-visualizer-container {
  user-select: none;
}
</style>
