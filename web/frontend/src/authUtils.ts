import { clearOfflineSnapshots } from './utils/offlineStore'
import type { AuthResponse } from './api/client'

export function errorMessage(error: unknown) {
  const message = error instanceof Error ? error.message : 'Не удалось выполнить действие'
  try {
    const detail = JSON.parse(message).detail
    return typeof detail === 'string' ? detail : 'Проверьте введённые данные'
  } catch { return message }
}

export async function clearLogin() {
  // Remove the authorization key synchronously to prevent stale-data reads.
  localStorage.removeItem('token')
  localStorage.removeItem('userRole')
  localStorage.removeItem('userName')
  localStorage.removeItem('adminBusinessId')
  window.dispatchEvent(new Event('servgo-logout'))
  // Callers handling explicit logout must await this before navigation.
  await clearOfflineSnapshots()
}

export function saveLogin(res: AuthResponse) {
  localStorage.setItem('token', res.token)
  localStorage.setItem('userRole', res.role)
  localStorage.setItem('userName', res.user.full_name)
  sessionStorage.removeItem('servgoExplicitLogout')
}
