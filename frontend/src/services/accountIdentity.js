export function rememberAccountIdentity(data) {
  localStorage.setItem('edumatrix_display_name', data.display_name || data.username || '学习者')
  localStorage.setItem('edumatrix_avatar_url', data.avatar_url || '')
  window.dispatchEvent(new Event('edumatrix-identity-changed'))
}
