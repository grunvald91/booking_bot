import { useState, useEffect } from 'react'
import { useParams, Link } from 'react-router-dom'
import {
  MapPin,
  Phone,
  Clock,
  ChevronLeft,
  User,
  Navigation,
  DoorOpen,
  Users as UsersIcon,
  X,
} from 'lucide-react'
import { api, type BusinessDetail, type EmployeeWithPricing } from '../../api/client'

function parsePhotos(raw?: string): string[] {
  if (!raw) return []
  try {
    const parsed = JSON.parse(raw)
    if (Array.isArray(parsed)) return parsed.filter((v): v is string => typeof v === 'string')
  } catch {
    // Treat as single file_id string
    if (typeof raw === 'string' && raw.length > 0) return [raw]
  }
  return []
}

function linkifyText(text: string): React.ReactNode {
  const urlPattern = /(https?:\/\/[^\s]+|(?:vk\.com|t\.me)\/[^\s]+)/gi
  const parts = text.split(urlPattern)
  if (parts.length === 1) return text
  return parts.map((part, i) => {
    if (/^(https?:\/\/|vk\.com\/|t\.me\/)/i.test(part)) {
      const href = part.startsWith('http') ? part : `https://${part}`
      return (
        <a key={i} href={href} target="_blank" rel="noopener noreferrer" className="text-apple-blue underline">
          {part}
        </a>
      )
    }
    return part
  })
}

function formatWorkingHours(start?: string, end?: string) {
  if (!start || !end) return null
  const fmt = (t: string) => t.substring(0, 5)
  return `${fmt(start)} — ${fmt(end)}`
}

export function BusinessPage() {
  const { id } = useParams<{ id: string }>()
  const [business, setBusiness] = useState<BusinessDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)
  const [selectedEmp, setSelectedEmp] = useState<EmployeeWithPricing | null>(null)

  useEffect(() => {
    if (!id) return
    api
      .getBusiness(Number(id))
      .then(setBusiness)
      .catch(() => setError(true))
      .finally(() => setLoading(false))
  }, [id])

  useEffect(() => {
    if (!selectedEmp) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setSelectedEmp(null)
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [selectedEmp])

  if (loading) {
    return (
      <div className="space-y-6 pb-24">
        <div className="h-8 w-2/3 skeleton" />
        <div className="h-5 w-1/2 skeleton" />
        <div className="space-y-4 mt-8">
          {[1, 2, 3].map((i) => (
            <div key={i} className="h-24 skeleton rounded-2xl" />
          ))}
        </div>
      </div>
    )
  }

  if (error || !business) {
    return (
      <div className="text-center py-20 animate-fade-in">
        <div className="w-20 h-20 bg-white rounded-3xl flex items-center justify-center mx-auto mb-5 shadow-sm">
          <MapPin size={32} className="text-apple-gray" />
        </div>
        <p className="text-apple-gray text-lg font-medium">Бизнес не найден</p>
        <Link to="/" className="text-apple-blue mt-4 inline-block text-sm font-semibold">
          На главную
        </Link>
      </div>
    )
  }

  const workingHours =
    business.working_hours ||
    formatWorkingHours(business.working_hours_start, business.working_hours_end)

  return (
    <div className="pb-28 md:pb-8">
      {/* Back button + Hero */}
      <div className="mb-8 animate-fade-in">
        <Link
          to="/"
          className="inline-flex items-center gap-1 text-sm text-apple-blue font-medium mb-3 hover:text-apple-blue-hover transition-colors duration-200"
        >
          <ChevronLeft size={18} />
          Все бизнесы
        </Link>
        <h1 className="text-2xl md:text-4xl font-extrabold text-apple-text tracking-tight">
          {business.name}
        </h1>
        {business.description && (
          <p className="text-apple-gray mt-2 leading-relaxed whitespace-pre-line">
            {linkifyText(business.description)}
          </p>
        )}

        {/* Info pills */}
        <div className="flex flex-wrap gap-2.5 mt-4">
          {business.address && (
            <a
              href={`https://yandex.ru/maps/?text=${encodeURIComponent(business.address)}`}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1.5 text-[13px] text-apple-blue bg-apple-blue/5 px-3 py-1.5 rounded-full shadow-sm hover:bg-apple-blue/10 transition-colors duration-200"
            >
              <MapPin size={13} />
              {business.address}
            </a>
          )}
          {business.phone && (
            <a
              href={`tel:${business.phone}`}
              className="inline-flex items-center gap-1.5 text-[13px] text-apple-blue bg-apple-blue/5 px-3 py-1.5 rounded-full shadow-sm hover:bg-apple-blue/10 transition-colors duration-200"
            >
              <Phone size={13} />
              {business.phone}
            </a>
          )}
          {workingHours && (
            <span className="inline-flex items-center gap-1.5 text-[13px] text-apple-gray bg-white px-3 py-1.5 rounded-full shadow-sm">
              <Clock size={13} />
              {workingHours}
            </span>
          )}
        </div>

        {/* Directions */}
        {business.directions && (
          <div className="mt-5 p-4 bg-white rounded-2xl shadow-sm animate-fade-in-delay-1">
            <div className="flex items-center gap-2 mb-2">
              <Navigation size={15} className="text-apple-blue" />
              <h3 className="text-sm font-semibold text-apple-text">
                Как добраться
              </h3>
            </div>
            <p className="text-sm text-apple-gray whitespace-pre-line leading-relaxed">
              {linkifyText(business.directions)}
            </p>
          </div>
        )}
      </div>

      {/* Employees / Rooms */}
      {business.employees && business.employees.length > 0 && (
        <section className="mb-8 animate-fade-in-delay-3">
          <h2 className="text-lg font-bold text-apple-text mb-3 flex items-center gap-2">
            {business.business_type === 'venue_rental' ? (
              <DoorOpen size={18} className="text-apple-blue" />
            ) : (
              <User size={18} className="text-apple-blue" />
            )}
            {business.business_type === 'venue_rental' ? 'Залы' : 'Специалисты'}
          </h2>
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3">
            {business.employees.map((emp) => {
              const photoIds = parsePhotos(emp.photos)
              const cover = photoIds[0]
              return (
                <button
                  key={emp.id}
                  type="button"
                  onClick={() => setSelectedEmp(emp)}
                  className="group bg-white rounded-2xl shadow-sm p-3 text-center hover:shadow-md transition-all duration-200 active:scale-[0.98] focus:outline-none focus:ring-2 focus:ring-apple-blue/40"
                >
                  <div className="w-16 h-16 bg-apple-bg rounded-full flex items-center justify-center mx-auto mb-2 overflow-hidden">
                    {cover ? (
                      <img
                        src={`/api/telegram-photo/${encodeURIComponent(cover)}`}
                        alt={emp.name}
                        className="w-full h-full object-cover"
                        loading="lazy"
                      />
                    ) : business.business_type === 'venue_rental' ? (
                      <DoorOpen size={22} className="text-apple-gray" />
                    ) : (
                      <User size={22} className="text-apple-gray" />
                    )}
                  </div>
                  <h3 className="font-semibold text-apple-text text-sm leading-tight">
                    {emp.name}
                  </h3>
                  {emp.specialization && (
                    <p className="text-[12px] text-apple-gray mt-0.5 line-clamp-2">
                      {emp.specialization}
                    </p>
                  )}
                  <span className="block text-[11px] text-apple-blue mt-1 opacity-0 group-hover:opacity-100 transition-opacity">
                    Подробнее →
                  </span>
                </button>
              )
            })}
          </div>
        </section>
      )}

      {/* Employee / Room detail modal */}
      {selectedEmp && (
        <div
          className="fixed inset-0 bg-black/50 backdrop-blur-sm z-[60] flex items-end sm:items-center justify-center px-3 pt-3 pb-[calc(4.5rem+env(safe-area-inset-bottom))] sm:p-4 animate-fade-in"
          onClick={() => setSelectedEmp(null)}
        >
          <div
            className="bg-white rounded-3xl shadow-xl w-full max-w-md max-h-[calc(100vh-6rem)] sm:max-h-[90vh] overflow-y-auto"
            onClick={(e) => e.stopPropagation()}
          >
            {(() => {
              const photoIds = parsePhotos(selectedEmp.photos)
              return (
                <>
                  {photoIds.length > 0 ? (
                    <div className="relative">
                      <div className="flex overflow-x-auto snap-x snap-mandatory scrollbar-hide rounded-t-3xl">
                        {photoIds.map((fid, idx) => (
                          <img
                            key={idx}
                            src={`/api/telegram-photo/${encodeURIComponent(fid)}`}
                            alt={`${selectedEmp.name} ${idx + 1}`}
                            className="w-full h-64 object-cover snap-start shrink-0"
                          />
                        ))}
                      </div>
                      <button
                        type="button"
                        onClick={() => setSelectedEmp(null)}
                        aria-label="Закрыть"
                        className="absolute top-3 right-3 w-9 h-9 rounded-full bg-black/40 backdrop-blur text-white flex items-center justify-center"
                      >
                        <X size={18} />
                      </button>
                      {photoIds.length > 1 && (
                        <div className="absolute bottom-2 left-0 right-0 flex justify-center gap-1.5 pointer-events-none">
                          {photoIds.map((_, idx) => (
                            <span key={idx} className="w-1.5 h-1.5 rounded-full bg-white/80" />
                          ))}
                        </div>
                      )}
                    </div>
                  ) : (
                    <div className="relative h-32 bg-apple-bg flex items-center justify-center rounded-t-3xl">
                      {business.business_type === 'venue_rental' ? (
                        <DoorOpen size={48} className="text-apple-gray" />
                      ) : (
                        <User size={48} className="text-apple-gray" />
                      )}
                      <button
                        type="button"
                        onClick={() => setSelectedEmp(null)}
                        aria-label="Закрыть"
                        className="absolute top-3 right-3 w-9 h-9 rounded-full bg-white shadow text-apple-gray flex items-center justify-center"
                      >
                        <X size={18} />
                      </button>
                    </div>
                  )}

                  <div className="p-5">
                    <h2 className="text-xl font-bold text-apple-text">
                      {selectedEmp.name}
                    </h2>
                    {selectedEmp.specialization && (
                      <p className="text-sm text-apple-gray mt-1">
                        {selectedEmp.specialization}
                      </p>
                    )}

                    {(selectedEmp.capacity != null || selectedEmp.area_sqm != null) && (
                      <div className="flex flex-wrap gap-2 mt-3">
                        {selectedEmp.capacity != null && (
                          <span className="inline-flex items-center gap-1 text-xs px-3 py-1.5 rounded-full bg-apple-blue/5 text-apple-blue">
                            <UsersIcon size={12} />
                            до {selectedEmp.capacity} чел.
                          </span>
                        )}
                        {selectedEmp.area_sqm != null && (
                          <span className="inline-flex items-center gap-1 text-xs px-3 py-1.5 rounded-full bg-apple-blue/5 text-apple-blue">
                            <MapPin size={12} />
                            {selectedEmp.area_sqm} м²
                          </span>
                        )}
                      </div>
                    )}

                    {selectedEmp.description && (
                      <p className="text-sm text-apple-text/80 mt-4 whitespace-pre-line leading-relaxed">
                        {linkifyText(selectedEmp.description)}
                      </p>
                    )}

                    <Link
                      to={`/book/${business.id}`}
                      onClick={() => setSelectedEmp(null)}
                      className="block w-full text-center bg-apple-blue text-white font-semibold py-3.5 rounded-2xl hover:bg-apple-blue-hover transition-all duration-200 mt-5 shadow-lg shadow-apple-blue/20 active:scale-[0.98]"
                    >
                      Записаться
                    </Link>
                  </div>
                </>
              )
            })()}
          </div>
        </div>
      )}

      {/* Sticky book button */}
      <div className="fixed bottom-16 md:bottom-0 left-0 right-0 p-4 pb-[max(1rem,calc(env(safe-area-inset-bottom)+4rem))] md:pb-4 bg-gradient-to-t from-apple-bg via-apple-bg/95 to-transparent md:relative md:from-transparent md:via-transparent md:bg-transparent md:p-0">
        <Link
          to={`/book/${business.id}`}
          className="block w-full max-w-md mx-auto bg-apple-blue text-white text-center font-semibold py-4 rounded-2xl hover:bg-apple-blue-hover transition-all duration-200 shadow-lg shadow-apple-blue/20 active:scale-[0.98]"
        >
          Записаться
        </Link>
      </div>
    </div>
  )
}

