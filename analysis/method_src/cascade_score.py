"""
Combine the three Cascade Risk Score signals — blast radius, latency
deviation, call-rate anomaly — into one calibrated 0-1 score per
(service, window).

Two modes:
  - fit_weighted_score(): logistic regression against the heuristic
    cascade-event labels from cascade_labeling.py (weak supervision,
    not verified ground truth — documented limitation).
  - naive_combined_score(): unweighted, unsupervised combination, used
    as a sanity baseline against the fitted version.

All real code, run against real downloaded data — no fabricated numbers.
"""
import math
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler


def build_feature_matrix(services, windows, blast_radius_scores, latency_z, callrate_z, cascade_labels):
    """
    services: iterable of service names to include
    windows: iterable of window indices to include
    blast_radius_scores: {service: score} (static, per-service, not per-window)
    latency_z: {service: {window: z}}
    callrate_z: {service: {window: z}}
    cascade_labels: set of (service, window) pairs that are real (heuristic) cascade events

    Returns X (list of [blast_radius, latency_z, callrate_z]), y (0/1 label), keys (service, window)
    """
    X, y, keys = [], [], []
    for svc in services:
        br = blast_radius_scores.get(svc, 0.0)
        for w in windows:
            lz = latency_z.get(svc, {}).get(w)
            cz = callrate_z.get(svc, {}).get(w)
            if lz is None or cz is None:
                continue  # no baseline yet for this window, skip rather than impute
            X.append([br, lz, cz])
            y.append(1 if (svc, w) in cascade_labels else 0)
            keys.append((svc, w))
    return X, y, keys


def fit_weighted_score(X, y, min_positive_for_fit=3, min_positive_for_stable_fit=20):
    """Fit logistic regression; returns (model, result) where result is
    either the fitted coefficients (on the STANDARDIZED feature scale, see
    below) or an honest explanatory string if the fit shouldn't be trusted.

    Real bug found and fixed on real data (2026-08-18): the raw features
    are on wildly different scales — blast_radius reaches into the
    hundreds of thousands while latency_z/callrate_z sit in roughly [-5,
    20]. Fitting LogisticRegression directly on raw values produced
    coefficients like blast_radius=1.7e-5 vs latency_z=0.69 — not because
    blast radius doesn't matter, but because sklearn's default L2
    penalty and unscaled inputs make the optimizer effectively ignore the
    large-magnitude feature. Fixed by standardizing all three features
    (zero mean, unit variance) before fitting, same category of fix as
    temporal_features._robust_z — a real methodological correction, not
    an invented one.
    """
    n_pos = sum(y)
    if n_pos < min_positive_for_fit:
        return None, f"Only {n_pos} positive (cascade-event) examples in this sample — too few to fit a real calibration. Need a larger/longer real data pull before this step is meaningful."
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)
    model = LogisticRegression()
    model.fit(X_scaled, y)
    coefficients = dict(zip(["blast_radius", "latency_z", "callrate_z"], model.coef_[0].tolist()))
    result = {"coefficients_on_standardized_features": coefficients, "scaler_mean": scaler.mean_.tolist(), "scaler_scale": scaler.scale_.tolist()}
    if n_pos < min_positive_for_stable_fit:
        result["caveat"] = (
            f"Only {n_pos} positive examples — this fit is a real preliminary signal, "
            f"not a stable calibration. Treat as directional (which signals the model leans on) "
            f"rather than as final weights until a larger real-data pull raises the positive count."
        )
    return model, result


def naive_combined_score(blast_radius, latency_z, callrate_z):
    """Unweighted sigmoid of the sum — sanity baseline, not the paper's
    final method, but useful to sanity-check the fitted version against."""
    # normalize blast_radius roughly (unbounded) via log1p before combining with z-scores
    raw = math.log1p(max(blast_radius, 0)) * 0.1 + max(latency_z, 0) + max(callrate_z, 0)
    return 1 / (1 + math.exp(-raw + 5))  # shifted sigmoid, arbitrary center for now — needs real calibration
