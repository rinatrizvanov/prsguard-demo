"""Local-only analysis server for the PRSGuard web interface.

    prsguard serve [--port 8765]

Binds to 127.0.0.1 only and rejects requests whose Host header is not a loopback name (DNS-rebinding guard).
An uploaded genotype file is written to a private temporary directory, analysed on this machine, and deleted
when the response is sent. It is never forwarded: the only outbound requests are trait text and PGS IDs to the
PGS Catalog (and nothing at all for the bundled breast-cancer demo, which replays the committed snapshot).

Endpoints
  GET  /api/health
  GET  /api/traits?q=<text>          PGS Catalog trait search (labels only)
  POST /api/analyze?trait=&sex=&build=   body: the genotype file; header X-Filename: original file name
"""

from __future__ import annotations

import json
import re
import shutil
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import prsguard
from prsguard import catalog, router
from prsguard.cli import DEMO_CANDIDATES, DEMO_LITERATURE

MAX_UPLOAD = 300 * 1024 * 1024
ALLOWED_SUFFIXES = (".txt", ".txt.gz", ".csv", ".tsv", ".vcf", ".vcf.gz")
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "[::1]"}
DEFAULT_ORIGINS = {"http://localhost:3000", "http://127.0.0.1:3000", "https://rinatrizvanov.github.io"}


def _demo_set_applies(trait: str, sex: str | None, build: str | None) -> bool:
    if not DEMO_CANDIDATES.exists():
        return False
    cs = json.loads(DEMO_CANDIDATES.read_text())
    return (router._norm(cs["trait"]["query"]) == router._norm(trait) and cs["options"]["sex"] == sex
            and build in (None, "GRCh37"))


class Handler(BaseHTTPRequestHandler):
    server_version = f"PRSGuard/{prsguard.__version__}"
    origins: set[str] = DEFAULT_ORIGINS

    def _host_ok(self) -> bool:
        host = (self.headers.get("Host") or "").rsplit(":", 1)[0]
        return host in LOOPBACK_HOSTS

    def _send(self, code: int, body: dict) -> None:
        data = json.dumps(body).encode()
        self.send_response(code)
        origin = self.headers.get("Origin")
        if origin in self.origins:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self):  # noqa: N802
        self.send_response(204)
        origin = self.headers.get("Origin")
        if origin in self.origins:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Filename")
            if self.headers.get("Access-Control-Request-Private-Network") == "true":
                self.send_header("Access-Control-Allow-Private-Network", "true")
            self.send_header("Access-Control-Max-Age", "600")
        self.end_headers()

    def do_GET(self):  # noqa: N802
        if not self._host_ok():
            return self._send(403, {"error": "non-loopback Host header"})
        url = urlparse(self.path)
        if url.path == "/api/health":
            return self._send(200, {"ok": True, "version": prsguard.__version__, "mode": "local"})
        if url.path == "/api/traits":
            q = (parse_qs(url.query).get("q") or [""])[0].strip()
            if not 2 <= len(q) <= 100:
                return self._send(400, {"error": "query must be 2-100 characters"})
            try:
                resp = catalog.LiveCatalogSource().fetch("trait/search", {"term": q, "limit": 20}, trait_id=q)
                hits = [{"id": r.get("id"), "label": r.get("label")} for r in (resp.json() or {}).get("results", [])]
            except catalog.MetadataUnavailable as exc:
                return self._send(502, {"error": str(exc)})
            return self._send(200, {"query": q, "results": hits})
        return self._send(404, {"error": "not found"})

    def do_POST(self):  # noqa: N802
        if not self._host_ok():
            return self._send(403, {"error": "non-loopback Host header"})
        url = urlparse(self.path)
        if url.path != "/api/analyze":
            return self._send(404, {"error": "not found"})
        qs = {k: v[0] for k, v in parse_qs(url.query).items()}
        trait = qs.get("trait", "").strip()
        sex = qs.get("sex") or None
        build = qs.get("build") or None
        name = Path(self.headers.get("X-Filename") or "upload.txt").name
        length = int(self.headers.get("Content-Length") or 0)
        if not trait or sex not in (None, "female", "male") or build not in (None, "GRCh37", "GRCh38", "NCBI36"):
            return self._send(400, {"error": "trait required; sex female|male; build GRCh37|GRCh38|NCBI36"})
        if not name.lower().endswith(ALLOWED_SUFFIXES) or not re.fullmatch(r"[\w.\- ]{1,200}", name):
            return self._send(400, {"error": f"file name must end with one of {ALLOWED_SUFFIXES}"})
        if not 0 < length <= MAX_UPLOAD:
            return self._send(413, {"error": f"file must be 1 byte to {MAX_UPLOAD // 2**20} MB"})
        work = Path(tempfile.mkdtemp(prefix="prsguard_"))
        try:
            src = work / name
            with open(src, "wb") as fh:
                remaining = length
                while remaining:
                    chunk = self.rfile.read(min(remaining, 1 << 20))
                    if not chunk:
                        break
                    fh.write(chunk)
                    remaining -= len(chunk)
            from prsguard.pipeline import RunConfig, run

            demo = _demo_set_applies(trait, sex, build)
            cfg = RunConfig(genotype=src, trait=trait, out_dir=work / "out", sex=sex, declared_build=build,
                            catalog_mode="snapshot" if demo else "live",
                            candidates=DEMO_CANDIDATES if demo else None,
                            literature_context=DEMO_LITERATURE if demo and DEMO_LITERATURE.exists() else None,
                            case={"provenance": "local upload (analysed on this machine, then deleted)"},
                            command=["prsguard", "serve", "(upload)"])
            try:
                result = run(cfg)
            except SystemExit as exc:
                return self._send(422, {"error": str(exc)})
            except Exception as exc:  # report, never leak file contents
                return self._send(500, {"error": f"analysis failed: {type(exc).__name__}"})
            result["input"]["genotype"]["file"] = name
            return self._send(200, result)
        finally:
            shutil.rmtree(work, ignore_errors=True)

    def log_message(self, fmt, *args):  # no request logs with file names or query text
        return


def serve(port: int = 8765, origins: set[str] | None = None) -> None:
    Handler.origins = set(origins or DEFAULT_ORIGINS)
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"PRSGuard local analysis server on http://127.0.0.1:{port} (loopback only; uploads deleted after use)")
    httpd.serve_forever()
