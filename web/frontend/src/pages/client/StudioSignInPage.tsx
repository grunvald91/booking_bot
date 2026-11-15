import { Link } from 'react-router-dom'
import { Building2, Sparkles } from 'lucide-react'
import { ClientShell } from '../../components/ClientShell'
import { StudioEntry } from '../../components/StudioEntry'
import './studio-entry.css'

/** Studio reuses the canonical ServGo session; selecting a company grants its scoped SSO ticket. */
export function StudioSignInPage() {
  return (
    <ClientShell backTo="/account" tabs={false}
      screenClassName="bf-screen--studio-entry" screenLabel="Студия ServGo">
      <div className="sg-studio-layout">
        <header className="sg-studio-intro">
          <span className="sg-studio-eyebrow"><Sparkles size={18} aria-hidden="true" /> SERVGO STUDIO</span>
          <h1>Маркетинг вашей компании</h1>
          <p>Выберите компанию, с которой хотите работать. Дополнительный вход не нужен — используется ваш аккаунт ServGo.</p>
          <div className="sg-studio-intro-mark" aria-hidden="true"><Building2 size={54} /></div>
        </header>
        <section className="sg-studio-businesses" aria-labelledby="sg-studio-businesses-title">
          <h2 id="sg-studio-businesses-title">Ваши компании</h2>
          <p className="sg-studio-hint">Доступны только компании, к которым у вас есть права.</p>
          <StudioEntry autoOpen showUnavailable />
          <p className="sg-studio-hint">Если компании нет в списке, проверьте доступ у владельца организации.</p>
          <Link to="/account" className="sg-studio-account-link">Мой аккаунт</Link>
        </section>
      </div>
    </ClientShell>
  )
}
