"""Oriented card geometry, calibration, and M-3 diagnostics (P-006).

Submodules:

- ``masks``: per-frame one-bit rasters re-decoded from raw wire
  files through the public observation codec chain (frozen modules
  reused, never modified).
- ``oriented``: PCA oriented rectangles from mask pixels
  (closed-form 2x2 eigen, deterministic).
- ``calibration``: KL-6.1 ``calibration.v1`` builder — explicit U-1
  dimensions, U-3 bound carried as an assumption, full assumption
  table with null+reason where unassessed.
- ``pivot``: M-3a arc-fit pivot localization with residual
  diagnostics (supersedes the M-2 demo placeholder in code).
- ``diagnostics``: M-3b corner jitter, M-3d geometric blur proxy,
  and bbox-overlap frames as pure descriptive data.
- ``export``: canonical JSON report bytes.

M-3e limitation (hollow ball / string mass vs point-mass rigid-rod
models) is documented in ``calibration.MODEL_LIMITATIONS`` and
carried in every calibration report; it is stated, never corrected.

Stdlib only. No network. Deterministic.
"""

from kineticlab.geometry.calibration import MODEL_LIMITATIONS, build_calibration
from kineticlab.geometry.diagnostics import (
    STATIONARY_BANDS_PX,
    TOP_RANK_COUNT,
    blur_proxy,
    corner_jitter,
    overlap_frames,
)
from kineticlab.geometry.export import report_bytes, save_report
from kineticlab.geometry.masks import FrameMask, decode_frame_masks
from kineticlab.geometry.oriented import (
    oriented_rectangle,
    oriented_rectangle_from_raster,
)
from kineticlab.geometry.pivot import TOP_RESIDUAL_COUNT, fit_arc

__all__ = [
    "MODEL_LIMITATIONS",
    "STATIONARY_BANDS_PX",
    "TOP_RANK_COUNT",
    "TOP_RESIDUAL_COUNT",
    "FrameMask",
    "blur_proxy",
    "build_calibration",
    "corner_jitter",
    "decode_frame_masks",
    "fit_arc",
    "oriented_rectangle",
    "oriented_rectangle_from_raster",
    "overlap_frames",
    "report_bytes",
    "save_report",
]
