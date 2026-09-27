"""Local analysis server: truncated uploads are rejected before any analysis and the temporary copy is deleted."""

from __future__ import annotations

import http.client
import json
import socket
import tempfile
import threading
from http.server import ThreadingHTTPServer

import pytest

from prsguard import pipeline, server


@pytest.fixture
def live_server(monkeypatch, tmp_path):
    work = tmp_path / "upload_work"
    monkeypatch.setattr(tempfile, "mkdtemp", lambda prefix="": (work.mkdir(), str(work))[1])
    monkeypatch.setattr(pipeline, "run", lambda cfg: pytest.fail("the pipeline must not run on a partial upload"))
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield httpd.server_address[1], work
    httpd.shutdown()
    httpd.server_close()


def _raw_post(port: int, declared: int, body: bytes) -> tuple[int, dict]:
    with socket.create_connection(("127.0.0.1", port), timeout=30) as s:
        head = (f"POST /api/analyze?trait=breast%20cancer&sex=female HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\n"
                f"X-Filename: genome.vcf\r\nContent-Length: {declared}\r\nConnection: close\r\n\r\n")
        s.sendall(head.encode() + body)
        s.shutdown(socket.SHUT_WR)  # the client stops before sending the declared number of bytes
        data = b""
        while chunk := s.recv(65536):
            data += chunk
    status = int(data.split(b" ", 2)[1])
    return status, json.loads(data.split(b"\r\n\r\n", 1)[1] or b"{}")


def test_truncated_upload_is_rejected_and_deleted(live_server):
    port, work = live_server
    status, body = _raw_post(port, declared=5000, body=b"##fileformat=VCFv4.2\n")
    assert status == 400 and "incomplete" in body["error"] and "nothing was analysed" in body["error"]
    assert not work.exists()


def test_health_and_host_guard(live_server):
    port, _ = live_server
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    c.request("GET", "/api/health")
    assert c.getresponse().status == 200
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    c.request("GET", "/api/health", headers={"Host": "evil.example"})
    assert c.getresponse().status == 403
