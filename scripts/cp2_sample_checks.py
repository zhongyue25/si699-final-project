"""Checkpoint 2 sample checks (peer review comments on Checkpoint 1).

1. Who is outside the balanced panel? Compare the 1,897 main-panel stations with the 393 others.
2. Do Findings 2 and 3 hold on all 2,290 stations?
   - F2: per-group rain levels on full-sample daily totals (contrasts were already in Checkpoint 1).
   - F3: yearly system rain effect and bike-mix decomposition on full-sample daily totals, a
     station-level Poisson with station fixed effects on the unbalanced panel (each station observed
     from its first to its last trip date), and the excluded stations alone.
3. Finding 3's 2024 Q1 vs 2025 Q1 gap with the hourly rain/snow split: a day is a rain day if it had a
   measurable rain hour with no snow code, and snow days are flagged from LCD present-weather codes.
"""

import sys
import warnings

import numpy as np
import pandas as pd
import pyfixest as pf

import config
import cp1_common as cp
import cp1_finding2 as f2
import cp1_finding3 as f3
import cp2_common as c2

warnings.filterwarnings("ignore")


def fepois(fml, data, vcov=None):
    return pf.fepois(fml, data=data, vcov=vcov or {"CRV1": "date_id"}, ssc=cp.SSC, copy_data=False)


def station_comparison():
    st = pd.read_parquet(config.STATIONS_PARQUET)
    st["main"] = st.months_active == len(config.MONTHS)
    p = pd.read_parquet(cp.PANEL_PARQUET, columns=["station", "ebike", "casual", "trips"])
    ids = pd.read_csv(cp.TAB_DIR / "panel_stations.csv", dtype={"station_id": str})[["station", "station_id"]]
    ids["station_id"] = ids.station_id.astype(str)
    p = p.merge(ids, on="station")
    by = p.groupby("station_id").apply(lambda d: pd.Series({
        "ebike_share": (d.trips * d.ebike).sum() / d.trips.sum(),
        "casual_share": (d.trips * d.casual).sum() / d.trips.sum()}), include_groups=False)
    st = st.join(by, on="station_id")
    st["active_days"] = (st.last_trip_date - st.first_trip_date).dt.days + 1
    st["trips_per_active_day"] = st.n_trips / st.active_days
    st["opened_in_window"] = st.first_trip_date > pd.Timestamp("2024-01-31")
    st["gone_before_end"] = st.last_trip_date < pd.Timestamp("2025-12-01")
    # Rough borough from coordinates: Manhattan west of the East River line, else outer boroughs.
    st["manhattan"] = (st.lng < -73.93 + (st.lat - 40.70) * 0.6) & (st.lat > 40.70) & (st.lng > -74.02)
    rows = []
    for name, d in (("main panel", st[st.main]), ("excluded", st[~st.main]), ("all", st)):
        w = d.n_trips
        rows.append({
            "sample": name, "stations": len(d), "trips": int(d.n_trips.sum()),
            "share_of_trips": d.n_trips.sum() / st.n_trips.sum(),
            "median_months_active": d.months_active.median(),
            "opened_after_jan_2024": d.opened_in_window.mean(),
            "gone_before_dec_2025": d.gone_before_end.mean(),
            "median_trips_per_active_day": d.trips_per_active_day.median(),
            "in_cbd_zone": d.in_zone.mean(), "manhattan_approx": d.manhattan.mean(),
            "ebike_share_tripweighted": np.average(d.ebike_share.fillna(0), weights=w),
            "casual_share_tripweighted": np.average(d.casual_share.fillna(0), weights=w),
            "median_lat": d.lat.median(), "median_lng": d.lng.median(),
        })
    return pd.DataFrame(rows), st


def f3_full(bins):
    out = {}
    g_full = cp.load_daily_groups("full", ("ebike", "casual"))
    daily = g_full.groupby("date_id").trips.sum().reset_index().merge(
        cp.load_calendar()[cp.CAL_COLS], on="date_id")
    daily["tmax_dm"] = daily.tmax_c - daily.groupby("year_month").tmax_c.transform("mean")
    sys_year, sys_diff = f3.yearly_system(daily, bins)
    out["system_year"] = pd.concat([sys_year, pd.DataFrame([sys_diff]).assign(model="system_direct")])
    q, q_tests, _ = f3.by_period(daily, "quarter")
    out["quarter"] = q
    out["quarter_tests"] = q_tests
    bike = g_full.groupby(["date_id", "ebike"]).trips.sum().reset_index().merge(
        cp.load_calendar()[cp.CAL_COLS], on="date_id")
    dec, eff, _ = f3.decomposition(bike, ["ebike"], bins, "bike_type_full_sample")
    out["decomposition"] = dec
    out["effects"] = eff

    # Station-level, unbalanced: station FE, all stations, and excluded stations only.
    rows = []
    for name in ("full", "excluded"):
        p = pd.read_parquet(cp.PANEL_PARQUET, columns=["station", "date_id", "trips", "main"])
        if name == "excluded":
            p = p[~p.main]
        p = p.groupby(["station", "date_id"], sort=False).trips.sum().reset_index()
        p = p.merge(cp.load_calendar()[cp.CAL_COLS], on="date_id")
        T = cp.add_bin_dummies(p, bins)
        for y in (2024, 2025):
            p[f"rain_{y}"] = (p.rain * (p.year == y)).astype(np.int8)
        fit = fepois(f"trips ~ rain_2024 + rain_2025 + {' + '.join(T)} + snow + awnd_ms + holiday"
                     " | station + year_month + weekday", p)
        t = cp.coef_table(fit, ["rain_2024", "rain_2025"], label=f"station_fe_{name}")
        t = pd.concat([t, pd.DataFrame([cp.lincom(fit, {"rain_2025": 1, "rain_2024": -1},
                                                  "rain_2025_minus_2024")]).assign(
            model=f"station_fe_{name}")])
        t["N"] = int(fit._N)
        t["stations"] = int(p.station.nunique())
        rows.append(t)
        print("station-level", name, fit._N, flush=True)
        del p
    out["station_level"] = pd.concat(rows, ignore_index=True)
    return out


def f2_full_levels(bins):
    g = cp.load_daily_groups("full", ("ebike", "casual"))
    lev = f2.levels(g, bins)
    return lev[lev.spec == "rain_any"].assign(sample="full")


def q1_rain_only(bins):
    """Quarterly rain effect with rain days and snow days defined from the hourly record."""
    w = c2.load_weather_hourly()
    day = w.groupby("date").agg(rain_hours=("rain_hour", "sum"), meas_hours=("wet_meas", "sum"),
                                snow_hours=("snow_hour", "sum")).reset_index()
    meas_rain = w[(w.wet_meas == 1) & (w.snow_hour == 0)].groupby("date").size()
    day["lcd_rain"] = day.date.map(meas_rain).fillna(0).gt(0).astype(np.int8)
    day["lcd_snow"] = (day.snow_hours > 0).astype(np.int8)
    daily = cp.load_daily_groups("main", ())
    daily["date"] = pd.to_datetime(daily.date)
    daily = daily.merge(day[["date", "lcd_rain", "lcd_snow"]], on="date")
    daily["tmax_dm"] = daily.tmax_c - daily.groupby("year_month").tmax_c.transform("mean")
    res = []
    for label, rain, snow in (("ghcn_rain_ghcn_snow", "rain", "snow"),
                              ("lcd_rain_only_lcd_snow", "lcd_rain", "lcd_snow")):
        d = daily.copy()
        d["rain"] = d[rain]
        d["snow"] = d[snow]
        q, tests, meta = f3.by_period(d, "quarter")
        q = q[q.model == "hetero"].assign(spec=label)
        tests = tests.assign(spec=label)
        res.append((q, tests, meta.assign(spec=label)))
    counts = daily.groupby("quarter").agg(ghcn_rain=("rain", "sum"), lcd_rain_only=("lcd_rain", "sum"),
                                          ghcn_snow=("snow", "sum"), lcd_snow=("lcd_snow", "sum"),
                                          both_rain_and_snow_lcd=("lcd_snow", lambda s: (
                                              s * daily.loc[s.index, "lcd_rain"]).sum()))
    return (pd.concat([r[0] for r in res]), pd.concat([r[1] for r in res]), counts.reset_index())


def figure_q1(q):
    import matplotlib.pyplot as plt
    import plot_style as style

    style.apply()
    q = q[q["var"] == "rain"]
    periods = sorted(q.period.unique())
    x = np.arange(len(periods))
    fig, ax = plt.subplots(figsize=(7.2, 2.9))
    specs = [("ghcn_rain_ghcn_snow", "Checkpoint 1: daily PRCP > 0 (snow days count as rain)",
              style.NEUTRAL, "o"),
             ("lcd_rain_only_lcd_snow", "Checkpoint 2: hourly record, rain-only days", style.TEXT, "s")]
    for k, (spec, lab, color, mk) in enumerate(specs):
        s = q[q.spec == spec].set_index("period").reindex(periods)
        ax.errorbar(x + (k - 0.5) * 0.22, s.pct, yerr=[s.pct - s.pct_lo, s.pct_hi - s.pct], fmt=mk,
                    ms=5, color=color, elinewidth=1.3, capsize=0, mec=style.SURFACE, mew=1, label=lab)
    ax.axhline(0, color=style.TEXT_MUTED, lw=0.8)
    ax.axvspan(-0.5, 0.5, color=style.GRID, alpha=0.4, lw=0)
    ax.axvspan(3.5, 4.5, color=style.GRID, alpha=0.4, lw=0)
    ax.set_xticks(x, periods, fontsize=8.5)
    ax.set_ylabel("Rain day vs dry day (%)")
    ax.set_ylim(-36, 6)
    ax.set_yticks([-30, -20, -10, 0])
    ax.legend(loc="upper center", fontsize=7.6, ncol=2, bbox_to_anchor=(0.5, -0.12))
    c2.save_fig(fig, "fig3_quarterly_rain_lcd.png")


def main():
    c2.ensure_dirs()
    if "--figure-only" in sys.argv:
        figure_q1(pd.read_csv(c2.TAB_DIR / "f3_quarter_lcd_rain_only.csv"))
        return
    bins = cp.bin_order()
    comp, st = station_comparison()
    comp.to_csv(c2.TAB_DIR / "sample_station_comparison.csv", index=False)
    pd.set_option("display.width", 220)
    print(comp.T.to_string())

    lev = f2_full_levels(bins)
    lev.to_csv(c2.TAB_DIR / "sample_f2_levels_full.csv", index=False)
    print(lev[["group", "pct", "pct_lo", "pct_hi"]].round(2).to_string(index=False))

    out = f3_full(bins)
    for k, v in out.items():
        v.to_csv(c2.TAB_DIR / f"sample_f3_{k}.csv", index=False)
    print(out["system_year"][["model", "term", "pct", "pct_lo", "pct_hi", "p"]].round(3).to_string())
    print(out["station_level"][["model", "term", "pct", "pct_lo", "pct_hi", "p", "N", "stations"]]
          .round(3).to_string())
    d = out["decomposition"]
    print(d[d.weights == "dry_day_share"].round(3).to_string(index=False))
    print(out["quarter_tests"].round(3).to_string(index=False))

    q, tests, counts = q1_rain_only(bins)
    q.to_csv(c2.TAB_DIR / "f3_quarter_lcd_rain_only.csv", index=False)
    tests.to_csv(c2.TAB_DIR / "f3_same_season_lcd_rain_only.csv", index=False)
    counts.to_csv(c2.TAB_DIR / "f3_quarter_day_counts_lcd.csv", index=False)
    figure_q1(q)
    print(counts.to_string(index=False))
    print(tests[tests.term.str.startswith("rain")][["spec", "term", "pct", "pct_lo", "pct_hi", "p"]]
          .round(3).to_string(index=False))
    print(q[q["var"] == "rain"][["spec", "period", "pct", "pct_lo", "pct_hi"]].round(1).to_string(index=False))


if __name__ == "__main__":
    sys.exit(main())
