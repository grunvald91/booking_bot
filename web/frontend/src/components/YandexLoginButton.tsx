import { useEffect, useState } from 'react'
import { api } from '../api/client'

// Both the public site and Studio start this same canonical ServGo login flow.
export function YandexLoginButton() {
  const [available, setAvailable] = useState(false)
  useEffect(() => {
    let active = true
    api.yandexCapabilities()
      .then(result => { if (active) setAvailable(result.available) })
      .catch(() => { if (active) setAvailable(false) })
    return () => { active = false }
  }, [])

  if (!available) return null
  return (
    <div className="sg-login__provider-group">
      <a href="/api/auth/yandex/start" className="sg-login__provider sg-login__provider--yandex">
        <span className="sg-login__yandex-mark" aria-hidden="true">Я</span>
        <span>Войти через Яндекс</span>
      </a>
      <details className="sg-login__data-note">
        <summary>Какие данные передаются?</summary>
        <p>Яндекс передаст ServGo имя, почту, телефон и дату рождения, если вы это разрешите. Пароль от Яндекса мы не получаем.</p>
      </details>
    </div>
  )
}
