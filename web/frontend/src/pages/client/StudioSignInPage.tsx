import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { Sparkles } from 'lucide-react'
import { ClientShell } from '../../components/ClientShell'
import { api } from '../../api/client'
import { isTrustedStudioTicketUrl } from '../../utils/studioTicketUrl'
import './studio-entry.css'

/** An account-level ticket opens Studio without selecting a booking business. */
export function StudioSignInPage() {
  const opening = useRef(false)
  const [error, setError] = useState('')
  const open = useCallback(async () => {
    if (opening.current) return
    opening.current = true
    setError('')
    try {
      const { url } = await api.studioAccountTicket()
      if (!isTrustedStudioTicketUrl(url)) throw new Error('Unexpected Studio SSO destination')
      window.location.assign(url)
    } catch {
      opening.current = false
      setError('Не удалось открыть Studio. Попробуйте ещё раз.')
    }
  }, [])
  useEffect(() => { void open() }, [open])

  return (
    <ClientShell backTo="/account" tabs={false}
      screenClassName="bf-screen--studio-entry" screenLabel="Студия ServGo">
      <div className="sg-studio-layout">
        <section className="sg-studio-businesses">
          <span className="sg-studio-eyebrow"><Sparkles size={18} aria-hidden="true" /> SERVGO STUDIO</span>
          <h1>Студия ServGo</h1>
          {error ? <>
            <p role="alert">{error}</p>
            <button className="bf-account-row" type="button" onClick={open}>Повторить вход</button>
          </> : <p role="status">Открываем Studio…</p>}
          <Link to="/account" className="sg-studio-account-link">Мой аккаунт</Link>
        </section>
      </div>
    </ClientShell>
  )
}
