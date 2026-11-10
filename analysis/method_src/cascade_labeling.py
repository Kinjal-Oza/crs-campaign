"""
Cascade-event labeling — real ground truth for evaluation, since the
Alibaba trace has no built-in incident labels (confirmed by reading the
dataset README directly; this is a documented, not assumed, gap).

Definition used (documented explicitly, per the research plan and TNSM
paper's Dataset/Method sections): a cascade event at window w is any
service whose downstream call-graph neighbors include >=3 distinct
services that ALSO show a latency-deviation z-score > threshold within
the same window w or the immediately following window w+1.

This is a heuristic proxy, not verified ground truth from a real incident
log (the trace doesn't have one) — that limitation must be stated
explicitly in the paper's Limitations section, not hidden.
"""
import collections


def label_cascade_events(graph, latency_z_by_service, z_threshold=3.0, min_downstream=3):
    """
    graph: {um: {dm: call_count}} from graph_features.build_call_graph
    latency_z_by_service: {msname: {window_idx: z_score}} from
        temporal_features.latency_deviation_score, one entry per service

    Returns: list of (upstream_service, window_idx, affected_downstream_count,
                       affected_downstream_services)
    """
    events = []
    for um, downstream in graph.items():
        um_z = latency_z_by_service.get(um, {})
        for window_idx, z in um_z.items():
            if z <= z_threshold:
                continue
            affected = []
            for dm in downstream:
                dm_z = latency_z_by_service.get(dm, {})
                # same window or the next one — cascades take a beat to propagate
                if dm_z.get(window_idx, -999) > z_threshold or dm_z.get(window_idx + 1, -999) > z_threshold:
                    affected.append(dm)
            if len(affected) >= min_downstream:
                events.append((um, window_idx, len(affected), affected))
    return events
