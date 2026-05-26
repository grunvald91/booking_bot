import { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'
import { MapPin, Clock, ChevronRight, Briefcase } from 'lucide-react'
import { api, type Business } from '../../api/client'

const gradients = [
  'from-blue-500 to-indigo-600',
  'from-violet-500 to-purple-600',
  'from-emerald-500 to-teal-600',
  'from-orange-500 to-rose-500',
  'from-cyan-500 to-blue-600',
  'from-pink-500 to-rose-600',
]

function formatWorkingHours(biz: Business) {
  if (biz.working_hours) return biz.working_hours
  if (biz.working_hours_start && biz.working_hours_end) {
    const fmt = (t: string) => t.substring(0, 5)
    return `${fmt(biz.working_hours_start)} — ${fmt(biz.working_hours_end)}`
  }
  return null
}

function SkeletonCard() {
  return (
    <div className="bg-white rounded-3xl shadow-sm overflow-hidden">
      <div className="h-36 skeleton rounded-none" />
      <div className="p-5 space-y-3">
        <div className="h-5 w-3/4 skeleton" />
        <div className="h-4 w-full skeleton" />
        <div className="h-4 w-1/2 skeleton" />
      </div>
    </div>
  )
}

export function HomePage() {
  const [businesses, setBusinesses] = useState<Business[]>([])
  const [loading, setLoading] = useState(true)
  const [failedPhotos, setFailedPhotos] = useState<Set<number>>(new Set())

  useEffect(() => {
    api
      .getBusinesses()
      .then(setBusinesses)
      .catch(() => setBusinesses([]))
      .finally(() => setLoading(false))
  }, [])

  return (
    <div className="pb-20 md:pb-0">
      {/* Hero section */}
      <div className="text-center py-8 md:py-14 animate-fade-in">
        <h1 className="text-3xl md:text-5xl font-extrabold text-apple-text tracking-tight leading-tight">
          Онлайн-запись
          <br />
          <span className="text-apple-blue">на услуги</span>
        </h1>
        <p className="text-apple-gray mt-3 text-base md:text-lg max-w-md mx-auto leading-relaxed">
          Выберите салон и запишитесь на удобное время
        </p>
      </div>

      {/* Business cards */}
      {loading ? (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
          {[1, 2, 3].map((i) => (
            <SkeletonCard key={i} />
          ))}
        </div>
      ) : businesses.length === 0 ? (
        <div className="text-center py-20 animate-fade-in">
          <div className="w-20 h-20 bg-white rounded-3xl flex items-center justify-center mx-auto mb-5 shadow-sm">
            <Briefcase size={32} className="text-apple-gray" />
          </div>
          <h2 className="text-xl font-bold text-apple-text mb-2">
            Пока нет доступных салонов
          </h2>
          <p className="text-apple-gray text-sm">
            Скоро здесь появятся салоны для записи
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
          {businesses.map((biz, idx) => {
            const hours = formatWorkingHours(biz)
            return (
              <Link
                key={biz.id}
                to={`/business/${biz.id}`}
                className="group bg-white rounded-3xl shadow-sm overflow-hidden hover:shadow-lg transition-all duration-300 press-scale animate-slide-in"
                style={{ animationDelay: `${idx * 0.06}s` }}
              >
                {/* Photo or gradient header */}
                {(() => {
                  let photoIds: string[] = []
                  try {
                    if (biz.photos) photoIds = JSON.parse(biz.photos)
                  } catch {}
                  const hasPhoto = photoIds.length > 0 && !failedPhotos.has(biz.id)
                  const gradient = `bg-gradient-to-br ${gradients[idx % gradients.length]}`
                  return (
                    <div
                      className={`h-32 md:h-36 relative overflow-hidden ${hasPhoto ? 'bg-gray-100' : gradient}`}
                    >
                      {hasPhoto ? (
                        <img
                          src={`/api/telegram-photo/${encodeURIComponent(photoIds[0])}`}
                          alt={biz.name}
                          className="w-full h-full object-cover"
                          loading="lazy"
                          onError={() => {
                            setFailedPhotos(prev => new Set(prev).add(biz.id))
                          }}
                        />
                      ) : (
                        <>
                          <div className="absolute inset-0 bg-black/5" />
                          <div className="absolute bottom-4 left-5">
                            <span className="text-white text-4xl font-extrabold opacity-30">
                              {biz.name.charAt(0)}
                            </span>
                          </div>
                        </>
                      )}
                      {biz.services_count != null && biz.services_count > 0 && (
                        <div className="absolute top-4 right-4 bg-white/20 backdrop-blur-md text-white text-xs font-semibold px-3 py-1.5 rounded-full">
                          {biz.services_count}{' '}
                          {biz.services_count === 1
                            ? 'услуга'
                            : biz.services_count < 5
                              ? 'услуги'
                              : 'услуг'}
                        </div>
                      )}
                    </div>
                  )
                })()}

                <div className="p-5">
                  <div className="flex items-start justify-between gap-2">
                    <h3 className="text-lg font-bold text-apple-text group-hover:text-apple-blue transition-colors duration-200 leading-snug">
                      {biz.name}
                    </h3>
                    <ChevronRight
                      size={20}
                      className="text-apple-gray/40 mt-0.5 shrink-0 group-hover:text-apple-blue group-hover:translate-x-0.5 transition-all duration-200"
                    />
                  </div>

                  {biz.description && (
                    <p className="text-sm text-apple-gray mt-1.5 line-clamp-2 leading-relaxed">
                      {biz.description}
                    </p>
                  )}

                  <div className="mt-4 flex flex-wrap gap-x-4 gap-y-1.5">
                    {biz.address && (
                      <div className="flex items-center gap-1.5 text-[13px] text-apple-gray">
                        <MapPin size={13} className="shrink-0" />
                        <span className="truncate">{biz.address}</span>
                      </div>
                    )}
                    {hours && (
                      <div className="flex items-center gap-1.5 text-[13px] text-apple-gray">
                        <Clock size={13} className="shrink-0" />
                        <span>{hours}</span>
                      </div>
                    )}
                  </div>
                </div>
              </Link>
            )
          })}
        </div>
      )}
    </div>
  )
}
