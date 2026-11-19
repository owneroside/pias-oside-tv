#!/usr/bin/env python3
"""Build snow.json for the live register-TV snow report slide.

Sources (fetched here, not in the browser, so CORS is not required):
  - Alterra MtnPowder feed (https://mtnpowder.com/feed/): Bear Mountain,
    Snow Summit, Snow Valley, Mammoth Mountain — official open/closed,
    lift and run counts, 24h/48h snow, base depth, and station temp.
  - Mountain High official snow report page (mthigh.com) — status, lifts,
    runs, base/top depth, 7-day new snow, official temp, opening date.
  - Open-Meteo (https://api.open-meteo.com) — current temperature at the
    resort coordinates, used only when the official station temp is missing
    or disagrees with the model by more than 15°F (SoCal stations currently
    report mid-60s while the written report and Open-Meteo are mid-30s).

Does not invent numbers. A field is omitted (null) when the source does not
provide it. 0 is a real value (no snow, no lifts) and is kept.

Writes snow.json in the repo root. Exit 0 even when a source fails, as long
as a usable file (new or previous) remains.
"""
from __future__ import annotations

import json, os, re, sys, html, datetime
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'snow.json')
UA = 'PIAS-Oceanside-TV/1.0 (snow report; https://owneroside.github.io/pias-oside-tv/)'
TZ = datetime.timezone(datetime.timedelta(hours=-8))  # labels are PT; stamps stored as ISO with offset

RESORTS = [
    {
        'id': 'bear',
        'name': 'Bear Mountain',
        'region': 'Big Bear Mountain Resort',
        'feed_name': 'Bear Mountain',
        'lat': 34.2292, 'lon': -116.8603,
    },
    {
        'id': 'summit',
        'name': 'Snow Summit',
        'region': 'Big Bear Mountain Resort',
        'feed_name': 'Snow Summit',
        'lat': 34.2285, 'lon': -116.8912,
    },
    {
        'id': 'valley',
        'name': 'Snow Valley',
        'region': 'Big Bear Mountain Resort',
        'feed_name': 'Snow Valley',
        'lat': 34.2247, 'lon': -117.0413,
    },
    {
        'id': 'mthigh',
        'name': 'Mountain High',
        'region': 'Wrightwood',
        'feed_name': None,
        'lat': 34.3770, 'lon': -117.6910,
    },
    {
        'id': 'mammoth',
        'name': 'Mammoth Mountain',
        'region': 'Eastern Sierra',
        'feed_name': 'Mammoth Mountain',
        'lat': 37.6513, 'lon': -119.0393,
    },
]

MTNPOWDER = 'https://mtnpowder.com/feed/'
MHIGH_URL = 'https://www.mthigh.com/site/trails-and-conditions/conditions/snow-and-weather-report/@@snow-and-weather-report'
OPEN_METEO = (
    'https://api.open-meteo.com/v1/forecast'
    '?latitude={lats}&longitude={lons}'
    '&current=temperature_2m'
    '&temperature_unit=fahrenheit'
    '&timezone=America%2FLos_Angeles'
    '&forecast_days=1'
)


def now_pt():
    # Use zoneinfo when available so PDT/PST is correct
    try:
        from zoneinfo import ZoneInfo
        return datetime.datetime.now(ZoneInfo('America/Los_Angeles'))
    except Exception:
        return datetime.datetime.now(TZ)


def iso(dt):
    if dt is None:
        return None
    if isinstance(dt, str):
        return dt
    return dt.isoformat()


def label_pt(dt):
    """'3:15 PM PT' from a datetime (aware) or parseable string."""
    if dt is None:
        return None
    if isinstance(dt, str):
        dt = parse_dt(dt)
        if dt is None:
            return None
    try:
        from zoneinfo import ZoneInfo
        dt = dt.astimezone(ZoneInfo('America/Los_Angeles'))
    except Exception:
        pass
    h = dt.strftime('%I:%M %p').lstrip('0')
    return f'{h} PT'


def parse_dt(s):
    if not s or s == '--':
        return None
    s = s.strip()
    for fmt in (
        '%Y-%m-%dT%H:%M:%S%z',
        '%Y-%m-%dT%H:%M:%S',
        '%Y-%m-%dT%H:%M:%z',
    ):
        try:
            t = s
            if fmt.endswith('%z') and re.search(r'[+-]\d{4}$', t):
                t = t[:-5] + t[-5:-2] + ':' + t[-2:] if t[-5] in '+-' and ':' not in t[-5:] else t
                # 2026-11-19T12:56:20-0800
                if re.search(r'[+-]\d{4}$', s):
                    s2 = s[:-2] + ':' + s[-2:]
                    return datetime.datetime.fromisoformat(s2)
            return datetime.datetime.strptime(s, fmt)
        except Exception:
            continue
    try:
        if re.search(r'[+-]\d{4}$', s):
            s = s[:-2] + ':' + s[-2:]
        return datetime.datetime.fromisoformat(s)
    except Exception:
        return None


def fetch(url, timeout=45, binary=False):
    req = Request(url, headers={'User-Agent': UA, 'Accept': '*/*'})
    with urlopen(req, timeout=timeout) as r:
        data = r.read()
    return data if binary else data.decode('utf-8', 'replace')


def to_num(v):
    """Return int/float or None. 0 is kept. '--' / '' / missing → None."""
    if v is None:
        return None
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return int(v) if float(v) == int(v) else float(v)
    s = str(v).strip().replace(',', '')
    if s in ('', '--', '—', '-', 'N/A', 'n/a', 'null'):
        return None
    s = s.replace('"', '').replace('″', '').replace('°', '').replace('F', '').strip()
    try:
        f = float(s)
        return int(f) if f == int(f) else f
    except ValueError:
        return None


def strip_html(s):
    s = re.sub(r'<[^>]+>', ' ', s or '')
    return re.sub(r'\s+', ' ', html.unescape(s)).strip()


def opening_from_text(text):
    if not text:
        return None
    if re.search(r'opening day.{0,100}not yet been determined', text, re.I):
        return 'TBD'
    m = re.search(
        r'official opening date is set for\s+(?:[A-Z]+,\s+)?([A-Z]+)\s+(\d{1,2})(?:ST|ND|RD|TH)?',
        text, re.I)
    if m:
        mon = m.group(1).title()[:3]
        return f'{mon} {int(m.group(2))}'
    m = re.search(r'opens?\s+on\s+([A-Z][a-z]+)\s+(\d{1,2})(?:st|nd|rd|th)?', text, re.I)
    if m:
        return f'{m.group(1)[:3]} {int(m.group(2))}'
    return None


def status_of(official_status, lifts_open, runs_open, opens):
    """Map official status + lift/run counts to open / limited / closed.

    MtnPowder sometimes flags a SoCal resort as "Open" before opening day
    (0 lifts, report says opening day has not been determined). Treat that
    as closed and surface the opening date. A resort with lifts or runs
    spinning is open, or limited if the official flag is Closed.
    """
    lo = lifts_open or 0
    ro = runs_open or 0
    spinning = lo > 0 or ro > 0
    flag = (official_status or '').strip().lower()
    if spinning and flag == 'closed':
        return 'limited'
    if spinning:
        return 'open'
    # No lifts/runs: if they haven't announced opening (or have a future date), closed
    if opens:
        return 'closed'
    if flag == 'open':
        # Officially "open" but nothing spinning (weather hold, night, etc.)
        return 'closed' if official_status and lo == 0 and ro == 0 else 'open'
    if flag in ('closed', 'temporarily closed', 'on hold'):
        return 'closed'
    if flag:
        return 'closed'
    return 'closed'


def load_prev():
    try:
        with open(OUT, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {'resorts': []}


def prev_by_id(prev, rid):
    for r in prev.get('resorts') or []:
        if r.get('id') == rid:
            return r
    return None


def fetch_mtnpowder():
    raw = fetch(MTNPOWDER, timeout=60)
    data = json.loads(raw)
    by = {r.get('Name'): r for r in data.get('Resorts') or []}
    return by


def parse_feed_resort(spec, raw):
    sr = raw.get('SnowReport') or {}
    ba = sr.get('BaseArea') or {}
    cc = (raw.get('CurrentConditions') or {}).get('Base') or {}
    report = strip_html(sr.get('Report') or '')
    opens = opening_from_text(report)
    lifts_open = to_num(sr.get('TotalOpenLifts'))
    lifts_total = to_num(sr.get('TotalLifts'))
    runs_open = to_num(sr.get('TotalOpenTrails'))
    runs_total = to_num(sr.get('TotalTrails'))
    official = raw.get('OperatingStatus')
    status = status_of(official, lifts_open, runs_open, opens)
    # Once a resort is actually spinning, don't show a stale "TBD" open date
    if status in ('open', 'limited'):
        opens = None
    src_up = parse_dt(sr.get('LastUpdate') or raw.get('LastUpdate'))
    official_temp = to_num(cc.get('TemperatureF'))
    return {
        'id': spec['id'],
        'name': spec['name'],
        'region': spec['region'],
        'status': status,
        'officialStatus': official,
        'opens': opens,
        'liftsOpen': lifts_open,
        'liftsTotal': lifts_total,
        'runsOpen': runs_open,
        'runsTotal': runs_total,
        'snow24h': to_num(ba.get('Last24HoursIn')),
        'snow48h': to_num(ba.get('Last48HoursIn')),
        'snow7d': to_num(ba.get('Last7DaysIn')),
        'baseIn': to_num(ba.get('BaseIn')),
        'baseRange': None if sr.get('SnowBaseRangeIn') in (None, '--', '') else str(sr.get('SnowBaseRangeIn')),
        'tempF': official_temp,
        'tempSource': 'resort' if official_temp is not None else None,
        'conditions': None if sr.get('BaseConditions') in (None, '--', '') else sr.get('BaseConditions'),
        'source': 'mtnpowder',
        'sourceUpdated': iso(src_up) if src_up else (sr.get('LastUpdate') or raw.get('LastUpdate')),
    }


def parse_mthigh(html_text):
    rows = dict(re.findall(
        r'class="mh-Conditions-label"[^>]*>\s*([^<]+?)\s*</span>\s*'
        r'<span class="mh-Conditions-value"[^>]*>\s*([^<]+?)\s*</span>',
        html_text))
    def val(*labels):
        for lab, v in rows.items():
            key = html.unescape(lab).strip().rstrip(':').lower()
            for want in labels:
                if key == want.lower():
                    return html.unescape(v).strip()
        return None

    text = strip_html(html_text)
    opens = opening_from_text(text)
    lifts_open = to_num(val('Open Lifts'))
    runs_open = to_num(val('Open Trails'))
    west = (val('WEST') or '').lower()
    east = (val('EAST') or '').lower()
    yeti = (val('YETI') or '').lower()
    area_open = any(s == 'open' for s in (west, east, yeti))
    official = 'Open' if area_open or (lifts_open or 0) > 0 else 'Closed'
    status = status_of(official, lifts_open, runs_open, opens)
    if status in ('open', 'limited'):
        opens = None

    updated = None
    m = re.search(r'Updated:\s*([^<]+)', html_text)
    if m:
        updated = html.unescape(m.group(1)).strip()
        # "Tuesday, November 17, 2026 08:40 PM"
        updated_iso = None
        for fmt in ('%A, %B %d, %Y %I:%M %p', '%B %d, %Y %I:%M %p'):
            try:
                from zoneinfo import ZoneInfo
                dt = datetime.datetime.strptime(updated.strip(), fmt).replace(
                    tzinfo=ZoneInfo('America/Los_Angeles'))
                updated_iso = iso(dt)
                break
            except Exception:
                continue
    else:
        updated_iso = None

    temp = to_num(val('Current Temp'))
    return {
        'id': 'mthigh',
        'name': 'Mountain High',
        'region': 'Wrightwood',
        'status': status,
        'officialStatus': official,
        'opens': opens,
        'liftsOpen': lifts_open,
        'liftsTotal': None,  # page does not publish a total
        'runsOpen': runs_open,
        'runsTotal': None,
        'snow24h': None,  # page only publishes 7-day new snow
        'snow48h': None,
        'snow7d': to_num(val('New Snow (7 Days)')),
        'baseIn': to_num(val('Base Depth')),
        'baseRange': None,
        'tempF': temp,
        'tempSource': 'resort' if temp is not None else None,
        'conditions': None,
        'source': 'mthigh',
        'sourceUpdated': updated_iso or updated,
        'areas': {
            'west': val('WEST'),
            'east': val('EAST'),
            'yeti': val('YETI'),
        },
    }


def fetch_open_meteo(specs):
    lats = ','.join(str(s['lat']) for s in specs)
    lons = ','.join(str(s['lon']) for s in specs)
    url = OPEN_METEO.format(lats=lats, lons=lons)
    data = json.loads(fetch(url, timeout=30))
    items = data if isinstance(data, list) else [data]
    out = {}
    for spec, item in zip(specs, items):
        cur = item.get('current') or {}
        t = to_num(cur.get('temperature_2m'))
        if t is not None:
            out[spec['id']] = t
    return out


def _deg(v):
    if v is None:
        return None
    return int(round(float(v)))

def apply_temps(resort, om_temp):
    official = _deg(resort.get('tempF'))
    om_temp = _deg(om_temp)
    if official is None and om_temp is not None:
        resort['tempF'] = om_temp
        resort['tempSource'] = 'open-meteo'
        return
    if official is not None and om_temp is not None and abs(official - om_temp) > 15:
        # Official station is far from the model (and often from the written
        # report). Keep the official value in the file but display the model.
        resort['tempOfficialF'] = official
        resort['tempF'] = om_temp
        resort['tempSource'] = 'open-meteo'
        return
    if official is not None:
        resort['tempF'] = official
        resort['tempSource'] = 'resort'


def label_status(st):
    return {'open': 'OPEN', 'limited': 'LIMITED', 'closed': 'CLOSED'}.get(st, st.upper() if st else '')


def merge_missing(new, old):
    """If a fetch failed for this resort, keep last-known values."""
    if new is not None:
        return new
    if old is None:
        return None
    old = dict(old)
    old['stale'] = True
    return old


def canonical(resorts):
    """Comparable snapshot, ignoring fetch timestamps."""
    keys = (
        'id', 'status', 'opens', 'liftsOpen', 'liftsTotal', 'runsOpen', 'runsTotal',
        'snow24h', 'snow48h', 'snow7d', 'baseIn', 'tempF', 'tempSource', 'conditions'
    )
    out = []
    for r in resorts:
        out.append({k: r.get(k) for k in keys})
    return out


def main():
    prev = load_prev()
    errors = []
    feed = {}
    try:
        feed = fetch_mtnpowder()
    except Exception as e:
        errors.append(f'mtnpowder: {e}')
        print('WARN mtnpowder failed:', e, file=sys.stderr)

    mh = None
    try:
        mh = parse_mthigh(fetch(MHIGH_URL, timeout=30))
    except Exception as e:
        errors.append(f'mthigh: {e}')
        print('WARN mthigh failed:', e, file=sys.stderr)

    om = {}
    try:
        om = fetch_open_meteo(RESORTS)
    except Exception as e:
        errors.append(f'open-meteo: {e}')
        print('WARN open-meteo failed:', e, file=sys.stderr)

    resorts = []
    for spec in RESORTS:
        parsed = None
        if spec['id'] == 'mthigh':
            parsed = mh
        elif spec['feed_name'] and spec['feed_name'] in feed:
            parsed = parse_feed_resort(spec, feed[spec['feed_name']])
        elif spec['feed_name']:
            errors.append(f'mtnpowder: missing {spec["feed_name"]}')
        if parsed:
            apply_temps(parsed, om.get(spec['id']))
            parsed['statusLabel'] = label_status(parsed['status'])
        else:
            parsed = merge_missing(None, prev_by_id(prev, spec['id']))
            if parsed:
                print(f'WARN using last-known values for {spec["id"]}', file=sys.stderr)
        if parsed:
            resorts.append(parsed)

    if not resorts:
        print('ERROR: no resort data and no previous snow.json', file=sys.stderr)
        return 1

    fetched = now_pt()
    # Prefer the newest source update for the on-screen stamp; fall back to fetch time
    source_times = [parse_dt(r.get('sourceUpdated')) for r in resorts]
    source_times = [t for t in source_times if t]
    newest_src = max(source_times) if source_times else fetched

    doc = {
        'updated': iso(fetched),
        'updatedLabel': label_pt(fetched),
        'sourceUpdated': iso(newest_src),
        'sourceUpdatedLabel': label_pt(newest_src),
        'resorts': resorts,
        'errors': errors,
    }

    # Avoid a commit every 30 min when nothing changed: if stdin flag?
    # The Action compares canonical data. Always write the file (updated time
    # changes) — the workflow decides whether to commit.
    changed = canonical(resorts) != canonical(prev.get('resorts') or [])
    if not changed and prev.get('resorts'):
        print(f'unchanged {OUT} ({len(resorts)} resorts, {len(errors)} source warnings)')
        for r in resorts:
            print(
                f"  {r.get('name')}: {r.get('statusLabel')} "
                f"lifts={r.get('liftsOpen')}/{r.get('liftsTotal')} "
                f"runs={r.get('runsOpen')}/{r.get('runsTotal')} "
                f"24h={r.get('snow24h')} 48h={r.get('snow48h')} 7d={r.get('snow7d')} "
                f"base={r.get('baseIn')} temp={r.get('tempF')}({r.get('tempSource')}) "
                f"opens={r.get('opens')}"
            )
        print('DATA_UNCHANGED')
        return 0
    tmp = OUT + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(doc, f, indent=2, ensure_ascii=False)
        f.write('\n')
    os.replace(tmp, OUT)
    print(f'wrote {OUT} ({len(resorts)} resorts, {len(errors)} source warnings)')
    for r in resorts:
        print(
            f"  {r.get('name')}: {r.get('statusLabel')} "
            f"lifts={r.get('liftsOpen')}/{r.get('liftsTotal')} "
            f"runs={r.get('runsOpen')}/{r.get('runsTotal')} "
            f"24h={r.get('snow24h')} 48h={r.get('snow48h')} 7d={r.get('snow7d')} "
            f"base={r.get('baseIn')} temp={r.get('tempF')}({r.get('tempSource')}) "
            f"opens={r.get('opens')}"
        )
    print('DATA_CHANGED')
    return 0


if __name__ == '__main__':
    sys.exit(main())
