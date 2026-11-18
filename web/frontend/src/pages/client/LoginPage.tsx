import { useState, useRef, useEffect } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { CalendarCheck2, ChevronDown, Mail, Phone, Send, Sparkles, Users } from 'lucide-react'
import { Logo } from '../../components/Logo'
import './login.css'
import { consumeLoginDestination, pendingLoginDestination, postLoginPath, rememberLoginDestination, STUDIO_ENTRY } from '../../utils/postLogin'
import { api, type TelegramLoginPayload } from '../../api/client'
import { errorMessage, saveLogin } from '../../authUtils'
import { ClientShell } from '../../components/ClientShell'
import { EmailAuthForm } from '../../components/EmailAuthForm'
import { YandexLoginButton } from '../../components/YandexLoginButton'
import { VkLoginButton } from '../../components/VkLoginButton'

// Кнопка Telegram сначала берётся через собственный прокси ServGo (tg.servgo.ru, сервер relay 89): в РФ
// telegram.org и oauth.telegram.org у многих не открываются. Скрипт кнопки сам берёт адрес рамки и окна
// входа с того хоста, откуда загружен; прокси отдаёт /widget.js, /embed, /auth и статику с переписанными
// ссылками. Если прокси не отвечает, пробуем напрямую telegram.org.
// Match the active bot verified by Telegram getMe in the production login preflight.
const LOGIN_BOT_USERNAME = 'sochi_servgo_bot'

const WIDGET_SOURCES = [
  'https://tg.servgo.ru/widget.js',
  'https://telegram.org/js/telegram-widget.js?22',
]
const WIDGET_WAIT_MS = 10000
const YANDEX_PROBLEMS: Record<string, string> = {
  expired: 'Вход через Яндекс не завершился: ссылка устарела. Нажмите кнопку ещё раз.',
  denied: 'Вход через Яндекс отменён.',
  failed: 'Яндекс не ответил. Попробуйте ещё раз или войдите другим способом.',
  unavailable: 'Вход через Яндекс пока недоступен.',
}

export function LoginPage() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const yandexProblem = YANDEX_PROBLEMS[searchParams.get('yandex') || '']
  const vkProblem = ({ expired: 'Ссылка VK ID устарела. Повторите вход.', denied: 'Вход через VK отменён.',
    failed: 'VK ID не подтвердил авторизацию. Повторите или выберите другой способ.',
    unavailable: 'Вход через VK пока не настроен.' } as Record<string, string>)[searchParams.get('vk') || '']
  const studioNext = searchParams.get('next')
  // Пришли из профиля Яндекс-аккаунта, чтобы объединить его с Telegram: сразу показываем кнопку Telegram.
  const joinTelegram = searchParams.get('join') === 'telegram'
  const [mode, setMode] = useState<'phone' | 'code'>('phone')
  const [phone, setPhone] = useState('')
  const [code, setCode] = useState(['', '', '', '', '', ''])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [codeSentVia, setCodeSentVia] = useState<'telegram' | 'fallback'>('telegram')
  const codeRefs = useRef<(HTMLInputElement | null)[]>([])
  const telegramWidgetRef = useRef<HTMLDivElement | null>(null)
  // Кнопка Telegram приходит с telegram.org. Если эта сеть там закрыта (блокировка провайдера,
  // расширение браузера), кнопка не появится: тогда честно говорим об этом и показываем другие входы.
  const [widget, setWidget] = useState<'loading' | 'ready' | 'failed'>('loading')
  const [widgetAttempt, setWidgetAttempt] = useState(0)
  const [widgetSource, setWidgetSource] = useState(0)
  const [method, setMethod] = useState<'email' | 'telegram' | 'phone' | null>(joinTelegram ? 'telegram' : null)

  useEffect(() => {
    if (studioNext !== STUDIO_ENTRY) return
    rememberLoginDestination(studioNext)
    let active = true
    const handleSavedLogin = () => {
      if (!active || !localStorage.getItem('token')) return
      void api.getMe().then(() => {
        if (active && pendingLoginDestination() === STUDIO_ENTRY) {
          consumeLoginDestination()
          navigate(STUDIO_ENTRY, { replace: true })
        }
      }).catch(() => {})
    }
    if (localStorage.getItem('token')) void api.getMe().then(() => {
      if (active && pendingLoginDestination() === STUDIO_ENTRY) {
        consumeLoginDestination()
        navigate(STUDIO_ENTRY, { replace: true })
      }
    }).catch(() => { /* The normal login page remains available. */ })
    window.addEventListener('servgo-login-saved', handleSavedLogin)
    return () => { active = false; window.removeEventListener('servgo-login-saved', handleSavedLogin) }
  }, [navigate, studioNext])

  useEffect(() => {
    if (joinTelegram) telegramWidgetRef.current?.scrollIntoView({ block: 'center' })
  }, [joinTelegram])

  useEffect(() => {
    if (mode === 'code' && codeRefs.current[0]) {
      codeRefs.current[0]?.focus()
    }
  }, [mode])

  useEffect(() => {
    if (method !== 'telegram' || !telegramWidgetRef.current) return
    const host = telegramWidgetRef.current
    const callbackWindow = window as Window & {
      servgoTelegramWidgetAuth?: (data: TelegramLoginPayload) => void
    }
    let active = true
    callbackWindow.servgoTelegramWidgetAuth = (data) => {
      setLoading(true)
      setError('')
      void api.telegramLogin(data)
        .then(async result => {
          if (!active) return
          saveLogin(result)
          const path = await postLoginPath(result.role)
          if (active) navigate(path, { replace: true })
        })
        .catch(err => { if (active) setError(errorMessage(err)) })
        .finally(() => { if (active) setLoading(false) })
    }
    const script = document.createElement('script')
    script.async = true
    script.src = WIDGET_SOURCES[widgetSource]
    script.setAttribute('data-telegram-login', LOGIN_BOT_USERNAME)
    script.setAttribute('data-size', 'large')
    script.setAttribute('data-onauth', 'window.servgoTelegramWidgetAuth(user)')
    // Этот источник не сработал: берём следующий, а если их не осталось, сообщаем об этом.
    const nextSource = () => {
      if (!active) return
      if (widgetSource + 1 < WIDGET_SOURCES.length) setWidgetSource(widgetSource + 1)
      else setWidget('failed')
    }
    script.onerror = nextSource
    host.appendChild(script)
    // Скрипт мог загрузиться, а рамка с самой кнопкой — нет (пустая рамка тоже бывает). Рамка, которая
    // действительно открылась, присылает странице сообщение «ready»: только оно считается успехом.
    const sourceOrigin = new URL(WIDGET_SOURCES[widgetSource]).origin
    const frameOrigins = sourceOrigin === 'https://telegram.org' ? ['https://oauth.telegram.org'] : [sourceOrigin]
    let opened = false
    const onMessage = (event: MessageEvent) => {
      if (!active || !frameOrigins.includes(event.origin) || typeof event.data !== 'string') return
      const frame = host.querySelector('iframe')
      if (!frame || event.source !== frame.contentWindow) return
      try {
        const data = JSON.parse(event.data) as { event?: string }
        if (data.event === 'ready' || data.event === 'resize') { opened = true; setWidget('ready') }
      } catch {
        // Чужие сообщения не про кнопку.
      }
    }
    window.addEventListener('message', onMessage)
    const giveUp = window.setTimeout(() => {
      if (active && !opened) nextSource()
    }, WIDGET_WAIT_MS)
    return () => {
      active = false
      window.removeEventListener('message', onMessage)
      window.clearTimeout(giveUp)
      script.remove()
      host.replaceChildren()
      delete callbackWindow.servgoTelegramWidgetAuth
    }
  }, [method, navigate, widgetAttempt, widgetSource])

  const handleSendCode = async () => {
    if (!phone) return
    setLoading(true)
    setError('')
    try {
      const res = await api.loginPhone(phone)
      setCodeSentVia(res.fallback ? 'fallback' : 'telegram')
      setMethod('phone')
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
          navigate(await postLoginPath(res.role), { replace: true })
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
    window.open(`https://t.me/${LOGIN_BOT_USERNAME}`, '_blank', 'noopener,noreferrer')
  }


  const toggleMethod = (next: 'email' | 'telegram' | 'phone') => {
    setMethod(current => current === next ? null : next)
  }

  return (
    <ClientShell backTo="/" tabs={false} screenClassName="bf-screen--auth" screenLabel="Вход в ServGo">
      <div className="sg-login-layout">
        <aside className="sg-login__brand-panel" aria-label="Возможности ServGo">
          <div className="sg-login__brand-top"><Logo size={39} light /></div>
          <div className="sg-login__brand-message">
            <p className="sg-login__brand-kicker">РАБОЧЕЕ ПРОСТРАНСТВО</p>
            <h2>Ваш бизнес. Одна платформа.</h2>
            <p>Запись клиентов, управление командой и маркетинг — в одном пространстве.</p>
          </div>
          <div className="sg-login__brand-features" aria-label="Разделы платформы">
            <div><CalendarCheck2 size={19} aria-hidden="true" /><span>Онлайн-запись</span></div>
            <div><Users size={19} aria-hidden="true" /><span>Команда</span></div>
            <div><Sparkles size={19} aria-hidden="true" /><span>Studio</span></div>
          </div>
          <div className="sg-login__brand-glow" aria-hidden="true" />
        </aside>
        <section className="sg-login ds-form-narrow" aria-labelledby="sg-login-title">
          <header className="sg-login__form-head">
            <p className="sg-login__form-kicker">SERVGO ACCOUNT</p>
            <h1 id="sg-login-title">Вход в ServGo</h1>
            <p className="sg-login__intro">Один аккаунт для ServGo и Studio. Выберите удобный способ входа.</p>
          </header>
        {studioNext === STUDIO_ENTRY && (
          <p role="status" className="sg-login__notice">
            После входа откроется Студия для доступной компании.
          </p>
        )}
        {yandexProblem && <p role="alert" className="sg-login__error">{yandexProblem}</p>}
        {vkProblem && <p role="alert" className="sg-login__error">{vkProblem}</p>}
        <div className="sg-login__social" aria-label="Вход через сервисы">
          <YandexLoginButton />
          <VkLoginButton />
        </div>

        <div className="sg-login__methods" aria-label="Другие способы входа">
          <button type="button" className="sg-login__method" aria-expanded={method === 'email'}
            aria-controls="sg-login-email" onClick={() => toggleMethod('email')}>
            <Mail size={17} aria-hidden="true" />
            <span>Войти по email</span>
            <ChevronDown className={method === 'email' ? 'sg-login__chevron is-open' : 'sg-login__chevron'} size={16} aria-hidden="true" />
          </button>
          <div id="sg-login-email" className="sg-login__details" hidden={method !== 'email'}>
            {method === 'email' && <EmailAuthForm />}
          </div>

          <button type="button" className="sg-login__method" aria-expanded={method === 'telegram'}
            aria-controls="sg-login-telegram" onClick={() => toggleMethod('telegram')}>
            <Send size={17} aria-hidden="true" />
            <span>Войти через Telegram</span>
            <ChevronDown className={method === 'telegram' ? 'sg-login__chevron is-open' : 'sg-login__chevron'} size={16} aria-hidden="true" />
          </button>
          <div id="sg-login-telegram" className="sg-login__details" hidden={method !== 'telegram'}>
            {method === 'telegram' && (
              <div className="sg-login__telegram">
                {joinTelegram && <p className="ds-hint" role="status">Войдите через Telegram для подтверждения объединения аккаунтов.</p>}
                <div ref={telegramWidgetRef} className="sg-login__telegram-widget" />
                {widget === 'loading' && <p className="ds-hint" role="status">Загружаем кнопку Telegram…</p>}
                {widget === 'failed' && (
                  <div role="status">
                    <p className="ds-hint">Кнопка Telegram не загрузилась. Можно попробовать ещё раз или войти по телефону либо email.</p>
                    <button type="button" className="ds-btn ds-btn--ghost ds-btn--sm"
                      onClick={() => { setWidget('loading'); setWidgetSource(0); setWidgetAttempt(n => n + 1) }}>
                      Повторить загрузку
                    </button>
                  </div>
                )}
                {error && <p role="alert" className="sg-login__error">{error}</p>}
                <p className="ds-hint">Вход выполняется кнопкой Telegram. Простое открытие бота не авторизует на сайте.</p>
                <button type="button" className="sg-login__bot-link" onClick={handleTelegramLogin}>
                  Открыть @{LOGIN_BOT_USERNAME}
                </button>
              </div>
            )}
          </div>

          <button type="button" className="sg-login__method" aria-expanded={method === 'phone'}
            aria-controls="sg-login-phone" onClick={() => toggleMethod('phone')}>
            <Phone size={17} aria-hidden="true" />
            <span>Войти по номеру телефона</span>
            <ChevronDown className={method === 'phone' ? 'sg-login__chevron is-open' : 'sg-login__chevron'} size={16} aria-hidden="true" />
          </button>
          <div id="sg-login-phone" className="sg-login__details" hidden={method !== 'phone'}>
            {method === 'phone' && (mode === 'phone' ? (
              <div className="sg-login__phone">
                <label htmlFor="sg-login-phone-number" className="ds-label">Номер телефона</label>
                <input id="sg-login-phone-number" type="tel" autoComplete="tel"
                  value={phone} onChange={e => setPhone(e.target.value)}
                  placeholder="+7 (___) ___-__-__" className="ds-input" />
                <button type="button" onClick={handleSendCode}
                  disabled={loading || !phone.trim()} className="ds-btn ds-btn--primary ds-btn--block">
                  {loading ? 'Отправляем…' : 'Получить код'}
                </button>
                {error && <p role="alert" className="sg-login__error">{error}</p>}
                <p className="ds-hint">Код придёт через @{LOGIN_BOT_USERNAME}, если номер привязан к вашему аккаунту.</p>
              </div>
            ) : (
              <div className="sg-login__phone">
                <p role="status" className="ds-hint">
                  {codeSentVia === 'telegram'
                    ? 'Код отправлен в Telegram для номера ' + phone
                    : 'Не удалось отправить код в Telegram. Проверьте, что номер зарегистрирован в боте.'}
                </p>
                <div className="sg-login__code-fields" aria-label="Шестизначный код">
                  {code.map((digit, i) => (
                    <input key={i} ref={el => { codeRefs.current[i] = el }}
                      type="text" inputMode="numeric" maxLength={1}
                      aria-label={'Цифра кода ' + (i + 1)} autoComplete={i === 0 ? 'one-time-code' : 'off'}
                      value={digit} onChange={e => handleCodeInput(i, e.target.value)}
                      onKeyDown={e => handleCodeKeyDown(i, e)} className="ds-input" />
                  ))}
                </div>
                {loading && <p className="ds-hint" role="status">Проверяем код…</p>}
                {error && <p role="alert" className="sg-login__error">{error}</p>}
                <button type="button" className="sg-login__bot-link" onClick={() => {
                  setMode('phone')
                  setCode(['', '', '', '', '', ''])
                  setError('')
                }}>Изменить номер</button>
              </div>
            ))}
          </div>
        </div>
        </section>
      </div>
    </ClientShell>
  )
}
