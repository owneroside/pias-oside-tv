# PIAS Oceanside register TV slideshow
Static page for Anthias (Web Page asset). Edit `manifest.json` only:
- image: {"type":"image","src":"slides/NN-name.jpg","seconds":10} (1080x1080 finished post graphic)
- video: {"type":"video","src":"clips/name.mp4","maxSeconds":12} (muted; return box hidden)
The page re-reads manifest.json every loop and reloads every 6h, so the Pi never needs changes.

Offline-first (sw.js v5): in Chromium (Anthias) the service worker keeps the page, logos, fonts, weather photos,
manifest.json and every slide in Cache Storage and serves them cache-first. About every 5 min it reads version.txt
(8 s timeout). When the number changes it downloads only new or changed files (by content hash from assets.json),
swaps the whole set in one step, then deletes files no longer listed. If the internet is down it keeps looping the
last good set. Workflow is unchanged: edit manifest/slides, merge, bump version.txt. The `assets` Action refreshes
assets.json on every push to main (or run `python3 tools/build-assets.py`). Status: bottom-left `m<min> v<ver> c<MB>`;
console logs `[pias-tv] sync ...`. Browsers without service workers (Samsung TV browser) behave as before.
Clips: Pexels (free license) ids 6573535 golf, 31955074 basketball, 6859162 skate, 12628499 surf.

Live snow report (`#snow`): two slides (SoCal and Mammoth). `snow.json` is built by `tools/fetch-snow.py` (GitHub Action every 30 minutes; no version.txt bump) from official sources: Alterra MtnPowder (Bear Mountain, Snow Summit, Snow Valley, Mammoth), the Mountain High snow-report page, and the Mt. Baldy tickets API. Fields include open/closed, lifts and runs open of total, 24h/48h snow, base and summit depth, temp, hours when published, and 3-day expected snow. Missing official values stay null (never invented). The player fetches `snow.json` network-first with a localStorage fallback. See `SNOW-FIELDS-FOR-DESIGN.md` for the field list Design should lay out. The current SoCal card in `index.html` still shows only new snow (if > 0) and temperature; Design owns any visual change. Do not put these slides live until Dustin has seen before/after at 1920×1080.
