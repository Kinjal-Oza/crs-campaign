"""Study 3 campaign driver. Plan: STUDY3_PLAN.md (deposited on OSF before scored runs).
Usage: APP=social|hotel|async DSB=<app dir> python3 campaign3.py OUTDIR SHARD NSHARDS
Builds the plan (primary block at 100 req/s, load block at 50/200 req/s), runs this shard's share, with the Study 2 health gate
plus a probe-freshness check for the social apps."""
import sys, os, json, random, subprocess, time, urllib.request
import pandas as pd
H = os.path.dirname(os.path.abspath(__file__)); OUT, SHARD, NSH = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]); os.makedirs(OUT, exist_ok=True)
APP = os.environ["APP"]; DSB = os.environ["DSB"]; FRONT = {"social": "nginx-web-server", "async": "nginx-web-server", "hotel": "frontend"}[APP]
TARGETS = {
 "social": ["compose-post-service", "home-timeline-service", "user-timeline-service", "post-storage-service", "social-graph-service",
            "text-service", "post-storage-mongodb", "home-timeline-redis"],
 "hotel": ["search", "geo", "rate", "profile", "reservation", "memcached-profile", "mongodb-geo", "mongodb-rate"],
 "async": ["write-home-timeline-service", "write-home-timeline-rabbitmq", "home-timeline-redis", "compose-post-service",
           "social-graph-service", "post-storage-service", "home-timeline-service", "social-graph-mongodb"]}[APP]
FAULTS = ["cpu_ramp_slow", "net_ramp", "loss_ramp", "mem_squeeze", "reset_ramp"]
SEED = {"social": 20261105, "hotel": 20261106, "async": 20261107}[APP]
prim = [(f, t, r, 100) for r in range(3) for f in FAULTS for t in TARGETS] + [("none", "-", r, 100) for r in range(12)]
load = [("net_ramp", t, r, q) for q in (50, 200) for r in range(3) for t in TARGETS[:4]] + [("none", "-", r, q) for q in (50, 200) for r in range(4)]
rng = random.Random(SEED); rng.shuffle(prim); rng.shuffle(load); plan = prim + load
if os.environ.get("SMOKE"):
    plan = [(f, TARGETS[i % len(TARGETS)], 0, 100) for i, f in enumerate(["none"] + FAULTS)]
json.dump(plan, open(f"{OUT}/plan3_{APP}.json", "w"))

def names(): return subprocess.run(["docker", "ps", "-a", "--format", "{{.Names}}"], capture_output=True, text=True).stdout.split()
def reset():   # unpause, clear CPU and memory limits, remove netem and iptables leftovers
    for n in names(): subprocess.run(["docker", "unpause", n], capture_output=True)
    subprocess.run("for f in /sys/fs/cgroup/system.slice/docker-*.scope/cpu.max; do echo 'max 100000' | sudo tee $f >/dev/null; done; "
                   "for f in /sys/fs/cgroup/system.slice/docker-*.scope/memory.high; do echo max | sudo tee $f >/dev/null; done", shell=True)
    for c in subprocess.run(["docker", "ps", "-q"], capture_output=True, text=True).stdout.split():
        subprocess.run(["docker", "run", "--rm", "--net", f"container:{c}", "--cap-add", "NET_ADMIN", "nicolaka/netshoot", "sh", "-c",
                        "tc qdisc del dev eth0 root 2>/dev/null; iptables -D INPUT -j CRSF 2>/dev/null; iptables -F CRSF 2>/dev/null; iptables -X CRSF 2>/dev/null; true"],
                       capture_output=True)
def healthy():
    p = f"{OUT}/_probe.req.csv"; subprocess.run(["python3", f"{H}/loadgen3.py", "50", "10", p], env=dict(os.environ, APP=APP))
    d = pd.read_csv(p); ok = (d.status == 200).mean() > 0.99 and d.lat_ms.quantile(.95) < 60; fr = None
    if APP in ("social", "async"):
        try:
            q = pd.read_csv(f"{OUT}/_probe.fresh.csv"); fr = float(q.fresh_s.max()); ok = ok and len(q) > 0 and fr < 2 and q.seen.all()
        except Exception: ok = False
    try:
        t1 = int(time.time() * 1e6)
        tr = json.load(urllib.request.urlopen(f"http://localhost:16686/api/traces?service={FRONT}&limit=5&start={t1-60_000_000}&end={t1}"))["data"] or []
        ok = ok and len(tr) > 0
    except Exception: ok = False
    return ok, round(float(d.lat_ms.quantile(.95)), 1), fr

log = open(f"{OUT}/campaign3_{APP}_{SHARD}.log", "a")
for i, (f, t, r, q) in enumerate(plan):
    rid = f"{APP}_r{i:03d}_{f}_{t}_{r}_q{q}"
    if i % NSH != SHARD or os.path.exists(f"{OUT}/{rid}.json"): continue
    for attempt in range(2):
        reset(); time.sleep(20); ok, p95, fr = healthy(); k = 0
        while not ok and k < 3:
            log.write(f"{time.time():.0f} unhealthy before {rid} p95={p95} fresh={fr}; restarting stack\n"); log.flush()
            subprocess.run(["docker", "compose", "restart"], cwd=DSB, capture_output=True, env=os.environ); time.sleep(90); ok, p95, fr = healthy(); k += 1
        log.write(f"{time.time():.0f} start {rid} attempt={attempt} healthy={ok} p95={p95} fresh={fr}\n"); log.flush()
        subprocess.run(["python3", f"{H}/inject3.py", rid, f, t, OUT, str(q)], env=dict(os.environ, APP=APP))
        if os.path.exists(f"{OUT}/{rid}.json"): break
        log.write(f"{time.time():.0f} FAILED {rid}\n"); log.flush()
    log.write(f"{time.time():.0f} end {rid}\n"); log.flush()
reset(); log.write("CAMPAIGN DONE\n")
