"""
Drop-in, numerically-equivalent, O(n) reimplementation of
temporal_features.latency_deviation_score / call_rate_anomaly_score for
larger window counts (150 vs the original 18) where the original's
O(n^2) per-service recomputation of statistics.mean/pstdev on a growing
history list becomes too slow. Same _robust_z formula (log1p transform,
epsilon-floored pstdev), just computed via a running sum/sum-of-squares
instead of recomputing over the full history list each step. Verified
against the original module's output on the original 18-window data
before use on the full 150-window pull (see verify_equivalence.py).
"""
import math


def _robust_z_incremental(value, n, sum_log, sumsq_log, epsilon=0.5):
    mu = sum_log / n
    var = sumsq_log / n - mu * mu
    if var < 0:
        var = 0.0  # float noise guard
    sigma = math.sqrt(var)
    return (math.log1p(max(value, 0)) - mu) / (sigma + epsilon)


def _score_series(series, value_index, min_history=3):
    """series: sorted [(window_idx, mean_rt, mean_mcr), ...]
    value_index: 1 for latency (mean_rt), 2 for call-rate (mean_mcr)
    """
    scores = {}
    n = 0
    sum_log = 0.0
    sumsq_log = 0.0
    for row in series:
        window_idx = row[0]
        value = row[value_index]
        if n >= min_history:
            scores[window_idx] = _robust_z_incremental(value, n, sum_log, sumsq_log)
        lv = math.log1p(max(value, 0))
        sum_log += lv
        sumsq_log += lv * lv
        n += 1
    return scores


def latency_deviation_score(series, min_history=3):
    return _score_series(series, 1, min_history)


def call_rate_anomaly_score(series, min_history=3):
    return _score_series(series, 2, min_history)
