"""
MiniSearch - Web Crawler & Search Engine
ITU AI Aided Computer Engineering - Project 1

Yalnizca Python stdlib kullanilir:
  urllib.request  - HTTP istekleri
  html.parser     - HTML parse
  threading       - Concurrency
  queue           - Thread-safe kuyruk (back-pressure)
  logging         - Loglama
"""

import urllib.request
import urllib.error
import urllib.parse
import ssl

# Mac'te SSL sertifika sorunlarini atlamak icin (gelistirme ortami)
_ssl_ctx = ssl.create_default_context()
_ssl_ctx.check_hostname = False
_ssl_ctx.verify_mode = ssl.CERT_NONE
from html.parser import HTMLParser
import threading
import queue
import logging
import time
import json
import os
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from typing import Optional

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(threadName)s] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("minisearch")


# ---------------------------------------------------------------------------
# Veri Yapilari
# ---------------------------------------------------------------------------
@dataclass
class PageRecord:
    url: str
    origin_url: str
    depth: int
    title: str = ""
    text: str = ""


@dataclass
class CrawlStats:
    processed: int = 0
    queued: int = 0
    errors: int = 0
    visited: int = 0
    throttled: bool = False
    running: bool = True


# ---------------------------------------------------------------------------
# HTML Parser  (stdlib html.parser kullanir, BeautifulSoup YOK)
# ---------------------------------------------------------------------------
class SimpleHTMLParser(HTMLParser):
    """Basliklar ve linkleri cikarir."""

    def __init__(self, base_url: str):
        super().__init__()
        self.base_url = base_url
        self.links: list[str] = []
        self.title: str = ""
        self.text_parts: list[str] = []
        self._in_title = False
        self._in_script = False
        self._in_style = False

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        if tag == "title":
            self._in_title = True
        elif tag in ("script", "style"):
            self._in_script = True
        elif tag == "a" and "href" in attrs_dict:
            href = attrs_dict["href"]
            full_url = urllib.parse.urljoin(self.base_url, href)
            parsed = urllib.parse.urlparse(full_url)
            # Sadece http/https linkleri al, fragment'lari temizle
            if parsed.scheme in ("http", "https"):
                clean = parsed._replace(fragment="").geturl()
                self.links.append(clean)

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        elif tag in ("script", "style"):
            self._in_script = False

    def handle_data(self, data):
        if self._in_title:
            self.title += data.strip()
        elif not self._in_script:
            stripped = data.strip()
            if stripped:
                self.text_parts.append(stripped)

    def get_text(self) -> str:
        return " ".join(self.text_parts)


# ---------------------------------------------------------------------------
# Inverted Index  (thread-safe)
# ---------------------------------------------------------------------------
class InvertedIndex:
    """
    Kelime -> [PageRecord listesi] eslesmesi.
    Okuma/yazma RLock ile korunur.
    """

    def __init__(self):
        self._lock = threading.RLock()
        self._index: dict[str, list[dict]] = defaultdict(list)
        self._pages: list[PageRecord] = []
        self._url_set: set[str] = set()  # hizli duplicate kontrolu

    def add_page(self, record: PageRecord) -> bool:
        """
        Sayfayı indekse ekler.
        Returns: True = yeni sayfa eklendi, False = zaten vardı (güncellendi)

        Skor:
          URL'de geçiyorsa    → +10
          Başlıkta geçiyorsa  → +5
          İçerikte her geçiş  → +1
        """
        url_tokens   = self._tokenize(record.url)
        title_tokens = self._tokenize(record.title)
        body_tokens  = self._tokenize(record.text)
        url_set      = set(url_tokens)
        title_set    = set(title_tokens)

        freq: dict[str, int] = defaultdict(int)
        for t in title_tokens + body_tokens:
            freq[t] += 1

        all_words = set(url_tokens + title_tokens) | set(freq.keys())
        entries = []
        for word in all_words:
            if word in self.STOP_WORDS or len(word) < 2:
                continue
            in_url   = word in url_set
            in_title = word in title_set
            score    = (10 if in_url else 0) + (5 if in_title else 0) + freq.get(word, 0)
            entries.append((word, {
                "url":        record.url,
                "origin_url": record.origin_url,
                "depth":      record.depth,
                "title":      record.title,
                "score":      score,
                "in_title":   in_title,
                "in_url":     in_url,
            }))

        with self._lock:
            is_new = record.url not in self._url_set

            if is_new:
                self._pages.append(record)
                self._url_set.add(record.url)
            else:
                # Eski kayıtları temizle, güncel içerikle değiştir
                for word in list(self._index.keys()):
                    self._index[word] = [e for e in self._index[word] if e["url"] != record.url]

            for word, entry in entries:
                self._index[word].append(entry)

        return is_new

    def search(self, query: str) -> list[dict]:
        """
        Sorgu mantığı:
        - Her kelime ayrı aranır
        - Sonuçlar: (kaç kelime eşleşti / toplam) × skor ile sıralanır
        - Çok kelimeli aramada tüm kelimelerde geçen sayfalar öne çıkar
        """
        tokens = [t for t in self._tokenize(query)
                  if t not in self.STOP_WORDS and len(t) > 1]
        if not tokens:
            return []

        with self._lock:
            combined: dict[str, dict] = {}
            for token in tokens:
                for entry in self._index.get(token, []):
                    url = entry["url"]
                    if url not in combined:
                        combined[url] = dict(entry)
                        combined[url]["matched_tokens"] = 1
                    else:
                        combined[url]["score"]          += entry["score"]
                        combined[url]["matched_tokens"] += 1

        if not combined:
            return []

        total = len(tokens)
        return sorted(
            combined.values(),
            key=lambda r: (r["matched_tokens"] / total, r["score"]),
            reverse=True
        )

    def page_count(self) -> int:
        with self._lock:
            return len(self._pages)

    def save(self, path: str):
        """Sadece sayfa içeriklerini kaydeder (site geneli indeks)."""
        with self._lock:
            data = {"pages": [asdict(p) for p in self._pages]}
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        size_kb = len(json.dumps(data)) // 1024
        log.info(f"Indeks kaydedildi: {path} ({len(self._pages)} sayfa, ~{size_kb}KB)")

    def load(self, path: str):
        """Sayfa içeriklerini yükler, indeksi yeniden oluşturur."""
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        pages = [PageRecord(**p) for p in data.get("pages", [])]
        # Önce temizle, sonra her şeyi tek seferde yükle
        with self._lock:
            self._pages = []
            self._index = defaultdict(list)
        # Lock dışında rebuild (performans), sonra pages'i ata
        new_index = defaultdict(list)
        for record in pages:
            self._rebuild_index_into(record, new_index)
        url_set = {p.url for p in pages}
        with self._lock:
            self._pages   = pages
            self._index   = new_index
            self._url_set = url_set
        log.info(f"Indeks yuklendi: {path} ({len(pages)} sayfa)")

    @staticmethod
    def load_state(state_path: str) -> tuple:
        """Crawler state'ini yükler: (visited set, frontier list, processed int)."""
        import json as _json
        with open(state_path, "r") as f:
            state = _json.load(f)
        visited  = set(state.get("visited", []))
        frontier = [tuple(item) for item in state.get("frontier", [])]
        processed = state.get("processed", 0)
        log.info(f"State yuklendi: {state_path} ({len(visited)} visited, {len(frontier)} frontier)")
        return visited, frontier, processed

    def _rebuild_index_into(self, record: "PageRecord", index: dict):
        """Tek sayfa için index dict'e yazar (thread-safe değil, load sırasında kullanılır)."""
        url_tokens   = self._tokenize(record.url)
        title_tokens = self._tokenize(record.title)
        body_tokens  = self._tokenize(record.text)
        url_set      = set(url_tokens)
        title_set    = set(title_tokens)
        freq: dict[str, int] = defaultdict(int)
        for t in title_tokens + body_tokens:
            freq[t] += 1
        all_words = set(url_tokens + title_tokens) | set(freq.keys())
        for word in all_words:
            if word in self.STOP_WORDS or len(word) < 2:
                continue
            in_url   = word in url_set
            in_title = word in title_set
            score = (10 if in_url else 0) + (5 if in_title else 0) + freq.get(word, 0)
            index[word].append({
                "url":        record.url,
                "origin_url": record.origin_url,
                "depth":      record.depth,
                "title":      record.title,
                "score":      score,
                "in_title":   in_title,
                "in_url":     in_url,
            })

    def _rebuild_index(self, record: "PageRecord"):
        """Geriye dönük compat - add_page ile aynı mantık."""
        self._rebuild_index_into(record, self._index)

    STOP_WORDS = {
        "the","a","an","and","or","but","in","on","at","to","for","of",
        "with","by","from","is","are","was","were","be","been","have",
        "has","had","do","does","did","this","that","it","its","as",
        "if","so","not","no","all","can","also","more","will","would",
    }

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        """Metni küçük harfe çevirip kelimelere böler."""
        import re
        return re.findall(r"[a-z0-9]+", text.lower())



# ---------------------------------------------------------------------------
# Crawler
# ---------------------------------------------------------------------------
class Crawler:
    """
    Back-pressure icin sinirli Queue kullanir.
    Worker thread'ler URL'leri ceker, isler, yeni linkleri kuyruga ekler.
    """

    def __init__(
        self,
        seed_url: str,
        crawler_id: str = "1",
        max_depth: int = 3,
        max_workers: int = 5,
        max_queue_size: int = 200,
        max_urls: int = 0,         # 0 = sinirsiz
        rate_limit: float = 0.5,   # saniyede max istek / worker
        timeout: int = 8,
        same_domain_only: bool = True,
        save_path: Optional[str] = None,
        state_path: Optional[str] = None,
        log_path: Optional[str] = None,
        shared_visited: Optional[set] = None,
        shared_visited_lock: Optional[object] = None,
    ):
        self.seed_url = seed_url
        self.crawler_id = crawler_id
        self.max_depth = max_depth
        self.max_workers = max_workers
        self.max_urls = max_urls
        self.rate_limit = rate_limit
        self.timeout = timeout
        self.same_domain_only = same_domain_only
        self.save_path  = save_path
        self.state_path = state_path
        self.log_path   = log_path
        self._log_lock  = threading.Lock()

        self._seed_domain = urllib.parse.urlparse(seed_url).netloc

        # Thread-safe veri yapilari
        self._url_queue: queue.Queue = queue.Queue(maxsize=max_queue_size)

        # Shared visited: birden fazla crawler aynı set'i paylaşabilir
        if shared_visited is not None:
            self._visited = shared_visited
            self._visited_lock = shared_visited_lock
        else:
            self._visited: set[str] = set()
            self._visited_lock = threading.Lock()

        self.index = InvertedIndex()
        self.stats = CrawlStats()
        self._stats_lock = threading.Lock()

        self._workers: list[threading.Thread] = []
        self._stop_event = threading.Event()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def start(self):
        """Taramayi baslatir."""
        log.info(f"Tarama basliyor: {self.seed_url} (max_depth={self.max_depth})")

        # Kuyruk bossa seed'i ekle
        if self._url_queue.empty():
            self._url_queue.put((self.seed_url, self.seed_url, 0))

        self._stop_event.clear()
        with self._stats_lock:
            self.stats.running = True

        self._workers = []
        for i in range(self.max_workers):
            t = threading.Thread(
                target=self._worker,
                name=f"C{self.crawler_id}-Worker-{i+1}",
                daemon=True,
            )
            t.start()
            self._workers.append(t)

    def resume(self):
        """Mevcut crawler'ı kaldığı yerden devam ettirir.
        visited, indeks, stats — hiçbiri sıfırlanmaz.
        Kuyrukta URL varsa oradan, yoksa tarama bitmiş demektir."""
        if self.stats.running:
            return

        queue_size = self._url_queue.qsize()
        log.info(f"Resume: kuyrukta {queue_size} URL, "
                 f"indeks={self.index.page_count()}, visited={len(self._visited)}")

        # Kuyruk tamamen boşsa tarama zaten bitmişti — birşey yapma
        if self._url_queue.empty():
            log.info("Kuyruk boş, tarama tamamlanmıştı. Resume edilmedi.")
            with self._stats_lock:
                self.stats.running = False
            return

        self._stop_event.clear()
        with self._stats_lock:
            self.stats.running = True

        self._workers = []
        for i in range(self.max_workers):
            t = threading.Thread(
                target=self._worker,
                name=f"C{self.crawler_id}-Worker-{i+1}",
                daemon=True,
            )
            t.start()
            self._workers.append(t)
        log.info(f"Resume edildi: {self.max_workers} worker, {queue_size} URL işlenecek")

    def _write_log(self, event: str, url: str, depth: int, origin: str,
                   title: str = "", error: str = ""):
        """JSONL formatında log yazar."""
        if not self.log_path:
            return
        import json as _json
        entry = {
            "ts":     __import__("time").strftime("%H:%M:%S"),
            "event":  event,   # crawling / indexed / error / skipped
            "url":    url,
            "origin": origin,
            "depth":  depth,
            "title":  title,
            "error":  error,
        }
        with self._log_lock:
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(_json.dumps(entry, ensure_ascii=False) + "\n")

    def stop(self):
        """Taramayi durdurur. Worker'ların durmasını bekler, frontier'i korur."""
        self._stop_event.set()
        with self._stats_lock:
            self.stats.running = False
        log.info("Durdurma sinyali gonderildi, worker'lar bekleniyor...")

        # Worker'ların durmasını bekle (max 3sn)
        for t in self._workers:
            t.join(timeout=3)

        # Şimdi kuyruk sabit — frontier'i al
        frontier = []
        while not self._url_queue.empty():
            try:
                frontier.append(self._url_queue.get_nowait())
            except:
                break

        # Frontier'i geri koy (resume için)
        self._frontier_backup = frontier
        for item in frontier:
            try:
                self._url_queue.put_nowait(item)
            except:
                break

        log.info(f"Durduruldu: {len(frontier)} URL frontier'de bekliyor")

        with self._visited_lock:
            visited_copy = set(self._visited)

        if self.save_path:
            self.index.save(self.save_path)

        if self.state_path:
            import json as _json
            state = {"visited": list(visited_copy), "frontier": frontier, "processed": self.stats.processed}
            with open(self.state_path, "w") as f:
                _json.dump(state, f)
            log.info(f"State: {len(visited_copy)} visited, {len(frontier)} frontier")



    def wait_until_done(self):
        """Kuyruk boşalana kadar bekler."""
        self._url_queue.join()
        self.stop()

    def search(self, query: str) -> list[dict]:
        return self.index.search(query)

    def get_stats(self) -> CrawlStats:
        with self._stats_lock:
            self.stats.queued = self._url_queue.qsize()
        with self._visited_lock:
            self.stats.visited = len(self._visited)
        return self.stats

    # ------------------------------------------------------------------
    # Worker
    # ------------------------------------------------------------------
    def _worker(self):
        while not self._stop_event.is_set():
            try:
                url, origin, depth = self._url_queue.get(timeout=1)
            except queue.Empty:
                # Kuyruk bos ve calisan baska sey yok - bitti
                if self._url_queue.empty():
                    with self._stats_lock:
                        self.stats.running = False
                    self._stop_event.set()
                continue

            try:
                self._process(url, origin, depth)
            except Exception as e:
                log.warning(f"Islenemedi {url}: {e}")
                with self._stats_lock:
                    self.stats.errors += 1
            finally:
                self._url_queue.task_done()

            # Rate limiting
            time.sleep(1.0 / self.rate_limit if self.rate_limit > 0 else 0)

    def _process(self, url: str, origin: str, depth: int):
        # Max URL limiti: sadece bu crawl'da YENİ işlenenler sayılır
        # (shared'dan gelen eski URL'ler sayılmaz)
        if self.max_urls > 0:
            with self._stats_lock:
                if self.stats.processed >= self.max_urls:
                    self._stop_event.set()
                    self.stats.running = False
                    return

        # Ziyaret kontrolu
        with self._visited_lock:
            if url in self._visited:
                return
            self._visited.add(url)

        log.info(f"[depth={depth}] {url}")
        self._write_log("crawling", url, depth, origin)

        # HTTP istegi (yalnizca urllib)
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "MiniSearch/1.0 (ITU project)"},
            )
            with urllib.request.urlopen(req, timeout=self.timeout, context=_ssl_ctx) as resp:
                content_type = resp.headers.get("Content-Type", "")
                if "text/html" not in content_type:
                    return
                raw = resp.read(500_000)  # max 500KB
                html = raw.decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            log.debug(f"HTTP {e.code} {url}")
            self._write_log("error", url, depth, origin, error=f"HTTP {e.code}")
            with self._stats_lock:
                self.stats.errors += 1
            return
        except urllib.error.URLError as e:
            log.debug(f"URL hatasi {url}: {e.reason}")
            self._write_log("error", url, depth, origin, error=str(e.reason)[:80])
            with self._stats_lock:
                self.stats.errors += 1
            return
        except Exception as e:
            log.debug(f"Beklenmedik hata {url}: {e}")
            self._write_log("error", url, depth, origin, error=str(e)[:80])
            with self._stats_lock:
                self.stats.errors += 1
            return

        # HTML parse
        parser = SimpleHTMLParser(base_url=url)
        parser.feed(html)

        record = PageRecord(
            url=url,
            origin_url=origin,
            depth=depth,
            title=parser.title or url,
            text=parser.get_text()[:5000],  # ilk 5000 karakter
        )
        is_new = self.index.add_page(record)

        with self._stats_lock:
            if is_new:
                self.stats.processed += 1
                self._write_log("indexed", url, depth, origin, title=record.title)

        # Yeni linkleri kuyruğa ekle
        if depth < self.max_depth:
            with self._stats_lock:
                self.stats.throttled = self._url_queue.full()
            for link in set(parser.links):
                if self._should_crawl(link):
                    try:
                        # put_nowait: bloke ETMEZ, kuyruk doluysa atlar
                        # Worker işlemeye devam eder, kuyruk boşaldıkça yeniler girer
                        self._url_queue.put_nowait((link, url, depth + 1))
                    except queue.Full:
                        log.debug(f"Kuyruk dolu, atlandi: {link}")

    def _should_crawl(self, url: str) -> bool:
        if self.same_domain_only:
            domain = urllib.parse.urlparse(url).netloc
            if domain != self._seed_domain:
                return False
        with self._visited_lock:
            return url not in self._visited