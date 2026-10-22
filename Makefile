PYTHON ?= .venv/bin/python

.PHONY: all download parquet weather clean-trips tables eda \
	panel finding1 finding2 finding3 availability checkpoint1

all: download parquet weather clean-trips tables eda checkpoint1

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

# Checkpoint 1: weather x bike type x rider type (needs the clean trips from clean-trips/tables)
checkpoint1: panel finding1 finding2 finding3 availability

panel:
	$(PYTHON) scripts/build_panel.py

finding1: panel
	$(PYTHON) scripts/cp1_finding1.py

finding2: panel
	$(PYTHON) scripts/cp1_finding2.py

finding3: panel
	$(PYTHON) scripts/cp1_finding3.py

availability: panel
	$(PYTHON) scripts/cp1_availability.py
