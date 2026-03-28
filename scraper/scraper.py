#!/usr/bin/env python3
"""Tapology UFC Forum Scraper.

Scrapes thread listings and individual threads from Tapology forums,
saving them as JSON for the PWA frontend.
"""

import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.tapology.com"
FORUM_URL = f"{BASE_URL}/forum/threads"
CONSENT_URL = f"{BASE_URL}/special-consent/accept"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/122.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate",
}

REQUEST_DELAY = 1.5  # seconds between requests
MAX_POSTS_PER_THREAD = 60  # ~3 pages worth
MEGA_THREAD_THRESHOLD = 200  # reply count above which we only scrape last pages

# Resolve paths relative to this script
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent
DATA_DIR = PROJECT_DIR / "docs" / "data"
THREADS_DIR = DATA_DIR / "threads"


def create_session():
    """Create a requests session and handle Tapology's consent modal."""
    session = requests.Session()
    session.headers.update(HEADERS)

    # First request to get session cookie and CSRF token
    resp = session.get(FORUM_URL, timeout=30)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")

    # Look for consent overlay - try the accept form specifically
    accept_form = soup.select_one('form[action="/special-consent/accept"]')
    if not accept_form:
        accept_form = soup.select_one("#specialConsentOverlay form")

    if accept_form:
        token_input = accept_form.select_one("input[name=authenticity_token]")
        if token_input:
            token = token_input.get("value", "")
            consent_resp = session.post(
                CONSENT_URL,
                data={
                    "authenticity_token": token,
                    "agree_legal": "1",
                    "agree": "1",
                },
                timeout=30,
                allow_redirects=True,
            )
            print(f"Consent accepted (status {consent_resp.status_code}).")
            time.sleep(REQUEST_DELAY)
        else:
            print("Warning: consent form found but no CSRF token.")
    else:
        print("No consent overlay found, proceeding.")

    return session


def scrape_thread_list(session, max_pages=3):
    """Scrape thread listings from the forum.

    Returns a list of thread summary dicts.
    """
    threads = []
    seen_ids = set()

    for page in range(1, max_pages + 1):
        url = f"{FORUM_URL}?page={page}"
        print(f"Scraping thread list page {page}...")
        resp = session.get(url, timeout=30)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")
        previews = soup.select("#postThreadsList .postPreview, .postPreview")

        if not previews:
            print(f"  No threads found on page {page}, stopping.")
            break

        for preview in previews:
            thread = parse_thread_preview(preview)
            if thread and thread["id"] not in seen_ids:
                threads.append(thread)
                seen_ids.add(thread["id"])

        print(f"  Found {len(previews)} threads on page {page}.")

        if page < max_pages:
            time.sleep(REQUEST_DELAY)

    return threads


def parse_thread_preview(preview):
    """Parse a single thread preview element into a dict."""
    # Thread ID from element id attribute (e.g., "pt94221")
    thread_id = None
    elem_id = preview.get("id", "")
    match = re.search(r"(\d+)", elem_id)
    if match:
        thread_id = match.group(1)

    # Title
    title_link = preview.select_one("a[href*='/forum/threads/']")
    title = title_link.get_text(strip=True) if title_link else "Untitled"
    url = title_link.get("href", "") if title_link else ""

    # Fallback: extract thread ID from URL
    if not thread_id and url:
        url_match = re.search(r"/forum/threads/(\d+)", url)
        if url_match:
            thread_id = url_match.group(1)

    if not thread_id:
        return None

    # Sticky
    is_sticky = "sticky" in preview.get("class", [])

    # Timestamp
    time_elem = preview.select_one("abbr.timeago")
    timestamp = ""
    if time_elem:
        timestamp = time_elem.get("title", "")

    # Reply count
    reply_count = 0
    stats = preview.select_one(".topicStats dt")
    if stats:
        count_text = stats.get_text(strip=True).replace(",", "")
        try:
            reply_count = int(count_text)
        except ValueError:
            pass

    # Last post snippet
    snippet_elem = preview.select_one(".previewContent dd a")
    snippet = snippet_elem.get_text(strip=True)[:150] if snippet_elem else ""

    # Icon
    icon_elem = preview.select_one(".postThreadPreviewIcon img")
    icon_url = icon_elem.get("src", "") if icon_elem else ""

    return {
        "id": thread_id,
        "title": title,
        "url": url,
        "isSticky": is_sticky,
        "lastPostTime": timestamp,
        "replyCount": reply_count,
        "snippet": snippet,
        "iconUrl": icon_url,
    }


def scrape_thread_detail(session, thread_id, existing_data=None):
    """Scrape all posts from a thread.

    For mega-threads (200+ replies), only scrapes the last few pages.
    If existing_data is provided and reply count hasn't changed, returns None.
    """
    url = f"{BASE_URL}/forum/threads/{thread_id}"
    print(f"  Scraping thread {thread_id}...")

    resp = session.get(url, timeout=30)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    # Thread title
    heading = soup.select_one(".postThreadShowHeading, h1")
    title = heading.get_text(strip=True) if heading else "Untitled"
    # Strip "Topic:" prefix that Tapology adds
    title = re.sub(r"^Topic:\s*", "", title)

    # Detect total pages
    total_pages = 1
    pager = soup.select_one("nav[aria-label='pager']")
    if pager:
        last_link = pager.select("a")
        for link in reversed(last_link):
            href = link.get("href", "")
            page_match = re.search(r"page=(\d+)", href)
            if page_match:
                total_pages = max(total_pages, int(page_match.group(1)))

    # For mega-threads, only get last 3 pages
    if total_pages > 10:
        start_page = max(1, total_pages - 2)
        print(f"    Mega-thread ({total_pages} pages), scraping pages {start_page}-{total_pages}")
    else:
        start_page = 1

    posts = []

    # Parse first page posts (already loaded)
    if start_page == 1:
        posts.extend(parse_posts(soup))
    else:
        # Need to fetch the start page
        time.sleep(REQUEST_DELAY)
        resp = session.get(f"{url}?page={start_page}", timeout=30)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        posts.extend(parse_posts(soup))

    # Fetch remaining pages
    for page in range(start_page + 1, total_pages + 1):
        if len(posts) >= MAX_POSTS_PER_THREAD:
            print(f"    Hit post limit ({MAX_POSTS_PER_THREAD}), stopping.")
            break

        time.sleep(REQUEST_DELAY)
        print(f"    Fetching page {page}/{total_pages}...")
        resp = session.get(f"{url}?page={page}", timeout=30)
        resp.raise_for_status()
        page_soup = BeautifulSoup(resp.text, "html.parser")
        posts.extend(parse_posts(page_soup))

    return {
        "id": thread_id,
        "title": title,
        "totalPages": total_pages,
        "posts": posts,
        "scrapedAt": datetime.now(timezone.utc).isoformat(),
    }


def parse_posts(soup):
    """Parse all posts from a page's soup."""
    posts = []
    post_elems = soup.select("div.pagePost, .pagePost")

    for elem in post_elems:
        post = parse_single_post(elem)
        if post:
            posts.append(post)

    return posts


def parse_single_post(elem):
    """Parse a single post element."""
    # Post ID
    post_id = elem.get("id", "")
    post_id = post_id.replace("post-", "") if post_id else ""

    # Author
    author_elem = elem.select_one(".posterName a")
    author = author_elem.get_text(strip=True) if author_elem else "Anonymous"
    author_url = author_elem.get("href", "") if author_elem else ""

    # Timestamp - format: "03.13.2026 | 10:25 AM ET"
    timestamp = ""
    header = elem.select_one(".postHeader p")
    if header:
        time_text = header.get_text(strip=True)
        timestamp = parse_post_timestamp(time_text)

    # Content
    content_elem = elem.select_one(".postText, [id^='postTextPostContent']")
    content = ""
    if content_elem:
        # Get text content, preserving paragraph breaks
        content = clean_html_content(content_elem)

    # Votes
    upvotes = 0
    downvotes = 0
    vote_buttons = elem.select(".votes button.thumber, .thumber")
    for btn in vote_buttons:
        text = btn.get_text(strip=True)
        count_match = re.search(r"(\d+)", text)
        if count_match:
            count = int(count_match.group(1))
            classes = btn.get("class", [])
            if any("up" in c.lower() for c in classes):
                upvotes = count
            elif any("down" in c.lower() for c in classes):
                downvotes = count

    return {
        "id": post_id,
        "author": author,
        "authorUrl": author_url,
        "timestamp": timestamp,
        "content": content,
        "upvotes": upvotes,
        "downvotes": downvotes,
    }


def parse_post_timestamp(text):
    """Parse timestamps like '03.13.2026 | 10:25 AM ET' to ISO 8601."""
    match = re.search(r"(\d{2})\.(\d{2})\.(\d{4})\s*\|\s*(\d{1,2}):(\d{2})\s*(AM|PM)\s*ET", text)
    if not match:
        return text  # Return raw text if can't parse

    month, day, year = int(match.group(1)), int(match.group(2)), int(match.group(3))
    hour, minute = int(match.group(4)), int(match.group(5))
    ampm = match.group(6)

    if ampm == "PM" and hour != 12:
        hour += 12
    elif ampm == "AM" and hour == 12:
        hour = 0

    try:
        dt = datetime(year, month, day, hour, minute)
        # ET is UTC-5 (EST) or UTC-4 (EDT), approximate as -05:00
        return dt.strftime("%Y-%m-%dT%H:%M:%S") + "-05:00"
    except ValueError:
        return text


def clean_html_content(elem):
    """Convert HTML content to clean text with basic formatting preserved."""
    # Replace <br> with newlines
    for br in elem.find_all("br"):
        br.replace_with("\n")

    # Replace <p> with double newlines
    for p in elem.find_all("p"):
        p.insert_before("\n\n")

    # Handle blockquotes (quoted replies)
    for quote in elem.find_all("blockquote"):
        quote_text = quote.get_text(strip=True)
        quote.replace_with(f"\n> {quote_text}\n")

    text = elem.get_text()

    # Clean up whitespace
    lines = text.split("\n")
    lines = [line.strip() for line in lines]
    text = "\n".join(lines)

    # Collapse prediction blocks
    text = re.sub(
        r"Predictions:\s*\d+\s*of\s*\d+\s*Pending[\s\S]*?(?:Tied for|Ranked)\s*[^\n]*",
        "[Predictions]",
        text,
    )

    # Collapse multiple newlines
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()


def load_existing_data():
    """Load existing thread index if available."""
    index_path = DATA_DIR / "threads.json"
    if index_path.exists():
        with open(index_path) as f:
            return {t["id"]: t for t in json.load(f)}
    return {}


def save_data(threads_index, thread_details):
    """Save scraped data to JSON files."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    THREADS_DIR.mkdir(parents=True, exist_ok=True)

    # Save thread index
    with open(DATA_DIR / "threads.json", "w") as f:
        json.dump(threads_index, f, indent=2, ensure_ascii=False)

    # Save individual threads
    for thread_id, data in thread_details.items():
        with open(THREADS_DIR / f"{thread_id}.json", "w") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    # Save meta
    with open(DATA_DIR / "meta.json", "w") as f:
        json.dump({
            "lastUpdated": datetime.now(timezone.utc).isoformat(),
            "threadCount": len(threads_index),
        }, f, indent=2)

    print(f"\nSaved {len(threads_index)} thread summaries and {len(thread_details)} thread details.")


def main():
    max_pages = int(os.environ.get("SCRAPE_PAGES", "3"))
    print(f"Tapology Forum Scraper - scraping {max_pages} pages\n")

    # Load existing data for incremental scraping
    existing = load_existing_data()

    session = create_session()

    # Scrape thread listings
    threads = scrape_thread_list(session, max_pages=max_pages)
    if not threads:
        print("No threads found. Exiting.")
        sys.exit(1)

    # Filter to UFC events only
    ufc_keywords = ["UFC", "The Miscellaneous Thread", "TAPOLOGY'S BADDEST"]
    threads = [t for t in threads if any(kw.lower() in t["title"].lower() for kw in ufc_keywords)]
    print(f"\nFound {len(threads)} UFC threads (filtered).\n")

    # Scrape individual threads
    thread_details = {}
    for i, thread in enumerate(threads):
        tid = thread["id"]

        # Incremental: skip if reply count unchanged
        if tid in existing:
            old_count = existing[tid].get("replyCount", 0)
            if old_count == thread["replyCount"]:
                print(f"  [{i+1}/{len(threads)}] Thread {tid} unchanged, skipping.")
                # Keep existing detail if we have it
                detail_path = THREADS_DIR / f"{tid}.json"
                if detail_path.exists():
                    with open(detail_path) as f:
                        thread_details[tid] = json.load(f)
                continue

        print(f"  [{i+1}/{len(threads)}] ", end="")
        time.sleep(REQUEST_DELAY)

        try:
            detail = scrape_thread_detail(session, tid)
            if detail:
                thread_details[tid] = detail
        except Exception as e:
            print(f"    Error scraping thread {tid}: {e}")
            continue

    save_data(threads, thread_details)
    print("\nDone!")


if __name__ == "__main__":
    main()
