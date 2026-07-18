<script setup>
import { useRouter } from 'vue-router'
import { ref, onMounted, onUnmounted } from 'vue'
import {
  Activity, ArrowRight, BrainCircuit, Check, Network,
  Orbit, Play, Sparkles, BookOpen, Route, ShieldCheck, LineChart, Layers3,
} from '@lucide/vue'

const router = useRouter()
const canvasRef = ref(null)
const landingRef = ref(null)
const scrollProgress = ref(0)
let revealObserver = null
let scrollRoot = null
let onScroll = null

let animationFrameId = null
let dots = []
let destroyCanvas = null

const initCanvas = () => {
  const canvas = canvasRef.value
  if (!canvas) return

  const ctx = canvas.getContext('2d')
  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches
  const pointer = { x: 0, y: 0, active: false }

  const resize = () => {
    const bounds = canvas.parentElement.getBoundingClientRect()
    const pixelRatio = Math.min(window.devicePixelRatio || 1, 2)
    canvas.width = Math.max(1, Math.floor(bounds.width * pixelRatio))
    canvas.height = Math.max(1, Math.floor(bounds.height * pixelRatio))
    canvas.style.width = `${bounds.width}px`
    canvas.style.height = `${bounds.height}px`
    ctx.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0)

    if (!dots.length) {
      const labels = ['GraphRAG', 'Socratic', 'Vision', 'Concept', 'Memory', 'Path', 'Quiz', 'Agent', 'Insight', 'Focus', 'Mastery', 'Review']
      dots = labels.map((label, index) => ({
        x: bounds.width * (0.12 + Math.random() * 0.76),
        y: bounds.height * (0.1 + Math.random() * 0.8),
        vx: (Math.random() - 0.5) * 0.18,
        vy: (Math.random() - 0.5) * 0.18,
        radius: index % 4 === 0 ? 4.5 : 2.6,
        label,
        accent: index % 3,
      }))
    }
  }

  const updatePointer = (event) => {
    const bounds = canvas.getBoundingClientRect()
    pointer.x = event.clientX - bounds.left
    pointer.y = event.clientY - bounds.top
    pointer.active = true
  }

  const clearPointer = () => {
    pointer.active = false
  }

  const draw = () => {
    const width = canvas.clientWidth
    const height = canvas.clientHeight
    ctx.clearRect(0, 0, width, height)

    const halo = ctx.createRadialGradient(width * 0.52, height * 0.46, 0, width * 0.52, height * 0.46, Math.max(width, height) * 0.52)
    halo.addColorStop(0, 'rgba(56, 189, 248, 0.09)')
    halo.addColorStop(0.52, 'rgba(99, 102, 241, 0.025)')
    halo.addColorStop(1, 'rgba(8, 15, 30, 0)')
    ctx.fillStyle = halo
    ctx.fillRect(0, 0, width, height)

    for (let i = 0; i < dots.length; i += 1) {
      for (let j = i + 1; j < dots.length; j += 1) {
        const distance = Math.hypot(dots[i].x - dots[j].x, dots[i].y - dots[j].y)
        if (distance < 180) {
          const opacity = 0.2 * (1 - distance / 180)
          const gradient = ctx.createLinearGradient(dots[i].x, dots[i].y, dots[j].x, dots[j].y)
          gradient.addColorStop(0, `rgba(103, 232, 249, ${opacity})`)
          gradient.addColorStop(1, `rgba(129, 140, 248, ${opacity * 0.55})`)
          ctx.strokeStyle = gradient
          ctx.lineWidth = 0.8
          ctx.beginPath()
          ctx.moveTo(dots[i].x, dots[i].y)
          ctx.lineTo(dots[j].x, dots[j].y)
          ctx.stroke()
        }
      }
    }

    dots.forEach((dot) => {
      if (!reduceMotion) {
        dot.x += dot.vx
        dot.y += dot.vy
      }

      if (pointer.active) {
        const dx = pointer.x - dot.x
        const dy = pointer.y - dot.y
        const distance = Math.hypot(dx, dy)
        if (distance < 150 && distance > 0) {
          dot.x -= (dx / distance) * 0.16
          dot.y -= (dy / distance) * 0.16
        }
      }

      if (dot.x < 20 || dot.x > width - 20) dot.vx *= -1
      if (dot.y < 20 || dot.y > height - 20) dot.vy *= -1

      const colors = ['#67e8f9', '#818cf8', '#5eead4']
      const color = colors[dot.accent]
      ctx.shadowBlur = 18
      ctx.shadowColor = color
      ctx.fillStyle = color
      ctx.beginPath()
      ctx.arc(dot.x, dot.y, dot.radius, 0, Math.PI * 2)
      ctx.fill()

      ctx.shadowBlur = 0
      ctx.fillStyle = 'rgba(219, 234, 254, 0.58)'
      ctx.font = '500 10px Inter, system-ui, sans-serif'
      ctx.fillText(dot.label, dot.x + 10, dot.y + 4)
    })

    animationFrameId = requestAnimationFrame(draw)
  }

  resize()
  draw()
  window.addEventListener('resize', resize)
  canvas.addEventListener('pointermove', updatePointer)
  canvas.addEventListener('pointerleave', clearPointer)

  return () => {
    window.removeEventListener('resize', resize)
    canvas.removeEventListener('pointermove', updatePointer)
    canvas.removeEventListener('pointerleave', clearPointer)
    cancelAnimationFrame(animationFrameId)
  }
}

onMounted(() => {
  destroyCanvas = initCanvas()

  scrollRoot = landingRef.value
  if (scrollRoot) {
    onScroll = () => {
      const maxScroll = scrollRoot.scrollHeight - scrollRoot.clientHeight
      scrollProgress.value = maxScroll > 0 ? Math.min(100, (scrollRoot.scrollTop / maxScroll) * 100) : 0
    }
    scrollRoot.addEventListener('scroll', onScroll, { passive: true })
    onScroll()

    revealObserver = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          entry.target.classList.add('is-visible')
          revealObserver?.unobserve(entry.target)
        }
      })
    }, { root: scrollRoot, threshold: 0.14 })
    scrollRoot.querySelectorAll('.reveal').forEach((element) => revealObserver.observe(element))
  }
})

onUnmounted(() => {
  if (destroyCanvas) destroyCanvas()
  if (scrollRoot && onScroll) scrollRoot.removeEventListener('scroll', onScroll)
  revealObserver?.disconnect()
})

function start() {
  router.push('/login')
}
</script>

<template>
  <div ref="landingRef" class="landing-page relative h-screen overflow-y-auto overflow-x-hidden text-[#f5f9ff]">
    <div class="landing-progress" :style="{ width: `${scrollProgress}%` }" />
    <div class="landing-grid pointer-events-none absolute inset-0" />
    <div class="landing-noise pointer-events-none absolute inset-0 opacity-[0.025]" />
    <div class="landing-orb landing-orb-cyan pointer-events-none absolute rounded-full" />
    <div class="landing-orb landing-orb-indigo pointer-events-none absolute rounded-full" />

    <header class="landing-header relative z-20 mx-auto flex w-full max-w-[1440px] items-center justify-between px-6 py-5 lg:px-10">
      <a class="landing-brand" href="#hero" aria-label="EduMatrix 首页">
        <span class="brand-mark flex h-10 w-10 items-center justify-center rounded-[14px]"><BrainCircuit :size="20" stroke-width="1.8" /></span>
        <span><strong>EduMatrix</strong><small>INTELLIGENT LEARNING OS</small></span>
      </a>
      <nav class="landing-nav hidden items-center gap-7 lg:flex" aria-label="首页导航">
        <a href="#experience">能力矩阵</a>
        <a href="#method">学习方法</a>
        <a href="#signal">数据回响</a>
      </nav>
      <button class="ghost-entry group inline-flex items-center gap-2 rounded-full px-4 py-2 text-xs font-medium" @click="start">
        登录学习空间 <ArrowRight :size="13" class="transition-transform duration-300 group-hover:translate-x-0.5" />
      </button>
    </header>

    <main class="relative z-10">
      <section id="hero" class="hero-section mx-auto grid min-h-[calc(100vh-84px)] w-full max-w-[1440px] items-center gap-12 px-6 pb-20 pt-8 lg:grid-cols-[0.88fr_1.12fr] lg:px-10 lg:pb-28 lg:pt-0">
        <div class="hero-copy max-w-[660px]">
          <div class="hero-kicker mb-7 inline-flex items-center gap-2 rounded-full px-3 py-1.5 text-[11px] font-semibold tracking-[0.08em]">
            <Sparkles :size="13" class="text-cyan-300" /> AI 驱动的个性化教学矩阵 <span class="h-1 w-1 rounded-full bg-cyan-300 shadow-[0_0_10px_#67e8f9]" />
          </div>
          <h1 class="hero-title text-[clamp(2.85rem,6vw,5.8rem)] font-semibold leading-[0.96] tracking-[-0.055em] text-white">
            <span>让每一次学习</span><span class="hero-gradient">都有清晰回响。</span>
          </h1>
          <p class="hero-lede mt-7 max-w-[580px] text-[15px] leading-7 md:text-base">将知识图谱、智能诊断与多智能体教学融入同一个学习空间。系统理解你的节奏，减少无效重复，让复杂知识变得可感知、可追踪、可掌握。</p>
          <div class="mt-9 flex flex-wrap items-center gap-4">
            <button class="primary-entry group relative inline-flex items-center gap-3 overflow-hidden rounded-2xl px-6 py-3.5 text-sm font-semibold text-[#06111f]" @click="start"><span class="primary-entry-shine absolute inset-y-0 w-16 -skew-x-12 bg-white/35 blur-md" /><span class="relative">开启学习旅程</span><span class="relative flex h-7 w-7 items-center justify-center rounded-full bg-[#07101f]/10"><ArrowRight :size="15" /></span></button>
            <button class="secondary-entry group inline-flex items-center gap-2.5 rounded-2xl px-5 py-3.5 text-sm font-medium" @click="start"><span class="flex h-7 w-7 items-center justify-center rounded-full border border-white/10 bg-white/[0.04]"><Play :size="12" class="ml-0.5 fill-current text-cyan-200" /></span>探索智能课堂</button>
          </div>
          <div class="hero-proof mt-10 flex flex-wrap gap-x-6 gap-y-3 text-[11px]">
            <span v-for="item in ['专注模式', '认知负荷调节', '学习路径可视化']" :key="item"><i><Check :size="9" stroke-width="2.5" /></i>{{ item }}</span>
          </div>
        </div>

        <section class="hero-visual relative mx-auto w-full max-w-[760px] lg:mx-0" aria-label="学习矩阵实时预览">
          <div class="visual-aura pointer-events-none absolute inset-[12%] rounded-full blur-3xl" />
          <div class="matrix-frame relative aspect-[1.12/0.9] min-h-[430px] overflow-hidden rounded-[32px]">
            <canvas ref="canvasRef" class="absolute inset-0 h-full w-full" />
            <div class="scan-beam pointer-events-none absolute inset-x-0 h-px" />
            <div class="matrix-vignette pointer-events-none absolute inset-0" />
            <div class="status-pill absolute left-5 top-5 flex items-center gap-2 rounded-full px-3 py-2 text-[10px] font-semibold tracking-[0.08em] md:left-7 md:top-7"><span class="relative flex h-2 w-2"><span class="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-300 opacity-50" /><span class="relative inline-flex h-2 w-2 rounded-full bg-emerald-300" /></span>LEARNING MATRIX ONLINE</div>
            <div class="core-orbit pointer-events-none absolute left-1/2 top-1/2 flex h-32 w-32 -translate-x-1/2 -translate-y-1/2 items-center justify-center rounded-full md:h-40 md:w-40"><div class="orbit-ring orbit-ring-one absolute inset-0 rounded-full" /><div class="orbit-ring orbit-ring-two absolute inset-5 rounded-full" /><div class="core-mark flex h-16 w-16 items-center justify-center rounded-[22px] text-cyan-100 md:h-[72px] md:w-[72px]"><Orbit :size="30" stroke-width="1.35" /></div></div>
            <div class="metric-card metric-card-top absolute right-4 top-[17%] w-[172px] rounded-2xl p-3.5 md:right-7 md:w-[190px]"><div class="flex items-center justify-between"><span class="text-[10px] font-medium text-slate-400">认知状态</span><Activity :size="13" class="text-emerald-300" /></div><div class="mt-2 flex items-end gap-2"><span class="text-2xl font-semibold tracking-tight text-white">92%</span><span class="mb-1 text-[9px] font-semibold text-emerald-300">专注稳定</span></div><div class="mt-3 flex h-7 items-end gap-1"><span v-for="height in [28, 42, 34, 58, 48, 72, 66, 86, 78, 92]" :key="height" class="metric-bar flex-1 rounded-full" :style="{ height: `${height}%` }" /></div></div>
            <div class="metric-card metric-card-bottom absolute bottom-[9%] left-4 w-[188px] rounded-2xl p-3.5 md:bottom-[12%] md:left-7 md:w-[216px]"><div class="flex items-center gap-2"><span class="flex h-8 w-8 items-center justify-center rounded-xl bg-indigo-300/10 text-indigo-200"><Network :size="15" /></span><div><div class="text-[10px] text-slate-500">知识网络</div><div class="mt-0.5 text-xs font-medium text-slate-100">12 个概念已建立连接</div></div></div><div class="mt-3 flex gap-1.5"><span v-for="index in 7" :key="index" class="h-1.5 flex-1 rounded-full" :class="index < 6 ? 'bg-gradient-to-r from-cyan-300/80 to-indigo-300/80' : 'bg-white/8'" /></div></div>
            <div class="absolute bottom-5 right-5 hidden items-center gap-2 text-[9px] font-semibold tracking-[0.12em] text-slate-600 sm:flex md:bottom-7 md:right-7"><span>ADAPTIVE ENGINE</span><span class="h-px w-8 bg-gradient-to-r from-slate-700 to-transparent" /><span>V2.4</span></div>
          </div>
        </section>
        <a class="scroll-cue" href="#experience"><span class="scroll-cue__line" />向下探索<span class="scroll-cue__line" /></a>
      </section>

      <section id="experience" class="landing-section reveal mx-auto max-w-[1440px] px-6 py-24 lg:px-10 lg:py-36">
        <div class="section-heading"><div><span class="section-eyebrow">01 / Learning matrix</span><h2>把分散的学习动作，<em>连成一条清晰路径。</em></h2></div><p>从理解、练习到复习，每一个节点都由真实学习信号驱动，系统只在需要的时候出现。</p></div>
        <div class="signal-grid mt-14">
          <article class="signal-card signal-card--wide"><div class="signal-card__icon"><Layers3 :size="18" /></div><span>知识网络</span><h3>看见知识之间的关系</h3><p>把文档、对话、错题和笔记汇聚成可追踪的知识网络，不再只记住孤立答案。</p><div class="signal-map"><span v-for="node in ['概念', '路径', '复习', '洞察', '掌握']" :key="node">{{ node }}</span></div></article>
          <article class="signal-card"><div class="signal-card__icon signal-card__icon--teal"><LineChart :size="18" /></div><span>学习趋势</span><h3>每一天都有可见进步</h3><p>用趋势而不是一次分数，理解你的状态与节奏。</p><div class="mini-chart"><i v-for="height in [32, 45, 38, 62, 56, 78, 92]" :key="height" :style="{ height: `${height}%` }" /></div></article>
          <article class="signal-card"><div class="signal-card__icon signal-card__icon--purple"><ShieldCheck :size="18" /></div><span>智能守护</span><h3>在遗忘发生前提醒你</h3><p>根据掌握度、认知负荷和复习间隔，自动给出刚刚好的下一步。</p><div class="signal-progress"><span style="width: 78%" /></div><small>复习节奏稳定度 <b>78%</b></small></article>
        </div>
      </section>

      <section id="method" class="method-section reveal">
        <div class="method-section__inner mx-auto grid max-w-[1440px] gap-16 px-6 py-24 lg:grid-cols-[.72fr_1.28fr] lg:px-10 lg:py-36">
          <div class="method-sticky"><span class="section-eyebrow">02 / Adaptive method</span><h2>不是更多功能，<br /><em>是更少的干扰。</em></h2><p>EduMatrix 将复杂的教学系统藏在顺手的操作之后，让你始终知道现在该做什么、为什么做、下一步是什么。</p><button class="method-link" @click="start">进入学习空间 <ArrowRight :size="14" /></button></div>
          <div class="method-rail">
            <article v-for="(step, index) in [{ icon: BookOpen, title: '先理解', copy: '用对话、讲义和可视化内容建立第一层直觉。', meta: 'CONTEXT' }, { icon: Route, title: '再推进', copy: '根据前置依赖和目标，动态编译属于你的学习路径。', meta: 'PATH' }, { icon: BrainCircuit, title: '最后掌握', copy: '用检索练习、错题回放和间隔复习，把理解变成稳定能力。', meta: 'MASTERY' }]" :key="step.title" class="method-step"><div class="method-step__index">0{{ index + 1 }}</div><div class="method-step__icon"><component :is="step.icon" :size="19" /></div><div><span>{{ step.meta }}</span><h3>{{ step.title }}</h3><p>{{ step.copy }}</p></div><ArrowRight class="method-step__arrow" :size="17" /></article>
          </div>
        </div>
      </section>

      <section id="signal" class="signal-section reveal mx-auto max-w-[1440px] px-6 py-24 lg:px-10 lg:py-36">
        <div class="section-heading section-heading--center"><div><span class="section-eyebrow">03 / A calmer dashboard</span><h2>让数据回答问题，<em>而不是制造压力。</em></h2></div><p>从今天的焦点到长期趋势，每一个数字都对应一个可执行的动作。</p></div>
        <div class="signal-metrics mt-14"><div><strong>92%</strong><span>专注状态</span><small>实时认知负荷</small></div><div><strong>5D</strong><span>自适应资源</span><small>讲义 / 思维导图 / 代码 / 测验 / 视频</small></div><div><strong>1→∞</strong><span>学习路径</span><small>从当前概念自然推进</small></div><div><strong>24/7</strong><span>学习回响</span><small>每次练习都会让系统更懂你</small></div></div>
      </section>

      <section class="landing-cta reveal mx-auto max-w-[1440px] px-6 pb-24 lg:px-10 lg:pb-36"><div class="landing-cta__inner"><span class="section-eyebrow">Start with one concept</span><h2>从一个知识点开始，<br /><em>把学习变成自己的系统。</em></h2><button class="primary-entry group inline-flex items-center gap-3 rounded-2xl px-6 py-3.5 text-sm font-semibold text-[#06111f]" @click="start">开启学习旅程 <ArrowRight :size="15" class="transition-transform group-hover:translate-x-0.5" /></button></div></section>
    </main>
    <footer class="landing-footer mx-auto flex max-w-[1440px] items-center justify-between px-6 py-7 lg:px-10"><span>© EduMatrix / Adaptive learning OS</span><span>把理解，变成能力。</span></footer>
  </div>
</template>

<style scoped>
.landing-page {
  background:
    radial-gradient(circle at 70% 20%, rgba(39, 88, 143, 0.18), transparent 34rem),
    radial-gradient(circle at 12% 78%, rgba(29, 118, 126, 0.08), transparent 28rem),
    #07101f;
}

.landing-grid {
  background-image:
    linear-gradient(rgba(148, 163, 184, 0.035) 1px, transparent 1px),
    linear-gradient(90deg, rgba(148, 163, 184, 0.035) 1px, transparent 1px);
  background-size: 64px 64px;
  mask-image: linear-gradient(to bottom, black, transparent 90%);
}

.landing-noise {
  background-image: url("data:image/svg+xml,%3Csvg viewBox='0 0 180 180' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='.8' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)' opacity='.8'/%3E%3C/svg%3E");
}

.landing-orb {
  filter: blur(110px);
  opacity: 0.12;
}

.landing-orb-cyan {
  top: -12rem;
  right: 20%;
  width: 32rem;
  height: 32rem;
  background: #22d3ee;
}

.landing-orb-indigo {
  right: -14rem;
  bottom: -18rem;
  width: 38rem;
  height: 38rem;
  background: #6366f1;
}

.brand-mark {
  color: #cffafe;
  background: linear-gradient(145deg, rgba(34, 211, 238, 0.2), rgba(99, 102, 241, 0.17));
  border: 1px solid rgba(165, 243, 252, 0.18);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.13), 0 12px 30px rgba(2, 132, 199, 0.16);
}

.ghost-entry,
.secondary-entry,
.hero-kicker,
.status-pill,
.metric-card {
  border: 1px solid rgba(148, 163, 184, 0.13);
  background: rgba(12, 25, 45, 0.58);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.045);
  backdrop-filter: blur(18px);
}

.ghost-entry:hover,
.secondary-entry:hover {
  color: #ecfeff;
  border-color: rgba(103, 232, 249, 0.28);
  background: rgba(20, 40, 66, 0.72);
}

.hero-copy {
  animation: hero-reveal 700ms cubic-bezier(0.16, 1, 0.3, 1) both;
}

.hero-gradient {
  color: transparent;
  background: linear-gradient(105deg, #f8fafc 5%, #a5f3fc 45%, #a5b4fc 88%);
  background-clip: text;
  -webkit-background-clip: text;
}

.primary-entry {
  background: linear-gradient(115deg, #a5f3fc, #67e8f9 45%, #a5b4fc);
  box-shadow: 0 14px 36px rgba(34, 211, 238, 0.16), inset 0 1px 0 rgba(255, 255, 255, 0.65);
  transition: transform 220ms ease, box-shadow 220ms ease, filter 220ms ease;
}

.primary-entry:hover {
  transform: translateY(-2px);
  filter: saturate(1.08) brightness(1.04);
  box-shadow: 0 18px 42px rgba(34, 211, 238, 0.23), inset 0 1px 0 rgba(255, 255, 255, 0.7);
}

.primary-entry-shine {
  left: -5rem;
  animation: button-shine 4.5s ease-in-out infinite;
}

.hero-visual {
  animation: visual-reveal 900ms 120ms cubic-bezier(0.16, 1, 0.3, 1) both;
}

.visual-aura {
  background: linear-gradient(135deg, rgba(34, 211, 238, 0.15), rgba(99, 102, 241, 0.16));
}

.matrix-frame {
  border: 1px solid rgba(148, 163, 184, 0.14);
  background: linear-gradient(145deg, rgba(10, 23, 43, 0.92), rgba(7, 15, 30, 0.78));
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.06),
    inset 0 0 80px rgba(8, 145, 178, 0.035),
    0 40px 100px rgba(0, 0, 0, 0.3);
}

.matrix-frame::before {
  content: '';
  position: absolute;
  inset: 0;
  border-radius: inherit;
  padding: 1px;
  background: linear-gradient(135deg, rgba(103, 232, 249, 0.18), transparent 35%, transparent 70%, rgba(129, 140, 248, 0.14));
  mask: linear-gradient(#000 0 0) content-box, linear-gradient(#000 0 0);
  mask-composite: exclude;
  pointer-events: none;
}

.scan-beam {
  top: 15%;
  z-index: 2;
  background: linear-gradient(90deg, transparent, rgba(103, 232, 249, 0.45), transparent);
  box-shadow: 0 0 18px rgba(34, 211, 238, 0.25);
  animation: scan 7s ease-in-out infinite;
}

.core-orbit {
  border: 1px solid rgba(103, 232, 249, 0.11);
  background: radial-gradient(circle, rgba(34, 211, 238, 0.08), transparent 64%);
  box-shadow: 0 0 80px rgba(34, 211, 238, 0.08);
}

.orbit-ring {
  border: 1px solid rgba(129, 140, 248, 0.22);
  border-top-color: rgba(103, 232, 249, 0.72);
  border-right-color: transparent;
}

.orbit-ring-one { animation: spin 16s linear infinite; }
.orbit-ring-two { animation: spin 10s linear infinite reverse; }

.core-mark {
  border: 1px solid rgba(165, 243, 252, 0.18);
  background: linear-gradient(145deg, rgba(34, 211, 238, 0.16), rgba(99, 102, 241, 0.13));
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.1), 0 0 36px rgba(34, 211, 238, 0.14);
}

.metric-card {
  z-index: 3;
  transition: transform 260ms ease, border-color 260ms ease, background 260ms ease;
}

.metric-card:hover {
  border-color: rgba(103, 232, 249, 0.22);
  background: rgba(15, 32, 56, 0.76);
}

.metric-card-top { animation: card-float 6s ease-in-out infinite; }
.metric-card-bottom { animation: card-float 7s 1s ease-in-out infinite reverse; }

.metric-bar {
  min-width: 3px;
  background: linear-gradient(to top, rgba(99, 102, 241, 0.35), rgba(103, 232, 249, 0.88));
  box-shadow: 0 0 8px rgba(103, 232, 249, 0.09);
}

@keyframes hero-reveal {
  from { opacity: 0; transform: translateY(18px); }
  to { opacity: 1; transform: translateY(0); }
}

@keyframes visual-reveal {
  from { opacity: 0; transform: translateY(22px) scale(0.98); }
  to { opacity: 1; transform: translateY(0) scale(1); }
}

@keyframes button-shine {
  0%, 58% { transform: translateX(-3rem); opacity: 0; }
  68% { opacity: 0.7; }
  82%, 100% { transform: translateX(22rem); opacity: 0; }
}

@keyframes scan {
  0%, 100% { transform: translateY(0); opacity: 0; }
  15% { opacity: 0.65; }
  72% { opacity: 0.38; }
  85% { transform: translateY(430px); opacity: 0; }
}

@keyframes card-float {
  0%, 100% { transform: translate3d(0, 0, 0); }
  50% { transform: translate3d(0, -7px, 0); }
}

@media (max-width: 1023px) {
  .hero-copy { max-width: 760px; }
  .matrix-frame { min-height: 520px; }
}

@media (max-width: 640px) {
  .landing-grid { background-size: 44px 44px; }
  .hero-title { letter-spacing: -0.045em; }
  .matrix-frame { min-height: 410px; border-radius: 24px; }
  .metric-card-top { top: 18%; right: 0.75rem; width: 160px; }
  .metric-card-bottom { bottom: 7%; left: 0.75rem; width: 180px; }
}

@media (prefers-reduced-motion: reduce) {
  .hero-copy,
  .hero-visual,
  .primary-entry-shine,
  .scan-beam,
  .orbit-ring,
  .metric-card {
    animation: none !important;
  }
}

/* Scroll-first landing system: brighter surfaces, stable typography, and progressive reveal. */
.landing-page {
  scroll-behavior: smooth;
  background:
    radial-gradient(circle at 73% 8%, rgba(38, 126, 160, .27), transparent 32rem),
    radial-gradient(circle at 8% 52%, rgba(37, 126, 126, .16), transparent 28rem),
    linear-gradient(180deg, #0c1e2f 0%, #0d2435 42%, #102b3a 100%);
  color: #f4f9f8;
}
.landing-page *, .landing-page :deep(*) { word-break: keep-all; }
.landing-progress { position: fixed; inset: 0 auto auto 0; z-index: 80; height: 2px; background: linear-gradient(90deg, #8deaf0, #8ba9ff, #d9c8ff); box-shadow: 0 0 18px rgba(141, 234, 240, .65); transition: width .12s linear; }
.landing-grid { opacity: .7; background-image: linear-gradient(rgba(179, 228, 230, .045) 1px, transparent 1px), linear-gradient(90deg, rgba(179, 228, 230, .045) 1px, transparent 1px); background-size: 72px 72px; mask-image: linear-gradient(to bottom, black, transparent 85%); }
.landing-noise { opacity: .018 !important; }
.landing-orb { display: none; }
.landing-header { position: sticky; top: 0; border-bottom: 1px solid rgba(181, 221, 224, .08); background: rgba(12, 30, 47, .72); backdrop-filter: blur(20px); }
.landing-brand { display: flex; align-items: center; gap: 11px; color: inherit; text-decoration: none; }
.landing-brand strong, .landing-brand small { display: block; white-space: nowrap; }
.landing-brand strong { color: #f5fbfa; font-size: 14px; font-weight: 700; }
.landing-brand small { margin-top: 2px; color: rgba(173, 231, 231, .58); font-size: 8px; font-weight: 700; letter-spacing: .2em; }
.landing-nav a { color: rgba(210, 233, 232, .62); font-size: 11px; font-weight: 560; text-decoration: none; transition: color .2s ease; white-space: nowrap; }
.landing-nav a:hover { color: #effefd; }
.ghost-entry { color: rgba(218, 239, 238, .74); border: 1px solid rgba(176, 226, 227, .14); background: rgba(102, 178, 188, .08); white-space: nowrap; transition: .22s ease; }
.ghost-entry:hover { color: #f4fffe; border-color: rgba(157, 236, 236, .42); background: rgba(104, 197, 200, .15); transform: translateY(-1px); }
.hero-section { position: relative; }
.hero-title { max-width: 700px; }
.hero-title > span { display: block; white-space: nowrap; }
.hero-lede { color: rgba(213, 235, 236, .72); }
.hero-kicker, .status-pill, .metric-card { border-color: rgba(165, 234, 233, .16); background: rgba(32, 74, 91, .44); }
.hero-kicker { color: rgba(222, 248, 246, .82); box-shadow: 0 8px 28px rgba(56, 183, 188, .08), inset 0 1px 0 rgba(255,255,255,.08); }
.hero-proof { color: rgba(189, 220, 218, .62); }
.hero-proof span { display: inline-flex; align-items: center; gap: 7px; white-space: nowrap; }
.hero-proof i { display: grid; width: 17px; height: 17px; place-items: center; color: #a2f2db; border: 1px solid rgba(162, 242, 219, .25); border-radius: 50%; background: rgba(162, 242, 219, .08); font-style: normal; }
.matrix-frame { border-color: rgba(178, 231, 235, .2); background: linear-gradient(145deg, rgba(17, 55, 71, .95), rgba(10, 30, 47, .86)); box-shadow: inset 0 1px 0 rgba(255,255,255,.1), inset 0 0 90px rgba(83, 214, 216, .09), 0 36px 100px rgba(3, 17, 30, .3); }
.matrix-vignette { background: linear-gradient(115deg, rgba(7,16,31,.36), transparent 38%, transparent 72%, rgba(7,16,31,.28)); }
.visual-aura { background: linear-gradient(135deg, rgba(83, 217, 215, .23), rgba(147, 158, 255, .22)); opacity: .88; }
.scroll-cue { position: absolute; bottom: 24px; left: 50%; display: flex; align-items: center; gap: 11px; color: rgba(190, 224, 223, .54); font-size: 9px; letter-spacing: .12em; text-decoration: none; text-transform: uppercase; transform: translateX(-50%); white-space: nowrap; }
.scroll-cue__line { width: 34px; height: 1px; background: linear-gradient(90deg, transparent, rgba(152, 229, 226, .55)); }
.scroll-cue__line:last-child { transform: rotate(180deg); }
.landing-section, .method-section, .signal-section, .landing-cta { position: relative; }
.landing-section::before, .signal-section::before { content: ''; position: absolute; top: 0; right: 6%; left: 6%; height: 1px; background: linear-gradient(90deg, transparent, rgba(191, 228, 228, .18), transparent); }
.section-heading { display: grid; grid-template-columns: minmax(0, 1fr) minmax(240px, .56fr); align-items: end; gap: 30px; }
.section-heading--center { grid-template-columns: 1fr; text-align: center; }
.section-heading--center p { max-width: 520px; margin: 0 auto; }
.section-eyebrow { display: block; margin-bottom: 13px; color: rgba(160, 235, 226, .72); font-size: 10px; font-weight: 700; letter-spacing: .14em; text-transform: uppercase; white-space: nowrap; }
.section-heading h2, .method-sticky h2, .landing-cta h2 { margin: 0; color: #f3fbf9; font-size: clamp(28px, 4vw, 55px); font-weight: 620; letter-spacing: -.055em; line-height: 1.11; }
.section-heading h2 em, .method-sticky h2 em, .landing-cta h2 em { color: #92ebeb; font-style: normal; }
.section-heading p, .method-sticky p { margin: 0; color: rgba(199, 227, 226, .62); font-size: 12px; line-height: 1.85; }
.signal-grid { display: grid; grid-template-columns: 1.2fr .9fr .9fr; gap: 15px; }
.signal-card { position: relative; min-height: 320px; overflow: hidden; padding: 25px; border: 1px solid rgba(174, 226, 225, .14); border-radius: 22px; background: rgba(29, 76, 89, .38); box-shadow: inset 0 1px 0 rgba(255,255,255,.06), 0 22px 60px rgba(2, 22, 34, .16); transition: transform .3s cubic-bezier(.22,1,.36,1), border-color .3s ease, background .3s ease; }
.signal-card:hover { border-color: rgba(157, 234, 227, .34); background: rgba(38, 96, 105, .45); transform: translateY(-5px); }
.signal-card--wide { min-height: 350px; background: linear-gradient(145deg, rgba(38, 95, 105, .58), rgba(25, 64, 82, .42)); }
.signal-card__icon { display: grid; width: 38px; height: 38px; place-items: center; color: #a5f0e2; border: 1px solid rgba(165, 240, 226, .2); border-radius: 13px; background: rgba(165, 240, 226, .08); }
.signal-card__icon--teal { color: #9fe9ef; border-color: rgba(159, 233, 239, .2); background: rgba(159, 233, 239, .08); }
.signal-card__icon--purple { color: #c0c8ff; border-color: rgba(192, 200, 255, .2); background: rgba(192, 200, 255, .08); }
.signal-card > span:not(.signal-card__icon) { display: block; margin-top: 27px; color: rgba(174, 227, 224, .56); font-size: 9px; font-weight: 700; letter-spacing: .14em; text-transform: uppercase; }
.signal-card h3 { margin: 8px 0 9px; color: #f2fbf9; font-size: 19px; font-weight: 610; letter-spacing: -.04em; white-space: nowrap; }
.signal-card p { max-width: 340px; margin: 0; color: rgba(205, 231, 230, .62); font-size: 11px; line-height: 1.8; }
.signal-map { position: absolute; right: 26px; bottom: 25px; left: 26px; display: flex; align-items: center; justify-content: space-between; padding-top: 28px; border-top: 1px solid rgba(175, 225, 223, .13); }
.signal-map::before { content: ''; position: absolute; top: 18px; right: 14%; left: 14%; height: 1px; background: linear-gradient(90deg, rgba(123,239,221,.15), rgba(123,239,221,.8), rgba(175,174,255,.15)); box-shadow: 0 0 16px rgba(123, 239, 221, .24); }
.signal-map span { position: relative; z-index: 1; padding: 7px 9px; color: rgba(212, 242, 238, .7); border: 1px solid rgba(163, 232, 224, .16); border-radius: 9px; background: #1f5a66; font-size: 9px; white-space: nowrap; }
.mini-chart { display: flex; height: 78px; align-items: end; gap: 7px; margin-top: 36px; padding: 12px 8px 0; border-bottom: 1px solid rgba(174, 226, 225, .14); }
.mini-chart i { flex: 1; min-height: 8px; border-radius: 5px 5px 0 0; background: linear-gradient(180deg, #b5f0e5, rgba(117, 203, 213, .2)); box-shadow: 0 0 16px rgba(126, 220, 216, .16); }
.signal-progress { height: 8px; margin-top: 42px; overflow: hidden; border-radius: 99px; background: rgba(182, 224, 224, .1); }
.signal-progress span { display: block; height: 100%; border-radius: inherit; background: linear-gradient(90deg, #9fe8d1, #8de5ed); box-shadow: 0 0 16px rgba(141, 229, 237, .3); }
.signal-card small { display: flex; justify-content: space-between; margin-top: 11px; color: rgba(200, 229, 226, .54); font-size: 9px; }
.signal-card small b { color: #a7ede0; font-weight: 650; }
.method-section { background: linear-gradient(180deg, rgba(4, 23, 35, .1), rgba(5, 26, 37, .36)); }
.method-section__inner { align-items: start; }
.method-sticky { position: sticky; top: 118px; }
.method-sticky p { max-width: 380px; margin-top: 19px; }
.method-link { display: inline-flex; align-items: center; gap: 8px; margin-top: 27px; padding: 0; color: #a3ede4; border: 0; background: none; font-size: 11px; font-weight: 650; cursor: pointer; white-space: nowrap; }
.method-rail { position: relative; display: grid; gap: 13px; }
.method-rail::before { content: ''; position: absolute; top: 32px; bottom: 32px; left: 18px; width: 1px; background: linear-gradient(#8be9dc, rgba(139, 233, 220, .12)); }
.method-step { position: relative; display: grid; grid-template-columns: 38px 42px 1fr auto; align-items: center; gap: 15px; min-height: 138px; padding: 22px 25px 22px 19px; border: 1px solid rgba(178, 227, 224, .12); border-radius: 20px; background: rgba(26, 71, 84, .35); transition: transform .28s ease, border-color .28s ease, background .28s ease; }
.method-step:hover { border-color: rgba(149, 233, 226, .3); background: rgba(42, 99, 105, .46); transform: translateX(5px); }
.method-step__index { color: rgba(160, 231, 224, .65); font-size: 10px; font-weight: 700; letter-spacing: .08em; }
.method-step__icon { display: grid; width: 40px; height: 40px; place-items: center; color: #b2f0e4; border: 1px solid rgba(178, 240, 228, .22); border-radius: 13px; background: rgba(178, 240, 228, .08); }
.method-step span { color: rgba(169, 225, 222, .48); font-size: 9px; font-weight: 700; letter-spacing: .14em; }
.method-step h3 { margin: 5px 0 5px; color: #f1fbf8; font-size: 18px; font-weight: 620; white-space: nowrap; }
.method-step p { margin: 0; color: rgba(204, 231, 228, .63); font-size: 11px; line-height: 1.7; }
.method-step__arrow { color: rgba(172, 231, 225, .46); transition: transform .2s ease; }
.method-step:hover .method-step__arrow { color: #b4f3e5; transform: translateX(4px); }
.signal-section { text-align: center; }
.signal-metrics { display: grid; grid-template-columns: repeat(4, 1fr); border-top: 1px solid rgba(181, 224, 222, .14); border-bottom: 1px solid rgba(181, 224, 222, .14); }
.signal-metrics > div { padding: 27px 18px; border-right: 1px solid rgba(181, 224, 222, .12); }
.signal-metrics > div:last-child { border-right: 0; }
.signal-metrics strong, .signal-metrics span, .signal-metrics small { display: block; white-space: nowrap; }
.signal-metrics strong { color: #baf2e8; font-size: 33px; font-weight: 640; letter-spacing: -.06em; }
.signal-metrics span { margin-top: 7px; color: #eefaf7; font-size: 11px; font-weight: 620; }
.signal-metrics small { margin-top: 6px; color: rgba(192, 226, 223, .51); font-size: 9px; }
.landing-cta__inner { position: relative; overflow: hidden; padding: clamp(32px, 6vw, 72px); border: 1px solid rgba(179, 228, 226, .2); border-radius: 26px; background: radial-gradient(circle at 86% 20%, rgba(106, 222, 212, .24), transparent 30%), linear-gradient(120deg, rgba(27, 85, 95, .74), rgba(28, 57, 91, .7)); box-shadow: inset 0 1px 0 rgba(255,255,255,.1), 0 26px 80px rgba(2, 20, 33, .24); }
.landing-cta__inner::after { content: ''; position: absolute; right: -70px; bottom: -170px; width: 420px; height: 420px; border: 1px solid rgba(181, 246, 235, .18); border-radius: 50%; box-shadow: 0 0 0 34px rgba(181, 246, 235, .05), 0 0 0 70px rgba(181, 246, 235, .03); }
.landing-cta h2 { max-width: 660px; margin-bottom: 31px; }
.landing-footer { color: rgba(183, 218, 216, .48); border-top: 1px solid rgba(182, 224, 223, .1); font-size: 9px; letter-spacing: .04em; }
.reveal { opacity: 0; transform: translateY(28px); transition: opacity .8s ease, transform .8s cubic-bezier(.22,1,.36,1); }
.reveal.is-visible { opacity: 1; transform: translateY(0); }

@media (max-width: 1023px) {
  .hero-title > span { white-space: normal; }
  .section-heading { grid-template-columns: 1fr; }
  .signal-grid { grid-template-columns: 1fr 1fr; }
  .signal-card--wide { grid-column: span 2; }
  .method-sticky { position: static; }
}
@media (max-width: 640px) {
  .landing-header { padding-top: 15px; padding-bottom: 15px; }
  .landing-brand small { font-size: 7px; }
  .hero-title { font-size: clamp(2.75rem, 14vw, 4.35rem); letter-spacing: -.06em; }
  .hero-lede { font-size: 13px; line-height: 1.8; }
  .matrix-frame { min-height: 410px; border-radius: 24px; }
  .scroll-cue { display: none; }
  .signal-grid, .signal-metrics { grid-template-columns: 1fr; }
  .signal-card--wide { grid-column: auto; }
  .signal-card h3 { font-size: 17px; }
  .signal-metrics > div { border-right: 0; border-bottom: 1px solid rgba(181, 224, 222, .12); }
  .signal-metrics > div:last-child { border-bottom: 0; }
  .method-step { grid-template-columns: 30px 40px 1fr; gap: 11px; padding-right: 16px; }
  .method-step__arrow { display: none; }
  .method-step h3 { font-size: 16px; }
}

@media (prefers-reduced-motion: reduce) {
  .landing-page { scroll-behavior: auto; }
  .reveal { opacity: 1; transform: none; transition: none; }
  .scroll-cue, .orbit-ring, .metric-card, .scan-beam, .primary-entry-shine { animation: none !important; }
}
</style>
