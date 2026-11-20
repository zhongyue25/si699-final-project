"""Checkpoint 3: trip purpose x bike type x trip distance in the hourly rain response.

Question. Checkpoint 2 found that the e-bike rain advantage shrinks with trip distance (members: +7.3%
under 1 km, +2.6% over 5 km), which we read as pointing to availability. But distance is a mixed proxy:
long trips are more often commute-type, and cp3_purpose_ebike.py shows the e-bike advantage is smallest
on commute-type trips. So the distance gradient may reflect trip composition rather than distance.
Here we estimate the distance gradient *within* purpose groups.

Design. Same hourly design as cp3_purpose_ebike.py, with distance band added to every cell:
cells = rider (2) x context (7; round trips have no A-to-B distance and are excluded) x bike (2) x
band (short < 2 km, long >= 2 km straight-line between stations) = 56. Cell-specific rain, snow, and
temperature terms; cell x date and cell x hour x daytype x month fixed effects; SEs clustered by date.

Purpose-level effects average context log effects with weights = the rider's dry-hour trip shares of
the contexts in the group. Two weightings:
    fixed     one set of weights for both bands (context mix held constant: distance itself)
    own-band  each band's own context mix (what a pooled distance model measures)
The gap between the two shows how much of a pooled distance gradient is trip composition.
All quantities (including the e-bike / classic penalty ratio) are computed on 20,000 draws from the
joint covariance of the rain coefficients.

Outputs: reports/tables/checkpoint3/p2_*.csv, figures/checkpoint3/fig6_purpose_distance.png.
--stress reruns with week clustering, trace precipitation, and a 3 km cut-off.
"""

import sys
import warnings

import numpy as np
import pandas as pd
import pyfixest as pf

import config
import cp1_common as cp
import cp2_common as c2
from cp2_finding4 import add_context

warnings.filterwarnings("ignore")
TAB_DIR = config.TABLES_DIR / "checkpoint3"
FIG_DIR = config.FIGURES_DIR / "checkpoint3"
HOURLY_DIST = config.PROCESSED_DIR / "hourly_trips_distance.parquet"
RIDERS = {0: "Member", 1: "Casual"}
BIKES = {0: "Classic", 1: "E-bike"}
CONTEXTS = ["am_in", "pm_out", "wd_am", "wd_pm", "wd_mid", "we_day", "night"]
PURPOSE = {"commute": ["am_in", "pm_out", "wd_am", "wd_pm"], "leisure": ["we_day"],
           "mixed": ["wd_mid", "night"]}
BANDS = ["short", "long"]
N_SIM = 20_000


def cell_name(r, b, c, d):
    return f"{r}{b}_{d}_{c}"


# ------------------------------------------------------------------------------------------- data
def grid(sample="main", cut_km=2.0, rain="exp_rain"):
    h = pd.read_parquet(HOURLY_DIST)
    if sample == "main":
        h = h[h.main]
    h = h[h.band != "round"].copy()
    long_bands = {2.0: ["2_3", "3_5", "ge5"], 3.0: ["3_5", "ge5"]}[cut_km]
    h["dband"] = np.where(h.band.isin(long_bands), "long", "short")
    cal = c2.load_calendar()[["date", "weekday", "holiday"]]
    h = h.merge(cal, on="date")
    h["weekend"] = ((h.weekday >= 5) | (h.holiday == 1)).astype(np.int8)
    h = add_context(h)
    trips = h.groupby(["date", "hour", "casual", "ebike", "dband", "context"]).trips.sum()
    g = c2.hourly_grid(["casual", "ebike"], sample=sample).drop(columns="trips")
    g = g.merge(pd.DataFrame({"context": CONTEXTS}), how="cross").merge(
        pd.DataFrame({"dband": BANDS}), how="cross")
    ok = (((g.context == "night") & (g.block == "night"))
          | (g.context.isin(["am_in", "wd_am"]) & (g.block == "wd_am"))
          | (g.context.isin(["pm_out", "wd_pm"]) & (g.block == "wd_pm"))
          | ((g.context == "wd_mid") & (g.block == "wd_mid"))
          | ((g.context == "we_day") & (g.block == "we_day")))
    g = g[ok].copy()
    g = g.join(trips, on=["date", "hour", "casual", "ebike", "dband", "context"])
    g["trips"] = g.trips.fillna(0).astype(np.int64)
    g["cell"] = [cell_name(*x) for x in zip(g.casual, g.ebike, g.context, g.dband)]
    return g


def counts(g, rain="exp_rain"):
    d = g.assign(rain_trips=g.trips * (g[rain] == 1), dry_trips=g.trips * (g[rain] == 0))
    out = d.groupby(["casual", "ebike", "dband", "context"]).agg(
        rain_hours=(rain, "sum"), trips=("trips", "sum"), rain_trips=("rain_trips", "sum"),
        dry_trips=("dry_trips", "sum")).reset_index()
    out["rider"] = out.casual.map(RIDERS)
    out["bike"] = out.ebike.map(BIKES)
    inv = {c: p for p, cs in PURPOSE.items() for c in cs}
    out["purpose"] = out.context.map(inv)
    return out


# ------------------------------------------------------------------------------------------ model
def fit_model(g, rain="exp_rain", cluster="date_id"):
    d = g.copy()
    terms, new = [], {}
    for c in sorted(d.cell.unique()):
        ind = (d.cell == c).to_numpy()
        for v in (rain, "exp_snow", "temp_c"):
            n = f"{v}__{c}"
            new[n] = np.where(ind, d[v].to_numpy(), 0.0)
            terms.append(n)
    d = pd.concat([d, pd.DataFrame(new, index=d.index)], axis=1)
    return pf.fepois(f"trips ~ {' + '.join(terms)} | cell^date_id + cell^hour^daytype^year_month",
                     data=d, vcov={"CRV1": cluster}, ssc=cp.SSC, copy_data=False)


def estimates(fit, g, rain="exp_rain"):
    """Every reported quantity as a function of the rain coefficients, point + simulated 95% CI."""
    names = [f"{rain}__{cell_name(r, b, c, d)}" for r in (0, 1) for b in (0, 1) for c in CONTEXTS
             for d in BANDS]
    idx = {n: i for i, n in enumerate(names)}
    beta = pd.Series(fit.coef())[names].to_numpy()
    V = pd.DataFrame(fit._vcov, index=fit._coefnames, columns=fit._coefnames).loc[names, names]
    rng = np.random.default_rng(699)
    S = np.vstack([beta, rng.multivariate_normal(beta, V.to_numpy(), size=N_SIM)])  # row 0 = point

    dry = g[g[rain] == 0].groupby(["casual", "dband", "context"]).trips.sum()

    def weights(r, p, band_mix):
        cs = PURPOSE[p]
        s = dry.loc[r].unstack("context")[cs]  # rows = band
        return (s.loc[band_mix] / s.loc[band_mix].sum()) if band_mix != "fixed" else \
            (s.sum() / s.sum().sum())

    def avg(r, b, p, d, mix):
        w = weights(r, p, d if mix == "own" else "fixed")
        vec = np.zeros(len(names))
        for c in PURPOSE[p]:
            vec[idx[f"{rain}__{cell_name(r, b, c, d)}"]] = w[c]
        return S @ vec  # log effect, all draws

    rows = []

    def put(kind, x, pct=True, **meta):
        f = np.expm1 if pct else (lambda v: v)
        lo, hi = np.quantile(x[1:], [0.025, 0.975])
        rows.append({"kind": kind, **meta, "est": 100 * f(x[0]) if pct else x[0],
                     "lo": 100 * f(lo) if pct else lo, "hi": 100 * f(hi) if pct else hi,
                     "p": 2 * min((x[1:] > 0).mean(), (x[1:] < 0).mean())})

    groups = list(PURPOSE) + ["all"]
    for r in (0, 1):
        for p in PURPOSE:
            for mix in ("fixed",):
                L = {(b, d): avg(r, b, p, d, mix) for b in (0, 1) for d in BANDS}
                m = dict(rider=RIDERS[r], purpose=p, mix=mix)
                for b in (0, 1):
                    for d in BANDS:
                        put("rain_effect", L[(b, d)], bike=BIKES[b], band=d, **m)
                    # distance gradient of the rain penalty (long vs short), per bike
                    put("rain_gradient_long_vs_short", L[(b, "long")] - L[(b, "short")], bike=BIKES[b], **m)
                for d in BANDS:
                    put("ebike_adv", L[(1, d)] - L[(0, d)], band=d, **m)
                    put("penalty_ratio", L[(1, d)] / L[(0, d)], pct=False, band=d, **m)
                put("ebike_adv_gradient_long_minus_short",
                    (L[(1, "long")] - L[(0, "long")]) - (L[(1, "short")] - L[(0, "short")]), **m)
                put("penalty_ratio_long_minus_short",
                    L[(1, "long")] / L[(0, "long")] - L[(1, "short")] / L[(0, "short")], pct=False, **m)
        # Pooled over purposes: composition held fixed vs each band's own context mix.
        for mix in ("fixed", "own"):
            dd = dry.loc[r]
            wt = {}
            for d in BANDS:
                base = dd.groupby("context").sum() if mix == "fixed" else dd.loc[d]
                wt[d] = (base[CONTEXTS] / base[CONTEXTS].sum())
            L = {}
            for b in (0, 1):
                for d in BANDS:
                    vec = np.zeros(len(names))
                    for c in CONTEXTS:
                        vec[idx[f"{rain}__{cell_name(r, b, c, d)}"]] = wt[d][c]
                    L[(b, d)] = S @ vec
            m = dict(rider=RIDERS[r], purpose="all", mix=mix)
            for d in BANDS:
                put("ebike_adv", L[(1, d)] - L[(0, d)], band=d, **m)
                put("penalty_ratio", L[(1, d)] / L[(0, d)], pct=False, band=d, **m)
            for b in (0, 1):
                put("rain_gradient_long_vs_short", L[(b, "long")] - L[(b, "short")], bike=BIKES[b], **m)
            put("ebike_adv_gradient_long_minus_short",
                (L[(1, "long")] - L[(0, "long")]) - (L[(1, "short")] - L[(0, "short")]), **m)
    out = pd.DataFrame(rows)
    # H2: is the classic-bike distance gradient of the rain penalty steeper on leisure than commute?
    return out


def h2_contrasts(fit, g, rain="exp_rain"):
    """Leisure minus commute distance gradient (classic bikes), per rider, via lincom."""
    dry = g[g[rain] == 0].groupby(["casual", "context"]).trips.sum()
    rows = []
    for b in (0, 1):
        for r in (0, 1):
            vec = {}
            for p, sgn in (("leisure", 1), ("commute", -1)):
                s = dry.loc[r].reindex(PURPOSE[p])
                for c in PURPOSE[p]:
                    w = s[c] / s.sum()
                    vec[f"{rain}__{cell_name(r, b, c, 'long')}"] = sgn * w
                    vec[f"{rain}__{cell_name(r, b, c, 'short')}"] = -sgn * w
            rows.append({**cp.lincom(fit, vec, "rain_gradient_leisure_minus_commute"),
                         "rider": RIDERS[r], "bike": BIKES[b]})
    return pd.DataFrame(rows)


def show(df, cols):
    print(df[cols].round(2).to_string(index=False), flush=True)


COLS = ["kind", "rider", "purpose", "mix", "bike", "band", "est", "lo", "hi", "p"]


def main():
    TAB_DIR.mkdir(parents=True, exist_ok=True)
    pd.set_option("display.width", 220)
    if "--figure-only" in sys.argv:
        figure()
        return
    if "--stress" in sys.argv:
        out = []
        g = grid()
        gw = g.merge(cp.load_calendar()[["date_id", "week_id"]], on="date_id")
        out.append(estimates(fit_model(gw, cluster="week_id"), gw).assign(spec="cluster_week"))
        print("done week", flush=True)
        out.append(estimates(fit_model(g, rain="exp_any"), g, rain="exp_any").assign(spec="trace"))
        print("done trace", flush=True)
        g3 = grid(cut_km=3.0)
        out.append(estimates(fit_model(g3), g3).assign(spec="cut_3km"))
        print("done 3km", flush=True)
        s = pd.concat(out, ignore_index=True)
        s.to_csv(TAB_DIR / "p2_stress.csv", index=False)
        k = s.kind.isin(["ebike_adv_gradient_long_minus_short", "penalty_ratio", "rain_gradient_long_vs_short"])
        show(s[k], ["spec"] + COLS)
        return

    g = grid()
    print("grid rows", len(g), "cells", g.cell.nunique(), flush=True)
    n = counts(g)
    n.to_csv(TAB_DIR / "p2_cell_counts.csv", index=False)
    print(n.groupby(["rider", "purpose", "bike", "dband"])[["rain_trips", "dry_trips"]].sum().to_string())
    fit = fit_model(g)
    est = estimates(fit, g)
    est.to_csv(TAB_DIR / "p2_estimates.csv", index=False)
    h2 = h2_contrasts(fit, g)
    h2.to_csv(TAB_DIR / "p2_h2_contrasts.csv", index=False)
    show(est, COLS)
    show(h2, ["term", "rider", "bike", "pct", "pct_lo", "pct_hi", "p"])
    figure()


# ----------------------------------------------------------------------------------------- figure
def figure():
    """A: e-bike advantage on short vs long trips, by purpose x rider (and pooled, with the context mix
    held fixed or left to vary by band). B: distance gradient of the rain penalty, by bike type."""
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D

    import plot_style as style

    style.apply()
    e = pd.read_csv(TAB_DIR / "p2_estimates.csv")
    plabel = {"commute": "Commute-type", "mixed": "Midday / night", "leisure": "Leisure-type",
              "all": "All purposes"}
    rows = [(p, r, "fixed") for p in ("commute", "mixed", "leisure", "all") for r in ("Member", "Casual")]
    rows += [("all", r, "own") for r in ("Member", "Casual")]
    y = np.arange(len(rows))[::-1].astype(float) - np.repeat([0, 0.5, 1.0, 1.5, 2.0], 2)
    labels = [f"{plabel[p]}, {r.lower()}" + ("\n(each band's own context mix)" if m == "own" else "")
              for p, r, m in rows]

    fig, (a1, a2) = plt.subplots(1, 2, figsize=(10.4, 4.8), sharey=True,
                                 gridspec_kw={"width_ratios": [1, 1], "wspace": 0.1})

    def pick(kind, p, r, m, **kw):
        q = e[(e.kind == kind) & (e.purpose == p) & (e.rider == r) & (e.mix == m)]
        for k, v in kw.items():
            q = q[q[k] == v]
        return q.iloc[0]

    for yi, (p, r, m) in zip(y, rows):
        color = style.MEMBER if r == "Member" else style.CASUAL
        s, l = pick("ebike_adv", p, r, m, band="short"), pick("ebike_adv", p, r, m, band="long")
        a1.plot([s.est, l.est], [yi, yi], color=style.GRID, lw=2.5, zorder=1, solid_capstyle="round")
        for v, off, filled in ((s, 0.13, False), (l, -0.13, True)):
            a1.errorbar(v.est, yi + off, xerr=[[v.est - v.lo], [v.hi - v.est]], fmt="o", ms=6,
                        color=color, mfc=color if filled else style.SURFACE, mew=1.4, elinewidth=1.1,
                        capsize=0, zorder=3)
        for bike, bc, mk, off in (("Classic", cp.CLASSIC, "o", 0.13), ("E-bike", cp.EBIKE, "s", -0.13)):
            if m == "own":
                continue
            v = pick("rain_gradient_long_vs_short", p, r, m, bike=bike)
            a2.errorbar(v.est, yi + off, xerr=[[v.est - v.lo], [v.hi - v.est]], fmt=mk, ms=6, color=bc,
                        elinewidth=1.1, capsize=0, mec=style.SURFACE, mew=1.1, zorder=3)
    a1.axvline(0, color=style.TEXT_MUTED, lw=0.8)
    a1.set_yticks(y, labels, fontsize=8.3)
    a1.set_xlabel("E-bike advantage in rain-exposed hours (%)")
    a1.set_title("A. The e-bike advantage shrinks with distance")
    a1.legend(handles=[Line2D([], [], marker="o", ls="", color=style.NEUTRAL, mfc=style.SURFACE, mew=1.4,
                              ms=6, label="Short trip (< 2 km)"),
                       Line2D([], [], marker="o", ls="", color=style.NEUTRAL, ms=6,
                              label="Long trip (2 km +)")], loc="upper right", fontsize=8)
    a2.axvline(0, color=style.TEXT_MUTED, lw=0.8)
    a2.set_xlabel("Rain penalty on long vs short trips (% difference)")
    a2.set_title("B. Rain hits long trips harder, most on leisure")
    a2.legend(handles=[Line2D([], [], marker="o", ls="", color=cp.CLASSIC, ms=6, label="Classic"),
                       Line2D([], [], marker="s", ls="", color=cp.EBIKE, ms=6, label="E-bike")],
              loc="lower left", fontsize=8)
    a1.axhspan(y[-1] - 0.5, y[-2] + 0.5, color=style.GRID, alpha=0.35, lw=0, zorder=0)
    a2.axhspan(y[-1] - 0.5, y[-2] + 0.5, color=style.GRID, alpha=0.35, lw=0, zorder=0)
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    fig.savefig(FIG_DIR / "fig6_purpose_distance.png", dpi=200, bbox_inches="tight")
    plt.close(fig)


if __name__ == "__main__":
    sys.exit(main())
