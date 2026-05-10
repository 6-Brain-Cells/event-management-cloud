export async function apiCall(url, method = 'GET', body = null) {
  const opts = {
    method,
    headers: { 'Content-Type': 'application/json' },
  };
  if (body) opts.body = JSON.stringify(body);
  const resp = await fetch(url, opts);
  if (!resp.ok) {
    const txt = await resp.text();
    throw new Error(`HTTP ${resp.status}: ${txt}`);
  }
  return resp.json();
}

export async function populateSelect(endpoint, selectEl, labelFn, valueFn) {
  const data = await apiCall(endpoint);
  let items = [];
  if (Array.isArray(data)) {
    items = data;
  } else if (data && typeof data === 'object') {
    const arrayKey = Object.keys(data).find(key => Array.isArray(data[key]));
    if (arrayKey) items = data[arrayKey];
  }

  selectEl.innerHTML = '';
  if (items.length === 0) {
    const opt = document.createElement('option');
    opt.value = '';
    opt.textContent = 'No items found';
    selectEl.appendChild(opt);
    return items;
  }

  items.forEach(item => {
    const opt = document.createElement('option');
    opt.value = valueFn(item);
    opt.textContent = labelFn(item);
    selectEl.appendChild(opt);
  });
  return items;
}

export function getActiveUserId() {
  return localStorage.getItem('activeUserId');
}

export function setActiveUserId(id) {
  if (id) {
    localStorage.setItem('activeUserId', id);
  } else {
    localStorage.removeItem('activeUserId');
  }
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
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  if (diff < 604800) return `${Math.floor(diff / 86400)}d ago`;
  return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}

export function formatCurrency(amount) {
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(amount);
}

export function getEventTypeIcon(type) {
  const icons = { conference: '🎤', workshop: '🛠️', seminar: '📚' };
  return icons[type] || '📅';
}

const navItems = [
  { key: 'home', label: 'Dashboard', href: '/index.html', icon: '◉' },
  { key: 'users', label: 'Users', href: '/users.html', icon: '◎' },
  { key: 'events', label: 'Events', href: '/events.html', icon: '◇' },
  { key: 'registrations', label: 'Tickets', href: '/registrations.html', icon: '▤' },
  { key: 'notifications', label: 'Alerts', href: '/notifications.html', icon: '◉' },
];

async function initGlobalUserSelector() {
  const selector = document.getElementById('global-user-select');
  if (!selector) return;

  try {
    const users = await populateSelect(
      '/api/users',
      selector,
      (u) => `${u.full_name} (@${u.username})`,
      (u) => u.id
    );

    if (!users || users.length === 0) {
      selector.innerHTML = '<option value="">No users yet</option>';
      return;
    }

    const currentId = getActiveUserId();
    if (currentId && Array.from(selector.options).some(o => o.value === currentId)) {
      selector.value = currentId;
    } else {
      selector.value = selector.options[0].value;
      setActiveUserId(selector.value);
    }

    selector.addEventListener('change', (e) => {
      setActiveUserId(e.target.value);
      window.location.reload();
    });
  } catch (err) {
    selector.innerHTML = '<option value="">Error loading</option>';
  }
}

export function renderNavbar(activePage) {
  const header = document.createElement('header');
  const navLinks = navItems.map(n =>
    `<a href="${n.href}" class="${activePage === n.key ? 'active' : ''}">${n.label}</a>`
  ).join('');

  header.innerHTML = `
    <a href="/index.html" class="logo">
      <div class="logo-icon">⚡</div>
      <span>EventHub</span>
    </a>
    <nav>${navLinks}</nav>
    <div class="user-context">
      <span class="user-context-label">Profile:</span>
      <select id="global-user-select">
        <option value="">Loading...</option>
      </select>
    </div>
  `;
  document.body.prepend(header);
  initGlobalUserSelector();
}
