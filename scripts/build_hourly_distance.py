"""Checkpoint 3 hourly table: trip starts per hour x bike x rider x trip context x distance band.

Combines the context markers of build_hourly_panel.py (round trip, start/end inside the CBD) with the
station-to-station distance bands of build_distance_table.py, so the distance gradient can be estimated
within trip-purpose groups. Trips with no end station are dropped (no distance).

Output: data/processed/hourly_trips_distance.parquet (non-empty cells only; zeros filled in analysis).
"""

import numpy as np
import pandas as pd

import config

OUT = config.PROCESSED_DIR / "hourly_trips_distance.parquet"


def main():
    con = config.connect()
    st = pd.read_parquet(config.STATIONS_PARQUET)[["station_id", "lat", "lng", "in_zone", "months_active"]]
    st["main"] = st.months_active == len(config.MONTHS)
    con.register("st", st)
    df = con.execute(
        f"""
        WITH t AS (
            SELECT started_at, rideable_type, member_casual, s.main,
                   s.in_zone AS z1, e.in_zone AS z2,
                   s.lat AS lat1, s.lng AS lng1, e.lat AS lat2, e.lng AS lng2,
                   t.start_station_id = t.end_station_id AS rt
            FROM read_parquet('{config.TRIPS_CLEAN_DIR}/**/*.parquet') t
            JOIN st s ON s.station_id = t.start_station_id
            JOIN st e ON e.station_id = t.end_station_id
            WHERE started_at::DATE BETWEEN DATE '{config.STUDY_START}' AND DATE '{config.STUDY_END}'
        ), d AS (
            SELECT *, CASE WHEN rt THEN 0.0 ELSE
                2 * 6371.0 * asin(sqrt(pow(sin(radians(lat2 - lat1) / 2), 2)
                    + cos(radians(lat1)) * cos(radians(lat2)) * pow(sin(radians(lng2 - lng1) / 2), 2)))
                END AS km
            FROM t
        )
        SELECT started_at::DATE AS date, hour(started_at)::TINYINT AS hour,
               (rideable_type = 'electric_bike')::TINYINT AS ebike,
               (member_casual = 'casual')::TINYINT AS casual,
               main, rt::TINYINT AS round_trip, z1::TINYINT AS start_zone, z2::TINYINT AS end_zone,
               CASE WHEN rt THEN 'round' WHEN km < 1 THEN 'lt1' WHEN km < 2 THEN '1_2'
                    WHEN km < 3 THEN '2_3' WHEN km < 5 THEN '3_5' ELSE 'ge5' END AS band,
               count(*)::INTEGER AS trips, sum(km) AS km
        FROM d GROUP BY ALL
        """
    ).fetchdf()
    df["date"] = pd.to_datetime(df.date)
    for c in ("round_trip", "start_zone", "end_zone"):
        df[c] = df[c].astype(np.int8)
    df.to_parquet(OUT, index=False)
    print(len(df), "rows;", int(df.trips.sum()), "trips;", int(df[df.main].trips.sum()), "in main panel")
    print((df[df.main].groupby("band").trips.sum() / df[df.main].trips.sum()).round(3))


if __name__ == "__main__":
    main()
