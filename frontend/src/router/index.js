import { createRouter, createWebHistory } from 'vue-router'
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

const routes = [
  { path: '/', name: 'Dashboard', component: Dashboard },
  { path: '/learn', name: 'Learn', component: Chat },
  { path: '/notes', name: 'Notes', component: Notes },
  { path: '/review', name: 'Review', component: Review },
  { path: '/teacher', name: 'Teacher', component: Teacher },
  { path: '/history', name: 'History', component: History },
  { path: '/knowledge', name: 'Knowledge', component: Knowledge },
  { path: '/profile', name: 'ProfileDashboard', component: ProfileDashboard },
  { path: '/settings', name: 'Settings', component: Settings },
  { path: '/learning-path', name: 'LearningPathGraph', component: LearningPathGraph },
  { path: '/wrong-questions', name: 'WrongQuestionBook', component: WrongQuestionBook },
  { path: '/revision-calendar', name: 'RevisionCalendar', component: RevisionCalendar },
]

export default createRouter({
  history: createWebHistory(),
  routes,
})
