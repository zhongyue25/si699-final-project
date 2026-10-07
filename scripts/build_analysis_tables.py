"""Build the station table (with congestion-zone flag) and the daily trips + weather table."""

import json

import holidays
import numpy as np
import pandas as pd
from matplotlib.path import Path as PolygonPath

import config


def load_zone_polygons():
    geojson = json.loads(config.RAW_ZONE_GEOJSON.read_text())
    polygons = []
    for feature in geojson["features"]:
        geometry = feature["geometry"]
        parts = (
            geometry["coordinates"]
            if geometry["type"] == "MultiPolygon"
            else [geometry["coordinates"]]
        )
        polygons += [np.array(part[0]) for part in parts]
    return polygons


def distance_to_polygon_m(points, polygon):
    """Distance from each (lng, lat) point to the polygon boundary, local flat-earth metres."""
    scale = np.array([111_320 * np.cos(np.radians(40.74)), 110_540])
    p = points[:, None, :] * scale
    a, b = polygon[:-1] * scale, polygon[1:] * scale
    ab = b - a
    t = np.clip(((p - a) * ab).sum(-1) / (ab * ab).sum(-1), 0, 1)
    nearest = a + ab * t[..., None]
    return np.sqrt(((nearest - p) ** 2).sum(-1)).min(axis=1)


def build_stations(con):
    stations = con.execute(
        f"""
        SELECT
            start_station_id AS station_id,
            mode(start_station_name) AS station_name,
            median(start_lat) AS lat,
            median(start_lng) AS lng,
            min(started_at)::DATE AS first_trip_date,
            max(started_at)::DATE AS last_trip_date,
            count(DISTINCT ym) AS months_active,
            count(*) AS n_trips,
            count(*) FILTER (WHERE year(started_at) = 2024) AS n_trips_2024,
            count(*) FILTER (WHERE year(started_at) = 2025) AS n_trips_2025
        FROM read_parquet('{config.TRIPS_CLEAN_DIR}/**/*.parquet')
        GROUP BY 1
        ORDER BY 1
        """
    ).fetchdf()

    points = stations[["lng", "lat"]].to_numpy()
    in_polygon = np.zeros(len(stations), dtype=bool)
    boundary_m = np.full(len(stations), np.inf)
    for polygon in load_zone_polygons():
        in_polygon |= PolygonPath(polygon).contains_points(points)
        boundary_m = np.minimum(boundary_m, distance_to_polygon_m(points, polygon))
    # Docks on the waterfront edge and on 60th St itself sit a few metres outside the polygon.
    stations["zone_boundary_m"] = boundary_m.round(1)
    stations["in_zone_polygon"] = in_polygon
    stations["in_zone"] = in_polygon | (boundary_m <= config.ZONE_BUFFER_M)
    stations.to_parquet(config.STATIONS_PARQUET, index=False)
    stations.to_csv(config.TABLES_DIR / "stations.csv", index=False)
    return stations


def build_daily(con):
    daily = con.execute(
        f"""
        WITH trips AS (
            SELECT
                started_at::DATE AS date,
                count(*) FILTER (WHERE member_casual = 'member') AS trips_member,
                count(*) FILTER (WHERE member_casual = 'casual') AS trips_casual,
                count(*) FILTER (WHERE rideable_type = 'electric_bike') AS trips_electric,
                count(*) FILTER (WHERE member_casual = 'member' AND rideable_type = 'electric_bike')
                    AS trips_member_electric,
                count(*) FILTER (WHERE member_casual = 'member' AND rideable_type = 'classic_bike')
                    AS trips_member_classic,
                count(*) FILTER (WHERE member_casual = 'casual' AND rideable_type = 'electric_bike')
                    AS trips_casual_electric,
                count(*) FILTER (WHERE member_casual = 'casual' AND rideable_type = 'classic_bike')
                    AS trips_casual_classic,
                count(*) FILTER (WHERE s.in_zone) AS trips_in_zone,
                count(*) AS trips_total,
                count(DISTINCT t.start_station_id) AS active_stations
            FROM read_parquet('{config.TRIPS_CLEAN_DIR}/**/*.parquet') t
            JOIN read_parquet('{config.STATIONS_PARQUET}') s ON t.start_station_id = s.station_id
            GROUP BY 1
        )
        SELECT
            w.date,
            trips.* EXCLUDE (date),
            dayname(w.date) AS weekday,
            isodow(w.date) >= 6 AS is_weekend,
            w.tmax_f, w.tmin_f, w.tmax_c, w.tmin_c, w.prcp_in, w.prcp_mm,
            w.snow_mm, w.snwd_mm, w.awnd_mph, w.awnd_ms,
            coalesce(w.prcp_mflag = 'T', false) AS prcp_trace
        FROM read_parquet('{config.WEATHER_PARQUET}') w
        LEFT JOIN trips USING (date)
        ORDER BY w.date
        """
    ).fetchdf()

    us_holidays = holidays.US(years=[2024, 2025])
    daily["date"] = pd.to_datetime(daily["date"])
    daily["is_holiday"] = daily["date"].dt.date.map(lambda d: d in us_holidays)
    daily["holiday_name"] = daily["date"].dt.date.map(us_holidays.get)
    daily["rain_day"] = daily["prcp_in"] > 0
    daily["heavy_rain_day"] = daily["prcp_in"] >= config.HEAVY_RAIN_IN
    daily["snow_day"] = daily["snow_mm"] > 0

    daily.to_parquet(config.DAILY_PARQUET, index=False)
    daily.to_csv(config.TABLES_DIR / "daily_trips_weather.csv", index=False)
    return daily


def main():
    config.TABLES_DIR.mkdir(parents=True, exist_ok=True)
    con = config.connect()
    stations = build_stations(con)
    daily = build_daily(con)

    print(f"stations: {len(stations):,} ({stations.in_zone.sum():,} inside the zone)")
    print(f"daily rows: {len(daily)}, days without trips: {daily.trips_total.isna().sum()}")


if __name__ == "__main__":
    main()
