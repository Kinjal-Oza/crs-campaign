"""Figures for paper v4 from scored Study 3 outputs (and external replication when present)."""
import json, os, sys, pandas as pd, numpy as np, matplotlib
matplotlib.use("Agg"); import matplotlib.pyplot as plt
O = sys.argv[1] if len(sys.argv) > 1 else "results"; F = sys.argv[2] if len(sys.argv) > 2 else "figs"; os.makedirs(F, exist_ok=True)
C = dict(M1="#2a78d6", M6="#eb6834", M10="#1baf7a", M9c="#eda100", M9="#52514e", M2="#6250d6")
INK, MUTED, GRID = "#0b0b0b", "#52514e", "#e4e3df"
plt.rcParams.update({"font.size": 8, "axes.edgecolor": MUTED, "axes.labelcolor": INK, "xtick.color": MUTED, "ytick.color": MUTED,
                     "axes.spines.top": False, "axes.spines.right": False, "font.family": "DejaVu Sans", "pdf.fonttype": 42})
APP = {"social": "Social (sync)", "hotel": "Hotel (sync)", "async": "Social-async (queue)"}

# ---------------- Fig 1: burn-rate mechanism
d = pd.read_csv(f"{O}/mech_primary.csv")
fig, ax = plt.subplots(1, 2, figsize=(7.0, 2.5), gridspec_kw=dict(width_ratios=[1.15, 1]))
a = ax[0]; x = d.bad60_at_onset.clip(upper=0.6) * 100
a.hist(x, bins=np.arange(0, 62, 2.5), color=C["M1"], edgecolor="white", linewidth=1)
a.axvline(14.4, color=INK, lw=1.2, ls="--"); a.axvline(5, color=MUTED, lw=1, ls=":")
Y = a.get_ylim()[1]
a.annotate("burn-rate page needs >14.4%\n(60-s window)", xy=(14.4, Y * 0.80), xytext=(26, Y * 0.80), fontsize=7, va="center", color=INK,
           arrowprops=dict(arrowstyle="-", color=INK, lw=0.6))
a.annotate("p95 SLO breaches when ~5% exceed it", xy=(5, Y * 0.97), xytext=(26, Y * 0.97), fontsize=7, va="center", color=MUTED,
           arrowprops=dict(arrowstyle="-", color=MUTED, lw=0.6))
a.set_xlabel("Requests over the SLO in the 60 s before breach onset (%)"); a.set_ylabel("Breaches")
a.set_title(f"(a) At onset, {int((d.bad60_at_onset <= .144).sum())} of {len(d)} breaches are below the page threshold", fontsize=8, loc="left")
a.yaxis.grid(True, color=GRID, lw=0.6); a.set_axisbelow(True)
b = ax[1]
cats = [("fires (possibly late)", "Pages (after onset)", C["M9"]), ("bad fraction never reaches 14.4%", "Never reaches 14.4%", C["M9c"]),
        ("short window met, 5-min window never reaches 6%", "5-min window < 6%", C["M6"]), ("freshness-only breach (invisible to frontend latency)", "Freshness only", C["M10"])]
apps = ["social", "hotel", "async"]; left = np.zeros(3)
for key, lab, col in cats:
    v = np.array([((d.app == ap) & (d.why == key)).sum() for ap in apps])
    b.barh(range(3), v, left=left, color=col, edgecolor="white", linewidth=2, label=lab, height=0.6)
    for i, (l, w) in enumerate(zip(left, v)):
        if w >= 6: b.text(l + w / 2, i, str(w), ha="center", va="center", fontsize=7, color="white" if col in (C["M9"], C["M1"]) else INK)
    left += v
b.set_yticks(range(3)); b.set_yticklabels([APP[x] for x in apps]); b.invert_yaxis(); b.set_xlabel("Breaches")
b.set_title("(b) What happens to the burn-rate rule", fontsize=8, loc="left")
b.legend(fontsize=6.5, frameon=False, loc="upper center", bbox_to_anchor=(0.45, -0.28), ncol=2)
fig.tight_layout(); fig.savefig(f"{F}/fig_mechanism.pdf", bbox_inches="tight"); plt.close(fig)

# ---------------- Fig 2: operating curves
g = json.load(open(f"{O}/guide.json"))
fig, ax = plt.subplots(1, 3, figsize=(7.0, 2.4), sharey=False)
for a, app in zip(ax, apps):
    for M, lab in (("M1", "CRS (M1)"), ("M6", "Frontend z (M6)"), ("M10", "Isolation Forest (M10)"), ("M9c", "Burn rate, tuned (M9c)")):
        pts = [p for p in g[app][M] if not (M == "M10" and p["early"] == 0 and p["level"] not in ("q0.95", "q0.99", "max"))]
        xs = [p["fa_h"] for p in pts]; ys = [p["early"] for p in pts]
        a.plot(xs, ys, "-o", color=C[M], ms=3.5, lw=1.6, label=lab, mec="white", mew=0.8)
        pm = [p for p in pts if p["level"] == "max"]
        if pm: a.plot(pm[0]["fa_h"], pm[0]["early"], "o", ms=6.5, mfc="white", mec=C[M], mew=1.5)
    p9 = g[app]["M9"][0]; a.plot(p9["fa_h"], p9["early"], "s", color=C["M9"], ms=6, label="Burn rate, SRE workbook (M9)")
    n = g[app]["M1"][0]["breaches"]; a.axhline(n, color=GRID, lw=1); a.text(a.get_xlim()[1] if False else 0.02, n + 1, f"{n} breaches", fontsize=6.5, color=MUTED)
    a.axvline(1.0, color=MUTED, lw=0.8, ls=":")
    a.set_title(APP[app], fontsize=8, loc="left"); a.set_xlabel("False-alarm incidents per hour"); a.set_ylim(-3, n + 8)
    a.yaxis.grid(True, color=GRID, lw=0.6); a.set_axisbelow(True)
ax[0].set_ylabel("Breaches warned before onset")
h, l = ax[0].get_legend_handles_labels(); fig.legend(h, l, loc="lower center", ncol=5, fontsize=6.5, frameon=False, bbox_to_anchor=(0.5, -0.08))
fig.tight_layout(rect=(0, 0.06, 1, 1)); fig.savefig(f"{F}/fig_operating.pdf", bbox_inches="tight"); plt.close(fig)

# ---------------- Fig 3: forest plot of paired differences
rows = []
for tag, f in (("Primary", "primary"), ("15-s windows", "w15"), ("1% sampling", "s1"), ("Without reset faults", "noreset"), ("Pooled thresholds", "pooled")):
    H = json.load(open(f"{O}/{f}.json"))["hypotheses"]
    for h, lab in (("H4", "H4  CRS − frontend z (sync, latency)"), ("H5", "H5  CRS − frontend z (async, freshness-led)"),
                   ("H6", "H6  frontend z − burn rate (all)"), ("H7", "H7  Isolation Forest − frontend z (sync)")):
        t = H[h]["test"]
        if t.get("n"): rows.append(dict(h=lab, cond=tag, mean=t["mean"], lo=t["ci"][0], hi=t["ci"][1], n=t["n"], holds=H[h]["holds"]))
ext = f"{O}/ext.json"
if os.path.exists(ext):
    H = json.load(open(ext))["hypotheses"]
    for h, lab in (("E4", "H4  CRS − frontend z (sync, latency)"), ("E1", "H6  frontend z − burn rate (all)"), ("E3", "H7  Isolation Forest − frontend z (sync)")):
        t = H[h]["test"]
        if t.get("n"): rows.append(dict(h=lab, cond="RCAEval replication", mean=t["mean"], lo=t["ci"][0], hi=t["ci"][1], n=t["n"], holds=H[h]["holds"]))
r = pd.DataFrame(rows); groups = list(dict.fromkeys(r.h)); conds = list(dict.fromkeys(r.cond))
cc = dict(zip(conds, ["#0b0b0b", "#2a78d6", "#1baf7a", "#eda100", "#e87ba4", "#e34948"]))
fig, ax = plt.subplots(figsize=(7.0, 3.6)); y = 0; yt, yl = [], []
for gname in groups:
    sub = r[r.h == gname]
    for _, q in sub.iterrows():
        ax.plot([q.lo, q.hi], [y, y], color=cc[q.cond], lw=1.8, solid_capstyle="round")
        ax.plot(q["mean"], y, "o", color=cc[q.cond], ms=5, mec="white", mew=0.8, mfc=cc[q.cond] if q.holds else "white")
        ax.text(205, y, f"n={q.n}", fontsize=6.5, va="center", color=MUTED); y -= 1
    yt.append(y + len(sub) / 2 + 0.5); yl.append(gname); y -= 0.8
ax.axvline(0, color=MUTED, lw=0.8); ax.axvspan(-15, 15, color="#f0efec", zorder=0)
ax.set_yticks(yt); ax.set_yticklabels(yl, fontsize=7.5); ax.set_xlim(-90, 200)
ax.set_xlabel("Mean paired difference in warning time (s); positive = first detector earlier.  Shaded: ±15-s equivalence margin")
for c in conds: ax.plot([], [], "-o", color=cc[c], label=c, ms=4)
ax.legend(fontsize=6.5, frameon=False, loc="lower right"); ax.tick_params(axis="y", length=0)
ax.xaxis.grid(True, color=GRID, lw=0.6); ax.set_axisbelow(True)
fig.tight_layout(); fig.savefig(f"{F}/fig_forest.pdf", bbox_inches="tight"); plt.close(fig)
print("ok", len(r))
