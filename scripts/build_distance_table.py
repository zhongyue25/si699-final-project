"""Trip distance table (Checkpoint 2 extension).

Citi Bike's start/end coordinates are the station coordinates (one coordinate pair per station in every
month, for classic and e-bikes alike), not GPS traces. Distance is therefore the straight-line
(haversine) distance between the start and end station, a lower bound on the route ridden. Round trips
(same station) have distance 0 and are kept as their own band; trips with no end station are dropped.

Output: data/processed/distance_hourly.parquet with, per date x hour x bike type x rider type x distance
band (main-panel start stations only): trips, summed km, summed duration (s), summed log km.
"""

import numpy as np
import pandas as pd

import config

OUT = config.PROCESSED_DIR / "distance_hourly.parquet"
BANDS_KM = [0, 1, 2, 3, 5]  # band edges; 'round' for same-station trips
BAND_LABELS = ["round", "lt1", "1_2", "2_3", "3_5", "ge5"]


def main():
    con = config.connect()
    st = pd.read_parquet(config.STATIONS_PARQUET)[["station_id", "lat", "lng", "months_active"]]
    st["main"] = st.months_active == len(config.MONTHS)
    con.register("st", st)
    df = con.execute(
        f"""
        WITH t AS (
            SELECT started_at, duration_s, rideable_type, member_casual,
                   s.lat AS lat1, s.lng AS lng1, e.lat AS lat2, e.lng AS lng2,
                   t.start_station_id = t.end_station_id AS rt
            FROM read_parquet('{config.TRIPS_CLEAN_DIR}/**/*.parquet') t
            JOIN st s ON s.station_id = t.start_station_id AND s.main
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
               CASE WHEN rt THEN 'round' WHEN km < 1 THEN 'lt1' WHEN km < 2 THEN '1_2'
                    WHEN km < 3 THEN '2_3' WHEN km < 5 THEN '3_5' ELSE 'ge5' END AS band,
               count(*)::INTEGER AS trips, sum(km) AS km, sum(duration_s) AS dur_s,
               sum(CASE WHEN rt THEN 0 ELSE ln(greatest(km, 0.05)) END) AS logkm
        FROM d GROUP BY ALL
        """
    ).fetchdf()
    df["date"] = pd.to_datetime(df.date)
    df.to_parquet(OUT, index=False)
    tot = df.groupby(["ebike", "casual"]).apply(
        lambda g: pd.Series({"trips": g.trips.sum(),
                             "mean_km_AtoB": g[g.band != "round"].km.sum() / g[g.band != "round"].trips.sum()}),
        include_groups=False)
    print(len(df), "rows;", int(df.trips.sum()), "trips with an end station")
    print(tot)
    print((df.groupby("band").trips.sum() / df.trips.sum()).reindex(BAND_LABELS).round(3))
    print(df.groupby(["band", "ebike"]).trips.sum().unstack().reindex(BAND_LABELS)
          .pipe(lambda x: x[1] / x.sum(axis=1)).round(3).rename("ebike_share"))


if __name__ == "__main__":
    main()
