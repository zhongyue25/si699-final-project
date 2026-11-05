"""Shared helpers for the Checkpoint 2 analyses (hourly weather, trip context, sample checks)."""

import numpy as np
import pandas as pd

import config
import cp1_common as cp

FIG_DIR = config.FIGURES_DIR / "checkpoint2"
TAB_DIR = config.TABLES_DIR / "checkpoint2"
HOURLY_TRIPS = config.PROCESSED_DIR / "hourly_trips.parquet"
HOURLY_WEATHER = config.PROCESSED_DIR / "weather_hourly.parquet"

# Weekday/weekend time blocks (local clock hour of the trip start). Holidays count as weekend.
BLOCKS = ["wd_am", "wd_mid", "wd_pm", "we_day", "night"]
BLOCK_LABEL = {"wd_am": "Weekday 7-10am", "wd_mid": "Weekday 10am-4pm", "wd_pm": "Weekday 4-8pm",
               "we_day": "Weekend 10am-8pm", "night": "Night / early (8pm-7am, all days)"}


def ensure_dirs():
    for d in (FIG_DIR, TAB_DIR):
        d.mkdir(parents=True, exist_ok=True)


def save_fig(fig, name):
    import matplotlib.pyplot as plt

    FIG_DIR.mkdir(parents=True, exist_ok=True)
    fig.savefig(FIG_DIR / name, dpi=200, bbox_inches="tight")
    plt.close(fig)


def load_weather_hourly():
    """Hourly weather with rain exposure terms.

    exp   = measurable precipitation (>= 0.25 mm) in this hour's report or the previous one, i.e. it
            was raining at some point in roughly the 2 hours before the end of the start hour.
    exp_rain / exp_snow split exp by whether either report carried a snow code.
    Leads and lags of wet_meas are kept for the event-time profile.
    """
    w = pd.read_parquet(HOURLY_WEATHER).sort_values("hour_ts").reset_index(drop=True)
    for k in range(1, 5):
        w[f"wet_l{k}"] = w.wet_meas.shift(k).fillna(0).astype(np.int8)
    for k in (1, 2):
        w[f"wet_f{k}"] = w.wet_meas.shift(-k).fillna(0).astype(np.int8)
    w["exp"] = ((w.wet_meas + w.wet_l1) > 0).astype(np.int8)
    snow2 = ((w.snow_hour + w.snow_hour.shift(1).fillna(0)) > 0).astype(np.int8)
    w["exp_snow"] = (w.exp * snow2).astype(np.int8)
    w["exp_rain"] = (w.exp * (1 - snow2)).astype(np.int8)
    # Looser definition: any precipitation including trace, same two-report window, no snow code.
    w["exp_any"] = (((w.wet + w.wet.shift(1).fillna(0)) > 0) & (snow2 == 0)).astype(np.int8)
    day = w.groupby("date").agg(wetday=("wet_meas", "max"), lcd_snowday=("snow_hour", "max"),
                                lcd_rain_hours=("rain_hour", "sum"),
                                lcd_meas_rain_hours=("wet_meas", "sum"))
    w = w.join(day, on="date")
    w["dry_on_wetday"] = ((w.wetday == 1) & (w.exp == 0)).astype(np.int8)
    return w


def load_calendar():
    cal = cp.load_calendar()[["date", "date_id", "year", "year_month", "quarter", "weekday",
                              "holiday", "tbin", "tmax_c", "awnd_ms", "rain_any", "snow"]].copy()
    cal["date"] = pd.to_datetime(cal.date)
    return cal


def hourly_grid(keys, sample="main", weather=None):
    """Trip starts per date x hour x keys with zeros filled, joined to hourly weather and calendar."""
    h = pd.read_parquet(HOURLY_TRIPS)
    if sample == "main":
        h = h[h.main]
    g = h.groupby(["date", "hour", *keys], observed=True).trips.sum().reset_index()
    w = load_weather_hourly() if weather is None else weather
    levels = [sorted(h[k].unique()) for k in keys]
    idx = pd.MultiIndex.from_product([sorted(w.date.unique()), range(24), *levels],
                                     names=["date", "hour", *keys])
    g = g.set_index(["date", "hour", *keys]).reindex(idx, fill_value=0).reset_index()
    g = g.merge(w, on=["date", "hour"], how="left").merge(load_calendar(), on="date", how="left")
    g["weekend"] = ((g.weekday >= 5) | (g.holiday == 1)).astype(np.int8)
    g["daytype"] = np.where(g.holiday == 1, 7, g.weekday).astype(np.int8)
    g["block"] = np.select(
        [(g.weekend == 0) & g.hour.between(7, 9), (g.weekend == 0) & g.hour.between(10, 15),
         (g.weekend == 0) & g.hour.between(16, 19), (g.weekend == 1) & g.hour.between(10, 19)],
        ["wd_am", "wd_mid", "wd_pm", "we_day"], "night")
    return g
