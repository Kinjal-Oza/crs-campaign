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
