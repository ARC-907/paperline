"""Entry point: `python -m paperline_ui` starts the UI server.

Defaults: host 127.0.0.1, port 8765 (chosen so it doesn't clash with
common dev ports — Datasette 8001, Jupyter 8888, Vite 5173, etc.).

Override with env vars:
    PAPERLINE_UI_HOST  (default 127.0.0.1)
    PAPERLINE_UI_PORT  (default 8765)
    PAPERLINE_PROJECT_ROOT  (default current working dir)
"""
from __future__ import annotations

import os
import sys


def main() -> int:
    try:
        import uvicorn
    except ImportError:
        sys.stderr.write(
            "paperline_ui requires uvicorn + fastapi + jinja2 + python-multipart.\n"
            "Install with one of:\n"
            "  pip install fastapi uvicorn 'jinja2>=3' python-multipart\n"
            "  pip install -e .[ui]  (if pyproject ui extras are defined)\n"
        )
        return 1

    host = os.environ.get("PAPERLINE_UI_HOST", "127.0.0.1")
    port = int(os.environ.get("PAPERLINE_UI_PORT", "8765"))

    sys.stdout.write(f"Paperline UI — http://{host}:{port}\n")
    sys.stdout.write(f"Project root: {os.environ.get('PAPERLINE_PROJECT_ROOT', os.getcwd())}\n")

    uvicorn.run("paperline_ui.app:app", host=host, port=port, reload=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
