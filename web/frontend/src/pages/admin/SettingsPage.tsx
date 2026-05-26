import { useState, useEffect, useRef } from 'react'
import {
  Building2,
  Camera,
  CreditCard,
  Users,
  QrCode,
  Plus,
  Trash2,
  X,
  Download,
  Check,
  Loader2,
  DoorOpen,
  User as UserIcon,
  ImagePlus,
} from 'lucide-react'
import { api, type BusinessUpdateData, type OwnerInfo, type Employee } from '../../api/client'

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

async function fetchQrBlob(url: string): Promise<string> {
  const token = localStorage.getItem('token')
  const tgInitData = (window as any).Telegram?.WebApp?.initData || ''
  const res = await fetch(url, {
    headers: {
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(tgInitData ? { 'X-Telegram-Init-Data': tgInitData } : {}),
    },
  })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  const blob = await res.blob()
  return URL.createObjectURL(blob)
}
import { useAdminBusiness } from '../../hooks/useAdminBusiness'
import { BusinessSelector } from '../../components/BusinessSelector'

const inputClass =
  'w-full px-4 py-3 rounded-xl border border-apple-border/50 text-sm focus:outline-none focus:border-apple-blue focus:ring-1 focus:ring-apple-blue/30 transition-all duration-200'

function Toggle({ checked, onChange }: { checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      onClick={() => onChange(!checked)}
      className={`relative inline-flex h-7 w-12 shrink-0 cursor-pointer rounded-full transition-colors duration-200 ease-in-out ${
        checked ? 'bg-apple-blue' : 'bg-gray-300'
      }`}
    >
      <span
        className={`pointer-events-none inline-block h-5 w-5 transform rounded-full bg-white shadow-md ring-0 transition-transform duration-200 ease-in-out mt-1 ${
          checked ? 'translate-x-6 ml-0.5' : 'translate-x-1'
        }`}
      />
    </button>
  )
}

export function SettingsPage() {
  const { businesses, selectedId: businessId, selectBusiness } = useAdminBusiness()
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [toast, setToast] = useState<string | null>(null)

  // Business profile form
  const [form, setForm] = useState<BusinessUpdateData>({})
  const [photos, setPhotos] = useState<string[]>([])
  const [uploadingPhoto, setUploadingPhoto] = useState(false)

  // QR blobs
  const [qrTelegram, setQrTelegram] = useState<string | null>(null)
  const [qrWebapp, setQrWebapp] = useState<string | null>(null)

  // Owners
  const [owners, setOwners] = useState<OwnerInfo[]>([])
  const [ownerModalOpen, setOwnerModalOpen] = useState(false)
  const [ownerField, setOwnerField] = useState('')

  // Employees / rooms with photos
  const [employees, setEmployees] = useState<Employee[]>([])
  const [employeesLoading, setEmployeesLoading] = useState(false)
  const [employeesError, setEmployeesError] = useState<string | null>(null)
  const [empPhotoUploadingId, setEmpPhotoUploadingId] = useState<number | null>(null)
  const empFileInputs = useRef<Record<number, HTMLInputElement | null>>({})

  const selectedBusiness = businesses.find((b) => b.id === businessId)
  const isVenueRental = selectedBusiness?.business_type === 'venue_rental'

  const fileInputRef = useRef<HTMLInputElement>(null)
  const toastTimeout = useRef<ReturnType<typeof setTimeout> | null>(null)

  const showToast = (msg: string) => {
    setToast(msg)
    if (toastTimeout.current) clearTimeout(toastTimeout.current)
    toastTimeout.current = setTimeout(() => setToast(null), 3000)
  }

  // Load employees / rooms for the "Фото сотрудников/залов" section.
  // include_inactive=true so we can manage photos even for disabled employees/rooms.
  useEffect(() => {
    if (!businessId) {
      setEmployees([])
      setEmployeesError(null)
      return
    }
    setEmployeesLoading(true)
    setEmployeesError(null)
    api
      .getEmployees(businessId, true)
      .then((list) => {
        setEmployees(list)
        setEmployeesError(null)
      })
      .catch((err) => {
        setEmployees([])
        setEmployeesError(err instanceof Error ? err.message : String(err))
      })
      .finally(() => setEmployeesLoading(false))
  }, [businessId])

  // Load business detail
  useEffect(() => {
    if (!businessId) return
    setLoading(true)
    Promise.all([
      api.getBusinessDetail(businessId),
      api.getOwners(businessId).catch(() => [] as OwnerInfo[]),
    ])
      .then(async ([biz, ownersList]) => {
        setForm({
          name: biz.name || '',
          description: biz.description || '',
          address: biz.address || '',
          phone: biz.phone || '',
          working_hours_start: biz.working_hours_start || '',
          working_hours_end: biz.working_hours_end || '',
          break_start: biz.break_start || '',
          break_end: biz.break_end || '',
          booking_interval_minutes: biz.booking_interval_minutes ?? undefined,
          directions: biz.directions || '',
          prepayment_enabled: biz.prepayment_enabled ?? false,
          prepayment_percent: biz.prepayment_percent ?? undefined,
          payment_phone: biz.payment_phone || '',
          payment_details: biz.payment_details || '',
          cancellation_policy_text: biz.cancellation_policy_text || '',
          require_receipt_for_prepayment: biz.require_receipt_for_prepayment ?? false,
        })
        try {
          setPhotos(biz.photos ? JSON.parse(biz.photos) : [])
        } catch {
          setPhotos([])
        }
        setOwners(ownersList)
        // Load QR codes with auth
        try {
          const [tg, wa] = await Promise.all([
            fetchQrBlob(api.getQrUrl(businessId, 'telegram')),
            fetchQrBlob(api.getQrUrl(businessId, 'webapp')),
          ])
          setQrTelegram(tg)
          setQrWebapp(wa)
        } catch {
          setQrTelegram(null)
          setQrWebapp(null)
        }
      })
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [businessId])

  const updateField = <K extends keyof BusinessUpdateData>(key: K, value: BusinessUpdateData[K]) => {
    setForm((prev) => ({ ...prev, [key]: value }))
  }

  // Save business profile
  const handleSaveProfile = async () => {
    if (!businessId) return
    setSaving(true)
    try {
      const updated = await api.updateBusiness(businessId, {
        name: form.name,
        description: form.description,
        address: form.address,
        phone: form.phone,
        working_hours_start: form.working_hours_start,
        working_hours_end: form.working_hours_end,
        break_start: form.break_start,
        break_end: form.break_end,
        booking_interval_minutes: form.booking_interval_minutes,
        directions: form.directions,
      })
      setForm((prev) => ({ ...prev, name: updated.name }))
      showToast('Профиль сохранён')
    } catch (e) {
      alert('Ошибка при сохранении: ' + (e instanceof Error ? e.message : String(e)))
    } finally {
      setSaving(false)
    }
  }

  // Save prepayment settings
  const handleSavePrepayment = async () => {
    if (!businessId) return
    setSaving(true)
    try {
      await api.updateBusiness(businessId, {
        prepayment_enabled: form.prepayment_enabled,
        prepayment_percent: form.prepayment_percent,
        payment_phone: form.payment_phone,
        payment_details: form.payment_details,
        cancellation_policy_text: form.cancellation_policy_text,
        require_receipt_for_prepayment: form.require_receipt_for_prepayment,
      })
      showToast('Настройки предоплаты сохранены')
    } catch (e) {
      alert('Ошибка при сохранении: ' + (e instanceof Error ? e.message : String(e)))
    } finally {
      setSaving(false)
    }
  }

  // Photo upload
  const handlePhotoUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file || !businessId) return
    setUploadingPhoto(true)
    try {
      const result = await api.uploadBusinessPhoto(businessId, file)
      setPhotos(result.photos)
      showToast('Фото загружено')
    } catch (err) {
      alert('Ошибка загрузки фото: ' + (err instanceof Error ? err.message : String(err)))
    } finally {
      setUploadingPhoto(false)
      if (fileInputRef.current) fileInputRef.current.value = ''
    }
  }

  const handlePhotoDelete = async (index: number) => {
    if (!businessId || !confirm('Удалить фото?')) return
    try {
      const result = await api.deleteBusinessPhoto(businessId, index)
      setPhotos(result.photos)
      showToast('Фото удалено')
    } catch (e) {
      alert('Ошибка удаления фото: ' + (e instanceof Error ? e.message : String(e)))
    }
  }

  // Per-employee/room photo upload
  const handleEmpPhotoUpload = async (empId: number, file: File) => {
    if (!businessId) return
    setEmpPhotoUploadingId(empId)
    try {
      const res = await api.uploadEmployeePhoto(businessId, empId, file)
      setEmployees((prev) =>
        prev.map((e) =>
          e.id === empId ? { ...e, photos: JSON.stringify(res.photos) } : e
        )
      )
      showToast('Фото загружено')
    } catch (err) {
      alert('Ошибка загрузки фото: ' + (err instanceof Error ? err.message : String(err)))
    } finally {
      setEmpPhotoUploadingId(null)
      const input = empFileInputs.current[empId]
      if (input) input.value = ''
    }
  }

  const handleEmpPhotoDelete = async (empId: number, index: number) => {
    if (!businessId || !confirm('Удалить фото?')) return
    try {
      const res = await api.deleteEmployeePhoto(businessId, empId, index)
      setEmployees((prev) =>
        prev.map((e) =>
          e.id === empId
            ? { ...e, photos: res.photos.length > 0 ? JSON.stringify(res.photos) : undefined }
            : e
        )
      )
      showToast('Фото удалено')
    } catch (e) {
      alert('Ошибка удаления фото: ' + (e instanceof Error ? e.message : String(e)))
    }
  }

  // Owners
  const handleAddOwner = async () => {
    if (!businessId || !ownerField.trim()) return
    const data: { telegram_id?: number; username?: string } = {}
    const trimmed = ownerField.trim()
    if (/^\d+$/.test(trimmed)) {
      data.telegram_id = Number(trimmed)
    } else {
      data.username = trimmed.replace(/^@/, '')
    }
    try {
      const owner = await api.addOwner(businessId, data)
      setOwners((prev) => [...prev, owner])
      setOwnerField('')
      setOwnerModalOpen(false)
      showToast('Совладелец добавлен')
    } catch (e) {
      alert('Ошибка: ' + (e instanceof Error ? e.message : String(e)))
    }
  }

  const handleRemoveOwner = async (ownerId: number) => {
    if (!businessId || !confirm('Удалить совладельца?')) return
    try {
      await api.removeOwner(businessId, ownerId)
      setOwners((prev) => prev.filter((o) => o.id !== ownerId))
      showToast('Совладелец удалён')
    } catch (e) {
      alert('Ошибка: ' + (e instanceof Error ? e.message : String(e)))
    }
  }

  if (loading) {
    return (
      <div className="space-y-4">
        <div className="h-8 w-48 skeleton mb-6" />
        {[1, 2, 3].map((i) => (
          <div key={i} className="h-32 skeleton rounded-2xl" />
        ))}
      </div>
    )
  }

  return (
    <div>
      {/* Success toast */}
      {toast && (
        <div className="fixed top-4 left-1/2 -translate-x-1/2 z-50 bg-apple-success text-white px-5 py-3 rounded-xl shadow-lg flex items-center gap-2 text-sm font-medium animate-fade-in">
          <Check size={16} />
          {toast}
        </div>
      )}

      <BusinessSelector businesses={businesses} selectedId={businessId} onSelect={selectBusiness} vertical />

      <h1 className="text-2xl font-bold text-apple-text mb-6">Настройки</h1>

      <div className="space-y-6">
        {/* === 1. Business Profile === */}
        <section className="bg-white rounded-2xl shadow-sm border border-apple-border/50 p-5">
          <h2 className="text-lg font-semibold text-apple-text flex items-center gap-2 mb-5">
            <Building2 size={20} />
            Профиль бизнеса
          </h2>

          <div className="space-y-4">
            <div>
              <label className="block text-sm text-apple-gray mb-1.5">Название</label>
              <input
                type="text"
                value={form.name || ''}
                onChange={(e) => updateField('name', e.target.value)}
                className={inputClass}
              />
            </div>

            <div>
              <label className="block text-sm text-apple-gray mb-1.5">Описание</label>
              <textarea
                value={form.description || ''}
                onChange={(e) => updateField('description', e.target.value)}
                rows={3}
                className={inputClass + ' resize-none'}
              />
            </div>

            <div>
              <label className="block text-sm text-apple-gray mb-1.5">Адрес</label>
              <input
                type="text"
                value={form.address || ''}
                onChange={(e) => updateField('address', e.target.value)}
                className={inputClass}
              />
            </div>

            <div>
              <label className="block text-sm text-apple-gray mb-1.5">Телефон</label>
              <input
                type="text"
                value={form.phone || ''}
                onChange={(e) => updateField('phone', e.target.value)}
                placeholder="+7 (900) 123-45-67"
                className={inputClass}
              />
            </div>

            <div>
              <label className="block text-sm text-apple-gray mb-1.5">Время работы</label>
              <div className="flex items-center gap-2">
                <span className="text-sm text-apple-gray">с</span>
                <input
                  type="time"
                  value={form.working_hours_start || ''}
                  onChange={(e) => updateField('working_hours_start', e.target.value)}
                  className={inputClass + ' w-auto'}
                />
                <span className="text-sm text-apple-gray">до</span>
                <input
                  type="time"
                  value={form.working_hours_end || ''}
                  onChange={(e) => updateField('working_hours_end', e.target.value)}
                  className={inputClass + ' w-auto'}
                />
              </div>
            </div>

            <div>
              <label className="block text-sm text-apple-gray mb-1.5">Перерыв</label>
              <div className="flex items-center gap-2">
                <span className="text-sm text-apple-gray">с</span>
                <input
                  type="time"
                  value={form.break_start || ''}
                  onChange={(e) => updateField('break_start', e.target.value)}
                  className={inputClass + ' w-auto'}
                />
                <span className="text-sm text-apple-gray">до</span>
                <input
                  type="time"
                  value={form.break_end || ''}
                  onChange={(e) => updateField('break_end', e.target.value)}
                  className={inputClass + ' w-auto'}
                />
              </div>
            </div>

            <div>
              <label className="block text-sm text-apple-gray mb-1.5">Интервал записи</label>
              <div className="flex items-center gap-2">
                <input
                  type="number"
                  value={form.booking_interval_minutes ?? ''}
                  onChange={(e) =>
                    updateField('booking_interval_minutes', e.target.value ? Number(e.target.value) : undefined)
                  }
                  placeholder="30"
                  className={inputClass + ' w-32'}
                />
                <span className="text-sm text-apple-gray">мин</span>
              </div>
            </div>

            <div>
              <label className="block text-sm text-apple-gray mb-1.5">Как добраться</label>
              <textarea
                value={form.directions || ''}
                onChange={(e) => updateField('directions', e.target.value)}
                rows={3}
                className={inputClass + ' resize-none'}
              />
            </div>
          </div>

          <button
            onClick={handleSaveProfile}
            disabled={saving}
            className="mt-5 w-full bg-apple-blue text-white font-medium py-3 rounded-xl hover:bg-apple-blue-hover transition-all duration-200 disabled:opacity-50"
          >
            {saving ? 'Сохранение...' : 'Сохранить профиль'}
          </button>
        </section>

        {/* === 2. Photos === */}
        <section className="bg-white rounded-2xl shadow-sm border border-apple-border/50 p-5">
          <h2 className="text-lg font-semibold text-apple-text flex items-center gap-2 mb-4">
            <Camera size={20} />
            Фотографии
          </h2>

          <p className="text-xs text-apple-gray mb-3">
            Первое фото будет показано на главной странице
          </p>

          <div className="grid grid-cols-3 sm:grid-cols-4 gap-3">
            {photos.map((fileId, index) => (
              <div key={index} className="relative group aspect-square rounded-xl overflow-hidden bg-apple-bg">
                <img
                  src={`/api/telegram-photo/${encodeURIComponent(fileId)}`}
                  alt={`Фото ${index + 1}`}
                  className="w-full h-full object-cover"
                />
                <button
                  onClick={() => handlePhotoDelete(index)}
                  className="absolute top-1.5 right-1.5 p-1 rounded-full bg-black/50 text-white opacity-0 group-hover:opacity-100 transition-opacity duration-200 hover:bg-black/70"
                >
                  <Trash2 size={14} />
                </button>
                {index === 0 && (
                  <span className="absolute bottom-1.5 left-1.5 text-[10px] bg-apple-blue text-white px-1.5 py-0.5 rounded-md font-medium">
                    Главная
                  </span>
                )}
              </div>
            ))}

            {/* Upload button */}
            <button
              onClick={() => fileInputRef.current?.click()}
              disabled={uploadingPhoto}
              className="aspect-square rounded-xl border-2 border-dashed border-apple-border/50 flex flex-col items-center justify-center text-apple-gray hover:border-apple-blue hover:text-apple-blue transition-all duration-200 disabled:opacity-50"
            >
              <Plus size={24} />
              <span className="text-xs mt-1">{uploadingPhoto ? 'Загрузка...' : 'Добавить'}</span>
            </button>
          </div>

          <input
            ref={fileInputRef}
            type="file"
            accept="image/*"
            onChange={handlePhotoUpload}
            className="hidden"
          />
        </section>

        {/* === 2.5. Employee / Room Photos === */}
        <section className="bg-white rounded-2xl shadow-sm border border-apple-border/50 p-5">
          <h2 className="text-lg font-semibold text-apple-text flex items-center gap-2 mb-1">
            {isVenueRental ? <DoorOpen size={20} /> : <UserIcon size={20} />}
            {isVenueRental ? 'Фото залов' : 'Фото сотрудников'}
          </h2>
          <p className="text-xs text-apple-gray mb-4">
            Прикрепите фото для каждого {isVenueRental ? 'зала' : 'сотрудника'} — оно появится в карточке при выборе клиентом.
          </p>

          {employeesLoading ? (
            <div className="space-y-2">
              {[1, 2].map((i) => (
                <div key={i} className="h-24 skeleton rounded-2xl" />
              ))}
            </div>
          ) : employeesError ? (
            <div className="bg-red-50 border border-red-200 rounded-xl p-3 text-sm text-red-700">
              Не удалось загрузить список: {employeesError}
            </div>
          ) : employees.length === 0 ? (
            <div className="bg-apple-bg rounded-xl p-3 text-sm text-apple-gray">
              В бизнесе <span className="font-medium text-apple-text">«{selectedBusiness?.name ?? '—'}»</span>{' '}
              пока нет {isVenueRental ? 'залов' : 'сотрудников'}. Добавьте их в разделе{' '}
              <a href="/admin/employees" className="text-apple-blue underline">Сотрудники</a>{' '}
              или через бота. Если вы уверены, что они есть — проверьте, что выбран правильный бизнес выше.
            </div>
          ) : (
            <div className="space-y-4">
              {employees.map((emp) => {
                const empPhotos = parsePhotos(emp.photos)
                const isUploading = empPhotoUploadingId === emp.id
                return (
                  <div
                    key={emp.id}
                    className="border border-apple-border/40 rounded-xl p-3"
                  >
                    <div className="flex items-center justify-between mb-2">
                      <div className="min-w-0">
                        <h3 className="font-medium text-sm text-apple-text truncate">
                          {emp.name}
                        </h3>
                        {emp.specialization && (
                          <p className="text-[11px] text-apple-gray truncate">
                            {emp.specialization}
                          </p>
                        )}
                      </div>
                      <span className="text-[10px] text-apple-gray shrink-0 ml-2">
                        {empPhotos.length} фото
                      </span>
                    </div>

                    <input
                      ref={(el) => {
                        empFileInputs.current[emp.id] = el
                      }}
                      type="file"
                      accept="image/*"
                      className="hidden"
                      onChange={(e) => {
                        const f = e.target.files?.[0]
                        if (f) handleEmpPhotoUpload(emp.id, f)
                      }}
                    />

                    <div className="grid grid-cols-4 sm:grid-cols-5 gap-2">
                      {empPhotos.map((fid, idx) => (
                        <div
                          key={`${fid}-${idx}`}
                          className="relative group aspect-square rounded-lg overflow-hidden bg-apple-bg"
                        >
                          <img
                            src={`/api/telegram-photo/${encodeURIComponent(fid)}`}
                            alt={`${emp.name} ${idx + 1}`}
                            className="w-full h-full object-cover"
                            loading="lazy"
                          />
                          <button
                            onClick={() => handleEmpPhotoDelete(emp.id, idx)}
                            className="absolute top-1 right-1 p-1 rounded-full bg-black/60 text-white opacity-0 group-hover:opacity-100 transition-opacity duration-200 hover:bg-black/80"
                            aria-label="Удалить"
                          >
                            <Trash2 size={11} />
                          </button>
                        </div>
                      ))}

                      <button
                        onClick={() => empFileInputs.current[emp.id]?.click()}
                        disabled={isUploading}
                        className="aspect-square rounded-lg border-2 border-dashed border-apple-border/50 flex flex-col items-center justify-center text-apple-gray hover:border-apple-blue hover:text-apple-blue transition-all duration-200 disabled:opacity-50"
                      >
                        {isUploading ? (
                          <Loader2 size={16} className="animate-spin" />
                        ) : (
                          <>
                            <ImagePlus size={16} />
                            <span className="text-[9px] mt-0.5 font-medium">Добавить</span>
                          </>
                        )}
                      </button>
                    </div>
                  </div>
                )
              })}
            </div>
          )}
        </section>

        {/* === 3. Prepayment Settings === */}
        <section className="bg-white rounded-2xl shadow-sm border border-apple-border/50 p-5">
          <h2 className="text-lg font-semibold text-apple-text flex items-center gap-2 mb-5">
            <CreditCard size={20} />
            Предоплата
          </h2>

          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <label className="text-sm text-apple-text font-medium">Включить предоплату</label>
              <Toggle
                checked={form.prepayment_enabled ?? false}
                onChange={(v) => updateField('prepayment_enabled', v)}
              />
            </div>

            {form.prepayment_enabled && (
              <>
                <div>
                  <label className="block text-sm text-apple-gray mb-1.5">Процент предоплаты</label>
                  <div className="flex items-center gap-2">
                    <input
                      type="number"
                      min={1}
                      max={100}
                      value={form.prepayment_percent ?? ''}
                      onChange={(e) =>
                        updateField('prepayment_percent', e.target.value ? Number(e.target.value) : undefined)
                      }
                      placeholder="50"
                      className={inputClass + ' w-32'}
                    />
                    <span className="text-sm text-apple-gray">%</span>
                  </div>
                </div>

                <div>
                  <label className="block text-sm text-apple-gray mb-1.5">Телефон для оплаты</label>
                  <input
                    type="text"
                    value={form.payment_phone || ''}
                    onChange={(e) => updateField('payment_phone', e.target.value)}
                    placeholder="+7 (900) 123-45-67"
                    className={inputClass}
                  />
                </div>

                <div>
                  <label className="block text-sm text-apple-gray mb-1.5">Реквизиты</label>
                  <textarea
                    value={form.payment_details || ''}
                    onChange={(e) => updateField('payment_details', e.target.value)}
                    rows={3}
                    placeholder="Номер карты, банк, получатель..."
                    className={inputClass + ' resize-none'}
                  />
                </div>

                <div className="flex items-center justify-between">
                  <label className="text-sm text-apple-text font-medium">Требовать чек</label>
                  <Toggle
                    checked={form.require_receipt_for_prepayment ?? false}
                    onChange={(v) => updateField('require_receipt_for_prepayment', v)}
                  />
                </div>

                <div>
                  <label className="block text-sm text-apple-gray mb-1.5">Условия отмены</label>
                  <textarea
                    value={form.cancellation_policy_text || ''}
                    onChange={(e) => updateField('cancellation_policy_text', e.target.value)}
                    rows={3}
                    placeholder="Опишите условия отмены и возврата предоплаты..."
                    className={inputClass + ' resize-none'}
                  />
                </div>
              </>
            )}
          </div>

          <button
            onClick={handleSavePrepayment}
            disabled={saving}
            className="mt-5 w-full bg-apple-blue text-white font-medium py-3 rounded-xl hover:bg-apple-blue-hover transition-all duration-200 disabled:opacity-50"
          >
            {saving ? 'Сохранение...' : 'Сохранить настройки предоплаты'}
          </button>
        </section>

        {/* === 4. Co-Owners === */}
        <section className="bg-white rounded-2xl shadow-sm border border-apple-border/50 p-5">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-lg font-semibold text-apple-text flex items-center gap-2">
              <Users size={20} />
              Совладельцы
            </h2>
            <button
              onClick={() => {
                setOwnerField('')
                setOwnerModalOpen(true)
              }}
              className="flex items-center gap-1.5 bg-apple-blue text-white text-sm font-medium px-3 py-2 rounded-xl hover:bg-apple-blue-hover transition-all duration-200"
            >
              <Plus size={14} />
              Добавить
            </button>
          </div>

          <div className="space-y-2">
            {owners.length === 0 && (
              <p className="text-sm text-apple-gray py-2">Нет совладельцев</p>
            )}
            {owners.map((owner) => (
              <div
                key={owner.id}
                className="flex items-center justify-between p-3 rounded-xl bg-apple-bg"
              >
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="font-medium text-sm text-apple-text truncate">
                      {owner.user_name}
                    </span>
                    <span
                      className={`text-xs px-2 py-0.5 rounded-full font-medium ${
                        owner.role === 'owner'
                          ? 'bg-purple-50 text-purple-700'
                          : 'bg-blue-50 text-blue-700'
                      }`}
                    >
                      {owner.role === 'owner' ? 'Владелец' : 'Совладелец'}
                    </span>
                  </div>
                  {owner.user_phone && (
                    <p className="text-xs text-apple-gray mt-0.5">{owner.user_phone}</p>
                  )}
                  {owner.telegram_id && (
                    <p className="text-xs text-apple-gray">ID: {owner.telegram_id}</p>
                  )}
                </div>
                {owner.role !== 'owner' && (
                  <button
                    onClick={() => handleRemoveOwner(owner.id)}
                    className="p-1.5 rounded-lg text-apple-gray hover:text-apple-danger hover:bg-red-50 transition-all duration-200 ml-2"
                  >
                    <Trash2 size={14} />
                  </button>
                )}
              </div>
            ))}
          </div>
        </section>

        {/* === 5. QR Codes === */}
        <section className="bg-white rounded-2xl shadow-sm border border-apple-border/50 p-5">
          <h2 className="text-lg font-semibold text-apple-text flex items-center gap-2 mb-4">
            <QrCode size={20} />
            QR-коды
          </h2>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            {businessId && (
              <>
                {[
                  { label: 'QR для Telegram', src: qrTelegram, filename: 'qr-telegram.png' },
                  { label: 'QR для WebApp', src: qrWebapp, filename: 'qr-webapp.png' },
                ].map(({ label, src, filename }) => (
                  <div key={label} className="border border-apple-border/50 rounded-xl p-4 flex flex-col items-center">
                    <p className="text-sm font-medium text-apple-text mb-3">{label}</p>
                    {src ? (
                      <img src={src} alt={label} className="w-48 h-48 rounded-lg" />
                    ) : (
                      <div className="w-48 h-48 rounded-lg bg-apple-bg flex items-center justify-center">
                        <Loader2 size={24} className="animate-spin text-apple-gray" />
                      </div>
                    )}
                    {src && (
                      <a
                        href={src}
                        download={filename}
                        className="flex items-center gap-1.5 mt-3 text-sm text-apple-blue hover:underline"
                      >
                        <Download size={14} />
                        Скачать
                      </a>
                    )}
                  </div>
                ))}
              </>
            )}
          </div>
        </section>
      </div>

      {/* Add Owner Modal */}
      {ownerModalOpen && (
        <div className="fixed inset-0 bg-black/40 backdrop-blur-sm z-50 flex items-center justify-center p-4">
          <div className="bg-white rounded-2xl shadow-xl w-full max-w-md p-6">
            <div className="flex items-center justify-between mb-5">
              <h2 className="text-lg font-semibold text-apple-text">Добавить совладельца</h2>
              <button
                onClick={() => setOwnerModalOpen(false)}
                className="p-1 rounded-lg text-apple-gray hover:bg-apple-bg transition-all duration-200"
              >
                <X size={20} />
              </button>
            </div>

            <div>
              <label className="block text-sm text-apple-gray mb-1.5">
                Telegram ID или @username
              </label>
              <input
                type="text"
                value={ownerField}
                onChange={(e) => setOwnerField(e.target.value)}
                placeholder="123456789 или @username"
                className={inputClass}
              />
              <p className="text-xs text-apple-gray mt-1.5">
                Введите числовой Telegram ID или имя пользователя
              </p>
            </div>

            <div className="flex gap-3 mt-6">
              <button
                onClick={() => setOwnerModalOpen(false)}
                className="flex-1 bg-apple-bg text-apple-text font-medium py-3 rounded-xl hover:bg-gray-200 transition-all duration-200"
              >
                Отмена
              </button>
              <button
                onClick={handleAddOwner}
                disabled={!ownerField.trim()}
                className="flex-1 bg-apple-blue text-white font-medium py-3 rounded-xl hover:bg-apple-blue-hover transition-all duration-200 disabled:opacity-50"
              >
                Добавить
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
