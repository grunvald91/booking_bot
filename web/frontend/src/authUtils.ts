import type { AuthResponse } from './api/client'

export function errorMessage(error: unknown) {
  const message = error instanceof Error ? error.message : 'Не удалось выполнить действие'
  try {
    const detail = JSON.parse(message).detail
    return typeof detail === 'string' ? detail : 'Проверьте введённые данные'
  } catch { return message }
}

export function clearLogin() {
  localStorage.removeItem('token')
  localStorage.removeItem('userRole')
  localStorage.removeItem('userName')
}

export function saveLogin(res: AuthResponse) {
  localStorage.setItem('token', res.token)
  localStorage.setItem('userRole', res.role)
  localStorage.setItem('userName', res.user.full_name)
  sessionStorage.removeItem('servgoExplicitLogout')
}
