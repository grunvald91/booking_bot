import { useEffect, useState } from 'react'
import { api } from '../api/client'

// A failed capabilities request must not silently remove a supported login choice.
export function YandexLoginButton() {
  const [status, setStatus] = useState<'checking' | 'ready' | 'unavailable'>('checking')

  useEffect(() => {
    let active = true
    api.yandexCapabilities()
      .then(result => { if (active) setStatus(result.available ? 'ready' : 'unavailable') })
      .catch(() => { if (active) setStatus('unavailable') })
    return () => { active = false }
  }, [])

  const mark = <span className="sg-login__yandex-mark" aria-hidden="true">Я</span>
  if (status !== 'ready') {
    return (
      <div className="sg-login__provider sg-login__provider--inactive" role="status"
        aria-label={status === 'checking' ? 'Проверяем доступность Яндекса' : 'Вход через Яндекс недоступен'}>
        {mark}<span>{status === 'checking' ? 'Проверяем Яндекс…' : 'Яндекс — пока недоступен'}</span>
      </div>
    )
  }

  return (
    <div className="sg-login__provider-group">
      <a href="/api/auth/yandex/start" className="sg-login__provider sg-login__provider--yandex">
        {mark}<span>Войти через Яндекс</span>
      </a>
      <details className="sg-login__data-note">
        <summary>Какие данные передаются?</summary>
        <p>Яндекс передаст ServGo имя, почту, телефон и дату рождения, если вы это разрешите. Пароль от Яндекса мы не получаем.</p>
      </details>
    </div>
  )
}
