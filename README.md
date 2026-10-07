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

`data/` is git-ignored. Raw files are never modified. Findings and proposal draft text are in
[`summary.md`](summary.md).

## Data sources

- Citi Bike trip histories: https://s3.amazonaws.com/tripdata/index.html
- NOAA GHCN-Daily, station USW00094728 (NY City Central Park)
- MTA Central Business District geofence: https://data.ny.gov/d/srxy-5nxn
