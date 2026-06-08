"""
One-Click Oscilloscope Launcher.

Auto-detects available environment and launches the best frontend:
  1. pyqtgraph (381 FPS) — if PySide6 is installed
  2. tkinter (143 FPS) — Python stdlib, always available
  3. Web server (77 FPS) — headless / remote access

Usage:
    python run_scope.py              # auto-detect best
    python run_scope.py --tk         # force tkinter
    python run_scope.py --web        # force web server
    python run_scope.py --qt         # force pyqtgraph
    python run_scope.py --demo       # demo mode (AI pipeline + synthetic data)
"""

import subprocess
import sys
from pathlib import Path

# Fix Windows GBK encoding
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PROJECT = Path(__file__).resolve().parent
SCOPE_DIR = PROJECT / "04-oscilloscope" / "src"


def check_qt() -> bool:
    """Check if PySide6 + pyqtgraph are importable."""
    try:
        import PySide6  # noqa: F401
        import pyqtgraph  # noqa: F401
        return True
    except ImportError:
        return False


def check_ai() -> bool:
    """Check if AI analyzer module is available."""
    ai_dir = PROJECT / "06-ai-analyzer"
    return ai_dir.exists() and (ai_dir / "ai_analyzer" / "__init__.py").exists()


def _run_with_clean_exit(cmd, stop_msg="Press Ctrl+C to stop"):
    """Run a subprocess and handle Ctrl+C gracefully — terminates the child too."""
    print(f"  ({stop_msg})")
    # Unbuffered: ensure child stdout/stderr go directly to the terminal
    env = {**__import__("os").environ, "PYTHONUNBUFFERED": "1"}
    proc = subprocess.Popen(cmd, env=env)
    try:
        return proc.wait()
    except KeyboardInterrupt:
        print("\nShutting down...")
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        return 0


def launch_tk():
    """Launch tkinter oscilloscope."""
    print("→ Launching tkinter scope (143 FPS, 0 deps)")
    return _run_with_clean_exit([sys.executable, str(SCOPE_DIR / "scope_tk.py")])


def launch_qt():
    """Launch pyqtgraph oscilloscope."""
    print("→ Launching pyqtgraph scope (381 FPS, GPU-accelerated)")
    return _run_with_clean_exit(
        [sys.executable, str(SCOPE_DIR / "scope_app.py")],
        "Close the window to stop")


def launch_web():
    """Launch web oscilloscope server."""
    print("→ Launching Web scope (http://localhost:8888)")
    return _run_with_clean_exit([sys.executable, str(SCOPE_DIR / "scope_server.py")])


def launch_demo():
    """Launch AI simulation demo."""
    script = PROJECT / "demo_ai_scope.py"
    if script.exists():
        print("→ Launching AI demo")
        return _run_with_clean_exit([sys.executable, str(script)])
    else:
        print("Demo script not found.")
        return 1


def print_env():
    """Print environment diagnostics."""
    print("=" * 50)
    print("  Delta A3 Oscilloscope — Environment Check")
    print("=" * 50)

    qt_ok = check_qt()
    ai_ok = check_ai()

    print(f"  PySide6 + pyqtgraph : {'✓ available (381 FPS)' if qt_ok else '✗ not installed'}")
    print(f"  tkinter             : ✓ always available (143 FPS)")
    print(f"  Web server          : ✓ always available (77 FPS)")
    print(f"  AI analyzer         : {'✓ ready' if ai_ok else '✗ not found'}")
    print(f"  Python              : {sys.version.split()[0]}")
    print("-" * 50)

    if qt_ok:
        print("  Best frontend: pyqtgraph (GPU-accelerated)")
        return "qt"
    else:
        print("  Best frontend: tkinter (zero dependencies)")
        return "tk"


def main():
    args = set(sys.argv[1:])

    if "--demo" in args:
        launch_demo()
        return

    if "--env" in args or "--check" in args:
        print_env()
        return

    # Check for numpy
    try:
        import numpy  # noqa: F401
    except ImportError:
        print("ERROR: numpy is required. Install it first:")
        print("  pip install numpy")
        print("Then run: python run_scope.py")
        return

    # Print environment info
    best = print_env()

    # Force specific frontend
    if "--tk" in args:
        launch_tk()
    elif "--web" in args:
        launch_web()
    elif "--qt" in args:
        if check_qt():
            launch_qt()
        else:
            print("PySide6 not installed. Falling back to tkinter.")
            launch_tk()
    else:
        # Auto-select best
        if best == "qt":
            launch_qt()
        else:
            launch_tk()


if __name__ == "__main__":
    main()
