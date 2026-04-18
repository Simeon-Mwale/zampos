const CACHE_NAME = 'zampos-v1'
const OFFLINE_URLS = ['/', '/dashboard']

self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => cache.addAll(OFFLINE_URLS))
  )
  self.skipWaiting()
})

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))
    )
  )
  self.clients.claim()
})

self.addEventListener('fetch', event => {
  const url = event.request.url

  // ── Never cache these ──────────────────────────────────────────────────────
  if (event.request.method !== 'GET') return        // POST/PUT/DELETE
  if (url.includes('onrender.com')) return          // Render backend API
  if (url.includes('localhost:8000')) return        // Local backend
  if (url.includes('railway.app')) return           // Railway (old)
  if (url.startsWith('chrome-extension')) return    // Browser extensions
  if (url.includes('/api/')) return                 // Any API route

  // ── Cache-first for static assets ─────────────────────────────────────────
  event.respondWith(
    fetch(event.request)
      .then(response => {
        // Only cache valid same-origin responses
        if (
          response.ok &&
          response.type === 'basic' &&
          url.startsWith(self.location.origin)
        ) {
          const clone = response.clone()
          caches.open(CACHE_NAME).then(cache => {
            try {
              cache.put(event.request, clone)
            } catch (e) {
              // Silently ignore cache errors (e.g. chrome-extension scheme)
            }
          })
        }
        return response
      })
      .catch(() => caches.match(event.request))
  )
})