import type { ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { LayoutDashboard, Clock, Scissors, Users, Settings, Moon, Sun, LogOut, MessageCircle } from 'lucide-react'
import { useTheme } from '../hooks/useTheme'

const NAV = [
  { to: '/admin', label: 'Панель', Icon: LayoutDashboard },
  { to: '/admin/schedule', label: 'Расписание', Icon: Clock },
  { to: '/admin/prepayments', label: 'Предоплаты', Icon: Clock },
  { to: '/admin/services', label: 'Услуги', Icon: Scissors },
  { to: '/admin/employees', label: 'Мастера', Icon: Users },
  { to: '/admin/sales', label: 'Диалоги', Icon: MessageCircle },
  { to: '/admin/settings', label: 'Настройки', Icon: Settings },
]

/**
 * Единый каркас экранов админки в дизайне расписания:
 * полноэкранный ds-screen + шапка (заголовок, слот, переключатель темы) +
 * нижняя навигация ds-bottomnav. Контент скроллится между ними.
 * Тема — общий useTheme() (свет/тёмная + Telegram + localStorage).
 */
export function AdminShell({
  title,
  subtitle,
  headerExtra,
  children,
}: {
  title: string
  subtitle?: ReactNode
  headerExtra?: ReactNode
  children: ReactNode
}) {
  const [theme, toggleTheme] = useTheme()
  const { pathname } = useLocation()
  const navigate = useNavigate()

  const handleLogout = () => {
    localStorage.removeItem('token')
    localStorage.removeItem('userRole')
    localStorage.removeItem('userName')
    sessionStorage.setItem('servgoExplicitLogout', '1')
    navigate('/login', { replace: true })
  }
  return createPortal(
    <div className="ds-screen" data-theme={theme}>
      <header className="ds-shell-header" style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '12px 14px', flexShrink: 0 }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <h1 className="ds-h1">{title}</h1>
          {subtitle != null && <div className="ds-sub" style={{ marginTop: 2 }}>{subtitle}</div>}
        </div>
        {headerExtra}
        <button className="ds-icon-btn bordered" onClick={toggleTheme} aria-label="Тема">
          {theme === 'dark' ? <Sun size={18} /> : <Moon size={18} />}
        </button>
        <button className="ds-icon-btn bordered" onClick={handleLogout} aria-label="Выйти" title="Выйти">
          <LogOut size={18} />
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
      </nav>
    </div>,
    document.body
  )
}
