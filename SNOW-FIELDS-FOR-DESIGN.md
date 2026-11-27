# Snow report fields for the register TV slides

PIAS Design owns the look of the live snow slides. This file is the data contract from PIAS ADS. Nothing here has been pushed live. Dustin asked (Nov 27, 2026, 6:54 AM PT) for more than place + temperature on the Southern California slide — specifically things like how many runs are open.

## Why the SoCal slide only shows place and temp today

`snow.json` already had lifts, runs, base, and 24h/48h snow. The SoCal renderer in `index.html` (`snHTML('socal')`) only paints **NEW SNOW** (and only if it is greater than 0) and **TEMP**. It never shows lifts, runs, or base, even when a resort is open. The Mammoth slide already shows new snow, base, temp, and lifts open (not runs, and not "of total").

Please keep status colors the same on every resort, no on-screen credits, and the wax banner: `SNOWBOARD & SKI TUNE-UPS AND WAX DONE HERE`.

## Data file

The player already loads `/snow.json` network-first about every 15 minutes (the Action refreshes it every 30 minutes). A local copy of today's values is in this branch; it is not on main and has not been deployed.

## Fields to lay out (per resort)

Use the `*Label` strings when present so you do not have to format fractions or inches. A field that is `null` was not published — omit it or show "n/a", but do not invent a number. `0` is a real value (no new snow, no lifts spinning yet).

| Field | Label helper | Meaning |
| --- | --- | --- |
| `status` / `statusLabel` | `OPEN`, `LIMITED`, `CLOSED` | Our mapped status. Pill already exists. |
| `opens` | e.g. `Nov 27` | Opening date if still closed. Omit once the resort is spinning. |
| `liftsOpen` / `liftsTotal` | `liftsLabel` e.g. `3 / 12` | Lifts open of total. |
| `liftsScenic` | (Baldy only, when > 0) | Scenic-only chair, not counted in `liftsOpen`. |
| `runsOpen` / `runsTotal` | `runsLabel` e.g. `6 / 49` | Trails/runs open of total. |
| `groomedOpen` | (Mountain High when published) | Groomed trails today. |
| `baseIn` / `baseRange` | `baseLabel` e.g. `12"`; range may be `12 - 18` | Base depth, inches. Prefer `baseRange` on the slide when it is present. |
| `topIn` | `topLabel` e.g. `24"` | Summit / top depth, inches. |
| `snow24h` / `snow48h` | `snow24hLabel`, `snow48hLabel` | New snow, inches. `0"` is a real "none". An `*`-style source is `snow24hSource` / `snow48hSource` = `open-meteo` when the official report did not publish 24h/48h. |
| `tempF` | already shown as `47°` | Current temp. `tempSource` is `resort` or `open-meteo`. |
| `conditions` | e.g. `Machine Groomed` | Surface conditions when published. |
| `hoursLabel` | e.g. `West 9:00 AM - 10:00 PM` or `9 AM – 5 PM` | Posted hours when we have them (Mountain High, Mt. Baldy). Null for BBMR/Mammoth. |
| `forecastLabel` / `snow72h` / `snow72hPeakDay` | e.g. `Cloudy`, or `Snow Sun` with expected inches | Next-3-day model forecast (Open-Meteo), not official. |
| `updatedLabel` (file level) | `Updated 7:05 AM PT` | Already on the slide stamp. |
| `reportStale` | (Baldy only) | `true` when the official mountain report is more than 18 hours old. Lift/run numbers are still the last official report; do not treat them as a live chair count if this is true. |

Suggested SoCal card metrics, in this order, when the value is present:

1. Status pill (already there)
2. Opening date, only if closed
3. Runs open of total
4. Lifts open of total
5. Base depth (and top if space)
6. 24h new snow (show `0"` or omit zeros — your call; do not hide a real 5" just because the resort is "limited")
7. 48h new snow if it differs from 24h or if you have room
8. Temp
9. Conditions and hours if they fit

The SoCal grid now has four resorts. This branch also adds **Mt. Baldy** as a fifth SoCal resort in `snow.json`. Including it on the slide is a layout decision for Design (five cards, or Baldy on its own, or leave it off until Dustin asks). Do not add June Mountain or other Northern/Eastern resorts to the SoCal slide.

## Overnight / early-morning quirk

Big Bear and Mammoth often report `liftsOpen: 0` before first chair (holiday hours today are 8:30 AM–4:00 PM PT at Bear and Summit) even when `runsOpen` is already set for the day and official status is Open. Show **runs** and **lifts** as reported (`0 / 11` is honest before first chair). Do not treat "0 lifts" as "the mountain is closed" if status is OPEN and runs are open.

Mammoth's official feed can say OperatingStatus `Closed` overnight while still listing many trails open; our status then becomes `LIMITED`. Prefer official `runsLabel` + `liftsLabel` over the word LIMITED alone.

## Sources (do not scrape OnTheSnow for the slide)

Official only: MtnPowder (Bear, Summit, Valley, Mammoth), mthigh.com snow report, Mt. Baldy tickets API. OnTheSnow was checked on Nov 27, 2026 and disagreed with official counts (it treated expected or total lifts as open, and used Mountain High's top depth as base).
