/* Thread Detail View */

const ThreadDetail = {
  POSTS_PER_PAGE: 20,
  currentPage: 1,
  thread: null,

  async load(threadId) {
    const header = document.getElementById('thread-header');
    const postList = document.getElementById('post-list');
    const status = document.getElementById('detail-status');

    header.innerHTML = '';
    postList.innerHTML = Array(3).fill('<div class="skeleton"></div>').join('');
    status.textContent = '';
    App.headerTitle.textContent = 'Loading...';

    // Check for page in hash
    const pageMatch = location.hash.match(/\/page\/(\d+)/);
    this.currentPage = pageMatch ? parseInt(pageMatch[1]) : 1;

    try {
      this.thread = await App.fetchJSON(`threads/${threadId}.json`);
      App.headerTitle.textContent = this.thread.title;

      // If there's a bookmark and no explicit page in hash, jump to bookmarked page
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
      status.textContent = 'Failed to load thread.';
      App.headerTitle.textContent = 'Error';
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

    // Check for bookmark
    const bookmark = App.getBookmark(thread.id);
    const bookmarkHtml = bookmark
      ? `<button class="bookmark-btn bookmark-active" id="bookmark-btn" title="Bookmarked at post">Bookmarked</button>`
      : `<button class="bookmark-btn" id="bookmark-btn" title="Save your spot">Save Spot</button>`;

    header.innerHTML = `
      <div class="thread-header-top">
        <h2>${App.escapeHtml(thread.title)}</h2>
        ${bookmarkHtml}
      </div>
      <div class="thread-meta">
        <span>${totalPosts} posts</span>
        ${totalPages > 1 ? `<span>Page ${this.currentPage} of ${totalPages}</span>` : ''}
      </div>
    `;

    // Bind bookmark button
    document.getElementById('bookmark-btn').addEventListener('click', () => this.handleBookmark());

    if (totalPosts === 0) {
      postList.innerHTML = '';
      status.textContent = 'No posts found.';
      return;
    }

    // Get posts for current page
    const start = (this.currentPage - 1) * this.POSTS_PER_PAGE;
    const end = start + this.POSTS_PER_PAGE;
    const pagePosts = thread.posts.slice(start, end);

    let html = '';

    // Top pagination
    if (totalPages > 1) {
      html += this.renderPagination(totalPages, 'top');
    }

    // Posts
    html += pagePosts.map((p, i) => this.renderPost(p, start + i)).join('');

    // Bottom pagination
    if (totalPages > 1) {
      html += this.renderPagination(totalPages, 'bottom');
    }

    postList.innerHTML = html;
    this.bindPaginationEvents();

    // If we have a bookmark, scroll to the bookmarked post
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

  handleBookmark() {
    const thread = this.thread;
    const existing = App.getBookmark(thread.id);

    if (existing) {
      App.clearBookmark(thread.id);
    } else {
      // Find the first visible post
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
    // Smart page range — show nearby pages, ellipsis for distant ones
    const current = this.currentPage;
    const pages = [];

    for (let i = 1; i <= totalPages; i++) {
      if (i === 1 || i === totalPages || (i >= current - 1 && i <= current + 1)) {
        const active = i === current ? ' active' : '';
        pages.push(`<button class="page-btn${active}" data-page="${i}">${i}</button>`);
      } else if (pages.length > 0 && !pages[pages.length - 1].includes('ellipsis')) {
        pages.push(`<span class="page-ellipsis">...</span>`);
      }
    }

    return `
      <div class="pagination pagination-${position}">
        ${current > 1 ? `<button class="page-btn page-nav" data-page="${current - 1}">Prev</button>` : ''}
        <div class="page-numbers">${pages.join('')}</div>
        ${current < totalPages ? `<button class="page-btn page-nav" data-page="${current + 1}">Next</button>` : ''}
      </div>
    `;
  },

  bindPaginationEvents() {
    document.querySelectorAll('.page-btn').forEach(btn => {
      btn.addEventListener('click', (e) => {
        const page = parseInt(e.target.dataset.page);
        if (isNaN(page)) return;
        this.currentPage = page;
        const threadId = this.thread.id;
        const newHash = page > 1 ? `thread/${threadId}/page/${page}` : `thread/${threadId}`;
        history.replaceState(null, '', '#' + newHash);
        this.renderAll();
      });
    });
  },

  renderPost(post, globalIndex) {
    const time = post.timestamp
      ? App.formatTime(new Date(post.timestamp))
      : '';

    // Clean content
    let content = App.escapeHtml(post.content);

    // Remove prediction blocks entirely
    content = content.replace(
      /Predictions:\s*\d+\s*of\s*\d+\s*Pending[\s\S]*?(?:Tied for|Ranked)\s*[^\n]*/g,
      ''
    );

    // Remove leading blank lines
    content = content.replace(/^\s*\n+/, '');

    // Remove trailing blank lines
    content = content.replace(/\n+\s*$/, '');

    // Collapse excessive blank lines in middle
    content = content.replace(/\n{3,}/g, '\n\n');

    // Format quoted text
    content = content.replace(
      /^(&gt; .+?)$/gm,
      '<span class="quote">$1</span>'
    );

    const votes = [];
    if (post.upvotes > 0) votes.push(`<span class="vote-up">+${post.upvotes}</span>`);
    if (post.downvotes > 0) votes.push(`<span class="vote-down">-${post.downvotes}</span>`);

    // Check if this post is bookmarked
    const bookmark = App.getBookmark(this.thread.id);
    const isBookmarked = bookmark && bookmark.postId === post.id;
    const bookmarkMark = isBookmarked ? '<span class="bookmark-indicator">Saved spot</span>' : '';

    return `
      <div class="post-card${isBookmarked ? ' post-bookmarked' : ''}" id="post-${App.escapeHtml(post.id)}">
        <div class="post-header">
          <div class="post-author-row">
            <span class="post-author">${App.escapeHtml(post.author)}</span>
            ${bookmarkMark}
          </div>
          <span class="post-time">${time}</span>
        </div>
        <div class="post-content">${content}</div>
        ${votes.length ? `<div class="post-footer">${votes.join(' ')}</div>` : ''}
      </div>
    `;
  }
};
