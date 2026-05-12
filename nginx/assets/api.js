const AUTH_KEY = 'eventhub_auth';

export function getAuth() {
  const raw = localStorage.getItem(AUTH_KEY);
  if (!raw) return null;
  try {
    const data = JSON.parse(raw);
    if (data.token && data.user) return data;
    clearAuth();
    return null;
  } catch {
    clearAuth();
    return null;
  }
}

export function setAuth(token, user) {
  localStorage.setItem(AUTH_KEY, JSON.stringify({ token, user }));
}

export function clearAuth() {
  localStorage.removeItem(AUTH_KEY);
}

export function getToken() {
  const auth = getAuth();
  return auth ? auth.token : null;
}

export function getCurrentUser() {
  const auth = getAuth();
  return auth ? auth.user : null;
}

export function getUserId() {
  const user = getCurrentUser();
  return user ? user.id : null;
}

export function getUserRole() {
  const user = getCurrentUser();
  return user ? user.role : null;
}

export function isSuperAdmin() {
  return getUserRole() === 'super_admin';
}

export function isOrganizer() {
  return getUserRole() === 'organizer' || getUserRole() === 'super_admin';
}

export function isLoggedIn() {
  return !!getAuth();
}

export function requireAuth() {
  if (!isLoggedIn()) {
    window.location.href = '/auth.html';
    return false;
  }
  return true;
}

export async function login(email, password) {
  const data = await apiCall('/api/users/login', 'POST', { email, password }, false);
  setAuth(data.token, data.user);
  return data;
}

export async function register(userData) {
  const data = await apiCall('/api/users/register', 'POST', userData, false);
  return data;
}

export function logout() {
  clearAuth();
  window.location.href = '/auth.html';
}

export async function apiCall(url, method = 'GET', body = null, authRequired = true) {
  if (authRequired && !getToken()) {
    window.location.href = '/auth.html';
    throw new Error('Authentication required');
  }

  const opts = {
    method,
    headers: { 'Content-Type': 'application/json' },
  };

  const token = getToken();
  if (token) {
    opts.headers['Authorization'] = `Bearer ${token}`;
  }

  if (body) opts.body = JSON.stringify(body);

  const resp = await fetch(url, opts);

  if (resp.status === 401 && authRequired) {
    clearAuth();
    window.location.href = '/auth.html';
    throw new Error('Session expired');
  }

  if (!resp.ok) {
    let msg = `HTTP ${resp.status}`;
    try {
      const errData = await resp.json();
      msg = errData.detail || errData.message || errData.error || msg;
    } catch {
      try { msg += ': ' + await resp.text(); } catch {}
    }
    throw new Error(msg);
  }

  if (resp.status === 204) return null;
  return resp.json();
}

export function getInitials(name) {
  if (!name) return '?';
  return name.split(' ').map(w => w[0]).join('').toUpperCase().slice(0, 2);
}

const avatarColors = ['purple', 'blue', 'green', 'yellow', 'red'];
export function getAvatarColor(id) {
  return avatarColors[(id - 1) % avatarColors.length];
}

export function showToast(message, type = 'info') {
  let container = document.querySelector('.toast-container');
  if (!container) {
    container = document.createElement('div');
    container.className = 'toast-container';
    document.body.appendChild(container);
  }
  const toast = document.createElement('div');
  toast.className = `toast ${type}`;
  toast.textContent = message;
  container.appendChild(toast);
  setTimeout(() => {
    toast.style.animation = 'toastOut 0.3s ease-in forwards';
    setTimeout(() => toast.remove(), 300);
  }, 3500);
}

export function formatRelativeTime(dateStr) {
  const date = new Date(dateStr);
  const now = new Date();
  const diff = Math.floor((now - date) / 1000);
  if (diff < 60) return 'Just now';
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 86400)}d ago`;
  return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}

export function formatCurrency(amount) {
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(amount);
}

export function getEventTypeIcon(type) {
  const icons = { conference: '🎤', workshop: '🛠️', seminar: '📚' };
  return icons[type] || '📅';
}

export function showConfirm(message) {
  return new Promise((resolve) => {
    const overlay = document.createElement('div');
    overlay.className = 'modal-overlay active';
    overlay.innerHTML = `
      <div class="modal">
        <div class="modal-header">
          <h3>Confirm Action</h3>
        </div>
        <div class="modal-body">
          <p>${message}</p>
        </div>
        <div class="modal-footer">
          <button class="btn secondary modal-cancel">Cancel</button>
          <button class="btn danger modal-confirm">Confirm</button>
        </div>
      </div>
    `;
    document.body.appendChild(overlay);
    overlay.querySelector('.modal-cancel').onclick = () => { overlay.remove(); resolve(false); };
    overlay.querySelector('.modal-confirm').onclick = () => { overlay.remove(); resolve(true); };
    overlay.addEventListener('click', (e) => { if (e.target === overlay) { overlay.remove(); resolve(false); } });
  });
}

export function openModal(title, bodyHtml, footerHtml = '') {
  const overlay = document.createElement('div');
  overlay.className = 'modal-overlay active';
  overlay.innerHTML = `
    <div class="modal modal-lg">
      <div class="modal-header">
        <h3>${title}</h3>
        <button class="btn secondary modal-close-btn" style="padding:0.3rem 0.6rem;font-size:0.8rem;">✕</button>
      </div>
      <div class="modal-body">${bodyHtml}</div>
      ${footerHtml ? `<div class="modal-footer">${footerHtml}</div>` : ''}
    </div>
  `;
  document.body.appendChild(overlay);
  overlay.querySelector('.modal-close-btn').onclick = () => overlay.remove();
  overlay.addEventListener('click', (e) => { if (e.target === overlay) overlay.remove(); });
  return overlay;
}

export function renderPagination(container, currentPage, totalPages, onPageChange) {
  if (totalPages <= 1) { container.innerHTML = ''; return; }
  let html = '<div class="pagination">';
  html += `<button class="btn secondary" ${currentPage <= 1 ? 'disabled' : ''} data-page="${currentPage - 1}">Prev</button>`;
  const maxVisible = 5;
  let start = Math.max(1, currentPage - Math.floor(maxVisible / 2));
  let end = Math.min(totalPages, start + maxVisible - 1);
  if (end - start + 1 < maxVisible) start = Math.max(1, end - maxVisible + 1);
  if (start > 1) html += `<button class="btn secondary" data-page="1">1</button>`;
  if (start > 2) html += '<span class="pagination-ellipsis">...</span>';
  for (let i = start; i <= end; i++) {
    html += `<button class="btn ${i === currentPage ? 'primary' : 'secondary'}" data-page="${i}">${i}</button>`;
  }
  if (end < totalPages - 1) html += '<span class="pagination-ellipsis">...</span>';
  if (end < totalPages) html += `<button class="btn secondary" data-page="${totalPages}">${totalPages}</button>`;
  html += `<button class="btn secondary" ${currentPage >= totalPages ? 'disabled' : ''} data-page="${currentPage + 1}">Next</button>`;
  html += '</div>';
  container.innerHTML = html;
  container.querySelectorAll('[data-page]').forEach(btn => {
    btn.addEventListener('click', () => {
      const p = parseInt(btn.getAttribute('data-page'));
      if (p >= 1 && p <= totalPages && p !== currentPage) onPageChange(p);
    });
  });
}

const navItems = [
  { key: 'home', label: 'Dashboard', href: '/index.html', icon: '◉', roles: null },
  { key: 'events', label: 'Events', href: '/events.html', icon: '◇', roles: null },
  { key: 'registrations', label: 'Tickets', href: '/registrations.html', icon: '▤', roles: null },
  { key: 'notifications', label: 'Alerts', href: '/notifications.html', icon: '◉', roles: null },
  { key: 'users', label: 'Users', href: '/users.html', icon: '◎', roles: null },
];

export function renderNavbar(activePage) {
  const existing = document.querySelector('header');
  if (existing) existing.remove();

  const header = document.createElement('header');
  const user = getCurrentUser();
  const role = getUserRole();

  const visibleNavItems = navItems.filter(n => !n.roles || n.roles.includes(role));
  const navLinks = visibleNavItems.map(n =>
    `<a href="${n.href}" class="${activePage === n.key ? 'active' : ''}">${n.label}</a>`
  ).join('');

  const roleBadge = role === 'super_admin' ? '<span class="badge danger" style="font-size:0.6rem;">Admin</span>'
    : role === 'organizer' ? '<span class="badge warning" style="font-size:0.6rem;">Organizer</span>'
    : '<span class="badge info" style="font-size:0.6rem;">Attendee</span>';

  const notifBadge = user ? `<span class="nav-notif-badge" id="nav-notif-count" style="display:none;">0</span>` : '';

  header.innerHTML = `
    <a href="/index.html" class="logo">
      <div class="logo-icon">⚡</div>
      <span>EventHub</span>
    </a>
    <button class="mobile-menu-btn" id="mobile-menu-btn">☰</button>
    <nav class="desktop-nav">${navLinks}</nav>
    <div class="user-context">
      ${user ? `
        <div class="user-info" id="user-info-btn">
          <div class="avatar ${getAvatarColor(user.id)}" style="width:32px;height:32px;font-size:0.75rem;">${getInitials(user.full_name)}</div>
          <div class="user-info-text">
            <span class="user-info-name">${user.full_name}</span>
            ${roleBadge}
          </div>
        </div>
        <button class="btn secondary" id="logout-btn" style="padding:0.35rem 0.7rem;font-size:0.8rem;">Logout</button>
      ` : `
        <a href="/auth.html" class="btn" style="padding:0.4rem 0.9rem;font-size:0.85rem;">Sign In</a>
      `}
    </div>
    <nav class="mobile-nav" id="mobile-nav">${navLinks}</nav>
  `;

  document.body.prepend(header);

  const logoutBtn = document.getElementById('logout-btn');
  if (logoutBtn) logoutBtn.addEventListener('click', logout);

  const mobileBtn = document.getElementById('mobile-menu-btn');
  const mobileNav = document.getElementById('mobile-nav');
  if (mobileBtn && mobileNav) {
    mobileBtn.addEventListener('click', () => {
      mobileNav.classList.toggle('open');
    });
  }

  loadNotifBadge();
}

async function loadNotifBadge() {
  const userId = getUserId();
  if (!userId) return;
  try {
    const data = await apiCall(`/api/notifications/user/${userId}?unread_only=true`, 'GET', null, true);
    const count = (data.notifications || []).length;
    const badge = document.getElementById('nav-notif-count');
    if (badge && count > 0) {
      badge.textContent = count > 9 ? '9+' : count;
      badge.style.display = 'inline-flex';
    }
  } catch {}
}

export async function refreshCurrentUser() {
  try {
    const data = await apiCall('/api/users/me');
    const auth = getAuth();
    if (auth) {
      auth.user = data.user || data;
      localStorage.setItem(AUTH_KEY, JSON.stringify(auth));
    }
    return auth.user;
  } catch { return null; }
}
