/* Thread Detail View */

const ThreadDetail = {
  POSTS_PER_PAGE: 20,
  currentPage: 1,
  thread: null,

  async load(threadId, { silent = false } = {}) {
    const header = document.getElementById('thread-header');
    const postList = document.getElementById('post-list');
    const status = document.getElementById('detail-status');

    if (!silent) {
      header.innerHTML = '';
      postList.innerHTML = Array(3).fill('<div class="skeleton" aria-hidden="true"></div>').join('');
      status.textContent = '';
      App.headerTitle.textContent = 'Loading…';
    }

    const pageMatch = location.hash.match(/\/page\/(\d+)/);
    this.currentPage = pageMatch ? parseInt(pageMatch[1]) : 1;

    try {
      this.thread = await App.fetchJSON(`threads/${threadId}.json`);
      App.headerTitle.textContent = this.thread.title;

      if (!pageMatch) {
        const bookmark = App.getBookmark(threadId);
        if (bookmark) {
          this.currentPage = bookmark.page;
        }
      }

      this.renderAll();
    } catch (err) {
      header.innerHTML = '';
      postList.innerHTML = '';
      status.innerHTML = `
        <p>Couldn't load this thread.</p>
        <button type="button" class="retry-btn" id="detail-retry">Retry</button>
      `;
      App.headerTitle.textContent = 'Error';
      const btn = document.getElementById('detail-retry');
      if (btn) btn.addEventListener('click', () => this.load(threadId));
      console.error(err);
    }
  },

  renderAll() {
    const thread = this.thread;
    const header = document.getElementById('thread-header');
    const postList = document.getElementById('post-list');
    const status = document.getElementById('detail-status');

    const totalPosts = thread.posts.length;
    const totalPages = Math.ceil(totalPosts / this.POSTS_PER_PAGE);

    if (this.currentPage > totalPages) this.currentPage = totalPages;
    if (this.currentPage < 1) this.currentPage = 1;

    const bookmark = App.getBookmark(thread.id);
    const bookmarkHtml = bookmark
      ? `<button class="bookmark-btn bookmark-active" id="bookmark-btn" title="Bookmarked — tap to remove">Bookmarked</button>`
      : `<button class="bookmark-btn" id="bookmark-btn" title="Save your spot">Save spot</button>`;

    const eventLine = thread.eventDate || thread.eventName
      ? `<div class="thread-event-line">${
          thread.eventDate ? `<span class="event-date-badge">${App.escapeHtml(thread.eventDate)}</span>` : ''
        }${
          thread.eventName ? `<span>${App.escapeHtml(thread.eventName)}</span>` : ''
        }</div>`
      : '';

    const jumpBtn = totalPages > 1 && this.currentPage !== totalPages
      ? `<button class="bookmark-btn" id="jump-latest-btn" title="Jump to the newest posts">Latest &rarr;</button>`
      : '';

    header.innerHTML = `
      <div class="thread-header-top">
        <h2>${App.escapeHtml(thread.title)}</h2>
        <div class="thread-header-btns">
          ${jumpBtn}
          ${bookmarkHtml}
        </div>
      </div>
      ${eventLine}
      <div class="thread-meta">
        <span>${totalPosts} ${totalPosts === 1 ? 'post' : 'posts'}</span>
        ${totalPages > 1 ? `<span>Page ${this.currentPage} of ${totalPages}</span>` : ''}
      </div>
    `;

    document.getElementById('bookmark-btn').addEventListener('click', () => this.handleBookmark());
    const jumpEl = document.getElementById('jump-latest-btn');
    if (jumpEl) jumpEl.addEventListener('click', () => this.jumpToPage(totalPages));

    if (totalPosts === 0) {
      postList.innerHTML = '';
      status.textContent = 'No posts found.';
      return;
    }

    const start = (this.currentPage - 1) * this.POSTS_PER_PAGE;
    const end = start + this.POSTS_PER_PAGE;
    const pagePosts = thread.posts.slice(start, end);

    let html = '';
    if (totalPages > 1) html += this.renderPagination(totalPages, 'top');
    html += pagePosts.map((p, i) => this.renderPost(p, start + i)).join('');
    if (totalPages > 1) html += this.renderPagination(totalPages, 'bottom');

    postList.innerHTML = html;
    this.bindPaginationEvents();

    if (bookmark && bookmark.page === this.currentPage) {
      setTimeout(() => {
        const el = document.getElementById(`post-${bookmark.postId}`);
        if (el) {
          el.scrollIntoView({ behavior: 'smooth', block: 'center' });
          el.classList.add('post-highlighted');
          setTimeout(() => el.classList.remove('post-highlighted'), 2000);
        }
      }, 100);
    } else {
      header.scrollIntoView({ behavior: 'smooth' });
    }

    status.textContent = '';
  },

  jumpToPage(page) {
    this.currentPage = page;
    const threadId = this.thread.id;
    const newHash = page > 1 ? `thread/${threadId}/page/${page}` : `thread/${threadId}`;
    history.replaceState(null, '', '#' + newHash);
    this.renderAll();
  },

  handleBookmark() {
    const thread = this.thread;
    const existing = App.getBookmark(thread.id);

    if (existing) {
      App.clearBookmark(thread.id);
    } else {
      const posts = document.querySelectorAll('.post-card');
      let visiblePost = null;
      for (const post of posts) {
        const rect = post.getBoundingClientRect();
        if (rect.top >= 0) {
          visiblePost = post;
          break;
        }
      }
      const postId = visiblePost ? visiblePost.id.replace('post-', '') : '';
      App.setBookmark(thread.id, postId, this.currentPage);
    }

    this.renderAll();
  },

  renderPagination(totalPages, position) {
    const current = this.currentPage;
    const pages = [];

    for (let i = 1; i <= totalPages; i++) {
      if (i === 1 || i === totalPages || (i >= current - 1 && i <= current + 1)) {
        const active = i === current ? ' active' : '';
        const ariaCurrent = i === current ? ' aria-current="page"' : '';
        pages.push(`<button class="page-btn${active}" data-page="${i}"${ariaCurrent}>${i}</button>`);
      } else if (pages.length > 0 && !pages[pages.length - 1].includes('ellipsis')) {
        pages.push(`<span class="page-ellipsis" aria-hidden="true">&hellip;</span>`);
      }
    }

    return `
      <nav class="pagination pagination-${position}" aria-label="Thread pages">
        ${current > 1 ? `<button class="page-btn page-nav" data-page="${current - 1}" aria-label="Previous page">Prev</button>` : ''}
        <div class="page-numbers">${pages.join('')}</div>
        ${current < totalPages ? `<button class="page-btn page-nav" data-page="${current + 1}" aria-label="Next page">Next</button>` : ''}
      </nav>
    `;
  },

  bindPaginationEvents() {
    document.querySelectorAll('.page-btn').forEach(btn => {
      btn.addEventListener('click', (e) => {
        const page = parseInt(e.currentTarget.dataset.page);
        if (isNaN(page)) return;
        this.jumpToPage(page);
      });
    });
  },

  renderPost(post, globalIndex) {
    const time = post.timestamp
      ? App.formatTime(new Date(post.timestamp))
      : '';

    let content = App.escapeHtml(post.content);

    content = content.replace(
      /Predictions:\s*\d+\s*of\s*\d+\s*Pending[\s\S]*?(?:Tied for|Ranked)\s*[^\n]*/g,
      ''
    );
    content = content.replace(/^\s*\n+/, '');
    content = content.replace(/\n+\s*$/, '');
    content = content.replace(/\n{3,}/g, '\n\n');
    content = content.replace(/^(&gt; .+?)$/gm, '<span class="quote">$1</span>');

    const votes = [];
    if (post.upvotes > 0) votes.push(`<span class="vote-up" aria-label="${post.upvotes} upvotes">+${post.upvotes}</span>`);
    if (post.downvotes > 0) votes.push(`<span class="vote-down" aria-label="${post.downvotes} downvotes">-${post.downvotes}</span>`);

    const bookmark = App.getBookmark(this.thread.id);
    const isBookmarked = bookmark && bookmark.postId === post.id;
    const bookmarkMark = isBookmarked ? '<span class="bookmark-indicator">Saved spot</span>' : '';

    const postNumber = globalIndex + 1;

    return `
      <article class="post-card${isBookmarked ? ' post-bookmarked' : ''}" id="post-${App.escapeHtml(post.id)}">
        <div class="post-header">
          <div class="post-author-row">
            <span class="post-author">${App.escapeHtml(post.author)}</span>
            <span class="post-number">#${postNumber}</span>
            ${bookmarkMark}
          </div>
          <span class="post-time">${time}</span>
        </div>
        <div class="post-content">${content}</div>
        ${votes.length ? `<div class="post-footer">${votes.join(' ')}</div>` : ''}
      </article>
    `;
  }
};
