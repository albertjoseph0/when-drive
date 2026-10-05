"""Collect predicted drive times for the River Vale <-> Wharton commute.

Queries the Routes API (computeRoutes, TRAFFIC_AWARE_OPTIMAL) on a 5-minute
departure grid for every weekday of one sample week, in both directions, under
the BEST_GUESS and PESSIMISTIC traffic models. Results go to data/raw.jsonl
(one JSON object per request) so reruns only fetch what is missing.

Usage:
    GOOGLE_MAPS_API_KEY=... python3 collect.py
"""

import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

TZ = ZoneInfo("America/New_York")
HOME = "589 Westwood Ave, River Vale, NJ"
WORK = "213 NJ-15, Wharton, NJ 07885"
URL = "https://routes.googleapis.com/directions/v2:computeRoutes"
FIELD_MASK = "routes.duration,routes.staticDuration,routes.distanceMeters,routes.description"

# Predictions far in the future come purely from historical day-of-week /
# time-of-day patterns (the same 7:15 Tuesday query returns identical results
# for Oct, Jan and Jul), so one ordinary, holiday-free week is representative.
WEEK_START = date(2026, 10, 19)  # Monday
AM_WINDOW = ("05:00", "08:55")  # leaving home
PM_WINDOW = ("14:45", "19:00")  # leaving work
STEP_MIN = 5
MODELS = ("BEST_GUESS", "PESSIMISTIC")
OUT = Path(__file__).parent / "data" / "raw.jsonl"


def grid(day, start, end):
    t = datetime.combine(day, datetime.strptime(start, "%H:%M").time(), TZ)
    stop = datetime.combine(day, datetime.strptime(end, "%H:%M").time(), TZ)
    while t <= stop:
        yield t
        t += timedelta(minutes=STEP_MIN)


def jobs():
    for offset in range(5):
        day = WEEK_START + timedelta(days=offset)
        for model in MODELS:
            for t in grid(day, *AM_WINDOW):
                yield ("AM", HOME, WORK, t, model)
            for t in grid(day, *PM_WINDOW):
                yield ("PM", WORK, HOME, t, model)


def key(direction, depart, model):
    return f"{direction}|{depart.isoformat()}|{model}"


def fetch(session, api_key, job):
    direction, origin, dest, depart, model = job
    body = {
        "origin": {"address": origin},
        "destination": {"address": dest},
        "travelMode": "DRIVE",
        "routingPreference": "TRAFFIC_AWARE_OPTIMAL",
        "trafficModel": model,
        "departureTime": depart.isoformat(),
    }
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": FIELD_MASK,
        "X-Goog-Maps-Solution-ID": "gmp_git_agentskills_v1",
    }
    for attempt in range(5):
        r = session.post(URL, headers=headers, json=body, timeout=30)
        if r.status_code == 200:
            route = r.json()["routes"][0]
            return {
                "direction": direction,
                "depart": depart.isoformat(),
                "weekday": depart.strftime("%a"),
                "model": model,
                "duration_s": int(route["duration"].rstrip("s")),
                "static_s": int(route["staticDuration"].rstrip("s")),
                "meters": route["distanceMeters"],
                "route": route.get("description", ""),
            }
        if r.status_code in (429, 500, 503):
            time.sleep(2 ** attempt)
            continue
        raise RuntimeError(f"{r.status_code}: {r.text[:300]}")
    raise RuntimeError(f"gave up after retries: {job}")


def main():
    api_key = os.environ.get("GOOGLE_MAPS_API_KEY")
    if not api_key:
        sys.exit("Set GOOGLE_MAPS_API_KEY")
    OUT.parent.mkdir(exist_ok=True)
    done = set()
    if OUT.exists():
        for line in OUT.read_text().splitlines():
            row = json.loads(line)
            done.add(f"{row['direction']}|{row['depart']}|{row['model']}")
    todo = [j for j in jobs() if key(j[0], j[3], j[4]) not in done]
    print(f"{len(done)} cached, {len(todo)} to fetch", flush=True)

    session = requests.Session()
    with ThreadPoolExecutor(max_workers=6) as pool, OUT.open("a") as out:
        for i, row in enumerate(pool.map(lambda j: fetch(session, api_key, j), todo), 1):
            out.write(json.dumps(row) + "\n")
            if i % 50 == 0:
                print(f"{i}/{len(todo)}", flush=True)
    print("done", flush=True)


if __name__ == "__main__":
    main()
