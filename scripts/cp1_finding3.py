"""Finding 3: is the system becoming less weather-sensitive?

(a) Daily system totals (main panel). Poisson:
      trips ~ rain:period + tmax_c:period + snow + wind + holiday | year_month + weekday
    for period = quarter (8) and half-year (4). The TMAX slope is identified from variation within a
    calendar month, so it is a local slope for that season, comparable across years for the same
    season, not across seasons. SEs: heteroskedasticity-robust (= clustered by date at this level),
    Newey-West with 7 lags as a stress test.
(b) Composition decomposition of the aggregate rain effect into bike mix and within-type change.
"""

import sys

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pyfixest as pf

import cp1_common as cp
import plot_style as style

N_SIM = 20_000
RNG = np.random.default_rng(699)


def fepois(fml, data, vcov="hetero", **kw):
    return pf.fepois(fml, data=data, vcov=vcov, ssc=cp.SSC, copy_data=False, **kw)


def by_period(daily, period):
    d = daily.copy()
    periods = sorted(d[period].unique())
    terms = []
    for p in periods:
        for v in ("rain", "tmax_c"):
            name = f"{v}_{p}"
            d[name] = d[v] * (d[period] == p)
            terms.append(name)
    fml = f"trips ~ {' + '.join(terms)} + snow + awnd_ms + holiday | year_month + weekday"
    out = []
    for label, kw in [("hetero", {}),
                      ("newey_west_7", {"vcov": "NW", "vcov_kwargs": {"lag": 7, "time_id": "date_id"}})]:
        fit = fepois(fml, d, **kw)
        t = cp.coef_table(fit, terms, label=label)
        t["var"] = t.term.str.rsplit("_", n=1).str[0]
        t["period"] = t.term.str.rsplit("_", n=1).str[1]
        out.append(t)
        if label == "hetero":
            # Same season, 2025 vs 2024.
            tests = []
            for p in periods:
                if p.startswith("2025"):
                    q = p.replace("2025", "2024")
                    for v in ("rain", "tmax_c"):
                        r = cp.lincom(fit, {f"{v}_{p}": 1, f"{v}_{q}": -1}, f"{v}: {p} - {q}")
                        tests.append(r)
            tests = pd.DataFrame(tests)
    res = pd.concat(out, ignore_index=True)
    meta = d.groupby(period).agg(days=("date_id", "size"), rain_days=("rain", "sum"),
                                 heavy_rain_days=("rain_05", "sum"),
                                 tmax_sd=("tmax_c", "std"), tmax_min=("tmax_c", "min"),
                                 tmax_max=("tmax_c", "max"),
                                 within_month_tmax_sd=("tmax_dm", "std"))
    return res, tests, meta.reset_index().rename(columns={period: "period"})


def yearly_system(daily, bins):
    d = daily.copy()
    T = cp.add_bin_dummies(d, bins)
    for y in (2024, 2025):
        d[f"rain_{y}"] = d.rain * (d.year == y)
    fit = fepois(f"trips ~ rain_2024 + rain_2025 + {' + '.join(T)} + snow + awnd_ms + holiday"
                 " | year_month + weekday", d)
    t = cp.coef_table(fit, ["rain_2024", "rain_2025"], label="system_direct")
    diff = cp.lincom(fit, {"rain_2025": 1, "rain_2024": -1}, "rain_2025_minus_2024")
    return t, diff


def decomposition(g, keys, bins, label):
    """Rain effect by cell x year from one stacked Poisson with every term cell-specific."""
    d = g.copy()
    d["cell"] = d[keys].astype(str).agg("_".join, axis=1)
    cells = sorted(d.cell.unique())
    T = cp.add_bin_dummies(d, bins)
    terms, rain_terms, new = [], [], {}
    for c in cells:
        ind = (d.cell == c).astype(np.int8)
        for y in (2024, 2025):
            n = f"r{y}_c{c}"
            new[n] = ind * d.rain * (d.year == y)
            terms.append(n)
            rain_terms.append(n)
        for v in T + ["snow", "awnd_ms", "holiday"]:
            n = f"{v}_c{c}"
            new[n] = ind * d[v]
            terms.append(n)
    d = pd.concat([d, pd.DataFrame(new, index=d.index)], axis=1)
    fit = fepois(f"trips ~ {' + '.join(terms)} | cell^year_month + cell^weekday", d,
                 vcov={"CRV1": "date_id"})
    b = pd.Series(fit.coef())[rain_terms]
    V = pd.DataFrame(fit._vcov, index=fit._coefnames, columns=fit._coefnames).loc[rain_terms,
                                                                                    rain_terms]
    # Weights: each cell's share of dry-day trips in that year (the no-rain baseline mix).
    dry = d[d.rain == 0].groupby(["year", "cell"]).trips.sum()
    w = (dry / dry.groupby(level=0).transform("sum")).unstack("cell")[cells]
    w_all = d.groupby(["year", "cell"]).trips.sum()
    w_all = (w_all / w_all.groupby(level=0).transform("sum")).unstack("cell")[cells]

    def quantities(beta, W):
        r = {y: np.array([np.expm1(beta[f"r{y}_c{c}"]) for c in cells]) for y in (2024, 2025)}
        w24, w25 = W.loc[2024].to_numpy(), W.loc[2025].to_numpy()
        A24, A25 = w24 @ r[2024], w25 @ r[2025]
        cf = w24 @ r[2025]  # 2025 effects with the 2024 mix
        mix_a = (w25 - w24) @ r[2025]
        within_a = w24 @ (r[2025] - r[2024])
        mix_b = (w25 - w24) @ r[2024]
        within_b = w25 @ (r[2025] - r[2024])
        return {"A2024": A24, "A2025": A25, "A2025_with_2024_mix": cf, "change": A25 - A24,
                "mix_2025_effects": mix_a, "within_2024_weights": within_a,
                "mix_2024_effects": mix_b, "within_2025_weights": within_b,
                "mix_shapley": (mix_a + mix_b) / 2, "within_shapley": (within_a + within_b) / 2}

    draws = RNG.multivariate_normal(b.to_numpy(), V.to_numpy(), size=N_SIM)
    rows = []
    for wname, W in (("dry_day_share", w), ("all_day_share", w_all)):
        point = quantities(b, W)
        sims = pd.DataFrame([quantities(pd.Series(x, index=rain_terms), W) for x in draws])
        for k, v in point.items():
            rows.append({"decomposition": label, "weights": wname, "quantity": k,
                         "pp": 100 * v, "pp_lo": 100 * sims[k].quantile(0.025),
                         "pp_hi": 100 * sims[k].quantile(0.975)})
    effects = cp.coef_table(fit, rain_terms, label=label)
    effects["cell"] = effects.term.str.split("_c", n=1).str[1]
    effects["year"] = effects.term.str[1:5].astype(int)
    shares = pd.concat([w.assign(weights="dry_day_share"), w_all.assign(weights="all_day_share")])
    shares["decomposition"] = label
    return pd.DataFrame(rows), effects, shares.reset_index()


def quarterly_share(g):
    q = g.groupby(["quarter", "ebike"]).trips.sum().unstack()
    return (q[1] / q.sum(axis=1)).rename("ebike_share").reset_index()


def figure(q, share, meta):
    style.apply()
    q = q[q.model == "hetero"]
    periods = sorted(q.period.unique())
    x = np.arange(len(periods))
    fig, axes = plt.subplots(3, 1, figsize=(7.4, 7.6), sharex=True,
                             gridspec_kw={"hspace": 0.28, "height_ratios": [1.2, 1.2, 0.8]})
    for ax, var, ylab, title in [
        (axes[0], "rain", "Rain day vs dry day (%)", "A. Rain effect by quarter"),
        (axes[1], "tmax_c", "% per +1 °C (+1.8 °F)\nTMAX, within month", "B. Temperature slope by quarter"),
    ]:
        s = q[q["var"] == var].set_index("period").reindex(periods)
        for yr, color in (("2024", style.NEUTRAL), ("2025", style.TEXT)):
            m = s.index.str.startswith(yr)
            ax.errorbar(x[m], s.pct[m], yerr=[(s.pct - s.pct_lo)[m], (s.pct_hi - s.pct)[m]],
                        fmt="o", ms=6, color=color, elinewidth=1.4, capsize=0,
                        mec=style.SURFACE, mew=1.2, label=yr)
        ax.axhline(0, color=style.TEXT_MUTED, lw=0.8)
        ax.set_ylabel(ylab)
        ax.set_title(title)
    axes[0].legend(loc="upper right", ncol=2, fontsize=8)
    lo, hi = axes[0].get_ylim()
    axes[0].set_ylim(lo - 4, hi + 3)
    rd = meta.set_index("period").reindex(periods)
    for xi, p in zip(x, periods):
        axes[0].annotate(f"{int(rd.rain_days[p])} rain d", (xi, 0), xycoords=("data", "axes fraction"),
                         xytext=(0, 3), textcoords="offset points", ha="center", va="bottom",
                         fontsize=7, color=style.TEXT_MUTED)
    sh = share.set_index("quarter").reindex(periods)
    axes[2].plot(x, 100 * sh.ebike_share, color=cp.EBIKE, marker="o", ms=5, mec=style.SURFACE)
    for xi, v in zip(x, 100 * sh.ebike_share):
        axes[2].annotate(f"{v:.0f}%", (xi, v), xytext=(0, 6), textcoords="offset points",
                         ha="center", fontsize=7.5, color=style.TEXT)
    axes[2].set_ylabel("E-bike share\nof trips (%)")
    axes[2].set_title("C. E-bike share by quarter")
    lo, hi = axes[2].get_ylim()
    axes[2].set_ylim(lo - 1, hi + 2)
    axes[2].set_xticks(x, periods)
    cp.save_fig(fig, "fig3_weather_sensitivity_over_time.png")


def main():
    cp.ensure_dirs()
    bins = cp.bin_order()
    g = cp.load_daily_groups("main", ("ebike", "casual"))
    daily = g.groupby("date_id").trips.sum().reset_index().merge(
        cp.load_calendar()[cp.CAL_COLS], on="date_id")
    daily["tmax_dm"] = daily.tmax_c - daily.groupby("year_month").tmax_c.transform("mean")
    share = quarterly_share(g)
    if "--figure-only" in sys.argv:
        figure(pd.read_csv(cp.TAB_DIR / "f3a_by_quarter.csv"), share,
               pd.read_csv(cp.TAB_DIR / "f3a_quarter_weather_counts.csv"))
        return

    q, q_tests, q_meta = by_period(daily, "quarter")
    h, h_tests, h_meta = by_period(daily, "half")
    sys_year, sys_diff = yearly_system(daily, bins)

    bike = g.groupby(["date_id", "ebike"]).trips.sum().reset_index().merge(
        cp.load_calendar()[cp.CAL_COLS], on="date_id")
    dec_b, eff_b, sh_b = decomposition(bike, ["ebike"], bins, "bike_type")
    dec_g, eff_g, sh_g = decomposition(g, ["ebike", "casual"], bins, "bike_x_rider")

    q.to_csv(cp.TAB_DIR / "f3a_by_quarter.csv", index=False)
    h.to_csv(cp.TAB_DIR / "f3a_by_half_year.csv", index=False)
    pd.concat([q_tests.assign(level="quarter"), h_tests.assign(level="half")]).to_csv(
        cp.TAB_DIR / "f3a_same_season_differences.csv", index=False)
    q_meta.to_csv(cp.TAB_DIR / "f3a_quarter_weather_counts.csv", index=False)
    h_meta.to_csv(cp.TAB_DIR / "f3a_half_year_weather_counts.csv", index=False)
    share.to_csv(cp.TAB_DIR / "f3_ebike_share_by_quarter.csv", index=False)
    pd.concat([dec_b, dec_g]).to_csv(cp.TAB_DIR / "f3b_decomposition.csv", index=False)
    pd.concat([eff_b, eff_g]).to_csv(cp.TAB_DIR / "f3b_rain_effects_by_cell_year.csv", index=False)
    pd.concat([sh_b, sh_g]).to_csv(cp.TAB_DIR / "f3b_weights.csv", index=False)
    pd.concat([sys_year, pd.DataFrame([sys_diff]).assign(model="system_direct")]).to_csv(
        cp.TAB_DIR / "f3b_system_rain_by_year.csv", index=False)

    figure(q, share, q_meta)
    pd.set_option("display.width", 220)
    cols = ["model", "var", "period", "pct", "pct_lo", "pct_hi"]
    print(q[cols].round(2).to_string(index=False))
    print(h[cols].round(2).to_string(index=False))
    print(q_tests.round(3).to_string(index=False))
    print(h_tests.round(3).to_string(index=False))
    print(q_meta.round(2).to_string(index=False))
    print(sys_year.round(3).to_string(index=False)); print(sys_diff)
    print(pd.concat([dec_b, dec_g]).round(3).to_string(index=False))
    print(pd.concat([eff_b, eff_g])[["model", "cell", "year", "pct", "pct_lo", "pct_hi"]].round(2)
          .to_string(index=False))
    print(pd.concat([sh_b, sh_g]).round(4).to_string(index=False))


if __name__ == "__main__":
    sys.exit(main())
