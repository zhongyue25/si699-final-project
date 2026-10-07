# EDA summary: weather, congestion pricing and Citi Bike ridership

All numbers come from `make all` and are stored in `reports/metrics.json` and `reports/tables/`.
Study window: 2024-01-01 to 2025-12-31 (731 days).

## Things that looked wrong (read first)

1. **Two months were missing locally.** `202402` and `202403` were not in the folder; both were
   downloaded from the official S3 bucket. All 24 months are now present.
2. **The local NOAA CSV was re-saved by a spreadsheet program.** Dates after 1900 are `2024/1/1`
   instead of ISO `2024-01-01`, and a naive string filter on the date silently returns only 2024.
   The parser accepts both formats. All 731 days were compared with a fresh NOAA download:
   values and flags are identical.
3. **`start_lng < -74.03` does not identify New Jersey.** 4,944 trips match, but 4,769 of them start
   at Bay Ridge, Brooklyn stations. NJ trips are identified by station id instead (`JC*`, `HB*`):
   168 trips start in NJ and 6,484 end there.
4. **Official preprocessing is incomplete.** 8,124 trips still start at depot/test/demo stations
   (`SYS*`, `Shop Morgan`, `Lab - NYC`, and `LA Metro Demo` with Los Angeles coordinates), and 118
   trips are shorter than 60 s.
5. **Station ids are not stable strings.** 502,131 trips (0.56%) carry ids with a dropped trailing
   zero (`7756.1` vs `7756.10`) or a suffix (`6569.09_`, `5348.06_old`, `6247.06_Pillar`). Without
   normalisation the station count is inflated (2,471 raw ids vs 2,291 normalised).
6. **Timestamps are local wall-clock time with no UTC offset.** All 801 trips with non-positive
   duration started on the two DST fall-back days (2024-11-03, 2025-11-02).
7. **Files are partitioned by trip end month, not start month.** 13,932 trips start in the month
   before their file; 410 start in December 2023 and are dropped. To complete December 2025 the
   pipeline also reads the `202601` archive and keeps only the 266 trips (of 1,816,391) that
   started in 2025; 229 of them survive cleaning.
8. **Ridership fell 7-10% year over year in October-December 2025**, inside and outside the zone
   alike. Q4 2025 was colder and wetter than Q4 2024 (table in section F); not investigated further.
9. **A Citi Bike fare change took effect on 2025-01-06, one day after congestion pricing began**
   (section F). The two cannot be separated by timing alone.

## A. Data collection and boundaries

| Item | Value |
|---|---|
| Monthly zip archives / CSV files | 24 / 103 (2-6 CSVs per month, 1M rows per CSV), plus `202601` (2 CSVs) for December spillover |
| Raw rows | 90,074,577 (90,074,311 from the 24 monthly files + 266 from `202601`) |
| Missing months | none |
| Header differences across 105 CSVs | none (13 identical columns) |
| Inferred-type differences | 11 CSVs infer a station id column as DOUBLE instead of VARCHAR; all columns are read as text and cast explicitly, 0 cast failures |
| Rows per file-month | min 1,888,085 (Jan 2024), max 5,287,447 (Sep 2025) |
| Trips started outside 2024-2025 | 410 (all in the last days of Dec 2023), 0 after the window |
| Trips with `start_lng < -74.03` | 4,944, of which 4,769 are Brooklyn (Bay Ridge) |
| Trips starting / ending at NJ stations | 168 / 6,484 |

Weather (USW00094728, Central Park), 731 of 731 days present:

| Field | Raw unit -> converted | Missing days | Quality-flagged | Trace days |
|---|---|---|---|---|
| TMAX, TMIN | tenths of °C -> °C and °F | 0 | 0 | - |
| PRCP | tenths of mm -> mm and inches | 0 | 0 | 79 |
| SNOW | mm | 0 | 0 | 22 |
| SNWD | mm | 1 | 0 | 8 |
| AWND | tenths of m/s -> m/s and mph | 4 (2024-01-24, 2024-01-27, 2024-06-23, 2024-06-24) | 0 | - |

No value carries a GHCN quality flag. Trace precipitation is stored as 0 with measurement flag `T`
and is treated as a dry day.

## B. Data quality

Cleaning rule, applied in this order (each trip is counted at the first step that removes it):

| Step | Removed | % of raw | Remaining |
|---|---|---|---|
| Raw | | | 90,074,577 |
| 1. Duplicate `ride_id` | 0 | 0.0000 | 90,074,577 |
| 2. Start outside 2024-2025 | 410 | 0.0005 | 90,074,167 |
| 3. Start station id/name missing | 50,106 | 0.0556 | 90,024,061 |
| 4. Depot / test / demo station at either end | 15,536 | 0.0172 | 90,008,525 |
| 5. Start station in New Jersey | 168 | 0.0002 | 90,008,357 |
| 6. Duration <= 0 (DST artefact) | 800 | 0.0009 | 90,007,557 |
| 7. Duration < 60 s | 1 | 0.0000 | 90,007,556 |
| 8. Duration > 24 h | 19,997 | 0.0222 | 89,987,559 |

Total removed: 87,018 trips (0.097%). Clean table: **89,987,559 trips**.

Non-exclusive counts on the raw table:

- Missing end station id: 252,958 (0.28%); missing end coordinates: 252,504. These are 92% e-bikes.
  Only 19,425 of them exceed 24 h; 123,192 are under one hour, so "missing end" mostly does not
  mean a lost bike.
- Duration > 24 h: 20,039, of which 19,969 fall between 24 and 25 h and 19,425 have no end
  station. This is a system cap, not real riding (Figure 3).
- Missing start station: 50,106, all e-bikes, start coordinates also missing.
- Duration quantiles: p1 85 s, median 537 s (9 min), p95 33 min, p99 61 min, p99.9 4.4 h.

Decision on missing end stations: **keep and flag** (`has_end_station`). Ridership is counted at
trip start, and 215,290 such trips remain after the other filters. They must be excluded from any
origin-destination or duration analysis.

## C. Scale and categories

| | 2024 | 2025 | Total |
|---|---|---|---|
| Clean trips | 44,254,988 | 45,732,571 | 89,987,559 |
| Member share | 80.7% | 82.6% | 81.6% |
| E-bike share | 66.1% | 70.5% | 68.3% |

- Monthly trips range from 1.89M (Jan 2024) to 5.28M (Sep 2025), a 2.8x seasonal swing.
- Member share by month ranges from 77% (summer) to 90% (winter); casual riding is far more
  seasonal.
- E-bike share rises from 64% (Jan 2024) to 73% (Dec 2025). Only `classic_bike` and
  `electric_bike` appear.
- Stations with at least one start per month: 2,125 (Jan 2024) to 2,183 (Dec 2025). 2,291 distinct
  station ids overall; 1,897 are active in all 24 months; 85 first appear in 2025.
- Trips per station: min 22, median 17,916, max 330,225. The top 334 stations (15%) generate half
  of all trips. All top-10 stations are inside the congestion zone; the largest is W 21 St & 6 Ave.
- Round trips (same start and end station): 2.1%.

Example rows (`reports/tables/example_trips.csv`):

| | Rider / bike | Start -> end | Started | Duration |
|---|---|---|---|---|
| Typical | member, electric | 62 St & 34 Ave -> 29 St & 40 Ave | Tue 2025-05-20 08:07 | 9 min |
| Very long | casual, electric | Paul Ave & W 205 St -> Jerome Ave & Bedford Park Blvd E | 2024-03-14 16:17 | 23 h 59 min |
| Round trip | casual, electric | 7 Ave & Central Park South -> same | Sun 2025-04-27 10:54 | 45 min |

## D. Temporal patterns

- Weekday members: two peaks, 08:00 (about 8.7k trips/hour) and 17:00-18:00 (about 10.7k).
  Weekday casual riders: a single peak at 17:00. Weekends: both groups have one broad afternoon
  peak (14:00-15:00) (Figure 2).
- Daily trips: min 12,857 (2025-12-27, 2.6 in of snow), median 130,857, max 201,875 (2025-09-26).
  Mean weekday 126,730 vs weekend 113,979.
- The five lowest days are snow days, a 3.66 in rain day (2024-03-23) or Christmas, which shows that
  single-day weather shocks are large relative to seasonal variation (Figure 1).

## E. Weather

| Quantity | Value |
|---|---|
| TMAX (°F) min / median / max | 19.2 / 64.9 / 99.0 |
| Rain days (PRCP > 0) | 246 of 731 (125 in 2024, 121 in 2025) |
| Heavy rain days (PRCP >= 0.5 in) | 58 (22 on weekends) |
| Trace-only days (counted as dry) | 79 |
| Snow days (SNOW > 0) / with >= 1 in | 22 / 10 |
| Days with snow on the ground | 41 |
| Days with TMAX >= 90 °F / <= 32 °F | 25 / 25 |
| Federal holidays | 22 |

Median daily trips relative to the dry-day median of the same month:

| | Member | Casual |
|---|---|---|
| Light rain (n = 188) | 0.90 | 0.84 |
| Heavy rain (n = 58) | 0.66 | 0.59 |

Preliminary regression, `log(daily trips) ~ TMAX + TMAX² + rain + weekday + month`, fit separately,
n = 731, Newey-West standard errors (7 lags). **Preliminary, not final.** Percentage effects are
`exp(beta) - 1`, applied to the point estimate and to both interval endpoints.

| Term | Member: coef [95% CI] | Casual: coef [95% CI] |
|---|---|---|
| TMAX (°F) | 0.0374 [0.0270, 0.0479] | 0.0755 [0.0627, 0.0884] |
| TMAX² | -0.000193 [-0.000267, -0.000120] | -0.000377 [-0.000471, -0.000283] |
| Rain day | -0.211 [-0.250, -0.173] | -0.321 [-0.366, -0.276] |
| Rain day, % change | -19% [-22, -16] | -27% [-31, -24] |
| R² | 0.74 | 0.90 |

The temperature slope for casual riders is about twice the member slope, and the rain penalty is
larger. The quadratic term is negative for both, but the implied turning point (97 °F for members,
100 °F for casual) is at the edge of the observed range: the data show flattening above about
80 °F, not a clear hot-weather decline. The full coefficient table is in
`reports/tables/preliminary_regression.csv`. The daily table (date, trips by rider type, weekday,
holiday flag, weather fields) is `reports/tables/daily_trips_weather.csv`.

### E-bike vs classic split

Overall e-bike share: 67.2% of member trips, 73.5% of casual trips.

Same preliminary model fit to each rider type × bike type group (n = 731 days each, Newey-West
7 lags; percentage effects are `exp(beta) - 1`). Table: `reports/tables/regression_by_rider_and_bike.csv`.

| Group | Rain day, % change [95% CI] | TMAX coef | TMAX² coef | Implied % per +1 °F at 50 °F / 80 °F | R² |
|---|---|---|---|---|---|
| Member, electric | -17.8% [-21.0, -14.4] | 0.0326 | -0.000163 | +1.6% / +0.7% | 0.72 |
| Member, classic | -21.7% [-24.8, -18.5] | 0.0471 | -0.000252 | +2.2% / +0.7% | 0.74 |
| Casual, electric | -25.4% [-28.5, -22.2] | 0.0685 | -0.000340 | +3.5% / +1.4% | 0.90 |
| Casual, classic | -34.0% [-37.7, -30.0] | 0.1009 | -0.000518 | +5.0% / +1.8% | 0.88 |

Within each rider type, classic-bike trips respond more to rain and to temperature than e-bike
trips. The gap is clear for casual riders (intervals do not overlap) and small for members
(intervals overlap). Rider type separates the groups more than bike type does.

E-bike share of trips by weather condition (`reports/tables/ebike_share_by_condition.csv`).
"Within month" is the mean daily share minus that calendar month's mean share, in percentage
points, which removes the upward trend and seasonality:

| Condition | Days | Member: share | Member: within month | Casual: share | Casual: within month |
|---|---|---|---|---|---|
| Dry | 485 | 66.9% | -0.4 pp | 73.1% | -0.7 pp |
| Rain | 246 | 67.9% | +0.7 pp | 74.8% | +1.3 pp |
| Heavy rain | 58 | 68.5% | +1.6 pp | 74.2% | +2.5 pp |
| TMAX 60-75 °F | 176 | 66.8% | -0.3 pp | 73.1% | -0.6 pp |
| TMAX >= 85 °F | 76 | 67.5% | +0.4 pp | 73.6% | +0.8 pp |

E-bike share is 1-2 points higher on rain days and about 1 point higher on hot days. These shifts
are small next to the 9-point rise over the window.

Caveats:

- `rideable_type` records the bike that was taken, not the bike the rider wanted. Share depends on
  what is docked nearby, and on low-demand (rainy) days e-bikes are less likely to be depleted, so
  a higher e-bike share in rain may reflect availability rather than preference.
- E-bike share rises from 64% to 73% across the window, so raw shares mix weather with trend.
  Use the within-month columns. The hot vs mild comparison is the weakest: 85 °F days and
  60-75 °F days rarely fall in the same month (in 2024 only June and August have both).
- E-bike per-minute fees changed three times in the window (section F).

No figure was added for this split: the share differences are 1-2 points and the regression
contrast fits in one table.

## F. Congestion pricing (feasibility only, no causal claim)

Zone definition: the official MTA Central Business District geofence polygon (data.ny.gov), which
follows 60th St and the shoreline. A station is "inside" if its median start coordinate lies in
the polygon or within 50 m of its boundary. The buffer captures 14 docks on the waterfront edge
and on 60th St itself. 82 stations lie within 150 m of the boundary, so results near 60th St are
sensitive to this choice.

| | Inside | Outside |
|---|---|---|
| Station ids (ever active) | 405 | 1,886 |
| Stations active in 2024 / 2025 | 397 / 388 | 1,809 / 1,847 |
| Stations active all 24 months | 324 | 1,573 |
| Trips 2024 | 21,334,281 | 22,920,707 |
| Trips 2025 | 22,130,667 | 23,601,904 |
| Change 2024 -> 2025, all stations | +3.7% | +3.0% |
| Change, stations active all 24 months | +1.1% | +2.7% |

Sensitivity to the boundary buffer (`reports/tables/zone_buffer_sensitivity.csv`). The 50 m buffer
is the main specification.

| Buffer | Stations inside | 2024 -> 2025, all stations: inside / outside / gap | Stations active all 24 months: inside / outside / gap |
|---|---|---|---|
| 0 m (polygon only) | 391 | +3.74% / +2.99% / +0.75 pp | +1.38% / +2.46% / -1.08 pp |
| 50 m (main) | 405 | +3.73% / +2.97% / +0.76 pp | +1.12% / +2.73% / -1.61 pp |
| 150 m | 410 | +3.90% / +2.81% / +1.10 pp | +1.10% / +2.75% / -1.66 pp |

The buffer moves the gap by at most 0.6 points. The choice of station panel moves it by about 2
points and changes its sign, so the panel definition matters more than the boundary.

The zone holds 18% of stations but 48% of trip starts in both years. The inside-outside difference
changes sign depending on whether the station set is held fixed (Figure 6), so any estimate depends
on how station churn is handled. Month-level year-over-year changes move together in both groups
(from +19% in March to -10% in December), which points to citywide drivers such as weather.

Citi Bike fare changes inside the study window (as reported by 6sqft, 7 January 2025; not
checked against Citi Bike's own announcements):

| Date | Change |
|---|---|
| January 2024 | Annual membership, unlock fee and e-bike fee increases |
| July 2024 | E-bike fee increase |
| 6 January 2025 | E-bike per-minute fee 24¢ -> 25¢ (members), 36¢ -> 38¢ (non-members) |
| 3 February 2025 | Single ride $4.99, day pass $25 |

**The 6 January 2025 fare increase starts one day after congestion pricing (5 January 2025).** A
before/after comparison cannot attribute a change to congestion pricing rather than to the fare
change. The fare change applies citywide, so it should affect inside and outside stations alike
unless e-bike share or rider mix differs by zone, which must be checked.

Other confounds to state: station additions and relocations (ids change when a dock moves), rising
e-bike share, year-to-year weather differences, and only one pre-period year.

Q4 2024 vs Q4 2025 (October-December), for the late-2025 decline. Descriptive only
(`reports/tables/q4_comparison.csv`):

| | Q4 2024 | Q4 2025 | Change |
|---|---|---|---|
| Trips | 11,158,901 | 10,230,570 | -8.3% |
| Member trips | 9,260,309 | 8,707,193 | -6.0% |
| Casual trips | 1,898,592 | 1,523,377 | -19.8% |
| Mean TMAX (°F) | 56.8 | 52.7 | -4.1 |
| Rain days | 25 | 32 | +7 |
| Heavy rain days | 6 | 7 | +1 |
| Snow days | 2 | 3 | +1 |
| Mean monthly active stations | 2,134 | 2,175 | +41 |
| E-bike share | 67.9% | 71.4% | +3.5 pp |

Q4 2025 was 4 °F colder with 7 more rain days (October alone: 9 rain days vs 1), while station
count and e-bike share both rose. The decline is larger for casual riders, the more
weather-sensitive group. This is consistent with weather explaining part of the drop; it is not a
test, and the February 2025 pass price change is also in effect by then.

## Findings that matter for later analysis

1. **Statistical power is adequate for temperature and rain, thin for snow and heat.** 246 rain
   days and 58 heavy-rain days support separate member/casual estimates. Only 22 snow days (10 with
   at least 1 inch) and 25 days at or above 90 °F: snow and extreme-heat effects will have wide
   intervals, and a hot-weather decline may not be identifiable.
2. **Almost nothing is lost to cleaning (0.097%), but station ids need normalising** before any
   station-level work, and trips are assigned to days by local start time with no time zone.
3. **Members and casual riders differ in both level and sensitivity.** Casual trips are 18% of the
   total, but their temperature slope is about double and their rain penalty about 8 percentage
   points larger. Modelling the two groups separately is justified.
4. **Bike type matters less than rider type, but is not ignorable.** Classic trips are more
   weather-sensitive than e-bike trips within each rider group, so the rising e-bike share could
   by itself dampen the measured weather response over time. Bike type reflects availability, not
   choice.
5. **System composition shifts within the window.** E-bike share rises from 66% (2024) to 70% (2025) and member
   share from 81% to 83%; the active station count grows only 2.7%, but 394 of 2,291
   station ids are not active in all 24 months. Trend comparisons need a fixed station panel.
6. **The congestion-pricing extension is feasible but fragile.** There is one pre-period year, the
   inside-outside gap is about 1-2 points and flips sign with the station panel, a fare increase
   starts one day after congestion pricing, and a citywide decline appears in late 2025.

## Figures

| File | Section | Shows |
|---|---|---|
| `figures/fig01_daily_trips.png` | D | Daily trips by rider type with 7-day mean |
| `figures/fig02_hourly_profile.png` | D | Hourly profile, weekday vs weekend, by rider type |
| `figures/fig03_duration_tail.png` | B | Duration distribution and the 24 h cap |
| `figures/fig04_system_confounds.png` | C | Active stations, e-bike share, member share by month |
| `figures/fig05_weather_response.png` | E | Trips vs TMAX; rain vs dry days |
| `figures/fig06_congestion_zone.png` | F | Indexed monthly trips and year-over-year change by zone |
| `figures/extra_station_zone_map.png` | F | Check of the zone classification |
| `figures/extra_station_long_tail.png` | C | Trips per station, ranked |

## Draft proposal text

### §2 Dataset summary

We combine 90 million Citi Bike trips started in New York City between January 2024 and December
2025 with daily weather observations from NOAA's Central Park station. Each trip records start and
end time, start and end station, bike type and whether the rider is a member or a casual user.

### §3 Data collection

Citi Bike publishes every trip as monthly CSV archives on a public S3 bucket; we use the 24 New
York City archives for 2024-2025 (103 CSV files, 90,074,311 rows), plus 266 trips from the January 2026
archive that started in December 2025, and exclude the separate Jersey
City files. The records are generated automatically when a bike is undocked and docked, so the
data are a census of rentals rather than a sample. The operator removes staff trips, trips at test
stations and trips shorter than 60 seconds before release. We found that this filtering is
incomplete (8,124 trips start at depot or demo stations) and that files are organised by the month
a trip ended, so 410 trips in the 2024 files started in December 2023 and were dropped. Riders are not identified: there
is no rider id, so we observe trips, not people, and "member" versus "casual" is the only rider
attribute. Timestamps are local time without a UTC offset.

Weather comes from NOAA's Global Historical Climatology Network Daily (GHCN-Daily) for station
USW00094728 (NY City Central Park): daily maximum and minimum temperature, precipitation, snowfall,
snow depth and average wind speed. All 731 days are present, no value carries a quality flag, and
only wind speed has gaps (4 days). We converted the native units (tenths of °C, tenths of mm,
tenths of m/s) to °F, inches and mph. One station represents the whole service area, and daily
totals cannot say whether rain fell during commuting hours. Congestion pricing is not recorded in
either dataset; we add its start date (5 January 2025) and classify stations with the MTA's
published zone boundary.

### §4 Data description

After removing 87,018 trips (0.097%) with no start station, a depot or New Jersey start, a start
outside the window, a non-positive duration or a duration above 24 hours, 89,987,559 trips remain:
44.3 million in 2024 and 45.7 million in 2025. There are no duplicate ride ids. Members account
for 81.6% of trips and e-bikes for 68.3%. The median trip lasts 9 minutes and 99% last under 61
minutes. About 20,000 trips sit at an artificial 24-25 hour cap, nearly all without an end
station, which we treat as unreturned bikes. A further 215,290 trips lack an end station but
have plausible durations; we keep them because our outcome is trip starts. Trips start at 2,291
stations after normalising inconsistent station ids, and demand is concentrated: 15% of stations
produce half of all trips.

Ridership is strongly seasonal, from 1.9 million trips in January 2024 to 5.3 million in September
2025. Members show weekday peaks at 08:00 and 17:00-18:00, while casual riders peak in the
afternoon, which supports reading the two groups as commute-like and leisure-like. The weather
record contains 246 days with rain, 58 with at least 0.5 inches, 22 with snowfall and 25 with a
maximum of 90 °F or more, so rain and temperature effects are well supported while snow and
extreme heat are not. **E-bikes.** E-bikes carry 68.3% of trips (67.2% for members, 73.5% for casual riders), and
their share rose from 64% in January 2024 to 73% in December 2025. In a preliminary model fit
separately by rider and bike type, a rain day lowers classic-bike trips more than e-bike trips:
-22% vs -18% for members and -34% vs -25% for casual riders, with only the casual gap clearly
separated. Within the same calendar month, the e-bike share is 1-2 percentage points higher on
rain days and under 1 point higher on days at or above 85 °F. The field records the bike that was
taken rather than the rider's preference, so these differences may reflect which bikes were
available.

Three changes inside the window can confound trends: the e-bike share rose
from 64% to 73%, the member share rose from 80.7% to 82.6%, and 17% of station ids were not active
in every month.

### §5 Proposed analyses

1. **Weather response.** Model daily trips by rider type as a function of temperature (allowing a
   non-linear shape), precipitation, snow and wind, with weekday, holiday and seasonal controls.
   A preliminary log-linear model suggests rain days reduce member trips by about 19% and casual
   trips by about 27%, and that the temperature slope for casual riders is about twice as steep.
2. **Member versus casual difference.** Test whether weather coefficients differ between the two
   groups using a pooled model with rider-type interactions, and check robustness to heavy-rain
   thresholds and to weekday-only and weekend-only samples.
3. **Finer time resolution.** Aggregate trips to the hour to separate commute-hour from off-peak
   responses, since daily precipitation totals hide timing.
4. **Congestion pricing (extension).** Compare monthly trip starts inside and outside the zone
   before and after 5 January 2025 on a fixed panel of stations active throughout, controlling for
   weather and e-bike share. With one pre-period year and a difference of 1-2 percentage points
   that depends on the station panel, and a Citi Bike fare increase on 6 January 2025, we will
   present this as descriptive evidence.

## Sources to cite

- Citi Bike / Lyft. *Citi Bike System Data.* https://citibikenyc.com/system-data
  (trip files: https://s3.amazonaws.com/tripdata/index.html; the Data License Agreement is linked
  from that page)
- Menne, M. J., Durre, I., Vose, R. S., Gleason, B. E., & Houston, T. G. (2012). An overview of the
  Global Historical Climatology Network-Daily database. *Journal of Atmospheric and Oceanic
  Technology*, 29(7), 897-910. https://doi.org/10.1175/JTECH-D-11-00103.1
- NOAA National Centers for Environmental Information. *Global Historical Climatology Network
  Daily (GHCN-Daily), Version 3*, station USW00094728. https://doi.org/10.7289/V5D21VHZ
- Metropolitan Transportation Authority. *MTA Central Business District Geofence.* NY Open Data.
  https://data.ny.gov/d/srxy-5nxn
- 6sqft (7 January 2025). Article on Citi Bike fare increases (add title and URL).
- Metropolitan Transportation Authority. *Congestion Relief Zone* (start date and boundary).
  https://congestionreliefzone.mta.info
- Tools: DuckDB (https://duckdb.org), statsmodels (Seabold & Perktold, 2010), Python `holidays`.
