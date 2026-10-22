# Checkpoint 1 summary: weather, e-bikes and Citi Bike ridership (2024-2025)

Research question: how does weather affect NYC Citi Bike ridership, and do e-bikes change that
response?

Everything below is produced by `make checkpoint1` (about 4 minutes on a laptop, after `make tables`).
Scripts: `scripts/build_panel.py`, `scripts/cp1_finding1.py`, `cp1_finding2.py`, `cp1_finding3.py`,
`cp1_availability.py`, shared code in `scripts/cp1_common.py`. Tables are in
`reports/tables/checkpoint1/`, figures in `figures/checkpoint1/`. Temperature bins are shown in
both °C and °F. One cleaning rule was added after the first draft (depot stations by name, see
flag 7); all numbers below are from the rerun.

## Things that look wrong or need a decision (read first)

1. **No paper PDF.** There is no `references/` folder, so the paper's temperature variable, reference
   bin and fixed effects could not be checked. I used the defaults from the brief (daily TMAX, 2 °C
   bins, reference 20-22 °C). The abstract does not say whether "5.6 / 7.7 percentage points" is a
   difference in % effects or in log points, so I report both.
2. **The paper's cold bin (−2 to 0 °C / 28.4 to 32 °F) cannot be formed.** It has only 12 days in
   2024-25. With the ≥ 15 days rule it merges with the colder days into `< 0 °C` (`< 32 °F`; 20 days,
   TMAX −7.1 to −0.5 °C / 19.2 to 31.1 °F). The paper's hot bin (30-32 °C / 86 to 89.6 °F, 41 days)
   is available as is.
3. **Hot days are not "losses" here.** Relative to 20-22 °C, neither bike type loses trips at
   30-32 °C (classic +3.3%, e-bike +9.5%). Trips peak at 28-30 °C. The e-bike *advantage* at 30-32 °C
   matches the paper, but the paper's framing ("smaller losses") does not hold for daily TMAX in
   2024-25.
4. **`log(trips + 1)` OLS reverses the cold-weather result.** In the stacked model it gives an
   e-bike *disadvantage* below 2 °C (−13% at < 0 °C), against +11% from Poisson. 21% of panel cells
   are zero and classic cells are small (median 6 trips per station-day), so log(y+1) effects depend
   on the count scale (Chen & Roth 2024). I treat Poisson as the main estimator and do not use the
   OLS numbers. Do not quote the OLS numbers as a robustness check that "agrees".
5. **The Finding 2 specification as written cannot give the four group rain effects.** With date
   fixed effects the rain main effect is absorbed, so only *differences* between groups are
   identified. Group levels come from a separate per-group model (the Finding 1(a) specification);
   the contrasts come from the stacked date-FE model.
6. **The Finding 1(a) formula has no holiday term.** I kept it as specified. Adding a holiday dummy
   moves the classic 30-32 °C effect from +3.3% to +5.8% (July 4 falls in a hot bin). The stacked
   contrasts are not affected (date FE absorbs holidays).
7. **Fixed: one depot-like station had survived cleaning.** `1234.56` "Morgan HCT Charging" has a
   normal-looking id, so the id-based depot rule missed it. A new cleaning step (4b) now drops trips
   that start or end at a station whose name contains the whole word Charging, Depot, Lab, Shop,
   Demo or Test. It drops **1,994 trips** (0.0022% of raw; 862 start at the station, the rest end
   there). Morgan HCT Charging is the only station it adds: every other match (`Shop Morgan`,
   `Lab - NYC`, `LA Metro Demo`) was already removed by the id rule. Whole-word matching matters:
   a plain substring match on "Lab" would also have removed `Union Ave & Wallabout St` and
   `Wallabout St & Kent Ave` (about 34,600 trip starts). Clean trips: 89,987,559 → 89,985,565;
   stations: 2,291 → 2,290. The main panel loses 987 trips (trips that ended at the depot); no
   estimate in this document moves by more than 0.003 points. `summary.md` has been updated to
   the new counts.
8. **27,019 main-panel station-days (1.9%) have zero trips of any type.** These are probably dock
   closures or outages, counted as zero demand. Not removed.
9. **E-bike trips fall *more* than classic trips on snow days** (−5.9% [−11.5, 0.0]), but this
   rests on only **22 snow days** (10 with ≥ 1 in; 8 in 2024, 14 in 2025, 11 of them in January-
   February 2025). It is not robust: with bike-specific month controls it shrinks to −1.6% [−5.0,
   +1.9]. It could be operational (e-bikes withdrawn or not charged in snow); not verified. See
   Finding 1 open issues.
10. **Rain effects here are smaller than in `summary.md`** (for example casual classic −25% here vs
    −34% there). The EDA used a log-OLS daily model with a quadratic in °F; this uses Poisson with
    temperature bins. Do not mix numbers from the two documents.
11. **Bike-specific calendar controls shrink the confidence intervals a lot** (for example the hot
    contrast goes from [−0.3, +11.9] to [+2.2, +8.6]). Much of the noise in the main specification is
    month-to-month movement in the e-bike share (fleet size, the January 2025 e-bike fee change).
    The main specification does not control for this; the stress test does.

## Data prep

| Item | Value |
|---|---|
| Panel | station × date × bike type (electric/classic) × rider type (member/casual), outcome = trip starts, zeros included |
| Main sample | **1,897 stations** with ≥ 1 start in each of the 24 months, all 731 days (balanced): 5,546,828 cells, 78,690,099 trips (87.4% of clean trips) |
| Full sample (robustness) | 2,290 stations, each observed from its first to its last trip date: 6,270,988 cells, all 89,985,565 clean trips |
| Zero cells (main) | 21.0% overall; member classic 17.3%, member e-bike 4.2%, casual classic 46.5%, casual e-bike 16.2% |
| Weather | Central Park (USW00094728): TMAX (°C, also shown in °F), rain = PRCP > 0 (trace counts as dry), snow = SNOW > 0, wind = AWND (m/s; missing on 4 days, which drop out of models with wind) |
| Calendar | weekday, 22 federal holidays (`holidays.US`), year-month |
| Rain days | > 0 in: 246; ≥ 0.1 in: 145; ≥ 0.5 in: 58. Snow days: 22 |

Temperature bins: 2 °C bins on daily TMAX, tails merged inward until every bin has ≥ 15 days.
Reference bin 20-22 °C / 68-71.6 °F (the brief's default; see flag 1). Bin edges in °F are exact
conversions of the °C edges (`temperature_bins.csv`).

| Bin (°C) | Bin (°F) | Days | | Bin (°C) | Bin (°F) | Days |
|---|---|---|---|---|---|---|
| < 0 | < 32 | 20 | | **20-22** | **68-71.6** | **41** |
| 0-2 | 32-35.6 | 28 | | 22-24 | 71.6-75.2 | 62 |
| 2-4 | 35.6-39.2 | 30 | | 24-26 | 75.2-78.8 | 32 |
| 4-6 | 39.2-42.8 | 34 | | 26-28 | 78.8-82.4 | 76 |
| 6-8 | 42.8-46.4 | 37 | | 28-30 | 82.4-86 | 55 |
| 8-10 | 46.4-50 | 36 | | 30-32 | 86-89.6 | 41 |
| 10-12 | 50-53.6 | 47 | | ≥ 32 | ≥ 89.6 | 35 |
| 12-14 | 53.6-57.2 | 40 | | | | |
| 14-16 | 57.2-60.8 | 44 | | | | |
| 16-18 | 60.8-64.4 | 47 | | | | |
| 18-20 | 64.4-68 | 26 | | | | |

Estimation: pyfixest `fepois` (Poisson pseudo-maximum likelihood with fixed effects), SEs clustered
by date. % effects are exp(β) − 1, applied to the estimate and both CI ends.

**Shortcut used for Findings 2-3, verified:** on a balanced panel where the regressors vary only by
group × date, Poisson with station fixed effects gives *identical* coefficients and date-clustered SEs
to Poisson on daily group totals (the station effects collapse into a group effect). I checked this
twice: the Finding 1(b) stacked model and a station-level rain model with all four groups (5.5M
rows) match the daily-totals fit to 4-5 decimals (`f2_station_level_equivalence_check.csv`). This
lets the 60-regressor Finding 2 model run in seconds instead of needing more than 8 GB of RAM. The
small-sample correction is set to G/(G−1) only, so the two fits also match on SEs.

---

## Finding 1: replicating Zheng et al. (2025) on 2024-2025

**Goal.** Check whether the e-bike temperature advantage reported for 2023 (5.6 points at 30-32 °C,
7.7 points at −2 to 0 °C) holds in 2024-25.

**Method.** (a) Separate Poisson per bike type, station × date (main sample):
`trips ~ temp_bins + rain + snow + wind | station + year_month + weekday`.
(b) Preferred: stack both bike types,
`trips ~ ebike × temp_bins + ebike × rain + ebike × snow | station×bike + date`. The date FE
absorbs everything common to a day; `ebike × bin` measures how much the e-bike response differs from
the classic response, as a ratio: exp(β) − 1 = (1 + e-bike effect) / (1 + classic effect) − 1.

**Output** (`f1_table_bins_and_contrasts.csv`, Figure 1):

| TMAX bin | Days | Classic vs 20-22 °C (68-71.6 °F) | E-bike vs 20-22 °C | Gap (pp, model a) | E-bike × bin, model b |
|---|---|---|---|---|---|
| < 0 °C (< 32 °F) | 20 | −59.7% [−65.5, −53.0] | −53.7% [−59.8, −46.6] | +6.1 | **+11.1% [+4.3, +18.3]** |
| 0-2 °C (32-35.6 °F) | 28 | −50.5% [−57.6, −42.3] | −43.3% [−50.8, −34.6] | +7.3 | **+19.2% [+13.2, +25.5]** |
| 2-4 °C (35.6-39.2 °F) | 30 | −48.1% | −40.9% | +7.1 | +9.5% [+2.5, +17.0] |
| 10-12 °C (50-53.6 °F) | 47 | −30.9% | −22.3% | +8.6 | +10.0% [+3.8, +16.7] |
| 28-30 °C (82.4-86 °F) | 55 | +11.8% | +13.7% | +1.9 | +2.8% [−2.7, +8.5] |
| 30-32 °C (86-89.6 °F) | 41 | +3.3% [−3.1, +10.0] | +9.5% [+3.9, +15.4] | +6.2 | **+5.6% [−0.3, +11.9]** (p = 0.06) |
| ≥ 32 °C (≥ 89.6 °F) | 35 | +1.5% [−5.3, +8.7] | +11.5% [+5.6, +17.6] | +10.0 | +5.9% [−0.2, +12.3] (p = 0.06) |
| Rain day | 246 | −18.7% [−21.1, −16.1] | −15.2% [−17.3, −12.9] | +3.5 | +4.5% [+2.1, +7.0] |
| Snow day | 22 | −17.3% [−29.2, −3.5] | −19.1% [−29.6, −7.0] | −1.7 | −5.9% [−11.5, 0.0] |

**Interpretation.** Direction matches the paper in both tails. Size also matches. At 30-32 °C the
gap is 6.2 points (separate models) and the contrast is +5.6% / 5.5 log points (paper: 5.6). In the
cold the gap is 6-7 points (paper: 7.7 at −2 to 0 °C). The stacked contrast is larger at 0-2 °C
(+19%) than in the merged `< 0 °C` bin (+11%). This fits the paper's finding that the advantage
weakens below −2 °C, since 8 of the 20 days in that bin are below −2 °C (28.4 °F). Two differences from
the paper: (i) at 30-32 °C classic trips do not fall below the reference (flag 3), so the advantage
is e-bikes *rising* rather than *falling less*. (ii) The cold advantage is not limited to extreme
cold. E-bikes lose 5-9 points less than classic bikes in every bin below 18 °C (64.4 °F). The hot contrast
alone is borderline in the main specification (p = 0.06).

**Stress tests** (`f1b_robustness_key_contrasts.csv`):

| Specification | < 0 °C (< 32 °F) | 0-2 °C (32-35.6 °F) | 30-32 °C (86-89.6 °F) | Rain |
|---|---|---|---|---|
| Main | +11.1% [+4.3, +18.3] | +19.2% [+13.2, +25.5] | +5.6% [−0.3, +11.9] | +4.5% [+2.1, +7.0] |
| Cluster by week | +11.1% [+1.5, +21.5] | +19.2% [+12.4, +26.4] | +5.6% [−1.6, +13.3] | +4.5% [+2.0, +7.2] |
| + e-bike × wind | +10.3% [+3.3, +17.7] | +18.3% [+12.1, +24.9] | +6.1% [+0.1, +12.4] | +4.6% [+2.1, +7.1] |
| + bike × month, bike × weekday FE, e-bike × holiday | +14.8% [+10.4, +19.4] | +13.6% [+9.4, +17.9] | +5.3% [+2.2, +8.6] | +4.2% [+3.0, +5.4] |
| Full station sample | +11.3% [+4.7, +18.4] | +19.1% [+13.3, +25.3] | +5.5% [−0.2, +11.6] | +4.5% [+2.1, +6.9] |
| Daily totals (equivalence check) | identical | identical | identical | identical |
| log(trips+1) OLS (rejected, flag 4) | −13.2% | −5.8% | +9.4% | +1.9% |

**Open issues.** The paper's temperature measure (daily vs hourly, max vs mean) is unknown; hourly
temperature at trip time would be a closer match. One weather station represents the city. Only 35
days are at or above 32 °C (89.6 °F), so extreme heat is thinly identified.

- **Snow (e-bike × snow = −5.9% [−11.5, 0.0]) rests on 22 snow days** (`f1_snow_days.csv`): 10 with
  ≥ 1 in, 8 in 2024 and 14 in 2025, 11 on weekends, all with TMAX below 6 °C (42.8 °F): 6 below
  0 °C, 7 at 0-2 °C, 7 at 2-4 °C, 2 at 4-6 °C. Every snow day is also a rain day (PRCP > 0), so the
  snow term is an extra effect on top of rain. 11 of the 22 fall in January-February 2025, and the
  estimate shrinks to −1.6% [−5.0, +1.9] with bike-specific month and weekday controls. So it may
  reflect e-bike-specific conditions in those months rather than snow. Treat it as unresolved;
  checking Citi Bike's e-bike operations on snow days (or the station-status archive) would settle
  it.

---

## Finding 2: rain × bike type × rider type (extension)

**Goal.** Test whether the e-bike rain advantage differs between members (commute-like) and casual
riders (leisure-like).

**Method.** Levels: per-group Poisson with the Finding 1(a) specification. Contrasts: stacked model
`trips ~ ebike × casual × (rain + temp_bins) | station×bike×rider + date`, fit on daily group totals
(identical to station level, see Data prep). Tests: (i) e-bike vs classic within each rider type =
`ebike:rain` (members) and `ebike:rain + ebike:casual:rain` (casual); (ii) `ebike:casual:rain`.

**Output** (`f2_rain_levels_by_group.csv`, `f2_rain_contrasts.csv`, Figure 2):

| Group | Rain day (PRCP > 0) | PRCP ≥ 0.1 in | PRCP ≥ 0.5 in |
|---|---|---|---|
| Member, classic | −17.3% [−19.8, −14.8] | −23.6% | −31.6% |
| Member, e-bike | −13.9% [−16.2, −11.7] | −19.7% | −28.2% |
| Casual, classic | −25.4% [−28.9, −21.7] | −33.5% | −35.3% |
| Casual, e-bike | −19.8% [−22.2, −17.3] | −26.3% | −32.6% |

| Contrast (stacked, date FE) | Estimate | p |
|---|---|---|
| (i) E-bike vs classic, members | +4.1% [+1.8, +6.5] | < 0.001 |
| (i) E-bike vs classic, casual | +7.3% [+2.3, +12.5] | 0.004 |
| (ii) Casual minus member e-bike advantage | +3.0% [−1.4, +7.6] | 0.18 |

**Interpretation.** In both rider groups, e-bike trips fall less on rain days than classic trips.
The advantage is about 4% for members and 7% for casual riders. Rider type matters more than bike
type: casual riders lose 6-9% more than members whichever bike they ride. The point estimate says the
e-bike advantage is larger for casual riders, but the difference is not statistically clear in the
main specification and it changes sign across stress tests. The within-month e-bike share is 1-2
points higher on rain days (members +0.7 pp vs −0.4 pp on dry days; casual +1.3 vs −0.7),
consistent with the contrasts.

**Stress tests** (casual minus member advantage, test ii): PRCP ≥ 0.1 in +5.1% [+0.4, +10.0];
PRCP ≥ 0.5 in −4.1% [−12.7, +5.3]; weekdays only +3.9% [+2.1, +5.8]; weekends only −0.2% [−6.9,
+6.9]; group-specific calendar FE +4.0% [+1.7, +6.4]; + group × snow +2.8% [−1.6, +7.5]; cluster by
week +3.0% [−1.6, +7.8]; full sample +2.9% [−1.5, +7.5]. Test (i) stays positive in every variant
for members (+3.8 to +5.7%). For casual riders it loses significance on heavy-rain days (+1.3%
[−7.7, +11.2], 58 days) and on weekends (+4.8% [−3.4, +13.8], 75 rain days).

**Open issues.** Daily rain totals do not tell whether rain fell during riding hours; hourly
precipitation would sharpen this. The weekday/weekend split of (ii) suggests the casual-member
difference is a weekday phenomenon (weekday casual riders may be tourists or non-member
commuters), but this is not tested.

---

## Finding 3: is the system becoming less weather-sensitive?

**Goal.** E-bike share rose from 64% to 71% of main-panel trips over the window. If e-bike trips are
less weather-sensitive, the system as a whole should become less weather-sensitive.

**Method.** (a) Daily system totals (main panel), Poisson with
`rain × quarter + TMAX × quarter + snow + wind + holiday | year_month + weekday`. The TMAX slope (% per +1 °C, i.e. per +1.8 °F) is
identified within calendar months, so it is a seasonal local slope: compare the same quarter across
years, not quarters with each other. SEs: heteroskedasticity-robust (= clustered by date at the
daily level); Newey-West (7 lags) as a stress test. Also by half-year.
(b) Decomposition. One stacked Poisson with every term bike-specific and a separate rain effect per
bike type and year, `| bike×year_month + bike×weekday`, clustered by date. Rain effects
r = exp(β) − 1. Weights w = each bike type's share of dry-day trips in that year (the no-rain
baseline). Aggregate rain effect A_y = Σ_b w_b,y · r_b,y. CIs: 20,000 draws from the joint
distribution of the four rain coefficients.

**Output (a)** (`f3a_by_quarter.csv`, Figure 3). Rain effect by quarter, 2024 → 2025: Q1 −23.8% →
−11.9%, Q2 −13.4% → −15.1%, Q3 −16.4% → −14.5%, Q4 −13.6% → −17.2%. Each quarter has 24-40 rain
days and 6-10 heavy-rain days, and the CIs are ±5 to ±14 points. Only Q1 differs between years (+15.6%
[+1.1, +32.2], p = 0.03, 1 of 8 tests). Half-years: no difference (H1 +4.1% [−3.0, +11.7], H2 −1.8%
[−9.8, +6.9]). Temperature slopes: no same-season difference (all p > 0.09). Whole-year system
model: rain −15.8% [−19.0, −12.5] in 2024, −16.2% [−19.1, −13.1] in 2025, difference −0.4% [−5.5,
+5.0].

**Output (b)** (`f3b_decomposition.csv`). The arithmetic, in % change on a rain day:

| | 2024 | 2025 |
|---|---|---|
| E-bike share of dry-day trips, w_E | 65.81% | 70.22% |
| Classic share, w_C | 34.19% | 29.78% |
| E-bike rain effect, r_E | −14.50% | −15.23% |
| Classic rain effect, r_C | −18.30% | −18.38% |
| Aggregate A = w_E·r_E + w_C·r_C | 0.6581(−14.50) + 0.3419(−18.30) = **−15.80** | 0.7022(−15.23) + 0.2978(−18.38) = **−16.17** |

- 2025 effects with the 2024 mix: 0.6581(−15.23) + 0.3419(−18.38) = **−16.31**.
- Total change: −16.17 − (−15.80) = **−0.37 pp** [−4.86, +4.06].
- Mix part, A_2025 − counterfactual = (w_2025 − w_2024)·r_2025 = 0.0441 × (−15.23 + 18.38) =
  **+0.14 pp** [+0.08, +0.19] (less sensitive).
- Within-type part, counterfactual − A_2024 = w_2024·(r_2025 − r_2024) = **−0.51 pp** [−4.99,
  +3.92].
- The other order (mix at 2024 effects, within at 2025 weights) gives +0.17 / −0.54; the average of
  the two orders gives +0.15 / −0.52.
- The share-weighted aggregates match the directly estimated system effects (−15.82, −16.16).

Using bike × rider (4 cells, which also picks up the member share rising from 80% to 82%), the mix
part is +0.28 pp [+0.21, +0.35] and the within part −0.39 pp [−4.71, +3.97].

**Interpretation.** The system is not becoming less weather-sensitive at a detectable level. The
e-bike shift does make it less rain-sensitive, but only by about 0.15 points over two years. Each
extra point of e-bike share cuts the aggregate rain penalty by about 0.03 points (the 3.15-point
gap between bike types × 0.01). That is two orders of magnitude below what quarterly estimates
(CIs of ±5 to ±14 points with 24-40 rain days per quarter) can detect. So (a) cannot reveal
the mix effect even though (b) shows it exists. Within-type change is close to zero and imprecise.

**Stress tests.** Newey-West SEs move quarterly CI ends by less than 2 points. All-day instead of
dry-day weights change any decomposition term by at most 0.04 points.

**Open issues.** The 2024 Q1 rain estimate (−24%) is the outlier. That quarter had 10 heavy-rain
days, including the 3.66 in day on 2024-03-23, so rain intensity, not sensitivity, may differ
between quarters. A rain-intensity specification would test this. Two years is short for a trend.

---

## Availability (exploration only)

**Is historical station status archived?** Yes, but not by the operator.

- **Kaggle, "Citi Bike Stations" (Ethan Rosenthal).** A third-party archive of the live GBFS
  `station_status` feed, polled every 2 minutes (details below). Not downloaded.
- **CityBikes (data.citybik.es), ODbL.** Monthly Parquet files of station status changes per network.
  The page does not list networks, and my guess at an NYC file name returned 404. Coverage of Citi
  Bike is not confirmed.
- **Official sources:** Citi Bike publishes only the live GBFS feed (no history), and the GBFS
  specification itself leaves history out of scope. NYC Open Data's "Citi Bike System Data" entry
  points to trips and the live feed only.

### Kaggle station-status archive: details (from the Kaggle API metadata, 2026-10-19)

| Item | Value |
|---|---|
| URL | https://www.kaggle.com/datasets/rosenthal/citi-bike-stations (version 3, updated 2026-09-28) |
| License | Creative Commons Attribution 4.0 International (CC BY 4.0): reuse allowed with attribution |
| Total size | 21,555,519,218 bytes (21.6 GB) in 11 Parquet files (zstd), one per year |
| Files for our window | `citi_bike_stations_2024.parquet` 4.23 GB, `citi_bike_stations_2025.parquet` 4.35 GB (8.58 GB together) |
| Time coverage | 2016-09-18 to 2026-09-27, about 3.9 billion rows (one row = one station at one poll). Gaps: about 2017-06-05 to 2017-09-13 and 2018-01-07 to 2018-01-23; otherwise about 720 polls per day, with a few days missing some polls |
| Resolution | 2-minute polls; poll time exact from 8/2019 on (hourly before) |
| Rows | 50M (2016) to 590M (2025) per year |

Fields:

| Column | Meaning |
|---|---|
| `station_id` | Id as recorded at the time: numeric until 2023-02, UUID from 2023-03 |
| `legacy_id` | Pre-2023 numeric id, constant over a station's history |
| `current_station_id` | Id in today's feed, for stations that still exist |
| `num_bikes_available` | Bikes available to rent, **including e-bikes** |
| `num_ebikes_available` | E-bikes available (null before 8/2019) |
| `num_bikes_disabled` | Broken bikes docked (null before 8/2019) |
| `num_docks_available`, `num_docks_disabled` | Empty / broken docks |
| `is_installed`, `is_renting`, `is_returning` | Station status flags (null before 8/2019) |
| `station_status_last_reported` | When the station last reported (null for placeholder values) |
| `station_name`, `lat`, `lon`, `region_id`, `capacity`, `has_kiosk` | Station information in effect at poll time (refreshed weekly before 9/2026, so up to 7 days old) |
| `station_information_last_updated`, `station_information_fetched_at`, `missing_station_information` | Provenance of the station information |
| `fetched_at` | Poll time, UTC |
| `source` | `legacy_hourly`, `legacy_raw` or `live` (which collection pipeline produced the row) |

Notes for use:

- Classic bikes available = `num_bikes_available` − `num_ebikes_available`.
- Timestamps are UTC; trip data are local time with no offset, so convert to America/New_York.
- Our trip data use short ids like `7756.10`, which are not among these columns. The join needs a
  name/coordinate match, or the `short_name` field from the GBFS `station_information` feed.
- About 1.5% of 2023-08-05 to 2023-09-07 rows are near-duplicates (outside our window).
- The dataset description says it was partly written by an AI assistant at the author's request.
  The fields above come from that description and have not been checked against the files.

Bottom line: a 2024-25 station × day "e-bike in stock" measure is feasible from this archive
(8.6 GB for two years, readable with DuckDB without loading into memory). This is the right next
step if availability becomes central.

**Cheap proxy check** (`avail_proxy_rain_gap.csv`). Keep station-days on which both bike types had
at least N trip starts, so neither type was missing from the dock all day. **N = 5**: the median
classic count per station-day is 6 (p25 = 1, p10 = 0; e-bike median 18). N = 5 requires classic bikes
to have been rented repeatedly that day, not one stray bike. It keeps 56% of station-days and 93% of
trips. N = 1 and N = 10 are shown for sensitivity.

| Sample | Station-days | E-bike × rain (F1b spec) | Within station-day FE |
|---|---|---|---|
| All station-days (main) | 1,386,707 | +4.5% [+2.1, +7.0] | +4.5% [+2.0, +7.1] |
| Both types ≥ 1 | 1,166,403 | +4.2% [+1.7, +6.7] | |
| **Both types ≥ 5** | 771,863 | **+3.7% [+1.2, +6.3]** | +3.7% [+1.2, +6.3] |
| Both types ≥ 10 | 578,138 | +3.2% [+0.7, +5.9] | |
| Station-months where both ≥ 5 on ≥ 90% of *dry* days (all days kept) | 610,316 | +4.4% [+1.8, +7.1] | +4.5% [+1.9, +7.2] |

The gap holds where both bike types were clearly in supply. It shrinks by about 1 point under the
stricter filters, so a small part of the main estimate may reflect availability. Selecting on the
day's own counts conditions on the outcome: rain removes low-demand station-days, and rain days are
dropped more often (52% kept vs 58% of dry days at N = 5). The last row avoids this by selecting
station-months on dry days only, and gives almost the main estimate. The "within station-day" column
uses station × date FE: it compares e-bike and classic trips at the same dock on the same day. The
cold-weather contrasts behave the same way (0-2 °C / 32-35.6 °F: +19.2% all, +18.0% at N = 5, +21.9% in the
dry-day selection).

---

## Draft text for the write-up

### Finding 1: E-bike trips are less sensitive to cold and heat, as in 2023

Zheng et al. (2025) found that, in 2023, e-bike usage losses in hot (30-32 °C) and cold (−2 to 0 °C)
weather were 5.6 and 7.7 percentage points smaller than classic-bike losses. We test this on
2024-2025, using daily trip starts by bike type at the 1,897 stations active in all 24 months
(78.7 million trips, zeros included). Daily maximum temperature from Central Park is
grouped into 2 °C bins, with the sparse tails merged so that every bin has at least 15 days. This
merges the paper's −2 to 0 °C bin, which has only 12 days, into a "below 0 °C" bin. We fit
Poisson models with station, month and weekday fixed effects per bike type, then pool both types
with date fixed effects to isolate how the e-bike response differs from the classic one.

Both tails replicate (Figure 1). Classic trips fall 60% below the 20-22 °C reference on days below
0 °C, against 54% for e-bikes; at 0-2 °C the losses are 51% and 43%. E-bikes therefore lose 6-7
percentage points less, close to the paper's 7.7. In the pooled model the e-bike advantage is 19%
[13, 26] at 0-2 °C and 11% [4, 18] below 0 °C. The weaker advantage in the coldest bin matches the
paper's finding that the advantage fades below −2 °C. At 30-32 °C the gap is 6.2 points (pooled
contrast +5.6%, 95% CI −0.3 to +11.9; paper: 5.6). Adding bike-specific month and weekday controls
narrows this interval to +2.2 to +8.6. Unlike in the paper, hot days in 2024-25 raise
ridership: relative to 20-22 °C, classic trips are flat at 30-32 °C and e-bike trips rise 9.5%, so we
describe the hot-weather e-bike advantage as a larger gain, not a smaller loss. The cold advantage is
also not confined to extreme cold: e-bikes lose 5-9 points less in every bin below 18 °C. Results hold on all 2,290 stations and with week-clustered errors. A log(trips + 1) regression
reverses the cold result; with many zero counts it depends on the count scale, so we do not use it.

### Finding 2: Rain hits casual riders hardest, and e-bikes soften the hit for both groups

We extend the comparison to rain and split riders into members and casual users. A rain day
(any measurable precipitation) lowers member classic trips by 17.3% [14.8, 19.8], member e-bike
trips by 13.9% [11.7, 16.2], casual classic trips by 25.4% [21.7, 28.9] and casual e-bike trips by
19.8% [17.3, 22.2] (Figure 2). Each estimate comes from a Poisson model with temperature bins, snow,
wind, and station, month and weekday fixed effects. To compare groups we pool all four in one model
with date fixed effects, which absorbs the weather and everything else that is common to a day. The
comparison is therefore within the same day.

Within the same day, e-bike trips fall 4.1% [1.8, 6.5] less than classic trips among members, and
7.3% [2.3, 12.5] less among casual riders. Rider type separates the groups more than bike type does:
casual riders lose 6-9% more than members on either bike. The e-bike advantage is larger for casual
riders by 3.0 points, but this difference is not statistically clear (95% CI −1.4 to +7.6). It
becomes significant with a stricter rain threshold (≥ 0.1 in), on weekdays only, and with
group-specific calendar controls. It disappears on heavy-rain days (≥ 0.5 in, 58 days) and on
weekends. The member advantage is positive in every specification we tried. The casual advantage
is positive in all but the heavy-rain and weekend subsamples, where it is imprecise. Consistent with
these contrasts, the e-bike share of trips is one to two percentage points higher on rain days than on
dry days in the same month.

A caveat applies throughout: the data record the bike that was taken, not the bike that was wanted.
On rainy, low-demand days e-bikes are less likely to run out, which would mimic an e-bike advantage.
Restricting to station-days on which both bike types were rented at least five times (56% of
station-days, 93% of trips), the pooled e-bike rain advantage falls only from 4.5% to 3.7%
[1.2, 6.3].

### Finding 3: The shift to e-bikes barely changes the system's weather sensitivity

The e-bike share of trips rose from 64% to 71% over the two years. If e-bike trips are less
weather-sensitive, the system as a whole should become less weather-sensitive over time. We check
this in two ways.

First, we estimate the rain effect and the temperature slope on system-wide daily trips separately
for each quarter (Figure 3). The rain effect ranges from −12% to −24% with no trend. Comparing the
same quarter across years, only the first quarter differs (−24% in 2024 vs −12% in 2025, p = 0.03,
one of eight comparisons). Temperature slopes show no change. Over whole years the rain effect is
−15.8% in 2024 and −16.2% in 2025.

Second, we decompose the aggregate rain effect into bike mix and within-type change. The aggregate
effect is the share-weighted average of the bike-type effects: in 2024, 0.658 × (−14.5%) + 0.342 ×
(−18.3%) = −15.8%. With the 2025 rain effects and the 2024 bike mix it would be −16.3%; with the
actual 2025 mix (70.2% e-bike) it is −16.2%. The mix shift therefore makes the system less
rain-sensitive by only 0.15 percentage points [0.11, 0.19]. Within-type change accounts for −0.5
points [−5.0, +3.9], indistinguishable from zero. The logic is simple arithmetic. The two bike types
differ in rain sensitivity by about 3 points, so each extra point of e-bike share lowers the
aggregate rain penalty by about 0.03 points. Including the rise in member share doubles the mix
effect to 0.28 points.

So the system is not measurably less weather-sensitive. The reason is not that e-bikes fail to
help: the shift in mix is too small relative to the difference between bike types. A mix effect
of 0.15 points is far below what quarterly estimates can detect, with 24-40 rain days per quarter
and confidence intervals of ±5 to ±14 points. At the current pace, a one-point reduction in the
rain penalty would need roughly 30 more points of e-bike share.

### Suggested figures (3 of a possible 4)

1. `figures/checkpoint1/fig1_temperature_by_bike_type.png`: Finding 1 (bins by bike type; e-bike
   contrast with the paper's estimate).
2. `figures/checkpoint1/fig2_rain_by_bike_and_rider.png`: Finding 2 (four group rain effects; contrasts
   across stress tests).
3. `figures/checkpoint1/fig3_weather_sensitivity_over_time.png`: Finding 3 (quarterly rain effect,
   temperature slope, e-bike share).

The decomposition is clearer as the small table above than as a figure. The availability check fits
in one sentence plus a table row.

---

## Libraries and sources (for acknowledgements)

Software (versions in `requirements.txt`):

- DuckDB 1.5.6: panel construction from the trip Parquet files. https://duckdb.org
- pandas 3.0.6, NumPy 2.5.3, pyarrow 25.0.1: data handling.
- pyfixest 0.60.0: Poisson and OLS with high-dimensional fixed effects, clustered and Newey-West
  SEs. https://github.com/py-econometrics/pyfixest (pulls in formulaic and narwhals).
- SciPy 1.18.1: normal distribution for p-values.
- matplotlib 3.11.2: figures.
- holidays 0.106: US federal holidays.
- statsmodels 0.15.0: used in the earlier EDA only.

Data:

- Citi Bike / Lyft, *Citi Bike System Data*, https://citibikenyc.com/system-data (trip files:
  https://s3.amazonaws.com/tripdata/index.html).
- NOAA NCEI, *GHCN-Daily*, station USW00094728 (NY City Central Park), https://doi.org/10.7289/V5D21VHZ;
  Menne et al. (2012), *Journal of Atmospheric and Oceanic Technology* 29(7), 897-910.
- Rosenthal, E., *Citi Bike Stations* (Kaggle, CC BY 4.0),
  https://www.kaggle.com/datasets/rosenthal/citi-bike-stations (explored, not used).
- CityBikes, *Historical bike share data*, https://data.citybik.es (explored, not used).
- General Bikeshare Feed Specification, https://github.com/MobilityData/gbfs.

Literature:

- Zheng, R., Liang, Y., Wang, D., & Ou, Y. (2025). Shared e-bikes are more resilient than shared
  bikes to extreme temperatures: Evidence from Citi Bike in New York City. *Journal of Transport
  Geography* 129, 104412. https://doi.org/10.1016/j.jtrangeo.2025.104412 (abstract only; read via
  https://scholars.hkbu.edu.hk/en/publications/shared-e-bikes-are-more-resilient-than-shared-bikes-to-extreme-te/).
- Suggested method citations (not yet checked against the text): Santos Silva & Tenreyro (2006),
  "The log of gravity", *Review of Economics and Statistics* 88(4) (Poisson PML); Chen & Roth (2024),
  "Logs with zeros? Some problems and solutions", *Quarterly Journal of Economics* 139(2) (why
  log(y+1) fails here); Newey & West (1987), *Econometrica* 55(3) (HAC SEs).
