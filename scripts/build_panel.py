"""Build the Checkpoint 1 panel: station x date x bike type x rider type, trip starts, zeros included.

Main sample: stations with at least one trip start in each of the 24 months, observed on all 731 days
(a balanced panel). Full sample: every station, observed from its first to its last trip start date
(days before a station opened or after it closed are not counted as zeros).

Also writes the daily calendar + weather table with the temperature bins.
"""

import holidays
import numpy as np
import pandas as pd

import config
import cp1_common as cp


def build_calendar():
    w = pd.read_parquet(config.WEATHER_PARQUET)
    cal = pd.DataFrame({"date": pd.to_datetime(w.date)})
    cal["date_id"] = np.arange(len(cal), dtype=np.int32)
    cal["year"] = cal.date.dt.year.astype(np.int16)
    cal["year_month"] = (cal.date.dt.year * 100 + cal.date.dt.month).astype(np.int32)
    cal["quarter"] = cal.date.dt.year.astype(str) + "Q" + cal.date.dt.quarter.astype(str)
    cal["half"] = cal.date.dt.year.astype(str) + "H" + np.where(cal.date.dt.month <= 6, "1", "2")
    cal["weekday"] = cal.date.dt.dayofweek.astype(np.int8)  # 0 = Monday
    cal["is_weekend"] = (cal.weekday >= 5).astype(np.int8)
    # ISO-like week id for week-clustered SEs (weeks start Monday; partial weeks at the edges).
    cal["week_id"] = ((cal.date - pd.Timestamp("2023-12-25")).dt.days // 7).astype(np.int16)
    us = holidays.US(years=[2024, 2025])
    cal["holiday"] = cal.date.dt.date.map(lambda d: d in us).astype(np.int8)
    cal["holiday_name"] = cal.date.dt.date.map(us.get)
    cal["tmax_c"] = w.tmax_c.to_numpy()
    cal["prcp_in"] = w.prcp_in.to_numpy()
    cal["snow_mm"] = w.snow_mm.to_numpy()
    cal["awnd_ms"] = w.awnd_ms.to_numpy()
    for name, thr in cp.RAIN_THRESHOLDS_IN.items():
        cal[name] = ((cal.prcp_in > 0) if thr == 0 else (cal.prcp_in >= thr - 1e-9)).astype(np.int8)
    cal["rain"] = cal.rain_any
    cal["snow"] = (cal.snow_mm > 0).astype(np.int8)
    cal["tbin"], bins = cp.make_temperature_bins(cal.tmax_c)
    return cal, bins


def build_panel(con, cal):
    stations = pd.read_parquet(config.STATIONS_PARQUET)
    stations = stations.sort_values("station_id").reset_index(drop=True)
    stations["station"] = np.arange(len(stations), dtype=np.int32)
    stations["main"] = stations.months_active == len(config.MONTHS)
    stations["first"] = np.where(stations.main, pd.Timestamp(config.STUDY_START),
                                 pd.to_datetime(stations.first_trip_date))
    stations["last"] = np.where(stations.main, pd.Timestamp(config.STUDY_END),
                                pd.to_datetime(stations.last_trip_date))
    con.register("st", stations[["station", "station_id", "main", "first", "last"]])
    con.register("cal", cal[["date", "date_id"]])
    panel = con.execute(
        f"""
        WITH counts AS (
            SELECT start_station_id AS station_id, started_at::DATE AS date,
                   (rideable_type = 'electric_bike')::TINYINT AS ebike,
                   (member_casual = 'casual')::TINYINT AS casual,
                   count(*)::INTEGER AS trips
            FROM read_parquet('{config.TRIPS_CLEAN_DIR}/**/*.parquet')
            GROUP BY ALL
        ),
        grid AS (
            SELECT st.station, st.station_id, st.main, cal.date_id, cal.date, b.ebike, r.casual
            FROM st
            JOIN cal ON cal.date BETWEEN st.first AND st.last
            CROSS JOIN (VALUES (0::TINYINT), (1::TINYINT)) b(ebike)
            CROSS JOIN (VALUES (0::TINYINT), (1::TINYINT)) r(casual)
        )
        SELECT g.station, g.date_id, g.ebike, g.casual, coalesce(c.trips, 0)::INTEGER AS trips, g.main
        FROM grid g
        LEFT JOIN counts c ON c.station_id = g.station_id AND c.date = g.date
                          AND c.ebike = g.ebike AND c.casual = g.casual
        ORDER BY g.station, g.date_id, g.ebike, g.casual
        """
    ).fetchdf()
    n_clean = con.execute(
        f"SELECT count(*) FROM read_parquet('{config.TRIPS_CLEAN_DIR}/**/*.parquet')"
    ).fetchone()[0]
    return panel, stations, n_clean


def by_group(df, col):
    s = df.groupby(["ebike", "casual"])[col].mean()
    return {f"ebike{e}_casual{c}": float(v) for (e, c), v in s.items()}


def main():
    cp.ensure_dirs()
    con = config.connect()
    cal, bins = build_calendar()
    cal.to_parquet(cp.CALENDAR_PARQUET, index=False)
    bins.to_csv(cp.TAB_DIR / "temperature_bins.csv", index=False)

    panel, stations, n_clean = build_panel(con, cal)
    for col, dtype in {"station": np.int32, "date_id": np.int16, "ebike": np.int8,
                       "casual": np.int8, "trips": np.int32}.items():
        panel[col] = panel[col].astype(dtype)
    panel.to_parquet(cp.PANEL_PARQUET, index=False)
    stations[["station", "station_id", "station_name", "main", "months_active", "first", "last",
              "n_trips"]].to_csv(cp.TAB_DIR / "panel_stations.csv", index=False)

    main_p = panel[panel.main]
    station_day = panel.groupby(["station", "date_id"], observed=True).trips.sum()
    main_day = main_p.groupby(["station", "date_id"]).trips.sum()
    metrics = {
        "n_stations_full": int(stations.station.nunique()),
        "n_stations_main": int(stations.main.sum()),
        "n_days": int(len(cal)),
        "rows_full": int(len(panel)),
        "rows_main": int(len(main_p)),
        "trips_in_panel_full": int(panel.trips.sum()),
        "trips_clean_table": int(n_clean),
        "trips_in_panel_main": int(main_p.trips.sum()),
        "share_trips_main": float(main_p.trips.sum() / panel.trips.sum()),
        "zero_cell_share_full": float((panel.trips == 0).mean()),
        "zero_cell_share_main": float((main_p.trips == 0).mean()),
        "zero_station_days_full": int((station_day == 0).sum()),
        "zero_station_days_main": int((main_day == 0).sum()),
        "station_days_main": int(len(main_day)),
        "zero_cell_share_main_by_group": by_group(main_p.assign(z=main_p.trips == 0), "z"),
        "mean_trips_per_cell_main_by_group": by_group(main_p, "trips"),
        "temperature_bins": bins.to_dict(orient="records"),
        "holidays": int(cal.holiday.sum()),
        "rain_days": {k: int(cal[k].sum()) for k in cp.RAIN_THRESHOLDS_IN},
        "snow_days": int(cal.snow.sum()),
        "awnd_missing_days": cal.loc[cal.awnd_ms.isna(), "date"].dt.date.astype(str).tolist(),
    }
    if metrics["trips_in_panel_full"] != n_clean:
        raise ValueError("panel trip total does not match the clean trip table")
    cp.save_metrics("panel.json", metrics)

    print(bins.to_string(index=False))
    for k, v in metrics.items():
        if k not in ("temperature_bins",):
            print(f"{k}: {v}")


if __name__ == "__main__":
    main()
