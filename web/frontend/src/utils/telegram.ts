// Telegram WebApp types
declare global {
  interface Window {
    Telegram?: {
      WebApp: TelegramWebApp
    }
  }
}

interface TelegramWebApp {
  ready: () => void
  expand: () => void
  close: () => void
  initData: string
  initDataUnsafe: {
    user?: {
      id: number
      first_name: string
      last_name?: string
      username?: string
    }
  }
  themeParams: Record<string, string>
  HapticFeedback: {
    selectionChanged: () => void
    notificationOccurred: (type: 'success' | 'error' | 'warning') => void
    impactOccurred: (style: 'light' | 'medium' | 'heavy') => void
  }
  showConfirm: (message: string, callback: (confirmed: boolean) => void) => void
  showPopup: (
    params: {
      title?: string
      message: string
      buttons?: Array<{ type: string; text: string }>
    },
    callback?: (buttonId: string) => void
  ) => void
  MainButton: {
    text: string
    show: () => void
    hide: () => void
    onClick: (fn: () => void) => void
    offClick: (fn: () => void) => void
    enable: () => void
    disable: () => void
    showProgress: (leaveActive: boolean) => void
    hideProgress: () => void
    isVisible: boolean
    isActive: boolean
    isProgressVisible: boolean
    color: string
    textColor: string
  }
  BackButton: {
    show: () => void
    hide: () => void
    onClick: (fn: () => void) => void
    offClick: (fn: () => void) => void
    isVisible: boolean
  }
  // Отступы от собственного UI Telegram (шапка с меню, safe area устройства).
  // Доступны с Bot API 8.0+ — на старых клиентах будут undefined.
  safeAreaInset?: { top: number; bottom: number; left: number; right: number }
  contentSafeAreaInset?: { top: number; bottom: number; left: number; right: number }
  onEvent: (eventType: string, callback: () => void) => void
  offEvent: (eventType: string, callback: () => void) => void
}

// ВРЕМЕННО: живой калибратор отступа под шапку Telegram — panel внизу экрана
// с кнопками +/-, не перекрывает область, которую как раз калибруем (верх).
// safeAreaInset/contentSafeAreaInset у Telegram оказались нулевыми на реальном
// устройстве — полагаться на API нельзя, подбираем значение вручную и один раз.
// Убрать вызов showSafeAreaCalibrator() (и саму функцию) после того как отступ
// будет подобран и зашит в CSS.
function showSafeAreaCalibrator() {
  if (!tg) return
  let current = 60
  document.documentElement.style.setProperty('--tg-safe-top', `${current}px`)

  const bar = document.createElement('div')
  bar.style.cssText =
    'position:fixed;bottom:0;left:0;right:0;z-index:999999;background:#000;color:#0f0;' +
    'font:13px/1.4 monospace;padding:10px;display:flex;align-items:center;gap:6px;flex-wrap:wrap;'

  const label = document.createElement('span')
  label.style.cssText = 'margin-right:auto;font-weight:bold;'
  const render = () => { label.textContent = `Отступ: ${current}px` }
  render()

  const mkBtn = (text: string, delta: number) => {
    const b = document.createElement('button')
    b.textContent = text
    b.style.cssText =
      'background:#0f0;color:#000;border:none;border-radius:6px;padding:8px 12px;font:13px monospace;font-weight:bold;'
    b.onclick = () => {
      current = Math.max(0, current + delta)
      document.documentElement.style.setProperty('--tg-safe-top', `${current}px`)
      render()
    }
    return b
  }

  const closeBtn = document.createElement('button')
  closeBtn.textContent = 'Готово'
  closeBtn.style.cssText =
    'background:#333;color:#0f0;border:1px solid #0f0;border-radius:6px;padding:8px 12px;font:13px monospace;'
  closeBtn.onclick = () => bar.remove()

  bar.append(label, mkBtn('−10', -10), mkBtn('−1', -1), mkBtn('+1', 1), mkBtn('+10', 10), closeBtn)
  document.body.appendChild(bar)
}

// Helper functions
export const tg = window.Telegram?.WebApp

export const isTelegramWebApp = !!tg

export function initTelegramWebApp() {
  if (!tg) return
  tg.ready()
  tg.expand()

  // Add class to body so CSS can target Telegram WebApp context
  document.documentElement.classList.add('tg-webapp')

  // Реальная высота шапки Telegram (меню/стрелка/название) — берём у самого
  // Telegram вместо зашитой константы, т.к. высота "родной" шапки отличается
  // от чата к чату/устройству к устройству. contentSafeAreaInset уже покрывает
  // зону под шапкой целиком (включая системную область) — плюсовать к нему ещё
  // safeAreaInset не нужно, иначе отступ задваивается и получается с запасом.
  const applySafeArea = () => {
    const top = tg.contentSafeAreaInset?.top ?? tg.safeAreaInset?.top ?? 0
    if (top > 0) {
      document.documentElement.style.setProperty('--tg-safe-top', `${top}px`)
    }
  }
  applySafeArea()
  tg.onEvent?.('safeAreaChanged', applySafeArea)
  tg.onEvent?.('contentSafeAreaChanged', applySafeArea)

  // ВРЕМЕННО: живой калибратор отступа (см. функцию выше). Убрать после подбора.
  showSafeAreaCalibrator()

  // Apply theme colors as CSS variables
  const params = tg.themeParams
  if (params) {
    const root = document.documentElement.style
    if (params.bg_color) root.setProperty('--tg-bg-color', params.bg_color)
    if (params.text_color) root.setProperty('--tg-text-color', params.text_color)
    if (params.button_color) root.setProperty('--tg-button-color', params.button_color)
    if (params.button_text_color)
      root.setProperty('--tg-button-text-color', params.button_text_color)
    if (params.secondary_bg_color)
      root.setProperty('--tg-secondary-bg-color', params.secondary_bg_color)
  }
}

export function hapticSelection() {
  tg?.HapticFeedback?.selectionChanged()
}

export function hapticSuccess() {
  tg?.HapticFeedback?.notificationOccurred('success')
}

export function hapticError() {
  tg?.HapticFeedback?.notificationOccurred('error')
}

export function hapticImpact(style: 'light' | 'medium' | 'heavy' = 'medium') {
  tg?.HapticFeedback?.impactOccurred(style)
}

export function getTelegramUser() {
  return tg?.initDataUnsafe?.user || null
}

export function getTelegramInitData() {
  return tg?.initData || ''
}

// Confirmation dialog — uses Telegram native if available, browser fallback
export function confirmAction(message: string): Promise<boolean> {
  return new Promise((resolve) => {
    if (tg) {
      tg.showConfirm(message, resolve)
    } else {
      resolve(window.confirm(message))
    }
  })
}

// Show main button
export function showMainButton(text: string, onClick: () => void) {
  if (!tg) return
  tg.MainButton.text = text
  tg.MainButton.onClick(onClick)
  tg.MainButton.show()
}

// Hide main button
export function hideMainButton() {
  if (!tg) return
  tg.MainButton.hide()
}

// Back button
export function showBackButton(onClick: () => void) {
  if (!tg) return
  tg.BackButton.onClick(onClick)
  tg.BackButton.show()
}

export function hideBackButton() {
  if (!tg) return
  tg.BackButton.hide()
}
