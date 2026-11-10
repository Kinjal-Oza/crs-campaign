"""Reduce RCAEval RE2 cases to compact per-case inputs (no outcomes computed here).
Per case writes OUT/<sys>__<target>_<fault>__<rep>/: meta.json, entry.csv.gz (t, lat_ms, err), svc.csv.gz (svc, sec, n, sum_ms),
edges.json (pre-injection caller->callee service counts).
Usage: python3 -I prep_ext.py SYSTEM SRC OUT   (SRC = extracted dir for OB/SS, or the .zip for TT)"""
import sys, os, io, re, json, zipfile, collections, pandas as pd, numpy as np

SYS, SRC, OUT = sys.argv[1], sys.argv[2], sys.argv[3]
SKIP = re.compile(r"health|TraceService/Export|metrics", re.I)
COLS = ["traceID", "spanID", "serviceName", "operationName", "startTime", "duration", "statusCode", "parentSpanID"]

def opener():
    if SRC.endswith(".zip"):
        z = zipfile.ZipFile(SRC); names = z.namelist()
        cases = sorted({n.rsplit("/", 1)[0] for n in names if n.endswith("inject_time.txt")})
        return cases, (lambda c, f: z.open(f"{c}/{f}")), (lambda c, f: f"{c}/{f}" in set(names))
    cases = sorted(os.path.relpath(r, os.path.dirname(SRC.rstrip("/"))) for r, d, fs in os.walk(SRC) if "inject_time.txt" in fs)
    base = os.path.dirname(SRC.rstrip("/"))
    return cases, (lambda c, f: open(os.path.join(base, c, f), "rb")), (lambda c, f: os.path.exists(os.path.join(base, c, f)))

def bad_status(s):
    if pd.isna(s): return False
    try: v = float(s)
    except ValueError: return False
    return (v >= 500) if v >= 100 else (v != 0)

cases, op, has = opener(); FE_OB = ("frontendservice", "frontend")
for c in cases:
    parts = c.split("/"); tf, rep = parts[-2], parts[-1]
    if not rep.isdigit(): print("skip non-case dir", c, flush=True); continue
    target, fault = tf.rsplit("_", 1)
    cid = f"{SYS}__{target}_{fault}__{rep}"; od = os.path.join(OUT, cid)
    if os.path.exists(os.path.join(od, "meta.json")): continue
    os.makedirs(od, exist_ok=True)
    inj = int(op(c, "inject_time.txt").read().decode().strip()); t0 = inj - 720
    tm = pd.read_csv(op(c, "metrics.csv"), usecols=["time"]).time; end = int(tm.max()) - t0
    meta = dict(case=cid, system=SYS, target=target, fault=fault, rep=int(rep), inject=inj, t0=t0, inj_s=720, end_s=end)
    if SYS == "SS":
        rows = []
        for ch in pd.read_csv(op(c, "logs.csv"), usecols=["timestamp", "container_name", "message"], chunksize=500000):
            ch = ch[ch.container_name == "front-end"]
            m = ch.message.astype(str).str.extract(r"^(GET|POST|PUT|DELETE|PATCH) (\S+) (\d{3}) ([\d.]+) ms")
            ok = m[0].notna(); x = pd.DataFrame(dict(t=ch.timestamp[ok] / 1e9 - t0, lat_ms=m[3][ok].astype(float), err=m[2][ok].astype(int) >= 500))
            rows.append(x)
        ent = pd.concat(rows) if rows else pd.DataFrame(columns=["t", "lat_ms", "err"])
        mt = pd.read_csv(op(c, "metrics.csv")); mt["sec"] = (mt.time - t0).astype(int); sv = []
        for col in mt.columns:
            if col.endswith("_istio-latency-50"):
                s = col[: -len("_istio-latency-50")]; rc = f"{s}_istio-request-total"
                n = mt[rc].diff().clip(lower=0).fillna(0) if rc in mt else pd.Series(np.nan, index=mt.index)
                sv.append(pd.DataFrame(dict(svc=s, sec=mt.sec, n=n, sum_ms=mt[col] * n.where(n > 0, 1), lat_ms=mt[col])))
        svc = pd.concat(sv) if sv else pd.DataFrame(columns=["svc", "sec", "n", "sum_ms", "lat_ms"])
        meta["svc_source"] = "istio metrics (latency-50, request-total)"; edges = {}
    else:
        span_svc, ent_l, agg, edges = {}, [], collections.Counter(), collections.defaultdict(collections.Counter)
        sums = collections.defaultdict(float); pend = []
        for ch in pd.read_csv(op(c, "traces.csv"), usecols=COLS, chunksize=1000000, dtype={"statusCode": str}):
            ch = ch[~ch.operationName.astype(str).str.contains(SKIP)]
            span_svc.update(zip(ch.spanID, ch.serviceName)); pend.append(ch[["spanID", "serviceName", "operationName", "startTime", "duration", "statusCode", "parentSpanID"]])
        tr = pd.concat(pend); tr["t"] = tr.startTime / 1e6 - t0; tr["ms"] = tr.duration / 1000.0
        tr["psvc"] = tr.parentSpanID.map(span_svc)
        root = tr.parentSpanID.isna()
        e = (tr[root & (tr.serviceName == FE_OB[0]) & (tr.operationName == FE_OB[1])] if SYS == "OB" else tr[root])
        ent = pd.DataFrame(dict(t=e.t, lat_ms=e.ms, err=e.statusCode.map(bad_status)))
        es = tr[root | (tr.psvc.notna() & (tr.psvc != tr.serviceName))].copy(); es["sec"] = es.t.astype(int)
        g = es.groupby(["serviceName", "sec"]).ms.agg(["size", "sum"]).reset_index()
        svc = g.rename(columns={"serviceName": "svc", "size": "n", "sum": "sum_ms"})
        pre = es[(es.t < 720) & es.psvc.notna()]
        for (a, b), n in pre.groupby(["psvc", "serviceName"]).size().items(): edges[a][b] += int(n)
        meta["svc_source"] = "trace entry spans"; meta["orphan_parent_share"] = float((tr.parentSpanID.notna() & tr.psvc.isna()).mean())
        del tr, es, pend
    meta.update(n_entry=int(len(ent)), n_entry_pre=int((ent.t < 720).sum()))
    ent.to_csv(os.path.join(od, "entry.csv.gz"), index=False); svc.to_csv(os.path.join(od, "svc.csv.gz"), index=False)
    json.dump({a: dict(b) for a, b in edges.items()}, open(os.path.join(od, "edges.json"), "w"))
    json.dump(meta, open(os.path.join(od, "meta.json"), "w")); print(cid, meta["n_entry"], meta["end_s"], flush=True)
