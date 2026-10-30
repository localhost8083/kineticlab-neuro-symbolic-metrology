"""HTTP server for the local web UI (KL-8.1 Part B).

Routes (all localhost-only, single-threaded — demo runs are long
and share fixed out dirs, so concurrent requests queue honestly
behind the real work instead of colliding on it):

- ``GET /`` — the single-page app.
- ``POST /api/upload`` — multipart ``clip`` file -> structure
  verdict JSON (media record + PTS health + measurement-
  unavailable notice). Validated before parsing: size cap,
  content-type, MP4 magic.
- ``POST /api/demo/success`` and ``POST /api/demo/rejection`` —
  run the pinned chains through ``kineticlab.demo`` (same code
  as the CLI) and return the result + export links.
- ``GET /api/exports/<chain>/<name>`` — written export bytes
  (strict allowlist, no path traversal possible).
- ``GET /api/overlay`` — the pinned ball-trajectory overlay SVG.
- ``POST /api/live`` — live capture stages (KL-8.4): multipart
  ``stage=detect`` (clip + mode + prompts -> run id + confirm
  summary) or ``stage=measure`` (run id + card mm -> result +
  export links). Requires ``MODEL_API_KEY`` in the server env.
- ``GET /api/runs/<run-id>/<name>`` — one live-run export's bytes
  (run id pattern-validated, name on a fixed allowlist; requires
  the key like all live routes).

HTTP-to-taxonomy map (locked codes only, zero new): unknown
route -> 404 ``E_MISSING_FIELD`` naming the path; wrong method
-> 405 ``E_WRONG_TYPE`` naming the expected method; foreign Host
on POST (not loopback) -> 400 ``E_WRONG_TYPE`` naming ``Host``;
oversized body -> 400 ``E_OUT_OF_RANGE``; empty body/file -> 400
``E_EMPTY_STRING``; non-multipart body or non-mp4 part ->
400 ``E_WRONG_TYPE``; missing boundary/part -> 400
``E_MISSING_FIELD``; bad magic -> 400 ``E_NOT_AN_OBJECT``;
deeper structural failures -> the ingest ``ContractError``'s
own first code. Live additions: missing key -> 503
``E_MISSING_FIELD`` naming ``MODEL_API_KEY``; bad stage/mode
label -> 400 ``E_BAD_ENUM``; client-value misuse (bad prompts,
bad/missing mm, motion mm) -> 400 with the chain's own code;
unknown run -> 404; any other ``ContractError`` escaping the
live chain (API transport, empty detections, parse, fit) ->
502 with the FIRST code/field/detail (the upstream/backend
failed, not the client's envelope).
Genuine server bugs answer 500 with a null code and no
traceback (user input must never cause one).

Console forensics (KL-8.7 item 5): every request writes one
guarded access line to stderr (stdlib format; a dead console
never fails the request). Capture it with
``python -m kineticlab serve 2>&1 | Tee-Object serve.log``.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from http.server import BaseHTTPRequestHandler
from http.server import HTTPServer as _StdHTTPServer
from pathlib import Path
from typing import Any

from kineticlab import __version__
from kineticlab.capture.chain import (
    CALIBRATION_FILENAME,
    GEOMETRY_REPORT_FILENAME,
    MOTION_CSV_FILENAME,
    MOTION_REPORT_FILENAME,
    SUMMARY_FILENAME,
    new_run_id,
    run_detect,
    run_measure,
    validate_mode,
    validate_run_id,
)
from kineticlab.contracts import ContractError, validate_frame_table
from kineticlab.demo import EXPORT_FILENAMES, run_demo_chain
from kineticlab.ingest import extract_frame_records, inspect_media

BIND_HOST = "127.0.0.1"
"""The only interface this server ever binds (never 0.0.0.0)."""

DEFAULT_PORT = 8137

MAX_UPLOAD_BYTES = 64 * 1024 * 1024
"""Upload cap: measured clips are <= 2 MB, so 64 MiB is ~30x
headroom while bounding the in-memory read and upload disk use."""

UPLOAD_FIELD = "clip"
MP4_CONTENT_TYPE = "video/mp4"
OVERLAY_REL = "fixtures/geometry/overlay_live_ball.svg"

MEASUREMENT_UNAVAILABLE = (
    "Full measurement requires a live SAM 3.1 run on this clip; "
    "this offline build replays pinned SAM artifacts only and "
    "never fabricates a measurement for an uploaded file."
)

EXPORT_CONTENT_TYPES = {
    "result.json": "application/json",
    "diagnostics.json": "application/json",
    "angles.csv": "text/csv",
    "summary.md": "text/markdown",
}

LIVE_PAGE_TOKEN = b"__KL_LIVE_AVAILABLE__"
VERSION_PAGE_TOKEN = b"__KL_VERSION__"
"""Placeholder the ``/`` route replaces with ``true``/``false``.

The page ships one self-contained file; the server stamps key
presence (a boolean ONLY — the secret is never read into the page)
at serve time. The live panel hides itself when the value is false.
"""

RUN_CONTENT_TYPES = {
    "result.json": "application/json",
    "diagnostics.json": "application/json",
    "angles.csv": "text/csv",
    "summary.md": "text/markdown",
    "motion_report.json": "application/json",
    "motion_angles.csv": "text/csv",
    "capture_metadata.json": "application/json",
    "calibration.json": "application/json",
    "geometry_report.json": "application/json",
    "detect_summary.json": "application/json",
}
"""Fixed ``/api/runs`` allowlist (raw fixtures + clip stay unserved)."""

LIVE_OUT_DIRNAME = "live_out"

FULL_RUN_FILES = ("result.json", "diagnostics.json", "angles.csv",
                  "summary.md")
MOTION_RUN_FILES = ("motion_report.json", "motion_angles.csv")
"""Primary exports linked from a measure response, per mode."""


class UiError(Exception):
    """HTTP-mapped failure carrying a registered taxonomy code."""

    def __init__(self, code: str, field: str | None, detail: str,
                 status: int = 400) -> None:
        super().__init__(detail)
        self.code = code
        self.field = field
        self.detail = detail
        self.status = status


def _fail(code: str, field: str | None, detail: str,
          status: int = 400) -> None:
    raise UiError(code, field, detail, status)


LOOPBACK_HOST_NAMES = ("127.0.0.1", "localhost")


def _host_is_loopback(host: str) -> bool:
    """True when a Host header names this loopback server only.

    Accepts ``127.0.0.1`` / ``localhost`` with an optional numeric
    ``:port`` suffix (case-insensitive); anything else is a foreign
    origin and fails closed.
    """
    name = host.strip().lower()
    if ":" in name:
        name, _, port = name.partition(":")
        if not port.isdigit():
            return False
    return name in LOOPBACK_HOST_NAMES


def parse_multipart(body: bytes, boundary: bytes) -> list[dict[str, Any]]:
    """Split a multipart body into parts (headers + bytes).

    Small strict parser (stdlib-only; the ``cgi`` module is gone):
    each part carries its content-disposition filename/name, its
    content-type, and its raw bytes. Malformed envelopes raise
    ``UiError`` — never partial parts.
    """
    if not boundary or b"\r\n" in boundary or len(boundary) > 200:
        _fail("E_MISSING_FIELD", "boundary",
              "multipart boundary missing or malformed")
    delimiter = b"--" + boundary
    chunks = body.split(delimiter)
    if len(chunks) < 3 or not chunks[-1].strip().startswith(b"--"):
        _fail("E_WRONG_TYPE", "body",
              "not a well-formed multipart body")
    parts = []
    for chunk in chunks[1:-1]:
        if chunk.startswith(b"\r\n"):
            chunk = chunk[2:]
        if chunk.endswith(b"\r\n"):
            chunk = chunk[:-2]
        head, separator, data = chunk.partition(b"\r\n\r\n")
        if not separator:
            _fail("E_WRONG_TYPE", "body",
                  "multipart part without a header block")
        headers: dict[str, str] = {}
        for line in head.decode("latin-1").split("\r\n"):
            name, separator, value = line.partition(":")
            if separator:
                headers[name.strip().lower()] = value.strip()
        disposition = headers.get("content-disposition", "")
        fields: dict[str, str] = {}
        for item in disposition.split(";"):
            key, separator, value = item.partition("=")
            if separator:
                fields[key.strip().lower()] = value.strip().strip('"')
        parts.append({"name": fields.get("name", ""),
                      "filename": fields.get("filename", ""),
                      "content_type": headers.get("content-type", ""),
                      "data": data})
    return parts


def validate_upload(content_type: str | None,
                    body: bytes) -> tuple[str, bytes]:
    """Validate an upload envelope; return (filename, mp4 bytes).

    Order is cheapest-first: envelope shape, content-type, magic
    bytes. Every failure carries a registered code.
    """
    if content_type is None or "multipart/form-data" not in content_type:
        _fail("E_WRONG_TYPE", "content_type",
              f"expected multipart/form-data, got {content_type!r}")
    boundary = b""
    for item in content_type.split(";"):
        key, separator, value = item.partition("=")
        if separator and key.strip().lower() == "boundary":
            boundary = value.strip().strip('"').encode("latin-1")
    parts = parse_multipart(body, boundary)
    clips = [part for part in parts if part["name"] == UPLOAD_FIELD]
    if not clips:
        _fail("E_MISSING_FIELD", f"part:{UPLOAD_FIELD}",
              f"multipart body carries no {UPLOAD_FIELD!r} file part")
    part = clips[0]
    if part["content_type"] != MP4_CONTENT_TYPE:
        _fail("E_WRONG_TYPE", "part:content_type",
              f"expected {MP4_CONTENT_TYPE}, "
              f"got {part['content_type']!r}")
    data = part["data"]
    if not data:
        _fail("E_EMPTY_STRING", f"part:{UPLOAD_FIELD}",
              "uploaded file is empty")
    if len(data) < 8 or data[4:8] != b"ftyp":
        _fail("E_NOT_AN_OBJECT", f"part:{UPLOAD_FIELD}",
              "bytes are not an MP4 (missing ftyp box)")
    return part["filename"], data


def live_text_fields(content_type: str | None,
                     body: bytes) -> dict[str, str]:
    """Read text fields from a live-stage multipart body (strict).

    Returns ``{field name: utf-8 text}`` for every non-file part; the
    clip part (when present) is validated separately by
    :func:`validate_upload` on the same body. Malformed envelopes fail
    with the same codes as the upload boundary.
    """
    if content_type is None or "multipart/form-data" not in content_type:
        _fail("E_WRONG_TYPE", "content_type",
              f"expected multipart/form-data, got {content_type!r}")
    assert content_type is not None
    boundary = b""
    for item in content_type.split(";"):
        key, separator, value = item.partition("=")
        if separator and key.strip().lower() == "boundary":
            boundary = value.strip().strip('"').encode("latin-1")
    fields: dict[str, str] = {}
    for part in parse_multipart(body, boundary):
        if part["name"] == UPLOAD_FIELD:
            continue
        try:
            text = part["data"].decode("utf-8")
        except UnicodeDecodeError:
            _fail("E_WRONG_TYPE", f"part:{part['name']}",
                  "text field is not utf-8")
            raise AssertionError("unreachable")
        fields[part["name"]] = text
    return fields


def live_key_present() -> bool:
    """Whether a live key exists (presence boolean ONLY, never the key)."""
    return bool(os.environ.get("MODEL_API_KEY"))


def build_upload_verdict(saved_path: Path, filename: str,
                         digest: str, size: int) -> dict[str, Any]:
    """Run real ingest validation over a stored upload (no guessing).

    ``inspect_media`` + ``extract_frame_records`` are the pipeline's
    own entry points, so every structural number and every failure
    code comes from the pipeline, not the UI. PTS health counts
    null-PTS rows and reports the contract table check outcome.
    """
    media = inspect_media(saved_path)
    table = extract_frame_records(str(saved_path))
    null_pts = sum(1 for record in table
                   if record.pts_seconds is None)
    try:
        validate_frame_table(list(table))
    except ContractError as error:
        first = error.errors[0]
        pts = {"samples": len(table), "null_pts": null_pts,
               "healthy": False, "code": first.code,
               "detail": f"{first.field}: {first.message}"}
    else:
        pts = {"samples": len(table), "null_pts": null_pts,
               "healthy": True, "code": None, "detail": None}
    return {
        "upload": {"filename": filename, "sha256": digest,
                   "bytes": size,
                   "stored": f"uploads/{saved_path.name}"},
        "media": media.to_dict(),
        "pts": pts,
        "measurement": {"available": False,
                        "reason": MEASUREMENT_UNAVAILABLE},
    }


class _Handler(BaseHTTPRequestHandler):
    """Routes; BaseHTTPRequestHandler keeps requests sequential."""

    server_version = "KineticLabUI/1"

    timeout = 30
    """KL-9.6 M9: idle-socket cap in seconds.

    socketserver applies this to the client socket at setup, so a
    silent client that connects and never speaks (or stalls
    mid-body) raises ``TimeoutError`` instead of holding the
    single-threaded server forever. The timeout path lands in
    :meth:`HTTPServer.handle_error` alongside dead sockets: quiet,
    connection closed, server keeps serving. Long demo/live runs
    are unaffected — the cap gates socket idleness, not handler
    compute time.
    """

    def log_message(self, fmt: str, *args: Any) -> None:
        # KL-8.7 item 5: one guarded access line per request
        # (stdlib format) for console forensics — capture with
        # ``python -m kineticlab serve 2>&1 | Tee-Object serve.log``.
        # A dead Windows console must never fail a request, so
        # stderr faults are swallowed; the response path never
        # depends on logging.
        try:
            sys.stderr.write("%s - - [%s] %s\n"
                             % (self.client_address[0],
                                self.log_date_time_string(),
                                fmt % args))
        except (OSError, ValueError):
            pass

    @property
    def _repo(self) -> Path:
        return self.server.ui_repo_root  # type: ignore[attr-defined]

    @property
    def _work(self) -> Path:
        return self.server.ui_work_dir  # type: ignore[attr-defined]

    @property
    def _transport(self) -> Any:
        return getattr(self.server, "ui_transport", None)

    def _require_live_key(self) -> str:
        key = os.environ.get("MODEL_API_KEY")
        if not key:
            _fail("E_MISSING_FIELD", "MODEL_API_KEY",
                  "live routes need MODEL_API_KEY in the server "
                  "environment", status=503)
            raise AssertionError("unreachable")
        return key

    def _send_json(self, payload: Any, status: int = 200) -> None:
        body = json.dumps(payload, sort_keys=True,
                          indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_bytes(self, body: bytes, content_type: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_error(self, error: UiError) -> None:
        self._send_json({"error": {"code": error.code,
                                   "field": error.field,
                                   "detail": error.detail}},
                        status=error.status)

    def _read_capped_body(self) -> bytes:
        declared = self.headers.get("Content-Length")
        if declared is None:
            _fail("E_MISSING_FIELD", "Content-Length",
                  "POST requires a Content-Length header")
        try:
            total = int(declared)
        except ValueError:
            _fail("E_WRONG_TYPE", "Content-Length",
                  f"not an integer: {declared!r}")
            raise AssertionError("unreachable")
        if total < 0:
            _fail("E_OUT_OF_RANGE", "Content-Length",
                  f"negative length: {total}")
        if total > MAX_UPLOAD_BYTES:
            _fail("E_OUT_OF_RANGE", "Content-Length",
                  f"declared {total} bytes exceeds the "
                  f"{MAX_UPLOAD_BYTES}-byte cap")
        if total == 0:
            _fail("E_EMPTY_STRING", "body", "POST body is empty")
        chunks = []
        remaining = total
        while remaining:
            piece = self.rfile.read(min(65536, remaining))
            if not piece:
                break
            chunks.append(piece)
            remaining -= len(piece)
        body = b"".join(chunks)
        if len(body) != total:
            _fail("E_OUT_OF_RANGE", "body",
                  f"short read: got {len(body)} of {total} bytes")
        return body

    def _route_get(self) -> None:
        path = self.path.split("?", 1)[0]
        if path == "/":
            page = (Path(__file__).resolve().parent
                    / "index.html").read_bytes()
            if page.count(LIVE_PAGE_TOKEN) != 1:
                self._send_json({"error": {"code": None, "detail":
                                           "internal server error"}},
                                status=500)
                return
            if page.count(VERSION_PAGE_TOKEN) != 1:
                self._send_json({"error": {"code": None, "detail":
                                           "internal server error"}},
                                status=500)
                return
            page = page.replace(
                LIVE_PAGE_TOKEN,
                b"true" if live_key_present() else b"false")
            page = page.replace(VERSION_PAGE_TOKEN,
                                __version__.encode("ascii"))
            self._send_bytes(page, "text/html; charset=utf-8")
        elif path == "/api/overlay":
            svg = (self._repo / OVERLAY_REL).read_bytes()
            self._send_bytes(svg, "image/svg+xml")
        elif path.startswith("/api/exports/"):
            rest = path[len("/api/exports/"):]
            chain, separator, name = rest.partition("/")
            if not separator or chain not in ("success", "rejection") \
                    or name not in EXPORT_CONTENT_TYPES:
                _fail("E_MISSING_FIELD", "path",
                      f"unknown export: {path!r}", status=404)
            target = (self._work / "demo_out" / chain / name)
            if not target.is_file():
                _fail("E_MISSING_FIELD", "path",
                      f"not written yet — run the {chain} demo first",
                      status=404)
            self._send_bytes(target.read_bytes(),
                             EXPORT_CONTENT_TYPES[name])
        elif path.startswith("/api/runs/"):
            self._require_live_key()
            rest = path[len("/api/runs/"):]
            run_id, separator, name = rest.partition("/")
            try:
                validate_run_id(run_id)
            except ContractError:
                _fail("E_MISSING_FIELD", "path",
                      f"unknown run export: {path!r}", status=404)
            if not separator or name not in RUN_CONTENT_TYPES:
                _fail("E_MISSING_FIELD", "path",
                      f"unknown run export: {path!r}", status=404)
            root = (self._work / LIVE_OUT_DIRNAME).resolve()
            target = (self._work / LIVE_OUT_DIRNAME / run_id
                      / name).resolve()
            if not target.is_relative_to(root) or not target.is_file():
                _fail("E_MISSING_FIELD", "path",
                      f"unknown run export: {path!r}", status=404)
            self._send_bytes(target.read_bytes(),
                             RUN_CONTENT_TYPES[name])
        else:
            _fail("E_MISSING_FIELD", "path",
                  f"unknown route: {path!r}", status=404)

    def _route_upload(self) -> None:
        body = self._read_capped_body()
        filename, data = validate_upload(
            self.headers.get("Content-Type"), body)
        digest = hashlib.sha256(data).hexdigest()
        uploads = self._work / "uploads"
        uploads.mkdir(parents=True, exist_ok=True)
        saved = uploads / f"{digest}.mp4"
        if not saved.is_file():
            saved.write_bytes(data)
        try:
            verdict = build_upload_verdict(saved, filename, digest,
                                           len(data))
        except ContractError as error:
            first = error.errors[0]
            raise UiError(first.code, first.field,
                          f"{first.field}: {first.message}")
        self._send_json(verdict)

    def _route_demo(self, chain: str) -> None:
        length = self.headers.get("Content-Length")
        if length is not None and length.strip() not in ("", "0"):
            _fail("E_WRONG_TYPE", "body",
                  "demo runs take no request body")
        out = run_demo_chain(self._repo, chain=chain,
                             out_dir=self._work / "demo_out" / chain)
        files = {name: f"/api/exports/{chain}/{name}"
                 for name in EXPORT_FILENAMES}
        self._send_json({"chain": chain,
                         "status_line": out["status_line"],
                         "result": out["result"],
                         "files": files,
                         "advisory": out["advisory"]})

    def do_GET(self) -> None:
        try:
            self._route_get()
        except UiError as error:
            self._send_error(error)
        except (OSError, ContractError):
            self._send_json(
                {"error": {"code": None,
                           "detail": "internal server error"}},
                status=500)

    def _chain_error(self, error: ContractError) -> None:
        first = error.errors[0]
        raise UiError(first.code, first.field, first.message,
                      status=502)

    def _live_error(self, error: ContractError) -> None:
        first = error.errors[0]
        field = first.field or ""
        if field == "card_width_mm" or field.startswith("prompt"):
            raise UiError(first.code, f"part:{field}", first.message)
        if first.code == "E_MISSING_FIELD" and field == "run_id":
            raise UiError(first.code, f"part:{field}", first.message,
                          status=404)
        self._chain_error(error)

    def _route_live_detect(self, live_key: str,
                           content_type: str | None,
                           body: bytes) -> None:
        fields = live_text_fields(content_type, body)
        if "mode" not in fields:
            _fail("E_MISSING_FIELD", "part:mode",
                  "detect needs a mode field ('full' or 'motion')")
        try:
            mode = validate_mode(fields["mode"])
        except ContractError as error:
            first = error.errors[0]
            raise UiError(first.code, f"part:{first.field}",
                          first.message)
        filename, data = validate_upload(content_type, body)
        prompts = {"bob": fields["prompt_bob"]
                       if "prompt_bob" in fields else "red ball"}
        if "prompt_card" in fields:
            prompts["card"] = fields["prompt_card"]
        elif mode == "full":
            prompts["card"] = "white paper card"
        digest = hashlib.sha256(data).hexdigest()
        uploads = self._work / "uploads"
        uploads.mkdir(parents=True, exist_ok=True)
        staged = uploads / f"{digest}.mp4"
        if not staged.is_file():
            staged.write_bytes(data)
        run_id = new_run_id()
        try:
            out = run_detect(staged, self._work / LIVE_OUT_DIRNAME
                             / run_id, mode, prompts, live_key,
                             transport=self._transport)
        except ContractError as error:
            self._live_error(error)
            raise AssertionError("unreachable")
        self._send_json({"run_id": run_id, "filename": filename,
                         "summary": out["summary"]})

    def _route_live_measure(self, content_type: str | None,
                            body: bytes) -> None:
        fields = live_text_fields(content_type, body)
        if "run_id" not in fields:
            _fail("E_MISSING_FIELD", "part:run_id",
                  "measure needs the confirmed run id")
        try:
            run_id = validate_run_id(fields["run_id"])
        except ContractError:
            _fail("E_MISSING_FIELD", "part:run_id",
                  f"unknown run: {fields['run_id']!r}", status=404)
            raise AssertionError("unreachable")
        run_dir = self._work / LIVE_OUT_DIRNAME / run_id
        if not run_dir.is_dir():
            _fail("E_MISSING_FIELD", "part:run_id",
                  f"unknown run: {run_id!r}", status=404)
        if "mode" in fields:
            try:
                summary = json.loads(
                    (run_dir / SUMMARY_FILENAME).read_text(
                        encoding="utf-8"))
            except (OSError, ValueError):
                summary = {}
            if fields["mode"] != summary.get("mode"):
                _fail("E_INCOHERENT_VALUE", "part:mode",
                      "measure mode disagrees with the confirmed run")
        try:
            out = run_measure(run_dir,
                              fields.get("card_width_mm"))
        except ContractError as error:
            self._live_error(error)
            raise AssertionError("unreachable")
        names = FULL_RUN_FILES if out["mode"] == "full" \
            else MOTION_RUN_FILES
        files = {name: f"/api/runs/{run_id}/{name}" for name in names}
        payload: dict[str, Any] = {"run_id": run_id,
                                   "mode": out["mode"],
                                   "status_line": out["status_line"],
                                   "files": files}
        if out["mode"] == "full":
            payload["result"] = out["result"]
            payload["diagnostics"] = out["diagnostics"]
        else:
            payload["report"] = out["report"]
        self._send_json(payload)

    def _route_live(self) -> None:
        live_key = self._require_live_key()
        body = self._read_capped_body()
        content_type = self.headers.get("Content-Type")
        fields = live_text_fields(content_type, body)
        stage = fields.get("stage")
        if stage is None:
            _fail("E_MISSING_FIELD", "part:stage",
                  "live needs a stage field ('detect' or 'measure')")
        if stage == "detect":
            self._route_live_detect(live_key, content_type, body)
        elif stage == "measure":
            self._route_live_measure(content_type, body)
        else:
            _fail("E_BAD_ENUM", "part:stage",
                  f"stage must be 'detect' or 'measure', got {stage!r}")

    def _require_loopback_host(self) -> None:
        # KL-9.6 M7: DNS-rebinding guard for the side-effecting POST
        # routes (GET responses carry no CORS headers, so cross-origin
        # reads are already impossible; the rebinding write risk is
        # here). An absent Host header is allowed: HTTP/1.0 and local
        # probes send none, and a rebinding attack must present the
        # victim domain as Host — an absent header carries no attack
        # origin. A PRESENT foreign Host fails closed with the
        # registered origin-misuse code.
        host = self.headers.get("Host")
        if host is None or _host_is_loopback(host):
            return
        _fail("E_WRONG_TYPE", "Host",
              f"Host {host!r} is not this loopback server "
              "(127.0.0.1 / localhost only)")

    def _dispatch_post(self) -> None:
        self._require_loopback_host()
        path = self.path.split("?", 1)[0]
        if path == "/api/upload":
            self._route_upload()
        elif path == "/api/demo/success":
            self._route_demo("success")
        elif path == "/api/demo/rejection":
            self._route_demo("rejection")
        elif path == "/api/live":
            self._route_live()
        else:
            _fail("E_MISSING_FIELD", "path",
                  f"unknown route: {path!r}", status=404)

    def do_POST(self) -> None:
        try:
            self._dispatch_post()
        except UiError as error:
            self._send_error(error)
        except (BrokenPipeError, ConnectionResetError):
            pass  # client went away; nothing to answer
        except Exception:  # noqa: BLE001 — bugs stay 500s, never leak
            self._send_json(
                {"error": {"code": None,
                           "detail": "internal server error"}},
                status=500)

    def _method_not_allowed(self) -> None:
        self._send_error(UiError("E_WRONG_TYPE", "method",
                                 f"{self.command} not supported here; "
                                 f"use GET or POST",
                                 status=405))

    do_PUT = _method_not_allowed
    do_DELETE = _method_not_allowed
    do_PATCH = _method_not_allowed


class HTTPServer(_StdHTTPServer):
    """Loopback server that stays quiet about dead client sockets.

    KL-9.2 item 1: when a browser refreshes mid-response, the
    response write raises a connection error that socketserver
    would otherwise print as a full secondary traceback — noise on
    top of the already-handled request outcome (the 500 fallback
    re-writes into the aborted socket first). Dead-socket failures
    print nothing; every other exception still goes through the
    standard ``handle_error`` path, so genuine server bugs stay
    loud and the KL-8.7 console-independence guarantee holds.

    KL-9.6 M9: idle-socket timeouts (``_Handler.timeout``) land here
    as ``TimeoutError`` and are quiet for the same reason — a gone
    client is not a server bug.
    """

    def handle_error(self, request: Any, client_address: Any) -> None:
        _exc_type, exc, _tb = sys.exc_info()
        if isinstance(exc, (BrokenPipeError, ConnectionResetError,
                            ConnectionAbortedError, TimeoutError)):
            return
        super().handle_error(request, client_address)


def make_server(port: int, repo_root: Path,
                work_dir: Path | None = None,
                transport: Any = None) -> HTTPServer:
    """Build the UI server (bound to 127.0.0.1 only, never 0.0.0.0).

    ``work_dir`` holds ``uploads/``, ``demo_out/``, and ``live_out/``
    (defaults to the repo root; tests pass a scratch dir). The server
    is single-threaded: demo/live runs queue behind real work, one at
    a time (single-flight v1, documented in the KL-8.4 handoff).
    ``transport`` overrides the live HTTP transport (tests inject a
    mock; production passes nothing and uses stdlib urllib). Port 0
    means OS-assigned (tests); human entry points pass an explicit
    port.
    """
    if port != 0 and not 1 <= port <= 65535:
        raise ValueError(f"port must be 0 or 1..65535, got {port}")
    work = work_dir if work_dir is not None else repo_root
    (work / "uploads").mkdir(parents=True, exist_ok=True)
    (work / "demo_out").mkdir(parents=True, exist_ok=True)
    (work / LIVE_OUT_DIRNAME).mkdir(parents=True, exist_ok=True)
    server = HTTPServer((BIND_HOST, port), _Handler)
    server.ui_repo_root = repo_root  # type: ignore[attr-defined]
    server.ui_work_dir = work  # type: ignore[attr-defined]
    server.ui_transport = transport  # type: ignore[attr-defined]
    return server


def serve(port: int, repo_root: Path,
          work_dir: Path | None = None,
          transport: Any = None) -> None:
    """Serve the UI until interrupted (blocking)."""
    server = make_server(port, repo_root, work_dir, transport)
    address = server.server_address
    print(f"KineticLab UI: open http://127.0.0.1:{address[1]}/ "
          f"in a browser (localhost only, Ctrl-C to stop)",
          flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
