"""Workspace preparation before a run's first agent phase ("Environment readiness").

``spec`` resolves the repository's declared environment, ``preparation`` is the ``workspace.prepare`` platform action
(server runtime now, device / terminal through their launcher's report), ``server_prepare`` prepares a server working
copy, ``readiness`` pauses a run whose test runner could not start in a phase.
"""
