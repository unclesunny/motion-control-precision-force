"""
Oscilloscope Web Server — Python http.server + HTML5 Canvas.
Zero GUI dependencies. Open browser → see waveforms.

Usage:
    python scope_server.py
    → Open http://localhost:8888 in any browser
"""

import http.server
import json
import math
import sys
import threading
import time
from pathlib import Path
from urllib.parse import urlparse, parse_qs

import numpy as np

# ── Data engine (runs in background thread) ──────────────

CHANNELS = [
    {"name": "Position", "unit": "pulses", "color": "#00FF88"},
    {"name": "Velocity", "unit": "rpm",    "color": "#FF8800"},
    {"name": "Current",  "unit": "%",      "color": "#FF4444"},
    {"name": "Torque",   "unit": "%",      "color": "#44AAFF"},
]

class ScopeEngine:
    def __init__(self):
        self.buf_size = 60000
        self.data = np.zeros((4, self.buf_size), dtype=np.float32)
        self.head = 0
        self.count = 0
        self._running = True
        self._lock = threading.Lock()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        t0 = time.perf_counter()
        while self._running:
            t = time.perf_counter() - t0
            s = self.count / 1000.0
            vals = [
                1000.0 * math.sin(2*math.pi*2.0*s),
                500.0  * math.sin(2*math.pi*3.5*s + 0.5),
                80.0   + 30.0 * math.sin(2*math.pi*5.0*s),
                60.0   * math.sin(2*math.pi*2.0*s + 1.2),
            ]
            with self._lock:
                for i, v in enumerate(vals):
                    self.data[i, self.head] = v
                self.head = (self.head + 1) % self.buf_size
                self.count += 1
            time.sleep(0.001)  # ~1kHz

    def get_waveform(self, n=6000):
        with self._lock:
            n = min(n, self.count, self.buf_size)
            if n == 0:
                return {"data": [], "ts": [], "count": 0}
            head = self.head
            if head >= n:
                seg = self.data[:, head-n:head]
            else:
                seg1 = self.data[:, -head:] if head > 0 else self.data[:, :0]
                seg2 = self.data[:, :n-head]
                seg = np.concatenate([seg1, seg2], axis=1)
            return {
                "data": seg.T.tolist()[-n:],
                "count": self.count,
            }

    def stop(self):
        self._running = False

engine = ScopeEngine()

# ── HTML page (embedded in Python) ────────────────────────

HTML_PAGE = r"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Delta A3 Oscilloscope</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{background:#0D0D1A;color:#CCC;font-family:Consolas,monospace;overflow:hidden}
#header{background:#111122;padding:8px 16px;display:flex;align-items:center;gap:16px;border-bottom:1px solid #2A2A4E}
#header h1{font-size:14px;color:#AAAACC}
#header span{font-size:11px;color:#666}
#main{display:flex;height:calc(100vh - 40px)}
#canvas-wrap{flex:1;position:relative}
canvas{display:block}
#side{width:240px;background:#111122;padding:12px;border-left:1px solid #2A2A4E;overflow-y:auto}
#side h3{font-size:11px;color:#AAAACC;margin:8px 0 4px}
.ch-row{display:flex;align-items:center;gap:8px;padding:4px 0;cursor:pointer}
.ch-dot{width:10px;height:10px;border-radius:50%;flex-shrink:0}
.ch-name{font-size:11px;flex:1}
.ch-val{font-size:10px;color:#888;text-align:right}
.ch-on .ch-val{color:#CCC}
button{width:100%;padding:8px;margin:4px 0;background:#2A2A4E;color:#CCC;border:1px solid #4A4A6E;border-radius:4px;cursor:pointer;font-family:Consolas,monospace;font-size:11px}
button:hover{background:#3A3A5E}
#stats{font-size:10px;color:#666;line-height:1.6;margin-top:8px}
.status{color:#888;font-size:10px;margin-top:4px}
</style>
</head>
<body>
<div id="header">
  <h1>Delta A3 Oscilloscope</h1>
  <span id="fps">FPS: --</span>
  <span id="samples">Samples: 0</span>
  <span id="conn">● Connected</span>
</div>
<div id="main">
  <div id="canvas-wrap"><canvas id="c"></canvas></div>
  <div id="side">
    <h3>Channels</h3>
    <div id="chlist"></div>
    <h3>Controls</h3>
    <button id="pauseBtn" onclick="togglePause()">Pause (Space)</button>
    <button onclick="clearBuf()">Clear (R)</button>
    <h3>Stats</h3>
    <div id="stats">Waiting for data...</div>
    <div class="status" id="ai"></div>
  </div>
</div>
<script>
const CH = [
  {name:"Position", unit:"pulses", color:"#00FF88"},
  {name:"Velocity", unit:"rpm",    color:"#FF8800"},
  {name:"Current",  unit:"%",      color:"#FF4444"},
  {name:"Torque",   unit:"%",      color:"#44AAFF"},
];
let pause = false, tw = 5.0, frameN = 0, lastFps = performance.now();

// Build channel toggle list
const chlist = document.getElementById('chlist');
let chVisible = [true,true,true,true];
CH.forEach((ch, i) => {
  const d = document.createElement('div');
  d.className = 'ch-row ch-on';
  d.onclick = () => { chVisible[i] = !chVisible[i]; renderChannels(); };
  d.innerHTML = `<div class="ch-dot" style="background:${ch.color}"></div>
    <div class="ch-name">${ch.name}</div><div class="ch-val" id="chv${i}">--</div>`;
  chlist.appendChild(d);
});

function renderChannels() {
  CH.forEach((ch, i) => {
    const d = chlist.children[i];
    d.className = 'ch-row' + (chVisible[i] ? ' ch-on' : '');
    d.children[0].style.background = chVisible[i] ? ch.color : '#444';
  });
}

function togglePause() {
  pause = !pause;
  document.getElementById('pauseBtn').textContent = pause ? 'Resume (Space)' : 'Pause (Space)';
}

let bufData = [], bufCount = 0;
async function poll() {
  try {
    const r = await fetch('/data?n=' + (tw * 1000));
    const j = await r.json();
    bufData = j.data;
    bufCount = j.count;
  } catch(e) {}
}

function draw() {
  requestAnimationFrame(draw);
  if (pause) return;
  frameN++;
  const now = performance.now();
  if (now - lastFps > 500) {
    document.getElementById('fps').textContent = 'FPS: ' + Math.round(frameN / (now - lastFps) * 1000);
    document.getElementById('samples').textContent = 'Samples: ' + bufCount;
    frameN = 0; lastFps = now;
  }

  const c = document.getElementById('c');
  const wrap = document.getElementById('canvas-wrap');
  c.width = wrap.clientWidth;
  c.height = wrap.clientHeight;
  const w = c.width, h = c.height;
  if (w < 50 || h < 50) return;

  const ctx = c.getContext('2d');
  ctx.fillStyle = '#0D0D1A'; ctx.fillRect(0, 0, w, h);

  if (!bufData.length) return;

  let nVis = chVisible.filter(v => v).length;
  if (nVis === 0) return;
  let chH = h / nVis;

  // Grid
  ctx.strokeStyle = '#1A1A2E'; ctx.lineWidth = 0.5;
  for (let i = 1; i < 10; i++) {
    ctx.beginPath(); ctx.moveTo(w*i/10, 0); ctx.lineTo(w*i/10, h); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(0, h*i/10); ctx.lineTo(w, h*i/10); ctx.stroke();
  }

  let drawn = 0;
  for (let ci = 0; ci < 4; ci++) {
    if (!chVisible[ci]) continue;
    let y0 = drawn * chH + 25, y1 = (drawn + 1) * chH - 10;
    let yRng = y1 - y0;
    if (yRng < 20) continue;

    // Channel data
    let arr = [];
    for (let r of bufData) arr.push(r[ci]);
    if (arr.length < 2) { drawn++; continue; }
    let dmin = Infinity, dmax = -Infinity;
    for (let v of arr) { if (v < dmin) dmin = v; if (v > dmax) dmax = v; }
    if (dmax - dmin < 1) { dmin = -100; dmax = 100; }
    let pad = (dmax - dmin) * 0.05;
    dmin -= pad; dmax += pad;

    // Label
    ctx.fillStyle = CH[ci].color;
    ctx.font = '10px Consolas';
    ctx.fillText(CH[ci].name + ' [' + Math.round(dmin) + '..' + Math.round(dmax) + ']', 10, y0 + 12);

    // Waveform
    ctx.strokeStyle = CH[ci].color;
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    let step = Math.max(1, Math.floor(arr.length / (w - 20)));
    for (let i = 0; i < arr.length; i += step) {
      let x = 10 + (w - 20) * i / arr.length;
      let y = y1 - yRng * (arr[i] - dmin) / (dmax - dmin);
      if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    }
    ctx.stroke();

    // Zero line
    if (dmin < 0 && dmax > 0) {
      let yz = y1 - yRng * (0 - dmin) / (dmax - dmin);
      ctx.strokeStyle = '#222244'; ctx.lineWidth = 0.5;
      ctx.beginPath(); ctx.moveTo(10, yz); ctx.lineTo(w-10, yz); ctx.stroke();
    }

    // Latest value
    let lastV = arr[arr.length-1];
    document.getElementById('chv'+ci).textContent = lastV.toFixed(1) + ' ' + CH[ci].unit;

    // Divider
    ctx.strokeStyle = '#2A2A4E'; ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(0, y1+5); ctx.lineTo(w, y1+5); ctx.stroke();

    drawn++;
  }

  // Stats
  if (bufData.length > 100) {
    let lines = [];
    for (let ci = 0; ci < 4; ci++) {
      let arr = [];
      for (let r of bufData.slice(-500)) arr.push(r[ci]);
      let mn = 0, mx = 0;
      for (let v of arr) { mn += v; if (v > mx) mx = v; }
      mn /= arr.length;
      lines.push(CH[ci].name.padEnd(8) + ' pk=' + mx.toFixed(0).padStart(7) + ' μ=' + mn.toFixed(0).padStart(7));
    }
    document.getElementById('stats').textContent = lines.join('\n');

    // AI check
    let curMax = 0;
    for (let r of bufData.slice(-200)) { if (r[2] > curMax) curMax = r[2]; }
    let ai = document.getElementById('ai');
    if (curMax > 105) {
      ai.textContent = '⚠ Current peak ' + curMax.toFixed(0) + '% — check load';
      ai.style.color = '#FF8844';
    } else {
      ai.textContent = '✓ Normal';
      ai.style.color = '#44FF44';
    }
  }
}

// Start
async function loop() {
  await poll();
  setTimeout(loop, 30);
}
loop();
requestAnimationFrame(draw);
document.addEventListener('keydown', e => {
  if (e.code === 'Space') { e.preventDefault(); togglePause(); }
  if (e.code === 'KeyR') { /* clear */ }
});
document.getElementById('tw').addEventListener('change', function() {
  tw = parseFloat(this.value);
});
</script>
</body>
</html>"""

# ── HTTP Server ───────────────────────────────────────────

class ScopeHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        path = urlparse(self.path).path

        if path == "/" or path == "/index.html":
            self._serve_html()
        elif path == "/data":
            self._serve_data()
        else:
            self.send_response(404)
            self.end_headers()

    def _serve_html(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(HTML_PAGE.encode("utf-8"))

    def _serve_data(self):
        qs = parse_qs(urlparse(self.path).query)
        n = int(qs.get("n", [6000])[0])
        wf = engine.get_waveform(n)
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(wf).encode("utf-8"))

    def log_message(self, format, *args):
        pass  # quiet

def main():
    port = 8888
    # Try to bind the port first
    import socket
    try:
        s = socket.socket()
        s.bind(('0.0.0.0', port))
        s.close()
    except OSError:
        print(f"Port {port} is in use. Trying 8889...")
        port = 8889

    server = http.server.HTTPServer(("0.0.0.0", port), ScopeHandler)

    # Write startup confirmation to file (bypass any terminal buffering)
    import os as _os
    here = Path(__file__).resolve().parent if '__file__' in dir() else Path.cwd()
    with open(here / "SERVER_IS_RUNNING.txt", "w") as f:
        f.write(f"SERVER IS RUNNING\nURL: http://localhost:{port}\nPID: {_os.getpid()}\n")

    msg = f"""
{'='*55}
  Delta A3 Oscilloscope Web Server
  >>> Open: http://localhost:{port} <<<
  Check SERVER_IS_RUNNING.txt in this directory
  Press Ctrl+C to stop
{'='*55}
"""
    sys.stdout.write(msg)
    sys.stdout.flush()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        engine.stop()
        server.shutdown()

if __name__ == "__main__":
    main()
