"""Muse Spark advisory layer (M-2): untrusted, advisory-only, offline-first.

Two advisory kinds, both schema-validated in the contracts style:

- ``setup_review``: five setup flags (card visible, camera static,
  blur severity, planar, unexpected note). Fired flags surface ONLY
  as the existing ``W_ASSUMPTION_UNVERIFIED`` code with fact-only
  details, and can only ADD warnings or DOWNGRADE ``success`` to
  ``success_with_warnings``. Never an upgrade, never a number change,
  never a suppression.
- ``narrative``: plain-language explanation + one suggested
  experiment for a computed result JSON. Every number in the model
  text must echo a value AND unit from the input JSON (exact float
  equality — rounding fails); any mismatch discards the narrative
  for a deterministic template built from JSON values only.

``cache`` stores raw responses as files (request metadata, SHA-256,
explicit ``live``/``replay``/``synthetic-fixture`` label) and replays
them fully offline with hash re-verification.

``live`` holds the user-verified request-body builder and the
response-content extractor (pure shapes, no I/O) that the helper
script uses; endpoint and model id stay caller-supplied arguments.

Stdlib only. No network anywhere in this subpackage: the live-cache
helper lives in ``scripts/`` (takes endpoint/model as arguments) and
is never imported here.
"""

from kineticlab.advisory.cache import (
    CACHE_KINDS,
    CACHE_LABELS,
    CACHE_VERSION,
    build_entry,
    entry_bytes,
    load_entry,
    replay_entry,
    response_digest,
    save_entry,
    validate_entry,
)
from kineticlab.advisory.live import build_chat_request, extract_content
from kineticlab.advisory.narrative import (
    NARRATIVE_VERSION,
    UNIT_VOCABULARY,
    Narrative,
    audit_narrative,
    parse_narrative,
    render_template,
    resolve_narrative,
)
from kineticlab.advisory.setup_review import (
    BLUR_SEVERITIES,
    SETUP_REVIEW_VERSION,
    SURFACED_CODE,
    SetupReview,
    apply_setup_advisory,
    map_flags_to_warnings,
    parse_setup_review,
)

__all__ = [
    "CACHE_KINDS",
    "CACHE_LABELS",
    "CACHE_VERSION",
    "BLUR_SEVERITIES",
    "NARRATIVE_VERSION",
    "SETUP_REVIEW_VERSION",
    "SURFACED_CODE",
    "UNIT_VOCABULARY",
    "Narrative",
    "SetupReview",
    "apply_setup_advisory",
    "audit_narrative",
    "build_chat_request",
    "build_entry",
    "extract_content",
    "entry_bytes",
    "load_entry",
    "map_flags_to_warnings",
    "parse_narrative",
    "parse_setup_review",
    "render_template",
    "replay_entry",
    "resolve_narrative",
    "response_digest",
    "save_entry",
    "validate_entry",
]
