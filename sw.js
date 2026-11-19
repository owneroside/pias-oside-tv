// v5 offline-first (2026-11-18). Everything the TV shows (page, logos, fonts, weather photos, manifest.json and every
// slide in it) lives in Cache Storage and is served cache-first, so the TV keeps looping the last good set when the
// internet is down or slow. The page asks for a sync about every 5 minutes. A sync reads version.txt (8 s timeout);
// when it changes it fetches manifest.json + assets.json (content hashes), downloads ONLY new or changed files into
// the blob cache (keyed by path + content hash), then swaps the active file list in one write. Files no longer listed
// are deleted only after the swap. A failed or partial download never touches the active set; the next sync resumes.
const BLOBS='pias-tv-blobs',META='pias-tv-meta',SCOPE=self.registration.scope,METAK=SCOPE+'__meta/active',BASE=new URL(SCOPE).pathname;
const SHELL=['index.html','logo-white.png','logo.png','logo-oside.png','tex.jpg','fonts/Poppins-Bold.ttf','fonts/Poppins-Medium.ttf'];
for(let n=1;n<=16;n++)SHELL.push('wx-bg/bg'+n+'.jpg');
const T_POLL=8000,T_MAN=20000,T_IMG=60000,T_VID=180000,BUDGET=600e6,CONC=3,isV=p=>/\.(mp4|webm|mov)$/i.test(p);
const NET=new Set(['version.txt','assets.json','sw.js','snow.json']);
let act,running=null;const failN={}; // a file that fails 3 syncs in a row is left out so it cannot block every other update
const bkey=(p,h)=>SCOPE+p+'?h='+h;
const pathOf=u=>{let p=u.pathname.slice(BASE.length);try{p=decodeURIComponent(p)}catch(e){}return p===''?'index.html':p};
async function getAct(){if(act!==undefined)return act;try{const r=await (await caches.open(META)).match(METAK);act=r?await r.json():null}catch(e){act=null}return act}
async function get(url,ms){const ac=new AbortController(),tm=setTimeout(()=>ac.abort(),ms);
 try{const r=await fetch(url,{cache:'no-store',signal:ac.signal});if(!r.ok){const e=new Error('http '+r.status);e.status=r.status;throw e}
  const buf=await r.arrayBuffer();return {buf,type:r.headers.get('content-type')||''}}finally{clearTimeout(tm)}}
async function sha(buf){const d=new Uint8Array(await crypto.subtle.digest('SHA-256',buf));let s='';for(let i=0;i<8;i++)s+=d[i].toString(16).padStart(2,'0');return s}
function srcs(m){const o=[];for(const it of [...(m.items||[]),...(m.dated||[])])for(const q of [it.src,it.wide,it.full])if(q&&!/^[a-z]+:/i.test(q))o.push(q.replace(/^\.?\//,'').split('?')[0]);return o}
function sync(o){if(!running)running=doSync(o||{}).catch(e=>({state:'error',err:String(e&&e.message||e)})).finally(()=>{running=null});return running}
async function doSync(o){const t0=Date.now(),a=await getAct();let v;
 try{v=new TextDecoder().decode((await get(SCOPE+'version.txt?'+Date.now(),T_POLL)).buf).trim()}catch(e){return stat(a,'offline')}
 if(!/^\d+$/.test(v))return stat(a,'bad-version');
 const same=a&&a.version===v;if(same&&a.idx&&!a.dirty&&!o.force)return stat(a,'current');
 let idx=null;try{idx=JSON.parse(new TextDecoder().decode((await get(SCOPE+'assets.json?'+Date.now(),T_POLL)).buf))}catch(e){}
 const idxOk=!!(idx&&String(idx.version)===v&&idx.files);
 if(same&&!idxOk&&!a.dirty&&!o.force)return stat(a,'current');
 let man;try{man=await get(SCOPE+'manifest.json?'+Date.now(),T_MAN);const j=JSON.parse(new TextDecoder().decode(man.buf));if(!j.items||!j.items.length)throw 0}catch(e){return stat(a,'offline')}
 const B=await caches.open(BLOBS),files={},q=[],failed=[],missing=[],bad=[];let fetched=0,fbytes=0;
 const put=async(p,buf,type)=>{const h=await sha(buf);await B.put(bkey(p,h),new Response(buf,{headers:{'content-type':type||'application/octet-stream','content-length':String(buf.byteLength)}}));return h};
 const mh=await put('manifest.json',man.buf,'application/json');files['manifest.json']={h:mh,s:man.buf.byteLength};fetched++;fbytes+=man.buf.byteLength;
 const want=[...new Set([...SHELL,...srcs(JSON.parse(new TextDecoder().decode(man.buf)))])];
 for(const p of want){const old=a&&a.files[p],ih=idxOk&&idx.files[p]&&idx.files[p][0];
  if(ih){const hit=await B.match(bkey(p,ih));if(hit){files[p]={h:ih,s:idx.files[p][1]};continue}}
  else if(old&&!old.bad&&await B.match(bkey(p,old.h))){files[p]=old;continue}
  if((failN[p]||0)>=3){missing.push(p);continue}
  q.push(p)}
 // videos last; skip any that would push the cache past the budget (those stream as before)
 q.sort((x,y)=>isV(x)-isV(y));let total=Object.values(files).reduce((s,f)=>s+(f.s||0),0);
 let k=0;const worker=async()=>{while(k<q.length){const p=q[k++];
  const est=idxOk&&idx.files[p]?idx.files[p][1]:0;if(isV(p)&&total+est>BUDGET){missing.push(p);continue}
  try{const r=await get(SCOPE+p.split('/').map(encodeURIComponent).join('/'),isV(p)?T_VID:T_IMG);const h=await put(p,r.buf,r.type);
   const ih=idxOk&&idx.files[p]&&idx.files[p][0];files[p]={h,s:r.buf.byteLength};if(ih&&ih!==h){files[p].bad=1;bad.push(p)}
   total+=r.buf.byteLength;fetched++;fbytes+=r.buf.byteLength;delete failN[p]}
  catch(e){if(e&&(e.status===404||e.status===410))missing.push(p);else{failed.push(p);failN[p]=(failN[p]||0)+1}}}};
 await Promise.all(Array.from({length:CONC},worker));
 if(failed.length||!files['index.html'])return stat(a,'partial',{failed,fetched,fbytes,ms:Date.now()-t0});
 const dirtyN=bad.length?((same&&a.dirtyN)||0)+1:0;
 const meta={version:v,idx:idxOk,dirty:bad.length>0&&dirtyN<12,dirtyN,files,bytes:Object.values(files).reduce((s,f)=>s+(f.s||0),0),at:Date.now(),missing};
 await (await caches.open(META)).put(METAK,new Response(JSON.stringify(meta),{headers:{'content-type':'application/json'}}));act=meta; // atomic swap
 const keep=new Set(Object.entries(files).map(([p,f])=>bkey(p,f.h)));let del=0;for(const r of await B.keys())if(!keep.has(r.url)){await B.delete(r);del++}
 for(const c of await caches.keys())if(c!==BLOBS&&c!==META)await caches.delete(c);
 const ch=p=>!a||!a.files[p]||a.files[p].h!==files[p].h;
 return stat(meta,'swapped',{fetched,fbytes,deleted:del,missing,bad,shellChanged:ch('index.html'),manChanged:ch('manifest.json'),ms:Date.now()-t0,from:a&&a.version})}
function stat(m,state,x){return Object.assign({t:'pias-sync',state,version:m&&m.version,files:m?Object.keys(m.files).length:0,bytes:m?m.bytes:0,idx:m?m.idx:false},x||{})}
self.addEventListener('install',()=>self.skipWaiting());
self.addEventListener('activate',e=>e.waitUntil(self.clients.claim()));
self.addEventListener('message',e=>{const d=e.data||{};if(d.t==='pias-sync')e.waitUntil(sync(d).then(r=>{if(e.source)e.source.postMessage(r)}))});
self.addEventListener('fetch',e=>{const r=e.request;if(r.method!=='GET')return;const u=new URL(r.url);if(u.origin!==self.location.origin||!u.pathname.startsWith(BASE))return;
 const p=pathOf(u);if(NET.has(p)||r.headers.has('range'))return;
 e.respondWith((async()=>{const a=await getAct(),f=a&&a.files[p];if(f){try{const c=await (await caches.open(BLOBS)).match(bkey(p,f.h));if(c)return c}catch(x){}}
  return fetch(r)})())});
