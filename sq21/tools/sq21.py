#!/usr/bin/env python3
"""Fetch SQ 21 (EWR->SIN) status/position for one departure date; print a trip/live doc as JSON.
Usage: python3 -I sq21.py YYYY-MM-DD   (Newark local departure date)
Exits non-zero and prints nothing on stdout if no real data could be read. Never invents values."""
import json, re, sys, subprocess, datetime as dt
from zoneinfo import ZoneInfo

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
NY = ZoneInfo("America/New_York")
day = dt.date.fromisoformat(sys.argv[1])
now = dt.datetime.now(dt.timezone.utc)
iso = lambda t: t.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if t else None
ts = lambda s: dt.datetime.fromtimestamp(s, dt.timezone.utc) if s else None
pz = lambda s: dt.datetime.fromisoformat(s.replace("Z", "+00:00")) if s else None
log = lambda *a: print(*a, file=sys.stderr)

def get(url):
    r = subprocess.run(["curl", "-sSL", "--max-time", "40", "-A", UA, url], capture_output=True, text=True)
    if r.returncode or len(r.stdout) < 2000: raise RuntimeError(f"fetch failed {url}: {r.stderr.strip()[:200]}")
    return r.stdout

def embedded(html, marker):
    i = html.index(marker) + len(marker)
    return json.JSONDecoder().raw_decode(html[i:])[0]

def flightstats():
    h = get(f"https://www.flightstats.com/v2/flight-tracker/SQ/21?year={day.year}&month={day.month}&date={day.day}")
    fl = embedded(h, "__NEXT_DATA__ = ")["props"]["initialState"]["flightTracker"].get("flight") or {}
    sc, st = fl.get("schedule") or {}, fl.get("status") or {}
    if (fl.get("departureAirport") or {}).get("iata") != "EWR" or (fl.get("arrivalAirport") or {}).get("iata") != "SIN": raise RuntimeError("FS: not EWR-SIN")
    if not (sc.get("scheduledDeparture") or "").startswith(day.isoformat()): raise RuntimeError("FS: wrong date")
    pos = sorted(((fl.get("positional") or {}).get("flexTrack") or {}).get("positions") or [], key=lambda p: p.get("date") or "")
    p = pos[-1] if pos else None
    words = {"S": "Scheduled", "A": "In the air", "L": "Landed", "C": "Cancelled", "D": "Diverted", "R": "Diverted"}
    status = words.get(st.get("statusCode"), st.get("status") or "Unknown")
    if st.get("statusCode") == "S" and (st.get("delay") or {}).get("departure", {}).get("minutes"): status += " · " + st.get("statusDescription", "")
    return {
        "status": status,
        "actualDepUtc": iso(pz(sc.get("estimatedActualDepartureUTC"))) if sc.get("estimatedActualDepartureTitle") == "Actual" else None,
        "estArriveUtc": iso(pz(sc.get("estimatedActualArrivalUTC") or sc.get("scheduledArrivalUTC"))),
        "lat": p and p.get("lat"), "lon": p and p.get("lon"), "altitudeFt": p and p.get("altitudeFt"),
        "posTime": p and pz(p.get("date")), "landed": st.get("statusCode") == "L",
    }

def flightaware():
    live = embedded(get("https://www.flightaware.com/live/flight/SIA21"), "trackpollBootstrap = ")
    log_ = next(iter(live["flights"].values()))["activityLog"]["flights"]
    leg = next((a for a in log_ if a["origin"].get("iata") == "EWR" and a["destination"].get("iata") == "SIN"
                and ts(a["gateDepartureTimes"]["scheduled"]).astimezone(NY).date() == day), None)
    if not leg: raise RuntimeError("FA: no leg for that date")
    f = next(iter(embedded(get("https://www.flightaware.com" + leg["permaLink"]), "trackpollBootstrap = ")["flights"].values()))
    tr = [t for t in (f.get("track") or []) if t.get("coord")]
    p = tr[-1] if tr else None
    arr = f["gateArrivalTimes"]; land = f["landingTimes"]; off = f["takeoffTimes"]
    landed = bool(land.get("actual")) or f.get("flightStatus") == "arrived"
    status = "Cancelled" if f.get("cancelled") else "Diverted" if f.get("diverted") else "Landed" if landed else "In the air" if off.get("actual") else "Scheduled"
    alt = p and p.get("alt")
    return {
        "status": status,
        "actualDepUtc": iso(ts(off.get("actual") or f["gateDepartureTimes"].get("actual"))),
        "estArriveUtc": iso(ts(arr.get("actual") or land.get("actual") or arr.get("estimated") or arr.get("scheduled"))),
        "lat": p and p["coord"][1], "lon": p and p["coord"][0], "altitudeFt": alt * 100 if alt is not None else None,
        "posTime": p and ts(p.get("timestamp")), "landed": landed,
    }

def adsb():
    # Real-time ADS-B position by callsign. Only meaningful while our flight is airborne
    # (the same callsign is reused daily), so the caller decides whether to use it.
    d = json.loads(get_json("https://api.adsb.lol/v2/callsign/SIA21"))
    ac = [a for a in d.get("ac") or [] if a.get("lat") is not None and (a.get("seen_pos") or 999) < 300]
    if not ac: raise RuntimeError("ADSB: no current position")
    a = min(ac, key=lambda a: a.get("seen_pos") or 999)
    t = ts((d.get("now") or now.timestamp() * 1000) / 1000 - (a.get("seen_pos") or 0))
    alt = a.get("alt_baro")
    return {"lat": a["lat"], "lon": a["lon"], "altitudeFt": alt if isinstance(alt, (int, float)) else None, "posTime": t}

def get_json(url):
    r = subprocess.run(["curl", "-sSL", "--max-time", "30", "-A", UA, url], capture_output=True, text=True)
    if r.returncode or not r.stdout.strip().startswith("{"): raise RuntimeError(f"fetch failed {url}: {r.stderr.strip()[:200]}")
    return r.stdout

res = {}
for name, fn in (("FlightStats", flightstats), ("FlightAware", flightaware)):
    try: res[name] = fn()
    except Exception as e: log(f"{name}: {e}")
if not res: log("No source returned data; leave trip/live unchanged."); sys.exit(2)

# Times/status: prefer FlightStats; position: whichever source has the newest real fix.
main_name = "FlightStats" if "FlightStats" in res else "FlightAware"
main = res[main_name]
fixes = [(r["posTime"], n, r) for n, r in res.items() if r["posTime"] and r["lat"] is not None]
# Add the ADS-B fix only when the sources above say our flight has departed and not landed.
if any(r["actualDepUtc"] or r["status"] == "In the air" for r in res.values()) and not any(r["landed"] for r in res.values()):
    try:
        a = adsb(); fixes.append((a["posTime"], "adsb.lol", dict(a, landed=False)))
    except Exception as e: log(f"adsb.lol: {e}")
doc = {k: main[k] for k in ("status", "actualDepUtc", "estArriveUtc")}
# If the other source is further along (e.g. FlightStats still says Scheduled after takeoff), use its status.
rank = lambda r: 2 if r["landed"] else 1 if r["status"] == "In the air" else 0
ahead = max(res.values(), key=rank)
if rank(ahead) > rank(main) and not main["status"].startswith(("Cancelled", "Diverted")):
    doc["status"] = ahead["status"]; main = dict(main, landed=ahead["landed"])
doc.update(lat=None, lon=None, altitudeFt=None)
src = [main_name]
if fixes:
    t, n, r = max(fixes, key=lambda x: x[0])
    doc.update(lat=round(r["lat"], 4), lon=round(r["lon"], 4), altitudeFt=r["altitudeFt"])
    if n not in src: src.append(n)
if not doc["actualDepUtc"]:
    doc["actualDepUtc"] = next((r["actualDepUtc"] for r in res.values() if r["actualDepUtc"]), None)
# updatedAt = when this data was true: the position fix time while airborne, else now.
airborne = fixes and not main["landed"] and doc["actualDepUtc"]
doc["updatedAt"] = iso(max(f[0] for f in fixes) if airborne else now)
doc["source"] = " + ".join(src)
log("LANDED=" + ("yes" if main["landed"] else "no"))
print(json.dumps(doc, indent=1))
