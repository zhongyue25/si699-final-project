PYTHON ?= .venv/bin/python

.PHONY: all download parquet weather clean-trips tables eda

all: download parquet weather clean-trips tables eda

download:
	$(PYTHON) scripts/download_data.py

parquet:
	$(PYTHON) scripts/build_trips_parquet.py

weather:
	$(PYTHON) scripts/build_weather.py

clean-trips:
	$(PYTHON) scripts/build_clean_trips.py

tables:
	$(PYTHON) scripts/build_analysis_tables.py

eda:
	$(PYTHON) scripts/run_eda.py
