"""
Oscilloscope Web Server — Python http.server + HTML5 Canvas.
Zero GUI dependencies. Open browser → see waveforms.

Usage:
    python scope_server.py
    → Open http://localhost:8888 in any browser
"""

import http.server
import io
import json
import math
import sys
import threading
import time
from pathlib import Path
from urllib.parse import urlparse, parse_qs

import numpy as np

# ── AI Analyzer + HITL (lazy import — graceful degradation if not installed) ──
_AIPIPELINE = None
_HITL_AVAILABLE = False
try:
    _ai_path = Path(__file__).resolve().parent.parent.parent / "06-ai-analyzer"
    sys.path.insert(0, str(_ai_path))
    from ai_analyzer import AIAnalyzerPipeline, EngineerFeedback, EngineerPrompt
    _HITL_AVAILABLE = True
except ImportError:
    pass

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
        self.data = np.zeros((8, self.buf_size), dtype=np.float32)
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
                1000.0 * math.sin(2*math.pi*2.0*s),              # Position
                500.0  * math.sin(2*math.pi*3.5*s + 0.5),        # Velocity
                80.0   + 30.0 * math.sin(2*math.pi*5.0*s),        # Current
                60.0   * math.sin(2*math.pi*2.0*s + 1.2),         # Torque
                15.0   * math.sin(2*math.pi*7.0*s),               # Foll.Err
                float(self.count % 100 > 50),                     # DIO
                0x0237 if self.count % 200 < 100 else 0x0007,     # Status
                float((self.count // 50) % 8),                    # OpMode
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

# ── Mode state (updated by CLI or API) ────────────────────
_server_mode = "sim"  # "sim" or "discover"


def set_server_mode(mode: str):
    global _server_mode
    _server_mode = mode


def get_server_mode() -> str:
    return _server_mode


# ── Discovery state (shared across requests) ──────────────
_discovery_done = False
_discovery_success = False
_discovery_steps = []  # [{name, status, detail}]
_discovery_master = None
_discovery_axes_cfg = None


def run_discovery():
    """Run hardware discovery, populating _discovery_steps with progress."""
    global _discovery_done, _discovery_success, _discovery_steps
    global _discovery_master, _discovery_axes_cfg

    _discovery_steps = []
    _discovery_done = False
    _discovery_success = False

    STEPS = ["Detect adapter", "Init master", "Scan bus",
             "Discover slaves", "Auto-name axes"]

    def _step(name, status, detail=""):
        _discovery_steps.append({"name": name, "status": status, "detail": detail})

    try:
        # Step 1
        _step(STEPS[0], "running")
        # Add bindings path
        _bindings_path = str(Path(__file__).resolve().parent.parent.parent
                             / "03-ethercat-master" / "bindings")
        if _bindings_path not in sys.path:
            sys.path.insert(0, _bindings_path)
        from discover import detect_ethercat_adapter
        adapter = detect_ethercat_adapter()
        if adapter is None:
            _discovery_steps[-1] = {"name": STEPS[0], "status": "fail",
                                    "detail": "No NIC found"}
            _discovery_done = True
            return
        _discovery_steps[-1] = {"name": STEPS[0], "status": "ok",
                                "detail": str(adapter)[:50]}

        # Step 2
        _step(STEPS[1], "running")
        from ec_master import EcMaster
        master = EcMaster(adapter=adapter)
        _discovery_steps[-1] = {"name": STEPS[1], "status": "ok",
                                "detail": "Ready"}

        # Step 3
        _step(STEPS[2], "running")
        master.scan()
        count = master.slavecount
        if count == 0:
            _discovery_steps[-1] = {"name": STEPS[2], "status": "fail",
                                    "detail": "0 slaves"}
            master.close()
            _discovery_done = True
            return
        _discovery_steps[-1] = {"name": STEPS[2], "status": "ok",
                                "detail": f"{count} slave(s)"}

        # Step 4
        _step(STEPS[3], "running")
        from discover import auto_name_axes, save_axis_config
        slaves = master.discover()
        if not slaves:
            _discovery_steps[-1] = {"name": STEPS[3], "status": "fail",
                                    "detail": "No response"}
            master.close()
            _discovery_done = True
            return
        servo_count = sum(1 for s in slaves
                         if s.get("esi_match", {}).get("is_servo_drive"))
        _discovery_steps[-1] = {"name": STEPS[3], "status": "ok",
                                "detail": f"{len(slaves)} devices ({servo_count} servos)"}

        # Step 5
        _step(STEPS[4], "running")
        axes_cfg = auto_name_axes(slaves)
        save_axis_config(axes_cfg)
        axis_list = ", ".join(a["id"] for a in axes_cfg)
        _discovery_steps[-1] = {"name": STEPS[4], "status": "ok",
                                "detail": axis_list}

        _discovery_success = True
        _discovery_master = master
        _discovery_axes_cfg = axes_cfg
        set_server_mode("discover")

    except Exception as e:
        _discovery_steps.append({"name": "Error", "status": "fail",
                                 "detail": str(e)[:80]})
        if master:
            try:
                master.close()
            except Exception:
                pass

    _discovery_done = True

# ── AI Analyzer + HITL Gate ───────────────────────────────
_AI_PIPELINE = None
_PENDING_PROMPTS = {}  # prompt_id → EngineerPrompt (in-memory for demo)

if _HITL_AVAILABLE:
    try:
        _AI_PIPELINE = AIAnalyzerPipeline(sample_rate_hz=1000.0)
        print(f"  AI Pipeline loaded: {len(_AI_PIPELINE.analyzers)} detectors, HITL enabled")
    except Exception as e:
        print(f"  AI Pipeline init failed: {e}")

def _get_ai_pipeline():
    """Lazy-get or create the AI pipeline."""
    global _AI_PIPELINE, _PENDING_PROMPTS
    if _AI_PIPELINE is None and _HITL_AVAILABLE:
        try:
            _AI_PIPELINE = AIAnalyzerPipeline(sample_rate_hz=1000.0)
        except Exception:
            pass
    return _AI_PIPELINE

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
#canvas-wrap{flex:1;position:relative;overflow:hidden}
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
  <span id="modeBadge" style="font-size:10px;padding:2px 8px;border-radius:3px;">● Sim</span>
  <span id="fps">FPS: --</span>
  <span id="samples">Samples: 0</span>
  <span id="conn">● Connected</span>
</div>
<div id="main">
  <div id="canvas-wrap">
    <div id="discPanel" style="display:block;padding:40px;box-sizing:border-box;
      position:absolute;top:0;left:0;width:100%;height:100%;background:#0D0D1A;z-index:10;">
      <h3 style="color:#AAAACC;text-align:center;margin-bottom:20px;">EtherCAT Hardware Discovery</h3>
      <div id="discSteps" style="max-width:500px;margin:0 auto;background:#111122;
        border:1px solid #2A2A4E;border-radius:6px;padding:16px;"></div>
      <div id="discStatus" style="text-align:center;color:#FFCC44;font-size:12px;margin-top:12px;"></div>
      <div id="discButtons" style="text-align:center;margin-top:14px;display:none;">
        <button onclick="enterSim()" style="background:#3A2A1A;color:#FF8844;
          border:2px solid #5A3A2A;padding:10px 30px;font-size:13px;font-weight:bold;margin:0 8px;">
          Run in Sim Mode</button>
        <button onclick="(function(){var x=new XMLHttpRequest();x.open('POST','/discover/exit');x.send();})()" style="background:#2A2A4E;color:#AAAACC;
          border:1px solid #4A4A6E;padding:10px 30px;font-size:13px;margin:0 8px;">Exit</button>
      </div>
    </div>
    <canvas id="c"></canvas></div>
  <div id="side">
    <h3>Channels</h3>
    <div id="chlist"></div>
    <h3>Controls</h3>
    <button id="pauseBtn" onclick="togglePause()">Pause (Space)</button>
    <button onclick="clearBuf()">Clear (R)</button>
    <button onclick="exportCSV()">Export CSV</button>
    <button onclick="runAIAnalysis()" style="background:#3A3A1E;color:#FFCC44;border-color:#6A6A2E;">🤖 AI 分析 (Run)</button>
    <div id="aiStatus" class="status" style="color:#888;margin-top:4px;font-size:10px;">AI: --</div>
    <h3>HITL Feedback</h3>
    <div id="hitlPanel" style="font-size:10px;color:#888;max-height:300px;overflow-y:auto;">
      <div id="hitlQuestion" style="color:#FFCC44;margin-bottom:6px;display:none;"></div>
      <div id="hitlContext" style="color:#AAAACC;margin-bottom:4px;font-size:9px;display:none;"></div>
      <div id="hitlChecks" style="margin-bottom:6px;display:none;"></div>
      <textarea id="hitlResponse" placeholder="输入观察结果..." style="width:100%;height:50px;background:#1A1A2E;color:#CCC;border:1px solid #4A4A6E;border-radius:4px;font-family:Consolas,monospace;font-size:10px;padding:4px;display:none;resize:vertical;"></textarea>
      <div id="hitlObserve" style="margin-bottom:4px;display:none;">
        <span style="color:#AAAACC;">确认检查项:</span>
        <select id="hitlObserveSelect" style="width:100%;background:#1A1A2E;color:#CCC;border:1px solid #4A4A6E;border-radius:4px;font-size:10px;padding:2px;">
          <option value="">-- 选择观察结果 --</option>
        </select>
      </div>
      <div id="hitlButtons" style="display:none;gap:4px;margin-top:4px;">
        <button onclick="submitFeedback('approved')" style="background:#1A3A1A;color:#44FF44;border-color:#2A5A2A;flex:1;">✓ 授权</button>
        <button onclick="submitFeedback('rejected')" style="background:#3A1A1A;color:#FF4444;border-color:#5A2A2A;flex:1;">✗ 拒绝</button>
      </div>
      <div id="hitlResult" style="margin-top:4px;display:none;"></div>
    </div>
    <h3>Stats</h3>
    <div id="stats">Waiting for data...</div>
    <div class="status" id="ai"></div>
  </div>
</div>
<script>
// ── Discovery (runs FIRST, inside canvas area) ──
var _discDone = false;
var _discSuccess = false;
var _discPanel = document.getElementById('discPanel');
var _discSteps = document.getElementById('discSteps');
var _discStatus = document.getElementById('discStatus');
var _discButtons = document.getElementById('discButtons');
var _discPollTimer = null;

function enterSim() {
  var xhr = new XMLHttpRequest();
  xhr.open('POST', '/discover/sim', true);
  xhr.onload = function() {
    _discDone = true;
    if (_discPanel) _discPanel.style.display = 'none';
  };
  xhr.send();
}

function _discRender(st) {
  if (!_discSteps) return;
  var icons = {pending: ['⏳','#666688'], running: ['⏳','#FFCC44'],
               ok: ['✓','#44FF44'], fail: ['✗','#FF4444']};
  var html = '';
  for (var i = 0; i < st.length; i++) {
    var s = st[i];
    var ic = icons[s.status] || ['?','#666'];
    html += '<div style="padding:5px 8px;color:'+ic[1]+';font-family:monospace;font-size:12px;">'+ic[0]+' '+s.name+' <span style="color:#888;font-size:10px;">'+(s.detail||'')+'</span></div>';
  }
  _discSteps.innerHTML = html;
}

function _discPoll() {
  if (_discDone) { if (_discPollTimer) clearInterval(_discPollTimer); return; }
  var xhr = new XMLHttpRequest();
  xhr.open('GET', '/discover/status', true);
  xhr.onload = function() {
    if (xhr.status !== 200) return;
    try {
      var j = JSON.parse(xhr.responseText);
      _discDone = j.done;
      _discSuccess = j.success;
      _discRender(j.steps || []);
      if (j.done) {
        _discStatus.textContent = j.success
          ? '✓ Hardware found! Loading scope...'
          : 'No EtherCAT hardware detected.';
        _discStatus.style.color = j.success ? '#44FF44' : '#FF8844';
        if (!j.success) _discButtons.style.display = 'block';
        if (j.success) setTimeout(function(){ if(_discPanel)_discPanel.style.display='none'; }, 600);
      } else {
        for (var k = 0; k < (j.steps||[]).length; k++) {
          if (j.steps[k].status === 'running') {
            _discStatus.textContent = j.steps[k].name + '...';
            break;
          }
        }
      }
    } catch(e) {}
  };
  xhr.send();
}
_discPollTimer = setInterval(_discPoll, 400);
_discPoll();

const CH = [
  {name:"Position Actual", unit:"pulses", color:"#00FF88"},
  {name:"Velocity Actual", unit:"rpm",    color:"#FF8800"},
  {name:"Current Actual",  unit:"%",      color:"#FF4444"},
  {name:"Torque Actual",   unit:"%",      color:"#44AAFF"},
  {name:"Following Error", unit:"pulses", color:"#E066CC"},
  {name:"Digital Inputs",      unit:"bits",   color:"#FFCC00"},
  {name:"Statusword",   unit:"hex",    color:"#22DD88"},
  {name:"Op Mode Display",   unit:"code",   color:"#CCCCCC"},
];
let pause = false, tw = 5.0, frameN = 0, lastFps = performance.now();

// Build channel toggle list
const chlist = document.getElementById('chlist');
let chVisible = [true,true,true,true,false,false,false,false];
CH.forEach((ch, i) => {
  const d = document.createElement('div');
  d.className = 'ch-row ch-on';
  d.onclick = () => { chVisible[i] = !chVisible[i]; renderChannels(); };
  d.innerHTML = `<div class="ch-dot" style="background:${ch.color}"></div>
    <div class="ch-name">${ch.name}</div><div class="ch-val" id="chv${i}">--</div>`;
  chlist.appendChild(d);
function exportCSV() {  window.open('/export', '_blank');}
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
  for (let ci = 0; ci < 8; ci++) {
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
    for (let ci = 0; ci < 8; ci++) {
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
if (e.code === 'KeyS' && e.ctrlKey) { e.preventDefault(); exportCSV(); }
function exportCSV() {  window.open('/export', '_blank');}
});
document.getElementById('tw').addEventListener('change', function() {
  tw = parseFloat(this.value);
function exportCSV() {  window.open('/export', '_blank');}
});

// ── HITL (Human-in-the-Loop) Functions ──────────────────────

let currentPromptId = null;
let currentClassification = null;

async function runAIAnalysis() {
  const statusEl = document.getElementById('aiStatus');
  statusEl.textContent = 'AI: 分析中...';
  statusEl.style.color = '#FFCC44';

  try {
    const r = await fetch('/hitl/analyze', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({}),
    });
    const j = await r.json();

    if (j.error) {
      statusEl.textContent = 'AI: ' + j.error;
      statusEl.style.color = '#FF4444';
      return;
    }

    // Show annotations
    let aiMsg = 'AI: ';
    if (j.annotations && j.annotations.length > 0) {
      aiMsg += j.annotations.length + ' events';
      const first = j.annotations[0];
      if (first.severity === 'critical') aiMsg += ' 🔴';
      else if (first.severity === 'warning') aiMsg += ' ⚠';
      else aiMsg += ' ℹ';
    } else {
      aiMsg += '✓ Normal';
      statusEl.style.color = '#44FF44';
    }
    statusEl.textContent = aiMsg;

    // Show HITL prompts
    if (j.prompts && j.prompts.length > 0) {
      showHitlPrompt(j.prompts[0]);
    } else {
      hideHitlPanel();
    }
  } catch(e) {
    statusEl.textContent = 'AI: 连接失败';
    statusEl.style.color = '#FF4444';
  }
}

function showHitlPrompt(prompt) {
  currentPromptId = prompt.prompt_id;
  currentClassification = prompt.classification;

  document.getElementById('hitlQuestion').style.display = 'block';
  document.getElementById('hitlQuestion').textContent = '🤖 ' + prompt.question;

  if (prompt.context) {
    document.getElementById('hitlContext').style.display = 'block';
    document.getElementById('hitlContext').textContent = prompt.context;
  }

  // Suggested checks
  const checksDiv = document.getElementById('hitlChecks');
  const selectEl = document.getElementById('hitlObserveSelect');
  selectEl.innerHTML = '<option value="">-- 选择观察结果 --</option>';

  if (prompt.suggested_checks && prompt.suggested_checks.length > 0) {
    checksDiv.style.display = 'block';
    let checksHtml = '<div style="color:#AAAACC;margin-bottom:2px;">检查清单:</div>';
    prompt.suggested_checks.forEach((check, i) => {
      checksHtml += '<div style="padding:2px 4px;margin:1px 0;background:#1A1A2E;border-radius:2px;color:#CCC;">' + (i+1) + '. ' + check + '</div>';
      const opt = document.createElement('option');
      opt.value = check;
      opt.textContent = (i+1) + '. ' + check.substring(0, 60);
      selectEl.appendChild(opt);
    });
    checksDiv.innerHTML = checksHtml;
  } else {
    checksDiv.style.display = 'none';
  }

  // Show feedback inputs
  document.getElementById('hitlResponse').style.display = 'block';
  document.getElementById('hitlObserve').style.display = 'block';
  document.getElementById('hitlButtons').style.display = 'flex';
  document.getElementById('hitlResult').style.display = 'none';

  // For actionable prompts: show authorize/reject buttons
  // For ambiguous prompts: show submit observation button
  const btnDiv = document.getElementById('hitlButtons');
  if (currentClassification === 'ambiguous') {
    btnDiv.innerHTML = '<button onclick="submitFeedback(\'pending\')" style="background:#2A2A4E;color:#FFCC44;border-color:#4A4A6E;flex:1;">📤 提交观察</button>';
  } else {
    btnDiv.innerHTML = '<button onclick="submitFeedback(\'approved\')" style="background:#1A3A1A;color:#44FF44;border-color:#2A5A2A;flex:1;">✓ 授权执行</button>' +
      '<button onclick="submitFeedback(\'rejected\')" style="background:#3A1A1A;color:#FF4444;border-color:#5A2A2A;flex:1;">✗ 拒绝</button>';
  }
}

function hideHitlPanel() {
  document.getElementById('hitlQuestion').style.display = 'none';
  document.getElementById('hitlContext').style.display = 'none';
  document.getElementById('hitlChecks').style.display = 'none';
  document.getElementById('hitlResponse').style.display = 'none';
  document.getElementById('hitlObserve').style.display = 'none';
  document.getElementById('hitlButtons').style.display = 'none';
}

async function submitFeedback(auth) {
  if (!currentPromptId) return;

  const responseText = document.getElementById('hitlResponse').value;
  const selectedObservation = document.getElementById('hitlObserveSelect').value;

  const btnDiv = document.getElementById('hitlButtons');
  btnDiv.style.opacity = '0.5';
  btnDiv.style.pointerEvents = 'none';

  try {
    const r = await fetch('/hitl/feedback', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        prompt_id: currentPromptId,
        response_text: responseText,
        selected_observation: selectedObservation,
        authorization: auth,
        authorized_by: 'scope-operator',
      }),
    });
    const j = await r.json();

    const resultDiv = document.getElementById('hitlResult');
    resultDiv.style.display = 'block';

    if (j.status === 'ok') {
      if (auth === 'approved') {
        resultDiv.innerHTML = '<div style="color:#44FF44;padding:6px;background:#1A3A1A;border-radius:4px;">✓ 已授权 — 参数可写入驱动</div>';
        if (j.authorized_actions && j.authorized_actions.length > 0) {
          let actHtml = '<div style="color:#CCC;margin-top:4px;">授权操作:</div>';
          j.authorized_actions.forEach(a => {
            const rec = a.recommendation || {};
            actHtml += '<div style="color:#AAAACC;font-size:9px;padding:2px;">' +
              (rec.action || '?') + ' ' + (rec.index || '?') + ' — ' + (rec.reason || '') +
              '</div>';
          });
          resultDiv.innerHTML += actHtml;
        }
      } else if (auth === 'rejected') {
        resultDiv.innerHTML = '<div style="color:#FF8844;padding:6px;background:#3A2A1A;border-radius:4px;">✗ 已拒绝 — 不会执行参数修改</div>';
      } else {
        // Show LLM refined diagnosis
        if (j.refined_annotations && j.refined_annotations.length > 0) {
          const a = j.refined_annotations[0];
          const isLLM = (a.message || '').startsWith('LLM 精化诊断');
          const bgColor = isLLM ? '#1A2A1E' : '#2A2A1E';
          const borderColor = isLLM ? '#2A5A4E' : '#4A4A2E';
          let html = '<div style="color:#FFCC44;padding:8px;background:' + bgColor + ';border:1px solid ' + borderColor + ';border-radius:4px;margin-bottom:4px;">';
          html += isLLM ? '🤖 LLM 精化诊断结果' : '📤 观察已提交 — 诊断结果';
          html += '</div>';
          html += '<div style="color:#CCC;font-size:10px;padding:4px;line-height:1.6;">' + a.message.replace(/\n/g, '<br>') + '</div>';
          if (a.category) {
            html += '<div style="color:#AAAACC;font-size:9px;padding:2px 4px;">分类: ' + a.category + ' | 严重度: ' + a.severity + '</div>';
          }
          resultDiv.innerHTML = html;
        } else {
          resultDiv.innerHTML = '<div style="color:#FFCC44;padding:6px;background:#2A2A1E;border-radius:4px;">📤 观察已提交</div>';
        }
      }
      // Update AI status
      document.getElementById('aiStatus').textContent = 'AI: ' + j.session_summary || '';
    } else {
      resultDiv.innerHTML = '<div style="color:#FF4444;">错误: ' + (j.error || '未知') + '</div>';
    }
  } catch(e) {
    document.getElementById('hitlResult').style.display = 'block';
    document.getElementById('hitlResult').innerHTML = '<div style="color:#FF4444;">连接失败: ' + e.message + '</div>';
  } finally {
    btnDiv.style.opacity = '1';
    btnDiv.style.pointerEvents = 'auto';
    currentPromptId = null;
  }
}

// Mode polling
function pollMode() {
  var xhr = new XMLHttpRequest();
  xhr.open('GET', '/mode', true);
  xhr.onload = function() {
    if (xhr.status !== 200) return;
    try {
      var j = JSON.parse(xhr.responseText);
      var badge = document.getElementById('modeBadge');
      if (!badge) return;
      if (j.mode === 'discover') {
        badge.textContent = '🔍 Discover';
        badge.style.background = '#1A3A1A';
        badge.style.color = '#44FF44';
        badge.style.border = '1px solid #2A5A2A';
      } else {
        badge.textContent = '● Sim';
        badge.style.background = '#3A2A1A';
        badge.style.color = '#FF8844';
        badge.style.border = '1px solid #5A3A2A';
      }
    } catch(e) {}
  };
  xhr.send();
}
setInterval(pollMode, 5000);
pollMode();

// Auto-poll HITL status every 5 seconds
setInterval(async () => {
  try {
    const r = await fetch('/hitl/status');
    const j = await r.json();
    if (j.available && j.pending > 0) {
      document.getElementById('aiStatus').textContent = 'AI: ' + j.pending + ' prompts pending';
      document.getElementById('aiStatus').style.color = '#FFCC44';
    }
  } catch(e) {}
}, 5000);
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
        elif path == "/mode":
            self._serve_mode()
        elif path == "/discover/status":
            self._serve_discover_status()
        elif path == "/export":
            self._serve_export_csv()
        elif path == "/export/annotations":
            self._serve_export_annotations()
        elif path == "/hitl/status":
            self._serve_hitl_status()
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        path = urlparse(self.path).path
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length) if content_length > 0 else b"{}"

        try:
            data = json.loads(body.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._send_json(400, {"error": "Invalid JSON"})
            return

        if path == "/hitl/analyze":
            self._handle_hitl_analyze(data)
        elif path == "/hitl/feedback":
            self._handle_hitl_feedback(data)
        elif path == "/discover/sim":
            self._handle_discover_sim(data)
        elif path == "/discover/exit":
            self._handle_discover_exit(data)
        else:
            self._send_json(404, {"error": "Not found"})

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

    def _serve_mode(self):
        """Return current scope mode (sim or discover)."""
        self._send_json(200, {
            "mode": _server_mode,
            "discovery_done": _discovery_done,
            "discovery_success": _discovery_success,
        })

    def _serve_discover_status(self):
        """Return discovery progress (step list)."""
        self._send_json(200, {
            "done": _discovery_done,
            "success": _discovery_success,
            "steps": _discovery_steps,
            "mode": _server_mode,
        })

    def _handle_discover_sim(self, data: dict):
        """User clicked 'Run in Sim Mode' — switch to sim."""
        global _server_mode
        _server_mode = "sim"
        self._send_json(200, {"mode": "sim", "status": "ok"})

    def _handle_discover_exit(self, data: dict):
        """User clicked 'Exit' — shut down the server (like Ctrl+C)."""
        self._send_json(200, {"status": "shutting down"})
        # Shutdown in a separate thread so the response can be sent first
        import threading as _th
        def _delayed_shutdown():
            import time as _t
            _t.sleep(0.5)
            engine.stop()
            print("\nServer stopped by user (Exit button).")
            import os as _os
            _os._exit(0)
        _th.Thread(target=_delayed_shutdown, daemon=True).start()

    def _serve_export_csv(self):
        """Generate CSV from scope data and return as downloadable file."""
        qs = parse_qs(urlparse(self.path).query)
        n = int(qs.get("n", [0])[0])  # 0 = all

        wf = engine.get_waveform(n if n > 0 else 60000)
        arr = np.array(wf.get("data", []))
        if arr.size == 0:
            self._send_json(400, {"error": "No data to export"})
            return

        # Build CSV in memory
        output = io.StringIO()
        import csv as csv_mod
        writer = csv_mod.writer(output)

        # Metadata header
        writer.writerow([f"# Generated: {time.strftime('%Y-%m-%dT%H:%M:%S')}"])
        writer.writerow([f"# Sample Rate: 1000 Hz"])
        writer.writerow([f"# Samples: {arr.shape[0]}"])
        writer.writerow(["#"])

        # Column headers
        ch_defs = [
            ("Position Actual", "pulses"),
            ("Velocity Actual", "rpm"),
            ("Current Actual", "%"),
            ("Torque Actual", "%"),
            ("Following Error", "pulses"),
            ("Digital Inputs", "bits"),
            ("Statusword", "hex"),
            ("Op Mode Display", "code"),
        ]
        headers = ["Timestamp (s)"] + [
            f"{name} ({unit})" for name, unit in ch_defs[:arr.shape[1]]
        ]
        writer.writerow(headers)

        # Data rows
        for i in range(arr.shape[0]):
            row = [f"{i / 1000.0:.6f}"]  # approximate timestamp
            for ch in range(arr.shape[1]):
                row.append(f"{arr[i, ch]:.6g}")
            writer.writerow(row)

        csv_bytes = output.getvalue().encode("utf-8")
        output.close()

        # Send as file download
        filename = time.strftime("scope_%Y%m%d_%H%M%S.csv")
        self.send_response(200)
        self.send_header("Content-Type", "text/csv; charset=utf-8")
        self.send_header("Content-Disposition",
                         f'attachment; filename="{filename}"')
        self.send_header("Content-Length", str(len(csv_bytes)))
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(csv_bytes)

    def _serve_export_annotations(self):
        """Export AI annotations as CSV."""
        pipeline = _get_ai_pipeline()
        if pipeline is None:
            self._send_json(503, {"error": "AI pipeline not available"})
            return

        try:
            annotations = getattr(pipeline, 'last_annotations', [])
        except Exception:
            annotations = []

        output = io.StringIO()
        import csv as csv_mod
        writer = csv_mod.writer(output)

        writer.writerow([f"# AI Annotations Export — {time.strftime('%Y-%m-%dT%H:%M:%S')}"])
        writer.writerow([f"# Total: {len(annotations)}"])
        writer.writerow(["#"])
        writer.writerow(["Timestamp (s)", "Channel", "Severity", "Category",
                         "Value", "Confidence", "Message", "Suggestion"])

        for ann in annotations:
            writer.writerow([
                f"{getattr(ann, 'timestamp', 0.0):.6f}",
                str(getattr(ann, 'channel', '')),
                str(getattr(ann, 'severity', 'info')),
                str(getattr(ann, 'category', '')),
                f"{getattr(ann, 'value', 0.0):.6g}",
                f"{getattr(ann, 'confidence', 0.0):.2f}",
                str(getattr(ann, 'message', '')),
                str(getattr(ann, 'suggestion', '')),
            ])

        csv_bytes = output.getvalue().encode("utf-8")
        output.close()

        filename = time.strftime("annotations_%Y%m%d_%H%M%S.csv")
        self.send_response(200)
        self.send_header("Content-Type", "text/csv; charset=utf-8")
        self.send_header("Content-Disposition",
                         f'attachment; filename="{filename}"')
        self.send_header("Content-Length", str(len(csv_bytes)))
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(csv_bytes)

    def _send_json(self, code: int, data: dict):
        """Send a JSON response."""
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))

    def _serve_hitl_status(self):
        """Return HITL status: pending prompts count and AI availability."""
        pipeline = _get_ai_pipeline()
        if pipeline is None:
            self._send_json(200, {"available": False, "pending": 0, "prompts": []})
            return

        prompts = pipeline.get_pending_prompts()
        self._send_json(200, {
            "available": True,
            "pending": len(prompts),
            "prompts": [p.to_dict() for p in prompts[-5:]],  # last 5
            "session_summary": pipeline.get_hitl_summary(),
        })

    def _handle_hitl_analyze(self, data: dict):
        """Run AI analysis on the latest buffer data and return HITL prompts."""
        pipeline = _get_ai_pipeline()
        if pipeline is None:
            self._send_json(503, {"error": "AI pipeline not available"})
            return

        try:
            # Get scope data
            wf = engine.get_waveform(6000)
            if not wf.get("data") or len(wf["data"]) < 100:
                self._send_json(200, {"annotations": [], "prompts": [], "message": "Not enough data"})
                return

            ch_names = [
                "Position", "Velocity", "Current", "Torque",
                "Foll.Err", "DIO", "Status", "OpMode",
            ]

            # Build buffer_stats from recent data
            arr = np.array(wf["data"])
            buffer_stats = {}
            for i, name in enumerate(ch_names):
                if i < arr.shape[1]:
                    col = arr[-2000:, i] if arr.shape[0] > 2000 else arr[:, i]
                    buffer_stats[name] = {
                        "mean": float(np.mean(col)),
                        "std": float(np.std(col)),
                        "min": float(np.min(col)),
                        "max": float(np.max(col)),
                        "rms": float(np.sqrt(np.mean(col ** 2))),
                        "peak_to_peak": float(np.max(col) - np.min(col)),
                    }

            # Run AI analysis on the most recent sample
            latest = arr[-1].tolist() if arr.shape[0] > 0 else [0] * 8
            annotations = pipeline.analyze(latest, ch_names, buffer_stats)

            # Generate HITL prompts
            prompts = pipeline.prompt_engineer(annotations)
            for p in prompts:
                _PENDING_PROMPTS[p.prompt_id] = p

            ann_list = []
            for a in annotations:
                ann_list.append({
                    "category": a.category,
                    "severity": a.severity,
                    "confidence": a.confidence,
                    "message": a.message,
                    "suggestion": a.suggestion,
                    "hitl_classification": a.hitl_classification,
                    "requires_authorization": a.requires_authorization,
                })

            self._send_json(200, {
                "annotations": ann_list,
                "prompts": [p.to_dict() for p in prompts],
                "pending_count": pipeline.hitl_gate.pending_count,
            })
        except Exception as e:
            self._send_json(500, {"error": f"Analysis failed: {e}"})

    def _handle_hitl_feedback(self, data: dict):
        """Receive engineer feedback and process it through the HITL gate."""
        pipeline = _get_ai_pipeline()
        if pipeline is None:
            self._send_json(503, {"error": "AI pipeline not available"})
            return

        try:
            prompt_id = data.get("prompt_id", "")
            if not prompt_id:
                self._send_json(400, {"error": "Missing prompt_id"})
                return

            feedback = EngineerFeedback(
                prompt_id=prompt_id,
                response_text=data.get("response_text", ""),
                media_paths=data.get("media_paths", []),
                selected_observation=data.get("selected_observation", ""),
                authorization=data.get("authorization", "pending"),
                authorized_by=data.get("authorized_by", "web-scope-user"),
                notes=data.get("notes", ""),
            )

            refined = pipeline.process_engineer_feedback(prompt_id, feedback)

            # Get any newly authorized actions
            actions = pipeline.get_authorized_actions()
            action_list = [a.to_dict() for a in actions[-5:]]

            self._send_json(200, {
                "status": "ok",
                "authorization": feedback.authorization,
                "refined_annotations": [
                    {
                        "category": a.category,
                        "severity": a.severity,
                        "message": a.message,
                    }
                    for a in refined
                ],
                "authorized_actions": action_list,
                "session_summary": pipeline.get_hitl_summary(),
            })
        except Exception as e:
            self._send_json(500, {"error": f"Feedback processing failed: {e}"})

    def _serve_export(self):
        import csv, io
        wf = engine.get_waveform(0)  # all data
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["Timestamp (s)"] + [c["name"] for c in CHANNELS])
        for i, row in enumerate(wf["data"]):
            writer.writerow([f"{i/1000.0:.6f}"] + [f"{v:.6g}" for v in row])

        self.send_response(200)
        self.send_header("Content-Type", "text/csv; charset=utf-8")
        self.send_header("Content-Disposition",
                        f'attachment; filename="scope_{int(time.time())}.csv"')
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(buf.getvalue().encode("utf-8"))

    def log_message(self, format, *args):
        pass  # quiet

def main():
    # ── Run hardware discovery at startup (non-blocking in background) ──
    import threading as _th
    _discover_thread = _th.Thread(target=run_discovery, daemon=True)
    _discover_thread.start()

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
        pass
    finally:
        # Always clean up
        engine.stop()
        server.shutdown()
        # Multi-channel shutdown message — terminal, file, stderr
        shutdown_msg = "Server stopped. Port closed."
        try:
            sys.stdout.write(f"\n{shutdown_msg}\n")
            sys.stdout.flush()
        except Exception:
            pass
        try:
            sys.stderr.write(f"\n{shutdown_msg}\n")
            sys.stderr.flush()
        except Exception:
            pass
        try:
            with open(here / "SERVER_IS_RUNNING.txt", "w") as f:
                f.write("SERVER STOPPED\n")
        except Exception:
            pass

if __name__ == "__main__":
    main()
