import { useState, useRef, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { Phone, Send } from 'lucide-react'
import { api, type TelegramLoginPayload } from '../../api/client'
import { errorMessage, saveLogin } from '../../authUtils'
import { ClientShell } from '../../components/ClientShell'
import { EmailAuthForm } from '../../components/EmailAuthForm'

export function LoginPage() {
  const navigate = useNavigate()
  const [mode, setMode] = useState<'phone' | 'code'>('phone')
  const [phone, setPhone] = useState('')
  const [code, setCode] = useState(['', '', '', '', '', ''])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [codeSentVia, setCodeSentVia] = useState<'telegram' | 'fallback'>('telegram')
  const codeRefs = useRef<(HTMLInputElement | null)[]>([])
  const telegramWidgetRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    if (mode === 'code' && codeRefs.current[0]) {
      codeRefs.current[0]?.focus()
    }
  }, [mode])

  useEffect(() => {
    if (mode !== 'phone' || !telegramWidgetRef.current) return
    const host = telegramWidgetRef.current
    const callbackWindow = window as Window & {
      servgoTelegramWidgetAuth?: (data: TelegramLoginPayload) => void
    }
    let active = true
    callbackWindow.servgoTelegramWidgetAuth = (data) => {
      setLoading(true)
      setError('')
      void api.telegramLogin(data)
        .then(result => {
          if (!active) return
          saveLogin(result)
          navigate(result.role === 'client' ? '/my' : '/admin', { replace: true })
        })
        .catch(err => { if (active) setError(errorMessage(err)) })
        .finally(() => { if (active) setLoading(false) })
    }
    const script = document.createElement('script')
    script.async = true
    script.src = 'https://telegram.org/js/telegram-widget.js?22'
    script.setAttribute('data-telegram-login', 'Sochiservice_bot')
    script.setAttribute('data-size', 'large')
    script.setAttribute('data-onauth', 'window.servgoTelegramWidgetAuth(user)')
    script.onerror = () => {
      if (active) setError('Не удалось загрузить вход через Telegram. Попробуйте вход по email.')
    }
    host.appendChild(script)
    return () => {
      active = false
      script.remove()
      delete callbackWindow.servgoTelegramWidgetAuth
    }
  }, [mode, navigate])

  const handleSendCode = async () => {
    if (!phone) return
    setLoading(true)
    setError('')
    try {
      const res = await api.loginPhone(phone)
      setCodeSentVia(res.fallback ? 'fallback' : 'telegram')
      setMode('code')
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setLoading(false)
    }
  }

  const handleCodeInput = async (index: number, value: string) => {
    if (value.length > 1) value = value.slice(-1)
    if (!/^\d*$/.test(value)) return

    const newCode = [...code]
    newCode[index] = value
    setCode(newCode)

    if (value && index < 5) {
      codeRefs.current[index + 1]?.focus()
    }

    if (value && index === 5) {
      const fullCode = newCode.join('')
      if (fullCode.length === 6) {
        setLoading(true)
        setError('')
        try {
          const res = await api.verifyCode(phone, fullCode)
          saveLogin(res)
          navigate(res.role === 'admin' || res.role === 'owner' ? '/admin' : '/')
        } catch (err) {
          setError(errorMessage(err))
          setCode(['', '', '', '', '', ''])
          codeRefs.current[0]?.focus()
        } finally {
          setLoading(false)
        }
      }
    }
  }

  const handleCodeKeyDown = (index: number, e: React.KeyboardEvent) => {
    if (e.key === 'Backspace' && !code[index] && index > 0) {
      codeRefs.current[index - 1]?.focus()
    }
  }

  const handleTelegramLogin = () => {
    window.open('https://t.me/Sochiservice_bot', '_blank', 'noopener,noreferrer')
  }

  return (
    <ClientShell backTo="/" title="Вход">
      <div className="ds-form-narrow" style={{ paddingTop: 4 }}>
        <EmailAuthForm />
        <p className="ds-hint" style={{ margin: '16px 0' }}>Для аккаунтов с привязанным Telegram доступны прежние способы входа:</p>
        {mode === 'phone' && (
          <div>
            <div className="ds-card" style={{ padding: 16, marginBottom: 14, textAlign: 'center' }}>
              <p className="ds-text" style={{ marginBottom: 12, fontWeight: 600 }}>Войти через Telegram</p>
              <div ref={telegramWidgetRef} style={{ minHeight: 40, display: 'flex', justifyContent: 'center' }} />
              <p className="ds-hint" style={{ marginTop: 10 }}>
                Авторизуйтесь кнопкой Telegram выше. Простое открытие бота не выполняет вход на сайт.
              </p>
              <button type="button" onClick={handleTelegramLogin}
                className="ds-btn ds-btn--ghost ds-btn--sm" style={{ marginTop: 8 }}>
                <Send size={16} /> Открыть бота
              </button>
            </div>

            <div style={{ display: 'flex', alignItems: 'center', gap: 12, margin: '16px 0' }}>
              <div style={{ flex: 1, height: 1, background: 'var(--s-line)' }} />
              <span className="ds-sub">или</span>
              <div style={{ flex: 1, height: 1, background: 'var(--s-line)' }} />
            </div>

            <div className="ds-field">
              <label className="ds-label">Номер телефона</label>
              <div style={{ position: 'relative' }}>
                <Phone
                  size={18}
                  style={{ position: 'absolute', left: 13, top: '50%', transform: 'translateY(-50%)', color: 'var(--s-muted)' }}
                />
                <input
                  type="tel"
                  value={phone}
                  onChange={(e) => setPhone(e.target.value)}
                  placeholder="+7 (___) ___-__-__"
                  className="ds-input"
                  style={{ paddingLeft: 40 }}
                />
              </div>
            </div>

            <button
              onClick={handleSendCode}
              disabled={loading || !phone}
              className="ds-btn ds-btn--primary ds-btn--block"
            >
              {loading ? 'Отправляем...' : 'Получить код'}
            </button>

            {error && <p className="ds-error" style={{ justifyContent: 'center', marginTop: 10 }}>{error}</p>}

            <p className="ds-hint" style={{ textAlign: 'center', marginTop: 14 }}>
              Код придёт через @Sochiservice_bot, только если этот номер уже привязан к вашему аккаунту.
              При отсутствии кода используйте вход через Telegram выше или прежний подтверждённый email.
            </p>
          </div>
        )}

        {mode === 'code' && (
          <div>
            <div style={{ textAlign: 'center', marginBottom: 20 }}>
              {codeSentVia === 'telegram' ? (
                <p className="ds-sub">
                  Код отправлен в <span style={{ fontWeight: 600, color: '#0088cc' }}>Telegram</span> на аккаунт с номером{' '}
                  <span style={{ fontWeight: 600, color: 'var(--s-text)' }}>{phone}</span>
                </p>
              ) : (
                <p className="ds-sub">
                  Не удалось отправить код в Telegram. Убедитесь, что вы зарегистрированы через бот{' '}
                  <a href="https://t.me/Sochiservice_bot" target="_blank" rel="noopener noreferrer" style={{ color: '#0088cc', fontWeight: 600 }}>@Sochiservice_bot</a>
                </p>
              )}
            </div>

            <div style={{ display: 'flex', justifyContent: 'center', gap: 10, marginBottom: 20 }}>
              {code.map((digit, i) => (
                <input
                  key={i}
                  ref={(el) => { codeRefs.current[i] = el }}
                  type="text"
                  inputMode="numeric"
                  maxLength={1}
                  value={digit}
                  onChange={(e) => handleCodeInput(i, e.target.value)}
                  onKeyDown={(e) => handleCodeKeyDown(i, e)}
                  className="ds-input"
                  style={{
                    width: 48,
                    height: 48,
                    padding: 0,
                    textAlign: 'center',
                    fontSize: 22,
                    fontWeight: 700,
                  }}
                />
              ))}
            </div>

            {loading && <p className="ds-sub" style={{ textAlign: 'center' }}>Проверяем...</p>}

            {error && <p className="ds-error" style={{ justifyContent: 'center' }}>{error}</p>}

            <button
              onClick={() => {
                setMode('phone')
                setCode(['', '', '', '', '', ''])
              }}
              className="ds-btn ds-btn--block"
              style={{ background: 'none', border: 'none', color: 'var(--s-accent)' }}
            >
              Изменить номер
            </button>
          </div>
        )}
      </div>
    </ClientShell>
  )
}
