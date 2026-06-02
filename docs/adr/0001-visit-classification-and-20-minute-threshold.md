# Visit classification and 20-minute real-session threshold

Matomo tracks browser sessions (visits), not CST therapy session durations directly. To distinguish genuine therapy delivery from brief check-ins and browsing, we classify deliver visits by duration: visits over 20 minutes are treated as Real Sessions; visits 20 minutes or under are treated as Short Visits (prep/browsing). The 20-minute threshold was chosen as the minimum plausible duration for a meaningful CST session delivery — shorter than that and the therapist is most likely checking the app, not running a session.

Mixed visits — where a therapist prepares and then delivers in the same browser session — are classified as deliver visits, not prepare-only. The alternative (excluding mixed visits from both categories, or splitting their duration by mode) would require new tracking (explicit mode-start/end events with timestamps), which does not currently exist.

## Considered options

- **CST session duration** (first action to last action per `bundle_id + session_id`): more precise, but requires reconstructing timelines from action sequences across potentially multiple visits. Not pursued due to complexity.
- **Exclude mixed visits**: would silently drop valid session data for therapists who prepare and deliver in one sitting. Rejected.
- **15-minute threshold**: considered too short — a real CST session with setup overhead is unlikely to fit in under 15 minutes. 20 minutes was the team's working estimate.
