# MiniSearch 🔍
**Concurrent Web Crawler & Real-Time Search Engine**  
ITU — AI Aided Computer Engineering, Homework 1
Berdan Duman 150210029
---

## Overview

MiniSearch is a functional web crawler and search engine built from scratch using only Python's standard library. It supports multiple concurrent crawlers, a live inverted index, real-time web dashboard, and persistent state across sessions.

## Requirements

- Python 3.9+
- Flask (only external dependency)

```bash
git clone https://github.com/bdduman/minisearch.git
cd minisearch
python3 -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

## Running

```bash
python3 app.py
# Open http://localhost:5000
```

## Usage

1. Enter a seed URL and configure parameters
2. Click **▶ Start** — crawler begins immediately
3. Search while crawling from the search box
4. Click **▼ Details** to inspect logs, queue, and visited URLs
5. Click **■ Stop** to pause — state is saved automatically
6. Click **▶ Resume** to continue exactly where it left off
7. Click **✕ Clear** to reset everything

### Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| Seed URL | — | Starting URL |
| Depth | 2 | Maximum crawl depth |
| Workers | 5 | Parallel worker threads |
| Rate/s | 2 | Requests per second per worker |
| Max Queue | 500 | Queue size cap (back-pressure trigger) |
| Max URL | 200 | New URLs to process in this session (0 = unlimited) |

---

## Architecture

```
app.py        →  Flask web server, SSE dashboard, REST API
crawler.py    →  Crawler, InvertedIndex, HTMLParser (all stdlib)
storage/
  crawlers/
    {id}/
      index.json    ← page contents (inverted index rebuilt on load)
      state.json    ← visited set + frontier queue
      logs.jsonl    ← per-URL crawl log
  shared/
    {domain}.json   ← cross-crawler visited coordination
```

### Key Design Decisions

**Back-pressure:** `queue.Queue(maxsize=N)` — when full, `put_nowait()` silently drops new URLs instead of blocking workers. The queue fill level is shown as a real-time progress bar.

**Thread safety:** `InvertedIndex` uses `threading.RLock` for reads/writes. The `visited` set uses a separate `Lock`. All shared state is protected.

**Concurrent search:** The query engine runs on the main thread independently of crawler workers — search is always available, even mid-crawl.

**Native parsing:** `urllib.request` for HTTP + `html.parser` for link/title extraction. No Scrapy, BeautifulSoup, or other high-level libraries.

**Inverted index:** Maps tokens → list of page entries with scores. Scoring: URL match = +10, title match = +5, body frequency = +1 per occurrence. Multi-token queries rank by coverage (matched tokens / total tokens) then score.

**Persistence:** On stop, `index.json` (page contents) and `state.json` (visited + frontier) are written to `storage/crawlers/{id}/`. On resume, the same Crawler object is restarted — no data is reset.

**Multi-crawler deduplication:** Crawlers targeting the same domain share a single in-memory `visited` set while running concurrently, preventing duplicate URL visits across parallel sessions.

---

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/start` | Start a crawler |
| POST | `/stop` | Stop a crawler |
| POST | `/resume` | Resume a stopped crawler |
| POST | `/clear` | Stop all, delete storage |
| POST | `/search` | Search the index |
| GET | `/stream` | SSE metrics stream |
| GET | `/crawler/{id}/logs` | Crawl log entries |
| GET | `/crawler/{id}/queue` | Current frontier queue |
| GET | `/crawler/{id}/visited` | Visited URL list |
| GET | `/shared/visited` | Shared visited sets by domain |

---

## Requirements Coverage

| Requirement | Status |
|------------|--------|
| Recursive crawling (depth k) | ✅ |
| Visited set — no duplicate crawls | ✅ |
| Back-pressure (bounded queue) | ✅ |
| Native urllib + html.parser only | ✅ |
| Concurrent search during indexing | ✅ |
| Thread-safe data structures (Lock, RLock, Queue) | ✅ |
| Relevancy scoring | ✅ |
| Real-time web dashboard (SSE) | ✅ |
| Persistence — resume after interruption | ✅ (bonus) |
| Multiple concurrent crawlers | ✅ |
# minisearch
