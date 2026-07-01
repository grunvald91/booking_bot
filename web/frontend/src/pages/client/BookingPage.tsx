import { useState, useEffect, useMemo, useRef, Component, type ReactNode } from 'react'
import { useParams, useSearchParams, useNavigate, Link } from 'react-router-dom'
import { ClientShell } from '../../components/ClientShell'
import './booking.css'

// Защита от белого экрана: если в success-рендере что-то падает,
// клиент должен увидеть хоть какое-то сообщение, а не пустоту.
class SuccessErrorBoundary extends Component<{ children: ReactNode; bookingId?: number | null; notifyToken?: string | null }, { error: Error | null }> {
  state: { error: Error | null } = { error: null }
  static getDerivedStateFromError(error: Error) { return { error } }
  componentDidCatch(error: Error) {
    try { console.error('Booking success render crashed:', error) } catch {}
  }
  render() {
    if (this.state.error) {
      const publicUrl = this.props.notifyToken
        ? `${window.location.origin}/b/${this.props.notifyToken}`
        : null
      return (
        <div className="bk-fallback">
          <div className="bk-fallback-icon is-ok">✅</div>
          <h2 className="ds-h1">Запись создана</h2>
          <p className="ds-sub bk-fallback-sub">
            Бронь сохранена{this.props.bookingId ? ` (№${this.props.bookingId})` : ''}. Подробности и статус доступны по ссылке.
          </p>
          {publicUrl && (
            <a href={publicUrl} className="ds-btn ds-btn--primary" style={{ marginBottom: 12 }}>
              Открыть страницу брони
            </a>
          )}
          <Link to="/" className="ds-accent" style={{ fontSize: 13, textDecoration: 'underline' }}>На главную</Link>
        </div>
      )
    }
    return this.props.children
  }
}
import {
  Calendar,
  Clock,
  CheckCircle,
  ChevronLeft,
  ChevronRight,
  ChevronDown,
  Scissors,
  User,
  Plus,
  Minus,
  Check,
  DoorOpen,
  Music,
  Users,
  UserCheck,
  Package,
  CreditCard,
  MapPin,
  Navigation,
  Paperclip,
} from 'lucide-react'
import {
  api,
  type Service,
  type EmployeeWithPricing,
  type BusinessDetail,
  type CalculatePriceResponse,
} from '../../api/client'
import { getTelegramUser } from '../../utils/telegram'

// ── Helpers ──

function formatPrice(price?: number | null, isHourly?: boolean) {
  if (price == null) return '\u2014'
  const formatted = new Intl.NumberFormat('ru-RU').format(price)
  return isHourly ? `${formatted} \u20BD/\u0447` : `${formatted} \u20BD`
}

function formatDuration(minutes?: number | null) {
  if (!minutes || minutes <= 0) return ''
  if (minutes < 60) return `${minutes} \u043C\u0438\u043D`
  const h = Math.floor(minutes / 60)
  const m = minutes % 60
  return m ? `${h} \u0447 ${m} \u043C\u0438\u043D` : `${h} \u0447`
}

function getRoomPriceRange(room: EmployeeWithPricing): string {
  if (!room.time_pricing || room.time_pricing.length === 0) return ''
  const prices = room.time_pricing.map((tp) => tp.price_per_hour)
  const min = Math.min(...prices)
  const max = Math.max(...prices)
  if (min === max) return formatPrice(min, true)
  return `${new Intl.NumberFormat('ru-RU').format(min)}\u2013${new Intl.NumberFormat('ru-RU').format(max)} \u20BD/\u0447`
}

function parsePhotos(raw?: string | null): string[] {
  if (!raw) return []
  try {
    const parsed = JSON.parse(raw)
    if (Array.isArray(parsed)) return parsed.filter((v): v is string => typeof v === 'string')
  } catch {
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

const DAYS_RU = ['\u0412\u0441', '\u041F\u043D', '\u0412\u0442', '\u0421\u0440', '\u0427\u0442', '\u041F\u0442', '\u0421\u0431']
const MONTHS_RU = [
  '\u042F\u043D\u0432\u0430\u0440\u044C', '\u0424\u0435\u0432\u0440\u0430\u043B\u044C', '\u041C\u0430\u0440\u0442',
  '\u0410\u043F\u0440\u0435\u043B\u044C', '\u041C\u0430\u0439', '\u0418\u044E\u043D\u044C',
  '\u0418\u044E\u043B\u044C', '\u0410\u0432\u0433\u0443\u0441\u0442', '\u0421\u0435\u043D\u0442\u044F\u0431\u0440\u044C',
  '\u041E\u043A\u0442\u044F\u0431\u0440\u044C', '\u041D\u043E\u044F\u0431\u0440\u044C', '\u0414\u0435\u043A\u0430\u0431\u0440\u044C',
]

function formatDateRu(dateStr: string) {
  const d = new Date(dateStr)
  return `${d.getDate()} ${MONTHS_RU[d.getMonth()].toLowerCase()}, ${DAYS_RU[d.getDay()]}`
}

// ── Calendar ──

function CalendarPicker({
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
    <div className="ds-card bk-cal">
      <div className="bk-cal-head">
        <button
          onClick={prevMonth}
          className="bk-cal-nav"
          aria-label="Предыдущий месяц"
        >
          <ChevronLeft size={20} />
        </button>
        <h3>
          {MONTHS_RU[currentMonth.getMonth()]} {currentMonth.getFullYear()}
        </h3>
        <button
          onClick={nextMonth}
          className="bk-cal-nav"
          aria-label="Следующий месяц"
        >
          <ChevronRight size={20} />
        </button>
      </div>

      <div className="bk-cal-weekdays">
        {['\u041F\u043D', '\u0412\u0442', '\u0421\u0440', '\u0427\u0442', '\u041F\u0442', '\u0421\u0431', '\u0412\u0441'].map((d) => (
          <span key={d}>{d}</span>
        ))}
      </div>

      <div className="bk-cal-days">
        {days.map((day, idx) => {
          if (!day) return <div key={`empty-${idx}`} />
          const dateStr = `${day.getFullYear()}-${String(day.getMonth() + 1).padStart(2, '0')}-${String(day.getDate()).padStart(2, '0')}`
          const isPast = day < new Date(today.getFullYear(), today.getMonth(), today.getDate())
          const isSelected = selected === dateStr
          const isToday =
            day.getDate() === today.getDate() &&
            day.getMonth() === today.getMonth() &&
            day.getFullYear() === today.getFullYear()

          return (
            <button
              key={dateStr}
              disabled={isPast}
              onClick={() => onSelect(dateStr)}
              className={`bk-cal-day ${isSelected ? 'is-selected' : isToday ? 'is-today' : ''}`}
            >
              {day.getDate()}
            </button>
          )
        })}
      </div>
    </div>
  )
}

// ── Helper: scroll into view ──
function scrollToRef(ref: React.RefObject<HTMLDivElement | null>, delay = 300) {
  setTimeout(() => {
    ref.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }, delay)
}

// ── Section header ──
function SectionHeader({ icon, title, subtitle }: { icon: React.ReactNode; title: string; subtitle?: string }) {
  return (
    <>
      <div className="bk-section-head">
        <span className="ico">{icon}</span>
        <h2 className="ds-h2">{title}</h2>
      </div>
      {subtitle && <p className="ds-sub bk-section-sub">{subtitle}</p>}
      {!subtitle && <div className="bk-section-sub" />}
    </>
  )
}

// ── Main Component ──

function BookingPageInner() {
  const { businessId } = useParams<{ businessId: string }>()
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()

  const preselectedServiceId = searchParams.get('service')
    ? Number(searchParams.get('service'))
    : null
  const preselectedEmployeeId = searchParams.get('employee')
    ? Number(searchParams.get('employee'))
    : null

  // Business data
  const [business, setBusiness] = useState<BusinessDetail | null>(null)
  const [services, setServices] = useState<Service[]>([])
  const [additionalServices, setAdditionalServices] = useState<Service[]>([])
  const [employees, setEmployees] = useState<EmployeeWithPricing[]>([])

  // Selections
  const [selectedRoom, setSelectedRoom] = useState<EmployeeWithPricing | null>(null)
  const [selectedServices, setSelectedServices] = useState<Service[]>([])
  const [selectedService, setSelectedService] = useState<Service | null>(null)
  const [selectedEmployee, setSelectedEmployee] = useState<EmployeeWithPricing | null>(null)
  const [selectedDate, setSelectedDate] = useState<string | null>(null)
  const [selectedTime, setSelectedTime] = useState<string | null>(null)
  const [isSoloPricing, setIsSoloPricing] = useState(false)
  const [selectedAddons, setSelectedAddons] = useState<Set<number>>(new Set())
  const [addonHours, setAddonHours] = useState<Record<number, number>>({})

  // Price
  const [priceData, setPriceData] = useState<CalculatePriceResponse | null>(null)
  const [priceLoading, setPriceLoading] = useState(false)

  // Slots
  const [slots, setSlots] = useState<string[]>([])
  const [loadingSlots, setLoadingSlots] = useState(false)

  // Form
  const tgUser = getTelegramUser()
  const [clientName, setClientName] = useState(
    tgUser ? [tgUser.first_name, tgUser.last_name].filter(Boolean).join(' ') : ''
  )
  const [clientPhone, setClientPhone] = useState(() => {
    return localStorage.getItem('clientPhone') || ''
  })
  const [comment, setComment] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [success, setSuccess] = useState(false)
  const [bookingError, setBookingError] = useState<string | null>(null)
  const [createdBookingId, setCreatedBookingId] = useState<number | null>(null)
  const [createdNotifyToken, setCreatedNotifyToken] = useState<string | null>(null)
  const [paymentSent, setPaymentSent] = useState(false)
  const [receiptUploading, setReceiptUploading] = useState(false)
  const [receiptUploaded, setReceiptUploaded] = useState(false)
  const receiptInputRef = useRef<HTMLInputElement>(null)
  const [pendingReceipt, setPendingReceipt] = useState<File | null>(null)
  const [pendingReceiptPreview, setPendingReceiptPreview] = useState<string | null>(null)
  const [receiptError, setReceiptError] = useState<string | null>(null)

  // Auto-skip toast
  const [skipToast, setSkipToast] = useState<string | null>(null)
  useEffect(() => {
    if (!skipToast) return
    const t = setTimeout(() => setSkipToast(null), 1200)
    return () => clearTimeout(t)
  }, [skipToast])

  function flashAutoPick(label: string, scrollRef?: React.RefObject<HTMLDivElement | null>) {
    setSkipToast(label)
    if (scrollRef) {
      // Дать клиенту увидеть toast 0.8с, потом проскроллить дальше
      setTimeout(() => scrollToRef(scrollRef, 0), 800)
    }
  }

  // Section refs for auto-scroll
  const refService = useRef<HTMLDivElement>(null)
  const refEmployee = useRef<HTMLDivElement>(null)
  const refRoom = useRef<HTMLDivElement>(null)
  const refVenueServices = useRef<HTMLDivElement>(null)
  const refDate = useRef<HTMLDivElement>(null)
  const refTime = useRef<HTMLDivElement>(null)
  const refFormat = useRef<HTMLDivElement>(null)
  const refAddons = useRef<HTMLDivElement>(null)
  const refConfirm = useRef<HTMLDivElement>(null)
  // Inputs (для скролла/фокуса при валидации)
  const nameInputRef = useRef<HTMLInputElement>(null)
  const phoneInputRef = useRef<HTMLInputElement>(null)
  // Подсветка пустых полей после попытки отправки
  const [fieldErrors, setFieldErrors] = useState<{ name?: boolean; phone?: boolean }>({})

  // Auto-fill phone (и префилл +7 9 если ничего не нашлось)
  useEffect(() => {
    if (clientPhone) return
    const token = localStorage.getItem('token')
    const setPrefillFallback = () => {
      // Префиксы РФ-номера, чтобы клиенту не вводить лишнее
      setClientPhone((v) => v || '+7 9')
    }
    if (token) {
      api.getMe().then((user) => {
        if (user?.phone) {
          setClientPhone(user.phone)
          localStorage.setItem('clientPhone', user.phone)
        } else {
          setPrefillFallback()
        }
      }).catch(() => setPrefillFallback())
    } else {
      setPrefillFallback()
    }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const isVenue = business?.business_type === 'venue_rental'

  // Load business data
  useEffect(() => {
    const bizId = Number(businessId)
    api
      .getBusiness(bizId)
      .then((biz: BusinessDetail) => {
        setBusiness(biz)
        setServices(biz.services.filter((s: Service) => s.is_active && !s.is_additional))
        setAdditionalServices(biz.services.filter((s: Service) => s.is_active && s.is_additional))
        setEmployees(biz.employees || [])
        if (preselectedServiceId) {
          const found = biz.services.find((s: Service) => s.id === preselectedServiceId)
          if (found) {
            if (biz.business_type === 'venue_rental') {
              setSelectedServices([found])
            } else {
              setSelectedService(found)
            }
          }
        }
        if (preselectedEmployeeId) {
          const emp = (biz.employees || []).find((e) => e.id === preselectedEmployeeId)
          if (emp) {
            if (biz.business_type === 'venue_rental') {
              setSelectedRoom(emp)
            } else {
              setSelectedEmployee(emp)
            }
          }
        }
      })
      .catch(() => {})
  }, [businessId, preselectedServiceId, preselectedEmployeeId])

  // Total duration
  const totalDuration = useMemo(() => {
    if (isVenue) {
      return selectedServices.reduce((sum, s) => sum + (s.duration_minutes ?? 0), 0)
    }
    return selectedService?.duration_minutes ?? 60
  }, [isVenue, selectedServices, selectedService])

  // Load slots
  useEffect(() => {
    if (!selectedDate || !businessId) return
    const serviceId = isVenue
      ? (selectedServices[0]?.id ?? 0)
      : (selectedService?.id ?? 0)
    if (!serviceId) return

    setLoadingSlots(true)
    api
      .getSlots(Number(businessId), serviceId, selectedDate)
      .then(setSlots)
      .catch(() => setSlots([]))
      .finally(() => setLoadingSlots(false))
  }, [businessId, selectedDate, isVenue, selectedServices, selectedService])

  // Auto-pick when single option (F2)
  // 1) Non-venue: единственная услуга
  useEffect(() => {
    if (isVenue) return
    if (selectedService) return
    if (services.length === 1) {
      const only = services[0]
      setSelectedService(only)
      flashAutoPick(`Услуга: ${only.name}`, refDate)
    }
  }, [isVenue, services, selectedService])

  // 2) Non-venue: единственный мастер (после выбора даты)
  useEffect(() => {
    if (isVenue) return
    if (!selectedDate) return
    if (selectedEmployee) return
    if (employees.length === 1) {
      const only = employees[0]
      setSelectedEmployee(only)
      flashAutoPick(`Специалист: ${only.name}`, refTime)
    }
  }, [isVenue, selectedDate, employees, selectedEmployee])

  // 3) Venue: единственное помещение
  useEffect(() => {
    if (!isVenue) return
    if (selectedRoom) return
    if (employees.length === 1) {
      const only = employees[0]
      setSelectedRoom(only)
      flashAutoPick(`Помещение: ${only.name}`, refDate)
    }
  }, [isVenue, employees, selectedRoom])

  // 4) Единственный слот времени
  useEffect(() => {
    if (!selectedDate) return
    if (selectedTime) return
    if (slots.length === 1) {
      const only = slots[0]
      setSelectedTime(only)
      flashAutoPick(`Время: ${only}`, refConfirm)
    }
  }, [selectedDate, slots, selectedTime])

  // Calculate price for venue
  useEffect(() => {
    if (!isVenue || !selectedRoom || !selectedTime || !businessId || totalDuration <= 0) {
      setPriceData(null)
      return
    }
    setPriceLoading(true)
    api
      .calculatePrice(
        Number(businessId),
        selectedRoom.id,
        selectedTime,
        totalDuration,
        selectedDate || undefined
      )
      .then(setPriceData)
      .catch(() => setPriceData(null))
      .finally(() => setPriceLoading(false))
  }, [isVenue, selectedRoom, selectedTime, totalDuration, businessId, selectedDate])

  // Addon total
  const addonTotal = useMemo(() => {
    let total = 0
    additionalServices.forEach((svc) => {
      if (!selectedAddons.has(svc.id)) return
      const base = svc.price ?? 0
      if (svc.is_hourly_price) {
        total += base * (addonHours[svc.id] ?? 1)
      } else {
        total += base
      }
    })
    return total
  }, [additionalServices, selectedAddons, addonHours])

  // Total price
  const totalPrice = useMemo(() => {
    if (isVenue) {
      if (isSoloPricing && selectedRoom?.solo_price_per_hour) {
        const hours = Math.max(1, totalDuration / 60)
        return selectedRoom.solo_price_per_hour * hours + addonTotal
      }
      const basePrice = (priceData?.has_time_price && priceData?.total)
        ? priceData.total
        : selectedServices.reduce((sum, s) => sum + (s.price ?? 0), 0)
      return basePrice + addonTotal
    }
    const servicePrice = selectedService?.price ?? 0
    return servicePrice + addonTotal
  }, [isVenue, isSoloPricing, selectedRoom, totalDuration, priceData, addonTotal, selectedService, selectedServices])

  // Addon toggle
  const toggleAddon = (svcId: number) => {
    setSelectedAddons((prev) => {
      const next = new Set(prev)
      if (next.has(svcId)) {
        next.delete(svcId)
      } else {
        next.add(svcId)
      }
      return next
    })
  }

  const setAddonHourCount = (svcId: number, hours: number) => {
    setAddonHours((prev) => ({ ...prev, [svcId]: Math.max(1, hours) }))
  }

  // Список незаполненного для подсказки над кнопкой
  const missingFields = useMemo(() => {
    const list: string[] = []
    if (!clientName.trim()) list.push('имя')
    if (!clientPhone.trim()) list.push('телефон')
    return list
  }, [clientName, clientPhone])

  // F1: business cover photo (first photo if any) — useMemo ОБЯЗАТЕЛЬНО до if(success) return,
  // иначе разное число хуков между рендерами → React error #300.
  const businessCover = useMemo(() => {
    const ids = parsePhotos(business?.photos)
    return ids[0] ?? null
  }, [business?.photos])

  // Submit
  const handleSubmit = async () => {
    if (!selectedDate || !selectedTime || !businessId) return

    // Валидация контактов: подсветить пустые поля и проскроллить к первому
    const errs: { name?: boolean; phone?: boolean } = {}
    if (!clientName.trim()) errs.name = true
    if (!clientPhone.trim()) errs.phone = true
    if (errs.name || errs.phone) {
      setFieldErrors(errs)
      setBookingError(
        `Заполните: ${[errs.name && 'имя', errs.phone && 'телефон'].filter(Boolean).join(' и ')}`
      )
      const target = errs.name ? nameInputRef.current : phoneInputRef.current
      target?.scrollIntoView({ behavior: 'smooth', block: 'center' })
      setTimeout(() => target?.focus(), 350)
      return
    }
    setFieldErrors({})

    setSubmitting(true)
    setBookingError(null)
    try {
      const serviceIds = isVenue
        ? selectedServices.map((s) => s.id)
        : selectedService
          ? [selectedService.id]
          : []

      const additionalServiceIds = Array.from(selectedAddons)
      const additionalServiceHoursMap: Record<string, number> = {}
      additionalServiceIds.forEach((id) => {
        const svc = additionalServices.find((s) => s.id === id)
        if (svc?.is_hourly_price) {
          additionalServiceHoursMap[String(id)] = addonHours[id] ?? 1
        }
      })

      if (clientPhone) localStorage.setItem('clientPhone', clientPhone)

      const result = await api.createBooking({
        business_id: Number(businessId),
        service_ids: serviceIds,
        additional_service_ids: additionalServiceIds.length > 0 ? additionalServiceIds : undefined,
        additional_service_hours: Object.keys(additionalServiceHoursMap).length > 0 ? additionalServiceHoursMap : undefined,
        is_solo_booking: isVenue && isSoloPricing ? true : undefined,
        employee_id: isVenue ? selectedRoom?.id : selectedEmployee?.id,
        date: selectedDate,
        time: selectedTime,
        client_name: clientName,
        client_phone: clientPhone,
        notes: comment || undefined,
      })
      const firstResult: any = Array.isArray(result) && result.length > 0
        ? result[0]
        : (result && typeof result === 'object' && 'id' in result ? result : null)
      if (firstResult) {
        setCreatedBookingId(firstResult.id)
        setCreatedNotifyToken(firstResult.notify_token ?? null)
        // Сохранить бронь в "Мои брони" для возврата без логина
        if (firstResult.notify_token) {
          try {
            const raw = localStorage.getItem('myBookings') || '[]'
            const arr = JSON.parse(raw)
            const list = Array.isArray(arr) ? arr : []
            const entry = {
              token: firstResult.notify_token,
              business: firstResult.business_name || business?.name || '',
              date: firstResult.date || selectedDate || '',
              time: firstResult.time || selectedTime || '',
              saved_at: Date.now(),
            }
            const idx = list.findIndex((x: any) => x?.token === entry.token)
            if (idx >= 0) list[idx] = entry
            else list.unshift(entry)
            localStorage.setItem('myBookings', JSON.stringify(list.slice(0, 20)))
          } catch {}
        }
      }
      setBookingError(null)
      setSuccess(true)
    } catch (err: any) {
      console.error('Booking creation error:', err)
      const msg = err?.message || ''
      if (msg.includes('409') || msg.includes('already taken')) {
        setBookingError('Это время уже занято. Выберите другое время.')
      } else {
        setBookingError('Не удалось создать запись. Попробуйте ещё раз.')
      }
    } finally {
      setSubmitting(false)
    }
  }

  // Summary helpers
  const selectedRoomOrEmployee = isVenue ? selectedRoom : selectedEmployee
  const mainServiceLabel = isVenue
    ? selectedServices.map((s) => s.name).join(', ')
    : selectedService?.name ?? ''

  // ── Visibility conditions ──
  // Order: Services → Date → Employee/Room → Time → ...
  const showDateSection = isVenue
    ? selectedServices.length > 0
    : !!selectedService
  const showEmployeeSection = !isVenue && employees.length > 0 && !!selectedDate
  const showRoomSection = isVenue && selectedServices.length > 0 && !!selectedDate
  const showTimeSection = isVenue
    ? (!!selectedDate && !!selectedRoom)
    : (!!selectedDate && !!selectedService)
  const showFormatSection = isVenue && !!selectedTime && !!selectedRoom?.solo_price_per_hour
  const showAddonsSection = !!selectedTime && additionalServices.length > 0
  const showConfirmSection = isVenue
    ? (!!selectedRoom && selectedServices.length > 0 && !!selectedDate && !!selectedTime)
    : (!!selectedService && !!selectedDate && !!selectedTime)

  // Next ref for the floating "Далее" button: the next required step that's
  // not satisfied yet. Returns null when nothing is selected (button hidden)
  // and when the user is already at the confirmation section.
  const nextRef = (() => {
    if (isVenue) {
      if (selectedServices.length === 0) return null
      if (!selectedDate) return refDate
      if (!selectedRoom) return refRoom
      if (!selectedTime) return refTime
      if (selectedRoom?.solo_price_per_hour && !showConfirmSection) return refFormat
      return null  // confirm already visible — sticky inline button handles it
    }
    if (!selectedService) return null
    if (!selectedDate) return refDate
    if (!selectedTime) return refTime
    return null
  })()

  // ── Success screen ──

  if (success) {
    const prepaymentEnabled = business?.prepayment_enabled
    const prepaymentPercent = business?.prepayment_percent ?? 100
    const paymentPhone = business?.payment_phone
    const paymentDetails = business?.payment_details
    const cancellationPolicyPhoto = business?.cancellation_policy_photo
    const cancellationPolicyText = business?.cancellation_policy_text
    const prepaymentAmount = totalPrice > 0 ? Math.ceil(totalPrice * prepaymentPercent / 100) : 0

    const handlePaymentSent = async () => {
      try {
        // QR-клиент без логина в Telegram → шлём по notify_token (без auth).
        // Залогиненный клиент — по id брони.
        if (createdNotifyToken) {
          await api.prepaymentSentByToken(createdNotifyToken)
        } else if (createdBookingId) {
          await api.prepaymentSent(createdBookingId)
        } else {
          return
        }
        setPaymentSent(true)
        // Сразу перебрасываем клиента на публичную страницу брони —
        // там поллинг и обновление статуса при подтверждении владельцем.
        if (createdNotifyToken) {
          navigate(`/b/${createdNotifyToken}`)
        }
      } catch {
        setPaymentSent(true)
      }
    }

    return (
      <ClientShell backTo={`/business/${businessId}`} title={business?.name ?? 'Запись'}>
       <SuccessErrorBoundary bookingId={createdBookingId} notifyToken={createdNotifyToken}>
        <div className="bk-success bk-fade-in">
          <div className={`bk-success-icon ${prepaymentEnabled && totalPrice > 0 ? 'is-pending' : 'is-done'}`}>
            {prepaymentEnabled && totalPrice > 0 ? (
              <Clock size={40} />
            ) : (
              <CheckCircle size={40} />
            )}
          </div>
          <h2 className="ds-h1">
            {prepaymentEnabled && totalPrice > 0
              ? 'Запись ожидает предоплаты'
              : 'Запись создана!'}
          </h2>
          <p className="ds-sub bk-success-sub">
            {prepaymentEnabled && totalPrice > 0 ? (
              <>
                {mainServiceLabel}, {selectedDate && formatDateRu(selectedDate)} в{' '}
                {selectedTime}
                {selectedRoomOrEmployee && ` \u00B7 ${selectedRoomOrEmployee.name}`}
                {'. Оплатите предоплату для подтверждения.'}
              </>
            ) : (
              <>
                {mainServiceLabel}, {selectedDate && formatDateRu(selectedDate)} в{' '}
                {selectedTime}
                {selectedRoomOrEmployee && ` \u00B7 ${selectedRoomOrEmployee.name}`}
              </>
            )}
          </p>
          <div className="ds-card bk-success-card">
            <div>
              <div className="bk-success-row">
                <span className="lbl">{isVenue ? 'Зал' : 'Услуга'}</span>
                <span className="val">
                  {isVenue ? selectedRoom?.name : selectedService?.name}
                </span>
              </div>
              {isVenue && selectedServices.length > 0 && (
                <div className="bk-success-row">
                  <span className="lbl">Услуги</span>
                  <span className="val">
                    {selectedServices.map((s) => s.name).join(', ')}
                  </span>
                </div>
              )}
              {!isVenue && selectedEmployee && (
                <div className="bk-success-row">
                  <span className="lbl">Специалист</span>
                  <span className="val">{selectedEmployee.name}</span>
                </div>
              )}
              <div className="bk-success-row">
                <span className="lbl">Дата и время</span>
                <span className="val">
                  {selectedDate && formatDateRu(selectedDate)}, {selectedTime}
                </span>
              </div>
              {business?.address && (
                <div className="bk-success-row">
                  <span className="lbl">Адрес</span>
                  <a
                    href={`https://yandex.ru/maps/?text=${encodeURIComponent(business.address)}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="ds-accent val"
                    style={{ textDecoration: 'underline' }}
                  >
                    {business.address}
                  </a>
                </div>
              )}
              {totalPrice > 0 && (
                <div className="bk-success-row total">
                  <span className="lbl">Итого</span>
                  <span className="val">{formatPrice(totalPrice)}</span>
                </div>
              )}
            </div>
          </div>

          {/* Bot subscribe — чтобы анонимный web-клиент мог получать уведомления о подтверждении */}
          {createdNotifyToken && (
            <a
              href={`https://t.me/Sochiservice_bot?start=notify_${createdNotifyToken}`}
              target="_blank"
              rel="noopener noreferrer"
              className="bk-bot-link"
            >
              <span className="t1">📲 Получать уведомления в Telegram</span>
              <span className="t2">
                Открыть бота, чтобы узнавать о подтверждении{prepaymentEnabled ? ' предоплаты' : ' записи'} и напоминаниях
              </span>
            </a>
          )}

          {/* Directions on success screen */}
          {business?.directions && (
            <div className="ds-card bk-directions-card">
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
                <Navigation size={15} className="ds-accent" />
                <h3 className="ds-h3">Как добраться</h3>
              </div>
              <p className="ds-sub" style={{ whiteSpace: 'pre-line', lineHeight: 1.6 }}>
                {linkifyText(business.directions)}
              </p>
            </div>
          )}

          {/* Prepayment block */}
          {prepaymentEnabled && totalPrice > 0 && (
            <div className="bk-prepay">
              <div className="bk-prepay-box">
                <div className="bk-prepay-head">
                  <CreditCard size={20} />
                  <h3>
                    Для подтверждения записи необходима предоплата
                  </h3>
                </div>
                <div>
                  <div className="bk-prepay-row">
                    <span>Сумма</span>
                    <span className="val">{formatPrice(prepaymentAmount)}</span>
                  </div>
                  {paymentPhone && (
                    <div className="bk-prepay-row">
                      <span>Телефон для оплаты</span>
                      <span className="val">{paymentPhone}</span>
                    </div>
                  )}
                  {paymentDetails && (
                    <div className="bk-prepay-row">
                      <span>Реквизиты</span>
                      <span className="val">{paymentDetails}</span>
                    </div>
                  )}
                </div>
                {cancellationPolicyText ? (
                  <div className="bk-cancel-policy">
                    <p>{'\u26A0\uFE0F Условия отмены'}</p>
                    <p>{cancellationPolicyText}</p>
                  </div>
                ) : cancellationPolicyPhoto ? (
                  <div className="bk-cancel-policy">
                    <img
                      src={'/api/telegram-photo/' + encodeURIComponent(cancellationPolicyPhoto)}
                      alt="Условия отмены"
                    />
                  </div>
                ) : null}
                <div className="bk-prepay-actions">
                  {paymentSent || receiptUploaded ? (
                    <div className="bk-prepay-done">
                      <CheckCircle size={24} className="ico" />
                      <p className="t1">
                        {receiptUploaded ? 'Чек отправлен владельцу' : 'Владелец уведомлён'}
                      </p>
                      <p className="t2">
                        Ожидайте подтверждения оплаты. Вам придёт уведомление.
                      </p>
                    </div>
                  ) : (
                    <>
                      <input
                        ref={receiptInputRef}
                        type="file"
                        accept="image/*,.pdf,application/pdf"
                        style={{ display: 'none' }}
                        onChange={(e) => {
                          const file = e.target.files?.[0]
                          if (!file) return
                          setReceiptError(null)
                          // Очистить старое превью
                          if (pendingReceiptPreview) URL.revokeObjectURL(pendingReceiptPreview)
                          setPendingReceipt(file)
                          const isImage = file.type.startsWith('image/')
                          setPendingReceiptPreview(isImage ? URL.createObjectURL(file) : null)
                          // Сброс input value чтобы повторный выбор того же файла триггерил onChange
                          e.target.value = ''
                        }}
                      />

                      {/* F3: превью + 3 кнопки (Отправить / Заменить / Удалить) */}
                      {pendingReceipt ? (
                        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                          <div className="bk-receipt-preview">
                            {pendingReceiptPreview ? (
                              <img
                                src={pendingReceiptPreview}
                                alt="Превью чека"
                              />
                            ) : (
                              <div className="bk-receipt-file">
                                <div className="bk-receipt-file-ico">
                                  <Paperclip size={20} />
                                </div>
                                <div style={{ minWidth: 0, flex: 1 }}>
                                  <p className="bk-receipt-file-name">{pendingReceipt.name}</p>
                                  <p className="bk-receipt-file-meta">
                                    {(pendingReceipt.size / 1024).toFixed(0)} КБ · {pendingReceipt.type || 'файл'}
                                  </p>
                                </div>
                              </div>
                            )}
                            <p className="bk-receipt-hint">
                              Проверьте, что файл правильный — затем отправьте
                            </p>
                          </div>

                          {receiptError && (
                            <p className="bk-receipt-error">{receiptError}</p>
                          )}

                          <button
                            onClick={async () => {
                              if (!pendingReceipt) return
                              if (!createdNotifyToken && !createdBookingId) return
                              setReceiptError(null)
                              setReceiptUploading(true)
                              try {
                                if (createdNotifyToken) {
                                  // QR-клиент без auth — публичный endpoint по токену.
                                  await api.uploadReceiptByToken(createdNotifyToken, pendingReceipt)
                                } else if (createdBookingId) {
                                  await api.uploadReceipt(createdBookingId, pendingReceipt)
                                }
                                setReceiptUploaded(true)
                                if (pendingReceiptPreview) URL.revokeObjectURL(pendingReceiptPreview)
                                setPendingReceipt(null)
                                setPendingReceiptPreview(null)
                                // Перебрасываем на публичную страницу брони — там поллинг
                                // и при подтверждении владельцем статус обновится сам.
                                if (createdNotifyToken) {
                                  navigate(`/b/${createdNotifyToken}`)
                                }
                              } catch (err) {
                                setReceiptError('Не удалось отправить чек. Попробуйте ещё раз.')
                              } finally {
                                setReceiptUploading(false)
                              }
                            }}
                            disabled={receiptUploading}
                            className="ds-btn ds-btn--primary ds-btn--block"
                          >
                            {receiptUploading ? (
                              <>
                                <span className="bk-spinner" />
                                Отправка...
                              </>
                            ) : (
                              <>
                                <CheckCircle size={18} />
                                Отправить чек
                              </>
                            )}
                          </button>

                          <div className="bk-receipt-actions-2">
                            <button
                              onClick={() => receiptInputRef.current?.click()}
                              disabled={receiptUploading}
                              className="ds-btn ds-btn--ghost ds-btn--sm"
                            >
                              <Paperclip size={15} />
                              Заменить
                            </button>
                            <button
                              onClick={() => {
                                if (pendingReceiptPreview) URL.revokeObjectURL(pendingReceiptPreview)
                                setPendingReceipt(null)
                                setPendingReceiptPreview(null)
                                setReceiptError(null)
                              }}
                              disabled={receiptUploading}
                              className="ds-btn ds-btn--ghost ds-btn--sm"
                              style={{ color: 'var(--s-danger)', borderColor: 'var(--s-danger)' }}
                            >
                              Удалить
                            </button>
                          </div>
                        </div>
                      ) : (
                        <button
                          onClick={() => receiptInputRef.current?.click()}
                          disabled={!createdBookingId}
                          className="ds-btn ds-btn--primary ds-btn--block"
                        >
                          <Paperclip size={18} />
                          Прикрепить чек
                        </button>
                      )}
                      {!business?.require_receipt_for_prepayment && (
                        <button
                          onClick={handlePaymentSent}
                          disabled={!createdBookingId}
                          className="ds-btn ds-btn--block"
                          style={{ background: 'var(--s-success)', color: '#fff' }}
                        >
                          {'Оплата отправлена \u2713'}
                        </button>
                      )}
                    </>
                  )}
                </div>
              </div>
            </div>
          )}

          {/* F-bonus: сохранить ссылку на публичную страницу брони (без TG) — в самом низу */}
          {createdNotifyToken && (() => {
            const publicUrl = `${window.location.origin}/b/${createdNotifyToken}`
            const copy = async () => {
              try { await navigator.clipboard.writeText(publicUrl) } catch {}
            }
            return (
              <div className="ds-card bk-save-link">
                <div className="bk-save-link-title">📌 Сохранить страницу брони</div>
                <p className="bk-save-link-hint">
                  Откройте позже, чтобы видеть статус и инструкции владельца. Без Telegram.
                </p>
                <div className="bk-save-link-url">
                  {publicUrl}
                </div>
                <div className="bk-save-link-actions">
                  <button
                    onClick={copy}
                    className="ds-btn ds-btn--primary ds-btn--sm"
                  >
                    Скопировать
                  </button>
                  <a
                    href={publicUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="ds-btn ds-btn--ghost ds-btn--sm"
                  >
                    Открыть ↗
                  </a>
                </div>
              </div>
            )
          })()}

          <div className="bk-success-actions">
            <button
              onClick={() => navigate(`/business/${businessId}`)}
              className="ds-btn ds-btn--ghost"
            >
              К бизнесу
            </button>
            <button
              onClick={() => navigate('/')}
              className="ds-btn ds-btn--primary"
            >
              На главную
            </button>
          </div>
        </div>
       </SuccessErrorBoundary>
      </ClientShell>
    )
  }

  // ── Main render — single long page ──

  return (
    <ClientShell backTo={`/business/${businessId}`} title={business?.name ?? 'Запись'}>
      <div style={{ paddingTop: 12, paddingBottom: 24 }}>

      {/* F1: business header — клиент видит, куда зашёл (важно при входе по QR) */}
      {business && (
        <div className="ds-card bk-biz-card">
          {businessCover ? (
            <div className="bk-biz-cover">
              <img
                src={`/api/telegram-photo/${encodeURIComponent(businessCover)}`}
                alt={business.name}
              />
            </div>
          ) : (
            <div className="bk-biz-cover">
              <Scissors size={18} />
            </div>
          )}
          <div style={{ minWidth: 0, flex: 1 }}>
            <div className="bk-biz-eyebrow">Запись в</div>
            <h2 className="ds-h2" style={{ whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{business.name}</h2>
            {business.address && (
              <p className="ds-caption" style={{ whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{business.address}</p>
            )}
          </div>
        </div>
      )}

      {/* F2: auto-pick toast */}
      {skipToast && (
        <div className="bk-toast">
          {`✓ выбрано — `}{skipToast}
        </div>
      )}

      {/* ═══════════════════════════════════════ */}
      {/* VENUE RENTAL FLOW                       */}
      {/* ═══════════════════════════════════════ */}

      {isVenue && (
        <>
          {/* 1. Service selection (multi) — first */}
          <div ref={refVenueServices} className="bk-section">
            <SectionHeader
              icon={<Scissors size={20} />}
              title="Выберите услуги"
              subtitle="можно несколько"
            />
            <div className="bk-option-list">
              {services.map((svc) => {
                const isSelected = selectedServices.some((s) => s.id === svc.id)
                return (
                  <button
                    key={svc.id}
                    onClick={() => {
                      setSelectedServices((prev) =>
                        prev.some((s) => s.id === svc.id)
                          ? prev.filter((s) => s.id !== svc.id)
                          : [...prev, svc]
                      )
                    }}
                    className={`bk-option ${isSelected ? 'is-selected' : ''}`}
                  >
                    <div style={{ flex: 1, textAlign: 'left' }}>
                      <h3 className="bk-option-title">
                        {svc.name}
                      </h3>
                      {svc.description && (
                        <p className="bk-option-desc">{svc.description}</p>
                      )}
                      {formatDuration(svc.duration_minutes) && (
                        <div className="bk-option-meta">
                          <span className="bk-option-meta-item">
                            {formatDuration(svc.duration_minutes)}
                          </span>
                        </div>
                      )}
                    </div>
                    <div className={`bk-check ${isSelected ? 'is-on' : ''}`}>
                      {isSelected && <Check size={14} strokeWidth={3} />}
                    </div>
                  </button>
                )
              })}
            </div>

            {/* Summary */}
            {selectedServices.length > 0 && (
              <div className="bk-summary-row">
                <div className="ds-sub">
                  {selectedServices.length} услуг
                  {selectedServices.reduce((sum, s) => sum + (s.duration_minutes ?? 0), 0) > 0 &&
                    ` \u00B7 ${formatDuration(selectedServices.reduce((sum, s) => sum + (s.duration_minutes ?? 0), 0))}`}
                </div>
                <button
                  onClick={() => scrollToRef(refRoom, 100)}
                  className="lnk"
                >
                  Далее ↓
                </button>
              </div>
            )}
          </div>

          {/* 2. Date — after services */}
          {showDateSection && (
            <div ref={refDate} className="bk-section bk-fade-in">
              <SectionHeader
                icon={<Calendar size={20} />}
                title="Выберите дату"
              />
              <CalendarPicker
                selected={selectedDate}
                onSelect={(date) => {
                  setSelectedDate(date)
                  setSelectedTime(null)
                  setPriceData(null)
                  scrollToRef(refRoom)
                }}
              />
            </div>
          )}

          {/* 3. Room selection — after date */}
          {showRoomSection && (
            <div ref={refRoom} className="bk-section bk-fade-in">
              <SectionHeader
                icon={<DoorOpen size={20} />}
                title="Выберите зал"
              />
              <div className="bk-option-grid bk-option-grid--2">
                {employees.map((room) => {
                  const isSelected = selectedRoom?.id === room.id
                  const priceRange = getRoomPriceRange(room)
                  const photoIds = parsePhotos(room.photos)
                  const cover = photoIds[0]
                  return (
                    <button
                      key={room.id}
                      onClick={() => {
                        setSelectedRoom(room)
                        scrollToRef(refTime)
                      }}
                      className={`bk-option bk-room-card ${isSelected ? 'is-selected' : ''}`}
                    >
                      <div style={{ display: 'flex', alignItems: 'flex-start', gap: 12 }}>
                        <div className="bk-room-thumb">
                          {cover ? (
                            <img
                              src={`/api/telegram-photo/${encodeURIComponent(cover)}`}
                              alt={room.name}
                              loading="lazy"
                            />
                          ) : (
                            <Music size={20} />
                          )}
                        </div>
                        <div style={{ flex: 1, minWidth: 0 }}>
                          <h3 className="bk-option-title">
                            {room.name}
                          </h3>
                          {room.description && (
                            <p className="bk-option-desc" style={{ display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', overflow: 'hidden' }}>
                              {room.description}
                            </p>
                          )}
                          <div className="bk-option-meta">
                            {room.capacity && (
                              <span className="bk-option-meta-item">
                                <Users size={12} />
                                до {room.capacity} чел.
                              </span>
                            )}
                            {priceRange && (
                              <span className="bk-option-price">
                                {priceRange}
                              </span>
                            )}
                          </div>
                        </div>
                      </div>
                    </button>
                  )
                })}
              </div>
            </div>
          )}

          {/* 4. Time */}
          {showTimeSection && (
            <div ref={refTime} className="bk-section bk-fade-in">
              <SectionHeader
                icon={<Clock size={20} />}
                title="Выберите время"
                subtitle={selectedDate ? formatDateRu(selectedDate) : undefined}
              />
              {loadingSlots ? (
                <div className="bk-slot-grid">
                  {Array.from({ length: 8 }).map((_, i) => (
                    <div key={i} className="skeleton" style={{ height: 48, borderRadius: 'var(--r-md)' }} />
                  ))}
                </div>
              ) : slots.length === 0 ? (
                <div className="bk-slot-empty">
                  <Clock size={32} style={{ color: 'var(--s-muted)', margin: '0 auto 12px' }} />
                  <p>Нет свободных слотов на эту дату</p>
                  <button
                    onClick={() => scrollToRef(refDate, 100)}
                    className="lnk"
                  >
                    Выбрать другую дату
                  </button>
                </div>
              ) : (
                <>
                  <div className="bk-slot-grid">
                    {slots.map((time) => (
                      <button
                        key={time}
                        onClick={() => {
                          setSelectedTime(time)
                          const nextRef = selectedRoom?.solo_price_per_hour ? refFormat : (additionalServices.length > 0 ? refAddons : refConfirm)
                          scrollToRef(nextRef)
                        }}
                        className={`bk-slot ${selectedTime === time ? 'is-selected' : ''}`}
                      >
                        {time}
                      </button>
                    ))}
                  </div>

                  {/* Price breakdown */}
                  {selectedTime && (
                    <div className="ds-card bk-price-card">
                      {priceLoading ? (
                        <div className="bk-price-loading">
                          <span className="bk-spinner" />
                          Рассчитываем цену...
                        </div>
                      ) : priceData && priceData.segments.length > 0 ? (
                        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                          {priceData.segments.map((seg, i) => (
                            <div key={i} className="bk-price-row">
                              <span className="lbl">
                                {seg.time_from}{'\u2013'}{seg.time_to} ({formatDuration(seg.minutes)}) {'\u00D7'} {formatPrice(seg.price_per_hour, true)}
                              </span>
                              <span className="val">{formatPrice(seg.subtotal)}</span>
                            </div>
                          ))}
                          <div className="bk-price-total">
                            <span className="lbl">Итого</span>
                            <span className="val">{formatPrice(priceData.total)}</span>
                          </div>
                        </div>
                      ) : priceData && priceData.total > 0 ? (
                        <div className="bk-price-row">
                          <span className="lbl">Стоимость</span>
                          <span className="val">{formatPrice(priceData.total)}</span>
                        </div>
                      ) : totalPrice > 0 ? (
                        <div className="bk-price-row">
                          <span className="lbl">Стоимость</span>
                          <span className="val">{formatPrice(totalPrice)}</span>
                        </div>
                      ) : null}
                    </div>
                  )}
                </>
              )}
            </div>
          )}

          {/* 5. Format (solo vs group) */}
          {showFormatSection && (
            <div ref={refFormat} className="bk-section bk-fade-in">
              <SectionHeader
                icon={<Users size={20} />}
                title="Формат занятия"
              />
              {(() => {
                const hours = Math.max(1, totalDuration / 60)
                const groupPrice = priceData?.total ?? 0
                const soloPrice = (selectedRoom?.solo_price_per_hour ?? 0) * hours
                return (
                  <div className="bk-option-list">
                    <button
                      onClick={() => {
                        setIsSoloPricing(false)
                        scrollToRef(additionalServices.length > 0 ? refAddons : refConfirm)
                      }}
                      className={`bk-option ${!isSoloPricing ? 'is-selected' : ''}`}
                    >
                      <div style={{ display: 'flex', alignItems: 'center', gap: 12, width: '100%' }}>
                        <div className={`bk-emp-ava ${!isSoloPricing ? 'is-selected' : ''}`} style={{ borderRadius: 'var(--r-md)' }}>
                          <Users size={18} />
                        </div>
                        <div style={{ flex: 1 }}>
                          <h3 className="bk-option-title">
                            Групповое занятие
                          </h3>
                          <p className="bk-option-desc">Цена по времени суток</p>
                        </div>
                        <span className="bk-option-price">{formatPrice(groupPrice)}</span>
                      </div>
                    </button>
                    <button
                      onClick={() => {
                        setIsSoloPricing(true)
                        scrollToRef(additionalServices.length > 0 ? refAddons : refConfirm)
                      }}
                      className={`bk-option ${isSoloPricing ? 'is-selected' : ''}`}
                    >
                      <div style={{ display: 'flex', alignItems: 'center', gap: 12, width: '100%' }}>
                        <div className={`bk-emp-ava ${isSoloPricing ? 'is-selected' : ''}`} style={{ borderRadius: 'var(--r-md)' }}>
                          <UserCheck size={18} />
                        </div>
                        <div style={{ flex: 1 }}>
                          <h3 className="bk-option-title">
                            Индивидуальное
                          </h3>
                          <p className="bk-option-desc">
                            {formatPrice(selectedRoom?.solo_price_per_hour, true)} {'\u00D7'} {hours} ч
                          </p>
                        </div>
                        <span className="bk-option-price">{formatPrice(soloPrice)}</span>
                      </div>
                    </button>
                  </div>
                )
              })()}
            </div>
          )}

        </>
      )}

      {/* ═══════════════════════════════════════ */}
      {/* SIMPLE (NON-VENUE) FLOW                 */}
      {/* ═══════════════════════════════════════ */}

      {!isVenue && (
        <>
          {/* 1. Service selection */}
          <div ref={refService} className="bk-section">
            <SectionHeader
              icon={<Scissors size={20} />}
              title="Выберите услугу"
            />
            <div className="bk-option-list">
              {services.map((service) => {
                const isSelected = selectedService?.id === service.id
                return (
                  <button
                    key={service.id}
                    onClick={() => {
                      setSelectedService(service)
                      setSelectedDate(null)
                      setSelectedTime(null)
                      scrollToRef(refDate)
                    }}
                    className={`bk-option ${isSelected ? 'is-selected' : ''}`}
                    style={{ display: 'block' }}
                  >
                    <h3 className="bk-option-title">{service.name}</h3>
                    {service.description && (
                      <p className="bk-option-desc">{service.description}</p>
                    )}
                    <div className="bk-option-meta">
                      {service.price != null && (
                        <span className="bk-option-price">
                          {formatPrice(service.price, service.is_hourly_price)}
                        </span>
                      )}
                      {formatDuration(service.duration_minutes) && (
                        <span className="bk-option-meta-item">
                          {formatDuration(service.duration_minutes)}
                        </span>
                      )}
                    </div>
                  </button>
                )
              })}
            </div>
          </div>

          {/* 2. Date — after service */}
          {showDateSection && (
            <div ref={refDate} className="bk-section bk-fade-in">
              <SectionHeader
                icon={<Calendar size={20} />}
                title="Выберите дату"
                subtitle={selectedService?.name}
              />
              <CalendarPicker
                selected={selectedDate}
                onSelect={(date) => {
                  setSelectedDate(date)
                  setSelectedTime(null)
                  scrollToRef(employees.length > 0 ? refEmployee : refTime)
                }}
              />
            </div>
          )}

          {/* 3. Employee selection — after date */}
          {showEmployeeSection && (
            <div ref={refEmployee} className="bk-section bk-fade-in">
              <SectionHeader
                icon={<User size={20} />}
                title="Выберите специалиста"
                subtitle="необязательно"
              />
              <div className="bk-emp-grid">
                {employees.map((emp) => {
                  const isSelected = selectedEmployee?.id === emp.id
                  const photoIds = parsePhotos(emp.photos)
                  const cover = photoIds[0]
                  return (
                    <button
                      key={emp.id}
                      onClick={() => {
                        setSelectedEmployee(isSelected ? null : emp)
                      }}
                      className={`bk-option bk-emp-card ${isSelected ? 'is-selected' : ''}`}
                      style={{ minHeight: 60 }}
                    >
                      <div className="bk-emp-ava">
                        {cover ? (
                          <img
                            src={`/api/telegram-photo/${encodeURIComponent(cover)}`}
                            alt={emp.name}
                            loading="lazy"
                          />
                        ) : (
                          <User size={18} />
                        )}
                      </div>
                      <span className="bk-emp-name">
                        {emp.name}
                      </span>
                    </button>
                  )
                })}
              </div>
            </div>
          )}

          {/* 4. Time */}
          {showTimeSection && (
            <div ref={refTime} className="bk-section bk-fade-in">
              <SectionHeader
                icon={<Clock size={20} />}
                title="Выберите время"
                subtitle={selectedDate ? formatDateRu(selectedDate) : undefined}
              />
              {loadingSlots ? (
                <div className="bk-slot-grid">
                  {Array.from({ length: 8 }).map((_, i) => (
                    <div key={i} className="skeleton" style={{ height: 48, borderRadius: 'var(--r-md)' }} />
                  ))}
                </div>
              ) : slots.length === 0 ? (
                <div className="bk-slot-empty">
                  <Clock size={32} style={{ color: 'var(--s-muted)', margin: '0 auto 12px' }} />
                  <p>Нет свободных слотов на эту дату</p>
                  <button
                    onClick={() => scrollToRef(refDate, 100)}
                    className="lnk"
                  >
                    Выбрать другую дату
                  </button>
                </div>
              ) : (
                <div className="bk-slot-grid">
                  {slots.map((time) => (
                    <button
                      key={time}
                      onClick={() => {
                        setSelectedTime(time)
                        scrollToRef(refConfirm)
                      }}
                      className={`bk-slot ${selectedTime === time ? 'is-selected' : ''}`}
                    >
                      {time}
                    </button>
                  ))}
                </div>
              )}
            </div>
          )}
        </>
      )}

      {/* ═══════════════════════════════════════ */}
      {/* ADDONS (shared — appears after time for any flow) */}
      {/* ═══════════════════════════════════════ */}

      {showAddonsSection && (
        <div ref={refAddons} className="bk-section bk-fade-in">
          <SectionHeader
            icon={<Package size={20} />}
            title="Дополнительные услуги"
            subtitle="необязательно"
          />
          <div className="bk-option-list">
            {additionalServices.map((svc) => {
              const isSelected = selectedAddons.has(svc.id)
              const hours = addonHours[svc.id] ?? 1
              return (
                <div key={svc.id}>
                  <button
                    onClick={() => toggleAddon(svc.id)}
                    className={`bk-option ${isSelected ? 'is-selected' : ''}`}
                  >
                    <div style={{ flex: 1, textAlign: 'left' }}>
                      <span className="bk-option-title">
                        {svc.name}
                      </span>
                      <div className="bk-option-meta" style={{ marginTop: 2 }}>
                        {(svc.price != null && svc.price > 0) && (
                          <span className="bk-option-meta-item" style={{ color: 'var(--s-accent)', fontWeight: 600 }}>
                            {formatPrice(svc.price)}{svc.is_hourly_price ? '/ч' : ''}
                          </span>
                        )}
                        {(svc.duration_minutes != null && svc.duration_minutes > 0) && (
                          <span className="bk-option-meta-item">
                            {formatDuration(svc.duration_minutes)}
                          </span>
                        )}
                      </div>
                    </div>
                    <div className={`bk-check ${isSelected ? 'is-on' : ''}`}>
                      {isSelected && <Check size={14} strokeWidth={3} />}
                    </div>
                  </button>

                  {/* Hourly controls */}
                  {isSelected && svc.is_hourly_price && (
                    <div className="bk-addon-hours">
                      <button
                        onClick={() => setAddonHourCount(svc.id, hours - 1)}
                        className="ds-icon-btn"
                      >
                        <Minus size={16} />
                      </button>
                      <span className="val">
                        {hours} ч
                      </span>
                      <button
                        onClick={() => setAddonHourCount(svc.id, hours + 1)}
                        className="ds-icon-btn"
                      >
                        <Plus size={16} />
                      </button>
                      <span className="price">
                        {formatPrice((svc.price ?? 0) * hours)}
                      </span>
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* ═══════════════════════════════════════ */}
      {/* CONFIRM SECTION (shared)                */}
      {/* ═══════════════════════════════════════ */}

      {showConfirmSection && (
        <div ref={refConfirm} className="bk-section bk-fade-in">
          <SectionHeader
            icon={<CheckCircle size={20} />}
            title="Подтверждение"
            subtitle="Проверьте данные"
          />

          {/* Summary card */}
          <div className="ds-card bk-card">
            <div className="bk-summary-list">
              {isVenue && selectedRoom && (
                <div className="bk-summary-line">
                  <span className="lbl">Зал</span>
                  <span className="val">{selectedRoom.name}</span>
                </div>
              )}
              {mainServiceLabel && (
                <div className="bk-summary-line">
                  <span className="lbl">{isVenue ? 'Услуги' : 'Услуга'}</span>
                  <span className="val" style={{ maxWidth: '60%' }}>{mainServiceLabel}</span>
                </div>
              )}
              {!isVenue && selectedEmployee && (
                <div className="bk-summary-line">
                  <span className="lbl">Специалист</span>
                  <span className="val">{selectedEmployee.name}</span>
                </div>
              )}
              {isVenue && isSoloPricing && (
                <div className="bk-summary-line">
                  <span className="lbl">Формат</span>
                  <span className="val">Индивидуальное</span>
                </div>
              )}
              <div className="bk-summary-line">
                <span className="lbl">Дата</span>
                <span className="val">
                  {selectedDate && formatDateRu(selectedDate)}
                </span>
              </div>
              <div className="bk-summary-line">
                <span className="lbl">Время</span>
                <span className="val">{selectedTime}</span>
              </div>
              {totalDuration > 0 && (
                <div className="bk-summary-line">
                  <span className="lbl">Длительность</span>
                  <span className="val">{formatDuration(totalDuration)}</span>
                </div>
              )}

              {/* Price breakdown for venue */}
              {isVenue && !isSoloPricing && priceData && priceData.segments.length > 0 && (
                <div className="bk-summary-block">
                  <div className="bk-summary-block-title">Расчёт стоимости:</div>
                  {priceData.segments.map((seg, i) => (
                    <div key={i} className="bk-summary-line">
                      <span className="lbl">
                        {seg.time_from}{'\u2013'}{seg.time_to} ({formatDuration(seg.minutes)}) {'\u00D7'} {formatPrice(seg.price_per_hour, true)}
                      </span>
                      <span className="val">{formatPrice(seg.subtotal)}</span>
                    </div>
                  ))}
                </div>
              )}

              {isVenue && !isSoloPricing && (!priceData || !priceData.has_time_price || (priceData.segments.length === 0 && priceData.total === 0)) && selectedServices.length > 0 && (
                <div className="bk-summary-block">
                  {selectedServices.map((svc: Service) => (
                    <div key={svc.id} className="bk-summary-line">
                      <span className="lbl">{svc.name}</span>
                      <span className="val">{formatPrice(svc.price ?? 0)}</span>
                    </div>
                  ))}
                </div>
              )}

              {isVenue && isSoloPricing && selectedRoom?.solo_price_per_hour && (
                <div className="bk-summary-block">
                  <div className="bk-summary-line">
                    <span className="lbl">{formatPrice(selectedRoom.solo_price_per_hour, true)} {'\u00D7'} {Math.max(1, totalDuration / 60)} ч</span>
                    <span className="val">{formatPrice(selectedRoom.solo_price_per_hour * Math.max(1, totalDuration / 60))}</span>
                  </div>
                </div>
              )}

              {/* Addons */}
              {(() => {
                const activeAddons = additionalServices.filter((s) => selectedAddons.has(s.id))
                if (activeAddons.length === 0) return null
                return (
                  <div className="bk-summary-block">
                    {activeAddons.map((addon) => {
                      const h = addonHours[addon.id] ?? 1
                      const price = addon.is_hourly_price
                        ? (addon.price ?? 0) * h
                        : (addon.price ?? 0)
                      return (
                        <div key={addon.id} className="bk-summary-line">
                          <span className="lbl">
                            + {addon.name}
                            {addon.is_hourly_price && ` (${h} ч)`}
                          </span>
                          <span className="val">{formatPrice(price)}</span>
                        </div>
                      )
                    })}
                  </div>
                )
              })()}

              {totalPrice > 0 && (
                <div className="bk-summary-total">
                  <span className="lbl">Итого</span>
                  <span className="val">{formatPrice(totalPrice)}</span>
                </div>
              )}
            </div>
          </div>

          {/* Address & directions */}
          {(business?.address || business?.directions) && (
            <div className="ds-card bk-card">
              {business?.address && (
                <div style={{ display: 'flex', alignItems: 'flex-start', gap: 8, marginBottom: business?.directions ? 8 : 0 }}>
                  <MapPin size={16} className="ds-accent" style={{ marginTop: 2, flexShrink: 0 }} />
                  <a
                    href={`https://yandex.ru/maps/?text=${encodeURIComponent(business.address)}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="ds-accent"
                    style={{ fontSize: 13, textDecoration: 'underline' }}
                  >
                    {business.address}
                  </a>
                </div>
              )}
              {business?.directions && (
                <div style={{ display: 'flex', alignItems: 'flex-start', gap: 8 }}>
                  <Navigation size={16} style={{ color: 'var(--s-muted)', marginTop: 2, flexShrink: 0 }} />
                  <p className="ds-sub" style={{ whiteSpace: 'pre-line', lineHeight: 1.6 }}>
                    {linkifyText(business.directions)}
                  </p>
                </div>
              )}
            </div>
          )}

          {/* Business description */}
          {business?.description && (
            <div className="ds-card bk-card">
              <p className="ds-sub" style={{ whiteSpace: 'pre-line', lineHeight: 1.6 }}>
                {linkifyText(business.description)}
              </p>
            </div>
          )}

          {/* Contact info */}
          <div style={{ marginBottom: 24 }}>
            <div className="ds-field">
              <label className="ds-label">
                Ваше имя <span style={{ color: 'var(--s-danger)' }}>*</span>
              </label>
              <input
                ref={nameInputRef}
                type="text"
                value={clientName}
                onChange={(e) => {
                  setClientName(e.target.value)
                  if (fieldErrors.name) setFieldErrors((p) => ({ ...p, name: false }))
                }}
                placeholder="Введите имя"
                className={`ds-input ${fieldErrors.name ? 'bk-input-error' : ''}`}
              />
              {fieldErrors.name && (
                <p className="ds-error" style={{ marginTop: 4, marginBottom: 0 }}>Укажите ваше имя</p>
              )}
            </div>
            <div className="ds-field">
              <label className="ds-label">
                Телефон <span style={{ color: 'var(--s-danger)' }}>*</span>
              </label>
              <input
                ref={phoneInputRef}
                type="tel"
                value={clientPhone}
                onChange={(e) => {
                  setClientPhone(e.target.value)
                  if (fieldErrors.phone) setFieldErrors((p) => ({ ...p, phone: false }))
                }}
                placeholder="+7 (___) ___-__-__"
                className={`ds-input ${fieldErrors.phone ? 'bk-input-error' : ''}`}
              />
              {fieldErrors.phone && (
                <p className="ds-error" style={{ marginTop: 4, marginBottom: 0 }}>Укажите телефон для связи</p>
              )}
            </div>
            <div className="ds-field" style={{ marginBottom: 0 }}>
              <label className="ds-label">
                Комментарий{' '}
                <span style={{ fontWeight: 400 }}>(необязательно)</span>
              </label>
              <textarea
                value={comment}
                onChange={(e) => setComment(e.target.value)}
                placeholder="Пожелания к записи..."
                rows={3}
                className="ds-input"
              />
            </div>
          </div>

          {/* Prepayment info */}
          {business?.prepayment_enabled && totalPrice > 0 && (
            <div className="bk-info-box is-amber">
              <h3>
                <CreditCard size={16} />
                Предоплата
              </h3>
              <div>
                <p>
                  {'Для подтверждения бронирования необходимо внести предоплату '}
                  <span style={{ fontWeight: 700 }}>
                    {(business.prepayment_percent ?? 100) === 100
                      ? formatPrice(totalPrice)
                      : `${business.prepayment_percent}% = ${formatPrice(Math.ceil(totalPrice * (business.prepayment_percent ?? 100) / 100))}`}
                  </span>
                </p>
                {(business.payment_details || business.payment_phone) && (
                  <p>
                    {'Реквизиты: '}
                    <span style={{ fontWeight: 600 }}>{business.payment_details || business.payment_phone}</span>
                  </p>
                )}
                {business.payment_phone && business.payment_details && (
                  <p>
                    {'Телефон: '}
                    <span style={{ fontWeight: 600 }}>{business.payment_phone}</span>
                  </p>
                )}
              </div>
              <p className="bk-info-hint">
                После записи оплатите по указанным реквизитам. Без предоплаты бронь может быть отменена.
              </p>
            </div>
          )}

          {/* Cancellation policy */}
          {business?.cancellation_policy_text ? (
            <div className="bk-info-box is-danger">
              <h3>
                {'\u26A0\uFE0F Условия отмены'}
              </h3>
              <p style={{ whiteSpace: 'pre-line' }}>
                {business.cancellation_policy_text}
              </p>
            </div>
          ) : business?.cancellation_policy_photo ? (
            <div className="bk-info-box is-danger">
              <h3>
                {'\u26A0\uFE0F Условия отмены'}
              </h3>
              <img
                src={`/api/telegram-photo/${encodeURIComponent(business.cancellation_policy_photo)}`}
                alt="Условия отмены"
              />
            </div>
          ) : null}

          {bookingError && (
            <div className="bk-error-box">
              <p>{bookingError}</p>
            </div>
          )}

          {missingFields.length > 0 && !bookingError && (
            <p className="bk-missing-hint">
              Чтобы записаться, осталось указать: <span style={{ fontWeight: 600, color: 'var(--s-text)' }}>{missingFields.join(' и ')}</span>
            </p>
          )}
          <button
            onClick={handleSubmit}
            disabled={submitting}
            className="ds-btn ds-btn--primary ds-btn--block"
            style={{ padding: '15px', fontSize: 16 }}
          >
            {submitting ? 'Записываем...' : 'Записаться'}
          </button>
        </div>
      )}

      {/* Floating "Далее" — appears once user makes a selection and points to the next required step */}
      {nextRef && (
        <button
          type="button"
          onClick={() => scrollToRef(nextRef, 0)}
          style={{ bottom: 'max(5rem, calc(4rem + env(safe-area-inset-bottom)))' }}
          className="bk-fab-next bk-fade-in"
        >
          Далее
          <ChevronDown size={16} strokeWidth={2.5} />
        </button>
      )}
      </div>
    </ClientShell>
  )
}

// Глобальный ErrorBoundary на всю страницу: если main render крашит, клиент
// видит сообщение + ссылку на главную, а не белый экран.
class PageErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state: { error: Error | null } = { error: null }
  static getDerivedStateFromError(error: Error) { return { error } }
  componentDidCatch(error: Error, info: { componentStack?: string }) {
    try {
      console.error('BookingPage crashed:', error)
      console.error('Component stack:', info?.componentStack)
    } catch {}
  }
  render() {
    if (this.state.error) {
      return (
        <div className="bk-fallback">
          <div className="bk-fallback-icon is-error">⚠️</div>
          <h2 className="ds-h1">Не удалось открыть форму записи</h2>
          <p className="ds-sub bk-fallback-sub">
            Произошла ошибка. Попробуйте обновить страницу или вернуться на главную.
          </p>
          <p className="bk-fallback-mono">
            {String(this.state.error?.message || this.state.error)}
          </p>
          <div className="bk-fallback-actions">
            <button
              onClick={() => window.location.reload()}
              className="ds-btn ds-btn--primary"
            >
              Обновить
            </button>
            <Link to="/" className="ds-btn ds-btn--ghost">
              На главную
            </Link>
          </div>
        </div>
      )
    }
    return this.props.children
  }
}

export function BookingPage() {
  return (
    <PageErrorBoundary>
      <BookingPageInner />
    </PageErrorBoundary>
  )
}
