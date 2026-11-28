from __future__ import annotations

from tests.guards._legacy_words._build import concept, within

DEPRECATED_FACT = concept(
    "'deprecated': a typed fact about the customer's software or documents (the DEPRECATED change type of "
    "knowledge change typing, deprecation evidence, titles marked deprecated in search)",
    *within("backend/app/services/engineering_knowledge/evidence_ledger.py", "_infer_fact_coverage_areas",
            'if any(term in haystack for term in ["removal", "removed", "deprecated", "deprecation", '
            '"breaking"]):'),
    *within("backend/app/services/engineering_knowledge/source_ingestion_audit.py", "_infer_coverage_areas",
            'if any(term in text for term in ["deprecated", "removal", "breaking"]):'),
    *within("backend/app/services/knowledge/eval/golden/change_typing_spring_boot.json", "<module>",
            ('{"id": "dep-jackson2", "text": "Jackson 2 support is deprecated and will be removed in a future '
             'release.", "expected": "DEPRECATED"},', 2),
            ('{"id": "dep-starter-web", "text": "The spring-boot-starter-web starter is deprecated in favour of '
             'spring-boot-starter-webmvc.", "expected": "DEPRECATED"},', 2)),
    *within("backend/app/services/knowledge/temporal/changes.py", "<module>",
            '("DEPRECATED", "DEFAULT_CHANGED"),',
            '("REQUIRES", "REMOVED", "RENAMED", "REPLACED_BY", "MOVED_TO", "DEPRECATED", "DEFAULT_CHANGED", '
            '"INTRODUCED")'),
    *within("backend/app/services/knowledge/temporal/profiles/change_records.json", "<module>",
            '"1. Use one of the provided fact types (REQUIRES, REMOVED, RENAMED, REPLACED_BY, DEPRECATED, '
            "MOVED_TO, DEFAULT_CHANGED, INTRODUCED) only when the text states that change for {product} "
            "{version}. Read each type's description with its Yes and No examples and choose the one type that "
            'fits.",',
            ('"description": "The subject should no longer be used in this version because the object takes its '
             'place. Yes:\\n \\"spring.http.client.connect-timeout is replaced by '
             'spring.http.clients.connect-timeout\\". No: a subject that is\\n only deprecated and still works '
             '(that is DEPRECATED)."', 2),
            ('"description": "The subject still works in this version but is deprecated and scheduled for '
             'removal, possibly in favour of\\n the object. Yes: \\"Jackson 2 support is deprecated and will be '
             'removed in a future release\\". No: a subject that\\n is already gone (that is REMOVED)."', 2),
            '"model": "Deprecated",',
            '"name": "DEPRECATED",'),
    *within("backend/app/tools/definitions/knowledge_evidence.py", "<module>",
            '"Default true: only typed changes (REMOVED, RENAMED, REPLACED_BY, DEPRECATED, "'),
    *within("frontend/chat/src/admin/components/workspaceKnowledge/KnowledgeChangesPanel.tsx", "ChangesForm",
            "Only typed change records (removed, renamed, replaced, deprecated, requires, moved, default changed, "
            "new)"),
    *within("frontend/chat/src/admin/components/workspaceKnowledge/search/searchFamilies.ts", "DEPRECATED",
            ("const DEPRECATED = /\\b(deprecated|obsolete|outdated|archived?|superseded)\\b/i;", 2)),
    *within("frontend/chat/src/admin/components/workspaceKnowledge/search/searchFamilies.ts", "isDeprecatedTitle",
            "return DEPRECATED.test(title);"),
    *within("frontend/chat/src/admin/components/workspaceKnowledge/search/searchFamilies.ts", "titleStem",
            '.replace(/[([]\\s*(deprecated|obsolete|outdated|archived?|superseded)\\s*[)\\]]/gi, " ")',
            '.replace(DEPRECATED, " ")'),
    *within("frontend/chat/src/chat/knowledge/relationshipPresenter.ts", "RELATION_LABELS",
            ('DEPRECATED: "deprecated",', 2)),
)


DEPRECATED_STATE = concept(
    "'deprecated': a stored lifecycle value of the MASH policy/change enums and the flow registry lifecycle",
    *within("backend/app/mash/master/models.py", "MashChangeLog",
            'Enum("created", "updated", "deprecated", "rolled_back", name="mash_change_type"),'),
    *within("backend/app/mash/master/models.py", "MashPolicy",
            'Enum("draft", "released", "deprecated", name="mash_policy_status"),'),
)
