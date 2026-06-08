"""Put `src/` on the path so tests import the `debate` package directly."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
