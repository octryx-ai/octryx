"""``python -m octryx_claude.pet``: the pet's own entry (native Windows, where the launcher itself runs in WSL)."""

import sys

from .cli import main

sys.exit(main())
