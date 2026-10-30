"""Live SAM 3.1 capture over stdlib ``urllib`` (KL-8.4).

One function per concern: :func:`run_capture` uploads a clip, runs one
``sam-3.1`` segmentation per prompt, and saves each role's ``output_text``
VERBATIM as ``raw_<role>_one_bit.txt`` plus a ``capture_metadata.json``
facts record. The wire text is exactly the saved-fixture format, so
:func:`kineticlab.observation.parse_raw_fixture` consumes it natively.

Transport shape (proven by ``Smoke/sam_smoke_test.py``, read-only; it wins
over prose on disagreement):

- ``POST {BASE_URL}/files`` multipart (``purpose=user_data`` + the MP4
  bytes) -> ``{"id": "file-..."}``.
- ``POST {BASE_URL}/responses`` JSON ``{"model": "sam-3.1", "input":
  [{"role": "user", "content": [{"type": "input_text", ...}, {"type":
  "input_video", "file_id": ...}]}], "metadata": {"include_confidence":
  "true", "mask_encoding": "one_bit"}, "stream": False}``.
- ``DELETE {BASE_URL}/files/{id}`` after each capture (upload hygiene).

Deltas vs the KL-8.4 brief, flagged honestly:

- The brief says ``input_video`` carries raw bytes inline; the wire takes
  a Files-API ``file_id`` instead (the smoke test proves this shape).
- ``include_confidence: "true"`` rides alongside ``mask_encoding``
  (proven shape; the brief lists only the latter).
- ``expires_after`` is NOT sent (its stdlib-multipart wire form is
  unverified); the explicit DELETE covers upload hygiene.
- The ``input_video`` part key ``file_id`` is inferred from the
  OpenAI-compatible ``input_image``/``file_id`` precedent — the SDK call
  in the smoke test hides the serialized key. First live run validates
  it; an API rejection here adjusts exactly this key.
- Multi-concept prompts (comma/``and``) pass through to the API instead
  of failing client-side: no registered code fits "prompt could segment
  better", and the API's own response governs. Blank prompts fail fast.

HTTP-to-taxonomy map (locked codes only, zero new):

- blank/missing key -> ``E_MISSING_FIELD`` naming ``MODEL_API_KEY``.
- blank prompt -> ``E_EMPTY_STRING`` naming ``prompt:<role>``.
- unknown role -> ``E_BAD_ENUM`` (roles are ``bob``/``card`` only).
- bad mode label -> ``E_BAD_ENUM`` (``full``/``motion`` only).
- missing clip -> ``E_MISSING_FIELD`` naming ``clip_path``; empty clip
  -> ``E_EMPTY_STRING``; a directory -> ``E_WRONG_TYPE``.
- 401/403 -> ``E_MISSING_FIELD`` naming ``MODEL_API_KEY`` (the key the
  upstream rejected; the secret itself never appears in any detail).
- other non-2xx -> ``E_MISSING_FIELD`` naming ``output_text`` with the
  HTTP status + API message in the detail (the required text is absent
  because the API errored).
- timeout/DNS/refused/reset -> ``E_MISSING_FIELD`` naming
  ``api_response`` (nearest honest code: the required response never
  arrived). Timeout is 300 s per operation, no retries (M-1 calls took
  ~40 s; 300 s is generous headroom, documented here).
- unparseable response bytes -> ``E_MALFORMED_JSON``; valid JSON of the
  wrong shape -> ``E_WRONG_TYPE`` naming ``response``; no ``output_text``
  segment -> ``E_MISSING_FIELD`` naming ``output_text``.
- empty output_text -> ``E_EMPTY_STRING`` (zero matches: a valid API
  outcome, reported as a registered-code rejection, never success).
- upload response without an id -> ``E_MISSING_FIELD`` ``upload_id``.

A transport is any callable taking ``{"method", "url", "headers",
"body"}`` and returning ``{"status", "body"}``. Tests inject a mock;
production uses :func:`urllib_transport`. ``out_dir`` creation ``OSError``
propagates raw (no registered code fits a filesystem failure, so none is
forced — same rule as the assembly clip read).

Stdlib only. No SDK. The key travels in the Authorization header alone:
never in metadata, errors, logs, or return values.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from kineticlab.contracts import ContractError, FieldError
from kineticlab.observation import find_multisegment_lines

__all__ = [
    "BASE_URL",
    "MODEL_ID",
    "TIMEOUT_SECONDS",
    "ROLE_FILENAMES",
    "MODES",
    "build_upload_body",
    "build_responses_body",
    "extract_output_text",
    "urllib_transport",
    "run_capture",
]

BASE_URL = "https://api.meta.ai/v1"
"""Live API base (user-verified contract; the only network peer)."""

MODEL_ID = "sam-3.1"
"""Segmentation model id (user-verified contract)."""

TIMEOUT_SECONDS = 300
"""Per-operation HTTP timeout; no retries (see module docstring)."""

ROLE_FILENAMES = {
    "bob": "raw_bob_one_bit.txt",
    "card": "raw_card_one_bit.txt",
}
"""Role -> verbatim artifact filename (matches the pinned live names)."""

MODES = ("full", "motion")
"""Measurement modes (validated labels only)."""


def _fail(code: str, field: str | None, detail: str) -> None:
    raise ContractError([FieldError(code, field, detail)])


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_upload_body(clip_bytes: bytes, filename: str) -> tuple[str, bytes]:
    """Build the multipart ``/files`` body (purpose + raw clip bytes)."""
    boundary = f"----kineticlab-{secrets.token_hex(16)}"
    head = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="purpose"\r\n\r\n'
        "user_data\r\n"
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        "Content-Type: video/mp4\r\n\r\n"
    ).encode("utf-8")
    tail = f"\r\n--{boundary}--\r\n".encode("utf-8")
    return (f"multipart/form-data; boundary={boundary}",
            head + clip_bytes + tail)


def build_responses_body(prompt: str, file_id: str) -> bytes:
    """Build the non-streaming ``/responses`` JSON body for one prompt."""
    payload = {
        "model": MODEL_ID,
        "input": [{
            "role": "user",
            "content": [
                {"type": "input_text", "text": prompt},
                {"type": "input_video", "file_id": file_id},
            ],
        }],
        "metadata": {
            "include_confidence": "true",
            "mask_encoding": "one_bit",
        },
        "stream": False,
    }
    return json.dumps(payload, ensure_ascii=True).encode("utf-8")


def _iter_output_text(node: Any) -> list[str]:
    """Collect every ``output_text`` segment from a responses payload."""
    texts: list[str] = []

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            if value.get("type") == "output_text" \
                    and isinstance(value.get("text"), str):
                texts.append(value["text"])
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(node)
    return texts


def extract_output_text(payload: Any, role: str) -> str:
    """Pull the segment text out of a ``/responses`` payload (strict)."""
    if not isinstance(payload, dict):
        _fail("E_WRONG_TYPE", "response",
              f"role {role!r}: API response is not a JSON object")
        raise AssertionError("unreachable")
    texts = _iter_output_text(payload)
    direct = payload.get("output_text")
    if isinstance(direct, str):
        texts.append(direct)
    if not texts:
        _fail("E_MISSING_FIELD", "output_text",
              f"role {role!r}: API response carries no output_text")
        raise AssertionError("unreachable")
    combined = "".join(texts)
    if not combined.strip():
        _fail("E_EMPTY_STRING", f"output_text:{role}",
              f"role {role!r}: output_text is empty (zero matches)")
        raise AssertionError("unreachable")
    return combined


def urllib_transport(request: dict[str, Any]) -> dict[str, Any]:
    """Run one HTTP operation with stdlib ``urllib`` (no SDK, no retry)."""
    http_request = urllib.request.Request(
        request["url"], data=request.get("body"),
        headers=request.get("headers", {}), method=request["method"])
    try:
        with urllib.request.urlopen(http_request,
                                    timeout=TIMEOUT_SECONDS) as response:
            return {"status": int(response.status),
                    "body": response.read()}
    except urllib.error.HTTPError as error:
        try:
            body = error.read()
        except OSError:
            body = b""
        return {"status": int(error.code), "body": body}
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        _fail("E_MISSING_FIELD", "api_response",
              f"{request['method']} {request['url']} failed: {error}")
        raise AssertionError("unreachable")


def _parse_json(body: bytes, role: str) -> Any:
    try:
        return json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        _fail("E_MALFORMED_JSON", "response",
              f"role {role!r}: API response is not parseable JSON: {error}")
        raise AssertionError("unreachable")


def _api_message(payload: Any) -> str:
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict) and isinstance(error.get("message"),
                                                  str):
            return error["message"]
        if isinstance(error, str):
            return error
        message = payload.get("message")
        if isinstance(message, str):
            return message
    return "no message"


def run_capture(clip_path: str | Path, prompts: dict[str, str],
                out_dir: str | Path, api_key: str,
                transport: Callable[[dict[str, Any]],
                                    dict[str, Any]] | None = None,
                mode: str | None = None) -> dict[str, Any]:
    """Capture one SAM segmentation per prompt; save verbatim artifacts.

    Returns ``{"raw_paths", "metadata_path", "metadata", "clip_sha256"}``.
    ``prompts`` maps ``"bob"``/``"card"`` to noun phrases; ``mode`` (when
    given) is stamped into the metadata verbatim after validation.
    """
    send = transport if transport is not None else urllib_transport
    if not isinstance(api_key, str) or not api_key:
        _fail("E_MISSING_FIELD", "MODEL_API_KEY",
              "a live capture needs MODEL_API_KEY in the environment")
        raise AssertionError("unreachable")
    if not isinstance(prompts, dict) or not prompts:
        _fail("E_MISSING_FIELD", "prompts",
              "at least one role prompt is required")
        raise AssertionError("unreachable")
    for role in prompts:
        if role not in ROLE_FILENAMES:
            _fail("E_BAD_ENUM", "prompts",
                  f"unknown role {role!r} (expected 'bob'/'card')")
            raise AssertionError("unreachable")
    for role, prompt in prompts.items():
        if not isinstance(prompt, str) or not prompt.strip():
            _fail("E_EMPTY_STRING", f"prompt:{role}",
                  f"role {role!r}: prompt must be a non-blank noun phrase")
            raise AssertionError("unreachable")
    if mode is not None and mode not in MODES:
        _fail("E_BAD_ENUM", "mode",
              f"mode must be 'full' or 'motion', got {mode!r}")
        raise AssertionError("unreachable")
    clip = Path(clip_path)
    if clip.is_dir():
        _fail("E_WRONG_TYPE", "clip_path",
              f"expected a clip file, got a directory: {clip.name!r}")
        raise AssertionError("unreachable")
    try:
        clip_bytes = clip.read_bytes()
    except OSError:
        _fail("E_MISSING_FIELD", "clip_path",
              f"clip is unreadable: {clip.name!r}")
        raise AssertionError("unreachable")
    if not clip_bytes:
        _fail("E_EMPTY_STRING", "clip_path",
              f"clip is empty: {clip.name!r}")
        raise AssertionError("unreachable")
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    clip_sha = hashlib.sha256(clip_bytes).hexdigest()
    headers = {"Authorization": "Bearer " + api_key}
    artifacts: dict[str, Any] = {}
    timestamps: dict[str, str] = {}
    raw_paths: dict[str, str] = {}
    deleted_all = True
    for role in sorted(prompts):
        prompt = prompts[role]
        content_type, upload_body = build_upload_body(clip_bytes,
                                                      clip.name)
        upload = send({"method": "POST",
                       "url": f"{BASE_URL}/files",
                       "headers": {**headers, "Content-Type": content_type},
                       "body": upload_body})
        upload_payload = _parse_json(upload["body"], role)
        if not 200 <= int(upload["status"]) < 300:
            status = int(upload["status"])
            if status in (401, 403):
                _fail("E_MISSING_FIELD", "MODEL_API_KEY",
                      f"role {role!r}: upload rejected with HTTP {status}: "
                      f"{_api_message(upload_payload)}")
            _fail("E_MISSING_FIELD", "output_text",
                  f"role {role!r}: upload failed with HTTP {status}: "
                  f"{_api_message(upload_payload)}")
            raise AssertionError("unreachable")
        file_id = upload_payload.get("id") \
            if isinstance(upload_payload, dict) else None
        if not isinstance(file_id, str) or not file_id:
            _fail("E_MISSING_FIELD", "upload_id",
                  f"role {role!r}: upload response carries no file id")
            raise AssertionError("unreachable")
        answered = send({"method": "POST",
                         "url": f"{BASE_URL}/responses",
                         "headers": {**headers,
                                     "Content-Type": "application/json"},
                         "body": build_responses_body(prompt, file_id)})
        answered_payload = _parse_json(answered["body"], role)
        if not 200 <= int(answered["status"]) < 300:
            status = int(answered["status"])
            if status in (401, 403):
                _fail("E_MISSING_FIELD", "MODEL_API_KEY",
                      f"role {role!r}: API rejected with HTTP {status}: "
                      f"{_api_message(answered_payload)}")
            _fail("E_MISSING_FIELD", "output_text",
                  f"role {role!r}: API failed with HTTP {status}: "
                  f"{_api_message(answered_payload)}")
            raise AssertionError("unreachable")
        text = extract_output_text(answered_payload, role)
        try:
            removed = send({"method": "DELETE",
                            "url": f"{BASE_URL}/files/{file_id}",
                            "headers": dict(headers),
                            "body": None})
            delete_status: int | None = int(removed["status"])
        except ContractError:
            delete_status = None
        deleted = delete_status is not None \
            and 200 <= delete_status < 300
        deleted_all = deleted_all and deleted
        filename = ROLE_FILENAMES[role]
        raw_path = out_path / filename
        raw_path.write_bytes(text.encode("utf-8"))
        # KL-9.2 item 2: fail fast per role, right after the verbatim
        # save (the offending bytes stay on disk as evidence). The
        # scan mirrors the canonical delimiter rule exactly, so a
        # hit here would deterministically fail canonical parsing
        # later with the same E_NOT_AN_OBJECT — fail now with an
        # actionable hint instead of burning the remaining roles'
        # API calls (and, on blind retry, a whole identical run).
        bad_lines = find_multisegment_lines(text)
        if bad_lines:
            nonblank = sum(1 for raw in text.splitlines()
                           if raw.strip())
            _fail("E_NOT_AN_OBJECT", f"line {bad_lines[0]}",
                  f"role {role!r}: model returned multiple objects for "
                  f"this prompt ({len(bad_lines)} of {nonblank} lines "
                  f"carry extra segments; first at line {bad_lines[0]}) "
                  f"- try a more specific {role} prompt or Motion mode")
            raise AssertionError("unreachable")
        raw_paths[role] = str(raw_path)
        artifacts[filename] = {
            "bytes": len(text.encode("utf-8")),
            "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "upload_id": file_id,
            "upload_deleted_after": deleted,
            "delete_status": delete_status,
        }
        timestamps[f"{filename}_captured_utc"] = _utc_now()
    metadata = {
        "model": MODEL_ID,
        "endpoint": BASE_URL,
        "mask_encoding": "one_bit",
        "include_confidence": True,
        "stream": False,
        "mode": mode,
        "prompts": {role: prompts[role] for role in sorted(prompts)},
        "input_clip": {"filename": clip.name, "bytes": len(clip_bytes),
                       "sha256": clip_sha},
        "artifacts": artifacts,
        "timestamps": timestamps,
        "transport": "kineticlab.capture urllib (non-streaming)",
        "uploads_deleted_after": deleted_all,
        "usage": None,
        "usage_note": "transport does not capture usage; not invented",
    }
    metadata_path = out_path / "capture_metadata.json"
    metadata_path.write_bytes((json.dumps(metadata, sort_keys=True,
                                          indent=2, ensure_ascii=True)
                               + "\n").encode("utf-8"))
    return {"raw_paths": raw_paths, "metadata_path": str(metadata_path),
            "metadata": metadata, "clip_sha256": clip_sha}
