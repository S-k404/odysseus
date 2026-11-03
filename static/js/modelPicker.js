// Model Picker — chatbox model selector dropdown
// Extracted from sessions.js

import { providerLogo } from './providers.js';
import uiModule from './ui.js';
import settingsModule from './settings.js';
import { sortModelObjects } from './modelSort.js';
import spinnerModule from './spinner.js';
import { releaseLocalModels } from './localModels.js';

const API_BASE = window.location.origin;

// ── Recent + Favorites persistence ──
// Recent is auto-tracked (last 5 picks, most-recent-first) and lives in its
// own key. Favorites is the SAME key the sidebar Models section uses, so a
// favorite toggled here shows up there and vice-versa.
const RECENT_KEY = 'odysseus-model-recent';
const FAVORITES_KEY = 'odysseus-model-favorites';
const RECENT_MAX = 5;
// Catalogs at or below this size are small enough that hiding everything
// behind search would be a regression — keep listing them in browse mode.
const BROWSE_ALL_LIMIT = 12;

function _loadList(key) {
  try {
    const a = JSON.parse(localStorage.getItem(key) || '[]');
    return Array.isArray(a) ? a : [];
  } catch { return []; }
}
function _saveList(key, list) {
  try { localStorage.setItem(key, JSON.stringify(list)); } catch { /* quota / private mode */ }
}
function _loadRecent() { return _loadList(RECENT_KEY); }
function _pushRecent(mid) {
  if (!mid) return;
  const next = _loadRecent().filter(x => x !== mid);
  next.unshift(mid);
  _saveList(RECENT_KEY, next.slice(0, RECENT_MAX));
}
function _loadFavorites() { return _loadList(FAVORITES_KEY); }
function _toggleFavorite(mid) {
  const favs = _loadFavorites();
  const i = favs.indexOf(mid);
  if (i >= 0) favs.splice(i, 1);
  else favs.push(mid);
  _saveList(FAVORITES_KEY, favs);
  // Keep the sidebar Models section (same key) in sync if it's mounted.
  try {
    if (window.modelsModule && typeof window.modelsModule.refreshModels === 'function') {
      window.modelsModule.refreshModels();
    }
  } catch { /* sidebar not present */ }
  return i < 0; // true when now favorited
}

// ── Use Case Specialist Models Catalog & Versioning ──
// Local models only; the picker hides any entry the endpoints don't list.
// The MLX Coder 7B is left out: Docker's vLLM-Metal backend reserves ~90% of
// RAM for its KV cache regardless of model size.
export const CLAUDE_TIERS = [
  {
    id: 'coding',
    name: 'Coding & Engineering',
    desc: 'Full-stack development, algorithms, code refactoring & syntax parsing',
    icon: `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#38bdf8" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/></svg>`,
    versions: [
      { id: 'huggingface.co/unsloth/qwen3.6-35b-a3b-gguf:UD-Q3_K_S', label: 'Qwen 3.6 35B MoE', tag: 'Best quality', endpoint_id: 'f6584950' },
      { id: 'huggingface.co/unsloth/qwen3-8b-gguf:Q4_K_M', label: 'Qwen3 8B', tag: 'Faster', endpoint_id: 'f6584950' },
    ],
  },
  {
    id: 'reasoning',
    name: 'Reasoning & Architecture',
    desc: 'Extended thinking, formal logic, system design & complex proof',
    icon: `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#d97757" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/></svg>`,
    versions: [
      { id: 'huggingface.co/unsloth/qwen3.6-35b-a3b-gguf:UD-Q3_K_S', label: 'Qwen 3.6 35B MoE', tag: 'Best quality', endpoint_id: 'f6584950' },
      { id: 'huggingface.co/unsloth/qwen3-8b-gguf:Q4_K_M', label: 'Qwen3 8B', tag: 'Faster', endpoint_id: 'f6584950' },
    ],
  },
  {
    id: 'agentic',
    name: 'Agentic & Workflow Automation',
    desc: 'Multi-step agent loops, autonomous task execution, n8n & tool orchestration',
    icon: `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#a855f7" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="7" width="20" height="14" rx="2" ry="2"/><path d="M16 21V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v16"/></svg>`,
    versions: [
      { id: 'huggingface.co/unsloth/qwen3.6-35b-a3b-gguf:UD-Q3_K_S', label: 'Qwen 3.6 35B MoE', tag: 'Best quality', endpoint_id: 'f6584950' },
      { id: 'huggingface.co/unsloth/qwen3-8b-gguf:Q4_K_M', label: 'Qwen3 8B', tag: 'Faster', endpoint_id: 'f6584950' },
    ],
  },
  {
    id: 'cad',
    name: 'CAD & 3D Modeling',
    desc: 'Parametric enclosures, OpenSCAD scripts, STL generation & Blender meshes',
    icon: `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#10b981" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/><polyline points="3.27 6.96 12 12.01 20.73 6.96"/><line x1="12" y1="22.08" x2="12" y2="12"/></svg>`,
    versions: [
      { id: 'huggingface.co/unsloth/qwen3.6-35b-a3b-gguf:UD-Q3_K_S', label: 'Qwen 3.6 35B MoE', tag: 'Best quality', endpoint_id: 'f6584950' },
    ],
  },
  {
    id: 'pcb',
    name: 'PCB Design & Hardware',
    desc: 'KiCad schematics, netlist routing, JLCPCB DRC rule checks & LCSC parts',
    icon: `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#f59e0b" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><rect x="4" y="4" width="16" height="16" rx="2"/><rect x="9" y="9" width="6" height="6"/><line x1="9" y1="1" x2="9" y2="4"/><line x1="15" y1="1" x2="15" y2="4"/><line x1="9" y1="20" x2="9" y2="23"/><line x1="15" y1="20" x2="15" y2="23"/><line x1="20" y1="9" x2="23" y2="9"/><line x1="20" y1="14" x2="23" y2="14"/><line x1="1" y1="9" x2="4" y2="9"/><line x1="1" y1="14" x2="4" y2="14"/></svg>`,
    versions: [
      { id: 'huggingface.co/unsloth/qwen3.6-35b-a3b-gguf:UD-Q3_K_S', label: 'Qwen 3.6 35B MoE', tag: 'Best quality', endpoint_id: 'f6584950' },
      { id: 'huggingface.co/unsloth/qwen3-8b-gguf:Q4_K_M', label: 'Qwen3 8B', tag: 'Faster', endpoint_id: 'f6584950' },
    ],
  },
  {
    id: 'computer_use',
    name: 'Computer Use & Screen Vision',
    desc: 'macOS screen recording, retina screenshots, UI visual inspection & control',
    icon: `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#6366f1" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="3" width="20" height="14" rx="2" ry="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/></svg>`,
    versions: [
      { id: 'huggingface.co/qwen/qwen3-vl-30b-a3b-instruct-gguf:Q4_K_M', label: 'Qwen3 VL 30B', tag: 'Vision', endpoint_id: 'f6584950' },
    ],
  },
  {
    id: 'music_gen',
    name: 'Music Gen & Neural Audio',
    desc: 'Procedural music synthesis (synthwave, ambient), Kokoro voice & Whisper STT',
    icon: `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#06b6d4" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/></svg>`,
    versions: [
      { id: 'huggingface.co/unsloth/qwen3.6-35b-a3b-gguf:UD-Q3_K_S', label: 'Qwen 3.6 35B MoE', tag: 'Best quality', endpoint_id: 'f6584950' },
    ],
  },
  {
    id: 'fast',
    name: 'Fast Utility & Subtasks',
    desc: 'Instant answers, lightweight utility, low latency & token-efficient chat',
    icon: `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#14b8a6" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z"/></svg>`,
    versions: [
      { id: 'huggingface.co/unsloth/qwen2.5-coder-1.5b-instruct-gguf:Q4_K_M', label: 'Qwen 2.5 Coder 1.5B', tag: 'Instant', endpoint_id: 'f6584950' },
      { id: 'qwen2.5:1.5b', label: 'Qwen 2.5 1.5B', tag: 'Ollama', endpoint_id: 'ollama_local' },
    ],
  },
];

export const THINKING_EFFORT_KEY = 'odysseus-thinking-effort';
export const THINKING_BUDGET_KEY = 'odysseus-thinking-budget';
export const CONTEXT_MODE_KEY = 'odysseus-context-mode';
export const CONTEXT_TOKENS_KEY = 'odysseus-context-tokens';

export function getThinkingEffort() {
  return localStorage.getItem(THINKING_EFFORT_KEY) || 'high';
}
export function getThinkingBudget() {
  return parseInt(localStorage.getItem(THINKING_BUDGET_KEY) || '16384', 10);
}
export function getContextMode() {
  return localStorage.getItem(CONTEXT_MODE_KEY) || '200k';
}
export function getContextTokens() {
  return parseInt(localStorage.getItem(CONTEXT_TOKENS_KEY) || '200000', 10);
}

function _pickerModelKey(m) {
  if (!m) return '';
  return `${m.endpointId || m.url || m.epName || 'model'}::${m.mid || ''}`;
}

// ── Shared keyboard nav for model pickers ──
function _handlePickerKeydown(e, listEl, itemSelector, closeFn) {
  if (e.key === 'Escape') { closeFn(); return; }
  if (e.key === 'Enter') {
    e.preventDefault();
    const active = listEl.querySelector(itemSelector + '.kb-active') || listEl.querySelector(itemSelector);
    if (active) active.click();
    return;
  }
  if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
    e.preventDefault();
    const items = [...listEl.querySelectorAll(itemSelector)].filter(el => el.style.display !== 'none');
    if (!items.length) return;
    const cur = items.findIndex(el => el.classList.contains('kb-active'));
    items.forEach(el => el.classList.remove('kb-active'));
    let next;
    if (e.key === 'ArrowDown') next = cur < items.length - 1 ? cur + 1 : 0;
    else next = cur > 0 ? cur - 1 : items.length - 1;
    items[next].classList.add('kb-active');
    items[next].scrollIntoView({ block: 'nearest' });
  }
}

// Dependencies injected via initModelPicker()
let _deps = null;
let _autoSelectingDefault = false;
let _defaultChatPickInFlight = false;
let _defaultPendingSeq = 0;

function _modelExists(modelId, url) {
  if (!modelId || !window.modelsModule || !window.modelsModule.getCachedItems) return false;
  const items = window.modelsModule.getCachedItems() || [];
  if (!items.length) return true;
  const targetUrl = (url || '').replace(/\/+$/, '');
  return items.some(item => {
    if (item.offline) return false;
    const itemUrl = (item.url || '').replace(/\/+$/, '');
    const models = (item.models || []).concat(item.models_extra || []);
    return models.includes(modelId) && (!targetUrl || itemUrl === targetUrl);
  });
}

function _firstAvailableModel() {
  if (!window.modelsModule || !window.modelsModule.getCachedItems) return null;
  const items = window.modelsModule.getCachedItems() || [];
  for (const item of items) {
    if (item.offline) continue;
    const models = (item.models || []).concat(item.models_extra || []);
    if (!models.length) continue;
    return {
      url: item.url,
      modelId: models[0],
      endpointId: item.endpoint_id || '',
    };
  }
  return null;
}

async function _ensureModelCacheForFallback() {
  if (!window.modelsModule || !window.modelsModule.getCachedItems) return;
  const items = window.modelsModule.getCachedItems() || [];
  if (items.length) return;
  if (typeof window.modelsModule.refreshModels === 'function') {
    try { await window.modelsModule.refreshModels(false); } catch (_) {}
  }
}

async function _ensureDefaultPendingChat() {
  if (!_deps || _defaultChatPickInFlight) return;
  if (_deps.getCurrentSessionId && _deps.getCurrentSessionId()) return;
  const pending = _deps.getPendingChat && _deps.getPendingChat();
  if (pending && pending.modelId) return;
  _defaultChatPickInFlight = true;
  const seq = ++_defaultPendingSeq;
  try {
    let dc = null;
    try {
      dc = window.__odysseusDefaultChat || null;
    } catch (_) {}
    if (!dc || !dc.endpoint_url || !dc.model) {
      try {
        const res = await fetch(`${API_BASE}/api/default-chat`, { credentials: 'same-origin' });
        if (res.ok) dc = await res.json();
      } catch (_) {}
    }
    if (dc && dc.endpoint_url && dc.model) {
      if (seq !== _defaultPendingSeq) return;
      const latest = _deps.getPendingChat && _deps.getPendingChat();
      if (latest && latest.modelId && latest.source !== 'default' && latest.source !== 'fallback') return;
      try {
        window.__odysseusDefaultChat = dc;
        localStorage.setItem('odysseus-default-chat-cache', JSON.stringify(dc));
      } catch (_) {}
      const pendingUrl = String((latest && latest.url) || '').replace(/\/+$/, '');
      const defaultUrl = String(dc.endpoint_url || '').replace(/\/+$/, '');
      _deps.setPendingChat({
        url: dc.endpoint_url,
        modelId: dc.model,
        endpointId: dc.endpoint_id || '',
        source: 'default',
      });
      if (!latest || latest.modelId !== dc.model || pendingUrl !== defaultUrl || latest.source !== 'default') {
        updateModelPicker();
      }
      return;
    }
    if (pending && pending.modelId) return;
    await _ensureModelCacheForFallback();
    // No configured default, or the configured default is gone/offline:
    // preserve the convenience fallback and keep the picker usable.
    const fallback = _firstAvailableModel();
    if (fallback) {
      if (seq !== _defaultPendingSeq) return;
      const latest = _deps.getPendingChat && _deps.getPendingChat();
      if (latest && latest.modelId && latest.source !== 'default' && latest.source !== 'fallback') return;
      _deps.setPendingChat({ ...fallback, source: 'fallback' });
      updateModelPicker();
    }
  } finally {
    _defaultChatPickInFlight = false;
  }
}

/**
 * Initialize the model picker dropdown.
 * @param {Object} deps
 * @param {function} deps.getCurrentSessionId - returns current session ID
 * @param {function} deps.getSessions - returns sessions array
 * @param {function} deps.getPendingChat - returns _pendingChat object
 * @param {function} deps.setPendingChat - sets _pendingChat object
 * @param {function} deps.createDirectChat - creates a new direct chat session
 */
export function initModelPicker(deps) {
  _deps = deps;
  _initModelPickerDropdown();
}

function _initModelPickerDropdown() {
  const wrap = document.getElementById('model-picker-wrap');
  const btn = document.getElementById('model-picker-btn');
  const menu = document.getElementById('model-picker-menu');
  const search = document.getElementById('model-picker-search');
  const listEl = document.getElementById('model-picker-list');
  const searchRow = menu ? menu.querySelector('.model-picker-search-row') : null;
  const refreshBtn = document.getElementById('model-picker-refresh-btn');
  if (!wrap || !btn || !menu || !search || !listEl) return;
  if (wrap.dataset.modelPickerBound === '1') return;
  wrap.dataset.modelPickerBound = '1';

  function _close() {
    if (menu.classList.contains('hidden')) return;
    // Restore scroll button
    const _scrollBtn = document.getElementById('scroll-bottom-btn');
    if (_scrollBtn) _scrollBtn.style.display = '';
    menu.classList.add('closing');
    menu.addEventListener('animationend', function _onDone() {
      menu.removeEventListener('animationend', _onDone);
      menu.classList.remove('closing');
      menu.classList.add('hidden');
      search.value = '';
    }, { once: true });
    // Fallback if animationend doesn't fire
    setTimeout(() => {
      if (!menu.classList.contains('hidden')) {
        menu.classList.remove('closing');
        menu.classList.add('hidden');
        search.value = '';
      }
    }, 200);
  }

  function _openPickerShortcut(kind) {
    _close();
    try {
      if (kind === 'cookbook') {
        if (window.cookbookModule && typeof window.cookbookModule.open === 'function') {
          window.cookbookModule.open();
        } else {
          const btn = document.getElementById('tool-cookbook-btn') || document.getElementById('rail-cookbook');
          if (btn) btn.click();
          else location.hash = '#cookbook';
        }
      } else if (kind === 'settings') {
        if (settingsModule && typeof settingsModule.open === 'function') settingsModule.open();
      } else if (window.adminModule && typeof window.adminModule.open === 'function') {
        window.adminModule.open('services');
      } else if (settingsModule && typeof settingsModule.open === 'function') {
        settingsModule.open('services');
      }
    } catch (_) {}
  }

  // Local endpoint health — only probed for LOCAL endpoints, since
  // cloud APIs are essentially always up. Cached briefly on the
  // server side too (8s TTL). Picker opens do not probe; the refresh button
  // is the explicit network/probe action.
  let _localProbe = {};            // {endpoint_id: {alive, latency_ms, error}}
  let _localProbeFetchedAt = 0;
  const _LOCAL_PROBE_TTL_MS = 5000;
  let _pickerLoading = false;
  let _pickerLoadSeq = 0;

  async function _refreshLocalProbe() {
    try {
      if (window.__odysseusChatBusy || Date.now() < (window.__odysseusChatBusyUntil || 0)) return;
    } catch (_) {}
    const now = Date.now();
    if (now - _localProbeFetchedAt < _LOCAL_PROBE_TTL_MS) return;
    _localProbeFetchedAt = now;
    try {
      const r = await fetch('/api/model-endpoints/probe-local', { credentials: 'same-origin' });
      if (r.ok) _localProbe = (await r.json()) || {};
    } catch (_) { /* leave stale data; picker still works */ }
  }

  function _getAllModels() {
    const items = (window.modelsModule && window.modelsModule.getCachedItems) ? window.modelsModule.getCachedItems() : [];
    const result = [];
    const seen = new Set();
    items.forEach(item => {
      // Previously: offline endpoints were skipped entirely, so a server
      // that briefly went down disappeared from the picker — confusing
      // when the user can still see it (offline-tagged) in Settings.
      // Now: include offline-endpoint models too but flag them
      // `stale: true` so the row renderer dims them + shows the offline
      // pill. The user can still click and try anyway (matches the
      // existing "local server appears offline" path on line 301).
      const epOffline = !!item.offline;
      const allModels = (item.models || []).concat(item.models_extra || []);
      const allDisplay = (item.models_display || []).concat(item.models_extra_display || []);
      // Mark local endpoints whose live probe failed.
      const probeResult = item.endpoint_id ? _localProbe[item.endpoint_id] : null;
      const isLocalDead = !!(probeResult && probeResult.alive === false);
      const isApiEndpoint = item.category && item.category !== 'local';
      allModels.forEach((mid, i) => {
        // Local/self-hosted servers often expose the same model through several
        // stale endpoints, so keep deduping those by model id. Cloud/API
        // endpoints are user-selected provider routes; the same model id can be
        // intentionally enabled on OpenRouter and OpenAI, so key those by
        // endpoint too or the chat picker silently drops one.
        const seenKey = isApiEndpoint
          ? `${item.endpoint_id || item.url || item.endpoint_name || 'api'}::${mid}`
          : mid;
        if (seen.has(seenKey)) return;
        seen.add(seenKey);
        result.push({
          key: seenKey,
          mid,
          display: (allDisplay[i] || mid).split('/').pop(),
          url: item.url,
          endpointId: item.endpoint_id,
          epName: item.endpoint_name || '',
          category: item.category || '',
          providerText: [
            item.endpoint_name || '',
            item.category || '',
            item.host || '',
            item.url || '',
          ].filter(Boolean).join(' '),
          stale: isLocalDead || epOffline,
          staleReason: epOffline
            ? (item.ping_error || 'endpoint offline')
            : (isLocalDead ? (probeResult.error || 'not responding') : ''),
          offline: epOffline,
        });
      });
    });
    return sortModelObjects(result);
  }

  function _hasModelCache() {
    try {
      return !!(window.modelsModule && window.modelsModule.getCachedItems && (window.modelsModule.getCachedItems() || []).length);
    } catch (_) {
      return false;
    }
  }

  function _renderLoading(text = 'Loading models…') {
    listEl.innerHTML = '';
    listEl.classList.remove('is-empty');
    listEl.classList.add('is-loading');
    menu.classList.remove('no-models');
    if (search) search.placeholder = text;
    let row = null;
    try {
      row = spinnerModule.createLoadingRow(text, 15);
    } catch (_) {
      row = document.createElement('div');
      row.className = 'model-switch-empty';
      row.textContent = text;
    }
    row.classList.add('model-picker-loading-row');
    listEl.appendChild(row);
  }

  async function _refreshPickerModels({ force = false, showLoading = false } = {}) {
    if (!window.modelsModule || typeof window.modelsModule.refreshModels !== 'function') return;
    const seq = ++_pickerLoadSeq;
    _pickerLoading = true;
    if (showLoading) _renderLoading(force ? 'Refreshing models…' : 'Loading models…');
    try {
      await window.modelsModule.refreshModels(force);
      await _refreshLocalProbe();
    } finally {
      if (seq === _pickerLoadSeq) {
        _pickerLoading = false;
        listEl.classList.remove('is-loading');
      }
    }
  }

  // ── Provider display names and grouping ──
  const _PROVIDER_NAMES = {
    '01-ai': 'Yi', 'abacusai': 'Abacus AI', 'adept': 'Adept',
    'ai21': 'AI21 Labs', 'ai21labs': 'AI21 Labs', 'aion-labs': 'Aion Labs',
    'aisingapore': 'AI Singapore', 'allenai': 'Allen AI', 'amazon': 'Amazon',
    'anthracite-org': 'Anthracite', 'anthropic': 'Anthropic', 'arcee-ai': 'Arcee AI',
    'baai': 'BAAI', 'baidu': 'Baidu', 'bigcode': 'BigCode',
    'black-forest-labs': 'Black Forest Labs', 'bytedance': 'ByteDance',
    'bytedance-seed': 'ByteDance', 'cognitivecomputations': 'Cognitive Computations',
    'cohere': 'Cohere', 'databricks': 'Databricks', 'deepcogito': 'DeepCogito',
    'deepseek': 'DeepSeek', 'deepseek-ai': 'DeepSeek', 'essentialai': 'Essential AI',
    'google': 'Google', 'gryphe': 'Gryphe', 'ibm': 'IBM',
    'ibm-granite': 'IBM Granite', 'inception': 'Inception',
    'inclusionai': 'Inclusion AI', 'inflection': 'Inflection',
    'kwaipilot': 'KwaiPilot', 'liquid': 'Liquid AI', 'mancer': 'Mancer',
    'meta': 'Llama', 'meta-llama': 'Llama', 'microsoft': 'Microsoft',
    'minimax': 'MiniMax', 'minimaxai': 'MiniMax', 'mistralai': 'Mistral',
    'moonshotai': 'Moonshot', 'morph': 'Morph', 'nex-agi': 'Nex AGI',
    'nousresearch': 'Nous Research', 'nv-mistralai': 'NVIDIA x Mistral',
    'nvidia': 'NVIDIA', 'openai': 'OpenAI', 'openrouter': 'OpenRouter',
    'perceptron': 'Perceptron', 'perplexity': 'Perplexity', 'poolside': 'Poolside',
    'prime-intellect': 'Prime Intellect', 'qwen': 'Qwen', 'rekaai': 'Reka',
    'relace': 'Relace', 'sao10k': 'Sao10k', 'sarvamai': 'Sarvam AI',
    'snowflake': 'Snowflake', 'stepfun': 'StepFun', 'stepfun-ai': 'StepFun',
    'stockmark': 'Stockmark', 'switchpoint': 'SwitchPoint', 'tencent': 'Tencent',
    'thedrummer': 'TheDrummer', 'undi95': 'Undi95', 'upstage': 'Upstage',
    'writer': 'Writer', 'x-ai': 'xAI', 'xiaomi': 'Xiaomi',
    'z-ai': 'Zhipu', 'zyphra': 'Zyphra',
    '~anthropic': 'Anthropic', '~google': 'Google',
    '~moonshotai': 'Moonshot', '~openai': 'OpenAI',
  };
  const _PROVIDER_ALIAS = {
    'meta-llama': 'meta', 'deepseek': 'deepseek-ai', 'minimaxai': 'minimax',
    'stepfun-ai': 'stepfun', 'ai21labs': 'ai21', 'ibm-granite': 'ibm',
    'bytedance-seed': 'bytedance', '~anthropic': 'anthropic',
    '~google': 'google', '~moonshotai': 'moonshotai', '~openai': 'openai',
  };
  function _providerDisplayName(slug) {
    return _PROVIDER_NAMES[slug] || slug.charAt(0).toUpperCase() + slug.slice(1).replace(/-/g, ' ');
  }
  function _providerGroupKey(m) {
    if (m && m.category && m.category !== 'local' && m.epName) {
      return `~endpoint:${m.epName}`;
    }
    return _providerSlug((m && m.mid) || '');
  }
  function _providerGroupName(key) {
    if (String(key || '').startsWith('~endpoint:')) return String(key).slice('~endpoint:'.length);
    return _providerDisplayName(key);
  }
  function _providerSlug(mid) {
    const slash = mid.indexOf('/');
    let slug = slash > 0 ? mid.substring(0, slash) : 'other';
    return _PROVIDER_ALIAS[slug] || slug;
  }
  const _collapsedProviders = new Set(_loadList('odysseus-model-collapsed'));
  let _justExpandedProvider = null;

  function _populate(filter) {
    listEl.innerHTML = '';
    listEl.classList.remove('is-loading');
    const all = _getAllModels();
    const q = (filter || '').trim().toLowerCase();
    const hasAnyModel = all.length > 0;
    listEl.classList.toggle('is-empty', !hasAnyModel);
    menu.classList.toggle('no-models', !hasAnyModel);
    if (search) {
      search.placeholder = hasAnyModel ? 'Search models…' : 'No models connected';
    }
    if (searchRow) {
      searchRow.classList.toggle('searching', !!q);
    }

    if (!hasAnyModel) return; // collapsed empty list — nothing to render

    // Unique lookup so Recent/Favorites (stored as bare model IDs) can be
    // resolved back to full model objects; drops anything no longer offered.
    const byId = new Map();
    const byKey = new Map();
    all.forEach(m => {
      const key = _pickerModelKey(m);
      if (key && !byKey.has(key)) byKey.set(key, m);
      if (!byId.has(m.mid)) byId.set(m.mid, m);
    });

    const favs = _loadFavorites();

    function _addSection(label) {
      const el = document.createElement('div');
      el.className = 'mp-section-label';
      el.textContent = label;
      listEl.appendChild(el);
    }
    function _addEmpty(text) {
      const empty = document.createElement('div');
      empty.className = 'model-switch-empty';
      empty.textContent = text;
      listEl.appendChild(empty);
    }
    function _addRow(m) {
      const row = document.createElement('div');
      row.className = 'model-switch-item';
      if (m.stale) {
        row.classList.add('model-switch-stale');
        row.style.opacity = '0.45';
        row.title = `Local server appears offline: ${m.staleReason}. Click to try anyway, or relaunch in Cookbook.`;
      }
      const _mlogo = providerLogo(m.mid);
      if (_mlogo) {
        const logoSpan = document.createElement('span');
        logoSpan.className = 'provider-logo';
        logoSpan.style.opacity = '0.6';
        logoSpan.innerHTML = _mlogo;
        row.appendChild(logoSpan);
      }
      const nameSpan = document.createElement('span');
      nameSpan.className = 'mp-model-name';
      nameSpan.textContent = m.display;
      // Long model names are clipped with ellipsis — expose the full name on
      // hover so the suffix/variant tag is still discoverable (#1982).
      nameSpan.title = m.display;
      row.appendChild(nameSpan);
      // Offline state is already conveyed by the row's reduced opacity —
      // a redundant "offline" pill on top of that just added clutter.
      // (Class kept on `row` so the opacity rule still applies; the text
      // badge is gone.)
      const epSpan = document.createElement('span');
      epSpan.className = 'model-switch-ep';
      // Don't show endpoint name if it matches the model name (local self-hosted)
      const _epDisplay = m.epName && !m.display.toLowerCase().includes(m.epName.toLowerCase().split('/').pop()) ? m.epName : '';
      epSpan.textContent = _epDisplay;
      row.appendChild(epSpan);

      // Inline favorite dot — toggles favorite, never picks the model.
      const favDot = document.createElement('button');
      favDot.type = 'button';
      favDot.className = 'mp-fav-dot' + (favs.includes(m.mid) ? ' active' : '');
      favDot.textContent = '●';
      const _setFavState = (on) => {
        favDot.classList.toggle('active', on);
        favDot.title = on ? 'Remove from favorites' : 'Add to favorites';
        favDot.setAttribute('aria-label', on ? 'Remove from favorites' : 'Add to favorites');
        favDot.setAttribute('aria-pressed', on ? 'true' : 'false');
      };
      _setFavState(favs.includes(m.mid));
      favDot.addEventListener('click', (e) => {
        e.stopPropagation();
        const nowFav = _toggleFavorite(m.mid);
        _setFavState(nowFav);
        favDot.classList.remove('pulse');
        void favDot.offsetWidth;
        favDot.classList.add('pulse');
        // Keep our in-memory copy aligned so a follow-up re-render is correct.
        const idx = favs.indexOf(m.mid);
        if (nowFav && idx < 0) favs.push(m.mid);
        else if (!nowFav && idx >= 0) favs.splice(idx, 1);
        if (uiModule && uiModule.showToast) uiModule.showToast(nowFav ? 'Favorited' : 'Unfavorited');
        // In browse mode the Favorites section membership changed — rebuild
        // (cheap: Recent + Favorites). In search mode the row stays put, so
        // the in-place favorite update above is enough.
        if (!q) {
          const st = listEl.scrollTop;
          _populate('');
          listEl.scrollTop = st;
        }
      });
      row.appendChild(favDot);

      row.addEventListener('click', () => _pick(m));
      listEl.appendChild(row);
    }

    // ── Search mode: flat, filtered results across the whole catalog ──
    if (q) {
      const matches = all.filter(m => {
        const provName = _providerDisplayName(_providerSlug(m.mid)).toLowerCase();
        return [m.mid, m.display, m.epName, m.providerText, provName]
          .filter(Boolean).join(' ').toLowerCase().includes(q);
      });
      if (matches.length === 0) _addEmpty('No matching models');
      else matches.forEach(_addRow);
      return;
    }

    // ── Browse mode: Favorites (manual) + Recent (auto), with dedupe. ──
    // Rules:
    //   1. Never list the same model twice in the dropdown. Favorites
    //      win over Recent (if you favorited it, that's where it
    //      belongs — Recent shouldn't show it again as duplicate).
    //   2. Small catalogs (≤ BROWSE_ALL_LIMIT total) skip the Recent
    //      section entirely — when there's only ~10 models, the whole
    //      list fits below as "All models" and a separate Recent
    //      section just duplicates rows.
    const shown = new Set();
    const favModels = favs.map(id => byKey.get(id) || byId.get(id)).filter(Boolean);
    if (favModels.length) {
      _addSection('Favorites');
      favModels.forEach(m => { shown.add(_pickerModelKey(m)); _addRow(m); });
    }
    // Recent: only render when the catalog is big enough that surfacing
    // a recency shortlist is actually useful, AND only models that
    // aren't already in Favorites (dedupe).
    if (all.length > BROWSE_ALL_LIMIT) {
      const recentModels = _loadRecent()
        .map(id => byKey.get(id) || byId.get(id))
        .filter(Boolean)
        .filter(m => !shown.has(_pickerModelKey(m)))
        .slice(0, RECENT_MAX);
      if (recentModels.length) {
        _addSection('Recent');
        recentModels.forEach(m => { shown.add(_pickerModelKey(m)); _addRow(m); });
      }
    }

    // Small catalogs: still list everything so users aren't forced to search.
    if (all.length <= BROWSE_ALL_LIMIT) {
      const rest = all.filter(m => !shown.has(_pickerModelKey(m)));
      if (rest.length) {
        if (shown.size) _addSection('All models');
        rest.forEach(_addRow);
      }
    } else {
      // Large catalog: show provider groups with collapsible sections.
      const rest = all.filter(m => !shown.has(_pickerModelKey(m)));
      const groups = new Map();
      rest.forEach(m => {
        const slug = _providerGroupKey(m);
        if (!groups.has(slug)) groups.set(slug, []);
        groups.get(slug).push(m);
      });
      const sorted = [...groups.keys()].sort((a, b) =>
        _providerGroupName(a).localeCompare(_providerGroupName(b)));

      sorted.forEach(provider => {
        const models = groups.get(provider);
        const isCollapsed = _collapsedProviders.has(provider);
        const header = document.createElement('div');
        header.className = 'mp-provider-header';
        header.innerHTML =
          `<svg class="mp-provider-chevron${isCollapsed ? ' collapsed' : ''}" width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"/></svg>`
          + `<span class="mp-provider-name">${_providerGroupName(provider)}</span>`
          + `<span class="mp-provider-count">${models.length}</span>`;
        header.addEventListener('click', (e) => {
          e.stopPropagation();
          if (_collapsedProviders.has(provider)) {
            _collapsedProviders.delete(provider);
            _justExpandedProvider = provider;
          } else {
            _collapsedProviders.add(provider);
            _justExpandedProvider = null;
          }
          _saveList('odysseus-model-collapsed', [..._collapsedProviders]);
          const st = listEl.scrollTop;
          _populate('');
          listEl.scrollTop = st;
        });
        listEl.appendChild(header);
        if (!isCollapsed) {
          const group = document.createElement('div');
          group.className = 'mp-provider-group' + (_justExpandedProvider === provider ? ' mp-just-expanded' : '');
          models.forEach(m => {
            _addRow(m);
            // Move the just-appended row into the group container
            group.appendChild(listEl.lastElementChild);
          });
          listEl.appendChild(group);
          if (_justExpandedProvider === provider) _justExpandedProvider = null;
        }
      });
    }
  }

async function _pick(m) {
    _defaultPendingSeq++;
    try {
      window.__odysseusLastPickedRoute = {
        model: m.mid || '',
        endpoint_url: m.url || '',
        endpoint_id: m.endpointId || '',
        display: m.display || m.mid || '',
        picked_at: Date.now(),
      };
    } catch (_) {}
    let switchDone = null;
    const switchPromise = new Promise(resolve => { switchDone = resolve; });
    try { window.__odysseusModelSwitchPromise = switchPromise; } catch (_) {}
    const finishSwitch = () => {
      try {
        if (switchDone) switchDone();
        if (window.__odysseusModelSwitchPromise === switchPromise) delete window.__odysseusModelSwitchPromise;
      } catch (_) {}
    };
    const currentSessionId = _deps.getCurrentSessionId();
    const _pendingChat = _deps.getPendingChat();

    // Remember this pick so it surfaces under "Recent" next time the picker
    // opens — the whole point of quick-switch.
    if (m && m.mid) _pushRecent(_pickerModelKey(m) || m.mid);
    // Unload the previous local model now rather than at the next message.
    if (m && m.mid) releaseLocalModels(m.mid);

    // Broadcast immediately so listeners (e.g. the tour) can advance without
    // waiting for the async session-create/PATCH that follows.
    try { document.dispatchEvent(new CustomEvent('odysseus:model-picked', { detail: m })); } catch {}

    // Blur search input before closing to dismiss keyboard on mobile
    if (document.activeElement) document.activeElement.blur();
    _close();
    // Refocus main textarea — skip on mobile to avoid keyboard bounce
    if (window.innerWidth >= 768) {
      const _ta = document.getElementById('message');
      if (_ta) setTimeout(() => _ta.focus(), 50);
    }
    if (!currentSessionId && _pendingChat) {
      // Already have a deferred session — just update the model
      _deps.setPendingChat({ url: m.url, modelId: m.mid, endpointId: m.endpointId, source: 'manual' });
      // Header stays as session name — model switch only updates picker
      updateModelPicker();
      uiModule.showToast(`Using ${m.display}`);
      finishSwitch();
      return;
    } else if (!currentSessionId) {
      // No session yet — create one with this model
      try {
        await _deps.createDirectChat(m.url, m.mid, m.endpointId);
      } catch (e) {
        uiModule.showError('Failed to start chat: ' + e);
        finishSwitch();
        return;
      }
    } else {
      // Existing session with no model — PATCH it
      const sessions = _deps.getSessions();
      const s = sessions.find(x => x.id === currentSessionId);
      if (s) { s.model = m.mid; s.endpoint_url = m.url; s.endpoint_id = m.endpointId || s.endpoint_id || ''; }
      updateModelPicker();
      const fd = new FormData();
      fd.append('model', m.mid);
      fd.append('endpoint_url', m.url);
      if (m.endpointId) fd.append('endpoint_id', m.endpointId);
      try {
        const res = await fetch(`${API_BASE}/api/session/${currentSessionId}`, { method: 'PATCH', body: fd });
        if (!res.ok) {
          uiModule.showError('Failed to set model');
          finishSwitch();
          return;
        }
        // Header stays as session name — model info shown in picker only
      } catch (e) {
        uiModule.showError('Failed to set model: ' + e);
        finishSwitch();
        return;
      }
    }
    // Update picker visibility — model is now set
    updateModelPicker();
    if (window.refreshChatContextHeader) window.refreshChatContextHeader('model-pick');
    uiModule.showToast(`Using ${m.display}`);
    finishSwitch();
  }

  document.addEventListener('odysseus:auto-select-model', async (e) => {
    const detail = (e && e.detail) || {};
    const currentSessionId = _deps.getCurrentSessionId();
    const sessions = _deps.getSessions();
    const current = sessions.find(x => x.id === currentSessionId);
    const pending = _deps.getPendingChat();
    if ((current && current.model) || (pending && pending.modelId)) return;

    if (window.modelsModule && window.modelsModule.refreshModels) {
      try { await window.modelsModule.refreshModels(false); } catch (_) {}
    }
    const items = window.modelsModule && window.modelsModule.getCachedItems ? window.modelsModule.getCachedItems() : [];
    const targetEndpointId = detail.endpointId ? String(detail.endpointId) : '';
    const targetModel = detail.modelId || '';
    let match = null;
    for (const item of items) {
      if (item.offline) continue;
      if (targetEndpointId && String(item.endpoint_id || '') !== targetEndpointId) continue;
      const models = (item.models || []).concat(item.models_extra || []);
      const displays = (item.models_display || []).concat(item.models_extra_display || []);
      const idx = targetModel ? models.indexOf(targetModel) : (models.length ? 0 : -1);
      if (idx >= 0) {
        match = {
          mid: models[idx],
          display: (displays[idx] || models[idx]).split('/').pop(),
          url: item.url || detail.url || '',
          endpointId: item.endpoint_id || detail.endpointId || '',
          epName: item.endpoint_name || detail.endpointName || '',
          providerText: [item.endpoint_name || detail.endpointName || '', item.url || detail.url || ''].filter(Boolean).join(' '),
        };
        break;
      }
    }
    if (!match && detail.modelId && detail.url) {
      match = {
        mid: detail.modelId,
        display: String(detail.modelId).split('/').pop(),
        url: detail.url,
        endpointId: detail.endpointId || '',
        epName: detail.endpointName || '',
        providerText: [detail.endpointName || '', detail.url || ''].filter(Boolean).join(' '),
      };
    }
    if (match) await _pick(match);
  });

  btn.addEventListener('pointerdown', (e) => {
    e.stopPropagation();
  });

  // ── Claude Tabs & Views ──
  const tabBtns = menu.querySelectorAll('.mp-tab-btn');
  const viewTiers = document.getElementById('mp-view-tiers');
  const viewAll = document.getElementById('mp-view-all');
  const tiersListEl = document.getElementById('claude-tiers-list');
  const MP_TABS = ['tiers', 'all'];

  // A stale saved tab (e.g. the removed 'effort' tab) would hide every view.
  let _activeTab = localStorage.getItem('odysseus-mp-tab');
  if (!MP_TABS.includes(_activeTab)) _activeTab = 'tiers';

  function _switchTab(tab) {
    if (!MP_TABS.includes(tab)) tab = 'tiers';
    _activeTab = tab;
    localStorage.setItem('odysseus-mp-tab', tab);
    tabBtns.forEach(b => {
      b.classList.toggle('active', b.dataset.mpTab === tab);
    });
    if (viewTiers) viewTiers.classList.toggle('hidden', tab !== 'tiers');
    if (viewAll) viewAll.classList.toggle('hidden', tab !== 'all');

    if (tab === 'tiers') {
      _renderClaudeTiers();
    } else {
      _populate(search ? search.value : '');
    }
  }

  tabBtns.forEach(b => {
    b.addEventListener('click', (e) => {
      e.stopPropagation();
      _switchTab(b.dataset.mpTab);
    });
  });

  // Resolve a catalog version against the live model list so a chip always
  // carries the endpoint's real URL, and versions that aren't configured
  // never show up as dead placeholders.
  function _resolveTierVersion(ver, available) {
    return available.find(m => m.mid === ver.id && m.endpointId === ver.endpoint_id)
      || available.find(m => m.mid === ver.id)
      || null;
  }

  function _renderClaudeTiers() {
    if (!tiersListEl) return;
    tiersListEl.innerHTML = '';

    const currentSessionId = _deps ? _deps.getCurrentSessionId() : null;
    const sessions = _deps ? _deps.getSessions() : [];
    const pendingChat = _deps ? _deps.getPendingChat() : null;
    const s = sessions.find(x => x.id === currentSessionId);
    const activeModelId = (s && s.model) || (pendingChat && pendingChat.modelId) || '';
    const available = _getAllModels();

    CLAUDE_TIERS.forEach(tier => {
      const versions = tier.versions
        .map(ver => ({ ver, model: _resolveTierVersion(ver, available) }))
        .filter(v => v.model);
      if (!versions.length) return;

      const card = document.createElement('div');
      card.className = 'claude-tier-card';
      card.dataset.tier = tier.id;

      const header = document.createElement('div');
      header.className = 'claude-tier-header';
      header.innerHTML = `
        <span class="tier-icon">${tier.icon}</span>
        <div class="tier-text">
          <div class="tier-name"></div>
          <div class="tier-desc"></div>
        </div>
      `;
      header.querySelector('.tier-name').textContent = tier.name;
      header.querySelector('.tier-desc').textContent = tier.desc;
      card.appendChild(header);

      const verRow = document.createElement('div');
      verRow.className = 'claude-tier-versions';

      versions.forEach(({ ver, model }) => {
        const chip = document.createElement('button');
        chip.type = 'button';
        chip.className = 'tier-ver-chip';
        chip.dataset.mid = model.mid;
        chip.title = model.stale ? `${model.mid} — ${model.staleReason || 'offline'}` : model.mid;
        if (activeModelId === model.mid) chip.classList.add('active');
        if (model.stale) chip.classList.add('stale');

        const label = document.createElement('span');
        label.className = 'ver-label';
        label.textContent = ver.label;
        const tag = document.createElement('span');
        tag.className = 'ver-tag';
        tag.textContent = ver.tag;
        chip.append(label, tag);

        chip.addEventListener('click', (e) => {
          e.stopPropagation();
          _pick({ ...model, display: ver.label });
        });

        verRow.appendChild(chip);
      });

      card.appendChild(verRow);
      tiersListEl.appendChild(card);
    });

    if (!tiersListEl.childElementCount) {
      const empty = document.createElement('div');
      empty.className = 'claude-tiers-empty';
      empty.textContent = _hasModelCache()
        ? 'None of the specialist models are configured. Pick one from All models.'
        : 'Loading models…';
      tiersListEl.appendChild(empty);
    }
  }

  // ── Reasoning Effort & Context (composer pills are the single control) ──
  const effortPill = document.getElementById('thinking-effort-pill');
  const effortPillLabel = document.getElementById('thinking-effort-label');
  const contextPill = document.getElementById('context-mode-pill');
  const contextPillLabel = document.getElementById('context-mode-label');

  const EFFORT_PRESETS = {
    'none': { budget: 0, label: 'Off' },
    'low': { budget: 2048, label: 'Low (2k)' },
    'medium': { budget: 8192, label: 'Med (8k)' },
    'high': { budget: 16384, label: 'High (16k)' },
    'max': { budget: 64000, label: 'Extra (64k)' },
  };

  // Limits on how much history is sent. The server clamps every choice to the
  // window the model is actually served with, so "Max" means "all of it".
  // ('200k' stays the key for Max so stored choices keep working.)
  const CONTEXT_PRESETS = {
    '16k': { tokens: 16384, label: '16k' },
    '32k': { tokens: 32768, label: '32k' },
    '64k': { tokens: 65536, label: '64k' },
    '200k': { tokens: 200000, label: 'Max' },
  };

  function _setEffort(effortKey, budgetVal, notify = false) {
    if (!EFFORT_PRESETS[effortKey]) effortKey = 'high';
    const cfg = EFFORT_PRESETS[effortKey];
    const finalBudget = budgetVal !== undefined ? budgetVal : cfg.budget;
    localStorage.setItem(THINKING_EFFORT_KEY, effortKey);
    localStorage.setItem(THINKING_BUDGET_KEY, String(finalBudget));

    if (effortPillLabel) effortPillLabel.textContent = `Thinking: ${cfg.label}`;
    if (effortPill) effortPill.classList.toggle('active', effortKey !== 'none');
    if (notify && uiModule && uiModule.showToast) {
      uiModule.showToast(`Thinking: ${cfg.label}`);
    }
  }

  function _setContext(ctxKey, tokenVal, notify = false) {
    if (!CONTEXT_PRESETS[ctxKey]) ctxKey = '200k';
    const cfg = CONTEXT_PRESETS[ctxKey];
    const finalTokens = tokenVal !== undefined ? tokenVal : cfg.tokens;
    localStorage.setItem(CONTEXT_MODE_KEY, ctxKey);
    localStorage.setItem(CONTEXT_TOKENS_KEY, String(finalTokens));

    if (contextPillLabel) contextPillLabel.textContent = `${cfg.label} Context`;
    if (notify && uiModule && uiModule.showToast) {
      uiModule.showToast(`Context: ${cfg.label}`);
    }
  }

  // Composer pills cycle through the presets
  if (effortPill) {
    const cycleOrder = Object.keys(EFFORT_PRESETS);
    effortPill.addEventListener('click', (e) => {
      e.stopPropagation();
      const nextIdx = (cycleOrder.indexOf(getThinkingEffort()) + 1) % cycleOrder.length;
      _setEffort(cycleOrder[nextIdx], undefined, true);
    });
  }

  if (contextPill) {
    const cycleContext = Object.keys(CONTEXT_PRESETS);
    contextPill.addEventListener('click', (e) => {
      e.stopPropagation();
      const nextIdx = (cycleContext.indexOf(getContextMode()) + 1) % cycleContext.length;
      _setContext(cycleContext[nextIdx], undefined, true);
    });
  }

  _setEffort(getThinkingEffort(), getThinkingBudget());
  _setContext(getContextMode(), getContextTokens());

  btn.addEventListener('click', (e) => {
    e.stopPropagation();
    if (menu.classList.contains('hidden') || menu.classList.contains('closing')) {
      // Force-clear any in-progress close animation
      menu.classList.remove('closing', 'hidden');
      // The menu opens upward; keep it inside the window when the composer
      // sits high (welcome screen) or the window is short.
      menu.style.maxHeight = `${Math.max(200, wrap.getBoundingClientRect().top - 24)}px`;
      _switchTab(_activeTab);
      const hasCache = _hasModelCache();
      if (hasCache) {
        _populate('');
      } else {
        _renderLoading('Loading models…');
      }
      if (window.modelsModule && window.modelsModule.refreshModels) {
        _refreshPickerModels({ force: hasCache, showLoading: !hasCache }).then(() => {
          if (!menu.classList.contains('hidden')) {
            if (_activeTab === 'tiers') _renderClaudeTiers();
            else if (_activeTab === 'all') _populate(search.value || '');
          }
          updateModelPicker();
        }).catch(() => {});
      }
      if (_activeTab === 'all' && window.innerWidth >= 768) search.focus();
      // Hide scroll button so it doesn't overlap
      const _scrollBtn = document.getElementById('scroll-bottom-btn');
      if (_scrollBtn) _scrollBtn.style.display = 'none';
    } else {
      _close();
    }
  });

  search.addEventListener('input', () => {
    if (_pickerLoading) return;
    if (_activeTab !== 'all') _switchTab('all');
    _populate(search.value);
  });
  search.addEventListener('click', (e) => e.stopPropagation());
  if (refreshBtn) {
    refreshBtn.addEventListener('click', async (e) => {
      e.stopPropagation();
      refreshBtn.disabled = true;
      refreshBtn.classList.add('spinning');
      try {
        await _refreshPickerModels({ force: true, showLoading: true });
        if (!menu.classList.contains('hidden')) _populate(search.value || '');
        updateModelPicker();
      } catch (_) {
        uiModule.showToast('Model refresh failed');
      } finally {
        refreshBtn.disabled = false;
        refreshBtn.classList.remove('spinning');
      }
    });
  }
  search.addEventListener('keydown', (e) => {
    _handlePickerKeydown(e, listEl, '.model-switch-item', _close);
  });
  const addModelsBtn = document.getElementById('model-picker-add-models-btn');
  if (addModelsBtn) {
    addModelsBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      _openPickerShortcut('models');
    });
  }
  document.addEventListener('click', (e) => {
    if (!menu.classList.contains('hidden') && !wrap.contains(e.target)) {
      _close();
    }
  });
  // The Specialists tab doesn't focus the search box, so Escape needs a
  // document-level hook (the search box handles its own Escape).
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && e.target !== search && !menu.classList.contains('hidden')) {
      _close();
    }
  });
}

/**
 * Update the model picker label to show the current model.
 * Always visible — shows current model name or "Select model" if none.
 * Called after selectSession, createDirectChat, and model switch.
 */
export function updateModelPicker() {
  if (!_deps) return;
  const label = document.getElementById('model-picker-label');
  if (!label) return;
  // Hide model picker when group chat is active
  const wrap = document.getElementById('model-picker-wrap');
  if (window.groupModule && window.groupModule.isActive()) {
    if (wrap) { wrap.style.display = 'none'; }
    return;
  }
  // Reset inline visibility (may have been hidden by typing in previous session)
  if (wrap) {
    wrap.style.display = '';
    wrap.style.opacity = '';
    wrap.style.pointerEvents = '';
  }
  const currentSessionId = _deps.getCurrentSessionId();
  const sessions = _deps.getSessions();
  const _pendingChat = _deps.getPendingChat();
  const s = sessions.find(x => x.id === currentSessionId);
  let modelId = null;
  if (s && s.model) {
    modelId = s.model;
  } else if (_pendingChat && _pendingChat.modelId) {
    modelId = _pendingChat.modelId;
    if (_pendingChat.source === 'fallback' && !_modelExists(modelId, _pendingChat.url || '')) {
      _deps.setPendingChat(null);
      modelId = null;
    }
  }
  if (!modelId && !currentSessionId && !_pendingChat && _deps.setPendingChat) {
    let cachedDefault = null;
    try {
      cachedDefault = window.__odysseusDefaultChat || null;
    } catch (_) {}
    if (!cachedDefault || !cachedDefault.endpoint_url || !cachedDefault.model) {
      try {
        cachedDefault = JSON.parse(localStorage.getItem('odysseus-default-chat-cache') || 'null');
      } catch (_) {}
    }
    if (cachedDefault && cachedDefault.endpoint_url && cachedDefault.model) {
      modelId = cachedDefault.model;
      _deps.setPendingChat({
        url: cachedDefault.endpoint_url,
        modelId,
        endpointId: cachedDefault.endpoint_id || '',
        source: 'default',
      });
    }
  }
  // SECURITY: deliberately NOT auto-injecting `odysseus-model-favorites[0]`
  // here. localStorage favorites are per-browser, not per-user, so on a
  // shared browser the previous account's first favorited model would
  // silently pre-populate the chatbox of the next user that signed in. If
  // we have no session model and no pending-chat pick, fall through to
  // the "Select model" placeholder below.
  //
  // Check if selected model is still available — fall back ONLY for pending chats with no user selection
  // Never override an existing session's model — the user explicitly chose it
  if (
    modelId &&
    !currentSessionId &&
    _pendingChat &&
    _pendingChat.source !== 'manual' &&
    window.modelsModule &&
    window.modelsModule.getCachedItems
  ) {
    const items = window.modelsModule.getCachedItems();
    const allAvailable = [];
    items.forEach(item => {
      if (item.offline) return;
      (item.models || []).concat(item.models_extra || []).forEach(m => allAvailable.push(m));
    });
    if (allAvailable.length > 0 && !allAvailable.includes(modelId)) {
      // Model no longer available — switch to first available
      const fallback = items.find(item => !item.offline && (item.models || []).length > 0);
      if (fallback) {
        modelId = fallback.models[0];
        _deps.setPendingChat({ url: fallback.url, modelId, endpointId: fallback.endpoint_id, source: 'fallback' });
      }
    }
  }
  const latestPending = _deps.getPendingChat && _deps.getPendingChat();
  if (
    !currentSessionId &&
    !_autoSelectingDefault &&
    window.modelsModule &&
    window.modelsModule.getCachedItems &&
    (!modelId || (latestPending && latestPending.source === 'fallback'))
  ) {
    _ensureDefaultPendingChat();
  }

  const displayName = modelId ? modelId.split('/').pop() : 'Select model';
  // The header indicator clips long names with ellipsis; show the full model
  // identifier on hover (#1982). No tooltip on the "Select model" placeholder.
  label.title = modelId || '';
  const logo = modelId ? providerLogo(modelId) : null;
  if (logo) {
    label.innerHTML = '<span class="model-picker-logo">' + logo + '</span> ' + displayName;
  } else {
    label.textContent = displayName;
  }

  // Update Claude tier chips active state if rendered
  document.querySelectorAll('.tier-ver-chip').forEach(chip => {
    chip.classList.toggle('active', !!modelId && chip.dataset.mid === modelId);
  });
}
