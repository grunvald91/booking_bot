import { useState, useEffect, useRef } from 'react'
import { Link } from 'react-router-dom'
import {
  Calendar,
  DollarSign,
  CheckCircle,
  AlertCircle,
  Camera,
  Trash2,
  Plus,
} from 'lucide-react'
import { api, type AdminBooking, type DashboardData } from '../../api/client'
import { useAdminBusiness } from '../../hooks/useAdminBusiness'
import { BusinessSelector } from '../../components/BusinessSelector'
import { AdminShell } from '../../components/AdminShell'

export function AdminDashboard() {
  const { businesses, selectedId: businessId, selectBusiness } = useAdminBusiness()
  const [data, setData] = useState<DashboardData | null>(null)
  const [loading, setLoading] = useState(true)
  const [bizPhotos, setBizPhotos] = useState<string[]>([])
  const [photoUploading, setPhotoUploading] = useState(false)
  const photoInputRef = useRef<HTMLInputElement>(null)
  const [todayBookings, setTodayBookings] = useState<AdminBooking[] | null>(null)

  // Ближайшие записи на сегодня для верхнего блока «Сегодня в студии»
  useEffect(() => {
    if (!businessId) return
    const d = new Date()
    const today = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
    api
      .getAdminBookings(`business_id=${businessId}&date=${today}`)
      .then((list) => setTodayBookings(list))
      .catch(() => setTodayBookings([]))
  }, [businessId])

  useEffect(() => {
    api
      .getDashboard()
      .then(setData)
      .catch(() => setData({ today_bookings: 0, total_revenue: 0, pending_count: 0, confirmed_count: 0 }))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    if (!businessId) return
    const biz = businesses.find((b) => b.id === businessId)
    if (biz?.photos) {
      try {
        setBizPhotos(JSON.parse(biz.photos))
      } catch {
        setBizPhotos([])
      }
    } else {
      setBizPhotos([])
    }
  }, [businessId, businesses])

  const handlePhotoUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file || !businessId) return
    setPhotoUploading(true)
    try {
      const result = await api.uploadBusinessPhoto(businessId, file)
      setBizPhotos(result.photos)
    } catch (err) {
      alert('Ошибка загрузки фото: ' + (err instanceof Error ? err.message : String(err)))
    } finally {
      setPhotoUploading(false)
      if (photoInputRef.current) photoInputRef.current.value = ''
    }
  }

  const handlePhotoDelete = async (index: number) => {
    if (!businessId || !confirm('Удалить фото?')) return
    try {
      const result = await api.deleteBusinessPhoto(businessId, index)
      setBizPhotos(result.photos)
    } catch (err) {
      alert('Ошибка удаления фото: ' + (err instanceof Error ? err.message : String(err)))
    }
  }

  const stats = data
    ? [
        { label: 'Записей сегодня', value: data.today_bookings, Icon: Calendar, color: 'var(--s-accent)' },
        { label: 'Выручка', value: `${new Intl.NumberFormat('ru-RU').format(data.total_revenue)} ₽`, Icon: DollarSign, color: 'var(--s-success)' },
        { label: 'Подтверждено', value: data.confirmed_count, Icon: CheckCircle, color: 'var(--st-completed)' },
        { label: 'Ожидает', value: data.pending_count, Icon: AlertCircle, color: 'var(--s-warning)' },
      ]
    : []

  const nowMin = new Date().getHours() * 60 + new Date().getMinutes()
  const todayKey = (() => {
    const d = new Date()
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
  })()
  const upcoming = (todayBookings || [])
    .filter((b) => b.date === todayKey && b.status !== 'cancelled' && b.status !== 'completed')
    .filter((b) => {
      const [h, m] = b.time.split(':').map(Number)
      return h * 60 + m + (b.service_duration || 60) >= nowMin
    })
    .sort((a, b) => a.time.localeCompare(b.time))
    .slice(0, 3)
  const cover = bizPhotos[0]

  return (
    <AdminShell
      title="Панель управления"
      headerExtra={<BusinessSelector businesses={businesses} selectedId={businessId} onSelect={selectBusiness} />}
    >
      {/* Сегодня в студии */}
      <div className="ds-context">
        <div className="ds-context-eyebrow">Сегодня{businesses.find((b) => b.id === businessId)?.name ? ` · ${businesses.find((b) => b.id === businessId)?.name}` : ''}</div>
        <div className="ds-context-hero">
          <div className="ds-context-art" aria-hidden="true">
            {cover ? (
              <img src={`/api/telegram-photo/${encodeURIComponent(cover)}`} alt="" />
            ) : (
              <><div className="art-circle" /><div className="art-arch" /><div className="art-chair" /></>
            )}
          </div>
          <div className="ds-context-hero-text">
            <div className="ds-context-headline">Ближайшие записи</div>
            {todayBookings === null ? (
              <div className="ds-context-help">Загружаем…</div>
            ) : upcoming.length === 0 ? (
              <div className="ds-context-help">На сегодня больше нет записей</div>
            ) : (
              upcoming.map((b) => (
                <Link key={b.id} to="/admin/schedule" className="ds-context-line" style={{ textDecoration: 'none' }}>
                  <strong>{b.time}</strong>
                  <span>{b.client_name}{b.service_name ? ` · ${b.service_name}` : ''}</span>
                  <span className={`ds-status-point ${b.status === 'confirmed' ? '' : 'warn'}`} title={b.status === 'confirmed' ? 'Подтверждена' : 'Ожидает'} />
                </Link>
              ))
            )}
          </div>
        </div>
      </div>

      {/* Статистика */}
      <div className="ds-stats-grid" style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6 }}>
        {loading
          ? [1, 2, 3, 4].map((i) => <div key={i} className="skeleton" style={{ height: 80, borderRadius: 14 }} />)
          : stats.map(({ label, value, Icon, color }) => (
              <div key={label} className="ds-card" style={{ padding: '9px 10px', minHeight: 78, display: 'flex', flexDirection: 'column', justifyContent: 'space-between', borderRadius: 14 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                  <span
                    style={{
                      width: 24, height: 24, borderRadius: 10, flexShrink: 0,
                      display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                      background: 'var(--s-surface-3)', color,
                    }}
                  >
                    <Icon size={14} />
                  </span>
                  <span className="ds-sub" style={{ fontSize: 10.5 }}>{label}</span>
                </div>
                <div style={{ fontSize: 21, fontWeight: 470, letterSpacing: '-0.055em', color: 'var(--s-text)', lineHeight: 1.06 }}>{value}</div>
              </div>
            ))}
      </div>

      {/* Фото бизнеса */}
      {businessId && (
        <div style={{ marginTop: 18 }}>
          <h2 className="ds-h3" style={{ display: 'flex', alignItems: 'center', gap: 7, marginBottom: 9 }}>
            <Camera size={16} style={{ color: "var(--s-accent)" }} /> Фото бизнеса
          </h2>
          <div style={{ padding: '4px 0' }}>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
              {bizPhotos.map((fileId, i) => (
                <div key={i} style={{ position: 'relative', width: 72, height: 72, borderRadius: 16, overflow: 'hidden', background: 'var(--s-surface-2)' }}>
                  <img
                    src={`/api/telegram-photo/${encodeURIComponent(fileId)}`}
                    alt={`Фото ${i + 1}`}
                    style={{ width: '100%', height: '100%', objectFit: 'cover' }}
                  />
                  <button
                    onClick={() => handlePhotoDelete(i)}
                    style={{
                      position: 'absolute', top: 4, right: 4, width: 20, height: 20,
                      background: '#fff', color: '#ac5f5f', borderRadius: '50%', border: 'none', boxShadow: '0 2px 8px rgba(0,0,0,.13)',
                      display: 'flex', alignItems: 'center', justifyContent: 'center', cursor: 'pointer',
                    }}
                  >
                    <Trash2 size={10} />
                  </button>
                </div>
              ))}
              <button
                onClick={() => photoInputRef.current?.click()}
                disabled={photoUploading}
                style={{
                  width: 72, height: 72, borderRadius: 16, cursor: 'pointer',
                  border: 0, background: 'var(--s-surface-2)', color: 'var(--s-accent)',
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                }}
              >
                {photoUploading ? (
                  <div className="animate-spin" style={{ width: 20, height: 20, border: '2px solid var(--s-accent)', borderTopColor: 'transparent', borderRadius: '50%' }} />
                ) : (
                  <Plus size={24} />
                )}
              </button>
            </div>
            <input ref={photoInputRef} type="file" accept="image/*" style={{ display: 'none' }} onChange={handlePhotoUpload} />
            <p className="ds-hint">Первое фото будет показано на главной странице</p>
          </div>
        </div>
      )}
    </AdminShell>
  )
}
