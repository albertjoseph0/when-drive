"""Pick the 5/4-9 shift start time, SDO, and 8-hour day that minimize commuting.

Reads data/raw.jsonl from collect.py. For every start time S (6:30-8:30 in
5-minute steps) it plans:
  * morning: the latest departure that reaches the gate GATE_BUFFER minutes
    before S (predicted BEST_GUESS duration, linearly interpolated per minute)
  * evening: leave the gate GATE_BUFFER minutes after the shift ends, where a
    9-hour day ends at S + 9h + lunch and the 8-hour day at S + 8h + lunch
and totals one pay period: 9 workdays (each weekday twice, minus the SDO),
with the 8-hour day on any one of them.

Usage:
    python3 analyze.py [--buffer MIN] [--lunch MIN]
"""

import argparse
import itertools
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path

DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri")
RAW = Path(__file__).parent / "data" / "raw.jsonl"


def minutes(hhmm):
    h, m = map(int, hhmm.split(":"))
    return h * 60 + m


def clock(mins):
    mins = round(mins)
    h, m = divmod(mins, 60)
    return f"{(h - 1) % 12 + 1}:{m:02d}{'am' if h < 12 else 'pm'}"


def load():
    """curves[(direction, model, weekday)] = sorted [(depart_min, duration_min)]"""
    curves = defaultdict(list)
    for line in RAW.read_text().splitlines():
        r = json.loads(line)
        t = datetime.fromisoformat(r["depart"])
        curves[(r["direction"], r["model"], r["weekday"])].append(
            (t.hour * 60 + t.minute, r["duration_s"] / 60)
        )
    return {k: sorted(v) for k, v in curves.items()}


def interp(curve, t):
    for (t0, d0), (t1, d1) in zip(curve, curve[1:]):
        if t0 <= t <= t1:
            return d0 + (d1 - d0) * (t - t0) / (t1 - t0)
    raise ValueError(f"{clock(t)} outside sampled window")


def latest_departure(curve, arrive_by):
    """Latest whole-minute departure whose predicted arrival is <= arrive_by."""
    t = arrive_by - 1
    while t + interp(curve, t) > arrive_by:
        t -= 1
    return t


def plan_day(curves, day, start, buffer, lunch, hours, model="BEST_GUESS"):
    am = curves[("AM", model, day)]
    pm = curves[("PM", model, day)]
    leave_home = latest_departure(curves[("AM", "BEST_GUESS", day)], start - buffer)
    leave_work = start + hours * 60 + lunch + buffer
    return {
        "leave_home": leave_home,
        "am": interp(am, leave_home),
        "leave_work": leave_work,
        "pm": interp(pm, leave_work),
    }


def evaluate(curves, start, buffer, lunch, model="BEST_GUESS"):
    """Best (SDO, 8-hr day) for this start time and the pay-period total."""
    nine = {d: plan_day(curves, d, start, buffer, lunch, 9, model) for d in DAYS}
    eight = {d: plan_day(curves, d, start, buffer, lunch, 8, model) for d in DAYS}
    base = sum(2 * (p["am"] + p["pm"]) for p in nine.values())
    options = []
    for sdo, short in itertools.product(DAYS, DAYS):
        total = (
            base
            - (nine[sdo]["am"] + nine[sdo]["pm"])
            + (eight[short]["pm"] - nine[short]["pm"])
        )
        options.append((total, sdo, short))
    options.sort()
    return options, nine, eight


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--buffer", type=int, default=5, help="gate <-> desk minutes")
    ap.add_argument("--lunch", type=int, default=30, help="unpaid lunch minutes")
    args = ap.parse_args()
    curves = load()
    free_am = min(d for k, c in curves.items() if k[0] == "AM" for _, d in c)
    free_pm = min(d for k, c in curves.items() if k[0] == "PM" for _, d in c)

    rows = []
    for start in range(minutes("6:30"), minutes("8:30") + 1, 5):
        options, nine, eight = evaluate(curves, start, args.buffer, args.lunch)
        total, sdo, short = options[0]
        # Same plan under the PESSIMISTIC model (bad-day exposure).
        p_opts, *_ = evaluate(curves, start, args.buffer, args.lunch, "PESSIMISTIC")
        bad = next(t for t, s, e in p_opts if (s, e) == (sdo, short))
        delay = total - 9 * (free_am + free_pm)
        rows.append((total, start, sdo, short, delay, bad))

    print(f"Assumptions: {args.lunch}-min lunch, {args.buffer}-min gate buffer each way")
    print(f"Free-flow: {free_am:.1f} min to work, {free_pm:.1f} min home\n")
    print("Start   SDO  8-hr  Pay-period  Avg/day  Traffic delay  Bad-day total")
    for total, start, sdo, short, delay, bad in sorted(rows):
        print(
            f"{clock(start):>7} {sdo:>4} {short:>5} {total:8.0f} min"
            f" {total / 9:6.1f}   {delay:6.0f} min      {bad:6.0f} min"
        )

    total, start, sdo, short, _, _ = min(rows)
    options, nine, eight = evaluate(curves, start, args.buffer, args.lunch)
    print(f"\nBest: start {clock(start)}, SDO {sdo}, 8-hour day {short}")
    print("\nSDO choice at this start time (best 8-hr day for each):")
    for d in DAYS:
        t, s, e = min(o for o in options if o[1] == d)
        print(f"  SDO {d}: {t:.0f} min/pay period (+{t - total:.0f}), 8-hr day {e}")

    print("\nDaily plan (typical / bad-day minutes):")
    for d in DAYS:
        for label, p in (("9-hr", nine[d]), ("8-hr", eight[d])):
            if label == "8-hr" and d != short:
                continue
            bad_am = interp(curves[("AM", "PESSIMISTIC", d)], p["leave_home"])
            bad_pm = interp(curves[("PM", "PESSIMISTIC", d)], p["leave_work"])
            safe = latest_departure(curves[("AM", "PESSIMISTIC", d)], start - args.buffer)
            print(
                f"  {d} {label}: leave home {clock(p['leave_home'])} ({p['am']:.0f}/{bad_am:.0f})"
                f" [bad-day-safe {clock(safe)}], leave gate {clock(p['leave_work'])}"
                f" ({p['pm']:.0f}/{bad_pm:.0f})"
            )


if __name__ == "__main__":
    main()
