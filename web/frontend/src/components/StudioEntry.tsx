import { useEffect, useState } from 'react'
import { Sparkles } from 'lucide-react'
import { api } from '../api/client'

type Entry = { id: number; name: string; role: string }

/**
 * Вход в маркетинговую студию (AI Growth OS) для тех, у кого он открыт: владельцев и администраторов,
 * которым владелец включил доступ. Ничего не показывает, пока доступа нет или вход не настроен.
 */
export function StudioEntry() {
  const [items, setItems] = useState<Entry[]>([])
  const [busy, setBusy] = useState<number | null>(null)
  const [error, setError] = useState('')
  useEffect(() => {
    if (!localStorage.getItem('token')) return
    api.studioBusinesses().then(setItems).catch(() => setItems([]))
  }, [])
  if (items.length === 0) return null
  const open = async (id: number) => {
    if (busy !== null) return
    setBusy(id); setError('')
    try {
      const { url } = await api.studioTicket(id)
      window.location.assign(url)
    } catch {
      setBusy(null)
      setError('Не удалось открыть маркетинг. Попробуйте ещё раз.')
    }
  }
  return (
    <div className="bf-account-actions" style={{ marginTop: 0, marginBottom: 14 }}>
      {items.map((item) => (
        <button key={item.id} type="button" className="bf-account-row" disabled={busy !== null} onClick={() => open(item.id)}>
          <Sparkles />
          <span>{items.length > 1 ? `Маркетинг — ${item.name}` : 'Маркетинг — AI Growth OS'}</span>
        </button>
      ))}
      {error && <p role="alert" className="ds-caption">{error}</p>}
    </div>
  )
}
