import { useState, useEffect, useCallback, useMemo, type CSSProperties } from 'react'
import {
  ChevronLeft,
  ChevronRight,
  Plus,
  X,
  Phone,
  Clock,
  CheckCircle,
  XCircle,
  AlertCircle,
  Loader2,
  ZoomIn,
  ZoomOut,
  Search,
  Moon,
  Sun,
  ChevronDown,
  CalendarClock,
} from 'lucide-react'
import { api, type AdminBooking, type Service, type Employee } from '../../api/client'
import { useAdminBusiness } from '../../hooks/useAdminBusiness'
import { BusinessSelector } from '../../components/BusinessSelector'
import './schedule.css'

// ── Constants ──
const DAYS_SHORT = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс']
const DAY_START_H = 8
const DAY_END_H = 22
const TOTAL_MIN = (DAY_END_H - DAY_START_H) * 60

const STATUS_LABELS: Record<string, string> = {
  pending: 'Ожидает',
  confirmed: 'Подтверждено',
  completed: 'Завершено',
  cancelled: 'Отменено',
  pending_prepayment: 'Ждёт оплату',
  prepayment_sent: 'Оплата отправлена',
}

// status → CSS var suffix
const STATUS_VAR: Record<string, string> = {
  pending: 'pending',
  confirmed: 'confirmed',
  completed: 'completed',
  cancelled: 'cancelled',
  pending_prepayment: 'prepay',
  prepayment_sent: 'prepay',
}

const LEGEND_ITEMS = [
  { key: 'pending', label: 'Ожидает' },
  { key: 'confirmed', label: 'Подтверждено' },
  { key: 'completed', label: 'Завершено' },
  { key: 'cancelled', label: 'Отменено' },
  { key: 'prepay', label: 'Оплата' },
]

// ── Helpers ──
function formatDateISO(d: Date) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}
function getMonday(d: Date): Date {
  const date = new Date(d)
  const day = date.getDay()
  const diff = day === 0 ? -6 : 1 - day
  date.setDate(date.getDate() + diff)
  date.setHours(0, 0, 0, 0)
  return date
}
function formatDateShort(d: Date) {
  return d.toLocaleDateString('ru-RU', { day: 'numeric', month: 'short' })
}
function timeToMin(t: string) {
  const [h, m] = t.split(':').map(Number)
  return h * 60 + m
}
function minToTime(min: number) {
  const h = Math.floor(min / 60)
  const m = min % 60
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`
}
function calcEndTime(start: string, durationMin: number) {
  return minToTime((timeToMin(start) + durationMin) % (24 * 60))
}

type Positioned = { booking: AdminBooking; startMin: number; endMin: number; lane: number; lanes: number }

// Greedy lane assignment for overlapping intervals within a column.
function layoutColumn(bookings: AdminBooking[]): Positioned[] {
  const items = bookings
    .map((b) => {
      const startMin = timeToMin(b.time)
      const dur = b.service_duration || 60
      return { booking: b, startMin, endMin: startMin + dur }
    })
    .sort((a, b) => a.startMin - b.startMin || a.endMin - b.endMin)

  const laneEnds: number[] = []
  const placed = items.map((it) => {
    let lane = laneEnds.findIndex((e) => e <= it.startMin)
    if (lane === -1) {
      lane = laneEnds.length
      laneEnds.push(it.endMin)
    } else {
      laneEnds[lane] = it.endMin
    }
    return { ...it, lane }
  })
  const lanes = Math.max(1, laneEnds.length)
  return placed.map((p) => ({ ...p, lanes }))
}

// Max simultaneous bookings (for week "overloaded day" collapse).
function maxConcurrency(bookings: AdminBooking[]): number {
  const points = bookings
    .flatMap((b) => {
      const s = timeToMin(b.time)
      const e = s + (b.service_duration || 60)
      return [
        { t: s, d: 1 },
        { t: e, d: -1 },
      ]
    })
    .sort((a, b) => a.t - b.t || a.d - b.d)
  let cur = 0
  let max = 0
  points.forEach((p) => {
    cur += p.d
    if (cur > max) max = cur
  })
  return max
}

function statusVar(status: string) {
  return STATUS_VAR[status] || 'confirmed'
}

// ── Booking detail modal ──
function BookingDetailModal({
  booking,
  onClose,
  onStatusChange,
  onReschedule,
  updating,
}: {
  booking: AdminBooking
  onClose: () => void
  onStatusChange: (id: number, status: string) => void
  onReschedule: (b: AdminBooking) => void
  updating: boolean
}) {
  const endTime = calcEndTime(booking.time, booking.service_duration || 60)
  const sv = statusVar(booking.status)
  return (
    <div className="fixed inset-0 bg-black/40 z-50 flex items-end sm:items-center justify-center p-0 sm:p-4" onClick={onClose}>
      <div
        className="sched-root w-full sm:max-w-sm rounded-t-2xl sm:rounded-2xl p-5"
        style={{ background: 'var(--s-surface)', boxShadow: '0 -8px 30px rgba(0,0,0,.2)' }}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex justify-between items-start mb-4">
          <h3 className="text-lg font-bold" style={{ color: 'var(--s-text)' }}>{booking.client_name}</h3>
          <button onClick={onClose} className="sched-iconbtn"><X size={18} /></button>
        </div>
        <div className="space-y-2.5 mb-5 text-sm" style={{ color: 'var(--s-text)' }}>
          {booking.client_phone && (
            <div className="flex items-center gap-2">
              <Phone size={15} style={{ color: 'var(--s-muted)' }} />
              <a href={`tel:${booking.client_phone}`} style={{ color: 'var(--s-accent)' }}>{booking.client_phone}</a>
            </div>
          )}
          <div className="flex items-center gap-2">
            <Clock size={15} style={{ color: 'var(--s-muted)' }} />
            <span>{booking.time} — {endTime} ({booking.service_duration || 60} мин)</span>
          </div>
          <div><span style={{ color: 'var(--s-muted)' }}>Услуга: </span><span className="font-medium">{booking.service_name}</span>{booking.price ? ` — ${booking.price}₽` : ''}</div>
          {booking.employee_name && <div><span style={{ color: 'var(--s-muted)' }}>Специалист: </span><span className="font-medium">{booking.employee_name}</span></div>}
          {booking.notes && <div><span style={{ color: 'var(--s-muted)' }}>Комментарий: </span><span>{booking.notes}</span></div>}
          <span
            className="inline-flex items-center px-2.5 py-1 rounded-full text-xs font-semibold"
            style={{ color: `var(--st-${sv})`, background: `var(--st-${sv}-bg)` }}
          >
            {STATUS_LABELS[booking.status] || booking.status}
          </span>
        </div>
        {booking.status !== 'cancelled' && booking.status !== 'completed' && (
          <div className="grid grid-cols-2 gap-2">
            {booking.status === 'pending' && (
              <button onClick={() => onStatusChange(booking.id, 'confirmed')} disabled={updating}
                className="flex items-center justify-center gap-1.5 text-white font-semibold py-2.5 rounded-xl text-sm disabled:opacity-50"
                style={{ background: 'var(--st-confirmed)' }}>
                <CheckCircle size={16} /> Подтвердить
              </button>
            )}
            <button onClick={() => onStatusChange(booking.id, 'completed')} disabled={updating}
              className="flex items-center justify-center gap-1.5 text-white font-semibold py-2.5 rounded-xl text-sm disabled:opacity-50"
              style={{ background: 'var(--st-completed)' }}>
              <CheckCircle size={16} /> Завершить
            </button>
            <button onClick={() => onReschedule(booking)} disabled={updating}
              className="flex items-center justify-center gap-1.5 font-semibold py-2.5 rounded-xl text-sm disabled:opacity-50"
              style={{ background: 'var(--s-surface-2)', color: 'var(--s-text)' }}>
              <CalendarClock size={16} /> Перенести
            </button>
            <button onClick={() => onStatusChange(booking.id, 'cancelled')} disabled={updating}
              className="flex items-center justify-center gap-1.5 text-white font-semibold py-2.5 rounded-xl text-sm disabled:opacity-50"
              style={{ background: 'var(--st-cancelled)' }}>
              <XCircle size={16} /> Отменить
            </button>
          </div>
        )}
      </div>
    </div>
  )
}

// ── Reschedule modal ──
function RescheduleModal({
  booking,
  employees,
  onClose,
  onSubmit,
  submitting,
  error,
}: {
  booking: AdminBooking
  employees: Employee[]
  onClose: () => void
  onSubmit: (date: string, time: string, employeeId?: number) => void
  submitting: boolean
  error: string
}) {
  const [date, setDate] = useState(booking.date)
  const [time, setTime] = useState(booking.time)
  const [employeeId, setEmployeeId] = useState<number | undefined>(booking.employee_id)
  return (
    <div className="fixed inset-0 bg-black/40 z-[60] flex items-end sm:items-center justify-center p-0 sm:p-4" onClick={onClose}>
      <div className="sched-root w-full sm:max-w-sm rounded-t-2xl sm:rounded-2xl p-5" style={{ background: 'var(--s-surface)' }} onClick={(e) => e.stopPropagation()}>
        <div className="flex justify-between items-start mb-4">
          <h3 className="text-lg font-bold" style={{ color: 'var(--s-text)' }}>Перенести запись</h3>
          <button onClick={onClose} className="sched-iconbtn"><X size={18} /></button>
        </div>
        <div className="space-y-3">
          <div>
            <label className="block text-xs font-semibold mb-1" style={{ color: 'var(--s-muted)' }}>Дата</label>
            <input type="date" value={date} onChange={(e) => setDate(e.target.value)} className="sched-input w-full" />
          </div>
          <div>
            <label className="block text-xs font-semibold mb-1" style={{ color: 'var(--s-muted)' }}>Время</label>
            <input type="time" value={time} onChange={(e) => setTime(e.target.value)} className="sched-input w-full" />
          </div>
          {employees.length > 0 && (
            <div>
              <label className="block text-xs font-semibold mb-1" style={{ color: 'var(--s-muted)' }}>Специалист / Зал</label>
              <select value={employeeId ?? ''} onChange={(e) => setEmployeeId(Number(e.target.value) || undefined)} className="sched-input w-full">
                <option value="">Без изменения</option>
                {employees.map((e) => <option key={e.id} value={e.id}>{e.name}</option>)}
              </select>
            </div>
          )}
          {error && <div className="flex items-center gap-1.5 text-sm" style={{ color: 'var(--st-cancelled)' }}><AlertCircle size={14} />{error}</div>}
        </div>
        <button onClick={() => onSubmit(date, time, employeeId)} disabled={submitting}
          className="w-full mt-4 text-white font-semibold py-3 rounded-xl disabled:opacity-50 flex items-center justify-center gap-2"
          style={{ background: 'var(--s-accent)' }}>
          {submitting ? <Loader2 size={16} className="animate-spin" /> : <CalendarClock size={16} />}
          {submitting ? 'Переносим...' : 'Перенести'}
        </button>
      </div>
    </div>
  )
}

// ── Manual booking modal (kept, themed) ──
function ManualBookingModal({
  businessId, services, employees, selectedDate, selectedTime, onClose, onCreated,
}: {
  businessId: number
  services: Service[]
  employees: Employee[]
  selectedDate: Date
  selectedTime?: string
  onClose: () => void
  onCreated: () => void
}) {
  const [serviceId, setServiceId] = useState<number | null>(null)
  const [employeeId, setEmployeeId] = useState<number | null>(null)
  const [time, setTime] = useState(selectedTime || '10:00')
  const [clientName, setClientName] = useState('')
  const [clientPhone, setClientPhone] = useState('')
  const [notes, setNotes] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')

  const handleSubmit = async () => {
    if (!serviceId || !clientName) return
    setSubmitting(true)
    setError('')
    try {
      await api.createManualBooking({
        business_id: businessId,
        service_id: serviceId,
        employee_id: employeeId ?? undefined,
        date: formatDateISO(selectedDate),
        time,
        client_name: clientName,
        client_phone: clientPhone || undefined,
        notes: notes || undefined,
      })
      onCreated()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Ошибка')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/40 z-50 flex items-end sm:items-center justify-center p-0 sm:p-4" onClick={onClose}>
      <div className="sched-root w-full sm:max-w-sm rounded-t-2xl sm:rounded-2xl p-5 max-h-[90vh] overflow-y-auto" style={{ background: 'var(--s-surface)' }} onClick={(e) => e.stopPropagation()}>
        <div className="flex justify-between items-start mb-4">
          <h3 className="text-lg font-bold" style={{ color: 'var(--s-text)' }}>Записать клиента</h3>
          <button onClick={onClose} className="sched-iconbtn"><X size={18} /></button>
        </div>
        <div className="space-y-3">
          <div>
            <label className="block text-xs font-semibold mb-1" style={{ color: 'var(--s-muted)' }}>Услуга</label>
            <select value={serviceId ?? ''} onChange={(e) => setServiceId(Number(e.target.value) || null)} className="sched-input w-full">
              <option value="">Выберите услугу</option>
              {services.filter((s) => s.is_active).map((s) => (
                <option key={s.id} value={s.id}>{s.name} {s.duration_minutes ? `(${s.duration_minutes} мин)` : ''} {s.price ? `— ${s.price}₽` : ''}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-xs font-semibold mb-1" style={{ color: 'var(--s-muted)' }}>Специалист / Зал</label>
            <select value={employeeId ?? ''} onChange={(e) => setEmployeeId(Number(e.target.value) || null)} className="sched-input w-full">
              <option value="">Любой</option>
              {employees.map((e) => <option key={e.id} value={e.id}>{e.name}</option>)}
            </select>
          </div>
          <div>
            <label className="block text-xs font-semibold mb-1" style={{ color: 'var(--s-muted)' }}>Время</label>
            <input type="time" value={time} onChange={(e) => setTime(e.target.value)} className="sched-input w-full" />
          </div>
          <div>
            <label className="block text-xs font-semibold mb-1" style={{ color: 'var(--s-muted)' }}>Имя клиента</label>
            <input type="text" value={clientName} onChange={(e) => setClientName(e.target.value)} placeholder="Введите имя" className="sched-input w-full" />
          </div>
          <div>
            <label className="block text-xs font-semibold mb-1" style={{ color: 'var(--s-muted)' }}>Телефон</label>
            <input type="tel" value={clientPhone} onChange={(e) => setClientPhone(e.target.value)} placeholder="+7" className="sched-input w-full" />
          </div>
          <div>
            <label className="block text-xs font-semibold mb-1" style={{ color: 'var(--s-muted)' }}>Комментарий</label>
            <textarea value={notes} onChange={(e) => setNotes(e.target.value)} rows={2} className="sched-input w-full resize-none" />
          </div>
          {error && <div className="flex items-center gap-1.5 text-sm" style={{ color: 'var(--st-cancelled)' }}><AlertCircle size={14} />{error}</div>}
        </div>
        <button onClick={handleSubmit} disabled={submitting || !serviceId || !clientName}
          className="w-full mt-4 text-white font-semibold py-3 rounded-xl disabled:opacity-50 flex items-center justify-center gap-2" style={{ background: 'var(--s-accent)' }}>
          {submitting ? <Loader2 size={16} className="animate-spin" /> : <Plus size={16} />}
          {submitting ? 'Записываем...' : 'Записать'}
        </button>
      </div>
    </div>
  )
}

// ── Booking card ──
function BookingCard({
  p, colWidth, pxPerMin, showEmployee, onClick, onDragStart, draggable,
}: {
  p: Positioned
  colWidth: number
  pxPerMin: number
  showEmployee: boolean
  onClick: () => void
  onDragStart?: () => void
  draggable: boolean
}) {
  const b = p.booking
  const sv = statusVar(b.status)
  const top = (p.startMin - DAY_START_H * 60) * pxPerMin
  const height = Math.max(20, (p.endMin - p.startMin) * pxPerMin - 2)
  const laneW = (colWidth - 4) / p.lanes
  const left = 2 + p.lane * laneW
  const cardStyle = {
    top, height, left, width: laneW - 2,
    '--card-accent': `var(--st-${sv})`,
    '--card-bg': `var(--st-${sv}-bg)`,
  } as CSSProperties
  return (
    <div
      className={`sched-card ${b.status === 'cancelled' ? 'is-cancelled' : ''} ${b.status === 'pending' ? 'is-pending' : ''}`}
      style={cardStyle}
      draggable={draggable}
      onDragStart={onDragStart}
      onClick={(e) => { e.stopPropagation(); onClick() }}
    >
      <div className="c-name">{b.client_name}</div>
      {height > 32 && <div className="c-sub">{b.service_name}</div>}
      {height > 46 && showEmployee && b.employee_name && <div className="c-sub">{b.employee_name}</div>}
      {height > 46 && <div className="c-sub">{b.time}–{calcEndTime(b.time, b.service_duration || 60)}</div>}
    </div>
  )
}

// ── Main ──
export function SchedulePage() {
  const { businesses, selectedId: businessId, selectBusiness } = useAdminBusiness()
  const [viewMode, setViewMode] = useState<'week' | 'day'>('day')
  const [weekOffset, setWeekOffset] = useState(0)
  const [dayOffset, setDayOffset] = useState(0)
  const [bookings, setBookings] = useState<AdminBooking[]>([])
  const [loading, setLoading] = useState(false)
  const [selectedBooking, setSelectedBooking] = useState<AdminBooking | null>(null)
  const [rescheduleBooking, setRescheduleBooking] = useState<AdminBooking | null>(null)
  const [rescheduleSubmitting, setRescheduleSubmitting] = useState(false)
  const [rescheduleError, setRescheduleError] = useState('')
  const [updating, setUpdating] = useState(false)
  const [showManualBooking, setShowManualBooking] = useState(false)
  const [manualBookingTime, setManualBookingTime] = useState<string | undefined>()
  const [manualBookingDate, setManualBookingDate] = useState<Date>(new Date())
  const [services, setServices] = useState<Service[]>([])
  const [allEmployees, setAllEmployees] = useState<Employee[]>([])
  const [selectedEmployeeId, setSelectedEmployeeId] = useState<number | null>(null)
  const [pxPerMin, setPxPerMin] = useState(0.8)
  const [search, setSearch] = useState('')
  const [legendOpen, setLegendOpen] = useState(false)
  const [summaryOpen, setSummaryOpen] = useState(false)
  const [theme, setTheme] = useState<'light' | 'dark'>(() => {
    const saved = localStorage.getItem('schedTheme')
    if (saved === 'dark' || saved === 'light') return saved
    const tg = (window as unknown as { Telegram?: { WebApp?: { colorScheme?: string } } }).Telegram?.WebApp?.colorScheme
    if (tg === 'dark') return 'dark'
    return window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
  })
  const [dragId, setDragId] = useState<number | null>(null)

  useEffect(() => { localStorage.setItem('schedTheme', theme) }, [theme])

  const employees = useMemo(
    () => allEmployees.filter((e) => !e.role || e.role === 'master' || e.role === 'master_and_admin'),
    [allEmployees]
  )

  const weekDates = useMemo(() => {
    const monday = getMonday(new Date())
    monday.setDate(monday.getDate() + weekOffset * 7)
    return Array.from({ length: 7 }, (_, i) => {
      const d = new Date(monday)
      d.setDate(d.getDate() + i)
      return d
    })
  }, [weekOffset])

  const dayDate = useMemo(() => {
    const d = new Date()
    d.setDate(d.getDate() + dayOffset)
    d.setHours(0, 0, 0, 0)
    return d
  }, [dayOffset])

  const weekLabel = useMemo(() => {
    if (weekOffset === 0) return 'Эта неделя'
    if (weekOffset === 1) return 'След. неделя'
    if (weekOffset === -1) return 'Прош. неделя'
    return `${formatDateShort(weekDates[0])} — ${formatDateShort(weekDates[6])}`
  }, [weekOffset, weekDates])

  const dayLabel = useMemo(() => {
    if (dayOffset === 0) return 'Сегодня'
    if (dayOffset === 1) return 'Завтра'
    if (dayOffset === -1) return 'Вчера'
    return dayDate.toLocaleDateString('ru-RU', { day: 'numeric', month: 'short', weekday: 'short' })
  }, [dayOffset, dayDate])

  const fetchBookings = useCallback(async () => {
    if (!businessId) return
    setLoading(true)
    try {
      let params = `business_id=${businessId}`
      if (viewMode === 'week') {
        params += `&start_date=${formatDateISO(weekDates[0])}&end_date=${formatDateISO(weekDates[6])}`
      } else {
        params += `&date=${formatDateISO(dayDate)}`
      }
      const data = await api.getAdminBookings(params)
      setBookings(data)
    } catch {
      // ignore
    } finally {
      setLoading(false)
    }
  }, [businessId, viewMode, weekDates, dayDate])

  useEffect(() => { fetchBookings() }, [fetchBookings])
  useEffect(() => {
    const timer = setInterval(fetchBookings, 15000)
    return () => clearInterval(timer)
  }, [fetchBookings])

  useEffect(() => {
    if (!businessId) return
    Promise.all([api.getServices(businessId), api.getEmployees(businessId)])
      .then(([svc, emp]) => { setServices(svc); setAllEmployees(emp) })
      .catch(() => {})
  }, [businessId])

  const handleStatusChange = async (bookingId: number, status: string) => {
    setUpdating(true)
    try {
      const updated = await api.updateBookingStatus(bookingId, status)
      setBookings((prev) => prev.map((b) => (b.id === bookingId ? updated : b)))
      setSelectedBooking(null)
    } catch { /* ignore */ } finally {
      setUpdating(false)
    }
  }

  const doReschedule = async (bookingId: number, date: string, time: string, employeeId?: number, optimistic = false) => {
    const prev = bookings
    if (optimistic) {
      setBookings((bs) => bs.map((b) => (b.id === bookingId ? { ...b, date, time, employee_id: employeeId ?? b.employee_id } : b)))
    }
    try {
      const updated = await api.adminReschedule(bookingId, date, time, employeeId)
      setBookings((bs) => bs.map((b) => (b.id === bookingId ? updated : b)))
      return true
    } catch (e) {
      if (optimistic) setBookings(prev) // rollback
      throw e
    }
  }

  const submitReschedule = async (date: string, time: string, employeeId?: number) => {
    if (!rescheduleBooking) return
    setRescheduleSubmitting(true)
    setRescheduleError('')
    try {
      await doReschedule(rescheduleBooking.id, date, time, employeeId)
      setRescheduleBooking(null)
      setSelectedBooking(null)
      fetchBookings()
    } catch (e) {
      setRescheduleError(e instanceof Error ? e.message : 'Не удалось перенести')
    } finally {
      setRescheduleSubmitting(false)
    }
  }

  const openNewBooking = (date: Date, time?: string) => {
    setManualBookingDate(date)
    setManualBookingTime(time)
    setShowManualBooking(true)
  }

  // Filtering: by employee + search
  const visibleBookings = useMemo(() => {
    let list = bookings
    if (selectedEmployeeId) list = list.filter((b) => b.employee_id === selectedEmployeeId)
    const q = search.trim().toLowerCase()
    if (q) {
      list = list.filter((b) =>
        (b.client_name || '').toLowerCase().includes(q) ||
        (b.service_name || '').toLowerCase().includes(q) ||
        (b.client_phone || '').toLowerCase().includes(q)
      )
    }
    return list
  }, [bookings, selectedEmployeeId, search])

  // Summary
  const summary = useMemo(() => {
    const active = visibleBookings.filter((b) => b.status !== 'cancelled')
    const revenue = visibleBookings
      .filter((b) => b.status === 'confirmed' || b.status === 'completed')
      .reduce((sum, b) => sum + (b.price || 0), 0)
    const busyMin = active.reduce((sum, b) => sum + (b.service_duration || 60), 0)
    const cols = viewMode === 'week' ? 7 : Math.max(1, employees.length || 1)
    const load = Math.min(100, Math.round((busyMin / (TOTAL_MIN * cols)) * 100))
    return { count: active.length, revenue, load }
  }, [visibleBookings, viewMode, employees.length])

  const nowMin = useMemo(() => {
    const n = new Date()
    return n.getHours() * 60 + n.getMinutes()
  }, [bookings])

  const colHeight = TOTAL_MIN * pxPerMin
  const todayISO = formatDateISO(new Date())
  const hourMarks = Array.from({ length: DAY_END_H - DAY_START_H + 1 }, (_, i) => DAY_START_H + i)

  // Day columns = masters (or single)
  const dayColumns = useMemo(() => {
    const base = selectedEmployeeId ? employees.filter((e) => e.id === selectedEmployeeId) : employees
    return base.length > 0 ? base : [{ id: 0, name: 'Расписание' } as Employee]
  }, [employees, selectedEmployeeId])

  return (
    <div
      className="sched-root flex flex-col"
      data-theme={theme}
      style={{ height: 'calc(100dvh - 120px - env(safe-area-inset-bottom, 0px))', background: 'var(--s-bg)' }}
    >
      {/* Toolbar row 1 */}
      <div className="flex items-center justify-between gap-2 shrink-0 px-1 pt-1">
        <BusinessSelector businesses={businesses} selectedId={businessId} onSelect={selectBusiness} />
        <div className="flex items-center gap-2">
          <div className="tabs-pill shrink-0">
            <button onClick={() => setViewMode('day')} className={viewMode === 'day' ? 'tab-active' : ''}>День</button>
            <button onClick={() => setViewMode('week')} className={viewMode === 'week' ? 'tab-active' : ''}>Неделя</button>
          </div>
          <button className="sched-iconbtn" onClick={() => setTheme((t) => (t === 'dark' ? 'light' : 'dark'))} aria-label="Тема">
            {theme === 'dark' ? <Sun size={16} /> : <Moon size={16} />}
          </button>
        </div>
      </div>

      {/* Toolbar row 2: nav + zoom + search */}
      <div className="flex items-center gap-1 shrink-0 px-1 mt-1">
        <button onClick={() => (viewMode === 'week' ? setWeekOffset((w) => w - 1) : setDayOffset((d) => d - 1))} className="sched-iconbtn"><ChevronLeft size={16} /></button>
        <button onClick={() => { setWeekOffset(0); setDayOffset(0) }} className="text-xs font-semibold px-2 py-1 rounded-lg" style={{ color: 'var(--s-accent)' }}>Сегодня</button>
        <span className="text-xs font-bold flex-1 text-center truncate" style={{ color: 'var(--s-text)' }}>{viewMode === 'week' ? weekLabel : dayLabel}</span>
        <button onClick={() => (viewMode === 'week' ? setWeekOffset((w) => w + 1) : setDayOffset((d) => d + 1))} className="sched-iconbtn"><ChevronRight size={16} /></button>
        <button className="sched-iconbtn" onClick={() => setPxPerMin((z) => Math.max(0.4, +(z - 0.15).toFixed(2)))}><ZoomOut size={14} /></button>
        <button className="sched-iconbtn" onClick={() => setPxPerMin((z) => Math.min(1.8, +(z + 0.15).toFixed(2)))}><ZoomIn size={14} /></button>
      </div>

      {/* Search */}
      <div className="px-1 mt-1 shrink-0 relative">
        <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2" style={{ color: 'var(--s-muted)' }} />
        <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Поиск: клиент, услуга, телефон"
          className="sched-input w-full" style={{ paddingLeft: 30 }} />
      </div>

      {/* Legend + summary toggles */}
      <div className="px-1 mt-1 shrink-0">
        <div className="flex gap-2">
          <button className="sched-chip flex items-center gap-1" onClick={() => setLegendOpen((v) => !v)}>
            Легенда <ChevronDown size={13} style={{ transform: legendOpen ? 'rotate(180deg)' : '', transition: 'transform .15s' }} />
          </button>
          <button className="sched-chip flex items-center gap-1" onClick={() => setSummaryOpen((v) => !v)}>
            Сводка <ChevronDown size={13} style={{ transform: summaryOpen ? 'rotate(180deg)' : '', transition: 'transform .15s' }} />
          </button>
        </div>
        {legendOpen && (
          <div className="sched-legend mt-2 px-1">
            {LEGEND_ITEMS.map((it) => (
              <span className="item" key={it.key}>
                <span className="dot" style={{ background: `var(--st-${it.key})` }} />{it.label}
              </span>
            ))}
          </div>
        )}
        {summaryOpen && (
          <div className="sched-summary mt-2">
            <div className="cell"><div className="v">{summary.count}</div><div className="l">записей</div></div>
            <div className="cell"><div className="v">{summary.revenue.toLocaleString('ru-RU')}₽</div><div className="l">выручка</div></div>
            <div className="cell"><div className="v">{summary.load}%</div><div className="l">загрузка</div></div>
          </div>
        )}
      </div>

      {/* Timeline */}
      <div className="flex-1 min-h-0 overflow-auto mt-2 px-1 pb-2">
        {loading && bookings.length === 0 ? (
          <div className="flex items-center justify-center py-20" style={{ color: 'var(--s-muted)' }}>
            <Loader2 size={22} className="animate-spin mr-2" /> Загрузка...
          </div>
        ) : viewMode === 'day' ? (
          /* ── DAY ── */
          <div className="sched-grid" style={{ gridTemplateColumns: `44px repeat(${dayColumns.length}, minmax(120px, 1fr))` }}>
            {/* header row */}
            <div className="sched-colhead" style={{ position: 'sticky', left: 0, zIndex: 7 }} />
            {dayColumns.map((emp) => (
              <div key={emp.id} className="sched-colhead">{emp.name}</div>
            ))}
            {/* body row */}
            <div className="sched-axis" style={{ height: colHeight }}>
              {hourMarks.map((h) => (
                <div key={h} className="sched-axis-tick" style={{ top: (h - DAY_START_H) * 60 * pxPerMin }}>{String(h).padStart(2, '0')}:00</div>
              ))}
            </div>
            {dayColumns.map((emp) => {
              const dateStr = formatDateISO(dayDate)
              const colBookings = visibleBookings.filter((b) => b.date === dateStr && (emp.id === 0 || b.employee_id === emp.id))
              const positioned = layoutColumn(colBookings)
              const isToday = dateStr === todayISO
              return (
                <div
                  key={emp.id}
                  className={`sched-col ${dragId !== null ? 'drop-active' : ''}`}
                  style={{ height: colHeight }}
                  onClick={(e) => {
                    const rect = (e.currentTarget as HTMLElement).getBoundingClientRect()
                    const min = DAY_START_H * 60 + Math.round(((e.clientY - rect.top) / pxPerMin) / 15) * 15
                    openNewBooking(dayDate, minToTime(Math.max(DAY_START_H * 60, Math.min(DAY_END_H * 60 - 15, min))))
                  }}
                  onDragOver={(e) => { if (dragId !== null) e.preventDefault() }}
                  onDrop={(e) => {
                    if (dragId === null) return
                    e.preventDefault()
                    const rect = (e.currentTarget as HTMLElement).getBoundingClientRect()
                    const rawMin = DAY_START_H * 60 + (e.clientY - rect.top) / pxPerMin
                    const snapped = Math.round(rawMin / 5) * 5
                    const id = dragId
                    setDragId(null)
                    doReschedule(id, dateStr, minToTime(Math.max(DAY_START_H * 60, Math.min(DAY_END_H * 60 - 15, snapped))), emp.id || undefined, true).catch(() => {})
                  }}
                >
                  {hourMarks.map((h) => <div key={h} className="sched-hourline" style={{ top: (h - DAY_START_H) * 60 * pxPerMin }} />)}
                  {isToday && nowMin >= DAY_START_H * 60 && nowMin <= DAY_END_H * 60 && (
                    <div className="sched-now" style={{ top: (nowMin - DAY_START_H * 60) * pxPerMin }} />
                  )}
                  {positioned.map((p) => (
                    <BookingCard
                      key={p.booking.id}
                      p={p}
                      colWidth={Math.max(120, 300)}
                      pxPerMin={pxPerMin}
                      showEmployee={false}
                      draggable
                      onDragStart={() => setDragId(p.booking.id)}
                      onClick={() => setSelectedBooking(p.booking)}
                    />
                  ))}
                </div>
              )
            })}
          </div>
        ) : (
          /* ── WEEK ── */
          <div className="sched-grid" style={{ gridTemplateColumns: `44px repeat(7, minmax(96px, 1fr))` }}>
            <div className="sched-colhead" style={{ position: 'sticky', left: 0, zIndex: 7 }} />
            {weekDates.map((d, i) => (
              <div key={i} className={`sched-colhead ${formatDateISO(d) === todayISO ? 'is-today' : ''}`}>
                <small>{DAYS_SHORT[i]}</small>{d.getDate()}
              </div>
            ))}
            <div className="sched-axis" style={{ height: colHeight }}>
              {hourMarks.map((h) => (
                <div key={h} className="sched-axis-tick" style={{ top: (h - DAY_START_H) * 60 * pxPerMin }}>{String(h).padStart(2, '0')}</div>
              ))}
            </div>
            {weekDates.map((d, dayIdx) => {
              const dateStr = formatDateISO(d)
              const dayBookings = visibleBookings.filter((b) => b.date === dateStr)
              const overloaded = maxConcurrency(dayBookings) >= 3
              const isToday = dateStr === todayISO
              return (
                <div key={dayIdx} className="sched-col" style={{ height: colHeight }}
                  onClick={() => dayBookings.length === 0 && openNewBooking(d)}>
                  {hourMarks.map((h) => <div key={h} className="sched-hourline" style={{ top: (h - DAY_START_H) * 60 * pxPerMin }} />)}
                  {isToday && nowMin >= DAY_START_H * 60 && nowMin <= DAY_END_H * 60 && (
                    <div className="sched-now" style={{ top: (nowMin - DAY_START_H * 60) * pxPerMin }} />
                  )}
                  {overloaded ? (
                    <button
                      className="sched-more"
                      style={{ top: 4, height: colHeight - 8 }}
                      onClick={(e) => { e.stopPropagation(); setDayOffset(Math.round((d.getTime() - new Date().setHours(0, 0, 0, 0)) / 86400000)); setViewMode('day') }}
                    >
                      {dayBookings.length} записей →
                    </button>
                  ) : (
                    layoutColumn(dayBookings).map((p) => (
                      <BookingCard
                        key={p.booking.id}
                        p={p}
                        colWidth={Math.max(96, 130)}
                        pxPerMin={pxPerMin}
                        showEmployee
                        draggable={false}
                        onClick={() => setSelectedBooking(p.booking)}
                      />
                    ))
                  )}
                </div>
              )
            })}
          </div>
        )}
      </div>

      {/* Employee filter + FAB */}
      {employees.length > 0 && (
        <div className="shrink-0 border-t pt-2 pb-1" style={{ borderColor: 'var(--s-line)', background: 'var(--s-surface)' }}>
          <div className="overflow-x-auto scrollbar-hide px-2">
            <div className="flex gap-2 items-center">
              <button onClick={() => setSelectedEmployeeId(null)} className={`sched-chip ${selectedEmployeeId === null ? 'active' : ''}`}>Все</button>
              {employees.map((emp) => (
                <button key={emp.id} onClick={() => setSelectedEmployeeId(emp.id)} className={`sched-chip ${selectedEmployeeId === emp.id ? 'active' : ''}`}>{emp.name}</button>
              ))}
              {businessId && (
                <button onClick={() => openNewBooking(viewMode === 'week' ? new Date() : dayDate)}
                  className="flex-shrink-0 ml-auto w-9 h-9 rounded-full text-white shadow-md flex items-center justify-center active:scale-95 transition-transform"
                  style={{ background: 'var(--s-accent)' }} aria-label="Записать клиента">
                  <Plus size={18} strokeWidth={2.5} />
                </button>
              )}
            </div>
          </div>
        </div>
      )}

      {selectedBooking && (
        <BookingDetailModal
          booking={selectedBooking}
          onClose={() => setSelectedBooking(null)}
          onStatusChange={handleStatusChange}
          onReschedule={(b) => { setRescheduleError(''); setRescheduleBooking(b) }}
          updating={updating}
        />
      )}

      {rescheduleBooking && (
        <RescheduleModal
          booking={rescheduleBooking}
          employees={employees}
          onClose={() => setRescheduleBooking(null)}
          onSubmit={submitReschedule}
          submitting={rescheduleSubmitting}
          error={rescheduleError}
        />
      )}

      {showManualBooking && businessId && (
        <ManualBookingModal
          businessId={businessId}
          services={services}
          employees={employees}
          selectedDate={manualBookingDate}
          selectedTime={manualBookingTime}
          onClose={() => setShowManualBooking(false)}
          onCreated={() => { setShowManualBooking(false); fetchBookings() }}
        />
      )}
    </div>
  )
}
