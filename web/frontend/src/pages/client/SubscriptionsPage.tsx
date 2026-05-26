import { useState, useEffect, useCallback } from 'react'
import {
  Ticket,
  Clock,
  CheckCircle,
  XCircle,
  AlertCircle,
  CreditCard,
  Package,
  ChevronRight,
  X,
  LogIn,
} from 'lucide-react'
import { hapticSelection, hapticSuccess } from '../../utils/telegram'
import { api } from '../../api/client'
import type { SubscriptionPlan, ClientSubscription, BusinessDetail } from '../../api/client'

// ── Status config ──

const statusMap: Record<
  string,
  { label: string; icon: typeof CheckCircle; className: string }
> = {
  active: {
    label: 'Активен',
    icon: CheckCircle,
    className: 'text-green-700 bg-green-50 border border-green-200',
  },
  expired: {
    label: 'Истёк',
    icon: XCircle,
    className: 'text-red-700 bg-red-50 border border-red-200',
  },
  waiting_confirmation: {
    label: 'Ожидает подтверждения',
    icon: AlertCircle,
    className: 'text-yellow-700 bg-yellow-50 border border-yellow-200',
  },
  pending_payment: {
    label: 'Ожидает оплаты',
    icon: AlertCircle,
    className: 'text-yellow-700 bg-yellow-50 border border-yellow-200',
  },
}

const defaultStatus = {
  label: 'Неизвестно',
  icon: AlertCircle,
  className: 'text-gray-700 bg-gray-50 border border-gray-200',
}

// ── Helpers ──

function formatPrice(price: number) {
  return new Intl.NumberFormat('ru-RU').format(price)
}

function formatDays(days: number) {
  if (days % 10 === 1 && days % 100 !== 11) return `${days} день`
  if ([2, 3, 4].includes(days % 10) && ![12, 13, 14].includes(days % 100)) return `${days} дня`
  return `${days} дней`
}

function formatSessions(count: number) {
  if (count % 10 === 1 && count % 100 !== 11) return `${count} занятие`
  if ([2, 3, 4].includes(count % 10) && ![12, 13, 14].includes(count % 100))
    return `${count} занятия`
  return `${count} занятий`
}

function formatDateRu(dateStr: string) {
  const d = new Date(dateStr)
  const months = [
    'января', 'февраля', 'марта', 'апреля', 'мая', 'июня',
    'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря',
  ]
  return `${d.getDate()} ${months[d.getMonth()]} ${d.getFullYear()}`
}

function daysUntil(dateStr: string) {
  const now = new Date()
  now.setHours(0, 0, 0, 0)
  const d = new Date(dateStr)
  d.setHours(0, 0, 0, 0)
  return Math.ceil((d.getTime() - now.getTime()) / (1000 * 60 * 60 * 24))
}

function getTotalSessions(plan: SubscriptionPlan): number {
  if (plan.services && plan.services.length > 0) {
    return plan.services.reduce((sum, s) => sum + s.quantity, 0)
  }
  return plan.sessions_count ?? 0
}

// ── Purchase Modal ──

function PurchaseModal({
  subscription,
  businessDetail,
  onClose,
  onPurchased,
}: {
  subscription: SubscriptionPlan
  businessDetail: BusinessDetail | null
  onClose: () => void
  onPurchased: () => void
}) {
  const [step, setStep] = useState<'confirm' | 'payment' | 'sent'>('confirm')
  const [buying, setBuying] = useState(false)
  const [sending, setSending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [clientSub, setClientSub] = useState<ClientSubscription | null>(null)

  const handleBuy = async () => {
    setBuying(true)
    setError(null)
    try {
      const result = await api.buySubscription(subscription.id)
      setClientSub(result)
      setStep('payment')
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Ошибка при покупке')
    } finally {
      setBuying(false)
    }
  }

  const handlePaymentSent = async () => {
    if (!clientSub) return
    setSending(true)
    setError(null)
    try {
      await api.subscriptionPaymentSent(clientSub.id)
      hapticSuccess()
      setStep('sent')
      onPurchased()
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Ошибка при отправке уведомления')
    } finally {
      setSending(false)
    }
  }

  const totalSessions = getTotalSessions(subscription)

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

        <div className="mb-5">
          <div className="w-14 h-14 bg-blue-50 rounded-2xl flex items-center justify-center mb-4">
            <CreditCard size={28} className="text-apple-blue" />
          </div>
          <h3 className="text-lg font-semibold text-apple-text mb-1">
            {subscription.name}
          </h3>
          <p className="text-2xl font-bold text-apple-text">
            {formatPrice(subscription.price)} {'\u20BD'}
          </p>
          {totalSessions > 0 && (
            <p className="text-sm text-apple-gray mt-1">
              {totalSessions >= 999 ? 'Безлимит' : formatSessions(totalSessions)} / {formatDays(subscription.validity_days)}
            </p>
          )}
        </div>

        {error && (
          <div className="bg-red-50 border border-red-200 text-red-700 text-sm rounded-xl p-3 mb-4">
            {error}
          </div>
        )}

        {step === 'confirm' && (
          <>
            {subscription.services && subscription.services.length > 0 && (
              <div className="bg-apple-bg rounded-xl p-4 mb-5">
                <p className="text-sm font-medium text-apple-text mb-2">Включено:</p>
                <ul className="space-y-1">
                  {subscription.services.map((s) => (
                    <li key={s.id} className="text-sm text-apple-gray flex justify-between">
                      <span>{s.name}</span>
                      <span className="font-medium text-apple-text">{s.quantity} шт.</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
            <button
              onClick={handleBuy}
              disabled={buying}
              className="w-full py-3 rounded-2xl text-sm font-semibold bg-apple-blue text-white hover:bg-apple-blue-hover transition-all duration-200 min-h-[44px] disabled:opacity-50"
            >
              {buying ? 'Оформление...' : 'Купить абонемент'}
            </button>
          </>
        )}

        {step === 'payment' && (
          <>
            <div className="bg-apple-bg rounded-xl p-4 mb-5 space-y-2">
              <p className="text-sm font-medium text-apple-text mb-2">Реквизиты для оплаты:</p>
              <div className="text-sm text-apple-gray">
                {businessDetail?.payment_phone ? (
                  <>
                    <p>Перевод по номеру телефона:</p>
                    <p className="font-semibold text-apple-text mt-1">{businessDetail.payment_phone}</p>
                  </>
                ) : null}
                {businessDetail?.payment_details ? (
                  <>
                    <p className={businessDetail?.payment_phone ? 'mt-2' : ''}>
                      {businessDetail?.payment_phone ? 'Или реквизиты:' : 'Реквизиты для оплаты:'}
                    </p>
                    <p className="font-semibold text-apple-text mt-1">{businessDetail.payment_details}</p>
                  </>
                ) : null}
                {!businessDetail?.payment_phone && !businessDetail?.payment_details && (
                  <p>Свяжитесь с компанией для уточнения реквизитов оплаты.</p>
                )}
              </div>
              <p className="text-xs text-apple-gray mt-3">
                В комментарии к переводу укажите ваше имя и название абонемента
              </p>
            </div>

            <button
              onClick={handlePaymentSent}
              disabled={sending}
              className="w-full py-3 rounded-2xl text-sm font-semibold bg-apple-blue text-white hover:bg-apple-blue-hover transition-all duration-200 min-h-[44px] disabled:opacity-50"
            >
              {sending ? 'Отправка...' : 'Оплата отправлена'}
            </button>
          </>
        )}

        {step === 'sent' && (
          <div className="text-center py-3">
            <CheckCircle size={24} className="text-green-500 mx-auto mb-2" />
            <p className="text-sm font-medium text-apple-text">
              Запрос отправлен! Ожидайте подтверждения.
            </p>
          </div>
        )}
      </div>
    </div>
  )
}

// ── Main Component ──

export function SubscriptionsPage() {
  const [activeTab, setActiveTab] = useState<'available' | 'my'>('available')
  const [subscriptions, setSubscriptions] = useState<SubscriptionPlan[]>([])
  const [mySubscriptions, setMySubscriptions] = useState<ClientSubscription[]>([])
  const [loading, setLoading] = useState(true)
  const [myLoading, setMyLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [myError, setMyError] = useState<string | null>(null)
  const [purchaseModal, setPurchaseModal] = useState<SubscriptionPlan | null>(null)
  const [businessDetail, setBusinessDetail] = useState<BusinessDetail | null>(null)
  const [, setBusinessId] = useState<number | null>(null)

  const isLoggedIn = !!localStorage.getItem('token')

  // Load available subscriptions
  useEffect(() => {
    const load = async () => {
      setLoading(true)
      setError(null)
      try {
        // Get businessId from URL or first business
        const params = new URLSearchParams(window.location.search)
        const bizIdParam = params.get('business_id')
        let bizId: number

        if (bizIdParam) {
          bizId = parseInt(bizIdParam, 10)
        } else {
          const businesses = await api.getBusinesses()
          if (businesses.length === 0) {
            setSubscriptions([])
            setLoading(false)
            return
          }
          bizId = businesses[0].id
        }

        setBusinessId(bizId)

        // Load subscriptions and business detail in parallel
        const [subs, detail] = await Promise.all([
          api.getSubscriptions(bizId),
          api.getBusiness(bizId),
        ])

        setSubscriptions(subs)
        setBusinessDetail(detail)
      } catch (e: unknown) {
        setError(e instanceof Error ? e.message : 'Ошибка загрузки абонементов')
      } finally {
        setLoading(false)
      }
    }
    load()
  }, [])

  // Load my subscriptions
  const loadMySubscriptions = useCallback(async () => {
    if (!isLoggedIn) return
    setMyLoading(true)
    setMyError(null)
    try {
      const subs = await api.getMySubscriptions()
      setMySubscriptions(subs)
    } catch (e: unknown) {
      setMyError(e instanceof Error ? e.message : 'Ошибка загрузки ваших абонементов')
    } finally {
      setMyLoading(false)
    }
  }, [isLoggedIn])

  useEffect(() => {
    if (isLoggedIn) {
      loadMySubscriptions()
    }
  }, [isLoggedIn, loadMySubscriptions])

  const handlePurchased = () => {
    // Reload my subscriptions after purchase
    loadMySubscriptions()
  }

  // ── Loading ──
  if (loading) {
    return (
      <div className="max-w-lg mx-auto space-y-4 pb-20">
        <div className="h-8 w-48 skeleton mb-6" />
        <div className="h-12 skeleton rounded-2xl mb-4" />
        {[1, 2, 3].map((i) => (
          <div key={i} className="h-48 skeleton rounded-2xl" />
        ))}
      </div>
    )
  }

  return (
    <div className="max-w-lg mx-auto pb-20 md:pb-8">
      <h1 className="text-2xl font-bold text-apple-text mb-6">Абонементы</h1>

      {/* Tabs */}
      <div className="flex bg-apple-bg rounded-2xl p-1 mb-6">
        <button
          onClick={() => {
            hapticSelection()
            setActiveTab('available')
          }}
          className={`flex-1 py-2.5 text-sm font-semibold rounded-xl transition-all duration-200 min-h-[44px] ${
            activeTab === 'available'
              ? 'bg-white text-apple-text shadow-sm'
              : 'text-apple-gray'
          }`}
        >
          Доступные
        </button>
        <button
          onClick={() => {
            hapticSelection()
            setActiveTab('my')
          }}
          className={`flex-1 py-2.5 text-sm font-semibold rounded-xl transition-all duration-200 min-h-[44px] ${
            activeTab === 'my'
              ? 'bg-white text-apple-text shadow-sm'
              : 'text-apple-gray'
          }`}
        >
          Мои
          {mySubscriptions.length > 0 && (
            <span className="ml-1.5 inline-flex items-center justify-center w-5 h-5 text-[11px] font-bold bg-apple-blue text-white rounded-full">
              {mySubscriptions.length}
            </span>
          )}
        </button>
      </div>

      {/* Error state */}
      {error && activeTab === 'available' && (
        <div className="bg-red-50 border border-red-200 text-red-700 text-sm rounded-xl p-4 mb-4">
          {error}
        </div>
      )}

      {/* Available subscriptions tab */}
      {activeTab === 'available' && !error && (
        <div className="space-y-4 animate-fade-in">
          {subscriptions.length === 0 ? (
            <div className="text-center py-20">
              <div className="w-16 h-16 bg-apple-bg rounded-2xl flex items-center justify-center mx-auto mb-4">
                <Package size={28} className="text-apple-gray" />
              </div>
              <h2 className="text-xl font-semibold text-apple-text mb-2">
                Нет доступных абонементов
              </h2>
              <p className="text-apple-gray">
                Абонементы пока не добавлены
              </p>
            </div>
          ) : (
            subscriptions.map((sub) => {
              const totalSessions = getTotalSessions(sub)
              return (
                <div
                  key={sub.id}
                  className="bg-white rounded-2xl shadow-sm border border-apple-border/50 p-5 transition-all duration-200"
                >
                  <div className="flex items-start justify-between mb-3">
                    <div className="flex-1 min-w-0">
                      <h3 className="font-semibold text-apple-text">{sub.name}</h3>
                      {businessDetail?.name && (
                        <p className="text-sm text-apple-gray mt-0.5">{businessDetail.name}</p>
                      )}
                    </div>
                    <div className="text-right shrink-0 ml-3">
                      <p className="text-lg font-bold text-apple-text">
                        {formatPrice(sub.price)} {'\u20BD'}
                      </p>
                    </div>
                  </div>

                  {sub.description && (
                    <p className="text-sm text-apple-gray mb-4">{sub.description}</p>
                  )}

                  <div className="flex items-center gap-4 text-sm text-apple-gray mb-4">
                    <span className="flex items-center gap-1.5">
                      <Ticket size={14} />
                      {totalSessions >= 999 ? 'Безлимит' : formatSessions(totalSessions)}
                    </span>
                    <span className="flex items-center gap-1.5">
                      <Clock size={14} />
                      {formatDays(sub.validity_days)}
                    </span>
                  </div>

                  {sub.services && sub.services.length > 0 && (
                    <div className="bg-apple-bg rounded-xl p-3 mb-4">
                      <ul className="space-y-1">
                        {sub.services.map((s) => (
                          <li key={s.id} className="text-xs text-apple-gray flex justify-between">
                            <span>{s.name}</span>
                            <span className="font-medium">{s.quantity} шт.</span>
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}

                  <button
                    onClick={() => {
                      hapticSelection()
                      setPurchaseModal(sub)
                    }}
                    className="w-full py-3 rounded-2xl text-sm font-semibold bg-apple-blue text-white hover:bg-apple-blue-hover transition-all duration-200 min-h-[44px] flex items-center justify-center gap-2"
                  >
                    Купить
                    <ChevronRight size={16} />
                  </button>
                </div>
              )
            })
          )}
        </div>
      )}

      {/* My subscriptions tab */}
      {activeTab === 'my' && (
        <div className="space-y-4 animate-fade-in">
          {!isLoggedIn ? (
            <div className="text-center py-20">
              <div className="w-16 h-16 bg-apple-bg rounded-2xl flex items-center justify-center mx-auto mb-4">
                <LogIn size={28} className="text-apple-gray" />
              </div>
              <h2 className="text-xl font-semibold text-apple-text mb-2">
                Войдите в аккаунт
              </h2>
              <p className="text-apple-gray">
                Для просмотра ваших абонементов необходимо авторизоваться
              </p>
            </div>
          ) : myLoading ? (
            <div className="space-y-4">
              {[1, 2].map((i) => (
                <div key={i} className="h-40 skeleton rounded-2xl" />
              ))}
            </div>
          ) : myError ? (
            <div className="bg-red-50 border border-red-200 text-red-700 text-sm rounded-xl p-4">
              {myError}
            </div>
          ) : mySubscriptions.length === 0 ? (
            <div className="text-center py-20">
              <div className="w-16 h-16 bg-apple-bg rounded-2xl flex items-center justify-center mx-auto mb-4">
                <Ticket size={28} className="text-apple-gray" />
              </div>
              <h2 className="text-xl font-semibold text-apple-text mb-2">
                У вас нет абонементов
              </h2>
              <p className="text-apple-gray mb-6">
                Выберите подходящий абонемент на вкладке "Доступные"
              </p>
              <button
                onClick={() => setActiveTab('available')}
                className="inline-block bg-apple-blue text-white font-medium px-6 py-3 rounded-xl hover:bg-apple-blue-hover transition-all duration-200"
              >
                Посмотреть абонементы
              </button>
            </div>
          ) : (
            mySubscriptions.map((sub) => {
              const validUntil = sub.valid_until
              const remaining = validUntil ? daysUntil(validUntil) : null
              const effectiveStatus = (sub.status === 'active' && remaining !== null && remaining < 0) ? 'expired' : sub.status
              const status = statusMap[effectiveStatus] || defaultStatus
              const StatusIcon = status.icon
              const sessionsPercent =
                sub.sessions_total > 0
                  ? Math.round((sub.sessions_remaining / sub.sessions_total) * 100)
                  : 0

              return (
                <div
                  key={sub.id}
                  className="bg-white rounded-2xl shadow-sm border border-apple-border/50 p-5 transition-all duration-200"
                >
                  <div className="flex items-start justify-between mb-3">
                    <div className="flex-1 min-w-0">
                      <h3 className="font-semibold text-apple-text">
                        {sub.subscription_name}
                      </h3>
                      {sub.business_name && (
                        <p className="text-sm text-apple-gray mt-0.5">{sub.business_name}</p>
                      )}
                    </div>
                    <span
                      className={`inline-flex items-center gap-1 text-xs font-medium px-2.5 py-1 rounded-full shrink-0 ml-2 ${status.className}`}
                    >
                      <StatusIcon size={12} />
                      {status.label}
                    </span>
                  </div>

                  {/* Sessions progress */}
                  {sub.sessions_total > 0 && sub.sessions_total < 999 && (
                    <div className="mb-4">
                      <div className="flex items-center justify-between text-sm mb-1.5">
                        <span className="text-apple-gray">Осталось посещений</span>
                        <span className="font-semibold text-apple-text">
                          {sub.sessions_remaining} из {sub.sessions_total}
                        </span>
                      </div>
                      <div className="h-2 bg-apple-bg rounded-full overflow-hidden">
                        <div
                          className="h-full bg-apple-blue rounded-full transition-all duration-500"
                          style={{ width: `${sessionsPercent}%` }}
                        />
                      </div>
                    </div>
                  )}

                  {/* Expiry info */}
                  {validUntil && (
                    <div className="flex items-center gap-1.5 text-sm">
                      <Clock size={14} className="text-apple-gray" />
                      {sub.status === 'expired' || (remaining !== null && remaining < 0) ? (
                        <span className="text-apple-danger">
                          Истёк {formatDateRu(validUntil)}
                        </span>
                      ) : remaining !== null && remaining <= 7 ? (
                        <span className="text-orange-600 font-medium">
                          Осталось {formatDays(remaining)}
                        </span>
                      ) : (
                        <span className="text-apple-gray">
                          Действует до {formatDateRu(validUntil)}
                        </span>
                      )}
                    </div>
                  )}

                  {/* Payment status */}
                  {sub.payment_status && sub.payment_status !== 'confirmed' && (
                    <div className="mt-2 text-xs text-apple-gray">
                      {sub.payment_status === 'pending' && 'Ожидается оплата'}
                      {sub.payment_status === 'sent' && 'Оплата отправлена, ожидает подтверждения'}
                    </div>
                  )}
                </div>
              )
            })
          )}
        </div>
      )}

      {/* Purchase modal */}
      {purchaseModal && (
        <PurchaseModal
          subscription={purchaseModal}
          businessDetail={businessDetail}
          onClose={() => setPurchaseModal(null)}
          onPurchased={handlePurchased}
        />
      )}
    </div>
  )
}
