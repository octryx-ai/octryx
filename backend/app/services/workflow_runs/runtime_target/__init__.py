"""Where a workflow run executes: its runtime target.

``target`` parses, validates and stores the target chosen at start (``server``, ``device {device_id, folder,
profile}``, ``terminal``); ``device_wait`` holds a run whose device is offline (``waiting_for_device``) and resumes it
when the device connects; ``switch`` is the explicit run action that changes the target and prepares the new runtime;
``send_guard`` refuses a chat message on the run's thread that would execute somewhere else.
"""
