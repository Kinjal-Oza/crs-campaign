"""Study 3 data-quality checks (no outcome variables): injection return codes, achieved pre-fault rate,
pre-fault errors, probe coverage, image digests and kernels. Usage: python3 qc3.py RUNDIR"""
import sys, os, json, glob, collections, re, pandas as pd
D = sys.argv[1]; rows = []; imgs = collections.defaultdict(set); kern = collections.Counter()
for f in sorted(glob.glob(f"{D}/*_q*.json")):
    m = json.load(open(f)); rid = m["run"]; ev = [str(e[0]) for e in m.get("events", []) if isinstance(e, list)]
    rc_bad = sum(1 for e in ev if re.search(r"rc=(-?\d+)", e) and re.search(r"rc=(-?\d+)", e).group(1) != "0")
    rc_n = sum(1 for e in ev if "rc=" in e)
    r = pd.read_csv(f"{D}/{rid}.req.csv"); s = r.t - m["t0"]; pre = r[(s >= 30) & (s < 240)]
    fr = f"{D}/{rid}.fresh.csv"; npb = len(pd.read_csv(fr)) if os.path.exists(fr) else None
    for line in m.get("images", []): imgs[(m["app"], line.split()[0])].add(line.split()[1] if len(line.split()) > 1 else "")
    kern[m.get("kernel")] += 1
    rows.append(dict(rid=rid, app=m["app"], fault=m["fault"], q=m.get("rate"), rc_steps=rc_n, rc_bad=rc_bad,
                     rate=len(pre) / 210, pre_err=float((pre.status != 200).mean()), probes=npb))
df = pd.DataFrame(rows)
print("runs", len(df)); print(df.groupby("app").size().to_dict())
print("injection steps", int(df.rc_steps.sum()), "non-zero rc", int(df.rc_bad.sum()), df[df.rc_bad > 0].rid.tolist()[:10])
print("achieved rate / target:", df.assign(ratio=df.rate / df.q).groupby(["app", "q"]).ratio.agg(["min", "median", "max"]).round(3).to_string())
print("pre-fault error rate max by app:", df.groupby("app").pre_err.max().round(4).to_dict(), "runs >1%:", int((df.pre_err > 0.01).sum()))
print("probes per run (social/async):", df[df.probes.notna()].groupby("app").probes.agg(["min", "median"]).to_dict())
print("kernels:", dict(kern))
print("images with >1 digest:", {k: len(v) for k, v in imgs.items() if len(v) > 1})
df.to_csv(os.path.join(os.path.dirname(__file__), "qc3_runs.csv"), index=False)
