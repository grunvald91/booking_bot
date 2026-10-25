import { api } from '../api/client'

/**
 * Куда вести человека сразу после входа (Telegram, email или Яндекс ID):
 * владельцев в админку, мастеров в их расписание, остальных в «Мои записи».
 */
export async function postLoginPath(role: string): Promise<string> {
  if (role !== 'client') return '/admin'
  try {
    const me = await api.masterMe()
    if (me.employees.length > 0) return '/master'
  } catch {
    // Нет кабинета мастера или сервер недоступен: обычный вход клиента.
  }
  return '/my'
}
