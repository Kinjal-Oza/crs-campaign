"""Pull sampled Jaeger traces from the testbed and write them as call-graph records in the Alibaba
cluster-trace-microservices-v2022 CallGraph layout: timestamp(ms), traceid, service, rpc_id, um, rpctype, dm, interface, rt(ms).
A record is one cross-service call (parent span's service != child span's service) or a storage call
(client span whose operation names redis/mongo/memcached; dm = <service>-<store>).
Usage: python3 collect.py START_EPOCH END_EPOCH OUT.csv   (queries in 30-s chunks)
"""
import sys, json, urllib.request, csv
S, E, OUT = float(sys.argv[1]), float(sys.argv[2]), sys.argv[3]
Q = "http://localhost:16686/api/traces?service=nginx-web-server&limit=20000&start={}&end={}"
STORES = ("redis", "mongo", "memcached")
seen = set(); n = 0
with open(OUT, "w", newline="") as f:
    w = csv.writer(f); w.writerow(["timestamp", "traceid", "service", "rpc_id", "um", "rpctype", "dm", "interface", "rt"])
    t = S
    while t < E:
        u = Q.format(int(t * 1e6), int(min(t + 30, E) * 1e6)); t += 30
        data = json.load(urllib.request.urlopen(u, timeout=120))["data"] or []
        for tr in data:
            if tr["traceID"] in seen: continue
            seen.add(tr["traceID"]); P = tr["processes"]
            sp = {s["spanID"]: s for s in tr["spans"]}
            svc = {k: P[s["processID"]]["serviceName"] for k, s in sp.items()}
            root = [s for s in tr["spans"] if not s["references"]]
            entry = root[0]["operationName"] if root else ""
            for k, s in sp.items():
                ref = s["references"][0]["spanID"] if s["references"] else None
                op = s["operationName"]; ts = s["startTime"] / 1000.0; rt = s["duration"] / 1000.0
                store = next((x for x in STORES if x in op.lower()), None)
                if store and op.endswith("_client"):
                    w.writerow([f"{ts:.3f}", tr["traceID"], entry, k, svc[k], "db" if store == "mongo" else "mc", f"{svc[k]}-{store}", op, f"{rt:.3f}"]); n += 1
                elif ref in sp and svc[ref] != svc[k]:
                    w.writerow([f"{ts:.3f}", tr["traceID"], entry, k, svc[ref], "rpc", svc[k], op, f"{rt:.3f}"]); n += 1
                elif ref is None:
                    w.writerow([f"{ts:.3f}", tr["traceID"], entry, k, "USER", "http", svc[k], op, f"{rt:.3f}"]); n += 1
print("traces", len(seen), "records", n)
if not seen: sys.exit("collector returned zero traces")
