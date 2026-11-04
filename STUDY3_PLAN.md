# Study 3 plan: asynchronous paths, operator and learned baselines, an equivalence test

Draft of 2026-11-04. To be deposited on OSF ("OSF Preregistration" template) **before any scored Study 3 run**. Smoke runs, which test plumbing only, may run before deposit and are never scored. The OSF registration, not this file, is the reference version. Any later change is appended as a dated deviation before the data it affects are scored.

Studies 1 and 2 are complete and published as data (see `results/`). Study 3 asks three questions they left open:
- Does per-service scoring warn earlier when a queue sits on the path to the user?
- Is "no meaningful difference" in synchronous applications supported as equivalence, not just as a failure to find a difference?
- How do the detectors compare with the alert operators actually run (multi-window burn rate) and with a learned detector?

## 1. Hypotheses (confirmatory)
Notation: lead(M) is a detector's warning before onset, in seconds, as defined in §6. Δ(A,B) is the per-run difference lead(A) − lead(B), over breach runs that both detectors detect. "Cluster bootstrap" means resampling fault targets (app × target) with replacement: 10,000 draws, percentile intervals, seed 3.

- **H4, equivalence in synchronous apps.** For apps S and H pooled, and the latency SLO, the mean of Δ(M1, M6) lies within ±15 s. Test: the 90% cluster-bootstrap interval of the mean lies inside [−15, +15] (TOST at α = 0.05).
  - The margin is half of one 30-s window. It was fixed before the survey in §10, whose results are reported but cannot change it.
- **H5, asynchronous app, freshness breaches.** In app A (asynchronous), on runs whose first breach is a freshness breach (§5), M1 warns earlier than M6. Both must hold: the mean Δ(M1, M6) > 0 with the 95% cluster-bootstrap lower bound > 0, and a one-sided Wilcoxon signed-rank test with p < 0.05 (zero differences dropped; Pratt treatment reported alongside).
- **H6, operator baseline.** Pooled over all three apps and both SLO types, M6 warns earlier than the burn-rate alert M9: the mean Δ(M6, M9) > 0 with the 95% cluster-bootstrap lower bound > 0.

**Secondary hypotheses, also confirmatory, reported with the same tests:**
- **H7:** the learned detector M10 does not warn earlier than M6. For S and H, the mean Δ(M10, M6) lies within ±15 s.
- **H8:** at a common false-alarm budget of 1.0 alert incident per control hour (thresholds from calibration quantiles, §7), M1 warns before onset in at least as many breach runs as M6. Tested separately in each app; reported descriptively, with no significance test.

**Decision rules:**
- If H4 holds, the paper states equivalence within ±15 s for synchronous apps.
- If H4 fails because the interval crosses a margin, the paper says the data cannot establish equivalence.
- If H5 holds, the paper states that per-service scoring warns earlier on asynchronous paths. If it fails, the paper states that it did not, even on an asynchronous path.
- Every result is reported whatever its direction.

## 2. Applications
1. **S, social network, synchronous.** DeathStarBench commit 6ecb097 with `dsb.patch` (Jaeger 1.57), exactly as in Study 2.
2. **H, hotel reservation, synchronous.** Same commit and patch as in Study 2.
3. **A, social network with asynchronous home-timeline fan-out.** DeathStarBench commit 5728790 (2019-12-04), the last release in which compose-post publishes to RabbitMQ and `write-home-timeline-service` consumes the queue and writes followers' home timelines in Redis.
   - Built from source on the `yg397/thrift-microservice-deps:xenial` base image (the repository's own Dockerfile).
   - Jaeger pinned to 1.57.
   - `scripts/init_social_graph.py` patched only to target localhost.
   - Users are numbered 1–962 in this release (0–961 in S); the workload uses each release's own numbering.
   - The image digest of each build is logged per run.

All container image digests are recorded per run (`docker image inspect`), along with the Docker, kernel and runner versions.

**Fallback for A:**
- If the A stack cannot pass the health gate (§4) in smoke testing after at most three logged fix attempts, A is dropped.
- The deviation is recorded before any scored run, and H5 is reported as untestable.
- No substitute application is introduced. This avoids choosing an application after seeing how it behaves.

## 3. Targets, faults, loads and runs
**Targets** (8 per app, fixed here; each container counts once):
- **S:** compose-post-service, home-timeline-service, user-timeline-service, post-storage-service, social-graph-service, text-service, post-storage-mongodb, home-timeline-redis.
- **H:** search, geo, rate, profile, reservation, memcached-profile, mongodb-geo, mongodb-rate.
- **A:** write-home-timeline-service, write-home-timeline-rabbitmq, home-timeline-redis, compose-post-service, social-graph-service, post-storage-service, home-timeline-service, social-graph-mongodb.

**Timeline per run (660 s):**
- 0–240 s normal load;
- 240–540 s the fault ramps in 30 steps of 10 s;
- at 540 s the fault is removed;
- 540–660 s recovery.

**Faults** (all ramp linearly over the 30 steps):
1. `cpu_ramp_slow`: the CPU quota (cgroup cpu.max) falls from 1.0 to 0.02 cores. As in Study 2.
2. `net_ramp`: netem egress delay rises from 5 to 150 ms. As in Study 2.
3. `loss_ramp`: netem egress packet loss rises from 0.5% to 15%.
4. `mem_squeeze`: cgroup `memory.high` falls from 1.0× to 0.3× the container's memory use at fault start. The kernel then reclaims memory and throttles allocation; `memory.max` is left alone, so the container is not OOM-killed by design.
5. `reset_ramp`: error injection. Inside the target's network namespace, an iptables rule sends TCP reset to a random fraction p of incoming TCP packets, with p rising from 0.5% to 20%. The rule is removed at fault end.

Every injection step's return code is logged. A run in which any step returns non-zero is marked and reported; it is not silently dropped.

**Runs:**
- **Primary block, 100 req/s:** per app, 8 targets × 5 faults × 3 repetitions = 120 fault runs, plus 12 no-fault runs. That is 132 per app and 396 in total.
- **Load block:** per app, `net_ramp` on the first 4 targets listed above × 3 repetitions at each of 50 and 200 req/s (24 fault runs), plus 4 no-fault runs at each load (8). That is 32 per app and 96 in total.
- **Total: 492 runs.**
- Order is randomised within each app by fixed seeds: 20261105 (S), 20261106 (H) and 20261107 (A).
- Runs are distributed round-robin over shards; each shard runs on a fresh GitHub-hosted runner (4 vCPU, 16 GB).

**Calibration:** the first 4 no-fault runs in plan order of each app's primary block, and the first 2 no-fault runs at each load in the load block. They set thresholds and are excluded from every reported number.

## 4. Workload, tracing, health gate
- **Workload:** open-loop Poisson load at the block's rate, in each app's DeathStarBench mix as in Study 2.
  - S and A: 60% home-timeline reads, 30% user-timeline reads, 10% composes.
  - H: 60% search, 39% recommend, 0.5% login, 0.5% reserve.
- **Freshness probe**, run alongside the workload in S and A:
  - Before the run, probe follower P2 follows probe author P1. The probe users are chosen as the two highest user ids.
  - Every 5 s, P1 composes a post containing a unique token.
  - P2's home timeline is then read every 0.5 s until the token appears, or for at most 30 s.
  - The time to appear is that post's freshness; "not seen within 30 s" is recorded as 30 s and flagged.
  - Probe requests are logged separately and excluded from the latency SLO and from the load rate.
- **Tracing:** Jaeger at 10% sampling, converted to CallGraph records as in Studies 1 and 2.
  - A **1% condition** is derived afterwards by keeping only traces whose trace id hashes to 0 mod 10 (first 15 hex digits, base 16).
  - All detectors are scored at 10% (primary) and 1% (secondary). Thresholds are recalibrated at 1%.
- **Health gate:** the same as Study 2 (more than 99% success, p95 < 60 ms, queryable frontend traces), plus for A and S a probe freshness below 2 s in the 10-s check. Up to three stack restarts, each logged; one retry of a failed run.

## 5. Ground truth
- **Bins and latency SLO:** 30-s bins. Baseline = the median per-bin p95 over bins 0–6.
  - **Latency SLO breach:** the bin's p95 exceeds max(5× baseline, 100 ms), or its error rate exceeds 5%. Identical to Studies 1 and 2.
- **Freshness SLO breach** (S and A): the bin's p95 probe freshness exceeds max(5× its baseline, 2 s), or any probe post in the bin is not seen within 30 s.
  - The baseline is the median per-bin p95 freshness over bins 0–6.
- **Fault-induced breach:** a breach of either SLO between fault start and fault end + 60 s.
  - The onset is its first bin.
  - The run's breach type is the SLO breached first; if both breach in the same bin, the type is "both".
- **Freshness-led breach:** a run whose first breach is a freshness breach (type "freshness" or "both"). These runs are the H5 population.
- **Local fault:** a fault run with no breach.

## 6. Detectors
All detectors read 30-s windows of sampled call records (except M7/M8), use history from the run's own earlier windows only, and score from the fourth window on. The windows are the same as in Study 2.
- **M1:** CRS, maximised over all services including the frontend. **M1int:** the same without the frontend.
- **M2:** latency z, maximised over services.
- **M5:** sliding latency z over the previous 10 windows.
- **M6:** frontend latency z.
- **M7:** CPU-throttling z. **M8:** CRS + throttling. As in Study 2.
- **M9, multi-window burn-rate SLO alert.** This scales down the workbook's two-window scheme (ref: Beyer et al. 2018, ch. 5) to run length.
  - From frontend call records, compute in every 10-s slice the fraction of calls with response time above 100 ms.
  - Error budget: 1%.
  - Burn rate over a span = (bad fraction in that span) / 0.01.
  - The alert fires in a 30-s window if the burn rate over the last 60 s exceeds 14.4 **and** the burn rate over the last 300 s exceeds 6.
  - This is a fixed rule, not calibrated. Its false-alarm rate is reported like the others. A calibrated variant M9c (threshold on the 60-s burn rate set by the calibration maximum) is also reported.
  - For freshness SLOs no frontend burn rate exists, so M9 is applied to the latency SLO only. On freshness-led breaches, M9 is scored as it fires on latency.
- **M10, learned detector: Isolation Forest** (Liu, Ting, Zhou, ICDM 2008), scikit-learn with n_estimators = 200, max_samples = 256 and random_state = 0.
  - Features per service-window: log1p(mean response time), log1p(call count), and their changes from the service's previous window.
  - Trained on every service-window of the calibration runs of that app and block.
  - Run-level score = the maximum over services of −score_samples.
- **Thresholds:** τ = the highest run-level score over that app's calibration runs, from window 3 on. Thresholds are set **per app**; Study 2 pooled its two apps, and `score3.py` reproduces Study 2 exactly when thresholds are pooled (`POOLED=1`). This applies to M1–M8, M9c and M10; M9 uses its fixed rule.
- **Resolution:** the primary analysis uses 30-s windows. A secondary analysis repeats everything at 15-s windows, with thresholds recalibrated and ground truth unchanged.

## 7. Metrics
- **Detection:** an alert between fault start and onset + 60 s.
- **Lead:** onset minus the first such alert, in seconds.
- **Alarms:**
  - False-alarm windows per control hour.
  - Alert incidents per control hour: maximal runs of consecutive alert windows.
  - Control time: whole evaluated no-fault runs plus the pre-fault part of fault runs.
- **Alarm budgets:** each detector's threshold swept over the calibration-score quantiles {0.90, 0.95, 0.98, 0.99, 0.995, 0.999, 1.0}. Report breaches warned before onset against incidents per control hour.
- **Local faults:** the share of local-fault runs with an alert before fault end + 60 s.
- **Retrospective AUC:** cascades versus local faults by maximum fault-window score. Reported, labelled retrospective.

## 8. Analysis plan
- **Confirmatory:** H4–H8 exactly as in §1.
  - The 10% sampling, 30-s windows and 100 req/s primary block are the confirmatory data.
  - Load-block runs enter only the load-sensitivity analysis.
- **Pre-specified secondary analyses**, reported as such:
  - H4/H5/H6 at 15-s windows and at 1% sampling;
  - per load level (50/100/200 req/s, `net_ramp` only);
  - per fault type and per app;
  - per breach type;
  - M1int in place of M1;
  - a sign test alongside the Wilcoxon;
  - Studies 1–2 pooled with Study 3 for S and H (H4 only, flagged as combining pre- and post-registered data).
- **Exploratory:** anything else, labelled as exploratory.
- **Missing data:** runs that fail twice are reported by id with the reason. Detectors that do not detect a breach are excluded from that pair and counted. No imputation.
- **Software:** the scorer is `score3.py`, committed (with its hash recorded on OSF) before any scored run. Its invariant tests must pass before scoring. Any later code change is a logged deviation.

## 9. Sample-size reasoning
Studies 1–2 had about 57 gradual-fault breaches from 120 runs. With 5 fault types, including two new ones of unknown potency, the expected breach yield in the primary block is roughly 120–200 runs over S and H, and 40–70 in A.

The Study 2 between-target SD of the mean paired difference was about 15 s. With about 16 target clusters in S + H, the expected half-width of a 90% interval is about 6–8 s, well inside the ±15-s margin if the true difference is near 0. For H5 the sample is smaller and the test may be underpowered; the paper will say so if H5 fails with a wide interval.

## 10. Practitioner survey (separate, descriptive)
An anonymous online survey of SREs and on-call engineers:
- how much advance warning changes their response;
- what false-page rate they accept;
- what they alert on today.

It is analysed descriptively only and does not change any threshold, margin or hypothesis above. Instrument: `SURVEY.md`.

## 11. Timeline and data
1. Smoke runs, never scored.
2. Deposit this plan on OSF; record the registration DOI and timestamp here.
3. Full campaign.
4. Upload the raw data to Kaggle (`kinjalvaishnav/crs-c3-*`).
5. Score with `score3.py` as committed.
6. Publish the results.

## 12. What was seen before deposit (disclosure)
The scorer was dry-run on **Study 2's existing data** (renamed to the Study 3 layout) to test the code. With pooled thresholds it reproduces every published Study 2 lead time exactly. On those data the new detectors behaved as follows, which we disclose because it was seen before the hypotheses were fixed:
- M9, the burn-rate alert, detected 28 of 57 breaches and trailed M6 in all 28.
- M10, the Isolation Forest, trailed M6 on average.
- The 90% interval for Δ(M1, M6) was about −17 to +1.5 s.

No Study 3 data existed when this plan was written.
