"""Campaign 2 (gradual faults, two applications). Plan: CAMPAIGN2_PLAN.md.
Usage: APP=social|hotel DSB=<app dir> python3 campaign2.py OUTDIR SHARD NSHARDS
"""
import sys, os, json, random, subprocess, time, urllib.request
import pandas as pd
H = os.path.dirname(os.path.abspath(__file__)); OUT, SHARD, NSH = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]); os.makedirs(OUT, exist_ok=True)
APP = os.environ["APP"]; DSB = os.environ["DSB"]; FRONT = {"social": "nginx-web-server", "hotel": "frontend"}[APP]
TARGETS = {
 "social": ["compose-post-service", "home-timeline-service", "user-timeline-service", "post-storage-service", "social-graph-service",
            "text-service", "user-service", "user-mention-service", "url-shorten-service", "media-service", "unique-id-service",
            "home-timeline-redis", "user-timeline-mongodb", "post-storage-mongodb", "post-storage-memcached", "social-graph-mongodb"],
 "hotel": ["search", "geo", "rate", "profile", "recommendation", "reservation", "user", "review", "attractions",
           "mongodb-geo", "mongodb-rate", "memcached-rate", "mongodb-profile", "memcached-profile"]}[APP]
plan = [(f, t, r) for r in range(2) for f in ("cpu_ramp_slow", "net_ramp") for t in TARGETS] + [("none", "-", r) for r in range(12)]
random.Random(20261029 + (0 if APP == "social" else 1)).shuffle(plan)
if os.environ.get("SMOKE"): plan = [("cpu_ramp_slow", TARGETS[3], 0), ("net_ramp", TARGETS[0], 0)]
json.dump(plan, open(f"{OUT}/plan_{APP}.json", "w"))

def names(): return [n for n in subprocess.run(["docker", "ps", "-a", "--format", "{{.Names}}"], capture_output=True, text=True).stdout.split()]
def reset():   # unpause everything and clear any cgroup CPU limit
    for n in names(): subprocess.run(["docker", "unpause", n], capture_output=True)
    subprocess.run("for f in /sys/fs/cgroup/system.slice/docker-*.scope/cpu.max; do echo 'max 100000' | sudo tee $f >/dev/null; done", shell=True)
def healthy():
    p = f"{OUT}/_probe.csv"; subprocess.run(["python3", f"{H}/loadgen2.py", "50", "10", p], env=dict(os.environ, APP=APP))
    d = pd.read_csv(p); ok = (d.status == 200).mean() > 0.99 and d.lat_ms.quantile(.95) < 60
    try:
        t1 = int(time.time() * 1e6)
        tr = json.load(urllib.request.urlopen(f"http://localhost:16686/api/traces?service={FRONT}&limit=5&start={t1-60_000_000}&end={t1}"))["data"] or []
        ok = ok and len(tr) > 0
    except Exception: ok = False
    return ok, round(float(d.lat_ms.quantile(.95)), 1)

log = open(f"{OUT}/campaign_{APP}_{SHARD}.log", "a")
for i, (f, t, r) in enumerate(plan):
    rid = f"{APP}_r{i:03d}_{f}_{t}_{r}"
    if i % NSH != SHARD or os.path.exists(f"{OUT}/{rid}.json"): continue
    for attempt in range(2):
        reset(); time.sleep(20); ok, p95 = healthy(); k = 0
        while not ok and k < 3:
            log.write(f"{time.time():.0f} unhealthy before {rid} p95={p95}; restarting stack\n"); log.flush()
            subprocess.run(["docker", "compose", "restart"], cwd=DSB, capture_output=True, env=os.environ); time.sleep(90); ok, p95 = healthy(); k += 1
        log.write(f"{time.time():.0f} start {rid} attempt={attempt} healthy={ok} p95={p95}\n"); log.flush()
        subprocess.run(["python3", f"{H}/inject2.py", rid, f, t, OUT], env=dict(os.environ, APP=APP))
        if os.path.exists(f"{OUT}/{rid}.json"): break
        log.write(f"{time.time():.0f} FAILED {rid}\n"); log.flush()
    log.write(f"{time.time():.0f} end {rid}\n"); log.flush()
reset(); log.write("CAMPAIGN DONE\n")
