"""Versioned result contracts, quality gates, and exports.

Observation-list exports land here in KL-3.3 (P-004) and the KL-4.x
quality layer (report-only facts plus rationale-backed thresholds
with trajectory/overlay artifacts) per master plan section 5.5;
full result assembly lands in KL-7.x (P-007). P-001 ships the
package boundary only.
"""

from kineticlab.result.observations import (
    CSV_COLUMNS,
    JSON_INDENT,
    TRAJECTORY_COLUMNS,
    export_observations_csv,
    export_observations_json,
    export_trajectory_csv,
    parse_observations_json,
)
from kineticlab.result.overlay import export_overlay_svg
from kineticlab.result.quality import (
    build_quality_report,
    export_quality_json,
    record_fill_ratio,
)
from kineticlab.result.thresholds import (
    AREA_MAX_STEP_RATIO,
    AREA_MIN_PX,
    FILL_MAX,
    FILL_MIN,
    JUMP_MAX_DIAGONALS_PER_STEP,
    assess_chain,
)

__all__ = [
    "AREA_MAX_STEP_RATIO",
    "AREA_MIN_PX",
    "CSV_COLUMNS",
    "FILL_MAX",
    "FILL_MIN",
    "JSON_INDENT",
    "JUMP_MAX_DIAGONALS_PER_STEP",
    "TRAJECTORY_COLUMNS",
    "assess_chain",
    "build_quality_report",
    "export_observations_csv",
    "export_observations_json",
    "export_quality_json",
    "export_overlay_svg",
    "export_trajectory_csv",
    "parse_observations_json",
    "record_fill_ratio",
]
