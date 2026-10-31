"""End-to-end offline result assembly (KL-7.1, P-007 stage 1).

Module layout (one stage per concern, mirroring the pipeline):

- ``angles``: fit points + display angle series from bob records
  (source PTS preserved, exclusions explicit).
- ``build``: the ``assemble`` orchestrator — joins ingest,
  observation, geometry pins, fit, and result through unchanged
  public surfaces; owns states, assumptions, and the M2
  include/skip rule.
- ``export``: canonical result/diagnostics JSON + presentation
  angle-series CSV (KL-3.3 pattern).
- ``summary``: human-auditable ``summary.md`` rendered from the
  validated result + diagnostics (KL-7.3; numbers copied, never
  recomputed; export SHA-256 list included).

The reported fit is always M1 (pre-registered parsimony); M2 rides
the diagnostics as a cross-check. Gravity stays null without a
human-typed pivot length (U-2); a supplied length attaches through
``apply_pivot_length`` on the success paths only. The
fitter's synthetic-input label is dropped at the boundary with the
reason documented in ``build`` — fit.v1 carries no synthetic
wording (asserted in tests).

Stdlib only. No network. Deterministic.
"""

from kineticlab.assembly.angles import angle_series, build_fit_points
from kineticlab.assembly.build import (
    AMP_BOUNDS,
    ARTIFACT_HASH_KEYS,
    GAMMA_BOUNDS,
    GRID_N_GAMMA,
    GRID_N_OMEGA,
    MAX_REFINE,
    MIN_FIT_POINTS,
    NON_CRITICAL_WARNINGS,
    OMEGA_BOUNDS,
    PIVOT_LENGTH_BOUNDS_MM,
    REJECTION_STATE,
    apply_pivot_length,
    assemble,
    assemble_parts,
    m2_section,
)
from kineticlab.assembly.export import (
    ANGLE_CSV_COLUMNS,
    export_angles_csv,
    export_diagnostics_json,
    export_result_json,
    write_assembly_exports,
)
from kineticlab.assembly.summary import (
    HASHED_FILES,
    SUMMARY_FILENAME,
    render_summary_md,
)

__all__ = [
    "AMP_BOUNDS",
    "ANGLE_CSV_COLUMNS",
    "ARTIFACT_HASH_KEYS",
    "GAMMA_BOUNDS",
    "GRID_N_GAMMA",
    "GRID_N_OMEGA",
    "HASHED_FILES",
    "MAX_REFINE",
    "MIN_FIT_POINTS",
    "NON_CRITICAL_WARNINGS",
    "OMEGA_BOUNDS",
    "PIVOT_LENGTH_BOUNDS_MM",
    "REJECTION_STATE",
    "SUMMARY_FILENAME",
    "angle_series",
    "apply_pivot_length",
    "assemble",
    "assemble_parts",
    "build_fit_points",
    "export_angles_csv",
    "export_diagnostics_json",
    "export_result_json",
    "m2_section",
    "render_summary_md",
    "write_assembly_exports",
]
