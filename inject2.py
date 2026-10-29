"""Campaign 2: one gradual-fault experiment (plan: CAMPAIGN2_PLAN.md).
Usage: APP=social|hotel python3 inject2.py RUN_ID FAULT TARGET OUTDIR [RATE]
FAULT: none | cpu_ramp_slow | net_ramp.  Timeline: 0-240 s normal, 240-540 s fault ramps up in 30 steps of 10 s, 540-660 s recovery.
cpu_ramp_slow: TARGET CPU quota falls linearly from 1.0 to 0.02 cores.
net_ramp     : egress delay on TARGET's interface rises linearly from 5 to 150 ms (netem).
Also samples every container's cgroup cpu.stat every 5 s (<RUN>.res.csv) for the resource-signal analysis.
Outputs <RUN>.req.csv, <RUN>.cg.csv.gz, <RUN>.res.csv, <RUN>.json.
"""
import sys, os, json, time, subprocess, threading, gzip, shutil, glob
RUN, FAULT, TARGET, OUT = sys.argv[1:5]; RATE = float(sys.argv[5]) if len(sys.argv) > 5 else 100.0
APP = os.environ.get("APP", "social"); FRONT = {"social": "nginx-web-server", "hotel": "frontend"}[APP]
H = os.path.dirname(os.path.abspath(__file__)); os.makedirs(OUT, exist_ok=True)
F0, F1, END, STEPS = (240, 540, 660, 30) if not os.environ.get('SMOKE') else (60, 120, 150, 6)
def sh(*a, **k): return subprocess.run(list(a), capture_output=True, text=True, **k)
def cid(svc):
    out = sh("docker", "ps", "-q", "--no-trunc", "--filter", f"label=com.docker.compose.service={svc}").stdout.split()
    return out[0] if out else None
C = cid(TARGET) if FAULT != "none" else None
assert FAULT == "none" or C, f"no container for {TARGET}"
def cpumax(cont, val):   # write cgroup v2 cpu.max directly ("<quota> 100000" or "max 100000"); docker update cannot clear a limit
    g = glob.glob(f"/sys/fs/cgroup/**/docker-{cont}.scope/cpu.max", recursive=True)
    return sh("sudo", "sh", "-c", f"echo '{val}' > {g[0]}").returncode if g else -1
def netem(args): return sh("docker", "run", "--rm", "--net", f"container:{C}", "--cap-add", "NET_ADMIN", "nicolaka/netshoot", "tc", "qdisc", *args)
t0 = time.time(); events = []; stop = threading.Event()
def at(s): time.sleep(max(0, t0 + s - time.time()))

def sampler():   # cgroup v2 cpu.stat for every running container, every 5 s
    ids = {}
    for line in sh("docker", "ps", "--no-trunc", "--format", '{{.ID}} {{.Label "com.docker.compose.service"}}').stdout.splitlines():
        i, *s = line.split(); ids[i] = s[0] if s else i[:12]
    paths = {}
    for i, s in ids.items():
        g = glob.glob(f"/sys/fs/cgroup/**/docker-{i}.scope/cpu.stat", recursive=True) or glob.glob(f"/sys/fs/cgroup/**/{i}/cpu.stat", recursive=True)
        if g: paths[s] = g[0]
    with open(f"{OUT}/{RUN}.res.csv", "w") as f:
        f.write("t,service,usage_usec,throttled_usec,nr_throttled\n")
        while not stop.is_set():
            now = time.time()
            for s, p in paths.items():
                try:
                    d = dict(l.split() for l in open(p))
                    f.write(f"{now:.2f},{s},{d.get('usage_usec',0)},{d.get('throttled_usec',0)},{d.get('nr_throttled',0)}\n")
                except Exception: pass
            f.flush(); stop.wait(5)
    events.append(("cgroups_found", len(paths)))
sm = threading.Thread(target=sampler); sm.start()
env = dict(os.environ, APP=APP)
lg = threading.Thread(target=lambda: subprocess.run(["python3", f"{H}/loadgen2.py", str(RATE), str(END), f"{OUT}/{RUN}.req.csv"], env=env)); lg.start()

at(F0); events.append(("fault_start", time.time()))
if FAULT == "cpu_ramp_slow":
    for k in range(STEPS):
        q = 1.0 - 0.98 * (k + 1) / STEPS; rc = cpumax(C, f"{int(q * 100000)} 100000"); events.append((f"cpus={q:.3f} rc={rc}", time.time())); at(F0 + 10 * (k + 1))
    cpumax(C, "max 100000")
elif FAULT == "net_ramp":
    for k in range(STEPS):
        ms = 5 * (k + 1) * (30 // STEPS); r = netem(["replace", "dev", "eth0", "root", "netem", "delay", f"{ms}ms"])
        events.append((f"delay={ms}ms rc={r.returncode}", time.time())); at(F0 + 10 * (k + 1))
    netem(["del", "dev", "eth0", "root"])
else:
    at(F1)
events.append(("fault_end", time.time()))
lg.join(); t1 = time.time(); stop.set(); sm.join()
time.sleep(5)
subprocess.run(["python3", f"{H}/collect2.py", str(t0), str(t1), f"{OUT}/{RUN}.cg.csv"], check=True, env=dict(os.environ, FRONT=FRONT))
with open(f"{OUT}/{RUN}.cg.csv", "rb") as a, gzip.open(f"{OUT}/{RUN}.cg.csv.gz", "wb") as b: shutil.copyfileobj(a, b)
os.remove(f"{OUT}/{RUN}.cg.csv")
json.dump(dict(run=RUN, app=APP, fault=FAULT, target=TARGET if FAULT != "none" else None, rate=RATE, t0=t0,
               fault_start=t0 + F0, fault_end=t0 + F1, end=t1, events=events), open(f"{OUT}/{RUN}.json", "w"), indent=1)
print("done", RUN, FAULT, TARGET)
