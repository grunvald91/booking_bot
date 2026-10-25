import { useCallback, useEffect, useMemo, useState } from 'react'
import { Phone, ChevronLeft, ChevronRight, CalendarOff } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { api, ApiError, type MasterBooking, type MasterSchedule } from '../../api/client'
import { ClientShell } from '../../components/ClientShell'

const WINDOW_DAYS = 14

const STATUS_LABELS: Record<string, string> = {
  pending: 'Ожидает подтверждения',
  confirmed: 'Подтверждена',
  completed: 'Завершена',
  cancelled: 'Отменена',
  pending_prepayment: 'Ждёт предоплату',
  prepayment_sent: 'Предоплата отправлена',
  prepayment_confirmed: 'Предоплата подтверждена',
}

function pad(n: number) { return String(n).padStart(2, '0') }
function toKey(d: Date) { return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}` }
function fromKey(key: string) {
  const [y, m, d] = key.split('-').map(Number)
  return new Date(y, m - 1, d)
}
function addDays(key: string, days: number) {
  const d = fromKey(key)
  d.setDate(d.getDate() + days)
  return toKey(d)
}

const MONTHS = ['января', 'февраля', 'марта', 'апреля', 'мая', 'июня', 'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря']
const WEEKDAYS = ['воскресенье', 'понедельник', 'вторник', 'среда', 'четверг', 'пятница', 'суббота']

function dayTitle(key: string, today: string) {
  const d = fromKey(key)
  const base = `${d.getDate()} ${MONTHS[d.getMonth()]}, ${WEEKDAYS[d.getDay()]}`
  if (key === today) return `Сегодня · ${base}`
  if (key === addDays(today, 1)) return `Завтра · ${base}`
  return base
}

function shortDate(key: string) {
  const d = fromKey(key)
  return `${d.getDate()} ${MONTHS[d.getMonth()]}`
}

function phoneHref(phone: string) {
  return `tel:${phone.replace(/[^\d+]/g, '')}`
}

/** Личное расписание мастера: только его записи, без цен, аналитики и настроек. */
export function MasterPage() {
  const navigate = useNavigate()
  const today = useMemo(() => toKey(new Date()), [])
  const [from, setFrom] = useState(today)
  const [data, setData] = useState<MasterSchedule | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)

  const load = useCallback(async (start: string) => {
    setLoading(true)
    setError('')
    try {
      setData(await api.masterSchedule(start, addDays(start, WINDOW_DAYS - 1)))
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) { navigate('/login', { replace: true }); return }
      if (e instanceof ApiError && e.status === 403) { navigate('/my', { replace: true }); return }
      setError('Не удалось загрузить расписание. Проверьте интернет и попробуйте ещё раз.')
    } finally {
      setLoading(false)
    }
  }, [navigate])

  useEffect(() => { void load(from) }, [from, load])

  const days = useMemo(() => Array.from({ length: WINDOW_DAYS }, (_, i) => addDays(from, i)), [from])
  const byDay = useMemo(() => {
    const map = new Map<string, MasterBooking[]>()
    for (const b of data?.bookings || []) {
      const list = map.get(b.date) || []
      list.push(b)
      map.set(b.date, list)
    }
    return map
  }, [data])
  const offDays = useMemo(() => new Set((data?.days_off || []).map((d) => d.date)), [data])
  const businesses = new Set((data?.employees || []).map((e) => e.business_id))
  const names = (data?.employees || []).map((e) => e.employee_name).join(', ')
  const visibleDays = days.filter((d) => byDay.has(d) || offDays.has(d))

  return (
    <ClientShell
      title="Моё расписание"
      subtitle={data ? `${names}${businesses.size === 1 ? ` · ${data.employees[0].business_name}` : ''}` : undefined}
    >
      {error && (
        <div role="alert" className="ds-card" style={{ padding: 16 }}>
          <p className="ds-sub" style={{ marginBottom: 10 }}>{error}</p>
          <button className="ds-btn ds-btn--primary" onClick={() => void load(from)}>Повторить</button>
        </div>
      )}

      {loading && !data && <p className="ds-sub" role="status">Загружаем…</p>}

      {data && (
        <>
          <p className="ds-hint" style={{ marginTop: 0 }}>
            {shortDate(from)} — {shortDate(addDays(from, WINDOW_DAYS - 1))}
          </p>

          {visibleDays.length === 0 && !loading && (
            <div className="ds-card" style={{ padding: 16 }}>
              <p className="ds-text">В этом периоде записей нет.</p>
            </div>
          )}

          <div style={{ display: 'grid', gap: 16, opacity: loading ? 0.6 : 1 }}>
            {visibleDays.map((day) => (
              <section key={day} aria-label={dayTitle(day, today)}>
                <h2 className="ds-h3" style={{ marginBottom: 8 }}>{dayTitle(day, today)}</h2>
                {offDays.has(day) && (
                  <p className="ds-sub" style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 8 }}>
                    <CalendarOff size={15} /> У вас выходной
                  </p>
                )}
                <div style={{ display: 'grid', gap: 8 }}>
                  {(byDay.get(day) || []).map((b) => (
                    <article
                      key={b.id}
                      className="ds-card"
                      style={{ padding: 14, display: 'grid', gap: 6, opacity: b.status === 'cancelled' ? 0.55 : 1 }}
                    >
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', gap: 10 }}>
                        <strong style={{ fontSize: 20 }}>{b.time}</strong>
                        <span className="ds-sub">{STATUS_LABELS[b.status] || b.status}</span>
                      </div>
                      <div className="ds-text" style={{ fontWeight: 650 }}>{b.service_name}</div>
                      {(businesses.size > 1 || (data.employees.length > 1)) && (
                        <div className="ds-sub">{b.business_name}{data.employees.length > 1 ? ` · ${b.employee_name}` : ''}</div>
                      )}
                      <div className="ds-text">{b.client_name}</div>
                      {b.client_phone && (
                        <a href={phoneHref(b.client_phone)} className="ds-btn ds-btn--sm" style={{ justifySelf: 'start', gap: 6 }}>
                          <Phone size={14} /> {b.client_phone}
                        </a>
                      )}
                      {b.notes && <div className="ds-sub">Комментарий: {b.notes}</div>}
                    </article>
                  ))}
                </div>
              </section>
            ))}
          </div>

          <div style={{ display: 'flex', gap: 8, marginTop: 20, flexWrap: 'wrap' }}>
            <button className="ds-btn" onClick={() => setFrom(addDays(from, -WINDOW_DAYS))} aria-label="Раньше">
              <ChevronLeft size={16} /> Раньше
            </button>
            {from !== today && (
              <button className="ds-btn" onClick={() => setFrom(today)}>Сегодня</button>
            )}
            <button className="ds-btn ds-btn--primary" onClick={() => setFrom(addDays(from, WINDOW_DAYS))} aria-label="Позже">
              Позже <ChevronRight size={16} />
            </button>
          </div>
        </>
      )}
    </ClientShell>
  )
}
