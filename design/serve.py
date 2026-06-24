#!/usr/bin/env python3
"""Kleiner Dev-Server fuer die Design-Exploration (Ordner design/).

Start:  python design/serve.py        (oder via VS-Code-Task "Design: HTML-Server")
URL:    http://localhost:4321

- liefert ausschliesslich den design/-Ordner aus
- sendet No-Cache-Header, damit Aenderungen sofort sichtbar sind (nur F5)
- Port via Umgebungsvariable DESIGN_PORT ueberschreibbar
"""
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import os
import sys

PORT = int(os.environ.get("DESIGN_PORT", "4321"))
ROOT = Path(__file__).resolve().parent


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store, max-age=0")
        self.send_header("Pragma", "no-cache")
        super().end_headers()

    def log_message(self, fmt, *args):
        sys.stderr.write("  " + (fmt % args) + "\n")


if __name__ == "__main__":
    httpd = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print("\n  Milon Design-Server  ->  http://localhost:%d" % PORT)
    print("  (Strg+C zum Beenden)\n")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n  beendet.")
