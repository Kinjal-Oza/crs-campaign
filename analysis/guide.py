"""Exploratory (not pre-registered): operating curves for practitioner guidance. For each app and detector, sweep the alert
threshold from calibration quantiles up to multiples of the calibration maximum, and report early warnings (lead > 0),
median lead among early warnings, and false-alarm incidents per control hour. Same scoring rules as score3.evaluate.
Usage: python3 guide.py RUNDIR OUT.json"""
import sys, os, json, math, collections, numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import score3 as S

D, OUT = sys.argv[1], sys.argv[2]; W = 30; lo = int(math.ceil(90 / W))
runs, calib = S.load_runs(D, "primary"); runs_d = dict(runs)
T = {r: S.truth(D, m) for r, m in runs}; Fe = {r: S.features(D, m, W, 10) for r, m in runs}
from sklearn.ensemble import IsolationForest
models = {app: IsolationForest(n_estimators=200, max_samples=256, random_state=0).fit(
    np.vstack([S.iforest_vectors(Fe[r])[0] for r, m in runs if r in calib and m["app"] == app and len(Fe[r]["series"])]))
    for app in {m["app"] for _, m in runs}}
METHODS = ["M1", "M1int", "M2", "M5", "M6", "M8", "M9c", "M10"]
LEVELS = [("q0.95", "q", .95), ("q0.99", "q", .99), ("max", "m", 1.0), ("1.25max", "m", 1.25), ("1.5max", "m", 1.5), ("2max", "m", 2.0), ("3max", "m", 3.0)]
out = {}
for M in METHODS + ["M9"]:
    Sc = {r: S.window_scores(Fe[r], M, models.get(m["app"])) for r, m in runs}
    for app in sorted({m["app"] for _, m in runs}):
        cal = [v for r, m in runs if r in calib and m["app"] == app for b, v in Sc[r].items() if b >= lo]
        levels = [("fixed", 0.5)] if M == "M9" else [(n, float(np.quantile(cal, x)) if k == "q" else max(cal) * x) for n, k, x in LEVELS]
        for name, tau in levels:
            early, leads, det, nbr, fa, hrs = 0, [], 0, 0, 0, 0.0
            for r, m in runs:
                if r in calib or m["app"] != app: continue
                al = sorted(b * W for b, v in Sc[r].items() if v > tau and b >= lo); ce = S.control_seconds(m)
                ca = [x for x in al if x < ce]; fa += sum(1 for i, x in enumerate(ca) if i == 0 or x - ca[i - 1] > W); hrs += ce / 3600
                t = T[r]
                if m["fault"] == "none" or not t["breach"]: continue
                nbr += 1; hit = [x for x in al if x >= S.F0 and x <= t["onset_bin"] * 30 + 60]
                if hit:
                    det += 1; L = t["onset_bin"] * 30 - hit[0]
                    if L > 0: early += 1; leads.append(L)
            out.setdefault(app, {}).setdefault(M, []).append(dict(level=name, tau=tau, breaches=nbr, detected=det, early=early,
                med_lead=(float(np.median(leads)) if leads else None), fa_h=fa / hrs, control_h=hrs))
json.dump(out, open(OUT, "w"), indent=1)
for app, d in out.items():
    print(f"\n== {app}")
    for M, pts in d.items():
        print(f"{M:6s}", "  ".join(f"{p['level']}:{p['early']}/{p['breaches']} fa{p['fa_h']:.1f}" for p in pts))
