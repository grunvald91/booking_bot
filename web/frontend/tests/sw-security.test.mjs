/* Regression tests for a single ServGo origin. Uses only Node's built-in test runner. */
import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { runInNewContext } from 'node:vm'

const script = readFileSync(new URL('../public/sw.js', import.meta.url), 'utf8')
const offline = readFileSync(new URL('../public/offline.html', import.meta.url), 'utf8')
const ORIGIN = 'https://servgo.ru'

function response(body, type = 'text/plain', headers = {}) {
  const value = new Response(body, { headers: { 'Content-Type': type, ...headers } })
  // A same-origin fetch returns 'basic'; Response() constructed in Node is 'default'.
  Object.defineProperty(value, 'type', { value: 'basic' })
  return value
}

function createHarness(network = async () => response('live')) {
  const listeners = new Map()
  const entries = new Map()
  const networkRequests = []
  const opened = []
  const key = (request) => new URL(typeof request === 'string' ? request : request.url, ORIGIN).href

  function makeCache() {
    const items = new Map()
    return {
      items,
      async addAll(paths) {
        for (const path of paths) {
          items.set(key(path), path === '/offline.html'
            ? response(offline, 'text/html')
            : response('public asset'))
        }
      },
      async match(request) { return items.get(key(request))?.clone() },
      async put(request, value) { items.set(key(request), value.clone()) },
    }
  }

  const caches = {
    async open(name) {
      if (!entries.has(name)) entries.set(name, makeCache())
      return entries.get(name)
    },
    async keys() { return [...entries.keys()] },
    async delete(name) { return entries.delete(name) },
  }

  const clients = {
    claim: async () => undefined,
    matchAll: async () => [],
    openWindow: async (url) => { opened.push(url); return undefined },
  }

  const self = {
    location: { origin: ORIGIN },
    addEventListener(name, handler) { listeners.set(name, handler) },
    skipWaiting: async () => undefined,
    clients,
    registration: { showNotification: async () => undefined },
  }

  const fetch = async (request) => {
    networkRequests.push(request)
    return network(request)
  }

  runInNewContext(script, { self, caches, fetch, URL, Response })

  function dispatch(name, data = {}) {
    const waits = []
    const event = {
      ...data,
      waitUntil(promise) { waits.push(promise) },
      respondWith(promise) { this.response = Promise.resolve(promise) },
    }
    const handler = listeners.get(name)
    assert.ok(handler, 'no ' + name + ' handler')
    handler(event)
    return { event, done: Promise.all(waits) }
  }

  async function request(path, { method = 'GET', mode = 'navigate', cache = 'default' } = {}) {
    const request = { url: new URL(path, ORIGIN).href, method, mode, cache }
    const fired = dispatch('fetch', { request })
    return fired.event.response ? fired.event.response : null
  }

  return { dispatch, request, caches, entries, networkRequests, self, opened }
}

test('upgrading v2 clears its cached private HTML but leaves unrelated caches untouched', async () => {
  const h = createHarness()
  const legacy = await h.caches.open('servgo-pwa-v2')
  await legacy.put('/index.html', response('<strong>Private account</strong>', 'text/html'))
  await h.caches.open('unrelated-app-cache')

  await h.dispatch('install').done
  await h.dispatch('activate').done

  assert.deepEqual((await h.caches.keys()).sort(), ['servgo-pwa-v4', 'unrelated-app-cache'])
  const fresh = await h.caches.open('servgo-pwa-v4')
  assert.ok((await fresh.match('/offline.html'))?.ok)
  assert.ok(await fresh.match('/index.html'), 'static PWA shell must exist for cold offline launch')
  assert.equal(await fresh.match('/'), undefined)
})

test('online navigation is network-first, including private Mail and Growth pages', async () => {
  const h = createHarness(async () => response('<secret>PRIVATE</secret>', 'text/html', {
    'Cache-Control': 'private, no-store',
  }))
  await h.dispatch('install').done

  for (const path of ['/', '/admin', '/my', '/workspace/mail/inbox',
    '/workspace/growth/studio', '/studio/team', '/mail']) {
    const served = await h.request(path)
    assert.match(await served.text(), /PRIVATE/)
  }
  const fresh = await h.caches.open('servgo-pwa-v4')
  assert.equal(fresh.items.size, 5, 'static shell and public assets only, never signed-in HTML')
  assert.ok(await fresh.match('/index.html'))
  assert.equal(h.networkRequests.length, 8, 'seven navigations and offline asset manifest request')
})

test('offline navigation shows a neutral page, not a cached authenticated SPA shell', async () => {
  const h = createHarness(async () => { throw Error('offline') })
  await h.dispatch('install').done
  const served = await h.request('/workspace/mail/inbox')
  const text = await served.text()
  assert.match(text, /Нет соединения с ServGo/)
  assert.doesNotMatch(text, /Private account|<secret>|Authorization/)
})

test('offline booking screens use the static shell, not saved personal HTML', async () => {
  const h = createHarness(async () => { throw Error('offline') })
  await h.dispatch('install').done
  for (const url of ['/admin/schedule', '/my', '/master', '/account', '/']) {
    const page = await h.request(url)
    assert.equal(await page.text(), 'public asset')
  }
  for (const url of ['/studio/team', '/workspace/growth', '/workspace/mail/inbox', '/mail']) {
    const page = await h.request(url)
    assert.match(await page.text(), /Нет соединения с ServGo/)
  }
  const cache = await h.caches.open('servgo-pwa-v4')
  assert.equal(await cache.match('/admin/schedule'), undefined)
  assert.equal(await cache.match('/my'), undefined)
})

test('no interception for API requests, private resources or third-party URLs', async () => {
  const h = createHarness()
  const paths = ['/api/owner-mail/inbox', '/workspace/mail/attachments/private.png',
    '/studio/assets/private.css', '/admin/customer/photo.png', 'https://other.example/asset.js']
  for (const path of paths) {
    assert.equal(await h.request(path, { mode: 'cors' }), null)
  }
  assert.equal(await h.request('/api/owner-mail/inbox', { method: 'POST' }), null)
  assert.equal(h.networkRequests.length, 0)
})

test('only public static assets are runtime-cached; private or HTML responses never are', async () => {
  const h = createHarness(async (req) => {
    if (req.url.endsWith('/assets/index-abcdef123456.js')) {
      return response('compiled code', 'application/javascript')
    }
    if (req.url.endsWith('/assets/redirect-abcdef123456.js')) {
      return response('<html>Login</html>', 'text/html')
    }
    return response('sensitive', 'text/plain', { 'Cache-Control': 'private' })
  })
  await h.dispatch('install').done

  assert.equal(await (await h.request('/assets/index-abcdef123456.js', { mode: 'cors' })).text(), 'compiled code')
  assert.equal(await (await h.request('/assets/index-abcdef123456.js', { mode: 'cors' })).text(), 'compiled code')
  assert.equal(h.networkRequests.length, 2, 'one manifest fetch and one uncached asset fetch')

  await h.request('/assets/redirect-abcdef123456.js', { mode: 'cors' })
  await h.request('/assets/private-abcdef123456.js', { mode: 'cors' })
  const cache = await h.caches.open('servgo-pwa-v4')
  assert.ok(await cache.match('/assets/index-abcdef123456.js'))
  assert.equal(await cache.match('/assets/redirect-abcdef123456.js'), undefined)
  assert.equal(await cache.match('/assets/private-abcdef123456.js'), undefined)
})

test('push notification target cannot navigate the installed app to an untrusted origin', async () => {
  const h = createHarness()
  const notification = { data: { url: 'https://external.example/phish' }, close() {} }
  await h.dispatch('notificationclick', { notification }).done
  assert.deepEqual(h.opened, [ORIGIN + '/my'])
})
