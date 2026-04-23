# Tapology Reader

A UFC-focused forum reader. A scraper pulls threads for upcoming UFC events
from [Tapology](https://www.tapology.com) once an hour, writes JSON to
`docs/data/`, and a small mobile PWA in `docs/` renders them offline-first.
The JSON output is also consumed by the
[cornerman-site](https://github.com/jackdengler/cornerman-site) project.

```
┌──────────────┐    hourly     ┌──────────────┐    reads     ┌────────────┐
│  Tapology    │ ────────────▶ │  scraper.py  │ ───────────▶ │ docs/data/ │
│  (fightcen-  │  (Playwright) │  (GH Action) │     JSON     │  *.json    │
│   ter+forum) │               └──────────────┘              └─────┬──────┘
└──────────────┘                                                   │
                                                                   ▼
                                                         ┌───────────────────┐
                                                         │  docs/ PWA        │  ← this repo, GH Pages
                                                         │  cornerman-site   │  ← sister repo
                                                         └───────────────────┘
```

## What's here

```
tapology-reader/
├── scraper/scraper.py        # Playwright-based scraper (CLI, see below)
├── scraper/requirements.txt
├── docs/                     # PWA (served by GitHub Pages)
│   ├── index.html
│   ├── css/style.css
│   ├── js/{app,thread-list,thread-detail}.js
│   ├── sw.js                 # service worker
│   └── data/                 # scraped JSON — written by scraper, read by PWA
├── serve.py                  # local static file server for docs/
└── .github/workflows/scrape.yml
```

## Running locally

### Serve the PWA

```sh
python3 serve.py            # http://localhost:8080 (override with PORT=...)
```

### Run the scraper

```sh
pip install -r scraper/requirements.txt
playwright install chromium --with-deps

python scraper/scraper.py                 # full scrape
python scraper/scraper.py --help          # all options
python scraper/scraper.py --dry-run       # discover events+threads, don't write
python scraper/scraper.py --thread 95498  # scrape a single thread by id
python scraper/scraper.py -v              # verbose logging
```

Useful flags:

| Flag | Purpose |
|---|---|
| `--max-pages N` | Cap forum listing pages scanned (default 5) |
| `--delay SECS` | Request delay between pages (default 1.5) |
| `--thread ID` | Scrape a single thread and exit (skips discovery) |
| `--dry-run` | Do discovery but don't write data files |
| `-v`, `-vv` | Verbose / very-verbose logs |

## Data schema

All files live in `docs/data/`.

**`meta.json`** — freshness marker for the UI.
```json
{ "lastUpdated": "2026-04-23T06:17:00Z", "threadCount": 12 }
```

**`threads.json`** — array of thread summaries, one entry per matched event.
```json
{
  "id": "95498",
  "title": "UFC Fight Night: Sterling vs. Zalal",
  "url": "/forum/threads/95498",
  "isSticky": false,
  "lastPostTime": "2026-04-23 02:46:29 -0400",
  "replyCount": 334,
  "snippet": "...",
  "iconUrl": "https://images.tapology.com/...",
  "eventName": "UFC Fight Night: Sterling vs. Zalal",
  "eventDate": "April 25",
  "fightcenterUrl": "/fightcenter/events/140114-ufc-fight-night"
}
```

**`threads/{id}.json`** — full thread detail with every post.
```json
{
  "id": "95498",
  "title": "UFC Fight Night: Sterling vs. Zalal",
  "totalPages": 17,
  "scrapedAt": "2026-04-23T06:17:00+00:00",
  "eventName": "...", "eventDate": "...", "fightcenterUrl": "...",
  "posts": [
    {
      "id": "1234567",
      "author": "someone",
      "authorUrl": "/someone",
      "timestamp": "2026-03-13T10:25:00-05:00",
      "content": "...",
      "upvotes": 3,
      "downvotes": 0
    }
  ]
}
```

## How it works

1. **Discover upcoming events** — fetch `fightcenter?group=ufc&schedule=upcoming`,
   extract name/date/slug for each event.
2. **Match forum threads** — scan `/forum/threads?page=N` up to `--max-pages`,
   fuzzy-match thread titles against event names (normalized, punctuation stripped).
3. **Scrape posts** — for each matched thread, paginate until the pager ends
   and collect every post. Threads whose `replyCount` is unchanged since last
   run are skipped (incremental).
4. **Write** — overwrite `threads.json`, `meta.json`, and per-thread JSON files.
   Thread files for events no longer upcoming are removed.

## Automation

`.github/workflows/scrape.yml` runs the scraper at `:17` every hour and
commits any changes under `docs/data/`. The run has a 20-minute timeout and
a `concurrency` group so overlapping runs can't step on each other.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| "No upcoming events found" | Tapology changed markup OR site is down | Re-run with `-vv`; check `_debug-*.html.json` |
| `playwright install` hangs | Missing system deps | `playwright install-deps chromium` |
| Scraper runs but 0 threads matched | Event titles diverged from forum titles | Raise `--max-pages`; inspect the "Matched" log lines |
| PWA shows stale data | Service worker cache | Hard-refresh (cmd/ctrl+shift+r) or bump `CACHE_VERSION` in `docs/sw.js` |
| Timestamps off by an hour | Tapology returns ET/EDT, scraper writes `-04:00` | Expected — times are ET, rendered as PT in the UI |

## License

Personal / non-commercial use. Respects Tapology's `robots.txt` and ToS via
rate limiting (`REQUEST_DELAY`, default 1.5s).
