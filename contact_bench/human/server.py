"""Localhost HTTP server for the play page (stdlib only).

* Binds 127.0.0.1 only.  Nothing here is deployed to the public site, so no
  visitor can trigger model calls.
* Every /api/ request needs the random session token (sent by the page in the
  ``X-Play-Token`` header; the token travels in the URL fragment, which
  browsers never send to servers or put in Referer headers).  A custom header
  also means a cross-site page cannot make these requests without a CORS
  preflight, which this server never approves.
* The Host header must name the loopback address (DNS-rebinding defence).
"""

from __future__ import annotations

import hmac
import json
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .session import HumanSession, SubmitError

STATIC = Path(__file__).resolve().parents[1] / "site" / "static"
FILES = {
    "/": (STATIC / "play" / "index.html", "text/html; charset=utf-8"),
    "/play.js": (STATIC / "play" / "play.js", "text/javascript; charset=utf-8"),
    "/play.css": (STATIC / "play" / "play.css", "text/css; charset=utf-8"),
    "/style.css": (STATIC / "style.css", "text/css; charset=utf-8"),
}
MAX_BODY = 256 * 1024
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
    "Cache-Control": "no-store",
}


def make_handler(session: HumanSession, token: str, port_ref: list[int]):
    class Handler(BaseHTTPRequestHandler):
        server_version = "contact-bench-play"
        sys_version = ""

        def log_message(self, fmt, *args):  # keep the terminal quiet
            pass

        def _send(self, code: int, body: bytes, ctype: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            for k, v in SECURITY_HEADERS.items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def _json(self, code: int, obj) -> None:
            self._send(code, json.dumps(obj).encode(), "application/json")

        def _host_ok(self) -> bool:
            host = (self.headers.get("Host") or "").lower()
            return host in {f"127.0.0.1:{port_ref[0]}", f"localhost:{port_ref[0]}"}

        def _api_ok(self) -> bool:
            got = self.headers.get("X-Play-Token") or ""
            return hmac.compare_digest(got.encode(), token.encode())

        def do_GET(self):
            if not self._host_ok():
                return self._json(403, {"error": "bad host"})
            path = self.path.split("?", 1)[0]
            if path in FILES:
                p, ctype = FILES[path]
                return self._send(200, p.read_bytes(), ctype)
            if path == "/api/state":
                if not self._api_ok():
                    return self._json(403, {"error": "missing or wrong session token"})
                return self._json(200, session.state())
            return self._json(404, {"error": "not found"})

        def do_POST(self):
            if not self._host_ok():
                return self._json(403, {"error": "bad host"})
            if not self._api_ok():
                return self._json(403, {"error": "missing or wrong session token"})
            if (self.headers.get("Content-Type") or "").split(";")[0].strip() != "application/json":
                return self._json(415, {"error": "expected application/json"})
            try:
                n = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                n = -1
            if n < 0 or n > MAX_BODY:
                return self._json(413, {"error": "request too large"})
            try:
                body = json.loads(self.rfile.read(n) or b"{}")
            except (json.JSONDecodeError, UnicodeDecodeError):
                return self._json(400, {"error": "invalid JSON"})
            if not isinstance(body, dict):
                return self._json(400, {"error": "expected a JSON object"})
            path = self.path.split("?", 1)[0]
            try:
                if path == "/api/lookup":
                    return self._json(200, session.lookup(str(body.get("decision_id")), str(body.get("name")),
                                                          body.get("args")))
                if path == "/api/check":
                    reason = session.check(str(body.get("decision_id")), body.get("action"))
                    return self._json(200, {"ok": reason is None, "reason": reason})
                if path == "/api/decide":
                    return self._json(200, session.submit(str(body.get("decision_id")), body.get("action"),
                                                          force=bool(body.get("force"))))
                if path == "/api/stop":
                    session.stop()
                    return self._json(200, {"stopped": True})
            except SubmitError as e:
                return self._json(409, {"error": str(e)})
            return self._json(404, {"error": "not found"})

        def do_OPTIONS(self):  # never approve cross-origin preflights
            self._json(403, {"error": "cross-origin requests are not allowed"})

    return Handler


class PlayServer:
    def __init__(self, session: HumanSession, port: int = 0, token: str | None = None):
        self.token = token or secrets.token_urlsafe(24)
        self._port = [port]
        self.httpd = ThreadingHTTPServer(("127.0.0.1", port), make_handler(session, self.token, self._port))
        self.httpd.daemon_threads = True
        self._port[0] = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, name="contact-bench-play", daemon=True)

    @property
    def port(self) -> int:
        return self._port[0]

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/#{self.token}"

    def start(self) -> "PlayServer":
        self.thread.start()
        return self

    def close(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
