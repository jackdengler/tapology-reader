/* Thread List View */

const ThreadList = {
  threads: [],
  sortBy: 'latest',
  searchQuery: '',
  bound: false,

  async load() {
    const list = document.getElementById('thread-list');
    const status = document.getElementById('list-status');

    list.innerHTML = Array(6).fill('<div class="skeleton"></div>').join('');
    status.textContent = '';

    try {
      this.threads = await App.fetchJSON('threads.json');
      this.render();
    } catch (err) {
      list.innerHTML = '';
      status.textContent = 'Failed to load threads. Tap refresh to retry.';
      console.error(err);
    }

    if (!this.bound) {
      this.bindEvents();
      this.bound = true;
    }
  },

  bindEvents() {
    const searchInput = document.getElementById('search-input');
    searchInput.addEventListener('input', (e) => {
      this.searchQuery = e.target.value.toLowerCase();
      this.render();
    });

    document.querySelectorAll('.sort-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        document.querySelectorAll('.sort-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
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
        (t.snippet && t.snippet.toLowerCase().includes(this.searchQuery))
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
      status.textContent = this.searchQuery ? 'No threads match your search.' : 'No threads found.';
      return;
    }

    status.textContent = '';
    list.innerHTML = filtered.map(t => this.renderCard(t)).join('');

    list.querySelectorAll('.thread-card').forEach(card => {
      card.addEventListener('click', () => {
        location.hash = `thread/${card.dataset.id}`;
      });
    });
  },

  renderCard(thread) {
    const time = thread.lastPostTime
      ? App.formatTime(new Date(thread.lastPostTime))
      : '';

    const icon = thread.iconUrl
      ? `<img class="thread-icon" src="${App.escapeHtml(thread.iconUrl)}" alt="" loading="lazy">`
      : `<div class="thread-icon placeholder">&#128172;</div>`;

    const stickyClass = thread.isSticky ? ' sticky' : '';

    // Check for bookmark
    const bookmark = App.getBookmark(thread.id);
    const bookmarkBadge = bookmark
      ? `<span class="thread-bookmark-badge">Saved</span>`
      : '';

    return `
      <div class="thread-card${stickyClass}" data-id="${App.escapeHtml(thread.id)}">
        ${icon}
        <div class="thread-info">
          <div class="thread-title-row">
            <div class="thread-title">${App.escapeHtml(thread.title)}</div>
            ${bookmarkBadge}
          </div>
          <div class="thread-meta">
            <span>${thread.replyCount.toLocaleString()} replies</span>
            ${time ? `<span>${time}</span>` : ''}
          </div>
        </div>
      </div>
    `;
  }
};
