# Ayla Usage Dashboard

Analytics dashboard for the Ayla CST Assistant product team. Combines Matomo visit data with PostgreSQL user and organisation data to report on therapist engagement and therapy session delivery.

## Language

### Product

**Organisation**:
A care provider (e.g. a care home) that has an account on Ayla. The unit of commercial and operational reporting.
_Avoid_: Account, client, customer

**Bundle**:
A configured sequence of CST therapy sessions created by a therapist for a specific patient group. Called "group" in the therapist-facing UI. The number of configured sessions varies by bundle.
_Avoid_: Group (ambiguous with patient group)

**CST Session**:
One configured therapy session within a bundle, delivered live to a group of patients. Identified by a `(bundle_id, session_id)` pair in Matomo and the database.
_Avoid_: Session (overloaded — see also Matomo Visit)

**Prepare Mode**:
A therapist editing or reviewing CST session content before delivery. Tracked in Matomo as `dimension10 == true`.
_Avoid_: Edit mode

**Deliver Mode**:
A therapist running a live CST session with patients. Tracked in Matomo as `dimension10 == false`. All session-level metrics are scoped to deliver mode only.
_Avoid_: Live mode

**Active User**:
A user with 2 or more Matomo visits in the selected reporting period. The threshold of 2 is fixed regardless of period length and serves as a minimum-engagement signal.
_Avoid_: Engaged user, retained user

**Daily Visit Activity**:
A chart in the Global Overview tab showing the count of Matomo visits and unique users for each calendar day in the selected reporting period. Uses `serverDate` (visit start date) for bucketing; visits without a `serverDate` are excluded. Days with no visits are shown with zero counts.
_Avoid_: Daily Login Activity (a Matomo visit does not prove an authentication event occurred)

**Reporting Period**:
The user-selected date range (From / To) applied to all period-based metrics — logins, completed sessions, visit durations, activity completions, and star ratings. Lifetime metrics (total registered users, total bundles created) are not period-scoped. Default is the previous 90 days.
_Avoid_: Date range, 30-day window, 90-day window

### Analytics

**Matomo Visit**:
One continuous browser session, from login to close or timeout. A single visit may contain both prepare-mode and deliver-mode actions. Distinct from a CST Session.
_Avoid_: Session (overloaded), login (imprecise)

**Deliver Visit**:
A Matomo visit that contains at least one deliver-mode action (`dimension10 == false`). Mixed visits — where a therapist prepares and then delivers in the same browser session — are classified as deliver visits.
_Avoid_: Delivered session (reserved for CST Sessions)

**Prepare-Only Visit**:
A Matomo visit with no deliver-mode actions; all actions are in prepare mode.

**Real Session**:
A deliver visit with a duration greater than 20 minutes. Treated as a genuine therapy session delivery for reporting purposes.
_Avoid_: Full session, delivered visit

**Short Visit**:
A deliver visit with a duration of 20 minutes or under. Treated as prep or browsing behaviour, not a genuine session delivery.
_Avoid_: Partial session, brief session

**Activity**:
A discrete content unit within a CST Session, belonging to one of five slots: intro, warmup, reality orientation (RO), main, or outro. Each activity has a unique ID in Squidex (the CMS) that is locale-specific — the same conceptual activity in different languages carries a different Squidex ID. Tracked in Matomo as `dimension6` (activityId). An activity is considered completed when a therapist navigates forward past it (firing an `Activity Complete` event); this is a known limitation — rapid forward navigation also triggers the event.
_Avoid_: Step (a sub-unit within an activity), exercise

**Step**:
A sub-unit within an Activity, containing one or more Talking Points. Therapists navigate between steps using the forward/back controls; completing the last Talking Point in a step fires a `Step Complete` event. Tracked in Matomo as `dimension7` (stepId).
_Avoid_: Screen, slide

**Talking Point**:
The finest navigable unit in a delivered CST Session — a single prompt card within a Step. A therapist advancing past a Talking Point fires a `Step Forward Click` event (`category='Activity'`). The time a therapist spends on a Talking Point is approximated as the delta between consecutive `Step Forward Click` events within a Matomo visit.
_Avoid_: Prompt (informal), card, slide
