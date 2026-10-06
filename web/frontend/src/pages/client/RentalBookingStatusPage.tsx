import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { api } from '../../api/client'
import { ClientShell } from '../../components/ClientShell'

const STATUS: Record<string, string> = {
  pending: 'Заявка создана', confirmed: 'Бронь подтверждена', cancelled: 'Бронь отменена',
  completed: 'Аренда завершена', pending_prepayment: 'Ожидается предоплата',
  prepayment_sent: 'Оплата отправлена, ожидается проверка владельцем',
}

export function RentalBookingStatusPage() {
  const { token } = useParams()
  const [booking, setBooking] = useState<Awaited<ReturnType<typeof api.rentalStatus>> | null>(null)
  const [error, setError] = useState('')
  useEffect(() => {
    let active = true
    const load = () => token && api.rentalStatus(token).then(result => {
      if (active) { setBooking(result); setError('') }
    }).catch(() => { if (active) setError('Не удалось загрузить статус записи') })
    void load()
    const timer = window.setInterval(load, 15000)
    return () => { active = false; window.clearInterval(timer) }
  }, [token])
  return <ClientShell title="Заявка на аренду">
    {error && <p role="alert" className="ds-sub">{error}</p>}
    {booking ? <div className="ds-card" style={{ padding: 20, marginTop: 16 }}>
      <h2 className="ds-h2">{STATUS[booking.status] || booking.status}</h2>
      <p className="ds-text" style={{ marginTop: 12 }}>{booking.date} в {booking.time}, {booking.duration_minutes / 60} ч.</p>
      <p className="ds-text" style={{ marginTop: 12 }}>{booking.price_requires_confirmation || booking.estimated_price === null
        ? 'Стоимость согласует менеджер' : `Стоимость: ${booking.estimated_price.toLocaleString('ru-RU')} ₽`}</p>
      <p className="ds-sub" style={{ marginTop: 12 }}>{booking.prepayment_amount === null
        ? 'Размер предоплаты подтвердит владелец.' : `Предоплата: ${booking.prepayment_amount.toLocaleString('ru-RU')} ₽`}</p>
      <p className="ds-sub" style={{ marginTop: 12 }}>Статус обновляется автоматически. Получение оплаты подтверждает владелец.</p>
    </div> : !error && <p className="ds-sub">Загрузка…</p>}
  </ClientShell>
}
