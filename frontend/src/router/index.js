import { createRouter, createWebHistory } from 'vue-router'
import { useContextStore } from '../stores/context'
const Landing = () => import('../views/Landing.vue')
const Login = () => import('../views/Login.vue')
const Onboarding = () => import('../views/Onboarding.vue')
const Dashboard = () => import('../views/Dashboard.vue')
const Chat = () => import('../views/Chat.vue')
const Notes = () => import('../views/Notes.vue')
const Review = () => import('../views/Review.vue')
const Teacher = () => import('../views/Teacher.vue')
const History = () => import('../views/History.vue')
const Knowledge = () => import('../views/Knowledge.vue')
const ProfileDashboard = () => import('../views/ProfileDashboard.vue')
const Settings = () => import('../views/Settings.vue')
const LearningPathGraph = () => import('../views/LearningPathGraph.vue')
const WrongQuestionBook = () => import('../views/WrongQuestionBook.vue')
const RevisionCalendar = () => import('../views/RevisionCalendar.vue')
const StudentAnalysis = () => import('../views/StudentAnalysis.vue')
const InternalObjectInspector = () => import('../views/InternalObjectInspector.vue')

function requireAuth() {
  const token = localStorage.getItem('edumatrix_token')
  if (!token) return '/landing'
  const role = localStorage.getItem('edumatrix_role')
  const onboarded = localStorage.getItem('edumatrix_onboarded') === 'true'
  if (role === 'student' && !onboarded) {
    return '/onboarding'
  }
  return true
}

// 教师路由守卫：只允许教师角色访问
function requireTeacher() {
  const token = localStorage.getItem('edumatrix_token')
  if (!token) return '/landing'
  const role = localStorage.getItem('edumatrix_role')
  if (!['teacher', 'admin'].includes(role)) return '/'
  return true
}

const routes = [
  { 
    path: '/landing', 
    name: 'Landing', 
    component: Landing,
    meta: { layout: 'full' },
    beforeEnter: () => {
      const token = localStorage.getItem('edumatrix_token')
      if (token) return '/'
      return true
    }
  },
  { 
    path: '/login', 
    name: 'Login', 
    component: Login,
    meta: { layout: 'full' },
    beforeEnter: () => {
      const token = localStorage.getItem('edumatrix_token')
      if (token) return '/'
      return true
    }
  },
  {
    path: '/onboarding',
    name: 'Onboarding',
    component: Onboarding,
    meta: { layout: 'full' },
    beforeEnter: () => {
      const token = localStorage.getItem('edumatrix_token')
      if (!token) return '/landing'
      const role = localStorage.getItem('edumatrix_role')
      if (role !== 'student') return '/'
      const onboarded = localStorage.getItem('edumatrix_onboarded') === 'true'
      if (onboarded) return '/'
      return true
    }
  },
  { path: '/', name: 'Dashboard', component: Dashboard, beforeEnter: requireAuth, meta: { requiresAuth: true } },
  { path: '/learn', name: 'Learn', component: Chat, beforeEnter: requireAuth, meta: { requiresAuth: true, courseScoped: true } },
  { path: '/notes', name: 'Notes', component: Notes, beforeEnter: requireAuth },
  { path: '/review', name: 'Review', component: Review, beforeEnter: requireAuth },
  { path: '/teacher', name: 'Teacher', component: Teacher, beforeEnter: requireTeacher, alias: ['/teacher/overview'], meta: { requiresAuth: true, roles: ['teacher', 'admin'] } },
  { path: '/teacher/students', name: 'TeacherStudents', component: Teacher, beforeEnter: requireTeacher, meta: { requiresAuth: true, roles: ['teacher', 'admin'] } },
  { path: '/teacher/reviews', name: 'TeacherReviews', component: Teacher, beforeEnter: requireTeacher, meta: { requiresAuth: true, roles: ['teacher', 'admin'] } },
  { path: '/teacher/reports', name: 'TeacherReports', component: Teacher, beforeEnter: requireTeacher, meta: { requiresAuth: true, roles: ['teacher', 'admin'] } },
  { path: '/history', name: 'History', component: History, beforeEnter: requireAuth },
  { path: '/knowledge', name: 'Knowledge', component: Knowledge, beforeEnter: requireAuth, meta: { requiresAuth: true, courseScoped: true } },
  { path: '/profile', name: 'ProfileDashboard', component: ProfileDashboard, beforeEnter: requireAuth },
  { path: '/settings', name: 'Settings', component: Settings, beforeEnter: requireAuth },
  { path: '/learning-path', name: 'LearningPathGraph', component: LearningPathGraph, beforeEnter: requireAuth, meta: { requiresAuth: true, courseScoped: true } },
  { path: '/wrong-questions', name: 'WrongQuestionBook', component: WrongQuestionBook, beforeEnter: requireAuth },
  { path: '/revision-calendar', name: 'RevisionCalendar', component: RevisionCalendar, beforeEnter: requireAuth },
  { path: '/student-analysis', name: 'StudentAnalysis', component: StudentAnalysis, beforeEnter: requireAuth },
  { path: '/internal/objects', name: 'InternalObjectInspector', component: InternalObjectInspector, beforeEnter: requireTeacher, meta: { requiresAuth: true, roles: ['teacher', 'admin'] } },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.beforeEach(async (to) => {
  if (!to.meta.requiresAuth && !to.meta.roles && !to.meta.courseScoped) return true
  const token = localStorage.getItem('edumatrix_token')
  if (!token) return { path: '/login', query: { redirect: to.fullPath } }
  const context = useContextStore()
  try {
    const identity = await context.ensureIdentity()
    if (Array.isArray(to.meta.roles) && !to.meta.roles.includes(identity?.role)) {
      return { path: '/', query: { access: 'forbidden' } }
    }
    if (to.meta.courseScoped) {
      const courseId = String(to.query.course_id || localStorage.getItem('edumatrix_course_id') || '')
      if (courseId) await context.loadCourse(courseId)
    }
    return true
  } catch (error) {
    if (error?.status === 403) return { path: '/', query: { access: 'forbidden' } }
    if (error?.status === 404) return { path: '/', query: { access: 'course-not-found' } }
    return { path: '/login', query: { reason: 'session-expired', redirect: to.fullPath } }
  }
})

export default router
