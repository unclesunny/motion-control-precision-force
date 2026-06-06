# Getting Started — Motion Control Precision Force

## 30-Second Quickstart

```bash
git clone https://github.com/wangp/motion-control-precision-force.git
cd motion-control-precision-force
pip install numpy              # required
python run_scope.py            # tkinter scope (zero other deps)
```

You should see an 8-channel oscilloscope window with synthetic servo waveforms.

## What You Can Do Without Hardware

| Command | What It Does | Needs |
|---------|-------------|-------|
| `python run_scope.py` | Auto-detect best frontend, launch oscilloscope | numpy |
| `python run_scope.py --tk` | Force tkinter frontend (143 FPS) | numpy |
| `python run_scope.py --qt` | Force pyqtgraph frontend (381 FPS) | numpy + PySide6 + pyqtgraph |
| `python run_scope.py --web` | Web server, open browser | numpy |
| `python run_scope.py --demo` | AI analysis simulation | numpy |
| `python demo_ai_scope.py` | Full AI demo: anomaly detection + tuning recommendations | numpy |
| `python -m pytest 06-ai-analyzer/tests/ tests/ -v` | Run all 75 tests | numpy + pytest |

## Install Everything (Full Desktop Experience)

```bash
pip install -r requirements.txt     # numpy + PySide6 + pyqtgraph
python run_scope.py                 # automatically picks pyqtgraph (381 FPS)
```

## Hardware Required (Phase 1.5)

| Item | Purpose | Approx. Cost |
|------|---------|-------------|
| Delta ASDA-A3-E servo drive + motor | EtherCAT PDO communication | ~$800 |
| Intel I210 / I226 NIC | EtherCAT real-time | ~$100 |
| Force sensor (0-10V analog) | Force control loop | ~$500 |

## Project Layout

```
motion-control-precision-force/
├── run_scope.py              <- One-click launcher (start here)
├── demo_ai_scope.py          <- AI analysis demo
├── GETTING_STARTED.md        <- You are here
├── README.md                 <- Full project overview
├── ROADMAP.md                <- Development roadmap
├── CONSTITUTION.md           <- Project governance
│
├── 04-oscilloscope/src/      <- Oscilloscope (3 frontends)
│   ├── scope_tk.py           <- tkinter: zero-dependency, 143 FPS
│   ├── scope_app.py          <- pyqtgraph: GPU-accelerated, 381 FPS
│   └── scope_server.py       <- Web HTML5 Canvas: browser, 77 FPS
│
├── 05-servo-params/          <- 12-brand servo parameter library
│   └── brand_loader.py       <- Cross-brand CoE object query
│
├── 06-ai-analyzer/           <- AI analysis engine
│   └── ai_analyzer/          <- Python package
│
├── 07-codesys-fb/            <- CODESYS function blocks
└── tests/                    <- Integration tests
```

## Need Help?

- **AI engine docs**: `06-ai-analyzer/README.md`
- **Developer guide**: `08-docs/developer-guide/README.md`
- **Servo brand list**: `python 05-servo-params/brand_loader.py list`
- **Run tests**: `python -m pytest 06-ai-analyzer/tests/ tests/ -v`
