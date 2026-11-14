// Auto-switch: just before a message is sent, ask the server which local model fits it
// (a picture request wants the image model, a plan wants the biggest model that fits, tools
// need more than a 1.5B model, ...) and switch to it through the model picker, which also
// unloads the model being left. A model is only ever loaded because the user sent a message.
// Routing must never get in the way of sending: any failure leaves the chat on its model.
import uiModule from './ui.js';
import { listChatModels, listImageModels, switchToModel } from './modelPicker.js';
import { autoRouteEnabled } from './localModels.js';
import { isImageModelId } from './modelSort.js';

export { autoRouteEnabled };

const API_BASE = window.location.origin;
const ROUTE_TIMEOUT_MS = 4000;
let _previousTextModel = ''; // the text model to come back to after a picture
let _autoImageModel = '';    // the image model we switched to ourselves (so we only switch back from that one)

// The newest picture this chat generated, as shown on screen ('' if none).
export function lastGeneratedImageSrc() {
  const shown = document.querySelectorAll('#chat-history img.generated-image');
  return shown.length ? (shown[shown.length - 1].getAttribute('src') || '') : '';
}

// Hand the chat's last generated picture to the message as a normal attachment. The server then gives it to the
// model the way it does for any attached picture (pixels for a vision model, a cached description for a text
// model), so asking about it never needs a different model.
const _pictureAttachedIn = new Set(); // "<chat>|<file>": attached once already; what was learned is in the history

async function attachLastPicture(src, attach, alreadyAttached, chatId) {
  const name = decodeURIComponent((src.split('?')[0].split('/').pop() || 'generated-image.png'));
  if (alreadyAttached.includes(name)) return false;
  const key = `${chatId || ''}|${name}`;
  if (_pictureAttachedIn.has(key)) return false; // asked about before: no second upload, no second look at it
  const res = await fetch(src, { credentials: 'same-origin' });
  if (!res.ok) return false;
  const blob = await res.blob();
  await attach(new File([blob], name, { type: blob.type || 'image/png' }));
  _pictureAttachedIn.add(key);
  return true;
}

export async function autoRouteBeforeSend({ message, currentModel, mode, planMode, approvedPlan, hasImage, attach, attachedNames, chatId }) {
  if (!autoRouteEnabled() || !currentModel) return null;
  const models = [...listChatModels(), ...listImageModels()].filter(m => !m.stale && !m.offline);
  if (models.length < 2) return null;

  const lastPicture = hasImage ? '' : lastGeneratedImageSrc();
  let verdict;
  const abort = new AbortController();
  const timer = setTimeout(() => abort.abort(), ROUTE_TIMEOUT_MS);
  try {
    const res = await fetch(`${API_BASE}/api/local-models/route`, {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      signal: abort.signal,
      body: JSON.stringify({
        message: message || '',
        current: currentModel,
        previous_text: _previousTextModel,
        mode: mode || 'chat',
        has_image: !!hasImage,
        plan_mode: !!planMode,
        approved_plan: !!approvedPlan,
        last_image: !!lastPicture,
        candidates: models.map(m => ({ model: m.mid, endpoint_id: m.endpointId || '', url: m.url || '' })),
      }),
    });
    if (!res.ok) return null;
    verdict = await res.json();
  } catch (_) {
    return null;
  } finally {
    clearTimeout(timer);
  }
  if (!verdict) return null;
  if (verdict.attach_last_image && lastPicture && attach) {
    try { await attachLastPicture(lastPicture, attach, attachedNames || [], chatId); } catch (_) {}
  }
  if (!verdict.switch || !verdict.model) return verdict.attach_last_image ? verdict : null;

  const target = models.find(m => m.mid === verdict.model && (!verdict.endpoint_id || m.endpointId === verdict.endpoint_id))
    || models.find(m => m.mid === verdict.model);
  if (!target) return null;
  if (!isImageModelId(currentModel)) _previousTextModel = currentModel;
  try {
    await switchToModel(target);
  } catch (_) {
    return null;
  }
  _autoImageModel = isImageModelId(target.mid) ? target.mid : '';
  try { uiModule.showToast('Auto: ' + verdict.reason, 5000); } catch (_) {}
  return verdict;
}

// After a turn: if we moved to the image model for a picture, go back to the text model now, so the chat is not
// left on a model that can only draw. Unloading the image model happens through the switch.
export async function autoRouteAfterTurn() {
  if (!autoRouteEnabled() || !_previousTextModel || !_autoImageModel) return;
  const pick = window.__odysseusLastPickedRoute;
  if (!pick || pick.model !== _autoImageModel) return;
  const back = listChatModels().find(m => m.mid === _previousTextModel && !m.stale && !m.offline);
  if (!back) return;
  _autoImageModel = '';
  try {
    await switchToModel(back);
    uiModule.showToast('Auto: back to ' + back.display + '.', 4000);
  } catch (_) {}
}
