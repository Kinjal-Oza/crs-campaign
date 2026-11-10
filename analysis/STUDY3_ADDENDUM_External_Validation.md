# Study 3 Addendum: External validation on an independent public dataset (RCAEval RE2)

**Parent registration:** Study 3, https://doi.org/10.17605/OSF.IO/UJDVS (registered 2026-11-08).
**Author:** Kinjal Vaishnav (ORCID linked on OSF).
**Date written:** 2026-11-09.

## 1. Status of the data at the time of registration
- The study's own results (Study 3, 490 runs) have been scored. This addendum is written after seeing them. It tests whether the Study 3 findings replicate on systems, faults and load generators we did not build.
- RCAEval RE2 (Zenodo record 14590730, DOI 10.5281/zenodo.14590730, CC BY 4.0) has been **downloaded**.
- Only the following has been inspected:
  - the directory layout;
  - the file names and column headers;
  - the injection timestamps (each case has 720 s of normal operation before injection and up to 720 s after it).
- **No detector score, SLI value, breach label or other outcome has been computed on RCAEval.**

## 2. Data
- **Systems:** RE2-OB (Online Boutique), RE2-SS (Sock Shop), RE2-TT (Train Ticket).
- **Faults:** cpu, mem, disk, delay, loss, socket, each injected into 5 services, 3 repetitions per pair; 270 cases (OB has 91).
- **Faults are step injections,** not ramps. So the outcomes are early warning before SLO breach onset *and* detection delay after injection.
- **Exclusions, decided now:**
  - cases with less than 600 s after injection;
  - cases with fewer than 600 entry requests in the 720 s before injection (no stable baseline);
  - OB and TT cases where more than 50% of spans have a parent span missing from the trace file (incomplete traces).

  The last two thresholds were set after counting requests and orphan spans per case during preprocessing. That count involved no SLI, breach or detector output. It flags 1 TT case under each rule, and 2 OB cases are short. Every excluded case is reported.

## 3. Inputs, mapped to Study 3
- **Per-request SLI (frontend entry requests):**
  - OB: root spans of `frontendservice` with operation `frontend` (`traces.csv`, spans without a parent). This excludes health checks and telemetry exports.
  - TT: no frontend or gateway service appears in the traces, so entry requests are all root spans except health checks.
  - OB and TT:
    - Latency = `duration`.
    - Error = a status code present and not OK (gRPC ≠ 0, HTTP ≥ 500). The headers show that root spans carry no status code in OB or TT. In practice the SLI there is therefore latency only.
  - SS: front-end access-log lines in `logs.csv` (`METHOD path STATUS ms`).
    - Latency = the logged ms.
    - Error = status ≥ 500.
- **Per-service series:**
  - OB and TT: from each service's entry spans, grouped by `serviceName` per 30-s window: mean duration and span count. An entry span is a root span, or a span whose parent belongs to a different service. Health checks and telemetry-export spans are excluded. This matches the Study 3 call-graph rows (caller → callee, callee response time).
  - SS: from `metrics.csv` per service: mean of `istio-latency-50` and the increase in `istio-request-total` per window.
- **Call graph for the blast-radius term:**
  - OB and TT: parent→child service edges from spans in the 720 s before injection.
  - SS: the published Sock Shop topology, written down before any scoring and committed with the code.
- **Windows:** 30-s windows aligned to the injection time minus 720 s (t = 0 at the start of the case).

## 4. Ground truth (as Study 3)
- Bin the frontend SLI into 30-s bins.
- **Baseline:** the median p95 over the bins before injection.
- **Threshold:** max(5 × baseline, 100 ms).
- **Breach bin:** p95 above the threshold, *or* error fraction above 5%.
- **Breach onset:** the earliest breach bin between injection and injection + 600 s.

## 5. Detectors
These are identical in code and constants to `score3.py` (SHA-256 prefix 0b6319aef5a575ba). W = 30 s; all spans are used.

| Detector | What it is |
|---|---|
| M1 | Cascade-risk score (blast radius × latency z × call-rate z), max over services |
| M6 | Adaptive baseline (robust z) on the mean latency of the entry-request series defined in Section 3. In Study 3 this was the frontend's entry calls. |
| M9 | Multi-window burn rate: 60-s burn > 14.4 and 300-s burn > 6, budget 1%. Bad request = latency above the case's SLO latency threshold (Section 4), or an error. In Study 3 that threshold was always the 100-ms floor, so this is the same rule. RCAEval baselines are slower, and a fixed 100-ms cutoff would sit below the SLO and make M9 fire on healthy traffic. Errors are added because RCAEval includes loss and socket faults; this can only make M9 fire earlier. M9c uses the same bad-request definition. |
| M9c | 60-s burn as a continuous score |
| M10 | Isolation Forest (n_estimators 200, max_samples 256, random_state 0), fit per system on calibration windows |

**Calibration:**
- **Calibration set:** the pre-injection windows of all **repetition-1** cases of each system.
- **Thresholds:** per system, the maximum calibration score from window 3 onward (as Study 3).
- **Excluded from evaluation:** repetition-1 cases.
- **Evaluated:** repetitions 2–3.

**Lead:** breach onset minus the first alert at or after injection, counting only alerts up to onset + 60 s (as Study 3). Lead > 0 is an early warning.

**Detection delay:** the first alert after injection minus the injection time, within 600 s. Reported for all evaluated cases.

**Analysis code, frozen at registration and attached:**
- `prep_ext.py`, SHA-256 prefix 6c94e442f61bc66e: reduces each case to compact inputs.
- `ext3.py`, SHA-256 prefix 9d571ce64071f4a1: scores the reduced inputs.

`ext3.py` imports `score3.py` unchanged. It has been tested on synthetic data only.

## 6. Confirmatory hypotheses
Paired lead differences, cluster bootstrap over system|target service, 10,000 draws, seed 3 (as Study 3).

- **E1 (replicates H6):** M6 warns earlier than M9 on all breaches. Holds if the mean difference is > 0 and the lower bound of the 95% CI is > 0.
- **E2 (replicates the burn-rate mechanism):** both conditions must hold.
  - (a) At the breach-onset bin, the frontend 60-s bad fraction is below 14.4% in more than half of breaches (exact binomial test, p < 0.05).
  - (b) M9 fires before breach onset in fewer than 5% of breaches.
- **E3 (replicates H7):** M10 is equivalent to M6 within ±15 s (TOST, 90% CI) on latency breaches.
- **E4 (replicates H4):** M1 is equivalent to M6 within ±15 s (TOST, 90% CI) on latency breaches.
- **E5 (tests an exploratory Study 3 finding out of sample):** in Study 3, raising thresholds to 1.25 × calibration maximum removed most false alarms at little cost. Here, at 1.25 × calibration maximum, M1 must meet both conditions.
  - It has ≤ 1 false-alarm incident per hour of pre-injection evaluation time in each system.
  - It keeps ≥ 90% of the early warnings it gives at 1 × maximum.

## 7. Reporting
- All five results will be reported, whatever they show, in the EMSE paper and in the repository.
- **Secondary, descriptive:** per-system breach counts, detection delays, false alarms per hour, and why M9 misses breaches (using the same categories as the Study 3 mechanism analysis).
- **Deviations:** any deviation from this addendum will be listed with its reason.
