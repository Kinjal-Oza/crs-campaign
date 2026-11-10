"""Invariant tests for the Study 3 scorer (score3.py). Run: python3 -m pytest -q tests/
Optional: CRS_DRY3=<Study 2 data in Study 3 layout> checks exact reproduction of Study 2 with pooled thresholds."""
import os, sys, json, gzip, tempfile, subprocess
import numpy as np, pandas as pd, pytest
H = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, H)
import score3 as S3

T0 = 2_000_000.0
def run(d, rid, app="async", lat=lambda t: 8.0, fresh=lambda t: 0.3, seen=lambda t: 1, front_rt=lambda t: 5.0, seed=0, n_users=1):
    rng = np.random.default_rng(seed); ts = np.sort(rng.uniform(0, 660, 100 * 660))
    pd.DataFrame(dict(t=T0 + ts, endpoint="home", status=200, lat_ms=[lat(t) * rng.uniform(.8, 1.2) for t in ts])).to_csv(f"{d}/{rid}.req.csv", index=False)
    pt = np.arange(0, 660, 5.0)
    pd.DataFrame(dict(t=T0 + pt, status=200, fresh_s=[fresh(t) for t in pt], seen=[seen(t) for t in pt])).to_csv(f"{d}/{rid}.fresh.csv", index=False)
    fr = S3.FRONT[app]; rows = []
    for i, t in enumerate(ts[::10]):
        tid = f"{i:016x}"
        rows.append(((T0 + t) * 1000, tid, "x", tid, "USER", "http", fr, "op", front_rt(t)))
        rows.append(((T0 + t) * 1000, tid, "x", tid + "a", fr, "rpc", "svc-a", "op", 2.0 * rng.uniform(.8, 1.2)))
    with gzip.open(f"{d}/{rid}.cg.csv.gz", "wt") as f:
        pd.DataFrame(rows, columns=["timestamp", "traceid", "service", "rpc_id", "um", "rpctype", "dm", "interface", "rt"]).to_csv(f, index=False)
    m = dict(run=rid, app=app, fault="net_ramp", target="svc-a", t0=T0); json.dump(m, open(f"{d}/{rid}.json", "w")); return m

@pytest.fixture(scope="module")
def d(): return tempfile.mkdtemp()

def test_quiet_run_has_no_breach(d):
    t = S3.truth(d, run(d, "q")); assert not t["breach"] and t["fresh_slo_s"] == 2.0 and t["lat_slo_ms"] == 100.0

def test_freshness_led_breach(d):
    t = S3.truth(d, run(d, "f", fresh=lambda s: 6.0 if s >= 360 else 0.3))
    assert t["breach"] and t["fresh_onset_bin"] == 12 and t["lat_onset_bin"] is None and t["type"] == "freshness" and t["freshness_led"]

def test_unseen_post_is_a_breach(d):
    t = S3.truth(d, run(d, "u", seen=lambda s: 0 if 400 <= s < 405 else 1)); assert t["fresh_onset_bin"] == 13

def test_latency_first_then_freshness(d):
    t = S3.truth(d, run(d, "lf", lat=lambda s: 400 if s >= 300 else 8, fresh=lambda s: 6 if s >= 420 else 0.3))
    assert t["type"] == "latency" and t["onset_bin"] == 10 and not t["freshness_led"]

def test_burn_rate_rule(d):
    """M9 fires only when both the 60-s and 300-s burn rates exceed their limits."""
    f = S3.features(d, run(d, "b", front_rt=lambda s: 300.0 if s >= 400 else 5.0), 30)
    s = S3.window_scores(f, "M9"); first = min(b for b, v in s.items() if v == 1.0)
    assert first * 30 + 30 >= 418 and all(v == 0 for b, v in s.items() if b * 30 + 30 <= 400)
    c = S3.window_scores(f, "M9c"); assert c[13] > 14.4 and c[5] == 0

def test_one_percent_subsample(d):
    run(d, "s1"); m = json.load(open(f"{d}/s1.json"))
    f10, f1 = S3.features(d, m, 30, 10), S3.features(d, m, 30, 1)
    n10 = sum(n for (b, rt, n) in f10["series"]["svc-a"]); n1 = sum(n for (b, rt, n) in f1["series"]["svc-a"])
    assert 0.07 < n1 / n10 < 0.13

def test_scores_are_causal(d):
    m = run(d, "c", front_rt=lambda s: 50.0 if s >= 420 else 5.0); c = pd.read_csv(f"{d}/c.cg.csv.gz")
    with gzip.open(f"{d}/c2.cg.csv.gz", "wt") as fh: c[c.timestamp / 1000 - T0 < 13 * 30].to_csv(fh, index=False)
    json.dump(dict(m, run="c2"), open(f"{d}/c2.json", "w"))
    for M in ("M1", "M2", "M5", "M6", "M9", "M9c"):
        a = S3.window_scores(S3.features(d, m, 30), M); b = S3.window_scores(S3.features(d, dict(m, run="c2"), 30), M)
        assert all(abs(a[k] - b[k]) < 1e-12 for k in b if k <= 11), M

def test_internal_only_ignores_frontend(d):
    a = S3.features(d, run(d, "i1", front_rt=lambda s: 5.0, seed=9), 30); b = S3.features(d, run(d, "i2", front_rt=lambda s: 80.0 if s > 300 else 5.0, seed=9), 30)
    assert S3.window_scores(a, "M1int") == S3.window_scores(b, "M1int") and S3.window_scores(a, "M6") != S3.window_scores(b, "M6")

def test_scorer_is_the_registered_version():
    """SHA-256 prefix recorded before the OSF deposit (2026-11-04)."""
    import hashlib
    assert hashlib.sha256(open(os.path.join(H, "score3.py"), "rb").read()).hexdigest()[:16] == "0b6319aef5a575ba"

@pytest.mark.skipif(not os.environ.get("CRS_DRY3"), reason="set CRS_DRY3 to Study 2 data in Study 3 layout")
def test_reproduces_study2_with_pooled_thresholds(tmp_path):
    out = tmp_path / "o.json"
    subprocess.run([sys.executable, f"{H}/score3.py", os.environ["CRS_DRY3"], str(out)], check=True, capture_output=True, env=dict(os.environ, POOLED="1"))
    a = json.load(open(out)); S = json.load(open(os.path.join(H, "..", "results", "score2_campaign2.json")))
    for M in ("M1", "M2", "M5", "M6", "M8"):
        L = sorted(v for k, v in a["methods"][M]["prereg"]["lead"].items() if k.endswith("|lat") and v is not None)
        assert L == sorted(S["methods"][M]["lead_s"]), M
