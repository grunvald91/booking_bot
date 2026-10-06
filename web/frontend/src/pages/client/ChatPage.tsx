import { useState, useRef, useEffect, useCallback } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { Bot, Send, Check, X, Loader2 } from 'lucide-react'
import { api, type Business, type SalesPendingAction, type SalesConfirmation } from '../../api/client'
import { ClientShell } from '../../components/ClientShell'

interface ChatMessage {
  id: string
  role: 'user' | 'ai'
  text: string
  booking_url?: string | null
}

function errorText(error: unknown) {
  if (error instanceof Error) {
    try {
      const detail = JSON.parse(error.message).detail
      if (typeof detail === 'string') return detail
    } catch { /* Non-JSON network failure. */ }
  }
  return 'Не удалось связаться с сервисом. Попробуйте ещё раз.'
}

function ConfirmationCard({ action, busy, onConfirm, onReject }: {
  action: SalesPendingAction
  busy: boolean
  onConfirm: (details: SalesConfirmation) => void
  onReject: () => void
}) {
  const [name, setName] = useState('')
  const [phone, setPhone] = useState('')
  const [consent, setConsent] = useState(false)
  const [terms, setTerms] = useState(false)
  const [expired, setExpired] = useState(() => new Date(`${action.expires_at}Z`).getTime() <= Date.now())
  useEffect(() => {
    const timer = window.setTimeout(() => setExpired(true), Math.max(0, new Date(`${action.expires_at}Z`).getTime() - Date.now()))
    return () => window.clearTimeout(timer)
  }, [action.expires_at])
  const validContact = !action.requires_contact || (name.trim().length >= 2 && /^\+?[0-9\s()-]+$/.test(phone) && phone.replace(/\D/g, '').length >= 10 && phone.replace(/\D/g, '').length <= 15)
  const canConfirm = !busy && !expired && validContact && (!action.requires_legal_consent || (consent && terms))
  return (
    <div className="ds-card" style={{ padding: 14, margin: '12px 0' }}>
      <p className="ds-text" style={{ fontWeight: 600 }}>{action.description}</p>
      {action.cancellation_policy && <p className="ds-sub" style={{ marginTop: 8 }}>{action.cancellation_policy}</p>}
      {action.requires_contact && (
        <div style={{ display: 'grid', gap: 8, marginTop: 12 }}>
          <label className="ds-sub">Ваше имя
            <input className="ds-input" autoComplete="name" maxLength={120} value={name} onChange={e => setName(e.target.value)} />
          </label>
          <label className="ds-sub">Телефон для записи
            <input className="ds-input" type="tel" autoComplete="tel" maxLength={30} value={phone} onChange={e => setPhone(e.target.value)} />
          </label>
        </div>
      )}
      {action.requires_legal_consent && (
        <div style={{ display: 'grid', gap: 10, marginTop: 12 }}>
          <label className="ds-sub">
            <input type="checkbox" checked={consent} onChange={e => setConsent(e.target.checked)} />{' '}
            Даю <Link to={`/legal/consent/${action.business_id}`} target="_blank">согласие на обработку данных</Link>
          </label>
          <label className="ds-sub">
            <input type="checkbox" checked={terms} onChange={e => setTerms(e.target.checked)} />{' '}
            Принимаю <Link to={`/legal/terms/${action.business_id}`} target="_blank">условия записи</Link>
          </label>
        </div>
      )}
      {expired && <p className="ds-sub">Подтверждение истекло. Попросите проверить время снова.</p>}
      <div style={{ display: 'flex', gap: 8, marginTop: 12 }}>
        <button className="ds-btn ds-btn--primary ds-btn--sm" disabled={!canConfirm} onClick={() => onConfirm({
          client_name: action.requires_contact ? name.trim() : undefined,
          client_phone: action.requires_contact ? phone.trim() : undefined,
          personal_data_consent: consent, booking_terms_accepted: terms,
        })}>{busy ? <Loader2 size={14} className="animate-spin" /> : <Check size={14} />} Подтвердить</button>
        <button className="ds-btn ds-btn--ghost ds-btn--sm" disabled={busy} onClick={onReject}><X size={14} /> Отмена</button>
      </div>
    </div>
  )
}

function SalesThread({ business }: { business: Business }) {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [pending, setPending] = useState<SalesPendingAction | null>(null)
  const [mode, setMode] = useState<'ai' | 'human'>('ai')
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [ready, setReady] = useState(false)
  const [error, setError] = useState('')
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const operation = useRef(false)

  const loadHistory = useCallback(async () => {
    const history = await api.aiHistory(business.id)
    const restored: ChatMessage[] = history.messages.length ? history.messages : [{
      id: 'welcome', role: 'ai', text: `Здравствуйте! Помогу подобрать услугу в «${business.name}» и найти удобное время. Что вас интересует?`,
    }]
    if (history.booking_url && restored.length) restored[restored.length - 1].booking_url = history.booking_url
    setMessages(restored)
    setPending(history.pending_action || null)
    setMode(history.mode)
  }, [business.id, business.name])

  useEffect(() => {
    let active = true
    api.aiHistory(business.id).then(history => {
      if (!active) return
      const restored: ChatMessage[] = history.messages.length ? history.messages : [{
        id: 'welcome', role: 'ai', text: `Здравствуйте! Помогу подобрать услугу в «${business.name}» и найти удобное время. Что вас интересует?`,
      }]
      if (history.booking_url && restored.length) restored[restored.length - 1].booking_url = history.booking_url
      setMessages(restored)
      setPending(history.pending_action || null)
      setMode(history.mode)
      setReady(true)
    }).catch(err => { if (active) setError(errorText(err)) })
    return () => { active = false }
  }, [business.id, business.name])

  useEffect(() => {
    if (mode !== 'human') return
    const timer = window.setInterval(() => {
      if (!operation.current) loadHistory().catch(err => setError(errorText(err)))
    }, 8000)
    return () => window.clearInterval(timer)
  }, [mode, loadHistory])

  useEffect(() => { messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [messages, pending, busy])

  const send = async (text = input.trim()) => {
    if (!text || operation.current || !ready) return
    operation.current = true
    setBusy(true)
    setError('')
    setInput('')
    try {
      const result = await api.aiChat(text, business.id)
      setMessages(previous => [...previous, { id: crypto.randomUUID(), role: 'user', text },
        { id: crypto.randomUUID(), role: 'ai', text: result.reply, booking_url: result.booking_url }])
      setPending(result.pending_action || null)
      setMode(result.mode)
    } catch (err) {
      setInput(text)
      setError(errorText(err))
    } finally { operation.current = false; setBusy(false) }
  }

  const handleAction = async (confirm: boolean, details: SalesConfirmation = {}) => {
    if (!pending || operation.current) return
    operation.current = true
    setBusy(true)
    setError('')
    try {
      if (confirm) await api.aiConfirm(pending.action_id, details)
      else await api.aiReject(pending.action_id)
      await loadHistory()
    } catch (err) { setError(errorText(err)) }
    finally { operation.current = false; setBusy(false) }
  }

  const requestOperator = async () => {
    if (operation.current || !ready) return
    operation.current = true; setBusy(true); setError('')
    try { await api.aiHandoff(business.id); await loadHistory() }
    catch (err) { setError(errorText(err)) }
    finally { operation.current = false; setBusy(false) }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', flex: 1, minHeight: 0 }}>
      {mode === 'human' && <p className="ds-sub" role="status">Диалог передан оператору. Ответ появится здесь.</p>}
      <div style={{ flex: 1, overflowY: 'auto', padding: '14px 0' }} aria-live="polite">
        {messages.map(message => <div key={message.id} style={{ display: 'flex', gap: 8, marginBottom: 12, justifyContent: message.role === 'user' ? 'flex-end' : 'flex-start' }}>
          {message.role === 'ai' && <Bot size={20} style={{ flexShrink: 0, color: 'var(--s-accent)', marginTop: 10 }} />}
          <div className="ds-text" style={{ maxWidth: '85%', whiteSpace: 'pre-wrap', padding: '12px 14px', borderRadius: 16, background: message.role === 'user' ? 'var(--s-accent-soft)' : 'var(--s-surface-2)' }}>
            {message.text}
            {message.booking_url && <div style={{ marginTop: 8 }}><Link className="ds-accent" to={message.booking_url}>Открыть запись</Link></div>}
          </div>
        </div>)}
        {pending && <ConfirmationCard key={pending.action_id} action={pending} busy={busy} onConfirm={details => handleAction(true, details)} onReject={() => handleAction(false)} />}
        {busy && <p className="ds-sub" role="status">Обрабатываю…</p>}
        <div ref={messagesEndRef} />
      </div>
      {error && <p className="ds-sub" role="alert" style={{ color: 'var(--s-danger)', marginBottom: 8 }}>{error}</p>}
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, marginBottom: 8 }}>
        <Link className="ds-accent" to={`/book/${business.id}`}>Обычная запись</Link>
        {mode === 'ai' && <button className="ds-chip" disabled={busy || !ready} onClick={requestOperator}>Позвать оператора</button>}
      </div>
      <div className="ds-search" style={{ borderRadius: 999, paddingRight: 6 }}>
        <input aria-label="Сообщение" value={input} maxLength={4000} onChange={e => setInput(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); void send() } }}
          placeholder={mode === 'human' ? 'Сообщение оператору…' : 'Напишите сообщение…'} disabled={busy || !ready} />
        <button className="ds-icon-btn" aria-label="Отправить" disabled={!input.trim() || busy || !ready} onClick={() => send()}><Send size={18} /></button>
      </div>
    </div>
  )
}

export function ChatPage() {
  const [params, setParams] = useSearchParams()
  const [businesses, setBusinesses] = useState<Business[]>([])
  const [error, setError] = useState('')
  const selectedId = Number(params.get('business_id'))
  const business = businesses.find(b => b.id === selectedId)
  useEffect(() => { api.getBusinesses().then(setBusinesses).catch(err => setError(errorText(err))) }, [])
  return (
    <ClientShell title="Подобрать услугу">
      <div style={{ display: 'flex', flexDirection: 'column', height: '100%', gap: 8 }}>
        <label className="ds-sub">Компания
          <select className="ds-input" value={business?.id || ''} onChange={e => setParams({ business_id: e.target.value })}>
            <option value="">Выберите компанию</option>
            {businesses.map(b => <option key={b.id} value={b.id}>{b.name}</option>)}
          </select>
        </label>
        {error && <p role="alert" className="ds-sub">{error}</p>}
        {business ? <SalesThread key={business.id} business={business} /> : <p className="ds-sub">Выберите компанию — помогу подобрать услугу, сравнить варианты и найти удобное время.</p>}
      </div>
    </ClientShell>
  )
}
