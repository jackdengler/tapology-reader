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
    this.offlineBanner = document.getElementById('offline-banner');

    this.backBtn.addEventListener('click', () => {
      // Prefer real browser back so we restore scroll position / history state,
      // fall back to clearing the hash if we got here directly.
      if (history.length > 1 && document.referrer.includes(location.host)) {
        history.back();
      } else {
        location.hash = '';
      }
    });

    this.refreshBtn.addEventListener('click', () => {
      this.refreshBtn.classList.add('spinning');
      this.loadMeta();
      this.route({ force: true });
      setTimeout(() => this.refreshBtn.classList.remove('spinning'), 600);
    });

    // Tap the header title to scroll back to top
    this.headerTitle.addEventListener('click', () => {
      window.scrollTo({ top: 0, behavior: 'smooth' });
    });

    // Global keyboard shortcuts
    document.addEventListener('keydown', (e) => {
      if (e.target.matches('input, textarea')) return;
      if (e.key === '/') {
        const search = document.getElementById('search-input');
        if (search && !this.listView.hidden) {
          e.preventDefault();
          search.focus();
        }
      } else if (e.key === 'Escape' && !this.detailView.hidden) {
        this.backBtn.click();
      } else if (e.key === 'r' && !e.metaKey && !e.ctrlKey) {
        this.refreshBtn.click();
      }
    });

    window.addEventListener('hashchange', () => this.route());
    window.addEventListener('online', () => this.setOnline(true));
    window.addEventListener('offline', () => this.setOnline(false));
    this.setOnline(navigator.onLine);

    this.loadMeta();

    if ('serviceWorker' in navigator) {
      navigator.serviceWorker.register(this.basePath + 'sw.js')
        .then(() => console.log('SW registered'))
        .catch(err => console.log('SW registration failed:', err));
    }

    this.route();
    this.startAutoRefresh();
  },

  setOnline(isOnline) {
    this.offlineBanner.hidden = isOnline;
  },

  startAutoRefresh() {
    if (this._refreshTimer) clearInterval(this._refreshTimer);
    this._refreshTimer = setInterval(() => {
      // Only refresh the list view silently — don't yank the user mid-scroll
      // on a thread detail.
      this.loadMeta();
      if (!this.listView.hidden) this.route({ silent: true });
    }, this.AUTO_REFRESH_MS);

    document.addEventListener('visibilitychange', () => {
      if (document.hidden) {
        clearInterval(this._refreshTimer);
        this._refreshTimer = null;
      } else {
        this.loadMeta();
        if (!this.listView.hidden) this.route({ silent: true });
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

  route(opts = {}) {
    const hash = location.hash.slice(1);
    const threadMatch = hash.match(/^thread\/(\d+)/);

    if (threadMatch) {
      this.showDetail(threadMatch[1], opts);
    } else {
      this.showList(opts);
    }
  },

  showList(opts = {}) {
    this.listView.hidden = false;
    this.detailView.hidden = true;
    this.backBtn.hidden = true;
    this.headerTitle.textContent = 'Tapology Forums';
    ThreadList.load(opts);
  },

  showDetail(threadId, opts = {}) {
    this.listView.hidden = true;
    this.detailView.hidden = false;
    this.backBtn.hidden = false;
    ThreadDetail.load(threadId, opts);
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
