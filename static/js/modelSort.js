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

// Models the server answers with an image instead of text: a chat session on one
// of these generates (or, with an attached picture, edits). Keep in step with
// src/image_model_ids.py, which makes that call; the picker lists these in their
// own "Image generation" section and the composer switches to image mode.
const _IMAGE_MODEL_PREFIX = /^(gpt-image|dall-e|chatgpt-image|hidream|qwen-image|z-image|flux|stable-diffusion|sdxl|boogu|krea-2)|^gpt-.*-image/;

export function isImageModelId(modelId) {
  const leaf = String(modelId || '').split('/').pop().trim().toLowerCase();
  return !!leaf && _IMAGE_MODEL_PREFIX.test(leaf);
}
