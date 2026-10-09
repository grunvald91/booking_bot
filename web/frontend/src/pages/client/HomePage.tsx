import { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'
import { MapPin, Clock, ChevronRight, Briefcase } from 'lucide-react'
import { api, type Business } from '../../api/client'
import { ClientShell } from '../../components/ClientShell'
import { NotificationSetup } from '../../components/NotificationSetup'

const gradients = [
  'linear-gradient(135deg, #3b82f6, #4f46e5)',
  'linear-gradient(135deg, #8b5cf6, #9333ea)',
  'linear-gradient(135deg, #10b981, #0d9488)',
  'linear-gradient(135deg, #f97316, #f43f5e)',
  'linear-gradient(135deg, #06b6d4, #2563eb)',
  'linear-gradient(135deg, #ec4899, #e11d48)',
]

const nichePresentations = [
  { label: 'Бани и сауны', href: 'https://promo.servgo.ru/banya' },
  { label: 'Барбершопы', href: 'https://promo.servgo.ru/barbershop' },
  { label: 'Салоны красоты', href: 'https://promo.servgo.ru/beauty' },
  { label: 'Маникюр и ногтевые студии', href: 'https://promo.servgo.ru/manicure' },
  { label: 'Аренда залов и фотостудий', href: 'https://promo.servgo.ru/hall-rental' },
  { label: 'Психологи и коучи', href: 'https://promo.servgo.ru/psy' },
  { label: 'Шиномонтаж', href: 'https://promo.servgo.ru/shinomontazh' },
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
    <div className="ds-card" style={{ overflow: 'hidden' }}>
      <div className="skeleton" style={{ height: 136, borderRadius: 0 }} />
      <div style={{ padding: 16, display: 'flex', flexDirection: 'column', gap: 10 }}>
        <div className="skeleton" style={{ height: 18, width: '75%' }} />
        <div className="skeleton" style={{ height: 14, width: '100%' }} />
        <div className="skeleton" style={{ height: 14, width: '50%' }} />
      </div>
    </div>
  )
}

export function HomePage() {
  const [businesses, setBusinesses] = useState<Business[]>([])
  const [loading, setLoading] = useState(true)
  const [failedPhotos, setFailedPhotos] = useState<Set<number>>(new Set())
  const isAuthenticated = Boolean(localStorage.getItem('token'))

  useEffect(() => {
    api
      .getBusinesses()
      .then(setBusinesses)
      .catch(() => setBusinesses([]))
      .finally(() => setLoading(false))
  }, [])

  return (
    <ClientShell>
      {/* Hero section */}
      <div style={{ textAlign: 'center', padding: '28px 0' }}>
        <h1 className="ds-h1" style={{ fontSize: 26 }}>
          Онлайн-запись
          <br />
          <span className="ds-accent">на услуги</span>
        </h1>
        <p className="ds-sub" style={{ marginTop: 8, maxWidth: 340, marginLeft: 'auto', marginRight: 'auto' }}>
          Выберите компанию, услугу и свободное время без звонка
        </p>
      </div>

      {isAuthenticated && (
        <details className="ds-card" style={{ marginBottom: 14, padding: 14 }}>
          <summary className="ds-text" style={{ cursor: 'pointer', fontWeight: 700 }}>
            Системные уведомления ServGo
          </summary>
          <p className="ds-sub" style={{ marginTop: 8, lineHeight: 1.5 }}>
            Включите их на этом устройстве, чтобы получать напоминания о записях. Это подходит и клиентам, и сотрудникам.
          </p>
          <NotificationSetup />
        </details>
      )}

      {/* Business cards */}
      {loading ? (
        <div style={{ display: 'grid', gridTemplateColumns: '1fr', gap: 14 }}>
          {[1, 2, 3].map((i) => (
            <SkeletonCard key={i} />
          ))}
        </div>
      ) : businesses.length === 0 ? (
        <div style={{ textAlign: 'center', padding: '60px 0' }}>
          <div
            className="ds-card"
            style={{
              width: 72, height: 72, borderRadius: 20,
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              margin: '0 auto 18px',
            }}
          >
            <Briefcase size={30} style={{ color: 'var(--s-muted)' }} />
          </div>
          <h2 className="ds-h2" style={{ marginBottom: 6 }}>Пока нет доступных компаний</h2>
          <p className="ds-hint" style={{ margin: 0 }}>Скоро здесь появятся компании для онлайн-записи</p>
        </div>
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: '1fr', gap: 14 }}>
          {businesses.map((biz) => {
            const hours = formatWorkingHours(biz)
            let photoIds: string[] = []
            try {
              if (biz.photos) photoIds = JSON.parse(biz.photos)
            } catch {}
            const hasPhoto = photoIds.length > 0 && !failedPhotos.has(biz.id)

            return (
              <Link
                key={biz.id}
                to={`/business/${biz.id}`}
                className="ds-card"
                style={{ overflow: 'hidden', display: 'block', textDecoration: 'none', color: 'inherit' }}
              >
                {/* Photo or gradient header */}
                <div
                  style={{
                    height: 136, position: 'relative', overflow: 'hidden',
                    background: hasPhoto ? 'var(--s-surface-2)' : gradients[biz.id % gradients.length],
                  }}
                >
                  {hasPhoto ? (
                    <img
                      src={`/api/telegram-photo/${encodeURIComponent(photoIds[0])}`}
                      alt={biz.name}
                      style={{ width: '100%', height: '100%', objectFit: 'cover' }}
                      loading="lazy"
                      onError={() => {
                        setFailedPhotos((prev) => new Set(prev).add(biz.id))
                      }}
                    />
                  ) : (
                    <div style={{ position: 'absolute', bottom: 16, left: 20 }}>
                      <span style={{ color: '#fff', fontSize: 36, fontWeight: 800, opacity: 0.3 }}>
                        {biz.name.charAt(0)}
                      </span>
                    </div>
                  )}
                  {biz.services_count != null && biz.services_count > 0 && (
                    <div
                      style={{
                        position: 'absolute', top: 14, right: 14,
                        background: 'rgba(255,255,255,0.2)', backdropFilter: 'blur(8px)',
                        color: '#fff', fontSize: 11, fontWeight: 650,
                        padding: '6px 12px', borderRadius: 999,
                      }}
                    >
                      {biz.services_count}{' '}
                      {biz.services_count === 1
                        ? 'услуга'
                        : biz.services_count < 5
                          ? 'услуги'
                          : 'услуг'}
                    </div>
                  )}
                </div>

                <div style={{ padding: 16 }}>
                  <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 8 }}>
                    <h3 className="ds-h2">{biz.name}</h3>
                    <ChevronRight size={20} style={{ color: 'var(--s-muted-2)', marginTop: 2, flexShrink: 0 }} />
                  </div>

                  {biz.description && (
                    <p
                      className="ds-sub"
                      style={{
                        marginTop: 6, display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical',
                        overflow: 'hidden',
                      }}
                    >
                      {biz.description}
                    </p>
                  )}

                  <div style={{ marginTop: 14, display: 'flex', flexWrap: 'wrap', columnGap: 16, rowGap: 6 }}>
                    {biz.address && (
                      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }} className="ds-caption">
                        <MapPin size={13} style={{ flexShrink: 0 }} />
                        <span style={{ whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{biz.address}</span>
                      </div>
                    )}
                    {hours && (
                      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }} className="ds-caption">
                        <Clock size={13} style={{ flexShrink: 0 }} />
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
      <footer
        style={{
          marginTop: 36,
          padding: '24px 18px',
          borderRadius: 22,
          background: 'var(--color-servgo-navy)',
          color: '#fff',
        }}
      >
        <p style={{ margin: 0, fontSize: 12, fontWeight: 700, opacity: 0.62, textTransform: 'uppercase', letterSpacing: '0.06em' }}>
          ServGo для бизнеса
        </p>
        <h2 style={{ margin: '8px 0 14px', fontSize: 20, lineHeight: 1.2, fontWeight: 800 }}>
          Онлайн-запись для вашего бизнеса
        </h2>

        <nav
          aria-label="Презентации ServGo по нишам"
          style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}
        >
          {nichePresentations.map((item) => (
            <a
              key={item.href}
              href={item.href}
              target="_blank"
              rel="noopener noreferrer"
              style={{
                color: '#fff',
                textDecoration: 'none',
                fontSize: 12,
                fontWeight: 650,
                lineHeight: 1.3,
                padding: '8px 10px',
                borderRadius: 10,
                border: '1px solid rgba(255,255,255,0.18)',
                background: 'rgba(255,255,255,0.07)',
              }}
            >
              {item.label}
            </a>
          ))}
        </nav>

        <div
          style={{
            marginTop: 20,
            paddingTop: 18,
            borderTop: '1px solid rgba(255,255,255,0.14)',
            display: 'flex',
            flexDirection: 'column',
            gap: 8,
          }}
        >
          <span style={{ fontSize: 12, fontWeight: 700, opacity: 0.62 }}>Связаться</span>
          <a href="mailto:grunvaldlab@gmail.com" style={{ color: '#fff', fontSize: 14, fontWeight: 700, textDecoration: 'none' }}>
            grunvaldlab@gmail.com
          </a>
          <a href="tel:+79023911399" style={{ color: '#fff', fontSize: 14, fontWeight: 700, textDecoration: 'none' }}>
            8 902 391-13-99
          </a>
        </div>
      </footer>

    </ClientShell>
  )
}
