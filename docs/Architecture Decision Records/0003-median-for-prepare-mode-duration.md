# Median instead of mean for prepare-mode visit duration

The prepare-mode duration metric (`median_prepare_minutes`) uses the median rather than the mean, both at the per-user level (median of a user's individual prepare-only visits) and at the org level (median of user medians).

Prepare-mode visits have a strongly skewed distribution: most therapists spend a few minutes reviewing content, but occasional outliers — a therapist spending an hour editing — inflate the mean dramatically. A high mean signals a usability issue only if the median is also elevated; a high mean with a low median means one person had a bad day. Median surfaces this distinction.

Deliver-mode (Real Session) duration retains the mean because the signal of interest there is total engagement, not individual anomaly detection.

## Considered options

- **Mean at both levels (previous behaviour)**: simple to compute and explain, but masks outliers that indicate prepare-mode usability problems. Rejected for prepare mode.
- **Median at user level, mean at org level**: avoids double-median but reintroduces skew at the org level when one user has an extreme median. Rejected — inconsistent with the stated goal.
- **Median at both levels (chosen)**: consistent aggregation, preserves the outlier-detection property through to the org summary. The column is renamed `median_prepare_minutes` to accurately reflect the statistic.
