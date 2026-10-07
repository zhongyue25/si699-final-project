"""Download any raw inputs that are not already on disk. Existing files are never overwritten."""

import urllib.request

import config


def fetch(url, dest):
    if dest.exists():
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    partial = dest.with_suffix(dest.suffix + ".part")
    print(f"downloading {url}")
    urllib.request.urlretrieve(url, partial)
    partial.rename(dest)


def main():
    for month in config.MONTHS + config.SPILLOVER_MONTHS:
        fetch(
            config.TRIPS_URL.format(month=month),
            config.RAW_TRIPS_DIR / f"{month}-citibike-tripdata.zip",
        )
    fetch(config.WEATHER_URL, config.RAW_WEATHER_CSV)
    fetch(config.ZONE_URL, config.RAW_ZONE_GEOJSON)


if __name__ == "__main__":
    main()
