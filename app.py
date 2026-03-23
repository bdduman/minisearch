"""
MiniSearch - Web Dashboard
Flask sunucusu: SSE ile gercek zamanli metrikler + arama arayuzu
"""

import threading
import json
import time
import sys
import os
import logging
import queue

from flask import Flask, Response, request, jsonify, render_template_string

# crawler.py ile ayni klasorde olmali
sys.path.insert(0, os.path.dirname(__file__))
from crawler import Crawler

log = logging.getLogger("minisearch.app")

app = Flask(__name__)

# Birden fazla crawler destegi
crawlers: dict[str, Crawler] = {}
crawlers_lock = threading.Lock()

# Her crawler kendi visited set'ini kullanır
# Aynı URL'yi iki kez indeksleme add_page() içindeki _url_set ile önlenir


def save_pdata():
    """Tüm crawler'ların indeksini birleştirip data/storage/p.data'ya yazar."""
    _base = os.path.dirname(os.path.abspath(__file__))
    _pdata_dir = os.path.join(_base, "data", "storage")
    os.makedirs(_pdata_dir, exist_ok=True)
    _pdata_path = os.path.join(_pdata_dir, "p.data")

    all_entries = []
    with crawlers_lock:
        for c in crawlers.values():
            with c.index._lock:
                for word, entries in c.index._index.items():
                    for entry in entries:
                        all_entries.append((
                            word,
                            entry.get("url", ""),
                            entry.get("origin_url", ""),
                            entry.get("depth", 0),
                            entry.get("frequency", 0),
                        ))

    all_entries.sort(key=lambda x: (x[0], x[1]))
    with open(_pdata_path, "w", encoding="utf-8") as f:
        for word, url, orig, depth, freq in all_entries:
            f.write(f"{word} {url} {orig} {depth} {freq}\n")
    log.info(f"p.data kaydedildi: {_pdata_path} ({len(all_entries)} entry, {len(set(c.crawler_id for c in crawlers.values()))} crawler)")


# ---------------------------------------------------------------------------
# HTML Sayfasi
# ---------------------------------------------------------------------------
HTML = r"""<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>MiniSearch Dashboard</title>
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@300;400;600;700&family=Syne:wght@400;700;800&display=swap" rel="stylesheet">
<style>
  :root { --bg:#0a0a0f;--surface:#111118;--border:#1e1e2e;--accent:#00ff88;--accent2:#0088ff;--warn:#ff6b35;--text:#e2e8f0;--muted:#4a5568;--card:#13131f; }
  *,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
  body{background:var(--bg);color:var(--text);font-family:"JetBrains Mono",monospace;min-height:100vh}
  body::before{content:"";position:fixed;inset:0;background-image:linear-gradient(rgba(0,255,136,.03) 1px,transparent 1px),linear-gradient(90deg,rgba(0,255,136,.03) 1px,transparent 1px);background-size:40px 40px;pointer-events:none;z-index:0}
  .wrap{position:relative;z-index:1;max-width:1100px;margin:0 auto;padding:2rem 1.5rem}
  header{display:flex;align-items:center;gap:1.5rem;border-bottom:1px solid var(--border);padding-bottom:1.5rem;margin-bottom:2rem}
  .logo{font-family:"Syne",sans-serif;font-size:1.8rem;font-weight:800;letter-spacing:-.03em;background:linear-gradient(135deg,var(--accent),var(--accent2));-webkit-background-clip:text;-webkit-text-fill-color:transparent}
  .logo span{font-weight:300;opacity:.6}
  .hdot{width:10px;height:10px;border-radius:50%;background:var(--muted);margin-left:auto;transition:background .3s}
  .hdot.running{background:var(--accent);animation:pulse 1.5s infinite}
  .hdot.done{background:var(--accent2)}
  @keyframes pulse{0%,100%{box-shadow:0 0 0 0 rgba(0,255,136,.4)}50%{box-shadow:0 0 0 8px rgba(0,255,136,0)}}

  #start-section{background:var(--card);border:1px solid var(--border);border-radius:12px;padding:2rem;margin-bottom:2rem}
  #start-section h2{font-family:"Syne",sans-serif;font-size:1rem;font-weight:700;color:var(--accent);letter-spacing:.1em;text-transform:uppercase;margin-bottom:1.2rem}
  .form-row{display:grid;grid-template-columns:1fr repeat(5,auto) auto;gap:.75rem;align-items:end}
  label{display:block;font-size:.7rem;color:var(--muted);margin-bottom:.4rem;letter-spacing:.08em;text-transform:uppercase}
  input[type=text],input[type=number]{background:var(--bg);border:1px solid var(--border);color:var(--text);font-family:"JetBrains Mono",monospace;font-size:.875rem;padding:.6rem .9rem;border-radius:8px;width:100%;outline:none;transition:border-color .2s}
  input:focus{border-color:var(--accent)}
  .btn{padding:.65rem 1.4rem;border-radius:8px;border:none;font-family:"JetBrains Mono",monospace;font-size:.875rem;font-weight:600;cursor:pointer;transition:all .2s}
  .btn-primary{background:var(--accent);color:#000}
  .btn-primary:hover{filter:brightness(1.15);transform:translateY(-1px)}
  .btn-danger{background:transparent;color:var(--warn);border:1px solid var(--warn)}
  .btn-danger:hover{background:var(--warn);color:#fff}
  .btn-sm{padding:.4rem .9rem;font-size:.75rem;border-radius:6px}

  #crawlers-list{margin-bottom:2rem}
  .cl-title{font-family:"Syne",sans-serif;font-size:.85rem;font-weight:700;color:var(--muted);letter-spacing:.12em;text-transform:uppercase;margin-bottom:1rem}
  .ci{background:var(--card);border:1px solid var(--border);border-radius:12px;padding:1.4rem;margin-bottom:1rem;animation:slideIn .3s ease}
  .ci.running{border-color:rgba(0,255,136,.3)}
  .ci.stopped{border-color:var(--border);opacity:.75}
  @keyframes slideIn{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:none}}
  .ci-header{display:flex;align-items:center;gap:.7rem;margin-bottom:1.1rem}
  .ci-badge{font-family:"Syne",sans-serif;font-size:.7rem;font-weight:700;padding:.2rem .65rem;border-radius:99px;background:rgba(0,255,136,.1);color:var(--accent);border:1px solid rgba(0,255,136,.2);flex-shrink:0}
  .ci-url{font-size:.8rem;color:var(--text);flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  .ci-state{font-size:.7rem;font-weight:600;flex-shrink:0}
  .ci-state.running{color:var(--accent)}
  .ci-state.stopped{color:var(--muted)}
  .ci-state.done{color:var(--accent2)}
  .cdot{width:8px;height:8px;border-radius:50%;background:var(--muted);flex-shrink:0}
  .cdot.running{background:var(--accent);animation:pulse 1.5s infinite}
  .cdot.done{background:var(--accent2)}
  .cdot.stopped{background:var(--muted)}

  .stats-grid{display:grid;grid-template-columns:repeat(5,1fr);gap:.6rem;margin-bottom:.9rem}
  .stat-card{background:var(--bg);border:1px solid var(--border);border-radius:9px;padding:.85rem 1rem}
  .stat-card.lit::after{opacity:1}
  .stat-label{font-size:.62rem;color:var(--muted);text-transform:uppercase;letter-spacing:.1em;margin-bottom:.3rem}
  .stat-value{font-size:1.7rem;font-weight:700;font-family:"Syne",sans-serif;line-height:1}
  .c-green{color:var(--accent)} .c-blue{color:var(--accent2)} .c-orange{color:var(--warn)} .c-gray{color:var(--muted)} .c-yellow{color:#ffd700}

  .detail{overflow:hidden;max-height:0;transition:max-height .3s ease}
  .detail.open{max-height:160px}
  .detail-inner{padding-top:.9rem;border-top:1px solid var(--border);margin-top:.4rem}
  .bar-wrap{margin-bottom:.7rem}
  .bar-hdr{display:flex;justify-content:space-between;font-size:.65rem;color:var(--muted);margin-bottom:.35rem}
  .bar-track{height:5px;background:var(--border);border-radius:99px;overflow:hidden}
  .bar-fill{height:100%;border-radius:99px;background:linear-gradient(90deg,var(--accent),var(--accent2));transition:width .5s;width:0%}
  .bar-fill.hot{background:linear-gradient(90deg,var(--warn),#ff3366)}
  .bar-fill.url{background:linear-gradient(90deg,var(--accent2),#8844ff)}

  .search-section{background:var(--card);border:1px solid var(--border);border-radius:12px;padding:1.5rem;margin-bottom:2rem}
  .search-section h2{font-family:"Syne",sans-serif;font-size:1rem;font-weight:700;color:var(--accent2);letter-spacing:.1em;text-transform:uppercase;margin-bottom:1rem}
  .search-row{display:flex;gap:.75rem}
  .search-row input{flex:1}
  #results{margin-top:1.2rem}
  .ri{border:1px solid var(--border);border-radius:8px;padding:1rem 1.2rem;margin-bottom:.6rem;background:var(--bg);animation:slideIn .25s}
  .ri-url{color:var(--accent2);font-size:.85rem;word-break:break-all}
  .ri-meta{font-size:.7rem;color:var(--muted);margin-top:.35rem}
  .ri-meta span{margin-right:.8rem}
  .badge{display:inline-block;padding:.1rem .5rem;border-radius:99px;font-size:.65rem;background:rgba(0,255,136,.1);color:var(--accent);border:1px solid rgba(0,255,136,.2)}
  .badge2{background:rgba(0,136,255,.1);color:var(--accent2);border-color:rgba(0,136,255,.2)}
  .no-result{color:var(--muted);font-size:.875rem;padding:.5rem 0}
  .ri-title{font-size:.9rem;font-weight:600;color:var(--text);margin-bottom:.25rem}
  a.ri-url{color:var(--accent2);font-size:.85rem;word-break:break-all;text-decoration:none}
  a.ri-url:hover{text-decoration:underline}

  /* Modal */
  .modal-overlay{position:fixed;inset:0;background:rgba(0,0,0,.7);z-index:100;display:none;align-items:center;justify-content:center}
  .modal-overlay.open{display:flex}
  .modal{background:var(--card);border:1px solid var(--border);border-radius:14px;width:min(900px,95vw);max-height:85vh;display:flex;flex-direction:column}
  .modal-header{display:flex;align-items:center;gap:.75rem;padding:1.2rem 1.4rem;border-bottom:1px solid var(--border)}
  .modal-header h3{font-family:"Syne",sans-serif;font-size:1rem;font-weight:700;flex:1}
  .modal-tabs{display:flex;gap:.5rem;padding:.8rem 1.4rem;border-bottom:1px solid var(--border)}
  .tab-btn{padding:.35rem .9rem;border-radius:6px;border:1px solid var(--border);background:transparent;color:var(--muted);font-family:"JetBrains Mono",monospace;font-size:.75rem;cursor:pointer;transition:all .2s}
  .tab-btn.active{background:var(--accent);color:#000;border-color:var(--accent)}
  .modal-body{flex:1;overflow-y:auto;padding:1rem 1.4rem}
  .log-line{font-size:.72rem;line-height:1.7;border-bottom:1px solid var(--border);padding:.15rem 0;display:grid;grid-template-columns:60px 80px 1fr auto;gap:.5rem}
  .log-line .ev-crawling{color:var(--muted)}
  .log-line .ev-indexed{color:var(--accent)}
  .log-line .ev-error{color:var(--warn)}
  .log-line a{color:var(--accent2);text-decoration:none;font-size:.7rem;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  .log-line a:hover{text-decoration:underline}
  .q-line{font-size:.72rem;line-height:1.8;border-bottom:1px solid var(--border);padding:.1rem 0}
  .q-line a{color:var(--accent2);text-decoration:none}
  .q-line a:hover{text-decoration:underline}
  .v-line{font-size:.72rem;line-height:1.8;border-bottom:1px solid var(--border);padding:.1rem 0}
  .v-line a{color:var(--muted);text-decoration:none}
  .v-line a:hover{color:var(--accent2);text-decoration:underline}
  .stat-pill{font-size:.65rem;padding:.1rem .5rem;border-radius:99px;background:var(--border);color:var(--muted)}

  .log-section{background:var(--card);border:1px solid var(--border);border-radius:12px;padding:1.2rem 1.4rem}
  .log-section h2{font-family:"Syne",sans-serif;font-size:1rem;font-weight:700;color:var(--muted);letter-spacing:.1em;text-transform:uppercase;margin-bottom:.8rem}
  #log-box{height:160px;overflow-y:auto;font-size:.7rem;line-height:1.8;color:var(--muted)}
  .le{border-bottom:1px solid var(--border);padding:.1rem 0}
  .le .ts{color:var(--accent);margin-right:.5rem}
  .btn-outline{background:transparent;color:var(--accent);border:1px solid var(--accent)}
  .btn-outline:hover{background:rgba(0,255,136,.1)}
  @media(max-width:700px){.form-row{grid-template-columns:1fr 1fr}.stats-grid{grid-template-columns:repeat(3,1fr)}.persist-row{flex-direction:column;gap:1rem}}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <div class="logo">Mini<span>Search</span></div>
    <small style="color:var(--muted);font-size:.75rem">ITU · AI Aided Computer Engineering</small>
    <div class="hdot" id="main-dot"></div>
  </header>

  <div id="start-section">
    <h2>&#9889; Tarama Başlat</h2>
    <div class="form-row">
      <div><label>Seed URL</label><input type="text" id="seed-url" value="https://python.org" placeholder="https://..."></div>
      <div><label>Derinlik</label><input type="number" id="depth" value="2" min="1" max="5" style="width:80px"></div>
      <div><label>Workers</label><input type="number" id="workers" value="5" min="1" max="20" style="width:80px"></div>
      <div><label>Rate/s</label><input type="number" id="rate" value="2" min="0.5" max="10" step="0.5" style="width:80px"></div>
      <div><label>Max Kuyruk</label><input type="number" id="queue-size" value="500" min="100" max="5000" step="100" style="width:90px"></div>
      <div><label>Max URL</label><input type="number" id="max-urls" value="200" min="0" max="10000" step="50" style="width:90px" title="0=sınırsız"></div>
      <div style="display:flex;gap:.5rem;align-items:flex-end">
        <button class="btn btn-primary" onclick="startCrawl()">&#9654; Başlat</button>
        <button class="btn btn-danger" onclick="clearAll()" title="Tüm crawler'ları durdur ve temizle">&#10006; Temizle</button>
      </div>
    </div>
    <div id="persist-status" style="font-size:.75rem;color:var(--muted);margin-top:.8rem"></div>
  </div>

  <div id="crawlers-list"></div>

  <div class="search-section">
    <h2>&#128269; Arama <span style="font-size:.75rem;color:var(--muted);font-weight:400">(tüm crawler'larda)</span></h2>
    <div class="search-row">
      <input type="text" id="query" placeholder="Arama sorgusu gir..." onkeydown="if(event.key==='Enter')doSearch()">
      <button class="btn btn-primary" onclick="doSearch()">Ara</button>
    </div>
    <div id="results"></div>
  </div>

  <div class="log-section">
    <h2>// Log</h2>
    <div id="log-box"></div>
  </div>
</div>

<script>
  let seq = 0;
  const stoppedIds = new Set(); // manuel durdurulanlar
  let sse = null;

  function log(msg, color) {
    const box = document.getElementById("log-box");
    const ts = new Date().toLocaleTimeString("tr-TR");
    const el = document.createElement("div");
    el.className = "le";
    el.innerHTML = `<span class="ts">${ts}</span><span style="color:${color||"inherit"}">${msg}</span>`;
    box.prepend(el);
    if (box.children.length > 100) box.lastChild.remove();
  }



  function setCardState(cid, state) {
    const card      = document.getElementById("ci-"+cid);
    const dot       = document.getElementById("cdot-"+cid);
    const lbl       = document.getElementById("clbl-"+cid);
    const stopBtn   = document.getElementById("stop-btn-"+cid);
    const resumeBtn = document.getElementById("resume-btn-"+cid);
    if (!card) return;

    card.className = "ci " + (state === "running" ? "running" : "stopped");
    dot.className  = "cdot " + state;

    if (state === "running") {
      lbl.textContent = "● Çalışıyor"; lbl.className = "ci-state running";
      if (stopBtn)   stopBtn.style.display   = "inline-block";
      if (resumeBtn) resumeBtn.style.display = "none";
    } else if (state === "done") {
      lbl.textContent = "✓ Tamamlandı"; lbl.className = "ci-state done";
      if (stopBtn)   stopBtn.style.display   = "none";
      if (resumeBtn) resumeBtn.style.display = "none";
    } else {
      lbl.textContent = "■ Durduruldu"; lbl.className = "ci-state stopped";
      if (stopBtn)   stopBtn.style.display   = "none";
      if (resumeBtn) resumeBtn.style.display = "inline-block";
    }
  }

  function addCard(cid, url) {
    const list = document.getElementById("crawlers-list");
    if (!document.getElementById("cl-title")) {
      const h = document.createElement("div");
      h.id = "cl-title"; h.className = "cl-title";
      h.textContent = "// Aktif Crawler'lar";
      list.appendChild(h);
    }
    const el = document.createElement("div");
    el.className = "ci running";
    el.id = "ci-"+cid;
    el.innerHTML = `
      <div class="ci-header">
        <span class="ci-badge">#${cid}</span>
        <span class="ci-url">${url}</span>
        <div class="cdot running" id="cdot-${cid}"></div>
        <span class="ci-state running" id="clbl-${cid}">● Çalışıyor</span>
        <button class="btn btn-danger btn-sm" id="tbtn-${cid}" onclick="openDetail('${cid}')">▼ Detay</button>
        <button class="btn btn-danger btn-sm" id="stop-btn-${cid}" onclick="stopCrawler('${cid}')">■ Durdur</button>
        <button class="btn btn-primary btn-sm" id="resume-btn-${cid}" style="display:none" onclick="resumeCrawler('${cid}')">▶ Devam</button>
      </div>
      <div class="stats-grid">
        <div class="stat-card"><div class="stat-label">İşlenen</div><div class="stat-value c-green" id="vp-${cid}">0</div></div>
        <div class="stat-card"><div class="stat-label">Kuyruk</div><div class="stat-value c-blue" id="vq-${cid}">0</div></div>
        <div class="stat-card"><div class="stat-label">Ziyaret</div><div class="stat-value c-yellow" id="vv-${cid}">0</div></div>
        <div class="stat-card"><div class="stat-label">Hata</div><div class="stat-value c-orange" id="ve-${cid}">0</div></div>
        <div class="stat-card"><div class="stat-label">İndeks</div><div class="stat-value c-gray" id="vi-${cid}">0</div></div>
      </div>
      <div style="margin-top:.6rem">
        <div class="bar-wrap">
          <div class="bar-hdr"><span>Kuyruk / Back-pressure</span><span id="thr-${cid}" style="color:var(--accent)">—</span></div>
          <div class="bar-track"><div class="bar-fill" id="qbar-${cid}"></div></div>
        </div>
        <div class="bar-wrap">
          <div class="bar-hdr"><span>URL Limiti</span><span id="ulbl-${cid}" style="color:var(--accent2)">—</span></div>
          <div class="bar-track"><div class="bar-fill url" id="ubar-${cid}"></div></div>
        </div>
      </div>`;
    const title = document.getElementById("cl-title");
    list.insertBefore(el, title.nextSibling);
  }

  async function startCrawl() {
    const url      = document.getElementById("seed-url").value.trim();
    const depth    = +document.getElementById("depth").value;
    const workers  = +document.getElementById("workers").value;
    const rate     = +document.getElementById("rate").value;
    const qsize    = +document.getElementById("queue-size").value;
    const max_urls = +document.getElementById("max-urls").value;
    if (!url) { alert("URL gerekli!"); return; }

    seq++;
    const cid = String(seq);
    addCard(cid, url);
    document.getElementById("main-dot").className = "hdot running";
    log(`[#${cid}] Başlatılıyor: ${url}`, "var(--accent)");

    const r = await fetch("/start", {
      method:"POST", headers:{"Content-Type":"application/json"},
      body: JSON.stringify({url, depth, workers, rate, queue_size:qsize, max_urls, crawler_id:cid, mode:"fresh"})
    });
    const d = await r.json();
    if (d.status !== "started") {
      log(`[#${cid}] Başlatılamadı!`, "var(--warn)");
      setCardState(cid, "stopped");
    } else {
      const st = document.getElementById("persist-status");
      if (d.mode === "resume") {
        // Devam: sayaçları restore et
        document.getElementById("vv-"+cid).textContent = d.resumed_count;
        document.getElementById("vi-"+cid).textContent = d.resumed_index;
        document.getElementById("vp-"+cid).textContent = d.resumed_index;
        st.innerHTML = `&#9654; <span style="color:var(--accent2)">${d.save_path}</span> — ${d.resumed_count} URL atlandı, devam ediliyor`;
        log(`[#${cid}] ▶ Devam: ${d.resumed_count} eski URL atlanıyor, ${d.resumed_index} sayfa indekste`, "var(--accent2)");
      } else if (d.resumed_index > 0) {
        // Fresh ama önceki indeks var: sayaçlar 0, ama arama çalışır
        st.innerHTML = `&#128260; <span style="color:var(--accent)">${d.save_path}</span> — ${d.resumed_index} eski sayfa indekste, ${document.getElementById("max-urls").value} yeni URL taranacak`;
        log(`[#${cid}] ↺ Yeni tarama: ${d.resumed_index} eski sayfa indekste kaldı, yeniden tarıyor`, "var(--accent)");
      } else {
        // Sıfırdan
        st.innerHTML = `&#128190; <span style="color:var(--muted)">${d.save_path}</span> — ilk tarama`;
        log(`[#${cid}] ◉ İlk tarama başladı`, "var(--muted)");
      }
    }
  }

  async function stopCrawler(cid) {
    stoppedIds.add(cid); // SSE'nin tekrar "running" yapmasını engelle
    setCardState(cid, "stopped");
    log(`[#${cid}] Durduruldu.`, "var(--warn)");
    await fetch("/stop", {
      method:"POST", headers:{"Content-Type":"application/json"},
      body: JSON.stringify({crawler_id: cid})
    });
  }

  async function resumeCrawler(cid) {
    stoppedIds.delete(cid);
    setCardState(cid, "running");

    const r = await fetch("/resume", {
      method:"POST", headers:{"Content-Type":"application/json"},
      body: JSON.stringify({crawler_id: cid})
    });
    const d = await r.json();
    if (d.status === "resumed") {
      // Sayaçları restore et
      document.getElementById("vp-"+cid).textContent = d.processed;
      document.getElementById("vi-"+cid).textContent = d.index_size;
      document.getElementById("vv-"+cid).textContent = d.visited;
      log(`[#${cid}] ▶ Devam: ${d.visited} visited korundu, ${d.queue_size} URL kuyrukta, ${d.index_size} indekste`, "var(--accent2)");
    } else if (d.status === "already_running") {
      log(`[#${cid}] Zaten çalışıyor`, "var(--muted)");
    } else {
      log(`[#${cid}] Resume hatası: ${d.error||d.status}`, "var(--warn)");
      setCardState(cid, "stopped");
    }
  }

  async function clearAll() {
    if (!confirm("Tüm crawler'lar durdurulacak, storage dosyaları silinecek. Emin misin?")) return;
    const r = await fetch("/clear", {method:"POST"});
    const d = await r.json();
    // UI temizle
    document.getElementById("crawlers-list").innerHTML = "";
    stoppedIds.clear();
    seq = 0;
    document.getElementById("main-dot").className = "hdot";
    document.getElementById("persist-status").innerHTML = "";
    document.getElementById("results").innerHTML = "";
    log(`Temizlendi: ${d.deleted_files} dosya silindi.`, "var(--warn)");
  }

  function startSSE() {
    if (sse) sse.close();
    sse = new EventSource("/stream");
    sse.onmessage = (e) => {
      const data = JSON.parse(e.data);
      let anyRunning = false;

      for (const c of data.crawlers) {
        const cid = c.crawler_id;
        if (!document.getElementById("ci-"+cid)) continue;

        // Manuel durdurulmuşsa SSE güncellemelerini yoksay
        if (stoppedIds.has(cid)) continue;

        document.getElementById("vp-"+cid).textContent = c.processed;
        document.getElementById("vq-"+cid).textContent = c.queued;
        document.getElementById("vv-"+cid).textContent = c.visited;
        document.getElementById("ve-"+cid).textContent = c.errors;
        document.getElementById("vi-"+cid).textContent = c.index_size;

        const qbar = document.getElementById("qbar-"+cid);
        if (qbar) {
          const pct = Math.min(100,(c.queued/c.max_queue_size)*100);
          qbar.style.width = pct+"%";
          qbar.className = "bar-fill"+(c.throttled?" hot":"");
          const thr = document.getElementById("thr-"+cid);
          thr.textContent = c.throttled ? "⚠ THROTTLED" : "✓ Normal";
          thr.style.color = c.throttled ? "var(--warn)" : "var(--accent)";
        }
        const ubar = document.getElementById("ubar-"+cid);
        if (ubar) {
          if (c.max_urls > 0) {
            ubar.style.width = Math.min(100,(c.visited/c.max_urls)*100)+"%";
            document.getElementById("ulbl-"+cid).textContent = c.visited+" / "+c.max_urls;
          } else {
            document.getElementById("ulbl-"+cid).textContent = c.visited+" (sınırsız)";
          }
        }

        if (c.running) {
          anyRunning = true;
          setCardState(cid, "running");
        } else {
          // Crawler kendi kendine bitti (max_urls veya kuyruk bitti)
          setCardState(cid, "done");
          log(`[#${cid}] Tamamlandı — ${c.processed} sayfa, ${c.index_size} indeks.`, "var(--accent2)");
          stoppedIds.add(cid); // bir daha işleme
        }
      }
      document.getElementById("main-dot").className = "hdot "+(anyRunning?"running":"done");
    };
  }

  async function doSearch() {
    const q = document.getElementById("query").value.trim();
    if (!q) return;
    const res = await fetch("/search",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({query:q})});
    const data = await res.json();
    const box = document.getElementById("results");
    if (!data.results||data.results.length===0){box.innerHTML="<div class='no-result'>Sonuç bulunamadı.</div>";return;}
    const total = data.total || data.results.length;
    box.innerHTML = `<div style="font-size:.72rem;color:var(--muted);margin-bottom:.8rem">
      ${total} sonuç bulundu ${total > 15 ? "(ilk 15 gösteriliyor)" : ""}
    </div>` + data.results.slice(0,15).map(r=>`
      <div class="ri">
        ${r.title ? `<div class="ri-title">${r.title}</div>` : ""}
        <a class="ri-url" href="${r.url}" target="_blank" rel="noopener">${r.url}</a>
        <div class="ri-meta">
          <span>Derinlik: ${r.depth}</span>
          <span class="badge">skor: ${Number(r.score).toFixed(2)}</span>
          ${r.in_url   ? '<span class="badge" style="background:rgba(255,200,0,.15);color:#ffd700;border-color:rgba(255,200,0,.3)">URL de</span>' : ""}
          ${r.in_title ? '<span class="badge" style="background:rgba(0,255,136,.15)">başlıkta</span>' : ""}
          ${r.matched_tokens > 1 ? `<span class="badge badge2">${r.matched_tokens} token</span>` : ""}
          <span class="badge badge2">crawler #${r.crawler_id||"?"}</span>
        </div>
      </div>`).join("");
    log(`Arama: "${q}" → ${total} sonuç`,"var(--accent2)");
  }

  startSSE();
</script>

<!-- Detay Modalı -->
<div class="modal-overlay" id="detail-modal" onclick="if(event.target===this)closeModal()">
  <div class="modal">
    <div class="modal-header">
      <h3 id="modal-title">Crawler Detayı</h3>
      <span class="stat-pill" id="modal-stat"></span>
      <button class="btn btn-danger btn-sm" onclick="closeModal()">&#10005; Kapat</button>
    </div>
    <div class="modal-tabs">
      <button class="tab-btn active" id="tab-logs"    onclick="switchTab(event,'logs')">&#128203; Log</button>
      <button class="tab-btn"        id="tab-queue"   onclick="switchTab(event,'queue')">&#9203; Kuyruk</button>
      <button class="tab-btn"        id="tab-visited" onclick="switchTab(event,'visited')">&#10003; Ziyaret</button>
    </div>
    <div class="modal-body" id="modal-body">
      <div style="color:var(--muted);font-size:.8rem;padding:1rem">Yükleniyor...</div>
    </div>
  </div>
</div>

<script>
  let _modalCid = null;
  let _modalTab = "logs";
  let _modalInterval = null;

  function openDetail(cid) {
    _modalCid = cid;
    const el = document.getElementById("ci-"+cid);
    if (!el) return;
    const url = el.querySelector(".ci-url").textContent.trim();
    document.getElementById("modal-title").textContent = "#"+cid+" — "+url;
    document.getElementById("detail-modal").classList.add("open");
    // Aktif tab'ı sıfırla
    document.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("active"));
    document.getElementById("tab-logs").classList.add("active");
    _modalTab = "logs";
    loadTab("logs");
    if (_modalInterval) clearInterval(_modalInterval);
    _modalInterval = setInterval(() => loadTab(_modalTab), 2000);
  }

  function closeModal() {
    document.getElementById("detail-modal").classList.remove("open");
    if (_modalInterval) { clearInterval(_modalInterval); _modalInterval = null; }
    _modalCid = null;
  }

  function switchTab(ev, tab) {
    _modalTab = tab;
    document.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("active"));
    ev.target.classList.add("active");
    loadTab(tab);
  }

  async function loadTab(tab) {
    if (!_modalCid) return;
    const body = document.getElementById("modal-body");
    const stat = document.getElementById("modal-stat");

    if (tab === "logs") {
      const r = await fetch(`/crawler/${_modalCid}/logs?n=200`);
      const d = await r.json();
      stat.textContent = d.logs.length + " kayıt";
      if (!d.logs.length) { body.innerHTML = "<div style='color:var(--muted);font-size:.8rem;padding:.5rem'>Henüz log yok</div>"; return; }
      body.innerHTML = d.logs.map(l => `
        <div class="log-line">
          <span style="color:var(--muted)">${l.ts}</span>
          <span class="ev-${l.event}">${l.event}</span>
          <a href="${l.url}" target="_blank" rel="noopener">${l.url}</a>
          <span style="color:var(--warn);font-size:.65rem">${l.error||""}</span>
        </div>`).join("");

    } else if (tab === "queue") {
      const r = await fetch(`/crawler/${_modalCid}/queue`);
      const d = await r.json();
      stat.textContent = d.size + " bekliyor";
      if (!d.queue.length) { body.innerHTML = "<div style='color:var(--muted);font-size:.8rem;padding:.5rem'>Kuyruk boş</div>"; return; }
      body.innerHTML = d.queue.map(q => `
        <div class="q-line">
          <span style="color:var(--muted);margin-right:.5rem">d${q.depth}</span>
          <a href="${q.url}" target="_blank" rel="noopener">${q.url}</a>
        </div>`).join("");

    } else if (tab === "visited") {
      const r = await fetch(`/crawler/${_modalCid}/visited?n=500`);
      const d = await r.json();
      stat.textContent = d.size + " URL";
      if (!d.visited.length) { body.innerHTML = "<div style='color:var(--muted);font-size:.8rem;padding:.5rem'>Henüz ziyaret yok</div>"; return; }
      body.innerHTML = d.visited.map(u => `
        <div class="v-line">
          <a href="${u}" target="_blank" rel="noopener">${u}</a>
        </div>`).join("");
    }
  }
</script>
</body>
</html>"""



# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.route("/")
def index():
    return render_template_string(HTML)


@app.route("/start", methods=["POST"])
def start_crawl():
    data = request.get_json()
    cid  = str(data.get("crawler_id", "1"))
    url  = data["url"]
    mode = data.get("mode", "fresh")

    import re, os
    domain = re.sub(r"[^a-z0-9]", "_", url.lower().split("//")[-1].split("/")[0])

    # Storage klasörü (absolute path — VSCode farklı cwd'den çalışabilir)
    _base = os.path.dirname(os.path.abspath(__file__))
    storage_dir = os.path.join(_base, "storage", "crawlers", cid)
    os.makedirs(storage_dir, exist_ok=True)

    save_path  = os.path.join(storage_dir, "index.json")
    state_path = os.path.join(storage_dir, "state.json")
    log_path   = os.path.join(storage_dir, "logs.jsonl")

    # Fresh modda logu sıfırla
    if mode == "fresh" and os.path.exists(log_path):
        open(log_path, "w").close()

    with crawlers_lock:
        if cid in crawlers and crawlers[cid].stats.running:
            crawlers[cid].stop()
            time.sleep(0.5)

        import urllib.parse as _up
        domain_key = _up.urlparse(url).netloc

        # Shared visited mantığı:
        # - Aynı anda çalışan crawlerlar aynı in-memory set'i paylaşır
        # - Fresh başlarken: önce diskten yükle (önceki taramalar korunur)
        c = Crawler(
            seed_url=url,
            crawler_id=cid,
            max_depth=int(data.get("depth", 2)),
            max_workers=int(data.get("workers", 5)),
            rate_limit=float(data.get("rate", 2.0)),
            max_queue_size=int(data.get("queue_size", 500)),
            max_urls=int(data.get("max_urls", 0)),
            same_domain_only=True,
            save_path=save_path,
            state_path=state_path,
            log_path=log_path,
            on_finish=save_pdata,
        )

        resumed_index = 0

        if mode == "resume" and os.path.exists(save_path):
            # DEVAM: indeks yükle, state'ten visited+frontier al
            try:
                c.index.load(save_path)
                resumed_index = c.index.page_count()
                with c._stats_lock:
                    c.stats.processed = resumed_index

                if os.path.exists(state_path):
                    visited_r, frontier_r, _ = InvertedIndex.load_state(state_path)
                    with c._visited_lock:
                        c._visited = visited_r
                    for item in frontier_r:
                        try: c._url_queue.put_nowait(item)
                        except: break
                    log.info(f"RESUME #{cid}: {len(visited_r)} visited, {c._url_queue.qsize()} frontier")
            except Exception as e:
                log.warning(f"Resume yukleme hatasi: {e}")

        elif os.path.exists(save_path):
            # FRESH ama önceki indeks var: sadece indeksi yükle, visited sıfır
            try:
                c.index.load(save_path)
                resumed_index = c.index.page_count()
                log.info(f"FRESH #{cid}: {resumed_index} eski sayfa indekste, sıfırdan tarıyor")
            except Exception as e:
                log.warning(f"Indeks yuklenemedi: {e}")

        crawlers[cid] = c
        c.start()

    return jsonify({
        "status":        "started",
        "crawler_id":    cid,
        "save_path":     save_path,
        "mode":          mode,
        "resumed_count": len(c._visited),
        "resumed_index": resumed_index,
    })

@app.route("/load", methods=["POST"])
def load_index():
    """Önceden kaydedilmiş indeksi yükler, tarama olmadan arama yapılabilir."""
    import os
    data = request.get_json()
    path = data.get("path", "").strip()

    if not path:
        return jsonify({"status": "error", "error": "Dosya adı boş"})
    if not os.path.exists(path):
        return jsonify({"status": "error", "error": f"Dosya bulunamadı: {path}"})

    try:
        # Özel bir "loaded" crawler oluştur - sadece indeks taşır, tarama yapmaz
        cid = "loaded"
        from crawler import InvertedIndex
        idx = InvertedIndex()
        idx.load(path)
        page_count = idx.page_count()

        # Dummy crawler - sadece indeks için
        with crawlers_lock:
            if cid not in crawlers:
                c = Crawler(seed_url="loaded://", crawler_id=cid,
                            max_depth=0, max_workers=0)
                c.index = idx
                c.stats.running = False
                crawlers[cid] = c
            else:
                crawlers[cid].index = idx

        return jsonify({"status": "ok", "message": f"{page_count} sayfa yüklendi ({path})"})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)})


@app.route("/resume", methods=["POST"])
def resume_crawl():
    """Mevcut crawler nesnesini sıfırlamadan devam ettirir."""
    data = request.get_json() or {}
    cid  = str(data.get("crawler_id", "1"))

    with crawlers_lock:
        if cid not in crawlers:
            return jsonify({"status": "error", "error": "Crawler bulunamadı"})
        c = crawlers[cid]
        if c.stats.running:
            return jsonify({"status": "already_running"})

        # Sunucu yeniden başlatılmışsa indeks bellekte yok — diskten yükle
        if c.index.page_count() == 0 and c.save_path and os.path.exists(c.save_path):
            try:
                c.index.load(c.save_path)
                with c._stats_lock:
                    c.stats.processed = c.index.page_count()
                log.info(f"RESUME #{cid}: indeks diskten yüklendi ({c.index.page_count()} sayfa)")
            except Exception as e:
                log.warning(f"Indeks yuklenemedi: {e}")

        c.resume()  # frontier state.json'dan yüklenir

    return jsonify({
        "status":     "resumed",
        "crawler_id": cid,
        "index_size": c.index.page_count(),
        "processed":  c.stats.processed,
        "visited":    len(c._visited),
        "queue_size": c._url_queue.qsize(),
    })


@app.route("/stop", methods=["POST"])
def stop_crawl():
    data = request.get_json() or {}
    cid = str(data.get("crawler_id", "1"))
    def do_stop():
        with crawlers_lock:
            if cid in crawlers:
                c = crawlers[cid]
                c.stop()
        save_pdata()

    threading.Thread(target=do_stop, daemon=True).start()
    return jsonify({"status": "stopping", "crawler_id": cid})


@app.route("/search", methods=["POST"])
def search():
    data  = request.get_json()
    query = data.get("query", "").strip()
    cid   = data.get("crawler_id")

    with crawlers_lock:
        targets = list(crawlers.values()) if not cid else [crawlers.get(str(cid))]
        targets = [c for c in targets if c]

    if not targets or not query:
        return jsonify({"results": [], "total": 0})

    combined: dict[str, dict] = {}

    # URL araması: https:// ile başlıyorsa direkt URL eşleştir
    if query.startswith("http://") or query.startswith("https://"):
        for c in targets:
            with c.index._lock:
                for page in c.index._pages:
                    if query in page.url:
                        combined[page.url] = {
                            "url":        page.url,
                            "origin_url": page.origin_url,
                            "depth":      page.depth,
                            "title":      page.title,
                            "score":      100 if page.url == query else 50,
                            "in_title":   False,
                            "in_url":     True,
                            "crawler_id": c.crawler_id,
                        }
    else:
        # Normal kelime araması
        for c in targets:
            for r in c.search(query):
                url = r["url"]
                if url not in combined or r["score"] > combined[url]["score"]:
                    combined[url] = r
                    combined[url]["crawler_id"] = c.crawler_id

    results = sorted(combined.values(), key=lambda x: x["score"], reverse=True)
    return jsonify({"results": results[:20], "total": len(results)})


@app.route("/search", methods=["GET"])
def search_get():
    """Quiz GET endpoint: /search?query=<word>&sortBy=relevance"""
    query   = request.args.get("query", "").strip()
    sort_by = request.args.get("sortBy", "relevance")  # noqa: F841 (future use)

    with crawlers_lock:
        targets = list(crawlers.values())

    # Aktif crawler yoksa disk'ten yükle
    if not targets:
        from crawler import InvertedIndex
        import glob as _glob
        tmp = InvertedIndex()
        for idx_path in _glob.glob("storage/crawlers/*/index.json"):
            try:
                tmp.load(idx_path)
            except Exception:
                pass
        targets = [type("_C", (), {"search": lambda self, q: tmp.search(q), "crawler_id": "disk"})()]

    if not query or not targets:
        return jsonify({"results": [], "total": 0})

    combined: dict[str, dict] = {}
    for c in targets:
        for r in c.search(query):
            url = r["url"]
            if url not in combined or r.get("relevance_score", 0) > combined[url].get("relevance_score", 0):
                combined[url] = r
                combined[url]["crawler_id"] = getattr(c, "crawler_id", "?")

    results = sorted(combined.values(), key=lambda x: x.get("relevance_score", 0), reverse=True)
    return jsonify({"results": results[:20], "total": len(results)})


@app.route("/stream")
def stream():
    """Server-Sent Events — her saniye tum crawler metriklerini gonderir."""
    def generate():
        while True:
            with crawlers_lock:
                all_crawlers = list(crawlers.values())

            stats_list = []
            for c in all_crawlers:
                s = c.get_stats()
                stats_list.append({
                    "crawler_id":     c.crawler_id,
                    "processed":      s.processed,
                    "queued":         s.queued,
                    "errors":         s.errors,
                    "visited":        s.visited,
                    "index_size":     c.index.page_count(),
                    "throttled":      s.throttled,
                    "running":        s.running,
                    "max_queue_size": c._url_queue.maxsize,
                    "max_urls":       c.max_urls,
                })

            payload = json.dumps({"crawlers": stats_list})
            yield f"data: {payload}\n\n"
            time.sleep(1)

    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.route("/crawler/<cid>/logs")
def get_logs(cid):
    """Son N log satırını döndür."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "storage", "crawlers", cid, "logs.jsonl")
    import os, json as _json
    if not os.path.exists(path):
        return jsonify({"logs": []})
    n = int(request.args.get("n", 100))
    with open(path, "r", encoding="utf-8") as f:
        lines = f.readlines()
    logs = []
    for line in lines[-n:]:
        try: logs.append(_json.loads(line))
        except: pass
    return jsonify({"logs": list(reversed(logs))})


@app.route("/crawler/<cid>/queue")
def get_queue(cid):
    """Kuyrukta bekleyen URL'leri döndür."""
    with crawlers_lock:
        c = crawlers.get(cid)
    if not c:
        return jsonify({"queue": [], "size": 0})
    items = list(c._url_queue.queue)  # kuyruğu kopyala
    return jsonify({
        "queue": [{"url": i[0], "origin": i[1], "depth": i[2]} for i in items[:200]],
        "size":  len(items)
    })


@app.route("/crawler/<cid>/visited")
def get_visited(cid):
    """Ziyaret edilen URL'leri döndür."""
    with crawlers_lock:
        c = crawlers.get(cid)
    if not c:
        return jsonify({"visited": [], "size": 0})
    with c._visited_lock:
        visited = sorted(c._visited)
    n = int(request.args.get("n", 500))
    return jsonify({"visited": visited[:n], "size": len(visited)})


@app.route("/shared/visited")
def get_shared_visited():
    """Tüm crawler'ların visited URL'lerini domain bazında gösterir."""
    result = {}
    with crawlers_lock:
        for cid2, c in crawlers.items():
            import urllib.parse as _up2
            domain = _up2.urlparse(c.seed_url).netloc
            with c._visited_lock:
                urls = sorted(c._visited)
            if domain not in result:
                result[domain] = {"size": 0, "urls": [], "crawlers": []}
            result[domain]["crawlers"].append(cid2)
            # Unique URL'leri birleştir
            existing = set(result[domain]["urls"])
            for u in urls:
                if u not in existing:
                    result[domain]["urls"].append(u)
                    existing.add(u)
            result[domain]["size"] = len(result[domain]["urls"])
    return jsonify(result)


@app.route("/clear", methods=["POST"])
def clear_all():
    """Tüm crawler'ları durdur, storage'ı temizle, shared visited sıfırla."""
    import shutil, os

    # Tüm crawler'ları durdur
    with crawlers_lock:
        for c in list(crawlers.values()):
            if c.stats.running:
                c._stop_event.set()
                c.stats.running = False
        crawlers.clear()

    # Storage dosyalarını sil
    deleted = 0
    _base = os.path.dirname(os.path.abspath(__file__))
    for subdir in [os.path.join(_base, "storage", "crawlers"), os.path.join(_base, "storage", "shared")]:
        if os.path.exists(subdir):
            for entry in os.scandir(subdir):
                if entry.is_dir():
                    shutil.rmtree(entry.path)
                    deleted += 1
                elif entry.name.endswith(".json"):
                    os.remove(entry.path)
                    deleted += 1
    log.info(f"Storage temizlendi: {deleted} dosya/klasör silindi")

    return jsonify({"status": "cleared", "deleted_files": deleted})


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("\n  MiniSearch Web Dashboard")
    print("  → http://localhost:3600\n")
    app.run(debug=False, threaded=True, port=3600)