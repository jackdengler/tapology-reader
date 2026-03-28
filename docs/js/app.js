/* Tapology Forum Reader - App Router & Data Layer */

const App = {
  // Detect base path for GitHub Pages
  basePath: (() => {
    const path = location.pathname;
    // If hosted at /tapology-reader/ or similar
    const match = path.match(/^(\/[^/]+\/)/);
    return match ? match[1] : '/';
  })(),

  dataUrl(path) {
    return `${this.basePath}data/${path}`;
  },

  async fetchJSON(path) {
    const url = this.dataUrl(path);
    const resp = await fetch(url);
    if (!resp.ok) throw new Error(`Failed to fetch ${url}: ${resp.status}`);
    return resp.json();
  },

  init() {
    this.listView = document.getElementById('thread-list-view');
    this.detailView = document.getElementById('thread-detail-view');
    this.backBtn = document.getElementById('back-btn');
    this.refreshBtn = document.getElementById('refresh-btn');
    this.headerTitle = document.getElementById('header-title');
    this.lastUpdated = document.getElementById('last-updated');

    this.backBtn.addEventListener('click', () => {
      location.hash = '';
    });

    this.refreshBtn.addEventListener('click', () => {
      this.route();
    });

    window.addEventListener('hashchange', () => this.route());

    // Load meta
    this.loadMeta();

    // Register service worker
    if ('serviceWorker' in navigator) {
      navigator.serviceWorker.register(this.basePath + 'sw.js')
        .then(() => console.log('SW registered'))
        .catch(err => console.log('SW registration failed:', err));
    }

    this.route();
  },

  async loadMeta() {
    try {
      const meta = await this.fetchJSON('meta.json');
      if (meta.lastUpdated) {
        const d = new Date(meta.lastUpdated);
        this.lastUpdated.textContent = `Updated ${App.formatTime(d)}`;
      }
    } catch {
      // No meta yet
    }
  },

  route() {
    const hash = location.hash.slice(1);
    const threadMatch = hash.match(/^thread\/(\d+)/);

    if (threadMatch) {
      this.showDetail(threadMatch[1]);
    } else {
      this.showList();
    }
  },

  showList() {
    this.listView.hidden = false;
    this.detailView.hidden = true;
    this.backBtn.hidden = true;
    this.headerTitle.textContent = 'Tapology Forums';
    ThreadList.load();
  },

  showDetail(threadId) {
    this.listView.hidden = true;
    this.detailView.hidden = false;
    this.backBtn.hidden = false;
    ThreadDetail.load(threadId);
  },

  formatTime(date) {
    if (isNaN(date.getTime())) return '';
    const now = new Date();
    const isToday = date.toDateString() === now.toDateString();
    const yesterday = new Date(now);
    yesterday.setDate(yesterday.getDate() - 1);
    const isYesterday = date.toDateString() === yesterday.toDateString();

    const timeStr = date.toLocaleTimeString('en-US', {
      hour: 'numeric',
      minute: '2-digit',
      hour12: true,
    });

    if (isToday) return timeStr;
    if (isYesterday) return `Yesterday ${timeStr}`;

    const dateStr = date.toLocaleDateString('en-US', {
      month: 'short',
      day: 'numeric',
    });

    // Include year if not current year
    if (date.getFullYear() !== now.getFullYear()) {
      return `${date.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })} ${timeStr}`;
    }

    return `${dateStr} ${timeStr}`;
  },

  escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }
};

document.addEventListener('DOMContentLoaded', () => App.init());
