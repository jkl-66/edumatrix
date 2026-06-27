import { createRouter, createWebHistory } from 'vue-router'
import Login from '../views/Login.vue'
import Dashboard from '../views/Dashboard.vue'
import Chat from '../views/Chat.vue'
import Notes from '../views/Notes.vue'
import Review from '../views/Review.vue'
import Teacher from '../views/Teacher.vue'
import History from '../views/History.vue'
import Knowledge from '../views/Knowledge.vue'
import ProfileDashboard from '../views/ProfileDashboard.vue'
import Settings from '../views/Settings.vue'
import LearningPathGraph from '../views/LearningPathGraph.vue'
import WrongQuestionBook from '../views/WrongQuestionBook.vue'
import RevisionCalendar from '../views/RevisionCalendar.vue'

import StudentAnalysis from '../views/StudentAnalysis.vue'

function requireAuth() {
  const token = localStorage.getItem('edumatrix_token')
  if (!token) return '/login'
  return true
}

const routes = [
  { path: '/login', name: 'Login', component: Login },
  { path: '/', name: 'Dashboard', component: Dashboard, beforeEnter: requireAuth },
  { path: '/learn', name: 'Learn', component: Chat, beforeEnter: requireAuth },
  { path: '/notes', name: 'Notes', component: Notes, beforeEnter: requireAuth },
  { path: '/review', name: 'Review', component: Review, beforeEnter: requireAuth },
  { path: '/teacher', name: 'Teacher', component: Teacher, beforeEnter: requireAuth, alias: ['/teacher/overview'] },
  { path: '/teacher/students', name: 'TeacherStudents', component: Teacher, beforeEnter: requireAuth },
  { path: '/teacher/reviews', name: 'TeacherReviews', component: Teacher, beforeEnter: requireAuth },
  { path: '/teacher/reports', name: 'TeacherReports', component: Teacher, beforeEnter: requireAuth },
  { path: '/history', name: 'History', component: History, beforeEnter: requireAuth },
  { path: '/knowledge', name: 'Knowledge', component: Knowledge, beforeEnter: requireAuth },
  { path: '/profile', name: 'ProfileDashboard', component: ProfileDashboard, beforeEnter: requireAuth },
  { path: '/settings', name: 'Settings', component: Settings, beforeEnter: requireAuth },
  { path: '/learning-path', name: 'LearningPathGraph', component: LearningPathGraph, beforeEnter: requireAuth },
  { path: '/wrong-questions', name: 'WrongQuestionBook', component: WrongQuestionBook, beforeEnter: requireAuth },
  { path: '/revision-calendar', name: 'RevisionCalendar', component: RevisionCalendar, beforeEnter: requireAuth },
  { path: '/student-analysis', name: 'StudentAnalysis', component: StudentAnalysis, beforeEnter: requireAuth },
]

export default createRouter({
  history: createWebHistory(),
  routes,
})
