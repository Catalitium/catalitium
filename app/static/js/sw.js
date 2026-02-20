/* Catalitium Service Worker — cache-first for static, network-first for pages */
var CACHE = 'catalitium-v1';
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
  /* Cache-first for static assets */
  if(url.pathname.startsWith('/static/')){
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
    return;
  }
  /* Network-first for API and pages — fall back to cache on failure */
  if(e.request.method !== 'GET') return;
  e.respondWith(
    fetch(e.request).then(function(res){
      if(res && res.status === 200 && url.origin === self.location.origin){
        var clone = res.clone();
        caches.open(CACHE).then(function(c){ c.put(e.request, clone); });
      }
      return res;
    }).catch(function(){
      return caches.match(e.request);
    })
  );
});
