// Frees local model RAM when the user switches model or starts a new chat:
// the server unloads every Docker Model Runner model except the one about to
// be used. Fire-and-forget; the server skips it while a reply is generating.
const API_BASE = window.location.origin;
let _lastKeep = null;
let _lastAt = 0;

export function releaseLocalModels(keepModel) {
  const keep = keepModel || '';
  const now = Date.now();
  // Picking a model with no chat open also starts a new chat; one call is enough.
  if (keep === _lastKeep && now - _lastAt < 3000) return;
  _lastKeep = keep;
  _lastAt = now;
  fetch(`${API_BASE}/api/local-models/release`, {
    method: 'POST',
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ model: keep }),
  }).catch(() => {});
}
