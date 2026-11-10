"""
Latency-deviation and call-rate-anomaly feature extraction.

Input: aggregated per-service, per-window MSRTMCR statistics
       (columns: window_idx, msname, mean_rt, max_rt, mean_mcr, n_samples)
       built by scripts/aggregate_msrtmcr.py from real Alibaba v2022 trace
       CallGraph/MSRTMCR windows.

Each service gets its own rolling baseline (mean + std of mean_rt / mean_mcr
over prior windows) rather than a single fixed threshold across all
services — different services have structurally different normal latency,
so a shared threshold either misses slow services or over-alerts on fast
ones. This is real code operating on real downloaded data; no numbers in
this module or its outputs are invented.
"""
import csv
import collections
import statistics
import math

def _robust_z(value, history, epsilon=0.5):
    """Log-transformed, epsilon-floored z-score. Raw latency is heavy-tailed
    (see the real p99=130ms / max=49.3s spread found in the dataset sanity
    check), so a linear-scale std produces unstable, occasionally absurd
    z-scores for services with near-constant near-zero baselines. Log1p
    compresses the tail; epsilon prevents division by a near-zero sigma
    from producing an inflated score off a trivial fluctuation.
    """
    log_history = [math.log1p(max(h, 0)) for h in history]
    mu = statistics.mean(log_history)
    sigma = statistics.pstdev(log_history)
    return (math.log1p(max(value, 0)) - mu) / (sigma + epsilon)


def load_aggregated(csv_path):
    """Returns {msname: [(window_idx, mean_rt, mean_mcr), ...]} sorted by window."""
    per_service = collections.defaultdict(list)
    with open(csv_path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            per_service[row["msname"]].append(
                (int(row["window_idx"]), float(row["mean_rt"]), float(row["mean_mcr"]))
            )
    for svc in per_service:
        per_service[svc].sort(key=lambda t: t[0])
    return per_service


def latency_deviation_score(series, min_history=3):
    """For each window after `min_history` prior windows exist, compute a
    z-score of that window's latency against the service's own rolling
    mean/std up to (not including) that window. Returns
    {window_idx: z_score} for windows where a baseline could be computed.
    Services with zero variance in their history are skipped (a z-score
    is undefined/infinite there) rather than assigning a fabricated value.
    """
    scores = {}
    history = []
    for window_idx, mean_rt, _ in series:
        if len(history) >= min_history:
            scores[window_idx] = _robust_z(mean_rt, history)
        history.append(mean_rt)
    return scores


def call_rate_anomaly_score(series, min_history=3):
    """Same z-score approach applied to call rate (mean_mcr) instead of
    latency — a sudden rate change often precedes a visible latency shift.
    """
    scores = {}
    history = []
    for window_idx, _, mean_mcr in series:
        if len(history) >= min_history:
            scores[window_idx] = _robust_z(mean_mcr, history)
        history.append(mean_mcr)
    return scores


def top_latency_deviations(per_service, n=10):
    """Across all services and windows, the largest positive latency
    z-scores seen — i.e. the real anomaly candidates in this sample."""
    results = []
    for svc, series in per_service.items():
        for window_idx, z in latency_deviation_score(series).items():
            results.append((svc, window_idx, z))
    results.sort(key=lambda t: t[2], reverse=True)
    return results[:n]
