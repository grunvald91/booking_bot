import type { ReactNode } from 'react'
import { AirFrame } from '../pages/client/AirFrame'
import { StudioEntry } from './StudioEntry'

/**
 * Каркас остальных клиентских экранов (записи, абонементы, статус записи,
 * вход, аккаунт, документы) — тот же ServGo Air, что у главной и записи:
 * шапка с логотипом и профилем, заголовок сверху, вкладки внизу.
 */
export function ClientShell({
  title,
  subtitle,
  backTo,
  headerExtra,
  studioEntry,
  tabs = true,
  screenClassName,
  screenLabel,
  children,
}: {
  title?: string
  subtitle?: ReactNode
  backTo?: string
  headerExtra?: ReactNode
  /** Показать вход в маркетинговую студию (если он открыт этому человеку). */
  studioEntry?: boolean
  /** Public auth may omit the unrelated booking navigation. */
  tabs?: boolean
  /** Page-specific responsive layout without modifying shared booking screens. */
  screenClassName?: string
  screenLabel?: string
  children: ReactNode
}) {
  return (
    <AirFrame label={title || 'ServGo'} backTo={backTo} topExtra={headerExtra} tabs={tabs}>
      <section className={screenClassName ? `bf-screen ${screenClassName}` : "bf-screen"} aria-label={screenLabel || title}>
        <div className="bf-inner bf-page bf-shell-page">
          {(title || subtitle != null) && (
            <header className="bf-shell-head">
              {title && <h1 className="bf-h2">{title}</h1>}
              {subtitle != null && <div className="bf-intro">{subtitle}</div>}
            </header>
          )}
          {studioEntry && <StudioEntry />}
          {children}
        </div>
      </section>
    </AirFrame>
  )
}
