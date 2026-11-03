"""Truthful demo front door (KL-8.1, OG F8b).

Shared entry surface for the demo CLI (``python -m kineticlab
demo``) and the local web UI: pinned SAM replay -> advisory
replay -> assemble. No scientific logic lives here — every number
comes from existing public APIs (ingest, observation, advisory,
assembly); this module only sequences them and shapes
human-readable output.

Honesty rules (binding):

- The advisory replay runs against its RECORDED M-2-era input
  (``fixtures/advisory/inputs/narrative_input_result.json``),
  exactly as M-2 closure validated — the cached narrative was
  authored against that input, not against a fresh assembly
  result, and the replay says so. Stale flags are never applied
  to fresh results.
- Rejection chains are first-class outcomes: ``run_demo_chain``
  returns (never raises) whatever state ``assemble`` produces,
  and the status line names it.
- Demonstration only: a fresh user clip still needs a live SAM
  run this offline build does not perform (the web UI states
  this on its upload panel; see ``kineticlab.ui``).

Stdlib only. No network.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from kineticlab.advisory import (
    Narrative,
    SetupReview,
    apply_setup_advisory,
    load_entry,
    map_flags_to_warnings,
    replay_entry,
    resolve_narrative,
)
from kineticlab.assembly import SUMMARY_FILENAME, assemble
from kineticlab.ingest import extract_frame_records
from kineticlab.observation import parse_raw_fixture

CLIP_REL = "Smoke/demo_test.mp4"
RAW_BOB_REL = "fixtures/live/raw_bob_one_bit.txt"
RAW_CARD_REL = "fixtures/live/raw_card_one_bit.txt"
CALIBRATION_REL = "fixtures/geometry/calibration_live.json"
GEOMETRY_REPORT_REL = "fixtures/geometry/geometry_report_live.json"
CORRUPT_REPORT_REL = "fixtures/assembly/corrupt_geometry_report.json"
SETUP_ENTRY_REL = "fixtures/advisory/setup-review_20261028T081141Z.json"
NARRATIVE_ENTRY_REL = "fixtures/advisory/narrative_20261028T081237Z.json"
ADVISORY_INPUT_REL = "fixtures/advisory/inputs/narrative_input_result.json"

BOB_OBJECT_ID = "live-ball"
CARD_OBJECT_ID = "live-card"

EXPORT_FILENAMES = ("result.json", "diagnostics.json", "angles.csv",
                    SUMMARY_FILENAME)


def replay_sam_pins(repo_root: Path) -> dict[str, Any]:
    """Replay both pinned SAM raw fixtures through the public parser.

    Returns per-role record/valid counts plus the frame-table size.
    Raises the parser's own registered ``ContractError`` on any
    malformed pin — loud, never partial.
    """
    table = extract_frame_records(str(repo_root / CLIP_REL))
    roles = {}
    for key, rel, role, object_id in (
            ("bob", RAW_BOB_REL, "bob", BOB_OBJECT_ID),
            ("card", RAW_CARD_REL, "reference_card", CARD_OBJECT_ID)):
        records = parse_raw_fixture(str(repo_root / rel),
                                    object_role=role,
                                    object_id=object_id,
                                    frame_table=table,
                                    model_name="sam-3.1")
        roles[key] = {"raw": rel,
                      "records": len(records),
                      "valid": sum(1 for record in records
                                   if record.valid)}
    return {"clip": CLIP_REL, "frames": len(table), **roles}


def replay_advisory_pins(repo_root: Path) -> dict[str, Any]:
    """Replay both live advisory cache entries against recorded input.

    This is the M-2 closure path verbatim: the setup review maps to
    warnings applied to the recorded input's state, and the
    narrative resolves (model text or deterministic template) via
    the number-echo audit against that same recorded input. The
    recorded input predates KL-7 assembly values and is labeled as
    such — never re-claimed against fresh results.
    """
    setup_entry = load_entry(repo_root / SETUP_ENTRY_REL)
    narrative_entry = load_entry(repo_root / NARRATIVE_ENTRY_REL)
    recorded = json.loads(
        (repo_root / ADVISORY_INPUT_REL).read_text(encoding="utf-8"))
    review = replay_entry(setup_entry)
    if not isinstance(review, SetupReview):
        raise TypeError(
            f"{SETUP_ENTRY_REL} replayed to "
            f"{type(review).__name__}, not a setup review")
    mapped = map_flags_to_warnings(review, SETUP_ENTRY_REL)
    applied_warnings, applied_status = apply_setup_advisory(
        list(recorded["warnings"]), recorded["status"], review,
        SETUP_ENTRY_REL)
    narrative = replay_entry(narrative_entry)
    if not isinstance(narrative, Narrative):
        raise TypeError(
            f"{NARRATIVE_ENTRY_REL} replayed to "
            f"{type(narrative).__name__}, not a narrative")
    text, source = resolve_narrative(recorded, narrative)
    return {
        "setup": {
            "entry": SETUP_ENTRY_REL,
            "label": setup_entry["label"],
            "model": setup_entry["request"]["model"],
            "input": ADVISORY_INPUT_REL,
            "warnings_added": len(mapped),
            "codes": [warning.code for warning in mapped],
            "details": [warning.detail for warning in mapped],
            "status_before": recorded["status"],
            "status_after": applied_status,
            "warnings_after": len(applied_warnings),
        },
        "narrative": {
            "entry": NARRATIVE_ENTRY_REL,
            "label": narrative_entry["label"],
            "model": narrative_entry["request"]["model"],
            "input": ADVISORY_INPUT_REL,
            "source": source,
            "chars": len(text),
            "text": text,
        },
    }


def run_demo_chain(repo_root: Path, *, chain: str,
                   out_dir: Path) -> dict[str, Any]:
    """Assemble one pinned chain (success or rejection).

    ``chain`` is ``"success"`` (live geometry report) or
    ``"rejection"`` (the corrupt-report pin). Returns the assemble
    output plus ``written`` (the four export paths, asserted to
    exist), a one-line ``status_line`` naming the honest state,
    and the ``advisory`` replay (KL-8.3 additive payload; recorded
    M-2-era input, never merged into the fresh result).
    """
    if chain == "success":
        report_rel = GEOMETRY_REPORT_REL
    elif chain == "rejection":
        report_rel = CORRUPT_REPORT_REL
    else:
        raise ValueError(f"chain must be 'success' or 'rejection', "
                         f"got {chain!r}")
    out = assemble({
        "clip_path": str(repo_root / CLIP_REL),
        "raw_bob_path": str(repo_root / RAW_BOB_REL),
        "raw_card_path": str(repo_root / RAW_CARD_REL),
        "calibration_path": str(repo_root / CALIBRATION_REL),
        "geometry_report_path": str(repo_root / report_rel),
        "out_dir": str(out_dir),
    })
    written = [out_dir / name for name in EXPORT_FILENAMES]
    missing = [str(path) for path in written if not path.is_file()]
    if missing:
        raise RuntimeError("assemble did not write: "
                           + ", ".join(missing))
    out["written"] = [str(path) for path in written]
    out["status_line"] = demo_status_line(chain, out["result"])
    # The CLI keeps its own earlier replay call so the F8b print
    # order (SAM -> advisory -> assemble) survives; this copy
    # serves API consumers (the web UI Evidence tab).
    out["advisory"] = replay_advisory_pins(repo_root)
    return out


def demo_status_line(chain: str, result: dict[str, Any]) -> str:
    """One honest status line for a demo chain result.

    Names the chain, the status, the measurement (copied fields),
    and the canonical relative export dir — never an absolute
    path (KL-8.3 design review; actual locations print on the
    CLI's ``wrote:`` lines and the UI's export links).
    """
    status = result.get("status")
    quantity = result.get("identifiable_quantity") or {}
    name = quantity.get("name")
    value = quantity.get("value")
    unit = quantity.get("unit")
    if value is None:
        measurement = "value null"
    else:
        measurement = f"{name} = {value!r} {unit}"
    reasons = result.get("reject_reasons") or []
    codes = ",".join(reason.get("code", "?") for reason in reasons)
    suffix = f" ({codes})" if codes else ""
    return (f"demo {chain} chain: {status} — {measurement}{suffix} "
            f"({len(EXPORT_FILENAMES)} exports in "
            f"demo_out/{chain})")
