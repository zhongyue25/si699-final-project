"""Finding 3 stress test: is the 2024 Q1 rain outlier about rain intensity?

The quarterly rain effects (cp1_finding3.py, model a) put 2024 Q1 at -24% against -12% to -17%
elsewhere. That quarter had 10 heavy-rain days (>= 0.5 in), including 3.66 in on 2024-03-23.
Re-estimate the quarterly rain effects
  (1) as in Finding 3,
  (2) without 2024-03-23,
  (3) with a heavy-rain term common to all quarters (rain:quarter is then the light-rain effect),
  (4) both,
  (5) without snow days (every snow day is also a rain day, and 11 of 2025 Q1's 25 rain days
      are snow days),
and compare each quarter with the same quarter a year earlier.
"""

import sys

import pandas as pd

import cp1_common as cp
from cp1_finding3 import fepois

BIG_RAIN_DAY = "2024-03-23"


def quarterly(daily, extra=""):
    d = daily.copy()
    periods = sorted(d.quarter.unique())
    terms = []
    for p in periods:
        for v in ("rain", "tmax_c"):
            name = f"{v}_{p}"
            d[name] = d[v] * (d.quarter == p)
            terms.append(name)
    snow = " + snow" if d.snow.any() else ""
    fit = fepois(f"trips ~ {' + '.join(terms)}{extra}{snow} + awnd_ms + holiday"
                 " | year_month + weekday", d)
    rain_terms = [f"rain_{p}" for p in periods]
    t = cp.coef_table(fit, rain_terms)
    t["quarter"] = t.term.str.split("_", n=1).str[1]
    tests = [cp.lincom(fit, {f"rain_{p}": 1, f"rain_{p.replace('2025', '2024')}": -1},
                       f"{p[-2:]}: 2025 - 2024")
             for p in periods if p.startswith("2025")]
    extra_t = cp.coef_table(fit, ["rain_05"]) if "rain_05" in extra else None
    return t, pd.DataFrame(tests), extra_t


def main():
    cp.ensure_dirs()
    daily = cp.load_daily_groups("main", ())
    big = daily.date.astype(str).str[:10] == BIG_RAIN_DAY
    if big.sum() != 1:
        raise ValueError(f"expected one row for {BIG_RAIN_DAY}, got {big.sum()}")

    specs = [("main", daily, ""),
             ("drop_2024_03_23", daily[~big], ""),
             ("common_heavy_rain", daily, " + rain_05"),
             ("drop_day_and_heavy_rain", daily[~big], " + rain_05"),
             ("drop_snow_days", daily[daily.snow == 0], "")]
    effects, tests, heavy = [], [], []
    for label, d, extra in specs:
        t, s, h = quarterly(d, extra)
        effects.append(t.assign(spec=label))
        tests.append(s.assign(spec=label))
        if h is not None:
            heavy.append(h.assign(spec=label))
    effects = pd.concat(effects, ignore_index=True)
    tests = pd.concat(tests, ignore_index=True)
    heavy = pd.concat(heavy, ignore_index=True)

    effects.to_csv(cp.TAB_DIR / "f3c_rain_intensity_by_quarter.csv", index=False)
    tests.to_csv(cp.TAB_DIR / "f3c_rain_intensity_same_season.csv", index=False)
    heavy.to_csv(cp.TAB_DIR / "f3c_heavy_rain_term.csv", index=False)

    pd.set_option("display.width", 220)
    print(effects.pivot(index="quarter", columns="spec", values="pct")
          [[s[0] for s in specs]].round(1).to_string())
    print(tests[["spec", "term", "pct", "pct_lo", "pct_hi", "p"]].round(3).to_string(index=False))
    print(heavy[["spec", "term", "pct", "pct_lo", "pct_hi", "p"]].round(3).to_string(index=False))


if __name__ == "__main__":
    sys.exit(main())
