"""Hourly weather for Central Park from NOAA Local Climatological Data (LCD v2, station USW00094728).

LCD v2 is metric (precipitation in mm, temperature in degC) and its DATE column is local clock time
(it skips 02:51 on the spring DST date and repeats 01:51 in November), the same clock as Citi Bike's
started_at.

Hour h (local clock) gets:
  precip_mm   from the routine FM-15 report at about h:51, which covers the 60 minutes ending then
              (51 of them inside hour h). If the routine report is missing, the largest special (FM-16)
              accumulation in the same window is used. 'T' (trace) is coded as 0.1 mm.
  rain / snow from the present-weather codes of every FM-15 and FM-16 report in the window
              (h-1):52 to h:51. Snow = SN, SG, PL (snow, snow grains, ice pellets); rain = RA, DZ (incl.
              freezing rain and drizzle), only if no snow code.
  temp_c      dry-bulb temperature at the routine report.

Writes data/processed/weather_hourly.parquet and a daily cross-check against GHCN-Daily.
"""

import re

import numpy as np
import pandas as pd

import config

RAW = config.RAW_DIR / "noaa_hourly"
URL = ("https://www.ncei.noaa.gov/oa/local-climatological-data/v2/access/{year}/"
       "LCD_USW00094728_{year}.csv")
OUT = config.PROCESSED_DIR / "weather_hourly.parquet"
TRACE_MM = 0.1
COLS = ["DATE", "REPORT_TYPE", "HourlyPrecipitation", "HourlyPresentWeatherType",
        "HourlyDryBulbTemperature", "HourlyWindSpeed"]
SNOW_RE = re.compile(r"(SN|SG|PL)")
RAIN_RE = re.compile(r"(RA|DZ)")


def download():
    import urllib.request

    RAW.mkdir(parents=True, exist_ok=True)
    for y in (2024, 2025):
        path = RAW / f"LCD_USW00094728_{y}.csv"
        if not path.exists():
            urllib.request.urlretrieve(URL.format(year=y), path)


def num(s):
    s = s.astype("string").str.strip().str.rstrip("s")  # 's' = suspect flag
    return pd.to_numeric(s.replace("T", str(TRACE_MM)), errors="coerce")


def codes(s):
    """First block of the present-weather field (AU codes), e.g. '-RA:02 BR:1 |RA BR |RA' -> '-RA BR'."""
    return s.fillna("").str.split("|").str[0].str.replace(r":\d+", "", regex=True).str.strip()


def main():
    download()
    raw = pd.concat([pd.read_csv(RAW / f"LCD_USW00094728_{y}.csv", usecols=COLS, low_memory=False)
                     for y in (2024, 2025)], ignore_index=True)
    obs = raw[raw.REPORT_TYPE.isin(["FM-15", "FM-16"])].copy()
    obs["ts"] = pd.to_datetime(obs.DATE)
    # Window (h-1):52 .. h:51 -> hour h.
    obs["hour_ts"] = (obs.ts + pd.Timedelta(minutes=8)).dt.floor("h")
    obs["precip"] = num(obs.HourlyPrecipitation)
    obs["temp"] = num(obs.HourlyDryBulbTemperature)
    obs["wind"] = num(obs.HourlyWindSpeed)
    wx = codes(obs.HourlyPresentWeatherType)
    obs["snow_code"] = wx.str.contains(SNOW_RE)
    obs["rain_code"] = wx.str.contains(RAIN_RE)

    routine = obs[obs.REPORT_TYPE == "FM-15"].groupby("hour_ts").agg(
        precip_routine=("precip", "sum"), n_routine=("precip", "size"),
        precip_routine_na=("precip", lambda s: s.isna().all()), temp_c=("temp", "mean"),
        wind_ms=("wind", "mean"))
    special = obs[obs.REPORT_TYPE == "FM-16"].groupby("hour_ts").precip.max().rename("precip_special")
    wxh = obs.groupby("hour_ts").agg(snow_code=("snow_code", "any"), rain_code=("rain_code", "any"))

    hours = pd.DataFrame({"hour_ts": pd.date_range(config.STUDY_START, f"{config.STUDY_END} 23:00",
                                                   freq="h")})
    h = hours.join(routine, on="hour_ts").join(special, on="hour_ts").join(wxh, on="hour_ts")
    h["precip_mm"] = np.where(h.precip_routine_na.fillna(True), h.precip_special, h.precip_routine)
    h["precip_source"] = np.where(h.precip_routine_na.fillna(True),
                                  np.where(h.precip_special.notna(), "special", "missing"), "routine")
    h["precip_mm"] = h.precip_mm.fillna(0.0)
    h[["snow_code", "rain_code"]] = h[["snow_code", "rain_code"]].fillna(False).astype(bool)
    h["temp_c"] = h.temp_c.interpolate(limit=3)
    h["wind_ms"] = h.wind_ms.interpolate(limit=3)
    h["wet"] = (h.precip_mm > 0).astype(np.int8)                 # any precipitation incl. trace
    h["wet_meas"] = (h.precip_mm >= 0.25).astype(np.int8)        # measurable (>= 0.01 in)
    h["wet_heavy"] = (h.precip_mm >= 2.5).astype(np.int8)        # >= 0.1 in/hour
    h["snow_hour"] = (h.wet.astype(bool) & h.snow_code).astype(np.int8)
    h["rain_hour"] = (h.wet.astype(bool) & ~h.snow_code).astype(np.int8)
    h["date"] = h.hour_ts.dt.normalize()
    h["hour"] = h.hour_ts.dt.hour.astype(np.int8)
    h = h.drop(columns=["precip_routine", "precip_routine_na", "precip_special"])
    h.to_parquet(OUT, index=False)

    # Daily cross-check against GHCN-Daily (the series used in Checkpoint 1).
    g = pd.read_parquet(config.WEATHER_PARQUET)[["date", "prcp_mm", "snow_mm"]]
    g["date"] = pd.to_datetime(g.date)
    day = h.groupby("date").agg(lcd_precip_mm=("precip_mm", "sum"), wet_hours=("wet", "sum"),
                                meas_hours=("wet_meas", "sum"), snow_hours=("snow_hour", "sum"),
                                rain_hours=("rain_hour", "sum"),
                                missing_hours=("precip_source", lambda s: (s == "missing").sum()))
    chk = g.merge(day, left_on="date", right_index=True)
    out_dir = config.TABLES_DIR / "checkpoint2"
    out_dir.mkdir(parents=True, exist_ok=True)
    chk.to_csv(out_dir / "weather_hourly_daily_check.csv", index=False)
    print(h.precip_source.value_counts())
    print("hours:", len(h), "wet:", h.wet.sum(), "measurable:", h.wet_meas.sum(),
          "snow:", h.snow_hour.sum(), "rain:", h.rain_hour.sum())
    print("corr daily precip LCD vs GHCN:", chk[["prcp_mm", "lcd_precip_mm"]].corr().iloc[0, 1].round(4))
    print("GHCN wet days with 0 LCD wet hours:", int(((chk.prcp_mm > 0) & (chk.wet_hours == 0)).sum()),
          "| LCD wet days with GHCN 0:", int(((chk.prcp_mm == 0) & (chk.wet_hours > 0)).sum()))
    print("GHCN snow days:", int((chk.snow_mm > 0).sum()), "| days with LCD snow hours:",
          int((chk.snow_hours > 0).sum()), "| both:", int(((chk.snow_mm > 0) & (chk.snow_hours > 0)).sum()))


if __name__ == "__main__":
    main()
