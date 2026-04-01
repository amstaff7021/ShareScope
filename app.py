from __future__ import annotations

import http.client
import json
import mimetypes
import secrets
import sys
import threading
import webbrowser
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright
from PySide6.QtCore import QObject, QTimer, QUrl, Qt, Signal, Slot
from PySide6.QtGui import QGuiApplication
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QApplication, QFileDialog, QVBoxLayout, QWidget

APP_DIR = Path(__file__).resolve().parent
STATE_FILE = APP_DIR / 'sharescope_state.json'
TRANSFER_URL = 'https://transfer.it/start'
BROWSER_CANDIDATES = (
    Path(r'C:\Program Files\Google\Chrome\Application\chrome.exe'),
    Path(r'C:\Program Files (x86)\Google\Chrome\Application\chrome.exe'),
    Path(r'C:\Program Files\Microsoft\Edge\Application\msedge.exe'),
    Path(r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'),
)
DEFAULT_EXPIRY_DAYS = 90
CATBOX_MAX_BYTES = 200 * 1024 * 1024
DIRECT_PREVIEW_EXTENSIONS = {
    '.aac', '.apng', '.avif', '.flac', '.gif', '.jpeg', '.jpg', '.m4a', '.m4v',
    '.mov', '.mp3', '.mp4', '.ogg', '.png', '.wav', '.webm', '.webp',
}

HTML = r"""<!doctype html>
<html lang="fr">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>ShareScope</title>
  <script src="qrc:///qtwebchannel/qwebchannel.js"></script>
  <style>
    :root {
      --bg: #03070d;
      --panel: rgba(7, 18, 32, 0.96);
      --line: rgba(86, 177, 255, 0.22);
      --line-strong: rgba(86, 177, 255, 0.84);
      --text: #dbeeff;
      --muted: #8aa3bc;
      --blue: #7acbff;
      --blue-2: #b2ebff;
      --danger: #ff9daf;
      --ok: #8df0c6;
      --shadow: 0 18px 60px rgba(0, 0, 0, 0.45);
    }
    * { box-sizing: border-box; }
    html, body { margin: 0; min-height: 100%; background: var(--bg); color: var(--text); font-family: "Space Mono", Consolas, monospace; }
    body {
      background:
        radial-gradient(circle at 14% 16%, rgba(88, 194, 255, 0.12), transparent 18%),
        radial-gradient(circle at 82% 14%, rgba(47, 129, 255, 0.1), transparent 16%),
        linear-gradient(180deg, #02070d, #07111d 52%, #02070d);
      overflow: auto;
    }
    .shell { width: min(470px, calc(100% - 10px)); margin: 0 auto; padding: 8px 0; min-height: 100vh; display: flex; align-items: flex-start; }
    .hud { width: 100%; border: 1px solid rgba(86, 177, 255, 0.3); background: linear-gradient(180deg, rgba(5, 13, 24, 0.98), rgba(3, 9, 16, 0.98)); box-shadow: var(--shadow); }
    .head { display: flex; align-items: center; gap: 7px; padding: 9px 12px; border-bottom: 1px solid rgba(86, 177, 255, 0.16); background: rgba(8, 20, 34, 0.94); }
    .window-actions { display: flex; gap: 8px; align-items: center; }
    .window-dot {
      width: 12px;
      height: 12px;
      border: none;
      border-radius: 50%;
      padding: 0;
      min-height: 12px;
      cursor: pointer;
      box-shadow: inset 0 0 0 1px rgba(255,255,255,0.08);
    }
    .window-dot:hover { filter: brightness(1.15); background-image: none; }
    .window-dot.close { background: rgba(255, 126, 148, 0.95); }
    .window-dot.min { background: rgba(255, 215, 112, 0.95); }
    .window-dot.refresh { background: rgba(108, 199, 255, 0.95); }
    .title { margin-left: 10px; color: var(--muted); font-size: .78rem; }
    .body { padding: 10px; display: flex; flex-direction: column; gap: 10px; }
    .card, .history, .status { border: 1px solid var(--line); background: var(--panel); box-shadow: var(--shadow); }
    .card { padding: 12px; }
    .brand { margin: 0; font-size: 1.1rem; line-height: 1; }
    .mini { color: var(--muted); font-size: .78rem; line-height: 1.55; }
    .status {
      position: relative;
      padding: 8px 10px 12px;
      display: flex;
      gap: 8px;
      align-items: center;
      flex-wrap: wrap;
      overflow: hidden;
    }
    .pill { min-height: 28px; display: inline-flex; align-items: center; padding: 0 9px; border: 1px solid var(--line); color: var(--blue-2); background: rgba(10, 24, 42, 0.82); font-size: .78rem; }
    .pill.ok { color: var(--ok); }
    .status-text { color: var(--muted); font-size: .76rem; flex: 1; min-width: 120px; }
    .progress-strip {
      position: absolute;
      left: 10px;
      right: 10px;
      bottom: 5px;
      height: 4px;
      border-radius: 999px;
      background: rgba(86, 177, 255, 0.12);
      opacity: 0;
      transition: opacity .14s ease;
      pointer-events: none;
    }
    .progress-strip.active { opacity: 1; }
    .progress-fill {
      width: 0%;
      height: 100%;
      border-radius: inherit;
      background: linear-gradient(90deg, rgba(88, 194, 255, 0.75), rgba(178, 235, 255, 0.96));
      box-shadow: 0 0 12px rgba(122, 203, 255, 0.34);
      transition: width .12s linear;
    }
    .drop-zone {
      border: 1px dashed rgba(86, 177, 255, 0.58);
      background: rgba(8, 20, 36, 0.82);
      min-height: 140px;
      display: flex;
      align-items: center;
      justify-content: center;
      text-align: center;
      padding: 18px;
      font-size: .92rem;
      line-height: 1.7;
    }
    .drop-zone.dragover { background: rgba(47, 129, 255, 0.18); border-color: rgba(143, 224, 255, 0.92); }
    .row { display: flex; gap: 8px; flex-wrap: wrap; }
    button {
      min-height: 34px; padding: 0 11px; color: var(--blue); background: transparent; border: 1px solid var(--line-strong);
      cursor: pointer; text-transform: uppercase; letter-spacing: .05em; font: inherit; font-size: .78rem;
    }
    button:hover { background: rgba(88, 194, 255, 0.12); }
    button.primary { background: rgba(47, 129, 255, 0.16); color: var(--blue-2); }
    button.danger { border-color: rgba(255, 157, 175, 0.48); color: var(--danger); }
    button.slim { min-height: 28px; padding: 0 8px; font-size: .72rem; }
    button:disabled { opacity: .42; cursor: not-allowed; }
    .history { min-height: 190px; max-height: 290px; overflow: auto; }
    .history-head { display: flex; justify-content: space-between; align-items: center; padding: 10px 12px; border-bottom: 1px solid rgba(56, 146, 255, 0.12); }
    .history-item { padding: 10px 12px; border-bottom: 1px solid rgba(56, 146, 255, 0.12); }
    .history-item:last-child { border-bottom: none; }
    .tooltip-wrap { position: relative; }
    .tooltip-panel {
      position: absolute;
      left: 0;
      bottom: calc(100% + 8px);
      min-width: 220px;
      max-width: 280px;
      padding: 10px 12px;
      border: 1px solid rgba(86, 177, 255, 0.34);
      background: linear-gradient(180deg, rgba(8, 20, 34, 0.98), rgba(5, 12, 22, 0.98));
      box-shadow: 0 18px 40px rgba(0, 0, 0, 0.42);
      color: var(--text);
      opacity: 0;
      visibility: hidden;
      transform: translateY(4px);
      transition: opacity .12s ease, transform .12s ease, visibility .12s ease;
      pointer-events: none;
      z-index: 20;
    }
    .tooltip-wrap:hover .tooltip-panel {
      opacity: 1;
      visibility: visible;
      transform: translateY(0);
    }
    .tooltip-title {
      color: var(--blue-2);
      font-size: .74rem;
      margin-bottom: 6px;
    }
    .tooltip-line {
      color: var(--muted);
      font-size: .72rem;
      line-height: 1.55;
      white-space: pre-wrap;
    }
    .history-top { display: flex; justify-content: space-between; gap: 10px; align-items: flex-start; }
    .history-name { font-size: .83rem; color: var(--blue-2); word-break: break-word; }
    .history-meta { margin-top: 4px; color: var(--muted); font-size: .72rem; }
    .history-actions { display: flex; gap: 6px; flex-shrink: 0; }
    .empty { padding: 14px 12px; color: var(--muted); font-size: .78rem; }
  </style>
</head>
<body>
  <main class="shell">
    <section class="hud">
      <div id="headBar" class="head">
        <div class="window-actions">
          <button class="window-dot close" title="Close" onclick="closeWindow(event)"></button>
          <button class="window-dot min" title="Minimize" onclick="minimizeWindow(event)"></button>
          <button class="window-dot refresh" title="Refresh" onclick="refreshHud(event)"></button>
        </div>
        <div class="title">root@sharescope:~$ mini_hud</div>
      </div>
      <div class="body">
        <section class="card">
          <h1 class="brand">ShareScope</h1>
          <p class="mini" style="margin:8px 0 0;">Drop a file. Direct media link first, fallback page if needed.</p>
        </section>
        <section class="status">
          <div id="pipelineChip" class="pill">IDLE</div>
          <div id="browserChip" class="pill">READY</div>
          <div id="statusText" class="status-text">Ready.</div>
          <div id="progressStrip" class="progress-strip"><div id="progressFill" class="progress-fill"></div></div>
        </section>
        <section class="card">
          <div id="dropZone" class="drop-zone">Drag and drop files here</div>
          <div class="row" style="margin-top:10px;">
            <button class="primary" onclick="browseFiles()">Browse files</button>
          </div>
        </section>
        <section class="history">
          <div class="history-head">
            <div id="libraryMeta" class="mini">0 file(s)</div>
            <button class="danger slim" onclick="clearHistory()">Clear</button>
          </div>
          <div id="transferList"></div>
        </section>
      </div>
    </section>
  </main>
  <script>
    let currentState = {pipeline: 'IDLE', transfers: []};
    let bridge = null;
    let bridgeReady = false;

    function escapeHtml(value) {
      return String(value ?? '').replace(/[&<>\"']/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',"'":'&#39;'}[c]));
    }

    function formatSize(size) {
      let value = Number(size || 0);
      const units = ['B', 'KB', 'MB', 'GB', 'TB'];
      for (const unit of units) {
        if (value < 1024 || unit === 'TB') {
          return unit === 'B' ? `${Math.round(value)} ${unit}` : `${value.toFixed(1)} ${unit}`;
        }
        value /= 1024;
      }
      return `${Math.round(Number(size || 0))} B`;
    }

    function setStatus(line) {
      document.getElementById('statusText').textContent = line || 'Ready.';
    }

    function callBridge(method, ...args) {
      return new Promise((resolve) => {
        if (!bridgeReady || !bridge || typeof bridge[method] !== 'function') {
          resolve(null);
          return;
        }
        bridge[method](...args, resolve);
      });
    }

    function renderState(state) {
      currentState = state || {pipeline: 'IDLE', transfers: []};
      const percent = Math.max(0, Math.min(100, Number(currentState.progress_percent || 0)));
      document.getElementById('pipelineChip').textContent = currentState.pipeline === 'IDLE' ? 'IDLE' : `UPLOADING ${percent}%`;
      document.getElementById('pipelineChip').className = currentState.pipeline === 'IDLE' ? 'pill' : 'pill ok';
      document.getElementById('browserChip').textContent = currentState.browser_ready ? 'FALLBACK OK' : 'NO FALLBACK';
      document.getElementById('browserChip').className = currentState.browser_ready ? 'pill ok' : 'pill';
      const strip = document.getElementById('progressStrip');
      const fill = document.getElementById('progressFill');
      strip.className = currentState.pipeline === 'IDLE' ? 'progress-strip' : 'progress-strip active';
      fill.style.width = `${percent}%`;
      document.getElementById('libraryMeta').textContent = `${(currentState.transfers || []).length} file(s)`;
      renderList();
    }

    function renderList() {
      const items = currentState.transfers || [];
      const list = document.getElementById('transferList');
      list.innerHTML = '';
      if (!items.length) {
        list.innerHTML = '<div class="empty">No upload yet.</div>';
        return;
      }
      items.slice().reverse().forEach((item, idx) => {
        const realIndex = items.length - 1 - idx;
        const row = document.createElement('div');
        row.className = 'history-item';
        row.innerHTML = `
          <div class="tooltip-wrap">
            <div class="tooltip-panel">
              <div class="tooltip-title">${escapeHtml(item.label)}</div>
              <div class="tooltip-line">Type: ${escapeHtml(item.service || 'Link')} / ${escapeHtml(item.delivery || 'LINK')}</div>
              <div class="tooltip-line">Size: ${escapeHtml(item.total_bytes ? formatSize(item.total_bytes) : 'unknown')}</div>
              <div class="tooltip-line">Created: ${escapeHtml(item.created_at || 'unknown')}</div>
              <div class="tooltip-line">Expires: ${escapeHtml(item.expires_at || 'unknown')}</div>
              <div class="tooltip-line">${escapeHtml(item.preview_hint || 'Shared link')}</div>
            </div>
            <div class="history-top">
              <div>
                <div class="history-name">${escapeHtml(item.label)}</div>
                <div class="history-meta">${escapeHtml(item.service || 'Link')} / ${escapeHtml(item.delivery || 'LINK')} / ${escapeHtml(item.total_bytes ? formatSize(item.total_bytes) : 'unknown size')}</div>
              </div>
              <div class="history-actions">
                <button class="slim" onclick="copyTransfer(${realIndex})">Copy</button>
                <button class="primary slim" onclick="openTransfer(${realIndex})">Open</button>
              </div>
            </div>
          </div>
        `;
        list.appendChild(row);
      });
    }

    async function bootstrap() {
      renderState(await callBridge('get_state'));
      const logs = await callBridge('get_logs');
      setStatus((logs || []).slice(-1)[0] || 'Ready.');
    }

    async function closeWindow(event) {
      event?.stopPropagation?.();
      await callBridge('close_window');
    }

    async function minimizeWindow(event) {
      event?.stopPropagation?.();
      await callBridge('minimize_window');
    }

    async function refreshHud(event) {
      event?.stopPropagation?.();
      renderState(await callBridge('get_state'));
      const logs = await callBridge('get_logs');
      setStatus((logs || []).slice(-1)[0] || 'Ready.');
    }

    async function browseFiles() {
      renderState(await callBridge('start_upload'));
    }

    async function clearHistory() {
      renderState(await callBridge('clear_history'));
      setStatus('History cleared.');
    }

    async function copyTransfer(index) {
      const item = (currentState.transfers || [])[index];
      if (!item || !item.link) return;
      const ok = await callBridge('copy_to_clipboard', item.link);
      setStatus(ok ? `Link copied for ${item.label}.` : 'Copy failed.');
    }

    async function openTransfer(index) {
      const item = (currentState.transfers || [])[index];
      if (!item || !item.link) return;
      await callBridge('open_external', item.link);
    }

    function installDragHelpers() {
      const zone = document.getElementById('dropZone');
      if (!zone) return;
      const activate = () => zone.classList.add('dragover');
      const clear = () => zone.classList.remove('dragover');
      ['dragenter', 'dragover'].forEach((eventName) => {
        zone.addEventListener(eventName, (event) => {
          event.preventDefault();
          activate();
        });
      });
      ['dragleave', 'drop'].forEach((eventName) => {
        zone.addEventListener(eventName, (event) => {
          event.preventDefault();
          clear();
        });
      });
      window.setDropHighlight = function(active) {
        if (active) activate(); else clear();
      };
    }

    function installWindowDrag() {
      const head = document.getElementById('headBar');
      if (!head) return;
      let dragging = false;
      function onMove(event) {
        if (!dragging) return;
        bridge.drag_move(event.screenX, event.screenY);
      }
      function onUp() {
        if (!dragging) return;
        dragging = false;
        document.removeEventListener('mousemove', onMove);
        bridge.end_drag();
      }
      head.addEventListener('mousedown', (event) => {
        if (!bridgeReady || event.button !== 0) return;
        if (event.target.closest('button')) return;
        dragging = true;
        bridge.begin_drag(event.screenX, event.screenY);
        document.addEventListener('mousemove', onMove);
        document.addEventListener('mouseup', onUp, { once: true });
      });
    }

    function initBridge() {
      new QWebChannel(qt.webChannelTransport, function(channel) {
        bridge = channel.objects.bridge;
        bridgeReady = true;
        installWindowDrag();
        bootstrap();
      });
    }

    window.handleBackendEvent = function(event) {
      if (event.type === 'state') renderState(event.payload);
      if (event.type === 'log') setStatus(event.payload);
    };

    document.addEventListener('DOMContentLoaded', () => {
      installDragHelpers();
      initBridge();
    });
  </script>
</body>
</html>"""


def find_browser() -> str | None:
    for candidate in BROWSER_CANDIDATES:
        if candidate.exists():
            return str(candidate)
    return None


def infer_expiry(created_at: str) -> str:
    if not created_at:
        return ''
    try:
        base = datetime.strptime(created_at, '%Y-%m-%d %H:%M:%S')
    except ValueError:
        return ''
    return (base + timedelta(days=DEFAULT_EXPIRY_DAYS)).strftime('%Y-%m-%d %H:%M:%S')


def infer_service(link: str) -> str:
    clean = (link or '').strip().lower()
    if 'files.catbox.moe/' in clean or 'litter.catbox.moe/' in clean:
        return 'Catbox'
    if 'transfer.it/' in clean:
        return 'Transfer.it'
    return 'Link'


def infer_delivery(link: str) -> str:
    clean = (link or '').strip().lower()
    if 'files.catbox.moe/' in clean or 'litter.catbox.moe/' in clean:
        return 'DIRECT'
    if 'transfer.it/' in clean:
        return 'PAGE'
    return 'LINK'


def infer_preview_hint(file_name: str, delivery: str) -> str:
    suffix = Path(file_name or '').suffix.lower()
    if delivery == 'DIRECT' and suffix in DIRECT_PREVIEW_EXTENSIONS:
        return 'Discord preview possible'
    if suffix in DIRECT_PREVIEW_EXTENSIONS:
        return 'Preview depends on the host'
    return 'Shared link'


def format_timestamp(moment: datetime) -> str:
    return moment.strftime('%Y-%m-%d %H:%M:%S')


@dataclass
class TransferRecord:
    label: str
    link: str
    created_at: str
    expires_at: str
    file_count: int
    total_bytes: int
    service: str = ''
    delivery: str = ''
    preview_hint: str = ''
    file_names: list[str] = field(default_factory=list)


@dataclass
class AppState:
    transfers: list[TransferRecord] = field(default_factory=list)

    @classmethod
    def load(cls, path: Path) -> 'AppState':
        if not path.exists():
            return cls()
        raw = json.loads(path.read_text(encoding='utf-8'))
        return cls(
            transfers=[
                TransferRecord(
                    label=item.get('label', ''),
                    link=item.get('link', ''),
                    created_at=item.get('created_at', ''),
                    expires_at=item.get('expires_at', '') or infer_expiry(item.get('created_at', '')),
                    file_count=item.get('file_count', 0),
                    total_bytes=item.get('total_bytes', 0),
                    service=item.get('service', '') or infer_service(item.get('link', '')),
                    delivery=item.get('delivery', '') or infer_delivery(item.get('link', '')),
                    preview_hint=item.get('preview_hint', '') or infer_preview_hint(item.get('label', ''), item.get('delivery', '') or infer_delivery(item.get('link', ''))),
                    file_names=item.get('file_names', []),
                )
                for item in raw.get('transfers', [])
            ]
        )

    def save(self, path: Path) -> None:
        path.write_text(json.dumps({'transfers': [asdict(item) for item in self.transfers]}, indent=2, ensure_ascii=False), encoding='utf-8')


class CatboxUploader:
    def upload_file(self, path: Path, progress: Any | None = None) -> str:
        guessed_type = mimetypes.guess_type(path.name)[0] or 'application/octet-stream'
        boundary = f'----ShareScope{secrets.token_hex(12)}'
        prefix = (
            f'--{boundary}\r\n'
            f'Content-Disposition: form-data; name="reqtype"\r\n\r\n'
            f'fileupload\r\n'
            f'--{boundary}\r\n'
            f'Content-Disposition: form-data; name="fileToUpload"; filename="{path.name}"\r\n'
            f'Content-Type: {guessed_type}\r\n\r\n'
        ).encode('utf-8')
        suffix = f'\r\n--{boundary}--\r\n'.encode('utf-8')
        total_length = len(prefix) + path.stat().st_size + len(suffix)
        sent = 0

        def bump(amount: int) -> None:
            nonlocal sent
            sent += amount
            if progress:
                progress(sent, total_length)

        connection = http.client.HTTPSConnection('catbox.moe', timeout=7200)
        try:
            connection.putrequest('POST', '/user/api.php')
            connection.putheader('Content-Type', f'multipart/form-data; boundary={boundary}')
            connection.putheader('Content-Length', str(total_length))
            connection.putheader('User-Agent', 'ShareScope/1.0')
            connection.endheaders()

            connection.send(prefix)
            bump(len(prefix))

            with path.open('rb') as handle:
                while True:
                    chunk = handle.read(64 * 1024)
                    if not chunk:
                        break
                    connection.send(chunk)
                    bump(len(chunk))

            connection.send(suffix)
            bump(len(suffix))

            response = connection.getresponse()
            text = response.read().decode('utf-8', errors='replace').strip()
        finally:
            connection.close()

        if response.status != 200:
            raise RuntimeError(f'Catbox HTTP {response.status}')
        if not text.startswith('https://'):
            raise RuntimeError(text or 'Catbox did not return a direct link.')
        return text


class TransferAutomator:
    def __init__(self, browser_path: str | None) -> None:
        self.browser_path = browser_path

    def _link_is_live(self, context: Any, link: str) -> bool:
        probe = context.new_page()
        try:
            probe.goto(link, wait_until='domcontentloaded', timeout=120000)
            probe.wait_for_timeout(4000)
            text = probe.locator('body').inner_text().lower()
            return 'nous ne trouvons pas ce transfert' not in text and "we can't find this transfer" not in text
        finally:
            probe.close()

    def upload_files(self, paths: list[Path], progress: Any | None = None) -> str:
        with sync_playwright() as p:
            if progress:
                progress(5, 'Opening Transfer.it')
            launch_kwargs: dict[str, Any] = {'headless': True}
            if self.browser_path:
                launch_kwargs['executable_path'] = self.browser_path
            browser = p.chromium.launch(**launch_kwargs)
            context = browser.new_context(permissions=['clipboard-read', 'clipboard-write'])
            page = context.new_page()
            try:
                page.goto(TRANSFER_URL, wait_until='networkidle', timeout=120000)
                if progress:
                    progress(12, 'Transfer.it ready')
                page.locator('input[name="select-file"]').first.set_input_files([str(path) for path in paths])
                if progress:
                    progress(24, 'Files selected')
                terms = page.locator('input[name="glb-terms-and-privacy"]').first
                if terms.count():
                    terms.check()
                if progress:
                    progress(32, 'Submitting upload')
                page.locator('button.js-get-link-button').first.click(timeout=30000)
                copy_button = page.locator('button.js-copy-link:visible').last
                copy_button.wait_for(state='visible', timeout=7200000)
                if progress:
                    progress(72, 'Upload finished, generating link')
                page.wait_for_function(
                    """() => {
                        const buttons = [...document.querySelectorAll('button.js-copy-link')];
                        const visible = buttons.filter((button) => {
                            const style = window.getComputedStyle(button);
                            return style.display !== 'none' && style.visibility !== 'hidden' && button.offsetParent !== null;
                        });
                        const active = visible[visible.length - 1];
                        return active && !active.classList.contains('disabled');
                    }""",
                    timeout=7200000,
                )
                if progress:
                    progress(92, 'Finalizing link')
                link = ''
                for attempt in range(4):
                    page.wait_for_timeout(2000 if attempt == 0 else 3000)
                    copy_button.click(timeout=15000)
                    link = page.evaluate('navigator.clipboard.readText()').strip()
                    if not link or 'transfer.it/' not in link:
                        continue
                    if self._link_is_live(context, link):
                        break
                if not link or 'transfer.it/' not in link:
                    raise RuntimeError('Transfer.it did not return a share link.')
                if not self._link_is_live(context, link):
                    raise RuntimeError('Transfer.it returned a link, but it is not live yet.')
                if progress:
                    progress(100, 'Transfer.it link ready')
                return link
            except PlaywrightTimeoutError as exc:
                raise RuntimeError('Transfer.it timed out while generating the link.') from exc
            finally:
                context.close()
                browser.close()


class HudWindow(QWidget):
    js_requested = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle('ShareScope')
        self.setFixedSize(470, 690)
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)

        self.view = QWebEngineView(self)
        self.view.setAcceptDrops(False)
        self.view.setContextMenuPolicy(Qt.NoContextMenu)
        self.view.settings().setAttribute(QWebEngineSettings.LocalContentCanAccessFileUrls, True)
        self.view.settings().setAttribute(QWebEngineSettings.LocalContentCanAccessRemoteUrls, True)
        self.view.settings().setAttribute(QWebEngineSettings.JavascriptCanAccessClipboard, False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.view)

        self.js_requested.connect(self._run_js)

    def _run_js(self, script: str) -> None:
        self.view.page().runJavaScript(script)

    def dispatch_js(self, script: str) -> None:
        self.js_requested.emit(script)


class DropWebView(QWebEngineView):
    def __init__(self, bridge: 'AppBridge', parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.bridge = bridge
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event) -> None:  # type: ignore[override]
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self.page().runJavaScript("window.setDropHighlight && window.setDropHighlight(true);")
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:  # type: ignore[override]
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dragLeaveEvent(self, event) -> None:  # type: ignore[override]
        self.page().runJavaScript("window.setDropHighlight && window.setDropHighlight(false);")
        super().dragLeaveEvent(event)

    def dropEvent(self, event) -> None:  # type: ignore[override]
        self.page().runJavaScript("window.setDropHighlight && window.setDropHighlight(false);")
        urls = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
        if urls:
            event.acceptProposedAction()
            self.bridge.queue_dropped_files(urls)
        else:
            super().dropEvent(event)


class AppBridge(QObject):
    def __init__(self) -> None:
        super().__init__()
        self.state = AppState.load(STATE_FILE)
        self.pipeline = 'IDLE'
        self.progress_percent = 0
        self.browser_path = find_browser()
        self.logs = [
            self._stamp('native hud ready'),
            self._stamp('drop files to get a direct media link when possible'),
        ]
        self.host: HudWindow | None = None
        self._drag_active = False
        self._drag_offset_x = 0
        self._drag_offset_y = 0

    def bind(self, host: HudWindow) -> None:
        self.host = host
        channel = QWebChannel(host.view.page())
        channel.registerObject('bridge', self)
        host.view.page().setWebChannel(channel)
        host.view.setHtml(HTML, QUrl('https://sharescope.local/'))
        host.view.loadFinished.connect(self._on_loaded)

    def _stamp(self, message: str) -> str:
        return f"[{datetime.now().strftime('%H:%M:%S')}] {message}"

    def _push(self, event_type: str, payload: Any) -> None:
        if not self.host:
            return
        script = (
            "window.handleBackendEvent && window.handleBackendEvent("
            f"{json.dumps({'type': event_type, 'payload': payload}, ensure_ascii=False)});"
        )
        self.host.dispatch_js(script)

    def _log(self, message: str) -> None:
        line = self._stamp(message)
        self.logs.append(line)
        self.logs = self.logs[-240:]
        self._push('log', line)

    def _state_payload(self) -> dict[str, Any]:
        return {
            'pipeline': self.pipeline,
            'progress_percent': self.progress_percent,
            'browser_ready': bool(self.browser_path) or getattr(sys, 'frozen', False),
            'transfers': [asdict(item) for item in self.state.transfers],
        }

    def _set_progress(self, percent: int, status: str | None = None) -> None:
        bounded = max(0, min(100, int(percent)))
        if bounded == self.progress_percent and not status:
            return
        self.progress_percent = bounded
        if status:
            self._log(status)
        self._push('state', self._state_payload())

    def _build_record(
        self,
        *,
        label: str,
        link: str,
        total_bytes: int,
        file_names: list[str],
        service: str,
        delivery: str,
        created_at: datetime | None = None,
    ) -> TransferRecord:
        moment = created_at or datetime.now()
        return TransferRecord(
            label=label,
            link=link,
            created_at=format_timestamp(moment),
            expires_at=format_timestamp(moment + timedelta(days=DEFAULT_EXPIRY_DAYS)),
            file_count=len(file_names),
            total_bytes=total_bytes,
            service=service,
            delivery=delivery,
            preview_hint=infer_preview_hint(file_names[0] if file_names else label, delivery),
            file_names=file_names,
        )

    def _append_record(self, record: TransferRecord) -> None:
        self.state.transfers.append(record)
        self.state.save(STATE_FILE)
        self._push('state', self._state_payload())

    def _should_try_catbox(self, path: Path) -> bool:
        try:
            return path.stat().st_size <= CATBOX_MAX_BYTES
        except OSError:
            return False

    def _queue_upload(self, paths: list[Path]) -> None:
        valid_paths = []
        for path in paths:
            expanded = Path(path).expanduser()
            if not expanded.exists():
                self._log(f'skipped missing path: {expanded}')
                continue
            if expanded.is_dir():
                self._log(f'skipped directory path: {expanded}')
                continue
            valid_paths.append(expanded)

        if not valid_paths:
            self._log('no valid file to upload')
            return

        if self.pipeline != 'IDLE':
            self._log('upload ignored because another upload is running')
            return

        threading.Thread(target=self._upload_worker, args=(valid_paths,), daemon=True).start()

    def _upload_worker(self, paths: list[Path]) -> None:
        self.pipeline = 'UPLOADING'
        self.progress_percent = 0
        self._push('state', self._state_payload())
        self._log(f'starting upload for {len(paths)} file(s)')
        try:
            catbox = CatboxUploader()
            transfer_fallback: list[Path] = []
            total_bytes = sum(path.stat().st_size for path in paths)
            completed_bytes = 0

            for path in paths:
                file_size = path.stat().st_size
                if not self._should_try_catbox(path):
                    self._log(f'{path.name} exceeds Catbox direct-link size, switching to transfer page')
                    transfer_fallback.append(path)
                    continue

                try:
                    self._log(f'uploading {path.name} to Catbox direct-link')

                    def report_catbox(sent: int, _total: int, *, base: int = completed_bytes) -> None:
                        percent = round(((base + sent) / total_bytes) * 100) if total_bytes else 0
                        self._set_progress(percent)

                    link = catbox.upload_file(path, progress=report_catbox)
                    self._set_progress(round(((completed_bytes + file_size) / total_bytes) * 100) if total_bytes else 100)
                    self._append_record(
                        self._build_record(
                            label=path.name,
                            link=link,
                            total_bytes=file_size,
                            file_names=[path.name],
                            service='Catbox',
                            delivery='DIRECT',
                        )
                    )
                    self._log(f'direct link ready: {link}')
                    completed_bytes += file_size
                except Exception as exc:
                    self._log(f'Catbox failed for {path.name}: {exc}')
                    transfer_fallback.append(path)

            if transfer_fallback:
                if not self.browser_path and not getattr(sys, 'frozen', False):
                    missing = ', '.join(path.name for path in transfer_fallback)
                    raise RuntimeError(f'No supported browser found for Transfer.it fallback: {missing}')

                self._log(f'opening Transfer.it fallback for {len(transfer_fallback)} file(s)')
                automator = TransferAutomator(self.browser_path)
                fallback_total = sum(path.stat().st_size for path in transfer_fallback)

                def report_transfer(stage_percent: int, status: str) -> None:
                    if total_bytes <= 0:
                        self._set_progress(stage_percent, status)
                        return
                    scaled = completed_bytes + round(fallback_total * (stage_percent / 100))
                    percent = round((scaled / total_bytes) * 100)
                    self._set_progress(percent, status)

                link = automator.upload_files(transfer_fallback, progress=report_transfer)
                label = transfer_fallback[0].name if len(transfer_fallback) == 1 else f'{transfer_fallback[0].name} +{len(transfer_fallback) - 1}'
                self._append_record(
                    self._build_record(
                        label=label,
                        link=link,
                        total_bytes=fallback_total,
                        file_names=[path.name for path in transfer_fallback],
                        service='Transfer.it',
                        delivery='PAGE',
                    )
                )
                self._log(f'fallback link ready: {link}')

            self._set_progress(100)
        except Exception as exc:
            self._log(f'upload failed: {exc}')
        finally:
            self.pipeline = 'IDLE'
            self.progress_percent = 0
            self._push('state', self._state_payload())

    def queue_dropped_files(self, paths: list[str]) -> None:
        if paths:
            self._log(f'dropped {len(paths)} file(s)')
            self._queue_upload([Path(path) for path in paths])

    def _on_loaded(self, ok: bool) -> None:
        if ok:
            QTimer.singleShot(150, lambda: self._push('state', self._state_payload()))

    @Slot(result='QVariant')
    def get_state(self) -> dict[str, Any]:
        return self._state_payload()

    @Slot(result='QVariant')
    def get_logs(self) -> list[str]:
        return self.logs[-120:]

    @Slot(result='QVariant')
    def start_upload(self) -> dict[str, Any]:
        if not self.host:
            return self._state_payload()
        selected, _ = QFileDialog.getOpenFileNames(self.host, 'Select files')
        if not selected:
            self._log('file picker closed')
            return self._state_payload()
        self._queue_upload([Path(path) for path in selected])
        return self._state_payload()

    @Slot(result='QVariant')
    def clear_history(self) -> dict[str, Any]:
        self.state.transfers.clear()
        self.state.save(STATE_FILE)
        self._log('local history cleared')
        self._push('state', self._state_payload())
        return self._state_payload()

    @Slot(str, result=bool)
    def open_external(self, url: str) -> bool:
        clean = (url or '').strip()
        if not clean:
            return False
        webbrowser.open(clean)
        self._log(f'opened {clean}')
        return True

    @Slot(str, result=bool)
    def copy_to_clipboard(self, value: str) -> bool:
        clean = (value or '').strip()
        if not clean:
            return False
        QGuiApplication.clipboard().setText(clean)
        self._log(f'copied link {clean}')
        return True

    @Slot(result=bool)
    def close_window(self) -> bool:
        if not self.host:
            return False
        self.host.close()
        return True

    @Slot(result=bool)
    def minimize_window(self) -> bool:
        if not self.host:
            return False
        self.host.showMinimized()
        return True

    @Slot(int, int)
    def begin_drag(self, screen_x: int, screen_y: int) -> None:
        if not self.host:
            return
        self._drag_active = True
        self._drag_offset_x = screen_x - self.host.x()
        self._drag_offset_y = screen_y - self.host.y()

    @Slot(int, int)
    def drag_move(self, screen_x: int, screen_y: int) -> None:
        if not self.host or not self._drag_active:
            return
        self.host.move(screen_x - self._drag_offset_x, screen_y - self._drag_offset_y)

    @Slot()
    def end_drag(self) -> None:
        self._drag_active = False


def main() -> None:
    app = QApplication.instance() or QApplication([])
    host = HudWindow()
    bridge = AppBridge()

    layout = host.layout()
    if layout is not None:
        layout.removeWidget(host.view)
    host.view.deleteLater()
    host.view = DropWebView(bridge, host)
    host.view.setContextMenuPolicy(Qt.NoContextMenu)
    host.view.settings().setAttribute(QWebEngineSettings.LocalContentCanAccessFileUrls, True)
    host.view.settings().setAttribute(QWebEngineSettings.LocalContentCanAccessRemoteUrls, True)
    host.view.settings().setAttribute(QWebEngineSettings.JavascriptCanAccessClipboard, False)
    if layout is not None:
        layout.addWidget(host.view)

    bridge.bind(host)
    host.show()
    app.exec()


if __name__ == '__main__':
    main()
