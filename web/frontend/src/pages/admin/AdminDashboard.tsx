import { useState, useEffect, useRef } from 'react'
import {
  Calendar,
  DollarSign,
  CheckCircle,
  AlertCircle,
  Camera,
  Trash2,
  Plus,
} from 'lucide-react'
import { api, type DashboardData } from '../../api/client'
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

  return (
    <AdminShell
      title="Панель управления"
      headerExtra={<BusinessSelector businesses={businesses} selectedId={businessId} onSelect={selectBusiness} />}
    >
      {/* Статистика */}
      <div className="ds-stats-grid" style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, marginTop: 4 }}>
        {loading
          ? [1, 2, 3, 4].map((i) => <div key={i} className="skeleton" style={{ height: 92, borderRadius: 14 }} />)
          : stats.map(({ label, value, Icon, color }) => (
              <div key={label} className="ds-card" style={{ padding: '12px 14px' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
                  <span
                    style={{
                      width: 32, height: 32, borderRadius: 9, flexShrink: 0,
                      display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                      background: 'var(--s-accent-soft)', color,
                    }}
                  >
                    <Icon size={16} />
                  </span>
                  <span className="ds-sub">{label}</span>
                </div>
                <div style={{ fontSize: 22, fontWeight: 750, color: 'var(--s-text)', lineHeight: 1 }}>{value}</div>
              </div>
            ))}
      </div>

      {/* Фото бизнеса */}
      {businessId && (
        <div style={{ marginTop: 18 }}>
          <h2 className="ds-h3" style={{ display: 'flex', alignItems: 'center', gap: 7, marginBottom: 9 }}>
            <Camera size={16} /> Фото бизнеса
          </h2>
          <div className="ds-card" style={{ padding: 14 }}>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
              {bizPhotos.map((fileId, i) => (
                <div key={i} style={{ position: 'relative', width: 80, height: 80, borderRadius: 12, overflow: 'hidden' }}>
                  <img
                    src={`/api/telegram-photo/${encodeURIComponent(fileId)}`}
                    alt={`Фото ${i + 1}`}
                    style={{ width: '100%', height: '100%', objectFit: 'cover' }}
                  />
                  <button
                    onClick={() => handlePhotoDelete(i)}
                    style={{
                      position: 'absolute', top: 4, right: 4, width: 20, height: 20,
                      background: 'var(--s-danger)', color: '#fff', borderRadius: '50%', border: 'none',
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
                  width: 80, height: 80, borderRadius: 12, cursor: 'pointer',
                  border: '2px dashed var(--s-line-2)', background: 'transparent', color: 'var(--s-muted)',
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
