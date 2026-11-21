"""Content routing as policy: the enforcement points that scan model requests and tool results.

Detectors find (``services/content_detection``); Cedar policies decide (``policy_engine.content_points``). This
package builds the scanned segments of a request, asks the policy engine and turns its answer into the outcome
an enforcement point applies.
"""
