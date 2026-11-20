# SI 699: Weather, Congestion Pricing and Citi Bike Ridership

How does weather affect NYC Citi Bike ridership, and does the effect differ between members and
casual riders? Extension: did ridership starting inside Manhattan's congestion relief zone change
after congestion pricing began on 2025-01-05?

## Setup

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt
make all
```

`make all` downloads any missing raw files, then runs the pipeline end to end (about 5 minutes
once the raw files are on disk; raw trip archives total ~16 GB).

## Pipeline

| Step | Script | Output |
|---|---|---|
| `make download` | `scripts/download_data.py` | `data/raw/{citibike,noaa,geo}/` (24 months + `202601` for December spillover) |
| `make parquet` | `scripts/build_trips_parquet.py` | `data/processed/trips_raw/`, `reports/tables/file_inventory.csv` |
| `make weather` | `scripts/build_weather.py` | `data/processed/weather_daily.parquet` |
| `make clean-trips` | `scripts/build_clean_trips.py` | `data/processed/trips_clean/`, cleaning tables |
| `make tables` | `scripts/build_analysis_tables.py` | station table with zone flag, daily trips + weather table |
| `make eda` | `scripts/run_eda.py` | `figures/`, `reports/tables/`, `reports/metrics.json` |
| `make checkpoint1` | `scripts/build_panel.py`, `scripts/cp1_*.py` | station-day panel, `figures/checkpoint1/`, `reports/tables/checkpoint1/` (see [`reports/checkpoint1_summary.md`](reports/checkpoint1_summary.md)) |
| `make checkpoint2` | `scripts/build_weather_hourly.py`, `scripts/build_hourly_panel.py`, `scripts/build_distance_table.py`, `scripts/cp2_*.py` | NOAA hourly LCD (`data/raw/noaa_hourly/`), hourly trip table, `figures/checkpoint2/`, `reports/tables/checkpoint2/` |
| `make checkpoint3` | `scripts/build_hourly_distance.py`, `scripts/cp3_*.py` | hourly trip table with context and distance band, `figures/checkpoint3/`, `reports/tables/checkpoint3/` |

`data/` is git-ignored. Raw files are never modified. Findings and proposal draft text are in
[`summary.md`](summary.md).

## Data sources

- Citi Bike trip histories: https://s3.amazonaws.com/tripdata/index.html
- NOAA GHCN-Daily, station USW00094728 (NY City Central Park)
- NOAA Local Climatological Data v2 (hourly), same station: https://www.ncei.noaa.gov/oa/local-climatological-data/v2/
- MTA Central Business District geofence: https://data.ny.gov/d/srxy-5nxn
