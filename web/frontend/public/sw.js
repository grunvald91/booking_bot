const CACHE_NAME = 'servgo-pwa-v2'
const APP_SHELL = ['/', '/manifest.webmanifest', '/favicon.svg']

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then((cache) => cache.addAll(APP_SHELL))
      .catch(() => undefined)
      .then(() => self.skipWaiting())
  )
})

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key))))
      .then(() => self.clients.claim())
  )
})

self.addEventListener('fetch', (event) => {
  const request = event.request
  if (request.method !== 'GET') return

  const url = new URL(request.url)
  if (url.origin !== self.location.origin) return
  if (url.pathname.startsWith('/api/')) return

  if (request.mode === 'navigate') {
    event.respondWith(
      fetch(request)
        .then((response) => {
          const copy = response.clone()
          caches.open(CACHE_NAME).then((cache) => cache.put('/index.html', copy))
          return response
        })
        .catch(() => caches.match('/index.html').then((cached) => cached || caches.match('/')))
    )
    return
  }

  event.respondWith(
    caches.match(request).then((cached) => {
      const network = fetch(request)
        .then((response) => {
          if (response.ok && (response.type === 'basic' || response.type === 'default')) {
            const copy = response.clone()
            caches.open(CACHE_NAME).then((cache) => cache.put(request, copy))
          }
          return response
        })
        .catch(() => cached)

      return cached || network
    })
  )
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
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then(clients => {
      if (payload.event_kind === 'prepayment_submitted') {
        clients.forEach(client => client.postMessage({ type: 'servgo-prepayment-update' }))
      }
    }),
  ]))
})

self.addEventListener('notificationclick', (event) => {
  event.notification.close()
  const targetUrl = new URL(event.notification?.data?.url || '/my', self.location.origin).href

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
