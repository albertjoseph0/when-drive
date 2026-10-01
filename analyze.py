"""Pick the 5/4-9 shift start time, SDO, and 8-hour day that minimize commuting.

Reads data/raw.jsonl from collect.py. For every start time S (6:30-8:30 in
5-minute steps) it plans:
  * morning: the latest departure that reaches the gate GATE_BUFFER minutes
    before S (predicted BEST_GUESS duration, linearly interpolated per minute)
  * evening: leave the gate GATE_BUFFER minutes after the shift ends, where a
    9-hour day ends at S + 9h + lunch and the 8-hour day at S + 8h + lunch
and totals one pay period: 9 workdays (each weekday twice, minus the SDO),
with the 8-hour day on any one of them.

Start times that would need leaving home before --earliest-leave on any
weekday are reported but never recommended.

Usage:
    python3 analyze.py [--buffer MIN] [--lunch MIN] [--earliest-leave H:MM]
                       [--html OUT.html]
"""

import argparse
import itertools
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path

DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri")
RAW = Path(__file__).parent / "data" / "raw.jsonl"
TEMPLATE = Path(__file__).parent / "report_template.html"
PAY_PERIODS_PER_YEAR = 26


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


def split(nine, eight, sdo, short):
    """(morning, evening) minutes per pay period for one SDO / 8-hr day pick."""
    am = sum(2 * p["am"] for p in nine.values()) - nine[sdo]["am"]
    pm = (
        sum(2 * p["pm"] for p in nine.values())
        - nine[sdo]["pm"]
        + eight[short]["pm"]
        - nine[short]["pm"]
    )
    return am, pm


def summarize(curves, start, args):
    options, nine, eight = evaluate(curves, start, args.buffer, args.lunch)
    total, sdo, short = options[0]
    # Same plan under the PESSIMISTIC model (bad-day exposure).
    p_opts, *_ = evaluate(curves, start, args.buffer, args.lunch, "PESSIMISTIC")
    bad = next(t for t, s, e in p_opts if (s, e) == (sdo, short))
    am, pm = split(nine, eight, sdo, short)
    leave = [p["leave_home"] for p in nine.values()]
    home = [p["leave_work"] + p["pm"] for p in nine.values()]
    return {
        "start": start,
        "feasible": min(leave) >= args.earliest,
        "total": total,
        "am": am,
        "pm": pm,
        "bad": bad,
        "sdo": sdo,
        "short": short,
        "leave_home": [min(leave), max(leave)],
        "leave_gate": nine["Mon"]["leave_work"],
        "home_by": [min(home), max(home)],
        "sdo_options": {
            d: min((t, e) for t, s, e in options if s == d) for d in DAYS
        },
        # per weekday: leave home, drive in, drive home (9-hr day), drive home (8-hr day)
        "days": {
            d: [nine[d]["leave_home"], nine[d]["am"], nine[d]["pm"], eight[d]["pm"]]
            for d in DAYS
        },
    }


def write_html(path, rows, curves, args, free_am, free_pm):
    data = {
        "assumptions": {
            "lunch": args.lunch,
            "buffer": args.buffer,
            "earliest_leave": args.earliest,
            "pay_periods_per_year": PAY_PERIODS_PER_YEAR,
        },
        "free_flow": {"am": round(free_am, 2), "pm": round(free_pm, 2)},
        "starts": [
            {
                **{k: v for k, v in r.items() if k != "sdo_options"},
                **{k: round(r[k], 2) for k in ("total", "am", "pm", "bad")},
                "home_by": [round(x) for x in r["home_by"]],
                "sdo_options": {
                    d: [round(t, 1), e] for d, (t, e) in r["sdo_options"].items()
                },
                "days": {d: [round(x, 1) for x in v] for d, v in r["days"].items()},
            }
            for r in rows
        ],
        "curves": {
            direction: {
                d: [[t, round(m, 2)] for t, m in curves[(direction, "BEST_GUESS", d)]]
                for d in DAYS
            }
            for direction in ("AM", "PM")
        },
    }
    html = TEMPLATE.read_text().replace("__DATA__", json.dumps(data, separators=(",", ":")))
    Path(path).write_text(html)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--buffer", type=int, default=5, help="gate <-> desk minutes")
    ap.add_argument("--lunch", type=int, default=30, help="unpaid lunch minutes")
    ap.add_argument(
        "--earliest-leave", default="6:45", help="earliest you can leave home (H:MM)"
    )
    ap.add_argument("--html", help="write the interactive chart page here")
    args = ap.parse_args()
    args.earliest = minutes(args.earliest_leave)
    curves = load()
    free_am = min(d for k, c in curves.items() if k[0] == "AM" for _, d in c)
    free_pm = min(d for k, c in curves.items() if k[0] == "PM" for _, d in c)

    rows = [summarize(curves, s, args) for s in range(minutes("6:30"), minutes("8:30") + 1)]
    feasible = [r for r in rows if r["feasible"]]
    if not feasible:
        raise SystemExit(f"No start time works when leaving after {args.earliest_leave}")
    best = min(feasible, key=lambda r: r["total"])

    print(
        f"Assumptions: {args.lunch}-min lunch, {args.buffer}-min gate buffer each way,"
        f" leave home no earlier than {clock(args.earliest)}"
    )
    print(f"Free-flow: {free_am:.1f} min to work, {free_pm:.1f} min home")
    print(f"Earliest workable start: {clock(feasible[0]['start'])}\n")
    print("Start   SDO  8-hr  Pay-period  Avg/day  Traffic delay  Bad-day total")
    for r in sorted((r for r in rows if r["start"] % 5 == 0), key=lambda r: r["total"]):
        delay = r["total"] - 9 * (free_am + free_pm)
        flag = "" if r["feasible"] else "  (leaves home too early)"
        print(
            f"{clock(r['start']):>7} {r['sdo']:>4} {r['short']:>5} {r['total']:8.0f} min"
            f" {r['total'] / 9:6.1f}   {delay:6.0f} min      {r['bad']:6.0f} min{flag}"
        )

    start, total, sdo, short = best["start"], best["total"], best["sdo"], best["short"]
    _, nine, eight = evaluate(curves, start, args.buffer, args.lunch)
    print(f"\nBest: start {clock(start)}, SDO {sdo}, 8-hour day {short}")
    print("\nSDO choice at this start time (best 8-hr day for each):")
    for d, (t, e) in best["sdo_options"].items():
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

    if args.html:
        write_html(args.html, rows, curves, args, free_am, free_pm)
        print(f"\nWrote {args.html}")


if __name__ == "__main__":
    main()
