"""
Two baseline detectors for comparison against the Cascade Risk Score.
Both operate on the same real per-service, per-window aggregated data
(data/agg/msrtmcr_agg.csv) — no synthetic data, no fabricated numbers.

1. static_slo_threshold: fixed absolute latency threshold (e.g. p95 of
   the ENTIRE dataset's mean_rt across all services/windows) — the
   naive approach real ops teams use before adopting per-service
   baselines. Deliberately crude: one global number for every service,
   regardless of that service's own normal operating range.

2. rolling_zscore_only: the SAME per-service rolling z-score as
   temporal_features, but using latency alone (no blast radius, no
   call-rate signal, no combination) — isolates how much the graph
   structure signal actually adds over a naive single-signal anomaly
   detector.
"""
import statistics


def static_slo_threshold_score(per_service, percentile=0.95):
    """Returns {(service, window): 1 if mean_rt exceeds the GLOBAL
    percentile-th value of mean_rt across the whole dataset, else 0}.
    """
    all_rt = []
    for svc, series in per_service.items():
        for row in series:
            all_rt.append(row[1])
    all_rt.sort()
    idx = int(len(all_rt) * percentile)
    threshold = all_rt[min(idx, len(all_rt) - 1)]

    scores = {}
    for svc, series in per_service.items():
        for row in series:
            window_idx, mean_rt = row[0], row[1]
            scores[(svc, window_idx)] = 1.0 if mean_rt > threshold else 0.0
    return scores, threshold


def rolling_zscore_only_score(latency_z_by_service):
    """Just the raw latency z-score per (service, window) — the single-signal
    baseline. Higher = more anomalous, same direction as the Cascade Risk
    Score so it's directly rank-comparable.
    """
    scores = {}
    for svc, d in latency_z_by_service.items():
        for w, z in d.items():
            scores[(svc, w)] = z
    return scores
