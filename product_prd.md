# Product Requirements Document
## MiniSearch — Web Crawler & Search Engine
**Course:** ITU AI Aided Computer Engineering  
**Author:** David Dogukan Erenel
**Student:** Berdan Duman 150210029 
**Date:** March 2026  
**Version:** 1.0

---

## 1. Overview

MiniSearch is a concurrent web crawler and real-time search engine built entirely from Python's standard library. The system crawls websites recursively, builds a live inverted index, and exposes a web-based dashboard for monitoring and querying. It demonstrates architectural patterns found in production search infrastructure — concurrent worker pools, back-pressure management, thread-safe data structures, and persistent state — implemented at a scale appropriate for a single-machine prototype.

---

## 2. Goals & Non-Goals

### Goals
- Crawl from a seed URL to depth k, discovering and indexing all reachable pages
- Support multiple simultaneous crawlers with shared deduplication
- Serve search queries concurrently while indexing is active
- Manage system load automatically via bounded queue back-pressure
- Provide a real-time web dashboard with live metrics and drill-down views
- Persist crawler state across interruptions; resume without restarting

### Non-Goals
- JavaScript-rendered pages (SPAs)
- Distributed / multi-machine crawling
- Full robots.txt compliance
- High-level crawling libraries (Scrapy, BeautifulSoup)
- Production-scale index (Elasticsearch, Solr)

---

## 3. System Architecture

```
┌──────────────────────────────────────────────────────┐
│               Web Dashboard (Flask + SSE)            │
│   Start / Stop / Resume / Search / Detail Modal      │
└────────────────────────┬─────────────────────────────┘
                         │ REST + Server-Sent Events
          ┌──────────────▼──────────────┐
          │         Flask App           │
          │  /start /stop /resume       │
          │  /search /stream /logs      │
          └──────┬───────────────────── ┘
                 │ spawns
    ┌────────────▼──────────────────────────────┐
    │            Crawler (per session)           │
    │  seed_url, depth, workers, rate, max_urls  │
    └──┬────────────────────┬───────────────────┘
       │                    │
  ┌────▼────┐         ┌─────▼──────────────────────┐
  │  URL    │ workers │     Worker Pool             │
  │ Queue   │◄────────│  N threads (urllib.request) │
  │(bounded)│         └─────────────────────────────┘
  └─────────┘                    │ add_page()
                        ┌────────▼────────────┐
                        │   InvertedIndex      │
                        │  token → [entries]   │
                        │  RLock (read/write)  │
                        └────────┬────────────┘
                                 │ search()
                        ┌────────▼────────────┐
                        │    Query Engine      │
                        │  (concurrent reads)  │
                        └─────────────────────┘

Storage (per crawler):
  storage/crawlers/{id}/index.json   ← page contents
  storage/crawlers/{id}/state.json   ← visited + frontier
  storage/crawlers/{id}/logs.jsonl   ← crawl log
  storage/shared/{domain}.json       ← cross-crawler visited
```

---

## 4. Functional Requirements

### 4.1 Crawler / Indexer

| ID | Requirement | Priority |
|----|-------------|----------|
| F-01 | Accept `seed_url`, `max_depth`, `max_workers`, `rate_limit`, `max_urls` | P0 |
| F-02 | Crawl recursively from seed to depth k | P0 |
| F-03 | Track visited URLs in a thread-safe set; never visit a URL twice | P0 |
| F-04 | Fetch HTML using `urllib.request` only (no high-level libraries) | P0 |
| F-05 | Parse links and titles using `html.parser` (stdlib) | P0 |
| F-06 | Limit crawl rate via per-worker sleep (rate limiting) | P1 |
| F-07 | Apply back-pressure via bounded `queue.Queue`; drop excess URLs gracefully | P1 |
| F-08 | Store page URL, title, body text, origin URL, and depth per page | P0 |
| F-09 | Support multiple concurrent crawlers on the same or different domains | P1 |
| F-10 | Share a visited set across crawlers on the same domain (no cross-crawler duplicates) | P1 |
| F-11 | Limit total new URLs processed per session via `max_urls` parameter | P1 |

### 4.2 Search Engine

| ID | Requirement | Priority |
|----|-------------|----------|
| S-01 | Search must work concurrently while indexing is active | P0 |
| S-02 | Return results as `(url, origin_url, depth, title, score)` | P0 |
| S-03 | Score = URL match (+10) + title match (+5) + body frequency (+1 per occurrence) | P1 |
| S-04 | Multi-token queries: rank by token coverage first, then total score | P1 |
| S-05 | Filter common stop words from index and queries | P1 |
| S-06 | All index reads/writes protected by `threading.RLock` | P0 |

### 4.3 Persistence

| ID | Requirement | Priority |
|----|-------------|----------|
| P-01 | Save page index (`index.json`) on stop | P2 (bonus) |
| P-02 | Save crawler state: visited set + frontier queue (`state.json`) | P2 (bonus) |
| P-03 | Resume a stopped crawler from exact checkpoint without data loss | P2 (bonus) |
| P-04 | Fresh start loads existing index but resets visited — finds new pages | P2 (bonus) |

### 4.4 Dashboard

| ID | Requirement | Priority |
|----|-------------|----------|
| D-01 | Show real-time: processed, queue depth, visited, errors, index size | P0 |
| D-02 | Show back-pressure status and queue fill progress bar | P1 |
| D-03 | Show URL limit progress bar | P1 |
| D-04 | Support search from dashboard while crawling | P0 |
| D-05 | Detail modal per crawler: log, frontier queue, visited URLs | P1 |
| D-06 | All URLs in results and detail views are clickable links | P1 |
| D-07 | Clear button: stop all crawlers, delete all storage | P1 |

---

## 5. Non-Functional Requirements

| Category | Requirement |
|----------|-------------|
| **Concurrency** | Thread-safe: `Lock`, `RLock`, `queue.Queue` throughout |
| **Performance** | Worker count configurable (default 5); rate limit configurable |
| **Reliability** | HTTP errors (4xx, 5xx, SSL, timeout) logged and skipped — never crash |
| **Portability** | Python 3.9+; only `flask` as external dependency |
| **Observability** | Per-URL JSONL log; SSE metrics stream; detail modal in dashboard |

---

## 6. Technical Design Decisions

### urllib + html.parser
Project constraint: no high-level crawling libraries. `urllib.request` gives full control over HTTP headers, timeouts, and SSL. `html.parser` from stdlib extracts `<a href>` links and `<title>` tags without additional dependencies.

### Thread-based concurrency
The workload is I/O-bound (network requests). Python's GIL does not limit parallelism for I/O-bound threads — workers block on network, not CPU. `threading` is simpler than `asyncio` for this use case and sufficient for the target scale.

### Inverted Index with URL scoring
```
token → [{ url, origin_url, depth, title, score, in_title, in_url }]
```
URL-path tokens receive the highest weight (+10) because a URL like `/about` reliably signals page topic. Title tokens (+5) confirm topic. Body frequency (+1/occurrence) captures content relevance. Stop words are filtered at index and query time.

### Back-pressure
`queue.Queue(maxsize=N)` with `put_nowait()` — drops excess URLs silently instead of blocking workers. Workers continue processing existing items. The dashboard shows queue fill as a live progress bar that turns red when throttled.

### Persistence model
Two separate files per crawler session: `index.json` (page contents, used to rebuild the inverted index on load) and `state.json` (visited set + frontier queue, used to resume from exact checkpoint). Separating them allows the index to grow across sessions independently of per-session state.

### Multi-crawler deduplication
While multiple crawlers run concurrently on the same domain, they share a single in-memory `visited` set. This prevents the same URL from being fetched twice across parallel workers. When a crawler finishes, the shared set is not cleared — new crawlers on the same domain start fresh (they may re-crawl previously seen URLs, but `add_page` deduplicates at the index level).

---

## 7. Milestones

| Phase | Content | Time |
|-------|---------|------|
| M1 | Core crawler: URL queue, worker pool, urllib fetch | 1h |
| M2 | Inverted index + thread safety + scoring | 1h |
| M3 | Concurrent search + multi-token ranking | 1h |
| M4 | Flask web dashboard + SSE metrics | 1h |
| M5 | Persistence: save/load index + state | 1h |
| M6 | Multi-crawler + shared visited dedup | 1h |
| M7 | Detail modal, logs, queue/visited views | 30m |
| M8 | Documentation | 30m |

---

## 8. Success Criteria

- [x] Crawler recursively crawls to depth k from any seed URL
- [x] No URL is ever processed twice within a session
- [x] Search returns ranked results while indexing is active
- [x] Back-pressure triggers at queue capacity; system slows, never crashes
- [x] All shared state protected by locks; no data corruption
- [x] Crawler can be stopped and resumed from exact checkpoint
- [x] Multiple crawlers on the same domain share a visited set
- [x] Developer can explain every piece of AI-generated code

---

## 9. Out of Scope (Future Work)

- PageRank / link graph scoring
- TF-IDF or BM25 ranking
- JavaScript rendering (Playwright/Puppeteer)
- Distributed crawling (Kafka, Redis, Kubernetes)
- robots.txt compliance
- Full-text search engine integration (Elasticsearch)
