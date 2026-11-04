"""Study 3: one gradual-fault experiment (plan: STUDY3_PLAN.md).
Usage: APP=social|async|hotel python3 inject3.py RUN_ID FAULT TARGET OUTDIR [RATE]
Timeline: 0-240 s normal, 240-540 s fault ramps in 30 steps of 10 s, removed at 540 s, 540-660 s recovery.
cpu_ramp_slow: CPU quota (cgroup cpu.max) 1.0 -> 0.02 cores.     net_ramp : netem egress delay 5 -> 150 ms.
loss_ramp    : netem egress loss 0.5% -> 15%.                    mem_squeeze: cgroup memory.high 1.0x -> 0.3x of memory.current at fault start.
reset_ramp   : iptables in the target's netns sends TCP reset to a random fraction 0.5% -> 20% of incoming TCP packets.
Also logs image digests, and samples cgroup cpu.stat / memory.current every 5 s.
Also samples every container's cgroup cpu.stat every 5 s (<RUN>.res.csv) for the resource-signal analysis.
Outputs <RUN>.req.csv, <RUN>.cg.csv.gz, <RUN>.res.csv, <RUN>.json.
"""
import sys, os, json, time, subprocess, threading, gzip, shutil, glob
RUN, FAULT, TARGET, OUT = sys.argv[1:5]; RATE = float(sys.argv[5]) if len(sys.argv) > 5 else 100.0
APP = os.environ.get("APP", "social"); FRONT = {"social": "nginx-web-server", "async": "nginx-web-server", "hotel": "frontend"}[APP]
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
def cg(cont, name):
    g = glob.glob(f"/sys/fs/cgroup/**/docker-{cont}.scope/{name}", recursive=True); return g[0] if g else None
def cgwrite(cont, name, val):
    p = cg(cont, name); return sh("sudo", "sh", "-c", f"echo '{val}' > {p}").returncode if p else -1
def ns(*cmd): return sh("docker", "run", "--rm", "--net", f"container:{C}", "--cap-add", "NET_ADMIN", "nicolaka/netshoot", *cmd)
def netem(args): return ns("tc", "qdisc", *args)
def lin(a, b, k): return a + (b - a) * (k + 1) / STEPS
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
        f.write("t,service,usage_usec,throttled_usec,nr_throttled,memory_current\n")
        while not stop.is_set():
            now = time.time()
            for s, p in paths.items():
                try:
                    d = dict(l.split() for l in open(p))
                    try: mem = open(p.replace("cpu.stat", "memory.current")).read().strip()
                    except Exception: mem = ""
                    f.write(f"{now:.2f},{s},{d.get('usage_usec',0)},{d.get('throttled_usec',0)},{d.get('nr_throttled',0)},{mem}\n")
                except Exception: pass
            f.flush(); stop.wait(5)
    events.append(("cgroups_found", len(paths)))
sm = threading.Thread(target=sampler); sm.start()
env = dict(os.environ, APP=APP)
lg = threading.Thread(target=lambda: subprocess.run(["python3", f"{H}/loadgen3.py", str(RATE), str(END), f"{OUT}/{RUN}.req.csv"], env=env)); lg.start()

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
elif FAULT == "loss_ramp":
    for k in range(STEPS):
        p = lin(0.5, 15.0, k); r = netem(["replace", "dev", "eth0", "root", "netem", "loss", f"{p:.2f}%"])
        events.append((f"loss={p:.2f}% rc={r.returncode}", time.time())); at(F0 + 10 * (k + 1))
    netem(["del", "dev", "eth0", "root"])
elif FAULT == "mem_squeeze":
    base = int(open(cg(C, "memory.current")).read()); events.append((f"mem_base={base}", time.time()))
    for k in range(STEPS):
        b = int(base * lin(1.0, 0.3, k)); rc = cgwrite(C, "memory.high", b); events.append((f"memory.high={b} rc={rc}", time.time())); at(F0 + 10 * (k + 1))
    cgwrite(C, "memory.high", "max")
elif FAULT == "reset_ramp":
    r0 = ns("sh", "-c", "iptables -N CRSF 2>/dev/null; iptables -F CRSF; iptables -C INPUT -j CRSF 2>/dev/null || iptables -I INPUT -j CRSF")
    events.append((f"chain rc={r0.returncode} {r0.stderr.strip()[:80]}", time.time()))
    for k in range(STEPS):
        p = lin(0.005, 0.20, k)
        r = ns("sh", "-c", f"iptables -F CRSF && iptables -A CRSF -p tcp -m statistic --mode random --probability {p:.4f} -j REJECT --reject-with tcp-reset")
        events.append((f"reset_p={p:.4f} rc={r.returncode}", time.time())); at(F0 + 10 * (k + 1))
    ns("sh", "-c", "iptables -D INPUT -j CRSF; iptables -F CRSF; iptables -X CRSF")
else:
    at(F1)
events.append(("fault_end", time.time()))
lg.join(); t1 = time.time(); stop.set(); sm.join()
time.sleep(5)
subprocess.run(["python3", f"{H}/collect2.py", str(t0), str(t1), f"{OUT}/{RUN}.cg.csv"], check=True, env=dict(os.environ, FRONT=FRONT))
with open(f"{OUT}/{RUN}.cg.csv", "rb") as a, gzip.open(f"{OUT}/{RUN}.cg.csv.gz", "wb") as b: shutil.copyfileobj(a, b)
os.remove(f"{OUT}/{RUN}.cg.csv")
dig = sh("sh", "-c", "docker ps --format '{{.Image}}' | sort -u | xargs docker image inspect --format '{{.RepoTags}} {{.Id}} {{.RepoDigests}}'").stdout
json.dump(dict(run=RUN, app=APP, images=dig.splitlines(), docker=sh("docker", "version", "--format", "{{.Server.Version}}").stdout.strip(),
               kernel=os.uname().release, fault=FAULT, target=TARGET if FAULT != "none" else None, rate=RATE, t0=t0,
               fault_start=t0 + F0, fault_end=t0 + F1, end=t1, events=events), open(f"{OUT}/{RUN}.json", "w"), indent=1)
print("done", RUN, FAULT, TARGET)
