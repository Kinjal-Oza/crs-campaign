"""One fault-injection experiment on the DeathStarBench socialNetwork testbed.
Usage: python3 inject.py RUN_ID FAULT TARGET OUTDIR [RATE]
FAULT: none | cpu_ramp | cpu_step | pause_flap | surge
Timeline (seconds from start): 0-240 normal load; fault from 240; fault active until 420; 420-540 recovery.
cpu_ramp  : CPU quota of TARGET falls linearly from 1.0 to 0.05 cores over 240-420 s (step every 10 s).
cpu_step  : CPU quota of TARGET set to 0.1 cores at 240 s, restored at 420 s.
pause_flap: TARGET frozen (docker pause) 0.3 s in every 1.0 s from 240 to 420 s.
surge     : request rate rises linearly from RATE to 3*RATE over 240-420 s (no target).
none      : no fault (control run for false alarms).
Outputs: <OUTDIR>/<RUN_ID>.req.csv (per request), <RUN_ID>.cg.csv.gz (call graph), <RUN_ID>.json (ground truth).
"""
import sys, os, json, time, subprocess, threading, gzip, shutil
RUN, FAULT, TARGET, OUT = sys.argv[1:5]; RATE = float(sys.argv[5]) if len(sys.argv) > 5 else 100.0
H = os.path.dirname(os.path.abspath(__file__)); os.makedirs(OUT, exist_ok=True)
F0, F1, END = 240, 420, 540
C = f"socialnetwork-{TARGET}-1"
def dk(*a): subprocess.run(["docker", *a], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
t0 = time.time(); events = []
def at(s): time.sleep(max(0, t0 + s - time.time()))

# load: three phases so 'surge' can change the rate; other faults keep RATE throughout
def load():
    if FAULT != "surge":
        subprocess.run(["python3", f"{H}/loadgen.py", str(RATE), str(END), f"{OUT}/{RUN}.req.csv"]); return
    parts = []
    def seg(i, r, d):
        p = f"{OUT}/{RUN}.req{i}.csv"; parts.append(p); subprocess.run(["python3", f"{H}/loadgen.py", str(r), str(d), p])
    seg(0, RATE, F0)
    for k in range(18):   # 18 x 10 s steps from RATE to 3*RATE
        seg(k + 1, RATE * (1 + 2 * (k + 1) / 18), 10)
    seg(99, RATE, END - F1)
    with open(f"{OUT}/{RUN}.req.csv", "w") as f:
        for i, p in enumerate(parts):
            lines = open(p).read().splitlines(); f.write("\n".join(lines if i == 0 else lines[1:]) + "\n"); os.remove(p)
th = threading.Thread(target=load); th.start()

at(F0); events.append(("fault_start", time.time()))
if FAULT == "cpu_ramp":
    for k in range(18):
        q = 1.0 - (0.95 * (k + 1) / 18); dk("update", "--cpus", f"{q:.3f}", C); events.append((f"cpus={q:.3f}", time.time())); at(F0 + 10 * (k + 1))
elif FAULT == "cpu_step":
    dk("update", "--cpus", "0.1", C); at(F1)
elif FAULT == "pause_flap":
    while time.time() < t0 + F1:
        dk("pause", C); time.sleep(0.3); dk("unpause", C); time.sleep(0.7)
else:
    at(F1)
if FAULT in ("cpu_ramp", "cpu_step"): dk("update", "--cpus", "2", C)
if FAULT == "pause_flap": dk("unpause", C)
events.append(("fault_end", time.time()))
th.join(); t1 = time.time()
time.sleep(5)
subprocess.run(["python3", f"{H}/collect.py", str(t0), str(t1), f"{OUT}/{RUN}.cg.csv"], check=True)
with open(f"{OUT}/{RUN}.cg.csv", "rb") as a, gzip.open(f"{OUT}/{RUN}.cg.csv.gz", "wb") as b: shutil.copyfileobj(a, b)
os.remove(f"{OUT}/{RUN}.cg.csv")
json.dump(dict(run=RUN, fault=FAULT, target=TARGET if FAULT not in ("none", "surge") else None, rate=RATE,
               t0=t0, fault_start=t0 + F0, fault_end=t0 + F1, end=t1, events=events), open(f"{OUT}/{RUN}.json", "w"), indent=1)
print("done", RUN, FAULT, TARGET)
