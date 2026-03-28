/* Thread Detail View */

const ThreadDetail = {
  POSTS_PER_PAGE: 20,
  currentPage: 1,
  thread: null,

  async load(threadId) {
    const header = document.getElementById('thread-header');
    const postList = document.getElementById('post-list');
    const status = document.getElementById('detail-status');

    // Show loading
    header.innerHTML = '';
    postList.innerHTML = Array(3).fill('<div class="skeleton"></div>').join('');
    status.textContent = '';
    App.headerTitle.textContent = 'Loading...';

    // Check for page in hash (e.g., #thread/123/page/2)
    const pageMatch = location.hash.match(/\/page\/(\d+)/);
    this.currentPage = pageMatch ? parseInt(pageMatch[1]) : 1;

    try {
      this.thread = await App.fetchJSON(`threads/${threadId}.json`);
      App.headerTitle.textContent = this.thread.title;
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

    // Clamp page
    if (this.currentPage > totalPages) this.currentPage = totalPages;
    if (this.currentPage < 1) this.currentPage = 1;

    header.innerHTML = `
      <h2>${App.escapeHtml(thread.title)}</h2>
      <div class="thread-meta">
        <span>${totalPosts} posts</span>
        ${totalPages > 1 ? `<span>Page ${this.currentPage} of ${totalPages}</span>` : ''}
      </div>
    `;

    if (totalPosts === 0) {
      postList.innerHTML = '';
      status.textContent = 'No posts found.';
      return;
    }

    // Get posts for current page
    const start = (this.currentPage - 1) * this.POSTS_PER_PAGE;
    const end = start + this.POSTS_PER_PAGE;
    const pagePosts = thread.posts.slice(start, end);

    postList.innerHTML = pagePosts.map(p => this.renderPost(p)).join('');

    // Render pagination if needed
    if (totalPages > 1) {
      postList.innerHTML += this.renderPagination(totalPages);
      this.bindPaginationEvents();
    }

    status.textContent = '';

    // Scroll to top of posts
    header.scrollIntoView({ behavior: 'smooth' });
  },

  renderPagination(totalPages) {
    const pages = [];
    for (let i = 1; i <= totalPages; i++) {
      const active = i === this.currentPage ? ' active' : '';
      pages.push(`<button class="page-btn${active}" data-page="${i}">${i}</button>`);
    }

    return `
      <div class="pagination">
        ${this.currentPage > 1 ? `<button class="page-btn page-prev" data-page="${this.currentPage - 1}">&larr; Prev</button>` : ''}
        ${pages.join('')}
        ${this.currentPage < totalPages ? `<button class="page-btn page-next" data-page="${this.currentPage + 1}">Next &rarr;</button>` : ''}
      </div>
    `;
  },

  bindPaginationEvents() {
    document.querySelectorAll('.page-btn').forEach(btn => {
      btn.addEventListener('click', (e) => {
        const page = parseInt(e.target.dataset.page);
        this.currentPage = page;
        // Update hash without triggering full reload
        const threadId = this.thread.id;
        const newHash = page > 1 ? `thread/${threadId}/page/${page}` : `thread/${threadId}`;
        history.replaceState(null, '', '#' + newHash);
        this.renderAll();
      });
    });
  },

  renderPost(post) {
    const time = post.timestamp
      ? App.formatTime(new Date(post.timestamp))
      : '';

    // Format content: clean up predictions block and quoted text
    let content = App.escapeHtml(post.content);

    // Collapse prediction blocks (e.g., "Predictions: 13 of 13 Pending\n|\nTied for 1st...")
    content = content.replace(
      /Predictions:\s*\d+\s*of\s*\d+\s*Pending[\s\S]*?(?:Tied for|Ranked)\s*[^\n]*/g,
      '<span class="predictions-collapsed">[Predictions]</span>'
    );

    // Format quoted text
    content = content.replace(
      /^(&gt; .+?)$/gm,
      '<span class="quote">$1</span>'
    );

    const votes = [];
    if (post.upvotes > 0) votes.push(`<span class="vote-up">+${post.upvotes}</span>`);
    if (post.downvotes > 0) votes.push(`<span class="vote-down">-${post.downvotes}</span>`);

    return `
      <div class="post-card" id="post-${App.escapeHtml(post.id)}">
        <div class="post-header">
          <span class="post-author">${App.escapeHtml(post.author)}</span>
          <span class="post-time">${time}</span>
        </div>
        <div class="post-content">${content}</div>
        ${votes.length ? `<div class="post-footer">${votes.join(' ')}</div>` : ''}
      </div>
    `;
  }
};
