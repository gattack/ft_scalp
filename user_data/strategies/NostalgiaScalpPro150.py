"""
NostalgiaScalpPro150 — NostalgiaScalpProOptimized run with 150 top-volume pairs.

Identical logic to NostalgiaScalpProOptimized; separate class name so backtest
outputs get distinct filenames (backtest_NostalgiaScalpPro150_YYYYMM.zip) and
don't conflict with the 90-pair results.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from NostalgiaScalpProOptimized import NostalgiaScalpProOptimized


class NostalgiaScalpPro150(NostalgiaScalpProOptimized):
    pass
