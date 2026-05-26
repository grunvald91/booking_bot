import { useState, useRef, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { Phone, Send } from 'lucide-react'
import { api } from '../../api/client'

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
    window.open('https://t.me/Sochiservice_bot?start=login', '_blank')
  }

  return (
    <div className="max-w-sm mx-auto py-12 md:py-20">
      <div className="text-center mb-10">
        <h1 className="text-2xl font-bold text-apple-text">Вход</h1>
        <p className="text-apple-gray mt-2">
          Войдите, чтобы управлять записями
        </p>
      </div>

      {mode === 'phone' && (
        <div className="space-y-4">
          <button
            onClick={handleTelegramLogin}
            className="w-full flex items-center justify-center gap-3 bg-[#0088cc] text-white font-medium py-3.5 rounded-xl hover:bg-[#0077b5] transition-all duration-200"
          >
            <Send size={18} />
            Войти через Telegram
          </button>

          <div className="flex items-center gap-4 my-6">
            <div className="flex-1 h-px bg-apple-border" />
            <span className="text-sm text-apple-gray">или</span>
            <div className="flex-1 h-px bg-apple-border" />
          </div>

          <div>
            <label className="block text-sm text-apple-gray mb-1.5">
              Номер телефона
            </label>
            <div className="relative">
              <Phone
                size={18}
                className="absolute left-4 top-1/2 -translate-y-1/2 text-apple-gray"
              />
              <input
                type="tel"
                value={phone}
                onChange={(e) => setPhone(e.target.value)}
                placeholder="+7 (___) ___-__-__"
                className="w-full pl-12 pr-4 py-3.5 rounded-xl border border-apple-border/50 text-sm focus:outline-none focus:border-apple-blue focus:ring-1 focus:ring-apple-blue/30 transition-all duration-200"
              />
            </div>
          </div>

          <button
            onClick={handleSendCode}
            disabled={loading || !phone}
            className="w-full bg-apple-blue text-white font-medium py-3.5 rounded-xl hover:bg-apple-blue-hover transition-all duration-200 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {loading ? 'Отправляем...' : 'Получить код'}
          </button>

          {error && (
            <p className="text-sm text-apple-danger text-center">{error}</p>
          )}

          <p className="text-xs text-apple-gray text-center mt-4 leading-relaxed">
            Если у вас есть бизнес — войдите через Telegram или по телефону.
            Роль администратора определится автоматически.
          </p>
        </div>
      )}

      {mode === 'code' && (
        <div className="space-y-6">
          <div className="text-center">
            {codeSentVia === 'telegram' ? (
              <p className="text-sm text-apple-gray">
                Код отправлен в <span className="font-medium text-[#0088cc]">Telegram</span> на аккаунт с номером{' '}
                <span className="font-medium text-apple-text">{phone}</span>
              </p>
            ) : (
              <p className="text-sm text-apple-gray">
                Не удалось отправить код в Telegram. Убедитесь, что вы зарегистрированы через бот{' '}
                <a href="https://t.me/Sochiservice_bot" target="_blank" rel="noopener noreferrer" className="text-[#0088cc] font-medium">@Sochiservice_bot</a>
              </p>
            )}
          </div>

          <div className="flex justify-center gap-2 sm:gap-3">
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
                className="w-12 h-12 sm:w-14 sm:h-14 text-center text-xl sm:text-2xl font-bold rounded-xl border border-apple-border/50 focus:outline-none focus:border-apple-blue focus:ring-2 focus:ring-apple-blue/40 transition-all duration-200"
              />
            ))}
          </div>

          {loading && (
            <p className="text-sm text-apple-gray text-center">Проверяем...</p>
          )}

          {error && (
            <p className="text-sm text-apple-danger text-center">{error}</p>
          )}

          <button
            onClick={() => {
              setMode('phone')
              setCode(['', '', '', '', '', ''])
            }}
            className="w-full text-sm text-apple-blue text-center py-2 hover:opacity-80 transition-opacity"
          >
            Изменить номер
          </button>
        </div>
      )}
    </div>
  )
}
