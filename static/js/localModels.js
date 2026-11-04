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

// "Optimise memory": the server frees what Odysseus can (loaded models, the decensor
// model), keeping `keepModel` if given. Resolves with the server's report.
export async function optimiseMemory(keepModel) {
  const res = await fetch(`${API_BASE}/api/local-models/optimize`, {
    method: 'POST',
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ model: keepModel || '' }),
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

// One toast line for the report: what was freed, what is free now, and what is still hogging RAM.
export function optimiseSummary(report) {
  const r = report || {};
  if (r.skipped) return 'A reply is generating, so nothing was unloaded. Try again when it finishes.';
  const unloaded = (r.steps || []).filter(s => s.startsWith('unloaded')).length;
  const freed = typeof r.freed_gb === 'number' && r.freed_gb >= 0.1 ? `Freed ${r.freed_gb.toFixed(1)} GB`
    : unloaded ? `Unloaded ${unloaded} item${unloaded === 1 ? '' : 's'}` : 'No model was loaded, so nothing of Odysseus to free';
  const free = typeof r.available_gb === 'number' ? `, ${Math.round(r.available_gb)} GB free` : '';
  const apps = (r.suggestions || []).slice(0, 2).map(s => `${s.app} ${s.gb.toFixed(1)} GB`).join(', ');
  return `${freed}${free}.${apps ? ` Biggest other apps: ${apps}.` : ''}`;
}
