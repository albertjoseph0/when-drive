# when-drive

Picks the 5/4-9 compressed work schedule (shift start time, SDO, and 8-hour
day) that minimizes the River Vale, NJ → Wharton, NJ (213 NJ-15) commute,
using Google Maps Routes API traffic predictions.

## Recommendation

You can't leave home before 6:45am, so the earliest shift start you can
reliably make is **7:34am**. Within 7:34–8:30:

**Start at 8:30am, take Thursday as the SDO (Tuesday ties), and make one
Friday your 8-hour day.** That is about 870 min per pay period, or 96.6 min
round trip per workday.

- **Start time barely matters inside your window.** The best start (8:30) and
  the worst (around 7:40) differ by 16 min per pay period, 1.8 min/day, or
  ~7 h/yr. Later starts make mornings worse but get you home after the evening
  peak, so the two mostly cancel. Pick by when you want to get home: about
  6:55pm with an 8:30 start, or 6:09pm with 7:34.
- **The 6:45 limit costs more than the choice within it.** A 6:30 start (leaving
  home at 5:43) would save another 38 min per pay period.
- **The SDO day barely matters.** At 8:30 the spread across weekdays is 7 min
  per pay period.

## Assumptions

- 30-min unpaid lunch, so 9-hr days end S + 9:30 and the 8-hr day S + 8:30.
- 5 min between the gate and your desk, each way.
- You can't leave home before 6:45am.
- The 8-hour day can fall on any weekday.
- Routes always come back as I-80 (W in the morning, E in the evening).

## About the predictions

For future departures, Google blends historical and live traffic. Live traffic
counts more the closer the departure is to now
([docs](https://developers.google.com/maps/documentation/routes/config_trade_offs)).
In testing, every regular weekday came back the same from October through
August, and holiday weeks were treated as normal. Thanksgiving and Christmas
Day came back traffic-free. Past dates are rejected. So the numbers describe
one typical week, not any particular season. Re-run `collect.py` in another
season to compare.

## Run it

```sh
export GOOGLE_MAPS_API_KEY=...   # needs Routes API enabled
python3 collect.py               # ~940 computeRoutes calls -> data/raw.jsonl
python3 analyze.py               # --buffer, --lunch, --earliest-leave to change assumptions
python3 analyze.py --html out.html   # interactive charts (fills report_template.html)
```

`collect.py` calls `computeRoutes` with `TRAFFIC_AWARE_OPTIMAL` and
`trafficModel` `BEST_GUESS` and `PESSIMISTIC`, every 5 minutes from 5:00–8:25am
(to work) and 2:45–7:00pm (home), Mon–Fri. These calls bill as the Routes
"Compute Routes Pro" SKU; one full run fits inside the monthly free usage cap.
`data/` is git-ignored.
