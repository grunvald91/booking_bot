import { useState, useEffect } from 'react'
import {
  Scissors,
  Plus,
  Pencil,
  Trash2,
  X,
  Clock,
  ChevronUp,
  ChevronDown,
} from 'lucide-react'
import { api, type Service, type GroupPricingTier } from '../../api/client'
import { useAdminBusiness } from '../../hooks/useAdminBusiness'
import { BusinessSelector } from '../../components/BusinessSelector'

const placeholderServices: Service[] = [
  { id: 1, name: 'Стрижка женская', description: 'Стрижка с укладкой', price: 2500, duration_minutes: 60, is_active: true, sort_order: 0 },
  { id: 2, name: 'Окрашивание', description: 'Однотонное окрашивание', price: 5000, duration_minutes: 120, is_active: true, sort_order: 1 },
  { id: 3, name: 'Маникюр', description: 'Классический маникюр с покрытием', price: 2000, duration_minutes: 90, is_active: true, sort_order: 2 },
  { id: 4, name: 'Укладка', description: 'Профессиональная укладка', price: 1500, duration_minutes: 45, is_active: true, sort_order: 3 },
  { id: 5, name: 'Мужская стрижка', description: 'Стрижка машинкой и ножницами', price: 1500, duration_minutes: 40, is_active: true, sort_order: 4 },
  { id: 6, name: 'Педикюр', description: 'Классический педикюр', price: 2500, duration_minutes: 75, is_active: false, sort_order: 5 },
]

function formatPrice(price?: number | null, isHourly?: boolean) {
  if (price == null) return '—'
  const formatted = new Intl.NumberFormat('ru-RU').format(price)
  return isHourly ? `${formatted} ₽/ч` : `${formatted} ₽`
}

function formatDuration(minutes?: number | null) {
  if (!minutes || minutes <= 0) return '—'
  if (minutes < 60) return `${minutes} мин`
  const h = Math.floor(minutes / 60)
  const m = minutes % 60
  return m ? `${h} ч ${m} мин` : `${h} ч`
}

interface ServiceFormData {
  name: string
  description: string
  price: string
  duration: string
  is_additional: boolean
  is_hourly_price: boolean
  pricing_type: string
  group_pricing: GroupPricingTier[]
}

function ToggleSwitch({
  checked,
  onChange,
  label,
}: {
  checked: boolean
  onChange: (val: boolean) => void
  label: string
}) {
  return (
    <label className="flex items-center gap-3 cursor-pointer">
      <div className="relative">
        <input
          type="checkbox"
          checked={checked}
          onChange={(e) => onChange(e.target.checked)}
          className="sr-only peer"
        />
        <div className="w-11 h-6 bg-gray-200 peer-focus:outline-none rounded-full peer peer-checked:bg-apple-blue transition-colors" />
        <div className="absolute left-[2px] top-[2px] bg-white w-5 h-5 rounded-full transition-transform peer-checked:translate-x-5 shadow-sm" />
      </div>
      <span className="text-sm text-apple-text">{label}</span>
    </label>
  )
}

export function ServicesPage() {
  const { businesses, selectedId: businessId, selectBusiness } = useAdminBusiness()
  const [services, setServices] = useState<Service[]>([])
  const [loading, setLoading] = useState(true)
  const [editingService, setEditingService] = useState<Service | null>(null)
  const [isCreating, setIsCreating] = useState(false)
  const [form, setForm] = useState<ServiceFormData>({
    name: '',
    description: '',
    price: '',
    duration: '',
    is_additional: false,
    is_hourly_price: false,
    pricing_type: 'fixed',
    group_pricing: [],
  })

  useEffect(() => {
    if (!businessId) return
    setLoading(true)
    api
      .getServices(businessId)
      .then(setServices)
      .catch(() => setServices(placeholderServices))
      .finally(() => setLoading(false))
  }, [businessId])

  const openCreate = () => {
    setForm({ name: '', description: '', price: '', duration: '', is_additional: false, is_hourly_price: false, pricing_type: 'fixed', group_pricing: [] })
    setEditingService(null)
    setIsCreating(true)
  }

  const openEdit = (service: Service) => {
    setForm({
      name: service.name,
      description: service.description || '',
      price: String(service.price ?? ''),
      duration: String(service.duration_minutes ?? service.duration ?? ''),
      is_additional: service.is_additional ?? false,
      is_hourly_price: service.is_hourly_price ?? false,
      pricing_type: service.pricing_type || 'fixed',
      group_pricing: service.group_pricing || [],
    })
    setEditingService(service)
    setIsCreating(true)
  }

  const closeModal = () => {
    setIsCreating(false)
    setEditingService(null)
  }

  const handleSave = async () => {
    const data: Partial<Service> = {
      name: form.name,
      description: form.description,
      price: form.price ? Number(form.price) : undefined,
      duration_minutes: form.duration ? Number(form.duration) : undefined,
      is_active: editingService?.is_active ?? true,
      is_additional: form.is_additional,
      is_hourly_price: form.is_hourly_price,
      pricing_type: form.pricing_type,
      group_pricing: form.pricing_type === 'per_person' && form.group_pricing.length > 0 ? form.group_pricing : null,
    }

    try {
      if (editingService) {
        const updated = await api.updateService(businessId!, editingService.id, data)
        setServices((prev) =>
          prev.map((s) => (s.id === editingService.id ? updated : s))
        )
      } else {
        const created = await api.createService(businessId!, data)
        setServices((prev) => [...prev, created])
      }
      closeModal()
    } catch (e) {
      alert('Ошибка при сохранении услуги: ' + (e instanceof Error ? e.message : String(e)))
    }
  }

  const handleDelete = async (id: number) => {
    if (!confirm('Удалить услугу?')) return
    try {
      await api.deleteService(businessId!, id)
      setServices((prev) => prev.filter((s) => s.id !== id))
    } catch (e) {
      alert('Ошибка при удалении услуги: ' + (e instanceof Error ? e.message : String(e)))
    }
  }

  const toggleActive = async (id: number) => {
    const service = services.find((s) => s.id === id)
    if (!service) return
    try {
      const updated = await api.updateService(businessId!, id, { is_active: !service.is_active })
      setServices((prev) =>
        prev.map((s) => (s.id === id ? updated : s))
      )
    } catch (e) {
      alert('Ошибка при переключении статуса: ' + (e instanceof Error ? e.message : String(e)))
    }
  }

  // Sort services by sort_order, then by id as fallback
  const sortedServices = [...services].sort((a, b) => {
    const orderA = a.sort_order ?? 9999
    const orderB = b.sort_order ?? 9999
    if (orderA !== orderB) return orderA - orderB
    return a.id - b.id
  })

  const mainServices = sortedServices.filter((s) => !s.is_additional)
  const additionalServices = sortedServices.filter((s) => s.is_additional)

  const handleMoveUp = async (service: Service, group: Service[]) => {
    const idx = group.findIndex((s) => s.id === service.id)
    if (idx <= 0) return

    const newGroup = [...group]
    ;[newGroup[idx - 1], newGroup[idx]] = [newGroup[idx], newGroup[idx - 1]]

    // Build the full ordered list: main first, then additional
    const isAdditionalGroup = service.is_additional
    const otherGroup = isAdditionalGroup ? mainServices : additionalServices
    const fullOrder = isAdditionalGroup
      ? [...otherGroup, ...newGroup]
      : [...newGroup, ...otherGroup]

    // Update sort_order locally
    const updatedServices = fullOrder.map((s, i) => ({ ...s, sort_order: i }))
    setServices(updatedServices)

    // Persist to server
    try {
      await api.reorderServices(businessId!, fullOrder.map((s) => s.id))
    } catch (e) {
      alert('Ошибка при сортировке: ' + (e instanceof Error ? e.message : String(e)))
      // Reload on error
      api.getServices(businessId!).then(setServices).catch(() => {})
    }
  }

  const handleMoveDown = async (service: Service, group: Service[]) => {
    const idx = group.findIndex((s) => s.id === service.id)
    if (idx < 0 || idx >= group.length - 1) return

    const newGroup = [...group]
    ;[newGroup[idx], newGroup[idx + 1]] = [newGroup[idx + 1], newGroup[idx]]

    // Build the full ordered list: main first, then additional
    const isAdditionalGroup = service.is_additional
    const otherGroup = isAdditionalGroup ? mainServices : additionalServices
    const fullOrder = isAdditionalGroup
      ? [...otherGroup, ...newGroup]
      : [...newGroup, ...otherGroup]

    // Update sort_order locally
    const updatedServices = fullOrder.map((s, i) => ({ ...s, sort_order: i }))
    setServices(updatedServices)

    // Persist to server
    try {
      await api.reorderServices(businessId!, fullOrder.map((s) => s.id))
    } catch (e) {
      alert('Ошибка при сортировке: ' + (e instanceof Error ? e.message : String(e)))
      api.getServices(businessId!).then(setServices).catch(() => {})
    }
  }

  const renderServiceCard = (service: Service, group: Service[], idx: number) => (
    <div
      key={service.id}
      className={`bg-white rounded-2xl shadow-sm border border-apple-border/50 p-5 transition-all duration-200 ${
        !service.is_active ? 'opacity-60' : ''
      }`}
    >
      <div className="flex items-start justify-between">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <h3 className="font-medium text-apple-text">{service.name}</h3>
            {service.is_additional && (
              <span className="text-xs px-2 py-0.5 rounded-full bg-blue-50 text-blue-600">
                Доп. услуга
              </span>
            )}
            {!service.is_active && (
              <span className="text-xs px-2 py-0.5 rounded-full bg-red-50 text-apple-danger">
                Неактивна
              </span>
            )}
          </div>
          <p className="text-sm text-apple-gray mt-0.5">
            {service.description}
          </p>
          <div className="flex items-center gap-4 mt-2">
            <span className="flex items-center gap-1 text-sm font-semibold text-apple-text">
              {formatPrice(service.price, service.is_hourly_price)}
              {service.pricing_type === 'per_person' && (
                <span className="text-xs font-normal text-apple-gray">/чел</span>
              )}
            </span>
            <span className="flex items-center gap-1 text-sm text-apple-gray">
              <Clock size={14} />
              {formatDuration(service.duration_minutes ?? service.duration)}
            </span>
            {service.pricing_type === 'per_person' && service.group_pricing && service.group_pricing.length > 0 && (
              <span className="text-xs text-blue-600 bg-blue-50 px-1.5 py-0.5 rounded">
                {service.group_pricing.length} тариф{service.group_pricing.length > 1 ? (service.group_pricing.length < 5 ? 'а' : 'ов') : ''}
              </span>
            )}
          </div>
        </div>

        <div className="flex items-center gap-1 ml-4">
          {/* Reorder buttons */}
          <div className="flex flex-col gap-0.5 mr-1">
            <button
              onClick={() => handleMoveUp(service, group)}
              disabled={idx === 0}
              className="p-1 rounded-md text-apple-gray hover:text-apple-blue hover:bg-blue-50 transition-all duration-200 disabled:opacity-30 disabled:hover:text-apple-gray disabled:hover:bg-transparent"
              title="Переместить вверх"
            >
              <ChevronUp size={14} />
            </button>
            <button
              onClick={() => handleMoveDown(service, group)}
              disabled={idx === group.length - 1}
              className="p-1 rounded-md text-apple-gray hover:text-apple-blue hover:bg-blue-50 transition-all duration-200 disabled:opacity-30 disabled:hover:text-apple-gray disabled:hover:bg-transparent"
              title="Переместить вниз"
            >
              <ChevronDown size={14} />
            </button>
          </div>

          <button
            onClick={() => toggleActive(service.id)}
            className={`text-xs px-3 py-1.5 rounded-lg font-medium transition-all duration-200 ${
              service.is_active
                ? 'bg-green-50 text-apple-success hover:bg-green-100'
                : 'bg-apple-bg text-apple-gray hover:bg-gray-200'
            }`}
          >
            {service.is_active ? 'Вкл' : 'Выкл'}
          </button>
          <button
            onClick={() => openEdit(service)}
            className="p-2 rounded-lg text-apple-gray hover:text-apple-blue hover:bg-blue-50 transition-all duration-200"
          >
            <Pencil size={16} />
          </button>
          <button
            onClick={() => handleDelete(service.id)}
            className="p-2 rounded-lg text-apple-gray hover:text-apple-danger hover:bg-red-50 transition-all duration-200"
          >
            <Trash2 size={16} />
          </button>
        </div>
      </div>
    </div>
  )

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
          <Scissors size={24} />
          Услуги
        </h1>
        <button
          onClick={openCreate}
          className="flex items-center gap-2 bg-apple-blue text-white text-sm font-medium px-4 py-2.5 rounded-xl hover:bg-apple-blue-hover transition-all duration-200"
        >
          <Plus size={16} />
          Добавить услугу
        </button>
      </div>

      {/* Main services section */}
      {mainServices.length > 0 && (
        <div className="mb-6">
          <h2 className="text-sm font-semibold text-apple-gray uppercase tracking-wide mb-3">
            Основные услуги
          </h2>
          <div className="space-y-3">
            {mainServices.map((service, idx) =>
              renderServiceCard(service, mainServices, idx)
            )}
          </div>
        </div>
      )}

      {/* Additional services section */}
      {additionalServices.length > 0 && (
        <div className="mb-6">
          <h2 className="text-sm font-semibold text-apple-gray uppercase tracking-wide mb-3">
            Дополнительные услуги
          </h2>
          <div className="space-y-3">
            {additionalServices.map((service, idx) =>
              renderServiceCard(service, additionalServices, idx)
            )}
          </div>
        </div>
      )}

      {/* Empty state */}
      {services.length === 0 && (
        <div className="text-center text-apple-gray py-12">
          <Scissors size={40} className="mx-auto mb-3 opacity-30" />
          <p>Нет услуг. Нажмите «Добавить услугу» чтобы создать первую.</p>
        </div>
      )}

      {/* Modal */}
      {isCreating && (
        <div className="fixed inset-0 bg-black/40 backdrop-blur-sm z-50 flex items-center justify-center p-4">
          <div className="bg-white rounded-2xl shadow-xl w-full max-w-md p-6">
            <div className="flex items-center justify-between mb-5">
              <h2 className="text-lg font-semibold text-apple-text">
                {editingService ? 'Редактировать услугу' : 'Новая услуга'}
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
                  placeholder="Например: Стрижка женская"
                  className="w-full px-4 py-3 rounded-xl border border-apple-border/50 text-sm focus:outline-none focus:border-apple-blue focus:ring-1 focus:ring-apple-blue/30 transition-all duration-200"
                />
              </div>
              <div>
                <label className="block text-sm text-apple-gray mb-1.5">
                  Описание
                </label>
                <input
                  type="text"
                  value={form.description}
                  onChange={(e) =>
                    setForm({ ...form, description: e.target.value })
                  }
                  placeholder="Краткое описание"
                  className="w-full px-4 py-3 rounded-xl border border-apple-border/50 text-sm focus:outline-none focus:border-apple-blue focus:ring-1 focus:ring-apple-blue/30 transition-all duration-200"
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
                    placeholder="2500"
                    className="w-full px-4 py-3 rounded-xl border border-apple-border/50 text-sm focus:outline-none focus:border-apple-blue focus:ring-1 focus:ring-apple-blue/30 transition-all duration-200"
                  />
                </div>
                <div>
                  <label className="block text-sm text-apple-gray mb-1.5">
                    Длительность, мин
                  </label>
                  <input
                    type="number"
                    value={form.duration}
                    onChange={(e) =>
                      setForm({ ...form, duration: e.target.value })
                    }
                    placeholder="60"
                    className="w-full px-4 py-3 rounded-xl border border-apple-border/50 text-sm focus:outline-none focus:border-apple-blue focus:ring-1 focus:ring-apple-blue/30 transition-all duration-200"
                  />
                </div>
              </div>

              {/* Toggle switches */}
              <div className="space-y-3 pt-1">
                <ToggleSwitch
                  checked={form.is_additional}
                  onChange={(val) => setForm({ ...form, is_additional: val })}
                  label="Дополнительная услуга"
                />
                <ToggleSwitch
                  checked={form.is_hourly_price}
                  onChange={(val) => setForm({ ...form, is_hourly_price: val })}
                  label="Почасовая цена"
                />
              </div>

              {/* Pricing type */}
              <div className="pt-2 border-t border-apple-border/30">
                <label className="block text-sm text-apple-gray mb-1.5">
                  Тип ценообразования
                </label>
                <select
                  value={form.pricing_type}
                  onChange={(e) => setForm({ ...form, pricing_type: e.target.value })}
                  className="w-full px-4 py-3 rounded-xl border border-apple-border/50 text-sm focus:outline-none focus:border-apple-blue focus:ring-1 focus:ring-apple-blue/30 transition-all duration-200 bg-white"
                >
                  <option value="fixed">Фиксированная цена</option>
                  <option value="per_person">По количеству человек</option>
                </select>
              </div>

              {/* Group pricing tiers */}
              {form.pricing_type === 'per_person' && (
                <div>
                  <div className="flex items-center justify-between mb-2">
                    <label className="text-sm text-apple-gray">Тарифы по кол-ву человек</label>
                    <button
                      type="button"
                      onClick={() => {
                        const lastMax = form.group_pricing.length > 0
                          ? form.group_pricing[form.group_pricing.length - 1].max_people + 1
                          : 1
                        setForm({
                          ...form,
                          group_pricing: [
                            ...form.group_pricing,
                            { min_people: lastMax, max_people: lastMax + 4, price: Number(form.price) || 0 },
                          ],
                        })
                      }}
                      className="text-xs text-apple-blue font-medium flex items-center gap-1 hover:underline"
                    >
                      <Plus size={12} />
                      Добавить тариф
                    </button>
                  </div>
                  {form.group_pricing.length === 0 && (
                    <p className="text-xs text-apple-gray italic">
                      Добавьте тарифы для разного количества человек
                    </p>
                  )}
                  <div className="space-y-2">
                    {form.group_pricing.map((tier, idx) => (
                      <div key={idx} className="flex items-center gap-2 bg-apple-bg rounded-xl p-2.5">
                        <div className="flex items-center gap-1 flex-1">
                          <input
                            type="number"
                            min={1}
                            value={tier.min_people}
                            onChange={(e) => {
                              const newTiers = [...form.group_pricing]
                              newTiers[idx] = { ...newTiers[idx], min_people: Number(e.target.value) || 1 }
                              setForm({ ...form, group_pricing: newTiers })
                            }}
                            className="w-12 px-2 py-1.5 rounded-lg border border-apple-border/50 text-xs text-center"
                          />
                          <span className="text-xs text-apple-gray">—</span>
                          <input
                            type="number"
                            min={1}
                            value={tier.max_people}
                            onChange={(e) => {
                              const newTiers = [...form.group_pricing]
                              newTiers[idx] = { ...newTiers[idx], max_people: Number(e.target.value) || 1 }
                              setForm({ ...form, group_pricing: newTiers })
                            }}
                            className="w-12 px-2 py-1.5 rounded-lg border border-apple-border/50 text-xs text-center"
                          />
                          <span className="text-xs text-apple-gray shrink-0">чел</span>
                        </div>
                        <div className="flex items-center gap-1">
                          <input
                            type="number"
                            value={tier.price}
                            onChange={(e) => {
                              const newTiers = [...form.group_pricing]
                              newTiers[idx] = { ...newTiers[idx], price: Number(e.target.value) || 0 }
                              setForm({ ...form, group_pricing: newTiers })
                            }}
                            className="w-20 px-2 py-1.5 rounded-lg border border-apple-border/50 text-xs text-right"
                          />
                          <span className="text-xs text-apple-gray">₽</span>
                        </div>
                        <button
                          type="button"
                          onClick={() => {
                            const newTiers = form.group_pricing.filter((_, i) => i !== idx)
                            setForm({ ...form, group_pricing: newTiers })
                          }}
                          className="p-1 text-apple-gray hover:text-apple-danger transition-colors"
                        >
                          <Trash2 size={12} />
                        </button>
                      </div>
                    ))}
                  </div>
                </div>
              )}
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
                disabled={!form.name || !form.price || !form.duration}
                className="flex-1 bg-apple-blue text-white font-medium py-3 rounded-xl hover:bg-apple-blue-hover transition-all duration-200 disabled:opacity-50"
              >
                {editingService ? 'Сохранить' : 'Создать'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
