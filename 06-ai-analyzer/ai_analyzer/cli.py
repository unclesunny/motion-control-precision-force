"""
CLI entry point for pip-installed servo command.

This thin wrapper ensures servo_cli.py is importable regardless of
the current working directory, then delegates to its main() function.

Usage (after pip install -e .):
    servo                    # REPL
    servo -c "status"        # single command
    servo --axes X,Y,Z       # multi-axis
"""

import sys
from pathlib import Path

# Ensure the project root (06-ai-analyzer/) is on sys.path
# so that `import servo_cli` works from anywhere
_parent = Path(__file__).resolve().parent  # ai_analyzer/
_project = _parent.parent                  # 06-ai-analyzer/
if str(_project) not in sys.path:
    sys.path.insert(0, str(_project))

from servo_cli import main


if __name__ == "__main__":
    main()
