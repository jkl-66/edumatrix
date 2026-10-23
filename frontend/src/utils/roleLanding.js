export function roleLandingPath(role) {
  if (role === 'admin') return '/admin/system'
  if (role === 'teacher') return '/teacher/overview'
  if (role === 'student') return '/'
  return '/login'
}
