"""Checkpoint 2 extension: trip distance as a mechanism test for the e-bike weather advantages.

Distance = straight-line km between start and end station (see build_distance_table.py); round trips
and trips without an end station are excluded. Bands: < 1, 1-2, 2-3, 3-5, >= 5 km.

(a) Does weather change which trips are taken? Daily geometric-mean distance and mean speed
    (km / duration) of A-to-B trips per rider x bike group, OLS on rain, snow, wind, temperature bins
    | year-month + weekday, heteroskedasticity-robust SEs.
(b) Rain level by distance band (classic and e-bike, per rider type), Finding 1(a) specification.
(c) E-bike advantage by distance band: the Finding 1(b)/2 stacked model, with every e-bike x weather
    term specific to the band and date fixed effects per band, so e-bike and classic trips of the same
    length are compared on the same days:
        trips ~ sum_b ebike x band_b x (rain + snow + temp bins) | band^ebike + band^date
    The gradient is the >= 5 km minus < 1 km difference. Stress tests: clustered by week; band x
    bike-specific year-month and weekday fixed effects (Checkpoint 1 showed month-to-month fleet
    swings matter for the hot-day contrast).
"""

import sys
import warnings

import numpy as np
import pandas as pd
import pyfixest as pf

import config
import cp1_common as cp
import cp2_common as c2

warnings.filterwarnings("ignore")
BANDS = ["lt1", "1_2", "2_3", "3_5", "ge5"]
BAND_LABEL = {"lt1": "< 1 km", "1_2": "1-2 km", "2_3": "2-3 km", "3_5": "3-5 km", "ge5": ">= 5 km"}
WEATHER = ["rain", "T_lt00", "T_00_02", "T_30_32", "T_ge32"]


def load():
    d = pd.read_parquet(config.PROCESSED_DIR / "distance_hourly.parquet")
    cal = cp.load_calendar()[cp.CAL_COLS].copy()
    cal["date"] = pd.to_datetime(cal.date)
    return d, cal


def composition(d, cal, bins):
    ab = d[d.band != "round"].groupby(["date", "ebike", "casual"]).agg(
        trips=("trips", "sum"), km=("km", "sum"), dur=("dur_s", "sum"), logkm=("logkm", "sum")
    ).reset_index().merge(cal, on="date")
    ab["log_gm_km"] = ab.logkm / ab.trips
    ab["log_speed"] = np.log(ab.km / (ab.dur / 3600))
    T = cp.add_bin_dummies(ab, bins)
    rows = []
    for (e, c), g in ab.groupby(["ebike", "casual"]):
        for y in ("log_gm_km", "log_speed"):
            f = pf.feols(f"{y} ~ rain + snow + awnd_ms + {' + '.join(T)} | year_month + weekday", g,
                         vcov="hetero")
            r = cp.coef_table(f, ["rain"]).iloc[0].to_dict()
            rows.append({"ebike": e, "casual": c, "outcome": y, **r,
                         "mean_km": g.km.sum() / g.trips.sum()})
    return pd.DataFrame(rows)


def levels(day, bins):
    rows = []
    for (c, b, e), g in day.groupby(["casual", "band", "ebike"]):
        g = g.copy()
        T = cp.add_bin_dummies(g, bins)
        f = pf.fepois(f"trips ~ rain + snow + awnd_ms + {' + '.join(T)} | year_month + weekday", g,
                      vcov={"CRV1": "date_id"}, ssc=cp.SSC)
        rows.append({"casual": c, "band": b, "ebike": e, **cp.coef_table(f, ["rain"]).iloc[0].to_dict(),
                     "trips": int(g.trips.sum())})
    return pd.DataFrame(rows)


def advantage(day, bins, spec="main"):
    out = []
    for c in (0, 1):
        d = day[day.casual == c].copy()
        T = cp.add_bin_dummies(d, bins)
        terms, new = [], {}
        for b in BANDS:
            ib = (d.band == b).to_numpy()
            for v in ["rain", "snow"] + T:
                n = f"e_{v}__{b}"
                new[n] = np.where(ib, d.ebike.to_numpy() * d[v].to_numpy(), 0)
                terms.append(n)
        d = pd.concat([d, pd.DataFrame(new, index=d.index)], axis=1)
        d["cell"] = d.band + "_" + d.ebike.astype(str)
        fe = "cell + band^date_id"
        cluster = "date_id"
        if spec == "cluster_week":
            cluster = "week_id"
        if spec == "bike_specific_calendar":
            fe += " + cell^year_month + cell^weekday"
        f = pf.fepois(f"trips ~ {' + '.join(terms)} | {fe}", d, vcov={"CRV1": cluster}, ssc=cp.SSC,
                      copy_data=False)
        for v in WEATHER:
            t = cp.coef_table(f, [f"e_{v}__{b}" for b in BANDS])
            t["band"] = BANDS
            g = cp.lincom(f, {f"e_{v}__ge5": 1, f"e_{v}__lt1": -1}, "ge5_minus_lt1")
            g["band"] = "gradient"
            t = pd.concat([t, pd.DataFrame([g])], ignore_index=True)
            t["weather"], t["casual"], t["spec"] = v, c, spec
            out.append(t)
        print("advantage", spec, c, flush=True)
    return pd.concat(out, ignore_index=True)


def main():
    c2.ensure_dirs()
    bins = cp.bin_order()
    d, cal = load()
    pd.set_option("display.width", 220)

    comp = composition(d, cal, bins)
    comp.to_csv(c2.TAB_DIR / "dist_a_composition.csv", index=False)
    print(comp[["ebike", "casual", "outcome", "pct", "pct_lo", "pct_hi", "mean_km"]].round(2)
          .to_string(index=False))

    day = d[d.band.isin(BANDS)].groupby(["date", "ebike", "casual", "band"]).trips.sum() \
        .reset_index().merge(cal, on="date")
    lev = levels(day, bins)
    lev.to_csv(c2.TAB_DIR / "dist_b_rain_levels.csv", index=False)
    print(lev.pivot_table(index=["casual", "band"], columns="ebike", values="pct").reindex(
        BANDS, level=1).round(1))

    adv = pd.concat([advantage(day, bins, s)
                     for s in ("main", "cluster_week", "bike_specific_calendar")], ignore_index=True)
    adv.to_csv(c2.TAB_DIR / "dist_c_ebike_advantage_by_band.csv", index=False)
    adv["cell"] = adv.apply(lambda r: f"{r.pct:+.1f} [{r.pct_lo:+.1f}, {r.pct_hi:+.1f}]", axis=1)
    for s in adv.spec.unique():
        print("==", s)
        print(adv[adv.spec == s].pivot_table(index=["casual", "weather"], columns="band", values="cell",
                                             aggfunc="first")[BANDS + ["gradient"]].to_string())


if __name__ == "__main__":
    sys.exit(main())
