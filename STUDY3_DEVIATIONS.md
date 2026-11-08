# Study 3: deviations from the registered plan (osf.io/ujdvs)
Each entry is recorded before the data it affects are scored.

1. **2026-11-08 — first full run lost before scoring.** In the first full campaign (GitHub Actions run 42515669236, started 19:33 UTC), every shard completed its runs, but the final upload to Kaggle failed with an authentication error: the Kaggle API token stored as a repository secret was no longer valid. The run data existed only on the ephemeral runners, so it was never seen or scored.
   - **Fix:** the workflow now checks Kaggle credentials before running, keeps every shard's output as a GitHub artifact (90-day retention) in addition to Kaggle, and retries the upload.
   - **Rerun:** the campaign is rerun in full with the identical plan, seeds, harness and scorer.
   - **Effect on design and analysis:** none.
