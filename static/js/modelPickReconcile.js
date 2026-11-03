// A sessions list fetched while the user was switching models can predate the
// PATCH that saves the switch: reply-completion handlers call loadSessions(), the
// server may answer before the PATCH commits, and the stale model then replaces
// the one just picked (picker label shows the old model; the chat itself is fine
// because the server did get the PATCH). This puts the pick back on that list.
//
// `pick` is window.__odysseusLastPickedRoute, set by the model picker:
//   { model, endpoint_url, endpoint_id, session_id, persisted, done_at }
// `switchPending` is true while a pick's PATCH is still in flight.
export function keepRecentModelPick(sessions, fetchStartedAt, pick, switchPending) {
  if (!Array.isArray(sessions) || !pick || !pick.session_id || !pick.model) return sessions;
  // The response is only suspect if it was requested before the PATCH finished.
  const overlaps = switchPending || (pick.persisted && fetchStartedAt <= pick.done_at);
  if (!overlaps) return sessions;
  const cur = sessions.find(s => s && s.id === pick.session_id);
  if (cur && cur.model !== pick.model) {
    cur.model = pick.model;
    cur.endpoint_url = pick.endpoint_url || cur.endpoint_url;
    cur.endpoint_id = pick.endpoint_id || cur.endpoint_id;
  }
  return sessions;
}
