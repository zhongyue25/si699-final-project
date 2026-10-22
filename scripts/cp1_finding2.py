"""Finding 2: rain x bike type x rider type.

Stacked design on the main (balanced) panel:
    trips ~ ebike x casual x (rain + temp_bins) | station^bike^rider + date
With a balanced panel and regressors that vary only by group x date, Poisson with station FE gives the
same coefficients and date-clustered SEs as Poisson on daily group totals (station FE collapse into
group FE). The models below are fit on the daily totals; a station-level fit of the rain terms is run
once as a check.

Rain effects for each group (levels) cannot come from the date-FE model (rain is absorbed by the date
FE), so they are estimated per group with the Finding 1(a) specification.
"""

import sys

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pyfixest as pf

import cp1_common as cp
import plot_style as style

GROUPS = [(0, 0), (1, 0), (0, 1), (1, 1)]  # (ebike, casual)


def glabel(e, c):
    return f"{cp.RIDER_LABEL[c]}, {cp.BIKE_LABEL[e].lower()}"


def fepois(fml, data, cluster="date_id"):
    return pf.fepois(fml, data=data, vcov={"CRV1": cluster}, ssc=cp.SSC, copy_data=False)


def prep(d, bins, rain_var="rain_any"):
    d = d.copy()
    d["rain"] = d[rain_var]
    d["ec"] = (d.ebike * d.casual).astype(np.int8)
    d["group"] = d.ebike * 2 + d.casual
    T = cp.add_bin_dummies(d, bins)
    terms = []
    for g in ("ebike", "casual", "ec"):
        terms += cp.interact(d, g, ["rain"] + T, f"{g[0] if g != 'ec' else 'x'}_")
    for g in ("ebike", "casual", "ec"):
        for v in ("snow", "holiday"):
            d[f"{g}_{v}"] = d[g] * d[v]
    return d, terms


def contrasts(fit, label):
    rows = [
        cp.lincom(fit, {"e_rain": 1}, "ebike_vs_classic_member"),
        cp.lincom(fit, {"e_rain": 1, "x_rain": 1}, "ebike_vs_classic_casual"),
        cp.lincom(fit, {"x_rain": 1}, "ebike_advantage_casual_minus_member"),
        cp.lincom(fit, {"c_rain": 1}, "casual_vs_member_classic"),
        cp.lincom(fit, {"c_rain": 1, "x_rain": 1}, "casual_vs_member_ebike"),
    ]
    out = pd.DataFrame(rows)
    out.insert(0, "spec", label)
    out["N"] = int(fit._N)
    return out


def stacked(g, bins):
    out = []
    specs = {}
    for rv in cp.RAIN_THRESHOLDS_IN:
        specs[rv] = dict(rain_var=rv, sub=None)
    specs["weekday_only"] = dict(rain_var="rain_any", sub="weekday")
    specs["weekend_only"] = dict(rain_var="rain_any", sub="weekend")
    for name, sp in specs.items():
        d, terms = prep(g, bins, sp["rain_var"])
        if sp["sub"] == "weekday":
            d = d[d.is_weekend == 0]
        elif sp["sub"] == "weekend":
            d = d[d.is_weekend == 1]
        fit = fepois(f"trips ~ {' + '.join(terms)} | group + date_id", d)
        out.append(contrasts(fit, name))
        if name == "rain_any":
            main_fit, main_terms = fit, terms
            full_coefs = cp.coef_table(fit, label="main")
            # Extra stress tests on the main threshold.
            out.append(contrasts(fepois(f"trips ~ {' + '.join(terms)} | group + date_id", d,
                                        cluster="week_id"), "cluster_week"))
            snow = " + ".join(f"{x}_snow" for x in ("ebike", "casual", "ec"))
            out.append(contrasts(fepois(f"trips ~ {' + '.join(terms)} + {snow} | group + date_id", d),
                                 "plus_group_x_snow"))
            hol = " + ".join(f"{x}_holiday" for x in ("ebike", "casual", "ec"))
            out.append(contrasts(fepois(
                f"trips ~ {' + '.join(terms)} + {hol} | group + date_id + group^year_month"
                " + group^weekday", d), "group_specific_calendar"))
        print(f"stacked {name}: N={fit._N}", flush=True)
    full = cp.load_daily_groups("full", ("ebike", "casual"))
    d, terms = prep(full, bins)
    out.append(contrasts(fepois(f"trips ~ {' + '.join(terms)} | group + date_id", d), "full_sample"))
    return pd.concat(out, ignore_index=True), full_coefs, main_fit


def levels(g, bins):
    """Per-group rain effect, Finding 1(a) spec, for each threshold and weekday/weekend subsample."""
    rows = []
    for e, c in GROUPS:
        for name, rv, sub in [("rain_any", "rain_any", None), ("rain_01", "rain_01", None),
                              ("rain_05", "rain_05", None), ("weekday_only", "rain_any", 0),
                              ("weekend_only", "rain_any", 1)]:
            d = g[(g.ebike == e) & (g.casual == c)].copy()
            if sub is not None:
                d = d[d.is_weekend == sub]
            d["rain"] = d[rv]
            T = cp.add_bin_dummies(d, bins)
            fit = fepois(f"trips ~ {' + '.join(T)} + rain + snow + awnd_ms | year_month + weekday", d)
            r = cp.coef_table(fit, ["rain"]).iloc[0].to_dict()
            rows.append({"group": glabel(e, c), "ebike": e, "casual": c, "spec": name, **r,
                         "N_days": int(fit._N)})
    return pd.DataFrame(rows)


def station_level_check(bins):
    """Station-level fit of the rain-interaction model (no bins, to fit in memory) vs daily totals."""
    p = pd.read_parquet(cp.PANEL_PARQUET, columns=["station", "date_id", "ebike", "casual",
                                                    "trips", "main"])
    p = p[p.main].drop(columns="main")
    cal = cp.load_calendar()[["date_id", "rain_any"]]
    p = p.merge(cal, on="date_id")
    p["e_rain"] = (p.ebike * p.rain_any).astype(np.int8)
    p["c_rain"] = (p.casual * p.rain_any).astype(np.int8)
    p["x_rain"] = (p.ebike * p.casual * p.rain_any).astype(np.int8)
    fml = "trips ~ e_rain + c_rain + x_rain | station^ebike^casual + date_id"
    s = cp.coef_table(fepois(fml, p), label="station_level")
    del p
    g = cp.load_daily_groups("main", ("ebike", "casual"))
    g["e_rain"] = g.ebike * g.rain_any
    g["c_rain"] = g.casual * g.rain_any
    g["x_rain"] = g.ebike * g.casual * g.rain_any
    a = cp.coef_table(fepois("trips ~ e_rain + c_rain + x_rain | ebike^casual + date_id", g),
                      label="daily_totals")
    return pd.concat([s, a], ignore_index=True)


def figure(lev, con):
    style.apply()
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10, 4.6), gridspec_kw={"width_ratios": [1, 1.25],
                                                                         "wspace": 0.62})
    m = lev[lev.spec == "rain_any"].set_index("group")
    order = [glabel(*g) for g in GROUPS]
    y = np.arange(len(order))[::-1]
    for yi, gname in zip(y, order):
        r = m.loc[gname]
        color = cp.EBIKE if r.ebike == 1 else cp.CLASSIC
        marker = "s" if r.casual == 1 else "o"
        ax1.errorbar(r.pct, yi, xerr=[[r.pct - r.pct_lo], [r.pct_hi - r.pct]], fmt=marker, ms=7,
                     color=color, elinewidth=1.6, capsize=0, mec=style.SURFACE, mew=1.2)
        ax1.annotate(f"{r.pct:.1f}%", (r.pct_lo, yi), xytext=(-6, 0), textcoords="offset points",
                     ha="right", va="center", fontsize=8.5, color=style.TEXT)
    ax1.set_yticks(y, order)
    ax1.axvline(0, color=style.TEXT_MUTED, lw=0.8)
    ax1.set_xlim(min(m.pct_lo.min() * 1.35, -40), 2)
    ax1.set_xlabel("Rain day (PRCP > 0) vs dry day, % change in trips")
    ax1.set_title("A. Rain effect by group")
    ax1.text(0, -0.24, "Circle = member, square = casual. Separate Poisson model per group,\n"
             "95% CI clustered by date.", transform=ax1.transAxes, fontsize=7.5,
             color=style.TEXT_MUTED, va="top")

    specs = ["rain_any", "rain_01", "rain_05", "weekday_only", "weekend_only", "cluster_week",
             "plus_group_x_snow", "group_specific_calendar", "full_sample"]
    names = {"rain_any": "Main: PRCP > 0", "rain_01": "PRCP >= 0.1 in", "rain_05": "PRCP >= 0.5 in",
             "weekday_only": "Weekdays only", "weekend_only": "Weekends only",
             "cluster_week": "Cluster by week", "plus_group_x_snow": "+ group x snow",
             "group_specific_calendar": "+ group-specific calendar",
             "full_sample": "Full station sample"}
    terms = [("ebike_vs_classic_member", "E-bike vs classic, members", style.MEMBER, "o"),
             ("ebike_vs_classic_casual", "E-bike vs classic, casual", style.CASUAL, "s"),
             ("ebike_advantage_casual_minus_member", "Casual minus member advantage",
              style.TEXT_MUTED, "D")]
    yy = np.arange(len(specs))[::-1]
    for k, (term, lab, color, mk) in enumerate(terms):
        s = con[con.term == term].set_index("spec").reindex(specs)
        off = (1 - k) * 0.24
        ax2.errorbar(s.pct, yy + off, xerr=[s.pct - s.pct_lo, s.pct_hi - s.pct], fmt=mk, ms=5,
                     color=color, elinewidth=1.2, capsize=0, mec=style.SURFACE, mew=1, label=lab)
    ax2.axvline(0, color=style.TEXT_MUTED, lw=0.8)
    ax2.set_yticks(yy, [names[s] for s in specs], fontsize=8.5)
    ax2.set_xlabel("Difference in rain effect (%, exp(b) - 1), stacked date-FE model")
    ax2.set_title("B. Contrasts and stress tests")
    ax2.legend(loc="upper center", bbox_to_anchor=(0.35, -0.14), ncol=2, fontsize=8)
    cp.save_fig(fig, "fig2_rain_by_bike_and_rider.png")


def main():
    cp.ensure_dirs()
    bins = cp.bin_order()
    if "--figure-only" in sys.argv:
        figure(pd.read_csv(cp.TAB_DIR / "f2_rain_levels_by_group.csv"),
               pd.read_csv(cp.TAB_DIR / "f2_rain_contrasts.csv"))
        return
    g = cp.load_daily_groups("main", ("ebike", "casual"))
    lev = levels(g, bins)
    con, full_coefs, _ = stacked(g, bins)
    check = station_level_check(bins)

    lev.to_csv(cp.TAB_DIR / "f2_rain_levels_by_group.csv", index=False)
    con.to_csv(cp.TAB_DIR / "f2_rain_contrasts.csv", index=False)
    cp.add_bin_labels(full_coefs).to_csv(cp.TAB_DIR / "f2_stacked_main_all_coefficients.csv", index=False)
    check.to_csv(cp.TAB_DIR / "f2_station_level_equivalence_check.csv", index=False)

    # E-bike share on dry vs rain days within month, for context (main panel).
    tot = g.groupby(["date_id", "casual"]).trips.sum().rename("all")
    eb = g[g.ebike == 1].set_index(["date_id", "casual"]).trips.rename("e")
    share = pd.concat([tot, eb], axis=1).reset_index().merge(
        cp.load_calendar()[["date_id", "year_month", "rain_any"]], on="date_id")
    share["share"] = share.e / share["all"]
    share["within"] = share.share - share.groupby(["year_month", "casual"]).share.transform("mean")
    share_tab = share.groupby(["casual", "rain_any"]).agg(days=("share", "size"),
                                                          share=("share", "mean"),
                                                          within_month_pp=("within", "mean"))
    share_tab["within_month_pp"] *= 100
    share_tab.reset_index().to_csv(cp.TAB_DIR / "f2_ebike_share_rain_vs_dry.csv", index=False)

    figure(lev, con)
    pd.set_option("display.width", 220)
    print(lev[["group", "spec", "pct", "pct_lo", "pct_hi", "N_days"]].round(2).to_string(index=False))
    print(con[["spec", "term", "pct", "pct_lo", "pct_hi", "p", "N"]].round(3).to_string(index=False))
    print(check.round(5).to_string(index=False))
    print(share_tab)


if __name__ == "__main__":
    sys.exit(main())
