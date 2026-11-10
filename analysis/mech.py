"""Exploratory (not pre-registered): why does the multi-window burn-rate rule (M9) fire late or not at all?
For every breach run in a block, reconstruct the frontend bad-request fraction (rt > 100 ms) in 10-s slices, the breach
onset (score3 ground truth), the first time each burn condition holds, and what the first-to-fire adaptive detector saw.
Usage: python3 mech.py RUNDIR results/primary.json OUT.csv [--block primary]"""
import sys, os, json, math, argparse, pandas as pd, numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import score3 as S

ap = argparse.ArgumentParser(); ap.add_argument("rundir"); ap.add_argument("score"); ap.add_argument("out"); ap.add_argument("--block", default="primary")
a = ap.parse_args()
sc = json.load(open(a.score)); T = sc["truth"]; lead = {M: sc["methods"][M]["prereg"]["lead"] for M in ("M1", "M6", "M9", "M10")}
runs, calib = S.load_runs(a.rundir, a.block); rows = []
for rid, m in runs:
    t = T.get(rid)
    if not t or not t["breach"] or rid in calib or m["fault"] == "none": continue
    f = S.features(a.rundir, m, 30, 10); bad, tot = f["burn_bad"], f["burn_tot"]
    def frac(e, span):
        sl = range(max(0, e - span // 10), e); n = sum(tot.get(i, 0) for i in sl)
        return sum(bad.get(i, 0) for i in sl) / n if n else 0.0
    E = S.END // 10; on = t["onset_bin"] * 30
    f60 = {e: frac(e, 60) for e in range(1, E + 1)}; f300 = {e: frac(e, 300) for e in range(1, E + 1)}
    first = lambda c: next((e * 10 for e in range(S.F0 // 10, E + 1) if c(e)), None)
    t_short = first(lambda e: f60[e] > S.BURN_SHORT * S.BUDGET); t_long = first(lambda e: f300[e] > S.BURN_LONG * S.BUDGET)
    t_both = first(lambda e: f60[e] > S.BURN_SHORT * S.BUDGET and f300[e] > S.BURN_LONG * S.BUDGET)
    eo = min(E, on // 10 + 3)   # slice index at the end of the onset bin
    rows.append(dict(rid=rid, app=m["app"], fault=m["fault"], target=m["target"], type=t["type"], onset_s=on,
                     lat_trigger=t.get("lat_trigger"), slo_ms=t["lat_slo_ms"],
                     bad60_at_onset=f60[eo], peak_bad60=max(f60.values()), peak_bad300=max(f300.values()),
                     t_short=t_short, t_long=t_long, t_burn=t_both,
                     burn_lag_s=(t_both - on - 30) if t_both is not None else None,   # alert evaluated at window close
                     **{f"lead_{M}": lead[M].get(f"{rid}|any") for M in lead}))
df = pd.DataFrame(rows)

def cls(r):
    if r.type == "freshness": return "freshness-only breach (invisible to frontend latency)"
    if r.peak_bad60 <= S.BURN_SHORT * S.BUDGET: return "bad fraction never reaches 14.4%"
    if r.peak_bad300 <= S.BURN_LONG * S.BUDGET: return "short window met, 5-min window never reaches 6%"
    if r.t_burn is None: return "conditions never hold together"
    return "fires (possibly late)"
df["why"] = df.apply(cls, axis=1); df.to_csv(a.out, index=False)
print("breaches", len(df)); print(df.groupby(["why"]).size().to_string())
print("\nbad fraction (60 s, frontend) at breach onset: median %.3f, IQR %.3f-%.3f, share below 14.4%%: %.2f" % (
    df.bad60_at_onset.median(), df.bad60_at_onset.quantile(.25), df.bad60_at_onset.quantile(.75), (df.bad60_at_onset <= .144).mean()))
fi = df[df.t_burn.notna()]
print("burn fires in %d; lag after onset: median %.0f s, min %.0f, max %.0f; fires before onset: %d" % (
    len(fi), fi.burn_lag_s.median(), fi.burn_lag_s.min(), fi.burn_lag_s.max(), (fi.burn_lag_s < 0).sum()))
print("binding condition (later of the two):", ((fi.t_long > fi.t_short).map({True: "5-min window", False: "60-s window"})).value_counts().to_dict())
print("\nby app/why:\n", df.groupby(["app", "why"]).size().to_string())
