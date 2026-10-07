from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

RAW_DIR = ROOT / "data" / "raw"
RAW_TRIPS_DIR = RAW_DIR / "citibike"
RAW_WEATHER_CSV = RAW_DIR / "noaa" / "USW00094728.csv"
RAW_ZONE_GEOJSON = RAW_DIR / "geo" / "mta_cbd_geofence.geojson"

PROCESSED_DIR = ROOT / "data" / "processed"
TRIPS_RAW_DIR = PROCESSED_DIR / "trips_raw"
TRIPS_CLEAN_DIR = PROCESSED_DIR / "trips_clean"
WEATHER_PARQUET = PROCESSED_DIR / "weather_daily.parquet"
STATIONS_PARQUET = PROCESSED_DIR / "stations.parquet"
DAILY_PARQUET = PROCESSED_DIR / "daily_trips_weather.parquet"
TMP_DIR = PROCESSED_DIR / "_tmp"

FIGURES_DIR = ROOT / "figures"
TABLES_DIR = ROOT / "reports" / "tables"
METRICS_JSON = ROOT / "reports" / "metrics.json"

TRIPS_URL = "https://s3.amazonaws.com/tripdata/{month}-citibike-tripdata.zip"
WEATHER_URL = (
    "https://www.ncei.noaa.gov/data/global-historical-climatology-network-daily/"
    "access/USW00094728.csv"
)
ZONE_URL = "https://data.ny.gov/resource/srxy-5nxn.geojson"

STUDY_START = "2024-01-01"
STUDY_END = "2025-12-31"
MONTHS = [f"{y}{m:02d}" for y in (2024, 2025) for m in range(1, 13)]
# Files are split by trip end month, so December starts that end in January are in the next file.
SPILLOVER_MONTHS = ["202601"]

CONGESTION_PRICING_START = "2025-01-05"
ZONE_BUFFER_M = 50
ZONE_BUFFER_SENSITIVITY_M = [0, 50, 150]
NJ_LNG_CUTOFF = -74.03
MAX_DURATION_S = 24 * 3600
MIN_DURATION_S = 60
HEAVY_RAIN_IN = 0.5

TRIP_COLUMNS = [
    "ride_id",
    "rideable_type",
    "started_at",
    "ended_at",
    "start_station_name",
    "start_station_id",
    "end_station_name",
    "end_station_id",
    "start_lat",
    "start_lng",
    "end_lat",
    "end_lng",
    "member_casual",
]


def connect():
    import duckdb

    TMP_DIR.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.execute(f"SET temp_directory = '{TMP_DIR}'")
    con.execute("SET preserve_insertion_order = false")
    return con
