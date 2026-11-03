// Projects page (sidebar > Projects): every project folder with its chat count and
// last activity, a filter, and one click to open it or start a chat in it.
// The folder data is the same one the sidebar uses; this only presents it.

const HIDDEN_FOLDERS = new Set(['Assistant', 'Tasks']);

/**
 * Projects from the session list plus any empty folders, most recently active first.
 * Archived chats don't count. Returns [{name, count, updatedAt, latestId}].
 */
export function summarizeProjects(sessions, folderNames = []) {
  const byName = new Map();
  for (const name of folderNames || []) {
    if (name && !HIDDEN_FOLDERS.has(name)) byName.set(name, { name, count: 0, updatedAt: '', latestId: null });
  }
  for (const s of Array.isArray(sessions) ? sessions : []) {
    const name = s && s.folder;
    if (!name || HIDDEN_FOLDERS.has(name) || s.archived) continue;
    const p = byName.get(name) || { name, count: 0, updatedAt: '', latestId: null };
    p.count += 1;
    const when = s.updated_at || s.created_at || '';
    if (!p.latestId || when > p.updatedAt) { p.updatedAt = when; p.latestId = s.id; }
    byName.set(name, p);
  }
  return [...byName.values()].sort((a, b) =>
    (b.updatedAt || '').localeCompare(a.updatedAt || '') || a.name.localeCompare(b.name));
}

/** "just now", "5 min ago", "3 h ago", "yesterday", "4 d ago", else a date. */
export function relativeTime(iso, now = Date.now()) {
  // The server sends UTC without a zone ("2026-11-03T14:31:00"); the browser would
  // read that as local time and show every chat hours old.
  const text = String(iso || '');
  const t = Date.parse(/T/.test(text) && !/(Z|[+-]\d\d:?\d\d)$/.test(text) ? text + 'Z' : text);
  if (!Number.isFinite(t)) return '';
  const minutes = Math.floor((now - t) / 60000);
  if (minutes < 1) return 'just now';
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} h ago`;
  const days = Math.floor(hours / 24);
  if (days === 1) return 'yesterday';
  if (days < 14) return `${days} d ago`;
  return new Date(t).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
}

export function filterProjects(projects, query) {
  const q = String(query || '').trim().toLowerCase();
  return q ? projects.filter(p => p.name.toLowerCase().includes(q)) : projects;
}

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

/**
 * Show the page. `getProjects()` returns fresh summaries each time it renders;
 * `onOpen(name)`, `onNewChat(name)` and `onNewProject()` do the work in the app.
 */
export function openProjectsPage({ getProjects, onOpen, onNewChat, onNewProject }) {
  closeProjectsPage();
  const modal = el('div', 'modal projects-modal');
  modal.id = 'projects-modal';
  const box = el('div', 'modal-content projects-modal-content');
  box.setAttribute('role', 'dialog');
  box.setAttribute('aria-label', 'Projects');

  const header = el('div', 'projects-header');
  header.appendChild(el('h2', 'projects-title', 'Projects'));
  const create = el('button', 'projects-new-btn', '+ New project');
  create.type = 'button';
  header.appendChild(create);
  const close = el('button', 'projects-close-btn', '×');
  close.type = 'button';
  close.setAttribute('aria-label', 'Close');
  header.appendChild(close);

  const search = el('input', 'projects-search');
  search.type = 'search';
  search.placeholder = 'Search projects';
  search.setAttribute('aria-label', 'Search projects');

  const list = el('div', 'projects-list');

  const render = () => {
    list.textContent = '';
    const all = getProjects();
    const shown = filterProjects(all, search.value);
    if (!shown.length) {
      list.appendChild(el('div', 'projects-empty', all.length
        ? 'No projects match that search.'
        : 'No projects yet. A project groups related chats, like a folder. Create one to get started.'));
      return;
    }
    for (const project of shown) {
      const card = el('div', 'projects-card');
      card.tabIndex = 0;
      card.setAttribute('role', 'button');
      card.setAttribute('aria-label', `Open project ${project.name}`);
      const text = el('div', 'projects-card-text');
      text.appendChild(el('div', 'projects-card-name', project.name));
      const when = relativeTime(project.updatedAt);
      const chats = `${project.count} chat${project.count === 1 ? '' : 's'}`;
      text.appendChild(el('div', 'projects-card-meta', when ? `${chats} · updated ${when}` : chats));
      card.appendChild(text);
      const fresh = el('button', 'projects-card-action', 'New chat');
      fresh.type = 'button';
      fresh.addEventListener('click', (e) => { e.stopPropagation(); closeProjectsPage(); onNewChat(project.name); });
      card.appendChild(fresh);
      const open = () => { closeProjectsPage(); onOpen(project.name); };
      card.addEventListener('click', open);
      card.addEventListener('keydown', (e) => {
        if (e.target === card && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); open(); }
      });
      list.appendChild(card);
    }
  };

  const onKey = (e) => { if (e.key === 'Escape') { e.stopPropagation(); closeProjectsPage(); } };
  modal.addEventListener('keydown', onKey);
  modal.addEventListener('mousedown', (e) => { if (e.target === modal) closeProjectsPage(); });
  close.addEventListener('click', closeProjectsPage);
  create.addEventListener('click', () => { closeProjectsPage(); onNewProject(); });
  search.addEventListener('input', render);

  box.append(header, search, list);
  modal.appendChild(box);
  document.body.appendChild(modal);
  render();
  search.focus();
}

export function closeProjectsPage() {
  const existing = document.getElementById('projects-modal');
  if (existing) existing.remove();
}
