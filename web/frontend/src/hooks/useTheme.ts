import { useEffect, useState } from 'react'

type Theme = 'light' | 'dark'

function detectInitial(): Theme {
  const saved = localStorage.getItem('schedTheme')
  if (saved === 'dark' || saved === 'light') return saved
  const tg = (window as unknown as { Telegram?: { WebApp?: { colorScheme?: string } } }).Telegram?.WebApp?.colorScheme
  if (tg === 'dark') return 'dark'
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

/**
 * Светлая/тёмная тема для админ-экранов. Хранит выбор в localStorage
 * (общий ключ schedTheme), по умолчанию следует Telegram colorScheme / системе.
 */
export function useTheme(): [Theme, () => void] {
  const [theme, setTheme] = useState<Theme>(detectInitial)
  useEffect(() => { localStorage.setItem('schedTheme', theme) }, [theme])
  const toggle = () => setTheme((t) => (t === 'dark' ? 'light' : 'dark'))
  return [theme, toggle]
}
