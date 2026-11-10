"""Study 3 scorer (plan: STUDY3_PLAN.md, deposited on OSF before any scored run).
Usage: python3 score3.py RUNDIR OUT.json [--window 30] [--sampling 10|1] [--block primary|load]
RUNDIR holds plan3_<app>.json and per-run files <rid>.json/.req.csv/.cg.csv.gz/.res.csv/.fresh.csv for apps social, hotel, async.
Detector code paths for M1-M8 are the Study 2 scorer's (score2.py), generalised to a window length and a run timeline.
"""
import sys, os, json, math, collections, hashlib, argparse
import numpy as np, pandas as pd
H = os.path.dirname(os.path.abspath(__file__))
for p in (f"{H}/method_src", os.path.join(H, "..", "..", "src")): sys.path.insert(0, p)
import graph_features as GF, temporal_features_fast as TF, cascade_score as CS

F0, F1, END = 240, 540, 660
FRONT = {"social": "nginx-web-server", "async": "nginx-web-server", "hotel": "frontend"}
SLO_FLOOR_MS, FRESH_FLOOR_S, MULT = 100.0, 2.0, 5
BUDGET, BURN_SHORT, BURN_LONG = 0.01, 14.4, 6.0
H8_BUDGET = 1.0   # alert incidents per control hour
POOLED = os.environ.get("POOLED") == "1"   # pooled thresholds over apps, as in Study 2 (used only to reproduce Study 2)
QS = [0.90, 0.95, 0.98, 0.99, 0.995, 0.999, 1.0]
SCORED = ["M1", "M1int", "M2", "M5", "M6", "M7", "M8", "M9c", "M10"]   # thresholded by calibration maximum
BINARY = ["M9"]                                                          # fixed rule

# ------------------------------------------------------------------ ground truth (always 30-s bins)
def _bins(t, t0, bs=30): return ((t - t0) // bs).astype(int)
def truth(D, m):
    """Latency SLO (as Studies 1-2) and, for the social apps, freshness SLO. Returns onsets per SLO and overall."""
    r = pd.read_csv(f"{D}/{m['run']}.req.csv"); nb = END // 30
    r["b"] = _bins(r.t, m["t0"]); r = r[(r.b >= 0) & (r.b < nb)]
    g = r.groupby("b").agg(p95=("lat_ms", lambda x: x.quantile(.95)), err=("status", lambda s: (s != 200).mean()))
    base = g.p95.loc[0:6].median(); thr = max(MULT * base, SLO_FLOOR_MS)
    lb = (g.p95 > thr) | (g.err > 0.05)
    win = [int(b) for b in g.index if lb[b] and F0 // 30 <= b <= (F1 + 60) // 30 - 1]
    out = dict(lat_slo_ms=thr, lat_base_ms=float(base), lat_onset_bin=(min(win) if win else None),
               lat_trigger=None, fresh_onset_bin=None, fresh_slo_s=None)
    if win:
        b = min(win); out["lat_trigger"] = "both" if (g.p95[b] > thr and g.err[b] > 0.05) else ("latency" if g.p95[b] > thr else "error")
    fp = f"{D}/{m['run']}.fresh.csv"
    if os.path.exists(fp):
        q = pd.read_csv(fp)
        if len(q):
            q["b"] = _bins(q.t, m["t0"]); q = q[(q.b >= 0) & (q.b < nb)]
            fg = q.groupby("b").agg(p95=("fresh_s", lambda x: x.quantile(.95)), miss=("seen", lambda s: (s == 0).any()))
            fbase = fg.p95.loc[0:6].median(); fthr = max(MULT * fbase, FRESH_FLOOR_S)
            fb = (fg.p95 > fthr) | fg.miss
            fw = [int(b) for b in fg.index if fb[b] and F0 // 30 <= b <= (F1 + 60) // 30 - 1]
            out.update(fresh_slo_s=float(fthr), fresh_base_s=float(fbase), fresh_onset_bin=(min(fw) if fw else None))
    ons = [x for x in (out["lat_onset_bin"], out["fresh_onset_bin"]) if x is not None]
    out["onset_bin"] = min(ons) if ons else None; out["breach"] = bool(ons)
    if ons:
        L, Fr = out["lat_onset_bin"], out["fresh_onset_bin"]
        out["type"] = "both" if L == Fr else ("latency" if (Fr is None or (L is not None and L < Fr)) else "freshness")
    else: out["type"] = None
    out["freshness_led"] = out["type"] in ("freshness", "both")
    return out

# ------------------------------------------------------------------ features
def keep_trace(tid): return int(str(tid)[:15], 16) % 10 == 0
def features(D, m, W, sampling=10):
    NW = int(math.ceil(END / W)); app = m["app"]
    c = pd.read_csv(f"{D}/{m['run']}.cg.csv.gz")
    if sampling == 1: c = c[c.traceid.map(keep_trace)]
    t0 = m["t0"]; c["s"] = c.timestamp / 1000 - t0; c["b"] = (c.s // W).astype(int); c = c[(c.b >= 0) & (c.b < NW)]
    pre = c[(c.s < F0) & (c.um != "USER")]
    graph = collections.defaultdict(collections.Counter)
    for (um, dm), n in pre.groupby(["um", "dm"]).size().items(): graph[um][dm] += int(n)
    blast = GF.blast_radius(graph)
    agg = c.groupby(["dm", "b"]).agg(rt=("rt", "mean"), n=("rt", "size")).reset_index()
    series = {s: [(int(r.b), float(r.rt), float(r.n)) for r in g.itertuples()] for s, g in agg.groupby("dm")}
    lz = {s: TF.latency_deviation_score(v) for s, v in series.items()}
    cz = {s: TF.call_rate_anomaly_score(v) for s, v in series.items()}
    sz = {}
    for s, v in series.items():
        d = {}
        for i in range(len(v)):
            hist = [x[1] for x in v[max(0, i - 10):i]]
            if len(hist) >= 3:
                lh = [math.log1p(max(h, 0)) for h in hist]; d[v[i][0]] = (math.log1p(max(v[i][1], 0)) - np.mean(lh)) / (np.std(lh) + 0.5)
        sz[s] = d
    tz = {}; rp = f"{D}/{m['run']}.res.csv"
    if os.path.exists(rp):
        r = pd.read_csv(rp); r["b"] = ((r.t - t0) // W).astype(int); r = r[(r.b >= 0) & (r.b < NW)]
        for svc, g in r.groupby("service"):
            per = g.sort_values("t").groupby("b").throttled_usec.agg(["min", "max"])
            tz[svc] = TF.latency_deviation_score([(int(b), float(x["max"] - x["min"]), 0.0) for b, x in per.iterrows()])
    # burn rate inputs: frontend entry calls in 10-s slices
    fe = c[(c.um == "USER") & (c.dm == FRONT[app])]
    sl = (fe.s // 10).astype(int); bad = (fe.rt > SLO_FLOOR_MS).groupby(sl).sum(); tot = fe.groupby(sl).size()
    return dict(app=app, W=W, NW=NW, blast=blast, series=series, lz=lz, cz=cz, sz=sz, tz=tz,
                burn_bad=bad.to_dict(), burn_tot=tot.to_dict())

RES = {"nginx-web-server": "nginx-thrift", "home-timeline-service-redis": "home-timeline-redis", "user-timeline-service-mongo": "user-timeline-mongodb",
       "user-timeline-service-redis": "user-timeline-redis", "post-storage-service-mongo": "post-storage-mongodb",
       "post-storage-service-memcached": "post-storage-memcached", "social-graph-service-mongo": "social-graph-mongodb",
       "social-graph-service-redis": "social-graph-redis", "url-shorten-service-mongo": "url-shorten-mongodb",
       "url-shorten-service-memcached": "url-shorten-memcached", "user-mention-service-memcached": "user-memcached"}   # as score2.py
def _res_name(s): return RES.get(s, s)

def iforest_vectors(f):
    rows, keys = [], []
    for s, v in f["series"].items():
        prev = None
        for (b, rt, n) in v:
            x = [math.log1p(max(rt, 0)), math.log1p(n)]
            d = [0.0, 0.0] if prev is None else [x[0] - prev[0], x[1] - prev[1]]
            rows.append(x + d); keys.append((s, b)); prev = x
    return np.array(rows), keys

def window_scores(f, M, model=None):
    out = {}; NW, W = f["NW"], f["W"]; fr = FRONT[f["app"]]
    if M in ("M9", "M9c"):
        for b in range(NW):
            e = (b + 1) * W // 10   # slice index after the window closes
            def burn(span):
                sl = range(max(0, e - span // 10), e); t = sum(f["burn_tot"].get(i, 0) for i in sl)
                return (sum(f["burn_bad"].get(i, 0) for i in sl) / t / BUDGET) if t else 0.0
            s60, s300 = burn(60), burn(300)
            out[b] = (1.0 if (s60 > BURN_SHORT and s300 > BURN_LONG) else 0.0) if M == "M9" else s60
        return out
    if M == "M10":
        X, keys = iforest_vectors(f)
        if len(X):
            sc = -model.score_samples(X); best = {}
            for (s, b), v in zip(keys, sc): best[b] = max(best.get(b, -1e9), float(v))
            out = best
        return out
    if M == "M7":
        for b in range(NW):
            vals = [d[b] for d in f["tz"].values() if b in d]
            if vals: out[b] = max(vals)
        return out
    for b in range(NW):
        vals = []
        for s in f["series"]:
            if M == "M1int" and s == fr: continue
            l = f["lz"][s].get(b); c = f["cz"][s].get(b)
            if M in ("M1", "M1int") and l is not None and c is not None: vals.append(CS.naive_combined_score(f["blast"].get(s, 0.0), l, c))
            elif M == "M2" and l is not None: vals.append(l)
            elif M == "M5" and f["sz"][s].get(b) is not None: vals.append(f["sz"][s][b])
            elif M == "M6" and s == fr and l is not None: vals.append(l)
            elif M == "M8" and l is not None and c is not None:
                zt = f["tz"].get(_res_name(s), {}).get(b, 0.0)
                vals.append(1 / (1 + math.exp(-(math.log1p(max(f["blast"].get(s, 0.0), 0)) * 0.1 + max(l, 0) + max(c, 0) + max(zt, 0)) + 5)))
        if vals: out[b] = max(vals)
    return out

# ------------------------------------------------------------------ evaluation
def load_runs(D, block):
    runs, calib = [], set()
    for app in ("social", "hotel", "async"):
        p = f"{D}/plan3_{app}.json"
        if not os.path.exists(p): continue
        plan = json.load(open(p)); seen = collections.Counter()
        for i, (f, t, r, q) in enumerate(plan):
            blk = "primary" if (i < len(plan) and q == 100 and not _is_load(plan, i)) else "load"
            if blk != block: continue
            rid = f"{app}_r{i:03d}_{f}_{t}_{r}_q{q}"
            if not os.path.exists(f"{D}/{rid}.json"): continue
            m = json.load(open(f"{D}/{rid}.json")); m.setdefault("app", app); m["block"] = blk; m["q"] = q; runs.append((rid, m))
            if f == "none":
                seen[(app, q)] += 1
                if seen[(app, q)] <= (4 if blk == "primary" else 2): calib.add(rid)
    return runs, calib

def _is_load(plan, i):   # the primary block is the first 132 entries (STUDY3_PLAN.md section 3)
    return i >= 132

def control_seconds(m): return END if m["fault"] == "none" else F0

def evaluate(D, runs, calib, W, sampling, quantiles=None):
    lo = int(math.ceil(90 / W)); T = {rid: truth(D, m) for rid, m in runs}
    Fe = {rid: features(D, m, W, sampling) for rid, m in runs}
    from sklearn.ensemble import IsolationForest
    models = {}
    for app in {m["app"] for _, m in runs}:
        X = np.vstack([iforest_vectors(Fe[r])[0] for r, m in runs if r in calib and m["app"] == app and len(Fe[r]["series"])])
        models[app] = IsolationForest(n_estimators=200, max_samples=256, random_state=0).fit(X)
    S = {M: {rid: window_scores(Fe[rid], M, models.get(m["app"])) for rid, m in runs} for M in SCORED + BINARY}
    res = {}
    for M in SCORED + BINARY:
        taus = {}
        for app in {m["app"] for _, m in runs}:
            same = (lambda mm: True) if POOLED else (lambda mm, app=app: mm["app"] == app)   # Study 3: per-app thresholds
            cal = [v for r, m in runs if r in calib and same(m) for b, v in S[M][r].items() if b >= lo]
            if M in BINARY: taus[app] = {"prereg": 0.5}
            elif quantiles is None: taus[app] = {"prereg": max(cal) if cal else float("inf")}
            else: taus[app] = {str(q): float(np.quantile(cal, q)) for q in quantiles}
        keys = next(iter(taus.values())).keys(); res[M] = {}
        for k in keys:
            lead, per = {}, collections.defaultdict(lambda: dict(fa_w=0, fa_inc=0, hours=0.0, loc=0, nloc=0))
            for rid, m in runs:
                if rid in calib: continue
                tau = taus[m["app"]][k]; al = sorted(b * W for b, v in S[M][rid].items() if v > tau and b >= lo)
                ce = control_seconds(m); ca = [a for a in al if a < ce]; P = per[m["app"]]
                P["fa_w"] += len(ca); P["fa_inc"] += sum(1 for i, a in enumerate(ca) if i == 0 or a - ca[i - 1] > W); P["hours"] += ce / 3600
                if m["fault"] == "none": continue
                t = T[rid]; fw = [a for a in al if a >= F0]
                if t["breach"]:
                    for key, ob in (("any", t["onset_bin"]), ("lat", t["lat_onset_bin"]), ("fresh", t["fresh_onset_bin"])):
                        if ob is None: continue
                        hit = [a for a in fw if a <= ob * 30 + 60]; lead[(rid, key)] = (ob * 30 - hit[0]) if hit else None
                else:
                    P["nloc"] += 1; P["loc"] += int(any(a < F1 + 60 for a in fw))
            res[M][k] = dict(tau={a: taus[a][k] for a in taus}, lead={f"{r}|{key}": v for (r, key), v in lead.items()},
                             per_app={a: dict(fa_windows_h=p["fa_w"] / p["hours"], fa_incidents_h=p["fa_inc"] / p["hours"], control_h=p["hours"],
                                              local_alert_share=p["loc"] / max(p["nloc"], 1)) for a, p in per.items()})
    return T, res

def cluster(rid, runs_d): m = runs_d[rid]; return f"{m['app']}|{m['target']}"
def paired(res, a, b, rids, key, runs_d, level, B=10000, seed=3):
    la, lb = res[a]["prereg"]["lead"], res[b]["prereg"]["lead"]
    ok = [r for r in rids if la.get(f"{r}|{key}") is not None and lb.get(f"{r}|{key}") is not None]
    d = np.array([la[f"{r}|{key}"] - lb[f"{r}|{key}"] for r in ok], float)
    if len(d) == 0: return dict(n=0)
    G = collections.defaultdict(list)
    for r, x in zip(ok, d): G[cluster(r, runs_d)].append(x)
    ks = list(G); rng = np.random.default_rng(seed); means = []
    for _ in range(B): means.append(np.concatenate([G[k] for k in rng.choice(ks, len(ks))]).mean())
    al = (1 - level) / 2
    from scipy.stats import wilcoxon, binomtest
    nz = d[d != 0]
    w = dict(wilcox_p=float(wilcoxon(d, zero_method="wilcox", alternative="greater").pvalue) if len(nz) else 1.0,
             pratt_p=float(wilcoxon(d, zero_method="pratt", alternative="greater").pvalue) if len(nz) else 1.0,
             sign_p=float(binomtest(int((nz > 0).sum()), len(nz), 0.5, alternative="greater").pvalue) if len(nz) else 1.0)
    return dict(n=len(d), clusters=len(ks), excluded=len(rids) - len(ok), ties=int((d == 0).sum()), a_earlier=int((d > 0).sum()),
                b_earlier=int((d < 0).sum()), mean=float(d.mean()), ci=[float(np.quantile(means, al)), float(np.quantile(means, 1 - al))],
                level=level, **w, diffs=sorted(d.tolist()))

def hypotheses(T, res, runs, calib):
    runs_d = dict(runs); ev = [r for r, m in runs if r not in calib and m["fault"] != "none"]
    sync_lat = [r for r in ev if runs_d[r]["app"] in ("social", "hotel") and T[r]["lat_onset_bin"] is not None]
    fresh_led = [r for r in ev if runs_d[r]["app"] == "async" and T[r]["freshness_led"]]
    allb = [r for r in ev if T[r]["breach"]]
    out = {}
    p = paired(res, "M1", "M6", sync_lat, "lat", runs_d, 0.90); out["H4"] = dict(test=p, holds=bool(p.get("n") and -15 <= p["ci"][0] and p["ci"][1] <= 15))
    p = paired(res, "M1", "M6", fresh_led, "any", runs_d, 0.95); out["H5"] = dict(test=p, holds=bool(p.get("n") and p["mean"] > 0 and p["ci"][0] > 0 and p["wilcox_p"] < 0.05),
                                                                                  testable=bool(fresh_led))
    p = paired(res, "M6", "M9", allb, "any", runs_d, 0.95); out["H6"] = dict(test=p, holds=bool(p.get("n") and p["mean"] > 0 and p["ci"][0] > 0))
    p = paired(res, "M10", "M6", sync_lat, "lat", runs_d, 0.90); out["H7"] = dict(test=p, holds=bool(p.get("n") and -15 <= p["ci"][0] and p["ci"][1] <= 15))
    out["populations"] = dict(sync_latency_breaches=len(sync_lat), async_freshness_led=len(fresh_led), all_breaches=len(allb))
    return out

def h8(D, runs, calib, W, sampling):
    T, RB = evaluate(D, runs, calib, W, sampling, quantiles=QS); runs_d = dict(runs); out = {}
    for app in sorted({m["app"] for _, m in runs}):
        ev = [r for r, m in runs if r not in calib and m["app"] == app and m["fault"] != "none" and T[r]["breach"]]; out[app] = {}
        for M in ("M1", "M6"):
            pts = []
            for q in map(str, QS):
                L = RB[M][q]["lead"]; e = sum(1 for r in ev if (L.get(f"{r}|any") or 0) > 0)
                pts.append(dict(q=q, early=e, fa_incidents_h=RB[M][q]["per_app"][app]["fa_incidents_h"]))
            within = [p for p in pts if p["fa_incidents_h"] <= H8_BUDGET]
            out[app][M] = dict(curve=pts, at_budget=(max(within, key=lambda p: p["early"]) if within else None))
        a, b = out[app]["M1"]["at_budget"], out[app]["M6"]["at_budget"]
        out[app]["holds"] = bool(a and b and a["early"] >= b["early"])
    return out

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("rundir"); ap.add_argument("out")
    ap.add_argument("--window", type=int, default=30); ap.add_argument("--sampling", type=int, default=10); ap.add_argument("--block", default="primary")
    a = ap.parse_args()
    runs, calib = load_runs(a.rundir, a.block)
    print("runs", len(runs), "calibration", len(calib))
    T, res = evaluate(a.rundir, runs, calib, a.window, a.sampling)
    out = dict(config=vars(a), n_runs=len(runs), calibration=sorted(calib), truth=T,
               methods={M: {k: {kk: vv for kk, vv in v.items()} for k, v in res[M].items()} for M in res})
    if a.block == "primary":
        out["hypotheses"] = hypotheses(T, res, runs, calib); out["H8"] = h8(a.rundir, runs, calib, a.window, a.sampling)
    json.dump(out, open(a.out, "w"), indent=1, default=lambda o: o.item() if isinstance(o, np.generic) else str(o))
    for k in ("H4", "H5", "H6", "H7"):
        if "hypotheses" in out: t = out["hypotheses"][k]["test"]; print(k, out["hypotheses"][k]["holds"], {x: t.get(x) for x in ("n", "ties", "a_earlier", "b_earlier", "mean", "ci")})
