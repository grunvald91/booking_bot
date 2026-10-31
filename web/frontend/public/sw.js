/*
 * ServGo PWA service worker — shared-origin migration foundation.
 *
 * SECURITY: Never cache HTML navigations, authenticated responses or API data.
 * In particular, future /workspace/growth/* and /workspace/mail/* pages must
 * not be stored under the public SPA shell key (the previous v2 did that).
 *
 * This worker owns only caches matching servgo-pwa-v<number>.
 * Do not delete push subscriptions or other apps' CacheStorage namespaces.
 */
const CACHE_NAME = 'servgo-pwa-v3'
const PRECACHE = ['/offline.html', '/favicon.svg', '/icon-192.png', '/icon-512.png']
const PUBLIC_ICONS = new Set(PRECACHE.filter((path) => path !== '/offline.html'))

function publicStaticAsset(path) {
  // /assets/ is reserved for Vite-built, publicly served static resources.
  // Do not broaden this matcher to /api, /studio, /workspace or arbitrary images.
  return path.startsWith('/assets/') && /\.(?:css|js|woff2?|ttf|eot|svg|png|jpe?g|webp|avif|ico)$/i.test(path)
}

function cacheableStaticResponse(response) {
  if (!response.ok || response.type !== 'basic') return false
  const cacheControl = response.headers.get('cache-control') || ''
  const contentType = response.headers.get('content-type') || ''
  return !/\b(?:private|no-store)\b/i.test(cacheControl)
    && !/\btext\/html\b/i.test(contentType)
}

self.addEventListener('install', (event) => {
  event.waitUntil((async () => {
    try {
      const cache = await caches.open(CACHE_NAME)
      await cache.addAll(PRECACHE)
    } catch (_) {
      // Installation must not prevent network-only navigation if offline assets fail.
    }
    await self.skipWaiting()
  })())
})

self.addEventListener('activate', (event) => {
  event.waitUntil((async () => {
    const names = await caches.keys()
    await Promise.all(names
      .filter((name) => /^servgo-pwa-v\d+$/.test(name) && name !== CACHE_NAME)
      .map((name) => caches.delete(name)))
    await self.clients.claim()
  })())
})

self.addEventListener('fetch', (event) => {
  const request = event.request
  if (request.method !== 'GET') return

  const url = new URL(request.url)
  if (url.origin !== self.location.origin) return

  if (request.mode === 'navigate') {
    // Network-only for *every* navigation, including public and private pages.
    // Never cache a signed-in HTML response as / or /index.html.
    event.respondWith(fetch(request).catch(async () => {
      const cached = await caches.open(CACHE_NAME).then((cache) => cache.match('/offline.html'))
      return cached || new Response('ServGo: нет соединения', {
        status: 503,
        headers: { 'Content-Type': 'text/plain; charset=utf-8' },
      })
    }))
    return
  }

  // Do not intercept API requests or protected files. In particular:
  // /api, /admin, /workspace, /studio, /mail, /my, /attachments.
  if (request.cache === 'no-store' ||
      (!PUBLIC_ICONS.has(url.pathname) && !publicStaticAsset(url.pathname))) return

  event.respondWith((async () => {
    const cache = await caches.open(CACHE_NAME)
    const cached = await cache.match(request)
    if (cached) return cached

    const response = await fetch(request)
    if (cacheableStaticResponse(response)) {
      try { await cache.put(request, response.clone()) } catch (_) { /* quota / private mode */ }
    }
    return response
  })())
})

self.addEventListener('push', (event) => {
  let payload = {}
  try {
    payload = event.data ? event.data.json() : {}
  } catch {
    payload = { body: event.data ? event.data.text() : '' }
  }

  const title = payload.title || 'ServGo'
  const options = {
    requireInteraction: payload.event_kind === 'prepayment_submitted',
    renotify: payload.event_kind === 'prepayment_submitted',
    body: payload.body || 'У вас есть обновление по записи',
    icon: '/icon-192.png',
    tag: payload.tag || 'servgo',
    data: {
      url: payload.url || '/my',
      bookingId: payload.booking_id || null,
    },
  }

  event.waitUntil(Promise.all([
    self.registration.showNotification(title, options),
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((clients) => {
      if (payload.event_kind === 'prepayment_submitted') {
        clients.forEach((client) => client.postMessage({ type: 'servgo-prepayment-update' }))
      }
    }),
  ]))
})

self.addEventListener('notificationclick', (event) => {
  event.notification.close()
  let targetUrl = new URL('/my', self.location.origin).href
  try {
    const requested = new URL(event.notification?.data?.url || '/my', self.location.origin)
    // A notification must not send the installed PWA to an untrusted origin.
    if (requested.origin === self.location.origin) targetUrl = requested.href
  } catch (_) { /* keep /my */ }

  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((clients) => {
      for (const client of clients) {
        if ('focus' in client) {
          if ('navigate' in client && client.url !== targetUrl) {
            return client.navigate(targetUrl).then(() => client.focus())
          }
          return client.focus()
        }
      }
      return self.clients.openWindow ? self.clients.openWindow(targetUrl) : undefined
    })
  )
})
