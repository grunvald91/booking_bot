import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../../api/client'
import { EmailAuthForm } from '../../components/EmailAuthForm'
import { errorMessage } from '../../authUtils'
import { TelegramAccountLink } from '../../components/TelegramAccountLink'
import { ClientShell } from '../../components/ClientShell'

export function AccountPage() {
  const [account, setAccount] = useState<Awaited<ReturnType<typeof api.emailAccount>> | null>(null)
  const [error, setError] = useState('')
  useEffect(() => { api.emailAccount().then(setAccount).catch(e => setError(errorMessage(e))) }, [])
  return <ClientShell title="Вход в аккаунт" backTo={localStorage.getItem('userRole') === 'client' ? '/my' : '/admin/settings'}>
    <div className="ds-form-narrow" style={{ paddingTop: 20 }}>
      {error && <p role="alert">{error}</p>}
      {account && (account.email ? <div className="ds-card" style={{ padding: 16 }}>
        <h2 className="ds-h3">Email подтверждён</h2><p>{account.email}</p>
        <p>Вы можете входить по email и паролю без Telegram.</p>
        <Link to="/login">Восстановить пароль на странице входа</Link>
      </div> : <><p>Привяжите подтверждённую почту к текущему аккаунту — ваши бизнесы и права сохранятся.</p><EmailAuthForm link /></>)}
      {account?.telegram ? <div className="ds-card" style={{ padding: 16, marginTop: 16 }}><h2 className="ds-h3">Telegram привязан</h2><p>{account.telegram.username ? `@${account.telegram.username}` : account.telegram.id}</p></div> : account?.email && (account.telegram_link_available ? <TelegramAccountLink /> : <p>Привязка Telegram пока не настроена администратором платформы.</p>)}
    </div>
  </ClientShell>
}
