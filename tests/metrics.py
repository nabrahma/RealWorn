"""Edge width metric for the v2.1 sharpness tests (PRD v2.1 "The edge width metric").

The implementation lives in the add-on (realworn/core/metrics.py) so the Sharpness Report
operator uses the same code; this module is the test-facing name the PRD refers to.
"""

from realworn.core.metrics import (GAUSSIAN_W_PER_SIGMA, boundary_length, disk, edge_report,  # noqa: F401
                                   edge_width, gaussian_blur, transition_area)
