"""
dashboard/server.py
───────────────────
🎓 DE CONCEPT: Serving Layer Web Gateway
────────────────────────────────────────
Book Reference:
  - Fundamentals of Data Engineering, Chapter 9 (Serving Data)

A lightweight web server to serve the GEOINT Lakehouse dashboard
and its underlying Gold tier datasets (GeoJSON, JSON metrics, CSVs).
"""

import http.server
import socketserver
import os
from pathlib import Path

PORT = 8080
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DASHBOARD_DIR = PROJECT_ROOT / "dashboard"
DATA_DIR = PROJECT_ROOT / "data"

class LakehouseHTTPRequestHandler(http.server.SimpleHTTPRequestHandler):
    def translate_path(self, path):
        # Strip query parameters
        clean_path = path.split("?")[0]
        
        # Route /data/ to project data directory
        if clean_path.startswith("/data/"):
            rel = clean_path[len("/data/"):]
            return str(DATA_DIR / rel)
        
        # Route /app.js to dashboard/app.js
        if clean_path == "/app.js":
            return str(DASHBOARD_DIR / "app.js")

        # Default route / to dashboard/index.html
        if clean_path == "/" or clean_path == "/index.html":
            return str(DASHBOARD_DIR / "index.html")

        # Fallback to dashboard directory
        return str(DASHBOARD_DIR / clean_path.lstrip("/"))

    def end_headers(self):
        # Enable CORS for local development
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        super().end_headers()


def run_server(port: int = PORT):
    with socketserver.TCPServer(("", port), LakehouseHTTPRequestHandler) as httpd:
        print("=" * 60)
        print(f"🌍 ARAKAN GEOINT LAKEHOUSE DASHBOARD LIVE")
        print(f"👉 Local URL: http://localhost:{port}")
        print("=" * 60)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nShutting down server.")


if __name__ == "__main__":
    run_server()
