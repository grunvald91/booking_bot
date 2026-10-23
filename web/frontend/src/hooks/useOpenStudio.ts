import { useState } from 'react'
import { api } from '../api/client'

/**
 * Открывает маркетинговую студию для выбранного заведения по одноразовой ссылке: студия узнаёт, кто вы и какое
 * заведение открыто, и при первом входе сама создаёт компанию из данных заведения.
 * Если вход не настроен или не получился — обычный вход в студию, как раньше.
 */
export function useOpenStudio(businessId: number | null | undefined) {
  const [busy, setBusy] = useState(false)
  const open = async () => {
    if (busy) return
    setBusy(true)
    try {
      if (businessId == null) throw new Error('no business')
      const { url } = await api.studioTicket(businessId)
      window.location.assign(url)
    } catch {
      window.location.assign('https://growth.servgo.ru/studio')
    }
  }
  return { open, busy }
}
