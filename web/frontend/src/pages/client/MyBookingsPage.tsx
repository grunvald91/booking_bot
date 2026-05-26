import { useState, useEffect, useMemo } from 'react'
import { Link } from 'react-router-dom'
import {
  Calendar,
  Clock,
  MapPin,
  XCircle,
  CheckCircle,
  AlertCircle,
  ClipboardList,
  RefreshCw,
  ChevronLeft,
  ChevronRight,
  X,
  CreditCard,
  User,
} from 'lucide-react'
import { api, type Booking } from '../../api/client'
import { hapticSelection, hapticSuccess, hapticError } from '../../utils/telegram'

// ── Status config ──

type BookingStatus = Booking['status'] | 'pending_prepayment'

const statusConfig: Record<
  BookingStatus,
  { label: string; icon: typeof CheckCircle; className: string }
> = {
  confirmed: {
    label: 'Подтверждено',
    icon: CheckCircle,
    className: 'text-green-700 bg-green-50 border border-green-200',
  },
  pending: {
    label: 'Ожидает',
    icon: AlertCircle,
    className: 'text-yellow-700 bg-yellow-50 border border-yellow-200',
  },
  pending_prepayment: {
    label: 'Ожидает оплату',
    icon: CreditCard,
    className: 'text-orange-700 bg-orange-50 border border-orange-200',
  },
  cancelled: {
    label: 'Отменено',
    icon: XCircle,
    className: 'text-red-700 bg-red-50 border border-red-200',
  },
  completed: {
    label: 'Завершено',
    icon: CheckCircle,
    className: 'text-apple-gray bg-gray-50 border border-gray-200',
  },
}

// ── Helpers ──

const MONTHS_RU = [
  'Январь', 'Февраль', 'Март', 'Апрель', 'Май', 'Июнь',
  'Июль', 'Август', 'Сентябрь', 'Октябрь', 'Ноябрь', 'Декабрь',
]

function formatDateRu(dateStr: string) {
  const d = new Date(dateStr)
  const months = [
    'января', 'февраля', 'марта', 'апреля', 'мая', 'июня',
    'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря',
  ]
  const days = ['воскресенье', 'понедельник', 'вторник', 'среда', 'четверг', 'пятница', 'суббота']
  return `${d.getDate()} ${months[d.getMonth()]}, ${days[d.getDay()]}`
}

function formatDateShort(dateStr: string) {
  const d = new Date(dateStr)
  const months = [
    'янв', 'фев', 'мар', 'апр', 'мая', 'июн',
    'июл', 'авг', 'сен', 'окт', 'ноя', 'дек',
  ]
  return `${d.getDate()} ${months[d.getMonth()]}`
}

function isToday(dateStr: string) {
  const today = new Date()
  const d = new Date(dateStr)
  return (
    d.getFullYear() === today.getFullYear() &&
    d.getMonth() === today.getMonth() &&
    d.getDate() === today.getDate()
  )
}

function isPast(dateStr: string) {
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  const d = new Date(dateStr)
  d.setHours(0, 0, 0, 0)
  return d < today
}

function pad2(n: number) {
  return n.toString().padStart(2, '0')
}

function dateToString(d: Date) {
  return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`
}

// ── Inline Calendar ──

function InlineCalendar({
  selected,
  onSelect,
}: {
  selected: string | null
  onSelect: (date: string) => void
}) {
  const today = new Date()
  const [currentMonth, setCurrentMonth] = useState(
    new Date(today.getFullYear(), today.getMonth(), 1)
  )

  const days = useMemo(() => {
    const year = currentMonth.getFullYear()
    const month = currentMonth.getMonth()
    const firstDay = new Date(year, month, 1).getDay()
    const daysInMonth = new Date(year, month + 1, 0).getDate()
    const result: (Date | null)[] = []
    const startIdx = firstDay === 0 ? 6 : firstDay - 1
    for (let i = 0; i < startIdx; i++) result.push(null)
    for (let d = 1; d <= daysInMonth; d++) result.push(new Date(year, month, d))
    return result
  }, [currentMonth])

  const prevMonth = () =>
    setCurrentMonth(new Date(currentMonth.getFullYear(), currentMonth.getMonth() - 1, 1))
  const nextMonth = () =>
    setCurrentMonth(new Date(currentMonth.getFullYear(), currentMonth.getMonth() + 1, 1))

  return (
    <div className="bg-apple-bg rounded-xl p-4">
      <div className="flex items-center justify-between mb-3">
        <button
          onClick={prevMonth}
          className="p-2 rounded-xl hover:bg-white transition-all duration-200 min-h-[44px] min-w-[44px] flex items-center justify-center"
        >
          <ChevronLeft size={18} />
        </button>
        <h4 className="font-semibold text-apple-text text-sm">
          {MONTHS_RU[currentMonth.getMonth()]} {currentMonth.getFullYear()}
        </h4>
        <button
          onClick={nextMonth}
          className="p-2 rounded-xl hover:bg-white transition-all duration-200 min-h-[44px] min-w-[44px] flex items-center justify-center"
        >
          <ChevronRight size={18} />
        </button>
      </div>
      <div className="grid grid-cols-7 gap-1 mb-1">
        {['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс'].map((d) => (
          <div key={d} className="text-center text-[11px] font-medium text-apple-gray py-1">
            {d}
          </div>
        ))}
      </div>
      <div className="grid grid-cols-7 gap-1">
        {days.map((day, i) => {
          if (!day) return <div key={`e-${i}`} />
          const ds = dateToString(day)
          const isSelected = ds === selected
          const isPastDay = isPast(ds) && !isToday(ds)
          return (
            <button
              key={ds}
              disabled={isPastDay}
              onClick={() => {
                hapticSelection()
                onSelect(ds)
              }}
              className={`
                text-sm rounded-lg py-1.5 min-h-[36px] transition-all duration-200
                ${isPastDay ? 'text-apple-gray/40 cursor-not-allowed' : 'hover:bg-white cursor-pointer'}
                ${isSelected ? 'bg-apple-blue text-white hover:bg-apple-blue' : ''}
                ${isToday(ds) && !isSelected ? 'font-bold text-apple-blue' : ''}
              `}
            >
              {day.getDate()}
            </button>
          )
        })}
      </div>
    </div>
  )
}

// ── Time Slot Picker ──

function TimeSlotPicker({
  slots,
  selected,
  onSelect,
  loading,
}: {
  slots: string[]
  selected: string | null
  onSelect: (time: string) => void
  loading: boolean
}) {
  if (loading) {
    return (
      <div className="flex flex-wrap gap-2 mt-3">
        {[1, 2, 3, 4].map((i) => (
          <div key={i} className="h-9 w-16 skeleton rounded-lg" />
        ))}
      </div>
    )
  }
  if (slots.length === 0) {
    return (
      <p className="text-sm text-apple-gray mt-3">Нет доступных слотов на эту дату</p>
    )
  }
  return (
    <div className="flex flex-wrap gap-2 mt-3">
      {slots.map((time) => (
        <button
          key={time}
          onClick={() => {
            hapticSelection()
            onSelect(time)
          }}
          className={`
            text-sm px-3 py-2 rounded-lg min-h-[36px] transition-all duration-200 font-medium
            ${selected === time
              ? 'bg-apple-blue text-white'
              : 'bg-apple-bg text-apple-text hover:bg-gray-200'
            }
          `}
        >
          {time}
        </button>
      ))}
    </div>
  )
}

// ── Cancel Confirmation Modal ──

function CancelModal({
  booking,
  onConfirm,
  onClose,
  loading,
}: {
  booking: Booking
  onConfirm: () => void
  onClose: () => void
  loading: boolean
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 animate-fade-in">
      <div className="absolute inset-0 bg-black/40 backdrop-blur-sm" onClick={onClose} />
      <div className="relative bg-white rounded-2xl shadow-xl max-w-sm w-full p-6 animate-fade-in">
        <button
          onClick={onClose}
          className="absolute top-4 right-4 p-1 text-apple-gray hover:text-apple-text transition-colors"
        >
          <X size={20} />
        </button>
        <div className="text-center mb-5">
          <div className="w-14 h-14 bg-red-50 rounded-2xl flex items-center justify-center mx-auto mb-4">
            <XCircle size={28} className="text-apple-danger" />
          </div>
          <h3 className="text-lg font-semibold text-apple-text mb-2">Отменить запись?</h3>
          <p className="text-sm text-apple-gray">
            {booking.service_name} - {formatDateRu(booking.date)}, {booking.time}
          </p>
        </div>
        <div className="flex gap-3">
          <button
            onClick={onClose}
            className="flex-1 py-3 rounded-2xl text-sm font-medium bg-apple-bg text-apple-text hover:bg-gray-200 transition-all duration-200 min-h-[44px]"
          >
            Нет, оставить
          </button>
          <button
            onClick={onConfirm}
            disabled={loading}
            className="flex-1 py-3 rounded-2xl text-sm font-medium bg-apple-danger text-white hover:bg-red-600 transition-all duration-200 min-h-[44px] disabled:opacity-50"
          >
            {loading ? 'Отменяем...' : 'Да, отменить'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Reschedule Panel ──

function ReschedulePanel({
  booking,
  onConfirm,
  onClose,
  loading,
}: {
  booking: Booking
  onConfirm: (date: string, time: string) => void
  onClose: () => void
  loading: boolean
}) {
  const [newDate, setNewDate] = useState<string | null>(null)
  const [newTime, setNewTime] = useState<string | null>(null)
  const [slots, setSlots] = useState<string[]>([])
  const [slotsLoading, setSlotsLoading] = useState(false)

  useEffect(() => {
    if (!newDate) {
      setSlots([])
      setNewTime(null)
      return
    }
    setSlotsLoading(true)
    setNewTime(null)
    api
      .getSlots(booking.business_id, booking.service_id, newDate)
      .then((result) => {
        setSlots(result)
      })
      .catch(() => {
        setSlots([])
      })
      .finally(() => {
        setSlotsLoading(false)
      })
  }, [newDate, booking.business_id, booking.service_id])

  return (
    <div className="mt-4 border-t border-apple-border/50 pt-4 animate-fade-in">
      <div className="flex items-center justify-between mb-3">
        <h4 className="text-sm font-semibold text-apple-text">Перенести запись</h4>
        <button
          onClick={onClose}
          className="text-sm text-apple-gray hover:text-apple-text transition-colors"
        >
          Отмена
        </button>
      </div>

      {/* Old vs New comparison */}
      {newDate && newTime && (
        <div className="flex items-center gap-3 mb-4 p-3 bg-apple-bg rounded-xl">
          <div className="flex-1 text-center">
            <p className="text-[11px] text-apple-gray uppercase tracking-wide mb-1">Сейчас</p>
            <p className="text-sm font-medium text-apple-text line-through opacity-60">
              {formatDateShort(booking.date)}, {booking.time}
            </p>
          </div>
          <ChevronRight size={16} className="text-apple-gray" />
          <div className="flex-1 text-center">
            <p className="text-[11px] text-apple-blue uppercase tracking-wide mb-1">Новое</p>
            <p className="text-sm font-medium text-apple-blue">
              {formatDateShort(newDate)}, {newTime}
            </p>
          </div>
        </div>
      )}

      <InlineCalendar selected={newDate} onSelect={setNewDate} />

      {newDate && (
        <div className="mt-3">
          <p className="text-sm font-medium text-apple-text mb-1">Выберите время:</p>
          <TimeSlotPicker
            slots={slots}
            selected={newTime}
            onSelect={setNewTime}
            loading={slotsLoading}
          />
        </div>
      )}

      {newDate && newTime && (
        <button
          onClick={() => onConfirm(newDate, newTime)}
          disabled={loading}
          className="w-full mt-4 py-3 rounded-2xl text-sm font-semibold bg-apple-blue text-white hover:bg-apple-blue-hover transition-all duration-200 min-h-[44px] disabled:opacity-50"
        >
          {loading ? 'Переносим...' : 'Подтвердить перенос'}
        </button>
      )}
    </div>
  )
}

// ── Main Component ──

export function MyBookingsPage() {
  const [bookings, setBookings] = useState<Booking[]>([])
  const [loading, setLoading] = useState(true)
  const [cancellingId, setCancellingId] = useState<number | null>(null)
  const [reschedulingId, setReschedulingId] = useState<number | null>(null)
  const [rescheduleLoading, setRescheduleLoading] = useState(false)
  const [cancelModalBooking, setCancelModalBooking] = useState<Booking | null>(null)

  useEffect(() => {
    api
      .getMyBookings()
      .then(setBookings)
      .catch(() => setBookings([]))
      .finally(() => setLoading(false))
  }, [])

  // Group bookings by date category
  const groupedBookings = useMemo(() => {
    const today: Booking[] = []
    const upcoming: Booking[] = []
    const past: Booking[] = []

    const sorted = [...bookings].sort((a, b) => {
      const dateA = `${a.date}T${a.time}`
      const dateB = `${b.date}T${b.time}`
      return dateA.localeCompare(dateB)
    })

    for (const b of sorted) {
      if (b.status === 'cancelled') {
        past.push(b)
      } else if (isToday(b.date)) {
        today.push(b)
      } else if (isPast(b.date)) {
        past.push(b)
      } else {
        upcoming.push(b)
      }
    }

    return { today, upcoming, past }
  }, [bookings])

  const handleCancel = async (booking: Booking) => {
    setCancelModalBooking(booking)
  }

  const confirmCancel = async () => {
    if (!cancelModalBooking) return
    const id = cancelModalBooking.id
    setCancellingId(id)
    try {
      await api.cancelBooking(id)
      hapticSuccess()
      setBookings((prev) =>
        prev.map((b) => (b.id === id ? { ...b, status: 'cancelled' as const } : b))
      )
    } catch {
      hapticError()
      alert('Не удалось отменить запись. Попробуйте снова.')
    } finally {
      setCancellingId(null)
      setCancelModalBooking(null)
    }
  }

  const handleReschedule = async (bookingId: number, date: string, time: string) => {
    setRescheduleLoading(true)
    try {
      await api.rescheduleBooking(bookingId, date, time)
      hapticSuccess()
      setBookings((prev) =>
        prev.map((b) => (b.id === bookingId ? { ...b, date, time } : b))
      )
      setReschedulingId(null)
    } catch {
      hapticError()
      alert('Не удалось перенести запись. Попробуйте снова.')
      setReschedulingId(null)
    } finally {
      setRescheduleLoading(false)
    }
  }

  // ── Loading state ──
  if (loading) {
    return (
      <div className="max-w-lg mx-auto space-y-4 pb-20">
        <div className="h-8 w-48 skeleton mb-6" />
        {[1, 2, 3].map((i) => (
          <div key={i} className="h-44 skeleton rounded-2xl" />
        ))}
      </div>
    )
  }

  // ── Empty state ──
  if (bookings.length === 0) {
    return (
      <div className="max-w-lg mx-auto pb-20 md:pb-8">
        <h1 className="text-2xl font-bold text-apple-text mb-6">Мои записи</h1>
        <div className="text-center py-20">
          <div className="w-16 h-16 bg-apple-bg rounded-2xl flex items-center justify-center mx-auto mb-4">
            <ClipboardList size={28} className="text-apple-gray" />
          </div>
          <h2 className="text-xl font-semibold text-apple-text mb-2">
            У вас пока нет записей
          </h2>
          <p className="text-apple-gray mb-6">
            Выберите салон и запишитесь на удобное время
          </p>
          <Link
            to="/"
            className="inline-block bg-apple-blue text-white font-medium px-6 py-3 rounded-xl hover:bg-apple-blue-hover transition-all duration-200"
          >
            Найти салон
          </Link>
        </div>
      </div>
    )
  }

  // ── Booking card renderer ──
  const renderBookingCard = (booking: Booking) => {
    const status = statusConfig[(booking as any).status as BookingStatus] || statusConfig.pending
    const StatusIcon = status.icon
    const statusAllowsModify = booking.status === 'confirmed' || booking.status === 'pending'
    const canCancel = booking.can_cancel !== undefined ? booking.can_cancel : statusAllowsModify
    const canReschedule = booking.can_reschedule !== undefined ? booking.can_reschedule : statusAllowsModify
    const canModify = canCancel || canReschedule
    const isRescheduling = reschedulingId === booking.id

    return (
      <div
        key={booking.id}
        className="bg-white rounded-2xl shadow-sm border border-apple-border/50 p-5 transition-all duration-200"
      >
        {/* Header: service + status */}
        <div className="flex items-start justify-between mb-3">
          <div className="flex-1 min-w-0">
            <h3 className="font-semibold text-apple-text truncate">
              {booking.service_name}
            </h3>
            <p className="text-sm text-apple-gray flex items-center gap-1.5 mt-0.5">
              <MapPin size={13} className="shrink-0" />
              <span className="truncate">{booking.business_name}</span>
            </p>
          </div>
          <span
            className={`inline-flex items-center gap-1 text-xs font-medium px-2.5 py-1 rounded-full shrink-0 ml-2 ${status.className}`}
          >
            <StatusIcon size={12} />
            {status.label}
          </span>
        </div>

        {/* Date/time/employee row */}
        <div className="flex items-center gap-4 text-sm text-apple-gray mb-3">
          <span className="flex items-center gap-1.5">
            <Calendar size={14} />
            {formatDateRu(booking.date)}
          </span>
          <span className="flex items-center gap-1.5">
            <Clock size={14} />
            {booking.time}
          </span>
        </div>

        {booking.employee_name && (
          <p className="text-sm text-apple-gray mb-3 flex items-center gap-1.5">
            <User size={14} className="shrink-0" />
            {booking.employee_name}
          </p>
        )}

        {/* Price + actions */}
        <div className="flex items-center justify-between pt-3 border-t border-apple-border/50">
          <span className="font-semibold text-apple-text">
            {booking.price
              ? `${new Intl.NumberFormat('ru-RU').format(booking.price)} \u20BD`
              : ''}
          </span>
          {canModify && (
            <div className="flex items-center gap-3">
              {canReschedule && (
                <button
                  onClick={() => {
                    hapticSelection()
                    setReschedulingId(isRescheduling ? null : booking.id)
                  }}
                  className="text-sm text-apple-blue hover:text-blue-600 font-medium transition-colors flex items-center gap-1 min-h-[44px]"
                >
                  <RefreshCw size={14} />
                  Перенести
                </button>
              )}
              {canCancel && (
                <button
                  onClick={() => handleCancel(booking)}
                  className="text-sm text-apple-danger hover:text-red-600 font-medium transition-colors min-h-[44px]"
                >
                  Отменить
                </button>
              )}
            </div>
          )}
        </div>

        {/* Inline reschedule panel */}
        {isRescheduling && (
          <ReschedulePanel
            booking={booking}
            onConfirm={(date, time) => handleReschedule(booking.id, date, time)}
            onClose={() => setReschedulingId(null)}
            loading={rescheduleLoading}
          />
        )}
      </div>
    )
  }

  // ── Section renderer ──
  const renderSection = (title: string, items: Booking[], _defaultOpen = true) => {
    if (items.length === 0) return null
    return (
      <div className="mb-6">
        <h2 className="text-sm font-semibold text-apple-gray uppercase tracking-wide mb-3">
          {title}
        </h2>
        <div className="space-y-4">
          {items.map(renderBookingCard)}
        </div>
      </div>
    )
  }

  return (
    <div className="max-w-lg mx-auto pb-20 md:pb-8">
      <h1 className="text-2xl font-bold text-apple-text mb-6">Мои записи</h1>

      {renderSection('Сегодня', groupedBookings.today)}
      {renderSection('Предстоящие', groupedBookings.upcoming)}
      {renderSection('Прошедшие', groupedBookings.past, false)}

      {/* Cancel confirmation modal */}
      {cancelModalBooking && (
        <CancelModal
          booking={cancelModalBooking}
          onConfirm={confirmCancel}
          onClose={() => setCancelModalBooking(null)}
          loading={cancellingId === cancelModalBooking.id}
        />
      )}
    </div>
  )
}
