"""
MiniSearch - CLI Dashboard
Gercek zamanli metrikler + arama arayuzu
"""

import threading
import time
import sys
import os
import argparse

from crawler import Crawler


# ---------------------------------------------------------------------------
# Renkli terminal ciktisi (ANSI)
# ---------------------------------------------------------------------------
class C:
    RESET  = "\033[0m"
    BOLD   = "\033[1m"
    GREEN  = "\033[92m"
    YELLOW = "\033[93m"
    CYAN   = "\033[96m"
    RED    = "\033[91m"
    GRAY   = "\033[90m"
    BLUE   = "\033[94m"


def clear_line():
    sys.stdout.write("\r\033[K")


def print_banner():
    print(f"""
{C.CYAN}{C.BOLD}
  __  __ _       _ ____                      _     
 |  \\/  (_)_ __ (_) ___|  ___  __ _ _ __ ___| |__  
 | |\\/| | | '_ \\| \\___ \\ / _ \\/ _` | '__/ __| '_ \\ 
 | |  | | | | | | |___) |  __/ (_| | | | (__| | | |
 |_|  |_|_|_| |_|_|____/ \\___|\\__,_|_|  \\___|_| |_|
{C.RESET}
{C.GRAY}  ITU AI Aided Computer Engineering — Project 1{C.RESET}
""")


# ---------------------------------------------------------------------------
# Dashboard thread
# ---------------------------------------------------------------------------
def dashboard_thread(crawler: Crawler, interval: float = 1.0):
    """Arkaplanda metrikleri ekrana yazar."""
    while True:
        stats = crawler.get_stats()
        if not stats.running:
            break

        throttle_str = (
            f"{C.RED}● THROTTLED{C.RESET}" if stats.throttled
            else f"{C.GREEN}● OK{C.RESET}"
        )
        bar_filled = min(stats.queued, 40)
        bar = "█" * bar_filled + "░" * (40 - bar_filled)

        clear_line()
        sys.stdout.write(
            f"{C.BOLD}[Dashboard]{C.RESET} "
            f"İşlendi: {C.GREEN}{stats.processed:>5}{C.RESET}  "
            f"Kuyruk: {C.YELLOW}{stats.queued:>4}{C.RESET}  "
            f"Hata: {C.RED}{stats.errors:>3}{C.RESET}  "
            f"Back-pressure: {throttle_str}  "
            f"[{bar}]"
        )
        sys.stdout.flush()
        time.sleep(interval)
    print()


# ---------------------------------------------------------------------------
# Arama sonuclarini yazdir
# ---------------------------------------------------------------------------
def print_results(results: list[dict], query: str):
    if not results:
        print(f"\n{C.YELLOW}Sonuç bulunamadı: '{query}'{C.RESET}\n")
        return

    print(f"\n{C.BOLD}{C.CYAN}═══ Arama Sonuçları: '{query}' ({len(results)} eşleşme) ═══{C.RESET}")
    for i, r in enumerate(results[:10], 1):
        print(
            f"\n  {C.BOLD}{i}.{C.RESET} {C.BLUE}{r['url']}{C.RESET}\n"
            f"     Kaynak : {C.GRAY}{r['origin_url']}{C.RESET}\n"
            f"     Derinlik: {r['depth']}   Skor: {C.GREEN}{r['score']}{C.RESET}"
        )
    print()


# ---------------------------------------------------------------------------
# Ana program
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="MiniSearch — Web Crawler & Arama Motoru"
    )
    parser.add_argument("url", help="Başlangıç URL'si (seed)")
    parser.add_argument("--depth",    type=int,   default=2,    help="Maksimum tarama derinliği (varsayılan: 2)")
    parser.add_argument("--workers",  type=int,   default=5,    help="Paralel worker sayısı (varsayılan: 5)")
    parser.add_argument("--rate",     type=float, default=2.0,  help="Saniyedeki istek/worker (varsayılan: 2)")
    parser.add_argument("--queue",    type=int,   default=200,  help="Max kuyruk boyutu (varsayılan: 200)")
    parser.add_argument("--save",     type=str,   default=None, help="İndeksi kaydet (örn: index.json)")
    parser.add_argument("--load",     type=str,   default=None, help="İndeks dosyasından yükle")
    parser.add_argument("--no-domain-limit", action="store_true", help="Tüm domainleri tara")
    args = parser.parse_args()

    print_banner()

    crawler = Crawler(
        seed_url=args.url,
        max_depth=args.depth,
        max_workers=args.workers,
        max_queue_size=args.queue,
        rate_limit=args.rate,
        same_domain_only=not args.no_domain_limit,
        save_path=args.save,
    )

    # Önceki indeksi yükle (bonus: persistence)
    if args.load and os.path.exists(args.load):
        crawler.index.load(args.load)
        print(f"{C.GREEN}✓ İndeks yüklendi: {args.load}{C.RESET}")

    # Taramayı başlat
    crawler.start()

    # Dashboard arkaplanda çalışsın
    dash = threading.Thread(
        target=dashboard_thread,
        args=(crawler,),
        name="Dashboard",
        daemon=True,
    )
    dash.start()

    print(f"\n{C.GRAY}Tarama çalışıyor. Arama yapmak için sorgu girin, çıkmak için 'q' yazın.{C.RESET}\n")

    # Eş zamanlı arama döngüsü
    try:
        while crawler.stats.running:
            try:
                query = input(f"\n{C.BOLD}🔍 Arama:{C.RESET} ").strip()
            except EOFError:
                break

            if query.lower() in ("q", "quit", "exit", "cikis", "çıkış"):
                break
            elif query.lower() in ("stats", "durum"):
                s = crawler.get_stats()
                print(
                    f"\n  İşlendi: {s.processed} | Kuyruk: {s.queued} | "
                    f"Hata: {s.errors} | İndeks: {crawler.index.page_count()} sayfa\n"
                )
            elif query:
                results = crawler.search(query)
                print_results(results, query)

    except KeyboardInterrupt:
        pass
    finally:
        print(f"\n{C.YELLOW}Durduruluyor...{C.RESET}")
        crawler.stop()
        print(f"{C.GREEN}✓ Tamamlandı. {crawler.stats.processed} sayfa işlendi.{C.RESET}\n")


if __name__ == "__main__":
    main()
