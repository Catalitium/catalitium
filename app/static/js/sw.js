/* Catalitium Service Worker — resilient static caching */
var CACHE = 'catalitium-v4';
var STATIC = [
  '/static/css/styles.css',
  '/static/js/main.js',
  '/static/img/logo.png',
  '/static/manifest.json'
];

self.addEventListener('install', function(e){
  e.waitUntil(
    caches.open(CACHE).then(function(c){ return c.addAll(STATIC); })
  );
  self.skipWaiting();
});

self.addEventListener('activate', function(e){
  e.waitUntil(
    caches.keys().then(function(keys){
      return Promise.all(
        keys.filter(function(k){ return k !== CACHE; }).map(function(k){ return caches.delete(k); })
      );
    })
  );
  self.clients.claim();
});

self.addEventListener('fetch', function(e){
  var url = new URL(e.request.url);
  if (e.request.method !== 'GET') return;
  /* Static assets only. Keep HTML/API network-driven. */
  if (!url.pathname.startsWith('/static/')) return;
  var networkFirst = (
    url.pathname.endsWith('/css/styles.css') ||
    url.pathname.endsWith('/js/main.js') ||
    url.pathname.endsWith('/js/ai_summary.js')
  );
  if (networkFirst) {
    e.respondWith(
      fetch(e.request).then(function(res){
        if(res && res.status === 200){
          var clone = res.clone();
          caches.open(CACHE).then(function(c){ c.put(e.request, clone); });
        }
        return res;
      }).catch(function(){
        return caches.match(e.request);
      })
    );
    return;
  }
  e.respondWith(
    caches.match(e.request).then(function(cached){
      if(cached) return cached;
      return fetch(e.request).then(function(res){
        if(res && res.status === 200){
          var clone = res.clone();
          caches.open(CACHE).then(function(c){ c.put(e.request, clone); });
        }
        return res;
      });
    })
  );
});
