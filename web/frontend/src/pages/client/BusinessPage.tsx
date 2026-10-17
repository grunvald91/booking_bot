import { useState, useEffect } from 'react'
import { useParams, Link } from 'react-router-dom'
import {
  MapPin,
  Phone,
  Clock,
  Navigation,
  DoorOpen,
  Users as UsersIcon,
  X,
} from 'lucide-react'
import { api, type BusinessDetail, type EmployeeWithPricing } from '../../api/client'
import { ClientShell } from '../../components/ClientShell'

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
        <a key={i} href={href} target="_blank" rel="noopener noreferrer" className="ds-accent" style={{ textDecoration: 'underline' }}>
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
      <ClientShell backTo="/" title="Загрузка…">
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10, marginTop: 12 }}>
          <div className="skeleton" style={{ height: 20, width: '60%', borderRadius: 8 }} />
          <div className="skeleton" style={{ height: 14, width: '40%', borderRadius: 8 }} />
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10, marginTop: 12 }}>
            {[1, 2, 3].map((i) => (
              <div key={i} className="skeleton" style={{ height: 72, borderRadius: 14 }} />
            ))}
          </div>
        </div>
      </ClientShell>
    )
  }

  if (error || !business) {
    return (
      <ClientShell backTo="/" title="Бизнес не найден">
        <div style={{ textAlign: 'center', padding: '48px 0' }}>
          <div style={{
            width: 64, height: 64, borderRadius: 20, background: 'var(--s-surface)',
            border: '1px solid var(--s-line)', display: 'flex', alignItems: 'center',
            justifyContent: 'center', margin: '0 auto 16px',
          }}>
            <MapPin size={28} style={{ color: 'var(--s-muted)' }} />
          </div>
          <p className="ds-sub" style={{ fontSize: 15 }}>Бизнес не найден</p>
          <Link to="/" className="ds-accent" style={{ marginTop: 12, display: 'inline-block', fontSize: 13, fontWeight: 650 }}>
            На главную
          </Link>
        </div>
      </ClientShell>
    )
  }

  const workingHours =
    business.working_hours ||
    formatWorkingHours(business.working_hours_start, business.working_hours_end)

  return (
    <ClientShell backTo="/" title={business.name}>
      {/* Info block: description, address, phone, hours, directions */}
      <div style={{ marginTop: 12, marginBottom: 20 }}>
        {business.description && (
          <p className="ds-sub" style={{ whiteSpace: 'pre-line', lineHeight: 1.5 }}>
            {linkifyText(business.description)}
          </p>
        )}

        {/* Info pills */}
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginTop: 12 }}>
          {business.address && (
            <a
              href={`https://yandex.ru/maps/?text=${encodeURIComponent(business.address)}`}
              target="_blank"
              rel="noopener noreferrer"
              className="ds-chip"
              style={{ color: 'var(--s-accent)' }}
            >
              <MapPin size={13} />
              {business.address}
            </a>
          )}
          {business.phone && (
            <a href={`tel:${business.phone}`} className="ds-chip" style={{ color: 'var(--s-accent)' }}>
              <Phone size={13} />
              {business.phone}
            </a>
          )}
          {workingHours && (
            <span className="ds-chip">
              <Clock size={13} />
              {workingHours}
            </span>
          )}
        </div>

        {/* Directions */}
        {business.directions && (
          <div className="ds-card" style={{ padding: 14, marginTop: 14 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 7, marginBottom: 7 }}>
              <Navigation size={15} className="ds-accent" />
              <h3 className="ds-h3">Как добраться</h3>
            </div>
            <p className="ds-sub" style={{ whiteSpace: 'pre-line', lineHeight: 1.5 }}>
              {linkifyText(business.directions)}
            </p>
          </div>
        )}
      </div>

      {/* Employees / Rooms */}
      {business.employees && business.employees.length > 0 && (
        <section style={{ marginBottom: 24 }}>
          <h2 className="ds-h2" style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
            {business.business_type === 'venue_rental' ? (
              <DoorOpen size={18} className="ds-accent" />
            ) : (
              <UsersIcon size={18} className="ds-accent" />
            )}
            {business.business_type === 'venue_rental' ? 'Залы' : 'Специалисты'}
          </h2>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 10 }}>
            {business.employees.map((emp) => {
              const photoIds = parsePhotos(emp.photos)
              const cover = photoIds[0]
              return (
                <button
                  key={emp.id}
                  type="button"
                  onClick={() => setSelectedEmp(emp)}
                  className="ds-card"
                  style={{
                    padding: 12, textAlign: 'center', cursor: 'pointer',
                    border: '1px solid var(--s-line)', font: 'inherit', color: 'inherit',
                  }}
                >
                  <div style={{
                    width: 60, height: 60, borderRadius: '50%', background: 'var(--s-surface-2)',
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                    margin: '0 auto 8px', overflow: 'hidden',
                  }}>
                    {cover ? (
                      <img
                        src={`/api/telegram-photo/${encodeURIComponent(cover)}`}
                        alt={emp.name}
                        style={{ width: '100%', height: '100%', objectFit: 'cover' }}
                        loading="lazy"
                      />
                    ) : business.business_type === 'venue_rental' ? (
                      <DoorOpen size={22} style={{ color: 'var(--s-muted)' }} />
                    ) : (
                      <UsersIcon size={22} style={{ color: 'var(--s-muted)' }} />
                    )}
                  </div>
                  <h3 className="ds-h3" style={{ fontSize: 13, lineHeight: 1.2, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                    {emp.name}
                  </h3>
                  {emp.specialization && (
                    <p className="ds-caption" style={{ marginTop: 3, display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', overflow: 'hidden' }}>
                      {emp.specialization}
                    </p>
                  )}
                </button>
              )
            })}
          </div>
        </section>
      )}

      {/* Employee / Room detail sheet */}
      {selectedEmp && (
        <div className="ds-sheet-ov" onClick={() => setSelectedEmp(null)}>
          <div className="ds-sheet" style={{ padding: 0 }} onClick={(e) => e.stopPropagation()}>
            {(() => {
              const photoIds = parsePhotos(selectedEmp.photos)
              return (
                <>
                  {photoIds.length > 0 ? (
                    <div style={{ position: 'relative' }}>
                      <div className="ds-sheet-grip" style={{ position: 'absolute', top: 10, left: '50%', transform: 'translateX(-50%)', zIndex: 1, background: 'rgba(255,255,255,0.7)' }} />
                      <div style={{ display: 'flex', overflowX: 'auto', scrollSnapType: 'x mandatory', borderRadius: 'var(--r-xl) var(--r-xl) 0 0' }}>
                        {photoIds.map((fid, idx) => (
                          <img
                            key={idx}
                            src={`/api/telegram-photo/${encodeURIComponent(fid)}`}
                            alt={`${selectedEmp.name} ${idx + 1}`}
                            style={{ width: '100%', height: 256, objectFit: 'cover', scrollSnapAlign: 'start', flexShrink: 0 }}
                          />
                        ))}
                      </div>
                      <button
                        type="button"
                        onClick={() => setSelectedEmp(null)}
                        aria-label="Закрыть"
                        className="ds-icon-btn"
                        style={{ position: 'absolute', top: 12, right: 12, background: 'rgba(4,9,16,0.45)', color: '#fff' }}
                      >
                        <X size={18} />
                      </button>
                      {photoIds.length > 1 && (
                        <div style={{ position: 'absolute', bottom: 8, left: 0, right: 0, display: 'flex', justifyContent: 'center', gap: 6, pointerEvents: 'none' }}>
                          {photoIds.map((_, idx) => (
                            <span key={idx} style={{ width: 6, height: 6, borderRadius: '50%', background: 'rgba(255,255,255,0.8)' }} />
                          ))}
                        </div>
                      )}
                    </div>
                  ) : (
                    <div style={{
                      position: 'relative', height: 128, background: 'var(--s-surface-2)',
                      display: 'flex', alignItems: 'center', justifyContent: 'center',
                      borderRadius: 'var(--r-xl) var(--r-xl) 0 0',
                    }}>
                      <div className="ds-sheet-grip" style={{ position: 'absolute', top: 10, left: '50%', transform: 'translateX(-50%)' }} />
                      {business.business_type === 'venue_rental' ? (
                        <DoorOpen size={44} style={{ color: 'var(--s-muted)' }} />
                      ) : (
                        <UsersIcon size={44} style={{ color: 'var(--s-muted)' }} />
                      )}
                      <button
                        type="button"
                        onClick={() => setSelectedEmp(null)}
                        aria-label="Закрыть"
                        className="ds-icon-btn bordered"
                        style={{ position: 'absolute', top: 12, right: 12 }}
                      >
                        <X size={18} />
                      </button>
                    </div>
                  )}

                  <div style={{ padding: '16px 18px calc(20px + env(safe-area-inset-bottom, 0px))' }}>
                    <h2 className="ds-h1">{selectedEmp.name}</h2>
                    {selectedEmp.specialization && (
                      <p className="ds-sub" style={{ marginTop: 4 }}>{selectedEmp.specialization}</p>
                    )}

                    {(selectedEmp.capacity != null || selectedEmp.area_sqm != null) && (
                      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginTop: 10 }}>
                        {selectedEmp.capacity != null && (
                          <span className="ds-chip" style={{ color: 'var(--s-accent)' }}>
                            <UsersIcon size={12} />
                            до {selectedEmp.capacity} чел.
                          </span>
                        )}
                        {selectedEmp.area_sqm != null && (
                          <span className="ds-chip" style={{ color: 'var(--s-accent)' }}>
                            <MapPin size={12} />
                            {selectedEmp.area_sqm} м²
                          </span>
                        )}
                      </div>
                    )}

                    {selectedEmp.description && (
                      <p className="ds-sub" style={{ marginTop: 14, whiteSpace: 'pre-line', lineHeight: 1.5 }}>
                        {linkifyText(selectedEmp.description)}
                      </p>
                    )}

                    <Link
                      to={`/book/${business.id}?employee=${selectedEmp.id}`}
                      onClick={() => setSelectedEmp(null)}
                      className="ds-btn ds-btn--primary ds-btn--block"
                      style={{ marginTop: 18 }}
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

      {/* Book button — sticky внизу скролл-контейнера, всегда на виду */}
      <div
        style={{
          position: 'sticky', bottom: 0, marginTop: 24, paddingTop: 12, paddingBottom: 4,
          background: 'linear-gradient(to top, var(--s-bg) 60%, transparent)',
        }}
      >
        <Link to={`/book/${business.id}`} className="ds-btn ds-btn--primary ds-btn--block">
          Записаться
        </Link>
        <Link to={`/chat?business_id=${business.id}`} className="ds-btn ds-btn--ghost ds-btn--block" style={{ marginTop: 8 }}>
          Помочь выбрать услугу
        </Link>
      </div>
    </ClientShell>
  )
}
