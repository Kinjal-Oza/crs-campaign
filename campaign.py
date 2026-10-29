"""Fault-injection campaign on the DeathStarBench socialNetwork testbed (plan: CAMPAIGN_PLAN.md).
Resumable: runs whose <id>.json exists are skipped. Usage: python3 campaign.py OUTDIR [SHARD NSHARDS]  (a shard runs plan entries with index % NSHARDS == SHARD)
"""
import sys, os, json, random, subprocess, time
import pandas as pd
H = os.path.dirname(os.path.abspath(__file__)); OUT = sys.argv[1]; os.makedirs(OUT, exist_ok=True)
SHARD, NSH = (int(sys.argv[2]), int(sys.argv[3])) if len(sys.argv) > 3 else (0, 1)
DSB = os.environ.get("DSB", "/home/claude/dsb/socialNetwork")
TARGETS = ["compose-post-service", "home-timeline-service", "user-timeline-service", "post-storage-service",
           "social-graph-service", "text-service", "user-service", "user-mention-service", "url-shorten-service",
           "media-service", "unique-id-service", "home-timeline-redis", "user-timeline-mongodb",
           "post-storage-mongodb", "post-storage-memcached", "social-graph-mongodb"]
FAULTS = ["cpu_ramp", "cpu_step", "pause_flap"]
plan = [(f, t, r) for r in range(2) for f in FAULTS for t in TARGETS] + [("surge", "-", r) for r in range(12)] \
     + [("none", "-", r) for r in range(24)]
random.Random(20261028).shuffle(plan)
json.dump(plan, open(f"{OUT}/plan.json", "w"))

def names(): return subprocess.run(["docker", "ps", "-a", "--format", "{{.Names}}"], capture_output=True, text=True).stdout.split()
def reset():
    for n in names():
        if n.startswith("socialnetwork-"):
            subprocess.run(["docker", "unpause", n], capture_output=True); subprocess.run(["docker", "update", "--cpus", "2", n], capture_output=True)
def healthy():
    p = f"{OUT}/_probe.csv"; subprocess.run(["python3", f"{H}/loadgen.py", "50", "10", p])
    d = pd.read_csv(p); ok = (d.status == 200).mean() > 0.99 and d.lat_ms.quantile(.95) < 200
    try:
        import urllib.request; ok = ok and len(json.load(urllib.request.urlopen("http://localhost:16686/api/services"))["data"] or []) >= 8
        t1 = int(time.time() * 1e6); tr = json.load(urllib.request.urlopen(f"http://localhost:16686/api/traces?service=nginx-web-server&limit=5&start={t1-60_000_000}&end={t1}"))["data"] or []
        ok = ok and len(tr) > 0   # the frontend's traces must be queryable, not just the service list
    except Exception: ok = False
    return ok, round(float(d.lat_ms.quantile(.95)), 1)

log = open(f"{OUT}/campaign.log", "a")
for i, (f, t, r) in enumerate(plan):
    rid = f"r{i:03d}_{f}_{t}_{r}"
    ONLY = [int(x) for x in os.environ.get("RUN_ONLY", "").split(",") if x]
    if ONLY: 
        if i not in ONLY or ONLY.index(i) % NSH != SHARD or os.path.exists(f"{OUT}/{rid}.json"): continue
    elif i % NSH != SHARD or os.path.exists(f"{OUT}/{rid}.json"): continue
    reset(); time.sleep(20); ok, p95 = healthy(); k = 0
    while not ok and k < 3:
        log.write(f"{time.time():.0f} unhealthy before {rid} p95={p95}; restarting stack\n"); log.flush()
        subprocess.run(["docker", "compose", "restart"], cwd=DSB, capture_output=True); time.sleep(60); ok, p95 = healthy(); k += 1
    log.write(f"{time.time():.0f} start {rid} healthy={ok} p95={p95}\n"); log.flush()
    subprocess.run(["python3", f"{H}/inject.py", rid, f, t, OUT])
    if not os.path.exists(f"{OUT}/{rid}.json"):   # e.g. collector got zero traces: restart stack, retry once
        log.write(f"{time.time():.0f} FAILED {rid}; restarting stack and retrying once\n"); log.flush()
        subprocess.run(["docker", "compose", "restart"], cwd=DSB, capture_output=True); time.sleep(60); reset(); time.sleep(20)
        subprocess.run(["python3", f"{H}/inject.py", rid, f, t, OUT])
    log.write(f"{time.time():.0f} end {rid}\n"); log.flush()
reset(); log.write("CAMPAIGN DONE\n")
