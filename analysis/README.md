# Study 3 analysis and external replication

This folder holds the code and results behind the EMSE paper *Burn-Rate Alerts Page After the Breach*.

| File | Role | Status |
|---|---|---|
| `score3.py`, `method_src/`, `tests/` | Study 3 scorer and its invariant tests | Registered: SHA-256 prefix `0b6319aef5a575ba` (osf.io/ujdvs) |
| `qc3.py` | Data-quality checks (no outcomes) | Planned |
| `prep_ext.py` | Reduces RCAEval RE2 cases to compact inputs | Registered with the addendum: `6c94e442f61bc66e` |
| `ext3.py` | Registered replication on RCAEval RE2 | Registered with the addendum: `9d571ce64071f4a1` |
| `mech.py` | Burn-rate mechanism decomposition (paper Fig. 2) | Exploratory |
| `guide.py` | Operating curves and threshold sweep (paper Fig. 3) | Exploratory |
| `make_figs.py` | Paper figures from `results/` | — |
| `STUDY3_ADDENDUM_External_Validation.md` | Registered replication plan | Registered on OSF, 2026-11-09 |
| `results/` | Scored outputs (JSON/CSV) for every analysis in the paper | — |

`prep_ext.py` and `ext3.py` are kept byte-identical to the registered versions, so they still contain the absolute paths of the machine they ran on.

## Reproduce
Study 3 data: the `c3-data-42537195202` and `c3r-data-42644788592` releases of this repository. Unpack both into one folder; where both contain a run, use the rerun's files.
```
pip install numpy pandas scipy scikit-learn matplotlib
cd analysis
python3 -m pytest -q tests                              # invariant tests
python3 qc3.py RUNDIR                                   # data quality
python3 score3.py RUNDIR results/primary.json           # confirmatory (H4-H8)
python3 score3.py RUNDIR results/w15.json --window 15   # secondary
python3 score3.py RUNDIR results/s1.json --sampling 1   # secondary
python3 score3.py RUNDIR results/load.json --block load # secondary
POOLED=1 python3 score3.py RUNDIR results/pooled.json   # Study 2-style thresholds
python3 mech.py RUNDIR results/primary.json results/mech_primary.csv
python3 guide.py RUNDIR results/guide.json
python3 make_figs.py results figs
```
`results/noreset.json` is `score3.py` run on RUNDIR without the `reset_ramp` runs.

**Replication.** Download RE2-OB, RE2-SS and RE2-TT from Zenodo (10.5281/zenodo.14590730). Run `prep_ext.py SYSTEM SRC PREPDIR` for each system, then `ext3.py PREPDIR results/ext.json`. `ext3.py` imports `score3.py` and `method_src/` from the path in its first lines; edit that line, or copy this folder to that path.
