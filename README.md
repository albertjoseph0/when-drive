# when-drive

Picks the 5/4-9 compressed work schedule (shift start time, SDO, and 8-hour
day) that minimizes the River Vale, NJ → Wharton, NJ (213 NJ-15) commute,
using Google Maps Routes API traffic predictions.

## Recommendation

**Start at 6:30am, take Tuesday as the SDO, and make the working Tuesday your
8-hour day.**

| | Typical | Bad day (pessimistic model) |
|---|---|---|
| Leave home | 5:43am (41 min) | 5:36am to still make the gate by 6:25 |
| Leave the gate, 9-hr days | 4:05pm (48–59 min, worst Tue) | 59–76 min |
| Leave the gate, 8-hr Tuesday | 3:05pm (50 min) | 62 min |
| Commuting per pay period | 832 min (92 min/day round trip) | 1,014 min |

- **Start time is the main lever.** 6:30 beats every later start on total time,
  time lost to traffic, and bad-day time. The closest alternative, 8:30 (SDO Thu,
  8-hr Fri), costs 38 more minutes per pay period (~16 h/yr). A 7:30 start costs
  52 more (~22 h/yr).
- **The SDO day barely matters.** Tuesday has the worst traffic in both
  directions, so dropping it saves the most, but every other day costs only 6–11
  more minutes per pay period (Fri +8, Mon +11).
- Results are unchanged with a 10- or 15-minute gate buffer.

## Assumptions

- 30-min unpaid lunch, so 9-hr days end S + 9:30 and the 8-hr day S + 8:30.
- 5 min between the gate and your desk, each way.
- The 8-hour day can fall on any weekday.
- Routes always come back as I-80 (W in the morning, E in the evening).
- Google's far-future predictions depend only on weekday and time of day: the
  same query returns identical times for October, January, and July. One
  sample week (Oct 19–23, 2026) therefore stands in for any normal week.

## Run it

```sh
export GOOGLE_MAPS_API_KEY=...   # needs Routes API enabled
python3 collect.py               # ~940 computeRoutes calls -> data/raw.jsonl
python3 analyze.py               # --buffer MIN, --lunch MIN to change assumptions
```

`collect.py` calls `computeRoutes` with `TRAFFIC_AWARE_OPTIMAL` and
`trafficModel` `BEST_GUESS` and `PESSIMISTIC`, every 5 minutes from 5:00–8:25am
(to work) and 2:45–7:00pm (home), Mon–Fri. These calls bill as the Routes
"Compute Routes Pro" SKU; one full run fits inside the monthly free usage cap.
`data/` is git-ignored.
