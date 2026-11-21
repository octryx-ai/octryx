"""``python -m octryx_claude``: the same entry as the installed console script."""

import sys

from .entry import main

if __name__ == "__main__":
    sys.exit(main())
