# Controlled fault-injection study: plan fixed before any run (2026-10-28)

## Testbed
- DeathStarBench socialNetwork (commit cloned 2026-10-28), docker compose, 27 containers, on one 2-vCPU / 8 GB cloud VM.
- Jaeger all-in-one 1.57 (`latest` dropped the UDP agent the services use). Sampling as shipped: probabilistic 0.1. In-memory store capped at 150,000 traces.
- Load: open-loop Poisson at 100 req/s with DeathStarBench's mixed workload: 60% home-timeline read, 30% user-timeline read, 10% compose-post. The generator is our own Python (`loadgen.py`), because wrk2's LuaJIT submodule did not build.
- Traces are converted to the Alibaba cluster-trace-microservices-v2022 CallGraph layout (`collect.py`), so the same pipeline runs on both.

## Faults (`inject.py`)
Each run lasts 540 s: 0–240 s normal, the fault is active from 240 to 420 s, and 420–540 s is recovery.

| Fault | What happens to the target |
|---|---|
| cpu_ramp | CPU quota falls from 1.0 to 0.05 cores in 18 steps of 10 s (a gradual degradation) |
| cpu_step | CPU quota drops to 0.1 cores at once (sudden) |
| pause_flap | The container is frozen 0.3 s out of every second (stalls) |
| surge | No target; request rate rises from 100 to 300 req/s (workload-driven) |
| none | No fault (control) |

- **Targets (16):** 11 application services (all except the nginx frontend) and 5 storage back ends: home-timeline-redis, user-timeline-mongodb, post-storage-mongodb, post-storage-memcached, social-graph-mongodb.
- **Run counts:** 3 faults × 16 targets × 2 repetitions = 96; plus 12 surge and 24 none, for 132 runs in total.
- **Order:** randomized with seed 20261028.
- **Health gate:** before each run, CPU limits are reset and containers unpaused, then a 10-s probe at 50 req/s must show >99% success and p95 < 200 ms. Otherwise the stack is restarted, up to 3 times, and every restart is logged.

## Ground truth, fixed now and computed from end-to-end requests, not from any detector input
- **Bins:** 30-s bins of end-to-end request latency.
- **Run baseline:** the median, over the first 7 bins (0–210 s), of the per-bin p95.
- **SLO breach:** a bin whose p95 exceeds max(5 × the run baseline, 100 ms), or whose error rate exceeds 5%.
- **Cascade run:** at least one SLO-breach bin between fault start and fault end + 60 s.
- **Cascade onset:** the start of the first such bin.
- **Fault without cascade:** a fault run with no SLO breach. These are the negatives for "will this fault become a user-visible cascade".
- **Control runs:** none runs, plus the pre-fault part (0–240 s) of every run.

## Metrics, fixed now; detector thresholds will be fixed before scoring
- **Detection:** an alert after fault start and no later than cascade onset + 60 s.
- **Lead time:** cascade onset minus first alert time. Positive means early warning.
- **False alarms:** alerts in control time, per hour.
- **Per-run discrimination:** each method's maximum score in the fault window, against cascade / no-cascade runs (AUC-ROC and AUC-PR).
- **Same metrics for every method:** the paper's method and the baselines (static global threshold, per-service adaptive threshold, latency-only variant).

## Deviation, recorded 2026-10-28 23:40 UTC, before any campaign result was scored
The cloud VM restarts unpredictably: twice in two hours, each time killing the testbed. Only one of the 132 runs finished there. The campaign therefore moves to GitHub-hosted runners (ubuntu-latest, 4 vCPU, 16 GB), split into 12 parallel shards. A shard runs plan entries i with i mod 12 = shard. Each shard is a fresh runner, and the plan, faults, load, health gate and ground truth are unchanged. The completed VM run (r000) and the pilot run are reported only as pilots, not pooled with the campaign data. Run-to-run hardware variation across runners is a stated limitation.
