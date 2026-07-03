<script setup>
import { useRouter } from 'vue-router'
import { ref, onMounted, onUnmounted } from 'vue'
import { BrainCircuit, ArrowRight } from '@lucide/vue'

const router = useRouter()
const canvasRef = ref(null)

let animationFrameId = null
let dots = []

const initCanvas = () => {
  const canvas = canvasRef.value
  if (!canvas) return
  const ctx = canvas.getContext('2d')
  
  const resize = () => {
    canvas.width = canvas.parentElement.clientWidth
    canvas.height = canvas.parentElement.clientHeight
  }
  resize()
  window.addEventListener('resize', resize)
  
  // Create nodes/dots for the topology flow
  const count = 15
  dots = []
  for (let i = 0; i < count; i++) {
    dots.push({
      x: Math.random() * canvas.width,
      y: Math.random() * canvas.height,
      vx: (Math.random() - 0.5) * 0.4,
      vy: (Math.random() - 0.5) * 0.4,
      radius: Math.random() * 3 + 3,
      label: ['CNN', 'RNN', 'Linear', 'SVM', 'GraphRAG', 'Gradient', 'Entropy', 'Adam', 'VisRAG', 'Socratic'][i % 10]
    })
  }
  
  const draw = () => {
    ctx.clearRect(0, 0, canvas.width, canvas.height)
    
    // Draw connections
    ctx.lineWidth = 0.5
    for (let i = 0; i < dots.length; i++) {
      for (let j = i + 1; j < dots.length; j++) {
        const dx = dots[i].x - dots[j].x
        const dy = dots[i].y - dots[j].y
        const dist = Math.sqrt(dx * dx + dy * dy)
        if (dist < 150) {
          ctx.strokeStyle = `rgba(14, 165, 233, ${0.15 * (1 - dist / 150)})`
          ctx.beginPath()
          ctx.moveTo(dots[i].x, dots[i].y)
          ctx.lineTo(dots[j].x, dots[j].y)
          ctx.stroke()
        }
      }
    }
    
    // Draw dots and text labels
    dots.forEach(dot => {
      dot.x += dot.vx
      dot.y += dot.vy
      
      // Bounce off walls
      if (dot.x < 0 || dot.x > canvas.width) dot.vx *= -1
      if (dot.y < 0 || dot.y > canvas.height) dot.vy *= -1
      
      // Draw glow
      ctx.shadowBlur = 8
      ctx.shadowColor = '#0ea5e9'
      ctx.fillStyle = 'rgba(16, 185, 129, 0.7)'
      ctx.beginPath()
      ctx.arc(dot.x, dot.y, dot.radius, 0, Math.PI * 2)
      ctx.fill()
      
      // Draw text
      ctx.shadowBlur = 0
      ctx.fillStyle = 'rgba(243, 244, 246, 0.5)'
      ctx.font = '10px Inter, sans-serif'
      ctx.fillText(dot.label, dot.x + 8, dot.y + 4)
    })
    
    animationFrameId = requestAnimationFrame(draw)
  }
  
  draw()
  
  return () => {
    window.removeEventListener('resize', resize)
    cancelAnimationFrame(animationFrameId)
  }
}

let destroyCanvas = null
onMounted(() => {
  destroyCanvas = initCanvas()
})

onUnmounted(() => {
  if (destroyCanvas) destroyCanvas()
})

function start() {
  router.push('/login')
}
</script>

<template>
  <div class="min-h-screen bg-[#0b0f19] text-[#f3f4f6] flex flex-col md:flex-row relative overflow-hidden font-sans">
    <!-- Fine grain overlay -->
    <div class="absolute inset-0 bg-noise opacity-[0.02] pointer-events-none"></div>
    
    <!-- Decorative background glow lines -->
    <div class="absolute top-[-10%] left-[-10%] w-[50%] h-[50%] bg-[#0ea5e9] opacity-[0.03] blur-[150px] rounded-full pointer-events-none"></div>
    <div class="absolute bottom-[-10%] right-[-10%] w-[50%] h-[50%] bg-[#10b981] opacity-[0.03] blur-[150px] rounded-full pointer-events-none"></div>
    
    <!-- Left Hero content -->
    <div class="w-full md:w-[45%] flex flex-col justify-center p-8 md:p-16 z-10 relative">
      <div class="flex items-center gap-3 mb-6">
        <div class="w-10 h-10 rounded-xl bg-gradient-to-br from-[#0ea5e9] to-[#10b981] flex items-center justify-center shadow-lg">
          <BrainCircuit :size="20" class="text-[#0b0f19]" />
        </div>
        <span class="text-sm font-semibold tracking-wider uppercase text-gray-400">EduMatrix AI</span>
      </div>
      
      <h1 class="text-4xl md:text-5xl font-extrabold tracking-tight mb-4 leading-tight">
        EduMatrix <br/>
        <span class="bg-gradient-to-r from-[#0ea5e9] to-[#10b981] bg-clip-text text-transparent">智教矩阵系统</span>
      </h1>
      
      <p class="text-base md:text-lg text-[#9ca3af] mb-8 leading-relaxed">
        基于 GraphRAG 与 1+3+5 多智能体协同矩阵构建的个性化自适应教育系统。为您打通概念可视化、动态诊断、代码沙箱与跨学科苏格拉底式对话的完整学情对齐链路。
      </p>
      
      <div>
        <button 
          @click="start"
          class="group relative inline-flex items-center gap-2 px-6 py-3 bg-gradient-to-r from-[#0ea5e9] to-[#10b981] text-[#0b0f19] font-bold rounded-xl shadow-lg hover:brightness-110 transition-all overflow-hidden"
        >
          <span>进入学习矩阵</span>
          <ArrowRight :size="16" class="group-hover:translate-x-1 transition-transform" />
        </button>
      </div>
    </div>
    
    <!-- Right Interactive Topology Graph -->
    <div class="w-full md:w-[55%] h-[300px] md:h-auto relative bg-[#0d121f] border-t md:border-t-0 md:border-l border-white/[0.05]">
      <canvas ref="canvasRef" class="w-full h-full block"></canvas>
      <div class="absolute inset-0 bg-gradient-to-t md:bg-gradient-to-r from-[#0b0f19] via-transparent to-transparent pointer-events-none"></div>
    </div>
  </div>
</template>

<style scoped>
/* Smooth texture bg */
.bg-noise {
  background-image: url("data:image/svg+xml,%3Csvg viewBox='0 0 200 200' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='noiseFilter'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.65' numOctaves='3' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23noiseFilter)'/%3E%3C/svg%3E");
}
</style>
