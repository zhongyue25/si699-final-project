"""Finding 1: replicate Zheng et al. (2025) on 2024-2025 Citi Bike data.

(a) Separate Poisson model per bike type, station x date panel (main sample):
      trips ~ temp_bins + rain + snow + wind | station + year_month + weekday
    plus log(trips + 1) OLS and a variant with a holiday dummy.
(b) Stacked bike types (preferred):
      trips ~ ebike x temp_bins + ebike x rain + ebike x snow | station^bike + date
    plus robustness variants.
SEs clustered by date. % effects are exp(beta) - 1.
"""

import sys

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pyfixest as pf

import cp1_common as cp
import plot_style as style

# Zheng et al. (2025) abstract: e-bike usage losses are 5.6 / 7.7 points smaller at 30-32 / -2-0 degC.
PAPER = {"30_32": 5.6, "m02_00": 7.7}


def fepois(fml, data, cluster="date_id"):
    return pf.fepois(fml, data=data, vcov={"CRV1": cluster}, ssc=cp.SSC, copy_data=False)


def feols(fml, data, cluster="date_id"):
    return pf.feols(fml, data=data, vcov={"CRV1": cluster}, ssc=cp.SSC, copy_data=False)


def model_a(d, T):
    rows = []
    rhs = " + ".join(T + ["rain", "snow", "awnd_ms"])
    specs = {
        "poisson": ("trips", rhs, fepois),
        "poisson_holiday": ("trips", rhs + " + holiday", fepois),
        "ols_log1p": ("log_trips1", rhs, feols),
    }
    nobs = {}
    for ebike in (0, 1):
        x = d[d.ebike == ebike]
        for spec, (y, r, fn) in specs.items():
            fit = fn(f"{y} ~ {r} | station + year_month + weekday", x)
            t = cp.coef_table(fit, label=spec)
            t.insert(1, "bike", cp.BIKE_LABEL[ebike])
            rows.append(t)
            nobs[f"{spec}_{cp.BIKE_LABEL[ebike]}"] = int(fit._N)
            print(f"(a) {spec} {cp.BIKE_LABEL[ebike]}: N={fit._N:,}", flush=True)
    return pd.concat(rows, ignore_index=True), nobs


def model_b(d, T):
    E = cp.interact(d, "ebike", T + ["rain", "snow"], "e_")
    base = " + ".join(E)
    fe = "station^ebike + date_id"
    out, nobs = [], {}

    def run(label, fit):
        out.append(cp.coef_table(fit, label=label))
        nobs[label] = int(fit._N)
        print(f"(b) {label}: N={fit._N:,}", flush=True)

    run("main", fepois(f"trips ~ {base} | {fe}", d))
    run("cluster_week", fepois(f"trips ~ {base} | {fe}", d, cluster="week_id"))
    d["e_awnd_ms"] = d.ebike * d.awnd_ms
    run("plus_ebike_x_wind", fepois(f"trips ~ {base} + e_awnd_ms | {fe}", d))
    d["e_holiday"] = (d.ebike * d.holiday).astype(np.int8)
    run("bike_specific_calendar",
        fepois(f"trips ~ {base} + e_holiday | {fe} + ebike^year_month + ebike^weekday", d))
    run("ols_log1p", feols(f"log_trips1 ~ {base} | {fe}", d))

    g = cp.load_daily_groups("main", ("ebike",))
    cp.add_bin_dummies(g, cp.bin_order())
    cp.interact(g, "ebike", T + ["rain", "snow"], "e_")
    run("aggregated_daily_check", fepois(f"trips ~ {base} | ebike + date_id", g))

    full = cp.load_station_panel("full", ("ebike",))
    cp.add_bin_dummies(full, cp.bin_order())
    cp.interact(full, "ebike", T + ["rain", "snow"], "e_")
    run("full_sample", fepois(f"trips ~ {base} | {fe}", full))
    return pd.concat(out, ignore_index=True), nobs


def figure(a, b, bins_tab):
    style.apply()
    bins = bins_tab.tbin.tolist()
    x = np.arange(len(bins))
    pos = dict(zip(bins, x))
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(8.2, 7.2), sharex=True,
                                   gridspec_kw={"height_ratios": [1.6, 1], "hspace": 0.12})
    a = a[(a.model == "poisson") & a.term.str.startswith("T_")].copy()
    a["tbin"] = a.term.str[2:]
    for bike, color, dx in (("Classic", cp.CLASSIC, -0.12), ("E-bike", cp.EBIKE, 0.12)):
        s = a[a.bike == bike].set_index("tbin").reindex(bins)
        s.loc[cp.REF_BIN, ["pct", "pct_lo", "pct_hi"]] = 0.0
        xs = x + dx
        ax1.plot(xs, s.pct, color=color, lw=1.4, alpha=0.8, zorder=2)
        ax1.errorbar(xs, s.pct, yerr=[s.pct - s.pct_lo, s.pct_hi - s.pct], fmt="o", ms=5,
                     color=color, ecolor=color, elinewidth=1.2, capsize=0, zorder=3,
                     mec=style.SURFACE, mew=1.2)
        ax1.annotate(bike, (xs[-1], s.pct.iloc[-1]), xytext=(8, 0), textcoords="offset points",
                     va="center", fontsize=9, color=style.TEXT)
    ax1.axhline(0, color=style.TEXT_MUTED, lw=0.8)
    ax1.axvspan(pos[cp.REF_BIN] - 0.4, pos[cp.REF_BIN] + 0.4, color=style.GRID, alpha=0.6, zorder=0)
    ax1.annotate("reference\n20–22 °C\n(68–71.6 °F)", (pos[cp.REF_BIN], ax1.get_ylim()[0]), xytext=(0, 6),
                 textcoords="offset points", ha="center", va="bottom", fontsize=8,
                 color=style.TEXT_MUTED)
    ax1.set_ylabel("Trips vs reference bin (%)")
    ax1.set_title("A. Daily trip starts by temperature bin, separate Poisson model per bike type")

    c = b[(b.model == "main") & b.term.str.startswith("e_T_")].copy()
    c["tbin"] = c.term.str[4:]
    c = c.set_index("tbin").reindex(bins)
    c.loc[cp.REF_BIN, ["pct", "pct_lo", "pct_hi"]] = 0.0
    ax2.errorbar(x, c.pct, yerr=[c.pct - c.pct_lo, c.pct_hi - c.pct], fmt="o", ms=5,
                 color=style.TEXT, elinewidth=1.2, capsize=0, mec=style.SURFACE, mew=1.2,
                 label="This study, 2024-25 (e-bike x bin, date FE)")
    ax2.plot([pos["30_32"] + 0.28], [PAPER["30_32"]], marker="D", ms=6, ls="none",
             color=style.CASUAL, mec=style.SURFACE, mew=1.0, label="Zheng et al. (2025), 2023 data")
    ax2.text(0.99, 0.80, "Paper's cold estimate (7.7 at -2 to 0 °C / 28.4 to 32 °F) not plotted:\n"
             "that bin has 12 days here, so it is merged into < 0 °C.",
             transform=ax2.transAxes, ha="right", va="top", fontsize=7.5, color=style.TEXT_MUTED)
    ax2.axhline(0, color=style.TEXT_MUTED, lw=0.8)
    ax2.axvspan(pos[cp.REF_BIN] - 0.4, pos[cp.REF_BIN] + 0.4, color=style.GRID, alpha=0.6, zorder=0)
    ax2.set_ylabel("E-bike minus classic\n(% difference in effect)")
    ax2.set_title("B. E-bike advantage relative to classic, stacked model")
    ax2.legend(loc="upper right", fontsize=8, ncol=2)
    lo, hi = ax2.get_ylim()
    ax2.set_ylim(lo - 4, hi + 5)
    ax2.set_xticks(x, [f"{cp.bin_display(b_).replace(' to ', '–')}  ({cp.bin_display_f(b_).replace(' to ', '–')})"
                       for b_ in bins], rotation=90, fontsize=7.5)
    ax2.set_xlabel("Daily maximum temperature, Central Park: °C (°F)")
    n = bins_tab.set_index("tbin").days
    for xi, b_ in zip(x, bins):
        ax2.annotate(f"{n[b_]}", (xi, 0), xycoords=("data", "axes fraction"), xytext=(0, 2),
                     textcoords="offset points", ha="center", fontsize=6.5, color=style.TEXT_MUTED)
    ax2.annotate("days per bin", (x[-1] + 0.5, 0), xycoords=("data", "axes fraction"),
                 xytext=(2, 2), textcoords="offset points", fontsize=6.5, color=style.TEXT_MUTED)
    cp.save_fig(fig, "fig1_temperature_by_bike_type.png")


def main():
    cp.ensure_dirs()
    bins_tab = pd.read_csv(cp.TAB_DIR / "temperature_bins.csv")
    bins = bins_tab.tbin.tolist()
    if "--figure-only" in sys.argv:
        figure(pd.read_csv(cp.TAB_DIR / "f1a_per_bike_type.csv"),
               pd.read_csv(cp.TAB_DIR / "f1b_stacked_contrasts_all_specs.csv"), bins_tab)
        return

    d = cp.load_station_panel("main", ("ebike",))
    T = cp.add_bin_dummies(d, bins)
    d["log_trips1"] = np.log1p(d.trips)
    a, nobs_a = model_a(d, T)

    b, nobs_b = model_b(d, T)

    cp.add_bin_labels(a).to_csv(cp.TAB_DIR / "f1a_per_bike_type.csv", index=False)
    cp.add_bin_labels(b).to_csv(cp.TAB_DIR / "f1b_stacked_contrasts_all_specs.csv", index=False)

    # Compact table: per-bin % by bike type (a) and e-bike x bin contrast (b).
    pa = a[a.model == "poisson"].pivot(index="term", columns="bike", values=["pct", "pct_lo", "pct_hi"])
    main_b = b[b.model == "main"].set_index("term")
    rows = []
    for t in [f"T_{x}" for x in bins if x != cp.REF_BIN] + ["rain", "snow", "awnd_ms"]:
        e = f"e_{t}"
        rows.append({
            "term": t, "label": cp.bin_display_cf(t[2:]) if t.startswith("T_") else t,
            "days": int(bins_tab.set_index("tbin").days.get(t[2:], np.nan))
            if t.startswith("T_") else None,
            "classic_pct": pa.loc[t, ("pct", "Classic")],
            "classic_ci": f"[{pa.loc[t, ('pct_lo', 'Classic')]:+.1f}, {pa.loc[t, ('pct_hi', 'Classic')]:+.1f}]",
            "ebike_pct": pa.loc[t, ("pct", "E-bike")],
            "ebike_ci": f"[{pa.loc[t, ('pct_lo', 'E-bike')]:+.1f}, {pa.loc[t, ('pct_hi', 'E-bike')]:+.1f}]",
            "gap_pp_separate_models": pa.loc[t, ("pct", "E-bike")] - pa.loc[t, ("pct", "Classic")],
            "contrast_beta_x100": main_b.beta.get(e, np.nan) * 100,
            "contrast_pct": main_b.pct.get(e, np.nan),
            "contrast_ci": (f"[{main_b.pct_lo[e]:+.1f}, {main_b.pct_hi[e]:+.1f}]"
                            if e in main_b.index else ""),
            "contrast_p": main_b.p.get(e, np.nan),
        })
    table = pd.DataFrame(rows)
    table.to_csv(cp.TAB_DIR / "f1_table_bins_and_contrasts.csv", index=False)

    # Robustness summary for the key contrasts.
    key = ["e_T_lt00", "e_T_00_02", "e_T_30_32", "e_T_ge32", "e_rain", "e_snow"]
    rob = b[b.term.isin(key)].assign(cell=lambda t: t.apply(cp.fmt_pct, axis=1))
    rob = rob.pivot(index="model", columns="term", values="cell")[key]
    rob.columns = [cp.bin_display_cf(c[4:]) if c.startswith("e_T_") else c for c in rob.columns]
    rob.to_csv(cp.TAB_DIR / "f1b_robustness_key_contrasts.csv")

    # Snow days behind the snow coefficients.
    cal = cp.load_calendar()
    snow = cal[cal.snow == 1][["date", "weekday", "holiday", "snow_mm", "prcp_in", "tmax_c", "tbin"]]
    snow = snow.assign(snow_in=(snow.snow_mm / 25.4).round(2), tmax_f=(snow.tmax_c * 9 / 5 + 32).round(1),
                       temp_bin=snow.tbin.map(cp.bin_display_cf))
    snow.to_csv(cp.TAB_DIR / "f1_snow_days.csv", index=False)
    snow_summary = {
        "snow_days": int(len(snow)),
        "snow_days_ge_1in": int((snow.snow_in >= 1).sum()),
        "snow_days_by_year": snow.date.dt.year.value_counts().sort_index().to_dict(),
        "snow_days_weekend": int((snow.weekday >= 5).sum()),
        "snow_days_by_temp_bin": snow.temp_bin.value_counts().to_dict(),
        "snow_days_also_rain_day": int((snow.prcp_in > 0).sum()),
    }
    figure(a, b, bins_tab)
    cp.save_metrics("finding1.json", {"snow": snow_summary, "nobs_a": nobs_a, "nobs_b": nobs_b,
                                      "paper": PAPER})
    print(snow.to_string(index=False))
    print(snow_summary)
    pd.set_option("display.width", 220)
    print(table.round(2).to_string(index=False))
    print(rob.to_string())


if __name__ == "__main__":
    sys.exit(main())
