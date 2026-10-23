<script setup>
import { useRouter } from 'vue-router'
import {
  ArrowRight,
  BookOpenCheck,
  BrainCircuit,
  Braces,
  CheckCircle2,
  FileText,
  Network,
  Route,
  SlidersHorizontal,
} from '@lucide/vue'

const router = useRouter()

const loopStages = [
  { index: '01', label: '理解差异', note: '画像与先验', icon: BrainCircuit },
  { index: '02', label: '组织路径', note: '知识与目标', icon: Route },
  { index: '03', label: '生成练习', note: '资源与实验', icon: FileText },
  { index: '04', label: '回收证据', note: '反馈与下一步', icon: Network },
]

const capabilityRows = [
  {
    number: '01',
    title: '从对话开始理解',
    copy: '把背景、目标、困难和偏好，整理成可持续更新的学习画像。',
    icon: BrainCircuit,
  },
  {
    number: '02',
    title: '从知识组织路径',
    copy: '让课程、章节、知识关系和学习目标共同决定下一步，而不是只给出一串链接。',
    icon: BookOpenCheck,
  },
  {
    number: '03',
    title: '从行动获得反馈',
    copy: '阅读、作答、运行、复述和实验，都会成为可解释的学习证据。',
    icon: CheckCircle2,
  },
]

const knowledgeSignals = [
  { label: '课程', width: '86%' },
  { label: '章节', width: '70%' },
  { label: '知识关系', width: '92%' },
  { label: '来源定位', width: '62%' },
]

const resourceTypes = [
  { label: '个性化讲义', note: '把复杂内容讲清楚', icon: FileText },
  { label: '可交互模型', note: '把规律变成可观察的变化', icon: SlidersHorizontal },
  { label: '代码实训', note: '把理解带进真实运行', icon: Braces },
  { label: '测验与复述', note: '把掌握变成可验证证据', icon: CheckCircle2 },
]

const practiceSteps = [
  { index: 'A', title: '理解', note: '得到清晰的概念入口' },
  { index: 'B', title: '练习', note: '用合适的任务形成动作' },
  { index: 'C', title: '运行', note: '在代码或实验中观察结果' },
  { index: 'D', title: '验证', note: '让反馈回到画像与路径' },
]

function start() {
  router.push('/login')
}
</script>

<template>
  <div class="landing-page">
    <header class="landing-header">
      <a class="landing-brand" href="#top" aria-label="返回 EduMatrix 首页">
        <span class="landing-brand__mark">E</span>
        <span class="landing-brand__copy">
          <strong>EduMatrix</strong>
          <small>人工智能工程技能学习</small>
        </span>
      </a>

      <nav class="landing-nav" aria-label="首页内容导航">
        <a href="#capabilities">学习方式</a>
        <a href="#knowledge">知识底座</a>
        <a href="#resources">资源形态</a>
      </nav>

      <button type="button" class="landing-header__entry" @click="start">
        进入系统
        <ArrowRight :size="16" />
      </button>
    </header>

    <main id="top">
      <section class="landing-hero" aria-labelledby="landing-title">
        <div class="landing-hero__copy">
          <p class="landing-kicker">领域知识 × 个性化学习</p>
          <h1 id="landing-title">把知识，<br /><em>变成下一步。</em></h1>
          <p class="landing-positioning">
            EduMatrix 让专业知识从理解出发，沿着适合你的路径，走到练习、运行和验证。
          </p>
          <div class="landing-actions">
            <button type="button" class="landing-primary" @click="start">
              开启学习旅程
              <ArrowRight :size="18" />
            </button>
            <a class="landing-scroll-link" href="#capabilities">
              向下探索
              <span aria-hidden="true">↓</span>
            </a>
          </div>
        </div>

        <div class="hero-system-map" aria-label="理解、路径、练习、反馈的学习机制示意">
          <div class="hero-system-map__header">
            <span>EDUMATRIX / LEARNING SYSTEM</span>
            <span class="hero-system-map__signal"><i /> ACTIVE LOOP</span>
          </div>
          <div class="hero-system-map__canvas">
            <div class="hero-system-map__spine" aria-hidden="true" />
            <div class="hero-system-map__axis hero-system-map__axis--top" aria-hidden="true" />
            <div class="hero-system-map__axis hero-system-map__axis--bottom" aria-hidden="true" />
            <div class="hero-system-map__center">
              <span class="hero-system-map__center-mark">E</span>
              <strong>学习闭环</strong>
              <small>从理解到验证</small>
            </div>
            <div class="hero-map-tag hero-map-tag--one"><b>01</b><span>画像</span></div>
            <div class="hero-map-tag hero-map-tag--two"><b>02</b><span>知识</span></div>
            <div class="hero-map-tag hero-map-tag--three"><b>03</b><span>资源</span></div>
            <div class="hero-map-tag hero-map-tag--four"><b>04</b><span>证据</span></div>
          </div>
          <div class="hero-system-map__footer">
            <span>差异被看见</span>
            <span>路径被组织</span>
            <span>行动被记录</span>
          </div>
        </div>
      </section>

      <section id="capabilities" class="capabilities-section section-wrap" aria-labelledby="capabilities-title">
        <div class="section-intro">
          <p class="section-eyebrow">THE LEARNING LOGIC</p>
          <h2 id="capabilities-title">不是把功能堆在一起，<br />而是让每一步产生下一步。</h2>
          <p class="section-lead">
            面对同一份领域知识，不同的人需要不同的入口、节奏和练习。系统把这种差异变成清晰可走的学习行动。
          </p>
        </div>

        <ol class="capability-list">
          <li v-for="row in capabilityRows" :key="row.number" class="capability-row">
            <span class="capability-row__number">{{ row.number }}</span>
            <component :is="row.icon" :size="22" stroke-width="1.7" />
            <div>
              <h3>{{ row.title }}</h3>
              <p>{{ row.copy }}</p>
            </div>
            <ArrowRight class="capability-row__arrow" :size="19" />
          </li>
        </ol>
      </section>

      <section id="path" class="path-section section-wrap" aria-labelledby="path-title">
        <div class="path-section__copy">
          <p class="section-eyebrow">A PATH THAT ADAPTS</p>
          <h2 id="path-title">学习路径，<br /><em>不是一张清单。</em></h2>
          <p class="section-lead">
            画像、课程知识和每一次真实行动共同决定学习顺序。你看到的不是复杂的系统状态，而是此刻最值得完成的下一步。
          </p>
          <a class="text-link" href="#resources">看看资源如何进入路径 <ArrowRight :size="16" /></a>
        </div>

        <div class="path-rail" aria-label="学习路径组成示意">
          <div class="path-rail__topline"><span>PATH ASSEMBLY</span><i /></div>
          <div class="path-rail__item path-rail__item--active">
            <span class="path-rail__dot" />
            <div><small>INPUT</small><strong>学习者画像</strong><p>目标 · 基础 · 偏好</p></div>
          </div>
          <div class="path-rail__connector" />
          <div class="path-rail__item">
            <span class="path-rail__dot" />
            <div><small>CONTEXT</small><strong>课程知识关系</strong><p>章节 · 来源 · 难度</p></div>
          </div>
          <div class="path-rail__connector" />
          <div class="path-rail__item">
            <span class="path-rail__dot" />
            <div><small>SIGNAL</small><strong>学习证据</strong><p>作答 · 运行 · 复述</p></div>
          </div>
          <div class="path-rail__result"><Route :size="18" /><span>生成当前的下一步</span><ArrowRight :size="17" /></div>
        </div>
      </section>

      <section id="knowledge" class="knowledge-section" aria-labelledby="knowledge-title">
        <div class="section-wrap knowledge-section__inner">
          <div class="knowledge-section__copy">
            <p class="section-eyebrow">A GROUNDED KNOWLEDGE BASE</p>
            <h2 id="knowledge-title">让专业知识<br /><em>有出处。</em></h2>
            <p class="section-lead">
              团队预置并整理领域课程，系统沿着课程、章节、来源和知识关系生成内容，让每一次回答都能回到知识底座。
            </p>
            <div class="knowledge-note"><BookOpenCheck :size="18" /><span>来源可追溯 · 关系可理解 · 内容可复用</span></div>
          </div>

          <div class="knowledge-index" aria-label="课程知识库结构示意">
            <div class="knowledge-index__head"><span>KNOWLEDGE INDEX</span><span>STRUCTURED</span></div>
            <div class="knowledge-index__body">
              <div class="knowledge-index__column">
                <span class="knowledge-index__label">COURSE MAP</span>
                <div v-for="signal in knowledgeSignals" :key="signal.label" class="knowledge-signal">
                  <span>{{ signal.label }}</span>
                  <i :style="{ '--signal-width': signal.width }" />
                </div>
              </div>
              <div class="knowledge-index__document">
                <div class="document-lines"><i /><i /><i /><i /><i /><i /></div>
                <div class="document-tags"><span>来源</span><span>章节</span><span>关系</span></div>
                <div class="document-stamp"><FileText :size="18" /><span>可定位内容</span></div>
              </div>
            </div>
            <div class="knowledge-index__foot"><span>READ</span><span>ASK</span><span>GENERATE</span><span>RETURN</span></div>
          </div>
        </div>
      </section>

      <section id="resources" class="resources-section section-wrap" aria-labelledby="resources-title">
        <div class="resources-section__header">
          <div>
            <p class="section-eyebrow">MANY WAYS TO LEARN</p>
            <h2 id="resources-title">同一目标，<br /><em>不止一种练习形态。</em></h2>
          </div>
          <p class="section-lead">理解需要解释，技能需要行动。系统把一次学习目标拆成相互衔接的资源，而不是一段聊天记录。</p>
        </div>

        <div class="resource-spectrum">
          <div v-for="(resource, index) in resourceTypes" :key="resource.label" class="resource-spectrum__item">
            <span class="resource-spectrum__index">0{{ index + 1 }}</span>
            <component :is="resource.icon" :size="21" stroke-width="1.7" />
            <div><strong>{{ resource.label }}</strong><span>{{ resource.note }}</span></div>
            <ArrowRight :size="17" />
          </div>
        </div>
      </section>

      <section class="practice-section" aria-labelledby="practice-title">
        <div class="section-wrap practice-section__inner">
          <div class="practice-section__copy">
            <p class="section-eyebrow section-eyebrow--light">FROM KNOWING TO DOING</p>
            <h2 id="practice-title">从理解到运行，<br />反馈会回来。</h2>
            <p class="section-lead section-lead--light">
              在代码、实验、测验和复述里，学习不再停留在“看过”。每一次行动都为下一次调整留下证据。
            </p>
          </div>

          <ol class="practice-flow">
            <li v-for="step in practiceSteps" :key="step.index">
              <b>{{ step.index }}</b>
              <span class="practice-flow__line" />
              <strong>{{ step.title }}</strong>
              <small>{{ step.note }}</small>
            </li>
          </ol>
        </div>
      </section>

      <section class="evidence-section section-wrap" aria-labelledby="evidence-title">
        <div class="evidence-section__heading">
          <p class="section-eyebrow">THE LOOP CLOSES HERE</p>
          <h2 id="evidence-title">完成一次学习，<br /><em>系统才多知道一点。</em></h2>
        </div>
        <div class="evidence-flow">
          <div class="evidence-flow__start"><span>一次行动</span><strong>发生</strong></div>
          <div class="evidence-flow__track" aria-hidden="true"><i /><i /><i /><i /></div>
          <div class="evidence-flow__end"><span>下一步</span><strong>更清晰</strong></div>
        </div>
        <div class="evidence-notes">
          <span>不凭点击猜测掌握</span>
          <span>只让有证据的行为进入反馈</span>
          <span>让路径持续贴近学习者</span>
        </div>
      </section>

      <section class="landing-final section-wrap" aria-labelledby="final-title">
        <div>
          <p class="section-eyebrow">EDUMATRIX</p>
          <h2 id="final-title">从今天的<br /><em>下一步开始。</em></h2>
        </div>
        <div class="landing-final__action">
          <p>进入你的学习空间，看看知识如何变成行动。</p>
          <button type="button" class="landing-primary" @click="start">
            进入系统
            <ArrowRight :size="18" />
          </button>
        </div>
      </section>
    </main>
  </div>
</template>

<style scoped>
.landing-page {
  --landing-ink: var(--color-text);
  --landing-deep: var(--color-accent);
  --landing-muted: var(--color-text-secondary);
  --landing-faint: var(--color-text-muted);
  --landing-line: var(--color-border);
  --landing-surface: var(--color-page);
  --landing-card: var(--color-surface);
  min-height: 100vh;
  height: 100vh;
  overflow: auto;
  color: var(--landing-ink);
  background: var(--landing-surface);
  font-family: var(--font-sans);
  scroll-behavior: smooth;
  scroll-padding-top: 76px;
}

.landing-page * {
  box-sizing: border-box;
}

.landing-page a,
.landing-page button {
  font: inherit;
}

.landing-page a:focus-visible,
.landing-page button:focus-visible {
  outline: 3px solid var(--color-border-strong);
  outline-offset: 4px;
}

.landing-header {
  position: sticky;
  z-index: 20;
  top: 0;
  display: grid;
  min-height: 76px;
  grid-template-columns: 1fr auto 1fr;
  align-items: center;
  padding: 0 5vw;
  border-bottom: 1px solid color-mix(in srgb, var(--landing-line) 82%, transparent);
  background: color-mix(in srgb, var(--landing-surface) 93%, transparent);
  backdrop-filter: blur(14px);
}

.landing-brand {
  display: inline-flex;
  width: fit-content;
  align-items: center;
  gap: 11px;
  color: inherit;
  text-decoration: none;
}

.landing-brand__mark {
  display: grid;
  width: 34px;
  height: 34px;
  place-items: center;
  color: #ffffff;
  border-radius: 5px;
  background: var(--landing-deep);
  font-size: 16px;
  font-weight: 750;
}

.landing-brand__copy {
  display: grid;
  gap: 2px;
}

.landing-brand__copy strong {
  font-size: 16px;
  font-weight: 750;
}

.landing-brand__copy small {
  color: var(--landing-muted);
  font-size: 12px;
}

.landing-nav {
  display: flex;
  align-items: center;
  gap: clamp(18px, 3vw, 42px);
}

.landing-nav a,
.landing-header__entry {
  color: var(--landing-muted);
  font-size: 13px;
  font-weight: 650;
  text-decoration: none;
  transition: color 160ms ease;
}

.landing-nav a:hover,
.landing-header__entry:hover {
  color: var(--landing-ink);
}

.landing-header__entry {
  display: inline-flex;
  justify-self: end;
  align-items: center;
  gap: 8px;
  padding: 9px 0 9px 14px;
  color: var(--landing-ink);
  border: 0;
  background: transparent;
  cursor: pointer;
}

.landing-hero,
.section-wrap {
  width: min(1180px, calc(100% - 10vw));
  margin-inline: auto;
}

.landing-hero {
  display: grid;
  min-height: calc(100vh - 76px);
  grid-template-columns: minmax(0, 1.05fr) minmax(360px, 0.95fr);
  align-items: center;
  gap: clamp(42px, 7vw, 110px);
  padding-block: clamp(64px, 9vh, 120px) clamp(74px, 10vh, 140px);
}

.landing-hero__copy {
  max-width: 620px;
}

.landing-kicker,
.section-eyebrow {
  margin: 0 0 18px;
  color: var(--landing-muted);
  font-size: 12px;
  font-weight: 750;
  letter-spacing: 0.14em;
  line-height: 1.5;
  text-transform: uppercase;
}

.landing-hero h1,
.section-intro h2,
.path-section h2,
.knowledge-section h2,
.resources-section h2,
.practice-section h2,
.evidence-section h2,
.landing-final h2 {
  margin: 0;
  color: var(--landing-ink);
  font-family: var(--font-display);
  font-weight: 650;
  letter-spacing: 0;
}

.landing-hero h1 {
  font-size: clamp(56px, 7.3vw, 104px);
  line-height: 0.98;
}

.landing-page em {
  color: var(--landing-muted);
  font-style: normal;
}

.landing-positioning {
  max-width: 600px;
  margin: 28px 0 0;
  color: var(--landing-muted);
  font-size: clamp(18px, 1.65vw, 24px);
  font-weight: 570;
  line-height: 1.65;
}

.landing-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 26px;
  margin-top: 36px;
}

.landing-primary {
  display: inline-flex;
  min-height: 48px;
  align-items: center;
  gap: 11px;
  padding: 0 19px;
  color: #ffffff;
  border: 1px solid var(--landing-deep);
  border-radius: 5px;
  background: var(--landing-deep);
  box-shadow: 0 8px 18px rgb(17 33 45 / 12%);
  font-size: 14px;
  font-weight: 700;
  cursor: pointer;
  transition: background 160ms ease, transform 160ms ease, box-shadow 160ms ease;
}

.landing-primary:hover {
  background: var(--color-text);
  box-shadow: 0 10px 22px rgb(17 33 45 / 18%);
  transform: translateY(-1px);
}

.landing-scroll-link,
.text-link {
  display: inline-flex;
  align-items: center;
  gap: 9px;
  color: var(--landing-muted);
  font-size: 13px;
  font-weight: 700;
  text-decoration: none;
}

.landing-scroll-link span {
  color: var(--landing-ink);
  font-size: 20px;
  line-height: 0.7;
}

.landing-scroll-link:hover,
.text-link:hover {
  color: var(--landing-ink);
}

.hero-system-map {
  align-self: center;
  min-height: 460px;
  border: 1px solid var(--landing-line);
  background: var(--landing-card);
  box-shadow: 0 24px 60px rgb(17 33 45 / 8%);
}

.hero-system-map__header,
.hero-system-map__footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 15px 18px;
  color: var(--landing-faint);
  font-size: 10px;
  font-weight: 750;
  letter-spacing: 0.14em;
}

.hero-system-map__header {
  border-bottom: 1px solid var(--landing-line);
}

.hero-system-map__signal {
  display: inline-flex;
  align-items: center;
  gap: 7px;
}

.hero-system-map__signal i {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #3f5b6a;
}

.hero-system-map__canvas {
  position: relative;
  min-height: 360px;
  overflow: hidden;
  background: #f9fafa;
}

.hero-system-map__canvas::before,
.hero-system-map__canvas::after {
  position: absolute;
  content: '';
  pointer-events: none;
}

.hero-system-map__canvas::before {
  inset: 15% 11%;
  border: 1px solid #dfe4e5;
  border-radius: 50%;
  transform: rotate(-17deg) scaleY(0.68);
}

.hero-system-map__canvas::after {
  inset: 24% 20%;
  border: 1px dashed #ccd0cf;
  border-radius: 50%;
  transform: rotate(34deg) scaleY(0.78);
}

.hero-system-map__spine {
  position: absolute;
  top: 10%;
  bottom: 10%;
  left: 50%;
  width: 1px;
  background: #aebabc;
}

.hero-system-map__axis {
  position: absolute;
  left: 21%;
  width: 58%;
  height: 1px;
  background: #c7d0d1;
}

.hero-system-map__axis--top {
  top: 31%;
  transform: rotate(-19deg);
}

.hero-system-map__axis--bottom {
  top: 67%;
  transform: rotate(16deg);
}

.hero-system-map__center {
  position: absolute;
  z-index: 2;
  top: 50%;
  left: 50%;
  display: grid;
  width: 124px;
  height: 124px;
  place-items: center;
  align-content: center;
  gap: 6px;
  border: 1px solid var(--landing-deep);
  border-radius: 50%;
  background: var(--landing-deep);
  box-shadow: 0 12px 24px rgb(6 20 27 / 16%);
  color: #ffffff;
  transform: translate(-50%, -50%);
}

.hero-system-map__center-mark {
  display: grid;
  width: 22px;
  height: 22px;
  place-items: center;
  border: 1px solid rgb(255 255 255 / 50%);
  border-radius: 50%;
  font-size: 11px;
  font-weight: 750;
}

.hero-system-map__center strong {
  font-size: 14px;
  font-weight: 700;
}

.hero-system-map__center small {
  color: #ccd0cf;
  font-size: 11px;
}

.hero-map-tag {
  position: absolute;
  z-index: 3;
  display: grid;
  gap: 4px;
  color: var(--landing-muted);
  font-size: 12px;
  font-weight: 700;
}

.hero-map-tag b {
  color: var(--landing-ink);
  font-size: 11px;
  letter-spacing: 0.12em;
}

.hero-map-tag--one { top: 20%; left: 13%; }
.hero-map-tag--two { top: 15%; right: 14%; }
.hero-map-tag--three { right: 12%; bottom: 19%; }
.hero-map-tag--four { bottom: 16%; left: 15%; }

.hero-system-map__footer {
  border-top: 1px solid var(--landing-line);
  color: var(--landing-muted);
  letter-spacing: 0;
}

.capabilities-section,
.path-section,
.resources-section,
.evidence-section,
.landing-final {
  padding-block: clamp(94px, 13vw, 176px);
}

.capabilities-section {
  display: grid;
  grid-template-columns: minmax(260px, 0.83fr) minmax(0, 1.17fr);
  gap: clamp(48px, 9vw, 142px);
  border-top: 1px solid var(--landing-line);
}

.section-intro h2,
.path-section h2,
.knowledge-section h2,
.resources-section h2,
.practice-section h2,
.evidence-section h2,
.landing-final h2 {
  font-size: clamp(33px, 4vw, 58px);
  line-height: 1.18;
}

.section-lead {
  max-width: 440px;
  margin: 25px 0 0;
  color: var(--landing-muted);
  font-size: 15px;
  line-height: 1.9;
}

.capability-list {
  display: grid;
  gap: 0;
  margin: 0;
  padding: 0;
  list-style: none;
  border-top: 1px solid var(--landing-line);
}

.capability-row {
  display: grid;
  grid-template-columns: 42px 30px minmax(0, 1fr) 24px;
  align-items: start;
  gap: 12px;
  padding: 25px 0 26px;
  border-bottom: 1px solid var(--landing-line);
  color: var(--landing-muted);
}

.capability-row__number {
  color: var(--landing-faint);
  font-size: 11px;
  font-weight: 750;
  letter-spacing: 0.12em;
}

.capability-row > svg {
  color: var(--landing-deep);
}

.capability-row h3,
.capability-row p {
  margin: 0;
}

.capability-row h3 {
  color: var(--landing-ink);
  font-size: 16px;
  font-weight: 750;
  line-height: 1.5;
}

.capability-row p {
  max-width: 430px;
  margin-top: 7px;
  color: var(--landing-muted);
  font-size: 13px;
  line-height: 1.75;
}

.capability-row__arrow {
  margin-top: 3px;
  color: var(--landing-faint) !important;
}

.path-section {
  display: grid;
  grid-template-columns: minmax(0, 0.8fr) minmax(390px, 1.2fr);
  gap: clamp(56px, 10vw, 170px);
  align-items: center;
  border-top: 1px solid var(--landing-line);
}

.path-section__copy .text-link {
  margin-top: 31px;
}

.path-rail {
  position: relative;
  padding: 4px 0 0 34px;
  border-left: 1px solid #aebabc;
}

.path-rail__topline {
  display: flex;
  align-items: center;
  gap: 15px;
  margin-left: -34px;
  color: var(--landing-faint);
  font-size: 10px;
  font-weight: 750;
  letter-spacing: 0.14em;
}

.path-rail__topline i {
  flex: 1;
  height: 1px;
  background: var(--landing-line);
}

.path-rail__item {
  position: relative;
  display: flex;
  min-height: 98px;
  align-items: flex-start;
  padding: 29px 0 19px;
}

.path-rail__dot {
  position: absolute;
  top: 37px;
  left: -39px;
  width: 9px;
  height: 9px;
  border: 2px solid var(--landing-surface);
  border-radius: 50%;
  background: var(--landing-faint);
  box-shadow: 0 0 0 1px #8f9ea1;
}

.path-rail__item--active .path-rail__dot {
  background: var(--landing-deep);
  box-shadow: 0 0 0 1px var(--landing-deep);
}

.path-rail__item small {
  display: block;
  margin-bottom: 6px;
  color: var(--landing-faint);
  font-size: 10px;
  font-weight: 750;
  letter-spacing: 0.13em;
}

.path-rail__item strong {
  display: block;
  color: var(--landing-ink);
  font-size: 17px;
  font-weight: 750;
}

.path-rail__item p {
  margin: 6px 0 0;
  color: var(--landing-muted);
  font-size: 13px;
}

.path-rail__connector {
  position: absolute;
  top: 104px;
  bottom: 103px;
  left: -1px;
  width: 1px;
  background: repeating-linear-gradient(to bottom, #aebabc 0 6px, transparent 6px 12px);
}

.path-rail__result {
  display: flex;
  min-height: 55px;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-left: -1px;
  padding: 0 18px;
  border: 1px solid var(--landing-deep);
  background: var(--landing-card);
  color: var(--landing-deep);
  font-size: 14px;
  font-weight: 750;
}

.knowledge-section {
  color: #ffffff;
  background: var(--landing-deep);
}

.knowledge-section__inner {
  display: grid;
  grid-template-columns: minmax(240px, 0.8fr) minmax(430px, 1.2fr);
  gap: clamp(54px, 10vw, 170px);
  align-items: center;
}

.knowledge-section h2 {
  color: #ffffff;
}

.knowledge-section em {
  color: #aebabc;
}

.section-eyebrow--light {
  color: #aebabc;
}

.knowledge-section__copy .section-lead {
  color: #c3ccce;
}

.knowledge-note {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  margin-top: 31px;
  color: #ffffff;
  font-size: 13px;
  font-weight: 650;
}

.knowledge-index {
  border: 1px solid #4a5c6a;
  background: #172a36;
}

.knowledge-index__head,
.knowledge-index__foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 18px;
  color: #aebabc;
  font-size: 10px;
  font-weight: 750;
  letter-spacing: 0.13em;
}

.knowledge-index__head {
  border-bottom: 1px solid #4a5c6a;
}

.knowledge-index__body {
  display: grid;
  grid-template-columns: 1fr 0.92fr;
  min-height: 270px;
}

.knowledge-index__column {
  padding: 28px 22px;
  border-right: 1px solid #4a5c6a;
}

.knowledge-index__label {
  display: block;
  margin-bottom: 25px;
  color: #7f949b;
  font-size: 10px;
  font-weight: 750;
  letter-spacing: 0.13em;
}

.knowledge-signal {
  display: grid;
  grid-template-columns: 68px 1fr;
  align-items: center;
  gap: 11px;
  margin-top: 17px;
  color: #d4dcdd;
  font-size: 12px;
}

.knowledge-signal i {
  display: block;
  height: 4px;
  background: #aebabc;
}

.knowledge-signal i::after {
  display: block;
  width: var(--signal-width);
  height: 4px;
  background: #ffffff;
  content: '';
}

.knowledge-index__document {
  position: relative;
  margin: 25px 22px;
  padding: 22px 18px;
  border: 1px solid #526770;
  background: #203540;
}

.document-lines {
  display: grid;
  gap: 15px;
}

.document-lines i {
  display: block;
  width: 100%;
  height: 5px;
  background: #526770;
}

.document-lines i:nth-child(2) { width: 78%; }
.document-lines i:nth-child(3) { width: 92%; }
.document-lines i:nth-child(5) { width: 66%; }
.document-lines i:nth-child(6) { width: 84%; }

.document-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 7px;
  margin-top: 31px;
}

.document-tags span {
  padding: 5px 7px;
  border: 1px solid #62777d;
  color: #d4dcdd;
  font-size: 10px;
}

.document-stamp {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  margin-top: 26px;
  color: #ffffff;
  font-size: 12px;
  font-weight: 650;
}

.knowledge-index__foot {
  justify-content: flex-start;
  gap: 21px;
  border-top: 1px solid #4a5c6a;
  letter-spacing: 0.06em;
}

.resources-section {
  border-bottom: 1px solid var(--landing-line);
}

.resources-section__header {
  display: grid;
  grid-template-columns: minmax(0, 0.95fr) minmax(260px, 0.7fr);
  gap: clamp(44px, 10vw, 170px);
  align-items: end;
}

.resources-section__header .section-lead {
  margin: 0 0 3px;
}

.resource-spectrum {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0 52px;
  margin-top: 72px;
  border-top: 1px solid var(--landing-line);
}

.resource-spectrum__item {
  display: grid;
  grid-template-columns: 36px 28px minmax(0, 1fr) 20px;
  align-items: center;
  gap: 13px;
  min-height: 92px;
  border-bottom: 1px solid var(--landing-line);
  color: var(--landing-muted);
}

.resource-spectrum__index {
  color: var(--landing-faint);
  font-size: 11px;
  font-weight: 750;
  letter-spacing: 0.1em;
}

.resource-spectrum__item > svg {
  color: var(--landing-deep);
}

.resource-spectrum__item div {
  display: grid;
  gap: 5px;
}

.resource-spectrum__item strong {
  color: var(--landing-ink);
  font-size: 15px;
  font-weight: 750;
}

.resource-spectrum__item span:not(.resource-spectrum__index) {
  color: var(--landing-muted);
  font-size: 12px;
}

.resource-spectrum__item > svg:last-child {
  color: var(--landing-faint);
}

.practice-section {
  color: #ffffff;
  background: var(--landing-deep);
}

.practice-section__inner {
  display: grid;
  grid-template-columns: minmax(240px, 0.77fr) minmax(420px, 1.23fr);
  gap: clamp(56px, 10vw, 170px);
  align-items: center;
  padding-block: clamp(94px, 13vw, 168px);
}

.practice-section h2 {
  color: #ffffff;
}

.section-lead--light {
  color: #c3ccce;
}

.practice-flow {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 0;
  margin: 0;
  padding: 0;
  list-style: none;
}

.practice-flow li {
  position: relative;
  display: grid;
  min-height: 190px;
  align-content: start;
  gap: 10px;
  padding: 0 18px;
  border-left: 1px solid #4a5c6a;
}

.practice-flow li:first-child {
  padding-left: 0;
  border-left: 0;
}

.practice-flow b {
  color: #aebabc;
  font-size: 11px;
  letter-spacing: 0.14em;
}

.practice-flow__line {
  display: block;
  width: 100%;
  height: 1px;
  margin: 9px 0 15px;
  background: #70838a;
}

.practice-flow strong {
  color: #ffffff;
  font-size: 17px;
  font-weight: 750;
}

.practice-flow small {
  color: #aebabc;
  font-size: 12px;
  line-height: 1.7;
}

.evidence-section {
  display: grid;
  grid-template-columns: minmax(250px, 0.72fr) minmax(0, 1.28fr);
  gap: clamp(52px, 9vw, 145px);
  align-items: center;
}

.evidence-flow {
  display: grid;
  grid-template-columns: auto minmax(180px, 1fr) auto;
  align-items: center;
  gap: 22px;
}

.evidence-flow__start,
.evidence-flow__end {
  display: grid;
  gap: 6px;
  min-width: 95px;
}

.evidence-flow__start span,
.evidence-flow__end span {
  color: var(--landing-muted);
  font-size: 12px;
}

.evidence-flow__start strong,
.evidence-flow__end strong {
  font-family: var(--font-display);
  font-size: 24px;
  font-weight: 650;
}

.evidence-flow__end {
  text-align: right;
}

.evidence-flow__track {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  align-items: center;
  gap: 11px;
}

.evidence-flow__track i {
  display: block;
  height: 8px;
  border-top: 1px solid var(--landing-muted);
  border-bottom: 1px solid var(--landing-muted);
}

.evidence-flow__track i:nth-child(2) { opacity: 0.75; }
.evidence-flow__track i:nth-child(3) { opacity: 0.5; }
.evidence-flow__track i:nth-child(4) { opacity: 0.3; }

.evidence-notes {
  display: flex;
  grid-column: 2;
  flex-wrap: wrap;
  gap: 12px 28px;
  margin-top: -55px;
  color: var(--landing-muted);
  font-size: 12px;
}

.evidence-notes span::before {
  display: inline-block;
  width: 5px;
  height: 5px;
  margin: 0 8px 2px 0;
  border-radius: 50%;
  background: var(--landing-ink);
  content: '';
}

.landing-final {
  display: flex;
  align-items: end;
  justify-content: space-between;
  gap: 48px;
  border-top: 1px solid var(--landing-line);
}

.landing-final__action {
  display: grid;
  justify-items: end;
  gap: 22px;
  max-width: 270px;
}

.landing-final__action p {
  margin: 0;
  color: var(--landing-muted);
  font-size: 14px;
  line-height: 1.8;
  text-align: right;
}

@media (max-width: 1100px) {
  .landing-nav {
    gap: 18px;
  }

  .landing-hero,
  .capabilities-section,
  .path-section,
  .knowledge-section__inner,
  .resources-section__header,
  .practice-section__inner,
  .evidence-section {
    gap: 48px;
  }
}

@media (max-width: 820px) {
  .landing-header {
    grid-template-columns: 1fr auto;
  }

  .landing-nav {
    display: none;
  }

  .landing-hero,
  .capabilities-section,
  .path-section,
  .knowledge-section__inner,
  .resources-section__header,
  .practice-section__inner,
  .evidence-section {
    grid-template-columns: 1fr;
  }

  .landing-hero {
    padding-top: 66px;
  }

  .hero-system-map {
    min-height: 390px;
  }

  .hero-system-map__canvas {
    min-height: 292px;
  }

  .resource-spectrum {
    grid-template-columns: 1fr;
  }

  .practice-flow {
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 32px 0;
  }

  .practice-flow li:nth-child(3) {
    padding-left: 0;
    border-left: 0;
  }

  .evidence-notes {
    grid-column: auto;
    margin-top: 0;
  }
}

@media (prefers-reduced-motion: reduce) {
  .landing-page {
    scroll-behavior: auto;
  }

  .landing-page * {
    transition-duration: 0.01ms !important;
  }
}
</style>
