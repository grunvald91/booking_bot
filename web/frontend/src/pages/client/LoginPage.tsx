import { useState, useRef, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { Phone, Send } from 'lucide-react'
import { api } from '../../api/client'
import { ClientShell } from '../../components/ClientShell'

export function LoginPage() {
  const navigate = useNavigate()
  const [mode, setMode] = useState<'phone' | 'code'>('phone')
  const [phone, setPhone] = useState('')
  const [code, setCode] = useState(['', '', '', '', '', ''])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [codeSentVia, setCodeSentVia] = useState<'telegram' | 'fallback'>('telegram')
  const codeRefs = useRef<(HTMLInputElement | null)[]>([])

  useEffect(() => {
    if (mode === 'code' && codeRefs.current[0]) {
      codeRefs.current[0]?.focus()
    }
  }, [mode])

  const handleSendCode = async () => {
    if (!phone) return
    setLoading(true)
    setError('')
    try {
      const res = await api.loginPhone(phone)
      setCodeSentVia(res.fallback ? 'fallback' : 'telegram')
      setMode('code')
    } catch {
      setError('Не удалось отправить код. Проверьте номер.')
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
          localStorage.setItem('token', res.token)
          localStorage.setItem('userRole', res.role)
          localStorage.setItem('userName', res.user.full_name)
          sessionStorage.removeItem('servgoExplicitLogout')
          navigate(res.role === 'admin' || res.role === 'owner' ? '/admin' : '/')
        } catch {
          setError('Неверный код. Попробуйте снова.')
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
    sessionStorage.removeItem('servgoExplicitLogout')
    window.open('https://t.me/Sochiservice_bot?start=login', '_blank')
  }

  return (
    <ClientShell backTo="/" title="Вход">
      <div className="ds-form-narrow" style={{ paddingTop: 4 }}>
        {mode === 'phone' && (
          <div>
            <button
              onClick={handleTelegramLogin}
              className="ds-btn ds-btn--block"
              style={{ background: '#0088cc', color: '#fff', marginBottom: 16 }}
            >
              <Send size={18} />
              Войти через Telegram
            </button>

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
              Если у вас есть бизнес — войдите через Telegram или по телефону.
              Роль администратора определится автоматически.
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
