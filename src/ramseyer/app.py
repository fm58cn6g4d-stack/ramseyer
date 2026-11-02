"""M8: the first version of the local app (docs/11-packaging.md): a page in the web browser that runs on this machine
only. Drop a draft, click Analyze, read the summary and the comparative print, download the Word version.

The server listens on 127.0.0.1 only, so nothing outside this computer can reach it, and drafts are never sent
anywhere; each analysis is also written to a report folder under var/app/. Python's standard library serves the page;
nothing else is installed for it. Finished in M12 (review buttons, ripple graph, settings).
"""
from __future__ import annotations

import html
import json
import secrets
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from ramseyer import config

PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>ramseyer</title><style>
:root { --ink:#1b1b1b; --muted:#5b5b5b; --line:#d8d8d8; --accent:#1f4e8c; --paper:#fff; --soft:#f4f6f9; }
@media (prefers-color-scheme: dark) { :root { --ink:#e8e8e8; --muted:#a8a8a8; --line:#3a3a3a; --accent:#8db4ef;
  --paper:#151515; --soft:#1f2329; } }
body { font: 16px/1.5 system-ui, sans-serif; color: var(--ink); background: var(--paper); margin: 0; }
main { max-width: 60rem; margin: 0 auto; padding: 1.5rem 1rem 4rem; }
h1 { font-size: 1.5rem; margin: 0 0 .25rem; } .muted { color: var(--muted); font-size: .9rem; }
#drop { border: 2px dashed var(--line); border-radius: 10px; padding: 2rem 1rem; text-align: center; margin: 1.25rem 0;
  background: var(--soft); cursor: pointer; } #drop.over { border-color: var(--accent); }
button { font: inherit; background: var(--accent); color: #fff; border: 0; border-radius: 6px; padding: .55rem 1.1rem;
  cursor: pointer; } button[disabled] { opacity: .5; cursor: default; }
.tabs { display: flex; gap: .25rem; border-bottom: 1px solid var(--line); margin-top: 1.5rem; flex-wrap: wrap; }
.tabs button { background: none; color: var(--ink); border-radius: 6px 6px 0 0; }
.tabs button.on { background: var(--soft); color: var(--accent); font-weight: 600; }
.panel { display: none; padding-top: 1rem; } .panel.on { display: block; }
iframe { width: 100%; height: 75vh; border: 1px solid var(--line); border-radius: 6px; background: #fff; }
table { border-collapse: collapse; width: 100%; font-size: .9rem; } td, th { border-bottom: 1px solid var(--line);
  padding: .35rem .5rem; text-align: left; vertical-align: top; } .err { color: #a1260d; }
</style></head><body><main>
<h1>ramseyer</h1><div class="muted">Maps a draft bill onto the U.S. Code. Runs on this computer only; nothing is
uploaded. Code checked against release point __RP__.</div>
<div id="drop">Drop a draft here (.txt, .md or bill .xml), or click to choose a file<br>
<span class="muted" id="fname">No file chosen</span><input type="file" id="file" accept=".txt,.md,.xml" hidden></div>
<button id="go" disabled>Analyze</button> <span class="muted" id="state"></span>
<div id="results" hidden>
<div class="tabs"><button data-p="sum" class="on">Summary</button><button data-p="committee">Comparative print
</button><button data-p="working">Working redline</button></div>
<div class="panel on" id="p-sum"></div>
<div class="panel" id="p-committee"><iframe id="f-committee" title="Comparative print"></iframe></div>
<div class="panel" id="p-working"><iframe id="f-working" title="Working redline"></iframe></div>
</div></main><script>
const TOKEN = "__TOKEN__";
let chosen = null;
const drop = document.getElementById('drop'), file = document.getElementById('file'), go = document.getElementById('go');
function pick(f) { chosen = f; document.getElementById('fname').textContent = f.name; go.disabled = false; }
drop.onclick = () => file.click(); file.onchange = () => file.files[0] && pick(file.files[0]);
drop.ondragover = e => { e.preventDefault(); drop.classList.add('over'); };
drop.ondragleave = () => drop.classList.remove('over');
drop.ondrop = e => { e.preventDefault(); drop.classList.remove('over'); e.dataTransfer.files[0] && pick(e.dataTransfer.files[0]); };
document.querySelectorAll('.tabs button').forEach(b => b.onclick = () => {
  document.querySelectorAll('.tabs button').forEach(x => x.classList.toggle('on', x === b));
  document.querySelectorAll('.panel').forEach(p => p.classList.toggle('on', p.id === 'p-' + b.dataset.p)); });
function esc(s) { return String(s).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])); }
go.onclick = async () => {
  go.disabled = true; document.getElementById('state').textContent = 'Analyzing… (a large bill can take a few minutes)';
  const r = await fetch('/analyze?name=' + encodeURIComponent(chosen.name),
                        {method: 'POST', headers: {'X-Token': TOKEN}, body: chosen});
  const d = await r.json(); go.disabled = false;
  if (!r.ok) { document.getElementById('state').innerHTML = '<span class="err">' + esc(d.error) + '</span>'; return; }
  document.getElementById('state').textContent = 'Done.';
  document.getElementById('results').hidden = false;
  document.getElementById('f-committee').src = '/report/' + d.id + '/comparative.html';
  document.getElementById('f-working').src = '/report/' + d.id + '/comparative-working.html';
  const counts = Object.entries(d.counts).map(([k, v]) => '<b>' + v + '</b> ' + esc(k)).join(' · ');
  const rows = d.instructions.map(i => '<tr><td>' + esc(i.status) + '</td><td>' + esc(i.target) + '</td><td>' +
    esc(i.source) + '</td><td>' + esc(i.detail) + '</td></tr>').join('');
  document.getElementById('p-sum').innerHTML = '<p>' + counts + '</p><p class="muted">Release point ' +
    esc(d.release_point) + ' · input ' + esc(d.input_hash.slice(0, 12)) + ' · ' + esc(d.generated) + '</p>' +
    '<p><a href="/report/' + d.id + '/comparative.docx" download>Download the Word version</a></p>' +
    '<table><tr><th>Status</th><th>Target</th><th>Instruction</th><th>Why</th></tr>' + rows + '</table>';
};
</script></body></html>"""


def make_server(port: int = 0, root: Path | None = None) -> ThreadingHTTPServer:
    """The app's server on 127.0.0.1 (port 0: any free port). Each page load carries a fresh token that analysis
    requests must return, so another web page open in the browser cannot post drafts to it."""
    from ramseyer.analyze import analyze, resolver, write_report
    root = root or config.load().var / "app"
    token = secrets.token_urlsafe(16)
    rp = resolver().ix.release_point

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):            # quiet: drafts' names are not logged
            pass

        def _send(self, code: int, body: bytes, kind: str, extra: dict | None = None):
            self.send_response(code)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Content-Type-Options", "nosniff")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path in ("/", "/index.html"):
                page = PAGE.replace("__TOKEN__", token).replace("__RP__", html.escape(rp))
                return self._send(200, page.encode(), "text/html; charset=utf-8")
            parts = self.path.split("/")
            if len(parts) == 4 and parts[1] == "report" and parts[2].isalnum() and \
                    parts[3] in ("comparative.html", "comparative-working.html", "comparative.docx"):
                path = root / parts[2] / parts[3]
                if path.exists():
                    kind = "text/html; charset=utf-8" if parts[3].endswith(".html") else \
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                    return self._send(200, path.read_bytes(), kind)
            self._send(404, b"not found", "text/plain")

        def do_POST(self):
            if not self.path.startswith("/analyze") or self.headers.get("X-Token") != token:
                return self._send(403, json.dumps({"error": "not allowed"}).encode(), "application/json")
            from urllib.parse import parse_qs, urlparse
            name = parse_qs(urlparse(self.path).query).get("name", ["draft.txt"])[0]
            data = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            try:
                a = analyze(name, data)
            except ValueError as e:
                return self._send(400, json.dumps({"error": str(e)}).encode(), "application/json")
            rid = a.input_hash[:16]
            write_report(a, root / rid)
            body = {"id": rid, "counts": a.counts, "instructions": a.instructions, "release_point": a.release_point,
                    "input_hash": a.input_hash, "generated": a.generated}
            self._send(200, json.dumps(body, ensure_ascii=False).encode(), "application/json")

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def serve(port: int = 0, open_browser: bool = True) -> None:
    server = make_server(port)
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    print(f"ramseyer is running at {url} (only on this computer). Press Ctrl+C to stop.")
    if open_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
