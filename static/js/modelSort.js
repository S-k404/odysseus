// Shared alphabetical sorting for model pickers and dropdowns.

function _sortText(value) {
  return String(value || '').split('/').pop().trim() || String(value || '');
}

function _compareText(a, b) {
  return _sortText(a).localeCompare(_sortText(b), undefined, {
    numeric: true,
    sensitivity: 'base',
  }) || String(a || '').localeCompare(String(b || ''), undefined, {
    numeric: true,
    sensitivity: 'base',
  });
}

function _arrayOrEmpty(models) {
  return Array.isArray(models) ? models : [];
}

export function sortModelIds(models) {
  return _arrayOrEmpty(models).slice().sort(_compareText);
}

export function compareModelObjects(a, b) {
  const aLabel = a && (a.display || a.displayName || a.name || a.mid || a.id || a.model);
  const bLabel = b && (b.display || b.displayName || b.name || b.mid || b.id || b.model);
  return _compareText(aLabel, bLabel);
}

export function sortModelObjects(models) {
  return _arrayOrEmpty(models).slice().sort(compareModelObjects);
}

// Speech, embedding and image models can't answer a chat message. Judged by the
// last path segment so "speaches-ai/Kokoro-82M-v1.0-ONNX" and "ai/stable-diffusion"
// are caught; the server keeps them for the voice, memory and image settings.
const _NON_CHAT_LEAF = /(^|[-_.])(whisper|kokoro|tts|stt|embed|embedding|embeddings|rerank|reranker|stable-diffusion|sdxl|flux|dall-e)([-_.:\d]|$)|^(text-embedding|gpt-image|chatgpt-image)/i;

export function isNonChatModelId(modelId) {
  const leaf = String(modelId || '').split('/').pop().trim();
  return !!leaf && _NON_CHAT_LEAF.test(leaf);
}
