"""Study 3 addendum: external validation on RCAEval RE2 (pre-specified in STUDY3_ADDENDUM_External_Validation.md).
Reuses score3.py (hash 0b6319aef5a575ba) detectors, thresholds, lead rule and bootstrap unchanged.
Usage: python3 -I ext3.py PREPDIR OUT.json"""
import sys, os, json, math, glob, collections, numpy as np, pandas as pd
sys.path.insert(0, "/home/claude/score"); sys.path.insert(0, "/home/claude/score/method_src")
import score3 as S, graph_features as GF, temporal_features_fast as TF
from scipy.stats import binomtest

PREP, OUT = sys.argv[1], sys.argv[2]
W, INJ, HORIZON = 30, 720, 600
LO = int(math.ceil(90 / W)); INJB = INJ // W; LASTB = (INJ + HORIZON) // W - 1
ENTRY = "__entry__"
for sysname in ("OB", "SS", "TT"): S.FRONT[sysname] = ENTRY
# Sock Shop topology (microservices-demo docs); edge weight = callee's pre-injection request count / number of its callers
SS_EDGES = {"front-end": ["catalogue", "carts", "orders", "user"], "orders": ["carts", "user", "payment", "shipping"]}
METHODS = ["M1", "M2", "M6", "M9c", "M10"]; BIN = ["M9"]

def load(cd):
    m = json.load(open(f"{cd}/meta.json")); e = pd.read_csv(f"{cd}/entry.csv.gz"); s = pd.read_csv(f"{cd}/svc.csv.gz")
    return m, e, s

def truth(m, e):
    nb = m["end_s"] // W; e = e.assign(b=(e.t // W).astype(int)); e = e[(e.b >= 0) & (e.b < nb)]
    g = e.groupby("b").agg(p95=("lat_ms", lambda x: x.quantile(.95)), err=("err", "mean"))
    base = g.p95.loc[0:INJB - 1].median(); thr = max(S.MULT * base, S.SLO_FLOOR_MS)
    lb = (g.p95 > thr) | (g.err > 0.05)
    win = [int(b) for b in g.index if lb[b] and INJB <= b <= LASTB]
    on = min(win) if win else None
    trig = None
    if on is not None: trig = "both" if (g.p95[on] > thr and g.err[on] > .05) else ("latency" if g.p95[on] > thr else "error")
    return dict(base_ms=float(base), slo_ms=float(thr), onset_bin=on, lat_onset_bin=(on if trig in ("latency", "both") else None),
                breach=on is not None, trigger=trig)

def features(m, e, s, thr):
    NW = int(math.ceil(m["end_s"] / W)); series = {}
    if m["system"] == "SS":
        s = s.assign(b=(s.sec // W).astype(int)); s = s[(s.b >= 0) & (s.b < NW)]
        a = s.groupby(["svc", "b"]).agg(rt=("lat_ms", "mean"), n=("n", "sum")).reset_index()
        pre = s[s.sec < INJ].groupby("svc").n.sum()
        graph = collections.defaultdict(collections.Counter); callers = collections.Counter(b for v in SS_EDGES.values() for b in v)
        for u, ds in SS_EDGES.items():
            for d in ds: graph[u][d] += max(int(pre.get(d, 0) / callers[d]), 1)
    else:
        s = s.assign(b=(s.sec // W).astype(int)); s = s[(s.b >= 0) & (s.b < NW)]
        a = s.groupby(["svc", "b"]).agg(sm=("sum_ms", "sum"), n=("n", "sum")).reset_index(); a["rt"] = a.sm / a.n
        graph = collections.defaultdict(collections.Counter)
        for u, ds in json.load(open(f"{PREP}/{m['case']}/edges.json")).items():
            for d, n in ds.items(): graph[u][d] += n
    for svc, g in a.groupby("svc"): series[svc] = [(int(r.b), float(r.rt), float(r.n)) for r in g.itertuples() if r.n > 0 or m["system"] == "SS"]
    ee = e.assign(b=(e.t // W).astype(int)); ee = ee[(ee.b >= 0) & (ee.b < NW)]
    series[ENTRY] = [(int(b), float(g.lat_ms.mean()), float(len(g))) for b, g in ee.groupby("b")]
    blast = GF.blast_radius(graph)
    lz = {k: TF.latency_deviation_score(v) for k, v in series.items()}; cz = {k: TF.call_rate_anomaly_score(v) for k, v in series.items()}
    sz = {}
    for k, v in series.items():
        d = {}
        for i in range(len(v)):
            hist = [x[1] for x in v[max(0, i - 10):i]]
            if len(hist) >= 3:
                lh = [math.log1p(max(h, 0)) for h in hist]; d[v[i][0]] = (math.log1p(max(v[i][1], 0)) - np.mean(lh)) / (np.std(lh) + 0.5)
        sz[k] = d
    sl = (e.t // 10).astype(int); bad = ((e.lat_ms > thr) | e.err.astype(bool)).groupby(sl).sum(); tot = e.groupby(sl).size()
    return dict(app=m["system"], W=W, NW=NW, blast=blast, series=series, lz=lz, cz=cz, sz=sz, tz={},
                burn_bad=bad.to_dict(), burn_tot=tot.to_dict())

def pre_only(f):
    g = dict(f); g["series"] = {k: [x for x in v if x[0] < INJB] for k, v in f["series"].items()}; return g

def score(sc, f, M, model=None):
    # M1 is max over real services; the entry pseudo-series feeds M6 only (pre-specified)
    if M in ("M1", "M2"):
        g = dict(f); g["series"] = {k: v for k, v in f["series"].items() if k != ENTRY}; return S.window_scores(g, M, model)
    return S.window_scores(f, M, model)

def main():
    cases = sorted(glob.glob(f"{PREP}/*__*"))
    runs, T, Fe, excl = [], {}, {}, []
    for cd in cases:
        m, e, s = load(cd)
        why = ("post-injection < 600 s" if m["end_s"] - INJ < HORIZON else "fewer than 600 pre-injection entry requests" if (e.t < INJ).sum() < 600
               else "orphan spans > 50%" if (m.get("orphan_parent_share") or 0) > 0.5 else None)
        if why: excl.append((m["case"], why)); continue
        rid = m["case"]; m = dict(m, app=m["system"], fault=m["fault"]); runs.append((rid, m)); T[rid] = truth(m, e); Fe[rid] = features(m, e, s, T[rid]["slo_ms"])
    calib = {r for r, m in runs if m["rep"] == 1}
    from sklearn.ensemble import IsolationForest
    models = {}
    for sy in sorted({m["system"] for _, m in runs}):
        X = np.vstack([S.iforest_vectors(pre_only(Fe[r]))[0] for r, m in runs if r in calib and m["system"] == sy])
        models[sy] = IsolationForest(n_estimators=200, max_samples=256, random_state=0).fit(X)
    Sc = {M: {r: score(None, Fe[r], M, models[m["system"]]) for r, m in runs} for M in METHODS + BIN}
    res, ops = {}, {}
    for M in METHODS + BIN:
        taus = {}
        for sy in models:
            cal = [v for r, m in runs if r in calib and m["system"] == sy for b, v in Sc[M][r].items() if LO <= b < INJB]
            taus[sy] = 0.5 if M in BIN else (max(cal) if cal else float("inf"))
        res[M] = {}
        for lvl, mult in (("prereg", 1.0), ("x1.25", 1.25)):
            if M in BIN and lvl != "prereg": continue
            lead, delay, per = {}, {}, collections.defaultdict(lambda: dict(fa=0, h=0.0, early=0))
            for r, m in runs:
                if r in calib: continue
                tau = taus[m["system"]] * mult; al = sorted(b * W for b, v in Sc[M][r].items() if v > tau and b >= LO)
                ca = [a for a in al if a < INJ]; P = per[m["system"]]
                P["fa"] += sum(1 for i, a in enumerate(ca) if i == 0 or a - ca[i - 1] > W); P["h"] += INJ / 3600
                fw = [a for a in al if a >= INJ]; dl = [a for a in fw if a < INJ + HORIZON]; delay[r] = (dl[0] - INJ) if dl else None
                t = T[r]
                if t["breach"]:
                    for key, ob in (("any", t["onset_bin"]), ("lat", t["lat_onset_bin"])):
                        if ob is None: continue
                        hit = [a for a in fw if a <= ob * 30 + 60]; lead[(r, key)] = (ob * 30 - hit[0]) if hit else None
                    if lead.get((r, "any")) is not None and lead[(r, "any")] > 0: P["early"] += 1
            res[M][lvl] = dict(tau={k: v * mult for k, v in taus.items()}, lead={f"{r}|{k}": v for (r, k), v in lead.items()}, delay=delay,
                               per_system={k: dict(fa_incidents_h=v["fa"] / v["h"], control_h=v["h"], early=v["early"]) for k, v in per.items()})
    runs_d = {r: dict(m, app=m["system"]) for r, m in runs}
    ev = [r for r, m in runs if r not in calib]; allb = [r for r in ev if T[r]["breach"]]; latb = [r for r in ev if T[r]["lat_onset_bin"] is not None]
    H = {}
    p = S.paired(res, "M6", "M9", allb, "any", runs_d, 0.95); H["E1"] = dict(test=p, holds=bool(p.get("n") and p["mean"] > 0 and p["ci"][0] > 0))
    # E2: burn-rate mechanism
    below, fires_before, nb = 0, 0, 0
    for r in allb:
        f = Fe[r]; on = T[r]["onset_bin"]; e_ = (on + 1) * W // 10; sl = range(max(0, e_ - 6), e_)
        n = sum(f["burn_tot"].get(i, 0) for i in sl); frac = (sum(f["burn_bad"].get(i, 0) for i in sl) / n) if n else 0.0
        below += frac <= S.BURN_SHORT * S.BUDGET; nb += 1
        al = [b * W for b, v in Sc["M9"][r].items() if v > 0.5 and b >= LO and b * W >= INJ]
        fires_before += bool(al and al[0] < on * W)
    bt = binomtest(below, nb, 0.5, alternative="greater") if nb else None
    H["E2"] = dict(n=nb, below_144_at_onset=below, share=below / nb if nb else None, binom_p=(bt.pvalue if bt else None),
                   m9_before_onset=fires_before, m9_before_share=fires_before / nb if nb else None,
                   holds=bool(nb and bt.pvalue < 0.05 and below / nb > 0.5 and fires_before / nb < 0.05))
    p = S.paired(res, "M10", "M6", latb, "lat", runs_d, 0.90); H["E3"] = dict(test=p, holds=bool(p.get("n") and -15 <= p["ci"][0] and p["ci"][1] <= 15))
    p = S.paired(res, "M1", "M6", latb, "lat", runs_d, 0.90); H["E4"] = dict(test=p, holds=bool(p.get("n") and -15 <= p["ci"][0] and p["ci"][1] <= 15))
    e5 = {}
    for sy in models:
        a, b = res["M1"]["x1.25"]["per_system"].get(sy), res["M1"]["prereg"]["per_system"].get(sy)
        e5[sy] = dict(fa_h=a["fa_incidents_h"], early_125=a["early"], early_1=b["early"],
                      ok=bool(a["fa_incidents_h"] <= 1.0 and (b["early"] == 0 or a["early"] >= 0.9 * b["early"])))
    H["E5"] = dict(per_system=e5, holds=all(v["ok"] for v in e5.values()))
    H["populations"] = dict(cases=len(runs), excluded=excl, calibration=len(calib), evaluated=len(ev), breaches=len(allb), latency_breaches=len(latb),
                            by_system={sy: dict(evaluated=sum(1 for r in ev if runs_d[r]["system"] == sy), breaches=sum(1 for r in allb if runs_d[r]["system"] == sy)) for sy in models})
    json.dump(dict(truth=T, methods=res, hypotheses=H), open(OUT, "w"), indent=1, default=lambda o: o.item() if isinstance(o, np.generic) else str(o))
    for k in ("E1", "E2", "E3", "E4", "E5"):
        v = H[k]; t = v.get("test", {}); print(k, v["holds"], {x: t.get(x) for x in ("n", "ties", "a_earlier", "b_earlier", "mean", "ci")} if t else {x: y for x, y in v.items() if x != "holds"})
    print(H["populations"])

if __name__ == "__main__": main()
