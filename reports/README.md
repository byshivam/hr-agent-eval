# Reports

- `latest.md` / `latest.json` — written by every run of `python -m evals.run_eval` (git-ignored).
- `baseline.json` — the approved run that later runs are compared against. Create it with `--update-baseline` after a run you are happy with, and commit it.

In CI, every run's report is also kept on the `eval-reports` branch.
