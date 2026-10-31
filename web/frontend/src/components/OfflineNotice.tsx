import { useEffect, useState } from 'react'
import { useConnectivity } from '../utils/useConnectivity'

/** Shows stale-data context without replacing the previously visited schedule. */
export function OfflineNotice() {
  const online = useConnectivity()
  const [savedAt, setSavedAt] = useState<number | null>(null)
  useEffect(() => {
    const onSnapshot = (event: Event) => {
      const detail = (event as CustomEvent<{ savedAt: number }>).detail
      if (typeof detail?.savedAt === 'number') setSavedAt(detail.savedAt)
    }
    window.addEventListener('servgo-offline-snapshot-used', onSnapshot)
    return () => window.removeEventListener('servgo-offline-snapshot-used', onSnapshot)
  }, [])
  useEffect(() => { if (online) setSavedAt(null) }, [online])
  if (online) return null
  const when = savedAt == null
    ? null
    : new Date(savedAt).toLocaleString('ru-RU', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })
  return (
    <div role="status" aria-live="polite" style={{
      position: 'fixed', top: 0, left: 0, right: 0, zIndex: 9999,
      padding: '8px 14px', textAlign: 'center', background: '#263d59',
      color: '#fff', fontSize: 13, lineHeight: 1.4,
      boxShadow: '0 2px 10px rgba(0,0,0,.14)',
    }}>
      Нет соединения — просмотр сохранённых записей.
      {when ? ` Обновлено: ${when}.` : ' Данные появятся, если ранее открывались с интернетом.'}
      {' '}Изменения доступны только онлайн.
    </div>
  )
}
