import { useEffect, useRef, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import {
  Home,
  ClipboardList,
  Ticket,
  MessageCircle,
  User,
  LogOut,
  LayoutDashboard,
  Moon,
  Sun,
  ArrowLeft,
} from 'lucide-react'
import { useTheme } from '../hooks/useTheme'
import { Logo } from './Logo'

const NAV = [
  { to: '/', label: 'Главная', Icon: Home },
  { to: '/my', label: 'Записи', Icon: ClipboardList },
  { to: '/subscriptions', label: 'Абонементы', Icon: Ticket },
  { to: '/chat', label: 'AI', Icon: MessageCircle },
]

/**
 * Единый каркас клиентских экранов (тот же паттерн, что AdminShell):
 * полноэкранный ds-screen через createPortal + шапка (лого/back, заголовок,
 * переключатель темы) + нижняя навигация ds-bottomnav (боковая на десктопе).
 */
export function ClientShell({
  title,
  subtitle,
  backTo,
  headerExtra,
  children,
}: {
  title?: string
  subtitle?: ReactNode
  backTo?: string
  headerExtra?: ReactNode
  children: ReactNode
}) {
  const [theme, toggleTheme] = useTheme()
  const { pathname } = useLocation()
  const navigate = useNavigate()
  const [profileOpen, setProfileOpen] = useState(false)
  const profileRef = useRef<HTMLDivElement>(null)

  const token = localStorage.getItem('token')
  const role = localStorage.getItem('userRole')
  const isLoggedIn = !!token
  const isAdminUser = role === 'admin' || role === 'owner'

  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (profileRef.current && !profileRef.current.contains(e.target as Node)) {
        setProfileOpen(false)
      }
    }
    if (profileOpen) document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [profileOpen])

  const handleLogout = () => {
    localStorage.removeItem('token')
    localStorage.removeItem('userRole')
    localStorage.removeItem('userName')
    window.location.href = '/'
  }

  return createPortal(
    <div className="ds-screen" data-theme={theme}>
      <header className="ds-shell-header" style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '12px 14px', flexShrink: 0 }}>
        {backTo ? (
          <button className="ds-icon-btn" onClick={() => navigate(backTo)} aria-label="Назад">
            <ArrowLeft size={18} />
          </button>
        ) : (
          <Logo size={26} light={theme === 'dark'} />
        )}
        <div style={{ flex: 1, minWidth: 0 }}>
          {title && <h1 className="ds-h1" style={{ whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{title}</h1>}
          {subtitle != null && <div className="ds-sub" style={{ marginTop: 2 }}>{subtitle}</div>}
        </div>
        {headerExtra}
        <button className="ds-icon-btn bordered" onClick={toggleTheme} aria-label="Тема">
          {theme === 'dark' ? <Sun size={18} /> : <Moon size={18} />}
        </button>
      </header>

      <div className="ds-shell-content" style={{ flex: 1, minHeight: 0, overflowY: 'auto', WebkitOverflowScrolling: 'touch', padding: '0 14px 16px' }}>
        {children}
      </div>

      <nav className="ds-bottomnav">
        {NAV.map(({ to, label, Icon }) => (
          <Link key={to} to={to} className={`ds-bn${pathname === to ? ' active' : ''}`}>
            <Icon size={21} />
            <span>{label}</span>
          </Link>
        ))}

        <div ref={profileRef} style={{ position: 'relative', flex: 1 }}>
          {isLoggedIn ? (
            <button
              onClick={() => setProfileOpen((v) => !v)}
              className={`ds-bn${profileOpen ? ' active' : ''}`}
              style={{ width: '100%', background: 'none', border: 'none', font: 'inherit' }}
            >
              <User size={21} />
              <span>Профиль</span>
            </button>
          ) : (
            <Link to="/login" className={`ds-bn${pathname === '/login' ? ' active' : ''}`}>
              <User size={21} />
              <span>Войти</span>
            </Link>
          )}

          {profileOpen && isLoggedIn && (
            <div
              className="ds-card"
              style={{
                position: 'absolute', bottom: '100%', right: 0, marginBottom: 8,
                width: 220, padding: 6, boxShadow: 'var(--sh-pop)', zIndex: 90,
              }}
            >
              <div style={{ padding: '8px 10px', borderBottom: '1px solid var(--s-line)', marginBottom: 4 }}>
                <div className="ds-text" style={{ fontWeight: 700 }}>
                  {localStorage.getItem('userName') || 'Пользователь'}
                </div>
              </div>
              {isAdminUser && (
                <Link
                  to="/admin"
                  onClick={() => setProfileOpen(false)}
                  className="ds-row"
                  style={{ border: 'none', background: 'none', borderRadius: 9, padding: '8px 10px', marginBottom: 2 }}
                >
                  <LayoutDashboard size={16} style={{ color: 'var(--s-muted)' }} />
                  <span className="ds-text">Админ-панель</span>
                </Link>
              )}
              <button
                onClick={() => { setProfileOpen(false); handleLogout() }}
                className="ds-row"
                style={{ border: 'none', background: 'none', borderRadius: 9, padding: '8px 10px', width: '100%', cursor: 'pointer' }}
              >
                <LogOut size={16} style={{ color: 'var(--s-danger)' }} />
                <span className="ds-text" style={{ color: 'var(--s-danger)' }}>Выйти</span>
              </button>
            </div>
          )}
        </div>
      </nav>
    </div>,
    document.body
  )
}
