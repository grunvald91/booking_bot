import { useState, useEffect, useCallback, useMemo, useRef, type CSSProperties } from 'react'
import { Link } from 'react-router-dom'
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
  Search,
  Moon,
  Sun,
  ChevronDown,
  CalendarClock,
  LayoutDashboard,
  Scissors,
  Users,
  Settings,
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

// Палитра цветов мастеров (для цветных кнопок-фильтров)
const MASTER_COLORS = ['#2f5beb', '#e0533a', '#1b9e54', '#c98a16', '#7c3aed', '#0ea5b7', '#d6457e', '#5b7c0a', '#0f766e', '#9333ea']

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
        className="w-full sm:max-w-sm rounded-t-2xl sm:rounded-2xl p-5"
        style={{ background: 'var(--s-surface)', color: 'var(--s-text)', boxShadow: '0 -8px 30px rgba(0,0,0,.2)' }}
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
      <div className="w-full sm:max-w-sm rounded-t-2xl sm:rounded-2xl p-5" style={{ background: 'var(--s-surface)', color: 'var(--s-text)' }} onClick={(e) => e.stopPropagation()}>
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

// ── Manual booking modal (новый дизайн + повтор по неделям) ──
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
  const [repeatExtra, setRepeatExtra] = useState(0) // сколько ДОПОЛНИТЕЛЬНЫХ недель
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')

  const REPEATS = [
    { v: 0, l: 'Нет' },
    { v: 3, l: '4 нед' },
    { v: 7, l: '8 нед' },
    { v: 11, l: '12 нед' },
  ]
  const dateLabel = selectedDate.toLocaleDateString('ru-RU', { weekday: 'long', day: 'numeric', month: 'long' })

  const handleSubmit = async () => {
    if (!serviceId || !clientName) return
    setSubmitting(true)
    setError('')
    try {
      for (let i = 0; i <= repeatExtra; i++) {
        const d = new Date(selectedDate)
        d.setDate(d.getDate() + 7 * i)
        await api.createManualBooking({
          business_id: businessId,
          service_id: serviceId,
          employee_id: employeeId ?? undefined,
          date: formatDateISO(d),
          time,
          client_name: clientName,
          client_phone: clientPhone || undefined,
          notes: notes || undefined,
        })
      }
      onCreated()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Ошибка')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="sched-sheet-ov" onClick={onClose}>
      <div className="sched-sheet" onClick={(e) => e.stopPropagation()}>
        <div className="sched-sheet-grip" />
        <div className="sched-sheet-head">
          <div><h3>Новая запись</h3><p>{dateLabel}</p></div>
          <button onClick={onClose} className="sched-iconbtn"><X size={18} /></button>
        </div>

        <div className="sched-field">
          <label>Услуга</label>
          <select value={serviceId ?? ''} onChange={(e) => setServiceId(Number(e.target.value) || null)} className="sched-input">
            <option value="">Выберите услугу</option>
            {services.filter((s) => s.is_active).map((s) => (
              <option key={s.id} value={s.id}>{s.name} {s.duration_minutes ? `(${s.duration_minutes} мин)` : ''} {s.price ? `— ${s.price}₽` : ''}</option>
            ))}
          </select>
        </div>

        <div className="sched-field">
          <label>Специалист / Зал</label>
          <select value={employeeId ?? ''} onChange={(e) => setEmployeeId(Number(e.target.value) || null)} className="sched-input">
            <option value="">Любой</option>
            {employees.map((e) => <option key={e.id} value={e.id}>{e.name}</option>)}
          </select>
        </div>

        <div className="sched-field">
          <div className="sched-field-row">
            <div>
              <label>Время</label>
              <input type="time" value={time} onChange={(e) => setTime(e.target.value)} className="sched-input" />
            </div>
            <div>
              <label>Телефон</label>
              <input type="tel" value={clientPhone} onChange={(e) => setClientPhone(e.target.value)} placeholder="+7" className="sched-input" />
            </div>
          </div>
        </div>

        <div className="sched-field">
          <label>Имя клиента</label>
          <input type="text" value={clientName} onChange={(e) => setClientName(e.target.value)} placeholder="Введите имя" className="sched-input" />
        </div>

        <div className="sched-field">
          <label>Комментарий</label>
          <textarea value={notes} onChange={(e) => setNotes(e.target.value)} rows={2} className="sched-input" />
        </div>

        <div className="sched-field">
          <label>Повторять еженедельно</label>
          <div className="sched-seg-full">
            {REPEATS.map((r) => (
              <button key={r.v} className={repeatExtra === r.v ? 'on' : ''} onClick={() => setRepeatExtra(r.v)}>{r.l}</button>
            ))}
          </div>
          {repeatExtra > 0 && (
            <p className="sched-hint">Будет создано {repeatExtra + 1} записей — то же время и день недели, {repeatExtra} недель подряд.</p>
          )}
        </div>

        {error && <div className="sched-error"><AlertCircle size={14} />{error}</div>}
        <button onClick={handleSubmit} disabled={submitting || !serviceId || !clientName} className="sched-submit">
          {submitting ? <Loader2 size={16} className="animate-spin" /> : <Plus size={16} />}
          {submitting ? 'Записываем…' : repeatExtra > 0 ? `Записать · ${repeatExtra + 1}` : 'Записать'}
        </button>
      </div>
    </div>
  )
}

// ── Подтверждение переноса (после drag&drop) ──
function ConfirmMoveModal({
  clientName, fromLabel, toLabel, submitting, onCancel, onConfirm,
}: {
  clientName: string
  fromLabel: string
  toLabel: string
  submitting: boolean
  onCancel: () => void
  onConfirm: () => void
}) {
  return (
    <div className="sched-center-ov" onClick={onCancel}>
      <div className="sched-confirm" onClick={(e) => e.stopPropagation()}>
        <h3>Перенести запись?</h3>
        <p>{clientName}</p>
        <div className="sched-confirm-from">Было: {fromLabel}</div>
        <div className="sched-confirm-to"><CalendarClock size={16} />{toLabel}</div>
        <div className="sched-confirm-actions">
          <button className="ghost" onClick={onCancel} disabled={submitting}>Отмена</button>
          <button className="primary" onClick={onConfirm} disabled={submitting}>
            {submitting ? <Loader2 size={15} className="animate-spin" /> : <CalendarClock size={15} />}Перенести
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Booking card ──
function BookingCard({
  p, pxPerMin, showEmployee, onClick, onPointerDown, dragging,
}: {
  p: Positioned
  pxPerMin: number
  showEmployee: boolean
  onClick?: () => void
  onPointerDown?: (e: React.PointerEvent) => void
  dragging?: boolean
}) {
  const b = p.booking
  const sv = statusVar(b.status)
  const top = (p.startMin - DAY_START_H * 60) * pxPerMin
  const height = Math.max(20, (p.endMin - p.startMin) * pxPerMin - 2)
  const laneWPct = 100 / p.lanes
  const cardStyle = {
    top,
    height,
    left: `calc(${(p.lane * laneWPct).toFixed(4)}% + 2px)`,
    width: `calc(${laneWPct.toFixed(4)}% - 4px)`,
    opacity: dragging ? 0.35 : undefined,
    '--card-accent': `var(--st-${sv})`,
    '--card-bg': `var(--st-${sv}-bg)`,
  } as CSSProperties
  return (
    <div
      className={`sched-card ${b.status === 'cancelled' ? 'is-cancelled' : ''} ${b.status === 'pending' ? 'is-pending' : ''} ${onPointerDown ? 'is-draggable' : ''}`}
      style={cardStyle}
      onPointerDown={onPointerDown}
      onClick={(e) => { e.stopPropagation(); onClick?.() }}
    >
      <div className="c-name">{b.client_name}</div>
      {height > 32 && <div className="c-sub">{b.service_name}</div>}
      {height > 46 && showEmployee && b.employee_name && <div className="c-sub">{b.employee_name}</div>}
      {height > 46 && <div className="c-sub">{b.time}–{calcEndTime(b.time, b.service_duration || 60)}</div>}
    </div>
  )
}

// ── Day-peek sheet (±окно вокруг места тапа в недельном виде) ──
function DayPeekSheet({
  dateStr, lo, hi, bookings, empColor, onClose, onPick,
}: {
  dateStr: string
  lo: number
  hi: number
  bookings: AdminBooking[]
  empColor: (id: number) => string
  onClose: () => void
  onPick: (b: AdminBooking) => void
}) {
  const [y, m, da] = dateStr.split('-').map(Number)
  const d = new Date(y, m - 1, da)
  const list = bookings
    .filter((b) => b.date === dateStr)
    .filter((b) => {
      const s = timeToMin(b.time)
      return s < hi && s + (b.service_duration || 60) > lo
    })
    .sort((a, b) => timeToMin(a.time) - timeToMin(b.time))
  const title = `${d.toLocaleDateString('ru-RU', { weekday: 'short', day: 'numeric', month: 'short' })} · ${minToTime(lo)}–${minToTime(hi)}`
  return (
    <div className="fixed inset-0 z-[60] flex items-end justify-center" onClick={onClose}>
      <div className="absolute inset-0" style={{ background: 'rgba(4,9,16,.55)' }} />
      <div className="sched-peek" onClick={(e) => e.stopPropagation()}>
        <div className="sched-peek-head">
          <h3>{title}</h3>
          <button onClick={onClose} className="sched-iconbtn"><X size={17} /></button>
        </div>
        <div className="sched-peek-list">
          {list.length === 0 ? (
            <div className="sched-peek-empty">В этом промежутке записей нет</div>
          ) : list.map((b) => {
            const sv = statusVar(b.status)
            const end = calcEndTime(b.time, b.service_duration || 60)
            return (
              <button key={b.id} className={`sched-di ${b.status === 'cancelled' ? 'cancelled' : ''}`}
                style={{ borderLeftColor: `var(--st-${sv})` }}
                onClick={() => onPick(b)}>
                <span className="di-time"><span className="t1">{b.time}</span><span className="t2">{b.service_duration || 60} мин</span></span>
                <span className="di-main">
                  <span className="di-name">{b.client_name}</span>
                  <span className="di-svc">{b.service_name}</span>
                  {b.employee_name && b.employee_id != null && (
                    <span className="di-emp"><span className="ed" style={{ background: empColor(b.employee_id) }} />{b.employee_name} · {b.time}–{end}</span>
                  )}
                </span>
                <span className="di-badge" style={{ background: `var(--st-${sv}-bg)`, color: `var(--st-${sv})` }}>{STATUS_LABELS[b.status] || b.status}</span>
              </button>
            )
          })}
        </div>
      </div>
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
  const [detailsOpen, setDetailsOpen] = useState(false)
  const [theme, setTheme] = useState<'light' | 'dark'>(() => {
    const saved = localStorage.getItem('schedTheme')
    if (saved === 'dark' || saved === 'light') return saved
    const tg = (window as unknown as { Telegram?: { WebApp?: { colorScheme?: string } } }).Telegram?.WebApp?.colorScheme
    if (tg === 'dark') return 'dark'
    return window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
  })
  const [daySheet, setDaySheet] = useState<{ dateStr: string; lo: number; hi: number } | null>(null)
  // живое состояние перетаскивания (день)
  const [drag, setDrag] = useState<null | {
    id: number; clientName: string; x: number; y: number; w: number; h: number; grabDY: number; newMin: number; durMin: number
  }>(null)
  const [pendingMove, setPendingMove] = useState<null | {
    id: number; clientName: string; date: string; time: string; employeeId?: number; fromLabel: string; toLabel: string
  }>(null)
  const [movingSubmit, setMovingSubmit] = useState(false)
  const colsRef = useRef<HTMLDivElement>(null)

  useEffect(() => { localStorage.setItem('schedTheme', theme) }, [theme])

  const WINDOW = 120 // ±минут для панели «записи рядом» в недельном виде

  // ── Pinch-to-zoom (щипком) по таймлайну + Ctrl+колесо на десктопе ──
  const tlRef = useRef<HTMLDivElement>(null)
  const pxPerMinRef = useRef(pxPerMin)
  useEffect(() => { pxPerMinRef.current = pxPerMin }, [pxPerMin])
  useEffect(() => {
    const el = tlRef.current
    if (!el) return
    const clamp = (v: number) => Math.min(1.8, Math.max(0.35, +v.toFixed(3)))
    const dist = (t: TouchList) => Math.hypot(t[0].clientX - t[1].clientX, t[0].clientY - t[1].clientY)
    let base: { d: number; ppm: number } | null = null
    const onStart = (e: TouchEvent) => { if (e.touches.length === 2) base = { d: dist(e.touches), ppm: pxPerMinRef.current } }
    const onMove = (e: TouchEvent) => {
      if (e.touches.length === 2 && base) {
        e.preventDefault()
        setPxPerMin(clamp(base.ppm * (dist(e.touches) / base.d)))
      }
    }
    const onEnd = (e: TouchEvent) => { if (e.touches.length < 2) base = null }
    const onWheel = (e: WheelEvent) => {
      if (!e.ctrlKey) return
      e.preventDefault()
      setPxPerMin((p) => clamp(p - e.deltaY * 0.0025))
    }
    el.addEventListener('touchstart', onStart, { passive: false })
    el.addEventListener('touchmove', onMove, { passive: false })
    el.addEventListener('touchend', onEnd)
    el.addEventListener('wheel', onWheel, { passive: false })
    return () => {
      el.removeEventListener('touchstart', onStart)
      el.removeEventListener('touchmove', onMove)
      el.removeEventListener('touchend', onEnd)
      el.removeEventListener('wheel', onWheel)
    }
  }, [])

  const employees = useMemo(
    () => allEmployees.filter((e) => !e.role || e.role === 'master' || e.role === 'master_and_admin'),
    [allEmployees]
  )

  const empColor = useCallback(
    (id: number) => {
      const i = employees.findIndex((e) => e.id === id)
      return MASTER_COLORS[(i < 0 ? 0 : i) % MASTER_COLORS.length]
    },
    [employees]
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

  // ── Pointer-based drag&drop переноса (день): работает и на touch, и мышью ──
  const beginCardDrag = (e: React.PointerEvent, p: Positioned) => {
    if (viewMode !== 'day') return
    if (e.pointerType === 'mouse' && e.button !== 0) return
    e.stopPropagation()
    const el = e.currentTarget as HTMLElement
    const rect = el.getBoundingClientRect()
    const grabDY = e.clientY - rect.top
    const startX = e.clientX, startY = e.clientY
    const ptrId = e.pointerId
    const durMin = p.endMin - p.startMin
    let dragging = false
    let holdTimer: number | undefined

    const target = (cx: number, cy: number) => {
      const cont = colsRef.current
      if (!cont) return { colIndex: 0, newMin: p.startMin }
      const cr = cont.getBoundingClientRect()
      const colW = cr.width / Math.max(1, dayColumns.length)
      const colIndex = Math.max(0, Math.min(dayColumns.length - 1, Math.floor((cx - cr.left) / colW)))
      const rawMin = DAY_START_H * 60 + (cy - grabDY - cr.top) / pxPerMin
      const newMin = Math.max(DAY_START_H * 60, Math.min(DAY_END_H * 60 - durMin, Math.round(rawMin / 5) * 5))
      return { colIndex, newMin }
    }

    const begin = (cx: number, cy: number) => {
      dragging = true
      try { el.setPointerCapture?.(ptrId) } catch { /* noop */ }
      const t = target(cx, cy)
      setDrag({ id: p.booking.id, clientName: p.booking.client_name, x: cx, y: cy, w: rect.width, h: rect.height, grabDY, newMin: t.newMin, durMin })
    }

    const onMove = (ev: PointerEvent) => {
      const moved = Math.hypot(ev.clientX - startX, ev.clientY - startY)
      if (!dragging) {
        if (e.pointerType === 'touch') {
          // до long-press любое движение = скролл таймлайна → отменяем кандидата
          if (moved > 10) { cleanup(); }
          return
        }
        if (moved > 5) begin(ev.clientX, ev.clientY); else return
      }
      ev.preventDefault()
      const t = target(ev.clientX, ev.clientY)
      setDrag((d) => (d ? { ...d, x: ev.clientX, y: ev.clientY, newMin: t.newMin } : d))
    }

    const onUp = (ev: PointerEvent) => {
      const wasDragging = dragging
      cleanup()
      if (wasDragging) {
        const t = target(ev.clientX, ev.clientY)
        const emp = dayColumns[t.colIndex]
        const dateStr = formatDateISO(dayDate)
        const empChanged = !!emp && emp.id !== 0 && emp.id !== (p.booking.employee_id || 0)
        const changed = t.newMin !== p.startMin || empChanged
        setDrag(null)
        if (changed) {
          const wd = dayDate.toLocaleDateString('ru-RU', { weekday: 'short', day: 'numeric', month: 'short' })
          const fromEmp = dayColumns.find((c) => c.id === (p.booking.employee_id || 0))?.name
          setPendingMove({
            id: p.booking.id,
            clientName: p.booking.client_name,
            date: dateStr,
            time: minToTime(t.newMin),
            employeeId: emp?.id || undefined,
            fromLabel: `${minToTime(p.startMin)}${fromEmp ? `, ${fromEmp}` : ''}`,
            toLabel: `${wd}, ${minToTime(t.newMin)}${empChanged ? `, ${emp!.name}` : ''}`,
          })
        }
      } else {
        setSelectedBooking(p.booking)
      }
    }

    function cleanup() {
      dragging = false
      if (holdTimer) { clearTimeout(holdTimer); holdTimer = undefined }
      window.removeEventListener('pointermove', onMove)
      window.removeEventListener('pointerup', onUp)
      window.removeEventListener('pointercancel', onUp)
    }

    window.addEventListener('pointermove', onMove, { passive: false })
    window.addEventListener('pointerup', onUp)
    window.addEventListener('pointercancel', onUp)
    if (e.pointerType === 'touch') holdTimer = window.setTimeout(() => begin(startX, startY), 220)
  }

  const openDayPeek = (dateStr: string, tappedMin: number) => {
    const lo = Math.max(DAY_START_H * 60, Math.round(tappedMin) - WINDOW)
    const hi = Math.min(DAY_END_H * 60, Math.round(tappedMin) + WINDOW)
    setDaySheet({ dateStr, lo, hi })
  }

  const confirmMove = async () => {
    if (!pendingMove) return
    setMovingSubmit(true)
    try {
      await doReschedule(pendingMove.id, pendingMove.date, pendingMove.time, pendingMove.employeeId, true)
    } catch { /* ignore */ } finally {
      setMovingSubmit(false)
      setPendingMove(null)
    }
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
  const currentBizName = businesses.find((b) => b.id === businessId)?.name
  const todayISO = formatDateISO(new Date())
  const hourMarks = Array.from({ length: DAY_END_H - DAY_START_H + 1 }, (_, i) => DAY_START_H + i)

  // Day columns = masters (or single)
  const dayColumns = useMemo(() => {
    const base = selectedEmployeeId ? employees.filter((e) => e.id === selectedEmployeeId) : employees
    return base.length > 0 ? base : [{ id: 0, name: 'Расписание' } as Employee]
  }, [employees, selectedEmployeeId])

  const showNow =
    (viewMode === 'day' ? formatDateISO(dayDate) === todayISO : weekOffset === 0) &&
    nowMin >= DAY_START_H * 60 && nowMin <= DAY_END_H * 60
  const colCount = viewMode === 'day' ? dayColumns.length : 7

  return (
    <div className="sched-root" data-theme={theme}>
      {/* Header */}
      <header className="sched-header">
        <div className="sched-htitle">
          <h1>Расписание</h1>
          {currentBizName && <div className="sched-hsub"><span className="dot" />{currentBizName}</div>}
        </div>
        <button className="sched-iconbtn bordered" onClick={() => setTheme((t) => (t === 'dark' ? 'light' : 'dark'))} aria-label="Тема">
          {theme === 'dark' ? <Sun size={17} /> : <Moon size={17} />}
        </button>
        <BusinessSelector businesses={businesses} selectedId={businessId} onSelect={selectBusiness} />
      </header>

      {/* Search */}
      <div className="sched-toolbar">
        <div className="sched-search">
          <Search size={17} />
          <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Поиск по клиенту, услуге, телефону" />
          {search && <button className="clear" onClick={() => setSearch('')} aria-label="Очистить">×</button>}
        </div>
      </div>

      {/* Control row: режим + листалка дат + сворачивание сводки */}
      <div className="sched-controls">
        <div className="sched-seg">
          <button onClick={() => setViewMode('day')} className={viewMode === 'day' ? 'active' : ''}>День</button>
          <button onClick={() => setViewMode('week')} className={viewMode === 'week' ? 'active' : ''}>Неделя</button>
        </div>
        <div className="sched-stepper">
          <button onClick={() => (viewMode === 'week' ? setWeekOffset((w) => w - 1) : setDayOffset((d) => d - 1))} className="sched-stepper-nav" aria-label="Назад"><ChevronLeft size={18} /></button>
          <button className="sched-stepper-label" onClick={() => { setWeekOffset(0); setDayOffset(0) }}>
            <span className="main">{viewMode === 'week' ? weekLabel : dayLabel}</span>
          </button>
          <button onClick={() => (viewMode === 'week' ? setWeekOffset((w) => w + 1) : setDayOffset((d) => d + 1))} className="sched-stepper-nav" aria-label="Вперёд"><ChevronRight size={18} /></button>
        </div>
        <button className={`sched-details-toggle ${detailsOpen ? 'open' : ''}`} onClick={() => setDetailsOpen((v) => !v)} aria-label="Сводка и легенда">
          <ChevronDown size={16} />
        </button>
      </div>

      {/* Сводка + легенда (свёрнуты по умолчанию) */}
      {detailsOpen && (
        <>
          <div className="sched-summary">
            <div className="tile"><div className="num">{summary.count}</div><div className="lbl">записей</div></div>
            <div className="tile"><div className="num">{summary.revenue.toLocaleString('ru-RU')}</div><div className="lbl">выручка ₽</div></div>
            <div className="tile"><div className="num">{summary.load}%</div><div className="lbl">загрузка</div></div>
          </div>
          <div className="sched-legend">
            {LEGEND_ITEMS.map((it) => (
              <div className="item" key={it.key}>
                <span className="swatch" style={{ background: `var(--st-${it.key})` }} /><span>{it.label}</span>
              </div>
            ))}
          </div>
        </>
      )}

      {/* Прилипшая шапка колонок */}
      <div className="sched-colhead" style={{ gridTemplateColumns: `var(--gutter) repeat(${colCount}, 1fr)` }}>
        <div />
        {viewMode === 'day'
          ? dayColumns.map((emp) => {
              const dim = selectedEmployeeId !== null && emp.id !== 0 && selectedEmployeeId !== emp.id
              return (
                <div key={emp.id} className="sched-emp-cap" style={{ opacity: dim ? 0.35 : 1 }}
                  onClick={() => emp.id !== 0 && setSelectedEmployeeId(selectedEmployeeId === emp.id ? null : emp.id)}>
                  <span className="cap" style={{ background: emp.id !== 0 ? empColor(emp.id) : 'var(--s-line-2)' }} />
                </div>
              )
            })
          : weekDates.map((d, i) => (
              <div key={i} className={`sched-wday-head ${formatDateISO(d) === todayISO ? 'today' : ''}`}>
                <span className="wd">{DAYS_SHORT[i]}</span><span className="dt">{d.getDate()}</span>
              </div>
            ))}
      </div>

      {/* Таймлайн (тело) */}
      <div className="sched-tl" ref={tlRef}>
        {loading && bookings.length === 0 ? (
          <div className="sched-empty"><Loader2 size={22} className="animate-spin" /> Загрузка…</div>
        ) : (
          <div className="sched-tl-inner" style={{ height: colHeight, '--pxh': `${(60 * pxPerMin).toFixed(2)}px` } as CSSProperties}>
            <div className="sched-tl-gutter">
              {hourMarks.map((h) => (
                <div key={h} className="sched-tl-hour" style={{ top: (h - DAY_START_H) * 60 * pxPerMin }}>{h}:00</div>
              ))}
            </div>
            <div className="sched-tl-cols" ref={colsRef} style={{ gridTemplateColumns: `repeat(${colCount}, 1fr)` }}>
              {viewMode === 'day'
                ? dayColumns.map((emp) => {
                    const dateStr = formatDateISO(dayDate)
                    const colBookings = visibleBookings.filter((b) => b.date === dateStr && (emp.id === 0 || b.employee_id === emp.id))
                    const positioned = layoutColumn(colBookings)
                    const dim = selectedEmployeeId !== null && emp.id !== 0 && selectedEmployeeId !== emp.id
                    return (
                      <div
                        key={emp.id}
                        className="sched-tl-col"
                        style={{ opacity: dim ? 0.32 : 1 }}
                        onClick={(e) => {
                          const rect = (e.currentTarget as HTMLElement).getBoundingClientRect()
                          const min = DAY_START_H * 60 + Math.round(((e.clientY - rect.top) / pxPerMin) / 15) * 15
                          openNewBooking(dayDate, minToTime(Math.max(DAY_START_H * 60, Math.min(DAY_END_H * 60 - 15, min))))
                        }}
                      >
                        {positioned.map((p) => (
                          <BookingCard
                            key={p.booking.id}
                            p={p}
                            pxPerMin={pxPerMin}
                            showEmployee={false}
                            dragging={drag?.id === p.booking.id}
                            onPointerDown={(e) => beginCardDrag(e, p)}
                          />
                        ))}
                      </div>
                    )
                  })
                : weekDates.map((d, dayIdx) => {
                    const dateStr = formatDateISO(d)
                    const dayBookings = visibleBookings.filter((b) => b.date === dateStr)
                    const isToday = dateStr === todayISO
                    return (
                      <div key={dayIdx} className={`sched-tl-col ${isToday ? 'today' : ''}`}
                        style={{ cursor: 'pointer' }}
                        onClick={(e) => {
                          if (dayBookings.length === 0) { openNewBooking(d); return }
                          const rect = (e.currentTarget as HTMLElement).getBoundingClientRect()
                          const t = DAY_START_H * 60 + (e.clientY - rect.top) / pxPerMin
                          openDayPeek(dateStr, t)
                        }}>
                        {layoutColumn(dayBookings).map((p) => (
                          <BookingCard
                            key={p.booking.id}
                            p={p}
                            pxPerMin={pxPerMin}
                            showEmployee
                          />
                        ))}
                      </div>
                    )
                  })}
            </div>
            {showNow && (
              <div className="sched-now" style={{ top: (nowMin - DAY_START_H * 60) * pxPerMin }}>
                <div className="bar" /><div className="knob" />
                {viewMode === 'day' && <div className="lbl">{minToTime(nowMin)}</div>}
              </div>
            )}
          </div>
        )}
      </div>

      {/* Чипы-фильтры мастеров */}
      {employees.length > 0 && (
        <div className="sched-chips">
          <button onClick={() => setSelectedEmployeeId(null)} className={`sched-chip ${selectedEmployeeId === null ? 'active' : ''}`}>Все</button>
          {employees.map((emp) => {
            const col = empColor(emp.id)
            const active = selectedEmployeeId === emp.id
            return (
              <button
                key={emp.id}
                onClick={() => setSelectedEmployeeId(active ? null : emp.id)}
                className={`sched-chip ${active ? 'active' : ''}`}
                style={active ? { background: col, borderColor: col, color: '#04121f' } : undefined}
              >
                {!active && <span className="chip-dot" style={{ background: col }} />}
                {emp.name}
              </button>
            )
          })}
        </div>
      )}

      {/* Нижняя навигация (как в архиве) */}
      <nav className="sched-bottomnav">
        <Link to="/admin" className="sched-bn"><LayoutDashboard size={21} /><span>Панель</span></Link>
        <Link to="/admin/schedule" className="sched-bn active"><Clock size={21} /><span>Расписание</span></Link>
        <Link to="/admin/services" className="sched-bn"><Scissors size={21} /><span>Услуги</span></Link>
        <Link to="/admin/employees" className="sched-bn"><Users size={21} /><span>Мастера</span></Link>
        <Link to="/admin/settings" className="sched-bn"><Settings size={21} /><span>Настройки</span></Link>
      </nav>

      {/* FAB — крупная плавающая кнопка (как в архиве) */}
      {businessId && (
        <button onClick={() => openNewBooking(viewMode === 'week' ? new Date() : dayDate)}
          className="sched-fab" aria-label="Записать клиента">
          <Plus size={26} strokeWidth={2.4} />
        </button>
      )}

      {/* Гхост при перетаскивании */}
      {drag && (
        <div className="sched-drag-ghost" style={{
          position: 'fixed', left: drag.x + 10, top: drag.y - drag.grabDY,
          width: drag.w, height: drag.h, pointerEvents: 'none', zIndex: 80,
        }}>
          <div className="c-name">{drag.clientName}</div>
          <div className="c-sub">{minToTime(drag.newMin)}–{minToTime(drag.newMin + drag.durMin)}</div>
        </div>
      )}

      {daySheet && (
        <DayPeekSheet
          dateStr={daySheet.dateStr}
          lo={daySheet.lo}
          hi={daySheet.hi}
          bookings={visibleBookings}
          empColor={empColor}
          onClose={() => setDaySheet(null)}
          onPick={(b) => { setDaySheet(null); setSelectedBooking(b) }}
        />
      )}

      {pendingMove && (
        <ConfirmMoveModal
          clientName={pendingMove.clientName}
          fromLabel={pendingMove.fromLabel}
          toLabel={pendingMove.toLabel}
          submitting={movingSubmit}
          onCancel={() => setPendingMove(null)}
          onConfirm={confirmMove}
        />
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
