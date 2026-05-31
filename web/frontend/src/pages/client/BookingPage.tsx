import { useState, useEffect, useMemo, useRef, Component, type ReactNode } from 'react'
import { useParams, useSearchParams, useNavigate, Link } from 'react-router-dom'

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
        <div className="flex flex-col items-center justify-center py-20 text-center px-4">
          <div className="w-16 h-16 mb-4 rounded-full bg-green-50 flex items-center justify-center">
            <span className="text-3xl">✅</span>
          </div>
          <h2 className="text-xl font-bold text-apple-text mb-2">Запись создана</h2>
          <p className="text-apple-gray text-sm mb-4 max-w-sm">
            Бронь сохранена{this.props.bookingId ? ` (№${this.props.bookingId})` : ''}. Подробности и статус доступны по ссылке.
          </p>
          {publicUrl && (
            <a href={publicUrl} className="inline-block bg-apple-blue text-white px-6 py-3 rounded-2xl font-semibold mb-3">
              Открыть страницу брони
            </a>
          )}
          <Link to="/" className="text-sm text-apple-blue underline">На главную</Link>
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
        <a key={i} href={href} target="_blank" rel="noopener noreferrer" className="text-apple-blue underline">
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
    <div className="bg-white rounded-2xl shadow-sm p-5">
      <div className="flex items-center justify-between mb-4">
        <button
          onClick={prevMonth}
          className="p-2.5 rounded-xl hover:bg-apple-bg transition-all duration-200 min-h-[44px] min-w-[44px] flex items-center justify-center"
          aria-label="Предыдущий месяц"
        >
          <ChevronLeft size={20} />
        </button>
        <h3 className="font-semibold text-apple-text">
          {MONTHS_RU[currentMonth.getMonth()]} {currentMonth.getFullYear()}
        </h3>
        <button
          onClick={nextMonth}
          className="p-2.5 rounded-xl hover:bg-apple-bg transition-all duration-200 min-h-[44px] min-w-[44px] flex items-center justify-center"
          aria-label="Следующий месяц"
        >
          <ChevronRight size={20} />
        </button>
      </div>

      <div className="grid grid-cols-7 gap-1 mb-2">
        {['\u041F\u043D', '\u0412\u0442', '\u0421\u0440', '\u0427\u0442', '\u041F\u0442', '\u0421\u0431', '\u0412\u0441'].map((d) => (
          <div key={d} className="text-center text-xs font-medium text-apple-gray py-1">
            {d}
          </div>
        ))}
      </div>

      <div className="grid grid-cols-7 gap-1">
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
              className={`aspect-square min-h-[40px] flex items-center justify-center rounded-xl text-sm font-medium transition-all duration-200 active:scale-95 ${
                isPast
                  ? 'text-apple-border cursor-not-allowed'
                  : isSelected
                    ? 'bg-apple-blue text-white shadow-sm'
                    : isToday
                      ? 'bg-apple-blue/10 text-apple-blue hover:bg-apple-blue/20'
                      : 'text-apple-text hover:bg-apple-bg'
              }`}
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
      <h2 className="text-lg font-bold text-apple-text mb-0.5 flex items-center gap-2">
        {icon}
        {title}
      </h2>
      {subtitle && <p className="text-sm text-apple-gray mb-4">{subtitle}</p>}
      {!subtitle && <div className="mb-4" />}
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
     <SuccessErrorBoundary bookingId={createdBookingId} notifyToken={createdNotifyToken}>
      <div className="flex flex-col items-center justify-center py-20 text-center animate-fade-in">
        <div className={`w-20 h-20 rounded-full flex items-center justify-center mb-6 ${prepaymentEnabled && totalPrice > 0 ? 'bg-amber-50' : 'bg-green-50'}`}>
          {prepaymentEnabled && totalPrice > 0 ? (
            <Clock size={40} className="text-amber-500" />
          ) : (
            <CheckCircle size={40} className="text-apple-success" />
          )}
        </div>
        <h2 className="text-2xl font-extrabold text-apple-text mb-2">
          {prepaymentEnabled && totalPrice > 0
            ? 'Запись ожидает предоплаты'
            : 'Запись создана!'}
        </h2>
        <p className="text-apple-gray mb-6 max-w-sm">
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
        <div className="bg-white rounded-2xl shadow-sm p-6 w-full max-w-sm mb-6">
          <div className="space-y-3 text-left">
            <div className="flex justify-between text-sm">
              <span className="text-apple-gray">{isVenue ? 'Зал' : 'Услуга'}</span>
              <span className="font-medium text-right">
                {isVenue ? selectedRoom?.name : selectedService?.name}
              </span>
            </div>
            {isVenue && selectedServices.length > 0 && (
              <div className="flex justify-between text-sm">
                <span className="text-apple-gray">Услуги</span>
                <span className="font-medium text-right">
                  {selectedServices.map((s) => s.name).join(', ')}
                </span>
              </div>
            )}
            {!isVenue && selectedEmployee && (
              <div className="flex justify-between text-sm">
                <span className="text-apple-gray">Специалист</span>
                <span className="font-medium">{selectedEmployee.name}</span>
              </div>
            )}
            <div className="flex justify-between text-sm">
              <span className="text-apple-gray">Дата и время</span>
              <span className="font-medium">
                {selectedDate && formatDateRu(selectedDate)}, {selectedTime}
              </span>
            </div>
            {business?.address && (
              <div className="flex justify-between text-sm">
                <span className="text-apple-gray">Адрес</span>
                <a
                  href={`https://yandex.ru/maps/?text=${encodeURIComponent(business.address)}`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="font-medium text-apple-blue underline text-right max-w-[60%]"
                >
                  {business.address}
                </a>
              </div>
            )}
            {totalPrice > 0 && (
              <div className="border-t border-apple-border/50 pt-3 flex justify-between">
                <span className="font-medium">Итого</span>
                <span className="font-bold text-lg">{formatPrice(totalPrice)}</span>
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
            className="w-full max-w-sm mb-3 flex flex-col items-center gap-1 bg-apple-blue text-white rounded-2xl px-5 py-4 shadow-lg shadow-apple-blue/20 active:scale-[0.98] transition-all"
          >
            <span className="text-sm font-bold">📲 Получать уведомления в Telegram</span>
            <span className="text-[11px] text-white/85 text-center leading-snug">
              Открыть бота, чтобы узнавать о подтверждении{prepaymentEnabled ? ' предоплаты' : ' записи'} и напоминаниях
            </span>
          </a>
        )}

        {/* Directions on success screen */}
        {business?.directions && (
          <div className="bg-white rounded-2xl shadow-sm p-5 w-full max-w-sm mb-6 text-left">
            <div className="flex items-center gap-2 mb-2">
              <Navigation size={15} className="text-apple-blue" />
              <h3 className="text-sm font-semibold text-apple-text">Как добраться</h3>
            </div>
            <p className="text-sm text-apple-gray whitespace-pre-line leading-relaxed">
              {linkifyText(business.directions)}
            </p>
          </div>
        )}

        {/* Prepayment block */}
        {prepaymentEnabled && totalPrice > 0 && (
          <div className="w-full max-w-sm mb-6">
            <div className="bg-amber-50 border border-amber-200 rounded-2xl p-5 text-left">
              <div className="flex items-center gap-2 mb-3">
                <CreditCard size={20} className="text-amber-600" />
                <h3 className="font-semibold text-amber-800">
                  Для подтверждения записи необходима предоплата
                </h3>
              </div>
              <div className="space-y-2 text-sm">
                <div className="flex justify-between">
                  <span className="text-amber-700">Сумма</span>
                  <span className="font-bold text-amber-900">{formatPrice(prepaymentAmount)}</span>
                </div>
                {paymentPhone && (
                  <div className="flex justify-between">
                    <span className="text-amber-700">Телефон для оплаты</span>
                    <span className="font-medium text-amber-900">{paymentPhone}</span>
                  </div>
                )}
                {paymentDetails && (
                  <div className="flex justify-between">
                    <span className="text-amber-700">Реквизиты</span>
                    <span className="font-medium text-amber-900">{paymentDetails}</span>
                  </div>
                )}
              </div>
              {cancellationPolicyText ? (
                <div className="mt-3 bg-red-50 border-2 border-red-400 rounded-xl p-3">
                  <p className="text-sm font-bold text-red-700 mb-1">{'\u26A0\uFE0F Условия отмены'}</p>
                  <p className="text-sm text-red-800 whitespace-pre-line">{cancellationPolicyText}</p>
                </div>
              ) : cancellationPolicyPhoto ? (
                <div className="mt-3">
                  <img
                    src={'/api/telegram-photo/' + encodeURIComponent(cancellationPolicyPhoto)}
                    alt="Условия отмены"
                    className="w-full rounded-xl border border-red-300"
                  />
                </div>
              ) : null}
              <div className="mt-4 space-y-3">
                {paymentSent || receiptUploaded ? (
                  <div className="py-4 rounded-2xl bg-green-50 border border-green-200 text-center">
                    <CheckCircle size={24} className="text-green-600 mx-auto mb-2" />
                    <p className="text-green-700 font-semibold text-sm">
                      {receiptUploaded ? 'Чек отправлен владельцу' : 'Владелец уведомлён'}
                    </p>
                    <p className="text-green-600 text-xs mt-1">
                      Ожидайте подтверждения оплаты. Вам придёт уведомление.
                    </p>
                  </div>
                ) : (
                  <>
                    <input
                      ref={receiptInputRef}
                      type="file"
                      accept="image/*,.pdf,application/pdf"
                      className="hidden"
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
                      <div className="space-y-3">
                        <div className="bg-white rounded-2xl border border-apple-border/60 p-3">
                          {pendingReceiptPreview ? (
                            <img
                              src={pendingReceiptPreview}
                              alt="Превью чека"
                              className="w-full max-h-72 object-contain rounded-xl"
                            />
                          ) : (
                            <div className="flex items-center gap-3 py-3">
                              <div className="w-12 h-12 rounded-xl bg-apple-blue/10 flex items-center justify-center shrink-0">
                                <Paperclip size={20} className="text-apple-blue" />
                              </div>
                              <div className="min-w-0 flex-1">
                                <p className="text-sm font-semibold text-apple-text truncate">{pendingReceipt.name}</p>
                                <p className="text-xs text-apple-gray">
                                  {(pendingReceipt.size / 1024).toFixed(0)} КБ · {pendingReceipt.type || 'файл'}
                                </p>
                              </div>
                            </div>
                          )}
                          <p className="text-xs text-apple-gray mt-2 text-center">
                            Проверьте, что файл правильный — затем отправьте
                          </p>
                        </div>

                        {receiptError && (
                          <p className="text-xs text-red-600 text-center">{receiptError}</p>
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
                          className="w-full py-4 rounded-2xl text-base font-bold bg-apple-blue text-white hover:bg-apple-blue-hover transition-all duration-200 min-h-[52px] disabled:opacity-50 shadow-lg shadow-apple-blue/20 active:scale-[0.98] flex items-center justify-center gap-2"
                        >
                          {receiptUploading ? (
                            <>
                              <div className="w-5 h-5 border-2 border-white border-t-transparent rounded-full animate-spin" />
                              Отправка...
                            </>
                          ) : (
                            <>
                              <CheckCircle size={18} />
                              Отправить чек
                            </>
                          )}
                        </button>

                        <div className="grid grid-cols-2 gap-2">
                          <button
                            onClick={() => receiptInputRef.current?.click()}
                            disabled={receiptUploading}
                            className="py-3 rounded-2xl text-sm font-semibold bg-white border border-apple-border text-apple-text hover:bg-apple-bg transition-all min-h-[44px] disabled:opacity-50 flex items-center justify-center gap-2"
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
                            className="py-3 rounded-2xl text-sm font-semibold bg-white border border-red-200 text-red-600 hover:bg-red-50 transition-all min-h-[44px] disabled:opacity-50"
                          >
                            Удалить
                          </button>
                        </div>
                      </div>
                    ) : (
                      <button
                        onClick={() => receiptInputRef.current?.click()}
                        disabled={!createdBookingId}
                        className="w-full py-4 rounded-2xl text-base font-bold bg-apple-blue text-white hover:bg-apple-blue-hover transition-all duration-200 min-h-[52px] disabled:opacity-50 shadow-lg shadow-apple-blue/20 active:scale-[0.98] flex items-center justify-center gap-2"
                      >
                        <Paperclip size={18} />
                        Прикрепить чек
                      </button>
                    )}
                    {!business?.require_receipt_for_prepayment && (
                      <button
                        onClick={handlePaymentSent}
                        disabled={!createdBookingId}
                        className="w-full py-4 rounded-2xl text-base font-bold bg-green-500 text-white hover:bg-green-600 transition-all duration-200 min-h-[52px] disabled:opacity-50 shadow-lg shadow-green-500/30 active:scale-[0.98]"
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
            <div className="w-full max-w-sm mb-6 bg-white rounded-2xl shadow-sm p-4 text-left">
              <div className="text-xs font-semibold text-apple-text mb-1">📌 Сохранить страницу брони</div>
              <p className="text-[11px] text-apple-gray mb-3 leading-snug">
                Откройте позже, чтобы видеть статус и инструкции владельца. Без Telegram.
              </p>
              <div className="bg-apple-bg rounded-xl px-3 py-2 text-[11px] text-apple-text font-mono break-all mb-3">
                {publicUrl}
              </div>
              <div className="grid grid-cols-2 gap-2">
                <button
                  onClick={copy}
                  className="py-2.5 rounded-xl bg-apple-blue text-white text-sm font-semibold active:scale-[0.98]"
                >
                  Скопировать
                </button>
                <a
                  href={publicUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="py-2.5 rounded-xl bg-white border border-apple-border text-apple-text text-sm font-semibold text-center"
                >
                  Открыть ↗
                </a>
              </div>
            </div>
          )
        })()}

        <div className="flex gap-3">
          <button
            onClick={() => navigate(`/business/${businessId}`)}
            className="bg-apple-bg text-apple-text font-medium px-6 py-3 rounded-xl hover:bg-gray-200 transition-all duration-200"
          >
            К бизнесу
          </button>
          <button
            onClick={() => navigate('/')}
            className="bg-apple-blue text-white font-medium px-6 py-3 rounded-xl hover:bg-apple-blue-hover transition-all duration-200"
          >
            На главную
          </button>
        </div>
      </div>
     </SuccessErrorBoundary>
    )
  }

  // ── Main render — single long page ──

  return (
    <div className="max-w-lg mx-auto pb-24 md:pb-8 space-y-6">

      {/* F1: business header — клиент видит, куда зашёл (важно при входе по QR) */}
      {business && (
        <div className="bg-white rounded-2xl shadow-sm p-3 flex items-center gap-3">
          {businessCover ? (
            <img
              src={`/api/telegram-photo/${encodeURIComponent(businessCover)}`}
              alt={business.name}
              className="w-12 h-12 rounded-xl object-cover shrink-0 border border-apple-border/40"
            />
          ) : (
            <div className="w-12 h-12 rounded-xl bg-apple-blue/10 flex items-center justify-center shrink-0">
              <Scissors size={18} className="text-apple-blue" />
            </div>
          )}
          <div className="min-w-0 flex-1">
            <div className="text-[11px] uppercase tracking-wide text-apple-gray">Запись в</div>
            <h1 className="text-base font-bold text-apple-text truncate">{business.name}</h1>
            {business.address && (
              <p className="text-xs text-apple-gray truncate">{business.address}</p>
            )}
          </div>
        </div>
      )}

      {/* F2: auto-pick toast */}
      {skipToast && (
        <div className="fixed left-1/2 -translate-x-1/2 top-20 z-50 px-4 py-2 bg-apple-text/90 text-white text-sm font-medium rounded-2xl shadow-lg animate-fade-in pointer-events-none">
          {`✓ выбрано — `}{skipToast}
        </div>
      )}

      {/* ═══════════════════════════════════════ */}
      {/* VENUE RENTAL FLOW                       */}
      {/* ═══════════════════════════════════════ */}

      {isVenue && (
        <>
          {/* 1. Service selection (multi) — first */}
          <div ref={refVenueServices}>
            <SectionHeader
              icon={<Scissors size={20} className="text-apple-blue" />}
              title="Выберите услуги"
              subtitle="можно несколько"
            />
            <div className="space-y-2.5">
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
                    className={`w-full flex items-center justify-between p-4 md:p-5 rounded-2xl transition-all duration-200 active:scale-[0.98] min-h-[56px] ${
                      isSelected
                        ? 'bg-apple-blue/10 border-2 border-apple-blue'
                        : 'bg-white shadow-sm border-2 border-transparent hover:shadow-md'
                    }`}
                  >
                    <div className="flex-1 text-left">
                      <h3 className={`font-semibold text-sm ${isSelected ? 'text-apple-blue' : 'text-apple-text'}`}>
                        {svc.name}
                      </h3>
                      {svc.description && (
                        <p className="text-xs text-apple-gray mt-0.5">{svc.description}</p>
                      )}
                      {formatDuration(svc.duration_minutes) && (
                        <div className="flex items-center gap-3 mt-1.5">
                          <span className="text-xs text-apple-gray">
                            {formatDuration(svc.duration_minutes)}
                          </span>
                        </div>
                      )}
                    </div>
                    <div
                      className={`w-6 h-6 rounded-full flex items-center justify-center shrink-0 ml-3 transition-all duration-200 ${
                        isSelected ? 'bg-apple-blue text-white' : 'border-2 border-apple-border'
                      }`}
                    >
                      {isSelected && <Check size={14} strokeWidth={3} />}
                    </div>
                  </button>
                )
              })}
            </div>

            {/* Summary */}
            {selectedServices.length > 0 && (
              <div className="mt-4 bg-white rounded-2xl shadow-sm p-4 flex items-center justify-between">
                <div className="text-sm text-apple-gray">
                  {selectedServices.length} услуг
                  {selectedServices.reduce((sum, s) => sum + (s.duration_minutes ?? 0), 0) > 0 &&
                    ` \u00B7 ${formatDuration(selectedServices.reduce((sum, s) => sum + (s.duration_minutes ?? 0), 0))}`}
                </div>
                <button
                  onClick={() => scrollToRef(refRoom, 100)}
                  className="text-sm font-semibold text-apple-blue"
                >
                  Далее ↓
                </button>
              </div>
            )}
          </div>

          {/* 2. Date — after services */}
          {showDateSection && (
            <div ref={refDate} className="animate-fade-in">
              <SectionHeader
                icon={<Calendar size={20} className="text-apple-blue" />}
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
            <div ref={refRoom} className="animate-fade-in">
              <SectionHeader
                icon={<DoorOpen size={20} className="text-apple-blue" />}
                title="Выберите зал"
              />
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
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
                      className={`text-left p-4 md:p-5 rounded-2xl transition-all duration-200 active:scale-[0.98] min-h-[44px] ${
                        isSelected
                          ? 'bg-apple-blue/10 border-2 border-apple-blue shadow-sm'
                          : 'bg-white shadow-sm hover:shadow-md border-2 border-transparent'
                      }`}
                    >
                      <div className="flex items-start gap-3">
                        <div
                          className={`w-14 h-14 rounded-xl flex items-center justify-center shrink-0 overflow-hidden ${
                            isSelected ? 'bg-apple-blue text-white' : 'bg-apple-bg text-apple-gray'
                          }`}
                        >
                          {cover ? (
                            <img
                              src={`/api/telegram-photo/${encodeURIComponent(cover)}`}
                              alt={room.name}
                              className="w-full h-full object-cover"
                              loading="lazy"
                            />
                          ) : (
                            <Music size={20} />
                          )}
                        </div>
                        <div className="flex-1 min-w-0">
                          <h3 className={`font-semibold text-sm ${isSelected ? 'text-apple-blue' : 'text-apple-text'}`}>
                            {room.name}
                          </h3>
                          {room.description && (
                            <p className="text-xs text-apple-gray mt-0.5 line-clamp-2">
                              {room.description}
                            </p>
                          )}
                          <div className="flex items-center gap-3 mt-2">
                            {room.capacity && (
                              <span className="text-xs text-apple-gray flex items-center gap-1">
                                <Users size={12} />
                                до {room.capacity} чел.
                              </span>
                            )}
                            {priceRange && (
                              <span className="text-xs font-semibold text-apple-text">
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
            <div ref={refTime} className="animate-fade-in">
              <SectionHeader
                icon={<Clock size={20} className="text-apple-blue" />}
                title="Выберите время"
                subtitle={selectedDate ? formatDateRu(selectedDate) : undefined}
              />
              {loadingSlots ? (
                <div className="grid grid-cols-3 sm:grid-cols-4 gap-2">
                  {Array.from({ length: 8 }).map((_, i) => (
                    <div key={i} className="h-12 skeleton rounded-xl" />
                  ))}
                </div>
              ) : slots.length === 0 ? (
                <div className="text-center py-8">
                  <Clock size={32} className="text-apple-gray mx-auto mb-3" />
                  <p className="text-apple-gray">Нет свободных слотов на эту дату</p>
                  <button
                    onClick={() => scrollToRef(refDate, 100)}
                    className="text-apple-blue text-sm font-semibold mt-3 hover:opacity-80 min-h-[44px]"
                  >
                    Выбрать другую дату
                  </button>
                </div>
              ) : (
                <>
                  <div className="grid grid-cols-3 sm:grid-cols-4 gap-2">
                    {slots.map((time) => (
                      <button
                        key={time}
                        onClick={() => {
                          setSelectedTime(time)
                          const nextRef = selectedRoom?.solo_price_per_hour ? refFormat : (additionalServices.length > 0 ? refAddons : refConfirm)
                          scrollToRef(nextRef)
                        }}
                        className={`py-3.5 min-h-[44px] rounded-xl text-sm font-semibold transition-all duration-200 active:scale-95 ${
                          selectedTime === time
                            ? 'bg-apple-blue text-white shadow-sm'
                            : 'bg-white shadow-sm text-apple-text hover:shadow-md'
                        }`}
                      >
                        {time}
                      </button>
                    ))}
                  </div>

                  {/* Price breakdown */}
                  {selectedTime && (
                    <div className="mt-4 bg-white rounded-2xl shadow-sm p-4">
                      {priceLoading ? (
                        <div className="flex items-center gap-2 text-sm text-apple-gray">
                          <div className="w-4 h-4 border-2 border-apple-blue border-t-transparent rounded-full animate-spin" />
                          Рассчитываем цену...
                        </div>
                      ) : priceData && priceData.segments.length > 0 ? (
                        <div className="space-y-2">
                          {priceData.segments.map((seg, i) => (
                            <div key={i} className="flex justify-between text-sm">
                              <span className="text-apple-gray">
                                {seg.time_from}{'\u2013'}{seg.time_to} ({formatDuration(seg.minutes)}) {'\u00D7'} {formatPrice(seg.price_per_hour, true)}
                              </span>
                              <span className="font-medium">{formatPrice(seg.subtotal)}</span>
                            </div>
                          ))}
                          <div className="border-t border-apple-border/50 pt-2 flex justify-between">
                            <span className="font-semibold text-sm">Итого</span>
                            <span className="font-bold">{formatPrice(priceData.total)}</span>
                          </div>
                        </div>
                      ) : priceData && priceData.total > 0 ? (
                        <div className="flex justify-between text-sm">
                          <span className="text-apple-gray">Стоимость</span>
                          <span className="font-bold">{formatPrice(priceData.total)}</span>
                        </div>
                      ) : totalPrice > 0 ? (
                        <div className="flex justify-between text-sm">
                          <span className="text-apple-gray">Стоимость</span>
                          <span className="font-bold">{formatPrice(totalPrice)}</span>
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
            <div ref={refFormat} className="animate-fade-in">
              <SectionHeader
                icon={<Users size={20} className="text-apple-blue" />}
                title="Формат занятия"
              />
              {(() => {
                const hours = Math.max(1, totalDuration / 60)
                const groupPrice = priceData?.total ?? 0
                const soloPrice = (selectedRoom?.solo_price_per_hour ?? 0) * hours
                return (
                  <div className="space-y-3">
                    <button
                      onClick={() => {
                        setIsSoloPricing(false)
                        scrollToRef(additionalServices.length > 0 ? refAddons : refConfirm)
                      }}
                      className={`w-full text-left p-5 rounded-2xl transition-all duration-200 active:scale-[0.98] min-h-[44px] ${
                        !isSoloPricing
                          ? 'bg-apple-blue/10 border-2 border-apple-blue'
                          : 'bg-white shadow-sm border-2 border-transparent hover:shadow-md'
                      }`}
                    >
                      <div className="flex items-center gap-3">
                        <div className={`w-10 h-10 rounded-xl flex items-center justify-center ${!isSoloPricing ? 'bg-apple-blue text-white' : 'bg-apple-bg text-apple-gray'}`}>
                          <Users size={18} />
                        </div>
                        <div className="flex-1">
                          <h3 className={`font-semibold text-sm ${!isSoloPricing ? 'text-apple-blue' : 'text-apple-text'}`}>
                            Групповое занятие
                          </h3>
                          <p className="text-xs text-apple-gray mt-0.5">Цена по времени суток</p>
                        </div>
                        <span className="font-bold text-sm">{formatPrice(groupPrice)}</span>
                      </div>
                    </button>
                    <button
                      onClick={() => {
                        setIsSoloPricing(true)
                        scrollToRef(additionalServices.length > 0 ? refAddons : refConfirm)
                      }}
                      className={`w-full text-left p-5 rounded-2xl transition-all duration-200 active:scale-[0.98] min-h-[44px] ${
                        isSoloPricing
                          ? 'bg-apple-blue/10 border-2 border-apple-blue'
                          : 'bg-white shadow-sm border-2 border-transparent hover:shadow-md'
                      }`}
                    >
                      <div className="flex items-center gap-3">
                        <div className={`w-10 h-10 rounded-xl flex items-center justify-center ${isSoloPricing ? 'bg-apple-blue text-white' : 'bg-apple-bg text-apple-gray'}`}>
                          <UserCheck size={18} />
                        </div>
                        <div className="flex-1">
                          <h3 className={`font-semibold text-sm ${isSoloPricing ? 'text-apple-blue' : 'text-apple-text'}`}>
                            Индивидуальное
                          </h3>
                          <p className="text-xs text-apple-gray mt-0.5">
                            {formatPrice(selectedRoom?.solo_price_per_hour, true)} {'\u00D7'} {hours} ч
                          </p>
                        </div>
                        <span className="font-bold text-sm">{formatPrice(soloPrice)}</span>
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
          <div ref={refService}>
            <SectionHeader
              icon={<Scissors size={20} className="text-apple-blue" />}
              title="Выберите услугу"
            />
            <div className="space-y-2.5">
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
                    className={`w-full text-left rounded-2xl p-5 transition-all duration-200 press-scale ${
                      isSelected
                        ? 'bg-apple-blue/10 border-2 border-apple-blue shadow-sm'
                        : 'bg-white shadow-sm hover:shadow-md border-2 border-transparent'
                    }`}
                  >
                    <h3 className={`font-semibold ${isSelected ? 'text-apple-blue' : 'text-apple-text'}`}>{service.name}</h3>
                    {service.description && (
                      <p className="text-sm text-apple-gray mt-0.5">{service.description}</p>
                    )}
                    <div className="flex items-center gap-3 mt-2">
                      {service.price != null && (
                        <span className="text-sm font-bold text-apple-text">
                          {formatPrice(service.price, service.is_hourly_price)}
                        </span>
                      )}
                      {formatDuration(service.duration_minutes) && (
                        <span className="text-sm text-apple-gray">
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
            <div ref={refDate} className="animate-fade-in">
              <SectionHeader
                icon={<Calendar size={20} className="text-apple-blue" />}
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
            <div ref={refEmployee} className="animate-fade-in">
              <SectionHeader
                icon={<User size={20} className="text-apple-blue" />}
                title="Выберите специалиста"
                subtitle="необязательно"
              />
              <div className="grid grid-cols-2 gap-2">
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
                      className={`p-4 rounded-2xl text-left transition-all duration-200 active:scale-95 min-h-[60px] ${
                        isSelected
                          ? 'bg-apple-blue/10 border-2 border-apple-blue shadow-sm'
                          : 'bg-white shadow-sm hover:shadow-md border-2 border-transparent'
                      }`}
                    >
                      <div className="flex items-center gap-3">
                        <div
                          className={`w-12 h-12 rounded-full flex items-center justify-center shrink-0 overflow-hidden ${
                            isSelected ? 'bg-apple-blue text-white' : 'bg-apple-bg text-apple-gray'
                          }`}
                        >
                          {cover ? (
                            <img
                              src={`/api/telegram-photo/${encodeURIComponent(cover)}`}
                              alt={emp.name}
                              className="w-full h-full object-cover"
                              loading="lazy"
                            />
                          ) : (
                            <User size={18} />
                          )}
                        </div>
                        <span className={`text-sm font-medium leading-tight ${isSelected ? 'text-apple-blue' : 'text-apple-text'}`}>
                          {emp.name}
                        </span>
                      </div>
                    </button>
                  )
                })}
              </div>
            </div>
          )}

          {/* 4. Time */}
          {showTimeSection && (
            <div ref={refTime} className="animate-fade-in">
              <SectionHeader
                icon={<Clock size={20} className="text-apple-blue" />}
                title="Выберите время"
                subtitle={selectedDate ? formatDateRu(selectedDate) : undefined}
              />
              {loadingSlots ? (
                <div className="grid grid-cols-3 sm:grid-cols-4 gap-2">
                  {Array.from({ length: 8 }).map((_, i) => (
                    <div key={i} className="h-12 skeleton rounded-xl" />
                  ))}
                </div>
              ) : slots.length === 0 ? (
                <div className="text-center py-8">
                  <Clock size={32} className="text-apple-gray mx-auto mb-3" />
                  <p className="text-apple-gray">Нет свободных слотов на эту дату</p>
                  <button
                    onClick={() => scrollToRef(refDate, 100)}
                    className="text-apple-blue text-sm font-semibold mt-3 hover:opacity-80 min-h-[44px]"
                  >
                    Выбрать другую дату
                  </button>
                </div>
              ) : (
                <div className="grid grid-cols-3 sm:grid-cols-4 gap-2">
                  {slots.map((time) => (
                    <button
                      key={time}
                      onClick={() => {
                        setSelectedTime(time)
                        scrollToRef(refConfirm)
                      }}
                      className={`py-3.5 min-h-[44px] rounded-xl text-sm font-semibold transition-all duration-200 active:scale-95 ${
                        selectedTime === time
                          ? 'bg-apple-blue text-white shadow-sm'
                          : 'bg-white shadow-sm text-apple-text hover:shadow-md'
                      }`}
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
        <div ref={refAddons} className="animate-fade-in">
          <SectionHeader
            icon={<Package size={20} className="text-apple-blue" />}
            title="Дополнительные услуги"
            subtitle="необязательно"
          />
          <div className="space-y-2.5">
            {additionalServices.map((svc) => {
              const isSelected = selectedAddons.has(svc.id)
              const hours = addonHours[svc.id] ?? 1
              return (
                <div key={svc.id}>
                  <button
                    onClick={() => toggleAddon(svc.id)}
                    className={`w-full flex items-center justify-between p-4 rounded-2xl transition-all duration-200 active:scale-[0.98] min-h-[56px] ${
                      isSelected
                        ? 'bg-apple-blue/10 border-2 border-apple-blue'
                        : 'bg-white shadow-sm border-2 border-transparent hover:shadow-md'
                    }`}
                  >
                    <div className="flex-1 text-left">
                      <span className={`text-sm font-medium ${isSelected ? 'text-apple-blue' : 'text-apple-text'}`}>
                        {svc.name}
                      </span>
                      <div className="flex items-center gap-2 mt-0.5">
                        {(svc.price != null && svc.price > 0) && (
                          <span className="text-[13px] text-apple-blue font-medium">
                            {formatPrice(svc.price)}{svc.is_hourly_price ? '/ч' : ''}
                          </span>
                        )}
                        {(svc.duration_minutes != null && svc.duration_minutes > 0) && (
                          <span className="text-[13px] text-apple-gray">
                            {formatDuration(svc.duration_minutes)}
                          </span>
                        )}
                      </div>
                    </div>
                    <div
                      className={`w-6 h-6 rounded-full flex items-center justify-center shrink-0 ml-3 transition-all duration-200 ${
                        isSelected ? 'bg-apple-blue text-white' : 'border-2 border-apple-border'
                      }`}
                    >
                      {isSelected && <Check size={14} strokeWidth={3} />}
                    </div>
                  </button>

                  {/* Hourly controls */}
                  {isSelected && svc.is_hourly_price && (
                    <div className="flex items-center gap-3 mt-2 ml-4 mb-1">
                      <button
                        onClick={() => setAddonHourCount(svc.id, hours - 1)}
                        className="w-9 h-9 rounded-xl bg-apple-bg flex items-center justify-center hover:bg-gray-200 transition-colors min-h-[44px] min-w-[44px]"
                      >
                        <Minus size={16} />
                      </button>
                      <span className="text-sm font-semibold w-12 text-center">
                        {hours} ч
                      </span>
                      <button
                        onClick={() => setAddonHourCount(svc.id, hours + 1)}
                        className="w-9 h-9 rounded-xl bg-apple-bg flex items-center justify-center hover:bg-gray-200 transition-colors min-h-[44px] min-w-[44px]"
                      >
                        <Plus size={16} />
                      </button>
                      <span className="text-sm text-apple-gray ml-auto">
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
        <div ref={refConfirm} className="animate-fade-in">
          <SectionHeader
            icon={<CheckCircle size={20} className="text-apple-blue" />}
            title="Подтверждение"
            subtitle="Проверьте данные"
          />

          {/* Summary card */}
          <div className="bg-white rounded-2xl shadow-sm p-5 mb-5">
            <div className="space-y-3">
              {isVenue && selectedRoom && (
                <div className="flex justify-between text-sm">
                  <span className="text-apple-gray">Зал</span>
                  <span className="font-medium">{selectedRoom.name}</span>
                </div>
              )}
              {mainServiceLabel && (
                <div className="flex justify-between text-sm">
                  <span className="text-apple-gray">{isVenue ? 'Услуги' : 'Услуга'}</span>
                  <span className="font-medium text-right max-w-[60%]">{mainServiceLabel}</span>
                </div>
              )}
              {!isVenue && selectedEmployee && (
                <div className="flex justify-between text-sm">
                  <span className="text-apple-gray">Специалист</span>
                  <span className="font-medium">{selectedEmployee.name}</span>
                </div>
              )}
              {isVenue && isSoloPricing && (
                <div className="flex justify-between text-sm">
                  <span className="text-apple-gray">Формат</span>
                  <span className="font-medium">Индивидуальное</span>
                </div>
              )}
              <div className="flex justify-between text-sm">
                <span className="text-apple-gray">Дата</span>
                <span className="font-medium">
                  {selectedDate && formatDateRu(selectedDate)}
                </span>
              </div>
              <div className="flex justify-between text-sm">
                <span className="text-apple-gray">Время</span>
                <span className="font-medium">{selectedTime}</span>
              </div>
              {totalDuration > 0 && (
                <div className="flex justify-between text-sm">
                  <span className="text-apple-gray">Длительность</span>
                  <span className="font-medium">{formatDuration(totalDuration)}</span>
                </div>
              )}

              {/* Price breakdown for venue */}
              {isVenue && !isSoloPricing && priceData && priceData.segments.length > 0 && (
                <div className="border-t border-apple-border/50 pt-3 space-y-1.5">
                  <div className="text-xs font-medium text-apple-gray mb-1">Расчёт стоимости:</div>
                  {priceData.segments.map((seg, i) => (
                    <div key={i} className="flex justify-between text-xs text-apple-gray">
                      <span>
                        {seg.time_from}{'\u2013'}{seg.time_to} ({formatDuration(seg.minutes)}) {'\u00D7'} {formatPrice(seg.price_per_hour, true)}
                      </span>
                      <span className="font-medium text-apple-text">{formatPrice(seg.subtotal)}</span>
                    </div>
                  ))}
                </div>
              )}

              {isVenue && !isSoloPricing && (!priceData || !priceData.has_time_price || (priceData.segments.length === 0 && priceData.total === 0)) && selectedServices.length > 0 && (
                <div className="border-t border-apple-border/50 pt-3 space-y-1.5">
                  {selectedServices.map((svc: Service) => (
                    <div key={svc.id} className="flex justify-between text-sm">
                      <span className="text-apple-gray">{svc.name}</span>
                      <span className="font-medium">{formatPrice(svc.price ?? 0)}</span>
                    </div>
                  ))}
                </div>
              )}

              {isVenue && isSoloPricing && selectedRoom?.solo_price_per_hour && (
                <div className="border-t border-apple-border/50 pt-3">
                  <div className="flex justify-between text-xs text-apple-gray">
                    <span>{formatPrice(selectedRoom.solo_price_per_hour, true)} {'\u00D7'} {Math.max(1, totalDuration / 60)} ч</span>
                    <span className="font-medium text-apple-text">{formatPrice(selectedRoom.solo_price_per_hour * Math.max(1, totalDuration / 60))}</span>
                  </div>
                </div>
              )}

              {/* Addons */}
              {(() => {
                const activeAddons = additionalServices.filter((s) => selectedAddons.has(s.id))
                if (activeAddons.length === 0) return null
                return (
                  <div className="border-t border-apple-border/50 pt-3 space-y-1.5">
                    {activeAddons.map((addon) => {
                      const h = addonHours[addon.id] ?? 1
                      const price = addon.is_hourly_price
                        ? (addon.price ?? 0) * h
                        : (addon.price ?? 0)
                      return (
                        <div key={addon.id} className="flex justify-between text-sm">
                          <span className="text-apple-gray">
                            + {addon.name}
                            {addon.is_hourly_price && ` (${h} ч)`}
                          </span>
                          <span className="font-medium">{formatPrice(price)}</span>
                        </div>
                      )
                    })}
                  </div>
                )
              })()}

              {totalPrice > 0 && (
                <div className="border-t border-apple-border/50 pt-3 flex justify-between">
                  <span className="font-semibold">Итого</span>
                  <span className="font-bold text-lg">{formatPrice(totalPrice)}</span>
                </div>
              )}
            </div>
          </div>

          {/* Address & directions */}
          {(business?.address || business?.directions) && (
            <div className="bg-white rounded-2xl shadow-sm p-5 mb-5">
              {business?.address && (
                <div className="flex items-start gap-2 mb-2">
                  <MapPin size={16} className="text-apple-blue mt-0.5 shrink-0" />
                  <a
                    href={`https://yandex.ru/maps/?text=${encodeURIComponent(business.address)}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-sm text-apple-blue underline"
                  >
                    {business.address}
                  </a>
                </div>
              )}
              {business?.directions && (
                <div className="flex items-start gap-2">
                  <Navigation size={16} className="text-apple-gray mt-0.5 shrink-0" />
                  <p className="text-sm text-apple-gray whitespace-pre-line leading-relaxed">
                    {linkifyText(business.directions)}
                  </p>
                </div>
              )}
            </div>
          )}

          {/* Business description */}
          {business?.description && (
            <div className="bg-white rounded-2xl shadow-sm p-5 mb-5">
              <p className="text-sm text-apple-gray whitespace-pre-line leading-relaxed">
                {linkifyText(business.description)}
              </p>
            </div>
          )}

          {/* Contact info */}
          <div className="space-y-3 mb-6">
            <div>
              <label className="block text-sm font-medium text-apple-gray mb-1.5">
                Ваше имя <span className="text-red-500">*</span>
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
                className={`w-full px-4 py-3.5 rounded-xl bg-white shadow-sm text-sm focus:outline-none focus:ring-2 transition-all duration-200 ${
                  fieldErrors.name
                    ? 'border-2 border-red-400 ring-2 ring-red-200 focus:ring-red-300'
                    : 'border-2 border-transparent focus:ring-apple-blue/40'
                }`}
              />
              {fieldErrors.name && (
                <p className="text-xs text-red-600 mt-1 ml-1">Укажите ваше имя</p>
              )}
            </div>
            <div>
              <label className="block text-sm font-medium text-apple-gray mb-1.5">
                Телефон <span className="text-red-500">*</span>
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
                className={`w-full px-4 py-3.5 rounded-xl bg-white shadow-sm text-sm focus:outline-none focus:ring-2 transition-all duration-200 ${
                  fieldErrors.phone
                    ? 'border-2 border-red-400 ring-2 ring-red-200 focus:ring-red-300'
                    : 'border-2 border-transparent focus:ring-apple-blue/40'
                }`}
              />
              {fieldErrors.phone && (
                <p className="text-xs text-red-600 mt-1 ml-1">Укажите телефон для связи</p>
              )}
            </div>
            <div>
              <label className="block text-sm font-medium text-apple-gray mb-1.5">
                Комментарий{' '}
                <span className="text-apple-gray/50 font-normal">(необязательно)</span>
              </label>
              <textarea
                value={comment}
                onChange={(e) => setComment(e.target.value)}
                placeholder="Пожелания к записи..."
                rows={3}
                className="w-full px-4 py-3.5 rounded-xl bg-white shadow-sm text-sm focus:outline-none focus:ring-2 focus:ring-apple-blue/40 transition-all duration-200 resize-none"
              />
            </div>
          </div>

          {/* Prepayment info */}
          {business?.prepayment_enabled && totalPrice > 0 && (
            <div className="bg-amber-50 border border-amber-200 rounded-2xl p-4 mb-5">
              <h3 className="text-sm font-semibold text-amber-800 mb-2 flex items-center gap-1.5">
                <CreditCard size={16} />
                Предоплата
              </h3>
              <div className="space-y-1.5 text-sm text-amber-700">
                <p>
                  {'Для подтверждения бронирования необходимо внести предоплату '}
                  <span className="font-bold">
                    {(business.prepayment_percent ?? 100) === 100
                      ? formatPrice(totalPrice)
                      : `${business.prepayment_percent}% = ${formatPrice(Math.ceil(totalPrice * (business.prepayment_percent ?? 100) / 100))}`}
                  </span>
                </p>
                {(business.payment_details || business.payment_phone) && (
                  <p>
                    {'Реквизиты: '}
                    <span className="font-medium">{business.payment_details || business.payment_phone}</span>
                  </p>
                )}
                {business.payment_phone && business.payment_details && (
                  <p>
                    {'Телефон: '}
                    <span className="font-medium">{business.payment_phone}</span>
                  </p>
                )}
              </div>
              <p className="text-xs text-amber-600 mt-2">
                После записи оплатите по указанным реквизитам. Без предоплаты бронь может быть отменена.
              </p>
            </div>
          )}

          {/* Cancellation policy */}
          {business?.cancellation_policy_text ? (
            <div className="bg-red-50 border-2 border-red-400 rounded-2xl p-4 mb-5">
              <h3 className="text-sm font-bold text-red-700 mb-2">
                {'\u26A0\uFE0F Условия отмены'}
              </h3>
              <p className="text-sm text-red-800 whitespace-pre-line leading-relaxed">
                {business.cancellation_policy_text}
              </p>
            </div>
          ) : business?.cancellation_policy_photo ? (
            <div className="bg-red-50 border-2 border-red-400 rounded-2xl p-4 mb-5">
              <h3 className="text-sm font-bold text-red-700 mb-2">
                {'\u26A0\uFE0F Условия отмены'}
              </h3>
              <img
                src={`/api/telegram-photo/${encodeURIComponent(business.cancellation_policy_photo)}`}
                alt="Условия отмены"
                className="w-full rounded-xl"
              />
            </div>
          ) : null}

          {bookingError && (
            <div className="bg-red-50 border border-red-200 rounded-2xl p-4 text-center mb-5">
              <p className="text-red-700 font-medium text-sm">{bookingError}</p>
            </div>
          )}

          {missingFields.length > 0 && !bookingError && (
            <p className="text-xs text-apple-gray text-center mb-2">
              Чтобы записаться, осталось указать: <span className="font-medium text-apple-text">{missingFields.join(' и ')}</span>
            </p>
          )}
          <button
            onClick={handleSubmit}
            disabled={submitting}
            className="w-full bg-apple-blue text-white font-semibold py-4 rounded-2xl hover:bg-apple-blue-hover transition-all duration-200 disabled:opacity-50 disabled:cursor-not-allowed shadow-lg shadow-apple-blue/20 active:scale-[0.98]"
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
          className="fixed right-4 z-50 flex items-center gap-1.5 bg-apple-blue text-white text-sm font-semibold pl-4 pr-3 py-2.5 rounded-full shadow-lg shadow-apple-blue/30 active:scale-95 animate-fade-in"
        >
          Далее
          <ChevronDown size={16} strokeWidth={2.5} />
        </button>
      )}
    </div>
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
        <div className="flex flex-col items-center justify-center py-20 text-center px-4">
          <div className="w-16 h-16 mb-4 rounded-full bg-red-50 flex items-center justify-center">
            <span className="text-3xl">⚠️</span>
          </div>
          <h2 className="text-xl font-bold text-apple-text mb-2">Не удалось открыть форму записи</h2>
          <p className="text-apple-gray text-sm mb-4 max-w-sm">
            Произошла ошибка. Попробуйте обновить страницу или вернуться на главную.
          </p>
          <p className="text-[10px] text-apple-gray mb-4 max-w-sm break-words font-mono">
            {String(this.state.error?.message || this.state.error)}
          </p>
          <div className="flex gap-2">
            <button
              onClick={() => window.location.reload()}
              className="bg-apple-blue text-white px-6 py-3 rounded-2xl font-semibold"
            >
              Обновить
            </button>
            <Link to="/" className="bg-apple-bg text-apple-text px-6 py-3 rounded-2xl font-semibold">
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
