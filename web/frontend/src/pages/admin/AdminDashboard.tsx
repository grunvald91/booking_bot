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

  // Load business photos when selected business changes
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

  if (loading) {
    return (
      <div className="space-y-6">
        <div className="grid grid-cols-2 gap-4">
          {[1, 2, 3, 4].map((i) => (
            <div key={i} className="h-28 skeleton rounded-2xl" />
          ))}
        </div>
      </div>
    )
  }

  if (!data) return null

  const stats = [
    {
      label: 'Записей сегодня',
      value: data.today_bookings,
      icon: Calendar,
      color: 'bg-blue-50 text-apple-blue',
    },
    {
      label: 'Выручка',
      value: `${new Intl.NumberFormat('ru-RU').format(data.total_revenue)} ₽`,
      icon: DollarSign,
      color: 'bg-green-50 text-apple-success',
    },
    {
      label: 'Подтверждено',
      value: data.confirmed_count,
      icon: CheckCircle,
      color: 'bg-emerald-50 text-emerald-600',
    },
    {
      label: 'Ожидает',
      value: data.pending_count,
      icon: AlertCircle,
      color: 'bg-amber-50 text-amber-600',
    },
  ]

  return (
    <div>
      <BusinessSelector businesses={businesses} selectedId={businessId} onSelect={selectBusiness} vertical />
      <h1 className="text-lg font-bold text-apple-text mb-3">Панель управления</h1>

      {/* Stats cards */}
      <div className="grid grid-cols-2 gap-3">
        {stats.map((stat) => {
          const Icon = stat.icon
          return (
            <div
              key={stat.label}
              className="bg-white rounded-2xl shadow-sm border border-apple-border/50 p-4"
            >
              <div className="flex items-center gap-2 mb-2">
                <div
                  className={`w-8 h-8 rounded-lg flex items-center justify-center ${stat.color}`}
                >
                  <Icon size={16} />
                </div>
                <span className="text-xs text-apple-gray">{stat.label}</span>
              </div>
              <p className="text-xl font-bold text-apple-text">{stat.value}</p>
            </div>
          )
        })}
      </div>

      {/* Business Photo Management */}
      {businessId && (
        <div className="mt-4">
          <h2 className="text-sm font-semibold text-apple-text mb-2 flex items-center gap-2">
            <Camera size={16} />
            Фото бизнеса
          </h2>
          <div className="bg-white rounded-2xl shadow-sm border border-apple-border/50 p-4">
            <div className="flex flex-wrap gap-2">
              {bizPhotos.map((fileId, i) => (
                <div key={i} className="relative w-20 h-20 rounded-xl overflow-hidden group">
                  <img
                    src={`/api/telegram-photo/${encodeURIComponent(fileId)}`}
                    alt={`Фото ${i + 1}`}
                    className="w-full h-full object-cover"
                  />
                  <button
                    onClick={() => handlePhotoDelete(i)}
                    className="absolute top-1 right-1 w-5 h-5 bg-red-500 text-white rounded-full flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity"
                  >
                    <Trash2 size={10} />
                  </button>
                </div>
              ))}
              <button
                onClick={() => photoInputRef.current?.click()}
                disabled={photoUploading}
                className="w-20 h-20 rounded-xl border-2 border-dashed border-apple-border flex items-center justify-center text-apple-gray hover:border-apple-blue hover:text-apple-blue transition-all disabled:opacity-50"
              >
                {photoUploading ? (
                  <div className="w-5 h-5 border-2 border-apple-blue border-t-transparent rounded-full animate-spin" />
                ) : (
                  <Plus size={24} />
                )}
              </button>
            </div>
            <input
              ref={photoInputRef}
              type="file"
              accept="image/*"
              className="hidden"
              onChange={handlePhotoUpload}
            />
            <p className="text-xs text-apple-gray mt-2">
              Первое фото будет показано на главной странице
            </p>
          </div>
        </div>
      )}
    </div>
  )
}
