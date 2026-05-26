import { useState, useEffect, useCallback, useRef } from 'react'
import { Users, Plus, Pencil, Trash2, X, User, Shield, Clock, MapPin, Users as UsersIcon, Calendar, ChevronLeft, ChevronRight, ImagePlus, ImageIcon } from 'lucide-react'
import { api, type Employee, type Service } from '../../api/client'
import { useAdminBusiness } from '../../hooks/useAdminBusiness'
import { BusinessSelector } from '../../components/BusinessSelector'

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

const placeholderEmployees: Employee[] = [
  { id: 1, name: 'Анна Иванова', role: 'master', specialization: 'Парикмахер-стилист', is_active: true },
  { id: 2, name: 'Мария Петрова', role: 'master', specialization: 'Мастер маникюра', is_active: true },
  { id: 3, name: 'Елена Сидорова', role: 'master', specialization: 'Колорист', is_active: true },
  { id: 4, name: 'Ольга Козлова', role: 'admin', specialization: 'Администратор', is_active: true },
  { id: 5, name: 'Дарья Новикова', role: 'master', specialization: 'Косметолог', is_active: false },
]

const roleBadge: Record<string, { label: string; className: string }> = {
  master: { label: 'Мастер', className: 'bg-blue-50 text-blue-700' },
  admin: { label: 'Администратор', className: 'bg-purple-50 text-purple-700' },
}

function getTodayStr(): string {
  const d = new Date()
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

interface EmployeeForm {
  name: string
  role: string
  specialization: string
  description: string
  telegram_id: string
  booking_interval_minutes: string
  capacity: string
  area_sqm: string
  min_booking_minutes: string
  solo_price_per_hour: string
}

const emptyForm: EmployeeForm = {
  name: '',
  role: 'master',
  specialization: '',
  description: '',
  telegram_id: '',
  booking_interval_minutes: '',
  capacity: '',
  area_sqm: '',
  min_booking_minutes: '',
  solo_price_per_hour: '',
}

export function EmployeesPage() {
  const { businesses, selectedId: businessId, selectBusiness } = useAdminBusiness()
  const [employees, setEmployees] = useState<Employee[]>([])
  const [loading, setLoading] = useState(true)
  const [isModalOpen, setIsModalOpen] = useState(false)
  const [editingEmployee, setEditingEmployee] = useState<Employee | null>(null)
  const [form, setForm] = useState<EmployeeForm>({ ...emptyForm })

  // Services for employee-service linking
  const [allServices, setAllServices] = useState<Service[]>([])
  const [selectedServiceIds, setSelectedServiceIds] = useState<number[]>([])
  const [servicesLoading, setServicesLoading] = useState(false)

  // Photos for the employee being edited
  const [employeePhotos, setEmployeePhotos] = useState<string[]>([])
  const [photoUploading, setPhotoUploading] = useState(false)
  const photoInputRef = useRef<HTMLInputElement>(null)

  // Duty toggling state
  const [dutyLoading, setDutyLoading] = useState<number | null>(null)

  // Duty schedule modal
  const [dutyModalEmp, setDutyModalEmp] = useState<Employee | null>(null)
  const [dutyDates, setDutyDates] = useState<Set<string>>(new Set())
  const [dutyMonthOffset, setDutyMonthOffset] = useState(0)
  const [dutySaving, setDutySaving] = useState(false)

  const isVenueRental = businesses.find(b => b.id === businessId)?.business_type === 'venue_rental'

  useEffect(() => {
    if (!businessId) return
    setLoading(true)
    api
      .getEmployees(businessId)
      .then(setEmployees)
      .catch(() => setEmployees(placeholderEmployees))
      .finally(() => setLoading(false))
  }, [businessId])

  // Load services when modal opens
  const loadServices = useCallback(async (empId?: number) => {
    if (!businessId) return
    setServicesLoading(true)
    try {
      const svcs = await api.getServices(businessId)
      setAllServices(svcs)

      if (empId) {
        // Load linked services for this employee
        const linked = await api.getEmployeeServices(businessId, empId)
        setSelectedServiceIds(linked.map(l => l.service_id))
      } else {
        setSelectedServiceIds([])
      }
    } catch {
      setAllServices([])
      setSelectedServiceIds([])
    } finally {
      setServicesLoading(false)
    }
  }, [businessId])

  const openCreate = () => {
    setForm({ ...emptyForm })
    setEditingEmployee(null)
    setSelectedServiceIds([])
    setAllServices([])
    setEmployeePhotos([])
    setIsModalOpen(true)
    loadServices()
  }

  const openEdit = (emp: Employee) => {
    setForm({
      name: emp.name,
      role: emp.role || 'master',
      specialization: emp.specialization || '',
      description: emp.description || '',
      telegram_id: emp.telegram_id ? String(emp.telegram_id) : '',
      booking_interval_minutes: emp.booking_interval_minutes ? String(emp.booking_interval_minutes) : '',
      capacity: emp.capacity ? String(emp.capacity) : '',
      area_sqm: emp.area_sqm ? String(emp.area_sqm) : '',
      min_booking_minutes: emp.min_booking_minutes ? String(emp.min_booking_minutes) : '',
      solo_price_per_hour: emp.solo_price_per_hour ? String(emp.solo_price_per_hour) : '',
    })
    setEditingEmployee(emp)
    setSelectedServiceIds(emp.service_ids || [])
    setAllServices([])
    setEmployeePhotos(parsePhotos(emp.photos))
    setIsModalOpen(true)
    loadServices(emp.id)
  }

  const closeModal = () => {
    setIsModalOpen(false)
    setEditingEmployee(null)
    setEmployeePhotos([])
  }

  const handlePhotoUpload = async (file: File) => {
    if (!businessId || !editingEmployee) {
      alert('Сначала сохраните сотрудника, затем добавьте фото.')
      return
    }
    setPhotoUploading(true)
    try {
      const res = await api.uploadEmployeePhoto(businessId, editingEmployee.id, file)
      setEmployeePhotos(res.photos)
      setEmployees((prev) =>
        prev.map((e) =>
          e.id === editingEmployee.id ? { ...e, photos: JSON.stringify(res.photos) } : e
        )
      )
    } catch (e) {
      alert('Ошибка загрузки фото: ' + (e instanceof Error ? e.message : String(e)))
    } finally {
      setPhotoUploading(false)
      if (photoInputRef.current) photoInputRef.current.value = ''
    }
  }

  const handlePhotoDelete = async (index: number) => {
    if (!businessId || !editingEmployee) return
    if (!confirm('Удалить это фото?')) return
    try {
      const res = await api.deleteEmployeePhoto(businessId, editingEmployee.id, index)
      setEmployeePhotos(res.photos)
      setEmployees((prev) =>
        prev.map((e) =>
          e.id === editingEmployee.id
            ? { ...e, photos: res.photos.length > 0 ? JSON.stringify(res.photos) : undefined }
            : e
        )
      )
    } catch (e) {
      alert('Ошибка удаления фото: ' + (e instanceof Error ? e.message : String(e)))
    }
  }

  const handleSave = async () => {
    const data: Partial<Employee> = {
      name: form.name,
      role: form.role,
      specialization: form.specialization,
      description: form.description || undefined,
      is_active: editingEmployee?.is_active ?? true,
      telegram_id: form.telegram_id ? parseInt(form.telegram_id) : undefined,
      booking_interval_minutes: form.booking_interval_minutes ? parseInt(form.booking_interval_minutes) : undefined,
    }

    if (isVenueRental) {
      data.capacity = form.capacity ? parseInt(form.capacity) : undefined
      data.area_sqm = form.area_sqm ? parseFloat(form.area_sqm) : undefined
      data.min_booking_minutes = form.min_booking_minutes ? parseInt(form.min_booking_minutes) : undefined
      data.solo_price_per_hour = form.solo_price_per_hour ? parseFloat(form.solo_price_per_hour) : undefined
    }

    try {
      let savedEmp: Employee
      if (editingEmployee) {
        savedEmp = await api.updateEmployee(businessId!, editingEmployee.id, data)
        setEmployees((prev) =>
          prev.map((e) => (e.id === editingEmployee.id ? { ...savedEmp, service_ids: selectedServiceIds } : e))
        )
      } else {
        savedEmp = await api.createEmployee(businessId!, data)
        setEmployees((prev) => [...prev, { ...savedEmp, service_ids: selectedServiceIds }])
      }

      // Save employee-service links
      if (businessId && savedEmp.id) {
        try {
          await api.setEmployeeServices(businessId, savedEmp.id, selectedServiceIds)
        } catch {
          // Non-critical: don't block save
        }
      }

      closeModal()
    } catch (e) {
      alert('Ошибка при сохранении сотрудника: ' + (e instanceof Error ? e.message : String(e)))
    }
  }

  const handleDelete = async (id: number) => {
    if (!confirm('Удалить сотрудника?')) return
    try {
      await api.deleteEmployee(businessId!, id)
      setEmployees((prev) => prev.filter((e) => e.id !== id))
    } catch (e) {
      alert('Ошибка при удалении сотрудника: ' + (e instanceof Error ? e.message : String(e)))
    }
  }

  const toggleActive = async (id: number) => {
    const emp = employees.find((e) => e.id === id)
    if (!emp) return
    try {
      const updated = await api.updateEmployee(businessId!, id, { is_active: !emp.is_active })
      setEmployees((prev) =>
        prev.map((e) => (e.id === id ? updated : e))
      )
    } catch (e) {
      alert('Ошибка при переключении статуса: ' + (e instanceof Error ? e.message : String(e)))
    }
  }

  const handleToggleDuty = async (empId: number) => {
    if (!businessId || dutyLoading !== null) return
    setDutyLoading(empId)
    try {
      const result = await api.toggleDuty(businessId, empId)
      setEmployees((prev) =>
        prev.map((e) =>
          e.id === empId
            ? { ...e, on_duty_date: result.on_duty ? result.date : undefined }
            : e
        )
      )
    } catch (e) {
      alert('Ошибка при переключении дежурства: ' + (e instanceof Error ? e.message : String(e)))
    } finally {
      setDutyLoading(null)
    }
  }

  const openDutySchedule = async (emp: Employee) => {
    setDutyModalEmp(emp)
    setDutyMonthOffset(0)
    try {
      const result = await api.getDutySchedule(businessId!, emp.id)
      setDutyDates(new Set(result.dates))
    } catch {
      setDutyDates(new Set())
    }
  }

  const toggleDutyDate = (dateStr: string) => {
    setDutyDates((prev) => {
      const next = new Set(prev)
      if (next.has(dateStr)) {
        next.delete(dateStr)
      } else {
        next.add(dateStr)
      }
      return next
    })
  }

  const saveDutySchedule = async () => {
    if (!businessId || !dutyModalEmp) return
    setDutySaving(true)
    try {
      await api.setDutySchedule(businessId, dutyModalEmp.id, Array.from(dutyDates))
      setDutyModalEmp(null)
    } catch (e) {
      alert('Ошибка сохранения графика: ' + (e instanceof Error ? e.message : String(e)))
    } finally {
      setDutySaving(false)
    }
  }

  const toggleServiceLink = (serviceId: number) => {
    setSelectedServiceIds((prev) =>
      prev.includes(serviceId)
        ? prev.filter((id) => id !== serviceId)
        : [...prev, serviceId]
    )
  }

  const inputClass =
    'w-full px-4 py-3 rounded-xl border border-apple-border/50 text-sm focus:outline-none focus:border-apple-blue focus:ring-1 focus:ring-apple-blue/30 transition-all duration-200'

  if (loading) {
    return (
      <div className="space-y-4">
        <div className="h-8 w-48 skeleton mb-6" />
        {[1, 2, 3].map((i) => (
          <div key={i} className="h-20 skeleton rounded-2xl" />
        ))}
      </div>
    )
  }

  const today = getTodayStr()

  return (
    <div>
      <BusinessSelector businesses={businesses} selectedId={businessId} onSelect={selectBusiness} vertical />
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-apple-text flex items-center gap-2">
          <Users size={24} />
          Сотрудники
        </h1>
        <button
          onClick={openCreate}
          className="flex items-center gap-2 bg-apple-blue text-white text-sm font-medium px-4 py-2.5 rounded-xl hover:bg-apple-blue-hover transition-all duration-200"
        >
          <Plus size={16} />
          Добавить
        </button>
      </div>

      {/* Employees grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {employees.map((emp) => {
          const badge = roleBadge[emp.role || 'master'] || roleBadge.master
          const isOnDuty = emp.on_duty_date === today
          return (
            <div
              key={emp.id}
              className={`bg-white rounded-2xl shadow-sm border border-apple-border/50 p-3 transition-all duration-200 ${
                emp.is_active === false ? 'opacity-60' : ''
              }`}
            >
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 bg-apple-bg rounded-full flex items-center justify-center shrink-0">
                  <User size={18} className="text-apple-gray" />
                </div>
                <div className="flex-1 min-w-0">
                  <h3 className="font-medium text-apple-text truncate">{emp.name}</h3>
                  <p className="text-xs text-apple-gray truncate">{emp.specialization || badge.label}</p>
                  {emp.telegram_id && (
                    <p className="text-[10px] text-apple-gray/60 truncate">
                      TG ID: {emp.telegram_id}
                    </p>
                  )}
                </div>
                <div className="flex items-center gap-1 shrink-0">
                  <button
                    onClick={() => toggleActive(emp.id)}
                    className={`text-xs px-2 py-1 rounded-lg font-medium transition-all duration-200 ${
                      emp.is_active !== false
                        ? 'bg-green-50 text-apple-success'
                        : 'bg-apple-bg text-apple-gray'
                    }`}
                  >
                    {emp.is_active !== false ? 'Вкл' : 'Выкл'}
                  </button>
                  <button
                    onClick={() => openEdit(emp)}
                    className="p-1.5 rounded-lg text-apple-gray hover:text-apple-blue hover:bg-blue-50 transition-all duration-200"
                  >
                    <Pencil size={14} />
                  </button>
                  <button
                    onClick={() => handleDelete(emp.id)}
                    className="p-1.5 rounded-lg text-apple-gray hover:text-apple-danger hover:bg-red-50 transition-all duration-200"
                  >
                    <Trash2 size={14} />
                  </button>
                </div>
              </div>

              {/* Info badges row */}
              <div className="flex flex-wrap items-center gap-1.5 mt-2 ml-[52px]">
                {/* Duty badge */}
                <button
                  onClick={() => handleToggleDuty(emp.id)}
                  disabled={dutyLoading === emp.id}
                  className={`inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-lg font-medium transition-all duration-200 cursor-pointer ${
                    isOnDuty
                      ? 'bg-green-50 text-green-700 hover:bg-green-100'
                      : 'bg-gray-50 text-apple-gray hover:bg-gray-100'
                  } ${dutyLoading === emp.id ? 'opacity-50' : ''}`}
                >
                  <Shield size={10} />
                  {isOnDuty ? 'На дежурстве' : 'Не дежурит'}
                </button>
                <button
                  onClick={() => openDutySchedule(emp)}
                  className="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-lg font-medium bg-purple-50 text-purple-600 hover:bg-purple-100 transition-all duration-200 cursor-pointer"
                >
                  <Calendar size={10} />
                  График
                </button>

                {/* Booking interval */}
                {emp.booking_interval_minutes && (
                  <span className="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-lg bg-blue-50 text-blue-600">
                    <Clock size={10} />
                    Интервал: {emp.booking_interval_minutes} мин
                  </span>
                )}

                {/* Venue rental badges */}
                {isVenueRental && emp.capacity && (
                  <span className="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-lg bg-orange-50 text-orange-600">
                    <UsersIcon size={10} />
                    {emp.capacity} чел
                  </span>
                )}
                {isVenueRental && emp.area_sqm && (
                  <span className="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-lg bg-orange-50 text-orange-600">
                    <MapPin size={10} />
                    {emp.area_sqm} м²
                  </span>
                )}
              </div>

              {emp.is_active === false && (
                <span className="inline-block text-xs text-apple-danger mt-1 ml-[52px]">
                  Неактивен
                </span>
              )}
            </div>
          )
        })}
      </div>

      {/* Modal */}
      {isModalOpen && (
        <div className="fixed inset-0 bg-black/40 backdrop-blur-sm z-50 flex items-center justify-center p-4">
          <div className="bg-white rounded-2xl shadow-xl w-full max-w-md max-h-[90vh] overflow-y-auto p-6">
            <div className="flex items-center justify-between mb-5">
              <h2 className="text-lg font-semibold text-apple-text">
                {editingEmployee ? 'Редактировать' : 'Новый сотрудник'}
              </h2>
              <button
                onClick={closeModal}
                className="p-1 rounded-lg text-apple-gray hover:bg-apple-bg transition-all duration-200"
              >
                <X size={20} />
              </button>
            </div>

            <div className="space-y-4">
              {/* Name */}
              <div>
                <label className="block text-sm text-apple-gray mb-1.5">Имя</label>
                <input
                  type="text"
                  value={form.name}
                  onChange={(e) => setForm({ ...form, name: e.target.value })}
                  placeholder="Иванова Анна"
                  className={inputClass}
                />
              </div>

              {/* Role */}
              <div>
                <label className="block text-sm text-apple-gray mb-1.5">Роль</label>
                <select
                  value={form.role}
                  onChange={(e) => setForm({ ...form, role: e.target.value })}
                  className={`${inputClass} bg-white`}
                >
                  <option value="master">Мастер</option>
                  <option value="admin">Администратор</option>
                </select>
              </div>

              {/* Specialization */}
              <div>
                <label className="block text-sm text-apple-gray mb-1.5">
                  Специализация
                </label>
                <input
                  type="text"
                  value={form.specialization}
                  onChange={(e) =>
                    setForm({ ...form, specialization: e.target.value })
                  }
                  placeholder="Парикмахер-стилист"
                  className={inputClass}
                />
              </div>

              {/* Description */}
              <div>
                <label className="block text-sm text-apple-gray mb-1.5">Описание</label>
                <textarea
                  value={form.description}
                  onChange={(e) => setForm({ ...form, description: e.target.value })}
                  placeholder="Описание сотрудника..."
                  rows={3}
                  className={`${inputClass} resize-none`}
                />
              </div>

              {/* Telegram ID */}
              <div>
                <label className="block text-sm text-apple-gray mb-1.5">Telegram ID</label>
                <input
                  type="number"
                  value={form.telegram_id}
                  onChange={(e) => setForm({ ...form, telegram_id: e.target.value })}
                  placeholder="123456789"
                  className={inputClass}
                />
              </div>

              {/* Booking Interval */}
              <div>
                <label className="block text-sm text-apple-gray mb-1.5">Интервал записи, мин</label>
                <input
                  type="number"
                  value={form.booking_interval_minutes}
                  onChange={(e) => setForm({ ...form, booking_interval_minutes: e.target.value })}
                  placeholder="30"
                  className={inputClass}
                />
              </div>

              {/* Venue Rental specific fields */}
              {isVenueRental && (
                <>
                  <div className="pt-2 border-t border-apple-border/30">
                    <p className="text-xs font-semibold text-apple-gray uppercase tracking-wider mb-3">
                      Параметры площадки
                    </p>
                  </div>

                  <div className="grid grid-cols-2 gap-3">
                    <div>
                      <label className="block text-sm text-apple-gray mb-1.5">Вместимость, чел</label>
                      <input
                        type="number"
                        value={form.capacity}
                        onChange={(e) => setForm({ ...form, capacity: e.target.value })}
                        placeholder="10"
                        className={inputClass}
                      />
                    </div>
                    <div>
                      <label className="block text-sm text-apple-gray mb-1.5">Площадь, м²</label>
                      <input
                        type="number"
                        value={form.area_sqm}
                        onChange={(e) => setForm({ ...form, area_sqm: e.target.value })}
                        placeholder="50"
                        className={inputClass}
                      />
                    </div>
                  </div>

                  <div>
                    <label className="block text-sm text-apple-gray mb-1.5">
                      Мин. время бронирования, мин
                    </label>
                    <input
                      type="number"
                      value={form.min_booking_minutes}
                      onChange={(e) => setForm({ ...form, min_booking_minutes: e.target.value })}
                      placeholder="60"
                      className={inputClass}
                    />
                  </div>

                  <div>
                    <label className="block text-sm text-apple-gray mb-1.5">Тариф соло, руб/ч</label>
                    <input
                      type="number"
                      value={form.solo_price_per_hour}
                      onChange={(e) => setForm({ ...form, solo_price_per_hour: e.target.value })}
                      placeholder="500"
                      className={inputClass}
                    />
                  </div>
                </>
              )}

              {/* Photos */}
              <div className="pt-2 border-t border-apple-border/30">
                <p className="text-xs font-semibold text-apple-gray uppercase tracking-wider mb-3">
                  Фото {isVenueRental ? 'зала' : 'сотрудника'}
                </p>
                {!editingEmployee ? (
                  <p className="text-xs text-apple-gray">
                    Сохраните {isVenueRental ? 'зал' : 'сотрудника'}, затем добавьте фото.
                  </p>
                ) : (
                  <>
                    <input
                      ref={photoInputRef}
                      type="file"
                      accept="image/*"
                      className="hidden"
                      onChange={(e) => {
                        const f = e.target.files?.[0]
                        if (f) handlePhotoUpload(f)
                      }}
                    />
                    <div className="grid grid-cols-3 gap-2">
                      {employeePhotos.map((fid, idx) => (
                        <div key={`${fid}-${idx}`} className="relative aspect-square rounded-xl overflow-hidden bg-apple-bg group">
                          <img
                            src={`/api/telegram-photo/${encodeURIComponent(fid)}`}
                            alt={`Фото ${idx + 1}`}
                            className="w-full h-full object-cover"
                          />
                          <button
                            type="button"
                            onClick={() => handlePhotoDelete(idx)}
                            className="absolute top-1 right-1 w-7 h-7 rounded-full bg-black/60 text-white flex items-center justify-center opacity-90"
                            aria-label="Удалить фото"
                          >
                            <Trash2 size={13} />
                          </button>
                        </div>
                      ))}
                      <button
                        type="button"
                        onClick={() => photoInputRef.current?.click()}
                        disabled={photoUploading}
                        className="aspect-square rounded-xl border-2 border-dashed border-apple-border flex flex-col items-center justify-center gap-1 text-apple-gray hover:border-apple-blue hover:text-apple-blue transition-all duration-200 disabled:opacity-50"
                      >
                        {photoUploading ? (
                          <div className="w-5 h-5 border-2 border-apple-blue border-t-transparent rounded-full animate-spin" />
                        ) : (
                          <>
                            <ImagePlus size={20} />
                            <span className="text-[10px] font-medium">Добавить</span>
                          </>
                        )}
                      </button>
                    </div>
                    {employeePhotos.length === 0 && !photoUploading && (
                      <p className="text-xs text-apple-gray mt-2 flex items-center gap-1">
                        <ImageIcon size={12} />
                        Фото пока нет
                      </p>
                    )}
                  </>
                )}
              </div>

              {/* Employee-Service Links */}
              <div className="pt-2 border-t border-apple-border/30">
                <p className="text-xs font-semibold text-apple-gray uppercase tracking-wider mb-3">
                  Услуги
                </p>
                {servicesLoading ? (
                  <div className="space-y-2">
                    {[1, 2, 3].map((i) => (
                      <div key={i} className="h-6 skeleton rounded-lg" />
                    ))}
                  </div>
                ) : allServices.length === 0 ? (
                  <p className="text-xs text-apple-gray">Нет доступных услуг</p>
                ) : (
                  <div className="space-y-2 max-h-48 overflow-y-auto">
                    {allServices.map((svc) => (
                      <label
                        key={svc.id}
                        className="flex items-center gap-3 cursor-pointer py-1 px-2 rounded-lg hover:bg-apple-bg transition-all duration-200"
                      >
                        <div className="relative">
                          <input
                            type="checkbox"
                            checked={selectedServiceIds.includes(svc.id)}
                            onChange={() => toggleServiceLink(svc.id)}
                            className="sr-only peer"
                          />
                          <div className="w-5 h-5 border-2 border-gray-300 rounded-md peer-checked:bg-apple-blue peer-checked:border-apple-blue transition-all duration-200 flex items-center justify-center">
                            {selectedServiceIds.includes(svc.id) && (
                              <svg className="w-3 h-3 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3}>
                                <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                              </svg>
                            )}
                          </div>
                        </div>
                        <div className="flex-1 min-w-0">
                          <span className="text-sm text-apple-text truncate block">{svc.name}</span>
                          {svc.price !== undefined && (
                            <span className="text-xs text-apple-gray">{svc.price} руб</span>
                          )}
                        </div>
                      </label>
                    ))}
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
                disabled={!form.name || !form.specialization}
                className="flex-1 bg-apple-blue text-white font-medium py-3 rounded-xl hover:bg-apple-blue-hover transition-all duration-200 disabled:opacity-50"
              >
                {editingEmployee ? 'Сохранить' : 'Добавить'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Duty Schedule Modal */}
      {dutyModalEmp && (
        <div className="fixed inset-0 bg-black/40 backdrop-blur-sm z-50 flex items-center justify-center p-4">
          <div className="bg-white rounded-2xl shadow-xl w-full max-w-sm p-5">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-lg font-semibold text-apple-text">
                График: {dutyModalEmp.name}
              </h2>
              <button
                onClick={() => setDutyModalEmp(null)}
                className="p-1 rounded-lg text-apple-gray hover:bg-apple-bg transition-all duration-200"
              >
                <X size={20} />
              </button>
            </div>

            {/* Month navigation */}
            {(() => {
              const baseDate = new Date()
              baseDate.setDate(1)
              baseDate.setMonth(baseDate.getMonth() + dutyMonthOffset)
              const year = baseDate.getFullYear()
              const month = baseDate.getMonth()
              const monthName = baseDate.toLocaleDateString('ru-RU', { month: 'long', year: 'numeric' })

              // Build calendar grid
              const firstDay = new Date(year, month, 1)
              const lastDay = new Date(year, month + 1, 0)
              let startDow = firstDay.getDay()
              if (startDow === 0) startDow = 7 // Mon=1..Sun=7
              const daysInMonth = lastDay.getDate()
              const todayStr = getTodayStr()

              const cells: (number | null)[] = []
              for (let i = 1; i < startDow; i++) cells.push(null)
              for (let d = 1; d <= daysInMonth; d++) cells.push(d)

              return (
                <>
                  <div className="flex items-center justify-between mb-3">
                    <button onClick={() => setDutyMonthOffset(o => o - 1)}
                      className="p-1.5 rounded-lg hover:bg-apple-bg transition-all">
                      <ChevronLeft size={16} />
                    </button>
                    <span className="text-sm font-medium text-apple-text capitalize">{monthName}</span>
                    <button onClick={() => setDutyMonthOffset(o => o + 1)}
                      className="p-1.5 rounded-lg hover:bg-apple-bg transition-all">
                      <ChevronRight size={16} />
                    </button>
                  </div>

                  {/* Day headers */}
                  <div className="grid grid-cols-7 gap-1 mb-1">
                    {['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс'].map((d) => (
                      <div key={d} className="text-center text-[10px] font-semibold text-apple-gray uppercase">{d}</div>
                    ))}
                  </div>

                  {/* Calendar grid */}
                  <div className="grid grid-cols-7 gap-1">
                    {cells.map((day, idx) => {
                      if (day === null) return <div key={`empty-${idx}`} />
                      const dateStr = `${year}-${String(month + 1).padStart(2, '0')}-${String(day).padStart(2, '0')}`
                      const isDuty = dutyDates.has(dateStr)
                      const isToday = dateStr === todayStr
                      return (
                        <button
                          key={dateStr}
                          onClick={() => toggleDutyDate(dateStr)}
                          className={`w-full aspect-square rounded-lg text-xs font-medium flex items-center justify-center transition-all duration-150 ${
                            isDuty
                              ? 'bg-green-500 text-white shadow-sm'
                              : isToday
                              ? 'bg-apple-blue/10 text-apple-blue border border-apple-blue/30'
                              : 'hover:bg-apple-bg text-apple-text'
                          }`}
                        >
                          {day}
                        </button>
                      )
                    })}
                  </div>

                  <p className="text-[10px] text-apple-gray mt-2 text-center">
                    Нажмите на день, чтобы отметить дежурство. Зелёные — дежурные дни.
                  </p>
                </>
              )
            })()}

            <div className="flex gap-3 mt-4">
              <button
                onClick={() => setDutyModalEmp(null)}
                className="flex-1 bg-apple-bg text-apple-text font-medium py-3 rounded-xl hover:bg-gray-200 transition-all duration-200"
              >
                Отмена
              </button>
              <button
                onClick={saveDutySchedule}
                disabled={dutySaving}
                className="flex-1 bg-apple-blue text-white font-medium py-3 rounded-xl hover:bg-apple-blue-hover transition-all duration-200 disabled:opacity-50"
              >
                {dutySaving ? 'Сохранение...' : 'Сохранить'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
