"""KineticLab project tests (KL-0.3).

Written as stdlib `unittest` cases so the suite runs offline via
`python -m unittest` and under the canonical `python -m pytest` runner.
"""

import unittest
from pathlib import Path


def require_smoke(*paths):
    """Skip the calling test unless every Smoke/ path exists.

    KL-9.6 B1: most of ``Smoke/`` is gitignored (privacy, user
    decision 2026-10-30); only ``test_3.mp4`` and
    ``gemini_generated_video_8eaef52c.mp4`` are tracked (KL-10.6
    exception). A fresh clone must skip tests needing absent
    Smoke-backed files instead of failing them. The skip reason
    names the first missing path. Raises
    :class:`unittest.SkipTest`, which also works from
    ``setUpClass`` (skips the class) and inside a ``subTest``
    (skips just that cell).
    """
    for path in paths:
        if not Path(path).is_file():
            raise unittest.SkipTest(f"Smoke file absent: {path}")
