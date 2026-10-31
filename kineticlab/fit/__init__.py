"""Bounded pendulum fits (M1, then M2) with diagnostics.

Deterministic synthetic trajectories land here in KL-5.1 (P-005):
``kineticlab.fit.synthetic`` generates seeded ideal/damped test
data (closed-form small-angle curves, not integrated ODEs) with
ground truth for the estimator stages. KL-5.2 adds the bounded M1
fit (``kineticlab.fit.m1``): separable omega-grid least squares
with golden-section refinement, honest converged/non-converged
states, and ``fit.v1`` records reporting ``g_over_l = omega^2``
under the synthetic TEST convention. KL-5.3 adds the bounded M2
fit (``kineticlab.fit.m2``): separable (omega, gamma) grid least
squares with alternating golden-section refinement, registered
mismatch/non-convergence/bound warnings, and M2 ``fit.v1``
records. Uncertainty (KL-5.4) and tolerance verdicts (KL-5.4) are
not implemented yet. P-001 ships the package boundary only.
"""

from kineticlab.fit.m1 import (
    DESIGN_SINGULAR_REL_TOL,
    OMEGA_REFINE_TOL,
    RECOVERY_TOL_AMPLITUDE_RAD,
    RECOVERY_TOL_OMEGA_PER_S,
    RECOVERY_TOL_PHASE_RAD,
    TERMINATION_BUDGET_EXHAUSTED,
    TERMINATION_DEGENERATE_DESIGN,
    TERMINATION_FLAT_OBJECTIVE,
    TERMINATION_TOLERANCE_MET,
    TEST_CONVENTION_NOTE,
    export_fit_json,
    fit_m1,
    parse_fit_json,
)
from kineticlab.fit.m2 import (
    GAMMA_REFINE_TOL,
    MISMATCH_MAX_DECAY,
    RECOVERY_TOL_GAMMA_PER_S,
    fit_m2,
)
from kineticlab.fit.matrix import (
    MAX_CELLS,
    export_matrix_json,
    parse_matrix_json,
    run_matrix,
)
from kineticlab.fit.synthetic import (
    CSV_COLUMNS,
    DISCLAIMER,
    GENERATOR_NAME,
    JSON_INDENT,
    MAX_SAMPLES,
    export_synthetic_csv,
    export_trajectory_json,
    generate_trajectory,
    parse_trajectory_json,
)
from kineticlab.fit.uncertainty import (
    BOOTSTRAP_SEED,
    N_BOOT,
    omega_interval,
)

__all__ = [
    "BOOTSTRAP_SEED",
    "CSV_COLUMNS",
    "DESIGN_SINGULAR_REL_TOL",
    "DISCLAIMER",
    "GAMMA_REFINE_TOL",
    "GENERATOR_NAME",
    "JSON_INDENT",
    "MAX_CELLS",
    "MAX_SAMPLES",
    "MISMATCH_MAX_DECAY",
    "N_BOOT",
    "OMEGA_REFINE_TOL",
    "RECOVERY_TOL_GAMMA_PER_S",
    "RECOVERY_TOL_AMPLITUDE_RAD",
    "RECOVERY_TOL_OMEGA_PER_S",
    "RECOVERY_TOL_PHASE_RAD",
    "TERMINATION_BUDGET_EXHAUSTED",
    "TERMINATION_DEGENERATE_DESIGN",
    "TERMINATION_FLAT_OBJECTIVE",
    "TERMINATION_TOLERANCE_MET",
    "TEST_CONVENTION_NOTE",
    "export_fit_json",
    "export_matrix_json",
    "export_synthetic_csv",
    "export_trajectory_json",
    "fit_m1",
    "fit_m2",
    "generate_trajectory",
    "omega_interval",
    "parse_fit_json",
    "parse_matrix_json",
    "parse_trajectory_json",
    "run_matrix",
]
