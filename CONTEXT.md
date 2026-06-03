# Ayla Usage Dashboard

Analytics dashboard for the Ayla CST Assistant product team. Combines Matomo visit data with PostgreSQL user and organisation data to report on therapist engagement and therapy session delivery.

## Language

### Product

**Organisation**:
A care provider (e.g. a care home) that has an account on Ayla. The unit of commercial and operational reporting.
_Avoid_: Account, client, customer

**Bundle**:
A group of 14 fixed CST therapy sessions created by a therapist for a specific patient group. Called "group" in the therapist-facing UI.
_Avoid_: Group (ambiguous with patient group)

**CST Session**:
One of the 14 fixed therapy sessions within a bundle, delivered live to a group of patients. Identified by a `(bundle_id, session_id)` pair in Matomo and the database.
_Avoid_: Session (overloaded — see also Matomo Visit)

**Prepare Mode**:
A therapist editing or reviewing CST session content before delivery. Tracked in Matomo as `dimension10 == true`.
_Avoid_: Edit mode

**Deliver Mode**:
A therapist running a live CST session with patients. Tracked in Matomo as `dimension10 == false`. All session-level metrics are scoped to deliver mode only.
_Avoid_: Live mode

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
