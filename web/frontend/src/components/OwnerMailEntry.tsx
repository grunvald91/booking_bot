import { useEffect, useState } from 'react'
import { Mail } from 'lucide-react'
import { useLocation } from 'react-router-dom'

/** Server-confirmed platform-owner navigation. Never trust userRole/localStorage for privileges. */
export function OwnerMailEntry() {
  const [allowed, setAllowed] = useState(false)
  const [busy, setBusy] = useState(false)
  const { pathname } = useLocation()

  useEffect(() => {
    const token = localStorage.getItem('token')
    if (!token) return
    let active = true
    fetch('/api/owner-mail/permission', {
      headers: { Authorization: 'Bearer ' + token },
      cache: 'no-store',
    }).then(response => {
      if (active) setAllowed(response.ok)
    }).catch(() => {
      if (active) setAllowed(false)
    })
    return () => { active = false }
  }, [pathname])

  const open = async () => {
    const token = localStorage.getItem('token')
    if (!token || busy) return
    setBusy(true)
    try {
      const result = await fetch('/api/owner-mail/entry', {
        method: 'POST',
        cache: 'no-store',
        headers: { Authorization: 'Bearer ' + token },
      })
      if (!result.ok) throw new Error('Доступ к почте не подтверждён')
      const data: { url?: string } = await result.json()
      if (!data.url || !data.url.startsWith('https://mail.servgo.ru/claim?ticket=')) {
        throw new Error('Неожиданный адрес почтового кабинета')
      }
      window.location.assign(data.url)
    } catch {
      alert('Не удалось открыть почту. Попробуй снова после входа в ServGo.')
      setBusy(false)
    }
  }

  if (!allowed) return null
  return (
    <button
      type="button"
      onClick={open}
      disabled={busy}
      className="ds-icon-btn bordered"
      style={{ display: 'inline-flex', alignItems: 'center', gap: 6, padding: '8px 10px', width: 'auto' }}
      title="Личная почта ServGo"
      aria-label="Почта"
    >
      <Mail size={18} /> <span style={{ fontSize: 12, fontWeight: 700 }}>Почта</span>
    </button>
  )
}
