"""Checkpoint 3: trip purpose x bike type (effort) in the hourly rain response.

Question. Finding 4 showed that the casual-member rain gap sits in leisure-type contexts. Here we cross
that purpose axis with the effort axis (e-bike vs classic): does the e-bike rain advantage depend on
trip purpose, and does Checkpoint 1's larger casual e-bike advantage on weekdays come from casual
riders on commute-type trips?

Design. Same hourly design as Finding 4 (cp2_finding4.py), with bike type added to every cell:
cells = rider (2) x context (8) x bike (2) = 32. Every term and fixed effect is cell-specific:
    trips ~ sum_cell [exp_rain + exp_snow + temp_c] x 1{cell} | cell^date + cell^hour^daytype^month
so each coefficient compares rain-exposed with dry hours of the same day, within one rider x context x
bike cell. The e-bike advantage in a rider x context is exp(b_ebike - b_classic) - 1.

Purpose groups (pre-specified, from the contexts in which casual riders and members responded alike
or differently in Finding 4):
    commute = weekday 7-10am and 4-8pm (into/out of the CBD and other)
    leisure = weekend/holiday daytime, round trips
    mixed   = weekday midday, night (errands, nightlife, shift work: purpose unclear)
Purpose-level effects are weighted averages of the context log effects, weights = the rider's dry-hour
trip shares (both bike types pooled) across the contexts in the group, so e-bike and classic use the
same weights.

Outputs (reports/tables/checkpoint3): cell rain effects, e-bike advantage by rider x context and rider x
purpose, purpose contrasts, casual-minus-member contrasts, cell counts. Run with --stress for the
stress tests (week clustering, trace precipitation, all stations).
"""

import sys
import warnings

import numpy as np
import pandas as pd
import pyfixest as pf

import config
import cp1_common as cp
import cp2_common as c2
from cp2_finding4 import CONTEXTS, CONTEXT_LABEL, add_context

warnings.filterwarnings("ignore")
TAB_DIR = config.TABLES_DIR / "checkpoint3"
FIG_DIR = config.FIGURES_DIR / "checkpoint3"
RIDERS = {0: "Member", 1: "Casual"}
BIKES = {0: "Classic", 1: "E-bike"}
PURPOSE = {"commute": ["am_in", "pm_out", "wd_am", "wd_pm"],
           "leisure": ["we_day", "round"],
           "mixed": ["wd_mid", "night"]}
CTX_PURPOSE = {c: p for p, cs in PURPOSE.items() for c in cs}


def cell_name(casual, ebike, ctx):
    return f"{casual}{ebike}_{ctx}"


# ------------------------------------------------------------------------------------------- data
def purpose_grid(sample="main"):
    """date x hour x rider x bike x context, zeros filled only where the context can occur."""
    h = pd.read_parquet(c2.HOURLY_TRIPS)
    if sample == "main":
        h = h[h.main]
    cal = c2.load_calendar()[["date", "weekday", "holiday"]]
    h = h.merge(cal, on="date")
    h["weekend"] = ((h.weekday >= 5) | (h.holiday == 1)).astype(np.int8)
    h = add_context(h)
    trips = h.groupby(["date", "hour", "casual", "ebike", "context"]).trips.sum()
    g = c2.hourly_grid(["casual", "ebike"], sample=sample).drop(columns="trips")
    g = g.merge(pd.DataFrame({"context": CONTEXTS}), how="cross")
    ok = ((g.context == "round")
          | ((g.context == "night") & (g.block == "night"))
          | (g.context.isin(["am_in", "wd_am"]) & (g.block == "wd_am"))
          | (g.context.isin(["pm_out", "wd_pm"]) & (g.block == "wd_pm"))
          | ((g.context == "wd_mid") & (g.block == "wd_mid"))
          | ((g.context == "we_day") & (g.block == "we_day")))
    g = g[ok].copy()
    g = g.join(trips, on=["date", "hour", "casual", "ebike", "context"])
    g["trips"] = g.trips.fillna(0).astype(np.int64)
    g["cell"] = [cell_name(a, b, c) for a, b, c in zip(g.casual, g.ebike, g.context)]
    return g


def cell_counts(g, rain="exp_rain"):
    """Hours and trips behind each cell (instructor/peer request: n per context)."""
    d = g.assign(rain_trips=g.trips * (g[rain] == 1), dry_trips=g.trips * (g[rain] == 0))
    out = d.groupby(["casual", "ebike", "context"]).agg(
        hours=("trips", "size"), rain_hours=(rain, "sum"),
        trips=("trips", "sum"), rain_trips=("rain_trips", "sum"),
        dry_trips=("dry_trips", "sum")).reset_index()
    out["rider"] = out.casual.map(RIDERS)
    out["bike"] = out.ebike.map(BIKES)
    out["purpose"] = out.context.map(CTX_PURPOSE)
    out["context_label"] = out.context.map(CONTEXT_LABEL)
    return out


def dry_weights(g, rain="exp_rain"):
    """Rider's dry-hour trip share of each context within its purpose group (bikes pooled)."""
    dry = g[g[rain] == 0].groupby(["casual", "context"]).trips.sum()
    w = {}
    for r in (0, 1):
        for p, cs in PURPOSE.items():
            s = dry.loc[r].reindex(cs)
            for c in cs:
                w[(r, c)] = s[c] / s.sum()
    return w


# ------------------------------------------------------------------------------------------ model
def fepois(fml, data, cluster="date_id"):
    return pf.fepois(fml, data=data, vcov={"CRV1": cluster}, ssc=cp.SSC, copy_data=False)


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
    return fepois(f"trips ~ {' + '.join(terms)} | cell^date_id + cell^hour^daytype^year_month", d,
                  cluster=cluster)


def summarize(fit, w, rain="exp_rain"):
    """Cell effects, e-bike advantages by context and purpose, and the key contrasts."""
    T = lambda r, b, c: f"{rain}__{cell_name(r, b, c)}"  # noqa: E731

    # (1) rain effect in each cell
    names = [T(r, b, c) for r in (0, 1) for b in (0, 1) for c in CONTEXTS]
    cells = cp.coef_table(fit, names)
    cells["rider"] = [RIDERS[r] for r in (0, 1) for _ in (0, 1) for _ in CONTEXTS]
    cells["bike"] = [BIKES[b] for _ in (0, 1) for b in (0, 1) for _ in CONTEXTS]
    cells["context"] = [c for _ in (0, 1) for _ in (0, 1) for c in CONTEXTS]
    cells["purpose"] = cells.context.map(CTX_PURPOSE)

    def adv(r, c):  # e-bike minus classic, one rider x context (log scale)
        return {T(r, 1, c): 1.0, T(r, 0, c): -1.0}

    def add(*ws, scale=None):
        out = {}
        for i, wd in enumerate(ws):
            s = 1.0 if scale is None else scale[i]
            for k, v in wd.items():
                out[k] = out.get(k, 0.0) + s * v
        return out

    def purpose_avg(r, p, bike=None):
        """Weighted average over the purpose's contexts: of e-bike advantage, or of one bike's effect."""
        out = {}
        for c in PURPOSE[p]:
            part = adv(r, c) if bike is None else {T(r, bike, c): 1.0}
            out = add(out, part, scale=[1.0, w[(r, c)]])
        return out

    rows = []

    def lc(weights, label, **meta):
        rows.append({**cp.lincom(fit, weights, label), **meta})

    # (2) e-bike advantage by rider x context
    for r in (0, 1):
        for c in CONTEXTS:
            lc(adv(r, c), "ebike_adv", rider=RIDERS[r], context=c, purpose=CTX_PURPOSE[c])
    # casual minus member e-bike advantage, by context
    for c in CONTEXTS:
        lc(add(adv(1, c), adv(0, c), scale=[1, -1]), "casual_minus_member_ebike_adv",
           rider="Casual-Member", context=c, purpose=CTX_PURPOSE[c])

    # (3) purpose level: each bike's rain effect, e-bike advantage, and contrasts
    for r in (0, 1):
        for p in PURPOSE:
            for b in (0, 1):
                lc(purpose_avg(r, p, bike=b), "rain_effect", rider=RIDERS[r], bike=BIKES[b],
                   context="all", purpose=p)
            lc(purpose_avg(r, p), "ebike_adv", rider=RIDERS[r], context="all", purpose=p)
        # H1: is the e-bike advantage larger on commute-type than on leisure-type trips?
        for p in ("leisure", "mixed"):
            lc(add(purpose_avg(r, "commute"), purpose_avg(r, p), scale=[1, -1]),
               f"ebike_adv_commute_minus_{p}", rider=RIDERS[r], context="all", purpose=f"commute-{p}")
    for p in PURPOSE:
        lc(add(purpose_avg(1, p), purpose_avg(0, p), scale=[1, -1]), "casual_minus_member_ebike_adv",
           rider="Casual-Member", context="all", purpose=p)
    # triple difference: does the casual-member gap in e-bike advantage differ commute vs leisure?
    lc(add(purpose_avg(1, "commute"), purpose_avg(0, "commute"), purpose_avg(1, "leisure"),
           purpose_avg(0, "leisure"), scale=[1, -1, -1, 1]),
       "casual_minus_member_ebike_adv_commute_minus_leisure", rider="Casual-Member", context="all",
       purpose="commute-leisure")
    return cells, pd.DataFrame(rows)


def weekday_split(fit, g, rain="exp_rain"):
    """E-bike advantage over all weekday-daytime contexts vs weekend daytime (Checkpoint 1 analogue)."""
    T = lambda r, b, c: f"{rain}__{cell_name(r, b, c)}"  # noqa: E731
    dry = g[g[rain] == 0].groupby(["casual", "context"]).trips.sum()
    groups = {"weekday_daytime": ["am_in", "pm_out", "wd_am", "wd_pm", "wd_mid"],
              "weekend_daytime": ["we_day"]}
    rows, wts = [], {}
    for r in (0, 1):
        for gname, cs in groups.items():
            s = dry.loc[r].reindex(cs)
            wts[(r, gname)] = {c: s[c] / s.sum() for c in cs}
            wv = {}
            for c in cs:
                wv[T(r, 1, c)] = wts[(r, gname)][c]
                wv[T(r, 0, c)] = -wts[(r, gname)][c]
            rows.append({**cp.lincom(fit, wv, "ebike_adv"), "rider": RIDERS[r], "group": gname})
    for gname in groups:
        wv = {}
        for r, s in ((1, 1.0), (0, -1.0)):
            for c, x in wts[(r, gname)].items():
                wv[T(r, 1, c)] = wv.get(T(r, 1, c), 0) + s * x
                wv[T(r, 0, c)] = wv.get(T(r, 0, c), 0) - s * x
        rows.append({**cp.lincom(fit, wv, "casual_minus_member_ebike_adv"), "rider": "Casual-Member",
                     "group": gname})
    return pd.DataFrame(rows)


def penalty_ratio(fit, w, rain="exp_rain", n_sim=20_000, seed=699):
    """Share of the classic rain penalty that remains on e-bikes, per rider x purpose:
    ratio = b_ebike / b_classic (log scale; 0.85 = e-bikes keep 85% of the classic penalty).
    CIs and purpose contrasts by simulation from the joint covariance."""
    T = lambda r, b, c: f"{rain}__{cell_name(r, b, c)}"  # noqa: E731
    names = [T(r, b, c) for r in (0, 1) for b in (0, 1) for c in CONTEXTS]
    b = pd.Series(fit.coef())[names]
    V = pd.DataFrame(fit._vcov, index=fit._coefnames, columns=fit._coefnames).loc[names, names]

    def q(beta):
        out = {}
        for r in (0, 1):
            for p, cs in PURPOSE.items():
                be = sum(w[(r, c)] * beta[T(r, 1, c)] for c in cs)
                bc = sum(w[(r, c)] * beta[T(r, 0, c)] for c in cs)
                out[(RIDERS[r], p)] = be / bc
            out[(RIDERS[r], "commute-leisure")] = out[(RIDERS[r], "commute")] - out[(RIDERS[r], "leisure")]
            out[(RIDERS[r], "commute-mixed")] = out[(RIDERS[r], "commute")] - out[(RIDERS[r], "mixed")]
        for p in list(PURPOSE) + ["commute-leisure"]:
            out[("Casual-Member", p)] = out[("Casual", p)] - out[("Member", p)]
        return out

    point = q(b)
    rng = np.random.default_rng(seed)
    sims = pd.DataFrame([q(pd.Series(x, index=names))
                         for x in rng.multivariate_normal(b.to_numpy(), V.to_numpy(), size=n_sim)])
    return pd.DataFrame([{"rider": k[0], "purpose": k[1], "ratio": v,
                          "lo": sims[k].quantile(0.025), "hi": sims[k].quantile(0.975)}
                         for k, v in point.items()])


def day_level_model(g, rain="exp_rain"):
    """No date FE: rain-exposed hours AND the dry hours of rainy days vs hours on dry days, per cell,
    to reconcile with Checkpoint 1's daily e-bike x rider x weekday result (Table 3 analogue)."""
    d = g.copy()
    d["snow_day"] = d.lcd_snowday
    vs = [rain, "dry_on_wetday", "exp_snow", "snow_day", "temp_c", "awnd_ms"]
    terms, new = [], {}
    for c in sorted(d.cell.unique()):
        ind = (d.cell == c).to_numpy()
        for v in vs:
            n = f"{v}__{c}"
            new[n] = np.where(ind, d[v].to_numpy(), 0.0)
            terms.append(n)
    d = pd.concat([d, pd.DataFrame(new, index=d.index)], axis=1)
    fit = fepois(f"trips ~ {' + '.join(terms)} | cell^hour^daytype^year_month + cell^tbin", d)
    dry = g[g[rain] == 0].groupby(["casual", "context"]).trips.sum()
    rows = []
    for v in (rain, "dry_on_wetday"):
        T = lambda r, b, c: f"{v}__{cell_name(r, b, c)}"  # noqa: E731
        for p, cs in {**PURPOSE, "weekday_daytime": ["am_in", "pm_out", "wd_am", "wd_pm", "wd_mid"]}.items():
            wts = {r: (dry.loc[r].reindex(cs) / dry.loc[r].reindex(cs).sum()).to_dict() for r in (0, 1)}
            adv = {r: {} for r in (0, 1)}
            for r in (0, 1):
                for c in cs:
                    adv[r][T(r, 1, c)] = wts[r][c]
                    adv[r][T(r, 0, c)] = -wts[r][c]
                rows.append({**cp.lincom(fit, adv[r], "ebike_adv"), "rider": RIDERS[r], "hours": v,
                             "purpose": p})
            diff = {k: adv[1].get(k, 0) - adv[0].get(k, 0) for k in set(adv[0]) | set(adv[1])}
            rows.append({**cp.lincom(fit, diff, "casual_minus_member_ebike_adv"),
                         "rider": "Casual-Member", "hours": v, "purpose": p})
    return pd.DataFrame(rows), fit


# ------------------------------------------------------------------------------------------- main
def run(g, label, **kw):
    rain = kw.get("rain", "exp_rain")
    fit = fit_model(g, **kw)
    w = dry_weights(g, rain)
    cells, con = summarize(fit, w, rain)
    wk = weekday_split(fit, g, rain)
    ratio = penalty_ratio(fit, w, rain, n_sim=5_000)
    return (cells.assign(spec=label), con.assign(spec=label), wk.assign(spec=label),
            ratio.assign(spec=label))


def show(df, cols):
    print(df[cols].round(2).to_string(index=False), flush=True)


def main():
    TAB_DIR.mkdir(parents=True, exist_ok=True)
    if "--figure-only" in sys.argv:
        figure()
        return
    pd.set_option("display.width", 220)
    g = purpose_grid()
    print("grid rows", len(g), "cells", g.cell.nunique(), flush=True)

    if "--stress" not in sys.argv:
        counts = cell_counts(g)
        counts.to_csv(TAB_DIR / "p1_cell_counts.csv", index=False)
        show(counts, ["rider", "bike", "context", "hours", "rain_hours", "trips", "rain_trips"])

        fit = fit_model(g)
        w = dry_weights(g)
        cells, con = summarize(fit, w)
        wk = weekday_split(fit, g)
        ratio = penalty_ratio(fit, w)
        cells.to_csv(TAB_DIR / "p1_cell_rain_effects.csv", index=False)
        con.to_csv(TAB_DIR / "p1_contrasts.csv", index=False)
        wk.to_csv(TAB_DIR / "p1_weekday_split.csv", index=False)
        ratio.to_csv(TAB_DIR / "p1_penalty_ratio.csv", index=False)
        show(cells, ["rider", "bike", "context", "pct", "pct_lo", "pct_hi"])
        show(con, ["term", "rider", "bike", "purpose", "context", "pct", "pct_lo", "pct_hi", "p"])
        show(wk, ["term", "rider", "group", "pct", "pct_lo", "pct_hi", "p"])
        show(ratio, ["rider", "purpose", "ratio", "lo", "hi"])
        day, fit_day = day_level_model(g)
        day.to_csv(TAB_DIR / "p1_day_level.csv", index=False)
        show(day, ["term", "rider", "hours", "purpose", "pct", "pct_lo", "pct_hi", "p"])
        rd = pd.concat([penalty_ratio(fit_day, w, rain=v).assign(hours=v)
                        for v in ("exp_rain", "dry_on_wetday")], ignore_index=True)
        rd.to_csv(TAB_DIR / "p1_day_level_penalty_ratio.csv", index=False)
        show(rd, ["hours", "rider", "purpose", "ratio", "lo", "hi"])
        figure()
        return

    out = []
    gw = g.merge(cp.load_calendar()[["date_id", "week_id"]], on="date_id")
    out.append(run(gw, "cluster_week", cluster="week_id"))
    print("done cluster_week", flush=True)
    out.append(run(g, "any_precip_incl_trace", rain="exp_any"))
    print("done trace", flush=True)
    out.append(run(purpose_grid("full"), "full_station_sample"))
    print("done full", flush=True)
    con = pd.concat([o[1] for o in out], ignore_index=True)
    wk = pd.concat([o[2] for o in out], ignore_index=True)
    ratio = pd.concat([o[3] for o in out], ignore_index=True)
    ratio.to_csv(TAB_DIR / "p1_stress_penalty_ratio.csv", index=False)
    show(ratio, ["spec", "rider", "purpose", "ratio", "lo", "hi"])
    con.to_csv(TAB_DIR / "p1_stress_contrasts.csv", index=False)
    wk.to_csv(TAB_DIR / "p1_stress_weekday_split.csv", index=False)
    show(con[con.context == "all"], ["spec", "term", "rider", "bike", "purpose", "pct", "pct_lo",
                                     "pct_hi", "p"])
    show(wk, ["spec", "term", "rider", "group", "pct", "pct_lo", "pct_hi", "p"])



# ----------------------------------------------------------------------------------------- figure
def figure():
    """A: rain penalty by purpose x rider for each bike type. B: share of the classic penalty that
    remains on e-bikes (within-day design, and the across-day design as hollow markers)."""
    import matplotlib.pyplot as plt

    import plot_style as style

    style.apply()
    con = pd.read_csv(TAB_DIR / "p1_contrasts.csv")
    ratio = pd.read_csv(TAB_DIR / "p1_penalty_ratio.csv")
    rday = pd.read_csv(TAB_DIR / "p1_day_level_penalty_ratio.csv")
    rday = rday[rday.hours == "exp_rain"]
    counts = pd.read_csv(TAB_DIR / "p1_cell_counts.csv")
    eff = con[(con.term == "rain_effect")]
    order = [(p, r) for p in ("commute", "mixed", "leisure") for r in ("Member", "Casual")]
    plabel = {"commute": "Commute-type", "mixed": "Midday / night", "leisure": "Leisure-type"}
    rain_trips = counts.groupby(["rider", "purpose"]).rain_trips.sum()
    y = np.arange(len(order))[::-1].astype(float)
    y -= np.repeat([0, 0.5, 1.0], 2)  # small gap between purpose groups

    fig, (a1, a2) = plt.subplots(1, 2, figsize=(10.4, 4.2), sharey=True,
                                 gridspec_kw={"width_ratios": [1.25, 1], "wspace": 0.12})
    for yi, (p, r) in zip(y, order):
        s = eff[(eff.purpose == p) & (eff.rider == r)].set_index("bike")
        a1.plot([s.loc["Classic", "pct"], s.loc["E-bike", "pct"]], [yi, yi], color=style.GRID, lw=2.5,
                zorder=1, solid_capstyle="round")
        for bike, color, mk in (("Classic", cp.CLASSIC, "o"), ("E-bike", cp.EBIKE, "s")):
            v = s.loc[bike]
            a1.errorbar(v.pct, yi, xerr=[[v.pct - v.pct_lo], [v.pct_hi - v.pct]], fmt=mk, ms=6.5,
                        color=color, elinewidth=1.2, capsize=0, mec=style.SURFACE, mew=1.2, zorder=3,
                        label=bike if (p, r) == order[0] else None)
    a1.axvline(0, color=style.TEXT_MUTED, lw=0.8)
    a1.set_xlim(-45, 2)
    a1.set_xlabel("Rain-exposed vs dry hour, same day (% change in trip starts)")
    a1.set_title("A. Trip purpose sets the size of the rain penalty")
    a1.legend(loc="lower right", fontsize=8.5)
    a1.set_yticks(y, [f"{plabel[p]}, {r.lower()}\n{rain_trips[(r, p)] / 1e3:,.0f}k rain-hour trips"
                      for p, r in order], fontsize=8.3)

    for yi, (p, r) in zip(y, order):
        color = style.MEMBER if r == "Member" else style.CASUAL
        v = ratio[(ratio.purpose == p) & (ratio.rider == r)].iloc[0]
        a2.errorbar(v.ratio, yi + 0.12, xerr=[[v.ratio - v.lo], [v.hi - v.ratio]], fmt="o", ms=6.5,
                    color=color, elinewidth=1.2, capsize=0, mec=style.SURFACE, mew=1.2, zorder=3)
        d = rday[(rday.purpose == p) & (rday.rider == r)].iloc[0]
        a2.errorbar(d.ratio, yi - 0.12, xerr=[[d.ratio - d.lo], [d.hi - d.ratio]], fmt="o", ms=6,
                    color=color, mfc=style.SURFACE, elinewidth=1.0, capsize=0, mew=1.4, zorder=3)
    a2.axvline(1, color=style.TEXT_MUTED, lw=0.8)
    a2.annotate("1 = e-bikes lose\nas many trips\nas classic", (1.0, y[3] - 0.65), xytext=(5, 0),
                textcoords="offset points", ha="left", va="center", fontsize=7.5,
                color=style.TEXT_MUTED)
    a2.set_xlim(0.5, 1.15)
    a2.set_xlabel("E-bike penalty ÷ classic penalty (log points)")
    a2.set_title("B. E-bikes keep a similar share of it")
    from matplotlib.lines import Line2D
    a2.legend(handles=[Line2D([], [], marker="o", ls="", color=style.NEUTRAL, ms=6,
                              label="Same day (date FE)"),
                       Line2D([], [], marker="o", ls="", color=style.NEUTRAL, mfc=style.SURFACE, mew=1.4,
                              ms=6, label="Across days (no date FE)")],
              loc="center left", bbox_to_anchor=(0.0, 0.655), fontsize=7.8,
              borderpad=0.1, labelspacing=0.3)
    a1.set_ylim(y.min() - 0.6, y.max() + 0.9)
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    fig.savefig(FIG_DIR / "fig5_purpose_x_ebike.png", dpi=200, bbox_inches="tight")
    plt.close(fig)


if __name__ == "__main__":
    sys.exit(main())
