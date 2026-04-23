/* Thread List View */

const ThreadList = {
  threads: [],
  sortBy: 'latest',
  searchQuery: '',
  bound: false,
  _searchDebounce: null,

  async load({ silent = false } = {}) {
    const list = document.getElementById('thread-list');
    const status = document.getElementById('list-status');

    if (!silent) {
      list.innerHTML = Array(6).fill('<div class="skeleton" aria-hidden="true"></div>').join('');
      status.textContent = '';
    }

    try {
      this.threads = await App.fetchJSON('threads.json');
      this.render();
    } catch (err) {
      list.innerHTML = '';
      status.innerHTML = `
        <p>Couldn't load threads.</p>
        <button type="button" class="retry-btn" id="list-retry">Retry</button>
      `;
      const btn = document.getElementById('list-retry');
      if (btn) btn.addEventListener('click', () => this.load());
      console.error(err);
    }

    if (!this.bound) {
      this.bindEvents();
      this.bound = true;
    }
  },

  bindEvents() {
    const searchInput = document.getElementById('search-input');
    const clearBtn = document.getElementById('search-clear');

    searchInput.addEventListener('input', (e) => {
      const val = e.target.value;
      clearBtn.hidden = !val;

      // Debounce renders so typing feels smooth on long lists
      clearTimeout(this._searchDebounce);
      this._searchDebounce = setTimeout(() => {
        this.searchQuery = val.toLowerCase();
        this.render();
      }, 80);
    });

    searchInput.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') {
        searchInput.value = '';
        clearBtn.hidden = true;
        this.searchQuery = '';
        this.render();
        searchInput.blur();
      }
    });

    clearBtn.addEventListener('click', () => {
      searchInput.value = '';
      clearBtn.hidden = true;
      this.searchQuery = '';
      this.render();
      searchInput.focus();
    });

    document.querySelectorAll('.sort-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        document.querySelectorAll('.sort-btn').forEach(b => {
          b.classList.remove('active');
          b.setAttribute('aria-selected', 'false');
        });
        btn.classList.add('active');
        btn.setAttribute('aria-selected', 'true');
        this.sortBy = btn.dataset.sort;
        this.render();
      });
    });
  },

  getFiltered() {
    let filtered = [...this.threads];

    if (this.searchQuery) {
      filtered = filtered.filter(t =>
        t.title.toLowerCase().includes(this.searchQuery) ||
        (t.snippet && t.snippet.toLowerCase().includes(this.searchQuery)) ||
        (t.eventName && t.eventName.toLowerCase().includes(this.searchQuery))
      );
    }

    const sticky = filtered.filter(t => t.isSticky);
    const regular = filtered.filter(t => !t.isSticky);

    if (this.sortBy === 'replies') {
      regular.sort((a, b) => b.replyCount - a.replyCount);
    } else {
      regular.sort((a, b) => {
        const ta = new Date(a.lastPostTime || 0).getTime();
        const tb = new Date(b.lastPostTime || 0).getTime();
        return tb - ta;
      });
    }

    return [...sticky, ...regular];
  },

  render() {
    const list = document.getElementById('thread-list');
    const status = document.getElementById('list-status');
    const filtered = this.getFiltered();

    if (filtered.length === 0) {
      list.innerHTML = '';
      status.textContent = this.searchQuery
        ? `No threads match "${this.searchQuery}".`
        : 'No threads found.';
      return;
    }

    if (this.searchQuery) {
      status.textContent = `${filtered.length} ${filtered.length === 1 ? 'match' : 'matches'}`;
    } else {
      status.textContent = '';
    }

    list.innerHTML = filtered.map(t => this.renderCard(t)).join('');

    list.querySelectorAll('.thread-card').forEach(card => {
      card.addEventListener('click', () => {
        location.hash = `thread/${card.dataset.id}`;
      });
      card.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          location.hash = `thread/${card.dataset.id}`;
        }
      });
    });
  },

  renderCard(thread) {
    const time = thread.lastPostTime
      ? App.formatTime(new Date(thread.lastPostTime))
      : '';

    const icon = thread.iconUrl
      ? `<img class="thread-icon" src="${App.escapeHtml(thread.iconUrl)}" alt="" loading="lazy">`
      : `<div class="thread-icon placeholder" aria-hidden="true">&#128172;</div>`;

    const stickyClass = thread.isSticky ? ' sticky' : '';

    const bookmark = App.getBookmark(thread.id);
    const bookmarkBadge = bookmark
      ? `<span class="thread-bookmark-badge">Saved</span>`
      : '';

    const eventDate = thread.eventDate
      ? `<span class="event-date-badge">${App.escapeHtml(thread.eventDate)}</span>`
      : '';

    return `
      <div class="thread-card${stickyClass}" data-id="${App.escapeHtml(thread.id)}" role="button" tabindex="0" aria-label="Open thread ${App.escapeHtml(thread.title)}">
        ${icon}
        <div class="thread-info">
          <div class="thread-title-row">
            <div class="thread-title">${App.escapeHtml(thread.title)}</div>
            ${bookmarkBadge}
          </div>
          <div class="thread-meta">
            ${eventDate}
            <span>${thread.replyCount.toLocaleString()} ${thread.replyCount === 1 ? 'reply' : 'replies'}</span>
            ${time ? `<span>${time}</span>` : ''}
          </div>
        </div>
      </div>
    `;
  }
};
