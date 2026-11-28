from __future__ import annotations

from tests.guards._legacy_words._build import concept, within

SHADOW_DECISION = concept(
    "'legacy': the platform's built-in policy decision that the Cedar policy engine is compared with in shadow "
    "mode and the test bench (stored as legacy_decision/legacy_reason, shown as 'existing check')",
    *within("backend/app/services/decisions/timeline.py", "_serialize",
            '"legacy": {"decision": record.legacy_decision, "reason": record.legacy_reason},'),
    *within("backend/app/services/devices/device_policy.py", "device_run_decision",
            "comparison = shadow_decision(POINT_DEVICE_DISPATCH, legacy, lambda: device_query(",
            "if not legacy.allowed:",
            "legacy = builtin_device_decision(section, rules, profile=profile, "
            "folder_allowlisted=folder_allowlisted)",
            ("return DispatchDecision.deny(_STATES.get(legacy.reason, STATE_DENIED), legacy.reason, decision_id)", 2)),
    *within("backend/app/services/policy_engine/decision_log.py", "serialize_decision",
            '"legacy": {"decision": row.legacy_decision, "reason": row.legacy_reason},'),
    *within("backend/app/services/policy_engine/impact.py", "impact",
            ('"legacy": answer["legacy"], "notes": answer["notes"]}', 2),
            'result = {"decision": "error", "determining": [], "error": error.code, "legacy": None, "notes": []}'),
    *within("backend/app/services/policy_engine/shadow.py", "_draft_blocking",
            "def _draft_blocking(query: PointQuery, legacy: LegacyDecision, runtime: PolicyRuntime) -> tuple[str, "
            "...]:",
            "if not runtime.draft_text or not legacy.allowed:"),
    *within("backend/app/services/policy_engine/shadow.py", "_outcome",
            "def _outcome(legacy: LegacyDecision, evaluation: Evaluation, query: PointQuery, runtime: "
            "PolicyRuntime) -> str:",
            "if evaluation.allowed == legacy.allowed:",
            "if legacy.allowed and custom_only:"),
    *within("backend/app/services/policy_engine/shadow.py", "shadow_decision",
            "_draft_blocking(built, legacy, runtime))",
            "memo = (runtime.key, point, memo_key, legacy.allowed) if memo_key is not None else None",
            "outcome = _outcome(legacy, evaluation, built, runtime)",
            "point: str, legacy: LegacyDecision, query: Callable[[], PointQuery], *, memo_key: Hashable | None = "
            "None",
            "record_decision(_entry(built, legacy, comparison, runtime, digest))"),
    *within("backend/app/services/policy_engine/shadow_record.py", "_entry",
            '"legacy_decision": _decision(legacy.allowed),',
            '"legacy_reason": str(legacy.reason or "")[:160] or None,',
            "def _entry(query: PointQuery, legacy: LegacyDecision, comparison: PolicyComparison, runtime: "
            "PolicyRuntime,"),
    *within("backend/app/services/policy_engine/test_bench.py", "_device_question",
            "legacy = (builtin_device_decision(device_runs_section(raw), rules, profile=profile, "
            "folder_allowlisted=folder)",
            ("return query, (legacy.allowed, legacy.reason) if legacy is not None else (False, loaded.reason)", 3)),
    *within("backend/app/services/policy_engine/test_bench.py", "_questions",
            'legacy = admission.builtin_decision(resource.get("alias"))',
            "legacy = builtin_seat_decision(loaded.policy, rules, level=level) if loaded.policy is not None else "
            "None",
            'legacy = builtin_tool_decision(str(resource["tool"]), section, params)',
            "legacy = evaluate_tool_check(loaded.policy, hook_input)",
            ('return model_query(admission, resource.get("alias"), principal=principal), (legacy.allowed, '
             "legacy.reason)", 2),
            ("return query, (legacy.allowed, legacy.reason)", 2),
            ("return query, (legacy.allowed, legacy.reason) if legacy is not None else (False, loaded.reason)", 3),
            ("return query, (legacy.decision != DECISION_DENY, legacy.rule_id or legacy.reason)", 3)),
    *within("backend/app/services/policy_engine/test_bench.py", "ask",
            ('"legacy": {"decision": "allow" if legacy[0] else "deny", "reason": legacy[1] or ""} if legacy else '
             "None,", 4),
            "query, legacy = await _questions(db, question, project, principal)"),
    *within("frontend/chat/src/admin/components/policyEngine/AdminPolicyTestBench.tsx", "AdminPolicyTestBench",
            ('{result.legacy ? <span className="policies__summary" data-testid="bench-legacy">existing check: '
             '{result.legacy.decision}{result.legacy.reason ? ` (${result.legacy.reason})` : ""}</span> : null}', 5)),
    *within("frontend/chat/src/admin/components/policyEngine/policyEngineBench.ts", "BenchResult",
            "legacy: { decision: string; reason: string } | null;"),
    *within("frontend/chat/src/admin/components/policyEngine/policyEngineBench.ts", "readBenchResult",
            ("const legacy = isRecord(raw.legacy) ? { decision: str(raw.legacy.decision), reason: "
             "str(raw.legacy.reason) } : null;", 4),
            "legacy,"),
    *within("frontend/chat/src/admin/components/policyEngine/policyEngineDecisions.ts", "decisionSentence",
            "const legacy = record.legacyDecision ? `; the existing check said "
            '${record.legacyDecision}${record.legacyReason ? ` (${record.legacyReason})` : ""}` : "";',
            "return `Cedar: ${record.decision}${why}${legacy}.`;"),
    *within("frontend/chat/src/admin/components/policyEngine/policyEngineDecisions.ts", "readDecision",
            ("const legacy = isRecord(raw.legacy) ? raw.legacy : {};", 3),
            "legacyDecision: str(legacy.decision),",
            "legacyReason: str(legacy.reason),"),
)
