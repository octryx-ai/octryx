"""Shared turn start time for the standard loop runtime-error salvage tests."""

from datetime import datetime

# These salvage tests model one turn whose rows were all persisted after it started.
TURN_STARTED_AT = datetime(2000, 1, 1)
