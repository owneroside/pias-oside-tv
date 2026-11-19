#!/usr/bin/env python3
"""Writes assets.json: {version, manifest, files: {path: [sha256[:16], bytes]}} for everything the TV can cache.
The service worker uses it to download only new or changed files. Run from the repo root after any media change
(the 'assets' GitHub Action also runs it on every push to main)."""
import hashlib, json, os
R = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
def h(p):
    b = open(os.path.join(R, p), 'rb').read()
    return [hashlib.sha256(b).hexdigest()[:16], len(b)]
files = {}
for top in ['index.html', 'manifest.json', 'logo-white.png', 'logo.png', 'logo-oside.png', 'tex.jpg']:
    if os.path.exists(os.path.join(R, top)): files[top] = h(top)
for d in ['slides', 'clips', 'wx-bg', 'fonts']:
    for root, _, fs in os.walk(os.path.join(R, d)):
        for f in fs:
            p = os.path.relpath(os.path.join(root, f), R).replace(os.sep, '/')
            files[p] = h(p)
out = {'version': open(os.path.join(R, 'version.txt')).read().strip(), 'manifest': files['manifest.json'][0],
       'files': dict(sorted(files.items()))}
open(os.path.join(R, 'assets.json'), 'w').write(json.dumps(out, separators=(',', ':')) + '\n')
print(len(files), 'files ->', out['version'])
