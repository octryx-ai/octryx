"""Flow graph (DAG) executor, split by concern.

Callers import from the module that defines a name. The modules here hold graph shape, node
execution, node-run persistence, run bookkeeping, the shared node loop and the execute / resume /
interrupted-resume / cancel entry points.
"""

from __future__ import annotations
