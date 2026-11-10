# Study 3: deviations from the registered plan (osf.io/ujdvs)
Each entry is recorded before the data it affects are scored.

1. **2026-11-08 — first full run lost before scoring.** In the first full campaign (GitHub Actions run 42515669236, started 19:33 UTC), every shard completed its runs, but the final upload to Kaggle failed with an authentication error: the Kaggle API token stored as a repository secret was no longer valid. The run data existed only on the ephemeral runners, so it was never seen or scored.
   - **Fix:** the workflow now checks Kaggle credentials before running, keeps every shard's output as a GitHub artifact (90-day retention) in addition to Kaggle, and retries the upload.
   - **Rerun:** the campaign is rerun in full with the identical plan, seeds, harness and scorer.
   - **Effect on design and analysis:** none.

2. **2026-11-09 — runs not completed in the full campaign are rerun.** In run 42537195202, 456 of 492 planned runs completed. 36 did not: 3 social-network runs (plan indices 69, 111, 121) and 33 asynchronous-app runs.
   - Most of the asynchronous runs were never started: four shards hit the 350-minute job limit after repeated health-gate restarts. A few failed twice in place.
   - **Rerun:** the 36 runs are rerun once each on fresh runners, with the identical plan, seeds, harness and scorer, by workflow `campaign3_rerun.yml` (`ONLY` = plan indices, spread over 12 jobs).
   - **Timing:** no Study 3 result has been scored or inspected; only completeness and run logs were checked.
   - **Reporting:** runs that still fail are reported by plan index and reason, as STUDY3_PLAN.md section 8 requires.
   - **Outcome (2026-11-09):** the rerun (run 42644788592) completed 34 of the 36 runs. Two failed both attempts and are missing from the analysis: asynchronous app, plan index 130 (`reset_ramp`, write-home-timeline-rabbitmq, repetition 2, 100 req/s) and plan index 160 (`net_ramp`, compose-post-service, repetition 1, 200 req/s). The analysed data are 490 runs: 395 in the primary block (12 calibration) and 95 in the load block.
   - **Data handling:** jobs that timed out had left partial request, resource and probe files for runs with no result record. When the rerun's files were merged, those partial files were replaced by the rerun's complete files before scoring. The data-quality check (`analysis/qc3.py`) found the problem as zero achieved rates; it was fixed before any outcome was computed.

## External replication (separate registration)
The addendum `analysis/STUDY3_ADDENDUM_External_Validation.md` (OSF, registered 2026-11-09) pre-specified a replication on RCAEval RE2. It was run once, after registration, with `analysis/prep_ext.py` and `analysis/ext3.py` unchanged. No deviations.
