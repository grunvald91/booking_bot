import { useState, useEffect, useCallback, useMemo, useRef } from 'react'
import {
  ChevronLeft,
  ChevronRight,
  Clock,
  Plus,
  X,
  Phone,
  CheckCircle,
  XCircle,
  AlertCircle,
  Loader2,
  ZoomIn,
  ZoomOut,
} from 'lucide-react'
import { api, type AdminBooking, type Service, type Employee } from '../../api/client'
import { useAdminBusiness } from '../../hooks/useAdminBusiness'
import { BusinessSelector } from '../../components/BusinessSelector'

// ── Helpers ──

const DAYS_SHORT = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс']

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

function calcEndTime(start: string, durationMin: number) {
  const [h, m] = start.split(':').map(Number)
  const total = h * 60 + m + durationMin
  return `${String(Math.floor(total / 60) % 24).padStart(2, '0')}:${String(total % 60).padStart(2, '0')}`
}

// 10-color gradient palette
const COLORS = [
  'from-violet-500 to-violet-700',
  'from-pink-500 to-pink-700',
  'from-amber-500 to-amber-700',
  'from-emerald-500 to-emerald-700',
  'from-blue-500 to-blue-700',
  'from-red-500 to-red-700',
  'from-cyan-500 to-cyan-700',
  'from-lime-500 to-lime-700',
  'from-rose-500 to-rose-700',
  'from-purple-500 to-purple-700',
]

const STATUS_LABELS: Record<string, string> = {
  pending: 'Ожидает',
  confirmed: 'Подтверждено',
  completed: 'Завершено',
  cancelled: 'Отменено',
  pending_prepayment: 'Ждёт оплату',
  prepayment_sent: 'Оплата отправлена',
}

const STATUS_COLORS: Record<string, string> = {
  pending: 'bg-yellow-100 text-yellow-800 border-yellow-300',
  confirmed: 'bg-blue-100 text-blue-800 border-blue-300',
  completed: 'bg-green-100 text-green-800 border-green-300',
  cancelled: 'bg-red-100 text-red-700 border-red-300',
  pending_prepayment: 'bg-orange-100 text-orange-800 border-orange-300',
  prepayment_sent: 'bg-purple-100 text-purple-800 border-purple-300',
}

// ── Booking Detail Modal ──

function BookingDetailModal({
  booking,
  onClose,
  onStatusChange,
  updating,
}: {
  booking: AdminBooking
  onClose: () => void
  onStatusChange: (id: number, status: string) => void
  updating: boolean
}) {
  const endTime = calcEndTime(booking.time, booking.service_duration || 60)

  return (
    <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4" onClick={onClose}>
      <div className="bg-white rounded-2xl shadow-xl max-w-sm w-full p-5" onClick={(e) => e.stopPropagation()}>
        <div className="flex justify-between items-start mb-4">
          <h3 className="text-lg font-bold text-apple-text">{booking.client_name}</h3>
          <button onClick={onClose} className="p-1 rounded-lg hover:bg-apple-bg">
            <X size={20} />
          </button>
        </div>

        <div className="space-y-3 mb-5">
          {booking.client_phone && (
            <div className="flex items-center gap-2 text-sm">
              <Phone size={16} className="text-apple-gray" />
              <a href={`tel:${booking.client_phone}`} className="text-apple-blue">{booking.client_phone}</a>
            </div>
          )}
          <div className="flex items-center gap-2 text-sm">
            <Clock size={16} className="text-apple-gray" />
            <span>{booking.time} — {endTime} ({booking.service_duration || 60} мин)</span>
          </div>
          <div className="text-sm">
            <span className="text-apple-gray">Услуга: </span>
            <span className="font-medium">{booking.service_name}</span>
          </div>
          {booking.employee_name && (
            <div className="text-sm">
              <span className="text-apple-gray">Специалист: </span>
              <span className="font-medium">{booking.employee_name}</span>
            </div>
          )}
          {booking.notes && (
            <div className="text-sm">
              <span className="text-apple-gray">Комментарий: </span>
              <span>{booking.notes}</span>
            </div>
          )}
          <span className={`inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium border ${STATUS_COLORS[booking.status] || 'bg-gray-100 text-gray-700 border-gray-300'}`}>
            {STATUS_LABELS[booking.status] || booking.status}
          </span>
        </div>

        {booking.status !== 'cancelled' && booking.status !== 'completed' && (
          <div className="flex gap-2">
            {booking.status === 'pending' && (
              <button
                onClick={() => onStatusChange(booking.id, 'confirmed')}
                disabled={updating}
                className="flex-1 flex items-center justify-center gap-1.5 bg-apple-blue text-white font-medium py-2.5 rounded-xl text-sm disabled:opacity-50"
              >
                <CheckCircle size={16} />
                Подтвердить
              </button>
            )}
            {(booking.status === 'confirmed' || booking.status === 'pending') && (
              <button
                onClick={() => onStatusChange(booking.id, 'completed')}
                disabled={updating}
                className="flex-1 flex items-center justify-center gap-1.5 bg-apple-success text-white font-medium py-2.5 rounded-xl text-sm disabled:opacity-50"
              >
                <CheckCircle size={16} />
                Завершить
              </button>
            )}
            <button
              onClick={() => onStatusChange(booking.id, 'cancelled')}
              disabled={updating}
              className="flex items-center justify-center gap-1.5 bg-apple-danger text-white font-medium py-2.5 px-4 rounded-xl text-sm disabled:opacity-50"
            >
              <XCircle size={16} />
            </button>
          </div>
        )}
      </div>
    </div>
  )
}

// ── Manual Booking Modal ──

function ManualBookingModal({
  businessId,
  services,
  employees,
  selectedDate,
  selectedTime,
  onClose,
  onCreated,
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
    <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4" onClick={onClose}>
      <div className="bg-white rounded-2xl shadow-xl max-w-sm w-full p-5 max-h-[90vh] overflow-y-auto" onClick={(e) => e.stopPropagation()}>
        <div className="flex justify-between items-start mb-4">
          <h3 className="text-lg font-bold text-apple-text">Записать клиента</h3>
          <button onClick={onClose} className="p-1 rounded-lg hover:bg-apple-bg"><X size={20} /></button>
        </div>

        <div className="space-y-3">
          <div>
            <label className="block text-sm font-medium text-apple-gray mb-1">Услуга</label>
            <select value={serviceId ?? ''} onChange={(e) => setServiceId(Number(e.target.value) || null)}
              className="w-full px-3 py-2.5 rounded-xl bg-apple-bg text-sm border-0 focus:outline-none focus:ring-2 focus:ring-apple-blue/40">
              <option value="">Выберите услугу</option>
              {services.filter(s => s.is_active).map((s) => (
                <option key={s.id} value={s.id}>{s.name} {s.duration_minutes ? `(${s.duration_minutes} мин)` : ''} {s.price ? `— ${s.price}₽` : ''}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-sm font-medium text-apple-gray mb-1">Специалист / Зал</label>
            <select value={employeeId ?? ''} onChange={(e) => setEmployeeId(Number(e.target.value) || null)}
              className="w-full px-3 py-2.5 rounded-xl bg-apple-bg text-sm border-0 focus:outline-none focus:ring-2 focus:ring-apple-blue/40">
              <option value="">Любой</option>
              {employees.map((e) => (<option key={e.id} value={e.id}>{e.name}</option>))}
            </select>
          </div>
          <div>
            <label className="block text-sm font-medium text-apple-gray mb-1">Время</label>
            <input type="time" value={time} onChange={(e) => setTime(e.target.value)}
              className="w-full px-3 py-2.5 rounded-xl bg-apple-bg text-sm border-0 focus:outline-none focus:ring-2 focus:ring-apple-blue/40" />
          </div>
          <div>
            <label className="block text-sm font-medium text-apple-gray mb-1">Имя клиента</label>
            <input type="text" value={clientName} onChange={(e) => setClientName(e.target.value)} placeholder="Введите имя"
              className="w-full px-3 py-2.5 rounded-xl bg-apple-bg text-sm border-0 focus:outline-none focus:ring-2 focus:ring-apple-blue/40" />
          </div>
          <div>
            <label className="block text-sm font-medium text-apple-gray mb-1">Телефон</label>
            <input type="tel" value={clientPhone} onChange={(e) => setClientPhone(e.target.value)} placeholder="+7"
              className="w-full px-3 py-2.5 rounded-xl bg-apple-bg text-sm border-0 focus:outline-none focus:ring-2 focus:ring-apple-blue/40" />
          </div>
          <div>
            <label className="block text-sm font-medium text-apple-gray mb-1">Комментарий</label>
            <textarea value={notes} onChange={(e) => setNotes(e.target.value)} rows={2}
              className="w-full px-3 py-2.5 rounded-xl bg-apple-bg text-sm border-0 focus:outline-none focus:ring-2 focus:ring-apple-blue/40 resize-none" />
          </div>
          {error && (
            <div className="flex items-center gap-1.5 text-sm text-apple-danger">
              <AlertCircle size={14} />{error}
            </div>
          )}
        </div>
        <button onClick={handleSubmit} disabled={submitting || !serviceId || !clientName}
          className="w-full mt-4 bg-apple-blue text-white font-semibold py-3 rounded-xl disabled:opacity-50 flex items-center justify-center gap-2">
          {submitting ? <Loader2 size={16} className="animate-spin" /> : <Plus size={16} />}
          {submitting ? 'Записываем...' : 'Записать'}
        </button>
      </div>
    </div>
  )
}

// ── Main Schedule Page ──

export function SchedulePage() {
  const { businesses, selectedId: businessId, selectBusiness } = useAdminBusiness()
  const [viewMode, setViewMode] = useState<'week' | 'day'>('week')
  const [weekOffset, setWeekOffset] = useState(0)
  const [dayOffset, setDayOffset] = useState(0)
  const [bookings, setBookings] = useState<AdminBooking[]>([])
  const [loading, setLoading] = useState(false)
  const [selectedBooking, setSelectedBooking] = useState<AdminBooking | null>(null)
  const [updating, setUpdating] = useState(false)
  const [showManualBooking, setShowManualBooking] = useState(false)
  const [manualBookingTime, setManualBookingTime] = useState<string | undefined>()
  const [manualBookingDate, setManualBookingDate] = useState<Date>(new Date())
  const [services, setServices] = useState<Service[]>([])
  const [allEmployees, setAllEmployees] = useState<Employee[]>([])
  const [selectedEmployeeId, setSelectedEmployeeId] = useState<number | null>(null)
  const [zoom, setZoom] = useState(0.7)
  const scheduleRef = useRef<HTMLDivElement>(null)
  const pinchStartDist = useRef<number | null>(null)
  const pinchStartZoom = useRef<number>(0.7)

  // Pinch-to-zoom handler
  useEffect(() => {
    const el = scheduleRef.current
    if (!el) return

    const getDistance = (touches: TouchList) => {
      const dx = touches[0].clientX - touches[1].clientX
      const dy = touches[0].clientY - touches[1].clientY
      return Math.sqrt(dx * dx + dy * dy)
    }

    const onTouchStart = (e: TouchEvent) => {
      if (e.touches.length === 2) {
        pinchStartDist.current = getDistance(e.touches)
        pinchStartZoom.current = zoom
      }
    }

    const onTouchMove = (e: TouchEvent) => {
      if (e.touches.length === 2 && pinchStartDist.current !== null) {
        e.preventDefault()
        const dist = getDistance(e.touches)
        const scale = dist / pinchStartDist.current
        const newZoom = Math.min(1.5, Math.max(0.4, pinchStartZoom.current * scale))
        setZoom(newZoom)
      }
    }

    const onTouchEnd = () => {
      pinchStartDist.current = null
    }

    el.addEventListener('touchstart', onTouchStart, { passive: true })
    el.addEventListener('touchmove', onTouchMove, { passive: false })
    el.addEventListener('touchend', onTouchEnd, { passive: true })
    return () => {
      el.removeEventListener('touchstart', onTouchStart)
      el.removeEventListener('touchmove', onTouchMove)
      el.removeEventListener('touchend', onTouchEnd)
    }
  }, [zoom])

  // Filter out admins — only show masters
  const employees = useMemo(() =>
    allEmployees.filter(e => !e.role || e.role === 'master' || e.role === 'master_and_admin'),
    [allEmployees]
  )

  // Color map for clients
  const colorMap = useMemo(() => {
    const map: Record<string, number> = {}
    let idx = 0
    bookings.forEach((b) => {
      const key = b.client_name || b.client_phone || ''
      if (key && !(key in map)) {
        map[key] = idx % 10
        idx++
      }
    })
    return map
  }, [bookings])

  const getColor = (b: AdminBooking) => COLORS[colorMap[b.client_name || b.client_phone || ''] ?? 0]

  // Time slots
  const TIME_SLOTS = useMemo(() => {
    const slots: string[] = []
    for (let h = 8; h <= 22; h++) slots.push(`${String(h).padStart(2, '0')}:00`)
    return slots
  }, [])

  const TIME_SLOTS_30 = useMemo(() => {
    const slots: string[] = []
    for (let h = 8; h < 22; h++) {
      slots.push(`${String(h).padStart(2, '0')}:00`)
      slots.push(`${String(h).padStart(2, '0')}:30`)
    }
    return slots
  }, [])

  // Current week dates
  const weekDates = useMemo(() => {
    const monday = getMonday(new Date())
    monday.setDate(monday.getDate() + weekOffset * 7)
    return Array.from({ length: 7 }, (_, i) => {
      const d = new Date(monday)
      d.setDate(d.getDate() + i)
      return d
    })
  }, [weekOffset])

  // Current day date
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

  // Fetch bookings
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

  // Auto-refresh every 15 seconds
  useEffect(() => {
    const timer = setInterval(fetchBookings, 15000)
    return () => clearInterval(timer)
  }, [fetchBookings])

  // Load services and employees
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
    } catch {} finally {
      setUpdating(false)
    }
  }

  const openNewBooking = (date: Date, time?: string) => {
    setManualBookingDate(date)
    setManualBookingTime(time)
    setShowManualBooking(true)
  }

  // Filter by employee in week view
  const filteredBookings = selectedEmployeeId
    ? bookings.filter((b) => b.employee_id === selectedEmployeeId)
    : bookings

  const todayISO = formatDateISO(new Date())

  return (
    <div className="flex flex-col" style={{ height: 'calc(100dvh - 130px - env(safe-area-inset-bottom, 0px))' }}>
      {/* Row 1: Business selector + View mode toggle */}
      <div className="flex items-center justify-between gap-2 shrink-0">
        <BusinessSelector businesses={businesses} selectedId={businessId} onSelect={selectBusiness} />
        <div className="flex gap-1 bg-apple-bg rounded-full p-0.5 shrink-0">
          <button onClick={() => setViewMode('week')}
            className={`px-3 py-1 rounded-full text-xs font-medium transition-all ${viewMode === 'week' ? 'bg-white text-apple-text shadow-sm' : 'text-apple-gray'}`}>
            Неделя
          </button>
          <button onClick={() => setViewMode('day')}
            className={`px-3 py-1 rounded-full text-xs font-medium transition-all ${viewMode === 'day' ? 'bg-white text-apple-text shadow-sm' : 'text-apple-gray'}`}>
            День
          </button>
        </div>
      </div>

      {/* Row 2: Navigation + zoom + stats */}
      <div className="flex items-center gap-1 shrink-0">
        <button onClick={() => viewMode === 'week' ? setWeekOffset(w => w - 1) : setDayOffset(d => d - 1)}
          className="p-1 rounded-lg hover:bg-apple-bg transition-all">
          <ChevronLeft size={18} />
        </button>
        <button onClick={() => { setWeekOffset(0); setDayOffset(0) }}
          className="text-xs text-apple-blue font-medium px-2 py-1 rounded-lg hover:bg-apple-blue/10 transition-all">
          Сегодня
        </button>
        <span className="text-xs font-semibold text-apple-text flex-1 text-center truncate">
          {viewMode === 'week' ? weekLabel : dayLabel}
        </span>
        <button onClick={() => viewMode === 'week' ? setWeekOffset(w => w + 1) : setDayOffset(d => d + 1)}
          className="p-1 rounded-lg hover:bg-apple-bg transition-all">
          <ChevronRight size={18} />
        </button>
        <div className="flex items-center gap-1 ml-1 bg-apple-bg rounded-lg px-1.5 py-0.5">
          <button onClick={() => setZoom(z => Math.max(0.4, z - 0.15))}
            className="w-7 h-7 rounded-md text-apple-gray hover:text-apple-text hover:bg-white flex items-center justify-center transition-all">
            <ZoomOut size={14} />
          </button>
          <button onClick={() => setZoom(0.7)}
            className="text-[11px] text-apple-gray font-medium w-9 text-center hover:text-apple-blue transition-colors cursor-pointer">
            {Math.round(zoom * 100)}%
          </button>
          <button onClick={() => setZoom(z => Math.min(1.5, z + 0.15))}
            className="w-7 h-7 rounded-md text-apple-gray hover:text-apple-text hover:bg-white flex items-center justify-center transition-all">
            <ZoomIn size={14} />
          </button>
        </div>
        {filteredBookings.length > 0 && (
          <div className="flex gap-1 ml-1">
            <span className="px-1.5 py-0.5 rounded-full bg-gray-100 text-[10px] text-apple-gray font-medium">
              {filteredBookings.length}
            </span>
            {filteredBookings.filter(b => b.status === 'pending').length > 0 && (
              <span className="px-1.5 py-0.5 rounded-full bg-yellow-50 text-[10px] text-yellow-700 font-medium">
                {filteredBookings.filter(b => b.status === 'pending').length}
              </span>
            )}
          </div>
        )}
      </div>

      {/* Schedule table — takes all remaining space */}
      <div ref={scheduleRef} className="flex-1 min-h-0 overflow-hidden">
        {loading && bookings.length === 0 ? (
          <div className="flex items-center justify-center py-20 text-apple-gray">
            <Loader2 size={24} className="animate-spin mr-2" />
            Загрузка...
          </div>
        ) : viewMode === 'week' ? (
          /* ═══ WEEK VIEW ═══ */
          <div className="overflow-auto" style={{ maxHeight: '100%' }}>
            <table className="w-full border-collapse origin-top-left" style={{ tableLayout: 'fixed', minWidth: `${60 + 7 * 110}px`, transform: `scale(${zoom})`, transformOrigin: 'top left', width: `${100 / zoom}%` }}>
              <thead className="sticky top-0 z-20">
                <tr>
                  <th className="sticky left-0 z-30 bg-gray-50 border border-apple-border/30 w-[60px] min-w-[60px]" />
                  {weekDates.map((d, i) => {
                    const isToday = formatDateISO(d) === todayISO
                    return (
                      <th key={i} className={`border border-apple-border/30 px-1 py-2 text-center min-w-[110px] ${isToday ? 'bg-apple-blue text-white' : 'bg-gray-50 text-apple-gray'}`}>
                        <div className="text-[10px] uppercase tracking-wider font-semibold opacity-80">{DAYS_SHORT[i]}</div>
                        <div className="text-sm font-bold mt-0.5">{d.getDate()}</div>
                      </th>
                    )
                  })}
                </tr>
              </thead>
              <tbody>
                {TIME_SLOTS.map((slot) => {
                  const hour = parseInt(slot)
                  return (
                    <tr key={slot}>
                      <td className="sticky left-0 z-10 bg-gray-50 border border-apple-border/30 text-center text-[11px] text-apple-gray font-medium py-1 w-[60px] min-w-[60px]">
                        {slot}
                      </td>
                      {weekDates.map((d, dayIdx) => {
                        const dateStr = formatDateISO(d)
                        const cellBookings = filteredBookings.filter((b) => {
                          if (b.date !== dateStr) return false
                          const bHour = parseInt(b.time.split(':')[0])
                          return bHour === hour
                        })
                        return (
                          <td key={dayIdx} className="border border-apple-border/30 p-0 h-12 align-top relative group cursor-pointer hover:bg-apple-blue/5 transition-colors"
                            onClick={() => cellBookings.length === 0 ? openNewBooking(d, slot) : undefined}>
                            {cellBookings.length === 0 && (
                              <div className="hidden group-hover:flex items-center justify-center h-full text-apple-blue/30 text-lg">+</div>
                            )}
                            {cellBookings.map((b) => {
                              const dur = b.service_duration || 60
                              const height = Math.max(44, (dur / 60) * 48 - 4)
                              const isPending = b.status === 'pending'
                              const isCancelled = b.status === 'cancelled'
                              return (
                                <div key={b.id}
                                  className={`absolute left-0.5 right-0.5 top-0.5 rounded bg-gradient-to-br ${getColor(b)} text-white cursor-pointer overflow-hidden hover:shadow-lg hover:scale-[1.02] transition-all z-[5] ${isPending ? 'opacity-75 border border-dashed border-white/40' : ''} ${isCancelled ? 'opacity-40 line-through' : ''}`}
                                  style={{ height: `${height}px` }}
                                  onClick={(e) => { e.stopPropagation(); setSelectedBooking(b) }}>
                                  <div className="px-1.5 py-1">
                                    <div className="text-[11px] font-semibold truncate">{b.client_name}</div>
                                    {selectedEmployeeId === null && b.employee_name && (
                                      <div className="text-[8px] bg-black/20 rounded px-1 mt-0.5 truncate">{b.employee_name}</div>
                                    )}
                                    <div className="text-[9px] opacity-85 truncate">{b.service_name}</div>
                                    <div className="text-[9px] opacity-70">{b.time}—{calcEndTime(b.time, dur)}</div>
                                  </div>
                                </div>
                              )
                            })}
                          </td>
                        )
                      })}
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        ) : (
          /* ═══ DAY VIEW ═══ */
          <div className="overflow-auto" style={{ maxHeight: '100%' }}>
            {(() => {
              const dayEmps = employees.length > 0 ? (selectedEmployeeId ? employees.filter(e => e.id === selectedEmployeeId) : employees) : [{ id: 0, name: 'Расписание' }]
              return (
                <table className="w-full border-collapse origin-top-left" style={{ tableLayout: 'fixed', minWidth: `${50 + dayEmps.length * 110}px`, transform: `scale(${zoom})`, transformOrigin: 'top left', width: `${100 / zoom}%` }}>
                  <thead className="sticky top-0 z-20">
                    <tr>
                      <th className="sticky left-0 z-30 bg-gray-50 border border-apple-border/30 w-[50px] min-w-[50px]" />
                      {dayEmps.map((emp) => (
                        <th key={emp.id} className="bg-gray-50 border border-apple-border/30 px-1 py-2 text-center text-[11px] font-semibold text-apple-gray min-w-[110px]">
                          {emp.name}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {TIME_SLOTS_30.map((slot) => {
                      const dateStr = formatDateISO(dayDate)
                      return (
                        <tr key={slot}>
                          <td className="sticky left-0 z-10 bg-gray-50 border border-apple-border/30 text-center text-[11px] text-apple-gray font-medium py-0 h-6 w-[50px] min-w-[50px]">
                            {slot}
                          </td>
                          {dayEmps.map((emp) => {
                            const dayBookings = bookings.filter(b => b.date === dateStr && (emp.id === 0 || b.employee_id === emp.id))
                            const startingBooking = dayBookings.find(b => b.time === slot)
                            const covered = dayBookings.some(b => {
                              if (b.time === slot) return false
                              const [bh, bm] = b.time.split(':').map(Number)
                              const [sh, sm] = slot.split(':').map(Number)
                              const bStart = bh * 60 + bm
                              const sStart = sh * 60 + sm
                              const dur = b.service_duration || 60
                              return sStart > bStart && sStart < bStart + dur
                            })

                            if (covered) return null

                            if (startingBooking) {
                              const dur = startingBooking.service_duration || 60
                              const rowspan = Math.max(1, Math.ceil(dur / 30))
                              const ci = colorMap[startingBooking.client_name || startingBooking.client_phone || ''] ?? 0
                              const isPending = startingBooking.status === 'pending'
                              const isCancelled = startingBooking.status === 'cancelled'
                              return (
                                <td key={emp.id} rowSpan={rowspan}
                                  className="border border-apple-border/30 p-0 relative cursor-pointer"
                                  onClick={() => setSelectedBooking(startingBooking)}>
                                  <div className={`absolute inset-px rounded bg-gradient-to-br ${COLORS[ci]} text-white overflow-hidden hover:brightness-110 transition-all ${isPending ? 'opacity-75 border border-dashed border-white/40' : ''} ${isCancelled ? 'opacity-40' : ''}`}>
                                    <div className="px-1.5 py-1">
                                      <div className="text-[10px] font-semibold truncate">{startingBooking.client_name}</div>
                                      {startingBooking.client_phone && (
                                        <div className="text-[9px] opacity-90 truncate">{startingBooking.client_phone}</div>
                                      )}
                                      {startingBooking.notes && (
                                        <div className="text-[9px] opacity-80 truncate italic">{startingBooking.notes}</div>
                                      )}
                                    </div>
                                  </div>
                                </td>
                              )
                            }

                            return (
                              <td key={emp.id} className="border border-apple-border/30 h-6 hover:bg-apple-blue/5 cursor-pointer transition-colors"
                                onClick={() => openNewBooking(dayDate, slot)} />
                            )
                          })}
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              )
            })()}
          </div>
        )}

      </div>

      {/* Employee filter tabs — connected to bottom nav */}
      {employees.length > 0 && (
        <div className="shrink-0 bg-white/95 backdrop-blur-xl border-t border-apple-border/20 shadow-[0_-1px_3px_rgba(0,0,0,0.04)] pb-1">
          <div className="overflow-x-auto scrollbar-hide px-3 py-2">
            <div className="flex gap-2 items-center">
              <button onClick={() => setSelectedEmployeeId(null)}
                className={`flex-shrink-0 px-3.5 py-1.5 rounded-full text-xs font-semibold transition-all ${selectedEmployeeId === null ? 'bg-apple-blue text-white shadow-sm' : 'bg-apple-bg text-apple-gray hover:bg-gray-200'}`}>
                Все
              </button>
              {employees.map((emp) => (
                <button key={emp.id} onClick={() => setSelectedEmployeeId(emp.id)}
                  className={`flex-shrink-0 px-3.5 py-1.5 rounded-full text-xs font-semibold transition-all whitespace-nowrap ${selectedEmployeeId === emp.id ? 'bg-apple-blue text-white shadow-sm' : 'bg-apple-bg text-apple-gray hover:bg-gray-200'}`}>
                  {emp.name}
                </button>
              ))}
              {/* FAB inline */}
              {businessId && (
                <button
                  onClick={() => openNewBooking(viewMode === 'week' ? new Date() : dayDate)}
                  className="flex-shrink-0 ml-auto w-9 h-9 rounded-full bg-apple-blue text-white shadow-md flex items-center justify-center active:scale-95 transition-transform"
                  aria-label="Записать клиента"
                >
                  <Plus size={18} strokeWidth={2.5} />
                </button>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Booking detail modal */}
      {selectedBooking && (
        <BookingDetailModal
          booking={selectedBooking}
          onClose={() => setSelectedBooking(null)}
          onStatusChange={handleStatusChange}
          updating={updating}
        />
      )}

      {/* Manual booking modal */}
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
