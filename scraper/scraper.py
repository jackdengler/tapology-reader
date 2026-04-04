#!/usr/bin/env python3
"""Tapology UFC Forum Scraper.

Scrapes forum threads for upcoming UFC events only, by first fetching the
upcoming schedule from Tapology's fightcenter, then finding and scraping the
matching forum threads with ALL posts.

Uses Playwright (headless Chromium) to bypass bot protection.
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
FIGHTCENTER_URL = f"{BASE_URL}/fightcenter?group=ufc&schedule=upcoming"
FORUM_URL = f"{BASE_URL}/forum/threads"

REQUEST_DELAY = 1.5  # seconds between requests

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
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(3000)
    return BeautifulSoup(page.content(), "html.parser")


def scrape_upcoming_events(page):
    """Scrape the list of upcoming UFC events from fightcenter.

    Returns a list of dicts with event name, date, and fightcenter URL slug.
    """
    print("Scraping upcoming UFC events from fightcenter...")
    soup = get_page_soup(page, FIGHTCENTER_URL)
    handle_consent(page)
    soup = BeautifulSoup(page.content(), "html.parser")

    events = []
    seen = set()

    for a in soup.find_all("a", href=re.compile(r"/fightcenter/events/.*ufc")):
        href = a["href"]
        if href in seen:
            continue
        seen.add(href)

        name = a.get_text(strip=True)
        # Skip truncated duplicate links (e.g. "UFC 328: Chimaev vs. Str...")
        if name.endswith("..."):
            continue

        # Extract date from parent container
        parent = a.find_parent("li") or a.find_parent("div") or a.find_parent("tr")
        event_date = ""
        if parent:
            parent_text = parent.get_text(" ", strip=True)
            date_match = re.search(
                r"(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),\s+"
                r"((?:January|February|March|April|May|June|July|August|September|October|November|December)"
                r"\s+\d{1,2})",
                parent_text,
            )
            if date_match:
                event_date = date_match.group(1)

        events.append({
            "name": name,
            "date": event_date,
            "fightcenterUrl": href,
        })

    print(f"  Found {len(events)} upcoming UFC events.")
    for e in events:
        print(f"    {e['date']:>20}  {e['name']}")

    return events


def normalize_event_name(name):
    """Normalize an event name for fuzzy matching."""
    name = name.lower().strip()
    name = re.sub(r"[^\w\s]", "", name)
    name = re.sub(r"\s+", " ", name)
    return name


def find_forum_threads(page, events, max_pages=5):
    """Search forum thread listings to find threads matching upcoming events.

    Returns a list of (event, thread_summary) tuples.
    """
    print(f"\nSearching forum for matching threads (up to {max_pages} pages)...")

    # Build lookup of normalized event names
    event_lookup = {}
    for event in events:
        norm = normalize_event_name(event["name"])
        event_lookup[norm] = event
        # Also match without the subtitle (e.g. "UFC 328" without ": Chimaev vs. Strickland")
        short = re.sub(r":.*", "", event["name"]).strip()
        short_norm = normalize_event_name(short)
        if short_norm != norm:
            event_lookup[short_norm] = event

    matched = []
    matched_events = set()

    for pg in range(1, max_pages + 1):
        url = f"{FORUM_URL}?page={pg}"
        print(f"  Forum page {pg}...")
        soup = get_page_soup(page, url)

        if pg == 1:
            handle_consent(page)
            soup = BeautifulSoup(page.content(), "html.parser")

        previews = soup.select("#postThreadsList .postPreview, .postPreview")
        if not previews:
            print(f"    No threads found, stopping.")
            break

        for preview in previews:
            thread = parse_thread_preview(preview)
            if not thread:
                continue

            thread_norm = normalize_event_name(thread["title"])

            for event_norm, event in event_lookup.items():
                if event["name"] in matched_events:
                    continue
                # Match if thread title contains the event name or vice versa
                if event_norm in thread_norm or thread_norm in event_norm:
                    thread["eventName"] = event["name"]
                    thread["eventDate"] = event["date"]
                    thread["fightcenterUrl"] = event["fightcenterUrl"]
                    matched.append(thread)
                    matched_events.add(event["name"])
                    print(f"    Matched: {thread['title']}  ->  {event['name']} ({event['date']})")
                    break

        # Stop if we've matched all events
        if len(matched_events) == len(events):
            print("  All events matched!")
            break

        time.sleep(REQUEST_DELAY)

    print(f"\n  Matched {len(matched)}/{len(events)} events to forum threads.")
    return matched


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
    """Scrape ALL posts from a thread (no page limit)."""
    url = f"{BASE_URL}/forum/threads/{thread_id}"
    print(f"  Scraping thread {thread_id}...")

    soup = get_page_soup(page, url)

    heading = soup.select_one(".postThreadShowHeading, h1")
    title = heading.get_text(strip=True) if heading else "Untitled"
    title = re.sub(r"^Topic:\s*", "", title)

    total_pages = 1
    pager = soup.select_one("nav[aria-label='pager']")
    if pager:
        for link in reversed(pager.select("a")):
            href = link.get("href", "")
            page_match = re.search(r"page=(\d+)", href)
            if page_match:
                total_pages = max(total_pages, int(page_match.group(1)))

    posts = parse_posts(soup)
    print(f"    Page 1/{total_pages} ({len(posts)} posts)")

    for pg in range(2, total_pages + 1):
        time.sleep(REQUEST_DELAY)
        print(f"    Page {pg}/{total_pages}...", end="")
        soup = get_page_soup(page, f"{url}?page={pg}")
        new_posts = parse_posts(soup)
        posts.extend(new_posts)
        print(f" ({len(new_posts)} posts)")

    print(f"    Total: {len(posts)} posts across {total_pages} pages")

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
    for elem in soup.select("div.pagePost, .pagePost"):
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

    # Clean out old thread detail files that are no longer in the index
    current_ids = {t["id"] for t in threads_index}
    for f in THREADS_DIR.glob("*.json"):
        if f.stem not in current_ids:
            f.unlink()
            print(f"  Removed old thread file: {f.name}")

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
    print("Tapology UFC Forum Scraper — upcoming events only\n")

    existing = load_existing_data()

    with sync_playwright() as pw:
        browser, page = create_browser(pw)

        try:
            # Step 1: Get upcoming UFC events
            events = scrape_upcoming_events(page)
            if not events:
                print("No upcoming events found. Exiting.")
                sys.exit(1)

            time.sleep(REQUEST_DELAY)

            # Step 2: Find matching forum threads
            threads = find_forum_threads(page, events)
            if not threads:
                print("No matching forum threads found. Exiting.")
                sys.exit(1)

            # Step 3: Scrape all posts from each thread
            print(f"\nScraping {len(threads)} threads (all posts)...\n")
            thread_details = {}
            for i, thread in enumerate(threads):
                tid = thread["id"]

                # Incremental: skip if reply count unchanged
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
                        # Attach event metadata
                        detail["eventName"] = thread.get("eventName", "")
                        detail["eventDate"] = thread.get("eventDate", "")
                        detail["fightcenterUrl"] = thread.get("fightcenterUrl", "")
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
