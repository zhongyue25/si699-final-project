"""Finding 4 (Checkpoint 2): is the casual-member rain gap about the rider or about the trip?

Peer review: rider type does not identify trip purpose. We use the hourly record to look at trips by
when and where they happen.

Data: main-panel trip starts per local clock hour x rider type (x trip context), hourly NOAA LCD weather.
Rain exposure (exp_rain): measurable rain (>= 0.25 mm, no snow code) in this hour's report or the
previous hour's report. Snow hours (exp_snow) are a separate control.

(A) Within-day timing. Poisson with date FE (everything common to the day cancels) and hour x day type
    x month FE (the usual daily profile):
        trips ~ wet_f2 + wet_f1 + wet_0 + wet_l1..l4 + exp_snow + temp_c | rider^date + rider^hour^daytype^ym
(B) Rain hours vs dry hours of rainy days. Same data without date FE, with daily temperature bins, wind,
    snow day:
        trips ~ exp_rain + exp_snow + dry_on_wetday + snow_day + T + wind | rider^hour^daytype^ym
    dry_on_wetday = an hour with no rain exposure on a day with at least one measurable-rain hour.
(C) Trip context. Disjoint contexts (round trip; weekday 7-10am into the CBD; weekday 4-8pm out of the
    CBD; other weekday morning / midday / afternoon; weekend daytime; night), with every term and FE
    specific to rider x context, so casual and member riders are compared within the same context and
    the same hours of the same days.
(D) Decomposition of the casual-member gap in (C) into context mix and within-context difference, with
    weights = dry-hour trip shares, CIs by simulation from the joint covariance.
SEs clustered by date throughout.
"""

import sys
import warnings

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pyfixest as pf

import cp1_common as cp
import cp2_common as c2
import plot_style as style

warnings.filterwarnings("ignore")
N_SIM = 20_000
RNG = np.random.default_rng(699)
RIDERS = {0: "Member", 1: "Casual"}
CONTEXTS = ["am_in", "pm_out", "wd_am", "wd_mid", "wd_pm", "we_day", "night", "round"]
CONTEXT_LABEL = {
    "am_in": "Weekday 7-10am, into CBD", "pm_out": "Weekday 4-8pm, out of CBD",
    "wd_am": "Weekday 7-10am, other", "wd_mid": "Weekday 10am-4pm", "wd_pm": "Weekday 4-8pm, other",
    "we_day": "Weekend/holiday 10am-8pm", "night": "Night (8pm-7am)", "round": "Round trip (any time)"}
EVENT_TERMS = ["wet_f2", "wet_f1", "wet_meas", "wet_l1", "wet_l2", "wet_l3", "wet_l4"]
EVENT_LABEL = ["h+2", "h+1", "h", "h-1", "h-2", "h-3", "h-4"]


def fepois(fml, data, cluster="date_id"):
    return pf.fepois(fml, data=data, vcov={"CRV1": cluster}, ssc=cp.SSC, copy_data=False)


def rider_terms(d, cols, key="casual"):
    """Rider-specific copies of cols: m_<col> for members, c_<col> for casual."""
    out = []
    for c in cols:
        for r, p in ((0, "m"), (1, "c")):
            n = f"{p}_{c}"
            d[n] = d[c] * (d[key] == r)
            out.append(n)
    return out


# ----------------------------------------------------------------------------------------------- A
def event_profile(g):
    d = g.copy()
    terms = rider_terms(d, EVENT_TERMS + ["exp_snow", "temp_c"])
    fit = fepois(f"trips ~ {' + '.join(terms)} | casual^date_id + casual^hour^daytype^year_month", d)
    t = cp.coef_table(fit, [t for t in terms if not t.endswith(("exp_snow", "temp_c"))])
    t["rider"] = np.where(t.term.str.startswith("c_"), "Casual", "Member")
    t["lag"] = t.term.str[2:].map(dict(zip(EVENT_TERMS, EVENT_LABEL)))
    sums = [cp.lincom(fit, {f"{p}_{x}": 1 for x in EVENT_TERMS[2:]}, f"{p}_sum_h_to_h-4")
            for p in ("m", "c")]
    sums.append(cp.lincom(fit, {**{f"c_{x}": 1 for x in EVENT_TERMS[2:]},
                                **{f"m_{x}": -1 for x in EVENT_TERMS[2:]}}, "casual_minus_member_sum"))
    return t, pd.DataFrame(sums)


# ----------------------------------------------------------------------------------------------- B
def rain_vs_dry_hours(g, bins, by_weekend=False):
    d = g.copy()
    T = cp.add_bin_dummies(d, bins)
    d["snow_day"] = d.lcd_snowday
    base = ["exp_rain", "exp_snow", "dry_on_wetday", "snow_day", "awnd_ms"] + T
    rows = []
    subsets = [("all", d)] if not by_weekend else [("weekday", d[d.weekend == 0]),
                                                   ("weekend", d[d.weekend == 1])]
    for name, dd in subsets:
        dd = dd.copy()
        terms = rider_terms(dd, base)
        fit = fepois(f"trips ~ {' + '.join(terms)} | casual^hour^daytype^year_month", dd)
        keep = [f"{p}_{x}" for p in ("m", "c") for x in ("exp_rain", "exp_snow", "dry_on_wetday")]
        t = cp.coef_table(fit, keep, label=name)
        diffs = [cp.lincom(fit, {f"c_{x}": 1, f"m_{x}": -1}, f"diff_{x}")
                 for x in ("exp_rain", "dry_on_wetday")]
        rows.append(pd.concat([t, pd.DataFrame(diffs).assign(model=name)], ignore_index=True))
    return pd.concat(rows, ignore_index=True)


# ----------------------------------------------------------------------------------------------- C
def add_context(h):
    wd = h.weekend == 0
    am, pm = h.hour.between(7, 9), h.hour.between(16, 19)
    h["context"] = np.select(
        [h.round_trip == 1,
         wd & am & (h.start_zone == 0) & (h.end_zone == 1),
         wd & pm & (h.start_zone == 1) & (h.end_zone == 0),
         wd & am, wd & h.hour.between(10, 15), wd & pm,
         (~wd) & h.hour.between(10, 19)],
        ["round", "am_in", "pm_out", "wd_am", "wd_mid", "wd_pm", "we_day"], "night")
    return h


def context_grid(sample="main"):
    """date x hour x rider x context, zeros filled only where the context can occur."""
    h = pd.read_parquet(c2.HOURLY_TRIPS)
    if sample == "main":
        h = h[h.main]
    cal = c2.load_calendar()[["date", "weekday", "holiday"]]
    h = h.merge(cal, on="date")
    h["weekend"] = ((h.weekday >= 5) | (h.holiday == 1)).astype(np.int8)
    h = add_context(h)
    trips = h.groupby(["date", "hour", "casual", "context"]).trips.sum()
    g = c2.hourly_grid(["casual"], sample=sample).drop(columns="trips")
    g = g.merge(pd.DataFrame({"context": CONTEXTS}), how="cross")
    # Keep each context only in the hours where it is defined (round trips and night: their own rule).
    ok = ((g.context == "round")
          | ((g.context == "night") & (g.block == "night"))
          | (g.context.isin(["am_in", "wd_am"]) & (g.block == "wd_am"))
          | (g.context.isin(["pm_out", "wd_pm"]) & (g.block == "wd_pm"))
          | ((g.context == "wd_mid") & (g.block == "wd_mid"))
          | ((g.context == "we_day") & (g.block == "we_day")))
    g = g[ok].copy()
    g = g.join(trips, on=["date", "hour", "casual", "context"])
    g["trips"] = g.trips.fillna(0).astype(np.int64)
    g["cell"] = g.casual.astype(str) + "_" + g.context
    return g


def context_model(g, rain="exp_rain", cluster="date_id"):
    d = g.copy()
    terms, new = [], {}
    for c in sorted(d.cell.unique()):
        ind = (d.cell == c).to_numpy()
        for v in (rain, "exp_snow", "temp_c"):
            n = f"{v}__{c}"
            new[n] = np.where(ind, d[v].to_numpy(), 0.0)
            terms.append(n)
    d = pd.concat([d, pd.DataFrame(new, index=d.index)], axis=1)
    fit = fepois(f"trips ~ {' + '.join(terms)} | cell^date_id + cell^hour^daytype^year_month", d,
                 cluster=cluster)
    rain_terms = [t for t in terms if t.startswith(f"{rain}__")]
    t = cp.coef_table(fit, rain_terms)
    t["cell"] = t.term.str.split("__").str[1]
    t["rider"] = t.cell.str[0].astype(int).map(RIDERS)
    t["context"] = t.cell.str[2:]
    diffs = []
    for ctx in CONTEXTS:
        a, b = f"{rain}__1_{ctx}", f"{rain}__0_{ctx}"
        if a in fit._coefnames and b in fit._coefnames:
            r = cp.lincom(fit, {a: 1, b: -1}, f"casual_minus_member__{ctx}")
            r["context"] = ctx
            diffs.append(r)
    return fit, t, pd.DataFrame(diffs), rain_terms


# ----------------------------------------------------------------------------------------------- D
def decomposition(fit, g, rain_terms, rain="exp_rain"):
    dry = g[g[rain] == 0].groupby(["casual", "context"]).trips.sum()
    w = (dry / dry.groupby(level=0).transform("sum")).unstack("context")[CONTEXTS]
    b = pd.Series(fit.coef())[rain_terms]
    V = pd.DataFrame(fit._vcov, index=fit._coefnames, columns=fit._coefnames).loc[rain_terms,
                                                                                    rain_terms]

    def q(beta):
        r = {k: np.array([np.expm1(beta[f"{rain}__{k}_{c}"]) for c in CONTEXTS]) for k in (0, 1)}
        wm, wc = w.loc[0].to_numpy(), w.loc[1].to_numpy()
        Am, Ac = wm @ r[0], wc @ r[1]
        mix_a, within_a = (wc - wm) @ r[1], wm @ (r[1] - r[0])
        mix_b, within_b = (wc - wm) @ r[0], wc @ (r[1] - r[0])
        return {"member_avg": Am, "casual_avg": Ac, "gap": Ac - Am,
                "casual_with_member_mix": wm @ r[1],
                "mix": (mix_a + mix_b) / 2, "within": (within_a + within_b) / 2}

    point = q(b)
    sims = pd.DataFrame([q(pd.Series(x, index=rain_terms))
                         for x in RNG.multivariate_normal(b.to_numpy(), V.to_numpy(), size=N_SIM)])
    rows = [{"quantity": k, "pp": 100 * v, "pp_lo": 100 * sims[k].quantile(0.025),
             "pp_hi": 100 * sims[k].quantile(0.975)} for k, v in point.items()]
    shares = w.T.rename(columns=RIDERS).reset_index()
    return pd.DataFrame(rows), shares


# ----------------------------------------------------------------------------------------- figure
def figure(ev, ctx, diffs, shares):
    style.apply()
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10.6, 4.4), gridspec_kw={"width_ratios": [0.8, 1.35],
                                                                           "wspace": 0.62})
    x = np.arange(len(EVENT_LABEL))
    for k, (rider, color, mk) in enumerate((("Member", style.MEMBER, "o"), ("Casual", style.CASUAL, "s"))):
        s = ev[ev.rider == rider].set_index("lag").reindex(EVENT_LABEL)
        off = (k - 0.5) * 0.18
        ax1.errorbar(x + off, s.pct, yerr=[s.pct - s.pct_lo, s.pct_hi - s.pct], fmt=mk, ms=5,
                     color=color, elinewidth=1.3, capsize=0, mec=style.SURFACE, mew=1, label=rider)
    ax1.axhline(0, color=style.TEXT_MUTED, lw=0.8)
    ax1.axvspan(1.5, 6.5, color=style.GRID, alpha=0.35, lw=0)
    ax1.set_xticks(x, ["+2h", "+1h", "same\nhour", "-1h", "-2h", "-3h", "-4h"], fontsize=8.5)
    ax1.set_xlabel("Hour with measurable rain,\nrelative to the trip's start hour")
    ax1.set_ylabel("% change in trip starts")
    ax1.set_title("A. Timing within the day")
    ax1.legend(loc="lower left", fontsize=8.5)

    order = ["am_in", "wd_am", "wd_mid", "pm_out", "wd_pm", "night", "we_day", "round"]
    y = np.arange(len(order))[::-1]
    sh = shares.set_index("context")
    for k, (rider, color, mk) in enumerate((("Member", style.MEMBER, "o"), ("Casual", style.CASUAL, "s"))):
        s = ctx[ctx.rider == rider].set_index("context").reindex(order)
        off = (0.5 - k) * 0.28
        ax2.errorbar(s.pct, y + off, xerr=[s.pct - s.pct_lo, s.pct_hi - s.pct], fmt=mk, ms=5,
                     color=color, elinewidth=1.3, capsize=0, mec=style.SURFACE, mew=1, label=rider)
    labels = [f"{CONTEXT_LABEL[c]}\n{100 * sh.loc[c, 'Member']:.0f}% / {100 * sh.loc[c, 'Casual']:.0f}%"
              for c in order]
    ax2.set_yticks(y, labels, fontsize=8)
    ax2.axvline(0, color=style.TEXT_MUTED, lw=0.8)
    dd = diffs.set_index("context").reindex(order)
    xmax = ax2.get_xlim()[1]
    for yi, c in zip(y, order):
        r = dd.loc[c]
        sig = "*" if (r.pct_lo > 0 or r.pct_hi < 0) else ""
        ax2.annotate(f"{(round(r.pct) or 0):+d}{sig}", (1.0, yi), xycoords=("axes fraction", "data"),
                     xytext=(6, 0), textcoords="offset points", va="center", fontsize=8,
                     color=style.TEXT)
    ax2.annotate("C - M", (1.0, 1.0), xycoords="axes fraction", xytext=(6, 2),
                 textcoords="offset points", fontsize=7.5, color=style.TEXT_MUTED, va="bottom")
    ax2.set_xlabel("Rain-exposed hour vs dry hour, same day, % change in trip starts")
    ax2.set_title("B. Rain effect by trip context")
    ax2.legend(loc="upper left", bbox_to_anchor=(0.0, 1.0), fontsize=8.5, ncol=2)
    lo, hi = ax2.get_ylim()
    ax2.set_ylim(lo, hi + 0.6)
    ax2.text(0, -0.2, "Under each label: share of member / casual dry-hour trips in that context. "
             "Right: casual minus member, * = 95% CI excludes 0.", transform=ax2.transAxes,
             fontsize=7.3, color=style.TEXT_MUTED, va="top")
    c2.save_fig(fig, "fig4_hourly_rain_context.png")


def main():
    c2.ensure_dirs()
    if "--figure-only" in sys.argv:
        figure(pd.read_csv(c2.TAB_DIR / "f4a_event_profile.csv"), pd.read_csv(c2.TAB_DIR / "f4c_context_effects.csv"),
               pd.read_csv(c2.TAB_DIR / "f4c_context_diffs.csv"), pd.read_csv(c2.TAB_DIR / "f4d_context_shares.csv"))
        return
    bins = cp.bin_order()
    pd.set_option("display.width", 220)
    g = c2.hourly_grid(["casual"])

    ev, ev_sums = event_profile(g)
    ev.to_csv(c2.TAB_DIR / "f4a_event_profile.csv", index=False)
    ev_sums.to_csv(c2.TAB_DIR / "f4a_event_sums.csv", index=False)
    print(ev[["rider", "lag", "pct", "pct_lo", "pct_hi"]].round(1).to_string(index=False))
    print(ev_sums[["term", "pct", "pct_lo", "pct_hi", "p"]].round(2).to_string(index=False))

    rd = pd.concat([rain_vs_dry_hours(g, bins), rain_vs_dry_hours(g, bins, by_weekend=True)])
    rd.to_csv(c2.TAB_DIR / "f4b_rain_vs_dry_hours.csv", index=False)
    print(rd[["model", "term", "pct", "pct_lo", "pct_hi", "p"]].round(2).to_string(index=False))

    cg = context_grid()
    fit, ctx, diffs, rain_terms = context_model(cg)
    dec, shares = decomposition(fit, cg, rain_terms)
    ctx.to_csv(c2.TAB_DIR / "f4c_context_effects.csv", index=False)
    diffs.to_csv(c2.TAB_DIR / "f4c_context_diffs.csv", index=False)
    dec.to_csv(c2.TAB_DIR / "f4d_decomposition.csv", index=False)
    shares.to_csv(c2.TAB_DIR / "f4d_context_shares.csv", index=False)
    print(ctx[["rider", "context", "pct", "pct_lo", "pct_hi"]].round(1).to_string(index=False))
    print(diffs[["context", "pct", "pct_lo", "pct_hi", "p"]].round(2).to_string(index=False))
    print(shares.round(3).to_string(index=False))
    print(dec.round(2).to_string(index=False))

    # Stress tests on the context model and decomposition.
    rows = []
    for label, kw, data in [("main", {}, cg),
                            ("cluster_week", {"cluster": "week_id"}, cg),
                            ("any_precip_incl_trace", {"rain": "exp_any"}, cg),
                            ("full_station_sample", {}, None)]:
        if label == "main":
            dd, rt, f = diffs, rain_terms, fit
        else:
            if data is None:
                data = context_grid("full")
            data = data.copy()
            if label == "cluster_week":
                data = data.merge(cp.load_calendar()[["date_id", "week_id"]], on="date_id")
            f, _, dd, rt = context_model(data, **kw)
        de, _ = decomposition(f, data if data is not None else cg, rt, kw.get("rain", "exp_rain"))
        rows.append(dd.assign(spec=label))
        rows.append(de.rename(columns={"quantity": "term", "pp": "pct", "pp_lo": "pct_lo",
                                       "pp_hi": "pct_hi"}).assign(spec=label, context="decomp"))
        print("stress", label, flush=True)
    stress = pd.concat(rows, ignore_index=True)
    stress.to_csv(c2.TAB_DIR / "f4e_stress_tests.csv", index=False)
    print(stress[["spec", "context", "term", "pct", "pct_lo", "pct_hi"]].round(2).to_string(index=False))

    figure(ev, ctx, diffs, shares)


if __name__ == "__main__":
    sys.exit(main())
