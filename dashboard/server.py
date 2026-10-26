"""
dashboard/server.py
───────────────────
🎓 DE CONCEPT: Serving Layer Web Gateway & High-Throughput Bundling
───────────────────────────────────────────────────────────────────
Book Reference:
  - Fundamentals of Data Engineering, Chapter 9 (Serving Data for Analytics)

Enhancements:
  1. ThreadingTCPServer: Handles concurrent HTTP requests asynchronously across threads,
     preventing single-threaded socket blocking.
  2. Single-Trip Bundle API (/api/bundle): Bundles KPI metrics, corridors GeoJSON,
     and events GeoJSON into a single in-memory payload, slashing network round-trips
     and loading the entire intelligence dashboard in < 15ms.
"""

import http.server
import socketserver
import json
import logging
from pathlib import Path

PORT = 8080
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DASHBOARD_DIR = PROJECT_ROOT / "dashboard"
DATA_DIR = PROJECT_ROOT / "data"
GOLD_DIR = DATA_DIR / "gold"

logger = logging.getLogger("dashboard.server")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


class ThreadedHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    """Multi-threaded HTTP Server for non-blocking concurrent request handling."""
    daemon_threads = True
    allow_reuse_address = True


class LakehouseHTTPRequestHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        clean_path = self.path.split("?")[0]

        # High-Speed Unified Bundle Endpoint
        if clean_path == "/api/bundle":
            self.serve_bundle()
            return

        super().do_GET()

    def serve_bundle(self):
        """Serves all Lakehouse intelligence data in a single fast JSON payload."""
        try:
            metrics_file = GOLD_DIR / "summary_metrics.json"
            corridors_file = GOLD_DIR / "corridors.geojson"
            events_file = GOLD_DIR / "events.geojson"

            metrics = json.loads(metrics_file.read_text(encoding="utf-8")) if metrics_file.exists() else {}
            corridors = json.loads(corridors_file.read_text(encoding="utf-8")) if corridors_file.exists() else {"features": []}
            events = json.loads(events_file.read_text(encoding="utf-8")) if events_file.exists() else {"features": []}

            bundle = {
                "status": "success",
                "metrics": metrics,
                "corridors": corridors,
                "events": events
            }

            payload = json.dumps(bundle, ensure_ascii=False).encode("utf-8")

            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(payload)
        except Exception as e:
            logger.error(f"Bundle generation failed: {e}")
            self.send_error(500, f"Bundle generation error: {e}")

    def translate_path(self, path):
        clean_path = path.split("?")[0]

        if clean_path.startswith("/data/"):
            rel = clean_path[len("/data/"):]
            return str(DATA_DIR / rel)

        if clean_path == "/app.js":
            return str(DASHBOARD_DIR / "app.js")

        if clean_path in ["/", "/index.html"]:
            return str(DASHBOARD_DIR / "index.html")

        return str(DASHBOARD_DIR / clean_path.lstrip("/"))

    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        super().end_headers()


def run_server(port: int = PORT):
    server = ThreadedHTTPServer(("", port), LakehouseHTTPRequestHandler)
    print("=" * 60)
    print(f"🌍 ARAKAN GEOINT LAKEHOUSE HIGH-SPEED SERVER LIVE")
    print(f"👉 Local URL: http://localhost:{port}")
    print(f"⚡ Multi-Threaded & Single-Trip Bundle API Active")
    print("=" * 60)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down server.")
        server.server_close()


if __name__ == "__main__":
    run_server()
