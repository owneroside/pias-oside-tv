const C='pias-media-v1';
self.addEventListener('install',e=>{self.skipWaiting();e.waitUntil(caches.open(C).then(c=>Promise.all([1,2,3,4].map(n=>{const k=new URL('wx-bg/bg'+n+'.jpg',self.registration.scope).href;return c.match(k).then(h=>h||fetch(k).then(r=>r.ok&&c.put(k,r))).catch(()=>{})}))))});
self.addEventListener('activate',e=>e.waitUntil(self.clients.claim()));
self.addEventListener('fetch',e=>{const u=new URL(e.request.url);if(e.request.method!=='GET')return;
 const media=/\.(mp4|jpg|jpeg|png|webp)$/i.test(u.pathname);
 if(media&&!e.request.headers.has('range')){e.respondWith(caches.open(C).then(async c=>{const k=u.origin+u.pathname;const h=await c.match(k);if(h)return h;const r=await fetch(k);if(r.ok)await c.put(k,r.clone());return r}));return}
 if(!media){e.respondWith(fetch(e.request).then(async r=>{if(r.ok&&u.origin===location.origin){const c=await caches.open(C);c.put(u.origin+u.pathname,r.clone())}return r}).catch(async()=>(await caches.open(C)).match(u.origin+u.pathname)||Response.error()))}});
