import { createRouter, createWebHistory } from 'vue-router'
import { useContextStore } from '../stores/context'
import { useCourseContextStore } from '../stores/courseContext'
import { isContextResolutionError } from '../services/context'
import { roleLandingPath } from '../utils/roleLanding'
import routeMigrationContract from './routeMigrationContract.json'
import Dashboard from '../views/Dashboard.vue'

const Landing = () => import('../views/Landing.vue')
const Login = () => import('../views/Login.vue')
const Onboarding = () => import('../views/Onboarding.vue')
const ProfileDashboard = () => import('../views/ProfileDashboard.vue')
const StudentAnalysis = () => import('../views/StudentAnalysis.vue')
const ProfileUpdateConversation = () => import('../views/ProfileUpdateConversation.vue')
const History = () => import('../views/History.vue')
const LearningWorkspace = () => import('../views/LearningWorkspace.vue')
const Chat = () => import('../views/Chat.vue')
const Knowledge = () => import('../views/Knowledge.vue')
const KnowledgeDocumentReader = () => import('../views/KnowledgeDocumentReader.vue')
const KnowledgeGraphWorkspace = () => import('../views/KnowledgeGraphWorkspace.vue')
const KnowledgeDiscoveryWorkspace = () => import('../views/KnowledgeDiscoveryWorkspace.vue')
const MarketplaceWorkspace = () => import('../views/MarketplaceWorkspace.vue')
const Settings = () => import('../views/Settings.vue')
const AssessmentWorkspace = () => import('../views/AssessmentWorkspace.vue')
const EntryDiagnostic = () => import('../views/EntryDiagnostic.vue')
const FormalExamWorkspace = () => import('../views/FormalExamWorkspace.vue')
const LearningPathGraph = () => import('../views/LearningPathGraph.vue')
const ResourceCenter = () => import('../views/ResourceCenter.vue')
const HandoutWorkspace = () => import('../views/HandoutWorkspace.vue')
const MindmapWorkspace = () => import('../views/MindmapWorkspace.vue')
const QuizResourceWorkspace = () => import('../views/QuizResourceWorkspace.vue')
const TrainingTaskWorkspace = () => import('../views/TrainingTaskWorkspace.vue')
const ResourceBundleWorkspace = () => import('../views/ResourceBundleWorkspace.vue')
const VideoRecommendationWorkspace = () => import('../views/VideoRecommendationWorkspace.vue')
const WebDeckWorkspace = () => import('../views/WebDeckWorkspace.vue')
const InteractiveLabWorkspace = () => import('../views/InteractiveLabWorkspace.vue')
const CodeSandboxWorkspace = () => import('../views/CodeSandboxWorkspace.vue')
const FeynmanWorkspace = () => import('../views/FeynmanWorkspace.vue')
const Review = () => import('../views/Review.vue')
const RevisionCalendar = () => import('../views/RevisionCalendar.vue')
const WrongQuestionBook = () => import('../views/WrongQuestionBook.vue')
const Notes = () => import('../views/Notes.vue')
const Teacher = () => import('../views/Teacher.vue')
const TeacherInterventions = () => import('../views/TeacherInterventions.vue')
const AdminAccounts = () => import('../views/AdminAccounts.vue')
const ModelOperationsWorkspace = () => import('../views/ModelOperationsWorkspace.vue')
const ContentReviewWorkspace = () => import('../views/ContentReviewWorkspace.vue')
const AdminSystem = () => import('../views/AdminSystem.vue')
const ContextRecovery = () => import('../views/ContextRecovery.vue')

export const TARGET_ROUTE_PATHS = [
  '/landing',
  '/login',
  '/onboarding',
  '/',
  '/profile',
  '/profile/learning',
  '/profile/history',
  '/workspace',
  '/chat',
  '/learn',
  '/knowledge',
  '/marketplace',
  '/settings',
  '/workspace/assessment',
  '/workspace/assessment/entry',
  '/workspace/assessment/exams',
  '/workspace/assessment/exams/:examId',
  '/workspace/path',
  '/workspace/resources',
  '/workspace/resources/handouts/:resourceId',
  '/workspace/resources/training-tasks/:resourceId',
  '/workspace/resources/mindmaps/:resourceId',
  '/workspace/resources/videos/:resourceId',
  '/workspace/resources/decks/:resourceId',
  '/workspace/resources/models/:resourceId',
  '/workspace/resources/bundles/:bundleId',
  '/workspace/resources/quizzes/:resourceId',
  '/workspace/code/:resourceId',
  '/workspace/feynman/:resourceId',
  '/workspace/review',
  '/workspace/review/calendar',
  '/workspace/review/wrong-questions',
  '/workspace/notes',
  '/knowledge/courses/:courseId',
  '/knowledge/documents/:documentId',
  '/knowledge/graph/:courseId',
  '/knowledge/discover',
  '/marketplace/items/:itemId',
  '/marketplace/publish',
  '/marketplace/mine',
  '/teacher/overview',
  '/teacher/courses',
  '/teacher/courses/:courseId',
  '/teacher/students',
  '/teacher/students/:studentId',
  '/teacher/assessment',
  '/teacher/interventions',
  '/admin/accounts',
  '/admin/models',
  '/admin/content-review',
  '/admin/system',
]

export const CURRENT_ROUTE_MIGRATION_CONTRACT = Object.freeze(routeMigrationContract)
const TARGET_ROUTE_PATH_SET = new Set(TARGET_ROUTE_PATHS)
const ROUTE_MIGRATION_BY_PATH = new Map(
  CURRENT_ROUTE_MIGRATION_CONTRACT.map((contract) => [contract.sourcePath, contract]),
)

const STUDENT = ['student']
const STUDENT_AND_TEACHER = ['student', 'teacher']
const TEACHING = ['teacher', 'admin']
const ADMIN = ['admin']

function requireAuth() {
  const token = localStorage.getItem('edumatrix_token')
  if (!token) return '/landing'
  const role = localStorage.getItem('edumatrix_role')
  const onboarded = localStorage.getItem('edumatrix_onboarded') === 'true'
  if (role === 'student' && !onboarded) return '/onboarding'
  return true
}

function requireTeacher() {
  if (!localStorage.getItem('edumatrix_token')) return '/landing'
  if (!TEACHING.includes(localStorage.getItem('edumatrix_role'))) return '/'
  return true
}

function requireAdmin() {
  if (!localStorage.getItem('edumatrix_token')) return '/landing'
  if (localStorage.getItem('edumatrix_role') !== 'admin') return '/'
  return true
}

function targetMeta(title, section, roles, extra = {}) {
  return {
    title,
    section,
    roles,
    requiresAuth: true,
    navigationLevel: extra.navigationLevel || 'secondary',
    courseScoped: Boolean(extra.courseScoped),
    allowEmptyCourse: Boolean(extra.allowEmptyCourse),
    featureFlag: extra.featureFlag || 'fusion_target',
    targetRoute: true,
  }
}

function migrationDestination(contract) {
  const role = localStorage.getItem('edumatrix_role')
  return contract.roleDestinations?.[role] || contract.destination
}

function compatibilityRedirect(contract) {
  return (to) => ({
    path: migrationDestination(contract),
    query: {
      ...to.query,
      compat: contract.notice || 'legacy-route',
      reason: contract.recoveryReason || to.query.reason,
      legacy_path: contract.sourcePath,
      return_to: to.fullPath,
    },
    replace: true,
  })
}

function legacy(contractOrPath, legacyName, destination) {
  const contract = typeof contractOrPath === 'string'
    ? ROUTE_MIGRATION_BY_PATH.get(contractOrPath) || {
      sourcePath: contractOrPath,
      sourceName: String(legacyName || '').replace(/^Legacy/, ''),
      destination: destination || contractOrPath,
      roles: [],
      disposition: 'compatibility',
      featureFlag: 'f10.route.legacy',
      rollbackRoute: contractOrPath,
    }
    : contractOrPath
  return {
    path: contract.sourcePath,
    name: `Legacy${contract.sourceName}`,
    beforeEnter: compatibilityRedirect(contract),
    meta: {
      requiresAuth: true,
      roles: contract.roles,
      navigationLevel: 'legacy',
      disposition: contract.disposition,
      destination: contract.destination,
      featureFlag: contract.featureFlag,
      rollbackRoute: contract.rollbackRoute,
      sourceRoute: contract.sourcePath,
    },
  }
}

function courseContextOverride(to) {
  const isLegacyInteractiveModel = (
    to.name === 'InteractiveModelResource'
    && String(to.params?.resourceId || '') === 'legacy'
  )
  return isLegacyInteractiveModel ? { resourceId: null } : null
}

function unknownRouteRedirect(to) {
  return {
    path: '/context-recovery',
    query: {
      ...to.query,
      reason: 'route_unknown',
      legacy_path: to.path,
      return_to: to.fullPath,
    },
    replace: true,
  }
}

const legacyHistoryRoute = legacy('/history', 'LegacyHistory', '/profile/history')
const legacyRoutes = [
  legacyHistoryRoute,
  ...CURRENT_ROUTE_MIGRATION_CONTRACT
    .filter((contract) => contract.sourcePath !== '/history' && !TARGET_ROUTE_PATH_SET.has(contract.sourcePath))
    .map(legacy),
]

const routes = [
  {
    path: '/landing',
    name: 'Landing',
    component: Landing,
    meta: { layout: 'full', title: 'EduMatrix', targetRoute: true },
    beforeEnter: () => {
      const token = localStorage.getItem('edumatrix_token')
      const role = localStorage.getItem('edumatrix_role')
      if (token && ['student', 'teacher', 'admin'].includes(role)) return roleLandingPath(role)
      return true
    },
  },
  {
    path: '/login',
    name: 'Login',
    component: Login,
    meta: { layout: 'full', title: '登录', targetRoute: true },
  beforeEnter: () => {
      if (localStorage.getItem('edumatrix_token')) {
        const role = localStorage.getItem('edumatrix_role')
        if (!['student', 'teacher', 'admin'].includes(role)) {
          localStorage.removeItem('edumatrix_token')
          return '/login'
        }
        return roleLandingPath(role)
      }
      return true
    },
  },
  {
    path: '/onboarding',
    name: 'Onboarding',
    component: Onboarding,
    meta: { layout: 'full', title: '首次学习引导', targetRoute: true },
    beforeEnter: () => {
      if (!localStorage.getItem('edumatrix_token')) return '/landing'
      const role = localStorage.getItem('edumatrix_role')
      if (role !== 'student') return roleLandingPath(role)
      if (localStorage.getItem('edumatrix_onboarded') === 'true') return '/'
      return true
    },
  },

  { path: '/', name: 'Dashboard', component: Dashboard, beforeEnter: requireAuth, meta: targetMeta('首页', '今日学习', STUDENT, { navigationLevel: 'primary', courseScoped: true }) },
  { path: '/profile', name: 'ProfileDashboard', component: ProfileDashboard, beforeEnter: requireAuth, meta: targetMeta('个人中心', '学习记录', STUDENT, { navigationLevel: 'primary' }) },
  { path: '/profile/learning', name: 'StudentAnalysis', component: StudentAnalysis, beforeEnter: requireAuth, meta: targetMeta('学习画像', '个人中心', STUDENT, { courseScoped: true }) },
  { path: '/profile/update', name: 'ProfileUpdateConversation', component: ProfileUpdateConversation, beforeEnter: requireAuth, meta: targetMeta('更新学习状态', '学习画像', STUDENT, { courseScoped: true }) },
  { path: '/profile/history', name: 'History', component: History, beforeEnter: requireAuth, meta: targetMeta('历史与学习记录', '个人中心', STUDENT, { courseScoped: true }) },
  { path: '/workspace', name: 'LearningWorkspace', component: LearningWorkspace, beforeEnter: requireAuth, meta: targetMeta('学习空间', '当前课程', STUDENT, { navigationLevel: 'primary', courseScoped: true }) },
  {
    path: '/chat',
    name: 'ChatEntry',
    redirect: (to) => ({ path: '/learn', query: to.query }),
    beforeEnter: requireAuth,
    meta: targetMeta('智能对话', '学习伙伴', STUDENT, { courseScoped: false }),
  },
  { path: '/learn', name: 'Learn', component: Chat, beforeEnter: requireAuth, meta: targetMeta('智能对话', '学习伙伴', STUDENT, { navigationLevel: 'primary', courseScoped: false }) },
  { path: '/knowledge', name: 'Knowledge', component: Knowledge, beforeEnter: requireAuth, meta: targetMeta('知识库', '预置课程', STUDENT_AND_TEACHER, { navigationLevel: 'primary', courseScoped: true }) },
  { path: '/marketplace', name: 'Marketplace', component: MarketplaceWorkspace, beforeEnter: requireAuth, meta: targetMeta('学习市场', '资源发现', STUDENT_AND_TEACHER, { navigationLevel: 'primary' }) },
  { path: '/settings', name: 'Settings', component: Settings, beforeEnter: requireAuth, meta: targetMeta('设置', '偏好与连接', ['student', 'teacher', 'admin'], { navigationLevel: 'primary' }) },

  { path: '/workspace/assessment', name: 'AssessmentCenter', component: AssessmentWorkspace, beforeEnter: requireAuth, meta: targetMeta('测评中心', '学习空间', STUDENT, { courseScoped: true }) },
  { path: '/workspace/assessment/entry', name: 'EntryAssessment', component: EntryDiagnostic, beforeEnter: requireAuth, meta: targetMeta('入学诊断', '测评中心', STUDENT, { courseScoped: true }) },
  { path: '/workspace/assessment/exams', name: 'IntelligentExams', component: FormalExamWorkspace, beforeEnter: requireAuth, meta: targetMeta('智能组卷', '测评中心', STUDENT, { courseScoped: true }) },
  { path: '/workspace/assessment/exams/:examId', name: 'ExamDetail', component: FormalExamWorkspace, beforeEnter: requireAuth, meta: targetMeta('试卷作答与报告', '智能组卷', STUDENT, { courseScoped: true }) },
  { path: '/workspace/path', name: 'LearningPath', component: LearningPathGraph, beforeEnter: requireAuth, meta: targetMeta('学习路径', '学习空间', STUDENT, { courseScoped: true }) },
  { path: '/workspace/resources', name: 'WorkspaceResources', component: ResourceCenter, beforeEnter: requireAuth, meta: targetMeta('资源中心', '学习空间', STUDENT, { courseScoped: true }) },
  { path: '/workspace/resources/handouts/:resourceId', name: 'HandoutResource', component: HandoutWorkspace, beforeEnter: requireAuth, meta: targetMeta('个性化讲义', '资源中心', STUDENT_AND_TEACHER, { courseScoped: true }) },
  { path: '/workspace/resources/training-tasks/:resourceId', name: 'TrainingTaskResource', component: TrainingTaskWorkspace, beforeEnter: requireAuth, meta: targetMeta('实训任务书', '资源中心', STUDENT_AND_TEACHER, { courseScoped: true }) },
  { path: '/workspace/resources/mindmaps/:resourceId', name: 'MindmapResource', component: MindmapWorkspace, beforeEnter: requireAuth, meta: targetMeta('思维导图', '资源中心', STUDENT_AND_TEACHER, { courseScoped: true }) },
  { path: '/workspace/resources/videos/:resourceId', name: 'VideoResource', component: VideoRecommendationWorkspace, beforeEnter: requireAuth, meta: targetMeta('视频推荐', '资源中心', STUDENT_AND_TEACHER, { courseScoped: true }) },
  { path: '/workspace/resources/decks/:resourceId', name: 'DeckResource', component: WebDeckWorkspace, beforeEnter: requireAuth, meta: targetMeta('PPT与网页课件', '资源中心', STUDENT_AND_TEACHER, { courseScoped: true }) },
  { path: '/workspace/resources/models/:resourceId', name: 'InteractiveModelResource', component: InteractiveLabWorkspace, beforeEnter: requireAuth, meta: targetMeta('可交互模型', '资源中心', STUDENT_AND_TEACHER, { courseScoped: true }) },
  { path: '/workspace/resources/bundles/:bundleId', name: 'ResourceBundle', component: ResourceBundleWorkspace, beforeEnter: requireAuth, meta: targetMeta('资源包', '资源中心', STUDENT_AND_TEACHER, { courseScoped: true }) },
  { path: '/workspace/resources/quizzes/:resourceId', name: 'QuizResource', component: QuizResourceWorkspace, beforeEnter: requireAuth, meta: targetMeta('测验题资源', '资源中心', STUDENT_AND_TEACHER, { courseScoped: true }) },
  { path: '/workspace/code/:resourceId', name: 'CodeSandbox', component: CodeSandboxWorkspace, beforeEnter: requireAuth, meta: targetMeta('代码沙盒', '学习空间', STUDENT, { courseScoped: true }) },
  { path: '/workspace/feynman/:resourceId', name: 'FeynmanResource', component: FeynmanWorkspace, beforeEnter: requireAuth, meta: targetMeta('费曼复述', '学习空间', STUDENT, { courseScoped: true }) },
  { path: '/workspace/review', name: 'ReviewCenter', component: Review, beforeEnter: requireAuth, meta: targetMeta('复习中心', '学习空间', STUDENT, { courseScoped: true }) },
  { path: '/workspace/review/calendar', name: 'ReviewCalendar', component: RevisionCalendar, beforeEnter: requireAuth, meta: targetMeta('复习日历', '复习中心', STUDENT, { courseScoped: true }) },
  { path: '/workspace/review/wrong-questions', name: 'WrongQuestionBook', component: WrongQuestionBook, beforeEnter: requireAuth, meta: targetMeta('错题本', '复习中心', STUDENT, { courseScoped: true }) },
  { path: '/workspace/notes', name: 'Notes', component: Notes, beforeEnter: requireAuth, meta: targetMeta('笔记本', '学习空间', STUDENT, { courseScoped: true }) },

  { path: '/knowledge/courses/:courseId', name: 'KnowledgeCourse', component: Knowledge, beforeEnter: requireAuth, meta: targetMeta('课程知识库', '知识库', STUDENT_AND_TEACHER, { courseScoped: true, allowEmptyCourse: true }) },
  { path: '/knowledge/documents/:documentId', name: 'KnowledgeDocument', component: KnowledgeDocumentReader, beforeEnter: requireAuth, meta: targetMeta('文档阅读器', '知识库', STUDENT_AND_TEACHER, { courseScoped: true }) },
  { path: '/knowledge/graph/:courseId', name: 'KnowledgeGraph', component: KnowledgeGraphWorkspace, beforeEnter: requireAuth, meta: targetMeta('课程知识图谱', '知识库', STUDENT_AND_TEACHER, { courseScoped: true }) },
  { path: '/knowledge/discover', name: 'KnowledgeDiscover', component: KnowledgeDiscoveryWorkspace, beforeEnter: requireAuth, meta: targetMeta('教材与来源发现', '知识库', STUDENT_AND_TEACHER) },
  { path: '/marketplace/items/:itemId', name: 'MarketplaceItem', component: MarketplaceWorkspace, beforeEnter: requireAuth, meta: targetMeta('学习资源详情', '学习市场', STUDENT_AND_TEACHER) },
  { path: '/marketplace/publish', name: 'MarketplacePublish', component: MarketplaceWorkspace, beforeEnter: requireAuth, meta: targetMeta('发布学习内容', '学习市场', STUDENT_AND_TEACHER) },
  { path: '/marketplace/mine', name: 'MarketplaceMine', component: MarketplaceWorkspace, beforeEnter: requireAuth, meta: targetMeta('我的分享与收藏', '学习市场', STUDENT_AND_TEACHER) },

  { path: '/teacher/overview', name: 'TeacherOverview', component: Teacher, beforeEnter: requireTeacher, meta: targetMeta('教学总览', '教师工作区', TEACHING, { navigationLevel: 'primary' }) },
  { path: '/teacher/courses', name: 'TeacherCourses', component: Teacher, beforeEnter: requireTeacher, meta: targetMeta('课程与资源', '教师工作区', TEACHING, { navigationLevel: 'primary' }) },
  { path: '/teacher/courses/:courseId', name: 'TeacherCourseDetail', component: Teacher, beforeEnter: requireTeacher, meta: targetMeta('课程详情', '课程与资源', TEACHING, { courseScoped: true }) },
  { path: '/teacher/students', name: 'TeacherStudents', component: Teacher, beforeEnter: requireTeacher, meta: targetMeta('学生学情', '教师工作区', TEACHING, { navigationLevel: 'primary' }) },
  { path: '/teacher/students/:studentId', name: 'TeacherStudentDetail', component: Teacher, beforeEnter: requireTeacher, meta: targetMeta('学生详情', '学生学情', TEACHING, { courseScoped: true }) },
  { path: '/teacher/assessment', name: 'TeacherAssessment', component: FormalExamWorkspace, beforeEnter: requireTeacher, meta: targetMeta('测评管理', '教师工作区', TEACHING, { navigationLevel: 'primary' }) },
  { path: '/teacher/interventions', name: 'TeacherInterventions', component: TeacherInterventions, beforeEnter: requireTeacher, meta: targetMeta('干预任务', '教师工作区', TEACHING, { navigationLevel: 'primary' }) },

  { path: '/admin/accounts', name: 'AdminAccounts', component: AdminAccounts, beforeEnter: requireAdmin, meta: targetMeta('账号权限', '管理工作区', ADMIN, { navigationLevel: 'primary' }) },
  { path: '/admin/models', name: 'AdminModels', component: ModelOperationsWorkspace, beforeEnter: requireAdmin, meta: targetMeta('模型配置', '管理工作区', ADMIN, { navigationLevel: 'primary' }) },
  { path: '/admin/content-review', name: 'AdminContentReview', component: ContentReviewWorkspace, beforeEnter: requireAdmin, meta: targetMeta('内容审核', '管理工作区', ADMIN, { navigationLevel: 'primary' }) },
  { path: '/admin/system', name: 'AdminSystem', component: AdminSystem, beforeEnter: requireAdmin, meta: targetMeta('系统状态', '管理工作区', ADMIN, { navigationLevel: 'primary' }) },

  ...legacyRoutes,

  {
    path: '/context-recovery',
    name: 'ContextRecovery',
    component: ContextRecovery,
    beforeEnter: requireAuth,
    meta: { title: '恢复学习位置', section: '当前课程', requiresAuth: true },
  },

  { path: '/:pathMatch(.*)*', name: 'NotFound', beforeEnter: unknownRouteRedirect, meta: { requiresAuth: true } },
]

for (const route of routes) {
  const contract = ROUTE_MIGRATION_BY_PATH.get(route.path)
  if (!contract) continue
  route.meta = {
    ...(route.meta || {}),
    disposition: contract.disposition,
    destination: contract.destination,
    featureFlag: contract.featureFlag,
    rollbackRoute: contract.rollbackRoute,
    sourceRoute: contract.sourcePath,
  }
}

const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.beforeEach(async (to) => {
  if (!to.meta.requiresAuth && !to.meta.roles && !to.meta.courseScoped) return true
  const token = localStorage.getItem('edumatrix_token')
  if (!token) {
    if (to.path === '/') return '/landing'
    return { path: '/login', query: { redirect: to.fullPath } }
  }

  const context = useContextStore()
  try {
    const identity = await context.ensureIdentity()
    if (Array.isArray(to.meta.roles) && !to.meta.roles.includes(identity?.role)) {
      return { path: roleLandingPath(identity?.role), query: { access: 'forbidden' } }
    }
    if (to.meta.courseScoped) {
      await useCourseContextStore().restoreFromRoute(to, courseContextOverride(to))
    }
    return true
  } catch (error) {
    const currentRole = context.role || localStorage.getItem('edumatrix_role')
    const contextDetail = error?.contextDetail
    if (isContextResolutionError(error)) {
      const candidate = contextDetail.context || {}
      const courseUnavailable = (
        contextDetail.field === 'courseId'
        && ['context_course_unavailable', 'context_object_not_found'].includes(contextDetail.code)
      )
      if (courseUnavailable && to.meta.allowEmptyCourse) return true
      return {
        path: '/context-recovery',
        query: {
          reason: contextDetail.code,
          field: contextDetail.field || undefined,
          object_id: courseUnavailable
            ? undefined
            : candidate.resourceId || candidate.taskId || candidate.attemptId || candidate.sourceRefId || candidate.knowledgePointId || candidate.chapterId || undefined,
          course_id: courseUnavailable ? undefined : candidate.courseId || undefined,
          return_to: courseUnavailable ? undefined : to.fullPath,
        },
      }
    }
    const requestStatus = Number(error?.status || error?.response?.status || 0)
    if (requestStatus === 403) return { path: roleLandingPath(currentRole), query: { access: 'forbidden' } }
    if (requestStatus === 404) return { path: roleLandingPath(currentRole), query: { access: 'course-not-found' } }
    return { path: '/login', query: { reason: 'session-expired', redirect: to.fullPath } }
  }
})

export default router
