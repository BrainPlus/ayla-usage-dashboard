# Raw visit durations for org-level min/max real session time

The min/max real session duration columns (`min_real_session_minutes`, `max_real_session_minutes`) in the By Organisation table are computed from **raw individual visit durations**, not from per-user averages.

The existing aggregation pipeline first computes a per-user average visit duration in `_build_visit_duration_metrics`, then averages those per-user averages at the org level. Using that same pipeline for min/max would yield the min/max of user averages — a user whose two sessions lasted 30 and 90 minutes would contribute "60 minutes" to the org min/max, hiding the 90-minute outlier. The stated purpose of the min/max columns is to surface outliers like a single two-hour session dragging up the mean; only raw visit durations can do that.

The same >20-minute Real Session filter applies: only deliver visits over 20 minutes are included in the min/max calculation.

## Considered options

- **Min/max of per-user averages**: simpler — no change to `build_org_summary`'s inputs needed. But hides within-user outliers and defeats the purpose of the feature. Rejected.
- **Raw visit durations (chosen)**: requires `build_org_summary` to accept a new `visit_durations` parameter and join it with the user→org mapping from `user_detail`. More complex, but the only way to expose the actual extreme values per organisation.
