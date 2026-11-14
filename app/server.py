"""Dependency-free HTTP endpoint for the isolated GitOps lab."""

from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path


def make_handler(version):
    if version not in ("v1", "v2"):
        raise ValueError("release must be v1 or v2")

    class Handler(BaseHTTPRequestHandler):
        server_version = "gitops-lab"
        sys_version = ""

        def respond(self, head=False):
            if self.path == "/":
                status, body = 200, f"gitops-lab {version}\n".encode()
            elif self.path in ("/readyz", "/healthz"):
                status, body = 200, b"ok\n"
            else:
                status, body = 404, b"not found\n"
            self.send_response(status)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if not head:
                self.wfile.write(body)

        def do_GET(self):
            self.respond()

        def do_HEAD(self):
            self.respond(head=True)

    return Handler


if __name__ == "__main__":
    version = Path(__file__).with_name("version.txt").read_text().strip()
    with HTTPServer(("0.0.0.0", 8080), make_handler(version)) as server:
        server.serve_forever()
