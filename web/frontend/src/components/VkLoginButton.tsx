import { useEffect, useState } from 'react'
import { api } from '../api/client'

// VK ID uses the same ServGo account and Studio SSO as other login methods.
// An unconfigured provider is visible but never starts a broken OAuth flow.
export function VkLoginButton() {
  const [status, setStatus] = useState<'checking' | 'ready' | 'unconfigured' | 'error'>('checking')

  useEffect(() => {
    let active = true
    api.vkCapabilities()
      .then(result => { if (active) setStatus(result.available ? 'ready' : 'unconfigured') })
      .catch(() => { if (active) setStatus('error') })
    return () => { active = false }
  }, [])

  const mark = <span className="sg-login__vk-mark" aria-hidden="true">VK</span>
  if (status === 'ready') {
    return (
      <a href="/api/auth/vk/start" className="sg-login__provider sg-login__provider--vk">
        {mark}<span>Войти через VK ID</span>
      </a>
    )
  }
  return (
    <div className="sg-login__provider sg-login__provider--inactive" role="status"
      aria-label={status === 'checking' ? 'Проверяем доступность VK ID' : 'Вход через VK ID недоступен'}>
      {mark}
      <span>{status === 'checking' ? 'Проверяем VK ID…' : 'VK ID — пока недоступен'}</span>
      {status !== 'checking' && (
        <span className="sg-login__provider-help" title={status === 'unconfigured'
          ? 'VK ID не настроен на сервере ServGo'
          : 'Не удалось проверить доступность VK ID'} aria-label="Информация о доступности">i</span>
      )}
    </div>
  )
}
