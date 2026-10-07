"""Run the proposal EDA (sections A-F): writes figures/, reports/tables/ and reports/metrics.json."""

import json

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statsmodels.formula.api as smf

import config
import plot_style as style

RIDERS = ["member", "casual"]
BIKES = ["electric", "classic"]


def save_table(df, name, index=False):
    df.to_csv(config.TABLES_DIR / name, index=index)


def month_axis(ax):
    ax.xaxis.set_major_locator(mdates.MonthLocator(bymonth=[1, 4, 7, 10]))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b\n%Y"))


def mark_pricing_start(ax, label=True):
    start = pd.Timestamp(config.CONGESTION_PRICING_START)
    ax.axvline(start, color=style.TEXT_MUTED, linewidth=1, linestyle=(0, (4, 3)))
    if label:
        ax.annotate(
            "congestion pricing\nstarts 2025-01-05", xy=(start, 1), xycoords=("data", "axes fraction"),
            xytext=(4, -2), textcoords="offset points", va="top", fontsize=8, color=style.TEXT_MUTED,
        )


# --------------------------------------------------------------------------- A


def section_a(con):
    inventory = pd.read_csv(config.TABLES_DIR / "file_inventory.csv", dtype={"file_month": str})
    per_month = inventory.groupby("file_month").agg(
        n_files=("csv", "count"), n_rows=("n_rows", "sum"), n_rows_in_file=("n_rows_in_file", "sum")
    )
    save_table(per_month.reset_index(), "rows_per_file_month.csv")

    issues = pd.read_csv(config.TABLES_DIR / "raw_issue_counts.csv").set_index("issue")
    weather_quality = pd.read_csv(config.TABLES_DIR / "weather_quality.csv")
    boundary = con.execute(
        f"""
        SELECT
            count(*) FILTER (WHERE strftime(ended_at, '%Y%m') <> left(source_file, 6))
                AS end_month_differs_from_file_month,
            count(*) FILTER (WHERE started_at < TIMESTAMP '{config.STUDY_START}') AS started_before_window,
            count(*) FILTER (WHERE started_at >= TIMESTAMP '{config.STUDY_END}' + INTERVAL 1 DAY)
                AS started_after_window,
            min(started_at) AS min_started_at,
            max(started_at) AS max_started_at,
            max(ended_at) AS max_ended_at
        FROM read_parquet('{config.TRIPS_RAW_DIR}/*.parquet')
        """
    ).fetchdf().iloc[0]

    return {
        "n_zip_files": int(inventory["zip"].nunique()),
        "n_csv_files": int(len(inventory)),
        "raw_rows": int(inventory.n_rows.sum()),
        "missing_months": sorted(set(config.MONTHS) - set(per_month.index)),
        "files_per_month": per_month.n_files.to_dict(),
        "rows_per_file_month": per_month.n_rows.to_dict(),
        "spillover_rows_kept": {
            m: int(per_month.n_rows[m]) for m in config.SPILLOVER_MONTHS if m in per_month.index
        },
        "spillover_rows_in_file": {
            m: int(per_month.n_rows_in_file[m]) for m in config.SPILLOVER_MONTHS if m in per_month.index
        },
        "distinct_header_sets": int(inventory["columns"].nunique()),
        "sniffed_type_sets": inventory.groupby("sniffed_types").size().to_dict(),
        "cast_failures": int(inventory.n_cast_failures.sum()),
        "start_lng_west_of_cutoff": int(issues.n_trips["start_lng_west_of_cutoff"]),
        "start_lng_west_of_cutoff_but_nyc_station": int(
            issues.n_trips["start_lng_west_of_cutoff_but_nyc_station"]
        ),
        "start_station_nj": int(issues.n_trips["start_station_nj"]),
        "end_station_nj": int(issues.n_trips["end_station_nj"]),
        "start_month_differs_from_file_month": int(
            issues.n_trips["start_month_differs_from_file_month"]
        ),
        **{k: (int(v) if isinstance(v, (int, np.integer)) else str(v)) for k, v in boundary.items()},
        "weather": weather_quality.set_index("field").to_dict(orient="index"),
    }


# --------------------------------------------------------------------------- B


def section_b(con):
    steps = pd.read_csv(config.TABLES_DIR / "cleaning_steps.csv")
    issues = pd.read_csv(config.TABLES_DIR / "raw_issue_counts.csv")

    raw = f"""
        (SELECT date_diff('millisecond', started_at, ended_at) / 1000.0 AS duration_s,
                end_station_id IS NULL AS no_end
         FROM read_parquet('{config.TRIPS_RAW_DIR}/*.parquet'))
    """
    hist = con.execute(
        f"""
        SELECT floor(log10(duration_s) * 20) / 20 AS log10_s, count(*) AS n,
               count(*) FILTER (WHERE no_end) AS n_no_end
        FROM {raw} WHERE duration_s > 0 GROUP BY 1 ORDER BY 1
        """
    ).fetchdf()
    tail = con.execute(
        f"""
        SELECT threshold_h, count(*) FILTER (WHERE duration_s > threshold_h * 3600) AS n_longer,
               count(*) FILTER (WHERE duration_s > threshold_h * 3600 AND no_end) AS n_longer_no_end
        FROM {raw}, (SELECT unnest([1, 3, 6, 12, 24, 25, 48]) AS threshold_h)
        GROUP BY 1 ORDER BY 1
        """
    ).fetchdf()
    quantiles = con.execute(
        f"""
        SELECT quantile_cont(duration_s, [0.01, 0.25, 0.5, 0.75, 0.95, 0.99, 0.999]) FROM {raw}
        """
    ).fetchone()[0]
    save_table(tail, "duration_tail.csv")

    fig, ax = plt.subplots(figsize=(8, 3.8))
    hist = hist[hist.log10_s <= np.log10(25.2 * 3600)]
    edges = np.append(10 ** hist.log10_s, 10 ** (hist.log10_s.iloc[-1] + 0.05))
    ax.stairs(hist.n, edges, color=style.MEMBER, linewidth=2.6, label="all raw trips")
    ax.stairs(hist.n_no_end.replace(0, np.nan), edges, color=style.CASUAL, linewidth=1.4,
              label="trips with no end station")
    ax.set_xscale("log")
    ax.set_yscale("log")
    ticks = {60: "1 min", 600: "10 min", 3600: "1 h", 6 * 3600: "6 h", 86400: "24 h"}
    ax.set_xticks(list(ticks), list(ticks.values()))
    ax.minorticks_off()
    ax.set_xlim(1, 2e5)
    ax.set_ylim(0.7, 3e7)
    for cutoff in (config.MIN_DURATION_S, config.MAX_DURATION_S):
        ax.axvline(cutoff, color=style.TEXT_MUTED, linewidth=1, linestyle=(0, (4, 3)))
    n_cap = int(tail.set_index("threshold_h").n_longer[24])
    ax.annotate(
        f"{n_cap:,} trips > 24 h,\nalmost all closed at 24-25 h\nwith no end station",
        xy=(88000, hist.n[hist.log10_s >= np.log10(86400)].max()), xytext=(0.66, 0.95),
        textcoords="axes fraction", va="top", fontsize=8, color=style.TEXT_MUTED,
        arrowprops={"arrowstyle": "-", "color": style.TEXT_MUTED, "linewidth": 0.8},
    )
    ax.set_xlabel("trip duration (log scale)")
    ax.set_ylabel("trips per bin (log scale)")
    ax.set_title("Trip duration: a clean bulk plus an artificial spike at the 24 h cap")
    ax.legend(loc="upper left")
    style.save(fig, "fig03_duration_tail.png")

    return {
        "cleaning_steps": steps.to_dict(orient="records"),
        "raw_issue_counts": issues.set_index("issue").to_dict(orient="index"),
        "duration_quantiles_s": dict(
            zip(["p1", "p25", "p50", "p75", "p95", "p99", "p99.9"], [round(q, 1) for q in quantiles])
        ),
        "duration_tail": tail.to_dict(orient="records"),
        "clean_rows": int(steps.remaining.iloc[-1]),
        "pct_removed": round(100 * (1 - steps.remaining.iloc[-1] / steps.remaining.iloc[0]), 4),
    }


# --------------------------------------------------------------------------- C


def section_c(con, clean, stations, station_month):
    monthly = con.execute(
        f"""
        SELECT ym,
               count(*) AS trips,
               count(*) FILTER (WHERE member_casual = 'member') AS member,
               count(*) FILTER (WHERE member_casual = 'casual') AS casual,
               count(*) FILTER (WHERE rideable_type = 'electric_bike') AS electric,
               count(*) FILTER (WHERE rideable_type = 'classic_bike') AS classic,
               count(*) FILTER (WHERE NOT has_end_station) AS no_end_station,
               count(*) FILTER (WHERE start_station_id = end_station_id) AS round_trips
        FROM {clean} GROUP BY 1 ORDER BY 1
        """
    ).fetchdf()
    monthly["member_share"] = monthly.member / monthly.trips
    monthly["electric_share"] = monthly.electric / monthly.trips
    monthly["active_stations"] = (
        station_month.groupby("ym").station_id.nunique().reindex(monthly.ym).to_numpy()
    )
    monthly["month_start"] = pd.to_datetime(monthly.ym, format="%Y%m")
    save_table(monthly, "monthly_summary.csv")

    other_types = con.execute(
        f"SELECT rideable_type, count(*) FROM {clean} GROUP BY 1 ORDER BY 2 DESC"
    ).fetchall()

    top10 = stations.nlargest(10, "n_trips")[["station_id", "station_name", "n_trips", "in_zone"]]
    save_table(top10, "top10_stations.csv")
    ranked = stations.n_trips.sort_values(ascending=False).to_numpy()
    cum_share = ranked.cumsum() / ranked.sum()

    examples = {
        "typical_trip": f"""
            SELECT * FROM {clean}
            WHERE member_casual = 'member' AND rideable_type = 'electric_bike'
              AND duration_s BETWEEN 530 AND 545 AND start_station_id <> end_station_id
              AND isodow(started_at) <= 5 AND hour(started_at) = 8
            ORDER BY ride_id LIMIT 1""",
        "very_long_trip": f"SELECT * FROM {clean} ORDER BY duration_s DESC, ride_id LIMIT 1",
        "round_trip": f"""
            SELECT * FROM {clean}
            WHERE start_station_id = end_station_id AND member_casual = 'casual'
              AND duration_s BETWEEN 1800 AND 3600 AND isodow(started_at) >= 6
            ORDER BY ride_id LIMIT 1""",
    }
    example_rows = pd.concat(
        [con.execute(sql).fetchdf().assign(example=name) for name, sql in examples.items()]
    ).drop(columns=["ym"])
    save_table(example_rows, "example_trips.csv")

    fig, axes = plt.subplots(1, 3, figsize=(11, 3.2))
    panels = [
        ("active_stations", "Stations with at least one trip start", style.NEUTRAL, False),
        ("electric_share", "E-bike share of trips", style.NEUTRAL, True),
        ("member_share", "Member share of trips", style.MEMBER, True),
    ]
    for ax, (col, title, color, is_share) in zip(axes, panels):
        ax.plot(monthly.month_start, monthly[col], color=color, marker="o", markersize=3)
        ax.set_title(title)
        ax.xaxis.set_major_locator(mdates.MonthLocator(bymonth=[1, 7]))
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%b\n%Y"))
        if is_share:
            ax.yaxis.set_major_formatter(lambda v, _: f"{v:.0%}")
        for i in (0, len(monthly) - 1):
            value = monthly[col].iloc[i]
            ax.annotate(
                f"{value:.0%}" if is_share else f"{value:,.0f}",
                (monthly.month_start.iloc[i], value), xytext=(0, 7), textcoords="offset points",
                ha="center", fontsize=8, color=style.TEXT_MUTED,
            )
        ax.margins(y=0.25)
    fig.suptitle("System changes over the study window that can confound trend comparisons",
                 x=0.01, ha="left", fontsize=11, fontweight="bold")
    fig.tight_layout()
    style.save(fig, "fig04_system_confounds.png")

    fig, ax = plt.subplots(figsize=(7, 3.6))
    ax.plot(np.arange(1, len(ranked) + 1), ranked, color=style.MEMBER)
    ax.set_yscale("log")
    ax.set_xlabel("station rank by trip starts")
    ax.set_ylabel("trip starts, 2024-2025 (log scale)")
    ax.set_title("Trips per station: long tail of low-volume and newly added stations")
    style.save(fig, "extra_station_long_tail.png")

    yearly = monthly.assign(year=monthly.ym.str[:4]).groupby("year")[
        ["trips", "member", "casual", "electric", "classic"]
    ].sum()
    total = int(monthly.trips.sum())
    return {
        "clean_trips_total": total,
        "trips_per_year": yearly.trips.to_dict(),
        "trips_per_month": monthly.set_index("ym").trips.to_dict(),
        "member_share_overall": round(monthly.member.sum() / total, 4),
        "member_share_by_year": (yearly.member / yearly.trips).round(4).to_dict(),
        "member_share_by_month": monthly.set_index("ym").member_share.round(4).to_dict(),
        "electric_share_overall": round(monthly.electric.sum() / total, 4),
        "electric_share_by_year": (yearly.electric / yearly.trips).round(4).to_dict(),
        "electric_share_by_month": monthly.set_index("ym").electric_share.round(4).to_dict(),
        "rideable_types": dict(other_types),
        "active_stations_by_month": monthly.set_index("ym").active_stations.to_dict(),
        "stations_total": int(len(stations)),
        "stations_active_all_24_months": int((stations.months_active == 24).sum()),
        "stations_first_seen_2025": int((stations.first_trip_date >= pd.Timestamp("2025-01-01")).sum()),
        "trips_per_station": {
            "min": int(ranked.min()), "median": float(np.median(ranked)), "max": int(ranked.max()),
            "stations_for_50pct_of_trips": int(np.searchsorted(cum_share, 0.5) + 1),
        },
        "top10_stations": top10.to_dict(orient="records"),
        "no_end_station_kept": int(monthly.no_end_station.sum()),
        "round_trip_share": round(monthly.round_trips.sum() / total, 4),
        "example_trips": json.loads(example_rows.to_json(orient="records", date_format="iso")),
    }


# --------------------------------------------------------------------------- D


def section_d(con, clean, daily):
    hourly = con.execute(
        f"""
        SELECT isodow(started_at) >= 6 AS is_weekend, hour(started_at) AS hour, member_casual,
               count(*) AS trips
        FROM {clean} GROUP BY ALL ORDER BY ALL
        """
    ).fetchdf()
    n_days = daily.groupby("is_weekend").size()
    hourly["trips_per_day"] = hourly.trips / hourly.is_weekend.map(n_days)
    save_table(hourly, "hourly_profile.csv")

    fig, axes = plt.subplots(1, 2, figsize=(10, 3.6), sharey=True)
    for ax, (is_weekend, title) in zip(axes, [(False, "Weekdays"), (True, "Weekends")]):
        for rider in RIDERS:
            part = hourly[(hourly.is_weekend == is_weekend) & (hourly.member_casual == rider)]
            ax.plot(part.hour, part.trips_per_day, color=style.RIDER_COLORS[rider], label=rider)
            peak = part.loc[part.trips_per_day.idxmax()]
            ax.annotate(f"{rider}\npeak {int(peak.hour)}:00", (peak.hour, peak.trips_per_day),
                        xytext=(0, 5), textcoords="offset points", ha="center", fontsize=8,
                        color=style.TEXT_MUTED)
        ax.set_title(title)
        ax.set_xticks(range(0, 24, 3))
        ax.set_xlabel("hour of trip start (local time)")
        ax.margins(y=0.18)
    axes[0].set_ylabel("average trips per hour")
    axes[0].yaxis.set_major_formatter(lambda v, _: f"{v / 1000:.0f}k")
    axes[0].legend(loc="upper left")
    fig.suptitle("Members show a commute double peak on weekdays; casual riders peak in the afternoon",
                 x=0.01, ha="left", fontsize=11, fontweight="bold")
    fig.tight_layout()
    style.save(fig, "fig02_hourly_profile.png")

    fig, ax = plt.subplots(figsize=(10, 3.8))
    for rider in RIDERS:
        col = f"trips_{rider}"
        ax.plot(daily.date, daily[col], color=style.RIDER_COLORS[rider], linewidth=0.5, alpha=0.3)
        rolling = daily[col].rolling(7, center=True).mean()
        ax.plot(daily.date, rolling, color=style.RIDER_COLORS[rider], label=f"{rider} (7-day mean)")
    mark_pricing_start(ax)
    month_axis(ax)
    ax.yaxis.set_major_formatter(lambda v, _: f"{v / 1000:.0f}k")
    ax.set_ylabel("trips per day")
    ax.set_ylim(0)
    ax.set_title("Daily Citi Bike trips, 2024-2025: strong seasonality, sharp single-day drops")
    ax.legend(loc="upper left")
    style.save(fig, "fig01_daily_trips.png")

    def peaks(is_weekend, rider):
        part = hourly[(hourly.is_weekend == is_weekend) & (hourly.member_casual == rider)]
        return part.nlargest(2, "trips_per_day").hour.sort_values().tolist()

    lowest = daily.nsmallest(5, "trips_total")
    return {
        "top2_hours": {
            f"{'weekend' if w else 'weekday'}_{r}": peaks(w, r) for w in (False, True) for r in RIDERS
        },
        "daily_trips": {
            "min": int(daily.trips_total.min()), "median": float(daily.trips_total.median()),
            "max": int(daily.trips_total.max()),
            "max_date": str(daily.loc[daily.trips_total.idxmax(), "date"].date()),
        },
        "lowest_days": [
            {"date": str(r.date.date()), "trips": int(r.trips_total), "tmax_f": round(r.tmax_f, 1),
             "prcp_in": round(r.prcp_in, 2), "snow_mm": r.snow_mm, "holiday": r.holiday_name}
            for r in lowest.itertuples()
        ],
        "weekday_mean_trips": float(daily[~daily.is_weekend].trips_total.mean()),
        "weekend_mean_trips": float(daily[daily.is_weekend].trips_total.mean()),
    }


# --------------------------------------------------------------------------- E


def fit_weather_model(daily, group):
    df = daily.assign(
        log_trips=np.log(daily[f"trips_{group}"]),
        rain=daily.rain_day.astype(int),
        month=daily.date.dt.month,
    )
    model = smf.ols(
        "log_trips ~ tmax_f + I(tmax_f ** 2) + rain + C(weekday) + C(month)", data=df
    ).fit(cov_type="HAC", cov_kwds={"maxlags": 7})
    ci = model.conf_int()
    table = pd.DataFrame(
        {"group": group, "term": model.params.index, "coef": model.params.to_numpy(),
         "ci_low": ci[0].to_numpy(), "ci_high": ci[1].to_numpy(), "p_value": model.pvalues.to_numpy()}
    )
    b1, b2 = model.params["tmax_f"], model.params["I(tmax_f ** 2)"]
    summary = {
        "n_days": int(model.nobs),
        "r_squared": round(model.rsquared, 3),
        "tmax_f": [round(v, 5) for v in (b1, *ci.loc["tmax_f"])],
        "tmax_f_squared": [round(v, 6) for v in (b2, *ci.loc["I(tmax_f ** 2)"])],
        "rain": [round(v, 4) for v in (model.params["rain"], *ci.loc["rain"])],
        "rain_pct_effect": [
            round(100 * (np.exp(v) - 1), 1) for v in (model.params["rain"], *ci.loc["rain"])
        ],
        "implied_peak_tmax_f": round(-b1 / (2 * b2), 1) if b2 < 0 else None,
        "pct_per_f_at_50f": round(100 * (np.exp(b1 + 2 * b2 * 50) - 1), 2),
        "pct_per_f_at_80f": round(100 * (np.exp(b1 + 2 * b2 * 80) - 1), 2),
    }
    return table, summary


def ebike_share_by_condition(daily):
    """E-bike share of trips by weather condition, raw and as deviation from the month's mean."""
    conditions = {
        "dry": ~daily.rain_day,
        "rain": daily.rain_day,
        "heavy rain": daily.heavy_rain_day,
        "TMAX 60-75F": daily.tmax_f.between(60, 75),
        "TMAX >= 85F": daily.tmax_f >= 85,
    }
    ym = daily.date.dt.to_period("M")
    rows = []
    for name, mask in conditions.items():
        row = {"condition": name, "n_days": int(mask.sum())}
        for rider in RIDERS:
            electric, total = daily[f"trips_{rider}_electric"], daily[f"trips_{rider}"]
            share = electric / total
            deviation = share - share.groupby(ym).transform("mean")
            row[f"{rider}_share"] = round(electric[mask].sum() / total[mask].sum(), 4)
            row[f"{rider}_within_month_pp"] = round(100 * deviation[mask].mean(), 2)
        rows.append(row)
    table = pd.DataFrame(rows)
    save_table(table, "ebike_share_by_condition.csv")
    return table.to_dict(orient="records")


def section_e(daily):
    daily = daily.copy()
    daily["rain_class"] = np.select(
        [daily.heavy_rain_day, daily.rain_day], ["heavy rain", "light rain"], default="dry"
    )
    ym = daily.date.dt.to_period("M")
    for rider in RIDERS:
        col = f"trips_{rider}"
        dry_median = daily[col].where(daily.rain_class == "dry").groupby(ym).transform("median")
        daily[f"rel_{rider}"] = daily[col] / dry_median

    rain_effect = daily.groupby("rain_class")[["rel_member", "rel_casual"]].median().round(3)
    rain_counts = daily.rain_class.value_counts()

    fig, axes = plt.subplots(1, 2, figsize=(11, 4), gridspec_kw={"width_ratios": [1.5, 1]})
    ax = axes[0]
    bins = np.arange(15, 105, 5)
    for rider in RIDERS:
        col = f"trips_{rider}"
        color = style.RIDER_COLORS[rider]
        ax.scatter(daily.tmax_f, daily[col], s=7, color=color, alpha=0.25, linewidths=0)
        binned = daily.groupby(pd.cut(daily.tmax_f, bins), observed=True)[col].agg(["median", "size"])
        binned = binned[binned["size"] >= 5]
        centers = [interval.mid for interval in binned.index]
        ax.plot(centers, binned["median"], color=color, marker="o", markersize=4,
                label=f"{rider} (median per 5 °F bin)")
    ax.set_yscale("log")
    ax.set_yticks([2000, 5000, 10000, 20000, 50000, 100000, 150000],
                  ["2k", "5k", "10k", "20k", "50k", "100k", "150k"])
    ax.minorticks_off()
    ax.set_xlabel("daily maximum temperature, Central Park (°F)")
    ax.set_ylabel("trips per day (log scale)")
    ax.set_title("Ridership rises with temperature and flattens when hot")
    ax.legend(loc="lower right")

    ax = axes[1]
    classes = ["dry", "light rain", "heavy rain"]
    for offset, rider in zip((-0.2, 0.2), RIDERS):
        data = [daily.loc[daily.rain_class == c, f"rel_{rider}"].dropna() for c in classes]
        color = style.RIDER_COLORS[rider]
        ax.boxplot(
            data, positions=np.arange(3) + offset, widths=0.34, patch_artist=True, showfliers=False,
            boxprops={"facecolor": color, "edgecolor": color, "alpha": 0.85},
            medianprops={"color": style.SURFACE, "linewidth": 1.5},
            whiskerprops={"color": color}, capprops={"color": color},
        )
    ax.axhline(1, color=style.TEXT_MUTED, linewidth=1, linestyle=(0, (4, 3)))
    ax.set_xticks(range(3), [f"{c}\n(n={rain_counts[c]})" for c in classes])
    ax.set_ylabel("trips relative to same-month dry-day median")
    ax.set_title("Rain cuts casual trips more than member trips")
    ax.legend(
        handles=[plt.Rectangle((0, 0), 1, 1, color=style.RIDER_COLORS[r]) for r in RIDERS],
        labels=RIDERS, loc="lower left",
    )
    fig.tight_layout()
    style.save(fig, "fig05_weather_response.png")

    tables, models = [], {}
    for group in RIDERS + [f"{r}_{b}" for r in RIDERS for b in BIKES]:
        table, models[group] = fit_weather_model(daily, group)
        tables.append(table)
    save_table(pd.concat(tables), "preliminary_regression.csv")
    by_bike = {g: m for g, m in models.items() if g not in RIDERS}
    save_table(
        pd.DataFrame(
            [
                {
                    "group": g, "tmax_f": m["tmax_f"][0], "tmax_f_squared": m["tmax_f_squared"][0],
                    "pct_per_f_at_50f": m["pct_per_f_at_50f"], "pct_per_f_at_80f": m["pct_per_f_at_80f"],
                    "rain_pct": m["rain_pct_effect"][0], "rain_pct_ci_low": m["rain_pct_effect"][1],
                    "rain_pct_ci_high": m["rain_pct_effect"][2], "r_squared": m["r_squared"],
                }
                for g, m in models.items()
            ]
        ),
        "regression_by_rider_and_bike.csv",
    )

    return {
        "tmax_f": {k: round(v, 1) for k, v in daily.tmax_f.agg(["min", "median", "max"]).items()},
        "tmin_f": {k: round(v, 1) for k, v in daily.tmin_f.agg(["min", "median", "max"]).items()},
        "awnd_mph": {k: round(v, 1) for k, v in daily.awnd_mph.agg(["min", "median", "max"]).items()},
        "days": int(len(daily)),
        "rain_days": int(daily.rain_day.sum()),
        "heavy_rain_days": int(daily.heavy_rain_day.sum()),
        "trace_only_days": int((daily.prcp_trace & ~daily.rain_day).sum()),
        "snow_days": int(daily.snow_day.sum()),
        "snow_days_ge_1in": int((daily.snow_mm >= 25.4).sum()),
        "snow_depth_days": int((daily.snwd_mm > 0).sum()),
        "days_tmax_ge_90f": int((daily.tmax_f >= 90).sum()),
        "days_tmax_le_32f": int((daily.tmax_f <= 32).sum()),
        "rain_days_by_year": daily.groupby(daily.date.dt.year).rain_day.sum().to_dict(),
        "heavy_rain_weekend_days": int((daily.heavy_rain_day & daily.is_weekend).sum()),
        "holidays": int(daily.is_holiday.sum()),
        "median_trips_relative_to_same_month_dry_median": rain_effect.to_dict(orient="index"),
        "preliminary_regression": {g: models[g] for g in RIDERS},
        "regression_by_rider_and_bike": by_bike,
        "ebike_share_by_condition": ebike_share_by_condition(daily),
    }


# --------------------------------------------------------------------------- F


def section_f(stations, station_month):
    panel = station_month.merge(stations[["station_id", "in_zone", "months_active"]], on="station_id")
    panel["zone"] = np.where(panel.in_zone, "inside", "outside")
    panel["year"] = panel.ym.str[:4]
    panel["month"] = panel.ym.str[4:].astype(int)

    def indexed(df):
        monthly = df.groupby(["zone", "ym"]).trips.sum().unstack("zone")
        return 100 * monthly / monthly[monthly.index.str.startswith("2024")].mean()

    def yoy(df):
        by = df.groupby(["zone", "year", "month"]).trips.sum().unstack("year")
        return (100 * (by["2025"] / by["2024"] - 1)).unstack("zone")

    constant = panel[panel.months_active == 24]
    index_all = indexed(panel)
    yoy_all, yoy_constant = yoy(panel), yoy(constant)
    save_table(index_all.reset_index(), "zone_monthly_index.csv")
    save_table(
        yoy_all.add_suffix("_all").join(yoy_constant.add_suffix("_constant")).reset_index(),
        "zone_yoy_change.csv",
    )

    colors = {"inside": style.INSIDE, "outside": style.OUTSIDE}
    fig, axes = plt.subplots(1, 2, figsize=(11, 3.8))
    ax = axes[0]
    dates = pd.to_datetime(index_all.index, format="%Y%m")
    for zone in ("inside", "outside"):
        ax.plot(dates, index_all[zone], color=colors[zone], marker="o", markersize=3,
                label=f"starts {zone} the zone")
    mark_pricing_start(ax)
    month_axis(ax)
    ax.set_ylabel("monthly trips (2024 monthly mean = 100)")
    ax.set_title("Monthly trip starts indexed to 2024, all stations")
    ax.legend(fontsize=8, ncols=2, loc="upper center", bbox_to_anchor=(0.5, -0.2))

    ax = axes[1]
    months = yoy_all.index
    for zone in ("inside", "outside"):
        ax.plot(months, yoy_all[zone], color=colors[zone], marker="o", markersize=3,
                label=f"{zone}, all stations")
        ax.plot(months, yoy_constant[zone], color=colors[zone], linestyle=(0, (4, 2)), linewidth=1.5,
                label=f"{zone}, stations active all 24 months")
    ax.axhline(0, color=style.TEXT_MUTED, linewidth=1)
    ax.set_xticks(range(1, 13), list("JFMAMJJASOND"))
    ax.yaxis.set_major_formatter(lambda v, _: f"{v:+.0f}%")
    ax.set_ylabel("2025 vs same month of 2024")
    ax.set_title("Year-over-year change by calendar month")
    ax.legend(fontsize=8, ncols=2, loc="upper center", bbox_to_anchor=(0.5, -0.2))
    fig.tight_layout()
    style.save(fig, "fig06_congestion_zone.png")

    fig, ax = plt.subplots(figsize=(6, 7.5))
    for in_zone, zone in ((False, "outside"), (True, "inside")):
        part = stations[stations.in_zone == in_zone]
        ax.scatter(part.lng, part.lat, s=3, color=colors[zone], label=f"{zone} ({len(part):,})")
    ax.set_aspect(1 / np.cos(np.radians(40.74)))
    ax.set_xlabel("longitude")
    ax.set_ylabel("latitude")
    ax.set_title("Start stations classified by the MTA congestion relief zone polygon")
    ax.legend(markerscale=4)
    style.save(fig, "extra_station_zone_map.png")

    def by_year(df):
        return df.groupby(["zone", "year"]).trips.sum().unstack("year")

    sensitivity = []
    base = station_month.merge(
        stations[["station_id", "in_zone_polygon", "zone_boundary_m", "months_active"]], on="station_id"
    )
    base["year"] = base.ym.str[:4]
    for buffer_m in config.ZONE_BUFFER_SENSITIVITY_M:
        inside = base.in_zone_polygon | (base.zone_boundary_m <= buffer_m)
        row = {"buffer_m": buffer_m, "stations_inside": int(base.station_id[inside].nunique())}
        for label, mask in (("all", slice(None)), ("constant", base.months_active == 24)):
            trips = base[mask].groupby([inside[mask].map({True: "inside", False: "outside"}), "year"])
            trips = trips.trips.sum().unstack("year")
            yoy_pct = 100 * (trips["2025"] / trips["2024"] - 1)
            row[f"yoy_inside_{label}_pct"] = round(yoy_pct["inside"], 2)
            row[f"yoy_outside_{label}_pct"] = round(yoy_pct["outside"], 2)
            row[f"gap_{label}_pp"] = round(yoy_pct["inside"] - yoy_pct["outside"], 2)
        sensitivity.append(row)
    save_table(pd.DataFrame(sensitivity), "zone_buffer_sensitivity.csv")

    trips_all, trips_constant = by_year(panel), by_year(constant)
    stations_by_year = panel.groupby(["zone", "year"]).station_id.nunique().unstack("year")
    return {
        "buffer_sensitivity": sensitivity,
        "stations_inside": int(stations.in_zone.sum()),
        "stations_inside_by_buffer_only": int((stations.in_zone & ~stations.in_zone_polygon).sum()),
        "stations_within_150m_of_boundary": int((stations.zone_boundary_m <= 150).sum()),
        "stations_outside": int((~stations.in_zone).sum()),
        "stations_active_by_zone_year": stations_by_year.to_dict(orient="index"),
        "stations_active_all_24_months_by_zone": constant.drop_duplicates("station_id")
        .zone.value_counts().to_dict(),
        "trips_by_zone_year": trips_all.to_dict(orient="index"),
        "yoy_pct_all_stations": (100 * (trips_all["2025"] / trips_all["2024"] - 1)).round(2).to_dict(),
        "yoy_pct_constant_stations": (
            100 * (trips_constant["2025"] / trips_constant["2024"] - 1)
        ).round(2).to_dict(),
        "inside_share_of_trips_by_year": (trips_all.loc["inside"] / trips_all.sum()).round(4).to_dict(),
        "yoy_pct_by_month_all_stations": yoy_all.round(1).to_dict(orient="index"),
    }


def q4_comparison(daily, station_month):
    """Descriptive Q4 2024 vs Q4 2025 comparison for the late-2025 year-over-year decline."""
    rows = {}
    for year in (2024, 2025):
        days = daily[(daily.date.dt.year == year) & (daily.date.dt.month >= 10)]
        months = station_month[station_month.ym.isin([f"{year}{m}" for m in (10, 11, 12)])]
        rows[f"Q4 {year}"] = {
            "trips_total": int(days.trips_total.sum()),
            "trips_member": int(days.trips_member.sum()),
            "trips_casual": int(days.trips_casual.sum()),
            "mean_tmax_f": round(days.tmax_f.mean(), 1),
            "mean_tmin_f": round(days.tmin_f.mean(), 1),
            "rain_days": int(days.rain_day.sum()),
            "heavy_rain_days": int(days.heavy_rain_day.sum()),
            "total_prcp_in": round(days.prcp_in.sum(), 2),
            "snow_days": int(days.snow_day.sum()),
            "days_tmax_le_40f": int((days.tmax_f <= 40).sum()),
            "mean_monthly_active_stations": round(months.groupby("ym").station_id.nunique().mean(), 0),
            "electric_share": round(months.electric.sum() / months.trips.sum(), 4),
            "member_share": round(days.trips_member.sum() / days.trips_total.sum(), 4),
        }
    table = pd.DataFrame(rows)
    table["change"] = table["Q4 2025"] - table["Q4 2024"]
    monthly = daily[daily.date.dt.month >= 10].groupby(
        [daily.date.dt.year.rename("year"), daily.date.dt.month.rename("month")]
    ).agg(trips=("trips_total", "sum"), mean_tmax_f=("tmax_f", "mean"), rain_days=("rain_day", "sum"),
          snow_days=("snow_day", "sum"))
    save_table(table, "q4_comparison.csv", index=True)
    save_table(monthly.round(1).reset_index(), "q4_comparison_by_month.csv")
    return {
        "by_quarter": table.to_dict(),
        "by_month": json.loads(monthly.round(1).reset_index().to_json(orient="records")),
    }


def main():
    config.TABLES_DIR.mkdir(parents=True, exist_ok=True)
    style.apply()
    con = config.connect()
    clean = f"read_parquet('{config.TRIPS_CLEAN_DIR}/**/*.parquet', hive_types = {{'ym': VARCHAR}})"

    stations = pd.read_parquet(config.STATIONS_PARQUET)
    stations["first_trip_date"] = pd.to_datetime(stations.first_trip_date)
    daily = pd.read_parquet(config.DAILY_PARQUET)
    station_month = con.execute(
        f"""
        SELECT start_station_id AS station_id, ym, count(*) AS trips,
               count(*) FILTER (WHERE rideable_type = 'electric_bike') AS electric,
               count(*) FILTER (WHERE member_casual = 'member') AS member
        FROM {clean} GROUP BY 1, 2
        """
    ).fetchdf()
    station_month.to_parquet(config.PROCESSED_DIR / "station_month.parquet", index=False)

    metrics = {
        "A_collection_and_boundaries": section_a(con),
        "B_data_quality": section_b(con),
        "C_scale_and_categories": section_c(con, clean, stations, station_month),
        "D_temporal_patterns": section_d(con, clean, daily),
        "E_weather": section_e(daily),
        "F_congestion_pricing": section_f(stations, station_month),
        "Q4_yoy_check": q4_comparison(daily, station_month),
    }
    config.METRICS_JSON.write_text(json.dumps(metrics, indent=2, default=str))
    print(f"wrote {config.METRICS_JSON}")


if __name__ == "__main__":
    main()
