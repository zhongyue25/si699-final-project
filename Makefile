PYTHON ?= .venv/bin/python

.PHONY: all download parquet weather clean-trips tables eda \
	panel finding1 finding2 finding3 rain-intensity availability checkpoint1 \
	weather-hourly hourly-panel sample-checks finding4 distance checkpoint2 \
	purpose-ebike hourly-distance purpose-distance checkpoint3

all: download parquet weather clean-trips tables eda checkpoint1 checkpoint2 checkpoint3

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
checkpoint1: panel finding1 finding2 finding3 rain-intensity availability

panel:
	$(PYTHON) scripts/build_panel.py

finding1: panel
	$(PYTHON) scripts/cp1_finding1.py

finding2: panel
	$(PYTHON) scripts/cp1_finding2.py

finding3: panel
	$(PYTHON) scripts/cp1_finding3.py

rain-intensity: panel
	$(PYTHON) scripts/cp1_rain_intensity.py

availability: panel
	$(PYTHON) scripts/cp1_availability.py

# Checkpoint 2: hourly weather, trip context, sample checks (needs checkpoint1's panel)
checkpoint2: weather-hourly hourly-panel sample-checks finding4 distance

weather-hourly:
	$(PYTHON) scripts/build_weather_hourly.py

hourly-panel:
	$(PYTHON) scripts/build_hourly_panel.py

sample-checks: panel weather-hourly
	$(PYTHON) scripts/cp2_sample_checks.py

finding4: weather-hourly hourly-panel
	$(PYTHON) scripts/cp2_finding4.py

distance:
	$(PYTHON) scripts/build_distance_table.py
	$(PYTHON) scripts/cp2_distance.py

# Checkpoint 3: trip purpose x bike type (needs the hourly panel from checkpoint2)
checkpoint3: purpose-ebike purpose-distance

purpose-ebike: weather-hourly hourly-panel
	$(PYTHON) scripts/cp3_purpose_ebike.py
	$(PYTHON) scripts/cp3_purpose_ebike.py --stress

hourly-distance:
	$(PYTHON) scripts/build_hourly_distance.py

purpose-distance: weather-hourly hourly-distance
	$(PYTHON) scripts/cp3_purpose_distance.py
	$(PYTHON) scripts/cp3_purpose_distance.py --stress
