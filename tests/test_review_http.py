"""Tests for scripts/review_http.py: el HTTP común de la pipeline de review.

Run: python3 -m unittest tests/test_review_http.py
stdlib only. La API local es un http.server: sin red ni datos reales. Se prueba la
regla que los tres scripts comparten desde el seguimiento D del arquitecto
(INFRA-332/333): 401/403 = AuthError, 404 con ok404 = None, el resto = Degraded, y
el redirect del zip del artefacto se sigue SIN el token.
"""

from __future__ import annotations

import http.server
import importlib.util
import json
import sys
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts/review_http.py"
spec = importlib.util.spec_from_file_location("review_http", SCRIPT)
rh = importlib.util.module_from_spec(spec)
sys.modules["review_http"] = rh
spec.loader.exec_module(rh)


class _Handler(http.server.BaseHTTPRequestHandler):
    def _reply(self, code, body=b"{}", extra=None):
        self.server.calls.append((self.command, self.path, self.headers.get("Authorization"),
                                  self.rfile.read(int(self.headers.get("Content-Length", 0)))
                                  if self.command == "POST" else b""))
        self.send_response(code)
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self._reply(self.server.code)

    def do_POST(self):
        self._reply(201 if self.server.code == 200 else self.server.code)

    def do_DELETE(self):
        self._reply(self.server.code)

    def do_PUT(self):  # el redirect del zip: PUT no; el destino del 302 se pide con GET
        self._reply(200)

    def log_message(self, *a):
        pass


class _Redirect(_Handler):
    """GET a /zip responde 302 a /blob, y /blob contesta los bytes del zip."""

    def do_GET(self):
        if self.path.endswith("/zip"):
            self.server.calls.append(("GET", self.path, self.headers.get("Authorization"), b""))
            self.send_response(302)
            self.send_header("Location", f"http://127.0.0.1:{self.server.server_port}/blob")
            self.end_headers()
            return
        self.server.calls.append(("GET", self.path, self.headers.get("Authorization"), b""))
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ZIPBYTES")


class ReviewHttp(unittest.TestCase):
    def server(self, handler=_Handler, code=200):
        srv = http.server.HTTPServer(("127.0.0.1", 0), handler)
        srv.calls, srv.code = [], code
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.shutdown)
        self.addCleanup(srv.server_close)
        return srv, f"http://127.0.0.1:{srv.server_port}"

    def test_200_json_and_headers(self):
        srv, url = self.server()
        out = rh.request(f"{url}/x", rh.github_headers("tok"), source="github")
        assert out == {}
        cmd, path, auth, body = srv.calls[0]
        assert (cmd, path) == ("GET", "/x") and auth == "Bearer tok" and body == b""

    def test_post_body_and_content_type(self):
        srv, url = self.server()
        rh.request(url, {"Accept": "application/json"}, body={"a": 1}, source="brain")
        cmd, _, _, body = srv.calls[0]
        assert cmd == "POST" and json.loads(body) == {"a": 1}

    def test_401_and_403_are_auth_error_with_source_and_code(self):
        for code in (401, 403):
            srv, url = self.server(code=code)
            with self.subTest(code=code):
                try:
                    rh.request(url, {}, source="brain")
                    self.fail("debía subir AuthError")
                except rh.AuthError as exc:
                    assert exc.source == "brain" and exc.code == code
                    assert "brain respondió HTTP" in str(exc)

    def test_other_http_is_degraded_with_code(self):
        srv, url = self.server(code=502)
        with self.assertRaises(rh.Degraded) as cm:
            rh.request(url, {}, source="github")
        assert cm.exception.code == 502 and "github: HTTP 502" in str(cm.exception)

    def test_404_ok404_returns_none_plain_404_degrades(self):
        srv, url = self.server(code=404)
        assert rh.request(url, {}, ok404=True, source="github") is None
        with self.assertRaises(rh.Degraded):
            rh.request(url, {}, source="github")

    def test_200_empty_body_is_degraded_204_is_none(self):
        # un 200 con cuerpo vacío es una API respondiendo mal: Degraded (como antes de
        # extraer el cliente). El único cuerpo vacío legítimo es el 204 de un DELETE.
        class _Empty(_Handler):
            def do_GET(self):
                self.server.calls.append(("GET", self.path, None, b""))
                self.send_response(self.server.status)
                self.end_headers()

        for status, expect_none in ((200, False), (204, True)):
            with self.subTest(status=status):
                srv, url = self.server(_Empty)
                srv.status = status
                if expect_none:
                    assert rh.request(url, {}, source="github") is None
                else:
                    with self.assertRaises(rh.Degraded):
                        rh.request(url, {}, source="github")

    def test_connection_refused_is_degraded_not_auth(self):
        with self.assertRaises(rh.Degraded) as cm:
            rh.request("http://127.0.0.1:1/x", {}, source="brain")
        assert cm.exception.code is None

    def test_raw_redirect_follows_without_the_token(self):
        srv, url = self.server(_Redirect)
        data = rh.request(f"{url}/zip", rh.github_headers("sekret"), raw=True, source="GitHub")
        assert data == b"ZIPBYTES"
        assert srv.calls[0][:2] == ("GET", "/zip")
        assert srv.calls[1][2] is None  # /blob no ve el Authorization de GitHub

    def test_github_headers_shape(self):
        h = rh.github_headers("t")
        assert h["Authorization"] == "Bearer t"
        assert h["X-GitHub-Api-Version"] == "2022-11-28"
        assert h["Accept"] == "application/vnd.github+json"


if __name__ == "__main__":
    unittest.main()
