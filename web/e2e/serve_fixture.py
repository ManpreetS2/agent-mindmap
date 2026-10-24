"""Serve web/dist with /activity.json mapped to one fixture file (visual QA only; localhost).

Usage: python web/e2e/serve_fixture.py FIXTURE_JSON PORT   (run from the repo root)
"""
import http.server
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
FIXTURE, PORT = sys.argv[1], int(sys.argv[2])


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=os.path.join(ROOT, "web", "dist"), **kwargs)

    def do_GET(self):
        if self.path.split("?")[0] == "/activity.json":
            with open(FIXTURE, "rb") as fh:
                body = fh.read()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        return super().do_GET()

    def log_message(self, *args):
        pass


http.server.ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
