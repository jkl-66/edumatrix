<script setup>
import { computed } from 'vue'
import {
  ArrowUpRight, BookOpenText, Braces, Check, CheckSquare, Circle,
  Map, MessageSquareText, MonitorPlay, Play, Presentation,
  SlidersHorizontal, Sparkles, Wrench,
} from '@lucide/vue'

const props = defineProps({
  definition: { type: Object, required: true },
  resourceCount: { type: Number, default: 0 },
  recentResource: { type: Object, default: null },
  knowledgePoint: { type: String, default: '' },
})

defineEmits(['generate', 'open-recent'])

const icons = {
  handout: BookOpenText,
  mind_map: Map,
  quiz: CheckSquare,
  training_task: Wrench,
  code_sandbox: Braces,
  video: MonitorPlay,
  deck: Presentation,
  interactive_model: SlidersHorizontal,
  feynman: MessageSquareText,
}

const icon = computed(() => icons[props.definition.id] || BookOpenText)
const topic = computed(() => props.knowledgePoint || props.recentResource?.knowledge_point?.title || '选择课程知识点')
</script>

<template>
  <section class="type-stage" :data-resource-space="definition.id">
    <header class="stage-heading">
      <div class="stage-identity">
        <span class="stage-icon"><component :is="icon" :size="21" /></span>
        <div>
          <span>{{ definition.kicker }}</span>
          <h2>{{ definition.label }}空间</h2>
          <p>{{ definition.description }}</p>
        </div>
      </div>
      <button type="button" class="stage-generate" @click="$emit('generate')">
        <Sparkles :size="17" />自定义生成
      </button>
    </header>

    <div class="stage-canvas" :class="`stage-canvas--${definition.id}`">
      <template v-if="definition.id === 'handout'">
        <aside class="handout-outline">
          <strong>目录</strong>
          <span class="active">01 核心概念</span>
          <span>02 图解与公式</span>
          <span>03 例子与反例</span>
          <span>04 学习检查</span>
        </aside>
        <article class="handout-sheet">
          <span>个性化讲义</span>
          <h3>{{ topic }}</h3>
          <p>围绕当前画像与课程来源组织关键概念、示例、代码和小测。</p>
          <div class="text-rule wide" /><div class="text-rule" /><div class="formula-line">f(x) = knowledge + practice</div>
        </article>
      </template>

      <template v-else-if="definition.id === 'mind_map'">
        <div class="mindmap-board" aria-label="思维导图结构预览">
          <span class="map-line map-line--a" /><span class="map-line map-line--b" /><span class="map-line map-line--c" />
          <div class="map-node map-node--root">{{ topic }}</div>
          <div class="map-node map-node--one">概念</div>
          <div class="map-node map-node--two">机制</div>
          <div class="map-node map-node--three">应用</div>
          <div class="map-node map-node--four">证据</div>
        </div>
        <aside class="map-inspector"><span>节点详情</span><strong>{{ topic }}</strong><p>选择节点后查看摘要、来源和下一步资源。</p></aside>
      </template>

      <template v-else-if="definition.id === 'quiz'">
        <div class="quiz-sheet">
          <div class="quiz-progress"><span>当前题目</span><strong>01 / 03</strong></div>
          <h3>关于“{{ topic }}”，哪项最符合课程来源？</h3>
          <div class="quiz-option"><Circle :size="15" />选项 A</div>
          <div class="quiz-option"><Circle :size="15" />选项 B</div>
          <div class="quiz-option"><Circle :size="15" />选项 C</div>
        </div>
        <aside class="quiz-feedback"><CheckSquare :size="24" /><strong>即时判分</strong><p>提交后在原位查看答案、解析与追问入口。</p></aside>
      </template>

      <template v-else-if="definition.id === 'training_task'">
        <article class="task-document">
          <span>实训任务书</span><h3>{{ topic }} · 工程任务</h3>
          <div class="task-row"><Check :size="15" /><span>目标与环境</span></div>
          <div class="task-row"><Circle :size="15" /><span>数据与步骤</span></div>
          <div class="task-row"><Circle :size="15" /><span>检查点与提交物</span></div>
        </article>
        <aside class="task-status"><strong>任务检查点</strong><span>01 环境准备</span><span>02 运行验证</span><span>03 结果提交</span></aside>
      </template>

      <template v-else-if="definition.id === 'code_sandbox'">
        <aside class="code-task"><strong>任务</strong><span>{{ topic }}</span><small>运行历史会保存在这里</small></aside>
        <div class="code-editor"><header><i /><i /><i /><span>main.py</span></header><pre><code>def train_model(data):
    result = analyze(data)
    return result</code></pre><label>标准输入<input value="sample.csv" readonly /></label></div>
        <aside class="code-output"><strong>运行结果</strong><span class="console-line">等待运行...</span><small>输出、错误、图表与 AI 点评</small></aside>
      </template>

      <template v-else-if="definition.id === 'video'">
        <div class="video-player"><span class="video-play" aria-hidden="true"><Play :size="24" fill="currentColor" /></span><span>{{ topic }}</span><div class="video-timeline"><i /></div></div>
        <aside class="video-list"><strong>推荐队列</strong><span class="active">01 核心讲解</span><span>02 工程案例</span><span>03 复习片段</span></aside>
      </template>

      <template v-else-if="definition.id === 'deck'">
        <aside class="deck-thumbs"><span class="active">01</span><span>02</span><span>03</span></aside>
        <article class="deck-slide"><span>课程课件</span><h3>{{ topic }}</h3><p>概念、图表和讲解按页面节奏展开。</p><div class="deck-figure"><i /><i /><i /></div></article>
      </template>

      <template v-else-if="definition.id === 'interactive_model'">
        <aside class="model-controls"><strong>实验参数</strong><label>学习率<input type="range" min="0" max="100" value="42" disabled /></label><label>迭代次数<input type="range" min="0" max="100" value="68" disabled /></label><span class="model-run">运行实验</span></aside>
        <div class="model-chart"><span>{{ topic }}</span><div class="chart-grid"><i class="curve curve--a" /><i class="curve curve--b" /></div><footer><span>训练曲线</span><span>参数对比</span></footer></div>
      </template>

      <template v-else>
        <div class="feynman-flow"><div class="flow-progress"><span class="done">1</span><i /><span>2</span><i /><span>3</span><i /><span>4</span></div><span>第一次复述</span><h3>用自己的话解释“{{ topic }}”</h3><div class="response-box">在这里完成第一次复述...</div></div>
        <aside class="feynman-review"><MessageSquareText :size="23" /><strong>追问与再解释</strong><p>评分后提出疑问，再完成第二次复述并比较提升。</p></aside>
      </template>
    </div>

    <footer class="stage-footer">
      <div><strong>{{ resourceCount }}</strong><span>份{{ definition.label }}历史</span></div>
      <button v-if="recentResource" type="button" @click="$emit('open-recent')">
        继续最近资源<ArrowUpRight :size="16" />
      </button>
      <span v-else>生成后会自动归档到当前空间</span>
    </footer>
  </section>
</template>

<style scoped>
.type-stage { border-bottom: 1px solid #dfe4e5; background: #fbfcfc; color: #06141b; }
.stage-heading { display: flex; align-items: center; justify-content: space-between; gap: 18px; padding: 16px 18px; }
.stage-identity { display: flex; min-width: 0; align-items: flex-start; gap: 12px; }
.stage-icon { display: grid; width: 38px; height: 38px; flex: 0 0 38px; place-items: center; border: 1px solid #c7cdce; border-radius: 8px; background: #fff; color: #11212d; }
.stage-identity > div { min-width: 0; }
.stage-identity span { color: #6a7478; font-size: 14px; }
.stage-identity h2 { margin: 2px 0 0; font-size: 20px; line-height: 1.3; }
.stage-identity p { margin: 4px 0 0; color: #4a5c6a; font-size: 14px; line-height: 1.5; }
.stage-generate { display: inline-flex; min-height: 40px; flex: 0 0 auto; align-items: center; gap: 8px; border: 1px solid #11212d; border-radius: 8px; padding: 0 14px; background: #11212d; color: #fff; font-size: 14px; font-weight: 650; cursor: pointer; }
.stage-canvas { position: relative; display: grid; min-height: 226px; margin: 0 18px; overflow: hidden; border: 1px solid #cfd5d5; border-radius: 8px; background: #fff; }
.stage-footer { display: flex; min-height: 50px; align-items: center; justify-content: space-between; gap: 16px; padding: 8px 18px 12px; color: #60727c; }
.stage-footer div { display: flex; align-items: baseline; gap: 7px; }
.stage-footer strong { color: #11212d; font-size: 20px; }
.stage-footer span, .stage-footer button { font-size: 14px; }
.stage-footer button { display: inline-flex; align-items: center; gap: 6px; border: 0; padding: 6px 0; background: transparent; color: #11212d; font-weight: 650; cursor: pointer; }

.stage-canvas--handout { grid-template-columns: 150px minmax(0, 1fr); background: #f1f3f3; }
.handout-outline { display: grid; align-content: start; gap: 4px; padding: 18px 12px; border-right: 1px solid #d9dede; background: #fff; }
.handout-outline strong { margin: 0 8px 8px; font-size: 14px; }
.handout-outline span { border-radius: 6px; padding: 8px; color: #64727a; font-size: 13px; }
.handout-outline span.active { background: #11212d; color: #fff; }
.handout-sheet { align-self: stretch; width: min(520px, calc(100% - 32px)); margin: 16px auto 0; padding: 24px 28px; background: #fff; box-shadow: 0 8px 22px rgba(6,20,27,.09); }
.handout-sheet > span { color: #526977; font-size: 13px; font-weight: 700; }
.handout-sheet h3 { margin: 7px 0 8px; font: 700 24px/1.3 var(--font-heading, sans-serif); }
.handout-sheet p { margin: 0; color: #53636d; font-size: 14px; line-height: 1.6; }
.text-rule { width: 72%; height: 5px; margin-top: 12px; border-radius: 2px; background: #dfe4e5; }.text-rule.wide { width: 94%; }
.formula-line { width: max-content; margin-top: 13px; border: 1px solid #d9dede; padding: 6px 9px; color: #344957; font: 13px/1.4 ui-monospace, Consolas, monospace; }

.stage-canvas--mind_map { grid-template-columns: minmax(0, 1fr) 190px; }
.mindmap-board { position: relative; min-height: 226px; background: #f8f9f9; }
.map-node { position: absolute; z-index: 2; display: grid; min-width: 74px; min-height: 34px; place-items: center; border: 1px solid #aeb8bb; border-radius: 7px; padding: 0 10px; background: #fff; color: #253745; font-size: 13px; }
.map-node--root { top: 88px; left: 41%; min-width: 118px; border-color: #11212d; background: #11212d; color: #fff; }
.map-node--one { top: 34px; left: 12%; }.map-node--two { right: 9%; top: 36px; }.map-node--three { bottom: 30px; left: 13%; }.map-node--four { right: 10%; bottom: 28px; }
.map-line { position: absolute; z-index: 1; width: 31%; height: 1px; background: #aeb8bb; transform-origin: left center; }.map-line--a { top: 99px; left: 20%; transform: rotate(18deg); }.map-line--b { top: 100px; left: 49%; transform: rotate(-17deg); }.map-line--c { top: 118px; left: 23%; width: 55%; }
.map-inspector { padding: 18px; border-left: 1px solid #d9dede; }.map-inspector span { color: #6a7478; font-size: 13px; }.map-inspector strong { display: block; margin-top: 10px; font-size: 16px; }.map-inspector p { color: #53636d; font-size: 14px; line-height: 1.6; }

.stage-canvas--quiz { grid-template-columns: minmax(0, 1fr) 180px; padding: 18px; gap: 18px; background: #f8f9f9; }
.quiz-sheet { display: grid; gap: 8px; }.quiz-progress { display: flex; justify-content: space-between; color: #60727c; font-size: 13px; }.quiz-sheet h3 { margin: 4px 0 6px; font-size: 17px; line-height: 1.5; }.quiz-option { display: flex; min-height: 38px; align-items: center; gap: 8px; border: 1px solid #d4dada; border-radius: 7px; padding: 0 11px; background: #fff; color: #344957; font-size: 14px; text-align: left; }
.quiz-feedback { display: grid; align-content: center; justify-items: start; border-left: 1px solid #d9dede; padding-left: 18px; }.quiz-feedback strong { margin-top: 10px; }.quiz-feedback p { color: #53636d; font-size: 14px; line-height: 1.55; }

.stage-canvas--training_task { grid-template-columns: minmax(0, 1fr) 200px; background: #f4f5f5; }
.task-document { margin: 14px 16px 0; padding: 20px 22px; background: #fff; box-shadow: 0 7px 18px rgba(6,20,27,.08); }.task-document > span { color: #526977; font-size: 13px; font-weight: 700; }.task-document h3 { margin: 6px 0 15px; font-size: 20px; }.task-row { display: flex; align-items: center; gap: 9px; min-height: 37px; border-top: 1px solid #e4e8e8; color: #344957; font-size: 14px; }
.task-status { display: grid; align-content: start; gap: 8px; padding: 18px; border-left: 1px solid #d9dede; background: #fff; }.task-status strong { margin-bottom: 6px; }.task-status span { border: 1px solid #d9dede; border-radius: 6px; padding: 8px; color: #53636d; font-size: 13px; }

.stage-canvas--code_sandbox { grid-template-columns: 150px minmax(0, 1fr) 170px; background: #10171b; color: #dce4e6; }
.code-task, .code-output { display: grid; align-content: start; gap: 10px; padding: 16px; background: #172126; }.code-task { border-right: 1px solid #2b373c; }.code-output { border-left: 1px solid #2b373c; }.code-task span, .code-output span { font-size: 13px; line-height: 1.5; }.code-task small, .code-output small { color: #8fa0a6; font-size: 12px; line-height: 1.5; }
.code-editor { min-width: 0; }.code-editor header { display: flex; height: 34px; align-items: center; gap: 6px; padding: 0 12px; border-bottom: 1px solid #2b373c; background: #151e22; }.code-editor header i { width: 7px; height: 7px; border-radius: 50%; background: #66757b; }.code-editor header span { margin-left: 7px; color: #b9c5c8; font-size: 12px; }.code-editor pre { height: 105px; margin: 0; padding: 18px; overflow: hidden; color: #d8e2e4; font: 13px/1.7 ui-monospace, Consolas, monospace; }.code-editor label { display: grid; gap: 5px; padding: 8px 14px; border-top: 1px solid #2b373c; color: #91a1a6; font-size: 12px; }.code-editor input { height: 28px; border: 1px solid #344248; border-radius: 5px; padding: 0 8px; background: #10171b; color: #d8e2e4; }.console-line { font-family: ui-monospace, Consolas, monospace; color: #bdc9cc; }

.stage-canvas--video { grid-template-columns: minmax(0, 1fr) 190px; background: #11181c; color: #fff; }
.video-player { position: relative; display: grid; place-content: center; justify-items: center; gap: 12px; background: radial-gradient(circle at center, #27353b 0, #11181c 62%); }.video-play { display: grid; width: 52px; height: 52px; place-items: center; border: 1px solid rgba(255,255,255,.45); border-radius: 50%; background: rgba(255,255,255,.1); color: #fff; }.video-player > span:not(.video-play) { font-size: 15px; }.video-timeline { position: absolute; right: 20px; bottom: 20px; left: 20px; height: 3px; background: rgba(255,255,255,.25); }.video-timeline i { display: block; width: 38%; height: 100%; background: #fff; }
.video-list { display: grid; align-content: start; gap: 7px; padding: 18px; border-left: 1px solid #303b40; background: #172126; }.video-list span { border-radius: 6px; padding: 9px; color: #b7c2c5; font-size: 13px; }.video-list span.active { background: #f3f5f5; color: #11212d; }

.stage-canvas--deck { grid-template-columns: 62px minmax(0, 1fr); padding: 14px; gap: 14px; background: #ecefef; }
.deck-thumbs { display: grid; align-content: start; gap: 8px; }.deck-thumbs span { display: grid; height: 42px; place-items: center; border: 1px solid #c9d0d1; border-radius: 5px; background: #fff; color: #66757b; font-size: 12px; }.deck-thumbs span.active { border-color: #11212d; color: #11212d; box-shadow: inset 0 0 0 1px #11212d; }
.deck-slide { position: relative; min-width: 0; padding: 22px 28px; overflow: hidden; background: #fff; box-shadow: 0 8px 20px rgba(6,20,27,.1); }.deck-slide > span { color: #526977; font-size: 13px; font-weight: 700; }.deck-slide h3 { max-width: 70%; margin: 8px 0; font: 700 25px/1.25 var(--font-heading, sans-serif); }.deck-slide p { color: #53636d; font-size: 14px; }.deck-figure { position: absolute; right: 28px; bottom: 24px; display: flex; height: 80px; align-items: flex-end; gap: 8px; }.deck-figure i { width: 18px; background: #11212d; }.deck-figure i:nth-child(1){height:38%}.deck-figure i:nth-child(2){height:78%;background:#526977}.deck-figure i:nth-child(3){height:56%;background:#78868b}

.stage-canvas--interactive_model { grid-template-columns: 190px minmax(0, 1fr); }
.model-controls { display: grid; align-content: start; gap: 13px; padding: 18px; border-right: 1px solid #d9dede; background: #f7f8f8; }.model-controls label { display: grid; gap: 7px; color: #53636d; font-size: 13px; }.model-controls input { width: 100%; accent-color: #11212d; }.model-run { display: grid; min-height: 34px; place-items: center; border: 1px solid #11212d; border-radius: 7px; background: #11212d; color: #fff; font-size: 13px; }
.model-chart { display: grid; grid-template-rows: auto 1fr auto; padding: 16px 20px; }.model-chart > span { color: #53636d; font-size: 13px; }.chart-grid { position: relative; min-height: 140px; margin-top: 8px; background: linear-gradient(#edf0f0 1px, transparent 1px), linear-gradient(90deg,#edf0f0 1px,transparent 1px); background-size: 25% 25%; }.curve { position: absolute; right: 4%; left: 5%; height: 3px; background: #11212d; transform: rotate(-8deg); }.curve--a { top: 58px; }.curve--b { top: 82px; background: #526977; transform: rotate(5deg); }.model-chart footer { display: flex; justify-content: flex-end; gap: 18px; color: #60727c; font-size: 12px; }

.stage-canvas--feynman { grid-template-columns: minmax(0, 1fr) 190px; padding: 18px; gap: 18px; background: #f7f8f8; }
.feynman-flow { min-width: 0; }.flow-progress { display: flex; align-items: center; margin-bottom: 16px; }.flow-progress span { display: grid; width: 25px; height: 25px; place-items: center; border: 1px solid #aeb8bb; border-radius: 50%; background: #fff; color: #53636d; font-size: 12px; }.flow-progress span.done { border-color: #11212d; background: #11212d; color: #fff; }.flow-progress i { width: 42px; height: 1px; background: #cfd5d5; }.feynman-flow > span { color: #526977; font-size: 13px; font-weight: 700; }.feynman-flow h3 { margin: 6px 0 10px; font-size: 18px; }.response-box { min-height: 70px; border: 1px solid #d4dada; border-radius: 7px; padding: 12px; background: #fff; color: #8a969a; font-size: 14px; }
.feynman-review { display: grid; align-content: center; justify-items: start; border-left: 1px solid #d9dede; padding-left: 18px; }.feynman-review strong { margin-top: 10px; }.feynman-review p { color: #53636d; font-size: 14px; line-height: 1.55; }

button:focus-visible { outline: 2px solid #11212d; outline-offset: 2px; }
@media (max-width: 1180px) {
  .stage-canvas { min-height: 210px; }
  .stage-canvas--mind_map, .stage-canvas--quiz, .stage-canvas--training_task, .stage-canvas--video, .stage-canvas--feynman { grid-template-columns: minmax(0, 1fr); }
  .map-inspector, .quiz-feedback, .task-status, .video-list, .feynman-review { display: none; }
  .stage-canvas--code_sandbox { grid-template-columns: 120px minmax(0, 1fr); }.code-output { display: none; }
}
</style>
