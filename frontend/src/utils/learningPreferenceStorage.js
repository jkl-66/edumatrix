// Keep this browser's preferences separate for each signed-in learner.
function owner() {
  return localStorage.getItem('edumatrix_username') || localStorage.getItem('edumatrix_student_id') || ''
}

export function readPreference(key, fallback = null) {
  const account = owner()
  if (!account) return localStorage.getItem(key) ?? fallback
  const saved = localStorage.getItem(`${key}:${account}`)
  if (saved !== null) return saved
  const legacyOwnerKey = 'edumatrix_preferences_legacy_owner'
  let legacyOwner = localStorage.getItem(legacyOwnerKey)
  if (!legacyOwner) {
    legacyOwner = account
    localStorage.setItem(legacyOwnerKey, account)
  }
  return legacyOwner === account ? localStorage.getItem(key) ?? fallback : fallback
}

export function writePreference(key, value) {
  const account = owner()
  localStorage.setItem(account ? `${key}:${account}` : key, String(value))
}
