// v3 cache v2, slides network-first
const C='pias-media-v2';
self.addEventListener('install',e=>{self.skipWaiting();e.waitUntil(caches.open(C).then(c=>{const a=['logo-white.png','logo.png'].map(f=>{const k=new URL(f,self.registration.scope).href;return fetch(k,{cache:'no-cache'}).then(r=>r.ok&&c.put(k,r)).catch(()=>{})});const b=[1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16].map(n=>{const k=new URL('wx-bg/bg'+n+'.jpg',self.registration.scope).href;return c.match(k).then(h=>h||fetch(k).then(r=>r.ok&&c.put(k,r))).catch(()=>{})});return Promise.all(a.concat(b))}))});
self.addEventListener('activate',e=>e.waitUntil(caches.keys().then(ks=>Promise.all(ks.filter(k=>k!==C).map(k=>caches.delete(k)))).then(()=>self.clients.claim())));
self.addEventListener('fetch',e=>{const u=new URL(e.request.url);if(e.request.method!=='GET')return;
 const media=/\.(mp4|jpg|jpeg|png|webp)$/i.test(u.pathname);
 if(media&&/\/slides\//.test(u.pathname)&&!e.request.headers.has('range')){e.respondWith(caches.open(C).then(async c=>{const k=u.origin+u.pathname;try{const r=await fetch(k,{cache:'no-cache'});if(r.ok){await c.put(k,r.clone());return r}}catch(x){}return (await c.match(k))||fetch(k)}));return}
 if(media&&!e.request.headers.has('range')){e.respondWith(caches.open(C).then(async c=>{const k=u.origin+u.pathname;const h=await c.match(k);if(h&&h.ok)return h;try{const r=await fetch(k,{cache:'no-cache'});if(r.ok)await c.put(k,r.clone());return r}catch(x){return h||Response.error()}}));return}
 if(!media){e.respondWith(fetch(e.request).then(async r=>{if(r.ok&&u.origin===location.origin){const c=await caches.open(C);c.put(u.origin+u.pathname,r.clone())}return r}).catch(async()=>(await caches.open(C)).match(u.origin+u.pathname)||Response.error()))}});
