"""FBD Lab — Free Body Diagram Laboratory."""

import re
from pathlib import Path

_toml = (Path(__file__).parent.parent / "pyproject.toml").read_text()
__version__ = re.search(r'version\s*=\s*"(.+?)"', _toml).group(1)
