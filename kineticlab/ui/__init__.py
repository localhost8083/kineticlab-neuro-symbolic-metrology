"""Local web UI (KL-8.1 Part B).

Stdlib ``http.server`` on 127.0.0.1 only; one self-contained page
(``index.html``, inline CSS/JS — no frameworks, no CDN, no build
step, fully offline). Uploads validate through the REAL ingest
entry points; demos run the pinned chains through the shared
``kineticlab.demo`` surface (same code as the CLI).

Trust boundary (upload): declared-size cap enforced before and
during the read, multipart file part required, video/mp4
content-type required, MP4 ftyp magic required, bytes stored
under their own SHA-256 (never the client filename) in the
gitignored ``uploads/`` dir. Every input failure answers HTTP
400 with a locked-taxonomy registered code — never a 500, never
a traceback, never a fabricated measurement.

Honesty rules: the upload verdict reports media structure + PTS
health and states that full measurement needs a live SAM run
this offline build does not perform; demo verdict styling keys
off the result ``status`` field (rejection never styled as
success); animation is CSS-only polish with a real request-tied
spinner and ``prefers-reduced-motion`` respected; all served
data is rendered via ``textContent``, never ``innerHTML``.

Live capture (KL-8.4): ``POST /api/live`` runs detect/measure
stages and ``GET /api/runs/<id>/<name>`` serves run exports;
both require ``MODEL_API_KEY`` in the server environment, the
page learns only a stamped true/false boolean, and the live
panel stays hidden without a key. Confirm-before-measure is
enforced in the page flow (measure needs a confirmed run id)
and re-checked at the chain boundary.
"""

from kineticlab.ui.server import (
    BIND_HOST,
    DEFAULT_PORT,
    MAX_UPLOAD_BYTES,
    make_server,
    serve,
)

__all__ = [
    "BIND_HOST",
    "DEFAULT_PORT",
    "MAX_UPLOAD_BYTES",
    "make_server",
    "serve",
]
