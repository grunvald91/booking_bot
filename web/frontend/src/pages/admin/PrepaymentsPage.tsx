import { useCallback, useEffect, useRef, useState } from 'react'
import { api, type AdminBooking } from '../../api/client'
import { errorMessage } from '../../authUtils'
import { AdminShell } from '../../components/AdminShell'
import { BusinessSelector } from '../../components/BusinessSelector'
import { useAdminBusiness } from '../../hooks/useAdminBusiness'

type Details = Awaited<ReturnType<typeof api.getPaymentDetails>>
const labels: Record<string, string> = { prepayment_sent: 'Оплата отправлена', pending_prepayment: 'Ждёт оплату', confirmed: 'Подтверждено', cancelled: 'Отменено', completed: 'Завершено' }

export function PrepaymentsPage() {
  const { businesses, selectedId, selectBusiness } = useAdminBusiness()
  const [filter, setFilter] = useState('prepayment_sent')
  const [items, setItems] = useState<AdminBooking[]>([])
  const [cursor, setCursor] = useState<number | null>(null)
  const [details, setDetails] = useState<Details | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [loading, setLoading] = useState(true)
  const [proof, setProof] = useState<{ url: string; mime: string } | null>(null)
  const activeKey = useRef('')
  const extraPages = useRef(false)
  const load = useCallback(async () => {
    if (!selectedId) { setLoading(false); return }
    try {
      const result = await api.getPrepayments(selectedId, filter)
      if (activeKey.current !== `${selectedId}/${filter}`) return
      setItems(result.items); setCursor(result.next_before_id)
    } catch (err) { setError(errorMessage(err)) } finally { setLoading(false) }
  }, [selectedId, filter])
  useEffect(() => {
    activeKey.current = `${selectedId}/${filter}`
    extraPages.current = false
    setDetails(null); setError(''); setLoading(true)
    void load()
    const timer = setInterval(() => { if (!extraPages.current) void load() }, 15000)
    return () => clearInterval(timer)
  }, [load, selectedId, filter])
  useEffect(() => () => { if (proof) URL.revokeObjectURL(proof.url) }, [proof])

  async function open(id: number) {
    setBusy(true); setError(''); setProof(null)
    const key = activeKey.current
    try { const result = await api.getPaymentDetails(id); if (key === activeKey.current) setDetails(result) } catch (err) { setError(errorMessage(err)) } finally { setBusy(false) }
  }
  async function more() {
    if (!selectedId || !cursor) return
    setBusy(true)
    try {
      const result = await api.getPrepayments(selectedId, filter, cursor)
      if (activeKey.current !== `${selectedId}/${filter}`) return
      extraPages.current = true
      setItems(current => [...current, ...result.items.filter(item => !current.some(old => old.id === item.id))]); setCursor(result.next_before_id)
    } catch (err) { setError(errorMessage(err)) } finally { setBusy(false) }
  }
  async function decide(action: 'confirm' | 'reject' | 'cancel') {
    if (!details) return
    const prompts = { confirm: 'Вы проверили поступление денег? Подтвердить оплату и бронь?', reject: 'Отклонить сообщение об оплате? Клиенту будет дано ещё 10 минут для исправления.', cancel: 'Отменить бронь и освободить слот? Деньги автоматически не возвращаются.' }
    if (!window.confirm(prompts[action])) return
    setBusy(true); setError('')
    try {
      const booking = action === 'cancel' ? await api.updateBookingStatus(details.booking.id, 'cancelled') :
        await api.reviewPrepayment(details.booking.id, action, details.booking.version)
      setDetails(current => current ? { ...current, booking } : null)
      await load()
      setDetails(await api.getPaymentDetails(booking.id))
    } catch (err) {
      setError(errorMessage(err))
      try { setDetails(await api.getPaymentDetails(details.booking.id)) } catch { /* Keep the error visible. */ }
    } finally { setBusy(false) }
  }
  async function viewProof(id: number) {
    setBusy(true); setError('')
    try { const blob = await api.downloadReceipt(id); setProof({ url: URL.createObjectURL(blob), mime: blob.type }) }
    catch (err) { setError(errorMessage(err)) } finally { setBusy(false) }
  }

  return <AdminShell title="Предоплаты" subtitle="Поступление денег проверяет владелец" headerExtra={<BusinessSelector businesses={businesses} selectedId={selectedId} onSelect={selectBusiness} />}>
    <label className="ds-field" style={{ margin: '12px 0' }}>Показать<select className="ds-input" value={filter} onChange={e => setFilter(e.target.value)}>
      <option value="prepayment_sent">На проверке</option><option value="pending_prepayment">Ожидают отправки</option><option value="all">Все предоплаты</option>
    </select></label>
    {error && <p role="alert" style={{ color: 'var(--s-danger)' }}>{error}</p>}
    {loading && <p role="status">Загрузка…</p>}
    {!loading && !items.length && <p>Заявок в этом списке нет.</p>}
    <div style={{ display: 'grid', gap: 10 }}>
      {items.map(item => <button key={item.id} className="ds-card" disabled={busy} style={{ padding: 14, textAlign: 'left' }} onClick={() => void open(item.id)}>
        <strong>{item.client_name} · {item.prepayment_amount == null ? 'Сумма не указана' : `${item.prepayment_amount} ₽`}</strong><p>{item.service_name} · {item.date} {item.time}</p><span>{labels[item.status] || item.status}</span>
      </button>)}
    </div>
    {cursor && <button className="ds-btn ds-btn--ghost" disabled={busy} onClick={() => void more()}>Загрузить ещё</button>}
    <button className="ds-btn ds-btn--ghost" disabled={busy} onClick={() => { extraPages.current = false; void load() }}>Обновить список</button>
    {details && <section className="ds-card" style={{ padding: 16, marginTop: 16 }}>
      <h2 className="ds-h3">Запись №{details.booking.id} · {details.booking.client_name}</h2>
      <p>{details.booking.date} {details.booking.time} · {details.booking.service_name}</p>
      <p>Предоплата за визит: {details.prepayment_total} ₽ · {labels[details.booking.status] || details.booking.status}</p>
      {details.visit.length > 1 && <p>Решение применяется ко всему визиту: {details.visit.map(b => b.service_name).join(', ')}.</p>}
      {details.booking.client_phone && <p><a href={`tel:${details.booking.client_phone}`}>{details.booking.client_phone}</a></p>}
      <h3>Чеки</h3>
      {!details.receipts.length && <p>Сохранённого чека нет. Проверьте поступление в банке; старые чеки из Telegram здесь недоступны.</p>}
      {details.receipts.map(receipt => <button key={receipt.id} className="ds-btn ds-btn--ghost" disabled={busy} onClick={() => void viewProof(receipt.id)}>Открыть чек · {new Date(receipt.created_at + 'Z').toLocaleString('ru-RU')}</button>)}
      {proof && <div style={{ margin: '12px 0' }}>
        {proof.mime.startsWith('image/') && <img src={proof.url} alt="Чек клиента" style={{ maxWidth: '100%', maxHeight: 480, objectFit: 'contain' }} />}
        <p><a href={proof.url} target="_blank" rel="noopener noreferrer">Открыть файл</a> · <a href={proof.url} download="receipt">Скачать</a></p>
      </div>}
      {details.booking.status === 'prepayment_sent' && <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginTop: 12 }}>
        <button className="ds-btn ds-btn--primary" disabled={busy} onClick={() => void decide('confirm')}>Подтвердить поступление</button>
        <button className="ds-btn ds-btn--ghost" disabled={busy} onClick={() => void decide('reject')}>Отклонить сообщение об оплате</button>
      </div>}
      {!['cancelled', 'completed'].includes(details.booking.status) && <button className="ds-btn ds-btn--ghost" disabled={busy} onClick={() => void decide('cancel')}>Отменить бронь</button>}
      {!!details.reviews.length && <div><h3>История проверки</h3>{details.reviews.map((review, index) => <p key={index}>{review.decision === 'confirm' ? 'Оплата подтверждена' : review.decision === 'cancel' ? 'Бронь отменена' : 'Сообщение отклонено'} · {new Date(review.reviewed_at + 'Z').toLocaleString('ru-RU')} · сотрудник №{review.reviewer_id}</p>)}</div>}
      <button className="ds-btn ds-btn--ghost" onClick={() => { setDetails(null); setProof(null) }}>Закрыть</button>
    </section>}
  </AdminShell>
}
