// v4: cache v3, all media network-first (revalidated by ETag), cache only as offline fallback
const C='pias-media-v3';
const MEDIA=/\.(mp4|webm|mov|jpg|jpeg|png|webp|gif|svg|woff2?|ttf|otf)$/i;
const T_IMG=8000,T_VID=15000;
async function fresh(c,k){const h=await c.match(k);const hd={};if(h){const et=h.headers.get('etag'),lm=h.headers.get('last-modified');if(et)hd['If-None-Match']=et;else if(lm)hd['If-Modified-Since']=lm}
 const ac=new AbortController(),tm=setTimeout(()=>ac.abort(),/\.(mp4|webm|mov)$/i.test(k)?T_VID:T_IMG);
 try{const r=await fetch(k,{cache:'no-store',headers:hd,signal:ac.signal});clearTimeout(tm);
  if(r.status===304&&h)return {r:h};
  if(r.ok)return {r,put:c.put(k,r.clone()).catch(()=>{})};
  if(r.status===404||r.status===410){await c.delete(k);return {r}}
  return {r:h||r}}
 catch(x){clearTimeout(tm);return {r:h||Response.error()}}}
self.addEventListener('install',e=>{self.skipWaiting();e.waitUntil(caches.open(C).then(c=>{const f=['logo-white.png','logo.png','logo-oside.png'];for(let n=1;n<=16;n++)f.push('wx-bg/bg'+n+'.jpg');return Promise.all(f.map(p=>fresh(c,new URL(p,self.registration.scope).href).then(o=>o.put).catch(()=>{})))}))});
self.addEventListener('activate',e=>e.waitUntil(caches.keys().then(ks=>Promise.all(ks.filter(k=>k!==C).map(k=>caches.delete(k)))).then(()=>self.clients.claim())));
self.addEventListener('fetch',e=>{if(e.request.method!=='GET')return;const u=new URL(e.request.url);if(u.origin!==self.location.origin)return;
 if(MEDIA.test(u.pathname)){if(e.request.headers.has('range'))return;
  e.respondWith(caches.open(C).then(async c=>{const o=await fresh(c,u.origin+u.pathname);if(o.put)e.waitUntil(o.put);return o.r}));return}
 // manifest.json and version.txt: always network; the page keeps its own offline copy of the manifest and knows when it is stale
 if(/\/(manifest\.json|version\.txt)$/.test(u.pathname))return;
 // pages, scripts, styles: network first (revalidated), cached copy only when offline
 const k=u.origin+u.pathname;
 e.respondWith((e.request.mode==='navigate'?fetch(e.request):fetch(e.request,{cache:'no-cache'})).then(r=>{if(r.ok&&!r.redirected&&r.type==='basic'){const cp=r.clone();e.waitUntil(caches.open(C).then(c=>c.put(k,cp)).catch(()=>{}))}return r}).catch(async()=>(await (await caches.open(C)).match(k))||Response.error()))});
