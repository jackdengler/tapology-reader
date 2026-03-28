/* Tapology Forum Reader - App Router & Data Layer */

const App = {
  // Detect base path for GitHub Pages
  basePath: (() => {
    const path = location.pathname;
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

  AUTO_REFRESH_MS: 5 * 60 * 1000, // 5 minutes
  _refreshTimer: null,

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

    this.loadMeta();

    if ('serviceWorker' in navigator) {
      navigator.serviceWorker.register(this.basePath + 'sw.js')
        .then(() => console.log('SW registered'))
        .catch(err => console.log('SW registration failed:', err));
    }

    this.route();
    this.startAutoRefresh();
  },

  startAutoRefresh() {
    if (this._refreshTimer) clearInterval(this._refreshTimer);
    this._refreshTimer = setInterval(() => {
      this.loadMeta();
      this.route();
    }, this.AUTO_REFRESH_MS);

    // Pause when tab is hidden, resume when visible
    document.addEventListener('visibilitychange', () => {
      if (document.hidden) {
        clearInterval(this._refreshTimer);
        this._refreshTimer = null;
      } else {
        this.loadMeta();
        this.route();
        this.startAutoRefresh();
      }
    });
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

  // Always display in Pacific Time
  formatTime(date) {
    if (isNaN(date.getTime())) return '';
    const opts = {
      hour: 'numeric',
      minute: '2-digit',
      hour12: true,
      timeZone: 'America/Los_Angeles',
    };

    const now = new Date();
    // Compare dates in PT
    const todayPT = now.toLocaleDateString('en-US', { timeZone: 'America/Los_Angeles' });
    const datePT = date.toLocaleDateString('en-US', { timeZone: 'America/Los_Angeles' });

    const yesterday = new Date(now);
    yesterday.setDate(yesterday.getDate() - 1);
    const yesterdayPT = yesterday.toLocaleDateString('en-US', { timeZone: 'America/Los_Angeles' });

    const timeStr = date.toLocaleTimeString('en-US', opts) + ' PT';

    if (datePT === todayPT) return timeStr;
    if (datePT === yesterdayPT) return `Yesterday ${timeStr}`;

    const dateStr = date.toLocaleDateString('en-US', {
      month: 'short',
      day: 'numeric',
      timeZone: 'America/Los_Angeles',
    });

    if (date.getFullYear() !== now.getFullYear()) {
      return `${date.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric', timeZone: 'America/Los_Angeles' })} ${timeStr}`;
    }

    return `${dateStr} ${timeStr}`;
  },

  escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  },

  // Bookmark helpers — saves to localStorage
  getBookmark(threadId) {
    try {
      const data = JSON.parse(localStorage.getItem('tapforum_bookmarks') || '{}');
      return data[threadId] || null;
    } catch { return null; }
  },

  setBookmark(threadId, postId, page) {
    try {
      const data = JSON.parse(localStorage.getItem('tapforum_bookmarks') || '{}');
      data[threadId] = { postId, page, savedAt: Date.now() };
      localStorage.setItem('tapforum_bookmarks', JSON.stringify(data));
    } catch {}
  },

  clearBookmark(threadId) {
    try {
      const data = JSON.parse(localStorage.getItem('tapforum_bookmarks') || '{}');
      delete data[threadId];
      localStorage.setItem('tapforum_bookmarks', JSON.stringify(data));
    } catch {}
  }
};

document.addEventListener('DOMContentLoaded', () => App.init());
