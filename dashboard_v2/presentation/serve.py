"""
Servidor HTTP local para el dashboard v2.

Necesario porque el HTML hace fetch a JSONs locales, y browsers bloquean file://
loads por CORS. Este server sirve el repo root en http://localhost:8765.

Uso:
    python -m dashboard_v2.presentation.serve
    -> abrir http://localhost:8765/dashboard_v2/presentation/index.html
"""
from __future__ import annotations
import http.server
import socketserver
import webbrowser
from pathlib import Path

PORT = 8765
ROOT = Path(__file__).resolve().parents[2]  # big-dashboard/

class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def log_message(self, format, *args):
        # Silenciar logs excepto errores
        if args and str(args[1]).startswith(("4", "5")):
            super().log_message(format, *args)


def main():
    url = f"http://localhost:{PORT}/dashboard_v2/presentation/index.html"
    print(f"Serving {ROOT} at http://localhost:{PORT}")
    print(f"Dashboard: {url}")
    print(f"Ctrl+C para parar")

    with socketserver.TCPServer(("", PORT), Handler) as httpd:
        try:
            webbrowser.open(url)
        except Exception:
            pass
        httpd.serve_forever()


if __name__ == "__main__":
    main()
