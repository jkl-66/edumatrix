<script setup>
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import {
  ArrowRight, BadgeCheck, Blocks, BriefcaseBusiness, Cpu, Film,
  Network, ShieldCheck, Store, Wrench,
} from '@lucide/vue'

const router = useRouter()
const role = localStorage.getItem('edumatrix_role') || 'student'

const groups = [
  {
    id: 'enterprise',
    title: '企业治理',
    description: '培训治理、认证复训与风险分析',
    icon: BriefcaseBusiness,
    items: [
      { title: '企业培训', path: '/enterprise-training', summary: '岗位能力、培训批次与能力差距', boundary: '冻结合成岗位与人员数据', roles: ['teacher', 'admin', 'assistant'] },
      { title: '认证与复训', path: '/certification-lifecycle', summary: '认证到期、撤销、复训与本地通知', boundary: '演示角色签核，不代表外部专家认证', roles: ['teacher', 'admin', 'assistant'] },
      { title: '多级审核', path: '/multilevel-review', summary: '三级审核队列与不可变责任记录', boundary: '演示角色流程', roles: ['teacher', 'admin', 'assistant'] },
      { title: '岗位标准升级', path: '/job-standard-impact', summary: '版本差异、影响预览与复训调度', boundary: '冻结合成岗位标准', roles: ['teacher', 'admin', 'assistant'] },
      { title: '企业风险指标', path: '/enterprise-risk', summary: '匿名组织指标、抑制规则与人工处置', boundary: '比赛演示指标，不用于真实人事决策', roles: ['teacher', 'admin', 'assistant'] },
    ],
  },
  {
    id: 'media',
    title: '媒体创作',
    description: '离线优先的课程媒体与交互资源',
    icon: Film,
    items: [
      { title: '视频制作', path: '/video-studio', summary: '分镜、字幕、讲稿与本地 MP4 渲染', boundary: '本地演示流水线', roles: ['teacher', 'admin', 'assistant'] },
      { title: '视频目录', path: '/video-catalog', summary: '来源、许可与课程视频目录', boundary: '仅展示合法来源清单', roles: ['teacher', 'admin', 'assistant'] },
      { title: '视频导入', path: '/video-imports', summary: '视频资产导入与版本记录', boundary: '不绕过版权与许可检查', roles: ['teacher', 'admin', 'assistant'] },
      { title: '章节视频', path: '/chapter-videos', summary: '按章节生成和管理课程视频', boundary: '演示课程内容', roles: ['teacher', 'admin', 'assistant'] },
      { title: '教学动画', path: '/teaching-animations', summary: '参数驱动动画与离线输出', boundary: '确定性模板，不宣称通用视频模型', roles: ['teacher', 'admin', 'assistant'] },
      { title: '网页课件', path: '/web-decks', summary: '可交互网页课件与版本管理', boundary: '本地课件工作流', roles: ['teacher', 'admin', 'assistant'] },
      { title: '语音训练', path: '/speech-training', summary: '本地识别、字幕与浏览器朗读', boundary: 'whisper.cpp CPU 基线，可文本降级', roles: ['teacher', 'admin', 'assistant'] },
    ],
  },
  {
    id: 'ecosystem',
    title: '生态市场',
    description: '课程分享、市场副本与领域扩展',
    icon: Store,
    items: [
      { title: '课程分享', path: '/course-sharing', summary: '发布快照、派生副本与上游更新', boundary: '许可证继承不等于法律结论', roles: ['teacher', 'admin', 'assistant'] },
      { title: '公共学习市场', path: '/marketplace', summary: '审核、获取、举报与下架', boundary: '无支付或商业交易', roles: ['teacher', 'admin', 'assistant'] },
      { title: '可解释推荐', path: '/marketplace/recommendations', summary: '画像、目标与质量约束推荐', boundary: '冻结演示权重', roles: ['teacher', 'admin', 'assistant'] },
      { title: '资源分叉', path: '/marketplace/forks', summary: '本地修改与上游三方合并', boundary: '保留来源与许可证快照', roles: ['teacher', 'admin', 'assistant'] },
      { title: '组织资源市场', path: '/organization-marketplace', summary: '组织范围发布与私有副本', boundary: '本地租户边界模拟', roles: ['teacher', 'admin', 'assistant'] },
      { title: '空间工作区', path: '/spatial-workspace', summary: '布局版本、撤销恢复与白名单动作', boundary: '非完整无限画布系统', roles: ['teacher', 'admin', 'assistant'] },
      { title: '领域插件', path: '/plugins', summary: '纯数据插件、hash 与能力权限', boundary: '禁止执行第三方代码和联网', roles: ['teacher', 'admin', 'assistant'] },
    ],
  },
  {
    id: 'integration',
    title: '本地集成',
    description: '可离线复现的企业接口模拟与故障边界',
    icon: Network,
    items: [
      { title: '集成沙箱', path: '/integration-sandbox', summary: '本地接口状态与集成边界', boundary: '不连接真实企业系统', roles: ['admin'] },
      { title: '本地 SSO', path: '/local-sso', summary: '身份映射与角色声明', boundary: '本地模拟器，不是生产 SSO', roles: ['admin'] },
      { title: 'HR 主数据', path: '/local-hr', summary: '合成人员与组织数据同步', boundary: '不含真实员工数据', roles: ['admin'] },
      { title: 'LMS 同步', path: '/local-lms', summary: '课程、成绩与学习记录同步', boundary: '本地协议适配演示', roles: ['admin'] },
      { title: '集成对账', path: '/integration-reconciliation', summary: '字段映射、差异和处理记录', boundary: '冻结合成交换数据', roles: ['admin'] },
      { title: '故障演练', path: '/integration-fault-drills', summary: '重试、补偿与恢复证据', boundary: '同机演练，不代表生产 SLA', roles: ['admin'] },
      { title: '本地适配器', path: '/local-adapter-lab', summary: '实验设备与业务接口适配', boundary: '本地模拟，不连接企业硬件', roles: ['admin'] },
    ],
  },
  {
    id: 'operations',
    title: '技术运营',
    description: '模型调用、内容质量与内部证据',
    icon: Cpu,
    items: [
      { title: '模型运营', path: '/model-operations', summary: '模型、Token、成本估算与任务健康', boundary: '工程估算，不是供应商账单或 SLA', roles: ['teacher', 'admin', 'assistant'] },
      { title: '内容审核', path: '/content-review', summary: '版本审核、返工、发布与下架', boundary: '演示角色责任链', roles: ['teacher', 'admin', 'assistant'] },
      { title: '对象证据', path: '/internal/objects', summary: '统一对象、版本和来源证据检查', boundary: '技术审计入口', roles: ['teacher', 'admin', 'assistant'] },
    ],
  },
]

const visibleGroups = computed(() => groups
  .map(group => ({ ...group, items: group.items.filter(item => item.roles.includes(role)) }))
  .filter(group => group.items.length))

const totalItems = computed(() => visibleGroups.value.reduce((total, group) => total + group.items.length, 0))
</script>

<template>
  <div class="advanced-directory">
    <header class="directory-header">
      <div>
        <p class="directory-kicker"><BadgeCheck :size="14" /> 已有能力</p>
        <h2>高级能力与技术证据</h2>
        <p>按当前角色展示可访问入口。核心学习与教学主线保持在一级导航。</p>
      </div>
      <div class="directory-count"><strong>{{ totalItems }}</strong><span>个可用入口</span></div>
    </header>

    <div class="boundary-strip">
      <ShieldCheck :size="16" />
      <span>页面使用合法公开材料、冻结合成业务数据和演示角色；不宣称真实企业接入、外部专家认证、第三方审计或生产 SLA。</span>
    </div>

    <section v-for="group in visibleGroups" :key="group.id" class="capability-section">
      <div class="section-heading">
        <div class="section-icon"><component :is="group.icon" :size="18" /></div>
        <div><h3>{{ group.title }}</h3><p>{{ group.description }}</p></div>
      </div>
      <div class="capability-grid">
        <button v-for="item in group.items" :key="item.path" class="capability-item" @click="router.push(item.path)">
          <div class="capability-item__top">
            <strong>{{ item.title }}</strong>
            <ArrowRight :size="15" />
          </div>
          <p>{{ item.summary }}</p>
          <span>{{ item.boundary }}</span>
        </button>
      </div>
    </section>
  </div>
</template>

<style scoped>
.advanced-directory { width: min(1180px, 100%); margin: 0 auto; color: #263129; }
.directory-header { display: flex; align-items: flex-end; justify-content: space-between; gap: 24px; padding: 4px 0 22px; border-bottom: 1px solid #dfe5df; }
.directory-kicker { display: flex; align-items: center; gap: 6px; margin: 0 0 7px; color: #567064; font-size: 11px; font-weight: 700; }
.directory-header h2 { margin: 0; font-size: 26px; font-weight: 720; letter-spacing: 0; }
.directory-header p:not(.directory-kicker) { margin: 8px 0 0; color: #758078; font-size: 13px; }
.directory-count { display: flex; min-width: 126px; align-items: baseline; justify-content: flex-end; gap: 7px; }
.directory-count strong { font-size: 28px; font-weight: 720; }
.directory-count span { color: #7d877f; font-size: 11px; }
.boundary-strip { display: flex; align-items: flex-start; gap: 9px; margin: 18px 0 28px; padding: 11px 13px; color: #5f6c64; border: 1px solid #dce5de; border-radius: 8px; background: #f2f6f2; font-size: 11px; line-height: 1.65; }
.boundary-strip svg { flex: 0 0 auto; margin-top: 1px; }
.capability-section { margin-top: 30px; }
.section-heading { display: flex; align-items: center; gap: 10px; margin-bottom: 12px; }
.section-icon { display: grid; width: 36px; height: 36px; place-items: center; color: #50695c; border: 1px solid #dce3dd; border-radius: 8px; background: #f7f9f6; }
.section-heading h3 { margin: 0; font-size: 16px; font-weight: 700; }
.section-heading p { margin: 3px 0 0; color: #879087; font-size: 11px; }
.capability-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; }
.capability-item { min-height: 126px; padding: 15px; text-align: left; border: 1px solid #dfe5df; border-radius: 8px; background: rgba(255, 255, 255, .74); cursor: pointer; transition: border-color .18s ease, background .18s ease, transform .18s ease; }
.capability-item:hover { border-color: #9eb2a5; background: #fff; transform: translateY(-1px); }
.capability-item__top { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
.capability-item__top strong { font-size: 13px; font-weight: 680; }
.capability-item__top svg { flex: 0 0 auto; color: #839087; }
.capability-item p { margin: 12px 0 9px; color: #68746c; font-size: 11px; line-height: 1.55; }
.capability-item span { display: block; color: #929a94; font-size: 10px; line-height: 1.5; }
@media (max-width: 920px) { .capability-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 600px) {
  .directory-header { align-items: flex-start; }
  .directory-header h2 { font-size: 21px; }
  .directory-count { min-width: auto; flex-direction: column; align-items: flex-end; gap: 0; }
  .capability-grid { grid-template-columns: 1fr; }
  .capability-item { min-height: 0; }
}
</style>
