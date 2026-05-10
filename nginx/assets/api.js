// assets/api.js
// Centralised helper for API calls and populating select elements

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
    if (arrayKey) {
      items = data[arrayKey];
    }
  }

  selectEl.innerHTML = '';
  
  if (items.length === 0) {
    const opt = document.createElement('option');
    opt.value = "";
    opt.textContent = "No items found";
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

// Global Active User Management
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

// Initialize the global user selector in the navbar
export async function initGlobalUserSelector() {
  const selector = document.getElementById('global-user-select');
  if (!selector) return;

  try {
    const users = await populateSelect(
      '/api/users', 
      selector, 
      (u) => `${u.full_name} (@${u.username})`, 
      (u) => u.id
    );

    // If no users, show a placeholder
    if (!users || users.length === 0) {
      selector.innerHTML = '<option value="">No users available</option>';
      return;
    }

    // Set the selected value to the active user if exists
    const currentId = getActiveUserId();
    if (currentId && Array.from(selector.options).some(o => o.value === currentId)) {
      selector.value = currentId;
    } else {
      // Default to first user if none selected
      selector.value = selector.options[0].value;
      setActiveUserId(selector.value);
    }

    // Listen for changes
    selector.addEventListener('change', (e) => {
      setActiveUserId(e.target.value);
      // Reload the page to reflect new user context
      window.location.reload();
    });

  } catch (err) {
    console.error('Failed to load global users:', err);
    selector.innerHTML = '<option value="">Error loading users</option>';
  }
}

// Helper to inject the global navbar into pages
export function renderNavbar(activePage) {
  const header = document.createElement('header');
  header.innerHTML = `
    <a href="/index.html" class="logo">⚡ <span>EventHub</span></a>
    <nav>
      <a href="/index.html" class="${activePage === 'home' ? 'active' : ''}">Dashboard</a>
      <a href="/users.html" class="${activePage === 'users' ? 'active' : ''}">Users</a>
      <a href="/events.html" class="${activePage === 'events' ? 'active' : ''}">Events</a>
      <a href="/registrations.html" class="${activePage === 'registrations' ? 'active' : ''}">My Registrations</a>
      <a href="/notifications.html" class="${activePage === 'notifications' ? 'active' : ''}">My Notifications</a>
    </nav>
    <div class="user-context">
      <span>Active User:</span>
      <select id="global-user-select">
        <option value="">Loading...</option>
      </select>
    </div>
  `;
  document.body.prepend(header);
  initGlobalUserSelector();
}
