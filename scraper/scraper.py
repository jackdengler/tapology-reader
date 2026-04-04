#!/usr/bin/env python3
"""Tapology UFC Forum Scraper.

Scrapes thread listings and individual threads from Tapology forums,
saving them as JSON for the PWA frontend.

Uses Playwright (headless Chromium) to bypass bot protection that blocks
datacenter IPs (e.g. GitHub Actions).
"""

import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

BASE_URL = "https://www.tapology.com"
FORUM_URL = f"{BASE_URL}/forum/threads"

REQUEST_DELAY = 1.5  # seconds between requests
MAX_POSTS_PER_THREAD = 60  # ~3 pages worth

# Resolve paths relative to this script
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent
DATA_DIR = PROJECT_DIR / "docs" / "data"
THREADS_DIR = DATA_DIR / "threads"


def create_browser(pw):
    """Launch a headless Chromium browser and return (browser, page)."""
    browser = pw.chromium.launch(headless=True)
    context = browser.new_context(
        user_agent=(
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        ),
        viewport={"width": 1280, "height": 800},
        locale="en-US",
    )
    page = context.new_page()
    return browser, page


def handle_consent(page):
    """Accept Tapology's consent overlay if present."""
    try:
        agree_btn = page.locator('form[action="/special-consent/accept"] input[type="submit"], form[action="/special-consent/accept"] button[type="submit"]')
        if agree_btn.count() > 0:
            agree_btn.first.click()
            page.wait_for_load_state("networkidle")
            print("Consent accepted.")
            time.sleep(REQUEST_DELAY)
        else:
            print("No consent overlay found, proceeding.")
    except Exception as e:
        print(f"Consent handling note: {e}")


def get_page_soup(page, url):
    """Navigate to a URL and return BeautifulSoup of the page content."""
    page.goto(url, wait_until="networkidle", timeout=60000)
    return BeautifulSoup(page.content(), "html.parser")


def scrape_thread_list(page, max_pages=3):
    """Scrape thread listings from the forum."""
    threads = []
    seen_ids = set()

    for pg in range(1, max_pages + 1):
        url = f"{FORUM_URL}?page={pg}"
        print(f"Scraping thread list page {pg}...")
        soup = get_page_soup(page, url)

        if pg == 1:
            handle_consent(page)
            # Re-fetch after consent in case page changed
            soup = BeautifulSoup(page.content(), "html.parser")

        previews = soup.select("#postThreadsList .postPreview, .postPreview")

        if not previews:
            print(f"  No threads found on page {pg}, stopping.")
            break

        for preview in previews:
            thread = parse_thread_preview(preview)
            if thread and thread["id"] not in seen_ids:
                threads.append(thread)
                seen_ids.add(thread["id"])

        print(f"  Found {len(previews)} threads on page {pg}.")

        if pg < max_pages:
            time.sleep(REQUEST_DELAY)

    return threads


def parse_thread_preview(preview):
    """Parse a single thread preview element into a dict."""
    thread_id = None
    elem_id = preview.get("id", "")
    match = re.search(r"(\d+)", elem_id)
    if match:
        thread_id = match.group(1)

    title_link = preview.select_one("a[href*='/forum/threads/']")
    title = title_link.get_text(strip=True) if title_link else "Untitled"
    url = title_link.get("href", "") if title_link else ""

    if not thread_id and url:
        url_match = re.search(r"/forum/threads/(\d+)", url)
        if url_match:
            thread_id = url_match.group(1)

    if not thread_id:
        return None

    is_sticky = "sticky" in preview.get("class", [])

    time_elem = preview.select_one("abbr.timeago")
    timestamp = ""
    if time_elem:
        timestamp = time_elem.get("title", "")

    reply_count = 0
    stats = preview.select_one(".topicStats dt")
    if stats:
        count_text = stats.get_text(strip=True).replace(",", "")
        try:
            reply_count = int(count_text)
        except ValueError:
            pass

    snippet_elem = preview.select_one(".previewContent dd a")
    snippet = snippet_elem.get_text(strip=True)[:150] if snippet_elem else ""

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


def scrape_thread_detail(page, thread_id):
    """Scrape all posts from a thread."""
    url = f"{BASE_URL}/forum/threads/{thread_id}"
    print(f"  Scraping thread {thread_id}...")

    soup = get_page_soup(page, url)

    heading = soup.select_one(".postThreadShowHeading, h1")
    title = heading.get_text(strip=True) if heading else "Untitled"
    title = re.sub(r"^Topic:\s*", "", title)

    total_pages = 1
    pager = soup.select_one("nav[aria-label='pager']")
    if pager:
        last_link = pager.select("a")
        for link in reversed(last_link):
            href = link.get("href", "")
            page_match = re.search(r"page=(\d+)", href)
            if page_match:
                total_pages = max(total_pages, int(page_match.group(1)))

    if total_pages > 10:
        start_page = max(1, total_pages - 2)
        print(f"    Mega-thread ({total_pages} pages), scraping pages {start_page}-{total_pages}")
    else:
        start_page = 1

    posts = []

    if start_page == 1:
        posts.extend(parse_posts(soup))
    else:
        time.sleep(REQUEST_DELAY)
        soup = get_page_soup(page, f"{url}?page={start_page}")
        posts.extend(parse_posts(soup))

    for pg in range(start_page + 1, total_pages + 1):
        if len(posts) >= MAX_POSTS_PER_THREAD:
            print(f"    Hit post limit ({MAX_POSTS_PER_THREAD}), stopping.")
            break

        time.sleep(REQUEST_DELAY)
        print(f"    Fetching page {pg}/{total_pages}...")
        soup = get_page_soup(page, f"{url}?page={pg}")
        posts.extend(parse_posts(soup))

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
    post_id = elem.get("id", "")
    post_id = post_id.replace("post-", "") if post_id else ""

    author_elem = elem.select_one(".posterName a")
    author = author_elem.get_text(strip=True) if author_elem else "Anonymous"
    author_url = author_elem.get("href", "") if author_elem else ""

    timestamp = ""
    header = elem.select_one(".postHeader p")
    if header:
        time_text = header.get_text(strip=True)
        timestamp = parse_post_timestamp(time_text)

    content_elem = elem.select_one(".postText, [id^='postTextPostContent']")
    content = ""
    if content_elem:
        content = clean_html_content(content_elem)

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
        return text

    month, day, year = int(match.group(1)), int(match.group(2)), int(match.group(3))
    hour, minute = int(match.group(4)), int(match.group(5))
    ampm = match.group(6)

    if ampm == "PM" and hour != 12:
        hour += 12
    elif ampm == "AM" and hour == 12:
        hour = 0

    try:
        dt = datetime(year, month, day, hour, minute)
        return dt.strftime("%Y-%m-%dT%H:%M:%S") + "-05:00"
    except ValueError:
        return text


def clean_html_content(elem):
    """Convert HTML content to clean text with basic formatting preserved."""
    for br in elem.find_all("br"):
        br.replace_with("\n")

    for p in elem.find_all("p"):
        p.insert_before("\n\n")

    for quote in elem.find_all("blockquote"):
        quote_text = quote.get_text(strip=True)
        quote.replace_with(f"\n> {quote_text}\n")

    text = elem.get_text()

    lines = text.split("\n")
    lines = [line.strip() for line in lines]
    text = "\n".join(lines)

    text = re.sub(
        r"Predictions:\s*\d+\s*of\s*\d+\s*Pending[\s\S]*?(?:Tied for|Ranked)\s*[^\n]*",
        "[Predictions]",
        text,
    )

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

    with open(DATA_DIR / "threads.json", "w") as f:
        json.dump(threads_index, f, indent=2, ensure_ascii=False)

    for thread_id, data in thread_details.items():
        with open(THREADS_DIR / f"{thread_id}.json", "w") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    with open(DATA_DIR / "meta.json", "w") as f:
        json.dump({
            "lastUpdated": datetime.now(timezone.utc).isoformat(),
            "threadCount": len(threads_index),
        }, f, indent=2)

    print(f"\nSaved {len(threads_index)} thread summaries and {len(thread_details)} thread details.")


def main():
    max_pages = int(os.environ.get("SCRAPE_PAGES", "3"))
    print(f"Tapology Forum Scraper - scraping {max_pages} pages\n")

    existing = load_existing_data()

    with sync_playwright() as pw:
        browser, page = create_browser(pw)

        try:
            threads = scrape_thread_list(page, max_pages=max_pages)
            if not threads:
                print("No threads found. Exiting.")
                sys.exit(1)

            ufc_keywords = ["UFC", "The Miscellaneous Thread", "TAPOLOGY'S BADDEST"]
            threads = [t for t in threads if any(kw.lower() in t["title"].lower() for kw in ufc_keywords)]
            print(f"\nFound {len(threads)} UFC threads (filtered).\n")

            thread_details = {}
            for i, thread in enumerate(threads):
                tid = thread["id"]

                if tid in existing:
                    old_count = existing[tid].get("replyCount", 0)
                    if old_count == thread["replyCount"]:
                        print(f"  [{i+1}/{len(threads)}] Thread {tid} unchanged, skipping.")
                        detail_path = THREADS_DIR / f"{tid}.json"
                        if detail_path.exists():
                            with open(detail_path) as f:
                                thread_details[tid] = json.load(f)
                        continue

                print(f"  [{i+1}/{len(threads)}] ", end="")
                time.sleep(REQUEST_DELAY)

                try:
                    detail = scrape_thread_detail(page, tid)
                    if detail:
                        thread_details[tid] = detail
                except Exception as e:
                    print(f"    Error scraping thread {tid}: {e}")
                    continue

            save_data(threads, thread_details)
            print("\nDone!")
        finally:
            browser.close()


if __name__ == "__main__":
    main()
