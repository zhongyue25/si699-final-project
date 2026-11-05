"""Checkpoint 2 hourly table: trip starts per local clock hour x bike type x rider type x trip context.

Trip-context proxies (rider type is not trip purpose, so we look at what the trip itself looks like):
  round_trip   start station = end station (a classic marker of leisure riding)
  start_zone   start station inside the Manhattan Central Business District (south of 60 St)
  end_zone     end station inside the CBD; -1 if the trip has no end station
Main = the Checkpoint 1 balanced panel (stations active in all 24 months); the table keeps both.

Output: data/processed/hourly_trips.parquet (one row per non-empty cell; zeros are filled in analysis).
"""

import numpy as np
import pandas as pd

import config

OUT = config.PROCESSED_DIR / "hourly_trips.parquet"


def main():
    con = config.connect()
    st = pd.read_parquet(config.STATIONS_PARQUET)[["station_id", "in_zone", "months_active"]]
    st["main"] = st.months_active == len(config.MONTHS)
    con.register("st", st)
    df = con.execute(
        f"""
        SELECT started_at::DATE AS date, hour(started_at)::TINYINT AS hour,
               (rideable_type = 'electric_bike')::TINYINT AS ebike,
               (member_casual = 'casual')::TINYINT AS casual,
               coalesce(s.main, false) AS main,
               (t.start_station_id = t.end_station_id)::TINYINT AS round_trip,
               coalesce(s.in_zone, false)::TINYINT AS start_zone,
               CASE WHEN e.station_id IS NULL THEN -1 ELSE e.in_zone::TINYINT END AS end_zone,
               count(*)::INTEGER AS trips,
               sum(duration_s)::DOUBLE AS dur_s
        FROM read_parquet('{config.TRIPS_CLEAN_DIR}/**/*.parquet') t
        LEFT JOIN st s ON s.station_id = t.start_station_id
        LEFT JOIN st e ON e.station_id = t.end_station_id
        WHERE started_at::DATE BETWEEN DATE '{config.STUDY_START}' AND DATE '{config.STUDY_END}'
        GROUP BY ALL
        """
    ).fetchdf()
    df["date"] = pd.to_datetime(df.date)
    for c in ("round_trip", "start_zone", "end_zone"):
        df[c] = df[c].fillna(0).astype(np.int8)
    df.to_parquet(OUT, index=False)
    print(len(df), "rows;", int(df.trips.sum()), "trips;", int(df[df.main].trips.sum()), "in main panel")
    print(df.groupby("casual").apply(lambda g: (g.trips * g.round_trip).sum() / g.trips.sum()))


if __name__ == "__main__":
    main()
