"""Availability proxy check: does the e-bike vs classic rain gap hold where both bike types were in supply?

rideable_type is the bike taken, not the bike wanted. Station status (bikes available by type) is not
in the trip data. Cheap proxy: keep station-days on which both bike types had at least N trip starts,
i.e. neither type was missing from that dock for the whole day.

Selection on the day's own counts conditions on the outcome (rain lowers counts, so rain-day
observations that survive are higher-demand ones). A second version selects station-months instead,
using dry days only: station-months where both types had >= N starts on at least 90% of dry days. All
days of those station-months, rain or dry, are kept.

Models (main panel, station x date x bike type):
  F1(b) spec: trips ~ ebike x (rain + temp_bins + snow) | station^bike + date
  within station-day: same terms | station^date + station^bike  (identified from the e-bike share
  at the same dock on the same day)
"""

import sys

import numpy as np
import pandas as pd
import pyfixest as pf

import cp1_common as cp

N_CHOICES = [1, 5, 10]
N_MAIN = 5
DRY_DAY_COVERAGE = 0.9


def fepois(fml, data):
    return pf.fepois(fml, data=data, vcov={"CRV1": "date_id"}, ssc=cp.SSC, copy_data=False)


def main():
    cp.ensure_dirs()
    bins = cp.bin_order()
    d = cp.load_station_panel("main", ("ebike",))
    T = cp.add_bin_dummies(d, bins)
    E = cp.interact(d, "ebike", ["rain"] + T + ["snow"], "e_")
    rhs = " + ".join(E)
    # Integer ids for the interacted fixed effects (cheaper than letting pyfixest build strings).
    d["sd_id"] = d.station.astype(np.int64) * 1000 + d.date_id
    d["se_id"] = d.station.astype(np.int64) * 2 + d.ebike

    wide = d.pivot_table(index=["station", "date_id"], columns="ebike", values="trips").rename(
        columns={0: "classic", 1: "ebike"})
    wide = wide.join(cp.load_calendar().set_index("date_id")[["rain", "year_month"]], on="date_id")
    q = wide.classic.quantile([0.1, 0.25, 0.5, 0.75, 0.9]).to_dict()
    qe = wide.ebike.quantile([0.1, 0.25, 0.5, 0.75, 0.9]).to_dict()
    dist = pd.DataFrame({"classic": q, "ebike": qe})
    dist.index.name = "quantile"

    rows, sample_rows = [], []

    def run(label, data, fe):
        fit = fepois(f"trips ~ {rhs} | {fe}", data)
        r = cp.coef_table(fit, ["e_rain", "e_T_lt00", "e_T_00_02", "e_T_30_32"], label=label)
        r["fe"] = fe
        r["N"] = int(fit._N)
        rows.append(r)
        print(label, fe, int(fit._N), flush=True)

    fe_b, fe_sd = "se_id + date_id", "sd_id + se_id"
    run("all_station_days", d, fe_b)
    run("all_station_days", d, fe_sd)

    for n in N_CHOICES:
        keep = wide[(wide.classic >= n) & (wide.ebike >= n)].index
        sel = d.merge(keep.to_frame(index=False), on=["station", "date_id"])
        w_keep = wide.loc[keep]
        sample_rows.append({
            "selection": f"station_day_both_ge_{n}", "station_days": len(keep),
            "share_station_days": len(keep) / len(wide),
            "share_trips": sel.trips.sum() / d.trips.sum(),
            "share_dry_days_kept": (w_keep.rain == 0).sum() / (wide.rain == 0).sum(),
            "share_rain_days_kept": (w_keep.rain == 1).sum() / (wide.rain == 1).sum(),
        })
        run(f"station_day_both_ge_{n}", sel, fe_b)
        if n == N_MAIN:
            run(f"station_day_both_ge_{n}", sel, fe_sd)
        del sel

    # Station-months selected on dry days only.
    dry = wide[wide.rain == 0].copy()
    dry["both"] = (dry.classic >= N_MAIN) & (dry.ebike >= N_MAIN)
    cover = dry.groupby(["station", "year_month"]).both.mean()
    good = cover[cover >= DRY_DAY_COVERAGE].index
    wide_sm = wide.reset_index().set_index(["station", "year_month"])
    keep_sm = wide_sm.loc[wide_sm.index.isin(good)]
    sel = d.merge(keep_sm.reset_index()[["station", "date_id"]], on=["station", "date_id"])
    sample_rows.append({
        "selection": f"station_month_dry_days_both_ge_{N_MAIN}_on_{int(DRY_DAY_COVERAGE * 100)}pct",
        "station_days": len(keep_sm), "share_station_days": len(keep_sm) / len(wide),
        "share_trips": sel.trips.sum() / d.trips.sum(),
        "share_dry_days_kept": (keep_sm.rain == 0).sum() / (wide.rain == 0).sum(),
        "share_rain_days_kept": (keep_sm.rain == 1).sum() / (wide.rain == 1).sum(),
        "station_months": len(good), "share_station_months": len(good) / len(cover),
    })
    run(sample_rows[-1]["selection"], sel, fe_b)
    run(sample_rows[-1]["selection"], sel, fe_sd)

    res = pd.concat(rows, ignore_index=True)
    samples = pd.DataFrame(sample_rows)
    cp.add_bin_labels(res).to_csv(cp.TAB_DIR / "avail_proxy_rain_gap.csv", index=False)
    samples.to_csv(cp.TAB_DIR / "avail_proxy_samples.csv", index=False)
    dist.to_csv(cp.TAB_DIR / "avail_trips_per_station_day_quantiles.csv")
    pd.set_option("display.width", 220)
    print(dist)
    print(samples.round(3).to_string(index=False))
    print(res[["model", "fe", "term", "pct", "pct_lo", "pct_hi", "N"]].round(2).to_string(index=False))


if __name__ == "__main__":
    sys.exit(main())
