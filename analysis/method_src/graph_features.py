"""
Blast-radius (call-graph centrality) feature extraction.

Input: Alibaba cluster-trace-microservices-v2022 CallGraph CSV
       (schema: timestamp,traceid,service,rpc_id,rpctype,um,uminstanceid,
                interface,dm,dminstanceid,rt)

This module builds a weighted directed call graph (um -> dm, weighted by
call count) for a given time window and computes a blast-radius score per
service: how many downstream services depend on it, weighted by how often
they're actually called (not just graph reachability).

No fabricated data anywhere in this file — every function operates on
real CallGraph rows and is validated against a real downloaded sample in
tests/test_graph_features.py.
"""
import csv
import collections


SENTINEL_CALLERS = {"UNKNOWN", "USER"}  # entry-point markers in the trace, not real services


def build_call_graph(csv_path, max_rows=None):
    """Build a weighted directed graph {um: {dm: call_count}} from a real
    CallGraph CSV slice. Sentinel entry-point callers (UNKNOWN/USER) are
    excluded from the *caller* side since they aren't real services, but
    their calls still count toward the callee's inbound traffic elsewhere
    if needed later.
    """
    graph = collections.defaultdict(collections.Counter)
    rows = 0
    with open(csv_path) as f:
        reader = csv.reader(f)
        next(reader)  # header
        for row in reader:
            if max_rows and rows >= max_rows:
                break
            rows += 1
            try:
                _, _, _, _, _, um, _, _, dm, _, _ = row
            except ValueError:
                continue  # malformed row, skip rather than guess
            if um in SENTINEL_CALLERS:
                continue
            graph[um][dm] += 1
    return graph


def load_aggregated_edges(csv_path):
    """Load a pre-aggregated edge-list CSV (columns: um,dm,call_count) —
    call counts summed across multiple real CallGraph windows that were
    downloaded and aggregated incrementally (see
    scripts/download_callgraph_matched.sh). Returns the same
    {um: {dm: call_count}} structure build_call_graph() produces from raw
    per-call rows, so blast_radius()/top_n() work unchanged on either
    input. Used to build a call graph from a real time range that MATCHES
    the time range of a separately-aggregated MSRTMCR pull, instead of a
    single independent snapshot window.
    """
    graph = collections.defaultdict(collections.Counter)
    with open(csv_path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            graph[row["um"]][row["dm"]] += int(row["call_count"])
    return graph


def blast_radius(graph):
    """Per-service blast radius: call-frequency-weighted out-degree.

    A simple, interpretable first pass — how much downstream call volume
    does this service directly generate. Deliberately NOT full PageRank-
    style multi-hop propagation for this first version: interpretability
    matters for an ops-facing score, and multi-hop centrality is a
    documented next iteration once the single-hop version is validated
    against real labeled cascades.
    """
    scores = {}
    for um, downstream in graph.items():
        total_calls = sum(downstream.values())
        distinct_downstream = len(downstream)
        # weight distinct fan-out by call volume so a service calling one
        # downstream service 1000x/window doesn't outrank one legitimately
        # fanning out to 20 different downstream services
        scores[um] = distinct_downstream * (total_calls ** 0.5)
    return scores


def top_n(scores, n=10):
    return sorted(scores.items(), key=lambda kv: kv[1], reverse=True)[:n]
