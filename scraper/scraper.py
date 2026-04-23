#!/usr/bin/env python3
"""Tapology UFC Forum Scraper.

Scrapes forum threads for upcoming UFC events only, by first fetching the
upcoming schedule from Tapology's fightcenter, then finding and scraping the
matching forum threads with ALL posts.

Uses Playwright (headless Chromium) to bypass bot protection.

Run ``python scraper.py --help`` for CLI options.
"""

import argparse
import json
import logging
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

BASE_URL = "https://www.tapology.com"
FIGHTCENTER_URL = f"{BASE_URL}/fightcenter?group=ufc&schedule=upcoming"
FORUM_URL = f"{BASE_URL}/forum/threads"

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent
DATA_DIR = PROJECT_DIR / "docs" / "data"
THREADS_DIR = DATA_DIR / "threads"

log = logging.getLogger("tapology")


@dataclass
class Config:
    max_pages: int = 5
    delay: float = 1.5
    thread_id: str | None = None
    dry_run: bool = False


def configure_logging(verbosity: int) -> None:
    level = logging.WARNING
    if verbosity == 1:
        level = logging.INFO
    elif verbosity >= 2:
        level = logging.DEBUG
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-5s %(message)s",
        datefmt="%H:%M:%S",
    )


def create_browser(pw):
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


def handle_consent(page, delay: float) -> None:
    try:
        agree_btn = page.locator(
            'form[action="/special-consent/accept"] input[type="submit"], '
            'form[action="/special-consent/accept"] button[type="submit"]'
        )
        if agree_btn.count() > 0:
            agree_btn.first.click()
            page.wait_for_load_state("networkidle")
            log.info("Consent accepted.")
            time.sleep(delay)
        else:
            log.debug("No consent overlay found.")
    except Exception as exc:
        log.warning("Consent handling failed: %s", exc)


def get_page_soup(page, url: str) -> BeautifulSoup:
    log.debug("GET %s", url)
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(3000)
    return BeautifulSoup(page.content(), "html.parser")


def scrape_upcoming_events(page, cfg: Config):
    log.info("Scraping upcoming UFC events from fightcenter...")
    get_page_soup(page, FIGHTCENTER_URL)
    handle_consent(page, cfg.delay)
    soup = BeautifulSoup(page.content(), "html.parser")

    events = []
    seen = set()

    for a in soup.find_all("a", href=re.compile(r"/fightcenter/events/.*ufc")):
        href = a["href"]
        if href in seen:
            continue
        seen.add(href)

        name = a.get_text(strip=True)
        if name.endswith("..."):
            continue

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

        events.append({"name": name, "date": event_date, "fightcenterUrl": href})

    log.info("Found %d upcoming UFC events.", len(events))
    for e in events:
        log.info("  %20s  %s", e["date"], e["name"])

    return events


def normalize_event_name(name: str) -> str:
    name = name.lower().strip()
    name = re.sub(r"[^\w\s]", "", name)
    name = re.sub(r"\s+", " ", name)
    return name


def find_forum_threads(page, events, cfg: Config):
    log.info("Searching forum for matching threads (up to %d pages)...", cfg.max_pages)

    event_lookup = {}
    for event in events:
        norm = normalize_event_name(event["name"])
        event_lookup[norm] = event
        short = re.sub(r":.*", "", event["name"]).strip()
        short_norm = normalize_event_name(short)
        if short_norm != norm:
            event_lookup[short_norm] = event

    matched = []
    matched_events = set()

    for pg in range(1, cfg.max_pages + 1):
        url = f"{FORUM_URL}?page={pg}"
        log.info("Forum page %d...", pg)
        soup = get_page_soup(page, url)

        if pg == 1:
            handle_consent(page, cfg.delay)
            soup = BeautifulSoup(page.content(), "html.parser")

        previews = soup.select("#postThreadsList .postPreview, .postPreview")
        if not previews:
            log.info("  No threads found on page %d, stopping.", pg)
            break

        for preview in previews:
            thread = parse_thread_preview(preview)
            if not thread:
                continue

            thread_norm = normalize_event_name(thread["title"])

            for event_norm, event in event_lookup.items():
                if event["name"] in matched_events:
                    continue
                if event_norm in thread_norm or thread_norm in event_norm:
                    thread["eventName"] = event["name"]
                    thread["eventDate"] = event["date"]
                    thread["fightcenterUrl"] = event["fightcenterUrl"]
                    matched.append(thread)
                    matched_events.add(event["name"])
                    log.info("  Matched: %s  ->  %s (%s)",
                             thread["title"], event["name"], event["date"])
                    break

        if len(matched_events) == len(events):
            log.info("All events matched!")
            break

        time.sleep(cfg.delay)

    unmatched = [e["name"] for e in events if e["name"] not in matched_events]
    if unmatched:
        log.warning("Unmatched events (no forum thread found): %s", ", ".join(unmatched))

    log.info("Matched %d/%d events to forum threads.", len(matched), len(events))
    return matched


def parse_thread_preview(preview):
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
        log.debug("Skipping preview with no extractable thread id")
        return None

    is_sticky = "sticky" in preview.get("class", [])

    time_elem = preview.select_one("abbr.timeago")
    timestamp = time_elem.get("title", "") if time_elem else ""

    reply_count = 0
    stats = preview.select_one(".topicStats dt")
    if stats:
        count_text = stats.get_text(strip=True).replace(",", "")
        try:
            reply_count = int(count_text)
        except ValueError:
            log.debug("Couldn't parse replyCount %r on thread %s", count_text, thread_id)

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


def scrape_thread_detail(page, thread_id: str, cfg: Config):
    url = f"{BASE_URL}/forum/threads/{thread_id}"
    log.info("Scraping thread %s...", thread_id)

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
    log.info("  Page 1/%d (%d posts)", total_pages, len(posts))

    for pg in range(2, total_pages + 1):
        time.sleep(cfg.delay)
        soup = get_page_soup(page, f"{url}?page={pg}")
        new_posts = parse_posts(soup)
        posts.extend(new_posts)
        log.info("  Page %d/%d (%d posts)", pg, total_pages, len(new_posts))

    log.info("  Total: %d posts across %d pages", len(posts), total_pages)

    return {
        "id": thread_id,
        "title": title,
        "totalPages": total_pages,
        "posts": posts,
        "scrapedAt": datetime.now(timezone.utc).isoformat(),
    }


def parse_posts(soup):
    posts = []
    for elem in soup.select("div.pagePost, .pagePost"):
        post = parse_single_post(elem)
        if post:
            posts.append(post)
    return posts


def parse_single_post(elem):
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


def parse_post_timestamp(text: str) -> str:
    """Parse timestamps like '03.13.2026 | 10:25 AM ET' to ISO 8601.

    ET is UTC-5 in winter and UTC-4 during DST. We pick the correct offset
    based on U.S. DST rules so downstream consumers can sort chronologically.
    """
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
        offset = "-04:00" if _is_us_dst(dt) else "-05:00"
        return dt.strftime("%Y-%m-%dT%H:%M:%S") + offset
    except ValueError:
        return text


def _is_us_dst(dt: datetime) -> bool:
    """True if the naive datetime falls inside U.S. DST (2nd Sun Mar → 1st Sun Nov)."""
    year = dt.year
    march1 = datetime(year, 3, 1).weekday()       # Mon=0..Sun=6
    first_sun_mar = ((6 - march1) % 7) + 1
    dst_start = datetime(year, 3, first_sun_mar + 7, 2)
    nov1 = datetime(year, 11, 1).weekday()
    first_sun_nov = ((6 - nov1) % 7) + 1
    dst_end = datetime(year, 11, first_sun_nov, 2)
    return dst_start <= dt < dst_end


def clean_html_content(elem) -> str:
    for br in elem.find_all("br"):
        br.replace_with("\n")

    for p in elem.find_all("p"):
        p.insert_before("\n\n")

    for quote in elem.find_all("blockquote"):
        quote_text = quote.get_text(strip=True)
        quote.replace_with(f"\n> {quote_text}\n")

    text = elem.get_text()
    lines = [line.strip() for line in text.split("\n")]
    text = "\n".join(lines)

    text = re.sub(
        r"Predictions:\s*\d+\s*of\s*\d+\s*Pending[\s\S]*?(?:Tied for|Ranked)\s*[^\n]*",
        "[Predictions]",
        text,
    )
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def load_existing_index():
    index_path = DATA_DIR / "threads.json"
    if index_path.exists():
        with open(index_path) as f:
            return {t["id"]: t for t in json.load(f)}
    return {}


def validate_thread_index(threads) -> list[str]:
    required = {"id", "title", "replyCount"}
    problems = []
    for t in threads:
        missing = required - t.keys()
        if missing:
            problems.append(f"thread {t.get('id', '?')} missing keys: {missing}")
    return problems


def save_data(threads_index, thread_details, cfg: Config):
    problems = validate_thread_index(threads_index)
    if problems:
        for p in problems:
            log.error("Schema problem: %s", p)
        if not cfg.dry_run:
            raise SystemExit("Refusing to write invalid data. Re-run with -vv for details.")

    if cfg.dry_run:
        log.info("[dry-run] would write %d thread summaries and %d thread details.",
                 len(threads_index), len(thread_details))
        return

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    THREADS_DIR.mkdir(parents=True, exist_ok=True)

    current_ids = {t["id"] for t in threads_index}
    for f in THREADS_DIR.glob("*.json"):
        if f.stem not in current_ids:
            f.unlink()
            log.info("Removed stale thread file: %s", f.name)

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

    log.info("Wrote %d thread summaries and %d thread details.",
             len(threads_index), len(thread_details))


def scrape_single_thread(cfg: Config) -> int:
    """--thread flow: scrape one thread id and write only its detail file."""
    with sync_playwright() as pw:
        browser, page = create_browser(pw)
        try:
            handle_consent(page, cfg.delay)
            detail = scrape_thread_detail(page, cfg.thread_id, cfg)
        finally:
            browser.close()

    if cfg.dry_run:
        log.info("[dry-run] would write thread %s (%d posts)", cfg.thread_id, len(detail["posts"]))
        return 0

    THREADS_DIR.mkdir(parents=True, exist_ok=True)
    with open(THREADS_DIR / f"{cfg.thread_id}.json", "w") as f:
        json.dump(detail, f, indent=2, ensure_ascii=False)
    log.info("Wrote thread %s (%d posts).", cfg.thread_id, len(detail["posts"]))
    return 0


def run(cfg: Config) -> int:
    log.info("Tapology UFC Forum Scraper — upcoming events only")

    if cfg.thread_id:
        return scrape_single_thread(cfg)

    existing = load_existing_index()

    with sync_playwright() as pw:
        browser, page = create_browser(pw)
        try:
            events = scrape_upcoming_events(page, cfg)
            if not events:
                log.error("No upcoming events found — Tapology markup may have changed.")
                return 1

            time.sleep(cfg.delay)

            threads = find_forum_threads(page, events, cfg)
            if not threads:
                log.error("No matching forum threads found.")
                return 1

            log.info("Scraping %d threads (all posts)...", len(threads))
            thread_details = {}
            for i, thread in enumerate(threads, start=1):
                tid = thread["id"]

                if tid in existing:
                    old_count = existing[tid].get("replyCount", 0)
                    if old_count == thread["replyCount"]:
                        log.info("[%d/%d] Thread %s unchanged (%d replies), skipping.",
                                 i, len(threads), tid, old_count)
                        detail_path = THREADS_DIR / f"{tid}.json"
                        if detail_path.exists():
                            with open(detail_path) as f:
                                thread_details[tid] = json.load(f)
                        continue

                log.info("[%d/%d] scraping…", i, len(threads))
                time.sleep(cfg.delay)

                try:
                    detail = scrape_thread_detail(page, tid, cfg)
                    detail["eventName"] = thread.get("eventName", "")
                    detail["eventDate"] = thread.get("eventDate", "")
                    detail["fightcenterUrl"] = thread.get("fightcenterUrl", "")
                    thread_details[tid] = detail
                except Exception:
                    log.exception("Error scraping thread %s — will retain previous version if present.", tid)
                    detail_path = THREADS_DIR / f"{tid}.json"
                    if detail_path.exists():
                        with open(detail_path) as f:
                            thread_details[tid] = json.load(f)

            save_data(threads, thread_details, cfg)
            log.info("Done.")
            return 0
        finally:
            browser.close()


def parse_args(argv: list[str] | None = None) -> Config:
    p = argparse.ArgumentParser(
        description="Scrape UFC forum threads from Tapology for upcoming events.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--max-pages", type=int, default=5,
                   help="Max forum listing pages to scan when matching events.")
    p.add_argument("--delay", type=float, default=1.5,
                   help="Seconds to wait between requests.")
    p.add_argument("--thread", dest="thread_id", metavar="ID", default=None,
                   help="Scrape a single thread by id and exit (skips discovery).")
    p.add_argument("--dry-run", action="store_true",
                   help="Do all the discovery and scraping, but don't write data files.")
    p.add_argument("-v", "--verbose", action="count", default=1,
                   help="Increase log verbosity (-v info, -vv debug).")
    args = p.parse_args(argv)

    configure_logging(args.verbose)

    return Config(
        max_pages=args.max_pages,
        delay=args.delay,
        thread_id=args.thread_id,
        dry_run=args.dry_run,
    )


def main() -> int:
    cfg = parse_args()
    try:
        return run(cfg)
    except KeyboardInterrupt:
        log.warning("Interrupted.")
        return 130


if __name__ == "__main__":
    sys.exit(main())
