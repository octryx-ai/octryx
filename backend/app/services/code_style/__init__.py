"""The installation's code style: defined once, centrally, for the whole installation.

A style profile is data, set once for the installation and overridable per Workspace, repository and language
(``schema``, ``defaults``); every resolved value names where it comes from (``resolve``); ``store`` reads and writes
the levels. The platform checks the measurable rules itself (``workflow_runs.octryx.code_limits`` at a phase's Stop,
and the pipeline gate), gives the profile to every changing phase and to the reviewer as a checklist.
"""
