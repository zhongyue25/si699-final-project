"""Shared helpers for the Checkpoint 1 analyses (weather x bike type x rider type)."""

import json

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pyfixest as pf

import config

PANEL_PARQUET = config.PROCESSED_DIR / "panel_station_day.parquet"
CALENDAR_PARQUET = config.PROCESSED_DIR / "calendar_weather.parquet"
FIG_DIR = config.FIGURES_DIR / "checkpoint1"
TAB_DIR = config.TABLES_DIR / "checkpoint1"
METRICS_DIR = TAB_DIR / "metrics"

# Temperature bins: 2 degC bins on daily TMAX, sparse tails merged until every bin has >= MIN_BIN_DAYS.
BIN_WIDTH_C = 2
MIN_BIN_DAYS = 15
REF_BIN = "20_22"
RAIN_THRESHOLDS_IN = {"rain_any": 0.0, "rain_01": 0.1, "rain_05": 0.5}  # > 0, >= 0.1, >= 0.5 in

# Only the ratio G/(G-1) is applied, so station-level and aggregated fits give identical SEs.
SSC = pf.ssc(k_adj=False, G_adj=True)
Z = 1.959964

BIKE_LABEL = {1: "E-bike", 0: "Classic"}
RIDER_LABEL = {1: "Casual", 0: "Member"}
EBIKE = "#1baf7a"
CLASSIC = "#4a3aa7"


def ensure_dirs():
    for d in (FIG_DIR, TAB_DIR, METRICS_DIR):
        d.mkdir(parents=True, exist_ok=True)


def bin_label(lo, hi):
    if lo is None:
        return f"lt{hi:02d}" if hi >= 0 else f"lt_m{-hi:02d}"
    if hi is None:
        return f"ge{lo:02d}"
    fmt = lambda v: f"{v:02d}" if v >= 0 else f"m{-v:02d}"
    return f"{fmt(lo)}_{fmt(hi)}"


def bin_display(label):
    """'20_22' -> '20 to 22', 'lt00' -> '< 0', 'ge32' -> '>= 32' (degC)."""
    if label.startswith("lt"):
        v = label[2:].replace("_m", "-").replace("m", "-")
        return f"< {int(v)}"
    if label.startswith("ge"):
        return f">= {int(label[2:])}"
    lo, hi = (int(p.replace("m", "-")) for p in label.split("_"))
    return f"{lo} to {hi}"


def c_to_f(v):
    f = v * 9 / 5 + 32
    return f"{f:.1f}".rstrip("0").rstrip(".")


def bin_display_f(label):
    """Same bin in degF: '20_22' -> '68 to 71.6', 'lt00' -> '< 32', 'ge32' -> '>= 89.6'."""
    c = bin_display(label)
    if c.startswith("<") or c.startswith(">="):
        op, v = c.rsplit(" ", 1)
        return f"{op} {c_to_f(int(v))}"
    lo, hi = c.split(" to ")
    return f"{c_to_f(int(lo))} to {c_to_f(int(hi))}"


def bin_display_cf(label):
    """'20 to 22 °C (68 to 71.6 °F)'."""
    return f"{bin_display(label)} °C ({bin_display_f(label)} °F)"


def make_temperature_bins(tmax_c):
    """Return (bin label per day, bin table). 2 degC bins, tails merged inward until >= 15 days."""
    edges = list(range(int(np.floor(tmax_c.min() / BIN_WIDTH_C) * BIN_WIDTH_C),
                       int(np.floor(tmax_c.max() / BIN_WIDTH_C) * BIN_WIDTH_C) + BIN_WIDTH_C + 1,
                       BIN_WIDTH_C))
    counts = pd.cut(tmax_c, edges, right=False).value_counts(sort=False).to_numpy()
    lo_cut, hi_cut = 1, len(counts) - 1  # inner edges kept: edges[lo_cut] .. edges[hi_cut]
    while counts[:lo_cut].sum() < MIN_BIN_DAYS:
        lo_cut += 1
    while counts[hi_cut:].sum() < MIN_BIN_DAYS:
        hi_cut -= 1
    inner = edges[lo_cut:hi_cut + 1]
    labels = [bin_label(None, inner[0])]
    labels += [bin_label(a, b) for a, b in zip(inner[:-1], inner[1:])]
    labels += [bin_label(inner[-1], None)]
    cut = pd.cut(tmax_c, [-np.inf] + inner + [np.inf], right=False, labels=labels)
    table = cut.value_counts(sort=False).rename_axis("tbin").reset_index(name="days")
    table["display_c"] = table.tbin.map(bin_display)
    table["display_f"] = table.tbin.map(bin_display_f)
    table["min_tmax_c"] = table.tbin.map(tmax_c.groupby(cut, observed=False).min())
    table["max_tmax_c"] = table.tbin.map(tmax_c.groupby(cut, observed=False).max())
    table["min_tmax_f"] = (table.min_tmax_c.astype(float) * 9 / 5 + 32).round(1)
    table["max_tmax_f"] = (table.max_tmax_c.astype(float) * 9 / 5 + 32).round(1)
    if (table.days < MIN_BIN_DAYS).any():
        raise ValueError(f"interior bin below {MIN_BIN_DAYS} days:\n{table}")
    return cut.astype(str), table


def load_calendar():
    return pd.read_parquet(CALENDAR_PARQUET)


def bin_order():
    """Temperature bin labels, coldest first (written by build_panel.py)."""
    return pd.read_csv(TAB_DIR / "temperature_bins.csv").tbin.tolist()


def add_bin_dummies(df, bins, prefix="T_"):
    """One 0/1 column per non-reference bin. Returns list of column names."""
    cols = []
    for b in bins:
        if b == REF_BIN:
            continue
        name = f"{prefix}{b}"
        df[name] = (df["tbin"] == b).astype(np.int8)
        cols.append(name)
    return cols


def interact(df, a, cols, prefix):
    out = []
    for c in cols:
        name = f"{prefix}{c}"
        df[name] = (df[a] * df[c]).astype(np.int8) if df[c].dtype == np.int8 else df[a] * df[c]
        out.append(name)
    return out


def pct(beta):
    return np.expm1(beta) * 100


def coef_table(fit, names=None, label=None):
    """Coefficients with % effects exp(b)-1 and normal 95% CIs from the model vcov."""
    b = pd.Series(fit.coef())
    se = pd.Series(np.sqrt(np.diag(fit._vcov)), index=fit._coefnames)
    names = names or list(b.index)
    out = pd.DataFrame({"term": names, "beta": b[names].to_numpy(), "se": se[names].to_numpy()})
    out["lo"] = out.beta - Z * out.se
    out["hi"] = out.beta + Z * out.se
    out["pct"] = pct(out.beta)
    out["pct_lo"] = pct(out.lo)
    out["pct_hi"] = pct(out.hi)
    out["p"] = 2 * (1 - _norm_cdf(np.abs(out.beta / out.se)))
    if label is not None:
        out.insert(0, "model", label)
    return out


def lincom(fit, weights, label):
    """Linear combination sum(w * beta) with SE from the model vcov."""
    names = fit._coefnames
    w = np.array([weights.get(n, 0.0) for n in names])
    b = float(w @ np.asarray(fit.coef()))
    se = float(np.sqrt(w @ fit._vcov @ w))
    return {"term": label, "beta": b, "se": se, "lo": b - Z * se, "hi": b + Z * se,
            "pct": pct(b), "pct_lo": pct(b - Z * se), "pct_hi": pct(b + Z * se),
            "p": float(2 * (1 - _norm_cdf(abs(b / se))))}


def _norm_cdf(x):
    from scipy.stats import norm
    return norm.cdf(x)


def fmt_pct(row, digits=1):
    return f"{row['pct']:+.{digits}f}% [{row['pct_lo']:+.{digits}f}, {row['pct_hi']:+.{digits}f}]"


def save_metrics(name, obj):
    METRICS_DIR.mkdir(parents=True, exist_ok=True)
    (METRICS_DIR / name).write_text(json.dumps(obj, indent=2, default=_json_default))


def _json_default(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, (pd.Timestamp,)):
        return str(o.date())
    raise TypeError(type(o))


def save_fig(fig, name):
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    fig.savefig(FIG_DIR / name, dpi=200, bbox_inches="tight")
    plt.close(fig)


CAL_COLS = ["date_id", "date", "year", "year_month", "quarter", "half", "weekday", "is_weekend",
            "week_id", "holiday", "tmax_c", "tbin", "prcp_in", "rain", "rain_any", "rain_01",
            "rain_05", "snow", "snow_mm", "awnd_ms"]


def load_station_panel(sample="main", keys=("ebike",)):
    """Station x date x keys trip counts (summing over the other cells), with calendar columns."""
    cols = ["station", "date_id", "ebike", "casual", "trips", "main"]
    p = pd.read_parquet(PANEL_PARQUET, columns=cols)
    if sample == "main":
        p = p[p.main]
    p = p.groupby(["station", "date_id", *keys], observed=True, sort=False).trips.sum().reset_index()
    return p.merge(load_calendar()[CAL_COLS], on="date_id", how="left")


def load_daily_groups(sample="main", keys=("ebike", "casual")):
    """Daily trip totals per group, summed over stations (keys=() gives the system total)."""
    p = pd.read_parquet(PANEL_PARQUET, columns=["date_id", "ebike", "casual", "trips", "main"])
    if sample == "main":
        p = p[p.main]
    g = p.groupby(["date_id", *keys], observed=True).trips.sum().reset_index()
    return g.merge(load_calendar()[CAL_COLS], on="date_id", how="left")


def add_bin_labels(df, col="term"):
    """Add a 'temp_bin' column ('20 to 22 °C (68 to 71.6 °F)') for coefficient rows on a bin dummy."""
    lab = df[col].astype(str).str.extract(r"T_((?:lt|ge)\d+|m?\d+_m?\d+)$")[0]
    df["temp_bin"] = lab.map(lambda b: bin_display_cf(b) if isinstance(b, str) else "")
    return df
