import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const css = readFileSync(new URL('../src/pages/client/booking-flow.css', import.meta.url), 'utf8')
const login = readFileSync(new URL('../src/pages/client/LoginPage.tsx', import.meta.url), 'utf8')
const email = readFileSync(new URL('../src/components/EmailAuthForm.tsx', import.meta.url), 'utf8')

test('login/account shell overrides light-only card and account panels for dark mode', () => {
  const dark = css.slice(css.indexOf("html[data-theme='dark'] .bf-root"))
  assert.ok(dark.includes("html[data-theme='dark'] .bf-shell-page .ds-card"))
  assert.ok(dark.includes("html[data-theme='dark'] .bf-account-card"))
  assert.ok(dark.includes("html[data-theme='dark'] .bf-account-row"))
  assert.match(dark, /\.bf-shell-page \.ds-card,[\s\S]*?background: var\(--s-surface-2\)/)
  assert.match(dark, /\.bf-shell-page \.ds-card \.ds-input[\s\S]*?background: var\(--s-surface\)/)
  assert.match(dark, /color-scheme: dark;/)
})

test('sign-in components use theme classes rather than static white fields', () => {
  assert.match(login, /<YandexLoginButton \/>/)
  assert.match(login, /<VkLoginButton \/>/)
  assert.match(login, /<EmailAuthForm \/>/)
  assert.match(email, /className="ds-card"/)
  assert.match(email, /className="ds-input"/)
  assert.doesNotMatch(email, /background:\s*['\"](?:white|#fff)/i)
})

test('VK sign-in and explicit identity linking are exposed in the current account experience', () => {
  const account = readFileSync(new URL('../src/pages/client/AccountPage.tsx', import.meta.url), 'utf8')
  const routes = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8')
  const vkLink = readFileSync(new URL('../src/components/VkAccountLink.tsx', import.meta.url), 'utf8')
  assert.match(account, /<VkAccountLink \/>/)
  assert.match(routes, /path="\/login\/vk"/)
  assert.match(vkLink, /vkLinkStart/)
  assert.doesNotMatch(vkLink, /background:\s*['\"](?:white|#fff)/i)
})

test('all five ServGo login methods remain discoverable on site and Studio', () => {
  const layout = readFileSync(new URL('../src/pages/client/login.css', import.meta.url), 'utf8')
  const vk = readFileSync(new URL('../src/components/VkLoginButton.tsx', import.meta.url), 'utf8')
  const yandex = readFileSync(new URL('../src/components/YandexLoginButton.tsx', import.meta.url), 'utf8')
  const routes = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8')

  assert.match(login, /className="sg-login ds-form-narrow"/)
  assert.match(layout, /grid-template-columns:\s*minmax\(0, 1\.08fr\) minmax\(390px, \.92fr\)/)
  assert.match(layout, /@media \(min-width:\s*1024px\)/)
  assert.match(layout, /\.bf-screen--auth \{/)
  assert.match(login, /screenClassName="bf-screen--auth" screenLabel="Вход в ServGo"/)
  assert.match(login, /<aside className="sg-login__brand-panel"/)
  assert.match(login, /aria-labelledby="sg-login-title"/)
  assert.match(login, /useState<('email' \| 'telegram' \| 'phone' \| null)>/)
  for (const caption of ['Войти по email', 'Войти через Telegram', 'Войти по номеру телефона']) {
    assert.ok(login.includes(caption), caption)
  }
  assert.match(login, /<YandexLoginButton \/>/)
  assert.match(login, /<VkLoginButton \/>/)
  assert.match(login, /id="sg-login-email"/)
  assert.match(login, /id="sg-login-telegram"/)
  assert.match(login, /id="sg-login-phone"/)
  assert.match(login, /mode === 'phone'/)
  assert.match(login, /autoComplete=\{i === 0 \? 'one-time-code'/)
  assert.match(vk, /status === 'ready'/)
  assert.match(vk, /\/api\/auth\/vk\/start/)
  assert.match(vk, /VK ID — пока недоступен/)
  assert.match(yandex, /status !== 'ready'/)
  assert.match(yandex, /Яндекс — пока недоступен/)
  assert.match(yandex, /\/api\/auth\/yandex\/start/)
  assert.match(routes, /path="\/login" element=\{<LoginPage \/>\}/)
  assert.match(routes, /path="\/workspace\/studio-entry"/)
})

test('Studio company selection uses the same protected ServGo identity and desktop layout', () => {
  const studio = readFileSync(new URL('../src/pages/client/StudioSignInPage.tsx', import.meta.url), 'utf8')
  const style = readFileSync(new URL('../src/pages/client/studio-entry.css', import.meta.url), 'utf8')
  const shell = readFileSync(new URL('../src/components/ClientShell.tsx', import.meta.url), 'utf8')
  assert.match(studio, /screenClassName="bf-screen--studio-entry"/)
  assert.match(studio, /<StudioEntry autoOpen showUnavailable \/>/)
  assert.match(style, /@media \(min-width:\s*1024px\)/)
  assert.match(style, /grid-template-columns:\s*minmax\(0, \.96fr\) minmax\(400px, 1\.04fr\)/)
  assert.match(shell, /screenClassName\?: string/)
  assert.match(shell, /aria-label=\{screenLabel \|\| title\}/)
})

test('standalone canonical login and Studio do not mount duplicate public navbar', () => {
  const appLayout = readFileSync(new URL('../src/components/Layout.tsx', import.meta.url), 'utf8')
  assert.match(appLayout, /location\.pathname === '\/login'/)
  assert.match(appLayout, /location\.pathname === '\/workspace\/studio-entry'/)
  assert.match(appLayout, /return <Outlet \/>/)
})


test('Telegram login widget and support links use the verified active bot', () => {
  assert.match(login, /const LOGIN_BOT_USERNAME = 'sochi_servgo_bot'/)
  assert.match(login, /script\.setAttribute\('data-telegram-login', LOGIN_BOT_USERNAME\)/)
  assert.match(login, /window\.open\(\x60https:\/\/t\.me\/\$\{LOGIN_BOT_USERNAME\}\x60/)
  assert.match(login, /Открыть @\{LOGIN_BOT_USERNAME\}/)
  assert.match(login, /Код придёт через @\{LOGIN_BOT_USERNAME\}/)
  assert.doesNotMatch(login, /Sochiservice_bot/i)
})


test('temporarily disabled Telegram login widget has a working phone fallback', () => {
  assert.match(login, /const TELEGRAM_WIDGET_DOMAIN_VERIFIED = false/)
  assert.match(login, /if \(!TELEGRAM_WIDGET_DOMAIN_VERIFIED \|\| method !== 'telegram'/)
  assert.match(login, /TELEGRAM_WIDGET_DOMAIN_VERIFIED && <>/)
  assert.match(login, /setMethod\('phone'\)/)
  assert.match(login, /Прямой вход через Telegram временно недоступен/)
  assert.match(login, /joinTelegram \? 'phone' : 'email'/)
})

test('Yandex explanation does not require a third-party browser installation', () => {
  const yandex = readFileSync(new URL('../src/components/YandexLoginButton.tsx', import.meta.url), 'utf8')
  assert.match(yandex, /ServGo не требует устанавливать браузер или расширение/)
  assert.match(yandex, /используйте тот же Яндекс ID/)
  assert.match(yandex, /восстановите пароль/)
})
