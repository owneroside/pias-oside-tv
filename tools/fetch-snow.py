#!/usr/bin/env python3
"""Build snow.json for the live register-TV snow report slide.

Sources (fetched here, not in the browser, so CORS is not required):
  - Alterra MtnPowder feed (https://mtnpowder.com/feed/): Bear Mountain,
    Snow Summit, Snow Valley, Mammoth Mountain — official open/closed,
    lift and run counts, 24h/48h snow, base and summit depth, and station
    temp. This is the official Big Bear / Mammoth feed; OnTheSnow is not
    used (it was wrong on 2026-11-27 vs official counts).
  - Mountain High official snow report page (mthigh.com) — status, lifts
    open, runs open, groomed trails, base/top depth, official 24h/48h/7-day
    new snow, official temp, area hours, opening date. Lift total from the
    official Mountain Stats page ("Lifts: 12 Total", fallback 12). Run total
    from named runs on the official interactive trail map (fallback 49).
  - Mt. Baldy official tickets API (tickets.mtbaldyresort.com/api/status
    and /api/mountain/weather) — chair status, run status, hours, live
    station temp. Lift total 4 and run total 26 from the official trail
    map / mountain stats page. Base depth and 24h snow are recorded only
    when the resort publishes them (they may be null).
  - Open-Meteo (https://api.open-meteo.com) — current temperature at the
    resort coordinates, used when the official station temp is missing or
    disagrees with the model by more than 15°F; 24h/48h snowfall (cm,
    converted to inches) only when a resort does not publish those fields;
    and a 3-day expected snowfall forecast (daily snowfall_sum, today plus
    the next 2 days) plus a short forecast label from the weather code.

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
    {
        'id': 'baldy',
        'name': 'Mt. Baldy',
        'region': 'Angeles National Forest',
        'feed_name': None,
        'lat': 34.2791, 'lon': -117.6576,
    },
]

MTNPOWDER = 'https://mtnpowder.com/feed/'
MHIGH_URL = 'https://www.mthigh.com/site/trails-and-conditions/conditions/snow-and-weather-report/@@snow-and-weather-report'
OPEN_METEO = (
    'https://api.open-meteo.com/v1/forecast'
    '?latitude={lats}&longitude={lons}'
    '&current=temperature_2m,weather_code'
    '&hourly=snowfall'
    '&daily=snowfall_sum,weather_code'
    '&past_days=2'
    '&forecast_days=4'
    '&temperature_unit=fahrenheit'
    '&timezone=America%2FLos_Angeles'
)
MHIGH_STATS_URL = 'https://www.mthigh.com/site/trails-and-conditions/other/mountain-stats.html'
MHIGH_MAP_URL = 'https://www.mthigh.com/site/mountain/mountain-info/interactive-trailmap.html'
# Fallbacks from official pages if a fetch fails (verified Nov 19, 2026)
MH_LIFTS_FALLBACK = 12  # "Lifts: 12 Total" on official Mountain Stats
MH_RUNS_FALLBACK = 49   # named runs on the official interactive trail map
BALDY_STATUS_URL = 'https://tickets.mtbaldyresort.com/api/status'
BALDY_WEATHER_URL = 'https://tickets.mtbaldyresort.com/api/mountain/weather'
# Official trail map / mountain stats: "Four chairs, 26 runs" (verified Nov 27, 2026)
BALDY_LIFTS_FALLBACK = 4
BALDY_RUNS_FALLBACK = 26


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
    if s.endswith('Z'):
        s = s[:-1] + '+00:00'
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
    # "Opening Day at Snow Valley is set for this Friday, November 27"
    m = re.search(
        r'opening day\b.{0,160}?\b(January|February|March|April|May|June|July|'
        r'August|September|October|November|December)\s+(\d{1,2})(?:st|nd|rd|th)?',
        text, re.I)
    if m:
        return f'{m.group(1).title()[:3]} {int(m.group(2))}'
    return None


_MONTHS = {
    'jan': 1, 'january': 1, 'feb': 2, 'february': 2, 'mar': 3, 'march': 3,
    'apr': 4, 'april': 4, 'may': 5, 'jun': 6, 'june': 6, 'jul': 7, 'july': 7,
    'aug': 8, 'august': 8, 'sep': 9, 'sept': 9, 'september': 9,
    'oct': 10, 'october': 10, 'nov': 11, 'november': 11, 'dec': 12, 'december': 12,
}


def parse_opens_date(opens, today=None):
    """Parse 'Nov 27' / 'November 27, 2026' to a date. TBD/unparseable → None."""
    if not opens:
        return None
    s = str(opens).strip()
    if re.match(r'^tbd$', s, re.I):
        return None
    m = re.match(r'^([A-Za-z]{3,9})\.?\s+(\d{1,2})(?:,?\s*(\d{4}))?$', s)
    if not m:
        return None
    mon = _MONTHS.get(m.group(1).lower())
    if not mon:
        return None
    today = today or now_pt().date()
    year = int(m.group(3)) if m.group(3) else today.year
    try:
        return datetime.date(year, mon, int(m.group(2)))
    except ValueError:
        return None


def opens_is_future(opens, today=None):
    """True if the opening date is after today. TBD/unparseable counts as
    still pre-opening (not 'today or earlier')."""
    today = today or now_pt().date()
    d = parse_opens_date(opens, today=today)
    if d is None:
        return bool(opens)
    return d > today


def status_of(official_status, lifts_open, runs_open, opens):
    """Map official status + lift/run counts to open / limited / closed.

    Prefer the official operating flag. A resort is OPEN if that flag is
    Open, or if lifts or runs are already spinning. MtnPowder sometimes
    flags a SoCal resort as "Open" before opening day (0 lifts, TBD or a
    future date). Only a future/TBD opening date may force CLOSED in that
    case. An opening date of today or earlier does not force CLOSED.
    Spinning lifts/runs with an official Closed flag stay LIMITED.
    """
    lo = lifts_open or 0
    ro = runs_open or 0
    spinning = lo > 0 or ro > 0
    flag = (official_status or '').strip().lower()
    if spinning and flag == 'closed':
        return 'limited'
    if spinning:
        return 'open'
    # Nothing spinning yet. Follow the official flag unless the mountain
    # has not reached its announced opening date (or the date is TBD).
    if opens_is_future(opens):
        return 'closed'
    if flag == 'open':
        return 'open'
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
        'topIn': to_num((sr.get('SummitArea') or {}).get('BaseIn')),
        'baseRange': None if sr.get('SnowBaseRangeIn') in (None, '--', '') else str(sr.get('SnowBaseRangeIn')),
        'tempF': official_temp,
        'tempSource': 'resort' if official_temp is not None else None,
        'conditions': None if sr.get('BaseConditions') in (None, '--', '') else sr.get('BaseConditions'),
        'source': 'mtnpowder',
        'sourceUpdated': iso(src_up) if src_up else (sr.get('LastUpdate') or raw.get('LastUpdate')),
    }


def _area_is_open(value):
    """West/East/Yeti may be 'Open', 'Closed', or hours like '9:00 AM - 10:00 PM'."""
    s = (value or '').strip().lower()
    if not s or s in ('closed', 'close', '--', '-'):
        return False
    if s == 'open' or re.search(r'\d\s*(am|pm)', s, re.I):
        return True
    return False


def _labelbox_inches(html_text):
    """Official LabelBox snowfall figures (24/48/7-day) from the full report page."""
    out = {}
    for m in re.finditer(
            r'class="t-digit-lg">\s*([^<]+).*?class="LabelBox-title">\s*([^<]+?)\s*</h3>',
            html_text, re.I | re.S):
        title = re.sub(r'\s+', ' ', html.unescape(m.group(2))).strip().lower()
        out[title] = to_num(m.group(1))
    return out


def parse_mthigh(html_text):
    rows = {}
    for lab, raw in re.findall(
            r'class="mh-Conditions-label"[^>]*>\s*([^<]+?)\s*</span>\s*'
            r'<span class="mh-Conditions-value"[^>]*>(.*?)</span>',
            html_text, re.S):
        key = html.unescape(lab).strip().rstrip(':')
        rows[key] = strip_html(raw)
    def val(*labels):
        for lab, v in rows.items():
            key = lab.strip().rstrip(':').lower()
            for want in labels:
                if key == want.lower():
                    return v
        return None

    text = strip_html(html_text)
    opens = opening_from_text(text)
    lifts_open = to_num(val('Open Lifts'))
    runs_open = to_num(val('Open Trails'))
    west = val('WEST')
    east = val('EAST')
    yeti = val('YETI')
    area_open = any(_area_is_open(s) for s in (west, east, yeti))
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
    boxes = _labelbox_inches(html_text)
    snow24h = boxes.get('24 hour snowfall')
    snow48h = boxes.get('48 hour snowfall')
    snow7d = to_num(val('New Snow (7 Days)'))
    if snow7d is None:
        snow7d = boxes.get('7 day snowfall')
    # Hours label: the open area's posted hours, if any
    hours = None
    for area_name, area_val in (('West', west), ('East', east), ('Yeti', yeti)):
        if area_val and _area_is_open(area_val) and re.search(r'\d', area_val or ''):
            hours = f'{area_name} {area_val}'
            break
    return {
        'id': 'mthigh',
        'name': 'Mountain High',
        'region': 'Wrightwood',
        'status': status,
        'officialStatus': official,
        'opens': opens,
        'liftsOpen': lifts_open,
        'liftsTotal': None,  # filled from official stats/trail map in main()
        'runsOpen': runs_open,
        'runsTotal': None,
        'groomedOpen': to_num(val('Groomed Trails')),
        'snow24h': snow24h,
        'snow48h': snow48h,
        'snow7d': snow7d,
        'baseIn': to_num(val('Base Depth')),
        'topIn': to_num(val('Top Depth')),
        'baseRange': None,
        'tempF': temp,
        'tempSource': 'resort' if temp is not None else None,
        'conditions': None,
        'hoursLabel': hours,
        'source': 'mthigh',
        'sourceUpdated': updated_iso or updated,
        'areas': {
            'west': west,
            'east': east,
            'yeti': yeti,
        },
    }


def _hourly_snow_inches(item):
    """Sum Open-Meteo hourly snowfall (cm) over the last 24h and 48h, as inches."""
    hourly = item.get('hourly') or {}
    times = hourly.get('time') or []
    snow = hourly.get('snowfall') or []
    if not times or not snow:
        return None, None
    try:
        from zoneinfo import ZoneInfo
        now = datetime.datetime.now(ZoneInfo('America/Los_Angeles')).replace(
            minute=0, second=0, microsecond=0)
    except Exception:
        now = now_pt().replace(minute=0, second=0, microsecond=0)
    s24 = s48 = 0.0
    for ts, cm in zip(times, snow):
        try:
            dt = datetime.datetime.fromisoformat(ts)
            if dt.tzinfo is None:
                try:
                    from zoneinfo import ZoneInfo
                    dt = dt.replace(tzinfo=ZoneInfo('America/Los_Angeles'))
                except Exception:
                    dt = dt.replace(tzinfo=TZ)
        except Exception:
            continue
        hrs = (now - dt).total_seconds() / 3600
        val = float(cm or 0)
        if 0 < hrs <= 24:
            s24 += val
        if 0 < hrs <= 48:
            s48 += val
    def inch(cm):
        return int(round(cm / 2.54))
    return inch(s24), inch(s48)


WEEKDAYS = ('Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun')


def _weather_label(code):
    """Short on-slide forecast word from an Open-Meteo / WMO weather code."""
    if code is None or code == '':
        return None
    try:
        c = int(code)
    except (TypeError, ValueError):
        return None
    if c <= 1:
        return 'Sunny'
    if c == 2:
        return 'Partly cloudy'
    if c == 3:
        return 'Cloudy'
    if c in (45, 48):
        return 'Fog'
    if 51 <= c <= 57:
        return 'Drizzle'
    if 61 <= c <= 67 or 80 <= c <= 82:
        return 'Rain'
    if 71 <= c <= 77 or 85 <= c <= 86:
        return 'Snow'
    if 95 <= c <= 99:
        return 'Storms'
    return 'Cloudy'


def _inch_cm(cm):
    return int(round(float(cm or 0) / 2.54))


def _forecast_from_daily(item):
    """Expected snow for today plus the next 2 days, and a short forecast label.

    Uses Open-Meteo daily snowfall_sum (cm, converted to whole inches) and
    weather_code. Returns None if the daily block is missing. 0 is a real value.
    """
    daily = item.get('daily') or {}
    times = daily.get('time') or []
    snow = daily.get('snowfall_sum') or []
    codes = daily.get('weather_code') or []
    if not times or not snow:
        return None
    try:
        from zoneinfo import ZoneInfo
        today = datetime.datetime.now(ZoneInfo('America/Los_Angeles')).date()
    except Exception:
        today = now_pt().date()
    days = []
    for i, ts in enumerate(times):
        try:
            d = datetime.date.fromisoformat(str(ts)[:10])
        except Exception:
            continue
        if d < today:
            continue
        cm = snow[i] if i < len(snow) else None
        inches = _inch_cm(cm) if cm is not None else 0
        code = codes[i] if i < len(codes) else None
        days.append({'date': d, 'inches': inches, 'code': code})
    next3 = days[:3]
    if not next3:
        return None
    total = sum(d['inches'] for d in next3)
    peak = max(next3, key=lambda d: d['inches'])
    peak_day = WEEKDAYS[peak['date'].weekday()] if peak['inches'] > 0 else None
    if peak_day:
        label = f'Snow {peak_day}'
    else:
        label = _weather_label(next3[0]['code'])
        if label is None:
            label = _weather_label((item.get('current') or {}).get('weather_code'))
    return {'snow72h': total, 'snow72hPeakDay': peak_day, 'forecastLabel': label}


BALDY_OPEN_RUN = {'open', 'groomed', 'ungroomed', 'grooming', 'packed'}


def parse_baldy(status_doc, weather_doc=None):
    """Build a resort record from the official Mt. Baldy tickets API."""
    report = (status_doc or {}).get('report') or {}
    chairs = report.get('chairs') or {}
    lifts_open = 0
    lifts_scenic = 0
    for info in chairs.values():
        st = str((info or {}).get('status') or '').strip().lower()
        if st == 'open':
            lifts_open += 1
        elif st == 'scenic':
            lifts_scenic += 1
    lifts_total = BALDY_LIFTS_FALLBACK
    catalog = status_doc.get('chairs') or []
    if isinstance(catalog, list) and 3 <= len(catalog) <= 8:
        lifts_total = len(catalog)

    runs_open = 0
    for run in status_doc.get('runs') or []:
        if run.get('never'):
            continue
        st = str(run.get('status') or '').strip().lower()
        if st in BALDY_OPEN_RUN:
            runs_open += 1

    wx = weather_doc or (status_doc.get('weather') or {})
    temp = to_num(wx.get('temp'))
    src_up = parse_dt(report.get('at') or report.get('clientTime'))
    hours = None
    today = ((status_doc.get('openHours') or {}).get('today') or {})
    if today.get('label'):
        hours = today.get('label') if today.get('open') else 'Closed'
    elif today.get('open') is False:
        hours = 'Closed'

    opens = None
    official = 'Open' if (lifts_open > 0 or runs_open > 0 or today.get('open')) else 'Closed'
    status = status_of(official, lifts_open, runs_open, opens)

    report_stale = False
    if src_up:
        try:
            age_h = (now_pt() - src_up).total_seconds() / 3600
            report_stale = age_h > 18
        except Exception:
            report_stale = False

    surface = report.get('surface')
    return {
        'id': 'baldy',
        'name': 'Mt. Baldy',
        'region': 'Angeles National Forest',
        'status': status,
        'officialStatus': official,
        'opens': opens,
        'liftsOpen': lifts_open,
        'liftsScenic': lifts_scenic,
        'liftsTotal': lifts_total,
        'runsOpen': runs_open,
        'runsTotal': BALDY_RUNS_FALLBACK,
        'snow24h': to_num(report.get('newSnow')),
        'snow48h': None,  # official API does not publish 48h snow
        'snow7d': None,
        'baseIn': to_num(report.get('base')),
        'topIn': None,
        'baseRange': None,
        'tempF': temp,
        'tempSource': 'resort' if temp is not None else None,
        'conditions': None if surface in (None, '', '--') else surface,
        'hoursLabel': hours,
        'source': 'baldy',
        'sourceUpdated': iso(src_up) if src_up else report.get('at'),
        'reportStale': report_stale,
        'roads': report.get('roads') or None,
    }


def add_display_fields(resort):
    """Slide-ready label strings. Missing values stay null (not invented)."""
    def count_label(opened, total):
        if opened is None and total is None:
            return None
        if opened is None:
            return None
        if total is None:
            return str(int(opened)) if float(opened) == int(opened) else str(opened)
        try:
            return f'{int(opened)} / {int(total)}'
        except (TypeError, ValueError):
            return f'{opened} / {total}'

    def inch_label(v):
        if v is None or v == '':
            return None
        try:
            return f'{int(round(float(v)))}"'
        except (TypeError, ValueError):
            return None

    resort['liftsLabel'] = count_label(resort.get('liftsOpen'), resort.get('liftsTotal'))
    resort['runsLabel'] = count_label(resort.get('runsOpen'), resort.get('runsTotal'))
    resort['baseLabel'] = inch_label(resort.get('baseIn'))
    resort['topLabel'] = inch_label(resort.get('topIn'))
    resort['snow24hLabel'] = inch_label(resort.get('snow24h'))
    resort['snow48hLabel'] = inch_label(resort.get('snow48h'))
    if not resort.get('hoursLabel'):
        resort['hoursLabel'] = None
    return resort


def fetch_open_meteo(specs):
    lats = ','.join(str(s['lat']) for s in specs)
    lons = ','.join(str(s['lon']) for s in specs)
    url = OPEN_METEO.format(lats=lats, lons=lons)
    data = json.loads(fetch(url, timeout=30))
    items = data if isinstance(data, list) else [data]
    out = {}
    for spec, item in zip(specs, items):
        cur = item.get('current') or {}
        temp = to_num(cur.get('temperature_2m'))
        s24, s48 = _hourly_snow_inches(item)
        fc = _forecast_from_daily(item) or {}
        out[spec['id']] = {
            'temp': temp,
            'snow24h': s24,
            'snow48h': s48,
            'snow72h': fc.get('snow72h'),
            'snow72hPeakDay': fc.get('snow72hPeakDay'),
            'forecastLabel': fc.get('forecastLabel'),
        }
    return out


def apply_model_snow(resort, om):
    """Fill missing 24h/48h snow from Open-Meteo. Does not override official values (including 0)."""
    if not om:
        return
    if resort.get('snow24h') is None and om.get('snow24h') is not None:
        resort['snow24h'] = om['snow24h']
        resort['snow24hSource'] = 'open-meteo'
    if resort.get('snow48h') is None and om.get('snow48h') is not None:
        resort['snow48h'] = om['snow48h']
        resort['snow48hSource'] = 'open-meteo'


def apply_forecast(resort, om):
    """Attach 3-day expected snow and a short forecast label. New fields only."""
    if not om:
        return
    if om.get('snow72h') is not None:
        resort['snow72h'] = om['snow72h']
        resort['snow72hSource'] = 'open-meteo'
        resort['snow72hPeakDay'] = om.get('snow72hPeakDay')
    if om.get('forecastLabel'):
        resort['forecastLabel'] = om['forecastLabel']


def fetch_mthigh_totals():
    """Official lift total from Mountain Stats; run total from the trail map."""
    lifts, runs = MH_LIFTS_FALLBACK, MH_RUNS_FALLBACK
    try:
        page = fetch(MHIGH_STATS_URL, timeout=30)
        m = re.search(r'Lifts:\s*(\d+)\s*Total', page, re.I)
        if m:
            lifts = int(m.group(1))
    except Exception as e:
        print('WARN mthigh stats failed:', e, file=sys.stderr)
    try:
        page = fetch(MHIGH_MAP_URL, timeout=30)
        ids = set(re.findall(r'id="(runs_x5F_[^"]+)"', page))
        if 20 <= len(ids) <= 120:
            runs = len(ids)
    except Exception as e:
        print('WARN mthigh trail map failed:', e, file=sys.stderr)
    return lifts, runs


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
        'id', 'status', 'opens', 'liftsOpen', 'liftsTotal', 'liftsScenic',
        'runsOpen', 'runsTotal', 'groomedOpen',
        'snow24h', 'snow48h', 'snow24hSource', 'snow48hSource', 'snow7d',
        'baseIn', 'topIn',
        'tempF', 'tempSource', 'conditions', 'hoursLabel',
        'snow72h', 'snow72hPeakDay', 'snow72hSource', 'forecastLabel',
        'liftsLabel', 'runsLabel', 'baseLabel', 'topLabel', 'snow24hLabel', 'snow48hLabel',
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

    mh_lifts, mh_runs = MH_LIFTS_FALLBACK, MH_RUNS_FALLBACK
    try:
        mh_lifts, mh_runs = fetch_mthigh_totals()
    except Exception as e:
        errors.append(f'mthigh totals: {e}')
        print('WARN mthigh totals failed:', e, file=sys.stderr)

    baldy = None
    try:
        baldy_status = json.loads(fetch(BALDY_STATUS_URL, timeout=30))
        baldy_wx = None
        try:
            baldy_wx = json.loads(fetch(BALDY_WEATHER_URL, timeout=20))
        except Exception as e:
            print('WARN baldy weather failed:', e, file=sys.stderr)
        baldy = parse_baldy(baldy_status, baldy_wx)
    except Exception as e:
        errors.append(f'baldy: {e}')
        print('WARN baldy failed:', e, file=sys.stderr)

    resorts = []
    for spec in RESORTS:
        parsed = None
        if spec['id'] == 'mthigh':
            parsed = mh
            if parsed:
                parsed['liftsTotal'] = mh_lifts
                parsed['runsTotal'] = mh_runs
        elif spec['id'] == 'baldy':
            parsed = baldy
        elif spec['feed_name'] and spec['feed_name'] in feed:
            parsed = parse_feed_resort(spec, feed[spec['feed_name']])
        elif spec['feed_name']:
            errors.append(f'mtnpowder: missing {spec["feed_name"]}')
        if parsed:
            apply_temps(parsed, (om.get(spec['id']) or {}).get('temp'))
            # Baldy publishes newSnow/base as null when unmeasured; do not
            # invent 0" from the weather model in that case.
            if spec['id'] != 'baldy':
                apply_model_snow(parsed, om.get(spec['id']) or {})
            apply_forecast(parsed, om.get(spec['id']) or {})
            parsed['statusLabel'] = label_status(parsed['status'])
            add_display_fields(parsed)
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
                f"72h={r.get('snow72h')} peak={r.get('snow72hPeakDay')} fc={r.get('forecastLabel')} "
                f"base={r.get('baseIn')} top={r.get('topIn')} temp={r.get('tempF')}({r.get('tempSource')}) "
                f"hours={r.get('hoursLabel')} opens={r.get('opens')}"
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
            f"72h={r.get('snow72h')} peak={r.get('snow72hPeakDay')} fc={r.get('forecastLabel')} "
            f"base={r.get('baseIn')} top={r.get('topIn')} temp={r.get('tempF')}({r.get('tempSource')}) "
            f"hours={r.get('hoursLabel')} opens={r.get('opens')}"
        )
    print('DATA_CHANGED')
    return 0


if __name__ == '__main__':
    sys.exit(main())
