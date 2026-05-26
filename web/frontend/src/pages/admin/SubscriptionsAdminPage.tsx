import { useState, useEffect } from 'react'
import { Ticket, Plus, Pencil, Trash2, X, Package, Clock, DollarSign } from 'lucide-react'
import { api, type Service, type SubscriptionAdmin, type SubscriptionCreateData } from '../../api/client'
import { useAdminBusiness } from '../../hooks/useAdminBusiness'
import { BusinessSelector } from '../../components/BusinessSelector'

function formatPrice(price?: number | null) {
  if (price == null) return '—'
  return new Intl.NumberFormat('ru-RU').format(price)
}

interface SubscriptionFormData {
  name: string
  description: string
  price: string
  validity_days: string
  rules: string
  services: { service_id: number; quantity: number }[]
}

const emptyForm: SubscriptionFormData = {
  name: '',
  description: '',
  price: '',
  validity_days: '',
  rules: '',
  services: [],
}

export function SubscriptionsAdminPage() {
  const { businesses, selectedId: businessId, selectBusiness } = useAdminBusiness()
  const [subscriptions, setSubscriptions] = useState<SubscriptionAdmin[]>([])
  const [loading, setLoading] = useState(true)
  const [editingSub, setEditingSub] = useState<SubscriptionAdmin | null>(null)
  const [isModalOpen, setIsModalOpen] = useState(false)
  const [form, setForm] = useState<SubscriptionFormData>(emptyForm)
  const [availableServices, setAvailableServices] = useState<Service[]>([])
  const [servicesLoading, setServicesLoading] = useState(false)

  useEffect(() => {
    if (!businessId) return
    setLoading(true)
    api
      .getAdminSubscriptions(businessId)
      .then((list) => {
        const sorted = [...list].sort((a, b) => {
          if (a.is_active !== b.is_active) return a.is_active ? -1 : 1
          return a.name.localeCompare(b.name, 'ru')
        })
        setSubscriptions(sorted)
      })
      .catch(() => setSubscriptions([]))
      .finally(() => setLoading(false))
  }, [businessId])

  const loadServices = () => {
    if (!businessId) return
    setServicesLoading(true)
    api
      .getServices(businessId)
      .then(setAvailableServices)
      .catch(() => setAvailableServices([]))
      .finally(() => setServicesLoading(false))
  }

  const openCreate = () => {
    setForm({ ...emptyForm, services: [] })
    setEditingSub(null)
    setIsModalOpen(true)
    loadServices()
  }

  const openEdit = (sub: SubscriptionAdmin) => {
    setForm({
      name: sub.name,
      description: sub.description || '',
      price: String(sub.price),
      validity_days: String(sub.validity_days),
      rules: sub.rules || '',
      services: sub.services.map((s) => ({ service_id: s.id, quantity: s.quantity })),
    })
    setEditingSub(sub)
    setIsModalOpen(true)
    loadServices()
  }

  const closeModal = () => {
    setIsModalOpen(false)
    setEditingSub(null)
  }

  const toggleServiceInForm = (serviceId: number) => {
    setForm((prev) => {
      const exists = prev.services.find((s) => s.service_id === serviceId)
      if (exists) {
        return { ...prev, services: prev.services.filter((s) => s.service_id !== serviceId) }
      }
      return { ...prev, services: [...prev.services, { service_id: serviceId, quantity: 1 }] }
    })
  }

  const setServiceQuantity = (serviceId: number, quantity: number) => {
    setForm((prev) => ({
      ...prev,
      services: prev.services.map((s) =>
        s.service_id === serviceId ? { ...s, quantity: Math.max(1, quantity) } : s
      ),
    }))
  }

  const handleSave = async () => {
    if (!businessId) return
    const data: SubscriptionCreateData = {
      name: form.name,
      description: form.description || undefined,
      price: Number(form.price),
      validity_days: Number(form.validity_days),
      rules: form.rules || undefined,
      services: form.services,
    }

    try {
      if (editingSub) {
        const updated = await api.updateSubscription(businessId, editingSub.id, data)
        setSubscriptions((prev) =>
          prev
            .map((s) => (s.id === editingSub.id ? updated : s))
            .sort((a, b) => {
              if (a.is_active !== b.is_active) return a.is_active ? -1 : 1
              return a.name.localeCompare(b.name, 'ru')
            })
        )
      } else {
        const created = await api.createSubscription(businessId, data)
        setSubscriptions((prev) =>
          [...prev, created].sort((a, b) => {
            if (a.is_active !== b.is_active) return a.is_active ? -1 : 1
            return a.name.localeCompare(b.name, 'ru')
          })
        )
      }
      closeModal()
    } catch (e) {
      alert('Ошибка при сохранении абонемента: ' + (e instanceof Error ? e.message : String(e)))
    }
  }

  const handleDelete = async (id: number) => {
    if (!businessId) return
    if (!confirm('Удалить абонемент?')) return
    try {
      await api.deleteSubscription(businessId, id)
      setSubscriptions((prev) => prev.filter((s) => s.id !== id))
    } catch (e) {
      alert('Ошибка при удалении абонемента: ' + (e instanceof Error ? e.message : String(e)))
    }
  }

  const toggleActive = async (id: number) => {
    if (!businessId) return
    const sub = subscriptions.find((s) => s.id === id)
    if (!sub) return
    try {
      const updated = await api.updateSubscription(businessId, id, { is_active: !sub.is_active })
      setSubscriptions((prev) =>
        prev
          .map((s) => (s.id === id ? updated : s))
          .sort((a, b) => {
            if (a.is_active !== b.is_active) return a.is_active ? -1 : 1
            return a.name.localeCompare(b.name, 'ru')
          })
      )
    } catch (e) {
      alert('Ошибка при переключении статуса: ' + (e instanceof Error ? e.message : String(e)))
    }
  }

  if (loading) {
    return (
      <div className="space-y-4">
        <div className="h-8 w-48 skeleton mb-6" />
        {[1, 2, 3].map((i) => (
          <div key={i} className="h-24 skeleton rounded-2xl" />
        ))}
      </div>
    )
  }

  return (
    <div>
      <BusinessSelector businesses={businesses} selectedId={businessId} onSelect={selectBusiness} vertical />
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-apple-text flex items-center gap-2">
          <Ticket size={24} />
          Абонементы
        </h1>
        <button
          onClick={openCreate}
          className="flex items-center gap-2 bg-apple-blue text-white text-sm font-medium px-4 py-2.5 rounded-xl hover:bg-apple-blue-hover transition-all duration-200"
        >
          <Plus size={16} />
          Добавить
        </button>
      </div>

      {/* Empty state */}
      {subscriptions.length === 0 && (
        <div className="flex flex-col items-center justify-center py-16 text-apple-gray">
          <Package size={48} className="mb-4 opacity-40" />
          <p className="text-lg font-medium mb-1">Нет абонементов</p>
          <p className="text-sm">Создайте первый абонемент</p>
        </div>
      )}

      {/* Subscriptions list */}
      <div className="space-y-3">
        {subscriptions.map((sub) => (
          <div
            key={sub.id}
            className={`bg-white rounded-2xl shadow-sm border border-apple-border/50 p-5 transition-all duration-200 ${
              !sub.is_active ? 'opacity-60' : ''
            }`}
          >
            <div className="flex items-start justify-between">
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <h3 className="font-medium text-apple-text">{sub.name}</h3>
                  {!sub.is_active && (
                    <span className="text-xs px-2 py-0.5 rounded-full bg-red-50 text-apple-danger">
                      Неактивен
                    </span>
                  )}
                </div>
                {sub.description && (
                  <p className="text-sm text-apple-gray mt-0.5">{sub.description}</p>
                )}
                <div className="flex items-center gap-4 mt-2">
                  <span className="flex items-center gap-1 text-sm font-semibold text-apple-text">
                    <DollarSign size={14} />
                    {formatPrice(sub.price)} ₽
                  </span>
                  <span className="flex items-center gap-1 text-sm text-apple-gray">
                    <Clock size={14} />
                    {sub.validity_days} дней
                  </span>
                </div>
                {sub.services.length > 0 && (
                  <div className="mt-2 space-y-0.5">
                    {sub.services.map((svc) => (
                      <p key={svc.id} className="text-sm text-apple-gray">
                        — {svc.name} x{svc.quantity}
                      </p>
                    ))}
                  </div>
                )}
                {sub.rules && (
                  <p className="text-xs text-apple-gray mt-2 line-clamp-2">{sub.rules}</p>
                )}
              </div>

              <div className="flex items-center gap-1 ml-4">
                <button
                  onClick={() => toggleActive(sub.id)}
                  className={`text-xs px-3 py-1.5 rounded-lg font-medium transition-all duration-200 ${
                    sub.is_active
                      ? 'bg-green-50 text-apple-success hover:bg-green-100'
                      : 'bg-apple-bg text-apple-gray hover:bg-gray-200'
                  }`}
                >
                  {sub.is_active ? 'Вкл' : 'Выкл'}
                </button>
                <button
                  onClick={() => openEdit(sub)}
                  className="p-2 rounded-lg text-apple-gray hover:text-apple-blue hover:bg-blue-50 transition-all duration-200"
                >
                  <Pencil size={16} />
                </button>
                <button
                  onClick={() => handleDelete(sub.id)}
                  className="p-2 rounded-lg text-apple-gray hover:text-apple-danger hover:bg-red-50 transition-all duration-200"
                >
                  <Trash2 size={16} />
                </button>
              </div>
            </div>
          </div>
        ))}
      </div>

      {/* Modal */}
      {isModalOpen && (
        <div className="fixed inset-0 bg-black/40 backdrop-blur-sm z-50 flex items-center justify-center p-4">
          <div className="bg-white rounded-2xl shadow-xl w-full max-w-md p-6 max-h-[90vh] overflow-y-auto">
            <div className="flex items-center justify-between mb-5">
              <h2 className="text-lg font-semibold text-apple-text">
                {editingSub ? 'Редактировать абонемент' : 'Новый абонемент'}
              </h2>
              <button
                onClick={closeModal}
                className="p-1 rounded-lg text-apple-gray hover:bg-apple-bg transition-all duration-200"
              >
                <X size={20} />
              </button>
            </div>

            <div className="space-y-4">
              <div>
                <label className="block text-sm text-apple-gray mb-1.5">
                  Название
                </label>
                <input
                  type="text"
                  value={form.name}
                  onChange={(e) => setForm({ ...form, name: e.target.value })}
                  placeholder="Например: Безлимит на месяц"
                  className="w-full px-4 py-3 rounded-xl border border-apple-border/50 text-sm focus:outline-none focus:border-apple-blue focus:ring-1 focus:ring-apple-blue/30 transition-all duration-200"
                />
              </div>
              <div>
                <label className="block text-sm text-apple-gray mb-1.5">
                  Описание
                </label>
                <textarea
                  value={form.description}
                  onChange={(e) => setForm({ ...form, description: e.target.value })}
                  placeholder="Краткое описание абонемента"
                  rows={2}
                  className="w-full px-4 py-3 rounded-xl border border-apple-border/50 text-sm focus:outline-none focus:border-apple-blue focus:ring-1 focus:ring-apple-blue/30 transition-all duration-200 resize-none"
                />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-sm text-apple-gray mb-1.5">
                    Цена, ₽
                  </label>
                  <input
                    type="number"
                    value={form.price}
                    onChange={(e) => setForm({ ...form, price: e.target.value })}
                    placeholder="5000"
                    className="w-full px-4 py-3 rounded-xl border border-apple-border/50 text-sm focus:outline-none focus:border-apple-blue focus:ring-1 focus:ring-apple-blue/30 transition-all duration-200"
                  />
                </div>
                <div>
                  <label className="block text-sm text-apple-gray mb-1.5">
                    Срок действия, дней
                  </label>
                  <input
                    type="number"
                    value={form.validity_days}
                    onChange={(e) => setForm({ ...form, validity_days: e.target.value })}
                    placeholder="30"
                    className="w-full px-4 py-3 rounded-xl border border-apple-border/50 text-sm focus:outline-none focus:border-apple-blue focus:ring-1 focus:ring-apple-blue/30 transition-all duration-200"
                  />
                </div>
              </div>
              <div>
                <label className="block text-sm text-apple-gray mb-1.5">
                  Правила
                </label>
                <textarea
                  value={form.rules}
                  onChange={(e) => setForm({ ...form, rules: e.target.value })}
                  placeholder="Условия использования абонемента"
                  rows={2}
                  className="w-full px-4 py-3 rounded-xl border border-apple-border/50 text-sm focus:outline-none focus:border-apple-blue focus:ring-1 focus:ring-apple-blue/30 transition-all duration-200 resize-none"
                />
              </div>

              {/* Services picker */}
              <div>
                <label className="block text-sm text-apple-gray mb-1.5">
                  Включённые услуги
                </label>
                {servicesLoading ? (
                  <div className="h-20 skeleton rounded-xl" />
                ) : availableServices.length === 0 ? (
                  <p className="text-sm text-apple-gray py-3">Нет доступных услуг</p>
                ) : (
                  <div className="space-y-2 max-h-48 overflow-y-auto border border-apple-border/50 rounded-xl p-3">
                    {availableServices
                      .filter((svc) => svc.is_active)
                      .map((svc) => {
                        const selected = form.services.find((s) => s.service_id === svc.id)
                        return (
                          <div key={svc.id} className="flex items-center gap-3">
                            <input
                              type="checkbox"
                              checked={!!selected}
                              onChange={() => toggleServiceInForm(svc.id)}
                              className="w-4 h-4 rounded border-apple-border text-apple-blue focus:ring-apple-blue/30"
                            />
                            <span className="flex-1 text-sm text-apple-text truncate">
                              {svc.name}
                              {svc.price != null && (
                                <span className="text-apple-gray ml-1">
                                  ({formatPrice(svc.price)} ₽)
                                </span>
                              )}
                            </span>
                            {selected && (
                              <input
                                type="number"
                                min={1}
                                value={selected.quantity}
                                onChange={(e) =>
                                  setServiceQuantity(svc.id, parseInt(e.target.value) || 1)
                                }
                                className="w-16 px-2 py-1 rounded-lg border border-apple-border/50 text-sm text-center focus:outline-none focus:border-apple-blue focus:ring-1 focus:ring-apple-blue/30 transition-all duration-200"
                              />
                            )}
                          </div>
                        )
                      })}
                  </div>
                )}
              </div>
            </div>

            <div className="flex gap-3 mt-6">
              <button
                onClick={closeModal}
                className="flex-1 bg-apple-bg text-apple-text font-medium py-3 rounded-xl hover:bg-gray-200 transition-all duration-200"
              >
                Отмена
              </button>
              <button
                onClick={handleSave}
                disabled={!form.name || !form.price || !form.validity_days}
                className="flex-1 bg-apple-blue text-white font-medium py-3 rounded-xl hover:bg-apple-blue-hover transition-all duration-200 disabled:opacity-50"
              >
                {editingSub ? 'Сохранить' : 'Создать'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
